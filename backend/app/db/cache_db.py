import sqlite3
import json
import logging
from backend.app.db.database import get_db_connection

_log = logging.getLogger(__name__)

def init_cache_tables():
    """캐시용 테이블들을 생성합니다."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 업종별 종목 레이아웃 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sector_layout (
            id INTEGER PRIMARY KEY,
            date TEXT,
            kind TEXT,
            val TEXT
        )
    ''')
    
    # 3. 5일 평균 거래대금 캐시 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS avg_amt_cache (
            code TEXT PRIMARY KEY,
            date TEXT,
            amt_array TEXT
        )
    ''')
    
    # 4. 시장 구분 맵 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_map (
            code TEXT PRIMARY KEY,
            date TEXT,
            market TEXT,
            is_nxt INTEGER
        )
    ''')
    
    # 5. 종목명 캐시 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_names (
            code TEXT PRIMARY KEY,
            date TEXT,
            name TEXT
        )
    ''')
    
    # 6. 범용 Key-Value 스토어 (진행상황, 정산상태, 설정 등 JSON 덤프용)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kv_store (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    _log.info("SQLite 캐시 테이블 초기화 완료.")

def get_kv(key: str) -> dict | None:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row["value"])
    except Exception as e:
        _log.warning("[kv_store] 로드 실패 (%s): %s", key, e)
    return None

def set_kv(key: str, data: dict) -> None:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", 
                       (key, json.dumps(data, ensure_ascii=False)))
        conn.commit()
        conn.close()
    except Exception as e:
        _log.warning("[kv_store] 저장 실패 (%s): %s", key, e)

def delete_kv(keys: list[str]) -> None:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM kv_store WHERE key IN ({','.join(['?']*len(keys))})", keys)
        conn.commit()
        conn.close()
    except Exception as e:
        _log.warning("[kv_store] 삭제 실패: %s", e)


def create_completed_snapshot_table():
    """completed_snapshot 테이블 생성 (읽기 전용 스냅샷)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS completed_snapshot (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sector TEXT,
            cur_price REAL,
            change REAL,
            change_rate REAL,
            strength TEXT,
            trade_amount REAL,
            avg_5d_trade_amount REAL,
            high_5d_price REAL,
            date TEXT
        )
    ''')
    
    # 인덱스 생성
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector ON completed_snapshot(sector)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON completed_snapshot(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector_date ON completed_snapshot(sector, date)')
    
    conn.commit()
    conn.close()
    _log.info("completed_snapshot 테이블 초기화 완료.")


def load_completed_snapshot() -> list[tuple[str, dict]] | None:
    """completed_snapshot 테이블에서 완성된 스냅샷 로드"""
    try:
        from backend.app.core.trading_calendar import current_trading_date_str
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 오늘 날짜의 스냅샷만 조회
        date_str = current_trading_date_str()
        cursor.execute("""
            SELECT code, name, sector, cur_price, change, change_rate, 
                   strength, trade_amount, avg_5d_trade_amount, high_5d_price
            FROM completed_snapshot
            WHERE date = ?
        """, (date_str,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            _log.warning("[completed_snapshot] 오늘 날짜의 스냅샷이 없습니다 (date=%s)", date_str)
            return None
        
        result = []
        for row in rows:
            detail = {
                "name": row["name"],
                "sector": row["sector"],
                "cur_price": row["cur_price"],
                "change": row["change"],
                "change_rate": row["change_rate"],
                "strength": row["strength"],
                "trade_amount": row["trade_amount"],
                "avg_5d_trade_amount": row["avg_5d_trade_amount"],
                "high_5d_price": row["high_5d_price"],
            }
            result.append((row["code"], detail))
        
        _log.info("[completed_snapshot] 로드 완료 -- %d종목 (date=%s)", len(result), date_str)
        return result
        
    except Exception as e:
        _log.warning("[completed_snapshot] 로드 실패: %s", e)
        return None


