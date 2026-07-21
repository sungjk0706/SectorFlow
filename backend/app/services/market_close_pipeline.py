# -*- coding: utf-8 -*-
"""
장마감 후 데이터 캐시 파이프라인 — 핵심 로직.

KRX/NXT 장마감 후 실시간 통신 구독 해지 → REST 확정 데이터 조회 → 캐시 저장.
daily_time_scheduler.py 타이머 콜백에서 호출된다.
"""
from __future__ import annotations
import asyncio
import time
from typing import TYPE_CHECKING
import logging
from backend.app.core.broker_providers import AuthProvider
if TYPE_CHECKING:
    from backend.app.core.stock_filter import StockFilterEvaluation
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    is_nxt_enabled,
    get_ws_subscribe_code,
)
from backend.app.services.engine_ws_reg import build_0b_remove_payloads
from backend.app.core.trading_calendar import (
    get_current_trading_day_str,
    get_previous_trading_day_str,
)
from backend.app.services import engine_state
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
from backend.app.core.logger import log_progress, log_progress_end
from backend.app.db.json_utils import dumps

logger = logging.getLogger(__name__)


def _broadcast_confirmed_progress(
    current: int, total: int, *, message: str = "", eta_sec: float = 0, step: int = 0,
    failed_count: int = 0,
    _loop: "asyncio.AbstractEventLoop | None" = None,
) -> None:
    """확정 데이터 조회 진행률 → confirmed-progress 실시간 통신 전송 (헤더 칩 표시용).

    _loop가 전달된 경우(스레드풀 내부 호출): _loop.call_soon_threadsafe()로 메인 루프에 큐 적재.
    _loop가 없는 경우(async context 직접 호출): q.put_nowait() 사용.
    """
    try:
        payload = {
            "_v": 1,
            "current": current,
            "total": total,
            "done": current >= total and total > 0,
            "message": message,
            "eta_sec": eta_sec,
            "status": "confirmed",
            "step": step,
            "failed_count": failed_count,
        }
        from backend.app.services.core_queues import get_broadcast_queue
        
        if current >= total:
            if failed_count > 0:
                payload["status"] = "partial"
            else:
                payload["status"] = "completed"

        q = get_broadcast_queue()
        data = {"type": "confirmed-progress", "data": payload}
        
        if _loop is not None:
            _loop.call_soon_threadsafe(lambda: q.put_nowait(data) if not q.full() else None)
        else:
            if not q.full():
                q.put_nowait(data)
    except Exception as exc:
        logger.warning("[시스템] 전송 실패: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 종목 분류 헬퍼
# ---------------------------------------------------------------------------

def _get_krx_only_codes() -> list[str]:
    """전종목 마스터 캐시에서 KRX 단독 종목(nxt_enable=False)만 추출.

    Returns:
        6자리 정규화된 KRX 단독 종목코드 리스트 (중복 없음).
    """
    result: list[str] = []
    seen: set[str] = set()

    sources: list[set | dict | list] = []
    # 전종목 마스터 캐시의 "_subscribed" 사용
    subscribed_codes = {cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_subscribed", False)}
    if subscribed_codes:
        sources.append(subscribed_codes)
    # _radar_cnsr_order 삭제

    for src in sources:
        for raw_cd in list(src):
            base = _base_stk_cd(raw_cd)
            if not base or base in seen:
                continue
            seen.add(base)
            if not is_nxt_enabled(base):
                result.append(base)

    # 레이아웃 캐시에서 seen에 없는 KRX 단독 종목 추가 (항상 순회)
    layout = engine_state.state.integrated_system_settings_cache["sector_stock_layout"]
    for kind, val in layout:
        if kind == "code":
            base = _base_stk_cd(val)
            if not base or base in seen:
                continue
            seen.add(base)
            if not is_nxt_enabled(base):
                result.append(base)

    return result


# ---------------------------------------------------------------------------
# KRX 단독 종목 REMOVE
# ---------------------------------------------------------------------------

async def remove_krx_only_stocks() -> dict:
    """KRX 단독 종목(nxt_enable=False)만 선택적 REMOVE.

    Returns:
        {"removed": int, "failed": int, "skipped": bool}
    """
    # 0B REMOVE 페이로드 전송 — 증권사별 ACK 지원 여부로 분기
    ws = engine_state.state.connector_manager or engine_state.state.active_connector
    if not ws or not ws.is_connected():
        logger.warning("[스케줄] KRX 장마감 구독해지 생략 — 실시간 미연결")
        return {"removed": 0, "failed": 0, "skipped": True}

    krx_codes = _get_krx_only_codes()
    if not krx_codes:
        logger.info("[스케줄] KRX 장마감 구독해지 대상 없음")
        return {"removed": 0, "failed": 0, "skipped": False}

    # 종목코드를 실시간 통신 구독 형식으로 변환하여 페이로드 생성
    ws_codes = [get_ws_subscribe_code(cd) for cd in krx_codes]
    payloads = build_0b_remove_payloads(ws_codes)

    if not payloads:
        return {"removed": 0, "failed": 0, "skipped": False}

    removed = 0
    failed = 0
    chunk_size = 100

    # 증권사별 ACK 지원 여부 확인
    supports_ack = ws.supports_ack() if hasattr(ws, 'supports_ack') else True

    for ci, payload in enumerate(payloads):
        chunk = krx_codes[ci * chunk_size : (ci + 1) * chunk_size]
        try:
            if supports_ack:
                # ACK 지원 증권사 (키움): ACK 대기
                from backend.app.services.engine_ws import _ws_send_reg_unreg_and_wait_ack
                ack_ok, rc = await _ws_send_reg_unreg_and_wait_ack(payload, sender=ws)
            else:
                # ACK 미지원 증권사 (LS): 즉시 전송 (응답 대기 없음)
                from backend.app.services.engine_ws import _ws_send_remove_fire_and_forget
                ack_ok = await _ws_send_remove_fire_and_forget(payload, sender=ws)
                rc = ""
        except Exception as exc:
            logger.warning(
                "[스케줄] KRX 장마감 구독해지 %d/%d 오류: %s",
                ci + 1, len(payloads), exc,
                exc_info=True,
            )
            failed += len(chunk)
            continue

        if ack_ok:
            # 성공 — 전종목 마스터 캐시에서 "_subscribed" 제거
            for cd in chunk:
                if cd in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
            removed += len(chunk)
            if supports_ack:
                logger.info(
                    "[스케줄] KRX 장마감 구독해지 %d/%d 완료 — %d종목 (rc=%s)",
                    ci + 1, len(payloads), len(chunk), rc,
                )
            else:
                logger.info(
                    "[스케줄] KRX 장마감 구독해지 %d/%d 완료 — %d종목 (ACK 미지원)",
                    ci + 1, len(payloads), len(chunk),
                )
        else:
            # 실패 — 전종목 마스터 캐시의 "_subscribed" 유지 + 경고
            failed += len(chunk)
            logger.warning(
                "[스케줄] KRX 장마감 구독해지 %d/%d 실패 — %d종목 유지",
                ci + 1, len(payloads), len(chunk),
            )

    logger.info(
        "[스케줄] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목",
        removed, failed,
    )
    return {"removed": removed, "failed": failed, "skipped": False}


# ---------------------------------------------------------------------------
# 단일 벌크 트랜잭션 헬퍼 함수
# ---------------------------------------------------------------------------

async def execute_unified_rolling_and_save(
    confirmed: dict[str, dict],
    name_map: dict[str, str] | None = None,
    *,
    qry_dt: str = "",
) -> bool:
    """모든 정산 데이터를 메모리에서 연산 후 단일 트랜잭션으로 DB 및 메모리에 저장.

    Args:
        confirmed: {종목코드: {cur_price, change, change_rate, trade_amount, high_price, high_5d_price}}
        name_map: {6자리 종목코드: 종목명} — 종목명 보정용
        qry_dt: API 조회일 (YYYYMMDD) = 가장 최근 확정된 거래일.
            stock_5d_bars의 dt로 저장되며, master_stocks_table.date에도 동일 기준 적용 (P10/P22).

    Returns:
        저장 성공 여부.
    """
    from backend.app.db.database import get_db_connection, get_db_lock

    # date_str = "데이터 기준일" — qry_dt(가장 최근 확정된 거래일 = 소속 거래일의 직전 거래일) 우선 (P10/P22).
    # qry_dt는 항상 직전 거래일이므로, 장 전/장 후 실행 모두 date=직전 거래일(예: 07-14)이 저장됨.
    # 이 값이 master_stocks_table.date와 메모리 캐시 date에 사용되며,
    # retry_pipeline_catchup_after_bootstrap의 스킵 판단도 동일 기준(직전 거래일)으로 비교함 (P10 SSOT).
    date_str = qry_dt or get_current_trading_day_str()
    _nm = name_map or {}

    if not date_str:
        logger.warning("[데이터] 저장 실패 — 현재 거래일 확인 불가 (P20 폴백 금지)")
        return False

    async with get_db_lock():
        conn = await get_db_connection()

        try:
            # 1. 당일 5일봉 행 INSERT OR REPLACE 파라미터 빌드 (rolling 제거 — 세로 행 구조 P24)
            master_bulk_params = []
            bars_bulk_params = []
            codes_to_recalc = []

            for raw_cd, detail in confirmed.items():
                nk = _base_stk_cd(raw_cd)
                if not nk:
                    continue

                # 당일 데이터 추출
                today_amt = int(detail["trade_amount"]) if detail.get("trade_amount") is not None else None
                today_high = int(detail.get("high_price") or detail.get("cur_price") or 0)
                cur_price = int(detail.get("cur_price") or 0)
                change = int(detail.get("change") or 0)
                change_rate = float(detail["change_rate"]) if detail.get("change_rate") is not None else None

                # stock_5d_bars.dt는 API가 반환한 일봉의 실제 거래일을 우선 사용 (P10/P22)
                # fetch_ka10081_daily_price가 latest 일봉의 dt를 반환 — 장마감 전 실행 시
                # API가 어제 일봉을 latest로 반환하므로, 달력 오늘(qry_dt)을 dt로 쓰면
                # 어제 값을 오늘 행으로 기록하는 중복이 발생함.
                bar_dt = str(detail.get("dt") or "").strip() or qry_dt or date_str
                if not bar_dt:
                    logger.warning("[데이터] %s 행 저장 생략 — dt 누락 (P20 폴백 금지)", nk)
                    continue
                # 안전망: 소속 거래일 자체(미확정 당일) 행은 저장 차단 (P22 데이터 정합성)
                # qry_dt를 직전 거래일로 설정했으므로 정상 경로에서는 발생하지 않으나,
                # API가 당일 행을 반환하는 예외 케이스를 방어.
                current_td = get_current_trading_day_str()
                if bar_dt == current_td:
                    logger.warning(
                        "[데이터] %s 행 저장 생략 — 소속 거래일(미확정) 행 감지 (bar_dt=%s, P22)",
                        nk, bar_dt,
                    )
                    continue

                # 당일 세로 행 파라미터 (INSERT OR REPLACE — 같은 날 재실행 시 자동 덮어쓰기 P22)
                bars_bulk_params.append((nk, bar_dt, today_amt, today_high))
                codes_to_recalc.append(nk)

                # 전종목 마스터 테이블 market 정보 조회
                stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)

                master_bulk_params.append((
                    nk, stk_nm, cur_price, change, change_rate,
                    today_amt, 0, 0, date_str  # avg_5d/high_5d는 아래에서 재계산 후 갱신
                ))

                # 메모리 캐시 동시 갱신 (avg_5d/high_5d는 아래에서 재계산 후 갱신)
                if nk in engine_state.state.master_stocks_cache:
                    entry = engine_state.state.master_stocks_cache[nk]
                    entry.update({
                        "cur_price": cur_price,
                        "change": change,
                        "change_rate": change_rate,
                        "trade_amount": today_amt,
                        "date": date_str,
                        "status": "active"
                    })
                    if stk_nm and stk_nm != nk:
                        entry["name"] = stk_nm

            # 2. 단일 트랜잭션 내 벌크 실행
            # 미확정 당일(미래) 행 정리 — qry_dt보다 큰 dt 행 삭제 (P22 데이터 정합성)
            # 기존 07-15 미확정 행이 잔존하면 avg_5d/high_5d 재계산이 왜곡되므로
            # INSERT OR REPLACE 전에 먼저 삭제.
            await conn.execute("DELETE FROM stock_5d_bars WHERE dt > ?", (qry_dt,))
            # 5일봉 세로 행 적재 (당일 1행씩 INSERT OR REPLACE)
            if bars_bulk_params:
                await conn.executemany("""
                    INSERT OR REPLACE INTO stock_5d_bars
                    (code, dt, trade_amount, high_price)
                    VALUES (?, ?, ?, ?)
                """, bars_bulk_params)

            # 3. avg_5d_trade_amount, high_5d_price 재계산 — stock_5d_bars에서 종목당 최근 5행 (P10 SSOT)
            recalc_params = []
            if codes_to_recalc:
                placeholders = ",".join("?" for _ in codes_to_recalc)
                cursor = await conn.execute(f"""
                    SELECT code, trade_amount, high_price
                    FROM stock_5d_bars
                    WHERE code IN ({placeholders})
                    ORDER BY dt DESC
                """, codes_to_recalc)
                rows = await cursor.fetchall()
                # 종목별 최근 5행 집계
                from collections import defaultdict
                by_code: dict[str, list] = defaultdict(list)
                for r in rows:
                    by_code[r["code"]].append(r)
                for nk in codes_to_recalc:
                    recent = by_code.get(nk, [])[:5]
                    valid_amts = [r["trade_amount"] for r in recent if r["trade_amount"] is not None and r["trade_amount"] > 0]
                    avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else 0
                    valid_highs = [r["high_price"] for r in recent if r["high_price"] is not None and r["high_price"] > 0]
                    high_5d = max(valid_highs) if valid_highs else 0
                    recalc_params.append((avg_5d, high_5d, nk))
                    # 메모리 캐시 갱신
                    if nk in engine_state.state.master_stocks_cache:
                        engine_state.state.master_stocks_cache[nk]["avg_5d_trade_amount"] = avg_5d
                        engine_state.state.master_stocks_cache[nk]["high_5d_price"] = high_5d

            # 마스터 테이블 적재 (UPSERT)
            if master_bulk_params:
                # 기존 market 정보 보존을 위해 먼저 조회
                cursor = await conn.execute("SELECT code, market FROM master_stocks_table")
                mkt_rows = await cursor.fetchall()
                mkt_map = {r["code"]: r["market"] for r in mkt_rows}

                # recalc 결과를 master_bulk_params에 반영
                recalc_map = {p[2]: (p[0], p[1]) for p in recalc_params}
                updated_params = []
                for params in master_bulk_params:
                    code = params[0]
                    avg_5d, high_5d = recalc_map.get(code, (0, 0))
                    market = mkt_map.get(code, "")
                    # params: (code, name, cur_price, change, change_rate, today_amt, 0, 0, date_str)
                    updated_params.append((params[0], params[1], params[2], params[3], params[4],
                                           params[5], avg_5d, high_5d, params[8], market))

                await conn.executemany("""
                    INSERT INTO master_stocks_table
                    (code, name, cur_price, change, change_rate, trade_amount, avg_5d_trade_amount, high_5d_price, date, market)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        cur_price = excluded.cur_price,
                        change = excluded.change,
                        change_rate = excluded.change_rate,
                        trade_amount = excluded.trade_amount,
                        avg_5d_trade_amount = excluded.avg_5d_trade_amount,
                        high_5d_price = excluded.high_5d_price,
                        date = excluded.date,
                        market = excluded.market
                """, updated_params)

            await conn.commit()
            logger.info("[데이터] 저장 완료 — 5일봉 세로 행: %d종목, 전종목 마스터 테이블: %d종목", len(bars_bulk_params), len(master_bulk_params))
            return True

        except Exception as e:
            await conn.rollback()
            logger.warning("[데이터] 저장 실패: %s", e, exc_info=True)
            raise e


async def _apply_confirmed_to_memory(
    confirmed: dict[str, dict],
    strength: dict[str, float],
    name_map: dict[str, str] | None = None,
    confirmed_codes: set[str] | None = None,
) -> int:
    """확정 데이터를 메모리 캐시에 반영. 0값은 기존 데이터를 덮지 않음.

    Args:
        confirmed: {종목코드: {cur_price, change, change_rate, sign, volume, trade_amount, prev_close}}
        strength: {종목코드: 체결강도 float}
        name_map: {6자리 종목코드: 종목명} — 전종목 통합 조회(ka10099)에서 조회한 매핑. 있으면 모든 엔트리 종목명 갱신.
        confirmed_codes: 매매적격 종목 코드 집합 — 이 외 코드는 메모리 캐시에 반영하지 않음 (SSOT).

    Returns:
        반영된 종목 수.
    """
    _nm = name_map or {}
    pending: dict = engine_state.state.master_stocks_cache

    updated = 0

    # SQLite DB에서 한 번에 모든 매핑 조회 (1회 쿼리 수행)
    from backend.app.db.database import get_db_connection
    db_mapping = {}
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()
        await cursor.execute("SELECT code, sector FROM master_stocks_table")
        rows = await cursor.fetchall()
        for r in rows:
            if r["code"] and r["sector"]:
                db_mapping[r["code"]] = r["sector"]
    except Exception as e:
        logger.warning("[데이터] 전체 매핑 DB 조회 실패: %s", e)

    for raw_cd, detail in confirmed.items():
        nk = _base_stk_cd(raw_cd)
        if not nk:
            continue
        # SSOT: confirmed_codes 기준으로만 메모리 캐시에 반영
        if confirmed_codes and nk not in confirmed_codes:
            continue

        entry = pending.get(nk)
        if entry is None:
            # 엔트리 없으면 새로 생성
            from backend.app.services.engine_strategy_core import make_detail
            px = int(detail.get("cur_price") or 0)
            stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)
            # sector는 DB에서 조회 (custom_sectors 기반 동기화 유지)
            sec = db_mapping.get(_base_stk_cd(raw_cd)) or "미분류"
            entry = make_detail(
                nk, stk_nm, px,
                str(detail.get("sign") or "3"),
                int(detail.get("change") or 0),
                float(detail["change_rate"]) if detail.get("change_rate") is not None else None,
                trade_amount=int(detail["trade_amount"]) if detail.get("trade_amount") is not None else None,
                sector=sec,
            )
            entry["status"] = "active"
            entry["base_price"] = px
            entry["target_price"] = px
            entry["captured_at"] = ""
            entry["reason"] = "확정 데이터 조회"
            pending[nk] = entry
            # _radar_cnsr_order 삭제: 전종목 마스터 캐시의 "_subscribed" 사용
            if nk in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[nk]["_subscribed"] = True
            updated += 1
            continue

        entry["status"] = "active"

        # cur_price
        px = int(detail.get("cur_price") or 0)
        entry["cur_price"] = px

        # change
        change = int(detail.get("change") or 0)
        entry["change"] = change

        # change_rate
        rate = float(detail["change_rate"]) if detail.get("change_rate") is not None else None
        entry["change_rate"] = rate

        # sign
        sign = str(detail.get("sign") or "").strip()
        if sign:
            entry["sign"] = sign

        # trade_amount
        amt = int(detail["trade_amount"]) if detail.get("trade_amount") is not None else None
        entry["trade_amount"] = amt

        # strength (from separate dict)
        str_val = strength.get(raw_cd) or strength.get(nk)
        if str_val is not None:
            try:
                strength_str = f"{float(str_val):.2f}"
                entry["strength"] = strength_str
            except (ValueError, TypeError):
                pass

        # name (from name_map)
        mapped_nm = _nm.get(_base_stk_cd(raw_cd))
        if mapped_nm:
            entry["name"] = mapped_nm

        updated += 1

    logger.info("[스케줄] 확정 데이터 메모리 반영 — %d종목", updated)
    return updated


# ---------------------------------------------------------------------------
# 확정 후 v2 캐시 롤링 파이프라인 (daily_time_scheduler.py에서 이동)
# ---------------------------------------------------------------------------

async def _run_post_confirmed_pipeline(eligible_codes: set[str] | None = None) -> None:
    """
    전종목 1일봉챠트 시세 조회(ka10081) 도입으로 5일 거래대금 및 최고가를 즉시 추출하므로,
    기존의 복잡한 v2 캐시 롤링 갱신 로직은 제거되었습니다.
    단순히 최종 스냅샷 및 캐시를 저장합니다.
    """
    try:
        await _save_confirmed_cache(eligible_codes=eligible_codes)
        logger.info("[스케줄] 확정 후 파이프라인 완료 (롤링 로직 생략)")
    except Exception as exc:
        logger.warning("[스케줄] 확정 후 파이프라인 오류: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 확정 데이터 디스크 캐시 저장
# ---------------------------------------------------------------------------

async def _save_confirmed_cache(
    skip_codes: set[str] | None = None,
    name_map: dict[str, str] | None = None,
    eligible_codes: set[str] | None = None,
) -> bool:
    """현재 메모리 데이터를 전종목 마스터 테이블로 디스크 저장.

    저장 직전에 종목명 캐시를 참조하여 name 필드를 보정한다.
    execute_unified_rolling_and_save가 이미 처리한 종목은 skip_codes로 제외하여 중복 저장 방지.
    eligible_codes가 주어지면 해당 종목만 저장 (confirmed_codes 기반 단일 소스 진리).

    Args:
        skip_codes: execute_unified_rolling_and_save에서 이미 처리한 종목 코드 집합
        eligible_codes: 매매적격 종목 코드 집합 (이 외 종목은 저장하지 않음)

    Returns:
        저장 성공 여부.
    """
    pending: dict = engine_state.state.master_stocks_cache
    if not pending:
        logger.warning("[스케줄] 저장할 데이터(전종목 마스터 캐시)가 비어있음 — 데이터 저장 생략")
        return False

    # 종목명 보정은 불필요: 전종목 마스터 캐시에 이미 name 필드 포함됨

    all_target_codes = set(pending.keys())
    # eligible_codes가 주어지면 confirmed_codes 외 종목 저장 방지 (단일 소스 진리)
    if eligible_codes:
        all_target_codes = all_target_codes & eligible_codes

    rows = [
        (cd, dict(detail))
        for cd, detail in pending.items()
        if cd in all_target_codes and detail.get("status") in ("active", "exited")
    ]
    if not rows:
        logger.warning("[스케줄] 저장 가능한 종목 없음 — 저장데이터 저장 생략")
        return False

    try:
        # DB 저장 전 avg_5d 유효성 체크
        if sum(1 for stock in pending.values() if int(stock.get("avg_5d_trade_amount", 0) or 0) > 0) < 100:
            logger.warning("[스케줄] DB 저장 전 5일 평균 거래대금 비정상 — 백그라운드 갱신 예정")

        # ── 전종목 마스터 테이블 저장 (Phase 1.2) ──
        try:
            from backend.app.db.database import get_db_connection

            conn = await get_db_connection()
            # date_str = 메모리 캐시의 date 우선 (execute_unified_rolling_and_save가 설정한 값),
            # 없으면 현재 거래일 (P10 — execute_unified_rolling_and_save와 동일 기준)
            _cached_date = ""
            if pending:
                _first = next(iter(pending.values()))
                _cached_date = _first.get("date", "")
            date_str = _cached_date or get_current_trading_day_str()

            # 전종목 마스터 테이블에서 각 종목의 market 정보 가져오기
            cursor = await conn.execute("SELECT code, market FROM master_stocks_table")
            mkt_rows = await cursor.fetchall()
            mkt_map = {r["code"]: r["market"] for r in mkt_rows}

            # 대상 종목: pending 종목 중 skip_codes 제외 (execute_unified_rolling_and_save에서 이미 처리)
            # SSOT: eligible_codes가 주어지면 해당 종목만 저장 (덮어쓰기 버그 수정)
            _skip = skip_codes or set()
            if eligible_codes:
                all_target_codes = (set(pending.keys()) & eligible_codes) - _skip
            else:
                all_target_codes = set(pending.keys()) - _skip

            if not all_target_codes:
                logger.info("[스케줄] 생략 종목으로 인해 저장할 종목 없음 — 저장 생략")
                return True

            for base_cd in all_target_codes:
                detail = pending.get(base_cd) or {}
                cd = base_cd

                stk_nm = detail.get("name")
                if not stk_nm or stk_nm == cd:
                    if name_map:
                        stk_nm = name_map.get(_base_stk_cd(cd), cd)
                    else:
                        stk_nm = cd

                # 1) 전종목 마스터 테이블에 저장 (UPSERT 적용 - 기존 사용자 커스텀 업종 보존)
                await conn.execute("""
                    INSERT INTO master_stocks_table
                    (code, name, market, sector, cur_price, change, change_rate,
                     trade_amount, avg_5d_trade_amount, high_5d_price, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        market = excluded.market,
                        sector = CASE WHEN master_stocks_table.sector IS NOT NULL AND master_stocks_table.sector != '' AND master_stocks_table.sector != '미분류' THEN master_stocks_table.sector ELSE excluded.sector END,
                        cur_price = excluded.cur_price,
                        change = excluded.change,
                        change_rate = excluded.change_rate,
                        trade_amount = excluded.trade_amount,
                        avg_5d_trade_amount = excluded.avg_5d_trade_amount,
                        high_5d_price = excluded.high_5d_price,
                        date = excluded.date
                """, (
                    cd,
                    stk_nm,
                    mkt_map.get(_base_stk_cd(cd), ""),
                    detail.get("sector", "미분류"),
                    detail.get("cur_price", 0),
                    detail.get("change", 0),
                    detail.get("change_rate", 0.0),
                    detail.get("trade_amount", 0),
                    detail.get("avg_5d_trade_amount", 0),
                    detail.get("high_5d_price", 0),
                    date_str
                ))

            await conn.commit()
            logger.info("[스케줄] 전종목 마스터 테이블 통합 저장 완료 — %d종목 (날짜=%s, 생략=%d)", len(all_target_codes), date_str, len(_skip))
        except Exception as e:
            if 'conn' in locals():
                await conn.rollback()
            logger.warning("[스케줄] DB 저장 실패 (전종목 마스터 테이블): %s", e, exc_info=True)

        return True
    except Exception as exc:
        logger.warning("[스케줄] 확정 데이터 DB 저장 실패: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 공통 1일봉챠트 시세 다운로드 파이프라인 (타이머/수동 공용)
# ---------------------------------------------------------------------------

async def _step1_fetch_all_stocks(
    tag: str, _sector: object, _broker_name: str,
) -> list | None:
    """1단계: 전종목 리스트 다운로드."""
    logger.info("%s 1단계 시작 — 전종목 리스트 다운로드 (증권사=%s)", tag, BROKER_DISPLAY_NAMES.get(_broker_name, _broker_name))
    _broadcast_confirmed_progress(0, 0, message="전종목 목록 갱신 중...", step=1)
    try:
        records: list = await _sector.fetch_all_stocks()
        if not records:
            logger.warning("%s 전종목 리스트 결과 비어있음 — 중단", tag)
            return None
        kospi_count = sum(1 for r in records if r.market_code == "0")
        kosdaq_count = sum(1 for r in records if r.market_code == "10")
        other_count = len(records) - kospi_count - kosdaq_count
        logger.info("%s 1단계 완료 — 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)", tag, len(records), kospi_count, kosdaq_count, other_count)
        return records
    except Exception as exc:
        logger.warning("%s 전종목 통합 조회(ka10099) 실패: %s", tag, exc, exc_info=True)
        return None


async def _step2_filter_eligible(
    tag: str, records: list,
) -> tuple[set[str], str] | None:
    """2단계: 적격 종목 필터링. Returns (confirmed_codes, filter_summary_meta) or None."""
    logger.info("%s 2단계 시작 — 적격 종목 필터링", tag)
    _broadcast_confirmed_progress(0, 0, message="2단계: 매매부적격종목 필터링 중...", step=2)
    try:
        confirmed_codes: set[str] = set()
        filter_reasons: dict[str, int] = {}  # 종목 단위/primary_reason 기반 (유일 정답)
        code_groups: dict[str, list[tuple[object, StockFilterEvaluation]]] = {}
        from backend.app.core.stock_filter import evaluate_stock_filter, to_display_reason
        for r in records:
            evaluation = evaluate_stock_filter(r.raw_item, r.code)
            code_groups.setdefault(r.code, []).append((r, evaluation))

        duplicate_codes = {code for code, group in code_groups.items() if len(group) > 1}
        final_excluded_codes: set[str] = set()
        conflict_codes: set[str] = set()
        for code, group in code_groups.items():
            row_results = {evaluation.excluded for _, evaluation in group}
            if len(row_results) > 1:
                conflict_codes.add(code)
            excluded_evaluations = [evaluation for _, evaluation in group if evaluation.excluded]
            if excluded_evaluations:
                final_excluded_codes.add(code)
                primary_reason = excluded_evaluations[0].primary_reason or "부적격"
                display_reason = to_display_reason(primary_reason)
                filter_reasons[display_reason] = filter_reasons.get(display_reason, 0) + 1
            else:
                confirmed_codes.add(code)

        raw_rows = len(records)
        unique_codes = len(code_groups)
        excluded_count = len(final_excluded_codes)
        pct = (excluded_count / unique_codes * 100) if unique_codes else 0
        pct_int = int(round(pct))

        # ── 2줄 요약 로그 (7줄 중복 제거) ──
        logger.info(
            "%s 2단계 완료 — 전체 %d종목 → 적격 %d종목, 제외 %d종목 (%d%%)",
            tag, unique_codes, len(confirmed_codes), excluded_count, pct_int,
        )
        if filter_reasons:
            top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
            reason_strs = [f"{k} {v}개" for k, v in top_reasons]
            logger.info("%s 주요 제외 사유: %s", tag, ", ".join(reason_strs))

        # 이상 케이스는 WARNING으로만 출력 (정상 시 silent)
        if duplicate_codes:
            duplicate_preview = sorted(duplicate_codes)[:20]
            logger.warning("%s 전종목 통합 조회(ka10099) 동일 종목코드 중복 감지 — %d종목, 예시=%s", tag, len(duplicate_codes), duplicate_preview)
        if conflict_codes:
            conflict_preview = sorted(conflict_codes)[:20]
            logger.warning("%s 전종목 통합 조회(ka10099) 동일 종목코드 판정 충돌 — %d종목, 예시=%s", tag, len(conflict_codes), conflict_preview)
        _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 완료: 총 {unique_codes}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)

        # UI 표시용 요약 문자열 — 일반 용어 사용 (P21 사용자 투명성)
        summary_str = f"전체 {unique_codes}종목 → 매매 가능 {len(confirmed_codes)}종목 (제외 {excluded_count}종목, {pct_int}%)"
        if filter_reasons:
            top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
            reason_strs = [f"{k} {v}개" for k, v in top_reasons]
            summary_str += " | 주요 제외: " + ", ".join(reason_strs)
        _meta_top = [
            {"k": k, "v": v}
            for k, v in sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
        ] if filter_reasons else []
        filter_summary_meta = dumps({
            "raw_rows": raw_rows,
            "unique_codes": unique_codes,
            "excluded_count": excluded_count,
            "pct": round(pct, 1),
            "duplicate_count": len(duplicate_codes),
            "top_reasons": _meta_top,
        })
        return confirmed_codes, filter_summary_meta
    except Exception as exc:
        logger.warning("%s 2단계 필터링 실패: %s", tag, exc, exc_info=True)
        return None


async def _step3_parse_confirmed(
    tag: str, records: list, confirmed_codes: set[str],
) -> tuple[dict[str, str], dict[str, str]] | None:
    """3단계: 적격 종목 해석/매칭. Returns (name_map, market_map) or None."""
    logger.info("%s 3단계 시작 — 적격 종목 해석 (%d종목)", tag, len(confirmed_codes))
    _broadcast_confirmed_progress(0, 0, message="종목 정보 해석 중...", step=3)
    try:
        name_map: dict[str, str] = {}
        market_map: dict[str, str] = {}
        for r in records:
            if r.code in confirmed_codes:
                name_map[r.code] = r.name
                market_map[r.code] = r.market_code
        logger.info("%s 3단계 완료 — %d종목 해석/매칭", tag, len(name_map))
        return name_map, market_map
    except Exception as exc:
        logger.warning("%s 3단계 해석/매칭 실패: %s", tag, exc, exc_info=True)
        return None


async def _step4_save_to_db_and_cache(
    tag: str, records: list, confirmed_codes: set[str],
    filter_summary_meta: str, name_map: dict[str, str],
) -> list[str] | None:
    """4단계: DB 저장 + 메모리 캐시 동기화 + 레이아웃. Returns all_codes or None."""
    logger.info("%s 4단계 시작 — 캐시 저장 (%d종목)", tag, len(confirmed_codes))
    _broadcast_confirmed_progress(0, 0, message="캐시 저장 중...", step=4)
    try:
        from backend.app.db.database import get_db_connection as _get_conn, get_db_lock
        _conn = await _get_conn()

        if confirmed_codes:
            placeholders = ",".join("?" for _ in confirmed_codes)
            confirmed_codes_list = list(confirmed_codes)

            async with get_db_lock():
                await _conn.execute(f"DELETE FROM master_stocks_table WHERE code NOT IN ({placeholders})", confirmed_codes_list)
                insert_values = [(r.code, r.name, r.market_code, 1 if r.nxt_enable else 0) for r in records if r.code in confirmed_codes]
                if insert_values:
                    await _conn.executemany("""INSERT INTO master_stocks_table (code, name, market, nxt_enable) VALUES (?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET name = excluded.name, market = excluded.market, nxt_enable = excluded.nxt_enable""", insert_values)
                cursor = await _conn.execute("SELECT code FROM master_stocks_table")
                master_codes = set(row[0] for row in await cursor.fetchall())
                master_placeholders = ",".join("?" for _ in master_codes)
                master_codes_list = list(master_codes)
                if master_codes:
                    await _conn.execute(f"DELETE FROM stock_5d_bars WHERE code NOT IN ({master_placeholders})", master_codes_list)
                await _conn.execute("""
                    CREATE TABLE IF NOT EXISTS system_state_cache (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await _conn.execute(
                    "INSERT OR REPLACE INTO system_state_cache (key, value) VALUES (?, ?)",
                    ("filter_summary_meta", filter_summary_meta)
                )
                await _conn.commit()

            keys_to_delete = [cd for cd in list(engine_state.state.master_stocks_cache.keys()) if cd not in confirmed_codes]
            for cd in keys_to_delete:
                engine_state.state.master_stocks_cache.pop(cd, None)
            for r in records:
                if r.code in confirmed_codes:
                    if r.code not in engine_state.state.master_stocks_cache:
                        engine_state.state.master_stocks_cache[r.code] = {
                            "name": r.name,
                            "market": r.market_code,
                            "nxt_enable": bool(r.nxt_enable),
                            "cur_price": None,
                            "change": None,
                            "change_rate": None,
                            "sign": "3",
                            "trade_amount": None,
                            "avg_5d_trade_amount": 0,
                            "high_5d_price": 0,
                            "date": "",
                            "volume": 0,
                            "sector": "미분류",
                            "status": "active",
                        }
                    else:
                        engine_state.state.master_stocks_cache[r.code]["market"] = r.market_code
                        engine_state.state.master_stocks_cache[r.code]["nxt_enable"] = bool(r.nxt_enable)

            from backend.app.core.stock_classification_data import sync_sector_from_custom_sectors
            await sync_sector_from_custom_sectors()

        engine_state.state.latest_filter_summary_meta = filter_summary_meta

        all_codes = list(confirmed_codes)
        await _update_layout_cache(all_codes, name_map)
        logger.info("%s 4단계 완료 — 저장 완료 (%d종목)", tag, len(confirmed_codes))

        try:
            from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
            await broadcast_stock_classification_changed()
        except Exception as e:
            logger.warning("필터 요약 전송 실패: %s", e)
        return all_codes
    except Exception as exc:
        logger.warning("%s 4단계 저장 실패: %s", tag, exc, exc_info=True)
        return None


async def _step5_download_daily_confirmed(
    tag: str, _sector: object, all_codes: list[str],
    name_map: dict[str, str], confirmed_codes: set[str],
) -> tuple[int, int, bool]:
    """5단계: 전종목 1일봉챠트 시세 조회(ka10081) 다운로드. Returns (fetched, failed, cached).

    qry_dt는 가장 최근 확정된 거래일을 사용 (P10/P22).
    달력 오늘을 사용하면 장 전/중 실행 시 API가 오늘 미확정 일봉(거래대금=0)을
    반환하여 미확정 데이터가 DB에 저장되는 정합성 위반이 발생함.
    """
    logger.info("[다운로드] 다운로드 시작 (%d종목)", len(all_codes))
    # 가장 최근 확정된 거래일 — 소속 거래일의 직전 거래일 (P10/P22)
    # 06:36 @ 07-15(수, 장전): current=07-15 → previous=07-14 (07-14 확정 데이터)
    # 20:40 @ 07-15(수, 장후): current=07-16 → previous=07-15 (07-15 확정 데이터)
    qry_dt = get_previous_trading_day_str(get_current_trading_day_str())
    total = len(all_codes)
    _main_loop = asyncio.get_running_loop()

    _broadcast_confirmed_progress(0, total, message=f"1일봉챠트 시세 다운로드 중 (0/{total:,}, 0%)", step=5)
    _dl_start = time.monotonic()

    def _on_progress(cur: int, tot: int) -> None:
        _pct = int(cur / total * 100) if total > 0 else 0
        _eta: float = 0
        if cur > 0:
            _elapsed = time.monotonic() - _dl_start
            _eta = _elapsed / cur * (total - cur)
        _broadcast_confirmed_progress(cur, total, message=f"1일봉챠트 시세 다운로드 중 ({cur:,}/{total:,}, {_pct}%)", eta_sec=_eta, step=5, _loop=_main_loop)

    try:
        confirmed = await _sector.fetch_all_stocks_daily_confirmed(all_codes, qry_dt, interval_sec=0.3, on_progress=_on_progress)
    except Exception as exc:
        logger.warning("[다운로드] 전종목 조회 실패: %s", exc, exc_info=True)
        confirmed = {}

    fetched = len(confirmed)
    failed = total - fetched
    success_rate = (fetched / total * 100) if total else 0
    logger.info("[다운로드] 다운로드 완료 — 성공 %d, 실패 %d (%.1f%%)", fetched, failed, success_rate)
    if failed > 0 and success_rate < 99.0:
        logger.warning("[다운로드] 실패율 높음: %d/%d (%.1f%%)", failed, total, 100 - success_rate)

    if confirmed:
        normalized_confirmed = {}
        for cd, val in confirmed.items():
            normalized_confirmed[cd] = {
                "dt": val.get("dt") or "",
                "cur_price": val.get("close") or val.get("cur_price") or 0,
                "trade_amount": val.get("value") if val.get("value") is not None else val.get("trade_amount"),
                "high_price": val.get("high") or val.get("high_price") or 0,
                "volume": val.get("volume") or 0,
                "change": val.get("change") or 0,
                "change_rate": val.get("rate") if val.get("rate") is not None else val.get("change_rate"),
                "sign": val.get("sign") or "3",
            }
        await _apply_confirmed_to_memory(normalized_confirmed, {}, name_map=name_map, confirmed_codes=confirmed_codes)

    cached = False
    if confirmed:
        logger.info("%s 단일 벌크 트랜잭션 시작", tag)
        await execute_unified_rolling_and_save(normalized_confirmed, name_map=name_map, qry_dt=qry_dt)
        logger.info("%s 단일 벌크 트랜잭션 완료", tag)
        cached = True

    try:
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        await broadcast_stock_classification_changed()
        logger.info("%s 종목분류 페이지 갱신 전송 완료", tag)
    except Exception as _bc_err:
        logger.warning("%s 종목분류 페이지 갱신 전송 실패(무시): %s", tag, _bc_err)

    if failed > 0:
        _broadcast_confirmed_progress(total, total, message=f"⚠️ 1일봉챠트 시세 다운로드 부분 완료 ({fetched:,}/{total:,}) — {failed}종목 실패", step=5, failed_count=failed)
    else:
        _broadcast_confirmed_progress(total, total, message=f"1일봉챠트 시세 다운로드 완료 ({fetched:,}/{total:,})", step=5)

    _broadcast_confirmed_progress(total, total, message="5일 거래대금 계산 중...", step=5)
    await _run_post_confirmed_pipeline(eligible_codes=confirmed_codes)

    if cached:
        final_eligible = confirmed_codes
        if final_eligible:
            to_remove = [cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_subscribed", False) and cd not in final_eligible]
            for cd in to_remove:
                if cd in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
            subscribed_count = sum(1 for entry in engine_state.state.master_stocks_cache.values() if entry.get("_subscribed", False))
            logger.info("%s 6단계 메모리 교체 완료 — 구독 중=%d종목", tag, subscribed_count)
    else:
        logger.warning("%s 캐시 미적용 — 메모리 교체 생략", tag)

    return fetched, failed, cached


async def _step7_recompute_and_broadcast(tag: str) -> None:
    """7단계: 업종순위 재계산 + 실시간 통신 전송."""
    try:
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        from backend.app.services.engine_account_notify import notify_desktop_sector_stocks_refresh
        # 확정 데이터 반영 후 수신율 갱신 — change_rate, trade_amount 기준 100% 산출 (P21 투명성, P22 정합성)
        from backend.app.pipelines.pipeline_compute import _calculate_receive_rate, _send_receive_rate, get_current_receive_rate
        await _calculate_receive_rate()
        await _send_receive_rate(get_current_receive_rate())
        await notify_desktop_sector_stocks_refresh(force=True)
        await recompute_sector_summary_now()
        logger.info("%s 업종순위 재계산 + 실시간 화면 전송 완료", tag)
    except Exception as _ws_err:
        logger.warning("%s 업종순위 재계산 실패: %s", tag, _ws_err, exc_info=True)


async def _run_confirmed_pipeline(
    tag: str,
    *,
    check_scheduler: bool = False,
    check_time_guard: bool = False,
) -> dict:
    """공통 1일봉챠트 시세 다운로드 파이프라인 (타이머/수동 공용).

    1~7단계: 전종목 통합 조회(ka10099) 전종목 다운로드 → 필터링 → 해석 → DB저장 →
    전종목 1일봉챠트 시세 조회(ka10081) 1일봉챠트 시세 다운로드 → 정규화 → 메모리/DB 저장 → 메모리 교체 → 전송.
    """
    if engine_state.state.confirmed_refresh_running_confirmed:
        logger.info("%s 확정 조회 이미 진행 중 — 생략", tag)
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    engine_state.state.confirmed_refresh_running_confirmed = True
    engine_state.state.confirmed_refresh_message = ""

    _broker_token_registered = False

    try:
        # ── 메모리 전체 초기화 ──
        engine_state.state.integrated_system_settings_cache["sector_stock_layout"] = []
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        logger.info("%s 메모리 전체 초기화 완료 — 새 데이터로 교체 시작", tag)

        # 스케줄러 토글 체크 (타이머 전용)
        if check_scheduler and not engine_state.state.integrated_system_settings_cache["scheduler_market_close_on"]:
            logger.info("%s 장마감 스케줄러=꺼짐 — 전체 갱신 생략", tag)
            return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

        from backend.app.core.broker_registry import _create_provider
        _settings = engine_state.state.integrated_system_settings_cache
        _broker_name = "kiwoom"
        _auth_cache: dict[str, AuthProvider] = {}
        _auth_provider = _create_provider("auth", _broker_name, _settings, _auth_cache)
        _broker_token = await _auth_provider.get_access_token() if _auth_provider else None
        if _broker_token and _broker_name not in engine_state.state.broker_tokens:
            engine_state.state.broker_tokens[_broker_name] = _broker_token
            _broker_token_registered = True
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            await broadcast_engine_status()
        _sector = _create_provider("stock", _broker_name, _settings, _auth_cache)

        # ── 1단계: 전종목 리스트 다운로드 ──
        records = await _step1_fetch_all_stocks(tag, _sector, _broker_name)
        if records is None:
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── 2단계: 적격 종목 필터링 ──
        step2_result = await _step2_filter_eligible(tag, records)
        if step2_result is None:
            return {"fetched": 0, "failed": 0, "cached": False}
        confirmed_codes, filter_summary_meta = step2_result

        # ── 3단계: 적격 종목 해석/매칭 ──
        step3_result = await _step3_parse_confirmed(tag, records, confirmed_codes)
        if step3_result is None:
            return {"fetched": 0, "failed": 0, "cached": False}
        name_map, _market_map = step3_result

        # ── 4단계: DB 저장 + 메모리 캐시 동기화 + 레이아웃 ──
        all_codes = await _step4_save_to_db_and_cache(tag, records, confirmed_codes, filter_summary_meta, name_map)
        if all_codes is None:
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── 시간 가드 (타이머 전용) ──
        if check_time_guard:
            from backend.app.services.daily_time_scheduler import is_heavy_operation_allowed
            if not await is_heavy_operation_allowed():
                logger.info("%s 안전 구역 외 시간대 — 5단계 생략", tag)
                return {"fetched": 0, "failed": 0, "cached": False}

        # ── 5단계: 전종목 1일봉챠트 시세 조회(ka10081) 다운로드 ──
        fetched, failed, cached = await _step5_download_daily_confirmed(tag, _sector, all_codes, name_map, confirmed_codes)

        # ── 7단계: 업종순위 재계산 + 실시간 통신 전송 ──
        await _step7_recompute_and_broadcast(tag)

        if cached:
            logger.info("[다운로드] 전체 완료 — 전종목 통합 조회(ka10099): %d종목 | 적격: %d종목 | 1일봉: %d/%d종목", len(all_codes), len(confirmed_codes), fetched, len(all_codes))
        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        if _broker_token_registered:
            engine_state.state.broker_tokens.pop(_broker_name, None)
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            await broadcast_engine_status()
        engine_state.state.confirmed_refresh_running_confirmed = False
        engine_state.state.confirmed_refresh_message = ""


# ---------------------------------------------------------------------------
# 통합 확정 데이터 조회 (20:30)
# ---------------------------------------------------------------------------

async def fetch_unified_confirmed_data() -> dict:
    """20:30 타이머 통합 확정 조회 — _run_confirmed_pipeline 위임."""
    return await _run_confirmed_pipeline("[스케줄]", check_scheduler=True, check_time_guard=True)


# ---------------------------------------------------------------------------
# 통합 확정 조회 헬퍼
# ---------------------------------------------------------------------------

async def _update_layout_cache(
    all_codes: list[str],
    name_map: dict[str, str],
) -> None:
    """confirmed_codes 기준으로 레이아웃 캐시를 완전 재구성.

    - 부적격이 된 종목은 레이아웃에서 제거된다.
    - stock_classification.json의 최신 업종 매핑이 전체 종목에 적용된다.
    - 업종 헤더가 없는 종목("미분류")도 레이아웃에 포함된다.
    """
    # sector_layout 캐시 저장 삭제 (전종목 마스터 테이블 sector 컬럼으로 대체)

    # SQLite DB에서 한 번에 모든 매핑 조회 (1회 쿼리 수행)
    from backend.app.db.database import get_db_connection
    db_mapping = {}
    try:
        conn = await get_db_connection()
        cursor = await conn.cursor()
        await cursor.execute("SELECT code, sector FROM master_stocks_table")
        rows = await cursor.fetchall()
        for r in rows:
            if r["code"] and r["sector"]:
                db_mapping[r["code"]] = r["sector"]
    except Exception as e:
        logger.warning("[데이터] 전체 매핑 DB 조회 실패: %s", e)

    # 전체 종목을 업종별로 그룹핑 (stock_classification.json 최신 매핑 적용)
    sector_groups: dict[str, list[str]] = {}
    for cd in all_codes:
        sec = None
        entry = engine_state.state.master_stocks_cache.get(cd)
        if entry and "sector" in entry:
            sec = entry["sector"]
        # 2) DB 매핑 확인
        if not sec:
            sec = db_mapping.get(_base_stk_cd(cd))
        # 3) 기본값
        if not sec:
            sec = "미분류"

        sector_groups.setdefault(sec, []).append(cd)

    # 업종 내 종목 정렬 (재현성 보장)
    for sec in sector_groups:
        sector_groups[sec].sort()

    # 업종 순서: 기존 레이아웃의 업종 순서를 최대한 유지하고 신규 업종는 뒤에 추가
    old_layout: list[tuple[str, str]] = engine_state.state.integrated_system_settings_cache["sector_stock_layout"]
    old_sector_order = list(dict.fromkeys(v for t, v in old_layout if t == "sector"))

    new_sectors = [s for s in sector_groups if s not in old_sector_order]
    final_sector_order = [s for s in old_sector_order if s in sector_groups] + new_sectors

    # 레이아웃 재구성
    new_layout: list[tuple[str, str]] = []
    for sec in final_sector_order:
        new_layout.append(("sector", sec))
        for cd in sector_groups[sec]:
            new_layout.append(("code", cd))

    engine_state.state.integrated_system_settings_cache["sector_stock_layout"] = new_layout
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache(new_layout)
    logger.info(
        "[스케줄] 레이아웃 저장데이터 완전 재구성 — %d종목, %d업종",
        len(all_codes), len(final_sector_order),
    )


# ---------------------------------------------------------------------------
# 수동 1일봉챠트 시세 및 5일봉챠트 다운로드
# ---------------------------------------------------------------------------

async def fetch_confirmed_data_only() -> dict:
    """수동 매매적격종목 1일봉챠트 시세 다운로드 파이프라인 — _run_confirmed_pipeline 위임."""
    return await _run_confirmed_pipeline("[수동 확정시세]")




async def fetch_5d_data_only() -> dict:
    """수동 5일봉 거래대금,고가 다운로드 파이프라인.

    DB의 master_stocks_table에 등록된 매매적격종목을 대상으로
    개별 종목의 5일 고가 및 거래대금 데이터를 다운로드하여 DB 및 메모리에 저장합니다.
    stock_5d_bars 테이블에 각 일봉을 (code, dt) 복합키 세로 행으로 INSERT OR REPLACE (P10/P22/P24).
    전체 DELETE 없이 덮어쓰기 방식 — 부분 실패 시 기존 데이터 보존 (P22).
    저장 후 최근 5개 거래일 외 행 삭제로 테이블 크기 유지 (P24).

    qry_dt는 가장 최근 확정된 거래일을 사용 (P10/P22).
    달력 오늘을 사용하면 장 전/중 실행 시 API가 오늘 미확정 일봉(거래대금=0)을
    반환하여 미확정 데이터가 DB에 저장되는 정합성 위반이 발생함.
    """

    # 중복 실행 방지
    if engine_state.state.confirmed_refresh_running_5d:
        logger.info("[다운로드] 다운로드 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    engine_state.state.confirmed_refresh_running_5d = True
    engine_state.state.confirmed_refresh_message = ""

    _broker_token_registered = False

    try:
        from backend.app.core.broker_registry import _create_provider
        _settings = engine_state.state.integrated_system_settings_cache
        _broker_name = "kiwoom"
        _auth_cache: dict[str, AuthProvider] = {}
        _auth_provider = _create_provider("auth", _broker_name, _settings, _auth_cache)
        _broker_token = await _auth_provider.get_access_token() if _auth_provider else None
        if _broker_token and _broker_name not in engine_state.state.broker_tokens:
            engine_state.state.broker_tokens[_broker_name] = _broker_token
            _broker_token_registered = True
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            await broadcast_engine_status()
        _sector = _create_provider("stock", _broker_name, _settings, _auth_cache)
        logger.info("[다운로드] 종목 제공자 증권사=%s", BROKER_DISPLAY_NAMES.get(_broker_name, _broker_name))

        # ── 메모리 캐시에서 매매적격종목 코드 리스트 로드 (SSOT: DB에서만 로드된 캐시 사용) ──
        logger.info("[다운로드] 매매적격종목 목록 로드 시작")
        all_codes = [cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("status") == "active"]
        total = len(all_codes)

        logger.info("[다운로드] 대상 적격 종목 수: %d", total)
        if total == 0:
            logger.warning("[다운로드] 대상 종목 없음 — 중단")
            engine_state.state.confirmed_refresh_running_5d = False
            engine_state.state.confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── DB 연결 (INSERT OR REPLACE 기반 — 전체 DELETE 제거로 부분 실패 시 기존 데이터 보존) ──
        from backend.app.db.database import get_db_connection, get_db_lock
        conn = await get_db_connection()

        # ── 개별 5일봉 데이터 다운로드 ───────────────────────────────────────
        logger.info("[다운로드] 다운로드 시작 (%d종목)", total)
        _broadcast_confirmed_progress(0, total, message=f"5일봉챠트 거래대금,고가 다운로드 중 (0/{total:,}, 0%)", step=5)
        _dl_start = time.monotonic()

        fetched = 0
        failed = 0
        confirmed_5d = {}
        # 가장 최근 확정된 거래일 — 소속 거래일의 직전 거래일 (P10/P22)
        # 06:36 @ 07-15(수, 장전): current=07-15 → previous=07-14 (07-14 이하 5영업일)
        # 20:40 @ 07-15(수, 장후): current=07-16 → previous=07-15 (07-15 이하 5영업일)
        qry_dt = get_previous_trading_day_str(get_current_trading_day_str())

        for idx, base_cd in enumerate(all_codes):
            nk = _base_stk_cd(base_cd)
            if not nk:
                failed += 1
                continue

            try:
                res = await _sector.fetch_stock_5day_data(base_cd, qry_dt)
                if res:
                    amounts_5d = res.get("amts_5d_array") or []
                    highs_5d = res.get("highs_5d_array") or []
                    dts_5d = res.get("dts_5d_array") or []

                    if amounts_5d and highs_5d and dts_5d:
                        confirmed_5d[nk] = {
                            "amts_5d_array": amounts_5d,
                            "highs_5d_array": highs_5d,
                            "dts_5d_array": dts_5d,
                        }
                        fetched += 1
                    else:
                        failed += 1
                        logger.warning("[다운로드] 데이터 비어있음 [%d/%d] %s", idx + 1, total, base_cd)
                else:
                    failed += 1
                    logger.warning("[다운로드] API 응답 없음 [%d/%d] %s", idx + 1, total, base_cd)

            except Exception as e:
                failed += 1
                logger.warning("[다운로드] 오류 발생 [%d/%d] %s: %s", idx + 1, total, base_cd, e)

            # 진행률 전송 (매 종목)
            pct = int((idx + 1) / total * 100) if total else 0
            _eta: float = 0
            if (idx + 1) > 0:
                _elapsed = time.monotonic() - _dl_start
                _eta = _elapsed / (idx + 1) * (total - (idx + 1))
            _broadcast_confirmed_progress(
                idx + 1, total,
                message=f"5일봉챠트 거래대금,고가 다운로드 중 ({idx + 1:,}/{total:,}, {pct}%)",
                eta_sec=_eta,
                step=5
            )
            log_progress("[다운로드]", idx + 1, total, code=base_cd)

            # 요청 간격 조절
            await asyncio.sleep(0.3)

        log_progress_end()
        # ── 5일봉 세로 행 테이블 직접 삽입 (5일치 전체 저장) ───────────────────
        if confirmed_5d:
            logger.info("[다운로드] 5일봉 세로 행 테이블 직접 삽입 — %d종목", len(confirmed_5d))

            bars_params = []
            master_update_params = []

            for cd, data in confirmed_5d.items():
                amts_5d = data.get("amts_5d_array") or []
                highs_5d = data.get("highs_5d_array") or []
                dts_5d = data.get("dts_5d_array") or []

                # 5일평균, 5일최고가 계산 (빈 값 제외)
                valid_amts = [a for a in amts_5d if a is not None and a > 0]
                avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else 0

                valid_highs = [h for h in highs_5d if h is not None and h > 0]
                high_5d = max(valid_highs) if valid_highs else 0

                # 세로 행 파라미터 — 각 일봉을 (code, dt, trade_amount, high_price) 1행으로 저장
                # 안전망: 소속 거래일 자체(미확정 당일) 행은 저장 차단 (P22 데이터 정합성)
                # qry_dt를 직전 거래일로 설정했으므로 정상 경로에서는 발생하지 않으나,
                # API가 당일 행을 반환하는 예외 케이스를 방어.
                current_td = get_current_trading_day_str()
                for i in range(min(len(amts_5d), len(highs_5d), len(dts_5d))):
                    dt = dts_5d[i]
                    if not dt:
                        continue
                    if str(dt) == current_td:
                        logger.warning(
                            "[다운로드] %s 행 저장 생략 — 소속 거래일(미확정) 행 감지 (dt=%s, P22)",
                            cd, dt,
                        )
                        continue
                    bars_params.append((cd, str(dt), amts_5d[i], highs_5d[i]))

                # 전종목 마스터 테이블 갱신 파라미터
                master_update_params.append((avg_5d, high_5d, cd))

            # 단일 트랜잭션으로 저장
            async with get_db_lock():
                if bars_params:
                    await conn.executemany(
                        """INSERT OR REPLACE INTO stock_5d_bars
                        (code, dt, trade_amount, high_price)
                        VALUES (?, ?, ?, ?)""",
                        bars_params
                    )
                await conn.executemany(
                    """UPDATE master_stocks_table
                    SET avg_5d_trade_amount = ?, high_5d_price = ?
                    WHERE code = ?""",
                    master_update_params
                )
                # 행 정리 — qry_dt 기준 최근 5거래일 외 행 삭제 + 미확정 당일(미래) 행 삭제 (P22/P24)
                # qry_dt 기준: 장 전 실행 시 qry_dt=직전 거래일(07-14) → 07-14 이하 5거래일만 보존
                # 미래 행 삭제: qry_dt보다 큰 dt 행(예: 기존 07-15 미확정 행)을 삭제하여
                #   미확정 당일 행이 DB에 잔존하는 정합성 위반 해소
                from datetime import date as _date
                from backend.app.core.trading_calendar import get_recent_trading_days
                qry_date = _date(int(qry_dt[:4]), int(qry_dt[4:6]), int(qry_dt[6:8]))
                recent_5 = get_recent_trading_days(5, from_date=qry_date)
                if recent_5:
                    oldest_dt = recent_5[0].strftime("%Y%m%d")
                    # dt < oldest_dt: 과거 행 정리 (기존)
                    # dt > qry_dt: 미확정 당일(미래) 행 정리 (신규) — 기존 07-15 행 삭제
                    await conn.execute(
                        "DELETE FROM stock_5d_bars WHERE dt < ? OR dt > ?",
                        (oldest_dt, qry_dt),
                    )
                await conn.commit()

            logger.info("[다운로드] DB 저장 완료 — %d종목, %d행", len(confirmed_5d), len(bars_params))

            # 메모리 캐시 갱신
            for cd, data in confirmed_5d.items():
                amts_5d = data.get("amts_5d_array") or []
                highs_5d = data.get("highs_5d_array") or []

                valid_amts = [a for a in amts_5d if a is not None and a > 0]
                avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else 0

                valid_highs = [h for h in highs_5d if h is not None and h > 0]
                high_5d = max(valid_highs) if valid_highs else 0

                if cd in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[cd]["avg_5d_trade_amount"] = avg_5d
                    engine_state.state.master_stocks_cache[cd]["high_5d_price"] = high_5d

            logger.info("[다운로드] 메모리 캐시 갱신 완료")

        success_rate = (fetched / total * 100) if total else 0
        logger.info("[다운로드] 다운로드 완료 — 성공 %d종목, 실패 %d종목 (%.1f%%)", fetched, failed, success_rate)

        if failed > 0:
            _broadcast_confirmed_progress(total, total, message=f"⚠️ 5일봉챠트 거래대금,고가 다운로드 부분 완료 ({fetched:,}/{total:,}) — {failed}종목 실패", step=5, failed_count=failed)
        else:
            _broadcast_confirmed_progress(total, total, message=f"5일봉챠트 거래대금,고가 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # 종목분류 전송 (프론트엔드 자동갱신)
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        await broadcast_stock_classification_changed()

        # 후처리
        await _run_post_confirmed_pipeline(eligible_codes=set(all_codes))

        # 업종순위 재계산 (내부에서 notify_desktop_sector_scores + notify_buy_targets_update 호출)
        # 순서: sector-stocks-refresh → recompute_sector_summary_now
        # sectorStocks가 먼저 갱신되어야 buy-targets-delta merge 시 최신 데이터 참조 가능
        try:
            from backend.app.services.sector_data_provider import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_stocks_refresh,
            )
            # 확정 데이터 반영 후 수신율 갱신 — change_rate, trade_amount 기준 100% 산출 (P21 투명성, P22 정합성)
            from backend.app.pipelines.pipeline_compute import _calculate_receive_rate, _send_receive_rate, get_current_receive_rate
            await _calculate_receive_rate()
            await _send_receive_rate(get_current_receive_rate())
            await notify_desktop_sector_stocks_refresh(force=True)
            await recompute_sector_summary_now()
            logger.info("[다운로드] 업종순위 재계산 + 실시간 화면 전송 완료")
        except Exception as _ws_err:
            logger.warning("[다운로드] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)

        return {"fetched": fetched, "failed": failed, "cached": False}
    finally:
        if _broker_token_registered:
            engine_state.state.broker_tokens.pop(_broker_name, None)
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            await broadcast_engine_status()
        engine_state.state.confirmed_refresh_running_5d = False
        engine_state.state.confirmed_refresh_message = ""
