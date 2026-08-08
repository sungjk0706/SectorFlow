#!/usr/bin/env bash
# UserPromptSubmit 훅 — 사전조사 게이트 (리마인드 주입)
# 매 사용자 메시지마다 .devin/state/investigation.lock 존재 여부 확인.
# 파일이 없으면 "코드 수정 전 사전조사 필요" 리마인드를 컨텍스트에 주입.
# 파일이 있으면 (이번 세션에서 조사 완료) 조용히 통과.
# 근거: engineering-playbook UserPromptSubmit 가이드 — 매 턴마다 컨텍스트 주입 패턴.
# 이 훅은 차단하지 않음 — 실제 차단은 PreToolUse 훅(investigation-gate-edit.sh)이 담당.

set -u

cd "$(dirname "$0")/../.." 2>/dev/null || exit 0

LOCK_FILE=".devin/state/investigation.lock"

# investigation.lock이 있으면 이번 세션에서 조사 완료 — 주입 없음
if [ -f "$LOCK_FILE" ]; then
    exit 0
fi

# 조사 완료 표시가 없으면 리마인드 주입
# 단순 질문·보고 요청에는 노이즈가 될 수 있으므로 1줄로 최소화
CONTEXT="== [사전조사 게이트] 이번 세션에서 사전조사 완료 표시가 없습니다. =="
CONTEXT="${CONTEXT}\n코드 수정 작업인 경우: 먼저 읽기 전용으로 관련 코드를 조사한 후, "
CONTEXT="${CONTEXT}\".devin/state/investigation.lock\" 파일을 생성(빈 파일)하여 조사 완료를 표시하세요."
CONTEXT="${CONTEXT}\n조사 없이 코드 수정 도구를 호출하면 자동으로 차단됩니다."
CONTEXT="${CONTEXT}\n단순 질문·보고·조사만 하는 작업은 이 리마인드를 무시해도 됩니다."

# JSON 출력 (additionalContext 주입)
python3 - "$CONTEXT" <<'PY'
import json, sys
ctx = sys.argv[1] if len(sys.argv) > 1 else ""
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ctx
    }
}))
PY
