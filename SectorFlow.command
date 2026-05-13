#!/bin/bash
cd "$(dirname "$0")"

echo "============================================"
echo "  SectorFlow 실행 중..."
echo "============================================"

# 가상환경 활성화
source .venv/bin/activate

# ---------------------------------------------------------
# [개선 1] 이전 프로세스 안전 종료 (Graceful Shutdown)
# ---------------------------------------------------------
echo "이전 프로세스 정리 중..."
# 1. 부드러운 종료 요청 (SIGTERM)
lsof -ti:8000 | xargs kill -15 2>/dev/null
lsof -ti:5173 | xargs kill -15 2>/dev/null
# 장부 정리할 시간(2초) 부여
sleep 2 
# 2. 그래도 살아있으면 강제 종료 (SIGKILL)
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
echo "  🛑 종료하려면 터미널 창을 닫거나 Ctrl+C를 누르세요."
echo "============================================"

# ---------------------------------------------------------
# [개선 2] 터미널 종료 시 자식 프로세스 동반 안전 종료 (Trap)
# ---------------------------------------------------------
cleanup() {
    echo ""
    echo "🛑 SectorFlow 안전 종료 중... (Graceful Shutdown)"
    kill -15 $BACKEND_PID 2>/dev/null
    kill -15 $FRONTEND_PID 2>/dev/null
    # 완전히 꺼질 때까지 대기
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "✅ 모든 프로세스가 안전하게 종료되었습니다."
    exit 0
}

# SIGINT(Ctrl+C), SIGTERM, EXIT 신호가 오면 cleanup 함수 실행
trap cleanup SIGINT SIGTERM EXIT

# 백그라운드 프로세스 유지
wait