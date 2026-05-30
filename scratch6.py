import asyncio
from backend.app.services.engine_sector import get_all_sector_stocks_from_cache

async def main():
    stocks = await get_all_sector_stocks_from_cache()
    gita = [s for s in stocks if s["sector"] == "기타" and s["name"] == s["code"]]
    print(f"Total '기타' stocks with name == code: {len(gita)}")
    for s in gita[:5]:
        print(s)

asyncio.run(main())
