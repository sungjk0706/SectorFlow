import re

files_to_fix = [
    "backend/app/core/kiwoom_providers.py",
    "backend/app/core/kiwoom_broker.py",
    "backend/app/core/kiwoom_connector.py"
]

def fix_file(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Revert to original logic:
    block_to_replace = r"""app_key = \(settings\.get\("kiwoom_app_key_real"\) or settings\.get\("kiwoom_app_key"\) or ""\)\.strip\(\)
\s*app_secret = \(settings\.get\("kiwoom_app_secret_real"\) or settings\.get\("kiwoom_app_secret"\) or ""\)\.strip\(\)"""

    new_block = """app_key = (settings.get("kiwoom_app_key") or "").strip()
        app_secret = (settings.get("kiwoom_app_secret") or "").strip()"""

    content = re.sub(block_to_replace, new_block, content)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Reverted keys in {path}")

for f in files_to_fix:
    fix_file(f)

