# -*- coding: utf-8 -*-
"""WebSocket 설정/진행률 전용 채널.

시세 폭주가 설정/진행률 이벤트를 막지 않도록 별도 채널로 분리."""
from __future__ import annotations
import json
import logging
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from backend.app.web.ws_manager import ws_manager
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["websocket"])


@router.websocket("/settings")
async def ws_settings(websocket: WebSocket, token: str = Query(...)):
    """설정/진행률 전용 WebSocket 엔드포인트."""
    # TODO: 개발 완료 후 토큰 검증 재활성화
    username = "dev"

    await websocket.accept()
    await ws_manager.register(websocket)
    logger.info(
        "[연결] 설정 채널 연결 (사용자=%s, 총 %d)", username, ws_manager.client_count
    )

    try:
        # 수신 루프: ping → pong, page-active/page-inactive → 페이지 추적
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
            elif msg_type == "page-active":
                page = msg.get("page", "")
                if page:
                    ws_manager.set_active_page(websocket, page)
            elif msg_type == "page-inactive":
                ws_manager.clear_active_page(websocket)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("[연결] 설정 채널 오류: %s", e)
    finally:
        ws_manager.unregister(websocket)
        logger.info("[연결] 설정 채널 해제 (총 %d)", ws_manager.client_count)
