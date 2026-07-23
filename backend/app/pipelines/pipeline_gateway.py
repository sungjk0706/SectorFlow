# -*- coding: utf-8 -*-
"""
화면 전송기 (게이트웨이 파이프라인) - 파이프라인 아키텍처 Step 5

전송 경로 (P23 일관성):
- 01/0B 틱 (현재가/등락률/체결강도/거래대금): broadcast_queue에 put → 게이트웨이 반복이 컨슘하여 전송
- 0D/PGM 틱 (호가잔량비/프로그램 순매수): notify_orderbook_update/notify_program_update가
  ws_manager.broadcast 직접 호출 (매수 후보만, broadcast_queue 우회)

게이트웨이 반복은 broadcast_queue를 지속적으로 컨슘하여,
현재 연결된 모든 웹소켓 클라이언트에게 실시간 데이터를 전송(Publish).
"""
from __future__ import annotations
from typing import Optional
import asyncio
import logging
from backend.app.services.core_queues import get_broadcast_queue
logger = logging.getLogger(__name__)

_gateway_task: Optional[asyncio.Task] = None
_gateway_running: bool = False

async def start_gateway_loop() -> None:
    """게이트웨이 반복 시작."""
    global _gateway_task, _gateway_running

    if _gateway_running:
        logger.warning("[연결] 이미 실행 중")
        return

    _gateway_running = True
    _gateway_task = asyncio.get_running_loop().create_task(_gateway_loop_impl())
    _gateway_task.add_done_callback(
        lambda t: logger.warning("[연결] 게이트웨이 루프 작업 실패: %s", t.exception())
        if t.exception() else None
    )
    logger.info("[연결] 반복 시작")


async def stop_gateway_loop() -> None:
    """게이트웨이 반복 종료."""
    global _gateway_running, _gateway_task

    _gateway_running = False
    if _gateway_task:
        _gateway_task.cancel()
        try:
            await _gateway_task
        except asyncio.CancelledError:
            pass
        _gateway_task = None
    logger.info("[연결] 반복 종료")


async def _gateway_loop_impl() -> None:
    """게이트웨이 반복 구현 — broadcast_queue 구독."""
    global _gateway_running

    try:
        await _broadcast_loop()
    finally:
        _gateway_running = False
        logger.info("[연결] 반복 종료")


async def _broadcast_loop() -> None:
    """broadcast_queue 구독 반복 — sector-scores 등 연산 결과 전송."""
    broadcast_queue = get_broadcast_queue()

    try:
        while _gateway_running:
            try:
                data = await broadcast_queue.get()

                await _process_broadcast(data)

                broadcast_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[연결] 전송 반복 오류 (계속): %s", e, exc_info=True)
    except asyncio.CancelledError:
        pass


async def _process_broadcast(data: dict) -> None:
    """
    전송 데이터 처리.

    실시간 통신 전송.

    Args:
        data: 전송 데이터
    """
    try:
        event_type = data.get("type")
        payload = data.get("data", {})
        if event_type is None:
            return
        await _send_to_websocket(event_type, payload)

    except Exception as e:
        logger.error("[연결] 전송 처리 오류: %s", e, exc_info=True)


async def _send_to_websocket(event_type: str, data: dict) -> None:
    """
    실시간 통신 전송.

    Args:
        event_type: 이벤트 타입
        data: 데이터
    """
    try:
        from backend.app.web.ws_manager import ws_manager

        if "_v" not in data:
            data["_v"] = 1

        await ws_manager.broadcast(event_type, data)

    except Exception as e:
        logger.error("[연결] 실시간 통신 전송 오류: %s", e, exc_info=True)
