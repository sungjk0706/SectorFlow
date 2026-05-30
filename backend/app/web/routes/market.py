from __future__ import annotations
# -*- coding: utf-8 -*-
"""시세/섹터/레이더/매수후보 라우터 — GET 엔드포인트는 WS initial-snapshot으로 대체됨."""

from fastapi import APIRouter, Depends

from backend.app.core.trading_calendar import is_trading_day, get_kst_today
from backend.app.web.deps import get_current_user

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/trading-day")
async def get_trading_day(_: str = Depends(get_current_user)):
    """오늘이 KRX 거래일인지 반환."""
    today = get_kst_today()
    return {
        "is_trading_day": is_trading_day(today),
        "today": today.isoformat(),
    }
