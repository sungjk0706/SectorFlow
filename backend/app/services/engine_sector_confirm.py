# -*- coding: utf-8 -*-
"""
업종 재계산 — 이벤트 기반 증분 갱신.

개별 REAL 체결마다 작업을 만들지 않는다.
recompute_sector_for_code(code)는 이벤트 발생 시 호출되며,
연속 호출은 중복 제거되어 1회만 재계산한다.
구독 갱신은 buy_targets 변경 시 직접 호출된다.
"""
from __future__ import annotations
import asyncio
import logging
from backend.app.services import engine_state
logger = logging.getLogger(__name__)

_dirty_codes: set[str] = set()

# 0D 구독 해지 지연 관리 (guard_pass 경계값 진동 방지)
# 종목별 독립 타이머 — 각 종목이 정확히 _UNREG_DELAY_SEC 후 해지됨 (리셋 누적 방지)
_PENDING_UNREG_TIMERS: dict[str, asyncio.TimerHandle] = dict()  # 종목별 해지 타이머
_UNREG_READY_CODES: set[str] = set()  # 타이머 만료된 종목 대기실
_UNREG_BATCH_PENDING: bool = False  # 일괄 처리 call_soon 예약 플래그
_UNREG_DELAY_SEC: float = 30.0  # 해지 지연 시간 (30초)

# DYNAMIC_REG 큐 발행 후 실제 구독 완료 전까지의 "구독 대기 중" 종목 추적 (P10 SSOT).
# _subscribed_dynamic은 "실제 구독 완료" 단일 진실 소스이며,
# _pending_reg_codes는 "큐에 발행됐으나 아직 subscribe_dynamic_data 완료 전" 상태를 추적.
# sync_dynamic_subscriptions 재진입 시 동일 종목 중복 REG 방지 목적.
_PENDING_REG_CODES: set[str] = set()


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


def extract_buy_target_page_codes(summary) -> set[str]:
    """매수 후보 화면에 표시되는 종목 코드 집합을 추출한다.

    buy-target 페이지는 매수 후보와 차단 후보를 모두 표시하므로 두 목록을
    downstream 실시간 전달 대상 비교에 포함한다. 순위·점수 변화는 페이지
    구독 대상 변경이 아니므로 코드 집합만 추출한다.
    """
    if not summary:
        return set()

    codes: set[str] = set()
    for attr in ("buy_targets", "blocked_targets"):
        targets = getattr(summary, attr, None)
        if not isinstance(targets, (list, tuple, set)):
            continue
        for target in targets:
            stock = getattr(target, "stock", None)
            code = getattr(stock, "code", None)
            if code:
                codes.add(str(code))
    return codes


def _build_prev_targets_map(summary) -> dict[str, str]:
    """이전 SectorSummary에서 통과 종목의 reject_reason 맵 생성 (보존용).

    rank_buy_targets가 BuyTarget을 새로 생성할 때 기존 reject_reason을 보존하도록
    전달하는 딕셔너리. 통과(guard_pass=True) 종목만 추출 — 차단 종목은 guard_reason이
    guard_pass 전환 시 재설정되므로 보존 대상이 아님 (P21 투명성, P23 일관성).
    """
    if not summary:
        return {}
    prev: dict[str, str] = {}
    targets = getattr(summary, "buy_targets", None)
    if not isinstance(targets, (list, tuple, set)):
        return prev
    for target in targets:
        stock = getattr(target, "stock", None)
        code = getattr(stock, "code", None)
        if code:
            prev[str(code)] = getattr(target, "reject_reason", "") or ""
    return prev


def are_buy_target_page_codes_changed(prev_summary, new_summary) -> bool:
    """매수 후보 페이지의 downstream 종목 코드 집합 변경 여부를 비교한다."""
    return extract_buy_target_page_codes(prev_summary) != extract_buy_target_page_codes(new_summary)


async def _refresh_buy_target_page_subscriptions(reason: str) -> None:
    """매수 후보 코드 변경 시 활성 화면의 downstream 구독을 최신화한다."""
    from backend.app.services.page_subscription_targets import (
        PAGE_BUY_TARGET,
        refresh_active_connections,
    )

    await refresh_active_connections(reason, {PAGE_BUY_TARGET})


async def _flush_sector_recompute_impl() -> None:
    """dirty 종목의 업종만 증분 재계산. 캐시 없으면 전체 재계산.

    비동기 함수. 순수 계산 + 알림 + 구독 갱신만 수행.
    """
    if not _dirty_codes:
        return

    codes_snapshot = set(_dirty_codes)
    _dirty_codes.clear()

    try:
        from backend.app.services.sector_data_provider import get_sector_summary_inputs
        from backend.app.domain.buy_filter import build_buy_targets_from_settings
        from backend.app.domain.sector_calculator import compute_sector_scores
        from backend.app.domain.sector_score import calculate_bonus_scores
        from backend.app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_buy_targets_update,
        )
        from backend.app.core import sector_mapping

        existing = engine_state.state.sector_summary_cache

        # 캐시 없음(콜드 스타트) → 전체 재계산 1회 (이후 증분 모드 전환)
        if not existing:
            await _full_recompute(codes_snapshot)
            return

        # __ALL__ 플래그는 설정 변경·기동 등 전체 갱신 신호이므로 전체 경로로 처리한다.
        # 전체 경로도 get_sector_summary_inputs()가 1차 필터를 적용한 종목만 반환한다.
        if "__ALL__" in codes_snapshot:
            await _full_recompute(codes_snapshot)
            return

        # ── 증분 갱신 ──
        # 1. 변경 종목 → 해당 업종 추출 (배치 조회)
        codes_list = list(codes_snapshot)
        sectors_map = await sector_mapping.get_merged_sectors_batch(codes_list)
        dirty_sectors: set[str] = set()
        for cd in codes_list:
            sec = sectors_map.get(cd, "미분류")
            if sec:
                dirty_sectors.add(sec)

        if not dirty_sectors:
            return

        # 2. 기존 업종 점수에 들어간 종목과 변경 종목만 후보로 구성.
        # 전체 master_stocks_cache를 다시 훑지 않고, 1차 필터를 통과했던
        # 해당 업종 종목만 get_sector_summary_inputs()에 전달한다.
        candidate_codes = set(codes_snapshot)
        for sector_score in existing.sectors:
            if sector_score.sector in dirty_sectors:
                candidate_codes.update(stock.code for stock in sector_score.stocks)

        inputs = await get_sector_summary_inputs(codes=sorted(candidate_codes))
        dirty_codes_for_calc = inputs["all_codes"]
        min_avg_amt_eok = float(engine_state.state.integrated_system_settings_cache["sector_min_trade_amt"])

        if dirty_codes_for_calc:
            # 명시 입력 계약 — 계산 본체에 종목 자료·업종 매핑을 전달 (2단계).
            # 임시 호환 외곽(None → 전역 상태) 경로를 더 이상 사용하지 않는다.
            new_sector_scores = await compute_sector_scores(
                dirty_codes_for_calc,
                trade_prices=inputs["trade_prices"],
                trade_amounts=inputs["trade_amounts"],
                avg_amt_5d=inputs["avg_amt_5d"],
                master_stocks_cache=inputs["master_stocks_cache"],
                sector_map=inputs["sector_map"],
                min_avg_amt_eok=min_avg_amt_eok,
            )
            new_map = {sc.sector: sc for sc in new_sector_scores}
        else:
            new_map = {}

        # 3. 기존 캐시의 업종 목록에서 dirty 업종만 교체
        merged: list = []
        for sc in existing.sectors:
            if sc.sector in dirty_sectors:
                replacement = new_map.pop(sc.sector, None)
                if replacement:
                    merged.append(replacement)
                # else: 업종가 사라진 경우 (종목 전부 필터됨) → 제외
            else:
                merged.append(sc)
        # 새로 생긴 업종 추가 (기존에 없던 업종)
        for sc in new_map.values():
            merged.append(sc)

        # 4. 3단계 누적 가산점 계산 + 컷오프 + 순위 재정렬
        min_rise_ratio = float(engine_state.state.integrated_system_settings_cache["sector_min_rise_ratio_pct"]) / 100.0
        calculate_bonus_scores(
            merged,
            min_rise_ratio=min_rise_ratio,
            rise_ratio_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_rise_ratio_slider"]),
            relative_strength_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_relative_strength_slider"]),
            trade_amount_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_trade_amount_slider"]),
        )

        # 5. 매수 타겟 큐
        # buy_targets 변경 감지를 위해 이전 값 저장
        prev_targets = existing.buy_targets if hasattr(existing, 'buy_targets') else None

        from backend.app.services import engine_account
        _held = await engine_account.get_held_codes()
        _bought_today: set[str] = set()
        if engine_state.state.auto_trade is not None:
            _bought_today = set(engine_state.state.auto_trade._bought_today.keys())
        ss = build_buy_targets_from_settings(
            merged,
            engine_state.state.integrated_system_settings_cache,
            held_codes=_held,
            bought_today_codes=_bought_today,
            prev_targets_map=_build_prev_targets_map(existing),
        )

        # 참조 교체 방식으로 캐시 갱신 (R5.6) — _set_sector_summary 단일 경로 (COUPLING-S1)
        from backend.app.services.engine_initial_data import _set_sector_summary
        _set_sector_summary(ss, "engine_sector_confirm.incremental_recompute")

        # 업종 점수 증분 전송 (내부에서 변경분만 비교)
        await notify_desktop_sector_scores()
        await notify_buy_targets_update()

        # 매수 후보 화면 downstream 구독 갱신 — 표시 종목 코드 집합 변동 시만.
        # 증권사 구독은 추가하지 않고, 이미 수신한 real-data의 페이지 라우팅만 최신화한다.
        if are_buy_target_page_codes_changed(existing, ss):
            await _refresh_buy_target_page_subscriptions("업종 증분 재계산 — 매수 후보 화면 대상 갱신")

        # 0D/PGM 동적 구독 갱신 — guard_pass 종목 집합 변동 시만.
        if are_buy_targets_changed(prev_targets, ss.buy_targets):
            sync_dynamic_subscriptions(ss.buy_targets)

        # 매수 후보 평가 요청 → 주문 실행 큐로 이동 (결정 4)
        # 업종 재계산 루프가 매수 주문·가상 체결(0.5초)에 블록되지 않도록
        # 매수 후보 평가는 주문 실행 루프가 큐에서 꺼내 처리 (W1·W2)
        # are_buy_targets_changed와 분리: 점수만 변해도 매수 기회 평가 (P11 이벤트 기반, P23 매도와 일관)
        from backend.app.services.buy_order_executor import _cash_insufficient
        from backend.app.services.core_queues import get_order_queue
        if not _cash_insufficient:
            try:
                get_order_queue().put_nowait({"type": "buy_evaluate"})
            except asyncio.QueueFull:
                # W1 무한 쌓기 방지 — 가득 시 경고 로그 + 드롭 (W8 폴백 금지, 명시적 드롭)
                logger.warning("[업종] 주문 큐 가득 참 — 매수 후보 평가 요청 드롭 (증분 재계산)")

        # 업종 요약정보 생성 완료 이벤트 설정
        engine_state.state.sector_summary_ready_event.set()

    except Exception as e:
        logger.warning("[업종] 증분 재계산 오류: %s", e, exc_info=True)


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
    _prev_cache = engine_state.state.sector_summary_cache
    prev_targets = _prev_cache.buy_targets if _prev_cache and hasattr(_prev_cache, 'buy_targets') else None

    inputs = await get_sector_summary_inputs()
    # krx_codes/nxt_codes는 수신률 분리 집계 전용, all_filter_codes는 구독 대상 식별 전용
    # — compute_full_sector_summary에는 all_codes만 전달
    compute_inputs = {k: v for k, v in inputs.items() if k not in ("krx_codes", "nxt_codes", "all_filter_codes")}
    sector_summary = await compute_full_sector_summary(
        **compute_inputs,
        min_rise_ratio=float(engine_state.state.integrated_system_settings_cache["sector_min_rise_ratio_pct"]) / 100.0,
        min_avg_amt_eok=float(engine_state.state.integrated_system_settings_cache["sector_min_trade_amt"]),
        rise_ratio_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_rise_ratio_slider"]),
        relative_strength_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_relative_strength_slider"]),
        trade_amount_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_trade_amount_slider"]),
    )
    from backend.app.services import engine_account
    _held = await engine_account.get_held_codes()
    _bought_today: set[str] = set()
    if engine_state.state.auto_trade is not None:
        _bought_today = set(engine_state.state.auto_trade._bought_today.keys())
    ss = build_buy_targets_from_settings(
        sector_summary.sectors,
        engine_state.state.integrated_system_settings_cache,
        held_codes=_held,
        bought_today_codes=_bought_today,
        prev_targets_map=_build_prev_targets_map(_prev_cache),
    )

    # 참조 교체 방식으로 캐시 갱신 (R5.6) — _set_sector_summary 단일 경로 (COUPLING-S1)
    from backend.app.services.engine_initial_data import _set_sector_summary
    _set_sector_summary(ss, "engine_sector_confirm.full_recompute")

    # 업종 점수 증분 전송 (내부에서 변경분만 비교)
    await notify_desktop_sector_scores()
    await notify_buy_targets_update()

    # 매수 후보 화면 downstream 구독 갱신 — 표시 종목 코드 집합 변동 시만.
    # 증권사 구독은 추가하지 않고, 이미 수신한 real-data의 페이지 라우팅만 최신화한다.
    if are_buy_target_page_codes_changed(_prev_cache, ss):
        await _refresh_buy_target_page_subscriptions("업종 전체 재계산 — 매수 후보 화면 대상 갱신")

    # 0D/PGM 동적 구독 갱신 — guard_pass 종목 집합 변동 시만.
    if are_buy_targets_changed(prev_targets, ss.buy_targets):
        sync_dynamic_subscriptions(ss.buy_targets)

    # 매수 후보 평가 요청 → 주문 실행 큐로 이동 (결정 4)
    # 업종 재계산 루프가 매수 주문·가상 체결(0.5초)에 블록되지 않도록
    # 매수 후보 평가는 주문 실행 루프가 큐에서 꺼내 처리 (W1·W2)
    # are_buy_targets_changed와 분리: 점수만 변해도 매수 기회 평가 (P11 이벤트 기반, P23 매도와 일관)
    from backend.app.services.core_queues import get_order_queue
    try:
        get_order_queue().put_nowait({"type": "buy_evaluate"})
    except asyncio.QueueFull:
        # W1 무한 쌓기 방지 — 가득 시 경고 로그 + 드롭 (W8 폴백 금지, 명시적 드롭)
        logger.warning("[업종] 주문 큐 가득 참 — 매수 후보 평가 요청 드롭 (전체 재계산)")

    # 업종 요약정보 생성 완료 이벤트 설정
    engine_state.state.sector_summary_ready_event.set()


# ── 0D 구독 증분 갱신 ────────────────────────────────────────────────────


def sync_dynamic_subscriptions(new_buy_targets) -> None:
    """buy_targets 변경 시 동적 구독 증분 갱신 (해지 지연 적용).

    신규 구독은 즉시, 해지는 30초 지연 후 적용.
    guard_pass 경계값 진동으로 인한 빈번한 REG/REMOVE 반복을 방지한다.
    특정 증권사에 종속되지 않도록 DYNAMIC_REG 이벤트를 제어 큐로 발행한다.
    """
    from backend.app.services.core_queues import get_control_queue
    import time

    # 실시간 통신 미연결 → 생략
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected() or not engine_state.state.login_ok:
        return

    new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}

    all_stocks = engine_state.state.master_stocks_cache
    # 구독 중 + 구독 대기 중 종목 모두 포함 — 중복 REG 방지 (P10 SSOT)
    prev_codes = ({cd for cd, entry in all_stocks.items() if entry.get("_subscribed_dynamic", False)}
                  | _PENDING_REG_CODES)

    # 신규 구독: 즉시 적용
    to_reg = new_codes - prev_codes
    if to_reg:
        payload = {
            "type": "DYNAMIC_REG",
            "payload": {
                "codes": sorted(to_reg),
                "types": ["0D", "PGM"]
            }
        }
        try:
            get_control_queue().put_nowait((1, time.time(), payload))
            # 큐 발행 성공 시 대기 세트에 추가 — 실제 구독 완료 시 pipeline_compute에서 제거
            _PENDING_REG_CODES.update(to_reg)
        except Exception as e:
            logger.warning("[구독] 신규 등록 이벤트 큐 발행 실패: %s", e)

    # 해지 대상: 종목별 독립 타이머 설정 (기존 타이머 건드리지 않음 — 리셋 누적 방지)
    new_unreg_candidates = prev_codes - new_codes
    if new_unreg_candidates:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        for code in new_unreg_candidates:
            if code not in _PENDING_UNREG_TIMERS and loop:
                _PENDING_UNREG_TIMERS[code] = loop.call_later(
                    _UNREG_DELAY_SEC,
                    _on_unreg_timer,
                    code,
                )

    # 복귀한 종목: 해당 종목 타이머만 취소
    returned_codes = set(_PENDING_UNREG_TIMERS.keys()) & new_codes
    for code in returned_codes:
        timer = _PENDING_UNREG_TIMERS.pop(code, None)
        if timer:
            timer.cancel()

    # _subscribed_dynamic 플래그는 구독 완료 후 pipeline_compute.py의 DYNAMIC_REG 처리에서만
    # 설정됨 (P10 SSOT, P22 정합성). 이전에는 구독 전에 설정하여 실패 시에도 True로 남는
    # 정합성 문제가 있었음 — _pending_reg_codes로 대기 상태 추적.


def _on_unreg_timer(code: str) -> None:
    """종목별 타이머 만료 콜백 — 준비 대기실에 추가 후 call_soon으로 일괄 처리 예약."""
    global _UNREG_BATCH_PENDING
    _PENDING_UNREG_TIMERS.pop(code, None)
    _UNREG_READY_CODES.add(code)
    if not _UNREG_BATCH_PENDING:
        _UNREG_BATCH_PENDING = True
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon(_flush_unreg_batch)
        except RuntimeError:
            _UNREG_BATCH_PENDING = False
            _UNREG_READY_CODES.clear()
            logger.warning("[구독] 타이머 만료 시 이벤트 루프 없음 — 해지 생략")


def _flush_unreg_batch() -> None:
    """타이머 만료된 종목들을 일괄 해지 (DYNAMIC_UNREG 1건 + notify 1회)."""
    global _UNREG_BATCH_PENDING
    _UNREG_BATCH_PENDING = False

    codes = set(_UNREG_READY_CODES)
    _UNREG_READY_CODES.clear()
    if not codes:
        return

    from backend.app.services.core_queues import get_control_queue
    import time

    all_stocks = engine_state.state.master_stocks_cache
    current_codes = {cd for cd, entry in all_stocks.items() if entry.get("_subscribed_dynamic", False)}
    to_unreg = codes & current_codes  # 아직 구독 중인 것만

    if to_unreg:
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
            logger.warning("[구독] 지연 해지 이벤트 큐 발행 실패: %s", e)

    # state.master_stocks_cache에서 "_subscribed_dynamic" 및 동적 데이터 완전 제거 (데이터 왜곡 차단)
    for cd in to_unreg:
        if cd in engine_state.state.master_stocks_cache:
            entry = engine_state.state.master_stocks_cache[cd]
            entry.pop("_subscribed_dynamic", None)
            entry.pop("order_ratio", None)
            entry.pop("program_net_buy", None)

    if to_unreg:
        from backend.app.services.engine_lifecycle import schedule_engine_task
        from backend.app.services.engine_account_notify import notify_buy_targets_update
        schedule_engine_task(notify_buy_targets_update(), context="구독해지 후 매수 후보 갱신")


# ── 호환용 ────────────────────────────────────────────────────────────────

def cancel_sector_recompute() -> None:
    clear_dirty_sectors()

def cancel_recompute_timer() -> None:
    clear_dirty_sectors()


def cancel_all_dynamic_unreg_timers() -> None:
    """증권사 변경 시 모든 동적 구독 해지 타이머 취소 + 대기실 비우기.

    stop_engine() 시 cancel_recompute_timer()가 _dirty_codes만 비우므로,
    동적 구독 해지 타이머는 별도로 취소해야 함.
    잔존 타이머가 신규 세션에서 발화하면 DYNAMIC_UNREG가 신규 증권사에 전송됨 (원칙 22 위반).
    """
    global _UNREG_BATCH_PENDING
    for timer in _PENDING_UNREG_TIMERS.values():
        timer.cancel()
    _PENDING_UNREG_TIMERS.clear()
    _UNREG_READY_CODES.clear()
    _UNREG_BATCH_PENDING = False
