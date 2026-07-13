# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-13: engine_settings.py 잔존 폴백 9곳 해결 — 복호화 실패 silent 1곳 + real 키 레거시 폴백 7곳 + max_position_size lambda 1곳 (P20/P21/P23)**
  - **현상**: 직전 세션에서 22곳 or 폴백 정리 후 잔존 9곳이 미해결 문제로 등록됨. (1) `_dec` 내 `decrypt_value(s) or ""` — 복호화 실패 시 빈문자열 폴백, 실패 사실 로그 미출력 (P21). (2) `_dec(real) or _dec(legacy)` 7곳 — real 키 복호화 실패 시 레거시 키로 인증 시도, 사용자 모르게 다른 키 사용 (P21). (3) max_position_size lambda — None/빈문자열/"None" → 0 폴백, 0이 유효값(제한 없음)이므로 구분 불가 (P20)
  - **근본 원인**: `backend/app/core/engine_settings.py:33` (`_dec` or 폴백), `:43-45`/`:126-128` (real 키 or 레거시 폴백, kiwoom + non-kiwoom 루프), `:73` (max_position_size lambda)
  - **수정 파일**: `backend/app/core/engine_settings.py`, `backend/tests/test_engine_settings.py` (2개 파일)
  - **변경 내용**:
    1. `_dec` 함수: `decrypt_value(s) or ""` → `decrypt_value(s)` 반환값 None 체크 + `logger.warning("[설정] 복호화 실패...")` 출력 후 빈문자열 반환 (P21)
    2. 신규 helper `_pick_real_or_legacy(real_key, legacy_key, field_name)`: real 키가 암호문(`gAAAA`)인데 복호화 실패 → 레거시 폴백 금지 + `logger.error("레거시 폴백 금지")` (P21). real 키가 None/빈값 → 레거시 폴백 허용 (정상 마이그레이션 유지). kiwoom 3곳 + non-kiwoom 루프 3곳 + account_no 명시적 None 체크로 통일
    3. max_position_size: lambda 제거 → `_v = merged.get("max_position_size"); result["max_position_size"] = 0 if _v is None or _v == "None" or _v == "" else int(_v)` (P20/P23). dict 블록에서 "리스크 (이어서)" 섹션으로 이동
    4. 신규 테스트 4건: `test_decrypt_failure_logs_warning`, `test_real_key_decrypt_failure_blocks_legacy_fallback`, `test_real_key_empty_falls_back_to_legacy`, `test_non_kiwoom_real_key_decrypt_failure_blocks_legacy`
  - **영향 범위**: `build_engine_settings_dict()` 반환 dict를 사용하는 모든 호출처. 정상 케이스(real 키 평문/None) 반환값 동일. 복호화 실패 케이스만 동작 변경 — 기존에는 레거시 키로 인증 시도, 수정 후 빈문자열 반환 + 에러 로그. account_no는 암호화 대상 아님(`SENSITIVE_KEYS` 제외) → 문자열 폴백만 명시적 None 체크로 통일
  - **검증**: pytest test_engine_settings.py 55 passed (기존 51 + 신규 4) in 0.81s. 런타임 기동 정상 — "복호화 실패" 경고 없음, 키움/LS 토큰 발급 완료, 잔존 프로세스 0건
  - **커밋**: (승인 대기)

- **2026-07-13: 키움증권 토큰 발급 경로 복구 — confirmed_data_broker 캐시 누락 수정 (P10 SSOT)**
  - **커밋**: `b27a8b0`

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책, JIF 경계 이벤트 즉시 갱신 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, DataTable 컬럼 너비 안정화, applyIndexRefresh dead code 제거 + applyIndexData market_phase 갱신 — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 pytest 56 passed (test_engine_ws_dispatch.py). 커버리지 Phase 1~3 완료
- **규칙/문서 정리**: AGENTS.md 4섹션 구조, 아키텍처 원칙 24개, .devin/workflows 제거 + skills 통합 — 완료 (2026-07-13)

## 진행 중 작업

### 업종 점수 누적 가산점제 전환 — 계획서 갱신 완료, 구현 대기
- **계획서**: `docs/plan_sector_bonus_points.md` (895줄 — 2026-07-13 갱신)
- **상태**: 폭넓은 사전조사(백엔드/프론트엔드/테스트 전 범위) + 설계 문제 2건 해결 + 프론트엔드 UI 계획 보강 완료. 사용자 승인 후 구현 착수.
- **설계 문제 해결**:
  - **옵션 C 채택** (2차 가산점 모집단 시점): 1차/3차 계산 → 컷오프 → 2차 계산(통과 업종만) → 종합 점수. 컷오프 로직을 `calculate_bonus_scores` 내부로 이관하여 진실 소스 1곳 (P10/P22 준수).
  - **Phase 1+2 통합** (중간 상태 깨짐 방지): 백엔드 도메인+서비스/설정을 1세션에 통합. "백엔드 전환"을 1단계로 정의. 각 Phase가 독립적으로 완료·검증 가능.
- **구현 단위 (3세션)**: Phase 1(백엔드 전환 — 도메인+서비스+설정 통합) → Phase 2(프론트엔드 전환) → Phase 3(테스트 전환)
- **추가 개선점**: 3차 가산점 median 대안(편향 모니터링 후 전환 검토), `total_trade_amount`→`avg_trade_amount` 명명 변경(P10/P23), `sector-stock.ts` 영향 범위 추가, `createDualLabelSlider` 삭제 불가(buy-settings.ts 사용), WS payload 하위 호환성 유지
- **각 Phase 완료 시**: 커밋 + HANDOVER.md 갱신 + 사용자 보고

### 아키텍처 전수 점검 — B-09 완료, 20개 미시작 (일시 보류)
- **완료**: B-01~B-09, F-01 (P0 전체 + B-06~B-09)
- **미시작**: B-10~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-10 (엔진 계좌/서비스) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 업종 점수 누적 가산점제 전환 구현 (승인 대기)
- **계획서**: `docs/plan_sector_bonus_points.md` (895줄 — 폭넓은 사전조사 + 설계 문제 해결 완료)
- **구현 순서** (계획서 섹션 9 — 3세션 구조):
  1. **Phase 1: 백엔드 전환 (1세션)** — 도메인+서비스+설정 통합 (11개 파일)
     - `models.py`: `MetricDef`/`DEFAULT_METRICS` 제거, `SectorScore` 필드 수정 (`scored_*` 제거, `total_trade_amount`→`avg_trade_amount` 명명 변경, `bonus_*` 신규 필드)
     - `sector_score.py`: `normalize_weight_values` 제거, `calculate_weighted_scores`→`calculate_bonus_scores` 재작성 (옵션 C 2패스, 컷오프 이관), `percentile_to_score` 신규
     - `sector_calculator.py`: `sector_weights`/`trim_*` 파라미터 제거, 트리밍 로직 제거, `calculate_bonus_scores` 호출로 교체
     - `engine_sector_confirm.py`, `sector_data_provider.py`, `engine_account_notify.py`, `settings_defaults.py`, `engine_settings.py`, `settings_file.py`, `telegram_bot.py`, `engine_service.py` — 참조/변수/인자 제거, WS payload 가산점 필드 추가
     - **검증**: 런타임 기동 + 신규 함수 단위 테스트 (기존 테스트는 Phase 3에서 수정)
  2. **Phase 2: 프론트엔드 전환 (1세션)** — UI+타입+바인딩 (8개 파일 + sliderConvert.ts 삭제)
     - `sector-settings.ts`: ④ 극단값 제외 + ⑤ 가중치 슬라이더 섹션 제거, "가산점 자동 계산" 안내문 추가, 섹션 번호 재정렬
     - `sector-ranking-list.ts`: 가산점 표시(0~300), 헤더 라벨 변경, `avg_trade_amount` 참조 변경
     - `sector-stock.ts` (신규 추가): `final_score`/`sectorScores` 참조 확인, `avg_trade_amount` 참조 변경
     - `types/index.ts`, `uiStore.ts`, `binding.ts`, `hotStore.ts` — 타입/상태/바인딩 전환
     - `sliderConvert.ts` 삭제 (sector-settings.ts 전용), `create-slider.ts` 유지 (buy-settings.ts 사용)
     - **검증**: `npm run build` + 브라우저 확인
  3. **Phase 3: 테스트 전환 (1세션)** — 백엔드 12개 + 프론트엔드 1개
     - `test_sector_score.py`: `TestNormalizeWeightValues`/`TestCalculateWeightedScores` 제거, `TestCalculateBonusScores`/`TestPercentileToScore` 신규
     - `test_sector_calculator.py`: `TestComputeSectorScoresTrimming`/`TestComputeSectorScoresWeights` 제거, `TestComputeSectorScoresWithBonus` 신규
     - `test_engine_sector_confirm.py`: mock 교체 (8개 테스트), `sector_weights`/`trim_*` mock 제거 (11개)
     - `test_settings_file.py`: `TestMigrateRankPrimaryToWeights`/`TestMigrateSectorWeights` 제거
     - 기타 8개 파일: `scored_trade_amount`→`avg_trade_amount` 참조 수정
     - `frontend/tests/utils/sliderConvert.test.ts` 삭제
     - **검증**: pytest 전체 통과 + ruff 0건 + 프론트엔드 빌드
- **주의**: WS payload 하위 호환성 — Phase 1에서 `total_trade_amount`→`avg_trade_amount` 명명 변경 시, 프론트엔드(Phase 2 전)가 일시적 에러. 해결: Phase 1에서 WS payload에 `total_trade_amount`와 `avg_trade_amount` 둘 다 전송(하위 호환), Phase 2 완료 후 `total_trade_amount` 제거.
- **시작점**: 사용자 "진행해" 지시 후 Phase 1부터 착수

### 2순위: engine_settings.py P20/P21 폴백 일괄 정리 — 전량 완료 (2026-07-13)
- 1차: 22곳 `or` 폴백 → `_v if _v is not None else 기본값` 통일
- 2차: 잔존 9곳 해결 — 복호화 실패 silent 1곳(logger.warning 추가), real 키 레거시 폴백 7곳(_pick_real_or_legacy helper + 복호화 실패 시 폴백 금지), max_position_size lambda 1곳(명시적 if 패턴)
- pytest 55 passed, 런타임 기동 정상

### 3순위: 아키텍처 전수 점검 P1 세션 (B-10)
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

- **engine_settings.py 내 `or` 폴백 패턴 (P20/P23 위반) — 전량 해결 완료**
  - **해결 완료 (2026-07-13)**: 1차 22곳 `or` 폴백 → `_v if _v is not None else 기본값` 통일. 2차 잔존 9곳(복호화 실패 silent 1곳, real 키 레거시 폴백 7곳, max_position_size lambda 1곳) 해결 — `_dec` 복호화 실패 시 `logger.warning` 추가, `_pick_real_or_legacy` helper로 real 키 복호화 실패 시 레거시 폴백 금지 + `logger.error`, max_position_size lambda → 명시적 if 패턴. pytest 55 passed.

- **pipeline_compute.py DYNAMIC_REG 처리 — 구독 실패 시에도 _subscribed_dynamic=True 설정 (P22 위반)**
  - 발견 일시: 2026-07-13 (실시간 데이터 수신율 문제 조사 중 발견)
  - **해결 완료 (2026-07-13)**: `subscribe_dynamic` 반환형 `None → bool` 통일 + DYNAMIC_REG 처리 시 성공 반환값 확인 후에만 `_subscribed_dynamic=True` 설정, 실패 시 `_PENDING_REG_CODES` 유지 (pipeline_compute.py:329-345, ls_connector.py, kiwoom_connector.py, engine_ws.py, connector_manager.py, broker_connector.py)

- **테스트 파일 ruff lint 에러 72건 (기존 존재, P23 일관성 위반 가능성)**
  - 발견 일시: 2026-07-13 (최초 17건 보고 후 4개 파일 17건 수정 완료, 전수 검사에서 추가 72건 발견)
  - **해결 완료 (17건, 4개 파일)**: `test_broker_router.py` (F401/F841×2/E731), `test_connector_manager.py` (F401), `test_engine_sector_confirm.py` (F401/F811×7), `test_pipeline_compute.py` (E402×3/F401) — 2026-07-13 수정, ruff 0건 + pytest 240 passed 확인
  - **해결 완료 (72건, 34개 파일)**: 2026-07-13 전량 해결
    - 1단계: `ruff --fix` 자동 수정 — F401 47건(unused import 제거) + F811 1건(중복 정의 제거)
    - 2단계: F841 20건 수동 수정 — `with patch(...) as mock_xxx:`에서 미사용 변수 `as mock_xxx` 제거 (10개 파일), `result = await ...` → `await ...`로 변경 (3건), 미사용 `mock_fh = MagicMock()` / `mock_cursor = AsyncMock()` 줄 제거 (3건)
    - 3단계: E402 3건 수동 수정 — 의도적 import 순서(헬퍼 함수 정의 후 백엔드 모듈 import, `initialize_queues()` 선행 필수)에 `# noqa: E402` 명시 (`test_daily_time_scheduler.py` 2건, `test_trading.py` 1건)
    - 검증: `ruff check backend/tests/` 0건 + `pytest backend/tests/` 2745 passed in 16.16s

- **test_engine_loop.py 12건 실패 — _init_ws_subscribe_state mock 누락 (P23 테스트 일관성)**
  - 발견 일시: 2026-07-13 (키움 토큰 발급 경로 복구 작업 중 발견)
  - **연관성 조사 완료 (규칙 4-1)**:
    1) 연관성: 실패 테스트들은 `run_engine_loop()`를 호출하며, `engine_loop.py:169`의 `_init_ws_subscribe_state()` 호출이 mock되지 않아 `RuntimeError: settings cache not initialized` 발생. 내 수정(`engine_settings.py`의 `confirmed_data_broker` 추가)과 무관 — 실패 위치는 `daily_time_scheduler.py:780`.
    2) 수정 전 비교: `git stash` 후 동일 12건 실패 확인 → 기존 실패 판정.
    3) 도입 커밋: `939d199` — 이 커밋에서 `engine_loop.py:169`에 `_init_ws_subscribe_state()` 호출 추가. 커밋 `939d199^` 기준으로 `test_engine_loop.py` 38 passed 확인. `939d199`에서 테스트 미갱신.
  - **원인**: 커밋 `939d199`에서 `engine_loop.run_engine_loop()` 내 WS 연결 이전에 `_init_ws_subscribe_state()` 호출을 추가했으나, `test_engine_loop.py`의 `TestRunEngineLoopInit`/`TestRunEngineLoopRestApi`/`TestRunEngineLoopAccountMasking` 클래스들이 이 호출을 mock하지 않아 `RuntimeError: settings cache not initialized` 발생. `test_state_initialized`는 `preboot_ready_event.set.assert_called()`를 검사하지 않아 통과.
  - **실패 12건**: `test_preboot_ready_event_set`, `test_token_ready_event_set_after_gather`, `test_no_valid_brokers_logs_warning`, `test_token_success_sets_access_token`, `test_token_failure_sets_access_token_none`, `test_rest_api_tr_ids_assigned`, `test_auto_trade_created_with_token`, `test_broadcast_buy_limit_status_called`, `test_broadcast_buy_limit_exception_handled`, `test_account_number_masked_in_log`, `test_short_account_number_not_masked`, `test_real_mode_warning_in_log`
  - **위반 원칙**: P23 (일관성) — 코드 변경 시 테스트 미갱신
  - **수정 방향**: `test_engine_loop.py`의 `run_engine_loop` 호출 테스트들에 `patch("backend.app.services.daily_time_scheduler._init_ws_subscribe_state", new_callable=AsyncMock())` 추가

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
