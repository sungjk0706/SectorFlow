# -*- coding: utf-8 -*-
"""
자동매매 엔진 오케스트레이터 (메모리 전용 버전) - 파사드 모듈
- 전역 상태 변수는 engine_state.py에 저장
- 분리된 모듈 함수 재내보내기
"""
import asyncio
import sys
import time
from backend.app.core.logger import get_logger
from backend.app.core.kiwoom_connector import KiwoomConnector
from backend.app.services.trading import AutoTradeManager
from backend.app.services import engine_account_notify as _account_notify
from backend.app.services.engine_utils import LazyLock, LazyEvent
from backend.app.services.state_manager import StateManager, OrderStatus

# ── 전역 상태 import (engine_state에서 직접 import) ─────────────────────
from backend.app.services.engine_state import (
    state,
    _get_rest_api_thread_sem,
    _get_account_rest_lock,
    _get_realtime_state,
    _set_realtime_state,
    _cancel_price_trace_delayed_task,
)

# ── 업종 요약 캐시 (단일 소스 진리) ───────────────────────────────────────
_sector_summary_cache: "SectorSummary | None" = None  # type: ignore[name-defined]

# ── 분리된 모듈 import ─────────────────────────────────────────────────
from backend.app.services.engine_ws import (
    _ws_send_reg_unreg_and_wait_ack,
    _ws_send_remove_fire_and_forget,
    _broker_message_handler,
    _handle_ws_data,
    _subscribe_stock_realtime_when_ready,
    _subscribe_account_realtime,
    _log_reg_stock_chunk,
    _subscribe_positions_stocks_realtime,
    _subscribe_radar_stocks_realtime,
    _subscribe_all_tracked_stocks_realtime,
    _item_cd_is_position,
    _item_cd_tracked_radar_or_ready,
    _sweep_unreg_subscribed_except_positions_and_tracked,
    _cleanup_stale_ws_subscriptions_on_session_ready,
    _subscribe_sector_stocks_0b,
    _ensure_ws_subscriptions_for_positions,
    _run_sector_reg_pipeline,
)
from backend.app.services.engine_account import (
    get_account_snapshot,
    get_trade_mode,
    get_positions,
    get_total_buy_amount,
    get_total_eval_amount,
    get_total_pnl,
    get_total_pnl_rate,
    get_snapshot_history,
    get_buy_limit_status,
    _broadcast_buy_limit_status,
    _fetch_account_data,
    _update_account_memory,
    _update_account_memory_inner,
    _merge_positions_from_rest,
    _apply_broker_totals_from_summary,
    _refresh_account_snapshot_meta,
    _apply_last_price_to_positions,
    _apply_balance_realtime,
    _on_fill_after_ws,
    _broadcast_account,
    _apply_delayed_account_broadcast,
    _position_codes_with_qty,
    _get_account_rest_lock,
)
from backend.app.services.engine_config import (
    _get_settings,
    get_settings_snapshot,
    refresh_engine_integrated_system_settings_cache,
    reload_engine_settings,
    _mask_sensitive_settings,
    get_connection_level_keys,
    TRADE_MODE_KEYS,
)
from backend.app.services.engine_radar import (
    get_pending_stocks,
    get_sector_stock_layout,
    # get_avg_amt_5d_map 유지: _master_stocks_cache에서 직접 추출
    get_avg_amt_5d_map,
    get_high_5d_cache,
    _overlay_radar_row_with_live_price,
    _apply_real01_volume_amount_to_radar_rows,
    _mark_radar_exited,
    clear_exited_from_radar,
    _drop_rest_radar_quote_for_nk,
    _clear_radar_rest_bootstrap_for_stk_cd,
    _clear_radar_and_ready_memory,
    _tracked_ui_stock_codes,
)
from backend.app.services.engine_sector import (
    get_sector_scores_snapshot,
    recompute_sector_summary_now,
    get_sector_summary_inputs,
    get_sector_stocks,
    get_all_sector_stocks,
    # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음
    _on_filter_settings_changed as _sector_on_filter_settings_changed,
    # _compute_filtered_codes 제거: sector_stock_layout 의존성 제거
)
from backend.app.services.engine_lifecycle import (
    start_engine,
    _engine_loop,
    stop_engine,
    is_running,
    get_status,
    on_trade_mode_switched,
    _try_sector_buy,
    _log,
    _now_kst,
    _schedule_engine_coro,
    _sync_sell_overrides_from_settings,
    _broadcast_engine_ws,
    update_broker_credentials_live,
    _delayed_resubscribe_stock_after_rate_limit,
)
from backend.app.services.engine_snapshot import (
    build_initial_snapshot,
    build_sector_stocks_payload,
    _filter_stock_fields,
    _get_trade_history_for_snapshot,
    _get_daily_summary_for_snapshot,
    _reset_realtime_fields,
    _set_realtime_state,
    _get_realtime_state,
    # 실시간 호가잔량 기능 삭제로 import 제거 (_get_orderbook)
    get_buy_targets_snapshot,
    get_position_pnl_pct_for_code,
    get_latest_trade_price_for_ui,
    _run_snapshot_and_sell_check,
)

# ── engine_account_notify 재내보내기 ────────────────────────────────────
broadcast_account_update = _account_notify.broadcast_account_update
broadcast_engine_status_ws = _account_notify.broadcast_engine_status_ws
notify_desktop_trade_price = _account_notify.notify_desktop_trade_price
register_account_ws_queue = _account_notify.register_account_ws_queue
register_desktop_buy_radar_notifier = _account_notify.register_desktop_buy_radar_notifier
register_desktop_account_tabs_refresh = _account_notify.register_desktop_account_tabs_refresh
register_desktop_header_refresh_notifier = _account_notify.register_desktop_header_refresh_notifier
register_desktop_trade_price_notifier = _account_notify.register_desktop_trade_price_notifier
notify_desktop_account_tabs_refresh = _account_notify.notify_desktop_account_tabs_refresh
notify_desktop_buy_radar_only = _account_notify.notify_desktop_buy_radar_only
register_engine_ws_queue = _account_notify.register_engine_ws_queue
unregister_account_ws_queue = _account_notify.unregister_account_ws_queue
unregister_engine_ws_queue = _account_notify.unregister_engine_ws_queue
register_desktop_index_notifier = _account_notify.register_desktop_index_notifier
register_desktop_sector_notifier = _account_notify.register_desktop_sector_notifier
notify_desktop_sector_refresh = _account_notify.notify_desktop_sector_refresh
notify_desktop_sector_scores = _account_notify.notify_desktop_sector_scores
register_desktop_settings_toggled_notifier = _account_notify.register_desktop_settings_toggled_notifier
notify_desktop_settings_toggled = _account_notify.notify_desktop_settings_toggled
notify_snapshot_history_update = _account_notify.notify_snapshot_history_update
notify_buy_targets_update = _account_notify.notify_buy_targets_update
notify_desktop_sector_stocks_refresh = _account_notify.notify_desktop_sector_stocks_refresh

logger = get_logger("engine")

# ── 재내보내기 (Facade Pattern) ─────────────────────────────────────────
# engine_ws
_ws_send_reg_unreg_and_wait_ack = _ws_send_reg_unreg_and_wait_ack
_ws_send_remove_fire_and_forget = _ws_send_remove_fire_and_forget
_broker_message_handler = _broker_message_handler
_handle_ws_data = _handle_ws_data
_subscribe_stock_realtime_when_ready = _subscribe_stock_realtime_when_ready
_subscribe_account_realtime = _subscribe_account_realtime
_log_reg_stock_chunk = _log_reg_stock_chunk
_subscribe_positions_stocks_realtime = _subscribe_positions_stocks_realtime
_subscribe_radar_stocks_realtime = _subscribe_radar_stocks_realtime
_subscribe_all_tracked_stocks_realtime = _subscribe_all_tracked_stocks_realtime
_item_cd_is_position = _item_cd_is_position
_item_cd_tracked_radar_or_ready = _item_cd_tracked_radar_or_ready
_sweep_unreg_subscribed_except_positions_and_tracked = _sweep_unreg_subscribed_except_positions_and_tracked
_cleanup_stale_ws_subscriptions_on_session_ready = _cleanup_stale_ws_subscriptions_on_session_ready
_subscribe_sector_stocks_0b = _subscribe_sector_stocks_0b
_ensure_ws_subscriptions_for_positions = _ensure_ws_subscriptions_for_positions
_run_sector_reg_pipeline = _run_sector_reg_pipeline

# engine_account
get_account_snapshot = get_account_snapshot
get_trade_mode = get_trade_mode
get_positions = get_positions
get_total_buy_amount = get_total_buy_amount
get_total_eval_amount = get_total_eval_amount
get_total_pnl = get_total_pnl
get_total_pnl_rate = get_total_pnl_rate
get_snapshot_history = get_snapshot_history
get_buy_limit_status = get_buy_limit_status
_broadcast_buy_limit_status = _broadcast_buy_limit_status
_fetch_account_data = _fetch_account_data
_update_account_memory = _update_account_memory
_update_account_memory_inner = _update_account_memory_inner
_merge_positions_from_rest = _merge_positions_from_rest
_apply_broker_totals_from_summary = _apply_broker_totals_from_summary
_refresh_account_snapshot_meta = _refresh_account_snapshot_meta
_apply_last_price_to_positions = _apply_last_price_to_positions
_apply_balance_realtime = _apply_balance_realtime
_on_fill_after_ws = _on_fill_after_ws
_broadcast_account = _broadcast_account
_apply_delayed_account_broadcast = _apply_delayed_account_broadcast
_position_codes_with_qty = _position_codes_with_qty

# engine_config
get_settings_snapshot = get_settings_snapshot
refresh_engine_integrated_system_settings_cache = refresh_engine_integrated_system_settings_cache
reload_engine_settings = reload_engine_settings
_mask_sensitive_settings = _mask_sensitive_settings
get_connection_level_keys = get_connection_level_keys
TRADE_MODE_KEYS = TRADE_MODE_KEYS

# engine_radar
get_pending_stocks = get_pending_stocks
get_sector_stock_layout = get_sector_stock_layout
get_avg_amt_5d_map = get_avg_amt_5d_map
get_high_5d_cache = get_high_5d_cache
_overlay_radar_row_with_live_price = _overlay_radar_row_with_live_price
_apply_real01_volume_amount_to_radar_rows = _apply_real01_volume_amount_to_radar_rows
_mark_radar_exited = _mark_radar_exited
clear_exited_from_radar = clear_exited_from_radar
_drop_rest_radar_quote_for_nk = _drop_rest_radar_quote_for_nk
_clear_radar_rest_bootstrap_for_stk_cd = _clear_radar_rest_bootstrap_for_stk_cd
_clear_radar_and_ready_memory = _clear_radar_and_ready_memory
_tracked_ui_stock_codes = _tracked_ui_stock_codes

# engine_sector
get_sector_scores_snapshot = get_sector_scores_snapshot
recompute_sector_summary_now = recompute_sector_summary_now
get_sector_summary_inputs = get_sector_summary_inputs
get_sector_stocks = get_sector_stocks
get_all_sector_stocks = get_all_sector_stocks
# _compute_filtered_codes 제거: sector_stock_layout 의존성 제거

# engine_lifecycle
start_engine = start_engine
_engine_loop = _engine_loop
stop_engine = stop_engine
is_running = is_running
get_status = get_status
on_trade_mode_switched = on_trade_mode_switched
_try_sector_buy = _try_sector_buy
_log = _log
_now_kst = _now_kst
_schedule_engine_coro = _schedule_engine_coro
_sync_sell_overrides_from_settings = _sync_sell_overrides_from_settings
_broadcast_engine_ws = _broadcast_engine_ws
_delayed_resubscribe_stock_after_rate_limit = _delayed_resubscribe_stock_after_rate_limit
update_broker_credentials_live = update_broker_credentials_live

# engine_snapshot
build_initial_snapshot = build_initial_snapshot
build_sector_stocks_payload = build_sector_stocks_payload
_filter_stock_fields = _filter_stock_fields
_get_trade_history_for_snapshot = _get_trade_history_for_snapshot
_get_daily_summary_for_snapshot = _get_daily_summary_for_snapshot
_reset_realtime_fields = _reset_realtime_fields
_set_realtime_state = _set_realtime_state
_get_realtime_state = _get_realtime_state
# 실시간 호가잔량 기능 삭제로 export 제거 (_get_orderbook)
get_buy_targets_snapshot = get_buy_targets_snapshot
get_position_pnl_pct_for_code = get_position_pnl_pct_for_code


async def apply_settings_change(changed_keys: set[str]) -> None:
    """설정 변경 후 엔진 동기화 (settings_store.py에서 이관)"""
    from backend.app.services.engine_account_notify import (
        notify_desktop_header_refresh,
        notify_desktop_sector_scores,
        notify_desktop_settings_toggled,
    )
    from backend.app.services.engine_config import _mask_sensitive_settings
    from backend.app.services import settlement_engine as _se
    from backend.app.services import daily_time_scheduler as _dts
    from backend.app.services import ws_subscribe_control
    import backend.app.services.engine_state as _st

    if not changed_keys:
        notify_desktop_header_refresh()
        return

    # ── 1) RAM 캐시 갱신 — PATCH 저장 직후 DB 최신값을 캐시에 반영 ──────────────
    # [핵심] DB 저장 후 브로드캐스트 전에 반드시 캐시를 갱신해야 최신 값이 전송됨.
    # refresh_engine_integrated_system_settings_cache는 엔진 실행 여부와 무관하게 캐시를 갱신함.
    from backend.app.services.engine_config import refresh_engine_integrated_system_settings_cache
    await refresh_engine_integrated_system_settings_cache(None, use_root=True)

    # ── 2) 연결 레벨 키 → 엔진 실시간 핫-리로드 ───────────────────────────────────
    broker_nm = str(state.integrated_system_settings_cache.get("broker", "") or "").lower().strip()
    connection_keys = get_connection_level_keys(broker_nm)
    if changed_keys & connection_keys:
        if is_running():
            _schedule_engine_coro(update_broker_credentials_live(), "자격 증명 핫-갱신")
            logger.info(
                "[설정] 연결 레벨 설정 변경 감지 -> 실시간 자격 증명 핫-갱신 및 토큰 재시도 가동 (키=%s)",
                changed_keys & connection_keys,
            )
        notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
        return

    # ── 3) 거래모드 전환 → 캐시 갱신 + 계좌 구독 전환 ────────────────────
    if changed_keys & TRADE_MODE_KEYS:
        if is_running():
            _schedule_engine_coro(on_trade_mode_switched(), "거래모드 전환")
            logger.info("[설정] 거래모드 전환 감지 -> 저장데이터 갱신 + 계좌 구독 전환 (엔진 재기동 없음)")
        notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
        return

    # ── 4) 일반 설정 변경 (증분 브로드캐스트 전송) ────────────────────────
    notify_desktop_header_refresh()
    
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
            _s = state.integrated_system_settings_cache or {}
            _deposit = int(_s.get("test_virtual_balance", _s.get("test_virtual_deposit", 10_000_000)) or 0)
            await _se.reset(_deposit)
            # 계좌 스냅샷 갱신 + WS account-update 발송
            await _refresh_account_snapshot_meta()
            _broadcast_account(reason="virtual_balance_changed")
        except Exception:
            logger.warning("[설정] 가상 예수금 동기화 실패", exc_info=True)

    # 5일봉 다운로드 토글 ON 시 즉시 다운로드 트리거
    if "scheduler_5d_download_on" in changed_keys:
        _5d_on = bool(get_settings_snapshot().get("scheduler_5d_download_on", True))
        if _5d_on:
            try:
                state.avg_amt_needs_bg_refresh = True
                logger.info("[설정] scheduler_5d_download_on=ON → 5일봉 다운로드 트리거")
            except Exception:
                logger.warning("[설정] 5일봉 다운로드 트리거 실패", exc_info=True)

    # 자동매매 시간 관련 설정 변경 시 타이머 재예약 + KiwoomConnector 플래그 동기화
    _TIME_SCHEDULE_KEYS = {
        "time_scheduler_on", "auto_buy_on", "auto_sell_on",
        "buy_time_start", "buy_time_end", "sell_time_start", "sell_time_end",
    }
    if changed_keys & _TIME_SCHEDULE_KEYS:
        try:
            from backend.app.services.daily_time_scheduler import schedule_auto_trade_timers
            new_settings = get_settings_snapshot()
            await schedule_auto_trade_timers(new_settings)
            # KiwoomConnector 자동매매 플래그 동기화
            ws = getattr(state.kiwoom_connector, None)
            if ws and "time_scheduler_on" in changed_keys:
                ws.set_auto_trade_enabled(bool(new_settings.get("time_scheduler_on", True)))
        except Exception:
            pass

    # WS 구독 시간/스위치 변경 시 → 즉시 구간 재판정 + 타이머 재예약
    _WS_SCHEDULE_KEYS = {"ws_subscribe_start", "ws_subscribe_end", "ws_subscribe_on"}
    if changed_keys & _WS_SCHEDULE_KEYS:
        try:
            new_settings = get_settings_snapshot()
            now_in_window = await _dts.is_ws_subscribe_window(new_settings)
            was_active = bool(_dts._ws_subscribe_window_active)

            # 1) 타이머 재예약 (항상)
            await _dts.schedule_ws_subscribe_timers(new_settings)

            # 2) KiwoomConnector 실시간 연결 플래그 업데이트
            ws = getattr(state.kiwoom_connector, None)
            if ws:
                ws.set_realtime_enabled(bool(new_settings.get("ws_subscribe_on", True)))
                ws.set_holiday_block_enabled(bool(new_settings.get("holiday_guard_on", True)))

            # 3) 활성→구간밖: 즉시 구독 해제 + WS 끊기 (장마감 후처리 없이)
            if was_active and not now_in_window:
                logger.info("[설정] 실시간 구독 구간 변경 → 현재 구간 밖 — 즉시 구독 해제")
                _dts._fire_ws_disconnect_only()

            # 4) 비활성→구간안: 즉시 WS 연결 + 구독 시작
            elif not was_active and now_in_window:
                logger.info("[설정] 실시간 구독 구간 변경 → 현재 구간 안 — 즉시 구독 시작")
                _schedule_engine_coro(_dts._on_ws_subscribe_start(), "실시간 구독 시작")
        except Exception:
            pass

    # 공휴일 자동 차단 설정 변경 시 KiwoomConnector 플래그 업데이트
    if "holiday_guard_on" in changed_keys:
        try:
            ws = getattr(state.kiwoom_connector, None)
            if ws:
                new_settings = get_settings_snapshot()
                ws.set_holiday_block_enabled(bool(new_settings.get("holiday_guard_on", True)))
        except Exception:
            pass

    # 섹터 정렬/필터 관련 설정 변경 시 업종 점수만 재계산 (종목 시세는 WS delta로만 전송)
    _SECTOR_UI_KEYS = {
        "sector_sort_keys", "sector_rank_primary", "sector_weights",
        "sector_min_rise_ratio_pct", "sector_min_trade_amt",
        "sector_max_targets", "buy_block_rise_pct", "buy_block_fall_pct",
        "buy_min_strength",
        "sector_trim_trade_amt_pct", "sector_trim_change_rate_pct",
        # 가산점 설정
        "boost_high_breakout_on", "boost_high_breakout_score",
        "boost_order_ratio_on",
        "boost_order_ratio_pct", "boost_order_ratio_score",
    }
    if changed_keys & _SECTOR_UI_KEYS:
        if is_running():
            if "sector_min_trade_amt" in changed_keys:
                _schedule_engine_coro(
                    state.on_filter_settings_changed(), context="필터 설정 변경"
                )
            _schedule_engine_coro(
                recompute_sector_summary_now(), context="섹터 설정 변경"
            )
        notify_desktop_sector_scores(force=True)

    # WS 구독 제어 설정 변경 시 즉시 반영 (구독 시작/해지)
    _WS_SUBSCRIBE_CONTROL_KEYS = {"index_auto_subscribe", "quote_auto_subscribe"}
    _ws_changed = changed_keys & _WS_SUBSCRIBE_CONTROL_KEYS
    if _ws_changed:
        try:
            raw = state.integrated_system_settings_cache or {}
            for key in _ws_changed:
                _schedule_engine_coro(
                    ws_subscribe_control.on_setting_changed(key, bool(raw.get(key)), engine_service),
                    f"WS 구독 제어 설정 반영({key})",
                )
        except Exception:
            logger.warning("[설정] ws_subscribe_control 설정 변경 반영 실패", exc_info=True)
get_latest_trade_price_for_ui = get_latest_trade_price_for_ui
_run_snapshot_and_sell_check = _run_snapshot_and_sell_check


# ── 모듈 수준 동적 속성 위임 (호환성 유지 - PEP 562) ─────────────────────
def __getattr__(name: str):
    if name.startswith('_'):
        clean_name = name[1:]
        from backend.app.services.engine_state import state
        if hasattr(state, clean_name):
            return getattr(state, clean_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

