# -*- coding: utf-8 -*-
"""
SQLite DB 마이그레이션 v3 (종목명/시장구분 메타데이터를 master_stocks_table로 통합, strength 제외, 원천 테이블 독립 유지)
"""

import logging
import sqlite3
from backend.app.db.database import get_db_connection

logger = logging.getLogger(__name__)


async def run_migration_v3() -> None:
    """SQLite DB 구조 개편 마이그레이션 v3 수행 (종목 시세 데이터마트 테이블 및 원천 테이블 분리 구축)"""
    conn = await get_db_connection()
    
    try:
        # --- 1. master_stocks_table 스펙 검사 ---
        cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
        columns = await cursor.fetchall()
        column_names = [col["name"] for col in columns]
        
        # 이전 마이그레이션이 중단되어 _old_v3 백업 테이블이 남아있는지 확인
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_stocks_table_old_v3'")
        backup_table_exists = await cursor.fetchone() is not None
        
        # master_stocks_table에 market, sector, nxt_enable이 없거나, strength가 여전히 들어있거나, day1_amount(v3 중간 버그 규격)가 들어가 있다면 재구축
        # 또는 이전에 중단된 마이그레이션 흔적(_old_v3 테이블)이 존재하면 재구축
        needs_migration = (
            backup_table_exists or
            "market" not in column_names or 
            "sector" not in column_names or 
            "nxt_enable" not in column_names or
            "strength" in column_names or 
            "day1_amount" in column_names
        )
        
        if needs_migration:
            logger.info("[마이그레이션 v3] master_stocks_table 구조 불일치 감지. 최종 데이터마트 규격으로 재구축 및 메타데이터 통합 시작...")
            
            # 이전 마이그레이션이 중간에 실패한 경우: master_stocks_table_old_v3가 이미 존재할 수 있음
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_stocks_table_old_v3'")
            old_backup_exists = await cursor.fetchone() is not None
            
            # 현재 master_stocks_table이 이전 마이그레이션에서 이미 신규 규격으로 생성됐는지 확인
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='master_stocks_table'")
            current_mst_exists = await cursor.fetchone() is not None
            
            if old_backup_exists:
                # 복구 시나리오: _old_v3가 실제 데이터 원본 → _old_v3의 실제 컬럼 목록으로 교체
                cursor = await conn.execute("PRAGMA table_info(master_stocks_table_old_v3)")
                old_v3_cols = await cursor.fetchall()
                column_names = [col["name"] for col in old_v3_cols]  # ← 백업 테이블 기준으로 재설정
                
                if current_mst_exists:
                    # 이전 마이그레이션이 RENAME 후 중단됨
                    # → 신규 master_stocks_table이 불완전할 수 있으므로 삭제 후 재생성
                    logger.warning("[마이그레이션 v3] 이전 중단된 마이그레이션 감지 — master_stocks_table 삭제 후 재생성")
                    await conn.execute("DROP TABLE IF EXISTS master_stocks_table")
                else:
                    # RENAME 성공 후 CREATE TABLE 전에 중단됨
                    logger.warning("[마이그레이션 v3] 이전 중단된 마이그레이션 감지 — master_stocks_table_old_v3에서 복구 시작")
            else:
                # 1-1. 기존 시세 테이블 백업용 이름 변경 (정상 경로)
                await conn.execute("ALTER TABLE master_stocks_table RENAME TO master_stocks_table_old_v3")
            
            # 1-2. 신규 최종 규격 master_stocks_table 생성 (strength 삭제, sector/market/nxt_enable 추가, day1~5 제외, avg_5d_trade_amount INTEGER로 변경)
            await conn.execute("""
                CREATE TABLE master_stocks_table (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    market TEXT,
                    sector TEXT,
                    cur_price REAL,
                    change REAL,
                    change_rate REAL,
                    trade_amount REAL,
                    avg_5d_trade_amount INTEGER,
                    high_5d_price REAL,
                    date TEXT,
                    nxt_enable INTEGER DEFAULT 0
                )
            """)
            
            # 1-3. 신규 인덱스 추가
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)")
            
            # 1-4. 안전한 원천 테이블 생성 보장 (custom_sector_mappings & stock_5d_array)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_sector_mappings (
                    code TEXT PRIMARY KEY,
                    sector TEXT NOT NULL
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_5d_array (
                    code TEXT,
                    date TEXT,
                    day1_amount REAL,
                    day2_amount REAL,
                    day3_amount REAL,
                    day4_amount REAL,
                    day5_amount REAL,
                    day1_high REAL,
                    day2_high REAL,
                    day3_high REAL,
                    day4_high REAL,
                    day5_high REAL,
                    PRIMARY KEY (code, date)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_5d_array_code ON stock_5d_array(code)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_5d_array_date ON stock_5d_array(date)")
            
            # 1-5. 기존에 나뉘어 있던 기본 메타데이터(stock_names, market_map) 및 업종/5일봉 정보 수집
            # stock_names 테이블 존재 여부
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_names'")
            has_names_table = await cursor.fetchone() is not None
            
            # market_map 테이블 존재 여부
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_map'")
            has_market_table = await cursor.fetchone() is not None
            
            # custom_sector_mappings 테이블 존재 여부
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_sector_mappings'")
            has_sector_table = await cursor.fetchone() is not None
            
            # stock_5d_array 테이블 존재 여부
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_5d_array'")
            has_array_table = await cursor.fetchone() is not None
            
            # 구 마스터 데이터 백업 조회
            cursor = await conn.execute("SELECT * FROM master_stocks_table_old_v3")
            old_mst_rows = await cursor.fetchall()
            
            # 종목명 맵 로드
            names_map = {}
            if has_names_table:
                cursor = await conn.execute("SELECT code, name FROM stock_names")
                for r in await cursor.fetchall():
                    names_map[r["code"]] = r["name"]
                    
            # 시장구분 및 NXT 여부 맵 로드
            market_map = {}
            nxt_map = {}
            if has_market_table:
                cursor = await conn.execute("PRAGMA table_info(market_map)")
                mm_cols = {col["name"] for col in await cursor.fetchall()}
                if "is_nxt" in mm_cols:
                    cursor = await conn.execute("SELECT code, market, is_nxt FROM market_map")
                    for r in await cursor.fetchall():
                        market_map[r["code"]] = r["market"]
                        nxt_map[r["code"]] = bool(r["is_nxt"])
                else:
                    cursor = await conn.execute("SELECT code, market FROM market_map")
                    for r in await cursor.fetchall():
                        market_map[r["code"]] = r["market"]
            
            # 만약 기존에 custom_sector_mappings 테이블이 비어있거나 없었다면, 구 마스터 테이블의 sector 컬럼에서 백업
            sector_backup = []
            if "sector" in column_names:
                cursor = await conn.execute("SELECT code, sector FROM master_stocks_table_old_v3 WHERE sector IS NOT NULL AND sector != ''")
                sector_backup = await cursor.fetchall()
                
            if has_sector_table and sector_backup:
                for r in sector_backup:
                    await conn.execute("INSERT OR IGNORE INTO custom_sector_mappings (code, sector) VALUES (?, ?)", (r["code"], r["sector"]))
            
            # 만약 기존에 stock_5d_array 테이블에 데이터가 없고 구 마스터 테이블에 day1~5 정보가 남아있었다면 백업
            if "day1_amount" in column_names:
                cursor = await conn.execute("""
                    SELECT code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                           day1_high, day2_high, day3_high, day4_high, day5_high 
                    FROM master_stocks_table_old_v3
                """)
                for r in await cursor.fetchall():
                    await conn.execute("""
                        INSERT OR IGNORE INTO stock_5d_array 
                        (code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount,
                         day1_high, day2_high, day3_high, day4_high, day5_high)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (r["code"], r["date"], r["day1_amount"], r["day2_amount"], r["day3_amount"], r["day4_amount"], r["day5_amount"],
                          r["day1_high"], r["day2_high"], r["day3_high"], r["day4_high"], r["day5_high"]))
            
            # 최종 마스터 테이블 데이터 구성 및 복원 인서트
            # 5일 평균 및 고가는 stock_5d_array와 연동
            for r in old_mst_rows:
                r_dict = dict(r)
                code = r_dict["code"]
                date = r_dict["date"]
                
                # 메타데이터 병합
                name = names_map.get(code) or r_dict.get("name") or code
                market = market_map.get(code) or r_dict.get("market") or ""
                
                # 업종 매핑 병합
                sector = "기타"
                if has_sector_table:
                    cursor = await conn.execute("SELECT sector FROM custom_sector_mappings WHERE code = ?", (code,))
                    s_row = await cursor.fetchone()
                    if s_row:
                        sector = s_row["sector"]
                else:
                    sector = r_dict.get("sector") or "기타"
                    
                # 5일 평균 및 최고가 계산값 복원
                avg_5d = r_dict.get("avg_5d_trade_amount") or 0.0
                high_5d = r_dict.get("high_5d_price") or 0.0
                
                # 새 마스터에 데이터 인서트
                await conn.execute("""
                    INSERT OR REPLACE INTO master_stocks_table
                    (code, name, market, sector, cur_price, change, change_rate, trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    code, name, market, sector, 
                    r_dict.get("cur_price") or 0.0, 
                    r_dict.get("change") or 0.0, 
                    r_dict.get("change_rate") or 0.0, 
                    r_dict.get("trade_amount") or 0.0, 
                    avg_5d, high_5d, date,
                    1 if nxt_map.get(code) or r_dict.get("nxt_enable") else 0
                ))
            
            # 1-6. 불필요해진 구 테이블 삭제
            await conn.execute("DROP TABLE IF EXISTS master_stocks_table_old_v3")
            await conn.execute("DROP TABLE IF EXISTS stock_names")
            await conn.execute("DROP TABLE IF EXISTS market_map")
            
            await conn.commit()
            logger.info("[마이그레이션 v3] master_stocks_table 최종 통합 완료. stock_names 및 market_map 삭제 완료 (%d건)", len(old_mst_rows))
        else:
            # 혹시 모를 정리 처리
            await conn.execute("DROP TABLE IF EXISTS stock_names")
            await conn.execute("DROP TABLE IF EXISTS market_map")
            await conn.commit()
            logger.info("[마이그레이션 v3] master_stocks_table 이미 최종 데이터마트 규격에 부합함. 마이그레이션 스킵.")
            
    except Exception as e:
        await conn.rollback()
        logger.error("[마이그레이션 v3] 처리 실패: %s", e, exc_info=True)
        raise e
