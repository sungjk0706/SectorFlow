# -*- coding: utf-8 -*-
"""계좌/잔고/수익 조회 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.services import engine_account
from backend.app.services.engine_account_notify import get_freshness
from backend.app.web.deps import get_current_user

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/account/snapshot")
async def get_account_snapshot(_: str = Depends(get_current_user)):
    """현재 계좌 스냅샷을 반환."""
    return {"data": await engine_account.get_account_snapshot(), "freshness": get_freshness("account")}


@router.get("/account/positions")
async def get_account_positions(_: str = Depends(get_current_user)):
    """현재 보유 종목 목록을 반환."""
    return {"data": await engine_account.get_positions(), "freshness": get_freshness("account")}
