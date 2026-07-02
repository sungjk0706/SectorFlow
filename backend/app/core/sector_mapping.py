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

    # 1) 인메모리 캐시에서 조회 (_master_stocks_cache)
    try:
        import backend.app.services.engine_service as es
        entry = es._master_stocks_cache.get(stock_code)
        if entry and "sector" in entry:
            return entry["sector"] or "미분류"
    except Exception as e:
        _log.warning("[업종매핑] 인메모리 캐시 조회 실패: %s", e)

    # 2) SQLite DB에서 조회
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

    return "미분류"


async def get_merged_sectors_batch(codes: list[str]) -> dict[str, str]:
    """종목 코드 리스트 → {code: sector} 배치 반환.

    메모리 캐시에서 일괄 조회하고, 캐시 미스 코드만 단일 DB 쿼리로 해결.
    1353회 개별 await get_merged_sector() 호출을 1회 await로 대체.
    """
    result: dict[str, str] = {}
    missed: list[str] = []

    for cd in codes:
        upper_cd = cd.upper()
        try:
            import backend.app.services.engine_service as es
            entry = es._master_stocks_cache.get(upper_cd)
            if entry and "sector" in entry:
                result[cd] = entry["sector"] or "미분류"
                continue
        except Exception as e:
            _log.warning("[매핑] 인메모리 캐시 배치 조회 실패 (%s): %s", upper_cd, e)
        missed.append(upper_cd)

    if missed:
        from backend.app.db.database import get_db_connection
        conn = await get_db_connection()
        try:
            placeholders = ",".join("?" * len(missed))
            cursor = await conn.execute(
                f"SELECT code, sector FROM master_stocks_table WHERE code IN ({placeholders})",
                missed,
            )
            rows = await cursor.fetchall()
            for row in rows:
                result[row["code"]] = row["sector"] or "미분류"
        except Exception as e:
            _log.warning("[매핑] get_merged_sectors_batch DB 조회 실패: %s", e)

    for cd in codes:
        if cd not in result:
            result[cd] = "미분류"

    return result


async def get_merged_all_sectors() -> list[str]:
    """sectors 테이블에서 전체 업종 목록 조회 (정렬). 업종 정의의 SSOT는 sectors 테이블."""
    sectors = set()
    try:
        from backend.app.db.database import get_db_connection
        conn = await get_db_connection()
        cursor = await conn.execute("SELECT name FROM sectors")
        rows = await cursor.fetchall()
        for row in rows:
            sectors.add(row["name"])
    except Exception as e:
        _log.warning("[매핑] get_merged_all_sectors sectors 테이블 조회 실패: %s", e)

    if "미분류" not in sectors:
        sectors.add("미분류")
    return sorted(list(sectors))
