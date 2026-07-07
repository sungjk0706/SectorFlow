# SectorFlow 수익현황/수익상세 페이지 구조 재조정 계획

- **프로젝트:** SectorFlow
- **작업명:** 수익현황/수익상세 페이지 역할 재분배 및 구조 개선
- **작성일:** 2026-07-07
- **전제:** 기존 `profit-detail-refactor-plan.md` 7단계는 완료됨. 본 계획은 그 후속 개선.

---

## 진행 원칙 (필수 준수)

### 1. 사전조사 선행 원칙
Step 진행 전 반드시 다음 사항을 코드 기반으로 조사한다:
- 대상 파일의 전체 구조와 의존성
- 영향 받는 모든 파일/함수/변수
- 기존 코드 패턴과의 일관성
- 테스트 커버리지 및 기존 테스트 영향
- 아키텍처 원칙(SSOT, 살아있는 경로, 폴백 금지) 부합 여부

### 2. 보고 → 승인 → 진행 원칙
1. 사전조사 결과를 바탕으로 근본 수정안과 검증 방법을 제시
2. 사용자 승인을 받은 후에만 실제 수정 진행
3. 승인 없이 수정/구현 금지

### 3. 세션당 1단계 원칙
- 각 세션은 1단계(Step)만 진행
- 단계 완료 시: 커밋 + HANDOVER.md 업데이트 + 사용자 보고

### 4. 보고 형식 (5항목)
1. 문제 현상 (UI 기준 설명 + 비유 + 실제 화면)
2. 근본 원인 (코드 기반, 파일:줄, 구체적 데이터 흐름)
3. 수정 방안 (아키텍처 원칙 부합 근거 포함)
4. 수정 영향 범위 (변경 파일, 영향 받는 다른 모듈)
5. 검증 방법 (테스트, 사용자 확인 방법)

---

## 페이지 역할 정의 (재조정 후)

### profit-overview (요약/대시보드) — "전체 현황과 추세 파악"
- **좌측 상단:** 일별 수익률 차트 (기존, 50% 높이)
- **좌측 하단:** 신규 차트 — 일별 거래건수(막대) + 수익률(라인) (50% 높이)
- **우측 패널:** 계좌 현황 (세로 전체, 글씨 크기 증가)
- **하단:** "상세 분석 보기 →" 버튼
- **제거:** 요약 카드 3개 (당일/당월/누적) → profit-detail로 이동

### profit-detail (상세/분석) — "거래 분석과 내역 탐색"
- **상단:** 요약 카드 3개 (당일/당월/누적 손익) — 클릭 시 거래내역 필터 연동
- **중단:** 드릴다운 (당월 일별 요약) — 기본 표시 (토글 유지, 기본값 true)
- **하단:** 날짜/종목 필터 + 매도/매수 탭 + 거래내역(가상스크롤) + 통계
- **제거:** 차트 (수익현황과 중복 해결)

---

## 진행 상태 요약

| 단계 | 내용 | 상태 | 세션 |
|------|------|------|------|
| Step 1 | canvas-profit-chart.ts 확장 (mode 옵션) | 대기 | - |
| Step 2 | profit-shared.ts 확장 (요약카드 공통 함수) | 대기 | - |
| Step 3 | profit-overview.ts 구조 재조정 | 대기 | - |
| Step 4 | profit-detail.ts 구조 재조정 | 대기 | - |
| Step 5 | 빌드 검증 + 브라우저 확인 | 대기 | - |

---

## Step 1: canvas-profit-chart.ts 확장 (mode 옵션)

- **사전조사:**
  - 대상 파일: `frontend/src/components/canvas-profit-chart.ts` (468줄)
  - 의존성: `dailySummary` 데이터 (`profit-shared.ts`의 `buildChartFromDailySummary`), `ProfitChartOptions` 타입, `ProfitChartRow` 인터페이스
  - 영향 범위: `profit-overview.ts` (신규 차트 호출 예정), `profit-detail.ts` (변경 없음, 기존 `mode='pnl'` 유지)
  - 기존 코드 패턴: `createProfitChart` 함수 내 `processData` → `render` 파이프라인, `ProfitChartApi` 인터페이스로 외부 노출
  - 테스트 영향: 기존 테스트 없음 (수동 브라우저 검증 의존)
  - 아키텍처 원칙: SSOT 준수 (`dailySummary` 단일 소스), 살아있는 경로 확장 (기존 차트 경로에 mode 분기 추가)

- **목표:** 기존 차트 컴포넌트에 `mode: 'pnl' | 'volume'` 옵션 추가
- **대상 파일:** `frontend/src/components/canvas-profit-chart.ts`
- **변경 내용:**
  - `ProfitChartOptions`에 `mode?: 'pnl' | 'volume'` 추가 (기본값 `'pnl'`)
  - `mode === 'volume'` 시:
    - 막대: 일별 거래건수 (`sell_count`) — 좌측 Y축
    - 라인: 일별 수익률 (`pnl_rate`) — 우측 Y축
    - 툴팁: 거래건수 + 수익률 표시
    - 데이터 타입: `ProfitChartRow` 재사용 (`pnl` 필드에 `sell_count` 매핑, `rate` 필드에 `pnl_rate` 매핑)
  - `mode === 'pnl'` 시: 기존 동작 유지 (일별 손익 막대 + 누적 손익 라인)
  - `processData`: mode에 따라 누적합 계산 여부 결정 (volume 모드는 누적합 없음)
  - `render`: mode에 따라 막대/라인 데이터 소스 전환
  - 툴팁 표시: mode에 따라 라벨/포맷 변경 ("일별 손익" vs "거래 건수")
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): `dailySummary` 단일 데이터 소스 재사용, 차트 표현만 분기
  - 원칙 16 (살아있는 경로): 기존 차트의 렌더링 경로에 mode 분기 추가, 신규 경로가 아닌 기존 경로 확장
  - 원칙 20 (폴백 금지): mode 미지정 시 기본값 `'pnl'`은 폴백이 아닌 명시적 기본값
- **검증:** `npm run type-check` + `npm run build`
- **의존성:** 없음 (최우선)

---

## Step 2: profit-shared.ts 확장 (요약카드 공통 함수)

- **사전조사:**
  - 대상 파일: `frontend/src/pages/profit-shared.ts` (308줄)
  - 의존성: `aggregatePnl` (기존 함수, `@:35-50`), `getLocalToday` (`@:29-31`), `PnlSummary` 인터페이스 (`@:11-15`)
  - 영향 범위: `profit-overview.ts` (요약카드 제거 예정, `updateSummaryCards` 함수 `@:74-92` 참조), `profit-detail.ts` (요약카드 추가 예정)
  - 기존 코드 패턴: `profit-overview.ts` 내 `updateSummaryCards` 함수 (`@:74-92`)가 당일/당월/누적 손익 계산 수행, `aggregatePnl` 호출 후 DOM 갱신
  - 테스트 영향: 기존 테스트 없음
  - 아키텍처 원칙: SSOT 준수 (요약카드 로직 단일 모듈 관리), 폴백 금지 (기존 순수 함수 재사용)

- **목표:** 요약 카드 생성/갱신 로직을 공통 모듈로 추출
- **대상 파일:** `frontend/src/pages/profit-shared.ts`
- **추가 내용:**
  - `SummaryCardConfig` 타입 정의 (label, pnlEl, rateEl)
  - `createSummaryCards(container, onClickCallbacks)`: 요약 카드 3개 DOM 생성, 클릭 콜백 주입
  - `updateSummaryCards(sellHistory, dailySummary, cardEls)`: 당일/당월/누적 손익 계산 및 표시
  - 기존 `aggregatePnl`, `getLocalToday` 재사용
- **이유:** profit-overview에서 요약카드 제거, profit-detail에서 요약카드 추가. 생성/갱신 로직이 양 페이지에서 중복되는 것을 방지
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): 요약카드 생성/갱신 로직 단일 모듈 관리
  - 원칙 20 (폴백 금지): 새로운 폴백 분기 없이 기존 `aggregatePnl` 순수 함수 재사용
- **검증:** `npm run type-check` + `npm run build`
- **의존성:** 없음 (Step 1과 독립)

---

## Step 3: profit-overview.ts 구조 재조정

- **사전조사:**
  - 대상 파일: `frontend/src/pages/profit-overview.ts` (396줄)
  - 의존성: `createProfitChart` (`canvas-profit-chart.ts`), `renderAccountVals` (`profit-shared.ts`), `aggregatePnl` (`profit-shared.ts`), `ACCOUNT_LABELS_REAL`/`ACCOUNT_LABELS_TEST` (`account-labels.ts`), `hotStore`, `api.getDailySummary`
  - 영향 범위: `profit-shared.ts` (Step 2에서 요약카드 함수 추출 완료 전제), `canvas-profit-chart.ts` (Step 1에서 mode 옵션 추가 완료 전제)
  - 기존 코드 패턴: `mount` 함수 내 DOM 구조 = `upper`(flex row: chartPanel + accountPanel) + `summaryRow`(카드 3개) + `lower`(버튼), rAF 배칭으로 `updateSummaryCards`/`updateAccount`/`updateChart` 호출
  - 테스트 영향: 기존 테스트 없음
  - 아키텍처 원칙: SSOT (`dailySummary` 단일 소스, `renderAccountVals` 재사용), 살아있는 경로 (미사용 코드 완전 제거), 폴백 금지 (빈 공간을 데이터 기반 차트로 대체)

- **목표:** 요약카드 제거, 레이아웃 2행×1열(좌) + 1열(우) 구조로 변경, 계좌현황 글씨 크기 증가
- **대상 파일:** `frontend/src/pages/profit-overview.ts`
- **제거:**
  - 요약 카드 3개 DOM 생성 (`@:204-250`)
  - `updateSummaryCards()` 함수 (`@:74-92`)
  - 요약카드 관련 모듈 변수 (`todayPnlEl`, `todayRateEl`, `monthPnlEl`, `monthRateEl`, `totalPnlEl`, `totalRateEl`)
  - rAF 핸들러 내 `updateSummaryCards()` 호출 (`@:347, 353`)
  - 미사용 import: `aggregatePnl` (더 이상 사용 안 함)
- **변경:**
  - `upper` 레이아웃: 현재 `display:flex` (row, chart 50% | account 50%)
    → 변경: `display:flex` (row, leftColumn(flex:5, column flex) | accountPanel(flex:5, 세로 전체))
  - `leftColumn` 내부: `chartPanel`(flex:1) + `newChartPanel`(flex:1, mode='volume')
  - `accountPanel`: `flex:5` 유지, 세로 전체 사용 (upper의 height 100%)
  - 계좌현황 글씨 크기: `ROW_CSS`의 `font-size`를 `FONT_SIZE.label`(12px) → `FONT_SIZE.body`(13px), `padding`을 `7px` → `10px`
  - 값 span 스타일: `fontSize: FONT_SIZE.body` 적용
- **추가:**
  - 신규 차트 인스턴스 (`volumeChart`) 생성, `mode: 'volume'` 옵션
  - 신규 차트용 `chartContainer2` DOM 요소
  - 신규 차트 타이틀 "일별 거래건수 + 수익률"
  - rAF 핸들러에 `_dirtyChart` 시 `volumeChart.updateData()` 호출 추가
  - unmount에 `volumeChart.destroy()` 추가
- **유지:**
  - 기존 차트 (mode='pnl', onBarClick → `#/profit-detail` 이동)
  - 계좌현황 렌더 로직 (`renderAccountVals`)
  - "상세 분석 보기 →" 버튼
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): `dailySummary` 단일 데이터 소스, `renderAccountVals` 공통 함수 재사용
  - 원칙 16 (살아있는 경로): 실제 렌더링 경로의 레이아웃 수정, 미사용 코드 제거
  - 원칙 20 (폴백 금지): 빈 공간을 임시 방편으로 채우지 않고, 실제 데이터 기반 차트 추가
- **검증:** `npm run type-check` + `npm run build` + 브라우저 `#/profit-overview` 확인
- **의존성:** Step 1, Step 2 완료 필수

---

## Step 4: profit-detail.ts 구조 재조정

- **사전조사:**
  - 대상 파일: `frontend/src/pages/profit-detail.ts` (575줄)
  - 의존성: `createProfitChart` (`canvas-profit-chart.ts`), `buildChartFromDailySummary` (`profit-shared.ts`), `buildMonthlyDrilldown`/`createDrilldownCols` (`profit-shared.ts`), `BUY_COLS`/`SELL_COLS` (`profit-shared.ts`), `hotStore`, `api.getDailySummary`
  - 영향 범위: `profit-shared.ts` (Step 2의 `createSummaryCards`/`updateSummaryCards` 사용), `canvas-profit-chart.ts` (import 제거, 의존성 감소)
  - 기존 코드 패턴: `mount` 내 `chartPanel`(300px) + `lower`(flex:1, 필터+드릴다운+탭+테이블+통계), `drilldownActive` 토글 방식 (`@:112-134`), `filterByDate` 단일 날짜 필터 (`@:137-147`)
  - 테스트 영향: 기존 테스트 없음
  - 아키텍처 원칙: SSOT (공통 함수 재사용), 살아있는 경로 (차트 관련 변수/이벤트/구독 전부 제거), 폴백 금지 (중복 차트 제거)

- **목표:** 차트 제거, 요약카드 추가, 드릴다운 기본 표시
- **대상 파일:** `frontend/src/pages/profit-detail.ts`
- **제거:**
  - 차트 패널 DOM 생성 (`@:251-269`)
  - 차트 인스턴스 생성 (`@:436-457`)
  - 차트 관련 모듈 변수 (`chart`)
  - 차트 관련 import: `createProfitChart`, `ProfitChartApi`, `buildChartFromDailySummary`
  - rAF 핸들러 내 `_dirtyChart` 차트 갱신 로직 (`@:514-525`)
  - unmount 내 `chart.destroy()` (`@:548`)
  - `_dirtyChart` 모듈 변수 및 관련 로직
- **추가:**
  - 요약 카드 3개 (상단, `createSummaryCards` 공통 함수 사용)
    - 당일 카드 클릭 → `filterByDate(today)` (오늘 날짜로 필터)
    - 당월 카드 클릭 → `filterByDateRange(monthStart, monthEnd)` (당월 1일~말일)
    - 누적 카드 클릭 → 날짜 필터 해제 (전체)
  - `updateSummaryCards()` 호출을 rAF 핸들러에 추가 (history/dailySummary 변경 시)
  - 드릴다운 `drilldownActive` 초기값 `false` → `true` (기본 표시)
  - mount 시 `drilldownActive = true`이므로 `showDrilldown()` 먼저 호출
  - `filterByDateRange(from, to)` 헬퍼 함수 추가 (기존 `filterByDate`는 단일 날짜, 범위 필터용 확장)
- **변경:**
  - mount 함수 내 `drilldownActive = false` → `drilldownActive = true` (`@:241`)
  - 초기 렌더링: `showTable()` → `showDrilldown()` 우선 호출 후 토글로 전환 가능
  - 드릴다운 토글 버튼 유지 (기본 활성 상태 표시)
- **유지:**
  - 드릴다운 로직 (`showDrilldown`, `filterByDate`, `createDrilldownCols`)
  - 필터 행 (날짜 + 종목 + 드릴다운 토글)
  - 매도/매수 탭 + 거래내역 (가상스크롤)
  - 통계 정보 행
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): 요약카드 생성/갱신을 `profit-shared.ts` 공통 함수 사용, `hotStore` 단일 데이터 소스
  - 원칙 16 (살아있는 경로): 차트 제거 시 관련 변수/이벤트/구독 모두 제거 (죽은 코드 잔류 방지)
  - 원칙 20 (폴백 금지): 차트 제거 자체가 중복 제거이며 폴백 아님
- **검증:** `npm run type-check` + `npm run build` + 브라우저 `#/profit-detail` 확인
- **의존성:** Step 2 완료 필수 (요약카드 공통 함수), Step 1과 독립

---

## Step 5: 빌드 검증 + 브라우저 확인

- **사전조사:**
  - 대상 파일: 전체 수정 파일 (`canvas-profit-chart.ts`, `profit-shared.ts`, `profit-overview.ts`, `profit-detail.ts`)
  - 의존성: Step 1~4 완료 후 전체 프로젝트 상태
  - 영향 범위: 프론트엔드 전체 빌드, 라우팅, WS 이벤트 구독
  - 기존 코드 패턴: `npm run type-check` + `npm run build` + `npm run lint` 검증 체인
  - 테스트 영향: 기존 테스트 없음, 수동 브라우저 검증 의존
  - 아키텍처 원칙: 전 단계 원칙 부합 여부 최종 확인

- **목표:** 전체 변경사항 빌드 통과 및 브라우저 동작 확인
- **검증 항목:**
  1. `npm run type-check` — 타입 오류 없음
  2. `npm run build` — 빌드 성공
  3. `npm run lint` — 린트 경고 없음
  4. 브라우저 `#/profit-overview`:
     - 좌측 상단: 일별 수익률 차트 표시
     - 좌측 하단: 일별 거래건수+수익률 차트 표시
     - 우측: 계좌현황 세로 전체, 글씨 크기 증가 확인
     - 요약카드 미표시 확인
     - "상세 분석 보기 →" 버튼 클릭 → `#/profit-detail` 이동
  5. 브라우저 `#/profit-detail`:
     - 상단: 요약 카드 3개 표시 (당일/당월/누적)
     - 요약카드 클릭 → 거래내역 필터 연동 확인
     - 중단: 드릴다운 기본 표시 확인
     - 드릴다운 날짜 클릭 → 거래내역 필터 확인
     - 하단: 필터 + 탭 + 거래내역 + 통계 정상 동작
     - 차트 미표시 확인
- **의존성:** Step 1~4 전부 완료 필수

---

## 세션별 진행 일정

| 세션 | 단계 | 작업 | 검증 | 승인 |
|------|------|------|------|------|
| 세션 1 | Step 1 + 2 | 차트 확장 + 공통 함수 추출 | typecheck + build | 대기 |
| 세션 2 | Step 3 | profit-overview 구조 재조정 | typecheck + build + 브라우저 | 대기 |
| 세션 3 | Step 4 | profit-detail 구조 재조정 | typecheck + build + 브라우저 | 대기 |
| 세션 4 | Step 5 | 전체 검증 | typecheck + build + lint + 브라우저 | 대기 |

---

## 유의사항

1. 각 단계 사전조사 → 보고 → 승인 → 진행 순서 준수
2. 세션당 1단계만 진행
3. Step 1과 Step 2는 독립적이므로 동시 진행 가능
4. Step 3은 Step 1, 2 완료 후 진행
5. Step 4는 Step 2 완료 후 진행 (Step 1과 독립)
6. 각 단계 완료 시 `HANDOVER.md` 업데이트 + Git 커밋 (사용자 승인 후)
7. 보고 형식 5항목 준수 (현상/원인/수정안/영향범위/검증)

---

## 아키텍처 원칙 부합 확인

| 원칙 | 부합 내용 |
|------|-----------|
| 원칙 10 (SSOT) | `dailySummary` 단일 데이터 소스 재사용, 요약카드/계좌현황 공통 함수를 `profit-shared.ts`에서 관리 |
| 원칙 11 (이벤트 기반) | 기존 WS 이벤트 구독 + rAF 배칭 유지, 폴링 없음 |
| 원칙 16 (살아있는 경로) | 차트 제거 시 관련 변수/이벤트/구독 전부 제거, 죽은 코드 잔류 방지 |
| 원칙 20 (폴백 금지) | 새로운 폴백 분기 없이 기존 데이터 구조와 순수 함수만 활용 |

---

## 영향 범위 요약

| 파일 | 변경 유형 | 영향 |
|------|-----------|------|
| `canvas-profit-chart.ts` | 수정 (Step 1) | `mode` 옵션 추가, volume 모드 렌더링 분기 |
| `profit-shared.ts` | 수정 (Step 2) | `createSummaryCards`, `updateSummaryCards` 공통 함수 추가 |
| `profit-overview.ts` | 수정 (Step 3) | 요약카드 제거, 레이아웃 변경, 신규 차트 추가, 계좌 글씨 크기 |
| `profit-detail.ts` | 수정 (Step 4) | 차트 제거, 요약카드 추가, 드릴다운 기본 표시 |
| `main.ts` | 변경 없음 | 라우트 유지 |
| `sidebar.ts` | 변경 없음 | 메뉴 유지 |
| `router.ts` | 변경 없음 | |
| `binding.ts` | 변경 없음 | WS 이벤트 기존 유지 |
| `hotStore.ts` | 변경 없음 | 데이터 소스 유지 |
| `account-labels.ts` | 변경 없음 | 라벨 상수 유지 |
