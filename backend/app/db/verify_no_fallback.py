#!/usr/bin/env python3
"""
Fallback 제거 검증 스크립트
completed_snapshot 없으면 오류 발생 확인
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

def verify_no_fallback():
    """Fallback 로직 제거 검증"""
    from backend.app.db.cache_db import load_completed_snapshot
    
    # 정상 로드 확인
    result = load_completed_snapshot()
    if result is None or len(result) == 0:
        print("[검증] completed_snapshot 로드 실패 -- None 또는 빈 데이터")
        return False
    
    print(f"[검증] completed_snapshot 로드 성공 -- {len(result)}개 종목")
    
    # engine_cache.py에서 Fallback 로직 제거 확인
    with open(PROJECT_ROOT / "backend/app/services/engine_cache.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "get_all_stocks" in content:
            print("[검증] 실패 -- engine_cache.py에 get_all_stocks 호출 남아있음")
            return False
        if "기존 방식으로 로드" in content:
            print("[검증] 실패 -- engine_cache.py에 Fallback 로직 남아있음")
            return False
    
    print("[검증] engine_cache.py Fallback 로직 제거 확인")
    
    # engine_bootstrap.py에서 get_all_stocks 호출 제거 확인
    with open(PROJECT_ROOT / "backend/app/services/engine_bootstrap.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "from backend.app.db.crud import get_all_stocks" in content:
            print("[검증] 실패 -- engine_bootstrap.py에 get_all_stocks import 남아있음")
            return False
    
    print("[검증] engine_bootstrap.py get_all_stocks import 제거 확인")
    
    # crud.py에서 get_all_stocks 함수 제거 확인
    with open(PROJECT_ROOT / "backend/app/db/crud.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "def get_all_stocks():" in content:
            print("[검증] 실패 -- crud.py에 get_all_stocks 함수 남아있음")
            return False
    
    print("[검증] crud.py get_all_stocks 함수 제거 확인")
    
    return True

if __name__ == "__main__":
    success = verify_no_fallback()
    sys.exit(0 if success else 1)
