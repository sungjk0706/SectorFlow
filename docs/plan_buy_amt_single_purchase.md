# 태스크 파일: 종목당 매수금액 설정 역할 분리 (누적 한도 → 1회 매수금액)

> **상태**: 다단계 4세션 완료 — 모의 관찰 게이트 대기
> **작성일**: 2026-08-01
> **설계서**: `docs/architecture_buy_amt_single_purchase_design.md` (본 파일과 불일치 시 **설계서가 SSOT**)
> **다단계 진행**: 1세션(설계) ✅ / 2세션(태스크) ✅ / 3세션(백엔드 거래 로직核心) ✅ 커밋 `30a8fc2` / 4세션(프론트엔드 UI + 주석 + 최종 검증) ✅ 커밋 `<세션 4 해시>`
> **위험도**: 높음 (거래 로직 — `execute_buy()` 주문 금액 산정 경로 수정, P15 단일 주문 경로 내부)
> **관련 원칙**: P10(SSOT) · P15(단일 주문 경로) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패)
> **필수 스킬**: 세션 3·4 진입 시 `safe-trade` 스킬 필수 (매수 주문 금액 계산 경로 수정 — P15 단일 주문 경로 내부)

---

## 0. 사전조사 결과 요약 (설계서 SSOT + 심층 조사 정정)

> 본 태스크 파일은 설계서의 조사 결과·설계 결정을 실행 단위로 구체화한 것. 2세션 심층 사전조사로 설계서 영향 범위를 정정·축소함.

### 0.1 사용자 진단 (전제 — 설계서 섹션 1.1)

> "매수설정에 종목당 일일 한도, 재매수 차단 설정이 충돌이 있어 보인다. 재매수 차단 OFF 시에도 종목당 일일 한도가 있으면 재매수 차단 ON의 효과 아닐까? 종목당 일일 한도가 종목당 1회 한도로 변경해야 하나."

### 0.2 핵심 발견: `buy_amt` 두 파일 해석 불일치 (P10 SSOT 위반)

| 파일 | 해석 | 근거 줄 |
|------|------|---------|
| `backend/app/services/trading.py` | **누적 한도** — `_symbol_daily_buy_spent`와 비교, 잔여만큼 주문 | 389-411줄 |
| `backend/app/services/buy_order_executor.py` | **1회 매수금액** — `buy_amt` 전체를 `effective_buy_amt`로 사용 | 132-164줄 |

재매수 차단 OFF + 같은 종목 재매수 시도 시 `trading.py`의 누적 한도가 사실상 재매수를 금액 제한 → 사용자 "재매수 차단을 껐는데 왜 안 사지?" 혼란 (P21 위반 소지).

### 0.3 심층 사전조사 정정: 설계서 영향 범위 과다 추정 (본 태스크 핵심 정정)

> 설계서 섹션 6 영향 범위가 "백엔드 4파일·프론트 2파일·테스트 70+건"으로 추정되었으나, 2세션 심층 조사 결과 **실제 수정 범위는 훨씬 좁음**. `buy_amt`라는 동일 이름이 두 가지 이질적 개념으로 사용되어 grep 기반 추정이 과다했음.

**두 가지 `buy_amt` 개념 분리 (정정 핵심)**:
| 개념 | 의미 | 사용처 | 본 태스크 수정 여부 |
|------|------|--------|---------------------|
| **설정 `buy_amt`** | 종목당 매수금액 설정값 | `buy-settings.ts`, `settings_defaults.py`, `engine_settings.py`, `trading.py`, `buy_order_executor.py`, `telegram_bot.py` | ✅ 수정 대상 |
| **position `buy_amt`** | 보유종목 1건의 매수금액(수수료 포함 매입원금) | `dry_run.py:239`, `types/index.ts:38,403`, `sell-position.ts`, `buy-target.ts`, `profit-shared.test.ts`, `hotStore.test.ts`, `test_dry_run.py` | ❌ 수정 불필요 (이질 개념) |

**정정된 실제 수정 범위**:

| 파일 | 설계서 추정 | 심층 조사 결과 | 비고 |
|------|-------------|----------------|------|
| `backend/app/services/trading.py` | 핵심 수정 | ✅ 핵심 수정 (유일한 로직 변경) | 누적 한도 로직·상태·상수 제거 |
| `backend/app/services/buy_order_executor.py` | 로직 변경 없음 | ✅ 로직 변경 없음 (설계서 정확) | 이미 1회 매수금액 기반 |
| `backend/app/core/settings_defaults.py` | 주석 갱신 | ⚠️ 주석 갱신 **불필요** — `buy_amt` 필드에 인라인 주석 없음 (33줄 `# 매수 설정` 섹션 헤더만 존재) | 선택적 주석 추가 가능 |
| `backend/app/core/engine_settings.py` | 주석 갱신 | ⚠️ 주석 갱신 **불필요** — `buy_amt` 관련 의미론적 주석 없음 (218-225줄 docstring은 "매수 설정" 일반 표현) | 선택적 주석 추가 가능 |
| `backend/app/services/telegram_bot.py` | 라벨/주석 갱신 | ⚠️ 라벨 **이미 중립적** — 216줄 `"종목당 금액"` (일일 한도 아님) | 변경 불필요, 유지 권장 |
| `frontend/src/pages/buy-settings.ts` | 라벨·infoText 3건 | ✅ 수정 — 351줄 라벨 + 352줄 infoText + 318줄 infoText | 유일한 프론트 수정 |
| `frontend/src/types/index.ts` | 주석 갱신 | ❌ 수정 **불필요** — 161-162줄 설정 인터페이스 필드에 주석 없음; 38·403줄은 position `buy_amt` (이질 개념) | 설계서 오류 정정 |
| 백엔드 테스트 9파일 (70+건) | 다수 수정 | ✅ **1파일 5건만 수정** — `test_trading.py`만 | 상세 0.4절 |
| 프론트 테스트 4파일 | 다수 수정 | ❌ 수정 **불필요** — 모두 position `buy_amt` 또는 키 이름 기반 값 검증 | 상세 0.4절 |

### 0.4 테스트 영향도 상세 분석 (정정)

**수정 필요 — `backend/tests/test_trading.py` (5건)**:
| 테스트 | 줄 | 수정 내용 |
|--------|----|-----------| 
| `test_load_uses_total_amt_sum` | 871-876 | `_load_daily_buy_state` 반환 3-tuple → 2-tuple. `symbol_spent` 변수·assertion 제거 |
| `test_load_real_mode_total_amt_excludes_fee` | 886-888 | 동일 — `symbol_spent` 변수·assertion 제거 |
| `test_load_empty_rows_returns_zero` | 895-898 | 동일 — `symbol_spent == {}` assertion 제거 |
| `test_load_failure_returns_none` | 905-908 | 동일 — `symbol_spent == {}` assertion 제거 |
| `test_post_buy_accumulation_test_mode_includes_fee` | 950 | `assert mgr._symbol_daily_buy_spent["005930"] == ...` 제거 (상태 제거) |
| `test_post_buy_accumulation_real_mode_excludes_fee` | 985 | `assert mgr._symbol_daily_buy_spent["005930"] == ...` 제거 (상태 제거) |

> 참고: `BUY_REJECT_SYMBOL_LIMIT` 사유코드를 직접 assertion하는 테스트는 존재하지 않음 (grep 확인). 누적 한도 도달 차단 경로를 검증하는 테스트도 없음 → 제거 시 회귀 없음.

**수정 불필요 — 키 이름·position 필드 기반 (검증 완료)**:
| 파일 | 줄 | 사유 |
|------|----|------|
| `test_buy_order_executor.py` | 60, 61, 207, 219, 709 등 18건 | `buy_amt`를 1회 매수금액으로 이미 사용 → 로직 변경 없이 통과 |
| `test_engine_settings.py` | 68-78, 180-182 | `_on` 키 마이그레이션 검증 (키 이름 기반) → 변경 없이 통과 |
| `test_telegram_bot.py` | 1966-1969, 2033, 2128-2129 | 설정 dict 값·"종목당 금액" 라벨 검증 → 변경 없이 통과 |
| `test_settings_store.py` | 654-659, 712-713 | `max_daily_total_buy_amt` 검증 (buy_amt 아님) → 통과 |
| `test_dry_run.py` | 12, 77, 123, 256, 260, 264 | position `buy_amt`(매입원금) 검증 → 이질 개념, 통과 |
| `test_engine_account_rest.py` | 348 | position `buy_amt` → 통과 |
| `test_risk_manager.py` | (buy_amt 참조) | RiskManager는 buy_amt 미사용 → 통과 |
| `test_settlement_engine.py` | (buy_amt 참조) | position `buy_amt` → 통과 |
| 프론트 `uiStore.test.ts` | 17-20, 151, 158 | 설정 `buy_amt` 키 이름·값 검증 (의미 미검증) → 키 유지로 통과 |
| 프론트 `profit-shared.test.ts` | 23 | position `buy_amt: avgPrice * qty` → 이질 개념, 통과 |
| 프론트 `hotStore.test.ts` | 1173-1257 | position `buy_amt` → 이질 개념, 통과 |
| 프론트 `order-block-status.test.ts` | (설계서 명시) | buy_amt 참조 없음 (grep 미검출) → 통과 |

### 0.5 비목표 (본 태스크 범위 외 — 설계서 1.3 준수)

- `rebuy_block_on`/`rebuy_block_period` 설정 동작 변경 없음 — 횟수 기반 차단 유지.
- `max_daily_total_buy_amt`(전체 일일 한도) 설정 변경 없음.
- `max_stock_cnt`(최대 보유 종목수) 변경 없음.
- `buy_amt`/`buy_amt_on` 설정 키 이름 변경 없음 (P24 — rename 비용 > 이익).
- 매수 주문 경로(`execute_buy()` 단일 경로, P15) 변경 없음 — 경로 내부 금액 계산 로직만 수정.
- 매도 로직 변경 없음.
- position `buy_amt`(보유종목 매입원금) 필드 변경 없음 — 이질 개념 (0.3절).

### 0.6 아키텍처 원칙 부합 (설계서 섹션 4 요약)

| 원칙 | 판정 | 구현 기준 |
|------|------|-----------|
| P10 (SSOT) | ✅ | `buy_amt` 해석 두 파일 동일(1회 매수금액) 통일. 누적 한도 상태 제거로 단일 진실 소스 회복 |
| P15 (단일 주문 경로) | ✅ | `execute_buy()` 단일 경로 유지. 경로 내부 금액 계산 로직만 수정, 분기/우회 경로 생성 없음 |
| P16 (살아있는 경로) | ✅ | 도달 불가능한 `BUY_REJECT_SYMBOL_LIMIT` 차단 코드 제거. 사용 안 되는 `_symbol_daily_buy_spent` 상태 제거 |
| P20 (폴백 금지) | ✅ | 누적 한도 잔여 계산의 `max(0, ...)` 폴백 패턴 제거 |
| P21 (사용자 투명성) | ✅ | UI 라벨이 실제 동작과 일치("1회 매수금액"). 재매수 차단 OFF 시 반복 매수 허용 명확 |
| P22 (데이터 정합성) | ✅ | 파생 상태(`_symbol_daily_buy_spent`) 제거. `_bought_today`·`_daily_buy_spent`는 `trade_history` 기반 단일 소스 유지 |
| P23 (일관성) | ✅ | UI 텍스트·주석·로그가 "1회 매수금액"으로 통일. 용어 사전 준수 |
| P24 (단순성) | ✅ | 누적 한도 로직 제거로 코드 단순화. 설정 키 rename 회피. 중복 제거 |
| P25 (격리된 실패) | ✅ | 변경이 매수 금액 계산에 한정. 매도·파이프라인·업종 점수 계산 영향 없음 |

---

## 1. 사용자 결정 항목 (설계서 섹션 3)

| 항목 | 확정 기준 | 사용자 영향 |
|------|-----------|-------------|
| 결정 1: `buy_amt` 의미 "종목당 1회 매수금액" 단일화 | `trading.py` 누적 한도 비교 로직 제거, `effective_buy_amt = buy_amt`(매번 전체). `max_daily_total_buy_amt`와의 min 계산은 유지 | 재매수 차단 OFF 시 같은 종목 `buy_amt`만큼 반복 매수 허용 |
| 결정 2: `_symbol_daily_buy_spent` 상태 제거 | 인스턴스 변수·로드 로직·post-buy 갱신 모두 제거. `_bought_today`·`_daily_buy_spent`는 유지 | 코드 단순화, P16 부합 |
| 결정 3: `BUY_REJECT_SYMBOL_LIMIT` 상수·매핑 제거 | 상수 정의·`BUY_REJECT_REASON_TEXT` 매핑 제거. 도달 불가능 차단 코드 | UI "원인" 컬럼 "종목당 한도 초과" 표시 제거 |
| 결정 4: UI 텍스트 "종목당 일일 한도" → "종목당 1회 매수금액" | `buy-settings.ts` 라벨·infoText 3건 갱신 | 설정 패널 라벨이 실제 동작과 일치 |
| 결정 5: 설정 키 `buy_amt`/`buy_amt_on` 이름 유지 | 키 이름 그대로, 주석·UI 텍스트만 갱신 | DB 저장값·API·타입 호환성 유지 |

**사전조사로 확정된 항목 (질문 생략 — 규칙 0-2-6)**:
- `buy_amt` 기본값 100만원 유지 — 사용자 UI 조정 가능.
- 실전/모의 전환 없음 — 본 변경은 모드 무관 공식 변경 (P18 동등성).

---

## 2. 의존성 및 재사용 자산

| 파일 | 역할 | 태스크 적용 기준 |
|------|------|------------------|
| `backend/app/services/trading.py:389-423` | 종목당 한도 + 일일 한도 산정 로직 | 세션 3 — 누적 한도 비교 제거, `effective_buy_amt = buy_amt` 단일화. `buy_amt_on=False` 분기의 414줄 `symbol_spent`(dead, 미사용)도 제거 |
| `backend/app/services/trading.py:245,278` | `_symbol_daily_buy_spent` 인스턴스 변수·로드 배선 | 세션 3 — 변수 선언 제거(245줄), `_ensure_daily_buy_counter` 3-tuple 할당을 2-tuple로 축소(278줄) |
| `backend/app/services/trading.py:249-272` | `_load_daily_buy_state` 반환 시그니처 | 세션 3 — `symbol_spent` 로드 부분(258, 262줄) 제거, 반환 `(spent, bought_today)` 2-tuple로 축소, docstring 갱신 |
| `backend/app/services/trading.py:558` | post-buy `_symbol_daily_buy_spent` 갱신 | 세션 3 — 해당 줄 제거. `_daily_buy_spent`(557줄)는 유지 |
| `backend/app/services/trading.py:56,95` | `BUY_REJECT_SYMBOL_LIMIT` 상수·매핑 | 세션 3 — 상수 정의(56줄)·`BUY_REJECT_REASON_TEXT` 매핑(95줄) 제거 |
| `backend/app/services/buy_order_executor.py:132-164` | 사전 필터 `effective_buy_amt` 산정 | 세션 3 — **변경 없음** (이미 1회 매수금액 기반, 설계서 결정 1 확인). 회귀 only |
| `backend/app/services/buy_order_executor.py:154-164` | `buy_amt_on=False` 분기 | 세션 3 — **변경 없음**. trading.py와 해석 일치화로 자연 해결 |
| `frontend/src/pages/buy-settings.ts:351-352` | "종목당 일일 한도" 라벨·infoText | 세션 4 — 라벨 "종목당 1회 매수금액", infoText "1회 매수 시 금액. 같은 종목 재매수는 '재매수 차단' 설정이 담당." |
| `frontend/src/pages/buy-settings.ts:318` | 전체 일일 한도 infoText | 세션 4 — "종목당 한도가 우선 적용" 표현 제거 → "전체 일일 누적 한도. 수수료 포함. OFF 시 제한 없음." |
| `backend/tests/test_trading.py:860-985` | `_load_daily_buy_state`·post-buy 누적 테스트 | 세션 3 — 5건 반환 시그니처 2-tuple화 + `_symbol_daily_buy_spent` assertion 제거 (0.4절) |

---

## 3. 구현 세션 분할

> 규칙: 한 구현 세션은 아래 단계 중 하나만 수행. 각 단계 완료 후 검증 → 코드 커밋(코드만) → `HANDOVER.md` 갱신(파일만) → 세션 완료 보고(채팅) 순서. 태스크 파일은 모든 단계 완료 시까지 삭제하지 않음.
>
> 세션 순서: 세션 3(백엔드 거래 로직核心 + 테스트) → 세션 4(프론트엔드 UI + 주석 + 최종 검증). 세션 3이 먼저인 이유: 위험도 높은 거래 로직 변경을 독립적으로 검증(pytest)한 뒤 프론트엔드 UI 변경을 분리. 거래 로직 오류 시 롤백 범위를 백엔드 1커밋으로 최소화.

### 세션 3 — 백엔드 거래 로직核心 변경 + 테스트 (위험도 높음)

**목표**: `trading.py`에서 `buy_amt`를 "종목당 1회 매수금액"으로 단일화. 누적 한도 로직·상태·상수 제거. 관련 테스트 5건 수정. `buy_order_executor.py`는 변경 없음(회귀만 검증).

**수정 파일**:
- `backend/app/services/trading.py` (핵심 로직 + 상수)
- `backend/tests/test_trading.py` (5건)

**작업 체크리스트**:

- [ ] `safe-trade` 스킬 invoke (매수 주문 금액 계산 경로 수정 — P15 단일 주문 경로 내부, 위험도 높음).
- [ ] **결정 2 — `_symbol_daily_buy_spent` 상태 제거**:
  - `trading.py:245` — `self._symbol_daily_buy_spent: dict[str, int] = {}` 인스턴스 변수 선언 제거.
  - `trading.py:278` — `self._daily_buy_spent, self._bought_today, self._symbol_daily_buy_spent = await self._load_daily_buy_state()` → `self._daily_buy_spent, self._bought_today = await self._load_daily_buy_state()` 2-tuple 할당으로 축소.
  - `trading.py:249-272` — `_load_daily_buy_state` 본문에서 `symbol_spent` dict 생성(258줄)·`symbol_spent[cd] = ...` 누적(262줄) 제거. 반환 `return spent, bought_today` 2-tuple로 축소. 예외 반환 `return None, {}` 2-tuple로 축소. docstring(250-252줄) "종목당 누적 매수금액 로드" 구절 제거.
- [ ] **결정 1 — 누적 한도 비교 로직 제거** (`trading.py:389-423`):
  - `buy_amt_on=True` 분기(394-411줄):
    - `symbol_spent = self._symbol_daily_buy_spent.get(stk_cd, 0)`(398줄) 제거.
    - `symbol_remain = max(0, int(buy_amt) - symbol_spent)`(399줄) 제거.
    - `if symbol_remain <= 0: ... return False, BUY_REJECT_SYMBOL_LIMIT`(400-402줄) 제거.
    - `effective_buy_amt = min(symbol_remain, daily_remain)`(409줄) → `effective_buy_amt = min(int(buy_amt), daily_remain)`.
    - `else: effective_buy_amt = symbol_remain`(410-411줄) → `else: effective_buy_amt = int(buy_amt)`.
    - 주석(397줄) "종목당 일일 누적 매수금액 한도 체크" → "종목당 1회 매수금액" 갱신.
  - `buy_amt_on=False` 분기(412-423줄):
    - `symbol_spent = self._symbol_daily_buy_spent.get(stk_cd, 0)`(414줄) 제거 (dead code — 미사용 변수).
    - 나머지 daily_remain 로직은 유지.
  - 섹션 주석(389줄) "종목당 일일 최대 매수 금액" → "종목당 1회 매수 금액" 갱신.
- [ ] **결정 3 — `BUY_REJECT_SYMBOL_LIMIT` 상수·매핑 제거**:
  - `trading.py:56` — `BUY_REJECT_SYMBOL_LIMIT = "symbol_limit"` 상수 정의 제거.
  - `trading.py:95` — `BUY_REJECT_REASON_TEXT` 딕셔너리에서 `BUY_REJECT_SYMBOL_LIMIT: "종목당 한도 초과"` 매핑 제거.
  - `BUY_GLOBAL_REJECT_REASONS` frozenset(63-80줄)에 `BUY_REJECT_SYMBOL_LIMIT` 포함되어 있지 않은지 확인 (조회 결과 미포함 — 종목별 차단 사유였음). 포함 시 제거.
- [ ] **post-buy 갱신 제거**:
  - `trading.py:558` — `self._symbol_daily_buy_spent[stk_cd] = self._symbol_daily_buy_spent.get(stk_cd, 0) + max(0, spent)` 제거.
  - `trading.py:557` — `self._daily_buy_spent += max(0, spent)`는 유지 (전체 일일 한도용).
  - 주석(552-553줄) "한도 누적 기준" 갱신 — 종목당 누적 언급 있으면 제거.
- [ ] **테스트 수정 — `test_trading.py` 5건** (0.4절):
  - `test_load_uses_total_amt_sum`(871-876): `spent, bought_today, symbol_spent =` → `spent, bought_today =`. `symbol_spent["005930"]`·`symbol_spent["000660"]` assertion 제거.
  - `test_load_real_mode_total_amt_excludes_fee`(886-888): `spent, _, symbol_spent =` → `spent, _ =`. `symbol_spent["005930"]` assertion 제거.
  - `test_load_empty_rows_returns_zero`(895-898): `spent, bought_today, symbol_spent =` → `spent, bought_today =`. `symbol_spent == {}` assertion 제거.
  - `test_load_failure_returns_none`(905-908): `spent, bought_today, symbol_spent =` → `spent, bought_today =`. `symbol_spent == {}` assertion 제거.
  - `test_post_buy_accumulation_test_mode_includes_fee`(950): `assert mgr._symbol_daily_buy_spent["005930"] == _expected_spent` 제거.
  - `test_post_buy_accumulation_real_mode_excludes_fee`(985): `assert mgr._symbol_daily_buy_spent["005930"] == _expected_base` 제거.
- [ ] **신규 테스트 추가 (P21/P10 검증 — 모의 관찰 게이트 대응)**:
  - `test_rebuy_block_disabled_buys_full_buy_amt_each_time`: 재매수 차단 OFF + 같은 종목 2회 매수 시도 → 2회 모두 `buy_amt` 전체만큼 매수되는지 검증 (누적 한도로 잔여 축소되지 않음). 핵심 사용자 의도 검증.
  - `test_buy_amt_on_false_no_symbol_spent_reference`: `buy_amt_on=False` 분기가 `_symbol_daily_buy_spent` 참조 없이 동작하는지 검증 (dead code 제거 확인).
- [ ] **`buy_order_executor.py` 회귀 확인** — 변경 없음. `test_buy_order_executor.py` 통과로 1회 매수금액 기반 로직이 여전히 유효한지 확인.
- [ ] `.venv/bin/python -m pytest backend/tests/test_trading.py backend/tests/test_buy_order_executor.py -q` 통과.
- [ ] `.venv/bin/python -m pytest backend/tests -q` 전체 통과 (2697+ tests + 신규 2건).
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — await 누락 없음 (금지 패턴 4번째).
- [ ] 0-1-3 명령어로 잔존 프로세스 0건 확인.

**세션 3 완료 조건**:
- [ ] `buy_amt`가 `trading.py`에서 1회 매수금액으로만 해석 (누적 한도 로직 완전 제거).
- [ ] `_symbol_daily_buy_spent` 상태·`BUY_REJECT_SYMBOL_LIMIT` 상수·매핑 완전 제거 (P16).
- [ ] `buy_order_executor.py` 변경 없음, 회귀 없음.
- [ ] test_trading.py 5건 수정 + 신규 2건 추가, pytest 전체 통과.
- [ ] RuntimeWarning 없음.
- [ ] 해당 세션 코드만 커밋하고 `HANDOVER.md`에 기록.

**위험/주의점**:
1. **P15 단일 주문 경로** — `execute_buy()` 내부 금액 계산 로직만 수정. 분기/우회 경로 생성 절대 금지.
2. **`max_daily_total_buy_amt`와의 min 계산 유지** — 전체 일일 한도는 별개 설정(비목표). `effective_buy_amt = min(buy_amt, daily_remain)` 분기 실수로 제거되지 않도록 주의.
3. **`buy_amt_on=False` 분기의 414줄 dead code** — `symbol_spent`가 계산만 되고 사용되지 않음. 제거 시 `_symbol_daily_buy_spent` 참조가 완전히 사라지는지 확인 (P16).
4. **post-buy 갱신 557줄 vs 558줄** — `_daily_buy_spent`(전체 일일 한도용)는 유지, `_symbol_daily_buy_spent`(종목당 누적용)만 제거. 줄 혼동 주의.
5. **모의투자 우선** — 본 변경은 위험도 높음. 세션 3 완료 후 모의 관찰 게이트(세션 4 이후)에서 검증 전까지 실전 전환 금지.

---

### 세션 4 — 프론트엔드 UI 텍스트 + 주석 + 최종 검증

**목표**: `buy-settings.ts` UI 라벨·infoText를 실제 동작("1회 매수금액")과 일치시키고(P21/P23), 백엔드 주석 정리(선택적), 전체 검증 게이트 통과.

**수정 파일**:
- `frontend/src/pages/buy-settings.ts` (라벨·infoText 3건)
- `backend/app/services/trading.py` (주석 정리 — 세션 3에서 누락 시)
- `backend/app/core/settings_defaults.py` (선택적 주석 추가)
- `backend/app/core/engine_settings.py` (선택적 주석 추가)

**작업 체크리스트**:

- [ ] `safe-trade` 스킬 invoke (매수 설정 UI·주석 — P15 인접, 세션 3 변경 회귀 확인).
- [ ] **결정 4 — `buy-settings.ts` UI 텍스트 3건**:
  - 351줄 라벨: `'종목당 일일 한도'` → `'종목당 1회 매수금액'`.
  - 352줄 infoText: `'종목당 하루 매수 금액 제한. 수수료 포함. OFF 시 한도 없음, 주문가능금액 전체로 매수 시도.'` → `'1회 매수 시 금액. 수수료 포함. OFF 시 한도 없음, 주문가능금액 전체로 매수 시도. 같은 종목 재매수는 "재매수 차단" 설정이 담당.'`
  - 318줄 infoText(전체 일일 한도): `'하루 매수 총액 제한. 수수료 포함. OFF 시 제한 없음, 종목당 한도가 우선 적용.'` → `'전체 일일 누적 한도. 수수료 포함. OFF 시 제한 없음.'` ("종목당 한도가 우선 적용" 제거 — 더 이상 의미 안 맞음).
  - 347줄 주석: `// 종목당 일일 최대 매수 금액 (토글 + 입력)` → `// 종목당 1회 매수 금액 (토글 + 입력)`.
- [ ] **P23 용어 일치 확인** — UI 텍스트 변경 전, 기존 동일 개념 표현을 코드베이스에서 검색하여 일치시켰는지 확인 (규칙 0-2.4). "1회 매수금액" 표현이 다른 UI에 이미 존재하는지 확인.
- [ ] **선택적 주석 추가** (P23 — 설정 의미 명시):
  - `settings_defaults.py:38-39` — `buy_amt_on`/`buy_amt` 위에 인라인 주석 `# 종목당 1회 매수금액 (재매수는 rebuy_block_on이 담당)` 추가 검토 (선택적 — 주석 없던 필드에 추가는 P24 단순성과 균형).
  - `engine_settings.py:226` — `_buy_amt_raw = int(merged["buy_amt"])` 위 주석 추가 검토 (선택적).
  - **주의**: 주석 추가는 선택적. 과도한 주석은 P24 위반이므로, 의미 혼동 위험이 있는 지점만 최소 추가.
- [ ] **`telegram_bot.py` 라벨 유지 확인** — 216줄 `"종목당 금액"`은 이미 중립적 표현. "1회 매수금액"으로 변경할지 사용자 결정 권장 (사전조사 0.3절 — 변경 불필요, 유지 권장).
- [ ] **세션 3 회귀 확인** — `trading.py` 주석이 "1회 매수금액"으로 일관되게 갱신되었는지 확인 (세션 3에서 누락된 주석 보강).
- [ ] `cd frontend && npm run typecheck` 통과.
- [ ] `cd frontend && npm run build` 통과.
- [ ] `cd frontend && npm run test` 통과 (116 tests).
- [ ] `.venv/bin/python -m pytest backend/tests -q` 전체 통과 (세션 3 변경 + 세션 4 주석 회귀).
- [ ] `.venv/bin/python -W error::RuntimeWarning main.py` — await 누락 없음.
- [ ] 0-1-3 명령어로 잔존 프로세스 0건 확인.
- [ ] ARCHITECTURE.md 금지 패턴 5개 점검:
  - `asyncio.run()` 사용 금지 위반 없음.
  - `create_task` 무분별 분리 금지 — `schedule_engine_task()` 사용.
  - `except Exception: pass` 금지 — `logger.warning(..., exc_info=True)`.
  - async 함수 `await` 누락 금지 — RuntimeWarning 검증으로 확인.
  - dead code 방치 금지 — `_symbol_daily_buy_spent`·`BUY_REJECT_SYMBOL_LIMIT` 완전 제거 확인.

**세션 4 완료 조건**:
- [ ] UI 라벨·infoText가 실제 동작과 일치 ("종목당 1회 매수금액").
- [ ] 프론트엔드 typecheck + build + test 통과.
- [ ] 백엔드 pytest + RuntimeWarning 통과.
- [ ] 금지 패턴 5개 위반 없음.
- [ ] 해당 세션 코드만 커밋하고 `HANDOVER.md`에 기록 — 모의 관찰 대기 항목 추가.

---

## 4. 검증 기준 (전체)

| 단계 | 명령어 | 기대 결과 |
|------|--------|-----------|
| 백엔드 단위 테스트 | `.venv/bin/python -m pytest backend/tests -q` | 2697+ tests 통과 (신규 2건 포함) |
| RuntimeWarning | `.venv/bin/python -W error::RuntimeWarning main.py` | await 누락 없음 |
| 잔존 프로세스 | 0-1-3 명령어 | 0건 |
| 프론트 타입체크 | `cd frontend && npm run typecheck` | 통과 |
| 프론트 빌드 | `cd frontend && npm run build` | 통과 |
| 프론트 테스트 | `cd frontend && npm run test` | 116 tests 통과 |

---

## 5. 검증·관찰 계층 게이트 (위험도 높음 — 전 게이트 필수)

> safe-trade 스킬 6-1절 준수. 거래 로직 변경은 위험도 '높음' — 독립 검증·사전 롤백·모의 관찰·배포 후 모니터링 전 게이트 필수.

### 5.1 사전 롤백 계획 (설계서 섹션 7)
- **롤백 명령**: `git revert <세션 3 구현 커밋 해시>` (세션 3 완료 후 해시 기재).
- **즉시 롤백 트리거 증상**:
  - 모의투자에서 같은 종목이 `buy_amt`를 초과해 한 번에 매수되는 현상.
  - 재매수 차단 ON인데 같은 종목이 재매수되는 현상.
  - 매수 주문 금액이 0 또는 예상과 크게 다른 현상.
  - `execute_buy()` 런타임 에러로 매수 전체 차단.

### 5.2 독립 검증 (세션 4 완료 후 별도 세션)
- 완료 보고 후 별도 세션에서 커밋 해시 + 본 태스크 파일만 주고 독립 검토.
- 결과를 `HANDOVER.md` "검증 결과"에 기록.

### 5.3 모의 관찰 (사용자 — 모의투자 dry_run)
- 재매수 차단 OFF + 같은 종목 신호 2회 → 2회 모두 `buy_amt`만큼 매수되는지 확인.
- 재매수 차단 ON + 같은 종목 신호 2회 → 1회만 매수되는지 확인.
- 전체 일일 한도 도달 시 매수 차단되는지 확인.
- 사용자 직접 확인: 텔레그램 알림의 매수 금액 ↔ 프론트 화면 매수 후보 금액 일치.

### 5.4 배포 후 모니터링 (실전 전환 후)
- 장 시작·장 마감·특정 시간대 매수 금액 정상 확인.
- 이상 시 `git revert <세션 3 해시>` 즉시 롤백.

---

## 6. 위험/주의점 (전체)

1. **위험도 높음 — 거래 로직**: `execute_buy()` 주문 금액 산정 경로 수정(P15 내부). 실전 모드에서 실제 주문 금액이 달라질 수 있음. 모의투자에서 먼저 확인 후 실전 적용.
2. **safe-trade 스킬 필수**: 세션 3·4 진입 시 `safe-trade` 스킬 invoke. P15/P16/P18 위반 발견 시 즉시 중단 + 보고.
3. **`max_daily_total_buy_amt` min 계산 유지**: 전체 일일 한도는 별개 설정(비목표). 누적 한도 제거 시 `min(buy_amt, daily_remain)` 분기를 실수로 제거하지 않도록 주의.
4. **두 가지 `buy_amt` 개념 혼동 주의** (0.3절): 설정 `buy_amt`(본 태스크 수정) vs position `buy_amt`(매입원금, 수정 금지). grep 시 이질 개념 필터링 필수.
5. **테스트 수정 범위 좁음** (0.4절): 설계서 추정 70+건 → 실제 5건. 과다 수정 금지(P24). position `buy_amt` 테스트는 건드리지 않음.
6. **`buy_order_executor.py` 변경 없음**: 이미 1회 매수금액 기반. 회귀 테스트만으로 검증. 동일 파일 수정 시 설계서 벗어남.
7. **설정 키 이름 유지** (결정 5): `buy_amt`→`buy_amt_per_order` rename 금지. DB 마이그레이션·프론트 타입·API 전면 수정 유발(P24 위반).
8. **모의 관찰 게이트 전 실전 전환 금지**: 세션 4 완료 후 모의 관찰(5.3절) 통과 전까지 실전 모드 전환 금지.

---

## 7. 미해결 문제 (후속 논의 대상)

- **(A) `telegram_bot.py` 라벨 "종목당 금액" 유지 여부**: 사전조사 0.3절 — 이미 중립적 표현. "1회 매수금액"으로 변경할지 사용자 결정 권장. 본 태스크는 유지 권장.
- **(B) `settings_defaults.py`·`engine_settings.py` 주석 추가 여부**: 사전조사 0.3절 — 기존 주석 없음. 의미 명시를 위한 최소 주석 추가는 선택적(P24 단순성과 균형). 세션 4에서 사용자 결정 권장.
- **(C) 설계서 영향 범위 과다 추정 정정**: 본 태스크 0.3절에서 설계서 섹션 6 영향 범위를 정정함. 설계서 SSOT 원칙상 본 태스크 파일의 정정이 실행 기준. 설계서 갱신 여부는 본 태스크 완료 후 별도 검토.
