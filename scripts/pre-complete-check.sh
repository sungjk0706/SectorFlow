#!/usr/bin/env bash
# SectorFlow pre-complete-check — 완료 보고 전 기계적 검증 (하네스 엔지니어링 강화)
# AGENTS.md "검증 게이트 원칙" + "작업 완료 시 점검 체크리스트" 1단계 구현
# 완료 보고(사용자에게 "다 됐다"고 알리기) 전 반드시 실행 — 실패 시 완료 보고 금지
# 사용법: bash scripts/pre-complete-check.sh [backend|frontend|all]
#   backend  — 백엔드 검증만 (백엔드 수정 시)
#   frontend — 프론트엔드 검증만 (프론트엔드 수정 시)
#   all      — 양쪽 모두 (기본값 — 변경 범위 불명확 시 안전)
# 설치 불필요 — 에이전트가 완료 전 직접 실행

set -uo pipefail

cd "$(git rev-parse --show-toplevel)"

TARGET="${1:-all}"
FAILED=0
SKIPPED=0

echo "[pre-complete] SectorFlow 완료 전 기계적 검증 시작 (대상: $TARGET)"
echo "[pre-complete] ------------------------------------------------"

# ─── 백엔드 검증 ───
run_backend() {
    if [ ! -f ".venv/bin/python" ]; then
        echo "[pre-complete] ⚠️ .venv 없음 — 백엔드 검증 생략"
        SKIPPED=$((SKIPPED + 1))
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

    echo "[pre-complete] [3/4] 런타임 기동 검증 (RuntimeWarning 에러 승격)..."
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

    # 잔존 프로세스 확인 (0-1-3)
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

# ─── 프론트엔드 검증 ───
run_frontend() {
    if [ ! -f "frontend/package.json" ]; then
        echo "[pre-complete] ⚠️ frontend/package.json 없음 — 프론트엔드 검증 생략"
        SKIPPED=$((SKIPPED + 1))
        return 0
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

# ─── 실행 ───
case "$TARGET" in
    backend)  run_backend ;;
    frontend) run_frontend ;;
    all)      run_backend; run_frontend ;;
    *)
        echo "[pre-complete] ❌ 잘못된 대상: $TARGET (backend|frontend|all 중 하나)"
        exit 2
        ;;
esac

echo "[pre-complete] ------------------------------------------------"
if [ "$FAILED" -gt 0 ]; then
    echo "[pre-complete] ❌ 검증 실패 — ${FAILED}건 실패, ${SKIPPED}건 생략"
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
