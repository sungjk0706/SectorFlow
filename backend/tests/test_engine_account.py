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
    get_buy_limit_status,
    _merge_positions_from_rest,
    _apply_broker_totals_from_summary,
    _fetch_and_store_unfilled_orders,
)


# ── get_account_snapshot ──────────────────────────────────────────────────────────

class TestGetAccountSnapshot:
    @pytest.mark.asyncio
    async def test_existing_snapshot(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_virtual_mode", return_value=False):
            mock_state.account_snapshot = {"deposit": 5000000, "trade_mode": "live"}
            result = await get_account_snapshot()
            assert result["deposit"] == 5000000
            assert result["trade_mode"] == "live"

    @pytest.mark.asyncio
    async def test_empty_snapshot_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_virtual_mode", return_value=False):
            mock_state.account_snapshot = {}
            result = await get_account_snapshot()
            assert result["trade_mode"] == "live"
            # 빈 snapshot = 데이터 없음 → None (0이 아님 — P20 폴백 금지, P21 투명성)
            assert result["total_buy"] is None
            assert result["total_eval"] is None
            assert result["position_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_snapshot_test_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_virtual_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_accumulated_investment", return_value=10000000), \
             patch("backend.app.services.settlement_engine.get_orderable", return_value=8000000):
            mock_state.account_snapshot = {}
            result = await get_account_snapshot()
            assert result["trade_mode"] == "virtual"
            assert result["accumulated_investment"] == 10000000
            assert result["orderable"] == 8000000
            assert result["initial_deposit"] == 10000000


# ── get_trade_mode ──────────────────────────────────────────────────────────────────

class TestGetTradeMode:
    def test_real(self):
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=False):
            assert get_trade_mode() == "live"

    def test_test(self):
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=True):
            assert get_trade_mode() == "virtual"


# ── get_positions ───────────────────────────────────────────────────────────────────

class TestGetPositions:
    @pytest.mark.asyncio
    async def test_real_mode(self):
        with patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.services.engine_account.is_virtual_mode", return_value=False):
            mock_state.positions = [{"stk_cd": "005930", "qty": 10}]
            result = await get_positions()
            assert result == [{"stk_cd": "005930", "qty": 10}]

    @pytest.mark.asyncio
    async def test_test_mode(self):
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[{"stk_cd": "005930", "qty": 5}]):
            result = await get_positions()
            assert result == [{"stk_cd": "005930", "qty": 5}]


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


# ── _fetch_and_store_unfilled_orders (결정 6 — 미체결 주문 조회) ──────────────────

class TestFetchAndStoreUnfilledOrders:
    @pytest.mark.asyncio
    async def test_virtual_mode_skips_fetch(self):
        """가상매매 모드 — 미체결 조회 수행하지 않고 빈 리스트."""
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.state") as mock_state:
            await _fetch_and_store_unfilled_orders({"broker": "kiwoom"})
            assert mock_state.unfilled_orders == []

    @pytest.mark.asyncio
    async def test_no_rest_api_returns_empty(self):
        """REST API 인스턴스 없음 — 빈 리스트."""
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_account.state") as mock_state:
            mock_state.broker_rest_apis.get.return_value = None
            await _fetch_and_store_unfilled_orders({"broker": "kiwoom"})
            assert mock_state.unfilled_orders == []

    @pytest.mark.asyncio
    async def test_kiwoom_success(self):
        """키움 — 미체결 주문 조회 성공 → 파싱 후 state 저장."""
        from backend.app.core.kiwoom_providers import KiwoomAccountProvider
        mock_rest_api = MagicMock()
        mock_rest_api.get_unfilled_orders = AsyncMock(return_value={
            "oso": [{"ord_no": "12345", "stk_cd": "005930", "stk_nm": "삼성전자", "ord_qty": 10, "ord_uv": 70000, "unfilled_qty": 5, "ord_stat": "미체결", "trde_tp": "2"}]
        })
        mock_router = MagicMock()
        mock_router.account = KiwoomAccountProvider()
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.core.broker_factory.get_router", return_value=mock_router):
            mock_state.broker_rest_apis.get.return_value = mock_rest_api
            mock_state.rest_api_thread_sem = MagicMock()
            mock_state.rest_api_thread_sem.__aenter__ = AsyncMock(return_value=mock_state.rest_api_thread_sem)
            mock_state.rest_api_thread_sem.__aexit__ = AsyncMock(return_value=None)
            await _fetch_and_store_unfilled_orders({"broker": "kiwoom"})
            assert len(mock_state.unfilled_orders) == 1
            order = mock_state.unfilled_orders[0]
            assert order["ord_no"] == "12345"
            assert order["stk_cd"] == "005930"
            assert order["stk_nm"] == "삼성전자"
            assert order["ord_qty"] == 10
            assert order["ord_price"] == 70000
            assert order["unfilled_qty"] == 5
            assert order["ord_type"] == "매수"

    @pytest.mark.asyncio
    async def test_ls_success(self):
        """LS — 미체결 주문 조회 성공 → 파싱 후 state 저장."""
        from backend.app.core.ls_providers import LsAccountProvider
        mock_rest_api = MagicMock()
        mock_rest_api.get_unfilled_orders = AsyncMock(return_value={
            "t0425OutBlock1": [{"ordno": "67890", "expcode": "005930", "ordmenuname": "삼성전자", "ordqty": 20, "ordprice": 71000, "unfilledqty": 10, "ordstatus": "미체결", "medosu": "1"}]
        })
        mock_router = MagicMock()
        mock_router.account = LsAccountProvider()
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.core.broker_factory.get_router", return_value=mock_router):
            mock_state.broker_rest_apis.get.return_value = mock_rest_api
            mock_state.rest_api_thread_sem = MagicMock()
            mock_state.rest_api_thread_sem.__aenter__ = AsyncMock(return_value=mock_state.rest_api_thread_sem)
            mock_state.rest_api_thread_sem.__aexit__ = AsyncMock(return_value=None)
            await _fetch_and_store_unfilled_orders({"broker": "ls"})
            assert len(mock_state.unfilled_orders) == 1
            order = mock_state.unfilled_orders[0]
            assert order["ord_no"] == "67890"
            assert order["stk_cd"] == "005930"
            assert order["stk_nm"] == "삼성전자"
            assert order["ord_qty"] == 20
            assert order["ord_price"] == 71000
            assert order["unfilled_qty"] == 10
            assert order["ord_type"] == "매도"

    @pytest.mark.asyncio
    async def test_fetch_returns_none(self):
        """조회 응답 None — 빈 리스트 유지."""
        mock_rest_api = MagicMock()
        mock_rest_api.get_unfilled_orders = AsyncMock(return_value=None)
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_account.state") as mock_state:
            mock_state.broker_rest_apis.get.return_value = mock_rest_api
            mock_state.rest_api_thread_sem = MagicMock()
            mock_state.rest_api_thread_sem.__aenter__ = AsyncMock(return_value=mock_state.rest_api_thread_sem)
            mock_state.rest_api_thread_sem.__aexit__ = AsyncMock(return_value=None)
            await _fetch_and_store_unfilled_orders({"broker": "kiwoom"})
            assert mock_state.unfilled_orders == []

    @pytest.mark.asyncio
    async def test_fetch_exception_returns_empty(self):
        """조회 예외 — 빈 리스트 유지 (P25 격리된 실패)."""
        mock_rest_api = MagicMock()
        mock_rest_api.get_unfilled_orders = AsyncMock(side_effect=Exception("net error"))
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_account.state") as mock_state:
            mock_state.broker_rest_apis.get.return_value = mock_rest_api
            mock_state.rest_api_thread_sem = MagicMock()
            mock_state.rest_api_thread_sem.__aenter__ = AsyncMock(return_value=mock_state.rest_api_thread_sem)
            mock_state.rest_api_thread_sem.__aexit__ = AsyncMock(return_value=None)
            await _fetch_and_store_unfilled_orders({"broker": "kiwoom"})
            assert mock_state.unfilled_orders == []

    @pytest.mark.asyncio
    async def test_unsupported_broker_returns_empty(self):
        """Provider 조회 실패 — 빈 리스트 (P25 격리된 실패)."""
        mock_rest_api = MagicMock()
        mock_rest_api.get_unfilled_orders = AsyncMock(return_value={"some": "data"})
        with patch("backend.app.services.engine_account.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_account.state") as mock_state, \
             patch("backend.app.core.broker_factory.get_router", side_effect=KeyError("broker_config")):
            mock_state.broker_rest_apis.get.return_value = mock_rest_api
            mock_state.rest_api_thread_sem = MagicMock()
            mock_state.rest_api_thread_sem.__aenter__ = AsyncMock(return_value=mock_state.rest_api_thread_sem)
            mock_state.rest_api_thread_sem.__aexit__ = AsyncMock(return_value=None)
            await _fetch_and_store_unfilled_orders({"broker": "unknown"})
            assert mock_state.unfilled_orders == []
