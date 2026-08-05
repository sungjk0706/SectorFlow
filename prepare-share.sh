#!/bin/bash
# SectorFlow 공유용 패키지 준비 (프로젝트 소유자용)
# 백엔드 종료 후 실행하세요.
#
# 사용법:
#   1. SectorFlow 앱 종료 (백엔드·프론트엔드 모두)
#   2. ./prepare-share.sh
#   3. 생성된 SectorFlow-share/ 폴더를 zip 으로 압축하여 공유

set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  SectorFlow 공유 패키지 준비"
echo "============================================"
echo ""

# 백엔드 실행 중 확인
if lsof -ti:8000 >/dev/null 2>&1; then
    echo "[오류] 백엔드가 실행 중입니다. 먼저 앱을 종료해 주세요."
    exit 1
fi

SHARE_DIR="SectorFlow-share"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 기존 공유 폴더 제거
rm -rf "$SHARE_DIR"
mkdir -p "$SHARE_DIR"

echo "프로젝트 파일 복사 중..."
# .git, .venv, node_modules, __pycache__ 등 제외
rsync -a --progress \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='frontend/node_modules' \
    --exclude='frontend/dist' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='.hypothesis' \
    --exclude='htmlcov' \
    --exclude='.coverage' \
    --exclude='*.log' \
    --exclude='.DS_Store' \
    --exclude='HANDOVER.md' \
    --exclude='.windsurf' \
    --exclude='.devin' \
    ./ "$SHARE_DIR/"

echo ""
echo "DB 사본 생성 중..."
# DB 백업 (안전 규칙: 원본 유지, 사본만 생성)
mkdir -p "$SHARE_DIR/backend/data"
cp backend/data/stocks.db "$SHARE_DIR/backend/data/stocks.db"
if [ -f backend/data/stocks.db-shm ]; then
    cp backend/data/stocks.db-shm "$SHARE_DIR/backend/data/stocks.db-shm"
fi
if [ -f backend/data/stocks.db-wal ]; then
    cp backend/data/stocks.db-wal "$SHARE_DIR/backend/data/stocks.db-wal"
fi

echo ""
echo "불필요한 lock 파일 제거..."
rm -f "$SHARE_DIR/backend/data/server.lock" 2>/dev/null || true
rm -f "$SHARE_DIR/backend/data/"*.lock 2>/dev/null || true

echo ""
echo "============================================"
echo "  공유 패키지 준비 완료"
echo "============================================"
echo ""
echo "  위치: $SHARE_DIR/"
echo "  크기: $(du -sh "$SHARE_DIR" | cut -f1)"
echo ""
echo "  다음 단계:"
echo "    1. zip -r SectorFlow-share.zip $SHARE_DIR/"
echo "    2. zip 파일을 지인에게 전달"
echo "    3. 지인은 SETUP-WINDOWS.md 참고하여 설치"
echo ""
echo "  주의: .env 파일이 포함되어 있습니다."
echo "        ENCRYPTION_KEY 가 함께 전달되므로 주의하세요."
echo "        지인은 본인의 증권사 API 키로 교체해야 합니다."
echo ""
