"""engine_snapshot.py 단위 테스트 — 스냅샷/데이터 필터링/실시간 필드 초기화."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.engine_snapshot import (
    _filter_stock_fields,
    _get_trade_history_for_snapshot,
    _get_daily_summary_for_snapshot,
    build_initial_snapshot,
    build_sector_stocks_payload,
    _reset_realtime_fields,
)


# ── 공통 fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_db():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB not available"))
    with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield


# ── _filter_stock_fields ────────────────────────────────────────────

class TestFilterStockFields:
    def test_filters_to_allowed_fields(self):
        stocks = [
            {"code": "005930", "name": "삼성전자", "cur_price": 70000, "change": 500,
             "change_rate": 0.72, "strength": 80, "trade_amount": 100000,
             "sector": "반도체", "avg_amt_5d": 50000, "market_type": "코스피",
             "nxt_enable": True, "extra_field": "removed"},
        ]
        result = _filter_stock_fields(stocks)
        assert len(result) == 1
        assert result[0]["code"] == "005930"
        assert result[0]["name"] == "삼성전자"
        assert result[0]["cur_price"] == 70000
        assert "extra_field" not in result[0]

    def test_empty_list(self):
        assert _filter_stock_fields([]) == []

    def test_multiple_stocks(self):
        stocks = [
            {"code": "005930", "name": "삼성전자", "cur_price": 70000},
            {"code": "005935", "name": "삼성전자우", "cur_price": 60000},
        ]
        result = _filter_stock_fields(stocks)
        assert len(result) == 2
        assert result[0]["code"] == "005930"
        assert result[1]["code"] == "005935"

    def test_missing_fields(self):
        """필수 필드가 없어도 에러 없이 처리."""
        stocks = [{"code": "005930"}]
        result = _filter_stock_fields(stocks)
        assert len(result) == 1
        assert result[0]["code"] == "005930"
        assert "name" not in result[0]

    def test_all_allowed_fields_preserved(self):
        """허용된 필드가 모두 보존되는지 확인."""
        stocks = [{
            "code": "005930", "name": "삼성전자", "cur_price": 70000, "change": 500,
            "change_rate": 0.72, "strength": 80, "trade_amount": 100000,
            "sector": "반도체", "avg_amt_5d": 50000, "market_type": "코스피",
            "nxt_enable": True,
        }]
        result = _filter_stock_fields(stocks)
        assert set(result[0].keys()) == {
            "code", "name", "cur_price", "change", "change_rate", "strength",
            "trade_amount", "sector", "avg_amt_5d", "market_type", "nxt_enable",
        }


# ── _get_trade_history_for_snapshot ─────────────────────────────────

class TestGetTradeHistoryForSnapshot:
    @pytest.mark.asyncio
    async def test_sell_history(self):
        with patch("backend.app.services.engine_account.get_trade_mode", return_value="test"), \
             patch("backend.app.services.trade_history.get_sell_history", new=AsyncMock(return_value=[
                 {"stk_cd": "005930", "side": "sell"},
             ])):
            result = await _get_trade_history_for_snapshot("sell")
            assert len(result) == 1
            assert result[0]["stk_cd"] == "005930"

    @pytest.mark.asyncio
    async def test_buy_history(self):
        with patch("backend.app.services.engine_account.get_trade_mode", return_value="test"), \
             patch("backend.app.services.trade_history.get_buy_history", new=AsyncMock(return_value=[
                 {"stk_cd": "005930", "side": "buy"},
             ])):
            result = await _get_trade_history_for_snapshot("buy")
            assert len(result) == 1
            assert result[0]["stk_cd"] == "005930"


# ── _get_daily_summary_for_snapshot ─────────────────────────────────

class TestGetDailySummaryForSnapshot:
    @pytest.mark.asyncio
    async def test_returns_summary(self):
        with patch("backend.app.services.engine_account.get_trade_mode", return_value="test"), \
             patch("backend.app.services.trade_history.get_daily_summary", new=AsyncMock(return_value=[
                 {"date": "2024-01-01", "pnl": 10000},
             ])):
            result = await _get_daily_summary_for_snapshot()
            assert len(result) == 1
            assert result[0]["date"] == "2024-01-01"


# ── build_initial_snapshot ─────────────────────────────────────────

class TestBuildInitialSnapshot:
    """build_initial_snapshot — WS 연결 시 메타 상태 스냅샷 조립 (L20-90)."""

    @pytest.fixture(autouse=True)
    def _mock_pipeline_compute(self):
        """pipeline_compute 모듈 import 시 broadcast_queue 초기화 에러 방지."""
        mock_mod = MagicMock()
        mock_mod.get_current_receive_rate = MagicMock(return_value={
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        })
        with patch.dict("sys.modules", {"backend.app.pipelines.pipeline_compute": mock_mod}):
            yield mock_mod

    @pytest.mark.asyncio
    async def test_happy_path(self, _mock_pipeline_compute):
        """모든 getter 정상 반환 — 스냅샷 dict 조립 확인."""
        _mock_pipeline_compute.get_current_receive_rate.return_value = {
            "krx": {"received": 8, "total": 10, "pct": 80.0},
            "nxt": {"received": 4, "total": 5, "pct": 80.0},
        }
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=[{"stk_cd": "005930"}])), \
             patch("backend.app.services.engine_account.get_account_snapshot", new=AsyncMock(return_value={"balance": 100000})), \
             patch("backend.app.services.engine_account.get_snapshot_history", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_buy_limit_status", new=AsyncMock(return_value={"daily_buy_spent": 5000})), \
             patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()), \
             patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", new=AsyncMock(return_value=([{"sector": "반도체"}], 3))), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={"masked": True}), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value="running"), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value="open"), \
             patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={"subscribed": True}), \
             patch("backend.app.services.engine_account_notify.init_sent_caches") as mock_init, \
             patch("backend.app.services.engine_snapshot._get_trade_history_for_snapshot", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_snapshot._get_daily_summary_for_snapshot", new=AsyncMock(return_value=[])):
            mock_state.master_stocks_cache = {"005930": {}, "005935": {}}
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5, "broker_config": {"name": "test_broker"}}
            mock_state.bootstrap_event = MagicMock()
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.preboot_cache_loaded = False

            result = await build_initial_snapshot()

            assert result["_v"] == 1
            assert result["account"] == {"balance": 100000}
            assert result["positions"] == [{"stk_cd": "005930"}]
            assert result["sector_stocks"] == []
            assert result["sector_scores"] == [{"sector": "반도체"}]
            assert result["sector_status"] == {"total_stocks": 2, "max_targets": 5, "ranked_sectors_count": 3}
            assert result["settings"] == {"masked": True}
            assert result["status"] == "running"
            assert result["market_phase"] == "open"
            assert result["receive_rate"] == {
                "krx": {"received": 8, "total": 10, "pct": 80.0},
                "nxt": {"received": 4, "total": 5, "pct": 80.0},
            }
            assert result["broker_config"] == {"name": "test_broker"}
            assert result["avg_amt_refresh"] is None
            assert result["bootstrap_done"] is True
            mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_getter_exception_returns_default(self):
        """getter 예외 시 _safe 래퍼가 기본값 반환."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.engine_account.get_account_snapshot", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.engine_account.get_snapshot_history", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.engine_account.get_buy_limit_status", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={"masked": True}), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value="running"), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value="open"), \
             patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={"subscribed": True}), \
             patch("backend.app.services.engine_account_notify.init_sent_caches"), \
             patch("backend.app.services.engine_snapshot._get_trade_history_for_snapshot", new=AsyncMock(side_effect=Exception("fail"))), \
             patch("backend.app.services.engine_snapshot._get_daily_summary_for_snapshot", new=AsyncMock(side_effect=Exception("fail"))):
            mock_state.master_stocks_cache = {}
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 3, "broker_config": {}}
            mock_state.bootstrap_event = MagicMock()
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.preboot_cache_loaded = False

            result = await build_initial_snapshot()

            assert result["positions"] == []
            assert result["account"] == {}
            assert result["sector_scores"] == []
            assert result["sector_status"]["ranked_sectors_count"] == 0
            assert result["buy_targets"] == []
            assert result["snapshot_history"] == []
            assert result["sell_history"] == []
            assert result["buy_history"] == []
            assert result["daily_summary"] == []
            assert result["buy_limit_status"] == {"daily_buy_spent": 0}

    @pytest.mark.asyncio
    async def test_scores_non_tuple(self):
        """get_sector_scores_snapshot이 tuple이 아닌 경우 (scores_list, 0) 분기 (L55)."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_account_snapshot", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account.get_snapshot_history", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_buy_limit_status", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()), \
             patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", new=AsyncMock(return_value=[{"sector": "반도체"}])), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={}), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value="running"), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value="closed"), \
             patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={}), \
             patch("backend.app.services.engine_account_notify.init_sent_caches"), \
             patch("backend.app.services.engine_snapshot._get_trade_history_for_snapshot", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_snapshot._get_daily_summary_for_snapshot", new=AsyncMock(return_value=[])):
            mock_state.master_stocks_cache = {"005930": {}}
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5, "broker_config": {}}
            mock_state.bootstrap_event = MagicMock()
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.preboot_cache_loaded = False

            result = await build_initial_snapshot()

            assert result["sector_scores"] == [{"sector": "반도체"}]
            assert result["sector_status"]["ranked_sectors_count"] == 0

    @pytest.mark.asyncio
    async def test_bootstrap_event_none(self):
        """bootstrap_event가 None인 경우 preboot_cache_loaded 사용 (L76)."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_account_snapshot", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account.get_snapshot_history", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_buy_limit_status", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()), \
             patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", new=AsyncMock(return_value=([], 0))), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={}), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value="running"), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value="closed"), \
             patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={}), \
             patch("backend.app.services.engine_account_notify.init_sent_caches"), \
             patch("backend.app.services.engine_snapshot._get_trade_history_for_snapshot", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_snapshot._get_daily_summary_for_snapshot", new=AsyncMock(return_value=[])):
            mock_state.master_stocks_cache = {}
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5, "broker_config": {}}
            mock_state.bootstrap_event = None
            mock_state.preboot_cache_loaded = True

            result = await build_initial_snapshot()

            assert result["bootstrap_done"] is True

    @pytest.mark.asyncio
    async def test_init_sent_caches_exception(self):
        """init_sent_caches 예외 시 로깅만 수행, 스냅샷 정상 반환 (L87-88)."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_account_snapshot", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account.get_snapshot_history", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_buy_limit_status", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()), \
             patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", new=AsyncMock(return_value=([], 0))), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_config._mask_sensitive_settings", return_value={}), \
             patch("backend.app.services.engine_lifecycle.get_engine_status", return_value="running"), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value="closed"), \
             patch("backend.app.services.ws_subscribe_control.get_subscribe_status", return_value={}), \
             patch("backend.app.services.engine_account_notify.init_sent_caches", side_effect=Exception("init fail")), \
             patch("backend.app.services.engine_snapshot._get_trade_history_for_snapshot", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_snapshot._get_daily_summary_for_snapshot", new=AsyncMock(return_value=[])):
            mock_state.master_stocks_cache = {}
            mock_state.integrated_system_settings_cache = {"sector_max_targets": 5, "broker_config": {}}
            mock_state.bootstrap_event = MagicMock()
            mock_state.bootstrap_event.is_set.return_value = True
            mock_state.preboot_cache_loaded = False

            result = await build_initial_snapshot()
            assert result["_v"] == 1


# ── build_sector_stocks_payload ────────────────────────────────────

class TestBuildSectorStocksPayload:
    """build_sector_stocks_payload — sector-stocks-refresh 페이로드 조립 (L93-108)."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        stocks = [{"code": "005930", "name": "삼성전자", "cur_price": 70000, "extra": "removed"}]
        with patch("backend.app.services.sector_data_provider.get_sector_stocks", new=AsyncMock(return_value=stocks)), \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_account_snapshot", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account_notify.init_sent_caches") as mock_init:
            result = await build_sector_stocks_payload()
            assert result["_v"] == 1
            assert len(result["stocks"]) == 1
            assert result["stocks"][0]["code"] == "005930"
            assert "extra" not in result["stocks"][0]
            mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_sent_caches_exception(self):
        """init_sent_caches 예외 시 로깅만 수행, 페이로드 정상 반환 (L106-107)."""
        with patch("backend.app.services.sector_data_provider.get_sector_stocks", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=[])), \
             patch("backend.app.services.engine_account.get_account_snapshot", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_account_notify.init_sent_caches", side_effect=Exception("init fail")):
            result = await build_sector_stocks_payload()
            assert result["_v"] == 1
            assert result["stocks"] == []


# ── _reset_realtime_fields ─────────────────────────────────────────

class TestResetRealtimeFields:
    """_reset_realtime_fields — WS 구독 시작 시 실시간 필드 초기화 (L149-208)."""

    @pytest.mark.asyncio
    async def test_non_test_mode(self):
        """실전모드 — master_stocks_cache, positions 필드 초기화 + notify 호출."""
        master_cache = {
            "005930": {"code": "005930", "cur_price": 70000, "change": 500, "change_rate": 0.72,
                       "trade_amount": 100000, "strength": 80, "name": "삼성전자"},
        }
        positions = [
            {"stk_cd": "005930", "cur_price": 70000, "change": 500, "change_rate": 0.72,
             "bid_depth": 100, "ask_depth": 200},
        ]
        mock_notify_cache = MagicMock()
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account_notify.notify_cache", mock_notify_cache), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()) as mock_notify_refresh, \
             patch("backend.app.services.engine_account_notify._broadcast", new=AsyncMock()) as mock_broadcast, \
             patch("backend.app.services.engine_account._broadcast_account", new=AsyncMock()) as mock_broadcast_account, \
             patch("backend.app.db.database.get_db_lock") as mock_get_lock, \
             patch("backend.app.db.database.get_db_connection", new=AsyncMock()) as mock_get_conn:
            mock_lock = AsyncMock()
            mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
            mock_lock.__aexit__ = AsyncMock(return_value=None)
            mock_get_lock.return_value = mock_lock
            mock_conn = AsyncMock()
            mock_get_conn.return_value = mock_conn

            mock_state.master_stocks_cache = master_cache
            mock_state.snapshot_history = MagicMock()
            mock_state.positions = positions
            mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
            mock_state.sector_summary_cache = MagicMock()

            await _reset_realtime_fields()

            assert master_cache["005930"]["cur_price"] is None
            assert master_cache["005930"]["change"] is None
            assert master_cache["005930"]["change_rate"] is None
            assert master_cache["005930"]["trade_amount"] is None
            assert master_cache["005930"]["strength"] is None
            assert positions[0]["cur_price"] is None
            assert positions[0]["change"] is None
            assert positions[0]["change_rate"] is None
            assert positions[0]["bid_depth"] is None
            assert positions[0]["ask_depth"] is None
            mock_state.snapshot_history.clear.assert_called_once()
            assert mock_state.sector_summary_cache is None
            mock_notify_cache.clear_all.assert_called_once()
            mock_conn.execute.assert_called_once()
            mock_conn.commit.assert_called_once()
            mock_notify_refresh.assert_called_once()
            mock_broadcast_account.assert_called_once_with("realtime_reset")
            mock_broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_test_mode_resets_dry_run_positions(self):
        """테스트모드 — dry_run._test_positions도 초기화 (L173-179)."""
        master_cache = {"005930": {"cur_price": 70000, "change": 500, "change_rate": 0.72,
                                    "trade_amount": 100000, "strength": 80}}
        test_positions = {
            "005930": {"cur_price": 70000, "change": 500, "change_rate": 0.72,
                       "bid_depth": 100, "ask_depth": 200},
        }
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run._test_positions", test_positions), \
             patch("backend.app.services.engine_account_notify.notify_cache", MagicMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify._broadcast", new=AsyncMock()), \
             patch("backend.app.services.engine_account._broadcast_account", new=AsyncMock()), \
             patch("backend.app.db.database.get_db_lock") as mock_get_lock, \
             patch("backend.app.db.database.get_db_connection", new=AsyncMock()):
            mock_lock = AsyncMock()
            mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
            mock_lock.__aexit__ = AsyncMock(return_value=None)
            mock_get_lock.return_value = mock_lock

            mock_state.master_stocks_cache = master_cache
            mock_state.snapshot_history = MagicMock()
            mock_state.positions = []
            mock_state.integrated_system_settings_cache = {"trade_mode": "test"}
            mock_state.sector_summary_cache = MagicMock()

            await _reset_realtime_fields()

            assert test_positions["005930"]["cur_price"] is None
            assert test_positions["005930"]["change"] is None
            assert test_positions["005930"]["change_rate"] is None
            assert test_positions["005930"]["bid_depth"] is None
            assert test_positions["005930"]["ask_depth"] is None

    @pytest.mark.asyncio
    async def test_db_exception_still_notifies(self):
        """DB 초기화 실패 시에도 notify 호출 수행 (L200-201)."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account_notify.notify_cache", MagicMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()) as mock_notify_refresh, \
             patch("backend.app.services.engine_account_notify._broadcast", new=AsyncMock()) as mock_broadcast, \
             patch("backend.app.services.engine_account._broadcast_account", new=AsyncMock()) as mock_broadcast_account, \
             patch("backend.app.db.database.get_db_lock") as mock_get_lock, \
             patch("backend.app.db.database.get_db_connection", new=AsyncMock(side_effect=Exception("DB fail"))):
            mock_lock = AsyncMock()
            mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
            mock_lock.__aexit__ = AsyncMock(return_value=None)
            mock_get_lock.return_value = mock_lock

            mock_state.master_stocks_cache = {}
            mock_state.snapshot_history = MagicMock()
            mock_state.positions = []
            mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
            mock_state.sector_summary_cache = None

            await _reset_realtime_fields()

            mock_notify_refresh.assert_called_once()
            mock_broadcast_account.assert_called_once()
            mock_broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_master_cache(self):
        """master_stocks_cache가 빈 경우에도 정상 동작."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account_notify.notify_cache", MagicMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify._broadcast", new=AsyncMock()), \
             patch("backend.app.services.engine_account._broadcast_account", new=AsyncMock()), \
             patch("backend.app.db.database.get_db_lock") as mock_get_lock, \
             patch("backend.app.db.database.get_db_connection", new=AsyncMock()):
            mock_lock = AsyncMock()
            mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
            mock_lock.__aexit__ = AsyncMock(return_value=None)
            mock_get_lock.return_value = mock_lock

            mock_state.master_stocks_cache = {}
            mock_state.snapshot_history = MagicMock()
            mock_state.positions = []
            mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
            mock_state.sector_summary_cache = None

            await _reset_realtime_fields()
            assert mock_state.sector_summary_cache is None
