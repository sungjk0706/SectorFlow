#!/bin/bash
# =============================================================================
# continuity-loop.sh — 연속성 루프 자동 재실행 스크립트
# =============================================================================
# 역할: Devin CLI SessionEnd 훅이 호출. 세션 종료 시 조사 상태 파일을 확인하여
#       남은 작업이 있으면 다음 세션을 자동으로 실행 (devin -p --prompt-file).
#       완료/중단/STOP 파일 감지 시 루프 종료.
#
# 호출 시점: .devin/hooks.v1.json 의 SessionEnd 훅
# stdin: 훅 이벤트 JSON (reason 등) — 본 스크립트는 사용하지 않음
#
# 실행 순서 (종료 조건을 devin 의존성 체크보다 먼저):
#   1. 상태 파일 없음 → 종료 (의존성 불필요)
#   2. STOP 파일 있음 → 종료 (의존성 불필요)
#   3. jq 없음 → 종료 (파싱 불가)
#   4. 상태 파싱 → 종료 조건 확인 (done/aborted/remaining=0/max_sessions) → 해당 시 종료
#   5. 여기까지 통과 = 다음 세션 실행 필요 → devin CLI 체크
#   6. continue.md 생성 → devin -p 백그라운드 실행
#
# 안전장치:
#   1. STOP 파일 존재 시 즉시 종료
#   2. status == "done" 또는 "aborted" 시 종료
#   3. remaining == 0 시 종료
#   4. session_count >= max_sessions 시 종료
#   5. devin CLI 없으면 종료 (사용자 안내만) — 종료 조건 통과 후에만 체크
#   6. jq 없으면 종료 (사용자 안내만)
#   7. nohup + 백그라운드 실행 (훅 블로킹 방지)
# =============================================================================

set -u  # 미정의 변수 오류

# --- 경로 설정 (스크립트 위치 기준 상대 경로 계산) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$DEVIN_DIR/.." && pwd)"
STATE_DIR="$DEVIN_DIR/state"

STATE_FILE="$STATE_DIR/investigation_status.json"
STATE_BAK="$STATE_DIR/investigation_status.json.bak"
STOP_FILE="$STATE_DIR/STOP"
CONTINUE_FILE="$STATE_DIR/continue.md"
LOG_DIR="$STATE_DIR/logs"

# --- 로그 설정 ---
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/loop_$(date +%Y%m%d_%H%M%S).log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# =============================================================================
# 1단계: 상태 파일 존재 확인 (의존성 불필요)
# =============================================================================
if [ ! -f "$STATE_FILE" ]; then
  log "상태 파일 없음. 루프 종료 (조사 미실행 또는 완료 후 정리됨)."
  exit 0
fi

# =============================================================================
# 2단계: STOP 파일 확인 (비상 정지, 의존성 불필요)
# =============================================================================
if [ -f "$STOP_FILE" ]; then
  log "STOP 파일 감지. 루프 즉시 종료."
  log "STOP 파일 제거 후 재시작하려면: rm $STOP_FILE"
  exit 0
fi

# =============================================================================
# 3단계: jq 의존성 확인 (상태 파싱에 필요)
# =============================================================================
if ! command -v jq >/dev/null 2>&1; then
  log "ERROR: jq 가 설치되어 있지 않음. 'brew install jq' 로 설치 후 재시도."
  exit 1
fi

# =============================================================================
# 4단계: 상태 파일 파싱 및 종료 조건 확인 (devin 불필요)
# =============================================================================
STATUS="$(jq -r '.status // "unknown"' "$STATE_FILE" 2>/dev/null)"
REMAINING_COUNT="$(jq -r '.remaining | length' "$STATE_FILE" 2>/dev/null)"
SESSION_COUNT="$(jq -r '.session_count // 0' "$STATE_FILE" 2>/dev/null)"
MAX_SESSIONS="$(jq -r '.max_sessions // 30' "$STATE_FILE" 2>/dev/null)"
TOPIC="$(jq -r '.topic // "조사"' "$STATE_FILE" 2>/dev/null)"

log "상태 확인: status=$STATUS, remaining=$REMAINING_COUNT, session=$SESSION_COUNT/$MAX_SESSIONS, topic=$TOPIC"

# 파싱 실패 시 종료
if [ "$STATUS" = "unknown" ] || [ "$REMAINING_COUNT" = "null" ]; then
  log "ERROR: 상태 파일 파싱 실패. 백업에서 복구 필요: $STATE_BAK"
  if [ -f "$STATE_BAK" ]; then
    log "백업 파일 존재: $STATE_BAK"
  fi
  exit 1
fi

# 종료 조건: done
if [ "$STATUS" = "done" ]; then
  log "조사 완료 상태 (status=done). 루프 종료."
  exit 0
fi

# 종료 조건: aborted
if [ "$STATUS" = "aborted" ]; then
  log "조사 중단 상태 (status=aborted). 루프 종료."
  exit 0
fi

# 종료 조건: remaining == 0
if [ "$REMAINING_COUNT" = "0" ]; then
  log "남은 조사 대상 0건. 루프 종료 (완료 처리는 마지막 세션이 담당)."
  exit 0
fi

# 종료 조건: max_sessions 초과
if [ "$SESSION_COUNT" -ge "$MAX_SESSIONS" ]; then
  log "최대 세션 수 도달 ($SESSION_COUNT >= $MAX_SESSIONS). 루프 강제 종료."
  log "계속하려면 상태 파일의 max_sessions 값을 증가시키세요: $STATE_FILE"
  # STOP 파일 생성하여 향후 재실행도 차단
  touch "$STOP_FILE"
  exit 0
fi

# =============================================================================
# 5단계: devin CLI 의존성 확인 (다음 세션 실행에 필요 — 종료 조건 통과 후에만)
# =============================================================================
if ! command -v devin >/dev/null 2>&1; then
  log "ERROR: devin CLI 가 PATH 에 없음. 자동 재실행 불가."
  log "수동 이어하기: 새 세션에서 '이어서 해줘' 입력"
  log "또는 Devin CLI 설치 후 다음 세션 종료 시 자동 재개"
  exit 1
fi

# =============================================================================
# 6단계: 다음 세션용 프롬프트 파일 생성 및 자동 실행
# =============================================================================
cat > "$CONTINUE_FILE" <<EOF
investigation_status.json 을 읽고 중단된 지점부터 다음 배치를 조사해줘.
continuity-investigation 스킬 절차를 따라. 주제: $TOPIC.
절차: 1-1(상태 복원) → 2(배치 조사) → 3(완료 시 보고서) 순서.
EOF

log "다음 세션 프롬프트 생성: $CONTINUE_FILE"

# 백그라운드 실행 (훅 블로킹 방지)
# --permission-mode bypass: 조사는 읽기/grep/glob 중심이므로 자동 승인 안전.
# --prompt-file: continue.md 에서 프롬프트 로드.
# nohup + &: 훅이 블로킹되지 않도록 백그라운드 실행.
NEXT_LOG="$LOG_DIR/session_$(date +%Y%m%d_%H%M%S).log"

log "다음 세션 실행: devin -p --prompt-file $CONTINUE_FILE --permission-mode bypass"
log "세션 로그: $NEXT_LOG"

nohup devin -p --prompt-file "$CONTINUE_FILE" \
  --permission-mode bypass \
  --respect-workspace-trust false \
  > "$NEXT_LOG" 2>&1 &

NEXT_PID=$!
log "다음 세션 PID: $NEXT_PID"
log "비상 정지: touch $STOP_FILE"

exit 0
