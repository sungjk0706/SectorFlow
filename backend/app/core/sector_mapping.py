# -*- coding: utf-8 -*-
"""
SQLite DB 및 인메모리 기반 종목 → 업종 매핑 모듈.

기존 stock_classification.json 의존성을 제거하고,
SQLite 데이터베이스(stocks 및 sectors 테이블) 또는 인메모리 캐시를 단일 진실 공급원으로 사용.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def get_merged_sector(stock_code: str) -> str:
    """인메모리 캐시 또는 SQLite DB에서 종목의 최종 업종명을 반환."""
    # 1) 인메모리 캐시에서 우선 조회
    try:
        import backend.app.services.engine_service as es
        entry = es._pending_stock_details.get(stock_code)
        if entry and "sector" in entry:
            return entry["sector"] or "기타"
    except Exception:
        pass

    # 2) SQLite DB에서 조회
    from backend.app.db.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT sector FROM stocks WHERE code = ?", (stock_code,))
        row = cursor.fetchone()
        if row and row["sector"]:
            return row["sector"]
    except Exception as e:
        _log.warning("[매핑] get_merged_sector DB 조회 실패 (%s): %s", stock_code, e)
    finally:
        conn.close()

    return "기타"


def get_merged_all_sectors() -> list[str]:
    """SQLite DB sectors 테이블에서 전체 업종 목록 조회 (정렬)."""
    from backend.app.db.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sectors")
        rows = cursor.fetchall()
        sectors = [r["name"] for r in rows if r["name"]]
        if "기타" not in sectors:
            sectors.append("기타")
        return sorted(list(set(sectors)))
    except Exception as e:
        _log.warning("[매핑] get_merged_all_sectors DB 조회 실패: %s", e)
        return ["기타"]
    finally:
        conn.close()
