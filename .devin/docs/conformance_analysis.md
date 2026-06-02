# SectorFlow 아키텍처 불변 원칙 준수 여부 분석 보고서

본 보고서는 **SectorFlow** 프로젝트의 현재 백엔드 코드 베이스를 전수 조사하여, 프로젝트에서 정의한 **아키텍처 불변 원칙**을 엄격히 준수하고 있는지 대조 분석하고, 발견된 위반 사례 및 런타임 위험 요소를 상세히 진단합니다.

---

## 1. 종합 평가 요약

현재 SectorFlow 프로젝트는 데이터베이스 비동기화(`aiosqlite` 도입) 및 전역 설정을 메모리 캐싱하는 등 불변 원칙을 준수하기 위한 기반 구조를 마련하였으나, **실제 런타임 비즈니스 로직 및 외부 API 통신부에서 심각한 원칙 위반 사례와 버그들이 잔존**하고 있습니다.

특히, **동기식 블로킹 I/O 호출을 비동기 태스크(async def) 내부에서 직접 실행**하여 asyncio 이벤트 루프를 완전히 중단(Freeze)시킬 수 있는 병목 지점들이 존재하며, **코루틴 호출 시 `await`를 누락**하여 핵심 로직(주문 실행 및 매도 조건 감시)이 전혀 작동하지 않는 치명적인 코딩 오류가 발견되었습니다.

---

## 2. 불변 원칙별 위반 및 준수 세부 분석

### ① 모든 I/O는 async def 및 run_in_executor 우회 금지 (위반)
* **원칙:** 동기 함수 금지, 모든 I/O는 비동기(`async/await`)로 처리하며, `run_in_executor` 등으로 동기 코드를 비동기로 위장하지 않는다.
* **위반 사례 1: `kiwoom_stock_rest.py` 내의 동기식 REST 호출 및 블로킹 sleep**
  * **대상 파일:** [kiwoom_stock_rest.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/core/kiwoom_stock_rest.py) (94, 157, 198, 249, 353, 407, 410, 456, 523, 534, 586, 616번 라인)
  * **원인:** 함수 자체는 `async def fetch_ka10081_daily_and_5d_data`와 같이 비동기로 정의되었으나, 내부에서 `requests.post()` (실제 httpx의 동기 post 호출)를 사용해 동기식으로 서버와 통신하며, API 속도 제한(429) 대기 시 **`time.sleep(wait)`**를 호출하여 asyncio 이벤트 루프 자체를 수 초간 정지(Freeze)시킵니다.
* **위반 사례 2: `data_manager.py` 내의 동기식 REST API 호출**
  * **대상 파일:** [data_manager.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/data_manager.py) (120, 212번 라인)
  * **원인:** 계좌 수익률을 조회하는 `get_account_profit_rate` 및 `get_main_account_info` 함수가 **동기 함수(`def`)**로 선언되어 있으며, 내부에서 `requests.post()`를 이용해 동기 I/O를 수행합니다.
* **위반 사례 3: `data_manager.py` 내 `asyncio.run` 중첩 호출**
  * **대상 파일:** [data_manager.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/data_manager.py) (82번 라인)
  * **원인:** 동기 함수 `get_stock_name` 내에서 `asyncio.run(load_stock_name_cache())`를 호출합니다. 이 함수가 이미 실행 중인 비동기 루프 내에서 호출되면 `RuntimeError: This event loop is already running`이 발생하여 서버가 크래시됩니다.

---

### ② 블로킹 = 지연 = 왜곡 = 망함 (위반)
* **원칙:** 단일 루프 시스템에서 블로킹 연산은 시세 지연 및 왜곡을 유발하므로 절대 차단한다.
* **위반 사례:** `pipeline_oms.py`와 `engine_account.py` 등 핵심 실시간 루프에서 `asyncio.to_thread`를 사용하여 동기식 블로킹 작업(위의 위반 사례 2)을 스레드로 우회 실행하고 있습니다.
  * **대상 파일:** [pipeline_oms.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/pipeline_oms.py#L159)
  ```python
  balance_raw = await asyncio.to_thread(get_account_profit_rate, access_token)
  ```
  * **진단:** `asyncio.to_thread`는 `run_in_executor`의 래퍼로, 동기 함수를 비동기로 위장하는 행위입니다. API 통신 라이브러리 자체가 완전 비동기형(`httpx.AsyncClient`)으로 구현되어 있으므로, 스레드 전환 오버헤드 없이 직접 `await`로 비동기 호출을 해야 합니다.

---

### ③ aiosqlite 단일화 및 DB 연결 생명주기 공유 (준수 및 제안)
* **원칙:** SQLite 하나로 단일화하고 ORM을 배제하며, DB 커넥션은 생명주기를 공유한다.
* **현황:** [database.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/db/database.py)에서 `aiosqlite` 기반의 전역 커넥션 `_db_connection`을 앱 시작 시 생성하고 종료 시 해제하도록 구현하여 원칙을 잘 준수하고 있습니다.
* **미완성 최적화:** 동시성 잠금 충돌을 완벽히 격리하기 위해 작성된 [db_writer.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/db/db_writer.py) (DB 쓰기 전용 백그라운드 큐 직렬화) 모듈이 아직 실제 비즈니스 로직(예: `crud.py`, `market_close_pipeline.py`)에 통합되지 않고 방치되어 있습니다. 여전히 개별 파일들에서 `conn.commit()`을 수동 호출하고 있어 쓰기 충돌 잠재 위험이 있습니다.

---

### ④ EventBus/발행구독 패턴 사용 금지 (준수)
* **원칙:** 느슨한 결합 대신 직접 호출 체인 및 명시적인 `asyncio.Queue` 배관을 사용한다.
* **현황:** `event_bus.py`가 완전히 삭제되었으며, 시세 처리는 `tick_queue` 및 `coalescing` 파이프라인을 경유하고, 주문은 `order_queue`를 컨슘하는 직접적인 흐름을 유지하고 있습니다.
* **잔존 코드 청소 필요:** [kiwoom_connector.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/core/kiwoom_connector.py) 내부에 이전 EventBus 구조에서 사용되던 `_event_bus_callback` 관련 멤버 변수와 메서드가 호출되지 않는 데드 코드로 남아 있습니다.

---

## 3. 치명적인 런타임 오류 및 버그 진단

아키텍처 불변 원칙을 수정하는 과정에서 도입된 치명적인 비동기 버그로, 실시간 자동매매 앱의 작동 자체를 불가능하게 만드는 부분들입니다.

### ⚠️ 치명 버그 1: `await` 누락으로 인한 코루틴 미실행 (주문 및 감시 마비)
* **버그 1: OMS 주문 처리부**
  * **대상 파일:** [pipeline_oms.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/pipeline_oms.py) (304, 435번 라인)
  * **상세:** 매수/매도 주문을 실행하는 `auto_trade.execute_buy`와 `auto_trade.execute_sell`이 `trading.py`에서 `async def`로 변경되었으나, `pipeline_oms.py`에서 **`await` 없이 일반 함수처럼 호출**하고 있습니다.
  * **결과:** 주문 신호가 큐에서 꺼내져도 실제 증권사로 주문이 전송되지 않고 `RuntimeWarning: coroutine was never awaited` 경고만 출력되며 매매가 마비됩니다.
* **버그 2: 실시간 시세 분기 및 매도 조건 감시부**
  * **대상 파일:** [engine_ws_dispatch.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py) (342, 346번 라인)
  * **상세:** 실시간 현재가가 갱신될 때 매도 대상을 감시하는 `engine_state._auto_trade.check_sell_conditions` 함수가 `async def`로 선언되어 있으나, 호출부에서 **`await`가 누락**되었습니다.
  * **결과:** 장중 실시간 익절/손절 감시 루프가 아예 동작하지 않습니다.

### ⚠️ 치명 버그 2: 존재하지 않는 변수 `es` 참조 (NameError 및 TypeError)
* **대상 파일:** [engine_ws_dispatch.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py) (269, 512, 514번 라인)
* **상세:** 
  * `engine_ws_dispatch.py`는 기존 `engine_service.py`에서 순환 참조 해결을 위해 분리되었으나, 코드 내부에 정의되지 않은 **`es`** 변수를 다수 참조하고 있습니다.
  * 라인 269: `_check_realtime_latency(_ts, es)` -> `_check_realtime_latency`는 인자가 1개인 함수인데 `es`를 추가로 넘겨 `TypeError`도 동시 유발합니다.
  * 라인 512, 514: `_handle_real_00(item, vals, es)`, `_handle_real_balance(item, vals, es)`를 호출하여 정의되지 않은 `es` 때문에 `NameError`를 발생시킵니다.
* **결과:** 실시간 틱 데이터가 수신되는 즉시 `NameError`가 발생해 WebSocket 데이터 수신 컨슈머가 강제 종료(크래시)됩니다.

### ⚠️ 치명 버그 3: 비동기 코루틴에 `asyncio.to_thread` 오남용 (API 무력화)
* **대상 파일:** [engine_account.py](file:///Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account.py) (217, 233, 236번 라인)
* **상세:**
  ```python
  token_ok = await asyncio.to_thread(_rest_api._ensure_token)
  deposit_raw = await asyncio.to_thread(_rest_api.get_deposit_detail, acnt_no)
  balance_raw = await asyncio.to_thread(_rest_api.get_balance_detail)
  ```
  * `_rest_api`는 비동기 클라이언트인 `KiwoomRestAPI`로, 각 호출 메서드들은 `async def`로 선언된 코루틴 함수입니다. 
  * 이를 `asyncio.to_thread()`로 감싸 실행하면 실제 비동기 처리가 동작하지 않고 코루틴 객체 자체가 리턴됩니다. 이에 따라 `deposit_raw`가 딕셔너리가 아닌 코루틴 객체가 되어 하단의 `parse_kt00001_deposit(deposit_raw)` 파싱 단계에서 즉시 속성 에러(`AttributeError`)로 크래시가 발생합니다.

---

## 4. 권장 해결책 및 로드맵

1. **REST API 호출의 순수 비동기화 (`httpx.AsyncClient` 완전 전환)**
   * `kiwoom_stock_rest.py`의 `requests.post`를 `await api.call_api` 또는 내부 `AsyncClient`를 통한 `await client.post`로 전환하고, `time.sleep`을 `await asyncio.sleep`으로 교체해야 합니다.
   * `data_manager.py` 내부의 동기 REST 호출 함수들을 `async def`로 바꾸고, 내부의 `asyncio.run`을 제거한 뒤 비동기 데이터 플로우로 교체해야 합니다.
2. **비동기 호출 체인 오류 전면 수정 (`await` 추가)**
   * `pipeline_oms.py`와 `engine_ws_dispatch.py`에서 비동기 주문/조건 감시 함수 호출 시 반드시 `await` 키워드를 삽입합니다.
3. **`engine_ws_dispatch.py` 내 잔존 오류 정리**
   * 정의되지 않은 `es` 파라미터 전달을 제거하고 모듈 전역 상태(`engine_state`)를 직접 참조하도록 수정합니다.
4. **`asyncio.to_thread` 오남용 제거**
   * 이미 비동기로 동작하는 REST API 클라이언트에 대한 `to_thread` 래핑을 걷어내고 직접 `await _rest_api.get_balance_detail()` 형태로 호출하도록 정정합니다.
5. **`db_writer.py` 실로직 통합**
   * `db_writer.py` 루프를 앱 실행 부트스트랩 단계에서 기동하고, 모든 SQLite 쓰기(`INSERT/UPDATE`) 쿼리를 `enqueue_db_write`를 타도록 구조를 개선합니다.
