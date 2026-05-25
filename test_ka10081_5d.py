#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ka10081 5일 데이터 테스트"""
import asyncio
import sys
sys.path.insert(0, '/Users/sungjk0706/Desktop/SectorFlow')

from backend.app.core.broker_factory import get_router
from backend.app.core.settings_file import load_settings_async

async def test():
    settings = await load_settings_async()
    router = get_router(settings)
    
    # API 직접 호출 (토큰은 내부에서 자동으로 처리됨)
    sector_provider = router.sector
    
    codes = ["005930", "000660"]
    
    for code in codes:
        print(f"\n===== {code} =====")
        # ka10081로 5일봉 데이터 조회
        from backend.app.core.kiwoom_sector_rest import fetch_ka10081_daily_5d_data
        result = fetch_ka10081_daily_5d_data(sector_provider._rest_api, code, "20260525")
        if result:
            print(f"highs_5d: {result.get('highs_5d_array')}")
            print(f"amts_5d: {result.get('amts_5d_array')}")
            print(f"high_price_5d: {result.get('high_price_5d')}")
            print(f"avg_amt_5d: {result.get('avg_amt_5d')}")
        else:
            print("조회 실패")

if __name__ == "__main__":
    asyncio.run(test())
