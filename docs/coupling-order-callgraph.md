# C-04 주문 호출 그래프와 side effect 경계

> 작성일: 2026-07-26
> 기준 계획서: `docs/coupling-audit-plan.md` C-04
> 상태: 조사 완료 (코드 수정 없음 — safe-trade 절차 적용)
> 대상 원칙: P10 SSOT, P15 단일 주문 경로, P16 살아있는 경로, P18 테스트모드 동등성, P20 오류 의미 보존, P21 사용자 투명성, P24 단순성, P25 격리된 실패

---

## 1. 조사 범위 및 방법

### 1.1 조사 대상 파일

| 파일 | 줄 수 | 역할 |
|------|-------|------|
| `backend/app/services/trading.py` | 886 | `execute_buy()`/`execute_sell()`/`check_sell_conditions()`/`on_fill_update()` 단일 진입점 + 매수 실패 사유 상수 |
| `backend/app/services/buy_order_executor.py` | 235 | 업종 매수 후보 순회 → `execute_buy()` 호출, 사유 분류(전체/종목별), 조건 스냅샷 게이트 |
| `backend/app/services/risk_manager.py` | 250 | 서킷브레이커/일일 손실/손실률/연속 손실/예수금/단일 종목 비중 게이트 |
| `backend/app/services/settlement_engine.py` | 344 | 테스트모드 전용 누적투자금/주문가능금액 관리, 사전 차감/롤백, 기동 정합성 대조 |
| `backend/app/services/engine_account.py` | 439 | 계좌 스냅샷/포지션 조회, `_on_fill_after_ws()` 체결 후 갱신, `_broadcast_account()` |
| `backend/app/services/engine_account_notify.py` | 457+ | WS 브로드캐스트 헬퍼(`_broadcast`/`_safe_broadcast`), delta 계산, 헤더 칩 알림 |
| `backend/app/services/dry_run.py` | 324 | 테스트모드 가상 체결 엔진, `fake_send_order()`/`fake_fill_event()`, 가상 잔고 |
| `backend/app/services/engine_strategy_core.py` | 43 | `reserve_test_buy_power()` — 테스트모드 사전 차감 래퍼 |
| `backend/app/services/order_interval.py` | 40 | 매수/매도 주문 간격 게이트 공통 헬퍼 |
| `backend/app/core/broker_providers.py` | 72 | `OrderProvider` ABC — `send_order()` 인터페이스 |
| `backend/app/core/journal.py` | 103 | `record_order_request()` — 주문 요청 저널링 |
| `backend/app/services/engine_ws_dispatch.py` | 169 | `_handle_real_00()` — 실전 체결(00) 이벤트 디스패치 |
| `frontend/src/binding.ts` | 339 | WS 이벤트 → uiStore 액션 배칭 (7개 주문 차단 이벤트) |
| `frontend/src/stores/uiStore.ts` | 294+ | 주문 차단 상태 7개 필드 + apply/clear 액션 |
| `frontend/src/utils/order-block-status.ts` | 95 | `computeOrderBlockStatus()` — 차단 상태 통합 판정 (P10 SSOT) |
| `frontend/src/layout/header.ts` | — | 차단 상태 헤더 칩 렌더링 (서킷브레이커/시간대/리스크/테스트잔고) |

### 1.2 조사 방법

- `send_order`/`fake_send_order` 전체 grep → 주문 전송 호출부 7건 확인 (trading.py 4건 = 단일 경로, 나머지는 정의/문서)
- `execute_buy`/`execute_sell` 전체 grep → 단일 진입점 확인
- `BUY_REJECT_*` 상수 18개 전체 grep → 사유코드 소비자 추적
- `circuit-breaker-open`/`risk-block-status`/`order-time-blocked`/`realtime-latency-status`/`daily-buy-state-status`/`test-cash-failed`/`buy-limit-status` 7개 WS 이벤트 → binding.ts → uiStore → header.ts/buy-target.ts 소비자 추적
- `is_test_mode` 분기 지점 전체 grep → P18 동등성 점검
- `RiskManager`/`CircuitBreaker` 호출 지점 추적 → P16 살아있는 경로 점검

---

## 2. 주문 단일 진입점 (P15 준수 확인)

### 2.1 진입점 구조

```
┌─────────────────────────────────────────────────────────────────┐
│  자동매매 트리거                                                 │
│  ├─ buy_order_executor.evaluate_buy_candidates()                │
│  │   └─ state.auto_trade.execute_buy()  ← 매수 유일 진입점     │
│  └─ trading.check_sell_conditions()                             │
│      └─ state.auto_trade.execute_sell()  ← 매도 유일 진입점    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 주문 전송 호출부 전수 조사

`send_order`/`fake_send_order` 호출부 (`backend/app` 전체 grep):

| 호출부 | 파일:줄 | 모드 | 비고 |
|--------|---------|------|------|
| `dry_run.fake_send_order("BUY", ...)` | `trading.py:415` | test | execute_buy 내부 |
| `get_router().order.send_order("BUY", ...)` | `trading.py:420` | real | execute_buy 내부 |
| `dry_run.fake_send_order("SELL", ...)` | `trading.py:629` | test | execute_sell 내부 |
| `get_router().order.send_order("SELL", ...)` | `trading.py:633` | real | execute_sell 내부 |

**P15 준수 확인**: 주문 전송은 `execute_buy()`/`execute_sell()` 내부에서만 발생. 우회 경로·분기 경로·병렬 경로 없음. `broker_router.py:40`은 docstring 예시, `dry_run.py:118`은 함수 정의.

---

## 3. execute_buy() 호출 그래프

> `trading.py:200-523` — 매수 주문 실행 본문. 글로벌 매수 락(`asyncio.Lock`)으로 순차 처리.

### 3.1 단계별 호출 그래프

```
execute_buy(stk_cd, current_price, access_token, reason)
│
├─ [1] 글로벌 매수 락 획득 (asyncio.Lock — TOCTOU 경쟁 상태 방지, P22)
│
└─ _execute_buy_locked()
   │
   ├─ [2] _ensure_daily_buy_counter()
   │   └─ trade_history.get_buy_history(today_only=True) → _daily_buy_spent/_bought_today/_symbol_daily_buy_spent 로드
   │      실패 시 → _daily_buy_spent=None → [차단] BUY_REJECT_DAILY_STATE
   │
   ├─ [3] 실시간 지연 게이트 (fail-closed — P20/P25)
   │   └─ engine_state.realtime_latency_exceeded 확인
   │      True/체크실패 → [차단] BUY_REJECT_REALTIME_LATENCY
   │
   ├─ [4] 자동매매 게이트
   │   └─ settings["is_auto"] 확인
   │      False → [차단] BUY_REJECT_AUTO_BUY_OFF
   │
   ├─ [5] 체결 불가 시간대 게이트
   │   └─ _is_order_time_blocked(stk_cd)
   │      True → [차단] BUY_REJECT_TIME_BLOCKED (종목별)
   │
   ├─ [6] 재매수 차단 게이트
   │   └─ rebuy_block_on + _bought_today 조회
   │      차단 → [차단] BUY_REJECT_REBUY (종목별)
   │
   ├─ [7] 미체결/연속신호 게이트
   │   ├─ has_open_buy=True → [차단] BUY_REJECT_OPEN_ORDER (종목별)
   │   └─ 30초 내 재신호 → [차단] BUY_REJECT_SIGNAL_INTERVAL (종목별)
   │
   ├─ [8] 최대 보유 종목 수 게이트
   │   └─ engine_account.get_positions() → holding_count 체크
   │      초과 → [차단] BUY_REJECT_MAX_HOLDING
   │
   ├─ [9] 종목당/일일 한도 게이트
   │   ├─ buy_amt ≤ 0 → [차단] BUY_REJECT_BUY_AMT_ZERO
   │   ├─ 종목 누적 초과 → [차단] BUY_REJECT_SYMBOL_LIMIT (종목별)
   │   └─ 일일 한도 초과 → [차단] BUY_REJECT_DAILY_LIMIT
   │
   ├─ [10] 현재가 체크
   │   └─ current_price ≤ 0 → [차단] BUY_REJECT_PRICE_ZERO (종목별)
   │
   ├─ [11] 등락률 가드
   │   └─ engine_state.master_stocks_cache에서 등락률 조회
   │      상승/하락 가드 → [차단] BUY_REJECT_RISE_GUARD / BUY_REJECT_FALL_GUARD (종목별)
   │
   ├─ [12] 주문가능 금액 + 수량 계산
   │   ├─ risk_manager.get_withdrawable_deposit()
   │   ├─ dry_run.estimate_fill_price() (테스트모드 슬리피지)
   │   └─ settlement_engine.max_buy_qty_for_budget()
   │      buy_qty ≤ 0 → [차단] BUY_REJECT_QTY_ZERO (조건부 — 잔액 0이면 전체, 단가 비싸면 종목별)
   │
   ├─ [13] RiskManager 게이트 (P16 — 주문 전 필수)
   │   └─ risk_manager.check_buy_order_allowed(stk_cd, price, qty)
   │      ├─ 서킷브레이커 → [차단] BUY_REJECT_RISK_CIRCUIT
   │      ├─ 일일 손실 한도 → [차단] BUY_REJECT_RISK_LOSS + _notify_telegram("🛑 [자동매매 중단] 일일 손실 한도 도달 — ...") (P21)
   │      ├─ 일일 손실률 한도 → [차단] BUY_REJECT_RISK_LOSS_RATE + _notify_telegram("🛑 [자동매매 중단] 일일 손실률 한도 도달 — ...") (P21)
   │      ├─ 연속 손실 한도 → [차단] BUY_REJECT_RISK_CONSEC_LOSS
   │      ├─ 예수금 부족 → [차단] BUY_REJECT_RISK_CASH
   │      └─ 단일 종목 비중 → [차단] BUY_REJECT_RISK_SINGLE (종목별)
   │      차단 시 → _fire_and_forget_telegram("🛑 [리스크차단] {종목명}({코드}) 매수 차단 — {사유}") (P21)
   │               + _safe_broadcast("risk-block-status", {blocked, side="buy", reason}) (P21)
   │
   ├─ [14] _buy_state 갱신 (has_open_buy=True)
   ├─ [15] 텔레그램 알림 (NotificationWorker 큐 — fire-and-forget)
   │
   ├─ [16] 테스트모드 사전 차감 (P22 — TOCTOU 방지)
   │   └─ engine_strategy_core.reserve_test_buy_power()
   │      └─ settlement_engine.reserve_buy_power() — 검증 + 즉시 차감 (원자적)
   │         실패 → [차단] BUY_REJECT_TEST_CASH + _broadcast_test_cash_failed() (P21)
   │
   ├─ [17] 주문 전송 (P15 단일 경로, P18 모드 분기 — 돈 I/O 최소 지점)
   │   ├─ 테스트: dry_run.fake_send_order()
   │   └─ 실전: get_router().order.send_order()
   │
   ├─ [17a] 주문 실패 시
   │   ├─ _buy_state["has_open_buy"] = False
   │   ├─ 텔레그램 알림 (실패)
   │   ├─ settlement_engine.release_buy_power(_reserved_cost) — 사전 차감 롤백 (P22)
   │   ├─ risk_manager.record_order_failure()
   │   └─ 서킷브레이커 OPEN 시:
   │       ├─ state.integrated_system_settings_cache["time_scheduler_on"] = False (강제 OFF)
   │       ├─ _broadcast("circuit-breaker-open", {message}) (P21)
   │       ├─ notify_desktop_header_refresh()
   │       └─ notify_desktop_settings_toggled({"time_scheduler_on": False})
   │   → [차단] BUY_REJECT_ORDER_FAIL
   │
   ├─ [18] 저널링: journal.record_order_request(side="buy")
   │
   ├─ [19] 한도 누적 갱신
   │   ├─ _daily_buy_spent += spent (수수료 포함 — 테스트 / 순수 매수가 — 실전, P18)
   │   └─ _symbol_daily_buy_spent[stk_cd] += spent
   │
   ├─ [20] _bought_today[stk_cd] = time.time() (재매수 차단용)
   │
   ├─ [21] 체결 이력 기록: trade_history.record_buy()
   │
   ├─ [22] 매수 한도 상태 WS 브로드캐스트
   │   └─ engine_account._broadcast_buy_limit_status() → "buy-limit-status" 이벤트 (P21)
   │
   ├─ [23] 테스트모드 가상 체결 예약
   │   └─ schedule_engine_task(dry_run.fake_fill_event("BUY", ...))
   │      └─ (지연 실행) _apply_buy → settlement_engine 영속화/브로드캐스트
   │                     → on_fill_update (has_open_buy 해제)
   │                     → engine_account._on_fill_after_ws() (계좌 갱신 + 매도 조건 검사)
   │
   └─ [24] RiskManager 성공 보고 (P16 — 주문 후 필수)
       ├─ risk_manager.record_order_success()
       └─ 서킷브레이커 HALF_OPEN→CLOSED 시 텔레그램 복구 알림
```

### 3.2 단계별 입력·출력·상태 변경·side effect

| 단계 | 입력 | 출력 | 상태 변경 | 외부 side effect |
|------|------|------|-----------|------------------|
| [2] 일일 카운터 | trade_history | _daily_buy_spent, _bought_today, _symbol_daily_buy_spent | 메모리 | DB 읽기 |
| [3] 지연 게이트 | engine_state.realtime_latency_exceeded | bool | 없음 | 없음 |
| [5] 시간대 게이트 | stk_cd, daily_time_scheduler | bool | 없음 | 없음 |
| [8] 보유 종목 수 | engine_account.get_positions() | holding_count | 없음 | 테스트: dry_run / 실전: state.positions |
| [12] 수량 계산 | risk_manager, settlement_engine, dry_run | buy_qty | 없음 | 없음 |
| [13] RiskManager | stk_cd, price, qty | (allowed, reason) | risk_manager 임계치 동기화 | trade_history 읽기 (손실/연속손실) |
| [16] 사전 차감 | settlement_engine | (ok, reason, cost) | _orderable 차감 | DB 쓰기(settlement_state), WS 브로드캐스트 |
| [17] 주문 전송 | dry_run / broker_router | res | 없음 | 테스트: 가상 / 실전: 증권사 API |
| [17a] 실패 처리 | risk_manager, settlement_engine | 없음 | _orderable 복원, circuit_breaker, time_scheduler_on | WS 브로드캐스트(circuit-breaker-open) |
| [18] 저널링 | journal | 없음 | 없음 | journal 큐 |
| [21] 체결 이력 | trade_history | 없음 | _positions_dirty=True | DB 쓰기(trades) |
| [22] 한도 브로드캐스트 | engine_account | 없음 | 없음 | WS "buy-limit-status" |
| [23] 가상 체결 | dry_run | 없음 | _orderable, _test_positions | DB 쓰기, WS "account-update" |
| [24] 성공 보고 | risk_manager | 없음 | circuit_breaker 상태 | 텔레그램 (복구 시) |

---

## 4. execute_sell() 호출 그래프

> `trading.py:559-709` — 매도 주문 실행. 매도는 사유코드 반환 없이 bool만 반환 (check_sell_conditions에서 건별 간격 적용에만 사용).

### 4.1 단계별 호출 그래프

```
execute_sell(stk_cd, cur_price, stk_nm, reason, qty, pnl_rate, trade_settings, base_settings, access_token)
│
├─ [1] 자동매도 게이트
│   └─ trade_settings["is_sell_auto"] False → return False
│
├─ [2] 체결 불가 시간대 게이트
│   └─ _is_order_time_blocked(stk_cd) True → return False
│
├─ [3] 텔레그램 알림 (매도 주문 전송)
├─ [4] _recent_sells.add(stk_cd) — 재주문 차단
│
├─ [5] 평균매입가 사전 조회 (P18 미세 분기 — 의도적, docstring 명시)
│   ├─ 테스트: trade_history.build_positions_from_trades("test")
│   │   └─ 유령 포지션 차단 (qty 부족 시 매도 중단, 안전장치)
│   └─ 실전: engine_account.get_positions() → 브로커 잔고 직접 조회
│
├─ [6] 주문 전송 (P15 단일 경로, P18 모드 분기)
│   ├─ 테스트: dry_run.fake_send_order("SELL", ...)
│   └─ 실전: get_router().order.send_order("SELL", ...)
│
├─ [6a] 주문 실패 시
│   ├─ _recent_sells.discard(stk_cd)
│   ├─ 텔레그램 알림 (실패)
│   ├─ risk_manager.record_order_failure()
│   └─ 서킷브레이커 OPEN 시:
│       ├─ state.integrated_system_settings_cache["time_scheduler_on"] = False
│       ├─ _broadcast("circuit-breaker-open", {message})
│       ├─ notify_desktop_header_refresh()
│       └─ notify_desktop_settings_toggled({"time_scheduler_on": False})
│   → return False
│
├─ [7] 매도 주문 간격 타이머 갱신
│   └─ order_interval.mark_order_executed("sell") → state._last_global_sell_ts
│
├─ [8] 저널링: journal.record_order_request(side="sell")
│
├─ [9] 체결 이력 기록: trade_history.record_sell()
│
├─ [10] 테스트모드 가상 체결 예약
│   └─ schedule_engine_task(dry_run.fake_fill_event("SELL", ...))
│      └─ (지연 실행) _apply_sell → settlement_engine.on_sell_fill()
│                     → on_fill_update (_recent_sells 해제)
│                     → engine_account._on_fill_after_ws() (계좌 갱신 + 매도 조건 재검사)
│
└─ [11] RiskManager 성공 보고 (P16)
    ├─ risk_manager.record_order_success()
    └─ 서킷브레이커 HALF_OPEN→CLOSED 시 텔레그램 복구 알림
    → return True
```

### 4.2 check_sell_conditions() 사전 게이트

> `trading.py:711-` — 매도 조건 순회. 1건 매도 성공 후 루프 종료 (건별 간격).

```
check_sell_conditions(stock_list, base_settings, access_token)
│
├─ [1] 자동매도 게이트 (is_sell_auto)
├─ [2] 실시간 지연 게이트 (fail-closed — 매수와 동일 정책, P23)
├─ [3] RiskManager 매도 차단 체크
│   └─ risk_manager.check_sell_order_allowed()
│      차단 → _fire_and_forget_telegram("🛑 [리스크차단] 매도 전체 차단 — {reason}") (P21)
│             + _safe_broadcast("risk-block-status", {blocked, side="sell", reason}) (P21)
├─ [4] 매도 주문 간격 게이트
│   └─ order_interval.check_order_interval("sell")
└─ [5] for stock in stock_list:
    ├─ 손절(chk_loss) → execute_sell("손절 발동")
    ├─ 익절(chk_tp) → execute_sell("익절 발동")
    └─ T/S 익절(chk_ts) → execute_sell("T/S 익절")
    성공 시 break (건별 간격), 실패 시 continue (차순위)
```

---

## 5. 체결 이벤트 처리 그래프

### 5.1 실전 체결 (WS "00" 이벤트)

```
WS "00" (주문체결)
└─ engine_ws_dispatch._handle_real_00(item, vals)
   ├─ auto_trade.on_fill_update(raw_cd, side, unex, access_token)
   │   ├─ side="1", unex=0: 매수 체결 → has_open_buy=False, 텔레그램
   │   ├─ side="2", unex=0: 매도 체결 → _recent_sells.discard, 텔레그램
   │   └─ side="3","4": has_open_buy=False
   └─ engine_account._on_fill_after_ws()
       ├─ _refresh_account_snapshot_meta() — 계좌 스냅샷 갱신
       └─ auto_trade.check_sell_conditions() — 매도 조건 재검사
```

### 5.2 테스트 가상 체결 (dry_run.fake_fill_event)

```
schedule_engine_task(dry_run.fake_fill_event("BUY"/"SELL", ...))
└─ (FAKE_FILL_DELAY 0.1초 후)
   ├─ _apply_buy/_apply_sell
   │   ├─ BUY: settlement_engine.on_buy_fill() 또는 _persist+_broadcast_delta (pre_reserved)
   │   └─ SELL: settlement_engine.on_sell_fill()
   │           └─ (잔고 회복 시) buy_order_executor.evaluate_buy_candidates() — 상태 게이트 회복
   ├─ on_fill_update (실전 _handle_real_00과 동일)
   └─ engine_account._on_fill_after_ws() (실전과 동일)
```

**P18 준수**: 테스트 가상 체결은 실전 WS "00"과 동일한 downstream 호출 체인을 사용. 모드 분기는 돈 I/O 최소 지점(`fake_send_order` vs `send_order`, `settlement_engine` vs `account_snapshot`)에서만 발생.

---

## 6. RiskManager / CircuitBreaker 배선 (P16 점검)

### 6.1 RiskManager 호출 지점

| 호출부 | 파일:줄 | 시점 | 비고 |
|--------|---------|------|------|
| `check_buy_order_allowed()` | `trading.py:438` | 주문 전 | execute_buy 내부 — P16 준수 |
| `check_sell_order_allowed()` | `trading.py:776` | 매도 조건 순회 전 | check_sell_conditions 내부 |
| `record_order_failure()` | `trading.py:432, 641` | 주문 실패 시 | execute_buy/execute_sell 내부 |
| `record_order_success()` | `trading.py:515, 701` | 주문 성공 시 | execute_buy/execute_sell 내부 |
| `get_withdrawable_deposit()` | `trading.py:363`, `buy_order_executor.py:126, 220` | 주문가능 금액 조회 | 주문 전 + 사전 체크 |

**P16 준수**: RiskManager는 주문 함수 내부에서 호출됨. 외부 사전 체크 후 주문 함수 내부 검사 생략 패턴 없음. `buy_order_executor`의 사전 체크는 `evaluate_buy_candidates()` 진입 시 조기 차단 목적이며, `execute_buy()` 내부에서 다시 RiskManager를 호출하므로 이중 안전장치.

### 6.2 CircuitBreaker 상태 전이

```
CLOSED (정상)
  │ record_order_failure() ×N (임계치 도달)
  ↓
OPEN (차단 — 모든 주문 거부)
  │ time_scheduler_on = False (마스터 스위치 강제 OFF)
  │ _broadcast("circuit-breaker-open")
  │ (타이머 경과 후)
  ↓
HALF_OPEN (복구 시도 — 1건 주문 허용)
  │ record_order_success() → CLOSED (복구 완료, 텔레그램 알림)
  │ record_order_failure() → OPEN (재차단)
```

---

## 7. 주문 실패 사유 → WS 이벤트 → 프론트엔드 계약

### 7.1 매수 실패 사유코드 (trading.py 상수)

| 사유코드 | 상수 | 분류 | WS 이벤트 | 프론트엔드 필드 |
|----------|------|------|-----------|-----------------|
| `daily_state` | BUY_REJECT_DAILY_STATE | 전체 | `daily-buy-state-status` | `dailyBuyStateFailed` |
| `realtime_latency` | BUY_REJECT_REALTIME_LATENCY | 전체 | `realtime-latency-status` | `realtimeLatencyExceeded` |
| `auto_buy_off` | BUY_REJECT_AUTO_BUY_OFF | 전체 | (없음 — uiStore에서 settings 기반 판정) | `computeOrderBlockStatus` |
| `max_holding` | BUY_REJECT_MAX_HOLDING | 전체 | (없음) | — |
| `buy_amt_zero` | BUY_REJECT_BUY_AMT_ZERO | 전체 | (없음) | — |
| `daily_limit` | BUY_REJECT_DAILY_LIMIT | 전체 | `buy-limit-status` | `buyLimitStatus` |
| `risk_circuit` | BUY_REJECT_RISK_CIRCUIT | 전체 | `circuit-breaker-open` | `circuitBreakerOpen` |
| `risk_loss` | BUY_REJECT_RISK_LOSS | 전체 | `risk-block-status` | `riskBlockStatus` |
| `risk_loss_rate` | BUY_REJECT_RISK_LOSS_RATE | 전체 | `risk-block-status` | `riskBlockStatus` |
| `risk_consec_loss` | BUY_REJECT_RISK_CONSEC_LOSS | 전체 | `risk-block-status` | `riskBlockStatus` |
| `risk_cash` | BUY_REJECT_RISK_CASH | 전체 | `risk-block-status` | `riskBlockStatus` |
| `test_cash` | BUY_REJECT_TEST_CASH | 전체 | `test-cash-failed` | `testCashFailed` |
| `order_fail` | BUY_REJECT_ORDER_FAIL | 전체 | `circuit-breaker-open` (서킷브레이커 시) | `circuitBreakerOpen` |
| `time_blocked` | BUY_REJECT_TIME_BLOCKED | 종목별 | `order-time-blocked` | `orderTimeBlocked` |
| `rebuy` | BUY_REJECT_REBUY | 종목별 | (없음) | — |
| `open_order` | BUY_REJECT_OPEN_ORDER | 종목별 | (없음) | — |
| `signal_interval` | BUY_REJECT_SIGNAL_INTERVAL | 종목별 | (없음) | — |
| `price_zero` | BUY_REJECT_PRICE_ZERO | 종목별 | (없음) | — |
| `rise_guard` | BUY_REJECT_RISE_GUARD | 종목별 | (없음) | — |
| `fall_guard` | BUY_REJECT_FALL_GUARD | 종목별 | (없음) | — |
| `symbol_limit` | BUY_REJECT_SYMBOL_LIMIT | 종목별 | (없음) | — |
| `risk_single` | BUY_REJECT_RISK_SINGLE | 종목별 | `risk-block-status` | `riskBlockStatus` |
| `qty_zero` | BUY_REJECT_QTY_ZERO | 조건부 | (없음 — 잔액 0 시 별도) | — |

**P10 SSOT**: `BUY_GLOBAL_REJECT_REASONS` frozenset이 사유 분류의 단일 진실 소스 (`trading.py:59-73`).
**P23 일관성**: 사유코드는 `buy_order_executor.py:182-184`에서 import하여 소비.

### 7.2 매도 실패

매도는 사유코드 없이 `bool`만 반환. `check_sell_conditions()`에서 건별 간격 적용에만 사용. 매도 차단 사유는 `risk-block-status` WS 이벤트(`side="sell"`)로 전달되며, 사용자에게 동일한 헤더 칩으로 표시됨.

### 7.3 프론트엔드 통합 판정 (order-block-status.ts)

```
computeOrderBlockStatus(side, uiState, settings)
├─ circuitBreakerOpen → "차단: 서킷브레이커"
├─ realtimeLatencyExceeded → "차단: 실시간 지연"
├─ riskBlockStatus.side === side → "차단: 리스크(reason)"
├─ orderTimeBlocked → "차단: reason"
├─ dailyBuyStateFailed (매수만) → "차단: 일일 상태 오류"
├─ !time_scheduler_on → "차단: 자동매매 OFF"
├─ !auto_buy_on / !auto_sell_on → "차단: 자동매수/매도 OFF"
└─ 시간대 외 → "차단: 매수/매도 시간대 외"
```

우선순위: 서킷브레이커 > 실시간 지연 > 리스크 > 시간대 > 일일 상태 > 자동매매 OFF > 시간대 외.

---

## 8. P15/P16/P18 점검 결과

### 8.1 P15 (단일 주문 경로) — 준수

- `send_order`/`fake_send_order` 호출부 4건 모두 `execute_buy()`/`execute_sell()` 내부.
- 우회 경로·분기 경로·병렬 경로 없음.
- `broker_router.py:40`은 docstring 예시, `dry_run.py:118`은 함수 정의.

### 8.2 P16 (살아있는 경로) — 준수

- RiskManager: `execute_buy()` 내부에서 `check_buy_order_allowed()` 호출 (trading.py:438). `check_sell_conditions()`에서 `check_sell_order_allowed()` 호출 (trading.py:776).
- CircuitBreaker: 주문 실패 시 `record_order_failure()` (trading.py:432, 641), 성공 시 `record_order_success()` (trading.py:515, 701). 주문 전후 모두 호출.
- `buy_order_executor.evaluate_buy_candidates()`의 사전 RiskManager 체크는 조기 차단 목적이며, `execute_buy()` 내부에서 다시 호출하므로 dead code 아님.

### 8.3 P18 (테스트모드 동등성) — 준수 (1건 미세 위반 소지, 의도적)

- 모드 분기는 돈 I/O 최소 지점에서만:
  - 주문 전송: `fake_send_order()` vs `send_order()` (trading.py:415/420, 629/633)
  - 예수금 조회: `settlement_engine.get_available_cash()` vs `account_snapshot["orderable"]` (risk_manager.py:161-164)
  - 포지션 조회: `dry_run.get_positions()` vs `state.positions` (engine_account.py:386-389)
  - 사전 차감: `reserve_test_buy_power()` — 테스트모드 전용 (실전은 증권사 서버가 SSOT)
- **미세 위반 소지 (의도적)**: `execute_sell()`의 평균매입가 조회 (trading.py:600-622) — 테스트는 `trade_history.build_positions_from_trades()`로 유령 포지션 차단 안전장치, 실전은 `get_positions()`로 브로커 잔고 직접 조회. docstring에 "엄격 해석상 미세 위반 소지 있으나 현행 유지 — 테스트모드는 유령 포지션 차단 검사를 수행하는 안전장치이므로 분기가 의도적"으로 명시.
- 업종 점수 계산, 필터링, 타이밍 로직은 테스트/실전 동일.

---

## 9. 결합도 관찰 및 개선 후보

> 본 세션은 조사만 수행. 개선은 별도 승인 후 진행.

### 9.1 관찰된 결합 형태

| 결합 | 위치 | 원칙 | 비고 |
|------|------|------|------|
| 주문 함수 내 정책·상태·전송·기록·알림 집중 | `trading.py` execute_buy/execute_sell | P24 | 계획서 C-04 관찰과 일치 — 단일 주문 API 안에 8+ 책임 집중. 거래 안전성 때문에 성급한 분리 금지. |
| 서킷브레이커 차단 처리 로직 중복 | `trading.py:430-446` (매수), `639-655` (매도) | P24 단순성 | 동일한 7줄 패턴 (record_order_failure → circuit_breaker OPEN 시 마스터 OFF + 브로드캐스트 + header_refresh + settings_toggled). 헬퍼 추출 후보. |
| `_broadcast_test_cash_failed`/`_broadcast_daily_buy_state_status` trading.py에 정의 | `trading.py:110-134` | P23 일관성 | 다른 WS 브로드캐스트 헬퍼는 `engine_account_notify.py`에 집중. trading.py의 2개 헬퍼는 `_safe_broadcast`를 lazy import하여 호출. 이동 검토 가능하나 trading.py에서만 호출되므로 응집성 관점에서 현행 유지 가능. |
| settlement_engine → buy_order_executor 역방향 호출 | `settlement_engine.py:137-140` | 결합도 역참조 | `on_sell_fill()`에서 잔고 회복 시 `evaluate_buy_candidates()` 호출. 상태 게이트 회복 목적이나, 정산 엔진이 매수 실행기를 직접 호출하는 역방향 의존. |
| 매수 사유코드 체계화 vs 매도 사유코드 부재 | `trading.py` | P23 일관성 | 매수는 18개 BUY_REJECT_* 상수 + frozenset 분류. 매도는 bool만 반환. 매도는 check_sell_conditions에서 건별 간격 적용에만 사용하므로 사유 분류 불필요 — 현행 유지 적합. |
| execute_sell 평균매입가 조회 모드 분기 | `trading.py:600-622` | P18 | 의도적 분기 (docstring 명시). 테스트: 유령 포지션 차단 안전장치. |

### 9.2 개선 후보 (우선순위)

| 후보 | 우선순위 | 원칙 | 위험도 | 비고 |
|------|---------|------|--------|------|
| 서킷브레이커 차단 처리 헬퍼 추출 | 낮음 | P24 | 낮음 | 매수/매도 7줄 중복 → 헬퍼 1개. 단, 거래 로직이므로 safe-trade 승인 필수. |
| `_broadcast_test_cash_failed`/`_broadcast_daily_buy_state_status` 이동 검토 | 낮음 | P23 | 낮음 | `engine_account_notify.py`로 이동. 단, trading.py에서만 호출되므로 응집성 관점에서 현행 유지 가능. |
| settlement_engine → buy_order_executor 역방향 호출 완화 | 낮음 | 결합도 | 중간 | 역방향 의존을 느슨하게 하려면 콜백/이벤트 구조 필요. 단, P5(직접 호출) 원칙과 P11(이벤트 기반) 균형. 현재는 단일 프로세스에서 직접 호출이 적합. |

### 9.3 변경 금지 항목 (거래 안전성)

- `execute_buy()`/`execute_sell()` 단일 진입점 — P15
- RiskManager/CircuitBreaker 주문 함수 내부 호출 — P16
- 테스트모드 사전 차감/롤백 (reserve_buy_power/release_buy_power) — P22
- 모드 분기는 돈 I/O 최소 지점에서만 — P18
- 서킷브레이커 OPEN 시 마스터 스위치 강제 OFF — 안전장치
- 매수 실패 사유코드 체계 (BUY_REJECT_* + frozenset) — P10 SSOT
- 7개 WS 차단 이벤트 → uiStore → header.ts 계약 — P21

---

## 10. safe-trade 점검 결과

| 점검 항목 | 결과 | 비고 |
|-----------|------|------|
| TRADE_MODE/모의투자 플래그 | 준수 | `trade_mode.py` — `normalize_trade_mode()`가 "real"만 실전, 그 외 "test". 기본 "test". |
| 하드코딩 자격증명 | 없음 | `backend/app` 전체 grep — api_key/password/secret/token 하드코딩 0건. |
| test_mode 보호 | 준수 | `is_test_mode()` 분기로 실전 서버 주문 차단. 테스트: `fake_send_order()`, 실전: `send_order()`. |
| 단일 주문 경로 (P15) | 준수 | `execute_buy()`/`execute_sell()` 내부에서만 주문 전송. |
| RiskManager 배선 (P16) | 준수 | 주문 함수 내부에서 호출. 외부 사전 체크 후 내부 검사 생략 없음. |
| 테스트모드 동등성 (P18) | 준수 | 모드 분기는 돈 I/O 최소 지점. 1건 의도적 분기(docstring 명시). |
| 기존 로직 롤백 여부 | 해당 없음 | 본 세션은 조사만 수행. 코드 수정 없음. |

---

## 11. 검증 결과

본 세션은 조사·문서 작성만 수행 (코드 수정 없음). 따라서 런타임 검증(테스트·기동)은 생적 대조 기반으로 생략.

- 주문 함수·호출부·실패 사유 상수·알림 payload 전체 참조 검색: 완료
- safe-trade 절차에 따른 실전/모의투자 경계와 단일 주문 경로 확인: 완료 (P15/P16/P18 준수)
- `coupling-audit-tasks.md` COUPLING-S4 상태 ☑ 갱신: 완료
- `HANDOVER.md` 갱신: 완료

---

## 12. 다음 세션 권장

- **COUPLING-S5** (C-05 스케줄러·파이프라인·실시간 엔진 경계) 진행 예정.
- 후속 개선은 9.2의 3개 후보 중 1개만 별도 승인 후 진행 권장 — 1순위: 서킷브레이커 차단 처리 헬퍼 추출 (P24, 낮은 위험도). 단, 거래 로직이므로 safe-trade 승인 필수.
