#!/usr/bin/env python3
"""
completed_snapshot → master_stocks_table 마이그레이션 스크립트
기존 completed_snapshot 테이블 데이터를 master_stocks_table로 이전
"""
import sys
import sqlite3
from pathlib import Path
from backend.app.core.logger import get_logger

logger = get_logger("migrate")

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "backend" / "data" / "stocks.db"

def migrate_to_master_stocks_table():
    """completed_snapshot 테이블 데이터를 master_stocks_table로 마이그레이션"""
    from backend.app.db.database import get_db_connection
    from backend.app.core.trading_calendar import current_trading_date_str
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 현재 날짜 가져오기
        date_str = current_trading_date_str()
        
        # completed_snapshot 테이블 존재 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='completed_snapshot'")
        if not cursor.fetchone():
            logger.warning("[마이그레이션] completed_snapshot 테이블이 존재하지 않습니다.")
            return
        
        # completed_snapshot에서 데이터 읽기
        cursor.execute("""
            SELECT code, name, sector, cur_price, change, change_rate, 
                   strength, trade_amount, avg_5d_trade_amount, high_5d_price, date
            FROM completed_snapshot
        """)
        rows = cursor.fetchall()
        
        if not rows:
            logger.warning("[마이그레이션] completed_snapshot 테이블에 데이터가 없습니다.")
            return
        
        # master_stocks_table에 INSERT OR REPLACE
        insert_count = 0
        for row in rows:
            avg_5d = row["avg_5d_trade_amount"] or 0
            high_5d = row["high_5d_price"] or 0
            
            # 기존 avg_5d_trade_amount를 day1~day5_amount에 균등 분배
            day1_amount = day2_amount = day3_amount = day4_amount = day5_amount = avg_5d
            # 기존 high_5d_price를 day1~day5_high에 균등 분배
            day1_high = day2_high = day3_high = day4_high = day5_high = high_5d
            
            cursor.execute("""
                INSERT OR REPLACE INTO master_stocks_table 
                (code, name, sector, cur_price, change, change_rate, 
                 strength, trade_amount, avg_5d_trade_amount, high_5d_price, date,
                 day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                 day1_high, day2_high, day3_high, day4_high, day5_high)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["code"],
                row["name"],
                row["sector"],
                row["cur_price"],
                row["change"],
                row["change_rate"],
                row["strength"],
                row["trade_amount"],
                avg_5d,
                high_5d,
                row["date"] or date_str,
                day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                day1_high, day2_high, day3_high, day4_high, day5_high
            ))
            insert_count += 1
        
        conn.commit()
        logger.info("[마이그레이션] 완료 -- %d개 행 이전 완료", insert_count)
        
    except Exception as e:
        conn.rollback()
        logger.error("[마이그레이션] 실패: %s", e, exc_info=True)
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    # 테이블 생성 후 마이그레이션
    from backend.app.db.cache_db import create_completed_snapshot_table as create_master_stocks_table
    create_master_stocks_table()
    migrate_to_master_stocks_table()
