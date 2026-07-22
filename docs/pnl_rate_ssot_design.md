# 수익률 계산 SSOT/P22 일괄 정비 설계 문서

> 작성일: 2026-07-22
> 기준 문서: `ARCHITECTURE.md` (불변 원칙 24개)
> 관련 원칙: P10(SSOT), P21(사용자 투명성), P22(데이터 정합성), P23(일관성), P18(테스트모드 동등성)
> 상태: 설계 완료 — 사용자 승인 대기. 승인 후 다음 세션에서 작업 파일(tasks) 작성.

---

## 1. 문제 정의

### 1.1 배경

수익현황/수익상세 페이지의 "수익률(%)" 표시가 백엔드 일별 요약 API(`get_daily_summary`)가 제공하는 `pnl_rate`와 프론트엔드가 sellHistory 원시 레코드에서 재집계한 rate가 혼재. 동일한 "수익률" 용어가 여러 계산 경로에서 산출되어, 한쪽 공식 변경 시 타측과 불일치 위험(P22 위반) + 단일 진실 소스 부재(P10 위반).

### 1.2 발견된 3개 문제

#### 문제 A: `buildMonthlyDrilldown` SSOT 위반 (P10)

- **위치**: `frontend/src/pages/profit-shared.ts:304-336`
- **현상**: 당월 일별 요약 드릴다운 뷰가 `hotStore.dailySummary`(백엔드 제공 per-day rate 포함)를 무시하고, sellHistory 원시 레코드에서 `row.pnl / row.buyTotal × 100`로 per-day rate를 재계산 (line 332).
- **백엔드 동일 데이터**: `get_daily_summary()`(trade_history.py:527)가 동일 per-day rate를 이미 계산하여 `daily_summary` 응답에 포함.
- **영향**: 백엔드 공식 변경 시 드릴다운 뷰만 다른 수치 표시 → 사용자 혼란 (P21 위반).
- **위반 원칙**: P10(SSOT), P22(데이터 정합성), P21(사용자 투명성).

#### 문제 B: 수수료/세금 미포함 (P22/P21)

- **위치**: 백엔드 per-trade 레코드 생성 `trade_history.py:353,369` + per-day 집계 `trade_history.py:518-527`.
- **현상**: `realized_pnl = (price - avg_buy_price) × qty` (주석 명시 "수수료/세금 제외"), `buy_total = avg_buy_price × qty` (매수수수료 제외). pnl_rate 분자·분모 모두 수수료/세금 미포함.
- **대조**: `get_total_realized_pnl()`(trade_history.py:436-454)는 현금 기준 `total_amt - buy_total_amt`(수수료/세금 포함) 사용. 동일 "실현손익" 용어가 두 기준으로 혼용.
- **실제 영향**:
  - 실전모드: 수수료/세금 0 → 차이 없음.
  - 테스트모드: 수수료 0.015% + 세금 0.20% → 실제 체감 수익률보다 과대 표시. 빈번한 매도 시 왜곡 증폭.
- **위반 원칙**: P22(동일 "실현손익" 용어의 두 기준 혼용), P21(사용자가 과대 표시 인지 불가), P18(테스트모드에서만 왜곡 발생 → 모드 동등성 위반).

#### 문제 C: P22 공식 중복 위험 (백엔드/프론트엔드 독립 구현)

- **위치**:
  - 백엔드: `trade_history.py:527` (per-day 집계), `trade_history.py:369` (per-trade 레코드).
  - 프론트엔드: `profit-shared.ts:300` (`aggregatePnl`), `profit-shared.ts:183-185` (업종별), `profit-shared.ts:227` (종목별), `profit-shared.ts:332` (드릴다운 per-day), `profit-detail-display.ts:149-150` (필터 범위 가중 평균).
- **현상**: 동일 공식 `realized_pnl / buy_total × 100` (소수 2자리 반올림)이 7곳에서 독립 구현. 한쪽 변경 시 타측 불일치.
- **불가피성 검토**: 프론트엔드 집계 중 백엔드가 제공하지 않는 범위(종목 필터, 임의 날짜 범위, 업종별, 종목별)는 불가피. 단, **per-day rate는 백엔드가 제공하므로 재계산 불필요** (문제 A와 중복).
- **위반 원칙**: P22(파이프라인 단계 간 일관성), P23(동일 기능의 파일 간 일관성).

### 1.3 현황 지도 (pnl_rate 계산 분산)

| 위치 | 계산 범위 | 데이터 소스 | 백엔드 제공? | SSOT 위반? |
|------|----------|-------------|---------------|-------------|
| 백엔드 trade_history.py:369 | per-trade | 매도 체결 시점 | O (원본) | 아니요 (진실 소스) |
| 백엔드 trade_history.py:527 | per-day | sell_history 집계 | O | 아니요 (진실 소스) |
| FE profit-shared.ts:129,140 | 당일/직전 | dailySummary 직접 사용 | O | 아니요 (준수) |
| FE profit-shared.ts:155,159 | 당월/누적 | aggregatePnl 재집계 | X (미제공) | 불가피 |
| FE profit-shared.ts:183-185 | 업종별 | buildSectorDonutRows 재집계 | X | 불가피 |
| FE profit-shared.ts:227 | 종목별 | buildSectorStockPnl 재집계 | X | 불가피 |
| FE profit-shared.ts:300 | 범위 손익 | aggregatePnl 재집계 | X | 불가피 |
| **FE profit-shared.ts:332** | **당월 per-day** | **buildMonthlyDrilldown 재집계** | **O (dailySummary)** | **예 (문제 A)** |
| FE profit-detail-display.ts:150 | 필터 범위 가중 평균 | filteredSells 재집계 | X (종목 필터) | 불가피 (공식 중복 = 문제 C) |

---

## 2. 해결 방향

### 2.1 문제 A 해결: buildMonthlyDrilldown을 백엔드 dailySummary 기반으로 전환

**방향**: 드릴다운 뷰가 sellHistory 재집계 대신 `hotStore.dailySummary`에서 per-day rate를 직접 사용.

**전제 조건 검증 (실행 단계에서 확인 필요)**:
- dailySummary가 당월 전체 날짜를 포함하는지 (현재 `getDailySummary` 호출 범위 확인).
- dailySummary의 per-day rate가 드릴다운 뷰 요구사양(당월 일별)과 정합.
- buyCount/sellCount/pnl/buyTotal 필드가 dailySummary에 존재 (현재 buy_count, sell_count, realized_pnl, pnl_rate, buy_fee, sell_fee, tax 존재 — buyTotal은 미존재, 필요 시 백엔드 추가 또는 드릴다운 표시에서 buyTotal 컬럼 제거 검토).

**대안 (전제 조건 미충족 시)**:
- 백엔드 `get_daily_summary` 응답에 `buy_total` 필드 추가 → 프론트엔드는 dailySummary만 사용.
- 이 경우 백엔드 단일 진실 소스 1곳新增, 프론트엔드 재집계 제거.

**영향 범위**:
- `frontend/src/pages/profit-shared.ts` (buildMonthlyDrilldown 시그니처 변경 또는 삭제)
- `frontend/src/pages/profit-detail-display.ts:106` (showDrilldown 호출부)
- `frontend/src/pages/profit-detail-mount.ts` (초기화 데이터 소스)
- `frontend/src/types/index.ts` (DailyDrilldownRow 타입 조정)
- (대안 적용 시) `backend/app/services/trade_history.py:522-531` (buy_total 필드 추가)

### 2.2 문제 B 해결: 수수료/세금 포함 기준으로 pnl_rate 통일

**방향**: pnl_rate를 "현금 기준 실제 수익률"로 통일 — 분자·분모 모두 수수료/세금 포함.

**새 공식**:
```
realized_pnl_net = sell_net - buy_total  (수수료/세금 포함)
  sell_net = price × qty - sell_fee - sell_tax  (이미 total_amt로 저장됨)
  buy_total = avg_buy_price × qty + buy_fee  (이미 buy_total_amt로 저장됨)
pnl_rate = realized_pnl_net / buy_total × 100  (소수 2자리 반올림)
```

**대안 B-1 (사용자 승인 필요)**: 현재 "순수 차익" 기준 유지 + 용어 명확화
- "실현손익" = 순수 차익 (수수료/세금 제외) — 현재 방식 유지
- "실현손익(현금)" = 현금 기준 (수수료/세금 포함) — `get_total_realized_pnl`이 이미 사용
- UI에서 두 값을 모두 표시하거나, "수익률" 라벨을 "수익률(수수료 제외)"로 명시
- **단점**: 사용자가 두 수치 혼란 가능 (P21 위반 잔존)

**대안 B-2 (권장)**: 현금 기준으로 단일 통일
- per-trade 레코드의 `realized_pnl`/`pnl_rate`를 현금 기준으로 변경
- `get_total_realized_pnl`과 동일 기준 → 용어 단일화 (P22/P23)
- 실전모드: 수수료/세금 0이므로 영향 없음 (P18 동등성 유지)
- 테스트모드: 실제 체감 수익률로 정확 표시 (P21 해결)
- **영향 범위**:
  - `backend/app/services/trade_history.py:353,369` (per-trade 레코드 생성)
  - `backend/app/services/trade_history.py:518-527` (per-day 집계)
  - DB 기존 레코드: 과거 데이터는 순수 차익 기준 → 마이그레이션 검토 (또는 기동 시 재계산)
  - 프론트엔드: 백엔드 값 그대로 사용하므로 프론트엔드 공식 중복 일부 자연 해소 (문제 C 연계)

**주의 (규칙 0-5)**: 이 pnl_rate 공식은 `trade_history.py:340-376`의 per-trade 레코드 생성 로직에 깊이 연결. 사용자가 이전에 설계/승인한 로직일 가능성. 변경 전 사용자에게 UI 기준 영향 설명 + 승인 필수 (규칙 0-4).

### 2.3 문제 C 해결: 공식 중복 통제 지점 신설

**방향**: 백엔드가 제공하지 않는 범위(업종별/종목별/임의 범위)의 프론트엔드 재집계는 불가피하므로, **공식을 공통 함수로 통일**하여 변경 지점을 1곳으로 집중.

**조치**:
- 프론트엔드 `profit-shared.ts`에 `computeWeightedRate(pnl, buyTotal): number` 공통 함수 신설 (소수 2자리 반올림 포함).
- `aggregatePnl`, `buildSectorDonutRows`, `buildSectorStockPnl`, `buildMonthlyDrilldown`(문제 A 해결 후 잔존 시), `updateStatistics`가 모두 이 함수 사용.
- 백엔드 공식 변경 시(문제 B 해결) 프론트엔드 공통 함수 1곳만 동기화.
- **P23 준수**: 동일 기능의 파일 간 일관성 확보.

**영향 범위**:
- `frontend/src/pages/profit-shared.ts` (공통 함수 신설 + 5곳 호출부 변경)
- `frontend/src/pages/profit-detail-display.ts:149-150` (공통 함수 사용)

### 2.4 원칙 준수 매핑

| 원칙 | 문제 A 해결 | 문제 B 해결 | 문제 C 해결 |
|------|-------------|-------------|-------------|
| P10 (SSOT) | O — dailySummary 단일 소스 사용 | O — 현금 기준 단일 진실 | 부분 — 공통 함수로 변경 지점 1곳 |
| P21 (투명성) | O — 백엔드 값과 UI 일치 | O — 실제 체감 수익률 표시 | — |
| P22 (정합성) | O — 재계산 제거 | O — "실현손익" 용어 단일 기준 | O — 공식 일관성 통제 |
| P23 (일관성) | — | O — 용어 통일 | O — 공식 구현 통일 |
| P18 (모드 동등성) | — | O — 테스트모드 왜곡 제거, 실전은 영향 없음 | — |

---

## 3. 영향 범위 요약

### 3.1 백엔드

| 파일 | 변경 내용 | 문제 |
|------|----------|------|
| `backend/app/services/trade_history.py` | per-trade 레코드 realized_pnl/pnl_rate 공식 변경 (B-2 채택 시), per-day 집계 buy_total 필드 추가 (대안 A 적용 시) | B, A |
| DB `trades` 테이블 | 기존 레코드의 realized_pnl/pnl_rate 값 기준 변경 — 마이그레이션 또는 재계산 검토 | B |

### 3.2 프론트엔드

| 파일 | 변경 내용 | 문제 |
|------|----------|------|
| `frontend/src/pages/profit-shared.ts` | buildMonthlyDrilldown을 dailySummary 기반 전환, computeWeightedRate 공통 함수 신설 + 5곳 호출부 변경 | A, C |
| `frontend/src/pages/profit-detail-display.ts` | updateStatistics의 avgRate 계산을 공통 함수 사용 | C |
| `frontend/src/pages/profit-detail-mount.ts` | showDrilldown 데이터 소스 변경 연계 | A |
| `frontend/src/types/index.ts` | DailyDrilldownRow 타입 조정 | A |

### 3.3 테스트

| 파일 | 변경 내용 |
|------|----------|
| `backend/tests/test_trade_history.py` (존재 시) | realized_pnl/pnl_rate 공식 변경 반영 |
| 프론트엔드 테스트 (vitest) | buildMonthlyDrilldown 테스트 케이스 조정 |

### 3.4 문서

| 파일 | 변경 내용 |
|------|----------|
| `HANDOVER.md` | 작업 완료 후 직전 완료 작업 섹션 갱신 |
| `docs/architecture_audit_plan.md` | 관련 위반 항목 해결 표시 (해당 시) |

---

## 4. 위험 및 주의사항

### 4.1 규칙 0-5 해당 로직 (사용자 설계/승인 로직)

- `trade_history.py:340-376`의 per-trade realized_pnl/pnl_rate 공식은 사용자가 이전에 설계/승인한 로직일 가능성.
- 문제 B 해결(공식 변경)은 반드시 사용자에게 UI 기준 영향 설명 + 명시적 승인 필요 (규칙 0-4, 0-5).
- 특히 "순수 차익" 기준이 의도적 설계였는지 확인 필요 — 실전모드에서 수수료/세금이 0이므로 테스트모드에서만 의미 있는 차이.

### 4.2 DB 기존 데이터 마이그레이션 (문제 B-2 채택 시)

- 기존 `trades` 테이블 레코드의 `realized_pnl`/`pnl_rate`는 순수 차익 기준.
- 공식 변경 시 신규 레코드만 현금 기준이 되어 과거/현재 데이터 불일치 (P22 위반).
- 해결 옵션:
  1. 기동 시 재계산 (trades 테이블 전체 스캔 + UPDATE) — I/O 비용.
  2. 마이그레이션 스크립트 1회 실행 — 사용자 승인 필요.
  3. 기존 데이터는 순수 차익 기준 유지, 신규 데이터만 현금 기준 — P22 위반 잔존 (부적합).
- 안전 규칙: DB 스키마/데이터 변경 전 `stocks.db` 백업 필수 (db-backup 스킬).

### 4.3 실전모드/테스트모드 동등성 (P18)

- 문제 B-2 해결 시 실전모드는 수수료/세금 0이므로 공식 변경 영향 없음 → P18 유지.
- 단, 공식 변경 로직이 모드 분기 없이 동일 적용되는지 검증 필요 (P18 준수).

### 4.4 세션 분할 (규칙 0-1)

- 본 설계 문서는 1단계(설계) 완료.
- 다음 세션: 작업 파일(tasks) 작성 — 단계별 체크리스트.
- 이후: 문제 A → 문제 C → 문제 B 순으로 단계별 실행 (각 세션당 1단계).
- 문제 B는 DB 마이그레이션 수반 → 별도 세션 + 사용자 승인 필수.

---

## 5. 다음 세션 인계 사항

1. **작업 파일 작성**: `docs/pnl_rate_ssot_tasks.md` — 문제 A/C/B 각 단계별 체크리스트 + 검증 항목.
2. **사용자 결정 필요 사항**:
   - 문제 B 해결 방향 선택 (B-1 용어 명확화 vs B-2 현금 기준 통일).
   - B-2 선택 시 DB 기존 데이터 마이그레이션 방식 선택.
3. **실행 순서 (제안)**:
   - 1단계: 문제 A (buildMonthlyDrilldown SSOT) — 프론트엔드 단독, 백엔드 영향 최소.
   - 2단계: 문제 C (공통 함수 통일) — 프론트엔드 단독.
   - 3단계: 문제 B (수수료/세금 포함) — 백엔드 + DB, 사용자 승인 필수.

---

## 6. 승인 대기 항목

- [ ] 본 설계 문서의 문제 정의·해결 방향·영향 범위 승인.
- [ ] 문제 B 해결 방향 (B-1 vs B-2) 사전 선택 — 다음 세션 tasks 작성 전 확정 필요.
- [ ] 작업 파일(tasks) 작성 진행 승인.
