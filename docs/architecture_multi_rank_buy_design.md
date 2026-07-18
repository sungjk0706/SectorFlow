# 설계서: 차순위 매수 시도 알고리즘 (Multi-Rank Buy)

> **상태**: 설계 완료 · 구현 승인 대기
> **작성일**: 2026-07-18
> **다단계 작업**: 2세션 구성 (1세션: `trading.py` 반환값 변경 / 2세션: `buy_order_executor.py` 루프 + 테스트 + 런타임 검증)
> **관련 원칙**: P10(SSOT) · P15(단일 주문 경로) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 1. 배경 및 목적

### 1-1. 문제 상황
- 현재 `buy_order_executor.evaluate_buy_candidates()`는 **매수 후보 테이블 1순위 종목 1종목만 시도 후 무조건 루프 종료** (`buy_order_executor.py:189` `break`).
- `break`가 `try/except` 바깥에 있어 **성공·실패·예외 모두 1회만 시도**.
- 사용자 시나리오: "주문가능 금액 500만원일 때 1순위 종목 300만원 매수 성공 → 잔액 200만원 남음 → 2순위 종목 매수 시도 안 함" → 잔액 비효율적 방치.
- 1순위 종목이 등락률 가드·재매수 차단 등 **종목별 사유**로 차단된 경우에도 차순위 시도 없이 종료 → 잔액이 충분해도 매수 기회 상실.

### 1-2. 목적
- **1순위 매수 성공 후 잔액 잔존 시 차순위 매수 시도** (잔액 효율적 활용)
- **1순위 종목별 차단 시 차순위 매수 시도** (매수 기회 확대)
- **1순위 전체 차단 시 루프 종료** (무의미한 차순위 시도 방지)
- **P15 단일 주문 경로 유지**: `execute_buy()` 단일 경로는 그대로, 변경은 `buy_order_executor` 루프 제어만
- **P21 사용자 투명성**: 매수 시도 순위·사유 로그 명시

### 1-3. 비목적 (본 설계에서 다루지 않음)
- 매도 로직 변경 없음
- 매수 후보 선정 알고리즘(`buy_filter.py`) 변경 없음
- 매수 후보 테이블 UI 표시 변경 없음 (rank 순서 그대로)
- 전역 주문 간격 게이트 정책 변경 없음 (같은 호출 내 연속 시도 허용만 추가, 게이트 자체는 유지)

---

## 2. 현재 동작 요약 (사전조사 결과 기반)

### 2-1. 호출 체인
```
engine_sector_confirm.py (buy_targets 변경 감지)
  → buy_order_executor.evaluate_buy_candidates()
    → state.auto_trade.execute_buy()
      → trading._execute_buy_locked()  [글로벌 매수 락 내부]
```

### 2-2. 핵심 파일
| 파일 | 역할 |
|---|---|
| `backend/app/services/buy_order_executor.py` | 매수 후보 평가·선택 루프 (주 수정 대상) |
| `backend/app/services/trading.py:94-417` | `execute_buy()` / `_execute_buy_locked()` 단일 주문 경로 |
| `backend/app/domain/buy_filter.py` | `BuyTarget(rank, sector_rank, stock)` 생성, `buy_targets`는 rank 오름차순 정렬 |
| `backend/app/services/order_interval.py` | `check_order_interval` / `mark_order_executed` (전역 주문 간격 게이트) |
| `backend/app/services/risk_manager.py:90` | `get_withdrawable_deposit()` (주문가능 금액) |

### 2-3. 현재 루프 동작 (`buy_order_executor.py:154-190`)
```python
for bt in ss.buy_targets:        # rank 오름차순 순회
    if not guard_pass: continue
    if after_hours and not nxt: continue
    if code not in _buyable_codes: continue
    execute_buy(code, price, ...)
    if success:
        invalidate_buy_snapshot()
        mark_order_executed("buy")
        _holding_cnt += 1
        if max_limit_reached: break
        if daily_limit_reached: break
    except: log warning
    break   # ← 핵심: 1순위 1종목 시도 후 무조건 루프 종료
```
주석 `# 1순위 종목 1종목만 시도 후 종료` 명시. `break`가 `try/except` 밖에 있어 성공·실패·예외 모두 1회만 시도.

### 2-4. `_execute_buy_locked` 실패 지점 (21개 `return False`)
| 구분 | 라인 | 사유 |
|---|---|---|
| 전체 차단 | 119, 126, 134, 183, 191-192, 204, 215 | 일일 상태 로드 실패, 실시간 지연, 자동매매 OFF, 최대 보유수, buy_amt<=0, 일일 매수 한도 |
| 종목별 차단 | 139, 148, 155, 165, 168, 223, 247, 260, 264, 344 | 체결 불가 시간대, 재매수, 미체결, 연속신호, 현재가≤0, 등락률, 체결강도, 주문 전송 실패 |
| 조건부 | 273, 287, 307 | buy_qty≤0(잔액/단가에 따라), RiskManager(서킷/손실/잔고/단일비중), 테스트 예수금 검증 실패 |

> **보정**: 사전조사에서 22개로 보고했으나, 라인 711 `_is_order_time_blocked` 헬퍼의 `return False`는 "토글 OFF → 차단 없음" 의미라 매수 실패 원인 아님. 실제 매수 차단 지점은 21개.
> **보정**: 사전조사에서 `buy_amt <= 0` (라인 191-192) 항목 누락 → 본 설계서에 포함.
> **`287 RiskManager`는 혼합**: 서킷브레이커·일일 손실 한도·예수금 부족은 전체 차단, 단일 종목 비중 초과는 종목별 차단.

---

## 3. 확정된 설계 결정 (사용자 결정 4항목)

### 3-1. 1순위 실패 시 차순위 시도 여부
**결정**: 종목별 차단 사유만 차순위 시도, 전체 차단 사유는 루프 종료.

**이유**:
- 전체 차단(시간대·자동매매 OFF·최대 보유수·일일 한도·서킷브레이커·일일 손실·잔액 0)은 차순위 시도해도 동일 사유로 차단되므로 무의미.
- 종목별 차단(재매수·미체결·연속신호·등락률·체결강도·단일 비중·단가 초과)은 차순위 종목에서는 통과할 수 있음.

### 3-2. 전역 주문 간격 게이트 (`buy_interval_sec`)
**결정**: 같은 `evaluate_buy_candidates` 호출 내 차순위 연속 시도는 간격 게이트 재적용 안 함.

**이유**:
- 간격 게이트는 "사용자가 설정한 N초 간격으로 매수 시도"를 위한 것. 한 번의 이벤트 기회 창 내에서 잔액을 분할 매수하는 것은 사용자 의도(잔액 활용)에 부합.
- `mark_order_executed("buy")`는 매 매수 성공 시마다 호출 → 다음 `evaluate_buy_candidates` 진입 시 간격 게이트가 마지막 매수 시각부터 적용.
- 즉, "같은 기회 창 내에서는 잔액 한도까지 연속 매수, 다음 기회 창은 간격 게이트 적용" — 자연스러운 정책.

### 3-3. 몇 순위까지 시도
**결정**: `buy_targets` 전체 순회, 단 잔액 0·최대 보유수·일일 한도 도달 시 즉시 중단.

**이유**:
- 상위 N개 제한은 임의 기준이 되어 P24 단순성 위반.
- 잔액/한도 도달 시 자동 중단되므로 무한 시도 아님.
- `buy_targets`는 이미 `max_sectors` 상위 업종 내 종목으로 한정되어 있어 과도한 순회 아님.

### 3-4. 세션 분할
**결정**: 2세션 구성.
- **1세션**: `trading.py` 사유코드 상수 정의 + `execute_buy`/`_execute_buy_locked` 반환값 `tuple[bool, str]` 변경 + `test_trading.py` 9곳 치환 + 신규 사유코드 검증 테스트.
- **2세션**: `buy_order_executor.py` 루프 제어 변경 + `_refresh_buyable_prices` 헬퍼 + `test_buy_order_executor.py` 치환 + 차순위 시도 신규 테스트 + 런타임 기동 검증 + `HANDOVER.md` 갱신.

**이유**:
- 1세션은 반환값 변경만 — `buy_order_executor` 루프는 임시 호환 코드(`if _ordered:`가 tuple 언패 없이도 동작)로 2세션까지 유지.
- 2세션은 루프 제어 + 테스트 + 런타임 검증 — 한 세션에 집중.
- 각 세션 종료 시 검증 + 커밋 + `HANDOVER.md` 갱신 (규칙 0-1).

---

## 4. 사유코드 체계 (P23 일관성)

### 4-1. 사유코드 상수 정의 (`trading.py` 모듈 상단)

```python
# ── 매수 실패 사유코드 (P23 일관성 — buy_order_executor 소비) ──
# 빈 문자열 = 성공
BUY_OK = ""

# 전체 차단 사유 (차순위 시도 무의미 → 루프 종료)
BUY_REJECT_DAILY_STATE = "daily_state"           # 일일 매수 상태 로드 실패
BUY_REJECT_REALTIME_LATENCY = "realtime_latency" # 실시간 지연 200ms 초과
BUY_REJECT_AUTO_BUY_OFF = "auto_buy_off"         # 자동매매 비활성화
BUY_REJECT_MAX_HOLDING = "max_holding"           # 최대 보유 종목 수 초과
BUY_REJECT_BUY_AMT_ZERO = "buy_amt_zero"         # 종목당 한도 설정값 0
BUY_REJECT_DAILY_LIMIT = "daily_limit"           # 일일 매수 한도 초과
BUY_REJECT_RISK_CIRCUIT = "risk_circuit"         # 서킷브레이커 차단
BUY_REJECT_RISK_LOSS = "risk_loss"               # 일일 손실 한도 초과
BUY_REJECT_RISK_CASH = "risk_cash"               # 예수금 부족 (잔액 0)
BUY_REJECT_TEST_CASH = "test_cash"               # 테스트 예수금 검증 실패
BUY_REJECT_ORDER_FAIL = "order_fail"             # 주문 전송 실패

# 종목별 차단 사유 (차순위 시도 유효 → continue)
BUY_REJECT_TIME_BLOCKED = "time_blocked"         # 체결 불가 시간대 (nxt 여부)
BUY_REJECT_REBUY = "rebuy"                       # 재매수 차단
BUY_REJECT_OPEN_ORDER = "open_order"             # 미체결 주문 존재
BUY_REJECT_SIGNAL_INTERVAL = "signal_interval"   # 30초 연속신호 차단
BUY_REJECT_PRICE_ZERO = "price_zero"             # 현재가 ≤ 0
BUY_REJECT_RISE_GUARD = "rise_guard"             # 등락률 상승 가드
BUY_REJECT_FALL_GUARD = "fall_guard"             # 등락률 하락 가드
BUY_REJECT_STRENGTH_GUARD = "strength_guard"     # 체결강도 가드
BUY_REJECT_SYMBOL_LIMIT = "symbol_limit"         # 종목당 한도 초과
BUY_REJECT_RISK_SINGLE = "risk_single"           # 단일 종목 비중 초과

# 조건부 사유 (buy_order_executor에서 잔액 재조회로 전체/종목별 판별)
BUY_REJECT_QTY_ZERO = "qty_zero"                 # buy_qty ≤ 0 (잔액 0이면 전체, 단가 비싸면 종목별)

# 전체 차단 사유 집합 (frozenset — P10 SSOT, 사유 분류의 단일 진실 소스)
BUY_GLOBAL_REJECT_REASONS: frozenset[str] = frozenset({
    BUY_REJECT_DAILY_STATE,
    BUY_REJECT_REALTIME_LATENCY,
    BUY_REJECT_AUTO_BUY_OFF,
    BUY_REJECT_MAX_HOLDING,
    BUY_REJECT_BUY_AMT_ZERO,
    BUY_REJECT_DAILY_LIMIT,
    BUY_REJECT_RISK_CIRCUIT,
    BUY_REJECT_RISK_LOSS,
    BUY_REJECT_RISK_CASH,
    BUY_REJECT_TEST_CASH,
    BUY_REJECT_ORDER_FAIL,
})
```

### 4-2. 사유코드 할당 매핑 (`_execute_buy_locked` 21개 `return False`)

| 라인 | 현재 로그 | 사유코드 | 분류 |
|---|---|---|---|
| 119 | 일일 매수 상태 로드 실패 | `BUY_REJECT_DAILY_STATE` | 전체 |
| 126 | 실시간 지연 200ms 초과 | `BUY_REJECT_REALTIME_LATENCY` | 전체 |
| 134 | 자동매매 비활성화 | `BUY_REJECT_AUTO_BUY_OFF` | 전체 |
| 139 | 체결 불가 시간대 | `BUY_REJECT_TIME_BLOCKED` | 종목별 |
| 148 | 재매수 차단 (today) | `BUY_REJECT_REBUY` | 종목별 |
| 155 | 재매수 차단 (N시간) | `BUY_REJECT_REBUY` | 종목별 |
| 165 | 미체결 주문 존재 | `BUY_REJECT_OPEN_ORDER` | 종목별 |
| 168 | 30초 연속신호 차단 | `BUY_REJECT_SIGNAL_INTERVAL` | 종목별 |
| 183 | 최대 보유 종목 수 초과 | `BUY_REJECT_MAX_HOLDING` | 전체 |
| 192 | buy_amt ≤ 0 | `BUY_REJECT_BUY_AMT_ZERO` | 전체 |
| 198 | 종목당 한도 초과 | `BUY_REJECT_SYMBOL_LIMIT` | 종목별 |
| 204 | 일일 매수 한도 (buy_amt_on=True) | `BUY_REJECT_DAILY_LIMIT` | 전체 |
| 215 | 일일 매수 한도 (buy_amt_on=False) | `BUY_REJECT_DAILY_LIMIT` | 전체 |
| 223 | 현재가 ≤ 0 | `BUY_REJECT_PRICE_ZERO` | 종목별 |
| 247 | 등락률 가드 (상승/하락) | `BUY_REJECT_RISE_GUARD` / `BUY_REJECT_FALL_GUARD` | 종목별 |
| 260 | 체결강도 값 해석 실패 | `BUY_REJECT_STRENGTH_GUARD` | 종목별 |
| 264 | 체결강도 미달 | `BUY_REJECT_STRENGTH_GUARD` | 종목별 |
| 273 | buy_qty ≤ 0 | `BUY_REJECT_QTY_ZERO` | 조건부 |
| 287 | RiskManager 거부 | 사유코드 분기 (아래 4-3) | 혼합 |
| 307 | 테스트 예수금 검증 실패 | `BUY_REJECT_TEST_CASH` | 전체 |
| 344 | 주문 전송 실패 | `BUY_REJECT_ORDER_FAIL` | 전체 |

### 4-3. RiskManager 사유코드 분기 (`trading.py:285-287`)

`risk_mgr.check_buy_order_allowed()`가 반환하는 `_risk_reason` 문자열을 기반으로 사유코드 매핑. 현재 `_risk_reason` 값:
- `"서킷브레이커 차단 상태 (...)"` → `BUY_REJECT_RISK_CIRCUIT` (전체)
- `"일일 손실 한도 초과"` → `BUY_REJECT_RISK_LOSS` (전체)
- `"예수금 부족"` → `BUY_REJECT_RISK_CASH` (전체)
- `"단일 종목 비중 한도 초과 (...)"` → `BUY_REJECT_RISK_SINGLE` (종목별)

매핑 헬퍼 함수 추가 (P23 일관성 — 문자열 매칭 중앙화):
```python
def _map_risk_reason_to_code(risk_reason: str) -> str:
    """RiskManager 거부 사유 문자열 → 사유코드 매핑 (P23 일관성)."""
    if "서킷브레이커" in risk_reason:
        return BUY_REJECT_RISK_CIRCUIT
    if "일일 손실 한도" in risk_reason:
        return BUY_REJECT_RISK_LOSS
    if "예수금 부족" in risk_reason:
        return BUY_REJECT_RISK_CASH
    if "단일 종목 비중" in risk_reason:
        return BUY_REJECT_RISK_SINGLE
    # 알 수 없는 사유는 안전하게 전체 차단 분류 (P20 폴백 금지 — 추정 아님, 보수적 차단)
    logger.warning("[매매] RiskManager 알 수 없는 사유 — 전체 차단 분류: %s", risk_reason)
    return BUY_REJECT_RISK_CIRCUIT
```

> **P20 주의**: 알 수 없는 사유를 "종목별 차단"으로 분류하면 차순위 시도했다가 또 같은 사유로 차단 반복. 보수적으로 전체 차단 분류하여 루프 종료하는 것이 안전.

### 4-4. `BUY_REJECT_QTY_ZERO` 조건부 판별 (`buy_order_executor` 측)

`buy_qty ≤ 0`은 두 가지 의미:
1. **잔액 0** (`get_withdrawable_deposit() <= 0`): 전체 차단 — 차순위도 불가
2. **단가 비싸서 못 삼** (`_est_buy_price > _max_available`): 종목별 차단 — 차순위 저단가 종목으로 시도 유효

`buy_order_executor`에서 `BUY_REJECT_QTY_ZERO` 수신 시 `get_withdrawable_deposit()` 재조회로 판별:
```python
if _reason == BUY_REJECT_QTY_ZERO:
    if get_risk_manager().get_withdrawable_deposit() <= 0:
        _cash_insufficient = True
        break  # 잔액 0 → 전체 차단
    else:
        continue  # 단가 초과 → 종목별 차단, 차순위 시도
```

---

## 5. 백엔드 설계

### 5-1. `trading.py` 반환값 변경 (1세션 주 수정)

#### 5-1-1. `execute_buy` 시그니처
```python
# Before
async def execute_buy(self, stk_cd: str, current_price: float,
                access_token: str, reason: str = "") -> bool:

# After
async def execute_buy(self, stk_cd: str, current_price: float,
                access_token: str, reason: str = "") -> tuple[bool, str]:
```

#### 5-1-2. `_execute_buy_locked` 시그니처
```python
# Before
async def _execute_buy_locked(self, stk_cd: str, current_price: float,
                access_token: str, reason: str = "") -> bool:

# After
async def _execute_buy_locked(self, stk_cd: str, current_price: float,
                access_token: str, reason: str = "") -> tuple[bool, str]:
```

#### 5-1-3. `execute_buy` 본문 (래퍼 — 변경 최소)
```python
async def execute_buy(self, stk_cd: str, current_price: float,
                access_token: str, reason: str = "") -> tuple[bool, str]:
    """
    매수 주문 실행 (글로벌 매수 락으로 순차 처리).
    reason: 매수 사유 (체결 이력 기록용).
    반환값: (True, "")=주문 전송 성공, (False, 사유코드)=가드에 의해 차단/실패
    """
    if self._buy_lock is None:
        self._buy_lock = asyncio.Lock()
    async with self._buy_lock:
        return await self._execute_buy_locked(stk_cd, current_price, access_token, reason)
```

#### 5-1-4. `_execute_buy_locked` 21개 `return False` → `return False, BUY_REJECT_XXX`

각 지점에 맞는 사유코드 할당 (4-2 매핑표 참조). 예:
```python
# 라인 119
if self._daily_buy_spent is None:
    logger.critical("[매매] [매수차단] %s 일일 매수 상태 로드 실패 — 매수 불가", stk_cd)
    return False, BUY_REJECT_DAILY_STATE

# 라인 287 (RiskManager)
if not _allowed:
    _reason_code = _map_risk_reason_to_code(_risk_reason)
    logger.info("[매매] [리스크차단] %s 매수 차단 — %s (사유코드=%s)", stk_cd, _risk_reason, _reason_code)
    return False, _reason_code
```

#### 5-1-5. 최종 성공 반환
```python
# 라인 417
return True  # Before

# After
return True, BUY_OK
```

### 5-2. `buy_order_executor.py` 루프 제어 변경 (2세션 주 수정)

#### 5-2-1. 임시 호환 코드 (1세션 완료 후 2세션까지)

1세션에서 `execute_buy`가 `tuple[bool, str]`을 반환하면, 2세션에서 루프를 변경하기 전까지 기존 `if _ordered:` 분기가 동작하지 않음 (tuple은 truthy). 임시 호환 코드:
```python
_ordered_result = await state.auto_trade.execute_buy(...)
_ordered = _ordered_result[0] if isinstance(_ordered_result, tuple) else _ordered_result
if _ordered:
    ...
```
> **P24 주의**: 임시 호환 코드는 2세션에서 제거. 1세션 커밋 메시지에 "임시 호환 — 2세션에서 제거 예정" 명시.

#### 5-2-2. 최종 루프 구조 (2세션)

```python
# ── 매수 후보 순회 — 차순위 시도 알고리즘 ──────────────────────
# 1순위 성공 후 잔액/한도 잔존 시 차순위 continue
# 1순위 종목별 차단 시 차순위 continue
# 1순위 전체 차단 시 break
# 잔액 0·최대 보유수·일일 한도 도달 시 break
from backend.app.services.trading import (
    BUY_OK, BUY_REJECT_QTY_ZERO, BUY_GLOBAL_REJECT_REASONS,
)
from backend.app.services.risk_manager import get_risk_manager as _get_rm

for bt in ss.buy_targets:
    s = bt.stock
    if not s.guard_pass:
        continue
    if _after_hours and not is_nxt_enabled(s.code):
        continue
    if s.code not in _buyable_codes:
        continue

    logger.info("[매매] 매수 시도: %s(%s) 순위=%d 업종=%s",
                s.name, s.code, bt.rank, s.sector)
    try:
        _price = int(s.cur_price or 0)
        if _price <= 0:
            break  # 현재가 0은 전역 이상 → 루프 종료
        _ordered, _reason = await state.auto_trade.execute_buy(
            s.code, float(_price), state.access_token or "",
            reason=f"업종자동매수 업종={s.sector} 순위={bt.rank}",
        )
        if _ordered:
            logger.info("[매매] 매수 주문 전송: %s(%s) 순위=%d", s.name, s.code, bt.rank)
            invalidate_buy_snapshot()
            from backend.app.services.order_interval import mark_order_executed
            mark_order_executed("buy")
            _holding_cnt += 1
            # 최대 보유수 도달 시 루프 종료
            if _max_limit_on and _holding_cnt >= _max_limit:
                logger.info("[매매] 최대 보유 종목 수 도달 — 차순위 시도 중단 (보유=%d)", _holding_cnt)
                break
            # 잔액 재조회 — 0이면 _cash_insufficient 설정 후 루프 종료
            _available = _get_rm().get_withdrawable_deposit()
            if _available <= 0:
                _cash_insufficient = True
                logger.info("[매매] 주문가능 금액 0원 — 차순위 시도 중단")
                break
            # 일일 한도 도달 시 루프 종료
            await state.auto_trade._ensure_daily_buy_counter()
            if state.auto_trade._daily_buy_spent is not None and _max_daily > 0 \
                    and state.auto_trade._daily_buy_spent >= _max_daily:
                logger.info("[매매] 일일 매수 한도 도달 — 차순위 시도 중단 (누적=%s원)",
                            f"{state.auto_trade._daily_buy_spent:,}")
                break
            # 차순위 시도를 위해 _buyable_codes 잔액/가격 부분 갱신
            _refresh_buyable_prices(ss, _available, _effective_buy_amt, _is_test)
            continue  # ← 차순위 시도
        else:
            # 실패 사유 분류
            if _reason == BUY_REJECT_QTY_ZERO:
                # 잔액 0이면 전체 차단, 단가 비싸면 종목별 차단
                if _get_rm().get_withdrawable_deposit() <= 0:
                    _cash_insufficient = True
                    logger.info("[매매] %s 잔액 0 — 차순위 시도 중단 (사유=%s)", s.code, _reason)
                    break
                else:
                    logger.info("[매매] %s 단가 초과 — 차순위 시도 (사유=%s)", s.code, _reason)
                    continue
            if _reason in BUY_GLOBAL_REJECT_REASONS:
                logger.info("[매매] %s 전체 차단 사유 — 차순위 시도 중단 (사유=%s)", s.code, _reason)
                break
            # 종목별 차단 사유 → 차순위 시도
            logger.info("[매매] %s 종목별 차단 — 차순위 시도 (사유=%s)", s.code, _reason)
            continue
    except Exception as e:
        logger.warning("[매매] 매수 실행 오류 %s: %s — 차순위 시도 중단", s.code, e, exc_info=True)
        break  # 예외 시 안전 종료
```

#### 5-2-3. `_refresh_buyable_prices` 헬퍼 (신규 — P23 공통 자산)

매수 성공 후 잔액이 줄어들면 고가 종목이 `_buyable_codes`에서 빠져야 함 (P10 SSOT — `_buyable_codes`와 `execute_buy` 내부 잔액 판단 일치).

```python
def _refresh_buyable_prices(ss, available: int, effective_buy_amt: int | None, is_test: bool) -> set[str]:
    """매수 성공 후 잔액 갱신 시 _buyable_codes 재계산 (P10 SSOT).
    
    잔액이 줄어들면 고가 종목이 _buyable_codes에서 빠짐.
    execute_buy 내부(trading.py:267-273)와 동일 기준.
    """
    from backend.app.services import dry_run
    from backend.app.services.engine_symbol_utils import is_nxt_enabled
    from backend.app.services.daily_time_scheduler import is_krx_after_hours
    from backend.app.services.engine_state import state
    
    _after_hours = is_krx_after_hours()
    _rebuy_block_on = bool(state.integrated_system_settings_cache.get("rebuy_block_on", True))
    _new_codes: set[str] = set()
    for bt in ss.buy_targets:
        s = bt.stock
        if not s.guard_pass:
            continue
        if _after_hours and not is_nxt_enabled(s.code):
            continue
        if _rebuy_block_on and s.code in state.auto_trade._bought_today:
            continue
        _price = int(s.cur_price or 0)
        if _price <= 0:
            continue
        _est_price = dry_run.estimate_fill_price(_price, "BUY") if is_test else _price
        _max_for_code = min(effective_buy_amt, available) if effective_buy_amt is not None else available
        if _max_for_code < _est_price:
            continue
        _new_codes.add(s.code)
    return _new_codes
```

> **P24 단순성**: 이 헬퍼는 기존 `_buyable_codes` 구축 로직(120-137줄)과 중복. 2세션에서 기존 로직을 이 헬퍼로 통합하여 단일 진실 소스화 (P10 SSOT). 즉, 최초 `_buyable_codes` 구축도 `_refresh_buyable_prices()` 호출로 통일.

#### 5-2-4. `_cash_insufficient` 설정 시점

- **기존**: `evaluate_buy_candidates` 진입 시 `_available <= 0`이면 `_cash_insufficient = True` (98-99줄)
- **추가**: 루프 중 잔액 0 도달 시 `_cash_insufficient = True` (위 5-2-2 루프 내)
- **회복 경로 유지**: `settlement_engine.py:138` (매도 체결 시) + `engine_account.py:402` (실전 잔고 업데이트 시)에서 `_cash_insufficient=True`일 때 `invalidate_buy_snapshot()` + `evaluate_buy_candidates()` 재호출 — 기존 패턴 그대로 작동.

### 5-3. `invalidate_buy_snapshot()` 호출 시점

- **기존**: 1순위 매수 성공 시 1회 호출
- **변경**: 매 매수 성공 시마다 호출 (차순위 매수 시에도 스냅샷 무효화)
- **이유**: 스냅샷은 "동일 조건 시 재시도 스킵"을 위한 것. 매수 성공 시 잔액·보유수·일일한도가 변하므로 스냅샷이 무효화되어야 함. 차순위 매수 후에도 동일.

### 5-4. `mark_order_executed("buy")` 호출 시점

- **기존**: 1순위 매수 성공 시 1회 호출
- **변경**: 매 매수 성공 시마다 호출 (차순위 매수 시에도 간격 게이트 타이머 갱신)
- **이유**: 3-2 정책 — 같은 호출 내 연속 시도는 간격 게이트 재적용 안 함. 단, `mark_order_executed`는 매 성공 시마다 찍어서 다음 `evaluate_buy_candidates` 진입 시 간격 게이트가 마지막 매수 시각부터 적용되도록 함.

---

## 6. 프론트엔드 설계

**변경 없음.**

- 매수 후보 테이블 UI는 `buy_targets` rank 순서 그대로 표시 (기존과 동일).
- 매수 이력 화면도 기존과 동일 (`trade_history`에 종목별 기록).
- 사용자 체감 변화는 "잔액이 남을 때 1순위만 사고 끝나지 않고 2순위·3순위로 잔액을 더 쓴다"는 점 only.

---

## 7. 테스트 설계

### 7-1. `test_trading.py` 수정 (1세션 — 9곳 치환)

#### 7-1-1. 기존 테스트 패턴 치환
```python
# Before
result = await mgr.execute_buy("005930", 70000, "token")
assert result is False

# After
result, _reason = await mgr.execute_buy("005930", 70000, "token")
assert result is False
```

9곳: 라인 138-139, 148-149, 158-159, 191-192, 201-202, 211-212, 223-224, 235-236, 249-250.

#### 7-1-2. 신규 테스트 (사유코드 검증)
```python
@pytest.mark.asyncio
async def test_rebuy_block_returns_rebuy_reason(self):
    """재매수 차단 시 사유코드 BUY_REJECT_REBUY 반환."""
    mgr = _make_manager(_raw_settings())
    mgr._bought_today["005930"] = time.time()
    with patch("backend.app.services.engine_state.state") as mock_state:
        mock_state.realtime_latency_exceeded = False
        mock_state.integrated_system_settings_cache = _raw_settings()
        result, reason = await mgr.execute_buy("005930", 70000, "token")
    assert result is False
    assert reason == BUY_REJECT_REBUY

@pytest.mark.asyncio
async def test_max_holding_returns_max_holding_reason(self):
    """최대 보유수 초과 시 사유코드 BUY_REJECT_MAX_HOLDING 반환."""
    ...

# 전체 차단 사유별 테스트 (대표 3개):
# - test_auto_buy_off_returns_auto_buy_off_reason
# - test_daily_state_load_fail_returns_daily_state_reason
# - test_risk_circuit_returns_risk_circuit_reason

# 종목별 차단 사유별 테스트 (대표 3개):
# - test_rise_guard_returns_rise_guard_reason
# - test_strength_guard_returns_strength_guard_reason
# - test_open_order_returns_open_order_reason

# RiskManager 사유 매핑 테스트:
# - test_risk_reason_mapping_circuit
# - test_risk_reason_mapping_loss
# - test_risk_reason_mapping_cash
# - test_risk_reason_mapping_single
```

신규 테스트 약 10개 추가 예상.

### 7-2. `test_buy_order_executor.py` 수정 (2세션 — 치환 + 신규 10개)

#### 7-2-1. 기존 테스트 치환
```python
# Before
fresh_state.auto_trade.execute_buy = AsyncMock(return_value=True)

# After
fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
```

`return_value=True` 다수 + `return_value=False` 3곳(453, 569, 721) + `side_effect=Exception` 1곳(406, 유지).

`return_value=False` 3곳은 사유코드 명시:
- 라인 453 (`test_second_call_with_same_conditions_skipped`): `return_value=(False, BUY_REJECT_RISE_GUARD)` (종목별 차단 — 스냅샷 유지 검증)
- 라인 569 (`test_different_top_code_allows_re_evaluation` 유사): `return_value=(False, BUY_REJECT_RISE_GUARD)`
- 라인 721 (`test_snapshot_excludes_available_cash`): `return_value=(False, BUY_REJECT_RISE_GUARD)`

#### 7-2-2. 신규 테스트 (차순위 시도 검증 — 10개)

```python
# 1. 1순위 성공 + 잔액 남음 → 2순위 execute_buy 호출됨
async def test_second_rank_tried_after_first_success_with_remaining_cash(self, ...):
    # buy_targets = [A001, A002], 잔액 500만원, 1순위 300만원 성공 → 잔액 200만원
    # execute_buy가 2회 호출됨 (A001, A002)
    assert fresh_state.auto_trade.execute_buy.await_count == 2

# 2. 1순위 성공 + 잔액 0 도달 → 2순위 호출 안 됨 + _cash_insufficient=True
async def test_loop_breaks_on_cash_zero_after_first_success(self, ...):
    # 1순위 성공 후 get_withdrawable_deposit()가 0 반환
    assert fresh_state.auto_trade.execute_buy.await_count == 1
    assert buy_order_executor._cash_insufficient is True

# 3. 1순위 성공 + 최대 보유수 도달 → 2순위 호출 안 됨
async def test_loop_breaks_on_max_holding_after_first_success(self, ...):
    # max_stock_cnt=1, 1순위 성공 → _holding_cnt=1 >= max_limit → break
    assert fresh_state.auto_trade.execute_buy.await_count == 1

# 4. 1순위 성공 + 일일 한도 도달 → 2순위 호출 안 됨
async def test_loop_breaks_on_daily_limit_after_first_success(self, ...):
    # max_daily_total_buy_amt=300만원, 1순위 300만원 성공 → _daily_buy_spent >= max_daily → break
    assert fresh_state.auto_trade.execute_buy.await_count == 1

# 5. 1순위 종목별 차단(등락률) → 2순위 호출됨
async def test_second_rank_tried_after_first_symbol_block(self, ...):
    # 1순위 execute_buy → (False, BUY_REJECT_RISE_GUARD) → continue → 2순위 시도
    assert fresh_state.auto_trade.execute_buy.await_count == 2

# 6. 1순위 전체 차단(자동매매 OFF) → 2순위 호출 안 됨
async def test_loop_breaks_on_global_block(self, ...):
    # 1순위 execute_buy → (False, BUY_REJECT_AUTO_BUY_OFF) → break
    assert fresh_state.auto_trade.execute_buy.await_count == 1

# 7. 1순위 BUY_REJECT_QTY_ZERO + 잔액 0 → 2순위 호출 안 됨
async def test_qty_zero_with_cash_zero_breaks_loop(self, ...):
    # 1순위 execute_buy → (False, BUY_REJECT_QTY_ZERO), get_withdrawable_deposit()=0 → break
    assert fresh_state.auto_trade.execute_buy.await_count == 1
    assert buy_order_executor._cash_insufficient is True

# 8. 1순위 BUY_REJECT_QTY_ZERO + 잔액 남음(단가 초과) → 2순위 호출됨
async def test_qty_zero_with_remaining_cash_continues(self, ...):
    # 1순위 execute_buy → (False, BUY_REJECT_QTY_ZERO), get_withdrawable_deposit()=200만원 → continue
    assert fresh_state.auto_trade.execute_buy.await_count == 2

# 9. 1순위 예외 → 2순위 호출 안 됨 (안전 종료)
async def test_exception_breaks_loop(self, ...):
    # 1순위 execute_buy → Exception → break
    assert fresh_state.auto_trade.execute_buy.await_count == 1

# 10. 1순위 성공 + 2순위 성공 + 잔액 0 → 3순위 호출 안 됨
async def test_loop_breaks_after_two_successes_on_cash_zero(self, ...):
    # buy_targets = [A001, A002, A003], 1순위+2순위 성공 후 잔액 0 → 3순위 호출 안 됨
    assert fresh_state.auto_trade.execute_buy.await_count == 2
```

### 7-3. 기존 테스트 영향 분석

| 테스트 | 영향 | 대응 |
|---|---|---|
| `test_calls_execute_buy_for_first_target` (307) | `return_value=True` → `(True, "")` 치환 | 단순 치환 |
| `test_zero_price_breaks_loop` (386) | `return_value=True` → `(True, "")` 치환, 단 0원 가격으로 루프 진입 전 break | 단순 치환 |
| `test_execute_buy_exception_does_not_crash` (405) | `side_effect=Exception` 유지 | 변경 없음 |
| `test_only_first_target_called_when_after_hours_krx_only` (427) | `return_value=True` → `(True, "")` 치환, 단 after_hours+KRX 단독 시 _buyable_codes에서 제외되어 1순위 호출 안 됨 | 단순 치환 |
| `test_second_call_with_same_conditions_skipped` (451) | `return_value=False` → `(False, BUY_REJECT_RISE_GUARD)` 치환 | 단순 치환 |
| `test_successful_buy_invalidates_snapshot` (608) | `return_value=True` → `(True, "")` 치환 | 단순 치환 |

---

## 8. 세션 분할 상세 (2세션)

### 8-1. 1세션: `trading.py` 반환값 변경 + `test_trading.py` 갱신

#### 수정 파일
1. `backend/app/services/trading.py`
   - 사유코드 상수 21개 + `BUY_GLOBAL_REJECT_REASONS` frozenset + `_map_risk_reason_to_code()` 헬퍼 추가 (모듈 상단)
   - `execute_buy` 시그니처 `-> bool` → `-> tuple[bool, str]` + docstring 갱신
   - `_execute_buy_locked` 시그니처 동일 변경 + docstring 갱신
   - 21개 `return False` → `return False, BUY_REJECT_XXX` (4-2 매핑표 참조)
   - 최종 `return True` → `return True, BUY_OK`
2. `backend/app/services/buy_order_executor.py` (임시 호환 코드만 — 2세션에서 제거)
   - 라인 172-175 `_ordered = await ...` → tuple 언패 호환 코드
3. `backend/tests/test_trading.py`
   - 9곳 `result = await mgr.execute_buy(...)` → `result, _reason = await mgr.execute_buy(...)`
   - 신규 테스트 약 10개 (사유코드 검증)

#### 검증 (1세션)
- `python -m py_compile backend/app/services/trading.py backend/app/services/buy_order_executor.py`
- `ruff check backend/app/services/trading.py backend/app/services/buy_order_executor.py backend/tests/test_trading.py`
- `pytest backend/tests/test_trading.py` — 기존 9개 + 신규 약 10개 전체 통과
- `pytest backend/tests/test_buy_order_executor.py` — 기존 테스트 전체 통과 (임시 호환 코드로 인해)
- 런타임 기동: `python -W error::RuntimeWarning main.py` — RuntimeWarning 0건 + 매수 시도 로그 정상 (1순위만 시도 — 2세션에서 차순위 활성화)

#### 커밋 메시지 (1세션)
```
feat: 차순위 매수 시도 1세션 — execute_buy 반환값 tuple[bool, str] 변경 + 사유코드 체계

- trading.py: 사유코드 상수 21개 + BUY_GLOBAL_REJECT_REASONS frozenset + _map_risk_reason_to_code() 헬퍼
- execute_buy/_execute_buy_locked 반환값 bool → tuple[bool, str] (성공여부, 사유코드)
- 21개 return False → return False, BUY_REJECT_XXX (전체/종목별 분류)
- buy_order_executor.py: 임시 호환 코드 추가 (2세션에서 제거 예정)
- test_trading.py: 9곳 result 언패킹 치환 + 신규 사유코드 검증 테스트 10개

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

### 8-2. 2세션: `buy_order_executor.py` 루프 제어 + `test_buy_order_executor.py` + 런타임 검증

#### 수정 파일
1. `backend/app/services/buy_order_executor.py`
   - 임시 호환 코드 제거
   - 루프 제어 로직 변경 (5-2-2 최종 루프 구조)
   - `_refresh_buyable_prices()` 헬퍼 추가 (기존 `_buyable_codes` 구축 로직과 통합 — P10 SSOT)
   - `from backend.app.services.trading import BUY_OK, BUY_REJECT_QTY_ZERO, BUY_GLOBAL_REJECT_REASONS` import 추가
   - 매수 사유 문자열에 순위 추가: `reason=f"업종자동매수 업종={s.sector} 순위={bt.rank}"`
   - docstring 갱신 ("매수 후보 테이블 1순위 종목만 매수" → "매수 후보 순회 — 차순위 시도 알고리즘")
2. `backend/tests/test_buy_order_executor.py`
   - `return_value=True` → `return_value=(True, "")` 다수 치환
   - `return_value=False` 3곳 → `return_value=(False, BUY_REJECT_RISE_GUARD)` 치환
   - 신규 테스트 10개 (7-2-2 참조)

#### 검증 (2세션)
- `python -m py_compile backend/app/services/buy_order_executor.py`
- `ruff check backend/app/services/buy_order_executor.py backend/tests/test_buy_order_executor.py`
- `pytest backend/tests/test_buy_order_executor.py` — 기존 + 신규 10개 전체 통과
- `pytest backend/tests/test_trading.py` — 1세션 테스트 회귀 없음
- 전체 회귀: `pytest backend/tests/` — 기존 실패 1개(`test_rebuy_block_disabled`)는 본 수정 무관 확인 (규칙 4-1)
- 런타임 기동: `python -W error::RuntimeWarning main.py` — RuntimeWarning 0건 + 매수 시도 로그 정상 + 차순위 시도 로그 확인 (테스트모드에서 잔액 분할 매수 시나리오)
- `HANDOVER.md` 갱신 + 설계서 삭제 (규칙 11)

#### 커밋 메시지 (2세션)
```
feat: 차순위 매수 시도 2세션 — buy_order_executor 루프 제어 + 차순위 시도 알고리즘 완성

- buy_order_executor.py: 루프 제어 로직 변경 (사유코드 기반 continue/break 분기)
- _refresh_buyable_prices() 헬퍼 추가 (잔액 갱신 시 _buyable_codes 재계산, P10 SSOT)
- 1순위 성공 후 잔액/한도 잔존 시 차순위 continue
- 1순위 종목별 차단 시 차순위 continue, 전체 차단 시 break
- 잔액 0·최대 보유수·일일 한도 도달 시 break
- 매수 사유 문자열에 순위 추가 (P21 사용자 투명성)
- test_buy_order_executor.py: return_value tuple 치환 + 차순위 시도 신규 테스트 10개
- 임시 호환 코드 제거 (1세션)
- 설계서 삭제 (규칙 11)

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

---

## 9. 검증 항목 (체크리스트)

### 9-1. 1세션 검증
- [ ] `py_compile` 통과 (trading.py, buy_order_executor.py)
- [ ] `ruff check` 통과
- [ ] `pytest test_trading.py` 전체 통과 (기존 9 + 신규 약 10)
- [ ] `pytest test_buy_order_executor.py` 전체 통과 (임시 호환 코드로 인해)
- [ ] 런타임 기동 `python -W error::RuntimeWarning main.py` RuntimeWarning 0건
- [ ] 기동 로그에서 매수 시도 정상 (1순위만 시도 — 2세션에서 차순위 활성화)
- [ ] 잔존 프로세스 0건

### 9-2. 2세션 검증
- [ ] `py_compile` 통과 (buy_order_executor.py)
- [ ] `ruff check` 통과
- [ ] `pytest test_buy_order_executor.py` 전체 통과 (기존 + 신규 10)
- [ ] `pytest test_trading.py` 회귀 없음
- [ ] 전체 회귀 `pytest backend/tests/` — 기존 실패 1개(`test_rebuy_block_disabled`) 본 수정 무관 확인 (규칙 4-1)
- [ ] 런타임 기동 RuntimeWarning 0건
- [ ] 기동 로그에서 차순위 시도 정상 (테스트모드 잔액 분할 매수 시나리오)
- [ ] 잔존 프로세스 0건
- [ ] `HANDOVER.md` 갱신
- [ ] 설계서 삭제 (규칙 11)

---

## 10. 아키텍처 원칙 부합 검증

| 원칙 | 부합 여부 | 비고 |
|---|---|---|
| **P10 (SSOT)** | ✅ | 실패 사유 진실 소스는 `execute_buy` 내부 1곳. `buy_order_executor`는 사유코드만 소비. `BUY_GLOBAL_REJECT_REASONS` frozenset이 사유 분류의 단일 진실 소스. `_refresh_buyable_prices()` 헬퍼로 `_buyable_codes` 구축 로직 단일화. |
| **P15 (단일 주문 경로)** | ✅ | `execute_buy()` 단일 경로 유지. 반환값만 변경, 경로 분기 아님. `buy_order_executor`는 `execute_buy`를 호출만 함. |
| **P16 (살아있는 경로)** | ✅ | RiskManager/CircuitBreaker는 `execute_buy` 내부에서 계속 호출. 차순위 시도 시에도 동일. 서킷브레이커 OPEN 시 `execute_buy` 내부에서 자동매매 OFF 강제 → 차순위 시도 시 자동 차단. |
| **P20 (폴백 금지)** | ✅ | 옵션 A 채택으로 사유 기반 정확 분기. 추정/폴백 없음. `_map_risk_reason_to_code()` 알 수 없는 사유는 보수적 전체 차단 (폴백 아님). |
| **P21 (사용자 투명성)** | ✅ | 매수 시도 순위·사유 로그 명시 ("매수 시도: 삼성전자 순위=1", "종목별 차단 — 차순위 시도 (사유=rise_guard)"). UI는 기존 매수 후보 테이블이 rank 순서로 표시되므로 추가 UI 변경 불필요. 매수 사유 문자열에 순위 추가. |
| **P22 (데이터 정합성)** | ✅ | `reserve_test_buy_power` 원자적 차감은 `execute_buy` 내부 유지. 차순위 시도 시 각 종목 독립 처리. 매수 성공 시마다 `_daily_buy_spent`/`_symbol_daily_buy_spent` 갱신 — 차순위 시도 시 최신 값 반영. |
| **P23 (일관성)** | ✅ | 사유코드 상수 정의 + `BUY_GLOBAL_REJECT_REASONS` frozenset. 용어 사전 준수 ("매수 후보", "차순위"). `_map_risk_reason_to_code()` 헬퍼로 RiskManager 사유 매핑 중앙화. `_refresh_buyable_prices()` 헬퍼로 `_buyable_codes` 구축 로직 통일. |
| **P24 (단순성)** | ✅ | tuple 반환 단순. 루프 제어는 사유코드 집합 조회로 단순 분기. `_refresh_buyable_prices()` 헬퍼로 중복 제거. 함수 50줄 이하 유지 가능 — `evaluate_buy_candidates`는 루프 내 로직이 길어질 수 있으나, `_refresh_buyable_prices()` 분리로 길이 분산. |

### 10-1. ARCHITECTURE.md 금지 패턴 5개 확인
- [ ] `asyncio.run()` 사용 금지 — 본 설계에서 사용 안 함
- [ ] `create_task` 무분별 분리 금지 — 본 설계에서 사용 안 함
- [ ] `except Exception: pass` 금지 — 루프 내 예외 시 `logger.warning(..., exc_info=True)` + break (안전 종료)
- [ ] async 함수 `await` 누락 금지 — `python -W error::RuntimeWarning main.py`로 검증
- [ ] dead code 방치 금지 — 임시 호환 코드는 2세션에서 제거 명시

---

## 11. UI 기준 변경 내용 (규칙 0-4)

### 11-1. 화면 변화
- **매수 후보 테이블**: 변경 없음 (rank 순서 그대로 표시)
- **매수 이력 화면**: 변경 없음 (체결 이력은 `trade_history`에 종목별 기록, 순위 정보는 매수 사유 문자열에 포함)
- **사용자 체감 변화**: "잔액이 남을 때 1순위만 사고 끝나지 않고 2순위·3순위로 잔액을 더 쓴다"는 점 only

### 11-2. 로그 예시 (사용자가 로그 뷰어에서 확인)
```
[매매] 매수 시도: 삼성전자(005930) 순위=1 업종=반도체
[매매] 매수 주문 전송: 삼성전자(005930) 순위=1
[매매] 매수 시도: SK하이닉스(000660) 순위=2 업종=반도체
[매매] 매수 주문 전송: SK하이닉스(000660) 순위=2
[매매] 주문가능 금액 0원 — 차순위 시도 중단
```
또는
```
[매매] 매수 시도: 삼성전자(005930) 순위=1 업종=반도체
[매매] 삼성전자(005930) 종목별 차단 — 차순위 시도 (사유=rise_guard)
[매매] 매수 시도: SK하이닉스(000660) 순위=2 업종=반도체
[매매] 매수 주문 전송: SK하이닉스(000660) 순위=2
```

### 11-3. 사용자 의문 사전 차단 (P21)
- "왜 1순위 안 사고 2순위 샀지?" → 로그에 "1순위 종목별 차단 — 차순위 시도 (사유=rise_guard)" 명시
- "왜 잔액 남았는데 안 샀지?" → 로그에 "주문가능 금액 0원 — 차순위 시도 중단" 또는 "일일 매수 한도 도달 — 차순위 시도 중단" 명시
- "왜 2순위만 사고 3순위는 안 샀지?" → 동일하게 잔액/한도 도달 로그 명시

---

## 12. 위험 및 완화

### 12-1. 임시 호환 코드 위험 (1세션~2세션 사이)
- **위험**: 1세션에서 `execute_buy`가 tuple 반환, 2세션까지 `buy_order_executor`에 임시 호환 코드가 있음. 이 사이에 다른 세션에서 `buy_order_executor`를 수정하면 호환 코드가 누락될 수 있음.
- **완화**: 1세션 커밋 메시지에 "임시 호환 — 2세션에서 제거 예정" 명시. `HANDOVER.md`에도 명시. 2세션은 1세션 직후에 진행 권장.

### 12-2. `_buyable_codes` 재계산 성능
- **위험**: 매 매수 성공 후 `_refresh_buyable_prices()` 호출 시 `buy_targets` 전체 순회. `buy_targets`는 `max_sectors` 상위 업종 내 종목으로 한정되어 있으나, 종목 수가 많을 경우 O(n) 순회 비용.
- **완화**: `buy_targets`는 이미 한정된 집합(상위 3개 업종 내 종목). 실제 종목 수는 수십 개 수준. 매 틱 단위가 아닌 매수 성공 시만 호출되므로 성능 영향 미미.

### 12-3. 차순위 시도 시 시간 지연
- **위험**: 1순위 매수 성공 후 2순위 시도까지 `execute_buy` 내부 로그·저널링·체결 이력 기록 등으로 인해 시간 지연. 2순위 시도 시 현재가가 변동될 수 있음.
- **완화**: `execute_buy`는 글로벌 매수 락 내부에서 순차 처리. 2순위 시도 시 `_execute_buy_locked`가 다시 호출되어 최신 현재가 기반으로 `buy_qty` 산정. 시간 지연은 자연스러운 순차 처리의 일부.

### 12-4. `BUY_REJECT_QTY_ZERO` 조건부 판별 TOCTOU
- **위험**: `buy_order_executor`에서 `BUY_REJECT_QTY_ZERO` 수신 후 `get_withdrawable_deposit()` 재조회 시점과 `execute_buy` 내부 잔액 조회 시점 간 미세한 시간 차이.
- **완화**: 글로벌 매수 락 내부에서 순차 처리되므로, `buy_order_executor` 재조회 후 2순위 `execute_buy` 호출 시 락을 다시 획득하여 최신 잔액 기반으로 처리. TOCTOU 경쟁 상태 발생 가능성 낮음. 추가적으로 `execute_buy` 내부에서 다시 잔액 검증하므로 이중 검증.

### 12-5. 서킷브레이커 OPEN 시 차순위 시도
- **위험**: 1순위 주문 전송 실패로 서킷브레이커가 OPEN이 되면, `trading.py:335`에서 자동매매 마스터 스위치 강제 OFF. 2순위 `execute_buy` 호출 시 `auto_buy_effective`가 False → `BUY_REJECT_AUTO_BUY_OFF` 반환 → 전체 차단 → 루프 종료.
- **완화**: 자연스럽게 전체 차단 사유로 분류되어 루프 종료. 추가 조치 불필요.

---

## 13. 참조 규칙

- AGENTS.md 섹션3 규칙 0 (승인 전 수정 금지)
- AGENTS.md 섹션3 규칙 0-1 (세션당 1단계)
- AGENTS.md 섹션3 규칙 0-2 (수정 전 사전조사)
- AGENTS.md 섹션3 규칙 0-4 (핵심 로직 변경 시 UI 기준 설명 + 승인)
- AGENTS.md 섹션3 규칙 0-5 (사용자가 설계/승인한 로직은 더 엄격하게)
- AGENTS.md 섹션3 규칙 3 (파일/블록 단위 수정)
- AGENTS.md 섹션3 규칙 4-1 (테스트 실패 추적 의무)
- AGENTS.md 섹션4 "다단계 작업 워크플로우"
- AGENTS.md 섹션4 규칙 11 (계획서 삭제)
- safe-trade 스킬 (거래 로직 수정 시 모의투자/안전성 확인)
- ARCHITECTURE.md P10/P15/P16/P20/P21/P22/P23/P24

---

## 14. 다단계 작업 완료 후 삭제 대상 (규칙 11)

- `docs/architecture_multi_rank_buy_design.md` (본 설계서 — 2세션 완료 후 삭제)

> **참고**: 본 설계서는 다단계 작업 완료 후 삭제. 태스크 파일(`docs/plan_*.md`)은 작성하지 않음 — 2세션 구성으로 태스크 파일이 필요할 만큼 단계가 많지 않음. 본 설계서의 섹션 8(세션 분할 상세)이 태스크 파일 역할 겸함.
