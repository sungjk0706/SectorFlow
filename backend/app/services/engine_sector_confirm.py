# -*- coding: utf-8 -*-
"""
섹터 재계산 — 이벤트 기반 증분 갱신.

개별 REAL 체결마다 태스크를 만들지 않는다.
recompute_sector_for_code(code)는 이벤트 발생 시 호출되며,
연속 호출은 coalesce되어 1회만 재계산한다.
구독 갱신은 buy_targets 변경 시 직접 호출된다.
"""
from __future__ import annotations

import asyncio
from app.core.logger import get_logger

logger = get_logger("engine")

_dirty_codes: set[str] = set()
_recompute_handle = None  # asyncio.TimerHandle — cancel 가능한 예약 핸들

# 0D 구독 해지 지연 관리 (guard_pass 경계값 진동 방지)
_PENDING_UNREG_CODES: set[str] = set()  # 해지 대기 중인 종목 코드
_PENDING_UNREG_TIMER: asyncio.TimerHandle | None = None  # 해지 타이머
_UNREG_DELAY_SEC: float = 30.0  # 해지 지연 시간 (30초)


def _is_engine_running() -> bool:
    from app.services.engine_service import _running
    return _running


def recompute_sector_for_code(code: str | None = None) -> None:
    """이벤트 발생 시 호출 — dirty 마킹 후 최대 0.3s 내 1회 실행 보장.

    첫 틱: 0.3s 후 실행 예약.
    추가 틱: dirty set에만 추가, 기존 예약 유지 (cancel 안 함).
    → 연속 틱 폭풍 중에도 0.3s마다 반드시 1회 실행된다.
    """
    global _recompute_handle

    if not _is_engine_running():
        return

    if code:
        _dirty_codes.add(code)
    else:
        _dirty_codes.add("__ALL__")

    if _recompute_handle is not None:
        return  # 이미 예약됨 — dirty set에만 추가하고 끝

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 이벤트 루프 없음(테스트 등) — 즉시 실행 폴백
        _flush_sector_recompute_impl()
        return

    _recompute_handle = loop.call_later(0.3, _run_flush_sync)


def _run_flush_sync() -> None:
    """call_later 콜백 — _flush 실행 후 핸들 초기화."""
    global _recompute_handle
    _recompute_handle = None
    _flush_sector_recompute_impl()


def is_sector_dirty() -> bool:
    return len(_dirty_codes) > 0


def clear_sector_dirty() -> None:
    _dirty_codes.clear()


def _get_guard_pass_codes(buy_targets) -> set[str]:
    """buy_targets에서 guard_pass=True인 종목코드 집합 추출."""
    if not buy_targets:
        return set()
    return {bt.stock.code for bt in buy_targets if bt.stock.guard_pass}


def _buy_targets_changed(prev_targets, new_targets) -> bool:
    """buy_targets의 guard_pass=True 종목코드 집합이 변경되었는지 비교."""
    prev_codes = _get_guard_pass_codes(prev_targets)
    new_codes = _get_guard_pass_codes(new_targets)
    return prev_codes != new_codes


def _flush_sector_recompute_impl() -> None:
    """dirty 종목의 섹터만 증분 재계산. 캐시 없으면 전체 재계산.

    동기 함수. 순수 계산 + 알림 + 구독 갱신만 수행.
    """
    global _dirty_codes
    
    if not _dirty_codes or not _is_engine_running():
        return

    codes_snapshot = set(_dirty_codes)
    _dirty_codes.clear()

    try:
        import app.services.engine_service as _es
        from app.services.engine_service import _get_settings, get_sector_summary_inputs
        from app.services.engine_sector_score import (
            compute_sector_scores,
            compute_weighted_scores,
            compute_full_sector_summary,
            check_index_guard,
            build_buy_targets,
        )
        from app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_buy_targets_update,
        )
        from app.core import sector_mapping

        settings = _get_settings()
        existing = _es._sector_summary_cache

        # 캐시 없음(콜드 스타트) → 전체 재계산 1회 (이후 증분 모드 전환)
        if not existing:
            _full_recompute(_es, settings, codes_snapshot)
            return

        # __ALL__ 플래그 + 캐시 존재 → 모든 active 종목을 dirty로 취급하여 증분 경로 사용
        if "__ALL__" in codes_snapshot:
            codes_snapshot = {
                cd for cd, det in _es._pending_stock_details.items()
                if det.get("status") == "active"
            }

        # ── 증분 갱신 ──
        # 1. dirty 종목 → 해당 섹터 추출
        dirty_sectors: set[str] = set()
        for cd in codes_snapshot:
            sec = sector_mapping.get_merged_sector(cd)
            if sec:
                dirty_sectors.add(sec)

        if not dirty_sectors:
            return

        # 2. 해당 섹터의 종목만 재계산
        inputs = get_sector_summary_inputs()
        all_codes = inputs["all_codes"]
        min_trade_amt_won = float(settings.get("sector_min_trade_amt", 0.0)) * 1_0000_0000
        trim_trade = float(settings.get("sector_trim_trade_amt_pct", 0) or 0)
        trim_change = float(settings.get("sector_trim_change_rate_pct", 0) or 0)
        sector_weights = settings.get("sector_weights")

        # dirty 섹터에 속한 종목코드만 필터
        dirty_codes_for_calc = [
            cd for cd in all_codes
            if sector_mapping.get_merged_sector(cd) in dirty_sectors
        ]

        if dirty_codes_for_calc:
            new_sector_scores = compute_sector_scores(
                dirty_codes_for_calc,
                trade_prices=inputs["trade_prices"],
                trade_amounts=inputs["trade_amounts"],
                avg_amt_5d=inputs["avg_amt_5d"],
                strengths=inputs["strengths"],
                stock_details=inputs["stock_details"],
                min_trade_amt_won=min_trade_amt_won,
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
        compute_weighted_scores(merged, weights=sector_weights)

        # 5. 업종 컷오프: 상승비율 미만 업종은 순위 없음(rank=0)
        min_rise_ratio = float(settings.get("sector_min_rise_ratio_pct", 60.0)) / 100.0
        if min_rise_ratio > 0:
            pass_sectors = [sc for sc in merged if sc.rise_ratio >= min_rise_ratio]
            fail_sectors = [sc for sc in merged if sc.rise_ratio < min_rise_ratio]
            # pass 그룹에만 순위 부여 (1부터)
            for i, sc in enumerate(pass_sectors):
                sc.rank = i + 1
            # fail 그룹은 순위 없음 (0)
            for sc in fail_sectors:
                sc.rank = 0
            # 표시 순서: pass 먼저, fail은 뒤에
            merged = pass_sectors + fail_sectors

        # 6. 지수 가드 + 매수 타겟 큐
        index_guard_active, index_guard_reason, kospi_hit, kosdaq_hit = check_index_guard(
            inputs["latest_index"],
            kospi_on=bool(settings.get("buy_index_guard_kospi_on", False)),
            kosdaq_on=bool(settings.get("buy_index_guard_kosdaq_on", False)),
            kospi_drop=float(settings.get("buy_index_kospi_drop", 2.0)),
            kosdaq_drop=float(settings.get("buy_index_kosdaq_drop", 2.0)),
        )

        # buy_targets 변경 감지를 위해 이전 값 저장
        prev_targets = existing.buy_targets if hasattr(existing, 'buy_targets') else None

        ss = build_buy_targets(
            merged,
            sort_keys=settings.get("sector_sort_keys") or None,
            min_rise_ratio=min_rise_ratio,
            block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
            block_fall_pct=float(settings.get("buy_block_fall_pct", 7.0)),
            min_strength=float(settings.get("buy_min_strength", 0)),
            index_guard_kospi_hit=kospi_hit,
            index_guard_kosdaq_hit=kosdaq_hit,
            index_guard_reason=index_guard_reason,
            latest_index=inputs["latest_index"],
            max_sectors=int(settings.get("sector_max_targets", 3)),
            # 가산점 파라미터
            high_5d_cache=_es._high_5d_cache,
            orderbook_cache=_es._orderbook_cache,
            boost_high_on=bool(settings.get("boost_high_breakout_on", False)),
            boost_high_score=float(settings.get("boost_high_breakout_score", 1.0)),
            boost_order_ratio_on=bool(settings.get("boost_order_ratio_on", False)),
            boost_order_ratio_pct=float(settings.get("boost_order_ratio_pct", 20.0)),
            boost_order_ratio_score=float(settings.get("boost_order_ratio_score", 1.0)),
        )

        # 참조 교체 방식으로 캐시 갱신 (R5.6)
        _es._sector_summary_cache = ss
        _es._invalidate_sector_stocks_cache()

        # 업종 점수 delta 전송 (내부에서 변경분만 비교)
        notify_desktop_sector_scores()
        notify_buy_targets_update()

        try:
            _es._try_sector_buy()
        except Exception as _buy_err:
            logger.debug("[섹터재계산] 매수 판단 오류: %s", _buy_err)

        # buy_targets 변경 시 구독 갱신 직접 호출 (이벤트 기반)
        if _buy_targets_changed(prev_targets, ss.buy_targets):
            _sync_0d_subscriptions_sync(_es, ss.buy_targets)

    except Exception as e:
        logger.warning("[섹터재계산] 증분 재계산 오류: %s", e, exc_info=True)


def _full_recompute(_es, settings: dict, codes_snapshot: set[str] | None = None) -> None:
    """전체 재계산 (캐시 없을 때 — 콜드 스타트).

    동기 함수. 순수 계산 + 알림 + 이벤트 발행만 수행.
    """
    from app.services.engine_service import get_sector_summary_inputs
    from app.services.engine_sector_score import compute_full_sector_summary
    from app.services.engine_account_notify import (
        notify_desktop_sector_scores,
        notify_buy_targets_update,
    )

    # buy_targets 변경 감지를 위해 이전 값 저장
    prev_targets = _es._sector_summary_cache.buy_targets if _es._sector_summary_cache and hasattr(_es._sector_summary_cache, 'buy_targets') else None

    trim_trade = float(settings.get("sector_trim_trade_amt_pct", 0) or 0)
    trim_change = float(settings.get("sector_trim_change_rate_pct", 0) or 0)

    inputs = get_sector_summary_inputs()
    ss = compute_full_sector_summary(
        **inputs,
        sort_keys=settings.get("sector_sort_keys") or None,
        min_rise_ratio=float(settings.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
        block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
        block_fall_pct=float(settings.get("buy_block_fall_pct", 7.0)),
        min_strength=float(settings.get("buy_min_strength", 0)),
        min_trade_amt_won=float(settings.get("sector_min_trade_amt", 0.0)) * 1_0000_0000,
        index_guard_kospi_on=bool(settings.get("buy_index_guard_kospi_on", False)),
        index_guard_kosdaq_on=bool(settings.get("buy_index_guard_kosdaq_on", False)),
        index_kospi_drop=float(settings.get("buy_index_kospi_drop", 2.0)),
        index_kosdaq_drop=float(settings.get("buy_index_kosdaq_drop", 2.0)),
        max_sectors=int(settings.get("sector_max_targets", 3)),
        sector_weights=settings.get("sector_weights"),
        trim_trade_amt_pct=trim_trade,
        trim_change_rate_pct=trim_change,
        # 가산점 파라미터
        high_5d_cache=_es._high_5d_cache,
        orderbook_cache=_es._orderbook_cache,
        boost_high_on=bool(settings.get("boost_high_breakout_on", False)),
        boost_high_score=float(settings.get("boost_high_breakout_score", 1.0)),
        boost_order_ratio_on=bool(settings.get("boost_order_ratio_on", False)),
        boost_order_ratio_pct=float(settings.get("boost_order_ratio_pct", 20.0)),
        boost_order_ratio_score=float(settings.get("boost_order_ratio_score", 1.0)),
    )

    # 참조 교체 방식으로 캐시 갱신 (R5.6)
    _es._sector_summary_cache = ss
    _es._invalidate_sector_stocks_cache()

    # 업종 점수 delta 전송 (내부에서 변경분만 비교)
    notify_desktop_sector_scores()
    notify_buy_targets_update()

    try:
        _es._try_sector_buy()
    except Exception as _buy_err:
        logger.debug("[섹터재계산] 매수 판단 오류: %s", _buy_err)

    # buy_targets 변경 시 구독 갱신 직접 호출 (이벤트 기반)
    if _buy_targets_changed(prev_targets, ss.buy_targets):
        _sync_0d_subscriptions_sync(_es, ss.buy_targets)


# ── 0D 구독 delta 갱신 ────────────────────────────────────────────────────


def _sync_0d_subscriptions_sync(es, new_buy_targets) -> None:
    """buy_targets 변경 시 0D 호가 구독 delta 갱신 (해지 지연 적용).

    신규 구독은 즉시, 해지는 30초 지연 후 적용.
    guard_pass 경계값 진동으로 인한 빈번한 REG/REMOVE 반복을 방지한다.
    """
    global _PENDING_UNREG_CODES, _PENDING_UNREG_TIMER

    from app.services.engine_ws_reg import build_0d_reg_payloads, build_0d_remove_payloads

    # WS 미연결 → 스킵
    if not es._kiwoom_connector or not es._kiwoom_connector.is_connected() or not es._login_ok:
        return

    new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}
    prev_codes = es._subscribed_0d_stocks

    # 신규 구독: 즉시 적용
    to_reg = new_codes - prev_codes
    if to_reg:
        logger.info("[호가구독] 신규 등록 %d종목", len(to_reg))
        payloads = build_0d_reg_payloads(sorted(to_reg))
        for payload in payloads:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(es._ws_send_reg_unreg_and_wait_ack(payload))
            except RuntimeError:
                pass
        prev_codes = prev_codes | to_reg  # 임시로 추가

    # 해지 대상: 지연 적용
    new_unreg_candidates = prev_codes - new_codes
    if new_unreg_candidates:
        _PENDING_UNREG_CODES.update(new_unreg_candidates)
        logger.debug("[호가구독] 해지 대기 %d종목 추가 (총 %d종목)",
                     len(new_unreg_candidates), len(_PENDING_UNREG_CODES))

    # 복귀한 종목은 해지 취소
    returned_codes = _PENDING_UNREG_CODES & new_codes
    if returned_codes:
        _PENDING_UNREG_CODES -= returned_codes
        logger.debug("[호가구독] 해지 취소 %d종목 (다시 통과)", len(returned_codes))

    # 해지 타이머 설정/재설정
    if _PENDING_UNREG_CODES:
        if _PENDING_UNREG_TIMER is not None:
            _PENDING_UNREG_TIMER.cancel()
        try:
            loop = asyncio.get_running_loop()
            _PENDING_UNREG_TIMER = loop.call_later(
                _UNREG_DELAY_SEC,
                _apply_delayed_unreg,
                es
            )
        except RuntimeError:
            pass

    es._subscribed_0d_stocks = prev_codes


def _apply_delayed_unreg(es) -> None:
    """30초 후 실제 해지 적용."""
    global _PENDING_UNREG_CODES, _PENDING_UNREG_TIMER

    from app.services.engine_ws_reg import build_0d_remove_payloads

    current_codes = es._subscribed_0d_stocks
    to_unreg = _PENDING_UNREG_CODES & current_codes  # 아직 구독 중인 것만

    if to_unreg:
        logger.info("[호가구독] 지연 해지 적용 %d종목", len(to_unreg))
        payloads = build_0d_remove_payloads(sorted(to_unreg))
        for payload in payloads:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(es._ws_send_reg_unreg_and_wait_ack(payload))
            except RuntimeError:
                pass
        current_codes -= to_unreg

    _PENDING_UNREG_CODES.clear()
    _PENDING_UNREG_TIMER = None
    es._subscribed_0d_stocks = current_codes


async def _sync_0d_subscriptions(es, new_buy_targets) -> None:
    """buy_targets 변경 시 0D 호가 구독 delta 갱신.

    guard_pass=True 종목(buy_targets)의 코드 집합과 이전 구독 집합을 비교하여
    REG(신규) / REMOVE(제거) 페이로드만 전송한다.
    WS 미연결 시 조용히 스킵.
    """
    from app.services.engine_ws_reg import build_0d_reg_payloads, build_0d_remove_payloads

    # WS 미연결 → 스킵
    if not es._kiwoom_connector or not es._kiwoom_connector.is_connected() or not es._login_ok:
        return

    new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}
    prev_codes = es._subscribed_0d_stocks

    to_reg = new_codes - prev_codes
    to_unreg = prev_codes - new_codes

    if to_reg:
        payloads = build_0d_reg_payloads(sorted(to_reg))
        for payload in payloads:
            try:
                ack_ok, rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
                if not ack_ok:
                    logger.warning("[호가잔량 구독등록] 응답 시간 초과 — %d종목", len(payload["data"][0]["item"]))
            except Exception as exc:
                logger.warning("[호가잔량 구독등록] 전송 오류: %s", exc)

    if to_unreg:
        payloads = build_0d_remove_payloads(sorted(to_unreg))
        for payload in payloads:
            try:
                ack_ok, rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
                if not ack_ok:
                    logger.debug("[호가잔량 구독해지] 응답 시간 초과 — 무시")
            except Exception as exc:
                logger.debug("[호가잔량 구독해지] 전송 오류 (무시): %s", exc)

    es._subscribed_0d_stocks = new_codes


# ── 호환용 ────────────────────────────────────────────────────────────────

def flush_sector_recompute() -> None:
    """하위 호환성: recompute_sector_for_code(None)과 동일."""
    recompute_sector_for_code(None)

def cancel_pending_recompute() -> None:
    clear_sector_dirty()

def cancel_sector_confirm_timer() -> None:
    clear_sector_dirty()
