# Antigravity_Refactoring_Plan (SectorFlow 궁극구조 전환 계획서)

본 문서는 `SectorFlow` 프로젝트를 "Cascade 아키텍처 02 - 궁극구조"로 전환하기 위해 작성된 단계별 리팩토링 가이드입니다.
이 문서를 읽는 하위 AI 에이전트들은 각 단계(Phase)의 목표와 원칙을 엄격하게 준수하여 리팩토링을 수행해야 합니다.

---

## 🛑 리팩토링 대원칙 (AI 에이전트 필독)

1. **점진적 전환 (Phased Approach)**: 빅뱅(한 번에 다 뜯어고치는 것) 방식은 금지합니다. 시스템이 항상 동작 가능한 상태(Runnable State)를 유지하도록 한 단계씩 쪼개어 PR/커밋을 진행하세요.
2. **단일 진실 공급원 (Single Source of Truth)**: 모든 상태(State)와 프로토콜은 단 한 곳에서만 관리되어야 합니다.
3. **블로킹 금지**: 실시간 데이터 수신(Hot Path) 루프 안에서 무거운 연산(JSON 파싱/스코어링 등)이나 로깅(매 틱마다 info 로그)을 절대 하지 마세요.

---

## 📍 Phase 1: Ingress Layer & Event Bus 분리 (백엔드 데이터 수신 최적화)

**현재 문제점**: 증권사(Kiwoom/LS)에서 들어오는 실시간 데이터가 백엔드의 `engine_service.py` 같은 거대한 모듈로 직접 들어와 동기적으로 처리되고 있습니다.

**목표**: 브로커의 원시 데이터를 시스템 내부 이벤트로 규격화하고, 폭주(Burst)를 제어할 수 있는 큐(Queue) 시스템을 도입합니다.

### 📝 작업 지시사항
1. **Event Model 정의 (`backend/app/core/events.py` 생성)**
   - `MarketTickEvent`, `OrderFillEvent`, `AccountUpdateEvent` 등 명확하게 타입이 지정된(Typed) 데이터 클래스(또는 Pydantic 모델)를 생성하세요.
   - 필수 포함 필드: `seq` (시퀀스 번호), `broker` (브로커명), `received_ts` (수신 타임스탬프).
2. **Event Bus / Ring Buffer 구현 (`backend/app/core/event_bus.py` 생성)**
   - `asyncio.Queue` 기반의 Bounded Queue를 설계하세요.
   - **Coalescing 로직 구현**: 시세 데이터(`MarketTickEvent`)의 경우 큐가 밀릴 때 종목(Symbol)별로 가장 최신 데이터만 남기고 이전 데이터는 Drop 시키는 로직을 반드시 포함하세요. (Drop 카운트는 로깅)
   - 주문/체결(`OrderFillEvent`) 이벤트는 절대 Drop되지 않도록 별도의 Priority Queue나 우선순위 채널로 분리하세요.
3. **Broker Adapter 리팩토링**
   - 기존의 WebSocket 수신부(`kiwoom_ws.py` 등)를 수정하여, 데이터를 수신하면 복잡한 비즈니스 로직을 태우지 말고 즉시 `EventBus`로 이벤트를 Publish 하도록 변경하세요.

---

## 📍 Phase 2: Frontend 렌더링 병목 제거 (UI 최적화)

**현재 문제점**: 백엔드에서 쏟아지는 초당 수백 건의 시세 업데이트를 React 상태(`useState`, `uiStore`)로 직접 밀어넣어 DOM 리렌더링 폭주 및 메인 스레드 프리징이 발생합니다.

**목표**: 실시간 시세 데이터 처리를 React 렌더링 라이프사이클에서 완전히 분리합니다.

### 📝 작업 지시사항
1. **Hot Store (Mutable State) 분리 (`frontend/src/stores/hotStore.ts` 생성)**
   - 불변성(Immutability)을 지키는 Redux/Zustand 대신, 실시간 시세만 담아두는 순수 자바스크립트 객체 기반의 Mutable Store를 만드세요. (`Map<string, MarketData>`)
   - 백엔드에서 데이터가 오면 이 객체의 값만 조용히 덮어씌웁니다(Coalescing).
2. **Web Component 도입 (실시간 테이블)**
   - 초당 수십 번 바뀌는 시세표(Grid/Table)나 호가창 요소는 React 컴포넌트가 아닌 `Custom Element (Web Component)`로 작성하세요.
   - `requestAnimationFrame`을 활용하여 초당 30~60 프레임으로 렌더링 주기를 제한(Throttling)하고, 렌더 주기마다 `Hot Store`의 데이터를 읽어와 DOM(또는 Canvas)을 직접 업데이트 하세요.
3. **React의 역할 축소**
   - React는 설정창, 레이아웃 구조, 저빈도 업데이트(예: 내 잔고 요약) 영역만 담당하도록 역할을 축소하세요.

---

## 📍 Phase 3: Strategy Core & Order Engine 독립 (비즈니스 로직 분리)

**현재 문제점**: 시세 감시, 업종 점수 계산, 매수/매도 판단, 실제 주문 API 호출이 하나의 거대한 엔진 모듈에 강하게 결합되어 있습니다.

**목표**: 판단(Strategy)과 실행(Order)을 분리하여 상태 기계(State Machine) 기반으로 주문을 안전하게 관리합니다.

### 📝 작업 지시사항
1. **Strategy Core 분리 (`backend/app/services/strategy_core.py`)**
   - `Event Bus`를 구독(Subscribe)하여 시세 이벤트를 받아 업종 점수와 매수 후보 리스트를 계산하는 독립적인 워커(Worker)를 만드세요.
   - 연산이 무겁다면 Python의 `multiprocessing`이나 별도 프로세스로 분리하는 것을 고려하세요.
   - 판단의 결과물은 반드시 `TradeSignal`(매수/매도 신호 객체)로만 배출되도록 작성하세요.
2. **Safety Layer & Order Engine 구현 (`backend/app/services/order_engine.py`)**
   - `TradeSignal`을 받으면 가장 먼저 **Safety Layer** (자동매매 시간, 최대 금액, 중복 주문 여부 등 확인)를 거치게 하세요.
   - 주문의 생명주기를 `NEW` -> `SUBMITTED` -> `ACKED` -> `FILLED` 등의 상태 기계(State Machine) 패턴으로 엄격하게 관리하세요.
   - 브로커 API 호출 부분은 Adapter 패턴을 통해 분리하여 주문 로직과 격리하세요.

---

## 📍 Phase 4: Protocol 최적화 및 Persistence 고도화

**현재 문제점**: 백엔드와 프론트엔드가 방대한 JSON 텍스트로 실시간 마켓 데이터를 주고받고 있어 CPU 오버헤드가 매우 큽니다.

**목표**: 네트워크 대역폭과 파싱 비용을 줄이고, 장애 발생 시 완벽한 복구(Resilience) 체계를 갖춥니다.

### 📝 작업 지시사항
1. **Binary Batch Protocol 적용 (Market 데이터)**
   - 백엔드 -> 프론트엔드로 가는 실시간 시세 WebSocket 채널을 분리(`/ws/market`)하고, 데이터를 JSON 대신 바이너리(예: `struct` 패킹 또는 Protobuf 배치)로 압축하여 전송하세요.
   - 프론트엔드에 Binary Decoder 함수를 구현하여 `Hot Store`로 데이터를 직배송하세요.
2. **Persistence Journaling 도입 (`backend/app/core/journal.py`)**
   - 시세 데이터(Tick)는 버리더라도, **사용자의 설정 변경, 주문 요청, 체결 결과(Fill)**는 절대 유실되지 않도록 SQLite의 WAL 모드나 Append-only 파일 저널링을 통해 디스크에 기록하세요.
3. **관측성(Observability) 메트릭 추가**
   - `broker_recv_ts` (브로커 수신 시간)부터 `ui_render_ts` (화면 표시 시간)까지의 지연(Latency) 시간을 측정하는 메트릭 코드를 삽입하세요.
   - 프론트엔드 최상단 또는 설정 페이지에 현재 시스템의 처리 지연시간(Latency)과 Drop된 패킷 수를 모니터링할 수 있는 지표를 노출하세요.

---

## 🚀 에이전트 실행 권장 순서
1. `Phase 1` -> 백엔드의 숨통을 틔웁니다. (안정성 확보)
2. `Phase 2` -> 프론트엔드의 렉(Lag)을 없앱니다. (체감 성능 극대화)
3. `Phase 3` -> 매매 로직을 견고하게 만듭니다. (논리적 분리)
4. `Phase 4` -> 극한의 최적화와 모니터링을 완성합니다. (엔터프라이즈급 완성)

이 문서를 바탕으로 각 단계별 코딩을 진행해 주시기 바랍니다.
