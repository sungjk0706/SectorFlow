import asyncio
from backend.app.core.sector_stock_cache import load_stock_name_cache

async def main():
    names = await load_stock_name_cache()
    codes_to_check = ["000500", "001230", "001380", "001560"]
    for code in codes_to_check:
        print(f"{code}: {names.get(code)}")

asyncio.run(main())
