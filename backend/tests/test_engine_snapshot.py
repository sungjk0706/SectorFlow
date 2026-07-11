"""engine_snapshot.py 단위 테스트 — 스냅샷/데이터 필터링/실시간 필드 초기화."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.engine_snapshot import (
    _filter_stock_fields,
    get_position_pnl_pct_for_code,
    _get_trade_history_for_snapshot,
    _get_daily_summary_for_snapshot,
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


# ── get_position_pnl_pct_for_code ───────────────────────────────────

class TestGetPositionPnlPctForCode:
    @pytest.mark.asyncio
    async def test_empty_code_returns_none(self):
        result = await get_position_pnl_pct_for_code("")
        assert result is None

    @pytest.mark.asyncio
    async def test_none_code_returns_none(self):
        result = await get_position_pnl_pct_for_code(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_test_mode_position_found(self):
        """테스트모드에서 dry_run 가상 잔고 조회."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=True), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.dry_run.get_position", new=AsyncMock(return_value={
                 "qty": 10, "pnl_rate": 5.5,
             })):
            mock_state.integrated_system_settings_cache = {"trade_mode": "test"}
            result = await get_position_pnl_pct_for_code("005930")
            assert result == 5.5

    @pytest.mark.asyncio
    async def test_test_mode_position_not_found(self):
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=True), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.dry_run.get_position", new=AsyncMock(return_value=None)):
            mock_state.integrated_system_settings_cache = {"trade_mode": "test"}
            result = await get_position_pnl_pct_for_code("005930")
            assert result is None

    @pytest.mark.asyncio
    async def test_test_mode_zero_qty(self):
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=True), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.dry_run.get_position", new=AsyncMock(return_value={
                 "qty": 0, "pnl_rate": 0.0,
             })):
            mock_state.integrated_system_settings_cache = {"trade_mode": "test"}
            result = await get_position_pnl_pct_for_code("005930")
            assert result is None

    @pytest.mark.asyncio
    async def test_real_mode_position_found(self):
        """실전모드에서 state.positions에서 조회."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", side_effect=lambda x: x):
            mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
            mock_state.positions = [
                {"stk_cd": "005930", "qty": 10, "pnl_rate": 3.2},
            ]
            result = await get_position_pnl_pct_for_code("005930")
            assert result == 3.2

    @pytest.mark.asyncio
    async def test_real_mode_position_not_found(self):
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", side_effect=lambda x: x):
            mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
            mock_state.positions = []
            result = await get_position_pnl_pct_for_code("005930")
            assert result is None

    @pytest.mark.asyncio
    async def test_real_mode_zero_qty(self):
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", side_effect=lambda x: x):
            mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
            mock_state.positions = [
                {"stk_cd": "005930", "qty": 0, "pnl_rate": 0.0},
            ]
            result = await get_position_pnl_pct_for_code("005930")
            assert result is None

    @pytest.mark.asyncio
    async def test_invalid_pnl_rate(self):
        """pnl_rate가 숫자가 아닌 경우 0.0 반환."""
        with patch("backend.app.services.engine_snapshot.state") as mock_state, \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", side_effect=lambda x: x):
            mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
            mock_state.positions = [
                {"stk_cd": "005930", "qty": 10, "pnl_rate": "invalid"},
            ]
            result = await get_position_pnl_pct_for_code("005930")
            assert result == 0.0


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
