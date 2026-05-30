from __future__ import annotations
# -*- coding: utf-8 -*-
"""
SQLite DB 및 인메모리 기반 종목 → 업종 매핑 모듈.

기존 stock_classification.json 의존성을 제거하고,
SQLite 데이터베이스(stocks 및 sectors 테이블) 또는 인메모리 캐시를 단일 진실 공급원으로 사용.
"""

import logging

_log = logging.getLogger(__name__)


async def get_merged_sector(stock_code: str) -> str:
    """인메모리 캐시 또는 SQLite DB에서 종목의 최종 업종명을 반환."""
    stock_code = stock_code.upper()  # 대문자 통일 (키움 원본 포맷 고수, 대조 시점에만 변환)

    # 1) sector 캐시에서 우선 조회 (master_stocks_table 로드 시 저장)
    try:
        import backend.app.services.engine_service as es
        if hasattr(es._st, "_sector_cache") and es._st._sector_cache:
            sector = es._st._sector_cache.get(stock_code)
            if sector:
                return sector
    except Exception:
        pass

    # 2) 인메모리 캐시에서 조회 (_master_stocks_cache)
    try:
        import backend.app.services.engine_service as es
        entry = es._master_stocks_cache.get(stock_code)
        if entry and "sector" in entry:
            return entry["sector"] or "기타"
    except Exception:
        pass

    # 3) SQLite DB에서 조회
    from backend.app.db.database import get_db_connection
    conn = await get_db_connection()
    try:
        cursor = await conn.cursor()
        await cursor.execute("SELECT sector FROM master_stocks_table WHERE code = ?", (stock_code,))
        row = await cursor.fetchone()
        if row and row["sector"]:
            return row["sector"]
    except Exception as e:
        _log.warning("[매핑] get_merged_sector DB 조회 실패 (%s): %s", stock_code, e)

    return "기타"


async def get_merged_all_sectors() -> list[str]:
    """SQLite DB sectors 테이블에서 전체 업종 목록 조회 (정렬)."""
    from backend.app.db.database import get_db_connection
    conn = await get_db_connection()
    try:
        cursor = await conn.cursor()
        await cursor.execute("SELECT name FROM sectors")
        rows = await cursor.fetchall()
        sectors = [r["name"] for r in rows if r["name"]]
        if "기타" not in sectors:
            sectors.append("기타")
        return sorted(list(set(sectors)))
    except Exception as e:
        _log.warning("[매핑] get_merged_all_sectors DB 조회 실패: %s", e)
        return ["기타"]
