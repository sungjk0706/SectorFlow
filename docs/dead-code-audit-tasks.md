# SectorFlow 데드코드·불필요 참조 전수조사 태스크

> 작성일: 2026-07-26
> 기준 계획서: `docs/dead-code-audit-plan.md`
> 상태: 실행 대기
> 원칙: 세션마다 한 가지 묶음만 조사·수정·검증한다. 각 세션은 사용자 실행 승인 후에만 코드 수정을 시작한다.

---

## 1. 사용 방법과 공통 규칙

- 본 문서는 `dead-code-audit-plan.md`의 DC-01~DC-12 및 정적 분석 결과를 실제 실행 가능한 세션 단위로 분할한다.
- 상태 표기:
  - `☐` 미시작
  - `◐` 진행 중
  - `☑` 완료
  - `⊘` 보류 또는 유지 결정
- “참조 0건”은 삭제 승인과 동일하지 않다. 프레임워크 진입점, 외부 API 계약, 동적 설정, 테스트 계약 여부를 먼저 확인한다.
- 테스트에서만 사용되는 함수는 운영 경로에서 제거하기 전에 테스트가 보호하는 계약을 확인한다.
- 삭제 대상의 이름으로 `backend`, `frontend`, `tests`, `docs` 전체를 다시 검색한다. 삭제된 함수·변수·타입을 언급하는 docstring·주석·태스크도 함께 정리한다.
- 거래·주문·잔고·정산 관련 대상(세션 4)은 구현 전 `safe-trade` 절차를 적용하고, 실전 주문 경로를 변경하지 않는다.
- DB는 읽기만 하며 `backend/data/stocks.db` 및 모든 DB 파일을 삭제·덮어쓰기하지 않는다.
- 한 세션에서 여러 세션을 연속 수행하지 않는다. 세션 종료 시 해당 세션의 검증과 HANDOVER 갱신을 완료한다.

## 2. 전체 세션 진행 현황

| 세션 | 우선순위 | 대상 | 계획 상태 | 비고 |
|---|---|---|---|---|
| DC-S1 | P16/P24 | DC-01, DC-05, DC-06 | ☑ | DC-01 제거, DC-06 제거, DC-05 ⊘ 보류(테스트 참조 존재) |
| DC-S2 | P16/P24 | DC-02, DC-03, DC-04 | ☑ | DC-02 `shutdown_requested` 제거, DC-03 `MIN_CACHE_LIFETIME_SEC` 제거, DC-04 `confirmed_refresh_running` 제거 (읽기 2건 → 실제 유지되는 플래그로 전환) |
| DC-S3 | P16/P23/P24 | DC-07, DC-10 | ☑ | 키움 5일 조회·구형 WS FID 파서 |
| DC-S4 | P15/P16/P20/P22 | DC-08, DC-11 | ☑ | 서킷브레이커·정산 매수능력 검증. safe-trade 필수 |
| DC-S5 | P10/P16/P24 | DC-09, DC-12 | ☑ | DC-09 `get_total_buy_amount`/`get_total_pnl` 제거, DC-12 `changed_keys_general_save`/`load_integrated_system_settings_for_editing` + cascading 3함수 제거 |
| DC-S6 | P16/P24 | 테스트·스크립트 미사용 자산 | ☐ | import·fixture·지역 변수·unreachable code |
| DC-S7 | P16/P21/P23 | 정적 분석 오탐 및 프론트엔드 최종 확인 | ☑ | 오탐 9종 근거 확정(유지), DC-13 신규(삭제), pyflakes/ESLint 근본 해결 |
| DC-S8 | P16/P19/P20/P25 | 전체 잔존 검색·통합 검증 | ☐ | 모든 승인 세션 완료 후 최종 게이트 |

---

## 3. 세션별 실행 태스크

### 세션 DC-S1 — 운영 경로 0건 후보 1차 정리

**상태:** ☑ 완료  

---

### 세션 DC-S2 — `engine_state` 잔여 dead 상태 정리

**상태:** ☑ 완료  
**대상 원칙:** P10 SSOT, P16, P21, P24

#### 대상 코드

- `backend/app/services/engine_state.py:111`
  - `shutdown_requested`
- `backend/app/services/engine_state.py:146`
  - `MIN_CACHE_LIFETIME_SEC`
- `backend/app/services/engine_state.py:148`
  - `confirmed_refresh_running`
- `backend/tests/test_engine_state_groups.py`
- `backend/tests/test_web_app.py`
- `engine_state.py` 상단 설명·dead-code 후보 목록·관련 docstring

#### 수정 내용

1. `shutdown_requested`와 `MIN_CACHE_LIFETIME_SEC`의 운영 읽기·쓰기 0건을 재확인한다.
2. `confirmed_refresh_running`의 읽기 2건이 실제 상태 판정에 필요한지 호출 경로와 UI 상태를 확인한다.
3. 사용되지 않는 항목만 삭제하고, 메타 테스트는 “dead 상태 확인” 목적에 맞게 제거 또는 최종 상태 테스트로 전환한다.
4. `engine_state.py`의 그룹 목록·주석·문서에서 제거된 항목을 정리한다.
5. 엔진 종료·재기동·확정시세 갱신 상태에 영향을 주지 않는지 확인한다.

#### 검증 방법

- `engine_state` 속성 전체 참조 검색
- 엔진 상태 관련 백엔드 테스트
- 전체 백엔드 테스트
- RuntimeWarning 승격 기동 및 잔존 프로세스 확인
- 엔진 상태 API/프론트 표시가 기존과 동일한지 확인

---

### 세션 DC-S3 — 테스트 전용 데이터 조회·구형 WS 파서 검토

**상태:** ☑ 완료  
**대상 원칙:** P16, P23 일관성, P24

#### 대상 코드

- `backend/app/core/kiwoom_stock_rest.py:282`
  - `fetch_ka10081_all_stocks_5day`
- `backend/app/services/engine_ws_parsing.py:150,162`
  - `parse_fid9081_exchange`
  - `parse_fid290_session`
- `backend/tests/test_kiwoom_stock_rest.py`
- `backend/tests/test_engine_ws_parsing.py`
- 실제 장마감 파이프라인·WS 등록/수신 호출부

#### 수정 내용

1. 각 함수가 테스트 외 운영 경로에 연결되어 있지 않은지 다시 확인한다.
2. API·WS 스펙상 외부에서 직접 호출되는 공개 계약인지 확인한다.
3. 구형 또는 미사용 함수가 확정되면 운영 함수와 해당 기능만 검증하는 테스트를 함께 제거한다.
4. 아직 외부 계약이거나 향후 파이프라인 진입점이면 삭제하지 않고 `⊘`로 기록한다.
5. 구형 FID 파서 삭제 시 현재 수신 타입(`0B`, `0g` 등) 처리에 영향이 없는지 확인한다.

#### 검증 방법

- 키움 REST·WS 함수명과 API/파서 호출부 전체 검색
- 관련 단위·통합 테스트
- 전체 백엔드 테스트 및 RuntimeWarning 승격 기동
- 장마감 파이프라인과 실시간 WS 수신 경로 회귀 확인

---

### 세션 DC-S4 — 거래 안전 경로 관련 테스트 전용 함수 검토

**상태:** ☑ 완료  
**대상 원칙:** P15 단일 주문 경로, P16, P20, P22, P25

> 주문·정산 관련 코드이므로 수정 착수 전 `safe-trade` 절차를 적용한다. 실전투자 주문 경로는 변경하지 않고, 기본 검증은 테스트모드에서 수행한다.

#### 대상 코드

- `backend/app/services/circuit_breaker.py:116`
  - `reset_circuit_breaker`
- `backend/app/services/settlement_engine.py:55`
  - `check_buy_power`
- 관련 테스트:
  - `backend/tests/test_circuit_breaker.py`
  - `backend/tests/test_settlement_engine.py`
- 실제 주문 경로 `trading.py`, `buy_order_executor.py`, `settlement_engine.py` 호출 관계

#### 수정 내용

1. `reset_circuit_breaker`가 운영 수동 제어·복구·관리자 API의 잠재 진입점인지 먼저 확인한다.
2. `check_buy_power`가 `reserve_buy_power`로 대체된 과거 API인지, 독립적인 정책 검증 함수인지 확인한다.
3. 운영 경로가 없고 외부 계약도 없다는 승인 후에만 함수와 전용 테스트를 함께 제거한다.
4. 주문 단일 경로와 서킷브레이커 차단, 테스트모드 잔고·정산 상태는 유지한다.
5. 함수가 필요하면 삭제하지 않고 공개 목적과 호출 경로를 문서화하는 방향으로 보류한다.

#### 검증 방법

- safe-trade 체크리스트 및 모의투자/테스트모드 확인
- circuit breaker·settlement·trading 관련 타깃 테스트
- 백엔드 전체 테스트
- RuntimeWarning 승격 기동
- 매수·매도 단일 경로 및 서킷브레이커 차단 회귀 확인
- 실전 주문 호출을 발생시키지 않았는지 확인

---

### 세션 DC-S5 — 계좌 집계·설정 저장 보조 함수 검토

**상태:** ☐ 미시작  
**대상 원칙:** P10 SSOT, P16, P21, P24

#### 대상 코드

- `backend/app/services/engine_account.py:56,65`
  - `get_total_buy_amount`
  - `get_total_pnl`
- `backend/app/core/settings_store.py:112,431`
  - `changed_keys_general_save`
  - `load_integrated_system_settings_for_editing`
- 관련 테스트 및 계좌·설정 API 호출부

#### 수정 내용

1. 계좌 집계 함수가 API·Telegram·UI에서 동적으로 참조되는지 확인한다.
2. 설정 보조 함수가 현재 프론트 저장 흐름의 과거 계약인지 확인한다.
3. 운영·외부 계약 참조가 없다는 승인 후 해당 함수와 테스트 전용 테스트를 함께 제거한다.
4. 설정 SSOT(`settings_store.py`)와 계좌 SSOT를 중복 생성하거나 폴백으로 대체하지 않는다.
5. UI에 표시되는 계좌 금액·수익·설정 저장 결과가 변하지 않는지 확인한다.

#### 검증 방법

- 함수명·모듈 import·라우트·Telegram 명령 전체 검색
- 계좌/설정 관련 타깃 테스트
- 백엔드 전체 테스트 및 RuntimeWarning 승격 기동
- 프론트엔드 typecheck/build/test
- UI에서 계좌·수익·설정 저장 흐름 확인

---

### 세션 DC-S6 — 테스트·스크립트 불필요 참조 정리

**상태:** ☑ 완료  
**대상 원칙:** P16, P24, P25

#### 대상 코드

- `backend/tests/`의 pyflakes/vulture 보고 항목
  - 미사용 import: `test_data_manager.py`, `test_engine_ws_dispatch_isolation.py`, `test_engine_state_groups.py`, `test_kiwoom_rest.py`, `test_engine_loop.py`, `test_daily_time_scheduler.py`
  - 미사용 지역 변수·fixture: `mock_task`, `provider`, `mock_sw`, `sched_ctx`, `seconds`, `setup_master_cache`, `task`, `_UNREG_BATCH_PENDING`, `reset_cash_gate`
  - `test_notification_worker.py`의 unreachable code
- `backend/scripts/migrate_realized_pnl_cash.py`의 `sys` import

#### 수정 내용

1. 각 import·fixture가 pytest 자동 적용, patch side effect, teardown 또는 assertion에 간접적으로 필요한지 확인한다.
2. 미사용이 확정된 import·매개변수·지역 변수만 제거한다.
3. unreachable code는 예외 검증 의도를 유지하면서 테스트 흐름을 명확히 한다.
4. 테스트가 검증하는 운영 계약을 삭제하지 않는다.
5. 스크립트 import 제거 후 스크립트 문법·기동 경로를 확인한다.

#### 검증 방법

- 대상 테스트 파일 우선 실행
- `.venv/bin/python -m pytest backend/tests -q`
- `pyflakes backend` 및 `vulture backend --min-confidence 80`
- 테스트 수 감소 시 제거된 테스트의 사유와 검증 범위를 기록
- RuntimeWarning 승격 기동

---

### 세션 DC-S7 — 정적 분석 오탐·프론트엔드 최종 확인

**상태:** ☑ 완료  
**대상 원칙:** P16, P21, P23, P24

#### 대상 코드

- `backend/app/core/broker_connector.py`, `kiwoom_connector.py`, `ls_connector.py`
  - 추상 `subscribe`/`unsubscribe`와 `data_types`
- `backend/app/web/deps.py`
  - 개발 모드 인증 placeholder `credentials`
- `backend/app/config.py`, `backend/app/domain/models.py`, `backend/app/core/stock_filter.py`, `backend/app/services/engine_utils.py`
  - 동적 설정·모델·콜백 계약으로 오탐 가능성이 있는 항목
- `backend/app/core/settings_file.py:341`
  - `SecretValueState` 정적 분석 경고
- `frontend/src/` 및 `frontend/tests/`
  - export 함수·타입·인터페이스 전체 참조
- `frontend/src/components/common/info-tooltip.ts:99`
  - 별도 lint 품질 신호

#### 수정 내용

1. 프레임워크·추상 계약·동적 접근으로 유지해야 하는 항목의 근거를 확정한다.
2. 실제 미사용으로 판명된 항목만 별도 DC ID를 추가한 후 수정한다. 계획 밖 일괄 삭제는 금지한다.
3. 인증 placeholder와 TODO는 데드코드 삭제가 아닌 보안 설계 과제로 유지한다.
4. 프론트엔드 타입은 `tsconfig`와 실제 import/구조 사용을 대조하고, 근거 없이 export API를 삭제하지 않는다.
5. lint 오류는 데드코드와 분리해 별도 수정 항목으로 기록한다.

#### 검증 방법

- 백엔드 전체 참조 검색 및 정적 분석 재실행
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- `cd frontend && npm run test`
- ESLint 재실행 결과를 데드코드 결과와 분리 기록

#### 완료 결과 (DC-S7)

**오탐 확정 (유지, 근거 기록):**
- `broker_connector.py:55,60` / `kiwoom_connector.py:271,275` / `ls_connector.py:432,436` `data_types` — 추상 브로커 계약 시그니처 + 테스트 4건 호출. 운영은 `subscribe_stocks` 사용. 유지 (P16)
- `deps.py:13` `credentials` — 개발 모드 인증 자리표시자. 보안 전환 과제. 유지 (DC-S7 규칙3)
- `engine_utils.py:54` `*args` — `__aexit__` async context manager 프로토콜 필수. 유지
- `stock_filter.py:126` `parsed_fields` — dataclass 필드, `stock_filter.py:235` 설정 + 테스트 검증. 유지
- `domain/models.py:53` `sector_rank` — `buy_filter.py:247,256` 설정 + 테스트 검증. 유지
- `domain/models.py:64` `version` — `buy_filter.py:263,272` 카운터 증가 + 테스트 검증. 유지
- `config.py` `ENCRYPTION_KEY`/`LOG_LEVEL`/`model_config`/`get_settings` — 사용 중. 유지
- 프론트엔드 export — typecheck 통과, 미사용 export 0건. 유지

**실제 dead code (신규 DC-13, 제거 완료):**
- `config.py:47,48,52` `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`TRADING_LOG_PATH` — Pydantic Settings 필드, 소비처 0건. 텔레그램 SSOT는 settings.json(DB) → `engine_settings._build_telegram_settings()`, 로그 경로는 `logger.py:158` 고정. P10(중복 SSOT)/P21(사용자 착각) 위반 → 제거 + docstring 정리

**lint/품질 이슈 (근본 해결, DC-S7 규칙5):**
- `settings_file.py:344` pyflakes `SecretValueState` undefined — `TYPE_CHECKING` 블록 임포트 추가 (런타임 임포트 유지). pyflakes 0경고
- `info-tooltip.ts:99` ESLint `no-unused-expressions` — 삼항식 → if/else 분기 전환. ESLint 0경고

---

### 세션 DC-S8 — 전체 잔존 검색·통합 검증 게이트

**상태:** ☐ 미시작  
**대상 원칙:** P16, P19, P20, P23, P24, P25

#### 대상 코드

- DC-S1~DC-S7에서 실제 수정된 모든 파일
- 삭제된 함수·변수·상수·import·타입·인터페이스의 전체 저장소 참조
- `docs/dead-code-audit-plan.md`, 본 태스크 파일, `HANDOVER.md`

#### 수정 내용

- 새로운 코드 수정은 원칙적으로 수행하지 않는다.
- 잔존 참조·불일치 문서·누락된 테스트가 발견되면 해당 원인이 속한 이전 세션으로 되돌아가 수정한다.
- 각 세션 상태와 실제 커밋·검증 결과를 문서에 반영한다.
- 계획서의 후보 수와 해결·보류 수를 실제 결과와 일치시킨다.

#### 검증 방법

- 제거 대상 이름 전체 검색: `backend`, `frontend`, `tests`, `docs`
- `.venv/bin/python -m pytest backend/tests -q`
- `.venv/bin/python -W error::RuntimeWarning main.py`
- 잔존 프로세스 0건 확인
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- `cd frontend && npm run test`
- 데드코드 관련 정적 분석 재실행
- 문서와 코드의 DC ID·상태·검증 결과 일치 여부 확인

---

## 4. 공통 완료 기준

각 구현 세션은 다음 조건을 모두 만족해야 완료로 표시한다.

- [ ] 해당 세션 대상의 전체 참조·외부 계약·테스트 사용 여부 조사 완료
- [ ] 사용자 실행 승인 후에만 코드 수정
- [ ] 삭제 대상의 docstring·주석·테스트·문서 참조 정리
- [ ] 관련 타깃 테스트 통과
- [ ] 세션 범위에 맞는 전체 검증 통과
- [ ] 백엔드 세션은 RuntimeWarning 승격 기동 및 잔존 프로세스 확인
- [ ] 프론트엔드 세션은 typecheck·build·test 및 브라우저 확인
- [ ] P10/P16/P20/P21/P22/P23/P24/P25 영향 점검
- [ ] 세션 결과를 `HANDOVER.md`에 기록
- [ ] 세션별 커밋 생성. 푸시는 사용자가 별도 요청한 경우에만 수행

## 5. 보류·삭제 금지 항목

- `backend/data/stocks.db` 및 `*.db` 파일
- FastAPI 라우트·예외 핸들러·SPA fallback·WebSocket 엔드포인트
- 브로커 추상 메서드와 외부 브로커 API 계약
- 인증 placeholder와 토큰 검증 재활성화 TODO
- 동적 설정·Pydantic 모델 필드
- 프론트엔드 export 타입·인터페이스(실제 사용 그래프 확정 전)
- 주문·정산 안전장치(실전 모드 확인 및 safe-trade 승인 전)

## 6. 참고 파일

- `docs/dead-code-audit-plan.md`
- `backend/app/services/engine_state.py`
- `backend/app/core/settings_defaults.py`
- `backend/app/core/ls_rest.py`
- `backend/app/web/ws_manager.py`
- `backend/app/services/circuit_breaker.py`
- `backend/app/services/settlement_engine.py`
- `backend/app/services/engine_account.py`
- `backend/app/services/engine_ws_parsing.py`
- `backend/app/core/settings_store.py`
- `frontend/src/types/index.ts`
- `frontend/tsconfig.json`
- `HANDOVER.md`
