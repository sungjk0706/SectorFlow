"""risk_manager.py 단위 테스트 — 주문 전 리스크 통제 로직 검증.

RiskManager의 check_buy_order_allowed, check_sell_order_allowed,
record_order_success/failure 로직을 검증.
CircuitBreaker, trade_history, engine_state는 mock로 격리.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.risk_manager import RiskManager
from backend.app.services.circuit_breaker import CircuitBreaker


# ── 픽스처 ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_circuit_breaker():
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
    cb.reset()
    return cb


@pytest.fixture
def risk_manager(mock_circuit_breaker):
    """RiskManager 인스턴스 생성 — engine_state 설정 캐시 mock."""
    rm = RiskManager.__new__(RiskManager)
    rm.circuit_breaker = mock_circuit_breaker
    rm.max_daily_loss_limit = -500_000
    rm.daily_loss_limit = -500_000
    rm.max_single_stock_exposure = 20_000_000
    return rm


@pytest.fixture
def settings_cache():
    """기본 설정 캐시 (실전모드)."""
    return {
        "test_mode_on": False,
        "max_daily_loss_limit": -500_000,
        "max_single_stock_exposure": 20_000_000,
    }


# ── _sync_thresholds ───────────────────────────────────────────────────────────

class TestSyncThresholds:
    def test_sync_reads_from_engine_state(self):
        rm = RiskManager.__new__(RiskManager)
        rm.circuit_breaker = CircuitBreaker()

        mock_cache = {
            "max_daily_loss_limit": -1_000_000,
            "max_single_stock_exposure": 30_000_000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.integrated_system_settings_cache = mock_cache
            rm._sync_thresholds()

        assert rm.max_daily_loss_limit == -1_000_000
        assert rm.daily_loss_limit == -1_000_000
        assert rm.max_single_stock_exposure == 30_000_000

    def test_sync_defaults_when_keys_missing(self):
        rm = RiskManager.__new__(RiskManager)
        rm.circuit_breaker = CircuitBreaker()

        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.integrated_system_settings_cache = {}
            rm._sync_thresholds()

        assert rm.max_daily_loss_limit == -500_000
        assert rm.daily_loss_limit == -500_000
        assert rm.max_single_stock_exposure == 20_000_000


# ── get_withdrawable_deposit ──────────────────────────────────────────────────

class TestGetWithdrawableDeposit:
    def test_test_mode_returns_settlement_engine_cash(self, risk_manager, settings_cache):
        settings_cache["test_mode_on"] = True
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=5_000_000):
            mock_state.integrated_system_settings_cache = settings_cache
            result = risk_manager.get_withdrawable_deposit()
        assert result == 5_000_000

    def test_real_mode_returns_account_snapshot_orderable(self, risk_manager, settings_cache):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 80_000_000}
            result = risk_manager.get_withdrawable_deposit()
        assert result == 80_000_000

    def test_real_mode_returns_zero_when_orderable_missing(self, risk_manager, settings_cache):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {}
            result = risk_manager.get_withdrawable_deposit()
        assert result == 0


# ── check_buy_order_allowed ────────────────────────────────────────────────────

class TestCheckBuyOrderAllowed:
    @pytest.mark.asyncio
    async def test_all_pass_returns_true(self, risk_manager, settings_cache):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is True
        assert reason == "승인"

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_blocks(self, risk_manager, settings_cache):
        risk_manager.circuit_breaker.state = "OPEN"
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "서킷브레이커" in reason

    @pytest.mark.asyncio
    async def test_daily_loss_limit_blocks(self, risk_manager, settings_cache):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=-600_000):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "일일 손실 한도" in reason

    @pytest.mark.asyncio
    async def test_daily_loss_at_limit_blocks(self, risk_manager, settings_cache):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=-500_000):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "일일 손실 한도" in reason

    @pytest.mark.asyncio
    async def test_daily_loss_above_limit_passes(self, risk_manager, settings_cache):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=-499_999):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_insufficient_deposit_blocks(self, risk_manager, settings_cache):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 500_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "예수금" in reason

    @pytest.mark.asyncio
    async def test_single_stock_exposure_blocks(self, risk_manager, settings_cache):
        # existing position 15M + new order 700K = 15.7M < 20M → pass
        # existing position 19.5M + new order 700K = 20.2M > 20M → block
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = [{"stk_cd": "005930", "buy_amount": 19_500_000}]
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "단일 종목" in reason

    @pytest.mark.asyncio
    async def test_single_stock_exposure_zero_disables_check(self, risk_manager, settings_cache):
        risk_manager.max_single_stock_exposure = 0
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0), \
             patch.object(risk_manager, "_sync_thresholds", lambda: None):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = [{"stk_cd": "005930", "buy_amount": 999_999_999}]
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_test_mode_uses_settlement_engine(self, risk_manager, settings_cache):
        settings_cache["test_mode_on"] = True
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=True), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=100_000_000), \
             patch("backend.app.services.dry_run.get_position", new_callable=AsyncMock, return_value=None):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_test_mode_insufficient_cash_blocks(self, risk_manager, settings_cache):
        settings_cache["test_mode_on"] = True
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=True), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=500_000), \
             patch("backend.app.services.dry_run.get_position", new_callable=AsyncMock, return_value=None):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "예수금" in reason

    @pytest.mark.asyncio
    async def test_test_mode_single_stock_exposure_with_position(self, risk_manager, settings_cache):
        settings_cache["test_mode_on"] = True
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=True), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=100_000_000), \
             patch("backend.app.services.dry_run.get_position", new_callable=AsyncMock, return_value={"buy_amount": 19_500_000}):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "단일 종목" in reason


# ── check_sell_order_allowed ───────────────────────────────────────────────────

class TestCheckSellOrderAllowed:
    def test_closed_allows_sell(self, risk_manager):
        risk_manager.circuit_breaker.state = "CLOSED"
        allowed, reason = risk_manager.check_sell_order_allowed("005930", 80_000, 10)
        assert allowed is True
        assert reason == "승인"

    def test_open_blocks_sell(self, risk_manager):
        risk_manager.circuit_breaker.state = "OPEN"
        allowed, reason = risk_manager.check_sell_order_allowed("005930", 80_000, 10)
        assert allowed is False
        assert "서킷브레이커" in reason

    def test_half_open_allows_sell(self, risk_manager):
        risk_manager.circuit_breaker.state = "HALF_OPEN"
        allowed, reason = risk_manager.check_sell_order_allowed("005930", 80_000, 10)
        assert allowed is True


# ── record_order_success / record_order_failure ────────────────────────────────

class TestRecordOrder:
    def test_record_success_delegates_to_circuit_breaker(self, risk_manager):
        risk_manager.circuit_breaker.failure_count = 3
        risk_manager.record_order_success()
        assert risk_manager.circuit_breaker.failure_count == 0

    def test_record_failure_delegates_to_circuit_breaker(self, risk_manager):
        risk_manager.circuit_breaker.failure_count = 0
        risk_manager.record_order_failure()
        assert risk_manager.circuit_breaker.failure_count == 1

    def test_record_failure_triggers_open_at_threshold(self, risk_manager):
        risk_manager.circuit_breaker.failure_threshold = 3
        for _ in range(3):
            risk_manager.record_order_failure()
        assert risk_manager.circuit_breaker.state == "OPEN"
