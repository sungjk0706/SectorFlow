# SectorFlow 결합도 조사 후속 실행 태스크

> 작성일: 2026-07-26
> 기준 계획서: `docs/coupling-audit-plan.md`
> 상태: 실행 대기
> 목적: 결합도 조사계획의 C-01~C-09를 세션당 하나의 실행 단계로 분할하고, 각 단계의 대상 코드·수정 범위·검증 방법을 고정한다.

---

## 1. 공통 실행 규칙

- 각 세션은 C 항목 하나만 수행한다. 다른 C 항목의 개선·리팩터링·파일 분할은 함께 진행하지 않는다.
- 각 세션은 **조사 → 사용자 실행 승인 후 필요한 최소 수정 → 검증 → 커밋 및 `HANDOVER.md` 갱신** 순서로 종료한다.
- 조사 단계에서는 전체 참조, producer/consumer, writer/reader, 관련 테스트, 기존 공통 자산을 다시 확인한다.
- 매트릭스·계약·호출 그래프·경계 기록은 실제 호출 경로와 코드 참조를 근거로 작성한다. 추측으로 소유자나 계약을 정하지 않는다.
- 정상 경로의 의미를 빈 값·`None`·임의 fallback으로 덮지 않는다(P20). 새 추상화는 실제 호출부에 연결되는 경우에만 만든다(P16).
- 기존 SSOT·공통 자산을 우선 재사용한다(P10/P23). 새 Store, 새 EventBus, 무분별한 범용 래퍼를 도입하지 않는다.
- 함수·타입·상수·파일을 이동하거나 제거할 때 이름으로 `backend`, `frontend`, `tests`, `docs` 전체를 재검색하고 관련 주석·docstring·테스트 설명도 함께 확인한다.
- DB 파일은 조사·수정 대상에서 제외한다. 주문·브로커·실시간 경로의 변경이 필요한 경우 해당 세션 범위를 벗어나지 않도록 중단하고 별도 승인을 받는다.
- 거래 경로가 포함된 C-04는 `safe-trade` 절차를 적용하며, `execute_buy()`/`execute_sell()` 단일 경로와 모의투자 안전을 유지한다.
- 문서만 수정하는 세션은 문서 링크·참조·상태 표를 검증한다. 운영 코드가 수정되는 세션은 백엔드 테스트와 RuntimeWarning 승격 기동 또는 프론트엔드 typecheck/build 및 브라우저 확인을 추가한다.

### 상태 표기

- `☐` 미시작
- `◐` 진행 중
- `☑` 완료
- `⊘` 조사 결과 결합도 개선을 적용하지 않고 유지

---

## 2. 전체 세션 진행 현황

| 세션 | 우선순위 | 대상 | 계획 상태 | 핵심 검증 |
|---|---|---|---|---|
| COUPLING-S1 | P0 | C-01 `engine_state` 상태 소유권 | ☑ | 69개 속성 owner/readers/writers 매트릭스 작성(`docs/coupling-engine-state-matrix.md`). 코드 수정 없음(조사·문서만). 후속 단일화 1순위: `sector_summary_cache` (7곳 writer). docstring 대조 1건 불일치(`positions`의 `kiwoom_account_parsing` 누락). |
| COUPLING-S2 | P0 | C-02 설정 키 영향 매트릭스 | ☑ | `docs/coupling-settings-impact-matrix.md` 작성 (525줄). DEFAULT_USER_SETTINGS 66키 + DEFAULT_SYSTEM_CONFIG 17키 + 동적 증권사 자격증명 + 파생 키 전체 파이프라인(DB→기본값→정규화→캐시→서비스→API/UI) 매트릭스화. 코드 수정 없음(조사·문서만). P10 SSOT 위반 후보 6건, P21 투명성 후보 1건, 검증 누락 키 다수, 단일화 우선순위 5건 식별. |
| COUPLING-S3 | P1 | C-03 WebSocket 이벤트 계약 인덱스 | ☑ | `docs/coupling-ws-event-contract-index.md` 작성 (575줄). WS 36개 구독 이벤트 + 4개 dead subscription 전수 인덱스화. 3 채널(prices/settings/orders) 구조, 40개 이벤트 producer/consumer/payload/Store 액션/CustomEvent 배칭 매트릭스. 코드 수정 없음(조사·문서만). P16/P21 위반 4건(dead subscription), P23 위반 8건(네이밍 6 + payload 불일치 2), P10/P24 위반 3건(중복 경로), 단일화 우선순위 9건 식별. |
| COUPLING-S4 | P0 | C-04 주문 호출 그래프 | ☑ | safe-trade 점검, 주문·리스크 테스트, RuntimeWarning 기동 |
| COUPLING-S5 | P1 | C-05 파이프라인 경계 | ☐ | 파이프라인·스케줄러 테스트, 전체 백엔드 테스트, RuntimeWarning 기동 |
| COUPLING-S6 | 중간 | C-06 브로커 core 역참조 | ☐ | import 방향·계약 대조, 브로커·WS 테스트, RuntimeWarning 기동 |
| COUPLING-S7 | 중간 | C-07 종목코드 정규화 표현 | ☐ | 입력/출력 경계 테스트, 백엔드 테스트, typecheck/build |
| COUPLING-S8 | 중간 | C-08 Store·페이지 직접 결합 | ☐ | producer/consumer 대조, 프론트 테스트, typecheck/build·브라우저 |
| COUPLING-S9 | 낮음~중간 | C-09 대형 프론트엔드 파일 | ☐ | fan-in/fan-out 검토, 관련 테스트, typecheck/build·브라우저 |

---

## 3. 세션별 실행 태스크

### 세션 COUPLING-S1 — C-01 `engine_state` 상태 소유권 매트릭스

**상태:** ☑ 완료 (매트릭스 문서 작성)
**대상 원칙:** P10 SSOT, P16 살아있는 경로, P23 일관성, P24 단순성, P25 격리된 실패
**결과:** `docs/coupling-engine-state-matrix.md`에 69개 속성의 owner/readers/writers/생명주기 매트릭스 작성. 코드 수정 없음(조사·문서만).
- 단일 writer 약 40개, 자연스러운 산재 13개, 단일화 후보 9개, 거래 관련 산재(변경 금지) 3개, dead code 후보 3개.
- 단일화 1순위 후보: `sector_summary_cache` (7곳 writer, 거래 비관련, docstring "가장 분산도 높음").
- docstring 대조 1건 불일치: `positions`의 `kiwoom_account_parsing.py:126` 누락 (세션 10 조사 시 누락).
- 후속 세션에서 `sector_summary_cache` 1개만 별도 승인 후 단일화 진행 권장.

#### 대상 코드

- `backend/app/services/engine_state.py`
  - `state`의 전체 속성, 특히 `integrated_system_settings_cache`, `login_ok`, `sector_summary_cache`, `positions`, `access_token`
- `backend/app/core/`, `backend/app/services/`, `backend/app/pipelines/`, `backend/app/web/`의 `engine_state` 및 `engine_state.state` 참조
- 상태를 갱신하는 lifecycle·scheduler·connector·route·WS 경로와 관련 테스트

#### 수정 내용

1. 속성별 owner, readers, writers, 생명주기, 갱신 빈도, 사용자 표시 여부를 실제 참조로 매트릭스화한다.
2. 다중 writer와 직접 `state` 접근을 구분하고, 이미 단일 소유권이 정리된 `connector_manager` 패턴과 비교한다.
3. 즉시 분리할 상태와 lifecycle 협업 때문에 유지할 상태를 구분한다. 모든 다중 참조를 위반으로 판정하지 않는다.
4. 실행 승인 후 변경이 필요할 때만 가장 변경 빈도와 위험도가 높은 한 상태의 읽기·쓰기 경계를 최소 범위로 좁힌다. 거래·WS·스케줄러를 한 번에 재설계하지 않는다.
5. 상태 의미, 초기화 순서, 기동 실패 격리, 사용자 표시 계약을 유지하고 새 전역 상태나 dead wrapper를 만들지 않는다.

#### 검증 방법

- 속성명으로 `backend`, `frontend`, `tests`, `docs` 전체 참조 재검색
- writer 수와 매트릭스 owner가 실제 코드와 일치하는지 정적 대조
- 변경 시 관련 engine lifecycle·scheduler·WS·state 테스트
- `.venv/bin/python -m pytest backend/tests -q`
- `.venv/bin/python -W error::RuntimeWarning main.py` 기동 후 잔존 프로세스 0건

---

### 세션 COUPLING-S2 — C-02 설정 키 영향 매트릭스

**상태:** ☑ 완료 (매트릭스 문서 작성)
**대상 원칙:** P10 SSOT, P20 폴백 금지, P21 사용자 투명성, P22 데이터 정합성, P23 일관성, P24 단순성
**결과:** `docs/coupling-settings-impact-matrix.md`에 설정 키 전체 파이프라인 매트릭스 작성. 코드 수정 없음(조사·문서만).
- 파이프라인 6단계 정의: DB 원본 → 기본값 보충 → 정규화(`build_engine_settings_dict` 9개 `_build_*`) → 메모리 캐시 → 서비스 소비자(28개 파일) → API/UI.
- 19개 키 그룹별 매트릭스: 자동매매 토글·시간(8), 투자모드·증권사·가상잔고(5), 매수 설정(12), NWS(4), 리스크 매니저(9), 레거시 리스크(3), 매도(11), 업종순위·필터(10), 슬라이더(3), 주문 간격(4), 수신율·구독한도(2), 종목별·브로커매핑(2), 스케줄러 토글(2), 타임테이블(4), UI(1), 수익요약(1), 텔레그램(5), 증권사 자격(동적), 시스템 설정(17).
- 정규화 변환 패턴 11종, 저장 검증 규칙 14종, PATCH 후처리 디스패처 11분기 정리.
- P10 SSOT 위반 후보 6건: `max_daily_loss_limit`/`daily_loss_limit` 중복, `max_single_stock_exposure`/`max_position_size` dead read, `tele_on`/`telegram_on` 복제, DEFAULT_SYSTEM_CONFIG 마켓시간 11키 vs 코드 상수, `boost_order_ratio_side` 레거시, `buy_interval_min` 레거시.
- P21 투명성 후보 1건: `confirmed_data_broker` PATCH 후처리 누락 (변경 시 재기동 필요하나 사용자 안내 없음).
- 검증 누락 키 다수: `buy_block_rise_pct`(양수만 허용해야 하나 검증 없음), `tp_val`/`ts_start_val`/`sell_offset`/`sell_custom_qty`/`max_daily_total_buy_amt`/`test_virtual_*` 등 수치 범위 검증 미존재.
- 단일화 우선순위 5건: (1) `sector_stock_layout` 원본 SSOT 명확화, (2) `confirmed_data_broker` PATCH 후처리 추가, (3) 레거시 리스크 3키 dead read 제거, (4) `tele_on`/`telegram_on` 중복 제거, (5) 수치 검증 누락 키 추가.
- 거래 관련 산재 1건(`trading.py`의 `time_scheduler_on` write)은 COUPLING-S1과 동일 변경 금지 범주.
- 후속 세션에서 위 5개 우선순위 항목 중 1개만 별도 승인 후 진행 권장.

#### 대상 코드

- `backend/app/core/settings_defaults.py`
- `backend/app/core/settings_file.py`
- `backend/app/core/settings_store.py`
- `backend/app/services/engine_settings.py`
- `backend/app/services/engine_state.py`의 `integrated_system_settings_cache`
- 설정을 읽거나 저장하는 백엔드 서비스·라우트와 프론트엔드 설정 타입·API·페이지·테스트
- `docs/duplication-audit-plan.md` 및 D-02의 시간 기본값 불일치 후보

#### 수정 내용

1. 설정 키별 원본(DB)·기본값·정규화·캐시·서비스 소비자·API·UI·테스트 연결을 매트릭스화한다.
2. 키 문자열, 타입, 기본값, 빈 값의 의미, 저장 전후 변환을 실제 코드와 대조한다.
3. 이미 통합된 기본값 SSOT와 캐시를 유지하고, 직접 dict 접근 중 변경 위험이 큰 계약만 우선순위화한다.
4. 실행 승인 후 수정하는 경우 한 계약 또는 한 키 묶음만 읽기 경계를 감싸며, 모든 설정을 새 추상화로 덮지 않는다.
5. 저장된 값과 서버 기본값을 프론트엔드 fallback이 임의로 대체하지 않도록 하고, 설정 화면과 주문 차단·엔진 상태 표시의 사용자 의미를 일치시킨다.

#### 검증 방법

- 설정 키·상수·타입명 전체 참조 및 fallback 문자열 검색
- 설정 저장/로드/정규화/캐시 관련 백엔드 테스트
- `.venv/bin/python -m pytest backend/tests -q`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 설정 저장값과 기본값 표시, 주문 차단 시각·상태 표시의 일치 확인
- `.venv/bin/python -W error::RuntimeWarning main.py` 기동 및 잔존 프로세스 0건

---

### 세션 COUPLING-S3 — C-03 WebSocket 이벤트 계약 인덱스

**상태:** ☑ 완료 (인덱스 문서 작성)
**대상 원칙:** P5 직접 호출·Queue 경계 유지, P10 SSOT, P16 살아있는 경로, P21 사용자 투명성, P23 일관성, P24 단순성, P25 격리된 실패
**결과:** `docs/coupling-ws-event-contract-index.md`에 WS 이벤트 전수 인덱스 작성. 코드 수정 없음(조사·문서만).
- WS 3 채널 구조 정의: prices(28 이벤트), settings(6 이벤트), orders(2 이벤트). 3 채널 모두 동일 `ws_manager` 싱글턴 공유 (채널 분리는 TCP 연결 분리일 뿐 이벤트 라우팅 분리 아님).
- 40개 이벤트 전수 인덱스: 36개 프론트엔드 구독 + 4개 dead subscription.
- P16/P21 위반 4건 (dead subscription): `engine-reload-complete`, `bootstrap-stage`, `avg-amt-progress`, `order-filled` — 백엔드 producer 전혀 없음. `bootstrap-stage`는 P21(사용자 투명성) 위반 (부트스트랩 진행 미표시).
- P23 위반 8건: 네이밍 underscore 6개(`circuit_breaker_open` 등) vs hyphen 34개, payload 필드 불일치 2건(`ws-subscribe-status` `index_subscribed` 누락, `account-update` 경량화/전체 분기).
- P10/P24 위반 3건 (중복 경로): `receive-rate` vs `sector-scores.status.receive_rate`, `engine-ready` vs `engine-reload-complete`(동일 액션), `confirmed-progress` vs `avg-amt-progress`(동일 액션).
- 다중 producer 6건: `index-data`(4곳, payload 혼용), `market-phase`(3곳, 부분 payload), `stock-classification-changed`(3곳), `buy-targets-update`/`sector-stocks-refresh`/`engine-ready`(각 2곳).
- CustomEvent 배칭 3종: `real-data-tick`/`orderbook-tick`/`program-tick` — hotStore `flushTickBatch()` rAF coalescing → 4개 페이지 consumer.
- 단일화 우선순위 9건 식별. 1순위: `bootstrap-stage` dead subscription (P21 위반).
- 후속 세션에서 위 9개 항목 중 1개만 별도 승인 후 진행 권장.

#### 대상 코드

- 백엔드 `backend/app/web/ws_manager.py`
- `backend/app/services/engine_account_notify.py` 및 WS broadcast 호출부
- 프론트엔드 `frontend/src/binding.ts`
- `frontend/src/stores/hotStore.ts`, `uiStore.ts`, `stockClassificationStore.ts`
- 페이지별 `addEventListener`, CustomEvent 배칭, 이벤트 타입 및 관련 테스트

#### 수정 내용

1. 이벤트별 이름·channel·producer·payload 필드·Store action·화면 consumer·갱신 빈도를 인덱스화한다.
2. 문자열 오타, producer/consumer 누락, payload 필드명·필수성 불일치를 먼저 식별한다.
3. 반복되거나 안전상 중요한 이벤트만 기존 타입·상수 자산에 연결할 후보로 정한다. 새 EventBus는 도입하지 않는다(P5).
4. 실행 승인 후 한 이벤트군만 명시 계약으로 승격하고 실제 producer, binding, Store, 화면을 모두 연결한다.
5. 주문 차단·엔진 저하·진행률 등 사용자에게 중요한 상태가 화면에서 사라지지 않도록 하며, 고빈도 이벤트의 배칭·실패 격리를 유지한다.

#### 검증 방법

- 이벤트명과 payload 필드로 백엔드·프론트엔드·테스트 전체 재검색
- 누락 producer/consumer 및 인덱스와 실제 호출 경로 정적 대조
- 관련 backend WS 테스트 및 frontend binding/Store 테스트
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 실시간 계좌·진행률·주문 차단 상태가 갱신되는지 확인
- 변경 시 `.venv/bin/python -m pytest backend/tests -q` 및 RuntimeWarning 승격 기동

---

### 세션 COUPLING-S4 — C-04 주문 호출 그래프와 side effect 경계

**상태:** ☑ 완료 (호출 그래프 문서 작성)
**대상 원칙:** P10 SSOT, P15 단일 주문 경로, P16 살아있는 경로, P20 오류 의미 보존, P21 사용자 투명성, P24 단순성, P25 격리된 실패

#### 대상 코드

- `backend/app/services/trading.py`의 `execute_buy()`/`execute_sell()` 및 내부 단계
- `backend/app/services/buy_order_executor.py`
- `backend/app/services/risk_manager.py`
- `backend/app/services/engine_account.py`
- `backend/app/services/settlement_engine.py`
- `backend/app/services/engine_account_notify.py`
- `backend/app/services/engine_state.py` 및 주문 실패 사유 상수·프론트엔드 상태 소비자

#### 수정 내용

1. 정책 판정, 설정·리스크 확인, 계좌 조회, 주문 전송, 테스트 체결, 정산, 기록, 알림, 플래그 갱신의 실제 순서를 호출 그래프로 고정한다.
2. 각 단계의 입력·출력·상태 변경·외부 side effect·실패 사유를 기록하고 중복 또는 우회 주문 경로가 없는지 확인한다.
3. 실행 승인 전에는 그래프 조사만 한다. 승인 후에도 순수 판정과 실행·기록·알림을 한 경계씩만 검토한다.
4. `execute_buy()`/`execute_sell()` 단일 진입점을 유지하고, 주문 우회·실전 전환·리스크 의미 변경을 만들지 않는다.
5. 모의투자/테스트 체결 안전장치, 주문 간격, 사용자용 차단 사유와 WS 알림 계약을 보존한다.

#### 검증 방법

- 주문 함수·호출부·실패 사유 상수·알림 payload 전체 참조 검색
- `safe-trade` 절차에 따른 실전/모의투자 경계와 단일 주문 경로 확인
- 주문·리스크·계좌·정산·알림 관련 대상 테스트
- `.venv/bin/python -m pytest backend/tests -q`
- `.venv/bin/python -W error::RuntimeWarning main.py` 기동 후 잔존 프로세스 0건
- 브라우저에서 주문 차단/실패 사유가 사용자에게 표시되는지 확인(운영 주문은 실행하지 않음)

---

### 세션 COUPLING-S5 — C-05 스케줄러·파이프라인·실시간 엔진 경계

**상태:** ☐ 미시작
**대상 원칙:** P8/P9 경계 보존, P10 SSOT, P11 이벤트 기반 처리, P16 살아있는 경로, P20 폴백 금지, P24 단순성, P25 격리된 실패

#### 대상 코드

- `backend/app/services/daily_time_scheduler.py`
- `backend/app/pipelines/market_close_pipeline.py`
- `backend/app/pipelines/pipeline_compute.py`
- `backend/app/pipelines/pipeline_compute_tick_handlers.py`
- `backend/app/services/engine_loop.py`
- `backend/app/services/engine_sector_confirm.py`
- scheduler·pipeline·WS·DB·업종·매수 후보 관련 테스트

#### 수정 내용

1. scheduler → pipeline → compute → candidate → notification의 단계별 입력·출력·소유 캐시·DB 저장·WS 진행률·주문 후보 side effect를 기록한다.
2. 시간 이벤트, 실시간 구독, 배치 계산, 업종 계산, 저장의 직접 호출과 실패 전파를 실제 그래프로 확인한다.
3. 기존 Queue·게이트·gateway 경계를 유지하고, 폴링(`while + sleep`)이나 새 EventBus를 도입하지 않는다.
4. 실행 승인 후 한 단계의 계약만 명시화하거나 경계를 좁히며, 데이터 구조·타이밍·진행률 의미를 변경하지 않는다.
5. 한 태스크 실패가 전체 엔진을 중단하지 않도록 기존 격리·로깅 패턴을 유지한다.

#### 검증 방법

- scheduler·pipeline 함수와 호출부, 캐시·DB·WS side effect 전체 참조 검색
- 단계별 매트릭스와 실제 호출 순서 정적 대조
- 파이프라인·스케줄러·엔진 루프·업종 계산 관련 대상 테스트
- `.venv/bin/python -m pytest backend/tests -q`
- `.venv/bin/python -W error::RuntimeWarning main.py` 기동 후 잔존 프로세스 0건
- 브라우저에서 장마감 진행률·업종 분석·매수 후보 상태가 정상 표시되는지 확인

---

### 세션 COUPLING-S6 — C-06 브로커 core의 services 역참조

**상태:** ☐ 미시작
**대상 원칙:** P4 증권사명 공통 침투 금지, P10 SSOT, P16 살아있는 경로, P23 계층 일관성, P24 단순성, P25 격리된 실패

#### 대상 코드

- `backend/app/core/kiwoom_connector.py`
- `backend/app/core/ls_connector.py`
- 위 모듈이 참조하는 `services/engine_state.py`, `engine_ws.py`, `daily_time_scheduler.py`, `ws_subscribe_control.py`
- `broker_factory.py`, `broker_registry.py`, 공통 broker protocol/interface와 브로커·WS·스케줄러 테스트

#### 수정 내용

1. core connector가 실제로 필요로 하는 상태·ACK·전송 결과·구독 결과를 의존성별로 목록화한다.
2. services 역참조가 필수 계약인지, 호출부에서 전달할 수 있는 결과인지, 이미 존재하는 broker 공통 자산으로 대체 가능한지 구분한다.
3. 증권사별 차이와 공통 인터페이스를 섞지 않고, 역참조 제거 후보의 import 방향과 실패 격리를 기록한다.
4. 실행 승인 후 가장 낮은 위험의 한 역참조만 공통 계약 또는 호출부 전달 방식으로 전환한다. connector 외부의 주문 정책을 변경하지 않는다.
5. 순환 import, 브로커별 테스트 격리, 연결 실패 시 다른 구성요소의 기동을 보존한다.

#### 검증 방법

- `core` → `services` import 전체 검색 및 의존 방향 대조
- broker factory/registry를 통한 실제 연결 경로 확인
- 키움·LS connector, WS 구독, scheduler 관련 대상 테스트
- `.venv/bin/python -m pytest backend/tests -q`
- `.venv/bin/python -W error::RuntimeWarning main.py` 기동 후 잔존 프로세스 0건
- 공통 로직에 `kiwoom_`/`ls_` 구현이 새로 침투하지 않았는지 정적 확인

---

### 세션 COUPLING-S7 — C-07 종목코드 정규화 표현의 의미 경계

**상태:** ☐ 미시작
**대상 원칙:** P10 SSOT, P16 살아있는 경로, P20 입력 오류 의미 보존, P22 데이터 정합성, P23 용어·타입 일관성, P24 단순성

#### 대상 코드

- `backend/app/core/settings_store.py`의 `normalize_stk_cd_key()`
- `backend/app/services/engine_symbol_utils.py`의 `_base_stk_cd()`
- `backend/app/services/data_manager.py`의 `_norm_stk_cd()`
- `frontend/src/stores/hotStore.ts`의 `normalizeStockCode()`
- 각 함수의 전체 호출부, DB·캐시 키, API·WS payload, 관련 백엔드·프론트엔드 테스트

#### 수정 내용

1. 함수별 입력 형식, 출력 보장, 접두사·시장 접미사·자리수 규칙, 허용 호출 계층, 사용 목적을 표로 비교한다.
2. 설정 키·기본 종목코드·DB/캐시 키·브라우저 데이터의 의미 차이를 분리해 통합 가능성과 통합 금지 사유를 판정한다.
3. 동일 계약이 확정되지 않으면 이름만 같은 공통 함수로 합치지 않고 `⊘`로 기록한다.
4. 실행 승인 후 의미가 동일하고 오류 경계가 보존되는 한 경로만 기존 공통 자산으로 전환한다.
5. 잘못된 코드 입력, 시장 접미사, 캐시 키 정합성, WS·API 표시 값을 임의 fallback으로 바꾸지 않는다.

#### 검증 방법

- 네 함수명·정규화 규칙·호출부 전체 검색
- 정상·접두사 포함·시장 접미사 포함·잘못된 입력의 경계 테스트
- `.venv/bin/python -m pytest backend/tests -q`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 종목 상세·실시간 목록·업종 화면의 종목코드 표시와 갱신 확인

---

### 세션 COUPLING-S8 — C-08 프론트엔드 Store와 페이지 직접 결합

**상태:** ☐ 미시작
**대상 원칙:** P10 SSOT, P16 살아있는 경로, P21 사용자 투명성, P23 공통 자산 재사용, P24 단순성, P25 격리된 실패

#### 대상 코드

- `frontend/src/stores/hotStore.ts`
- `frontend/src/stores/uiStore.ts`
- `frontend/src/stores/stockClassificationStore.ts`
- `frontend/src/binding.ts`, `frontend/src/settings.ts`
- `frontend/src/pages/*.ts`의 Store `getState()`·`setState()`·action·구독·cleanup 호출부
- 관련 Store·binding·페이지 테스트와 공통 컴포넌트

#### 수정 내용

1. 상태 필드별 producer·consumer·갱신 빈도·소유 action·mount/unmount cleanup·사용자 표시 여부를 목록화한다.
2. 직접 `setState()`가 필요한 경우와 action으로 감쌀 수 있는 경우를 구분한다.
3. 고빈도 데이터·인덱스 캐시·CustomEvent 배칭과 설정·엔진·시장·주문 차단·진행률의 책임 경계를 기록한다.
4. 새 Store를 만들지 않고, 실행 승인 후 한 상태군의 직접 쓰기만 기존 action 또는 공통 자산으로 최소 전환한다.
5. binding 오류가 전체 화면으로 전파되지 않도록 기존 격리·로깅을 유지하고, 주문 차단·엔진 상태 등 사용자에게 필요한 표시를 제거하지 않는다.

#### 검증 방법

- `getState`, `setState`, action, `addEventListener`, cleanup 호출부 전체 검색
- producer/consumer 매트릭스와 실제 Store binding·페이지 렌더링 경로 대조
- 관련 frontend Store/binding/page 테스트
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 실시간 목록, 업종 화면, 설정·엔진 상태, 주문 차단 표시와 페이지 전환 후 cleanup 확인

---

### 세션 COUPLING-S9 — C-09 대형 프론트엔드 파일의 변경 책임 집중

**상태:** ☐ 미시작
**대상 원칙:** P16 살아있는 경로, P21 사용자 투명성, P23 공통 UI 자산, P24 단순성, P25 격리된 실패

#### 대상 코드

- `frontend/src/layout/header.ts`
- `frontend/src/stores/hotStore.ts`
- `frontend/src/components/virtual-scroller.ts`
- `frontend/src/pages/profit-shared.ts`
- `frontend/src/pages/buy-target.ts`
- `frontend/src/pages/sector-stock.ts`
- `frontend/src/components/common/data-table-fixed.ts`
- 각 파일의 import/export, 테스트, 공통 컴포넌트·스타일·Store·이벤트 호출부

#### 수정 내용

1. 파일별 변경 이유, 책임 묶음, fan-in/fan-out, 재사용 여부, 상태·렌더링·이벤트·스타일의 경계를 실제 코드로 분류한다.
2. 줄 수만으로 분할하지 않고, 한 변경 이유가 독립될 때만 대상 파일 하나를 선택한다.
3. 기존 `components/common/`과 공통 스타일·포맷·타입 자산을 먼저 재사용하고, 공통화 실익이 없는 책임은 억지로 이동하지 않는다.
4. 실행 승인 후 한 파일의 한 책임만 분리하며 import 방향, public API, mount/unmount, 실시간 이벤트, 사용자 표시를 보존한다.
5. 분리 결과가 새 결합·순환 import·dead module을 만들지 않는지 확인하고, 실익이 없으면 `⊘`로 기록한다.

#### 검증 방법

- 대상 파일의 import/export·호출부·테스트 전체 검색 및 fan-in/fan-out 대조
- 분리 시 이동한 함수·타입·상수명으로 전체 저장소 재검색
- 관련 페이지·공통 컴포넌트·Store 테스트
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 헤더·가상 스크롤·수익·매수 후보·업종 화면의 표시·스크롤·실시간 갱신·페이지 전환 확인

---

## 4. 세션 종료 기록

각 세션 종료 시 해당 세션의 커밋과 `HANDOVER.md`에 다음 인덱스만 남긴다.

- 수행한 C 항목과 실제 변경 파일
- 조사만 수행했는지, 결합 경계를 실제로 좁혔는지, 또는 `⊘`로 유지했는지
- 대상 테스트·typecheck/build·RuntimeWarning·브라우저 검증 결과
- 다음 세션의 C 항목과 이 문서의 참조 경로
- 거래 경로·DB·비밀정보를 변경하지 않았는지 여부
