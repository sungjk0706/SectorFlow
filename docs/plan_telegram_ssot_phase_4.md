# 태스크 파일: 텔레그램 SSOT 4단계 — 프론트 거래일 기준 오늘 백엔드 참조 전환 구현

> **상태**: 태스크 분할 완료 / 구현 승인 대기
> **작성일**: 2026-07-31
> **설계서 경로**: `docs/architecture_telegram_ssot_phase_4_design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ / 2세션(태스크 분할) ✅ / 3세션(구현) 대기
> **관련 원칙**: P10 · P16 · P20 · P21 · P22 · P23 · P24 · P25
> **위험도**: 높음 (시간/날짜 의존 로직) — 전 게이트 필수

---

## 0. 사전조사 결과 요약

> 설계서(섹션 1·2·6·7·8)에서 이미 확정한 사실은 P10(SSOT)에 따라 본 섹션에서 요약만 기재. 상세 근거는 설계서 참조.
> **본 세션에서 실제 코드 대상으로 검증한 항목**을 함께 기재 (규칙 0-2 — 태스크 파일 작성 단계 심층 사전조사).

### 0.1 의존성

| 파일 | 변경점 | 기준 라인 (실제 검증) |
|------|--------|----------------------|
| `backend/app/services/daily_time_scheduler.py` | `get_market_phase()` 반환 dict에 `chart_reference_trading_day` 필드 추가. `get_chart_reference_trading_day()` 로컬 import (기존 `is_trading_day` 로컬 import 패턴 재사용 — 142·540·563줄 등) | 439–461 (필드 추가: 461줄 `return phase` 직전) |
| `backend/app/services/engine_lifecycle.py` | **변경 없음** — `get_engine_status()`가 `get_market_phase()` 호출(208줄) → 신규 필드 자동 포함 | 208 |
| `backend/app/services/engine_initial_data.py` | **변경 없음** — `build_initial_snapshot()`이 `get_market_phase()` 호출(80줄) → 신규 필드 자동 포함 | 80 |
| `backend/app/core/trading_calendar.py` | **변경 없음** — `get_chart_reference_trading_day()` (384–411줄) 그대로 사용. 반환형 `date` → `.isoformat()`으로 `YYYY-MM-DD` 문자열 변환 | 384–411 |
| `frontend/src/utils/date.ts` | `getTradingToday()` 백엔드 값 직접 반환 · `isPreOpenPhase()` 백엔드 값 기반 전환 · `_prevWeekday()` 제거 · `PRE_OPEN_PHASES` 제거 | 14–49 (전면 교체) |
| `frontend/src/stores/uiStore.ts` | `UIState['marketPhase']` 타입에 `chart_reference_trading_day?: string` 추가 · 초기값 `chart_reference_trading_day: ''` 추가 | 타입 36–43 · 초기값 103 |
| `frontend/src/types/index.ts` | `EngineStatusPayload.market_phase` 타입에 `chart_reference_trading_day?: string` 추가 | 127–134 |
| `frontend/tests/utils/date.test.ts` | phase 문자열 mock → `chart_reference_trading_day` 값 mock 기반 전환. `_prevWeekday` 주말 스킵 테스트 제거, 백엔드 값 전달 테스트 추가 | 전면 갱신 (136줄) |
| `backend/tests/test_daily_time_scheduler.py` | `TestGetMarketPhase` 클래스에 `chart_reference_trading_day` 필드 존재 검증 추가 | 779–834 (신규 테스트 추가) |

### 0.2 영향 범위

- **백엔드**: `daily_time_scheduler.py` `get_market_phase()` 반환 dict에 필드 1개 추가 (+2줄). 외부 인터페이스(함수 시그니처) 변경 없음. `get_engine_status()`·`build_initial_snapshot()`은 `get_market_phase()` 호출 경로로 자동 포함 — 수정 불필요 (설계서 섹션 6.1 검증 완료).
- **프론트엔드**: `date.ts` 4개 요소(`PRE_OPEN_PHASES`·`_prevWeekday`·`isPreOpenPhase`·`getTradingToday`) 교체, `uiStore.ts` 타입+초기값, `types/index.ts` 타입. 총 3파일, 순 줄 수 감소(-10+4+2+1 = -3줄).
- **DB / 설정 스키마 / 거래 로직**: 변경 없음 (설계서 섹션 6.4 — 매수/매도 게이트는 `engine_state.market_phase` 문자열 직접 참조, phase→날짜 변환 경로와 무관).
- **호출부 (수정 없음 — 시그니처 유지)**: `profit-shared.ts:188,199` · `profit-detail.ts:136` · `profit-detail-display.ts:254,273` · `profit-overview-mount.ts:297` · `profit-overview-date.ts:63` · `canvas-profit-chart.ts:155` (getTradingMonthStart 경유). 총 7파일 9개 호출부 — 전부 함수 시그니처 유지로 수정 불필요 (실제 grep 검증 완료).

### 0.3 아키텍처 원칙 부합

> 상세 근거는 설계서 섹션 4. 본 태스크는 실행 단계별 부합 항목만 표기.

| 원칙 | 부합 | 실행 단계에서의 확인점 |
|------|------|----------------------|
| P10 | ✅ | `get_chart_reference_trading_day()` 단일 소스로 수렴. 프론트 `_prevWeekday()`/`PRE_OPEN_PHASES` 독자 로직 제거. phase→날짜 변환 경로 단일화 |
| P16 | ✅ | `get_chart_reference_trading_day()`는 `telegram_bot.py:665`·`trade_history.py:626`에서 이미 살아있는 경로. `get_market_phase()`도 `get_engine_status()`/`build_initial_snapshot()` 양쪽 살아있는 경로 (208·80줄 실제 확인) |
| P20 | ✅ | 빈 문자열(엔진 기동 전)을 `getLocalToday()` 폴백으로 덮지 않음. 빈 문자열 그대로 전달 → 호출부 명시 처리 |
| P21 | ✅ | 평일 공휴일에 프론트↔텔레그램 날짜 불일치 해결. 사용자가 "왜 화면과 텔레그램이 다르지?" 의문 제거 |
| P22 | ✅ | 프론트↔텔레그램↔dailySummary가 동일 날짜 범위 사용 → 파생 데이터 일치 |
| P23 | ✅ | `chart_reference_trading_day`를 `market_phase` dict 내부에 추가 → 기존 `is_nxt_only`/`krx_countdown` 파생 필드 패턴 일치. WS 이벤트 필드명 `snake_case` 유지 |
| P24 | ✅ | 프론트 `_prevWeekday()`(8줄)·`PRE_OPEN_PHASES`(2줄) 제거. `getTradingToday()` 6줄→1줄. 백엔드 필드 추가 1줄. 전체 줄 수 감소 |
| P25 | ✅ | `get_market_phase()` 내 `get_chart_reference_trading_day()` 호출 실패 시 해당 필드만 빈 문자열, phase 문자열은 영향 없음. 프론트 빈 문자열 반환 시 호출부에서 차트 미표시 등 격리 처리 |

### 0.4 기존 공통 자산 확인

- **재사용 (신규 생성 없음)**:
  - `get_chart_reference_trading_day()` (`trading_calendar.py:384`) — 백엔드 SSOT 함수, 1-3단계에서 이미 살아있는 경로에 배선됨. 본 작업은 노출 경로 추가만.
  - `get_market_phase()` (`daily_time_scheduler.py:439`) — phase SSOT 읽기 함수, `get_engine_status()`/`build_initial_snapshot()` 양쪽 경유. 기존 파생 필드 패턴(`is_nxt_only`·`krx_countdown`)과 동일 방식으로 필드 추가.
  - 로컬 import 패턴 — `daily_time_scheduler.py`는 `trading_calendar`에서 함수 단위 로컬 import를 기존 패턴으로 사용 (142·540·563·594·630줄 등). `get_chart_reference_trading_day`도 동일 패턴 적용.
  - `getLocalToday()` (`date.ts:9`) — `isPreOpenPhase()` 새 구현에서 로컬 오늘 비교용 재사용. 변경 없음.
  - `uiStore.getState().marketPhase` — 기존 store 접근 패턴 그대로.
- **신규 생성**: 없음 (임의 파일/함수/전역 매니저 추가 금지 — 설계서 섹션 2.2 기각 방안)

### 0.5 사전조사에서 발견한 설계서 보완점 (바로잡음 로그 이관)

> 설계서 결정 3의 `isPreOpenPhase()` 목표 코드에 빈 문자열 처리 누락 발견. 본 태스크에서 보완.

**설계서 결정 3 원안**:
```typescript
export function isPreOpenPhase(): boolean {
  const ref = uiStore.getState().marketPhase.chart_reference_trading_day
  return ref !== undefined && ref !== getLocalToday()
}
```

**문제**: 결정 4가 초기값을 빈 문자열 `''`로 설정하므로, 엔진 기동 전(WS 미연결)에는 `ref === ''`이다. 원안의 `ref !== undefined`는 `''`에 대해 `true`이고, `'' !== getLocalToday()`도 `true` → **`isPreOpenPhase()`가 `true` 반환**.

- **현재 동작**: 초기 `marketPhase = { krx: '장마감', nxt: '장마감' }` → `PRE_OPEN_PHASES.has('장마감')` = `false` → `isPreOpenPhase()` = `false`.
- **원안 적용 시**: `isPreOpenPhase()` = `true` → `profit-shared.ts:199`에서 `preOpen=true` → 당일 카드 "개장 전" + 0원 강제 표시. **WS 연결 전 초기 화면에서 동작 변경** (P21 위반 가능 — 사용자가 예상하지 못한 "개장 전" 표시).

**보완안 (본 태스크 적용)**:
```typescript
export function isPreOpenPhase(): boolean {
  const ref = uiStore.getState().marketPhase.chart_reference_trading_day
  return !!ref && ref !== getLocalToday()
}
```

- `!!''` = `false` → 빈 문자열 시 `false` 반환 → 현재 동작(초기 `false`)과 일치.
- 백엔드 값 수신 후: `!!'2026-07-30'` = `true` → `getLocalToday()`와 비교 → 의도대로 동작.
- `getTradingToday()`는 설계서 원안대로 `uiStore.getState().marketPhase.chart_reference_trading_day ?? ''` 유지 (빈 문자열 그대로 반환 — P20).

**근거**: P20(폴백 금지 — 빈 문자열을 폴백으로 덮지 않음)·P21(사용자 투명성 — 초기 화면 동작 변경 회피)·P25(격리된 실패 — WS 미연결 시 안전한 기본값). 설계서 결정 4의 "빈 문자열 그대로 전달하여 호출부가 명시 처리" 원칙과 일치 — `!!ref`가 빈 문자열을 명시적으로 처리.

---

## 1. 단계 분할

> 정량 기준(컨텍스트 관리 규칙 1 · 규칙 0-2-5): 수정 파일 3개 초과 또는 수정 라인 50줄 초과 시 다단계 분할 필수.
> 본 작업: 백엔드 +2줄, 프론트 -10+7줄(3파일), 테스트 2파일 갱신. **수정 파일 6개이나 실제 코드 변경량은 약 15줄** (테스트 갱신 제외). 백엔드↔프론트 결합도 높음(동일 필드 추가·소비) → **단일 구현 세션(3세션)으로 분할** (P24 단순성 — 과잉 분할 회피). 백엔드 필드 추가와 프론트 소비를 같은 세션에서 수행해야 WS 이벤트 스키마 일관성 유지.

### 3세션: 구현 + 테스트 (단일 세션)

**목표**: 백엔드 `get_market_phase()`에 `chart_reference_trading_day` 필드를 추가하고, 프론트 `date.ts`의 `getTradingToday()`/`isPreOpenPhase()`를 백엔드 값 기반으로 전환하며, `_prevWeekday()`/`PRE_OPEN_PHASES`를 제거한 후, 검증 게이트 3단계를 통과한다.

**수정 파일 목록**:
1. `backend/app/services/daily_time_scheduler.py` — 백엔드 필드 추가
2. `frontend/src/utils/date.ts` — 프론트 전환 + 독자 로직 제거
3. `frontend/src/stores/uiStore.ts` — 타입 + 초기값
4. `frontend/src/types/index.ts` — WS payload 타입
5. `frontend/tests/utils/date.test.ts` — 테스트 전면 갱신
6. `backend/tests/test_daily_time_scheduler.py` — 필드 존재 검증 추가

**파일별 변경점**:

#### `backend/app/services/daily_time_scheduler.py` (백엔드 필드 추가)

`get_market_phase()` (439–461줄)의 `return phase` 직전(461줄)에 필드 추가:

```python
# 차트 기준 거래일 — 프론트 getTradingToday() SSOT (P10 — 휴장일 캘린더 단일 소스)
try:
    from backend.app.core.trading_calendar import get_chart_reference_trading_day
    phase["chart_reference_trading_day"] = get_chart_reference_trading_day().isoformat()
except Exception:
    logger.warning("[시스템] chart_reference_trading_day 산출 실패 — 빈 문자열 사용", exc_info=True)
    phase["chart_reference_trading_day"] = ""
```

- 로컬 import — 기존 패턴(142·540줄 등 `from backend.app.core.trading_calendar import ...`) 일치 (P23).
- `try/except` — `get_chart_reference_trading_day()` 실패 시 해당 필드만 빈 문자열, phase 문자열은 영향 없음 (P25 격리된 실패). `except Exception:` + `logger.warning(..., exc_info=True)` — silent pass 금지 (금지 패턴 3번째).
- `.isoformat()` — `date` 객체를 `YYYY-MM-DD` 문자열로 변환.

**유지 (변경 금지)**:
- `engine_state.state.market_phase` 읽기 로직 (445–449줄) — 변경 없음
- 기존 파생 필드 (`is_nxt_only`·`krx_countdown`·`nxt_countdown`) — 변경 없음
- 함수 시그니처·docstring — 반환 dict에 필드 추가만, 시그니처 변경 없음

#### `frontend/src/utils/date.ts` (프론트 전환 + 독자 로직 제거)

전면 교체 (14–49줄):

```typescript
// 제거: PRE_OPEN_PHASES (17줄), _prevWeekday (22–28줄)
// 제거: isPreOpenPhase 기존 구현 (33–36줄), getTradingToday 기존 구현 (43–49줄)

/** 당일 카드 개장 전(08:00 이전 또는 휴일) 여부 — 백엔드 chart_reference_trading_day 기반.
 *  chart_reference_trading_day가 로컬 오늘과 다르면 개장 전 (백엔드가 전일 반환했다는 의미).
 *  빈 문자열(WS 미연결) 시 false — 안전한 기본값 (P20 폴백 금지, P25 격리).
 *  P10 SSOT — phase 판정은 백엔드 get_chart_reference_trading_day() 단일 소스. */
export function isPreOpenPhase(): boolean {
  const ref = uiStore.getState().marketPhase.chart_reference_trading_day
  return !!ref && ref !== getLocalToday()
}

/** 거래일 기준 오늘 날짜 (YYYY-MM-DD) — 백엔드 chart_reference_trading_day 직접 반환.
 *  - 개장 전(08:00 이전 또는 휴일): 백엔드가 직전 거래일 반환 (휴장일 캘린더 기반)
 *  - 장중·장마감 후(08:00~24:00): 백엔드가 오늘 반환
 *  - WS 미연결: 빈 문자열 반환 → 호출부에서 명시 처리 (P20 폴백 금지)
 *  P10 SSOT — uiStore.marketPhase.chart_reference_trading_day 단일 소스. */
export function getTradingToday(): string {
  return uiStore.getState().marketPhase.chart_reference_trading_day ?? ''
}
```

- `getTradingMonthStart()` (53–55줄) — **변경 없음**. `getTradingToday()` 기반으로 자동 백엔드 값 연동.
- `getLocalToday()` (9–12줄) — **변경 없음**. `isPreOpenPhase()` 비교용 재사용.
- import `uiStore` (6줄) — **변경 없음**.

#### `frontend/src/stores/uiStore.ts` (타입 + 초기값)

- 타입 (36–43줄): `marketPhase` 객체에 `chart_reference_trading_day?: string` 추가
- 초기값 (103줄): `marketPhase: { krx: '장마감', nxt: '장마감', krx_alert: null, is_nxt_only: false, chart_reference_trading_day: '' }`

#### `frontend/src/types/index.ts` (WS payload 타입)

- `EngineStatusPayload.market_phase` (127–134줄): `chart_reference_trading_day?: string` 추가

#### `frontend/tests/utils/date.test.ts` (테스트 전면 갱신)

phase 문자열 mock → `chart_reference_trading_day` 값 mock 기반으로 전환:

- **테스트 헬퍼 변경**: `setMarketPhase(krx, nxt)` → `setMarketPhase(krx, nxt, chartRefDay)` — `chart_reference_trading_day` 필드 포함
- **`getTradingToday` 테스트**:
  - 개장 전(장개시전, 07:00) + `chart_reference_trading_day='2026-07-29'` → `'2026-07-29'` 반환 (백엔드 값 직접 반환)
  - 장중(정규장, 10:00) + `chart_reference_trading_day='2026-07-30'` → `'2026-07-30'` 반환
  - 장마감 후 + `chart_reference_trading_day='2026-07-30'` → `'2026-07-30'` 반환
  - 초기값(WS 수신 전, `chart_reference_trading_day=''`) → `''` 반환 (빈 문자열 — P20)
  - **평일 공휴일 시나리오 (설계서 1.2 시나리오 A)**: 금 06:47 + `chart_reference_trading_day='2026-08-13'` (수) → `'2026-08-13'` 반환 (백엔드 캘린더 기반 — 프론트 독자 로직 `_prevWeekday`였으면 `'2026-08-14'` 반환)
- **`isPreOpenPhase` 테스트**:
  - `chart_reference_trading_day='2026-07-29'` + 로컬 오늘 `'2026-07-30'` → `true` (전일 = 개장 전)
  - `chart_reference_trading_day='2026-07-30'` + 로컬 오늘 `'2026-07-30'` → `false` (오늘 = 개장 후)
  - `chart_reference_trading_day=''` → `false` (빈 문자열 — 0.5 보완안)
- **`getTradingMonthStart` 테스트**: `getTradingToday()` 기반 유지 — `chart_reference_trading_day` 값으로 자동 연동 검증
- **`getLocalToday` 테스트**: 변경 없음 (캘린더 날짜 — 시간 무관)
- **제거**: `_prevWeekday` 주말 스킵 테스트 (월요일 07:00→금요일, 일요일→금요일 등) — 독자 로직 제거로 더 이상 유효하지 않음

#### `backend/tests/test_daily_time_scheduler.py` (필드 존재 검증 추가)

`TestGetMarketPhase` 클래스 (779줄)에 신규 테스트 추가:

```python
def test_includes_chart_reference_trading_day(self):
    """get_market_phase() 반환에 chart_reference_trading_day 필드 포함 검증 (P10/P16)."""
    mock_state = MagicMock()
    mock_state.market_phase = {"krx": "정규장", "nxt": "메인마켓"}
    mock_state.krx_countdown_override = None
    mock_state.nxt_countdown_override = None
    with patch("backend.app.services.engine_state.state", mock_state):
        result = get_market_phase()
        assert "chart_reference_trading_day" in result
        # ISO 날짜 형식 (YYYY-MM-DD) 검증
        assert isinstance(result["chart_reference_trading_day"], str)
        assert len(result["chart_reference_trading_day"]) == 10
```

- 기존 테스트(`test_returns_copy_with_krx_nxt` 등)는 `chart_reference_trading_day` 필드 추가 후에도 통과해야 함 — 기존 assert가 신규 필드에 의존하지 않으므로. 단, `test_returns_copy_with_krx_nxt` 등에서 `get_chart_reference_trading_day`가 실제 호출되므로 트레이딩 캘린더 초기화가 필요할 수 있음 — 구현 시 기존 테스트 통과 여부 확인 후 필요하면 patch 추가.

**검증 방법** (3단계 게이트 — 설계서 섹션 5):

```bash
# 1단계: 관련 테스트만 먼저
.venv/bin/python -m pytest backend/tests/test_daily_time_scheduler.py -q
cd frontend && npm run test -- --run utils/date    # date.test.ts만
cd frontend && npm run typecheck

# 2단계: 전체 (2697 tests, asyncio_mode=auto)
.venv/bin/python -m pytest backend/tests -q
cd frontend && npm run test
cd frontend && npm run build

# 3단계: RuntimeWarning (await 누락 검증 — 금지 패턴 4번째)
.venv/bin/python -W error::RuntimeWarning main.py
```

**핵심 검증 (전체 pytest 통과만으로는 부족)**:
1. `get_market_phase()` 반환에 `chart_reference_trading_day` 필드 존재 + ISO 날짜 형식 — 신규 백엔드 테스트
2. 프론트 `getTradingToday()`가 백엔드 값 직접 반환 (phase 문자열 해석 아님) — 프론트 테스트
3. 프론트 `isPreOpenPhase()` 빈 문자열 시 `false` (0.5 보완안) — 프론트 테스트
4. 평일 공휴일 시나리오에서 백엔드 값 그대로 반환 (프론트 독자 `_prevWeekday`와 다른 결과) — 프론트 테스트
5. 기존 호출부 7파일 9개 호출부 회귀 없음 — typecheck + build로 시그니처 호환 검증

---

## 2. 사용자 결정 항목

> 설계서 섹션 3에서 확정된 사항 이관. 구현 중 추가 결정 시 누적 기록.

| # | 결정 사항 | 확정 내용 | 근거 (설계서) |
|---|----------|-----------|--------------|
| A | 다단계 워크플로우 진행 | 다단계 진행 (설계→태스크→구현 3세션) | 설계서 섹션 3 — 작업량 큼(프론트+백엔드 동시 수정), 디버깅 추적성 확보 |
| B | 백엔드→프론트 노출 방식 | WS `engine-status` + `initial-snapshot` 필드 추가 (`get_market_phase()` 경유) | 설계서 섹션 3 — 기존 WS 패턴 재사용, 별도 API 불필요 (P24) |
| C | `chart_reference_trading_day` 필드 위치 | `market_phase` dict 내부 (최상위 분리 안 함) | 설계서 섹션 2.1 결정 1 — phase 파생 데이터 집중 (P23) |
| D | `isPreOpenPhase()` 제거 여부 | 제거 안 함 — 함수 내부만 교체 (시그니처 유지) | 설계서 섹션 2.2 기각 방안 — 호출부 수정 최소화 (P24) |
| E | 빈 문자열 폴백 | 빈 문자열을 `getLocalToday()` 폴백으로 덮지 않음 — 그대로 전달 | 설계서 섹션 2.1 결정 4 — P20 폴백 금지 |
| F | `isPreOpenPhase()` 빈 문자열 처리 | `!!ref` 로 빈 문자열 시 `false` 반환 (설계서 원안 `ref !== undefined` 보완) | 본 태스크 0.5 — P21(초기 화면 동작 유지)·P25(격리) |

---

## 3. 사전 롤백 계획

> 위험도 높음 (시간/날짜 의존 로직) — 필수 (검증·관찰 계층 게이트).

### 3.1 롤백 명령

```bash
# 구현 커밋 해시는 3세션 완료 후 본 파일에 기재
git revert <구현 커밋 해시>
```

- 단일 커밋으로 예상 (단일 구현 세션). 백엔드+프론트 동일 커밋.
- 롤백 시 프론트가 다시 독자 로직(`_prevWeekday`/`PRE_OPEN_PHASES`) 사용 → 기존 상태(평일 공휴일 불일치)로 복귀. 거래 로직 무관.

### 3.2 즉시 롤백 트리거 (사용자가 확인 시 즉시 실행)

| 증상 | 발생 조건 | 영향 |
|------|----------|------|
| 수익현황 페이지 날짜 빈 문자열 표시 | WS 연결 후에도 `chart_reference_trading_day=''` 수신 | 차트/수익현황 날짜 미표시 → 사용자 의사결정 왜곡 |
| 08:00 경계 이후에도 전일 기준 유지 | 장 개시(08:00) 후에도 당일 카드가 "개장 전" + 0원 표시 | 당일 성과 미표시 → 사용자 혼란 |
| 텔레그램과 화면 날짜 불일치 지속 | 평일 공휴일에 화면과 텔레그램이 여전히 다른 날짜 기준 | 본 작업 목표 미달성 |
| 당일 카드가 "개장 전"으로 강제 0원 표시 (WS 연결 전 아님) | `isPreOpenPhase()`가 정상 시간에 `true` 오반환 | 0.5 보완안 실패 — 빈 문자열 처리 오류 |

### 3.3 잠재 리스크 (설계서 섹션 7.1 이관)

| 리스크 | 발생 조건 | 영향 | 완화 |
|--------|----------|------|------|
| 엔진 기동 전 빈 문자열 | WS 미연결 시 `chart_reference_trading_day=''` | 차트/수익현황 날짜 빈 → 표시 깨짐 가능 | 빈 문자열 시 호출부에서 차트 미표시 (P25 격리). initial-snapshot이 WS 연결 즉시 전송되므로 실제 발생 빈도 낮음 |
| 08:00 경계 지연 | phase 전환 시점과 `chart_reference_trading_day` 갱신 시점 차이 | 08:00~08:00:xx에 일시적 불일치 | `get_market_phase()`가 매 호출 시 `get_chart_reference_trading_day()` 실시간 산출 → 지연 없음 (캐시 아님) |
| 백엔드 캘린더 누락 | 휴장일 캘린더에 공휴일 미등록 | 백엔드도 잘못된 날짜 반환 | 기존 `get_chart_reference_trading_day()`의 이미 검증된 캘린더 사용 → 신규 리스크 아님 |

---

## 4. 관찰 기준

> 위험도 높음 (시간/날짜 의존 로직) — 필수 (검증·관찰 계층 게이트).

### 4.1 모의/dry-run 관찰 기간 (실계좌 적용 전)

**관찰 기간: 2세션 (모의투자/dry-run 모드)**

시간 의존 로직 버그는 특정 시간대에만 드러나므로, 다음 시간대를 관찰 기간 내에 포함해야 함:

| 관찰 시간대 | 확인 항목 | 예상 결과 |
|------------|----------|----------|
| 평일 06:47 (08:00 이전) | 화면 수익현황 날짜 = 텔레그램 손익 날짜 | 전일 거래일 (백엔드 캘린더 기반) |
| 평일 08:00~08:01 (프리마켓 개시 경계) | 당일 카드가 "개장 전" → 정상 전환 | 08:00 전환 후 당일 성과 표시 |
| 평일 10:00 (장중) | 화면 날짜 = 오늘, 당일 카드 정상 | 오늘 거래일 |
| 평일 21:00 (장마감 후) | 화면 날짜 = 오늘 유지 (당일 성과) | 오늘 거래일 (다음 거래일 전환 아님) |
| 월요일 06:47 (주말 직후) | 화면 날짜 = 금요일 = 텔레그램 날짜 | 금요일 |
| 월초 1일 06:47 (월 경계) | `getTradingMonthStart()` = 전월 1일 | 전월 1일 (당일 유지 모델) |
| **평일 공휴일 06:47** (가능 시) | 화면 날짜 = 백엔드 캘린더 직전 거래일 = 텔레그램 날짜 | 공휴일을 건너뛴 직전 거래일 (핵심 시나리오 — 설계서 1.2 시나리오 A) |

### 4.2 배포 후 모니터링 (실계좌 반영 후)

**모니터링 횟수: 3회**

| 회차 | 시간대 | 사용자 직접 비교 항목 |
|------|--------|---------------------|
| 1회 | 장 시작 (09:00 직후) | 화면 수익현황 "오늘" 날짜 ↔ 텔레그램 손익 알림 날짜 일치 |
| 2회 | 장 마감 (15:30 직후) | 화면 당일 카드 숫자 ↔ 텔레그램 일일 손익 숫자 일치 |
| 3회 | 특정 시간대 (08:00 경계 또는 평일 공휴일) | 화면 날짜 범위 ↔ 텔레그램 날짜 범위 일치 |

- 사용자가 화면 숫자와 텔레그램 숫자를 눈으로 직접 비교 (비개발자가 가장 잘할 수 있는 검증).
- 이상 시 3.1 롤백 명령 즉시 실행.
- 3회 모두 이상 없으면 안정화 판정 → 태스크 종료.

### 4.3 독립 검증 게이트 (완료 보고 후)

완료 보고 후, 별도 세션에서 **커밋 해시 + 본 태스크 파일만 주고** "이 커밋이 태스크 파일 요구사항을 실제로 충족했는지" 독립 검토. 결과를 HANDOVER "검증 결과"에 기록.

---

## 5. 바로잡음 로그

> 구현 중 태스크 기재 오류 발견 시 원인+수정 기록.

- **2026-07-31 (태스크 작성 세션 내 보완)**: 설계서 결정 3 `isPreOpenPhase()` 목표 코드의 빈 문자열 처리 누락 발견. `ref !== undefined` → `!!ref` 로 보완 (0.5절·사용자 결정 F 신설). 근거: P21(초기 화면 동작 유지)·P25(격리된 실패). 설계서 결정 4 "빈 문자열 그대로 전달" 원칙과 일치.
