"""4단계: 주문 체결 종목 한정 매도 조건 점검 회귀 테스트.

검증 대상:
  - _on_fill_after_ws(fill_code) — 체결 종목만 매도 조건 점검 대상 필터링
  - 실전매매: state.positions에서 체결 종목만 매칭
  - 가상매매: dry_run.get_position(code)로 해당 종목만 조회
  - 체결 종목이 보유 목록에 없거나 전량 매도로 사라진 경우 → 빈 목록, check_sell_conditions 호출 안 함 (안전 종료)
  - fill_code 빈 문자열(구 호출부 호환) → 전체 보유 종목 검사 (회귀 보호)
  - _handle_real_00 / fake_fill_event에서 체결 종목 코드 전달 확인
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


from backend.app.services.core_queues import initialize_queues  # noqa: E402
initialize_queues()


from backend.app.services import engine_account  # noqa: E402
from backend.app.services.engine_ws_dispatch import _handle_real_00  # noqa: E402
from backend.app.services import dry_run  # noqa: E402


# ── _on_fill_after_ws: 체결 종목 한정 매도 점검 ──────────────────────────────

class TestOnFillAfterWsScopedSellCheck:
    """체결 종목 코드 전달 시 해당 종목만 매도 조건 점검 대상."""

    @pytest.mark.asyncio
    async def test_real_mode_fill_code_filters_to_matched_position(self):
        """실전매매 — 체결 종목 코드로 보유 목록에서 일치 종목만 매도 검사 전달."""
        matched = {"stk_cd": "005930", "qty": "10", "cur_price": 70000, "pnl_rate": 1.5}
        other = {"stk_cd": "000660", "qty": "5", "cur_price": 100000, "pnl_rate": -0.5}
        mock_state = MagicMock()
        mock_state.positions = [matched, other]
        mock_state.auto_trade = MagicMock()
        mock_state.auto_trade.check_sell_conditions = AsyncMock()
        mock_state.access_token = "tok"
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}  # 실전매매

        with (
            patch("backend.app.services.engine_account.state", mock_state),
            patch("backend.app.services.engine_account.is_virtual_mode", return_value=False),
            patch("backend.app.services.auto_trading_effective.auto_sell_effective", return_value=True),
            patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()),
        ):
            await engine_account._on_fill_after_ws("005930")

        mock_state.auto_trade.check_sell_conditions.assert_awaited_once()
        args = mock_state.auto_trade.check_sell_conditions.call_args
        passed_positions = args.args[0]
        assert len(passed_positions) == 1
        assert passed_positions[0]["stk_cd"] == "005930"

    @pytest.mark.asyncio
    async def test_real_mode_fill_code_not_in_positions_skips_sell_check(self):
        """실전매매 — 체결 종목이 보유 목록에 없으면(전량 매도 등) check_sell_conditions 호출 안 함."""
        other = {"stk_cd": "000660", "qty": "5", "cur_price": 100000, "pnl_rate": -0.5}
        mock_state = MagicMock()
        mock_state.positions = [other]
        mock_state.auto_trade = MagicMock()
        mock_state.auto_trade.check_sell_conditions = AsyncMock()
        mock_state.access_token = "tok"
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}

        with (
            patch("backend.app.services.engine_account.state", mock_state),
            patch("backend.app.services.engine_account.is_virtual_mode", return_value=False),
            patch("backend.app.services.auto_trading_effective.auto_sell_effective", return_value=True),
            patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()),
        ):
            await engine_account._on_fill_after_ws("005930")  # 보유 목록에 없는 종목

        mock_state.auto_trade.check_sell_conditions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_test_mode_fill_code_filters_to_matched_position(self):
        """가상매매 — dry_run.get_position(code)로 해당 종목만 매도 검사 전달."""
        matched = {"stk_cd": "005930", "qty": 10, "cur_price": 70000, "pnl_rate": 1.5}
        mock_state = MagicMock()
        mock_state.positions = []  # 가상매매에서는 사용 안 함
        mock_state.auto_trade = MagicMock()
        mock_state.auto_trade.check_sell_conditions = AsyncMock()
        mock_state.access_token = "tok"
        mock_state.integrated_system_settings_cache = {"broker": "dry_run"}  # 가상매매

        with (
            patch("backend.app.services.engine_account.state", mock_state),
            patch("backend.app.services.engine_account.is_virtual_mode", return_value=True),
            patch("backend.app.services.auto_trading_effective.auto_sell_effective", return_value=True),
            patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()),
            patch("backend.app.services.dry_run.get_position", new=AsyncMock(return_value=matched)),
        ):
            await engine_account._on_fill_after_ws("005930")

        mock_state.auto_trade.check_sell_conditions.assert_awaited_once()
        args = mock_state.auto_trade.check_sell_conditions.call_args
        passed_positions = args.args[0]
        assert len(passed_positions) == 1
        assert passed_positions[0]["stk_cd"] == "005930"

    @pytest.mark.asyncio
    async def test_test_mode_fill_code_not_in_positions_skips_sell_check(self):
        """가상매매 — 체결 종목이 보유 목록에 없으면 check_sell_conditions 호출 안 함."""
        mock_state = MagicMock()
        mock_state.positions = []
        mock_state.auto_trade = MagicMock()
        mock_state.auto_trade.check_sell_conditions = AsyncMock()
        mock_state.access_token = "tok"
        mock_state.integrated_system_settings_cache = {"broker": "dry_run"}

        with (
            patch("backend.app.services.engine_account.state", mock_state),
            patch("backend.app.services.engine_account.is_virtual_mode", return_value=True),
            patch("backend.app.services.auto_trading_effective.auto_sell_effective", return_value=True),
            patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()),
            patch("backend.app.services.dry_run.get_position", new=AsyncMock(return_value=None)),
        ):
            await engine_account._on_fill_after_ws("005930")

        mock_state.auto_trade.check_sell_conditions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_fill_code_falls_back_to_all_positions(self):
        """fill_code 빈 문자열(구 호출부 호환) → 전체 보유 종목 검사 (회귀 보호)."""
        pos_a = {"stk_cd": "005930", "qty": "10", "cur_price": 70000, "pnl_rate": 1.5}
        pos_b = {"stk_cd": "000660", "qty": "5", "cur_price": 100000, "pnl_rate": -0.5}
        mock_state = MagicMock()
        mock_state.positions = [pos_a, pos_b]
        mock_state.auto_trade = MagicMock()
        mock_state.auto_trade.check_sell_conditions = AsyncMock()
        mock_state.access_token = "tok"
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}

        with (
            patch("backend.app.services.engine_account.state", mock_state),
            patch("backend.app.services.engine_account.is_virtual_mode", return_value=False),
            patch("backend.app.services.auto_trading_effective.auto_sell_effective", return_value=True),
            patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()),
        ):
            await engine_account._on_fill_after_ws("")

        mock_state.auto_trade.check_sell_conditions.assert_awaited_once()
        args = mock_state.auto_trade.check_sell_conditions.call_args
        passed_positions = args.args[0]
        assert len(passed_positions) == 2

    @pytest.mark.asyncio
    async def test_auto_sell_not_effective_skips_sell_check(self):
        """자동매도 비활성 시 체결 종목 유무와 무관하게 check_sell_conditions 호출 안 함."""
        matched = {"stk_cd": "005930", "qty": "10", "cur_price": 70000, "pnl_rate": 1.5}
        mock_state = MagicMock()
        mock_state.positions = [matched]
        mock_state.auto_trade = MagicMock()
        mock_state.auto_trade.check_sell_conditions = AsyncMock()
        mock_state.access_token = "tok"
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}

        with (
            patch("backend.app.services.engine_account.state", mock_state),
            patch("backend.app.services.engine_account.is_virtual_mode", return_value=False),
            patch("backend.app.services.auto_trading_effective.auto_sell_effective", return_value=False),
            patch("backend.app.services.engine_account._refresh_account_snapshot_meta", new=AsyncMock()),
        ):
            await engine_account._on_fill_after_ws("005930")

        mock_state.auto_trade.check_sell_conditions.assert_not_awaited()


# ── _handle_real_00: 체결 종목 코드 전달 연결 ──────────────────────────────────

class TestHandleReal00PassesFillCode:
    """_handle_real_00이 체결 후 처리 큐에 체결 종목 코드를 전달하는지 확인.

    체결 후 처리는 주문 대기열로 이동 — _handle_real_00은 _on_fill_after_ws를 직접 호출하지 않고
    get_order_queue().put_nowait({"type":"fill_after","code":...})로 위임.
    """

    @pytest.mark.asyncio
    async def test_handle_real_00_passes_raw_cd_to_fill_after_queue(self):
        """_handle_real_00이 추출한 종목 코드를 fill_after 큐 요청에 전달."""
        mock_auto_trade = MagicMock()
        mock_auto_trade.on_fill_update = AsyncMock()
        mock_state = MagicMock()
        mock_state.auto_trade = mock_auto_trade
        mock_state.access_token = "tok"

        mock_queue = MagicMock()

        with (
            patch("backend.app.services.engine_ws_dispatch.engine_state", state=mock_state),
            patch("backend.app.services.engine_ws_dispatch.get_order_queue", return_value=mock_queue),
            patch("backend.app.services.engine_ws_dispatch._check_realtime_latency"),
            patch("backend.app.services.engine_ws_dispatch._real_item_stk_cd", return_value="005930"),
        ):
            await _handle_real_00({"90001": "005930"}, {"907": "1", "902": "0"})

        mock_queue.put_nowait.assert_called_once_with({"type": "fill_after", "code": "005930"})


# ── fake_fill_event: 가상매매 체결 종목 코드 전달 ──────────────────────────

class TestFakeFillEventPassesFillCode:
    """fake_fill_event가 _on_fill_after_ws에 체결 종목 코드를 전달하는지 확인."""

    @pytest.mark.asyncio
    async def test_fake_fill_event_passes_code_to_on_fill_after_ws(self):
        """fake_fill_event가 가상 체결 종목 코드를 _on_fill_after_ws에 전달."""
        with (
            patch("backend.app.services.dry_run._apply_buy", new=AsyncMock()),
            patch("backend.app.services.dry_run._apply_sell", new=AsyncMock()),
            patch("backend.app.services.dry_run.set_stock_name", new=AsyncMock()),
            patch("backend.app.services.dry_run.asyncio.sleep", new=AsyncMock()),
            patch("backend.app.services.dry_run._apply_slippage", return_value=70000),
            patch("backend.app.services.dry_run.FAKE_FILL_DELAY", 0),
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.services.engine_account._on_fill_after_ws", new=AsyncMock()) as mock_after,
        ):
            mock_state.auto_trade = MagicMock()
            mock_state.auto_trade.on_fill_update = AsyncMock()
            mock_state.access_token = "tok"

            await dry_run.fake_fill_event("BUY", "005930", 10, 70000, stk_nm="삼성전자")

        mock_after.assert_awaited_once()
        assert mock_after.call_args.args == ("005930",)
