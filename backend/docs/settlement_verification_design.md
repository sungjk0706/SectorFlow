# 계좌 잔액 검증 테스트 설계 (2026-07-17)

> **상태**: 설계 검토 완료. 코드 수정 전 사용자 승인 대기.
> **관련 문서**: 사전조사 결과(이 세션 대화 기록), `backend/app/services/settlement_engine.py`, `backend/app/services/dry_run.py`, `backend/app/services/trade_history.py`
> **관련 원칙**: P10(SSOT), P16(살아있는 경로), P20(폴백 금지), P22(데이터 정합성), P24(단순성)

---

## 1. 배경

### 1-1. 문제 현상

테스트모드 계좌 현황에서 불가능한 수치가 관찰됨:

| 항목 | 값 | 비고 |
|---|---|---|
| 누적 투자금 | 10,000,000원 | 초기 설정값 |
| 주문가능 금액 | 28,372,133원 | 누적투자금의 **2.8배** |
| 오늘 매도 금액 | 51,118,988원 | 누적투자금의 **5.1배** |

손해 보는 중(미실현 평가손익 마이너스)인데 주문가능 금액이 늘어나 있는 모순.

### 1-2. 사전조사 결과 (DB 실제 값)

```
settlement_state 테이블 (2026-07-16 14:37:35 마지막 갱신):
  accumulated_investment: 10,000,000원
  orderable:              28,372,133원  ← 누적투자금의 2.8배
  initial_deposit:        10,000,000원
```

trades 테이블: 2026-07-16 기준 매수 3건 / 매도 7건 (07-17 거래 없음).

### 1-3. 잔액 계산 SSOT 구조

```
settlement_engine.py (SSOT)
  ├── _orderable: int              ← 주문가능금액 (유일한 진실 소스)
  ├── _accumulated_investment: int ← 누적투자금 (매수/매도 시 불변)
  └── DB settlement_state (id=1)   ← 영속화

매수 차감 경로:
  trading.execute_buy (주문 성공)
    → trade_history.record_buy (동기 await, 체결 이력)
    → asyncio.create_task(fake_fill_event("BUY", ...))  ← 비동기, 0.1초 지연
        → dry_run._apply_buy
            → settlement_engine.on_buy_fill(price, qty)
                → _orderable -= (price*qty + 매수수수료)
                → _persist() (DB 저장)

매도 증가 경로:
  trading.execute_sell (주문 성공)
    → trade_history.record_sell (동기 await, 체결 이력)
    → asyncio.create_task(fake_fill_event("SELL", ...))  ← 비동기, 0.1초 지연
        → dry_run._apply_sell
            → settlement_engine.on_sell_fill(price, qty, ...)
                → _orderable += (price*qty - 세금 - 매도수수료)
                → _persist() (DB 저장)
```

### 1-4. 근본 원인 후보

| 후보 | 설명 | 가능성 |
|---|---|---|
| **A — 정상 작동, 사용자 오해** | 매도 실현 수익이 현금에 누적된 정상 결과. 미실현 손익(보유 종목)과 실현 수익(매도 완료)은 별개. | 중. 하지만 orderable이 누적투자금의 2.8배는 수치적으로 설명 필요 |
| **B — 매수 차감 누락** | 매수 경로의 차감이 누락되는 비대칭 버그. 대략 계산 시 약 10,000,000 차이(초기투자금과 유사)가 발견됨. | 중-고. 비대칭 경로 존재 가능성 |
| **C — 비동기 태스크 누락** | `asyncio.create_task(fake_fill_event(...))`가 엔진 재시작 시 미실행. record_buy/sell은 처리되었으나 on_buy_fill/on_sell_fill은 누락. 매도 후 재시작이 잦았다면 orderable 편향. | 중. 매수/매도 대칭이지만 빈도 편향 가능 |

---

## 2. 검증 테스트 방식 설계

### 2-1. 핵심 원칙: 실제 소스코드 import

테스트는 **실제 `settlement_engine.py`, `dry_run.py`, `trade_history.py`를 그대로 import**하여 사용. 모킹하지 않음. 오직 DB 연결만 테스트용으로 격리.

### 2-2. DB 격리 방식 (사용자 선택: 실제 DB 복사본 + 거래 내역 하드코딩 조합)

**방식 A — 실제 DB 복사본 (재현 테스트용)**:
- `backend/data/stocks.db`를 임시 파일(`tmp/test_stocks_<pid>.db`)로 복사
- 복사본에서 `settlement_state` + `trades` 테이블을 그대로 사용
- 실제 거래 내역을 settlement_engine 로직에 통과시켜 예상 orderable과 DB 저장값 비교
- 원본 DB 보호 (읽기 전용 복사)
- 테스트 종료 시 임시 파일 자동 삭제

**방식 C — 거래 내역 하드코딩 (회귀 테스트용)**:
- 사전조사에서 확인한 거래 내역(2026-07-14~16, 20건)을 테스트 코드에 직접 입력
- 인메모리 SQLite(`:memory:`)에 trades 테이블 생성 후 하드코딩 데이터 삽입
- 재현성 100% 보장 (DB 상태에 의존하지 않음)
- 향후 회귀 테스트 기반으로 활용

**조합 전략**:
- 근본 원인 특정: 방식 A(실제 DB 복사본)로 실제 거래 재현 → 수치 불일치 지점 식별
- 회귀 테스트 기반: 방식 C(하드코딩)로 최소 재현 케이스를 고정하여 회귀 테스트 작성

### 2-3. 날짜/시간 조작 방식

`trade_history.record_buy/record_sell`은 `datetime.now()`를 사용하여 `ts`/`date`/`time` 필드 생성. 테스트에서 날짜를 조작하는 두 방식:

**방식 1 — monkeypatch `datetime.now()`**:
- `freezegun` 라이브러리 사용 불가 (의존성 추가 금지, P24 단순성)
- 대신 `trade_history` 모듈의 `datetime`을 테스트에서 monkeypatch
- 부작용: 모듈 전역 datetime 교체 → 테스트 간 격리 필요

**방식 2 — 거래 내역 직접 삽입 (채택)**:
- `record_buy/record_sell`을 호출하지 않고 `_insert_trade()`에 직접 dict 삽입
- `ts`/`date`/`time` 필드를 테스트에서 명시적으로 지정
- `datetime.now()` 의존성 제거 → 결정론적 테스트
- 단점: `record_buy/record_sell` 내부 로직(수수료 계산 등)을 테스트에서 재현해야 함
- **채택 이유**: 결정론적 실행이 회귀 테스트 기반 구축 목표에 부합

### 2-4. settlement_engine 상태 격리

`settlement_engine`은 모듈 레벨 전역 변수(`_orderable`, `_accumulated_investment`, `_loaded`)를 사용. 테스트 간 격리 필수:

- 각 테스트 시작 시 `settlement_engine._loaded = False`로 리셋
- `settlement_engine.reset(initial_deposit)` 호출로 초기화
- 테스트용 DB 경로를 `stock_tables` 모듈에 주입 (또는 인메모리 DB 사용)
- `settlement_engine._broadcast_delta()`는 WS 미기동 환경에서 예외 발생 가능 → 테스트에서는 `_broadcast_delta`를 no-op로 패치하거나 예외 무시

---

## 3. 테스트 시나리오 목록

### 3-1. 기본 매수 1건 차감 확인 (S1)

**목적**: 단일 매수 체결 시 orderable이 정확히 차감되는지 확인.

**절차**:
1. `settlement_engine.reset(10_000_000)` → orderable=10,000,000
2. 매수 체결: `on_buy_fill(price=100_000, qty=10)`
3. 예상: orderable = 10,000,000 − (1,000,000 + 150) = 8,999,850 (수수료 0.015%)
4. `get_orderable()` 반환값 == 예상값 검증

**검증 항목**:
- orderable 차감값 정확성 (수수료 포함)
- DB settlement_state에 저장된 값과 메모리 값 일치

### 3-2. 같은 종목 2회 매수 (평균가) (S2)

**목적**: 동일 종목 2회 매수 시 orderable이 2회 모두 차감되는지 확인.

**절차**:
1. reset(10_000_000)
2. 1차 매수: `on_buy_fill(price=100_000, qty=5)` → orderable = 10,000,000 − 500,075 = 9,499,925
3. 2차 매수: `on_buy_fill(price=120_000, qty=5)` → orderable = 9,499,925 − 600,090 = 8,899,835
4. `get_orderable()` == 8,899,835 검증
5. `trade_history.build_positions_from_trades("test")`로 평균가 검증: (500,000+600,000)/10 = 110,000

**검증 항목**:
- 2회 매수 모두 차감 누적
- 평균단가 정확성 (trade_history 파생)

### 3-3. 매수 후 매도 (순서 검증) (S3)

**목적**: 매수 → 매도 순서로 진행 시 orderable이 정확히 차감 후 증가하는지 확인.

**절차**:
1. reset(10_000_000)
2. 매수: `on_buy_fill(price=100_000, qty=10)` → orderable = 8,999,850
3. 매도: `on_sell_fill(price=110_000, qty=10, stk_cd="005930", stk_nm="삼성전자")`
   - gross = 1,100,000
   - net = 1,100,000 − 2,200(세금 0.20%) − 165(수수료 0.015%) = 1,097,635
   - orderable = 8,999,850 + 1,097,635 = 10,097,485
4. `get_orderable()` == 10,097,485 검증
5. 누적투자금 == 10,000,000 (불변) 검증

**검증 항목**:
- 매도 시 세금+수수료 공제 후 순수령 추가
- 누적투자금 매수/매도 시 불변 (P10 SSOT)

### 3-4. 매수 후 엔진 재시작 (비동기 태스크 누락 검증) (S4)

**목적**: 후보 C 검증 — `asyncio.create_task(fake_fill_event(...))`가 실행되지 않은 채 엔진 재시작 시 orderable이 틀어지는지 확인.

**절차 (태스크 취소 시뮬레이션)**:
1. reset(10_000_000)
2. 매수 주문: `trade_history.record_buy(...)` 호출 (체결 이력 기록)
3. `fake_fill_event("BUY", ...)` 태스크 생성 후 **즉시 취소** (엔진 재시작 시뮬레이션)
4. `settlement_engine.load_state()` 재호출 (엔진 재시작 시뮬레이션)
5. `get_orderable()` 검증:
   - **정상**: 10,000,000 (차감 누락 → 원래 값 유지)
   - **오류**: 차감이 적용된 값 (태스크가 취소 전에 실행된 경우)
6. trades 테이블에는 매수 기록이 있지만 orderable은 차감되지 않은 상태 → **불일치 상황 재현**

**절차 (순차 실행 비교)**:
1. reset(10_000_000)
2. 동일 매수를 두 방식으로 실행:
   - (a) `asyncio.create_task(fake_fill_event(...))` + `await asyncio.sleep(0.2)` (비동기)
   - (b) `await dry_run._apply_buy(...)` 직접 호출 (동기)
3. 두 방식의 `get_orderable()` 결과가 동일한지 검증

**검증 항목**:
- 태스크 취소 시 orderable과 trades 테이블 불일치 상황 재현 (후보 C 확인)
- 비동기/동기 실행 결과 동일성 (경로 대칭성)

### 3-5. 여러 종목 반복 거래 (오차 누적 검증) (S5)

**목적**: 5개 종목 × 매수/매도 각 3회 = 30건 거래 시 오차가 누적되는지 확인.

**절차**:
1. reset(10_000_000)
2. 5개 종목(A~E)에 대해 매수→매도 사이클 3회 반복
3. 각 거래마다 예상 orderable을 별도로 계산하여 추적
4. 최종 `get_orderable()` == 예상값 검증 (오차 0원)

**검증 항목**:
- 반복 거래 시 부동소수점/반올림 오차 누적 여부
- 30건 거래 후에도 정확성 유지

### 3-6. 실제 DB 거래 내역 재현 (S6)

**목적**: 방식 A(실제 DB 복사본)로 2026-07-14~16 실제 거래 20건을 재현하여 예상 orderable과 DB 저장값(28,372,133) 비교.

**절차**:
1. `backend/data/stocks.db`를 임시 파일로 복사
2. 복사본에서 trades 테이블의 모든 거래를 시간순으로 조회
3. `settlement_engine.reset(10_000_000)`로 초기화 (초기 상태 재현)
4. 각 거래를 시간순으로 `on_buy_fill`/`on_sell_fill`에 적용
5. 최종 `get_orderable()` 계산값 vs DB 저장값(28,372,133) 비교
6. **불일치 시**: 어느 거래에서 분기가 발생하는지 단계별 추적

**검증 항목**:
- 실제 거래 재현 시 예상값과 DB값 일치 여부
- 불일치 시 분기 지점 특정 (근본 원인 좁히기)

---

## 4. 검증할 의심 경로

### 4-1. 매수 차감 누락 (후보 B)

**의심 경로**: `trading.execute_buy` 내부에서 `trade_history.record_buy`는 동기 await로 실행되지만, `settlement_engine.on_buy_fill`은 `asyncio.create_task`로 비동기 예약됨. 태스크가 실행되기 전에 다음 코드가 진행될 수 있음.

**검증 방법**:
- S4(태스크 취소 시뮬레이션): 매수 후 태스크 취소 → orderable 차감 누락 재현
- S6(실제 DB 재현): 실제 거래에서 매수 차감이 누락된 거래가 있는지 단계별 추적
- 코드 경로 분석: `execute_buy`에서 `record_buy`와 `fake_fill_event` 사이에 예외/return가 있는지 확인

### 4-2. 비동기 태스크 누락 (후보 C)

**의심 경로**: 엔진 재시작 시 `asyncio.create_task`로 예약된 `fake_fill_event`가 소멸. `record_buy/record_sell`은 이미 DB에 기록되었으나 `on_buy_fill/on_sell_fill`은 미실행.

**검증 방법**:
- S4(태스크 취소 시뮬레이션): 태스크 취소 후 `load_state()` 재호출 → orderable과 trades 불일치 확인
- S4(순차 실행 비교): 비동기 vs 동기 실행 결과 비교
- 빈도 편향 분석: 실제 trades에서 매도 후 재시작이 매수 후 재시작보다 많았는지 로그 확인

### 4-3. 매수/매도 비대칭 경로

**의심 경로**: 매수와 매도의 차감/증가 로직이 대칭이 아닐 가능성.

**검증 방법**:
- S3(매수 후 매도): 단일 사이클에서 차감+증가 정확성
- S5(반복 거래): 대칭성 유지 검증
- 코드 비교: `on_buy_fill`과 `on_sell_fill`의 수수료/세금 계산 공식 대칭성 확인
  - 매수: `cost = price*qty + round(price*qty * BUY_COMMISSION)`
  - 매도: `net = price*qty - round(price*qty * SECURITIES_TAX) - round(price*qty * SELL_COMMISSION)`
  - 대칭성: 매수는 수수료만, 매도는 세금+수수료 (정상 — 매도가 더 많이 공제됨)

---

## 5. 아키텍처 원칙 검토

### 5-1. P10 (SSOT): _orderable 단일 소스 검증

**검증 항목**:
- `_orderable`이 `settlement_engine.py`에서만 관리되는지 전체 코드베이스 검색
- `state.account_snapshot["orderable"]`가 `settlement_engine.get_orderable()`에서만 파생되는지 확인
- 프론트엔드 `account.orderable`가 백엔드 snapshot에서만 수신되는지 확인 (독립 계산 금지)
- DB `settlement_state` 단일 행(id=1)이 유일한 영속화 소스인지 확인

**테스트 연계**:
- S1~S6 모든 시나리오에서 `get_orderable()`과 DB 저장값 일치 검증
- `state.account_snapshot["orderable"]`와 `settlement_engine.get_orderable()` 동기화 검증

### 5-2. P16 (살아있는 경로): 모든 차감/증가 경로가 실제 실행되는지

**검증 항목**:
- `on_buy_fill`/`on_sell_fill`이 실제 호출 경로에 연결되어 있는지 (dead code 아님)
- `asyncio.create_task(fake_fill_event(...))`가 실제로 실행 완료되는지 (태스크 소멸 가능성)
- `_persist()`가 모든 상태 변경 후 호출되는지

**테스트 연계**:
- S4(태스크 취소 시뮬레이션): 태스크 소멸 시 dead path 확인
- S4(순차 실행 비교): 비동기 경로가 실제로 실행 완료되는지 확인

### 5-3. P20 (폴백 금지)

**검증 항목**:
- `on_buy_fill`/`on_sell_fill`에서 빈 값/None을 폴백으로 덮는 분기가 없는지
- `settlement_engine._load()`에서 DB 로드 실패 시 폴백 처리가 P20 준수하는지

### 5-4. P22 (데이터 정합성)

**검증 항목**:
- `trades` 테이블(체결 이력)과 `settlement_state`(orderable)의 정합성
- 매수/매도 체결 이력이 있지만 orderable이 반영되지 않은 불일치 상황 검출
- 기동 시 대조(reconciliation) 로직 존재 여부 확인

**테스트 연계**:
- S4: trades에 매수 기록 있음 + orderable 차감 누락 = 정합성 위반 재현
- S6: 실제 DB에서 trades와 settlement_state 정합성 검증

### 5-5. P24 (단순성)

**검증 항목**:
- 테스트 코드가 실제 소스코드를 import하여 별도 로직 재구현하지 않는지
- 테스트 헬퍼 함수가 50줄 이하인지

---

## 6. 회귀 테스트 기반 구축 (사용자 선택 목표)

### 6-1. 회귀 테스트 파일 위치

`backend/tests/test_settlement_verification.py`

### 6-2. 회귀 테스트 구성

**픽스처 (conftest.py 또는 테스트 파일 내)**:
- `settlement_engine` 상태 격리 (각 테스트 전 reset)
- 인메모리 DB 연결 (방식 C)
- `_broadcast_delta` no-op 패치

**테스트 함수 (S1~S5 고정 케이스)**:
- S1: `test_single_buy_deduction`
- S2: `test_double_buy_same_stock`
- S3: `test_buy_then_sell_sequence`
- S4: `test_async_task_cancellation` + `test_sync_vs_async_equivalence`
- S5: `test_repeated_trades_no_drift`

**재현 테스트 (S6 — 방식 A, 별도 함수)**:
- `test_real_db_replay`: 실제 DB 복사본 사용 (원본 DB 보호)
- 이 테스트는 회귀 테스트 기반에서 분리 (DB 의존성으로 인해 비결정론적)
- 대신 S6에서 발견한 최소 재현 케이스를 S1~S5 중 하나로 고정하여 회귀 테스트에 편입

### 6-3. 향후 잔액 오류 재발 방지

- 회귀 테스트 S1~S5가 CI/pytest 실행 시마다 자동 검증
- 새로운 매수/매도 경로 추가 시 기존 orderable 계산이 깨지지 않는지 즉시 감지
- `settlement_engine` 로직 수정 시 회귀 테스트가 안전망 역할

---

## 7. 다음 세션 (2세션) 예정 작업

다단계 워크플로우 2세션에서 수행할 작업:

1. **심층 사전조사**: 디자인 파일 기반으로 실제 코드 대상 사전조사 (규칙 0-2 4항목)
   - `settlement_engine` import 시 모듈 전역 변수 격리 방식 상세
   - `stock_tables` DB 연결 주입 방식 (인메모리 DB 경로 설정)
   - `_broadcast_delta` 패치 위치 (conftest.py vs 테스트 파일)
   - `trade_history._insert_trade` 직접 호출 가능 여부

2. **작업량 계산 → 단계 분할**: 테스트 파일 1개 vs 여러 개, conftest 분리 여부

3. **태스크 파일 작성**: `docs/plan_settlement_verification.md`
   - 구현 Step + 세션 분할 + 테스트 계획 + 런타임 검증 방법 + 사용자 결정 항목

---

## 8. 사용자 승인 대기 항목

1. **본 디자인 파일 승인**: 위 설계안(테스트 방식, 시나리오 S1~S6, 회귀 테스트 기반 구축)에 대한 승인
2. 승인 후 2세션(태스크 파일 작성) 진행
