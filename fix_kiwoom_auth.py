import re

def fix_file(path, is_broker=False):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the block where app_key is assigned
    # app_key = (settings.get("kiwoom_app_key") or "").strip()
    # app_secret = (settings.get("kiwoom_app_secret") or "").strip()
    
    old_code = """app_key = (settings.get("kiwoom_app_key") or "").strip()
        app_secret = (settings.get("kiwoom_app_secret") or "").strip()"""
    
    if is_broker:
        old_code = """app_key    = (settings.get("kiwoom_app_key")    or "").strip()
        app_secret = (settings.get("kiwoom_app_secret") or "").strip()"""

    # We need to import is_test_mode
    import_str = "from backend.app.core.trade_mode import is_test_mode\n"
    if "is_test_mode" not in content:
        content = content.replace("import logging\n", "import logging\n" + import_str)
        # fallback if import logging is not there
        if "from backend.app.core.trade_mode import is_test_mode" not in content:
            content = content.replace("from typing import Callable, Optional\n", "from typing import Callable, Optional\n" + import_str)
            
    new_code = """from backend.app.core.trade_mode import is_test_mode
        _is_test = is_test_mode(settings)
        if _is_test:
            app_key = (settings.get("kiwoom_app_key_test") or settings.get("kiwoom_app_key") or "").strip()
            app_secret = (settings.get("kiwoom_app_secret_test") or settings.get("kiwoom_app_secret") or "").strip()
        else:
            app_key = (settings.get("kiwoom_app_key_real") or settings.get("kiwoom_app_key") or "").strip()
            app_secret = (settings.get("kiwoom_app_secret_real") or settings.get("kiwoom_app_secret") or "").strip()"""

    content = content.replace(old_code, new_code)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Fixed {path}")

fix_file("backend/app/core/kiwoom_providers.py")
fix_file("backend/app/core/kiwoom_broker.py", True)

