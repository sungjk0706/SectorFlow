# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-13: 매수후보/보유종목 상단 배지 인디케이터 + 업종별 종목 시세 상단 요약 라벨 정리**
  - **목적**:
    1. 매수설정 → 매수후보 페이지 상단 3개 인디케이터(주문가능금액, 일일 매수 금액, 동시 보유 종목)가 금액/종목명/수량 변동 시 좌우로 밀리는 문제 해결
    2. 업종순위 → 업종별 종목 실시간 시세 페이지 상단 라벨(`5일평균거래대금`과 `합계/KRX/NXT/코스피/코스닥`)을 1행으로 정리해 불안정해 보이는 배치 개선
  - **근본 원인**:
    1. `buy-target.ts:312-313` 배지 행에 `display: flex`/`gap`이 없이 `lineHeight: '2'`만 지정 → 자식 `span`이 inline 상태로 텍스트 폭에 따라 shrink-to-fit
    2. `renderLimitBadge`/`renderOrderableBadge`가 매번 `el.textContent = ''` 후 새 `span` 생성/append → DOM 재구성
    3. `sell-position.ts:145-146`도 동일한 inline 배지 행으로 중복 구현
    4. `sector-stock.ts`의 `summaryBar`가 `flexDirection: 'column'` + `alignItems: 'center'`로 2행 중앙 정렬되어 있어, 그룹 간 여백과 중심이 고정되지 않아 불안정해 보임
  - **해결 방안**:
    - `frontend/src/components/common/badge.ts` 신규: `createBadgeRow`, `createBadge`, `updateBadge` — `display: flex` + `gap` + `flex: 1` + `min-width: 0` + `nowrap` + `ellipsis` 구조
    - `buy-target.ts` 배지 행과 렌더 로직을 공통 컴포넌트로 교체, `updateBadges`는 `textContent`만 갱신
    - `sell-position.ts` 요약 배지 행도 동일한 공통 컴포넌트로 교체
    - `sector-stock.ts`의 `summaryBar`를 `flexDirection: 'row'` + `justifyContent: 'space-between'`로 1행 정리. 좌측에 `5일평균거래대금 (N)억`, 우측에 `합계/KRX/NXT/코스피/코스닥` 종목수 요약
  - **수정 파일**: `components/common/badge.ts` (신규), `buy-target.ts`, `sell-position.ts`, `sector-stock.ts`
  - **검증**: `npm run typecheck` 통과, `npm run build` 통과
  - **커밋/푸쉬**: `21ddb1b` pushed to `origin/main`

- **2026-07-13: DataTable 컬럼 너비 안정화 — 실시간 틱 시 구분선 흔들림 + 좌우 스크롤 근본 해결**
  - **목적**: 정규장 실시간 틱 수신 시 매수후보 테이블 컬럼 구분선이 미세하게 흔들리고, 모든 페이지에 좌우 스크롤이 발생하는 문제 해결
  - **근본 원인 3단계**:
    1. `checkCellWidth`/`flushWidthUpdate` — 실시간 틱 경로에서 셀 텍스트 폭 재측정 → 전체 컬럼 % 재계산 → 구분선 이동
    2. `initFromRows` 무조건 `applyWidths` 호출 — `buy-targets-delta` 이벤트 시마다 폭 재계산
    3. `gridTemplateColumns` % 단위 → 매 레이아웃 평가 시 컨테이너 너비 기준 px 재변환 + `wrapper.clientWidth` 사용으로 스크롤바 너비 초과 → 좌우 스크롤
  - **해결 방안**: 첫 `updateRows` 시 1회만 데이터 기반 폭 계산 후 고정 (`initialized` 플래그). 이후 실시간 틱/데이터 변화에 재계산 없음. px 단위 고정 + `scrollContainer.clientWidth` 사용 + 반올림 오차 보정. 전체 7개 DataTable 페이지 28개 컬럼에 minWidth/maxWidth 지정.
  - **수정 파일**: `data-table.ts` (폭 재계산 로직 전면 개편), `buy-target.ts`, `sell-position.ts`, `profit-shared.ts`, `stock-classification.ts`, `stock-detail.ts`, `general-settings.ts` (컬럼 minWidth/maxWidth 추가)
  - **검증**: `npm run typecheck` 통과, `npm run build` 통과, 브라우저 확인 대기

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, DataTable 컬럼 너비 안정화(1회 계산 후 고정 + px 단위 + 전체 컬럼 minWidth/maxWidth 지정) — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 pytest 통과. 커버리지 Phase 1~3 완료
- **업종 분류**: 69→55 재분류 + 업종명 정비 + 순위 기반 점수 전환 + 종목 이동 버그 3건 근본 해결 + "업종명없음" 잔적 제거 — 완료, 사용자 UI 확인 대기
- **규칙/문서 정리**: AGENTS.md 4섹션 구조, 아키텍처 원칙 24개, .devin/workflows 제거 + skills 통합 — 완료 (2026-07-13)

## 진행 중 작업

### 업종 점수 누적 가산점제 전환 — 사전 조사 완료, 구현 대기
- **계획서**: `docs/plan_sector_bonus_points.md` (687줄)
- **상태**: 정밀 사전 조사 + 변경 계획서 작성 완료. 사용자 승인 후 구현 착수.
- **구현 단위**: Phase 1(백엔드 도메인) → Phase 2(백엔드 서비스/설정) → Phase 3(프론트엔드) → Phase 4(테스트)
- **각 Phase 완료 시**: 커밋 + HANDOVER.md 갱신 + 사용자 보고

### 아키텍처 전수 점검 — B-09 완료, 20개 미시작 (일시 보류)
- **완료**: B-01~B-09, F-01 (P0 전체 + B-06~B-09)
- **미시작**: B-10~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-10 (엔진 계좌/서비스) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 업종 점수 누적 가산점제 전환 구현 (승인 대기)
- **계획서**: `docs/plan_sector_bonus_points.md` (정밀 사전 조사 완료)
- **구현 순서** (계획서 섹션 9):
  1. Phase 1: 백엔드 도메인 (`models.py`, `sector_score.py`, `sector_calculator.py`) — `MetricDef`/`DEFAULT_METRICS` 제거, `calculate_bonus_scores` + `percentile_to_score` 신규, `sector_weights` 파라미터 제거, **트리밍 로직/파라미터 제거**, `scored_rise_ratio`/`scored_trade_amount` 필드 제거 → `rise_ratio`/`total_trade_amount` 통합
  2. Phase 2: 백엔드 서비스/설정 (`engine_sector_confirm.py`, `sector_data_provider.py`, `settings_*.py`, `engine_account_notify.py`) — `sector_weights` 참조 제거, **트리밍 변수/인자/설정 키 제거** (`sector_trim_*`), WS payload 가산점 필드 추가
  3. Phase 3: 프론트엔드 (`sector-settings.ts` 슬라이더 + **④ 극단값 제외(트리밍) 섹션 제거**, `sector-ranking-list.ts` 점수 표시, `types/index.ts`, `uiStore.ts`, `binding.ts`)
  4. Phase 4: 테스트 전면 수정 (11개 파일, **트리밍 테스트 제거 포함**)
- **주의**: 2차 가산점 모집단 시점 이슈 (계획서 섹션 8.1) — `calculate_bonus_scores`에 `min_rise_ratio` 파라미터 추가로 통과 업종 판단 필요
- **시작점**: 사용자 "진행해" 지시 후 Phase 1부터 착수

### 2순위: 업종순위 수신율 UI 확인 대기
- 브라우저에서 업종순위설정 패널 ② 행 확인: 수신율 100.0% 표시, 수신/미수신 종목수 표시
- 라벨 색상: 정적 라벨 검정, 동적 숫자 파랑 구분 확인
- 장개시 후 WS 구독 시작 시 수신율 0% → 틱 수신시 상승 → 임계값 도달시 업종점수 계산 시작 확인

### 3순위: engine_settings.py 인접 라인 P20 폴백 일괄 정리 (승인 대기)
- line 138: `sector_min_rise_ratio_pct` — `or 60.0`이 0%를 60%로 치환
- line 139: `sector_min_trade_amt` — `or 0.0`은 다행이지만 패턴 동일 위험
- 동일 패턴(`_v if _v is not None else 기본값`)으로 일괄 정리 권장
- **참고**: 업종 점수 가산점제 전환 시 `sector_weights` 관련 코드 제거되므로, 본 항목과 중복 정리 검토

### 4순위: 아키텍처 전수 점검 P1 세션 (B-10)
- B-10: 엔진 계좌/서비스 (`engine_account.py`, `engine_account_rest.py`, `engine_account_notify.py`, `engine_service.py`)
- `docs/architecture_audit_plan.md` 체크리스트 사용, 발견 문제를 섹션 7에 등록
- 이후 B-11 (P1) → B-12~B-19 (P2) → B-20~B-23 (P3) → F-02~F-07 순서

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
