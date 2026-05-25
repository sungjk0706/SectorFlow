#!/usr/bin/env python3
"""
kv_store의 avg_amt_5d_cache (JSON) 데이터를 
master_stocks_table의 day1~day5_amount, day1~day5_high 컬럼으로 변환
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

def migrate_json_to_columns():
    """kv_store JSON 데이터를 master_stocks_table 컬럼으로 변환"""
    from backend.app.db.database import get_db_connection
    from backend.app.db.cache_db import get_kv
    
    # kv_store에서 avg_amt_5d_cache 로드
    cache_data = get_kv("avg_amt_5d_cache")
    
    if not cache_data:
        print("[변환] kv_store에 avg_amt_5d_cache 데이터가 없습니다.")
        return
    
    print(f"[변환] avg_amt_5d_cache 로드 완료 -- version={cache_data.get('version')}, date={cache_data.get('date')}")
    
    # 데이터 추출
    v2_data = cache_data.get("data", {})  # dict[str, list[int]]
    high_5d_arr = cache_data.get("high_5d_arr", {})  # dict[str, list[int]]
    
    if not v2_data:
        print("[변환] data 필드가 비어있습니다.")
        return
    
    print(f"[변환] v2_data: {len(v2_data)}종목, high_5d_arr: {len(high_5d_arr)}종목")
    
    # master_stocks_table 업데이트
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        update_count = 0
        for code, amounts in v2_data.items():
            if not isinstance(amounts, list) or len(amounts) != 5:
                continue
            
            highs = high_5d_arr.get(code, [])
            if not isinstance(highs, list) or len(highs) != 5:
                highs = [0, 0, 0, 0, 0]
            
            cursor.execute("""
                UPDATE master_stocks_table
                SET day1_amount = ?, day2_amount = ?, day3_amount = ?, day4_amount = ?, day5_amount = ?,
                    day1_high = ?, day2_high = ?, day3_high = ?, day4_high = ?, day5_high = ?
                WHERE code = ?
            """, (
                amounts[0], amounts[1], amounts[2], amounts[3], amounts[4],
                highs[0], highs[1], highs[2], highs[3], highs[4],
                code
            ))
            update_count += 1
        
        conn.commit()
        print(f"[변환] 완료 -- {update_count}개 종목 업데이트")
        
    except Exception as e:
        conn.rollback()
        print(f"[변환] 실패: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_json_to_columns()
