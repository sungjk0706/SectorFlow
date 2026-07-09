# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-10: 매수후보 페이지 주문가능금액 배지 추가 — 1위 종목 매수 가능 수량 통합**
  - 목적: "왜 매수가 안 되지?" UX 해소 — 아키텍처 원칙 21 (User Transparency)
  - 추가: `renderOrderableBadge()` — `hotStore.account.orderable` 실시간 표시 + 1위 통과 종목 매수 가능 수량 통합
    - 예: `💳 주문가능금액 2,037,794원 (1위 삼성전자 7주)`
    - `orderable <= 0` 또는 1위 종목 1주 미달 시 빨간 배지 + `⚠️ 매수 불가` 경고
  - 수정: `effectiveBuyAmt` 계산에 `orderable` 반영 — `min(buy_amt, dailyRemain, orderable)` (백엔드 `trading.py:217-220`과 정합)
  - 수정: `scheduleRender()`에 `account` 참조 변경 감지 추가 (기존: buyTargets/positions/settings/buyLimitStatus만 감시)
  - 제거: perStock 배지 (종목당 매수 최대 금액) — 매수설정 패널에서 확인 가능하므로 중복 제거
  - 변경 파일: `frontend/src/pages/buy-target.ts` 1개 (프론트엔드 only, 백엔드/WS 변경 불필요 — account-update 이벤트 이미 buy-target 페이지에 전송됨)
  - 검증: `npm run build` 통과 (tsc + vite, exit code 0)
  - 커밋: `08256ec` push 완료
- **2026-07-10: 차트 툴팁 하단 잘림 수정 — positionTooltip 공통 함수 추출**
  - 문제: 수익현황 페이지 일별 수익률 막대차트에서 막대 하단 호버 시 툴팁이 `canvasWrap`(overflow:hidden) 경계를 벗어나 잘림
  - 근본 원인: 툴팁 위치 계산이 `tooltip.offsetHeight`를 고려하지 않아 하단 경계 초과
  - 추가 발견: X축 좌측 넘침 미처리 버그, 두 차트 컴포넌트에 동일 코드 중복 (SSOT 위반)
  - 수정: `ui-styles.ts`에 `positionTooltip()` 공통 함수 추가 (양축 경계 클램핑), `canvas-profit-chart.ts`/`canvas-sector-donut.ts` 중복 코드를 공통 함수 호출로 교체
  - 검증: `npm run build` 통과 (tsc + vite, exit code 0)
  - 커밋: `e77ea70` push 완료
- **2026-07-10: 유령 매도 기록(id=144) 삭제 및 수익 통계 정정**
  - 내용: `trades` 테이블에서 005930 유령 매도 1건 삭제 (BUY 기록 없는 SELL 10주 @279,500, avg_buy_price=70,100)
  - 영향: `trade_history.py` 집계 함수만 영향 (test 모드 총 실현손익 +1,215,065→-872,821 정정, 2026-07-09 daily sell=21→20, pnl=+1,391,531→-696,355)
  - 무영향: `settlement_state`, `test_positions`, `build_positions_from_trades` 모두 독립
  - 검증: 백엔드 기동 정상 (매도 34→33건 복원), API 응답에서 유령 매도 미표시 확인, 잔존 프로세스 0건
  - 상세 기록: `docs/ghost_position_investigation.md` "유령 매도 기록 삭제" 섹션
- **2026-07-10: 유령 포지션 재발 방지 예방 조치 구현**
  - 내용: `_test_positions`와 `trade_history` 독립적 영속화 문제를 SSOT 원칙으로 해결
  - 수정: 7개 파일 (stock_tables.py, trade_history.py, dry_run.py, trading.py, engine_lifecycle.py, settings.py, test_dry_run_fill_event.py)
  - 핵심: `test_positions` 테이블 제거, `trades` 기반 포지션 파생, `execute_sell()` 런타임 가드 추가
  - 검증: pytest 105 passed in 17.31s
  - 상세 기록: `docs/ghost_position_investigation.md` "예방 조치 구현 기록" 섹션

## 현재 상태
- **백엔드**: 유령 매도 기록(id=144) 삭제 완료, 유령 포지션 재발 방지 예방 조치 구현 완료 (근본 원인은 미해결), boost_order_ratio_pct 422 오류 수정 완료, Settlement Engine 리팩토링 완료, RiskManager 리팩토링 Phase 1 완료
- **프론트엔드**: 더미 데이터 삭제 완료, 차트 툴팁 잘림 수정 완료, 매수후보 페이지 주문가능금액 배지 추가 완료, `npm run build` 통과
- **Git**: 커밋 `08256ec` push 완료 (관련 없는 변경사항 ARCHITECTURE.md, architecture_principles.md, risk_manager_refactor_megaplan.md, fix-plan-boost-order-ratio-422.md는 미커밋)

## 다음 단계
- **1순위: 유령 포지션 근본 원인 심층 조사 (별도 세션)**:
  - 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
  - WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
  - `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조
- **2순위: 브라우저 실제 화면 확인** — 장중에 매수후보 테이블에서 SK하이닉스(000660) 하이라이트 깜빡임 없는지 확인 + 매수/매도호가잔량비율 슬라이더 422 미발생 확인
- **3순위: exchange_calendars 교체 검토** — pandas(70MB)+numpy(33MB) 등 간접 의존성 약 112MB 절감 가능

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결, 재발 방지 조치 + 유령 매도 기록 삭제 완료**
  - 상세 조사 기록: `docs/ghost_position_investigation.md`
  - 재발 방지 조치 (2026-07-10 구현): `test_positions` 테이블 제거, `trades` 기반 SSOT 전환, `execute_sell()` 런타임 가드
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성
- **체결지연 50ms 초과 WARNING 7건** (2026-07-08 13:26~ 런타임 기동 중 발생)
  - `trading_2026-07-08.log:9597~9609` — 50~143ms 지연 7건 (200ms 초과 없음)
  - 조사 필요: `_handle_real_01_tick` await 체인 프로파일링, 지연 발생 위치 식별

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

## 개선 필요 영역 — 테스트 커버리지

### 현재 커버리지: 14% (13,833줄 중 1,981줄 커버)

### 고커버리지 영역 (유지)
- `sector_score.py` 100%, `models.py` 100%, `settings_defaults.py` 100%
- `sector_calculator.py` 97%, `sector_filter.py` 96%
- `test_dry_run_fill_event.py` 95%, `test_sector_calculator.py` 100%
- `database.py` 88%, `engine_state.py` 82%, `trade_mode.py` 79%
- `settings_file.py` 70%, `engine_utils.py` 68%

### 테스트 부족 영역 (우선순위별)

#### Priority 1 — 매매 핵심 로직 (완료)
- `test_buy_filter.py` ✅, `test_circuit_breaker.py` ✅, `test_settlement_engine.py` ✅
- `test_risk_manager.py` ✅, `test_buy_order_executor.py` ✅, `test_trading.py` ✅ (hang 해결 — 커밋 `a4fa031`)

#### Priority 2 — 엔진/WS 계층 (완료)
- `test_engine_ws.py` ✅, `test_engine_ws_dispatch.py` ✅, `test_engine_ws_parsing.py` ✅
- `test_engine_ws_reg.py` ✅, `test_engine_account.py` ✅, `test_engine_account_notify.py` ✅
- `test_engine_account_rest.py` ✅, `test_engine_symbol_utils.py` ✅

#### Priority 3 — 파이프라인/스케줄러 (완료)
- `market_close_pipeline.py` (712줄, 86%) ✅
- `pipeline_compute.py` (655줄, 92%) ✅ — 배치 드레인 + 코얼레싱 + 계좌 디바운스 추가 (2026-07-06)
- `pipeline_gateway.py` (86줄, 87%) ✅
- `daily_time_scheduler.py` (601줄, 90%) ✅
- `data_manager.py` (136줄, 96%) ✅

#### Priority 4 — 브로커 커넥터 (0% 커버, 장기)
- `kiwoom_connector.py`, `kiwoom_rest.py`, `kiwoom_order.py`, `kiwoom_providers.py`, `kiwoom_stock_rest.py`
- `ls_connector.py`, `ls_rest.py`, `ls_providers.py`
- `connector_manager.py`

#### Priority 5 — Web 라우트 (0% 커버, 장기)
- `app.py`, `ws.py`, `ws_manager.py`, `settings.py`, `stock_classification.py`, `status.py`

#### Priority 6 — 유틸/기타 (0% 커버, 장기)
- `telegram.py`, `telegram_bot.py`, `trade_history.py` (회귀 테스트 2건 추가), `dry_run.py`
- `journal.py`, `logger.py`, `encryption.py`, `sector_mapping.py`
