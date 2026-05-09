# -*- coding: utf-8 -*-
"""WS 구독 제어 라우터 — 업종(0U) / 지수(0J) / 실시간시세(0B) 수동 시작·중지."""
from __future__ import annotations

import sys
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.web.deps import get_current_user

router = APIRouter(prefix="/api/ws-subscribe", tags=["ws-subscribe"])


class SubscribeGroup(str, Enum):
    sector = "sector"       # 하위 호환: industry + index 동시 제어
    industry = "industry"   # grp 5 (0U)
    index = "index"         # grp 2 (0J)
    quote = "quote"         # grp 4 (0B)


class SubscribeRequest(BaseModel):
    group: SubscribeGroup


@router.post("/start")
async def start_subscription(
    body: SubscribeRequest,
    _: str = Depends(get_current_user),
):
    """수동 구독 시작. WS 구독 구간 밖이면 400 에러."""
    from app.services.daily_time_scheduler import is_ws_subscribe_window
    import app.services.engine_service as es

    settings = getattr(es, "_settings_cache", None) or {}
    if not is_ws_subscribe_window(settings):
        raise HTTPException(status_code=400, detail="WS 구독 구간이 아닙니다")

    from app.services import ws_subscribe_control
    _es = sys.modules["app.services.engine_service"]

    if body.group == SubscribeGroup.sector:
        # 하위 호환: industry + index 동시 시작
        r1 = await ws_subscribe_control.start_industry(_es)
        r2 = await ws_subscribe_control.start_index(_es)
        if not r1.get("ok") and not r2.get("ok"):
            return {"ok": False, "message": r1.get("message", "알 수 없는 오류")}
        return {"ok": True, "status": ws_subscribe_control.get_subscribe_status()}
    elif body.group == SubscribeGroup.industry:
        result = await ws_subscribe_control.start_industry(_es)
    elif body.group == SubscribeGroup.index:
        result = await ws_subscribe_control.start_index(_es)
    else:
        result = await ws_subscribe_control.start_quote(_es)

    if not result.get("ok"):
        return {"ok": False, "message": result.get("message", "알 수 없는 오류")}
    return {"ok": True, "status": result["status"]}


@router.post("/stop")
async def stop_subscription(
    body: SubscribeRequest,
    _: str = Depends(get_current_user),
):
    """수동 구독 해지."""
    from app.services import ws_subscribe_control
    _es = sys.modules["app.services.engine_service"]

    if body.group == SubscribeGroup.sector:
        # 하위 호환: industry + index 동시 해지
        r1 = await ws_subscribe_control.stop_industry(_es)
        r2 = await ws_subscribe_control.stop_index(_es)
        if not r1.get("ok") and not r2.get("ok"):
            return {"ok": False, "message": r1.get("message", "알 수 없는 오류")}
        return {"ok": True, "status": ws_subscribe_control.get_subscribe_status()}
    elif body.group == SubscribeGroup.industry:
        result = await ws_subscribe_control.stop_industry(_es)
    elif body.group == SubscribeGroup.index:
        result = await ws_subscribe_control.stop_index(_es)
    else:
        result = await ws_subscribe_control.stop_quote(_es)

    if not result.get("ok"):
        return {"ok": False, "message": result.get("message", "알 수 없는 오류")}
    return {"ok": True, "status": result["status"]}
