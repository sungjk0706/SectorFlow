# -*- coding: utf-8 -*-
"""
SQLite DB 마이그레이션 v2 (master_stocks_table에서 sector 분리, custom_sector_mappings 생성, trading_days_cache 구조화)
"""

import logging
import json
import sqlite3
from backend.app.db.database import get_db_connection

logger = logging.getLogger(__name__)


async def run_migration_v2() -> None:
    """SQLite DB 구조 개편 마이그레이션 v2 수행"""
    conn = await get_db_connection()
    
    try:
        # --- 1. master_stocks_table 구조 변경 및 custom_sector_mappings 신설 ---
        cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
        columns = await cursor.fetchall()
        column_names = [col["name"] for col in columns]
        
        # master_stocks_table에 여전히 sector 컬럼이 존재할 경우 마이그레이션 수행
        if "sector" in column_names:
            logger.info("[마이그레이션 v2] master_stocks_table에서 sector 컬럼 감지. 구조 개편 시작...")
            
            # 1-1. 기존 데이터 백업 (code, sector, name)
            cursor = await conn.execute("SELECT code, sector, name FROM master_stocks_table")
            backup_rows = await cursor.fetchall()
            sector_backup = {row["code"]: row["sector"] for row in backup_rows if row["code"] and row["sector"]}
            
            # 1-2. 기존 인덱스 삭제
            await conn.execute("DROP INDEX IF EXISTS idx_sector")
            await conn.execute("DROP INDEX IF EXISTS idx_date")
            await conn.execute("DROP INDEX IF EXISTS idx_sector_date")
            
            # 1-3. 기존 테이블 백업을 위한 이름 변경
            await conn.execute("ALTER TABLE master_stocks_table RENAME TO master_stocks_table_old")
            
            # 1-4. 신규 최적화 master_stocks_table 생성
            await conn.execute("""
                CREATE TABLE master_stocks_table (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    market TEXT,
                    cur_price REAL,
                    change REAL,
                    change_rate REAL,
                    strength TEXT,
                    trade_amount REAL,
                    avg_5d_trade_amount REAL,
                    high_5d_price REAL,
                    date TEXT
                )
            """)
            
            # 1-5. 신규 인덱스 추가
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)")
            
            # 1-6. 데이터 복원 (sector 제외, market은 기본값 세팅)
            cursor = await conn.execute("SELECT code, market FROM market_map")
            mkt_rows = await cursor.fetchall()
            mkt_map = {r["code"]: r["market"] for r in mkt_rows}
            
            cursor = await conn.execute("""
                SELECT code, name, cur_price, change, change_rate, strength, trade_amount, avg_5d_trade_amount, high_5d_price, date 
                FROM master_stocks_table_old
            """)
            old_data_rows = await cursor.fetchall()
            
            insert_mst_values = []
            for r in old_data_rows:
                code = r["code"]
                market = mkt_map.get(code, "")
                insert_mst_values.append((
                    code, r["name"], market, r["cur_price"], r["change"], r["change_rate"],
                    r["strength"], r["trade_amount"], r["avg_5d_trade_amount"], r["high_5d_price"], r["date"]
                ))
                
            if insert_mst_values:
                await conn.executemany("""
                    INSERT INTO master_stocks_table 
                    (code, name, market, cur_price, change, change_rate, strength, trade_amount, avg_5d_trade_amount, high_5d_price, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_mst_values)
                
            # 1-7. 백업본 삭제
            await conn.execute("DROP TABLE master_stocks_table_old")
            logger.info("[마이그레이션 v2] master_stocks_table 구조 개선 및 데이터 이전 완료")
            
            # 1-8. custom_sector_mappings 생성 및 백업 데이터 인입
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_sector_mappings (
                    code TEXT PRIMARY KEY,
                    sector TEXT NOT NULL,
                    FOREIGN KEY(code) REFERENCES master_stocks_table(code) ON DELETE CASCADE
                )
            """)
            
            insert_sector_values = [(code, sector) for code, sector in sector_backup.items()]
            if insert_sector_values:
                await conn.executemany("""
                    INSERT OR REPLACE INTO custom_sector_mappings (code, sector)
                    VALUES (?, ?)
                """, insert_sector_values)
            logger.info("[마이그레이션 v2] custom_sector_mappings 테이블 생성 및 매핑 데이터 복원 완료 (%d건)", len(insert_sector_values))
        else:
            # 혹시 테이블이 아직 안 만들어졌을 수도 있으므로, custom_sector_mappings 강제 생성 보장
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_sector_mappings (
                    code TEXT PRIMARY KEY,
                    sector TEXT NOT NULL,
                    FOREIGN KEY(code) REFERENCES master_stocks_table(code) ON DELETE CASCADE
                )
            """)
            
        # --- 2. trading_days_cache 구조화 ---
        cursor = await conn.execute("PRAGMA table_info(trading_days_cache)")
        td_columns = await cursor.fetchall()
        td_column_names = [col["name"] for col in td_columns]
        
        if "data" in td_column_names:
            logger.info("[마이그레이션 v2] trading_days_cache에서 JSON Blob 'data' 컬럼 감지. 테이블 구조화 시작...")
            
            # 2-1. 기존 JSON 데이터 파싱 백업
            cursor = await conn.execute("SELECT data FROM trading_days_cache WHERE id = 1")
            td_row = await cursor.fetchone()
            
            parsed_days = {}
            if td_row and td_row["data"]:
                try:
                    parsed_days = json.loads(td_row["data"])
                except Exception as je:
                    logger.warning("[마이그레이션 v2] trading_days JSON 파싱 오류: %s", je)
            
            # 2-2. 기존 테이블 삭제 및 재생성
            await conn.execute("DROP TABLE IF EXISTS trading_days_cache")
            await conn.execute("""
                CREATE TABLE trading_days_cache (
                    year INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    PRIMARY KEY (year, date),
                    CHECK(length(date) = 10 or (year = 0 and length(date) = 8))
                )
            """)
            
            # 2-3. 데이터 정형화 복원 (year, date)
            # 날짜를 YYYY-MM-DD 포맷(10자리)으로 정형화하여 인서트
            insert_td_values = []
            for year_str, dates in parsed_days.items():
                if year_str == "last_updated":
                    # 메타 데이터 저장 (year=0)
                    # YYYYMMDD 형식을 YYYY-MM-DD 형식이 아니더라도 8자리 메타태그로 유지 또는 YYYY-MM-DD 변환
                    val = str(dates)
                    if len(val) == 8:
                        val = f"{val[:4]}-{val[4:6]}-{val[6:]}"
                    insert_td_values.append((0, val))
                else:
                    year = int(year_str)
                    for d_str in dates:
                        # YYYYMMDD -> YYYY-MM-DD 변환
                        if len(d_str) == 8:
                            d_formatted = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"
                        else:
                            d_formatted = d_str
                        insert_td_values.append((year, d_formatted))
            
            if insert_td_values:
                await conn.executemany("""
                    INSERT OR REPLACE INTO trading_days_cache (year, date)
                    VALUES (?, ?)
                """, insert_td_values)
                
            logger.info("[마이그레이션 v2] trading_days_cache 테이블 구조화 완료 (%d건)", len(insert_td_values))
        else:
            # 정형 테이블 강제 생성 보장
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trading_days_cache (
                    year INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    PRIMARY KEY (year, date),
                    CHECK(length(date) = 10 or (year = 0 and length(date) = 8))
                )
            """)
            
        await conn.commit()
        logger.info("[마이그레이션 v2] 전체 마이그레이션 완료 및 데이터 무결성 보장 적용 성공")
    except Exception as e:
        await conn.rollback()
        logger.error("[마이그레이션 v2] 처리 실패: %s", e, exc_info=True)
        raise e
