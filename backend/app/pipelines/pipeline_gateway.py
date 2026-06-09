from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
UI 브로드캐스터 (Gateway Pipeline) - 파이프라인 아키텍처 Step 5

모든 연산 엔진과 OMS에서 나오는 결과값들은 직접 프론트엔드로 쏘지 말고,
오직 broadcast_queue에 put 하는 구조를 유지.

Gateway 루프는 broadcast_queue를 지속적으로 컨슘하여,
현재 연결된 모든 웹소켓 클라이언트에게 실시간 데이터를 전송(Publish).

데이터 폭주 방지(Coalescing) 적용:
- 동일 종목에 대한 시세 업데이트가 0.1초 내에 여러 번 발생하면 최신값만 골라 묶어서 한 번에 전송
"""

import asyncio
import time

from backend.app.core.logger import get_logger
from backend.app.services.core_queues import get_broadcast_queue

logger = get_logger("pipeline_gateway")

_gateway_task: Optional[asyncio.Task] = None
_gateway_running: bool = False

# Coalescing 설정
_COALESCE_MS = 100  # 0.1초 내 동일 종목 업데이트 병합
_coalesce_cache: dict[str, dict] = {}  # code -> {"data": dict, "ts": float}


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
    """Gateway 루프 구현."""
    global _gateway_running
    broadcast_queue = get_broadcast_queue()

    try:
        # ── Gateway 루프 ───────────────────────────────────────────────────────
        while _gateway_running:
            try:
                # broadcast_queue에서 데이터 꺼내기
                data = await broadcast_queue.get()

                # Coalescing 적용 후 WebSocket 전송
                await _process_broadcast(data)

                broadcast_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Gateway] 처리 예외 (계속): %s", e, exc_info=True)
    finally:
        _gateway_running = False
        logger.info("[Gateway] 루프 종료")


async def _process_broadcast(data: dict) -> None:
    """
    브로드캐스트 데이터 처리.

    Coalescing 적용 후 WebSocket 전송.

    Args:
        data: 브로드캐스트 데이터
    """
    try:
        event_type = data.get("type")
        payload = data.get("data", {})

        # 시계열 데이터(종목별)인 경우 Coalescing 적용
        if event_type in ("real-data", "trade-price", "orderbook-update"):
            code = payload.get("item")  # pipeline_compute.py:349에서 "item" 키로 설정
            if code:
                # Coalescing 체크
                if _should_coalesce(code, payload):
                    logger.debug("[Gateway] Coalescing 적용 - code=%s", code)
                    return  # 병합 처리됨 (최신값만 유지)

        # WebSocket 전송
        await _send_to_websocket(event_type, payload)

    except Exception as e:
        logger.error("[Gateway] 브로드캐스트 처리 예외: %s", e, exc_info=True)


def _should_coalesce(code: str, data: dict) -> bool:
    """
    Coalescing 체크.

    동일 종목에 대한 시세 업데이트가 0.1초 내에 여러 번 발생하면 True 반환.

    Args:
        code: 종목코드
        data: 데이터

    Returns:
        Coalescing 적용 여부
    """
    now = time.time()
    last = _coalesce_cache.get(code)

    if last is not None and (now - last["ts"]) < (_COALESCE_MS / 1000):
        # 0.1초 내 동일 종목 업데이트 - 최신값으로 덮어쓰기
        _coalesce_cache[code] = {"data": data, "ts": now}
        return True

    # Coalescing 기간 경과 - 전송
    _coalesce_cache[code] = {"data": data, "ts": now}
    return False


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

        ws_manager.broadcast(event_type, data)

    except Exception as e:
        logger.error("[Gateway] WebSocket 전송 예외: %s", e, exc_info=True)
