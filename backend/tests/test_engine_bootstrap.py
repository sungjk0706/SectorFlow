"""engine_bootstrap.py 단위 테스트 — 엔진 부트스트랩 흐름."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.engine_bootstrap import (
    BOOTSTRAP_STAGES,
    _broadcast_bootstrap_stage,
    _deferred_sector_summary,
    _notify_close_data_ui,
    _run_sector_reg_pipeline,
    _login_post_pipeline,
)


# ── 공통 fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_db():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB not available"))
    with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield


# ── BOOTSTRAP_STAGES ────────────────────────────────────────────────

class TestBootstrapStages:
    def test_stages_count(self):
        assert len(BOOTSTRAP_STAGES) == 6

    def test_stages_ids(self):
        ids = [s[0] for s in BOOTSTRAP_STAGES]
        assert ids == [1, 2, 3, 4, 5, 6]

    def test_stage_names_not_empty(self):
        for _, name in BOOTSTRAP_STAGES:
            assert name
            assert isinstance(name, str)


# ── _broadcast_bootstrap_stage ──────────────────────────────────────

class TestBroadcastBootstrapStage:
    @pytest.mark.asyncio
    async def test_broadcast_success(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _broadcast_bootstrap_stage(1, "레이아웃 저장데이터 확인")
            mock_ws.broadcast.assert_called_once()
            call_args = mock_ws.broadcast.call_args
            assert call_args[0][0] == "bootstrap-stage"
            payload = call_args[0][1]
            assert payload["stage_id"] == 1
            assert payload["stage_name"] == "레이아웃 저장데이터 확인"
            assert payload["total"] == 6

    @pytest.mark.asyncio
    async def test_broadcast_with_progress(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _broadcast_bootstrap_stage(2, "업종 매핑 로드", progress={"current": 50})
            call_args = mock_ws.broadcast.call_args
            payload = call_args[0][1]
            assert payload["progress"] == {"current": 50}

    @pytest.mark.asyncio
    async def test_broadcast_exception_logged(self):
        """WS 브로드캐스트 실패 시 예외 로깅만 수행 (raise 아님)."""
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock(side_effect=Exception("WS error"))
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            # 예외가 raise되지 않음
            await _broadcast_bootstrap_stage(1, "테스트")


# ── _deferred_sector_summary ────────────────────────────────────────

class TestDeferredSectorSummary:
    @pytest.mark.asyncio
    async def test_no_codes_sets_event(self):
        """all_codes가 비어있으면 이벤트만 set."""
        with patch("backend.app.services.engine_bootstrap.state") as mock_state:
            mock_state.sector_summary_ready_event = MagicMock()
            with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                "all_codes": [], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {},
            })):
                await _deferred_sector_summary()
                mock_state.sector_summary_ready_event.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_codes_success(self):
        """all_codes가 있으면 재계산 수행."""
        mock_ss = MagicMock()
        mock_ss.sectors = []

        with patch("backend.app.services.engine_bootstrap.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_ss)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_ss), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.web.ws_manager.ws_manager") as mock_ws:
            mock_ws.client_count = 1
            mock_state.integrated_system_settings_cache = {
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 60.0,
                "sector_min_trade_amt": 0.0,
            }
            mock_state.auto_trade = None
            await _deferred_sector_summary()
            # sector_summary_cache 갱신 확인
            assert mock_state.sector_summary_cache == mock_ss

    @pytest.mark.asyncio
    async def test_exception_sets_event(self):
        """예외 발생 시에도 이벤트 set (대기 해제)."""
        with patch("backend.app.services.engine_bootstrap.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(side_effect=Exception("test error"))):
            mock_state.sector_summary_ready_event = MagicMock()
            await _deferred_sector_summary()
            mock_state.sector_summary_ready_event.set.assert_called_once()


# ── _notify_close_data_ui ───────────────────────────────────────────

class TestNotifyCloseDataUi:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch("backend.app.services.engine_account_notify.notify_desktop_buy_radar_only", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()):
            # 예외 없이 완료
            await _notify_close_data_ui()

    @pytest.mark.asyncio
    async def test_inner_exception_logged(self):
        """내부 notify 예외 시 로깅만 수행."""
        with patch("backend.app.services.engine_account_notify.notify_desktop_buy_radar_only", new=AsyncMock(side_effect=Exception("notify error"))), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()):
            # 예외가 raise되지 않음
            await _notify_close_data_ui()

    @pytest.mark.asyncio
    async def test_all_exceptions_logged(self):
        """모든 notify 예외 시에도 로깅만 수행."""
        with patch("backend.app.services.engine_account_notify.notify_desktop_buy_radar_only", new=AsyncMock(side_effect=Exception("error1"))), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock(side_effect=Exception("error2"))):
            await _notify_close_data_ui()


# ── _run_sector_reg_pipeline ────────────────────────────────────────

class TestRunSectorRegPipeline:
    @pytest.mark.asyncio
    async def test_delegates_to_engine_ws(self):
        with patch("backend.app.services.engine_ws._run_sector_reg_pipeline", new=AsyncMock()) as mock_reg:
            await _run_sector_reg_pipeline()
            mock_reg.assert_called_once()


# ── _deferred_sector_summary 보완 ───────────────────────────────────

class TestDeferredSectorSummaryExtended:
    @pytest.mark.asyncio
    async def test_with_auto_trade_not_none(self):
        """auto_trade가 None이 아닐 때 _bought_today 추출 확인 (L79-80)."""
        mock_ss = MagicMock()
        mock_ss.sectors = []

        mock_auto_trade = MagicMock()
        mock_auto_trade._bought_today = {"005930": 1, "000660": 2}

        with patch("backend.app.services.engine_bootstrap.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_ss)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_ss) as mock_build, \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.web.ws_manager.ws_manager") as mock_ws:
            mock_ws.client_count = 1
            mock_state.integrated_system_settings_cache = {
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 60.0,
                "sector_min_trade_amt": 0.0,
            }
            mock_state.auto_trade = mock_auto_trade
            await _deferred_sector_summary()
            call_kwargs = mock_build.call_args.kwargs
            assert call_kwargs["bought_today_codes"] == {"005930", "000660"}

    @pytest.mark.asyncio
    async def test_ui_broadcast_failure(self):
        """UI 전송 실패 시 에러 로깅만 수행 (raise 아님) (L105-106)."""
        mock_ss = MagicMock()
        mock_ss.sectors = []

        with patch("backend.app.services.engine_bootstrap.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {},
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_ss)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_ss), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock(side_effect=Exception("UI error"))), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()), \
             patch("backend.app.web.ws_manager.ws_manager") as mock_ws:
            mock_ws.client_count = 1
            mock_state.integrated_system_settings_cache = {
                "sector_trim_trade_amt_pct": 10.0,
                "sector_trim_change_rate_pct": 10.0,
                "sector_weights": {"rise_ratio": 0.5, "trade_amount": 0.5},
                "sector_min_rise_ratio_pct": 60.0,
                "sector_min_trade_amt": 0.0,
            }
            mock_state.auto_trade = None
            # 예외가 raise되지 않음
            await _deferred_sector_summary()
            # sector_summary_cache 갱신 확인
            assert mock_state.sector_summary_cache == mock_ss


# ── _notify_close_data_ui 보완 ──────────────────────────────────────

class TestNotifyCloseDataUiExtended:
    @pytest.mark.asyncio
    async def test_outer_exception(self):
        """외부 예외 (import 실패 등) 시 로깅만 수행 (L128-129)."""
        import sys
        parent = sys.modules.get("backend.app.services")
        saved = getattr(parent, "engine_account_notify", None)
        if parent is not None and hasattr(parent, "engine_account_notify"):
            delattr(parent, "engine_account_notify")
        try:
            with patch.dict(sys.modules, {"backend.app.services.engine_account_notify": None}):
                # 예외가 raise되지 않음
                await _notify_close_data_ui()
        finally:
            if saved is not None and parent is not None:
                setattr(parent, "engine_account_notify", saved)


# ── _login_post_pipeline ────────────────────────────────────────────

def _make_login_state_mock(**overrides):
    """_login_post_pipeline 테스트용 state mock 생성."""
    _state = MagicMock()
    _state.ws_reg_pipeline_done = MagicMock()
    _state.ws_reg_pipeline_done.clear = MagicMock()
    _state.ws_reg_pipeline_done.set = MagicMock()
    _state.integrated_system_settings_cache = {"test": True}
    _state.account_rest_bootstrapped = False
    _state.positions = {}
    _state.master_stocks_cache = {}
    _state.connector_manager = None
    _state.active_connector = None
    for k, v in overrides.items():
        setattr(_state, k, v)
    return _state


class TestLoginPostPipeline:
    @pytest.mark.asyncio
    async def test_test_mode_skips_rest(self):
        """test_mode인 경우 REST 잔고 조회 생략 (L148-149)."""
        mock_state = _make_login_state_mock()
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=False)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=True), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()) as mock_update, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()):
            await _login_post_pipeline()
            mock_update.assert_not_called()
            mock_state.ws_reg_pipeline_done.set.assert_called_once()
            mock_refresh.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_non_ws_window_not_bootstrapped_rest(self):
        """비 WS 윈도우 + 미부트스트랩 → REST 잔고 조회 (L150-155)."""
        mock_state = _make_login_state_mock(account_rest_bootstrapped=False, positions={})
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=False)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()) as mock_update, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()):
            await _login_post_pipeline()
            mock_update.assert_called_once_with(mock_state.integrated_system_settings_cache)
            mock_state.ws_reg_pipeline_done.set.assert_called_once()
            mock_refresh.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_non_ws_window_bootstrapped_skip(self):
        """비 WS 윈도우 + 부트스트랩 완료 → 재조회 생략 (L156-157)."""
        mock_state = _make_login_state_mock(account_rest_bootstrapped=True, positions={"005930": {}})
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=False)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()) as mock_update, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()):
            await _login_post_pipeline()
            mock_update.assert_not_called()
            mock_state.ws_reg_pipeline_done.set.assert_called_once()
            mock_refresh.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_ws_window_no_positions_rest(self):
        """WS 윈도우 + 잔고없음 + 미부트스트랩 → REST 조회 (L158-161)."""
        mock_state = _make_login_state_mock(account_rest_bootstrapped=False, positions={})
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=True)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()) as mock_update, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()) as mock_stocks_refresh:
            await _login_post_pipeline()
            mock_update.assert_called_once_with(mock_state.integrated_system_settings_cache)
            # WS 윈도우이므로 ws_reg_pipeline_done.set 호출 안함
            mock_state.ws_reg_pipeline_done.set.assert_not_called()
            mock_refresh.assert_called_once_with()
            mock_stocks_refresh.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_stale_subscription_cleanup(self):
        """stale 구독 상태 초기화 확인 (L163-169)."""
        mock_state = _make_login_state_mock(
            master_stocks_cache={
                "005930": {"_subscribed": True, "price": 100},
                "000660": {"_subscribed": False, "price": 200},
                "035420": {"_subscribed": True, "price": 300},
            },
        )
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=False)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()):
            await _login_post_pipeline()
            # _subscribed=True 인 두 종목에서 _subscribed 키 제거 확인
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]
            assert "_subscribed" not in mock_state.master_stocks_cache["035420"]
            # _subscribed=False 인 종목은 변경 없음
            assert mock_state.master_stocks_cache["000660"]["price"] == 200

    @pytest.mark.asyncio
    async def test_ws_window_connected_recompute_reg(self):
        """WS 윈도우 + ws 연결 → recompute + reg pipeline (L174-182)."""
        mock_connector = MagicMock()
        mock_connector.is_connected.return_value = True
        mock_state = _make_login_state_mock(
            positions={"005930": {}},
            account_rest_bootstrapped=True,
            connector_manager=mock_connector,
        )
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()) as mock_recompute, \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=True)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()) as mock_update, \
             patch("backend.app.services.engine_ws._run_sector_reg_pipeline", new=AsyncMock()) as mock_reg, \
             patch("backend.app.services.engine_ws._ensure_ws_subscriptions_for_positions", new=AsyncMock()) as mock_ensure, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()) as mock_stocks_refresh:
            await _login_post_pipeline()
            mock_recompute.assert_called_once()
            mock_reg.assert_called_once()
            mock_ensure.assert_called_once()
            mock_update.assert_not_called()
            mock_state.ws_reg_pipeline_done.set.assert_not_called()
            mock_refresh.assert_called_once_with()
            mock_stocks_refresh.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_ws_window_not_connected_notify(self):
        """WS 윈도우 + ws 미연결 → notify만 (L184-185)."""
        mock_connector = MagicMock()
        mock_connector.is_connected.return_value = False
        mock_state = _make_login_state_mock(
            positions={"005930": {}},
            account_rest_bootstrapped=True,
            connector_manager=mock_connector,
        )
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()) as mock_recompute, \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=True)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._run_sector_reg_pipeline", new=AsyncMock()) as mock_reg, \
             patch("backend.app.services.engine_ws._ensure_ws_subscriptions_for_positions", new=AsyncMock()) as mock_ensure, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()) as mock_stocks_refresh:
            await _login_post_pipeline()
            mock_recompute.assert_not_called()
            mock_reg.assert_not_called()
            mock_ensure.assert_not_called()
            mock_state.ws_reg_pipeline_done.set.assert_not_called()
            mock_refresh.assert_called_once_with()
            mock_stocks_refresh.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_non_ws_window_sets_event(self):
        """비 WS 윈도우 → ws_reg_pipeline_done.set 호출 (L186-189)."""
        mock_state = _make_login_state_mock(account_rest_bootstrapped=True, positions={"005930": {}})
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock()), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=False)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()) as mock_stocks_refresh:
            await _login_post_pipeline()
            mock_state.ws_reg_pipeline_done.set.assert_called_once()
            mock_refresh.assert_called_once_with(force=True)
            mock_stocks_refresh.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_exception_handler(self):
        """전체 예외 핸들러 확인 (L190-191) — 예외 발생 시 로깅만 수행 (raise 아님)."""
        mock_state = _make_login_state_mock()
        with patch("backend.app.services.engine_bootstrap.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock(side_effect=Exception("pipeline error"))), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=False)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()):
            # 예외가 raise되지 않음
            await _login_post_pipeline()
