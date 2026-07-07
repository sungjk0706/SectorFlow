# -*- coding: utf-8 -*-
"""
섹터 재계산 — 이벤트 기반 증분 갱신.

개별 REAL 체결마다 태스크를 만들지 않는다.
recompute_sector_for_code(code)는 이벤트 발생 시 호출되며,
연속 호출은 중복 제거되어 1회만 재계산한다.
구독 갱신은 buy_targets 변경 시 직접 호출된다.
"""
from __future__ import annotations
import asyncio
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import state
logger = get_logger("engine")

_dirty_codes: set[str] = set()

# 0D 구독 해지 지연 관리 (guard_pass 경계값 진동 방지)
_PENDING_UNREG_CODES: set[str] = set()  # 해지 대기 중인 종목 코드
_PENDING_UNREG_TIMER: asyncio.TimerHandle | None = None  # 해지 타이머
_UNREG_DELAY_SEC: float = 30.0  # 해지 지연 시간 (30초)


def is_engine_running_internal() -> bool:
    from backend.app.services.engine_state import state
    return state.running


def request_sector_recompute(code: str | None = None) -> None:
    """종목을 dirty로 마킹. 실제 재계산은 배치 루프에서 단일 호출.

    SSOT: _dirty_codes는 이 모듈에서만 관리.
    create_task 분리 금지 — 재계산은 호출자가 await로 직접 실행.
    """
    if code:
        _dirty_codes.add(code)
    else:
        _dirty_codes.add("__ALL__")


def has_dirty_sectors() -> bool:
    return len(_dirty_codes) > 0


def clear_dirty_sectors() -> None:
    _dirty_codes.clear()


def extract_guard_pass_codes(buy_targets) -> set[str]:
    """buy_targets에서 guard_pass=True인 종목코드 집합 추출."""
    if not buy_targets:
        return set()
    return {bt.stock.code for bt in buy_targets if bt.stock.guard_pass}


def are_buy_targets_changed(prev_targets, new_targets) -> bool:
    """buy_targets의 guard_pass=True 종목코드 집합이 변경되었는지 비교."""
    prev_codes = extract_guard_pass_codes(prev_targets)
    new_codes = extract_guard_pass_codes(new_targets)
    return prev_codes != new_codes


async def _flush_sector_recompute_impl() -> None:
    """dirty 종목의 섹터만 증분 재계산. 캐시 없으면 전체 재계산.

    비동기 함수. 순수 계산 + 알림 + 구독 갱신만 수행.
    """
    global _dirty_codes

    if not _dirty_codes:
        return

    codes_snapshot = set(_dirty_codes)
    _dirty_codes.clear()

    try:
        from backend.app.services.sector_data_provider import get_sector_summary_inputs
        from backend.app.domain.buy_filter import build_buy_targets_from_settings
        from backend.app.domain.sector_calculator import compute_sector_scores
        from backend.app.domain.sector_score import calculate_weighted_scores
        from backend.app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_buy_targets_update,
        )
        from backend.app.core import sector_mapping

        existing = state.sector_summary_cache

        # 캐시 없음(콜드 스타트) → 전체 재계산 1회 (이후 증분 모드 전환)
        if not existing:
            await _full_recompute(codes_snapshot)
            return

        # __ALL__ 플래그 + 캐시 존재 → 전체 종목(all_codes)를 dirty로 취급하여 증분 경로 사용
        # _master_stocks_cache의 "_subscribed" 대신 all_codes 사용: 업종 요약정보는 실시간 구독 상태와 무관하게 전체 종목 기준으로 계산
        if "__ALL__" in codes_snapshot:
            inputs = await get_sector_summary_inputs()
            codes_snapshot = set(inputs["all_codes"])

        # ── 증분 갱신 ──
        # 1. dirty 종목 → 해당 섹터 추출 (배치 조회)
        codes_list = list(codes_snapshot)
        sectors_map = await sector_mapping.get_merged_sectors_batch(codes_list)
        dirty_sectors: set[str] = set()
        for cd in codes_list:
            sec = sectors_map.get(cd, "미분류")
            if sec:
                dirty_sectors.add(sec)

        if not dirty_sectors:
            return

        # 2. 해당 섹터의 종목만 재계산
        inputs = await get_sector_summary_inputs()
        all_codes = inputs["all_codes"]
        min_avg_amt_eok = float(state.integrated_system_settings_cache["sector_min_trade_amt"])
        trim_trade = float(state.integrated_system_settings_cache["sector_trim_trade_amt_pct"])
        trim_change = float(state.integrated_system_settings_cache["sector_trim_change_rate_pct"])
        sector_weights = state.integrated_system_settings_cache["sector_weights"]

        # dirty 섹터에 속한 종목코드만 필터 (배치 조회)
        all_sectors_map = await sector_mapping.get_merged_sectors_batch(all_codes)
        dirty_codes_for_calc = [
            cd for cd in all_codes
            if all_sectors_map.get(cd, "미분류") in dirty_sectors
        ]

        if dirty_codes_for_calc:
            new_sector_scores = await compute_sector_scores(
                dirty_codes_for_calc,
                trade_prices=inputs["trade_prices"],
                trade_amounts=inputs["trade_amounts"],
                avg_amt_5d=inputs["avg_amt_5d"],
                min_avg_amt_eok=min_avg_amt_eok,
                sector_weights=sector_weights,
                trim_trade_amt_pct=trim_trade,
                trim_change_rate_pct=trim_change,
            )
            new_map = {sc.sector: sc for sc in new_sector_scores}
        else:
            new_map = {}

        # 3. 기존 캐시의 섹터 목록에서 dirty 섹터만 교체
        merged: list = []
        for sc in existing.sectors:
            if sc.sector in dirty_sectors:
                replacement = new_map.pop(sc.sector, None)
                if replacement:
                    merged.append(replacement)
                # else: 섹터가 사라진 경우 (종목 전부 필터됨) → 제외
            else:
                merged.append(sc)
        # 새로 생긴 섹터 추가 (기존에 없던 섹터)
        for sc in new_map.values():
            merged.append(sc)

        # 4. 전체 정규화 + 순위 재정렬
        calculate_weighted_scores(merged, weights=sector_weights)

        # 5. 업종 컷오프: 상승비율 미만 업종은 순위 없음(rank=0)
        min_rise_ratio = float(state.integrated_system_settings_cache["sector_min_rise_ratio_pct"]) / 100.0
        if min_rise_ratio > 0:
            pass_sectors = [sc for sc in merged if sc.rise_ratio >= min_rise_ratio]
            fail_sectors = [sc for sc in merged if sc.rise_ratio < min_rise_ratio]
            # pass 그룹에만 순위 부여 (1부터)
            for i, sc in enumerate(pass_sectors):
                sc.rank = i + 1
            # fail 그룹은 순위 없음 (0)
            for sc in fail_sectors:
                sc.rank = 0
            # 표시 순서는 프론트엔드에서 결정 (백엔드는 final_score 기준 정렬 유지)

        # 6. 매수 타겟 큐
        # buy_targets 변경 감지를 위해 이전 값 저장
        prev_targets = existing.buy_targets if hasattr(existing, 'buy_targets') else None

        from backend.app.services.engine_symbol_utils import _base_stk_cd
        _held = {_base_stk_cd(cd) for cd in state.checked_stocks}
        _bought_today: set[str] = set()
        if state.auto_trade is not None:
            _bought_today = set(state.auto_trade._bought_today.keys())
        ss = build_buy_targets_from_settings(
            merged,
            state.integrated_system_settings_cache,
            held_codes=_held,
            bought_today_codes=_bought_today,
        )

        # 참조 교체 방식으로 캐시 갱신 (R5.6)
        state.sector_summary_cache = ss

        # 업종 점수 delta 전송 (내부에서 변경분만 비교)
        await notify_desktop_sector_scores()
        await notify_buy_targets_update()

        # buy_targets 변경 시 구독 갱신 + 매수 시도 (이벤트 기반)
        if are_buy_targets_changed(prev_targets, ss.buy_targets):
            sync_dynamic_subscriptions(ss.buy_targets)
            from backend.app.services.buy_order_executor import evaluate_buy_candidates, _cash_insufficient
            if not _cash_insufficient:
                await evaluate_buy_candidates()

        # 업종 요약정보 생성 완료 이벤트 설정
        state.sector_summary_ready_event.set()

    except Exception as e:
        logger.warning("[섹터재계산] 증분 재계산 오류: %s", e, exc_info=True)


async def _full_recompute(codes_snapshot: set[str] | None = None) -> None:
    """전체 재계산 (캐시 없을 때 — 콜드 스타트).

    비동기 함수. 순수 계산 + 알림 + 이벤트 발행만 수행.
    """
    from backend.app.services.sector_data_provider import get_sector_summary_inputs
    from backend.app.domain.sector_calculator import compute_full_sector_summary
    from backend.app.domain.buy_filter import build_buy_targets_from_settings
    from backend.app.services.engine_account_notify import (
        notify_desktop_sector_scores,
        notify_buy_targets_update,
    )
    # buy_targets 변경 감지를 위해 이전 값 저장
    _prev_cache = state.sector_summary_cache
    prev_targets = _prev_cache.buy_targets if _prev_cache and hasattr(_prev_cache, 'buy_targets') else None

    trim_trade = float(state.integrated_system_settings_cache["sector_trim_trade_amt_pct"])
    trim_change = float(state.integrated_system_settings_cache["sector_trim_change_rate_pct"])

    inputs = await get_sector_summary_inputs()
    sector_summary = await compute_full_sector_summary(
        **inputs,
        min_rise_ratio=float(state.integrated_system_settings_cache["sector_min_rise_ratio_pct"]) / 100.0,
        min_avg_amt_eok=float(state.integrated_system_settings_cache["sector_min_trade_amt"]),
        sector_weights=state.integrated_system_settings_cache["sector_weights"],
        trim_trade_amt_pct=trim_trade,
        trim_change_rate_pct=trim_change,
    )
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    _held = {_base_stk_cd(cd) for cd in state.checked_stocks}
    _bought_today: set[str] = set()
    if state.auto_trade is not None:
        _bought_today = set(state.auto_trade._bought_today.keys())
    ss = build_buy_targets_from_settings(
        sector_summary.sectors,
        state.integrated_system_settings_cache,
        held_codes=_held,
        bought_today_codes=_bought_today,
    )

    # 참조 교체 방식으로 캐시 갱신 (R5.6)
    state.sector_summary_cache = ss

    # 업종 점수 delta 전송 (내부에서 변경분만 비교)
    await notify_desktop_sector_scores()
    await notify_buy_targets_update()

    # buy_targets 변경 시 구독 갱신 + 매수 시도 (이벤트 기반)
    if are_buy_targets_changed(prev_targets, ss.buy_targets):
        sync_dynamic_subscriptions(ss.buy_targets)
        from backend.app.services.buy_order_executor import evaluate_buy_candidates
        await evaluate_buy_candidates()

    # 업종 요약정보 생성 완료 이벤트 설정
    state.sector_summary_ready_event.set()


# ── 0D 구독 delta 갱신 ────────────────────────────────────────────────────


def sync_dynamic_subscriptions(new_buy_targets) -> None:
    """buy_targets 변경 시 동적 구독 delta 갱신 (해지 지연 적용).

    신규 구독은 즉시, 해지는 30초 지연 후 적용.
    guard_pass 경계값 진동으로 인한 빈번한 REG/REMOVE 반복을 방지한다.
    특정 증권사에 종속되지 않도록 DYNAMIC_REG 이벤트를 제어 큐로 발행한다.
    """
    global _PENDING_UNREG_CODES, _PENDING_UNREG_TIMER

    from backend.app.services.engine_state import state
    from backend.app.services.core_queues import get_control_queue
    import time

    # WS 미연결 → 스킵
    ws = state.connector_manager or state.active_connector
    if not ws or not ws.is_connected() or not state.login_ok:
        return

    new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}

    all_stocks = state.master_stocks_cache
    prev_codes = {cd for cd, entry in all_stocks.items() if entry.get("_subscribed_dynamic", False)}

    # 신규 구독: 즉시 적용
    to_reg = new_codes - prev_codes
    if to_reg:
        logger.info("[동적구독] 신규 등록 %d종목", len(to_reg))
        payload = {
            "type": "DYNAMIC_REG",
            "payload": {
                "codes": sorted(to_reg),
                "types": ["0D", "PGM"]
            }
        }
        try:
            get_control_queue().put_nowait((1, time.time(), payload))
        except Exception as e:
            logger.warning("[동적구독] 신규 등록 이벤트 큐 발행 실패: %s", e)
        prev_codes = prev_codes | to_reg  # 임시로 추가

    # 해지 대상: 지연 적용
    new_unreg_candidates = prev_codes - new_codes
    if new_unreg_candidates:
        _PENDING_UNREG_CODES.update(new_unreg_candidates)

    # 복귀한 종목은 해지 취소
    returned_codes = _PENDING_UNREG_CODES & new_codes
    if returned_codes:
        _PENDING_UNREG_CODES -= returned_codes

    # 해지 타이머 설정/재설정
    if _PENDING_UNREG_CODES:
        if _PENDING_UNREG_TIMER is not None:
            _PENDING_UNREG_TIMER.cancel()
        try:
            loop = asyncio.get_running_loop()
            _PENDING_UNREG_TIMER = loop.call_later(
                _UNREG_DELAY_SEC,
                apply_delayed_unsubscription
            )
        except RuntimeError:
            pass

    # state.master_stocks_cache에 "_subscribed_dynamic" 설정
    for cd in prev_codes:
        if cd in state.master_stocks_cache:
            state.master_stocks_cache[cd]["_subscribed_dynamic"] = True


def apply_delayed_unsubscription() -> None:
    """30초 후 실제 해지 적용."""
    global _PENDING_UNREG_CODES, _PENDING_UNREG_TIMER

    from backend.app.services.core_queues import get_control_queue
    import time

    all_stocks = state.master_stocks_cache
    current_codes = {cd for cd, entry in all_stocks.items() if entry.get("_subscribed_dynamic", False)}
    to_unreg = _PENDING_UNREG_CODES & current_codes  # 아직 구독 중인 것만

    if to_unreg:
        logger.info("[동적구독] 지연 해지 적용 %d종목", len(to_unreg))
        payload = {
            "type": "DYNAMIC_UNREG",
            "payload": {
                "codes": sorted(to_unreg),
                "types": ["0D", "PGM"]
            }
        }
        try:
            get_control_queue().put_nowait((1, time.time(), payload))
        except Exception as e:
            logger.warning("[동적구독] 지연 해지 이벤트 큐 발행 실패: %s", e)
        current_codes -= to_unreg

    _PENDING_UNREG_CODES.clear()
    _PENDING_UNREG_TIMER = None
    # state.master_stocks_cache에서 "_subscribed_dynamic" 및 동적 데이터 완전 제거 (데이터 왜곡 차단)
    for cd in to_unreg:
        if cd in state.master_stocks_cache:
            entry = state.master_stocks_cache[cd]
            entry.pop("_subscribed_dynamic", None)
            entry.pop("order_ratio", None)
            entry.pop("program_net_buy", None)



# ── 호환용 ────────────────────────────────────────────────────────────────

def flush_pending_recompute() -> None:
    """하위 호환성: recompute_sector_for_code(None)과 동일."""
    request_sector_recompute(None)

def cancel_sector_recompute() -> None:
    clear_dirty_sectors()

def cancel_recompute_timer() -> None:
    clear_dirty_sectors()
