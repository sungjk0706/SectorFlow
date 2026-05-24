import asyncio
from backend.app.core.kiwoom_rest import KiwoomRestAPI
from backend.app.core.kiwoom_sector_rest import fetch_ka10081_daily_and_5d_data
from backend.app.db.crud import get_ls_settings

async def main():
    ls = get_ls_settings()
    api = KiwoomRestAPI(ls.get("app_key", ""), ls.get("app_secret", ""))
    await api.connect()
    # 삼성전자 (005930)
    data = fetch_ka10081_daily_and_5d_data(api, "005930", "20260526")
    print(data)

asyncio.run(main())
