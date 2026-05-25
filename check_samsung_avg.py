import sqlite3

conn = sqlite3.connect("backend/data/stocks.db")
cursor = conn.cursor()

cursor.execute("""
    SELECT code, name, avg_5d_trade_amount
    FROM master_stocks_table
    WHERE code = '005930'
""")

row = cursor.fetchone()
print(row)

conn.close()
