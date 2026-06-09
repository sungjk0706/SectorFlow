from __future__ import annotations
# -*- coding: utf-8 -*-
"""
섹터 재계산 — 이벤트 기반 증분 갱신.

개별 REAL 체결마다 태스크를 만들지 않는다.
recompute_sector_for_code(code)는 이벤트 발생 시 호출되며,
연속 호출은 coalesce되어 1회만 재계산한다.
구독 갱신은 buy_targets 변경 시 직접 호출된다.
"""

import asyncio
from backend.app.core.logger import get_logger
from backend.app.services.engine_radar import get_high_price_5d_cache, get_program_net_buy_cache
from backend.app.services.sector_data_provider import SectorDataProvider

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
    """이벤트 발생 시 즉시 실행.

    실시간 데이터 처리 아키텍처에 부합: 코알레싱 제거로 지연 없이 즉시 실행.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.debug("[업종순위] recompute_sector_for_code 호출: code=%s", code)

    # 엔진 실행 상태 확인 제거: 업종 요약정보는 엔진 실행 상태와 무관하게 생성 (테스트모드 포함)

    if code:
        _dirty_codes.add(code)
    else:
        _dirty_codes.add("__ALL__")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 이벤트 루프 없음(테스트 등) — 즉시 실행 폴백
        asyncio.run(_flush_sector_recompute_impl())
        return

    # 즉시 실행 (코알레싱 제거)
    loop.create_task(_flush_sector_recompute_impl())


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

    # _is_engine_running() 확인 제거: 업종 요약정보는 엔진 실행 상태와 무관하게 생성 (테스트모드 포함)
    if not _dirty_codes:
        return

    codes_snapshot = set(_dirty_codes)
    _dirty_codes.clear()

    try:
        import backend.app.services.engine_service as _es
        from backend.app.services.sector_data_provider import get_sector_summary_inputs
        from backend.app.domain.buy_filter import create_buy_targets
        from backend.app.domain.sector_calculator import compute_sector_scores
        from backend.app.domain.sector_score import calculate_weighted_scores
        from backend.app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_buy_targets_update,
        )
        from backend.app.core import sector_mapping

        existing = _es._sector_summary_cache

        # 캐시 없음(콜드 스타트) → 전체 재계산 1회 (이후 증분 모드 전환)
        if not existing:
            await _full_recompute(_es, codes_snapshot)
            return

        # 스켈레톤 캐시 모드 감지 (is_skeleton_mode 플래그 기반)
        if existing.is_skeleton_mode:
            # 스켈레톤 캐시인 경우 실시간 틱 기반 증분 연산 수행
            await _skeleton_incremental_update(_es, codes_snapshot)
            return

        # __ALL__ 플래그 + 캐시 존재 → 전체 종목(all_codes)를 dirty로 취급하여 증분 경로 사용
        # _master_stocks_cache의 "_subscribed" 대신 all_codes 사용: 업종 요약정보는 실시간 구독 상태와 무관하게 전체 종목 기준으로 계산
        if "__ALL__" in codes_snapshot:
            inputs = await get_sector_summary_inputs()
            codes_snapshot = set(inputs["all_codes"])

        # ── 증분 갱신 ──
        # 1. dirty 종목 → 해당 섹터 추출
        dirty_sectors: set[str] = set()
        for cd in codes_snapshot:
            sec = await sector_mapping.get_merged_sector(cd)
            if sec:
                dirty_sectors.add(sec)

        if not dirty_sectors:
            return

        # 2. 해당 섹터의 종목만 재계산
        from backend.app.services.engine_state import state
        inputs = await get_sector_summary_inputs()
        all_codes = inputs["all_codes"]
        min_avg_amt_eok = float(state.integrated_system_settings_cache.get("sector_min_trade_amt", 0.0))
        trim_trade = float(state.integrated_system_settings_cache.get("sector_trim_trade_amt_pct", 0) or 0)
        trim_change = float(state.integrated_system_settings_cache.get("sector_trim_change_rate_pct", 0) or 0)
        sector_weights = state.integrated_system_settings_cache.get("sector_weights") or {}

        # dirty 섹터에 속한 종목코드만 필터
        dirty_codes_for_calc = [
            cd for cd in all_codes
            if await sector_mapping.get_merged_sector(cd) in dirty_sectors
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
        min_rise_ratio = float(state.integrated_system_settings_cache.get("sector_min_rise_ratio_pct", 60.0)) / 100.0
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

        ss = create_buy_targets(
            merged,
            sort_keys=state.integrated_system_settings_cache.get("sector_sort_keys") or None,
            min_rise_ratio=min_rise_ratio,
            block_rise_pct=float(state.integrated_system_settings_cache.get("buy_block_rise_pct", 7.0)),
            block_fall_pct=float(state.integrated_system_settings_cache.get("buy_block_fall_pct", 7.0)),
            min_strength=float(state.integrated_system_settings_cache.get("buy_min_strength", 0)),
            max_sectors=int(state.integrated_system_settings_cache.get("sector_max_targets", 3)),
            # 가산점 파라미터
            high_5d_cache=get_high_price_5d_cache(),
            orderbook_cache={},  # 호가잔량 캐시 삭제로 빈 dict 전달
            program_net_buy_cache=get_program_net_buy_cache(),
            boost_high_on=bool(state.integrated_system_settings_cache.get("boost_high_breakout_on", False)),
            boost_high_score=float(state.integrated_system_settings_cache.get("boost_high_breakout_score", 1.0)),
            boost_order_ratio_on=bool(state.integrated_system_settings_cache.get("boost_order_ratio_on", False)),
            boost_order_ratio_pct=float(state.integrated_system_settings_cache.get("boost_order_ratio_pct", 20.0)),
            boost_order_ratio_score=float(state.integrated_system_settings_cache.get("boost_order_ratio_score", 1.0)),
            boost_program_net_buy_on=bool(state.integrated_system_settings_cache.get("boost_program_net_buy_on", False)),
            boost_program_net_buy_score=float(state.integrated_system_settings_cache.get("boost_program_net_buy_score", 1.0)),
        )

        # 참조 교체 방식으로 캐시 갱신 (R5.6)
        _es._sector_summary_cache = ss
        # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음

        # 업종 점수 delta 전송 (내부에서 변경분만 비교)
        notify_desktop_sector_scores()
        await notify_buy_targets_update()

        try:
            await _es.try_sector_buy()
        except Exception as _buy_err:
            pass

        # buy_targets 변경 시 구독 갱신 직접 호출 (이벤트 기반)
        if are_buy_targets_changed(prev_targets, ss.buy_targets):
            sync_dynamic_subscriptions(_es, ss.buy_targets)

        # 업종 요약정보 생성 완료 이벤트 설정
        _es._sector_summary_ready_event.set()

    except Exception as e:
        logger.warning("[섹터재계산] 증분 재계산 오류: %s", e, exc_info=True)


async def _skeleton_incremental_update(_es, codes_snapshot: set[str]) -> None:
    """스켈레톤 캐치 상태에서 실시간 틱 기반 단건 델타 연산 수행.

    이벤트 주도형 구조: 틱 이벤트가 인입된 단일 종목의 등락 상태 변화만 델타로 처리.
    분모(Total)는 선행 고정되어 있으므로 분자(Rise Count)만 증분 패치.
    4대 틱 등락 상태 전환(State Transition) 매트릭스 적용.
    메모리 상의 _sector_summary_cache를 직접 갱신(In-place Update).
    단일 소스 진리: master_stocks_cache를 직접 참조.
    """
    from backend.app.core import sector_mapping
    from backend.app.services.engine_service import get_sector_summary_inputs
    from backend.app.services.engine_state import state
    
    # 실시간 틱 데이터 기반 단건 델타 연산
    inputs = await get_sector_summary_inputs()

    # 각 틱 이벤트 종목별 단건 델타 처리 (배치 루프 제거)
    for cd in codes_snapshot:
        # 해당 종목의 업종 추출
        sector = await sector_mapping.get_merged_sector(cd)
        if not sector:
            continue

        # 해당 종목의 현재 등락 상태 확인 (master_stocks_cache 직접 참조)
        detail = SectorDataProvider.get_stock(cd)
        change_rate = detail.get("change_rate", 0.0)
        curr_rising = change_rate > 0
        
        # 이전 상태 조회 (초기값은 False)
        prev_rising = _es._master_stocks_cache.get(cd, {}).get("_rising", False)
        
        # 4대 틱 등락 상태 전환(State Transition) 매트릭스
        # False -> True: 상승 전환, rise_count += 1
        # True -> False: 하락 전환, rise_count -= 1
        # False -> False 또는 True -> True: 상태 유지, 연산 없음 (O(1) 쇼트 서킷)
        if not prev_rising and curr_rising:
            # 상승 전환
            sc = _es._sector_score_index.get(sector)
            if sc:
                sc.rise_count += 1
                sc.rise_ratio = sc.rise_count / sc.total if sc.total > 0 else 0.0
        elif prev_rising and not curr_rising:
            # 하락 전환
            sc = _es._sector_score_index.get(sector)
            if sc:
                sc.rise_count = max(0, sc.rise_count - 1)
                sc.rise_ratio = sc.rise_count / sc.total if sc.total > 0 else 0.0
        else:
            # 상태 유지 (False->False 또는 True->True): 연산 없음, 즉시 continue
            pass
        
        # 현재 상태를 다음 틱을 위해 업데이트
        if cd in _es._master_stocks_cache:
            _es._master_stocks_cache[cd]["_rising"] = curr_rising
    
    # 웹소켓 난사 방지: 코알레싱 버퍼링 연동
    # 캐시 업데이트만 수행, 백엔드 코알레싱 스케줄러가 주기적으로 통합 발행
    # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음


async def _full_recompute(_es, codes_snapshot: set[str] | None = None) -> None:
    """전체 재계산 (캐시 없을 때 — 콜드 스타트).

    비동기 함수. 순수 계산 + 알림 + 이벤트 발행만 수행.
    """
    import logging
    logger = logging.getLogger(__name__)
    from backend.app.services.engine_service import get_sector_summary_inputs
    from backend.app.domain.sector_calculator import compute_full_sector_summary
    from backend.app.services.engine_account_notify import (
        notify_desktop_sector_scores,
        notify_buy_targets_update,
    )
    from backend.app.services.engine_state import state

    # buy_targets 변경 감지를 위해 이전 값 저장
    _prev_cache = _es._sector_summary_cache
    prev_targets = _prev_cache.buy_targets if _prev_cache and hasattr(_prev_cache, 'buy_targets') else None

    trim_trade = float(state.integrated_system_settings_cache.get("sector_trim_trade_amt_pct", 0) or 0)
    trim_change = float(state.integrated_system_settings_cache.get("sector_trim_change_rate_pct", 0) or 0)

    inputs = await get_sector_summary_inputs()
    ss = await compute_full_sector_summary(
        **inputs,
        sort_keys=state.integrated_system_settings_cache.get("sector_sort_keys") or None,
        min_rise_ratio=float(state.integrated_system_settings_cache.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
        block_rise_pct=float(state.integrated_system_settings_cache.get("buy_block_rise_pct", 7.0)),
        block_fall_pct=float(state.integrated_system_settings_cache.get("buy_block_fall_pct", 7.0)),
        min_strength=float(state.integrated_system_settings_cache.get("buy_min_strength", 0)),
        min_avg_amt_eok=float(state.integrated_system_settings_cache.get("sector_min_trade_amt", 0.0)),
        max_sectors=int(state.integrated_system_settings_cache.get("sector_max_targets", 3)),
        sector_weights=state.integrated_system_settings_cache.get("sector_weights"),
        trim_trade_amt_pct=trim_trade,
        trim_change_rate_pct=trim_change,
        # 가산점 파라미터
        high_5d_cache=get_high_price_5d_cache(),
        orderbook_cache={},  # 호가잔량 캐시 삭제로 빈 dict 전달
        program_net_buy_cache=get_program_net_buy_cache(),
        boost_high_on=bool(state.integrated_system_settings_cache.get("boost_high_breakout_on", False)),
        boost_high_score=float(state.integrated_system_settings_cache.get("boost_high_breakout_score", 1.0)),
        boost_order_ratio_on=bool(state.integrated_system_settings_cache.get("boost_order_ratio_on", False)),
        boost_order_ratio_pct=float(state.integrated_system_settings_cache.get("boost_order_ratio_pct", 20.0)),
        boost_order_ratio_score=float(state.integrated_system_settings_cache.get("boost_order_ratio_score", 1.0)),
        boost_program_net_buy_on=bool(state.integrated_system_settings_cache.get("boost_program_net_buy_on", False)),
        boost_program_net_buy_score=float(state.integrated_system_settings_cache.get("boost_program_net_buy_score", 1.0)),
    )

    # 참조 교체 방식으로 캐시 갱신 (R5.6)
    _es._sector_summary_cache = ss
    # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음

    # 업종 점수 delta 전송 (내부에서 변경분만 비교)
    notify_desktop_sector_scores()
    await notify_buy_targets_update()

    try:
        from backend.app.services.buy_order_executor import try_sector_buy
        await try_sector_buy()
    except Exception as _buy_err:
        logger.debug("[섹터재계산] 매수 판단 오류: %s", _buy_err)

    # buy_targets 변경 시 구독 갱신 직접 호출 (이벤트 기반)
    if are_buy_targets_changed(prev_targets, ss.buy_targets):
        sync_dynamic_subscriptions(_es, ss.buy_targets)

    # 업종 요약정보 생성 완료 이벤트 설정
    state.sector_summary_ready_event.set()


# ── 0D 구독 delta 갱신 ────────────────────────────────────────────────────


def sync_dynamic_subscriptions(es, new_buy_targets) -> None:
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
    ws = state.connector_manager or state.kiwoom_connector
    if not ws or not ws.is_connected() or not state.login_ok:
        return

    new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}

    all_stocks = SectorDataProvider.get_all_stocks()
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
                apply_delayed_unsubscription,
                es
            )
        except RuntimeError:
            pass

    # state.master_stocks_cache에 "_subscribed_dynamic" 설정
    for cd in prev_codes:
        if SectorDataProvider.has_stock(cd):
            entry = SectorDataProvider.get_stock(cd)
            entry["_subscribed_dynamic"] = True


def apply_delayed_unsubscription(es) -> None:
    """30초 후 실제 해지 적용."""
    global _PENDING_UNREG_CODES, _PENDING_UNREG_TIMER

    from backend.app.services.engine_state import state
    from backend.app.services.core_queues import get_control_queue
    import time

    all_stocks = SectorDataProvider.get_all_stocks()
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
        if SectorDataProvider.has_stock(cd):
            entry = SectorDataProvider.get_stock(cd)
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
