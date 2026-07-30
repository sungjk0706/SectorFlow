# 태스크 분할: 수익 카드 실현손익 전용화 + 당월 차트 비거래일 제거

> **다단계 워크플로우 2세션(태스크 분할)** — 본 파일은 1세션 설계(`architecture_profit_realized_only_design.md`)를 태스크 단위로 분해.
> **작성일**: 2026-07-30
> **관련 커밋**: dc9e145 (1세션 설계 파일)
> **설계 파일**: `docs/architecture_profit_realized_only_design.md`
> **선행 구현**: 수익 카드 4종 리팩토링(`architecture_profit_cards_refactor_tasks.md` B-1~B-4, F-1~F-7) — 구현 완료. 본 작업은 그 위에서 동작.
> **구현 세션 예상**: 3세션(3-1 당일 카드 평가손익 제거 / 3-2 드릴다운 평가 영역 제거 / 3-3 차트 비거래일 필터링 + 라벨 통일)

---

## 0. 사용자 결정 사항 (1세션 확정)

| # | 결정 사항 | 확정값 | 출처 |
|---|---|---|---|
| A | 계좌현황 평가 3행 | 유지 (핵심 원칙의 예외 영역) | 1세션 결정 |
| B | 다단계 워크플로우 전환 | 승인 ("이대로 진행" → "다단계로 진행") | 1세션 결정 |

> 본 2세션은 태스크 분할만 수행. 신규 사용자 결정 사항 없음 (설계 6개 결정은 1세션에서 모두 확정).

---

## 1. 코드 조사 결과 (2세션 — 설계 대비 정정 포함)

### 1.1 프론트엔드 조사 (설계 대비 정정)

| 설계 문서 기재 | 실제 위치 | 비고 |
|---|---|---|
| `updateSummaryCards` 당일 카드 `dayPnl = realizedToday + evalPnl` | `profit-shared.ts:231` | 정확 — `dayPnl = realizedToday + evalPnl` |
| `computeHoldingsSummary.evalPnl` 합산 | `profit-shared.ts:230` | 정확 — `const { evalPnl } = computeHoldingsSummary(positions, sectorStocks)` |
| `openSubText` '최근 체결 기준' 전달 | `profit-detail-mount.ts:233, 266` (2곳) | 정확 — **profit-overview-mount.ts에는 `updateSummaryCards` 호출 없음** (설계 2.1 결정 2의 "profit-overview: 생략=''"은 profit-shared.ts:195 주석의 매개변수 규칙 설명일 뿐 실제 호출부 아님) |
| `TodayDrilldownResult` 타입 `evalRows`/`evalTotal` | `profit-math.ts:69-74` | 정확 — `realizedRows`/`evalRows`/`realizedTotal`/`evalTotal` 4필드 |
| `buildTodayDrilldown` 평가 영역 계산 | `profit-math.ts:345-359` | 정확 — `computePositionValuation` 루프 + `evalRows`/`evalTotal` |
| `buildTodayDrilldownContent` 평가 섹션 | `profit-detail-display.ts:191-209` | 정확 — "평가 손익 (현재 보유 — 최근 체결 기준)" 섹션 + "당일 총 손익" 행 |
| `buildChartFromDailySummary` `sell_count=0` → `pnl=null` | `profit-math.ts:407` | 정확 — `if (sellCount === 0) return { date: raw, pnl: null, ... }` |
| 차트 빈 데이터 라벨 "거래 내역이 없습니다" | `canvas-profit-chart.ts:225` | 정확 — `overlay.textContent = '거래 내역이 없습니다'` (마침표 없음) |
| 당일 드릴다운 "매도 내역이 없습니다." | `profit-detail-display.ts:185` | 정확 — 마침표 있음 |
| 당일 드릴다운 "보유 종목이 없습니다." | `profit-detail-display.ts:202` | 정확 — 마침표 있음 (평가 섹션 제거 시 함께 제거) |
| 5거래일 드릴다운 "5거래일 거래 내역이 없습니다." | `profit-detail-display.ts:290` | 정확 — `buildDailyDrilldownContent(rows, '5거래일 거래 내역이 없습니다.')` |
| 당월 드릴다운 "당월 거래 내역이 없습니다." | `profit-detail-display.ts:300` | 정확 — `buildDailyDrilldownContent(rows, '당월 거래 내역이 없습니다.')` |
| 누적 드릴다운 "거래 내역이 없습니다." | `profit-detail-display.ts:242` | 정확 — 마침표 있음 (월별 누적 손익 섹션) |
| 누적 드릴다운 "입금 이력이 없습니다." | `profit-detail-display.ts:257` | 정확 — 별개 개념, 유지 |
| `openTodayDrilldown` 호출부 | `profit-detail-display.ts:275-284` | 정확 — `buildTodayDrilldown(state.sellHistory, hotState.positions, hotState.sectorStocks, today)` |

### 1.2 정정 사항

1. **`openSubText` 매개변수**: 설계 2.1 결정 2는 `profit-detail-mount.ts`의 `openSubText` 인수만 `''`로 변경. `profit-overview-mount.ts`는 `updateSummaryCards`를 호출하지 않으므로 변경 대상 아님. (profit-shared.ts:195 주석의 "profit-overview: 생략=''"은 매개변수 규칙 설명일 뿐 실제 호출부 없음)
2. **`buildTodayDrilldown` 매개변수**: 설계 2.2 기각 방안에 "positions/sectorStocks 매개변수 제거는 구현 단계에서 결정" 명시. 3-2 태스크에서 평가 영역 제거 후 잔존 매개변수 제거 여부 결정 (unused 경고 발생 시 제거 권장 — P16 살아있는 경로).

### 1.3 테스트 파일 조사

| 테스트 대상 | 파일:라인 | 본 작업 영향 |
|---|---|---|
| `buildTodayDrilldown` | `profit-math.test.ts:283-330` | 3-2에서 `evalRows`/`evalTotal` 검증 3건 제거/수정 필요 (3개 it 블록) |
| `buildChartFromDailySummary` | `profit-math.test.ts:263-278` | 3-3에서 비거래일 필터링 검증 추가 필요 (현재 `sell_count=0` → `pnl=null` 유지 검증만 존재) |

---

## 2. 태스크 분할

> **원칙**: 프론트엔드 단독 작업 (백엔드 변경 없음 — 설계 1.3 비목표). 3개 구현 세션으로 분할.
> **분할 기준**: 설계 6개 결정을 3개 세션으로 그룹화 — (1) 당일 카드 계산식 + 라벨 (2) 드릴다운 타입 + 렌더 (3) 차트 필터링 + 라벨 통일.
> **순서 의존성**: 3-1 → 3-2 (당일 카드 계산식 변경 후 드릴다운 정합성 맞춤). 3-3은 독립 (병행 가능하나 가독성을 위해 순차 진행 권장).

### 3-1. 당일 카드 평가손익 합산 제거 + 서브 텍스트 라벨 제거

> **설계 결정 1, 2**. 핵심 원칙("모든 손익 카드는 실현손익만") 준수.
> **수정 파일**: `profit-shared.ts`, `profit-detail-mount.ts` (2개)

#### 3-1-1. `updateSummaryCards` 당일 카드 계산식 변경
- **파일**: `frontend/src/pages/profit-shared.ts:226-234`
- **변경**: `dayPnl = realizedToday + evalPnl` → `dayPnl = realizedToday`
- **상세**:
  - `computeHoldingsSummary(positions, sectorStocks)` 호출 제거 (evalPnl 사용 제거)
  - `realizedToday` 계산 유지 (sellHistory 오늘 매도 realized_pnl 합)
  - `dayRate` 계산 유지 (`dayBaseAsset != null ? computeWeightedRate(dayPnl, dayBaseAsset) : null`)
  - `els.todaySubTextEl.textContent = openSubText ?? ''` 유지 (개장 중 서브 텍스트는 3-1-2에서 ''로 변경)
- **주석 수정**: 184줄 "08:00+ → 오늘 실현(sellHistory 오늘 매도 realized_pnl 합) + 보유 평가(computeHoldingsSummary.evalPnl)" → "08:00+ → 오늘 실현(sellHistory 오늘 매도 realized_pnl 합)만" (P23 용어 일관 — 평가 제거 명시)
- **원칙**: P10(실현 SSOT), P21(평가손익 혼란 제거), P22(당일 카드=실현만 정합성 단순화)

#### 3-1-2. `profit-detail-mount.ts` `openSubText` 인수 ''로 변경
- **파일**: `frontend/src/pages/profit-detail-mount.ts:233, 266` (2곳)
- **변경**: `'최근 체결 기준'` → `''`
- **주석 수정**: 233줄/266줄 "P21 투명성 — 수익상세는 실시간 틱 미반영, 최근 체결 기준 평가손익" → "P21 투명성 — 당일 카드는 실현손익만 (평가손익 제거)" (P23 용어 일관)
- **사유**: 평가손익 제거되었으므로 "최근 체결 기준" 라벨 불필요 (실현손익은 체결 완료값). 개장 전 "개장 전" 라벨은 유지 (profit-shared.ts:224).
- **원칙**: P21(투명성 — 불필요 라벨 제거), P23(용어 일관)

#### 3-1-3. `updateSummaryCards` 매개변수 `positions`/`sectorStocks` 잔존 검토
- **파일**: `frontend/src/pages/profit-shared.ts:186-196`
- **검토**: 3-1-1에서 `computeHoldingsSummary` 호출 제거 후 `positions`/`sectorStocks` 매개변수가 unused 됨. 제거 시 호출부 2곳(profit-detail-mount.ts:227, 260) 시그니처 변경 동반.
- **결정**: **매개변수 유지** (3-2에서 `buildTodayDrilldown`이 동일 매개변수 사용하므로 3-2 완료 후 통합 검토). unused 경고는 TypeScript strict 모드에서 에러 아님(메서드 매개변수는 허용). 제거 시 P16 검증 필요.
- **비고**: 설계 2.2 기각 방안에 "매개변수 제거 검토는 구현 단계에서 결정" 명시됨.

#### 3-1-V. 검증
- `cd frontend && npm run typecheck` — 타입 에러 없음
- `cd frontend && npm run test` — 기존 테스트 통과 (buildTodayDrilldown 테스트는 3-2에서 수정, updateSummaryCards 테스트는 DOM 의존으로 vitest 대상 아님)
- `cd frontend && npm run build` — 빌드 성공

---

### 3-2. buildTodayDrilldown 평가 영역 제거 + 드릴다운 콘텐츠 평가 섹션 제거

> **설계 결정 3, 4**. 당일 드릴다운 모달도 핵심 원칙 준수 (실현 영역만 표시).
> **수정 파일**: `profit-math.ts`, `profit-detail-display.ts`, `profit-math.test.ts` (3개)

#### 3-2-1. `TodayDrilldownResult` 타입에서 평가 필드 제거
- **파일**: `frontend/src/pages/profit-math.ts:61-74`
- **변경**:
  - `TodayDrilldownEvalRow` 인터페이스 제거 (61-67줄)
  - `TodayDrilldownResult`에서 `evalRows`/`evalTotal` 필드 제거 → `realizedRows`/`realizedTotal`만 남김 (69-74줄)
  - 53줄 주석 "당일 드릴다운 행 (실현/평가 영역 구분 — P22 정합성: 실현+평가=당일 카드 총액)" → "당일 드릴다운 행 (실현 영역만 — 핵심 원칙: 실현손익만)" (P23 용어 일관)
- **원칙**: P24(타입 단순화), P22(정합성 단순화 — 실현만)

#### 3-2-2. `buildTodayDrilldown` 평가 영역 계산 제거
- **파일**: `frontend/src/pages/profit-math.ts:321-362`
- **변경**:
  - 321-324줄 docstring "실현(오늘 매도) + 평가(현재 보유) 영역 구분 (F-3-d, 결정 3·11)" → "실현(오늘 매도) 영역만 (핵심 원칙: 실현손익만)" (P23 용어 일관)
  - 324줄 "P22 정합성: realizedTotal + evalTotal = 당일 카드 총액" → "P22 정합성: realizedTotal = 당일 카드 총액 (3-1에서 평가 합산 제거와 일치)" (P23 용어 일관)
  - 345-359줄 `evalRows`/`evalTotal` 계산 루프 제거 (`computePositionValuation` 호출 제거)
  - 361줄 `return { realizedRows, evalRows, realizedTotal, evalTotal }` → `return { realizedRows, realizedTotal }`
- **매개변수 검토**: `positions`/`sectorStocks` 매개변수가 unused 됨. 제거 시 `openTodayDrilldown`(profit-detail-display.ts:278) 호출부 시그니처 변경 동반.
  - **결정**: **매개변수 제거** (3-1-3에서 유지 결정한 `updateSummaryCards` 매개변수와 별개 — `buildTodayDrilldown`은 평가 영역 제거 후 완전히 unused). 호출부 `openTodayDrilldown`에서 `hotState.positions, hotState.sectorStocks` 인수 제거.
  - **사유**: P16(살아있는 경로 — unused 매개변수는 dead parameter), P24(단순성 — 불필요 매개변수 제거)
- **원칙**: P16(살아있는 경로), P24(단순성)

#### 3-2-3. `buildTodayDrilldownContent` 평가 섹션 제거
- **파일**: `frontend/src/pages/profit-detail-display.ts:170-212`
- **변경**:
  - 170줄 주석 "당일 드릴다운 모달 콘텐츠 — 실현/평가 영역 구분 (P22 정합성: 실현+평가=당일 카드 총액)" → "당일 드릴다운 모달 콘텐츠 — 실현 영역만 (핵심 원칙: 실현손익만)" (P23 용어 일관)
  - 191-206줄 "평가 손익 (현재 보유 — 최근 체결 기준)" 섹션 전체 제거 (섹션 타이틀 + evalRows 테이블 + "보유 종목이 없습니다." + "평가 합계" 행)
  - 208-209줄 "당일 총 손익" 행 제거 (실현 합계만 표시하므로 중복 — 189줄 "실현 합계"와 동일)
  - 185줄 "매도 내역이 없습니다." → "거래 내역이 없습니다." (3-3 라벨 통일과 일관, 단 3-3에서 전체 통일하므로 여기서 미리 변경 가능 — 3-3에서 중복 검증)
- **잔존 구조**: "실현 손익 (오늘 매도)" 섹션 타이틀 + 실현 테이블 + "실현 합계" 행만 남김
- **원칙**: P21(평가손익 혼란 제거), P22(실현만 정합성), P24(렌더 단순화)

#### 3-2-4. `openTodayDrilldown` 호출부 시그니처 변경
- **파일**: `frontend/src/pages/profit-detail-display.ts:275-284`
- **변경**: `buildTodayDrilldown(state.sellHistory, hotState.positions, hotState.sectorStocks, today)` → `buildTodayDrilldown(state.sellHistory, today)` (3-2-2 매개변수 제거에 따른 호출부 동기화)
- **원칙**: P16(살아있는 경로 — 호출부와 정의 일치)

#### 3-2-5. `profit-math.test.ts` `buildTodayDrilldown` 테스트 수정
- **파일**: `frontend/tests/pages/profit-math.test.ts:283-330`
- **변경**:
  - 298-314줄 "실현(오늘 매도) + 평가(현재 보유) 영역 구분" it 블록: `evalRows`/`evalTotal` 검증 제거 (311-313줄). 실현 검증(307-309줄) 유지. it 설명 → "실현(오늘 매도) 영역만"
  - 316-322줄 "오늘 매도 없음 + 보유 없음" it 블록: `evalRows`/`evalTotal` 검증 제거 (319, 321줄). `realizedRows`/`realizedTotal` 검증 유지
  - 324-329줄 "cur_price null인 보유종목은 평가에서 제외 (P21)" it 블록: **전체 제거** (평가 영역 제거로 테스트 대상 소멸)
  - `makePosition`/`makeSectorStock` 헬퍼(284-296줄): 잔존 사용처 확인 후 unused면 제거 (3-2-5에서 모든 평가 테스트 제거 시 unused)
- **신규 테스트 추가**: "오늘 매도 있음 + 보유 있음 → 실현만 반환 (평가 무시)" — positions/sectorStocks 매개변수 제거 후 평가 데이터가 결과에 영향 없음 검증 (매개변수 제거한 경우 불필요, 유지한 경우 필요)
- **원칙**: P16(테스트-코드 정합성), P22(테스트 정합성)

#### 3-2-V. 검증
- `cd frontend && npm run typecheck` — 타입 에러 없음 (TodayDrilldownEvalRow 제거로 인한 잔존 참조 없음)
- `cd frontend && npm run test` — 수정된 buildTodayDrilldown 테스트 통과
- `cd frontend && npm run build` — 빌드 성공

---

### 3-3. buildChartFromDailySummary 비거래일 필터링 + 빈 데이터 라벨 통일

> **설계 결정 5, 6**. 당월 차트 가독성 향상 + P23 라벨 일관성.
> **수정 파일**: `profit-math.ts`, `profit-detail-display.ts`, `profit-math.test.ts` (3개)

#### 3-3-1. `buildChartFromDailySummary` 비거래일 필터링 추가
- **파일**: `frontend/src/pages/profit-math.ts:402-417`
- **변경**: `sell_count=0 && buy_count=0`인 행을 배열에서 제외 (filter 추가)
- **상세**:
  - 현재: `sell_count=0` → `pnl=null` (빈 막대 표시). 모든 달력일 포함.
  - 변경: `sell_count=0 && buy_count=0` → 배열에서 제외 (filter). 매수만 있거나 매도만 있는 날은 유지 (거래 데이터 존재).
  - 구현: `summary.filter(r => Number(r.sell_count ?? 0) > 0 || Number(r.buy_count ?? 0) > 0).map(...)` 또는 map 후 filter (`pnl != null || buyCount > 0`).
  - **주의**: `sell_count=0 && buy_count>0`인 날(매수만 있는 날)은 `pnl=null` 유지 (매도 없으므로 실현손익 없음)하지만 차트에 표시 (거래 데이터 존재). 현재 로직 `if (sellCount === 0) return { ..., pnl: null, ... }` 유지 가능 — filter만 추가.
- **주석 수정**: 402줄 "매도 없는 날(sell_count=0)은 pnl=null로 표시 → 막대 안 그림" → "비거래일(sell_count=0 && buy_count=0)은 배열에서 제외. 매도 없는 날(sell_count=0, buy_count>0)은 pnl=null로 표시 → 막대 안 그림" (P23 용어 일관)
- **사유**: 백엔드 휴장일 캘린더 의존 없이 P24 단순성 부합. 공휴일 건너뛰기는 HANDOVER 후순위 항목.
- **원칙**: P20(비거래일 필터링은 거래일 정의 기반 — 빈 데이터 숨김이 아님), P24(프론트 단독 처리)

#### 3-3-2. 빈 데이터 라벨 "거래 내역이 없습니다"로 통일
- **파일**: `frontend/src/pages/profit-detail-display.ts`
- **변경 대상 및 통일값**:

| 위치 | 현재 | 변경 | 비고 |
|---|---|---|---|
| 185줄 (당일 드릴다운 실현 빈) | "매도 내역이 없습니다." | "거래 내역이 없습니다." | 3-2-3에서 미리 변경한 경우 중복 — 3-3에서 최종 확인 |
| 202줄 (당일 드릴다운 평가 빈) | "보유 종목이 없습니다." | **제거** (3-2-3에서 평가 섹션 제거) | 3-2 완료 시 이미 제거됨 |
| 290줄 (5거래일 드릴다운 빈) | "5거래일 거래 내역이 없습니다." | "거래 내역이 없습니다." | `buildDailyDrilldownContent` 호출부 인수 변경 |
| 300줄 (당월 드릴다운 빈) | "당월 거래 내역이 없습니다." | "거래 내역이 없습니다." | `buildDailyDrilldownContent` 호출부 인수 변경 |
| 242줄 (누적 월별 빈) | "거래 내역이 없습니다." | 유지 | 이미 통일값 |
| 257줄 (누적 입금 빈) | "입금 이력이 없습니다." | 유지 | 별개 개념 (입금 ≠ 거래) |
| `canvas-profit-chart.ts:225` (차트 빈) | "거래 내역이 없습니다" | 유지 | 기준 라벨 (마침표 없음 — 차트 오버레이 스타일) |

- **마침표 일관성**: 드릴다운 모달 라벨은 마침표 있음("."), 차트 오버레이는 마침표 없음. 이는 서로 다른 UI 컨텍스트(모달 vs 캔버스 오버레이)이므로 각 컨텍스트 내에서 일관성 유지. 드릴다운 라벨은 모두 마침표 있는 "거래 내역이 없습니다."로 통일.
- **원칙**: P23(라벨 일관성 — 동일 개념 동일 표현)

#### 3-3-3. `profit-math.test.ts` `buildChartFromDailySummary` 테스트 보강
- **파일**: `frontend/tests/pages/profit-math.test.ts:263-278`
- **변경**:
  - 264-274줄 "매도 있는 날 → pnl/rate/fee/tax 추출" it 블록: 현재 `sell_count=0` 행이 `pnl=null`로 유지됨 검증. 3-3-1 필터링 후 `sell_count=0 && buy_count=0` 행은 **제거**되므로 테스트 수정 필요.
    - 현재 데이터: `[{date:'2026-07-28', sell_count:2, ...}, {date:'2026-07-29', sell_count:0, buy_count:0, ...}]`
    - 변경 후: 2번째 행 제거 → `rows.toHaveLength(1)` (또는 `buy_count>0` 추가하여 유지 검증)
  - **신규 테스트 추가**:
    - "비거래일(sell_count=0 && buy_count=0) 제외" — `sell_count=0, buy_count=0` 행이 배열에서 제외됨 검증
    - "매수만 있는 날(sell_count=0, buy_count>0) 유지 → pnl=null" — 매도 없지만 거래 데이터 있으므로 유지, `pnl=null` 검증
- **원칙**: P16(테스트-코드 정합성), P20(필터링 검증)

#### 3-3-V. 검증
- `cd frontend && npm run typecheck` — 타입 에러 없음
- `cd frontend && npm run test` — 수정/추가된 buildChartFromDailySummary 테스트 통과
- `cd frontend && npm run build` — 빌드 성공

---

## 3. 전체 검증 (3-1, 3-2, 3-3 완료 후)

> 각 세션 종료 시 해당 세션의 V 태스크 수행. 3개 세션 모두 완료 후 아래 전체 검증 수행 (선택 — 중복이나 안전망).

- `cd frontend && npm run typecheck` — 전체 타입 에러 없음
- `cd frontend && npm run test` — 전체 116 tests 통과 (buildTodayDrilldown/buildChartFromDailySummary 수정분 반영)
- `cd frontend && npm run build` — 빌드 성공
- **브라우저 화면 확인 (사용자)**: 개발 서버(`npm run dev`) 실행 후 수익현황/수익상세 페이지에서 3가지 결함 수정 결과 확인:
  1. 당일 카드에 평가손익 합산 제거 (실현손익만 표시)
  2. 당일 드릴다운 모달 평가 섹션 제거 (실현 영역만)
  3. 당월 차트 비거래일 빈 막대 제거 (거래일만 표시)
  4. 빈 데이터 라벨 "거래 내역이 없습니다." 통일

---

## 4. 아키텍처 원칙 부합 (태스크별)

| 태스크 | 주요 원칙 | 부합 근거 |
|---|---|---|
| 3-1 | P10, P21, P22, P23 | 실현 SSOT, 평가 혼란 제거, 당일 카드=실현만 정합성, 주석 용어 일관 |
| 3-2 | P16, P21, P22, P24 | unused 매개변수 제거(살아있는 경로), 평가 섹션 제거(투명성), 실현만 정합성, 타입·렌더 단순화 |
| 3-3 | P20, P23, P24 | 비거래일 필터링(거래일 정의 기반), 라벨 통일, 프론트 단독 처리(백엔드 의존 최소) |

---

## 5. 비목표 (다루지 않는 것 — 설계 1.3 준수)

- **계좌현황 평가 3행 유지**: 보유 종목 평가금액/평가손익/평가수익률은 계좌현황 섹션에서 유지 (사용자 결정 A)
- **보유종목 페이지 평가 유지**: `sell-position.ts`의 평가 계산은 유지
- **공휴일 캘린더 동기화**: 백엔드 휴장일 캘린더를 프론트에 동기화하는 작업은 별도 후순위 (HANDOVER 미해결 문제)
- **백엔드 dailySummary 비거래일 생성 로직 수정**: 프론트 `buildChartFromDailySummary`에서 필터링 (P24 단순성)
- **`computePositionValuation`/`computeHoldingsSummary` 제거**: 계좌현황·보유종목 페이지에서 계속 사용 (3-2에서 `buildTodayDrilldown` 사용처만 제거)
