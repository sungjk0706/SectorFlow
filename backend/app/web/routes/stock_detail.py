# -*- coding: utf-8 -*-
"""종목상세 REST API 라우터.

GET /api/stock-detail/5d-array — stock_5d_bars + master_stocks_table JOIN 조회.
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends
from backend.app.web.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stock-detail", tags=["stock-detail"])


@router.get("/5d-array")
async def get_stock_detail_5d_array(_: str = Depends(get_current_user)):
    """5일봉 거래대금/고가 배열 조회.

    stock_5d_bars 테이블에서 각 종목의 최근 5행을 날짜 내림차순으로 조회하고
    master_stocks_table에서 종목명/시장구분/NXT여부를 LEFT JOIN.
    거래대금은 백만원 단위, 고가는 원 단위 (DB 저장 단위 그대로 반환).
    """
    from backend.app.db.database import get_db_connection

    conn = await get_db_connection()
    # 1. master_stocks_table에서 종목 기본 정보 조회
    cursor = await conn.execute(
        """
        SELECT code, name, market AS market_type, nxt_enable
        FROM master_stocks_table
        ORDER BY code
        """
    )
    master_rows = await cursor.fetchall()

    # 2. stock_5d_bars에서 각 종목의 최근 5행 조회 (날짜 내림차순)
    cursor = await conn.execute(
        """
        SELECT code, dt, trade_amount, high_price
        FROM stock_5d_bars
        ORDER BY code, dt DESC
        """
    )
    bar_rows = await cursor.fetchall()

    # 3. 종목별 bars 그룹화 (최근 5행)
    from collections import defaultdict
    bars_by_code: dict[str, list] = defaultdict(list)
    latest_dt = ""
    for r in bar_rows:
        bars_by_code[r["code"]].append({
            "dt": r["dt"],
            "trade_amount": r["trade_amount"],
            "high_price": r["high_price"],
        })
        if not latest_dt or r["dt"] > latest_dt:
            latest_dt = r["dt"]

    items = []
    for row in master_rows:
        items.append(
            {
                "code": row["code"],
                "name": row["name"] or "",
                "market_type": row["market_type"] if row["market_type"] is not None else "",
                "nxt_enable": bool(row["nxt_enable"] or 0),
                "bars": bars_by_code.get(row["code"], [])[:5],
            }
        )

    return {"date": latest_dt, "items": items}
