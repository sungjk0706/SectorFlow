"""B1-02-05/06/07 P25 격리된 실패 단위 테스트 — leaf 핸들러/엔진 시작 보호.

검증 대상:
  - B1-02-05: _handle_real_00 — on_fill_update/_on_fill_after_ws 예외 시 정상 반환 + 지연 측정 유지
  - B1-02-06: _handle_real_balance — _apply_balance_realtime 예외 시 정상 반환
  - B1-02-07: start_engine — _refresh_positions_if_dirty 예외 시 엔진 기동 계속 (True 반환)

hang 방지 원칙 (test_pipeline_compute.py와 동일):
  - 실제 asyncio.Queue/create_task 사용 금지 → mock으로 대체
  - engine_state.state를 mock으로 대체
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Initialize queues before importing pipeline_compute (module-level get_broadcast_queue call)
from backend.app.services.core_queues import initialize_queues  # noqa: E402
initialize_queues()


from backend.app.services.engine_ws_dispatch import (  # noqa: E402
    _handle_real_00,
    _handle_real_balance,
)
from backend.app.services.engine_lifecycle import start_engine  # noqa: E402


# ── B1-02-05: _handle_real_00 격리 ──────────────────────────────────────────

class TestHandleReal00Isolation:
    """on_fill_update/_on_fill_after_ws 예외 시에도 함수 정상 반환 + 지연 측정 유지."""

    @pytest.mark.asyncio
    async def test_on_fill_update_exception_does_not_raise(self):
        """on_fill_update가 throw해도 _handle_real_00 정상 반환 + 지연 측정 유지.

        단일 try 블록 구조: on_fill_update 실패 시 _on_fill_after_ws는 스킵 (같은 블록 내).
        체결 콜백 실패를 잔고 갱신 실패와 분리하지 않는 단순성(P24) 선택.
        """
        mock_auto_trade = MagicMock()
        mock_auto_trade.on_fill_update = AsyncMock(side_effect=RuntimeError("callback boom"))
        mock_state = MagicMock()
        mock_state.auto_trade = mock_auto_trade
        mock_state.access_token = "tok"

        with (
            patch("backend.app.services.engine_ws_dispatch.engine_state", state=mock_state),
            patch("backend.app.services.engine_ws_dispatch.engine_account._on_fill_after_ws", new=AsyncMock()) as mock_after,
            patch("backend.app.services.engine_ws_dispatch._check_realtime_latency") as mock_latency,
            patch("backend.app.services.engine_ws_dispatch._real_item_stk_cd", return_value="005930"),
        ):
            # 예외 전파 없이 정상 반환
            await _handle_real_00({"90001": "005930"}, {"907": "1", "902": "0"})

        # on_fill_update 실패 → 같은 try 블록의 _on_fill_after_ws는 스킵
        mock_after.assert_not_called()
        # 지연 측정은 try 외부 — 예외와 무관하게 항상 실행
        mock_latency.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_fill_after_ws_exception_does_not_raise(self):
        """_on_fill_after_ws가 throw해도 _handle_real_00 정상 반환 + 지연 측정 유지."""
        mock_auto_trade = MagicMock()
        mock_auto_trade.on_fill_update = AsyncMock()
        mock_state = MagicMock()
        mock_state.auto_trade = mock_auto_trade
        mock_state.access_token = "tok"

        with (
            patch("backend.app.services.engine_ws_dispatch.engine_state", state=mock_state),
            patch("backend.app.services.engine_ws_dispatch.engine_account._on_fill_after_ws", new=AsyncMock(side_effect=RuntimeError("account boom"))),
            patch("backend.app.services.engine_ws_dispatch._check_realtime_latency") as mock_latency,
            patch("backend.app.services.engine_ws_dispatch._real_item_stk_cd", return_value="005930"),
        ):
            # 예외 전파 없이 정상 반환
            await _handle_real_00({"90001": "005930"}, {"907": "1", "902": "0"})

        mock_latency.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_trade_none_skips_callback_and_measures_latency(self):
        """auto_trade=None이면 콜백 스킵 + 잔고 갱신 + 지연 측정 정상 동작 (회귀 보호)."""
        mock_state = MagicMock()
        mock_state.auto_trade = None
        mock_state.access_token = "tok"

        with (
            patch("backend.app.services.engine_ws_dispatch.engine_state", state=mock_state),
            patch("backend.app.services.engine_ws_dispatch.engine_account._on_fill_after_ws", new=AsyncMock()) as mock_after,
            patch("backend.app.services.engine_ws_dispatch._check_realtime_latency") as mock_latency,
            patch("backend.app.services.engine_ws_dispatch._real_item_stk_cd", return_value="005930"),
        ):
            await _handle_real_00({"90001": "005930"}, {"907": "1", "902": "0"})

        mock_after.assert_awaited_once()
        mock_latency.assert_called_once()


# ── B1-02-06: _handle_real_balance 격리 ──────────────────────────────────────

class TestHandleRealBalanceIsolation:
    """_apply_balance_realtime 예외 시에도 함수 정상 반환."""

    @pytest.mark.asyncio
    async def test_apply_balance_exception_does_not_raise(self):
        """_apply_balance_realtime가 throw해도 _handle_real_balance 정상 반환."""
        item = {"90001": "005930", "302": "100"}
        with patch("backend.app.services.engine_ws_dispatch.engine_account._apply_balance_realtime", new=AsyncMock(side_effect=RuntimeError("balance boom"))):
            # 예외 전파 없이 정상 반환
            await _handle_real_balance(item, item)

    @pytest.mark.asyncio
    async def test_apply_balance_normal_path_preserved(self):
        """정상 경로 회귀 보호 — _apply_balance_realtime 호출 확인."""
        item = {"90001": "005930", "302": "100"}
        with patch("backend.app.services.engine_ws_dispatch.engine_account._apply_balance_realtime", new=AsyncMock()) as mock_apply:
            await _handle_real_balance(item, item)
        mock_apply.assert_awaited_once_with(item, item)


# ── B1-02-07: start_engine 포지션 구축 격리 ──────────────────────────────────

class TestStartEngineRefreshPositionsIsolation:
    """_refresh_positions_if_dirty 예외 시에도 엔진 기동 계속 (True 반환)."""

    def _make_fake_create_task(self, fake_task):
        """create_task mock — 전달된 코루틴을 close하여 RuntimeWarning 방지."""
        def _fake(coro, *args, **kwargs):
            coro.close()
            return fake_task
        return _fake

    @pytest.mark.asyncio
    async def test_refresh_positions_exception_continues_startup(self):
        """테스트모드에서 _refresh_positions_if_dirty가 throw해도 start_engine이 True 반환 +
        후속 _apply_pending_settings_on_startup/broadcast_engine_status 실행."""
        mock_state = MagicMock()
        mock_state.engine_task = None  # 기동 전
        mock_state.running = False
        mock_state.engine_user_id = ""
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}  # is_test_mode True 유도

        fake_task = MagicMock()
        fake_task.done.return_value = False

        with (
            patch("backend.app.services.engine_lifecycle.engine_state", state=mock_state),
            patch("backend.app.services.engine_lifecycle.asyncio.create_task", side_effect=self._make_fake_create_task(fake_task)),
            patch("backend.app.services.engine_lifecycle.is_test_mode", return_value=True),
            patch("backend.app.services.engine_lifecycle._engine_loop", new=AsyncMock()),
            patch("backend.app.services.dry_run._refresh_positions_if_dirty", new=AsyncMock(side_effect=RuntimeError("positions boom"))),
            patch("backend.app.services.engine_lifecycle._apply_pending_settings_on_startup", new=AsyncMock()) as mock_pending,
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new=AsyncMock()) as mock_broadcast,
        ):
            result = await start_engine(user_id="admin")

        assert result is True
        mock_pending.assert_awaited_once()
        mock_broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_positions_normal_path_preserved(self):
        """정상 경로 회귀 보호 — _refresh_positions_if_dirty 호출 + True 반환."""
        mock_state = MagicMock()
        mock_state.engine_task = None
        mock_state.running = False
        mock_state.engine_user_id = ""
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}

        fake_task = MagicMock()
        fake_task.done.return_value = False

        with (
            patch("backend.app.services.engine_lifecycle.engine_state", state=mock_state),
            patch("backend.app.services.engine_lifecycle.asyncio.create_task", side_effect=self._make_fake_create_task(fake_task)),
            patch("backend.app.services.engine_lifecycle.is_test_mode", return_value=True),
            patch("backend.app.services.engine_lifecycle._engine_loop", new=AsyncMock()),
            patch("backend.app.services.dry_run._refresh_positions_if_dirty", new=AsyncMock()) as mock_refresh,
            patch("backend.app.services.engine_lifecycle._apply_pending_settings_on_startup", new=AsyncMock()),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new=AsyncMock()),
        ):
            result = await start_engine(user_id="admin")

        assert result is True
        mock_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_real_mode_skips_refresh_positions(self):
        """실전투자 모드 회귀 보호 — is_test_mode False 시 _refresh_positions_if_dirty 호출 안 함."""
        mock_state = MagicMock()
        mock_state.engine_task = None
        mock_state.running = False
        mock_state.engine_user_id = ""
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}

        fake_task = MagicMock()
        fake_task.done.return_value = False

        with (
            patch("backend.app.services.engine_lifecycle.engine_state", state=mock_state),
            patch("backend.app.services.engine_lifecycle.asyncio.create_task", side_effect=self._make_fake_create_task(fake_task)),
            patch("backend.app.services.engine_lifecycle.is_test_mode", return_value=False),
            patch("backend.app.services.engine_lifecycle._engine_loop", new=AsyncMock()),
            patch("backend.app.services.dry_run._refresh_positions_if_dirty", new=AsyncMock()) as mock_refresh,
            patch("backend.app.services.engine_lifecycle._apply_pending_settings_on_startup", new=AsyncMock()),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new=AsyncMock()),
        ):
            result = await start_engine(user_id="admin")

        assert result is True
        mock_refresh.assert_not_called()
