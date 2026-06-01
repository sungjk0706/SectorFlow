# -*- coding: utf-8 -*-
"""
CustomSector — 사용자 커스텀 업종 데이터 관리 (증권사 API 비종속)

업종 데이터는 사용자가 직접 정의하는 커스텀 데이터이므로,
특정 증권사 API와 무관하게 DB(master_stocks_table, sectors)에서 직접 조회합니다.
"""

import logging
from typing import Callable, Optional

from backend.app.db.database import get_db_connection

logger = logging.getLogger(__name__)


class CustomSector:
    """사용자 커스텀 업종 데이터 관리 (증권사 API 비종속)"""

    def __init__(self):
        pass

    async def fetch_daily_price(
        self, stk_cd: str, qry_dt: str
    ) -> dict | None:
        """master_stocks_table에서 일별 주가 조회."""
        try:
            conn = await get_db_connection()
            cursor = await conn.execute(
                "SELECT code, name, cur_price, change, change_rate, trade_amount, avg_5d_trade_amount, high_5d_price "
                "FROM master_stocks_table WHERE code = ?",
                (stk_cd,)
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "code": row["code"],
                    "name": row["name"],
                    "cur_price": row["cur_price"],
                    "change": row["change"],
                    "change_rate": row["change_rate"],
                    "trade_amount": row["trade_amount"],
                    "avg_5d_trade_amount": row["avg_5d_trade_amount"],
                    "high_5d_price": row["high_5d_price"],
                }
            return None
        except Exception as e:
            logger.warning("[CustomSector] fetch_daily_price 실패: %s", e)
            return None

    async def fetch_all_stocks_daily_confirmed(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.1,
        on_progress: Callable[[int, int], None] | None = None,
        resume_codes: set[str] | None = None,
    ) -> dict[str, dict]:
        """master_stocks_table에서 전체 종목 일별 확정 시세 조회."""
        try:
            conn = await get_db_connection()
            cursor = await conn.execute(
                "SELECT code, name, cur_price, change, change_rate, trade_amount, avg_5d_trade_amount, high_5d_price "
                "FROM master_stocks_table"
            )
            rows = await cursor.fetchall()
            
            result = {}
            for row in rows:
                code = row["code"]
                if krx_codes and code not in krx_codes:
                    continue
                result[code] = {
                    "code": row["code"],
                    "name": row["name"],
                    "cur_price": row["cur_price"],
                    "change": row["change"],
                    "change_rate": row["change_rate"],
                    "trade_amount": row["trade_amount"],
                    "avg_5d_trade_amount": row["avg_5d_trade_amount"],
                    "high_5d_price": row["high_5d_price"],
                }
            
            if on_progress:
                on_progress(len(result), len(krx_codes) if krx_codes else len(result))
            
            return result
        except Exception as e:
            logger.warning("[CustomSector] fetch_all_stocks_daily_confirmed 실패: %s", e)
            return {}

    async def fetch_sector_all_5d(
        self,
        krx_codes: list[str],
        qry_dt: str,
        interval_sec: float = 0.33,
        on_progress: Callable[[int, int], None] | None = None,
        resume_codes: set[str] | None = None,
    ) -> dict[str, dict]:
        """master_stocks_table에서 5일 평균 거래대금 조회."""
        try:
            conn = await get_db_connection()
            cursor = await conn.execute(
                "SELECT m.code, m.name, m.avg_5d_trade_amount, s.day1_amount, s.day2_amount, s.day3_amount, s.day4_amount, s.day5_amount "
                "FROM master_stocks_table m "
                "LEFT JOIN stock_5d_array s ON m.code = s.code"
            )
            rows = await cursor.fetchall()
            
            result = {}
            for row in rows:
                code = row["code"]
                if krx_codes and code not in krx_codes:
                    continue
                result[code] = {
                    "code": row["code"],
                    "name": row["name"],
                    "avg_5d_trade_amount": row["avg_5d_trade_amount"],
                    "day1_amount": row["day1_amount"],
                    "day2_amount": row["day2_amount"],
                    "day3_amount": row["day3_amount"],
                    "day4_amount": row["day4_amount"],
                    "day5_amount": row["day5_amount"],
                }
            
            if on_progress:
                on_progress(len(result), len(krx_codes) if krx_codes else len(result))
            
            return result
        except Exception as e:
            logger.warning("[CustomSector] fetch_sector_all_5d 실패: %s", e)
            return {}

    def fetch_industry_stocks(self, inds_cd: str) -> list[dict]:
        """sectors 테이블에서 업종별 종목 조회."""
        try:
            # 현재는 빈 리스트 반환 (향후 sectors 테이블 구현 시 수정)
            return []
        except Exception as e:
            logger.warning("[CustomSector] fetch_industry_stocks 실패: %s", e)
            return []

    async def fetch_avg_amt_5d(self, stk_cd: str) -> int:
        """master_stocks_table에서 5일 평균 거래대금 조회."""
        try:
            conn = await get_db_connection()
            cursor = await conn.execute(
                "SELECT avg_5d_trade_amount FROM master_stocks_table WHERE code = ?",
                (stk_cd,)
            )
            row = await cursor.fetchone()
            if row:
                return int(row["avg_5d_trade_amount"] or 0)
            return 0
        except Exception as e:
            logger.warning("[CustomSector] fetch_avg_amt_5d 실패: %s", e)
            return 0

    async def fetch_daily_amounts_5d(self, stk_cd: str) -> list[int]:
        """stock_5d_array에서 5일 거래대금 조회."""
        try:
            conn = await get_db_connection()
            cursor = await conn.execute(
                "SELECT day1_amount, day2_amount, day3_amount, day4_amount, day5_amount "
                "FROM stock_5d_array WHERE code = ?",
                (stk_cd,)
            )
            row = await cursor.fetchone()
            if row:
                return [
                    int(row["day1_amount"] or 0),
                    int(row["day2_amount"] or 0),
                    int(row["day3_amount"] or 0),
                    int(row["day4_amount"] or 0),
                    int(row["day5_amount"] or 0),
                ]
            return []
        except Exception as e:
            logger.warning("[CustomSector] fetch_daily_amounts_5d 실패: %s", e)
            return []
