#!/usr/bin/env python3
"""
Phase 4 검증 스크립트
테이블 및 코드 제거 확인
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

def verify_table_removal():
    """테이블 삭제 확인"""
    from backend.app.db.database import get_db_connection
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # snapshot_cache 테이블 존재 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='snapshot_cache'")
        if cursor.fetchone():
            print("[검증] 실패 -- snapshot_cache 테이블이 존재함")
            return False
        print("[검증] snapshot_cache 테이블 삭제 확인")
        
        # stocks 테이블 존재 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stocks'")
        if cursor.fetchone():
            print("[검증] 실패 -- stocks 테이블이 존재함")
            return False
        print("[검증] stocks 테이블 삭제 확인")
        
        return True
    except Exception as e:
        print(f"[검증] 실패: {e}")
        return False
    finally:
        conn.close()

def verify_code_removal():
    """코드 제거 확인"""
    # cache_db.py에서 snapshot_cache 테이블 생성 로직 제거 확인
    with open(PROJECT_ROOT / "backend/app/db/cache_db.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "CREATE TABLE IF NOT EXISTS snapshot_cache" in content:
            print("[검증] 실패 -- cache_db.py에 snapshot_cache 테이블 생성 로직 남아있음")
            return False
        print("[검증] cache_db.py snapshot_cache 테이블 생성 로직 제거 확인")
    
    # sector_stock_cache.py에서 snapshot_cache 관련 함수 제거 확인
    with open(PROJECT_ROOT / "backend/app/core/sector_stock_cache.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "def save_snapshot_cache" in content:
            print("[검증] 실패 -- sector_stock_cache.py에 save_snapshot_cache 함수 남아있음")
            return False
        if "def load_snapshot_cache" in content:
            print("[검증] 실패 -- sector_stock_cache.py에 load_snapshot_cache 함수 남아있음")
            return False
        if "def get_snapshot_cache_date" in content:
            print("[검증] 실패 -- sector_stock_cache.py에 get_snapshot_cache_date 함수 남아있음")
            return False
        print("[검증] sector_stock_cache.py snapshot_cache 관련 함수 제거 확인")
    
    # market_close_pipeline.py에서 snapshot_cache 저장 로직 제거 확인
    with open(PROJECT_ROOT / "backend/app/services/market_close_pipeline.py", "r", encoding="utf-8") as f:
        content = f.read()
        # 주석 제거 후 검사
        lines = [line for line in content.split('\n') if not line.strip().startswith('#') and not line.strip().startswith('"""')]
        code_content = '\n'.join(lines)
        if "save_snapshot_cache(" in code_content:
            print("[검증] 실패 -- market_close_pipeline.py에 save_snapshot_cache 호출 남아있음")
            return False
        if "batch_insert_stocks(" in code_content:
            print("[검증] 실패 -- market_close_pipeline.py에 batch_insert_stocks 호출 남아있음")
            return False
        print("[검증] market_close_pipeline.py snapshot_cache/stocks 저장 로직 제거 확인")
    
    # engine_cache.py에서 load_snapshot_cache import 제거 확인
    with open(PROJECT_ROOT / "backend/app/services/engine_cache.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "load_snapshot_cache" in content:
            print("[검증] 실패 -- engine_cache.py에 load_snapshot_cache import 남아있음")
            return False
        print("[검증] engine_cache.py load_snapshot_cache import 제거 확인")
    
    # daily_time_scheduler.py에서 snapshot_cache 관련 로직 제거 확인
    with open(PROJECT_ROOT / "backend/app/services/daily_time_scheduler.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "load_snapshot_cache" in content:
            print("[검증] 실패 -- daily_time_scheduler.py에 load_snapshot_cache 호출 남아있음")
            return False
        if "get_snapshot_cache_date" in content:
            print("[검증] 실패 -- daily_time_scheduler.py에 get_snapshot_cache_date 호출 남아있음")
            return False
        print("[검증] daily_time_scheduler.py snapshot_cache 관련 로직 제거 확인")
    
    # crud.py에서 batch_insert_stocks 함수 제거 확인
    with open(PROJECT_ROOT / "backend/app/db/crud.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "def batch_insert_stocks" in content:
            print("[검증] 실패 -- crud.py에 batch_insert_stocks 함수 남아있음")
            return False
        print("[검증] crud.py batch_insert_stocks 함수 제거 확인")
    
    return True

if __name__ == "__main__":
    table_ok = verify_table_removal()
    code_ok = verify_code_removal()
    success = table_ok and code_ok
    sys.exit(0 if success else 1)
