from backend.app.db.db_writer import execute_db_write, DBWriteOperation

async def batch_update_avg_5d(avg_map: dict) -> int:
    """avg_5d_trade_amount만 일괄 업데이트 (복구 데이터 DB 반영용)."""
    if not avg_map:
        return 0
    
    query = "UPDATE master_stocks_table SET avg_5d_trade_amount = ? WHERE code = ?"
    params = [(int(v), k) for k, v in avg_map.items()]
    
    op = DBWriteOperation(
        table="master_stocks_table",
        operation="UPDATE",
        data={},
        query=query,
        params=params,
    )
    
    await execute_db_write(op, wait=True)
    return len(params)
