"""engine_bootstrap.py 단위 테스트 — 엔진 부트스트랩 흐름."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.engine_bootstrap import (
    _login_post_pipeline,
)


# ── 공통 fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_db():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB not available"))
    with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield

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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()), \
             patch("backend.app.services.engine_ws._cleanup_stale_ws_subscriptions_on_session_ready", new=AsyncMock(side_effect=Exception("pipeline error"))), \
             patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new=AsyncMock(return_value=False)), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account._update_account_memory", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()):
            # 예외가 raise되지 않음
            await _login_post_pipeline()
