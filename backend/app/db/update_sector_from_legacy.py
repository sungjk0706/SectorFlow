#!/usr/bin/env python3
"""
레거시 sector_custom.json의 stock_moves 매핑으로 master_stocks_table sector 업데이트
"""
import json
from pathlib import Path
from backend.app.core.logger import get_logger

logger = get_logger("migrate")

def update_sector_from_legacy():
    from backend.app.db.database import get_db_connection
    
    # 레거시 파일 읽기
    legacy_path = Path("/Users/sungjk0706/Desktop/SectorFlow1/backend/data/sector_custom.json")
    with open(legacy_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    stock_moves = data["stock_moves"]
    logger.info("[업데이트] 레거시 매핑 로드 완료 -- %d종목", len(stock_moves))
    
    # master_stocks_table 업데이트
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        update_count = 0
        for code, sector in stock_moves.items():
            cursor.execute(
                "UPDATE master_stocks_table SET sector = ? WHERE code = ?",
                (sector, code)
            )
            if cursor.rowcount > 0:
                update_count += 1
        
        conn.commit()
        logger.info("[업데이트] 완료 -- %d개 종목 업데이트", update_count)
        
        # 삼성전자 확인
        cursor.execute("SELECT sector FROM master_stocks_table WHERE code = '005930'")
        row = cursor.fetchone()
        if row:
            logger.info("[확인] 삼성전자(005930) sector: %s", row['sector'])
        
    except Exception as e:
        conn.rollback()
        logger.error("[업데이트] 실패: %s", e, exc_info=True)
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    update_sector_from_legacy()
