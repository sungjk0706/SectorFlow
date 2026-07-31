# -*- coding: utf-8 -*-
"""시세/업종/레이더/매수 후보 조회 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.core.trading_calendar import is_trading_day, get_kst_today
from backend.app.services.sector_data_provider import (
    get_buy_targets_sector_stocks,
    get_sector_scores_snapshot,
    get_sector_stocks,
)
from backend.app.web.deps import get_current_user

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/market/buy-targets")
async def get_buy_targets(_: str = Depends(get_current_user)):
    """매수 후보와 차단 후보 목록을 반환."""
    return await get_buy_targets_sector_stocks()


@router.get("/market/sector-scores")
async def get_sector_scores(_: str = Depends(get_current_user)):
    """업종 점수와 컷오프 통과 업종 수를 반환."""
    scores, ranked_count = get_sector_scores_snapshot()
    return {"scores": scores, "ranked_count": ranked_count}


@router.get("/market/sector-stocks")
async def get_sector_stocks_snapshot(_: str = Depends(get_current_user)):
    """업종별 종목 시세 목록을 반환."""
    return await get_sector_stocks()


@router.get("/trading-day")
async def get_trading_day(_: str = Depends(get_current_user)):
    """오늘이 KRX 거래일인지 반환."""
    today = get_kst_today()
    return {
        "is_trading_day": is_trading_day(today),
        "today": today.isoformat(),
    }
