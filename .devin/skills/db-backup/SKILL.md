---
name: db-backup
description: DB 마이그레이션 전 stocks.db 백업
allowed-tools:
  - exec
  - read
  - write
---

## 사용자 전제 (필수)
- **사용자는 코딩 지식이 전혀 없음.** UI 기준 일반 용어로만 소통. 기술 명령어 안내 금지. 에이전트가 직접 실행.
- **승인 전 코드 수정 절대 금지 (AGENTS.md 섹션3 규칙0 준수).** 사용자가 "진행해/수정해/구현해/적용해/go" 등 명시적 실행 지시어를 준 경우에만 수정. 분석/조사/계획/추천까지만 수행하고 대기.

## DB 백업 절차

### 1. 앱 종료
- 백엔드가 실행 중이면 먼저 안전 종료 (`kill -15 <PID>`)
- `lsof -ti:8000` 등으로 프로세스 확인

### 2. 백업 파일 생성
```bash
# 타임스탬프 생성
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

cp backend/data/stocks.db "backend/data/stocks.db.${TIMESTAMP}.backup"
cp backend/data/stocks.db-shm "backend/data/stocks.db-shm.${TIMESTAMP}.backup" 2>/dev/null || true
cp backend/data/stocks.db-wal "backend/data/stocks.db-wal.${TIMESTAMP}.backup" 2>/dev/null || true
```

### 3. 백업 검증
- `ls -lh backend/data/*.backup` 결과 확인
- `stocks.db` 백업 파일 크기가 0보다 큰지 확인
- 백업 파일 3개(`stocks.db`, `db-shm`, `db-wal`) 모두 존재 여부 확인

### 4. 복원 절차 (문제 발생 시)
```bash
# 가장 최근 백업 찾기
LATEST=$(ls -t backend/data/stocks.db.*.backup | head -1 | sed 's/\.backup$//')

# 원래 파일로 복원
cp "${LATEST}.backup" "backend/data/stocks.db"
cp "${LATEST}-shm.backup" "backend/data/stocks.db-shm" 2>/dev/null || true
cp "${LATEST}-wal.backup" "backend/data/stocks.db-wal" 2>/dev/null || true
```

### 5. 완료 보고
- 백업 파일명
- 파일 크기
- 백업 시점

⚠️ DB 백업이 확인되기 전에는 절대 마이그레이션/스키마 변경/테이블 삭제를 진행하지 마라.
