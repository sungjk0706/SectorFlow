---
name: db-backup
description: DB 마이그레이션 전 stocks.db 백업
allowed-tools:
  - exec
  - read
  - write
---

## 사용자 전제 (필수)
> **공통 전제 (승인 전 수정 금지·사용자 소통·보고·오류 알림 의무·작업 시작 전 아키텍처 판정 필수·완료 보고 봉인)**: problem-solve 스킬 "사용자 전제" 섹션 (.devin/skills/problem-solve/SKILL.md) 참조. 단, 오류·위험 알림 의무는 DB 특성상 **DB 삭제·덮어쓰기 위험 시 즉시 알림**으로 더 엄격 적용 (docs/절차규칙/절차규칙_조사_상세.md 규칙 0-9), 아키텍처 판정 게이트는 **DB 관련 변경 전** 수행.

## DB 백업 절차

### 1. 앱 종료
- 백엔드가 실행 중이면 먼저 안전 종료 (`kill -15 <PID>`)
- `lsof -ti:8000` 등으로 프로세스 확인
- 종료 후 잔존 프로세스 0건 확인 (docs/절차규칙/절차규칙_조사_상세.md 0-1-3 준수)

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
> **사용자 보고 의무**: docs/절차규칙/절차규칙_조사_상세.md 규칙 0-8 준수 (UI 기준 일반 용어 + P1~P25 부합 여부 + 보고서 형식은 docs/절차규칙/절차규칙_보고_상세.md '작업 완료 보고서 표준 형식' 참조). 오류·위험 발견 시 규칙 0-9(오류·위험 알림 의무) 준수.
> **보조 도구 추가 행 원칙 (docs/절차규칙/절차규칙_보고_상세.md 0.3 준수)**: 임의 표 생성 금지. 기존 표의 새 행으로만 추가하며, 행 제목은 "DB백업: 항목명" 형식. 추가 행도 2칸 구조(`항목 | 내용`) 준수.

- **변경 내용 표**에 DB백업 추가 행 (행 제목: "DB백업: <항목명>"):
  - DB백업: 백업 파일 — 백업 파일명, 파일 크기, 백업 시점
  - DB백업: 복원 절차 적용 여부 — 문제 발생 시
- **검증 결과 표**에 DB백업 추가 행 (행 제목: "DB백업: <항목명>"):
  - DB백업: 백업 파일 목록 — `ls -lh backend/data/*.backup` 결과
  - DB백업: 3개 파일 존재 — `.db`, `-shm`, `-wal` 파일 존재 여부
  - DB백업: 백업 파일 크기 — `stocks.db` 백업 파일 크기 0보다 큼
- **최종 판별 표**에 안전 규칙 준수: 원본 `.db` 파일 삭제 금지, 삭제는 사용자 승인 + 런타임 검증 후.
- **검증·관찰 계층 게이트 (위험도 '중간' — docs/절차규칙/절차규칙_세션절차_상세.md "검증·관찰 계층 게이트" 준수)**: DB 마이그레이션·스키마 변경은 위험도 '중간' — 사전 롤백 필수, 독립 검증·관찰 권장. **사전 롤백 트리거**: 마이그레이션 후 런타임 기동 실패·핵심 데이터 조회 불일치·기동 시 대조(reconciliation) 차단 발생 시, 백업 파일로 복원 절차를 태스크 파일에 사전 정의. 백업 파일 자체가 롤백 수단이므로 검증 완료 전까지 삭제 금지.

⚠️ DB 백업이 확인되기 전에는 절대 마이그레이션/스키마 변경/테이블 삭제를 진행하지 마라.

### 6. 백업 파일 삭제 (마이그레이션 검증 완료 시 — docs/절차규칙/절차규칙_컨텍스트관리_상세.md 규칙 10 (2)항 준수)
마이그레이션/스키마 변경 작업 완료 후 런타임 검증(docs/절차규칙/절차규칙_조사_상세.md 0-1-2 표준 검증 절차) 이상 없으면, 생성한 타임스탬프 백업 파일을 삭제.
- **삭제 조건**: 마이그레이션 후 런타임 기동 정상 + 핵심 데이터 조회 이상 없음 확인 후
- **삭제 대상**: `backend/data/stocks.db.*.backup`, `backend/data/stocks.db-shm.*.backup`, `backend/data/stocks.db-wal.*.backup` (원본 `.db` 파일 절대 삭제 금지 — 안전 규칙 1)
- **승인**: 삭제 전 사용자 승인 필수 (docs/절차규칙/절차규칙_조사_상세.md 규칙 0 — 파일 삭제는 코드 제거와 동일 취급)
- **커밋**: 삭제는 다음 커밋에 포함하거나 검증 완료 보고 시 사용자 승인 후 별도 삭제

## 작업 중 발견 문제 기록 의무
docs/절차규칙/절차규칙_컨텍스트관리_상세.md 규칙 9 준수 — 발견 즉시 `HANDOVER.md` "미해결 문제"에 기록, 사용자 승인 불필요.
