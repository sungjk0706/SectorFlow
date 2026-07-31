# 태스크 파일: 보유종목 실시간 단일 파이프라인 통합

> **상태**: 태스크 작성 완료 — 구현 세션 대기
> **작성일**: 2026-08-01
> **설계서**: `docs/architecture_holdings_single_pipeline_design.md`
> **다단계 진행**: 1세션(설계) ✅ / 2세션(태스크) ✅ / 3세션(결정3 캐시 유지) ✅ 커밋 `ac54231` / 3.5세션(보유종목 업종별 종목 테이블 제외) 대기 / 4세션(결정2 0D/PGM 구독) 대기 / 5세션(결정4 REST 머지 분리) 대기 / 6세션(결정1 문서정리+회귀) 대기 / 7세션(최종 검증) 대기
> **위험도**: 중간 (보유종목 시세 추적·구독·positions 머지 경로 변경. 주문 로직 미변경이나 계좌 상태 갱신 경로 수정 포함)
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패)
> **필수 스킬**: 구현 세션 진입 시 `safe-trade` 스킬 필수 (positions/구독 경로 수정 — P15 단일 주문 경로 인접)

---

## 0. 사전조사 결과 요약 (설계서 SSOT)

> 본 태스크 파일은 `docs/architecture_holdings_single_pipeline_design.md`의 조사 결과·설계 결정을 실행 단위로 구체화한 것. 본 파일과 설계서가 불일치할 경우 **설계서가 SSOT**.

### 0.1 사용자 진단 (전제)

- "1차 필터링(5거래일 평균 거래대금)의 책임은 구독 대상 선정에서 끝나야 한다. 그 이후 로직들에 혼재되어 있다."
- "보유종목은 1차 필터링 통과 여부와 무관하게 같은 실시간 파이프라인으로 틱을 수신하는 게 정상 아키텍처다."
- "별개로 보유종목 구독을 별개로 해서 다른 파이프라인을 사용하는 것은 잘못된 아키텍처다."

### 0.2 핵심 발견: 핸드오버 기록과 실제 코드 불일치 (정정)

- **핸드오버 기록(2026-07-31)**: "1차 필터링 탈락 종목(052690)이 `market_close_pipeline.py:867-869`에서 master_stocks_cache 삭제됨"
- **실제 코드**: 867-869줄 삭제 대상은 **2단계 매매부적격 필터링 탈락 종목**(관리종목·거래정지 등). 1차 필터링 탈락 종목은 `_filtered` 플래그만 제거하고 캐시에 유지됨.
- 052690(197억 < 200억)은 1차 필터링 탈락이므로 master_stocks_cache에 존재했음. 이전 세션 "배선 교정"(커밋 `9c737f9`)이 정확한 증상 치료였음.

### 0.3 실제 구조 문제 3건

| 문제 | 설계 결정 | 수정 파일 | 수정 규모 |
|------|-----------|-----------|-----------|
| A: 보유종목 0D/PGM 구독 누락 | 결정 2 | engine_sector_confirm.py | 중 |
| B: 2단계 매매부적격 필터링 탈락 보유종목 캐시 삭제 | 결정 3 | market_close_pipeline.py | 소 |
| C: REST positions 통째로 덮어쓰기 → 틱 기반 실시간 값 퇴행 | 결정 4 | engine_account.py, engine_account_rest.py | 중 |
| —: 1차 필터링 책임 분리 (이미 부분 구현) | 결정 1 | (주석·문서 정리) | 소 |

### 0.4 비목표 (본 태스크 범위 외)

- 1차 필터링 로직 자체(`filter_by_avg_amt`) 변경 없음.
- 2단계 매매부적격종목 필터링(`evaluate_stock_filter`) 변경 없음.
- 매수후보 파이프라인 변경 없음 (이미 단일 파이프라인).
- priceStore 통합 리팩토링(Option A) — 별도 논의 대상.
- REST 기반 계좌 부트스트랩 자체 제거 안 함 (실전 모드 부트스트랩 필요).

### 0.5 아키텍처 원칙 부합

| 원칙 | 판정 | 구현 기준 |
|------|------|-----------|
| P10 (SSOT) | ✅ | 보유종목 cur_price 단일 진실 소스 = 틱 기반 갱신. REST는 확정 필드(수량·매입가)만 SSOT. 결정 4로 이중 경로 해소. |
| P16 (살아있는 경로) | ✅ | 보유종목 0D/PGM 구독이 buy_targets에만 의존하던 dead path 제거(결정 2). 2단계 필터 탈락 보유종목 캐시 삭제로 인한 dead path 제거(결정 3). |
| P20 (폴백 금지) | ✅ | "보유종목은 시세 추적 대상"은 명시적 도메인 조건 (빈 값/None 폴백 아님). REST 머지 시 실시간 필드 보존도 폴백이 아닌 SSOT 우선순위 지정. |
| P21 (사용자 투명성) | ✅ | 보유종목 화면에 호가잔량비·프.순.매·현재가 누락 제거. |
| P22 (데이터 정합성) | ✅ | REST 재조회 시 틱 기반 실시간 값이 REST 값으로 퇴행하는 불일치 제거(결정 4). |
| P23 (일관성) | ✅ | 용어 사전 준수("업종"/"종목"/"매수 후보"). 기존 `get_held_codes()` 헬퍼 재사용. |
| P24 (단순성) | ✅ | 별도 우회 파이프라인 제거 → 단일 파이프라인. 중복 갱신 경로 통합. |
| P25 (격리된 실패) | ✅ | 보유종목 구독 실패가 매수후보 구독을 블로킹하지 않도록 격리. |

---

## 1. 사용자 결정 항목 (설계서 섹션 3.1)

| 항목 | 확정 기준 | 사용자 영향 |
|------|-----------|-------------|
| 결정 1: 1차 필터링 책임 분리 | 1차 필터링은 구독 대상 선정(+업종 점수)에만 사용. 보유종목 시세 추적에는 영향 없음 | 보유종목이 1차 필터링 탈락해도 실시간 시세 표시 |
| 결정 2: 보유종목 0D/PGM 구독 보장 | `sync_dynamic_subscriptions`에 보유종목 코드를 guard_pass와 별도로 포함 | 보유종목 화면에 호가잔량비·프.순.매 표시 |
| 결정 3: 2단계 필터 탈락 보유종목 캐시 유지 | `market_close_pipeline.py:867-869` 삭제 조건에 보유종목 제외 추가 | 매매부적격 보유종목(관리종목 등)도 시세 추적 유지 |
| 결정 4: REST positions 머지 분리 | 부트스트랩은 통째로, 재조회 시 확정 필드만 머지(실시간 파생 필드 보존) | WS 재연결 후에도 틱 기반 실시간 값 유지 |

---

## 2. 의존성 및 재사용 자산

| 파일 | 역할 | 태스크 적용 기준 |
|------|------|------------------|
| `backend/app/services/market_close_pipeline.py` | 장마감 파이프라인 4단계 캐시 동기화 | 결정 3 — 867-869줄 삭제 조건에 보유종목 제외 + 844줄 DELETE 쿼리 동일 조건 |
| `backend/app/services/engine_sector_confirm.py` | 0D/PGM 동적 구독 증분 갱신 | 결정 2 — `sync_dynamic_subscriptions`(267줄) new_codes에 보유종목 추가 + `_flush_unreg_batch`(350줄) 해지 시 보유종목 보호 |
| `backend/app/services/engine_account.py` | REST 잔고 → positions 반영 | 결정 4 — `_apply_account_yield_to_state`(223줄) 부트스트랩/재조회 분기 |
| `backend/app/services/engine_account_rest.py` | positions 병합·스냅샷 메타 | 결정 4 — 신규 함수 `merge_rest_confirmed_fields_only` 추가 |
| `backend/app/services/engine_account.py:406-421` | `get_held_codes()` 헬퍼 | 결정 2·3에서 재사용 (이미 구현됨, 신규 작성 금지 — P23 공통 자산 재사용) |
| `backend/app/services/engine_radar.py:65-67` | 0B/01 틱 캐시 부재 스킵 | 결정 3의 효과 검증 지점 (보유종목 캐시 유지 시 스킵 해제) |
| `backend/app/pipelines/pipeline_compute_tick_handlers.py:295-338` | 0D/PGM 틱 캐시 부재 스킵 | 결정 2의 효과 검증 지점 (보유종목 0D/PGM 구독 시 스킵 해제) |

---

## 3. 구현 세션 분할

> 규칙: 한 구현 세션은 아래 단계 중 하나만 수행한다. 각 단계 완료 후 검증 → 코드 커밋(코드만) → `HANDOVER.md` 갱신(파일만) → 세션 완료 보고(채팅) 순서로 수행하고 다음 세션으로 넘긴다. 태스크 파일은 모든 단계가 완료될 때까지 삭제하지 않는다.
>
> 세션 순서는 의존성 기반: 결정 3(캐시 유지) → 세션 3.5(업종별 종목 테이블 제외) → 결정 2(구독) → 결정 4(REST 머지) → 결정 1(문서정리+회귀) → 최종 검증. 결정 3이 먼저인 이유: 캐시에 보유종목이 있어야 결정 2의 0D/PGM 구독이 의미 있음(틱 수신 시 스킵 방지). 세션 3.5가 세션 4 앞인 이유: 세션 3으로 인해 발생한 부작용(업종별 종목 테이블에 보유종목 노출)을 즉시 차단하여 업종 순위 왜곡 방지.

### 세션 3 — 결정 3: 2단계 필터 탈락 보유종목 master_stocks_cache 유지

**목표**: 매매부적격(관리종목·거래정지 등)으로 2단계 필터링 탈락한 보유종목이 master_stocks_cache에서 삭제되어 틱 수신 시 스킵되는 문제 제거. 보유종목은 도메인상 시세 추적 대상이므로 매매 적격 여부와 무관하게 캐시에 유지.

**수정 파일**:
- `backend/app/services/market_close_pipeline.py`

**작업 체크리스트**:

- [ ] `safe-trade` 스킬 invoke (positions/캐시 경로 수정 — P15 인접).
- [ ] `_step4_save_to_db_and_cache` 함수 시그니처 확인 — `confirmed_codes: set[str]` 파라미터.
- [ ] `get_held_codes()` 호출 추가 — `engine_account.get_held_codes()`는 async이므로 `await` 필수 (P1 async 일관성, 금지 패턴 4번째 `await` 누락).
- [ ] 867-869줄 캐시 삭제 조건 수정:
  ```python
  # Before
  keys_to_delete = [cd for cd in list(engine_state.state.master_stocks_cache.keys()) if cd not in confirmed_codes]
  # After
  held_codes = await engine_account.get_held_codes()
  keys_to_delete = [
      cd for cd in list(engine_state.state.master_stocks_cache.keys())
      if cd not in confirmed_codes and cd not in held_codes
  ]
  ```
- [ ] 844줄 DB DELETE 쿼리 동일 조건 적용 — `DELETE FROM master_stocks_table WHERE code NOT IN (...)`에 보유종목 제외 조건 추가. 단, DB 쿼리는 `confirmed_codes_list` placeholders에 보유종목을 추가하는 방식으로 구현 (보유종목이 confirmed_codes에 없으므로 별도 세트 결합).
  - 주의: DB DELETE의 placeholders는 `confirmed_codes` 기준. 보유종목을 제외하려면 `confirmed_codes | held_codes`로 확장하거나 서브쿼리 방식 검토. 구현 시 기존 쿼리 패턴 유지 (P23 일관성).
- [ ] `_step4_save_to_db_and_cache`가 async인지 확인 — `get_held_codes()` await 가능 여부. (함수가 이미 async이므로 await 직접 호출 가능 — P1).
- [ ] 보유종목이 캐시에 유지된 상태에서 `engine_radar.py:65-67` 스킵이 해제되는지 확인 (코드 읽기만, 수정 불필요).
- [ ] 매수후보 선정 시 매매부적격 종목 제외는 `buy_filter.py`의 `check_stock_guards()`에서 이미 처리됨 확인 (별도 레이어 — 본 수정이 매수후보에 매매부적격 종목이 들어가게 하지 않는지 검증).
- [ ] 단위 테스트 추가 — `test_market_close_pipeline.py`에 "보유종목이 confirmed_codes에 없어도 master_stocks_cache에서 삭제되지 않음" 케이스.
- [ ] 단위 테스트 추가 — "보유종목이 아닌 2단계 필터 탈락 종목은 여전히 캐시에서 삭제됨" 케이스 (회귀 보호).
- [ ] `.venv/bin/python -m pytest backend/tests/test_market_close_pipeline.py -q` 통과.
- [ ] `.venv/bin/python -m pytest backend/tests -q` 전체 통과 (2697 tests).
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` 짧게 기동 후 종료 — `await` 누락 RuntimeWarning 없음 확인.

**세션 3 완료 조건**:
- [ ] 매매부적격 보유종목이 master_stocks_cache + DB master_stocks_table에 유지됨.
- [ ] 매수후보 선정에는 매매부적격 종목이 여전히 제외됨 (별도 레이어 확인).
- [ ] pytest 전체 통과 + RuntimeWarning 없음.
- [ ] 해당 세션 코드만 커밋하고 실제 커밋 해시를 `HANDOVER.md`에 기록.

**위험/주의점**:
1. `get_held_codes()`가 테스트 모드에서 `dry_run.position_codes()`를 사용 — 테스트 시 모의 보유종목 세팅 필요.
2. DB DELETE 쿼리 수정 시 placeholders 개수와 파라미터 리스트 길이 일치 필수 (SQL 에러 방지).
3. **[정정 — 세션 3 구현 중 발견]** 보유종목이 `master_stocks_cache`에 유지되면, `get_sector_stocks()`(업종별 종목 실시간 시세 테이블용)에 매매부적격 보유종목이 표시될 수 있음. `get_sector_stocks()`는 `_filtered` 플래그가 아닌 `cur_price`/`avg_5d_trade_amount` 기반 필터링만 수행하므로, 매매부적격이더라도 5거래일 평균 거래대금 기준을 통과하면 업종별 종목 테이블에 노출됨. 이는 업종 순위 왜곡(매수 불가 종목이 업종 분석 데이터에 혼재)을 유발하므로 **세션 3.5에서 해결** — `get_sector_stocks()`에서 보유종목 제외.

---

### 세션 3.5 — 보유종목 업종별 종목 시세 테이블 제외 (사용자 추가 요구사항)

> **추가 배경**: 세션 3 구현 중 발견 — 보유종목을 `master_stocks_cache`에 유지(세션 3)하면, `get_sector_stocks()`가 이를 업종별 종목 실시간 시세 테이블(업종순위 페이지 우측 패널)에 노출할 수 있음. 사용자 결정: "보유종목은 보유 종목 화면에만 표시, 업종별 종목 시세 테이블에는 미노출. 매매부적격 또는 5거래일 평균 거래대금 미통과 종목이 업종 순위 데이터에 혼재되면 순위 정합성 왜곡 우려. 보유종목은 실시간 구독 유지하되 매도만 가능."

**목표**: 보유종목이 `master_stocks_cache`에 유지되더라도(세션 3), `get_sector_stocks()`(업종별 종목 실시간 시세 테이블용)에서는 제외되도록 수정. 업종 순위 왜곡 방지 + 보유종목은 보유 종목 화면에만 표시.

**수정 파일**:
- `backend/app/services/sector_data_provider.py`

**작업 체크리스트**:

- [ ] `safe-trade` 스킬 invoke (업종별 종목 시세 테이블은 매수 후보 선정 기초 데이터 — P15 인접).
- [ ] `get_sector_stocks()`(68줄) 함수 확인 — 이미 `async def`이므로 `await get_held_codes()` 직접 호출 가능 (P1).
- [ ] 82줄 `for cd in engine_state.state.master_stocks_cache:` 루프 시작 전 `held_codes = await engine_account.get_held_codes()` 조회.
- [ ] 루프 내 보유종목 제외 조건 추가:
  ```python
  # Before
  for cd in engine_state.state.master_stocks_cache:
      e = engine_state.state.master_stocks_cache.get(cd, {}).copy()
      ...
  # After
  held_codes = await engine_account.get_held_codes()
  for cd in engine_state.state.master_stocks_cache:
      if cd in held_codes:
          continue  # 보유종목은 업종별 종목 시세 테이블에서 제외 (업종 순위 왜곡 방지)
      e = engine_state.state.master_stocks_cache.get(cd, {}).copy()
      ...
  ```
- [ ] `get_buy_targets_sector_stocks()`(118줄)는 `_sector_summary_cache.buy_targets` 기반이므로 영향 없음 확인 — 보유종목은 이미 `guard_pass=False`로 매수 후보에서 제외됨.
- [ ] `get_sector_stocks()` 호출처 전수 조사 — 시그니처 변경 없음(async 유지), 호출처 수정 불필요. 단, 성능 영향 검토: `get_held_codes()` 호출 추가로 인한 오버헤드 (이미 다른 경로에서 빈번 호출되는 헬퍼이므로 미미 예상).
- [ ] 업종 순위 계산 파이프라인(`sector_summary_cache` 생성 경로)이 `get_sector_stocks()` 기반인지 확인 — 만약 그렇다면 보유종목 제외가 업종 순위 계산에도 반영되는지 검증. 만약 업종 순위 계산이 별도 경로라면 `get_sector_stocks()`는 표시용만 수정.
- [ ] 단위 테스트 추가 — `test_sector_data_provider.py`에:
  - "보유종목이 master_stocks_cache에 있어도 get_sector_stocks() 결과에서 제외됨"
  - "비보유종목은 get_sector_stocks() 결과에 포함됨 (회귀 보호)"
  - "보유종목 매도 후(get_held_codes에서 제외) get_sector_stocks()에 다시 포함됨"
- [ ] `.venv/bin/python -m pytest backend/tests/test_sector_data_provider.py -q` 통과.
- [ ] `.venv/bin/python -m pytest backend/tests -q` 전체 통과.
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — await 누락 없음.

**세션 3.5 완료 조건**:
- [ ] 보유종목이 업종별 종목 실시간 시세 테이블(업종순위 페이지 우측 패널)에 표시되지 않음.
- [ ] 보유종목은 보유 종목 화면(positions 기반)에만 표시됨.
- [ ] 보유종목은 master_stocks_cache에 유지되어 실시간 틱 수신 정상 (세션 3 효과 유지).
- [ ] 비보유종목은 기존대로 업종별 종목 시세 테이블에 표시됨 (회귀 없음).
- [ ] pytest 전체 통과 + RuntimeWarning 없음.
- [ ] 해당 세션 코드만 커밋하고 실제 커밋 해시를 `HANDOVER.md`에 기록.

**위험/주의점**:
1. `get_sector_stocks()` 호출 빈도 — 실시간 갱신 경로에서 빈번 호출 시 `get_held_codes()` 오버헤드. 단, `get_held_codes()`는 `state.positions` 순회(동기) 또는 `dry_run.position_codes()`(async)로 가벼운 헬퍼이므로 미미 예상.
2. 업종 순위 계산 경로 확인 필수 — `get_sector_stocks()`가 업종 순위 계산의 원재료인지, 표시용인지에 따라 영향 범위 다름. 사전 조사 시 반드시 확인.
3. 보유종목 매도 후 즉시 업종별 종목 테이블에 복귀 — `get_held_codes()`에서 제외되면 다음 `get_sector_stocks()` 호출 시 포함. 단, 매도 후에도 5거래일 평균 거래대금 기준은 유지되어야 포함됨.

---

### 세션 4 — 결정 2: 보유종목 0D/PGM 구독 보장

**목표**: 보유종목이 buy_targets의 guard_pass가 아니어도 0D(호가잔량)·PGM(프로그램순매수) 구독을 보장. 보유종목 화면에 호가잔량비·프.순.매가 누락되는 P21 위반 제거.

**수정 파일**:
- `backend/app/services/engine_sector_confirm.py`

**작업 체크리스트**:

- [ ] `safe-trade` 스킬 invoke (구독 경로 수정).
- [ ] `sync_dynamic_subscriptions`(267줄) 함수 시그니처 확인 — 현재 동기 함수(`def`, `new_buy_targets` 파라미터). `get_held_codes()`는 async이므로 **함수를 async로 전환** 또는 **보유종목 코드를 동기적으로 조회하는 방법** 검토.
  - 옵션 A: `sync_dynamic_subscriptions`를 `async def`로 전환 + 모든 호출처에 `await` 추가 (P1 async 일관성).
  - 옵션 B: `state.positions`에서 동기적으로 보유종목 코드 추출 (`get_held_codes()`의 동기 버전 또는 인라인 추출). 단, 테스트 모드의 `dry_run.position_codes()`는 async이므로 옵션 A가 일관성 있음.
  - **권장: 옵션 A** — `get_held_codes()` 재사용 (P23 공통 자산 재사용, P10 SSOT). 호출처 전수 조사 후 `await` 전파.
- [ ] 282줄 new_codes 계산 수정:
  ```python
  # Before
  new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}
  # After
  held_codes = await engine_account.get_held_codes()
  new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass} | held_codes
  ```
- [ ] `sync_dynamic_subscriptions` 호출처 전수 조사 — `await` 전파 필요. grep으로 모든 호출 지점 확인.
- [ ] `_flush_unreg_batch`(350줄) 해지 시 보유종목 보호 검증:
  - 현재 `to_unreg = codes & current_codes` — `codes`는 타이머 만료된 종목. 보유종목이 `new_codes`에 항상 포함되면 `returned_codes`(323줄)에서 타이머 취소되므로 해지 대상에 들어가지 않음.
  - 단, 보유종목 매도 후 `get_held_codes()`에서 제외되면 다음 `sync_dynamic_subscriptions` 호출 시 new_codes에서 빠짐 → 30초 지연 후 해지. 이는 의도된 동작(설계서 6.2 시나리오).
  - 검증: 보유종목이 보유 중에는 해지 대상에 절대 들어가지 않는지 코드 경로 추적.
- [ ] WS 구독 한도 검토 (설계서 미해결 문제 B): `sync_dynamic_subscriptions`에 보유종목 추가 시 0D/PGM 구독 종목 수 증가. DYNAMIC_REG는 별도 한도 관리가 있는지 확인 — 없다면 보유종목 수가 한도 초과를 유발하지 않는지 검증. 보유종목은 일반적으로 소수(1~10종목)이므로 한도 영향 미미 예상.
- [ ] 단위 테스트 추가 — `test_engine_sector_confirm.py`에:
  - "보유종목이 buy_targets에 없어도 0D/PGM 구독 대상에 포함됨"
  - "보유종목이 buy_targets에 있으면 중복 추가되지 않음 (set 연산)"
  - "보유종목은 해지 대상에서 제외됨"
  - "보유종목 매도 후 new_codes에서 제외 → 30초 지연 후 해지 대상"
- [ ] 기존 `sync_dynamic_subscriptions` 테스트 시그니처 전파 (async 전환 시).
- [ ] `.venv/bin/python -m pytest backend/tests/test_engine_sector_confirm.py -q` 통과.
- [ ] `.venv/bin/python -m pytest backend/tests -q` 전체 통과.
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — await 누락 없음.

**세션 4 완료 조건**:
- [ ] 보유종목이 buy_targets guard_pass 여부와 무관하게 0D/PGM 구독됨.
- [ ] 보유종목 보유 중에는 해지되지 않음.
- [ ] 보유종목 매도 후 30초 지연 해지 정상 동작.
- [ ] pytest 전체 통과 + RuntimeWarning 없음.
- [ ] 해당 세션 코드만 커밋하고 `HANDOVER.md`에 기록.

**위험/주의점**:
1. `sync_dynamic_subscriptions` async 전환 시 호출처 영향 범위 — 반드시 grep 전수 후 전파 (P16 살아있는 경로, 누락 시 dead call).
2. WS 재연결 시 `sync_dynamic_subscriptions` 재호출 시점 확인 — 재연결 후 보유종목 0D/PGM이 재구독되는지.
3. 0D/PGM 구독 한도 초과 시 에러 로깅 + 보유종목 우선 보장 (P25 격리된 실패 — 매수후보 구독 실패가 보유종목 구독을 블로킹하지 않도록).

---

### 세션 5 — 결정 4: REST positions 머지 분리 (부트스트랩 vs 재조회)

**목표**: REST 기반 positions 갱신이 틱 기반 실시간 값(cur_price/pnl/rate/eval_amount)을 REST 값으로 덮어쓰는 P10 SSOT 위반 제거. 부트스트랩(기동 1회)은 통째로, 재조회(WS 재연결 등)는 확정 필드만 머지.

**수정 파일**:
- `backend/app/services/engine_account.py`
- `backend/app/services/engine_account_rest.py`

**작업 체크리스트**:

- [ ] `safe-trade` 스킬 invoke (positions 갱신 경로 수정 — P15 인접, 가장 위험도 높은 세션).
- [ ] `_apply_account_yield_to_state`(223줄) 호출 지점 전수 조사:
  - `engine_account.py:207` — `_update_account_memory` 내부 (부트스트랩 경로).
  - `engine_bootstrap.py:30-40` — 기동 시 REST 잔고 조회.
  - WS 재연결 시 재조회 경로 확인 — `account_rest_bootstrapped`가 `engine_lifecycle.py:131`에서 False로 리셋되는지 확인.
- [ ] 부트스트랩 vs 재조회 분기 조건 확정:
  - **부트스트랩**: `not state.positions` (positions가 비어있을 때) → 통째로 `state.positions = merged` (현재 동작 유지).
  - **재조회**: `state.positions`가 이미 있을 때 → 확정 필드만 머지.
  - 주의: `account_rest_bootstrapped` 플래그만으로 분기하면 안 됨 — positions 내용 유무가 더 정확한 분기 기준 (빈 positions + bootstrapped=True 케이스 대비).
- [ ] `_apply_account_yield_to_state` 수정 (236-238줄):
  ```python
  # Before
  merged = _merge_positions_from_rest(stock_list)
  state.positions = merged
  _rebuild_positions_cache(merged)

  # After
  merged = _merge_positions_from_rest(stock_list)
  if not state.positions:
      # 부트스트랩: 통째로 (틱 수신 전이므로 REST cur_price로 초기화가 정상)
      state.positions = merged
  else:
      # 재조회: 확정 필드만 머지 (틱 기반 실시간 값 보존)
      merge_rest_confirmed_fields_only(state.positions, merged)
  _rebuild_positions_cache(state.positions)
  ```
- [ ] `engine_account_rest.py`에 신규 함수 `merge_rest_confirmed_fields_only(existing_positions, rest_positions)` 추가:
  - **머지 대상 필드 (확정값 — REST 기준)**: `qty`, `avail_qty`, `avg_price`, `buy_amount`, `buy_amt`, `total_fee`, `pur_cmsn`, `sell_cmsn`, `sum_cmsn`, `tax`, `stk_nm`, `hold_ratio`, `crd_tp`
  - **보존 대상 필드 (실시간 파생 — 틱 기준)**: `cur_price`, `pnl_amount`, `pnl_rate`, `eval_amount`, `change`, `change_rate`
  - 매칭 키: `stk_cd` (`_base_stk_cd` 정규화).
  - REST에만 있는 신규 보유종목: 통째로 추가 (부트스트랩과 동일).
  - existing에만 있는 종목(REST에서 사라진): 틱 기반 값 유지하되 qty=0 처리 검토 — 단, 매도 체결은 REAL 01/04 틱으로 이미 처리되므로 REST에서 사라졌다고 임의 삭제 금지 (P20 폴백 금지). 그대로 유지.
- [ ] `merge_positions_from_rest`(17줄)는 부트스트랩용으로 그대로 유지 — 신규 함수는 재조회 전용.
- [ ] 단위 테스트 추가 — `test_engine_account_rest.py`에:
  - "부트스트랩: positions 비어있을 때 REST 값으로 통째로 초기화"
  - "재조회: 기존 cur_price/pnl/rate가 REST 값으로 덮어쓰기되지 않음"
  - "재조회: qty/avg_price/stk_nm 등 확정 필드는 REST 값으로 갱신됨"
  - "재조회: REST에만 있는 신규 종목은 통째로 추가"
  - "재조회: existing에만 있는 종목은 유지됨 (임의 삭제 금지)"
- [ ] `test_engine_account.py` / `test_broker_change.py` 기존 테스트 회귀 확인 — broker 변경 시나리오에서 positions 덮어쓰기 동작 변경 영향.
- [ ] REAL 04 종목 단위 레코드(`real04_official_apply_position_line`)와의 상호작용 검토 (설계서 미해결 문제 C) — REAL 04는 틱 기반 갱신의 일종이므로 결정 4 머지 로직과 충돌 없는지 확인. `prefer_01` 로직으로 REAL 0B 우선 처리가 이미 구현됨.
- [ ] `.venv/bin/python -m pytest backend/tests/test_engine_account_rest.py backend/tests/test_engine_account.py backend/tests/test_broker_change.py -q` 통과.
- [ ] `.venv/bin/python -m pytest backend/tests -q` 전체 통과.
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — await 누락 없음.

**세션 5 완료 조건**:
- [ ] 부트스트랩 시 REST 값으로 통째로 초기화 (기존 동작 유지).
- [ ] 재조회 시 수량·매입가 등 확정 필드만 갱신, cur_price/pnl/rate는 틱 값 유지.
- [ ] REST에만 있는 신규 종목은 통째로 추가.
- [ ] pytest 전체 통과 + RuntimeWarning 없음.
- [ ] 해당 세션 코드만 커밋하고 `HANDOVER.md`에 기록.

**위험/주의점**:
1. **가장 위험도 높은 세션** — positions는 계좌 상태 SSOT. 머지 로직 오류 시 손익·수익률 왜곡. 반드시 `safe-trade` 스킬 진행.
2. broker 변경 시나리오(`test_broker_change.py`) — broker 전환 시 positions 전체 재구성이 필요할 수 있음. 이 경우 부트스트랩과 동일하게 통째로 덮어쓰기가 정상일 수 있으므로, 분기 조건이 broker 변경을 포함하는지 검토.
3. `account_rest_bootstrapped` 리셋 시점(`engine_lifecycle.py:131`)과 positions 유무의 관계 — 재연결 시 positions가 비어있지 않으면 재조회 경로로 가는지 확인.
4. 머지 필드 분류 오류 주의 — `buy_amt`(수수료 포함 매입)는 확정값이지만 `eval_amount`는 실시간 파생. 필드 분류는 설계서 4.3 기준 엄수.

---

### 세션 6 — 결정 1: 1차 필터링 책임 분리 (주석·문서 정리) + 전체 회귀 테스트

**목표**: 1차 필터링 책임 분리를 코드 주석·문서로 명시하고, 세션 3·4·5의 변경 사항이 전체 시스템에 회귀를 일으키지 않는지 통합 검증.

**수정 파일**:
- `backend/app/services/engine_ws_reg.py` (주석 정리)
- 회귀 발견 시 해당 파일

**작업 체크리스트**:

- [ ] `subscribe_sector_stocks_0b`(`engine_ws_reg.py:70-156`) 주석에 "보유종목은 1차 필터링과 무관하게 구독 대상에 포함" 명시 (124-130줄 선행 REG 부분).
- [ ] 1차 필터링(`filter_by_avg_amt`) 사용처 전수 확인 — `compute_sector_scores`(업종 점수)·`get_sector_stocks`(화면용 종목 리스트)에만 사용됨 확인. 보유종목 시세 추적 경로에 1차 필터링이 영향 주지 않는지 최종 검증.
- [ ] 세션 3·4·5 변경 사항 교차 회귀 테스트:
  - 보유종목이 1차 필터링 탈락 + 2단계 필터링 탈락 동시 케이스 — 캐시 유지(세션 3) + 0D/PGM 구독(세션 4) 모두 적용되는지.
  - 보유종목 매도 후 — 캐시에서 제거(세션 3 조건) + 0D/PGM 해지(세션 4) + REST 머지 시 existing에서 사라지는지(세션 5).
  - WS 재연결 후 — REST 재조회 시 확정 필드만 머지(세션 5) + 보유종목 0D/PGM 재구독(세션 4).
- [ ] 통합 시나리오 단위 테스트 추가 (설계서 6.2):
  - "1차 필터링 탈락 보유종목(052690 케이스) — 0B/01 틱 수신 → cur_price 갱신 → 화면 전파 정상"
  - "매매부적격 보유종목(관리종목) — master_stocks_cache 유지 → 틱 수신 정상"
  - "WS 재연결 시 — REST 재조회 후 수량·매입가만 갱신, cur_price는 틱 값 유지"
  - "보유종목 매도 후 — get_held_codes 제외 → 0D/PGM 구독 해지(30초 지연)"
- [ ] `.venv/bin/python -m pytest backend/tests -q` 전체 통과 (2697 tests + 신규 테스트).
- [ ] 프론트엔드 영향 확인 — 본 태스크는 백엔드만 수정하나, positions/구독 상태가 WS로 전파되는 프론트 수신부 회귀 확인 (typecheck + build).

**세션 6 완료 조건**:
- [ ] 1차 필터링 책임 분리가 주석·코드 구조로 명시됨.
- [ ] 세션 3·4·5 교차 회귀 테스트 통과.
- [ ] 통합 시나리오 4건 단위 테스트 통과.
- [ ] pytest 전체 통과.
- [ ] 해당 세션 코드만 커밋하고 `HANDOVER.md`에 기록.

---

### 세션 7 — 최종 검증 (pytest + RuntimeWarning + typecheck + build)

**목표**: 모든 구현 세션 완료 후 전체 검증 게이트 통과 확인.

**수정 파일**:
- 원칙적으로 없음. 세션 3~6에서 발견된 직접적인 오류만 선행 단계로 되돌려 수정.

**검증 체크리스트**:

- [ ] `.venv/bin/python -m pytest backend/tests -q` 통과 (전체).
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — await 누락 RuntimeWarning 없음 (금지 패턴 4번째).
- [ ] 0-1-3 명령어로 잔존 프로세스 0건 확인.
- [ ] `cd frontend && npm run typecheck` 통과.
- [ ] `cd frontend && npm run build` 통과.
- [ ] `cd frontend && npm run test` 통과 (116 tests).
- [ ] ARCHITECTURE.md 금지 패턴 5개 점검:
  - `asyncio.run()` 사용 금지 위반 없음.
  - `create_task` 무분별 분리 금지 — `schedule_engine_task()` 사용.
  - `except Exception: pass` 금지 — `logger.warning(..., exc_info=True)`.
  - async 함수 `await` 누락 금지 — RuntimeWarning 검증으로 확인.
  - dead code 방치 금지 — 세션 3~6에서 추가한 함수가 실제 호출 경로에 연결됨.

**세션 7 완료 조건**:
- [ ] 백엔드 pytest + RuntimeWarning 검증 통과.
- [ ] 프론트엔드 typecheck + build + test 통과.
- [ ] 금지 패턴 5개 위반 없음.
- [ ] `HANDOVER.md` 최종 갱신 — 다단계 진행 표시 모두 ✅, 브라우저 관찰 대기 항목 추가 (사용자가 실시간 화면에서 보유종목 호가잔량비·프.순.매·현재가 표시 확인 필요).

---

## 4. 검증 기준 (전체)

| 단계 | 명령어 | 기대 결과 |
|------|--------|-----------|
| 백엔드 단위 테스트 | `.venv/bin/python -m pytest backend/tests -q` | 2697+ tests 통과 (신규 테스트 포함) |
| RuntimeWarning | `.venv/bin/python -W error::RuntimeWarning main.py` | await 누락 없음 |
| 잔존 프로세스 | 0-1-3 명령어 | 0건 |
| 프론트 타입체크 | `cd frontend && npm run typecheck` | 통과 |
| 프론트 빌드 | `cd frontend && npm run build` | 통과 |
| 프론트 테스트 | `cd frontend && npm run test` | 116 tests 통과 |

---

## 5. 위험/주의점 (전체)

1. **세션 순서 준수**: 결정 3(캐시 유지) → 결정 2(구독) → 결정 4(REST 머지) 순서. 캐시에 보유종목이 있어야 구독한 틱이 스킵되지 않음.
2. **safe-trade 스킬 필수**: 세션 3·4·5는 positions/구독 경로 수정이므로 P15 단일 주문 경로 인접. 각 세션 진입 시 `safe-trade` 스킬 invoke.
3. **테스트 모드 vs 실전 모드**: `get_held_codes()`가 테스트 모드에서 `dry_run.position_codes()` 사용. 테스트 시 모의 보유종목 세팅 필요. 본 수정은 테스트/실전 공통 로직 (AGENTS.md "매매 판단은 동일 로직").
4. **WS 구독 한도** (설계서 미해결 문제 B): 세션 4에서 보유종목 0D/PGM 구독 추가 시 한도 영향 검증. 보유종목은 소수 예상이나 확인 필수.
5. **REAL 04 상호작용** (설계서 미해결 문제 C): 세션 5에서 `real04_official_apply_position_line`과 머지 로직의 상호작용 검토.
6. **DB 안전 규칙**: 세션 3이 DB DELETE 쿼리 수정 포함. `stocks.db` 삭제/덮어쓰기 금지 (안전 규칙 1). 스키마 변경 없으므로 백업 불필요하나, DELETE 쿼리 수정 시 신중.
7. **브라우저 최종 관찰**: 세션 7 완료 후 사용자가 실시간 화면에서 보유종목 호가잔량비·프.순.매·현재가 표시 확인 필요 (P21 최종 검증).

---

## 6. 미해결 문제 (후속 논의 대상 — 설계서 섹션 8)

- **(A) priceStore 통합 리팩토링 (Option A)**: 본 태스크와 별개. 틱 핸들러 3곳 쓰기 통합. 본 태스크 완료 후 별도 논의.
- **(B) WS 구독 한도와 보유종목 0D/PGM 추가 상호영향**: 세션 4에서 검증 후 필요 시 설계서 갱신.
- **(C) REAL 04 종목 단위 레코드와 틱 기반 갱신 관계**: 세션 5에서 검토 후 필요 시 설계서 갱신.
