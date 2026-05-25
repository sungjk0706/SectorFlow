from backend.app.db.database import get_db_connection

# stocks 테이블 삭제 - master_stocks_table로 통합

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

