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

def get_all_stocks():
    """전체 주식 정보 조회"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT code, name, sector, cur_price, sign, change, change_rate, prev_close, trade_amount, today_high_price, avg_5d_trade_amount, high_5d_price, strength 
            FROM stocks
        """)
        rows = cursor.fetchall()
    except Exception as e:
        import logging
        logging.getLogger("engine").warning(f"DB 읽기 실패 (테이블이 없거나 비어있음): {e}")
        rows = []
    finally:
        conn.close()
    
    return [dict(row) for row in rows]

def batch_update_avg_5d(avg_map: dict) -> int:
    """avg_5d_trade_amount만 일괄 업데이트 (복구 데이터 DB 반영용)."""
    if not avg_map:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.executemany(
            "UPDATE stocks SET avg_5d_trade_amount = ? WHERE code = ?",
            [(float(v), k) for k, v in avg_map.items()],
        )
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def batch_insert_stocks(stocks_data):
    """대량 주식 정보를 단일 트랜잭션으로 고속 저장
    
    Args:
        stocks_data: [
            {
                "code": "005930",
                "name": "삼성전자",
                ...
            },
            ...
        ]
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        insert_query = """
            INSERT OR REPLACE INTO stocks 
            (code, name, sector, cur_price, sign, change, change_rate, prev_close, trade_amount, today_high_price, avg_5d_trade_amount, high_5d_price, strength)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        insert_values = [
            (
                stock["code"],
                stock["name"],
                stock["sector"],
                stock["cur_price"],
                stock["sign"],
                stock["change"],
                stock["change_rate"],
                stock["prev_close"],
                stock["trade_amount"],
                stock["today_high_price"],
                stock["avg_5d_trade_amount"],
                stock["high_5d_price"],
                stock["strength"]
            )
            for stock in stocks_data
        ]
        
        cursor.executemany(insert_query, insert_values)
        conn.commit()
        return len(insert_values)
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
