# -*- coding: utf-8 -*-
"""
DB Writer - 단일 쓰기 직렬화

책임:
  1. db_write_queue에서 DB 쓰기 작업 소비
  2. executemany() + 단일 트랜잭션 커밋
  3. DB 쓰기 직렬화 및 I/O 횟수 감소

특징:
  - 단일 asyncio 이벤트 루프 내에서 실행
  - aiosqlite 단일 커넥션 공유
  - asyncio.Lock으로 쓰기 구간 보호
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from backend.app.db.database import get_db_connection, get_db_lock
logger = logging.getLogger(__name__)

# ── DB Write Queue ─────────────────────────────────────────────────────────────

_DB_WRITE_QUEUE_MAXSIZE = 100
_db_write_queue: asyncio.Queue = asyncio.Queue(maxsize=_DB_WRITE_QUEUE_MAXSIZE)
_writer_task: asyncio.Task | None = None
_running: bool = False
_shutdown_event: asyncio.Event | None = None


def _get_shutdown_event() -> asyncio.Event:
    """shutdown 이벤트 반환 (lazy init)."""
    global _shutdown_event
    if _shutdown_event is None:
        _shutdown_event = asyncio.Event()
    return _shutdown_event


@dataclass
class DBWriteOperation:
    """DB 쓰기 작업"""
    table: str  # 테이블 이름
    operation: str  # "INSERT", "UPDATE", "DELETE"
    data: list[dict] | dict  # 단일 또는 다중 데이터
    query: str | None = None  # 사용자 정의 쿼리 (선택)
    params: list[tuple] | tuple | None = None  # 쿼리 파라미터
    future: asyncio.Future | None = None  # 결과 통보용 Future (선택)


# ── DB Writer Loop ─────────────────────────────────────────────────────────────

async def _db_writer_loop() -> None:
    """DB Writer 루프 - 큐에서 작업을 꺼내어 일괄 처리"""
    global _running

    _running = True

    try:
        while _running:
            try:
                queue_task = asyncio.ensure_future(_db_write_queue.get())
                shutdown_task = asyncio.ensure_future(_get_shutdown_event().wait())
                done, pending = await asyncio.wait(
                    {queue_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for t in pending:
                    t.cancel()

                if shutdown_task in done and not shutdown_task.cancelled():
                    _running = False
                    break

                if queue_task in done and not queue_task.cancelled():
                    op = queue_task.result()
                    await _process_operation(op)
                    _db_write_queue.task_done()

            except Exception as e:
                logger.error("[데이터] 작업 처리 실패: %s", e, exc_info=True)

    except asyncio.CancelledError:
        logger.info("[데이터] 반복 취소됨")
    finally:
        _running = False
        logger.info("[데이터] 반복 종료")


async def _process_operation(op: DBWriteOperation) -> None:
    """단일 DB 쓰기 작업 처리. query+params 필수 (모든 호출처가 제공)."""
    async with get_db_lock():
        conn = await get_db_connection()

        try:
            if isinstance(op.params, list) and len(op.params) > 0:
                # 일괄 실행
                await conn.executemany(op.query, op.params)
            else:
                # 단일 실행
                await conn.execute(op.query, op.params)

            await conn.commit()
            if op.future and not op.future.done():
                op.future.set_result(None)

        except Exception as e:
            await conn.rollback()
            logger.error("[데이터] 작업 실패 - 테이블=%s, 작업=%s: %s", op.table, op.operation, e, exc_info=True)
            if op.future and not op.future.done():
                op.future.set_exception(e)
            raise


# ── Public API ───────────────────────────────────────────────────────────────

async def start_db_writer() -> None:
    """DB Writer 루프 시작. 태스크 조용히 사맅 시 로깅 (P16/P21)."""
    global _writer_task

    if _writer_task is not None and not _writer_task.done():
        logger.warning("[데이터] 이미 실행 중")
        return

    _get_shutdown_event().clear()
    _writer_task = asyncio.create_task(_db_writer_loop())
    _writer_task.add_done_callback(
        lambda t: logger.warning("[데이터] DB Writer 루프 비정상 종료: %s", t.exception(), exc_info=t.exception())
        if t.exception() and not t.cancelled() else None
    )
    logger.info("[데이터] 시작됨")


async def stop_db_writer() -> None:
    """DB Writer 루프 정지"""
    global _writer_task, _running

    _running = False
    _get_shutdown_event().set()

    if _writer_task is not None:
        _writer_task.cancel()
        try:
            await _writer_task
        except asyncio.CancelledError:
            pass
        _writer_task = None

    # 큐 비우기
    while not _db_write_queue.empty():
        _db_write_queue.get_nowait()
        _db_write_queue.task_done()

    logger.info("[데이터] 정지됨")


async def enqueue_db_write(op: DBWriteOperation) -> None:
    """DB 쓰기 작업을 큐에 추가"""
    await _db_write_queue.put(op)


async def execute_db_write(op: DBWriteOperation, wait: bool = False) -> Any:
    """DB 쓰기 작업을 수행. wait=True인 경우 완료를 대기."""
    if wait:
        op.future = asyncio.get_running_loop().create_future()
    await enqueue_db_write(op)
    if wait and op.future:
        return await op.future


def get_db_write_queue() -> asyncio.Queue:
    """DB 쓰기 큐 반환"""
    return _db_write_queue


def is_writer_running() -> bool:
    """DB Writer 실행 상태 확인"""
    return _running
