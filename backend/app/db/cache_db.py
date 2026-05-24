import sqlite3
import json
import logging
from backend.app.db.database import get_db_connection

_log = logging.getLogger(__name__)

def init_cache_tables():
    """캐시용 테이블들을 생성합니다."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 확정 시세 스냅샷 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS snapshot_cache (
            code TEXT PRIMARY KEY,
            date TEXT,
            detail TEXT
        )
    ''')
    
    # 2. 업종별 종목 레이아웃 테이블
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


