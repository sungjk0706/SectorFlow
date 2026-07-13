# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-13: 실시간 데이터 구독 기동 순서 경쟁 조건 해결 + 동적 구독 정합성 3건 수정 (P22/P10/P23)**
  - **목적**: 앱 재기동 시 간헐적 수신율 상승 정체 + "업종점수 미전송 — 수신율 임계값 미달" 장시간 지속 문제 근본 해결
  - **근본 원인**:
    1. `app.py:121-129` — `start_engine()`(엔진 루프 백그라운드) 후 `start_daily_time_scheduler()` 순차 호출 시, 엔진 루프가 WS 연결+구독+틱 수신까지 도달한 후 `_init_ws_subscribe_state()`가 실행되어 이미 수신된 틱 데이터를 None으로 리셋 → 수신율 0% 추락 → 임계값 재대기
    2. `engine_lifecycle.py:59-93` — `stop_engine()`이 `_PENDING_REG_CODES`와 동적 구독 해지 타이머를 정리하지 않음 → 이전 세션 잔존 상태가 신규 세션으로 누출
    3. `pipeline_compute.py:336-340` — DYNAMIC_REG 처리 시 `subscribe_dynamic_data` 실패해도 `_subscribed_dynamic=True` 설정 → 플래그와 실제 구독 상태 불일치
  - **해결 방안**:
    - 표준 기동 순서 적용 (초기화 → 연결 → 구독): `_init_ws_subscribe_state()`를 `engine_loop.run_engine_loop()` 내 WS 연결 이전에 실행 (engine_loop.py:165-169)
    - `start_daily_time_scheduler()`에서 `_init_ws_subscribe_state()` 중복 호출 제거 (daily_time_scheduler.py:1081-1084)
    - `stop_engine()`에 `cancel_all_dynamic_unreg_timers()` + `_PENDING_REG_CODES.clear()` 추가 (engine_lifecycle.py:71-74)
    - `subscribe_dynamic` 반환형 `None → bool` 통일 (ls_connector.py, kiwoom_connector.py, engine_ws.py, connector_manager.py, broker_connector.py — P23 일관성)
    - DYNAMIC_REG 처리 시 성공 반환값 확인 후에만 `_subscribed_dynamic=True` 설정, 실패 시 `_PENDING_REG_CODES` 유지 (pipeline_compute.py:329-345)
  - **수정 파일**: 백엔드 9파일(engine_loop.py, daily_time_scheduler.py, engine_lifecycle.py, pipeline_compute.py, engine_ws.py, ls_connector.py, kiwoom_connector.py, connector_manager.py, broker_connector.py)
  - **검증**: pytest 2741 passed, ruff 0건, 런타임 기동 OK (초기화→연결→구독 순서 로그 확인, 수신율 5초 만에 95.4% 임계값 통과, 에러 없음)
  - **커밋/푸쉬**: 사용자 승인 대기

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책, JIF 경계 이벤트 즉시 갱신 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, DataTable 컬럼 너비 안정화, applyIndexRefresh dead code 제거 + applyIndexData market_phase 갱신 — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 pytest 56 passed (test_engine_ws_dispatch.py). 커버리지 Phase 1~3 완료
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
- **재기동 시 수신율 상승 속도 확인** (이번 수정 후 기대 효과): 앱 재기동 시 수신율이 일관되게 정상 속도로 상승하는지 확인. 이전 증상(간헐적 정체, "업종점수 미전송 — 수신율 임계값 미달" 장시간 지속)이 해결되었는지 검증

### 3순위: engine_settings.py 인접 라인 P20 폴백 일괄 정리 — 완료 (2026-07-13)
- line 139-140: `sector_min_rise_ratio_pct` / `sector_min_trade_amt` — `or` 패턴 → `_v if _v is not None else 기본값` 패턴으로 통일 완료
- **잔존**: 같은 파일 내 다른 `or` 패턴 27곳 → "미해결 문제"에 신규 등록 (P20/P23 위반)

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

- **engine_settings.py 내 `or` 폴백 패턴 다수 잔존 (P20/P23 위반)**
  - 발견 일시: 2026-07-13 (engine_settings.py P20 폴백 일괄 정리 작업 중 발견)
  - **해결 완료 (2026-07-13)**:
    - `engine_settings.py:80` `max_daily_loss_limit` — `or -500000` → `_v if _v is not None else -500000` 패턴으로 수정 (dict 블록 밖으로 이동)
    - `engine_settings.py:81` `max_single_stock_exposure` — `or 20000000` → `_v if _v is not None else 20000000` 패턴으로 수정 (dict 블록 밖으로 이동)
    - `engine_settings.py:139-140` `sector_min_rise_ratio_pct` / `sector_min_trade_amt` — `or` 패턴 → `_v if _v is not None else 기본값` 패턴으로 수정
  - **미해결 잔존**:
    - **해결 완료 (2026-07-13, 매수설정 토글 작업 중)**: `engine_settings.py:67,118` — `int(merged.get("max_stock_cnt", 5) or 5)` — 0을 5로 치환하던 부분을 `flat.get` + `is not None` 패턴으로 수정 (max_stock_cnt_on 마이그레이션과 함께)
    - **P23 일관성 위반 (or 0 패턴, 0이 정상값)**: line 66, 70, 72, 73, 75, 77, 115, 117, 119, 122, 124, 125, 159 — `or 0` 패턴 13곳. 0이 정상값이므로 사실상 문제 없으나, `_v if _v is not None else 0` 패턴으로 통일 권장
    - **기본값 불일치 의심**: `engine_settings.py:206` — `int(merged.get("test_virtual_deposit", 10_000_000) or 0)` — 기본값 10_000_000이지만 or가 0으로 치환. None→10_000_000, 0→0으로 의도적일 수 있으나 패턴 불일치. `engine_settings.py:207` 동일
    - 수정 방향: P23 일관성 정리 시 일괄 처리

- **pipeline_compute.py DYNAMIC_REG 처리 — 구독 실패 시에도 _subscribed_dynamic=True 설정 (P22 위반)**
  - 발견 일시: 2026-07-13 (실시간 데이터 수신율 문제 조사 중 발견)
  - **해결 완료 (2026-07-13)**: `subscribe_dynamic` 반환형 `None → bool` 통일 + DYNAMIC_REG 처리 시 성공 반환값 확인 후에만 `_subscribed_dynamic=True` 설정, 실패 시 `_PENDING_REG_CODES` 유지 (pipeline_compute.py:329-345, ls_connector.py, kiwoom_connector.py, engine_ws.py, connector_manager.py, broker_connector.py)

- **테스트 파일 ruff lint 에러 72건 (기존 존재, P23 일관성 위반 가능성)**
  - 발견 일시: 2026-07-13 (최초 17건 보고 후 4개 파일 17건 수정 완료, 전수 검사에서 추가 72건 발견)
  - **해결 완료 (17건, 4개 파일)**: `test_broker_router.py` (F401/F841×2/E731), `test_connector_manager.py` (F401), `test_engine_sector_confirm.py` (F401/F811×7), `test_pipeline_compute.py` (E402×3/F401) — 2026-07-13 수정, ruff 0건 + pytest 240 passed 확인
  - **미해결 (72건, 34개 파일)**: 전체 `backend/tests/` 디렉토리 ruff 검사 결과 72건 잔존
    - 주요 파일: `test_engine_ws_dispatch.py` (8건), `test_daily_time_scheduler.py` (6건), `test_market_close_pipeline.py` (5건), `test_web_app.py`/`test_logger.py`/`test_broker_change.py` (각 4건) 외 28개 파일
    - 위반 원칙: P23 (일관된 통일성) — 테스트 파일 lint 일관성 미준수
    - 수정 방향: 47건은 `ruff --fix`로 자동 수정 가능 (F401/F811 unused import 제거), 25건은 수동 수정 필요 (F841 unused var, E731 lambda→def, E402 import 순서 등)

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
