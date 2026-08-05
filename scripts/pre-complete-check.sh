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
echo "[pre-complete]   독립 검증자(거래·핵심 로직 시)도 통과해야 완료"
exit 0
