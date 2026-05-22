import asyncio
from backend.app.core.settings_store import after_settings_persisted

async def test():
    try:
        await after_settings_persisted("admin", {"sector_min_trade_amt"})
        print("Success async")
    except Exception as e:
        print(f"Exception async: {e}")

asyncio.run(test())
