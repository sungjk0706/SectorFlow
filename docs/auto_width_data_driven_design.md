# 컬럼 자동 폭 — 데이터 분포 기반 산출 설계

> **상태**: 설계 보완 완료 (세션 1/3 — 다단계 워크플로우)
> **다음 세션**: 태스크 파일 기준 구현 (세션 3/3)
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

- **자동 조화**: 대표성이 확보된 데이터 분포를 반영하여 일일이 px 조정 불필요.
- **준비 완료 후 1회 계산**: 실시간 수신율 임계값 통과 전에는 최종 폭을 고정하지 않고, 대표 데이터가 준비된 뒤 1회 계산한다.
- **장중 안정성 보장**: 준비 완료 후 계산한 폭은 영구 고정하며 이후 수신율·틱 변화로 재계산하지 않는다.
- **라벨 보호**: 라벨 텍스트를 캡 범위 안에서 우선 보호한다.
- **안전장치**: 최소/최대 캡 유지하여 극단값 차단.
- **실제 표시값 기준**: 마스터 캐시 원본이 아니라 각 테이블 `render()` 결과를 폭 샘플로 사용한다.

### 1.3 비목표 (명시적 제외)

- 준비 완료 후 장중 실시간 재계산 (사용자 명시적 거부 — "장중 변동 시 컬럼 폭 변동 절대 안 됨").
- CSS `table-layout: auto` 전환 (가상 스크롤 호환성 위험).
- 마스터 캐시 원본값을 직접 측정하여 화면 폭으로 사용하는 방식.
- 페이지별 컬럼 비율 프리셋 (수동 지정 필요, 자동화 아님).

---

## 2. 핵심 설계 결정

### 2.1 백분위 기반 폭 산출 (이상치 완화)

**현재**: `maxTextWidth = max(라벨 폭, 모든 데이터 샘플 최대 폭)`

**변경**: `maxTextWidth = max(라벨 폭, 데이터 샘플의 P95 백분위 폭)`

- P95(95백분위)는 대표 폭을 데이터 분포의 상위 경계로 정하는 방법이다.
- Nearest Rank는 작은 샘플에서 P95가 최댓값과 같을 수 있다. 따라서 샘플 20개 미만에서는 이상치 완화 효과를 과장하지 않고 기존 `max` 방식을 유지한다.
- 샘플 20개 이상이면 상위 5%에 해당하는 값이 최소 한 개 이상 제외될 수 있다. 제외된 값은 `text-overflow: ellipsis`로 표시한다.
- P95는 통계적 이상치 판정기가 아니라 컬럼 폭을 위한 보수적 대표값이며, 별도의 이상치 삭제나 데이터 변경을 수행하지 않는다.

**P95 산출 알고리즘**:
```
samples가 비어 있으면 → 0 (라벨 폭만 사용)
samples.length < 20이면 → max (샘플 부족 또는 P95가 max와 같을 수 있음)
samples.length >= 20이면 → percentile(samples, 95)
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

- 라벨이 데이터보다 길면 라벨 폭을 대표 폭으로 사용한다.
- 단, type/page 최대 폭 또는 절대 최대 폭이 라벨 폭보다 작으면 최종 캡이 우선하며, 해당 라벨은 기존 `ellipsis` 규칙으로 표시될 수 있다.
- 데이터가 라벨보다 길면 P95 데이터 폭을 대표 폭으로 사용한다.

### 2.3 안전장치 — 최소/최대 캡 (극단값 차단)

**현재**: `clamp(rawWidth, minWidth, maxWidth)` — 하드코딩된 값.

**변경**: 3계층 캡 시스템.

| 계층 | 역할 | 값 |
|------|------|-----|
| **절대 캡** (하드코딩 불변값) | 폭 계산 가중치의 극단값 차단 | `ABSOLUTE_MIN=36`, `ABSOLUTE_MAX=240` |
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

- 절대 캡은 type/페이지 캡과 **교집합**으로 동작한다.
- 현재 `data-table.ts`는 페이지 min/max 중 하나라도 있으면 type 캡을 통째로 대체하므로, 구현 시 type 값과 페이지 값을 각 축별로 병합해야 한다.
- 페이지 `minWidth`는 type 최소값과 비교해 더 큰 값을 사용하고, 페이지 `maxWidth`는 type 최대값과 비교해 더 작은 값을 사용한다.
- 이 병합을 통해 기존 페이지별 의도를 유지하면서 type별 안전 범위도 잃지 않는다.

### 2.4 샘플 부족 시 폴백 (비대표적 데이터 방지)

**문제**: 앱 시작 시 매수후보가 1~2개뿐이면 P95가 비대표적.

**해결**: 샘플 수에 따른 단계적 폴백.

| 샘플 수 | 전략 | 이유 |
|---------|------|------|
| 0 | 라벨 폭만 사용 | 데이터 없음 — 헤더 잘림 방지가 최우선 |
| 1~19 | `max(라벨, 데이터 max)` (기존 방식) | Nearest Rank P95가 max와 같을 수 있어 이상치 완화 효과를 보장할 수 없음 |
| ≥20 | `max(라벨, P95)` (새 방식) | 상위 5%에 해당하는 값이 최소 한 개 이상 제외될 수 있음 |

- 20개는 보편적인 통계 신뢰성 기준이 아니라, 현재 Nearest Rank 정의에서 P95가 max와 같지 않을 수 있도록 정한 구현 기준이다.
- 임계값 상수화: `P95_MIN_SAMPLES = 20`.

### 2.5 간헐·동적 구독 컬럼의 샘플 처리

업종순위 수신율 95%는 `change_rate`·`trade_amount` 중심의 핵심 필드 기준이다. 프.순.매·호가잔량비·체결강도처럼 후속 동적 구독으로 들어오는 필드와 📰뉴스처럼 조건 발생 시에만 들어오는 필드는 같은 시점에 값이 없을 수 있다.

#### 확정 규칙

1. `null`, `undefined`, 빈 문자열, 공백만 있는 `render()` 결과는 폭 분포의 유효 샘플에 포함하지 않는다.
2. 유효 샘플이 없으면 `dataWidth = 0`으로 두고, 컬럼 라벨 + 공통 셀 패딩을 대표 폭으로 사용한다.
3. 유효 샘플이 1~19개이면 유효 샘플의 `max`를 사용한다. 단, 최종 type/page 캡을 넘지 않는다.
4. 유효 샘플이 20개 이상이면 유효 샘플의 P95를 사용한다.
5. 뉴스처럼 값이 간헐적인 컬럼은 별도 임의 `+5px`, `+7px`을 넣지 않는다. `labelWidth + CELL_HORIZONTAL_PADDING`와 기존 `news` type 캡(50~70)을 사용한다.
6. 프.순.매·호가잔량비·체결강도처럼 동적 구독 지연이 있는 컬럼은 값이 준비되지 않아도 기존 type/page 캡을 안전 기본값으로 사용한다. 현재 매수후보의 `program_net` 고정폭 76px, `order_ratio` 최대폭 88px을 유지하고 업종별 종목의 `strength`는 기존 type 캡을 사용한다.
7. 준비 완료 후 늦게 들어온 값이 고정 폭을 초과하면 폭을 재계산하지 않고 기존 셀 `ellipsis` 규칙으로 표시한다.

이 정책은 필드명을 `auto-width.ts`에 하드코딩하지 않고, 공통 샘플 수집기에서 유효 텍스트만 선별하며 기존 type/page 캡을 재사용한다. 따라서 새로운 간헐 필드가 추가되어도 별도 폭 상수를 만들 필요가 없다.

### 2.6 수신율 임계값 기반 폭 계산 준비 게이트

현재 백엔드는 마스터 종목 캐시의 `change_rate`·`trade_amount` 수신 상태를 기준으로 KRX/NXT 수신율을 계산하고, 설정된 업종순위 수신율 임계값 통과 전에는 업종점수 전송을 대기시킨다. 이 기존 게이트를 컬럼 폭 계산의 **준비 신호**로 재사용한다.

#### 확정 규칙

1. 수신율 임계값 미통과 시 실시간 업종·종목 테이블의 최종 폭을 계산·고정하지 않는다.
2. 임계값 통과 후 해당 테이블에 전달된 현재 `rows`를 기준으로 폭을 1회 계산한다.
3. 폭 샘플은 마스터 캐시 원본값이 아니라 `ColumnDef.render(row, index)` 결과의 `textContent`를 사용한다.
4. 폭 계산이 완료되면 `initialized = true`로 전환하고, 이후 수신율·틱·행 갱신으로 재계산하지 않는다.
5. 임계값에 도달하지 않거나 데이터가 비어 있어도 앱 전체를 차단하지 않는다. 대기 중에는 헤더·type 캡 기반 안전 폭을 사용하고 대기 상태를 UI에 표시한다.
6. 일반 참고 테이블은 업종순위 수신율을 불필요하게 기다리지 않고 기존 첫 데이터 1회 계산 정책을 유지한다.

#### 준비 상태 전달

- 백엔드 수신율 판정 자체를 프론트에서 재계산하지 않는다.
- 백엔드의 기존 수신율 게이트가 판정 SSOT이고, 프론트는 그 결과를 `uiStore.sectorDataReady`로 전달한다.
- `sectorDataReady`는 WS 구독 시작 시 false로 리셋하고, 임계값 통과 후 정상 업종 데이터 이벤트 또는 비-WS 확정 데이터 스냅샷 수신 시에만 true로 전환한다.
- 단순히 `sectorScoresWaiting === false`인 초기 기본값만으로 준비 완료라고 판단하지 않는다.
- `DataTable`은 `widthReady?: () => boolean` 조건을 받아 실시간 테이블에만 적용하며, 일반 테이블의 기본값은 true로 한다.

#### 준비 전·후 동작

```
준비 전:
  rows 수신 → 행 렌더링은 허용
  폭 관리자 → 최종 폭 계산 보류
  표시 폭 → 헤더/type 캡 기반 안전 폭

준비 완료:
  현재 rows의 render 결과 수집
  컬럼별 대표 폭(P95 또는 샘플 부족 max) 계산
  type/page/절대 캡 적용
  percentage 변환·적용
  이후 폭 계산 영구 고정
```

#### 오류·예외

- 준비 전 `rows=[]`가 들어와도 최종 폭을 고정하지 않는다.
- 준비 완료 후 render 오류가 발생한 셀은 기존 P25 셀 격리·로깅 규칙을 따른다.
- 폭 계산·적용 실패가 전체 테이블이나 다른 테이블을 중단시키지 않도록 안전 폭을 유지하고 오류를 로깅한다.
- 준비 완료 이벤트가 중복 수신되어도 이미 고정된 폭은 변경하지 않는다.

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

    // 유효 데이터 샘플 폭 배열 계산 — 빈 문자열·공백은 분포에서 제외
    const sampleWidths: number[] = []
    for (let j = 0; j < col.samples.length; j++) {
      if (col.samples[j].trim().length === 0) continue
      sampleWidths.push(estimateTextWidth(col.samples[j], fontSize))
    }

    // 대표 폭 선택 (유효 샘플 수에 따른 단계적 전략)
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
/** P95 백분위 적용 최소 샘플 수 (미만 시 max 사용 — Nearest Rank 특성 반영) */
const P95_MIN_SAMPLES = 20

/** 절대 최소 폭 (모든 컬럼 공통 하한) */
const ABSOLUTE_MIN_WIDTH = 36

/** 절대 최대 폭 (모든 컬럼 공통 상한) */
const ABSOLUTE_MAX_WIDTH = 240
```

---

## 4. 영향 범위 분석

### 4.1 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `frontend/src/components/common/auto-width.ts` | `clampColWidth` 내부 로직, `computeColWidths` P95 로직, `percentile` 신규 함수, 상수 3개 |
| `frontend/src/components/common/data-table.ts` | type 캡과 페이지 min/max 병합, `widthReady` 준비 조건에 따른 최종 폭 계산 보류·1회 초기화 |
| `frontend/src/components/common/data-table-fixed.ts` | 빈 rows 또는 준비 전 rows에서 최종 폭을 고정하지 않고 안전 폭 경로 유지 |
| `frontend/src/components/common/data-table-virtual.ts` | 고정 모드와 동일한 준비 전·후 폭 초기화 계약 적용 |
| `frontend/src/stores/uiStore.ts` 또는 기존 상태 SSOT 경로 | 실제 수신율 임계값 통과 후 준비 완료 상태 전달. 중복 수신율 계산 금지 |
| `frontend/src/pages/sector-ranking-list.ts` | 업종순위 테이블에 기존 수신 대기 상태를 `widthReady`로 연결 |
| `frontend/src/pages/sector-stock.ts` | 업종별 종목 테이블에 동일한 준비 상태를 연결 |
| `frontend/tests/`의 기존 공통 컴포넌트 테스트 파일 | P95·캡 병합·준비 전 보류·준비 후 1회 고정 회귀 테스트 |

### 4.2 적용 대상 분류

모든 테이블은 `auto-width.ts`의 폭 계산을 공유하지만, 수신율 준비 게이트는 실시간 업종 데이터에만 적용한다.

- **준비 게이트 적용**: 업종 순위, 업종별 종목 테이블. 수신율 임계값 통과 후 첫 대표 rows에서 폭을 계산한다.
- **기존 즉시 계산 유지**: 매수후보, 보유 종목, 종목 상세, 분류 센터·마스터, 손익 상세, 텔레그램 명령어. 각 테이블의 데이터 생명주기가 업종순위 게이트와 직접 같지 않으므로 불필요하게 대기시키지 않는다.

8개 페이지, 총 11개 테이블의 폭 산출은 공통 경로를 유지한다.

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
| `COLUMN_WIDTH[type]` 상수 | 100% 유지 | type 캡 병합에 계속 사용 |
| 페이지별 덮어쓰기 | 동작 유지 | type 캡과 각 축별 교집합으로 병합 |
| `createColumnWidthManager` (1회 계산) | 100% 유지 | 첫 호출·고정 계약 유지 |
| 고정/가상스크롤 모드 | 100% 유지 | 두 모드 모두 동일 경로 |

### 4.4 동작 변화 예측

| 컬럼 타입 | 현재 폭 결정 | 변경 후 폭 결정 | 예상 효과 |
|-----------|-------------|----------------|-----------|
| seq (순번) | max(라벨, 데이터) → 36 | 동일 (샘플 1~3자, P95=max) | 변화 없음 |
| name (종목명) | max(라벨, 가장 긴 종목명) | max(라벨, P95 종목명) | 이상치 완화 → 약간 좁아질 수 있음 |
| amount (거래대금) | max(라벨, 가장 큰 값) | max(라벨, P95 값) | 대형주 이상치 완화 → 좁아짐 |
| price (현재가) | max(라벨, 가장 비싼 주가) | max(라벨, P95 주가) | 고가주 이상치 완화 → 좁아짐 |
| order_ratio | max(라벨, 데이터) | 유효 샘플 부족 시 라벨·type/page 캡, 충분하면 P95 | 동적 구독 지연에도 기존 안전 폭 유지 |
| program_net | max(라벨, 데이터) | 유효 샘플 부족 시 기존 페이지 76px 고정폭 | 늦은 수신에도 폭 이동 없음 |
| news (📰뉴스) | max(라벨, 이모지) | 유효 샘플 없음이면 라벨+공통 패딩·news 캡 | 뉴스 수신 여부와 무관하게 기본 폭 유지 |

**순 효과**: 이상치가 있는 핵심 컬럼(name/amount/price)은 약간 좁아질 수 있고, 간헐 컬럼은 값 수신 여부와 무관하게 안전 기본 폭을 유지한다. 종목명 minWidth 보장(140)은 유지되므로 종목명이 지나치게 좁아지지는 않음.

---

## 5. 엣지케이스 점검

### 5.1 빈 데이터

- 일반 테이블: `samples = []` → `dataWidth = 0` → `maxTextWidth = labelWidth` → 라벨·type 캡으로 1회 확정.
- 준비 게이트 대상 테이블: 준비 전 `rows = []`이면 최종 폭을 확정하지 않고 안전 폭으로 대기한다.
- 준비 게이트 통과 후에도 `rows = []`이면 라벨·type 캡 기반 안전 폭을 적용하되, 이후 유효 rows가 들어올 때 1회 확정할 수 있어야 한다.
- **안전**: 빈 데이터 때문에 대표성이 없는 폭이 영구 고정되지 않으며, 헤더 잘림도 방지한다.

### 5.2 샘플 1~19개 (앱 시작 직후)

- `sampleWidths.length < 20` → `dataWidth = max(...sampleWidths)` (기존 방식).
- **안전**: 비대표적 P95 방지.

### 5.3 모든 샘플이 동일 폭 (예: 모두 "100.0")

- P95 = max = 동일값 → 변화 없음.
- **안전**.

### 5.4 극단적 이상치 1개 (예: 종목명 20자 1개, 나머지 4자)

- 샘플 20개 이상 → Nearest Rank P95 사용 → 상위 5% 경계 밖의 이상치가 대표 폭에서 제외될 수 있음.
- 샘플 5~19개 → P95가 max와 같을 수 있으므로 기존 max 방식 유지.
- 대표 폭 밖의 긴 값은 `text-overflow: ellipsis`로 표시될 수 있다.
- **안전**: 데이터 원본은 변경하지 않고 화면 표시 폭만 제한한다.

### 5.5 type 없는 컬럼 (stock-classification-center code)

- `col.type` 없음 → `COLUMN_WIDTH[type]` 미적용 → `minWidth/maxWidth` 직접 지정값(72/72) 사용.
- 3계층 캡: `max(36, 72) = 72`, `min(240, 72) = 72` → 72px 고정.
- **안전**: 기존 동작 유지.

### 5.6 minWidth > maxWidth (설정 오류)

- 기존 `console.warn` + `minW = maxW` 보정 유지.
- **안전**.

### 5.7 ABSOLUTE_MAX_WIDTH=240 초과 데이터

- 예: `desc` 타입(매수 근거)에 매우 긴 텍스트.
- 폭 계산 가중치 240으로 클램핑 → `text-overflow: ellipsis`로 표시될 수 있다.
- 기존 `maxWidth: 160`이 더 작으므로 실제 계산 가중치는 160이 우선한다 (3계층 교집합).
- **안전**.

### 5.8 간헐·동적 구독 컬럼

- `program_net_buy`, `order_ratio`, `news_boost`가 비어 있으면 빈 문자열을 유효 샘플로 세지 않는다.
- 유효 샘플이 없으면 라벨·공통 패딩과 type/page 캡만으로 안전 폭을 계산한다.
- 뉴스 컬럼은 `news` type의 50~70 가중치 범위 안에서 라벨과 공통 패딩을 우선한다.
- 프.순.매와 호가잔량비는 현재 페이지의 76px 고정폭·88px 최대폭 설정을 그대로 안전 캡으로 사용한다.
- 준비 완료 후 늦게 들어온 값은 고정 폭을 변경하지 않고 ellipsis로 처리한다.

### 5.9 수신율 임계값 미통과·통과 경계

- 준비 전 rows가 여러 번 갱신되어도 최종 폭은 고정하지 않는다.
- 준비 완료 이벤트와 rows 갱신이 같은 시점에 들어오면 최신 rows로 1회 계산한다.
- 준비 완료 이벤트가 중복 수신되어도 이미 계산된 폭은 변경하지 않는다.
- 수신율 임계값에 도달하지 않아도 테이블·페이지 전체는 계속 표시되고, 대기 상태를 사용자에게 표시한다.
- 새 WS 구독 세션에서 준비 상태가 다시 미완료로 바뀌더라도 이미 고정된 테이블 폭을 장중에 재계산하지 않는다. 다음 테이블 인스턴스 생성 시에만 새 준비 상태를 적용한다.

---

## 6. 검증 계획 (구현 세션용)

### 6.1 단위 테스트

- `computeColWidths`를 통해 샘플 10개에서 Nearest Rank P95가 max와 같음을 검증한다.
- `computeColWidths`를 통해 샘플 19개가 max 전략을 사용하는지 검증한다.
- `computeColWidths`를 통해 샘플 20개 + 이상치가 P95 대표 폭을 사용하는지 검증한다.
- `computeColWidths` 빈 샘플 → 라벨 폭.
- `clampColWidth` 절대 캡과 병합된 type/page 캡의 교집합.
- `createColumnWidthManager` type 캡과 페이지 min/max의 축별 병합.
- 빈 문자열·공백 샘플이 P95 유효 샘플 수에 포함되지 않음.
- 유효 샘플이 없는 뉴스·동적 구독 컬럼이 라벨+공통 패딩·type/page 캡으로 처리됨.
- `createColumnWidthManager` 준비 전 rows에서는 최종 폭을 고정하지 않음.
- `createColumnWidthManager` 준비 완료 후 첫 rows에서 1회 계산하고 이후 rows에서는 재계산하지 않음.
- `percentile`은 내부 함수로 유지하고 export하지 않는다.

### 6.2 통합 검증

- `npm run typecheck` 통과.
- `npm run build` 통과.
- `npm run test` 통과 (기존 테스트 회귀 확인).
- 수신율 임계값 미통과 상태에서 업종순위·업종별 종목 폭이 최종 고정되지 않는지 확인.
- 임계값 통과 이벤트 후 실제 `render()` 결과로 폭이 1회 계산되는지 확인.
- 통과 후 추가 rows·수신률 이벤트에서 폭이 변하지 않는지 확인.
- 브라우저: 매수후보/보유종목/업종순위 화면에서 컬럼 폭 시각적 확인.

### 6.3 회귀 위험

- 기존 테스트 중 `auto-width` 관련 테스트가 있다면 P95 로직으로 인해 폭 값 변경 → 테스트 업데이트 필요 가능성.
- 구현 시 기존 테스트 먼저 실행하여 회귀 탐지.

---

## 7. 구현 세션 작업 순서 (참고용)

1. 수신율 준비 상태 SSOT와 실시간 대상 테이블의 `widthReady` 연결 계약 확인.
2. `data-table.ts`에서 type/page min/max를 각 축별로 병합하고 준비 전 최종 폭 계산을 보류.
3. `data-table-fixed.ts`·`data-table-virtual.ts`에 동일한 준비 전·후 초기화 계약 연결.
4. `auto-width.ts`에 `percentile` 함수 + 상수 3개 추가.
5. `clampColWidth` 내부 로직 수정 (절대 캡과 병합 캡의 교집합).
6. `computeColWidths` P95 로직 추가.
7. 기존 테스트 실행 → 회귀 확인.
8. 신규 단위 테스트 추가.
9. `npm run typecheck && npm run build && npm run test`.
10. 브라우저 화면 확인 (사용자).

---

## 8. 아키텍처 원칙 부합

| 원칙 | 부합 여부 | 근거 |
|------|-----------|------|
| P10 (SSOT) | 부합 | 수신율 준비 상태는 기존 게이트·상태 경로, 폭 대표값은 `auto-width.ts`, type/page 캡 조립은 `data-table.ts`에서만 관리 |
| P16 (살아있는 경로) | 부합 | 준비 상태를 실제 `DataTable` 초기화 경로와 `computeColWidths`에 연결하고 dead code를 남기지 않음 |
| P20 (폴백 금지) | 부합 | 샘플 부족 시 `max`는 명시된 표본 부족 전략이며 P95 효과를 과장하지 않음 |
| P21 (사용자 투명성) | 부합 | 캡 범위 내 라벨 우선, 범위를 벗어난 값은 기존 ellipsis로 표시 가능 |
| P23 (일관성) | 부합 | 기존 시그니처·공통 테이블 경로·type 상수를 유지 |
| P24 (단순성) | 부합 | Nearest Rank와 축별 캡 병합만 추가하고 별도 라이브러리·페이지 프리셋을 만들지 않음 |
| P25 (격리된 실패) | 부합 | 컬럼별 독립 계산, 한 컬럼 오류가 다른 컬럼에 영향 없음 |

---

## 9. 설계 보완 결과

초기 설계의 사용자 결정 항목을 현재 코드 경로와 Nearest Rank 정의에 대조한 결과, 구현 기준을 다음처럼 보완했다.

1. **P95 백분위 채택 유지** — Nearest Rank의 단순·결정론적 계산을 유지한다.
2. **샘플 임계값을 5개에서 20개로 보완** — 샘플 5~19개에서는 P95가 max와 같을 수 있으므로 기존 max를 사용한다.
3. **ABSOLUTE_MAX_WIDTH=240 유지** — percentage 변환 전 폭 계산 가중치 상한으로 정의한다. 실제 렌더링 px 상한으로 해석하지 않는다.
4. **기존 페이지별 덮어쓰기 유지** — type 캡과 각 축별 교집합으로 병합하여 페이지 특수 요구와 공통 안전 범위를 함께 보존한다.
5. **수정 범위 보완** — `auto-width.ts`뿐 아니라 type/page 캡을 조립하는 `data-table.ts`, 고정·가상 모드, 준비 상태 연결, 공통 테스트를 포함한다.
6. **준비 게이트 확정** — 수신율 임계값은 계산 허가 신호로만 사용하고, 실제 샘플은 해당 테이블의 `render()` 결과에서 수집한다.

근거: NIST는 백분위 추정에서 원하는 백분위가 관측값 사이에 위치하면 보간이 필요할 수 있고, 작은 표본에서는 방법에 따라 결과가 달라질 수 있다고 설명한다. 이번 구현은 보간 대신 Nearest Rank 단순성을 유지하되, 작은 표본에서 P95 효과를 과장하지 않는 보수적 임계값을 사용한다.
