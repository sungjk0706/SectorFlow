# 설계서: 보유종목 실시간 단일 파이프라인 통합

> **상태**: 설계 완료 — 다음 세션에서 태스크 파일 작성 대기
> **작성일**: 2026-08-01
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패)
> **관련 파일**: `backend/app/services/engine_ws_reg.py` · `backend/app/services/engine_radar.py` · `backend/app/services/engine_account.py` · `backend/app/services/engine_account_rest.py` · `backend/app/services/sector_data_provider.py` · `backend/app/services/engine_sector_confirm.py` · `backend/app/services/market_close_pipeline.py` · `backend/app/pipelines/pipeline_compute_tick_handlers.py` · `backend/app/services/engine_cache.py`
> **선행 세션**: 커밋 `9c737f9` (보유종목 현재가 배선 교정 — 증상 치료)

---

## 1. 배경 및 목표

### 1.1 사용자 진단 (전제)

> "1차 필터링 5거래일 평균 거래대금 최소 N억원을 통과한 종목들 중 보유 중인 종목이 없으면 추가 구독해서 같은 실시간 파이프라인으로 실시간 틱을 수신하는 게 정상적 아키텍처다. 1차 필터링의 책임은 구독 대상 선정에서 끝나야 하는데, 그 이후 로직들에 여기저기 혼재되어 있다."

> "현재는 1차 필터링 통과 종목들과 별개로 보유종목 구독 신청을 별개로 해서 개별 다른 파이프라인을 사용하는 것 같다. 그런 로직·아키텍처는 잘못된 것 같다."

### 1.2 목표 (사용자 관점)

1. **보유종목은 도메인 정의상 시세 추적 대상** — 1차 필터링(5일평균거래대금) 통과 여부와 무관하게 실시간 틱을 수신·갱신·화면 전파.
2. **단일 실시간 파이프라인** — 보유종목과 매수후보가 동일한 틱 수신 → 캐시 갱신 → 화면 전파 경로를 사용. 별도 우회 파이프라인 제거.
3. **1차 필터링 책임 분리** — "5일평균거래대금 N억 이상" 필터링은 구독 대상 선정(+업종 점수 계산)에만 사용. 보유종목 시세 추적에는 영향을 주지 않음.

### 1.3 비목표 (다루지 않는 것)

- 1차 필터링 로직 자체(`filter_by_avg_amt`) 변경 없음 — 임계값·단위 변환 그대로 유지.
- 2단계 매매부적격종목 필터링(`evaluate_stock_filter`) 변경 없음 — 관리종목·거래정지 등 매매 부적격 판정은 별도 도메인.
- 매수후보 파이프라인 변경 없음 — 조사 결과 매수후보는 이미 단일 파이프라인 구조 (우회 없음).
- priceStore 통합 리팩토링(Option A) — 본 설계와 별개. 틱 핸들러 3곳 쓰기(sectorStocks/buyTargets/positions) 통합은 독립 논의 대상.
- REST 기반 계좌 부트스트랩 자체 제거 안 함 — 기동 시 1회 잔고·수량·매입가 확정값 조회는 실전 모드에서 필요(AGENTS.md "실전 모드: 증권사가 SSOT"). 다만 틱 기반 cur_price 갱신과의 관계 정리가 본 설계 범위.

---

## 2. 조사 결과 (현재 구조 정밀 분석)

### 2.1 전체 종목 로드 → 1차 필터링 → 구독 흐름

```
앱 기동
  → engine_cache.py: _load_caches_preboot()
      → stock_tables.py: load_master_stocks_table()
          → DB master_stocks_table 전체(~1300개) → master_stocks_cache (메모리)
  → recompute_sector_summary_now()
      → sector_data_provider.py:298-305 — _filtered 플래그 마킹
          (1차 필터 통과: _filtered=True, 탈락: _filtered 키 제거, 캐시에는 유지)
  → subscribe_sector_stocks_0b()
      → 보유종목 선행 REG (124-130줄)
      → _filtered=True 종목 누적 REG (141-156줄)
```

### 2.2 핵심 발견: 핸드오버 기록과 실제 코드의 불일치

**핸드오버 기록** (2026-07-31):
> "현재 필터 탈락 종목(예: 052690)은 `market_close_pipeline.py:867-869`에서 master_stocks_cache에서 삭제됨"

**실제 코드 조사 결과**:
- `market_close_pipeline.py:867-869`에서 삭제되는 것은 **2단계 매매부적격종목 필터링 탈락 종목**임 (관리종목·거래정지·우선주·스팩 등).
- **1차 필터링(5일평균거래대금) 탈락 종목은 master_stocks_cache에서 삭제되지 않고 유지됨** — 단지 `_filtered` 플래그만 제거됨.
- 052690 한전기술(5일평균 197억 < 200억)은 1차 필터링 탈락이므로 **master_stocks_cache에 존재**했음.

**이전 세션 052690 버그의 실제 원인 재해석**:
- master_stocks_cache에 052690이 존재했으므로, 틱 수신 시 `engine_radar.py:65-67`에서 스킵되지 않았을 것.
- `apply_last_price_to_positions_inplace`도 positions에 052690이 있으면 정상 갱신했을 것.
- **진짜 문제는 화면이 `sectorStocks`(get_sector_stocks() 결과, 1차 필터 통과 종목만 포함)에서 현재가를 읽었다는 것** — 이전 세션의 "배선 교정"이 정확한 증상 치료였음.
- 하지만 **근본 구조 문제는 별도로 존재** (아래 2.3~2.5 참조).

### 2.3 실제 구조 문제 3건

#### 문제 A: 보유종목 0D/PGM 구독 누락

| 항목 | 0B/01 (체결) | 0D (호가잔량) | PGM (프로그램순매수) |
|------|-------------|--------------|---------------------|
| 매수후보 | subscribe_sector_stocks_0b (기본 구독) | sync_dynamic_subscriptions (guard_pass=True만) | sync_dynamic_subscriptions (guard_pass=True만) |
| 보유종목 | subscribe_sector_stocks_0b (별도 선행 REG) | **구독 안 됨** (buy_targets의 guard_pass 아니면) | **구독 안 됨** (동일) |

- `sync_dynamic_subscriptions` (`engine_sector_confirm.py:267-302`)는 `new_buy_targets`에서 `guard_pass=True`인 종목만 0D/PGM 구독 대상으로 선정.
- 보유종목이 buy_targets에 포함되지 않거나 guard_pass=False이면 0D/PGM 틱을 수신하지 못함.
- 보유종목 화면에 호가잔량비·프.순.매 표시가 누락될 수 있음 (P21 사용자 투명성 위반).

#### 문제 B: 2단계 매매부적격 필터링 탈락 보유종목의 master_stocks_cache 삭제

- `market_close_pipeline.py:867-869`: `confirmed_codes`(2단계 필터 통과)에 없는 종목을 master_stocks_cache에서 삭제.
- 보유종목이 매매부적격(관리종목·거래정지 등)으로 판정되면 master_stocks_cache에서 삭제 → 틱 수신 시 `engine_radar.py:65-67`에서 스킵.
- 거래정지 종목은 틱 자체가 안 올 수 있으나, 관리종목·감리지정 등은 틱이 정상 수신됨에도 캐시 부재로 스킵.
- **보유종목은 도메인상 시세 추적 대상이므로 매매 적격 여부와 무관하게 캐시에 유지되어야 함** (P20 폴백이 아닌 명시적 도메인 조건).

#### 문제 C: REST 기반 보유종목 갱신과 틱 기반 갱신의 이중 경로 (P10 SSOT 위반)

| 경로 | 함수 | 트리거 | 갱신 대상 | cur_price 출처 |
|------|------|--------|-----------|---------------|
| **틱 기반 (정상)** | `apply_last_price_to_positions_inplace` | 0B/01 틱 수신 시 | `state.positions[i].cur_price` | 틱 체결가 (실시간) |
| **REST 기반 (우회)** | `_merge_positions_from_rest` → `state.positions = merged` | 기동 1회 + WS 재연결 + broker 변경 | `state.positions` 통째로 덮어쓰기 | REST kt00018 응답 `cur_pric` |

- REST 기반 갱신은 `state.positions`를 **통째로 덮어쓰기** (`engine_account.py:237`) → 틱 기반으로 갱신된 cur_price/pnl/rate가 REST 응답값으로 교체됨.
- 기동 시 1회는 부트스트랩으로 정상이나, **WS 재연결 시 재실행**되면 직전까지 틱으로 유지되던 실시간 값이 REST 값(수 분 전 데이터)으로 퇴행.
- 두 경로가 `state.positions`를 동시에 갱신하므로 어느 것이 SSOT인지 모호 (P10 위반).

### 2.4 보유종목 구독 신청의 구조 (오해 정정)

사용자 인식: "별개로 보유종목 구독신청을 별개로 해서 개별 다른 파이프라인을 사용"

실제 코드: `subscribe_sector_stocks_0b` (`engine_ws_reg.py:70-156`) 내에서 보유종목과 필터 통과 종목이 **같은 함수**에서 처리됨. 다만:
- 보유종목이 **선행 REG** (124-130줄) → 필터 통과 종목이 **누적 REG** (141-156줄)로 순서만 다름.
- 구독 신청 자체는 동일한 `ws.subscribe_stocks()` 호출 → 동일한 WS 파이프라인.
- **"별개 파이프라인"이 아니라 "같은 파이프라인 내 순서 분리"** — 사용자 인식과 코드가 부분적으로 다름.

다만 **REST 기반 갱신 경로(문제 C)는 실제로 별개 파이프라인**이 맞음. 틱 기반과 REST 기반이 분리되어 있으므로 사용자 진단의 본질은 유효.

### 2.5 틱 핸들러 캐시 부재 스킵 지점 전수

| 틱 종류 | 파일 | 줄번호 | 스킵 조건 |
|---------|------|--------|-----------|
| 0B/01 (체결) | `engine_radar.py` | 65-67 | `master_stocks_cache.get(nk)` → None 시 return |
| 0D (호가) | `pipeline_compute_tick_handlers.py` | 295-297 | `nk not in cache` → warning + return |
| PGM (순매수) | `pipeline_compute_tick_handlers.py` | 338-340 | `nk not in cache` → warning + return |

- 0B/01은 보유종목이 1차 필터링 탈락해도 캐시에 있으므로 스킵되지 않음 (정상).
- 0D/PGM은 보유종목이 buy_targets의 guard_pass가 아니면 구독 자체가 안 되어 틱이 수신되지 않음 (문제 A).
- 2단계 필터링 탈락 보유종목은 캐시에서 삭제되므로 모든 틱이 스킵됨 (문제 B).

---

## 3. 설계 방향

### 3.1 핵심 설계 결정

**결정 1: 보유종목은 1차 필터링과 무관하게 단일 실시간 파이프라인에 포함**

- 근거: 보유종목은 도메인 정의상 "시세 추적 대상" — 사용자가 보유 중인 종목의 현재가·손익을 실시간으로 봐야 하는 것은 필터링 조건과 무관한 기본 요구.
- P20(폴백 금지) 위반 아님: "보유종목은 시세 추적 대상"은 명시적 도메인 조건이지 빈 값/None에 대한 폴백이 아님.
- 1차 필터링의 책임은 "매수후보 선정용 구독 대상" + "업종 점수 계산 대상"으로 한정. 보유종목 시세 추적은 별도 도메인 조건.

**결정 2: 보유종목 0D/PGM 구독을 0B 구독과 동일하게 보장**

- 근거: 보유종목 화면에 호가잔량비·프.순.매가 표시되지 않으면 P21(사용자 투명성) 위반 — "왜 내 보유종목은 호가잔량비가 없지?" 
- 현재 0B는 보유종목 선행 REG로 보장되나, 0D/PGM은 buy_targets의 guard_pass에만 연동 → 보유종목 누락.
- `sync_dynamic_subscriptions`에 보유종목 코드를 guard_pass와 별도로 포함.

**결정 3: 2단계 매매부적격 필터링 탈락 보유종목을 master_stocks_cache에 유지**

- 근거: 매매 부적격(관리종목 등)은 "신규 매수 불가"를 의미할 뿐 "시세 추적 불가"를 의미하지 않음. 보유 중인 종목의 시세는 계속 추적해야 함.
- `market_close_pipeline.py:867-869`의 삭제 조건에 보유종목 제외 조건 추가.
- P22(데이터 정합성): 보유종목이 캐시에서 사라지면 틱 수신 시 스킵 → cur_price 갱신 누락 → 화면에 옛날 값 또는 빈 값 표시.

**결정 4: REST 기반 positions 덮어쓰기를 틱 기반 갱신과 분리 (P10 SSOT 정합)**

- 현재: REST 갱신이 `state.positions`를 통째로 덮어쓰기 → 틱 기반 cur_price/pnl/rate가 REST 값으로 교체.
- 설계: REST 부트스트랩은 "수량·매입가·종목명·수수료" 등 **확정값 필드만 갱신**, cur_price/pnl/rate/eval_amount 등 **실시간 파생 필드는 틱 기반 갱신이 우선**.
- 단, 기동 시 첫 부트스트랩에서는 cur_price를 REST 값으로 초기화 (틱 수신 전이므로). 이후 틱 수신 시작 시 틱 값으로 전환.
- WS 재연결 시: REST 재조회 후 positions를 통째로 덮어쓰지 않고, 수량·매입가 등 확정 필드만 머지 (틱 기반 cur_price 보존).

### 3.2 설계 범위 매트릭스

| 문제 | 설계 결정 | 수정 파일 | 수정 규모 |
|------|-----------|-----------|-----------|
| A: 0D/PGM 구독 누락 | 결정 2 | engine_sector_confirm.py | 중 |
| B: 2단계 필터 탈락 보유종목 캐시 삭제 | 결정 3 | market_close_pipeline.py | 소 |
| C: REST positions 덮어쓰기 | 결정 4 | engine_account.py, engine_account_rest.py | 중 |
| —: 1차 필터링 책임 분리 (이미 부분 구현) | 결정 1 | (문서화·주석 정리) | 소 |

---

## 4. 상세 설계

### 4.1 결정 2: 보유종목 0D/PGM 구독 보장

**현재** (`engine_sector_confirm.py:282`):
```python
new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}
```

**설계**:
```python
# guard_pass 매수후보 + 보유종목을 모두 0D/PGM 구독 대상에 포함
held_codes = await engine_account.get_held_codes()
new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass} | held_codes
```

- `get_held_codes()`는 이미 구현되어 있음 (`engine_account.py:406-421`).
- 보유종목이 buy_targets에 포함되어 있으면 중복 추가되지 않음 (set 연산).
- 해지 시 보유종목은 해지 대상에서 제외 (이미 보유종목이 new_codes에 있으므로 자연 제외).

**주의**: `_flush_unreg_batch` (`engine_sector_confirm.py:350-392`)에서 해지 시 보유종목이 해지되지 않도록 보장 필요. 현재 `current_codes`에서 `to_unreg = codes & current_codes` 계산 시 보유종목이 codes에 없으면 해지되지 않으나, 보유종목이 codes에 들어가는 시나리오 검토 필요.

### 4.2 결정 3: 2단계 필터 탈락 보유종목 캐시 유지

**현재** (`market_close_pipeline.py:867-869`):
```python
keys_to_delete = [cd for cd in list(engine_state.state.master_stocks_cache.keys()) if cd not in confirmed_codes]
for cd in keys_to_delete:
    engine_state.state.master_stocks_cache.pop(cd, None)
```

**설계**:
```python
# 보유종목은 매매 부적격 여부와 무관하게 캐시에 유지 (시세 추적 대상)
held_codes = await engine_account.get_held_codes()
keys_to_delete = [
    cd for cd in list(engine_state.state.master_stocks_cache.keys())
    if cd not in confirmed_codes and cd not in held_codes
]
for cd in keys_to_delete:
    engine_state.state.master_stocks_cache.pop(cd, None)
```

- DB `master_stocks_table`에서도 보유종목은 삭제하지 않도록 동일 조건 적용 (844줄 DELETE 쿼리).
- 보유종목이 매매부적격이더라도 캐시·DB에 유지 → 틱 수신 정상 처리.
- 단, 매수후보 선정 시에는 매매부적격 종목이 제외되어야 함 — 이는 `buy_filter.py`의 `check_stock_guards()`에서 이미 처리됨 (별도 레이어).

### 4.3 결정 4: REST positions 덮어쓰기 → 확정 필드만 머지

**현재** (`engine_account.py:236-238`):
```python
merged = _merge_positions_from_rest(stock_list)
state.positions = merged  # 통째로 덮어쓰기
_rebuild_positions_cache(merged)
```

**설계**: 부트스트랩(기동 1회)과 재연결 시나리오를 분리.

**부트스트랩 (기동 시, positions가 비어있을 때)**:
- 현재와 동일하게 `state.positions = merged` (통째로). 틱 수신 전이므로 REST cur_price로 초기화가 정상.

**재연결/재조회 시 (positions가 이미 있을 때)**:
- 수량·매입가·종목명·수수료 등 **확정 필드만 머지**, cur_price/pnl/rate/eval_amount 등 **실시간 파생 필드는 기존값 보존**.

```python
# 의사코드
if not state.positions:
    # 부트스트랩: 통째로
    state.positions = merged
else:
    # 재조회: 확정 필드만 머지
    _merge_rest_confirmed_fields_only(state.positions, merged)
```

**머지 대상 필드 (확정값 — REST 기준)**:
- `qty`, `avail_qty`, `avg_price`, `buy_amount`, `buy_amt`, `total_fee`, `pur_cmsn`, `sell_cmsn`, `sum_cmsn`, `tax`, `stk_nm`, `hold_ratio`, `crd_tp`

**보존 대상 필드 (실시간 파생 — 틱 기준)**:
- `cur_price`, `pnl_amount`, `pnl_rate`, `eval_amount`, `change`, `change_rate`

**구현 위치**: `engine_account_rest.py`에 신규 함수 `merge_rest_confirmed_fields_only(existing_positions, rest_positions)` 추가.

### 4.4 결정 1: 1차 필터링 책임 분리 (문서화·주석 정리)

- 1차 필터링(`filter_by_avg_amt`)은 이미 `compute_sector_scores`(업종 점수)와 `get_sector_stocks`(화면용 종목 리스트)에만 사용됨.
- 보유종목 시세 추적에는 1차 필터링이 영향을 주지 않도록 결정 2·3으로 보장.
- `subscribe_sector_stocks_0b`의 주석에 "보유종목은 1차 필터링과 무관하게 구독 대상에 포함" 명시.

---

## 5. 아키텍처 원칙 점검

### 5.1 준수 원칙

| 원칙 | 준수 내용 |
|------|-----------|
| **P10 (SSOT)** | 보유종목 cur_price의 단일 진실 소스 = 틱 기반 갱신. REST는 확정 필드(수량·매입가)만 SSOT. 결정 4로 이중 경로 해소. |
| **P16 (살아있는 경로)** | 보유종목 0D/PGM 구독이 buy_targets에만 의존하던 dead path 제거 (결정 2). 2단계 필터 탈락 보유종목 캐시 삭제로 인한 dead path 제거 (결정 3). |
| **P20 (폴백 금지)** | "보유종목은 시세 추적 대상"은 명시적 도메인 조건 (빈 값/None 폴백 아님). REST 머지 시 실시간 필드 보존도 폴백이 아닌 SSOT 우선순위 지정. |
| **P21 (사용자 투명성)** | 보유종목 화면에 호가잔량비·프.순.매·현재가가 누락되지 않음. |
| **P22 (데이터 정합성)** | REST 재조회 시 틱 기반 실시간 값이 REST 값으로 퇴행하는 불일치 제거 (결정 4). |
| **P24 (단순성)** | 별도 우회 파이프라인 제거 → 단일 파이프라인. 중복 갱신 경로 통합. |

### 5.2 위반 위험 및 대응

| 위험 | 대응 |
|------|------|
| 보유종목 0D/PGM 구독 시 WS 구독 한도 초과 | `subscribe_sector_stocks_0b`의 200개 한도 로직에서 보유종목 우선 처리 이미 구현됨. 0D/PGM은 동적 구독이므로 별도 한도 확인 필요 — `sync_dynamic_subscriptions` 호출 시 보유종목 수가 한도에 미치는 영향 검토 (태스크 단계에서 검증). |
| REST 머지 시 기존 positions에 없는 신규 보유종목 (REST에서만 발견) | 부트스트랩과 동일하게 신규 종목은 통째로 추가. 기존 종목만 확정 필드 머지. |
| 2단계 필터 탈락 보유종목이 DB master_stocks_table에 유지 시, 다음 파이프라인에서 재평가 시 중복 | `INSERT ... ON CONFLICT DO UPDATE` 패턴이므로 중복 없음. |

---

## 6. 테스트 전략

### 6.1 단위 테스트

| 테스트 | 대상 | 검증 |
|--------|------|------|
| 보유종목 0D/PGM 구독 포함 | `sync_dynamic_subscriptions` | 보유종목이 buy_targets에 없어도 0D/PGM 구독 대상에 포함 |
| 2단계 필터 탈락 보유종목 캐시 유지 | `market_close_pipeline._step4_save_to_db_and_cache` | 보유종목이 confirmed_codes에 없어도 master_stocks_cache에서 삭제되지 않음 |
| REST 재조회 시 실시간 필드 보존 | `merge_rest_confirmed_fields_only` | 기존 cur_price/pnl/rate가 REST 값으로 덮어쓰기되지 않음 |
| REST 부트스트랩 시 통째로 초기화 | `_apply_account_yield_to_state` | positions 비어있을 때 REST 값으로 통째로 초기화 (기존 동작 유지) |

### 6.2 통합 시나리오

| 시나리오 | 검증 |
|----------|------|
| 1차 필터링 탈락 보유종목 (예: 052690) | 0B/01 틱 수신 → cur_price 갱신 → 화면 전파 정상 |
| 매매부적격 보유종목 (예: 관리종목) | master_stocks_cache에 유지 → 틱 수신 정상 |
| WS 재연결 시 | REST 재조회 후 수량·매입가만 갱신, cur_price는 틱 값 유지 |
| 보유종목 매도 후 | get_held_codes에서 제외 → 0D/PGM 구독 해지 대상에 포함 (30초 지연) |

---

## 7. 다음 세션 태스크 분할 제안

| 세션 | 내용 | 예상 수정 파일 |
|------|------|---------------|
| 1 | 결정 3: 2단계 필터 탈락 보유종목 캐시 유지 | market_close_pipeline.py |
| 2 | 결정 2: 보유종목 0D/PGM 구독 보장 | engine_sector_confirm.py |
| 3 | 결정 4: REST positions 머지 분리 (부트스트랩 vs 재조회) | engine_account.py, engine_account_rest.py |
| 4 | 결정 1: 주석·문서 정리 + 전체 회귀 테스트 | 다수 |
| 5 | 최종 검증 (pytest + RuntimeWarning + typecheck + build) | — |

---

## 8. 미해결 문제 (후속 논의 대상)

### (A) priceStore 통합 리팩토링 (Option A) — 본 설계와 별개

틱 핸들러 3곳 쓰기(sectorStocks/buyTargets/positions)를 단일 priceStore로 통합하는 리팩토링. 본 설계의 "단일 파이프라인"과 방향이 일치하나, 수정 범위가 크고 현재 당장 필수는 아님. 본 설계 완료 후 별도 논의.

### (B) WS 구독 한도와 보유종목 0D/PGM 구독 추가의 상호영향

`sync_dynamic_subscriptions`에 보유종목을 추가하면 0D/PGM 구독 종목 수가 증가. 현재 0D/PGM은 동적 구독(DYNAMIC_REG)으로 별도 한도 관리가 있는지 확인 필요. 태스크 단계에서 검증.

### (C) REAL 04 종목 단위 레코드와 틱 기반 갱신의 관계

`real04_official_apply_position_line` (`kiwoom_account_parsing.py:68-152`)이 REAL 04 종목 단위 레코드로 positions를 갱신. 이 경로도 틱 기반 갱신의 일종이나, `prefer_01` 로직으로 REAL 0B 우선 처리가 이미 구현되어 있음. 본 설계에서는 변경 불필요하나, 결정 4의 머지 로직과의 상호작용 검토 필요.
