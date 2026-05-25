from backend.app.db.database import get_db_connection

def insert_stock(code, name, sector, cur_price, sign, change, change_rate, prev_close, trade_amount, today_high_price, avg_5d_trade_amount, high_5d_price, strength):
    """주식 정보를 DB에 삽입"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO stocks 
        (code, name, sector, cur_price, sign, change, change_rate, prev_close, trade_amount, today_high_price, avg_5d_trade_amount, high_5d_price, strength)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (code, name, sector, cur_price, sign, change, change_rate, prev_close, trade_amount, today_high_price, avg_5d_trade_amount, high_5d_price, strength))
    
    conn.commit()
    conn.close()

# get_all_stocks() 함수 제거 - completed_snapshot으로 대체
# batch_insert_stocks() 함수 제거 - stocks 테이블 삭제로 더 이상 사용하지 않음

def batch_update_avg_5d(avg_map: dict) -> int:
    """avg_5d_trade_amount만 일괄 업데이트 (복구 데이터 DB 반영용)."""
    if not avg_map:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.executemany(
            "UPDATE master_stocks_table SET avg_5d_trade_amount = ? WHERE code = ?",
            [(float(v), k) for k, v in avg_map.items()],
        )
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
