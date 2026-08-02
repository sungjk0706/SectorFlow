#!/usr/bin/env bash
# SectorFlow pre-commit hook — 커밋 전 자동 검증 (하네스 엔지니어링)
# AGENTS.md 금지 패턴 + 아키텍처 원칙을 커밋 시점에 자동 강제
# 설치: cp scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# 또는: ln -sf ../../scripts/pre-commit.sh .git/hooks/pre-commit

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "[pre-commit] SectorFlow 자동 검증 시작..."

# 1. Python 린트 (Ruff) — 금지 패턴 5개 + dead code 자동 검사
if [ -f ".venv/bin/ruff" ]; then
    echo "[pre-commit] Ruff 린트 검사..."
    if ! .venv/bin/ruff check backend/app/; then
        echo "[pre-commit] ❌ Ruff 검사 실패 — 금지 패턴 또는 dead code 발견"
        echo "[pre-commit] 자동 수정 가능 항목: .venv/bin/ruff check backend/app/ --fix"
        echo "[pre-commit] 더 자세한 내용: AGENTS.md 섹션2 '금지 패턴 5개' + ARCHITECTURE.md W1/W6/W8"
        exit 1
    fi
    echo "[pre-commit] ✅ Ruff 통과"
else
    echo "[pre-commit] ⚠️ Ruff 미설치 — 린트 검사 생략"
fi

# 2. Frontend 타입체크 — 변경된 프론트엔드 파일이 있을 때만
frontend_changed=$(git diff --cached --name-only --diff-filter=ACM | grep "^frontend/" || true)
if [ -n "$frontend_changed" ]; then
    echo "[pre-commit] Frontend 타입체크..."
    if ! (cd frontend && npm run typecheck 2>&1); then
        echo "[pre-commit] ❌ Frontend 타입체크 실패"
        echo "[pre-commit] 더 자세한 내용: AGENTS.md 섹션2 '코드 수정 시 점검 체크리스트 — 프론트엔드'"
        exit 1
    fi
    echo "[pre-commit] ✅ Frontend 타입체크 통과"
fi

# 3. DB 파일 직접 커밋 차단 (안전 규칙 1 — stocks.db 삭제/덮어쓰기 금지)
db_files=$(git diff --cached --name-only --diff-filter=ACMR | grep -E "\.(db|db-shm|db-wal|db-journal)$" || true)
if [ -n "$db_files" ]; then
    echo "[pre-commit] ❌ DB 파일 커밋 시도 감지 — 안전 규칙 1 위반"
    echo "[pre-commit] 감지 파일: $db_files"
    echo "[pre-commit] DB 파일은 git 추적 대상이 아님 — 스테이징에서 제거하세요"
    echo "[pre-commit] 더 자세한 내용: AGENTS.md 섹션2 '안전 규칙' 1번 + db-backup 스킬"
    exit 1
fi

# 4. 증권사별 코드가 공통 로직에 침투하는지 검사 (P4) — 신규 추가 라인만
broker_leak=$(git diff --cached --name-only --diff-filter=ACM | grep -E "^backend/app/(services|pipelines|web)/.*\.py$" || true)
if [ -n "$broker_leak" ]; then
    # 스테이징된 변경 사항에서 신규 추가된 kiwoom_/ls_ import만 검사 (기존 코드는 무시)
    broker_imports=$(git diff --cached | grep -E "^\+.*from backend\.app\.core\.(kiwoom|ls)_.*import" || true)
    if [ -n "$broker_imports" ]; then
        echo "[pre-commit] ❌ P4 위반 — 신규 추가된 증권사별 모듈 직접 import 감지"
        echo "$broker_imports"
        echo "[pre-commit] 레지스트리 패턴(broker_factory/broker_registry) 경유 필수"
        echo "[pre-commit] 더 자세한 내용: AGENTS.md 섹션2 P4 + ARCHITECTURE.md '불변 원칙 25개' P4"
        exit 1
    fi
fi

# 5. 동기 I/O 신규 사용 차단 (P1-P3) — Python 파일의 신규 추가 라인만 (주석 제외)
py_files_changed=$(git diff --cached --name-only --diff-filter=ACM | grep "\.py$" || true)
if [ -n "$py_files_changed" ]; then
    sync_io_new=$(git diff --cached -- "*.py" | grep -E "^\+[^#]" | grep -E "(import requests|from requests|import sqlite3|from sqlite3|from time import sleep|.*time\.sleep)" || true)
else
    sync_io_new=""
fi
if [ -n "$sync_io_new" ]; then
    echo "[pre-commit] ❌ P1-P3 위반 — 신규 동기 I/O 사용 감지"
    echo "$sync_io_new"
    echo "[pre-commit] async I/O(httpx, aiosqlite, asyncio.sleep) 사용 필수"
    echo "[pre-commit] 더 자세한 내용: AGENTS.md 섹션2 P1-P3 + ARCHITECTURE.md '불변 원칙 25개' P1~P3"
    exit 1
fi

# 6. asyncio.run() 신규 사용 차단 (금지 패턴 1) — Python 파일의 신규 추가 라인만
if [ -n "$py_files_changed" ]; then
    asyncio_run_new=$(git diff --cached -- "*.py" | grep -E "^\+[^#].*asyncio\.run\(" || true)
else
    asyncio_run_new=""
fi
if [ -n "$asyncio_run_new" ]; then
    echo "[pre-commit] ❌ 금지 패턴 1 — 신규 asyncio.run() 사용 감지"
    echo "$asyncio_run_new"
    echo "[pre-commit] 더 자세한 내용: AGENTS.md 섹션2 '금지 패턴 5개' 1번째 + ARCHITECTURE.md W1"
    exit 1
fi

# 7. DB 파일 삭제 코드 신규 추가 차단 (안전 규칙 1) — Python 파일의 신규 추가 라인만
if [ -n "$py_files_changed" ]; then
    db_remove_new=$(git diff --cached -- "*.py" | grep -E "^\+[^#].*(os\.remove|os\.unlink|shutil\.rmtree)" | grep -iE "\.db|stocks" || true)
else
    db_remove_new=""
fi
if [ -n "$db_remove_new" ]; then
    echo "[pre-commit] ❌ 안전 규칙 1 위반 — 신규 DB 파일 삭제 코드 감지"
    echo "$db_remove_new"
    echo "[pre-commit] stocks.db 삭제/덮어쓰기 금지 — 백업은 db-backup 스킬 사용"
    echo "[pre-commit] 더 자세한 내용: AGENTS.md 섹션2 '안전 규칙' 1번 + db-backup 스킬"
    exit 1
fi

echo "[pre-commit] ✅ 모든 검증 통과 — 커밋 진행"
exit 0
