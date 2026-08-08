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
from backend.app.core.broker_providers import (
    AuthProvider,
    RawStockFetchResult,
)
if TYPE_CHECKING:
    from backend.app.core.stock_filter import StockFilterEvaluation
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    is_nxt_enabled,
)
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

    연결 관리자의 증권사별 라우팅에 위임하여 각 증권사 규격으로 해지 메시지 전송.
    정상 종료 경로(disconnect_all)와 동일한 구조 (P23 일관성).

    Returns:
        {"removed": int, "failed": int, "skipped": bool}
    """
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected():
        logger.warning("[스케줄] KRX 장마감 구독해지 생략 — 실시간 미연결")
        return {"removed": 0, "failed": 0, "skipped": True}

    krx_codes = _get_krx_only_codes()
    if not krx_codes:
        logger.info("[스케줄] KRX 장마감 구독해지 대상 없음")
        return {"removed": 0, "failed": 0, "skipped": False}

    # 원본 6자리 코드 그대로 전달 — 각 커넥터가 자사 규격으로 변환 (P10 SSOT).
    # 장마감 경로에서 변환하면 연결 관리자 _sub_codes 매칭 실패 → 해지 누락 발생.
    try:
        ok = await ws.unsubscribe_stocks(krx_codes)
    except Exception as exc:
        logger.warning(
            "[스케줄] KRX 장마감 구독해지 오류: %s", exc, exc_info=True,
        )
        return {"removed": 0, "failed": len(krx_codes), "skipped": False}

    if ok:
        # 성공 — 전종목 마스터 캐시에서 "_subscribed" 제거
        # (연결 관리자는 _sub_codes만 제거하므로 장마감 경로에서 별도 수행)
        for cd in krx_codes:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
        removed = len(krx_codes)
        failed = 0
    else:
        # 실패 — 전종목 마스터 캐시의 "_subscribed" 유지
        removed = 0
        failed = len(krx_codes)
        logger.warning(
            "[스케줄] KRX 장마감 구독해지 실패 — %d종목 유지", len(krx_codes),
        )

    logger.info(
        "[스케줄] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목",
        removed, failed,
    )
    return {"removed": removed, "failed": failed, "skipped": False}


# ---------------------------------------------------------------------------
# NXT 종목 REMOVE (NXT 종료 시 — krx_end 대칭 구조)
# ---------------------------------------------------------------------------


def _get_nxt_subscribed_codes() -> list[str]:
    """전종목 마스터 캐시에서 NXT 종목(nxt_enable=True) 중 구독 중인 것만 추출.

    Returns:
        6자리 정규화된 NXT 종목코드 리스트 (중복 없음).
    """
    result: list[str] = []
    seen: set[str] = set()

    subscribed_codes = {cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_subscribed", False)}
    for raw_cd in subscribed_codes:
        base = _base_stk_cd(raw_cd)
        if not base or base in seen:
            continue
        seen.add(base)
        if is_nxt_enabled(base):
            result.append(base)

    return result


async def remove_nxt_stocks() -> dict:
    """NXT 종목(nxt_enable=True)만 선택적 REMOVE.

    remove_krx_only_stocks()와 대칭 구조 (P23 일관성).
    NXT 종료 시각에 호출 — KRX 단독 종목은 krx_end에서 이미 해지됨.

    Returns:
        {"removed": int, "failed": int, "skipped": bool}
    """
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected():
        logger.warning("[스케줄] NXT 종료 구독해지 생략 — 실시간 미연결")
        return {"removed": 0, "failed": 0, "skipped": True}

    nxt_codes = _get_nxt_subscribed_codes()
    if not nxt_codes:
        logger.info("[스케줄] NXT 종료 구독해지 대상 없음")
        return {"removed": 0, "failed": 0, "skipped": False}

    try:
        ok = await ws.unsubscribe_stocks(nxt_codes)
    except Exception as exc:
        logger.warning("[스케줄] NXT 종료 구독해지 오류: %s", exc, exc_info=True)
        return {"removed": 0, "failed": len(nxt_codes), "skipped": False}

    if ok:
        for cd in nxt_codes:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
        removed = len(nxt_codes)
        failed = 0
    else:
        removed = 0
        failed = len(nxt_codes)
        logger.warning("[스케줄] NXT 종료 구독해지 실패 — %d종목 유지", len(nxt_codes))

    logger.info("[스케줄] NXT 종료 구독해지 완료 — 해지 %d종목, 실패 %d종목", removed, failed)
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
    """자동 일봉 확정시세 저장 + 메모리 반영.

    DB 저장은 ``market_close_storage.save_daily_confirmed`` 에 위임 (단일 트랜잭션).
    메모리 반영은 저장 성공 후 본 함수에서 수행 — 저장 모듈이 메모리를 직접 건드리지 않도록
    분리 (설계 5.4). 메모리 반영은 ``_apply_confirmed_to_memory`` 로 통합·정식 정리 (세션 3, 설계 3.3).
    메모리 반영 실패 시 DB 커밋 범위 재로드 회복, 재로드 실패 시 후속 계산 중단 (설계 3.3).

    Args:
        confirmed: {종목코드: {cur_price, change, change_rate, trade_amount, high_price, high_5d_price}}
        name_map: {6자리 종목코드: 종목명} — 종목명 보정용
        qry_dt: API 조회일 (YYYYMMDD) = 가장 최근 확정된 거래일.
            stock_5d_bars의 dt로 저장되며, master_stocks_table.date에도 동일 기준 적용 (P10/P22).

    Returns:
        저장 성공 여부. 메모리 반영·재로드 회복까지 성공해야 True.
    """
    from backend.app.services.market_close_storage import save_daily_confirmed

    # date_str = "데이터 기준일" — qry_dt(가장 최근 확정된 거래일 = 소속 거래일의 직전 거래일) 우선 (P10/P22).
    # qry_dt는 항상 직전 거래일이므로, 장 전/장 후 실행 모두 date=직전 거래일(예: 07-14)이 저장됨.
    # 이 값이 master_stocks_table.date와 메모리 캐시 date에 사용되며,
    # retry_pipeline_catchup_after_bootstrap의 스킵 판단도 동일 기준(직전 거래일)으로 비교함 (P10 SSOT).
    date_str = qry_dt or get_current_trading_day_str()
    _nm = name_map or {}

    if not date_str:
        logger.warning("[데이터] 저장 실패 — 현재 거래일 확인 불가 (P20 폴백 금지)")
        return False

    # DB 저장 — 단일 트랜잭션 (성공·검증 완료 집합 전부 성공 또는 전부 롤백, 설계 4.3)
    result = await save_daily_confirmed(confirmed, qry_dt=qry_dt, name_map=name_map)
    if not result["success"]:
        return False

    # 메모리 반영 (저장 성공 후) — _apply_confirmed_to_memory로 통합·정식 정리 (세션 3, 설계 3.3).
    # 저장 성공 결과(saved_codes·derived·date_str)만 메모리에 반영 — 이중 반영 금지 (P10 SSOT).
    saved_codes = set(result["saved_codes"])
    try:
        await _apply_confirmed_to_memory(
            confirmed, {}, name_map=name_map,
            confirmed_codes=saved_codes,
            date_str=date_str, derived=result["derived"],
        )
    except Exception as mem_err:
        # 메모리 반영 실패 — DB 재로드 회복 (설계 3.3). DB 재저장 금지.
        logger.warning("[데이터] 메모리 반영 실패 — DB 재로드 회복: %s", mem_err, exc_info=True)
        try:
            await _reload_confirmed_from_db(saved_codes)
        except Exception as reload_err:
            # 재로드 실패 — 업종 계산·매매 판단·화면 확정 중단 (설계 3.3)
            logger.error("[데이터] DB 재로드 실패 — 후속 계산 중단: %s", reload_err, exc_info=True)
            return False
    return True


async def _apply_confirmed_to_memory(
    confirmed: dict[str, dict],
    strength: dict[str, float],
    name_map: dict[str, str] | None = None,
    confirmed_codes: set[str] | None = None,
    *,
    date_str: str = "",
    derived: dict[str, tuple[int | None, int | None]] | None = None,
) -> int:
    """확정 데이터를 메모리 캐시에 반영. 0값은 기존 데이터를 덮지 않음.

    세션 3 정식 정리 — DB 커밋 성공 결과만 반영 (설계 3.3).
    ``date_str`` 과 ``derived`` 는 저장 모듈(``market_close_storage``)의 저장 성공 결과에서 전달되며,
    본 함수에서 한 번만 메모리에 적용한다 (이중 반영 금지, P10 SSOT).
    실시간 필드(strength·sign·captured_at·base_price·target_price·_subscribed 등)는 건드리지 않아 보존된다.

    Args:
        confirmed: {종목코드: {cur_price, change, change_rate, sign, volume, trade_amount, prev_close}}
        strength: {종목코드: 체결강도 float}
        name_map: {6자리 종목코드: 종목명} — 전종목 통합 조회(ka10099)에서 조회한 매핑. 있으면 모든 엔트리 종목명 갱신.
        confirmed_codes: 매매적격 종목 코드 집합 — 이 외 코드는 메모리 캐시에 반영하지 않음 (SSOT).
        date_str: DB 커밋 성공 결과의 데이터 기준일(YYYYMMDD). 비어있으면 date 필드를 갱신하지 않음.
        derived: DB 커밋 성공 결과의 5일 파생값 {code: (avg_5d, high_5d)}.
            None 이면 파생값을 반영하지 않음. 전달 시 저장 결과값을 그대로 반영(None도 포함, P22 정합성).

    Returns:
        반영된 종목 수.

    Raises:
        메모리 반영 중 오류 발생 시 예외 전파 (P20 폴백 금지) — 호출자가 DB 재로드 회복 경로 처리.
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
        logger.warning("[데이터] 전체 매핑 DB 조회 실패: %s", e, exc_info=True)

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
            # date·5일 파생값 — 저장 성공 결과에서 한 번만 반영 (세션 3, 설계 3.3)
            if date_str:
                entry["date"] = date_str
            if derived and nk in derived:
                avg_5d, high_5d = derived[nk]
                entry["avg_5d_trade_amount"] = avg_5d
                entry["high_5d_price"] = high_5d
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
                logger.warning("[데이터] strength 변환 실패 (코드=%s, 값=%r)", raw_cd, str_val, exc_info=True)

        # name (from name_map)
        mapped_nm = _nm.get(_base_stk_cd(raw_cd))
        if mapped_nm:
            entry["name"] = mapped_nm

        # date·5일 파생값 — 저장 성공 결과에서 한 번만 반영 (세션 3, 설계 3.3 · P10 SSOT)
        if date_str:
            entry["date"] = date_str
        if derived and nk in derived:
            avg_5d, high_5d = derived[nk]
            entry["avg_5d_trade_amount"] = avg_5d
            entry["high_5d_price"] = high_5d

        updated += 1

    logger.info("[스케줄] 확정 데이터 메모리 캐시 갱신 — %d종목", updated)
    return updated


async def _reload_confirmed_from_db(saved_codes: set[str]) -> None:
    """메모리 반영 실패 시 DB 커밋 범위 재로드 회복 (설계 3.3).

    ``saved_codes`` 범위만 DB에서 다시 불러와 ``master_stocks_cache`` 에 적용.
    DB 재저장은 수행하지 않는다 (메모리 반영 실패를 DB에 되돌리지 않음, 설계 3.3).
    실시간 필드(strength·sign·captured_at·base_price·target_price·_subscribed 등)는 건드리지 않아 보존.

    Raises:
        DB 조회 오류 시 예외 전파 (P20 폴백 금지) — 호출자가 후속 계산 중단 처리.
    """
    if not saved_codes:
        return
    from backend.app.db.database import get_db_connection
    conn = await get_db_connection()
    codes_list = list(saved_codes)
    placeholders = ",".join("?" for _ in codes_list)
    cursor = await conn.execute(f"""
        SELECT code, name, cur_price, change, change_rate, trade_amount,
               avg_5d_trade_amount, high_5d_price, date
        FROM master_stocks_table
        WHERE code IN ({placeholders})
    """, codes_list)
    rows = await cursor.fetchall()
    reloaded = 0
    for r in rows:
        code = str(r["code"])
        entry = engine_state.state.master_stocks_cache.get(code)
        if entry is None:
            continue
        entry["cur_price"] = int(r["cur_price"]) if r["cur_price"] is not None else None
        entry["change"] = int(r["change"]) if r["change"] is not None else None
        entry["change_rate"] = float(r["change_rate"]) if r["change_rate"] is not None else None
        entry["trade_amount"] = int(r["trade_amount"]) if r["trade_amount"] is not None else None
        entry["avg_5d_trade_amount"] = int(r["avg_5d_trade_amount"] or 0)
        entry["high_5d_price"] = int(r["high_5d_price"] or 0)
        entry["date"] = str(r["date"] or "")
        if r["name"]:
            entry["name"] = str(r["name"])
        reloaded += 1
    logger.info("[데이터] 메모리 반영 실패 회복 — DB 재로드 %d종목", reloaded)


async def _apply_5d_derived_to_memory(
    derived: dict[str, tuple[int | None, int | None]],
) -> int:
    """수동 5일 파생값(평균 거래대금·최고가)을 메모리 캐시에 반영 (설계 3.3, 세션 3).

    저장 모듈(``save_5d_bars``)의 저장 성공 결과(``derived``)만 반영.
    ``cur_price`` 등 다른 필드는 건드리지 않는다 (수동 5일은 파생값만 다룸).
    실시간 필드(strength·sign·captured_at·base_price·target_price·_subscribed 등)도 보존.

    Args:
        derived: {code: (avg_5d, high_5d)} — 저장 성공 결과의 파생값.

    Raises:
        반영 중 오류 시 예외 전파 (P20 폴백 금지) — 호출자가 DB 재로드 회복 경로 처리.
    """
    updated = 0
    for cd, avg_high in derived.items():
        entry = engine_state.state.master_stocks_cache.get(cd)
        if entry is None:
            continue
        avg_5d, high_5d = avg_high
        entry["avg_5d_trade_amount"] = avg_5d
        entry["high_5d_price"] = high_5d
        updated += 1
    logger.info("[다운로드] 5일 파생값 메모리 캐시 갱신 — %d종목", updated)
    return updated


# ---------------------------------------------------------------------------
# 확정 후 v2 캐시 롤링 파이프라인 (daily_time_scheduler.py에서 이동)
# ---------------------------------------------------------------------------

async def _save_daily_snapshot(trade_mode: str) -> None:
    """장마감 후 당일 계좌 총자산 스냅샷 저장 (기초자산 분모 방식).

    account_snapshot에서 total_asset 산출:
      - 테스트모드: orderable + total_eval_amount (주문가능금액 + 총평가금액)
      - 실전모드: deposit + total_eval_amount (예수금 + 총평가금액)
    P22 데이터 정합성 — total_asset은 원본 account_snapshot에서 파생.
    저장 후 settlement_engine.reset_daily_deposit_total() 호출 (당일 입금액 누적 초기화).
    """
    from backend.app.db.database import get_db_connection
    from backend.app.db.stock_tables import save_daily_account_snapshot
    from backend.app.services import settlement_engine
    from backend.app.services.engine_account import get_account_snapshot

    today = get_current_trading_day_str()
    snap = await get_account_snapshot()
    deposit = int(snap.get("deposit", 0) or 0)
    orderable = int(snap.get("orderable", 0) or 0)
    total_eval = int(snap.get("total_eval_amount", 0) or snap.get("total_eval", 0) or 0)
    accumulated = int(snap.get("accumulated_investment", 0) or 0)
    daily_deposit = settlement_engine.get_daily_deposit_total()

    if trade_mode == "virtual":
        total_asset = orderable + total_eval
    else:
        total_asset = deposit + total_eval

    conn = await get_db_connection()
    await save_daily_account_snapshot(
        conn,
        date=today,
        trade_mode=trade_mode,
        total_asset=total_asset,
        deposit=deposit,
        orderable=orderable,
        total_eval_amount=total_eval,
        accumulated_investment=accumulated,
        daily_deposit=daily_deposit,
    )
    settlement_engine.reset_daily_deposit_total()
    logger.info(
        "[스케줄] 일별 계좌 스냅샷 저장 — %s %s 총자산 %s원 (예수금 %s원 / 평가 %s원 / 당일입금 %s원)",
        today, trade_mode, f"{total_asset:,}", f"{deposit:,}", f"{total_eval:,}", f"{daily_deposit:,}",
    )


async def _run_post_confirmed_pipeline(eligible_codes: set[str] | None = None) -> None:
    """확정 데이터 저장 후 처리 — 일별 계좌 스냅샷 저장만 수행.

    세션 2 정리: 기존 ``_save_confirmed_cache`` (메모리 전체를 DB에 재저장) 호출 제거.
    저장은 ``execute_unified_rolling_and_save`` / ``save_5d_bars`` 가 성공 종목만 단일 트랜잭션으로
    이미 처리하므로, 동일 데이터를 다시 DB에 쓰는 중복 저장 경로를 제거 (설계 5.4 · 태스크 세션 2).
    ``eligible_codes`` 인자는 호출 호환성 유지를 위해 남기며, 본 함수에서는 사용하지 않는다.
    """
    _ = eligible_codes  # 호출 호환성 — 본 함수에서 미사용 (중복 저장 경로 제거)
    try:
        # 장마감 후 당일 계좌 스냅샷 저장 (P25 격리 — 실패 시 파이프라인 중단 안 함)
        try:
            from backend.app.services.engine_account import get_trade_mode
            await _save_daily_snapshot(get_trade_mode())
        except Exception as e:
            logger.warning("[스케줄] 일별 계좌 스냅샷 저장 실패 (기동 유지): %s", e, exc_info=True)
        logger.info("[스케줄] 확정 후 파이프라인 종료 (중복 재저장 경로 제거)")
    except Exception as exc:
        logger.warning("[스케줄] 확정 후 파이프라인 오류: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 공통 일봉 차트 시세 다운로드 파이프라인 (타이머/수동 공용)
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
        logger.info("%s 1단계 종료 — 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)", tag, len(records), kospi_count, kosdaq_count, other_count)
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
            top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:8]
            reason_strs = [f"{k} {v}개" for k, v in top_reasons]
            logger.info("%s 주요 제외 사유: %s", tag, ", ".join(reason_strs))

        # 이상 케이스는 WARNING으로만 출력 (정상 시 silent)
        if duplicate_codes:
            duplicate_preview = sorted(duplicate_codes)[:20]
            logger.warning("%s 전종목 통합 조회(ka10099) 동일 종목코드 중복 감지 — %d종목, 예시=%s", tag, len(duplicate_codes), duplicate_preview)
        if conflict_codes:
            conflict_preview = sorted(conflict_codes)[:20]
            logger.warning("%s 전종목 통합 조회(ka10099) 동일 종목코드 판정 충돌 — %d종목, 예시=%s", tag, len(conflict_codes), conflict_preview)
        _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 종료: 총 {unique_codes}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)

        # 전체 사유 저장 — 표시층(sector_stock_cache.assemble_filter_summary)에서 8개로 자름.
        # 저장은 전체로 하여 향후 표시 개수 조정 시 파이프라인 재수정 불필 (P10 SSOT).
        _meta_top = [
            {"k": k, "v": v}
            for k, v in sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)
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
) -> tuple[dict[str, str], dict[str, str], set[str]] | None:
    """3단계: 적격 종목 해석/매칭. Returns (name_map, market_map, name_missing_codes) or None.

    설계서 4.1(응답 보존) — 전종목 목록 조회 결과에서 이름 없음과 자료 조회 실패를
    각각 구분한다. 이름이 빈 문자열이거나 None인 종목은 name_missing_codes 에 담아
    별도 상태로 보존한다 (설계서 4.6 종목명 없음 표시).
    """
    logger.info("%s 3단계 시작 — 적격 종목 해석 (%d종목)", tag, len(confirmed_codes))
    _broadcast_confirmed_progress(0, 0, message="종목 정보 해석 중...", step=3)
    try:
        name_map: dict[str, str] = {}
        market_map: dict[str, str] = {}
        name_missing_codes: set[str] = set()
        for r in records:
            if r.code in confirmed_codes:
                name_map[r.code] = r.name
                market_map[r.code] = r.market_code
                # 이름 없음 구분 — 빈 문자열·None 을 종목코드로 대체하지 않음 (설계서 4.1·5.1)
                if not r.name or not str(r.name).strip():
                    name_missing_codes.add(r.code)
        logger.info("%s 3단계 종료 — %d종목 해석/매칭 (이름 없음 %d종목)",
                    tag, len(name_map), len(name_missing_codes))
        return name_map, market_map, name_missing_codes
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

        # latest_filter_summary_meta 쓰기는 _set_latest_filter_summary_meta() 단일 경로 (세션 11 P10 SSOT)
        _set_latest_filter_summary_meta(filter_summary_meta)

        all_codes = list(confirmed_codes)
        await _update_layout_cache(all_codes, name_map)
        logger.info("%s 4단계 종료 — 저장 (%d종목)", tag, len(confirmed_codes))

        try:
            from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
            await broadcast_stock_classification_changed()
        except Exception as e:
            logger.warning("필터 요약 전송 실패: %s", e, exc_info=True)
        return all_codes
    except Exception as exc:
        logger.warning("%s 4단계 저장 실패: %s", tag, exc, exc_info=True)
        return None


async def _step5_download_daily_confirmed(
    tag: str, _sector: object, all_codes: list[str],
    *,
    qry_dt: str,
) -> tuple[dict[str, dict], int, int, dict[str, str]]:
    """5단계: 전종목 일봉 차트 시세 조회(ka10081) 다운로드 + 검증.

    Returns ``(verified, fetched, failed, failed_details)``.
    ``failed_details`` 는 {종목코드: 실패 사유} — 호출자가 실패 종목을 메모리에
    실패 상태로 표시할 때 사용 (설계서 4.3 부분 성공).

    다운로드 + 검증만 담당한다 (세션 5 — 총괄 경계 정리).
    저장·메모리 반영·화면 전송·계좌 스냅샷·메모리 교체는 호출자(``_run_confirmed_pipeline``)가
    저장 성공·메모리 반영 성공 후 순서대로 호출한다 (설계 5.4 · 태스크 세션 5).

    qry_dt는 호출자가 가장 최근 확정된 거래일로 계산해 전달 (P10/P22).
    달력 오늘을 사용하면 장 전/중 실행 시 API가 오늘 미확정 일봉(거래대금=0)을
    반환하여 미확정 데이터가 DB에 저장되는 정합성 위반이 발생함.

    설계서 4.2(요청/응답 날짜 분리)·4.3(부분 성공) 반영:
    - 응답 기준일이 없으면 저장 성공으로 처리하지 않는다.
    - 응답 기준일이 요청 기준일과 다르면 날짜 불일치 상태로 분류한다.
    - 수신 실패·날짜 불일치·cur_price=0 종목은 verified 에서 제외하고 failed_details 에 기록한다.
    """
    logger.info("[다운로드] 다운로드 시작 (%d종목)", len(all_codes))
    total = len(all_codes)
    _main_loop = asyncio.get_running_loop()

    _broadcast_confirmed_progress(0, total, message=f"일봉 차트 시세 다운로드 중 (0/{total:,}, 0%)", step=5)
    _dl_start = time.monotonic()

    def _on_progress(processed: int, success: int, failed_n: int, tot: int) -> None:
        _pct = int(processed / total * 100) if total > 0 else 0
        _eta: float = 0
        if processed > 0:
            _elapsed = time.monotonic() - _dl_start
            _eta = _elapsed / processed * (total - processed)
        _broadcast_confirmed_progress(processed, total, message=f"일봉 차트 시세 다운로드 중 ({processed:,}/{total:,}, {_pct}%)", eta_sec=_eta, step=5, _loop=_main_loop)

    try:
        confirmed = await _sector.fetch_all_stocks_daily_confirmed(all_codes, qry_dt, interval_sec=0.3, on_progress=_on_progress)
    except Exception as exc:
        # 전종목 조회 실패 — 빈 폴백으로 후속 파이프라인 진행 금지 (P20 폴백 금지).
        # 빈 confirmed로 _run_post_confirmed_pipeline 실행 시 빈 캐시 저장 시도 위험.
        # 실패를 화면에 알리고 파이프라인 중단 (P21 사용자 투명성).
        logger.error("[다운로드] 전종목 조회 실패 — 파이프라인 중단: %s", exc, exc_info=True)
        _broadcast_confirmed_progress(
            total, total,
            message=f"❌ 일봉 차트 시세 다운로드 실패 — 파이프라인 중단 ({total:,}종목)",
            step=5, failed_count=total,
        )
        _all_failed = {cd: "fetch_exception" for cd in all_codes}
        return {}, 0, total, _all_failed

    # 검증: 확정 데이터 유효성 검사 (설계서 4.1·4.2·4.3)
    # RawStockFetchResult 에서 상태·응답일·원문을 확인해 정상 종목만 verified 에 담는다.
    verified_confirmed: dict[str, dict] = {}
    failed_details: dict[str, str] = {}
    verification_failed = 0
    date_mismatch_count = 0
    no_response_date_count = 0

    for cd, result in confirmed.items():
        # RawStockFetchResult 가 아닌 dict 가 들어온 레거시 호환 — raw_payload 에서 원문 추출
        if isinstance(result, RawStockFetchResult):
            # 수신 실패 — raw_payload 없음으로 구분 (설계서 4.3)
            if result.raw_payload is None:
                failed_details[cd] = "fetch_failed"
                continue
            payload = result.raw_payload
            response_date = payload.get("dt")
        else:
            # 레거시 dict 경로 (테스트·기존 mock 호환)
            payload = result
            response_date = result.get("response_date") or result.get("dt")

        # 응답 기준일이 없으면 저장 성공으로 처리하지 않는다 (설계서 4.2)
        if not response_date:
            no_response_date_count += 1
            failed_details[cd] = "no_response_date"
            logger.warning("[다운로드] 응답 기준일 없음 — %s", cd)
            continue

        # 응답 기준일이 요청 기준일과 다르면 날짜 불일치 상태로 분류 (설계서 4.2)
        if qry_dt and str(response_date) != str(qry_dt):
            date_mismatch_count += 1
            failed_details[cd] = "date_mismatch"
            logger.warning("[다운로드] 응답 기준일 불일치 — %s (요청=%s, 응답=%s)", cd, qry_dt, response_date)
            continue

        # cur_price 검증 — 0이면 확정되지 않은 것으로 판정 (P22)
        cur_price = payload.get("close") or payload.get("cur_price") or 0
        if int(cur_price) == 0:
            verification_failed += 1
            failed_details[cd] = "cur_price_zero"
            logger.warning("[다운로드] 검증 실패 — %s (cur_price=0)", cd)
            continue

        verified_confirmed[cd] = {
            "dt": payload.get("dt") or response_date or "",
            "cur_price": cur_price,
            "trade_amount": payload.get("value") if payload.get("value") is not None else payload.get("trade_amount"),
            "high_price": payload.get("high") or payload.get("high_price") or 0,
            "volume": payload.get("volume") or 0,
            "change": payload.get("change") or 0,
            "change_rate": payload.get("rate") if payload.get("rate") is not None else payload.get("change_rate"),
            "sign": payload.get("sign") or "3",
        }

    # 요청했으나 응답에 없는 종목 — 실패 집합에 포함 (설계서 4.3 부분 성공)
    for cd in all_codes:
        nk = _base_stk_cd(cd) or cd
        if cd not in confirmed and nk not in failed_details and cd not in failed_details:
            failed_details[cd] = "no_data"

    fetched = len(verified_confirmed)
    failed = total - fetched
    success_rate = (fetched / total * 100) if total else 0
    logger.info("[다운로드] 다운로드 종료 — 성공 %d, 실패 %d (%.1f%%)", fetched, failed, success_rate)
    if verification_failed > 0:
        logger.info("[다운로드] cur_price=0 검증 실패 %d종목 — 실패 집합 포함", verification_failed)
    if date_mismatch_count > 0:
        logger.info("[다운로드] 응답 기준일 불일치 %d종목 — 실패 집합 포함", date_mismatch_count)
    if no_response_date_count > 0:
        logger.info("[다운로드] 응답 기준일 없음 %d종목 — 실패 집합 포함", no_response_date_count)
    if failed > 0 and success_rate < 99.0:
        logger.warning("[다운로드] 실패율 높음: %d/%d (%.1f%%)", failed, total, 100 - success_rate)

    # 검증 완료 데이터만 반환 (설계 4.2) — 저장·메모리 반영·화면·스냅샷은 호출자(총괄)가 담당 (세션 5).
    # 다운로드 단계 완료 진행률 — 화면 전송 단계 진행률("5거래일 거래대금 계산 중...")은 총괄이 전송.
    if failed > 0:
        _broadcast_confirmed_progress(total, total, message=f"⚠️ 일봉 차트 시세 다운로드 부분 종료 ({fetched:,}/{total:,}) — {failed}종목 실패", step=5, failed_count=failed)
    else:
        _broadcast_confirmed_progress(total, total, message=f"일봉 차트 시세 다운로드 종료 ({fetched:,}/{total:,})", step=5)

    return verified_confirmed, fetched, failed, failed_details


async def _post_recompute_notify(tag: str) -> None:
    """확정 데이터 반영 후 수신율 갱신 + 업종순위 재계산 + 실시간 화면 전송 (P24 단일 SSOT).

    _step7_recompute_and_broadcast와 fetch_5d_data_only 후처리의 공통 후처리.
    순서: 수신율 갱신 → sector-stocks-refresh → recompute_sector_summary_now.
    sectorStocks가 먼저 갱신되어야 buy-targets-delta merge 시 최신 데이터 참조 가능.
    실패 시 파이프라인 전체 중단 차단 (P25 격리된 실패) — warning 로깅 후 진행.
    """
    try:
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        from backend.app.services.engine_account_notify import notify_desktop_sector_stocks_refresh
        # 확정 데이터 반영 후 수신율 갱신 — change_rate, trade_amount 기준 100% 산출 (P21 투명성, P22 정합성)
        from backend.app.pipelines.pipeline_compute import _calculate_receive_rate, _send_receive_rate, get_current_receive_rate
        await _calculate_receive_rate()
        await _send_receive_rate(get_current_receive_rate())
        await notify_desktop_sector_stocks_refresh(force=True)
        await recompute_sector_summary_now()
        # 확정 데이터 반영 후 화면별 구독 대상 갱신 + 활성 연결 갱신 (태스크 2세션).
        # recompute_sector_summary_now 내부에서 업종 순위·매수 후보 갱신이 이미 연결되어 있으나,
        # 보유 종목·자료 화면도 확정 데이터 반영 후 최신화 필요.
        from backend.app.services.page_subscription_targets import refresh_active_connections
        await refresh_active_connections(
            "장 마감 확정 데이터 반영",
            {"sell-position", "profit-overview", "profit-detail", "stock-detail"},
        )
        logger.info("%s 업종순위 재계산 + 실시간 화면 전송", tag)
    except Exception as _ws_err:
        logger.warning("%s 업종순위 재계산 실패: %s", tag, _ws_err, exc_info=True)


async def _step7_recompute_and_broadcast(tag: str) -> None:
    """7단계: 업종순위 재계산 + 실시간 통신 전송 — _post_recompute_notify 위임."""
    await _post_recompute_notify(tag)


def _reset_confirmed_refresh_running() -> None:
    """``confirmed_refresh_running_confirmed`` 플래그 리셋 (단일 소유자 — 세션 11).

    확정 데이터 파이프라인 실패 시 외부 모듈(``daily_time_scheduler``)에서 호출하는
    안전 청소. 정상 경로의 True/False 수명 주기는 ``_run_confirmed_pipeline``에서
    직접 관리하므로 본 함수는 예외 경로의 외부 리셋 전용 (P10 SSOT — 그룹 F 소유권 계약).
    """
    engine_state.state.confirmed_refresh_running_confirmed = False


def _set_latest_filter_summary_meta(meta: str) -> None:
    """``latest_filter_summary_meta`` 갱신 (단일 소유자 — 세션 11).

    기동 시 DB 캐시 로드(``web/app.py``)와 파이프라인 4단계 완료 후 갱신 양쪽에서 호출.
    모든 ``latest_filter_summary_meta`` 쓰기는 본 함수에서만 수행 (P10 SSOT — 그룹 F 소유권 계약).
    """
    engine_state.state.latest_filter_summary_meta = meta


def _mark_failed_stocks_in_memory(failed_details: dict[str, str]) -> None:
    """실패 종목을 메모리 캐시에 실패 상태로 표시 (설계서 4.3 부분 성공).

    실패 종목의 이전 확정값이 최신 자료처럼 업종 계산·매수 후보·화면에 남지 않도록
    메모리 캐시 엔트리의 ``date`` 를 비운다.
    정상 종목의 자료는 삭제하지 않는다 (설계서 4.3).
    저장 성공 종목은 저장 결과로 메모리가 덮어쓰여지므로, 본 함수는 저장 전에 호출하여
    실패 종목만 표시한다.

    Args:
        failed_details: {종목코드: 실패 사유} — _step5_download_daily_confirmed 반환.
    """
    cache = engine_state.state.master_stocks_cache
    for raw_cd, reason in failed_details.items():
        nk = _base_stk_cd(raw_cd) or raw_cd
        entry = cache.get(nk)
        if entry is None:
            continue
        # date 를 비워 최신 자료로 오인되지 않도록 한다 (설계서 4.4 오래된 자료 차단)
        entry["date"] = ""


async def _run_confirmed_pipeline(
    tag: str,
    *,
    check_scheduler: bool = False,
    check_time_guard: bool = False,
) -> dict:
    """공통 일봉 차트 시세 다운로드 파이프라인 (타이머/수동 공용).

    1~7단계: 전종목 통합 조회(ka10099) 전종목 다운로드 → 필터링 → 해석 → DB저장 →
    전종목 일봉 차트 시세 조회(ka10081) 일봉 차트 시세 다운로드 → 정규화 → 메모리/DB 저장 → 메모리 교체 → 전송.
    """
    if engine_state.state.confirmed_refresh_running_confirmed:
        logger.info("%s 확정 조회 이미 진행 중 — 생략", tag)
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    engine_state.state.confirmed_refresh_running_confirmed = True

    _broker_token_registered = False

    try:
        # ── 메모리 전체 초기화 ──
        engine_state.state.integrated_system_settings_cache["sector_stock_layout"] = []
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        logger.info("%s 메모리 전체 초기화 — 새 데이터로 교체 시작", tag)

        # 스케줄러 토글 체크 (타이머 전용)
        if check_scheduler and not engine_state.state.integrated_system_settings_cache["scheduler_market_close_on"]:
            logger.info("%s 장마감 스케줄러=꺼짐 — 전체 갱신 생략", tag)
            return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

        from backend.app.core.broker_registry import _create_provider
        _settings = engine_state.state.integrated_system_settings_cache
        # 확정 시세 다운로드 증권사: confirmed_data_broker 우선, 빈 값이면 활성 broker 사용
        # (settings_defaults.py 계약: "빈 문자열 = 현재 broker 사용")
        _confirmed_broker = str(_settings.get("confirmed_data_broker") or "").strip().lower()
        _broker_name = _confirmed_broker or str(_settings.get("broker") or "").strip().lower()
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
        name_map, _market_map, _name_missing_codes = step3_result

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

        # ── 5단계: 전종목 일봉 차트 시세 조회(ka10081) 다운로드 + 검증 ──
        # qry_dt는 가장 최근 확정된 거래일 — 소속 거래일의 직전 거래일 (P10/P22).
        # 06:36 @ 07-15(수, 장전): current=07-15 → previous=07-14 (07-14 확정 데이터)
        # 20:40 @ 07-15(수, 장후): current=07-16 → previous=07-15 (07-15 확정 데이터)
        qry_dt = get_previous_trading_day_str(get_current_trading_day_str())
        verified_confirmed, fetched, failed, failed_details = await _step5_download_daily_confirmed(
            tag, _sector, all_codes, qry_dt=qry_dt,
        )

        # ── 실패 종목 메모리 표시 (설계서 4.3 부분 성공) ──
        # 실패 종목의 이전 확정값이 최신 자료처럼 남지 않도록 메모리 캐시에 실패 상태를 표시한다.
        # 정상 종목의 자료는 부분 실패 때문에 삭제하지 않는다 (설계서 4.3).
        # 저장·메모리 반영·화면 전송 단계 사이에서 실패 상태가 정상 상태로 바뀌지 않도록
        # 저장 전에 먼저 실패 종목을 표시하고, 저장 성공 종목은 저장 결과로 덮어쓴다.
        if failed_details:
            _mark_failed_stocks_in_memory(failed_details)

        # ── 6단계: 저장 + 메모리 반영 (총괄 책임 — 세션 5 경계 정리) ──
        # 검증 완료 데이터만 저장에 전달 (설계 4.2). 메모리 반영은 저장 성공 후 (설계 3.3, 세션 3).
        # DB 커밋 전 메모리 선반영 금지 — 저장 성공 결과만 메모리에 반영.
        cached = False
        if verified_confirmed:
            logger.info("%s 단일 벌크 트랜잭션 시작", tag)
            save_ok = await execute_unified_rolling_and_save(
                verified_confirmed, name_map=name_map, qry_dt=qry_dt,
            )
            logger.info("%s 단일 벌크 트랜잭션 종료", tag)
            if save_ok:
                cached = True
            else:
                # 저장·메모리 반영·재로드 회복 중 실패 — 후속 업종 계산·화면 확정은 cached=False로 분기 (설계 3.3)
                logger.warning("%s 저장·메모리 반영 실패 — cached=False, 후속 처리 분기", tag)

        # ── 화면: 종목분류 갱신 (저장 성공 여부 무관 — 4단계에서 종목·업종 매핑 이미 저장) ──
        try:
            from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
            await broadcast_stock_classification_changed()
            logger.info("%s 종목분류 페이지 갱신 전송", tag)
        except Exception as _bc_err:
            logger.warning("%s 종목분류 페이지 갱신 전송 실패(무시): %s", tag, _bc_err, exc_info=True)

        # ── 계좌 일별 스냅샷 (P25 격리 — 확정 데이터와 별도, 실패 시 파이프라인 중단 안 함) ──
        # 진행률: 화면 전송 단계 진입 알림 (다운로드 단계 진행률과 구분 — 세션 5).
        _broadcast_confirmed_progress(len(all_codes), len(all_codes), message="5거래일 거래대금 계산 중...", step=5)
        await _run_post_confirmed_pipeline(eligible_codes=confirmed_codes)

        # ── 메모리 교체: cached일 때만 구독 플래그 정리 ──
        if cached:
            final_eligible = confirmed_codes
            if final_eligible:
                to_remove = [cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_subscribed", False) and cd not in final_eligible]
                for cd in to_remove:
                    if cd in engine_state.state.master_stocks_cache:
                        engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
                subscribed_count = sum(1 for entry in engine_state.state.master_stocks_cache.values() if entry.get("_subscribed", False))
                logger.info("%s 6단계 메모리 교체 — 구독 중=%d종목", tag, subscribed_count)
        else:
            logger.warning("%s 캐시 미적용 — 메모리 교체 생략", tag)

        # ── 7단계: 업종순위 재계산 + 실시간 화면 전송 (cached일 때만 — 설계 3.3) ──
        # 저장·메모리 반영·재로드 회복 중 실패 시 업종 계산·화면 확정 중단 (설계 3.3).
        if cached:
            await _step7_recompute_and_broadcast(tag)
        else:
            logger.warning("%s 저장·메모리 반영 실패 — 업종순위 재계산·화면 확정 중단 (설계 3.3)", tag)

        if cached:
            logger.info("[다운로드] 전체 종료 — 전종목 통합 조회(ka10099): %d종목 | 적격: %d종목 | 일봉: %d/%d종목", len(all_codes), len(confirmed_codes), fetched, len(all_codes))
        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        if _broker_token_registered:
            engine_state.state.broker_tokens.pop(_broker_name, None)
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            await broadcast_engine_status()
        engine_state.state.confirmed_refresh_running_confirmed = False


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

    sector_stock_layout 원본 SSOT: master_stocks_table의 sector 컬럼에서 파생 (P22 데이터 정합성).
    본 함수가 런타임 파생 경로 중 하나 — 장마감 파이프라인에서 DB 매핑 기반으로 재구성.
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
        logger.warning("[데이터] 전체 매핑 DB 조회 실패: %s", e, exc_info=True)

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
# 수동 일봉 차트 시세 및 5거래일 일봉 차트 다운로드
# ---------------------------------------------------------------------------

async def fetch_confirmed_data_only() -> dict:
    """수동 매매적격종목 일봉 차트 시세 다운로드 파이프라인 — _run_confirmed_pipeline 위임."""
    return await _run_confirmed_pipeline("[수동 확정시세]")




async def fetch_5d_data_only() -> dict:
    """수동 5거래일 일봉 거래대금,고가 다운로드 파이프라인.

    DB의 master_stocks_table에 등록된 매매적격종목을 대상으로
    개별 종목의 5거래일 고가 및 거래대금 데이터를 다운로드하여 DB 및 메모리에 저장합니다.
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

    _broker_token_registered = False

    try:
        from backend.app.core.broker_registry import _create_provider
        _settings = engine_state.state.integrated_system_settings_cache
        # 확정 시세 다운로드 증권사: confirmed_data_broker 우선, 빈 값이면 활성 broker 사용
        # (settings_defaults.py 계약: "빈 문자열 = 현재 broker 사용")
        _confirmed_broker = str(_settings.get("confirmed_data_broker") or "").strip().lower()
        _broker_name = _confirmed_broker or str(_settings.get("broker") or "").strip().lower()
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
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── 개별 5거래일 일봉 데이터 다운로드 ───────────────────────────────────────
        logger.info("[다운로드] 다운로드 시작 (%d종목)", total)
        _broadcast_confirmed_progress(0, total, message=f"5거래일 일봉 차트 거래대금,고가 다운로드 중 (0/{total:,}, 0%)", step=5)
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
                # RawStockFetchResult 처리 — raw_payload 에서 5일 배열 추출 (설계서 4.1)
                # 레거시 dict 호환 — RawStockFetchResult 가 아닌 경우 dict 로 직접 접근
                if isinstance(res, RawStockFetchResult):
                    if res.raw_payload is None:
                        failed += 1
                        logger.warning("[다운로드] API 응답 없음 [%d/%d] %s", idx + 1, total, base_cd)
                        continue
                    payload = res.raw_payload
                elif res:
                    payload = res
                else:
                    failed += 1
                    logger.warning("[다운로드] API 응답 없음 [%d/%d] %s", idx + 1, total, base_cd)
                    continue

                amounts_5d = payload.get("amts_5d_array") or []
                highs_5d = payload.get("highs_5d_array") or []
                dts_5d = payload.get("dts_5d_array") or []

                if amounts_5d and highs_5d and dts_5d:
                    # 검증: 유효한 값(>0)이 거래대금·고가 각각 1개 이상 있어야 확정된 것으로 판정 (P22)
                    # 배열은 비어있지 않더라도 전부 0이면 확정되지 않은 데이터 (설계 4.2)
                    valid_amts = [a for a in amounts_5d if a is not None and a > 0]
                    valid_highs = [h for h in highs_5d if h is not None and h > 0]
                    if not valid_amts or not valid_highs:
                        failed += 1
                        logger.warning("[다운로드] 검증 실패 — 유효값 없음 [%d/%d] %s", idx + 1, total, base_cd)
                    else:
                        confirmed_5d[nk] = {
                            "amts_5d_array": amounts_5d,
                            "highs_5d_array": highs_5d,
                            "dts_5d_array": dts_5d,
                        }
                        fetched += 1
                else:
                    failed += 1
                    logger.warning("[다운로드] 데이터 비어있음 [%d/%d] %s", idx + 1, total, base_cd)

            except Exception as e:
                failed += 1
                logger.warning("[다운로드] 오류 발생 [%d/%d] %s: %s", idx + 1, total, base_cd, e, exc_info=True)

            # 진행률 전송 (매 종목)
            pct = int((idx + 1) / total * 100) if total else 0
            _eta: float = 0
            if (idx + 1) > 0:
                _elapsed = time.monotonic() - _dl_start
                _eta = _elapsed / (idx + 1) * (total - (idx + 1))
            _broadcast_confirmed_progress(
                idx + 1, total,
                message=f"5거래일 일봉 차트 거래대금,고가 다운로드 중 ({idx + 1:,}/{total:,}, {pct}%)",
                eta_sec=_eta,
                step=5
            )
            log_progress("[다운로드]", idx + 1, total, code=base_cd)

            # 요청 간격 조절
            await asyncio.sleep(0.3)

        log_progress_end()
        # ── 5거래일 일봉 저장 — 저장 전담 모듈로 위임 (단일 트랜잭션, 설계 5.4) ────────────
        # 메모리 반영은 저장 성공 후 파생값만 정식 반영 + 실패 시 DB 재로드 회복 (설계 3.3, 세션 3).
        _memory_ok = True
        if confirmed_5d:
            logger.info("[다운로드] 5거래일 일봉 저장 시작 — %d종목", len(confirmed_5d))

            from backend.app.services.market_close_storage import save_5d_bars
            save_result = await save_5d_bars(confirmed_5d, qry_dt=qry_dt)
            if save_result["success"]:
                saved_codes = set(save_result["saved_codes"])
                try:
                    await _apply_5d_derived_to_memory(
                        save_result["derived"],
                    )
                except Exception as mem_err:
                    # 메모리 반영 실패 — DB 재로드 회복 (설계 3.3). DB 재저장 금지.
                    logger.warning("[다운로드] 5일 파생값 메모리 반영 실패 — DB 재로드 회복: %s", mem_err, exc_info=True)
                    try:
                        await _reload_confirmed_from_db(saved_codes)
                    except Exception as reload_err:
                        # 재로드 실패 — 업종 계산·매매 판단·화면 확정 중단 (설계 3.3)
                        logger.error("[다운로드] DB 재로드 실패 — 후속 업종 계산 중단: %s", reload_err, exc_info=True)
                        _memory_ok = False
            else:
                logger.warning("[다운로드] 5거래일 일봉 저장 실패 — 메모리 반영 생략 (P22)")

        success_rate = (fetched / total * 100) if total else 0
        logger.info("[다운로드] 다운로드 종료 — 성공 %d종목, 실패 %d종목 (%.1f%%)", fetched, failed, success_rate)

        if failed > 0:
            _broadcast_confirmed_progress(total, total, message=f"⚠️ 5거래일 일봉 차트 거래대금,고가 다운로드 부분 종료 ({fetched:,}/{total:,}) — {failed}종목 실패", step=5, failed_count=failed)
        else:
            _broadcast_confirmed_progress(total, total, message=f"5거래일 일봉 차트 거래대금,고가 다운로드 종료 ({fetched:,}/{total:,})", step=5)

        # 종목분류 전송 (프론트엔드 자동갱신)
        from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
        await broadcast_stock_classification_changed()

        # 후처리 — 일별 계좌 스냅샷 저장은 확정 데이터와 무관하므로 항상 수행 (P25 격리)
        await _run_post_confirmed_pipeline(eligible_codes=set(all_codes))

        # 업종순위 재계산 (내부에서 notify_desktop_sector_scores + notify_buy_targets_update 호출)
        # 순서·격리는 _post_recompute_notify 헬퍼에 캡슐화 (P24 단일 SSOT)
        # 메모리 반영·재로드 실패 시 업종 계산·화면 확정 중단 (설계 3.3)
        if _memory_ok:
            await _post_recompute_notify("[다운로드]")
        else:
            logger.warning("[다운로드] 메모리 반영·재로드 실패 — 업종순위 재계산·화면 전송 중단 (설계 3.3)")

        return {"fetched": fetched, "failed": failed, "cached": False}
    finally:
        if _broker_token_registered:
            engine_state.state.broker_tokens.pop(_broker_name, None)
            from backend.app.services.engine_lifecycle import broadcast_engine_status
            await broadcast_engine_status()
        engine_state.state.confirmed_refresh_running_5d = False
