# SectorFlow 프로젝트 전체 결합도 조사 후속 수정계획서

> 작성일: 2026-07-26  
> 상태: 조사 완료 / 수정 대기  
> 조사 범위: 백엔드 운영 코드·프론트엔드 운영 코드·관련 테스트 및 기존 감사 문서  
> 원칙: 본 문서는 조사 결과와 후속 작업 계획만 기록하며, 이번 세션에서는 코드·설정·DB를 수정하지 않음.

---

## 1. 조사 목적

한 모듈의 작은 변경이 여러 계층·파일·테스트·UI 계약으로 연쇄 전파되는 과도한 결합 지점을 찾았다. 특히 다음 두 가지를 기준으로 분류했다.

1. **P10(SSOT)**: 같은 상태·설정·이벤트 계약·정규화 규칙이 여러 위치에 독립적으로 표현되어 변경 시 불일치가 생기는가.
2. **P24(단순성)**: 전역 상태, 직접 참조, 분산 계약, 과도하게 큰 파일 때문에 한 책임의 변경 범위가 불필요하게 넓어지는가.

B21-01을 대표 사례로 삼았다. 암호화 상태 모델 자체보다 설정 저장·복호화 소비자·API 오류·프론트엔드 상태 표시가 서로 연결되어 한 줄 수준의 정책 변경이 8개 세션으로 확산되었다. 이 조사는 해당 현상이 특정 기능만의 예외인지, 프로젝트 전반의 구조적 패턴인지 확인하는 데 목적이 있다.

---

## 2. 조사 방법과 범위

### 2.1 조사 대상

- 백엔드: `backend/app/` 전체 109개 Python 파일
  - `core/`, `db/`, `domain/`, `pipelines/`, `services/`, `web/`
- 프론트엔드: `frontend/src/` 전체 91개 TypeScript 파일
- 참조 자료: `AGENTS.md`, `ARCHITECTURE.md`, `HANDOVER.md`, 기존 `docs/architecture_audit_plan.md`, `docs/architecture_audit_tasks.md`, `docs/duplication-audit-plan.md`, B21-01 문서
- DB 파일은 읽기·변경 대상에서 제외

### 2.2 확인 항목

- 모듈 import 방향과 계층 경계 침범
- 전역 mutable state의 읽기·쓰기 분산
- 설정 키·기본값·캐시의 참조 위치
- 백엔드 WebSocket 이벤트와 프론트엔드 바인딩·Store·화면의 계약 연결
- 주문·파이프라인·브로커 연결의 호출 체인
- 종목코드 정규화와 공통 UI/타입 자산의 중복 표현
- 파일 규모와 fan-in/fan-out이 높은 변경 허브
- 이미 해결된 감사 항목과 잔존 후보의 구분

### 2.3 정량 관찰

- 백엔드에서 `engine_state`를 참조하는 모듈이 다수이며, `engine_state.py` 자체가 69개 속성을 전역 상태로 보유한다고 문서화되어 있다.
- `engine_state.state`의 일부 속성은 여러 모듈에서 직접 쓰고 읽는다. 특히 `integrated_system_settings_cache`, `login_ok`, `sector_summary_cache`, `positions`, `access_token`이 변경 허브다.
- 대형 백엔드 파일: `daily_time_scheduler.py` 1,510줄, `market_close_pipeline.py` 1,425줄, `trading.py` 886줄, `trade_history.py` 674줄, `ls_connector.py` 832줄.
- 대형 프론트엔드 파일: `hotStore.ts` 751줄, `header.ts` 615줄, `virtual-scroller.ts` 555줄, `profit-shared.ts` 537줄, `buy-target.ts` 477줄.
- 기존 문서상 프론트엔드 WebSocket 바인딩은 18개 이상의 이벤트를 Store 액션에 연결한다. 이벤트 이름·payload·화면 소비자가 백엔드·`binding.ts`·두 Store·각 페이지에 분산되어 있다.

정량 수치는 결합도 우선순위를 정하기 위한 관찰값이며, 자동 리팩터링 기준이나 단독 위반 판정으로 사용하지 않는다.

---

## 3. 조사 결론

### 3.1 가장 우선적인 구조적 결합 후보

#### C-01. `engine_state` 전역 상태 허브 — 매우 높음

- 위치: `backend/app/services/engine_state.py`
- 관찰:
  - 엔진·브로커·계좌·업종 분석·스케줄러·이벤트·기동 플래그를 한 객체가 함께 소유한다.
  - `engine_state.state`가 `core`, `services`, `pipelines`, `web` 여러 계층에서 직접 참조된다.
  - 문서 자체가 여러 속성의 다중 쓰기를 기록하고 있으며, `integrated_system_settings_cache`는 10개 이상 파일에서 사용된다고 명시한다.
- 결합 형태: 전역 데이터 결합 + 쓰기 소유권 분산 + 계층 간 직접 참조.
- P10/P24 영향:
  - 상태의 SSOT는 하나지만, 상태별 소유권 SSOT가 충분히 분리되지 않아 한 속성 변경이 다수 모듈에 전파된다.
  - 작은 상태 모델 변경도 엔진 루프·스케줄러·브로커·라우트·WS 알림 테스트를 함께 깨뜨릴 수 있다.
- 우선순위: **P0**.
- 후속 계획: 거래·WS·스케줄러를 한 번에 재설계하지 않고, 속성별 소유자·허용 writer·읽기 API를 표로 확정한 뒤 가장 변경 빈도가 높은 상태부터 한 단계씩 격리한다. 기존 `connector_manager` 단일 소유권 정리 패턴을 기준으로 삼는다.

#### C-02. 설정의 세 겹 계약 — 매우 높음

- 위치: `settings_defaults.py`, `settings_file.py`, `settings_store.py`, `engine_settings.py`, `engine_state.integrated_system_settings_cache`, 다수 서비스·라우트·프론트엔드 설정 화면.
- 관찰:
  - DB 원본 → 정규화된 엔진 설정 → 메모리 캐시 → 서비스별 직접 키 조회 → 프론트엔드 `AppSettings`와 화면 fallback으로 이어진다.
  - 기본값 SSOT 통합은 일부 완료되었지만, 설정 키 문자열과 의미는 호출부에 반복된다.
  - 기존 중복 조사에서 `15:20` 기준과 프론트엔드의 `15:00` fallback 불일치가 이미 확인되었다.
  - `integrated_system_settings_cache`는 단일 캐시이지만 여러 소비자가 dict 키를 직접 사용하므로 계약 변경의 파급 범위가 넓다.
- 결합 형태: 설정 스키마·기본값·정규화·런타임 캐시·UI 표시의 분산 계약.
- P10/P24 영향: 설정 키 하나의 이름·타입·기본값 변경이 저장, 엔진, 스케줄러, 주문, UI, 테스트를 동시에 요구한다.
- 우선순위: **P0**.
- 후속 계획: 먼저 키별 원본/정규화/캐시/UI 소비자 매트릭스를 만들고, 이미 있는 기본값 SSOT를 유지하면서 변경 빈도와 위험도가 높은 설정만 단계별 읽기 계약으로 감싼다. 모든 설정을 새 추상화로 덮는 방식은 금지한다.

#### C-03. WebSocket 이벤트 계약의 분산 — 높음

- 위치: 백엔드 `ws_manager.py`·`engine_account_notify.py`·각 서비스 브로드캐스트, 프론트엔드 `binding.ts`, `hotStore.ts`, `uiStore.ts`, 페이지별 `addEventListener`.
- 관찰:
  - 이벤트 이름과 payload 생성은 백엔드 여러 서비스에 흩어져 있다.
  - `binding.ts`가 이벤트를 두 Store와 종목분류 Store에 직접 연결하며, 일부 고빈도 이벤트는 다시 `window` CustomEvent로 페이지에 전달한다.
  - 이벤트 타입 정의가 일부 핵심 데이터에만 있고 전체 이벤트 계약의 단일 목록은 확인되지 않았다.
- 결합 형태: 문자열 이벤트명 + 비공식 payload 계약 + 백엔드→binding→Store→페이지 다단 연결.
- P10/P24 영향: payload 필드 한 개의 변경도 producer, binding, Store 타입, 화면 렌더링, 관련 테스트를 연쇄 수정하게 된다. 오타·누락은 컴파일러가 잡지 못할 가능성이 있다.
- 우선순위: **P1**.
- 후속 계획: 전체 이벤트를 채널·producer·payload·Store action·화면 소비자 표로 고정하고, 먼저 반복되거나 안전상 중요한 이벤트만 명시 타입과 공통 상수로 승격한다. 새로운 이벤트 버스는 도입하지 않는다(P5).

#### C-04. 주문 경로와 엔진 상태·알림의 다중 결합 — 높음

- 위치: `services/trading.py`, `buy_order_executor.py`, `risk_manager.py`, `engine_account.py`, `settlement_engine.py`, `engine_account_notify.py`, `engine_state.py`.
- 관찰:
  - 주문 단일 진입점 자체는 `execute_buy()`/`execute_sell()`로 유지되고 있다.
  - 그러나 주문 함수가 리스크, 설정 캐시, 계좌 조회, 정산, 테스트 체결, 주문 간격, 엔진 상태, WS 알림, 설정 플래그 갱신에 직접 연결된다.
  - 주문 실패 사유는 백엔드 상수·알림 payload·프론트엔드 UI 상태에 걸쳐 있다.
- 결합 형태: 단일 주문 API 안의 정책·상태·외부 전송·기록 책임 집중.
- P10/P24 영향: 주문 정책 한 줄 변경이 위험 판정, 계좌 상태, 체결 후속 처리, UI 차단 표시 테스트까지 연쇄된다. 다만 거래 안전성 때문에 성급한 분리는 주문 우회 경로를 만들 위험이 있다.
- 우선순위: **P0**.
- 후속 계획: 주문 경로를 분리하기 전에 현재 실행 단계와 side effect를 호출 그래프로 고정한다. 이후 순수 판정과 실행·기록·알림의 경계를 한 단계씩 추출하되 `execute_buy()`/`execute_sell()` 단일 경로와 모의투자 안전을 유지한다. safe-trade 승인 없이 구현하지 않는다.

#### C-05. 스케줄러·장마감 파이프라인·실시간 엔진의 직접 결합 — 높음

- 위치: `daily_time_scheduler.py`, `market_close_pipeline.py`, `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `engine_loop.py`, `engine_sector_confirm.py`.
- 관찰:
  - 스케줄러가 WS 구독·해지, 장마감 파이프라인, 설정 캐시, 업종 재계산, 주문 후보 평가를 직접 호출한다.
  - 장마감 파이프라인이 `connector_manager`, 설정 layout, master cache, WS 등록 모듈, DB 저장, 업종·매수 후보 후속 작업을 함께 사용한다.
  - 대형 파일과 직접 import가 겹쳐 변경 영향 범위가 넓다.
- 결합 형태: 시간 이벤트·실시간 연결·배치 데이터·업종 계산·주문 후보의 호출 체인 결합.
- P8/P9/P10/P24 영향: 한 파이프라인 단계의 데이터 구조나 타이밍 변경이 실시간 구독·캐시·UI 진행률·매수 후보에 동시에 영향을 줄 수 있다.
- 우선순위: **P1**.
- 후속 계획: 먼저 단계별 입력·출력·소유 캐시·side effect를 기록하고, 이미 존재하는 Queue/게이트웨이 경계를 보존한 채 진행률·구독·계산·저장을 각각의 명시적 단계 계약으로 좁힌다. 폴링·새 EventBus는 도입하지 않는다.

### 3.2 중간 우선순위 결합 후보

#### C-06. 브로커별 `core` 구현이 `services`로 역참조

- 위치: `core/kiwoom_connector.py`, `core/ls_connector.py` 및 `services/engine_state.py`, `engine_ws.py`, `daily_time_scheduler.py`, `ws_subscribe_control.py`.
- 관찰: 브로커 커넥터가 공통 인터페이스만 구현하는 대신 엔진 상태·스케줄러·WS 알림·WS 등록 유틸을 직접 import한다.
- 영향: 브로커 연결/구독 변경이 엔진 서비스와 커넥터 테스트를 동시에 요구하고, 공통 경계가 약해진다. P4/P23과 연관되나 현재 즉시 증권사명 침투 위반으로 단정하지 않는다.
- 후속 계획: connector가 반환해야 하는 상태·ACK·전송 결과를 먼저 공통 계약으로 목록화하고, 실제 중복/필수 의존을 확인한 뒤 낮은 위험의 역참조부터 제거 검토.

#### C-07. 종목코드 정규화 규칙의 다중 표현

- 위치: `core/settings_store.py`의 `normalize_stk_cd_key()`, `services/engine_symbol_utils.py`의 `_base_stk_cd()`, `services/data_manager.py`의 `_norm_stk_cd()`, 프론트엔드 `hotStore.ts`의 `normalizeStockCode()`.
- 관찰: 이름과 구현이 유사하지만 설정 키, 기본 종목코드, DB/캐시 키, 브라우저 데이터라는 목적 차이가 섞여 있다.
- 영향: 접두사·시장 접미사·자리수 정책 변경 시 여러 계층이 연쇄적으로 영향을 받는다.
- 후속 계획: 즉시 통합하지 않고 입력 형식/출력 보장/허용 호출 계층을 표로 검증한다. 의미가 다른 정규화는 억지로 합치지 않는다(P24).

#### C-08. 프론트엔드 Store와 페이지의 직접 결합

- 위치: `stores/hotStore.ts`, `stores/uiStore.ts`, `stores/stockClassificationStore.ts`, `binding.ts`, `settings.ts`, 다수 `pages/*.ts`.
- 관찰:
  - 페이지가 Store의 큰 상태를 `getState()`로 직접 읽고 일부는 `setState()`까지 호출한다.
  - `hotStore`는 고빈도 데이터와 인덱스 캐시·CustomEvent 배칭을 함께 책임진다.
  - `uiStore`는 설정·엔진 상태·시장 상태·주문 차단·진행률을 함께 보유한다.
- 영향: 상태 필드 이동/이름 변경이 binding, 페이지, 테스트에 넓게 전파되고, hot/UI 상태 경계 변경이 화면별 cleanup과 함께 움직인다.
- 후속 계획: 새 Store를 추가하지 않고, 먼저 각 상태 필드의 producer·consumer·갱신 빈도·소유 액션을 목록화한다. 직접 `setState`가 필요한 경우와 액션으로 감쌀 수 있는 경우를 분리한다.

#### C-09. 프론트엔드 페이지·공통 자산의 파일 규모 집중

- 위치: `header.ts`, `hotStore.ts`, `virtual-scroller.ts`, `profit-shared.ts`, `buy-target.ts`, `sector-stock.ts`, `data-table-fixed.ts` 등.
- 관찰: 파일 분할 작업은 일부 완료되었지만, 상태·렌더링·이벤트·공통 스타일을 동시에 가진 대형 파일이 남아 있다.
- 영향: 공통 UI 변경이 여러 페이지와 테스트를 건드리고, 한 화면의 상태 변경이 화면 mount/unmount 및 실시간 이벤트 구독까지 연쇄된다.
- 후속 계획: 줄 수만으로 분할하지 않고 변경 이유별 책임·fan-in/fan-out·재사용 여부를 기준으로 한 파일씩 검토한다. 기존 `components/common/`을 우선 활용한다.

### 3.3 이미 해결되었거나 즉시 결합도 문제로 보지 않은 항목

- `connector_manager`를 단일 연결 소유자로 정리한 내용은 현재 구조상 개선된 경계로 확인되었다.
- `integrated_system_settings_cache`는 캐시 자체의 중복은 줄어든 상태이며, 잔여 문제는 캐시 내부 dict 계약과 writer 분산이다.
- `engine_state`의 일부 속성은 lifecycle 협업 또는 이벤트 준비 상태라서 모든 다중 참조를 결합도 위반으로 볼 수 없다.
- `normalize_stk_cd_key()`·`_base_stk_cd()`·`_norm_stk_cd()`는 목적 차이가 있어 현 단계에서 통합 대상으로 확정하지 않는다.
- 일반적인 `datetime`·`asyncio`·`logging` import와 공통 컴포넌트 import 반복은 결합도 위반으로 세지 않는다.
- 기존 `docs/duplication-audit-plan.md`의 D-01~D-06은 중복 정의 조사 결과이며, C-01~C-09는 모듈 경계·변경 영향 조사 결과다. 두 문서는 중복되지 않는다.

---

## 4. B21-01과의 비교

B21-01은 다음 결합 사슬을 실제로 보여준 사례다.

`encryption.py` 상태 모델 → `settings_file.py` 저장·복호화 경로 → `engine_settings.py`·`telegram_bot.py` 소비자 → 설정 API 오류 계약 → 프론트엔드 API 클라이언트 → 설정 Store/UI 상태 → 테스트·런타임 검증.

8세션이 걸린 원인은 단일 함수의 복잡도만이 아니라 다음의 **분산 계약**이었다.

- 저장 정책과 복호화 상태가 여러 소비자에 걸침
- 예외 표현이 백엔드 라우트와 프론트엔드 API 클라이언트로 전달됨
- 사용자 투명성 때문에 UI 상태·문구·저장 버튼 동작까지 변경됨
- 기존 주문·브로커 안전 경계를 건드리지 않고 전환해야 함

따라서 후속 작업은 B21-01처럼 기능별로 일괄 추상화하기보다, 먼저 변경 영향 매트릭스와 계약의 SSOT를 만든 뒤 한 세션 한 단계로 진행해야 한다.

---

## 5. 후속 조사·수정 순서

수정은 이 문서에 대한 별도 실행 승인 후, 한 세션에 한 단계만 진행한다.

1. **C-01 상태 소유권 매트릭스 작성** — 코드 수정 없이 `engine_state` 각 속성의 owner/readers/writers/생명주기/사용자 표시 여부 확정.
2. **C-02 설정 키 영향 매트릭스 작성** — 기본값·DB 저장·정규화·캐시·서비스·API·UI·테스트 연결을 필드별로 정리. 기존 D-02와 함께 우선 확인.
3. **C-03 이벤트 계약 인덱스 작성** — 전체 이벤트의 producer/channel/payload/action/consumer를 정리하고 누락·이름 불일치만 먼저 찾음.
4. **C-04 주문 호출 그래프 조사** — 수정하지 않고 정책 판정·주문 실행·기록·알림의 실제 순서를 고정. 거래 로직은 safe-trade 절차 적용.
5. **C-05 파이프라인 경계 조사** — scheduler → pipeline → compute → candidate → notification 경로의 입력·출력·side effect를 기록.
6. **C-06~C-09 우선순위 재평가** — 앞선 매트릭스와 실제 변경 빈도·장애 이력을 대조한 후, 한 번에 하나만 승인 요청.

각 단계의 기본 검증은 해당 영역의 기존 테스트와 정적 참조 확인이다. 실제 코드 수정이 발생하는 단계에서는 백엔드 테스트·RuntimeWarning 기동 또는 프론트엔드 typecheck/build·브라우저 확인을 해당 규칙에 따라 수행한다.

---

## 6. P10/P24 점검 요약

| 항목 | 현재 판단 | 핵심 이유 |
|---|---|---|
| P10 SSOT | 부분 준수, 변경 계약은 분산 | 캐시·일부 상태는 단일화되었으나 상태 writer·설정 키·WS payload·정규화 의미가 여러 계층에 표현됨 |
| P24 단순성 | 핵심 허브에 개선 여지 큼 | 전역 상태·대형 파일·직접 dict 접근·문자열 이벤트 계약이 작은 변경의 영향 범위를 키움 |
| P16 살아있는 경로 | 일부 개선 완료 | dead code 정리는 진행되었으나 결합도 조사의 후속 계획은 모두 실제 호출 경로를 먼저 고정해야 함 |
| P21 사용자 투명성 | 결합도를 높이는 정당한 요구 | 주문 차단·엔진 저하·암호화 상태를 숨길 수 없으므로 UI 계약을 단순 삭제해서 해결하면 안 됨 |
| P25 격리된 실패 | 일부 경계 존재 | WS·엔진 기동·알림에 격리 처리가 있으나 전역 상태·분산 이벤트 계약 변경 시 영향 격리가 약함 |

---

## 7. 이번 세션 안전 확인

- 수정한 운영 코드 없음
- 테스트 코드 수정 없음
- 설정 및 DB 파일 수정 없음
- 새 문서 `docs/coupling-audit-plan.md`만 작성
- `HANDOVER.md`에는 조사 완료 사실과 후속 문서 인덱스만 갱신
