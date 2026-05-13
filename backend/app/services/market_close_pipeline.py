# -*- coding: utf-8 -*-
"""
장마감 후 데이터 캐시 파이프라인 — 핵심 로직.

KRX/NXT 장마감 후 WS 구독 해지 → REST 확정 데이터 조회 → 캐시 저장.
daily_time_scheduler.py 타이머 콜백에서 호출된다.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

from app.services.engine_symbol_utils import (
    _base_stk_cd,
    _format_kiwoom_reg_stk_cd,
    is_nxt_enabled,
    get_ws_subscribe_code,
)
from app.services.engine_ws_reg import build_0b_remove_payloads

_log = logging.getLogger("engine")
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
        from app.web.ws_manager import ws_manager
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
        if _loop is not None:
            ws_manager.broadcast_threadsafe("confirmed-progress", payload, _loop)
        else:
            ws_manager.broadcast("confirmed-progress", payload)
    except Exception as e:
        _log.warning("[데이터] 브로드캐스트 실패: %s", e, exc_info=True)

_log = logging.getLogger(__name__)


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
    ltp: dict = getattr(es, "_latest_trade_prices", {})
    lta: dict = getattr(es, "_latest_trade_amounts", {})
    lst: dict = getattr(es, "_latest_strength", {})

    updated = 0

    for raw_cd, detail in confirmed.items():
        nk = _format_kiwoom_reg_stk_cd(raw_cd)
        if not nk:
            continue

        entry = pending.get(nk)
        if entry is None:
            # 엔트리 없으면 새로 생성
            from app.services.engine_strategy_core import make_detail
            px = int(detail.get("cur_price") or 0)
            stk_nm = _nm.get(_base_stk_cd(raw_cd), nk)
            entry = make_detail(
                nk, stk_nm, px,
                str(detail.get("sign") or "3"),
                int(detail.get("change") or 0),
                float(detail.get("change_rate") or 0.0),
                prev_close=int(detail.get("prev_close") or 0),
                trade_amount=int(detail.get("trade_amount") or 0),
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

        updated += 1

    _log.info("[타이머] 확정 데이터 메모리 반영 -- %d종목", updated)
    return updated


# ---------------------------------------------------------------------------
# 확정 후 v2 캐시 롤링 파이프라인 (daily_time_scheduler.py에서 이동)
# ---------------------------------------------------------------------------

async def _run_post_confirmed_pipeline(es: ModuleType) -> None:
    """확정 조회 완료 후 v2 캐시 롤링 갱신 + 최종 스냅샷 캐시 덮어쓰기.

    (1) _pending_stock_details에서 trade_amount + high_price 수집
    (2) rolling_update_v2_from_trade_amounts()로 v2 캐시 + 고가 배열 롤링 갱신
    (3) _high_5d_cache 갱신 + 저장
    (4) _save_confirmed_cache(es)로 최종 스냅샷 캐시 덮어쓰기
    """
    try:
        # (1) trade_amount + high_price 수집 — 키를 6자리 정규화 형식으로 변환
        # 적격종목만 수집 (부적격 종목이 5일평균 캐시에 포함되지 않도록)
        import app.core.industry_map as _ind_mod
        elig = _ind_mod._eligible_stock_codes  # {코드: ""} — 빈 dict이면 필터 미적용
        pending = getattr(es, "_pending_stock_details", {})
        trade_amounts: dict[str, int] = {}
        high_prices: dict[str, int] = {}
        for cd, detail in pending.items():
            normalized = _base_stk_cd(cd)
            if elig and normalized not in elig:
                continue
            amt = int(detail.get("trade_amount") or 0)
            if amt > 0:
                trade_amounts[normalized] = amt
            hp = int(detail.get("high_price") or 0)
            if hp > 0:
                high_prices[normalized] = hp

        # (2) v2 캐시 + 고가 배열 롤링 갱신
        from app.core.avg_amt_cache import (
            load_avg_amt_cache_v2,
            save_avg_amt_cache_v2,
            rolling_update_v2_from_trade_amounts,
            avg_from_v2,
            _kst_today_yyyymmdd,
        )
        existing_v2_result = load_avg_amt_cache_v2()
        if existing_v2_result:
            existing_v2, existing_high_arr = existing_v2_result
        else:
            existing_v2, existing_high_arr = None, None
        eligible_codes = set(elig.keys()) if elig else None
        updated_v2, updated_high_arr = rolling_update_v2_from_trade_amounts(
            existing_v2, trade_amounts,
            high_prices=high_prices,
            high_5d_arr=existing_high_arr,
            eligible_set=eligible_codes,
        )

        # (3) _high_5d_cache 갱신 + 저장
        es._high_5d_cache = {code: max(arr) for code, arr in updated_high_arr.items() if arr}
        date = _kst_today_yyyymmdd()
        save_avg_amt_cache_v2(
            updated_v2, date,
            high_5d=es._high_5d_cache,
            high_5d_arr=updated_high_arr,
        )
        # 엔진 메모리 갱신
        avg_map = avg_from_v2(updated_v2)
        es._update_avg_amt_5d(avg_map)

        # (4) 최종 스냅샷 캐시 덮어쓰기
        await _save_confirmed_cache(es)

        _log.info("[타이머] post-confirmed 파이프라인 완료 — trade_amounts=%d종목, high_prices=%d종목", len(trade_amounts), len(high_prices))
    except Exception as exc:
        _log.warning("[타이머] post-confirmed 파이프라인 오류: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# 확정 데이터 디스크 캐시 저장
# ---------------------------------------------------------------------------

async def _save_confirmed_cache(es: ModuleType) -> bool:
    """현재 메모리 데이터를 save_snapshot_cache()로 디스크 저장.

    저장 직전에 종목명 캐시를 참조하여 name 필드를 보정한다.

    Args:
        es: engine_service 모듈 참조

    Returns:
        저장 성공 여부.
    """
    from app.core.sector_stock_cache import save_snapshot_cache, load_stock_name_cache

    pending: dict = getattr(es, "_pending_stock_details", {})
    if not pending:
        _log.warning("[타이머] _pending_stock_details 비어있음 — 데이터 저장 생략")
        return False

    # 적격종목 필터 — eligible 캐시 기준으로 부적격 종목 제외
    # 모듈 직접 참조: Step 4에서 _eligible_stock_codes가 재할당되어도 최신값을 사용
    import app.core.industry_map as _ind_mod
    elig = _ind_mod._eligible_stock_codes or {}

    # 종목명 캐시로 name 필드 보정
    name_map = load_stock_name_cache() or {}
    if name_map:
        for cd, detail in pending.items():
            nm = name_map.get(cd)
            if nm and detail.get("name") in (cd, "", None):
                detail["name"] = nm

    rows = [
        (cd, dict(detail))
        for cd, detail in pending.items()
        if detail.get("status") in ("active", "exited")
        and (not elig or cd in elig)
    ]
    if not rows:
        _log.warning("[타이머] 저장 가능한 종목 없음 — 저장데이터 저장 생략")
        return False

    try:
        await asyncio.to_thread(save_snapshot_cache, rows)
        _log.info("[타이머] 확정 데이터 저장데이터 저장 완료 — %d종목", len(rows))
        return True
    except Exception as exc:
        _log.warning("[타이머] 확정 데이터 저장데이터 저장 실패: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 통합 확정 데이터 조회 (20:30)
# ---------------------------------------------------------------------------

async def fetch_unified_confirmed_data(es: ModuleType) -> dict:
    """20:30 통합 확정 조회 — 전종목 대상 ka10099 + ka10086 + 후처리.

    1단계 ka10099: 전종목 목록 갱신 (레이아웃 캐시 + 종목명 캐시 + 신규 종목 섹터 매핑)
    2단계 ka10086: 전종목 확정 시세 순차 호출 (interval_sec=0.3) → 메모리 + 디스크 갱신
       - 이어받기 지원: 20종목마다 진행 저장, 재기동 시 중단 지점부터 계속
    3단계 후처리: v2 캐시 롤링 + 5일 평균 재계산 (업종순위 재계산 안 함)

    Args:
        es: engine_service 모듈 참조

    Returns:
        {"fetched": int, "failed": int, "cached": bool}
    """
    from app.core.broker_factory import get_router
    from app.core.sector_stock_cache import (
        save_layout_cache,
        save_stock_name_cache,
        load_progress_cache,
        clear_progress_cache,
    )
    from app.core.trading_calendar import current_trading_date_str, kst_today_str

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
        from app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        getattr(es, "_avg_amt_5d", {}).clear()
        getattr(es, "_high_5d_cache", {}).clear()
        import app.core.industry_map as _ind_mod
        _ind_mod._eligible_stock_codes.clear()
        _log.info("[타이머] 메모리 전체 초기화 완료 — 새 데이터로 교체 시작")
    
        # 스케줄러 토글 OFF 시 전체 갱신 스킵
        if not _settings.get("scheduler_market_close_on", True):
            _log.info("[타이머] scheduler_market_close_on=OFF — 전체 갱신 생략")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False, "skipped": True}
    
        _sector = get_router(_settings).sector
    
        # ── Pipeline events ──────────────────────────────────────────────────
        data_fetched_event = asyncio.Event()
        parsing_done_event = asyncio.Event()
        filtering_done_event = asyncio.Event()
        save_done_event = asyncio.Event()
    
        # ── Step 1: API 호출 (raw data 수집) ─────────────────────────────────
        _log.info("[타이머] Step 1 시작 — ka10099 전종목 리스트 다운로드 (코스피+코스닥)")
        _broadcast_confirmed_progress(0, 0, message="전종목 목록 갱신 중...", step=1)
        try:
            from app.core.broker_providers import UnifiedStockRecord
            records: list[UnifiedStockRecord] = await asyncio.to_thread(
                _sector.fetch_unified_stock_data
            )
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
        _broadcast_confirmed_progress(0, 0, message="적격 종목 필터링 중...", step=2)
        try:
            await asyncio.wait_for(data_fetched_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            _log.error("[타이머] Step 2 대기 타임아웃 — data_fetched_event 미수신, 파이프라인 중단")
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        try:
            from app.core.stock_filter import is_excluded
            confirmed_codes: set[str] = set()
            filter_reasons: dict[str, int] = {}
            for r in records:
                excluded, reason = is_excluded(r.raw_item, r.code)
                if excluded:
                    filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                else:
                    confirmed_codes.add(r.code)
    
            excluded_count = len(records) - len(confirmed_codes)
            _log.info(
                "[타이머] Step 2 완료 — 적격 종목 필터링: 전체 %d종목 → 적격 %d종목 (제외 %d종목, %.1f%%)",
                len(records), len(confirmed_codes), excluded_count,
                (excluded_count / len(records) * 100) if records else 0
            )
            if filter_reasons:
                top_reasons = sorted(filter_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
                _log.info("[타이머] 주요 부적격 사유 (Top 5): %s", dict(top_reasons))
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
            await asyncio.to_thread(save_stock_name_cache, name_map)
    
            import app.core.industry_map as _ind_mod
            eligible_map: dict[str, str] = {cd: "" for cd in confirmed_codes}
            _ind_mod.save_eligible_stocks_cache(eligible_map)
            _ind_mod._eligible_stock_codes = eligible_map
    
            from app.core.sector_stock_cache import save_market_map_cache
            # NXT 정보는 서버 응답(nxtEnable)에서 파싱한 원본값 사용 [출처: kiwoom_rest.py:621]
            nxt_map = {r.code: r.nxt_enable for r in records if r.code in confirmed_codes}
            save_market_map_cache(market_map, nxt_map)
    
            all_codes = list(confirmed_codes)
            _update_layout_cache(es, all_codes, name_map)
            save_done_event.set()
            _log.info("[타이머] Step 4 완료 — 3개 저장데이터 저장 (%d종목)", len(confirmed_codes))
        except Exception as exc:
            _log.warning("[타이머] Step 4 저장데이터 저장 실패: %s — save_done_event 미발행", exc, exc_info=True)
            # save_done_event 미발행 → 후속 단계 진행 불가
            es._confirmed_refresh_running = False
            es._confirmed_refresh_message = ""
            return {"fetched": 0, "failed": 0, "cached": False}
    
        # ── 2단계 ka10086: 전종목 확정 시세 순차 호출 (이어받기 지원) ───────
        _log.info("[타이머] Step 5 시작 — ka10086 전종목 확정 시세 다운로드 (%d종목)", len(all_codes))
        qry_dt = kst_today_str()  # 당일 확정 시세 조회: 20:00 이후에도 오늘 날짜 사용 (current_trading_date_str은 다음 거래일 반환)
        total = len(all_codes)
        _main_loop = asyncio.get_running_loop()
    
        # 사용자 설정의 ws_subscribe_start 시간 확인 (진행 파일 유효 기간용)
        _settings = getattr(es, "_settings_cache", {}) or {}
        ws_subscribe_start = str(_settings.get("ws_subscribe_start") or "07:50")
    
        # 이어받기: 진행 파일 로드 (다음 거래일 ws_subscribe_start까지 유효)
        resume_codes = load_progress_cache(qry_dt, all_codes, ws_subscribe_start)
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
            eta = remaining * 0.3
            _pct = int(cur / total * 100) if total > 0 else 0
            _broadcast_confirmed_progress(
                cur, total,
                message=f"전종목 확정시세 데이터 다운로드 중 ({cur:,}/{total:,}, {_pct}%)",
                eta_sec=eta,
                step=5,
                _loop=_main_loop,
            )
    
        try:
            def _sync_ka10086():
                return _sector.fetch_sector_all_daily(
                    all_codes, qry_dt, interval_sec=0.3, on_progress=_on_progress,
                    resume_codes=resume_codes,  # 이어받기 지원
                )
    
            confirmed = await asyncio.get_running_loop().run_in_executor(
                _CONFIRMED_FETCH_EXECUTOR,
                _sync_ka10086,
            )
        except Exception as exc:
            _log.warning("[타이머] ka10086 전종목 조회 실패: %s", exc, exc_info=True)
            confirmed = {}
    
        fetched = len(confirmed)
        failed = total - fetched
        success_rate = (fetched / total * 100) if total else 0
        _log.info(
            "[타이머] Step 5 완료 — ka10086 확정 시세 다운로드: 성공 %d종목, 실패 %d종목 (%.1f%% 성공)",
            fetched, failed, success_rate
        )
        # 실패율이 1% 이상이면 경고 로그 (디버깅용)
        if failed > 0 and success_rate < 99.0:
            _log.warning(
                "[타이머] ka10086 실패율 높음: %d/%d종목 (%.1f%%) — kiwoom_sector_rest.py 로그에서 실패 원인 확인",
                failed, total, 100 - success_rate
            )
    
        # 메모리 반영
        if confirmed:
            await _apply_confirmed_to_memory(es, confirmed, {}, name_map=name_map)
    
        # 디스크 캐시 저장
        cached = await _save_confirmed_cache(es)
    
        # 완료 후 진행 파일 삭제
        if cached:
            clear_progress_cache()
    
        _broadcast_confirmed_progress(total, total, message=f"전종목 확정시세 데이터 다운로드 완료 ({fetched:,}/{total:,})", step=5)
    
        # ── 3단계 후처리: v2 캐시 롤링 (업종순위 재계산 안 함) ────────────────
        _broadcast_confirmed_progress(total, total, message="5일 거래대금 계산 중...", step=5)
        await _run_post_confirmed_pipeline(es)
    
        # ── Step 6: 완전한 매핑 단계 (적격종목 × 시세 데이터 매핑) ────────────
        if cached:
            import app.core.industry_map as _ind_mod_step6
            final_eligible = set(_ind_mod_step6._eligible_stock_codes.keys())
            if not final_eligible:
                _log.warning("[타이머] Step 6 — 적격종목 비어있음, 메모리 교체 생략")
            else:
                # Build mapped_pending: 적격종목 중 entry 데이터가 있는 것만 수집
                mapped_pending: dict = {}
                for cd in final_eligible:
                    entry = es._pending_stock_details.get(cd)
                    if entry is not None:
                        mapped_pending[cd] = entry
    
                # Filter _avg_amt_5d and _high_5d_cache to eligible-only
                new_avg = {cd: v for cd, v in es._avg_amt_5d.items() if cd in final_eligible}
                new_high = {cd: v for cd, v in es._high_5d_cache.items() if cd in final_eligible}
    
                # ── Step 7: 원자적 메모리 교체 (_shared_lock 내부) ────────────
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
                    "[타이머] Step 7 원자적 메모리 교체 완료 — pending=%d종목, avg=%d, high=%d",
                    len(mapped_pending), len(new_avg), len(new_high),
                )
        else:
            _log.warning("[타이머] cached=False — 메모리 교체 생략 (기존 상태 유지)")
    
        # ── 4단계: 업종순위 재계산 + WS 브로드캐스트 (화면 자동 갱신) ────────
        try:
            from app.services.engine_service import recompute_sector_summary_now
            from app.services.engine_account_notify import (
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
        _log.info(
            "[타이머] === 전체 완료 === 총 %d단계 | ka10099: %d종목 | 적격: %d종목 | ka10086: %d/%d종목 | 저장데이터: %s",
            7, len(records), len(confirmed_codes), fetched, total, "저장됨" if cached else "실패"
        )
        return {"fetched": fetched, "failed": failed, "cached": cached}
    finally:
        es._confirmed_refresh_running = False
        es._confirmed_refresh_message = ""


# ---------------------------------------------------------------------------
# 통합 확정 조회 헬퍼
# ---------------------------------------------------------------------------

def _update_layout_cache(
    es: ModuleType,
    all_codes: list[str],
    name_map: dict[str, str],
) -> None:
    """confirmed_codes 기준으로 레이아웃 캐시를 완전 재구성.

    - 부적격이 된 종목은 레이아웃에서 제거된다.
    - sector_custom.json의 최신 업종 매핑이 전체 종목에 적용된다.
    - 섹터 헤더가 없는 종목("업종명없음")도 레이아웃에 포함된다.
    """
    from app.core.sector_mapping import get_merged_sector
    from app.core.sector_stock_cache import save_layout_cache

    # 전체 종목을 섹터별로 그룹핑 (sector_custom.json 최신 매핑 적용)
    sector_groups: dict[str, list[str]] = {}
    for cd in all_codes:
        sec = get_merged_sector(cd) or "업종명없음"
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
    from app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache(new_layout)
    save_layout_cache(new_layout)
    _log.info(
        "[타이머] 레이아웃 저장데이터 완전 재구성 — %d종목, %d업종",
        len(all_codes), len(final_sector_order),
    )




