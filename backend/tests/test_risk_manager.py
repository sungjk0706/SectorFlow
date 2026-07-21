"""risk_manager.py 단위 테스트 — 주문 전 리스크 통제 로직 검증.

RiskManager의 check_buy_order_allowed, check_sell_order_allowed,
record_order_success/failure 로직을 검증.
CircuitBreaker, trade_history, engine_state는 mock로 격리.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

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
    # 신규 — 리스크 매니저 확장 속성 (기본값: risk_manager_on=False)
    rm.risk_manager_on = False
    rm.daily_loss_limit_on = True
    rm.risk_block_buy_on = True
    rm.risk_block_sell_on = False
    rm.daily_loss_rate_limit_on = False
    rm.daily_loss_rate_limit = -5.0
    rm.daily_profit_limit_on = False
    rm.daily_profit_limit = 500_000
    rm.daily_profit_rate_limit_on = False
    rm.daily_profit_rate_limit = 5.0
    rm.consecutive_loss_limit_on = False
    rm.consecutive_loss_limit = 3
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
        assert rm.daily_loss_limit_on is True  # 기본 ON — 기존 항상 실행 동작 유지


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
    async def test_daily_loss_limit_off_skips_check(self, risk_manager, settings_cache):
        """daily_loss_limit_on=False 시 손실 한도 체크 스킵 — 한도 초과여도 매수 허용."""
        settings_cache["daily_loss_limit_on"] = False
        settings_cache["daily_loss_limit"] = -500_000
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=-600_000):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is True

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
    @pytest.mark.asyncio
    async def test_closed_allows_sell(self, risk_manager):
        risk_manager.circuit_breaker.state = "CLOSED"
        with patch.object(risk_manager, "_sync_thresholds", lambda: None):
            allowed, reason = await risk_manager.check_sell_order_allowed("005930", 80_000, 10)
        assert allowed is True
        assert reason == "승인"

    @pytest.mark.asyncio
    async def test_open_blocks_sell(self, risk_manager):
        risk_manager.circuit_breaker.state = "OPEN"
        with patch.object(risk_manager, "_sync_thresholds", lambda: None):
            allowed, reason = await risk_manager.check_sell_order_allowed("005930", 80_000, 10)
        assert allowed is False
        assert "서킷브레이커" in reason

    @pytest.mark.asyncio
    async def test_half_open_allows_sell(self, risk_manager):
        risk_manager.circuit_breaker.state = "HALF_OPEN"
        with patch.object(risk_manager, "_sync_thresholds", lambda: None):
            allowed, reason = await risk_manager.check_sell_order_allowed("005930", 80_000, 10)
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


# ── 리스크 매니저 확장 — 신규 조건 테스트 (4세션) ───────────────────────────────

class TestRiskManagerToggle:
    """risk_manager_on / risk_block_buy_on / risk_block_sell_on 토글 동작 검증."""

    @pytest.mark.asyncio
    async def test_risk_manager_off_skips_extended_checks(self, risk_manager, settings_cache):
        """risk_manager_on=False 시 신규 조건 스킵 — 기존 일일 손실 한도/예수금/비중은 항상 실행."""
        risk_manager.risk_manager_on = False
        risk_manager.daily_profit_limit_on = True  # 신규 조건 활성화되어 있어도 스킵되어야 함
        risk_manager.daily_profit_limit = 100_000
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=200_000), \
             patch.object(risk_manager, "_check_extended_buy_risk", new_callable=AsyncMock) as mock_ext:
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is True
        mock_ext.assert_not_awaited()  # 신규 조건 호출 안 됨

    @pytest.mark.asyncio
    async def test_risk_block_buy_off_skips_extended_checks(self, risk_manager, settings_cache):
        """risk_block_buy_on=False 시 신규 조건 스킵 — 기존 체크는 항상 실행."""
        risk_manager.risk_manager_on = True
        risk_manager.risk_block_buy_on = False
        risk_manager.daily_profit_limit_on = True
        risk_manager.daily_profit_limit = 100_000
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=200_000), \
             patch.object(risk_manager, "_check_extended_buy_risk", new_callable=AsyncMock) as mock_ext:
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is True
        mock_ext.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_risk_block_sell_off_skips_sell_checks(self, risk_manager, settings_cache):
        """risk_block_sell_on=False 시 매도 리스크 조건 스킵 — 서킷브레이커만 동작."""
        risk_manager.risk_manager_on = True
        risk_manager.risk_block_sell_on = False
        with patch.object(risk_manager, "_sync_thresholds", lambda: None), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock) as mock_pnl:
            allowed, reason = await risk_manager.check_sell_order_allowed("005930", 80_000, 10)
        assert allowed is True
        assert reason == "승인"
        mock_pnl.assert_not_awaited()  # 매도 리스크 조건 호출 안 됨


class TestDailyLossRateLimit:
    """일일 손실률 한도 초과 시 매수/매도 차단 검증."""

    @pytest.mark.asyncio
    async def test_loss_rate_exceeds_blocks_buy(self, risk_manager, settings_cache):
        """손실률 한도 초과 시 매수 차단."""
        risk_manager.risk_manager_on = True
        risk_manager.risk_block_buy_on = True
        risk_manager.daily_loss_rate_limit_on = True
        risk_manager.daily_loss_rate_limit = -5.0  # -5%
        risk_manager.daily_loss_limit = -700_000  # 기존 한도는 통과하도록 완화
        # today_pnl=-600_000 > -700_000 (기존 통과), today_principal=10_000_000 → -6% ≤ -5% (신규 차단)
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=-600_000), \
             patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[{"price": 50_000, "qty": 200}]), \
             patch.object(risk_manager, "_sync_thresholds", lambda: None):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "일일 손실률 한도" in reason

    @pytest.mark.asyncio
    async def test_loss_rate_exceeds_blocks_sell(self, risk_manager, settings_cache):
        """손실률 한도 초과 시 매도 차단 (risk_block_sell_on=True)."""
        risk_manager.risk_manager_on = True
        risk_manager.risk_block_sell_on = True
        risk_manager.daily_loss_rate_limit_on = True
        risk_manager.daily_loss_rate_limit = -5.0
        risk_manager.daily_loss_limit = -700_000  # 기존 한도는 통과하도록 완화
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=-600_000), \
             patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[{"price": 50_000, "qty": 200}]), \
             patch.object(risk_manager, "_sync_thresholds", lambda: None):
            mock_state.integrated_system_settings_cache = settings_cache
            allowed, reason = await risk_manager.check_sell_order_allowed("005930", 80_000, 10)
        assert allowed is False
        assert "일일 손실률 한도" in reason
        assert "매도 차단" in reason


class TestDailyProfitLimit:
    """일일 수익 한도 도달 시 차단 검증."""

    @pytest.mark.asyncio
    async def test_profit_reached_blocks_buy(self, risk_manager, settings_cache):
        """수익 한도 도달 시 매수 차단."""
        risk_manager.risk_manager_on = True
        risk_manager.risk_block_buy_on = True
        risk_manager.daily_profit_limit_on = True
        risk_manager.daily_profit_limit = 500_000
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=500_000), \
             patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[]), \
             patch.object(risk_manager, "_sync_thresholds", lambda: None):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "일일 수익 한도" in reason


class TestDailyProfitRateLimit:
    """일일 수익률 한도 도달 시 차단 검증."""

    @pytest.mark.asyncio
    async def test_profit_rate_reached_blocks_buy(self, risk_manager, settings_cache):
        """수익률 한도 도달 시 매수 차단."""
        risk_manager.risk_manager_on = True
        risk_manager.risk_block_buy_on = True
        risk_manager.daily_profit_rate_limit_on = True
        risk_manager.daily_profit_rate_limit = 5.0  # 5%
        # today_pnl=600_000, today_principal=10_000_000 → 6% ≥ 5% → 차단
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=600_000), \
             patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[{"price": 50_000, "qty": 200}]), \
             patch.object(risk_manager, "_sync_thresholds", lambda: None):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "일일 수익률 한도" in reason


class TestConsecutiveLossLimit:
    """연속 손실 횟수 한도 초과 시 차단 검증."""

    @pytest.mark.asyncio
    async def test_consec_loss_exceeds_blocks_buy(self, risk_manager, settings_cache):
        """연속 손실 3회 시 매수 차단 (한도=3)."""
        risk_manager.risk_manager_on = True
        risk_manager.risk_block_buy_on = True
        risk_manager.consecutive_loss_limit_on = True
        risk_manager.consecutive_loss_limit = 3
        sell_rows = [{"realized_pnl": -10_000}, {"realized_pnl": -20_000}, {"realized_pnl": -30_000}]
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.risk_manager.is_test_mode", return_value=False), \
             patch("backend.app.services.risk_manager.get_total_realized_pnl", new_callable=AsyncMock, return_value=0), \
             patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=sell_rows), \
             patch.object(risk_manager, "_sync_thresholds", lambda: None):
            mock_state.integrated_system_settings_cache = settings_cache
            mock_state.account_snapshot = {"orderable": 100_000_000}
            mock_state.positions = []
            allowed, reason = await risk_manager.check_buy_order_allowed("005930", 70_000, 10)
        assert allowed is False
        assert "연속 손실 한도" in reason

    @pytest.mark.asyncio
    async def test_consec_loss_zero_history(self, risk_manager):
        """매도 이력 없으면 0회 — 차단 안 함."""
        with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=[]):
            count = await risk_manager._get_consecutive_loss_count("test")
        assert count == 0

    @pytest.mark.asyncio
    async def test_consec_loss_breaks_on_profit(self, risk_manager):
        """최신 거래가 수익이면 연속 손실 0회."""
        sell_rows = [{"realized_pnl": 10_000}, {"realized_pnl": -20_000}, {"realized_pnl": -30_000}]
        with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=sell_rows):
            count = await risk_manager._get_consecutive_loss_count("test")
        assert count == 0

    @pytest.mark.asyncio
    async def test_consec_loss_counts_consecutive(self, risk_manager):
        """연속 손실 2회 후 수익 거래 → 2회."""
        sell_rows = [{"realized_pnl": -10_000}, {"realized_pnl": -20_000}, {"realized_pnl": 30_000}]
        with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=sell_rows):
            count = await risk_manager._get_consecutive_loss_count("test")
        assert count == 2
