from backend.app.db.database import get_db_connection

def create_stocks_table():
    """stocks 테이블 생성"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sector TEXT,
            cur_price REAL,
            sign TEXT,
            change REAL,
            change_rate REAL,
            prev_close REAL,
            trade_amount REAL,
            today_high_price REAL,
            avg_5d_trade_amount REAL,
            high_5d_price REAL,
            strength TEXT
        )
    """)
    
    conn.commit()
    conn.close()
