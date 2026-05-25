#!/usr/bin/env python3
"""
레거시 sector_custom.json의 stock_moves 매핑으로 master_stocks_table sector 업데이트
"""
import json
from pathlib import Path

def update_sector_from_legacy():
    from backend.app.db.database import get_db_connection
    
    # 레거시 파일 읽기
    legacy_path = Path("/Users/sungjk0706/Desktop/SectorFlow1/backend/data/sector_custom.json")
    with open(legacy_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    stock_moves = data["stock_moves"]
    print(f"[업데이트] 레거시 매핑 로드 완료 -- {len(stock_moves)}종목")
    
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
        print(f"[업데이트] 완료 -- {update_count}개 종목 업데이트")
        
        # 삼성전자 확인
        cursor.execute("SELECT sector FROM master_stocks_table WHERE code = '005930'")
        row = cursor.fetchone()
        if row:
            print(f"[확인] 삼성전자(005930) sector: {row['sector']}")
        
    except Exception as e:
        conn.rollback()
        print(f"[업데이트] 실패: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    update_sector_from_legacy()
