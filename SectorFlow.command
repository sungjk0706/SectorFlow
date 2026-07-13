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
_prev_pids=$(lsof -ti:8000 -ti:5173 2>/dev/null)
if [ -n "$_prev_pids" ]; then
    echo "$_prev_pids" | xargs kill -15 2>/dev/null
    # 프로세스가 실제로 종료될 때까지 대기 (최대 1초)
    _wait=0
    while [ $_wait -lt 10 ]; do
        _alive=$(lsof -ti:8000 -ti:5173 2>/dev/null)
        if [ -z "$_alive" ]; then
            break
        fi
        sleep 0.1
        _wait=$((_wait+1))
    done
    # 2. 그래도 살아있으면 강제 종료 (SIGKILL)
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    lsof -ti:5173 | xargs kill -9 2>/dev/null
fi

rm -f backend/data/server.lock
rm -f /tmp/sectorflow.lock

# 백엔드 + 프론트엔드 병렬 실행 (양쪽 ready 후 브라우저 오픈)
echo "백엔드 및 프론트엔드 동시 준비 중..."
.venv/bin/python main.py &
BACKEND_PID=$!

(cd frontend && npm run dev) &
FRONTEND_PID=$!

# 양쪽 준비 대기 (병렬, 0.2초 간격 — 백엔드+프론트엔드 모두 ready 후 브라우저 오픈)
# 백엔드가 먼저 준비되어야 프론트엔드 healthCheck()가 Vite 프록시를 통해
# ECONNREFUSED 없이 첫 시도에 성공 → http proxy error 로그 미발생
MAX_RETRIES=150
RETRY=0
BACKEND_READY=false
FRONTEND_READY=false
while [ $RETRY -lt $MAX_RETRIES ]; do
    if [ "$BACKEND_READY" = false ] && curl -s --connect-timeout 1 --max-time 2 http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✅ 백엔드 준비 완료"
        BACKEND_READY=true
    fi
    if [ "$FRONTEND_READY" = false ] && curl -s --connect-timeout 1 --max-time 2 http://localhost:5173 > /dev/null 2>&1; then
        echo "✅ 프론트엔드 준비 완료"
        FRONTEND_READY=true
    fi
    if [ "$BACKEND_READY" = true ] && [ "$FRONTEND_READY" = true ]; then
        break
    fi
    sleep 0.2
    RETRY=$((RETRY+1))
done

if [ "$FRONTEND_READY" = false ]; then
    echo "⚠️ 프론트엔드 타임아웃, 그래도 계속 진행..."
fi

if [ "$BACKEND_READY" = false ]; then
    echo "⚠️ 백엔드 타임아웃 — 프론트엔드 healthCheck에서 자동 재시도 중..."
fi

# 브라우저 열기 (Safari) — 백엔드 준비 확인 후
# 백엔드가 ready 상태이므로 프론트엔드 healthCheck()가 첫 시도에 성공 → proxy error 없음
# 기존 localhost:5173 탭을 닫고 새로 열어 Safari 캐시/bfcache로 인한 이전 코드 잔존 방지
# 주의: Safari가 꺼져 있을 때 osascript "tell application Safari"가 Safari를 강제 기동하여
#       시작 페이지 탭이 추가로 열리므로, 이미 실행 중인 경우에만 기존 탭 닫기 수행
if pgrep -x "Safari" > /dev/null 2>&1; then
    osascript -e 'tell application "Safari" to close every tab in every window where URL starts with "http://localhost:5173"' 2>/dev/null
fi
open -a "Safari" http://localhost:5173

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
    trap - SIGINT SIGTERM EXIT
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

# 백엔드 종료 대기 — 브라우저 닫기 → 백엔드 graceful shutdown → 여기서 반환
wait $BACKEND_PID

# 정상 종료 경로 — trap 해제 후 프론트엔드 종료
trap - SIGINT SIGTERM EXIT
kill -15 $FRONTEND_PID 2>/dev/null
wait $FRONTEND_PID 2>/dev/null
exit 0