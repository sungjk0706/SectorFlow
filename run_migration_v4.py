#!/usr/bin/env python3
"""
마이그레이션 v4 실행 스크립트 (avg_5d_trade_amount REAL → INTEGER)
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.db.migration_v3 import run_migration_v3

async def main():
    print("[마이그레이션 v4] avg_5d_trade_amount REAL → INTEGER 타입 변경 시작...")
    try:
        await run_migration_v3()
        print("[마이그레이션 v4] 완료")
    except Exception as e:
        print(f"[마이그레이션 v4] 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
