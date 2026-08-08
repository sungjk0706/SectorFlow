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
            buy_date TEXT,
            sector TEXT,
            buy_rank INTEGER
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

    # 일별 계좌 스냅샷 테이블 (기초자산 분모 방식 — 장마감 후 총자산 저장)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS account_daily_snapshot (
            date TEXT NOT NULL,                  -- 거래일 (YYYY-MM-DD)
            trade_mode TEXT NOT NULL,            -- "test" 또는 "real"
            total_asset INTEGER NOT NULL,        -- 기초자산 (예수금/주문가능금액 + 총평가금액)
            deposit INTEGER,                     -- 예수금 (참조용)
            orderable INTEGER,                   -- 주문가능금액 (참조용)
            total_eval_amount INTEGER,           -- 총평가금액 (참조용)
            accumulated_investment INTEGER,      -- 누적투자금 (참조용, 가상매매)
            daily_deposit INTEGER DEFAULT 0,     -- 당일 입금액
            daily_withdrawal INTEGER DEFAULT 0,  -- 당일 출금액 (현재 0, 후순위)
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (date, trade_mode)
        )
    ''')
    await conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_account_daily_snapshot_date
        ON account_daily_snapshot (date)
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
    logger.info("SQLite 캐시 테이블 생성.")

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


# ── 일별 계좌 스냅샷 (기초자산 분모 방식) ─────────────────────────────────────

async def save_daily_account_snapshot(
    conn,
    *,
    date: str,
    trade_mode: str,
    total_asset: int,
    deposit: int = 0,
    orderable: int = 0,
    total_eval_amount: int = 0,
    accumulated_investment: int = 0,
    daily_deposit: int = 0,
    daily_withdrawal: int = 0,
) -> None:
    """장마감 후 당일 계좌 총자산 스냅샷 저장 (INSERT OR REPLACE).

    P22 데이터 정합성 — total_asset은 호출부에서 원본 account_snapshot에서 파생.
    예외 전파 (P20) — 호출자가 실패를 인지 (P25 격리는 호출부에서 처리).
    """
    await conn.execute(
        """INSERT OR REPLACE INTO account_daily_snapshot
           (date, trade_mode, total_asset, deposit, orderable, total_eval_amount,
            accumulated_investment, daily_deposit, daily_withdrawal, snapshot_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (date, trade_mode, total_asset, deposit, orderable, total_eval_amount,
         accumulated_investment, daily_deposit, daily_withdrawal),
    )
    await conn.commit()


async def get_base_asset_for_period(conn, *, date_from: str, trade_mode: str) -> int | None:
    """기간 시작 시점 기초자산 조회.

    date_from의 전일 장마감 스냅샷 total_asset 반환 (당일 분모 = 전일 종가).
    date_from이 당일이면 전일, 5거래일이면 5일 전, 당월이면 월초.
    없으면 None (프론트에서 초기 투자원금으로 처리 — 결정 6, 폴백 아닌 초기값 정의).
    """
    cursor = await conn.execute(
        """SELECT total_asset FROM account_daily_snapshot
           WHERE date < ? AND trade_mode = ? AND total_asset > 0
           ORDER BY date DESC LIMIT 1""",
        (date_from, trade_mode),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return int(row["total_asset"])


async def get_earliest_base_asset(conn, *, trade_mode: str) -> int | None:
    """해당 모드의 가장 오래된 total_asset 반환 (누적 카드 분모용).

    account_daily_snapshot에서 trade_mode 필터 후 가장 오래된 date의 total_asset.
    없으면 None (프론트에서 rate null → '-' 표시, P20 폴백 금지).

    P10 SSOT — account_daily_snapshot.total_asset 단일 소스.
    """
    cursor = await conn.execute(
        """SELECT total_asset FROM account_daily_snapshot
           WHERE trade_mode = ? AND total_asset > 0
           ORDER BY date ASC LIMIT 1""",
        (trade_mode,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return int(row["total_asset"])


async def get_deposit_history(conn, *, trade_mode: str) -> list[dict]:
    """누적 드릴다운용 입금 이력 조회.

    account_daily_snapshot에서 daily_deposit > 0인 행의 date, daily_deposit 반환.
    date 오름차순 정렬.

    P10 SSOT — account_daily_snapshot.daily_deposit 단일 소스.
    """
    cursor = await conn.execute(
        """SELECT date, daily_deposit FROM account_daily_snapshot
           WHERE trade_mode = ? AND daily_deposit > 0
           ORDER BY date ASC""",
        (trade_mode,),
    )
    rows = await cursor.fetchall()
    return [{"date": r["date"], "daily_deposit": int(r["daily_deposit"])} for r in rows]


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
            nxt_enable INTEGER DEFAULT 0,
            raw_payload TEXT              -- 해석 전 원문 (JSON — 증권사 응답 원본)
        )
    ''')

    # 인덱스 생성
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_sector ON master_stocks_table(sector)')

    await conn.commit()
    logger.info("전종목 마스터 테이블 생성.")


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
            nxt_enable INTEGER DEFAULT 0,
            raw_payload TEXT
        )
    """)
    await conn.execute("""
        INSERT INTO _master_stocks_table_pk_tmp
            (code, name, market, sector, cur_price, change, change_rate,
             trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable,
             raw_payload)
        SELECT code, name, market, sector, cur_price, change, change_rate,
               trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable,
               raw_payload
        FROM master_stocks_table
    """)
    await conn.execute("ALTER TABLE master_stocks_table RENAME TO _master_stocks_table_old")
    await conn.execute("ALTER TABLE _master_stocks_table_pk_tmp RENAME TO master_stocks_table")

    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_market ON master_stocks_table(market)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_date ON master_stocks_table(date)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_avg_5d ON master_stocks_table(avg_5d_trade_amount)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_mst_sector ON master_stocks_table(sector)')
    await conn.commit()
    logger.info("[데이터] 전종목 마스터 테이블 종목코드 기본키 복구 — 백업 테이블 삭제 진행")

    await conn.execute("DROP TABLE _master_stocks_table_old")
    await conn.commit()
    logger.info("[데이터] 전종목 마스터 테이블 마이그레이션 백업 테이블 삭제")


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
        logger.info("[데이터] 사용자 업종에 숨김 컬럼 추가")
    else:
        logger.debug("[데이터] 사용자 업종 숨김 컬럼 이미 존재 - 생략")


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
        logger.info("[데이터] 체결 이력 테이블에 매수일 컬럼 추가")
    else:
        logger.debug("[데이터] 체결 이력 매수일 컬럼 이미 존재 - 생략")


async def migrate_add_buy_reason_columns_to_trades():
    """기존 trades에 매수 근거 구조화 컬럼 2개(sector, buy_rank) 추가 (마이그레이션).

    매수 레코드에 한해 매수 시점 업종(sector)과 매수순위(buy_rank) 저장.
    과거 레코드 및 매도 레코드는 NULL (P20 폴백 아님 — 명시적 미적용).
    앱 기동 시마다 1회 실행하여 구 버전 DB에서도 컬럼이 보장되도록 한다.
    """
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(trades)")
    columns = await cursor.fetchall()
    column_names = {col["name"] for col in columns}

    added = []
    if "sector" not in column_names:
        await conn.execute("ALTER TABLE trades ADD COLUMN sector TEXT")
        added.append("sector")
    if "buy_rank" not in column_names:
        await conn.execute("ALTER TABLE trades ADD COLUMN buy_rank INTEGER")
        added.append("buy_rank")

    if added:
        await conn.commit()
        logger.info("[데이터] 체결 이력 테이블에 매수 근거 컬럼 추가: %s", ", ".join(added))
    else:
        logger.debug("[데이터] 체결 이력 매수 근거 컬럼 이미 존재 - 생략")


async def migrate_add_raw_payload_to_stock_5d_bars():
    """stock_5d_bars에 원문 보존 필드 추가 (마이그레이션).

    설계서 4.1(응답 보존) 반영 — 일봉 행별 원문 보존.
    기존 컬럼의 기본값으로 누락을 정상값처럼 만들지 않는다 (W8 폴백 금지).
    앱 기동 시마다 1회 실행하여 구 버전 DB에서도 필드가 보장되도록 한다.
    """
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(stock_5d_bars)")
    columns = await cursor.fetchall()
    column_names = {col["name"] for col in columns}

    added = []
    if "raw_payload" not in column_names:
        await conn.execute("ALTER TABLE stock_5d_bars ADD COLUMN raw_payload TEXT")
        added.append("raw_payload")

    if added:
        await conn.commit()
        logger.info("[데이터] 5거래일 일봉 테이블에 원문 필드 추가: %s", ", ".join(added))
    else:
        logger.debug("[데이터] 5거래일 일봉 테이블 원문 필드 이미 존재 - 생략")


async def migrate_drop_raw_status_columns():
    """master_stocks_table에서 자료 상태 컬럼 4개 삭제 (마이그레이션).

    자료 상태 시스템 전면 제거 — 코드에서 더 이상 사용하지 않는 컬럼 삭제.
    대상: raw_status, request_date, response_date, problems (raw_payload는 유지).
    멱등성 — 컬럼이 존재할 때만 DROP. 이미 삭제된 경우 스킵.
    안전 규칙 2 준수 — 호출 전 타임스탬프 백업 권장.
    """
    conn = await get_db_connection()

    cursor = await conn.execute("PRAGMA table_info(master_stocks_table)")
    columns = await cursor.fetchall()
    column_names = {col["name"] for col in columns}

    if not column_names:
        logger.info("[데이터] 전종목 마스터 테이블 없음 — 자료 상태 컬럼 삭제 생략")
        return

    drop_targets = ["raw_status", "request_date", "response_date", "problems"]
    to_drop = [c for c in drop_targets if c in column_names]

    if not to_drop:
        logger.debug("[데이터] 전종목 마스터 테이블 자료 상태 컬럼 이미 삭제됨 - 생략")
        return

    for col in to_drop:
        await conn.execute(f'ALTER TABLE master_stocks_table DROP COLUMN "{col}"')
    await conn.commit()
    logger.info("[데이터] 전종목 마스터 테이블 자료 상태 컬럼 삭제: %s", ", ".join(to_drop))


# load_stock_name_cache 함수 삭제: 메모리 캐시(_master_stocks_cache)로 단일화

async def create_stock_5d_bars_table():
    """stock_5d_bars 테이블 생성 (5거래일 일봉 세로 행 데이터 저장용).

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
            raw_payload TEXT,           -- 해석 전 원문 (JSON — 일봉 행별 원문 보존)
            PRIMARY KEY (code, dt)
        )
    ''')
    await conn.commit()
    logger.info("5거래일 일봉 테이블 생성.")


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
    logger.info("[스케줄] DB 저장 — %d개 연도", len(cache))


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
    logger.debug("[스케줄] DB 로드 — %d개 연도", len(result))
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

        # 5일 파생값 None 보존 (P20 폴백 금지) — 0으로 덮어 "자료 없음"을 숨기지 않음.
        avg_5d_raw = r["avg_5d_trade_amount"]
        high_5d_raw = r["high_5d_price"]

        result[code] = {
            "name": str(r["name"] or ""),
            "market": str(r["market"] or ""),
            "nxt_enable": bool(r["nxt_enable"] or 0),
            "cur_price": int(r["cur_price"]) if r["cur_price"] is not None else None,
            "change": int(r["change"]) if r["change"] is not None else None,
            "change_rate": float(r["change_rate"]) if r["change_rate"] is not None else None,
            "sign": "3",
            "trade_amount": int(r["trade_amount"]) if r["trade_amount"] is not None else None,
            "avg_5d_trade_amount": int(avg_5d_raw) if avg_5d_raw is not None else None,
            "high_5d_price": float(high_5d_raw) if high_5d_raw is not None else None,
            "date": str(r["date"] or ""),
            "volume": 0,
            "sector": sector,
            "status": "active",
        }
    logger.info("[데이터] 로드 — %d종목", len(result))
    return result


