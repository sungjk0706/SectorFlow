import asyncio
from backend.app.db.database import get_db_connection

async def main():
    conn = await get_db_connection()
    cursor = await conn.execute("SELECT code, data FROM master_stocks_table LIMIT 1")
    row = await cursor.fetchone()
    print(row)

asyncio.run(main())
