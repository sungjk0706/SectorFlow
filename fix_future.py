import os
import re

for root, dirs, files in os.walk("backend/app"):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Find if from __future__ is present
            if "from __future__ import annotations" in content:
                # Remove it
                content = content.replace("from __future__ import annotations\n", "")
                content = content.replace("from __future__ import annotations", "")
                
                # Prepend it at the absolute beginning
                content = "from __future__ import annotations\n" + content.lstrip()
                
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Fixed __future__ in {path}")
