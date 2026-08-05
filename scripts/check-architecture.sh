#!/usr/bin/env bash
# SectorFlow 아키텍처 검사 — 의존성 방향 + 증권사 코드 격리 (하네스 엔지니어링)
# AGENTS.md P4(증권사명 침투 금지) + 계층 구조(core → services → pipelines → web) 강제
# pre-commit hook에서 호출됨

set -uo pipefail
for required_command in git grep; do
    command -v "$required_command" >/dev/null 2>&1 || {
        echo "[아키텍처] ❌ 필수 실행 환경이 없습니다: $required_command"
        exit 1
    }
done
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

exit_code=0
scope="backend/app/core, backend/app/services, backend/app/pipelines, backend/app/web"

usage() {
    cat <<'EOF'
사용법:
  check-architecture.sh [--scope 설명]

옵션 없이 실행하면 전수 스캔으로 모든 위반을 출력하고, 위반이 있으면 종료 코드 1로 끝납니다.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --scope)
            [[ $# -ge 2 ]] || { echo "[아키텍처] ❌ --scope 뒤에 설명이 필요합니다."; exit 2; }
            scope="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[아키텍처] ❌ 알 수 없는 옵션: $1"
            usage >&2
            exit 2
            ;;
    esac
done

echo "[아키텍처] 확인 범위: $scope"

# ── P4: 공통 로직에서 증권사별 모듈 직접 import 금지 ──────────────────────────
# 허용: core/kiwoom_*.py, core/ls_*.py, core/broker_registry.py, core/broker_factory.py
# 금지: services/, pipelines/, web/에서 core/kiwoom_* 또는 core/ls_* 직접 import
broker_violations=$(grep -rn "from backend\.app\.core\.\(kiwoom\|ls\)_" backend/app/services/ backend/app/pipelines/ backend/app/web/ --include="*.py" 2>/dev/null || true)

if [ -n "$broker_violations" ]; then
    echo "[아키텍처] ❌ P4 위반 — 공통 로직에서 증권사별 모듈 직접 import 감지"
    echo "$broker_violations"
    echo "[아키텍처] 레지스트리 패턴(broker_factory/broker_registry) 경유해야 함"
    exit_code=1
fi

# ── 계층 구조: core/ → services/ 역방향 import 감지 ────────────────────────────
# core/는 services/를 import하면 안 됨 (의존성 방향: core ← services)
reverse_deps=$(grep -rn "from backend\.app\.services" backend/app/core/ --include="*.py" 2>/dev/null || true)

if [ -n "$reverse_deps" ]; then
    echo "[아키텍처] ⚠️  의존성 방향 경고 — core/에서 services/ import 감지"
    echo "$reverse_deps"
    echo "[아키텍처] core/는 services/에 의존하지 않아야 함 (계층: core ← services)"
    # 경고만 하고 통과 (기존 3건 존재 — 별도 리팩토링 태스크에서 처리)
fi

# ── 동기 I/O 금지 (P1-P3): requests, sqlite3, time.sleep ───────────────────────
sync_io=$(grep -rn "^\(import requests\|from requests\|import sqlite3\|from sqlite3\|from time import sleep\|time\.sleep\)" backend/app/ --include="*.py" 2>/dev/null || true)

if [ -n "$sync_io" ]; then
    echo "[아키텍처] ❌ P1-P3 위반 — 동기 I/O 라이브러리 사용 감지"
    echo "$sync_io"
    echo "[아키텍처] async I/O(httpx, aiosqlite, asyncio.sleep) 사용 필수"
    exit_code=1
fi

# ── asyncio.run() 금지 (금지 패턴 1) ──────────────────────────────────────────
asyncio_run=$(grep -rn "asyncio\.run(" backend/app/ --include="*.py" 2>/dev/null || true)

if [ -n "$asyncio_run" ]; then
    echo "[아키텍처] ❌ 금지 패턴 1 — asyncio.run() 사용 감지"
    echo "$asyncio_run"
    exit_code=1
fi

# ── DB 파일 보호 (안전 규칙 1) — os.remove/unlink가 DB 경로 건드리는지 검사 ────
db_remove=$(grep -rn "os\.remove\|os\.unlink\|shutil\.rmtree" backend/app/ --include="*.py" 2>/dev/null | grep -iE "\.db|stocks" || true)

if [ -n "$db_remove" ]; then
    echo "[아키텍처] ❌ 안전 규칙 1 위반 — DB 파일 삭제 코드 감지"
    echo "$db_remove"
    echo "[아키텍처] stocks.db 삭제/덮어쓰기 금지 — 백업은 db-backup 스킬 사용"
    exit_code=1
fi

if [ $exit_code -eq 0 ]; then
    echo "[아키텍처] ✅ 아키텍처 검사 통과"
fi

exit $exit_code
