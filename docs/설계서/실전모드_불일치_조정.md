# 설계서: 실전 모드 전환 전 필수 Reconciliation 보완

> **상태**: 설계 (구현 미착수 — 별도 승인 필요)
> **작성일**: 2026-07-31
> **관련 원칙**: P10 · P11 · P18 · P20 · P21 · P22 · P25
> **관련 아키텍처 섹션**: W4(단계 간 정합성) · W7(테스트모드 동등성) · D13(미체결 복구) · D14(잔고 동기화) · D17(런타임 주기적 reconciliation)
> **위험도**: 높음 (실전 모드 돈 I/O 정합성 — 실전 전환 전 필수 보완)

---

## 1. 배경 및 목적

### 1.1 사용자 정제 원칙 (2026-07-31)

사용자가 제시한 "실전 vs 테스트 모드" 역할 정의 정제:

| 영역 | 실전 모드 | 테스트 모드 |
|------|-----------|-------------|
| 매매 판단(전략·신호·순위 등) | 앱이 계산 (동일 로직) | 앱이 계산 (동일 로직) |
| 잔고/주문/체결/손익/수익률 (돈) | 증권사가 SSOT — 확정 데이터를 그대로 신뢰 | 앱의 가상 시뮬레이터가 SSOT 역할 |

핵심: "돈 관련 수치를 계산하는 **공식 자체**"는 테스트/실전 동일, 그 공식에 들어가는 "**원재료(확정 체결가, 확정 수량)**"만 실전은 증권사에서, 테스트는 가상 시뮬레이터에서 온다. 앱이 손익을 독자적으로 재계산해서 증권사 수치와 경쟁하면 안 되고, 확정 체결/잔고는 증권사 응답을 그대로 받아 저장하며, 그 위에서 파생 지표를 계산하는 공식만 공통으로 쓴다.

### 1.2 2026-07-31 코드베이스 조사 결과

5개 항목에 대한 조사 판정:

| # | 항목 | 판정 | 비고 |
|---|------|------|------|
| 1 | 잔고/보유수량 자체 계산 경로 | 구현됨 | 실전: 증권사 REST+WS SSOT. 앱 자체 누적 계산 없음 |
| 2 | 체결 판정 경로 | 구현됨 | 실전: WS "00" 미체결수량 기준. 주문 즉시 체결 마킹 없음 |
| 3 | 손익/수익률 공식 동일 | 부분 구현 | 공식 동일. 실전 rate는 null('-') — 설계 의도(키움 API 미지원) |
| 4 | reconciliation | 부분 구현 | 테스트모드만 완전. 실전은 조회만, 대조 없음. 주기적·이벤트 트리거 누락 |
| 5 | 시뮬레이터 응답 형태 일치 | 부분 구현 | 키움만 일치. LS 불일치. 공통 데이터 모델 부재 |

### 1.3 본 설계의 범위

항목 #4(reconciliation)의 실전 모드 갭 3건 + 항목 #5(응답 형태)의 다중 증권사 갭을 보완하기 위한 설계. 항목 #1·#2·#3은 이미 구현됨 또는 설계 의도이므로 본 설계 범위 외.

---

## 2. 런타임 주기적 Reconciliation (D17)

### 2.1 문제

실전 모드 런타임 중 WS 체결 통보("00" 이벤트)를 놓친 경우, 앱 내부 기록(`state.positions`·`account_snapshot`)과 증권사 서버 실제 계좌가 어긋남. 현재 런타임 중 주기적 증권사 재조회 로직이 전혀 없어 불일치가 조용히 영구화됨.

영향:
- 매도 누락 (보유수량이 실제보다 적게 기록된 경우)
- 잔고 오산 (예수금이 실제보다 많게 기록된 경우 → 과매수)
- 리스크 게이트 오작동 (잔고 기반 차단이 제대로 동작하지 않음)

### 2.2 사전조사 — 현재 구현 상태

- `backend/app/services/daily_time_scheduler.py`: 시간 기반 자동매매 ON/OFF, 장마감 파이프라인, WS 구독 구간 관리. **잔고 재조회 스케줄 없음**.
- `backend/app/services/engine_ws_reg.py:269-313` `restore_subscriptions_after_reconnect()`: 재연결 시 구독 복원만. **체결 누락 감지·복구 없음**.
- `backend/app/services/engine_account.py:178-263` `_update_account_memory()`: 기동 시 증권사 REST 조회. 런타임 호출 경로 없음 (기동 전용).
- 체결 누락 감지: 주문 타임아웃 검증 없음, 주문 상태 추적 없음.

### 2.3 설계 방향

**스케줄링 방식** (P11 폴링 금지 준수):
- `daily_time_scheduler`에 실전 모드 잔고 재조회 스케줄 추가 (예: 장중 1회 — 11:00 또는 14:00).
- 또는 이벤트 트리거: WS 재연결 성공 후, 주문 타임아웃 감지 시.
- `while + sleep` 폴링 금지 — `asyncio` 기반 스케줄링.

**대조 항목**:
- 예수금: `state.account_snapshot.deposit` vs 증권사 kt00001 조회값
- 보유 종목: `state.positions` vs 증권사 kt00018 조회값 (종목별 수량·매입단가)
- 미체결 주문: (D13 구현 후) 내부 주문 상태 vs 증권사 미체결 조회

**불일치 처리** (W4/P22 준수):
- `logger.critical` 경고 + 관련 파이프라인(자동매매) 일시 중단.
- UI 알림(P21) — "잔고 정합성 불일치 감지 — 자동매매 일시 중단. 증권사 조회값으로 동기화 후 재개 필요."
- 자동 보정 여부는 별도 결정 — 테스트모드 `reconcile_with_trades()`는 자동 복구하지만, 실전 모드는 자동 보정 위험(잔고 오차가 실제 손실과 무관한 데이터 오류인지 구분 불가). 1차 설계: 자동 중단 + 사용자 확인 후 수동 동기화.

**테스트모드**: 가상 원장이 SSOT이므로 자기 자신과 대조하는 의미 없음 → 스킵 (W7 동등성 위반 아님).

### 2.4 의존성

| 파일 | 변경점 |
|------|--------|
| `backend/app/services/daily_time_scheduler.py` | 실전 모드 잔고 재조회 스케줄 추가 |
| `backend/app/services/engine_account.py` | `_update_account_memory()` 런타임 호출 경로 + 대조 로직 추가 |
| `backend/app/services/engine_lifecycle.py` | 스케줄 등록 |
| `backend/tests/test_*` | reconciliation 대조·불일치 차단 테스트 |

### 2.5 미해결 설계 질문

- Q1: 자동 보정 vs 사용자 확인 후 수동 동기화 — 1차 설계는 후자. 사용자 결정 필요.
- Q2: 재조회 간격 — 장중 1회(11:00)가 적당한가, 아니면 더 자주(매 시간) 필요한가.
- Q3: 체결 누락 감지 — 주문 제출 후 N초 내 WS "00" 수신 없으면 조회 API로 확인하는 타임아웃 로직을 별도 추가할 것인가.

---

## 3. 실전 모드 기동 시 불일치 대조/차단 (D14 보완)

### 3.1 문제

`engine_bootstrap.py`에서 `_update_account_memory()`로 증권사 REST 조회 후 메모리 반영은 구현되어 있으나, **내부 기록과의 불일치 대조·차단 로직이 없음**. 조회 실패 시 기존 스냅샷 유지(silent fallback) — W8(P20 폴백 금지) 위반 가능.

`engine_lifecycle.py:38` 주석 "증권사 서버가 SSOT이므로 별도 대조 불필요"는 현재 코드 상태를 반영하지만, P22 "불일치 시 즉시 차단" 요건 미충족.

### 3.2 사전조사 — 현재 구현 상태

- `backend/app/services/engine_bootstrap.py:27-36`: 실전 모드 기동 시 `_update_account_memory()` 호출.
- `backend/app/services/engine_account.py:200-205`: 조회 실패 시 `logger.warning` + 기존 스냅샷 유지 (silent fallback).
- 대조 로직: 없음. 조회 성공 시 그대로 반영, 실패 시 기존 유지 — 어느 쪽도 "불일치 감지"가 아님.

### 3.3 설계 방향

**기동 시 대조 절차**:
1. 증권사 REST 조회 (kt00001 예수금 + kt00018 잔고) — 기존 `_update_account_memory()` 재사용.
2. 조회 성공 시: 증권사 값으로 메모리 로드 (기존 동작 유지).
3. 조회 실패 시: 기존 스냅샷 유지가 아닌, `logger.critical` + 자동매매 차단 + UI 알림. silent fallback 제거 (P20/W8).
4. (선택) 기존 내부 기록이 있을 경우, 증권사 값과 대조하여 불일치 시 `logger.critical` + 차단.

**테스트모드**: 기존 `settlement_engine.reconcile_with_trades()` 유지 — 변경 없음.

### 3.4 의존성

| 파일 | 변경점 |
|------|--------|
| `backend/app/services/engine_account.py` | `_update_account_memory_inner()` 조회 실패 시 silent fallback → critical + 차단 |
| `backend/app/services/engine_lifecycle.py` | 주석 "별도 대조 불필요" 제거/정정 |
| `backend/tests/test_engine_bootstrap.py` | 조회 실패 시 차단 검증 테스트 추가 |

---

## 4. 미체결 주문 조회 API 및 기동 복구 (D13)

### 4.1 문제

키움·LS 모두 미체결 주문 조회 API가 미구현. 기동 시 이전 세션의 잔여 미체결 주문이 있어도 감지 불가 → 사용자 모르게 잔여 주문이 체결될 수 있음 (W10/P21 위반).

### 4.2 사전조사 — 현재 구현 상태

- `backend/app/core/kiwoom_rest.py`: `get_deposit_detail()`(kt00001), `get_balance_detail()`(kt00018) 구현. **미체결조회 API 없음**.
- `backend/app/core/ls_rest.py`: 주문 실행만. **잔고·미체결 조회 API 미구현**.
- `kiwoom_order.py:3`: 미체결조회 주석만 존재.
- 런타임: `has_open_buy` 플래그로 실시간 중복 주문 차단 — 기동 시 잔여 복구와는 별개.

### 4.3 설계 방향

**키움 미체결조회 API**:
- 키움 REST API 문서 확인 필요 — 미체결 주문 조회 TR(예: `kt00012` 또는 유사) 식별.
- `kiwoom_rest.py`에 `get_unfilled_orders()` 추가.
- 응답 파싱: 주문번호·종목코드·주문수량·미체결수량·주문가·주문시간.

**LS 미체결조회 API**:
- LS REST API 문서 확인 필요 — 미체결 주문 조회 엔드포인트 식별.
- `ls_rest.py`에 동일 인터페이스 추가.

**기동 시 복구 절차** (D13 요건):
1. 실전 모드 기동 시 미체결 주문 조회 API 호출.
2. 잔여 미체결 주문 존재 시 UI에 명시적 표시 + 사용자 결정(취소/유지) 대기. 자동 처리 금지(W10).
3. 테스트모드는 `fake_send_order()`가 동기식 즉시 체결이므로 미체결 상태 발생 자체가 없음 → 스킵.

### 4.4 의존성

| 파일 | 변경점 |
|------|--------|
| `backend/app/core/kiwoom_rest.py` | `get_unfilled_orders()` 추가 (TR 식별 사전 조사 필요) |
| `backend/app/core/ls_rest.py` | 미체결조회 + 잔고조회 API 추가 |
| `backend/app/services/engine_bootstrap.py` | 기동 시 미체결 조회 + UI 알림 |
| `backend/tests/test_*` | 미체결 조회·복구 테스트 |

### 4.5 선행 조건

- 키움/LS REST API 문서에서 미체결조회 TR/엔드포인트 식별이 선행되어야 함. 본 설계는 API 식별 완료 전까지 구현 불가.

---

## 5. 시뮬레이터 응답 형태 통일 (W7 보완, 다중 증권사)

### 5.1 문제

`dry_run.fake_send_order()`는 키움 응답 구조(`{"success","msg","data":{"output":{"ord_no",...}}}`)를 모방. 단 LS 증권 응답은 `{"success","order_no","raw_res"}` 구조로 불일치. 공통 데이터 모델이 없어 증권사별 분기 처리 필요.

### 5.2 사전조사 — 현재 구현 상태

- `backend/app/services/dry_run.py:118-150` `fake_send_order()`: 키움 구조 모방.
- `backend/app/core/kiwoom_order.py:50-76`: `{"success","msg","data"}` 반환.
- `backend/app/core/ls_providers.py:88-97`: `{"success","order_no","raw_res"}` 반환.
- `backend/app/domain/models.py`: 업종 모델만. `OrderResult`/`Fill`/`AccountBalance` 공통 모델 없음.
- `backend/app/core/broker_providers.py:47-67` `OrderProvider` ABC: 반환값 구조 정규화 약함 (docstring만).

### 5.3 설계 방향

**공통 데이터 모델 도입**:
- `backend/app/domain/models.py`에 `OrderResult` dataclass 추가.
  - 필드: `success: bool`, `order_no: str`, `msg: str`, `raw: dict`.
- 각 증권사 `send_order()`가 `OrderResult` 반환하도록 정규화.
- `dry_run.fake_send_order()`도 `OrderResult` 반환 — 시뮬레이터가 증권사 공통 모델을 채움.
- 호출자(`trading.py`)는 `res.order_no`로 통일 접근 — 증권사별 분기 제거.

**체결 통보·잔고 조회 응답**:
- 체결 통보: WS "00" downstream 호출 체인은 이미 동일 (`on_fill_update` → `_on_fill_after_ws`). 단, 테스트 `fake_fill_event`가 항상 `unex=0`(전량 체결) 가정 — 부분 체결 시나리오 테스트 누락.
- 잔고 조회: `build_positions_from_trades()`가 kt00018 필드 구조 모방 — 이미 동일.

### 5.4 의존성

| 파일 | 변경점 |
|------|--------|
| `backend/app/domain/models.py` | `OrderResult` dataclass 추가 |
| `backend/app/core/kiwoom_order.py` | `OrderResult` 반환으로 정규화 |
| `backend/app/core/ls_providers.py` | `OrderResult` 반환으로 정규화 |
| `backend/app/services/dry_run.py` | `fake_send_order()`가 `OrderResult` 반환 |
| `backend/app/services/trading.py` | `res.order_no` 통일 접근 |
| `backend/tests/test_*` | 정규화 회귀 테스트 |

### 5.5 우선순위

- 본 항목은 다중 증권사(키움+LS) 사용 시에만 치명적.
- 키움 단독 사용 시에는 시뮬레이터가 이미 키움 구조 모방하므로 갭 없음.
- LS 실전 전환 시 필수 — D17/D14/D13 이후 후순위 권장.

---

## 6. 구현 순서 제안

1. **D13 미체결조회 API 식별** (키움/LS REST API 문서 조사) — 선행 조건, 구현 불가항목.
2. **D14 기동 시 대조/차단** — silent fallback 제거, P20/P22 준수. 범위 작음.
3. **D17 런타임 주기적 reconciliation** — 스케줄링 + 대조 + 차단. 범위 중간.
4. **D13 기동 시 미체결 복구** — API 식별 완료 후 구현.
5. **W7 시뮬레이터 응답 형태 통일** — 다중 증권사 확장 시. LS 실전 전환 전.

각 항목은 별도 승인 후 다단계 워크플로우(설계→태스크→구현)로 진행 권장.

---

## 7. 테스트 전략

- **D14**: 조회 실패 시 차단 검증, 조회 성공 시 메모리 로드 검증.
- **D17**: 주기적 스케줄 실행 검증, 불일치 감지·차단 검증, 테스트모드 스킵 검증.
- **D13**: 미체결 주문 있을 시 UI 알림 검증, 없을 시 정상 기동 검증.
- **W7**: `OrderResult` 정규화 후 키움/LS/시뮬레이터 동일 접근 검증.

모든 항목은 기존 테스트 회귀 없음을 교차 검증.

---

## 8. 위험도 및 게이트

- **위험도**: 높음 (실전 모드 돈 I/O 정합성).
- **5단계 게이트**: 전 게이트 필수 — 독립 검증 + 사전 롤백 + 모의 관찰 + 배포 후 모니터링.
- **실전 전환 조건**: 본 설계의 4개 항목(D13/D14/D17/W7) 구현 + 검증 완료 전까지 실전 모드 전환 금지 (안전 규칙 3).
