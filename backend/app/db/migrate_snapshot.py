#!/usr/bin/env python3
"""
completed_snapshot 테이블 마이그레이션 스크립트
기존 stocks 테이블 데이터를 completed_snapshot으로 이전
"""
import sys
import sqlite3
from pathlib import Path

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "backend" / "data" / "stocks.db"

def migrate_to_completed_snapshot():
    """stocks 테이블 데이터를 completed_snapshot으로 마이그레이션"""
    from backend.app.db.database import get_db_connection
    from backend.app.core.trading_calendar import current_trading_date_str
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 현재 날짜 가져오기
        date_str = current_trading_date_str()
        
        # stocks 테이블에서 데이터 읽기
        cursor.execute("""
            SELECT code, name, sector, cur_price, change, change_rate, 
                   strength, trade_amount, avg_5d_trade_amount, high_5d_price
            FROM stocks
        """)
        rows = cursor.fetchall()
        
        if not rows:
            print("[마이그레이션] stocks 테이블에 데이터가 없습니다.")
            return
        
        # completed_snapshot에 INSERT OR REPLACE
        insert_count = 0
        for row in rows:
            cursor.execute("""
                INSERT OR REPLACE INTO completed_snapshot 
                (code, name, sector, cur_price, change, change_rate, 
                 strength, trade_amount, avg_5d_trade_amount, high_5d_price, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["code"],
                row["name"],
                row["sector"],
                row["cur_price"],
                row["change"],
                row["change_rate"],
                row["strength"],
                row["trade_amount"],
                row["avg_5d_trade_amount"],
                row["high_5d_price"],
                date_str
            ))
            insert_count += 1
        
        conn.commit()
        print(f"[마이그레이션] 완료 -- {insert_count}개 행 이전 완료 (date={date_str})")
        
    except Exception as e:
        conn.rollback()
        print(f"[마이그레이션] 실패: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    # 테이블 생성 후 마이그레이션
    from backend.app.db.cache_db import create_completed_snapshot_table
    create_completed_snapshot_table()
    migrate_to_completed_snapshot()
