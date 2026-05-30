def fix():
    with open("backend/app/services/market_close_pipeline.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    for i in range(len(lines)):
        if "from backend.app.core.engine_settings import get_engine_settings" in lines[i]:
            # if previous line is indented more, fix it
            if "사용자 설정의 ws_subscribe_start 시간 확인" in lines[i-1]:
                lines[i] = "        from backend.app.core.engine_settings import get_engine_settings\n"
                lines[i+1] = "        _settings = await get_engine_settings()\n"

    with open("backend/app/services/market_close_pipeline.py", "w", encoding="utf-8") as f:
        f.writelines(lines)
        
fix()
