#!/usr/bin/env python3
"""
Phase 3.3 검증 스크립트
종목분류 변경 로직 completed_snapshot 업데이트 확인
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

def verify_completed_snapshot_update():
    """completed_snapshot 업데이트 로직 검증"""
    from backend.app.db.database import get_db_connection
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # completed_snapshot 테이블에서 샘플 데이터 확인
        cursor.execute("SELECT code, sector FROM completed_snapshot LIMIT 1")
        row = cursor.fetchone()
        
        if not row:
            print("[검증] completed_snapshot 테이블에 데이터가 없습니다.")
            return False
        
        code = row["code"]
        old_sector = row["sector"]
        print(f"[검증] 샘플 종목: {code}, 현재 업종: {old_sector}")
        
        # stock_classification_data.py에서 completed_snapshot 업데이트 로직 확인
        with open(PROJECT_ROOT / "backend/app/core/stock_classification_data.py", "r", encoding="utf-8") as f:
            content = f.read()
            
            if "UPDATE completed_snapshot SET sector" not in content:
                print("[검증] 실패 -- completed_snapshot 업데이트 로직 없음")
                return False
            
            # rename_sector 함수 확인
            if "def rename_sector" in content:
                rename_section = content[content.find("def rename_sector"):content.find("def create_sector")]
                if "UPDATE completed_snapshot SET sector" in rename_section:
                    print("[검증] rename_sector: completed_snapshot 업데이트 로직 확인")
                else:
                    print("[검증] 실패 -- rename_sector에 completed_snapshot 업데이트 없음")
                    return False
            
            # delete_sector 함수 확인
            if "def delete_sector" in content:
                delete_section = content[content.find("def delete_sector"):content.find("def move_stock")]
                if "UPDATE completed_snapshot SET sector" in delete_section:
                    print("[검증] delete_sector: completed_snapshot 업데이트 로직 확인")
                else:
                    print("[검증] 실패 -- delete_sector에 completed_snapshot 업데이트 없음")
                    return False
            
            # move_stock 함수 확인
            if "def move_stock" in content:
                move_section = content[content.find("def move_stock"):]
                if "UPDATE completed_snapshot SET sector" in move_section:
                    print("[검증] move_stock: completed_snapshot 업데이트 로직 확인")
                else:
                    print("[검증] 실패 -- move_stock에 completed_snapshot 업데이트 없음")
                    return False
        
        print("[검증] 성공 -- 모든 함수에 completed_snapshot 업데이트 로직 추가됨")
        return True
        
    except Exception as e:
        print(f"[검증] 실패: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = verify_completed_snapshot_update()
    sys.exit(0 if success else 1)
