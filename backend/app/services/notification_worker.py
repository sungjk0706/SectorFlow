# -*- coding: utf-8 -*-
"""
Notification Worker — asyncio.Queue 기반 알림/파일저장 워커 (싱글톤).

REAL Consumer 경로에서 텔레그램 전송 + 파일 저장을 별도 태스크로 격리.
모든 I/O는 비동기로 처리하며, 예외 발생 시 로깅 후 다음 항목 계속 처리.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class NotificationWorker:
    """asyncio.Queue 기반 알림/파일저장 워커 (싱글톤)."""

    _instance: NotificationWorker | None = None

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running: bool = False

    @classmethod
    def get_instance(cls) -> NotificationWorker:
        """싱글톤 인스턴스 반환."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        """워커 태스크 시작. 이미 실행 중이면 no-op."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        logger.info("[NotificationWorker] 워커 태스크 시작")

    def enqueue(self, msg: dict) -> None:
        """큐에 메시지 추가 (논블로킹). 워커 미시작이면 자동 시작."""
        if not self._task or self._task.done():
            try:
                self.start()
            except RuntimeError:
                pass
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("[NotificationWorker] 큐 가득 참 -- 메시지 드롭: %s", msg.get("type"))

    async def _consume_loop(self) -> None:
        """큐 소비 루프. 예외 격리."""
        while self._running:
            try:
                msg = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._handle(msg)
            except Exception as e:
                logger.warning("[NotificationWorker] 처리 실패 (계속): %s", e)
            finally:
                self._queue.task_done()

    async def _handle(self, msg: dict) -> None:
        """메시지 타입별 핸들러 라우팅."""
        msg_type = msg.get("type")
        if msg_type == "telegram":
            from app.services import telegram
            await telegram.send_msg_async(
                msg["message"], settings=msg.get("settings"),
            )
        elif msg_type == "file_save":
            save_fn = msg.get("save_fn")
            if save_fn:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, save_fn)
        else:
            logger.warning("[NotificationWorker] 알 수 없는 메시지 타입: %s", msg_type)

    async def shutdown(self) -> None:
        """큐 잔여 항목 처리 후 종료 (graceful shutdown)."""
        self._running = False
        if not self._queue.empty():
            logger.info("[NotificationWorker] 종료 대기 -- 큐 잔량 %d건", self._queue.qsize())
            try:
                await asyncio.wait_for(self._queue.join(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("[NotificationWorker] 종료 타임아웃 -- 큐 잔량 %d건 드롭", self._queue.qsize())
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[NotificationWorker] 워커 종료 완료")

    @classmethod
    def reset_instance(cls) -> None:
        """테스트용 싱글톤 리셋."""
        cls._instance = None
