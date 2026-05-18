# Cascade 아키텍처 02 - 궁극구조

## 목표 정의

`SectorFlow`의 궁극 구조는 일반 웹서비스 구조가 아니다.

목표는 다음이다.

```text
한국 주식시장 실시간 데이터를 최소 지연으로 수신
이벤트 순서와 의미를 왜곡하지 않음
전략 판단과 주문 실행을 블로킹하지 않음
체결/잔고 기준으로 포지션을 정확히 동기화
프론트 UI는 실시간 데이터를 빠르게 표시하되 메인 스레드를 막지 않음
1인 로컬 환경에서 극한의 단순성/성능/안정성을 달성
```

---

## 최종 아키텍처 한눈에 보기

```text
┌──────────────────────────────┐
│ Broker Layer                  │
│ - LS Realtime WS              │
│ - Kiwoom Order/Fill WS         │
│ - Kiwoom/LS REST               │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Ingress Layer                 │
│ - 전용 수신 task              │
│ - 최소 파싱                   │
│ - timestamp/sequence 부여      │
│ - hot path 로그 금지           │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Event Bus / Ring Buffer       │
│ - bounded queue               │
│ - latest-by-symbol map         │
│ - backpressure/drop policy     │
│ - latency metrics              │
└──────────────┬───────────────┘
               │
        ┌──────┴────────┐
        ▼               ▼
┌───────────────┐ ┌────────────────┐
│ Strategy Core │ │ UI Publisher    │
│ - scoring     │ │ - coalescing    │
│ - signal      │ │ - snapshots     │
└───────┬───────┘ └───────┬────────┘
        │                 │
        ▼                 ▼
┌───────────────┐ ┌────────────────┐
│ Order Engine  │ │ Frontend        │
│ - safety      │ │ - WS decoder    │
│ - router      │ │ - hot store     │
│ - state mach. │ │ - WebComponent  │
└───────┬───────┘ └────────────────┘
        │
        ▼
┌──────────────────────────────┐
│ Persistence / Journal         │
│ - order/fill journal          │
│ - account snapshot            │
│ - config/settings             │
│ - atomic write                 │
└──────────────────────────────┘
```

---

## 1. Broker Layer

### 역할

브로커 API 차이를 시스템 내부로 전파하지 않는다.

브로커별 adapter가 해야 할 일:

```text
인증/토큰 관리
WebSocket 연결/재연결
REST 호출
브로커 원본 메시지 수신
최소 공통 이벤트로 변환
```

### 권장 분리

```text
LsRealtimeAdapter
KiwoomOrderAdapter
KiwoomAccountAdapter
LsOrderAdapter(optional)
HistoricalDataAdapter
```

### 원칙

- 브로커 원본 필드는 adapter 경계에서 보존한다.
- 내부 이벤트에는 `broker`, `raw`, `normalized`를 구분한다.
- 실시간 수신 루프에서는 복잡한 비즈니스 판단을 하지 않는다.

---

## 2. Ingress Layer

### 역할

브로커에서 들어온 이벤트를 시스템에 안전하게 넣는 첫 관문이다.

해야 할 일:

```text
수신 timestamp 기록
sequence 번호 부여
최소 파싱
종목코드 추출
EventBus에 전달
```

하지 말아야 할 일:

```text
매 tick마다 info 로그 출력
복잡한 전략 계산
파일 저장
REST 호출
React/UI 상태 직접 변경
무거운 JSON pretty print
```

### 권장 이벤트 포맷

```text
MarketTickEvent {
  seq: number
  broker: 'LS' | 'KIWOOM'
  received_ts: number
  symbol: string
  event_type: string
  raw: object | bytes
  normalized?: object
}
```

---

## 3. Event Bus / Ring Buffer

### 왜 필요한가

실시간 데이터는 burst가 발생한다.

모든 tick을 모든 계층이 그대로 처리하면 다음 문제가 생긴다.

```text
큐 폭증
UI 렌더링 폭주
전략 처리 지연
오래된 데이터가 늦게 표시됨
```

### 권장 구조

```text
bounded asyncio.Queue
latest_by_symbol dict
priority queue for order/fill/account
latency metrics collector
```

### drop 정책

시세 이벤트:

```text
동일 종목 최신값만 유지 가능
오래된 tick drop 허용
단, drop count metrics 기록
```

체결/주문 이벤트:

```text
절대 drop 금지
순서 보존
journal 기록
```

계좌/잔고 이벤트:

```text
최신 snapshot 중요
중간 snapshot은 coalescing 가능
```

---

## 4. Strategy Core

### 역할

시세/업종/호가/계좌 상태를 기반으로 매수/매도 신호를 생성한다.

원칙:

- strategy는 broker API를 직접 호출하지 않는다.
- strategy는 UI를 직접 변경하지 않는다.
- strategy는 `TradeSignal`만 생성한다.
- 같은 입력에 같은 결과가 나오도록 deterministic하게 만든다.

권장 흐름:

```text
MarketTickEvent
→ Feature Update
→ Sector/Stock Score Update
→ Buy/Sell Candidate Update
→ TradeSignal
```

---

## 5. Safety Layer

자동매매 시스템에서 Safety Layer는 옵션이 아니라 필수다.

검증 항목:

```text
자동매매 ON/OFF
장 시간
일일 최대 매수 금액
종목당 최대 매수 금액
최대 보유 종목 수
중복 주문 방지
미체결 주문 존재 여부
가격 범위
수량 범위
브로커/계좌 상태
거래정지/주의 종목 제외
```

Safety Layer는 주문 직전 마지막 관문이어야 한다.

---

## 6. Order Engine

### 목표

주문은 반드시 상태기계로 관리한다.

권장 상태:

```text
NEW
VALIDATED
SUBMITTED
ACKED
PARTIALLY_FILLED
FILLED
CANCEL_REQUESTED
CANCELED
REJECTED
UNKNOWN_RECOVERY
```

### 원칙

- 주문 요청과 체결 반영을 분리한다.
- 포지션은 주문 발생이 아니라 체결 이벤트 기준으로 변경한다.
- 브로커 주문번호와 내부 주문 ID 매핑은 journal에 남긴다.
- 체결 이벤트는 절대 drop하지 않는다.

---

## 7. Persistence / Journal

1인 로컬 앱이라도 자동매매에는 복구성이 필요하다.

### 필수 저장 대상

```text
settings
broker credentials reference
order journal
fill journal
position snapshot
trade history
download cache
sector classification
```

### 권장 방식

초기:

```text
JSON atomic write
파일 잠금
백업 파일 유지
```

고도화:

```text
SQLite WAL
order/fill append-only journal
snapshot table
```

장마감 분석:

```text
DuckDB 또는 Parquet 검토
```

---

## 8. Backend WebSocket Outbound

### 채널 분리 권장

```text
/ws/control
/ws/account
/ws/market
```

control:

```text
engine-ready
settings-changed
download-progress
bootstrap-stage
```

account:

```text
account-update
order-filled
position-update
buy-limit-status
```

market:

```text
real-data
orderbook-update
sector-score
```

### outbound queue 원칙

```text
client별 queue
market queue는 latest-only coalescing
account/order queue는 drop 금지
느린 client는 market event drop 허용
```

---

## 9. Frontend 궁극 구조

프론트는 React만으로 HTS급 실시간 테이블을 처리하면 안 된다.

권장 역할 분리:

```text
React
- 라우팅
- 레이아웃
- 설정 화면
- 저빈도 상태

Web Components
- 실시간 테이블
- 종목 리스트
- 체결/호가/업종 랭킹 표시

Web Worker
- 업종 점수 계산
- 매수 후보 계산
- 매도 조건 계산

Hot Store
- mutable realtime state
- render와 분리

Snapshot Store
- UI가 읽는 안정적 read model
```

---

## 10. Frontend 실시간 데이터 흐름

권장 흐름:

```text
WebSocket binary frame
→ decoder
→ frontend coalescing
→ hot mutable store
→ snapshot publisher
→ WebComponent updateData
→ React는 최소 관여
```

금지:

```text
tick마다 React setState
실시간 이벤트마다 console.log
대형 배열 전체 replace 반복
메인 스레드에서 무거운 계산
```

---

## 11. 프로토콜 표준화

현재처럼 JSON, zlib JSON, Protobuf 단일, Protobuf batch가 혼재하면 안 된다.

권장:

```text
Control/Account: JSON text
Market Tick: binary batch
```

Market binary batch 예:

```text
magic bytes
version
batch_seq
event_count
[event_length][event_payload]
[event_length][event_payload]
...
```

프론트 decoder는 반드시 이 포맷을 정확히 파싱해야 한다.

---

## 12. 관측/성능 지표

HTS급 최적화는 감이 아니라 숫자로 해야 한다.

필수 지표:

```text
broker_recv_ts
backend_ingest_ts
backend_flush_ts
frontend_recv_ts
frontend_apply_ts
ui_render_ts
order_signal_ts
order_submit_ts
broker_ack_ts
fill_recv_ts
position_update_ts
```

권장 표시:

```text
최근 1분 평균 latency
p95 latency
drop count
queue depth
reconnect count
worker response time
FPS
```

단, 지표 수집 자체가 hot path를 막으면 안 된다.

---

## 결론

궁극 구조의 핵심은 다음이다.

```text
실시간 수신은 가볍게
이벤트는 명확히 분류
시세는 coalescing 가능
주문/체결은 drop 금지
프론트는 React와 hot path를 분리
모든 지연은 숫자로 측정
DI/상태/프로토콜은 단일 진실 공급원으로 통일
```
