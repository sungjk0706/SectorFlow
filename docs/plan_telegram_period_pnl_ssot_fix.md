# 태스크 파일: 텔레그램 기간별 손익 날짜 범위 SSOT 위반 수정 구현

> **상태**: 태스크 파일 작성 완료 / 구현 승인 대기
> **작성일**: 2026-07-31
> **설계서 경로**: `docs/telegram-period-pnl-ssot-fix-design.md` (301줄, 커밋 `7be9290`)
> **다단계 진행 상황**:
> - 1세션(설계 검토 + 디자인 파일 작성) ✅ — 커밋 `7be9290`
> - 2세션(심층 사전조사 + 태스크 파일 작성) ✅ — 본 파일
> - 3세션(구현) ⏳ — 본 태스크 파일 기반
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)
> **거래 안전성**: 주문 경로 미변경(P15) — 조회 전용 명령어 표시만 변경

---

## 0. 사전조사 결과 요약

### 0.1 의존성

| 파일 | 변경점 | 기준 라인 |
|------|--------|-----------|
| `backend/app/services/telegram_bot.py` | import 교체: `get_kst_today` → `get_chart_reference_trading_day` | 663줄 |
| `backend/app/services/telegram_bot.py` | `today`/`today_iso` 변수 → `ref`/`ref_iso` 변수 (당일·5일·당월 분기 공통 사용) | 665-666줄 |
| `backend/app/services/telegram_bot.py` | 당일 분기: `today_only=True` → `date_from=ref_iso, date_to=ref_iso` | 668-669줄 |
| `backend/app/services/telegram_bot.py` | 5일 분기: `get_recent_trading_days(5)` → `get_recent_trading_days(5, from_date=ref)` | 671줄 |
| `backend/app/services/telegram_bot.py` | 당월 분기: `today` 기반 → `ref` 기반 (`_date(ref.year, ref.month, 1)`, `date_to=ref_iso`) | 678-680줄 |
| `backend/app/services/telegram_bot.py` | 누적 수익률 분모: `is_test` 분기 제거 → `cum_denominator = realized_buy_total` (양 모드 공통) | 142-147줄 |
| `backend/app/services/telegram_bot.py` | 주석 정정: "테스트모드=누적투자금…실전모드=매수총액" → "매수원금 합계 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT)" | 142줄 |
| `backend/app/services/telegram_bot.py` | docstring 정정: 분모가 매수원금 합계로 통일되었음을 명시 | 115-123줄 |
| `backend/tests/test_telegram_bot.py` | `TestCmdPeriodPnl` 6개 테스트: `get_kst_today` patch → `get_chart_reference_trading_day` patch | 1047-1140줄 |
| `backend/tests/test_telegram_bot.py` | `test_today_period`: `today_only=True` 검증 → `date_from=="2026-07-31"` + `date_to=="2026-07-31"` 검증 | 1059-1060줄 |
| `backend/tests/test_telegram_bot.py` | `TestCmdPeriodPnl` 신규 1개: `test_today_period_premarket` (08:00 이전 회귀) | 1140줄 뒤 |
| `backend/tests/test_telegram_bot.py` | `test_account_test_mode_shows_initial_deposit`: 분모 검증값 `1.50` → `1.88` + docstring 정정 | 1457-1501줄 |

**참조 파일 (수정 없음)**:
- `backend/app/core/trading_calendar.py` — `get_chart_reference_trading_day()` (384-411줄), `get_recent_trading_days(days, from_date)` (419줄) — 이미 존재하는 공통 자산
- `backend/app/services/trade_history.py` — `get_realized_pnl_summary()` (557-588줄), `get_daily_summary()` (626줄 참조 — 동일 패턴 `get_recent_trading_days(days, from_date=get_chart_reference_trading_day())`)
- `frontend/src/pages/profit-math.ts` — `aggregatePnl` (204-218줄), `computeCumulativePnl` (237-244줄) — 분모 = `buyTotal` (매수원금 합) 양 모드 공통

### 0.2 영향 범위

- **백엔드**: `telegram_bot.py` 1개 파일 (2개 함수 — `_cmd_period_pnl`, `_build_account_brief_lines`)
- **테스트**: `test_telegram_bot.py` 1개 파일 (`TestCmdPeriodPnl` 6개 갱신 + 1개 신규, `TestCmdAccount` 1개 갱신)
- **프론트엔드**: 수정 없음 (4단계 — 별도 설계안)
- **DB**: 수정 없음
- **거래 로직**: 무관 (주문 경로 `execute_buy()`/`execute_sell()` 미접근 — P15)
- **`trade_history.py`**: 수정 없음 (`today_only` 파라미터·분기 코드 유지 — 시그니처 변경 최소화, 설계서 3.1절 결정)

### 0.3 아키텍처 원칙 부합

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10 (SSOT) | ✅ | "거래일 기준 오늘" 단일 소스 `get_chart_reference_trading_day()`로 수렴. 누적 수익률 분모 `realized_buy_total`로 양 모드 통일 (프론트 `aggregatePnl`과 동일). |
| P16 (살아있는 경로) | ✅ | `get_chart_reference_trading_day()`는 이미 `trade_history.py:626`에서 살아있는 경로에 배선됨. 텔레그램도 동일 함수 사용 → dead path 아님. |
| P20 (폴백 금지) | ✅ | `accumulated_investment ?? initial_deposit` 폴백 체인 제거 → 단일 분모 `realized_buy_total`. `today_only=True` 우회 제거 → 명시적 `date_from/date_to`. |
| P21 (사용자 투명성) | ✅ | 06:47에 텔레그램 "당일 손익"이 프론트 수익현황과 다른 결과 표시 문제 해결. |
| P22 (데이터 정합성) | ✅ | 텔레그램 손익 명령어와 프론트 수익현황 페이지가 동일 날짜 범위·동일 분모 사용 → 파생 데이터 일치. |
| P23 (일관성) | ✅ | `get_recent_trading_days(5, from_date=ref)` 패턴이 `trade_history.py:626`과 동일. 주석 "프론트엔드와 동일"이 실제와 불일치했던 것 정정. |
| P24 (단순성) | ✅ | `is_test` 분기 제거 (분모 단일화). `today_only=True` 우회 제거. `ref` 변수 재사용 (중복 호출 방지). |
| P25 (격리된 실패) | ✅ | 텔레그램 명령어 예외는 기존 `_cmd_period_pnl` try/except + `_send` 오류 메시지 전송 유지. |

### 0.4 기존 공통 자산 확인

| 자산 | 위치 | 재사용 여부 |
|------|------|------------|
| `get_chart_reference_trading_day()` | `trading_calendar.py:384-411` | ✅ 재사용 — 신규 생성 없음. `trade_history.py:626`과 동일 패턴. |
| `get_recent_trading_days(days, from_date)` | `trading_calendar.py:419` | ✅ 재사용 — `from_date` 파라미터 이미 존재. |
| `get_realized_pnl_summary()` | `trade_history.py:557-588` | ✅ 재사용 — `date_from`/`date_to` 파라미터 이미 존재. `today_only` 파라미터도 유지 (시그니처 변경 없음). |
| 프론트 `aggregatePnl`/`computeCumulativePnl` 분모 규칙 | `profit-math.ts:204-244` | ✅ 참조 — 분모 = `buyTotal` (매수원금 합) 양 모드 공통. 백엔드 `realized_buy_total`과 동일 의미. |

**신규 생성**: 없음 (모두 기존 자산 재사용)

---

## 1. 단계 분할

> **작업량**: 수정 파일 2개, 수정 라인 ~45줄 (telegram_bot.py ~15줄 + test ~30줄)
> **정량 기준**(컨텍스트 관리 규칙 1): 3파일 초과 또는 50줄 초과 시 분할 → **기준 미달**
> **단계 수**: **1개 세션** (1-3단계가 같은 파일의 인접 영역이라 한 번에 수정·검증하는 것이 자연스러움)

### 1세션: 1-3단계 통합 구현

**목표**: 텔레그램 기간별 손익 명령어 날짜 범위를 `get_chart_reference_trading_day()` 기반으로 통일 + 누적 수익률 분모를 `realized_buy_total`로 양 모드 통일

**수정 파일 목록**:
1. `backend/app/services/telegram_bot.py`
2. `backend/tests/test_telegram_bot.py`

**파일별 변경점**:

#### `backend/app/services/telegram_bot.py`

**1-2단계: `_cmd_period_pnl` (648-687줄)**

- 663줄 import: `from backend.app.core.trading_calendar import get_kst_today, get_recent_trading_days` → `from backend.app.core.trading_calendar import get_chart_reference_trading_day, get_recent_trading_days`
- 665-666줄: `today = get_kst_today(); today_iso = today.isoformat()` → `ref = get_chart_reference_trading_day(); ref_iso = ref.isoformat()`
- 668-669줄 당일: `await _compute_period_pnl("당일", today_only=True, is_test=_is_test)` → `await _compute_period_pnl("당일", date_from=ref_iso, date_to=ref_iso, is_test=_is_test)`
- 671줄 5일: `recent5 = get_recent_trading_days(5)` → `recent5 = get_recent_trading_days(5, from_date=ref)`
- 678-680줄 당월: `month_start = _date(today.year, today.month, 1).isoformat()` → `month_start = _date(ref.year, ref.month, 1).isoformat()`; `date_to=today_iso` → `date_to=ref_iso`

**3단계: `_build_account_brief_lines` (114-163줄)**

- 142-147줄 분모:
  ```python
  # 수익률 분모: 매수원금 합계 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT)
  cum_denominator = realized_buy_total
  ```
  - `is_test` 분기 제거
  - `snap.get("accumulated_investment", 0) or snap.get("initial_deposit", 0)` 제거
  - 주석 정정 (기존 "테스트모드=누적투자금…실전모드=매수총액 합계 (프론트엔드와 동일)" → "매수원금 합계 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT)")
- 115-123줄 docstring: 122줄 "누적 실현 손익금/수익률 추가 — 프론트엔드 aggregatePnl과 동일 공식 (P21)."에 분모가 매수원금 합계로 통일되었음을 명시

#### `backend/tests/test_telegram_bot.py`

**`TestCmdPeriodPnl` (1038-1140줄) — 6개 갱신 + 1개 신규**

| 테스트 | 변경점 |
|--------|--------|
| `test_today_period` (1047) | `get_kst_today` patch → `get_chart_reference_trading_day` patch; `today_only=True` 검증 → `date_from=="2026-07-31"` + `date_to=="2026-07-31"` 검증 |
| `test_5day_period` (1063) | `get_kst_today` patch → `get_chart_reference_trading_day` patch; `date_from`/`date_to` 검증 동일 |
| `test_month_period` (1081) | `get_kst_today` patch → `get_chart_reference_trading_day` patch; `date_from=="2026-07-01"` + `date_to=="2026-07-31"` 검증 유지 |
| `test_cumulative_period` (1098) | `get_kst_today` patch → `get_chart_reference_trading_day` patch; 누적 검증 동일 |
| `test_real_mode_omits_rate` (1114) | `get_kst_today` patch → `get_chart_reference_trading_day` patch; "증권사 확인" 검증 동일 |
| `test_exception_sends_error` (1131) | `get_kst_today` patch → `get_chart_reference_trading_day` patch; "오류" 검증 동일 |
| `test_today_period_premarket` (신규) | 08:00 이전(예: 06:47)에 `get_chart_reference_trading_day`가 직전 거래일(예: 수 2026-07-29) 반환 → 당일 손익이 직전 거래일 기준으로 집계되는지 검증. `date_from=="2026-07-29"` + `date_to=="2026-07-29"`. 프론트 `getTradingToday()`와 동일 동작 확인 (P10 SSOT). |

**`TestCmdAccount.test_account_test_mode_shows_initial_deposit` (1457-1501줄) — 1개 갱신**

- 1462줄 docstring: "실현 수익률 분모 = 누적투자금(accumulated_investment ?? initial_deposit)" → "실현 수익률 분모 = 매수원금 합계(realized_buy_total)"
- 1494줄 주석: "테스트모드 분모 = accumulated_investment(10,000,000)" → "분모 = realized_buy_total(8,000,000)"
- 1498-1499줄: `# 150,000 / 10,000,000 * 100 = 1.50%` → `# 150,000 / 8,000,000 * 100 = 1.875% → 1.88%`; `assert "1.50" in text` → `assert "1.88" in text`
- 테스트명 유지 ("초기 예치금 표시" 검증은 그대로 — row0 라벨 "누적 투자금" + initial_deposit 표시 검증)

**검증 방법**:
1. `cd /Users/sungjk0706/Desktop/SectorFlow && .venv/bin/python -m pytest backend/tests/test_telegram_bot.py -q` — TestCmdPeriodPnl 7개 + TestCmdAccount 1개 passed
2. `cd /Users/sungjk0706/Desktop/SectorFlow && .venv/bin/python -m pytest backend/tests -q` — 전체 passed (회귀 없음)
3. `cd /Users/sungjk0706/Desktop/SectorFlow && .venv/bin/python -W error::RuntimeWarning main.py` — RuntimeWarning 0건 + 텔레그램 폴링 정상 + 엔진 기동 정상 (10~30초 대기 후 종료)
4. 잔존 프로세스 0건 확인 (0-1-3)
5. `cd /Users/sungjk0706/Desktop/SectorFlow/frontend && npm run typecheck` — 통과 (프론트 수정 없음 — 회귀 확인용)

---

## 2. 사용자 결정 항목

> 설계서(`docs/telegram-period-pnl-ssot-fix-design.md`)에 명시적 "사용자 결정 항목" 섹션은 없으나, 이전 세션에서 사용자가 제시한 분리 원칙을 이관.

| 항목 | 사용자 결정 | 근거 |
|------|------------|------|
| 1-3단계 vs 4단계 분리 | "1-3번 먼저 완료·검증 → 4번 별도 세션/별도 커밋" | P24 단일 과제 원칙 — 문제 발생 시 원인 추적성 확보. 1-3단계(텔레그램 함수 교체)와 4단계(프론트 대개편)를 같은 세션/커밋에 섞으면 디버깅 추적성 훼손. |
| 4단계 범위 | 프론트 TS `isPreOpenPhase()`/`getTradingToday()` 독자 구현을 백엔드 phase 상태 참조로 전환 — 별도 설계안 작성 | API 설계부터 다시 해야 하는 큰 작업 (백엔드 phase 전달 방식 설계, 프론트 사용처 전수 조사·변경, `_prevWeekday()` vs `get_previous_trading_day()` 차이 해소). |
| `trade_history.py` 수정 범위 | 본 설계안(1-3단계)에서 `trade_history.py`는 수정하지 않음 | `today_only` 파라미터는 공개 API 시그니처 일부. 다른 호출자 조사 선행 필요. 본 설계안은 텔레그램 `_cmd_period_pnl`의 `today_only=True` 호출을 `date_from/date_to`로 교체하는 것만 수행. |
| 실전 전환 전 4단계 완료 필요성 | 실전 모드 전환 전 4단계도 완료되어야 함 | 현재 테스트모드라 4단계 미진행이 "안 터진 문제"지만, 실전 모드에서 phase 오판은 매수 게이트 오작동 → 실제 돈 I/O로 직결. |

---

## 3. 테스트 계획

### 3.1 신규 테스트 케이스

| 테스트 | 목적 | 검증 |
|--------|------|------|
| `test_today_period_premarket` | 08:00 이전 시나리오 회귀 (P10 SSOT) | `get_chart_reference_trading_day`가 직전 거래일(수 2026-07-29) 반환 → `date_from=="2026-07-29"` + `date_to=="2026-07-29"` 검증. 프론트 `getTradingToday()`와 동일 동작 확인. |

### 3.2 갱신 테스트 케이스

| 테스트 | 갱신 사유 |
|--------|----------|
| `TestCmdPeriodPnl` 6개 | `get_kst_today` patch → `get_chart_reference_trading_day` patch. `test_today_period`는 `today_only=True` 검증 → `date_from`/`date_to` 검증으로 변경. |
| `TestCmdAccount.test_account_test_mode_shows_initial_deposit` | 분모 검증값 `1.50` → `1.88` (150,000 / 8,000,000 * 100 = 1.875 → round 1.88). docstring·주석 정정. |

### 3.3 회귀 확인 (수정 없음)

- `test_trade_history.py` 전체 — `trade_history.py` 미수정으로 회귀 없음 확인
- 프론트엔드 테스트 — 프론트 수정 없음으로 회귀 없음 확인

---

## 4. 런타임 검증 방법

| 단계 | 명령어 | 기대 결과 |
|------|--------|----------|
| (1) 개별 pytest | `.venv/bin/python -m pytest backend/tests/test_telegram_bot.py -q` | TestCmdPeriodPnl 7개(6 갱신+1 신규) + TestCmdAccount 1개 갱신 passed |
| (2) 전체 pytest | `.venv/bin/python -m pytest backend/tests -q` | 전체 passed (회귀 없음) |
| (3) RuntimeWarning | `.venv/bin/python -W error::RuntimeWarning main.py` | RuntimeWarning 0건 + 텔레그램 폴링 정상 + 엔진 기동 정상 |
| (4) 잔존 프로세스 | `ps aux \| grep -E "python\|main.py\|pytest\|vite" \| grep -v grep` | 잔존 0건 (0-1-3) |
| (5) 프론트 typecheck | `cd frontend && npm run typecheck` | 통과 (프론트 수정 없음 — 회귀 확인용) |

---

## 5. 완료 기준

- [ ] 1-3단계 코드 수정 완료 (telegram_bot.py 2개 함수)
- [ ] 테스트 갱신·신규 추가 완료 (test_telegram_bot.py)
- [ ] 5단계 검증 게이트 통과 (pytest 전체 + RuntimeWarning + 잔존 0건 + 프론트 typecheck)
- [ ] 코드 커밋 (코드만 — `HANDOVER.md` 커밋 제외)
- [ ] `HANDOVER.md` 갱신 (파일만, 커밋 제외)
- [ ] 세션 완료 보고 (채팅 출력 — 커밋 해시·핸드오버 갱신 여부 명시)
- [ ] 계획서 파일 삭제 (디자인 파일 + 태스크 파일 — 규칙 10, 최종 커밋 시)
