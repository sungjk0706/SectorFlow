# HANDOVER — SectorFlow

## 추후 논의 필요 (미결정)
- 없음

## 직전 완료 작업
- **2026-07-12: 증권사 변경 확인 팝업 추가 + 라디오 disabled 잔존 버그 수정**
  - **대상**: `frontend/src/pages/general-settings.ts`
  - **수정 1**: `handleBrokerChange`를 `async`로 변경하고 `showConfirmDialog`(공통 팝업)로 확인 단계 삽입 — 라디오 클릭 → 팝업(변경 전/후 증권사명 + 4개 작업 요약: 연결 해제, 토큰 폐기, 엔진 재기동, 새 연결/인증) → 확인 시 재기동. 취소/Escape/외부클릭 시 `syncBrokerRadios()`로 라디오 원래 값 복원. `BROKER_NAMES` 상수 추가(라디오 items 라벨과 SSOT 일치).
  - **수정 2**: `saveSection` then 콜백에서 `brokerSaving = false`를 `syncBrokerRadios()` 이전으로 이동 — 기존에는 `syncBrokerRadios()`가 `brokerSaving=true` 상태로 `setDisabled(true)`를 호출한 뒤 `brokerSaving=false`가 설정되어 라디오가 영구 disabled 되는 버그. 실행 순서 교정만으로 해결.
  - 검증: `npm run typecheck` exit 0, `npm run build` exit 0 (60 modules transformed)
- **2026-07-12: B-04 정산 엔진 및 거래 이력 아키텍처 점검 (4건 수정, 1건 보류)**
  - **대상**: `services/settlement_engine.py`, `services/trade_history.py`, `db/stock_tables.py`, `web/app.py` + 테스트 3개 파일
  - **수정 1 (B04-04, P16)**: dead code 5개 함수 제거 — `_migrate_from_json`, `_patch_sell_history`, `start/stop_consumer_task`, `close_db_connection` (no-op이거나 앱 코드에서 호출되지 않음) + `app.py`에서 `trade_history.start_consumer_task()`/`stop_consumer_task()` 호출 제거 + 관련 테스트 8개 제거
  - **수정 2 (B04-01, P20)**: `_ensure_loaded`에서 `_loaded = True`를 try 블록 이전에 설정하던 것을 성공 후로 이동 — DB 로드 실패 시 `_loaded`를 `False`로 유지하여 다음 호출에서 재시도, silent except 제거 + "신규 설치 시 정상" 잘못된 진단 메시지 제거
  - **수정 3 (B04-03, P20)**: `_lookup_sector`의 silent except 제거 — DB 에러 시 예외 전파, "행 없음"일 때만 "미분류" 반환 + `record_sell`에서 `_lookup_sector` 실패 시 "미분류"로 진행하되 logger.error 레벨로 명시적 로깅
  - **수정 4 (B04-02, P20/P22, CRITICAL)**: `load_settlement_state`의 silent except 제거 — "행 없음"과 "DB 에러" 구분 (행 없음 시 None 반환, DB 에러 시 예외 전파) + `_load`의 try/except 폴백 제거 — DB 에러 시 기본값으로 정산 상태 덮어쓰던 CRITICAL 폴백 제거, 예외 전파하여 기동 실패로 명시적 알림
  - **보류 (B04-05, P22)**: 기동 시 정산 상태-거래 이력 대조(reconciliation) 없음 — 설계 수준의 문제, 별도 논의 항목으로 등록
  - 수정 파일: `backend/app/services/settlement_engine.py`, `backend/app/services/trade_history.py`, `backend/app/db/stock_tables.py`, `backend/app/web/app.py`, `backend/tests/test_settlement_engine.py`, `backend/tests/test_trade_history.py`, `backend/tests/test_stock_tables.py`, `backend/tests/test_web_app.py`
  - 검증: 2763 passed 0 failed, 런타임 기동 정상 (체결 이력 로드 44건/39건, 정산 상태 로드 완료, AttributeError/Traceback 없음)

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체 (korean_lunar_calendar), boost_order_ratio_pct 422 수정, 보유종목 buy_date 파생, 유령 포지션 재발 방지 조치, 테스트모드 6개월 보관 정책(125거래일, 메모리+DB 동시 정리) — 모두 코드 확인 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 주문가능금액 배지, 매수일자 컬럼, stale state 수정, 색상 체계 통일 (COLOR 상수화), 검색 입력란 공통 컴포넌트, 가상 스크롤 플래시 억제, 일반설정 비거래일 배지 정렬 수정, 업종순위 요약 라벨 가독성 개선, 매수후보 배지 폰트 13px 확대, 매도설정 보유종목 요약 배지 추가, 업종순위 페이지 불투명도 3단계 통일, maxTargets fallback SSOT 통일(DEFAULT_SECTOR_MAX_TARGETS 상수), 수익현황/수익상세 기간 전환 버튼(당일/5일/당월/전체 4버튼 + 파랑 테두리), 일별수익률 안내 라벨 삭제, Enter 키 포커스 이동 개선(28개 입력창), Vite 프록시 크래시 방어, Vite http proxy error 로그 근본 해결(백엔드 ready 대기 후 브라우저 오픈), 수익현황 업종 섹션 연동(도넛 범례 클릭→스크롤+하이라이트), 전체보기/전체접기 토글 버튼, 차트 onMove undefined 크래시 근본 해결(render early return 시 barRects 동기화), 수익현황 기간 선택 상태 재기동 후 유지(localStorage quickLabel 영속화 + 초기 활성 버튼 복원), 수익상세 페이지 뷰 상태 재기동 후 유지(localStorage selectedView+drilldownActive+dateRange 영속화, 7곳 핸들러 persistViewState), 스핀버튼 초기 비활성 버그 근본 해결(store subscriber settings 변경 시에만 notify + createSpinButtons mousedown 포커스 유지 + registerEditing 데드 코드 제거), 증권사 변경 확인 팝업 추가(showConfirmDialog 재사용 + 변경 전/후 증권사명 + 4개 작업 요약 + 취소 시 라디오 복원 + BROKER_NAMES SSOT 상수), brokerSaving disabled 잔존 버그 수정(then 콜백 실행 순서 교정) — 모두 코드 확인 완료, `npm run build` 통과
- **Git**: 증권사 변경 확인 팝업 + 라디오 disabled 잔존 버그 수정 — 커밋 대기
- **테스트 커버리지**: Stage 1~9 + P6(telegram_bot.py) + 0% 모듈 7개 + 10%대 모듈 9개 + 30~50%대 Phase 1,2,3 전부 완료 — 백엔드 2763 passed, 0 failed
  - 0% 모듈 7개 해결: engine_ws_fill_followup(100%), engine_radar_ops(100%), notification_worker(85.19%), lock_manager(68.09%), engine_cache, broker_router, engine_loop
  - 10%대 모듈 9개 해결: engine_settings(100%), stock_tables(100%), stock_filter(99.44%), stock_classification_data(95.14%), settings_store(93.13%), sector_data_provider(92.94%), engine_bootstrap(49.62%), engine_snapshot(39.22%), engine_sector_confirm(33.45%)
  - 30~50%대 Phase 1,2,3 전부 완료 (실측): engine_snapshot(39.22%→97.39%, 12 테스트), engine_sector_confirm(33.45%→100%, 51 테스트), engine_bootstrap(49.62%→99.25%, 12 테스트)
  - 커버리지 실행 명령어: `python -m pytest backend/tests --cov=backend --cov-report=term-missing --cov-report=html --timeout=15 --timeout-method=signal`
- **settlement.py await 누락**: 수정 완료 (`settlement.py:16`)

## 진행 중 작업

### 아키텍처 전수 점검 — 4/30 세션 완료

| 세션 ID | 우선순위 | 내용 | 상태 |
|---------|----------|------|------|
| B-01 | P0 | 주문 실행 경로 | ☑ 완료 (8건 수정, 50 tests passed) |
| B-02 | P0 | 리스크 관리 및 서킷 브레이커 | ☑ 완료 (3건 수정, 2774 tests passed, V-02 프론트 통지 보류) |
| B-03 | P0 | Dry Run (테스트 모드 가상 주문) | ☑ 완료 (3건 수정, 2768 tests passed) |
| B-04 | P0 | 정산 엔진 및 거래 이력 | ☑ 완료 (4건 수정, 1건 보류, 2763 tests passed) |
| B-05 | P0 | 자동매매 유효성 및 코어 큐 | ☐ 미시작 |
| F-01 | P0 | 통신 계층 및 상태 관리 | ☐ 미시작 |
| B-06~B-11 | P1 | 엔진 루프/WS/부트스트랩/섹터/계좌/파이프라인 | ☐ 미시작 |
| B-12~B-19 | P2 | DB/설정/Broker/증권사/Domain/스케줄러 | ☐ 미시작 |
| B-20~B-23 | P3 | 알림/유틸/Web API/테스트 | ☐ 미시작 |
| F-02~F-07 | P1~P3 | 진입점/핵심페이지/설정/수익/컴포넌트/타입 | ☐ 미시작 |

## 다음 단계

### 1순위: 아키텍처 전수 점검 P0 세션 (B-05, F-01)

B-04 완료. 다음 세션에서 `docs/architecture_audit_plan.md`의 추천 세션 순서에 따라 진행:

1. **B-05**: 자동매매 유효성 및 코어 큐 (`services/auto_trading_effective.py`, `services/core_queue.py`)
2. **F-01**: 통신 계층 및 상태 관리 (`stores/hotStore.ts`, `api/ws.ts`, `binding.ts` 등)

**보류 (V-02)**: B-02에서 발견된 OMS 서킷브레이커 OPEN 프론트엔드 통지 (P21) — 프론트엔드 세션에서 `circuit_breaker_open` WS 이벤트 핸들러 및 UI 알림 칩 추가 필요

**보류 (B04-05)**: B-04에서 발견된 기동 시 정산 상태-거래 이력 대조(reconciliation) 부재 (P22) — `_orderable`이 거래 이력으로 역산한 값과 일치하는지 검증 로직 설계 필요

각 세션 진행 시:
- `docs/architecture_audit_plan.md`의 해당 세션 체크리스트 사용
- 발견된 문제를 계획서 섹션 7 "발견된 문제 기록"에 등록
- 세션 완료 시 계획서 섹션 8 "점검 진행 현황 요약" 갱신
- 세션 종료 시 본 `HANDOVER.md` 진행 상태 갱신

### 2순위: 유령 포지션 005930 근본 원인 조사
- 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
- WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
- `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조

### 3순위: P1 세션 (B-06~B-11, F-02)
P0 세션 완료 후 진행.

### 4순위: P2 세션 (B-12~B-19, F-03~F-04)
P1 세션 완료 후 진행.

### 5순위: P3 세션 (B-20~B-23, F-05~F-07)
P2 세션 완료 후 진행.

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
