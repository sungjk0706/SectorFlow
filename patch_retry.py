import re

file_path = "backend/app/services/engine_lifecycle.py"
with open(file_path, "r") as f:
    content = f.read()

content = content.replace(
    "_log(\"[경고] 토큰 발급 응답 실패 - 키 규격을 확인하십시오.\")",
    "_log(f\"[경고] 토큰 발급 응답 실패 - success={success}, token_info={es._rest_api._token_info}\")"
)

with open(file_path, "w") as f:
    f.write(content)
