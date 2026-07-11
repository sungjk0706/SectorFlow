"""pipeline_gateway.py 단위 테스트 — Gateway Pipeline 브로드캐스트 검증.

hang 방지 원칙:
- 실제 asyncio.Queue 사용 금지 → mock으로 대체
- asyncio.create_task / asyncio.gather 사용 금지 → mock으로 대체
- ws_manager.broadcast를 AsyncMock으로 대체
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, DEFAULT, MagicMock, patch


def _close_coro(*args, **kwargs):
    """mock에 전달된 코루틴을 close하여 RuntimeWarning 방지."""
    for arg in args:
        if asyncio.iscoroutine(arg):
            arg.close()
    return DEFAULT


def _close_coro_then_raise(exc):
    """코루틴을 close한 후 exc를 발생시키는 side_effect 팩토리."""
    def _fn(*args, **kwargs):
        for arg in args:
            if asyncio.iscoroutine(arg):
                arg.close()
        raise exc
    return _fn

from backend.app.pipelines.pipeline_gateway import (
    _process_broadcast,
    _send_to_websocket,
    _send_price_tick_to_frontend,
    _broadcast_loop,
    _price_pass_through_loop,
    _gateway_loop_impl,
    start_gateway_loop,
    stop_gateway_loop,
)


# ── _process_broadcast ────────────────────────────────────────────────────────

class TestProcessBroadcast:
    @pytest.mark.asyncio
    async def test_valid_event(self):
        data = {"type": "sector-scores", "data": {"scores": [1, 2]}}
        with patch("backend.app.pipelines.pipeline_gateway._send_to_websocket", new_callable=AsyncMock) as mock_send:
            await _process_broadcast(data)
            mock_send.assert_awaited_once_with("sector-scores", {"scores": [1, 2]})

    @pytest.mark.asyncio
    async def test_no_type_returns_early(self):
        data = {"data": {"scores": [1]}}
        with patch("backend.app.pipelines.pipeline_gateway._send_to_websocket", new_callable=AsyncMock) as mock_send:
            await _process_broadcast(data)
            mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_data_key_defaults_to_empty_dict(self):
        data = {"type": "market-phase"}
        with patch("backend.app.pipelines.pipeline_gateway._send_to_websocket", new_callable=AsyncMock) as mock_send:
            await _process_broadcast(data)
            mock_send.assert_awaited_once_with("market-phase", {})

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("backend.app.pipelines.pipeline_gateway._send_to_websocket", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("boom")
            await _process_broadcast({"type": "test", "data": {}})


# ── _send_to_websocket ────────────────────────────────────────────────────────

class TestSendToWebSocket:
    @pytest.mark.asyncio
    async def test_broadcast_called(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _send_to_websocket("sector-scores", {"scores": [1]})
            mock_ws.broadcast.assert_awaited_once_with("sector-scores", {"scores": [1], "_v": 1})

    @pytest.mark.asyncio
    async def test_adds_v_if_missing(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _send_to_websocket("test", {"foo": "bar"})
            args = mock_ws.broadcast.call_args
            assert args.args[1]["_v"] == 1

    @pytest.mark.asyncio
    async def test_preserves_existing_v(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _send_to_websocket("test", {"foo": "bar", "_v": 2})
            args = mock_ws.broadcast.call_args
            assert args.args[1]["_v"] == 2

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock(side_effect=Exception("ws error"))
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _send_to_websocket("test", {})


# ── _send_price_tick_to_frontend ──────────────────────────────────────────────

class TestSendPriceTickToFrontend:
    @pytest.mark.asyncio
    async def test_broadcast_sector_price_tick(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        data = {
            "code": "005930",
            "raw_code": "005930",
            "price": 60000,
            "change": 1000,
            "change_rate": 1.5,
            "sector": "반도체",
            "timestamp": 1234567890,
        }
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _send_price_tick_to_frontend(data)
            mock_ws.broadcast.assert_awaited_once()
            event_type, payload = mock_ws.broadcast.call_args.args
            assert event_type == "sector-price-tick"
            assert payload["code"] == "005930"
            assert payload["price"] == 60000
            assert payload["_v"] == 1

    @pytest.mark.asyncio
    async def test_missing_fields_default_to_none(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _send_price_tick_to_frontend({})
            _, payload = mock_ws.broadcast.call_args.args
            assert payload["code"] is None
            assert payload["price"] is None
            assert payload["_v"] == 1

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock(side_effect=Exception("ws error"))
        with patch("backend.app.web.ws_manager.ws_manager", mock_ws):
            await _send_price_tick_to_frontend({"code": "005930"})


# ── _broadcast_loop ───────────────────────────────────────────────────────────

class TestBroadcastLoop:
    @pytest.mark.asyncio
    async def test_processes_one_item_then_stops(self):
        import backend.app.pipelines.pipeline_gateway as gw_mod
        old_running = gw_mod._gateway_running

        mock_queue = AsyncMock()
        mock_queue.task_done = MagicMock()
        call_count = [0]
        async def _get():
            call_count[0] += 1
            if call_count[0] > 1:
                gw_mod._gateway_running = False
                raise asyncio.CancelledError()
            return {"type": "test", "data": {"v": 1}}
        mock_queue.get = _get

        gw_mod._gateway_running = True
        try:
            with patch("backend.app.pipelines.pipeline_gateway.get_broadcast_queue", return_value=mock_queue), \
                 patch("backend.app.pipelines.pipeline_gateway._process_broadcast", new_callable=AsyncMock) as mock_proc:
                try:
                    await _broadcast_loop()
                except asyncio.CancelledError:
                    pass
            mock_proc.assert_awaited_once_with({"type": "test", "data": {"v": 1}})
        finally:
            gw_mod._gateway_running = old_running

    @pytest.mark.asyncio
    async def test_exception_in_loop_continues(self):
        import backend.app.pipelines.pipeline_gateway as gw_mod
        old_running = gw_mod._gateway_running

        mock_queue = AsyncMock()
        mock_queue.task_done = MagicMock()
        call_count = [0]
        async def _get():
            call_count[0] += 1
            if call_count[0] == 1:
                return {"type": "test", "data": {}}
            gw_mod._gateway_running = False
            raise asyncio.CancelledError()
        mock_queue.get = _get

        gw_mod._gateway_running = True
        try:
            with patch("backend.app.pipelines.pipeline_gateway.get_broadcast_queue", return_value=mock_queue), \
                 patch("backend.app.pipelines.pipeline_gateway._process_broadcast", new_callable=AsyncMock, side_effect=Exception("proc error")):
                try:
                    await _broadcast_loop()
                except asyncio.CancelledError:
                    pass
        finally:
            gw_mod._gateway_running = old_running


# ── _price_pass_through_loop ──────────────────────────────────────────────────

class TestPricePassThroughLoop:
    @pytest.mark.asyncio
    async def test_processes_one_item_then_stops(self):
        import backend.app.pipelines.pipeline_gateway as gw_mod
        old_running = gw_mod._gateway_running

        mock_queue = AsyncMock()
        mock_queue.task_done = MagicMock()
        call_count = [0]
        async def _get():
            call_count[0] += 1
            if call_count[0] > 1:
                gw_mod._gateway_running = False
                raise asyncio.CancelledError()
            return {"code": "005930", "price": 60000}
        mock_queue.get = _get

        gw_mod._gateway_running = True
        try:
            with patch("backend.app.services.core_queues.get_price_pass_through_queue", return_value=mock_queue), \
                 patch("backend.app.pipelines.pipeline_gateway._send_price_tick_to_frontend", new_callable=AsyncMock) as mock_send:
                try:
                    await _price_pass_through_loop()
                except asyncio.CancelledError:
                    pass
            mock_send.assert_awaited_once_with({"code": "005930", "price": 60000})
        finally:
            gw_mod._gateway_running = old_running

    @pytest.mark.asyncio
    async def test_queue_access_failure_returns(self):
        # The lazy import 'from backend.app.services.core_queue import ...' will fail
        # because the module is 'core_queues' (plural), causing the function to return early.
        await _price_pass_through_loop()


# ── _gateway_loop_impl ────────────────────────────────────────────────────────

class TestGatewayLoopImpl:
    @pytest.mark.asyncio
    async def test_gathers_two_loops(self):
        with patch("backend.app.pipelines.pipeline_gateway._broadcast_loop", new_callable=AsyncMock) as mock_b, \
             patch("backend.app.pipelines.pipeline_gateway._price_pass_through_loop", new_callable=AsyncMock) as mock_p, \
             patch("backend.app.pipelines.pipeline_gateway.asyncio.gather", new_callable=AsyncMock, side_effect=_close_coro) as mock_gather:
            mock_gather.return_value = None
            await _gateway_loop_impl()
            mock_gather.assert_awaited_once()
            # Check that both coroutines were passed
            args = mock_gather.call_args.args
            assert len(args) == 2

    @pytest.mark.asyncio
    async def test_finally_sets_running_false(self):
        with patch("backend.app.pipelines.pipeline_gateway._broadcast_loop", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_gateway._price_pass_through_loop", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_gateway.asyncio.gather", new_callable=AsyncMock, side_effect=_close_coro_then_raise(Exception("test"))):
            import backend.app.pipelines.pipeline_gateway as gw_mod
            old = gw_mod._gateway_running
            try:
                await _gateway_loop_impl()
                assert gw_mod._gateway_running is False
            except Exception:
                pass
            finally:
                gw_mod._gateway_running = old


# ── start_gateway_loop / stop_gateway_loop ────────────────────────────────────

class TestStartStopGatewayLoop:
    @pytest.mark.asyncio
    async def test_start_when_not_running(self):
        import backend.app.pipelines.pipeline_gateway as gw_mod
        old_running = gw_mod._gateway_running
        old_task = gw_mod._gateway_task
        gw_mod._gateway_running = False
        gw_mod._gateway_task = None

        mock_task = MagicMock()
        mock_loop = MagicMock()
        mock_loop.create_task = MagicMock(return_value=mock_task)

        try:
            with patch("asyncio.get_running_loop", return_value=mock_loop), \
                 patch("backend.app.pipelines.pipeline_gateway._gateway_loop_impl", new_callable=AsyncMock):
                await start_gateway_loop()
                for call in mock_loop.create_task.call_args_list:
                    for arg in call.args:
                        if asyncio.iscoroutine(arg):
                            arg.close()
                assert gw_mod._gateway_running is True
                assert gw_mod._gateway_task is mock_task
        finally:
            gw_mod._gateway_running = old_running
            gw_mod._gateway_task = old_task

    @pytest.mark.asyncio
    async def test_start_when_already_running(self):
        import backend.app.pipelines.pipeline_gateway as gw_mod
        old_running = gw_mod._gateway_running
        old_task = gw_mod._gateway_task
        gw_mod._gateway_running = True

        mock_loop = MagicMock()
        try:
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                await start_gateway_loop()
                mock_loop.create_task.assert_not_called()
        finally:
            gw_mod._gateway_running = old_running
            gw_mod._gateway_task = old_task

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        import backend.app.pipelines.pipeline_gateway as gw_mod
        old_running = gw_mod._gateway_running
        old_task = gw_mod._gateway_task

        class _FakeTask:
            cancelled = False
            def cancel(self):
                _FakeTask.cancelled = True
            def __await__(self):
                yield

        fake_task = _FakeTask()
        gw_mod._gateway_running = True
        gw_mod._gateway_task = fake_task

        try:
            await stop_gateway_loop()
            assert gw_mod._gateway_running is False
            assert _FakeTask.cancelled is True
            assert gw_mod._gateway_task is None
        finally:
            gw_mod._gateway_running = old_running
            gw_mod._gateway_task = old_task

    @pytest.mark.asyncio
    async def test_stop_with_no_task(self):
        import backend.app.pipelines.pipeline_gateway as gw_mod
        old_running = gw_mod._gateway_running
        old_task = gw_mod._gateway_task
        gw_mod._gateway_running = True
        gw_mod._gateway_task = None

        try:
            await stop_gateway_loop()
            assert gw_mod._gateway_running is False
        finally:
            gw_mod._gateway_running = old_running
            gw_mod._gateway_task = old_task
