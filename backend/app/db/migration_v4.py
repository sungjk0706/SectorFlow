# -*- coding: utf-8 -*-
"""
SQLite DB 마이그레이션 v4 (master_stocks_table에 downloaded_at 컬럼 추가 - 이어받기 기능 지원)
"""

import logging
from backend.app.db.database import get_db_connection

logger = logging.getLogger(__name__)


async def run_migration_v4() -> None:
    """SQLite DB 마이그레이션 v4 수행 (master_stocks_table에 downloaded_at 컬럼 추가)"""
    conn = await get_db_connection()
    
    try:
        # master_stocks_table 스펙 검사
        cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
        columns = await cursor.fetchall()
        column_names = [col["name"] for col in columns]
        
        # downloaded_at 컬럼이 없으면 추가
        if "downloaded_at" not in column_names:
            logger.info("[마이그레이션 v4] master_stocks_table에 downloaded_at 컬럼 추가 시작...")
            
            await conn.execute("ALTER TABLE master_stocks_table ADD COLUMN downloaded_at TIMESTAMP")
            await conn.commit()
            
            logger.info("[마이그레이션 v4] downloaded_at 컬럼 추가 완료")
        else:
            pass
            
    except Exception as e:
        logger.error("[마이그레이션 v4] 마이그레이션 실패: %s", e)
        raise
