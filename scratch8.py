import asyncio
from backend.app.services.engine_snapshot import build_initial_snapshot

async def main():
    import backend.app.services.engine_state as state
    res = await build_initial_snapshot()
    # Let's test get_all_sector_stocks!
    from backend.app.services.engine_sector import get_all_sector_stocks
    stocks = await get_all_sector_stocks()
    gita = [s for s in stocks if s["sector"] == "기타"]
    print(f"Total get_all_sector_stocks: {len(stocks)}")
    if len(stocks) > 0:
        print(f"First gita: {gita[0] if gita else None}")

asyncio.run(main())
