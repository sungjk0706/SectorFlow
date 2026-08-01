# 설계서: 보유종목 현재가 avg_price 폴백 제거 — None 명시 처리

> **상태**: 설계 완료, 승인 대기
> **작성일**: 2026-08-01
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P25(격리된 실패)
> **관련 파일**: `backend/app/services/dry_run.py` · `backend/app/services/trade_history.py` · `backend/app/services/trading.py` · `backend/app/services/engine_account.py`
> **관련 API 스펙**: 해당 없음 (내부 계산 로직 수정, API 시그니처 변경 없음)

---

## 1. 배경 및 목표

### 1.1 현재 상태 (문제)

보유종목 페이지 평가손익/수익률 컬럼과 수익현황 페이지 계좌 현황 섹션이 **0원 / 0.00%**로 표시되는 문제.

근본 원인: 테스트 모드에서 보유 포지션의 `cur_price`가 `avg_price`(매입평균가)로 폴백 채워지는 위치가 2곳 존재:

1. **`trade_history.py:811`** — `_position_from_lots()`에서 trades 파생 시 초기값:
   ```python
   "cur_price": avg_price,   # 현재가를 매입가로 초기화
   ```
   trades 원장에는 현재가 정보가 없으므로 매입가로 채움. 설계적 폴백.

2. **`dry_run.py:234`** — `_recalc_pnl()`에서 None을 avg로 덮음:
   ```python
   cur = int(pos.get("cur_price") or avg)   # P20 위반 — None을 avg로 위장
   ```
   `_reset_realtime_fields()`가 `cur_price = None`으로 초기화한 직후, `_recalc_pnl`이 호출되면 avg로 폴백. **이게 진짜 P20 위반 폴백** — "시세 없음"을 "0손익"으로 위장.

**폴백이 위험한 이유 (이번 사례가 증명)**:
- 증상을 지워버림 — 0원/0.00%가 그럴듯한 숫자로 표시되어 사용자가 "본전이구나"로 오해
- 원인 조사를 어렵게 만듦 — "현재가 폴백 취약점"을 별개 문제로 보고하게 함 (실제로는 배선 문제의 또 다른 증상)
- P20(폴백 금지) 원칙 위반 — 정상 경로의 None을 폴백으로 덮음

### 1.2 목표

1. `cur_price`가 없을 때(틱 미수신) avg_price로 폴백하지 않고 **None을 그대로 유지**
2. None 상태에서 하위 소비자(매도 조건 검사, 스냅샷 합산, 프론트엔드 렌더링)가 **크래시 없이 안전하게 처리** — "시세 미수신"을 명시적으로 드러냄 (P21)
3. 테스트 모드와 실전 모드의 PnL 계산 공식을 **동일화** — 실전은 이미 폴백이 없으므로, 테스트의 폴백 제거가 원칙("공식은 동일, 원재료만 소스 다름")을 강화

### 1.3 비목표 (다루지 않는 것)

| 항목 | 사유 |
|---|---|
| 실전 모드 `engine_account_rest.py` 수정 | 실전은 이미 `or avg` 폴백이 없음 (조사 확정). REST에서 증권사 값 직접 수신, 틱 핸들러도 price<=0이면 스킵. 수정 불필요 |
| `test_positions` DB 테이블 DROP | 완료 (2026-08-01, 태스크 `docs/task_drop_test_positions_table.md` 1단계 — RENAME 격리) |
| 실전 모드 `pnl_amount`를 증권사 산출값으로 전환 | 현재 앱이 `eval_amt - buy_amount`로 계산. 증권사가 pnl_amount를 보내준다면 그걸 쓰는 게 맞으나, 별도 이슈. 본 태스크 범위 외 |
| `priceStore` 통합 리팩토링 | 이전 태스크(9c737f9)에서 별도 태스크로 분리됨. 본 태스크 범위 외 |
| 프론트엔드 수정 | `computePositionValuation`은 이미 `cur_price == null`일 때 `isNull=true` → '-' 표시로 안전하게 처리됨 (9c737f9에서 확인). 회귀 테스트만 수행 |

---

## 2. 설계 방향

### 2.1 핵심 설계 결정

**결정 1: `_position_from_lots` 초기값 `cur_price: avg_price` → `cur_price: None`**

- 위치: `trade_history.py:811`
- 왜: trades 원장에는 현재가가 없음. 매입가로 채우면 "0손익"으로 위장됨. None으로 두면 프론트엔드가 '-' 표시 (P21 투명성). 실시간 틱이 오면 `update_price()`가 실제 시세로 갱신.

**결정 2: `_recalc_pnl`의 `or avg` 폴백 제거 — None일 때 eval_amt/pnl_amount/pnl_rate를 None으로 설정**

- 위치: `dry_run.py:231-242`
- 왜: `cur_price`가 None이면 PnL 계산 자체가 불가능. avg로 덮어서 "0손익"으로 위장하는 대신, None을 그대로 전파하여 하위 소비자가 명시적으로 처리하도록 함.
- **적용 범위 확인 (trades 로드 시점 + 장 시작 초기화 이후 첫 틱 전 구간 모두 포함)**: `_reset_realtime_fields`(engine_initial_data.py:181)가 `_test_positions` 캐시의 `cur_price`를 직접 None으로 설정하며, 이후 `_refresh_positions_if_dirty()`(dry_run.py:51-57)의 보존 로직은 `if old.get(f) is not None:` 조건으로 인해 None을 보존하지 않으므로 재구축 시에도 None이 유지됨. 따라서 결정 2는 서버 재시작 직후(trades 로드 시점)뿐 아니라 장 시작 2분 전 실시간 필드 초기화 이후 첫 틱 수신 전 구간에서도 동일하게 적용되어 avg 위장 없이 None이 유지됨.
- 변경 후 동작:
  ```python
  def _recalc_pnl(pos: dict) -> None:
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

**결정 3: 매도 조건 검사(`trading.py`)에 `pnl_rate is None` 가드 추가 — 시세 미수신 시 "평가 불가"로 스킵**

- 위치: `trading.py:840-844`
- 왜: `pnl_rate`가 None이면 `float(None)` → TypeError 크래시. 매도 조건 검사는 시세 기반으로 익절/손절/트레일링스탑을 판단하므로, 시세가 없으면 평가 자체가 불가능. 스킵 + 로깅이 맞음 (P25 격리된 실패).
- 변경 후 동작: `pnl_rate`가 None인 종목은 `continue`로 스킵, `logger.debug`로 "시세 미수신 — 매도 조건 평가 스킵" 기록.

**결정 4: 테스트 모드 스냅샷 합산(`engine_account.py:290`)에 None 가드 추가**

- 위치: `engine_account.py:289-292`
- 왜: `eval_amt`가 None이면 `int(None)` → TypeError. None인 종목은 합산에서 제외하고, hasNullPrice 플래그로 전파하는 것이 맞음. 단, 백엔드 스냅샷은 프론트엔드가 직접 계산하지 않으므로(프론트엔드는 cur_price/avg_price로 직접 계산), 스냅샵 totals의 정확도보다 크래시 방지가 우선.
- 변경 후 동작: `eval_amt`가 None인 종목은 합산에서 제외. `total_eval`/`total_pnl`은 None이 아닌 종목만 합산.

### 2.2 기각 방안

| 방안 | 기각 사유 |
|---|---|
| 폴백 유지 + "시세 확인 중" 텍스트 표시 | 폴백이 문제의 원인. 폴백을 유지하면 0원/0.00% 위장이 지속됨. 근본 해결 아님 |
| `cur_price` 초기값을 0으로 설정 | 0도 "0손익"으로 위장됨. None과 달리 "값이 있다"는 의미를 갖으므로 더 혼란. None이 "없음"을 명확히 표현 |
| 실전 경로도 함께 수정 | 실전은 이미 폴백이 없음 (조사 확정). 불필요한 변경은 P24(단순성) 위반 |
| 매도 조건 검사에서 None일 때 "0%로 간주" | P20 위반. 시세가 없는데 0%로 간주하면 손절/익절 조건이 잘못 트리거될 수 있음. 스킵이 맞음 |

---

## 3. 사용자 결정 항목

| 항목 | 확정 기준 | 사용자 영향 |
|---|---|---|
| 시세 미수신 종목의 매도 조건 검사 | "평가 불가"로 스킵 (매도 안 함) | 시세가 안 들어오는 종목은 자동매도가 동작하지 않음. 시세가 들어오면 정상 동작 재개. 사용자가 수동 매도는 가능 |
| 폴백 제거 범위 | 테스트 모드 4곳만 (실전 제외) | 테스트 모드에서 시세 미수신 종목이 '-'로 표시됨. 실전은 변화 없음 (이미 폴백 없음) |

> 사전조사로 모든 구현 세부가 확정되었으므로, 추가 사용자 질문은 없음. 위 두 항목은 코드 패턴·아키텍처 원칙(P20/P21/P25)으로 자동 결정된 사항을 사용자에게 명시적으로 알리는 것.

---

## 4. 아키텍처 원칙 부합 검토

| 원칙 | 부합 | 근거 |
|---|---|---|
| P10 (SSOT) | ✅ | cur_price의 주 소스는 positions 자체의 실시간 갱신 값. avg_price 폴백은 잘못된 SSOT 참조 |
| P16 (살아있는 경로) | ✅ | None 가드 추가 후 모든 경로가 살아있는 경로로 연결. dead code 없음 |
| P20 (폴백 금지) | ✅ | 핵심 — `or avg` 폴백 제거로 None을 정상 경로에서 그대로 노출. silent 위장 제거 |
| P21 (사용자 투명성) | ✅ | 시세 미수신 시 '-' 표시로 사용자에게 "데이터 없음" 명시. 0원 위장 제거 |
| P22 (데이터 정합성) | ✅ | 파생 데이터(eval_amt/pnl_amount)가 원본(cur_price) None 상태를 정확히 반영. 불일치 시 위장하지 않고 None 전파 |
| P23 (일관성) | ✅ | 테스트 모드 폴백 제거로 실전과 동일한 계산 공식 확보 ("공식 동일, 원재료만 소스 다름") |
| P24 (단순성) | ✅ | 실전은 수정 없음 (이미 폴백 없음). 테스트만 수정하여 최소 변경. 불필요한 추상화 없음 |
| P25 (격리된 실패) | ✅ | 매도 조건 검사에서 None 종목 스킵 시 다른 종목 매도 조건 검사는 정상 진행. 한 종목 실패가 전체 블록 안 함 |

---

## 5. 위험도 산정

**위험도: 중간**

근거: 매도 조건 검사 로직(`trading.py`)을 직접 수정. 매도 조건 검사는 자동매도 핵심 경로이며, 수정이 잘못되면 손절/익절이 동작하지 않거나 잘못 트리거될 수 있음. 단, 수정 범위는 "None 가드 추가" (신규 분기)이지 기존 조건 로직 변경이 아님. 실전 모드는 수정하지 않으므로 실전 투자에는 직접 영향 없음.

### 비개발자용 3줄 요약

- **문제**: 시세가 안 들어올 때 "0원 손익"으로 거짓 표시되는 원인이, 매입가를 현재가로 슬쩍 대체하는 코드(폴백) 때문.
- **해결**: 폴백을 제거하고 시세가 없으면 "시세 확인 중"으로 솔직하게 표시. 매도 자동화도 시세가 없으면 안전하게 대기.
- **위험도**: 중간 — 자동 매도 조건 검사 코드를 건드리므로, 모의투자에서 직접 관찰 후 실전 적용.

---

## 6. 영향 범위

| 영역 | 변경 여부 | 비고 |
|---|---|---|
| 백엔드 — 테스트 모드 | ✅ 수정 | dry_run.py, trade_history.py, trading.py, engine_account.py (4파일) |
| 백엔드 — 실전 모드 | ❌ 미변경 | engine_account_rest.py는 이미 폴백 없음 |
| 프론트엔드 | ❌ 미변경 | 이미 cur_price=null → '-' 처리됨 (9c737f9). 회귀 테스트만 |
| DB | ❌ 미변경 | 스키마 변경 없음 |
| 거래 로직 | ⚠️ 간접 영향 | trading.py 매도 조건 검사에 None 가드 추가. 기존 조건 로직은 변경하지 않음. 시세 미수신 시 매도 안 함이 정상 동작 |

---

## 7. 리스크 / 롤백 기준

### 7.1 롤백 트리거 증상

다음 중 하나라도 발생하면 즉시 롤백:

| 증상 | 의미 | 확인 방법 |
|---|---|---|
| 매도 조건 검사 에러 로그 (`TypeError`/`AttributeError`) | None 가드가 불완전 — 크래시 발생 | 백엔드 로그 `trading.py` 관련 traceback |
| 시세 미수신 종목에 이상한 값 표시 (0원이 아닌 잘못된 숫자) | None 처리가 누락된 소비자 존재 | 보유종목 페이지 / 수익현황 페이지 화면 |
| 정상 시세 수신 중인데도 손절/익절이 동작하지 않음 | None 가드가 정상 종목까지 스킵 | 모의투자에서 손절/익절 조건 걸리는 종목 관찰 |
| 서버 재시작 직후 화면 깨짐 / 에러 페이지 | 초기 로딩 시 None 처리 크래시 | 서버 재시작 후 첫 화면 로딩 |

### 7.2 롤백 명령

구현 완료 후 커밋 해시를 태스크 파일에 기록. 문제 발생 시:
```bash
git revert <커밋 해시>
```
