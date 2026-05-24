import sys

class ModuleMock:
    def __init__(self):
        self.my_list = []
        
    def read_list(self):
        return len(self.my_list)

m = ModuleMock()
sys.modules['m'] = m

m.my_list = []  # rebind
m.my_list[:] = [1, 2, 3]  # mutate
print("Length inside module:", m.read_list())
