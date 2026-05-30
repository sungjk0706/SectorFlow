import re

files_to_fix = [
    "backend/app/core/kiwoom_providers.py",
    "backend/app/core/kiwoom_broker.py",
    "backend/app/core/kiwoom_connector.py"
]

def fix_file(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # We need to replace the old block with a unified block.
    # In kiwoom_connector.py, it's:
    # app_key = (settings.get("kiwoom_app_key") or "").strip()
    # app_secret = (settings.get("kiwoom_app_secret") or "").strip()
    
    # In providers and broker, it might have the `is_test_mode` block I just added.
    
    # Let's just use regex to replace all variants of app_key / app_secret extraction.
    
    # For kiwoom_connector.py:
    content = re.sub(
        r'app_key\s*=\s*\(settings\.get\("kiwoom_app_key"\)\s*or\s*""\)\.strip\(\)\n\s*app_secret\s*=\s*\(settings\.get\("kiwoom_app_secret"\)\s*or\s*""\)\.strip\(\)',
        'app_key = (settings.get("kiwoom_app_key_real") or settings.get("kiwoom_app_key") or "").strip()\n    app_secret = (settings.get("kiwoom_app_secret_real") or settings.get("kiwoom_app_secret") or "").strip()',
        content
    )
    
    # For providers and broker (the block I added):
    block_to_replace = r"""from backend\.app\.core\.trade_mode import is_test_mode
\s*_is_test = is_test_mode\(settings\)
\s*if _is_test:
\s*app_key = \(settings\.get\("kiwoom_app_key_test"\) or settings\.get\("kiwoom_app_key"\) or ""\)\.strip\(\)
\s*app_secret = \(settings\.get\("kiwoom_app_secret_test"\) or settings\.get\("kiwoom_app_secret"\) or ""\)\.strip\(\)
\s*else:
\s*app_key = \(settings\.get\("kiwoom_app_key_real"\) or settings\.get\("kiwoom_app_key"\) or ""\)\.strip\(\)
\s*app_secret = \(settings\.get\("kiwoom_app_secret_real"\) or settings\.get\("kiwoom_app_secret"\) or ""\)\.strip\(\)"""

    new_block = """app_key = (settings.get("kiwoom_app_key_real") or settings.get("kiwoom_app_key") or "").strip()
        app_secret = (settings.get("kiwoom_app_secret_real") or settings.get("kiwoom_app_secret") or "").strip()"""

    content = re.sub(block_to_replace, new_block, content)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Unified keys in {path}")

for f in files_to_fix:
    fix_file(f)

