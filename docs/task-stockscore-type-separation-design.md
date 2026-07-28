# 태스크: StockScore / SectorStock 타입 분리 설계

> **다단계 워크플로우 세션 1 (설계)** 산출물.
> 세션 2(태스크 분할) → 세션 3(구현) 순차 진행.

## 1. 배경

프론트엔드 `SectorStock` 타입이 매수후보(`buyTargets`)와 업종분류(`sectorStocks`) 양쪽 컨텍스트에서 공유되어 의미 불일치 발생.
- `buyTargets`: 백엔드 `StockScore` + `BuyTarget` 래핑 + 캐시 병합 (19개 필드) — `StockScore`와 동일 개념
- `sectorStocks`: 백엔드 `get_all_sector_stocks()` (5개 필드) — 단순 종목 식별 정보, `StockScore` 아님

옵션 B(타입 분리)로 해결: `buyTargets`는 `StockScore`, `sectorStocks`는 `SectorStock`(축소) 유지.

## 2. 타입 설계

### 2.1 `StockScore` (신규 — 매수후보 전용)

백엔드 `_build_target_entry()` 반환 필드와 1:1 매핑.

```typescript
export interface StockScore {
  // ── 식별 필드 ──
  code: string
  name: string
  sector?: string
  market_type?: string
  nxt_enable?: boolean
  // ── 실시간 파생 필드 (sectorStocks SSOT에서 파생 — null 허용) ──
  cur_price: number | null
  change_rate: number
  change?: number
  strength?: number
  trade_amount?: number
  // ── 정적 스코어 필드 (백엔드 StockScore + BuyTarget) ──
  rank?: number
  guard_pass?: boolean
  reason?: string
  boost_score?: number
  // ── 매수후보 전용 파생 필드 (캐시 병합) ──
  order_ratio?: [number, number] | null
  high_5d?: number
  program_net_buy?: number | null
  news_boost?: number
  news_boost_title?: string
}
```

> **avg_amt_5d 제거 (T1 설계 수정)**: `avg_amt_5d`는 1차 필터링(거래대금 적은 종목 걸러내기)과
> 우측 패널 표시용이며 매수후보 판단에 사용되지 않으므로 `StockScore`에서 제거.
> 주인은 `SectorStock` (P10 SSOT). 백엔드 `_build_target_entry()`에서도 제거,
> `_BUY_TARGET_CMP_KEYS`에서도 제거 (P23 일관성).

### 2.2 `SectorStock` (축소 — 업종분류 전용)

백엔드 `get_all_sector_stocks()` 반환 필드 + 실시간 파생 필드 + 5거래일 평균 거래대금.

```typescript
export interface SectorStock {
  // ── 식별 필드 (백엔드 get_all_sector_stocks — 5개) ──
  code: string
  name: string
  sector?: string
  market_type?: string
  nxt_enable?: boolean
  // ── 실시간 파생 필드 (sectorStocks SSOT — applyRealData가 갱신) ──
  cur_price: number | null
  change_rate: number
  change?: number
  strength?: number
  trade_amount?: number
  // ── 5거래일 평균 거래대금 (우측 패널 표시용 — T1 설계 수정) ──
  avg_amt_5d?: number
}
```

> **avg_amt_5d 추가 (T1 설계 수정)**: 우측 패널(`sector-stock-rows.ts`)의 5거래일 평균 거래대금
> 컬럼 표시를 위해 `SectorStock`에 포함. 백엔드 `get_all_sector_stocks()`에서
> `master_stocks_cache["avg_5d_trade_amount"]` (백만원 단위)를 억 단위로 변환하여 전송.

### 2.3 필드 배분 요약

| 필드 | StockScore | SectorStock | 비고 |
|------|:---:|:---:|------|
| code, name, sector, market_type, nxt_enable | ✅ | ✅ | 공통 식별 |
| cur_price, change, change_rate, strength, trade_amount | ✅ | ✅ | 공통 실시간 (sectorStocks SSOT에서 파생) |
| avg_amt_5d | ❌ | ✅ | 업종분류 전용 (1차 필터링·우측 패널 표시) — T1 설계 수정 |
| rank, guard_pass, reason, boost_score | ✅ | ❌ | 매수후보 전용 (백엔드 BuyTarget/StockScore) |
| order_ratio, high_5d, program_net_buy | ✅ | ❌ | 매수후보 전용 (캐시 병합) |
| news_boost, news_boost_title | ✅ | ❌ | 매수후보 전용 (news-hit 이벤트) |

### 2.4 `Position.sectorStock` 필드

`Position.sectorStock?: SectorStock` 유지 — 보유 종목의 업종 종목 정보이므로 `SectorStock`이 맞음.

## 3. hotStore 동기화 로직 매핑 설계

### 3.1 상태 타입 변경

```typescript
export interface HotState {
  sectorStocks: Record<string, SectorStock>   // 유지
  buyTargets: StockScore[]                     // SectorStock[] → StockScore[]
  // ...
}
```

### 3.2 동기화 함수 시그니처 변경

| 함수 | 현재 | 변경 후 |
|------|------|---------|
| `stocksToMap` | `(stocks: SectorStock[]) => Record<string, SectorStock>` | 유지 (sectorStocks 전용) |
| `rebuildBuyTargetIndex` | `(targets: SectorStock[])` | `(targets: StockScore[])` |
| `applyRealData` | buyTargets 요소 `SectorStock` | buyTargets 요소 `StockScore` — 필드 동일하므로 로직 변경 없음 |
| `applyOrderbookUpdate` | `t.order_ratio` 갱신 | 동일 — `StockScore.order_ratio` 존재 |
| `applyProgramUpdate` | `t.program_net_buy` 갱신 | 동일 — `StockScore.program_net_buy` 존재 |
| `applyRealtimeReset` | `nullifyFields(stock, ...)` for sectorStocks + `rebindBuyTargetsRealtime` | sectorStocks는 `SectorStock`, buyTargets는 `StockScore` — `rebindBuyTargetsRealtime` 시그니처 변경 |
| `applyBuyTargetsUpdate` | `(data: { buy_targets: SectorStock[] })` | `(data: { buy_targets: StockScore[] })` — 내부 로직 동일 |
| `applyNewsHit` | `buyTargets.findIndex((t: SectorStock) => ...)` | `(t: StockScore)` |
| `applyBuyTargetsDelta` | `added?: SectorStock[]` 등 | `added?: StockScore[]` 등 |
| `rebindBuyTargetsRealtime` | `(buyTargets: SectorStock[], sectorStocks: Record<string, SectorStock>)` | `(buyTargets: StockScore[], sectorStocks: Record<string, SectorStock>)` — 필드 동일하므로 로직 변경 없음 |
| `applySectorStocksRefresh` | `(data: { stocks: SectorStock[] })` | 유지 (sectorStocks 전용) |
| `applySectorStocksDelta` | `(data: { added: SectorStock[]; removed: string[] })` | 유지 |
| `applyInitialSnapshotHot` | `buy_targets as SectorStock[]` | `buy_targets as StockScore[]` |

### 3.3 핵심: 동기화 로직은 필드 동일하므로 변경 최소

`rebindBuyTargetsRealtime`과 `applyRealData`의 buyTargets 동기화는 `cur_price/change/change_rate/strength/trade_amount` 5개 필드만 다루며, 이 필드들은 `StockScore`와 `SectorStock` 양쪽에 모두 존재. 따라서 **시그니처 타입 변경만으로 로직 수정 불필요**.

## 4. 공통 유틸 제네릭 설계

### 4.1 `filterStocksBySearch` (utils/stock-search.ts)

현재: `(stocks: Iterable<SectorStock>, query: string)`
- `buy-target.ts` 호출: `state.buyTargets` (→ `StockScore[]`)
- `sector-stock.ts` 호출: `Object.values(state.sectorStocks)` (→ `SectorStock[]`)

제네릭 변경:
```typescript
export function filterStocksBySearch<T extends { code: string; name?: string }>(
  stocks: Iterable<T>,
  query: string,
): Set<string> | null
```

- `s.code`와 `s.name`만 접근하므로 구조적 타입으로 제약.
- 호출처에서 타입 인수 자동 추론되므로 명시 불필요.

## 5. 파일별 변경 명세

### 5.1 타입 정의

| 파일 | 변경 |
|------|------|
| `types/index.ts` | `StockScore` 인터페이스 추가 (매수후보 전용 — `avg_amt_5d` 제외). `SectorStock` 축소 (5개 식별 + 5개 실시간 파생 + `avg_amt_5d`). `Position.sectorStock?: SectorStock` 유지. 기존 주석 업데이트 |

### 5.2 상태 저장소

| 파일 | 변경 |
|------|------|
| `stores/hotStore.ts` | import `StockScore` 추가. `HotState.buyTargets: StockScore[]`. `rebuildBuyTargetIndex(targets: StockScore[])`. `applyBuyTargetsUpdate/applyBuyTargetsDelta/applyNewsHit` 시그니처 `SectorStock`→`StockScore`. `rebindBuyTargetsRealtime(buyTargets: StockScore[], ...)`. `applyInitialSnapshotHot` 캐스팅 `as StockScore[]`. `applyRealData`/`applyOrderbookUpdate`/`applyProgramUpdate` 내부 `t` 타입은 TS 추론 (명시적 타입 변경 최소). 주석 업데이트 |

### 5.3 WS 바인딩

| 파일 | 변경 |
|------|------|
| `binding.ts` | import `StockScore` 추가. `buy-targets-update`: `as { buy_targets: StockScore[] }`. `buy-targets-delta`: `as { added: StockScore[]; ...; changed: StockScore[] }`. `sector-stocks-refresh`/`sector-stocks-delta`: `SectorStock` 유지 |

### 5.4 매수후보 페이지

| 파일 | 변경 |
|------|------|
| `pages/buy-target.ts` | import `StockScore` (기존 `SectorStock` 제거). `DataTable<StockScore>`. `compareBuyTargets(a: StockScore, b: StockScore)`. `_rsBuyTargets: HotState['buyTargets']` (자동 추론). 모든 `SectorStock` 참조 `StockScore`로 |
| `pages/buy-target-columns.ts` | import `StockScore`. `ColumnDef<StockScore>[]`. 모든 제네릭 `<SectorStock>` → `<StockScore>` |

### 5.5 업종분류 페이지 (변경 최소)

| 파일 | 변경 |
|------|------|
| `pages/sector-stock.ts` | `SectorStock` 유지 — 변경 없음 |
| `pages/sector-stock-rows.ts` | `SectorStock` 유지 — 변경 없음 (`avg_amt_5d` 접근은 `SectorStock`에 포함되어 유효) |

### 5.6 수익현황 페이지 (변경 최소)

| 파일 | 변경 |
|------|------|
| `pages/profit-shared.ts` | `sectorStocks: Record<string, SectorStock>` 유지 — 변경 없음 (`computePositionValuation`/`computeHoldingsSummary`는 sectorStocks 컨텍스트) |
| `pages/profit-overview-sector-pnl.ts` | `SectorStockPnl` (별도 타입) 유지 — 변경 없음 |
| `pages/profit-overview-mount.ts` | `sectorStocks` 변수명 유지 — 변경 없음 |
| `pages/profit-detail-mount.ts` | `sectorStocks`/`dirtySectorStocks` 변수명 유지 — 변경 없음 |
| `pages/profit-detail.ts` | 변경 없음 |

### 5.7 보유 종목 페이지 (변경 없음)

| 파일 | 변경 |
|------|------|
| `pages/sell-position.ts` | `HotState['sectorStocks']` 참조 유지 — 변경 없음 |

### 5.8 종목분류 페이지 (변경 없음)

| 파일 | 변경 |
|------|------|
| `pages/stock-classification.ts` | `SectorStock` 타입 import 없음, 변수명만 `cachedSectorStocksRef` — 변경 없음 |
| `pages/stock-classification-staging.ts` | 변경 없음 |

### 5.9 유틸

| 파일 | 변경 |
|------|------|
| `utils/stock-search.ts` | 제네릭 `<T extends { code: string; name?: string }>` 적용. `SectorStock` import 제거 |

### 5.10 테스트

| 파일 | 변경 |
|------|------|
| `tests/stores/hotStore.test.ts` | `buyTargets` 관련 테스트 데이터를 `StockScore` 타입에 맞게 (`avg_amt_5d` 제거). `sectorStocks` 관련은 `SectorStock` 유지 (`avg_amt_5d` 포함). 각 테스트가 어느 컨텍스트인지 판별 (40곳 중 buyTargets 관련만 변경) |
| `tests/pages/profit-shared.test.ts` | `Position.sectorStock`은 `SectorStock` 유지이나, `sectorStocks` Record 생성 시 `SectorStock` 필드만 사용하는지 확인. 일부 테스트가 `buyTargets` 필드(`rank`, `guard_pass` 등)를 포함하면 `StockScore`로 분리 (20곳 판별) |

### 5.11 백엔드 (T1 설계 수정 — avg_amt_5d 이동)

> `avg_amt_5d`를 매수후보(StockScore)에서 업종분류(SectorStock)로 이동하기 위한 백엔드 변경.
> P10(SSOT — avg_amt_5d 주인은 SectorStock) + P23(일관성 — 백엔드·프론트 비교 키 일치) + P24(단순성 — 불필요 필드 제거).

| 파일 | 변경 |
|------|------|
| `backend/app/services/sector_data_provider.py` | (1) `_build_target_entry()`: `"avg_amt_5d": s.avg_amt_5d` 라인 제거 (매수후보에서 불필요). (2) `get_all_sector_stocks()`: 각 종목 dict에 `"avg_amt_5d"` 추가 — `master_stocks_cache[cd]["avg_5d_trade_amount"]` (백만원 단위)를 억 단위로 변환 (`sector_calculator.py`의 `avg5d_eok = avg5d_million // 100` 패턴과 일치). 0 = 원천 부재/미다운로드 표시 규칙 유지 |
| `backend/app/services/engine_account_notify.py` | `_BUY_TARGET_CMP_KEYS` 튜플에서 `"avg_amt_5d"` 제거. 주석(530줄 프론트와 대응) 업데이트 |
| `backend/tests/test_engine_account_notify.py` | (1) `_make_target`의 `avg_amt_5d` 제거 (매수후보 테스트 데이터에서 불필요). (2) `test_cmp_keys_excludes_realtime_and_news_boost`의 `avg_amt_5d` 포함 검증 제거. (3) `test_initial_send_buy_targets_update_*` 등 added/changed 검증에서 `avg_amt_5d` 제거. (4) `test_delta_changed_avg_amt_5d_triggers_change` 테스트 제거 (더 이상 changed 판정 키가 아님) |
| `backend/tests/test_web_routes.py` | `sector-stocks` 응답 fixture에 `avg_amt_5d` 추가 (393-395줄 — 이미 포함되어 있으므로 유지 확인) |
| `backend/tests/test_engine_initial_data.py` | `initial-snapshot`의 `sector_stocks` 필드 목록(118줄)에 `avg_amt_5d` 포함 확인 |

## 6. 구현 순서 (세션 3용)

의존성 순서대로 진행하여 단계별 typecheck 검증:

1. **타입 정의**: `types/index.ts` — `StockScore` 추가 (`avg_amt_5d` 제외), `SectorStock` 축소 (`avg_amt_5d` 포함)
2. **유틸**: `utils/stock-search.ts` — 제네릭화
3. **상태 저장소**: `stores/hotStore.ts` — 시그니처 변경 + `applyBuyTargetsUpdate` 비교 키 `avg_amt_5d` 제거
4. **WS 바인딩**: `binding.ts` — 캐스팅 변경
5. **매수후보 페이지**: `buy-target.ts`, `buy-target-columns.ts` — 타입 변경
6. **테스트**: `hotStore.test.ts`, `profit-shared.test.ts` — 타입 맞춤
7. **백엔드**: `sector_data_provider.py`, `engine_account_notify.py`, 백엔드 테스트 — `avg_amt_5d` 이동 (T1 설계 수정)
8. **검증**: `npm run typecheck` + `npm run build` + `npm run test` + `.venv/bin/python -m pytest backend/tests -q`

## 7. 위험 요소 및 대응

| 위험 | 대응 |
|------|------|
| `StockScore`와 `SectorStock` 필드 중복 (cur_price 등)으로 인한 동기화 로직 오류 | 5개 실시간 필드는 양쪽 동일하므로 `rebindBuyTargetsRealtime` 로직 변경 불필요 — 시그니처만 변경 |
| 테스트 데이터가 두 타입 필드를 혼용 | 테스트 데이터를 컨텍스트에 맞게 분리 — `sectorStocks` 테스트는 5개 식별+5개 실시간+`avg_amt_5d`, `buyTargets` 테스트는 `avg_amt_5d` 제외 전체 필드 |
| `filterStocksBySearch` 제네릭화 시 호출처 타입 추론 실패 | TS 구조적 타이핑으로 자동 추론되므로 문제 없음. 실패 시 명시적 타입 인수 |
| `applyInitialSnapshotHot`의 `buy_targets as SectorStock[]` 캐스팅 | `as StockScore[]`로 변경 — 런타임 동작 동일 |
| `avg_amt_5d` 이동으로 인한 백엔드·프론트 비교 키 불일치 (T1 설계 수정) | 백엔드 `_BUY_TARGET_CMP_KEYS`와 프론트 `applyBuyTargetsUpdate` 비교 키에서 `avg_amt_5d` 동시 제거 (P23 일관성) |
| `get_all_sector_stocks()`에 `avg_amt_5d` 추가 시 단위 변환 오류 | `master_stocks_cache["avg_5d_trade_amount"]` (백만원) → 억 단위 변환은 `sector_calculator.py`의 기존 패턴(`avg5d_eok = avg5d_million // 100`)과 일치시킴 |

## 8. 검증 체크포인트

- [ ] `npm run typecheck` 통과 — 타입 분리로 인한 오류 없음
- [ ] `npm run build` 통과
- [ ] `npm run test` 통과 — 294테스트 전체 성공
- [ ] P10 (SSOT): `sectorStocks`가 실시간 SSOT, `buyTargets`가 파생 캐시 — 분리 후에도 동기화 경로 유지
- [ ] P22 (데이터 정합성): `rebindBuyTargetsRealtime` 동작 동일
- [ ] P23 (용어 통일): `StockScore`는 매수후보 컨텍스트, `SectorStock`은 업종분류 컨텍스트 — 의미 일치
- [ ] P24 (단순성): 불필요한 추상화 없음, 제네릭 1곳만
