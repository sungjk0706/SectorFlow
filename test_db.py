import sqlite3
import pprint

def _format_kiwoom_reg_stk_cd(stk_cd: str) -> str:
    s = str(stk_cd or "").strip().upper().lstrip("A")
    for suffix in ("_AL", "_NX"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s

conn = sqlite3.connect("backend/data/stocks.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT * FROM stocks LIMIT 5")
rows = cursor.fetchall()
_db_stocks = [dict(row) for row in rows]

_avg_map = {}
for row in _db_stocks:
    cd = _format_kiwoom_reg_stk_cd(row["code"])
    _avg_map[cd] = int(row.get("avg_5d_trade_amount") or 0)

print(f"Loaded {_avg_map}")
