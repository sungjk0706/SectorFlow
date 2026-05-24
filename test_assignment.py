import sys

# Create a mock module 'engine_service'
class EngineService:
    _sector_stock_layout: list[tuple[str, str]] = []

es = EngineService()
sys.modules['engine_service'] = es

_cached_layout = [("code", "005930"), ("title", "Samsung"), ("code", "000660")]

es._sector_stock_layout[:] = _cached_layout

def test_compute():
    # Simulate reading the module variable
    global _sector_stock_layout
    codes = [v for t, v in es._sector_stock_layout if t == "code"]
    print("Codes length:", len(codes))
    print("Codes:", codes)

test_compute()
