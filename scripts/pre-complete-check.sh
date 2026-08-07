#!/usr/bin/env bash
# SectorFlow pre-complete-check — 완료 보고 전 기계적 검증 (하네스 엔지니어링 강화)
# AGENTS.md "검증 게이트 원칙" + "작업 완료 시 점검 체크리스트" 1단계 구현
# 완료 보고(사용자에게 "다 됐다"고 알리기) 전 반드시 실행 — 실패 시 완료 보고 금지
# 사용법: bash scripts/pre-complete-check.sh [auto|backend|frontend|docs|all]
#   auto     — 세션 시작 스냅샷과 비교하여 이번 세션에서 새로 바뀐 파일만 보고
#              알맞은 모드를 자동 판단 (권장 — Stop 훅 기본값). 백엔드 수정 시
#              런타임 기동 검증까지 자동 진입. 이전 세션 잔재는 이번 세션 수정으로
#              잘못 인식되지 않음.
#   backend  — 백엔드 검증만 (수동 지정). 런타임 기동 검증을 위해 기존 백엔드
#              프로세스를 종료 후 새 코드로 기동 검증.
#   frontend — 프론트엔드 검증만 (수동 지정). 백엔드 프로세스를 건드리지 않음.
#   docs     — 문서 전용 세션 (코드 검증 전부 스킵). 백엔드 프로세스를 절대 건드리지 않음.
#   all      — 백엔드 린트/테스트 + 프론트엔드 검증 (수동 지정).
#              백엔드 프로세스를 건드리지 않음 — 런타임 기동 검증이 필요하면 backend 모드로 별도 실행.
# 핵심 원칙: 백엔드 프로세스 종료·재기동은 backend 모드에서만. 이전 세션 잔재가 작업 창에
# 남아 있어도, 이번 세션에서 백엔드를 수정하지 않았으면 백엔드 프로세스를 절대 종료하지 않는다.
# 설치 불필요 — 에이전트가 완료 전 직접 실행

set -uo pipefail

cd "$(git rev-parse --show-toplevel)"

TARGET="${1:-auto}"
FAILED=0

# ─── Stop 훅 무한 루프 방지 ───
# Stop 훅으로 등록 시 stdin으로 JSON 이벤트 데이터가 들어옴.
# stop_hook_active=true면 이미 차단 후 재작업 중이므로 추가 차단 금지 → 통과.
# 이 가드가 없으면 검증 실패 시 에이전트가 영원히 종료하지 못하는 루프 발생.
# stdin이 파이프(훅 호출)일 때만 이벤트 파싱 — 수동 실행(TTY) 시에는 무시.
# read -t 1 로 1초 타임아웃 적용하여 수동 실행 시 입력 대기로 멈추지 않음.
if [ ! -t 0 ]; then
    EVENT=""
    while IFS= read -r -t 1 LINE 2>/dev/null; do
        EVENT="${EVENT}${LINE}"
    done
    if echo "$EVENT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
        echo "[pre-complete] stop_hook_active=true — 이미 차단 후 재작업 중이므로 추가 차단 금지, 통과"
        exit 0
    fi
fi

echo "[pre-complete] SectorFlow 완료 전 기계적 검증 시작 (대상: $TARGET)"
echo "[pre-complete] ------------------------------------------------"

# ─── 백엔드 검증 ───
# 인자 $1 = 호출 모드 ("backend" | "all"). "backend"일 때만 런타임 기동 검증(프로세스 종료) 실행.
# "all" 모드(Stop 훅 자동 실행 포함)에서는 린트/테스트만 돌리고 백엔드 프로세스를 건드리지 않음.
run_backend() {
    local MODE="${1:-all}"
    if [ ! -f ".venv/bin/python" ]; then
        echo "[pre-complete] ❌ .venv 없음 — 백엔드 검증을 수행할 수 없음"
        FAILED=$((FAILED + 1))
        return 0
    fi

    echo "[pre-complete] [1/4] Ruff 린트 (금지 패턴 + dead code)..."
    if ! .venv/bin/ruff check backend/app/; then
        echo "[pre-complete] ❌ Ruff 실패 — 금지 패턴 또는 dead code 발견"
        echo "[pre-complete]    수정 방법: .venv/bin/ruff check backend/app/ --fix"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션2 '금지 패턴 5개' + ARCHITECTURE.md W1/W6/W8"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ Ruff 통과"
    fi

    echo "[pre-complete] [2/4] 백엔드 전체 테스트 (pytest)..."
    if ! .venv/bin/python -m pytest backend/tests -q 2>&1 | tail -5; then
        echo "[pre-complete] ❌ pytest 실패 — 기존 기능 회귀 또는 신규 테스트 실패"
        echo "[pre-complete]    수정 방법: 실패한 테스트 함수명으로 원인 추적 후 수정"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션3 규칙 0-1-2 '검증 자동화 루프'"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ pytest 통과"
    fi

    # 런타임 기동 검증(프로세스 종료 + 재기동)은 backend 모드에서만 실행.
    # all 모드(Stop 훅 자동 실행 포함)에서는 백엔드 프로세스를 건드리지 않음 —
    # 이전 세션 잔재가 작업 창에 남아 있어도 이번 세션에서 백엔드를 수정하지 않았으면 종료 금지.
    if [ "$MODE" != "backend" ]; then
        echo "[pre-complete] ℹ️ [3/4] 런타임 기동 검증 스킵 — ${MODE} 모드 (백엔드 프로세스 보호)"
        echo "[pre-complete] ℹ️ [4/4] 잔존 프로세스 정리 스킵 — ${MODE} 모드 (백엔드 프로세스 보호)"
        echo "[pre-complete]    주의: 런타임 기동 검증이 필요하면 backend 모드로 별도 실행."
        return 0
    fi

    echo "[pre-complete] [3/4] 런타임 기동 검증 (RuntimeWarning 에러 승격)..."
    echo "[pre-complete]    backend 모드 — 기존 백엔드 모두 종료 후 새 코드로 기동 검증"
    # 백엔드 수정 세션은 기존 백엔드(사용자가 켜둔 것 포함)를 모두 종료 —
    # 포트 충돌 방지 + 구버전 코드로 돌아가는 프로세스 배제 + 검증 확실성 (사용자 합의).
    ps aux | grep -E "python.*main\.py" | grep -v grep | awk '{print $2}' | while read pid; do
        kill "$pid" 2>/dev/null || true
    done
    sleep 1
    # 유니크 로그 파일 (PID+타임스탬프로 충돌 방지)
    # macOS에는 timeout 명령어가 없으므로 백그라운드 + sleep + kill 패턴 사용
    LOG_FILE="/tmp/sf_precomplete_runtime_$$_$(date +%s).log"
    .venv/bin/python -W error::RuntimeWarning main.py > "$LOG_FILE" 2>&1 &
    RT_PID=$!
    sleep 10
    if kill -0 $RT_PID 2>/dev/null; then
        kill $RT_PID 2>/dev/null || true
        wait $RT_PID 2>/dev/null || true
    fi
    # 에러/경고 OR 기동 실패(정상 기동 메시지 없음) 확인
    # 한글/영문 기동 메시지 모두 매칭 (이 프로젝트는 한글 로그 사용)
    if grep -qE "RuntimeWarning|Traceback|Error" "$LOG_FILE" || ! grep -qiE "engine.*start|uvicorn.*started|application.*start|api.*start|앱 시작|Uvicorn 실행|엔진 기동|엔진 준비|서버 프로세스 시작" "$LOG_FILE"; then
        echo "[pre-complete] ❌ 런타임 검증 실패 — RuntimeWarning/Traceback/Error 발생 또는 기동 실패"
        grep -E "RuntimeWarning|Traceback|Error" "$LOG_FILE" | head -5
        echo "[pre-complete]    수정 방법: await 누락 또는 비동기 누수 — 해당 함수에 await 추가"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 금지 패턴 4번째 + ARCHITECTURE.md W8"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ 런타임 기동 검증 통과"
    fi
    rm -f "$LOG_FILE"

    # 잔존 프로세스 확인 (0-1-3) — backend 모드는 검증용 백엔드만 정리
    REMAIN=$(ps aux | grep -E "python.*main\.py" | grep -v grep | wc -l | tr -d ' ')
    if [ "$REMAIN" -gt 0 ]; then
        echo "[pre-complete] ❌ 잔존 백엔드 프로세스 ${REMAIN}건 — 수동 종료 필요"
        ps aux | grep -E "python.*main\.py" | grep -v grep | awk '{print $2}' | while read pid; do
            kill "$pid" 2>/dev/null || true
        done
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션3 규칙 0-1-3 '잔존 프로세스 완전 종료'"
        FAILED=$((FAILED + 1))
    fi
}

# ─── auto 모드 — 이번 세션 변경 파일 기반 모드 자동 판단 ───
# 세션 시작 훅(session-bootstrap.sh)이 기록한 스냅샷과 현재 변경 파일을 비교하여
# "이번 세션에서 새로 바뀐 파일"만 추출. 이전 세션 잔재는 이번 세션 수정으로
# 잘못 인식되지 않음 (사용자가 켜둔 백엔드 프로세스 보호 — 핵심 안전장치).
#
# 판정:
#   - 백엔드 파일(backend/ 또는 main.py)이 새로 바뀌면 → backend 모드 (런타임 기동 검증 포함)
#   - 프론트엔드 파일(frontend/)만 새로 바뀌면 → frontend 모드
#   - 둘 다 → backend 런타임 검증 + frontend 검증 순차 실행
#   - 코드 변경 없음 → docs 모드 (코드 검증 스킵, 백엔드 프로세스 보호)
#
# 스냅샷이 없으면(이전 버전 호환·세션 시작 훅 미실행) 현재 변경 전체를 이번 세션
# 수정으로 간주하되 경고 출력 — 안전 측(검증 누락 방지).
run_auto() {
    local SNAPSHOT=".devin/state/session_changes_snapshot.txt"

    # 현재 변경 파일 수집: tracked(HEAD 대비) + untracked(무시 제외)
    local current
    current=$({
        git diff --name-only HEAD 2>/dev/null
        git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u)

    # 이번 세션에서 새로 바뀐 파일 = 현재 목록 - 스냅샷 목록 (차집합)
    # comm은 정렬된 입력 필요 — 양쪽 모두 sort -u 보장.
    local session_changes
    if [ -f "$SNAPSHOT" ]; then
        session_changes=$(comm -23 \
            <(printf '%s\n' "$current" | sort -u) \
            <(sort -u "$SNAPSHOT" 2>/dev/null) \
            2>/dev/null)
    else
        echo "[pre-complete] ⚠️ 세션 시작 스냅샷 없음 — 현재 변경 전체를 이번 세션 수정으로 간주 (안전 측)"
        echo "[pre-complete]    원인: 세션 시작 훅 미실행 또는 스냅샷 파일 삭제. 정상 작동 시 다음 세션부터 자동 판단."
        session_changes="$current"
    fi

    # 코드 파일 분류 — 백엔드/프론트엔드
    local backend_new frontend_new
    backend_new=$(printf '%s\n' "$session_changes" | grep -E '^(backend/|main\.py$)' | head -1)
    frontend_new=$(printf '%s\n' "$session_changes" | grep -E '^frontend/' | head -1)

    echo "[pre-complete] [auto] 이번 세션 변경 파일 분석:"
    if [ -n "$session_changes" ]; then
        printf '%s\n' "$session_changes" | sed 's/^/  - /'
    else
        echo "  - (이번 세션 코드 변경 없음 — 이전 세션 잔재만 또는 변경 없음)"
    fi

    if [ -n "$backend_new" ]; then
        echo "[pre-complete] [auto] 백엔드 수정 감지 → backend 모드 (런타임 기동 검증 포함)"
        run_backend "backend"
        if [ -n "$frontend_new" ]; then
            echo "[pre-complete] [auto] 프론트엔드 수정도 감지 → frontend 검증 추가 실행"
            run_frontend
        fi
    elif [ -n "$frontend_new" ]; then
        echo "[pre-complete] [auto] 프론트엔드 수정만 감지 → frontend 모드 (백엔드 프로세스 보호)"
        run_frontend
    else
        echo "[pre-complete] [auto] 코드 변경 없음 → docs 모드 (코드 검증 스킵, 백엔드 프로세스 보호)"
        run_docs
    fi
}

# ─── 문서 전용 세션 검증 ───
# 코드 검증은 전부 스킵. 백엔드 프로세스를 절대 건드리지 않음.
# 단, 작업 창에 백엔드/프론트엔드 코드 변경이 감지되면 docs 모드를 거부(fail) —
# 에이전트가 잘못된 모드를 골랐을 때 검증 누락을 막는 안전장치.
# 문서 자체 점검(깨진 참조·포맷)은 에이전트가 별도 수행 — 본 스크립트는 안내만 출력.
run_docs() {
    local code_changed
    code_changed=$(git status --short --untracked-files=no 2>/dev/null \
        | awk '{print $2}' \
        | grep -E '^(backend/|frontend/|main\.py$)' \
        | head -1)
    if [ -n "$code_changed" ]; then
        echo "[pre-complete] ❌ docs 모드 거부 — 코드 변경 감지됨: $code_changed"
        echo "[pre-complete]    이번 세션에서 코드를 수정했으면 docs 모드가 아닌 올바른 모드로 실행:"
        echo "[pre-complete]    백엔드 수정 → backend, 프론트엔드 수정 → frontend, 양쪽 → all (또는 backend 후 frontend)"
        echo "[pre-complete]    코드 변경이 이전 세션 잔재라면 해당 변경을 먼저 정리(stash/commit/checkout) 후 docs 모드 재실행."
        FAILED=$((FAILED + 1))
        return 0
    fi
    echo "[pre-complete] ℹ️ 문서 전용 세션 — 코드 기계 검증 전부 스킵 (코드 변경 감지 0건 확인)"
    echo "[pre-complete] ℹ️ 백엔드 프로세스를 건드리지 않습니다 (사용자가 켜둔 백엔드 보호)."
    echo "[pre-complete] ℹ️ 문서 자체 점검(깨진 참조·포맷·용어 일관성)은 에이전트가 별도 수행 후 보고."
}

# ─── 프론트엔드 검증 ───
run_frontend() {
    if [ ! -f "frontend/package.json" ]; then
        echo "[pre-complete] ❌ frontend/package.json 없음 — 프론트엔드 검증을 수행할 수 없음"
        FAILED=$((FAILED + 1))
        return 0
    fi

    # 백엔드 코드 변경 감지 시 경고 — frontend 모드는 백엔드 검증을 스킵하므로
    # 백엔드 수정이 있으면 all 또는 backend 모드로 별도 실행해야 함.
    local backend_changed
    backend_changed=$(git status --short --untracked-files=no 2>/dev/null \
        | awk '{print $2}' \
        | grep -E '^(backend/|main\.py$)' \
        | head -1)
    if [ -n "$backend_changed" ]; then
        echo "[pre-complete] ⚠️ 주의: 백엔드 코드 변경 감지됨($backend_changed) — frontend 모드는 백엔드 검증을 스킵합니다."
        echo "[pre-complete]    백엔드 수정이 이번 세션 작업이라면 all 또는 backend 모드로 별도 실행 필요."
        echo "[pre-complete]    이전 세션 잔재라면 해당 변경을 먼저 정리(stash/commit/checkout) 권장."
    fi

    echo "[pre-complete] [1/4] 프론트엔드 타입체크 (tsc --noEmit)..."
    if ! (cd frontend && npm run typecheck 2>&1 | tail -5); then
        echo "[pre-complete] ❌ 타입체크 실패 — 타입 오류 존재"
        echo "[pre-complete]    수정 방법: 실패한 파일/줄의 타입 오류 수정"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션2 '코드 수정 시 점검 체크리스트 — 프론트엔드'"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ 타입체크 통과"
    fi

    echo "[pre-complete] [2/4] 프론트엔드 린트 (ESLint)..."
    if ! (cd frontend && npm run lint 2>&1 | tail -5); then
        echo "[pre-complete] ❌ ESLint 실패 — empty catch/unused vars/no-redeclare 등 발견"
        echo "[pre-complete]    수정 방법: 실패한 파일/줄의 린트 오류 수정"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션1 검증 명령어 표"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ ESLint 통과"
    fi

    echo "[pre-complete] [3/4] 프론트엔드 빌드 (vite build)..."
    if ! (cd frontend && npm run build 2>&1 | tail -5); then
        echo "[pre-complete] ❌ 빌드 실패 — 빌드 오류 존재"
        echo "[pre-complete]    수정 방법: 빌드 오류 메시지의 지시에 따라 수정"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션1 검증 명령어 표"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ 빌드 통과"
    fi

    echo "[pre-complete] [4/4] 프론트엔드 테스트 (vitest)..."
    if ! (cd frontend && npm run test 2>&1 | tail -5); then
        echo "[pre-complete] ❌ vitest 실패 — 기존 UI 동작 회귀 또는 신규 테스트 실패"
        echo "[pre-complete]    수정 방법: 실패한 테스트의 assertion 기준으로 원인 추적"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션3 규칙 0-1-2 '검증 자동화 루프'"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ vitest 통과"
    fi
}

# ─── 사실 보고 근거 검증 (하네스 강화 — 추측 보고 차단 + 4-게이트 패턴) ───
# 이번 세션에서 생성/수정된 보고서(조사보고서/설계서/태스크)에 근거 표기가 있는지 확인.
# 4계층 검증 (인터넷 검증 패턴 취합 — 2-게이트 + Phantom Grounding 방지 + 코드 대조):
#   게이트 1 (cite-check): 단정 표현이 있는데 근거 표기가 0개면 차단 (기존)
#   게이트 2 (근접성 검사): 단정이 있는 문단(빈 줄로 구분)에 근거가 없으면 차단 (1단계)
#   게이트 3 (근거 존재 확인): 근거로 적힌 파일 경로가 실제 파일 시스템에 없으면 차단 (2단계)
#   게이트 4 (코드-단정 연관): 근거 코드의 식별자가 단정 문단에 언급되지 않으면 차단 (3단계)
# 선언된 추측("가정/가능성/추측/예상")은 허용 — 가정 선언 의무 규칙 준수.
# 사건 재발 방지: 2026-08-07 추측 보고 사건 (코드 안 읽고 구조 단언 → 사용자 추궁 후 정정).
# 패턴 출처:
#   - a builder's codex "claim-verify-gate" 2-게이트 (cite-check + claim-verify)
#   - Agent Patterns 카탈로그 "Hallucinated Sources" fail-closed 검증
#   - 학술 연구 LedgerMind "Phantom Grounding" — 인용은 있으나 인용이 단정을 지지하지 않는 실패
#   - GitHub truth + agentic_codebase::grounding — 클레임에서 코드 참조 추출, 실제 코드와 대조,
#     "검증 불가능한 것은 정직하게 거부" 철학. NLI 모델 없이 결정론적 방식으로 의미 연관 근사.
check_fact_grounding() {
    local SNAPSHOT=".devin/state/session_changes_snapshot.txt"

    # 이번 세션에서 새로 바뀐 파일 수집 (run_auto와 동일 방식)
    local current
    current=$({
        git diff --name-only HEAD 2>/dev/null
        git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u)

    local session_changes
    if [ -f "$SNAPSHOT" ]; then
        session_changes=$(comm -23 \
            <(printf '%s\n' "$current" | sort -u) \
            <(sort -u "$SNAPSHOT" 2>/dev/null) \
            2>/dev/null)
    else
        session_changes="$current"
    fi

    # 보고서 파일만 추출 (조사보고서/설계서/태스크 — 사실 단언이 담기는 문서)
    local report_files
    report_files=$(printf '%s\n' "$session_changes" | grep -E '^docs/(조사보고서|설계서|태스크)/.*\.md$')

    if [ -z "$report_files" ]; then
        echo "[pre-complete] ℹ️ 사실 보고 근거 검사 생략 — 이번 세션 보고서 파일 없음"
        return 0
    fi

    echo "[pre-complete] [사실 보고 근거 검증] 이번 세션 보고서 파일:"
    printf '%s\n' "$report_files" | sed 's/^/  - /'

    # 근거 표기 정규식 (게이트 1·2·3 공용)
    local EVIDENCE_RE='[a-zA-Z_][a-zA-Z0-9_/]+\.(py|ts|js|tsx|jsx):[0-9]+|코드 위치|로그|trading_[0-9]|\.log|`[a-zA-Z_]+\.(py|ts|js)'
    # 단정 표현 정규식 (게이트 1·2 공용)
    local ASSERTION_RE='확정|단언|사실|틀린|맞음|준수|위반|확인됨|검증됨|실제로는|실제 원인'
    # 선언된 추측 표현 (가정 선언 의무 준수 시)
    local HEDGED_RE='가정|가능성|추측|예상|추정|수 있|것으로'
    # 근거에서 파일 경로만 추출 (게이트 3용) — 파일:라인 형식에서 파일 부분
    local FILEPATH_RE='[a-zA-Z_][a-zA-Z0-9_/]+\.(py|ts|js|tsx|jsx)'

    while IFS= read -r rf; do
        [ -z "$rf" ] && continue
        [ -f "$rf" ] || continue

        # ── 파일 전체 개수 집계 (게이트 1 — 기존 로직 유지) ──
        local has_evidence
        has_evidence=$(grep -cE "$EVIDENCE_RE" "$rf" 2>/dev/null || true)
        [ -z "$has_evidence" ] && has_evidence=0

        local has_assertion
        has_assertion=$(grep -cE "$ASSERTION_RE" "$rf" 2>/dev/null || true)
        [ -z "$has_assertion" ] && has_assertion=0

        local has_hedged
        has_hedged=$(grep -cE "$HEDGED_RE" "$rf" 2>/dev/null || true)
        [ -z "$has_hedged" ] && has_hedged=0

        # 게이트 1: 단정이 있는데 근거 표기가 0개면 차단 (기존)
        if [ "$has_assertion" -gt 0 ] && [ "$has_evidence" -eq 0 ]; then
            echo "[pre-complete] ❌ 사실 보고 근거 누락 (게이트 1) — $rf"
            echo "[pre-complete]    단정 표현(${has_assertion}개)이 있으나 코드/로그 근거 표기가 없음"
            echo "[pre-complete]    → 코드를 먼저 직접 읽고 근거(파일:라인 또는 로그)를 보고서에 포함 후 재시도"
            echo "[pre-complete]    사건 재발 방지: 2026-08-07 추측 보고 (코드 안 읽고 구조 단언 → 사용자 추궁 후 정정)"
            echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션3 규칙 0(사전조사·가정 선언) + 규칙 0-8(사용자 보고 의무)"
            FAILED=$((FAILED + 1))
            continue
        fi

        # 선언된 추측만 있고 단정이 없으면 통과 (기존)
        if [ "$has_hedged" -gt 0 ] && [ "$has_assertion" -eq 0 ]; then
            echo "[pre-complete] ✅ $rf — 선언된 추측만 존재 (가정 선언 의무 준수)"
            continue
        fi

        # 단정 표현이 없으면 검사 대상 아님 (기존)
        if [ "$has_assertion" -eq 0 ]; then
            echo "[pre-complete] ✅ $rf — 단정 표현 없음 (검사 대상 아님)"
            continue
        fi

        # ── 게이트 2: 근거-단정 근접성 검사 (신규 — 1단계) ──
        # 보고서를 빈 줄로 문단 분할, 단정이 포함된 문단에 근거가 같이 있는지 확인.
        # 무관한 곳에 근거를 흩뿌려 통과하는 우회 차단 (Phantom Grounding 방지).
        # 패턴: a builder's codex "근접성 휴리스틱" — 단정과 가장 가까운 근거 매핑.
        local para_assertion_count=0
        local para_ungrounded_count=0
        local current_para=""
        local para_has_assertion=false
        local para_has_evidence=false
        local para_line=0
        local ungrounded_details=""

        while IFS= read -r line || [ -n "$line" ]; do
            para_line=$((para_line + 1))
            # 빈 줄(공백만) = 문단 구분자
            if [ -z "$(printf '%s' "$line" | tr -d '[:space:]')" ]; then
                # 문단 종료 — 판정
                if $para_has_assertion && ! $para_has_evidence; then
                    para_ungrounded_count=$((para_ungrounded_count + 1))
                fi
                if $para_has_assertion; then
                    para_assertion_count=$((para_assertion_count + 1))
                fi
                current_para=""
                para_has_assertion=false
                para_has_evidence=false
                continue
            fi
            current_para="${current_para}${line}"$'\n'
            if echo "$line" | grep -qE "$ASSERTION_RE"; then
                para_has_assertion=true
            fi
            if echo "$line" | grep -qE "$EVIDENCE_RE"; then
                para_has_evidence=true
            fi
        done < "$rf"
        # 마지막 문단 처리 (파일 끝에 빈 줄이 없는 경우)
        if $para_has_assertion && ! $para_has_evidence; then
            para_ungrounded_count=$((para_ungrounded_count + 1))
        fi
        if $para_has_assertion; then
            para_assertion_count=$((para_assertion_count + 1))
        fi

        if [ "$para_ungrounded_count" -gt 0 ]; then
            echo "[pre-complete] ❌ 사실 보고 근거 근접성 위반 (게이트 2) — $rf"
            echo "[pre-complete]    단정이 포함된 문단 ${para_assertion_count}개 중 ${para_ungrounded_count}개에 근거 표기 없음"
            echo "[pre-complete]    → 단정과 같은 문단에 근거(파일:라인 또는 로그)를 함께 배치 후 재시도"
            echo "[pre-complete]    패턴: 2-게이트 근접성 휴리스틱 — 무관한 곳에 근거 흩뿌려 통과 차단"
            FAILED=$((FAILED + 1))
            # 게이트 2 실패 시 게이트 3은 건너뜀 (이미 차단)
            continue
        fi

        # ── 게이트 3: 근거 파일 실제 존재 확인 (신규 — 2단계) ──
        # 근거로 적힌 파일 경로(.py/.ts/.js 등)를 추출해 실제 파일 시스템에 존재하는지 확인.
        # 존재하지 않는 파일 경로를 근거로 적는 환각 차단 (Hallucinated Sources 방지).
        # 패턴: Agent Patterns "fail-closed 검증" + CitationStore "source 존재 확인".
        local missing_files=""
        local checked_paths=""
        local extracted_paths
        extracted_paths=$(grep -oE "$FILEPATH_RE" "$rf" 2>/dev/null | sort -u || true)

        if [ -n "$extracted_paths" ]; then
            while IFS= read -r fp; do
                [ -z "$fp" ] && continue
                # 프로젝트 루트 상대경로로 확인 (이 스크립트는 git root에서 실행)
                if [ ! -f "$fp" ]; then
                    missing_files="${missing_files}  ${fp}"$'\n'
                fi
                checked_paths="${checked_paths} ${fp}"
            done <<< "$extracted_paths"
        fi

        if [ -n "$missing_files" ]; then
            echo "[pre-complete] ❌ 사실 보고 근거 파일 미존재 (게이트 3) — $rf"
            echo "[pre-complete]    보고서에 적힌 근거 파일 경로가 실제로 존재하지 않음:"
            printf '%s' "$missing_files" | sed 's/^/      /'
            echo "[pre-complete]    → 실제 코드를 읽고 존재하는 파일 경로를 근거로 기재 후 재시도"
            echo "[pre-complete]    패턴: Hallucinated Sources fail-closed — 존재하지 않는 출처 인용 차단"
            FAILED=$((FAILED + 1))
            continue
        fi

        # ── 게이트 4: 코드-단정 의미 연관 검사 (신규 — 3단계) ──
        # 근거로 적힌 파일:라인의 실제 코드 내용을 추출하고, 그 코드의 식별자(함수명·변수명 등)가
        # 단정이 포함된 문단에 언급되어 있는지 검사. 하나도 없으면 "관련 없는 코드를 근거로 적음"으로 차단.
        # "코드는 읽었는데 잘못 해석"·"관련 없는 코드 근거" 실패 모드 방지.
        # 패턴: truth "클레임을 실제 코드와 대조" + agentic_codebase::grounding "코드 참조 추출 + 그래프 대조"
        # 한계: 완전한 의미 검증(NLI)이 아닌 식별자 동시 출현 휴리스틱. truth 철학에 따라
        # "검증 불가능한 것은 통과시키되, 명백히 무관한 근거는 차단" — false positive 최소화.
        local FILELINE_RE='[a-zA-Z_][a-zA-Z0-9_/]+\.(py|ts|js|tsx|jsx):[0-9]+'
        local ungrounded_refs=""
        local total_refs=0

        # 보고서에서 파일:라인 패턴 추출
        local fileline_matches
        fileline_matches=$(grep -oE "$FILELINE_RE" "$rf" 2>/dev/null | sort -u || true)

        if [ -n "$fileline_matches" ]; then
            while IFS= read -r fl; do
                [ -z "$fl" ] && continue
                total_refs=$((total_refs + 1))

                # 파일 경로와 라인 번호 분리
                local fl_file="${fl%:*}"
                local fl_line="${fl##*:}"
                [ -f "$fl_file" ] || continue

                # 해당 라인 ±5줄 코드 추출
                local start_line=$((fl_line - 5))
                [ "$start_line" -lt 1 ] && start_line=1
                local end_line=$((fl_line + 5))
                local code_snippet
                code_snippet=$(sed -n "${start_line},${end_line}p" "$fl_file" 2>/dev/null || true)

                [ -z "$code_snippet" ] && continue

                # 코드에서 식별자 추출 — 영어 단어, 4글자 이상 (함수명·변수명·클래스명)
                # 키워드 제외 (def/class/import/return/if/else/for/while/try/except/async/await 등)
                local code_identifiers
                code_identifiers=$(printf '%s' "$code_snippet" \
                    | grep -oE '[a-zA-Z_][a-zA-Z0-9_]+' \
                    | grep -vE '^(def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|in|not|and|or|is|None|True|False|async|await|self|cls|print|len|range|open|raise|pass|break|continue|global|nonlocal|yield|lambda|del|assert)$' \
                    | sort -u 2>/dev/null || true)

                [ -z "$code_identifiers" ] && continue

                # 해당 파일:라인이 포함된 문단 추출 (게이트 2와 동일한 문단 분할)
                # 단정이 있는 문단을 찾아, 그 문단에 코드 식별자가 하나라도 언급되었는지 검사
                local para_with_ref=""
                local current_p=""
                local in_target_para=false

                while IFS= read -r pline || [ -n "$pline" ]; do
                    if [ -z "$(printf '%s' "$pline" | tr -d '[:space:]')" ]; then
                        # 문단 종료 — 타겟 파일:라인이 이 문단에 있었으면 저장
                        if $in_target_para; then
                            para_with_ref="$current_p"
                            in_target_para=false
                        fi
                        current_p=""
                        continue
                    fi
                    current_p="${current_p}${pline}"$'\n'
                    # 이 줄에 타겟 파일:라인이 포함되어 있는지
                    if echo "$pline" | grep -qF "$fl"; then
                        in_target_para=true
                    fi
                done < "$rf"
                # 마지막 문단
                if $in_target_para; then
                    para_with_ref="$current_p"
                fi

                [ -z "$para_with_ref" ] && continue

                # 단정 문단에서 파일:라인 패턴 자체를 제거한 텍스트로 식별자 매칭.
                # 파일 경로 자체(engine_loop 등)가 식별자로 추출되어 항상 통과하는 우회 방지.
                local para_text_only
                para_text_only=$(printf '%s' "$para_with_ref" | sed -E 's/[a-zA-Z_][a-zA-Z0-9_/]+\.(py|ts|js|tsx|jsx):[0-9]+//g' | sed -E 's/[a-zA-Z_][a-zA-Z0-9_/]+\.(py|ts|js|tsx|jsx)//g')

                # 단정 문단(파일 경로 제거)에 코드 식별자 중 하나라도 언급되었는지 검사
                local found_match=false
                while IFS= read -r ident; do
                    [ -z "$ident" ] && continue
                    if printf '%s' "$para_text_only" | grep -qF "$ident"; then
                        found_match=true
                        break
                    fi
                done <<< "$code_identifiers"

                if ! $found_match; then
                    ungrounded_refs="${ungrounded_refs}  ${fl} (코드 식별자와 단정 문단 연관 없음)"$'\n'
                fi
            done <<< "$fileline_matches"
        fi

        if [ -n "$ungrounded_refs" ]; then
            echo "[pre-complete] ❌ 사실 보고 근거-단정 연관 위반 (게이트 4) — $rf"
            echo "[pre-complete]    근거 코드 ${total_refs}개 중 연관 없는 근거:"
            printf '%s' "$ungrounded_refs" | sed 's/^/      /'
            echo "[pre-complete]    → 근거로 인용한 코드의 함수명·변수명이 단정 문단에 언급되어야 함"
            echo "[pre-complete]    패턴: truth + agentic_codebase::grounding — 클레임과 실제 코드 대조, 무관한 근거 차단"
            FAILED=$((FAILED + 1))
            continue
        fi

        # 4계층 전부 통과
        echo "[pre-complete] ✅ $rf — 4계층 통과 (단정 ${has_assertion}·근거 ${has_evidence}·근접성 OK·파일 존재 OK·코드 연관 OK)"
    done <<< "$report_files"
}

# ─── 핸드오버 갱신 여부 확인 (완료 보고 누락 방지) ───
# 코드를 수정했는데 다음 세션 인계 문서(HANDOVER.md)를 갱신하지 않고
# "완료" 보고하는 것을 차단. 코드 변경이 없는 문서 전용 작업은 예외(규칙 0-6-2).
# 판정 방법: 이번 세션에서 변경된 코드 파일(working tree + 마지막 커밋) 중
# 가장 최근 수정 시각과 HANDOVER.md 수정 시각을 비교 —
# HANDOVER가 최근 코드 변경보다 오래됐으면 갱신 누락으로 판정.
check_handover_update() {
    local HANDOVER="HANDOVER.md"
    if [ ! -f "$HANDOVER" ]; then
        echo "[pre-complete] ℹ️ HANDOVER.md 없음 — 핸드오버 갱신 검사 생략"
        return 0
    fi

    # 이번 세션 변경 코드 파일 수집: working tree(수정/추가) + 마지막 커밋
    local changed
    changed=$(git status --short --untracked-files=no 2>/dev/null | awk '{print $2}')
    changed="$changed
$(git diff --name-only HEAD~1 HEAD 2>/dev/null)"
    # 코드 경로만 (backend/ frontend/) — 문서·스크립트는 제외
    local code_files
    code_files=$(echo "$changed" | grep -E '^(backend|frontend)/' | sort -u)

    if [ -z "$code_files" ]; then
        echo "[pre-complete] ℹ️ 코드 변경 없음 — 핸드오버 갱신 검사 생략(문서 전용 작업 예외)"
        return 0
    fi

    # 수정 시각(mtime) 비교 — macOS(BSD stat) / Linux(GNU stat) 호환
    local handover_mtime
    handover_mtime=$(stat -f %m "$HANDOVER" 2>/dev/null || stat -c %Y "$HANDOVER" 2>/dev/null)
    if [ -z "$handover_mtime" ]; then
        echo "[pre-complete] ℹ️ HANDOVER.md mtime 확인 불가 — 핸드오버 갱신 검사 생략"
        return 0
    fi

    local newest=0
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        [ -f "$f" ] || continue
        local m
        m=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null)
        if [ -n "$m" ] && [ "$m" -gt "$newest" ] 2>/dev/null; then
            newest="$m"
        fi
    done <<< "$code_files"

    if [ "$handover_mtime" -lt "$newest" ] 2>/dev/null; then
        echo "[pre-complete] ❌ 핸드오버 갱신 누락 — HANDOVER.md가 최근 코드 변경보다 오래됨"
        echo "[pre-complete]    수정 방법: 세션 종료 절차 3단계 — HANDOVER.md 갱신 후 재시도"
        echo "[pre-complete]    더 자세한 내용: AGENTS.md 섹션4 '세션 종료 절차' + 규칙 0-6-2"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ 핸드오버 갱신 확인 (최근 코드 변경 이후 갱신됨)"
    fi
}

# ─── 핵심 로직 변경 자동 감지 (하네스 강화 — 위험도 판정 자동화) ───
# 이번 세션에서 변경된 파일 목록을 보고 매매·주문·엔진·리스크 관련 파일이 포함되면
# 자동으로 "핵심 로직 변경"으로 판정. 에이전트가 위험도를 자발적으로 판정하지 않고
# 스크립트가 기계적으로 판정 — "핵심 로직인데 독립 검증 생략" 회피 방지.
# 패턴: Deterministic Guardrails (agentpatterns.ai) — "에이전트에게 판단을 맡기지 않고
# 스크립트가 결정론적으로 판정". P24 단순성 부합 — 에이전트가 위험도를 고를 필요 없음.
#
# 출력: 핵심 로직 감지 시 CORE_LOGIC=1, 감지 안 되면 CORE_LOGIC=0
# 감지된 파일 목록은 CORE_LOGIC_FILES에 저장.
CORE_LOGIC=0
CORE_LOGIC_FILES=""
detect_core_logic() {
    local SNAPSHOT=".devin/state/session_changes_snapshot.txt"

    # 이번 세션 변경 파일 수집 (run_auto와 동일 방식)
    local current
    current=$({
        git diff --name-only HEAD 2>/dev/null
        git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u)

    local session_changes
    if [ -f "$SNAPSHOT" ]; then
        session_changes=$(comm -23 \
            <(printf '%s\n' "$current" | sort -u) \
            <(sort -u "$SNAPSHOT" 2>/dev/null) \
            2>/dev/null)
    else
        session_changes="$current"
    fi

    # 핵심 로직 파일 패턴 — 매매·주문·엔진·리스크·매수후보·업종점수·토큰발급
    # 파일 경로로 판정 (에이전트 판단 개입 제거 — P24 단순성)
    local CORE_PATTERN='trading\.py|engine_loop\.py|engine_lifecycle\.py|engine_buy_target|engine_order_loop|risk_|buy_filter|pipeline_compute|pipeline_screening|pipeline_ranking|daily_time_scheduler|broker_|ls_connector|kiwoom_connector|connector_manager|token_|settings_store|settings_defaults|core_queues'

    CORE_LOGIC_FILES=$(printf '%s\n' "$session_changes" \
        | grep -E "$CORE_PATTERN" \
        | grep -E '^backend/' \
        2>/dev/null || true)

    if [ -n "$CORE_LOGIC_FILES" ]; then
        CORE_LOGIC=1
        echo "[pre-complete] [핵심 로직 감지] 매매·주문·엔진·리스크 관련 파일 변경 감지:"
        printf '%s\n' "$CORE_LOGIC_FILES" | sed 's/^/  - /'
        echo "[pre-complete]    → 독립 검증 도구(independent-verify) 실행 필수 (위험도 높음 — 생략 불가)"
    fi
}

# ─── 검증 도구 실행 증거 확인 (하네스 강화 — 이관 후 실행 보장) ───
# 독립 검증·커밋 전 검토 도구가 이관된 후 실행 보장 장치가 없어 한 번도 실행되지 않은
# 문제 해결. "에이전트가 알아서 따라야 하는 절차"에서 "안 하면 진행 불가" 방식으로 전환.
#
# 패턴 출처:
#   - Pre-completion Checklists (agentpatterns.ai) — "체크리스트는 제안이 아니라 게이트다"
#   - Evidence before claims (OpenAI superpowers) — "검증 명령을 실행하지 않았으면 통과라고 주장 불가"
#   - Stop 훅 강제 (harnesswright/Tautline) — "에이전트의 완료는 주장이지 사실이 아니다"
#   - Deterministic Guardrails (agentpatterns.ai) — "가드레일은 매번 실행되고 추론으로 우회 불가"
#
# 확인 방식: 도구 실행 후 결과 파일(.devin/state/verify-results/)이 생성되었는지 결정론적 확인.
# 파일 존재 여부로 판정 — 에이전트 자기 보고가 아닌 파일 시스템 증거로 확인 (self-attested
# verification 차단 — tianpan.co "검증은 런타임에서, 모델 출력이 아닌").
#
# 위험도 계층 (수정안 4 자동 감지 결과 사용):
#   - CORE_LOGIC=1 (핵심 로직) → pre-commit-review + independent-verify 둘 다 필수
#   - 코드 변경 있으나 핵심 아님 → pre-commit-review 필수, independent-verify 권장(생략 가능)
#   - 코드 변경 없음 (docs 모드) → 둘 다 생략
check_verification_tools() {
    local VERIFY_DIR=".devin/state/verify-results"
    local SNAPSHOT=".devin/state/session_changes_snapshot.txt"

    # 이번 세션 변경 파일 수집
    local current
    current=$({
        git diff --name-only HEAD 2>/dev/null
        git ls-files --others --exclude-standard 2>/dev/null
    } | sort -u)

    local session_changes
    if [ -f "$SNAPSHOT" ]; then
        session_changes=$(comm -23 \
            <(printf '%s\n' "$current" | sort -u) \
            <(sort -u "$SNAPSHOT" 2>/dev/null) \
            2>/dev/null)
    else
        session_changes="$current"
    fi

    # 코드 변경 여부 확인
    local has_code_change
    has_code_change=$(printf '%s\n' "$session_changes" \
        | grep -E '^(backend/|frontend/|main\.py$)' \
        | head -1)

    if [ -z "$has_code_change" ]; then
        echo "[pre-complete] ℹ️ 검증 도구 실행 검사 생략 — 코드 변경 없음 (문서 전용)"
        return 0
    fi

    echo "[pre-complete] [검증 도구 실행 증거 확인]"

    # ── pre-commit-review 도구 실행 증거 확인 (모든 코드 변경 시 필수) ──
    local pcr_found=false
    if [ -d "$VERIFY_DIR" ]; then
        # 이번 세션 커밋 해시 또는 미커밋 변경에 대한 증거 파일 확인
        # 증거 파일명 패턴: pre-commit-review-*.md
        local pcr_files
        pcr_files=$(ls -1 "$VERIFY_DIR"/pre-commit-review-*.md 2>/dev/null || true)
        if [ -n "$pcr_files" ]; then
            # 가장 최근 파일의 수정 시각이 이번 세션 시작 이후인지 확인
            local snapshot_mtime=0
            if [ -f "$SNAPSHOT" ]; then
                snapshot_mtime=$(stat -f %m "$SNAPSHOT" 2>/dev/null || stat -c %Y "$SNAPSHOT" 2>/dev/null)
            fi
            local newest_pcr=0
            while IFS= read -r pf; do
                [ -z "$pf" ] && continue
                local m
                m=$(stat -f %m "$pf" 2>/dev/null || stat -c %Y "$pf" 2>/dev/null)
                if [ -n "$m" ] && [ "$m" -gt "$newest_pcr" ] 2>/dev/null; then
                    newest_pcr="$m"
                fi
            done <<< "$pcr_files"
            # 스냅샷이 있으면 스냅샷 이후, 없으면 최근 1시간 이내
            if [ "$snapshot_mtime" -gt 0 ]; then
                if [ "$newest_pcr" -ge "$snapshot_mtime" ] 2>/dev/null; then
                    pcr_found=true
                fi
            else
                local now
                now=$(date +%s)
                local one_hour_ago=$((now - 3600))
                if [ "$newest_pcr" -ge "$one_hour_ago" ] 2>/dev/null; then
                    pcr_found=true
                fi
            fi
        fi
    fi

    if ! $pcr_found; then
        echo "[pre-complete] ❌ 커밋 전 검토 도구(pre-commit-review) 실행 증거 없음"
        echo "[pre-complete]    코드 변경 시 커밋 전 검토 도구 실행 필수 — 방금 바뀐 부분 안전·의도·회귀 점검"
        echo "[pre-complete]    실행 방법: pre-commit-review 스킬 호출 → 결과를 .devin/state/verify-results/ 에 저장"
        echo "[pre-complete]    패턴: Evidence before claims — 검증 없이 완료 주장 불가"
        FAILED=$((FAILED + 1))
    else
        echo "[pre-complete] ✅ 커밋 전 검토 도구 실행 증거 확인"
    fi

    # ── independent-verify 도구 실행 증거 확인 (핵심 로직 변경 시 필수) ──
    if [ "$CORE_LOGIC" -eq 1 ]; then
        local iv_found=false
        if [ -d "$VERIFY_DIR" ]; then
            local iv_files
            iv_files=$(ls -1 "$VERIFY_DIR"/independent-verify-*.md 2>/dev/null || true)
            if [ -n "$iv_files" ]; then
                local snapshot_mtime=0
                if [ -f "$SNAPSHOT" ]; then
                    snapshot_mtime=$(stat -f %m "$SNAPSHOT" 2>/dev/null || stat -c %Y "$SNAPSHOT" 2>/dev/null)
                fi
                local newest_iv=0
                while IFS= read -r vf; do
                    [ -z "$vf" ] && continue
                    local m
                    m=$(stat -f %m "$vf" 2>/dev/null || stat -c %Y "$vf" 2>/dev/null)
                    if [ -n "$m" ] && [ "$m" -gt "$newest_iv" ] 2>/dev/null; then
                        newest_iv="$m"
                    fi
                done <<< "$iv_files"
                if [ "$snapshot_mtime" -gt 0 ]; then
                    if [ "$newest_iv" -ge "$snapshot_mtime" ] 2>/dev/null; then
                        iv_found=true
                    fi
                else
                    local now
                    now=$(date +%s)
                    local one_hour_ago=$((now - 3600))
                    if [ "$newest_iv" -ge "$one_hour_ago" ] 2>/dev/null; then
                        iv_found=true
                    fi
                fi
            fi
        fi

        if ! $iv_found; then
            echo "[pre-complete] ❌ 독립 검증 도구(independent-verify) 실행 증거 없음 — 핵심 로직 변경 시 필수"
            echo "[pre-complete]    매매·주문·엔진·리스크 관련 파일 변경 감지 — 독립 검증 생략 불가"
            echo "[pre-complete]    실행 방법: independent-verify 스킬 호출(별도 작업창) → 결과를 .devin/state/verify-results/ 에 저장"
            echo "[pre-complete]    패턴: Generator-Critic Separation — 작성자=검증자 편향 차단"
            FAILED=$((FAILED + 1))
        else
            echo "[pre-complete] ✅ 독립 검증 도구 실행 증거 확인 (핵심 로직 변경 — 필수 충족)"
        fi
    else
        echo "[pre-complete] ℹ️ 독립 검증 도구 검사 생략 — 핵심 로직 변경 아님 (위험도 낮음, 생략 가능)"
    fi
}

# ─── 실행 ───
case "$TARGET" in
    auto)     run_auto ;;
    backend)  run_backend "backend" ;;
    frontend) run_frontend ;;
    docs)     run_docs ;;
    all)      run_backend "all"; run_frontend ;;
    *)
        echo "[pre-complete] ❌ 잘못된 대상: $TARGET (auto|backend|frontend|docs|all 중 하나)"
        exit 2
        ;;
esac

# 핸드오버 갱신 확인은 대상과 무관하게 항상 실행 (코드 변경 있을 때만 실제 판정)
check_handover_update

# 사실 보고 근거 검증 — 보고서 파일이 이번 세션에 생성/수정됐을 때만 실제 판정.
# 조사·보고 세션의 추측 보고를 기계적으로 차단 (사건 재발 방지).
check_fact_grounding

# 핵심 로직 변경 자동 감지 — 위험도 판정 자동화 (수정안 4)
# 도구 실행 증거 확인(아래)보다 먼저 실행 — CORE_LOGIC 변수 설정.
detect_core_logic

# 검증 도구 실행 증거 확인 — 이관 후 실행 보장 (수정안 1)
# 코드 변경 시 pre-commit-review 필수, 핵심 로직 시 independent-verify 필수.
# 증거 파일(.devin/state/verify-results/) 존재 여부로 결정론적 판정.
check_verification_tools

echo "[pre-complete] ------------------------------------------------"
if [ "$FAILED" -gt 0 ]; then
    echo "[pre-complete] ❌ 검증 실패 — ${FAILED}건 실패"
    echo "[pre-complete] 완료 보고 금지 — 실패 항목 수정 후 재실행"
    echo "[pre-complete] 3회 재시도 후에도 동일 실패 시 사용자 보고 후 대기 (규칙 0-1-2)"
    exit 1
fi

echo "[pre-complete] ✅ 모든 기계적 검증 통과 — 완료 보고 진행 가능"
echo "[pre-complete] 주의: 기계적 검증 통과만으로 완료 아님 —"
echo "[pre-complete]   의미적 검증(태스크 항목/원칙/설계/부작용) +"
echo "[pre-complete]   요청 의도 사후 확인(Intent layer) +"
echo "[pre-complete]   검증 도구 실행 증거(pre-commit-review·independent-verify)도 통과해야 완료"
exit 0
