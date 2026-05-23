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

def create_sectors_table():
    """sectors 테이블 생성"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sectors (
            name TEXT PRIMARY KEY
        )
    """)
    
    conn.commit()
    conn.close()

def create_system_settings_table():
    """system_settings 테이블 생성"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

