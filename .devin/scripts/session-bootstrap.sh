#!/usr/bin/env bash
# SessionStart 훅 — 매 세션 시작 시 AGENTS.md "빠른 룰 인덱스" + HANDOVER.md "다음 세션 첫 동작" 블록을
# additionalContext로 주입하여 AI가 룰 위치를 즉시 파악하도록 강제.
# 컨텍스트 소모 최소화: AGENTS.md 상단 ~40줄 + HANDOVER.md 상단 ~12줄만 발췌.
# 종료 코드 0 유지 (훅 실패가 세션 시작을 방해하지 않도록).

set -u

cd "$(dirname "$0")/../.." 2>/dev/null || exit 0

# python3가 없으면 no-op (훅 실패가 세션 시작을 블로킹하지 않도록).
if ! command -v python3 >/dev/null 2>&1; then
  exit 0
fi

AGENTS_SLICE=""
HANDOVER_SLICE=""
[ -f "AGENTS.md" ] && AGENTS_SLICE=$(sed -n '1,40p' AGENTS.md 2>/dev/null)
[ -f "HANDOVER.md" ] && HANDOVER_SLICE=$(sed -n '1,12p' HANDOVER.md 2>/dev/null)

# 진행 중 태스크 파일 탐지 — HANDOVER.md가 가리키는 경로 우선, 없으면 docs/태스크_*.md 최신 1개.
TASK_FILE=""
TASK_SLICE=""
if [ -f "HANDOVER.md" ]; then
  TASK_FILE=$(grep -oE 'docs/[^` ]+\.md' HANDOVER.md 2>/dev/null | grep -E '태스크' | head -1)
fi
if [ -z "$TASK_FILE" ] || [ ! -f "$TASK_FILE" ]; then
  TASK_FILE=$(ls -t docs/태스크_*.md 2>/dev/null | head -1)
fi
if [ -n "$TASK_FILE" ] && [ -f "$TASK_FILE" ]; then
  TASK_SLICE=$(sed -n '1,200p' "$TASK_FILE" 2>/dev/null)
fi

export AGENTS_SLICE HANDOVER_SLICE TASK_FILE TASK_SLICE

python3 - <<'PY'
import json, os, re

agents = os.environ.get("AGENTS_SLICE", "")
handover = os.environ.get("HANDOVER_SLICE", "")
task_slice = os.environ.get("TASK_SLICE", "")
task_file = os.environ.get("TASK_FILE", "")

# 진행 중 태스크 파일의 "다음 세션 진행 단계" 발췌.
# 메타데이터의 "다음 세션 진행 단계" 줄에서 단계명(예: 1단계) 추출 후
# 본문의 "### {단계명}:" 섹션을 다음 "## "/"### " 전까지 발췌.
task_excerpt = ""
if task_slice:
    lines = task_slice.splitlines()
    next_step_line = ""
    stage_name = ""
    for ln in lines:
        if "다음 세션 진행 단계" in ln:
            next_step_line = ln.lstrip("- *>").strip().replace("**", "")
            m = re.search(r"(\d+단계)", ln)
            if m:
                stage_name = m.group(1)
            break
    stage_section = ""
    if stage_name:
        capturing = False
        for ln in lines:
            if ln.startswith(f"### {stage_name}"):
                capturing = True
                stage_section += ln + "\n"
                continue
            if capturing:
                if ln.startswith("### ") or ln.startswith("## "):
                    break
                stage_section += ln + "\n"
    if next_step_line or stage_section:
        task_excerpt = f"**작업 지시서**: {task_file}\n"
        if next_step_line:
            task_excerpt += next_step_line + "\n"
        if stage_section:
            task_excerpt += "\n**해당 단계 본문**:\n" + stage_section.rstrip()

context = "== [SessionStart 자동 주입] 룰 참조 가이드 ==\n\n"
context += "### ⚠️ 최우선 강제 — 모든 응답은 일반 사용자 용어로 (규칙 0-8 1항 + 규칙 5)\n"
context += "사용자는 코딩을 모르는 일반인. 모든 응답은 일반 사용자 용어로 작성.\n"
context += "금지 (두 종류 모두 사용자 응답 본문 노출 금지):\n"
context += "  (a) 코드 기술 참조: 파일 경로·줄번호·함수명·변수명·SQL·코드 인용 태그(<ref_file>/<ref_snippet>)·스택 트레이스·명령어·커밋 해시·내부 상태값\n"
context += "  (b) 규칙·원칙 메타 용어: 규칙 번호(0-8 등)·원칙 번호(P10 등)·메타 명칭(단일 진실 소스·검증 게이트·역할 원칙·다단계 워크플로우 등). 원칙 언급 시 번호 없이 '원칙에 부합합니다' 정도로만.\n"
context += "응답 전송 직전 반드시 점검: 기술 참조가 있으면 일반 용어로 다시 작성 후 전송 (규칙 5 강제).\n"
context += "예: 'market_close_pipeline.py:844에서 DELETE 실행' (X) → '매매 대상 종목만 남기고 나머지는 자동 정리' (O)\n\n"
context += "### ⚠️ 작업 전환 시 재점검 (강제 — 규칙 0 동급)\n"
context += "세션 중 작업 유형이 바뀔 때마다(조사→보고→핸드오버 작성→코드 수정 등) 전환 직전에 AGENTS.md '빠른 룰 인덱스' 표에서 해당 작업 유형의 룰 위치를 재확인 후 진행.\n"
context += "세션 시작 1회 점검으로는 부족 — 작업이 바뀌면 적용 규칙도 바뀜. '이미 알고 있다'는 가정 금지.\n\n"
context += "### AGENTS.md 상단 (빠른 룰 인덱스 + 문서 역할 원칙 5항목)\n"
context += agents
context += "\n\n### HANDOVER.md 상단 (다음 세션 첫 동작 + 최근 세션 개요)\n"
context += handover
context += "\n새 작업창에서는 설계서·태스크를 다시 읽고, 사용자가 시작을 지시하기 전에는 진행하지 않을 것.\n"
if task_excerpt:
    context += "\n\n### 진행 중 작업 지시서 — 다음 세션 진행 단계\n"
    context += task_excerpt
    context += "\n\n== 작업 지시서 발췌 끝. 위 단계는 사용자 진행 지시가 있을 때만 시작. ==\n"
context += "\n\n== 자동 주입 끝. 위 룰 위치를 파악한 후 작업 유형에 맞는 AGENTS.md 섹션을 재독할 것. ==\n"
context += "⚠️ 위 '최우선 강제' 문구를 무시하고 기술 용어를 사용자 응답에 노출하면 규칙 0-8 1항 + 규칙 5 위반."

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context
    }
}))
PY
