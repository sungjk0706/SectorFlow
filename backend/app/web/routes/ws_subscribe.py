# -*- coding: utf-8 -*-
"""WS 구독 제어 라우터 — 업종(0U) / 지수(0J) / 실시간시세(0B) 수동 시작·중지."""
from __future__ import annotations
from enum import Enum
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.app.web.deps import get_current_user
router = APIRouter(prefix="/api/ws-subscribe", tags=["ws-subscribe"])


class SubscribeGroup(str, Enum):
    sector = "sector"       # 하위 호환: industry 동시 제어
    industry = "industry"   # grp 5 (0U)
    quote = "quote"         # grp 4 (0B)


class SubscribeRequest(BaseModel):
    group: SubscribeGroup


@router.post("/start")
async def start_subscription(
    body: SubscribeRequest,
    _: str = Depends(get_current_user),
):
    """수동 구독 시작. WS 구독 구간 밖이면 400 에러."""
    from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
    from backend.app.services.engine_state import state

    settings = state.integrated_system_settings_cache
    if not await is_ws_subscribe_window(settings):
        raise HTTPException(status_code=400, detail="WS 구독 구간이 아닙니다")

    from backend.app.services import ws_subscribe_control

    if body.group == SubscribeGroup.sector:
        # 업종 구독 폐지됨 (sector_mapping 기반 자체 집계)
        return {"ok": True, "status": ws_subscribe_control.get_subscribe_status()}
    elif body.group == SubscribeGroup.industry:
        # 업종 구독 폐지됨 (sector_mapping 기반 자체 집계)
        return {"ok": True, "status": ws_subscribe_control.get_subscribe_status()}
    else:
        result = await ws_subscribe_control.start_quote()

    if not result.get("ok"):
        return {"ok": False, "message": result.get("message", "알 수 없는 오류")}
    return {"ok": True, "status": result["status"]}


@router.post("/stop")
async def stop_subscription(
    body: SubscribeRequest,
    _: str = Depends(get_current_user),
):
    """수동 구독 해지."""
    from backend.app.services import ws_subscribe_control

    if body.group == SubscribeGroup.sector:
        # 업종 구독 폐지됨 (sector_mapping 기반 자체 집계)
        return {"ok": True, "status": ws_subscribe_control.get_subscribe_status()}
    elif body.group == SubscribeGroup.industry:
        # 업종 구독 폐지됨 (sector_mapping 기반 자체 집계)
        return {"ok": True, "status": ws_subscribe_control.get_subscribe_status()}
    else:
        result = await ws_subscribe_control.stop_quote()

    if not result.get("ok"):
        return {"ok": False, "message": result.get("message", "알 수 없는 오류")}
    return {"ok": True, "status": result["status"]}
