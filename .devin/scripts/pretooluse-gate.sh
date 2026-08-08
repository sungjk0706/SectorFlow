#!/usr/bin/env bash
# PreToolUse 훅 — 코드 수정 도구(edit/write) 호출 시 게이트 검사
# 2가지 게이트 수행:
#   1. 사전조사 게이트 — .devin/state/investigation.lock 없으면 차단
#   2. 승인 게이트 — 위험 작업 4종(매매·실전모드·DB·API키) 파일에 대해
#      .devin/state/approval.lock 없으면 차단
# 근거: claude-code-guards PreToolUse 게이트 패턴, Anthropic 공식 훅 문서.
# 읽기 도구(read/grep/glob)는 이 훅의 matcher(edit|write)에 걸리지 않으므로
# 사전조사 단계의 읽기 작업은 차단되지 않음.

set -u

cd "$(dirname "$0")/../.." 2>/dev/null || exit 0

# stdin에서 JSON 읽기 (훅 호출 시), 수동 실행 시 빈 입력
INPUT=""
if [ ! -t 0 ]; then
    while IFS= read -r -t 1 LINE 2>/dev/null; do
        INPUT="${INPUT}${LINE}"
    done
fi

# python3가 없으면 통과 (훅 실패가 작업을 막지 않도록)
if ! command -v python3 >/dev/null 2>&1; then
    exit 0
fi

LOCK_DIR=".devin/state"
INVESTIGATION_LOCK="${LOCK_DIR}/investigation.lock"
APPROVAL_LOCK="${LOCK_DIR}/approval.lock"

# JSON 파싱 및 게이트 검사를 python으로 수행
python3 - "$INPUT" "$INVESTIGATION_LOCK" "$APPROVAL_LOCK" <<'PY'
import json, sys, os, re

raw = sys.argv[1] if len(sys.argv) > 1 else ""
investigation_lock = sys.argv[2] if len(sys.argv) > 2 else ""
approval_lock = sys.argv[3] if len(sys.argv) > 3 else ""

# 입력이 비어있으면 통과 (수동 실행)
if not raw.strip():
    sys.exit(0)

try:
    data = json.loads(raw)
except json.JSONDecodeError:
    sys.exit(0)

tool_name = data.get("tool_name", "")
tool_input = data.get("tool_input", {})
file_path = tool_input.get("file_path", "")

# edit/write 도구만 검사 (다른 도구는 통과)
if tool_name not in ("edit", "write"):
    sys.exit(0)

# file_path가 없으면 통과 (이상 케이스)
if not file_path:
    sys.exit(0)

# ─── 게이트 1: 사전조사 게이트 ───
# investigation.lock이 없으면 코드 수정 차단
if not os.path.exists(investigation_lock):
    reason = (
        "사전조사 게이트: 이번 세션에서 사전조사 완료 표시가 없습니다. "
        "코드 수정 전 먼저 읽기 전용으로 관련 코드를 조사한 후, "
        "'.devin/state/investigation.lock' 파일을 생성(빈 파일)하여 "
        "조사 완료를 표시하세요. 조사 없는 코드 수정은 차단됩니다."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)

# ─── 게이트 2: 승인 게이트 (위험 작업 4종) ───
# 위험 파일 패턴 — 매매 로직, 실전 모드 전환, DB 스키마, API 키 관련
# 사용자가 "승인"이라는 단어로 명시적 승인 후 approval.lock 생성 시에만 통과.
DANGER_PATTERNS = [
    # 매매 로직 (안전 규칙 3 — 실전 모드 전환 3조건 승인)
    r"backend/app/services/trading\.py$",
    r"backend/app/services/engine_lifecycle\.py$",
    r"backend/app/services/engine_loop\.py$",
    r"backend/app/services/engine_order_loop\.py$",
    r"backend/app/services/order_interval\.py$",
    r"backend/app/services/settlement_engine\.py$",
    r"backend/app/services/auto_trading_effective\.py$",
    r"backend/app/core/broker.*\.py$",
    r"backend/app/core/broker_connector\.py$",
    # 실전 모드 전환 (프론트엔드 — handleTradeMode 함수가 있는 파일)
    r"frontend/src/pages/general-settings-account-tab\.ts$",
    # DB 스키마 (안전 규칙 1, 2)
    r"backend/app/db/.*\.py$",
    r"backend/app/core/settings_store\.py$",
    r"backend/app/core/settings_defaults\.py$",
    # API 키 (안전 규칙 4)
    r"backend/app/core/.*key.*\.py$",
    r"backend/app/core/.*token.*\.py$",
    r"backend/app/core/.*auth.*\.py$",
]

is_dangerous = False
for pattern in DANGER_PATTERNS:
    if re.search(pattern, file_path, re.IGNORECASE):
        is_dangerous = True
        break

if is_dangerous and not os.path.exists(approval_lock):
    reason = (
        f"승인 게이트: 이 파일은 위험 작업 대상입니다 (매매 로직/실전 모드/DB/API 키). "
        "사용자가 '승인'이라는 단어로 명시적 승인 후, "
        "'.devin/state/approval.lock' 파일을 생성해야 수정할 수 있습니다. "
        "승인 없이 위험 코드를 수정할 수 없습니다."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)

# 모든 게이트 통과
sys.exit(0)
PY
