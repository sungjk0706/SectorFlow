# SectorFlow 실전투자 준비 마스터 지시서 (Pre-Live Readiness)

> 이 문서는 **사전 지식이 전혀 없는 하위 AI 에이전트**가 단독으로 읽고 작업을 진행할 수 있도록 작성되었다.
> 작성 근거는 모두 **실제 코드/로그 확인 결과**이며, 추측은 포함하지 않는다. 각 항목에 `파일:라인`을 명시한다.
> 작업자는 반드시 본문의 "검증 게이트"를 통과해야만 항목을 완료로 표시할 수 있다.

---

## 0. 이 프로젝트가 무엇인가 (필수 컨텍스트)

- **정체:** 1인 · 로컬 실행 · 실시간 데이터 처리 기반 · 주식 자동매매 웹앱.
- **백엔드:** Python / FastAPI / 단일 asyncio 이벤트 루프 / aiosqlite. 진입점 `main.py`.
- **프론트:** `frontend/` (TS). 본 지시서는 백엔드 중심.
- **현재 상태:** 아직 실전투자(실거래)를 실행하지 않는다. **실거래 전에 "이론적 완전성"을 확보하는 것이 이 지시서의 목표다.**

### 0.1 가장 중요한 불변 사실 — 테스트모드 == 실전모드 (돈만 다름)

테스트모드와 실전모드는 **오직 돈과 직접 닿는 부분만** 가상으로 대체된다:
- 가상화 대상: 매수/매도 주문 전송, 체결, 보유종목, 잔고, 계좌, 거래내역.
- **그 외 모든 과정(시세 수신·시세 처리·업종 계산·매수/매도 판단·가드·지연감시·안전장치·브로드캐스트·DB 기록 흐름)은 실전모드와 100% 동일해야 한다.**

→ **판단 기준:** "이 코드 경로가 테스트모드와 실전모드에서 다르게 동작하는가? 돈 I/O가 아닌데도 다르다면 그것은 버그다."
→ **검증 이점:** 돈 I/O를 제외한 모든 안전장치는 **테스트모드에서 전부 검증 가능**하다. 실거래 없이 이론적 완전성을 확보할 수 있다.

---

## 1. 아키텍처 불변 원칙 (반드시 준수, 개정판)

기존 5원칙에 더해, 이번 진단으로 드러난 **실전 안전성 직결 원칙 6~10**을 추가한다.

1. **단일 asyncio 이벤트 루프** — 모든 비동기 작업은 단일 루프에서 협동 처리. blocking 동기 호출 금지.
2. **모든 I/O는 비동기** — 외부요청 `httpx.AsyncClient`, DB `aiosqlite`. 동기 `requests`/blocking 금지.
3. **EventBus/발행구독 금지** — 제어/데이터는 명시적 직접 호출 + `asyncio.Queue` 파이프라인으로 일원화. (콜백 리스트로 우회하는 옵서버 패턴도 이 원칙 위반으로 간주)
4. **증권사 하드코딩 금지** — 핵심 로직에 `kiwoom`/`ls` 직접 등장 금지. `BrokerInterface`/레지스트리로 추상화.
5. **단일 소스 진리(SSOT)** — 동일 상태/설정은 한 곳에서만 관리·갱신.
6. **[신규] 단일 주문 경로** — 주문이 흐르는 경로는 단 하나여야 한다. 병렬·죽은 주문 경로 금지.
7. **[신규] "구현 = 살아있는 경로에 배선됨"** — 안전/제어 장치는 *실제 실행 경로*에 연결되어 동작이 입증되어야 한다. 호출되지 않는 안전코드는 "구현됨"이 아니라 "위험한 착시"다.
8. **[신규] 플래그 단일 소스** — 하나의 상태 플래그는 정의·설정·읽기가 모두 같은 변수를 가리켜야 한다. 쓰는 변수와 읽는 변수가 다르면 안 된다.
9. **[신규] 테스트모드 동등성** — 돈 I/O를 제외한 모든 경로는 두 모드에서 동일. 모드 분기는 "주문 전송/체결/잔고/이력 저장"의 최소 지점에만 둔다.
10. **[신규] 런타임 검증 게이트** — `py_compile`/import 성공은 검증이 아니다. 변경은 반드시 **실제 실행 경로를 한 번 흘려본 런타임 점검**으로 검증한다. (4장 참조)

---

## 2. 현재 진단 요약 — 핵심 문제는 "보이지 않는 단절"

코드/로그로 확정된 큰 문제는 하나의 패턴으로 수렴한다:

> **안전·제어 장치가 "구현은 되어 있으나" 실제 매매 경로와 배선이 끊겨 있고, 검증 기준(`py_compile`)이 이 단절을 잡지 못한다.**

이로 인해 "검증 완료"로 기록된 변경이 런타임에서 깨지는 사건이 실제로 발생했다 (4.0 증거 참조). 따라서 **개별 버그 수정보다 "런타임 검증 게이트 수립"이 1순위**다.

---

## 2.5 하위 에이전트 작업 시작 가이드 (여기부터 읽고 시작)

- **시작 지점:** 무조건 **PHASE 0(테스트 골격 생성)부터.** 코드 수정(PHASE 1+)을 PHASE 0보다 먼저 하지 말 것.
- **진행 방식:** PHASE 0 → 1 → 2 → 3 **순차**. 한 PHASE의 검증 게이트를 통과하기 전에는 다음 PHASE로 넘어가지 말 것. 각 PHASE는 독립 커밋.
- **작업 단위:** 한 번에 한 파일/작은 블록만. 수정 직후 잔여 문자열 검색으로 확인.
- **검증:** 4장 게이트(런타임 테스트)만 인정. `py_compile` 통과는 검증이 아님.
- **막히면:** 추측으로 진행하지 말고, 해당 파일을 직접 읽어 근거를 확인하거나 아래 "사람 결정 정지점"에 해당하면 멈추고 사람에게 질의.

### 2.6 사람 결정 정지점 (도달 시 멈추고 질의할 것)
아래 항목은 돈·정책과 직결되어 하위 에이전트가 임의 결정 금지. 해당 단계 도달 시 **작업을 멈추고 사람 승인을 받는다.**
- **2.1** 지연 회복 시 플래그를 `False`로 되돌리는 **리셋 시점/위치**.
- **2.2** RiskManager **임계치 값**(일일 손실 한도, 단일종목/총자본 비중 등)과 설정 키 매핑.
- **3.1** DB 쓰기 경로 **단일화 여부**(`db_writer` 큐로 수렴 vs 현행 유지).
- **3.3** `dynamic_broker.py` **삭제 vs 비동기 통합** 결정.
- 그 외 본문에 "사람과 합의"로 표기된 모든 항목.

> 이미 확정된 항목(임의 변경 금지): **2.0 주문 경로 = A안(OMS 단일 경로 승격).**

---

## 3. 작업 단계 (반드시 이 순서로)

> 각 단계는 독립 커밋 단위. 한 번에 한 파일/작은 블록만 수정하고, 수정 직후 잔여 검색으로 검증. 4장 게이트 통과 전까지 완료 표시 금지.

### [PHASE 0] 런타임 검증 게이트부터 만든다 (최우선)

이게 없으면 이후 모든 수정이 또 단절을 만든다. **코드 수정보다 먼저 한다.**

> **중요 — 현재 상태(확인됨):** 백엔드에는 **테스트 인프라가 아직 없다.** `backend/tests/` 디렉터리 없음, `conftest.py`/`pytest.ini`/`pyproject.toml` 없음. 단, `backend/requirements.txt:45-46`에 `pytest>=8.0.0`, `pytest-asyncio>=1.0.0`가 이미 선언돼 있다(도구는 준비됨, 골격만 없음). 따라서 PHASE 0은 "기존 테스트 실행"이 아니라 **"테스트 골격을 신규 생성"하는 작업이다.**

#### 0.0 테스트 골격 신규 생성 (가장 먼저)
- **0.0.1** 디렉터리 생성: `backend/tests/`, 빈 `backend/tests/__init__.py`.
- **0.0.2** 의존성 설치 확인: 가상환경(`.venv`)에서 `pip install -r backend/requirements.txt` 후 `pytest --version`이 동작하는지 확인. (pytest/pytest-asyncio는 이미 requirements에 있음 — 추가 설치 금지)
- **0.0.3** 저장소 루트에 pytest 설정 파일 생성(택1: `pytest.ini` 또는 `pyproject.toml [tool.pytest.ini_options]`). 다음을 반드시 포함:
  ```ini
  [pytest]
  asyncio_mode = auto
  filterwarnings =
      error::RuntimeWarning      # coroutine never awaited 등을 즉시 실패로 승격
  testpaths = backend/tests
  ```
  - `asyncio_mode = auto`: async 테스트 함수를 자동 인식(별도 마커 불필요).
  - `filterwarnings = error::RuntimeWarning`: **await 누락(코루틴 미대기)을 테스트 실패로 만드는 핵심 장치**(0.2 대체). 이 한 줄이 PHASE 1 버그를 자동 검출한다.
- **0.0.4** `backend/tests/conftest.py` 생성: 격리용 임시 SQLite DB 픽스처를 둔다. 운영 DB(`backend/data/stocks.db`)를 절대 건드리지 않도록, 테스트는 임시 파일/`:memory:` 기반 커넥션을 사용하게 한다. (DB 경로 주입 방식은 `backend/app/db/database.py`의 커넥션 획득부를 읽고 거기에 맞춰 구성 — 환경변수 또는 monkeypatch)
- **검증:** `pytest backend/tests`가 "수집 0건"이라도 **에러 없이 실행**되면 골격 완성.

#### 0.1 테스트모드 엔드투엔드 스모크 테스트 작성
- 파일 예: `backend/tests/test_order_flow_smoke.py`.
- 요건:
  1. **테스트모드로 설정** (`is_test_mode()`가 True가 되도록 `integrated_system_settings_cache` 또는 설정 픽스처 구성 — `backend/app/core/trade_mode.py`의 판정 기준을 읽고 맞출 것).
  2. 가짜 시세/매수 타점을 주입해 **시세 → 판단 → 주문 → 체결기록 → 잔고반영** 경로를 1회 흐르게 한다. (전체 앱 기동이 무거우면, 실제 주문 경로 함수를 직접 호출하는 통합 테스트로 시작 — 단 실행 경로는 운영과 동일해야 함, 목으로 대체 금지)
  3. **단언:** `trade_history`(`backend/app/services/trade_history.py`)와 `journal`(`backend/app/core/journal.py`)에 레코드가 실제로 생성됨.
  4. **단언:** 테스트모드이므로 실거래 `send_order`가 **호출되지 않고** `dry_run.fake_send_order` 경로만 탐(돈 I/O 분리 검증, 원칙 9).
- **0.0.3의 `filterwarnings=error::RuntimeWarning` 덕분에 await 누락은 자동으로 실패 처리**된다(별도 단언 불필요).

#### 0.2 안전장치 단위 테스트 작성 (4.1 게이트 자동화)
- `backend/tests/test_safety_gates.py` 예시 항목:
  - 지연 플래그를 200ms 초과 상태로 만들고 매수/매도가 **차단**되는지(2.1).
  - 서킷브레이커를 실패 임계치까지 올린 뒤 주문이 **거부**되고 매매가 정지되는지(2.2).
  - Pending 주문이 있을 때 기동 대조 루틴이 호출되는지(2.3).
- PHASE 2를 아직 구현하기 전이므로, **이 테스트들은 처음엔 실패(RED)해야 정상**이다(아래 게이트 참조).

**Phase 0 검증 게이트(반드시 이 순서):**
1. 0.0 골격이 에러 없이 `pytest`로 수집/실행됨.
2. 0.1 스모크 + 0.2 안전장치 테스트가 **현재 코드에서 실패(RED)** 하는 것을 먼저 확인한다 → 테스트가 실제 결함을 잡는다는 증거.
3. 이후 PHASE 1~2에서 수정하며 하나씩 **통과(GREEN)** 시킨다. (테스트를 약화시켜 통과시키는 것 금지 — 원칙 위반)

---

### [PHASE 1] 실전 주문 경로의 치명 단절 복구 (P0)

#### 1.1 실전 주문 전송 `await` 누락 — **실전에서 주문이 안 나감**
- 근거(확인): `send_order`는 async — `backend/app/core/kiwoom_broker.py:58`, `kiwoom_providers.py:220`, `kiwoom_order.py:49`.
- 결함 위치:
  - 매수: `backend/app/services/trading.py:239` `res = get_router().order.send_order(...)` (await 없음)
  - 매도: `backend/app/services/trading.py:380` `result = get_router().order.send_order(...)` (await 없음)
- 영향: 실전모드에서 코루틴이 실행되지 않고 다음 줄 `.get("success")`(241/382)에서 오류 → **실거래 주문 미전송**. (테스트모드는 `await dry_run.fake_send_order` 사용해 정상)
- 지시: 두 호출에 `await` 부여. 단, **다른 코드는 건드리지 말 것.**

#### 1.2 주문 장부/거래이력 `await` 누락 — **양쪽 모드 모두 기록 누락**
- 근거(확인): `record_order_request`는 async `backend/app/core/journal.py:166`; `record_buy` `backend/app/services/trade_history.py:171`; `record_sell` `trade_history.py:232`.
- 결함 위치(trading.py): `:250`, `:390`(record_order_request), `:266`(record_buy), `:404`(record_sell) — 모두 await 없음.
- 영향: DB 기록 코루틴이 실행되지 않아 **거래내역/장부가 저장되지 않음**(테스트·실전 공통). UI 거래내역 공백.
- 지시: 네 호출에 `await` 부여. (주의: `data_manager.get_stock_name`은 동기 함수 `data_manager.py:77` — await 불필요. 헷갈리지 말 것.)

**Phase 1 검증 게이트:** 0.1 스모크에서 거래내역·장부 레코드 생성 단언 통과 + RuntimeWarning 0건.

---

### [PHASE 2] 안전장치를 "살아있는 경로"에 재연결 (P0~P1)

#### 2.0 주문 경로 일원화 — **[확정: 선택지 A] OMS 단일 경로 승격**

> **사람 승인 완료(2026-06-08):** 주문 경로는 **A안(OMS 단일 경로)**으로 확정한다. 아래 B안은 채택하지 않으며 기록용으로만 남긴다.

**확정 근거 (실전 안정성 + 최적화 손실 0):**
- 무손실: `order_queue`는 드롭 미적용(`core_queues.py:111`)으로 주문 유실 0 보장.
- 직렬화: 단일 컨슈머가 1건씩 처리 → 동시 신호 경합/중복 주문 방지.
- 안전장치/원장대조가 OMS 경로에 이미 구현돼 있어 재사용 가능(2.2/2.3).
- 추가 지연은 `asyncio.Queue` 1홉(수 μs)으로, 증권사 네트워크 왕복(수십~수백 ms) 대비 무의미. 1인·소량 주문(쿨다운 90초 `buy_order_executor.py:70`, 최대보유 5)이라 주문경로 속도가 병목이 될 수 없음. 실시간성이 중요한 시세 경로(`tick_queue`)는 불변.

**현재 상태(확인):**
- **죽은 경로(승격 대상):** `order_queue → backend/app/pipelines/pipeline_oms.py`. `order_queue`에 주문을 넣는 생산자가 코드 전체에 0건이라 현재 미동작. 단, 안전장치/원장대조가 이미 구현돼 있음.
- **살아있는 경로(흡수 대상):** `pipeline_compute._check_buy_target_reached`(`pipeline_compute.py:542`) → `engine_service.try_sector_buy()`(`backend/app/services/buy_order_executor.py:23`) → `trading.py`. 안전장치 참조 0건.
- **(기각) 선택지 B:** 직통 경로 정식화 + OMS 폐기. 안전장치/원장대조를 새로 이식해야 해 새 단절 위험 + 무손실/직렬화 상실. → **채택 안 함.**

**A안 구현 순서 (하위 에이전트용, 이 순서 엄수):**

1. **OMS 내부 기존 결함 먼저 수정** (생산자 연결 전에 OMS가 정상이어야 함):
   - `pipeline_oms.py:436` `base_settings=settings` → 미정의 변수. `_execute_sell_order` 스코프에서 올바른 설정 소스로 교체(예: `es._get_settings()` 또는 주문지령에 실어 전달). 정확한 소스는 `_execute_buy_order`가 쓰는 방식과 일치시킬 것.
   - `pipeline_oms.py:310`, `:326`, `:442` `oms_update_order_status(...)` → async 함수(`journal.py:233`)이므로 `await` 부여.
2. **생산자 연결 — compute가 주문을 직접 실행하지 않고 `order_queue`에 투입하도록 전환:**
   - 대상: `backend/app/services/buy_order_executor.py:96` `await state.auto_trade.execute_buy(...)` 직접 호출, 및 매도 판단부(`engine_strategy_core`/`trading.check_sell_conditions` 경로).
   - 변경 방향: 매수/매도 "판단"은 그대로 두되, **실행 트리거를 `order_queue.put({"action":"BUY"/"SELL","code":...,"price":...,"qty":...})`로 대체.** 실제 `execute_buy/execute_sell` 호출은 OMS(`_execute_buy_order`/`_execute_sell_order`)만 수행.
   - 주의: `_execute_*_order`는 결국 `trading.py`의 `AutoTradeManager`를 호출하므로(`pipeline_oms.py:298,428`), **PHASE 1의 `trading.py` await 수정이 선행 완료돼 있어야 한다.**
   - 중복 실행 금지: 전환 후 compute/`try_sector_buy`가 `execute_buy`를 **직접 호출하지 않는지** 잔여 검색으로 확인(이중 경로 재발 방지, 원칙 6).
3. **모드 분기 정합:** OMS의 저널링 `trade_mode`가 현재 `"real"` 하드코딩(`pipeline_oms.py:282,408`). `is_test_mode()` 기준으로 `"test"/"real"`을 판정하도록 교체(원칙 9). 실제 주문 전송의 모드 분기는 `trading.py`(dry_run vs send_order)에 이미 있으므로 OMS는 그 결과만 신뢰.
4. 그 후 2.1~2.3(안전장치/지연/원장대조)을 **이 단일 OMS 경로에만** 연결.

**2.0 검증 게이트:** 테스트모드 스모크에서 매수/매도 신호가 `order_queue`를 거쳐 OMS에서 1회 실행되고, `execute_buy`가 **OMS를 통해서만** 호출됨(직통 호출 0건)을 단언. RuntimeWarning 0건.

#### 2.1 200ms 지연 중단 게이트 — **읽는 변수와 쓰는 변수가 다름(단절)**
- 근거(확인):
  - 설정(쓰기): `backend/app/services/engine_ws_dispatch.py:370` → `engine_state.state.realtime_latency_exceeded = True` (정의: `engine_state.py:36`)
  - 판단(읽기): `backend/app/services/trading.py:85` 및 `:423` → `engine_service._realtime_latency_exceeded`
  - 전수검색 결과 `_realtime_latency_exceeded`(밑줄, 모듈변수)는 **읽기 2곳 외 어디에도 정의/설정되지 않음.**
- 영향: 읽기가 존재하지 않는 변수를 참조 → `except`로 조용히 무시 → **지연 200ms 초과해도 자동매매가 멈추지 않음**(왜곡 데이터로 거래). 핵심 안전원칙 위반.
- 지시: 읽기를 단일 소스(`engine_state.state.realtime_latency_exceeded`)로 통일(원칙 8). 추가로 **지연 회복 시 `False`로 되돌리는 리셋 로직이 있는지 확인**하고 없으면 설계에 포함(과도 차단 방지). 리셋 위치는 사람과 합의.

#### 2.2 RiskManager / CircuitBreaker 연결
- 근거(확인): `RiskManager`(`backend/app/services/risk_manager.py:26`)와 `CircuitBreaker`(`circuit_breaker.py:22`)는 **오직 `pipeline_oms.py`에서만 참조**(죽은 경로). 살아있는 경로엔 0건.
- 지시: 2.0에서 정한 단일 경로에 매수/매도 전 `check_*_order_allowed`와 성공/실패 기록(`record_order_success/failure`)을 연결. 임계치(`risk_manager.py:34` 손실한도 등)는 설정에서 읽도록 사람과 합의.

#### 2.3 기동 원장 대조(Reconciliation)
- 근거(확인): `_reconciliation_on_startup` `backend/app/pipelines/pipeline_oms.py:100` — 죽은 경로에만 존재.
- 영향: 실거래에서 앱 재시작 시 실제 보유/주문과 로컬 상태 정합을 맞추는 기능이 미동작.
- 지시: 단일 경로 기동 시퀀스에 연결. (테스트모드는 가상잔고이므로 대조 스킵 분기 유지 — 돈 I/O 차이에 해당, 원칙 9 부합.)

**Phase 2 검증 게이트:** 테스트모드에서 (a) 인위적 200ms 초과 시 매수/매도 차단됨을 단언, (b) 연속 주문 실패 N회 후 서킷브레이커 OPEN으로 매매 정지됨을 단언, (c) Pending 주문 존재 시 기동 대조 루틴이 호출됨을 단언.

---

### [PHASE 3] 중복·죽은 코드 정리 (단절 재발 토양 제거, P2)

> 이 단계는 동작 변경이 아니라 "혼란 제거"다. 하위 에이전트가 죽은 경로를 실수로 고치는 사고를 막는다.

- **3.1 DB 쓰기 경로 이원화 정리** — `db_writer.py` 직렬화 큐(`crud.py`, `stock_tables.py`에서 사용)와 `journal/trade_history`의 직접 커넥션 쓰기가 공존. SSOT(원칙 5) 관점에서 단일 쓰기 경로로 수렴할지 사람과 합의 후 진행.
- **3.2 EventBus 잔재 제거** — `kiwoom_connector.py:221` `_event_bus_callback`, `:437` `set_event_bus_callback`(호출처 0건). 원칙 3 위반 잔재. `engine_ws_dispatch.py:227` 등 "Event Bus Publish" 주석도 코드와 불일치 → 정정/삭제.
- **3.3 미사용 DynamicBrokerClient 처리** — `backend/app/core/dynamic_broker.py`는 동기 `httpx`(blocking, 원칙 2 위반)이며 호출처 0건. 삭제 또는 비동기 추상화로 통합(증권사 추상화 원칙 4와 연계) — 사람과 합의.
- **3.4 Gateway real-data coalescing 키 불일치** — `pipeline_gateway.py:100`이 `payload.get("code")`로 찾지만 실제 페이로드 키는 `item`(생성: `pipeline_compute.py:349,353`). 분기가 항상 스킵됨(죽은 로직). real-data throttle은 `ws_manager`(`engine_account_notify.py:66`, 50ms conflation)에만 존재. 키 정합 또는 중복 경로 제거.
- **3.5 OMS 경로 처리** — **[A안 확정]** `pipeline_oms.py`는 폐기하지 않고 **단일 주문 경로로 승격**(2.0 참조). 따라서 이 항목에서는 OMS를 제거하지 않으며, 대신 OMS와 무관한 잔여 죽은 코드(3.2~3.4)만 정리한다.

**Phase 3 검증 게이트:** 정리 후 0.1 스모크 + Phase 1/2 게이트 전부 재통과(회귀 없음).

---

## 4. 검증 게이트 정의 (모든 단계 공통, py_compile 금지)

### 4.0 왜 py_compile은 검증이 아닌가 (실제 증거)
`logs/trading_2026-06-07.log:1`:
```
[섹터재계산] 증분 재계산 오류: compute_full_sector_summary() missing 1 required keyword-only argument: 'strengths'
```
HANDOVER.md는 같은 날 이 변경을 "검증 완료(py_compile)"로 기록했으나, 실행 시 **업종 재계산(→매수후보 산출) 전체가 런타임 크래시**했다. (현재 `sector_calculator.py:190` 정의에서 `strengths`는 제거되어 해당 크래시는 해소됨.)
→ **`py_compile`/import 성공은 인자불일치·await누락·변수단절을 못 잡는다. 반드시 런타임 게이트를 쓴다.**

### 4.1 필수 통과 기준 (체크리스트)
- [ ] 테스트모드 스모크: 시세→판단→주문→거래내역/장부 기록까지 1회 완주.
- [ ] 실행 중 `RuntimeWarning: coroutine never awaited` 0건 (RuntimeWarning을 error로 승격해 검사).
- [ ] 지연 200ms 초과 시 매수·매도 모두 차단됨(단일 플래그 기준).
- [ ] 서킷브레이커 OPEN 시 매매 정지 + 자동매매 마스터 OFF.
- [ ] 동일 시나리오를 테스트모드/실전 코드경로가 동일하게 타는지 확인(돈 I/O 분기 외 분기 없음).
- [ ] 변경 파일에 대한 잔여 문자열 검색으로 옛 패턴 미잔존 확인.

### 4.2 보조 명령 (참고용, 단독 검증 불가)
```bash
python -m py_compile <변경파일>     # 문법만. 통과해도 검증 아님.
pytest -W error::RuntimeWarning backend/tests/   # 런타임 게이트. 이것이 기준.
```

---

## 5. 절대 금지 사항 (하위 에이전트 공통)
- PHASE 2.0 승격 완료 **전까지** `pipeline_oms.py`는 아직 죽은 경로다. 승격 전에 거기만 고치면 실제 동작에 반영되지 않는다(이번에 실제로 발생한 함정). 승격 후에는 OMS가 유일한 산 경로다.
- `py_compile` 통과만으로 "검증 완료" 표기.
- 안전장치를 "구현"했다고만 하고 살아있는 경로 연결을 생략하는 것(원칙 7).
- 돈 I/O가 아닌 곳에 테스트/실전 모드 분기를 추가하는 것(원칙 9).
- 한 번에 여러 파일을 긴 스크립트로 일괄 치환하는 것. (작은 단위 + 즉시 검증)
- 2.0 확정 방향(A안: OMS 단일 경로 승격)을 임의로 뒤집는 것. B안(직통/폐기)은 채택되지 않았다.

## 6. 완료 보고 형식
- 수정 파일 및 라인
- 제거한 근본 단절(어느 안전장치를 어느 경로에 연결했는가)
- 통과한 검증 게이트 항목(4.1 체크리스트)
- 남은 확인 사항 / 사람 승인 필요 항목
- 사람이 직접 확인할 방법(테스트모드 재현 절차)
