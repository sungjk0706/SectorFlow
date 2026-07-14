"""sector_data_provider.py 단위 테스트 — 업종 데이터 제공자."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.sector_data_provider import (
    get_sector_summary_inputs,
    get_sector_stocks,
    get_buy_targets_sector_stocks,
    get_all_sector_stocks,
    get_sector_scores_snapshot,
    recompute_sector_summary_now,
    _on_filter_settings_changed,
)


# ── 공통 fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_db():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB not available"))
    with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield


# ── get_sector_scores_snapshot ──────────────────────────────────────

class TestGetSectorScoresSnapshot:
    def test_no_cache_returns_empty(self):
        with patch("backend.app.services.sector_data_provider.state") as mock_state:
            mock_state.sector_summary_cache = None
            result = get_sector_scores_snapshot()
            assert result == ([], 0)

    def test_with_cache(self):
        mock_sc = MagicMock()
        mock_sc.rank = 1
        mock_sc.sector = "반도체"
        mock_sc.final_score = 85.5
        mock_sc.rise_ratio = 0.65
        mock_sc.total = 10

        mock_ss = MagicMock()
        mock_ss.sectors = [mock_sc]

        with patch("backend.app.services.sector_data_provider.state") as mock_state:
            mock_state.sector_summary_cache = mock_ss
            scores, ranked_count = get_sector_scores_snapshot()
            assert len(scores) == 1
            assert scores[0]["sector"] == "반도체"
            assert scores[0]["rank"] == 1
            assert scores[0]["final_score"] == 85.5
            assert ranked_count == 1

    def test_unranked_sectors_not_counted(self):
        """rank=0인 업종은 ranked_count에서 제외."""
        mock_sc1 = MagicMock()
        mock_sc1.rank = 1
        mock_sc1.sector = "반도체"
        mock_sc1.final_score = 85.5
        mock_sc1.rise_ratio = 0.65
        mock_sc1.total = 10

        mock_sc2 = MagicMock()
        mock_sc2.rank = 0
        mock_sc2.sector = "미분류"
        mock_sc2.final_score = 30.0
        mock_sc2.rise_ratio = 0.3
        mock_sc2.total = 5

        mock_ss = MagicMock()
        mock_ss.sectors = [mock_sc1, mock_sc2]

        with patch("backend.app.services.sector_data_provider.state") as mock_state:
            mock_state.sector_summary_cache = mock_ss
            scores, ranked_count = get_sector_scores_snapshot()
            assert len(scores) == 2
            assert ranked_count == 1


# ── get_buy_targets_sector_stocks ───────────────────────────────────

class TestGetBuyTargetsSectorStocks:
    @pytest.mark.asyncio
    async def test_no_cache_returns_empty(self):
        with patch("backend.app.services.sector_data_provider.state") as mock_state:
            mock_state.sector_summary_cache = None
            result = await get_buy_targets_sector_stocks()
            assert result == []

    @pytest.mark.asyncio
    async def test_with_buy_targets(self):
        """buy_targets + blocked_targets 통합 반환."""
        mock_stock = MagicMock()
        mock_stock.code = "005930"
        mock_stock.name = "삼성전자"
        mock_stock.avg_amt_5d = 50000
        mock_stock.market_type = "코스피"
        mock_stock.nxt_enable = True
        mock_stock.sector = "반도체"
        mock_stock.guard_pass = True
        mock_stock.boost_score = 1.5
        mock_stock.trade_amount_rank = 1

        mock_bt = MagicMock()
        mock_bt.stock = mock_stock
        mock_bt.rank = 1
        mock_bt.reason = "상승률 상위"

        mock_ss = MagicMock()
        mock_ss.buy_targets = [mock_bt]
        mock_ss.blocked_targets = []

        with patch("backend.app.services.sector_data_provider.state") as mock_state:
            mock_state.sector_summary_cache = mock_ss
            mock_state.master_stocks_cache = {
                "005930": {"cur_price": 70000, "change_rate": 0.5, "change": 350,
                           "strength": 80, "trade_amount": 100000, "high_5d_price": 71000,
                           "order_ratio": 0.3, "program_net_buy": 1000}
            }
            result = await get_buy_targets_sector_stocks()
            assert len(result) == 1
            assert result[0]["code"] == "005930"
            assert result[0]["guard_pass"] is True
            assert result[0]["cur_price"] == 70000
            assert result[0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_with_blocked_targets(self):
        """blocked_targets (guard_pass=False) 포함."""
        mock_stock = MagicMock()
        mock_stock.code = "005935"
        mock_stock.name = "삼성전자우"
        mock_stock.avg_amt_5d = 5000
        mock_stock.market_type = "코스피"
        mock_stock.nxt_enable = False
        mock_stock.sector = "반도체"
        mock_stock.guard_pass = False
        mock_stock.boost_score = 0
        mock_stock.trade_amount_rank = 5

        mock_bt = MagicMock()
        mock_bt.stock = mock_stock
        mock_bt.rank = 0
        mock_bt.reason = "상승률 미달"

        mock_ss = MagicMock()
        mock_ss.buy_targets = []
        mock_ss.blocked_targets = [mock_bt]

        with patch("backend.app.services.sector_data_provider.state") as mock_state:
            mock_state.sector_summary_cache = mock_ss
            mock_state.master_stocks_cache = {"005935": {}}
            result = await get_buy_targets_sector_stocks()
            assert len(result) == 1
            assert result[0]["guard_pass"] is False


# ── get_all_sector_stocks ───────────────────────────────────────────

class TestGetAllSectorStocks:
    @pytest.mark.asyncio
    async def test_active_stocks_only(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(return_value={"005930": "반도체"})), \
             patch("backend.app.services.engine_symbol_utils.get_stock_market", return_value="코스피") as _, \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=True) as _:
            mock_state.master_stocks_cache = {
                "005930": {"name": "삼성전자", "status": "active"},
                "005931": {"name": "비활성", "status": "inactive"},
            }
            result = await get_all_sector_stocks()
            assert len(result) == 1
            assert result[0]["code"] == "005930"
            assert result[0]["name"] == "삼성전자"
            assert result[0]["sector"] == "반도체"
            assert result[0]["market_type"] == "코스피"
            assert result[0]["nxt_enable"] is True

    @pytest.mark.asyncio
    async def test_empty_cache(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(return_value={})):
            mock_state.master_stocks_cache = {}
            result = await get_all_sector_stocks()
            assert result == []


# ── get_sector_stocks ───────────────────────────────────────────────

class TestGetSectorStocks:
    @pytest.mark.asyncio
    async def test_filters_invalid_entries(self):
        """시세/이름 없는 엔트리 제거."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_symbol_utils.get_stock_market", return_value="코스피"), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=False):
            mock_state.integrated_system_settings_cache = {"sector_min_trade_amt": 0.0}
            mock_state.master_stocks_cache = {
                "005930": {"name": "삼성전자", "cur_price": 70000, "avg_5d_trade_amount": 50000, "high_5d_price": 71000},
                "000000": {"cur_price": 0, "name": ""},  # 무효 — cur_price=0, name 없음
            }
            mock_state.sector_summary_cache = None
            result = await get_sector_stocks()
            assert len(result) == 1
            assert result[0]["code"] == "005930"

    @pytest.mark.asyncio
    async def test_filters_by_min_trade_amt(self):
        """5일평균거래대금 필터링."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.sector_mapping.get_merged_sectors_batch", new=AsyncMock(return_value={})), \
             patch("backend.app.services.engine_symbol_utils.get_stock_market", return_value="코스피"), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", return_value=False):
            mock_state.integrated_system_settings_cache = {"sector_min_trade_amt": 1000.0}  # 1000억원
            mock_state.master_stocks_cache = {
                "005930": {"name": "삼성전자", "cur_price": 70000, "avg_5d_trade_amount": 50000, "high_5d_price": 71000},
                # avg_5d_trade_amount=50000 (백만원) → 500억원 → 1000억 미만 → 필터됨
            }
            mock_state.sector_summary_cache = None
            result = await get_sector_stocks()
            assert len(result) == 0


# ── get_sector_summary_inputs ───────────────────────────────────────

class TestGetSectorSummaryInputs:
    @pytest.mark.asyncio
    async def test_returns_expected_structure(self):
        with patch("backend.app.services.sector_data_provider.get_sector_stocks", new=AsyncMock(return_value=[
            {"code": "005930", "avg_amt_5d": 50000},
        ])), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False):
            result = await get_sector_summary_inputs()
            assert "all_codes" in result
            assert "trade_prices" in result
            assert "trade_amounts" in result
            assert "avg_amt_5d" in result
            assert "latest_index" in result
            assert result["all_codes"] == ["005930"]
            assert result["avg_amt_5d"]["005930"] == 50000

    @pytest.mark.asyncio
    async def test_nxt_only_window_filters(self):
        """NXT-only 구간에서는 NXT-enabled 종목만 포함."""
        with patch("backend.app.services.sector_data_provider.get_sector_stocks", new=AsyncMock(return_value=[
            {"code": "005930", "avg_amt_5d": 50000},
            {"code": "005931", "avg_amt_5d": 30000},
        ])), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=True), \
             patch("backend.app.services.engine_symbol_utils.is_nxt_enabled", side_effect=lambda cd: cd == "005930"):
            result = await get_sector_summary_inputs()
            assert result["all_codes"] == ["005930"]


# ── recompute_sector_summary_now ────────────────────────────────────

class TestRecomputeSectorSummaryNow:
    @pytest.mark.asyncio
    async def test_engine_not_running_returns_early(self):
        with patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=False):
            await recompute_sector_summary_now()
            # 엔진 미실행 → early return, 예외 없음

    @pytest.mark.asyncio
    async def test_recompute_success(self):
        mock_ss = MagicMock()
        mock_ss.sectors = []
        mock_ss.buy_targets = []
        mock_ss.blocked_targets = []

        settings_cache = {
            "sector_min_rise_ratio_pct": 60.0,
            "sector_min_trade_amt": 0.0,
            "sector_bonus_rise_ratio_slider": 0,
            "sector_bonus_relative_strength_slider": 0,
            "sector_bonus_trade_amount_slider": 0,
        }

        with patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=True), \
             patch("backend.app.services.sector_data_provider.state") as mock_state, \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new=AsyncMock(return_value={
                 "all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {}
             })), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new=AsyncMock(return_value=mock_ss)), \
             patch("backend.app.domain.buy_filter.build_buy_targets_from_settings", return_value=mock_ss), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.engine_sector_confirm.cancel_sector_recompute"), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=AsyncMock()), \
             patch("backend.app.services.engine_account_notify.notify_buy_targets_update", new=AsyncMock()):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.auto_trade = None
            mock_state.master_stocks_cache = {"005930": {}}
            mock_state.sector_summary_ready_event = MagicMock()
            await recompute_sector_summary_now()
            mock_state.sector_summary_ready_event.set.assert_called()


# ── _on_filter_settings_changed ─────────────────────────────────────

class TestOnFilterSettingsChanged:
    @pytest.mark.asyncio
    async def test_calls_recompute(self):
        with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock()) as mock_recompute:
            await _on_filter_settings_changed()
            mock_recompute.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_logged(self):
        """recompute 예외 시 로깅만 수행 (raise 아님)."""
        with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=AsyncMock(side_effect=Exception("test error"))):
            # 예외가 raise되지 않음
            await _on_filter_settings_changed()
