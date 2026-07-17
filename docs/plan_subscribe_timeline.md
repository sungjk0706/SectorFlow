# 구독/해지 타임라인 재설계 태스크 파일 (2026-07-17)

> **설계서**: `docs/architecture_subscribe_timeline_design.md` (1세션 산출물)
> **조사 보고서**: `docs/subscribe_timeline_investigation.md` (사전 조사)
> **상태**: 심층 사전조사 완료. 구현 승인 대기.
> **참조 규칙**: AGENTS.md 섹션3 규칙 0(승인 전 수정 금지) + 0-1(세션당 1단계) + 0-2(수정 전 사전조사) + P10/P16/P20/P21/P22/P23/P24

---

## 1. 심층 사전조사 결과 (규칙 0-2 4항목)

### 1.1 의존성 분석

#### Change 1 (07:58 통합) — 의존 함수
| 함수 | 파일:줄 | 영향 | 변경 내용 |
|------|---------|------|-----------|
| `_on_realtime_fields_reset()` | `daily_time_scheduler.py:641-661` | **확장** | GC 비활성화 + 수신율 게이트 리셋 + 캐시 초기화 추가 |
| `_on_ws_subscribe_start()` | `daily_time_scheduler.py:664-708` | **축소** | GC/캐시/게이트 리셋 제거 → 상태 전환 + 통지만 |
| `_init_ws_subscribe_state()` | `daily_time_scheduler.py:835-886` | **확장** | 재시작 시 사전 구간 내 GC+캐시 초기화 포함 (07:58 로직과 동일) |
| `gc.disable()` | `_on_ws_subscribe_start:678` | **이동** | `_on_realtime_fields_reset`로 이동 (거래일 체크 이후) |

#### Change 2 (07:59 NXT 구독) — 의존 함수
| 함수 | 파일:줄 | 영향 | 변경 내용 |
|------|---------|------|-----------|
| `is_ws_subscribe_window()` | `daily_time_scheduler.py:340-359` | **확장** | 사전 구간(07:59~08:00) 시간 기반 판정 추가 |
| `is_nxt_only_window()` | `daily_time_scheduler.py:238-250` | **확장** | 사전 구간 시 KRX_INACTIVE + 시간 기반 → True |
| `_is_pre_subscribe_window()` | (신규) | **신규** | 공통 헬퍼 — 시간 기반 사전 구간 판정 |
| `is_heavy_operation_allowed()` | `daily_time_scheduler.py:309-323` | **간접** | `is_ws_subscribe_window()` 경유 — 자동 반영 |
| `is_edit_window_open()` | `daily_time_scheduler.py:362-370` | **간접** | `is_ws_subscribe_window()` 경유 — 자동 반영 |
| `stock_classification.py:26` | `stock_classification.py` | **간접** | `is_ws_subscribe_window()` 경유 — 자동 반영 |

#### Change 3 (08:59 KRX 사전 구독) — 의존 함수
| 함수 | 파일:줄 | 영향 | 변경 내용 |
|------|---------|------|-----------|
| `KRX_PRE_SUBSCRIBE_TIME` | (신규 상수) | **신규** | `(8, 59)` |
| `_check_prestart_triggers()` | `daily_time_scheduler.py:1128-1151` | **확장** | 08:59 KRX 사전 구독 트리거 추가 |
| `_on_krx_pre_subscribe()` | (신규) | **신규** | KRX 단독 종목 구독만 (재계산 없음) |
| `subscribe_sector_stocks_0b()` | `engine_ws_reg.py:244` | **변경 없음** | `_subscribed` 플래그 멱등성 — 08:59 구독 시 09:00 스킵 |
| `engine_state.last_krx_pre_subscribe_date` | `engine_state.py:113-115` | **신규 필드** | 멱등성 가드 (날짜 기반) |

#### Change 4 (15:20 KRX 해지) — 의존 함수 + Code Removal Rules
| 함수 | 파일:줄 | 영향 | 변경 내용 |
|------|---------|------|-----------|
| `_apply_market_phase()` | `daily_time_scheduler.py:565-605` | **트리거 조건 변경** | "체결 정산" → "종가 동시호가" (L600-601) |
| `_on_krx_after_hours_start()` | `daily_time_scheduler.py:431-461` | **개명** | → `_on_krx_closing_auction_start()` + docstring 갱신 |

**`_on_krx_after_hours_start` 전체 참조 위치 (Code Removal Rules 규칙 3 — 전체 검색 완료)**:

| 위치 | 파일:줄 | 변경 내용 |
|------|---------|-----------|
| 정의 | `daily_time_scheduler.py:431` | 개명 + docstring "15:30 체결 정산" → "15:20 종가 동시호가" |
| docstring 참조 | `daily_time_scheduler.py:576` | `_apply_market_phase` 내 주석 갱신 |
| 트리거 | `daily_time_scheduler.py:601` | 조건 "체결 정산" → "종가 동시호가" + context 문구 변경 |
| import | `test_daily_time_scheduler.py:49` | `_on_krx_closing_auction_start`로 변경 |
| 테스트 클래스 | `test_daily_time_scheduler.py:858` | `TestOnKrxAfterHoursStart` → `TestOnKrxClosingAuctionStart` |
| 테스트 호출 | `test_daily_time_scheduler.py:863,875,887` | 함수명 변경 |
| 테스트 시각 | `test_daily_time_scheduler.py:861,871,883` | `_make_kst(15, 30)` → `_make_kst(15, 20)` |
| 트리거 테스트 | `test_daily_time_scheduler.py:738-748` | "체결 정산" 전환 → "종가 동시호가" 전환 + context "KRX 장외 전환" → "KRX 종가 동시호가 — 구독 해지" |
| 역사적 문서 | `architecture_session_state_design.md:108` | **유지** (감사계획 역사적 로그 — Code Removal Rules 규칙 3 예외) |
| 역사적 문서 | `plan_session_state_*.md` | **유지** (역사적 계획서 — 완료 시 삭제 대상 아님) |

### 1.2 영향 범위

| 영역 | 변경 여부 | 상세 |
|------|-----------|------|
| **백엔드** | 변경 | `daily_time_scheduler.py` (핵심), `engine_state.py` (필드 1개 추가) |
| **프론트엔드** | 변경 없음 | P21 검토 완료 — 사전 구독 UI 표시 불필요 (사용자 결정) |
| **테스트** | 변경 | `test_daily_time_scheduler.py` (기존 테스트 갱신 + 신규 테스트 추가) |
| **문서** | 변경 (5세션) | `ARCHITECTURE.md:976-983` 타임라인 섹션 갱신 |
| **DB** | 변경 없음 | 스키마 변경 없음 |
| **설정** | 변경 없음 | `integrated_system_settings_cache` 키 변경 없음 |

### 1.3 아키텍처 원칙 부합 여부

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10 (SSOT) | 준수 | `_is_pre_subscribe_window()` 헬퍼로 시간 판정 단일화, 기존 시간 상수 재사용 |
| P16 (살아있는 경로) | 준수 | 시간 기반 판정 → 재시작 시 사전 구간 동작, 07:58 누락 시 07:59 보완 |
| P20 (폴백 금지) | 준수 | 시간 기반 판정은 정상 경로 확장 (플래그 미의존), silent except: pass 금지 |
| P21 (사용자 투명성) | 준수 | 사전 구독 UI 불필요 (사용자 결정), 15:20 해지는 기존 장 상태 UI로 충분 |
| P22 (데이터 정합성) | 준수 | 15:20 해지 시 종가 손실 없음 (20:40 확정시세), 멱등성 가드 유지 |
| P23 (일관성) | 준수 | 공통 헬퍼 추출, 함수 개명으로 명칭-동작 일치, 용어 통일 |
| P24 (단순성) | 준수 | 안 A 선택 (가장 단순), 신규 함수 2개만 추가, 프론트엔드 변경 없음 |

### 1.4 기존 공통 자산 확인 (P23 사전 절차)

| 자산 | 위치 | 재사용 여부 |
|------|------|-------------|
| `WS_SUBSCRIBE_PRESTART_TIME` | `daily_time_scheduler.py:47` | **재사용** — `_is_pre_subscribe_window()` 시간 범위 하한 |
| `NXT_PREMARKET_START` | `daily_time_scheduler.py:35` | **재사용** — `_is_pre_subscribe_window()` 시간 범위 상한 |
| `KRX_REGULAR_START` | `daily_time_scheduler.py:26` | **재사용** — `_check_prestart_triggers()` 08:59 상한 |
| `KRX_INACTIVE_PHASES` | `daily_time_scheduler.py:226` | **재사용** — `is_nxt_only_window()` 사전 구간 조건 |
| `NXT_ACTIVE_PHASES` | `daily_time_scheduler.py:232` | **재사용** — `is_ws_subscribe_window()` 기존 조건 |
| `subscribe_sector_stocks_0b()` | `engine_ws_reg.py:244` | **재사용** — `_on_krx_pre_subscribe()` 내 호출 (멱등성 보장) |
| `_subscribed` 플래그 | `engine_ws_reg.py:298,315 등` | **재사용** — 08:59/09:00 중복 구독 방지 |
| `schedule_engine_task()` | `engine_lifecycle.py` | **재사용** — 모든 비동기 트리거 |
| `_close_coro` 테스트 헬퍼 | `test_daily_time_scheduler.py` | **재사용** — `schedule_engine_task` mock side_effect |
| `_make_kst()` 테스트 헬퍼 | `test_daily_time_scheduler.py:80` | **재사용** — 시간 기반 테스트 |
| 멱등성 가드 패턴 | `engine_state.py:113-115` | **재사용** — `last_krx_pre_subscribe_date` 동일 패턴 추가 |

**신규 생성 자산**: `_is_pre_subscribe_window()` (공통 헬퍼), `_on_krx_pre_subscribe()` (신규 콜백), `KRX_PRE_SUBSCRIBE_TIME` (상수), `last_krx_pre_subscribe_date` (상태 필드). 모두 기존 패턴 준수.

---

## 2. 구현 Step + 세션 분할

> 규칙 0-1(세션당 1단계) 준수. 3세션/4세션은 각각 독립적으로 완료·검증 가능.

### 2.1 3세션 — 구현 Step 1: 사전 구간 판정 + 07:58 통합 (Change 1, 2)

#### 수정 파일
- `backend/app/services/daily_time_scheduler.py`
- `backend/app/services/engine_state.py`
- `backend/tests/test_daily_time_scheduler.py`

#### 수정 상세

**A. `engine_state.py` — 필드 추가 없음 (Change 1, 2는 신규 필드 불필요)**
- `last_krx_pre_subscribe_date`는 4세션에서 추가 (Change 3 전용).

**B. `daily_time_scheduler.py` — `_is_pre_subscribe_window()` 신규 함수**
- 위치: `is_nxt_only_window()` 정의 이전 (L238 부근)
- 시간 기반 판정: `WS_SUBSCRIBE_PRESTART_TIME <= t < NXT_PREMARKET_START`
- 휴장일 체크: `market_phase`의 krx/nxt가 "휴장일"이면 False

**C. `daily_time_scheduler.py` — `is_ws_subscribe_window()` 확장**
- 기존 조건(`nxt in NXT_ACTIVE_PHASES`) 후 `_is_pre_subscribe_window()` OR 조건 추가
- settings 체크 로직은 기존 유지

**D. `daily_time_scheduler.py` — `is_nxt_only_window()` 확장**
- 기존 조건 후 사전 구간 조건 추가: `_is_pre_subscribe_window() and krx in KRX_INACTIVE_PHASES`

**E. `daily_time_scheduler.py` — `_on_realtime_fields_reset()` 확장**
- 기존: `_reset_realtime_fields()`만
- 변경 후: `_reset_realtime_fields()` + `gc.disable()` + `reset_sector_threshold()` + `notify_cache.prev_scores = []` + `state.sector_summary_cache = None`
- 순서: 거래일 체크 → GC 비활성화 → 필드 초기화 → 게이트 리셋 → 캐시 초기화
- 멱등성 가드 `last_realtime_reset_date`가 전체 작업 보호 (이미 실행 시 전체 스킵)

**F. `daily_time_scheduler.py` — `_on_ws_subscribe_start()` 축소**
- 제거: `gc.disable()`, `reset_sector_threshold()`, `notify_cache.prev_scores = []`, `state.sector_summary_cache = None`, `_broadcast_market_phase()` 내부 중복 (07:58에서 이미 브로드캐스트)
- 유지: 멱등성 가드, `ws_subscribe_window_active = True`, `last_ws_subscribe_start_date`, `_broadcast_market_phase()`, `ws_window_changed_event.set()`
- 보완 로직: `last_realtime_reset_date != today_str` 시 `_on_realtime_fields_reset()` 1회 호출 (07:58 누락 시 전체 데이터 준비 복구)

**G. `daily_time_scheduler.py` — `_init_ws_subscribe_state()` 확장**
- 재시작 시 사전 구간 내 기동 시: 07:58 로직과 동일하게 GC + 캐시 초기화 수행
- `_is_pre_subscribe_window()` 판정 추가 (in_window가 False이지만 사전 구간이면 데이터 준비)

**H. 테스트 갱신 + 신규**
- `TestOnRealtimeFieldsReset`: GC + 캐시 초기화 검증 추가 (기존 4개 테스트 갱신)
- `TestOnWsSubscribeStartIdempotency`: 보완 경로 `_on_realtime_fields_reset()` 호출 검증으로 변경
- `TestIsWsSubscribeWindow`: 사전 구간(07:59~08:00) True 테스트 추가, 휴장일 사전 구간 False 테스트 추가
- `TestIsNxtOnlyWindow`: 사전 구간 NXT-only True 테스트 추가
- `TestInitWsSubscribeState`: 사전 구간 재시작 시 GC+캐시 초기화 테스트 추가

#### 검증
- `pytest backend/tests/test_daily_time_scheduler.py -v`
- `python3 -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 0건
- `/api/settings` 응답 정상
- 잔존 프로세스 0건

### 2.2 4세션 — 구현 Step 2: 08:59 KRX 사전 구독 + 15:20 KRX 해지 (Change 3, 4)

#### 수정 파일
- `backend/app/services/daily_time_scheduler.py`
- `backend/app/services/engine_state.py`
- `backend/tests/test_daily_time_scheduler.py`

#### 수정 상세

**A. `engine_state.py` — 필드 추가**
- L115 이후: `self.last_krx_pre_subscribe_date: str = ""  # KRX 사전 구독 실행 날짜 (YYYYMMDD)`
- 멱등성 가드 그룹(L113-115)에 추가 — 기존 패턴 준수

**B. `daily_time_scheduler.py` — 상수 추가**
- L47 이후: `KRX_PRE_SUBSCRIBE_TIME = (8, 59)   # 08:59 KRX 사전 구독 (정규장 1분 전)`

**C. `daily_time_scheduler.py` — `_on_krx_pre_subscribe()` 신규 함수**
- 위치: `_on_krx_market_open()` 정의 이후 (L428 부근)
- 동작: 거래일 체크 → `subscribe_sector_stocks_0b()` 호출 (재계산 없음)
- 멱등성 가드: `last_krx_pre_subscribe_date == today_str` 시 스킵
- 거래일 아닌 시 가드 미설정 (다음 거래일에 실행)

**D. `daily_time_scheduler.py` — `_check_prestart_triggers()` 확장**
- 기존 07:58/07:59 트리거 후 08:59 트리거 추가
- 조건: `KRX_PRE_SUBSCRIBE_TIME <= t < KRX_REGULAR_START and last_krx_pre_subscribe_date != today_str`
- `schedule_engine_task(_on_krx_pre_subscribe(), context="KRX 사전 구독 (08:59)")`

**E. `daily_time_scheduler.py` — `_apply_market_phase()` 트리거 조건 변경**
- L600-601: `new_krx == "체결 정산"` → `new_krx == "종가 동시호가"`
- context: `"KRX 장외 전환"` → `"KRX 종가 동시호가 — 구독 해지"`
- L576 docstring 갱신: "15:30 체결 정산" → "15:20 종가 동시호가"

**F. `daily_time_scheduler.py` — 함수 개명**
- `_on_krx_after_hours_start()` → `_on_krx_closing_auction_start()`
- docstring 갱신: "15:30 전환 콜백" → "15:20 종가 동시호가 전환 콜백", "KRX 종가 동시호가 종료(15:30)" → "KRX 정규장 종료(15:20)"
- 동작 내용은 동일 (재계산 + KRX 단독 종목 해지)

**G. 테스트 갱신 + 신규**
- import 갱신: `_on_krx_after_hours_start` → `_on_krx_closing_auction_start` (L49)
- `TestOnKrxAfterHoursStart` → `TestOnKrxClosingAuctionStart` (L858)
- 테스트 시각: `_make_kst(15, 30)` → `_make_kst(15, 20)` (L861, 871, 883)
- `test_triggers_krx_after_hours_on_phase_change` (L738): "체결 정산" 전환 → "종가 동시호가" 전환, context "KRX 장외 전환" → "KRX 종가 동시호가 — 구독 해지"
- `TestCheckPrestartTriggers`: 08:59 KRX 사전 구독 트리거 테스트 추가 (기존 6개 + 신규 2~3개)
- `TestOnKrxPreSubscribe` 신규 클래스: 거래일 구독 실행, 주말/공휴일 스킵, 멱등성 가드, 예외 처리 테스트

#### 검증
- `pytest backend/tests/test_daily_time_scheduler.py -v`
- `python3 -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 0건
- `/api/settings` 응답 정상
- 잔존 프로세스 0건

### 2.3 5세션 — 통합 런타임 검증 + 문서 갱신 + 계획서 삭제

#### 수정 파일
- `ARCHITECTURE.md` (타임라인 섹션 갱신)
- `docs/architecture_subscribe_timeline_design.md` (삭제)
- `docs/plan_subscribe_timeline.md` (삭제 — 본 파일)

#### 수정 상세

**A. `ARCHITECTURE.md:976-983` 타임라인 갱신**
```
07:58  _on_realtime_fields_reset() — 실시간 필드 초기화 + GC 비활성화 + 캐시 초기화
07:59  WS 구독 구간 진입 — 상태 전환 + 엔진 루프 통지 (사전 구독)
08:00  NXT 프리마켓 진입 — 업종 재계산 (이미 구독됨)
08:59  _on_krx_pre_subscribe() — KRX 단독 종목 사전 구독
09:00  KRX 정규장 진입 — 업종 재계산 (구독은 멱등 스킵)
15:20  _on_krx_closing_auction_start() — KRX 단독 종목 구독 해지
20:00  _on_ws_subscribe_end() — WS 구독 종료 + GC 정상화
20:40  _fire_unified_confirmed_fetch() — 확정 시세 + 5일봉 다운로드
00:00  _on_midnight() — 일일 리셋
```

**B. `ARCHITECTURE.md:995-1001` WS 구독 구간 판정 갱신**
- 사전 구간(07:59~08:00) 시간 기반 판정 추가 명시

**C. 계획서 삭제 (규칙 11)**
- `git rm docs/architecture_subscribe_timeline_design.md`
- `git rm docs/plan_subscribe_timeline.md`

#### 검증 (통합)
- `pytest` 전체 — 기존 2822 passed 카운트 유지 (회귀 없음)
- `npm run build` — 프론트엔드 변경 없으므로 기존 빌드 유지 (회귀 확인용)
- `python3 -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 0건, 기동 정상
- `/api/settings` 응답 정상
- 잔존 프로세스 0건
- `grep "_on_krx_after_hours_start"` 잔존 참조 0건 (Code Removal Rules 규칙 3 — 역사적 문서 제외)

---

## 3. 테스트 계획

### 3.1 3세션 테스트 (Change 1, 2)

| 테스트 클래스 | 테스트 | 검증 항목 |
|---------------|--------|-----------|
| `TestOnRealtimeFieldsReset` | `test_resets_fields_and_sets_flag` (갱신) | 필드 초기화 + GC 비활성화 + 게이트 리셋 + 캐시 초기화 |
| `TestOnRealtimeFieldsReset` | `test_skips_if_already_run_today` (기존 유지) | 멱등성 가드 — 전체 스킵 |
| `TestOnRealtimeFieldsReset` | `test_skips_on_weekend` (갱신) | 주말 시 GC 비활성화 미실행 (개선 검증) |
| `TestOnRealtimeFieldsReset` | `test_skips_on_non_trading_day` (기존 유지) | 공휴일 스킵 |
| `TestOnWsSubscribeStartIdempotency` | `test_compensates_missing_fields_reset` (갱신) | 보완 시 `_on_realtime_fields_reset()` 호출 (GC+캐시 포함) |
| `TestOnWsSubscribeStartIdempotency` | `test_skips_fields_reset_if_already_done` (갱신) | 07:58 실행 시 보완 스킵 |
| `TestIsWsSubscribeWindow` | `test_pre_subscribe_window_returns_true` (신규) | 07:59~08:00 시간 기반 True |
| `TestIsWsSubscribeWindow` | `test_pre_subscribe_window_holiday_returns_false` (신규) | 휴장일 사전 구간 False |
| `TestIsNxtOnlyWindow` | `test_pre_subscribe_window_nxt_only` (신규) | 사전 구간 KRX_INACTIVE → True |
| `TestInitWsSubscribeState` | `test_pre_subscribe_window_init` (신규) | 재시작 시 사전 구간 GC+캐시 초기화 |

### 3.2 4세션 테스트 (Change 3, 4)

| 테스트 클래스 | 테스트 | 검증 항목 |
|---------------|--------|-----------|
| `TestCheckPrestartTriggers` | `test_triggers_krx_pre_subscribe_at_0859` (신규) | 08:59 KRX 사전 구독 트리거 1회 |
| `TestCheckPrestartTriggers` | `test_skips_krx_pre_subscribe_if_already_run` (신규) | 멱등성 가드 — 스킵 |
| `TestCheckPrestartTriggers` | `test_skips_krx_pre_subscribe_after_0900` (신규) | 09:00 이상 시 스킵 (phase 변경 감지가 담당) |
| `TestOnKrxPreSubscribe` | `test_trading_day_subscribes` (신규) | 거래일 `subscribe_sector_stocks_0b` 호출 |
| `TestOnKrxPreSubscribe` | `test_weekend_skips` (신규) | 주말 스킵 |
| `TestOnKrxPreSubscribe` | `test_holiday_skips` (신규) | 공휴일 스킵 |
| `TestOnKrxPreSubscribe` | `test_skips_if_already_run_today` (신규) | 멱등성 가드 |
| `TestOnKrxClosingAuctionStart` | (개명 + 시각 갱신) | 기존 `TestOnKrxAfterHoursStart` 3개 테스트 — `_make_kst(15, 20)` |
| `TestApplyMarketPhase` | `test_triggers_krx_closing_auction_on_phase_change` (갱신) | "종가 동시호가" 전환 시 트리거 + context "KRX 종가 동시호가 — 구독 해지" |

### 3.3 5세션 통합 검증

- pytest 전체 회귀 (기존 2822 passed 카운트 유지)
- 런타임 기동 (`python3 -W error::RuntimeWarning main.py`)
- 빌드 (`npm run build`)
- 잔존 참조 grep (`_on_krx_after_hours_start` — 역사적 문서 제외 0건)

---

## 4. 런타임 검증 방법

### 4.1 각 구현 세션 (3, 4세션)

```bash
# 테스트
cd backend && pytest tests/test_daily_time_scheduler.py -v

# 런타임 기동
python3 -W error::RuntimeWarning main.py
# → RuntimeWarning 0건, 기동 정상, 에러/traceback 없음 확인

# 설정 응답
curl -s http://localhost:8000/api/settings | python3 -m json.tool
# → 응답 정상 확인

# 잔존 프로세스
ps aux | grep "[m]ain.py" | wc -l
# → 0건 확인
```

### 4.2 5세션 통합 검증

```bash
# pytest 전체
cd backend && pytest

# 빌드
cd frontend && npm run build

# 런타임 기동
python3 -W error::RuntimeWarning main.py

# 잔존 참조 확인 (역사적 문서 제외)
grep -r "_on_krx_after_hours_start" backend/ --include="*.py"
# → 0건 (Code Removal Rules 규칙 3)
```

---

## 5. 사용자 결정 항목

### 5.1 이미 결정된 항목 (설계서 1세션)

| 항목 | 결정 | 근거 |
|------|------|------|
| 4개 변경안 전부 구현 | 승인 | 사용자 작업 지시 |
| 사전 구독 UI 표시 | 불필요 | 사용자 결정 (P21) |
| "웹소켓 연결" 단순화 | 대상 아님 | 조사 보고서 3절 |

### 5.2 2세션에서 확인된 항목 (심층 사전조사)

| 항목 | 결정 | 근거 |
|------|------|------|
| Change 2 방식: 시간 기반 (안 A) | 확정 | 재시작 대응 (P16) — 플래그 기반 안 B는 재시작 시 사전 구간 누락 |
| Change 1 방식: 함수 확장 (안 A) | 확정 | P24 단순성 — 함수 수 증가 없음 |
| Change 4 방식: 함수 개명 (안 A) | 확정 | P23 명칭-동작 일치 — Code Removal Rules 준수 |
| 주말 GC 비활성화 제거 | 개선으로 확정 | 07:58 거래일 체크 이후 GC 비활성화 — 주말 GC 장기 비활성화 방지 |
| 세션 분할: 3세션(Change 1,2) + 4세션(Change 3,4) | 확정 | 수정 함수 독립성 — 같은 파일이지만 수정 영역 분리 |

### 5.3 구현 승인 대기

- 3세션 구현 Step 1 승인 (Change 1, 2)
- 4세션 구현 Step 2 승인 (Change 3, 4)
- 5세션 통합 검증 + 문서 갱신 + 계획서 삭제 승인

---

## 6. 위험 요소 + 대응

| 위험 | 가능성 | 대응 |
|------|--------|------|
| 07:59 사전 구간 중 WS 연결 실패 | 낮음 | 엔진 루프 재시도 루프가 기존과 동일 동작 — 08:00 phase 변경 시 재감지 |
| 08:59 KRX 사전 구독 시 `_subscribed` 플래그 불일치 | 매우 낮음 | `subscribe_sector_stocks_0b()` 내부 멱등성 — 09:00 재호출 시 스킵 |
| 15:20 해지 시 KRX 단독 종목 실시간 시세 손실 | 없음 | 시장가 체결만 사용 → 동시호가 구간 체결 불가 → 구독 유지 불필요 |
| 재시작 시 사전 구간 판정 오류 | 낮음 | 시간 기반 판정 — `_init_ws_subscribe_state()`에서 `is_ws_subscribe_window()` 호출 |
| `_on_krx_after_hours_start` 참조 누락 | 낮음 | Code Removal Rules 규칙 3 — 전체 검색 완료 (1.1절 참조) |

---

## 7. 완료 기준

### 7.1 각 구현 세션 (3, 4세션)
- [ ] 코드 수정 완료 (설계서 + 본 태스크 파일 기준)
- [ ] pytest 해당 파일 통과
- [ ] 런타임 기동 — RuntimeWarning 0건, 에러 없음
- [ ] `/api/settings` 응답 정상
- [ ] 잔존 프로세스 0건
- [ ] 커밋 (사용자 승인 후)
- [ ] HANDOVER.md 갱신

### 7.2 5세션 (통합 검증 + 정리)
- [ ] pytest 전체 — 기존 2822 passed 유지
- [ ] npm run build 성공
- [ ] 런타임 기동 정상
- [ ] `ARCHITECTURE.md` 타임라인 갱신
- [ ] 계획서 2개 파일 삭제 (`architecture_subscribe_timeline_design.md`, `plan_subscribe_timeline.md`)
- [ ] 잔존 참조 grep 0건 (역사적 문서 제외)
- [ ] 커밋 (사용자 승인 후)
- [ ] HANDOVER.md 갱신 — 다단계 작업 완료 기록
