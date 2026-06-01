#!/usr/bin/env python3
"""
레거시 테이블 삭제 스크립트
user_settings, system_config, broker_credentials → integrated_system_settings로 통합 완료 후 삭제
custom_sector_mappings → master_stocks_table sector 컬럼으로 대체 후 삭제
"""
import logging
import sqlite3
from pathlib import Path

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "backend" / "data" / "stocks.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def drop_legacy_tables():
    """레거시 테이블 삭제"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    try:
        # 테이블 존재 확인 및 삭제
        tables_to_drop = [
            "user_settings",
            "system_config",
            "broker_credentials",
            "custom_sector_mappings"
        ]
        
        for table in tables_to_drop:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            if cursor.fetchone():
                logger.info("[테이블 삭제] %s 테이블 삭제 중...", table)
                cursor.execute(f"DROP TABLE {table}")
                logger.info("[테이블 삭제] %s 테이블 삭제 완료", table)
            else:
                logger.info("[테이블 삭제] %s 테이블 없음 (이미 삭제됨)", table)
        
        conn.commit()
        logger.info("[테이블 삭제] 완료")
        
    except Exception as e:
        logger.error("[테이블 삭제] 실패: %s", e)
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    drop_legacy_tables()
