# -*- coding: utf-8 -*-
"""거래내역 라우터 — 매수/매도 체결 이력 조회."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.web.deps import get_current_user
from app.services.trade_history import get_buy_history, get_sell_history, get_daily_summary

router = APIRouter(prefix="/api/trade-history", tags=["trade-history"])


@router.get("/buy")
async def buy_history(
    today_only: bool = Query(False),
    trade_mode: str | None = Query(None),
    _: str = Depends(get_current_user),
):
    return get_buy_history(today_only=today_only, trade_mode=trade_mode)


@router.get("/sell")
async def sell_history(
    today_only: bool = Query(False),
    trade_mode: str | None = Query(None),
    _: str = Depends(get_current_user),
):
    return get_sell_history(today_only=today_only, trade_mode=trade_mode)


@router.get("/daily-summary")
async def daily_summary(
    days: int = Query(5),
    date_from: str = Query(""),
    date_to: str = Query(""),
    trade_mode: str | None = Query(None),
    _: str = Depends(get_current_user),
):
    return get_daily_summary(days=days, date_from=date_from, date_to=date_to, trade_mode=trade_mode)
