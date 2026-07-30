# 설계서: 실현 수익률 분모 통일 (매수원금 기반)

> **상태**: 설계 완료, 사용자 승인 대기
> **작성일**: 2026-07-30
> **관련 원칙**: P10(SSOT) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)
> **관련 파일**: `frontend/src/pages/profit-math.ts` · `profit-shared.ts` · `profit-overview-mount.ts` · `profit-detail-display.ts` · `profit-detail-mount.ts` · `profit-shared.test.ts`
> **관련 API 스펙**: 백엔드 `get_daily_summary` (이미 매수원금 기반 — 변경 없음)

---

## 0. 최상위 원칙 (불변)

> **실현 수익률 = 해당 기간 매도 완료된 종목들의 실현손익 합 ÷ 해당 기간 매도 완료된 종목들의 총 매수원금 합 × 100**

본 설계는 계좌 전체의 자산 증감을 계산하는 것이 아니라, 자동매매 엔진이 완료한 거래의 실현 성과를 계산하는 것을 목적으로 한다.

본 공식은 본 설계의 최상위 원칙이며, 아래 설계 원칙(불변 규칙)과 함께 향후 모든 수정에서 준수해야 한다.

### 설계 원칙 (불변 규칙)

1. **팔린(매도 완료된) 거래만 계산한다.** 보유 중인 종목은 실현손익이 발생하지 않으므로 분자·분모 모두에서 제외.
2. **분모는 항상 매수원금이다.** 총자산·예수금·주문가능금액·투자원금·평가손익은 분모로 사용하지 않는다.
3. **보유 종목은 계산에서 제외한다.** 평가손익·평가금은 실현 수익률 계산에 포함하지 않는다.
4. **총자산·예수금·주문가능금액은 계산에 사용하지 않는다.** 이들은 계좌 상태를 나타낼 뿐 자동매매 성과가 아니다.
5. **모든 기간(당일/5거래일/당월/누적)은 동일한 공식을 사용한다.** 기간별 분모 규칙 분기 없음.

### 검증 원칙 (불변)

동일한 `sellHistory` 입력에 대해 기간(당일·5거래일·당월·누적)에 관계없이 계산 공식은 반드시 동일해야 하며, 집계 대상(기간 필터)만 달라져야 한다.

---

## 1. 배경 및 목표

### 1.1 현재 상태 (문제)

수익 페이지 요약 카드 4개(당일/5거래일/당월/누적)의 수익률 분모가 **스냅샷 기반 총자산**(`base_asset`, `earliest_base_asset`)을 사용 중.

- 분자: 실현손익 only (평가손익 제외 — 사용자 결정)
- 분모: 총자산 (예수금 + **평가금 포함**) → **분자-분모 불일치** (P22 위반)
- `account_daily_snapshot` 테이블 의존 → 장마감 파이프라인 미실행 시 분모 null → rate '-' 표시
- 분모 추정 로직(`accumulated_investment + 기간 전 누적 실현손익`)이 직전 세션에서 추가됨 → 복잡도 증가 (P24 위반)

**핵심 발견**: 백엔드 `get_daily_summary`의 `pnl_rate`와 프론트엔드 `aggregatePnl`은 **이미 매수원금 기반**으로 계산 중:
- `trade_history.py:672` — `pnl_rate = realized_pnl / buy_total * 100`
- `profit-math.ts:229` — `aggregatePnl` 반환 `rate: computeWeightedRate(pnl, buyTotal)`
- `buildMonthlyDrilldown`/`buildFivedayDrilldown`은 dailySummary의 `pnl_rate`를 직접 사용 → 이미 매수원금 기반

즉, **드릴다운 테이블은 이미 매수원금 기반이나 요약 카드 4개만 스냅샷 분모를 별도 사용** — P23(일관성) 위반.

관련 코드 위치:
- `profit-math.ts:272-297` — `computeCumulativePnl` 분모 분기 로직 (스냅샷 우선 → earliestBaseAsset → 투자원금+누적손익 추정)
- `profit-shared.ts:207-241` — `updateSummaryCards` 당일 카드 분모 (전일 baseAsset + daily_deposit)
- `profit-overview-mount.ts:77-95` — `buildDonutCenter` 분모 (findBaseAssetForDate + earliestBaseAsset)
- `profit-detail-display.ts:331-348` — 통계 평균 수익률 분모

### 1.2 목표 (사용자 관점 달성 항목)

1. 수익 페이지 요약 카드 4개(당일/5거래일/당월/누적)의 수익률이 **"매도 완료된 종목들의 총 매수원금 대비 실현손익"**으로 통일 표시
2. 수익률 명칭을 **"실현 수익률"**로 변경하여 사용자가 "매도된 거래 기준 수익률"임을 명확히 인지 (P21)
3. 장마감 스냅샷이 없어도 수익률 정상 표시 (DB 의존 제거)
4. 분자-분모 정합성 확보: 분자=실현손익, 분모=매수원금 (둘 다 매도 완료된 거래에서만)

### 1.3 비목표 (다루지 않는 것 + 사유)

- **실전모드 수익률 표시**: 실전모드는 증권사 SSOT (앱 재계산 금지) → rate null('-') 유지. 본 설계는 테스트모드 한정.
- **백엔드 `account_daily_snapshot` 테이블/파이프라인 제거**: 스냅샷은 리스크 관리·기초자산 추적용으로 유지 가능. 프론트엔드 수익률 계산에서만 의존 제거. 백엔드 정리는 후순위 (별도 설계).
- **백엔드 `get_daily_summary`의 `base_asset`/`earliest_base_asset` 필드 제거**: 프론트엔드에서 미사용 처리 후, 백엔드 필드 제거는 후순위 (별도 설계 — P16 살아있는 경로 확인 필요).
- **평가손익 포함 수익률**: 사용자 결정(실현 only) 유지 — 변경 없음.
- **용어 정리("평가손익"/"평가" → 한국 주식시장 표준)**: HANDOVER "다음 세션 진행 대기"의 별도 작업. 본 설계와 독립.

---

## 2. 설계 방향

### 2.1 핵심 설계 결정

**결정 1: 분모 = 매도 완료된 종목들의 총 매수원금 합 (매수원금 기반 실현 수익률)**
- 왜: 이 앱은 자동매매 엔진 성과 표시. 사용자가 알고 싶은 것은 "이 기간에 자동매매가 투입한 자본으로 얼마를 벌었는가" — Capital At Risk = 매수원금. 총자산/주문가능금액/투자원금은 자동매매 성과가 아닌 계좌 상태를 반영.
- 공식: 최상위 원칙(0절) 참조.
- 구현: `aggregatePnl(sellHistory, dateFrom, dateTo)`가 이미 이 계산 수행 (`pnl / buyTotal * 100`). `computeCumulativePnl`은 `aggregatePnl`의 `buyTotal`을 분모로 사용하도록 단순화.

**결정 2: 4카드(당일/5거래일/당월/누적) 동일 원칙 적용**
- 왜: 누적 카드도 "자동매매 엔진의 누적 거래 품질"을 표시. 투자원금 분모는 "계좌 자본 증감"이지 "거래 성과"가 아님. P23(일관성) — 4카드 동일 공식 (설계 원칙 5).
- 누적 카드: `dateFrom`/`dateTo` 없이 `aggregatePnl(sellHistory)` 전체 범위 → 전체 매도 종목 매수원금 합 분모.

**결정 3: UI 명칭 "실현 수익률" 표시**
- 왜: "수익률"만 표시 시 사용자가 "계좌 전체 수익률"로 오인 가능. "실현 수익률"은 "매도 완료된 거래 기준"임을 명시 (P21 투명성).
- 적용 범위: 6절 "UI 용어 변경 체크리스트" 참조.

**결정 4: 스냅샷 의존 코드 제거 (프론트엔드)**
- 왜: 매수원금 기반은 `sellHistory`만으로 계산 → `account_daily_snapshot` 의존 불필요. P24(단순성) — 복잡한 분모 추정 로직 제거.
- 제거 대상 함수: `extractEarliestBaseAsset`, `findBaseAssetForDate`, `cumulativeRealizedPnlBeforeDate` (profit-math.ts)
- 제거 대상 호출: `computeCumulativePnl`의 `baseAsset`/`earliestBaseAsset` 파라미터, `updateSummaryCards`의 `dayBaseAsset`/`fiveBaseAsset`/`monthBaseAsset`/`earliestBaseAsset` 파라미터, `buildDonutCenter`의 분모 로직, `profit-detail-display.ts` 통계 분모 로직.

**결정 5: `aggregatePnl`을 실현 수익률의 유일한 계산 함수(SSOT)로 명시**
- 왜: `aggregatePnl`이 이미 매수원금 기반 계산을 수행. `computeCumulativePnl`은 분모 분기 로직 제거 후 `aggregatePnl`의 `buyTotal`/`rate`를 그대로 사용. P10(SSOT) · P24(단순성).
- **SSOT 규칙 (불변)**:
  - 실현 수익률 계산은 `aggregatePnl`만 수행한다.
  - 동일 계산을 수행하는 신규 함수를 만들지 않는다.
  - 모든 화면(요약 카드·도넛 중앙·통계·계좌현황 누적)은 `aggregatePnl` 결과만 사용한다.
- 실전모드 분기 유지: `!isTestMode` 시 `rate: null` 반환 (증권사 SSOT — 변경 없음).
- `CumulativePnlParams` 인터페이스 축소: `account`, `baseAsset`, `earliestBaseAsset` 제거. `sellHistory`, `isTestMode`, `dateFrom`, `dateTo`만 잔류.

### 2.2 기각 방안

| 방안 | 기각 사유 |
|------|-----------|
| B. 기간 시작 총자산 분모 (현재 구현) | 분자(실현 only)와 분모(평가금 포함) 불일치. 자동매매 성과가 아닌 계좌 상태 반영. 스냅샷 DB 의존. |
| C. 주문가능금액 분모 | hold list에서 전일 매수 시 주문가능금액 0 → 다음 날 매도 시 분모 0 왜곡. 실현손익의 원천(매수원금)과 무관. |
| D. 투자원금 분모 (누적 카드) | "계좌 자본 증감"이지 "거래 성과" 아님. 4카드 원칙 불일치 (P23 위반). 재매매 시 분모 고정으로 거래 품질 왜곡. |
| 분자에 평가손익 포함 | 사용자 결정(실현 only)과 충돌. |
| 백엔드 스냅샷 테이블/파이프라인 제거 | 리스크 관리·기초자산 추적 용도 가능. 프론트엔드 의존 제거만으로 목표 달성. 백엔드 정리는 후순위. |

---

## 3. 사용자 결정 항목

> 본 설계의 설계 결정은 사용자와의 사전 대화에서 확정된 항목. 2세션 태스크 파일에서 활용.

**질문 1: 수익률 분모 설계 방향**
- 사용자 결정: **매수원금 기반 실현 수익률 통일** — 당일/5거래일/당월/누적 모두 동일 원칙.
- 근거 (사용자): "이 앱은 자동매매 엔진의 성과를 보여주는 앱. 사용자가 궁금한 것은 '이 기간에 자동매매가 투입한 자본으로 얼마를 벌었는가'. Capital At Risk = 매수원금. 총자산/주문가능금액/투자원금은 자동매매 성과가 아님."
- 분자 = 해당 기간 매도 완료된 종목들의 실현손익 합
- 분모 = 해당 기간 매도 완료된 종목들의 총 매수원금 합
- 투자원금, 총자산, 주문가능금액, 평가손익, account_daily_snapshot은 수익률 계산에 사용하지 않음

**질문 2: 누적 카드 분모**
- 사용자 결정: **매수원금 기반 통일** (투자원금 분모 기각)
- 근거 (사용자): "계좌 전체 자산의 증감이 아니라 매매가 완료된 거래의 성과를 보여주는 것이 목적. 전 기간 동일하게 유지."

**질문 3: UI 명칭**
- 사용자 결정: **"실현 수익률"** 표시
- 근거 (사용자): "사용자도 '매도된 거래 기준이구나'라고 이해. 명확히 표시."

---

## 4. 아키텍처 원칙 부합 검토

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10 (SSOT) | ✅ | `aggregatePnl` 단일 공식으로 4카드·도넛 중앙·통계·계좌현황 누적 모두 동일 분모. 현재는 `computeCumulativePnl`(스냅샷 분모) vs `aggregatePnl`(매수원금 분모) vs dailySummary `pnl_rate`(매수원금 분모) 3경로 혼재 → 1경로 통합. 결정 5 SSOT 규칙으로 신규 함수 생성 금지. |
| P16 (살아있는 경로) | ✅ | 제거 대상 함수(`extractEarliestBaseAsset` 등)는 제거 후 호출처 0건 확인 후 삭제. dead code 방치 금지. 7절 검증 항목 참조. |
| P20 (폴백 금지) | ✅ | 분모 0(매도 없음) 시 `computeWeightedRate`가 0 반환 (기존 동일). rate null은 실전모드만. 빈 문자열/None 폴백 분기 제거. |
| P21 (사용자 투명성) | ✅ | "실현 수익률" 명칭으로 사용자가 "매도 완료된 거래 기준"임을 인지. 스냅샷 미존재 시 '-' 표시 문제 제거 (매도 이력만 있으면 항상 표시). |
| P22 (데이터 정합성) | ✅ | 분자(실현손익)와 분모(매수원금) 모두 매도 완료된 거래에서만 발생 — 논리적 일치. 현재 분모(총자산-평가금 포함)와 분자(실현 only) 불일치 해소. |
| P23 (일관성) | ✅ | 4카드 동일 공식 (설계 원칙 5). 드릴다운 테이블(dailySummary pnl_rate 직접 사용)과 요약 카드 동일 분모. 용어 "실현 수익률" 통일. |
| P24 (단순성) | ✅ | 분모 추정 로직(스냅샷 우선 → earliestBaseAsset → 투자원금+누적손익) 제거. `account_daily_snapshot` 의존 제거. `computeCumulativePnl` 분기 로직 축소. |
| P25 (격리된 실패) | ✅ | 변경 없음 — 계산 함수 실패 시 해당 카드만 영향. |

---

## 5. 영향 범위

- **프론트엔드**: 6~8파일 수정 예상 (`profit-math.ts`, `profit-shared.ts`, `profit-overview-mount.ts`, `profit-detail-display.ts`, `profit-detail-mount.ts`, `profit-shared.test.ts` + UI 명칭 변경 파일 `profit-columns.ts`, `sell-position.ts` 일부)
- **백엔드**: 변경 없음 (이미 매수원금 기반 — `get_daily_summary` pnl_rate 유지)
- **DB**: 변경 없음 (`account_daily_snapshot` 테이블 유지 — 프론트엔드 의존만 제거)
- **거래 로직**: 영향 없음 (수익 표시 전용 — safe-trade 스킬 미연계)

## 리스크/롤백 기준

- 거래 로직 변경 아님 → 리스크 낮음.
- 롤백 기준: 검증(typecheck/build/test) 실패 시. 단, 본 설계는 단순화 방향이므로 실패 시 원인 추적 용이.

---

## 6. UI 용어 변경 체크리스트

### 6.1 "실현 수익률"로 변경 (적용 대상)

| 위치 | 파일 | 현재 명칭 | 변경 후 | 비고 |
|------|------|-----------|---------|------|
| 요약 카드 4개 수익률 영역 | `profit-shared.ts` | (숫자만 표시, 라벨은 카드 타이틀 "당일 손익" 등) | 카드 타이틀 유지, 수익률 숫자 영역은 "실현 수익률" 맥락 | 카드 타이틀 "당일 손익"은 손익금 의미이므로 유지; 수익률이 "실현 수익률"임이 명확하도록 서브 텍스트 또는 툴팁 검토 |
| 드릴다운 테이블 헤더 | `profit-detail-display.ts:208` | `'수익률'` | `'실현 수익률'` | `createDrilldownTable(['날짜', '매도', '매수', '실현손익', '수익률'])` |
| 통계 라벨 | `profit-detail-mount.ts:161` | `'수익률'` | `'실현 수익률'` | `STAT_LABELS` 배열 5번째 |
| 거래내역 컬럼 헤더 | `profit-columns.ts:75` | `'수익률'` | `'실현 수익률'` | `{ key: 'pnl_rate', label: '수익률', ... }` |
| 차트 타이틀 | `profit-overview-mount.ts:136` | `'거래일별 수익률'` | `'거래일별 실현 수익률'` | `sectionTitle('거래일별 수익률')` |
| 도넛 중앙/업종별 종목 수익 타이틀 | `profit-overview-mount.ts:64-68` | "당일 손익"/"5거래일 손익" 등 | 유지 (손익금 라벨) + 수익률 숫자는 "실현 수익률" 맥락 | 타이틀은 손익금, 수익률 숫자는 본 설계 적용 |
| 계좌 현황 "누적 총 실현 수익률" | `account-labels.ts:17,31` | `'누적 총 실현 수익률'` | 유지 (이미 "실현" 포함) | 변경 없음 — 명칭 이미 부합 |

### 6.2 변경하지 않는 항목 (예외)

| 위치 | 파일 | 명칭 | 사유 |
|------|------|------|------|
| 보유 종목 평가 수익률 | `account-labels.ts:13,27` | `'보유 종목 평가 수익률'` | 평가 기반(미실현) — 실현 수익률 아님. 설계 원칙 3(보유 종목 제외) 준수. |
| 보유 종목 평가 손익금 | `account-labels.ts:12,26` | `'보유 종목 평가 손익금'` | 평가 기반 — 실현 수익률 계산과 무관. |
| 보유 종목 평가 금액 | `account-labels.ts:11,25` | `'보유 종목 평가 금액'` | 평가 기반 — 실현 수익률 계산과 무관. |
| sell-position 평가수익률 배지 | `sell-position.ts:175` | `'📈 평가수익률'` | 매도 화면의 보유종목 평가 기반 — 실현 아님. |
| sell-position 컬럼 수익률 | `sell-position.ts:70` | `'수익률'` | 매도 화면 보유종목 평가 수익률 — 실현 아님. (검토: "평가 수익률"로 명시 검토 가능하나 본 설계 범위 외 — 용어 정리 작업에서 처리) |

---

## 7. 제거 후 검증 항목

> 스냅샷 관련 코드 제거 후 반드시 확인해야 할 항목. 3세션 구현 단계에서 검증 게이트로 적용.

### 7.1 함수 호출처 0건 확인 (grep 검증)

| 제거 대상 함수 | 검색 패턴 | 기대 결과 |
|----------------|-----------|-----------|
| `extractEarliestBaseAsset` | `extractEarliestBaseAsset` (frontend/src 전체) | 호출처 0건 (정의 제거 후) |
| `findBaseAssetForDate` | `findBaseAssetForDate` (frontend/src 전체) | 호출처 0건 (정의 제거 후) |
| `cumulativeRealizedPnlBeforeDate` | `cumulativeRealizedPnlBeforeDate` (frontend/src 전체) | 호출처 0건 (정의 제거 후) |

### 7.2 참조 경로 제거 확인 (grep 검증)

| 제거 대상 참조 | 검색 패턴 | 기대 결과 |
|----------------|-----------|-----------|
| `base_asset` (프론트엔드) | `base_asset` (frontend/src 전체) | 0건 (백엔드 필드는 본 설계 범위 외 — 후순위) |
| `earliest_base_asset` (프론트엔드) | `earliest_base_asset` (frontend/src 전체) | 0건 (백엔드 필드는 본 설계 범위 외 — 후순위) |
| `earliestBaseAsset` (프론트엔드 변수) | `earliestBaseAsset` (frontend/src 전체) | 0건 |
| `baseAsset` (프론트엔드 변수, 분모용) | `baseAsset` (frontend/src 전체) | 0건 (단, 다른 맥락의 `baseAsset` 변수가 있다면 별도 확인) |
| `dayBaseAsset`/`fiveBaseAsset`/`monthBaseAsset` | 각 패턴 (frontend/src 전체) | 0건 |

### 7.3 표준 검증 게이트

- typecheck: `cd frontend && npm run typecheck` 통과
- build: `cd frontend && npm run build` 성공
- test: `cd frontend && npm run test` 통과 (8절 테스트 케이스 포함)

---

## 8. 테스트 케이스

> 계산식 변경 검증을 위한 최소 테스트 케이스. `profit-shared.test.ts`에 추가. 3세션 구현 단계에서 작성.

### 8.1 계산 정확성 케이스

| 케이스 | 입력 | 기대 결과 | 비고 |
|--------|------|-----------|------|
| 매도 없음 | sellHistory=[] | pnl=0, rate=0 | 분모 0 → `computeWeightedRate` 0 반환 |
| 1건 매도 (수익) | 매수 100만원 → 매도 105만원 | pnl=+5만원, rate=+5.00% | 단일 거래 정확성 |
| 1건 매도 (손실) | 매수 100만원 → 매도 98만원 | pnl=-2만원, rate=-2.00% | 단일 거래 손실 |
| 여러 건 매도 (모두 수익) | 3건: 100→105, 200→210, 300→309 | pnl=+24만원, rate=+4.00% (24/600) | 매수원금 합 분모 — 개별 평균 아님 |
| 손익 혼합 (+/-) | 100→105(+5), 200→198(-2), 300→309(+9) | pnl=+12만원, rate=+2.00% (12/600) | 손익 상쇄 + 매수원금 합 분모 |

### 8.2 기간별 케이스 (동일 공식 적용 — 설계 원칙 5 · 검증 원칙)

> 검증 원칙(0절) 검증: 동일 `sellHistory` 입력으로 4기간 모두 동일 공식(`aggregatePnl`) 적용, 기간 필터만 차이 확인.

| 케이스 | dateFrom/dateTo | 기대 | 비고 |
|--------|-----------------|------|------|
| 당일 | today ~ today | 당일 매도만 집계 | 개장 전 분기(PRE OPEN)는 기존 로직 유지 — 0원 + "개장 전" |
| 5거래일 | recent5[4] ~ recent5[0] | 5거래일 내 매도만 집계 | `getRecent5TradingDays` 공통 소스 |
| 당월 | monthStart ~ monthEnd | 당월 매도만 집계 | — |
| 누적 | (없음) | 전체 매도 집계 | `aggregatePnl(sellHistory)` 전체 범위 |

**검증 명제**: 4기간 케이스 모두 동일 `aggregatePnl` 함수 호출, 분모 규칙 분기 없음. 기간 필터(`dateFrom`/`dateTo`)만 입력 차이.

### 8.3 모드별 케이스

| 케이스 | isTestMode | 기대 rate | 비고 |
|--------|------------|-----------|------|
| 테스트모드 | true | 계산된 수익률 | `aggregatePnl` 결과 사용 |
| 실전모드 | false | null ('-') | 증권사 SSOT — 앱 재계산 금지 (변경 없음) |

### 8.4 기존 테스트 업데이트

- 직전 세션에서 추가된 스냅샷 분모 추정 테스트(`profit-shared.test.ts` 실전모드 4건 rate=null, 테스트모드 스냅샷 미존재 2건) → 매수원금 기반 기대값으로 업데이트.
- 스냅샷 의존 테스트 케이스 제거 (분모 추정 로직 제거로 인해 불필요).
