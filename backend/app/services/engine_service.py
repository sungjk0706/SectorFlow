# -*- coding: utf-8 -*-
"""
설정 변경 동기화 — apply_settings_change 단일 함수 유지.
파사드 재내보내기는 제거됨. 각 모듈에서 직접 import할 것.
"""
import logging
from backend.app.services.engine_state import state
from backend.app.services.engine_account import (
    _refresh_account_snapshot_meta,
    _broadcast_account,
)
from backend.app.services.engine_config import (
    get_settings_snapshot,
    refresh_engine_integrated_system_settings_cache,
    _mask_sensitive_settings,
    TRADE_MODE_KEYS,
)
from backend.app.services.engine_lifecycle import (
    is_engine_running,
    schedule_engine_task,
    on_trade_mode_switched,
)
from backend.app.services.sector_data_provider import (
    recompute_sector_summary_now,
)

logger = logging.getLogger(__name__)


async def apply_settings_change(changed_keys: set[str]) -> None:
    """설정 변경 후 엔진 동기화 (settings_store.py에서 이관)"""
    from backend.app.services.engine_account_notify import (
        notify_desktop_header_refresh,
        notify_desktop_sector_scores,
        notify_desktop_settings_toggled,
    )
    from backend.app.services import settlement_engine as _se
    from backend.app.services import daily_time_scheduler as _dts
    from backend.app.services import ws_subscribe_control

    if not changed_keys:
        await notify_desktop_header_refresh()
        return

    # ── 1) RAM 캐시 갱신 — PATCH 저장 직후 DB 최신값을 캐시에 반영 ──────────────
    # [핵심] DB 저장 후 브로드캐스트 전에 반드시 캐시를 갱신해야 최신 값이 전송됨.
    # refresh_engine_integrated_system_settings_cache는 엔진 실행 여부와 무관하게 캐시를 갱신함.
    await refresh_engine_integrated_system_settings_cache(None, use_root=True)

    # ── 2) broker 변경 → 엔진 재기동 (단일 진입점 보장) ───────────────────────
    if "broker" in changed_keys:
        from backend.app.core.broker_factory import reset_router
        if is_engine_running():
            from backend.app.services.engine_lifecycle import stop_engine, start_engine, reset_broker_session_state
            logger.info("[설정] 증권사 변경 감지 — 엔진 재기동 (단일 진입점 보장)")
            await stop_engine()
            reset_broker_session_state()
            reset_router()
            await start_engine()
        else:
            reset_router()
        await notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
        return

    # ── 3) 투자모드 전환 → 캐시 갱신 + 계좌 구독 전환 ────────────────────
    if changed_keys & TRADE_MODE_KEYS:
        if is_engine_running():
            schedule_engine_task(on_trade_mode_switched(), context="투자모드 전환")
            logger.info("[설정] 투자모드 전환 감지 — 저장데이터 갱신 + 계좌 구독 전환 (엔진 재기동 없음)")
        await notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
        return

    # ── 4) 일반 설정 변경 (증분 브로드캐스트 전송) ────────────────────────
    await notify_desktop_header_refresh()
    
    changed_dict = {}
    try:
        display_settings = dict(state.integrated_system_settings_cache)
        masked_settings = _mask_sensitive_settings(display_settings)
        for k in changed_keys:
            if k in masked_settings:
                changed_dict[k] = masked_settings[k]
    except Exception as e:
        logger.warning("[설정] 마스킹 델타 추출 실패: %s", e)

    await notify_desktop_settings_toggled(changed_dict)

    # 테스트모드 가상 예수금 변경 시 Settlement Engine 동기화 + 계좌 스냅샷 갱신
    _VIRTUAL_BALANCE_KEYS = {"test_virtual_balance", "test_virtual_deposit"}
    if changed_keys & _VIRTUAL_BALANCE_KEYS:
        try:
            _s = state.integrated_system_settings_cache
            _deposit = int(_s.get("test_virtual_balance", _s.get("test_virtual_deposit", 10_000_000)) or 0)
            await _se.reset(_deposit)
            # 계좌 스냅샷 갱신 + WS account-update 발송
            await _refresh_account_snapshot_meta()
            await _broadcast_account(reason="virtual_balance_changed")
        except Exception:
            logger.warning("[설정] 가상 예수금 동기화 실패", exc_info=True)

    # 5일봉 다운로드 토글 ON 시 즉시 다운로드 트리거
    if "scheduler_5d_download_on" in changed_keys:
        _5d_on = bool(get_settings_snapshot().get("scheduler_5d_download_on", True))
        if _5d_on:
            try:
                state.avg_amt_needs_bg_refresh = True
                logger.info("[설정] 5일봉 다운로드 설정=ON → 5일봉 다운로드 트리거")
            except Exception:
                logger.warning("[설정] 5일봉 다운로드 트리거 실패", exc_info=True)

    # 자동매매 시간 관련 설정 변경 시 타이머 재예약 + Connector 플래그 동기화
    _TIME_SCHEDULE_KEYS = {
        "time_scheduler_on", "auto_buy_on", "auto_sell_on",
        "buy_time_start", "buy_time_end", "sell_time_start", "sell_time_end",
    }
    if changed_keys & _TIME_SCHEDULE_KEYS:
        try:
            from backend.app.services.daily_time_scheduler import schedule_auto_trade_timers
            new_settings = get_settings_snapshot()
            await schedule_auto_trade_timers(new_settings)
        except Exception:
            logger.warning("[설정] 자동매매 타이머 재예약 실패", exc_info=True)

    # WS 구독 시간/스위치 변경 시 → 즉시 구간 재판정 + 타이머 재예약
    _WS_SCHEDULE_KEYS = {"ws_subscribe_on", "confirmed_download_time", "scheduler_market_close_on"}
    if changed_keys & _WS_SCHEDULE_KEYS:
        try:
            new_settings = get_settings_snapshot()
            now_in_window = await _dts.is_ws_subscribe_window(new_settings)
            was_active = bool(state.ws_subscribe_window_active)

            # 1) 타이머 재예약 (항상)
            await _dts.schedule_ws_subscribe_timers(new_settings)

            # 2) 활성→구간밖: 즉시 구독 해제 + WS 끊기 (장마감 후처리 없이)
            if was_active and not now_in_window:
                logger.info("[설정] 실시간 구독 구간 변경 → 현재 구간 밖 — 즉시 구독 해제")
                _dts._fire_ws_disconnect_only()

            # 3) 비활성→구간안: 즉시 WS 연결 + 구독 시작
            elif not was_active and now_in_window:
                logger.info("[설정] 실시간 구독 구간 변경 → 현재 구간 안 — 즉시 구독 시작")
                schedule_engine_task(_dts._on_ws_subscribe_start(), context="실시간 구독 시작")
        except Exception:
            logger.warning("[설정] 실시간 구독 타이머 재예약 실패", exc_info=True)

    # 업종 정렬/필터 관련 설정 변경 시 업종 점수만 재계산 (종목 시세는 WS delta로만 전송)
    _SECTOR_UI_KEYS = {
        "sector_sort_keys",
        "sector_min_rise_ratio_pct", "sector_min_trade_amt",
        "sector_max_targets",
        "sector_bonus_rise_ratio_slider",
        "sector_bonus_relative_strength_slider",
        "sector_bonus_trade_amount_slider",
        "buy_block_rise_on", "buy_block_rise_pct",
        "buy_block_fall_on", "buy_block_fall_pct",
        "buy_block_strength_on", "buy_min_strength",
        # 가산점 설정
        "boost_high_breakout_on", "boost_high_breakout_score",
        "boost_order_ratio_on",
        "boost_order_ratio_pct", "boost_order_ratio_score",
        "boost_program_net_buy_on", "boost_program_net_buy_score",
        "boost_trade_amount_rank_on", "boost_trade_amount_rank_score",
        # 재매수 차단 — 보유/금일매수 종목의 buy_targets/blocked_targets 분류에 영향
        "rebuy_block_on",
    }
    if changed_keys & _SECTOR_UI_KEYS:
        if is_engine_running():
            if "sector_min_trade_amt" in changed_keys:
                schedule_engine_task(
                    state.on_filter_settings_changed(), context="필터 설정 변경"
                )
            schedule_engine_task(
                recompute_sector_summary_now(), context="업종 설정 변경"
            )
        try:
            await notify_desktop_sector_scores(force=True)
        except Exception as e:
            logger.warning("[설정] 업종 점수 전송 실패: %s", e, exc_info=True)

    # WS 구독 제어 설정 변경 시 즉시 반영 (구독 시작/해지)
    _WS_SUBSCRIBE_CONTROL_KEYS = {"index_auto_subscribe", "quote_auto_subscribe"}
    _ws_changed = changed_keys & _WS_SUBSCRIBE_CONTROL_KEYS
    if _ws_changed:
        try:
            raw = state.integrated_system_settings_cache
            for key in _ws_changed:
                schedule_engine_task(
                    ws_subscribe_control.on_setting_changed(key, bool(raw.get(key))),
                    context=f"WS 구독 제어 설정 반영({key})",
                )
        except Exception:
            logger.warning("[설정] 실시간 구독 제어 설정 변경 반영 실패", exc_info=True)

    # 텔레그램 토글 시 폴링 start/stop
    if "tele_on" in changed_keys:
        try:
            from backend.app.services.telegram_bot import telegram_bot
            _tele_on = bool(state.integrated_system_settings_cache.get("tele_on", False))
            if _tele_on:
                telegram_bot.start()
                logger.info("[설정] 텔레그램 설정=ON → 텔레그램 폴링 시작")
            else:
                await telegram_bot.stop_async()
                logger.info("[설정] 텔레그램 설정=OFF → 텔레그램 폴링 종료")
        except Exception:
            logger.warning("[설정] 텔레그램 폴링 토글 실패", exc_info=True)

    # ── 매수 조건 스냅샷 무효화 — 설정 변경 시 매수 재평가 허용 ──
    try:
        from backend.app.services.buy_order_executor import invalidate_buy_snapshot
        invalidate_buy_snapshot()
    except Exception:
        pass

