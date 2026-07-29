# 태스크 분할: 수익 상세/수익현황 기간별 카드 4종 + 드릴다운 리팩토링

> **다단계 워크플로우 2세션(태스크 분할)** — 본 파일은 1세션 설계(`architecture_profit_cards_refactor_design.md`)를 태스크 단위로 분해.
> **작성일**: 2026-07-30
> **관련 커밋**: 0951aae (1세션 설계 파일)
> **설계 파일**: `docs/architecture_profit_cards_refactor_design.md`
> **선행 구현**: 기초자산 분모 방식(`architecture_base_asset_denominator_tasks.md` B-1~B-7, F-1~F-7) + 개장 전 거래일 판정(`architecture_trading_day_premarket_tasks.md` F-1~F-4) — 모두 구현 완료. 본 리팩토링은 그 위에서 동작.

---

## 0. 사용자 결정 사항 (1세션 + 2세션 확정)

| # | 결정 사항 | 확정값 | 출처 |
|---|---|---|---|
| 1 | 카드 구조 | 4개(당일/5거래일/당월/누적). 전일 카드 제거 | 1세션 결정 |
| 2 | 드릴다운 형태 | 공통 모달(`dialog.ts`). 인라인 토글 제거 | 1세션 결정 |
| 3 | 당일 드릴다운 범위 | 실현+평가 둘 다. 카드 총액 = 모달 합계 100% 일치 | 1세션 결정 |
| 4 | 누적 드릴다운 범위 | 입금 히스토리 + 월별 누적 손익. 출금 후순위 | 1세션 결정 |
| 5 | 실전 분모 기준 | 증권사 API total_asset 스냅샷. buyTotal 분모 전면 폐지 | 1세션 결정 |
| 6 | 당일 카드 PRE_OPEN 표시 | 0원(0.00%) + "개장 전" 서브 텍스트 | 1세션 결정 |
| 7 | 거래일 기준일 분리 | 당일 = `getLocalToday()` + PRE_OPEN 강제 0. 기간 = "오늘 제외" 기준 | 1세션 결정 |
| 8 | 20:00~24:00 조기 리셋 | 방지(다음날 전환 금지) | 1세션 결정 |
| 9 | **업종 도넛 rate 분모** | **도넛 rate 제거(B) — 금액(손익 원금)만 표시, buyTotal 분모 제거** | 2세션 결정 |
| 10 | **earliest_base_asset 전달 방식** | **dailySummary 확장** (별도 API 배제, P24 단순성) | 2세션 결정 |
| 11 | **당일 실현+평가 합산 데이터 조립** | **프론트 조립** (현행 sellHistory + positions/sectorStocks, 백엔드 추가 최소) | 2세션 결정 |
| 12 | **구현 세션 분할** | **2세션 분할(백/프론트)**: 3세션 백엔드 B-1~B-4, 4세션 프론트 F-1~F-7 | 2세션 결정 |

### 결정 9 상세 (사용자 2세션 결정)

- **배경**: 설계 5.4절에서 (A) buyTotal 유지 vs (B) 도넛 rate 제거 중 사용자 결정 권장.
- **선택**: (B) 도넛 rate 제거 — 도넛에 rate 표시 제거, 손익 금액만 표시.
- **근거**: buyTotal 분모 "전면 폐지" 기획에 부합. 도넛 rate 분모 논쟁 원천 제거. 업종별 손익 분포는 금액으로 충분.
- **구현**: `buildSectorDonutRows` 반환에서 `rate` 필드 제거, 도넛 렌더링에서 rate 표시 제거.

### 결정 10 상세 (사용자 2세션 결정)

- **선택**: dailySummary 응답에 `earliest_base_asset` 필드 1개 추가.
- **배제**: 별도 API 추가 — dailySummary 확장이 API 추가보다 단순 (P24).
- **구현**: `get_daily_summary` 반환 행에 `earliest_base_asset` 필드 포함 (모든 행 동일 값, 누적 카드 분모용).

### 결정 11 상세 (사용자 2세션 결정)

- **선택**: 프론트에서 현행 데이터로 조립.
- **근거**: `sellHistory`(오늘 매도) + `positions`/`sectorStocks`(현재 보유)가 이미 프론트에 있음 (P10 SSOT). 백엔드 추가 최소.
- **구현**: `buildTodayDrilldown(sellHistory, positions, sectorStocks, today)` 프론트 빌더 함수.

### 결정 12 상세 (사용자 2세션 결정)

- **3세션 (백엔드)**: B-1 ~ B-4 + 백엔드 pytest
- **4세션 (프론트엔드)**: F-1 ~ F-7 + 프론트엔드 typecheck/test/build + V-1
- **근거**: 백엔드 완료 후 프론트 착수 (B-2 dailySummary 확장이 있어야 F-3 소비 가능).

---

## 1. 코드 조사 결과 (2세션 — 설계 대비 정정 포함)

### 1.1 백엔드 조사 (설계 대비 정정)

| 설계 문서 기재 | 실제 위치 | 비고 |
|---|---|---|
| `get_earliest_base_asset` (신규) | 존재하지 않음 | 신규 구현 필요 (B-1) |
| `get_daily_summary` | `backend/app/services/trade_history.py:599-710` | `base_asset` 필드 포함(라인 703-708), `earliest_base_asset` 없음 |
| `account_daily_snapshot` 테이블 | `backend/app/db/stock_tables.py:60-72` | total_asset/daily_deposit/daily_withdrawal 모두 존재 (선행 구현 완료) |
| 입금 이력 조회 | `settlement_engine.get_daily_deposit_total()` (151-153줄) — **당일 누적만**. 과거 일자별 조회 함수 없음 | 신규 필요 (B-3) |
| 실전 total_asset 스냅샷 | `market_close_pipeline.py:510-553` `_save_daily_snapshot` | `deposit + total_eval_amount` (실전), `orderable + total_eval` (테스트). 정합성 확인 필요 (B-4) |
| `get_chart_reference_trading_day` | `trading_calendar.py:384-411` | 08:00 기준 (`_NXT_PREMARKET_HOUR = 8`) |
| `stock_tables.py` 경로 | `backend/app/db/stock_tables.py` | `services/` 아님 (설계 기재와 일치) |
| `trade_history.py` 경로 | `backend/app/services/trade_history.py` | 정확 |
| `trade.py` 라우트 | `backend/app/web/routes/trade.py` | `/api/trade-history/daily-summary` (라인 33-41) |
| 기존 조회 함수 | `get_account_snapshot_by_date` (stock_tables.py:196-220), `get_base_asset_for_period` (stock_tables.py:223-239) | 선행 구현 완료 |

> **정정**: 설계 1.2절 "buyTotal 분모 사용"은 선행 구현(기초자산 분모)에서 이미 `base_asset` 분모로 전환 완료. 본 리팩토링의 "buyTotal 폐지"는 **잔존 buyTotal 분모 경로**(실전 누적 카드, 도넛 rate) 한정.

### 1.2 프론트엔드 조사 (설계 대비 정정)

| 설계 문서 기재 | 실제 | 비고 |
|---|---|---|
| `getLocalMonthStart()` 사용처 | **함수 존재하지 않음** | 이전 다단계(개장 전 거래일)에서 `getTradingMonthStart()`로 전환 완료. 본 리팩토링은 `getLocalMonthStart` 제거 대상 아님 |
| `AccountSnapshot.total_asset` | **필드 존재하지 않음** | 신규 추가 필요 (F-2). 설계 8.2절 "확인" → "추가"로 정정 |
| `computeCumulativePnl` `baseAsset` 필드 | **이미 존재** (profit-shared.ts:374) | 선행 구현에서 추가됨. `earliestBaseAsset` 필드만 신규 추가 |
| `computeCumulativePnl` 테스트 | **존재** (profit-shared.test.ts, computeCumulativePnl describe 블록) | 설계 "테스트 없음" → 정정. 회귀 테스트 추가 필요 |
| `date.test.ts` | **존재** (110줄, getTradingToday/getTradingMonthStart 테스트) | `isPreOpenPhase` 테스트만 추가 |
| `computeWeightedRate` 위치 | `ui-styles.ts` (profit-shared.ts에서 import) | 정확 |
| 카드 개수 | 5개 (SUMMARY_CARD_TITLES:72, createSummaryCards:113-148) | 정확 — 4개로 축소 |
| `SelectedView` 'prev'/'drilldown' | 존재 (profit-detail.ts:32) | 정확 — 제거 대상 |
| `quickDateRangesConfig` 5개 | 정확 (profit-overview-mount.ts:280-286) | 4개로 축소 |
| `makeCenterTitle` '전일' 분기 | 존재 (profit-overview-mount.ts:62) | 제거 대상 |
| `CustomDialogOptions` | 존재 (dialog.ts:21-29) | 드릴다운 모달 재사용 |

### 1.3 computeCumulativePnl 사용처 (정정 — 선행 구현 후 상태)

| # | 함수 | 파일:라인 | 현재 분모 | 본 리팩토링 변경 |
|---|---|---|---|---|
| 1 | updateSummaryCards (당일) | profit-shared.ts:191 | baseAsset (전일) + daily_deposit | 당일 실현+평가 계산식으로 교체 |
| 2 | updateSummaryCards (전일) | profit-shared.ts:193 | baseAsset | **제거** (전일 카드 폐지) |
| 3 | updateSummaryCards (5거래일) | profit-shared.ts:196 | baseAsset | 유지 (분모 규칙 동일) |
| 4 | updateSummaryCards (당월) | profit-shared.ts:198 | baseAsset | 유지 |
| 5 | updateSummaryCards (누적) | profit-shared.ts:199 | 테스트=accumulated_investment, **실전=buyTotal** | 실전=earliestBaseAsset로 교체 (buyTotal 폐지) |
| 6 | renderAccountVals | profit-shared.ts:565-567 | 동일 (누적 모드) | 동일 (5번과 동일 변경) |
| 7 | buildDonutCenter | profit-overview-mount.ts:74-80 | baseAsset | 유지 (기간 카드) |
| 8 | updateStatistics | profit-detail-display.ts:157-163 | baseAsset | 유지 |

> **P10/P23 일관성**: 8곳 모두 `computeCumulativePnl` SSOT 호출. 본 리팩토링은 #1(당일 계산식 교체), #2(제거), #5/#6(실전 누적 buyTotal→earliestBaseAsset) 4곳 변경.

### 1.4 도넛 rate 잔존 경로 (결정 9 — rate 제거)

| 위치 | 현재 | 변경 |
|---|---|---|
| `buildSectorDonutRows` (profit-shared.ts:243-260) | `rate: computeWeightedRate(pnl, buyTotal)` 필드 반환 | `rate` 필드 제거, `buyTotal` 필드 제거 |
| 도넛 렌더링 (rate 표시 부분) | rate 표시 | 금액만 표시 |
| `computeWeightedRate` (ui-styles.ts) | 도넛 rate 계산 | 도넛 사용 처소 제거 후 잔존 사용처 확인 (다른 곳에서 사용 시 유지) |

---

## 2. 태스크 분할

> **원칙**: 백엔드 태스크(B-*) → 프론트엔드 태스크(F-*) 순서. 백엔드가 earliest_base_asset 데이터를 제공해야 프론트가 소비 가능.
> 각 태스크는 독립 커밋 단위. 태스크 완료 시마다 검증 게이트 통과 필수.

### 2.1 백엔드 태스크 (B-1 ~ B-4)

#### B-1: `get_earliest_base_asset()` 구현 + 테스트

- **파일**: `backend/app/db/stock_tables.py` (기존 `get_base_asset_for_period` 다음, 239줄 이후)
- **함수 시그니처**:
```python
async def get_earliest_base_asset(conn, *, trade_mode: str) -> int | None:
    """해당 모드의 가장 오래된 total_asset 반환 (누적 카드 분모용).
    account_daily_snapshot에서 trade_mode 필터 후 가장 오래된 date의 total_asset.
    없으면 None (프론트에서 rate null → '-' 표시, P20 폴백 금지)."""
    cursor = await conn.execute(
        """SELECT total_asset FROM account_daily_snapshot
           WHERE trade_mode = ? AND total_asset > 0
           ORDER BY date ASC LIMIT 1""",
        (trade_mode,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return int(row["total_asset"]) if row else None
```
- **패턴**: 기존 `get_base_asset_for_period` 패턴 준수 (`ORDER BY date ASC` 차이 — 가장 오래된 것)
- **P10 SSOT**: `account_daily_snapshot.total_asset` 단일 소스
- **P20 폴백 금지**: None 반환 시 프론트에서 rate null → "-" 표시 (buyTotal로 덮지 않음)
- **검증**: `.venv/bin/python -m pytest backend/tests -q` (신규 테스트: 스냅샷 있음/없음 케이스)
- **커밋**: `feat: get_earliest_base_asset 조회 함수 추가 (누적 카드 분모용)`

#### B-2: `get_daily_summary`에 `earliest_base_asset` 필드 추가 + 테스트

- **파일**: `backend/app/services/trade_history.py` `get_daily_summary` (599-710줄)
- **변경**: `daily_map[d]` 구성 시 `earliest_base_asset` 필드 추가 (모든 행 동일 값)
```python
# 함수 시작 부근에서 1회 조회 (매 행마다 조회하지 않음 — P24 단순성)
earliest_base_asset = await get_earliest_base_asset(conn, trade_mode=trade_mode)

# daily_map[d] 구성 시 (703-708줄 부근)
daily_map[d] = {
    "date": d,
    ...기존 필드...,
    "base_asset": await get_base_asset_for_period(conn, date_from=d, trade_mode=trade_mode),
    "earliest_base_asset": earliest_base_asset,  # 신규 (모든 행 동일 값)
}
```
- **import 추가**: `from backend.app.db.stock_tables import get_earliest_base_asset` (기존 `get_base_asset_for_period` import 옆)
- **P10 SSOT**: dailySummary가 일별 데이터 + 누적 분모 단일 소스
- **P24 단순성**: `earliest_base_asset`은 함수 시작 부근에서 1회 조회 (매 행마다 조회 금지)
- **검증**: `.venv/bin/python -m pytest backend/tests -q` (daily_summary에 earliest_base_asset 필드 존재, 모든 행 동일 값)
- **커밋**: `feat: get_daily_summary earliest_base_asset 필드 추가 (dailySummary 확장)`

#### B-3: 누적 드릴다운용 입금 이력 조회 함수 + 라우트 + 테스트

- **파일 1**: `backend/app/db/stock_tables.py` (B-1 함수 다음)
- **신규 함수**:
```python
async def get_deposit_history(conn, *, trade_mode: str) -> list[dict]:
    """누적 드릴다운용 입금 이력 조회.
    account_daily_snapshot에서 daily_deposit > 0인 행의 date, daily_deposit 반환.
    date 오름차순 정렬."""
    cursor = await conn.execute(
        """SELECT date, daily_deposit FROM account_daily_snapshot
           WHERE trade_mode = ? AND daily_deposit > 0
           ORDER BY date ASC""",
        (trade_mode,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [{"date": r["date"], "daily_deposit": int(r["daily_deposit"])} for r in rows]
```
- **파일 2**: `backend/app/web/routes/trade.py` (기존 `/api/trade-history/daily-summary` 라우트 옆)
- **신규 라우트**:
```python
@router.get("/api/trade-history/deposit-history")
async def get_deposit_history_route():
    """누적 드릴다운용 입금 이력 (date, daily_deposit 리스트)."""
    trade_mode = get_trade_mode()
    async with get_db_connection() as conn:
        history = await get_deposit_history(conn, trade_mode=trade_mode)
    return {"deposit_history": history}
```
- **P10 SSOT**: `account_daily_snapshot.daily_deposit` 단일 소스
- **P25 격리된 실패**: 라우트 실패 시 500 에러 (프론트에서 빈 리스트 폴백 금지 — P20)
- **검증**: `.venv/bin/python -m pytest backend/tests -q` (신규 테스트: 입금 이력 있음/없음 케이스)
- **커밋**: `feat: get_deposit_history 조회 함수 + 라우트 추가 (누적 드릴다운용)`

#### B-4: 실전 total_asset 스냅샷 정합성 확인 (변경 최소)

- **파일**: `backend/app/services/market_close_pipeline.py` `_save_daily_snapshot` (510-553줄)
- **확인 항목**:
  1. 실전 `total_asset = deposit + total_eval_amount` 로직 정합 (현행 유지)
  2. `account_daily_snapshot.total_asset`에 실전 값 저장됨 (현행 유지)
  3. `engine_account.py` `get_account_snapshot()` 반환에 `deposit`, `total_eval_amount` 포함 확인
- **변경**: 최소 — 정합성 확인 후 변경 불필요 시 커밋 없음 (확인 완료 자체가 완료 기준)
- **P22 데이터 정합성**: 실전 total_asset = 증권사 API 원본에서 파생 (재계산 금지)
- **검증**: `.venv/bin/python -m pytest backend/tests -q` + `.venv/bin/python -W error::RuntimeWarning main.py`
- **커밋**: 변경 시 `refactor: 실전 total_asset 스냅샷 정합성 확인 (변경 최소)` / 변경 없으면 커밋 생략

---

### 2.2 프론트엔드 태스크 (F-1 ~ F-7)

#### F-1: `utils/date.ts` `isPreOpenPhase()` 신규 + 테스트

- **파일**: `frontend/src/utils/date.ts` (기존 `getTradingToday` 다음, 42줄 이후)
- **신규 함수**:
```typescript
/** 당일 카드 개장 전(08:00 이전) 여부 — 당일 카드 0원 강제 판정.
 *  PRE_OPEN_PHASES (기존 상수, 17줄) 재사용 — P23 일관성.
 *  P10 SSOT — phase 판정은 uiStore.marketPhase 단일 소스. */
export function isPreOpenPhase(): boolean {
  const phase = uiStore.getState().marketPhase
  return PRE_OPEN_PHASES.has(phase.krx) && PRE_OPEN_PHASES.has(phase.nxt)
}
```
- **테스트**: `frontend/tests/utils/date.test.ts` (기존 파일 확장)
  - `isPreOpenPhase()` 개장 전(장개시전) → true
  - `isPreOpenPhase()` 휴장일 → true
  - `isPreOpenPhase()` 장중(정규장) → false
  - `isPreOpenPhase()` 장마감 → false
- **P23 일관성**: `PRE_OPEN_PHASES` 기존 상수 재사용, `getTradingToday` 판정과 동일 집합
- **검증**: `cd frontend && npm run typecheck && npm run test`
- **커밋**: `feat: isPreOpenPhase 함수 추가 (당일 카드 개장 전 판정)`

#### F-2: `types/index.ts` `AccountSnapshot.total_asset` 필드 추가

- **파일**: `frontend/src/types/index.ts` `AccountSnapshot` (3-16줄)
- **변경**: `total_asset?: number` 필드 추가 (실전 증권사 API 총자산 = 평가금 + 예수금)
```typescript
export interface AccountSnapshot {
  // 기존 필드...
  accumulated_investment?: number;
  daily_deposit?: number;
  total_asset?: number;  // 신규: 실전 증권사 API 총자산 (평가금 + 예수금)
  trade_mode: string;
  // ...
}
```
- **P10 SSOT**: 실전 total_asset은 증권사 API 원본 (재계산 금지)
- **검증**: `cd frontend && npm run typecheck`
- **커밋**: `feat: AccountSnapshot total_asset 필드 추가 (실전 총자산)`

#### F-3: `profit-shared.ts` 카드 4종 + 분모 폐지 + 당일 계산식 + 드릴다운 빌더 + 도넛 rate 제거 + 테스트

> **본 리팩토링 핵심 태스크** — `profit-shared.ts` 변경량이 많아 내부를 서브 스텝으로 분해.

- **파일**: `frontend/src/pages/profit-shared.ts`

##### F-3-a: 카드 5→4 (전일 제거)

- `SUMMARY_CARD_TITLES` (72줄): `['당일 손익', '전일 손익', '5거래일 손익', '당월 손익', '누적 손익']` → `['당일 손익', '5거래일 손익', '당월 손익', '누적 손익']`
- `SummaryCardEls` (45-61줄): `prevPnlEl`, `prevRateEl`, `prevCard` 필드 제거
- `createSummaryCards` (113-148줄): 루프 5→4, `clickHandlers` prev 제거
- `updateSummaryCards` (169-234줄): `prevS` 계산 제거, prev DOM 업데이트 제거
- `SummaryCardCallbacks.onPrevClick` 제거

##### F-3-b: `computeCumulativePnl` 분모 buyTotal 폐지 + earliestBaseAsset + rate null

- `CumulativePnlParams` (368-375줄): `earliestBaseAsset?: number` 필드 추가
- 반환 타입 (389줄): `{ pnl: number; rate: number }` → `{ pnl: number; rate: number | null }`
- 분모 로직:
  - 누적 카드: 테스트=`accumulated_investment`, 실전=`earliestBaseAsset` (buyTotal 폐지)
  - 기간 카드: `baseAsset ?? earliestBaseAsset` (둘 다 없으면 rate null)
  - rate null 시 호출부에서 "-" 표시 (P20 폴백 금지)
```typescript
export function computeCumulativePnl(params: CumulativePnlParams): { pnl: number; rate: number | null } {
  const { sellHistory, account, isTestMode, dateFrom, dateTo, baseAsset, earliestBaseAsset } = params
  const { pnl } = aggregatePnl(sellHistory, dateFrom, dateTo)
  const isCumulative = !dateFrom && !dateTo
  let denominator: number | null
  if (isCumulative) {
    denominator = isTestMode
      ? (account?.accumulated_investment ?? account?.initial_deposit ?? null)
      : (earliestBaseAsset ?? null)
  } else {
    denominator = baseAsset ?? earliestBaseAsset ?? null
  }
  return { pnl, rate: denominator ? computeWeightedRate(pnl, denominator) : null }
}
```

##### F-3-c: 당일 카드 실현+평가 계산식 + "개장 전" 서브 텍스트

- 당일 카드 계산 분리 (updateSummaryCards 내부):
  - PRE_OPEN (`isPreOpenPhase()`): 당일 pnl=0, rate=0, "개장 전" 서브 텍스트
  - 08:00+: 당일 손익 = 오늘 실현(`sellHistory` 오늘 매도 realized_pnl 합) + 현재 보유 평가(`computeHoldingsSummary.evalPnl`)
  - 분모 = 전일 baseAsset + account.daily_deposit
- `SummaryCardEls`에 `todaySubTextEl?: HTMLSpanElement` 추가 (당일 카드 전용)
- `createSummaryCards` 당일 카드에 서브 텍스트 요소 생성

##### F-3-d: 드릴다운 빌더 4종 신규

- `buildTodayDrilldown(sellHistory, positions, sectorStocks, today)` → `{ realizedRows, evalRows, realizedTotal, evalTotal }`
  - `realizedRows`: 오늘 매도 종목별 realized_pnl 리스트
  - `evalRows`: 현재 보유 종목별 평가손익 (`computePositionValuation` 재사용, P23)
  - `realizedTotal + evalTotal = 당일 카드 총액` (P22 정합성)
- `buildFivedayDrilldown(dailySummary)` → `DailyDrilldownRow[]` (최근 5거래일, `getRecent5TradingDays` + 일별 realized_pnl)
- `buildMonthlyDrilldown` (현행 재사용, 431-447줄)
- `buildCumulativeDrilldown(depositHistory, dailySummary)` → `{ monthlyRows[], depositHistory[] }` (신규 — 백엔드 입금 이력 소비)

##### F-3-e: 도넛 rate 제거 (결정 9)

- `buildSectorDonutRows` (243-260줄): 반환에서 `rate` 필드 제거, `buyTotal` 필드 제거
```typescript
export function buildSectorDonutRows(sells: Record<string, unknown>[]): SectorDonutRow[] {
  const pnlMap = new Map<string, number>()
  for (const r of sells) {
    const sector = String(r.sector ?? '미분류')
    const pnl = Number(r.realized_pnl ?? 0)
    pnlMap.set(sector, (pnlMap.get(sector) ?? 0) + pnl)
  }
  return Array.from(pnlMap.entries())
    .map(([sector, pnl]) => ({ sector, pnl }))  // rate, buyTotal 제거
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
}
```
- `SectorDonutRow` 타입: `rate`, `buyTotal` 필드 제거
- 도넛 렌더링: rate 표시 제거, 금액만 표시
- `computeWeightedRate` 잔존 사용처 확인 후 사용처 없으면 제거 검토 (P16 dead code)

##### F-3-f: 테스트 (profit-shared.test.ts 확장)

- 기존 `computeCumulativePnl` 테스트: rate null 반환 케이스 추가 (earliestBaseAsset 없음)
- 신규 `buildTodayDrilldown` 테스트: 실현+평가 합 = 당일 카드 총액 정합성
- 신규 `buildFivedayDrilldown` 테스트: 최근 5거래일 추출
- 신규 `buildCumulativeDrilldown` 테스트: 입금 이력 + 월별 누적
- `buildSectorDonutRows` 테스트: rate 필드 제거 회귀
- **검증**: `cd frontend && npm run typecheck && npm run test && npm run build`
- **커밋**: `refactor: profit-shared 카드 4종 + 분모 폐지 + 당일 실현평가 + 드릴다운 빌더 + 도넛 rate 제거`

#### F-4: `profit-detail-*` 4카드 + 모달 드릴다운 + prev/인라인 토글 제거

- **파일 1**: `frontend/src/pages/profit-detail.ts`
  - `SelectedView` (32줄): `'prev'`, `'drilldown'` 값 제거 → `'today' | 'fiveday' | 'month' | 'total' | null`
- **파일 2**: `frontend/src/pages/profit-detail-mount.ts`
  - `buildFilterRow` (116-157줄): "당월 거래일별 요약" 토글 버튼 제거
  - `buildSummaryRow`: 4카드 콜백을 모달 오픈 핸들러로 연결 (당일/5거래일/당월/누적 각각)
  - `drilldownViewContainer`/`drilldownTable` 인라인 경로 제거
  - `restoreInitialView`/`flushDirtyRender`: 'prev'/'drilldown' 참조 정리
- **파일 3**: `frontend/src/pages/profit-detail-display.ts`
  - `updateCardSelection`/`updateStatCardSelection`: prev 제거
  - 인라인 드릴다운 표시 함수 제거 → 모달 드릴다운 표시 함수 신규 (dialog.ts 호출)
- **P16 살아있는 경로**: 드릴다운 모달이 카드 클릭 실제 경로에 연결. 인라인 토글 dead code 제거
- **검증**: `cd frontend && npm run typecheck && npm run build`
- **커밋**: `refactor: profit-detail 4카드 + 모달 드릴다운 + prev/인라인 토글 제거`

#### F-5: `profit-overview-*` quickRange 4 + 분모 연동 + 메인-상세 일관화

- **파일 1**: `frontend/src/pages/profit-overview-mount.ts`
  - `quickDateRangesConfig` (280-286줄): 5개 → 4개 (전일 항목 제거)
  - `makeCenterTitle` (59-66줄): '전일' 분기 제거
  - `buildDonutCenter` (74-80줄): `earliestBaseAsset` 전달 (누적 카드 분모)
  - 분모 연동: dailySummary에서 `earliest_base_asset` 추출하여 누적 카드에 전달
- **파일 2**: `frontend/src/pages/profit-overview-date.ts`
  - 기본 날짜 범위 4종 정합 (전일 제거)
- **P10 SSOT**: 메인-상세 동일 카드 4종/분모/거래일 유틸 공유
- **P23 일관성**: 두 페이지 동일 카드 명칭/분모 규칙
- **검증**: `cd frontend && npm run typecheck && npm run build`
- **커밋**: `refactor: profit-overview quickRange 4 + 분모 연동 + 메인-상세 일관화`

#### F-6: `dialog.ts` 드릴다운 모달 적용

- **파일**: `frontend/src/components/common/dialog.ts` (변경 최소 — 기존 `CustomDialog` 재사용)
- **적용**: F-4/F-5에서 모달 오픈 시 `CustomDialogOptions` 전달
  - 당일: 타이틀 "당일 손익 상세", 내용 = `buildTodayDrilldown` 결과 (실현/평가 영역 구분)
  - 5거래일: 타이틀 "5거래일 손익 상세", 내용 = `buildFivedayDrilldown` 결과
  - 당월: 타이틀 "당월 손익 상세", 내용 = `buildMonthlyDrilldown` 결과
  - 누적: 타이틀 "누적 손익 상세", 내용 = `buildCumulativeDrilldown` 결과 (월별 + 입금 이력)
- **P23 일관성**: 공통 모달 재사용 (신규 모달 컴포넌트 작성 금지)
- **검증**: `cd frontend && npm run typecheck && npm run build`
- **커밋**: `feat: 드릴다운 4종 모달 적용 (공통 dialog 재사용)`

#### F-7: 전체 검증 게이트 (V-1 통합)

- **프론트엔드**:
  - `cd frontend && npm run typecheck` (`tsc --noEmit`)
  - `cd frontend && npm run test` (vitest, 기존 + F-1/F-3 신규)
  - `cd frontend && npm run build` (`tsc -b && vite build`)
- **백엔드**: B-1~B-4에서 이미 검증 (4세션에서는 회귀 확인만)
- **DB**: 스키마 변경 없음 (기존 `account_daily_snapshot` 재사용) → 백업 불필요
- **커밋**: 검증 태스크는 커밋 없음 (각 태스크 커밋 시 검증 포함)

---

## 3. 태스크 의존성 그래프

```
[3세션 — 백엔드]
B-1 (get_earliest_base_asset) → B-2 (dailySummary earliest_base_asset 확장)
B-3 (입금 이력 조회 + 라우트)        ← 독립 (B-1/B-2와 병렬 가능)
B-4 (실전 total_asset 정합성 확인)   ← 독립 (B-1/B-2와 병렬 가능)

[4세션 — 프론트엔드] (백엔드 B-2 완료 후 착수)
F-1 (isPreOpenPhase) ──┐
F-2 (AccountSnapshot.total_asset) ──┤
                                    ↓
F-3 (profit-shared 핵심: 카드4/분모폐지/당일계산/드릴다운빌더/도넛rate제거)
                                    ↓
                     F-4 (profit-detail 4카드+모달) → F-6 (dialog 모달 적용)
                                    ↓
                     F-5 (profit-overview quickRange4+분모연동) → F-6
                                    ↓
                                F-7 (전체 검증)
```

- **직렬 필수**: B-1 → B-2 (earliest_base_asset 함수가 있어야 dailySummary에 포함)
- **병렬 가능**: B-3, B-4는 B-1/B-2와 독립 (백엔드 3세션 내 병렬)
- **프론트는 백엔드 B-2 완료 후 착수**: dailySummary에 earliest_base_asset 필드가 있어야 F-3 소비 가능
- **F-1, F-2는 병렬**: 서로 독립 (date.ts, types/index.ts)
- **F-3은 F-1, F-2 완료 후**: isPreOpenPhase, total_asset 타입 필요
- **F-4, F-5는 F-3 완료 후**: profit-shared 변경이 있어야 페이지 적용
- **F-6은 F-4, F-5 완료 후**: 모달 적용 대상이 페이지에 연결되어 있어야
- **F-7은 모든 태스크 완료 후**: 최종 회귀 검증

---

## 4. 구현 순서 권장 (2세션 분할 — 사용자 결정 12)

### 4.1 3세션 (백엔드)

```
B-1 → B-2 → (B-3, B-4 병렬) → 백엔드 pytest 회귀
```

> B-3, B-4는 B-1/B-2와 독립이므로 병렬 진행 가능. 단, 단일 세션 내 순차 진행도 무방 (규모 작음).

### 4.2 4세션 (프론트엔드)

```
(F-1, F-2 병렬) → F-3 → (F-4, F-5 병렬) → F-6 → F-7
```

> F-3이 핵심 태스크 (서브 스텝 a~f 포함). F-4/F-5는 F-3 완료 후 병렬 가능. F-6은 F-4/F-5 완료 후.

---

## 5. 아키텍처 원칙 점검 (구현 완료 후 필수)

| 원칙 | 태스크 | 점검 항목 |
|---|---|---|
| P10 (SSOT) | B-2, F-3, F-5 | dailySummary가 일별 데이터 + earliest_base_asset 단일 소스. 두 페이지 카드 구조·분모·거래일 유틸 공유 |
| P16 (살아있는 경로) | F-3, F-4 | 드릴다운 모달이 카드 클릭 실제 경로에 연결. 전일 카드/인라인 토글 dead code 제거 |
| P20 (폴백 금지) | B-1, F-3 | earliest_base_asset 없으면 rate null → "-" 표시 (buyTotal로 덮지 않음). "개장 전" 명시적 상태 |
| P21 (사용자 투명성) | F-3, F-4 | "개장 전" 표시, 당일 카드-모달 정합, 분모 회전율 착시 제거 |
| P22 (데이터 정합성) | F-3 | 당일 카드 = 실현 + 평가 = 모달 합. 분모 단일 소스. 파생 데이터 중복 저장 금지 |
| P23 (일관성) | F-1, F-3, F-5 | `isPreOpenPhase` 기존 `PRE_OPEN_PHASES` 재사용. 두 페이지 동일 카드 4종/용어/네이밍. 공통 모달 재사용. `computePositionValuation` 재사용 |
| P24 (단순성) | B-2, F-3 | dailySummary 확장이 API 추가보다 단순. 전일 카드/인라인 토글 제거로 중복 축소. 도넛 rate 제거로 분모 논쟁 원천 제거 |
| P25 (격리된 실패) | B-4, F-3 | 카드/모달 단위 격리 유지. 백엔드 스냅샷 조회 실패 시 rate null (블로킹 아님) |

### 코드 제거 규칙 점검 (F-3, F-4)

- 전일 카드 제거 시: `SUMMARY_CARD_TITLES`, `SummaryCardEls`(prev*), `createSummaryCards`(루프 5→4), `updateSummaryCards`(prevS), `SummaryCardCallbacks.onPrevClick`, `SelectedView='prev'`, `colorMap.prev`, `quickDateRangesConfig` '전일' 항목, `makeCenterTitle` '전일' 분기 — 전부 제거 후 잔존 참조 grep 재검증
- 인라인 토글 제거 시: `buildFilterRow` 토글 버튼, `drilldownViewContainer`/`drilldownTable`, `SelectedView='drilldown'`, `onDrilldownToggle` — 제거 후 잔존 참조 grep 재검증
- 도넛 rate 제거 시: `buildSectorDonutRows` 반환 rate 필드, `SectorDonutRow` 타입 rate 필드, 도넛 렌더링 rate 표시, `computeWeightedRate` 잔존 사용처 확인 (사용처 없으면 제거 검토)
- 제거된 코드를 참조하는 주석/docstring 동시 정리 (P23 주석-코드 불일치 금지)

---

## 6. 후순위 (본 태스크 범위 외)

- **실전 출금 추적(`daily_withdrawal`)** — 결정 4에서 후순위 명시. 출금 API 지원 시 별도 세션.
- **백엔드 `get_current_trading_day()` 08:00 기준 미반영** — 선행 설계 1.5절에서 수정 제외 확정. 본 설계도 유지.
- **공휴일 주말 건너뛰기 미적용** — `_prevWeekday()`는 토/일만 건너뛰고 공휴일 미처리. 백엔드 휴장일 캘린더 동기화 별도 작업.
- **과거 데이터 소급 적용** — 기존 거래일의 base_asset 소급 계산 (현재는 첫 스냅샷 이후부터 적용).

---

## 7. 다음 세션 인계 사항

1. **3세션 (백엔드)**: 본 태스크 파일의 B-1 ~ B-4 순서대로 구현. B-1 → B-2 직렬, B-3/B-4 병렬 가능.
2. **4세션 (프론트엔드)**: F-1 ~ F-7 순서대로 구현. F-1/F-2 병렬 → F-3(핵심) → F-4/F-5 병렬 → F-6 → F-7.
3. **정정 사항 반영**:
   - 설계 1.2절 `getLocalMonthStart()` — 실제 함수 없음 (이전 다단계에서 `getTradingMonthStart`로 전환 완료). 본 리팩토링은 `getLocalMonthStart` 제거 대상 아님.
   - 설계 8.2절 `AccountSnapshot.total_asset` — "확인"이 아닌 "추가" 필요 (F-2).
   - `computeCumulativePnl` `baseAsset` 필드 — 이미 존재 (선행 구현). `earliestBaseAsset` 필드만 신규 추가.
   - `computeCumulativePnl` 테스트 — 이미 존재 (profit-shared.test.ts). 회귀 테스트 추가.
   - `date.test.ts` — 이미 존재 (110줄). `isPreOpenPhase` 테스트만 추가.
4. **결정 9 (도넛 rate 제거)**: `buildSectorDonutRows` 반환에서 `rate`/`buyTotal` 필드 제거, 도넛 렌더링에서 rate 표시 제거. `computeWeightedRate` 잔존 사용처 확인 후 dead code 제거 검토 (P16).
5. **결정 10 (dailySummary 확장)**: B-2에서 `get_daily_summary` 반환 행에 `earliest_base_asset` 필드 추가 (모든 행 동일 값, 함수 시작 부근에서 1회 조회 — P24).
6. **결정 11 (프론트 조립)**: 당일 실현+평가 합산은 프론트 `buildTodayDrilldown`에서 조립 (sellHistory + positions/sectorStocks 재사용, 백엔드 추가 최소).
7. **B-3 입금 이력 라우트**: `/api/trade-history/deposit-history` 신규. 프론트 `buildCumulativeDrilldown`에서 소비.
8. **각 태스크 완료 시 검증 게이트 통과 후 커밋 (코드만, HANDOVER.md 제외)**.
9. **전체 완료 후 HANDOVER.md 갱신 + 세션 완료 보고 (규칙 0-6-2/0-7)**.
