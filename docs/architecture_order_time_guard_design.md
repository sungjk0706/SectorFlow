# 설계서: 시장가 주문 중단 시간대 게이트 (Order Time Guard)

> **상태**: 설계 완료 · 구현 승인 대기
> **작성일**: 2026-07-17
> **전신**: `docs/plan_order_suspension_by_time.md` (사전조사 + 사용자 결정 완료 → 본 설계서로 통합)
> **관련 원칙**: P10(SSOT) · P13(설정 메모리 상주) · P15(단일 주문 경로) · P16(살아있는 경로) · P17(플래그 단일 소스) · P20(폴백 금지) · P21(사용자 투명성) · P23(일관성) · P24(단순성)

---

## 1. 배경 및 목적

### 1-1. 문제 상황
- 본 앱은 **시장가 단일 운용** (`trading.py` `execute_buy`/`execute_sell` 내 `order_type = "시장가"`)
- 실시간 체결이 불가능한 시간대에 시장가 주문이 들어가면 **미체결 또는 오류** 발생
- 현재 일부 시간대는 차단되어 있으나 **동시호가 2구간(08:50~09:00, 15:20~15:30)이 누락**
- 매도 경로는 시간 체크 자체가 없어 동시호가 시간대에 매도 주문 시도 가능

### 1-2. 목적
- 체결 불가 시간대에 매수/매도 주문을 자동 거부 (매수·매도 동일 적용)
- 체결 가능 시간대가 되면 별도 재개 로직 없이 자동 통과 (시간 기반이므로, P24)
- 사용자가 "왜 주문이 안 들어가지?" 의문을 갖지 않도록 UI에 상태 표시 (P21)
- 사용자가 기능 ON/OFF 선택 가능 (토글, 기본 ON)

---

## 2. 확정된 차단 시간대 맵 (사용자 결정)

> 기준: `/Users/sungjk0706/Desktop/KRX-NXT시간대별장운영정보.txt` + 사용자 원칙 "NXT가 거래 중이면 KRX만 차단, NXT는 허용"

| 시간대 | KRX phase | NXT phase | 처리 | 근거 |
|---|---|---|---|---|
| 00:00~08:00 | 장개시전 | 장개시전 | 양쪽 차단 | 양쪽 비활성 (기존과 동일) |
| **08:00~08:50** | 장전 대기·장전 시간외·동시호가 접수 | 프리마켓 | **KRX만 차단 / NXT 허용** | KRX 시장가 불가, NXT 체결 가능 |
| **08:50~09:00** | 시가 동시호가 | 정규장 준비 | **양쪽 차단** | 양쪽 체결 없음 (09:00 일괄) |
| 09:00~15:20 | 정규장 | 메인마켓 | 양쪽 허용 | 정규 매매 |
| **15:20~15:40** | 종가 동시호가·체결 정산 | 조기 마감·단일가 매매 | **양쪽 차단** | 양쪽 체결 없음/일괄 |
| **15:40~20:00** | 장후 시간외·시간외 단일가·장 종료 | 애프터마켓·애프터마켓 지속 | **KRX만 차단 / NXT 허용** | KRX 시장가 불가, NXT 체결 가능 |
| 20:00~24:00 | 장마감 | 장마감 | 양쪽 차단 | 양쪽 비활성 (기존과 동일) |

### 차단 판별 로직 (단일 함수)
```
is_order_blocked_by_time(stk_cd) -> bool:
  krx = market_phase["krx"]
  nxt = market_phase["nxt"]
  if krx in KRX_INACTIVE_PHASES:
      # KRX 비활성 — NXT 활성 여부로 분기
      if nxt in NXT_ACTIVE_PHASES:
          # NXT-only 구간: 종목이 NXT 활성이면 허용, KRX 단독이면 차단
          return not is_nxt_enabled(stk_cd)
      else:
          # 양쪽 비활성 — 전부 차단
          return True
  else:
      # KRX 활성 — 허용
      return False
```

→ 기존 `is_nxt_only_window()` 패턴과 동일 구조 (P23 일관성). `KRX_INACTIVE_PHASES`·`NXT_ACTIVE_PHASES` 재사용, 새 시간 상수 생성 없음 (P10 SSOT).

---

## 3. 아키텍처 원칙 준수

| 원칙 | 준수 내용 |
|---|---|
| **P10 (SSOT)** | `market_phase` 단일 기준, `KRX_INACTIVE_PHASES`/`NXT_ACTIVE_PHASES` 재사용, 새 시간 상수 생성 금지 |
| **P13 (설정 메모리 상주)** | `order_time_guard_on`을 `integrated_system_settings_cache`에서 조회, 틱 단계 DB 조회 금지 |
| **P15 (단일 주문 경로)** | `execute_buy()`/`execute_sell()` 내부에만 게이트 배선, 분기·우회 경로 생성 금지 |
| **P16 (살아있는 경로)** | 내부 체크가 실제 주문 전송 전 호출 — 외부 사전 필터(`buy_order_executor.py`)는 성능 최적화로 유지 |
| **P17 (플래그 단일 소스)** | `order_time_guard_on`은 `integrated_system_settings_cache`에서만 관리 |
| **P20 (폴백 금지)** | `market_phase` 빈 문자열 시 `logger.error` + False 반환(기존 패턴 유지), silent `except: pass` 금지 |
| **P21 (사용자 투명성)** | 차단 시 헤더 칩 표시 + 설정 토글 제공 |
| **P23 (일관성)** | 기존 `is_nxt_only_window()` 패턴, `createToggleBtn()`, 서킷브레이커 칩 패턴 재사용 |
| **P24 (단순성)** | 시간 기반이므로 별도 재개 로직 불필요, 함수 50줄 이하 유지 |

---

## 4. 백엔드 설계

### 4-1. 차단 판별 함수 (Step 1)
**파일**: `backend/app/services/daily_time_scheduler.py`

신규 함수 `is_order_blocked_by_time(stk_cd: str) -> bool` 추가:
- `state.market_phase`에서 KRX/NXT phase 읽기 (SSOT)
- `KRX_INACTIVE_PHASES`·`NXT_ACTIVE_PHASES` 재사용
- KRX 비활성 + NXT 활성 시 `is_nxt_enabled(stk_cd)`로 종목별 분기 (기존 `buy_order_executor.py:124` 패턴과 동일)
- 빈 문자열 phase 시 `logger.error` + False 반환 (기존 `is_krx_after_hours()` 패턴, P20)
- **기존 `is_krx_after_hours()`는 유지** (영향 범위 최소화, `buy_order_executor.py` 기존 동작 보존)

### 4-2. ±5초 버퍼 (Step 1 내부)
사용자 결정: **주문 체크 시점에만 적용** (phase 산정은 건드리지 않음)
- `is_order_blocked_by_time()` 내부에서만 ±5초 버퍼 계산
- 경계(09:00:00, 15:20:00, 15:40:00 등)에서 ±5초 내면 차단 상태 유지 (안전 측)
- `calc_timebased_market_phase()`는 분 단위 산정(`t = hour*60 + minute`)이므로, 버퍼는 본 함수에서 초 단위로 별도 계산
- 다른 기능(WS 구독, 카운트다운 등)에 영향 없음

### 4-3. execute_buy() 내부 게이트 (Step 2)
**파일**: `backend/app/services/trading.py` (라인 94~, `_execute_buy_locked`)

삽입 위치: 자동매매 게이트(`if not settings["is_auto"] and not force_buy`) **직후**, 재매수 차단 전:
```python
# ── 체결 불가 시간대 주문 게이트 (P15 단일 경로, P16 살아있는 경로) ──
if _is_order_time_blocked(stk_cd, settings):
    return False
```
- `force_buy` 경로 포함 모든 호출 경로 차단 (P15) — 단, 현재 `force_buy=True` 호출부가 없으므로 실질적으로는 자동 경로만 적용 (별도 이슈는 섹션 8 참조)
- 차단 시 `logger.info` + 사용자 안내 (P21)

### 4-4. execute_sell() 내부 게이트 (Step 3)
**파일**: `backend/app/services/trading.py` (라인 450~, `execute_sell`)

삽입 위치: `is_sell_auto` 체크(`if not trade_settings.get("is_sell_auto", False): return`) **직후**:
```python
# ── 체결 불가 시간대 주문 게이트 — 매도 동일 적용 (P15/P16) ──
if _is_order_time_blocked(stk_cd, trade_settings):
    return
```
- 매수·매도 동일 적용 (사용자 의견 반영)
- 매도는 시장가이므로 동시호가 시간대 체결 불가 → 차단 권장

### 4-5. 헬퍼 함수 (Step 2/3 공통)
`trading.py` 내부에 동기 헬퍼 `_is_order_time_blocked(stk_cd, settings) -> bool` 추가:
- `settings.get("order_time_guard_on", True)`가 False면 즉시 False 반환 (토글 OFF)
- True면 `is_order_blocked_by_time(stk_cd)` 호출
- 동기 함수 (시간 계산만, P1-P3 async 일관성 위반 아님)

### 4-6. 설정 키 추가 (Step 4)
**파일**: `backend/app/core/settings_defaults.py`

`DEFAULT_USER_SETTINGS`에 추가:
```python
"order_time_guard_on": True,  # 체결 불가 시간대 주문 차단 (기본 ON)
```
- 기본 True: 안전 장치이므로 기본 켜짐
- P13/P17: `integrated_system_settings_cache`에서만 관리

### 4-7. WS 이벤트 (Step 5)
**파일**: `backend/app/services/engine_ws_dispatch.py`

차단 시 `order_time_blocked` 이벤트 브로드캐스트:
- 기존 `circuit_breaker_open` 이벤트 패턴 재사용 (P23)
- 다만 시간대 차단은 **정상 반복 이벤트**이므로 서킷브레이커(비정상)와 메시지로 구분
- 이벤트 페이로드: `{"blocked": bool, "reason": "동시호가 시간대" 등}`
- 시간대 종료 시 `blocked: false` 이벤트로 자동 해제 (시간 기반, P24)

---

## 5. 프론트엔드 설계

### 5-1. 설정 토글 (Step 6)
**파일**: `frontend/src/pages/general-settings.ts`

자동매매 탭, 자동매도 행 아래에 추가:
- 라벨: "체결 불가 시간대 주문 차단"
- 설명: "동시호가·장외 시간대에 시장가 주문 자동 중단 (KRX 단독 종목만, NXT 종목은 NXT 거래 시간에 허용)"
- `createToggleBtn()` 재사용 (P23)
- 설정 키: `order_time_guard_on`, 기본 ON

### 5-2. 헤더 칩 (Step 7)
**파일**: `frontend/src/layout/header.ts`

노란색 "주문 일시중단(동시호가)" 칩 추가:
- 기존 서킷브레이커 칩 패턴 재사용, 색상/메시지로 구분 (P23)
- WS 이벤트 `order_time_blocked` 수신 시 표시
- `blocked: false` 수신 또는 시간대 종료 시 자동 해제 (P24)

### 5-3. WS 바인딩 (Step 8)
**파일**: `frontend/src/binding.ts` + `frontend/src/stores/uiStore.ts`

- `binding.ts`: `order_time_blocked` 이벤트 바인딩 추가
- `uiStore.ts`: `orderTimeBlocked` 상태 추가
- 기존 `circuitBreakerOpen` 패턴 재사용 (P23)

---

## 6. 세션 분할 계획 (AGENTS.md 섹션3 규칙 0-1: 세션당 1단계)

| 세션 | 작업 범위 | 검증 |
|---|---|---|
| **세션 1** | Step 1 (차단 판별 함수 + ±5초 버퍼) + Step 4 (설정 키) | 단위 테스트 (시간대별·경계·NXT 분기) |
| **세션 2** | Step 2 (execute_buy 게이트) + Step 3 (execute_sell 게이트) + Step 5 (헬퍼) | 런타임 기동 + 차단 로그 확인 |
| **세션 3** | Step 7 (WS 이벤트) + Step 8 (바인딩) | WS 이벤트 수신 확인 |
| **세션 4** | Step 6 (설정 토글) + Step 9 (헤더 칩) | 브라우저 확인 |

> 각 세션 종료 시 커밋 + HANDOVER.md 갱신 + 사용자 보고

---

## 7. 테스트 계획

### 7-1. 단위 테스트 (세션 1)
- `is_order_blocked_by_time()` 시간대별 판별:
  - 08:00~08:50: KRX 단독 종목 차단 / NXT 종목 허용
  - 08:50~09:00: 양쪽 차단
  - 09:00~15:20: 양쪽 허용
  - 15:20~15:40: 양쪽 차단
  - 15:40~20:00: KRX 단독 차단 / NXT 종목 허용
- ±5초 버퍼 경계 테스트 (08:59:55, 09:00:00, 09:00:05 등)
- `order_time_guard_on=False` 시 항상 False 반환
- 빈 문자열 phase 시 False 반환 (P20)

### 7-2. 런타임 검증 (세션 2)
- 백엔드 기동 후 로그에서 시간 체크 호출 확인
- 동시호가 시간대에 매수/매도 시도 시 차단 로그 확인
- 정규장 시간대에 주문 정상 통과 확인

### 7-3. WS 이벤트 검증 (세션 3)
- 차단 진입 시 `order_time_blocked` 이벤트 수신
- 시간대 종료 시 `blocked: false` 이벤트 수신

### 7-4. UI 검증 (세션 4)
- 설정 토글 ON/OFF 동작
- 헤더 칩 표시/해제
- 토글 OFF 시 차단 무효화

---

## 8. 별도 이슈: force_buy dead parameter (해결 완료 — 2026-07-17)

### 8-1. 발견 내용 (당시)
- `execute_buy(force_buy: bool = False)` 파라미터가 존재하나, **`force_buy=True`로 호출하는 코드가 백엔드·프론트엔드·테스트 전체에 0건**
- 유일한 실제 호출부: `buy_order_executor.py:172` — `force_buy=False` 고정
- "매수대기 수동 매수"라는 용어는 `trading.py` docstring/주석(98, 132행)에만 잔존
- 프론트엔드에 수동 매수 UI 없음 — 순수 자동매매 앱

### 8-2. 아키텍처 이슈
- **P16(살아있는 경로) 위반 소지**: 호출되지 않는 분기(`if not settings["is_auto"] and not force_buy`) 잔존
- **P23(일관성) 위반**: docstring이 실제 동작과 불일치 ("매수대기 수동 매수 전용"이라 했으나 해당 기능 없음)

### 8-3. 해결 (2026-07-17 별도 세션)
- **해결 완료**: `force_buy` 파라미터·분기·docstring·주석·로그 전부 제거
- `execute_buy()` 시그니처·`_execute_buy_locked()` 시그니처에서 `force_buy` 제거
- 자동매매 게이트 분기를 `if not settings["is_auto"]:`로 단순화 (동작 변화 없음 — 기존 `force_buy` 항상 False → `not force_buy` 항상 True)
- `buy_order_executor.py:172`의 `force_buy=False` 인자 제거
- `ARCHITECTURE.md` "자동매매 게이트 (force_buy 시 우회)" → "자동매매 게이트 (자동매매 비활성화 시 차단)" 갱신
- `HANDOVER.md` P-NEW-4 해결 완료 처리
- 본 시간 게이트 설계서의 본문 force_buy 참조(L100, L106)는 설계 당시 기준이므로 그대로 유지 (역사적 맥락 보존)

---

## 9. 위험 및 주의점

1. **기존 `is_krx_after_hours()` 수정 시 영향 범위**
   - `buy_order_executor.py:110`에서 호출 중
   - **대안**: 기존 함수는 유지하고 신규 함수 `is_order_blocked_by_time()` 추가 — 기존 동작 보존

2. **매도 차단 시 손절 기회 상실**
   - 동시호가 10분간 매도 차단 시 그 사이 손절 조건 hit되어도 매도 불가
   - 다음 체결 가능 시간(정규장 재개)까지 대기 — 사용자에게 사전 안내 필요 (헤더 칩으로 표시)

3. **±5초 버퍼 경계 오차**
   - 09:00:00 정각에 "시가 동시호가" → "정규장" 전환 — 08:59:55에 주문 시 차단 (안전 측)
   - phase 산정은 분 단위, 버퍼는 본 함수에서 초 단위 별도 계산

4. **NXT 분리 차단 시 `is_nxt_enabled()` 의존**
   - 종목의 NXT 활성 여부 판별은 기존 `is_nxt_enabled()` 함수에 의존 (P23 재사용)
   - `is_nxt_enabled()` 구현이 정확한지 사전 확인 필요 (구현 세션에서 검증)

---

## 10. 참조 파일

| 파일 | 역할 | 수정 세션 |
|---|---|---|
| `backend/app/services/daily_time_scheduler.py` | 시간 SSOT, 차단 판별 함수 | 세션 1 (Step 1) |
| `backend/app/core/settings_defaults.py` | 설정 기본값 | 세션 1 (Step 4) |
| `backend/app/services/trading.py` | execute_buy/execute_sell 게이트 | 세션 2 (Step 2, 3, 5) |
| `backend/app/services/engine_ws_dispatch.py` | WS 이벤트 | 세션 3 (Step 7) |
| `frontend/src/binding.ts` | WS 이벤트 바인딩 | 세션 3 (Step 8) |
| `frontend/src/stores/uiStore.ts` | UI 상태 | 세션 3 (Step 8) |
| `frontend/src/pages/general-settings.ts` | 설정 토글 | 세션 4 (Step 6) |
| `frontend/src/layout/header.ts` | 헤더 칩 | 세션 4 (Step 9) |
| `backend/app/services/buy_order_executor.py` | 매수 사전 필터 (기존 유지) | — |

---

## 11. 승인 대기 항목

본 설계서는 **사용자 결정 사항이 모두 확정**된 상태. 구현 진행은 사용자가 "진행해/구현해/적용해" 등 명시적 실행 지시어를 줄 때까지 대기 (AGENTS.md 섹션3 규칙 0).

구현 시 섹션 6의 세션 분할 계획에 따라 세션당 1단계씩 진행 (AGENTS.md 섹션3 규칙 0-1).
