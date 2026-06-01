#!/usr/bin/env python3
"""
test_positions 테이블 마이그레이션 스크립트
JSON 컬럼 → 개별 컬럼으로 분리
"""
import asyncio
import json
import logging
from pathlib import Path

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db.stock_tables import get_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_test_positions():
    """test_positions 테이블 마이그레이션"""
    conn = await get_db_connection()
    
    try:
        # 1. 기존 데이터 백업
        logger.info("[마이그레이션] 기존 데이터 백업 중...")
        cursor = await conn.execute("SELECT data FROM test_positions WHERE id = 1")
        row = await cursor.fetchone()
        
        if not row:
            logger.info("[마이그레이션] 기존 데이터 없음 (빈 테이블)")
            old_data = {}
        else:
            from backend.app.db.json_utils import decode_json_field
            old_data = decode_json_field(row["data"], expected_type=dict) or {}
            logger.info("[마이그레이션] 기존 데이터 로드 완료: %d종목", len(old_data))
        
        # 2. 기존 테이블 백업
        logger.info("[마이그레이션] 기존 테이블 백업 중...")
        await conn.execute("DROP TABLE IF EXISTS test_positions_backup")
        await conn.execute("ALTER TABLE test_positions RENAME TO test_positions_backup")
        await conn.commit()
        
        # 3. 새 테이블 생성
        logger.info("[마이그레이션] 새 테이블 생성 중...")
        await conn.execute('''
            CREATE TABLE test_positions (
                stk_cd TEXT PRIMARY KEY,
                stk_nm TEXT,
                qty INTEGER,
                avg_price INTEGER,
                cur_price INTEGER,
                total_fee INTEGER,
                buy_amt INTEGER,
                eval_amt INTEGER,
                pnl_amount INTEGER,
                pnl_rate REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.commit()
        
        # 4. 데이터 이전
        logger.info("[마이그레이션] 데이터 이전 중...")
        for stk_cd, pos_data in old_data.items():
            await conn.execute('''
                INSERT OR REPLACE INTO test_positions (
                    stk_cd, stk_nm, qty, avg_price, cur_price,
                    total_fee, buy_amt, eval_amt, pnl_amount, pnl_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                stk_cd,
                pos_data.get("stk_nm", ""),
                pos_data.get("qty", 0),
                pos_data.get("avg_price", 0),
                pos_data.get("cur_price", 0),
                pos_data.get("total_fee", 0),
                pos_data.get("buy_amt", 0),
                pos_data.get("eval_amt", 0),
                pos_data.get("pnl_amount", 0),
                pos_data.get("pnl_rate", 0.0),
            ))
        
        await conn.commit()
        logger.info("[마이그레이션] 데이터 이전 완료: %d종목", len(old_data))
        
        # 5. 백업 테이블 삭제
        logger.info("[마이그레이션] 백업 테이블 삭제 중...")
        await conn.execute("DROP TABLE test_positions_backup")
        await conn.commit()
        
        logger.info("[마이그레이션] 완료")
        
    except Exception as e:
        logger.error("[마이그레이션] 실패: %s", e)
        await conn.rollback()
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate_test_positions())
