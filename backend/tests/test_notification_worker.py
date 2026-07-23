"""notification_worker.py 단위 테스트 — asyncio.Queue 기반 알림 워커 검증.

NotificationWorker 싱글톤의 start/enqueue/_handle/shutdown 동작 검증.
hang 방지: 실제 asyncio.create_task / Queue 사용하지 않고 mock으로 대체.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.notification_worker import NotificationWorker


def _make_worker():
    """테스트용 NotificationWorker 인스턴스 (싱글톤 경로 우회)."""
    return NotificationWorker()


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_instance_returns_same(self):
        a = NotificationWorker.get_instance()
        b = NotificationWorker.get_instance()
        assert a is b


# ── __init__ ───────────────────────────────────────────────────────────────────

class TestInit:
    def test_default_values(self):
        w = _make_worker()
        assert w._task is None
        assert w._running is False
        assert w._queue is not None

    def test_queue_maxsize(self):
        w = _make_worker()
        assert w._QUEUE_MAXSIZE == 100


# ── start ──────────────────────────────────────────────────────────────────────

class TestStart:
    def test_start_sets_running(self):
        w = _make_worker()
        with patch("backend.app.services.notification_worker.asyncio.create_task") as mock_task:
            mock_task.return_value = MagicMock(done=MagicMock(return_value=False))
            w.start()
        assert w._running is True

    def test_start_creates_task(self):
        w = _make_worker()
        mock_task_obj = MagicMock(done=MagicMock(return_value=False))
        with patch("backend.app.services.notification_worker.asyncio.create_task", return_value=mock_task_obj) as mock_ct:
            w.start()
        mock_ct.assert_called_once()

    def test_start_noop_if_task_running(self):
        w = _make_worker()
        mock_task_obj = MagicMock(done=MagicMock(return_value=False))
        w._task = mock_task_obj
        with patch("backend.app.services.notification_worker.asyncio.create_task") as mock_ct:
            w.start()
        mock_ct.assert_not_called()

    def test_start_restarts_if_task_done(self):
        w = _make_worker()
        mock_done_task = MagicMock(done=MagicMock(return_value=True))
        w._task = mock_done_task
        mock_new_task = MagicMock(done=MagicMock(return_value=False))
        with patch("backend.app.services.notification_worker.asyncio.create_task", return_value=mock_new_task) as mock_ct:
            w.start()
        mock_ct.assert_called_once()


# ── enqueue ────────────────────────────────────────────────────────────────────

class TestEnqueue:
    def test_enqueue_puts_message(self):
        w = _make_worker()
        w._task = MagicMock(done=MagicMock(return_value=False))
        mock_queue = MagicMock()
        w._queue = mock_queue
        w.enqueue({"type": "telegram", "message": "hello"})
        mock_queue.put_nowait.assert_called_once_with({"type": "telegram", "message": "hello"})

    def test_enqueue_auto_starts_if_no_task(self):
        w = _make_worker()
        mock_queue = MagicMock()
        w._queue = mock_queue
        with patch("backend.app.services.notification_worker.asyncio.create_task", return_value=MagicMock(done=MagicMock(return_value=False))):
            w.enqueue({"type": "telegram", "message": "hello"})
        mock_queue.put_nowait.assert_called_once()

    def test_enqueue_auto_starts_if_task_done(self):
        w = _make_worker()
        w._task = MagicMock(done=MagicMock(return_value=True))
        mock_queue = MagicMock()
        w._queue = mock_queue
        with patch("backend.app.services.notification_worker.asyncio.create_task", return_value=MagicMock(done=MagicMock(return_value=False))):
            w.enqueue({"type": "test", "message": "msg"})
        mock_queue.put_nowait.assert_called_once()

    def test_enqueue_queue_full_drops_message(self):
        w = _make_worker()
        w._task = MagicMock(done=MagicMock(return_value=False))
        mock_queue = MagicMock()
        mock_queue.put_nowait.side_effect = asyncio.QueueFull()
        w._queue = mock_queue
        w.enqueue({"type": "telegram", "message": "dropped"})
        mock_queue.put_nowait.assert_called_once()

    def test_enqueue_auto_start_runtime_error_handled(self):
        w = _make_worker()
        mock_queue = MagicMock()
        w._queue = mock_queue
        with patch("backend.app.services.notification_worker.asyncio.create_task", side_effect=RuntimeError("no event loop")):
            w.enqueue({"type": "telegram", "message": "msg"})
        mock_queue.put_nowait.assert_called_once()


# ── _handle ────────────────────────────────────────────────────────────────────

class TestHandle:
    @pytest.mark.asyncio
    async def test_handle_telegram_calls_send_msg(self):
        w = _make_worker()
        msg = {"type": "telegram", "message": "hello", "settings": {"token": "abc"}}
        with patch("backend.app.services.telegram.send_msg_async", new_callable=AsyncMock) as mock_send:
            await w._handle(msg)
        mock_send.assert_awaited_once_with("hello", settings={"token": "abc"})

    @pytest.mark.asyncio
    async def test_handle_telegram_no_settings(self):
        w = _make_worker()
        msg = {"type": "telegram", "message": "hello"}
        with patch("backend.app.services.telegram.send_msg_async", new_callable=AsyncMock) as mock_send:
            await w._handle(msg)
        mock_send.assert_awaited_once_with("hello", settings=None)

    @pytest.mark.asyncio
    async def test_handle_unknown_type_logs_warning(self):
        w = _make_worker()
        msg = {"type": "unknown", "message": "hello"}
        await w._handle(msg)
        # no exception

    @pytest.mark.asyncio
    async def test_handle_none_type(self):
        w = _make_worker()
        msg = {"message": "hello"}
        await w._handle(msg)
        # no exception


# ── shutdown ───────────────────────────────────────────────────────────────────

class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_empty_queue(self):
        w = _make_worker()
        w._running = True
        mock_queue = MagicMock()
        mock_queue.empty.return_value = True
        w._queue = mock_queue
        w._task = None
        await w.shutdown()
        assert w._running is False

    @pytest.mark.asyncio
    async def test_shutdown_sets_running_false(self):
        w = _make_worker()
        w._running = True
        mock_queue = MagicMock()
        mock_queue.empty.return_value = True
        w._queue = mock_queue
        await w.shutdown()
        assert w._running is False

    @pytest.mark.asyncio
    async def test_shutdown_cancels_task(self):
        w = _make_worker()
        w._running = True
        mock_queue = MagicMock()
        mock_queue.empty.return_value = True
        w._queue = mock_queue

        class _FakeTask:
            def __init__(self):
                self.cancel_called = False
            def done(self):
                return False
            def cancel(self):
                self.cancel_called = True
            def __await__(self):
                raise asyncio.CancelledError()
                yield  # pragma: no cover

        fake_task = _FakeTask()
        w._task = fake_task
        await w.shutdown()
        assert fake_task.cancel_called is True

    @pytest.mark.asyncio
    async def test_shutdown_task_already_done_no_cancel(self):
        w = _make_worker()
        w._running = True
        mock_queue = MagicMock()
        mock_queue.empty.return_value = True
        w._queue = mock_queue
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.cancel = MagicMock()
        w._task = mock_task
        await w.shutdown()
        mock_task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_non_empty_queue_waits(self):
        w = _make_worker()
        w._running = True
        mock_queue = MagicMock()
        mock_queue.empty.return_value = False
        mock_queue.qsize.return_value = 3
        mock_queue.join = AsyncMock()
        w._queue = mock_queue
        w._task = None
        await w.shutdown()
        mock_queue.join.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_non_empty_queue_timeout(self):
        w = _make_worker()
        w._running = True
        mock_queue = MagicMock()
        mock_queue.empty.return_value = False
        mock_queue.qsize.return_value = 5
        mock_queue.join = AsyncMock(side_effect=asyncio.TimeoutError())
        w._queue = mock_queue
        w._task = None
        await w.shutdown()
        assert w._running is False

    @pytest.mark.asyncio
    async def test_shutdown_no_task(self):
        w = _make_worker()
        w._running = True
        mock_queue = MagicMock()
        mock_queue.empty.return_value = True
        w._queue = mock_queue
        w._task = None
        await w.shutdown()
        assert w._running is False
