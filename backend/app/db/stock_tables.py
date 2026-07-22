import logging
from backend.app.db.database import get_db_connection
from backend.app.db.json_utils import dumps, loads

logger = logging.getLogger(__name__)

async def _create_runtime_tables(conn) -> None:
    """정산/체결이력/거래일 캐시 테이블 생성 (init_cache_tables 헬퍼)."""
    # 정산 상태 테이블
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS settlement_state (
            id INTEGER PRIMARY KEY,
            accumulated_investment INTEGER,
            orderable INTEGER,
            initial_deposit INTEGER,
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
            trade_mode TEXT NOT NULL,
            buy_date TEXT
        )
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_trades_date_mode ON trades (date, trade_mode)
    ''')

    # 거래일 캐시 테이블 (korean_lunar_calendar 기반 연 1회 갱신, 이후 DB에서 메모리 로드)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS trading_days_cache (
            year INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )
    ''')


async def _create_user_tables(conn) -> None:
    """사용자 업종/설정/업종정의 테이블 생성 + 종목 파생 업종 마이그레이션 (init_cache_tables 헬퍼)."""
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


async def init_cache_tables():
    """캐시용 테이블들을 생성합니다 (runtime + 사용자 테이블 그룹)."""
    conn = await get_db_connection()
    # sector_layout/market_map/eligible_stocks_cache/sector_summary_cache 테이블은
    # master_stocks_table sector 컬럼 또는 메모리 캐시로 대체되어 제거됨.
    await _create_runtime_tables(conn)
    await _create_user_tables(conn)
    # order_time_guard_on 토글 제거 마이그레이션 (idempotent) — 시장가 단일 운용에서
    # OFF의 의미가 없어 토글 자체를 제거. key-value row이므로 스키마 변경 아님.
    await conn.execute(
        "DELETE FROM integrated_system_settings WHERE key = 'order_time_guard_on'"
    )
    await conn.commit()
    logger.info("SQLite 캐시 테이블 초기화 완료.")

# ── 정산 상태 ─────────────────────────────────────────────────────────────
async def save_settlement_state(data: dict) -> None:
    """정산 상태 저장. 예외 전파 (P20) — 호출자가 실패를 인지."""
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

async def load_settlement_state() -> dict | None:
    """정산 상태 로드. 행이 없으면 None 반환, DB 에러 시 예외 전파."""
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
    return None


# test_positions 테이블 및 관련 함수 제거 — trades 테이블이 보유 포지션 SSOT
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
    logger.info("전종목 마스터 테이블 초기화 완료.")


async def _rebuild_master_stocks_with_pk(conn) -> None:
    """기본키 소실된 master_stocks_table을 tmp 테이블 경유로 재생성 (마이그레이션 헬퍼)."""
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
    await conn.execute("ALTER TABLE master_stocks_table RENAME TO _master_stocks_table_old")
    await conn.execute("ALTER TABLE _master_stocks_table_pk_tmp RENAME TO master_stocks_table")

    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_sector ON master_stocks_table(sector)')
    await conn.commit()
    logger.info("[데이터] 전종목 마스터 테이블 종목코드 기본키 복구 완료 — 백업 테이블 삭제 진행")

    await conn.execute("DROP TABLE _master_stocks_table_old")
    await conn.commit()
    logger.info("[데이터] 전종목 마스터 테이블 마이그레이션 백업 테이블 삭제 완료")


async def migrate_master_stocks_table_pk():
    """master_stocks_table의 code 컬럼 PRIMARY KEY 복구 (초기 1회 마이그레이션).

    과거 CREATE TABLE AS SELECT 또는 제약조건 없는 생성으로 인해
    code 컬럼의 PRIMARY KEY가 소실된 경우 복구한다.
    """
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
    columns = await cursor.fetchall()
    if not columns:
        logger.info("[데이터] 전종목 마스터 테이블 없음 — 기본키 마이그레이션 생략")
        return

    code_col = next((col for col in columns if col["name"] == "code"), None)
    if code_col and code_col["pk"] >= 1:
        return

    logger.warning("[데이터] 전종목 마스터 테이블 종목코드 컬럼 기본키 소실 — 재생성 시작")
    await _rebuild_master_stocks_with_pk(conn)


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
        logger.info("[데이터] 사용자 업종에 숨김 컬럼 추가 완료")
    else:
        logger.debug("[데이터] 사용자 업종 숨김 컬럼 이미 존재 - 생략")


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
        logger.info("[데이터] 전종목 마스터 테이블에 NXT 거래 가능 컬럼 추가 완료")
    else:
        logger.debug("[데이터] NXT 거래 가능 컬럼 이미 존재 - 생략")


async def migrate_add_buy_date_to_trades():
    """기존 trades에 buy_date 컬럼 추가 (마이그레이션).

    매도 레코드에 한해 해당 종목의 최초 매수일(잔여 FIFO lot 기준)을 저장.
    앱 기동 시마다 1회 실행하여 구 버전 DB에서도 buy_date 컬럼이 보장되도록 한다.
    """
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(trades)")
    columns = await cursor.fetchall()
    column_names = {col["name"] for col in columns}

    if "buy_date" not in column_names:
        await conn.execute("ALTER TABLE trades ADD COLUMN buy_date TEXT")
        await conn.commit()
        logger.info("[데이터] 체결 이력 테이블에 매수일 컬럼 추가 완료")
    else:
        logger.debug("[데이터] 체결 이력 매수일 컬럼 이미 존재 - 생략")


# load_stock_name_cache 함수 삭제: 메모리 캐시(_master_stocks_cache)로 단일화

async def create_stock_5d_bars_table():
    """stock_5d_bars 테이블 생성 (5일봉 세로 행 데이터 저장용).

    가로 배열(day1~day5) 구조를 세로 행으로 변경 — 각 일봉이 (종목코드, 거래일) 복합키로 1행 저장.
    기존 stock_5d_array 테이블은 각 day의 실제 날짜를 알 수 없어 마이그레이션 불가 → DROP 후 신규 시작 (P10/P22/P24).
    """
    conn = await get_db_connection()
    # 기존 가로 배열 테이블 제거 (날짜 모호성이 근본 원인 — 마이그레이션 불가)
    await conn.execute("DROP TABLE IF EXISTS stock_5d_array")
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS stock_5d_bars (
            code TEXT NOT NULL,
            dt TEXT NOT NULL,           -- 실제 거래일 (YYYYMMDD)
            trade_amount INTEGER,       -- 백만원 단위
            high_price INTEGER,         -- 원 단위
            PRIMARY KEY (code, dt)
        )
    ''')
    await conn.commit()
    logger.info("5일봉 세로 행 테이블 초기화 완료.")


# ── 거래일 캐시 ─────────────────────────────────────────────────────────────

async def save_trading_days_cache(cache: dict[int, set[str]]) -> None:
    """거래일 캐시를 DB에 저장 (연도별 거래일 set). 예외 전파 (P20)."""
    conn = await get_db_connection()
    for year, days_set in cache.items():
        data_json = dumps(sorted(days_set))
        await conn.execute(
            "INSERT OR REPLACE INTO trading_days_cache (year, data) VALUES (?, ?)",
            (year, data_json)
        )
    await conn.commit()
    logger.info("[스케줄] DB 저장 완료 — %d개 연도", len(cache))


async def load_trading_days_cache() -> dict[int, set[str]] | None:
    """DB에서 거래일 캐시 로드. 데이터 없으면 None 반환, DB 에러 시 예외 전파 (P20)."""
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT year, data FROM trading_days_cache")
    rows = await cursor.fetchall()
    if not rows:
        return None
    result: dict[int, set[str]] = {}
    for row in rows:
        result[row["year"]] = set(loads(row["data"]))
    logger.debug("[스케줄] DB 로드 완료 — %d개 연도", len(result))
    return result


async def load_master_stocks_table() -> dict[str, dict]:
    """master_stocks_table 전체를 메모리(KrX format)로 로드 (단일 테이블 조회).

    DB 에러 시 예외 전파 (P20 폴백 금지) — 호출자(engine_cache)가 빈 dict를
    "데이터 없음"으로 오인하는 것을 방지.
    """
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
            "cur_price": int(r["cur_price"]) if r["cur_price"] is not None else None,
            "change": int(r["change"]) if r["change"] is not None else None,
            "change_rate": float(r["change_rate"]) if r["change_rate"] is not None else None,
            "sign": "3",
            "trade_amount": int(r["trade_amount"]) if r["trade_amount"] is not None else None,
            "avg_5d_trade_amount": int(r["avg_5d_trade_amount"] or 0),
            "high_5d_price": float(r["high_5d_price"] or 0),
            "date": str(r["date"] or ""),
            "volume": 0,
            "sector": sector,
            "status": "active"
        }
    logger.info("[데이터] 로드 완료 — %d종목", len(result))
    return result


