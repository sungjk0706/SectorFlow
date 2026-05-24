import json
from pathlib import Path
from backend.app.core.sector_stock_cache import save_layout_cache
from backend.app.core.industry_map import save_eligible_stocks_cache

DATA_DIR = Path("backend/data")

def migrate():
    # 1. Layout
    layout_file = DATA_DIR / "sector_layout_cache.json"
    if layout_file.exists():
        try:
            with open(layout_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                layout_data = data.get("data", [])
                if layout_data:
                    # JSON layout is [["sector", "A"], ["code", "005930"], ...]
                    # save_layout_cache expects list[tuple[str, str]]
                    tuples = [(item[0], item[1]) for item in layout_data if len(item) == 2]
                    save_layout_cache(tuples)
                    print(f"Migrated {len(tuples)} layout items to SQLite.")
        except Exception as e:
            print(f"Failed to migrate layout: {e}")
            
    # 2. Eligible Stocks
    eligible_file = DATA_DIR / "eligible_stocks_cache.json"
    if eligible_file.exists():
        try:
            with open(eligible_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                eligible_data = data.get("data", {})
                if eligible_data:
                    save_eligible_stocks_cache(eligible_data)
                    print(f"Migrated {len(eligible_data)} eligible stocks to SQLite.")
        except Exception as e:
            print(f"Failed to migrate eligible stocks: {e}")

if __name__ == "__main__":
    migrate()
