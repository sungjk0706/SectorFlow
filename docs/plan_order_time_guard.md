# 태스크 파일: 시장가 주문 중단 시간대 게이트 (Order Time Guard)

> **상태**: 2세션(심층 사전조사 + 태스크 파일 작성) 완료 · 구현 승인 대기
> **작성일**: 2026-07-17
> **설계서**: `docs/architecture_order_time_guard_design.md` (1세션 완료)
> **관련 원칙**: P10(SSOT) · P13(설정 메모리 상주) · P15(단일 주문 경로) · P16(살아있는 경로) · P17(플래그 단일 소스) · P20(폴백 금지) · P21(사용자 투명성) · P23(일관성) · P24(단순성)

---

## 1. 사전조사 결과 (AGENTS.md 섹션3 규칙 0-2 4항목)

### 1-1. 의존성 (전체 코드베이스 검색)

| 자산 | 위치 | 역할 | 본 작업에서의 활용 |
|---|---|---|---|
| `KRX_INACTIVE_PHASES` | `daily_time_scheduler.py:227` | frozenset 12개 KRX 비활성 phase | **재사용** — `is_order_blocked_by_time()` 내부 |
| `NXT_ACTIVE_PHASES` | `daily_time_scheduler.py:233` | frozenset 6개 NXT 활성 phase | **재사용** — `is_order_blocked_by_time()` 내부 |
| `is_nxt_enabled(stk_cd)` | `engine_symbol_utils.py:11` | `state.master_stocks_cache`에서 NXT 중복상장 여부 조회 | **재사용** — KRX 비활성+NXT 활성 시 종목별 분기 |
| `is_nxt_only_window()` | `daily_time_scheduler.py:260` | KRX 비활성+NXT 활성 판별 (패턴 원형) | **패턴 참조** — 신규 함수와 동일 구조 |
| `is_krx_after_hours()` | `daily_time_scheduler.py:298` | KRX 장외 판별 (기존) | **유지** — `buy_order_executor.py:110` 기존 동작 보존 |
| `_broadcast(event_type, data)` | `engine_account_notify.py:69` | WS 이벤트 브로드캐스트 | **재사용** — `order_time_blocked` 이벤트 |
| `createToggleBtn()` | `frontend/src/components/common/setting-row.ts` | 설정 토글 공통 컴포넌트 | **재사용** — 설정 토글 (Step 6) |
| `circuitBreakerOpen` 패턴 | `uiStore.ts:69` / `binding.ts:322` / `header.ts:251` | 서킷브레이커 칩+바인딩+상태 | **패턴 참조** — `orderTimeBlocked` 동일 구조 |
| `_kst_now()` | `daily_time_scheduler.py` (내부) | KST 현재 시각 반환 | **재사용** — ±5초 버퍼 초 단위 계산 |

**외부 참조 없음**: `KRX_INACTIVE_PHASES`·`NXT_ACTIVE_PHASES`는 `daily_time_scheduler.py` 내부 + `is_nxt_only_window()`에서만 사용. 신규 함수 추가 시 외부 파일 영향 없음.

### 1-2. 영향범위

| 계층 | 파일 | 변경 유형 | 세션 |
|---|---|---|---|
| 백엔드 | `daily_time_scheduler.py` | 신규 함수 `is_order_blocked_by_time()` + ±5초 버퍼 | 3세션 |
| 백엔드 | `settings_defaults.py` | `order_time_guard_on: True` 설정 키 추가 | 3세션 |
| 백엔드 | `trading.py` | `_is_order_time_blocked()` 헬퍼 + execute_buy/execute_sell 게이트 배선 | 4세션 |
| 백엔드 | `engine_ws_dispatch.py` | `order_time_blocked` WS 이벤트 브로드캐스트 | 5세션 |
| 프론트엔드 | `binding.ts` | `order_time_blocked` 이벤트 바인딩 | 5세션 |
| 프론트엔드 | `uiStore.ts` | `orderTimeBlocked` 상태 추가 | 5세션 |
| 프론트엔드 | `general-settings.ts` | "체결 불가 시간대 주문 차단" 토글 | 6세션 |
| 프론트엔드 | `header.ts` | 노란색 "주문 일시중단(동시호가)" 칩 | 6세션 |
| 테스트 | `test_daily_time_scheduler.py` | `is_order_blocked_by_time()` 단위 테스트 추가 | 3세션 |
| 테스트 | `test_buy_order_executor.py` | **변경 없음** — 기존 `is_krx_after_hours` mock 유지 (기존 함수 유지) | — |

### 1-3. 아키텍처 원칙 부합 여부

| 원칙 | 부합 | 비고 |
|---|---|---|
| P10 (SSOT) | ✅ | `market_phase` 단일 기준, 기존 상수 재사용, 새 시간 상수 생성 없음 |
| P13 (설정 메모리 상주) | ✅ | `order_time_guard_on`을 `integrated_system_settings_cache`에서 조회 — 틱 단계 DB 조회 없음 |
| P15 (단일 주문 경로) | ✅ | `execute_buy()`/`execute_sell()` 내부에만 게이트 배선 |
| P16 (살아있는 경로) | ✅ | 내부 체크가 실제 주문 전송 전 호출 — 외부 사전 필터는 성능 최적화로 유지 |
| P17 (플래그 단일 소스) | ✅ | `order_time_guard_on`은 `integrated_system_settings_cache`에서만 관리 |
| P20 (폴백 금지) | ✅ | `market_phase` 빈 문자열 시 `logger.error` + False 반환 (기존 패턴) |
| P21 (사용자 투명성) | ✅ | 차단 시 헤더 칩 + 설정 토글 + 차단 로그 |
| P22 (데이터 정합성) | ✅ | 파생 데이터 중복 저장 없음 — phase에서 실시간 산출 |
| P23 (일관성) | ✅ | 기존 `is_nxt_only_window()` 패턴, `createToggleBtn()`, 서킷브레이커 칩 패턴 재사용 |
| P24 (단순성) | ✅ | 시간 기반 — 별도 재개 로직 불필요, 함수 50줄 이하 |

### 1-4. 기존 공통 자산 확인 (P23 사전 절차)

신규 함수/컴포넌트/상수 구현 전 기존 공통 자산 검색 완료:
- **백엔드**: `KRX_INACTIVE_PHASES`·`NXT_ACTIVE_PHASES`·`is_nxt_enabled()`·`_broadcast()`·`_kst_now()` 전부 재사용 확정. 새 시간 상수·새 브로드캐스트 함수 생성 없음.
- **프론트엔드**: `createToggleBtn()`·`circuitBreakerOpen` 패턴·`COLOR` 표준 색상 재사용 확정. 새 공통 컴포넌트 생성 없음.
- **동일 기능 중복 생성 없음**: `is_order_blocked_by_time()`은 기존 `is_krx_after_hours()`와 다른 목적(매수·매도 통합 + NXT 분기 + 동시호가 2구간 추가)이므로 별개 함수. 기존 함수는 유지.

---

## 2. 설계서 대비 심층 발견사항 (구현 세션 전 반드시 반영)

### 2-1. ★ `_to_trade_settings` 설정 키 누락 (중요 — 토글 무효화 위험)

**발견**: `trading.py:694` `_to_trade_settings()` 반환 dict에 `order_time_guard_on` 키가 없음.

**영향**:
- `execute_buy` (L112): `settings = self._to_trade_settings(self.get_settings_fn())` → `settings.get("order_time_guard_on", True)`가 **항상 True** (토글 OFF 불가 → P17 위반)
- `execute_sell` (L448): `trade_settings` = `_to_trade_settings` 출력 → 동일 문제

**해결안 (확정)**: 헬퍼 `_is_order_time_blocked(stk_cd, raw_settings)`에 **raw engine_settings** 전달:
- `execute_buy`: 이미 보유 중인 `raw_all = self.get_settings_fn()` (L113) 전달
- `execute_sell`: 인자 `base_settings` (raw engine_settings, L457) 전달
- 헬퍼 내부: `raw_settings.get("order_time_guard_on", True)` 조회 → 토글 정상 동작

**설계서 보완**: 설계서 4-3/4-4의 `_is_order_time_blocked(stk_cd, settings)` 의사코드에서 `settings`는 raw engine_settings 의미. 4세션 구현 시 `raw_all`(buy) / `base_settings`(sell) 전달.

**기각안**: `_to_trade_settings`에 `order_time_guard_on` 통과 추가 — trade_settings shape 변경 + P23 일관성 검토 범위 확대. raw settings 전달이 최소 변경.

### 2-2. ±5초 버퍼 구현 접근 (Step 1 내부)

**환경**: `calc_timebased_market_phase()`는 분 단위 산정 (`t = hour*60 + minute`) → `state.market_phase`는 분 단위 갱신. 09:00:02에 이미 "정규장" phase.

**구현 접근 (확정)**: 차단 상태가 전환되는 경계 시각(초 단위) 집합 정의 → 현재 시각이 경계 ±5초 내면 **무조건 차단(True)** 반환 (양방향 안전 측).

**경계 목록 (block↔allow 전환점, 초 단위 = hour*3600+minute*60+second)**:
| 경계 | 시각 | 전환 | 차단 의미 |
|---|---|---|---|
| NXT 프리마켓 시작 | 08:00:00 | allow→block (KRX 단독) | KRX 단독 종목 차단 시작 |
| KRX 정규장 시작 | 09:00:00 | block→allow (KRX) | 5초 대기 후 허용 (체결 안정) |
| NXT 메인마켓 시작 | 09:00:30 | block→allow (NXT) | 이미 `calc_timebased_market_phase` 초 단위 처리 → 중복 검토 |
| 종가 동시호가 시작 | 15:20:00 | allow→block (양쪽) | 5초 전부터 차단 |
| NXT 애프터마켓 시작 | 15:40:00 | block→block (KRX) / block→allow (NXT) | NXT 종목 5초 대기 |
| 장마감 | 20:00:00 | allow→block (양쪽) | 5초 전부터 차단 |

**단순화 (P24)**: 경계 ±5초 내면 무조건 `True` 반환. 방향성 판단 제거 — "안전 측" 원칙으로 단순화. 정규장 진입(09:00) 시 5초 지연은 체결 안정성에 기여.

**NXT 09:00:30 예외**: `calc_timebased_market_phase()`가 이미 `now.second < NXT_MAINMARKET_START_SECOND`로 초 단위 처리 중 (L159). 버퍼 경계 집합에서 09:00:30 제외 검토 — 중복 차단 방지. 3세션 구현 시 확정.

**버퍼 상수**: `ORDER_TIME_BUFFER_SEC = 5` (새 상수 — 시간 상수 아님, 버퍼 전용이므로 P10 위반 아님).

### 2-3. execute_sell 삽입 위치 확인

- L461: `if not trade_settings.get("is_sell_auto", False): return` 직후
- L464: `order_type = "시장가"` 선언 전 — OK
- **주의**: `trade_settings`는 `_to_trade_settings` 출력 → `order_time_guard_on` 없음 → 2-1 해결안대로 `base_settings` 사용

### 2-4. WS 이벤트 브로드캐스트 시점 (Step 5)

**설계서 명확화**: `order_time_blocked` 이벤트를 언제 브로드캐스트할지 확정.

**확정안**: `_broadcast_market_phase()` (페이즈 갱신 시 10초 주기 브로드캐스트)에서 `is_order_blocked_by_time()` 상태를 함께 산정하여 **별도 이벤트** `order_time_blocked` 브로드캐스트.
- 시간 기반이므로 10초 주기면 충분 (P11 폴링 아님 — 페이즈 갱신 이벤트에 탑승)
- 페이로드: `{"blocked": bool, "reason": str}` — reason은 phase 기반 산정 ("동시호가 시간대" / "장외 시간대" / "")
- `blocked: false` 시 자동 해제 (P24 — 별도 해제 로직 없음)

**기각안**: 기존 `market-phase` 이벤트에 필드 추가 — 이벤트 페이로드 확장은 P23 일관성 검토 범위 확대. 별도 이벤트가 기존 `krx-circuit-breaker` 패턴과 일관.

### 2-5. 기존 `plan_order_suspension_by_time.md` 잔존 (규칙 11)

**발견**: `docs/plan_order_suspension_by_time.md` (15930바이트)가 설계서에 "통합됨" 기록되었으나 파일 잔존.
- 규칙 11(계획서 삭제) 위반 소지
- 본 태스크 파일 작성 완료 후 사용자 승인 시 삭제 권장 (3세션 시작 전 또는 본 세션 종료 시)

---

## 3. 세션 분할 확정 (설계서 섹션 6 + 본 조사 반영)

| 세션 | 작업 범위 | 파일 | 검증 |
|---|---|---|---|
| **3세션** | Step 1 (차단 판별 함수 + ±5초 버퍼) + Step 4 (설정 키) | `daily_time_scheduler.py` + `settings_defaults.py` + `test_daily_time_scheduler.py` | 단위 테스트 (시간대별·경계·NXT 분기·토글) |
| **4세션** | Step 2 (execute_buy 게이트) + Step 3 (execute_sell 게이트) + Step 5 (헬퍼) | `trading.py` | 런타임 기동 + 차단 로그 확인 |
| **5세션** | Step 7 (WS 이벤트) + Step 8 (바인딩) | `engine_ws_dispatch.py` + `binding.ts` + `uiStore.ts` | WS 이벤트 수신 확인 |
| **6세션** | Step 6 (설정 토글) + Step 9 (헤더 칩) | `general-settings.ts` + `header.ts` | 브라우저 확인 |

> 각 세션 종료 시 커밋 + HANDOVER.md 갱신 + 사용자 보고 (AGENTS.md 섹션3 규칙 0-1)

---

## 4. 각 세션별 태스크 상세

### 4-1. 3세션: 차단 판별 함수 + 설정 키

**Step 1 — `daily_time_scheduler.py` 신규 함수**:
```python
ORDER_TIME_BUFFER_SEC = 5  # ±5초 버퍼 (주문 체크 시점 전용)

# 차단 상태 전환 경계 (초 단위) — block↔allow 전환점
_ORDER_TIME_BOUNDARIES_SEC: frozenset[int] = frozenset({
    8 * 3600,           # 08:00:00 NXT 프리마켓 시작 (KRX 단독 차단 시작)
    9 * 3600,           # 09:00:00 KRX 정규장 시작 (5초 대기)
    15 * 3600 + 20 * 60, # 15:20:00 종가 동시호가 시작 (양쪽 차단)
    15 * 3600 + 40 * 60, # 15:40:00 NXT 애프터마켓 시작 (KRX 단독 차단)
    20 * 3600,          # 20:00:00 장마감 (양쪽 차단)
})  # 09:00:30은 calc_timebased_market_phase가 이미 초 단위 처리 → 제외

def is_order_blocked_by_time(stk_cd: str) -> bool:
    """체결 불가 시간대 주문 차단 판별 (매수·매도 공통).

    SSOT: state.market_phase 기반. 기존 is_nxt_only_window() 패턴과 동일 구조.
    ±5초 버퍼: 경계 시각 ±5초 내면 무조건 차단 (안전 측, P24 단순화).
    """
    mp = state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: krx=%r, nxt=%r — 시간 기반 초기화 누락 가능", krx, nxt)
        return False  # P20 폴백 금지 — 빈 문자열은 차단하지 않고 에러 로그

    # ±5초 버퍼 — 경계 근처면 무조건 차단
    now = _kst_now()
    now_sec = now.hour * 3600 + now.minute * 60 + now.second
    for boundary in _ORDER_TIME_BOUNDARIES_SEC:
        if abs(now_sec - boundary) <= ORDER_TIME_BUFFER_SEC:
            return True

    # 본 판별 — 기존 is_nxt_only_window()와 동일 구조
    if krx in KRX_INACTIVE_PHASES:
        if nxt in NXT_ACTIVE_PHASES:
            from backend.app.services.engine_symbol_utils import is_nxt_enabled
            return not is_nxt_enabled(stk_cd)  # NXT 종목 허용, KRX 단독 차단
        return True  # 양쪽 비활성 — 전부 차단
    return False  # KRX 활성 — 허용
```

**Step 4 — `settings_defaults.py` 설정 키**:
```python
# DEFAULT_USER_SETTINGS 내 "ui_price_flash_on" 아래에 추가
"order_time_guard_on": True,  # 체결 불가 시간대 주문 차단 (기본 ON)
```

**단위 테스트 — `test_daily_time_scheduler.py` 신규 클래스 `TestIsOrderBlockedByTime`**:
- 08:00~08:50 (KRX 장전 대기 + NXT 프리마켓): KRX 단독 종목 차단 / NXT 종목 허용
- 08:50~09:00 (KRX 시가 동시호가 + NXT 정규장 준비): 양쪽 차단
- 09:00~15:20 (KRX 정규장 + NXT 메인마켓): 양쪽 허용
- 15:20~15:40 (KRX 종가 동시호가/체결 정산 + NXT 조기 마감/단일가): 양쪽 차단
- 15:40~20:00 (KRX 장후 시간외 + NXT 애프터마켓): KRX 단독 차단 / NXT 종목 허용
- 20:00~24:00 (양쪽 장마감): 양쪽 차단
- ±5초 버퍼 경계 (08:59:55, 09:00:00, 09:00:05, 15:19:55, 15:20:05 등)
- 빈 문자열 phase 시 False 반환 (P20)
- `is_nxt_enabled` mock으로 NXT 종목/KRX 단독 종목 분기 검증

### 4-2. 4세션: execute_buy/execute_sell 게이트 + 헬퍼

**Step 5 — `trading.py` 헬퍼 (동기)**:
```python
def _is_order_time_blocked(self, stk_cd: str, raw_settings: dict) -> bool:
    """체결 불가 시간대 주문 게이트 헬퍼 (토글 + 시간 판별).

    raw_settings: raw engine_settings (order_time_guard_on 포함).
    동기 함수 — 시간 계산만 수행 (P1-P3 async 일관성 위반 아님).
    """
    if not raw_settings.get("order_time_guard_on", True):
        return False  # 토글 OFF — 차단 없음
    from backend.app.services.daily_time_scheduler import is_order_blocked_by_time
    return is_order_blocked_by_time(stk_cd)
```

**Step 2 — `execute_buy` 게이트 (L134 직후, 재매수 차단 전)**:
```python
# ── 체결 불가 시간대 주문 게이트 (P15 단일 경로, P16 살아있는 경로) ──
if self._is_order_time_blocked(stk_cd, raw_all):
    stk_nm = data_manager.get_stock_name(stk_cd, access_token)
    logger.info("[매매] [주문차단] %s(%s) 체결 불가 시간대 — 동시호가/장외", stk_nm, stk_cd)
    return False
```
- `raw_all` (L113) 전달 — 2-1 해결안

**Step 3 — `execute_sell` 게이트 (L462 직후, `order_type` 선언 전)**:
```python
# ── 체결 불가 시간대 주문 게이트 — 매도 동일 적용 (P15/P16) ──
if self._is_order_time_blocked(stk_cd, base_settings):
    logger.info("[매매] [주문차단] %s(%s) 체결 불가 시간대 — 매도 중단", stk_nm, stk_cd)
    return
```
- `base_settings` (L457 인자) 전달 — 2-1 해결안

**검증**: 런타임 기동 (테스트모드) + 동시호가 시간대 매수/매도 시도 시 차단 로그 확인 + 정규장 시간대 주문 정상 통과.

### 4-3. 5세션: WS 이벤트 + 바인딩

**Step 7 — `engine_ws_dispatch.py` (또는 `_broadcast_market_phase` 내부)**:
- `_broadcast_market_phase()`에서 페이즈 갱신 시 `is_order_blocked_by_time()` 상태 산정
- 별도 이벤트 `order_time_blocked` 브로드캐스트: `{"blocked": bool, "reason": str}`
- reason 산정: KRX 비활성+NXT 활성 → "NXT 전용 구간 (KRX 단독 종목 차단)" / 양쪽 비활성 → "동시호가/장외 시간대" / KRX 활성 → ""

**Step 8 — `binding.ts` + `uiStore.ts`**:
- `uiStore.ts`: `orderTimeBlocked: { reason: string } | null` 상태 추가 (초기값 null, reset 시 null)
- `uiStore.ts`: `applyOrderTimeBlocked(data)` / `clearOrderTimeBlocked()` 함수 추가 (기존 `applyCircuitBreakerOpen` 패턴)
- `binding.ts`: `pricesClient.onEvent('order_time_blocked', ...)` 바인딩 추가

**검증**: WS 이벤트 수신 확인 — 차단 진입 시 `blocked: true`, 시간대 종료 시 `blocked: false`.

### 4-4. 6세션: 설정 토글 + 헤더 칩

**Step 6 — `general-settings.ts` 자동매매 탭**:
- 자동매도 행 아래에 "체결 불가 시간대 주문 차단" 토글 추가
- `createToggleBtn()` 재사용, 설정 키 `order_time_guard_on`, 기본 ON
- 설명: "동시호가·장외 시간대에 시장가 주문 자동 중단 (KRX 단독 종목만, NXT 종목은 NXT 거래 시간에 허용)"

**Step 9 — `header.ts` 헤더 칩**:
- 노란색 "주문 일시중단(동시호가)" 칩 추가 (기존 `circuitBreakerChip` 패턴, 색상/메시지로 구분)
- `orderTimeBlocked` 상태 구독 — `null`이면 숨김, `{reason}`이면 표시
- `COLOR.warning`/`COLOR.warningBg` 사용 (표준 색상, P23)

**검증**: 브라우저 확인 — 토글 ON/OFF 동작, 헤더 칩 표시/해제, 토글 OFF 시 차단 무효화.

---

## 5. 위험 및 주의점 (설계서 섹션 9 + 본 조사 추가)

1. **기존 `is_krx_after_hours()` 수정 시 영향 범위** — 기존 함수 유지, 신규 함수 추가 (설계서 9-1)
2. **매도 차단 시 손절 기회 상실** — 동시호가 10분간 매도 차단, 헤더 칩으로 사전 안내 (설계서 9-2)
3. **±5초 버퍼 경계 오차** — 분 단위 phase + 초 단위 버퍼 별도 계산 (설계서 9-3, 본 조사 2-2)
4. **`is_nxt_enabled()` 의존** — `state.master_stocks_cache` 조회, 기존 함수 재사용 (설계서 9-4)
5. **★ `_to_trade_settings` 설정 키 누락** — raw settings 전달로 해결 (본 조사 2-1) — 4세션 구현 시 필수 반영
6. **NXT 09:00:30 경계 중복** — `calc_timebased_market_phase` 이미 초 단위 처리, 버퍼 경계 집합에서 제외 검토 (본 조사 2-2) — 3세션 구현 시 확정
7. **기존 `plan_order_suspension_by_time.md` 잔존** — 규칙 11, 삭제 권장 (본 조사 2-5)

---

## 6. 승인 대기 항목

- **3세션 진행**: Step 1 (차단 판별 함수 + ±5초 버퍼) + Step 4 (설정 키) — 사용자 "진행" 지시 시 시작
- **기존 `plan_order_suspension_by_time.md` 삭제**: 규칙 11 — 사용자 승인 시 본 세션 또는 3세션 시작 전 삭제

---

## 7. 참조

- **설계서**: `docs/architecture_order_time_guard_design.md` (1세션)
- **전신 문서**: `docs/plan_order_suspension_by_time.md` (사전조사 + 사용자 결정 — 설계서로 통합됨, 잔존)
- **아키텍처 원칙**: `ARCHITECTURE.md` 제1부 P10/P13/P15/P16/P17/P20/P21/P22/P23/P24
- **수행 규칙**: `AGENTS.md` 섹션3 규칙 0/0-1/0-2 + 섹션2 코드 수정 시 점검 체크리스트
