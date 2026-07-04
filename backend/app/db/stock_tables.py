import json
import logging
import sqlite3
from backend.app.db.database import get_db_connection

_log = logging.getLogger(__name__)

async def init_cache_tables():
    """캐시용 테이블들을 생성합니다."""
    conn = await get_db_connection()

    # sector_layout 테이블 삭제 (master_stocks_table sector 컬럼으로 대체)
    # market_map 테이블 삭제 (master_stocks_table로 통합)

    # 6. 정산 상태 테이블
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS settlement_state (
            id INTEGER PRIMARY KEY,
            accumulated_investment INTEGER,
            orderable INTEGER,
            initial_deposit INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 7. 테스트 포지션 테이블
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS test_positions (
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

    # 체결 이력 테이블
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            side TEXT NOT NULL,
            stk_cd TEXT NOT NULL,
            stk_nm TEXT,
            price INTEGER,
            qty INTEGER,
            total_amt INTEGER,
            fee INTEGER,
            tax INTEGER,
            avg_buy_price INTEGER,
            buy_total_amt INTEGER,
            realized_pnl INTEGER,
            pnl_rate REAL,
            reason TEXT,
            trade_mode TEXT NOT NULL
        )
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_trades_date_mode ON trades (date, trade_mode)
    ''')

    # 거래일 캐시 테이블 (exchange_calendars 연 1회 갱신, 이후 DB에서 메모리 로드)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS trading_days_cache (
            year INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )
    ''')

    # eligible_stocks_cache 테이블 삭제 (master_stocks_table이 단일 소스)

    # sector_summary_cache 테이블 삭제 (메모리 캐시로 대체)

    # 커스텀 업종 매핑 테이블 (종목 → 업종 원본 매핑)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS custom_sectors (
            stock_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            hidden INTEGER DEFAULT 0
        )
    ''')

    # 통합 시스템 설정 테이블 (단일 사용자 설정 저장)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS integrated_system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 업종 정의 테이블 (빈 업종 생성용 — custom_sectors는 stock_code가 PK이므로 종목 없이 업종 정의 불가)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS sectors (
            name TEXT PRIMARY KEY
        )
    ''')

    # 기존 종목 파생 업종을 sectors 테이블로 마이그레이션 (idempotent)
    await conn.execute('''
        INSERT OR IGNORE INTO sectors (name)
        SELECT DISTINCT sector FROM master_stocks_table
        WHERE sector IS NOT NULL AND sector != '' AND sector != '미분류'
    ''')

    await conn.commit()
    _log.info("SQLite 캐시 테이블 초기화 완료.")

# ── 정산 상태 ─────────────────────────────────────────────────────────────
async def save_settlement_state(data: dict) -> None:
    """정산 상태 저장"""
    try:
        from backend.app.db.db_writer import execute_db_write, DBWriteOperation
        query = """INSERT OR REPLACE INTO settlement_state 
                   (id, accumulated_investment, orderable, initial_deposit) 
                   VALUES (1, ?, ?, ?)"""
        params = (data.get("accumulated_investment", 0),
                  data.get("orderable", 0),
                  data.get("initial_deposit", 0))
        op = DBWriteOperation(
            table="settlement_state",
            operation="INSERT_OR_REPLACE",
            data={},
            query=query,
            params=params,
        )
        await execute_db_write(op, wait=True)
    except Exception as e:
        _log.warning("[settlement_state] 저장 실패: %s", e)

async def load_settlement_state() -> dict | None:
    """정산 상태 로드"""
    try:
        conn = await get_db_connection()
        cursor = await conn.execute("""SELECT accumulated_investment, orderable, initial_deposit 
                                        FROM settlement_state WHERE id = 1""")
        row = await cursor.fetchone()
        if row:
            return {
                "accumulated_investment": row["accumulated_investment"],
                "orderable": row["orderable"],
                "initial_deposit": row["initial_deposit"],
            }
    except Exception as e:
        _log.warning("[settlement_state] 로드 실패: %s", e)
    return None




# ── 테스트 포지션 ─────────────────────────────────────────────────────────
async def save_test_positions(data: dict) -> None:
    """테스트 포지션 저장 (개별 컬럼)"""
    try:
        conn = await get_db_connection()
        
        # 기존 데이터 삭제
        await conn.execute("DELETE FROM test_positions")
        
        # 각 종목별로 INSERT
        for stk_cd, pos_data in data.items():
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
    except Exception as e:
        _log.warning("[test_positions] 저장 실패: %s", e)

async def load_test_positions() -> dict | None:
    """테스트 포지션 로드 (개별 컬럼)"""
    try:
        conn = await get_db_connection()
        cursor = await conn.execute('''
            SELECT stk_cd, stk_nm, qty, avg_price, cur_price,
                   total_fee, buy_amt, eval_amt, pnl_amount, pnl_rate
            FROM test_positions
        ''')
        rows = await cursor.fetchall()
        
        if not rows:
            return {}
        
        result = {}
        for row in rows:
            result[row["stk_cd"]] = {
                "stk_cd": row["stk_cd"],
                "stk_nm": row["stk_nm"],
                "qty": row["qty"],
                "avg_price": row["avg_price"],
                "cur_price": row["cur_price"],
                "total_fee": row["total_fee"],
                "buy_amt": row["buy_amt"],
                "eval_amt": row["eval_amt"],
                "pnl_amount": row["pnl_amount"],
                "pnl_rate": row["pnl_rate"],
            }
        
        return result
    except Exception as e:
        _log.warning("[test_positions] 로드 실패: %s", e)
    return None


# eligible_stocks_cache 함수 삭제 (master_stocks_table이 단일 소스)

# sector_summary_cache 삭제 (메모리 캐시로 대체)



async def create_master_stocks_table():
    """master_stocks_table 테이블 생성 (통합 마스터 테이블 - 모든 시세/업종 일괄 관리)"""
    conn = await get_db_connection()

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS master_stocks_table (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT,
            sector TEXT,
            cur_price INTEGER,
            change INTEGER,
            change_rate REAL,
            trade_amount INTEGER,  -- 백만원 단위
            avg_5d_trade_amount INTEGER,  -- 백만원 단위
            high_5d_price INTEGER,
            date TEXT,
            nxt_enable INTEGER DEFAULT 0
        )
    ''')

    # 인덱스 생성
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_sector ON master_stocks_table(sector)')

    await conn.commit()
    _log.info("master_stocks_table 테이블 초기화 완료.")


async def migrate_master_stocks_table_pk():
    """master_stocks_table의 code 컬럼 PRIMARY KEY 복구 (초기 1회 마이그레이션).

    과거 CREATE TABLE AS SELECT 또는 제약조건 없는 생성으로 인해
    code 컬럼의 PRIMARY KEY가 소실된 경우 복구한다.
    """
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
    columns = await cursor.fetchall()
    if not columns:
        _log.info("[마이그레이션] master_stocks_table 없음 — skip PK migration")
        return

    code_col = next((col for col in columns if col["name"] == "code"), None)
    if code_col and code_col["pk"] >= 1:
        return

    _log.warning("[마이그레이션] master_stocks_table code 컬럼 PK 소실 — 재생성 시작")

    await conn.execute("""
        CREATE TABLE _master_stocks_table_pk_tmp (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT,
            sector TEXT,
            cur_price INTEGER,
            change INTEGER,
            change_rate REAL,
            trade_amount INTEGER,
            avg_5d_trade_amount INTEGER,
            high_5d_price INTEGER,
            date TEXT,
            nxt_enable INTEGER DEFAULT 0
        )
    """)
    await conn.execute("""
        INSERT INTO _master_stocks_table_pk_tmp
            (code, name, market, sector, cur_price, change, change_rate,
             trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable)
        SELECT code, name, market, sector, cur_price, change, change_rate,
               trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable
        FROM master_stocks_table
    """)
    await conn.execute("DROP TABLE master_stocks_table")
    await conn.execute("ALTER TABLE _master_stocks_table_pk_tmp RENAME TO master_stocks_table")

    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_sector ON master_stocks_table(sector)')
    await conn.commit()
    _log.info("[마이그레이션] master_stocks_table code PRIMARY KEY 복구 완료")


async def migrate_drop_high_price_column():
    """기존 master_stocks_table에서 high_price 컬럼 제거 (마이그레이션).

    CREATE TABLE AS SELECT 대신 명시적 스키마 + INSERT INTO SELECT를 사용하여
    PRIMARY KEY 등 제약조건이 보존되도록 한다.
    """
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
    columns = await cursor.fetchall()
    column_names = {col["name"] for col in columns}

    if "high_price" in column_names:
        await conn.execute("""
            CREATE TABLE _master_stocks_table_tmp (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                market TEXT,
                sector TEXT,
                cur_price INTEGER,
                change INTEGER,
                change_rate REAL,
                trade_amount INTEGER,
                avg_5d_trade_amount INTEGER,
                high_5d_price INTEGER,
                date TEXT,
                nxt_enable INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            INSERT INTO _master_stocks_table_tmp
                (code, name, market, sector, cur_price, change, change_rate,
                 trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable)
            SELECT code, name, market, sector, cur_price, change, change_rate,
                   trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable
            FROM master_stocks_table
        """)
        await conn.execute("DROP TABLE master_stocks_table")
        await conn.execute("ALTER TABLE _master_stocks_table_tmp RENAME TO master_stocks_table")
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_sector ON master_stocks_table(sector)')
        await conn.commit()
        _log.info("[마이그레이션] master_stocks_table에서 high_price 컬럼 제거 완료")


async def migrate_add_hidden_to_custom_sectors():
    """기존 custom_sectors에 hidden 컬럼 추가 (마이그레이션).
    앱 기동 시마다 1회 실행하여 구 버전 DB에서도 hidden 컬럼이 보장되도록 한다."""
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(custom_sectors)")
    columns = await cursor.fetchall()
    column_names = {col["name"] for col in columns}

    if "hidden" not in column_names:
        await conn.execute("ALTER TABLE custom_sectors ADD COLUMN hidden INTEGER DEFAULT 0")
        await conn.commit()
        _log.info("[마이그레이션] custom_sectors에 hidden 컬럼 추가 완료")
    else:
        _log.debug("[마이그레이션] custom_sectors hidden 컬럼 이미 존재 - 스킵")


async def migrate_add_nxt_enable_column():
    """기존 master_stocks_table에 nxt_enable 컬럼 추가 (마이그레이션).
    앱 기동 시마다 1회 실행하여 구 버전 DB에서도 nxt_enable 컬럼이 보장되도록 한다."""
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
    columns = await cursor.fetchall()
    column_names = {col["name"] for col in columns}

    if "nxt_enable" not in column_names:
        await conn.execute("ALTER TABLE master_stocks_table ADD COLUMN nxt_enable INTEGER DEFAULT 0")
        await conn.commit()
        _log.info("[마이그레이션] master_stocks_table에 nxt_enable 컬럼 추가 완료")
    else:
        _log.debug("[마이그레이션] nxt_enable 컬럼 이미 존재 - 스킵")


# load_stock_name_cache 함수 삭제: 메모리 캐시(_master_stocks_cache)로 단일화

async def create_stock_5d_array_table():
    """stock_5d_array 테이블 생성 (5일봉 배열 데이터 저장용)"""
    conn = await get_db_connection()
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS stock_5d_array (
            code TEXT PRIMARY KEY,
            date TEXT,
            day1_amount INTEGER,  -- 백만원 단위
            day2_amount INTEGER,  -- 백만원 단위
            day3_amount INTEGER,  -- 백만원 단위
            day4_amount INTEGER,  -- 백만원 단위
            day5_amount INTEGER,  -- 백만원 단위
            day1_high INTEGER,
            day2_high INTEGER,
            day3_high INTEGER,
            day4_high INTEGER,
            day5_high INTEGER
        )
    ''')
    await conn.commit()
    _log.info("stock_5d_array 테이블 초기화 완료.")


async def migrate_stock_5d_array_pk():
    """기존 (code, date) PK → code 단일 PK 마이그레이션"""
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_5d_array'")
    row = await cursor.fetchone()
    if row is None:
        return
    schema_sql = row["sql"] if isinstance(row, sqlite3.Row) or hasattr(row, "__getitem__") else row[0]
    if "PRIMARY KEY (code, date)" not in schema_sql:
        _log.debug("[마이그레이션] stock_5d_array PK 이미 code 단일 — 스킵")
        return
    _log.info("[마이그레이션] stock_5d_array PK (code, date) → code 단일 변경 시작")
    await conn.execute('CREATE TABLE IF NOT EXISTS stock_5d_array_new (code TEXT PRIMARY KEY, date TEXT, day1_amount INTEGER, day2_amount INTEGER, day3_amount INTEGER, day4_amount INTEGER, day5_amount INTEGER, day1_high INTEGER, day2_high INTEGER, day3_high INTEGER, day4_high INTEGER, day5_high INTEGER)')
    await conn.execute('''INSERT OR REPLACE INTO stock_5d_array_new (code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount, day1_high, day2_high, day3_high, day4_high, day5_high)
        SELECT code, date, day1_amount, day2_amount, day3_amount, day4_amount, day5_amount, day1_high, day2_high, day3_high, day4_high, day5_high
        FROM stock_5d_array
        WHERE (code, date) IN (SELECT code, MAX(date) FROM stock_5d_array GROUP BY code)
    ''')
    await conn.execute('DROP TABLE stock_5d_array')
    await conn.execute('ALTER TABLE stock_5d_array_new RENAME TO stock_5d_array')
    await conn.commit()
    _log.info("[마이그레이션] stock_5d_array PK 변경 완료 — 종목당 최신 1행만 유지")


# ── 거래일 캐시 ─────────────────────────────────────────────────────────────

async def save_trading_days_cache(cache: dict[int, set[str]]) -> None:
    """거래일 캐시를 DB에 저장 (연도별 거래일 set)."""
    try:
        conn = await get_db_connection()
        for year, days_set in cache.items():
            data_json = json.dumps(sorted(days_set))
            await conn.execute(
                "INSERT OR REPLACE INTO trading_days_cache (year, data) VALUES (?, ?)",
                (year, data_json)
            )
        await conn.commit()
        _log.info("[trading_days_cache] DB 저장 완료 — %d개 연도", len(cache))
    except Exception as e:
        _log.warning("[trading_days_cache] 저장 실패: %s", e)


async def load_trading_days_cache() -> dict[int, set[str]] | None:
    """DB에서 거래일 캐시 로드. 데이터 없으면 None 반환."""
    try:
        conn = await get_db_connection()
        cursor = await conn.execute("SELECT year, data FROM trading_days_cache")
        rows = await cursor.fetchall()
        if not rows:
            return None
        result: dict[int, set[str]] = {}
        for row in rows:
            result[row["year"]] = set(json.loads(row["data"]))
        _log.debug("[trading_days_cache] DB 로드 완료 — %d개 연도", len(result))
        return result
    except Exception as e:
        _log.warning("[trading_days_cache] 로드 실패: %s", e)
        return None


async def load_master_stocks_table() -> dict[str, dict]:
    """master_stocks_table 전체를 메모리(KrX format)로 로드 (단일 테이블 조회)"""
    try:
        conn = await get_db_connection()
        cursor = await conn.execute("""
            SELECT code, name, market, sector, cur_price, change, change_rate,
                   trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable
            FROM master_stocks_table
        """)
        rows = await cursor.fetchall()
        
        result = {}
        for r in rows:
            code = str(r["code"])
            sector = str(r["sector"] or "미분류")
            
            result[code] = {
                "name": str(r["name"] or ""),
                "market": str(r["market"] or ""),
                "nxt_enable": bool(r["nxt_enable"] or 0),
                "cur_price": int(r["cur_price"] or 0),
                "change": int(r["change"] or 0),
                "change_rate": float(r["change_rate"] or 0.0),
                "sign": "3",
                "trade_amount": int(r["trade_amount"] or 0),
                "avg_5d_trade_amount": int(r["avg_5d_trade_amount"] or 0),
                "high_5d_price": float(r["high_5d_price"] or 0),
                "date": str(r["date"] or ""),
                "volume": 0,
                "sector": sector,
                "status": "active"
            }
        _log.info("[master_stocks_table] 로드 완료 -- %d종목", len(result))
        return result
    except Exception as e:
        _log.warning("[master_stocks_table] 로드 실패: %s", e)
        return {}


