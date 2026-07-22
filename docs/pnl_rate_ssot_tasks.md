# 수익률 계산 SSOT/P22 일괄 정비 작업 파일

> 작성일: 2026-07-22
> 기준 설계: `docs/pnl_rate_ssot_design.md`
> 관련 원칙: P10(SSOT), P21(사용자 투명성), P22(데이터 정합성), P23(일관성), P18(테스트모드 동등성)
> 사용자 결정: 문제 B는 B-2(수수료/세금 포함 현금 기준 진짜 수익률)로 확정.
> 상태: 작업 파일 작성 완료 — 사용자 승인 대기. 승인 후 단계별 실행 (세션당 1단계, 규칙 0-1).

---

## 0. 세션 분할 및 실행 순서

| 세션 | 단계 | 내용 | 영역 | 사용자 승인 필요 |
|------|------|------|------|-------------------|
| 1 | A | buildMonthlyDrilldown SSOT 위반 해결 | 프론트엔드 | 사전조사 + 수정 계획 승인 |
| 2 | C | 공통 함수 computeWeightedRate 신설 + 7곳 호출부 통일 | 프론트엔드 | 사전조사 + 수정 계획 승인 |
| 3 | B-사전 | DB 백업 + 마이그레이션 방식 확정 | 백엔드/DB | DB 백업 승인 + 마이그레이션 방식 승인 |
| 4 | B-본 | per-trade realized_pnl/pnl_rate 공식 현금 기준 전환 + 기존 데이터 마이그레이션 | 백엔드/DB | 핵심 로직 변경 승인 (규칙 0-4/0-5) |
| 5 | B-연계 | 프론트엔드 공식 동기화 + 테스트 갱신 | 프론트엔드/테스트 | 사전조사 + 수정 계획 승인 |

> 각 세션은 규칙 0-1(세션당 1단계) 준수. 검증(테스트 + 런타임 기동/빌드) 완료 후 커밋 + HANDOVER.md 갱신 + 사용자 보고 후 세션 종료.

---

## 1. 단계 A: buildMonthlyDrilldown SSOT 위반 해결

### 1.1 목표

- 드릴다운 뷰(수익상세 페이지 "당월 일별 요약")가 sellHistory 재집계 대신 백엔드 `dailySummary`의 per-day rate를 직접 사용.
- P10(SSOT), P22(데이터 정합성), P21(사용자 투명성) 준수.

### 1.2 사전조사 항목 (수정 전 필수, 규칙 0-2)

- [ ] **의존성**: `buildMonthlyDrilldown` 호출부 전체 식별 (showDrilldown, 테스트 파일).
- [ ] **영향범위**: profit-shared.ts, profit-detail-display.ts, profit-detail-mount.ts, types/index.ts, 테스트 파일.
- [ ] **dailySummary 필드 확인**: 당월 범위 조회 시 per-day rate/buy_count/sell_count/realized_pnl 포함 여부. buyTotal 필드 존재 여부 (현재 미존재 — 백엔드 추가 또는 드릴다운 컬럼에서 buyTotal 제거 검토).
- [ ] **dailySummary 당월 범위 보장**: showDrilldown 호출 시점에 hotStore.dailySummary가 당월 전체를 포함하는지 확인 (현재 applyDateRange에서 조회 범위 확인 필요).
- [ ] **아키텍처 원칙 부합**: P10(SSOT) — dailySummary 단일 소스. P22 — 재계산 제거. P21 — 백엔드 값과 UI 일치.
- [ ] **기존 공통 자산 확인**: dailySummary 기반 차트 변환 `buildChartFromDailySummary`(profit-shared.ts:339)가 이미 동일 패턴 사용 — 참고.

### 1.3 수정 체크리스트

- [ ] **백엔드 검토**: `get_daily_summary` 응답에 `buy_total` 필드 추가 필요 여부 결정 (드릴다운 표시 컬럼 요구사항 기준).
  - 옵션 1: 백엔드에 `buy_total` 필드 추가 (trade_history.py:522-531) → 프론트엔드는 dailySummary만 사용.
  - 옵션 2: 드릴다운 표시에서 buyTotal 컬럼 제거 → 백엔드 변경 없음.
  - 사용자와 확인 후 결정.
- [ ] **프론트엔드 buildMonthlyDrilldown 재작성**: sellHistory/buyHistory 인자 대신 dailySummary 인자 사용. per-day rate는 `Number(r.pnl_rate ?? 0)` 직접 사용.
- [ ] **DailyDrilldownRow 타입 조정**: buyTotal 필드 제거 시 타입에서도 제거 (P23 일관성).
- [ ] **showDrilldown 호출부 갱신**: `buildMonthlyDrilldown(state.sellHistory, state.buyHistory, yearMonth)` → `buildMonthlyDrilldown(hotStore.getState().dailySummary, yearMonth)` (profit-detail-display.ts:106).
- [ ] **초기화 연계**: profit-detail-mount.ts에서 dailySummary가 당월 범위 보장하도록 초기 조회 확인 (필요 시 applyDateRange 호출 추가).
- [ ] **테스트 갱신**: buildMonthlyDrilldown 테스트 케이스 시그니처 변경 반영.

### 1.4 검증

- [ ] `npm run typecheck` exit 0
- [ ] `npm run build` exit 0
- [ ] `npx vitest run` — buildMonthlyDrilldown 관련 테스트 통과
- [ ] (백엔드 변경 시) 백엔드 테스트 + 런타임 기동 (규칙 5)

### 1.5 완료 조건

- 드릴다운 뷰 per-day rate가 백엔드 dailySummary 값과 일치.
- sellHistory 재집계 코드 제거 (P16 살아있는 경로 — dead code 잔존 금지).
- HANDOVER.md 직전 완료 작업 섹션 갱신.

---

## 2. 단계 C: 공통 함수 computeWeightedRate 신설 + 7곳 호출부 통일

> **갱신 (2026-07-22)**: 사전조사 결과 작업 파일 예상 5곳이 아닌 7곳으로 확정.
> - 단계 A에서 buildMonthlyDrilldown per-day rate이 백엔드 값 직접 사용으로 전환되어 1곳 감소.
> - 조사로 3곳 추가 발견: profit-shared.ts:245(업종 합계 수익률), profit-shared.ts:368(보유종목 평가손익 수익률), canvas-sector-donut.ts:203(도넛 차트 누적 수익률).
> - 함수 위치를 profit-shared.ts가 아닌 `components/common/ui-styles.ts`로 변경 — canvas-sector-donut.ts와의 순환 참조 방지 + fmtRate/pnlColor 등 동일 성격 공통 함수군과 함께 배치.

### 2.1 목표

- 프론트엔드 내 pnl_rate 공식(소수 2자리 반올림)을 공통 함수 1곳으로 통일.
- 백엔드 공식 변경 시(단계 B) 프론트엔드 동기화 지점 1곳으로 집중.
- P22(파이프라인 단계 간 일관성), P23(동일 기능 파일 간 일관성) 준수.

### 2.2 사전조사 항목 (수정 전 필수, 규칙 0-2)

- [x] **의존성**: 공식 `Math.round(pnl / buyTotal * 10000) / 100` 사용 7곳 식별 (단계 A 이후 잔존):
  - profit-shared.ts:183 (buildSectorDonutRows — 업종별 도넛 행 수익률)
  - profit-shared.ts:226 (buildSectorStockPnl — 종목별 수익률)
  - profit-shared.ts:245 (buildSectorStockPnl — 업종 합계 수익률, 작업 파일 누락분)
  - profit-shared.ts:299 (aggregatePnl — 범위 손익 집계 수익률)
  - profit-shared.ts:368 (computeHoldingsSummary — 보유종목 평가손익 수익률, 작업 파일 누락분)
  - profit-detail-display.ts:151 (updateStatistics — 통계 가중평균 수익률)
  - canvas-sector-donut.ts:203 (도넛 차트 중앙 누적 수익률, 작업 파일 누락분)
- [x] **영향범위**: profit-shared.ts, profit-detail-display.ts, canvas-sector-donut.ts, components/common/ui-styles.ts (신규 함수).
- [x] **아키텍처 원칙 부합**: P23(일관성) — 공통 함수 재사용. P22 — 공식 통제 지점 단일화. P24(단순성) — 1회용 래퍼 아님 (7곳 재사용). P10(SSOT) — 공식 1곳 정의.
- [x] **기존 공통 자산 확인**: ui-styles.ts에 fmtRate/pnlColor/rateColor 등 동일 성격 공통 함수 존재 → 이 파일에 배치가 자연스러움. computeWeightedRate 기존 함수 없음 (신설 확정).
- [x] **순환 참조 검토**: profit-shared.ts가 canvas-sector-donut.ts를 사용 중 → 함수를 profit-shared.ts에 두면 역방향 참조 발생. ui-styles.ts는 두 파일 모두 이미 import 중이므로 순환 없음.

### 2.3 수정 체크리스트

- [x] **공통 함수 신설**: `components/common/ui-styles.ts`에 `computeWeightedRate(pnl: number, buyTotal: number): number` 추가. 구현: `buyTotal > 0 ? Math.round(pnl / buyTotal * 10000) / 100 : 0`.
- [x] **7곳 호출부 변경**: 직접 공식 → `computeWeightedRate(pnl, buyTotal)` 호출.
- [x] **import 추가**: profit-shared.ts, profit-detail-display.ts, canvas-sector-donut.ts의 ui-styles import 라인에 computeWeightedRate 추가.
- [x] **export**: ui-styles.ts에 export function으로 정의 (타 모듈 사용 가능).

### 2.4 검증

- [x] `npm run typecheck` exit 0
- [x] `npm run build` exit 0 (1.99s)
- [x] `npx vitest run` — 8 files / 116 tests passed (8.07s, 공식 동일하므로 수치 변화 없음)

### 2.5 완료 조건

- [x] pnl_rate 공식이 components/common/ui-styles.ts 1곳에서만 정의.
- [x] 7곳 호출부가 모두 공통 함수 사용.
- [x] HANDOVER.md 직전 완료 작업 섹션 갱신.

---

## 3. 단계 B-사전: DB 백업 + 마이그레이션 방식 확정

### 3.1 목표

- 문제 B-2(현금 기준 진짜 수익률) 적용 전 DB 백업 수행.
- 기존 trades 테이블 레코드의 realized_pnl/pnl_rate 마이그레이션 방식 확정.

### 3.2 사전조사 항목 (수정 전 필수, 규칙 0-2)

- [x] **의존성**: trades 테이블의 realized_pnl/pnl_rate 필드를 읽는 코드 경로 식별 — trade_history.py per-trade 생성(353,369), per-day 집계(518,527), get_total_realized_pnl(453), risk_manager.py 연속손실 카운트(63), 프론트엔드 수익률 표시 전체.
- [x] **영향범위**: backend/app/services/trade_history.py, DB trades 테이블(stock_tables.py:22-43 — realized_pnl/pnl_rate/buy_total_amt 필드 모두 존재, 스키마 변경 불필요), 프론트엔드 수익률 표시 전체.
- [x] **기존 데이터 규모**: trades 테이블 SELL 레코드 **0건** (전체 0건). test_positions 테이블 3건은 pnl_amount/pnl_rate(평가손익) 필드이며 realized_pnl/buy_total_amt 없음 → 마이그레이션 대상 아님.
- [x] **마이그레이션 방식 결정**: **옵션 2(1회 마이그레이션 스크립트 실행)** 확정 (사용자 결정 2026-07-22). 옵션 1(기동 시 재계산)은 기각. 옵션 3(P22 위반 잔존)은 부적합 후보에서 제외.
- [x] **아키텍처 원칙 부합**: P22(데이터 정합성) — 과거/현재 데이터 기준 일치. P18(모드 동등성) — 실전/테스트 동일 마이그레이션 적용 (실전은 fee/tax=0이므로 영향 없음).

### 3.3 수정 체크리스트

- [x] **DB 백업**: db-backup 스킬 호출 — stocks.db.20260722_230709.backup (1.2M), stocks.db-shm.20260722_230709.backup (32K), stocks.db-wal.20260722_230709.backup (0B). 백엔드 미실행 상태에서 안전 백업.
- [x] **마이그레이션 방식 사용자 승인**: 옵션 2(1회 스크립트 실행) 확정.
- [x] **마이그레이션 스크립트 설계** (옵션 2 적용, 사용자 설계 승인 2026-07-22):
  - 대상: `trades` 테이블 SELL 레코드 전체 (현재 0건, 향후 매도 발생 시 대상)
  - 조건: `side='SELL' AND avg_buy_price > 0 AND buy_total_amt > 0` (유령 데이터/0매입 제외, trade_history.py:340 안전장치와 동일 기준)
  - `realized_pnl = total_amt - buy_total_amt` (현금 기준 재계산)
  - `pnl_rate = round(realized_pnl / buy_total_amt * 100, 2)` (buy_total_amt 기준, 수수료 포함)
  - UPDATE 쿼리 1건 실행 (트랜잭션 단위)
  - **idempotent (멱등)**: 이미 현금 기준인 레코드는 재실행해도 동일값 → 안전 재실행 가능
  - **스키마 변경 없음**: UPDATE만, DDL 없음
  - **모드 무관**: trade_mode 분기 없이 동일 적용 (P18 준수)
  - 실행 시점: 단계 B-본 세션에서 per-trade 생성 공식 변경 직후 실행 (같은 세션 내)

### 3.4 검증

- [x] DB 백업 파일 생성 확인 (타임스탬프 20260722_230709 포함, 3개 파일 모두 존재).
- [x] 마이그레이션 방식 사용자 승인 확보 (설계 승인 2026-07-22).

### 3.5 완료 조건

- [x] DB 백업 완료.
- [x] 마이그레이션 방식 확정 + 사용자 승인.
- [x] HANDOVER.md 직전 완료 작업 섹션 갱신.

---

## 4. 단계 B-본: per-trade realized_pnl/pnl_rate 공식 현금 기준 전환 + 마이그레이션

### 4.1 목표

- per-trade 레코드 생성 시 realized_pnl/pnl_rate를 현금 기준(수수료/세금 포함)으로 변경.
- 기존 trades 테이블 레코드 마이그레이션 실행.
- P22(데이터 정합성), P21(사용자 투명성), P18(테스트모드 동등성) 준수.

### 4.2 사전조사 항목 (수정 전 필수, 규칙 0-2 + 규칙 0-4/0-5)

- [x] **의존성**: trade_history.py:340-376 per-trade 레코드 생성 로직이 영향 주는 모든 코드 경로 — record_sell(353,369), get_daily_summary(518-519,527), get_total_realized_pnl(453, 이미 현금 기준), risk_manager.py:63(부호만 판별, 영향 없음), build_positions_from_trades(645-650, docstring만).
- [x] **영향범위**: 백엔드 집계(get_daily_summary, get_total_realized_pnl, build_positions_from_trades), 테스트 파일. 프론트엔드 수익률 표시는 단계 B-연계(세션 5)에서 처리.
- [x] **규칙 0-5 해당 여부**: per-trade realized_pnl/pnl_rate 공식이 사용자가 이전에 승인한 로직 — 변경 사유(P22/P21 위반, 두 기준 혼재)·영향(매도 체결값, 일별 요약, 연속손실 부호 동일)·대안(유지 시 위반 지속) 상세 보고 후 승인 (2026-07-22).
- [x] **규칙 0-4 UI 기준 설명**: 변경 전(순수 차익, 테스트모드 과대 표시) vs 변경 후(현금 기준, 실제 체감 수익률)를 UI 기준 일반 용어로 설명 — 예: 7만원 매수→6.9만원 매도 시 −10,000원/−1.43% → −11,589원/−1.66%. 승인 확보 (2026-07-22).
- [x] **P18 동등성**: 공식 변경이 모드 분기 없이 동일 적용 확인 (실전: 수수료/세금 0 → 영향 없음, 테스트: 정확한 수익률).
- [x] **아키텍처 원칙 부합**: P22 — 과거/현재 데이터 기준 일치. P21 — 실제 체감 수익률 표시. P23 — "실현손익" 용어 단일 기준.

### 4.3 수정 체크리스트

- [x] **per-trade 레코드 공식 변경** (trade_history.py:352-368):
  - `realized_pnl = (price - avg_buy_price) * qty` → `realized_pnl = sell_net - buy_total` (현금 기준)
  - `pnl_rate = round(realized_pnl / buy_principal * 100, 2)` → `pnl_rate = round(realized_pnl / buy_total * 100, 2)` (buy_total 기준, 수수료 포함)
  - `buy_principal` 변수 제거 (P24 단순성, 더 이상 사용 안 함)
  - 주석 갱신: "순수 차익(수수료/세금 제외)" → "현금 기준 실현손익(수수료/세금 포함)"
- [x] **per-day 집계 공식 변경** (trade_history.py:517-518):
  - `realized_pnl += rec["realized_pnl"]` (이미 현금 기준으로 변경된 per-trade 값 합산)
  - `buy_total += (rec["avg_buy_price"] or 0) * (rec["qty"] or 0)` → `buy_total += rec.get("buy_total_amt") or 0` (수수료 포함)
  - pnl_rate 공식은 동일 (realized_pnl / buy_total × 100) — 분자·분모 모두 현금 기준으로 일관.
- [x] **build_positions_from_trades docstring 갱신** (trade_history.py:647-650): "pnl_amount/pnl_rate는 순수 차익(수수료/세금 제외)" → "현금 기준(수수료/세금 포함)".
- [x] **마이그레이션 실행**: `backend/scripts/migrate_realized_pnl_cash.py` 신설 + 실행. 대상 0건(현재 SELL 레코드 없음) → 갱신 대상 없음. 멱등 확인.
- [x] **get_total_realized_pnl 일관성 확인**: 이미 현금 기준(`total_amt - buy_total_amt`) 사용 중 — 공식 변경 후 per-trade realized_pnl과 동일 기준 확인 (P22 일관성).
- [x] **테스트 갱신**: `_make_sell_rec` 헬퍼 + `test_daily_summary_no_duplicate_buy_total` + `test_daily_summary_fee_tax_aggregation` 주입 데이터 현금 기준으로 갱신.

### 4.4 검증

- [x] `python -m py_compile backend/app/services/trade_history.py` 성공
- [x] 백엔드 테스트: `pytest backend/tests/test_trade_history.py` — 64 passed (realized_pnl/pnl_rate 공식 변경 반영)
- [x] 전체 백엔드 테스트: `pytest backend/tests/` — 2790 passed
- [x] 런타임 기동 (규칙 5): `python -W error::RuntimeWarning main.py` — 앱 시작 완료, RuntimeWarning 에러 없음. 매수 0건/매도 0건 정상 로드.
- [x] 마이그레이션 후 trades 테이블 기존 레코드 realized_pnl/pnl_rate 값이 현금 기준인지 확인 — 대상 0건으로 갱신 없음, 향후 매도 시 현금 기준 적용.

### 4.5 완료 조건

- [x] per-trade realized_pnl/pnl_rate가 현금 기준으로 계산.
- [x] 기존 trades 레코드 마이그레이션 완료 (대상 0건, 멱등 스크립트 보관).
- [x] 실전/테스트 모드 동등성 유지 (P18).
- [x] HANDOVER.md 직전 완료 작업 섹션 갱신 (마이그레이션 사유 포함, 규칙 0-3).

---

## 5. 단계 B-연계: 프론트엔드 공식 동기화 + 테스트 갱신

### 5.1 목표

- 프론트엔드 공통 함수 `computeWeightedRate`(단계 C 신설)가 백엔드 현금 기준 공식과 일치하는지 확인.
- 프론트엔드 집계(업종별/종목별/임의 범위)가 현금 기준으로 동작하도록 동기화.
- 테스트 케이스 현금 기준으로 갱신.

### 5.2 사전조사 항목 (수정 전 필수, 규칙 0-2)

- [ ] **의존성**: 프론트엔드가 sellHistory의 `realized_pnl`/`avg_buy_price`/`qty`를 사용하는 모든 집계 지점.
- [ ] **영향범위**: profit-shared.ts (aggregatePnl, buildSectorDonutRows, buildSectorStockPnl), profit-detail-display.ts (updateStatistics).
- [ ] **공식 일치 확인**: 프론트엔드 `computeWeightedRate(pnl, buyTotal)`의 분자·분모가 백엔드 현금 기준과 동일한지.
  - 분자: `realized_pnl` (백엔드 per-trade가 현금 기준으로 변경되면 자동 동기화 — sellHistory에서 그대로 읽음)
  - 분모: 현재 `avg_buy_price * qty` (수수료 미포함) → `buy_total_amt` (수수료 포함)로 변경 필요 여부 확인.
- [ ] **아키텍처 원칙 부합**: P22 — 백엔드/프론트엔드 공식 일치. P23 — 공통 함수 일관성.

### 5.3 수정 체크리스트

- [ ] **프론트엔드 분모 변경** (필요 시): `avg_buy_price * qty` → `buy_total_amt` (수수료 포함). sellHistory 레코드에 `buy_total_amt` 필드 존재 확인.
- [ ] **computeWeightedRate 호출부 확인**: 5곳 모두 현금 기준 분자·분모 사용.
- [ ] **테스트 갱신**: vitest 테스트 케이스의 기대값을 현금 기준으로 조정.
- [ ] **UI 수치 변화 확인**: 테스트모드에서 수익률 표시가 기존보다 낮아짐(수수료/세금 반영) — 사용자에게 사전 안내 (P21).

### 5.4 검증

- [ ] `npm run typecheck` exit 0
- [ ] `npm run build` exit 0
- [ ] `npx vitest run` — 현금 기준 기대값으로 갱신된 테스트 통과
- [ ] 브라우저 확인: 수익현황/수익상세 페이지 수익률 표시가 백엔드 dailySummary와 일치

### 5.5 완료 조건

- 프론트엔드 집계가 백엔드 현금 기준과 동일 공식 사용.
- 테스트 케이스 현금 기준 반영.
- HANDOVER.md 직전 완료 작업 섹션 갱신.

---

## 6. 전체 완료 조건

- [ ] 문제 A: buildMonthlyDrilldown이 백엔드 dailySummary 사용 (P10/P22/P21 준수)
- [ ] 문제 C: pnl_rate 공식이 computeWeightedRate 공통 함수 1곳에서 정의 (P22/P23 준수)
- [ ] 문제 B: per-trade realized_pnl/pnl_rate가 현금 기준 (수수료/세금 포함) (P22/P21/P18 준수)
- [ ] 기존 trades 레코드 마이그레이션 완료 (P22 과거/현재 일치)
- [ ] 실전/테스트 모드 동등성 유지 (P18)
- [ ] 프론트엔드/백엔드 공식 일치 (P22)
- [ ] 모든 테스트 통과
- [ ] HANDOVER.md 최종 갱신
- [ ] docs/architecture_audit_plan.md 관련 위반 항목 해결 표시 (해당 시)

---

## 7. 승인 대기 항목

- [ ] 본 작업 파일의 단계 분할·체크리스트·검증 항목 승인.
- [ ] 단계 A 실행 시작 승인 (다음 세션).
- [ ] 단계 B-사전의 마이그레이션 방식(옵션 1 기동 시 재계산 vs 옵션 2 스크립트) 사전 선택 — 단계 B-사전 세션 전 확정.
