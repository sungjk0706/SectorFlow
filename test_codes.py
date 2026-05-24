import sqlite3
import json

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
cursor = conn.cursor()
cursor.execute("SELECT value FROM kv_store WHERE key = 'sector_layout'")
row = cursor.fetchone()
if row:
    val = row[0]
    data = json.loads(val)
    print("layout length:", len(data))
    
    codes = {
        _format_kiwoom_reg_stk_cd(v)
        for t, v in data
        if t == "code" and v
    }
    print("codes count:", len(codes))
    print("Sample codes:", list(codes)[:5])
else:
    print("No sector_layout in DB")
