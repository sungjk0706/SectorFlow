# 태스크 파일: 업종 필터·매수 차단 실행 로직 분리 구현

> **상태**: 태스크 분할 완료 / 구현 승인 대기
> **작성일**: 2026-07-31
> **설계서 경로**: `docs/architecture_buy_filter_separation_design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ / 2세션(태스크 분할) ✅ / 3세션(구현 1단계) ✅ / 4세션(구현 2단계) ✅ / 5세션(구현 3단계) ✅ / 6세션(구현 4단계) ✅ / 7세션(구현 5단계) ✅ / 8세션(구현 6단계) 대기 / 9세션(최종 검증) 대기
> **관련 원칙**: P4 · P8 · P10 · P15 · P16 · P20 · P21 · P22 · P23 · P24 · P25

---

## 0. 사전조사 결과 요약

> 설계서(섹션 1·2·4·5·7·10)에서 이미 확정한 사실은 P10(SSOT)에 따라 본 섹션에서 요약만 기재. 상세 근거는 설계서 참조. 사전조사는 2026-07-31 실제 코드 대상 수행 — 설계안 초안과의 불일치 4건을 설계서에 반영 완료 (본 태스크는 반영된 설계서 기준).

### 0.1 의존성

| 파일 | 변경점 | 기준 라인 |
|------|--------|-----------|
| `backend/app/domain/buy_filter.py` | `is_change_rate_blocked()` 신규 추가 + `check_stock_guards()` 리팩터 (판정 위임) | 81-107 (check_stock_guards) |
| `backend/app/domain/buy_filter.py` | `apply_buy_block_guards()` + `rank_buy_targets()` 신규 추가, `create_buy_targets()`(118-283) 분해·제거, `build_buy_targets_from_settings()`(286-325) 3단계 재배선, `min_rise_ratio` 전달 제거 | 118-325 |
| `backend/app/domain/sector_calculator.py` | `select_top_sector_stocks()` 신규 추가 (업종 단위 선택 종결점) | 파일 끝 (197줄) |
| `backend/app/services/trading.py` | 428-453행 인라인 차단 판정(442-449) → `is_change_rate_blocked()` 호출로 통합. 450-453 로깅/리턴 유지, reject_code 매핑 유지 | 428-453 |
| `backend/app/services/engine_service.py` | `_SECTOR_UI_KEYS`(216-232)에서 `buy_block_*` 4개 + `boost_*` 7개 + `rebuy_block_on` 분리 → 신규 `_BUY_BLOCK_UI_KEYS`. `_apply_sector_ui_change`(233-242)에서 `_BUY_BLOCK_UI_KEYS` 변경 시 `recompute_buy_targets_only()` 트리거 분기 추가 | 216-242 |
| `backend/app/services/sector_data_provider.py` | `recompute_buy_targets_only()` 신규 추가 — `engine_state.state.sector_summary_cache.sectors` 재사용 → `build_buy_targets_from_settings()`만 재실행 → `notify_buy_targets_update()`. `recompute_sector_summary_now()`(254-314)는 유지 | 254-323 (신규 함수는 이후) |
| `backend/app/services/engine_sector_confirm.py` | `build_buy_targets_from_settings()` 호출부(171-176) — 시그니처 유지 시 영향 없음, 호출부 검증만 | 171-176 |
| `backend/tests/test_buy_filter.py` | `TestCreateBuyTargets` 30개 테스트 메서드의 `create_buy_targets` 직접 호출 → `build_buy_targets_from_settings` 또는 분리 함수로 갱신. `TestCheckStockGuards` 14개는 `check_stock_guards` 시그니처 유지로 변경 없음 | 439-715 (TestCreateBuyTargets) |

### 0.2 영향 범위

- **백엔드 도메인**: `buy_filter.py`(종목 단위 분해), `sector_calculator.py`(업종 단위 선택 추가). 데이터 모델(`SectorSummary`/`BuyTarget`/`StockScore`/`SectorScore`) 구조 변경 없음.
- **백엔드 서비스**: `trading.py`(중복 판정 통합), `engine_service.py`(키 집합 분리), `sector_data_provider.py`(경량 재순위 경로 추가), `engine_sector_confirm.py`(호출부 검증).
- **프론트엔드 / DB / 설정 스키마 / WS 이벤트**: 변경 없음 (설계서 섹션 10 "변하지 않는 것" · 섹션 11 범위 밖 7항).
- **설정 정의·빌더·표시 계층**: 선행 작업 완료, 본 설계 범위 외 (설계서 섹션 4 "건드리지 않을 파일").
- **리스크 매니저**: `buy_block_*` 무관, 영향 없음 (설계서 섹션 4).
- **`buy_order_executor.py`**: `guard_pass` 소비 인터페이스 유지, 미변경 (설계서 섹션 4).
- **파이프라인 틱 핸들러**: `calculate_boost_score`·`build_buy_targets_from_settings` 시그니처 유지 시 영향 없음 (설계서 섹션 4).

### 0.3 아키텍처 원칙 부합

> 상세 근거는 설계서 섹션 7. 본 태스크는 실행 단계별 부합 항목만 표기.

| 원칙 | 부합 | 실행 단계에서의 확인점 |
|------|------|----------------------|
| P4 | ✅ | 분리된 함수 모두 공통 로직, 증권사 접두사 없음 |
| P8 | ✅ | 업종 선택 → 매수 차단 → 매수 순위 명시적 파이프 단계 분리 |
| P10 | ✅ | 매수 차단 판정 `is_change_rate_blocked()` 단일 소스 통합, `buy_filter.py`·`trading.py` 중복 제거 |
| P15 | ✅ | 주문 경로 `execute_buy()` 단일 유지, 분기·우회 생성 없음 |
| P16 | ✅ | `apply_buy_block_guards`·`is_change_rate_blocked` 실제 실행 경로 배선, dead code 아님 |
| P20 | ✅ | 폴백 분기·`except: pass` 추가 없음, `guard_pass` 미설정 상태는 순차 보장 |
| P21 | ✅ | `guard_reason` UI 표시 경로 유지, `execute_buy` reject_code 매핑 유지, 경량 경로 `notify_buy_targets_update` 보장 |
| P22 | ✅ | `StockScore.guard_pass` 단일 설정점(`apply_buy_block_guards`), 파생 데이터 중복 저장 없음 |
| P23 | ✅ | 신규 함수명 `snake_case`, 용어 "업종"/"종목"/"매수 후보" 사용, 기존 `check_stock_guards`·`calculate_boost_score` 재사용 |
| P24 | ✅ | `create_buy_targets()` 325행 → 3 함수 분해, `trading.py` 중복 제거, 1회용 래퍼 없음 |
| P25 | ✅ | 각 단계 함수 실패 시 호출부 `try/except` 로깅, `recompute_buy_targets_only` 실패가 업종 루프 중단 안 함, `schedule_engine_task()` 유지 |

### 0.4 기존 공통 자산 확인

- **재사용 (신규 생성 없음)**:
  - `backend.app.domain.buy_filter.calculate_boost_score` — `rank_buy_targets` 내 기존 호출 그대로 유지
  - `backend.app.domain.sector_score.calculate_bonus_scores` — 업종 가산점, 미변경
  - `backend.app.domain.sector_calculator.compute_sector_scores` / `compute_full_sector_summary` — 업종 스코어 계산, 미변경
  - `backend.app.services.engine_account_notify.notify_buy_targets_update` — 경량 경로 알림 재사용
  - `backend.app.services.engine_initial_data._set_sector_summary` — 캐시 갱신 재사용
  - `engine_state.state.integrated_system_settings_cache` — 설정 SSOT, 기존 참조 그대로
  - `engine_state.state.sector_summary_cache` — 업종 스코어 캐시, 경량 경로에서 `.sectors` 재사용
  - 테스트 헬퍼: `_stock`(`test_buy_filter.py:19`), `_sector`(`test_buy_filter.py:47`)
- **신규 생성** (설계서 섹션 5):
  - `is_change_rate_blocked()` — `buy_filter.py`, 순수 판정 함수 (W3 SSOT 통합)
  - `select_top_sector_stocks()` — `sector_calculator.py`, 업종 단위 선택 종결점
  - `apply_buy_block_guards()` — `buy_filter.py`, 종목 차단 통합
  - `rank_buy_targets()` — `buy_filter.py`, 종목 순위·생성
  - `recompute_buy_targets_only()` — `sector_data_provider.py`, 경량 재순위 경로
  - `_BUY_BLOCK_UI_KEYS` — `engine_service.py`, 매수 차단 설정 키 집합

---

## 1. 단계 분할

> 정량 기준(컨텍스트 관리 규칙 1 · 규칙 0-2-5): 수정 파일 3개 초과 또는 수정 라인 50줄 초과 시 다단계 분할 필수.
> 본 작업: 수정 파일 7개(구현 6 + 테스트 1), 수정 라인 약 300줄(분해+재배선+중복제거+키분리+경량경로+테스트 갱신) → 다단계 분할 필수.
> 설계서 섹션 12 구현 순서 9단계를 의존성 그래프 기반으로 7개 세션(3~9세션)으로 분할. 각 세션은 세션당 1단계 원칙(규칙 0-1) 준수 — 강결합 단계는 단일 세션 내 묶음 (P24 과잉 분할 회피).

### 3세션: `is_change_rate_blocked()` + `check_stock_guards()` 리팩터

**목표**: `buy_filter.py`에 순수 판정 함수 `is_change_rate_blocked()`를 추가하고, `check_stock_guards()`가 이를 위임 호출하도록 리팩터한다 (설계서 섹션 5-2·5-3).

**수정 파일 목록**:
1. `backend/app/domain/buy_filter.py` — 구현

**파일별 변경점**:

#### `backend/app/domain/buy_filter.py` (구현)

- **신규 추가** `is_change_rate_blocked()` (설계서 섹션 5-2 시그니처 준수):
  - 입력: `change_rate: float`, `*`, `block_rise_on`, `block_rise_pct`, `block_fall_on`, `block_fall_pct`
  - 반환: `tuple[bool, str]` — `(blocked, reason)`, `reason`은 `""` | `"상승률"` | `"하락률"`
  - 순수 함수 (객체 변이 없음). `check_stock_guards()`와 `trading.py` 양쪽 공유 단일 판정 소스 (W3).
- **리팩터** `check_stock_guards()` (81-107줄):
  - 기존 인라인 판정 로직(89-104줄) → `is_change_rate_blocked()` 호출로 위임
  - `stock.guard_pass = not blocked`, `stock.guard_reason = reason` 설정
  - 시그니처·동작 유지 (호환성) — `TestCheckStockGuards` 14개 테스트 변경 없음

**유지 (변경 금지)**:
- `create_buy_targets()`(118-283) — 본 세션에서 미수정 (5세션에서 분해)
- `build_buy_targets_from_settings()`(286-325) — 본 세션에서 미수정
- `calculate_boost_score` — 미변경

**검증 방법**:
```bash
# 1단계: 관련 테스트
.venv/bin/python -m pytest backend/tests/test_buy_filter.py::TestCheckStockGuards -q

# 2단계: 전체 (2697 tests, asyncio_mode=auto)
.venv/bin/python -m pytest backend/tests -q

# 3단계: RuntimeWarning (await 누락 검증 — 금지 패턴 4번째)
.venv/bin/python -W error::RuntimeWarning main.py
```

**정량 기준**: 수정 파일 1개, 수정 라인 약 30줄 (기준 미달). 독립성 높고 안전 기반 확보를 위해 별도 세션 — `is_change_rate_blocked()`는 6세션(`trading.py` 통합)의 선행 의존.

---

### 4세션: `select_top_sector_stocks()` 추가

**목표**: `sector_calculator.py`에 업종 단위 선택 종결점 함수 `select_top_sector_stocks()`를 추가한다 (설계서 섹션 5-1)

**수정 파일 목록**:
1. `backend/app/domain/sector_calculator.py` — 구현

**파일별 변경점**:

#### `backend/app/domain/sector_calculator.py` (구현)

- **신규 추가** `select_top_sector_stocks()` (설계서 섹션 5-1 시그니처 준수):
  - 입력: `sector_scores: list` (list[SectorScore] — `calculate_bonus_scores` 결과, 정렬됨), `*`, `max_sectors: int = 3`
  - 출력: `list[tuple[StockScore, SectorScore]]` — 업종 통과 종목 풀. `guard_pass`/`boost_score` 미설정 상태.
  - 로직: `is_cutoff_passed=False` 업종 제외, `max_sectors`개까지 업종의 종목을 `(stock, sector_score)` 튜플 리스트로 평탄화. 차단·가산점·정렬 일체 수행 안 함.
  - `sector_scores` 재정렬 금지 — 이미 `calculate_bonus_scores`에서 순위 부여됨 (설계서 섹션 10 회귀 위험 완화).

**유지 (변경 금지)**:
- `compute_sector_scores()`(14-150) — 미변경
- `calculate_bonus_scores` import(9) — 미변경

**검증 방법**:
```bash
# 1단계: 관련 테스트 (신규 함수 직접 테스트는 8세션에서 추가, 본 세션은 기존 테스트 회귀 확인)
.venv/bin/python -m pytest backend/tests/test_sector_calculator.py -q 2>/dev/null || true
.venv/bin/python -m pytest backend/tests -q

# 2단계: RuntimeWarning
.venv/bin/python -W error::RuntimeWarning main.py
```

**정량 기준**: 수정 파일 1개, 수정 라인 약 25줄 (기준 미달). 독립성 높고 5세션(`apply_buy_block_guards`+`rank_buy_targets`)의 선행 의존.

---

### 5세션: `apply_buy_block_guards()` + `rank_buy_targets()` + `build_buy_targets_from_settings()` 재배선 + `create_buy_targets()` 제거

**목표**: `buy_filter.py`에서 `create_buy_targets()`(118-283)를 `apply_buy_block_guards()` + `rank_buy_targets()`로 분해하고, `build_buy_targets_from_settings()`(286-325)를 3단계 순차 호출로 재배선하며, `create_buy_targets()`를 제거한다 (설계서 섹션 5-4·5-5·5-6·9-3)

**수정 파일 목록**:
1. `backend/app/domain/buy_filter.py` — 구현

**파일별 변경점**:

#### `backend/app/domain/buy_filter.py` (구현)

- **신규 추가** `apply_buy_block_guards()` (설계서 섹션 5-4 시그니처 준수):
  - 입력: `stock_sector_pairs: list` (list[(StockScore, SectorScore)] — `select_top_sector_stocks` 출력), `*`, `block_rise_on/pct`, `block_fall_on/pct`, `rebuy_block_on`, `held_codes`, `bought_today_codes`
  - 동작: (1) `check_stock_guards()`로 상승/하락 차단 적용, (2) `rebuy_block_on` 시 보유/금일매수 종목 `guard_pass=False` 마킹. 리스트 in-place 변이, 반환 없음.
  - 기존 `create_buy_targets()` 173-194줄(업종 선택+가드)·196-205줄(재매수 차단 마킹) 중 종목 단위 부분을 통합.
- **신규 추가** `rank_buy_targets()` (설계서 섹션 5-5 시그니처 준수):
  - 입력: `stock_sector_pairs: list` (차단 마킹 완료), `*`, `sort_keys`, `high_5d_cache`, `orderbook_cache`, `program_net_buy_cache`, `news_boost_cache`, `boost_*` 파라미터
  - 출력: `SectorSummary` (`buy_targets` + `blocked_targets`)
  - 동작: (1) `calculate_boost_score` 가산점 계산, (2) proximity 정렬(부합 종목 앞, 미부합 뒤, 가산점·sort_keys 내림차순), (3) `BuyTarget`/`blocked_targets` 분류, (4) `SectorSummary` 생성.
  - 기존 `create_buy_targets()` 216-271줄(가산점·정렬·분류) 이관.
- **재배선** `build_buy_targets_from_settings()` (286-325):
  - 기존 `create_buy_targets()` 단일 호출 → 3단계 순차 호출로 교체:
    1. `select_top_sector_stocks(sector_scores, max_sectors=...)`
    2. `apply_buy_block_guards(pairs, block_rise/fall, rebuy_*, held_codes, bought_today_codes)`
    3. `rank_buy_targets(pairs, sort_keys, boost_*)`
  - 시그니처 유지 (호출부 3곳: `engine_sector_confirm.py:171`, `sector_data_provider.py:288`, 파이프라인 — 영향 없음).
  - **`min_rise_ratio` 전달 제거** (설계서 섹션 5-6 정리 항목): 기존 `min_rise_ratio=float(settings.get("sector_min_rise_ratio_pct", 60.0)) / 100.0` 전달 제거 — `create_buy_targets` 내부에서 미사용, `select_top_sector_stocks`도 미수신.
- **제거** `create_buy_targets()` (118-283):
  - 설계 결정 9-3에 따라 제거. 직접 호출부는 `build_buy_targets_from_settings` 또는 분리 함수로 이전 (8세션에서 테스트 갱신).
  - 제거 후 참조 주석·docstring 정리 (AGENTS.md 코드 제거 규칙 1·2 준수).

**유지 (변경 금지)**:
- `is_change_rate_blocked()` — 3세션에서 추가, 본 세션에서 호출만
- `check_stock_guards()` — 3세션에서 리팩터 완료, 본 세션에서 `apply_buy_block_guards` 내 호출
- `calculate_boost_score` — 미변경, `rank_buy_targets` 내 기존 호출 유지

**검증 방법**:
```bash
# 1단계: 관련 테스트 (TestCreateBuyTargets 30개는 8세션에서 갱신 — 본 세션에서 일시 실패 예상, create_buy_targets 제거로 import 에러)
#   → 본 세션에서는 test_buy_filter.py를 일시 skip 처리하거나 import를 build_buy_targets_from_settings로 임시 교체 후 회귀 확인
.venv/bin/python -m pytest backend/tests/test_buy_filter.py::TestCheckStockGuards -q
.venv/bin/python -m pytest backend/tests/test_buy_filter.py::TestCalculateBoostScore -q

# 2단계: 전체 (create_buy_targets 제거로 TestCreateBuyTargets 실패 예상 → 8세션에서 갱신)
.venv/bin/python -m pytest backend/tests -q --ignore=backend/tests/test_buy_filter.py

# 3단계: RuntimeWarning
.venv/bin/python -W error::RuntimeWarning main.py
```

**정량 기준**: 수정 파일 1개, 수정 라인 약 150줄 (50줄 초과). **초과 사유**: 3·4단계(설계서 섹션 12)가 강결합 — `rank_buy_targets`가 `apply_buy_block_guards` 마킹 결과 소비, `build_buy_targets_from_settings`가 양쪽 호출. 중간 상태(한쪽만 분리)에서 `create_buy_targets` 제거 시 불안정. 단일 파일 내 완결되므로 단일 세션 묶음 (P24 과잉 분할 회피).

---

### 6세션: `trading.py` 중복 판정 통합 + `engine_sector_confirm.py` 호출부 검증

**목표**: `trading.py` 428-453행 인라인 차단 판정을 `is_change_rate_blocked()` 호출로 통합하고, `engine_sector_confirm.py`의 `build_buy_targets_from_settings()` 호출부가 시그니처 유지로 정상 동작함을 검증한다 (설계서 섹션 5-7·4 변경 파일 목록)

**수정 파일 목록**:
1. `backend/app/services/trading.py` — 구현
2. `backend/app/services/engine_sector_confirm.py` — 검증 (수정 최소)

**파일별 변경점**:

#### `backend/app/services/trading.py` (구현)

- **교체** 428-453행 인라인 차단 판정(442-449) → `is_change_rate_blocked()` 호출 (설계서 섹션 5-7):
  - `from backend.app.domain.buy_filter import is_change_rate_blocked` 추가
  - 기존 `_rise_on/_fall_on/_rise_limit/_fall_limit` 직접 읽기 + 인라인 판정(442-449) → `is_change_rate_blocked()` 호출
  - `_change_rate`는 기존대로 `state.master_stocks_cache.get(stk_cd, {}).get("change_rate")`에서 읽기 (437줄 유지)
  - `_blocked, _block_reason = is_change_rate_blocked(_change_rate, block_rise_on=..., block_rise_pct=..., block_fall_on=..., block_fall_pct=...)`
  - `if _blocked:` 시 기존 로깅(450-452) + `return False, _reject_code`(453) 유지
  - **reject_code 매핑 유지**: `BUY_REJECT_RISE_GUARD`/`BUY_REJECT_FALL_GUARD` (53-54줄) — `is_change_rate_blocked` 반환 `reason`이 `"상승률"`/`"하락률"`이므로 이를 reject_code로 매핑하는 래퍼 유지
- **이중 게이트 의도 보존** (설계서 섹션 5-7): 후보 생성 시점(`apply_buy_block_guards`)과 주문 직전(`execute_buy`) 양쪽 차단 판정 유지 — 등락률 변동 방어. 판정 로직은 `is_change_rate_blocked()` 단일 소스.

#### `backend/app/services/engine_sector_confirm.py` (검증)

- `build_buy_targets_from_settings()` 호출부(171-176) — 시그니처 유지(5세션)로 영향 없음 예상.
- 본 세션에서 실제 기동/테스트로 호출부 정상 동작 검증. 수정은 시그니처 변경 시에만 최소 수행.

**유지 (변경 금지)**:
- `execute_buy()` 시그니처(293-303) — 변경 없음
- `BUY_REJECT_RISE_GUARD`/`BUY_REJECT_FALL_GUARD` 상수(53-54) — 유지
- `engine_sector_confirm.py`의 import(79)·호출부(171-176) — 시그니처 유지 시 변경 없음

**검증 방법**:
```bash
# 1단계: 관련 테스트
.venv/bin/python -m pytest backend/tests/test_trading.py -q 2>/dev/null || true
.venv/bin/python -m pytest backend/tests/test_engine_sector_confirm.py -q
.venv/bin/python -m pytest backend/tests/test_buy_order_executor.py -q

# 2단계: 전체 (test_buy_filter.py::TestCreateBuyTargets는 8세션에서 갱신)
.venv/bin/python -m pytest backend/tests -q --ignore=backend/tests/test_buy_filter.py

# 3단계: RuntimeWarning
.venv/bin/python -W error::RuntimeWarning main.py
```

**정량 기준**: 수정 파일 2개, 수정 라인 약 25줄 (기준 미달). 5단계(설계서 섹션 12)·7단계(호출부 검증)를 묶음 — `trading.py` 통합은 3세션(`is_change_rate_blocked`) 의존, `engine_sector_confirm` 검증은 5세션(시그니처 유지) 의존으로 독립성 확보.

---

### 7세션: `engine_service._BUY_BLOCK_UI_KEYS` 분리 + `recompute_buy_targets_only()` 추가

**목표**: `engine_service.py`의 `_SECTOR_UI_KEYS`에서 매수 차단·가산점 키를 분리하여 `_BUY_BLOCK_UI_KEYS`를 신규 생성하고, `sector_data_provider.py`에 경량 재순위 경로 `recompute_buy_targets_only()`를 추가한다 (설계서 섹션 5-8·4 변경 파일 목록)

**수정 파일 목록**:
1. `backend/app/services/engine_service.py` — 구현
2. `backend/app/services/sector_data_provider.py` — 구현

**파일별 변경점**:

#### `backend/app/services/engine_service.py` (구현)

- **분리** `_SECTOR_UI_KEYS`(216-232):
  - 제거: `buy_block_rise_on`, `buy_block_rise_pct`, `buy_block_fall_on`, `buy_block_fall_pct`, `rebuy_block_on`, `boost_*` 7개 키
  - 잔류: `sector_sort_keys`, `sector_min_rise_ratio_pct`, `sector_min_trade_amt`, `sector_max_targets`, `sector_bonus_*` 3개
- **신규 추가** `_BUY_BLOCK_UI_KEYS` (설계서 섹션 5-8):
  - `buy_block_rise_on`, `buy_block_rise_pct`, `buy_block_fall_on`, `buy_block_fall_pct`, `rebuy_block_on`, `boost_*` 7개 (설계 결정 9-2 — 가산점은 매수 순위에만 영향, 업종 재계산 불필요)
- **분기 추가** `_apply_sector_ui_change`(233-242):
  - `_SECTOR_UI_KEYS` 변경 시 기존대로 `recompute_sector_summary_now()` 트리거 (업종 재계산)
  - `_BUY_BLOCK_UI_KEYS` 변경 시 `recompute_buy_targets_only()` 트리거 (경량 재순위, 업종 재계산 생략)
  - 양쪽 교집합 시 업종 재계산 경로 우선 (안전)

#### `backend/app/services/sector_data_provider.py` (구현)

- **신규 추가** `recompute_buy_targets_only()` (설계서 섹션 5-8):
  - `engine_state.state.sector_summary_cache.sectors` 재사용 (업종 스코어 캐시)
  - `build_buy_targets_from_settings(sectors, settings, held_codes, bought_today_codes)`만 재실행
  - `_set_sector_summary()`로 캐시 갱신
  - `notify_buy_targets_update()` 필수 호출 (UI 갱신 보장 — 설계서 섹션 10 회귀 위험 완화)
  - 업종 스코어 재계산 생략 — `compute_full_sector_summary` 미호출
  - `schedule_engine_task()` 사용 (P25 격리된 실패)
  - 실패 시 `logger.warning(..., exc_info=True)` (silent pass 금지)

**유지 (변경 금지)**:
- `recompute_sector_summary_now()`(254-314) — 유지, 업종 재계산 경로
- `_on_filter_settings_changed()`(317-323) — 유지

**검증 방법**:
```bash
# 1단계: 관련 테스트
.venv/bin/python -m pytest backend/tests/test_engine_service.py -q 2>/dev/null || true
.venv/bin/python -m pytest backend/tests/test_sector_data_provider.py -q
.venv/bin/python -m pytest backend/tests/test_settings_boost_order_ratio.py -q

# 2단계: 전체 (test_buy_filter.py::TestCreateBuyTargets는 8세션에서 갱신)
.venv/bin/python -m pytest backend/tests -q --ignore=backend/tests/test_buy_filter.py

# 3단계: RuntimeWarning
.venv/bin/python -W error::RuntimeWarning main.py
```

**정량 기준**: 수정 파일 2개, 수정 라인 약 50줄 (기준 경계). 6단계(설계서 섹션 12) — `engine_service` 키 분리와 `recompute_buy_targets_only` 추가가 강결합(키 변경 시 트리거 경로 결정), 단일 세션 묶음.

---

### 8세션: `test_buy_filter.py` 30건 갱신 + 회귀 테스트

**목표**: `test_buy_filter.py`의 `TestCreateBuyTargets` 30개 테스트 메서드가 `create_buy_targets` 직접 호출을 `build_buy_targets_from_settings` 또는 분리된 함수(`select_top_sector_stocks`/`apply_buy_block_guards`/`rank_buy_targets`) 호출로 갱신하고, 신규 함수 단위 테스트를 추가하며, 회귀를 검증한다 (설계서 섹션 8-1·8-2)

**수정 파일 목록**:
1. `backend/tests/test_buy_filter.py` — 테스트 갱신 + 신규 추가

**파일별 변경점**:

#### `backend/tests/test_buy_filter.py` (테스트)

- **import 갱신** (10-14줄):
  - `create_buy_targets` 제거 (5세션에서 제거)
  - `build_buy_targets_from_settings`, `select_top_sector_stocks`, `apply_buy_block_guards`, `rank_buy_targets`, `is_change_rate_blocked` 추가
- **기존 테스트 갱신** `TestCreateBuyTargets` 30개 메서드(439-715):
  - `create_buy_targets([sc], ...)` 직접 호출 → `build_buy_targets_from_settings([sc], _settings(...), ...)` 호출로 교체
  - 또는 분리된 함수 직접 호출 (단위 검증 목적): `select_top_sector_stocks` → `apply_buy_block_guards` → `rank_buy_targets` 순차
  - 동일 입력에 대해 동일 출력 보장 (회귀 검증 — 설계서 섹션 8-2)
  - `test_version_increments`(574-575) 2회 호출 갱신
- **신규 단위 테스트 추가** (설계서 섹션 8-1):
  - `TestSelectTopSectorStocks`: cutoff 미달 제외, max_sectors 초과 시 상위 N개, 빈 sector_scores
  - `TestIsChangeRateBlocked`: 상승률 ≥ limit 차단, 하락률 ≤ limit 차단, 범위 내 통과, `block_rise_on=False` 미차단, `block_rise_pct=0` 무효
  - `TestApplyBuyBlockGuards`: 보유+rebuy_block_on 차단, 금일매수+rebuy_block_on 차단, rebuy_block_on=False 통과
  - `TestRankBuyTargets`: 부합 종목 앞 정렬, boost_score 내림차순, sort_keys 다단계
  - `TestBuildBuyTargetsFromSettings`: 설정 → 3단계 호출 회귀 (기존 `create_buy_targets` 동일 결과)
- **기존 테스트 유지** (변경 없음):
  - `TestCheckStockGuards` 14개(73-150) — `check_stock_guards` 시그니처 유지 (3세션)
  - `TestCalculateBoostScore` 19개(152-437) — `calculate_boost_score` 미변경
  - 헬퍼 `_stock`(19-44), `_sector`(47-68) — 재사용

**검증 방법**:
```bash
# 1단계: 갱신된 테스트
.venv/bin/python -m pytest backend/tests/test_buy_filter.py -q

# 2단계: 전체 (2697 tests)
.venv/bin/python -m pytest backend/tests -q

# 3단계: RuntimeWarning
.venv/bin/python -W error::RuntimeWarning main.py
```

**정량 기준**: 수정 파일 1개, 수정 라인 약 100줄 (50줄 초과). **초과 사유**: 30건 테스트 갱신 + 신규 단위 테스트 4그룹 추가가 단일 파일 내 완결. 분리 시 중간 상태(일부만 갱신)에서 테스트 실패. 단일 세션 묶음 (P24 과잉 분할 회피).

---

### 9세션: 최종 검증 게이트

**목표**: 모든 구현 단계 완료 후 표준 검증 게이트 3단계를 통과한다 (설계서 섹션 8-4)

**수정 파일 목록**: 없음 (검증만)

**검증 방법** (설계서 섹션 8-4):
```bash
# 1단계: 전체 pytest (2697 tests, asyncio_mode=auto)
.venv/bin/python -m pytest backend/tests -q

# 2단계: RuntimeWarning (await 누락 검증 — 금지 패턴 4번째)
.venv/bin/python -W error::RuntimeWarning main.py

# 3단계: 기동 — 0-1-3 명령어로 잔존 프로세스 0건 확인 후 기동
.venv/bin/python main.py
```

**핵심 검증 (전체 pytest 통과만으로는 부족 — 설계서 섹션 8-3)**:
1. `build_buy_targets_from_settings` 회귀 — 기존 `create_buy_targets` 동일 결과 (8세션 회귀 테스트)
2. `trading.py` reject_code 매핑 유지 — `BUY_REJECT_RISE_GUARD`/`BUY_REJECT_FALL_GUARD` (6세션)
3. 경량 재순위 경로 UI 갱신 — `recompute_buy_targets_only()`에서 `notify_buy_targets_update()` 필수 호출 (7세션)
4. `select_top_sector_stocks` 정렬 순서 유지 — `sector_scores` 재정렬 금지 (4세션)
5. `test_engine_sector_confirm.py` 11건 — `build_buy_targets_from_settings` patch 유지 (6세션)
6. `test_buy_order_executor.py` — `rebuy_block_on` 게이트 동작 유지 (6세션)
7. `test_risk_manager.py` — `buy_block_*` 무관 영향 없음 확인

**정량 기준**: 코드 수정 없음. 검증만 수행.

---

## 2. 사용자 결정 항목

> 설계서 섹션 9에서 확정된 사항 이관. 구현 중 추가 결정 시 누적 기록.

| # | 결정 사항 | 확정 내용 | 근거 (설계서) |
|---|----------|-----------|--------------|
| A | `select_top_sector_stocks` 파일 배치 | `sector_calculator.py` — 업종 단위 연산 종결점. `buy_filter.py`는 종목 단위만 담당 | 섹션 9-1 |
| B | `boost_*` 키 소속 | `_BUY_BLOCK_UI_KEYS` 포함 — 가산점은 매수 순위에만 영향, 업종 재계산 불필요 → `recompute_buy_targets_only()` 처리 | 섹션 9-2 |
| C | `create_buy_targets()` 제거 여부 | 제거 — `build_buy_targets_from_settings()`가 동일 경로(3단계 순차 호출)로 수렴. W12(불필요 추상화 금지) | 섹션 9-3 |
| D | 이중 게이트 유지 | 후보 생성(`apply_buy_block_guards`) + 주문 직전(`execute_buy`) 양쪽 차단 판정 유지, 판정 로직은 `is_change_rate_blocked()` 통합. W6(살아있는 안전장치) | 섹션 9-4 |
| E | `min_rise_ratio` 잔여 제거 | `build_buy_targets_from_settings()`에서 `min_rise_ratio` 전달 제거 — `create_buy_targets` 내부 미사용, `select_top_sector_stocks` 미수신 (사전조사 2026-07-31) | 섹션 5-6 정리 항목 (설계안 수정 반영) |

---

## 3. 테스트 계획

> 설계서 섹션 8의 테스트 계획 중 각 세션에 반영되는 항목 매핑. 상세 기대값은 설계서 섹션 8-1 표 참조.

| 함수 | 시나리오 | 반영 세션 | 비고 |
|------|---------|-----------|------|
| `is_change_rate_blocked` | 상승률 ≥ limit → `(True, "상승률")` | 8세션 (신규) | 순수 판정 단위 테스트 |
| | 하락률 ≤ limit → `(True, "하락률")` | 8세션 (신규) | |
| | 범위 내 → `(False, "")` | 8세션 (신규) | |
| | `block_rise_on=False` → 미차단 | 8세션 (신규) | |
| | `block_rise_pct=0` → 무효 → 미차단 | 8세션 (신규) | |
| `check_stock_guards` | 14개 시나리오 | 3세션 (기존 유지) | 시그니처 유지로 변경 없음 |
| `select_top_sector_stocks` | cutoff 미달 제외 | 8세션 (신규) | |
| | max_sectors 초과 시 상위 N개 | 8세션 (신규) | |
| | 빈 sector_scores → 빈 리스트 | 8세션 (신규) | |
| `apply_buy_block_guards` | 보유 + rebuy_block_on → 차단 | 8세션 (신규) | |
| | 금일매수 + rebuy_block_on → 차단 | 8세션 (신규) | |
| | rebuy_block_on=False → 통과 | 8세션 (신규) | |
| `rank_buy_targets` | 부합 종목 앞 정렬 | 8세션 (신규) | |
| | boost_score 내림차순 | 8세션 (신규) | |
| | sort_keys 다단계 | 8세션 (신규) | |
| `build_buy_targets_from_settings` | 설정 → 3단계 호출 회귀 | 8세션 (갱신) | 기존 `create_buy_targets` 30건 갱신 |
| `trading.py` reject_code 매핑 | `BUY_REJECT_RISE_GUARD`/`FALL_GUARD` 유지 | 6세션 (검증) | 기존 테스트 회귀 |
| `recompute_buy_targets_only` | 경량 경로 UI 갱신 | 7세션 (검증) | `notify_buy_targets_update` 호출 |

---

## 4. 런타임 검증 방법

> 백엔드 변경이므로 기동 검증 포함 (선택 섹션 — 설계서 섹션 8-4 3단계와 중복이나, 런타임 기동 체크포인트 보강).

**기동 명령**:
```bash
.venv/bin/python main.py                              # 정상 기동
.venv/bin/python -W error::RuntimeWarning main.py     # await 누락 검증 (금지 패턴 4번째)
```

**체크 포인트** (0-1-3 명령어로 잔존 프로세스 0건 확인 후 기동):
1. 기동 로그에 업종 스코어 계산 + 매수 타겟 생성이 기존과 동일하게 수행되는지 확인
2. 매수 차단 설정(`buy_block_rise_pct` 등) 변경 시 업종 전체 재계산이 아닌 매수 타겟 재순위만 수행되는지 확인 (경량 경로 — 7세션)
3. 가산점 설정(`boost_*`) 변경 시 매수 타겟 재순위만 수행되는지 확인 (7세션)
4. 주문 직전 등락률 차단 시 기존 reject_code(`rise_guard`/`fall_guard`) 로그가 동일하게 출력되는지 확인 (6세션)
5. 매수 후보 목록 UI 갱신이 경량 경로에서도 정상 수행되는지 확인 (7세션)

---

## 5. 바로잡음 로그

> 구현 중 태스크 기재 오류 발견 시 원인+수정 기록. (초기 작성 시 공란)

- **2026-07-31 (태스크 작성 세션)**: 사전조사로 설계안 초안과의 불일치 4건 발견 → 설계서 수정 후 태스크 작성.
  1. 테스트 건수 48건 → 실제 30개 메서드 (`TestCreateBuyTargets`, `test_version_increments` 2회 호출 포함 31 호출 지점). 설계서 섹션 8-2·9-3·10·12 수정.
  2. `trading.py` 차단 로직 줄 범위 428-449 → 실제 428-453 (442-449 판정 + 450-453 로깅/리턴). 설계서 섹션 1·2·4·5-7·10·12 수정.
  3. `recompute_sector_summary_now()` 위치 확인 — `sector_data_provider.py:254` 존재 (설계서 명시와 일치, 조사 중 일시적 보고 오류 정정).
  4. `min_rise_ratio` 잔여 — `build_buy_targets_from_settings`에서 `create_buy_targets`에 전달되나 내부 미사용. 분리 후 `select_top_sector_stocks` 미수신 → 전달 제거 정리 항목으로 설계서 섹션 5-6에 추가.
