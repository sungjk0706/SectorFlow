# SectorFlow 캐시·상태 구조 3차 교차 검증 기반 수정 계획서

> 작성일: 2026-07-25
> 문서 성격: 설계/수정 계획서
> 범위: 캐시·상태·큐 정합성 및 관련 화면 갱신 구조
> 현재 단계: 계획서 및 세부 태스크 파일 작성 완료. 구현 승인 대기.
> 다음 단계: `docs/cache_state_fix_tasks.md` 기준으로 세션 1(테스트모드 정산·주문가능금액 정합성 검증)부터 단계별 진행.

---

## 1. 작업 원칙 및 전제

### 1.1 안전 전제

- 거래 관련 변경은 테스트모드에서만 검증한다.
- 실전 주문 경로, 브로커 API 키, 계좌 정보는 변경하거나 실행하지 않는다.
- 주문 경로는 기존 `trading.py`의 단일 경로를 유지한다.
- DB 스키마 변경 또는 마이그레이션이 필요한 경우에만 `stocks.db`, `stocks.db-shm`, `stocks.db-wal`을 먼저 백업한다. 현재 계획은 기존 테이블을 활용하는 것을 우선하며, 백업이 필요한 변경은 구현 전 별도 확인한다.
- 한 세션에는 하나의 구현 단계만 진행한다. 각 단계가 끝나면 해당 단계의 테스트와 런타임 검증을 완료한 후 커밋하고 다음 세션으로 넘긴다.

### 1.2 아키텍처 원칙

- P10: SSOT와 파생 캐시의 경계를 명확히 한다.
- P13: 실시간 틱 경로에서 DB 조회를 추가하지 않는다.
- P15/P18: 단일 주문 경로와 테스트모드 동등성을 유지한다.
- P21: 캐시 불일치나 자동매매 차단 상태를 사용자에게 숨기지 않는다.
- P22: 기동·재연결·체결 후 파생 상태를 원천 데이터와 대조한다.
- P23: 같은 역할의 갱신·오류 처리·시간 상수 패턴을 통일한다.
- P24: 1인 로컬 앱에 불필요한 추상화는 만들지 않고, 실제 위험이 있는 경계만 정리한다.
- P25: 한 캐시·클라이언트·렌더링 실패가 전체 루프를 중단시키지 않도록 한다.

### 1.3 현재 코드 기준 중요한 정정

다음 항목은 기존 1차 보고서의 문제 제기를 그대로 구현하지 않는다.

1. 프론트 WebSocket 이벤트 핸들러별 `try/catch`는 현재 구현되어 있으므로 WS 핸들러 격리 자체를 신규 수정 대상으로 삼지 않는다.
2. `system_state_cache`는 임시 데이터뿐 아니라 `pending_settings_changes`를 영속 보관하므로 제거하지 않는다.
3. 테스트모드 `_test_positions`는 거래내역 기반 파생 캐시이므로 중복 SSOT로 취급하지 않는다.
4. KST 상수 중복은 실제 P23 정리 대상이지만 거래 정합성 항목보다 후순위로 둔다.

---

## 2. 최종 우선순위별 계획

### 1순위. 테스트모드 정산/주문가능금액 정합성 검증

#### 현재 문제 요약

테스트모드에는 다음 상태가 서로 다른 생명주기로 존재한다.

- 거래내역 기반 원천: `trade_history`의 매수·매도 기록
- 포지션 파생 캐시: `dry_run._test_positions`
- 엔진 런타임 포지션: `engine_state.state.positions`
- 주문가능금액/누적투자금: `settlement_engine._orderable`, `_accumulated_investment`
- SQLite 영속 상태: `settlement_state`

현재 구조 자체는 의도된 파생 캐시 구조지만, 아래 실패 경로의 정합성 보장이 계획서 단계에서 아직 입증되지 않았다.

- 매수 예약 후 주문 전송 실패
- 예약 차감 후 프로세스 종료
- 체결 기록 저장 성공/실패와 정산 저장 성공/실패의 순서 차이
- 매도 후 포지션 재구축 및 주문가능금액 회복
- 앱 재기동 후 거래내역·정산 상태·화면 상태 불일치
- 여러 매수 후보가 연속 평가될 때 예약 차감 경쟁

#### 수정 방향

1. 먼저 코드 수정 없이 현재 실행 경로와 테스트 커버리지를 시나리오별로 확정한다.
2. 테스트모드에서 원천 데이터와 파생 상태의 정합성 불변조건을 정의한다.
   - `trades`에서 재구축한 포지션과 `_test_positions` 일치
   - 주문 실패 시 예약 금액 복원 또는 복구 불가 상태의 명시적 차단
   - 재기동 후 `settlement_state`와 거래내역 기반 계산의 불일치 감지
   - 정산 실패가 매수 재평가를 조용히 허용하지 않음
3. 기존 매수 Lock과 `reserve_buy_power` 호출 경계를 확인한다.
4. 부족한 부분만 최소 범위로 보강한다. 새 주문 경로는 만들지 않는다.
5. 실전모드 수수료 기준 차이는 기존 HANDOVER의 별도 보류 항목으로 유지하며 이번 계획에서 임의로 통합하지 않는다.

#### 영향 범위

- 핵심: `backend/app/services/settlement_engine.py`, `backend/app/services/dry_run.py`
- 연관: `backend/app/services/trading.py`, `backend/app/services/buy_order_executor.py`, `backend/app/services/engine_account.py`
- 원천/영속: `backend/app/services/trade_history.py`, `backend/app/db/stock_tables.py`
- 테스트: `backend/tests/`의 dry-run, settlement, trading, trade-history 관련 테스트

#### 예상 작업량

- 2세션
  - 세션 1: 시나리오·불변조건 확정 및 테스트 태스크 설계
  - 세션 2: 테스트모드 검증/최소 수정 및 전체 관련 검증

#### 검증 방법

- 기존 관련 테스트 + 실패 시나리오 테스트
- `.venv/bin/python -m pytest backend/tests -q -W error::RuntimeWarning`
- 테스트모드 런타임 기동 확인
- 매수 예약/실패/복원, 매도/재기동 후 화면의 주문가능금액과 보유 종목 확인
- 실전 주문은 실행하지 않음

---

### 2순위. `sectorStocks` ↔ `buyTargets` 갱신 정합성

#### 현재 문제 요약

`sectorStocks`가 실시간 시세의 기준인데, `buyTargets`에도 실시간 필드가 복사되어 있다. 현재 `applyRealData()`는 양쪽 객체를 직접 변경한다.

또한 `applySectorStocksRefresh()`는 `sectorStocks`만 새 Record로 교체하고 `buyTargets`는 갱신하지 않는다. 따라서 업종 종목 새로고침 직후 다음 틱이 오기 전까지 매수 후보 화면의 현재가·등락률·체결강도 등이 이전 값으로 남을 수 있다.

이 문제는 단순 메모리 중복보다 **파생 뷰 무효화/동기화 계약 누락**이 핵심이다.

#### 수정 방향

1. SSOT를 `sectorStocks`로 확정한다.
2. `buyTargets`의 정적 필드와 실시간 파생 필드를 명확히 분리한다.
3. 세 가지 대안의 비용을 비교한 뒤 하나를 선택한다.
   - A: `buyTargets`에 실시간 필드를 유지하되 모든 목록 갱신에서 동기화
   - B: `buyTargets`에는 정적 매수 후보 정보만 저장하고 렌더링 시 `sectorStocks[code]`를 결합
   - C: store 내부에서만 결합된 읽기 모델을 제공하고 각 페이지의 직접 결합을 방지
4. 초저지연 `real-data-tick` DOM 갱신을 유지하면서 목록 새로고침 시 stale 값이 남지 않도록 한다.
5. `sector-stocks-refresh`, `sector-stocks-delta`, `buy-targets-update`, `buy-targets-delta`, `realtime-reset`의 순서를 함께 검증한다.

#### 영향 범위

- 핵심: `frontend/src/stores/hotStore.ts`, `frontend/src/binding.ts`
- 화면: `frontend/src/pages/buy-target.ts`, `frontend/src/components/sector-stock.ts`
- 백엔드 계약: `backend/app/services/sector_data_provider.py`, `backend/app/services/engine_account_notify.py`, `backend/app/services/engine_initial_data.py`
- 타입/테스트: `frontend/src/types/index.ts`, `frontend` 테스트

#### 예상 작업량

- 2세션
  - 세션 3: 읽기 모델/갱신 계약 설계 및 프론트 테스트 작성
  - 세션 4: 프론트·백엔드 이벤트 계약 구현 및 빌드 검증

#### 검증 방법

- `sector-stocks-refresh` 직후 새 틱이 오기 전 두 화면의 현재가가 일치하는지 확인
- 후보 추가·변경·제거와 업종 종목 추가·제거를 연속 발생시켜 코드별 상태 확인
- `realtime-reset` 후 실시간 필드가 일관되게 초기화되는지 확인
- `cd frontend && npm run typecheck`
- `cd frontend && npm run test`
- `cd frontend && npm run build`

---

### 3순위. `notify_cache` 재연결/초기화 시나리오

#### 현재 문제 요약

`notify_cache`는 전역 단일 인스턴스인데, 클라이언트별 초기 스냅샷 기준점처럼 보이는 역할도 함께 수행한다. WebSocket 초기 연결마다 `init_sent_caches()`가 호출되어 전역 델타 기준점이 재설정된다.

특히 다음 상황의 기준점 오염 가능성을 확인해야 한다.

- 브라우저 새로고침/재연결
- 두 개 이상의 브라우저 탭
- 초기 스냅샷 생성 중 실시간 브로드캐스트
- `build_initial_snapshot()`의 빈 종목 기준점과 `build_sector_stocks_payload()`의 실제 종목 기준점 사이
- 엔진 재기동 또는 실시간 필드 초기화

#### 수정 방향

1. 먼저 현재 `notify_cache`가 실제로 전역 브로드캐스트 델타 캐시인지, 클라이언트별 상태인지 책임을 확정한다.
2. 브로드캐스트용 전역 기준점과 클라이언트 초기 스냅샷 전송 상태를 분리한다.
3. 다중 탭을 지원하지 않을 경우에도 새 연결이 기존 클라이언트의 델타 기준점을 덮어쓰지 않도록 한다.
4. 초기 스냅샷 전송과 실시간 델타 사이의 순서 보장/누락 방지 방식을 설계한다.
5. 불필요하게 전체 이벤트를 다시 보내는 방식보다, 연결별 초기 스냅샷 + 전역 이후 델타 흐름을 우선한다.

#### 영향 범위

- 핵심: `backend/app/services/engine_account_notify.py`, `backend/app/services/engine_initial_data.py`
- WS 연결: `backend/app/web/routes/ws.py`, `backend/app/web/ws_manager.py`
- 연관: `backend/app/services/engine_lifecycle.py`, `backend/app/services/engine_cache.py`
- 테스트: WebSocket manager/route/notification 관련 백엔드 테스트

#### 예상 작업량

- 2세션
  - 세션 5: 연결·재연결 경쟁 시나리오 조사 및 테스트 설계
  - 세션 6: 캐시 생명주기 수정 및 WS 회귀 검증

#### 검증 방법

- 장중 새로고침 후 전체 목록·매수 후보·업종 점수·계좌 상태가 복원되는지 확인
- WebSocket 강제 단절/재연결 후 delta 누락·중복 여부 확인
- 두 탭 동시 연결/해제 시 한 탭의 상태가 다른 탭 때문에 바뀌지 않는지 확인
- 초기 스냅샷 전송 중 실시간 이벤트 발생 시 최종 화면과 백엔드 상태 대조
- 백엔드 전체 테스트 및 런타임 기동 검증

---

### 4순위. `applyRealData` 커스텀 갱신 계약 문서화

#### 현재 문제 요약

`applyRealData()`는 일반 store 구독을 우회하고 객체를 직접 변경한 뒤 `window`의 `real-data-tick` 이벤트로 특정 종목만 갱신한다. 이는 초저지연 목적에는 맞지만, 일반 `hotStore.subscribe()`와 갱신 방식이 달라 신규 화면에서 오용할 수 있다.

#### 수정 방향

1. 실제 구현을 변경하기 전에 고빈도 틱 경로와 일반 상태 갱신 경로를 문서화한다.
2. 직접 mutation되는 필드, 이벤트명, 이벤트 payload, 구독 해제 규칙을 명시한다.
3. 가능하면 기존 공통 자산을 활용해 `subscribeRealtimeTick`과 같은 명시적 내부 API를 검토하되, 새 이벤트 버스를 도입하지 않는다.
4. `hotStore`의 일반 store 구독으로 틱 갱신을 기대하는 코드가 없는지 검색한다.
5. 문서화만으로 충분한지, 작은 공통 API가 필요한지 측정 후 결정한다.

#### 영향 범위

- 핵심: `frontend/src/stores/hotStore.ts`
- 연관: `frontend/src/pages/buy-target.ts`, `frontend/src/pages/sell-position.ts`, `frontend/src/components/sector-stock.ts`
- 참고: `frontend/src/stores/store.ts`, `frontend/src/binding.ts`

#### 예상 작업량

- 1세션
  - 세션 7: 계약 문서화 및 기존 구독 경로 점검

#### 검증 방법

- 기존 `real-data-tick`, `orderbook-tick`, `program-tick` 구독/해제 경로 검색
- 고빈도 틱에서 전체 store subscriber가 불필요하게 실행되지 않는지 확인
- 프론트 타입체크·빌드·테스트

---

### 5순위. 매수후보 payload 계약 정리

#### 현재 문제 요약

백엔드 `_build_target_entry()`는 매수 후보 정적 정보와 `master_stocks_cache`의 실시간 필드를 함께 전송한다. 프론트는 동시에 `sectorStocks`를 실시간 SSOT로 간주한다. 초기 payload와 delta payload의 필드 의미가 혼재되어 있다.

#### 수정 방향

1. 매수 후보 payload를 정적 후보 정보와 실시간 종목 데이터로 구분한다.
2. 2순위에서 선택한 프론트 읽기 모델과 계약을 일치시킨다.
3. `null` 실시간 값, 아직 수신되지 않은 값, 종목이 `sectorStocks`에 없는 경우의 표시 규칙을 명시한다.
4. 백엔드의 `_BUY_TARGET_CMP_KEYS`와 프론트 비교 기준이 일치하는지 점검한다.
5. 매수 후보 선정·순위·가드·차단 사유 자체는 변경하지 않는다.

#### 영향 범위

- 핵심: `backend/app/services/sector_data_provider.py`, `backend/app/services/engine_account_notify.py`
- WS/스냅샷: `backend/app/services/engine_initial_data.py`, `backend/app/web/routes/ws.py`
- 프론트: `frontend/src/stores/hotStore.ts`, `frontend/src/binding.ts`, `frontend/src/pages/buy-target.ts`
- 타입/테스트: `frontend/src/types/index.ts`, 백엔드·프론트 관련 테스트

#### 예상 작업량

- 1세션
  - 세션 8: 이벤트 계약 정리 및 양쪽 회귀 테스트

#### 검증 방법

- 초기 스냅샷과 이후 update/delta의 필드가 같은 의미인지 확인
- 실시간 필드 제외 후에도 매수 후보 화면이 즉시 올바른 값을 표시하는지 확인
- 업종 점수·매수 후보 순위·가드 판정이 변경되지 않았는지 확인
- 백엔드 테스트, 프론트 타입체크/빌드/테스트

---

### 6순위. 차단 UI 로직 통일

#### 현재 문제 요약

매수 후보와 보유 종목 화면에서 주문 차단 배지를 갱신하는 로직이 반복될 가능성이 있다. 공통 함수 `computeOrderBlockStatus()`가 존재하므로 실제 두 화면이 모두 이를 사용하는지 확인해야 한다.

#### 수정 방향

1. 먼저 중복 판정의 실제 범위를 확인한다.
2. 공통 함수가 이미 사용되는 부분은 중복 추출하지 않는다.
3. 공통 함수 미사용 또는 화면별 예외가 있으면 공통 판정 함수를 SSOT로 삼는다.
4. 매수/매도 차단 사유와 표시 우선순위는 변경하지 않는다.

#### 영향 범위

- `frontend/src/pages/buy-target.ts`, `frontend/src/pages/sell-position.ts`
- `frontend/src/utils/order-block-status.ts`
- 관련 공통 배지 컴포넌트 및 프론트 테스트

#### 예상 작업량

- 1세션
  - 세션 9: 실제 중복 확인, 최소 통일, 프론트 검증

#### 검증 방법

- 자동매매 OFF, 시간 외, 리스크 차단, 실시간 지연 등 각 상태의 배지 표시 비교
- 매수 화면과 매도 화면의 차단 사유·우선순위 회귀 확인
- `npm run typecheck`, `npm run test`, `npm run build`

---

### 7순위. `engine_state` 그룹화

#### 현재 문제 요약

`engine_state`에 브로커 연결, 계좌, 업종 분석, 스케줄러, 이벤트, 안전 플래그 등 70개 이상의 상태가 한 객체에 평면적으로 존재한다. 현재 즉시 오류라고 단정할 수는 없지만, 상태 책임이 분산되고 이름 충돌·갱신 위치 추적 비용이 커진다.

#### 수정 방향

1. 먼저 그룹화 대상과 외부 참조를 전수 조사한다.
2. 1차 구현에서는 기존 속성 접근을 깨지 않는 최소 변경을 우선한다.
3. 거래 관련 상태를 먼저 묶지 않고, 브로커 세션/스케줄러 등 비거래 상태부터 분리 검토한다.
4. 그룹화가 alias/fallback 중복을 늘리면 진행하지 않는다.
5. 기능 변경이 아니라 구조 리팩토링이므로 별도 회귀 범위를 정의한다.

#### 영향 범위

- 핵심: `backend/app/services/engine_state.py`
- 연관: `engine_loop.py`, `engine_lifecycle.py`, `engine_ws.py`, `engine_ws_reg.py`, `engine_account.py`, `daily_time_scheduler.py`
- 전체 `backend/app`의 state 참조 및 테스트

#### 예상 작업량

- 2세션
  - 세션 10: 상태 분류/의존성 맵 및 설계
  - 세션 11: 비거래 상태 중심 그룹화와 회귀 검증

#### 검증 방법

- 전체 테스트
- 런타임 기동 및 런타임 경고 검증
- WS 연결/해제, 엔진 시작/중지, 장 운영시간 전환 확인
- 주문·리스크·포지션 관련 외부 동작이 동일한지 확인

---

### 8순위. `active_connector` 정리

#### 현재 문제 요약

`connector_manager`와 그 내부 주 커넥터를 가리키는 `active_connector`가 함께 존재하고 여러 곳에서 `connector_manager or active_connector` fallback을 사용한다. 현재는 편의 참조로 동작하지만 실제 연결 상태의 단일 진실원이 모호해진다.

#### 수정 방향

1. 모든 참조와 초기화·해제 순서를 전수 조사한다.
2. `connector_manager`를 연결 상태의 주 소유자로 할지 확정한다.
3. `active_connector`가 필요한 단일 브로커 호환 경로가 있으면 명시적 deprecated 경계로 남긴다.
4. 다중 브로커 라우팅을 단일 커넥터 fallback으로 바꾸지 않는다.
5. 연결 관리 변경은 실시간 주문·구독에 영향을 주므로 테스트모드에서만 검증한다.

#### 영향 범위

- `backend/app/services/engine_state.py`, `engine_loop.py`, `engine_lifecycle.py`
- `engine_ws.py`, `engine_ws_reg.py`, `engine_sector_confirm.py`
- `daily_time_scheduler.py`, `market_close_pipeline.py`, `ws_subscribe_control.py`
- `backend/app/web/routes/status.py`, 관련 테스트

#### 예상 작업량

- 1세션
  - 세션 12: 참조 통일 및 연결/구독 회귀 검증

#### 검증 방법

- 테스트모드에서 연결 초기화·구독·해제 흐름 확인
- 연결 상태 표시, 재연결 후 구독 복원 확인
- 관련 백엔드 테스트 및 런타임 기동
- 실전 계좌 연결/주문은 실행하지 않음

---

### 9순위. KST 상수 통합

#### 현재 문제 요약

`UTC+9` 시간대 상수가 여러 모듈에 중복 정의되어 있다. 현재 값은 동일하지만 P23 일관성과 향후 변경 위험이 있다.

#### 수정 방향

1. 기존 `backend/app/core/constants.py`의 `_KST`를 공통 기준으로 삼는다.
2. 각 모듈의 중복 정의를 import로 대체한다.
3. 거래일·장 운영시간·자동매매 허용시간의 결과가 변경되지 않음을 확인한다.
4. import cycle이 발생하면 통합하지 않고 현재 구조를 유지하며 별도 보고한다.

#### 영향 범위

- `backend/app/core/constants.py`
- `backend/app/core/trading_calendar.py`
- `backend/app/services/auto_trading_effective.py`
- `backend/app/services/daily_time_scheduler.py`
- `backend/app/services/telegram_bot.py`

#### 예상 작업량

- 1세션
  - 세션 13: 상수 통합 및 시간 관련 테스트/런타임 검증

#### 검증 방법

- 거래일·장 상태·자동매매 허용 여부 관련 테스트
- KST 경계 시간 테스트
- 런타임 기동 및 전체 백엔드 테스트

---

## 3. 단계별 진행 순서 요약

| 구현 세션 | 대상 | 핵심 이유 |
|-----------|------|-----------|
| 1~2 | 테스트모드 정산/주문가능금액 | 주문 안전성 최우선 |
| 3~4 | `sectorStocks` ↔ `buyTargets` | 화면/상태 정합성 및 후보 데이터 계약 기반 |
| 5~6 | `notify_cache` | 재연결·초기화 후 델타 누락 방지 |
| 7 | `applyRealData` 갱신 계약 | 이후 프론트 상태 변경의 기준 문서화 |
| 8 | 매수후보 payload | 백엔드·프론트 SSOT 계약 일치 |
| 9 | 차단 UI | 사용자 투명성과 화면 일관성 |
| 10~11 | `engine_state` 그룹화 | 기능 안정화 후 구조 리팩토링 |
| 12 | `active_connector` | 연결 소유권 명확화 |
| 13 | KST 상수 | 낮은 위험의 일관성 정리 |

총 예상: **13개 구현 세션**. 단, 조사·설계만 필요한 항목은 구현 태스크 세션과 통합할 수 있으며, 테스트 실패 또는 영향 범위 증가 시 다음 단계로 분리한다.

### 세션당 공통 흐름

1. 해당 세션의 세부 태스크 파일 확인
2. 수정 전 의존성·영향 범위·공통 자산·P10/P16/P20/P21/P22/P23/P24/P25 점검
3. 사용자 승인 확인
4. 테스트모드에서 최소 변경
5. 단계별 테스트 및 런타임/빌드 검증
6. 결과를 `HANDOVER.md`에 기록하고 커밋
7. 다음 세션으로 인계

---

## 4. 다음 세션에서 작성할 세부 태스크 파일 구조

다음 세션은 이 계획서를 그대로 구현하지 않고, 먼저 `docs/cache_state_fix_tasks.md` 세부 태스크 파일을 작성한다.

태스크 파일에는 각 구현 세션별로 다음을 포함한다.

- 작업 목적
- 수정 대상 파일·함수
- 사전 조사 결과와 호출 관계
- 변경하지 않을 범위
- 사용자 결정 필요 항목
- 테스트 시나리오와 합격 기준
- 실패 시 중단 기준
- 커밋 단위
- 다음 세션 인계 조건

첫 세부 태스크는 1순위인 테스트모드 정산/주문가능금액 정합성 검증부터 작성한다. 실전모드 전환이나 리스크 임계값 변경은 포함하지 않는다.

---

## 5. 계획 승인 상태

- 계획서 작성: 완료
- 코드 수정: 없음
- DB 변경: 없음
- 테스트/런타임 실행: 계획 단계이므로 미실행
- 사용자 승인: 대기
- 다음 실행 조건: 사용자가 명시적으로 `승인. 수정 진행`이라고 말한 후, 다음 세션에서 세부 태스크 작성부터 시작
