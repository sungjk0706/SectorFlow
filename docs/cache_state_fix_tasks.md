# 태스크 파일: 캐시·상태 정합성 구현

> 상태: 작성 완료 · 사용자 승인 대기
> 작성일: 2026-07-25
> 기준 설계서: `docs/cache_state_fix_plan.md`
> 다단계 진행: 설계·수정 계획 ✅ (`docs/cache_state_fix_plan.md`) · 세부 태스크 작성 ✅ · 구현 대기
> 관련 원칙: P10, P13, P15, P18, P21, P22, P23, P24, P25
> 관련 파일: `backend/app/services/settlement_engine.py`, `backend/app/services/dry_run.py`, `backend/app/services/trading.py`, `backend/app/services/trade_history.py`, `backend/app/services/buy_order_executor.py`, `frontend/src/stores/hotStore.ts` 외 세션별 목록 참조
> 관련 API/이벤트 스펙: 기존 주문 단일 경로(`execute_buy()`/`execute_sell()`), `settlement_state`, `sector-stocks-refresh`, `sector-stocks-delta`, `buy-targets-update`, `buy-targets-delta`, `realtime-reset`

---

## 0. 사전조사 결과 요약

### 0.1 의존성

| 파일 | 확인된 호출·변경 관계 | 기준 라인 |
|---|---|---:|
| `backend/app/services/settlement_engine.py` | 테스트모드 주문가능금액의 원천 상태. `reserve_buy_power()`가 매수 전 차감하고, `release_buy_power()`가 주문 전송 실패 시 복원한다. `on_buy_fill()`·`on_sell_fill()`·`reconcile_with_trades()`가 체결·재기동 정합성을 담당한다. | 30-32, 67-140, 188-318 |
| `backend/app/services/dry_run.py` | 테스트모드 가상 체결 경로. `fake_fill_event()` → `_apply_buy()`/`_apply_sell()` → 정산 엔진·거래 이력으로 연결된다. `pre_reserved=True`는 매수 중복 차감을 막는다. | 153-229 |
| `backend/app/services/trading.py` | 주문 단일 경로. 테스트모드에서 `reserve_test_buy_power()`를 호출하고, 주문 전송 실패 시 예약 금액을 복원한 뒤 `fake_fill_event()`를 예약한다. | 214-218, 396-500 |
| `backend/app/services/engine_strategy_core.py` | `reserve_test_buy_power()`가 가격·수량·일일 매수 한도를 정산 엔진으로 전달하는 어댑터다. | 31-43 |
| `backend/app/services/trade_history.py` | `trades` 원천 기록과 `_test_positions` 무효화, 거래 이력 기준 주문가능금액 재계산을 담당한다. | 99-125, 368-409 |
| `backend/app/services/engine_cache.py` | 테스트모드 기동 시 정산 상태 로드 후 `reconcile_with_trades()`를 호출한다. | 108-117 |
| `backend/app/services/risk_manager.py` | 테스트모드 주문가능금액 조회를 `settlement_engine.get_available_cash()`로 단일화한다. | 153-164 |
| `backend/app/db/stock_tables.py` | `settlement_state` 영속 저장·로드. DB 에러는 호출자에게 전파된다. | 1-18, 107-141 |
| `backend/tests/test_settlement_engine.py` | 정산 엔진의 로드·예약·복원·체결·충전 단위 테스트가 존재한다. 실패 경로와 재기동 대조 시나리오는 보강 대상이다. | 1-530 |
| `backend/tests/test_dry_run.py` | `pre_reserved=True/False` 중복 차감 방지와 가상 매도 정산을 검증한다. | 302-324 |
| `backend/tests/test_trading.py` | 테스트모드 매수 주문 전송·실패·예약 호출을 검증한다. | 188-205, 831-860 |
| `backend/tests/test_engine_cache.py` | 테스트모드 기동 시 정산 상태 로드와 대조 호출을 검증한다. | 16-25, 361-406 |

### 0.2 영향 범위

- **백엔드 핵심**: 테스트모드 정산 상태, 가상 체결, 매수 예약·실패 복원, 재기동 시 거래 이력 대조.
- **백엔드 연관**: 주문가능금액을 읽는 리스크 검사와 계좌 화면 브로드캐스트.
- **프론트엔드**: 2순위부터 `sectorStocks`와 `buyTargets`의 읽기 모델·갱신 계약, 4~6순위의 실시간 갱신·매수 차단 표시.
- **DB**: 기존 `settlement_state`와 `trades` 테이블만 사용한다. 현재 계획에는 스키마 변경이 없다. 스키마 변경이 발견되면 구현을 중단하고 DB 백업 승인 절차를 먼저 진행한다.
- **거래 안전**: 실전 주문·브로커 연결·API 키·리스크 임계값 변경은 범위에서 제외한다. 모든 거래 검증은 테스트모드에서만 수행한다.

### 0.3 아키텍처 원칙 부합

- **P10 ✅**: `trades`는 거래 원천, `_test_positions`는 파생 포지션 캐시, `settlement_state`는 정산 영속 상태로 역할을 구분한다. 동일 값을 별도 SSOT로 새로 만들지 않는다.
- **P13 ✅**: 틱 경로에 DB 조회를 추가하지 않고 메모리 정산 상태를 사용한다.
- **P15 ✅**: 주문 변경이 필요한 경우에도 `trading.py`의 `execute_buy()`/`execute_sell()` 단일 경로만 유지한다.
- **P18 ✅**: 테스트모드와 실전모드의 전략·리스크·주문 흐름은 유지하고, 돈 I/O인 가상 체결 경계만 테스트모드로 검증한다.
- **P21 ✅**: 정산 불일치·자동 보정·매수 차단 사유를 기존 브로드캐스트 경로로 화면에 알린다. 사용자에게 보이지 않는 자동 의사결정을 새로 만들지 않는다.
- **P22 ✅**: 예약·체결·거래 이력·재기동 대조의 불변조건을 테스트로 고정한다. 불일치는 조용히 덮지 않고 기록·차단·복구 기준을 명시한다.
- **P23 ✅**: 기존 정산 엔진, 거래 이력 계산, 공통 UI/이벤트 패턴을 재사용한다. 신규 주문 경로·중복 상수·중복 판정 함수를 만들지 않는다.
- **P24 ✅**: 9개 우선순위를 13개 세션으로 분할하고, 위험도가 높은 정산 검증을 먼저 처리한다. 조사만 필요한 세션은 구현 범위를 늘리지 않는다.
- **P25 ✅**: 정산 대조·브로드캐스트 실패가 전체 엔진을 조용히 중단시키지 않되, 정산 핵심 실패는 로그·검증 결과로 식별한다.

### 0.4 기존 공통 자산 확인

- **재사용**: `settlement_engine.reserve_buy_power()`, `release_buy_power()`, `on_buy_fill()`, `on_sell_fill()`, `reconcile_with_trades()`, `trade_history.compute_expected_orderable()`, `dry_run.fake_fill_event()`, `schedule_engine_task()`, `_safe_broadcast()`.
- **재사용**: 테스트의 `fresh_engine` 픽스처와 `_mock_helpers.py`의 awaitable mock 헬퍼.
- **재사용**: 프론트 `hotStore`, `binding.ts`, `components/common/`, `computeOrderBlockStatus()` 및 기존 표준 UI 상수.
- **신규 생성 제한**: 새 SSOT, 새 주문 함수, 새 이벤트 버스, 새 DB 테이블, 중복 KST/색상/차단 판정 함수는 만들지 않는다. 필요한 경우 기존 자산의 계약·호출 관계만 명확히 한다.

---

## 1. 단계 분할

> 규칙: 한 세션에는 한 단계만 진행한다. 각 세션은 태스크 확인 → 사용자 승인 → 수정/문서화 → 해당 단계 검증 → 커밋 및 인계 순서로 진행한다. 아래 파일 목록은 조사 결과 기준이며, 실제 구현 세션 시작 시 변경 전 재검색한다.

### 세션 1 — 테스트모드 정산 불변조건과 실패 시나리오 고정

- **목표**: 현재 코드를 변경하지 않고 예약·체결·실패·재기동 경로의 정합성 기준을 테스트로 표현한다.
- **수정 파일 목록**:
  - `backend/tests/test_settlement_engine.py`
  - `backend/tests/test_dry_run.py`
  - `backend/tests/test_trading.py`
  - `backend/tests/test_engine_cache.py`
- **파일별 변경점**:
  - 매수 예약 성공 후 주문 전송 실패 시 주문가능금액이 예약 전 상태로 복원되는 시나리오를 고정한다.
  - 예약 후 프로세스가 종료되거나 가상 체결 태스크가 실패한 경우 재기동 대조 기준을 고정한다.
  - `pre_reserved=True` 매수 체결에서 중복 차감이 없고, `pre_reserved=False` 직접 체결에서 한 번만 차감되는 조건을 고정한다.
  - 매도 체결 후 순매도대금 반영과 포지션 재구축 기준을 고정한다.
  - 여러 매수 예약이 순차적으로 현재 잔액을 반영하고 잔액을 초과하지 않는 조건을 고정한다.
- **변경하지 않을 범위**: 프로덕션 로직, 주문 조건, 수수료·세금·리스크 임계값, 실전모드.
- **검증 방법**: 관련 테스트 실행 → `.venv/bin/python -m pytest backend/tests/test_settlement_engine.py backend/tests/test_dry_run.py backend/tests/test_trading.py backend/tests/test_engine_cache.py -q -W error::RuntimeWarning`.
- **합격 기준**: 새 시나리오가 현재 동작의 실제 결함만 재현하고, 기존 정상 테스트가 모두 통과한다. 결함이 없으면 테스트만 추가하고 프로덕션 수정 없이 종료한다.
- **실패 시 중단 기준**: 주문가능금액이 거래 이력·정산 상태 중 어느 기준으로도 명확히 계산되지 않거나 실전 주문 경로가 호출될 가능성이 확인되면 구현을 중단하고 사용자 결정 항목으로 인계한다.
- **커밋 단위**: 정산 실패 시나리오 테스트만 포함.
- **다음 세션 인계 조건**: 재현 가능한 실패 테스트 또는 현재 구조가 모든 불변조건을 만족한다는 검증 결과가 `HANDOVER.md`에 기록됨.

### 세션 2 — 테스트모드 정산·주문가능금액 최소 보강

- **목표**: 세션 1에서 재현된 결함만 기존 단일 경로 안에서 최소 수정한다.
- **수정 파일 목록**:
  - 세션 1에서 결함이 확인된 `backend/app/services/settlement_engine.py`, `dry_run.py`, `trading.py`, `trade_history.py` 중 최소 파일
  - 해당 회귀 테스트 파일
- **파일별 변경점**:
  - 예약 차감·주문 실패 복원·가상 체결·재기동 대조의 호출 순서와 상태 전이를 정합성 있게 보강한다.
  - 거래 이력 기준 재계산이 필요한 경우 기존 `compute_expected_orderable()`와 `reconcile_with_trades()`를 확장하며 새 계산 원천을 만들지 않는다.
  - 실패 시 자동 매수를 조용히 계속하지 않고 기존 상태 게이트·브로드캐스트 패턴으로 차단 사유를 전달한다.
- **변경하지 않을 범위**: `execute_buy()`/`execute_sell()` 우회 경로, 수수료·세금 정책, 실전 계좌, DB 스키마.
- **검증 방법**: 관련 테스트 → 전체 백엔드 테스트 → `-W error::RuntimeWarning` 전체 테스트 → 테스트모드 런타임 기동 및 잔존 프로세스 0건 확인.
- **합격 기준**: 예약·실패·체결·매도·재기동 시 주문가능금액과 보유 종목이 거래 이력 기준과 일치하고, 실전 주문은 실행되지 않는다.
- **실패 시 중단 기준**: DB 스키마 변경, 모의투자에서만 안전장치 생략, 주문 단일 경로 이탈, 정합성 불일치의 무음 폴백 발견.
- **커밋 단위**: 테스트모드 정산 정합성 최소 수정과 회귀 테스트.
- **다음 세션 인계 조건**: 전체 관련 검증과 런타임 검증 통과.

### 세션 3 — `sectorStocks`·`buyTargets` 읽기 모델 및 갱신 계약 확정

- **목표**: 프론트에서 실시간 종목 데이터의 SSOT와 매수 후보 정적 정보를 분리하는 최소 읽기 모델을 확정한다.
- **수정 파일 목록**: `frontend/src/stores/hotStore.ts`, `frontend/src/types/index.ts`, 관련 프론트 테스트, 필요 시 `frontend/src/pages/buy-target.ts`.
- **파일별 변경점**: `sectorStocks`를 실시간 원천으로 두고 매수 후보의 정적 정보와 결합 규칙을 명시한다. `applyRealData()`의 초저지연 경로는 유지한다.
- **변경하지 않을 범위**: 업종 점수, 매수 후보 순위·선정, 매수 조건.
- **검증 방법**: 프론트 테스트 및 `cd frontend && npm run typecheck`.
- **합격 기준**: 설계 대안 A/B/C 중 선택한 모델에 대해 새 틱 전후 값이 일관되고 타입이 명확하다.
- **실패 시 중단 기준**: 두 화면이 서로 다른 실시간 SSOT를 계속 요구하거나 기존 틱 성능 경로를 보장할 수 없음.
- **커밋 단위**: 읽기 모델·타입·단위 테스트.
- **다음 세션 인계 조건**: 결합 규칙과 테스트가 확정됨.

### 세션 4 — 업종 종목·매수 후보 이벤트 계약 구현

- **목표**: 목록 새로고침·delta·초기화 이벤트에서 동일한 읽기 모델이 유지되도록 연결한다.
- **수정 파일 목록**: `frontend/src/stores/hotStore.ts`, `frontend/src/binding.ts`, `frontend/src/pages/buy-target.ts`, `frontend/src/components/sector-stock.ts`, 필요 시 `backend/app/services/sector_data_provider.py`, `engine_account_notify.py`, 관련 테스트.
- **파일별 변경점**: `sector-stocks-refresh`, `sector-stocks-delta`, `buy-targets-update`, `buy-targets-delta`, `realtime-reset` 순서를 검증하고 stale 실시간 필드를 남기지 않는다.
- **변경하지 않을 범위**: 백엔드 매수 후보 선정 알고리즘, 실전 주문.
- **검증 방법**: `cd frontend && npm run typecheck && npm run test && npm run build`, 관련 백엔드 테스트.
- **합격 기준**: 새로고침 직후 다음 틱 전에도 업종 종목과 매수 후보 화면의 현재가·등락률이 일치한다.
- **실패 시 중단 기준**: 이벤트 순서 변경으로 전체 화면이 비거나 실시간 틱 DOM 갱신이 중단됨.
- **커밋 단위**: 이벤트 계약과 프론트 회귀 테스트.
- **다음 세션 인계 조건**: 브라우저에서 두 화면의 상태 일치 확인.

### 세션 5 — `notify_cache` 책임과 재연결 경쟁 시나리오 검증

- **목표**: 전역 delta 기준점과 연결별 초기 스냅샷 상태의 실제 책임을 분리해 확인한다.
- **수정 파일 목록**: `backend/app/services/engine_account_notify.py`, `engine_initial_data.py`, `backend/app/web/routes/ws.py`, `ws_manager.py`, 관련 테스트.
- **파일별 변경점**: 새로고침·강제 재연결·다중 탭·스냅샷 중 실시간 이벤트 시나리오를 테스트로 고정하고 필요한 변경 계약을 정의한다.
- **변경하지 않을 범위**: 이벤트 버스 도입, 단일 프로세스 구조 변경, 거래 로직.
- **검증 방법**: 관련 WebSocket 테스트와 백엔드 전체 테스트.
- **합격 기준**: 한 연결의 초기화가 다른 연결의 delta 기준점을 덮어쓰지 않는 구조가 확인된다.
- **실패 시 중단 기준**: 연결별 상태와 전역 상태의 소유권을 코드만으로 확정할 수 없음.
- **커밋 단위**: 시나리오 테스트·책임 정의.
- **다음 세션 인계 조건**: 수정 계약과 경쟁 조건 재현 여부 확정.

### 세션 6 — `notify_cache` 생명주기 수정 및 WS 회귀 검증

- **목표**: 세션 5에서 확정한 책임 경계만 구현한다.
- **수정 파일 목록**: 세션 5의 영향 파일 중 최소 범위와 관련 테스트.
- **파일별 변경점**: 연결별 초기 스냅샷과 전역 delta 기준점의 초기화·갱신 순서를 정리한다.
- **변경하지 않을 범위**: 메시지 브로커, 재시도 폴링, 매수·매도 로직.
- **검증 방법**: WebSocket 단위/통합 테스트, 백엔드 전체 테스트, 런타임 기동.
- **합격 기준**: 새로고침·재연결·두 탭에서 누락·중복 delta가 없고 기존 초기 화면이 복원된다.
- **실패 시 중단 기준**: 초기 스냅샷과 delta 순서를 보장할 수 없음.
- **커밋 단위**: cache 생명주기 수정과 WS 회귀 테스트.
- **다음 세션 인계 조건**: 런타임에서 연결·해제·재연결 정상.

### 세션 7 — `applyRealData` 갱신 계약 문서화 및 구독 경로 점검

- **목표**: 고빈도 틱의 직접 mutation과 일반 store 구독의 경계를 문서·타입·테스트로 명확히 한다.
- **수정 파일 목록**: `frontend/src/stores/hotStore.ts`, `binding.ts`, `buy-target.ts`, `sell-position.ts`, `components/sector-stock.ts`, 관련 테스트.
- **파일별 변경점**: 직접 갱신 필드, `real-data-tick` payload, 구독·해제 규칙, 일반 subscriber와의 차이를 명시한다. 필요성이 입증된 경우에만 기존 공통 자산 기반 내부 API를 추가한다.
- **변경하지 않을 범위**: 새 이벤트 버스, 전체 store subscriber의 틱 실행, 매매 조건.
- **검증 방법**: 구독·해제 검색 검증, 프론트 테스트·typecheck·build.
- **합격 기준**: 고빈도 틱이 불필요하게 전체 subscriber를 실행하지 않고 각 화면이 계약된 이벤트만 사용한다.
- **실패 시 중단 기준**: 문서화만으로 오용 방지가 불가능하나 공통 API의 책임이 정의되지 않음.
- **커밋 단위**: 갱신 계약과 테스트.
- **다음 세션 인계 조건**: 틱 이벤트 구독 목록과 payload가 확정됨.

### 세션 8 — 매수 후보 payload 계약 정리

- **목표**: 백엔드 초기 payload/delta와 프론트 읽기 모델의 필드 의미를 일치시킨다.
- **수정 파일 목록**: `backend/app/services/sector_data_provider.py`, `engine_account_notify.py`, `engine_initial_data.py`, `backend/app/web/routes/ws.py`, `frontend/src/stores/hotStore.ts`, `binding.ts`, `pages/buy-target.ts`, 타입·테스트.
- **파일별 변경점**: 정적 후보 필드와 실시간 필드를 분리하고 null·미수신·원천 부재 표시 규칙을 고정한다. `_BUY_TARGET_CMP_KEYS`와 프론트 비교 기준을 대조한다.
- **변경하지 않을 범위**: 매수 후보 선정·순위·가드·차단 사유.
- **검증 방법**: 백엔드 테스트, `cd frontend && npm run typecheck && npm run test && npm run build`.
- **합격 기준**: 초기·update·delta payload가 같은 의미를 유지하고 화면 값이 즉시 올바르다.
- **실패 시 중단 기준**: payload 계약 변경이 기존 클라이언트와 호환되지 않음.
- **커밋 단위**: payload 계약과 양쪽 회귀 테스트.
- **다음 세션 인계 조건**: 백엔드·프론트 필드 매핑 표가 테스트와 일치함.

### 세션 9 — 주문 차단 UI 판정 통일

- **목표**: 매수 후보·보유 종목 화면이 기존 공통 차단 판정과 동일한 사유·우선순위를 표시하게 한다.
- **수정 파일 목록**: `frontend/src/pages/buy-target.ts`, `sell-position.ts`, `frontend/src/utils/order-block-status.ts`, 관련 공통 배지·테스트.
- **파일별 변경점**: 실제 중복만 제거하고 `computeOrderBlockStatus()`를 재사용한다. 자동매매 OFF·시간 외·리스크·실시간 지연·주문가능금액 부족 상태 표시를 비교한다.
- **변경하지 않을 범위**: 백엔드 차단 조건과 우선순위, 매수·매도 판단.
- **검증 방법**: `cd frontend && npm run typecheck && npm run test && npm run build`.
- **합격 기준**: 같은 상태에서 두 화면의 차단 사유·표시 우선순위가 일치하고 사용자가 이유를 확인할 수 있다.
- **실패 시 중단 기준**: 공통 함수로 통합할 수 없는 화면별 예외가 정의되지 않음.
- **커밋 단위**: 차단 표시 통일과 테스트.
- **다음 세션 인계 조건**: 브라우저에서 상태별 배지 일치 확인.

### 세션 10 — `engine_state` 상태 분류 및 참조 의존성 맵

- **목표**: 평면 상태의 외부 참조를 전수 조사하고 기능을 깨지 않는 그룹화 경계를 확정한다.
- **수정 파일 목록**: `backend/app/services/engine_state.py` 및 전체 `backend/app`·테스트의 참조 조사 결과 문서/테스트.
- **파일별 변경점**: 상태를 브로커·계좌·업종 분석·스케줄러·이벤트·안전 영역으로 분류하고 alias 증가 여부를 측정한다. 실제 코드 변경은 최소화한다.
- **변경하지 않을 범위**: 거래 상태를 임의로 이동, 주문·리스크 로직 변경.
- **검증 방법**: 전체 참조 검색, 백엔드 테스트, 런타임 경로 점검.
- **합격 기준**: 그룹화 대상·외부 참조·호환 경계가 명시되고 중복 SSOT가 생기지 않는다.
- **실패 시 중단 기준**: alias/fallback 증가 또는 순환 import 가능성 확인.
- **커밋 단위**: 분류·의존성 테스트만.
- **다음 세션 인계 조건**: 안전한 비거래 상태 그룹이 확정됨.

### 세션 11 — 비거래 상태 그룹화 및 회귀 검증

- **목표**: 세션 10에서 확정된 비거래 상태만 그룹화하고 기존 참조 호환성을 유지한다.
- **수정 파일 목록**: `engine_state.py`, `engine_loop.py`, `engine_lifecycle.py`, `engine_ws.py`, `engine_ws_reg.py`, `engine_account.py`, `daily_time_scheduler.py`, 관련 테스트.
- **파일별 변경점**: 브로커 세션·스케줄러 등 비거래 상태의 소유권을 명확히 하고 호출부를 최소 변경한다.
- **변경하지 않을 범위**: 거래 관련 상태·주문 조건·리스크 임계값.
- **검증 방법**: 전체 백엔드 테스트, `-W error::RuntimeWarning` 테스트, 런타임 기동, WS·엔진 시작/중지 점검.
- **합격 기준**: 기존 외부 동작이 동일하고 상태 갱신 위치가 단일화된다.
- **실패 시 중단 기준**: 엔진 기동·WS 연결·주문 상태에 영향이 발생함.
- **커밋 단위**: 상태 그룹화와 회귀 테스트.
- **다음 세션 인계 조건**: 테스트·런타임 검증 통과.

### 세션 12 — `active_connector` 연결 소유권 정리

- **목표**: `connector_manager`와 `active_connector`의 역할을 명확히 하고 연결·구독 경로의 fallback 중복을 제거한다.
- **수정 파일 목록**: `engine_state.py`, `engine_loop.py`, `engine_lifecycle.py`, `engine_ws.py`, `engine_ws_reg.py`, `engine_sector_confirm.py`, `daily_time_scheduler.py`, `market_close_pipeline.py`, `ws_subscribe_control.py`, `backend/app/web/routes/status.py`, 관련 테스트.
- **파일별 변경점**: 주 연결 소유자를 확정하고 필요한 호환 참조만 명시적 경계로 유지한다. 다중 브로커 라우팅을 단일 커넥터로 바꾸지 않는다.
- **변경하지 않을 범위**: 실전 주문 실행, 브로커 API 키·토큰, 다중 브로커 정책.
- **검증 방법**: 테스트모드 연결·구독·해제·재연결, 관련 백엔드 테스트, 런타임 기동.
- **합격 기준**: 연결 상태 표시와 구독 복원이 유지되고 테스트모드에서 실전 주문이 실행되지 않는다.
- **실패 시 중단 기준**: 연결 소유권이 불명확하거나 실전 경로에 영향을 줌.
- **커밋 단위**: 연결 참조 통일과 회귀 테스트.
- **다음 세션 인계 조건**: 테스트모드 런타임 연결 흐름 정상.

### 세션 13 — KST 상수 통합

- **목표**: 중복된 UTC+9 상수를 기존 공통 `_KST`로 통합해 시간 기준을 단일화한다.
- **수정 파일 목록**: `backend/app/core/constants.py`, `backend/app/core/trading_calendar.py`, `backend/app/services/auto_trading_effective.py`, `daily_time_scheduler.py`, `telegram_bot.py`, 관련 테스트.
- **파일별 변경점**: 중복 정의를 기존 상수 import로 대체하고 import cycle이 발생하는 모듈은 변경하지 않고 보고한다.
- **변경하지 않을 범위**: 거래일·장 운영시간·자동매매 허용시간 정책.
- **검증 방법**: 시간 경계·거래일 테스트, 전체 백엔드 테스트, 런타임 기동.
- **합격 기준**: KST 계산 결과와 장 상태 판정이 변경되지 않고 중복 상수가 제거된다.
- **실패 시 중단 기준**: import cycle 또는 시간 결과 변경.
- **커밋 단위**: KST 상수 통합과 시간 관련 회귀 테스트.
- **다음 세션 인계 조건**: 전체 검증 통과.

---

## 2. 사용자 결정 항목

- **현재 결정 상태**: 세션 1~13의 실행 범위는 `docs/cache_state_fix_plan.md`의 수정 계획을 기준으로 작성했으며, 구현 시작은 별도 사용자 승인 후 진행한다.
- **고정 전제**: 실전 주문은 실행하지 않으며, 테스트모드에서만 거래 관련 검증을 수행한다. 주문 경로·수수료·세금·리스크 임계값은 변경하지 않는다.
- **추가 결정 필요 시점**: 세션 1에서 현재 불변조건으로 판단할 수 없는 주문 실패·재기동 불일치가 확인될 때에만 사용자에게 UI 기준으로 영향과 선택지를 보고하고, 승인 전 구현하지 않는다.

---

## 3. 테스트 계획

### 백엔드 공통

- 관련 단위 테스트와 회귀 테스트.
- `.venv/bin/python -m pytest backend/tests -q -W error::RuntimeWarning`.
- `.venv/bin/python main.py`로 테스트모드 런타임 기동, RuntimeWarning 없음, 잔존 프로세스 0건 확인.
- 실전 주문·실전 계좌 연결은 실행하지 않는다.

### 프론트엔드 공통

- `cd frontend && npm run typecheck`.
- `cd frontend && npm run test`.
- `cd frontend && npm run build`.
- 브라우저에서 새로고침·재연결·매수 후보·보유 종목·차단 사유·계좌 상태를 확인한다.

### 정산 핵심 합격 기준

- 매수 예약 성공: 주문가능금액이 수수료 포함 예약액만큼 즉시 감소.
- 주문 전송 실패: 예약액이 정확히 복원되고 매수 재평가가 잘못 허용되지 않음.
- 가상 매수 체결: `pre_reserved=True`에서 중복 차감 없음.
- 가상 매도 체결: 세금·수수료 차감 후 순매도대금이 주문가능금액에 반영.
- 재기동: 거래 이력 기준 계산과 영속 `settlement_state`가 일치하거나 불일치가 사용자에게 보이는 방식으로 복구됨.

---

## 4. 런타임 검증 방법

1. 테스트모드 설정을 유지한 상태에서 백엔드를 기동한다.
2. 화면에서 테스트모드의 주문가능금액과 보유 종목을 확인한다.
3. 매수 후보 평가·예약·가상 체결·매도·재연결/재기동 시 화면의 주문가능금액과 보유 종목이 거래 이력과 일치하는지 확인한다.
4. 검증 중 실전모드 전환이나 실제 주문은 수행하지 않는다.
5. 백엔드 변경 세션은 테스트·런타임 기동·잔존 프로세스 확인까지 완료한 뒤 다음 세션으로 넘긴다. 프론트 변경 세션은 typecheck·test·build와 브라우저 확인까지 완료한다.

---

## 5. 실패·중단 기준과 인계 규칙

- 정합성 실패를 빈 값·기본값·조용한 예외로 덮지 않는다.
- 주문 단일 경로가 깨지거나 테스트모드와 실전모드의 전략·리스크 흐름이 달라지면 즉시 중단한다.
- DB 스키마 변경이 필요해지면 `stocks.db`, `stocks.db-shm`, `stocks.db-wal` 백업 승인 전에는 진행하지 않는다.
- 한 구성요소의 브로드캐스트·렌더링 실패가 전체 루프를 중단시키지 않도록 기존 격리 패턴을 유지한다.
- 각 세션 종료 후 변경 파일·검증 결과·미해결 문제·다음 세션 경로를 `HANDOVER.md`에 기록하고, 다음 세션은 사용자 승인 후 시작한다.
- 모든 단계 완료 후 최종 정리 커밋에서 본 태스크 파일과 기준 계획서의 보존·삭제 여부를 프로젝트 규칙에 따라 확인한다.
