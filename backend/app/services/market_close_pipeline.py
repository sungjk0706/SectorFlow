from __future__ import annotations
# -*- coding: utf-8 -*-
"""
장마감 후 데이터 캐시 파이프라인 — 핵심 로직.

KRX/NXT 장마감 후 WS 구독 해지 → REST 확정 데이터 조회 → 캐시 저장.
daily_time_scheduler.py 타이머 콜백에서 호출된다.
"""

import asyncio
import json
import time
from types import ModuleType

from backend.app.core.logger import get_logger
from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    is_nxt_enabled,
    get_ws_subscribe_code,
)
from backend.app.services.engine_ws_reg import build_0b_remove_payloads
from backend.app.core.trading_calendar import get_current_trading_day_str
from backend.app.services.engine_state import state

_log = get_logger("engine")


def _broadcast_confirmed_progress(
    current: int, total: int, *, message: str = "", eta_sec: float = 0, step: int = 0,
    failed_count: int = 0,
    _loop: "asyncio.AbstractEventLoop | None" = None,
) -> None:
    """확정 데이터 조회 진행률 → confirmed-progress WS 브로드캐스트 (헤더 칩 표시용).

    _loop が渡된 경우(스레드풀 내부 호출): broadcast_threadsafe()로 메인 루프에 예약.
    _loop가 없는 경우(async context 직접 호출): broadcast() 사용.
    """
    try:
        from backend.app.web.ws_manager import ws_manager
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
        _log.warning("[데이터] 브로드캐스트 실패: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 종목 분류 헬퍼
# ---------------------------------------------------------------------------

def _get_krx_only_codes(es: ModuleType) -> list[str]:
    """_master_stocks_cache에서 KRX 단독 종목(nxt_enable=False)만 추출.

    Args:
        es: engine_service 모듈 참조

    Returns:
        6자리 정규화된 KRX 단독 종목코드 리스트 (중복 없음).
    """
    result: list[str] = []
    seen: set[str] = set()

    sources: list[set | dict | list] = []
    # _master_stocks_cache의 "_subscribed" 사용
    subscribed_codes = {cd for cd, entry in es._master_stocks_cache.items() if entry.get("_subscribed", False)}
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
    layout = es._integrated_system_settings_cache["sector_stock_layout"]
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

async def remove_krx_only_stocks(es: ModuleType) -> dict:
    """KRX 단독 종목(nxt_enable=False)만 선택적 REMOVE.

    Args:
        es: engine_service 모듈 참조

    Returns:
        {"removed": int, "failed": int, "skipped": bool}
    """
    # BrokerConnector 추상화 사용
    ws = state.connector_manager or state.active_connector
    if not ws or not ws.is_connected():
        _log.warning("[타이머] KRX 장마감 구독해지 생략 — 실시간 미연결")
        return {"removed": 0, "failed": 0, "skipped": True}

    krx_codes = _get_krx_only_codes(es)
    if not krx_codes:
        _log.info("[타이머] KRX 장마감 구독해지 대상 없음")
        return {"removed": 0, "failed": 0, "skipped": False}

    # 종목코드를 WS 구독 형식으로 변환하여 페이로드 생성
    ws_codes = [get_ws_subscribe_code(cd) for cd in krx_codes]
    payloads = build_0b_remove_payloads(ws_codes)

    if not payloads:
        return {"removed": 0, "failed": 0, "skipped": False}

    removed = 0
    failed = 0
    chunk_size = 100

    # 브로커별 ACK 지원 여부 확인
    supports_ack = ws.supports_ack() if hasattr(ws, 'supports_ack') else True

    for ci, payload in enumerate(payloads):
        chunk = krx_codes[ci * chunk_size : (ci + 1) * chunk_size]
        try:
            if supports_ack:
                # ACK 지원 브로커 (Kiwoom): ACK 대기
                ack_ok, rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
            else:
                # ACK 미지원 브로커 (LS): fire-and-forget
                ack_ok = await es._ws_send_remove_fire_and_forget(payload)
                rc = ""
        except Exception as exc:
            _log.warning(
                "[타이머] KRX 장마감 구독해지 %d/%d 예외: %s",
                ci + 1, len(payloads), exc,
                exc_info=True,
            )
            failed += len(chunk)
            continue

        if ack_ok:
            # 성공 — _master_stocks_cache에서 "_subscribed" 제거
            for cd in chunk:
                if cd in es._master_stocks_cache:
                    es._master_stocks_cache[cd].pop("_subscribed", None)
            removed += len(chunk)
            if supports_ack:
                _log.info(
                    "[타이머] KRX 장마감 구독해지 %d/%d 완료 — %d종목 (rc=%s)",
                    ci + 1, len(payloads), len(chunk), rc,
                )
            else:
                _log.info(
                    "[타이머] KRX 장마감 구독해지 %d/%d 완료 — %d종목 (ACK 미지원)",
                    ci + 1, len(payloads), len(chunk),
                )
        else:
            # 실패 — _master_stocks_cache의 "_subscribed" 유지 + 경고
            failed += len(chunk)
            _log.warning(
                "[타이머] KRX 장마감 구독해지 %d/%d 실패 — %d종목 유지",
                ci + 1, len(payloads), len(chunk),
            )

    _log.info(
        "[타이머] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목",
        removed, failed,
    )
    return {"removed": removed, "failed": failed, "skipped": False}


# ---------------------------------------------------------------------------
# 단일 벌크 트랜잭션 헬퍼 함수
# ---------------------------------------------------------------------------

async def execute_unified_rolling_and_save(
    es: ModuleType,
    confirmed: dict[str, dict],
    name_map: dict[str, str] | None = None,
) -> bool:
    """모든 정산 데이터를 메모리에서 연산 후 단일 트랜잭션으로 DB 및 메모리에 저장.

    Args:
        es: engine_service 모듈 참조
        confirmed: {종목코드: {cur_price, change, change_rate, trade_amount, high_price}}
        name_map: {6자리 종목코드: 종목명} — 종목명 보정용

    Returns:
        저장 성공 여부.
    """
    from backend.app.db.database import get_db_connection, get_db_lock
    import backend.app.services.engine_state as _st

    date_str = get_current_trading_day_str()
    _nm = name_map or {}

    async with get_db_lock():
        conn = await get_db_connection()

        try:
            # 1. 기존 5일 배열 일괄 로드 (1회 조회)
            cursor = await conn.execute("""
                SELECT code, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                       day1_high, day2_high, day3_high, day4_high, day5_high
                FROM stock_5d_array
                WHERE date = (SELECT MAX(date) FROM stock_5d_array WHERE date < ?)
            """, (date_str,))
            existing_rows = await cursor.fetchall()
            existing_map = {r["code"]: r for r in existing_rows}

            # 2. 메모리 연산 및 벌크 파라미터 빌드
            master_bulk_params = []
            array_5d_bulk_params = []

            for raw_cd, detail in confirmed.items():
                nk = _base_stk_cd(raw_cd)
                if not nk:
                    continue

                # 당일 데이터 추출
                today_amt = int(detail.get("trade_amount") or 0)
                today_high = int(detail.get("high_price") or detail.get("cur_price") or 0)
                cur_price = int(detail.get("cur_price") or 0)
                change = int(detail.get("change") or 0)
                change_rate = float(detail.get("change_rate") or 0.0)

                # 5일 롤링 계산 (NULL 허용)
                if nk in existing_map:
                    row = existing_map[nk]
                    new_amts = [today_amt, row["day1_amount"], row["day2_amount"], row["day3_amount"], row["day4_amount"]]
                    new_highs = [today_high, row["day1_high"], row["day2_high"], row["day3_high"], row["day4_high"]]
                else:
                    new_amts = [today_amt, None, None, None, None]
                    new_highs = [today_high, None, None, None, None]

                # 메트릭 계산 (NULL 제외)
                valid_amts = [a for a in new_amts if a is not None and a > 0]
                avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else 0

                valid_highs = [h for h in new_highs if h is not None and h > 0]
                high_5d = max(valid_highs) if valid_highs else 0

                # DB 벌크 파라미터 추가
                array_5d_bulk_params.append((
                    nk, date_str,
                    new_amts[0], new_amts[1], new_amts[2], new_amts[3], new_amts[4],
                    new_highs[0], new_highs[1], new_highs[2], new_highs[3], new_highs[4]
                ))

                # master_stocks_table market 정보 조회
                stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)

                master_bulk_params.append((
                    nk, stk_nm, cur_price, change, change_rate,
                    today_amt, today_high, avg_5d, high_5d, date_str
                ))

                # 메모리 캐시 동시 갱신
                if nk in _st._master_stocks_cache:
                    entry = _st._master_stocks_cache[nk]
                    entry.update({
                        "cur_price": cur_price,
                        "change": change,
                        "change_rate": change_rate,
                        "trade_amount": today_amt,
                        "high_price": today_high,
                        "avg_5d_trade_amount": avg_5d,
                        "high_5d_price": high_5d,
                        "date": date_str,
                        "status": "active"
                    })
                    if stk_nm and stk_nm != nk:
                        entry["name"] = stk_nm

            # 3. 단일 트랜잭션 내 벌크 실행
            # 5일 배열 적재
            if array_5d_bulk_params:
                await conn.executemany("""
                    INSERT OR REPLACE INTO stock_5d_array
                    (code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                     day1_high, day2_high, day3_high, day4_high, day5_high)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, array_5d_bulk_params)

            # 마스터 테이블 적재 (UPSERT)
            if master_bulk_params:
                # 기존 market 정보 보존을 위해 먼저 조회
                cursor = await conn.execute("SELECT code, market FROM master_stocks_table")
                mkt_rows = await cursor.fetchall()
                mkt_map = {r["code"]: r["market"] for r in mkt_rows}

                updated_params = []
                for params in master_bulk_params:
                    code = params[0]
                    market = mkt_map.get(code, "")
                    updated_params.append(params + (market,))

                await conn.executemany("""
                    INSERT INTO master_stocks_table
                    (code, name, cur_price, change, change_rate, trade_amount, high_price, avg_5d_trade_amount, high_5d_price, date, market)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        cur_price = excluded.cur_price,
                        change = excluded.change,
                        change_rate = excluded.change_rate,
                        trade_amount = excluded.trade_amount,
                        high_price = excluded.high_price,
                        avg_5d_trade_amount = excluded.avg_5d_trade_amount,
                        high_5d_price = excluded.high_5d_price,
                        date = excluded.date,
                        market = excluded.market
                """, updated_params)

            await conn.commit()
            _log.info("[단일 벌크 트랜잭션] 저장 완료 -- stock_5d_array: %d종목, master_stocks_table: %d종목", len(array_5d_bulk_params), len(master_bulk_params))
            return True

        except Exception as e:
            await conn.rollback()
            _log.warning("[단일 벌크 트랜잭션] 저장 실패: %s", e, exc_info=True)
            raise e


async def _apply_confirmed_to_memory(
    es: ModuleType,
    confirmed: dict[str, dict],
    strength: dict[str, float],
    name_map: dict[str, str] | None = None,
    confirmed_codes: set[str] | None = None,
) -> int:
    """확정 데이터를 메모리 캐시에 반영. 0값은 기존 데이터를 덮지 않음.

    Args:
        es: engine_service 모듈 참조
        confirmed: {종목코드: {cur_price, change, change_rate, sign, volume, trade_amount, prev_close}}
        strength: {종목코드: 체결강도 float}
        name_map: {6자리 종목코드: 종목명} — ka10099에서 조회한 매핑. 있으면 모든 엔트리 종목명 갱신.
        confirmed_codes: 매매적격 종목 코드 집합 — 이 외 코드는 메모리 캐시에 반영하지 않음 (SSOT).

    Returns:
        반영된 종목 수.
    """
    _nm = name_map or {}
    import backend.app.services.engine_state as _st
    pending: dict = _st._master_stocks_cache
    ltp: dict = {}
    lta: dict = {}
    lst: dict = {}

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
        _log.warning("[메모리 반영] 전체 매핑 DB 조회 실패: %s", e)

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
                float(detail.get("change_rate") or 0.0),
                trade_amount=int(detail.get("trade_amount") or 0),
                sector=sec,
            )
            entry["status"] = "active"
            entry["base_price"] = px
            entry["target_price"] = px
            entry["captured_at"] = ""
            entry["reason"] = "확정 데이터 조회"
            pending[nk] = entry
            # _radar_cnsr_order 삭제: _master_stocks_cache의 "_subscribed" 사용
            if nk in es._master_stocks_cache:
                es._master_stocks_cache[nk]["_subscribed"] = True
            ltp[nk] = px
            amt = int(detail.get("trade_amount") or 0)
            lta[nk] = amt
            updated += 1
            continue

        entry["status"] = "active"

        # cur_price
        px = int(detail.get("cur_price") or 0)
        entry["cur_price"] = px
        ltp[nk] = px

        # change
        change = int(detail.get("change") or 0)
        entry["change"] = change

        # change_rate
        rate = float(detail.get("change_rate") or 0.0)
        entry["change_rate"] = rate

        # sign
        sign = str(detail.get("sign") or "").strip()
        if sign:
            entry["sign"] = sign

        # trade_amount
        amt = int(detail.get("trade_amount") or 0)
        entry["trade_amount"] = amt
        lta[nk] = amt

        # high_price
        hp = int(detail.get("high_price") or 0)
        entry["high_price"] = hp

        # strength (from separate dict)
        str_val = strength.get(raw_cd) or strength.get(nk)
        if str_val is not None:
            try:
                strength_str = f"{float(str_val):.2f}"
                entry["strength"] = strength_str
                lst[nk] = strength_str
            except (ValueError, TypeError):
                pass

        # name (from name_map)
        mapped_nm = _nm.get(_base_stk_cd(raw_cd))
        if mapped_nm:
            entry["name"] = mapped_nm

        updated += 1

    _log.info("[타이머] 확정 데이터 메모리 반영 -- %d종목", updated)
    return updated


# ---------------------------------------------------------------------------
# 확정 후 v2 캐시 롤링 파이프라인 (daily_time_scheduler.py에서 이동)
# ---------------------------------------------------------------------------

async def _run_post_confirmed_pipeline(es: ModuleType, eligible_codes: set[str] | None = None) -> None:
    """
    ka10081 도입으로 5일 거래대금 및 최고가를 즉시 추출하므로,
    기존의 복잡한 v2 캐시 롤링 갱신 로직은 제거되었습니다.
    단순히 최종 스냅샷 및 캐시를 저장합니다.
    """
    try:
        await _save_confirmed_cache(es, eligible_codes=eligible_codes)
        _log.info("[타이머] post-confirmed 파이프라인 완료 (롤링 로직 생략)")
    except Exception as exc:
        _log.warning("[타이머] post-confirmed 파이프라인 오류: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 확정 데이터 디스크 캐시 저장
# ---------------------------------------------------------------------------

async def _save_filter_diagnostics_snapshot(
    run_id: str,
    evaluations: list[tuple[object, object]],
    final_excluded_codes: set[str],
    duplicate_codes: set[str],
) -> None:
    try:
        from backend.app.db.database import get_db_connection, get_db_lock
        conn = await get_db_connection()
        rows = []
        for record, evaluation in evaluations:
            parsed = getattr(evaluation, "parsed_fields", {}) or {}
            rows.append((
                run_id,
                record.code,
                record.name,
                parsed.get("marketCode", ""),
                parsed.get("marketName", ""),
                parsed.get("orderWarning", ""),
                parsed.get("state", ""),
                json.dumps(getattr(evaluation, "state_flags", []), ensure_ascii=False),
                parsed.get("auditInfo", ""),
                parsed.get("listCount", ""),
                parsed.get("lastPrice", ""),
                parsed.get("regDay", ""),
                parsed.get("companyClassName", ""),
                parsed.get("nxtEnable", ""),
                1 if getattr(evaluation, "excluded", False) else 0,
                getattr(evaluation, "primary_reason", ""),
                json.dumps(getattr(evaluation, "reasons", []), ensure_ascii=False),
                json.dumps(getattr(evaluation, "diagnostic_flags", []), ensure_ascii=False),
                1 if record.code in duplicate_codes else 0,
                1 if record.code in final_excluded_codes else 0,
            ))
        async with get_db_lock():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_filter_diagnostics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    code TEXT NOT NULL,
                    name TEXT,
                    market_code TEXT,
                    market_name TEXT,
                    order_warning TEXT,
                    state TEXT,
                    state_flags TEXT,
                    audit_info TEXT,
                    list_count TEXT,
                    last_price TEXT,
                    reg_day TEXT,
                    company_class_name TEXT,
                    nxt_enable TEXT,
                    row_excluded INTEGER,
                    primary_reason TEXT,
                    all_reasons TEXT,
                    diagnostic_flags TEXT,
                    duplicate_code INTEGER,
                    final_code_excluded INTEGER
                )
            """)
            await conn.executemany("""
                INSERT INTO stock_filter_diagnostics (
                    run_id, code, name, market_code, market_name, order_warning, state,
                    state_flags, audit_info, list_count, last_price, reg_day,
                    company_class_name, nxt_enable, row_excluded, primary_reason,
                    all_reasons, diagnostic_flags, duplicate_code, final_code_excluded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            await conn.execute("""
                DELETE FROM stock_filter_diagnostics
                WHERE run_id NOT IN (
                    SELECT run_id FROM stock_filter_diagnostics
                    GROUP BY run_id
                    ORDER BY MAX(created_at) DESC
                    LIMIT 10
                )
            """)
            await conn.commit()
        _log.info("[필터진단] 스냅샷 저장 완료 -- run_id=%s, rows=%d", run_id, len(rows))
    except Exception as exc:
        _log.warning("[필터진단] 스냅샷 저장 실패: %s", exc, exc_info=True)


async def _save_confirmed_cache(
    es: ModuleType,
    skip_codes: set[str] | None = None,
    name_map: dict[str, str] | None = None,
    eligible_codes: set[str] | None = None,
) -> bool:
    """현재 메모리 데이터를 master_stocks_table로 디스크 저장.

    저장 직전에 종목명 캐시를 참조하여 name 필드를 보정한다.
    execute_unified_rolling_and_save가 이미 처리한 종목은 skip_codes로 제외하여 중복 저장 방지.
    eligible_codes가 주어지면 해당 종목만 저장 (confirmed_codes 기반 단일 소스 진리).

    Args:
        es: engine_service 모듈 참조
        skip_codes: execute_unified_rolling_and_save에서 이미 처리한 종목 코드 집합
        eligible_codes: 매매적격 종목 코드 집합 (이 외 종목은 저장하지 않음)

    Returns:
        저장 성공 여부.
    """
    import backend.app.services.engine_state as _st
    pending: dict = _st._master_stocks_cache
    if not pending:
        _log.warning("[타이머] 저장할 데이터(_master_stocks_cache)가 비어있음 — 데이터 저장 생략")
        return False

    # 종목명 보정은 불필요: _master_stocks_cache에 이미 name 필드 포함됨

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
        _log.warning("[타이머] 저장 가능한 종목 없음 — 저장데이터 저장 생략")
        return False

    try:
        # DB 저장 전 avg_5d 유효성 체크
        if sum(1 for stock in pending.values() if int(stock.get("avg_5d_trade_amount", 0) or 0) > 0) < 100:
            _log.warning("[타이머] DB 저장 전 avg_5d_trade_amount 비정상 -- 백그라운드 갱신 예정")

        # ── master_stocks_table 저장 (Phase 1.2) ──
        try:
            from backend.app.db.database import get_db_connection

            conn = await get_db_connection()
            date_str = get_current_trading_day_str()

            # master_stocks_table에서 각 종목의 market 정보 가져오기
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
                _log.info("[타이머] skip_codes로 인해 저장할 종목 없음 — 저장 생략")
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

                # 당일 고가 추출 (pending detail 또는 cur_price)
                today_high = detail.get("high_price") or detail.get("cur_price") or 0

                # 1) master_stocks_table에 저장 (UPSERT 적용 - 기존 사용자 커스텀 업종 보존)
                await conn.execute("""
                    INSERT INTO master_stocks_table
                    (code, name, market, sector, cur_price, change, change_rate,
                     trade_amount, high_price, avg_5d_trade_amount, high_5d_price, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        market = excluded.market,
                        sector = CASE WHEN master_stocks_table.sector IS NOT NULL AND master_stocks_table.sector != '' AND master_stocks_table.sector != '미분류' THEN master_stocks_table.sector ELSE excluded.sector END,
                        cur_price = excluded.cur_price,
                        change = excluded.change,
                        change_rate = excluded.change_rate,
                        trade_amount = excluded.trade_amount,
                        high_price = excluded.high_price,
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
                    today_high,
                    detail.get("avg_5d_trade_amount", 0),
                    detail.get("high_5d_price", 0),
                    date_str
                ))

            await conn.commit()
            _log.info("[타이머] master_stocks_table 통합 저장 완료 -- %d종목 (date=%s, skip=%d)", len(all_target_codes), date_str, len(_skip))
        except Exception as e:
            if 'conn' in locals():
                await conn.rollback()
            _log.warning("[타이머] DB 저장 실패 (master_stocks_table): %s", e, exc_info=True)

        return True
    except Exception as exc:
        _log.warning("[타이머] 확정 데이터 DB 저장 실패: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 공통 1일봉챠트 시세 다운로드 파이프라인 (타이머/수동 공용)
# ---------------------------------------------------------------------------

async def _run_confirmed_pipeline(
    es: ModuleType,
    tag: str,
    *,
    check_scheduler: bool = False,
    check_time_guard: bool = False,
) -> dict:
    """공통 1일봉챠트 시세 다운로드 파이프라인 (타이머/수동 공용).

    Steps 1-7: ka10099 전종목 다운로드 → 필터링 → 파싱 → DB저장 →
    ka10081 1일봉챠트 시세 다운로드 → 정규화 → 메모리/DB 저장 → 메모리 교체 → 브로드캐스트.
    """
    from backend.app.core.trading_calendar import get_kst_today_str

    if getattr(es, "_confirmed_refresh_running_confirmed", False):
        _log.info("%s 확정 조회 이미 진행 중 — 생략", tag)
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running_confirmed = True
    es._confirmed_refresh_message = ""

    import backend.app.services.engine_state as _es_state
    _broker_token_registered = False

    try:
        # ── 메모리 전체 초기화 ──
        es._integrated_system_settings_cache["sector_stock_layout"] = []
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        _log.info("%s 메모리 전체 초기화 완료 — 새 데이터로 교체 시작", tag)

        # 스케줄러 토글 체크 (타이머 전용)
        if check_scheduler and not es._integrated_system_settings_cache["scheduler_market_close_on"]:
            _log.info("%s scheduler_market_close_on=OFF — 전체 갱신 생략", tag)
            return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

        from backend.app.core.broker_registry import _create_provider
        _broker_name = str(es._integrated_system_settings_cache.get("broker", "") or "").lower().strip() or "kiwoom"
        _auth_cache: dict[str, object] = {}
        _auth_provider = _create_provider("auth", _broker_name, es._integrated_system_settings_cache, _auth_cache)
        _broker_token = await _auth_provider.get_access_token() if _auth_provider else None
        if _broker_token and _broker_name not in _es_state._broker_tokens:
            _es_state._broker_tokens[_broker_name] = _broker_token
            _broker_token_registered = True
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            broadcast_engine_status()
        _sector = _create_provider("stock", _broker_name, es._integrated_system_settings_cache, _auth_cache)

        # ── Step 1: ka10099 전종목 리스트 다운로드 ──
        _log.info("%s Step 1 시작 — ka10099 전종목 리스트 다운로드", tag)
        _broadcast_confirmed_progress(0, 0, message="전종목 목록 갱신 중...", step=1)
        try:
            from backend.app.core.broker_providers import UnifiedStockRecord
            records: list[UnifiedStockRecord] = await _sector.fetch_all_stocks()
            if not records:
                _log.warning("%s ka10099 결과 비어있음 — 중단", tag)
                return {"fetched": 0, "failed": 0, "cached": False}
            kospi_count = sum(1 for r in records if r.market_code == "0")
            kosdaq_count = sum(1 for r in records if r.market_code == "10")
            other_count = len(records) - kospi_count - kosdaq_count
            _log.info("%s Step 1 완료 — 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)", tag, len(records), kospi_count, kosdaq_count, other_count)
        except Exception as exc:
            _log.warning("%s ka10099 통합 조회 실패: %s", tag, exc, exc_info=True)
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 2: 적격 종목 필터링 ──
        _log.info("%s Step 2 시작 — 적격 종목 필터링", tag)
        _broadcast_confirmed_progress(0, 0, message="2단계: 매매부적격종목 필터링 중...", step=2)
        try:
            confirmed_codes: set[str] = set()
            filter_reasons: dict[str, int] = {}
            all_reason_counts: dict[str, int] = {}
            state_flag_counts: dict[str, int] = {}
            diagnostic_counts: dict[str, int] = {}
            code_groups: dict[str, list[tuple[object, object]]] = {}
            row_evaluations: list[tuple[object, object]] = []
            from backend.app.core.stock_filter import evaluate_stock_filter
            for r in records:
                evaluation = evaluate_stock_filter(r.raw_item, r.code)
                row_evaluations.append((r, evaluation))
                code_groups.setdefault(r.code, []).append((r, evaluation))
                for reason in evaluation.reasons:
                    all_reason_counts[reason] = all_reason_counts.get(reason, 0) + 1
                for state_flag in evaluation.state_flags:
                    state_flag_counts[state_flag] = state_flag_counts.get(state_flag, 0) + 1
                for diagnostic_flag in evaluation.diagnostic_flags:
                    diagnostic_counts[diagnostic_flag] = diagnostic_counts.get(diagnostic_flag, 0) + 1

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
                    filter_reasons[primary_reason] = filter_reasons.get(primary_reason, 0) + 1
                else:
                    confirmed_codes.add(code)

            run_id = f"{get_current_trading_day_str()}-{int(time.time())}"
            await _save_filter_diagnostics_snapshot(run_id, row_evaluations, final_excluded_codes, duplicate_codes)

            raw_rows = len(records)
            unique_codes = len(code_groups)
            excluded_count = len(final_excluded_codes)
            pct = (excluded_count / unique_codes * 100) if unique_codes else 0
            _log.info(
                "%s Step 2 완료 — raw_rows=%d, unique_codes=%d, duplicate_codes=%d, conflict_codes=%d, 통과=%d, 제외=%d, 제외 사유: %s",
                tag, raw_rows, unique_codes, len(duplicate_codes), len(conflict_codes), len(confirmed_codes), excluded_count, filter_reasons,
            )
            if all_reason_counts:
                _log.info("%s 전체 부적격 사유 집계: %s", tag, dict(sorted(all_reason_counts.items(), key=lambda x: x[1], reverse=True)[:20]))
            if state_flag_counts:
                _log.info("%s state 플래그 집계: %s", tag, dict(sorted(state_flag_counts.items(), key=lambda x: x[1], reverse=True)[:20]))
            if diagnostic_counts:
                _log.info("%s 진단 플래그 집계: %s", tag, dict(sorted(diagnostic_counts.items(), key=lambda x: x[1], reverse=True)[:20]))
            if duplicate_codes:
                duplicate_preview = sorted(duplicate_codes)[:20]
                _log.warning("%s ka10099 동일 code 중복 감지 — %d종목, 예시=%s", tag, len(duplicate_codes), duplicate_preview)
            if conflict_codes:
                conflict_preview = sorted(conflict_codes)[:20]
                _log.warning("%s ka10099 동일 code 판정 충돌 — %d종목, 예시=%s", tag, len(conflict_codes), conflict_preview)
            _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 완료: 총 {unique_codes}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)

            summary_str = f"전체 {unique_codes}종목(raw {raw_rows}행) → 적격 {len(confirmed_codes)}종목 (제외 {excluded_count}종목, {pct:.1f}%, 중복 {len(duplicate_codes)}종목)"
            if filter_reasons:
                top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
                _log.info("%s 주요 부적격 사유 (Top 5): %s", tag, dict(top_reasons))
                reason_strs = []
                for k, v in top_reasons:
                    k_clean = k.split("(")[-1].replace(")", "") if "(" in k else k.split("=")[-1]
                    reason_strs.append(f"{k_clean} {v}개")
                summary_str += " | 주요 부적격: " + ", ".join(reason_strs)
            import json as _json
            _meta_top = [
                {"k": k.split("(")[-1].replace(")", "") if "(" in k else k.split("=")[-1], "v": v}
                for k, v in sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
            ] if filter_reasons else []
            filter_summary_meta = _json.dumps({
                "raw_rows": raw_rows,
                "unique_codes": unique_codes,
                "excluded_count": excluded_count,
                "pct": round(pct, 1),
                "duplicate_count": len(duplicate_codes),
                "top_reasons": _meta_top,
            })
        except Exception as exc:
            _log.warning("%s Step 2 필터링 실패: %s", tag, exc, exc_info=True)
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 3: 적격 종목 파싱/매칭 ──
        _log.info("%s Step 3 시작 — 적격 종목 파싱 (%d종목)", tag, len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="종목 정보 파싱 중...", step=3)
        try:
            name_map: dict[str, str] = {}
            market_map: dict[str, str] = {}
            for r in records:
                if r.code in confirmed_codes:
                    name_map[r.code] = r.name
                    market_map[r.code] = r.market_code
            _log.info("%s Step 3 완료 — %d종목 파싱/매칭", tag, len(name_map))
        except Exception as exc:
            _log.warning("%s Step 3 파싱/매칭 실패: %s", tag, exc, exc_info=True)
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 4: DB 저장 + 메모리 캐시 동기화 + 레이아웃 ──
        _log.info("%s Step 4 시작 — 캐시 저장 (%d종목)", tag, len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="캐시 저장 중...", step=4)
        try:
            from backend.app.db.database import get_db_connection as _get_conn, get_db_lock
            _conn = await _get_conn()

            if confirmed_codes:
                placeholders = ",".join("?" for _ in confirmed_codes)
                confirmed_codes_list = list(confirmed_codes)

                async with get_db_lock():
                    # 1) 적격 아닌 종목 DELETE
                    await _conn.execute(f"DELETE FROM master_stocks_table WHERE code NOT IN ({placeholders})", confirmed_codes_list)
                    # 2) UPSERT (기존 sector 보존)
                    insert_values = [(r.code, r.name, r.market_code, 1 if r.nxt_enable else 0) for r in records if r.code in confirmed_codes]
                    if insert_values:
                        await _conn.executemany("""INSERT INTO master_stocks_table (code, name, market, nxt_enable) VALUES (?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET name = excluded.name, market = excluded.market, nxt_enable = excluded.nxt_enable""", insert_values)
                    # 3) stock_5d_array 정리
                    cursor = await _conn.execute("SELECT code FROM master_stocks_table")
                    master_codes = set(row[0] for row in await cursor.fetchall())
                    master_placeholders = ",".join("?" for _ in master_codes)
                    master_codes_list = list(master_codes)
                    if master_codes:
                        await _conn.execute(f"DELETE FROM stock_5d_array WHERE code NOT IN ({master_placeholders})", master_codes_list)
                    # 4) filter_summary_meta를 같은 트랜잭션에 저장 (SSOT: 종목수는 master_stocks_table, 메타만 저장)
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
                    # 7) 단일 commit
                    await _conn.commit()

                # 8) 메모리 캐시 동기화 — confirmed_codes 전체 보장 생성 (SSOT: cache = confirmed_codes)
                import backend.app.services.engine_state as _st
                keys_to_delete = [cd for cd in list(_st._master_stocks_cache.keys()) if cd not in confirmed_codes]
                for cd in keys_to_delete:
                    _st._master_stocks_cache.pop(cd, None)
                for r in records:
                    if r.code in confirmed_codes:
                        if r.code not in _st._master_stocks_cache:
                            _st._master_stocks_cache[r.code] = {
                                "name": r.name,
                                "market": r.market_code,
                                "nxt_enable": bool(r.nxt_enable),
                                "cur_price": 0,
                                "change": 0,
                                "change_rate": 0.0,
                                "sign": "3",
                                "trade_amount": 0,
                                "high_price": 0,
                                "avg_5d_trade_amount": 0,
                                "high_5d_price": 0,
                                "date": "",
                                "volume": 0,
                                "sector": "미분류",
                                "status": "active",
                            }
                        else:
                            _st._master_stocks_cache[r.code]["market"] = r.market_code
                            _st._master_stocks_cache[r.code]["nxt_enable"] = bool(r.nxt_enable)

                # 5) sector 동기화 — 메모리 캐시 재구성 이후에 실행 (모든 종목이 캐시에 존재해야 sector 반영 가능)
                from backend.app.core.stock_classification_data import sync_sector_from_custom_sectors
                await sync_sector_from_custom_sectors()

            # filter_summary_meta 메모리 설정 — cache 동기화 완료 후 설정 (DB는 같은 트랜잭션에 이미 저장됨)
            _es_state.state.latest_filter_summary_meta = filter_summary_meta

            all_codes = list(confirmed_codes)
            await _update_layout_cache(es, all_codes, name_map)
            _log.info("%s Step 4 완료 — 저장 완료 (%d종목)", tag, len(confirmed_codes))

            try:
                from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
                await broadcast_stock_classification_changed()
            except Exception as e:
                _log.warning("Failed to broadcast filter summary: %s", e)
        except Exception as exc:
            _log.warning("%s Step 4 저장 실패: %s", tag, exc, exc_info=True)
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── 시간 가드 (타이머 전용) ──
        if check_time_guard:
            from backend.app.services.daily_time_scheduler import is_heavy_operation_allowed
            if not await is_heavy_operation_allowed():
                _log.info("%s 안전 구역 외 시간대 — Step 5 스킵", tag)
                return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 5: ka10081 전종목 1일봉챠트 시세 다운로드 ──
        _log.info("[1일봉챠트 시세 다운로드] 다운로드 시작 (%d종목)", len(all_codes))
        qry_dt = get_kst_today_str()
        total = len(all_codes)
        _main_loop = asyncio.get_running_loop()

        _broadcast_confirmed_progress(0, total, message=f"1일봉챠트 시세 다운로드 중 (0/{total:,}, 0%)", step=5)

        def _on_progress(cur: int, tot: int) -> None:
            _pct = int(cur / total * 100) if total > 0 else 0
            _broadcast_confirmed_progress(cur, total, message=f"1일봉챠트 시세 다운로드 중 ({cur:,}/{total:,}, {_pct}%)", eta_sec=(total - cur) * 1.0, step=5, _loop=_main_loop)

        try:
            confirmed = await _sector.fetch_all_stocks_daily_confirmed(all_codes, qry_dt, interval_sec=0.33, on_progress=_on_progress)
        except Exception as exc:
            _log.warning("[1일봉챠트 시세 다운로드] 전종목 조회 실패: %s", exc, exc_info=True)
            confirmed = {}

        fetched = len(confirmed)
        failed = total - fetched
        success_rate = (fetched / total * 100) if total else 0
        _log.info("[1일봉챠트 시세 다운로드] 다운로드 완료 — 성공 %d, 실패 %d (%.1f%%)", fetched, failed, success_rate)
        if failed > 0 and success_rate < 99.0:
            _log.warning("[1일봉챠트 시세 다운로드] 실패율 높음: %d/%d (%.1f%%)", failed, total, 100 - success_rate)

        # 데이터 정규화 (공통: 타이머/수동 모두 적용)
        if confirmed:
            normalized_confirmed = {}
            for cd, val in confirmed.items():
                normalized_confirmed[cd] = {
                    "cur_price": val.get("close") or val.get("cur_price") or 0,
                    "trade_amount": val.get("value") or val.get("trade_amount") or 0,
                    "high_price": val.get("high") or val.get("high_price") or 0,
                    "volume": val.get("volume") or 0,
                    "change": val.get("change") or 0,
                    "change_rate": val.get("rate") or val.get("change_rate") or 0.0,
                    "sign": val.get("sign") or "3",
                }
            await _apply_confirmed_to_memory(es, normalized_confirmed, {}, name_map=name_map, confirmed_codes=confirmed_codes)

        # ── 단일 벌크 트랜잭션: 5일봉 롤링 및 DB 저장 ──
        cached = False
        if confirmed:
            _log.info("%s 단일 벌크 트랜잭션 시작", tag)
            await execute_unified_rolling_and_save(es, normalized_confirmed, name_map=name_map)
            _log.info("%s 단일 벌크 트랜잭션 완료", tag)
            cached = True

        # ── 종목분류 페이지 갱신 브로드캐스트 ──
        try:
            from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
            await broadcast_stock_classification_changed()
            _log.info("%s 종목분류 페이지 갱신 브로드캐스트 완료", tag)
        except Exception as _bc_err:
            _log.warning("%s 종목분류 페이지 갱신 브로드캐스트 실패(무시): %s", tag, _bc_err)

        if failed > 0:
            _broadcast_confirmed_progress(total, total, message=f"⚠️ 1일봉챠트 시세 다운로드 부분 완료 ({fetched:,}/{total:,}) — {failed}종목 실패", step=5, failed_count=failed)
        else:
            _broadcast_confirmed_progress(total, total, message=f"1일봉챠트 시세 다운로드 완료 ({fetched:,}/{total:,})", step=5)


        # ── 후처리 ──
        _broadcast_confirmed_progress(total, total, message="5일 거래대금 계산 중...", step=5)
        await _run_post_confirmed_pipeline(es, eligible_codes=confirmed_codes)
        if cached:
            final_eligible = confirmed_codes
            if final_eligible:
                to_remove = [cd for cd, entry in es._master_stocks_cache.items() if entry.get("_subscribed", False) and cd not in final_eligible]
                for cd in to_remove:
                    if cd in es._master_stocks_cache:
                        es._master_stocks_cache[cd].pop("_subscribed", None)
                subscribed_count = sum(1 for entry in es._master_stocks_cache.values() if entry.get("_subscribed", False))
                _log.info("%s Step 6 메모리 교체 완료 — subscribed=%d종목", tag, subscribed_count)
        else:
            _log.warning("%s cached=False — 메모리 교체 생략", tag)

        # ── Step 7: 업종순위 재계산 + WS 브로드캐스트 ──
        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import notify_desktop_sector_stocks_refresh
            await notify_desktop_sector_stocks_refresh(force=True)
            await recompute_sector_summary_now()
            _log.info("%s 업종순위 재계산 + 실시간 화면전송 완료", tag)
        except Exception as _ws_err:
            _log.warning("%s 업종순위 재계산 실패: %s", tag, _ws_err, exc_info=True)

        if cached:
            _log.info("[1일봉챠트 시세 다운로드] 전체 완료 — ka10099: %d종목 | 적격: %d종목 | 1일봉: %d/%d종목", len(all_codes), len(final_eligible) if 'final_eligible' in locals() else 0, fetched, total)
        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        if _broker_token_registered:
            _es_state._broker_tokens.pop(_broker_name, None)
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            broadcast_engine_status()
        es._confirmed_refresh_running_confirmed = False
        es._confirmed_refresh_message = ""


# ---------------------------------------------------------------------------
# 통합 확정 데이터 조회 (20:30)
# ---------------------------------------------------------------------------

async def fetch_unified_confirmed_data(es: ModuleType) -> dict:
    """20:30 타이머 통합 확정 조회 — _run_confirmed_pipeline 위임."""
    return await _run_confirmed_pipeline(es, "[타이머]", check_scheduler=True, check_time_guard=True)


# ---------------------------------------------------------------------------
# 통합 확정 조회 헬퍼
# ---------------------------------------------------------------------------

async def _update_layout_cache(
    es: ModuleType,
    all_codes: list[str],
    name_map: dict[str, str],
) -> None:
    """confirmed_codes 기준으로 레이아웃 캐시를 완전 재구성.

    - 부적격이 된 종목은 레이아웃에서 제거된다.
    - stock_classification.json의 최신 업종 매핑이 전체 종목에 적용된다.
    - 섹터 헤더가 없는 종목("미분류")도 레이아웃에 포함된다.
    """
    # sector_layout 캐시 저장 삭제 (master_stocks_table sector 컬럼으로 대체)

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
        _log.warning("[레이아웃] 전체 매핑 DB 조회 실패: %s", e)

    # 전체 종목을 섹터별로 그룹핑 (stock_classification.json 최신 매핑 적용)
    sector_groups: dict[str, list[str]] = {}
    for cd in all_codes:
        sec = None
        import backend.app.services.engine_state as _st
        entry = _st._master_stocks_cache.get(cd)
        if entry and "sector" in entry:
            sec = entry["sector"]
        # 2) DB 매핑 확인
        if not sec:
            sec = db_mapping.get(_base_stk_cd(cd))
        # 3) 기본값
        if not sec:
            sec = "미분류"

        sector_groups.setdefault(sec, []).append(cd)

    # 섹터 내 종목 정렬 (재현성 보장)
    for sec in sector_groups:
        sector_groups[sec].sort()

    # 섹터 순서: 기존 레이아웃의 섹터 순서를 최대한 유지하고 신규 섹터는 뒤에 추가
    old_layout: list[tuple[str, str]] = es._integrated_system_settings_cache["sector_stock_layout"]
    old_sector_order = list(dict.fromkeys(v for t, v in old_layout if t == "sector"))

    new_sectors = [s for s in sector_groups if s not in old_sector_order]
    final_sector_order = [s for s in old_sector_order if s in sector_groups] + new_sectors

    # 레이아웃 재구성
    new_layout: list[tuple[str, str]] = []
    for sec in final_sector_order:
        new_layout.append(("sector", sec))
        for cd in sector_groups[sec]:
            new_layout.append(("code", cd))

    es._integrated_system_settings_cache["sector_stock_layout"] = new_layout
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache(new_layout)
    _log.info(
        "[타이머] 레이아웃 저장데이터 완전 재구성 — %d종목, %d업종",
        len(all_codes), len(final_sector_order),
    )


# ---------------------------------------------------------------------------
# 수동 1일봉챠트 시세 및 5일봉챠트 다운로드
# ---------------------------------------------------------------------------

async def fetch_confirmed_data_only() -> dict:
    """수동 매매적격종목 1일봉챠트 시세 다운로드 파이프라인 — _run_confirmed_pipeline 위임."""
    from backend.app.services import engine_service as es
    return await _run_confirmed_pipeline(es, "[수동 확정시세]")




async def fetch_5d_data_only() -> dict:
    """수동 5일봉 거래대금,고가 다운로드 파이프라인.
    
    DB의 master_stocks_table에 등록된 매매적격종목을 대상으로
    개별 종목의 5일 고가 및 거래대금 데이터를 다운로드하여 DB 및 메모리에 저장합니다.
    execute_unified_rolling_and_save()를 사용하여 순서 보장.
    """
    from backend.app.services import engine_service as es
    from backend.app.core.broker_factory import get_router
    from backend.app.core.trading_calendar import get_kst_today_str, get_current_trading_day_str

    # 중복 실행 방지
    if getattr(es, "_confirmed_refresh_running_5d", False):
        _log.info("[5일봉챠트 거래대금,고가 다운로드] 다운로드 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running_5d = True
    es._confirmed_refresh_message = ""

    import backend.app.services.engine_state as _es_state
    _broker_token_registered = False

    try:
        from backend.app.core.broker_registry import _create_provider
        _broker_name = str(es._integrated_system_settings_cache.get("broker", "") or "").lower().strip() or "kiwoom"
        _auth_cache: dict[str, object] = {}
        _auth_provider = _create_provider("auth", _broker_name, es._integrated_system_settings_cache, _auth_cache)
        _broker_token = await _auth_provider.get_access_token() if _auth_provider else None
        if _broker_token and _broker_name not in _es_state._broker_tokens:
            _es_state._broker_tokens[_broker_name] = _broker_token
            _broker_token_registered = True
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            broadcast_engine_status()
        _sector = _create_provider("stock", _broker_name, es._integrated_system_settings_cache, _auth_cache)

        # ── 메모리 캐시에서 매매적격종목 코드 리스트 로드 (SSOT: DB에서만 로드된 캐시 사용) ──
        _log.info("[5일봉챠트 거래대금,고가 다운로드] 매매적격종목 목록 로드 시작")
        import backend.app.services.engine_state as _st
        all_codes = [cd for cd, entry in _st._master_stocks_cache.items() if entry.get("status") == "active"]
        total = len(all_codes)
        
        _log.info("[5일봉챠트 거래대금,고가 다운로드] 대상 적격 종목 수: %d", total)
        if total == 0:
            _log.warning("[5일봉챠트 거래대금,고가 다운로드] 대상 종목 없음 — 중단")
            es._confirmed_refresh_running_5d = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── stock_5d_array 전체 삭제 (수동 다운로드는 무조건 재다운로드) ─────────
        from backend.app.db.database import get_db_connection, get_db_lock
        conn = await get_db_connection()
        try:
            async with get_db_lock():
                await conn.execute("DELETE FROM stock_5d_array")
                await conn.commit()
            _log.info("[5일봉챠트 거래대금,고가 다운로드] stock_5d_array 전체 삭제 후 재다운로드")
        except Exception as e:
            _log.warning("[5일봉챠트 거래대금,고가 다운로드] 전체 데이터 삭제 실패: %s", e)

        # ── 개별 5일봉 데이터 다운로드 ───────────────────────────────────────
        _log.info("[5일봉챠트 거래대금,고가 다운로드] 다운로드 시작 (%d종목)", total)
        _broadcast_confirmed_progress(0, total, message=f"5일봉챠트 거래대금,고가 다운로드 중 (0/{total:,}, 0%)", step=5)

        fetched = 0
        failed = 0
        confirmed_5d = {}
        qry_dt = get_kst_today_str()

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
                    
                    if amounts_5d and highs_5d:
                        confirmed_5d[nk] = {
                            "amts_5d_array": amounts_5d,
                            "highs_5d_array": highs_5d,
                        }
                        fetched += 1
                    else:
                        failed += 1
                        _log.warning("[5일봉챠트 거래대금,고가 다운로드] 데이터 비어있음 [%d/%d] %s", idx + 1, total, base_cd)
                else:
                    failed += 1
                    _log.warning("[5일봉챠트 거래대금,고가 다운로드] API 응답 없음 [%d/%d] %s", idx + 1, total, base_cd)

            except Exception as e:
                failed += 1
                _log.warning("[5일봉챠트 거래대금,고가 다운로드] 예외 발생 [%d/%d] %s: %s", idx + 1, total, base_cd, e)

            # 진행률 브로드캐스트 (매 종목)
            pct = int((idx + 1) / total * 100) if total else 0
            _broadcast_confirmed_progress(
                idx + 1, total,
                message=f"5일봉챠트 거래대금,고가 다운로드 중 ({idx + 1:,}/{total:,}, {pct}%)",
                step=5
            )
            _log.info("[5일봉챠트 거래대금,고가 다운로드] 진행 중: %d/%d (%d%%)", idx + 1, total, pct)

            # Rate limiting
            await asyncio.sleep(0.33)

        # ── stock_5d_array 직접 INSERT (5일치 전체 저장) ───────────────────────
        if confirmed_5d:
            _log.info("[5일봉챠트 거래대금,고가 다운로드] stock_5d_array 직접 INSERT — %d종목", len(confirmed_5d))
            
            date_str = get_kst_today_str()
            array_5d_params = []
            master_update_params = []
            
            for cd, data in confirmed_5d.items():
                amts_5d = data.get("amts_5d_array") or []
                highs_5d = data.get("highs_5d_array") or []
                
                # 5일평균, 5일최고가 계산 (NULL 제외)
                valid_amts = [a for a in amts_5d if a is not None and a > 0]
                avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else 0
                
                valid_highs = [h for h in highs_5d if h is not None and h > 0]
                high_5d = max(valid_highs) if valid_highs else 0
                
                # stock_5d_array INSERT 파라미터
                array_5d_params.append((
                    cd, date_str,
                    amts_5d[0] if len(amts_5d) > 0 else None,
                    amts_5d[1] if len(amts_5d) > 1 else None,
                    amts_5d[2] if len(amts_5d) > 2 else None,
                    amts_5d[3] if len(amts_5d) > 3 else None,
                    amts_5d[4] if len(amts_5d) > 4 else None,
                    highs_5d[0] if len(highs_5d) > 0 else None,
                    highs_5d[1] if len(highs_5d) > 1 else None,
                    highs_5d[2] if len(highs_5d) > 2 else None,
                    highs_5d[3] if len(highs_5d) > 3 else None,
                    highs_5d[4] if len(highs_5d) > 4 else None,
                ))
                
                # master_stocks_table UPDATE 파라미터
                master_update_params.append((avg_5d, high_5d, cd))
            
            # 단일 트랜잭션으로 저장
            async with get_db_lock():
                await conn.executemany(
                    """INSERT OR REPLACE INTO stock_5d_array
                    (code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                     day1_high, day2_high, day3_high, day4_high, day5_high)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    array_5d_params
                )
                await conn.executemany(
                    """UPDATE master_stocks_table
                    SET avg_5d_trade_amount = ?, high_5d_price = ?
                    WHERE code = ?""",
                    master_update_params
                )
                await conn.commit()
            
            _log.info("[수동 5일봉] DB 저장 완료 — %d종목", len(confirmed_5d))
            
            # 메모리 캐시 업데이트
            for cd, data in confirmed_5d.items():
                amts_5d = data.get("amts_5d_array") or []
                highs_5d = data.get("highs_5d_array") or []
                
                valid_amts = [a for a in amts_5d if a is not None and a > 0]
                avg_5d = sum(valid_amts) // len(valid_amts) if valid_amts else 0
                
                valid_highs = [h for h in highs_5d if h is not None and h > 0]
                high_5d = max(valid_highs) if valid_highs else 0
                
                if cd in es._master_stocks_cache:
                    es._master_stocks_cache[cd]["avg_5d_trade_amount"] = avg_5d
                    es._master_stocks_cache[cd]["high_5d_price"] = high_5d
            
            _log.info("[5일봉챠트 거래대금,고가 다운로드] 메모리 캐시 업데이트 완료")

        success_rate = (fetched / total * 100) if total else 0
        _log.info("[5일봉챠트 거래대금,고가 다운로드] 다운로드 완료 — 성공 %d종목, 실패 %d종목 (%.1f%%)", fetched, failed, success_rate)

        if failed > 0:
            _broadcast_confirmed_progress(total, total, message=f"⚠️ 5일봉챠트 거래대금,고가 다운로드 부분 완료 ({fetched:,}/{total:,}) — {failed}종목 실패", step=5, failed_count=failed)
        else:
            _broadcast_confirmed_progress(total, total, message=f"5일봉챠트 거래대금,고가 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # 종목분류 브로드캐스트 (프론트엔드 자동갱신)
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        await broadcast_stock_classification_changed()

        # 후처리
        await _run_post_confirmed_pipeline(es, eligible_codes=set(all_codes))

        # 업종순위 재계산 (내부에서 notify_desktop_sector_scores + notify_buy_targets_update 호출)
        # 순서: sector-stocks-refresh → recompute_sector_summary_now
        # sectorStocks가 먼저 갱신되어야 buy-targets-delta merge 시 최신 데이터 참조 가능
        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_stocks_refresh,
            )
            await notify_desktop_sector_stocks_refresh(force=True)
            await recompute_sector_summary_now()
            _log.info("[5일봉챠트 거래대금,고가 다운로드] 업종순위 재계산 + 실시간 화면전송 완료")
        except Exception as _ws_err:
            _log.warning("[5일봉챠트 거래대금,고가 다운로드] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)

        return {"fetched": fetched, "failed": failed, "cached": False}
    finally:
        if _broker_token_registered:
            _es_state._broker_tokens.pop(_broker_name, None)
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            broadcast_engine_status()
        es._confirmed_refresh_running_5d = False
        es._confirmed_refresh_message = ""
