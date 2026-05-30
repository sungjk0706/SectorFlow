import asyncio
from backend.app.db.stock_tables import load_stock_names

async def main():
    names = await load_stock_names()
    codes_to_check = ["000500", "001230", "001380", "001560"]
    for code in codes_to_check:
        print(f"{code}: {names.get(code)}")

asyncio.run(main())
