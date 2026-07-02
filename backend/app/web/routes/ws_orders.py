from __future__ import annotations
# -*- coding: utf-8 -*-
"""WebSocket 체결 전용 채널.

시세 폭주가 체결 이벤트를 막지 않도록 별도 채널로 분리."""

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.app.web.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["websocket"])


@router.websocket("/orders")
async def ws_orders(websocket: WebSocket, token: str = Query(...)):
    """체결 전용 WebSocket 엔드포인트."""
    # TODO: 개발 완료 후 토큰 검증 재활성화
    username = "dev"

    await websocket.accept()
    await ws_manager.register(websocket)
    logger.info(
        "[연결] 체결채널 연결 (user=%s, 총 %d)", username, ws_manager.client_count
    )

    try:
        # 수신 루프: ping → pong
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("[연결] 체결채널 오류: %s", e)
    finally:
        ws_manager.unregister(websocket)
        logger.info("[연결] 체결채널 해제 (총 %d)", ws_manager.client_count)
