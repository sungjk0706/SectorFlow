import sqlite3

conn = sqlite3.connect("backend/data/stocks.db")
cursor = conn.cursor()

cursor.execute("""
    SELECT key, value
    FROM system_settings
    WHERE key = 'sector_min_trade_amt'
""")

row = cursor.fetchone()
print(row)

conn.close()
