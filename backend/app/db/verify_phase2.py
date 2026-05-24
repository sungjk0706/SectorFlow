#!/usr/bin/env python3
"""
Phase 2.3 검증 스크립트
completed_snapshot 로드 기능 검증
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

def verify_load_completed_snapshot():
    """load_completed_snapshot() 함수 검증"""
    from backend.app.db.cache_db import load_completed_snapshot
    
    result = load_completed_snapshot()
    
    if result is None:
        print("[검증] completed_snapshot 로드 실패 -- None 반환")
        return False
    
    print(f"[검증] completed_snapshot 로드 성공 -- {len(result)}개 종목")
    
    # 샘플 3개 출력
    for i, (code, detail) in enumerate(result[:3]):
        print(f"  [{i+1}] {code}: {detail.get('name')} ({detail.get('sector')})")
    
    return True

if __name__ == "__main__":
    success = verify_load_completed_snapshot()
    sys.exit(0 if success else 1)
