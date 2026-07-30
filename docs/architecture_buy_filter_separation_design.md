# 업종 필터·매수 차단 실행 로직 분리 설계안

> **상태**: 설계 완료 / 구현 승인 대기
> **작성일**: 2026-07-31
> **범위**: `buy_filter.py:create_buy_targets()` 내 업종 top-N 선택(업종 단위)과 매수 차단(종목 단위) 혼재 해소, `trading.py` 중복 구현 통합, `engine_service.py` 결합 해소
> **범위 외**: 설정 정의·빌더 분리(`settings_defaults.py`, `engine_settings.py`, `telegram_bot.py` — 선행 작업 완료됨), 업종 스코어 계산식 변경, 가산점 로직 변경, 매도 로직, 리스크 매니저 체계

---

## 1. 근본 원인

혼재의 근본 원인은 **`create_buy_targets()` 하나의 함수가 두 추상화 수준의 책임을 동시에 수행**하도록 성장했기 때문이다.

### 성장 경로 (코드 기반 추정)

1. 초기 `create_buy_targets()`는 "업종 스코어 → 매수 타겟 큐 생성"이라는 단일 목적 함수로 시작.
2. 업종 top-N 선택(업종 단위)과 종목별 가드 적용(종목 단위)이 자연스럽게 한 루프에 묶임 — "선택하면서 가드 적용"이 직관적이었기 때문.
3. 재매수 차단(`rebuy_block_on`)·가산점(`boost_*`)·다단계 정렬(`sort_keys`)이 추가되며 종목 단위 책임이 비대해졌으나, 함수 분리 없이 같은 함수에 파라미터·분기가 누적.
4. 결과: 함수 시그니처(118-147행)에 `max_sectors`(업종) + `block_rise_*`/`block_fall_*`/`rebuy_block_*`/`boost_*`(종목)가 섞인 채 결합.

### 2차 혼재 (중복 구현)

`trading.py:execute_buy()` 428-453행이 동일한 매수 차단 판정을 **독립적으로 재구현** (442-449행 판정 + 450-453행 로깅/리턴). 432행 주석 *"buy_filter.py와 동일 조건, P10 SSOT"*가 명시하듯 의도는 동일 조건이나, 코드가 두 곳에 존재해 한쪽 수정 시 다른쪽과 불일치 발생 가능 (W3/W12 위반 소지).

### 3차 혼재 (결합 전파)

`engine_service._SECTOR_UI_KEYS`(216-232행)가 `buy_block_*` 키를 `sector_*` 키와 같은 집합에 포함. 매수 차단 설정 변경 시 `recompute_sector_summary_now()`(업종 스코어 전체 재계산)가 트리거됨. 매수 차단은 종목 단위인데 업종 재계산을 유발하는 논리적 불일치.

### 근본 원인 요약

> 부품(`sector_filter.py`, `sector_calculator.py`, `check_stock_guards()`)은 이미 분리되어 있으나, **조립 지점인 `create_buy_targets()`에서 두 추상화 수준을 한 함수에 묶어 배선**한 것이 근본 원인. 파이프라인 패턴 관점에서 각 필터가 독립 단계가 아니라 하나의 거대 함수에 인라인된 상태.

---

## 2. 현재 상태 vs 목표 아키텍처

### 현재 상태 (혼재)

```
create_buy_targets(sector_scores, max_sectors, block_rise_*, block_fall_*, rebuy_*, boost_*, sort_keys, ...)
│
├─ [업종 단위] is_cutoff_passed 필터 + max_sectors 상위 업종 선택   ← (a)
├─ [종목 단위] check_stock_guards(block_rise/fall) 적용              ← (b)
├─ [종목 단위] rebuy_block (보유/금일매수) 마킹                      ← (c)
├─ [종목 단위] calculate_boost_score 가산점 계산                     ← (d)
└─ [종목 단위] proximity 정렬 + BuyTarget/blocked 분류              ← (e)

trading.py:execute_buy() 428-453행: (b) 동일 로직 독립 재구현 ← 중복
engine_service._SECTOR_UI_KEYS: buy_block_* → recompute_sector_summary_now() ← 결합
```

### 목표 아키텍처 (분리)

```
[업종 단계 — sector_calculator.py / sector_filter.py]
  compute_sector_scores() → calculate_bonus_scores() → SectorSummary(sectors)
  select_top_sector_stocks(sector_scores, max_sectors) → list[(StockScore, SectorScore)]
        ↓ (업종 통과 종목 풀 전달)
[매수 단계 — buy_filter.py]
  apply_buy_block_guards(stocks, block_rise/fall, rebuy_*)        ← 종목 차단 (b)+(c)
  rank_buy_targets(stock_sector_pairs, sort_keys, boost_*)       ← 가산점+정렬+생성 (d)+(e)
        ↓
  build_buy_targets_from_settings() → SectorSummary(buy_targets, blocked_targets)
        ↓
[주문 단계 — trading.py:execute_buy()]
  is_change_rate_blocked(change_rate, block_rise/fall)            ← (b) 공유 함수 재사용 (중복 제거)
```

---

## 3. 분리 원칙

| 단계 | 책임 | 추상화 수준 | 금지 |
|------|------|------------|------|
| 업종 선택 | `is_cutoff_passed` 필터 + top-N 업종 선택까지만 | 업종 단위 | 종목 단위 판정(차단·가산점·정렬) 금지 |
| 매수 차단 | 개별 종목 상승/하락 차단 + 재매수 차단 마킹 | 종목 단위 | 업종 선택·업종 스코어 계산 금지 |
| 매수 순위 | 가산점 계산 + 다단계 정렬 + BuyTarget 생성 | 종목 단위 | 업종 선택 금지 |
| 주문 게이트 | 주문 직전 등락률 재검증 (공유 차단 함수 사용) | 종목 단위 | 차단 로직 독립 재구현 금지 (W3) |

각 함수는 **하나의 추상화 수준만 다룬다** (W12). 업종 단계의 출력이 매수 단계의 입력이 되는 파이프 형태 (W2).

---

## 4. 변경 파일 목록 및 책임 범위

### 수정할 파일

| 파일 | 역할 | 수정 내용 |
|------|------|----------|
| `backend/app/domain/sector_calculator.py` | 업종 단위 연산 | **추가**: `select_top_sector_stocks()` — cutoff 통과 top-N 업종의 종목 풀 산출 (업종 단위 책임 종결점) |
| `backend/app/domain/buy_filter.py` | 종목 단위 매수 차단·순위 | **분해**: `create_buy_targets()` → `apply_buy_block_guards()` + `rank_buy_targets()`. **추가**: `is_change_rate_blocked()` 순수 판정 함수. `build_buy_targets_from_settings()`는 3단계 순차 호출로 재배선 |
| `backend/app/services/trading.py` | 주문 실행 | 428-453행 인라인 차단 로직(442-449 판정 + 450-453 로깅/리턴) → `is_change_rate_blocked()` 호출로 통합 (중복 제거, W3) |
| `backend/app/services/engine_service.py` | 설정 변경 디스패치 | `_SECTOR_UI_KEYS`에서 `buy_block_*` 분리 → 신규 `_BUY_BLOCK_UI_KEYS`. 매수 차단 변경 시 경량 재순위 경로(업종 재계산 생략) 트리거 |
| `backend/app/services/sector_data_provider.py` | 업종 재계산 | `recompute_sector_summary_now()` 유지. 신규 `recompute_buy_targets_only()` 추가 — 업종 스코어 캐시 재사용, 매수 타겟만 재생성 |
| `backend/app/services/engine_sector_confirm.py` | 증분 재계산 | `build_buy_targets_from_settings()` 호출부를 분리된 3단계 순차 호출로 교체 (시그니처 유지 시 영향 최소) |

### 건드리지 않을 파일 및 이유

| 파일 | 이유 |
|------|------|
| `backend/app/domain/sector_filter.py` | 이미 순수 업종 단위 (`filter_by_avg_amt`, `group_by_sector`). 분리 대상 아님 |
| `backend/app/domain/sector_score.py` | 업종 가산점 계산 (`calculate_bonus_scores`). 업종 단위, 분리 대상 아님 |
| `backend/app/core/settings_defaults.py` | 선행 작업에서 매수 설정 블록으로 `buy_block_*` 이동 완료. 본 설계는 실행 로직 분리이므로 설정 정의 미변경 |
| `backend/app/core/engine_settings.py` | 선행 작업에서 `_build_buy_settings()`/`_build_sector_and_order_settings()` 분리 완료. 빌더 계층 미변경 |
| `backend/app/services/telegram_bot.py` | 선행 작업에서 매수 조건 섹션으로 표시 이동 완료. 표시 계층 미변경 |
| `backend/app/services/risk_manager.py` | `buy_block_*` 참조 없음. 리스크 차단은 별도 체계 (W6). 영향 없음 |
| `backend/app/services/buy_order_executor.py` | `rebuy_block_on` 참조(57-65행)는 주문 실행 단계 게이트. `guard_pass` 결과 소비. 본 분리 후에도 동일 인터페이스 유지 |
| `backend/app/pipelines/pipeline_compute*.py` | 틱 핸들러. `calculate_boost_score`·`build_buy_targets_from_settings` patch 사용. 시그니처 유지 시 영향 없음 |

---

## 5. 함수 분리 설계

### 5-1. `select_top_sector_stocks()` (신규 — sector_calculator.py)

```python
def select_top_sector_stocks(
    sector_scores: list,  # list[SectorScore] — calculate_bonus_scores 결과
    *,
    max_sectors: int = 3,
) -> list:  # list[tuple[StockScore, SectorScore]]
```

**책임**: 업종 단위 선택만. `is_cutoff_passed=False` 업종 제외, `max_sectors` 개까지 업종의 종목을 `(stock, sector_score)` 튜플 리스트로 평탄화. 차단·가산점·정렬 일체 수행 안 함.

**입력**: 정렬된 `sector_scores` (이미 `calculate_bonus_scores`에서 순위 부여됨)
**출력**: `list[(StockScore, SectorScore)]` — 업종 통과 종목 풀. `guard_pass`/`boost_score` 미설정 상태.

**근거**: 업종 단위 책임의 종결점. 이 함수의 출력 이후에는 업종 정보가 더 이상 필요 없으나, 정렬 시 `sector_rank` 표시를 위해 `SectorScore` 참조를 튜플로 전달.

### 5-2. `is_change_rate_blocked()` (신규 — buy_filter.py, 순수 판정)

```python
def is_change_rate_blocked(
    change_rate: float,
    *,
    block_rise_on: bool = True,
    block_rise_pct: float = 7.0,
    block_fall_on: bool = True,
    block_fall_pct: float = -7.0,
) -> tuple[bool, str]:
    # 반환: (blocked, reason) — reason은 "" | "상승률" | "하락률"
```

**책임**: 등락률 기반 차단 판정만. 순수 함수 (객체 변이 없음). `check_stock_guards()`와 `trading.py` 양쪽이 공유하는 **단일 판정 소스** (W3).

**근거**: 현재 `check_stock_guards()`(buy_filter.py:97-104)와 `execute_buy()`(trading.py:442-449)가 동일 판정을 독립 구현. 순수 함수로 추출하여 양쪽이 호출하도록 통합.

### 5-3. `check_stock_guards()` (리팩터 — buy_filter.py, 얇은 래퍼)

```python
def check_stock_guards(stock, *, block_rise_on, block_rise_pct, block_fall_on, block_fall_pct) -> object:
    blocked, reason = is_change_rate_blocked(
        stock.change_rate,
        block_rise_on=block_rise_on, block_rise_pct=block_rise_pct,
        block_fall_on=block_fall_on, block_fall_pct=block_fall_pct,
    )
    stock.guard_pass = not blocked
    stock.guard_reason = reason
    return stock
```

**책임**: `StockScore` 객체의 `guard_pass`/`guard_reason` 필드 설정. 판정 로직은 `is_change_rate_blocked()`에 위임. 기존 시그니처·동작 유지 (호환성).

### 5-4. `apply_buy_block_guards()` (신규 — buy_filter.py, 종목 차단 통합)

```python
def apply_buy_block_guards(
    stock_sector_pairs: list,  # list[(StockScore, SectorScore)] — select_top_sector_stocks 출력
    *,
    block_rise_on: bool, block_rise_pct: float,
    block_fall_on: bool, block_fall_pct: float,
    rebuy_block_on: bool = True,
    held_codes: set[str] | None = None,
    bought_today_codes: set[str] | None = None,
) -> None:
```

**책임**: 종목 단위 차단 마킹만. (1) `check_stock_guards()`로 상승/하락 차단 적용, (2) `rebuy_block_on` 시 보유/금일매수 종목 `guard_pass=False` 마킹. 리스트 in-place 변이, 반환 없음.

**근거**: 현재 `create_buy_targets()` 182-214행에 인라인된 두 차단 로직을 하나의 종목 단위 함수로 통합. 차단 조건 추가 시 이 함수만 변경.

### 5-5. `rank_buy_targets()` (신규 — buy_filter.py, 순위·생성)

```python
def rank_buy_targets(
    stock_sector_pairs: list,  # list[(StockScore, SectorScore)] — 차단 마킹 완료
    *,
    sort_keys: list[Literal["strength", "change_rate", "trade_amount"]] | None,
    high_5d_cache, orderbook_cache, program_net_buy_cache, news_boost_cache,
    boost_high_on, boost_high_score, boost_order_ratio_on, boost_order_ratio_pct,
    boost_order_ratio_score, boost_program_net_buy_on, boost_program_net_buy_score,
    boost_news_on, boost_news_score,
) -> SectorSummary:
```

**책임**: 종목 단위 순위·생성만. (1) `calculate_boost_score` 가산점 계산, (2) proximity 정렬(부합 종목 앞, 미부합 뒤, 가산점·sort_keys 내림차순), (3) `BuyTarget`/`blocked_targets` 분류, (4) `SectorSummary` 생성. 업종 선택·차단 판정 수행 안 함.

**근거**: 현재 `create_buy_targets()` 216-283행. 가산점·정렬 로직은 순수 종목 단위이므로 독립 함수로 분리.

### 5-6. `build_buy_targets_from_settings()` (재배선 — buy_filter.py, 어댑터)

```python
def build_buy_targets_from_settings(sector_scores, settings, *, held_codes, bought_today_codes) -> SectorSummary:
    pairs = select_top_sector_stocks(sector_scores, max_sectors=int(settings.get("sector_max_targets", 3)))
    apply_buy_block_guards(
        pairs,
        block_rise_on=bool(settings.get("buy_block_rise_on", True)),
        block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
        block_fall_on=bool(settings.get("buy_block_fall_on", True)),
        block_fall_pct=float(settings.get("buy_block_fall_pct", -7.0)),
        rebuy_block_on=bool(settings.get("rebuy_block_on", True)),
        held_codes=held_codes, bought_today_codes=bought_today_codes,
    )
    return rank_buy_targets(pairs, sort_keys=settings.get("sector_sort_keys") or None, ...boost params...)
```

**책임**: 설정 → 3단계 순차 호출 배선. 시그니처 유지 (호출부 3곳 영향 없음). `create_buy_targets()`는 제거 또는 `build_buy_targets_from_settings`와 동일 경로로 수렴.

**정리 항목 (min_rise_ratio 잔여 제거)**: 기존 `build_buy_targets_from_settings()`는 `min_rise_ratio`를 `create_buy_targets()`에 전달하나, `create_buy_targets()` 내부(173-190줄)는 `is_cutoff_passed`만 사용하고 `min_rise_ratio`를 직접 사용하지 않음 (cutoff는 이미 `calculate_bonus_scores()`에서 `is_cutoff_passed`로 설정됨). 분리 후 `select_top_sector_stocks()`는 `min_rise_ratio`를 받지 않으므로, `build_buy_targets_from_settings()`에서 `min_rise_ratio` 전달을 제거한다 (사전조사 2026-07-31 확인).

### 5-7. `trading.py` 중복 구현 처리

428-453행 인라인 차단 로직(442-449 판정 + 450-453 로깅/리턴)을 `is_change_rate_blocked()` 호출로 대체:

```python
# 기존: _rise_on/_fall_on/_rise_limit/_fall_limit 직접 읽기 + 인라인 판정 (442-449행)
# 변경:
from backend.app.domain.buy_filter import is_change_rate_blocked
_blocked, _block_reason = is_change_rate_blocked(
    _change_rate,
    block_rise_on=bool(raw_all.get("buy_block_rise_on", True)),
    block_rise_pct=float(raw_all.get("buy_block_rise_pct", 7.0)),
    block_fall_on=bool(raw_all.get("buy_block_fall_on", True)),
    block_fall_pct=float(raw_all.get("buy_block_fall_pct", -7.0)),
)
if _blocked:
    # 기존 reject_code 매핑 유지 (BUY_REJECT_RISE_GUARD / BUY_REJECT_FALL_GUARD)
```

**이중 게이트 의도 보존**: 후보 생성 시점(`apply_buy_block_guards`)과 주문 직전(`execute_buy`) 양쪽 차단 판정 유지 — 등락률 변동 방어. 단, **판정 로직은 `is_change_rate_blocked()` 단일 소스**로 통합 (W3). 양쪽 호출 유지, 중복 구현 제거.

### 5-8. `engine_service.py` 결합 해소

```python
# 기존: _SECTOR_UI_KEYS에 buy_block_* 포함 → recompute_sector_summary_now() 트리거
# 변경:
_SECTOR_UI_KEYS = {
    "sector_sort_keys", "sector_min_rise_ratio_pct", "sector_min_trade_amt",
    "sector_max_targets", "sector_bonus_rise_ratio_slider",
    "sector_bonus_relative_strength_slider", "sector_bonus_trade_amount_slider",
    # buy_block_* 제거 — 종목 단위 설정이므로 업종 재계산 불필요
}
_BUY_BLOCK_UI_KEYS = {
    "buy_block_rise_on", "buy_block_rise_pct",
    "buy_block_fall_on", "buy_block_fall_pct",
    "rebuy_block_on",  # 종목 단위 차단
}
# _BUY_BLOCK_UI_KEYS 변경 시 → recompute_buy_targets_only() 트리거 (경량 경로)
```

**경량 경로 `recompute_buy_targets_only()`** (sector_data_provider.py 신규):
기존 `sector_summary_cache.sectors` 재사용 → `build_buy_targets_from_settings()`만 재실행 → `notify_buy_targets_update()`. 업종 스코어 재계산 생략.

**근거**: 매수 차단은 종목 `guard_pass` 마킹과 순위에만 영향. 업종 스코어·컷오프·순위는 불변이므로 업종 재계산은 비용 낭비. `boost_*` 키는 가산점 계산에 영향이므로 `_BUY_BLOCK_UI_KEYS`에 포함 검토 (설계 결정 항목 9-2 참조).

---

## 6. 데이터 흐름 (분리 후)

```
[장마감 / 실시간 증분 재계산]
  compute_full_sector_summary() / compute_sector_scores() + calculate_bonus_scores()
    → SectorSummary(sectors=[SectorScore(..., is_cutoff_passed, rank, stocks=[StockScore])])
         │
         ▼
  select_top_sector_stocks(sectors, max_sectors)
    → list[(StockScore, SectorScore)]   # 업종 통과 종목 풀 (guard_pass 미설정)
         │
         ▼
  apply_buy_block_guards(pairs, block_rise/fall, rebuy_*)
    → pairs in-place 변이              # StockScore.guard_pass / guard_reason 설정
         │
         ▼
  rank_buy_targets(pairs, sort_keys, boost_*)
    → SectorSummary(buy_targets=[BuyTarget], blocked_targets=[BuyTarget])
         │
         ▼
  _set_sector_summary() → notify_buy_targets_update() → evaluate_buy_candidates()
         │
         ▼
[주문 실행]
  execute_buy(stk_cd)
    → is_change_rate_blocked(change_rate, block_rise/fall)  # 주문 직전 재검증 (공유 함수)
    → execute_buy 본 로직 (잔액/한도/시간/재매수 게이트) → dry_run/send_order
```

**파이프 특성**: 각 단계 출력이 다음 단계 입력. 단계 간 결합은 데이터 타입(`list[(StockScore, SectorScore)]`)으로만. W2(파이프라인 분리) 부합.

---

## 7. 아키텍처 원칙 부합

| 원칙 | 부합 근거 |
|------|----------|
| **P4 / D3 (증권사명 침투 금지)** | 분리된 함수 모두 공통 로직. `kiwoom_`/`ls_` 접두사 없음. 증권사별 코드는 `core/` 레지스트리 경유. 변경 없음 — 부합 유지 |
| **P8 / W2 (파이프라인 분리)** | 업종 선택 → 매수 차단 → 매수 순위가 명시적 파이프 단계로 분리. 각 단계 독립 함수, 데이터 타입으로만 결합. 한 단계 수정이 다른 단계에 간섭하지 않음 |
| **P10 / W3 (SSOT)** | 매수 차단 판정 로직이 `is_change_rate_blocked()` 단일 소스로 통합. `check_stock_guards()`·`trading.py` 양쪽 독립 구현 제거. 설정값은 `integrated_system_settings_cache` 단일 참조 유지 |
| **P15 / W5 (단일 주문 경로)** | 주문 경로는 `execute_buy()` 단일 유지. 본 설계는 주문 경로 분기·우회 생성 없음. `is_change_rate_blocked()`는 판정 함수이며 주문 경로 아님 — 게이트 내부 호출 |
| **P16 / W6 (살아있는 안전장치)** | `apply_buy_block_guards()`·`is_change_rate_blocked()`는 실제 실행 경로(`build_buy_targets_from_settings` → `evaluate_buy_candidates` / `execute_buy`)에서 호출. dead code 아님. 분리 후 호출 경로 명시적 배선 |
| **P20 / W8 (폴백 금지)** | 분리 과정에서 폴백 분기·`except: pass` 추가 없음. `guard_pass` 미설정 상태(`select_top_sector_stocks` 출력)는 다음 단계에서 반드시 설정됨 — 폴백으로 덮지 않고 순차 보장 |
| **P21 / W10 (사용자 투명성)** | 차단 사유(`guard_reason`) UI 표시 경로 유지. `execute_buy` reject_code 매핑 유지. 매수 차단 설정 변경 시 `notify_buy_targets_update()`로 UI 즉시 갱신 — 경량 경로에서도 알림 보장 |
| **P22 / W4 (단계 간 정합성)** | `StockScore.guard_pass`는 `apply_buy_block_guards()`에서만 설정 (단일 설정점). `select_top_sector_stocks` 출력은 미설정 상태로 전달, `rank_buy_targets`는 설정된 값 소비. 파생 데이터 중복 저장 없음 |
| **P23 / W11 (표현 통일)** | 신규 함수명 `snake_case` 준수. 용어 "업종"/"종목"/"매수 후보" 사용. 기존 `check_stock_guards`·`calculate_boost_score` 재사용 (새로 만들지 않음). `is_change_rate_blocked`는 기존 판정 로직의 추출이므로 동일 동작 |
| **P24 / W12 (단순성)** | `create_buy_targets()` 325행 → 3 함수 분해 (각 50행 내외 예상). 중복 구현(`trading.py`) 제거. 1회용 래퍼 없음. `build_buy_targets_from_settings`는 어댑터(필수). 새 필터 추가 시 해당 단계 함수만 변경 |
| **P25 / W9 (격리된 실패)** | 각 단계 함수 실패 시 호출부 `try/except`에서 로깅. `recompute_buy_targets_only()` 실패가 업종 재계산 루프를 중단하지 않음. 기존 `schedule_engine_task()` 패턴 유지 |

---

## 8. 테스트 계획

### 8-1. 단위 테스트 (test_buy_filter.py 확장)

| 함수 | 시나리오 | 기대 |
|------|---------|------|
| `select_top_sector_stocks` | cutoff 미달 업종 제외 | 미달 업종 종목 미포함 |
| | max_sectors 초과 시 상위 N개만 | `len(pairs)` ≤ top-N 업종 종목 합 |
| | 빈 sector_scores | 빈 리스트 |
| `is_change_rate_blocked` | 상승률 ≥ limit → 차단 | `(True, "상승률")` |
| | 하락률 ≤ limit → 차단 | `(True, "하락률")` |
| | 범위 내 → 통과 | `(False, "")` |
| | `block_rise_on=False` → 상승 미차단 | `(False, "")` |
| | `block_rise_pct=0` → 무효 → 미차단 | `(False, "")` |
| `apply_buy_block_guards` | 보유 종목 + rebuy_block_on → 차단 | `guard_pass=False`, `reason="보유중"` |
| | 금일매수 + rebuy_block_on → 차단 | `guard_pass=False`, `reason="금일매수"` |
| | rebuy_block_on=False → 보유 종목 통과 | `guard_pass` 상승/하락 판정만 |
| `rank_buy_targets` | 부합 종목 앞, 미부합 뒤 정렬 | `buy_targets` 전원 `guard_pass=True` |
| | boost_score 내림차순 | 높은 가산점 우선 |
| | sort_keys 다단계 | 1순위→2순위 적용 |
| `build_buy_targets_from_settings` | 설정 → 3단계 호출 | 기존 `create_buy_targets` 동일 결과 (회귀) |

### 8-2. 회귀 테스트 (기존 30건 시그니처 갱신)

`test_buy_filter.py` `TestCreateBuyTargets` 클래스 30개 테스트 메서드의 `create_buy_targets` 직접 호출 → `build_buy_targets_from_settings` 또는 분리된 함수로 갱신. 동일 입력에 대해 동일 출력 보장 (회귀 검증). (사전조사: 설계 초안 48건은 과대 집계 — 실제 30개 메서드, `test_version_increments` 2회 호출 포함 31 호출 지점.)

### 8-3. 통합 테스트

| 경로 | 검증 |
|------|------|
| `test_engine_sector_confirm.py` (11건) | `build_buy_targets_from_settings` patch 유지 — 시그니처 유지 시 영향 없음 |
| `test_buy_order_executor.py` | `rebuy_block_on` 게이트 동작 유지 |
| `test_risk_manager.py` | `buy_block_*` 무관 — 영향 없음 확인 |
| `test_engine_settings.py` | 빌더 테스트 — 선행 작업 완료, 영향 없음 |

### 8-4. 런타임 검증 게이트 (D5)

- `.venv/bin/python -m pytest backend/tests -q` (2697 tests)
- `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락)
- `.venv/bin/python main.py` 기동 — 0-1-3 잔존 프로세스 0건

---

## 9. 설계 결정 항목

### 9-1. `select_top_sector_stocks` 파일 배치: `sector_calculator.py`

**결정**: `sector_calculator.py`에 배치.
**근거**: 업종 단위 연산의 종결점. `compute_sector_scores`·`calculate_bonus_scores`와 같은 모듈에서 업종 단위 책임 완결. `buy_filter.py`는 종목 단위만 담당하여 "업종은 업종만" 원칙 강제.
**대안**: `buy_filter.py`에 두는 방안 — 기각 (종목 단위 모듈에 업종 선택이 섞이면 본 설계 목적 훼손).

### 9-2. `boost_*` 키 소속: `_BUY_BLOCK_UI_KEYS` 포함

**결정**: `boost_*` 키는 가산점 계산에 영향하므로 매수 순위 단계(`rank_buy_targets`)에 속함. 업종 스코어에는 무영향이므로 `_BUY_BLOCK_UI_KEYS`(경량 재순위 경로)에 포함.
**근거**: 가산점 변경 시 업종 재계산 불필요, 매수 타겟 재순위만 필요. `recompute_buy_targets_only()`로 처리 가능.

### 9-3. `create_buy_targets()` 제거 여부

**결정**: 제거. `build_buy_targets_from_settings()`가 동일 경로(3단계 순차 호출)로 수렴. `create_buy_targets()` 직접 호출부는 `build_buy_targets_from_settings` 또는 분리 함수로 이전.
**근거**: W12(불필요 추상화 금지). 두 진입점 유지 시 SSOT 위반 소지. 테스트 30건 갱신 필요.

### 9-4. 이중 게이트(후보 생성 + 주문 직전) 유지

**결정**: 양쪽 차단 판정 유지, 판정 로직은 `is_change_rate_blocked()` 통합.
**근거**: 후보 생성 시점과 주문 실행 시점 사이 등락률 변동 방어가 의도적 이중 게이트. 한쪽 제거 시 주문 직전 재검증 소실 → 안전성 저하. W6(살아있는 안전장치) 부합.

---

## 10. 영향 범위 및 회귀 위험

### 변하는 것

| 항목 | 변화 |
|------|------|
| `create_buy_targets()` | 3 함수로 분해 → 제거 (9-3) |
| `trading.py:execute_buy()` 428-453행 | 인라인 판정 → `is_change_rate_blocked()` 호출 |
| `engine_service._SECTOR_UI_KEYS` | `buy_block_*` 분리 → `_BUY_BLOCK_UI_KEYS` |
| 매수 차단 설정 변경 시 | 업종 전체 재계산 → 매수 타겟 재순위만 (경량화) |
| `test_buy_filter.py` 30건 | 분리된 함수 시그니처로 갱신 |

### 변하지 않는 것

| 항목 | 이유 |
|------|------|
| `build_buy_targets_from_settings()` 시그니처 | 어댑터로 캡슐화, 호출부 3곳 영향 없음 |
| `SectorSummary`/`BuyTarget`/`StockScore`/`SectorScore` 데이터 모델 | 구조 변경 없음 |
| `execute_buy()`/`execute_sell()` 주문 경로 | 단일 경로 유지 (W5) |
| `evaluate_buy_candidates()` 흐름 | `guard_pass` 결과 소비 인터페이스 동일 |
| 업종 스코어 계산·컷오프·순위 | `sector_calculator.py`/`sector_score.py` 미변경 |
| 설정 정의·빌더·표시 계층 | 선행 작업 완료, 본 설계 범위 외 |
| WS 이벤트·프론트엔드 | 백엔드 내부 구조 분리, 외부 인터페이스 불변 |

### 회귀 위험 및 완화

| 위험 | 완화 |
|------|------|
| 분리 후 동일 입력 → 상이 출력 | `build_buy_targets_from_settings` 회귀 테스트로 기존 결과와 비교 |
| `trading.py` 판정 로직 교체 시 reject_code 매핑 누락 | 기존 `BUY_REJECT_RISE_GUARD`/`BUY_REJECT_FALL_GUARD` 매핑 명시적 유지 |
| 경량 재순위 경로 누락 시 UI 미갱신 | `recompute_buy_targets_only()`에서 `notify_buy_targets_update()` 필수 호출 |
| `select_top_sector_stocks` 정렬 순서 변경 | `sector_scores`는 이미 `calculate_bonus_scores`에서 정렬됨 — 재정렬 금지, 순서 유지 |

---

## 11. 범위 밖 (이번에 하지 않을 것)

1. **설정 정의·빌더·표시 분리** — `settings_defaults.py`, `engine_settings.py`, `telegram_bot.py`는 선행 작업 완료. 미변경.
2. **업종 스코어 계산식 변경** — `compute_sector_scores`/`calculate_bonus_scores` 로직 미변경.
3. **가산점 로직 변경** — `calculate_boost_score` 알고리즘 미변경 (함수 추출만).
4. **매도 로직** — `execute_sell()`/T/S/익절/손절 체계 미변경.
5. **리스크 매니저 체계** — `risk_manager.py`는 `buy_block_*` 무관. 별도 체계 유지.
6. **데이터 모델 변경** — `SectorSummary`/`BuyTarget`/`StockScore`/`SectorScore` 구조 미변경.
7. **WS 이벤트·프론트엔드** — 백엔드 내부 분리이므로 외부 인터페이스 불변.
8. **`buy_order_executor.py` 내부 로직** — `guard_pass` 소비 인터페이스 유지, 미변경.
9. **파이프라인 틱 핸들러** — `pipeline_compute_tick_handlers.py`의 `calculate_boost_score` 직접 호출은 유지 (boost 재계산 경로).

---

## 12. 위험도 산정 및 검증·관찰 계층 게이트 (소급 추가 — AGENTS.md 섹션4)

> 본 섹션은 AGENTS.md 섹션4 "검증·관찰 계층 게이트" 신규 규칙에 따라 소급 추가. 본 설계는 거래 로직(매수 차단) 변경이므로 위험도 '높음' — 전 게이트 필수 적용.

### 위험도 산정

| 항목 | 내용 |
|------|------|
| 위험도 | **높음** |
| 근거 | 매수 차단 로직(`create_buy_targets()` → `execute_buy()` 경로) 분리. 주문 경로 직결 — 판정 로직 교체 시 reject_code 매핑 누락·차단 조건 불일치 시 잔고 손실 위험. P15(주문 경로 단일성)·P16(살아있는 경로) 직결. |
| 비개발자용 3줄 요약 | 매수 후보를 고르는 과정이 한 함수에 너무 많이 얽혀 있어, 고르는 부분과 차단하는 부분을 나눕니다. 차단 조건이 두 곳에 중복되어 있던 것을 한 곳으로 통합합니다. 위험도: 높음 — 매수 주문 경로를 직접 다루는 변경. |

### 적용 게이트 (전부 필수 — 위험도 높음)

1. **독립 검증**: 구현 완료 후 별도 세션에서 커밋 해시 + 태스크 파일만 주고 "분리 후 동일 입력 → 동일 출력 보장하는가, reject_code 매핑 누락 없는가" 독립 검토. 결과를 HANDOVER "검증 결과"에 기록.
2. **사전 롤백 계획**: 태스크 파일에 명시 예정 — (a) 롤백 명령, (b) 즉시 롤백 트리거: 매수 주문이 차단되어야 할 종목에서 발생·차단되지 않은 종목이 통과·reject_code 미매핑으로 인한 주문 누락·분리 후 매수 후보 목록이 기존과 상이.
3. **모의/dry-run 관찰**: 실계좌 적용 전 모의투자 모드로 최소 2세션(장마감 파이프라인 2회 실행) 관찰 — 매수 후보 목록이 분리 전과 동일한지 비교.
4. **배포 후 모니터링**: 실계좌 반영 후 3회(장 시작·장마감 파이프라인·매수 주문 시도) 텔레그램 알림과 프론트 화면의 매수 후보 목록을 사용자가 직접 비교.
5. **이견 조정**: 구현 중 분리 방식에 이견 시 제3의 AI에게 재검증(1회) → 2차 갈림 시 사용자 최종 결정 → 태스크 파일 "바로잡음 로그"에 결정 사유 기록.

---

## 13. 구현 순서 (참고 — 승인 후 별도 세션)

> 본 설계안은 설계 단계 완료. 구현은 safe-trade 스킬 적용 하 별도 세션에서 진행. 섹션 12 위험도 '높음' 게이트 전부 적용.

1. `is_change_rate_blocked()` + `check_stock_guards()` 리팩터 (순수 판정 추출)
2. `select_top_sector_stocks()` 추가 (sector_calculator.py)
3. `apply_buy_block_guards()` + `rank_buy_targets()` 분리 (buy_filter.py)
4. `build_buy_targets_from_settings()` 3단계 재배선
5. `trading.py` 428-453행 `is_change_rate_blocked()` 통합
6. `engine_service._BUY_BLOCK_UI_KEYS` 분리 + `recompute_buy_targets_only()` 추가
7. `engine_sector_confirm.py` 호출부 조정
8. `test_buy_filter.py` 30건 갱신 + 회귀 테스트
9. 검증 게이트: pytest / RuntimeWarning / 기동
10. **독립 검증 게이트**: 별도 세션에서 커밋 해시 + 태스크 파일 기반 독립 검토 (섹션 12-1)
11. **모의 관찰**: 모의투자 모드 2세션 관찰 (섹션 12-3)
