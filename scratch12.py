import asyncio
from backend.app.services.engine_sector import get_all_sector_stocks
import backend.app.services.engine_state as state

async def main():
    state._pending_stock_details["000500"] = {"cur_price": "1000", "rate": "1.0", "change": "10"}
    stocks = await get_all_sector_stocks()
    gita = [s for s in stocks if s["code"] == "000500"]
    if gita:
        print(f"000500 name: {gita[0]['name']}")

asyncio.run(main())
