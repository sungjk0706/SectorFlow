#!/bin/bash
cd "$(dirname "$0")"

echo "============================================"
echo "  SectorFlow 실행 중..."
echo "============================================"

# 가상환경 활성화
source .venv/bin/activate

# 사용하는 포트
BACKEND_PORT=8000
FRONTEND_PORT=5173

BACKEND_PID=""
FRONTEND_PID=""

# ---------------------------------------------------------
# 터미널 종료 시 자식 프로세스 동반 안전 종료
# ---------------------------------------------------------
cleanup() {
    local code="${1:-0}"
    trap - SIGINT SIGTERM EXIT
    echo ""
    echo "SectorFlow 안전 종료 중... (Graceful Shutdown)"
    if [ -n "$BACKEND_PID" ]; then
        kill -15 $BACKEND_PID 2>/dev/null
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill -15 $FRONTEND_PID 2>/dev/null
    fi
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "모든 프로세스가 안전하게 종료되었습니다."
    exit "$code"
}

# ---------------------------------------------------------
# 이전 프로세스 안전 종료 (Graceful Shutdown)
# ---------------------------------------------------------
echo "이전 프로세스 정리 중..."

kill_port() {
    local port=$1
    local pids
    pids=$(lsof -ti tcp:"$port" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -15 2>/dev/null
        local wait=0
        while [ $wait -lt 10 ]; do
            pids=$(lsof -ti tcp:"$port" 2>/dev/null)
            if [ -z "$pids" ]; then
                return 0
            fi
            sleep 0.1
            wait=$((wait+1))
        done
        pids=$(lsof -ti tcp:"$port" 2>/dev/null)
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill -9 2>/dev/null
        fi
    fi
}

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

rm -f backend/data/server.lock
rm -f /tmp/sectorflow.lock

# ---------------------------------------------------------
# 백엔드 + 프론트엔드 병렬 실행
# ---------------------------------------------------------
echo "백엔드 및 프론트엔드 동시 준비 중..."
.venv/bin/python main.py &
BACKEND_PID=$!

(cd frontend && npm run dev) &
FRONTEND_PID=$!

trap cleanup SIGINT SIGTERM EXIT

# 양쪽 준비 대기 (0.2초 간격, 최대 30초)
MAX_RETRIES=150
RETRY=0
BACKEND_READY=false
FRONTEND_READY=false
while [ $RETRY -lt $MAX_RETRIES ]; do
    if [ "$BACKEND_READY" = false ] && curl -s --connect-timeout 1 --max-time 2 "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
        echo "백엔드 준비 완료"
        BACKEND_READY=true
    fi
    if [ "$FRONTEND_READY" = false ] && curl -s --connect-timeout 1 --max-time 2 "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1; then
        echo "프론트엔드 준비 완료"
        FRONTEND_READY=true
    fi
    if [ "$BACKEND_READY" = true ] && [ "$FRONTEND_READY" = true ]; then
        break
    fi
    sleep 0.2
    RETRY=$((RETRY+1))
done

# 백엔드가 시작되지 않으면 매매 로직이 동작할 수 없으므로 중단
if [ "$BACKEND_READY" = false ]; then
    echo ""
    echo "백엔드가 정상적으로 시작되지 않았습니다."
    echo "로그를 확인한 후 다시 시도해 주세요."
    cleanup 1
fi

if [ "$FRONTEND_READY" = false ]; then
    echo "프론트엔드 준비가 지연되고 있습니다. 화면 확인 시 접속이 지연될 수 있습니다."
fi

echo ""
echo "============================================"
echo "  SectorFlow 실행 완료."
echo "============================================"
echo ""
echo "  브라우저에서 접속하세요:"
echo "     http://localhost:$FRONTEND_PORT"
echo ""
echo "  종료하려면 터미널 창을 닫거나 Ctrl+C를 누르세요."
echo "============================================"

# 백엔드 종료 대기 — 백엔드 graceful shutdown 시 cleanup이 먼저 실행되거나,
# 정상 종료 경로로 아래로 내려옴
wait $BACKEND_PID

# 정상 종료 경로 — trap 해제 후 프론트엔드 종료
trap - SIGINT SIGTERM EXIT
if [ -n "$FRONTEND_PID" ]; then
    kill -15 $FRONTEND_PID 2>/dev/null
    wait $FRONTEND_PID 2>/dev/null
fi
exit 0
