import sqlite3

conn = sqlite3.connect("backend/data/stocks.db")
cursor = conn.cursor()

cursor.execute("""
    SELECT code, name, avg_5d_trade_amount
    FROM master_stocks_table
    WHERE avg_5d_trade_amount > 0
    ORDER BY avg_5d_trade_amount DESC
    LIMIT 20
""")

rows = cursor.fetchall()
for row in rows:
    print(row)

conn.close()
