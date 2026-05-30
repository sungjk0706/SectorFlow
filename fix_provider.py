import os
import re

path = "backend/app/services/market_close_pipeline.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the block
old_block1 = """from backend.app.core.kiwoom_broker import KiwoomBroker
        _sector = KiwoomBroker(_settings).get_provider('sector')"""
new_block1 = """from backend.app.core.kiwoom_providers import KiwoomSectorProvider
        _sector = KiwoomSectorProvider(_settings)"""
content = content.replace(old_block1, new_block1)

old_block2 = """from backend.app.core.kiwoom_broker import KiwoomBroker
    _sector = KiwoomBroker(_settings).get_provider('sector')"""
new_block2 = """from backend.app.core.kiwoom_providers import KiwoomSectorProvider
    _sector = KiwoomSectorProvider(_settings)"""
content = content.replace(old_block2, new_block2)


with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Fixed get_provider in {path}")
