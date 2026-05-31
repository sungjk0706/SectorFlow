#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
custom_sector_mappings 정리 스크립트

master_stocks_table에 없는 종목의 sector 매핑 삭제
"""

import sqlite3
from pathlib import Path

CURRENT_DB = Path("/Users/sungjk0706/Desktop/SectorFlow/backend/data/stocks.db")

def cleanup_orphan_sectors():
    """master_stocks_table에 없는 종목의 sector 매핑 삭제"""
    print("custom_sector_mappings 정리 시작")
    
    conn = sqlite3.connect(CURRENT_DB)
    cursor = conn.cursor()
    
    # 트랜잭션 시작
    cursor.execute("BEGIN TRANSACTION")
    
    try:
        # 삭제 전 카운트
        cursor.execute("SELECT COUNT(*) FROM custom_sector_mappings")
        before_count = cursor.fetchone()[0]
        print(f"삭제 전: {before_count}종목")
        
        # master_stocks_table에 없는 종목 삭제
        cursor.execute("""
            DELETE FROM custom_sector_mappings
            WHERE code NOT IN (SELECT code FROM master_stocks_table)
        """)
        
        deleted = cursor.rowcount
        conn.commit()
        
        # 삭제 후 카운트
        cursor.execute("SELECT COUNT(*) FROM custom_sector_mappings")
        after_count = cursor.fetchone()[0]
        
        print(f"삭제된 종목: {deleted}종목")
        print(f"삭제 후: {after_count}종목")
        print("정리 완료")
        
    except Exception as e:
        conn.rollback()
        print(f"오류 발생: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    cleanup_orphan_sectors()
