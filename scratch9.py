import asyncio
from backend.app.services.engine_snapshot import build_initial_snapshot
from backend.app.services.engine_sector import get_all_sector_stocks
import backend.app.services.engine_state as state

async def main():
    # Simulate a quote arriving
    state._pending_stock_details["000500"] = {"cur_price": "1000", "rate": "1.0", "change": "10"}
    
    stocks = await get_all_sector_stocks()
    gita = [s for s in stocks if s["code"] == "000500"]
    print(f"Total get_all_sector_stocks: {len(stocks)}")
    if len(stocks) > 0:
        print(f"000500 entry: {gita[0] if gita else None}")

asyncio.run(main())
