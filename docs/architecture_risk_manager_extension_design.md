# 설계서: 리스크 매니저 확장 — 수익률/손실 기반 매매 중단

> **상태**: 설계 완료 (구현 대기)
> **작성일**: 2026-07-18
> **관련 원칙**: P10(SSOT) · P15(단일 주문 경로) · P16(살아있는 경로) · P17(플래그 단일 소스) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)
> **관련 파일**: `backend/app/services/risk_manager.py` · `backend/app/services/trading.py` · `backend/app/core/settings_defaults.py` · `backend/app/core/engine_settings.py` · `backend/app/core/settings_store.py` · `backend/app/services/trade_history.py` · `backend/app/services/engine_account_notify.py` · `frontend/src/pages/general-settings.ts` · `frontend/src/stores/uiStore.ts` · `frontend/src/binding.ts` · `frontend/src/layout/header.ts`

---

## 1. 배경 및 목표

### 1.1 현재 상태

`RiskManager`(`backend/app/services/risk_manager.py`)는 매수/매도 주문이 실제로 나가기 직전에 게이트 역할을 수행. 현재 체크 항목:

| 단계 | 항목 | 설명 |
|------|------|------|
| 1 | 서킷브레이커 | 연속 주문 실패 시 일시 차단 |
| 2 | 일일 손실 한도 | `daily_loss_limit` (기본 -50만원). 당일 실현손익 ≤ 한도 → 매수 차단 |
| 3 | 예수금 잔액 | 주문금액 > 가용 예수금 → 매수 차단 |
| 4 | 단일 종목 비중 | `max_single_stock_exposure` (기본 2,000만원) |

**문제점**:
1. **일일 손실 한도(`daily_loss_limit`)가 UI에 노출되지 않음** — 백엔드에만 존재. 사용자가 조작 불가 (P21 위반).
2. **수익금/수익률 기반 중단 기능 부재** — 목표 수익 달성 시 자동 중단 불가.
3. **손실률 기반 중단 기능 부재** — 손실금만 있고 손실률(%) 기준 없음.
4. **연속 손실 횟수 기반 중단 부재** — N회 연속 손실 시 자동 중단 불가.
5. **매도 쪽 리스크 체크 얇음** — `check_sell_order_allowed()`가 서킷브레이커만 확인.
6. **차단 사유 UI 표시 부재** — 리스크 차단 시 헤더 칩 표시 없음 (P21 위반).

### 1.2 목표

1. **수익금/수익률 기반 매매 중단**: 일정 수익 도달 시 매수/매도 중단 (체크박스로 매수/매도 각각 선택)
2. **손실률 기반 매매 중단**: 일일 손실률 한도 초과 시 매수/매도 중단
3. **일일 손실 한도 UI 노출**: 기존 `daily_loss_limit`을 일반설정 자동매매 탭에 표시
4. **연속 손실 횟수 기반 중단**: N회 연속 손실 시 매수/매도 중단
5. **리스크 매니저 전체 토글**: 모든 리스크 조건을 한 번에 ON/OFF
6. **차단 사유 UI 표시**: 헤더 칩으로 차단 상태/사유 실시간 표시 (P21)
7. **P10/P15/P16/P17/P20/P21/P22/P23/P24 완전 부합**

### 1.3 비목표 (본 설계에서 다루지 않음)

- **코스피/코스닥 지수 차단 (2순위)**: 아키텍처 검토가 더 필요하므로 추후 별도 설계
- **개별 종목 수익률 기반 중단**: 본 설계는 "당일 누적 수익" 기준 단일화. 개별 종목 기준은 복잡도 증가로 제외
- **포트폴리오 전체 수익률 기반 중단**: "당일 실현손익" 기준과 혼동 방지를 위해 본 설계에서는 "당일 누적"만 다룸
- **리스크 조건 알림 텔레그램 전송**: 기존 `_fire_and_forget_telegram()` 패턴 재사용은 구현 단계에서 검토

---

## 2. 설계 방향

### 2.1 핵심 설계 결정

#### 결정 1: 손익 집계 기준 = 현금 기준 (`get_total_realized_pnl`)
- 기존 `daily_loss_limit`과 동일 기준 사용 (P23 일관성)
- 수익금/손실금 = 당일 실현손익 합계 (현금 기준: 매도 실수령 - 매수 실지출, 수수료/세금 포함)
- 수익률/손실률 = 당일 실현손익 ÷ 당일 매수 원금 × 100
- 단일 진실 소스: `trade_history` (P10 SSOT)

#### 결정 2: 매도 차단 조건 배선 위치 = `check_sell_order_allowed()` 내부
- 현재 `check_sell_order_allowed()`는 `check_sell_conditions()` 시작 부분(`trading.py:682-688`)에서만 호출
- 새 매도 차단 조건을 `check_sell_order_allowed()`에 추가하면 자동으로 `check_sell_conditions()`에 배선됨 (P16)
- `execute_sell()` 본문에 별도 체크 추가하지 않음 (P15 단일 경로 유지)

#### 결정 3: 매수 차단 조건 배선 위치 = `check_buy_order_allowed()` 내부
- 현재 `execute_buy()` → `check_buy_order_allowed()` 호출 구조 유지
- 새 조건을 `check_buy_order_allowed()`에 추가하면 자동 배선 (P16)

#### 결정 4: UI 차단 표시 = 기존 헤더 칩 패턴 재사용
- `circuit_breaker_open`, `order_time_blocked`와 동일 패턴
- 새 WS 이벤트 `risk_block_status` 추가 → 헤더 칩 표시
- 차단 조건 미충족 시 자동으로 칩 제거

#### 결정 5: "일일 손실 한도"는 기존 기능 UI 노출로 통합
- 이미 `daily_loss_limit` 키가 백엔드에 존재 (기본 -50만원)
- 별도 기능 추가 대신, 기존 키를 UI에 노출
- 손실금 기반 중단 = 기존 `daily_loss_limit` 활용
- 손실률 기반 중단 = 신규 추가

#### 결정 6: 매도 차단 기본값 = OFF
- `risk_block_sell_on` 기본값 False — 사용자가 명시적으로 ON 해야 활성화
- 사유: 손실 상태에서 매도를 막으면 손실 확대 가능. 수익 상태에서 매도를 막으면 수익 확정 방해.
- 사용자가 위험성 인지 후 명시적으로 활성화하도록 설계

#### 결정 7: 연속 손실 기준 = 최근 매도 거래의 `realized_pnl` (순수 차익)
- `trade_history.get_sell_history()`는 DESC 정렬(최신순)
- 최신 매도부터 역순으로 `realized_pnl < 0`인 거래가 연속 몇 건인지 카운트
- 매도 이력이 없으면 0회
- `realized_pnl` 필드 기준 (순수 차익 = (매도가-매수가)×수량) — 손실 여부 판단은 순수 차익 기준이 직관적

### 2.2 기각 방안

| 방안 | 기각 사유 |
|------|-----------|
| 개별 종목 수익률 기반 중단 | 복잡도 증가, 사용자 혼란. "당일 누적" 단일화가 P24 단순성 부합 |
| 포트폴리오 전체 수익률 | "당일 실현손익"과 혼동. 기준 명확성 위해 당일 누적만 |
| `execute_sell()` 본문에 리스크 체크 추가 | P15 단일 경로 위반. `check_sell_order_allowed()` 확장이 P16 부합 |
| 별도 리스크 서비스 클래스 생성 | P24 단순성 위반. 기존 `RiskManager` 확장이 단순 |
| 손익 집계를 별도 테이블에 저장 | P22 위반. `trade_history` 파생 데이터 중복 저장 금지 |

---

## 3. 백엔드 변경 사항

### 3.1 설정 기본값 추가

**파일**: `backend/app/core/settings_defaults.py`

`DEFAULT_USER_SETTINGS` 딕셔너리에 신규 키 추가 (기존 `max_daily_loss_limit`/`max_single_stock_exposure` 블록 직후):

```python
# 리스크 매니저 (전역매매설정)
"risk_manager_on": False,                  # 리스크 매니저 전체 ON/OFF
"daily_loss_limit": -500000,               # 일일 손실 한도 (원, 음수) — 기존 max_daily_loss_limit과 동일 기준
"daily_loss_rate_limit_on": False,         # 일일 손실률 한도 사용 여부
"daily_loss_rate_limit": -5.0,             # 일일 손실률 한도 (%)
"daily_profit_limit_on": False,            # 일일 수익 한도 사용 여부
"daily_profit_limit": 500000,              # 일일 수익 한도 (원, 양수)
"daily_profit_rate_limit_on": False,       # 일일 수익률 한도 사용 여부
"daily_profit_rate_limit": 5.0,            # 일일 수익률 한도 (%)
"risk_block_buy_on": True,                 # 리스크 조건 충족 시 매수 차단
"risk_block_sell_on": False,               # 리스크 조건 충족 시 매도 차단 (기본 OFF — 손실 확대 방지)
"consecutive_loss_limit_on": False,        # 연속 손실 횟수 제한 사용 여부
"consecutive_loss_limit": 3,               # 연속 손실 N회 시 중단
```

**주의**: 기존 `max_daily_loss_limit` 키는 유지 (레거시 호환). `daily_loss_limit`을 신규 UI 노출용 키로 추가하고, `RiskManager._sync_thresholds()`에서 두 키를 모두 인식하도록 수정 (마이그레이션 호환).

### 3.2 엔진 설정 로더 수정

**파일**: `backend/app/core/engine_settings.py`

기존 리스크 블록(라인 137-144) 직후에 신규 키 타입 캐스팅 추가:

```python
# 리스크 매니저 확장 (이어서) — 0도 유효값이므로 or 폴백 금지 (P20)
result["risk_manager_on"] = bool(merged.get("risk_manager_on"))
_v = merged.get("daily_loss_limit")
result["daily_loss_limit"] = int(_v if _v is not None else -500000)
result["daily_loss_rate_limit_on"] = bool(merged.get("daily_loss_rate_limit_on"))
_v = merged.get("daily_loss_rate_limit")
result["daily_loss_rate_limit"] = float(_v if _v is not None else -5.0)
result["daily_profit_limit_on"] = bool(merged.get("daily_profit_limit_on"))
_v = merged.get("daily_profit_limit")
result["daily_profit_limit"] = int(_v if _v is not None else 500000)
result["daily_profit_rate_limit_on"] = bool(merged.get("daily_profit_rate_limit_on"))
_v = merged.get("daily_profit_rate_limit")
result["daily_profit_rate_limit"] = float(_v if _v is not None else 5.0)
result["risk_block_buy_on"] = bool(merged.get("risk_block_buy_on", True))
result["risk_block_sell_on"] = bool(merged.get("risk_block_sell_on", False))
result["consecutive_loss_limit_on"] = bool(merged.get("consecutive_loss_limit_on"))
_v = merged.get("consecutive_loss_limit")
result["consecutive_loss_limit"] = int(_v if _v is not None else 3)
```

### 3.3 설정 저장 검증 추가

**파일**: `backend/app/core/settings_store.py`

`apply_settings_updates()` 내 기존 `subscribe.max_0b_count` 범위 검증(라인 296-303) 직후에 신규 리스크 키 검증 추가:

```python
# 리스크 매니저 설정 검증 (P20/P22) — 범위/부호 검증
_RISK_INT_KEYS = {
    "daily_loss_limit": (-1_000_000_000, 0),        # 음수만 허용 (손실 한도)
    "daily_profit_limit": (0, 1_000_000_000),       # 양수만 허용 (수익 한도)
    "consecutive_loss_limit": (1, 100),             # 1~100회
}
_RISK_FLOAT_KEYS = {
    "daily_loss_rate_limit": (-100.0, 0.0),         # 음수만 허용
    "daily_profit_rate_limit": (0.0, 100.0),        # 양수만 허용
}
for k, (lo, hi) in _RISK_INT_KEYS.items():
    if k in data:
        try:
            _n = int(data[k])
        except (TypeError, ValueError):
            raise ValueError(f"{k}는 정수여야 합니다")
        if _n < lo or _n > hi:
            raise ValueError(f"{k}는 {lo}~{hi} 사이여야 합니다")
for k, (lo, hi) in _RISK_FLOAT_KEYS.items():
    if k in data:
        try:
            _f = float(data[k])
        except (TypeError, ValueError):
            raise ValueError(f"{k}는 숫자여야 합니다")
        if _f < lo or _f > hi:
            raise ValueError(f"{k}는 {lo}~{hi} 사이여야 합니다")
```

### 3.4 RiskManager 확장

**파일**: `backend/app/services/risk_manager.py`

#### 3.4.1 `_sync_thresholds()` 확장

기존 임계치 동기화에 신규 키 추가:

```python
def _sync_thresholds(self) -> None:
    """engine_state 설정 캐시에서 리스크 임계치 동기화."""
    from backend.app.services.engine_state import state as engine_state
    cache = engine_state.integrated_system_settings_cache
    # 기존
    self.max_daily_loss_limit = int(cache.get("max_daily_loss_limit", -500000) or -500000)
    self.daily_loss_limit = int(
        cache.get("daily_loss_limit", self.max_daily_loss_limit) or self.max_daily_loss_limit
    )
    self.max_single_stock_exposure = int(cache.get("max_single_stock_exposure", 20000000) or 20000000)
    # 신규 — 리스크 매니저 확장
    self.risk_manager_on = bool(cache.get("risk_manager_on", False))
    self.daily_loss_rate_limit_on = bool(cache.get("daily_loss_rate_limit_on", False))
    self.daily_loss_rate_limit = float(cache.get("daily_loss_rate_limit", -5.0) or -5.0)
    self.daily_profit_limit_on = bool(cache.get("daily_profit_limit_on", False))
    self.daily_profit_limit = int(cache.get("daily_profit_limit", 500000) or 500000)
    self.daily_profit_rate_limit_on = bool(cache.get("daily_profit_rate_limit_on", False))
    self.daily_profit_rate_limit = float(cache.get("daily_profit_rate_limit", 5.0) or 5.0)
    self.risk_block_buy_on = bool(cache.get("risk_block_buy_on", True))
    self.risk_block_sell_on = bool(cache.get("risk_block_sell_on", False))
    self.consecutive_loss_limit_on = bool(cache.get("consecutive_loss_limit_on", False))
    self.consecutive_loss_limit = int(cache.get("consecutive_loss_limit", 3) or 3)
```

#### 3.4.2 당일 손익 집계 헬퍼 추가

```python
async def _get_today_pnl_and_principal(self, trade_mode: str) -> tuple[int, int]:
    """당일 실현손익(현금 기준) + 당일 매수 원금 반환.
    
    반환: (today_pnl, today_buy_principal)
    - today_pnl: get_total_realized_pnl(today_only=True) — 현금 기준
    - today_buy_principal: 당일 매수 총액 (수익률 계산 분모)
    """
    from backend.app.services.trade_history import get_total_realized_pnl, get_buy_history
    today_pnl = await get_total_realized_pnl(today_only=True, trade_mode=trade_mode)
    buy_rows = await get_buy_history(today_only=True, trade_mode=trade_mode)
    today_buy_principal = sum(
        int(r.get("price", 0) or 0) * int(r.get("qty", 0) or 0) for r in buy_rows
    )
    return today_pnl, today_buy_principal
```

#### 3.4.3 연속 손실 횟수 집계 헬퍼 추가

```python
async def _get_consecutive_loss_count(self, trade_mode: str) -> int:
    """최근 매도 거래 기준 연속 손실 횟수 반환.
    
    trade_history.get_sell_history()는 DESC 정렬(최신순).
    최신 매도부터 역순으로 realized_pnl < 0인 거래가 연속 몇 건인지 카운트.
    매도 이력이 없거나 최신 거래가 수익이면 0반환.
    """
    from backend.app.services.trade_history import get_sell_history
    rows = await get_sell_history(trade_mode=trade_mode)
    count = 0
    for r in rows:
        pnl = int(r.get("realized_pnl", 0) or 0)
        if pnl < 0:
            count += 1
        else:
            break  # 연속 손실 끊김
    return count
```

#### 3.4.4 `check_buy_order_allowed()` 확장

기존 일일 손실 한도 체크(라인 50-57) 직후에 신규 조건 추가:

```python
async def check_buy_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
    self._sync_thresholds()
    
    # 0. 리스크 매니저 전체 OFF → 모든 리스크 체크 스킵 (서킷브레이커는 유지)
    # 서킷브레이커는 계좌 보호 최소 안전장치이므로 risk_manager_on과 무관하게 항상 동작
    
    # 1. 서킷브레이커 검사 (공통 — 항상 동작)
    if not self.circuit_breaker.allow_request():
        return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"
    
    # 리스크 매니저 OFF → 여기서 종료 (서킷브레이커만 유지)
    if not self.risk_manager_on:
        return True, "승인 (리스크 매니저 OFF — 서킷브레이커만 동작)"
    
    # 매수 차단 비활성화 → 리스크 조건 스킵
    if not self.risk_block_buy_on:
        return True, "승인 (매수 리스크 차단 비활성화)"
    
    from backend.app.services.engine_state import state as engine_state
    cache = engine_state.integrated_system_settings_cache
    trade_mode = "test" if is_test_mode(cache) else "real"
    today_pnl, today_principal = await self._get_today_pnl_and_principal(trade_mode)
    
    # 2. 일일 손실 한도 검사 (기존 — 현금 기준)
    if today_pnl <= self.daily_loss_limit:
        logger.warning("[매매] 일일 손실 한도 초과: 현재 %s, 한도 %s", f"{today_pnl:,}", f"{self.daily_loss_limit:,}")
        return False, "일일 손실 한도 초과"
    
    # 3. 일일 손실률 한도 검사 (신규)
    if self.daily_loss_rate_limit_on and today_principal > 0:
        today_pnl_rate = today_pnl / today_principal * 100
        if today_pnl_rate <= self.daily_loss_rate_limit:
            logger.warning("[매매] 일일 손실률 한도 초과: 현재 %.2f%%, 한도 %.2f%%", today_pnl_rate, self.daily_loss_rate_limit)
            return False, "일일 손실률 한도 초과"
    
    # 4. 일일 수익 한도 검사 (신규)
    if self.daily_profit_limit_on and today_pnl >= self.daily_profit_limit:
        logger.warning("[매매] 일일 수익 한도 도달: 현재 %s, 한도 %s", f"{today_pnl:,}", f"{self.daily_profit_limit:,}")
        return False, "일일 수익 한도 도달"
    
    # 5. 일일 수익률 한도 검사 (신규)
    if self.daily_profit_rate_limit_on and today_principal > 0:
        today_pnl_rate = today_pnl / today_principal * 100
        if today_pnl_rate >= self.daily_profit_rate_limit:
            logger.warning("[매매] 일일 수익률 한도 도달: 현재 %.2f%%, 한도 %.2f%%", today_pnl_rate, self.daily_profit_rate_limit)
            return False, "일일 수익률 한도 도달"
    
    # 6. 연속 손실 횟수 검사 (신규)
    if self.consecutive_loss_limit_on:
        consec_count = await self._get_consecutive_loss_count(trade_mode)
        if consec_count >= self.consecutive_loss_limit:
            logger.warning("[매매] 연속 손실 한도 초과: 현재 %d회, 한도 %d회", consec_count, self.consecutive_loss_limit)
            return False, f"연속 손실 한도 초과 ({consec_count}회)"
    
    # ── 기존 예수금/단일 종목 비중 체크는 그대로 유지 ──
    order_amount = price * qty
    withdrawable = self.get_withdrawable_deposit()
    if order_amount > withdrawable:
        logger.warning("[매매] 예수금 부족: 주문액 %s, 출금가능액 %s", f"{order_amount:,}", f"{withdrawable:,}")
        return False, "예수금 잔고 부족"
    # ... (기존 단일 종목 비중 체크 유지) ...
```

#### 3.4.5 `check_sell_order_allowed()` 확장

기존 서킷브레이커만 체크하던 것을 확장:

```python
async def check_sell_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
    """매도 주문 허용 여부 검사.
    
    매도는 리스크 축소 행위이지만, 사용자가 risk_block_sell_on 활성화 시
    수익/손실 한도 도달 시 매도도 차단 가능.
    """
    # 1. 서킷브레이커 (항상 동작)
    if not self.circuit_breaker.allow_request():
        return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"
    
    # 리스크 매니저 OFF → 종료
    if not self.risk_manager_on:
        return True, "승인 (리스크 매니저 OFF)"
    
    # 매도 차단 비활성화 → 종료
    if not self.risk_block_sell_on:
        return True, "승인 (매도 리스크 차단 비활성화)"
    
    self._sync_thresholds()
    from backend.app.services.engine_state import state as engine_state
    cache = engine_state.integrated_system_settings_cache
    trade_mode = "test" if is_test_mode(cache) else "real"
    today_pnl, today_principal = await self._get_today_pnl_and_principal(trade_mode)
    
    # 2. 일일 손실 한도 (매도 차단 시 손실 확대 위험 — 사용자 명시적 활성화 시에만)
    if today_pnl <= self.daily_loss_limit:
        return False, "일일 손실 한도 초과 (매도 차단)"
    
    # 3. 일일 손실률 한도
    if self.daily_loss_rate_limit_on and today_principal > 0:
        today_pnl_rate = today_pnl / today_principal * 100
        if today_pnl_rate <= self.daily_loss_rate_limit:
            return False, "일일 손실률 한도 초과 (매도 차단)"
    
    # 4. 일일 수익 한도
    if self.daily_profit_limit_on and today_pnl >= self.daily_profit_limit:
        return False, "일일 수익 한도 도달 (매도 차단)"
    
    # 5. 일일 수익률 한도
    if self.daily_profit_rate_limit_on and today_principal > 0:
        today_pnl_rate = today_pnl / today_principal * 100
        if today_pnl_rate >= self.daily_profit_rate_limit:
            return False, "일일 수익률 한도 도달 (매도 차단)"
    
    # 6. 연속 손실 횟수
    if self.consecutive_loss_limit_on:
        consec_count = await self._get_consecutive_loss_count(trade_mode)
        if consec_count >= self.consecutive_loss_limit:
            return False, f"연속 손실 한도 초과 (매도 차단, {consec_count}회)"
    
    return True, "승인"
```

**주의**: `check_sell_order_allowed()`를 `async def`로 변경해야 함. 현재 동기 함수인데, `trade_history` 조회가 async이므로 async로 변환. 호출부(`trading.py:682-683`)도 `await` 추가 필요.

### 3.5 사유코드 추가

**파일**: `backend/app/services/trading.py`

기존 사유코드 블록(라인 35-51)에 신규 코드 추가:

```python
BUY_REJECT_RISK_PROFIT = "risk_profit"           # 일일 수익 한도 도달
BUY_REJECT_RISK_LOSS_RATE = "risk_loss_rate"     # 일일 손실률 한도 초과
BUY_REJECT_RISK_PROFIT_RATE = "risk_profit_rate" # 일일 수익률 한도 도달
BUY_REJECT_RISK_CONSEC_LOSS = "risk_consec_loss" # 연속 손실 한도 초과
```

`BUY_GLOBAL_REJECT_REASONS` frozenset(라인 57-69)에 4개 추가:

```python
BUY_GLOBAL_REJECT_REASONS: frozenset[str] = frozenset({
    # ... 기존 ...
    BUY_REJECT_RISK_PROFIT,
    BUY_REJECT_RISK_LOSS_RATE,
    BUY_REJECT_RISK_PROFIT_RATE,
    BUY_REJECT_RISK_CONSEC_LOSS,
})
```

`_map_risk_reason_to_code()`(라인 72-86)에 신규 매핑 추가:

```python
def _map_risk_reason_to_code(risk_reason: str) -> str:
    if "서킷브레이커" in risk_reason:
        return BUY_REJECT_RISK_CIRCUIT
    if "일일 손실 한도" in risk_reason:
        return BUY_REJECT_RISK_LOSS
    if "일일 손실률 한도" in risk_reason:
        return BUY_REJECT_RISK_LOSS_RATE
    if "일일 수익 한도" in risk_reason:
        return BUY_REJECT_RISK_PROFIT
    if "일일 수익률 한도" in risk_reason:
        return BUY_REJECT_RISK_PROFIT_RATE
    if "연속 손실 한도" in risk_reason:
        return BUY_REJECT_RISK_CONSEC_LOSS
    if "예수금 부족" in risk_reason:
        return BUY_REJECT_RISK_CASH
    if "단일 종목 비중" in risk_reason:
        return BUY_REJECT_RISK_SINGLE
    logger.warning("[매매] RiskManager 알 수 없는 사유 — 전체 차단 분류: %s", risk_reason)
    return BUY_REJECT_RISK_CIRCUIT
```

### 3.6 매도 차단 시 WS 브로드캐스트

**파일**: `backend/app/services/trading.py`

`check_sell_conditions()` 내 기존 리스크 체크(라인 680-688) 확장:

```python
# ── RiskManager 매도 차단 체크 ───────────────────────────────────────
try:
    risk_mgr = get_risk_manager()
    allowed, reason = await risk_mgr.check_sell_order_allowed("", 0, 0)  # await 추가
    if not allowed:
        logger.info("[매매] [리스크차단] 매도 조건 전체 차단 — %s", reason)
        # P21 사용자 투명성 — 차단 사유 WS 브로드캐스트
        from backend.app.services.engine_account_notify import _safe_broadcast
        await _safe_broadcast("risk_block_status", {
            "blocked": True,
            "side": "sell",
            "reason": reason,
        })
        return
except Exception:
    logger.warning("[매매] 리스크 관리자 체크 실패 — 매도 전체 중단", exc_info=True)
    return
```

매수 차단 시에도 동일하게 WS 브로드캐스트 추가 (`execute_buy()` 내 리스크 차단 분기):

```python
if not _allowed:
    _reason_code = _map_risk_reason_to_code(_risk_reason)
    logger.info("[매매] [리스크차단] %s 매수 차단 — %s (사유코드=%s)", stk_cd, _risk_reason, _reason_code)
    # P21 사용자 투명성 — 차단 사유 WS 브로드캐스트
    from backend.app.services.engine_account_notify import _safe_broadcast
    await _safe_broadcast("risk_block_status", {
        "blocked": True,
        "side": "buy",
        "reason": _risk_reason,
    })
    # ... (기존 실패 처리 유지) ...
```

**차단 해제 브로드캐스트**: 리스크 조건 미충족 시(차단 해제 시) `blocked: False` 전송. 이는 주문 시도 시 자동으로 해제되므로, 매수/매도 시도가 성공적으로 통과될 때 `blocked: False` 전송.

### 3.7 `check_sell_order_allowed()` async 변환 영향

`check_sell_order_allowed()`를 `async def`로 변경 시 호출부 수정:

| 파일 | 위치 | 변경 |
|------|------|------|
| `trading.py` | 라인 682-683 | `allowed, reason = risk_mgr.check_sell_order_allowed(...)` → `allowed, reason = await risk_mgr.check_sell_order_allowed(...)` |

단일 호출부만 존재하므로 영향 범위 최소.

---

## 4. 프론트엔드 변경 사항

### 4.1 UI 배치 (일반설정 → 자동매매 탭)

```
일반설정 → 자동매매 탭
├── 자동매매 (마스터 토글) — 기존
├── 자동매수 (토글) — 기존
├── 자동매도 (토글) — 기존
├── 체결 불가 시간대 주문 차단 — 기존
├── [신규] 전역매매설정 (리스크 매니저) 섹션
│   ├── 리스크 매니저 (토글 — risk_manager_on)
│   ├── 일일 손실 한도 (금액 입력 — daily_loss_limit, 음수)
│   ├── 일일 손실률 한도 (토글 + % 입력 — daily_loss_rate_limit_on/_limit)
│   ├── 일일 수익 한도 (토글 + 금액 입력 — daily_profit_limit_on/_limit)
│   ├── 일일 수익률 한도 (토글 + % 입력 — daily_profit_rate_limit_on/_limit)
│   ├── 연속 손실 횟수 (토글 + 횟수 입력 — consecutive_loss_limit_on/_limit)
│   ├── 매수 차단 (체크박스 — risk_block_buy_on)
│   └── 매도 차단 (체크박스 — risk_block_sell_on)
└── 화면 표시 섹션 — 기존
```

### 4.2 general-settings.ts 수정

**파일**: `frontend/src/pages/general-settings.ts`

1. 모듈 상태 변수 추가 (기존 `orderTimeGuardToggle` 등 직후):
```typescript
// 리스크 매니저 참조
let riskManagerToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyLossInput: ReturnType<typeof createMoneyInput> | null = null
let dailyLossRateToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyLossRateInput: ReturnType<typeof createNumInput> | null = null
let dailyProfitToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyProfitInput: ReturnType<typeof createMoneyInput> | null = null
let dailyProfitRateToggle: ReturnType<typeof createToggleBtn> | null = null
let dailyProfitRateInput: ReturnType<typeof createNumInput> | null = null
let consecLossToggle: ReturnType<typeof createToggleBtn> | null = null
let consecLossInput: ReturnType<typeof createNumInput> | null = null
let riskBlockBuyCheckbox: HTMLInputElement | null = null
let riskBlockSellCheckbox: HTMLInputElement | null = null
```

2. `renderAutoTradeTab()` 내 기존 `orderTimeGuardRow` 직후에 리스크 매니저 섹션 추가:
- `sectionTitle('전역매매설정 (리스크 매니저)')`
- `createToggleLabelControlsRow()`로 토글+입력쌍 구성 (기존 패턴 재사용)
- 각 행 자동 저장 (`settingsMgr.saveSection({ key: value }).then(toastResult)`)

3. `syncFromSettings()`에 신규 키 동기화 추가:
```typescript
riskManagerToggle?.setOn(bool(vals.risk_manager_on))
// ... 각 입력값 동기화 ...
```

### 4.3 UI 차단 상태 표시 (P21)

#### 4.3.1 uiStore.ts 수정

**파일**: `frontend/src/stores/uiStore.ts`

1. `UIState` 인터페이스에 신규 상태 추가 (기존 `orderTimeBlocked` 직후):
```typescript
/* ── 리스크 매니저 차단 상태 ── */
riskBlockStatus: { side: string; reason: string } | null
```

2. `initialState`에 추가:
```typescript
riskBlockStatus: null,
```

3. 적용/해제 함수 추가 (기존 `applyOrderTimeBlocked` 패턴 복제):
```typescript
/* ── risk_block_status: 리스크 매니저 차단 상태 갱신 ── */
export function applyRiskBlockStatus(data: { blocked?: boolean; side?: string; reason?: string }): void {
  if (data.blocked) {
    uiStore.setState({ riskBlockStatus: { side: data.side ?? 'unknown', reason: data.reason ?? '리스크 차단' } })
  } else {
    uiStore.setState({ riskBlockStatus: null })
  }
}

/* ── 리스크 차단 상태 수동 해제 (사용자 클릭) ── */
export function clearRiskBlockStatus(): void {
  uiStore.setState({ riskBlockStatus: null })
}
```

4. `applySnapshotData()` 내 초기화에 `riskBlockStatus: null` 추가.

#### 4.3.2 binding.ts 수정

**파일**: `frontend/src/binding.ts`

기존 `order_time_blocked` 핸들러(라인 330-333) 직후에 추가:
```typescript
/* ── risk_block_status: 리스크 매니저 차단 상태 ── */
pricesClient.onEvent('risk_block_status', (data) => {
  applyRiskBlockStatus(data as { blocked?: boolean; side?: string; reason?: string })
})
```

#### 4.3.3 header.ts 수정

**파일**: `frontend/src/layout/header.ts`

기존 `orderTimeBlockedChip`(라인 219-223) 직후에 리스크 차단 칩 추가:
```typescript
// 리스크 매니저 차단 칩 (클릭 시 해제)
const riskBlockChip = createChipEl()
riskBlockChip.style.display = 'none'
riskBlockChip.style.cursor = 'pointer'
riskBlockChip.addEventListener('click', () => clearRiskBlockStatus())
header.appendChild(riskBlockChip)
```

`onStateChange()` 내 기존 `orderTimeBlocked` 표시 로직(라인 271-280) 직후에 추가:
```typescript
// 리스크 매니저 차단 칩 (빨간색 — 손실/수익 한도 도달)
if (riskBlockStatus) {
  riskBlockChip.style.display = ''
  riskBlockChip.style.background = `${COLOR.downBg}`
  riskBlockChip.style.color = `${COLOR.down}`
  riskBlockChip.style.border = `1px solid ${COLOR.down}40`
  const sideLabel = riskBlockStatus.side === 'buy' ? '매수' : riskBlockStatus.side === 'sell' ? '매도' : '매매'
  riskBlockChip.textContent = `⚠ 리스크 차단(${sideLabel}): ${riskBlockStatus.reason}`
} else {
  riskBlockChip.style.display = 'none'
}
```

`onStateChange` 매개변수 destructuring에 `riskBlockStatus` 추가.

### 4.4 types.ts 수정 (선택)

**파일**: `frontend/src/types/index.ts` (또는 `types.ts`)

`AppSettings`에 신규 키 타입 추가 (P23 일관성):
```typescript
risk_manager_on?: boolean
daily_loss_limit?: number
daily_loss_rate_limit_on?: boolean
daily_loss_rate_limit?: number
daily_profit_limit_on?: boolean
daily_profit_limit?: number
daily_profit_rate_limit_on?: boolean
daily_profit_rate_limit?: number
risk_block_buy_on?: boolean
risk_block_sell_on?: boolean
consecutive_loss_limit_on?: boolean
consecutive_loss_limit?: number
```

---

## 5. 테스트 변경 사항

### 5.1 test_trading.py

**파일**: `backend/tests/test_trading.py`

- `RiskManager` mock에 신규 조건 반영
- `check_sell_order_allowed()` async 변환에 따른 mock 조정 (`AsyncMock` 사용)
- 신규 사유코드 4개 분류 테스트 추가

### 5.2 test_buy_order_executor.py

**파일**: `backend/tests/test_buy_order_executor.py`

- `BUY_GLOBAL_REJECT_REASONS` 확장에 따른 차순위 시도 분기 테스트
- 신규 사유코드가 전체 차단(break)으로 분류되는지 검증

### 5.3 test_settings_store.py

**파일**: `backend/tests/test_settings_store.py`

- 신규 리스크 키 범위 검증 테스트 추가:
  - `daily_loss_limit` 양수 입력 시 422
  - `daily_profit_limit` 음수 입력 시 422
  - `consecutive_loss_limit` 0/101 입력 시 422
  - `daily_loss_rate_limit` 양수 입력 시 422
  - `daily_profit_rate_limit` 음수 입력 시 422

### 5.4 test_risk_manager.py (신규 파일)

**파일**: `backend/tests/test_risk_manager.py` (신규)

RiskManager 확장 전용 테스트 파일:
- `risk_manager_on=False` 시 서킷브레이커만 동작
- `risk_block_buy_on=False` 시 매수 리스크 조건 스킵
- `risk_block_sell_on=False` 시 매도 리스크 조건 스킵
- 일일 손실 한도 초과 시 매수/매도 차단
- 일일 손실률 한도 초과 시 차단
- 일일 수익 한도 도달 시 차단
- 일일 수익률 한도 도달 시 차단
- 연속 손실 N회 시 차단
- `check_sell_order_allowed()` async 동작 검증

---

## 6. 아키텍처 원칙 부합 분석

### 6.1 P10 (SSOT)
- ✅ 설정: `integrated_system_settings_cache` 단일 진실 소스
- ✅ 손익: `trade_history` 단일 진실 소스. 별도 저장 없음
- ✅ 연속 손실: `trade_history.get_sell_history()` 파생. 중복 저장 없음

### 6.2 P15 (단일 주문 경로)
- ✅ `execute_buy()`/`execute_sell()` 경로 유지
- ✅ 새 조건을 `check_buy_order_allowed()`/`check_sell_order_allowed()` 내부에 추가
- ✅ 별도 주문 경로/분기 생성 없음

### 6.3 P16 (살아있는 경로)
- ✅ 새 조건이 `check_buy_order_allowed()`/`check_sell_order_allowed()`에 추가 → 자동으로 주문 경로에 배선
- ✅ `check_sell_order_allowed()`가 `check_sell_conditions()`에서 호출되므로 매도 경로에 자동 배선
- ✅ dead code 없음 — 모든 조건이 실제 주문 경로에서 호출됨

### 6.4 P17 (플래그 단일 소스)
- ✅ `risk_manager_on`, `risk_block_buy_on`, `risk_block_sell_on` 등 모든 플래그를 `integrated_system_settings_cache`에서만 관리
- ✅ 여러 곳에서 플래그 직접 수정 금지

### 6.5 P20 (폴백 금지)
- ✅ 0도 유효값이므로 `or 폴밭` 금지 — `int(_v if _v is not None else 기본값)` 패턴 사용
- ✅ 범위 검증 실패 시 422 차단 (silent pass 금지)
- ✅ 알 수 없는 사유는 보수적 전체 차단 분류 (기존 패턴 유지)

### 6.6 P21 (사용자 투명성)
- ✅ 모든 리스크 조건을 UI에서 제어 가능
- ✅ 차단 사유 WS 브로드캐스트 → 헤더 칩 실시간 표시
- ✅ 기존 `circuit_breaker_open`/`order_time_blocked` 패턴 재사용
- ✅ 사용자가 "왜 매매가 안 되지?" 의문 갖지 않도록 차단 사유 명시

### 6.7 P22 (데이터 정합성)
- ✅ 손익 집계는 `trade_history` 파생 데이터. 별도 저장 없음
- ✅ 연속 손실 카운트도 `trade_history` 파생. 중복 저장 없음
- ✅ 불일치 가능성 없음 — 단일 진실 소스에서 파생

### 6.8 P23 (일관성)
- ✅ 손익 기준 = 기존 `daily_loss_limit`과 동일(현금 기준)
- ✅ 사유코드 패턴 기존 `BUY_REJECT_RISK_*` 준수
- ✅ UI 공통 컴포넌트 재사용 (`createToggleLabelControlsRow`, `createMoneyInput`, `createNumInput`)
- ✅ 헤더 칩 패턴 기존 `circuitBreakerOpen`/`orderTimeBlocked`와 동일
- ✅ 용어 사전 준수 — "매수"/"매도" not "Buy"/"Sell", "종목" not "주식"

### 6.9 P24 (단순성)
- ✅ `RiskManager` 내부 조건 추가만. 새 클래스/서비스/경로 생성 없음
- ✅ 함수 50줄 이하 — `_get_today_pnl_and_principal()`, `_get_consecutive_loss_count()` 헬퍼로 분리
- ✅ 기존 UI 패턴 재사용 — 새 UI 인프라 구축 없음
- ✅ 불필요한 추상화 없음 — 직접 조건 체크

---

## 7. 영향 범위 요약

### 7.1 백엔드 (5파일 수정 + 1파일 신규)

| 파일 | 변경 유형 | 변경 내용 |
|------|----------|----------|
| `backend/app/core/settings_defaults.py` | 수정 | 신규 키 12개 기본값 추가 |
| `backend/app/core/engine_settings.py` | 수정 | 신규 키 타입 캐스팅 추가 |
| `backend/app/core/settings_store.py` | 수정 | 신규 키 범위 검증 추가 |
| `backend/app/services/risk_manager.py` | 수정 | `_sync_thresholds()` 확장, 헬퍼 2개 추가, `check_buy/sell_order_allowed()` 확장, `check_sell_order_allowed()` async 변환 |
| `backend/app/services/trading.py` | 수정 | 신규 사유코드 4개, `BUY_GLOBAL_REJECT_REASONS` 확장, `_map_risk_reason_to_code()` 확장, 매도 체크 `await` 추가, WS 브로드캐스트 추가 |
| `backend/tests/test_risk_manager.py` | 신규 | RiskManager 확장 전용 테스트 |

### 7.2 프론트엔드 (4파일 수정)

| 파일 | 변경 유형 | 변경 내용 |
|------|----------|----------|
| `frontend/src/pages/general-settings.ts` | 수정 | 자동매매 탭에 리스크 매니저 섹션 추가 |
| `frontend/src/stores/uiStore.ts` | 수정 | `riskBlockStatus` 상태 + 적용/해제 함수 |
| `frontend/src/binding.ts` | 수정 | `risk_block_status` WS 이벤트 핸들러 |
| `frontend/src/layout/header.ts` | 수정 | 리스크 차단 칩 추가 |
| `frontend/src/types/index.ts` | 수정 (선택) | 신규 키 타입 추가 |

### 7.3 테스트 (3파일 수정 + 1파일 신규)

| 파일 | 변경 유형 | 변경 내용 |
|------|----------|----------|
| `backend/tests/test_trading.py` | 수정 | RiskManager mock 조정, async 변환 반영 |
| `backend/tests/test_buy_order_executor.py` | 수정 | 신규 사유코드 분류 테스트 |
| `backend/tests/test_settings_store.py` | 수정 | 신규 키 범위 검증 테스트 |
| `backend/tests/test_risk_manager.py` | 신규 | RiskManager 확장 전용 테스트 |

---

## 8. 다단계 작업 분할 (3세션)

본 작업은 다단계 작업이므로 AGENTS.md 섹션4 "다단계 작업 워크플로우"에 따라 3세션으로 분할:

### 8.1 설계 세션 (본 세션)
- 본 설계서 작성
- 사용자 승인 획득

### 8.2 태스크 세션 (다음 세션)
- 본 설계서를 구현 단위 태스크로 분할
- `docs/plan_risk_manager_extension.md` 태스크 파일 작성
- 백엔드 → 프론트엔드 → 테스트 → 런타임 기동 검증 순서로 태스크 정의

### 8.3 구현 세션들 (이후 세션들)
- 태스크 파일 기반으로 단계별 구현
- 각 세션당 1단계 원칙 준수 (AGENTS.md 섹션3 규칙 0-1)
- 단계 완료 시 검증 + 커밋 + HANDOVER.md 갱신

---

## 9. 사용자 확인 사항

### 9.1 UI 기준 동작 설명 (규칙 0-4 준수)

**변경 전 화면**:
- 일반설정 → 자동매매 탭에 자동매매/자동매수/자동매도/체결불가시간대 토글만 존재
- 리스크 매니저 설정이 백엔드에만 있어 사용자가 조작 불가
- 리스크 차단 시 화면에 표시 없음

**변경 후 화면**:
- 자동매매 탭에 "전역매매설정 (리스크 매니저)" 섹션 신규 추가
- 리스크 매니저 토글 ON 시 아래 6개 설정 활성화:
  1. 일일 손실 한도 (금액 입력, 음수, 기본 -50만원)
  2. 일일 손실률 한도 (토글 + %, 기본 -5%)
  3. 일일 수익 한도 (토글 + 금액, 기본 +50만원)
  4. 일일 수익률 한도 (토글 + %, 기본 +5%)
  5. 연속 손실 횟수 (토글 + 횟수, 기본 3회)
  6. 매수 차단/매도 차단 체크박스 (매수 기본 ON, 매도 기본 OFF)
- 리스크 차단 발생 시 화면 상단에 빨간 칩 표시: "⚠ 리스크 차단(매수): 일일 손실 한도 초과"
- 칩 클릭 시 수동 해제 가능

**사용자가 확인할 수 있는 영향**:
- 목표 수익 도달 시 자동으로 매수/매도 중단 (설정 ON 시)
- 일일 손실 한도 도달 시 자동으로 매수 중단
- 연속 손실 N회 시 자동으로 매수/매도 중단
- 차단 시 화면 상단 칩으로 즉시 인지 가능

### 9.2 승인된 설계 결정 (사용자 승인 완료)

1. ✅ 수익금/손실금 기준: 당일 실현손익(현금 기준, 수수료/세금 포함) — 기존 `daily_loss_limit`과 동일
2. ✅ 매도 차단 기본값: `risk_block_sell_on` 기본 False (사용자 명시적 ON 필요)
3. ✅ 연속 손실 기준: 최근 매도 거래의 `realized_pnl`(순수 차익)이 음수인 건수
4. ✅ 리스크 매니저 전체 토글: `risk_manager_on` 별도 두어 모든 리스크 조건 한 번에 끄기 가능

---

## 10. 위험 및 주의사항

### 10.1 매도 차단 위험
- 손실 상태에서 매도 차단 시 손실 확대 가능
- 수익 상태에서 매도 차단 시 수익 확정 방해
- → `risk_block_sell_on` 기본값 False로 사용자 명시적 활성화 유도
- → UI 설명 문구에 위험성 명시

### 10.2 `check_sell_order_allowed()` async 변환
- 동기 → async 변환 시 호출부 모두 `await` 추가 필요
- 현재 단일 호출부만 존재(`trading.py:682-683`)하므로 영향 최소
- 테스트 mock을 `AsyncMock`으로 변경 필요

### 10.3 성능 고려
- 매수/매도 시도 시마다 `trade_history` 조회 발생
- `get_total_realized_pnl()` + `get_buy_history()` + `get_sell_history()` 3회 조회
- 모두 메모리 조회(`_ensure_loaded()` 후 메모리 리스트 순회)이므로 DB I/O 없음
- 주문 빈도(초당 수십 건 아님)를 고려하면 성능 이슈 없음

### 10.4 기존 `max_daily_loss_limit` 키 호환
- 기존 `max_daily_loss_limit` 키는 유지 (레거시 호환)
- 신규 `daily_loss_limit` 키를 UI 노출용으로 추가
- `RiskManager._sync_thresholds()`에서 두 키 모두 인식: `daily_loss_limit` 우선, 없으면 `max_daily_loss_limit` 폴백 (정상 마이그레이션)
