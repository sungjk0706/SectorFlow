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
from backend.app.services.engine_utils import LRUCache, LazyLock, LazyEvent
from backend.app.services.state_manager import StateManager, OrderStatus

# ── 전역 상태 import (engine_state에서 직접 import) ─────────────────────
from backend.app.services.engine_state import (
    _state_manager,
    _running,
    _connector_manager,
    _kiwoom_connector,
    _broker_tokens,
    _engine_task,
    _engine_loop_ref,
    _access_token,
    _login_ok,
    _checked_stocks,
    _engine_user_id,
    _last_ws_limit_warn_ts,
    _realtime_latency_exceeded,
    _shared_lock,
    _realtime_state,
    _data_ready_event,
    _token_ready_event,
    _ws_reg_pipeline_done,
    _bootstrap_event,
    _sector_summary_ready_event,
    _engine_ready_event,
    _server_ready_event,
    _preboot_cache_loaded,
    _preboot_ready_event,
    _engine_stop_event,
    _reg_seq_lock,
    _reg_ack_event,
    _reg_ack_return_code,
    _rest_api_thread_sem,
    _account_rest_lock,
    # _pending_stock_details 제거
    _radar_cnsr_order,
    _sector_stock_layout,
    _amts_5d_arrays,
    _highs_5d_arrays,
    _subscribed_0d_stocks,
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_latest_trade_prices, _latest_trade_amounts)
    _sector_dirty_codes,
    _filtered_sector_codes,
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_latest_strength)
    _sector_stocks_cache,
    _sector_stocks_dirty,
    _sector_stocks_last_invalidated,
    _MIN_CACHE_LIFETIME_SEC,
    _buy_targets_snapshot_cache,
    _buy_targets_cache_ref,
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_rest_radar_quote_cache)
    _rest_radar_rest_once,
    _sector_summary_cache,
    _sector_buy_last_ts,
    _stock_rising_state,
    _sector_score_index,
    _confirmed_refresh_running,
    _confirmed_refresh_message,
    _latest_filter_summary,
    _ws_account_subscribed,
    _account_rest_bootstrapped,
    _broker_rest_totals,
    _latest_stock_info,
    _auto_trade,
    _settings_cache,
    _subscribed_stocks,
    _broker_spec,
    _rest_api,
    _account_snapshot,
    _positions,
    _snapshot_history,
    _REG_POST_ACK_GAP_SEC,
    _REG_RATE_LIMIT_RESUB_SEC,
    _REG_STOCK_LOG_CHUNK_SIZE,
    _REG_REAL_DEBUG_EXTRA_LOG,
    _AVG_AMT_CHUNK_SIZE,
    _INDUSTRY_CHUNK_SIZE,
    _ACCOUNT_BROADCAST_COALESCE_SEC,
    _account_broadcast_pending_reason,
    _account_broadcast_timer,
    _get_rest_api_thread_sem,
    _get_account_rest_lock,
    _get_realtime_state,
    _set_realtime_state,
    _on_filter_settings_changed,
    _cancel_price_trace_delayed_task,
)

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
    refresh_engine_settings_cache,
    reload_engine_settings,
    _mask_sensitive_settings,
    get_connection_level_keys,
    TRADE_MODE_KEYS,
)
from backend.app.services.engine_radar import (
    get_pending_stocks,
    get_sector_stock_layout,
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
    _invalidate_sector_stocks_cache,
    _on_filter_settings_changed as _sector_on_filter_settings_changed,
    _compute_filtered_codes,
    _update_avg_amt_5d,
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
_get_settings = _get_settings
get_settings_snapshot = get_settings_snapshot
refresh_engine_settings_cache = refresh_engine_settings_cache
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
_compute_filtered_codes = _compute_filtered_codes
_update_avg_amt_5d = _update_avg_amt_5d

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
get_latest_trade_price_for_ui = get_latest_trade_price_for_ui
_run_snapshot_and_sell_check = _run_snapshot_and_sell_check
_token_ready_event = _token_ready_event
