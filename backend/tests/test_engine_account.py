"""engine_account.py 단위 테스트 — 계좌 스냅샷·포지션·거래모드 조회 함수 검증.

state 의존 함수는 state를 mock하여 검증.
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

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
    _position_codes_with_qty,
    _merge_positions_from_rest,
    _apply_broker_totals_from_summary,
)


# ── get_account_snapshot ──────────────────────────────────────────────────────────

class TestGetAccountSnapshot:
    @pytest.mark.asyncio
    async def test_existing_snapshot(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.account_snapshot = {"deposit": 5000000, "trade_mode": "real"}
            result = await get_account_snapshot()
            assert result["deposit"] == 5000000
            assert result["trade_mode"] == "real"

    @pytest.mark.asyncio
    async def test_empty_snapshot_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.account_snapshot = {}
            result = await get_account_snapshot()
            assert result["trade_mode"] == "real"
            assert result["total_buy"] == 0
            assert result["total_eval"] == 0
            assert result["position_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_snapshot_test_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_accumulated_investment", return_value=10000000), \
             patch("backend.app.services.settlement_engine.get_orderable", return_value=8000000):
            mock_state.account_snapshot = {}
            result = await get_account_snapshot()
            assert result["trade_mode"] == "test"
            assert result["accumulated_investment"] == 10000000
            assert result["orderable"] == 8000000
            assert result["initial_deposit"] == 10000000


# ── get_trade_mode ──────────────────────────────────────────────────────────────────

class TestGetTradeMode:
    def test_real(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            assert get_trade_mode() == "real"

    def test_test(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True):
            assert get_trade_mode() == "test"


# ── get_positions ───────────────────────────────────────────────────────────────────

class TestGetPositions:
    @pytest.mark.asyncio
    async def test_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.positions = [{"stk_cd": "005930", "qty": 10}]
            result = await get_positions()
            assert result == [{"stk_cd": "005930", "qty": 10}]

    @pytest.mark.asyncio
    async def test_test_mode(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[{"stk_cd": "005930", "qty": 5}]):
            result = await get_positions()
            assert result == [{"stk_cd": "005930", "qty": 5}]


# ── get_total_buy_amount ────────────────────────────────────────────────────────────

class TestGetTotalBuyAmount:
    @pytest.mark.asyncio
    async def test_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.broker_rest_totals = {"total_buy": 7000000}
            result = await get_total_buy_amount()
            assert result == 7000000

    @pytest.mark.asyncio
    async def test_test_mode(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[{"buy_amt": 3000000}, {"buy_amt": 2000000}]):
            result = await get_total_buy_amount()
            assert result == 5000000


# ── get_total_eval_amount ────────────────────────────────────────────────────────────

class TestGetTotalEvalAmount:
    @pytest.mark.asyncio
    async def test_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.broker_rest_totals = {"total_eval": 8000000}
            result = await get_total_eval_amount()
            assert result == 8000000

    @pytest.mark.asyncio
    async def test_test_mode(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[{"eval_amt": 4000000}, {"eval_amt": 3000000}]):
            result = await get_total_eval_amount()
            assert result == 7000000


# ── get_total_pnl ────────────────────────────────────────────────────────────────────

class TestGetTotalPnl:
    @pytest.mark.asyncio
    async def test_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.broker_rest_totals = {"total_pnl": 1000000}
            result = await get_total_pnl()
            assert result == 1000000

    @pytest.mark.asyncio
    async def test_test_mode(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[{"pnl_amount": 500000}, {"pnl_amount": 300000}]):
            result = await get_total_pnl()
            assert result == 800000


# ── get_total_pnl_rate ────────────────────────────────────────────────────────────────

class TestGetTotalPnlRate:
    @pytest.mark.asyncio
    async def test_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.broker_rest_totals = {"total_rate": 5.26}
            result = await get_total_pnl_rate()
            assert result == 5.26

    @pytest.mark.asyncio
    async def test_test_mode_with_buy(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[{"buy_amt": 10000000, "pnl_amount": 500000}]):
            result = await get_total_pnl_rate()
            assert result == round(500000 / 10000000 * 100, 2)

    @pytest.mark.asyncio
    async def test_test_mode_zero_buy(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[{"buy_amt": 0, "pnl_amount": 0}]):
            result = await get_total_pnl_rate()
            assert result == 0.0


# ── get_snapshot_history ──────────────────────────────────────────────────────────────

class TestGetSnapshotHistory:
    def test_basic(self):
        with patch("backend.app.services.engine_account.state") as mock_state:
            mock_state.snapshot_history = [{"ts": 1}, {"ts": 2}]
            result = get_snapshot_history()
            assert result == [{"ts": 1}, {"ts": 2}]

    def test_empty(self):
        with patch("backend.app.services.engine_account.state") as mock_state:
            mock_state.snapshot_history = []
            result = get_snapshot_history()
            assert result == []


# ── get_buy_limit_status ──────────────────────────────────────────────────────────────

class TestGetBuyLimitStatus:
    @pytest.mark.asyncio
    async def test_no_auto_trade(self):
        with patch("backend.app.services.engine_account.state") as mock_state:
            mock_state.auto_trade = None
            result = await get_buy_limit_status()
            assert result == {"daily_buy_spent": 0}

    @pytest.mark.asyncio
    async def test_with_auto_trade(self):
        with patch("backend.app.services.engine_account.state") as mock_state:
            mock_auto = MagicMock()
            mock_auto._daily_buy_spent = 500000
            mock_auto._ensure_daily_buy_counter = AsyncMock()
            mock_state.auto_trade = mock_auto
            result = await get_buy_limit_status()
            assert result == {"daily_buy_spent": 500000}
            mock_auto._ensure_daily_buy_counter.assert_awaited_once()


# ── _position_codes_with_qty ──────────────────────────────────────────────────────────

class TestPositionCodesWithQty:
    @pytest.mark.asyncio
    async def test_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.positions = [
                {"stk_cd": "005930", "qty": 10},
                {"stk_cd": "000660", "qty": 0},
                {"stk_cd": "035420", "qty": 5},
            ]
            result = await _position_codes_with_qty()
            assert result == {"005930", "035420"}

    @pytest.mark.asyncio
    async def test_empty_positions(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_test_mode", return_value=False):
            mock_state.positions = []
            result = await _position_codes_with_qty()
            assert result == set()

    @pytest.mark.asyncio
    async def test_test_mode(self):
        with patch("backend.app.services.engine_account.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.position_codes", new_callable=AsyncMock, return_value={"005930"}):
            result = await _position_codes_with_qty()
            assert result == {"005930"}


# ── _merge_positions_from_rest ────────────────────────────────────────────────────────

class TestMergePositionsFromRest:
    def test_basic(self):
        with patch("backend.app.services.engine_account_rest.merge_positions_from_rest", return_value=[{"stk_cd": "005930"}]) as mock_merge:
            result = _merge_positions_from_rest([{"stk_cd": "005930", "qty": "10"}])
            assert result == [{"stk_cd": "005930"}]
            mock_merge.assert_called_once()

    def test_empty(self):
        with patch("backend.app.services.engine_account_rest.merge_positions_from_rest", return_value=[]):
            result = _merge_positions_from_rest([])
            assert result == []


# ── _apply_broker_totals_from_summary ──────────────────────────────────────────────────

class TestApplyBrokerTotalsFromSummary:
    def test_basic(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account_rest.broker_totals_from_summary", return_value={"total_eval": 10000000}) as mock_fn:
            _apply_broker_totals_from_summary({"tot_eval": 10000000})
            assert mock_state.broker_rest_totals == {"total_eval": 10000000}
            mock_fn.assert_called_once()
