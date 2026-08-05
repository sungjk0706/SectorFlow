"""db_writer.py 단위 테스트 — B4-06-01 task_done 보장 검증.

_process_operation 실패 시에도 task_done()이 호출되어 큐 미완료 카운트가
누적되지 않는지 검증 (P25 격리된 실패). graceful shutdown queue.join() 무한 대기 방지.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.db.db_writer import DBWriteOperation, _db_writer_loop, _process_operation


# ── _process_operation — 실패 시 task_done 보장 (B4-06-01) ──────────────────────

class TestDbWriterLoopTaskDoneGuarantee:
    """B4-06-01: _process_operation 실패 시에도 task_done() 호출 검증."""

    @pytest.mark.asyncio
    async def test_process_operation_failure_calls_task_done(self):
        """_process_operation 예외 → task_done() 호출 (큐 미완료 누적 방지, P25)."""
        # 로컬 fresh 큐 사용 — 모듈 수준 큐가 다른 이벤트 루프에 바인딩되어 있을 수 있음.
        local_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        op = DBWriteOperation(table="t", operation="INSERT", data={}, query="INSERT INTO t VALUES (?)", params=[("x",)])
        await local_queue.put(op)

        # task_done 호출 추적 — 원래 메서드를 spy로 감싸 카운트 기록
        task_done_calls = []
        original_task_done = local_queue.task_done

        def _spy_task_done():
            task_done_calls.append(1)
            return original_task_done()

        local_queue.task_done = _spy_task_done  # type: ignore[assignment]

        shutdown_evt = asyncio.Event()

        async def _trigger_shutdown_after_one_iter():
            await asyncio.sleep(0.05)
            shutdown_evt.set()

        trigger_task = asyncio.create_task(_trigger_shutdown_after_one_iter())

        # _process_operation이 예외를 raise하도록 강제
        with patch("backend.app.db.db_writer._process_operation", new_callable=AsyncMock, side_effect=Exception("DB fail")), \
             patch("backend.app.db.db_writer._db_write_queue", local_queue), \
             patch("backend.app.db.db_writer._get_shutdown_event", return_value=shutdown_evt):
            try:
                await _db_writer_loop()
            except Exception:
                # 외부 except에서 로깅하므로 루프 자체는 종료되지 않음 — 여기서는 무시
                pass
            finally:
                trigger_task.cancel()
                try:
                    await trigger_task
                except asyncio.CancelledError:
                    pass

        # task_done이 호출되었는지 검증 (B4-06-01 핵심)
        assert len(task_done_calls) == 1, f"task_done 미호출 — 큐 미완료 누적 위험. calls={task_done_calls}"

    @pytest.mark.asyncio
    async def test_process_operation_success_calls_task_done(self):
        """_process_operation 성공 → task_done() 호출 (회귀 보호)."""
        local_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        op = DBWriteOperation(table="t", operation="INSERT", data={}, query="INSERT INTO t VALUES (?)", params=[("x",)])
        await local_queue.put(op)

        task_done_calls = []
        original_task_done = local_queue.task_done

        def _spy_task_done():
            task_done_calls.append(1)
            return original_task_done()

        local_queue.task_done = _spy_task_done  # type: ignore[assignment]

        shutdown_evt = asyncio.Event()

        async def _trigger_shutdown_after_one_iter():
            await asyncio.sleep(0.05)
            shutdown_evt.set()

        trigger_task = asyncio.create_task(_trigger_shutdown_after_one_iter())
        success_mock = AsyncMock()
        with patch("backend.app.db.db_writer._process_operation", success_mock), \
             patch("backend.app.db.db_writer._db_write_queue", local_queue), \
             patch("backend.app.db.db_writer._get_shutdown_event", return_value=shutdown_evt):
            try:
                await _db_writer_loop()
            finally:
                trigger_task.cancel()
                try:
                    await trigger_task
                except asyncio.CancelledError:
                    pass

        success_mock.assert_awaited_once()
        assert len(task_done_calls) == 1


# ── _process_operation — 단위 ──────────────────────────────────────────────────

class TestProcessOperation:
    """_process_operation 자체 동작 — 롤백 + future 예외 전파."""

    @pytest.mark.asyncio
    async def test_execute_failure_rolls_back_and_raises(self):
        """executemany 실패 → rollback + future.set_exception + raise."""
        conn = MagicMock()
        conn.executemany = AsyncMock(side_effect=Exception("exec fail"))
        conn.rollback = AsyncMock()
        conn.commit = AsyncMock()

        lock = MagicMock()
        lock.__aenter__ = AsyncMock(return_value=lock)
        lock.__aexit__ = AsyncMock(return_value=None)

        future = asyncio.get_running_loop().create_future()
        op = DBWriteOperation(
            table="t", operation="INSERT", data={},
            query="INSERT INTO t VALUES (?)", params=[("x",)],
            future=future,
        )

        with patch("backend.app.db.db_writer.get_db_connection", new_callable=AsyncMock, return_value=conn), \
             patch("backend.app.db.db_writer.get_db_lock", return_value=lock):
            with pytest.raises(Exception, match="exec fail"):
                await _process_operation(op)

        conn.rollback.assert_awaited_once()
        assert future.done()
        with pytest.raises(Exception, match="exec fail"):
            future.result()
