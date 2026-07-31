# 전수 조사 보고서: frontend/src 데드 코드 및 중복 함수

- 조사 일시: 2026-08-01
- 조사 범위: `frontend/src/**/*.ts` / 총 93파일
- 세션 수: 1 / 최대 30
- 조사 기준: (1) 정의됐으나 어디에서도 import/호출/참조되지 않는 함수·클래스·상수·변수(데드 코드), (2) 사용되지 않는 import, (3) 주석 처리된 코드 블록, (4) 동일/유사 구현이 여러 파일에 중복 존재하는 함수, (5) Deprecated 표시 후 방치된 함수. 단, export 중 다른 파일에서 import하는 심볼, 라우트 진입점, WS 이벤트 핸들러, DOM 이벤트 리스너는 데드 코드에서 제외.

## 요약

- 발견 문제: 9건 (high 8 / mid 1 / low 1)
- 조사 완료 파일: 93 / 93
- tsconfig `noUnusedLocals: true` + `noUnusedParameters: true` — 미사용 import/지역변수/매개변수는 tsc가 이미 검출. 본 조사는 tsc가 잡지 못하는 **미사용 export**에 집중.

## 심각도별 발견 목록

### High (8건) — 진짜 데드 코드 (삭제 대상)

#### 1. `src/pages/profit-shared.ts:12-30` — re-export 블록 전체 dead (13개 심볼)

```
export {
  type SectorStockPnl, type SectorPnlGroup, type PnlSummary,
  type CumulativePnlParams, type PositionValuation,
  getRecent5TradingDays, buildSectorDonutRows, buildSectorStockPnl,
  filterTradeRows, aggregatePnl, computeCumulativePnl,
  buildChartFromDailySummary, computePositionValuation,
  computeHoldingsSummary, computeTodayAggregates,
} from './profit-math'
```

- **상세**: profit-math.ts 분리(F-05) 시 "기존 import 경로 호환" 목적의 re-export 블록이나, 모든 호출자가 이미 직접 `./profit-math`에서 import 중. 13개 심볼 중 단 1개도 profit-shared에서 import하는 파일 없음.
- **위반 원칙**: P16 (살아있는 경로 — 호출되지 않는 dead re-export), P24 (단순성 — 불필요한 간접 경로)

#### 2. `src/api/ws.ts:284` — `subscribeFids`

```
export function subscribeFids(fids: string[]): void {
```

- 정의만 있고 프로젝트 어디에서도 호출되지 않음 (내부에서도 미사용).

#### 3. `src/components/common/broker-badge.ts:15` — `createBrokerBadge`

```
export function createBrokerBadge(broker: string, onClick?: () => void): HTMLElement {
```

- 정의만 있고 호출 없음. (동일 파일의 `BROKER_LABELS`는 header.ts에서 사용 중이므로 파일 자체는 살아있음.)

#### 4. `src/components/common/setting-row.ts:208` — `createSettingField`

```
export function createSettingField(label: string, unit?: string, child?: HTMLElement, ...): HTMLElement {
```

- 정의만 있고 호출 없음.

#### 5. `src/components/common/ui-styles.ts:308` — `createDarkSelect`

```
export function createDarkSelect(options: ..., value: string): HTMLSelectElement {
```

- 정의만 있고 호출 없음.

#### 6. `src/components/common/ui-styles.ts:331` — `setDisplay`

```
export function setDisplay(el: HTMLElement, visible: boolean): void {
```

- 정의만 있고 호출 없음.

#### 7. `src/components/virtual-scroller.ts:64` — `getOffsetFixed`

```
export function getOffsetFixed(index: number, rowHeight: number): number {
```

- 정의만 있고 내부에서도 호출 없음. (동일 파일의 다른 함수들은 `createVirtualScroller` 내부에서 사용 중이므로 파일 자체는 살아있음.)

#### 8. `src/utils/page-refresh.ts:151` — `clearPageRefreshCache`

```
export function clearPageRefreshCache(): void {
```

- 정의만 있고 호출 없음. (동일 파일의 `refreshPageData`, `createPageRefreshStatus`는 7개 페이지에서 사용 중.)

### Mid (1건) — 미사용 상수

#### 9. `src/components/common/ui-styles.ts:260,267` — `ROW_HEIGHT`, `ROW_HEIGHT_PX`

```
export const ROW_HEIGHT = { ... }
export const ROW_HEIGHT_PX = { ... }
```

- 두 상수 모두 프로젝트 어디에서도 사용되지 않음.

### Low (1건) — 불필요 export (84개 심볼)

#### 10. 84개 심볼 — `export` 키워드만 불필요 (내부에서만 사용)

- export되었으나 외부 파일에서 import되지 않고, 정의 파일 내부에서만 사용되는 심볼 84개.
- 대표적: `virtual-scroller.ts`의 `computeOffsets`, `computeVisibleRange`, `detectFixedHeight` 등 7개 (내부 `createVirtualScroller`에서만 사용), `page-refresh.ts`의 `PageRefreshOptions`, `PageRefreshResult` 등 7개 (내부 `refreshPageData`에서만 사용), `profit-overview-mount.ts`의 `applyDateRange`, `flushRender` 등.
- **위반 원칙**: P24 (단순성 — 불필요한 public API 노출), P23 (일관성 — 공통 컴포넌트는 최소 API만 노출)
- **우선순위**: 낮음. 기능 영향 없음. 캡슐화 개선 목적의 `export` 제거.

## 중복 함수 조사 결과

### 동일 이름 함수 7건 발견 — 전부 패턴/어댑터/이름 충돌 (로직 중복 아님)

| 함수명 | 파일 수 | 판정 | 근거 |
|--------|---------|------|------|
| `mount` | 12 | **패턴 (정상)** | 라우터 페이지 생명주기 계약 — 각 페이지가 독립적 mount 구현 |
| `unmount` | 12 | **패턴 (정상)** | 라우터 페이지 생명주기 계약 — 각 페이지가 독립적 unmount 구현 |
| `createState` | 4 | **패턴 (정상)** | 각 페이지가 서로 다른 상태 객체 초기화 |
| `syncFromSettings` | 4 | **패턴 (정상)** | 각 설정 페이지가 서로 다른 필드 동기화 (공통부 2줄만, 추출 비용 > 이득) |
| `buildTableArea` | 2 | **유사 구조 (경계선)** | scrollContainer + DataTable 패턴 공유. 단 DataTable 설정(컬럼/타입/가상스크롤)이 페이지별 상이. 공유부는 div 생성 4줄로 추출 이득 미미 |
| `createAmountCell` | 2 | **이름 충돌 (정상)** | ui-styles-cells.ts: 백만원→억단위 단순 셀. profit-overview-sector-pnl.ts: PnL 색상+부호+단위 복합 셀. 완전히 다른 구현 |
| `renderAccountVals` | 2 | **어댑터 패턴 (정상)** | profit-shared.ts: 공통 DOM 렌더. profit-overview-mount.ts: 상태 추출 후 공통 함수 호출하는 래퍼 |

**결론: 로직 중복 함수 0건.** 모든 동일 이름은 페이지 패턴, 어댑터, 또는 이름 충돌이며 실제 구현 중복 없음.

### 기타 조사 항목

- **주석 처리된 코드 블록**: 0건
- **Deprecated 표시 후 방치된 함수**: 0건
- **비export 데드 함수**: 0건 (tsc `noUnusedLocals`가 이미 검출)

## 권장 후속 작업 (아키텍처 부합 수정안)

> **주의**: 아래는 수정안 제시이며 사용자 승인 전 수정 불가 (AGENTS.md 규칙 0).

### 수정안 1: High 8건 데드 코드 삭제 (P16/P24)

**일괄 삭제 대상 (9개 심볼 + 1개 블록):**

| 파일 | 라인 | 대상 | 조치 |
|------|------|------|------|
| `src/pages/profit-shared.ts` | 12-30 | re-export 블록 전체 (13개 심볼) | 블록 삭제. 내부 import(33-38번 줄)는 유지 — DOM 렌더에서 사용 |
| `src/api/ws.ts` | 284~ | `subscribeFids` 함수 | 함수 삭제 |
| `src/components/common/broker-badge.ts` | 15~ | `createBrokerBadge` 함수 | 함수 삭제 (`BROKER_LABELS`는 유지) |
| `src/components/common/setting-row.ts` | 208~ | `createSettingField` 함수 | 함수 삭제 |
| `src/components/common/ui-styles.ts` | 308~ | `createDarkSelect` 함수 | 함수 삭제 |
| `src/components/common/ui-styles.ts` | 331~ | `setDisplay` 함수 | 함수 삭제 |
| `src/components/common/ui-styles.ts` | 260,267 | `ROW_HEIGHT`, `ROW_HEIGHT_PX` 상수 | 두 상수 삭제 |
| `src/components/virtual-scroller.ts` | 64~ | `getOffsetFixed` 함수 | 함수 삭제 |
| `src/utils/page-refresh.ts` | 151~ | `clearPageRefreshCache` 함수 | 함수 삭제 |

**검증**: `npm run typecheck` + `npm run build` + `npm run test` 통과 확인.

### 수정안 2: Low 84개 불필요 export 제거 (P24 — 선택적)

- 84개 심볼의 `export` 키워드 제거 (내부 전용으로 변경).
- 기능 영향 없음, 캡슐화 개선.
- **우선순위 낮음** — 별도 세션에서 일괄 처리 권장.

### 수정안 3: 중복 함수 — 조치 불필요

- 로직 중복 0건이므로 별도 조치 없음.
- `buildTableArea` 2건은 구조 유사하나 공유부가 4줄(div 생성)로 추출 이득이 미미하므로 현상 유지 권장 (P24 — 불필요한 추상화 금지).

## 원본 데이터
- 상세 조사 기록: `.devin/state/investigation_status.json`
- 분석 원시 데이터: `/tmp/fe_final.json` (truly_dead 14건 + internal_only 84건 + all_unused 98건)
