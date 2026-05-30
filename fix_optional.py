import os
import re

for root, dirs, files in os.walk("backend/app"):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if "Optional[" in content and "Optional" not in re.findall(r"^import\s+.*Optional.*|^from\s+.*import\s+.*Optional.*", content, re.MULTILINE):
                # Try to add Optional to existing typing import
                if re.search(r"^from typing import (.*)$", content, re.MULTILINE):
                    content = re.sub(r"^(from typing import .*)(?<!Optional)$", r"\1, Optional", content, 1, re.MULTILINE)
                else:
                    # Add import at the top after docstrings/first imports
                    content = "from typing import Optional\n" + content
                
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Fixed Optional import in {path}")
