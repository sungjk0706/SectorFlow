# 태스크 파일: 보유종목 현재가 avg_price 폴백 제거 — None 명시 처리 구현

> **상태**: 작성 완료, 승인 대기
> **작성일**: 2026-08-01
> **설계서 경로**: `docs/architecture_cur_price_fallback_removal_design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ · 2세션(태스크 파일) ✅ · 3세션(구현) ✅ · 4세션(검증/관찰) ✅ — 독립 검증 게이트 통과, 모의투자 관찰 대기
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P25(격리된 실패)
> **위험도**: 중간 (매도 조건 검사 로직 수정 포함, 단 신규 분기 추가만으로 기존 조건 로직은 변경하지 않음)

---

## 0. 사전조사 결과 요약

> 설계서 1.1·2.1·6절과 실제 코드 라인 교차 검증 완료. 모든 변경점은 단일 세션 내 수행 가능한 크기.

### 0.1 의존성 (수정 파일 · 변경점 · 기준 라인)

| 파일 | 변경점 | 기준 라인 |
|---|---|---|
| `backend/app/services/trade_history.py` | `_position_from_lots()` 반환 dict의 `cur_price` 초기값 `avg_price` → `None`. 동시에 `eval_amt`/`pnl_amount`/`pnl_rate`도 None으로 변경 (폴백 제거 일관성 — avg로 채우면 0손익 위장) | 811-814 |
| `backend/app/services/dry_run.py` | `_recalc_pnl()`의 `cur = int(pos.get("cur_price") or avg)` 폴백 제거. `cur_price is None` 분기 추가 → `eval_amt`/`pnl_amount`/`pnl_rate`를 None으로 설정 후 early return | 231-242 |
| `backend/app/services/trading.py` | 매도 조건 검사 루프 진입부에 `pnl_rate is None`(또는 `cur_price` None) 가드 추가 → `continue` + `logger.debug` ("시세 미수신 — 매도 조건 평가 스킵") | 840-844 |
| `backend/app/services/engine_account.py` | 테스트 모드 스냅샷 합산 시 `eval_amt is None` 가드 추가 → 해당 종목 합산 제외. `total_buy`는 `buy_amt` 기반이므로 None 영향 없음 | 289-292 |

### 0.2 영향 범위

- **백엔드 — 테스트 모드**: 4파일 수정 (위 표). `_recalc_pnl`은 `update_price()`·`record_buy()`·`record_sell()`·`get_positions()` 경로에서 호출되므로 모든 호출 경로에 None 전파가 일관 적용됨.
- **백엔드 — 실전 모드**: 미변경. `engine_account_rest.py`는 이미 `or avg` 폴백이 없고 REST에서 증권사 값 직접 수신, 틱 핸들러도 `price <= 0`이면 스킵 (설계서 1.3·6절).
- **프론트엔드**: 미변경. `computePositionValuation`은 이미 `cur_price == null` → `isNull=true` → '-' 표시로 안전 처리됨 (커밋 9c737f9 확인). 회귀 테스트만 수행.
- **DB**: 스키마 변경 없음. 백업 불필요.
- **거래 로직**: `trading.py` 매도 조건 검사에 None 가드 추가 (신규 분기). 기존 익절/손절/트레일링스탑 조건 로직은 변경하지 않음.

### 0.3 아키텍처 원칙 부합

| 원칙 | 부합 | 근거 |
|---|---|---|
| P10 (SSOT) | ✅ | cur_price 주 소스는 positions 실시간 갱신 값. avg_price 폴백은 잘못된 SSOT 참조 제거 |
| P16 (살아있는 경로) | ✅ | None 가드 추가 후 모든 소비자 경로가 살아있는 경로로 연결. dead code 없음 |
| P20 (폴백 금지) | ✅ | 핵심 — `or avg` 폴백 제거로 None을 정상 경로에서 그대로 노출. silent 위장 제거 |
| P21 (사용자 투명성) | ✅ | 시세 미수신 시 '-' 표시로 "데이터 없음" 명시. 0원 위장 제거 |
| P22 (데이터 정합성) | ✅ | 파생 데이터(eval_amt/pnl_amount)가 원본(cur_price) None 상태를 정확히 반영 |
| P23 (일관성) | ✅ | 테스트 모드 폴백 제거로 실전과 동일 계산 공식 확보 ("공식 동일, 원재료만 소스 다름") |
| P24 (단순성) | ✅ | 실전은 수정 없음. 테스트만 수정하여 최소 변경. 불필요한 추상화 없음 |
| P25 (격리된 실패) | ✅ | 매도 조건 검사에서 None 종목 스킵 시 다른 종목 검사는 정상 진행 |

### 0.4 기존 공통 자산 확인

- **재사용**: `logger` (각 파일 기존 인스턴스), `is_test_mode()` (`engine_account.py` 이미 사용 중), `_base_stk_cd()` (`trading.py` 이미 사용 중). 신규 유틸/상수 불필요.
- **신규 생성**: 없음. 모든 변경은 기존 함수 내 분기 추가/초기값 변경만.
- **용어 일관성 (P23)**: 신규 로그 메시지 "시세 미수신 — 매도 조건 평가 스킵"은 기존 "시세" 표현 사용. "현재가"·"평가손익" 등 기존 용어 사전 준수.

---

## 1. 단계 분할

> 위험도 중간이나 변경 범위가 4파일·단일 로직(폴백 제거 + None 가드)으로 응집되어 있어 **단일 세션(3세션) 구현 + 별도 세션(4세션) 검증/관찰** 2단계 구성. 규칙 0-1 "세션당 1단계"에 따라 분할.

### 1세션 (3세션): 구현 — 폴백 제거 + None 가드 4곳

**목표**: 테스트 모드 4파일의 avg_price 폴백을 제거하고, None을 명시적으로 처리하는 가드를 추가한다.

**수정 파일 목록**:
1. `backend/app/services/trade_history.py`
2. `backend/app/services/dry_run.py`
3. `backend/app/services/trading.py`
4. `backend/app/services/engine_account.py`

**파일별 변경점**:

#### (1) `trade_history.py` — `_position_from_lots()` 초기값 None화

```python
# 811-814줄 변경 전
"cur_price": avg_price,
"eval_amt": buy_amount,
"pnl_amount": 0,
"pnl_rate": 0.0,

# 변경 후
"cur_price": None,
"eval_amt": None,
"pnl_amount": None,
"pnl_rate": None,
```

- 근거: trades 원장에는 현재가 정보 없음. avg_price로 채우면 "0손익" 위장. None으로 두면 프론트엔드가 '-' 표시 (P21). 실시간 틱 수신 시 `update_price()`가 실제 시세로 갱신.

#### (2) `dry_run.py` — `_recalc_pnl()` 폴백 제거 + None 분기

```python
# 231-242줄 변경 전
def _recalc_pnl(pos: dict) -> None:
    """현재가 기준 손익 재계산 (순수 차익: 수수료/세금 제외)."""
    avg = int(pos.get("avg_price", 0))
    cur = int(pos.get("cur_price") or avg)
    qty = int(pos.get("qty", 0))
    total_fee = int(pos.get("total_fee", 0))
    buy_amount = avg * qty
    pos["buy_amount"] = buy_amount
    pos["buy_amt"] = buy_amount + total_fee
    pos["eval_amt"] = cur * qty
    pos["pnl_amount"] = pos["eval_amt"] - buy_amount
    pos["pnl_rate"] = round((pos["pnl_amount"] / buy_amount) * 100, 2) if buy_amount > 0 else 0.0

# 변경 후
def _recalc_pnl(pos: dict) -> None:
    """현재가 기준 손익 재계산 (순수 차익: 수수료/세금 제외).

    cur_price가 None(시세 미수신)인 경우 eval_amt/pnl_amount/pnl_rate를 None으로 설정하여
    avg_price 폴백 위장을 제거 (P20). 하위 소비자는 None을 명시적으로 처리 (P21/P25).
    """
    avg = int(pos.get("avg_price", 0))
    cur_raw = pos.get("cur_price")
    qty = int(pos.get("qty", 0))
    total_fee = int(pos.get("total_fee", 0))
    buy_amount = avg * qty
    pos["buy_amount"] = buy_amount
    pos["buy_amt"] = buy_amount + total_fee
    if cur_raw is None:
        pos["eval_amt"] = None
        pos["pnl_amount"] = None
        pos["pnl_rate"] = None
        return
    cur = int(cur_raw)
    pos["eval_amt"] = cur * qty
    pos["pnl_amount"] = pos["eval_amt"] - buy_amount
    pos["pnl_rate"] = round((pos["pnl_amount"] / buy_amount) * 100, 2) if buy_amount > 0 else 0.0
```

- 적용 범위: 서버 재시작 직후(trades 로드 시점) + 장 시작 2분 전 `_reset_realtime_fields` 초기화 이후 첫 틱 수신 전 구간 모두 포함 (설계서 2.1 결정 2 적용 범위 확인 참조).

#### (3) `trading.py` — 매도 조건 검사 None 가드

```python
# 840-844줄 변경 전
cur_price = float(str(stock.get("cur_price", 0)).replace(",", ""))
qty = int(str(stock.get("qty", 0)).replace(",", ""))
pnl_rate = float(stock.get("pnl_rate", 0))
# 서버 손익값만 사용: 표준 키(pnl_amount) 우선, 하위 호환 키(pnl_amt) 보조.
pnl_amt = float(stock.get("pnl_amount", stock.get("pnl_amt", 0)) or 0)

# 변경 후 (가드를 float 변환 전에 삽입)
cur_price_raw = stock.get("cur_price")
pnl_rate_raw = stock.get("pnl_rate")
# 시세 미수신(cur_price/pnl_rate None) — 평가 불가, 매도 조건 검사 스킵 (P25 격리된 실패)
if cur_price_raw is None or pnl_rate_raw is None:
    logger.debug(
        "시세 미수신 — 매도 조건 평가 스킵 stk_cd=%s stk_nm=%s",
        stk_cd, stk_nm,
    )
    continue
cur_price = float(str(cur_price_raw).replace(",", ""))
qty = int(str(stock.get("qty", 0)).replace(",", ""))
pnl_rate = float(pnl_rate_raw)
# 서버 손익값만 사용: 표준 키(pnl_amount) 우선, 하위 호환 키(pnl_amt) 보조.
# NOTE: 아래 `or 0`은 폴백이 아님 — pnl_rate is None인 종목은 위 가드에서 continue되어
# 이 줄에 도달 불가. 도달한 종목은 cur_price/pnl_rate가 모두 非-None이므로 pnl_amount도 非-None.
# 나중에 "여기도 폴백이 남아있다"고 오해하여 재수정하지 말 것 (P20 위반 아님).
pnl_amt = float(stock.get("pnl_amount", stock.get("pnl_amt", 0)) or 0)
```

- `pnl_amt`도 `pnl_amount is None`이면 0으로 폴백(`or 0`)되나, 위 가드에서 `pnl_rate is None`이면 이미 continue되므로 도달하지 않음. 일관성 차원에서 가드 조건에 `pnl_rate_raw is None`만으로 충분 (`_recalc_pnl`에서 cur_price None일 때 pnl_rate도 동시 None 설정).
- **`pnl_amt` 줄에 오해 방지 주석 필수**: `or 0`이 폴백처럼 보이나 실제로는 도달 불가 경로이므로 P20 위반이 아님. 코드에 `NOTE:` 주석으로 명시 (위 코드 블록 참조). 다른 세션에서 이 줄만 보고 "폴백 잔존"으로 재수정하는 것을 방지.
- `logger`는 `trading.py` 기존 모듈 레벨 인스턴스 사용 (이미 존재 — 신규 import 불필요, 구현 시 확인).

#### (4) `engine_account.py` — 스냅샷 합산 None 가드

```python
# 289-292줄 변경 전
total_buy = sum(int(p.get("buy_amt", 0) or 0) for p in pos)
total_eval = sum(int(p.get("eval_amt", 0) or 0) for p in pos)
total_pnl = total_eval - total_buy
total_rate = round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0

# 변경 후
total_buy = sum(int(p.get("buy_amt", 0) or 0) for p in pos)
# eval_amt가 None(시세 미수신)인 종목은 합산에서 제외 (P20 폴백 금지, P25 격리)
total_eval = sum(int(p["eval_amt"]) for p in pos if p.get("eval_amt") is not None)
total_pnl = total_eval - total_buy
total_rate = round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0
```

- `total_buy`는 `buy_amt` 기반이므로 None 영향 없음 (매입가는 항상 존재).
- 프론트엔드는 스냅샷 totals가 아닌 `cur_price`/`avg_price`로 직접 재계산하므로, totals 정확도 저하(시세 미수신 종목 제외)보다 크래시 방지가 우선 (설계서 2.1 결정 4).

**검증 방법 (1세션 완료 후)**:
1. `py_compile`: 4파일 각각 — `.venv/bin/python -m py_compile backend/app/services/{trade_history,dry_run,trading,engine_account}.py`
2. `ruff`: 4파일 각각 — `.venv/bin/python -m ruff check backend/app/services/{trade_history,dry_run,trading,engine_account}.py`
3. `pytest` (관련 테스트): `.venv/bin/python -m pytest backend/tests -q -k "pnl or recalc or position or sell_condition or account_snapshot or dry_run or trade_history"`
4. `pytest` (전체 회귀): `.venv/bin/python -m pytest backend/tests -q` (2697 tests)
5. `RuntimeWarning`: `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락 검증 — 0-1-3 명령어로 잔존 프로세스 0건 확인 후 기동)
6. 프론트엔드 회귀: `cd frontend && npm run typecheck && npm run build && npm run test` (cur_price=null 처리 회귀)

### 2세션 (4세션): 검증 · 관찰 · 롤백 준비

**목표**: 구현 커밋에 대해 독립 검증 게이트 수행 + 모의투자 관찰 기준 명시 + 롤백 준비.

**수정 파일 목록**: 없음 (검증 전용 세션).

**수행 항목**:
1. **독립 검증 게이트**: 3세션 커밋 해시 + 본 태스크 파일만으로 별도 세션에서 "커밋이 태스크 요구사항 충족하는가" 독립 검토 (AGENTS.md "검증·관찰 계층 게이트" 1항).
2. **모의투자 관찰 기준 명시**: 본 태스크 파일 섹션 7에 따라 관찰 항목 체크리스트로 사용자가 직접 확인.
3. **롤백 준비**: 3세션 커밋 해시를 본 태스크 파일 섹션 6에 기록. 문제 시 `git revert <해시>` 즉시 실행 가능 상태 유지.

**검증 방법**: 1세션 검증 항목 재실행 + 모의투자 런타임 관찰 (섹션 7).

---

## 2. 사용자 결정 항목

> 설계서 섹션 3에서 이관. 사전조사로 모든 구현 세부가 확정되었으므로 추가 사용자 질문은 없음. 아래 두 항목은 코드 패턴·아키텍처 원칙(P20/P21/P25)으로 자동 결정된 사항을 사용자에게 명시적으로 알리는 것.

| 항목 | 결정 | 사용자 영향 |
|---|---|---|
| 시세 미수신 종목의 매도 조건 검사 | "평가 불가"로 스킵 (매도 안 함) | 시세가 안 들어오는 종목은 자동매도가 동작하지 않음. 시세 수신 재개 시 정상 동작. 수동 매도는 가능 |
| 폴백 제거 범위 | 테스트 모드 4곳만 (실전 제외) | 테스트 모드에서 시세 미수신 종목이 '-'로 표시됨. 실전은 변화 없음 (이미 폴백 없음) |

---

## 3. 테스트 계획

> 기존 테스트 중 폴백 가정(`cur_price == avg_price` 초기 상태)에 의존하는 케이스가 회귀 실패할 수 있음. 구현 시 실패하는 테스트 식별 후, 본 태스크의 새 동작(None 전파)에 맞게 테스트 단언문 갱신.

**신규/갱신 테스트 대상**:
1. `_position_from_lots()` 반환값 단언 — `cur_price is None`, `eval_amt is None`, `pnl_amount is None`, `pnl_rate is None` (기존 `== avg_price`/`== buy_amount`/`== 0` 단언 갱신)
2. `_recalc_pnl()` — `cur_price=None` 입력 시 `eval_amt`/`pnl_amount`/`pnl_rate`가 None인지 단언 (신규 케이스)
3. `_recalc_pnl()` — `cur_price` 정상값 입력 시 기존 공식대로 계산되는지 회귀 단언
4. 매도 조건 검사 — `pnl_rate is None`인 종목이 스킵되는지 단언 (신규 케이스, `trading.py` 관련 테스트)
5. `engine_account.py` 스냅샷 합산 — `eval_amt is None`인 종목이 합산에서 제외되는지 단언 (신규 케이스)

> 구현 세션에서 기존 테스트 회귀 실패 시, 실패 원인이 "폴백 제거로 인한 정상적 동작 변경"인지 "실제 버그"인지 판별 후 갱신. **임의로 판단하고 넘어가지 말 것 — 반드시 5절 바로잡음 로그에 판단 근거("왜 그렇게 결론 내렸는지")를 명시한 후 다음 단계로 진행한다.** 판별 근거 없는 갱신은 금지 (P10 SSOT — 추적 가능성).

---

## 4. 런타임 검증 방법

> 1세션(구현) 완료 후 런타임 기동 검증.

**기동 명령**:
```bash
.venv/bin/python -W error::RuntimeWarning main.py
```

**체크 포인트**:
1. 서버 재시작 직후 보유종목 페이지 로딩 — 시세 미수신 종목이 '-'로 표시되는지 (0원/0.00% 위장 제거 확인)
2. 수익현황 페이지 계좌 현황 섹션 — 시세 미수신 종목이 totals에 0으로 합산되지 않고 제외되는지
3. 틱 수신 시작 후 — '-'였던 종목이 실제 시세로 갱신되어 손익이 표시되는지
4. 매도 조건 검사 로그 — 시세 미수신 종목에 "시세 미수신 — 매도 조건 평가 스킵" debug 로그가 남는지
5. 잔존 프로세스 0건 확인 — 0-1-3 명령어로 기동 전/후 확인

---

## 5. 바로자음 로그

> 구현 중 태스크 기재 오류 발견 시 원인+수정 기록. (현재: 없음)

| 날짜 | 항목 | 원인 | 수정 |
|---|---|---|---|
| — | — | — | — |

---

## 6. 사전 롤백 계획

> 위험도 중간 — 사전 롤백 계획 필수 (AGENTS.md "검증·관찰 계층 게이트" 2항).

### 6.1 구현 커밋 해시

> 3세션(구현) 완료 후 기입.

```
커밋 해시: e0055c6
```

### 6.2 롤백 명령

```bash
git revert <커밋 해시>
```

### 6.3 즉시 롤백 트리거 증상

다음 중 하나라도 발생하면 즉시 롤백 (설계서 7.1절):

| 증상 | 의미 | 확인 방법 |
|---|---|---|
| 매도 조건 검사 에러 로그 (`TypeError`/`AttributeError`) | None 가드 불완전 — 크래시 발생 | 백엔드 로그 `trading.py` 관련 traceback |
| 시세 미수신 종목에 이상한 값 표시 (0원이 아닌 잘못된 숫자) | None 처리 누락 소비자 존재 | 보유종목 페이지 / 수익현황 페이지 화면 |
| 정상 시세 수신 중인데도 손절/익절이 동작하지 않음 | None 가드가 정상 종목까지 스킵 | 모의투자에서 손절/익절 조건 걸리는 종목 관찰 |
| 서버 재시작 직후 화면 깨짐 / 에러 페이지 | 초기 로딩 시 None 처리 크래시 | 서버 재시작 후 첫 화면 로딩 |

### 6.4 독립 검증 결과 (4세션 — 2026-08-01)

> 별도 세션에서 커밋 해시 `e0055c6` + 본 태스크 파일만으로 독립 검토. AGENTS.md "검증·관찰 계층 게이트" 1항 준수.

**1. 커밋-태스크 일치 검토**: 4파일 diff가 태스크 섹션 0.1·1세션 변경점과 정확히 일치.
- `trade_history.py:811-814` — cur_price/eval_amt/pnl_amount/pnl_rate → None ✅
- `dry_run.py:231-252` — `cur_raw = pos.get("cur_price")`, `cur_raw is None` 분기 → 파생값 None + early return ✅
- `trading.py:840-856` — `cur_price_raw`/`pnl_rate_raw` 추출, None 가드 → `continue` + `logger.debug` + NOTE 주석 3줄 ✅
- `engine_account.py:289-293` — `total_eval = sum(int(p["eval_amt"]) for p in pos if p.get("eval_amt") is not None)` ✅

**2. 실전 모드 미변경 주장 검증**: `engine_account_rest.py`에 `or avg`/cur_price 폴백 0건 (grep 확인). 테스트 모드 분기는 `is_test_mode()`로 게이트됨. ✅

**3. 프론트엔드 null 처리 확인**: `profit-math.ts` `computePositionValuation` — `curPrice == null` → `isNull=true` → '-' 표시. 회귀 없음. ✅

**4. 검증 게이트 재실행 결과**:

| 게이트 | 결과 |
|---|---|
| py_compile 4파일 | ✅ 통과 |
| ruff 4파일 | ✅ 수정 라인 위반 0건 (사전 존재 59건은 수정 라인 외 스타일) |
| pytest 관련 (192) | ✅ 192 passed |
| pytest 전체 (2997) | ✅ 2997 passed, 3 warnings (사전 Starlette deprecation) |
| RuntimeWarning 기동 | ✅ 0건 — 엔진 143ms, 정산 대조 일치(169,196원), 5종목 포지션 재구축, 테스트모드=True |
| 프론트엔드 typecheck | ✅ 통과 |
| 프론트엔드 build | ✅ 1.07s |
| 프론트엔드 test | ✅ 403 passed (20 files) |
| 잔존 프로세스 | ✅ 기동 전 0건 / 종료 후 0건 |

**5. 아키텍처 원칙 독립 판별**:

| 원칙 | 판별 | 근거 |
|---|---|---|
| P10 (SSOT) | ✅ | cur_price 주 소스 = 실시간 틱. avg_price 폴백은 잘못된 SSOT 참조 제거 |
| P15 (단일 주문 경로) | ✅ | 매도 조건 검사 루프 변경이나 주문은 여전히 `execute_sell()` 단일 경로 (892·906·923줄) |
| P16 (살아있는 경로) | ✅ | None 가드 분기 도달 가능 — startup 시 `_position_from_lots()` cur_price=None → `get_positions()` → `check_sell_conditions()` 경로. 틱 수신 후 `update_price()`가 실제 시세로 갱신 |
| P20 (폴백 금지) | ✅ | `or avg` 폴백 제거. `pnl_amt` 줄 `or 0`은 NOTE 주석 명시대럼 도달 불가 경로 (위 가드에서 continue) — 폴백 아님 |
| P21 (사용자 투명성) | ✅ | 시세 미수신 시 프론트엔드 '-' 표시. 0원 위장 제거 |
| P22 (데이터 정합성) | ✅ | 파생값(eval_amt/pnl_amount/pnl_rate)이 원본(cur_price) None 상태를 정확 반영 |
| P23 (일관성) | ✅ | 테스트 모드 폴백 제거로 실전과 동일 계산 공식. 신규 로그 "시세 미수신" 기존 용어 사용 |
| P25 (격리된 실패) | ✅ | None 종목 스킵 시 다른 종목 검사 정상 진행. 스냅샷 합산 시 None 종목 제외 |

**6. 금지 패턴 5개 확인**: `asyncio.run()` 0 · `create_task` 무분별 0 · `except: pass` 0 · await 누락 0 (RuntimeWarning 검증) · dead code 0 (모든 분기 도달 가능). ✅

**7. 롤백 준비**: `git revert e0055c6` dry-run 충돌 0건 — 즉시 실행 가능. 트리거는 섹션 6.3 참조.

**독립 검증 결론**: 커밋 `e0055c6`은 본 태스크 파일 요구사항을 충족하며, 모든 검증 게이트 통과, 아키텍처 원칙 위반 0건. 모의투자 2세션 관찰 대기 (섹션 7.2).

---

## 7. 관찰 기준

> 위험도 중간 (설계서는 '중간' 분류). 모의/dry-run 관찰 기간 명시.

### 7.1 모의투자 관찰 기간

- **기간**: 모의투자 2세션 (또는 2거래일). 시간 의존 로직 버그(개장 전, 장 중 틱 누락, 장 마감 등 특정 시간대에만 드러나는 버그) 검증을 위해 최소 2세션 관찰.
- **관찰 모드**: 테스트 모드 (dry_run). 실전 모드는 수정 없음.

### 7.2 사용자 직접 확인 항목

> 사용자가 코딩을 모르므로, 화면에서 직접 비교 가능한 항목 명시.

| 항목 | 기대 현상 | 확인 화면 |
|---|---|---|
| 시세 미수신 종목 표시 | '-' (또는 "시세 확인 중")으로 표시, 0원/0.00% 위장 제거 | 보유종목 페이지 평가손익/수익률 컬럼 |
| 틱 수신 후 갱신 | '-'에서 실제 손익 숫자로 갱신 | 보유종목 페이지 (틱 수신 후) |
| 계좌 현황 합산 | 시세 미수신 종목이 총평가금액에 0으로 잘못 합산되지 않음 | 수익현황 페이지 계좌 현황 섹션 |
| 자동매도 동작 | 시세 수신 중인 종목은 익절/손절/트레일링스탑 정상 동작 | 모의투자에서 조건 걸리는 종목 관찰 + 텔레그램 알림 |
| 시세 미수신 종목 자동매도 | 시세 미수신 종목은 자동매도 동작 안 함 (대기) | 백엔드 로그 "시세 미수신 — 매도 조건 평가 스킵" |

### 7.3 배포 후 모니터링

- 모의투자 관찰 기간 중 이상 징후 시 즉시 섹션 6.3 트리거 적용.
- 관찰 기간 무사 통과 시 실전 모드 적용 검토 (단, 실전 모드는 본 태스크 수정 대상 아님 — 실전은 이미 폴백 없음).
