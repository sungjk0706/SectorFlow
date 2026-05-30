import re

with open("backend/app/core/kiwoom.py", "r") as f:
    content = f.read()

if "from typing import Optional" not in content and "from typing import " not in content:
    content = content.replace("import asyncio", "import asyncio\nfrom typing import Optional", 1)
elif "from typing import" in content and "Optional" not in content:
    content = re.sub(r"(from typing import .*?)\n", r"\1, Optional\n", content, count=1)

with open("backend/app/core/kiwoom.py", "w") as f:
    f.write(content)

print("kiwoom.py patched")
