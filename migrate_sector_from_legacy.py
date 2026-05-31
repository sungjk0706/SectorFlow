#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
레거시 프로젝트 업종 매핑 마이그레이션 스크립트

순서:
1. 레거시 DB에서 sector 데이터 추출
2. 현재 custom_sector_mappings에 업데이트
3. master_stocks_table에 반영
"""

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

# 경로 설정
LEGACY_DB = Path("/Users/sungjk0706/Desktop/SectorFlow 2/backend/data/stocks.db")
CURRENT_DB = Path("/Users/sungjk0706/Desktop/SectorFlow/backend/data/stocks.db")
BACKUP_DB = Path("/Users/sungjk0706/Desktop/SectorFlow/backend/data/stocks.db.backup")

def create_backup():
    """현재 DB 백업"""
    print(f"[1/4] 백업 생성: {BACKUP_DB}")
    shutil.copy2(CURRENT_DB, BACKUP_DB)
    print("백업 완료")

def extract_legacy_sectors():
    """레거시 DB에서 sector 데이터 추출"""
    print(f"[2/4] 레거시 DB에서 sector 데이터 추출: {LEGACY_DB}")
    
    conn = sqlite3.connect(LEGACY_DB)
    cursor = conn.cursor()
    
    cursor.execute("SELECT code, sector FROM master_stocks_table WHERE sector IS NOT NULL AND sector != '기타'")
    rows = cursor.fetchall()
    
    conn.close()
    
    print(f"추출된 종목 수: {len(rows)}")
    return {code: sector for code, sector in rows}

def update_custom_sector_mappings(sector_map):
    """custom_sector_mappings 테이블 업데이트"""
    print("[3/4] custom_sector_mappings 테이블 업데이트")
    
    conn = sqlite3.connect(CURRENT_DB)
    cursor = conn.cursor()
    
    # 트랜잭션 시작
    cursor.execute("BEGIN TRANSACTION")
    
    try:
        updated = 0
        inserted = 0
        
        for code, sector in sector_map.items():
            # 기존 데이터 확인
            cursor.execute("SELECT sector FROM custom_sector_mappings WHERE code = ?", (code,))
            existing = cursor.fetchone()
            
            if existing:
                # 업데이트
                cursor.execute("UPDATE custom_sector_mappings SET sector = ? WHERE code = ?", (sector, code))
                updated += 1
            else:
                # 삽입
                cursor.execute("INSERT INTO custom_sector_mappings (code, sector) VALUES (?, ?)", (code, sector))
                inserted += 1
        
        conn.commit()
        print(f"업데이트: {updated}종목, 삽입: {inserted}종목")
        
    except Exception as e:
        conn.rollback()
        print(f"오류 발생: {e}")
        raise
    finally:
        conn.close()

def sync_to_master_stocks_table():
    """custom_sector_mappings → master_stocks_table 동기화"""
    print("[4/4] master_stocks_table에 sector 반영")
    
    conn = sqlite3.connect(CURRENT_DB)
    cursor = conn.cursor()
    
    # 트랜잭션 시작
    cursor.execute("BEGIN TRANSACTION")
    
    try:
        # custom_sector_mappings 기반 업데이트
        cursor.execute("""
            UPDATE master_stocks_table 
            SET sector = (
                SELECT csm.sector 
                FROM custom_sector_mappings csm 
                WHERE csm.code = master_stocks_table.code
            )
            WHERE code IN (SELECT code FROM custom_sector_mappings)
        """)
        
        updated = cursor.rowcount
        conn.commit()
        print(f"master_stocks_table 업데이트: {updated}종목")
        
    except Exception as e:
        conn.rollback()
        print(f"오류 발생: {e}")
        raise
    finally:
        conn.close()

def verify():
    """검증"""
    print("\n[검증] 업종 분포 확인")
    
    conn = sqlite3.connect(CURRENT_DB)
    cursor = conn.cursor()
    
    # master_stocks_table sector 분포
    cursor.execute("SELECT sector, COUNT(*) as count FROM master_stocks_table GROUP BY sector ORDER BY count DESC LIMIT 20")
    rows = cursor.fetchall()
    
    print("master_stocks_table sector 분포:")
    for sector, count in rows:
        print(f"  {sector}: {count}종목")
    
    # custom_sector_mappings 카운트
    cursor.execute("SELECT COUNT(*) FROM custom_sector_mappings")
    csm_count = cursor.fetchone()[0]
    print(f"\ncustom_sector_mappings 총 종목: {csm_count}")
    
    conn.close()

def main():
    print("=" * 60)
    print("레거시 업종 매핑 마이그레이션 시작")
    print(f"시작 시간: {datetime.now()}")
    print("=" * 60)
    
    try:
        create_backup()
        sector_map = extract_legacy_sectors()
        update_custom_sector_mappings(sector_map)
        sync_to_master_stocks_table()
        verify()
        
        print("\n" + "=" * 60)
        print("마이그레이션 완료")
        print(f"완료 시간: {datetime.now()}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n마이그레이션 실패: {e}")
        print("백업에서 복원 필요")
        raise

if __name__ == "__main__":
    main()
