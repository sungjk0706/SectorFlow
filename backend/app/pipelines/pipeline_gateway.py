from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
UI 브로드캐스터 (Gateway Pipeline) - 파이프라인 아키텍처 Step 5

모든 연산 엔진과 OMS에서 나오는 결과값들은 직접 프론트엔드로 쏘지 말고,
오직 broadcast_queue에 put 하는 구조를 유지.

Gateway 루프는 broadcast_queue를 지속적으로 컨슘하여,
현재 연결된 모든 웹소켓 클라이언트에게 실시간 데이터를 전송(Publish).

모든 이벤트는 ws_manager.broadcast를 통해 즉시 전송.
"""

import asyncio

from backend.app.core.logger import get_logger
from backend.app.services.core_queues import get_broadcast_queue

logger = get_logger("pipeline_gateway")

_gateway_task: Optional[asyncio.Task] = None
_gateway_running: bool = False

async def start_gateway_loop() -> None:
    """Gateway 루프 시작."""
    global _gateway_task, _gateway_running

    if _gateway_running:
        logger.warning("[Gateway] 이미 실행 중")
        return

    _gateway_running = True
    _gateway_task = asyncio.get_running_loop().create_task(_gateway_loop_impl())
    logger.info("[Gateway] 루프 시작")


async def stop_gateway_loop() -> None:
    """Gateway 루프 종료."""
    global _gateway_running, _gateway_task

    _gateway_running = False
    if _gateway_task:
        _gateway_task.cancel()
        try:
            await _gateway_task
        except asyncio.CancelledError:
            pass
    logger.info("[Gateway] 루프 종료")


async def _gateway_loop_impl() -> None:
    """Gateway 루프 구현 — broadcast_queue + price_pass_through_queue 동시 구독."""
    global _gateway_running

    try:
        # 두 큐를 동시에 구독 (asyncio.gather)
        await asyncio.gather(
            _broadcast_loop(),
            _price_pass_through_loop(),
        )
    finally:
        _gateway_running = False
        logger.info("[Gateway] 루프 종료")


async def _broadcast_loop() -> None:
    """broadcast_queue 구독 루프 — sector-scores 등 연산 결과 전송."""
    global _gateway_running
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
                logger.error("[Gateway] broadcast 루프 예외 (계속): %s", e, exc_info=True)
    except asyncio.CancelledError:
        pass


async def _price_pass_through_loop() -> None:
    """price_pass_through_queue 구독 루프 — 현재가 직통 전송."""
    global _gateway_running

    # lazy import: core_queues 초기화 이후에 import
    try:
        from backend.app.services.core_queues import get_price_pass_through_queue
        pq = get_price_pass_through_queue()
    except Exception as e:
        logger.error("[Gateway] price_pass_through_queue 접근 실패: %s", e)
        return

    try:
        while _gateway_running:
            try:
                data = await pq.get()

                # 현재가 직통 전송 (sector-price-tick 이벤트)
                await _send_price_tick_to_frontend(data)

                pq.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Gateway] price_pass_through 루프 예외 (계속): %s", e, exc_info=True)
    except asyncio.CancelledError:
        pass


async def _send_price_tick_to_frontend(data: dict) -> None:
    """
    현재가 직통 전송 — sector-price-tick 이벤트로 프론트엔드 전송.

    Args:
        data: price_tick_data 딕셔너리
            {"code": ..., "raw_code": ..., "price": ..., "change": ...,
             "change_rate": ..., "sector": ..., "timestamp": ...}
    """
    try:
        from backend.app.web.ws_manager import ws_manager

        payload = {
            "code": data.get("code"),
            "raw_code": data.get("raw_code"),
            "price": data.get("price"),
            "change": data.get("change"),
            "change_rate": data.get("change_rate"),
            "sector": data.get("sector"),
            "timestamp": data.get("timestamp"),
            "_v": 1,
        }
        await ws_manager.broadcast("sector-price-tick", payload)

    except Exception as e:
        logger.error("[Gateway] sector-price-tick 전송 예외: %s", e, exc_info=True)


async def _process_broadcast(data: dict) -> None:
    """
    브로드캐스트 데이터 처리.

    WebSocket 전송.

    Args:
        data: 브로드캐스트 데이터
    """
    try:
        event_type = data.get("type")
        payload = data.get("data", {})
        await _send_to_websocket(event_type, payload)

    except Exception as e:
        logger.error("[Gateway] 브로드캐스트 처리 예외: %s", e, exc_info=True)


async def _send_to_websocket(event_type: str, data: dict) -> None:
    """
    WebSocket 전송.

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
        logger.error("[Gateway] WebSocket 전송 예외: %s", e, exc_info=True)
