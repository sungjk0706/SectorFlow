# 테스트모드 동등성 위반 — 근본해결 계획서

## 1. 현황 분석

### 1.1 실전 모드 주문/체결 흐름 (기준)

```
execute_buy()
  ├─ has_open_buy = True (trading.py:268)
  ├─ send_order() → {"success": True} (주문 접수만)
  ├─ 저널 기록, _daily_buy_spent, _bought_today, trade_history 기록
  ├─ buy-limit-status 브로드캐스트
  └─ return True
       │
       │ (WS "00" 이벤트 도착 — 비동기, 별도 타이밍)
       ▼
  _handle_real_00() (engine_ws_dispatch.py:221)
  ├─ on_fill_update(stk_cd, side="1", unex=0) (trading.py:388)
  │   ├─ has_open_buy = False
  │   ├─ "[매수체결]" 로그 + 텔레그램
  │   └─ _buy_state 갱신
  └─ _on_fill_after_ws() (engine_account.py:423)
      ├─ refresh_account_snapshot_meta (계좌 스냅샷 갱신)
      └─ sell_if_applicable (매도 조건 검사)
```

**매도**도 동일 구조: `execute_sell()` → `send_order()` (접수) → WS "00" → `on_fill_update(side="2")` → `_recent_sells.discard()` + `_on_fill_after_ws()`

### 1.2 테스트 모드 주문/체결 흐름 (현재 — 위반)

```
execute_buy()
  ├─ has_open_buy = True (trading.py:268)
  ├─ fake_send_order() (dry_run.py:104)
  │   ├─ asyncio.sleep(0.1)
  │   ├─ _apply_buy() ← 포지션 생성 + settlement_engine.on_buy_fill()
  │   └─ return {"success": True} (주문 접수 + 체결 동시 처리)
  ├─ set_stock_name()
  ├─ 저널 기록, _daily_buy_spent, _bought_today, trade_history 기록
  ├─ buy-limit-status 브로드캐스트
  ├─ _dryrun_post_buy_broadcast() ← UI 갱신 (별도 함수)
  └─ return True

  (on_fill_update 호출 안 됨 — has_open_buy 영원히 True)
  (_on_fill_after_ws 호출 안 됨 — 매도 조건 검사 안 됨)
```

**매도**:
```
execute_sell()
  ├─ _recent_sells.add(stk_cd) (trading.py:446)
  ├─ fake_send_order() → _apply_sell() (포지션 삭제 + settlement_engine.on_sell_fill())
  ├─ 저널, trade_history 기록
  ├─ _dryrun_post_sell_broadcast()
  │   ├─ _broadcast_account()
  │   └─ _recent_sells 해제 (잔고 기반 폴백 — 원칙 20 위반)
  └─ return

  (on_fill_update 호출 안 됨 — "[매도체결]" 로그/텔레그램 없음)
```

### 1.3 동등성 위반 5가지

| # | 위반 내용 | 관련 원칙 | 코드 위치 |
|---|-----------|----------|-----------|
| **V1** | `fake_send_order`가 주문 접수와 체결을 동시 처리 | 원칙 18 | `dry_run.py:117-126` |
| **V2** | `fake_send_order`가 항상 성공만 반환 — CircuitBreaker 실패 경로 미검증 | 원칙 18, 16 | `dry_run.py:134` |
| **V3** | `_dryrun_post_sell_broadcast`가 잔고 기반으로 `_recent_sells` 해제 (폴백) | 원칙 20 | `trading.py:685-690` |
| **V4** | `on_fill_update` 테스트모드 분기가 `pass` — 체결 확인 로그/텔레그램/`has_open_buy` 해제 안 됨 | 원칙 18 | `trading.py:417-421` |
| **V5** | `_on_fill_after_ws`가 테스트모드에서 호출 안 됨 — 계좌 갱신/매도조건검사 누락 | 원칙 18 | (호출부 없음) |

### 1.4 추가 발견: 사전 존재 버그

- **B1**: `state.refresh_account_snapshot_meta`와 `state.update_account_memory`가 `engine_state.py:40-41`에서 `None`으로 초기화된 후 **영원히 할당되지 않음** (전체 backend 디렉토리 검색 확인)
- **B2**: `_on_fill_after_ws()` (`engine_account.py:437-441`)가 이 `None` 값을 `run_after_order_fill_ws()`에 전달 → `None()` 호출 시도 → `TypeError` 발생
- **B3**: 실전 모드 WS "00" 처리 시 `_handle_real_00` → `_on_fill_after_ws` 호출 → 예외 발생 → `engine_ws_dispatch.py:365`의 `except`에서 silent catch → **실전 모드에서도 체결 후 계좌 갱신/매도검사가 동작하지 않음**

---

## 2. 수정 계획 (8단계)

### Step 1: `fake_send_order`에서 체결 로직 제거

**파일**: `backend/app/services/dry_run.py:104-146`

**수정 내용**:
- `asyncio.sleep(FAKE_FILL_DELAY)` 제거 (주문 접수는 즉시 반환)
- `_apply_buy`/`_apply_sell` 호출 제거
- 주문 접수 응답만 반환 (order_no 포함, fill_price는 주문 가격 그대로)
- `fill_price` 계산은 유지하되, 체결이 아닌 주문 가격으로 사용

**수정 후**:
```python
async def fake_send_order(
    settings, access_token, order_type, code, qty, price=0, trde_tp="3",
) -> dict:
    """키움 send_order()와 동일한 반환 구조. 주문 접수만 (체결은 fake_fill_event에서)."""
    order_no = _next_fake_order_no()
    fill_price = price if price > 0 else _estimate_market_price(code)
    side = order_type.upper()
    logger.info(
        "[테스트모드] %s 주문 접수 %s %d주 @%s ord_no=%s",
        side, code, qty, f"{fill_price:,}" if fill_price else "시장가", order_no,
    )
    return {
        "success": True,
        "msg": "[테스트모드] 가상 주문 접수 완료",
        "data": {
            "rt_cd": "0",
            "msg1": "[테스트모드] 가상 주문 접수 완료",
            "output": {
                "ord_no": order_no,
                "stk_cd": str(code),
                "ord_qty": str(qty),
                "ord_uv": str(fill_price),
            },
        },
    }
```

**영향 범위**: `fake_send_order` 호출부는 `trading.py`의 `execute_buy`/`execute_sell` 2곳만 — 반환 구조 동일하므로 호출부 코드 변경 불필요

---

### Step 2: `fake_fill_event` 함수 추가

**파일**: `backend/app/services/dry_run.py` (신규 함수, `fake_send_order` 아래에 추가)

**목적**: 실전 WS "00" 이벤트를 시뮬레이션 — `_handle_real_00`과 동일한 downstream 호출 체인 실행

**구현**:
```python
async def fake_fill_event(
    order_type: str,   # "BUY" | "SELL"
    code: str,
    qty: int,
    price: int,
    stk_nm: str = "",
) -> None:
    """
    테스트모드 가상 체결 이벤트 — 실전 WS "00" 이벤트와 동일한 downstream 호출 체인.
    1. _apply_buy/_apply_sell (포지션 + Settlement Engine)
    2. on_fill_update (has_open_buy 해제, _recent_sells 해제, 로그/텔레그램)
    3. _on_fill_after_ws (계좌 갱신, 매도 조건 검사)
    """
    from backend.app.services.engine_state import state
    from backend.app.services import engine_account

    await asyncio.sleep(FAKE_FILL_DELAY)

    side = order_type.upper()
    fill_price = price if price > 0 else _estimate_market_price(code)

    # 1. 가상 체결 (포지션 + Settlement Engine)
    if side == "BUY":
        await _apply_buy(code, qty, fill_price)
        if stk_nm:
            await set_stock_name(code, stk_nm)
    elif side == "SELL":
        await _apply_sell(code, qty, fill_price)

    logger.info(
        "[테스트모드] 가상 체결 완료 %s %s %d주 @%s",
        side, code, qty, f"{fill_price:,}" if fill_price else "시장가",
    )

    # 2. on_fill_update (실전 _handle_real_00과 동일)
    #    side: "1"=매수, "2"=매도, unex=0 (전량 체결)
    ws_side = "1" if side == "BUY" else "2"
    if state.auto_trade:
        await state.auto_trade.on_fill_update(code, ws_side, 0, state.access_token)

    # 3. _on_fill_after_ws (실전 _handle_real_00과 동일)
    await engine_account._on_fill_after_ws()
```

**영향 범위**: 신규 함수 — 기존 코드 영향 없음

---

### Step 3: `execute_buy` 수정 — `_dryrun_post_buy_broadcast` 제거, `fake_fill_event` 예약

**파일**: `backend/app/services/trading.py:363-365`

**수정 전**:
```python
        if is_test_mode(base_settings):
            await _dryrun_post_buy_broadcast(stk_cd, stk_nm)
```

**수정 후**:
```python
        if is_test_mode(base_settings):
            _dry_fill_price = int(order_price) if order_price > 0 else int(current_price)
            asyncio.create_task(
                dry_run.fake_fill_event("BUY", stk_cd, buy_qty, _dry_fill_price, stk_nm)
            )
```

**영향 범위**: `execute_buy` 내부만 변경. 저널/`_daily_buy_spent`/`_bought_today`/`trade_history` 기록은 주문 접수 후 실행되므로 실전과 동일

---

### Step 4: `execute_sell` 수정 — `_dryrun_post_sell_broadcast` 제거, `fake_fill_event` 예약

**파일**: `backend/app/services/trading.py:518-520`

**수정 전**:
```python
        if is_test_mode(base_settings):
            await _dryrun_post_sell_broadcast(stk_cd, stk_nm, base_settings)
```

**수정 후**:
```python
        if is_test_mode(base_settings):
            _dry_sell_price = int(order_price) if order_price > 0 else int(cur_price)
            asyncio.create_task(
                dry_run.fake_fill_event("SELL", stk_cd, qty, _dry_sell_price, stk_nm)
            )
```

**영향 범위**: `execute_sell` 내부만 변경. `_recent_sells`는 `execute_sell`에서 `add` 후, `fake_fill_event` → `on_fill_update`에서 `discard` (실전과 동일)

---

### Step 5: `_dryrun_post_buy_broadcast` / `_dryrun_post_sell_broadcast` 함수 삭제

**파일**: `backend/app/services/trading.py:661-696`

**수정 내용**: 두 함수와 관련 상수(`_DRYRUN_BUY_BROADCAST_DELAY`) 삭제

**영향 범위**: 호출부가 Step 3, 4에서 이미 제거됨 — 잔여 호출 없음 (검색으로 확인 완료)

---

### Step 6: `on_fill_update` 테스트모드 분기 제거

**파일**: `backend/app/services/trading.py:417-421`

**수정 전**:
```python
        # 테스트모드: WS 체결 콜백 수신 시 dry_run 잔고 현재가 동기화
        if is_test_mode(self.get_settings_fn()):
            cur = await dry_run.get_position(nk)
            if cur:
                pass
```

**수정 후**: (삭제 — `on_fill_update` 본체만 남김)

**영향 범위**: `on_fill_update`가 테스트모드에서도 정상적으로 `has_open_buy` 해제, `_recent_sells.discard`, 로그/텔레그램 수행

---

### Step 7: `_on_fill_after_ws` 사전 버그 수정

**파일**: `backend/app/services/engine_account.py:423-442`

**문제**: `state.refresh_account_snapshot_meta`와 `state.update_account_memory`가 항상 `None` → `run_after_order_fill_ws`에서 `None()` 호출 → `TypeError`

**수정 전**:
```python
async def _on_fill_after_ws() -> None:
    from backend.app.services.auto_trading_effective import auto_sell_effective
    from backend.app.services.engine_ws_fill_followup import run_after_order_fill_ws
    from backend.app.services import dry_run

    async def _sell_if_applicable() -> None:
        if is_test_mode(state.integrated_system_settings_cache):
            pos = await dry_run.get_positions()
        else:
            pos = state.positions
        if pos and state.auto_trade and auto_sell_effective(state.integrated_system_settings_cache) and state.access_token:
            await state.auto_trade.check_sell_conditions(pos, state.integrated_system_settings_cache, state.access_token)

    run_after_order_fill_ws(
        0.0,
        state.refresh_account_snapshot_meta,
        lambda: state.update_account_memory(),
        is_dry_run=is_test_mode(state.integrated_system_settings_cache),
    )
```

**수정 후**:
```python
async def _on_fill_after_ws() -> None:
    from backend.app.services.auto_trading_effective import auto_sell_effective
    from backend.app.services import dry_run

    # 1. 계좌 스냅샷 갱신
    await _refresh_account_snapshot_meta()

    # 2. 매도 조건 검사
    if is_test_mode(state.integrated_system_settings_cache):
        pos = await dry_run.get_positions()
    else:
        pos = state.positions
    if pos and state.auto_trade and auto_sell_effective(state.integrated_system_settings_cache) and state.access_token:
        await state.auto_trade.check_sell_conditions(pos, state.integrated_system_settings_cache, state.access_token)
```

**영향 범위**:
- 실전 모드: WS "00" → `_on_fill_after_ws`가 이제 정상 동작 (사전 버그 B3 수정)
- 테스트 모드: `fake_fill_event` → `_on_fill_after_ws` 정상 동작
- `engine_ws_fill_followup.py`의 `run_after_order_fill_ws`는 더 이상 사용되지 않음 — 잔여 호출 검색 후 삭제 검토

---

### Step 8: 테스트 추가

**파일**: `backend/tests/test_dry_run_fill_event.py` (신규)

**테스트 케이스**:

1. **`test_fake_send_order_no_position_update`**: `fake_send_order` 호출 후 `_test_positions`에 포지션 생성되지 않음 확인
2. **`test_fake_fill_event_buy`**: `fake_fill_event("BUY", ...)` 호출 후 포지션 생성 + `settlement_engine.on_buy_fill` 반영 확인
3. **`test_fake_fill_event_sell`**: `fake_fill_event("SELL", ...)` 호출 후 포지션 삭제 + `settlement_engine.on_sell_fill` 반영 확인
4. **`test_on_fill_update_called_in_test_mode`**: `fake_fill_event` → `on_fill_update` 호출 확인 (`has_open_buy` 해제, `_recent_sells.discard`)
5. **`test_no_fallback_in_sell_broadcast`**: `_dryrun_post_sell_broadcast` 함수가 더 이상 존재하지 않음 확인 (검색 기반)
6. **`test_on_fill_after_ws_works_in_test_mode`**: `_on_fill_after_ws` 호출 시 `TypeError` 없이 정상 실행 확인

---

## 3. 수정 후 흐름도 (테스트 모드)

```
execute_buy()
  ├─ has_open_buy = True
  ├─ fake_send_order() → {"success": True} (주문 접수만, 포지션 변경 없음)
  ├─ set_stock_name()
  ├─ 저널, _daily_buy_spent, _bought_today, trade_history 기록
  ├─ buy-limit-status 브로드캐스트
  ├─ asyncio.create_task(fake_fill_event("BUY", ...))
  └─ return True
       │
       │ (FAKE_FILL_DELAY 후 비동기 실행 — 실전 WS "00"과 동일)
       ▼
  fake_fill_event()
  ├─ _apply_buy() (포지션 생성 + settlement_engine.on_buy_fill)
  ├─ on_fill_update(side="1", unex=0)
  │   ├─ has_open_buy = False
  │   ├─ "[매수체결]" 로그 + 텔레그램
  │   └─ _buy_state 갱신
  └─ _on_fill_after_ws()
      ├─ _refresh_account_snapshot_meta() (계좌 스냅샷 갱신)
      └─ check_sell_conditions() (매도 조건 검사)
```

**실전 모드와 완전 동일한 구조** — 모드 분기는 `fake_send_order` vs `send_order` (돈 I/O 최소 지점)에만 존재

---

## 4. 검증 방법

### 4.1 정적 검증
- `grep_search`로 `_dryrun_post_buy_broadcast`, `_dryrun_post_sell_broadcast` 잔여 확인
- `grep_search`로 `run_after_order_fill_ws` 잔여 호출 확인
- `python -m py_compile`로 수정 파일 컴파일 확인

### 4.2 단위 테스트
```bash
cd /Users/sungjk0706/Desktop/SectorFlow
python -m pytest backend/tests/test_dry_run_fill_event.py --timeout=30 -v
```

### 4.3 기존 테스트 회귀 확인
```bash
python -m pytest backend/tests/ --timeout=30 -v
```

### 4.4 런타임 검증 (원칙 19)
- `SectorFlow.command`로 앱 기동
- 테스트모드에서 자동매수 발생 시 로그 확인:
  - `[테스트모드] BUY 주문 접수` → `[테스트모드] 가상 체결 완료` → `[매수체결]` 순서 확인
  - `has_open_buy`가 `False`로 해제되는지 확인 (동일 종목 재매수 차단 후 해제)
- 테스트모드에서 자동매도 발생 시 로그 확인:
  - `[매도체결]` 로그 + 텔레그램 발송 확인
  - `_recent_sells`가 `on_fill_update`에서 해제되는지 확인 (잔고 기반 폴백 없음)

### 4.5 실전 모드 회귀 확인 (사전 버그 B3 수정)
- 실전모드에서 WS "00" 이벤트 수신 시 `_on_fill_after_ws` 정상 실행 확인
- 계좌 스냅샷 갱신 + 매도 조건 검사 정상 동작 확인

---

## 5. 위험 및 주의사항

- **`asyncio.create_task` 예외 처리**: `fake_fill_event` 내부 예외가 silent되지 않도록 `add_done_callback`으로 예외 로깅 필요
- **`set_stock_name` 타이밍**: `fake_send_order` 후 즉시 호출 시 포지션이 아직 없음 → `set_stock_name`이 no-op → `fake_fill_event` 내부에서 `_apply_buy` 후 `set_stock_name` 호출 (Step 2 구현에 반영)
- **`_estimate_market_price`**: 주문 접수 시점(`fake_send_order`)과 체결 시점(`fake_fill_event`)에 각각 호출 — 시장가 주문 시 현재가가 변할 수 있으나, 테스트모드이므로 같은 값 사용 허용
- **`engine_ws_fill_followup.py`**: `run_after_order_fill_ws`가 더 이상 사용되지 않을 수 있음 — 잔여 호출 검색 후 삭제 여부 결정

---

## 6. 아키텍처 원칙 부합성

| 원칙 | 부합 여부 | 근거 |
|------|----------|------|
| **18. 테스트모드 동등성** | ✅ | 주문 접수와 체결 분리 → 실전과 동일한 2단계 구조 |
| **20. 폴백 금지** | ✅ | `_dryrun_post_sell_broadcast`의 잔고 기반 `_recent_sells` 해제 제거 |
| **15. 단일 주문 경로** | ✅ | 주문 경로는 `execute_buy`/`execute_sell` → `fake_send_order`/`send_order` 단일 |
| **16. 구현 = 살아있는 경로** | ✅ | `on_fill_update` 테스트모드 분기가 실제 실행 경로에 배선됨 |
| **10. 단일 소스 진리** | ✅ | `_recent_sells` 해제가 `on_fill_update` 단일 경로로 일원화 |
| **5. 직접 호출 체인** | ✅ | `fake_fill_event` → `on_fill_update` → `_on_fill_after_ws` 직접 호출 |

---

## 7. 작업 순서 요약

1. **Step 1**: `dry_run.py` — `fake_send_order`에서 `_apply_buy`/`_apply_sell` 호출 제거, `asyncio.sleep` 제거
2. **Step 2**: `dry_run.py` — `fake_fill_event` 신규 함수 추가
3. **Step 3**: `trading.py:363-365` — `_dryrun_post_buy_broadcast` → `asyncio.create_task(fake_fill_event(...))` 교체
4. **Step 4**: `trading.py:518-520` — `_dryrun_post_sell_broadcast` → `asyncio.create_task(fake_fill_event(...))` 교체
5. **Step 5**: `trading.py:661-696` — `_dryrun_post_buy_broadcast`, `_dryrun_post_sell_broadcast` 함수 삭제
6. **Step 6**: `trading.py:417-421` — `on_fill_update` 테스트모드 `pass` 분기 삭제
7. **Step 7**: `engine_account.py:423-442` — `_on_fill_after_ws`에서 `state.refresh_account_snapshot_meta`/`state.update_account_memory` (None) 대신 직접 함수 호출
8. **Step 8**: `backend/tests/test_dry_run_fill_event.py` — 테스트 6개 추가
