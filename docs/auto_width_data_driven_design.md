# 컬럼 자동 폭 — 데이터 분포 기반 산출 설계

> **상태**: 설계 완료 (세션 1/3 — 다단계 워크플로우)
> **다음 세션**: 태스크 파일 작성 (세션 2/3)
> **최종 세션**: 구현 + 검증 (세션 3/3)
> **작성일**: 2026-07-31

---

## 1. 배경 및 목표

### 1.1 현재 로직의 한계

현재 `auto-width.ts`의 `clampColWidth`는 각 컬럼의 폭을 다음과 같이 결정한다:

```
rawWidth = max(라벨 텍스트 폭, 데이터 샘플 최대 폭) + 셀 패딩(8px)
finalWidth = clamp(rawWidth, minWidth, maxWidth)
```

이후 `widthsToPercentages`가 전체 합으로 비율(%)을 분배한다.

**한계점**:

1. **데이터 최대 폭 사용** — 이상치 하나가 컬럼 폭을 과도하게 늘림.
   - 예: 종목명 대부분이 "삼성전자"(4자)인데 "에스케이하이닉스"(7자)가 하나면 그 폭으로 확정.
   - 예: 거래대금 대부분이 "1.2억"인데 "1,234.5억"이 하나면 그 폭으로 확정.
2. **minWidth/maxWidth 하드코딩** — `table-config.ts`의 type별 고정값 + 페이지별 덮어쓰기.
   - 데이터 특성(평균 길이, 분포)을 전혀 반영하지 못함.
   - 페이지마다 일일이 px 값을 수동 조정해야 함 (사용자 피드백: "일일이 조정하기 힘듦").
3. **첫 데이터 1회만 계산** — 이후 더 긴 값이 와도 재계산 안 함 (의도된 설계, 유지).

### 1.2 목표

- **자동 조화**: 데이터 분포를 반영하여 일일이 px 조정 불필요.
- **장중 안정성 보장**: 첫 1회 계산 후 영구 고정 (현재 설계 유지).
- **라벨 보호**: 라벨 텍스트는 항상 안 잘림 (하한선 보장).
- **안전장치**: 최소/최대 캡 유지하여 극단값 차단.
- **일괄 적용**: `auto-width.ts` 2개 함수만 수정 → 모든 페이지 자동 적용.

### 1.3 비목표 (명시적 제외)

- 장중 실시간 재계산 (사용자 명시적 거부 — "장중 변동 시 컬럼 폭 변동 절대 안 됨").
- CSS `table-layout: auto` 전환 (가상 스크롤 호환성 위험).
- 페이지별 컬럼 비율 프리셋 (수동 지정 필요, 자동화 아님).

---

## 2. 핵심 설계 결정

### 2.1 백분위 기반 폭 산출 (이상치 완화)

**현재**: `maxTextWidth = max(라벨 폭, 모든 데이터 샘플 최대 폭)`

**변경**: `maxTextWidth = max(라벨 폭, 데이터 샘플의 P95 백분위 폭)`

- P95(95백분위): 상위 5% 이상치를 무시하고, 95%의 데이터가 수용되는 폭.
- 소수의 비정상적으로 긴 값(예: 외국계 기업명, 특수 거래대금)에 컬럼이 끌려다니지 않음.
- 5% 미만 잘림은 `text-overflow: ellipsis`로 자연스럽게 처리 (이미 종목명 셀에 적용됨).

**P95 산출 알고리즘**:
```
samples가 비어 있으면 → 0 (라벨 폭만 사용)
samples.length <= 4이면 → max (샘플太少, P95 신뢰도 부족 → 기존 방식)
samples.length >= 5이면 → percentile(samples, 95)
```

**백분위 계산 (Nearest Rank 방식 — 단순·결정론적)**:
```
function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const rank = Math.ceil((p / 100) * sorted.length)
  return sorted[Math.min(rank - 1, sorted.length - 1)]
}
```

- 부동소수점 보간 미사용 (P24 단순성 — 실제 폭은 어차피 정수 px).
- `Math.ceil` 사용 → 보수적 (더 큰 폭 선택, 잘림 최소화).

### 2.2 라벨 폭 하한선 보장 (라벨 보호)

**규칙**: `maxTextWidth = max(라벨 폭, P95 데이터 폭)`

- 라벨이 데이터보다 길면 라벨 폭 사용 (라벨 절대 안 잘림).
- 데이터가 라벨보다 길면 P95 데이터 폭 사용 (데이터 95% 수용).

### 2.3 안전장치 — 최소/최대 캡 (극단값 차단)

**현재**: `clamp(rawWidth, minWidth, maxWidth)` — 하드코딩된 값.

**변경**: 3계층 캡 시스템.

| 계층 | 역할 | 값 |
|------|------|-----|
| **절대 캡** (하드코딩 불변값) | 극단값 차단, 최소 가독성 보장 | `ABSOLUTE_MIN=36`, `ABSOLUTE_MAX=240` |
| **type 캡** (table-config.ts) | type별 합리적 범위 | 기존 `COLUMN_WIDTH[type]` 유지 |
| **페이지 덮어쓰기** (ColumnDef.minWidth/maxWidth) | 페이지별 특수 요구 | 기존 방식 유지 (선택적) |

**적용 순서**:
```
finalWidth = clamp(
  rawWidth,
  max(ABSOLUTE_MIN, typeMin, pageMin),   // 최소값은 셋 중 최대
  min(ABSOLUTE_MAX, typeMax, pageMax)    // 최대값은 셋 중 최소
)
```

- 절대 캡이 type/페이지 캡보다 우선하지 않고 **교집합**으로 동작 (가장 보수적).
- 기존 type/페이지 덮어쓰기는 그대로 작동 → 기존 코드 호환성 100%.

### 2.4 샘플 부족 시 폴백 (비대표적 데이터 방지)

**문제**: 앱 시작 시 매수후보가 1~2개뿐이면 P95가 비대표적.

**해결**: 샘플 수에 따른 단계적 폴백.

| 샘플 수 | 전략 | 이유 |
|---------|------|------|
| 0 | 라벨 폭만 사용 | 데이터 없음 — 헤더 잘림 방지가 최우선 |
| 1~4 | `max(라벨, 데이터 max)` (기존 방식) | 샘플太少, P95 신뢰도 부족 |
| ≥5 | `max(라벨, P95)` (새 방식) | 충분한 샘플, 이상치 완화 효과 |

- 5개 임계값은 통계적 P95 신뢰성의 최소 기준 (너무 작으면 상위 5% = 0.25개).
- 임계값 상수화: `P95_MIN_SAMPLES = 5`.

---

## 3. 알고리즘 상세

### 3.1 수정 대상 함수

| 함수 | 파일 | 변경 |
|------|------|------|
| `clampColWidth` | `auto-width.ts` | 시그니처 유지, 내부 로직만 개선 (안전장치 3계층) |
| `computeColWidths` | `auto-width.ts` | P95 백분위 산출 로직 추가 |

### 3.2 `computeColWidths` 변경안

```typescript
export function computeColWidths(
  columns: ColumnWidthInput[],
  fontSize: number = DEFAULT_FONT_SIZE,
): number[] {
  if (columns.length === 0) return []

  const widths: number[] = new Array(columns.length)

  for (let i = 0; i < columns.length; i++) {
    const col = columns[i]
    const labelWidth = estimateTextWidth(col.label, fontSize)

    // 데이터 샘플 폭 배열 계산
    const sampleWidths: number[] = []
    for (let j = 0; j < col.samples.length; j++) {
      sampleWidths.push(estimateTextWidth(col.samples[j], fontSize))
    }

    // 대표 폭 선택 (샘플 수에 따른 단계적 전략)
    let dataWidth: number
    if (sampleWidths.length === 0) {
      dataWidth = 0                                    // 데이터 없음 → 라벨만 사용
    } else if (sampleWidths.length < P95_MIN_SAMPLES) {
      dataWidth = Math.max(...sampleWidths)            // 샘플 부족 → max (기존 방식)
    } else {
      dataWidth = percentile(sampleWidths, 95)         // 충분 → P95
    }

    const maxTextWidth = Math.max(labelWidth, dataWidth)
    widths[i] = clampColWidth(maxTextWidth, col.minWidth, col.maxWidth)
  }

  return widths
}
```

### 3.3 `clampColWidth` 변경안

```typescript
/** 절대 캡 — 극단값 차단 (모든 컬럼 공통 불변값) */
const ABSOLUTE_MIN_WIDTH = 36   // 순번/가드 등 최소 가독성
const ABSOLUTE_MAX_WIDTH = 240  // 극단적 긴 텍스트 차단

export function clampColWidth(
  textWidth: number,
  minWidth?: number,
  maxWidth?: number,
): number {
  const rawWidth = textWidth + CELL_HORIZONTAL_PADDING

  // 3계층 캡 교집합
  const effectiveMin = minWidth !== undefined
    ? Math.max(ABSOLUTE_MIN_WIDTH, minWidth)
    : ABSOLUTE_MIN_WIDTH
  const effectiveMax = maxWidth !== undefined
    ? Math.min(ABSOLUTE_MAX_WIDTH, maxWidth)
    : ABSOLUTE_MAX_WIDTH

  // min > max 시 보정 (기존 경고 로직 유지)
  let minW = effectiveMin
  let maxW = effectiveMax
  if (minW > maxW) {
    console.warn(
      `[auto-width] minWidth(${minW}) > maxWidth(${maxW}), clamping minWidth to maxWidth`,
    )
    minW = maxW
  }

  return Math.max(minW, Math.min(rawWidth, maxW))
}
```

**주의**: `DEFAULT_MIN_WIDTH=40` 상수는 `ABSOLUTE_MIN_WIDTH=36`으로 대체 (더 관대한 최소값, type/페이지 캡이 실질적 최소 보장).

### 3.4 신규 함수 — `percentile`

```typescript
/** 배열의 p백분위 값 (Nearest Rank 방식 — 단순·결정론적, 보간 없음). */
function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const rank = Math.ceil((p / 100) * sorted.length)
  return sorted[Math.min(rank - 1, sorted.length - 1)]
}
```

- `Math.ceil` → 보수적 (더 큰 폭, 잘림 최소화).
- 정렬 비용: 샘플 수는 컬럼당 최대 수백 개 → O(n log n) 무시 가능 (첫 1회만 실행).
- 불변 입력 (새 배열 복사) → 부작용 없음.

### 3.5 신규 상수

```typescript
/** P95 백분위 적용 최소 샘플 수 (미만 시 max 사용 — 기존 방식) */
const P95_MIN_SAMPLES = 5

/** 절대 최소 폭 (모든 컬럼 공통 하한) */
const ABSOLUTE_MIN_WIDTH = 36

/** 절대 최대 폭 (모든 컬럼 공통 상한) */
const ABSOLUTE_MAX_WIDTH = 240
```

---

## 4. 영향 범위 분석

### 4.1 수정 파일 (단 1개)

| 파일 | 변경 내용 |
|------|-----------|
| `frontend/src/components/common/auto-width.ts` | `clampColWidth` 내부 로직, `computeColWidths` P95 로직, `percentile` 신규 함수, 상수 3개 |

### 4.2 자동 적용 대상 (수정 불필요 — 공통 함수 경유)

8개 페이지, 총 11개 테이블:

| 페이지 | 테이블 | 컬럼 수 | type 전용 | 페이지 덮어쓰기 |
|--------|--------|---------|-----------|----------------|
| buy-target-columns | 매수후보 | 12 | 6개 | 5개 (name/order_ratio/program_net/news/high_5d) |
| sector-stock-rows | 업종별 종목 | 9 | 0 | 3개 (name/amount/avg_amount) |
| sector-ranking-list | 업종 순위 | 6 | 6개 | 0개 |
| sell-position | 보유 종목 | 10 | 10개 | 0개 |
| stock-detail | 종목 상세 | 3+10 동적 | 2개 | 1개 (name) |
| stock-classification-center | 분류 센터 | 2 | 0 | 1개 (code, type 없음) |
| stock-classification-master | 분류 마스터 | 2 | 2개 | 0개 |
| profit-detail-display | 손익 상세(BUY/SELL) | 9+14 | 23개 | 0개 |
| general-settings-telegram-tab | 텔레그램 명령어 | 2 | 2개 | 0개 |

### 4.3 호환성 분석

| 항목 | 호환성 | 근거 |
|------|--------|------|
| `ColumnDef.minWidth/maxWidth` 인터페이스 | 100% 유지 | 시그니처 변경 없음 |
| `COLUMN_WIDTH[type]` 상수 | 100% 유지 | type 캡으로 여전히 사용 |
| 페이지별 덮어쓰기 | 100% 유지 | 3계층 교집합에서 페이지 캡 포함 |
| `createColumnWidthManager` (1회 계산) | 100% 유지 | 호출부 변경 없음 |
| 고정/가상스크롤 모드 | 100% 유지 | 두 모드 모두 동일 경로 |

### 4.4 동작 변화 예측

| 컬럼 타입 | 현재 폭 결정 | 변경 후 폭 결정 | 예상 효과 |
|-----------|-------------|----------------|-----------|
| seq (순번) | max(라벨, 데이터) → 36 | 동일 (샘플 1~3자, P95=max) | 변화 없음 |
| name (종목명) | max(라벨, 가장 긴 종목명) | max(라벨, P95 종목명) | 이상치 완화 → 약간 좁아질 수 있음 |
| amount (거래대금) | max(라벨, 가장 큰 값) | max(라벨, P95 값) | 대형주 이상치 완화 → 좁아짐 |
| price (현재가) | max(라벨, 가장 비싼 주가) | max(라벨, P95 주가) | 고가주 이상치 완화 → 좁아짐 |
| order_ratio | max(라벨, 데이터) | max(라벨, P95 데이터) | 라벨이 길어 라벨 폭 유지 |
| news (📰뉴스) | max(라벨, 이모지) | 동일 (샘플 1자) | 변화 없음 |

**순 효과**: 이상치가 있는 컬럼(name/amount/price)이 약간 좁아지고, 그만큼 다른 컬럼으로 비중 재분배. 종목명 minWidth 보장(140)은 유지되므로 종목명이 지나치게 좁아지지는 않음.

---

## 5. 엣지케이스 점검

### 5.1 빈 데이터 (매수후보 0개)

- `samples = []` → `dataWidth = 0` → `maxTextWidth = labelWidth` → 라벨 폭으로 확정.
- 기존 동작과 동일 (`computeColWidths` 주석: "샘플 비어도 라벨 폭 사용").
- **안전**: 헤더 잘림 방지 유지.

### 5.2 샘플 1~4개 (앱 시작 직후)

- `sampleWidths.length < 5` → `dataWidth = max(...sampleWidths)` (기존 방식).
- **안전**: 비대표적 P95 방지.

### 5.3 모든 샘플이 동일 폭 (예: 모두 "100.0")

- P95 = max = 동일값 → 변화 없음.
- **안전**.

### 5.4 극단적 이상치 1개 (예: 종목명 20자 1개, 나머지 4자)

- 샘플 ≥5 → P95 사용 → 20자 이상치 무시 → 4~5자 폭으로 확정.
- 20자 종목은 `text-overflow: ellipsis`로 잘림 (이미 종목명 셀에 적용됨).
- **안전**: 5% 미만 잘림은 허용 설계.

### 5.5 type 없는 컬럼 (stock-classification-center code)

- `col.type` 없음 → `COLUMN_WIDTH[type]` 미적용 → `minWidth/maxWidth` 직접 지정값(72/72) 사용.
- 3계층 캡: `max(36, 72) = 72`, `min(240, 72) = 72` → 72px 고정.
- **안전**: 기존 동작 유지.

### 5.6 minWidth > maxWidth (설정 오류)

- 기존 `console.warn` + `minW = maxW` 보정 유지.
- **안전**.

### 5.7 ABSOLUTE_MAX_WIDTH=240 초과 데이터

- 예: `desc` 타입(매수 근거)에 매우 긴 텍스트.
- 240px로 클램핑 → `text-overflow: ellipsis`로 잘림.
- 기존 `maxWidth: 160`이 더 작았으므로 실제로는 160이 우선 (3계층 교집합).
- **안전**.

---

## 6. 검증 계획 (구현 세션용)

### 6.1 단위 테스트 (auto-width.ts)

- `percentile([1,2,3,4,5,6,7,8,9,10], 95)` → 10 (상위 5% = 10번째).
- `percentile([1,2,3,4,5], 95)` → 5.
- `percentile([], 95)` → 0.
- `computeColWidths` 빈 샘플 → 라벨 폭.
- `computeColWidths` 샘플 4개 → max 사용.
- `computeColWidths` 샘플 10개 + 이상치 → P95 사용 (이상치 무시).
- `clampColWidth` 3계층 캡 교집합.

### 6.2 통합 검증

- `npm run typecheck` 통과.
- `npm run build` 통과.
- `npm run test` 통과 (기존 116개 테스트 회귀 확인).
- 브라우저: 매수후보/보유종목/업종순위 화면에서 컬럼 폭 시각적 확인.

### 6.3 회귀 위험

- 기존 테스트 중 `auto-width` 관련 테스트가 있다면 P95 로직으로 인해 폭 값 변경 → 테스트 업데이트 필요 가능성.
- 구현 시 기존 테스트 먼저 실행하여 회귀 탐지.

---

## 7. 구현 세션 작업 순서 (참고용)

1. `auto-width.ts`에 `percentile` 함수 + 상수 3개 추가.
2. `clampColWidth` 내부 로직 수정 (3계층 캡).
3. `computeColWidths` P95 로직 추가.
4. 기존 테스트 실행 → 회귀 확인.
5. 신규 단위 테스트 추가.
6. `npm run typecheck && npm run build && npm run test`.
7. 브라우저 화면 확인 (사용자).

---

## 8. 아키텍처 원칙 부합

| 원칙 | 부합 여부 | 근거 |
|------|-----------|------|
| P10 (SSOT) | 부합 | 폭 계산 로직이 `auto-width.ts` 단일 경로 |
| P16 (살아있는 경로) | 부합 | 기존 호출부 그대로 사용, dead code 없음 |
| P20 (폴백 금지) | 부합 | 샘플 부족 시 `max`는 폴백이 아닌 합리적 기본값 (명시적 전략) |
| P21 (사용자 투명성) | 부합 | 라벨 잘림 방지, 잘림 시 ellipsis로 사용자 인지 가능 |
| P23 (일관성) | 부합 | 기존 `clampColWidth`/`computeColWidths` 시그니처 유지 |
| P24 (단순성) | 부합 | `percentile` 5줄 함수, 복잡도 낮음, 기존 구조 유지 |
| P25 (격리된 실패) | 부합 | 컬럼별 독립 계산, 한 컬럼 오류가 다른 컬럼에 영향 없음 |

---

## 9. 사용자 승인 필요 항목

1. **P95 백분위 채택** — 상위 5% 이상치 잘림 허용 (ellipsis 처리).
   - 대안: P90(10% 잘림), P99(1% 잘림), max(기존=0% 잘림).
2. **샘플 5개 임계값** — 미만 시 기존 max 방식.
3. **ABSOLUTE_MAX_WIDTH=240** — 극단값 상한.
4. **기존 페이지별 덮어쓰기 유지** — `buy-target-columns.ts`의 minWidth:140 등 그대로 둠.
