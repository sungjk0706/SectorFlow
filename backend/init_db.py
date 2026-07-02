#!/usr/bin/env python3
"""
데이터베이스 테이블 초기화 스크립트

앱 기동 시마다 실행되는 불필요한 테이블 초기화를 분리하여
별도 스크립트로 관리. 스키마 변경 시에만 실행 필요.

사용법:
    python -m backend.init_db
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def init_all_tables():
    """모든 테이블 초기화"""
    from backend.app.db.stock_tables import (
        init_cache_tables,
        create_stock_5d_array_table,
        migrate_stock_5d_array_pk,
        create_master_stocks_table,
        migrate_drop_high_price_column,
        migrate_add_nxt_enable_column,
    )
    from backend.app.db.database import get_db_connection, close_db_connection

    print("[init_db] 데이터베이스 테이블 초기화 시작...")

    # DB 연결
    conn = await get_db_connection()
    print("[init_db] DB 연결 완료")

    # 캐시 테이블 초기화
    await init_cache_tables()
    print("[init_db] 캐시 테이블 초기화 완료")

    # stock_5d_array 테이블 초기화 + 마이그레이션
    await create_stock_5d_array_table()
    await migrate_stock_5d_array_pk()
    print("[init_db] stock_5d_array 테이블 초기화 완료")

    # master_stocks_table 초기화
    await create_master_stocks_table()
    print("[init_db] master_stocks_table 초기화 완료")

    # 마이그레이션: high_price 컬럼 제거
    await migrate_drop_high_price_column()
    print("[init_db] high_price 컬럼 제거 마이그레이션 완료")

    # 마이그레이션: nxt_enable 컬럼
    await migrate_add_nxt_enable_column()
    print("[init_db] nxt_enable 컬럼 마이그레이션 완료")

    print("[init_db] 모든 테이블 초기화 완료")

    await close_db_connection()


if __name__ == "__main__":
    asyncio.run(init_all_tables())
