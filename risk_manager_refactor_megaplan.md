# SectorFlow RiskManager 리팩토링 정밀 검증 및 단계별 구현 계획

**한 문장 요약:** 기존 `risk_manager_refactor.md`를 코드 기반으로 검증·보정하고, `RiskManager`의 실전 모드 `get_withdrawable_deposit` 버그 수정과 `daily_loss_limit` 런타임 alias 중앙화를 핵심으로 하는 Phase 1 구현 계획을 작성하며, 일일 매수/보유/비중 한도 중앙화(Phase 2)와 프론트 UI 반영(Phase 3)은 명확한 게이트 조건과 함께 포함한다.

---

## 1. 기존 `risk_manager_refactor.md` 검증 결과

### 1.1 정확한 주장

- `max_daily_loss_limit` 설정은 `backend/app/core/settings_defaults.py:57`, `backend/app/core/engine_settings.py:77`, `backend/app/services/risk_manager.py:33`에서 정의/캐스팅/동기화됨.
- `RiskManager.check_buy_order_allowed`는 `backend/app/services/risk_manager.py:53`에서 `today_pnl <= self.max_daily_loss_limit`로 매수 차단.
- 실전 모드 매수 경로에서 `get_risk_manager().account_manager.get_withdrawable_deposit()` 호출이 존재함:
  - `backend/app/services/trading.py:221`
  - `backend/app/services/buy_order_executor.py:86`
- `RiskManager` 클래스에는 실제로 `account_manager` 속성이 없어 실전 모드에서 `AttributeError`가 발생함.
- `max_total_exposure_ratio`는 `risk_manager.py:35`에서 동기화만 하고 `check_buy_order_allowed`에서는 사용하지 않음.
- 일일 매수 한도(`max_daily_total_buy_amt`)는 현재 `trading.py:158-174`, `buy_order_executor.py:72-78`에서 직접 관리.

### 1.2 오류/누락/부정확한 부분

| 항목 | 기존 계획 | 실제 코드 상태 |
|------|----------|---------------|
| `trading.py` 라인 | 221이라고 언급 | 실제 `execute_buy`는 85~ 선언, `account_manager` 호출은 **221** — 번호는 맞지만 함수 시작점이 85라는 맥락 누락 |
| `buy_order_executor.py` 라인 | 86이라고 언급 | 실제 **85~86**에 import+호출이 있음; top-level import가 아님 |
| `daily_loss_limit` 설정 키 | "둘 중 하나로 중앙화" 제안 | 코드/기본값에 `daily_loss_limit`이라는 **키가 존재하지 않음**. `max_daily_loss_limit`만 존재 |
| 사용자 투명성(원칙 21) | 언급 없음 | 매수 차단 사유가 프론트엔드로 전달되지 않음; 수익현황 페이지에 손실 한도/남은 여력 표시 없음 |
| `_sync_thresholds` 호출 시점 | 매 `check_buy_order_allowed`마다 호출 | 맞지만, 설정 변경 즉시 반영은 `state.integrated_system_settings_cache`가 이미 갱신되므로 현재 구조로도 충족 |
| 테스트 | `test_risk_manager.py` 검증 언급 | `get_withdrawable_deposit`/`daily_loss_limit` alias에 대한 테스트 없음; fixture가 `__new__`로 객체를 직접 조립하므로 변경 시 fixture 갱신 필요 |

### 1.3 핵심 결함 요약

1. **실전 모드 매수 시 `AttributeError`**: `trading.py:221`, `buy_order_executor.py:86`가 없는 `account_manager`를 호출.
2. **`daily_loss_limit` 부재**: 요구사항에만 등장하고 실제 데이터/코드에는 없음. `max_daily_loss_limit`의 alias로 처리하는 것이 SSOT 원칙(원칙 10)에 부합.
3. **`max_total_exposure_ratio` 무용**: 설정값은 있으나 검사 로직 미구현.
4. **사용자 투명성 부족(원칙 21)**: 매수 차단 사유가 로그에만 남고 UI로 전달되지 않음.

---

## 2. 목표 및 수용 기준

### 2.1 목표

Phase 1 필수:
- `RiskManager`가 매수 전 **출금가능 예수금/주문가능금액**을 통일하여 제공.
- `daily_loss_limit`를 `max_daily_loss_limit`의 런타임 alias로 정의하여 용어 혼란 제거.
- 실전 모드에서의 `AttributeError` 근본 제거.
- 관련 단위 테스트를 보강하고 런타임 기동 검증을 통과.

Phase 2/3 선택:
- Phase 2: 일일 매수 한도, 보유 종목 수, 전체 투자 비중 한도를 `RiskManager`가 총괄하는 방향으로 **준비**하되, 별도 승인 후 구현.
- Phase 3: `AccountSnapshot`/WS 페이로드에 리스크 한도 상태를 노출하고, 프론트엔드 수익현황/설정 페이지에 반영.

### 2.2 수용 기준

Phase 1:
- `python -m pytest backend/tests/test_risk_manager.py -v` 전체 통과.
- `python -m pytest backend/tests/test_trading.py -v` (또는 존재하지 않으면 `test_buy_order_executor.py`) 통과.
- `.venv/bin/python main.py` 10~30초 기동 후 `backend/logs/trading_*.log`에 `AttributeError`, `RuntimeWarning`, `Traceback` 없음.
- `trading.py`, `buy_order_executor.py`에서 `account_manager` 문자열이 **전혀 남지 않음**.
- `RiskManager`에 `daily_loss_limit` 속성이 존재하고 `check_buy_order_allowed`가 이를 사용함.

Phase 2/3 (승인 시):
- Phase 2: `max_daily_total_buy_amt`, `max_stock_cnt`, `max_total_exposure_ratio` 검사가 `RiskManager` 호출 체인으로 들어오고, 기존 `trading.py`/`buy_order_executor.py`의 중복 검사가 제거됨.
- Phase 3: `npm run build` 통과, 수익현황 페이지에서 `max_daily_loss_limit`/`daily_loss_limit` 및 차단 사유 확인 가능.

---

## 3. 범위 및 제약

### 3.1 범위

**Phase 1 (이 계획의 핵심):**
- `backend/app/services/risk_manager.py`
- `backend/app/services/trading.py`
- `backend/app/services/buy_order_executor.py`
- `backend/tests/test_risk_manager.py`
- `backend/tests/test_trading.py` (존재 시)
- `backend/tests/test_buy_order_executor.py` (존재 시)

**Phase 2 (게이트 조건 만족 시):**
- 동일 파일 + `backend/app/services/engine_strategy_core.py`, `backend/app/services/settlement_engine.py`

**Phase 3 (게이트 조건 만족 시):**
- `frontend/src/types/index.ts`
- `frontend/src/stores/hotStore.ts`
- `frontend/src/pages/buy-settings.ts` 또는 `frontend/src/pages/general-settings.ts`
- `backend/app/services/engine_account_notify.py` (WS 페이로드)

### 3.2 제약

- **새 설정 키 추가 금지 (Phase 1)**: `daily_loss_limit`는 런타임 alias일 뿐, DB/기본값에는 `max_daily_loss_limit`만 유지. SSOT 원칙(원칙 10) 준수.
- **폴백 금지 (원칙 20)**: `account_manager` 호출부를 삭제하고 올바른 메서드로 교체; `try/except`로 에러를 숨기지 않음.
- **테스트모드 동등성 (원칙 18)**: `get_withdrawable_deposit` 내부에서 모드 분기를 최소화; 돈 I/O(예수금 조회) 지점에서만 분기.
- **사용자 투명성 (원칙 21)**: Phase 1에서도 차단 사유 문자열을 그대로 활용 가능한 구조로 남겨두고, Phase 3에서 WS로 노출.
- **런타임 검증 (원칙 19)**: 백엔드 수정 후 반드시 `main.py` 기동 및 로그 확인.

---

## 4. 현재 코드 기반 사실

### 4.1 `RiskManager` (`backend/app/services/risk_manager.py`)

```
25:  def __init__(self):
26:      self.circuit_breaker = get_circuit_breaker()
27:      self._sync_thresholds()

29:  def _sync_thresholds(self) -> None:
30:      ...
33:      self.max_daily_loss_limit = int(cache.get("max_daily_loss_limit", -500000) or -500000)
34:      self.max_single_stock_exposure = int(...)
35:      self.max_total_exposure_ratio = float(...)

37:  async def check_buy_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
42:      self._sync_thresholds()
45:      if not self.circuit_breaker.allow_request(): ...
52:      today_pnl = await get_total_realized_pnl(...)
53:      if today_pnl <= self.max_daily_loss_limit: ...
60-67: 예수금 검사 (테스트모드: settlement_engine.get_available_cash, 실전: account_snapshot["orderable"])
69-88: 단일 종목 비중 검사
```

### 4.2 `trading.py` 매수 경로 (`backend/app/services/trading.py`)

```
85:  async def execute_buy(...)
144-153: max_stock_cnt 보유 종목 수 검사 (state.auto_trade 로직)
155-174: buy_amt, max_daily_total_buy_amt, 종목당 일일 한도 계산
180-214: 등락률/체결강도 가드
217-221: 주문가능 금액 계산
       if is_test_mode(raw_all):
           from backend.app.services.settlement_engine import get_available_cash
           _orderable = get_available_cash()
       else:
           _orderable = get_risk_manager().account_manager.get_withdrawable_deposit()  # ← AttributeError

234-240: RiskManager.check_buy_order_allowed 호출
```

### 4.3 `buy_order_executor.py` (`backend/app/services/buy_order_executor.py`)

```
59-66: max_stock_cnt 사전 차단
68-78: buy_amt, max_daily_total_buy_amt 사전 차단
81-86: 주문가능 금액 사전 체크
       if is_test_mode(state.integrated_system_settings_cache):
           from backend.app.services.settlement_engine import get_available_cash
           _available = get_available_cash()
       else:
           from backend.app.services.risk_manager import get_risk_manager
           _available = get_risk_manager().account_manager.get_withdrawable_deposit()  # ← AttributeError

154-158: state.auto_trade.execute_buy 호출
```

### 4.4 설정/정산 (`backend/app/core/settings_defaults.py`, `engine_settings.py`, `settlement_engine.py`)

- `settings_defaults.py:57`: `"max_daily_loss_limit": -500000`
- `engine_settings.py:77`: `"max_daily_loss_limit": int(merged.get("max_daily_loss_limit", -500000) or -500000)`
- `settlement_engine.py:51-53`: `get_available_cash()` → `_orderable`
- `settlement_engine.py:144-151`: `get_effective_buy_power(daily_limit, daily_spent)` — 일일 매수 한도 관련

### 4.5 계좌 스냅샷/WS (`backend/app/services/engine_account.py`, `engine_account_notify.py`)

- `engine_account.py:333-334`: 테스트모드에서 `account_snapshot["accumulated_investment"]`와 `"orderable"` 설정.
- `engine_account_notify.py:181-182`: `_SNAPSHOT_CMP_KEYS`에 `deposit`, `orderable`, `accumulated_investment`, `total_buy_amount`, `total_eval_amount`, `total_pnl`, `total_pnl_rate`만 포함.
- 현재 `max_daily_loss_limit`은 스냅샷/WS에 미포함.

### 4.6 프론트엔드 타입 (`frontend/src/types/index.ts`)

- `AccountSnapshot`에 `max_daily_loss_limit`, `daily_loss_limit`, `daily_buy_spent`, `max_daily_total_buy_amt` 없음.
- `AppSettings`에 `max_daily_loss_limit` 없음.

### 4.7 테스트 (`backend/tests/test_risk_manager.py`)

- Fixture `risk_manager`가 `RiskManager.__new__`로 객체 생성 후 속성 직접 주입 (`max_daily_loss_limit`, `max_single_stock_exposure`, `max_total_exposure_ratio`).
- `daily_loss_limit` 및 `get_withdrawable_deposit`에 대한 테스트 부재.

---

## 5. 구현 단계

### Phase 1: RiskManager 본연의 책임 강화 (필수)

#### Step 1.1 — `RiskManager.get_withdrawable_deposit()` 추가

`backend/app/services/risk_manager.py`에 동기 메서드 추가:

```python
def get_withdrawable_deposit(self) -> int:
    """주문 가능한 예수금/가용금액을 모드에 따라 반환.

    - 테스트모드: settlement_engine._orderable
    - 실전모드: account_snapshot['orderable']
    """
    from backend.app.services.engine_state import state as engine_state
    cache = engine_state.integrated_system_settings_cache
    if is_test_mode(cache):
        from backend.app.services.settlement_engine import get_available_cash
        return get_available_cash()
    return int(engine_state.account_snapshot.get("orderable", 0) or 0)
```

아키텍처 근거:
- 원칙 18: 돈 I/O(예수금 조회) 지점에서만 모드 분기.
- 원칙 10: 예수금 데이터는 `settlement_engine`(테스트)과 `account_snapshot`(실전)이 SSOT.
- 원칙 16: `check_buy_order_allowed`와 `execute_buy`가 실제 살아있는 경로.

#### Step 1.2 — `daily_loss_limit` alias 정의

`RiskManager._sync_thresholds` 마지막에 추가:

```python
self.max_daily_loss_limit = int(cache.get("max_daily_loss_limit", -500000) or -500000)
self.daily_loss_limit = int(
    cache.get("daily_loss_limit", self.max_daily_loss_limit) or self.max_daily_loss_limit
)
```

`check_buy_order_allowed`에서 `self.max_daily_loss_limit` 대신 `self.daily_loss_limit` 사용:

```python
if today_pnl <= self.daily_loss_limit:
    ...
    return False, "일일 손실 한도 초과"
```

> Phase 1에서는 DB에 `daily_loss_limit` 키가 없으므로 항상 `max_daily_loss_limit`과 동일. 이는 향후 별도 런타임 한도가 필요할 때 대비한 alias 지점.

#### Step 1.3 — 호출부 교체

`backend/app/services/trading.py:217-221`:

```python
# 변경 전
if is_test_mode(raw_all):
    from backend.app.services.settlement_engine import get_available_cash
    _orderable = get_available_cash()
else:
    _orderable = get_risk_manager().account_manager.get_withdrawable_deposit()

# 변경 후
_orderable = get_risk_manager().get_withdrawable_deposit()
```

`backend/app/services/buy_order_executor.py:81-86`:

```python
# 변경 전
if is_test_mode(state.integrated_system_settings_cache):
    from backend.app.services.settlement_engine import get_available_cash
    _available = get_available_cash()
else:
    from backend.app.services.risk_manager import get_risk_manager
    _available = get_risk_manager().account_manager.get_withdrawable_deposit()

# 변경 후
from backend.app.services.risk_manager import get_risk_manager
_available = get_risk_manager().get_withdrawable_deposit()
```

> `buy_order_executor.py`의 import를 top-level로 이동하여 코드 중복 제거. 단, 순환 import 여부를 확인 후 적용.

#### Step 1.4 — `RiskManager.check_buy_order_allowed` 내부 예수금 검사 통일

현재 `check_buy_order_allowed`의 예수금 검사(60-67)를 `get_withdrawable_deposit()`를 사용하도록 교체:

```python
withdrawable = self.get_withdrawable_deposit()
if order_amount > withdrawable:
    ...
    return False, "예수금 잔고 부족"
```

이로써 `trading.py`/`buy_order_executor.py`의 조기 예수금 체크와 `RiskManager`의 최종 게이트가 동일한 금액 소스를 바라봄.

#### Step 1.5 — 테스트 보강

`backend/tests/test_risk_manager.py`:

1. `risk_manager` fixture에 `daily_loss_limit = -500_000` 추가.
2. `test_all_pass_returns_true`, `test_daily_loss_limit_blocks`, `test_daily_loss_at_limit_blocks`, `test_daily_loss_above_limit_passes` 등이 `daily_loss_limit`을 참조하도록 수정.
3. `get_withdrawable_deposit` 테스트 케이스 추가:
   - 테스트모드: `settlement_engine.get_available_cash`가 호출되고 값 반환.
   - 실전모드: `account_snapshot["orderable"]` 반환.
4. `test_trading.py`/`test_buy_order_executor.py`가 있다면 `account_manager` mock을 `get_withdrawable_deposit` mock으로 교체.

### Phase 2: 일일 매수/보유 종목/전체 비중 한도 중앙화 (선택, 별도 승인 필요)

게이트 조건:
- Phase 1이 완료되어 있고, 사용자가 "Phase 2도 진행"이라고 명시.

변경 방향:
- `RiskManager`에 `get_buy_power_status(stk_cd, order_amount, symbol_daily_spent, daily_buy_spent, holding_count)` 추가.
- 또는 `check_buy_order_allowed` 시그니처를 확장하여 `max_daily_total_buy_amt`, `max_stock_cnt`, `max_total_exposure_ratio` 검사 포함.
- `trading.py:144-174`, `buy_order_executor.py:59-78`의 중복 검사를 제거하고 `RiskManager` 호출로 위임.
- `engine_strategy_core.py:67-78`의 `check_test_buy_power`는 `settlement_engine.check_buy_power`를 유지하되, `RiskManager`가 래핑할지 여부는 추가 검토.

참고:
- `max_total_exposure_ratio` 계산 기준(`accumulated_investment` vs `total_buy_amount` vs `orderable`)은 사용자와 사전 협의 필요.

### Phase 3: 프론트엔드 사용자 투명성 반영 (선택, 별도 승인 필요)

게이트 조건:
- Phase 1(또는 Phase 2) 완료 후 사용자가 "프론트 UI도 진행"이라고 명시.

변경 방향:
1. `backend/app/services/engine_account_notify.py`:
   - `_SNAPSHOT_CMP_KEYS`에 `max_daily_loss_limit`, `daily_loss_limit` 추가 (또는 별도 WS 이벤트 `risk-status-update` 도입).
   - `_build_lightweight_payload_for_profit_overview`에도 동일 필드 추가.
2. `frontend/src/types/index.ts`:
   - `AccountSnapshot`에 `max_daily_loss_limit?: number; daily_loss_limit?: number;` 추가.
   - `AppSettings`에 `max_daily_loss_limit: number;` 추가.
3. `frontend/src/stores/hotStore.ts`:
   - `applyAccountUpdate`에서 `max_daily_loss_limit`/`daily_loss_limit`를 `account`에 반영.
4. `frontend/src/pages/buy-settings.ts` 또는 `frontend/src/pages/general-settings.ts`:
   - 일일 손실 한도 입력 UI 추가. `max_daily_loss_limit`이 이미 `settings_defaults.py`에 있으므로 별도 기본값 추가 불필요.
5. 수익현황 페이지(또는 헤더):
   - "오늘 손익 / 일일 손실 한도" 게이지/배지 추가.
   - `buy_order_executor.py` 등에서 차단 시 WS로 `buy-blocked` 이벤트 발송하여 "왜 매수되지 않았는지" 표시.

---

## 6. 인터페이스 변경

### 6.1 `RiskManager`에 추가/변경되는 메서드/속성

```python
class RiskManager:
    ...

    def _sync_thresholds(self) -> None:
        ...
        self.daily_loss_limit: int = ...  # max_daily_loss_limit alias

    def get_withdrawable_deposit(self) -> int:
        ...

    async def check_buy_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        ...
```

### 6.2 호출부 변경

- `trading.py:217-221` → 단일 `get_risk_manager().get_withdrawable_deposit()`
- `buy_order_executor.py:81-86` → 단일 `get_risk_manager().get_withdrawable_deposit()`
- `risk_manager.py:60-67` → `self.get_withdrawable_deposit()`

---

## 7. 테스트 및 검증 매트릭스

| 단계 | 검증 항목 | 명령/방법 | 통과 기준 |
|------|----------|----------|-----------|
| Phase 1-1 | RiskManager 단위 테스트 | `python -m pytest backend/tests/test_risk_manager.py -v` | 전체 통과, 특히 `daily_loss_limit`/`get_withdrawable_deposit` 신규 케이스 |
| Phase 1-2 | Trading/BuyExecutor 단위 테스트 | `python -m pytest backend/tests/test_trading.py backend/tests/test_buy_order_executor.py -v` | 전체 통과 (파일이 없으면 생략) |
| Phase 1-3 | 정적 분석 | `mypy backend/app/services/risk_manager.py backend/app/services/trading.py backend/app/services/buy_order_executor.py` | 오류 없음 |
| Phase 1-4 | 문자열 잔여 확인 | `grep -R "account_manager" backend/app/services/trading.py backend/app/services/buy_order_executor.py` | 출력 없음 |
| Phase 1-5 | 런타임 기동 | `.venv/bin/python main.py` 10~30초 대기 | 콘솔/파일 로그에 `AttributeError`, `RuntimeWarning`, `Traceback` 없음 |
| Phase 1-6 | 잔존 프로세스 정리 | `ps aux \| grep -E "python main.py" \| grep -v grep` | 기동 테스트 후 0개 |
| Phase 2 | 통합 테스트 | `python -m pytest backend/tests/test_risk_manager.py backend/tests/test_trading.py backend/tests/test_buy_order_executor.py -v` | Phase 2 범위까지 통과 |
| Phase 3 | 프론트엔드 빌드 | `cd frontend && npm run build && npm run type-check` | 오류 없음 |
| Phase 3 | 브라우저 UI 확인 | 개발 서버 기동 후 수익현황/설정 페이지 확인 | 손실 한도 및 차단 사유 표시됨 |

---

## 8. 아키텍처 원칙 준수 점검

| 원칙 | 적용 내용 |
|------|----------|
| 원칙 10 (SSOT) | `max_daily_loss_limit`만 설정 키로 유지; `daily_loss_limit`는 런타임 alias. 예수금은 `settlement_engine`/`account_snapshot`이 SSOT. |
| 원칙 16 (살아있는 경로) | `execute_buy` → `check_buy_order_allowed`의 예수금/손실 한도 검사를 실제 호출 체인에서 통일. |
| 원칙 18 (테스트모드 동등성) | `get_withdrawable_deposit` 내부에서만 모드 분기; 외부 로직은 동일. |
| 원칙 20 (폴백 금지) | `account_manager` 호출을 삭제; 임시 `try/except`로 에러를 숨기지 않음. |
| 원칙 21 (사용자 투명성) | Phase 1에서 차단 사유 문자열을 그대로 유지하고, Phase 3에서 WS/UI로 노출. |

---

## 9. 리스크 및 완화

| 리스크 | 영향 | 완화책 |
|--------|------|--------|
| `buy_order_executor.py`에 top-level `get_risk_manager` import 시 순환 import | `ImportError` | import 위치를 조정하거나 기존 lazy import를 유지한 채 호출부만 교체 |
| `RiskManager._sync_thresholds`가 매 호출마다 `engine_state`를 import | 성능/순환 | 현재와 동일한 lazy import 방식 유지; 필요 시 `_sync_thresholds` 호출 최적화는 별도 검토 |
| `get_withdrawable_deposit` 반환값이 실제 "출금가능 예수금"과 다름 | 실전 모드에서 주문 실패 | 현재 실전 모드도 `account_snapshot["orderable"]`을 사용 중이므로 동일 데이터를 사용; 향후 실제 출금가능예수금 API가 생기면 그때 교체 |
| Phase 2/3 범위 확대로 인한 회귀 | 테스트 실패 | Phase 1 완료 후 별도 승인 받고, 작은 PR로 분리 |

---

## 10. 승인 요청

사용자가 아래 항목을 확인/승인하면 Phase 1 구현 시작:

1. `daily_loss_limit`를 `max_daily_loss_limit`의 런타임 alias로 처리 (새 설정 키 미추가) — 동의함 / 별도 설정 키 필요
2. Phase 1만 우선 진행 — 동의함 / Phase 2도 같이 진행 / Phase 3도 같이 진행
3. `get_withdrawable_deposit` 실전 모드 반환값을 `account_snapshot["orderable"]`로 유지 — 동의함 / 실제 출금가능예수금 조회 필요
4. Phase 1 구현 후 런타임 기동 검증까지 수행 — 동의함

> 위 4가지 중 변경 사항이 있으면 이 계획을 수정한 뒤 구현에 들어간다. 변경 사항이 없다면 "Phase 1 진행"이라고 회신해주세요.
