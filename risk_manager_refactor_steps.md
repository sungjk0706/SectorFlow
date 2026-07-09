# RiskManager 리팩토링 — 단계별 실행 계획서

**한 문장 요약:** `RiskManager`의 실전 모드 `account_manager` 버그를 수정하고 `daily_loss_limit` alias를 중앙화하는 Phase 1을 5개 세션 단계로 분리하여 실행한다.

> **Phase 1 완료 (2026-07-09)** — Step 1~5 전체 완료. 커밋: `6a4f1e1`, `16f739b`, `96d9dde`, `74d25bc`. 전체 회귀 1020 passed, 런타임 기동 정상.

> 참조: 상세 분석은 `risk_manager_refactor-megaplan-5b058d.md` 참고.

---

## Step 1 — `RiskManager.get_withdrawable_deposit()` + `daily_loss_limit` alias 추가

**세션 목표:** `risk_manager.py`에 `get_withdrawable_deposit()` 메서드를 추가하고, `_sync_thresholds`에 `daily_loss_limit` alias를 정의한다.

**대상 파일:** `backend/app/services/risk_manager.py`

**변경 내용:**

1. `_sync_thresholds` 마지막에 `self.daily_loss_limit` alias 추가:
   ```python
   self.max_daily_loss_limit = int(cache.get("max_daily_loss_limit", -500000) or -500000)
   self.daily_loss_limit = int(
       cache.get("daily_loss_limit", self.max_daily_loss_limit) or self.max_daily_loss_limit
   )
   ```

2. `check_buy_order_allowed`에서 `self.max_daily_loss_limit` → `self.daily_loss_limit`로 교체 (53, 54번 라인)

3. `check_buy_order_allowed` 내부 예수금 검사(60-67)를 `self.get_withdrawable_deposit()` 호출로 통일:
   ```python
   # 변경 전 (60-67)
   if is_test_mode(cache):
       from backend.app.services.settlement_engine import get_available_cash
       withdrawable = get_available_cash()
   else:
       withdrawable = int(engine_state.account_snapshot.get("orderable", 0) or 0)

   # 변경 후
   withdrawable = self.get_withdrawable_deposit()
   ```

4. `RiskManager` 클래스에 `get_withdrawable_deposit()` 동기 메서드 추가 (`check_sell_order_allowed` 앞):
   ```python
   def get_withdrawable_deposit(self) -> int:
       """주문 가능한 예수금/가용금액을 모드에 따라 반환."""
       from backend.app.services.engine_state import state as engine_state
       cache = engine_state.integrated_system_settings_cache
       if is_test_mode(cache):
           from backend.app.services.settlement_engine import get_available_cash
           return get_available_cash()
       return int(engine_state.account_snapshot.get("orderable", 0) or 0)
   ```

**검증:**
- `python -m pytest backend/tests/test_risk_manager.py -v` — 기존 테스트 전체 통과
- `grep -n "daily_loss_limit" backend/app/services/risk_manager.py` — `self.daily_loss_limit` 할당 + 사용 확인
- `grep -n "get_withdrawable_deposit" backend/app/services/risk_manager.py` — 메서드 정의 + 호출 확인

**완료 조건:** 코드 수정 + pytest 통과 + 커밋

---

## Step 2 — `trading.py` 호출부 교체

**세션 목표:** `trading.py:217-221`의 `account_manager` 호출을 `get_risk_manager().get_withdrawable_deposit()`로 교체.

**대상 파일:** `backend/app/services/trading.py`

**변경 내용:**

`trading.py:217-221`:
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

> `get_risk_manager`는 이미 `trading.py:19`에 top-level import 되어 있음.

**검증:**
- `python -m pytest backend/tests/test_trading.py -v` — 전체 통과
- `grep -n "account_manager" backend/app/services/trading.py` — 출력 없음
- `grep -n "get_withdrawable_deposit" backend/app/services/trading.py` — 호출 1건 확인

**완료 조건:** 코드 수정 + pytest 통과 + 커밋

---

## Step 3 — `buy_order_executor.py` 호출부 교체

**세션 목표:** `buy_order_executor.py:81-86`의 `account_manager` 호출을 `get_risk_manager().get_withdrawable_deposit()`로 교체.

**대상 파일:** `backend/app/services/buy_order_executor.py`

**변경 내용:**

`buy_order_executor.py:81-86`:
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

> 순환 import 확인: `buy_order_executor.py`는 현재 lazy import로 `get_risk_manager`를 사용 중. 변경 후에도 lazy import 유지 (top-level 이동 시 순환 import 위험).

**검증:**
- `python -m pytest backend/tests/test_buy_order_executor.py -v` — 전체 통과
- `grep -n "account_manager" backend/app/services/buy_order_executor.py` — 출력 없음
- `grep -n "get_withdrawable_deposit" backend/app/services/buy_order_executor.py` — 호출 1건 확인

**완료 조건:** 코드 수정 + pytest 통과 + 커밋

---

## Step 4 — 테스트 보강

**세션 목표:** `test_risk_manager.py`에 `daily_loss_limit` alias와 `get_withdrawable_deposit` 단위 테스트를 추가.

**대상 파일:** `backend/tests/test_risk_manager.py`

**변경 내용:**

1. `risk_manager` fixture에 `daily_loss_limit` 속성 추가:
   ```python
   rm.max_daily_loss_limit = -500_000
   rm.daily_loss_limit = -500_000  # alias
   ```

2. `TestSyncThresholds`에 `daily_loss_limit` alias 검증 추가:
   - `test_sync_reads_from_engine_state`: `assert rm.daily_loss_limit == -1_000_000`
   - `test_sync_defaults_when_keys_missing`: `assert rm.daily_loss_limit == -500_000`

3. `TestGetWithdrawableDeposit` 클래스 추가:
   - `test_test_mode_returns_settlement_engine_cash`: `is_test_mode=True`, `get_available_cash` mock → 반환값 확인
   - `test_real_mode_returns_account_snapshot_orderable`: `is_test_mode=False`, `account_snapshot["orderable"]` → 반환값 확인

4. 기존 테스트 중 `check_buy_order_allowed`의 예수금 검사가 `get_withdrawable_deposit`을 통해 호출되므로, mock 경로 확인:
   - 실전모드 테스트: `mock_state.account_snapshot = {"orderable": ...}` 유지 → `get_withdrawable_deposit`이 이를 읽음
   - 테스트모드 테스트: `patch("backend.app.services.settlement_engine.get_available_cash", ...)` 유지 → `get_withdrawable_deposit`이 이를 호출

**검증:**
- `python -m pytest backend/tests/test_risk_manager.py -v` — 신규 테스트 포함 전체 통과

**완료 조건:** 테스트 추가 + pytest 통과 + 커밋

---

## Step 5 — 런타임 기동 검증 + 전체 회귀 테스트

**세션 목표:** 모든 변경사항 통합 검증.

**검증 순서:**

1. **전체 회귀 테스트:**
   ```
   python -m pytest backend/tests/test_risk_manager.py backend/tests/test_trading.py backend/tests/test_buy_order_executor.py -v
   ```

2. **문자열 잔여 확인:**
   ```
   grep -R "account_manager" backend/app/services/trading.py backend/app/services/buy_order_executor.py
   ```
   → 출력 없음

3. **런타임 기동 (원칙 19):**
   - `.venv/bin/python main.py` 기동
   - 10~30초 대기
   - 콘솔/파일 로그에 `AttributeError`, `RuntimeWarning`, `Traceback` 없음 확인
   - 프로세스 종료 후 잔존 프로세스 0개 확인

4. **Git 커밋 + HANDOVER.md 업데이트** (사용자 승인 후)

**완료 조건:** 회귀 테스트 통과 + 런타임 기동 정상 + HANDOVER.md 업데이트

---

## Phase 2/3 (별도 승인 필요)

- **Phase 2 게이트:** Phase 1 완료 + 사용자 "Phase 2 진행" 명시
- **Phase 3 게이트:** Phase 1(또는 2) 완료 + 사용자 "프론트 UI 진행" 명시
- 상세 내용: `risk_manager_refactor-megaplan-5b058d.md` 섹션 5의 Phase 2/3 참조
