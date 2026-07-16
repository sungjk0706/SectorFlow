# 구현 계획서: 계좌 잔액 검증 테스트 (회귀 테스트 기반 구축)

> **상태**: 심층 사전조사 완료 · 태스크 파일 작성 완료 · **구현 승인 대기**
> **작성일**: 2026-07-17
> **다단계 작업**: 2세션(태스크 파일 작성) → 3세션(구현)
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P22(데이터 정합성) · P24(단순성)
> **참조 문서**: `backend/docs/settlement_verification_design.md` (디자인 파일)

---

## 1. 배경 및 목적

### 1-1. 문제 현상
테스트모드 계좌 현황에서 불가능한 수치 관찰:
- 누적투자금 10,000,000원 / 주문가능금액 28,372,133원 (누적투자금의 2.8배) / 오늘 매도 금액 51,118,988원
- 손해 보는 중(미실현 평가손익 마이너스)인데 주문가능 금액이 늘어난 모순

### 1-2. 목적
- 근본 원인 특정: 후보 A(정상 작동) / B(매수 차감 누락) / C(비동기 태스크 누락) 중 어느 것인지 검증
- 회귀 테스트 기반 구축: 향후 잔액 오류 재발 방지 안전망

---

## 2. 심층 사전조사 결과 (규칙 0-2 4항목)

### 2-1. 의존성 식별

| 모듈 | 관련 심볼 | 역할 |
|---|---|---|
| `settlement_engine.py` | `_orderable`, `_accumulated_investment`, `_loaded`, `_initial_deposit` (모듈 전역) | 잔액 SSOT. `on_buy_fill`/`on_sell_fill`/`reset`/`_persist`/`_broadcast_delta` |
| `dry_run.py` | `_apply_buy`/`_apply_sell`, `fake_fill_event` | 가상 체결 → settlement_engine 위임. `fake_fill_event`는 0.1초 지연 후 `_apply_buy`/`_apply_sell` 호출 |
| `trade_history.py` | `_insert_trade`, `record_buy`/`record_sell`, `_buy_history`/`_sell_history` | 체결 이력. `_insert_trade`는 직접 호출 가능 (DB 저장은 db_writer 큐 경유) |
| `stock_tables.py` | `save_settlement_state`/`load_settlement_state` | settlement_state 테이블 영속화. `get_db_connection()` 사용 |
| `database.py` | `_db_connection` (싱글톤), `get_db_connection()` | `stocks.db` 경로 하드코딩 |
| `constants.py` | `BUY_COMMISSION=0.00015`, `SELL_COMMISSION=0.00015`, `SECURITIES_TAX=0.002` | 수수료/세금 상수 |

### 2-2. 영향 범위
- **신규 파일 1개**: `backend/tests/test_settlement_verification.py` (회귀 테스트 + 재현 테스트)
- **기존 코드 수정**: 없음 (테스트 파일만 신규 생성)
- **DB 접근**: S1~S5는 인메모리/패치 (원본 DB 미접근). S6은 `backend/data/stocks.db` 읽기 전용 복사본 사용 (원본 보호)

### 2-3. 아키텍처 원칙 부합 여부
- **P10(SSOT)**: `_orderable` 단일 소스 검증 — 테스트에서 독립 계산 금지, `get_orderable()` 반환값만 검증
- **P16(살아있는 경로)**: `fake_fill_event` 비동기 태스크 실행 완료 검증 (S4)
- **P20(폴백 금지)**: `on_buy_fill`/`on_sell_fill` 내 폴백 분기 없음 확인 (코드 분석 + 테스트)
- **P22(데이터 정합성)**: trades 테이블 vs settlement_state 정합성 검증 (S4/S6)
- **P24(단순성)**: 실제 소스코드 import (모킹 금지), 헬퍼 함수 50줄 이하

### 2-4. 기존 공통 자산 확인 (P23 사전 절차)

| 공통 자산 | 위치 | 재사용 방식 |
|---|---|---|
| `_noop_async` 헬퍼 | `test_dry_run.py:27`, `test_dry_run_fill_event.py:32` | 동일 패턴 복사 (async no-op stub) |
| `_setup_dry_run_env` fixture | `test_dry_run.py:38~65` | monkeypatch `_persist`/`_broadcast_delta`/`_ensure_loaded` no-op 패턴 재사용 |
| `_do_buy`/`_do_sell` 헬퍼 | `test_dry_run_fill_event.py:46~64` | record_buy → fake_fill_event 프로덕션 흐름 패턴 재사용 |
| conftest.py 전역 캐시 초기화 | `backend/tests/conftest.py` | 기존 그대로 활용 (수정 불필요) — `trade_history._loaded=False`, DB 연결 정리 이미 포함 |

### 2-5. 심층 기술 조사 (디자인 파일 섹션 7 항목)

#### 2-5-1. settlement_engine 모듈 전역 변수 격리 방식
- `_loaded = True` 설정 → `_load()` 스킵 (DB 로드 차단)
- `_orderable`/`_accumulated_investment`/`_initial_deposit` 직접 할당
- 각 테스트 전 fixture에서 초기화 (기존 `test_dry_run.py` 패턴 준수)
- `reset()` 호출 시 `_persist`/`_broadcast_delta`가 no-op이므로 DB I/O 없이 메모리만 초기화

#### 2-5-2. stock_tables DB 연결 주입 방식
- `save_settlement_state`는 `db_writer.execute_db_write(wait=True)` 사용 → **db_writer 큐가 시작되지 않은 테스트 환경에서 무한 대기** (기존 `test_dry_run_fill_event.py:9~12` 주석에 명시)
- **해결**: 회귀 테스트(S1~S5)는 `_persist`를 no-op으로 패치하여 DB I/O 차단 + 메모리 값 검증
- DB 저장값 정합성 검증이 필요한 경우: `save_settlement_state`를 직접 monkeypatch하여 인메모리 aiosqlite 연결에 저장
- `load_settlement_state`는 `get_db_connection()` 직접 사용 → 인메모리 DB 사용 시 `get_db_connection()` 패치 필요

#### 2-5-3. `_broadcast_delta` 패치 위치
- **테스트 파일 내 fixture** (기존 `test_dry_run.py:43`, `test_dry_run_fill_event.py:86` 패턴 준수)
- conftest.py가 아닌 테스트 파일 내 `monkeypatch.setattr(settlement_engine, "_broadcast_delta", _noop_async)` 사용
- 이유: conftest.py는 전역 캐시 초기화만 담당 (기존 설계 준수, P23 일관성)

#### 2-5-4. `trade_history._insert_trade` 직접 호출 가능 여부
- 직접 호출 가능. `rec` dict를 받아 메모리 `_buy_history`/`_sell_history`에 insert + DB 저장 (db_writer 큐 경유)
- **DB 저장 부분**: `execute_db_write` 호출 → 테스트 환경 무한 대기 가능. 따라서 `execute_db_write`를 no-op으로 패치하거나, 디자인 방식 2(거래 내역 직접 삽입) 채택 시 메모리 리스트 직접 append
- **채택 방식**: S4(태스크 취소 시뮬레이션)에서는 `record_buy` 호출 후 `fake_fill_event` 태스크 취소 → `_insert_trade`의 DB 부분은 `execute_db_write` 패치로 차단, 메모리만 검증

---

## 3. 구현 상세

### 3-1. 테스트 파일 구조

**파일**: `backend/tests/test_settlement_verification.py`
**예상 줄 수**: ~300줄

```
# ── no-op stubs ──
_noop_async()

# ── 픽스처 ──
@pytest.fixture(autouse=True)
async def _setup_settlement_env(monkeypatch):
    # DB I/O 차단 (기존 test_dry_run.py 패턴 재사용)
    # settlement_engine._persist → no-op
    # settlement_engine._broadcast_delta → no-op
    # trade_history._ensure_loaded → no-op
    # trade_history._insert_trade의 DB 부분 → execute_db_write 패치
    # settlement_engine._loaded = True
    # settlement_engine 변수 초기화 (10,000,000)
    # trade_history 메모리 리스트 clear

# ── 헬퍼 ──
async def _do_buy(code, qty, price, stk_nm=""):
    # 기존 test_dry_run_fill_event.py 패턴 재사용
async def _do_sell(code, qty, price, stk_nm=""):
    # 기존 test_dry_run_fill_event.py 패턴 재사용

# ── 회귀 테스트 S1~S5 ──
test_single_buy_deduction()           # S1
test_double_buy_same_stock()          # S2
test_buy_then_sell_sequence()         # S3
test_async_task_cancellation()        # S4-1
test_sync_vs_async_equivalence()      # S4-2
test_repeated_trades_no_drift()       # S5

# ── 재현 테스트 S6 (별도, DB 의존) ──
test_real_db_replay()                 # S6 — 실제 DB 복사본 사용
```

### 3-2. 시나리오별 구현 상세

#### S1: 단일 매수 차감 (test_single_buy_deduction)
- `reset(10_000_000)` → `on_buy_fill(price=100_000, qty=10)`
- 예상: `orderable = 10,000,000 - (1,000,000 + round(1,000,000 * 0.00015))` = 10,000,000 - 1,000,150 = 8,999,850
- `get_orderable() == 8,999,850` 검증
- `get_accumulated_investment() == 10,000,000` (불변) 검증

#### S2: 같은 종목 2회 매수 (test_double_buy_same_stock)
- 1차: `on_buy_fill(100_000, 5)` → 10,000,000 - 500,075 = 9,499,925
- 2차: `on_buy_fill(120_000, 5)` → 9,499,925 - 600,090 = 8,899,835
- `get_orderable() == 8,899,835` 검증

#### S3: 매수 후 매도 (test_buy_then_sell_sequence)
- 매수: `on_buy_fill(100_000, 10)` → 8,999,850
- 매도: `on_sell_fill(110_000, 10, "005930", "삼성전자")`
  - gross = 1,100,000
  - net = 1,100,000 - round(1,100,000 * 0.002) - round(1,100,000 * 0.00015) = 1,100,000 - 2,200 - 165 = 1,097,635
  - orderable = 8,999,850 + 1,097,635 = 10,097,485
- `get_orderable() == 10,097,485` 검증
- `get_accumulated_investment() == 10,000,000` (불변) 검증

#### S4-1: 태스크 취소 시뮬레이션 (test_async_task_cancellation)
- `reset(10_000_000)`
- `record_buy(...)` 호출 (체결 이력 기록)
- `asyncio.create_task(fake_fill_event("BUY", ...))` 후 즉시 태스크 취소 (`task.cancel()`)
- `settlement_engine.load_state()` 재호출 (엔진 재시작 시뮬레이션) — `_loaded=False`로 리셋 후 `load_state()`
- **검증**: `get_orderable() == 10,000,000` (차감 누락 → 원래 값 유지)
- **검증**: `trade_history._buy_history`에 매수 기록 존재 (정합성 위반 상황 재현)
- 이 테스트는 후보 C(비동기 태스크 누락) 재현 — 실제 버그라면 orderable이 틀어지지만, 정상이라면 load_state가 DB에서 원래 값 로드

#### S4-2: 비동기 vs 동기 실행 비교 (test_sync_vs_async_equivalence)
- (a) `asyncio.create_task(fake_fill_event("BUY", ...))` + `await asyncio.sleep(0.2)` (비동기)
- (b) `await dry_run._apply_buy(...)` 직접 호출 (동기)
- 두 방식의 `get_orderable()` 결과 동일성 검증 (경로 대칭성)

#### S5: 반복 거래 오차 누적 (test_repeated_trades_no_drift)
- 5개 종목(A~E) × 매수/매도 3회 = 30건
- 각 거래마다 예상 orderable을 별도 계산하여 추적
- 최종 `get_orderable() == 예상값` 검증 (오차 0원)

#### S6: 실제 DB 거래 재현 (test_real_db_replay)
- `backend/data/stocks.db`를 임시 파일(`tmp/test_stocks_<pid>.db`)로 복사
- 복사본에서 trades 테이블 시간순 조회
- `settlement_engine.reset(10_000_000)` 후 각 거래를 `on_buy_fill`/`on_sell_fill`에 적용
- 최종 계산값 vs DB 저장값(28,372,133) 비교
- 불일치 시 분기 지점 특정 (단계별 추적 로그)
- 테스트 종료 시 임시 파일 자동 삭제 (tmp_path fixture 사용)
- **주의**: 이 테스트는 DB 의존성으로 인해 비결정론적 — 회귀 테스트 기반에서 분리. S6에서 발견한 최소 재현 케이스를 S1~S5 중 하나로 고정하여 회귀 테스트에 편입 (3세션 구현 시 판단)

### 3-3. fixture 상세 (_setup_settlement_env)

```python
@pytest.fixture(autouse=True)
async def _setup_settlement_env(monkeypatch):
    # DB I/O 차단 (기존 test_dry_run.py 패턴 재사용)
    monkeypatch.setattr(settlement_engine, "_persist", _noop_async)
    monkeypatch.setattr(settlement_engine, "_broadcast_delta", _noop_async)
    monkeypatch.setattr(trade_history, "_ensure_loaded", _noop_async)
    # trade_history._insert_trade의 DB 저장 경로 차단
    # (execute_db_write → no-op, 메모리 저장은 유지)
    # → _insert_trade 자체를 패치하거나 execute_db_write 패치

    # DB 로드 스킵
    settlement_engine._loaded = True
    dry_run._positions_loaded = True
    dry_run._positions_dirty = False

    # 인메모리 상태 초기화
    settlement_engine._accumulated_investment = 10_000_000
    settlement_engine._orderable = 10_000_000
    settlement_engine._initial_deposit = 10_000_000
    dry_run._test_positions.clear()
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()

    yield

    # 정리
    dry_run._test_positions.clear()
    trade_history._buy_history.clear()
    trade_history._sell_history.clear()
```

**주의**: S6(test_real_db_replay)은 실제 DB 복사본을 사용하므로 `_persist` no-op 대신 인메모리/임시 DB에 저장하도록 별도 fixture 또는 패치 오버라이드 필요. S6 테스트 함수 내에서 fixture 동작을 부분적으로 우회하는 방식으로 구현.

---

## 4. 세션 분할

### 4-1. 3세션 (구현) — 단일 세션
- **작업**: `backend/tests/test_settlement_verification.py` 신규 작성 (S1~S6 전체)
- **작업량**: ~300줄, 테스트 함수 7개 + fixture + 헬퍼
- **근거**: 단일 파일 신규 생성, 기존 코드 수정 없음, 기존 패턴 재사용으로 복잡도 낮음

### 4-2. 검증 계획 (3세션)
1. `python -m pytest backend/tests/test_settlement_verification.py -v` — 신규 테스트 전체 통과
2. `python -m pytest backend/tests/ -x` — 기존 테스트 회귀 없음 확인
3. `python -m py_compile backend/tests/test_settlement_verification.py` — 컴파일 확인
4. `ruff check backend/tests/test_settlement_verification.py` — 린트 확인
5. S6 실행 시 임시 파일 생성/삭제 확인 (원본 DB 미수정)

### 4-3. 런타임 검증 (별도 세션)
- S6 결과에 따라 근본 원인 특정 후, 별도 세션에서 실제 코드 수정 진행 (후보 B/C 중 하나)
- 본 태스크 파일은 테스트 작성까지만 담당. 코드 수정은 근본 원인 특정 후 별도 다단계 작업으로 진행.

---

## 5. 사용자 결정 항목 (승인 대기)

### 5-1. 구현 승인
- 위 태스크 파일대로 `backend/tests/test_settlement_verification.py`를 신규 작성할지 승인

### 5-2. S6(실제 DB 재현) 포함 여부
- S6은 `backend/data/stocks.db` 읽기 전용 복사본을 사용하므로 원본 DB 보호됨
- 단, 테스트 환경에서 DB 파일 접근이 제한될 수 있음 (경로 의존성)
- **옵션**:
  - (a) S6 포함 — 근본 원인 특정 정확도 최대화
  - (b) S6 제외 — 회귀 테스트(S1~S5)만 작성, 근본 원인 특정은 별도 수동 진행

---

## 6. 아키텍처 원칙 검토

### 6-1. P10 (SSOT)
- 테스트에서 `_orderable`을 독립 계산하지 않고 `get_orderable()` 반환값만 검증
- `state.account_snapshot["orderable"]`와 `settlement_engine.get_orderable()` 동기화 검증 (S3)

### 6-2. P16 (살아있는 경로)
- S4-1: 태스크 취소 시 `fake_fill_event` 미실행 → dead path 확인
- S4-2: 비동기 경로가 실제로 실행 완료되는지 검증

### 6-3. P20 (폴백 금지)
- `on_buy_fill`/`on_sell_fill` 코드 분석: 빈 값/None 폴백 분기 없음 확인 (사전조사 완료)
- 테스트에서 폴백 동작 검증하지 않음 (폴백이 없으므로)

### 6-4. P22 (데이터 정합성)
- S4-1: trades에 매수 기록 있음 + orderable 차감 누락 = 정합성 위반 재현
- S6: 실제 DB에서 trades와 settlement_state 정합성 검증

### 6-5. P24 (단순성)
- 실제 소스코드 import (모킹 금지), DB 연결만 패치
- 헬퍼 함수 50줄 이하 (`_do_buy`/`_do_sell` 각 ~8줄)
- fixture ~30줄

---

## 7. 다음 세션 (3세션) 예정 작업

1. `backend/tests/test_settlement_verification.py` 신규 작성
2. 검증: pytest 실행 + 기존 테스트 회귀 확인 + ruff + py_compile
3. S6 결과 분석: 근본 원인 후보 A/B/C 중 특정
4. 커밋 + HANDOVER.md 갱신
5. 근본 원인 특정 후 코드 수정은 별도 다단계 작업으로 진행 (본 태스크 범위 외)
