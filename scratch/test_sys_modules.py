import sys
import importlib
from importlib.machinery import ModuleSpec

ALIASES = {
    "backend.app.services.engine_service": "app.services.engine_service",
}

class AliasLoader:
    def __init__(self, module):
        self.module = module
    def create_module(self, spec):
        print(f"create_module called, returning {self.module}")
        return self.module
    def exec_module(self, module):
        print("exec_module called")
        pass

class DuplicateNamespaceResolver:
    def find_spec(self, fullname, path, target=None):
        print(f"find_spec: {fullname}")
        if fullname in ALIASES:
            alias_name = ALIASES[fullname]
            try:
                module = importlib.import_module(alias_name)
                print(f"  Mapping {fullname} -> {alias_name} (module={module})")
                sys.modules[fullname] = module
                spec = ModuleSpec(fullname, AliasLoader(module))
                return spec
            except Exception as e:
                print(f"  Error: {e}")
                return None
        return None

sys.meta_path.insert(0, DuplicateNamespaceResolver())

sys.path.insert(0, "/Users/sungjk0706/Desktop/SectorFlow")
sys.path.insert(0, "/Users/sungjk0706/Desktop/SectorFlow/backend")

import app.services.engine_service as es1
import backend.app.services.engine_service as es2

print("es1 is es2:", es1 is es2)
print("es1:", es1)
print("es2:", es2)
print("sys.modules[app.services.engine_service]:", sys.modules.get("app.services.engine_service"))
print("sys.modules[backend.app.services.engine_service]:", sys.modules.get("backend.app.services.engine_service"))
