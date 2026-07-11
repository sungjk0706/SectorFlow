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
