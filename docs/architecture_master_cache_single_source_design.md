# 설계서: 마스터 종목 캐시 단일 시세 소스 + 페이지별 구독 Push 모델

> **상태**: 설계 완료, 승인 대기
> **작성일**: 2026-08-01
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패) · W3(단일 소스 진리) · W4(파생 데이터 모델) · W7(시뮬레이터/증권사 응답 동일 구조) · W11(표현 통일)
> **관련 파일**: `frontend/src/stores/hotStore.ts` · `frontend/src/binding.ts` · `frontend/src/api/ws.ts` · `frontend/src/api/client.ts` · `frontend/src/types/index.ts` · `frontend/src/pages/sell-position.ts` · `frontend/src/pages/buy-target.ts` · `frontend/src/pages/buy-target-columns.ts` · `frontend/src/pages/sector-stock.ts` · `frontend/src/pages/profit-math.ts` · `frontend/src/pages/profit-detail-mount.ts` · `backend/app/services/sector_data_provider.py` · `backend/app/services/engine_initial_data.py` · `backend/app/services/engine_account_notify.py` · `backend/app/services/engine_radar.py` · `backend/app/services/engine_state.py` · `backend/app/web/routes/ws.py` · `backend/app/web/ws_manager.py` · `backend/app/services/pipeline_compute_tick_handlers.py`
> **선행 작업**: `docs/architecture_position_display_source_separation_design.md` (커밋 `08efb81`) — 보유종목 표시 소스를 sectorStocks로 전환. 본 설계는 이 전환에서 노출된 "sectorStocks가 필터된 부분집합이라 보유종목이 누락되는 결함"의 근본 해결.
> **사전조사**: 4개 병렬 서브에이전트 전수 조사(프론트 파생 캐시 의존성·DataTable O(1) 갱신·백엔드 master_stocks_cache 소비자·매수후보 스코어/틱/리셋) + 인터넷 검증(Bloomberg 시스템 설계·Engineered.at 실시간 마켓 데이터·schwab-data-proxy refcount·GraphQL Subscriptions at Scale)

---

## 금지사항 (Not To Do) — 본 작업에서 절대 수행하지 않는 것

> 구현 과정에서 범위가 자연스럽게 확장되는 것을 방지하기 위한 명시적 경계. 본 설계의 핵심은 **"시세 데이터의 단일 진실 소스를 마스터 종목 캐시 하나로 통일하고, 각 페이지가 필요한 종목을 백엔드에 구독 신청하여 push로 받는 구조로 전환"**이며, 아래 항목들은 이 원칙에 반하는 과도한 확장이다.

| 금지 항목 | 사유 |
|---|---|
| `positions.cur_price` 필드 자체 제거 | positions는 손익·평가·매도조건 계산의 입력값으로 계속 사용 (선행 설계 `08efb81` 결정 1·2 유지). 표시만 마스터 캐시로 전환, 계산은 positions 유지. W7(증권사 응답 구조) 보존 |
| 매수후보 정적 스코어 필드(rank, guard_pass, reject_reason, boost_score)를 마스터 캐시로 이동 | 이 필드들은 `sector_summary_cache`가 SSOT이며 마스터 캐시와 무관 (사전조사 4 확인). 매수후보 전용 별도 소스 유지 — 마스터 캐시는 "종목 단위 실시간 데이터"만 담당 |
| `news_boost`/`news_boost_title`을 마스터 캐시에서 별도 캐시로 유지하면서 동시에 마스터 캐시에도 추가 | 이중 SSOT 위반(P10). `news_boost_cache`를 마스터 캐시의 필드로 통합하거나, 통합하지 않을 경우 별도 캐시 그대로 유지. 둘 다 가지지 않음 |
| DB 스키마 변경 (신규 컬럼·마이그레이션) | 마스터 캐시는 메모리 상태이며 DB는 `master_stocks_table` 그대로. 실시간 필드(order_ratio, program_net_buy, news_boost)는 메모리 전용 필드이므로 DB 변경 불필요. 안전 규칙 2(백업) 미적용 |
| Redis/Pub-Sub/분산 메시지 브로커 도입 | 1인 로컬 단일 프로세스 구조(D1) 유지. 구독 관리는 백엔드 메모리의 참조 카운트 맵으로 구현 — 외부 브로커 불필요 (P5 준수) |
| 페이지가 마스터 캐시 전체를 프론트에 들고 직접 필터링하는 구조 | 사용자 원칙 1 위반 — "각 페이지가 마스터 캐시를 직접 뒤지는 구조가 아니다". 백엔드가 페이지별 구독을 관리하고 신청한 종목만 push |
| 거래 로직(execute_buy/execute_sell)·리스크 매니저·서킷브레이커 수정 | 본 설계는 데이터 표시·전송 구조 변경. 주문 경로(P15)·거래 로직은 변경 없음. safe-trade 스킬 대상 아님 |
| `_reset_realtime_fields` 리셋 시점(07:58 등) 변경 | 리셋 시점은 그대로 유지. 리셋 대상만 파생 캐시 동기화 로직 제거로 단순화 |
| 장마감 파이프라인·확정가 저장 로직 수정 | `market_close_pipeline.py`의 확정가 저장은 그대로. 마스터 캐시 갱신 경로 유지 |
| ARCHITECTURE.md P1~P25 원칙 본문 수정 | 본 설계는 기존 원칙을 준수하는 구조 변경. 원칙 자체를 바꾸지 않음 |

---

## 0. 최상위 원칙

> **시세(현재가·대비·등락률·체결강도·거래대금)와 종목 단위 실시간 데이터(호가잔량비·프로그램순매수·뉴스 가산점)는 마스터 종목 캐시(`master_stocks_cache`)가 단일 진실 소스다.** 각 페이지는 마스터 캐시를 직접 뒤지지 않고, 백엔드에 필요한 종목을 미리 신청하여 이벤트 발생 시 신청한 페이지에만 해당 데이터를 push받는다. 파생 캐시(buyTargets 실시간 필드 복사·positions 표시용 cur_price·rebindBuyTargetsRealtime 동기화 로직)는 제거한다.

---

## 1. 배경 및 목표

### 1.1 문제 발단 — 052690(한전기술) 보유종목 현재가 "-" 표시

보유종목 화면에서 한전기술(052690)만 현재가가 "-"로 표시되는 현상 발견. 조사 결과:

- DB `master_stocks_table`: 052690 cur_price=87400 정상 존재
- 백엔드 `master_stocks_cache`: 전 종목 보관 (052690 포함)
- **프론트 `sectorStocks`**: `get_sector_stocks()`의 5거래일 평균 거래대금 필터(임계값 200억)를 거친 **부분집합** — 052690은 197억으로 미달 → 제외
- 보유종목 표시 소스(`sell-position.ts:46-54`, 커밋 `08efb81`): `sectorStocks[code].cur_price` 참조 → 052690 없음 → "-"

### 1.2 근본 원인 — "부분집합을 SSOT라 부르는 모순"

현재 프론트 `sectorStocks`는 **필터된 부분집합**이면서 **실시간 시세 SSOT**로 불린다. 이는 W3 SSOT 위반 — "같은 데이터는 한 곳에서만 관리"인데, 시세가 `sectorStocks`·`buyTargets`(복사)·`positions.cur_price`(복사) 3곳에 중복 관리.

필터가 데이터 소스 단계에서 수행되어, 소비자(각 페이지)가 소스에 없는 데이터를 결코 볼 수 없음. 052690이 정상 보유종목인데도 섹터 화면 필터 기준의 부분집합에 없어서 표시 불가.

### 1.3 현재 구조의 복잡도 — 파생 캐시 동기화 로직 7곳

시세가 3곳에 중복 저장되어 동기화 로직이 존재:

| 동기화 로직 | 위치 | 존재 이유 |
|---|---|---|
| `rebindBuyTargetsRealtime` 함수 | `hotStore.ts:807-835` | sectorStocks 교체 시 buyTargets 실시간 필드 재결합 |
| `rebindBuyTargetsRealtime` 호출 3곳 | applyRealtimeReset/applySectorStocksRefresh/applySectorStocksDelta | 동일 |
| `applyRealData` buyTargets 분기 | `hotStore.ts:424-446` | 틱마다 buyTargets 실시간 필드 복사 갱신 |
| `applyOrderbookUpdate` | `hotStore.ts:483-491` | order_ratio를 buyTargets에 복사 |
| `applyProgramUpdate` | `hotStore.ts:512-516` | program_net_buy를 buyTargets에 복사 |
| `applyBuyTargetsUpdate` sectorStocks 재결합 분기 | `hotStore.ts:611-627` | buyTargets 교체 시 sectorStocks 기준 재결합 |
| `applyBuyTargetsDelta` sectorStocks 재결합 분기 | `hotStore.ts:708-743` | 동일 |

이 로직이 존재하는 유일한 이유 = `buyTargets[i].cur_price` 등을 `sectorStocks[code]`에서 **복사**해서 들고 있기 때문. 참조로 바꾸면 전부 사라짐.

### 1.4 목표

1. **052690 결함 해결**: 보유종목은 필터와 무관하게 마스터 캐시에서 시세 표시
2. **W3/P10 SSOT 준수**: 시세 단일 진실 소스 = 마스터 캐시. 파생 캐시 중복 저장 제거
3. **P24 단순성**: 파생 캐시 동기화 로직 7곳 제거
4. **사용자 원칙 1 구현**: 페이지별 구독 신청 → 백엔드가 신청한 페이지에만 push
5. **사용자 원칙 2 구현**: 마스터 캐시에 모든 실시간 종목 데이터 통합 (시세·호가·프로그램·뉴스)
6. **P23 일관성**: 보유·매수·섹터 세 페이지의 시세 표시 소스 통일
7. **DataTable O(1) 갱신 보존**: in-place mutation + updateItemByKey 성능 유지

---

## 2. 문제 + 현재 구조

### 2.1 현재 시세 데이터 흐름 (3곳 중복 저장)

```
백엔드 master_stocks_cache (전 종목, 시세 SSOT)
        │
   get_sector_stocks() — 5거래일 필터 (sector_min_trade_amt=200억)
        │
   sector-stocks-refresh WS 이벤트 (필터된 부분집합)
        │
   프론트 sectorStocks (부분집합) ← 시세 SSOT라 불리지만 실제는 부분집합
        │
   ┌────┴────────────────┬──────────────────┐
   │ (복사)              │ (직접 참조)        │ (직접 참조)
buyTargets.cur_price   sell-position.ts    sector-stock.ts
(파생 캐시)             cur_price 컬럼       전체 행
        │
   rebindBuyTargetsRealtime 등 7곳 동기화 로직
        │
   positions.cur_price (복사 — 표시용 08efb81 이전, 계산용 유지)
```

### 2.2 현재 WS 이벤트 → 상태 갱신 매트릭스

| WS 이벤트 | 갱신 상태 | 파생 캐시 동기화 |
|---|---|---|
| sector-stocks-refresh | sectorStocks 전체 교체 | ✅ rebindBuyTargetsRealtime |
| sector-stocks-delta | sectorStocks 증분 | ✅ rebindBuyTargetsRealtime |
| buy-targets-update | buyTargets 전체 교체 | ✅ sectorStocks 기준 재결합 |
| buy-targets-delta | buyTargets 증분 | ✅ sectorStocks 기준 재결합 |
| account-update | account + positions | ❌ (positions는 계산 전용) |
| real-data | sectorStocks + buyTargets + positions (in-place) | ✅ buyTargets 파생 동기화 |
| orderbook-update | buyTargets[].order_ratio (in-place) | ❌ (단일 소스) |
| program-update | buyTargets[].program_net_buy (in-place) | ❌ (단일 소스) |
| news-hit | buyTargets[].news_boost | ❌ (별도 캐시) |
| realtime-reset | sectorStocks/positions null화 | ✅ rebindBuyTargetsRealtime |

### 2.3 현재 페이지-상태 참조 매트릭스

| 페이지 | 표시 소스 | 계산 소스 | 필터 조건 |
|---|---|---|---|
| sell-position.ts | sectorStocks.cur_price (08efb81) | positions.cur_price (computePositionValuation) | 없음 |
| buy-target.ts | buyTargets 실시간 필드 (파생 캐시) | buyTargets.cur_price (1위 종목 수량) | 검색어 |
| sector-stock.ts | sectorStocks 전체 필드 | 없음 | 검색어, selectedSector, NXT-only |
| profit-detail.ts | sectorStocks (종목명) | positions.cur_price (computeHoldingsSummary) | 날짜, 종목 검색 |

### 2.4 사전조사 핵심 발견 (4개 병렬 조사 취합)

**조사 1 (프론트 파생 캐시 의존성)**:
- sectorStocks 참조 21곳, buyTargets 참조 16곳, positions.cur_price 참조 4곳
- rebindBuyTargetsRealtime 3곳 호출 (reset/refresh/delta)
- applyRealData 틱당 최대 3분기 갱신 (sectorStocks + buyTargets + positions)

**조사 2 (DataTable O(1) 갱신)**:
- DataTable currentRows가 객체 참조 보관, in-place mutation으로 O(1) 갱신
- buyTargets 실시간 필드는 "DataTable O(1) updateItemByKey 갱신을 위한 파생 캐시"
- **핵심**: 참조 기반으로 변경하면 O(1) 갱신 보존 가능 — 복사가 아니라 마스터 캐시 객체를 직접 참조

**조사 3 (백엔드 master_stocks_cache 소비자)**:
- master_stocks_cache는 백엔드 전체에서 실시간 종목 데이터 단일 소스
- sector-stocks-refresh는 필터된 부분집합만 전송 — 전 종목 전송 경로 부재
- 보유종목은 `subscribe_positions_stocks_realtime()`에서 필터 면제 별도 구독
- `get_all_sector_stocks()`는 전 종목 반환하지만 실시간 필드 없음 (업종분류 전용)

**조사 4 (매수후보 스코어·틱·리셋)**:
- order_ratio, program_net_buy, high_5d는 **이미 master_stocks_cache 단일 소스** (백엔드)
- news_boost, news_boost_title은 `news_boost_cache` 별도 캐시
- rank, guard_pass, reject_reason, boost_score는 `sector_summary_cache` 전용 (마스터 캐시 무관)
- 프론트에서만 buyTargets 파생 캐시로 중복 관리 → orderbook-update/program-update 이벤트와 동기화 로직 추가 존재

### 2.5 인터넷 검증 — 업계 표준과 일치 확인

| 소스 | 핵심 패턴 | 사용자 원칙과의 관계 |
|---|---|---|
| Bloomberg 시스템 설계 (chiraghasija.cc) | "subscription fan-out tree" — 좁은 허리(전 세계 시세 12MB)에서 per-symbol 구독 트리로 fan-out | 원칙 1·2 완전 일치 |
| Engineered.at (React 1000 updates/sec) | "external hot state store" + "row-level subscriptions" + frame-aligned flushing | 원칙 1 프론트 구현 패턴 일치 |
| Medium (WebSocket to Screen) | "WebSocket layer should not directly control UI" + "subscribe only to the specific snapshot they need" | 원칙 1 일치 |
| schwab-data-proxy (GitHub) | "Reference-counted subscriptions" — 0→1 전환 시 상위 구독, 1→0 시 해제 | 중복 구독 최적화 표준 해법 |
| GraphQL Subscriptions at Scale (Medium) | "subscription registry" — 동일 구독 그룹화, 50%+ 전송량 감소 | 동일 패턴 |

**현재 SectorFlow는 업계 표준에서 벗어난 구조** — Bloomberg/Engineered.at/schwab 모두 "단일 SSOT + 구독 기반 push"인데, SectorFlow만 "부분집합 SSOT + 파생 캐시 동기화".

---

## 3. 채택안 + 이유

### 채택 결정 1: 마스터 종목 캐시를 프론트 단일 시세 소스로 격상

**결정**: 백엔드 `master_stocks_cache`(이미 존재)를 프론트에 push로 전달하여 프론트 상태로 보관한다. 기존 `sectorStocks`는 마스터 캐시를 사용하면 사용처가 없어지므로 삭제한다. 시세·호가·프로그램·뉴스 등 종목 단위 실시간 데이터의 단일 진실 소스는 백엔드 `master_stocks_cache`이며, 프론트는 이를 전달받아 보관만 한다 (사용자 결정 1).

**왜**:
- W3 SSOT: "종목 정보: master_stocks_cache(메모리) → master_stocks_table(영속)" — 마스터 캐시가 종목 정보 SSOT. 현재 프론트 sectorStocks는 필터 부분집합이라 SSOT 위반.
- 052690 결함의 근본 해결: 전 종목을 들고 있으면 보유종목이 필터 미달이어도 누락되지 않음.
- P10 SSOT: 시세가 3곳 중복 저장(sectorStocks·buyTargets·positions) → 1곳(마스터 캐시)으로 통일.
- 업계 검증: Bloomberg "narrow waist"(전 세계 시세 12MB 상태 하나), Engineered.at "external hot state store" — 단일 SSOT가 업계 표준.

### 채택 결정 2: 페이지별 구독 신청 + 백엔드 참조 카운트 push 모델

**결정**: 각 페이지가 mount 시 백엔드에 "이 종목들의 실시간 데이터를 달라"고 신청하고, unmount 시 해제한다. 백엔드는 종목별로 구독 페이지 집합을 참조 카운트 맵으로 관리하여, 이벤트(틱/호가/PGM/뉴스) 발생 시 해당 종목을 구독 중인 페이지에만 push한다.

**왜**:
- 사용자 원칙 1: "각 페이지가 마스터 캐시를 직접 뒤지는 구조가 아니다. 각 페이지는 필요한 데이터를 백엔드에 미리 신청해 놓고, 백엔드는 이벤트 발생 시 신청한 페이지에만 해당 데이터를 전송한다."
- 업계 검증: schwab-data-proxy "Reference-counted subscriptions fire only on 0→1 transition, drop on 1→0", GraphQL Subscriptions "subscription registry grouped identical subscriptions" — 참조 카운트가 중복 구독 최적화 표준.
- P24 단순성: 페이지가 마스터 캐시 전체(약 2700종목)를 들고 직접 필터링하지 않음 — 자기 역할에 맞는 종목만 push받아 프론트 메모리·렌더링 부하 최소화.
- 기존 인프라 재사용: `notifyPageActive`/`notifyPageInactive`(`frontend/src/api/ws.ts:265-276`)가 이미 모든 페이지에 구현되어 있어 구독 신청 채널로 자연 확장. 백엔드 `ws.py`의 `page-active`/`page-inactive` 처리 로직도 이미 존재.

### 채택 결정 3: 마스터 캐시에 모든 실시간 종목 데이터 통합

**결정**: `master_stocks_cache`에 시세뿐 아니라 호가잔량비(order_ratio), 프로그램순매수(program_net_buy), 뉴스 가산점(news_boost, news_boost_title)을 필드로 통합한다. 이미 order_ratio·program_net_buy·high_5d는 마스터 캐시에 존재(조사 4 확인). news_boost만 `news_boost_cache`에서 마스터 캐시 필드로 이동.

**왜**:
- 사용자 원칙 2: "마스터 종목 캐시에는 시세뿐 아니라 뉴스, 프로그램 순매수, 호가 잔량 비율 등 실시간으로 변하는 모든 종목 데이터가 포함되어야 한다. 빠진 자리가 있다면 캐시에 추가해야 한다."
- P10 SSOT: 종목 단위 실시간 데이터가 한 곳에 통합. 현재 news_boost만 별도 캐시(`news_boost_cache`)로 분리되어 있어 종목 단위 데이터가 2곳에 분산.
- W4 파생 데이터 모델: "두 번째 데이터 저장소를 운영하는 대신 하나의 원본에서 파생" — news_boost_cache를 마스터 캐시 필드로 통합.
- 단, news_boost 만료 TTL 로직은 시세와 수명 주기가 다르므로 마스터 캐시 필드로 옮기되 만료 처리 로직은 그대로 유지 (필드 위치만 이동, 로직은 보존).

### 채택 결정 4: 파생 캐시(실시간 필드 복사) 전부 제거, 참조 기반 전환

**결정**: buyTargets의 실시간 필드(cur_price, change, change_rate, strength, trade_amount, order_ratio, program_net_buy)를 마스터 캐시에서 **복사**해서 들고 있지 않고, render 함수가 마스터 캐시에서 직접 참조. rebindBuyTargetsRealtime, applyOrderbookUpdate, applyProgramUpdate, applyRealData의 buyTargets 분기 등 동기화 로직 7곳 제거.

**왜**:
- P10 SSOT: 시세가 sectorStocks·buyTargets 2곳에 중복 저장 제거 → 마스터 캐시 1곳.
- P24 단순성: 동기화 로직 7곳 제거. rebindBuyTargetsRealtime 함수 자체 사라짐.
- P22 데이터 정합성: 복사본과 원본 사이에 불일치 윈도우 자체가 발생 불가 — 참조이므로 항상 동일.
- DataTable O(1) 갱신 보존(조사 2 재해석): buyTargets 배열 자체가 아니라 **실시간 필드 복사**를 삭제하는 것. buyTargets는 정적 스코어(rank, guard_pass 등)만 보관하고, render 함수가 마스터 캐시 객체를 참조. 마스터 캐시 객체 in-place mutation 시 updateItemByKey가 자동으로 최신 값 표시 — 객체 참조 유지 = O(1) 갱신 보존. 이 패턴은 sell-position.ts:31-41 종목명 컬럼이 이미 하고 있는 것(`sectorStocks[code].market_type` 참조).

### 채택 결정 5: positions.cur_price는 계산 전용으로 유지 (표시만 마스터 캐시로 전환)

**결정**: positions.cur_price 필드는 제거하지 않고 손익·평가·매도조건 계산 입력값으로 유지. 표시만 마스터 캐시에서. 이는 선행 설계 `08efb81` 결정 1·2를 그대로 계승.

**왜**:
- W7(시뮬레이터/증권사 응답 동일 구조): positions payload의 cur_price 필드는 증권사 REST 응답(kt00018)과 가상 시뮬레이터가 동일 구조로 유지해야 함. 필드 제거 시 W7 위반.
- P22 데이터 정합성: positions는 "돈 관련 수치"의 계산 입력값. 증권사 확정 체결가를 그대로 받아 저장하므로 계산용 SSOT 역할 유지.
- 역할 분리(선행 설계): 표시 소스 = 마스터 캐시, 계산 소스 = positions. 본 설계는 표시 소스를 sectorStocks(부분집합)에서 마스터 캐시(전 종목)로 교체할 뿐 역할 분리 원칙은 동일.

### 채택 결정 6: 기존 rAF 배칭 = Conflation으로 재해석·유지

**결정**: 현재 `applyRealData`의 rAF 배칭(requestAnimationFrame + dirty Set + 프레임당 1회 디스패치)은 업계 표준 conflation 패턴으로 그대로 유지. 단, 갱신 대상이 마스터 캐시 1곳으로 단순화.

**왜**:
- 업계 검증: Bloomberg "Conflation is the single most important lever on the read side" — tick마다 push하지 않고 심볼별 최신값만 유지하다 정해진 rate로 갱신.
- 현재 rAF 배칭이 이미 동일 역할 수행 — 60fps로 coalescing하여 초당 수백 틱을 프레임당 1회 디스패치.
- P24 단순성: 새로운 최적화 도입 없이 기존 구조 재사용.

---

## 4. 기각안 + 사유

| 기각안 | 기각 사유 |
|---|---|
| **A. 보유종목을 sectorStocks에 필터 면제로 포함** | 부분집합을 보유종목 기준으로 확장하면 매수/섹터 화면에도 보유종목이 섞여 들어감. 근본 해결이 아니라 증상 완화. 사용자 원칙 1(페이지별 구독) 위반 — 여전히 모든 페이지가 같은 부분집합을 바라봄 |
| **B. 프론트에 "전 종목 마스터 캐시" 상태를 별도 보관, 보유종목 표시만 이쪽 참조** | 사용자 구도에 가장 부합하나, 사용자 원칙 1("각 페이지가 마스터 캐시를 직접 뒤지는 구조가 아니다")에 반함. 프론트가 전 종목을 들고 직접 참조하면 페이지별 구독 신청 의미 상실. 메모리·렌더링 부하도 증가 (약 2700종목 전체 보관) |
| **C. 보유종목 표시만 positions.cur_price로 회귀 (08efb81 되돌림)** | P23 일관성 목표 포기. 보유종목만 positions 기반 표시를 쓰는 비일관성 복귀. 근본 원인(부분집합 SSOT 모순) 미해결 |
| **D. Redis Pub-Sub 도입으로 구독 관리** | 1인 로컬 단일 프로세스 구조(D1)에 외부 브로커 불필요. P5 위반. 백엔드 메모리 참조 카운트 맵으로 충분 |
| **E. 모든 데이터(정적 스코어 포함)를 마스터 캐시로 통합** | rank, guard_pass, reject_reason, boost_score는 sector_summary_cache가 SSOT이며 종목 단위 데이터가 아님(매수후보 선정 결과). 마스터 캐시는 "종목 단위 실시간 데이터"만 담당하는 역할 원칙 위반. P10 SSOT — 각 데이터는 자기 역할에 맞는 소스에서 |
| **F. news_boost를 마스터 캐시와 별도 캐시 양쪽에 유지** | 이중 SSOT 위반(P10). 통합하거나 유지하거나 하나만 선택 — 본 설계는 통합(결정 3) |

---

## 5. 영향 범위

> 개념 수준. 파일/라인 단위는 2세션 태스크 파일 영역 — 침범 금지.

### 5.1 백엔드 (중간 규모)

**신규 추가**:
- 종목별 구독 페이지 집합 관리자(참조 카운트 맵): `symbol → {page: refcount}` 구조. 0→1 전환 시 해당 종목 실시간 전송 시작, 1→0 시 해제.
- 페이지별 구독 신청 처리: 기존 `page-active`/`page-inactive` WS 메시지 확장 — 프론트가 종목 코드 목록을 직접 전송 (사용자 결정 2 — 백엔드가 페이지 이름으로 종목을 알아서 매핑하지 않음, 업계 표준 준수).
- 전 종목 마스터 캐시 payload 생성 함수: `get_all_sector_stocks()`에 실시간 필드 추가, 또는 별도 함수. snapshot(초기 전체) + delta(변경분) 전송.
- 틱/호가/PGM/뉴스 이벤트 발생 시 구독 페이지 라우팅: 마스터 캐시 갱신 후 해당 종목을 구독 중인 페이지에만 push.

**제거**:
- `orderbook-update`/`program-update` WS 이벤트의 프론트 전송 (백엔드 마스터 캐시 갱신만 유지, 프론트는 마스터 캐시 push로 갱신)
- `sector-stocks-refresh`/`sector-stocks-delta`의 필터 로직 (전 종목 전송으로 전환하거나, 페이지별 구독으로 대체)

**유지**:
- `master_stocks_cache` 갱신 경로(틱 수신·장마감 확정가·리셋) 그대로
- `news_boost_cache` 만료 TTL 로직 (필드 위치만 마스터 캐시로 이동, 만료 처리는 동일)
- 거래 로직·주문 경로·리스크 매니저 변경 없음

### 5.2 프론트 (큼 — 구조 변경)

**신규 추가**:
- 마스터 캐시 상태(전 종목): hotStore에 백엔드 `master_stocks_cache`를 push로 전달받아 보관 (신설 아님 — 백엔드 SSOT 전달). 상태 명칭은 태스크 파일에서 확정.
- 페이지별 구독 신청 로직: mount 시 백엔드에 종목 코드 목록 전송, unmount 시 해제. 기존 `notifyPageActive` 확장.
- `MasterStock` 타입: 시세 + 호가 + 프로그램 + 뉴스 필드 통합 (백엔드 master_stocks_cache 필드와 1:1 대응).

**제거**:
- `sectorStocks` 상태: 마스터 캐시를 사용하면 사용처가 없어지므로 삭제 (사용자 결정 1)
- `rebindBuyTargetsRealtime` 함수 및 호출 3곳
- `applyOrderbookUpdate`, `applyProgramUpdate` 함수
- `applyRealData`의 buyTargets 분기 (마스터 캐시 갱신만 남김)
- `applyBuyTargetsUpdate`/`applyBuyTargetsDelta`의 sectorStocks 재결합 분기
- buyTargets의 실시간 필드(cur_price, change, change_rate, strength, trade_amount, order_ratio, program_net_buy) — 매수 순위·차단·가산점 등은 각 페이지가 자체 계산 (사용자 결정 3 — 마스터 캐시는 공통 실시간 데이터만)
- `orderbook-update`/`program-update` 이벤트 핸들러 (binding.ts)

**수정**:
- `buy-target-columns.ts` render 함수: 마스터 캐시에서 시세 참조 (buyTargets[i].cur_price → masterCache[buyTargets[i].code].cur_price)
- `sell-position.ts` 현재가 컬럼: sectorStocks → masterCache 참조
- `sector-stock.ts`: sectorStocks → masterCache에서 필터 파생 (또는 페이지별 구독 결과 사용)
- `applyRealData`: 갱신 대상을 masterCache + positions 2곳으로 단순화 (기존 3곳)
- `applyRealtimeReset`: masterCache null화 + positions null화만 (rebind 제거)

**유지**:
- DataTable O(1) 갱신 메커니즘 (updateItemByKey, in-place mutation, rAF 배칭)
- positions.cur_price 계산용 사용 (computePositionValuation, computeHoldingsSummary)
- news-hit 이벤트 처리 (마스터 캐시 필드 갱신으로 변경, 로직은 유지)
- 페이지 전환 시 DataTable 재생성 패턴

### 5.3 DB/스키마

변경 없음. 마스터 캐시는 메모리 상태이며 `master_stocks_table`은 그대로. 실시간 필드(order_ratio, program_net_buy, news_boost)는 메모리 전용.

### 5.4 거래 로직

변경 없음. execute_buy/execute_sell, RiskManager, CircuitBreaker, 매수/매도 조건 계산 모두 그대로.

---

## 6. 동작 원리

> 본 설계는 상태 전이가 3개 이상(마스터 캐시 교체·리셋·틱 갱신·구독 신청/해지)이므로 동작 원리 명시.

### 6.1 전체 데이터 흐름 (전환 후)

```
백엔드 master_stocks_cache (전 종목, 모든 실시간 필드 통합)
  - 시세: cur_price, change, change_rate, strength, trade_amount
  - 호가: order_ratio
  - 프로그램: program_net_buy
  - 뉴스: news_boost, news_boost_title (만료 TTL 유지)
  - 정적: high_5d, name, sector, market_type, nxt_enable
        │
  페이지별 구독 채널 (mount 시 신청, unmount 시 해지)
  - 보유종목 페이지 → 보유 종목 코드를 직접 백엔드에 전송 (052690 포함 → 해결)
  - 매수후보 페이지 → 매수후보 종목 코드를 직접 백엔드에 전송
  - 섹터 페이지 → 필터 통과 종목 코드를 직접 백엔드에 전송
  ※ 프론트엔드가 종목 코드를 직접 지정 (사용자 결정 2, 업계 표준 준수)
  ※ 백엔드가 페이지 이름만 보고 알아서 매핑하지 않음
        │
  참조 카운트 맵: symbol → {page: refcount}
  - 0→1 전환 시 해당 종목 실시간 전송 시작
  - 1→0 시 전송 중단
  - 같은 종목이 여러 페이지에 필요하면 refcount로 중복 방지
        │
  이벤트 발생 시 (틱/호가/PGM/뉴스):
  1. 마스터 캐시 갱신 (단일 소스)
  2. 해당 종목을 구독 중인 페이지 집합 조회 (O(1) 맵 조회)
  3. 신청한 페이지에만 push (conflation = rAF 배칭)
        │
  ┌─────┴─────────────┬─────────────┐
  │                   │             │
보유종목 페이지      매수후보 페이지   섹터 페이지
(보유 종목 push)    (매수후보 push)  (필터 통과 push)
  │                   │             │
평가손익 계산       매수 순위·차단·  업종 점수 계산
(positions.cur_price 가산점 자체 계산  자체 계산 함수
 + 마스터 캐시)      (마스터 캐시      (마스터 캐시
                     시세 참조 +       시세 참조 +
                     자체 스코어)      자체 점수)
  │                   │             │
표시/요약           표시/랭킹        표시/분석

※ 마스터 캐시 = 공통 실시간 데이터만 (시세·호가·프로그램·뉴스)
※ 매수 순위·차단 여부·가산점·업종 점수 = 각 페이지가 자체 계산 (사용자 결정 3)
※ 업계 표준: "Separate market data from derived UI data" (Medium)
            "indicators are a client or separate-service concern" (Bloomberg)
```

### 6.2 상태 전이

**상태 1: 페이지 mount 시 구독 신청**
1. 페이지 mount → `notifyPageActive(page, codes)` 전송 (페이지 식별자 + **종목 코드 목록을 프론트가 직접 지정** — 사용자 결정 2, 업계 표준 준수)
2. 백엔드: 각 코드에 대해 refcount 맵 갱신 (해당 페이지 추가). 백엔드가 페이지 이름으로 종목을 알아서 매핑하지 않음 — 프론트가 전송한 코드 목록만 사용
3. 백엔드: 0→1 전환 종목에 대해 현재 마스터 캐시 값 snapshot 전송
4. 이후 해당 종목 이벤트 시 delta push

**상태 2: 틱/호가/PGM/뉴스 이벤트 발생**
1. 백엔드: 마스터 캐시 갱신 (단일 소스)
2. 백엔드: 해당 종목의 구독 페이지 집합 조회
3. 백엔드: 각 페이지에 push (conflation 적용 — rAF 배칭과 유사, 백엔드 단에서 프레임 단위 coalescing 또는 최신값만 전송)
4. 프론트: 마스터 캐시 상태 in-place mutation
5. 프론트: updateItemByKey(code)로 DataTable O(1) 갱신

**상태 3: 07:58 리셋**
1. 백엔드: `_reset_realtime_fields` — 마스터 캐시 실시간 필드 null화 + positions null화
2. 백엔드: 구독 중인 모든 페이지에 null화 push
3. 프론트: 마스터 캐시 null화 + positions null화
4. 프론트: DataTable 갱신 → '-' 표시 (rebindBuyTargetsRealtime 제거 — 참조 기반이므로 자동 동기화)

**상태 4: 페이지 unmount 시 구독 해지**
1. 페이지 unmount → `notifyPageInactive(page)` 전송
2. 백엔드: 해당 페이지가 구독한 모든 종목 refcount 감소
3. 백엔드: 1→0 전환 종목은 해당 종목 전송 중단

**상태 5: 페이지 전환 (보유 → 매수후보)**
1. 기존 페이지 unmount → 구독 해지
2. 새 페이지 mount → 새 종목 목록 구독 신청
3. 겹치는 종목(보유이면서 매수후보)은 refcount로 중복 방지 — 해지 후 재신청이 아니라 refcount 조정만

### 6.3 DataTable O(1) 갱신 보존 원리

현재: buyTargets[i] 객체를 DataTable currentRows가 참조 → in-place mutation으로 O(1) 갱신.

전환 후: buyTargets[i]는 정적 스코어만 보관, render 함수가 `masterCache[code].cur_price` 참조. masterCache[code] 객체 in-place mutation 시:
1. render 함수가 호출되면 최신 값 읽음 (참조이므로)
2. updateItemByKey(code)가 해당 행만 render() → 최신 값 표시
3. 객체 참조 유지 → O(1) 갱신 보존

이 패턴은 sell-position.ts:31-41 종목명 컬럼이 이미 사용 중 (`sectorStocks[code].market_type` 참조). 새로운 패턴 아님.

---

## 7. 아키텍처 원칙 부합표

| 원칙 | 부합 방식 |
|---|---|
| **P10 SSOT** | 시세·호가·프로그램·뉴스 등 종목 단위 실시간 데이터 = master_stocks_cache 단일 소스. 현재 sectorStocks(부분집합)·buyTargets(복사)·positions(복사) 3곳 중복 → 1곳 통일. 정적 스코어(rank 등)는 sector_summary_cache가 별도 SSOT (역할 분리 — 종목 단위 데이터 vs 매수후보 선정 결과) |
| **P16 살아있는 경로** | 제거되는 동기화 로직(rebindBuyTargetsRealtime 등)은 참조 기반 전환으로 더 이상 필요 없음 — dead code가 아니라 역할 자체가 소멸. 신규 구독 관리자는 실제 push 경로에 연결 |
| **P20 폴백 금지** | 마스터 캐시에 종목이 없거나 cur_price가 null → '-' 표시 (명시적 null 처리). positions.cur_price로 폴백하지 않음. 선행 설계 08efb81의 P20 준수 계승 |
| **P21 사용자 투명성** | 052690 결함 해결 — 보유종목이 필터 미달로 "-" 표시되는 사용자 불가해석 상황 제거. 모든 보유종목이 마스터 캐시에서 시세 표시 |
| **P22 데이터 정합성** | 복사본과 원본 사이 불일치 윈도우 자체 발생 불가 — 참조 기반이므로 항상 동일. rebindBuyTargetsRealtime이 제거되어도 정합성이 더 강화됨 (동기화 로직 실패 경로 자체 소멸) |
| **P23 일관성** | 보유·매수·섹터 세 페이지의 시세 표시 소스 = 마스터 캐시로 통일. 현재 보유종목만 sectorStocks(부분집합) 기반 표시의 비일관성 해소. 용어 사전 준수 — "마스터 종목 캐시" 단일 용어 사용 |
| **P24 단순성** | 동기화 로직 7곳 제거 (rebindBuyTargetsRealtime, applyOrderbookUpdate, applyProgramUpdate, applyRealData buyTargets 분기, applyBuyTargetsUpdate/Delta 재결합 분기). 신규 DB 컬럼 0, 신규 플래그 0. 구독 관리자는 기존 notifyPageActive 인프라 확장 |
| **P25 격리된 실패** | 한 페이지의 구독 신청 실패가 다른 페이지에 영향 주지 않음 (페이지별 독립 구독). 마스터 캐시 참조 실패 시 해당 종목만 '-' 표시, 전체 화면 중단 없음 (선행 설계 계승) |
| **W3 단일 소스 진리** | "종목 정보: master_stocks_cache" 원칙 정확 구현. 현재 프론트 sectorStocks가 필터 부분집합이면서 SSOT라 불리는 모순 해소 |
| **W4 파생 데이터 모델** | "두 번째 데이터 저장소 대신 하나의 원본에서 파생" — buyTargets 실시간 필드 복사(중복 저장) 제거, 참조(파생)로 전환. news_boost_cache를 마스터 캐시 필드로 통합 |
| **W7 시뮬레이터/증권사 응답 동일 구조** | positions payload의 cur_price 필드 유지 (계산용). 증권사 REST 응답 구조 변경 없음. 백엔드 마스터 캐시 갱신 경로도 테스트/실전 동일 |
| **W11 표현 통일** | "마스터 종목 캐시" 단일 용어 사용. "sectorStocks" 용어는 전 종목 마스터 캐시로 흡수되거나 페이지별 구독 결과로 재정의 |

---

## 8. 위험도 산정

**위험도: 중간**

근거:
- 프론트 구조 변경 범위가 큼 (hotStore, binding, 3개 페이지, types, buy-target-columns)
- 백엔드 WS 이벤트 신설·제거 동반
- 핵심 아키텍처 원칙(W3/P10) 수정 수반
- 단, 거래 로직·DB·주문 경로 변경 없음 → 실전 돈 위험 없음
- DataTable O(1) 갱신은 참조 기반으로 보존 가능 (조사 2 확인) → 성능 위험 낮음

**비개발자용 3줄 요약**:
- 보유종목 화면에서 특정 종목(한전기술)만 가격이 "-"로 표시되는 문제의 근본 해결.
- 시세 데이터의 원본을 하나로 통일하고, 각 화면이 필요한 종목만 백엔드에 요청해서 받는 구조로 전환.
- 거래·주문 로직은 건드리지 않으므로 실전 돈 위험은 없음. 화면 표시 구조 변경이 주요 위험.

**검증·관찰 계층 게이트 적용**: 위험도 '중간'이므로 사전 롤백 계획 필수, 모의 관찰 권장.

---

## 9. 완료 기준 (사용자 관점 수용 조건)

> 검증의 최종 판정 기준 (AGENTS.md 섹션4 "문서 역할 원칙" — 검증=설계 완료기준 따른다). 태스크 완료 조건은 여기서 파생.

### 9.1 052690 결함 해결
- [ ] 한전기술(052690) 보유종목 화면 현재가가 정상 표시 (마스터 캐시에서 87400 등 확정가/실시간가 표시)
- [ ] 5일평균 거래대금 200억 미달 종목이 보유종목일 경우에도 가격 정상 표시

### 9.2 단일 시세 소스
- [ ] 보유·매수·섹터 세 페이지의 현재가 표시 소스가 모두 마스터 종목 캐시 (P23 일관성)
- [ ] 시세 데이터가 프론트에 1곳(마스터 캐시)에만 존재 (P10 SSOT — buyTargets 실시간 필드 복사 제거 확인)

### 9.3 파생 캐시 동기화 로직 제거
- [ ] rebindBuyTargetsRealtime 함수 및 호출 3곳 제거
- [ ] applyOrderbookUpdate, applyProgramUpdate 함수 제거
- [ ] applyRealData의 buyTargets 분기 제거 (마스터 캐시 + positions 2곳만 갱신)
- [ ] orderbook-update/program-update WS 이벤트 핸들러 제거 (binding.ts)

### 9.4 페이지별 구독
- [ ] 페이지 mount 시 백엔드에 종목 코드 목록을 프론트가 직접 전송하여 구독 신청 (사용자 결정 2 — 백엔드가 페이지 이름으로 알아서 매핑하지 않음)
- [ ] 페이지 unmount 시 구독 해지 전송
- [ ] 같은 종목을 여러 페이지가 구독할 때 참조 카운트로 중복 전송 방지

### 9.5 마스터 캐시 통합 (공통 실시간 데이터만)
- [ ] news_boost, news_boost_title이 마스터 캐시 필드로 통합 (news_boost_cache 제거)
- [ ] order_ratio, program_net_buy, high_5d가 마스터 캐시에서 참조 (기존 유지)
- [ ] 마스터 캐시에 매수 순위·차단 여부·가산점·업종 점수가 포함되지 않음 (사용자 결정 3 — 공통 실시간 데이터만)
- [ ] 매수 순위·차단 여부·가산점·업종 점수가 각 페이지의 자체 계산 함수로 산출됨 (마스터 캐시 참조 아님)

### 9.6 성능 보존
- [ ] DataTable O(1) 갱신 유지 — 틱 수신 시 updateItemByKey로 단일 행 갱신
- [ ] rAF 배칭 유지 — 60fps 유지, 초당 수백 틱 처리 가능

### 9.7 리셋 정합성
- [ ] 07:58 리셋 후 첫 틱 전까지 보유·매수·섹터 모든 페이지 현재가 '-' 표시
- [ ] 첫 틱 수신 후 실시간 값으로 전환
- [ ] rebindBuyTargetsRealtime 제거 후에도 리셋 정합성 유지 (참조 기반 자동 동기화)

### 9.8 계산 경로 유지
- [ ] positions.cur_price가 손익·평가·매도조건 계산에 계속 사용 (computePositionValuation, computeHoldingsSummary)
- [ ] 비실시간 구간 평가손익/수익률 '-' 표시 (positions.cur_price=null → isNull=true)
- [ ] 매수후보 정적 스코어(rank, guard_pass, reject_reason, boost_score)가 sector_summary_cache에서 계속 공급

### 9.9 거래 로직 무변경
- [ ] execute_buy/execute_sell, RiskManager, CircuitBreaker 변경 없음
- [ ] 매수/매도 조건 계산 로직 변경 없음
- [ ] 주문 경로(P15) 단일 경로 유지

---

## 10. 사전 롤백 계획 (위험도 '중간' — 필수)

> "검증·관찰 계층 게이트" 연계. 문제 발생 시 코딩을 모르는 사용자가 즉시 실행할 수 있도록.

### 10.1 롤백 명령
- `git revert <구현 커밋 해시>` — 구현 완료 후 커밋 해시 기재

### 10.2 즉시 롤백 트리거 (다음 중 하나 발생 시)
- 보유종목 화면에서 가격이 "-"로 표시되는 종목이 이전보다 많아짐 (052690 외 다수 종목 누락)
- 매수후보 화면 랭킹 순서가 이전과 달라짐 (정적 스코어 참조 경로 깨짐 의미)
- 실시간 틱 수신 시 화면이 끊기거나 멈춤 (DataTable O(1) 갱신 경로 깨짐 의미)
- 07:58 리셋 후 가격이 '-'로 표시되지 않고 이전 값 잔류 (리셋 정합성 깨짐)
- 자동매수/자동매도가 이전과 다르게 동작 (거래 로직에 영향 전파 의미)

### 10.3 관찰 기준 (위험도 '중간' — 모의 관찰 권장)
- 모의투자/test 모드에서 최소 1거래일 관찰
- 확인 항목:
  - 보유종목 화면: 모든 보유 종목 가격 표시 (이전 "-"였던 052690 포함)
  - 매수후보 화면: 랭킹·가격·호가·프로그램·뉴스 컬럼 정상 표시
  - 섹터 화면: 필터 통과 종목 가격 정상 표시
  - 07:58 리셋 → 첫 틱 전 '-' → 첫 틱 후 실시간가 전환
  - 페이지 전환(보유↔매수↔섹터) 시 가격 표시 끊김 없음

---

## 11. 사용자 결정 항목

> problem-solve 섹션 1-1 의무. 사전조사(코드/설정/기존 패턴)로 확정 불가한 항목만. 2세션 태스크 파일에서 활용.

### 결정 1: 백엔드 마스터 캐시를 프론트에 전달, sectorStocks 삭제 — 사용자 결정 완료

**사용자 결정**: "백엔드 캐시에 마스터종목 캐시가 있는데 왜 신설을 하지? 단지 확인할 건 마스터종목 캐시를 사용하면 섹터스톡 캐시는 사용처가 없으면 삭제하는 거야."

→ **백엔드 `master_stocks_cache`를 프론트에 push로 전달하여 프론트 상태로 보관** (신설 아님 — 백엔드 SSOT를 전달받는 것). **`sectorStocks`는 마스터 캐시를 사용하면 사용처가 없어지므로 삭제**.

**설계서 정정**: 본 설계서에서 "프론트에 전 종목 마스터 캐시 상태를 신설"이라고 표현한 부분은 오해의 소지가 있었음. 정확히는 백엔드 `master_stocks_cache`(이미 존재)를 프론트에 push로 전달하여 프론트 상태로 보관하는 것 — 신규 생성이 아님.

**구조 확정**:
- 백엔드 `master_stocks_cache`: 이미 존재 (전 종목, 모든 실시간 필드 통합 — 결정 3에 따라 공통 실시간 데이터만)
- 프론트 상태: 백엔드에서 push받은 마스터 캐시 데이터를 보관 (이름은 태스크 파일에서 확정 — `masterCache` 또는 기존 `sectorStocks` 재활용 여부 등)
- `sectorStocks`: 마스터 캐시를 사용하면 사용처가 없어지므로 삭제
- 섹터 화면: 마스터 캐시에서 필터 파생 (또는 페이지별 구독 결과 사용)

**태스크 파일에서 다룰 세부 사항**: 프론트 상태의 명칭(masterCache 등), 기존 sectorStocks 참조처의 마이그레이션 경로, 섹터 화면 필터 로직 위치.

### 결정 2: 페이지별 구독 신청 시 종목 코드 전송 방식 — 사용자 결정 완료

**사용자 결정**: "프론트엔드가 필요한 종목 코드를 직접 백엔드에 구독 신청하는 방식으로 한다. 백엔드가 페이지 이름만 보고 알아서 매핑하는 방식은 안 된다."

→ **옵션 A 또는 B 채택** (프론트가 종목 코드를 직접 전송). **옵션 C 기각** (백엔드가 페이지 이름으로 종목을 알아서 매핑하는 방식은 안 됨).

**업계 표준 검증 — 사용자 결정과 완전 일치**:

| 소스 | 클라이언트 전송 형식 | 페이지 이름만 전송? |
|---|---|---|
| Bloomberg BLPAPI | `SubscriptionList.add(topic, ...)` — 클라이언트가 subscription string(심볼) 직접 지정 | ❌ |
| Alpaca WebSocket | `{"action":"subscribe","trades":["FAKEPACA"]}` — 심볼 배열 직접 전송 | ❌ |
| Robinhood/E*TRADE HLD | `{"action":"subscribe","symbols":["AAPL","TSLA","NVDA"]}` — 심볼 직접 지정 | ❌ |
| Paxos Smart Order Routing | `{"type":"subscribe","channels":[{"type":"market_data","params":{"market":"BTCUSD"}}]}` — 마켓(심볼) 직접 지정 | ❌ |
| GraphQL Subscriptions (Apollo/Relay) | `subscription($repoName:String!){commentAdded(repoFullName:$repoName)}` — 변수로 심볼 지정 | ❌ |
| MarketMux/fanout-gateway | readPump가 "subscriptions/unsubscriptions" 제어 메시지 처리 — 클라이언트 구독 신청 | ❌ |

**검증 결론**: 검증한 6개 업계 표준 소스 중 어느 곳도 "페이지 이름만 보내면 백엔드가 알아서 매핑"하는 방식을 사용하지 않음. 모든 소스가 클라이언트가 심볼(종목)을 직접 지정하여 구독 신청. 사용자 결정이 업계 표준과 완전 일치.

**남은 세부 선택 (A vs B)**: 태스크 파일 작성 시 확정.
- A: 기존 `notifyPageActive(page)`를 `notifyPageActive(page, codes)`로 확장 (단일 메시지)
- B: `notifyPageActive(page)`는 그대로, 별도로 `{type: 'subscribe', codes: [...]}` 메시지 추가 (역할 분리)

둘 다 "프론트가 종목 코드를 직접 전송"한다는 사용자 결정을 준수하므로, 태스크 파일에서 기존 인프라 재사용 관점에서 A/B 중 선택.

### 결정 3: 매수 순위·차단 여부·가산점·업종 점수 등 페이지별 계산 데이터의 처리 방식 — 사용자 결정 완료

**사용자 결정**: "마스터 종목 캐시에 들어가는 건 공통 실시간 데이터(시세, 호가, 프로그램, 뉴스)뿐이다. 매수 순위, 차단 여부, 가산점, 업종 점수 등은 페이지마다 계산 방식이 다르다. 이것들은 마스터 캐시에 넣지 않고, 각 페이지가 자체 계산 함수로 산출한다."

→ **마스터 캐시 = 공통 실시간 데이터만** (시세·호가·프로그램·뉴스). **매수 순위·차단 여부·가산점·업종 점수 등 = 각 페이지가 자체 계산 함수로 산출** (마스터 캐시에 넣지 않음).

**업계 표준 검증 — 사용자 결정과 완전 일치**:

| 소스 | 핵심 패턴 | 사용자 결정과의 관계 |
|---|---|---|
| Medium "From WebSocket to Screen" | **"Separate market data from derived UI data"** — "A common mistake is mixing raw market data and derived display data in the same state". Raw data: price/volume/bid/ask. Derived data: formatted price/color/percentage/portfolio value. "Keep raw data clean. Derive display values close to where they are needed." | 완전 일치 — 공통 실시간 데이터(raw)와 페이지별 계산(derived) 분리 |
| Bloomberg 시스템 설계 | "Deep analytics (technical indicators computed server-side, backtesting, options greeks). Charts serve raw OHLCV; **indicators are a client or separate-service concern** that reads the same candle store." | 완전 일치 — 시세는 공통, 분석 지표는 클라이언트/별도 서비스에서 |
| Trading Market Data Pipeline Architecture | "treats raw events, normalized candles, and **derived features as distinct, replayable data products**" | 완전 일치 — raw와 derived를 명확히 분리 |
| Low-Latency Market Data Feeds | "best effort path for analytics and hard SLO path for execution-critical consumers" — raw와 analytics 경로 분리 | 완전 일치 — 공통 데이터와 파생 분석의 경로 분리 |
| Compliant Auditable Pipelines | "isolate the pipeline into discrete stages: raw ingestion, canonicalization, enrichment, **calculation, and publication**" — 계산 단계가 별도 | 완전 일치 — 계산은 별도 단계 |

**검증 결론**: 검증한 5개 업계 표준 소스 모두 "공통 raw 데이터"와 "페이지/소비자별 derived 계산"의 분리를 강조. 특히 Medium "From WebSocket to Screen"은 "raw market data와 derived UI data를 같은 state에 섞는 것은 흔한 실수"라고 명시. 사용자 결정이 업계 표준과 완전 일치.

**설계서 반영 사항**:
- 마스터 캐시 필드: 시세(cur_price, change, change_rate, strength, trade_amount) + 호가(order_ratio) + 프로그램(program_net_buy) + 뉴스(news_boost, news_boost_title) + 정적 메타(high_5d, name, sector, market_type, nxt_enable)만
- 매수 순위(rank), 차단 여부(guard_pass, reject_reason), 가산점(boost_score), 업종 점수(sectorScores)는 마스터 캐시에 넣지 않음 — 각 페이지가 자체 계산 함수로 산출
- 이는 기존 사전조사 4 결과와 일치: rank/guard_pass/reject_reason/boost_score는 `sector_summary_cache`가 SSOT이며 마스터 캐시와 무관. 사용자 결정은 이 구조를 명시적으로 확정한 것.

**태스크 파일에서 다룰 세부 사항**: 각 페이지의 자체 계산 함수가 어디서 입력 데이터를 받는지 (예: 매수후보 페이지는 sector_summary_cache 기반 스코어 + 마스터 캐시 기반 시세를 결합). 이는 태스크 파일 작성 시 구현 수준에서 확정.

---

## 12. 다음 세션 인계

**다음 세션 예정**: 2세션 — 심층 사전조사(태스크 파일 기반) + 태스크 파일 작성 (`docs/plan_master_cache_single_source.md`)

**설계서 경로**: `docs/architecture_master_cache_single_source_design.md` (본 파일)

**사전조사 4건 결과**: 본 설계서 섹션 2.4에 취합. 상세는 세션 기록(서브에이전트 agent_id: 4e9b2173, 803da213, 78ec7764, 68fbeb56) 참조 가능하나 본 설계서에 핵심 반영 완료.

**인터넷 검증 결과**: 본 설계서 섹션 2.5에 취합. 업계 표준과 사용자 원칙 일치 확인.

**사용자 결정 대기 항목**: 섹션 11 (결정 1·2·3) — 태스크 파일 작성 전 사용자 응답 필요.
