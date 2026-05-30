import asyncio
from backend.app.core.engine_settings import get_engine_settings

async def main():
    settings = await get_engine_settings()
    for k, v in settings.items():
        if 'key' in k or 'secret' in k or 'token' in k or 'acnt' in k or 'account' in k:
            print(f"{k}: {repr(v)}")

if __name__ == '__main__':
    asyncio.run(main())
