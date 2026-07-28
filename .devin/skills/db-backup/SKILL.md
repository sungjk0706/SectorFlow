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
- 종료 후 잔존 프로세스 0건 확인 (AGENTS.md 0-1-3 준수)

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
> **사용자 보고 의무 (AGENTS.md 섹션3 규칙 0-8 준수)**: 모든 보고는 UI 기준 일반 용어 + P10~P25 부합 여부 명시. 보고서 형식은 `AGENTS.md` 섹션3 '작업 완료 보고서 표준 형식 (필수 포함 표)'을 따른다. 위반 시 규칙 0-6 동일 강제성.

- **변경 내용 표**에 백업 항목:
  - 백업 파일명, 파일 크기, 백업 시점
  - 복원 절차 적용 여부(문제 발생 시)
- **검증 결과 표**에 백업 검증 항목:
  - `ls -lh backend/data/*.backup` 결과
  - 3개 파일(`.db`, `-shm`, `-wal`) 존재
  - `stocks.db` 백업 파일 크기 0보다 큼
- **최종 판별 표**에 안전 규칙 준수: 원본 `.db` 파일 삭제 금지, 삭제는 사용자 승인 + 런타임 검증 후.

⚠️ DB 백업이 확인되기 전에는 절대 마이그레이션/스키마 변경/테이블 삭제를 진행하지 마라.

### 6. 백업 파일 삭제 (마이그레이션 검증 완료 시 — AGENTS.md 섹션3 규칙 10 (2)항 준수)
마이그레이션/스키마 변경 작업 완료 후 런타임 검증(AGENTS.md 0-1-2 표준 검증 절차) 이상 없으면, 생성한 타임스탬프 백업 파일을 삭제.
- **삭제 조건**: 마이그레이션 후 런타임 기동 정상 + 핵심 데이터 조회 이상 없음 확인 후
- **삭제 대상**: `backend/data/stocks.db.*.backup`, `backend/data/stocks.db-shm.*.backup`, `backend/data/stocks.db-wal.*.backup` (원본 `.db` 파일 절대 삭제 금지 — 안전 규칙 1)
- **승인**: 삭제 전 사용자 승인 필수 (AGENTS.md 규칙 0 — 파일 삭제는 코드 제거와 동일 취급)
- **커밋**: 삭제는 다음 커밋에 포함하거나 검증 완료 보고 시 사용자 승인 후 별도 삭제

## 작업 중 발견 문제 기록 의무
- 메인 작업 도중 발견한 아키텍처 위반(P원칙), 오류, 잠재적 버그, dead code, 폴백 패턴, 아키텍처 원칙에 부합하는 더 나은 구조(개선점) 등은 즉시 `HANDOVER.md` "미해결 문제" 섹션에 기록 (파일:줄, 위반/부합 원칙 번호, 증상/개선내용). 사용자 승인 불필요 — 발견 즉시 기록. 상세 규칙은 AGENTS.md 섹션4 규칙 9 참조.
