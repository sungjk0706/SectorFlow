# 텔레그램 기간별 손익 명령어 날짜 범위 SSOT 위반 수정 설계안

> **상태**: 설계 완료 / 구현 승인 완료 (사용자 승인 — 핸드오버 "다음 세션 진행 대기" 항목)
> **작성일**: 2026-07-31
> **범위**: `telegram_bot.py` 기간별 손익 명령어(당일/5일/당월/누적)의 날짜 범위 산정을 `get_chart_reference_trading_day()` 기반으로 통일 + 계좌 요약 누적 수익률 분모를 매수원금 기반으로 통일
> **범위 외**: 프론트엔드 TS `isPreOpenPhase()`/`getTradingToday()` 독자 구현을 백엔드 phase 상태 참조로 전환 (4단계 — 별도 설계안·별도 세션)

---

## 1. 근본 원인

### 1.1 P10 SSOT 위반 — "거래일 기준 오늘" 두 개의 독립 구현

"거래일 기준 오늘/5일/당월" 개념이 **프론트엔드(phase 기반)와 백엔드 텔레그램(캘린더 기반)에 독립 구현**되어 있다.

| 계층 | 함수 | 기준 | 위치 |
|------|------|------|------|
| 프론트엔드 | `getTradingToday()` | `uiStore.marketPhase` 기반 (08:00 프리마켓 개시 판정) | `frontend/src/utils/date.ts:43-49` |
| 백엔드 텔레그램 | `get_kst_today()` | 캘린더 날짜 (시각 무관, 무조건 오늘) | `telegram_bot.py:665` |
| 백엔드 dailySummary | `get_chart_reference_trading_day()` | 08:00 프리마켓 개시 기준 (phase 기반과 동일 의미) | `trading_calendar.py:384-411` |

**핵심**: 백엔드 내부에 이미 프론트 `getTradingToday()`와 동일 의미의 함수 `get_chart_reference_trading_day()`가 존재하며, `trade_history.py:626` `get_daily_summary()`가 이를 사용 중이다. 즉 **백엔드 SSOT 함수가 이미 살아있는 경로에 배선되어 있으나, 텔레그램 명령어만 이를 우회하여 `get_kst_today()`를 독자 사용**하고 있다.

### 1.2 차이 발생 시나리오

```
목요일 06:47 (08:00 프리마켓 개시 전)
├─ 프론트 getTradingToday()           → 수요일 (직전 거래일) ← dailySummary 기준
├─ 백엔드 get_chart_reference_trading_day() → 수요일 (직전 거래일) ← dailySummary 기준
└─ 텔레그램 get_kst_today()           → 목요일 (오늘 캘린더 날짜) ← 손익 명령어 기준
```

→ 사용자가 06:47에 텔레그램 "당일 손익" 조회 시, 프론트 수익현황 페이지(수요일 기준)와 텔레그램(목요일 기준)이 다른 결과를 표시.

### 1.3 누적 수익률 분모 불일치 (3단계 — 별개 이슈)

`_build_account_brief_lines` 누적 수익률 분모가 모드별로 상이하며, 프론트엔드와 불일치:

| 계층 | 테스트모드 분모 | 실전모드 분모 | 위치 |
|------|---------------|--------------|------|
| 텔레그램 | `accumulated_investment ?? initial_deposit` | `realized_buy_total` | `telegram_bot.py:143-146` |
| 프론트 | `buyTotal` (aggregatePnl 매수원금 합) | `buyTotal` (동일) | `profit-shared.ts:286` → `profit-math.ts:237-244` |

→ 테스트모드에서 텔레그램은 "누적투자금" 분모, 프론트는 "매수원금 합" 분모를 사용 → 수익률 숫자 상이. 주석 "프론트엔드와 동일"(142줄)이 실제와 불일치 (P23 위반).

### 1.4 손익금 공식 자체는 일치 (DB 검증 완료)

DB 107건 전부 `(total_amt - buy_total_amt) == realized_pnl` 성립. 즉 **손익금 계산은 SSOT 준수**, **날짜 범위 산정과 분모만 상이**. 본 설계안은 이 두 가지만 다룬다.

---

## 2. 현재 상태 vs 목표

### 2.1 날짜 범위 산정 (1-2단계)

#### 현재 상태 (`telegram_bot.py:648-687` `_cmd_period_pnl`)

```
당일: today_only=True → _query_history() 내부 date.today() 사용 (533/578줄)
5일:  get_recent_trading_days(5) → from_date=None → get_kst_today() 기준 (426줄)
당월: _date(today.year, today.month, 1) ~ today.isoformat() (679-680줄)
누적: date_from/date_to 미지정 (전체) — 변경 없음
```

#### 목표 (1-2단계)

```
당일: date_from=date_to=get_chart_reference_trading_day().isoformat()
5일:  get_recent_trading_days(5, from_date=get_chart_reference_trading_day())
당월: _date(ref.year, ref.month, 1).isoformat() ~ ref.isoformat()
누적: date_from/date_to 미지정 (전체) — 변경 없음
```

### 2.2 누적 수익률 분모 (3단계)

#### 현재 상태 (`telegram_bot.py:142-147`)

```python
# 수익률 분모: 테스트모드=누적투자금(투자원금 대비), 실전모드=매수총액 합계 (프론트엔드와 동일)
if is_test:
    cum_denominator = int(snap.get("accumulated_investment", 0) or snap.get("initial_deposit", 0) or 0)
else:
    cum_denominator = realized_buy_total
```

#### 목표 (3단계)

```python
# 수익률 분모: 매수원금 합계 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT)
cum_denominator = realized_buy_total
```

양 모드 공통으로 `realized_buy_total` 사용. `accumulated_investment`/`initial_deposit` 분모 사용 제거. 주석 정정.

---

## 3. 수정 계획

### 3.1 1단계: `_cmd_period_pnl` 당일/당월 `get_chart_reference_trading_day` 기반 교체

**대상 파일**: `backend/app/services/telegram_bot.py` (648-687줄)

**수정 내용**:

1. **import 변경** (663줄):
   - `from backend.app.core.trading_calendar import get_kst_today, get_recent_trading_days`
   - → `from backend.app.core.trading_calendar import get_chart_reference_trading_day, get_recent_trading_days`

2. **당일 분기** (668-669줄):
   - `today_only=True` 제거
   - `ref = get_chart_reference_trading_day(); ref_iso = ref.isoformat()`
   - `await _compute_period_pnl("당일", date_from=ref_iso, date_to=ref_iso, is_test=_is_test)`

3. **당월 분기** (678-680줄):
   - `today` → `ref` 기반
   - `month_start = _date(ref.year, ref.month, 1).isoformat()`
   - `date_to=ref_iso`

4. **`get_kst_today()` 사용 제거** (665-666줄):
   - `today = get_kst_today()` / `today_iso = today.isoformat()` 제거
   - `ref` / `ref_iso` 변수로 대체

**`trade_history.py` `today_only` 분기 처리**:

`_query_history`(524-542줄)와 `get_realized_pnl_summary`(557-588줄)의 `today_only=True` 분기가 `date.today()`(533/578줄)를 사용. 1단계에서 `today_only=True` 호출 자체를 제거하므로, **`today_only` 분기 코드는 dead path가 됨**.

**결정**: `today_only` 파라미터와 분기 코드를 제거하지 않고 유지. 이유:
- `today_only`는 `get_buy_history`/`get_sell_history`/`get_total_realized_pnl` 공개 API 시그니처의 일부
- 다른 호출자가 있을 수 있으므로, 본 설계안 범위(텔레그램)에서는 시그니처 변경 최소화
- 단, `today_only` 분기의 `date.today()`를 `get_chart_reference_trading_day()` 기반으로 변경하는 것은 **별도 검토 필요** (본 설계안 범위 외 — `today_only`를 사용하는 다른 호출자 조사 선행)

→ **1단계는 텔레그램 `_cmd_period_pnl`의 `today_only=True` 호출을 `date_from=date_to=ref_iso`로 교체하는 것만 수행. `trade_history.py`는 수정하지 않음.**

### 3.2 2단계: `get_recent_trading_days(5)` `from_date` 주입

**대상 파일**: `backend/app/services/telegram_bot.py` (671줄)

**수정 내용**:

- `recent5 = get_recent_trading_days(5)`
- → `recent5 = get_recent_trading_days(5, from_date=get_chart_reference_trading_day())`

`trade_history.py:626` `get_daily_summary()`의 `get_recent_trading_days(days, from_date=get_chart_reference_trading_day())`와 동일 패턴 (P23 일관성).

**1단계에서 이미 `ref = get_chart_reference_trading_day()` 변수를 선언하므로, 2단계는 `from_date=ref` 재사용** (중복 호출 방지 — P24 단순성).

### 3.3 3단계: `_build_account_brief_lines` 누적 수익률 분모 통일

**대상 파일**: `backend/app/services/telegram_bot.py` (114-163줄)

**수정 내용**:

1. **분모 계산 단순화** (142-147줄):
   ```python
   # 수익률 분모: 매수원금 합계 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT)
   cum_denominator = realized_buy_total
   ```
   - `is_test` 분기 제거
   - `snap.get("accumulated_investment", 0) or snap.get("initial_deposit", 0)` 제거

2. **주석 정정** (142줄):
   - 기존: `# 수익률 분모: 테스트모드=누적투자금(투자원금 대비), 실전모드=매수총액 합계 (프론트엔드와 동일)`
   - 신규: `# 수익률 분모: 매수원금 합계 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT)`
   - 기존 주석 "프론트엔드와 동일"이 실제와 불일치했던 것을 정정 (P23)

3. **docstring 정정** (115-123줄):
   - 122줄 `누적 실현 손익금/수익률 추가 — 프론트엔드 aggregatePnl과 동일 공식 (P21).`는 공식(손익금)은 맞으나 분모 설명 보강 필요
   - 분모가 매수원금 합계로 통일되었음을 명시

---

## 4. 테스트 영향 분석

### 4.1 `test_telegram_bot.py` `TestCmdPeriodPnl` (1038-1140줄)

| 테스트 | 현재 patch | 수정 후 patch | 검증값 변경 |
|--------|-----------|---------------|------------|
| `test_today_period` (1047) | `get_kst_today` → 2026-07-31 | `get_chart_reference_trading_day` → 2026-07-31 | `today_only=True` 검증 → `date_from=="2026-07-31"` + `date_to=="2026-07-31"` 검증으로 변경 |
| `test_5day_period` (1063) | `get_kst_today` + `get_recent_trading_days` | `get_chart_reference_trading_day` + `get_recent_trading_days` | `date_from`/`date_to` 검증 동일 (5거래일 범위) |
| `test_month_period` (1081) | `get_kst_today` → 2026-07-31 | `get_chart_reference_trading_day` → 2026-07-31 | `date_from=="2026-07-01"` + `date_to=="2026-07-31"` 검증 유지 |
| `test_cumulative_period` (1098) | `get_kst_today` | `get_chart_reference_trading_day` | 누적은 date_from/date_to 미지정 — 검증 동일 |
| `test_real_mode_omits_rate` (1114) | `get_kst_today` | `get_chart_reference_trading_day` | "증권사 확인" 검증 동일 |
| `test_exception_sends_error` (1131) | `get_kst_today` | `get_chart_reference_trading_day` | "오류" 검증 동일 |

**신규 테스트 추가** (1단계 — 08:00 이전 시나리오 회귀):
- `test_today_period_premarket`: 08:00 이전(예: 06:47)에 `get_chart_reference_trading_day`가 직전 거래일 반환 → 당일 손익이 직전 거래일 기준으로 집계되는지 검증. 프론트 `getTradingToday()`와 동일 동작 확인 (P10 SSOT).

### 4.2 `test_telegram_bot.py` `TestCmdAccount` (1417-1521줄)

| 테스트 | 현재 검증 | 수정 후 검증 |
|--------|----------|------------|
| `test_account_test_mode_shows_initial_deposit` (1457) | 분모 10,000,000(accumulated_investment) → 150,000/10,000,000*100 = 1.50% | 분모 8,000,000(realized_buy_total) → 150,000/8,000,000*100 = 1.875% |
| | `assert "1.50" in text` | `assert "1.88" in text` (round(150000/8000000*100, 2) = 1.875 → 1.88) |
| | docstring "실현 수익률 분모 = 누적투자금(accumulated_investment ?? initial_deposit)" | docstring "실현 수익률 분모 = 매수원금 합계(realized_buy_total)" |
| `test_account_real_mode` (참조용) | 실전모드 분모 = realized_buy_total — 변경 없음 | 동일 |

**주의**: `test_account_test_mode_shows_initial_deposit` 테스트명이 분모 변경 후 의미 변화. 테스트명은 "초기 예치금 표시"를 검증하므로, 분모 검증 부분만 수정하고 테스트명은 유지 (row0 라벨 "누적 투자금" + initial_deposit 표시 검증은 그대로).

### 4.3 `test_trade_history.py` — 수정 없음

`trade_history.py`는 본 설계안에서 수정하지 않으므로, `test_trade_history.py`도 수정 없음.

### 4.4 프론트엔드 테스트 — 수정 없음

프론트엔드는 본 설계안(1-3단계)에서 수정하지 않으므로, `frontend/` 테스트도 수정 없음.

---

## 5. 검증 계획

### 5.1 1-3단계 완료 후 3단계 검증 게이트

| 단계 | 명령어 | 기대 결과 |
|------|--------|----------|
| (1) pytest | `.venv/bin/python -m pytest backend/tests -q` | 전체 passed (신규 1개 추가 — premarket 회귀, 갱신 7개 — TestCmdPeriodPnl 6 + TestCmdAccount 1) |
| (2) RuntimeWarning | `.venv/bin/python -W error::RuntimeWarning main.py` | RuntimeWarning 0건 + 텔레그램 폴링 정상 + 엔진 기동 정상 |
| (3) 잔존 프로세스 | 0-1-3 명령어 | 잔존 0건 |
| (4) 프론트엔드 typecheck | `cd frontend && npm run typecheck` | 통과 (프론트 수정 없음 — 회귀 확인용) |

### 5.2 핵심 교차 검증

- `test_telegram_bot.py` `TestCmdPeriodPnl` 7개 (6 갱신 + 1 신규 premarket) passed
- `test_telegram_bot.py` `TestCmdAccount` 1개 갱신 passed
- `test_trade_history.py` 전체 passed (수정 없음 — 회귀 없음 확인)

---

## 6. 아키텍처 원칙 부합

| 원칙 | 부합 내용 |
|------|----------|
| **P10 (SSOT)** | "거래일 기준 오늘" 단일 소스 `get_chart_reference_trading_day()`로 수렴. 텔레그램 독자 `get_kst_today()` 사용 제거. 누적 수익률 분모 `realized_buy_total`로 양 모드 통일 (프론트 `aggregatePnl`과 동일). |
| **P16 (살아있는 경로)** | `get_chart_reference_trading_day()`는 이미 `trade_history.py:626`에서 살아있는 경로에 배선됨. 텔레그램도 동일 함수 사용 → dead path 아님. |
| **P20 (폴백 금지)** | `accumulated_investment ?? initial_deposit` 폴백 체인 제거 → 단일 분모 `realized_buy_total`. `today_only=True` 우회 제거 → 명시적 `date_from/date_to`. |
| **P21 (사용자 투명성)** | 06:47에 텔레그램 "당일 손익"이 프론트 수익현황과 다른 결과 표시 문제 해결. 사용자가 "왜 텔레그램과 화면이 다르지?" 의문 제거. |
| **P22 (데이터 정합성)** | 텔레그램 손익 명령어와 프론트 수익현황 페이지가 동일 날짜 범위·동일 분모 사용 → 파생 데이터 일치. |
| **P23 (일관성)** | `get_recent_trading_days(5, from_date=ref)` 패턴이 `trade_history.py:626`과 동일. 주석 "프론트엔드와 동일"이 실제와 불일치했던 것 정정. 용어 사전 준수. |
| **P24 (단순성)** | `is_test` 분기 제거 (분모 단일화). `today_only=True` 우회 제거 → `date_from/date_to` 직접 전달. `ref` 변수 재사용 (중복 호출 방지). |

---

## 7. 거래 안전성

- 주문 경로 미변경 (P15) — `execute_buy()`/`execute_sell()` 미접근
- 손익금 계산 공식 미변경 — `(total_amt - buy_total_amt)` 동일
- 날짜 범위 산정·분모만 변경 → 조회 전용 명령어 표시 변경
- `trade_history.py` 미수정 → 집계 로직 무관
- 거래 로직 무관

---

## 8. 4단계 분리 근거 (본 설계안 범위 외)

### 8.1 분리 사유

4단계(프론트 TS `isPreOpenPhase()`/`getTradingToday()` 독자 구현을 백엔드 phase 상태 참조로 전환)는 **API 설계부터 다시 해야 하는 큰 작업**:

1. 백엔드가 "현재 phase가 뭔지"를 프론트에 어떻게 알려줄지 설계 (API 엔드포인트 신설? 기존 응답에 필드 추가? WS 이벤트?)
2. 프론트 `getTradingToday()`, `isPreOpenPhase()`를 사용하는 모든 곳 탐색·변경
3. `_prevWeekday()`(주말만 스킵) vs `get_previous_trading_day()`(휴장일 캘린더 기반) 차이 해소

### 8.2 분리 필요성 (P24 단일 과제 원칙)

1-3단계(텔레그램 함수 교체)와 4단계(프론트 대개편)를 같은 세션/같은 커밋에 섞으면:
- 문제 발생 시 "텔레그램 교체 때문인지 프론트 대개편 때문인지" 구분 불가
- 디버깅 추적성 훼손

1-3단계 완료 후 "텔레그램 손익이 dailySummary와 일치"라는 기준선이 명확해진 상태에서 4단계 진행 → 문제 발생 시 원인 즉시 좁힘 가능.

### 8.3 1-3단계 유효성 훼손 여부

4단계 미진행이 1-3단계 수정 유효성을 훼손하지 않음:
- `_prevWeekday()`(주말만 스킵) vs `get_previous_trading_day()`(평일 공휴일 스킵) 차이는 존재하나, **평일 공휴일이 아닌 한 동일 결과**
- 1-3단계 완료 시 텔레그램이 `get_chart_reference_trading_day()`(백엔드 캘린더 기반) 사용 → dailySummary와 일치
- 프론트가 여전히 `_prevWeekday()` 사용하더라도, 텔레그램↔dailySummary 일치가 우선순위 더 높음
- 프론트↔텔레그램 불일치는 4단계에서 해결

### 8.4 실전 전환 전 완료 필요성

현재 테스트모드라 4단계 미진행이 "안 터진 문제"로 분류 가능. 단, **실전 모드에서 phase 오판은 매수 게이트 오작동 → 실제 돈 I/O로 직결**되므로, 실전 전환 전에는 4단계도 완료되어 있어야 함.

---

## 9. 관련 파일

### 수정 대상 (1-3단계)
- `backend/app/services/telegram_bot.py`
  - `_cmd_period_pnl` (648-687줄) — 1-2단계
  - `_build_account_brief_lines` (114-163줄) — 3단계

### 참조 (수정 없음)
- `backend/app/core/trading_calendar.py` — `get_chart_reference_trading_day` (384-411줄), `get_recent_trading_days` (419줄)
- `backend/app/services/trade_history.py` — `get_realized_pnl_summary` (557-588줄), `get_daily_summary` (626줄 참조)
- `frontend/src/pages/profit-math.ts` — `aggregatePnl` (204-218줄), `computeCumulativePnl` (237-244줄)
- `frontend/src/pages/profit-shared.ts` — `renderAccountVals` (274-329줄)
- `frontend/src/utils/date.ts` — `getTradingToday` (43-49줄)

### 테스트 수정 대상
- `backend/tests/test_telegram_bot.py`
  - `TestCmdPeriodPnl` (1038-1140줄) — 6개 갱신 + 1개 신규
  - `TestCmdAccount.test_account_test_mode_shows_initial_deposit` (1457-1501줄) — 분모 검증값 갱신
