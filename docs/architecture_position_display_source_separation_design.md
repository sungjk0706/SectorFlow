# 설계서: 보유종목 화면 표시 소스 분리 — master_stocks_cache(표시) · positions(계산) 역할 명확화

> **상태**: 설계 완료, 승인 대기
> **작성일**: 2026-08-01
> **관련 원칙**: P10(SSOT) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패) · W7(시뮬레이터/증권사 응답 동일 구조)
> **관련 파일**: `frontend/src/pages/sell-position.ts` · `frontend/src/pages/profit-math.ts` · `frontend/src/pages/profit-shared.ts` · `frontend/src/types/index.ts` · `frontend/src/stores/hotStore.ts` · `backend/app/services/engine_account_rest.py` · `backend/app/services/dry_run.py` · `backend/app/services/trade_history.py` · `backend/app/services/trading.py` · `backend/app/services/engine_initial_data.py` · `backend/app/services/engine_account_notify.py`
> **관련 API 스펙**: positions payload 필드명 (프론트/백엔드 WS 계약 — 이름 변경 옵션 시 영향)
> **선행 작업**: `docs/architecture_cur_price_fallback_removal_design.md` (avg_price 폴백 제거, 커밋 `e0055c6`) — 본 설계의 직전 작업. positions.cur_price가 None을 유지하는 구조 위에 표시 소스 분리를 얹음.

---

## 금지사항 (Not To Do) — 본 작업에서 절대 수행하지 않는 것

> 구현 과정에서 범위가 자연스럽게 확장되는 것을 방지하기 위한 명시적 경계. 본 설계의 핵심은 **"기존 구조의 책임을 명확히 하는 것만으로 표시 정책이 달성된다"**이며, 아래 항목들은 이 원칙에 반하는 과도한 확장이다.

| 금지 항목 | 사유 |
|---|---|
| `confirmed_cur_price` 별도 필드/컬럼 추가 | `master_stocks_cache.cur_price` 생명주기가 확정가→None→실시간가 자연 전환으로 이미 달성. 별도 필드는 제2의 생명주기를 만들어 P10/P24 위반 |
| `confirmed_price_displayable` 파생 플래그 추가 | 표시 정책이 cur_price 생명주기로 자동 달성되므로 창구 제어 플래그 불필요. 플래그는 "별도 확정가 필드가 항상 존재할 때만" 필요 |
| 시장상태 판별 상태머신 추가 | 07:58 `_reset_realtime_fields`가 이미 명시적 전환점. 시장 상태 평가 로직은 리셋 생명주기와 중복 (P24 위반) |
| 표시용 fallback 로직 추가 (`positions.cur_price == null → sectorStocks에서 가져옴`) | 표시 소스를 "조건부로" sectorStocks로 지정하는 것이 아님. 처음부터 sectorStocks가 표시 소스. 조건 분기 fallback은 P20 위반 |
| DB 스키마 변경 (신규 컬럼·마이그레이션) | 백엔드/DB 변경 없이 프론트 표시 소스 참조만으로 달성. 안전 규칙 2(백업) 미적용 |
| 백엔드 로직 변경 (1단계) | 1단계는 프론트엔드 표시 소스 분리만. 백엔드 계산·리셋·delta 캐시 로직은 변경 없음. 2단계 이름 변경 시에만 백엔드 수정 (별도 태스크) |
| 신규 UI 라벨/배지 추가 ("시세 확인 중" 등) | 상단 헤더 장 상태 칩으로 충분 (사용자 결정). reset→첫 틱 구간은 기존 '-' 유지 |
| `_reset_realtime_fields` 리셋 로직 수정 | 07:58 이중 차단(master+positions)이 표시 정책의 핵심. 변경 시 자연 전환 깨짐 |
| `applyRealData` 틱 갱신 로직 수정 | sectorStocks·positions 양쪽 갱신이 자연 전환의 핵심. 변경 시 표시·계산 소스 동기화 깨짐 |
| 계산 경로 수정 (`computePositionValuation`·`check_sell_conditions`·`_recalc_pnl` 등) | 계산은 이미 cur_price==None → 스킵/0 처리로 안전하게 동작. 변경 불필요 |

---

## 0. 최상위 원칙

> **확정가는 마스터 종목 캐시의 실시간 현재가를 보충하거나 대체하는 데이터가 아니다.** `master_stocks_cache.cur_price`의 생명주기가 시간에 따라 확정가 → None → 실시간가로 자연 전환하므로, 별도의 확정가 필드·플래그·상태머신 없이 기존 구조의 책임을 명확히 하는 것만으로 표시 정책이 달성된다. 확정가는 손익·수익률 및 모든 매매 계산에 사용하지 않는다.

---

## 1. 배경 및 목표

### 1.1 현재 상태 (문제)

보유종목 페이지의 현재가 컬럼이 `positions[i].cur_price`를 표시 소스로 사용하고 있다.
그런데 `positions.cur_price`의 실제 역할은 **화면 표시용 현재가가 아니라 손읜·평가금액·매도조건 계산의 입력값**이다.

**현재 구조의 역할 혼재:**

| 데이터 소스 | 현재 사용처 | 실제 적합 역할 |
|---|---|---|
| `master_stocks_cache.cur_price` | 매수후보 표시 ✓, 업종별 종목 표시 ✓, 보유종목 표시 ✗ (사용 안 함) | **화면 표시 SSOT** |
| `positions.cur_price` | 손익 계산 ✓, 평가금액 계산 ✓, 매도조건 검사 ✓, **보유종목 화면 표시 ✗ (역할 불일치)** | **계산 SSOT** |

보유종목 페이지만 표시 소스로 positions를 사용하고 있어, 매수후보·업종별 종목 페이지와 **표시 소스가 불일치** (P23 위반).

**비실시간 구간(장마감 후 ~ 장 시작 전, 비거래일)의 증상:**
- `positions.cur_price` = None (틱 미수신, `_reset_realtime_fields` 또는 초기 생성 시 None)
- `master_stocks_cache.cur_price` = 확정가 (장마감 파이프라인이 저장, 07:58 리셋 전까지 유지)
- 현재 보유종목 페이지: positions.cur_price=None → '-' 표시
- **사용자가 보고 싶은 것**: 비실시간 구간에는 확정가 표시

### 1.2 핵심 통찰 — 기존 생명주기가 표시 정책을 이미 구현함

`master_stocks_cache.cur_price`의 생명주기를 추적한 결과, **사용자가 원하는 표시 정책이 이미 이 필드의 시간에 따른 자연 전환으로 100% 구현되어 있음**이 확인되었다:

| 구간 | `master_stocks_cache.cur_price` | `positions.cur_price` | 사용자 표시 정책 |
|---|---|---|---|
| 비거래일 종일 | 확정가 (리셋 스킵 — `is_trading_day=False`) | None | 확정가 표시 ✓ |
| 거래일 장마감 파이프라인 후 ~ 07:58 전 | 확정가 (파이프라인 저장, 리셋 전) | None | 확정가 표시 ✓ |
| 거래일 07:58 후 ~ 첫 틱 전 | None (`_reset_realtime_fields` 실행) | None | '-' 유지 ✓ |
| 첫 틱 수신 후 | 실시간 (틱 갱신) | 실시간 (틱 갱신) | 실시간 표시 ✓ |

**이중 차단 메커니즘 (이미 작동 중):**
- 07:58 `_reset_realtime_fields`가 `master_stocks_cache.cur_price`와 `positions.cur_price`를 **둘 다** None화 (`engine_initial_data.py:167-176`)
- 비거래일 리셋 스킵 (`daily_time_scheduler._on_realtime_fields_reset` — `is_trading_day=False` 시 실행 안 함)
- 틱 도착 시 `applyRealData`가 sectorStocks와 positions 양쪽 cur_price를 같은 값으로 갱신 (`hotStore.ts:405-457`)

### 1.3 목표

1. **보유종목 페이지 현재가 표시 소스를 `positions.cur_price`에서 `master_stocks_cache.cur_price`(sectorStocks)로 변경** — 매수후보·업종별 종목과 동일한 표시 소스로 통일 (P23)
2. **계산 경로는 positions.cur_price를 그대로 유지** — 손익·평가금액·매도조건·리스크 계산은 변경 없음
3. **positions.cur_price의 역할을 이름 또는 주석으로 명확화** — "화면 표시용 현재가"가 아닌 "계산용 가격"임이 드러나도록 (P22/P23)
4. **신규 데이터/플래그/상태머신 추가 없이 기존 구조의 책임만 명확히** (P24)

### 1.4 비목표 (다루지 않는 것)

| 항목 | 사유 |
|---|---|
| `confirmed_cur_price` 별도 DB 컬럼 추가 | `master_stocks_cache.cur_price` 생명주기가 확정가→None→실시간가 전환을 이미 구현. 별도 컬럼은 제2의 생명주기를 만들어 P10/P24 위반 |
| `confirmed_price_displayable` 파생 플래그 | 표시 정책이 cur_price 생명주기로 자동 달성되므로 창구 제어 플래그 불필요. 플래그는 "별도 확정가 필드가 항상 존재할 때만" 필요 |
| 시장 상태 판별 상태머신 | 07:58 리셋이 이미 명시적 전환점. 시장 상태 평가 로직은 리셋 생명주기와 중복 |
| `positions.cur_price` 계산 경로 수정 | 계산은 이미 cur_price==None → 스킵/0 처리로 안전하게 동작 (`computePositionValuation` isNull, `check_sell_conditions` None 가드, `_recalc_pnl` None 처리). 변경 불필요 |
| 실시간 전환 로직 신규 작성 | `applyRealData`가 sectorStocks·positions 양쪽을 같은 틱값으로 갱신. 표시 소스를 sectorStocks로 바꿔도 첫 틱 후 자연 전환 |
| 신규 UI 라벨/배지 ("시세 확인 중" 등) | 상단 헤더 장 상태 칩으로 충분 (사용자 결정). reset→첫 틱 구간은 기존 '-' 유지 |
| sector_stocks(매수후보·업종별 종목) 표시 로직 변경 | 이미 sectorStocks 기반 표시 사용 중. 변경 없음 |
| 백엔드 DB 스키마 변경 | DB 컬럼 추가 없음. 안전 규칙 2(백업) 미적용 |

---

## 2. 설계 방향

### 2.1 핵심 설계 결정

**결정 1: 보유종목 페이지 현재가 표시 소스를 `sectorStocks[code].cur_price`로 변경**

- 위치: `frontend/src/pages/sell-position.ts` cur_price 컬럼 render (현재 `computePositionValuation(p)` → `p.cur_price`)
- 변경: `sectorStocks[normalizeStockCode(p.stk_cd)]?.cur_price` 참조
- **이미 종목명 컬럼이 같은 패턴** (`sell-position.ts:31-41`)으로 sectorStocks를 참조 → P23 일관성 강화
- pnl/rate 컬럼은 `computePositionValuation(p)` 유지 — `p.cur_price==null` → `isNull=true` → '-' (계산은 positions 기반 유지)

**결정 2: 계산 경로는 positions.cur_price 유지 (변경 없음)**

- `computePositionValuation` (`profit-math.ts:258-274`): `p.cur_price` 사용. null → isNull=true → pnl/rate/evalAmt=0
- `computeHoldingsSummary` (`profit-math.ts:286-303`): 동일
- 백엔드 `check_sell_conditions` (`trading.py:840-849`): `stock.get("cur_price")` None → 매도 스킵
- 백엔드 `apply_last_price_to_positions_inplace` (`engine_account_rest.py:146-173`): 틱 시 positions cur_price 갱신 + eval/pnl/rate 재계산
- 백엔드 `_recalc_pnl` (`dry_run.py:231-252`): 테스트모드 손익 재계산

**결정 3: positions.cur_price → `calc_cur_price` 이름 변경 (설계에서 확정)**

현재 `positions.cur_price`라는 이름은 "화면 표시용 현재가"로 오해되나, 실제 역할은 계산 입력값. P22(데이터 정합성)·P23(용어 일관성) 관점에서 역할이 드러나는 이름으로 변경.

**실제 역할 범위 (조사 확정):**
- 평가금액 계산 (`eval_amt = cur_price * qty`)
- 손익 계산 (`pnl = eval_amt - buy_amount`)
- 매도조건 계산 (`check_sell_conditions` — 손절/익절/트레일링스탑 판정)
- 리스크 계산 (`check_buy_order_allowed` 등)
- 평가손익률 계산 (`pnl_rate = pnl / buy_amount * 100`)

즉 "평가(evaluation)"가 아닌 "계산(calculation)" 전반에 사용. `eval_price`는 "평가금액 계산용 가격"으로 좁게 읽혀 실제 역할 범위를 축소시킴. `calc_*` 계열이 역할에 더 부합.

**이름 후보 검토 (설계에서 확정):**

| 후보 | 의미 | 장점 | 단점 |
|---|---|---|---|
| ~~`eval_price`~~ | ~~평가용 가격~~ | ~~포괄적 뉘앙스~~ | "평가금액 계산용"으로 좁게 읽혀 손익·매도조건·리스크 계산 역할 축소. 기각 |
| `calc_price` | 계산용 가격 | 가장 직관적·간결. 계산 전용임이 명확 | "어떤 계산"인지 구체성 부족. "가격"이 "현재가"인지 명시 아님 |
| **`calc_cur_price`** | **계산용 현재가** | **"현재가"임은 유지하면서 "계산용"임을 명시. 표시용 master_stocks_cache.cur_price와의 구분 명확. P23 snake_case/camelCase 준수** | **약간 김. 단, 역할 명확성이 우선** |
| `pnl_basis_price` | 손익 기준가 | 손익 계산 기준가임이 명시적 | 과도하게 긺. 매도조건·평가금액·리스크도 포함되므로 손익만은 아님. 기각 |

**확정안: `calc_cur_price`** — "현재가"임은 유지하면서 "계산용"임을 명시. 표시 소스(`master_stocks_cache.cur_price`)와 계산 소스(`positions.calc_cur_price`)의 역할 분리가 이름에서 직관적으로 드러남. 이름은 설계의 일부이므로 본 설계서에서 확정.

**이름 변경 파급 영역 (개념 수준 — 상세 파일/라인은 2단계 태스크에서 추적):**

- 백엔드 positions dict 생성처 3곳 — `trade_history`·`engine_account_rest`(REST 매핑, **W7 영향 — 증권사 응답 `cur_price` → `calc_cur_price` 매핑 레이어 추가**)·`dry_run`(보존 필드)
- 백엔드 계산 소비처 — `apply_last_price_to_positions_inplace`·`_recalc_pnl`·`check_sell_conditions` (간접 소비처 `recalc_broker_totals_from_positions`는 변경 없음)
- 백엔드 리셋·delta 캐시 — `_reset_realtime_fields`·`_POSITION_CMP_KEYS`(delta 비교 키)
- 프론트엔드 — `Position` 타입·`computePositionValuation`·`applyRealData`·`applyRealtimeReset`
- WS payload 필드명 — 프론트/백엔드 계약, 양쪽 동시 변경 필요
- 테스트 코드 다수 — positions 관련 백엔드 테스트 전반

**이름 변경 트레이드오프:**

| 옵션 | 내용 | 파급 | P23 | W7 |
|---|---|---|---|---|
| A (채택) | 전면 이름 변경 `cur_price → calc_cur_price` | 큼 (백엔드+프론트+테스트+WS 계약) | 역할 명확 ✓ | 매핑 레이어 추가 필요 |
| B | 백엔드는 cur_price 유지(W7 정합), 프론트 Position 타입만 calc_cur_price + 매핑 | 중간 | 부분 | 백엔드/프론트 필드명 불일치 |
| C | 이름 유지 + 주석/문서로 역할 명시 | 최소 | 용어 일관성 약함 | 정합 ✓ |

**본 설계서의 입장**: 옵션 A 채택 — 역할 명확화가 핵심이므로 전면 이름 변경. 단, 파급 범위가 크므로 표시 소스 분리(결정 1·2)와 이름 변경(결정 3)을 **독립 태스크로 분리**하여, 표시 소스 분리를 먼저 적용 후 이름 변경을 별도 세션에서 진행하는 것이 P24(단순성)·P25(격리된 실패)에 부합. 이름은 설계에서 확정했으나 구현 시점은 2단계 태스크에서 진행.

### 2.2 역할 분리 원칙 (P10 SSOT)

```
master_stocks_cache (sectorStocks)
  ├── cur_price: 화면 표시 SSOT
  │   ├── 비거래일/07:58 전: 확정가 (파이프라인 저장)
  │   ├── 07:58 후 ~ 첫 틱 전: None (리셋)
  │   └── 첫 틱 후: 실시간 (틱 갱신)
  └── 화면 표시에만 사용 (매수후보·업종별 종목·보유종목 공통)

positions
  ├── calc_cur_price: 계산 SSOT
  │   ├── 초기/리셋 시: None
  │   └── 틱 수신 후: 실시간 (틱 갱신)
  └── 손익·평가금액·매도조건·리스크 계산에만 사용
      (화면 표시 소스로 사용 금지 — 본 설계의 핵심)
```

**확정가가 계산에 유입되지 않는 이유 (P22 자동 달성):**
- 비실시간 구간: positions.cur_price = None → `computePositionValuation` isNull=true → pnl/rate/evalAmt=0
- 확정가는 master_stocks_cache에만 존재하고, 계산 함수들은 positions만 참조
- 별도 차단 로직 불필요 — 데이터 흐름 자체가 차단

### 2.3 폴백이 아닌 이유 (P20)

본 설계는 "cur_price가 None이면 다른 소스에서 가져오는" 값 기반 fallback이 아님:
- 표시 소스를 **항상** sectorStocks로 지정 (조건 분기 없음)
- 계산 소스를 **항상** positions로 지정
- "positions.cur_price가 None이면 sectorStocks에서 가져온다"가 아니라 "표시는 처음부터 sectorStocks가 소스"
- 07:58 후 구간에서 sectorStocks.cur_price=None → '-' (확정가 표시 안 함) — 이것이 fallback이 아니라 **소스의 생명주기에 따른 자연 결과**

---

## 3. 영향 범위

> 파일/라인 단위 변경 내역은 태스크 영역(AGENTS.md 섹션4 "문서 역할 원칙"). 본 섹션은 개념 수준 — "무엇이 어떻게 바뀌는가"만 담당.

### 3.1 1단계: 표시 소스 분리 (핵심 변경)

**프론트엔드 (변경 영역):**

| 영역 | 변경 개념 |
|---|---|
| 보유종목 페이지 현재가 컬럼 render | 표시 소스를 `positions[i].cur_price`에서 `sectorStocks[code].cur_price`로 전환. 종목명 컬럼이 이미 같은 패턴이므로 P23 일관성 강화 |
| `computePositionValuation` 주석 | "현재가" → "계산 입력값(손익·평가·매도조건 계산용). 화면 표시 소스 아님"으로 역할 명시 |
| `Position` 타입 주석 | `cur_price` 필드 역할을 "계산 기준가. 화면 표시 소스 아님"으로 명시 |

**엣지케이스 처리 (정책 결정 — 설계 영역):**
- positions 종목이 sectorStocks에 없는 경우 (상장폐지 등): `sectorStocks[code]` = undefined → cur_price 표시 '-'. **p.cur_price를 폴백으로 참조하지 않음** (P20). 단, 이 케이스는 비정상이므로 console.warn 로깅 고려.
- sectorStocks에 종목은 있으나 cur_price가 undefined인 경우: `!= null` 가드로 '-' 표시.

**백엔드 (변경 없음):**
- positions dict 구조, 계산 로직, 리셋 로직, delta 캐시 비교 — 모두 기존 유지
- WS payload 필드명 — 1단계에서는 변경 없음 (이름 변경은 2단계)

**계산 경로 (변경 없음 — 확인만):**
- `computePositionValuation` / `computeHoldingsSummary`: `p.cur_price` 사용 유지, null → isNull=true → '-' / 0 처리
- pnl/rate 컬럼 render, 요약 행 `renderSummary`, `profit-shared.ts` 계좌 현황 — 모두 기존 동작 유지

### 3.2 2단계: positions.cur_price 이름 변경 (별도 태스크 제안)

- 확정안: `cur_price → calc_cur_price` (Python snake_case / TS camelCase) — 설계에서 확정
- 파급 영역: 섹션 2.1 결정 3 참조
- W7 대응: `merge_positions_from_rest`에서 증권사 응답 `cur_price` → positions `calc_cur_price` 매핑 추가
- **1단계와 독립적으로 진행** — 표시 소스 분리가 먼저 적용·검증된 후 이름 변경 진행 (P25 격리된 실패)

### 3.3 변경하지 않는 것 (명시)

| 항목 | 사유 |
|---|---|
| `_reset_realtime_fields` 리셋 로직 | 07:58 이중 차단(master+positions)이 표시 정책의 핵심. 변경 시 자연 전환 깨짐 |
| `applyRealData` 틱 갱신 로직 | sectorStocks·positions 양쪽 갱신이 자연 전환의 핵심 |
| 장마감 파이프라인 | master_stocks_cache.cur_price 저장 로직은 그대로. 별도 컬럼 추가 없음 |
| `master_stocks_table` 스키마 | DB 변경 없음 |
| 매수후보·업종별 종목 표시 로직 | 이미 sectorStocks 기반. 변경 없음 |

---

## 4. 아키텍처 원칙 부합표

| 원칙 | 부합 방식 |
|---|---|
| **P10 SSOT** | 표시 소스 = master_stocks_cache(단일). 계산 소스 = positions(단일). 두 역할이 이미 분리됨. confirmed_cur_price 같은 제2의 확정가 소스 불필요 — 확정가는 master_stocks_cache.cur_price의 비실시간 구간 값이므로 별도 소스 아님 |
| **P20 폴백 금지** | "positions.cur_price null → sectorStocks에서 가져옴"이 아님. 표시 소스를 처음부터 sectorStocks로 지정. 07:58 후 sectorStocks.cur_price=None → '-'는 소스 생명주기의 자연 결과이지 폴백 아님 |
| **P21 사용자 투명성** | 비실시간 구간에 확정가 표시(사용자가 보고 싶은 것). 07:58 후 첫 틱 전에는 '-' 유지(과거 확정가를 현재 시세처럼 표시하지 않음). 헤더 장 상태 칩으로 충분 — 개별 종목 라벨 불필요 |
| **P22 데이터 정합성** | 확정가가 별도 필드로 존재하지 않으므로 계산에 유입될 경로 자체가 없음. positions.cur_price==null → 계산 스킵. 별도 차단 로직 불필요. avg_price 폴백 위장(선행 작업 e0055c6)과 동일 종류 결함 방지 |
| **P23 일관성** | 보유종목 cur_price 표시를 매수후보·업종별 종목과 동일하게 sectorStocks 기반으로 통일. 현재 보유종목만 positions 기반 표시를 쓰는 비일관성 해소. positions.cur_price 이름 변경 시 역할 명시로 용어 일관성 추가 강화 |
| **P24 단순성** | 신규 DB 컬럼 0, 신규 플래그 0, 신규 분기 로직 0, 신규 상태머신 0, 백엔드 변경 0(1단계). 프론트 표시 소스 참조 1곳 + 주석 문서화만. 기존 구조의 책임을 명확히 하는 것이 핵심 |
| **P25 격리된 실패** | 표시 소스 분리(1단계)와 이름 변경(2단계)을 독립 태스크로 분리. 1단계 실패가 이름 변경에 전파되지 않음. sectorStocks 참조 실패 시 해당 종목만 '-' 표시, 전체 화면 중단 없음 |
| **W7 (시뮬레이터/증권사 응답 동일 구조)** | 1단계는 백엔드 변경 없으므로 W7 영향 없음. 2단계 이름 변경 시 `merge_positions_from_rest` 매핑 레이어에서 증권사 `cur_price` → `calc_cur_price` 변환으로 W7 유지 |

---

## 5. 완료 기준 (사용자 관점 수용 조건)

> 검증의 최종 판정 기준 (AGENTS.md 섹션4 "문서 역할 원칙" — 검증=설계 완료기준 따른다). 태스크 완료 조건은 여기서 파생.

### 5.1 1단계 완료 기준 (표시 소스 분리)

- [ ] 비거래일/장마감 후 기동 시 보유종목 현재가에 확정가 표시 (positions.cur_price=None이어도 sectorStocks에 확정가 있음)
- [ ] 거래일 07:58 리셋 후 ~ 첫 틱 전 구간에 보유종목 현재가 '-' 표시 (과거 확정가를 현재 시세처럼 표시하지 않음)
- [ ] 첫 틱 수신 후 보유종목 현재가가 실시간 값으로 전환
- [ ] 비실시간 구간 평가손익/수익률 '-' 표시 (확정가가 계산에 유입되지 않음 — P22 핵심 검증)
- [ ] 비실시간 구간 요약 행 '-' 표시 (hasNullPrice=true)
- [ ] 매수후보·업종별 종목 페이지와 보유종목 페이지의 현재가 표시 소스 일치 (P23)
- [ ] positions 종목이 sectorStocks에 없는 비정상 케이스: '-' 표시 (p.cur_price 폴백 참조 없음 — P20)

### 5.2 2단계 완료 기준 (이름 변경 — 별도 태스크)

- [ ] positions 필드명 `cur_price` → `calc_cur_price` 전면 반영 (백엔드·프론트·WS payload·테스트)
- [ ] 증권사 응답 `cur_price` → positions `calc_cur_price` 매핑 레이어 정상 동작 (W7 유지)
- [ ] 기존 계산·리셋·delta 캐시 동작 회귀 없음 (이름만 변경, 로직 변경 없음)

---

## 6. 위험도 산정

> "검증·관찰 계층 게이트" 입력 (AGENTS.md 섹션4). 비개발자용 3줄 요약 + 승인 판단 근거.

| 단계 | 위험도 | 근거 |
|---|---|---|
| 1단계 (표시 소스 분리) | **낮음** | 프론트엔드 1~3개 파일 변경, 백엔드 변경 0, DB 변경 0, 신규 로직/플래그/상태머신 0. 표시 소스 참조 1곳 + 주석 문서화만. 계산 경로 미변경으로 매매 로직 영향 없음 |
| 2단계 (이름 변경) | **중간** | 백엔드+프론트+WS 계약+테스트 다수 파일 파급. W7 매핑 레이어 신규 도입(증권사 응답 필드명과 positions 필드명 분리). 단, 로직 변경 없이 이름 치환만이므로 매매 판단 로직 영향 없음 |

**비개발자용 3줄 요약:**
1. 1단계는 화면에 보이는 현재가 숫자의 출처만 바꾸는 것 — 계산·주문 로직은 건드리지 않아 위험 낮음
2. 2단계는 프로그램 내부 변수명을 역할에 맞게 바꾸는 것 — 증권사 연동 부분도 함께 바꿔야 해서 파급 범위가 넓음
3. 두 단계를 나누어 진행하므로 1단계 문제가 2단계로 번지지 않음

---

## 7. 검증 계획 (게이트 수준)

> 구체적 검증 명령(`npm run typecheck` 등)은 태스크 파일의 "작업 순서" 단계별 검증 방법에 이관 (AGENTS.md 섹션4 — 검증 명령은 태스크 영역). 본 섹션은 적용 게이트 수준만 명시.

### 7.1 1단계 검증 게이트

- **자동 검증 게이트**: 프론트엔드 타입체크 · 프론트엔드 테스트 회귀 · 프론트엔드 빌드
- **수동 검증 게이트 (모의투자 — 사용자 확인)**: 섹션 5.1 완료 기준 7개 시나리오. 핵심은 P22 — 비실시간 구간에 확정가가 표시되는 동안 평가손익/수익률이 0 또는 확정가 기준 계산값이 아닌 '-'로 표시되는지 확인. 확정가가 계산에 유입되면 avg_price 폴백 위장(선행 작업 e0055c6)과 동일 종류 결함.

### 7.2 2단계 검증 게이트

- **백엔드 게이트**: positions 관련 pytest 전체 · RuntimeWarning(await 누락) 검증
- **프론트엔드 게이트**: 타입체크 · 테스트 · 빌드
- **계약 게이트**: WS payload 필드명 변경 시 프론트/백엔드 계약 일치 확인

---

## 8. 사전 롤백 계획 (2단계 조건부 — 위험도 중간)

> AGENTS.md 섹션4 — 위험도 '높음'/'중간' 시 사전 롤백 계획 필수. 1단계는 위험도 낮음으로 미적용. 2단계 진행 전 상세 롤백 절차는 2단계 태스크 파일에 이관.

**2단계 사전 롤백 원칙 (개념 수준):**
- 이름 변경은 단일 커밋으로 일괄 적용 — 부분 적용 시 프론트/백엔드 필드명 불일치로 WS 계약 붕괴
- 검증 게이트(특히 WS 계약 일치) 실패 시 즉시 롤백 — 부분 수정 후 재시도 금지
- W7 매핑 레이어 신규 도입 부분은 별도 검증 — 매핑 누락 시 증권사 응답 `cur_price`가 positions에 누락됨
- 롤백 시 사용자 승인 필수 (AGENTS.md 규칙 0-3 — 사용자 승인 없는 롤백 절대 금지)

---

## 9. 다단계 작업 워크플로우 (AGENTS.md 섹션4)

| 세션 | 산출물 | 상태 |
|---|---|---|
| 1세션 (본 세션) | 설계 파일 (본 문서) | 완료 |
| 2세션 | 태스크 파일 `docs/plan_position_display_source_separation.md` | 대기 |
| 3세션 | 1단계 구현 (표시 소스 분리) | 대기 |
| 4세션 | 1단계 독립 검증 + 모의 관찰 | 대기 |
| 별세션 | 2단계 태스크 파일 (이름 변경) | 대기 |
| 별세션 | 2단계 구현 (이름 변경) | 대기 |

**1단계·2단계 분리 사유:** 표시 소스 분리는 프론트엔드 1~3개 파일 변경으로 파급 작음. 이름 변경은 백엔드+프론트+WS 계약+테스트로 파급 큼. P25(격리된 실패)·P24(단순성) 관점에서 독립 진행.

---

## 10. 참조 경로

### 10.1 기존 구조 참조 (역할 분리의 근거)

- `master_stocks_cache` 표시 소스 사용처 (이미 sectorStocks 기반):
  - `backend/app/services/sector_data_provider.py:68-86` — `get_sector_stocks()` master_stocks_cache 복사
  - `backend/app/services/sector_data_provider.py:158-168` — `_build_target_entry()` cache_entry.get("cur_price")
  - `frontend/src/pages/sector-stock-rows.ts:26-28` — `item.stock.cur_price` 표시
  - `frontend/src/pages/buy-target-columns.ts:37-39` — `t.cur_price` 표시
- `positions.cur_price` 계산 소스 사용처 (변경 없음):
  - `backend/app/services/trading.py:840-849` — `check_sell_conditions` None 가드
  - `backend/app/services/engine_account_rest.py:146-173` — `apply_last_price_to_positions_inplace`
  - `backend/app/services/dry_run.py:231-252` — `_recalc_pnl`
  - `backend/app/services/engine_account_rest.py:78-97` — `recalc_broker_totals_from_positions`
  - `frontend/src/pages/profit-math.ts:258-274` — `computePositionValuation`
  - `frontend/src/pages/profit-math.ts:286-303` — `computeHoldingsSummary`
- 생명주기 전환 메커니즘 (변경 없음):
  - `backend/app/services/engine_initial_data.py:167-176` — `_reset_realtime_fields` 이중 차단
  - `frontend/src/stores/hotStore.ts:405-457` — `applyRealData` 양쪽 갱신
  - `frontend/src/stores/hotStore.ts:543-589` — `applyRealtimeReset` 양쪽 None화
  - `backend/app/services/daily_time_scheduler.py:860-886` — 비거래일 리셋 스킵
- 보유종목 페이지 현재 표시 소스 (현재 구조 — 1단계에서 표시 소스 전환 대상):
  - `frontend/src/pages/sell-position.ts:42-49` — cur_price 컬럼 render (현재 positions 기반)
  - `frontend/src/pages/sell-position.ts:31-41` — 종목명 컬럼 (이미 sectorStocks 기반 — 동일 패턴 참조)
- delta 캐시 비교 (이름 변경 시 영향):
  - `backend/app/services/engine_account_notify.py:163` — `_POSITION_CMP_KEYS`
  - `backend/app/services/engine_account_notify.py:180-193` — `_compute_position_delta`

### 10.2 선행 작업 참조

- `docs/architecture_cur_price_fallback_removal_design.md` — avg_price 폴백 제거 (커밋 `e0055c6`). positions.cur_price가 None을 유지하는 구조의 기반. 본 설계는 그 위에 표시 소스 분리를 얹음.

### 10.3 아키텍처 원칙 참조

- `AGENTS.md` 섹션2 — P10(SSOT)·P20(폴백 금지)·P21(사용자 투명성)·P22(데이터 정합성)·P23(일관성)·P24(단순성)·P25(격리된 실패)
- `AGENTS.md` 실전 모드 vs 테스트 모드 테이블 — "돈 관련 수치는 증권사가 SSOT". 본 설계는 계산 경로 미변경이므로 실전/테스트 모드 모두 동일 동작
- `ARCHITECTURE.md` W7 — 시뮬레이터/증권사 응답 동일 구조. 1단계 백엔드 변경 없음, 2단계 이름 변경 시 매핑 레이어로 유지

---

## 11. 사용자 결정 항목

| 항목 | 사용자 결정 | 본 설계 반영 |
|---|---|---|
| confirmed_cur_price 별도 컬럼 | 불필요 (master_stocks_cache.cur_price 생명주기로 달성) | 섹션 1.4 비목표 |
| confirmed_price_displayable 플래그 | 불필요 (창구 정책이 생명주기로 자동 달성) | 섹션 1.4 비목표 |
| 시장상태 판별 상태머신 | 불필요 | 섹션 1.4 비목표 |
| 신규 UI 라벨/배지 | 추가 안 함 (헤더 장 상태 칩으로 충분) | 섹션 1.4 비목표 |
| reset→첫 틱 구간 표시 | 기존 '-' 유지 ("시세 확인 중" 등 신규 텍스트 추가 안 함) | 섹션 3.1 |
| positions.cur_price 이름 변경 | `calc_cur_price` 확정 (설계에서 결정) | 섹션 2.1 결정 3 — 확정안 calc_cur_price, 별도 태스크 분리 |
| 표시 소스 분리와 이름 변경 분리 | (설계 제안 — 승인 대기) 1단계·2단계 독립 태스크 | 섹션 3.2 · 섹션 9 |
