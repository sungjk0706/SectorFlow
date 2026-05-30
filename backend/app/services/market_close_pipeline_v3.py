from __future__ import annotations
# -*- coding: utf-8 -*-
"""
장마감 후 데이터 캐시 파이프라인 — 핵심 로직.

KRX/NXT 장마감 후 WS 구독 해지 → REST 확정 데이터 조회 → 캐시 저장.
daily_time_scheduler.py 타이머 콜백에서 호출된다.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

from backend.app.core.logger import get_logger
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    _format_kiwoom_reg_stk_cd,
    is_nxt_enabled,
    get_ws_subscribe_code,
)
from backend.app.services.engine_ws_reg import build_0b_remove_payloads
from backend.app.core.trading_calendar import get_current_trading_day_str

_log = get_logger("engine")
_CONFIRMED_FETCH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="confirmed-fetch")


def _broadcast_confirmed_progress(
    current: int, total: int, *, message: str = "", eta_sec: float = 0, step: int = 0,
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
        }
        from backend.app.services.core_queues import get_broadcast_queue
        
        if current >= total:
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
    """_subscribed_stocks / _pending_stock_details / _sector_stock_layout에서 KRX 단독 종목(nxt_enable=False)만 추출.

    Args:
        es: engine_service 모듈 참조

    Returns:
        6자리 정규화된 KRX 단독 종목코드 리스트 (중복 없음).
    """
    result: list[str] = []
    seen: set[str] = set()

    sources: list[set | dict | list] = []
    if hasattr(es, "_subscribed_stocks"):
        sources.append(es._subscribed_stocks)
    if hasattr(es, "_pending_stock_details"):
        sources.append(es._pending_stock_details)

    for src in sources:
        for raw_cd in list(src):
            base = _base_stk_cd(raw_cd)
            if not base or base in seen:
                continue
            seen.add(base)
            if not is_nxt_enabled(base):
                result.append(base)

    # 레이아웃 캐시에서 seen에 없는 KRX 단독 종목 추가 (항상 순회)
    layout = getattr(es, "_sector_stock_layout", [])
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
    # WS 미연결 시 스킵
    ws = getattr(es, "_kiwoom_connector", None)
    if not ws or not getattr(ws, "is_connected", lambda: False)():
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

    for ci, payload in enumerate(payloads):
        chunk = krx_codes[ci * chunk_size : (ci + 1) * chunk_size]
        try:
            ack_ok, rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
        except Exception as exc:
            _log.warning(
                "[타이머] KRX 장마감 구독해지 %d/%d 예외: %s",
                ci + 1, len(payloads), exc,
                exc_info=True,
            )
            failed += len(chunk)
            continue

        if ack_ok:
            # ACK 성공 — _subscribed_stocks에서 제거
            for cd in chunk:
                es._subscribed_stocks.discard(cd)
            removed += len(chunk)
            _log.info(
                "[타이머] KRX 장마감 구독해지 %d/%d 완료 — %d종목 (rc=%s)",
                ci + 1, len(payloads), len(chunk), rc,
            )
        else:
            # ACK 타임아웃 — _subscribed_stocks 유지 + 경고
            failed += len(chunk)
            _log.warning(
                "[타이머] KRX 장마감 구독해지 %d/%d ACK 응답없음 — %d종목 유지",
                ci + 1, len(payloads), len(chunk),
            )

    _log.info(
        "[타이머] KRX 장마감 구독해지 완료 — 해지 %d종목, 실패 %d종목",
        removed, failed,
    )
    return {"removed": removed, "failed": failed, "skipped": False}


# ---------------------------------------------------------------------------
# 확정 데이터 메모리 반영
# ---------------------------------------------------------------------------

async def _apply_5d_to_memory(es: ModuleType, confirmed_5d: dict[str, dict]) -> int:
    """ka10081 5일봉 데이터를 메모리 캐시와 master_stocks_table에 반영."""
    from backend.app.db.database import get_db_connection

    updated = 0
    amts_5d_arrays: dict = getattr(es, "_amts_5d_arrays", {})
    highs_5d_arrays: dict = getattr(es, "_highs_5d_arrays", {})

    # DB 업데이트를 위한 연결
    conn = get_db_connection()
    cursor = conn.cursor()

    for raw_cd, detail in confirmed_5d.items():
        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        if not nk:
            continue

        # avg_amt_5d
        avg5d = int(detail.get("avg_amt_5d") or 0)
        if avg5d > 0:
            if nk in _master_stocks_cache:
                _master_stocks_cache[nk]["avg_5d_trade_amount"] = avg5d

        # high_price_5d
        high5d = int(detail.get("high_price_5d") or 0)
        if high5d > 0:
            if nk in _master_stocks_cache:
                _master_stocks_cache[nk]["high_5d_price"] = high5d

        # 5일봉 배열
        amts_5d = detail.get("amts_5d_array")
        if amts_5d and isinstance(amts_5d, list):
            amts_5d_arrays[nk] = amts_5d

        highs_5d = detail.get("highs_5d_array")
        if highs_5d and isinstance(highs_5d, list):
            highs_5d_arrays[nk] = highs_5d

        # master_stocks_table에 day 컬럼 업데이트
        if amts_5d and isinstance(amts_5d, list) and len(amts_5d) >= 5:
            day1_amt = amts_5d[0] if len(amts_5d) > 0 else 0
            day2_amt = amts_5d[1] if len(amts_5d) > 1 else 0
            day3_amt = amts_5d[2] if len(amts_5d) > 2 else 0
            day4_amt = amts_5d[3] if len(amts_5d) > 3 else 0
            day5_amt = amts_5d[4] if len(amts_5d) > 4 else 0
        else:
            day1_amt = day2_amt = day3_amt = day4_amt = day5_amt = 0

        if highs_5d and isinstance(highs_5d, list) and len(highs_5d) >= 5:
            day1_high = highs_5d[0] if len(highs_5d) > 0 else 0
            day2_high = highs_5d[1] if len(highs_5d) > 1 else 0
            day3_high = highs_5d[2] if len(highs_5d) > 2 else 0
            day4_high = highs_5d[3] if len(highs_5d) > 3 else 0
            day5_high = highs_5d[4] if len(highs_5d) > 4 else 0
        else:
            day1_high = day2_high = day3_high = day4_high = day5_high = 0

        cursor.execute("""
            UPDATE master_stocks_table
            SET day1_amount = ?, day2_amount = ?, day3_amount = ?, day4_amount = ?, day5_amount = ?,
                day1_high = ?, day2_high = ?, day3_high = ?, day4_high = ?, day5_high = ?,
                avg_5d_trade_amount = ?, high_5d_price = ?
            WHERE code = ?
        """, (day1_amt, day2_amt, day3_amt, day4_amt, day5_amt,
              day1_high, day2_high, day3_high, day4_high, day5_high,
              avg5d, high5d, nk))

        updated += 1

    conn.commit()
    conn.close()

    _log.info("[타이머] 5일봉 데이터 메모리 및 DB 반영 -- %d종목", updated)
    return updated


async def _apply_confirmed_to_memory(
    es: ModuleType,
    confirmed: dict[str, dict],
    strength: dict[str, float],
    name_map: dict[str, str] | None = None,
) -> int:
    """확정 데이터를 메모리 캐시에 반영. 0값은 기존 데이터를 덮지 않음.

    Args:
        es: engine_service 모듈 참조
        confirmed: {종목코드: {cur_price, change, change_rate, sign, volume, trade_amount, prev_close}}
        strength: {종목코드: 체결강도 float}
        name_map: {6자리 종목코드: 종목명} — ka10099에서 조회한 매핑. 있으면 모든 엔트리 종목명 갱신.

    Returns:
        반영된 종목 수.
    """
    _nm = name_map or {}
    pending: dict = getattr(es, "_pending_stock_details", {})
    # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
    ltp: dict = {}
    lta: dict = {}
    lst: dict = {}
    _amts_5d_arrays: dict = getattr(es, "_amts_5d_arrays", {})
    _highs_5d_arrays: dict = getattr(es, "_highs_5d_arrays", {})

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
        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        if not nk:
            continue

        entry = pending.get(nk)
        if entry is None:
            # 엔트리 없으면 새로 생성
            from backend.app.services.engine_strategy_core import make_detail
            px = int(detail.get("cur_price") or 0)
            stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)
            sec = detail.get("sector")
            if not sec:
                sec = db_mapping.get(_base_stk_cd(raw_cd)) or "기타"
            entry = make_detail(
                nk, stk_nm, px,
                str(detail.get("sign") or "3"),
                int(detail.get("change") or 0),
                float(detail.get("change_rate") or 0.0),
                prev_close=int(detail.get("prev_close") or 0),
                trade_amount=int(detail.get("trade_amount") or 0),
                sector=sec,
            )
            entry["status"] = "active"
            entry["base_price"] = px
            entry["target_price"] = px
            entry["captured_at"] = ""
            entry["reason"] = "확정 데이터 조회"
            async with es._shared_lock:
                pending[nk] = entry
                if hasattr(es, "_radar_cnsr_order"):
                    es._radar_cnsr_order.append(nk)
            if px > 0:
                ltp[nk] = px
            amt = int(detail.get("trade_amount") or 0)
            if amt > 0:
                lta[nk] = amt
            updated += 1
            continue

        # cur_price
        px = int(detail.get("cur_price") or 0)
        if px > 0:
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
        if amt > 0:
            entry["trade_amount"] = amt
            lta[nk] = amt

        # high_price
        hp = int(detail.get("high_price") or 0)
        if hp > 0:
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

        # ── 5일봉 거래대금/고가 배열 롤링(Rolling) 갱신 ──
        base_cd = nk
        amts_5d = _amts_5d_arrays.get(base_cd)
        highs_5d = _highs_5d_arrays.get(base_cd)

        today_amt = int(detail.get("trade_amount") or 0)
        today_high = int(detail.get("high_price") or detail.get("cur_price") or 0)

        # 0값 필터링 제거: 장외 시간 데이터도 캐시에 반영
        if amts_5d is not None and isinstance(amts_5d, list):
            new_amts = [today_amt] + amts_5d[:4]
            _amts_5d_arrays[base_cd] = new_amts
            avg5d = int(sum(new_amts) / len(new_amts))
            if base_cd in _master_stocks_cache:
                _master_stocks_cache[base_cd]["avg_5d_trade_amount"] = avg5d
        else:
            _amts_5d_arrays[base_cd] = [today_amt]
            avg5d = int(today_amt or 0)
            if base_cd in _master_stocks_cache:
                _master_stocks_cache[base_cd]["avg_5d_trade_amount"] = avg5d

        if highs_5d is not None and isinstance(highs_5d, list):
            new_highs = [today_high] + highs_5d[:4]
            _highs_5d_arrays[base_cd] = new_highs
            high5d = max(new_highs)
            if base_cd in _master_stocks_cache:
                _master_stocks_cache[base_cd]["high_5d_price"] = high5d
        else:
            _highs_5d_arrays[base_cd] = [today_high]
            if base_cd in _master_stocks_cache:
                _master_stocks_cache[base_cd]["high_5d_price"] = today_high

        updated += 1

    _log.info("[타이머] 확정 데이터 메모리 반영 -- %d종목", updated)
    return updated


# ---------------------------------------------------------------------------
# 확정 후 v2 캐시 롤링 파이프라인 (daily_time_scheduler.py에서 이동)
# ---------------------------------------------------------------------------

async def _run_post_confirmed_pipeline(es: ModuleType) -> None:
    """
    ka10081 도입으로 5일 거래대금 및 최고가를 즉시 추출하므로,
    기존의 복잡한 v2 캐시 롤링 갱신 로직은 제거되었습니다.
    단순히 최종 스냅샷 및 캐시를 저장합니다.
    """
    try:
        await _save_confirmed_cache(es)
        _log.info("[타이머] post-confirmed 파이프라인 완료 (롤링 로직 생략)")
    except Exception as exc:
        _log.warning("[타이머] post-confirmed 파이프라인 오류: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 확정 데이터 디스크 캐시 저장
# ---------------------------------------------------------------------------

async def _save_confirmed_cache(es: ModuleType) -> bool:
    """현재 메모리 데이터를 master_stocks_table로 디스크 저장.

    저장 직전에 종목명 캐시를 참조하여 name 필드를 보정한다.

    Args:
        es: engine_service 모듈 참조

    Returns:
        저장 성공 여부.
    """
    from backend.app.core.sector_stock_cache import load_stock_name_cache

    pending: dict = getattr(es, "_pending_stock_details", {})
    amts_5d_arrays = getattr(es, "_amts_5d_arrays", {})
    if not pending and not amts_5d_arrays:
        _log.warning("[타이머] 저장할 데이터(_pending_stock_details 및 _amts_5d_arrays)가 모두 비어있음 — 데이터 저장 생략")
        return False

    # 적격종목 필터 — eligible 캐시 기준으로 부적격 종목 제외
    # 모듈 직접 참조: Step 4에서 _eligible_stock_codes가 재할당되어도 최신값을 사용
    import backend.app.core.industry_map as _ind_mod
    elig = _ind_mod._eligible_stock_codes or {}

    # 메모리 원자적 필터링 (Bug 4 수정) - 시작 시점에 먼저 수행하여 정합성 보장
    if elig:
        async with es._shared_lock:
            for cd in list(pending.keys()):
                if _base_stk_cd(cd) not in elig:
                    pending.pop(cd, None)

    # 종목명 캐시로 name 필드 보정
    name_map = load_stock_name_cache() or {}
    if name_map:
        for cd, detail in pending.items():
            base_cd = _base_stk_cd(cd)
            nm = name_map.get(base_cd)
            if nm and detail.get("name") in (cd, base_cd, "", None):
                detail["name"] = nm

    rows = [
        (cd, dict(detail))
        for cd, detail in pending.items()
        if detail.get("status") in ("active", "exited")
    ]
    if not rows and not amts_5d_arrays:
        _log.warning("[타이머] 저장 가능한 종목 및 5일봉 데이터 없음 — 저장데이터 저장 생략")
        return False

    try:
        highs_5d_arrays = getattr(es, "_highs_5d_arrays", {})

        # DB 저장 전 avg_5d 유효성 체크
        if sum(1 for stock in _master_stocks_cache.values() if int(stock.get("avg_5d_trade_amount", 0) or 0) > 0) < 100:
            _log.warning("[타이머] DB 저장 전 avg_5d_trade_amount 비정상 -- 백그라운드 갱신 예정")
        
        # ── master_stocks_table 저장 (Phase 1.2) ──
        try:
            from backend.app.db.database import get_db_connection
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            date_str = get_current_trading_day_str()
            
            # 대상 종목: pending 종목 및 amts_5d_arrays 종목 합집합
            all_target_codes = set(pending.keys()) | set(amts_5d_arrays.keys())
            
            for base_cd in all_target_codes:
                detail = pending.get(base_cd) or {}
                amts_5d = amts_5d_arrays.get(base_cd, [])
                highs_5d = highs_5d_arrays.get(base_cd, [])
                cd = base_cd

                day1_amt = amts_5d[0] if len(amts_5d) > 0 else 0
                day2_amt = amts_5d[1] if len(amts_5d) > 1 else 0
                day3_amt = amts_5d[2] if len(amts_5d) > 2 else 0
                day4_amt = amts_5d[3] if len(amts_5d) > 3 else 0
                day5_amt = amts_5d[4] if len(amts_5d) > 4 else 0

                day1_high = highs_5d[0] if len(highs_5d) > 0 else 0
                day2_high = highs_5d[1] if len(highs_5d) > 1 else 0
                day3_high = highs_5d[2] if len(highs_5d) > 2 else 0
                day4_high = highs_5d[3] if len(highs_5d) > 3 else 0
                day5_high = highs_5d[4] if len(highs_5d) > 4 else 0

                stk_nm = detail.get("name")
                if not stk_nm or stk_nm == cd:
                    stk_nm = name_map.get(_base_stk_cd(cd), cd)

                cursor.execute("""
                    INSERT OR REPLACE INTO master_stocks_table
                    (code, name, sector, cur_price, change, change_rate,
                     strength, trade_amount, avg_5d_trade_amount, high_5d_price,
                     day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                     day1_high, day2_high, day3_high, day4_high, day5_high, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cd,
                    stk_nm,
                    detail.get("sector", "기타"),
                    detail.get("cur_price", 0),
                    detail.get("change", 0),
                    detail.get("change_rate", 0.0),
                    detail.get("strength", "-"),
                    detail.get("trade_amount", 0),
                    avg_5d_map.get(base_cd, 0),
                    high_5d_map.get(base_cd, 0),
                    day1_amt, day2_amt, day3_amt, day4_amt, day5_amt,
                    day1_high, day2_high, day3_high, day4_high, day5_high,
                    date_str
                ))
            
            conn.commit()
            conn.close()
            _log.info("[타이머] master_stocks_table 저장 완료 -- %d종목 (date=%s)", len(all_target_codes), date_str)
        except Exception as e:
            _log.warning("[타이머] master_stocks_table 저장 실패: %s", e, exc_info=True)
        
        return True
    except Exception as exc:
        _log.warning("[타이머] 확정 데이터 DB 저장 실패: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 통합 확정 데이터 조회 (20:30)
# ---------------------------------------------------------------------------

async def fetch_unified_confirmed_data(es: ModuleType) -> dict:
    """20:30 통합 확정 조회 — 전종목 대상 ka10099 + ka10081 + 후처리.

    1단계 ka10099: 전종목 목록 갱신 (레이아웃 캐시 + 종목명 캐시 + 신규 종목 섹터 매핑)
    2단계 ka10081: 전종목 확정 시세 순차 호출 (interval_sec=0.33) → 메모리 + 디스크 갱신
       - 이어받기 지원: 20종목마다 진행 저장, 재기동 시 중단 지점부터 계속
    3단계 후처리: 스냅샷 및 캐시 저장 (롤링 갱신 생략)

    Args:
        es: engine_service 모듈 참조

    Returns:
        {"fetched": int, "failed": int, "cached": bool}
    """
    from backend.app.core.broker_factory import get_router
    from backend.app.core.sector_stock_cache import (
        save_stock_name_cache,
        load_progress_cache,
        clear_progress_cache,
    )
    from backend.app.core.trading_calendar import get_kst_today_str

    _settings = getattr(es, "_settings_cache", {}) or {}

    # 중복 실행 방지
    if getattr(es, "_confirmed_refresh_running", False):
        _log.info("[타이머] 확정 조회 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running = True
    es._confirmed_refresh_message = ""

    try:
    
        # ── 메모리 전체 초기화 — 새 데이터로 완전 교체 (정합성 보장) ──────────
        getattr(es, "_pending_stock_details", {}).clear()
        _layout = getattr(es, "_sector_stock_layout", None)
        if _layout is not None:
            _layout.clear()
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        import backend.app.core.industry_map as _ind_mod
        _ind_mod._eligible_stock_codes.clear()
        _log.info("[타이머] 메모리 전체 초기화 완료 — 새 데이터로 교체 시작")
    
        # 스케줄러 토글 OFF 시 전체 갱신 스킵
        if not _settings.get("scheduler_market_close_on", True):
            _log.info("[타이머] scheduler_market_close_on=OFF — 전체 갱신 생략")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        from backend.app.core.broker_factory import get_router
        _router = get_router()
        _auth = _router.get_auth_provider("kiwoom")
        _sector = KiwoomStockProvider(_settings, auth_provider=_auth)
    
        # ── Pipeline events ──────────────────────────────────────────────────
        data_fetched_event = asyncio.Event()
        parsing_done_event = asyncio.Event()
        filtering_done_event = asyncio.Event()
        save_done_event = asyncio.Event()
    
        # ── Step 1: API 호출 (raw data 수집) ─────────────────────────────────
        _log.info("[타이머] Step 1 시작 — ka10099 전종목 리스트 다운로드 (코스피+코스닥)")
        _broadcast_confirmed_progress(0, 0, message="전종목 목록 갱신 중...", step=1)
        try:
            from backend.app.core.broker_providers import UnifiedStockRecord
            records: list[UnifiedStockRecord] = await _sector.fetch_unified_stock_data()
            if not records:
                _log.warning("[타이머] ka10099 결과 비어있음 — 통합 확정 조회 중단")
                es._confirmed_refresh_running = False
                es._confirmed_refresh_message = ""
                return {"fetched": 0, "failed": 0, "cached": False}
            # marketCode 분포 카운트 ("0"=코스피, "10"=코스닥, 나머지=ETF/ETN 등)
            kospi_count = sum(1 for r in records if r.market_code == "0")
            kosdaq_count = sum(1 for r in records if r.market_code == "10")
            other_count = len(records) - kospi_count - kosdaq_count
            data_fetched_event.set()
            _log.info(
                "[타이머] Step 1 완료 — ka10099 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)",
                len(records), kospi_count, kosdaq_count, other_count
            )
        except Exception as exc:
            _log.warning("[타이머] ka10099 통합 조회 실패: %s", exc, exc_info=True)
            # data_fetched_event 미발행 → Step 2 타임아웃으로 자동 중단
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 2: 적격 종목 필터링 (매매부적격 종목 제외) ─────────────────
        _log.info("[타이머] Step 2 시작 — 적격 종목 필터링 (매매부적격 종목 제외)")
        _broadcast_confirmed_progress(0, 0, message="2단계: 매매부적격종목 필터링 중...", step=2)
        try:
            await asyncio.wait_for(data_fetched_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[타이머] Step 2 대기 타임아웃 — data_fetched_event 미수신, 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            confirmed_codes: set[str] = set()
            filter_reasons: dict[str, int] = {}
            from backend.app.core.stock_filter import is_excluded
            for r in records:
                excluded, reason = is_excluded(r.raw_item, r.code)
                if excluded:
                    filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                else:
                    confirmed_codes.add(r.code)

            excluded_count = len(records) - len(confirmed_codes)
            pct = (excluded_count / len(records) * 100) if records else 0
            _log.info(
                "[타이머] Step 2 완료 — 대상: %d종목, 필터링 통과: %d종목, 제외 사유: %s",
                len(records), len(confirmed_codes), filter_reasons,
            )
            _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 완료: 총 {len(records)}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)
            await asyncio.sleep(1.5)

            summary_str = f"전체 {len(records)}종목 → 적격 {len(confirmed_codes)}종목 (제외 {excluded_count}종목, {pct:.1f}%)"
            if filter_reasons:
                top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
                _log.info("[타이머] 주요 부적격 사유 (Top 5): %s", dict(top_reasons))

                reason_strs = []
                for k, v in top_reasons:
                    if "(" in k:
                        k_clean = k.split("(")[-1].replace(")", "")
                    else:
                        k_clean = k.split("=")[-1]
                    reason_strs.append(f"{k_clean} {v}개")
                summary_str += " | 주요 부적격: " + ", ".join(reason_strs)

            es._latest_filter_summary = summary_str
            from backend.app.core.sector_stock_cache import save_filter_summary_cache
            await save_filter_summary_cache(summary_str)

            try:
                from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
                await broadcast_stock_classification_changed()
            except Exception as e:
                _log.warning("Failed to broadcast filter summary: %s", e)

            filtering_done_event.set()
        except Exception as exc:
            _log.warning("[타이머] Step 2 필터링 실패: %s — filtering_done_event 미발행", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        # ── Step 3: 적격 종목만 파싱/매칭 (종목명/시장구분) ───────────────────
        _log.info("[타이머] Step 3 시작 — 적격 종목 파싱 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="종목 정보 파싱 중...", step=3)
        try:
            await asyncio.wait_for(filtering_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[타이머] Step 3 대기 타임아웃 — filtering_done_event 미수신, 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        try:
            name_map: dict[str, str] = {}
            market_map: dict[str, str] = {}
            for r in records:
                if r.code in confirmed_codes:
                    name_map[r.code] = r.name
                    market_map[r.code] = r.market_code
            parsing_done_event.set()
            _log.info("[타이머] Step 3 완료 — %d종목 파싱/매칭 (종목명/시장구분)", len(name_map))
        except Exception as exc:
            _log.warning("[타이머] Step 3 파싱/매칭 실패: %s — parsing_done_event 미발행", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        # ── Step 4: 동일 종목 집합으로 4개 캐시 저장 + 레이아웃 ──────────────
        _log.info("[타이머] Step 4 시작 — 종목명/업종/시장구분 캐시 저장 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="캐시 저장 중...", step=4)
        try:
            await asyncio.wait_for(parsing_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[타이머] Step 4 대기 타임아웃 — parsing_done_event 미수신, 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        try:
            await save_stock_name_cache(name_map)
    
            import backend.app.core.industry_map as _ind_mod
            eligible_map: dict[str, str] = {cd: "" for cd in confirmed_codes}
            await _ind_mod.persist_eligible_stocks_cache(eligible_map)
            _ind_mod._eligible_stock_codes = eligible_map
    
            from backend.app.core.sector_stock_cache import save_market_map_cache
            # NXT 정보는 서버 응답(nxtEnable)에서 파싱한 원본값 사용 [출처: kiwoom_rest.py:621]
            nxt_map = {r.code: r.nxt_enable for r in records if r.code in confirmed_codes}
            await save_market_map_cache(market_map, nxt_map)
    
            all_codes = list(confirmed_codes)
            await _update_layout_cache(es, all_codes, name_map)
            save_done_event.set()
            _log.info("[타이머] Step 4 완료 — 3개 저장데이터 저장 (%d종목)", len(confirmed_codes))
        except Exception as exc:
            _log.warning("[타이머] Step 4 저장데이터 저장 실패: %s — save_done_event 미발행", exc, exc_info=True)
            # save_done_event 미발행 → 후속 단계 진행 불가
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        # ── 2단계 ka10081: 전종목 확정 시세 순차 호출 (이어받기 지원) ───────
        # 20:30 이전 시간 가드 (Phase 2.1 단계 3)
        from backend.app.services.daily_time_scheduler import is_heavy_operation_allowed
        if not is_heavy_operation_allowed():
            _log.info("[타이머] 안전 구역(20:30~연결시작전) 외 시간대 진입으로 인한 Step 5 ka10081 전종목 확정 시세 다운로드 스킵")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        _log.info("[타이머] Step 5 시작 — ka10081 전종목 확정 시세 다운로드 (%d종목)", len(all_codes))
        qry_dt = get_kst_today_str()
        total = len(all_codes)
        _main_loop = asyncio.get_running_loop()

        # 사용자 설정의 ws_subscribe_start 시간 확인 (진행 파일 유효 기간용)
        _settings = getattr(es, "_settings_cache", {}) or {}
        ws_subscribe_start = str(_settings.get("ws_subscribe_start") or "07:50")

        # 이어받기: 진행 파일 로드 (다음 거래일 ws_subscribe_start까지 유효)
        resume_codes = await load_progress_cache(qry_dt, all_codes, ws_subscribe_start)
        starting_count = len(resume_codes)

        if starting_count > 0:
            _log.info("[타이머] 이어받기 — %d/%d종목부터 계속", starting_count, total)
            _broadcast_confirmed_progress(
                starting_count, total,
                message=f"전종목 확정시세 데이터 다운로드 중 ({starting_count}/{total:,}, {int(starting_count/total*100)}%) - 이어받기",
                step=5
            )
        else:
            _broadcast_confirmed_progress(0, total, message=f"전종목 확정시세 데이터 다운로드 중 (0/{total:,}, 0%)", step=5)

        def _on_progress(cur: int, tot: int) -> None:
            remaining = total - cur
            eta = remaining * 1.0
            _pct = int(cur / total * 100) if total > 0 else 0
            # 중복 로그 제거: kiwoom_stock_rest.py에서 1종목 단위 실시간 로그 출력 중
            _broadcast_confirmed_progress(
                cur, total,
                message=f"전종목 확정시세 데이터 다운로드 중 ({cur:,}/{total:,}, {_pct}%)",
                eta_sec=eta,
                step=5,
                _loop=_main_loop,
            )

        try:
            confirmed = await _sector.fetch_all_stocks_daily_confirmed(
                all_codes, qry_dt, interval_sec=0.33, on_progress=_on_progress,
                resume_codes=resume_codes,  # 이어받기 지원
            )
        except Exception as exc:
            _log.warning("[타이머] ka10081 전종목 조회 실패: %s", exc, exc_info=True)
            confirmed = {}

        fetched = len(confirmed)
        failed = total - fetched
        success_rate = (fetched / total * 100) if total else 0
        _log.info(
            "[타이머] Step 5 완료 — ka10081 확정 시세 다운로드: 성공 %d종목, 실패 %d종목 (%.1f%% 성공)",
            fetched, failed, success_rate
        )
        # 실패율이 1% 이상이면 경고 로그 (디버깅용)
        if failed > 0 and success_rate < 99.0:
            _log.warning(
                "[타이머] ka10081 실패율 높음: %d/%d종목 (%.1f%%) — custom_sector 로그에서 실패 원인 확인",
                failed, total, 100 - success_rate
            )

        # 메모리 반영 (확정시세만)
        if confirmed:
            await _apply_confirmed_to_memory(es, confirmed, {}, name_map=name_map)

        # 5일봉 데이터 메모리 및 DB 반영
        if confirmed:
            await _apply_5d_to_memory(es, confirmed)

        # 디스크 캐시 저장
        cached = await _save_confirmed_cache(es)

        # 완료 후 진행 파일 삭제
        if cached:
            await clear_progress_cache()

        _broadcast_confirmed_progress(total, total, message=f"전종목 확정시세 데이터 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # ── 3단계 후처리: v2 캐시 롤링 (업종순위 재계산 안 함) ────────────────
        _broadcast_confirmed_progress(total, total, message="5일 거래대금 계산 중...", step=5)
        await _run_post_confirmed_pipeline(es)
    
        # ── Step 6: 완전한 매핑 단계 (적격종목 × 시세 데이터 매핑) ────────────
        if cached:
            import backend.app.core.industry_map as _ind_mod_step6
            final_eligible = set(_ind_mod_step6._eligible_stock_codes.keys())
            if not final_eligible:
                _log.warning("[타이머] Step 6 — 적격종목 비어있음, 메모리 교체 생략")
            else:
                # _apply_confirmed_to_memory가 이미 es._pending_stock_details를 업데이트했으므로
                # 최신 다운로드 데이터가 포함된 es._pending_stock_details를 직접 필터링
                mapped_pending = {cd: es._pending_stock_details[cd] for cd in final_eligible if cd in es._pending_stock_details}

                # ── Step 7: 원자적 메모리 교체 (_shared_lock 내부) ────────────
                async with es._shared_lock:
                    es._pending_stock_details.clear()
                    for key, value in mapped_pending.items():
                        es._pending_stock_details[key] = value
                    es._radar_cnsr_order[:] = [
                        cd for cd in es._radar_cnsr_order if cd in final_eligible
                    ]

                _log.info(
                    "[타이머] Step 7 원자적 메모리 교체 완료 — pending=%d종목",
                    len(mapped_pending),
                )
        else:
            _log.warning("[타이머] cached=False — 메모리 교체 생략 (기존 상태 유지)")

        # ── 4단계: 업종순위 재계산 + WS 브로드캐스트 (화면 자동 갱신) ────────
        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_scores,
                notify_desktop_sector_stocks_refresh,
            )
            recompute_sector_summary_now()
            notify_desktop_sector_scores(force=True)
            notify_desktop_sector_stocks_refresh()
            _log.info("[타이머] 확정 조회 후 업종순위 재계산 + 실시간 화면전송 완료")
        except Exception as _ws_err:
            _log.warning("[타이머] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)
            _log.warning("[타이머] 확정 조회 후 실시간 화면전송 실패(무시): %s", _ws_err)

        # 파이프라인 전체 완료 로그
        if cached:
            _log.info(
                "[타이머] === 전체 완료 === 총 %d단계 | ka10099: %d종목 | 적격: %d종목 | ka10081: %d/%d종목 | 저장데이터: %s",
                5, len(all_codes), len(final_eligible) if 'final_eligible' in locals() else 0, fetched, total, "성공"
            )
        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        es._confirmed_refresh_running = False
        es._confirmed_refresh_message = ""


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
    - 섹터 헤더가 없는 종목("기타")도 레이아웃에 포함된다.
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
        # 1) pending stock details 캐시 확인
        sec = None
        entry = es._pending_stock_details.get(cd)
        if entry and "sector" in entry:
            sec = entry["sector"]
        # 2) DB 매핑 확인
        if not sec:
            sec = db_mapping.get(_base_stk_cd(cd))
        # 3) 기본값
        if not sec:
            sec = "기타"
            
        sector_groups.setdefault(sec, []).append(cd)

    # 섹터 내 종목 정렬 (재현성 보장)
    for sec in sector_groups:
        sector_groups[sec].sort()

    # 섹터 순서: 기존 레이아웃의 섹터 순서를 최대한 유지하고 신규 섹터는 뒤에 추가
    old_layout: list[tuple[str, str]] = getattr(es, "_sector_stock_layout", [])
    old_sector_order = list(dict.fromkeys(v for t, v in old_layout if t == "sector"))

    new_sectors = [s for s in sector_groups if s not in old_sector_order]
    final_sector_order = [s for s in old_sector_order if s in sector_groups] + new_sectors

    # 레이아웃 재구성
    new_layout: list[tuple[str, str]] = []
    for sec in final_sector_order:
        new_layout.append(("sector", sec))
        for cd in sector_groups[sec]:
            new_layout.append(("code", cd))

    es._sector_stock_layout = new_layout
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache(new_layout)
    # sector_layout 캐시 저장 삭제 (master_stocks_table sector 컬럼으로 대체)
    _log.info(
        "[타이머] 레이아웃 저장데이터 완전 재구성 — %d종목, %d업종",
        len(all_codes), len(final_sector_order),
    )


# ---------------------------------------------------------------------------
# 수동 확정시세 및 5일봉 다운로드
# ---------------------------------------------------------------------------

async def fetch_confirmed_data_only() -> dict:
    """수동 매매적격종목 확정시세 다운로드 파이프라인.
    
    진행 과정 (Step 1 ~ Step 5) 및 브로드캐스트를 지원하며,
    다운로드 완료 시 5일봉 배열 롤링 갱신을 적용하고 DB에 저장합니다.
    """
    from backend.app.services import engine_service as es
    from backend.app.core.broker_factory import get_router
    from backend.app.core.sector_stock_cache import (
        save_stock_name_cache,
        load_progress_cache,
        clear_progress_cache,
    )
    from backend.app.core.trading_calendar import get_kst_today_str

    _settings = getattr(es, "_settings_cache", {}) or {}

    # 중복 실행 방지
    if getattr(es, "_confirmed_refresh_running", False):
        _log.info("[수동 확정시세] 다운로드 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running = True
    es._confirmed_refresh_message = ""

    try:
        # ── 메모리 전체 초기화 — 새 데이터로 완전 교체 (정합성 보장) ──────────
        getattr(es, "_pending_stock_details", {}).clear()
        _layout = getattr(es, "_sector_stock_layout", None)
        if _layout is not None:
            _layout.clear()
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        getattr(es, "_avg_amt_5d", {}).clear()
        getattr(es, "_high_5d_cache", {}).clear()
        import backend.app.core.industry_map as _ind_mod
        _ind_mod._eligible_stock_codes.clear()
        _log.info("[수동 확정시세] 메모리 전체 초기화 완료 — 새 데이터로 교체 시작")

        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        from backend.app.core.broker_factory import get_router
        _router = get_router()
        _auth = _router.get_auth_provider("kiwoom")
        _sector = KiwoomStockProvider(_settings, auth_provider=_auth)

        # ── Pipeline events ──────────────────────────────────────────────────
        data_fetched_event = asyncio.Event()
        parsing_done_event = asyncio.Event()
        filtering_done_event = asyncio.Event()
        save_done_event = asyncio.Event()

        # ── Step 1: API 호출 (raw data 수집) ─────────────────────────────────
        _log.info("[수동 확정시세] Step 1 시작 — ka10099 전종목 리스트 다운로드 (코스피+코스닥)")
        _broadcast_confirmed_progress(0, 0, message="1단계: 코스피/코스닥 전종목 목록 수집 중...", step=1)
        try:
            from backend.app.core.broker_providers import UnifiedStockRecord
            records: list[UnifiedStockRecord] = await _sector.fetch_unified_stock_data()
            if not records:
                _log.warning("[수동 확정시세] 전종목 목록 수집 결과 비어있음 — 중단")
                es._confirmed_refresh_running = False
                es._confirmed_refresh_message = ""
                return {"fetched": 0, "failed": 0, "cached": False}
            kospi_count = sum(1 for r in records if r.market_code == "0")
            kosdaq_count = sum(1 for r in records if r.market_code == "10")
            other_count = len(records) - kospi_count - kosdaq_count
            data_fetched_event.set()
            _log.info(
                "[수동 확정시세] Step 1 완료 — ka10099 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)",
                len(records), kospi_count, kosdaq_count, other_count
            )
        except Exception as exc:
            _log.warning("[수동 확정시세] ka10099 통합 조회 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 2: 적격 종목 필터링 (매매부적격 종목 제외) ─────────────────
        _log.info("[수동 확정시세] Step 2 시작 — 적격 종목 필터링")
        _broadcast_confirmed_progress(0, 0, message="2단계: 매매부적격종목 필터링 중...", step=2)
        try:
            await asyncio.wait_for(data_fetched_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 확정시세] Step 2 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            confirmed_codes: set[str] = set()
            filter_reasons: dict[str, int] = {}
            from backend.app.core.stock_filter import is_excluded
            for r in records:
                excluded, reason = is_excluded(r.raw_item, r.code)
                if excluded:
                    filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                else:
                    confirmed_codes.add(r.code)

            excluded_count = len(records) - len(confirmed_codes)
            pct = (excluded_count / len(records) * 100) if records else 0
            _log.info(
                "[수동 확정시세] Step 2 완료 — 대상: %d종목, 필터링 통과: %d종목, 제외 사유: %s",
                len(records), len(confirmed_codes), filter_reasons,
            )
            _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 완료: 총 {len(records)}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)
            await asyncio.sleep(1.5)

            summary_str = f"전체 {len(records)}종목 → 적격 {len(confirmed_codes)}종목 (제외 {excluded_count}종목, {pct:.1f}%)"
            if filter_reasons:
                top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
                _log.info("[수동 확정시세] 주요 부적격 사유 (Top 5): %s", dict(top_reasons))

                reason_strs = []
                for k, v in top_reasons:
                    if "(" in k:
                        k_clean = k.split("(")[-1].replace(")", "")
                    else:
                        k_clean = k.split("=")[-1]
                    reason_strs.append(f"{k_clean} {v}개")
                summary_str += " | 주요 부적격: " + ", ".join(reason_strs)

            es._latest_filter_summary = summary_str
            from backend.app.core.sector_stock_cache import save_filter_summary_cache
            await save_filter_summary_cache(summary_str)

            try:
                from backend.app.web.routes.stock_classification import broadcast_stock_classification_changed
                await broadcast_stock_classification_changed()
            except Exception as e:
                _log.warning("Failed to broadcast filter summary: %s", e)

            filtering_done_event.set()
        except Exception as exc:
            _log.warning("[수동 확정시세] Step 2 필터링 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 3: 적격 종목만 파싱/매칭 (종목명/시장구분) ───────────────────
        _log.info("[수동 확정시세] Step 3 시작 — 적격 종목 파싱 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="3단계: 종목 정보 파싱 중...", step=3)
        try:
            await asyncio.wait_for(filtering_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 확정시세] Step 3 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            name_map: dict[str, str] = {}
            market_map: dict[str, str] = {}
            for r in records:
                if r.code in confirmed_codes:
                    name_map[r.code] = r.name
                    market_map[r.code] = r.market_code
            parsing_done_event.set()
            _log.info("[수동 확정시세] Step 3 완료 — %d종목 파싱/매칭 완료", len(name_map))
        except Exception as exc:
            _log.warning("[수동 확정시세] Step 3 파싱/매칭 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 4: 동일 종목 집합으로 4개 캐시 저장 + 레이아웃 ──────────────
        _log.info("[수동 확정시세] Step 4 시작 — 종목명/업종/시장구분 캐시 저장 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="4단계: 디스크 캐시 저장 중...", step=4)
        try:
            await asyncio.wait_for(parsing_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 확정시세] Step 4 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            await save_stock_name_cache(name_map)

            import backend.app.core.industry_map as _ind_mod
            eligible_map: dict[str, str] = {cd: "" for cd in confirmed_codes}
            await _ind_mod.persist_eligible_stocks_cache(eligible_map)
            _ind_mod._eligible_stock_codes = eligible_map

            from backend.app.core.sector_stock_cache import save_market_map_cache
            nxt_map = {r.code: r.nxt_enable for r in records if r.code in confirmed_codes}
            # market/nxt_enable 정보를 master_stocks_table에 직접 업데이트 (단일 진실 공급원)
            from backend.app.db.database import get_db_connection as _get_conn
            _conn = await _get_conn()
            _mst_updates = [
                (r.market_code, 1 if r.nxt_enable else 0, r.code)
                for r in records if r.code in confirmed_codes
            ]
            if _mst_updates:
                await _conn.executemany(
                    "UPDATE master_stocks_table SET market=?, nxt_enable=? WHERE code=?",
                    _mst_updates
                )
                await _conn.commit()
                import backend.app.services.engine_state as _st
                for r in records:
                    if r.code in confirmed_codes and r.code in _st._master_stocks_cache:
                        _st._master_stocks_cache[r.code]["market"] = r.market_code
                        _st._master_stocks_cache[r.code]["nxt_enable"] = bool(r.nxt_enable)

            all_codes = list(confirmed_codes)
            await _update_layout_cache(es, all_codes, name_map)
            save_done_event.set()
            _log.info("[수동 확정시세] Step 4 완료 — 저장데이터 저장 완료 (%d종목)", len(confirmed_codes))
        except Exception as exc:
            _log.warning("[수동 확정시세] Step 4 저장데이터 저장 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 5: 개별 확정 시세 다운로드 ───────
        _log.info("[수동 확정시세] Step 5 시작 — 전종목 확정 시세 다운로드 (%d종목)", len(all_codes))
        qry_dt = get_kst_today_str()
        total = len(all_codes)
        _main_loop = asyncio.get_running_loop()

        # 이어받기
        ws_subscribe_start = str(_settings.get("ws_subscribe_start") or "07:50")
        resume_codes = await load_progress_cache(qry_dt, all_codes, ws_subscribe_start)
        starting_count = len(resume_codes)

        if starting_count > 0:
            _log.info("[수동 확정시세] 이어받기 — %d/%d종목부터 계속", starting_count, total)
            _broadcast_confirmed_progress(
                starting_count, total,
                message=f"5단계: 개별 확정시세 데이터 다운로드 중 ({starting_count}/{total:,}, {int(starting_count/total*100)}%) - 이어받기",
                step=5
            )
        else:
            _broadcast_confirmed_progress(0, total, message=f"5단계: 개별 확정시세 데이터 다운로드 중 (0/{total:,}, 0%)", step=5)

        def _on_progress(cur: int, tot: int) -> None:
            remaining = total - cur
            eta = remaining * 1.0
            _pct = int(cur / total * 100) if total > 0 else 0
            # 중복 로그 제거: kiwoom_stock_rest.py에서 1종목 단위 실시간 로그 출력 중
            _broadcast_confirmed_progress(
                cur, total,
                message=f"5단계: 개별 확정시세 데이터 다운로드 중 ({cur:,}/{total:,}, {_pct}%)",
                eta_sec=eta,
                step=5,
                _loop=_main_loop,
            )

        try:
            confirmed = await _sector.fetch_all_stocks_daily_confirmed(
                all_codes, qry_dt, interval_sec=0.33, on_progress=_on_progress,
                resume_codes=resume_codes,
            )
        except Exception as exc:
            _log.warning("[수동 확정시세] ka10081 전종목 조회 실패: %s", exc, exc_info=True)
            confirmed = {}

        fetched = len(confirmed)
        failed = total - fetched
        success_rate = (fetched / total * 100) if total else 0
        _log.info(
            "[수동 확정시세] Step 5 완료 — ka10081 확정 시세 다운로드: 성공 %d종목, 실패 %d종목 (%.1f%% 성공)",
            fetched, failed, success_rate
        )

        for code, details in list(confirmed.items()):
            cur_price = details.get("close") or details.get("cur_price") or 0
            trade_amount = details.get("value") or details.get("trade_amount") or 0
            _log.info("[수동 확정시세 다운로드] [%d/%d] 종목 %s 다운로드 완료 (현재가=%d, 거래대금=%d)", 
                      list(confirmed.keys()).index(code) + 1, fetched, code, cur_price, trade_amount)

        # 메모리 반영 (확정시세 반영 + 5일 배열 롤링)
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
                    "prev_close": val.get("open") or val.get("prev_close") or 0,
                }
            await _apply_confirmed_to_memory(es, normalized_confirmed, {}, name_map=name_map)

        # 디스크 캐시 저장
        cached = await _save_confirmed_cache(es)

        # 완료 후 진행 파일 삭제
        if cached:
            await clear_progress_cache()

        _broadcast_confirmed_progress(total, total, message=f"✅ 확정시세 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # 후처리
        await _run_post_confirmed_pipeline(es)
    
        # Step 6/7/8: 원자적 메모리 교체 및 업종순위 재계산
        if cached:
            import backend.app.core.industry_map as _ind_mod_step6
            final_eligible = set(_ind_mod_step6._eligible_stock_codes.keys())
            if final_eligible:
                mapped_pending: dict = {}
                for cd in final_eligible:
                    entry = es._pending_stock_details.get(cd)
                    if entry is not None:
                        mapped_pending[cd] = entry

                new_avg = {cd: v for cd, v in es._avg_amt_5d.items() if cd in final_eligible}
                new_high = {cd: v for cd, v in es._high_5d_cache.items() if cd in final_eligible}

                async with es._shared_lock:
                    es._pending_stock_details.clear()
                    es._pending_stock_details.update(mapped_pending)
                    es._avg_amt_5d.clear()
                    es._avg_amt_5d.update(new_avg)
                    es._high_5d_cache.clear()
                    es._high_5d_cache.update(new_high)
                    es._radar_cnsr_order[:] = [
                        cd for cd in es._radar_cnsr_order if cd in final_eligible
                    ]

                _log.info(
                    "[수동 확정시세] Step 7 원자적 메모리 교체 완료 — pending=%d종목, avg=%d, high=%d",
                    len(mapped_pending), len(new_avg), len(new_high),
                )
        
        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_scores,
                notify_desktop_sector_stocks_refresh,
            )
            recompute_sector_summary_now()
            notify_desktop_sector_scores(force=True)
            notify_desktop_sector_stocks_refresh()
            _log.info("[수동 확정시세] 업종순위 재계산 + 실시간 화면전송 완료")
        except Exception as _ws_err:
            _log.warning("[수동 확정시세] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)

        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        es._confirmed_refresh_running = False
        es._confirmed_refresh_message = ""


async def fetch_5d_data_only() -> dict:
    """수동 5일봉 거래대금,고가 다운로드 파이프라인.
    
    진행 과정 (Step 1 ~ Step 5) 및 브로드캐스트를 지원하며,
    개별 종목의 5일 고가 및 거래대금 데이터를 다운로드하여 DB 및 메모리에 저장합니다.
    """
    from backend.app.services import engine_service as es
    from backend.app.core.broker_factory import get_router
    from backend.app.core.sector_stock_cache import save_stock_name_cache
    from backend.app.core.trading_calendar import get_kst_today_str

    _settings = getattr(es, "_settings_cache", {}) or {}

    # 중복 실행 방지
    if getattr(es, "_confirmed_refresh_running", False):
        _log.info("[수동 5일봉] 다운로드 이미 진행 중 — 생략")
        return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    es._confirmed_refresh_running = True
    es._confirmed_refresh_message = ""

    try:
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        from backend.app.core.broker_factory import get_router
        _router = get_router()
        _auth = _router.get_auth_provider("kiwoom")
        _sector = KiwoomStockProvider(_settings, auth_provider=_auth)

        # ── Pipeline events ──────────────────────────────────────────────────
        data_fetched_event = asyncio.Event()
        parsing_done_event = asyncio.Event()
        filtering_done_event = asyncio.Event()
        save_done_event = asyncio.Event()

        # ── Step 1: API 호출 (raw data 수집) ─────────────────────────────────
        _log.info("[수동 5일봉] Step 1 시작 — ka10099 전종목 리스트 다운로드 (코스피+코스닥)")
        _broadcast_confirmed_progress(0, 0, message="1단계: 코스피/코스닥 전종목 목록 수집 중...", step=1)
        try:
            from backend.app.core.broker_providers import UnifiedStockRecord
            records: list[UnifiedStockRecord] = await _sector.fetch_unified_stock_data()
            if not records:
                _log.warning("[수동 5일봉] 전종목 목록 수집 결과 비어있음 — 중단")
                es._confirmed_refresh_running = False
                es._confirmed_refresh_message = ""
                return {"fetched": 0, "failed": 0, "cached": False}
            kospi_count = sum(1 for r in records if r.market_code == "0")
            kosdaq_count = sum(1 for r in records if r.market_code == "10")
            other_count = len(records) - kospi_count - kosdaq_count
            data_fetched_event.set()
            _log.info(
                "[수동 5일봉] Step 1 완료 — ka10099 총 %d종목 (코스피 %d, 코스닥 %d, 기타 %d)",
                len(records), kospi_count, kosdaq_count, other_count
            )
        except Exception as exc:
            _log.warning("[수동 5일봉] ka10099 통합 조회 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 2: 적격 종목 필터링 (매매부적격 종목 제외) ─────────────────
        _log.info("[수동 5일봉] Step 2 시작 — 적격 종목 필터링")
        _broadcast_confirmed_progress(0, 0, message="2단계: 매매부적격종목 필터링 중...", step=2)
        try:
            await asyncio.wait_for(data_fetched_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 5일봉] Step 2 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            confirmed_codes: set[str] = set()
            filter_reasons: dict[str, int] = {}
            from backend.app.core.stock_filter import is_excluded
            for r in records:
                excluded, reason = is_excluded(r.raw_item, r.code)
                if excluded:
                    filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                else:
                    confirmed_codes.add(r.code)

            excluded_count = len(records) - len(confirmed_codes)
            pct = (excluded_count / len(records) * 100) if records else 0
            _log.info(
                "[수동 5일봉] Step 2 완료 — 대상: %d종목, 필터링 통과: %d종목, 제외 사유: %s",
                len(records), len(confirmed_codes), filter_reasons,
            )
            _broadcast_confirmed_progress(0, 0, message=f"✅ 2단계 완료: 총 {len(records)}종목 중 {len(confirmed_codes)}종목 적격 판정", step=2)
            await asyncio.sleep(1.5)

            summary_str = f"전체 {len(records)}종목 → 적격 {len(confirmed_codes)}종목 (제외 {excluded_count}종목, {pct:.1f}%)"
            if filter_reasons:
                top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
                _log.info("[수동 5일봉] 주요 부적격 사유 (Top 5): %s", dict(top_reasons))
                reason_strs = [f"{k.split('=')[-1]} {v}개" for k, v in top_reasons]
                summary_str += " | 주요 부적격: " + ", ".join(reason_strs)
            es._latest_filter_summary = summary_str
            from backend.app.core.sector_stock_cache import save_filter_summary_cache
            await save_filter_summary_cache(summary_str)

            filtering_done_event.set()
        except Exception as exc:
            _log.warning("[수동 5일봉] Step 2 필터링 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 3: 적격 종목만 파싱/매칭 (종목명/시장구분) ───────────────────
        _log.info("[수동 5일봉] Step 3 시작 — 적격 종목 파싱 (%d종목)", len(confirmed_codes))
        _broadcast_confirmed_progress(0, 0, message="3단계: 종목 정보 파싱 중...", step=3)
        try:
            await asyncio.wait_for(filtering_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 5일봉] Step 3 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            name_map: dict[str, str] = {}
            market_map: dict[str, str] = {}
            for r in records:
                if r.code in confirmed_codes:
                    name_map[r.code] = r.name
                    market_map[r.code] = r.market_code
            parsing_done_event.set()
            _log.info("[수동 5일봉] Step 3 완료 — %d종목 파싱/매칭 완료", len(name_map))
        except Exception as exc:
            _log.warning("[수동 5일봉] Step 3 파싱/매칭 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 4: 동일 종목 집합으로 4개 캐시 저장 + 레이아웃 ──────────────
        _log.info("[수동 5일봉] Step 4 시작 — 캐시 저장")
        _broadcast_confirmed_progress(0, 0, message="4단계: 디스크 캐시 저장 중...", step=4)
        try:
            await asyncio.wait_for(parsing_done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[수동 5일봉] Step 4 대기 타임아웃 — 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        try:
            await save_stock_name_cache(name_map)

            import backend.app.core.industry_map as _ind_mod
            eligible_map: dict[str, str] = {cd: "" for cd in confirmed_codes}
            await _ind_mod.persist_eligible_stocks_cache(eligible_map)
            _ind_mod._eligible_stock_codes = eligible_map

            # market/nxt_enable 정보를 master_stocks_table에 직접 업데이트 (단일 진실 공급원)
            from backend.app.db.database import get_db_connection as _get_conn
            _conn = await _get_conn()
            _mst_updates = [
                (r.market_code, 1 if r.nxt_enable else 0, r.code)
                for r in records if r.code in confirmed_codes
            ]
            if _mst_updates:
                await _conn.executemany(
                    "UPDATE master_stocks_table SET market=?, nxt_enable=? WHERE code=?",
                    _mst_updates
                )
                await _conn.commit()
                import backend.app.services.engine_state as _st
                for r in records:
                    if r.code in confirmed_codes and r.code in _st._master_stocks_cache:
                        _st._master_stocks_cache[r.code]["market"] = r.market_code
                        _st._master_stocks_cache[r.code]["nxt_enable"] = bool(r.nxt_enable)

            all_codes = list(confirmed_codes)
            await _update_layout_cache(es, all_codes, name_map)
            save_done_event.set()
            _log.info("[수동 5일봉] Step 4 완료")
        except Exception as exc:
            _log.warning("[수동 5일봉] Step 4 저장데이터 저장 실패: %s", exc, exc_info=True)
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}

        # ── Step 5: 개별 5일봉 데이터 다운로드 ───────
        total = len(all_codes)
        _log.info("[수동 5일봉] Step 5 시작 — 개별 5일봉 다운로드 (%d종목)", total)
        _broadcast_confirmed_progress(0, total, message=f"5단계: 개별 5일봉 데이터 다운로드 중 (0/{total:,}, 0%)", step=5)

        # _master_stocks_cache에서 sector 정보 직접 읽기 (단일 진실 공급원)
        import backend.app.services.engine_state as _st_cache
        db_mapping = {
            code: data.get("sector", "기타")
            for code, data in _st_cache._master_stocks_cache.items()
        }

        fetched = 0
        failed = 0

        for idx, base_cd in enumerate(all_codes):
            nk = _format_kiwoom_reg_stk_cd(base_cd)
            if not nk:
                failed += 1
                continue

            try:
                # 5일치 고가(high)와 거래대금(value) 다운로드
                qry_dt = get_kst_today_str()
                res = await _sector.fetch_stock_5day_data(base_cd, qry_dt)
                amounts_5d = res.get("amts_5d_array") or [] if res else []
                highs_5d = res.get("highs_5d_array") or [] if res else []

                if amounts_5d and highs_5d and len(amounts_5d) > 0 and len(highs_5d) > 0:
                    # _pending_stock_details 에 기본 종목 정보 등록 보장
                    if nk not in es._pending_stock_details:
                        from backend.app.services.engine_strategy_core import make_detail
                        stk_nm = name_map.get(_base_stk_cd(nk), nk)
                        sec = db_mapping.get(_base_stk_cd(nk)) or "기타"
                        es._pending_stock_details[nk] = make_detail(
                            nk, stk_nm, 0, "3", 0, 0.0,
                            prev_close=0, trade_amount=0, sector=sec
                        )
                        es._pending_stock_details[nk]["status"] = "active"
                        es._pending_stock_details[nk]["reason"] = "5일봉 수동 다운로드"
                        if hasattr(es, "_radar_cnsr_order") and nk not in es._radar_cnsr_order:
                            es._radar_cnsr_order.append(nk)

                    # 메모리 캐시 및 배열 갱신
                    es._amts_5d_arrays[nk] = amounts_5d
                    es._highs_5d_arrays[nk] = highs_5d

                    avg5d = int(sum(amounts_5d) / len(amounts_5d))
                    high5d = max(highs_5d)

                    if avg5d > 0:
                        if nk in _master_stocks_cache:
                            _master_stocks_cache[nk]["avg_5d_trade_amount"] = avg5d
                    if high5d > 0:
                        if nk in _master_stocks_cache:
                            _master_stocks_cache[nk]["high_5d_price"] = high5d

                    fetched += 1
                    _log.info("[5일봉 다운로드] [%d/%d] 종목 %s 다운로드 완료 (고가 5일최대=%d, 5일평균거래대금=%d)", 
                              idx + 1, total, base_cd, high5d, avg5d)
                else:
                    failed += 1
                    _log.warning("[5일봉 다운로드] [%d/%d] 종목 %s 데이터 비어있음", idx + 1, total, base_cd)

            except Exception as e:
                failed += 1
                _log.warning("[5일봉 다운로드] [%d/%d] 종목 %s 예외 발생: %s", idx + 1, total, base_cd, e)

            # 진행률 브로드캐스트
            if (idx + 1) % 10 == 0 or idx + 1 == total:
                pct = int((idx + 1) / total * 100)
                remaining = total - (idx + 1)
                eta = remaining * 1.0
                _broadcast_confirmed_progress(
                    idx + 1, total,
                    message=f"5단계: 개별 5일봉 데이터 다운로드 중 ({idx + 1:,}/{total:,}, {pct}%)",
                    eta_sec=eta,
                    step=5
                )

            # Rate limiting
            await asyncio.sleep(1.0)

        success_rate = (fetched / total * 100) if total else 0
        _log.info("[수동 5일봉] Step 5 완료 — 성공 %d종목, 실패 %d종목 (%.1f%% 성공)", fetched, failed, success_rate)

        # 디스크 캐시 저장
        cached = await _save_confirmed_cache(es)

        _broadcast_confirmed_progress(total, total, message=f"✅ 5일봉 다운로드 완료 ({fetched:,}/{total:,})", step=5)

        # 후처리 및 업종순위 재계산
        await _run_post_confirmed_pipeline(es)

        try:
            from backend.app.services.engine_service import recompute_sector_summary_now
            from backend.app.services.engine_account_notify import (
                notify_desktop_sector_scores,
                notify_desktop_sector_stocks_refresh,
            )
            recompute_sector_summary_now()
            notify_desktop_sector_scores(force=True)
            notify_desktop_sector_stocks_refresh()
            _log.info("[수동 5일봉] 업종순위 재계산 + 실시간 화면전송 완료")
        except Exception as _ws_err:
            _log.warning("[수동 5일봉] 업종순위 재계산 실패: %s", _ws_err, exc_info=True)

        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        es._confirmed_refresh_running = False
        es._confirmed_refresh_message = ""





