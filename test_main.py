import test_mod as es

es._sector_stock_layout = []
es._sector_stock_layout[:] = [1, 2, 3]

print("Len from module function:", es.get_len())
