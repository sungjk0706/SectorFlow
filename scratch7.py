import asyncio
from backend.app.services.engine_state import _pending_stock_details

async def main():
    import backend.app.services.engine_state as state
    print(f"Total _pending_stock_details: {len(state._pending_stock_details)}")
    gita = [cd for cd, entry in state._pending_stock_details.items() if not entry.get("name")]
    print(f"Total stocks with no name: {len(gita)}")
    for cd in gita[:5]:
        print(f"cd: {cd}, entry: {state._pending_stock_details[cd]}")

asyncio.run(main())
