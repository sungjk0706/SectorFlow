import asyncio
from backend.app.core.sector_stock_cache import load_layout_cache
import logging
logging.basicConfig(level=logging.DEBUG)

layout = load_layout_cache()
print("Layout:", layout)
