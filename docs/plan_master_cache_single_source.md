# 태스크 파일: 마스터 종목 캐시 단일 시세 소스 + 페이지별 구독 Push 모델 구현

> **상태**: 태스크 파일 작성 완료, 3세션 구현 승인 대기
> **작성일**: 2026-08-02
> **설계서 경로**: `docs/architecture_master_cache_single_source_design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ · 2세션(태스크 파일) ✅ · 3세션(백엔드 구현) 예정 · 4세션(프론트 상태·binding) 예정 · 5세션(파생 캐시 제거·render 전환) 예정 · 6세션(독립 검증) 예정 · 모의 관찰 대기
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패) · W3(단일 소스 진리) · W4(파생 데이터 모델) · W7(시뮬레이터/증권사 응답 동일 구조) · W11(표현 통일)
> **위험도**: 중간 (프론트 구조 변경 범위 큼, 백엔드 WS 이벤트 신설·제거 동반. 단, 거래 로직·DB·주문 경로 변경 없음 → 실전 돈 위험 없음)

---

## 목표

시세·호가·프로그램·뉴스 등 종목 단위 실시간 데이터의 단일 진실 소스를 백엔드 `master_stocks_cache`로 통일하고, 각 페이지가 필요한 종목 코드를 백엔드에 직접 신청하여 push로 받는 구조로 전환. 파생 캐시 동기화 로직 7곳 제거. 보유종목 052690 결함(필터 미달 종목 현재가 "-") 근본 해결.

---

## 태스크에서 확정한 세부 결정 (설계서 "남은 세부 선택" 해소)

> 설계서 결정 1·2·3은 사용자 완료. 태스크 파일에서 구현 수준 세부 선택 확정.

### 결정 A: 프론트 상태 명칭 = `masterCache` (sectorStocks 재활용 아님)

**선택**: `sectorStocks`를 재활용하지 않고 `masterCache` 신규 명칭 사용.

**사유**: sectorStocks는 "필터된 부분집합"이라는 역사적 의미가 남아 역할 혼동 유발. 전 종목 마스터 캐시로 역할이 변경되므로 P23 일관성을 위해 명칭 교체. 마이그레이션 비용보다 의미 명확성이 우선 (P24 단순성 — 중복 제거보다 역할 명확성이 근본).

### 결정 B: 구독 신청 방식 = A (notifyPageActive 확장)

**선택**: 기존 `notifyPageActive(page)`를 `notifyPageActive(page, codes)`로 확장 (단일 메시지). 별도 subscribe 메시지(B안)는 채택하지 않음.

**사유**: 기존 인프라(ws.ts:265-276, ws.py:207-212) 재사용 → P24 단순성. 페이지 활성화와 구독 신청이 동일 생명주기이므로 메시지 분리 불필요.

### 결정 C: 마스터 캐시 snapshot + delta 전송

**선택**: 페이지 구독 신청 시 해당 종목들의 현재 마스터 캐시 값 snapshot 전송 → 이후 이벤트 시 delta push. 기존 `sector-stocks-refresh`/`sector-stocks-delta` 이벤트는 `master-cache-snapshot`/`master-cache-delta`로 대체.

**사유**: 기존 snapshot+delta 패턴 재사용 (P23 일관성). 전 종목 전송이 아니라 구독 신청한 종목만 전송하므로 부하 최소화.

---

## 변경 대상 파일

### 백엔드 (3세션)

| 파일 | 수정 목적 | 수정 포인트 | 수정 범위 |
|---|---|---|---|
| `backend/app/services/engine_state.py` | news_boost_cache를 master_stocks_cache 필드로 통합 | 140행 `master_stocks_cache` 선언, 154행 `news_boost_cache` 선언 | `news_boost_cache`를 별도 dict에서 master_stocks_cache[code]["news_boost"]·["news_boost_ts"] 필드로 이동. TTL 로직은 필드 위치만 이동, 만료 처리 동일 |
| `backend/app/services/engine_radar.py` | news_boost_cache 조회 함수 갱신 | `get_news_boost_cache()` 26-39행 | master_stocks_cache[code].get("news_boost") 기반으로 조회. 만료 시 필드 null화 로직으로 변경 |
| `backend/app/pipelines/pipeline_compute_tick_handlers.py` | 뉴스 이벤트가 news_boost_cache 대신 master_stocks_cache 필드 갱신 | `_handle_nws_news` 453행, 470-476행 | `news_boost_cache[code] = (score, now)` → `master_stocks_cache[code]["news_boost"] = score; ["news_boost_ts"] = now`. news-hit 이벤트 payload는 그대로 (프론트가 마스터 캐시 필드로 갱신) |
| `backend/app/web/ws_manager.py` | 종목별 구독 참조 카운트 맵 추가 | `__init__` 80-85행, `set_active_page`/`clear_active_page` 109-119행 | `self._symbol_subscribers: dict[str, dict[str, int]]` (symbol → {page: refcount}) 추가. `subscribe_codes(page, codes)`·`unsubscribe_page(page)` 메서드 추가. 0→1 전환 시 해당 종목 실시간 전송 시작, 1→0 시 중단 |
| `backend/app/web/routes/ws.py` | page-active payload에 codes 처리 추가 | 207-212행 page-active/page-inactive 처리 | `page = msg.get("page", ""); codes = msg.get("codes", [])`. `ws_manager.subscribe_codes(websocket, page, codes)`. 구독 신청 시 해당 종목 마스터 캐시 snapshot 전송 (`master-cache-snapshot` 이벤트) |
| `backend/app/services/engine_initial_data.py` | 마스터 캐시 snapshot payload 생성 함수 추가 | `build_sector_stocks_payload` 99-116행 | `build_master_cache_snapshot(codes)` 함수 추가 — 전 종목이 아닌 요청된 codes만. 기존 `build_sector_stocks_payload`는 제거 또는 snapshot 함수로 대체 |
| `backend/app/services/sector_data_provider.py` | get_all_sector_stocks()에 실시간 필드 추가 옵션 | `get_all_sector_stocks` 183-221행 | 실시간 필드 포함 버전 추가 (snapshot 생성용). 단, 기존 업종분류 전용 호출처는 영향 없도록 파라미터 분리 |
| `backend/app/services/engine_ws_dispatch.py`·`engine_ws_reg.py` | 틱/호가/PGM 이벤트 시 구독 페이지 라우팅 | 틱/호가/PGM 전송 함수들 | 마스터 캐시 갱신 후 해당 종목을 구독 중인 페이지 집합 조회 → `broadcast_to_pages`로 push. 기존 `notify_orderbook_update`/`notify_program_update`의 전체 전송을 구독 페이지 전송으로 변경 |

### 프론트 (4세션·5세션)

| 파일 | 수정 목적 | 수정 포인트 | 수정 범위 |
|---|---|---|---|
| `frontend/src/types/index.ts` | MasterStock 타입 추가, SectorStock 제거 | SectorStock 84-102행, StockScore 54-82행 | `MasterStock` 신규 타입 (시세+호가+프로그램+뉴스 필드 통합). StockScore에서 실시간 필드(cur_price, change, change_rate, strength, trade_amount, order_ratio, program_net_buy) 제거 — 정적 스코어만 남김. SectorStock은 MasterStock으로 흡수 |
| `frontend/src/stores/hotStore.ts` | masterCache 상태 추가, sectorStocks 제거, 파생 캐시 동기화 로직 7곳 제거 | `HotState` interface, applyRealData 331-467, applyOrderbookUpdate 478-496, applyProgramUpdate 507-524, applyRealtimeReset 548-589, applyBuyTargetsUpdate 608-650, applyBuyTargetsDelta 688-760, rebindBuyTargetsRealtime 808-824, applySectorStocksRefresh 826-837, applySectorStocksDelta 843-865 | `masterCache: Record<string, MasterStock>` 상태 추가. `sectorStocks` 상태 제거. `rebindBuyTargetsRealtime` 함수 제거. `applyOrderbookUpdate`·`applyProgramUpdate` 제거. `applyRealData` buyTargets 분기(424-446) 제거 — masterCache + positions 2곳만 갱신. `applyBuyTargetsUpdate`·`applyBuyTargetsDelta`의 sectorStocks 재결합 분기 제거. `applyRealtimeReset`에서 rebind 호출 제거 — masterCache null화만. `applySectorStocksRefresh`·`applySectorStocksDelta`를 `applyMasterCacheSnapshot`·`applyMasterCacheDelta`로 대체 |
| `frontend/src/api/ws.ts` | notifyPageActive에 codes 파라미터 추가 | 265-276행 | `notifyPageActive(page: string, codes: string[])`로 확장. payload에 `codes` 배열 추가 |
| `frontend/src/binding.ts` | WS 이벤트 핸들러 교체 | 102-104, 107-109, 128-130, 132-134, 271-275행 | `sector-stocks-refresh`/`sector-stocks-delta` 핸들러를 `master-cache-snapshot`/`master-cache-delta`로 교체. `orderbook-update`·`program-update` 핸들러 제거. `news-hit` 핸들러는 masterCache 필드 갱신으로 변경 |
| `frontend/src/pages/sell-position.ts` | 현재가 컬럼을 masterCache 참조로 전환 | 42-55행 현재가 컬럼 render | `state.sectorStocks[code]` → `state.masterCache[code]`. mount 시 보유 종목 코드를 `notifyPageActive('sell-position', codes)`로 전송 |
| `frontend/src/pages/buy-target.ts` | 매수후보 페이지 구독 신청 | mount/unmount 시 notifyPageActive 호출 | 매수후보 종목 코드를 `notifyPageActive('buy-target', codes)`로 전송. buyTargets 배열에서 종목 코드 추출 |
| `frontend/src/pages/buy-target-columns.ts` | render 함수를 masterCache 참조로 전환 | 35-50행 현재가 컬럼, 51-52행 등락/등락률 컬럼 | `t.cur_price` → `masterCache[t.code]?.cur_price`. 모든 실시간 필드(cur_price, change, change_rate, strength, trade_amount, order_ratio, program_net_buy)를 masterCache에서 참조 |
| `frontend/src/pages/sector-stock.ts` | sectorStocks → masterCache에서 필터 파생 | 63-82행 buildRows | `state.sectorStocks` → `state.masterCache`. 필터 통과 종목 코드를 `notifyPageActive('sector-stock', codes)`로 전송 |
| `frontend/src/pages/profit-detail-mount.ts` | 종목명 참조를 masterCache로 전환 | 종목명 참조부 | sectorStocks → masterCache 참조 |

### 테스트 (5세션)

| 파일 | 수정 목적 | 수정 포인트 |
|---|---|---|
| `frontend/tests/stores/hotStore.test.ts` | masterCache 갱신 회귀, 파생 캐시 제거 검증 | applyRealData, applyRealtimeReset, applyMasterCacheSnapshot/Delta 테스트. rebindBuyTargetsRealtime 제거 검증 |
| `frontend/tests/pages/sell-position.test.ts` | 현재가 컬럼 masterCache 참조 회귀 | render가 masterCache[code] 참조, null 시 '-' |
| `frontend/tests/pages/buy-target-columns.test.ts` | 매수후보 컬럼 masterCache 참조 회귀 | render가 masterCache[t.code] 참조 |
| `backend/tests/test_engine_radar.py` | news_boost_cache 통합 회귀 | get_news_boost_cache가 master_stocks_cache 기반 동작 |
| `backend/tests/test_ws_manager.py` | 구독 참조 카운트 맵 회귀 | subscribe_codes/unsubscribe_page, 0→1/1→0 전환 |

---

## 작업 순서

> 세션당 1단계 원칙 (규칙 0-1). 위험도 중간 — 각 단계별 검증 게이트 필수.

### 1단계: 백엔드 — 마스터 캐시 통합 + 구독 관리자 + WS 이벤트 (3세션)

- [ ] `engine_state.py` — `news_boost_cache`를 master_stocks_cache 필드로 통합. `news_boost_cache` dict 제거, master_stocks_cache[code]에 `news_boost`·`news_boost_ts` 필드 추가
- [ ] `engine_radar.py` — `get_news_boost_cache()`를 master_stocks_cache 기반으로 갱신. 만료 시 필드 null화
- [ ] `pipeline_compute_tick_handlers.py` — `_handle_nws_news`가 master_stocks_cache[code] 필드 갱신하도록 변경. news-hit 이벤트 payload 유지
- [ ] `ws_manager.py` — `_symbol_subscribers: dict[str, dict[str, int]]` 추가. `subscribe_codes(ws, page, codes)`·`unsubscribe_page(ws, page)` 메서드 구현. 0→1 전환 시 snapshot 전송 트리거, 1→0 시 전송 중단
- [ ] `ws.py` — page-active 처리에서 `codes` 배열 수신 → `ws_manager.subscribe_codes(websocket, page, codes)`. 구독 신청 종목 snapshot 전송 (`master-cache-snapshot` 이벤트)
- [ ] `engine_initial_data.py` — `build_master_cache_snapshot(codes)` 함수 추가. 기존 `build_sector_stocks_payload`는 제거 또는 snapshot 함수로 대체
- [ ] `sector_data_provider.py` — `get_all_sector_stocks()`에 실시간 필드 포함 옵션 추가 (snapshot 생성용)
- [ ] `engine_ws_dispatch.py`·`engine_ws_reg.py` — 틱/호가/PGM 이벤트 시 구독 페이지 라우팅. 기존 `notify_orderbook_update`/`notify_program_update` 전체 전송을 구독 페이지 전송으로 변경
- [ ] 기존 `sector-stocks-refresh`/`sector-stocks-delta` 이벤트 전송 경로 제거 (master-cache-snapshot/delta로 대체)
- [ ] 거래 로직(execute_buy/execute_sell)·리스크 매니저·서킷브레이커 변경 없음 확인
- [ ] DB 스키마 변경 없음 확인 (메모리 전용 필드)

**1단계 검증 방법:**
- [ ] `.venv/bin/python -m pytest backend/tests -q` — 전체 백엔드 테스트 통과
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — RuntimeWarning 0건, 정상 기동
- [ ] news_boost_cache 통합 후 뉴스 가산점 정상 동작 (테스트 모드)
- [ ] 구독 참조 카운트 맵 정상 동작 (0→1 snapshot 전송, 1→0 중단)
- [ ] 거래 로직 회귀 없음 (test_buy_filter.py 등 매수 관련 테스트 통과)

### 2단계: 프론트 — masterCache 상태 + binding 교체 + 구독 신청 (4세션)

- [ ] `types/index.ts` — `MasterStock` 타입 추가 (시세+호가+프로그램+뉴스 필드 통합). `SectorStock` 제거. `StockScore`에서 실시간 필드 제거 (정적 스코어만)
- [ ] `hotStore.ts` — `masterCache: Record<string, MasterStock>` 상태 추가. `sectorStocks` 상태 제거. `applyMasterCacheSnapshot`·`applyMasterCacheDelta` 함수 추가 (기존 applySectorStocksRefresh/Delta 대체)
- [ ] `ws.ts` — `notifyPageActive(page, codes)`로 확장. payload에 `codes` 배열 추가
- [ ] `binding.ts` — `sector-stocks-refresh`/`sector-stocks-delta` 핸들러를 `master-cache-snapshot`/`master-cache-delta`로 교체. `orderbook-update`·`program-update` 핸들러 제거. `news-hit` 핸들러를 masterCache 필드 갱신으로 변경
- [ ] `applyRealData` — 갱신 대상을 masterCache + positions 2곳으로 단순화 (기존 3곳). buyTargets 분기 제거
- [ ] `applyRealtimeReset` — masterCache null화 + positions null화만. rebind 호출 제거
- [ ] 각 페이지 mount 시 `notifyPageActive(page, codes)`로 종목 코드 전송, unmount 시 `notifyPageInactive(page)` 전송
  - sell-position: 보유 종목 코드 (positions에서 추출)
  - buy-target: 매수후보 종목 코드 (buyTargets에서 추출)
  - sector-stock: 필터 통과 종목 코드 (masterCache에서 필터 후 추출)
- [ ] `applyRealData`의 rAF 배칭(_tickDirty + scheduleTickFlush) 유지 — conflation으로 재해석 (설계서 결정 6)

**2단계 검증 방법:**
- [ ] `cd frontend && npm run typecheck` — 통과
- [ ] `cd frontend && npm run test` — 통과 (기존 테스트 갱신 포함)
- [ ] `cd frontend && npm run build` — 통과
- [ ] masterCache 상태가 백엔드 push로 정상 갱신되는지 확인 (정적 코드 검증)
- [ ] 구독 신청 payload에 종목 코드 포함 확인

### 3단계: 파생 캐시 제거 + 페이지 render 전환 (5세션)

- [ ] `hotStore.ts` — `rebindBuyTargetsRealtime` 함수 제거 (808-824행)
- [ ] `hotStore.ts` — `applyOrderbookUpdate`·`applyProgramUpdate` 함수 제거 (478-496, 507-524행)
- [ ] `hotStore.ts` — `applyBuyTargetsUpdate`·`applyBuyTargetsDelta`의 sectorStocks 재결합 분기 제거 (620-634, 710-754행). buyTargets는 정적 스코어만 보관
- [ ] `binding.ts` — `orderbook-update`·`program-update` 이벤트 핸들러 제거 완료 확인
- [ ] `sell-position.ts` — 현재가 컬럼 render를 `state.masterCache[code]` 참조로 전환 (기존 sectorStocks → masterCache)
- [ ] `buy-target-columns.ts` — 모든 실시간 필드 참조를 `masterCache[t.code]`로 전환. `t.cur_price` → `masterCache[t.code]?.cur_price` 등
- [ ] `sector-stock.ts` — `state.sectorStocks` → `state.masterCache`에서 필터 파생
- [ ] `profit-detail-mount.ts` — 종목명 참조를 masterCache로 전환
- [ ] buyTargets에서 실시간 필드(cur_price, change, change_rate, strength, trade_amount, order_ratio, program_net_buy) 제거 — 정적 스코어(rank, guard_pass, reject_reason, boost_score)만 남김
- [ ] positions.cur_price는 계산용 유지 (computePositionValuation, computeHoldingsSummary) — 변경 없음

**3단계 검증 방법:**
- [ ] `cd frontend && npm run typecheck` — 통과
- [ ] `cd frontend && npm run test` — 통과 (파생 캐시 제거 회귀 테스트 포함)
- [ ] `cd frontend && npm run build` — 통과
- [ ] `rebindBuyTargetsRealtime` 함수 및 호출 3곳 제거 확인 (grep)
- [ ] `applyOrderbookUpdate`·`applyProgramUpdate` 제거 확인 (grep)
- [ ] buyTargets에서 실시간 필드 참조 제거 확인 (grep — `t.cur_price` 등 직접 참조 없음)
- [ ] positions.cur_price 계산용 사용 유지 확인 (computePositionValuation 변경 없음)
- [ ] DataTable O(1) 갱신 보존 확인 — updateItemByKey 경로 유지

### 4단계: 독립 검증 (6세션)

- [ ] 3-5세션 구현 커밋 + 본 태스크 파일만 기준으로 독립 검토 수행 (코드 변경 없음)
- [ ] 설계서 9.1~9.9 완료 기준 정적 코드 검증
- [ ] 기계적 검증 게이트 전부 통과 확인
- [ ] 독립 검증 결과를 HANDOVER.md에 기록

**4단계 검증 방법:**
- [ ] `.venv/bin/python -m pytest backend/tests -q` — 통과
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — RuntimeWarning 0건
- [ ] `cd frontend && npm run typecheck` — 통과
- [ ] `cd frontend && npm run test` — 통과
- [ ] `cd frontend && npm run build` — 통과
- [ ] 설계서 9.1(052690 결함 해결) — masterCache가 전 종목 보관하므로 보유종목 필터 미달 누락 없음 확인
- [ ] 설계서 9.2(단일 시세 소스) — 시세가 masterCache 1곳에만 존재 확인 (buyTargets 실시간 필드 복사 제거)
- [ ] 설계서 9.3(파생 캐시 동기화 로직 제거) — 7곳 전부 제거 확인
- [ ] 설계서 9.4(페이지별 구독) — mount 시 codes 전송, unmount 시 해지, 참조 카운트 확인
- [ ] 설계서 9.5(마스터 캐시 통합) — news_boost가 masterCache 필드, 매수 순위·차단·가산점은 마스터 캐시 외부 확인
- [ ] 설계서 9.6(성능 보존) — DataTable O(1) 갱신, rAF 배칭 유지 확인
- [ ] 설계서 9.7(리셋 정합성) — 07:58 리셋 후 masterCache null화 → '-' 표시, 첫 틱 후 전환 확인
- [ ] 설계서 9.8(계산 경로 유지) — positions.cur_price 계산용 사용, 비실시간 구간 '-' 표시 확인
- [ ] 설계서 9.9(거래 로직 무변경) — execute_buy/execute_sell, RiskManager, CircuitBreaker 변경 없음 확인

### 5단계: 모의 관찰 (사용자)

- [ ] 모의투자/test 모드에서 최소 1거래일 관찰
- [ ] 보유종목 화면: 모든 보유 종목 가격 표시 (이전 "-"였던 052690 포함)
- [ ] 매수후보 화면: 랭킹·가격·호가·프로그램·뉴스 컬럼 정상 표시
- [ ] 섹터 화면: 필터 통과 종목 가격 정상 표시
- [ ] 07:58 리셋 → 첫 틱 전 '-' → 첫 틱 후 실시간가 전환
- [ ] 페이지 전환(보유↔매수↔섹터) 시 가격 표시 끊김 없음
- [ ] 이상 시 `git revert <구현 커밋 해시>`

---

## 금지사항 (Not To Do)

> 설계서 비목표와 동일. 아래 항목은 본 태스크에서 절대 수행하지 않음.

- [ ] `positions.cur_price` 필드 자체 제거 금지 — 계산용 유지 (W7)
- [ ] 매수후보 정적 스코어(rank, guard_pass, reject_reason, boost_score)를 마스터 캐시로 이동 금지 — sector_summary_cache가 SSOT
- [ ] news_boost를 마스터 캐시와 별도 캐시 양쪽에 유지 금지 — 마스터 캐시 필드로 통합 (P10)
- [ ] DB 스키마 변경 금지 — 마스터 캐시는 메모리 상태
- [ ] Redis/Pub-Sub/분산 메시지 브로커 도입 금지 — 백엔드 메모리 참조 카운트 맵 (P5)
- [ ] 페이지가 마스터 캐시 전체를 프론트에 들고 직접 필터링하는 구조 금지 — 페이지별 구독 push
- [ ] 거래 로직(execute_buy/execute_sell)·리스크 매니저·서킷브레이커 수정 금지
- [ ] `_reset_realtime_fields` 리셋 시점(07:58 등) 변경 금지
- [ ] 장마감 파이프라인·확정가 저장 로직 수정 금지
- [ ] ARCHITECTURE.md P1~P25 원칙 본문 수정 금지
- [ ] 백엔드가 페이지 이름으로 종목을 알아서 매핑 금지 — 프론트가 종목 코드 직접 전송 (사용자 결정 2)
- [ ] 마스터 캐시에 매수 순위·차단 여부·가산점·업종 점수 포함 금지 — 공통 실시간 데이터만 (사용자 결정 3)

---

## 완료 조건 (Done Criteria)

> 설계서 "완료 기준"(9.1~9.9)에서 파생된 구현 수준 조건.

- [ ] `engine_state.py`에서 `news_boost_cache`가 별도 dict가 아닌 master_stocks_cache 필드로 존재
- [ ] `ws_manager.py`에 `_symbol_subscribers` 참조 카운트 맵이 존재하고 subscribe_codes/unsubscribe_page 메서드가 구현됨
- [ ] `ws.py` page-active 처리가 `codes` 배열을 수신하여 구독 신청 처리
- [ ] `master-cache-snapshot`/`master-cache-delta` WS 이벤트가 구현됨
- [ ] 기존 `sector-stocks-refresh`/`sector-stocks-delta` 이벤트 전송 경로가 제거됨
- [ ] `orderbook-update`/`program-update` 이벤트가 구독 페이지 전송으로 변경됨 (전체 전송 아님)
- [ ] `types/index.ts`에 `MasterStock` 타입이 존재하고 `SectorStock`이 제거됨
- [ ] `hotStore.ts`에 `masterCache` 상태가 존재하고 `sectorStocks`이 제거됨
- [ ] `rebindBuyTargetsRealtime` 함수가 제거됨 (grep 검색 0건)
- [ ] `applyOrderbookUpdate`·`applyProgramUpdate` 함수가 제거됨 (grep 검색 0건)
- [ ] `applyRealData`가 masterCache + positions 2곳만 갱신 (buyTargets 분기 제거)
- [ ] `applyRealtimeReset`이 masterCache null화만 하고 rebind 호출 없음
- [ ] `binding.ts`에 `orderbook-update`/`program-update` 핸들러가 없음
- [ ] `sell-position.ts` 현재가 컬럼이 `state.masterCache[code]` 참조
- [ ] `buy-target-columns.ts` 모든 실시간 필드가 `masterCache[t.code]` 참조 (t.cur_price 직접 참조 없음)
- [ ] `sector-stock.ts`가 `state.masterCache`에서 필터 파생
- [ ] `notifyPageActive`가 `(page, codes)` 시그니처로 종목 코드 전송
- [ ] buyTargets에서 실시간 필드(cur_price, change, change_rate, strength, trade_amount, order_ratio, program_net_buy)가 제거됨
- [ ] positions.cur_price가 computePositionValuation·computeHoldingsSummary에서 계속 사용됨
- [ ] execute_buy/execute_sell, RiskManager, CircuitBreaker 변경 없음
- [ ] DB 스키마 변경 없음
- [ ] `.venv/bin/python -m pytest backend/tests -q` 통과
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` RuntimeWarning 0건
- [ ] `cd frontend && npm run typecheck` 통과
- [ ] `cd frontend && npm run test` 통과
- [ ] `cd frontend && npm run build` 통과

---

## 테스트 계획

- **백엔드 단위 테스트**: `test_engine_radar.py` news_boost_cache 통합 회귀, `test_ws_manager.py` 구독 참조 카운트 맵 회귀 (0→1/1→0 전환), `test_pipeline_compute_tick_handlers.py` 뉴스 이벤트 master_stocks_cache 갱신 회귀
- **프론트 단위 테스트**: `hotStore.test.ts` masterCache 갱신·파생 캐시 제거 검증, `sell-position.test.ts`·`buy-target-columns.test.ts` render 참조 전환 회귀
- **범위 회귀**: 프론트 전체 테스트·빌드, 백엔드 전체 pytest
- **거래 로직 회귀**: test_buy_filter.py 등 매수 관련 테스트 통과 확인 (거래 로직 무변경 검증)

---

## 런타임 검증 방법

- 백엔드 기동: `.venv/bin/python main.py` — 0-1-3 명령어로 잔존 프로세스 0건 확인
- RuntimeWarning 검증: `.venv/bin/python -W error::RuntimeWarning main.py` — await 누락 검증
- 테스트 모드에서 구독 신청·snapshot 전송·delta push 정상 동작 확인
- 페이지 전환 시 구독 해지·재신청 정상 동작 확인

---

## 사전 롤백 계획

> 위험도 '중간' — 필수. 문제 발생 시 코딩을 모르는 사용자가 즉시 실행할 수 있도록.

### 롤백 명령
- `git revert <구현 커밋 해시>` — 각 세션 구현 완료 후 커밋 해시 기재

### 즉시 롤백 트리거 (다음 중 하나 발생 시)
- 보유종목 화면에서 가격이 "-"로 표시되는 종목이 이전보다 많아짐 (052690 외 다수 종목 누락)
- 매수후보 화면 랭킹 순서가 이전과 달라짐 (정적 스코어 참조 경로 깨짐 의미)
- 실시간 틱 수신 시 화면이 끊기거나 멈춤 (DataTable O(1) 갱신 경로 깨짐 의미)
- 07:58 리셋 후 가격이 '-'로 표시되지 않고 이전 값 잔류 (리셋 정합성 깨짐)
- 자동매수/자동매도가 이전과 다르게 동작 (거래 로직에 영향 전파 의미)
- 뉴스 가산점이 표시되지 않거나 만료 후 잔류 (news_boost 통합 깨짐)

### 관찰 기준 (위험도 '중간' — 모의 관찰 권장)
- 모의투자/test 모드에서 최소 1거래일 관찰
- 확인 항목:
  - 보유종목 화면: 모든 보유 종목 가격 표시 (이전 "-"였던 052690 포함)
  - 매수후보 화면: 랭킹·가격·호가·프로그램·뉴스 컬럼 정상 표시
  - 섹터 화면: 필터 통과 종목 가격 정상 표시
  - 07:58 리셋 → 첫 틱 전 '-' → 첫 틱 후 실시간가 전환
  - 페이지 전환(보유↔매수↔섹터) 시 가격 표시 끊김 없음

### 롤백 후 확인
- `git revert <해시>` 후 `.venv/bin/python -m pytest backend/tests -q`, `cd frontend && npm run typecheck && npm run test && npm run build` 재실행

---

## 사용자 결정 항목

> 설계서 "사용자 결정 항목" 3건 전부 사용자 완료. 본 태스크 파일에서 구현 수준 세부 선택(결정 A·B·C) 확정.

- **결정 1 (사용자 완료)**: 백엔드 마스터 캐시를 프론트에 전달, sectorStocks 삭제
- **결정 2 (사용자 완료)**: 프론트가 종목 코드 직접 전송, 백엔드 매핑 금지
- **결정 3 (사용자 완료)**: 마스터 캐시는 공통 실시간 데이터만, 페이지별 계산은 자체
- **결정 A (태스크 확정)**: 프론트 상태 명칭 = `masterCache` (sectorStocks 재활용 아님)
- **결정 B (태스크 확정)**: 구독 신청 방식 = notifyPageActive(page, codes) 확장 (A안)
- **결정 C (태스크 확정)**: 마스터 캐시 snapshot + delta 전송 (master-cache-snapshot/delta 이벤트)

---

## 바로잡음 로그

- 없음.
