import sys
import asyncio
from backend.app.core.kiwoom_rest import KiwoomRestAPI

async def main():
    api = KiwoomRestAPI(base_url="http://test", app_key="test_key_3", app_secret="test_secret_3")
    api._token_info = None
    success = await api._ensure_token()
    print(f"success: {success}")
    print(f"token_info: {api._token_info}")

asyncio.run(main())
