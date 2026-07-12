# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-13: 종목분류 페이지 업종관리 테이블 UI 개선 + 승인 규칙 강화**
  - **순번 컬럼 추가**: `frontend/src/pages/stock-classification.ts:106` MasterRow에 `seq: number | null` 필드 추가, `buildMasterRows()`에서 미분류 제외 1번부터 순차 부여, `masterColumns` 맨 앞에 36px 고정폭 순번 컬럼 삽입 (미분류 행은 빈 칸)
  - **통계 라벨 숫자 파란색 강조 + 미분류 제외**: `updateStatsLabel()` 단일 textContent → span 구조로 변경, 숫자+단위 부분만 COLOR.down(파랑) 강조, 업종 수 계산 시 미분류 제외, 전체 종목 수는 모든 종목 포함 유지
  - **"새 업종 추가" 버튼 md 사이즈 적용**: 작업 컬럼 버튼(sm)보다 한 단계 큰 md 사이즈(6px 12px, 12px label)로 중요 액션 버튼 시각적 비중 강화
  - **통계 라벨 폰트 통일**: statsLabelRef 폰트를 11px(small)로 변경
  - **승인 전 코드 수정 절대 금지 규칙 강화**: AGENTS.md 섹션3 규칙0 강화 (승인 트리거, 미승인 상황, 추천 요청 시 자동 수정 금지, Plan 모드 무관 적용), 5개 스킬 파일에 동일 규칙 추가
  - 검증: `npm run typecheck` 통과, `npm run build` 통과
  - 추가 점검: 좌측/우측 업종 정렬 순서 일치 확인 (양쪽 모두 `getActiveSectors()` 단일 소스 공유, P10 준수), 우측 순번 컬럼은 추가 안 함 권장 (이동 타겟 선택 UI에 순번이 의미 없고 단순성 P24 위반)

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, 테이블 컬럼 너비 동적 조정 등 — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 2784 passed, 0 failed. 커버리지 Phase 1~3 완료
- **업종 분류**: 69→55 재분류 + 업종명 정비 + 순위 기반 점수 전환 — 완료, 사용자 UI 확인 대기
- **규칙/문서 정리**: AGENTS.md 4섹션 구조, 아키텍처 원칙 24개, .devin/workflows 제거 + skills 통합 — 완료 (2026-07-13)

## 진행 중 작업

### 아키텍처 전수 점검 — 7/30 세션 완료, 23개 미시작
- **완료**: B-01~B-06, F-01 (P0 전체 + B-06)
- **미시작**: B-07~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-07 (WS 시세 처리) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 업종 분류 재분류 — 사용자 UI 확인 대기
- 69→55 업종 재분류 + 9개 업종명 정비 + 순위 기반 점수 전환 완료
- 사용자 확인 필요: 업종순위 화면(55개 업종 표시, 변경된 업종명, 점수 바 균등 간격), 매수 후보 화면(25개 이동 종목 새 업종 표시)

### 2순위: 아키텍처 전수 점검 P1 세션 (B-07)
- B-07: WS 시세 처리 (`engine_ws_reg.py`, `engine_ws_dispatch.py`, `engine_ws.py`, `engine_ws_parsing.py`, `engine_ws_fill_followup.py`)
- `docs/architecture_audit_plan.md` 체크리스트 사용, 발견 문제를 섹션 7에 등록
- 이후 B-08~B-11 (P1) → B-12~B-19 (P2) → B-20~B-23 (P3) → F-02~F-07 순서

### 3순위: 유령 포지션 005930 근본 원인 조사
- `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조

### 보류: P23 테이블 컬럼 너비 일관성 개선 (사용자 승인 대기)
- stock-detail.ts 자체 `makeAmountColumn` 너비 설정 없음, 비표준 컬럼 너비 설정 없음 (buy-target.ts 6개, sell-position.ts 6개, profit-shared.ts 9개), 순번/종목코드 컬럼 팩토리 사용 통일

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결**
  - 상세 조사 기록: `docs/ghost_position_investigation.md` ([A]~[I] 미조사 항목)
  - 재발 방지 조치 (2026-07-10, 코드 확인 완료):
    - `test_positions` 테이블 제거 — `stock_tables.py:141`, DB 저장 로직 전체 제거
    - `trades` 기반 SSOT 전환 — `dry_run.py:38-68`, `trade_history.py:549`
    - `execute_sell()` 런타임 가드 — `trading.py:418-436` (유령 포지션 차단 + Telegram 알림)
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 수동 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성

## 테스트 실행 원칙 (필수 준수)

### 1. 실행 명령어 (통일)
```
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- `timeout_method = signal` 필수 — `thread` 방식은 asyncio C-level wait를 interrupt하지 못해 hang 시 프로세스가 영구 블록됨
- `pytest.ini`에 전역 설정되어 있으므로 CLI에서 생략 가능

### 2. 자동 hang 체크 원칙 (에이전트 필수 강제 — 수동 개입 금지)
- **a. 10초마다 진행 상태 자동 체크**: 테스트 실행 후 `command_status`로 주기적 확인
- **b. 10초 이상 로그/출력 멈추면 즉시 hang 간주**: 대기 없이 강제 종료 결정
- **c. hang 감지 시 즉시 프로세스 강제 종료**: SIGTERM/Ctrl+C로 프로세스 종료
- **d. hang 원인 자동 분석**: 종료 후 로그/코드 분석하여 원인 보고
- **e. 위 모든 과정은 에이전트가 자동 수행**: 사용자 확인 대기 금지, 수동 개입 금지
- 정상 완료: "✅ N passed in N.Ns"
- hang 감지: "❌ 10초 이상 응답 없음 — 강제 종료 및 원인 분석 시작"

### 3. 테스트 hang 방지 코딩 원칙 (근본 원인별)

#### 원인 A: 실제 asyncio 동기화 프리미티브 (Lock/Event/wait_for)
- **금지**: 테스트에서 실제 `asyncio.Lock()`, `asyncio.Event()`, `asyncio.wait_for()` 사용
- **해결**: `MagicMock` + `AsyncMock`으로 교체
  - Lock: `lock.__aenter__ = AsyncMock(return_value=lock)`, `lock.__aexit__ = AsyncMock(return_value=None)`
  - Event: `ev.wait = AsyncMock()`, `ev.clear/set = MagicMock()`
  - wait_for: 즉시 반환 또는 즉시 `TimeoutError` 발생시키는 async 함수로 patch

#### 원인 B: asyncio.create_task 백그라운드 태스크
- **금지**: 테스트에서 `asyncio.create_task()`가 실제 실행되는 것을 허용
- **해결**: `patch("module.asyncio.create_task")`로 mock 교체, `add_done_callback` 속성 포함

#### 원인 C: NotificationWorker / 백그라운드 워커 싱글톤
- **금지**: `_fire_and_forget_telegram` 등이 실제 `NotificationWorker.get_instance()`를 호출하여 백그라운드 태스크 생성
- **해결**: autouse fixture에서 `patch("module._fire_and_forget_telegram")` 처리

#### 원인 D: 실제 DB I/O (aiosqlite)
- **금지**: 테스트에서 `get_db_connection()`이 실제 DB에 연결
- **해결**: autouse fixture에서 `patch("backend.app.db.database.get_db_connection")` 처리

#### 원인 E: pytest-asyncio 이벤트 루프 간섭
- **금지**: conftest.py에 async fixture 사용 (이벤트 루프 정리 중 hang 유발)
- **금지**: conftest.py에서 `asyncio.sleep` 전역 patch (pytest-asyncio 내부 동작 간섭)
- **해결**: conftest.py는 동기 fixture만 사용, 캐시 리셋 등 최소 기능만 유지

### 4. run_command 사용 시
- `Blocking: false` + `WaitMsBeforeAsync: 20000` — hang 감지 시 명령 취소 가능
- 또는 subprocess + `proc.wait(timeout=N)` + `proc.kill()` 패턴 사용
