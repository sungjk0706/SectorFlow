#!/bin/bash
cd "$(dirname "$0")"

echo "============================================"
echo "  SectorFlow 실행 중..."
echo "============================================"

# 가상환경 활성화
source .venv/bin/activate

# 이전 프로세스 정리
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:5173 | xargs kill -9 2>/dev/null
rm -f backend/data/server.lock
rm -f /tmp/sectorflow.lock

# 백엔드 실행
python main.py &
BACKEND_PID=$!

# 백엔드 준비 대기 (포트 체크 방식)
echo "백엔드 준비 중..."
MAX_RETRIES=30
RETRY=0
while [ $RETRY -lt $MAX_RETRIES ]; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ 백엔드 준비 완료"
        break
    fi
    sleep 1
    RETRY=$((RETRY+1))
done

if [ $RETRY -eq $MAX_RETRIES ]; then
    echo "⚠️ 백엔드 타임아웃, 그래도 계속 진행..."
fi

# 프론트엔드 실행
cd frontend
npx vite &
FRONTEND_PID=$!
cd ..

# 프론트엔드 준비 대기 (포트 체크)
echo "프론트엔드 준비 중..."
RETRY=0
while [ $RETRY -lt $MAX_RETRIES ]; do
    if curl -s http://localhost:5173 > /dev/null 2>&1; then
        echo "✅ 프론트엔드 준비 완료"
        break
    fi
    sleep 1
    RETRY=$((RETRY+1))
done

# 브라우저 열기 (Chrome)
open -a "Google Chrome" http://localhost:5173

echo ""
echo "============================================"
echo "  ✅ SectorFlow 실행 완료!"
echo "============================================"
echo ""
echo "  🌐 브라우저에서 접속하세요:"
echo "     http://localhost:5173"
echo ""
echo "  🛑 종료하려면 이 터미널 창을 닫으세요"
echo "============================================"

wait