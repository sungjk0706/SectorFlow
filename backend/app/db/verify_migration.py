#!/usr/bin/env python3
"""
completed_snapshot 마이그레이션 검증 스크립트
stocks 테이블과 completed_snapshot의 데이터 일치 여부 확인
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

def verify_migration():
    """stocks 테이블과 completed_snapshot의 데이터 일치 여부 검증"""
    from backend.app.db.database import get_db_connection
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # stocks 테이블에서 샘플 100개 읽기
        cursor.execute("""
            SELECT code, name, sector, cur_price, change, change_rate, 
                   strength, trade_amount, avg_5d_trade_amount, high_5d_price
            FROM stocks
            LIMIT 100
        """)
        stocks_rows = cursor.fetchall()
        
        if not stocks_rows:
            print("[검증] stocks 테이블에 데이터가 없습니다.")
            return
        
        # completed_snapshot에서 동일한 코드 읽기
        mismatch_count = 0
        for row in stocks_rows:
            code = row["code"]
            cursor.execute("""
                SELECT code, name, sector, cur_price, change, change_rate, 
                       strength, trade_amount, avg_5d_trade_amount, high_5d_price
                FROM completed_snapshot
                WHERE code = ?
            """, (code,))
            snapshot_row = cursor.fetchone()
            
            if not snapshot_row:
                print(f"[불일치] {code}: completed_snapshot에 없음")
                mismatch_count += 1
                continue
            
            # 각 필드 비교
            fields = ["name", "sector", "cur_price", "change", "change_rate", 
                      "strength", "trade_amount", "avg_5d_trade_amount", "high_5d_price"]
            for field in fields:
                if row[field] != snapshot_row[field]:
                    print(f"[불일치] {code}.{field}: stocks={row[field]}, snapshot={snapshot_row[field]}")
                    mismatch_count += 1
                    break
        
        total_count = len(stocks_rows)
        match_count = total_count - mismatch_count
        match_rate = (match_count / total_count * 100) if total_count > 0 else 0
        
        print(f"[검증] 완료 -- {match_count}/{total_count}개 일치 ({match_rate:.1f}%)")
        
        if mismatch_count == 0:
            print("[검증] 성공 -- 모든 데이터 일치")
        else:
            print(f"[검증] 실패 -- {mismatch_count}개 불일치")
        
    except Exception as e:
        print(f"[검증] 실패: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    verify_migration()
