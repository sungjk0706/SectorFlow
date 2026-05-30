import asyncio
from backend.app.services.engine_sector import get_all_sector_stocks

async def main():
    stocks = await get_all_sector_stocks()
    print(f"Total: {len(stocks)}")

asyncio.run(main())
