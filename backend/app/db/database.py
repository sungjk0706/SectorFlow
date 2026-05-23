import sqlite3
import os

def get_db_connection():
    """SQLite 데이터베이스 연결 객체 반환"""
    db_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if "PYTEST_CURRENT_TEST" in os.environ:
        db_path = os.path.join(db_dir, "data", "stocks_test.db")
    else:
        db_path = os.path.join(db_dir, "data", "stocks.db")
    
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
