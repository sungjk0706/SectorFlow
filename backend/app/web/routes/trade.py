# -*- coding: utf-8 -*-
"""거래내역 라우터 — 매수/매도 체결 이력 조회."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from backend.app.web.deps import get_current_user
from backend.app.services.trade_history import get_buy_history, get_sell_history, get_daily_summary
from backend.app.core.trading_calendar import get_previous_trading_day_str
router = APIRouter(prefix="/api/trade-history", tags=["trade-history"])


@router.get("/buy")
async def buy_history(
    today_only: bool = Query(False),
    date_from: str = Query(""),
    date_to: str = Query(""),
    trade_mode: str | None = Query(None),
    _: str = Depends(get_current_user),
):
    return await get_buy_history(today_only=today_only, date_from=date_from, date_to=date_to, trade_mode=trade_mode)


@router.get("/sell")
async def sell_history(
    today_only: bool = Query(False),
    date_from: str = Query(""),
    date_to: str = Query(""),
    trade_mode: str | None = Query(None),
    _: str = Depends(get_current_user),
):
    return await get_sell_history(today_only=today_only, date_from=date_from, date_to=date_to, trade_mode=trade_mode)


@router.get("/daily-summary")
async def daily_summary(
    days: int = Query(5),
    date_from: str = Query(""),
    date_to: str = Query(""),
    trade_mode: str | None = Query(None),
    _: str = Depends(get_current_user),
):
    return await get_daily_summary(days=days, date_from=date_from, date_to=date_to, trade_mode=trade_mode)


@router.get("/prev-trading-day")
async def prev_trading_day(
    _: str = Depends(get_current_user),
):
    """직전 거래일 반환 (YYYY-MM-DD). 수익현황 '직전' 버튼용."""
    yyyymmdd = get_previous_trading_day_str()
    return {"date": f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"}


@router.get("/deposit-history")
async def deposit_history(
    trade_mode: str | None = Query(None),
    _: str = Depends(get_current_user),
):
    """누적 드릴다운용 입금 이력 (date, daily_deposit 리스트).

    trade_mode 미지정 시 현재 거래 모드로 해결 (get_daily_summary와 동일 패턴, P23).
    P10 SSOT — account_daily_snapshot.daily_deposit 단일 소스.
    P25 격리된 실패 — 라우트 실패 시 500 에러 (프론트 빈 리스트 폴백 금지, P20).
    """
    from backend.app.db.database import get_db_connection
    from backend.app.db.stock_tables import get_deposit_history
    from backend.app.services.engine_account import get_trade_mode

    resolved_mode = trade_mode if trade_mode is not None else get_trade_mode()
    conn = await get_db_connection()
    history = await get_deposit_history(conn, trade_mode=resolved_mode)
    return {"deposit_history": history}
