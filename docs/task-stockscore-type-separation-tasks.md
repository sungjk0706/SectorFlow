# 태스크 분할: StockScore / SectorStock 타입 분리

> **다단계 워크플로우 세션 2 (태스크 분할)** 산출물.
> 세션 1 산출물: `docs/task-stockscore-type-separation-design.md`
> 세션 3 (구현): 본 파일의 태스크 T1~T7을 순차 실행.

## 0. 분할 원칙

- **세션당 1단계 원칙 (AGENTS.md 규칙 0-1)**: 각 태스크는 1단위 작업으로 독립 실행 가능해야 함.
- **의존성 순서 준수**: 설계 문서 섹션 6의 구현 순서를 그대로 태스크 번호에 반영. T(n)은 T(1..n-1) 완료 후 실행.
- **단계별 typecheck 검증**: 각 태스크 종료 후 `npm run typecheck`를 실행하여 회귀 없음을 확인. 실패 시 다음 태스크로 넘어가지 않음.
- **승인 게이트**: AGENTS.md 규칙 0에 따라 각 태스크는 사용자 명시적 승인 후 실행. 태스크 완료 후 다음 태스크 승인 대기.
- **검증 게이트 (T7)**: 모든 태스크 완료 후 typecheck + build + test 3종 전체 통과로 최종 검증.

## 1. 태스크 목록 요약

| 태스크 | 대상 | 의존성 | 검증 |
|--------|------|--------|------|
| T1 | `types/index.ts` — `StockScore` 추가, `SectorStock` 축소 (`avg_amt_5d` 이동) | 없음 | typecheck |
| T2 | `utils/stock-search.ts` — `filterStocksBySearch` 제네릭화 | T1 | typecheck |
| T3 | `stores/hotStore.ts` — 동기화 함수 시그니처 변경 + `applyBuyTargetsUpdate` 비교 키 `avg_amt_5d` 제거 | T1, T2 | typecheck |
| T4 | `binding.ts` — WS 캐스팅 변경 | T3 | typecheck |
| T5 | `pages/buy-target.ts`, `pages/buy-target-columns.ts` — 타입 변경 | T3 | typecheck |
| T6 | `tests/stores/hotStore.test.ts`, `tests/pages/profit-shared.test.ts` — 테스트 데이터 분리 | T1~T5 | typecheck + test |
| T7 | 백엔드 — `sector_data_provider.py`, `engine_account_notify.py`, 백엔드 테스트 (`avg_amt_5d` 이동) | T1~T6 | pytest |
| T8 | 최종 검증 — typecheck + build + test + pytest 4종 | T1~T7 | 4종 전체 통과 |

> 설계 문서 섹션 5.5~5.8 (sector-stock, profit-*, sell-position, stock-classification)은 "변경 없음"이므로 태스크에서 제외.
> 단, `sector-stock-rows.ts`의 `avg_amt_5d` 접근은 T1 설계 수정으로 `SectorStock`에 포함되어 유효.

---

## T1. 타입 정의 분리

### 대상
- `frontend/src/types/index.ts`

### 변경 명세 (설계 5.1, T1 설계 수정)
1. `StockScore` 인터페이스 신규 추가 — 설계 2.1의 18개 필드 적용 (**`avg_amt_5d` 제외**).
   - 식별 5개 + 실시간 파생 5개 + 정적 스코어 4개 (rank, guard_pass, reason, boost_score) + 매수후보 전용 파생 5개 (order_ratio, high_5d, program_net_buy, news_boost, news_boost_title).
2. `SectorStock` 인터페이스 축소 — 설계 2.2의 11개 필드(식별 5 + 실시간 파생 5 + `avg_amt_5d`)만 남기고, 매수후보 전용 필드(`rank`, `guard_pass`, `reason`, `boost_score`, `order_ratio`, `high_5d`, `program_net_buy`, `news_boost`, `news_boost_title`) 제거. **`avg_amt_5d`는 `SectorStock`에 유지** (우측 패널 표시용).
3. `Position.sectorStock?: SectorStock` 유지 (설계 2.4).
4. 기존 주석 중 `SectorStock`이 매수후보·업종분류 양쪽에서 공유된다는 설명이 있으면 "매수후보는 `StockScore`, 업종분류는 `SectorStock`으로 분리"로 업데이트.

### 주의 사항
- `SectorStock` 필드 축소로 인해 기존 `SectorStock`을 매수후보 컨텍스트로 사용하던 코드에서 타입 오류 발생 예상 — 이 오류들은 T3, T4, T5에서 해결. T1 완료 시점의 typecheck는 실패할 수 있으나, **T1 자체는 타입 정의 추가·축소만 완료하면 종료**. 실패 오류 목록을 T3~T5 작업 지시로 활용.
- 단, T1 완료 후 typecheck를 실행하여 "오류가 `SectorStock` 필드 축소로 인한 것"인지 확인 — 예상치 못한 오류(다른 모듈에서 `SectorStock`의 매수후보 필드를 사용)가 있으면 설계 문서로 보고.

### 검증
- `cd frontend && npm run typecheck` 실행.
- 예상 결과: `hotStore.ts`, `binding.ts`, `buy-target.ts`, `buy-target-columns.ts`에서 타입 오류 (T3~T5에서 해결).
- `sector-stock-rows.ts`는 `avg_amt_5d`가 `SectorStock`에 포함되어 오류 없음 (T1 설계 수정 반영).
- 오류가 예상 범위 내인지 확인 후 T1 종료.

---

## T2. 검색 유틸 제네릭화

### 대상
- `frontend/src/utils/stock-search.ts`

### 변경 명세 (설계 4.1, 5.9)
1. `SectorStock` import 제거.
2. `filterStocksBySearch` 시그니처를 제네릭으로 변경:
   ```typescript
   export function filterStocksBySearch<T extends { code: string; name?: string }>(
     stocks: Iterable<T>,
     query: string,
   ): Set<string> | null
   ```
3. 함수 본문은 `s.code`/`s.name`만 접근하므로 변경 없음.

### 주의 사항
- 호출처(`buy-target.ts`, `sector-stock.ts`)는 자동 추론되므로 명시적 타입 인수 불필요.
- T2 시점에는 `buy-target.ts`가 아직 `SectorStock`을 사용 중이므로 추론 결과가 `SectorStock`으로 나옴 — T5에서 `StockScore`로 자동 전환됨.

### 검증
- `cd frontend && npm run typecheck` 실행.
- T2 자체로 인한 신규 오류 없음 (기존 T1 오류는 그대로 유지).

---

## T3. hotStore 동기화 시그니처 변경

### 대상
- `frontend/src/stores/hotStore.ts`

### 변경 명세 (설계 3.2, 5.2, T1 설계 수정)
1. `StockScore` import 추가 (`SectorStock` import는 유지 — sectorStocks용).
2. `HotState.buyTargets: StockScore[]` (기존 `SectorStock[]`).
3. 시그니처 변경:
   - `rebuildBuyTargetIndex(targets: StockScore[])`
   - `applyBuyTargetsUpdate(data: { buy_targets: StockScore[] })`
   - `applyBuyTargetsDelta(data: { added?: StockScore[]; removed?: string[]; changed?: StockScore[] })`
   - `applyNewsHit` 내부 `(t: SectorStock)` → `(t: StockScore)`
   - `rebindBuyTargetsRealtime(buyTargets: StockScore[], sectorStocks: Record<string, SectorStock>)`
   - `applyInitialSnapshotHot`: `buy_targets as SectorStock[]` → `as StockScore[]`
4. **`applyBuyTargetsUpdate` 비교 키에서 `avg_amt_5d` 제거 (T1 설계 수정)**:
   - 571줄 `&& p.avg_amt_5d === n.avg_amt_5d` 제거.
   - 530줄 주석 "정적 필드: rank, boost_score, guard_pass, reason, order_ratio, program_net_buy, high_5d, avg_amt_5d"에서 `avg_amt_5d` 제거.
   - 백엔드 `_BUY_TARGET_CMP_KEYS`와 일치 (P23) — T7에서 백엔드도 동일 제거.
5. **유지 함수 (sectorStocks 전용 — 변경 금지)**:
   - `stocksToMap(stocks: SectorStock[])`
   - `applySectorStocksRefresh(data: { stocks: SectorStock[] })`
   - `applySectorStocksDelta(data: { added: SectorStock[]; removed: string[] })`
6. `applyRealData`/`applyOrderbookUpdate`/`applyProgramUpdate` 내부 `t` 타입은 TS 추론에 맡김 — 명시적 타입 annotation이 `SectorStock`으로 되어 있으면 제거하여 추론 유도. 단, 본문 로직은 변경 없음 (설계 3.3).
7. `applyRealtimeReset`의 `nullifyFields` 대상은 sectorStocks이므로 `SectorStock` 유지. `rebindBuyTargetsRealtime` 호출부는 T3 변경을 따라감.
8. 주석 업데이트: buyTargets 동기화 관련 주석이 "SectorStock"을 참조하면 "StockScore"로.

### 주의 사항
- 핵심 원칙 (설계 3.3): 동기화 로직은 필드 동일하므로 **시그니처 타입 변경만** 수행. 본문 로직 수정 금지 — P22 (데이터 정합성) 위반 소지.
- 단, `applyBuyTargetsUpdate` 비교 키 `avg_amt_5d` 제거는 T1 설계 수정에 의한 예외 — `avg_amt_5d`가 `StockScore`에서 제거되었으므로 비교 키에서도 제거해야 타입 오류 없음 + P23 일관성 유지.
- `applyRealData`의 buyTargets 루프가 `cur_price/change/change_rate/strength/trade_amount` 5개 필드만 다루는지 확인 — 다른 필드 접근 시 설계 문서로 보고.

### 검증
- `cd frontend && npm run typecheck` 실행.
- 예상: `hotStore.ts` 내부 오류 해소. `binding.ts`, `buy-target.ts`, `buy-target-columns.ts` 오류는 T4, T5로 잔존.

---

## T4. WS 바인딩 캐스팅 변경

### 대상
- `frontend/src/binding.ts`

### 변경 명세 (설계 5.3)
1. `StockScore` import 추가.
2. `buy-targets-update` 이벤트: `as { buy_targets: StockScore[] }`.
3. `buy-targets-delta` 이벤트: `as { added: StockScore[]; removed: string[]; changed: StockScore[] }` (필드명은 실제 코드 확인).
4. `sector-stocks-refresh`/`sector-stocks-delta` 이벤트: `SectorStock` 유지 — 변경 금지.
5. `initial-snapshot`의 `buy_targets` 캐스팅이 있으면 `as StockScore[]`.

### 주의 사항
- 이벤트 페이로드 필드명은 백엔드 WS 스펙(`docs/api_specs/`)과 일치해야 함 — 변경 전 실제 코드의 필드명 확인.
- 캐스팅만 변경하므로 런타임 동작 동일 — P21 (사용자 투명성) 위반 없음.

### 검증
- `cd frontend && npm run typecheck` 실행.
- 예상: `binding.ts` 오류 해소. `buy-target.ts`, `buy-target-columns.ts` 오류는 T5로 잔존.

---

## T5. 매수후보 페이지 타입 변경

### 대상
- `frontend/src/pages/buy-target.ts`
- `frontend/src/pages/buy-target-columns.ts`

### 변경 명세 (설계 5.4)
1. `buy-target.ts`:
   - `SectorStock` import 제거, `StockScore` import 추가.
   - `DataTable<StockScore>` (기존 `DataTable<SectorStock>`).
   - `compareBuyTargets(a: StockScore, b: StockScore)`.
   - `_rsBuyTargets: HotState['buyTargets']` — 자동 추론으로 `StockScore[]` 적용.
   - 모든 `SectorStock` 타입 참조를 `StockScore`로.
2. `buy-target-columns.ts`:
   - `StockScore` import 추가.
   - `ColumnDef<StockScore>[]` (기존 `ColumnDef<SectorStock>[]`).
   - 모든 제네릭 `<SectorStock>` → `<StockScore>`.
   - 컬럼 `accessor`/`value` 함수의 인자 타입이 `SectorStock`이면 `StockScore`로.

### 주의 사항
- 매수후보 전용 필드(`rank`, `guard_pass`, `order_ratio`, `news_boost` 등) 접근은 `StockScore`에서만 유효 — `SectorStock` 참조가 잔존하면 typecheck 오류로 검출됨.
- `sectorStocks`를 참조하는 부분이 있으면 `SectorStock` 유지 (예: 실시간 SSOT 조회용).

### 검증
- `cd frontend && npm run typecheck` 실행.
- 예상: 모든 타입 오류 해소 — typecheck 0 오류.

---

## T6. 테스트 데이터 분리

### 대상
- `frontend/tests/stores/hotStore.test.ts`
- `frontend/tests/pages/profit-shared.test.ts`

### 변경 명세 (설계 5.10)
1. `hotStore.test.ts`:
   - `buyTargets` 관련 테스트 데이터를 `StockScore` 타입에 맞게 (19개 필드 모두 또는 매수후보 컨텍스트에 필요한 필드).
   - `sectorStocks` 관련 테스트 데이터는 `SectorStock` 유지 (10개 필드만).
   - 각 테스트가 어느 컨텍스트인지 판별 — 설계 문서 기준 약 40곳 중 buyTargets 관련만 변경.
2. `profit-shared.test.ts`:
   - `Position.sectorStock`은 `SectorStock` 유지.
   - `sectorStocks` Record 생성 시 `SectorStock` 필드(10개)만 사용하는지 확인.
   - 일부 테스트가 `buyTargets` 필드(`rank`, `guard_pass` 등)를 포함하면 `StockScore`로 분리 — 설계 기준 약 20곳 판별.

### 주의 사항
- 테스트 데이터 분리 시 **실시간 파생 5개 필드**(`cur_price`, `change`, `change_rate`, `strength`, `trade_amount`)는 양쪽 타입 모두에 존재하므로 어느 컨텍스트든 포함 가능 — 혼동 주의.
- 매수후보 전용 필드(`rank`, `guard_pass`, `order_ratio`, `news_boost` 등)가 `SectorStock` 테스트 데이터에 잔존하면 안 됨 — T1의 축소 정책과 일치.
- 테스트 본문 로직(단언 등)은 변경 금지 — 데이터 초기값만 타입에 맞춤.

### 검증
- `cd frontend && npm run typecheck` 실행 — 타입 오류 없음.
- `cd frontend && npm run test` 실행 — 기존 116 테스트 전체 통과 (설계 8의 "294테스트"는 설계 문서 오류 가능, AGENTS.md 기준 116 tests).

---

## T7. 백엔드 avg_amt_5d 이동 (T1 설계 수정)

### 대상
- `backend/app/services/sector_data_provider.py`
- `backend/app/services/engine_account_notify.py`
- `backend/tests/test_engine_account_notify.py`
- `backend/tests/test_web_routes.py` (확인만)
- `backend/tests/test_engine_initial_data.py` (확인만)

### 변경 명세 (설계 5.11)
1. **`sector_data_provider.py` — `_build_target_entry()`**:
   - 165줄 `"avg_amt_5d": s.avg_amt_5d,` 제거 (매수후보에서 불필요).
   - docstring(138-140줄) "정적·식별 필드" 목록에서 `avg_amt_5d` 제거.
2. **`sector_data_provider.py` — `get_all_sector_stocks()`**:
   - 각 종목 dict에 `"avg_amt_5d"` 추가. 데이터 소스: `master_stocks_cache[cd]["avg_5d_trade_amount"]` (백만원 단위) → 억 단위 변환.
   - 변환 패턴: `sector_calculator.py:89`의 `avg5d_eok = avg5d_million // 100`와 일치.
   - 0 = 원천 부재/미다운로드 표시 규칙 유지 (P20 폴백 금지).
3. **`engine_account_notify.py` — `_BUY_TARGET_CMP_KEYS`**:
   - 368줄 `"avg_amt_5d"` 제거.
   - 주석(360-364줄)은 `avg_amt_5d` 개별 언급 없으므로 변경 불필요.
4. **`test_engine_account_notify.py`**:
   - `_make_target`의 `avg_amt_5d` 제거 (647줄).
   - `test_cmp_keys_excludes_realtime_and_news_boost`의 `avg_amt_5d` 포함 검증 제거 (673줄).
   - added/changed 검증에서 `avg_amt_5d` 제거 (720, 804줄).
   - `test_delta_changed_avg_amt_5d_triggers_change` 테스트 제거 (790-804줄) — 더 이상 changed 판정 키가 아님.
5. **`test_web_routes.py`**: 393-395줄 `sector-stocks` 응답 fixture에 이미 `avg_amt_5d` 포함되어 있으므로 유지 확인만.
6. **`test_engine_initial_data.py`**: 118줄 `initial-snapshot`의 `sector_stocks` 필드 목록에 `avg_amt_5d` 포함 확인만.

### 주의 사항
- **safe-trade 스킬 준수**: `_build_target_entry()`는 매수후보 데이터 생성 함수이나, `avg_amt_5d` 제거는 데이터 표시·비교 키 변경이지 주문 경로/매수 조건 변경이 아님 — P15(단일 주문 경로) 영향 없음.
- **P23 일관성**: 백엔드 `_BUY_TARGET_CMP_KEYS`와 프론트 `applyBuyTargetsUpdate` 비교 키가 동일하게 `avg_amt_5d` 제거되어야 함 (T3에서 프론트 제거, T7에서 백엔드 제거).
- **단위 변환 주의**: `master_stocks_cache["avg_5d_trade_amount"]`는 백만원 단위. `sector_calculator.py`는 `avg5d_eok = avg5d_million // 100` (억 단위)로 변환. `get_all_sector_stocks()`도 동일 변환 적용 — P23 일관성.

### 검증
- `.venv/bin/python -m pytest backend/tests/test_engine_account_notify.py backend/tests/test_sector_data_provider.py backend/tests/test_web_routes.py backend/tests/test_engine_initial_data.py -q` 실행.
- 관련 테스트 전체 통과 확인.

---

## T8. 최종 검증

### 대상
- 전체 프론트엔드 + 백엔드

### 검증 항목 (설계 섹션 8)
1. `cd frontend && npm run typecheck` — 통과.
2. `cd frontend && npm run build` — 통과.
3. `cd frontend && npm run test` — 116 테스트 전체 성공.
4. `.venv/bin/python -m pytest backend/tests -q` — 2697 테스트 전체 성공.

### 아키텍처 원칙 점검
- [ ] **P10 (SSOT)**: `sectorStocks`가 실시간 SSOT, `buyTargets`가 파생 캐시 — 분리 후에도 `rebindBuyTargetsRealtime` 동기화 경로 유지 확인. `avg_amt_5d` 주인은 `SectorStock` (T1 설계 수정).
- [ ] **P22 (데이터 정합성)**: `rebindBuyTargetsRealtime` 동작이 변경 전과 동일 — 본문 로직 수정이 없었는지 최종 확인.
- [ ] **P23 (용어 통일)**: `StockScore`는 매수후보 컨텍스트, `SectorStock`은 업종분류 컨텍스트 — 의미 일치. 백엔드 `_BUY_TARGET_CMP_KEYS`와 프론트 비교 키 일치 (`avg_amt_5d` 제거).
- [ ] **P24 (단순성)**: 불필요한 추상화 없음 — 제네릭은 `filterStocksBySearch` 1곳만. `avg_amt_5d` 매수후보에서 제거로 단순화.
- [ ] **P25 (격리된 실패)**: 타입 분리로 인해 한 페이지 렌더링 실패가 다른 페이지로 전파되지 않는지 확인.

### 완료 기준
- 4종 검증 모두 통과 + 원칙 점검 체크리스트 모두 충족.
- 실패 시: 어느 태스크에서 회귀 발생했는지 추적 후 해당 태스크 재실행.

---

## 2. 태스크 실행 워크플로우

```
T1 승인 → T1 실행 → T1 검증(typecheck, 예상 오류 범위 확인)
  → T2 승인 → T2 실행 → T2 검증
  → T3 승인 → T3 실행 → T3 검증
  → T4 승인 → T4 실행 → T4 검증
  → T5 승인 → T5 실행 → T5 검증 (typecheck 0 오류)
  → T6 승인 → T6 실행 → T6 검증 (typecheck + test)
  → T7 승인 → T7 실행 → T7 검증 (pytest — 백엔드 avg_amt_5d 이동)
  → T8 승인 → T8 실행 → T8 검증 (typecheck + build + test + pytest 4종)
```

- 각 태스크 시작 전 사용자 명시적 승인 필수 (AGENTS.md 규칙 0).
- 태스크 실패 시 다음 태스크로 넘어가지 않음 — 실패 원인 분석 후 재시도 또는 설계 수정.
- T5 완료 시점에 typecheck 0 오류가 아니면 T3/T4/T5 중 누락이 있는 것 — 추적.
