# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-13: 수익 상세 페이지 요약/통계 카드 폰트 크기 통일 — 상단 라벨 11px→14px + 하단 라벨/값 12px→14px (P23)**
  - **현상**: 수익 상세 페이지 상단 요약 카드(당일/당월/누적 손익) 라벨이 11px(badge)로 너무 작았고, 하단 통계 카드 6개도 12px(label)로 작았음. 상단 라벨이 손익금액(14px)보다 작아 위계 반전.
  - **근본 원인**: `profit-shared.ts:82` 상단 카드 라벨이 `FONT_SIZE.badge`(11px, 배지/경고용)로 설정되어 카드 제목 역할과 불일치. `profit-detail.ts:467-472` 하단 통계 카드 라벨/값이 `FONT_SIZE.label`(12px)로 설정.
  - **수정 파일**: `frontend/src/pages/profit-shared.ts`, `frontend/src/pages/profit-detail.ts` (2개 파일)
  - **변경 내용**: 상단 카드 라벨 `FONT_SIZE.badge`(11px) → `FONT_SIZE.section`(14px). 하단 통계 카드 라벨/값 `FONT_SIZE.label`(12px) → `FONT_SIZE.section`(14px). 상단/하단 14px 통일.
  - **영향 범위**: `createSummaryCards`는 `profit-detail.ts`에서만 사용 → 다른 페이지 영향 없음.
  - **검증**: `npm run build` 성공 (✓ built in 2.07s). 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: (본 커밋)

- **2026-07-13: 에이전트/스킬 아키텍처 원칙 실행 절차 구체화 — 24원칙 체크리스트 + safe-trade P15/P16/P18 + 금지패턴 5개 + 잔존 프로세스 규칙 5-1 (P10/P16/P20/P21/P23)**
  - **현상**: 에이전트 스킬과 AGENTS.md가 24개 원칙 중 일부만 실행 절차로 구체화하여 사각지대 존재. safe-trade에 거래 핵심 원칙 누락, AGENTS.md에 실행 가능한 체크리스트 부재, 금지 패턴 5개 미참조, 용어 사전 미참조.
  - **근본 원인**: 각 스킬이 개별 원칙만 부분 명시, AGENTS.md 섹션2가 원칙 번호 나열만으로 실행 불가. 사용자가 코딩 지식 없으므로 에이전트 자력 준수 불가.
  - **수정 파일**: AGENTS.md, .devin/skills/{safe-trade,backend-fix,problem-solve,frontend-fix,db-backup}/SKILL.md, HANDOVER.md (7개 파일)
  - **변경 내용**: (1) AGENTS.md 섹션2 체크리스트 신설 — 백엔드 14항목+프론트엔드 3항목+금지패턴 5항목. (2) AGENTS.md 섹션3 규칙 5-1 신설 — 세션 종료 전 잔존 프로세스 완전 종료 강제. (3) safe-trade P15/P16/P18 추가. (4) backend-fix 금지 패턴 5개+RuntimeWarning 검증 추가. (5) problem-solve 사전조사 P10/P16/P20/P21/P22/P23/P24 구체화. (6) frontend-fix P21/P23 추가. (7) 5개 스킬 용어 사전(부록 L) 참조 추가. (8) HANDOVER.md 직전 완료 작업 2건 축소+미해결 문제 6건 삭제.
  - **영향 범위**: 프로덕션 코드 변경 없음. 이후 모든 코드 수정 시 에이전트가 24원칙 체크리스트로 점검. 거래 로직 수정 시 P15/P16/P18 강제 준수.
  - **검증**: git diff 7개 파일 114줄 추가/71줄 삭제. 잔존 프로세스 0건 확인(규칙 5-1 준수). 오타 1건 수정(safe-trade "반도시"→"반드시").
  - **커밋**: `77af288`

- **2026-07-13: test_engine_loop.py is_ws_subscribe_window dead code 19곳 제거 + _init_ws_subscribe_state 패치 누락 4곳 추가 (P16/P23)**
  - **현상**: (1) 19개 테스트에 `is_ws_subscribe_window` 패치 잔존 — `engine_stop_event.is_set()==True`로 while 루프 진입 불가 → 도달 불가 dead code (P16 위반). (2) 직전 커밋 `ee4b67d`에서 15곳만 `_init_ws_subscribe_state` 패치 추가하고 4곳 누락 — `test_state_initialized`, `test_finally_clears_broker_rest_apis`, `test_finally_running_set_false`, `test_finally_calls_stop_compute_loop`. 이 4곳은 `engine_loop.py:169` 실제 호출 시 `RuntimeError` → `except Exception` 포착 → finally 경로에서 우연히 통과 (P16 위반, 잘못 통과)
  - **근본 원인**: `engine_loop.py:300-304` while 루프 내 `is_ws_subscribe_window` 호출은 `engine_stop_event.is_set()==True` 시 도달 불가. 누락 4곳은 이전 커밋의 패치 추가 범위 누락
  - **수정 파일**: `backend/tests/test_engine_loop.py` (1개 파일, 19곳)
  - **변경 내용**: 19곳 `is_ws_subscribe_window` 패치 제거. 이중 4곳(427, 637, 669, 706)은 `is_ws_subscribe_window` → `_init_ws_subscribe_state` 교체, 나머지 15곳은 중복 패치 라인 제거. 최종 `_init_ws_subscribe_state` 19건으로 통일
  - **영향 범위**: `test_engine_loop.py` 내 `run_engine_loop()` 호출 테스트만. 프로덕션 코드 변경 없음
  - **검증**: pytest test_engine_loop.py 38 passed in 6.94s. ruff 0건
  - **커밋**: `087ca1f`

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

### 2순위: 아키텍처 전수 점검 P1 세션 (B-10)
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
