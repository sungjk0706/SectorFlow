from __future__ import annotations
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

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from backend.app.db.database import get_db_connection, get_db_lock

logger = logging.getLogger(__name__)

# ── DB Write Queue ─────────────────────────────────────────────────────────────

_db_write_queue: asyncio.Queue = asyncio.Queue()
_writer_task: asyncio.Task | None = None
_running: bool = False


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
                # 큐에서 작업 꺼내기 (타임아웃으로 정기적 체크)
                op = await asyncio.wait_for(_db_write_queue.get(), timeout=1.0)

                # 작업 처리
                await _process_operation(op)

                # 작업 완료 표시
                _db_write_queue.task_done()

            except asyncio.TimeoutError:
                # 타임아웃 시 계속 루프
                continue
            except Exception as e:
                logger.error("[DB Writer] 작업 처리 실패: %s", e, exc_info=True)

    except asyncio.CancelledError:
        logger.info("[DB Writer] 루프 취소됨")
    finally:
        _running = False
        logger.info("[DB Writer] 루프 종료")


async def _process_operation(op: DBWriteOperation) -> None:
    """단일 DB 쓰기 작업 처리"""
    async with get_db_lock():
        conn = await get_db_connection()

        try:
            if op.query and op.params is not None:
                # 사용자 정의 쿼리 실행
                if isinstance(op.params, list) and len(op.params) > 0:
                    # 일괄 실행
                    await conn.executemany(op.query, op.params)
                else:
                    # 단일 실행
                    await conn.execute(op.query, op.params)
            else:
                # 기본 테이블 작업 (확장 가능)
                logger.warning("[DB Writer] 사용자 정의 쿼리 없음 - 작업 스킵: %s", op.table)
                if op.future and not op.future.done():
                    op.future.set_result(None)
                return

            await conn.commit()
            logger.debug("[DB Writer] 작업 완료 - table=%s, operation=%s", op.table, op.operation)
            if op.future and not op.future.done():
                op.future.set_result(None)

        except Exception as e:
            await conn.rollback()
            logger.error("[DB Writer] 작업 실패 - table=%s, operation=%s: %s", op.table, op.operation, e, exc_info=True)
            if op.future and not op.future.done():
                op.future.set_exception(e)
            raise


# ── Public API ───────────────────────────────────────────────────────────────

async def start_db_writer() -> None:
    """DB Writer 루프 시작"""
    global _writer_task

    if _writer_task is not None and not _writer_task.done():
        logger.warning("[DB Writer] 이미 실행 중")
        return

    _writer_task = asyncio.create_task(_db_writer_loop())
    logger.info("[DB Writer] 시작됨")


async def stop_db_writer() -> None:
    """DB Writer 루프 정지"""
    global _writer_task, _running

    _running = False

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

    logger.info("[DB Writer] 정지됨")


async def enqueue_db_write(op: DBWriteOperation) -> None:
    """DB 쓰기 작업을 큐에 추가"""
    await _db_write_queue.put(op)
    logger.debug("[DB Writer] 작업 큐에 추가 - table=%s, operation=%s", op.table, op.operation)


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
