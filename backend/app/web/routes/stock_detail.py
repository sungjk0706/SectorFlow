# -*- coding: utf-8 -*-
"""종목상세 REST API 라우터.

GET /api/stock-detail/5d-array — stock_5d_array + master_stocks_table JOIN 조회.
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

    stock_5d_array 테이블과 master_stocks_table을 LEFT JOIN하여 종목명 포함.
    거래대금은 백만원 단위, 고가는 원 단위 (DB 저장 단위 그대로 반환).
    """
    from backend.app.db.database import get_db_connection

    conn = await get_db_connection()
    cursor = await conn.execute(
        """
        SELECT
            a.code,
            a.date,
            a.day1_amount, a.day2_amount, a.day3_amount, a.day4_amount, a.day5_amount,
            a.day1_high,   a.day2_high,   a.day3_high,   a.day4_high,   a.day5_high,
            m.name,
            m.market AS market_type,
            m.nxt_enable
        FROM stock_5d_array a
        LEFT JOIN master_stocks_table m ON a.code = m.code
        ORDER BY a.code
        """
    )
    rows = await cursor.fetchall()

    date = ""
    items = []
    for row in rows:
        if not date:
            date = row["date"] or ""
        items.append(
            {
                "code": row["code"],
                "name": row["name"] or "",
                "market_type": row["market_type"] if row["market_type"] is not None else "",
                "nxt_enable": bool(row["nxt_enable"] or 0),
                "day1_amount": row["day1_amount"],
                "day2_amount": row["day2_amount"],
                "day3_amount": row["day3_amount"],
                "day4_amount": row["day4_amount"],
                "day5_amount": row["day5_amount"],
                "day1_high": row["day1_high"],
                "day2_high": row["day2_high"],
                "day3_high": row["day3_high"],
                "day4_high": row["day4_high"],
                "day5_high": row["day5_high"],
            }
        )

    return {"date": date, "items": items}
