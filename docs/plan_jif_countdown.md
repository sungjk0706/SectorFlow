# JIF 카운트다운 복구 태스크 파일

> **작성일**: 2026-07-23
> **기준 문서**: `docs/jif_countdown_design.md` (설계 완료) + `ARCHITECTURE.md` (불변 원칙 24개)
> **목적**: 설계 문서의 방안 1~4를 실행 가능한 세션별 구현 Step으로 전개. 각 Step별 조사·수정·검증 단계를 추적 가능한 단위로 분해.
> **적용 워크플로우**: AGENTS.md 섹션4 "다단계 작업 워크플로우" 3세션~ (단계별 구현)
> **세션 분할**: 설계 문서 섹션 7 기준 2세션 (백엔드 핵심 → 프론트엔드 + 테스트)

---

## 0. 사용 방법

- 본 파일은 `jif_countdown_design.md`의 실행 추적용 태스크 파일. 설계 원칙·방안 상세·세션 분할 논리는 설계 문서 본문 참조.
- 각 세션은 **재심층 사전조사 → (사용자 승인 후) 수정 → 검증** 3단계로 진행 (AGENTS.md 규칙 0, 0-1, 0-2 준수).
- 세션당 1단계 원칙 (AGENTS.md 규칙 0-1): 한 세션에서 여러 세션 연속 진행 금지.
- 세션 완료 시 커밋 + `HANDOVER.md` 갱신 + 사용자 보고 후 세션 종료.
- 모든 단계 완료 후 최종 커밋 시 본 파일 + `jif_countdown_design.md` 삭제 (AGENTS.md 규칙 11).

---

## 1. 심층 사전조사 결과 (2세션 산물)

> 규칙 0-2 4항목(의존성·영향범위·아키텍처 원칙 부합·기존 공통 자산 확인) 결과.

### 1.1 의존성 식별

| 대상 파일 | 수정 지점 | 의존 코드 (영향 받는 호출자/참조자) |
|-----------|-----------|-----------------------------------|
| `engine_ws_dispatch.py` | `_JIF_IGNORE_CODES`(229-237), `_handle_jif()`(256-322), 매핑 테이블 신설 | `handle_ws_data()`(JIF 분기), `test_engine_ws_dispatch.py`(test_jif_countdown_ignored 등 다수) |
| `daily_time_scheduler.py` | 시간 상수 영역(21-49), `_KRX_COUNTDOWN_MAP`(183-186), `_NXT_COUNTDOWN_MAP`(188-195), `NXT_ACTIVE_PHASES`(234-237), `NXT_AFTERMARKET_MID_END`(42), `calc_countdown()`(198-225), `get_market_phase()`(367-386), `build_timetable_from_cache()`(927-979), `_timetable_event_fired()`(1034-1061) | `_apply_market_phase()`(691-736), `_broadcast_market_phase()`(739-750), `is_ws_subscribe_window()`(420-), `test_daily_time_scheduler.py` |
| `engine_state.py` | state 필드 영역(69-115) | `engine_state.state` 참조 전체 (읽기 전용 추가이므로 기존 참조 영향 없음) |
| `header.ts` | `formatCountdown()`(74-82) | `applyMarketPhaseChip()`(84-), market-phase WS 핸들러 |
| `test_engine_ws_dispatch.py` | `test_jif_countdown_ignored`(369-376), JIF constants 테스트(401-) | — |
| `test_daily_time_scheduler.py` | 카운트다운/맵/페이즈명 테스트 신규 추가 | — |

### 1.2 영향 범위

- **백엔드**: 3파일 (`engine_ws_dispatch.py`, `engine_state.py`, `daily_time_scheduler.py`)
- **프론트엔드**: 1파일 (`header.ts`)
- **테스트**: 2파일 (`test_engine_ws_dispatch.py`, `test_daily_time_scheduler.py`)
- **거래 로직 영향**: 없음 — 카운트다운은 표시 전용. 매수/매도/주문 차단은 `get_order_time_block_status()`가 담당 (설계 문서 8.1).

### 1.3 아키텍처 원칙 부합 여부

| 원칙 | 부합 확인 내용 |
|------|----------------|
| P10 (SSOT) | 카운트다운 임계 시각 = 코드 상수(거래소 규정) 단일 관리. override = `engine_state` 단일 소스. |
| P11 (폴링 금지) | 별도 타이머 없이 기존 `_TIMETABLE` 스케줄러 재사용 (`call_later` 이벤트 기반). |
| P14 (멀티스레드 금지) | 타이머 1개 유지 (기존 `timetable_timer_handle`). |
| P16 (살아있는 경로) | JIF 경로(`_handle_jif`) + 타임테이블 보조 경로(`_timetable_event_fired`) 모두 실제 실행 경로에 연결. |
| P20 (폴백 금지) | override 만료 시 None 반환 (만료된 값 사용 금지). `calc_countdown()` remaining_sec<=0 시 None 이미 구현됨. |
| P23 (일관성) | 페이즈명 통일 ("애프터마켓"), `_TIMETABLE` 엔트리 구조 일관, 용어("업종"/"종목") 준수. |
| P24 (단순성) | 별도 타이머 없이 기존 스케줄러 확장. 카운트다운 임계 시각 = 코드 상수(DB 아님). 함수 50줄 이하 유지. |

### 1.4 기존 공통 자산 확인 (P23 사전 절차)

| 재사용 자산 | 위치 | 재사용 방식 |
|-------------|------|-------------|
| `calc_countdown()` | `daily_time_scheduler.py` 198-225 | 보조 로직에서 그대로 호출 (새 계산 함수 생성 금지) |
| `_TIMETABLE` 스케줄러 | `daily_time_scheduler.py` 982-1061 | `kind="countdown"` 엔트리 추가로 확장 (새 타이머 금지) |
| `_apply_market_phase()` | `daily_time_scheduler.py` 691-736 | 페이즈 전환 시 override 초기화 경로로 활용 |
| `_broadcast()` | `engine_account_notify.py` | 카운트다운 브로드캐스트에 재사용 |
| 시간 상수 (`KRX_REGULAR_END` 등) | `daily_time_scheduler.py` 21-49 | 카운트다운 임계 시각 상수 정의 시 참조 (새 하드코딩 최소화) |
| `_to3()`, `_m()`, `_kst_now()` | `daily_time_scheduler.py` | 타임테이블 엔트리/시간 계산에 재사용 |

### 1.5 ⚠️ 설계 문서 오류 바로잡기 (태스크 파일에 반영)

설계 문서 3.2의 KRX 장마감 JIF 매핑이 API 문서(`docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt` 114-122줄)와 불일치.

| 코드 | 설계 문서 3.2 (오류) | API 문서 실제 (본 태스크 파일 적용) |
|------|---------------------|-----------------------------------|
| 44 | 600초 (10분전) | **300초 (5분전)** |
| 43 | 300초 (5분전) | **60초 (1분전)** |
| 42 | 60초 (1분전) | **10초 (10초전)** |

- KRX 장마감은 5분전(44)이 최대. **10분전 코드 없음** → KRX 장마감 10분전은 `_TIMETABLE` 보조 엔트리만 담당.
- KRX 장개시는 25=10분전까지 존재 (설계 문서 3.2 일치).
- NXT 프리마켓/에프터마켓 장마감(C/D)은 5분전이 최대 (10분전 없음) — 설계 문서 3.2 일치.
- **후속 조치**: 1세션 착수 전 설계 문서 3.2 매핑 테이블도 함께 수정하여 P10(SSOT) 위반(문서-코드 불일치) 해소.

---

## 2. 세션 분할 (2세션)

> 설계 문서 섹션 7 기준. 방안 2가 별도 타이머 없이 기존 `_TIMETABLE` 엔트리 추가만으로 해결되어 3세션 → 2세션 단축.

| 세션 | 내용 | 파일 수 | 상태 |
|------|------|---------|------|
| S-1 | 백엔드 핵심 (방안 1 + 3 + 2 + 4-2/4-3) | 3 + 1 테스트 | ✅ 완료 (2026-07-23) |
| S-2 | 프론트엔드 + 테스트 보완 (방안 4-1 + 테스트 정비) | 1 + 2 테스트 | ☐ 미시작 |

---

## 3. S-1: 백엔드 핵심 (방안 1 + 3 + 2 + 4-2/4-3)

### 3.1 구현 Step

#### Step 1-1: `engine_state.py` — override 필드 추가
- `engine_state.py` 110줄 부근(`last_jif_received_at` 이후)에 추가:
  ```python
  self.krx_countdown_override: dict | None = None  # {label, remaining_sec, expires_at}
  self.nxt_countdown_override: dict | None = None
  ```
- **체크**: P10(SSOT) — override 단일 소스. P16 — `get_market_phase()`에서 읽히는 살아있는 경로.

#### Step 1-2: `engine_ws_dispatch.py` — JIF 카운트다운 매핑 테이블 신설 + `_JIF_IGNORE_CODES` 정리
- `_JIF_IGNORE_CODES`(229-237)에서 카운트다운 코드(22~25, 42~44, A2~A5, B2~B5, C2~C4, D2~D4) 제거. `"53"`(사용안함)만 남김.
- 신설 매핑 테이블 (API 문서 기준 — 섹션 1.5 바로잡기 적용):
  ```python
  _JIF_COUNTDOWN_KRX: dict[str, tuple[str, int]] = {
      # 장개시 카운트다운 (→ 09:00) — 현재 페이즈가 "시가 동시호가"일 때
      "25": ("정규장 장개시", 600),   # 10분전 (08:50)
      "24": ("정규장 장개시", 300),   # 5분전  (08:55)
      "23": ("정규장 장개시", 60),    # 1분전  (08:59)
      "22": ("정규장 장개시", 10),    # 10초전 (08:59:50)
      # 장마감 카운트다운 (→ 15:20, 종가동시호가 개시) — 현재 페이즈가 "정규장"일 때
      # API 문서 기준: 44=5분전(최대), 10분전 코드 없음
      "44": ("정규장 장마감", 300),   # 5분전  (15:15)
      "43": ("정규장 장마감", 60),    # 1분전  (15:19)
      "42": ("정규장 장마감", 10),    # 10초전 (15:19:50)
  }

  _JIF_COUNTDOWN_NXT: dict[str, tuple[str, int]] = {
      # 프리마켓 장개시 (→ 08:00)
      "A5": ("프리마켓 장개시", 600),
      "A4": ("프리마켓 장개시", 300),
      "A3": ("프리마켓 장개시", 60),
      "A2": ("프리마켓 장개시", 10),
      # 프리마켓 장마감 (→ 08:50) — 5분전이 최대
      "C4": ("프리마켓 장마감", 300),
      "C3": ("프리마켓 장마감", 60),
      "C2": ("프리마켓 장마감", 10),
      # 에프터마켓 장개시 (→ 15:40)
      "B5": ("에프터마켓 장개시", 600),
      "B4": ("에프터마켓 장개시", 300),
      "B3": ("에프터마켓 장개시", 60),
      "B2": ("에프터마켓 장개시", 10),
      # 에프터마켓 장마감 (→ 20:00) — 5분전이 최대
      "D4": ("에프터마켓 장마감", 300),
      "D3": ("에프터마켓 장마감", 60),
      "D2": ("에프터마켓 장마감", 10),
  }
  ```
- **체크**: P4(증권사명 침투 금지) — 매핑 테이블에 `ls_`/`kiwoom_` 접두사 없음. P23 — 페이즈명 "애프터마켓" 통일.

#### Step 1-3: `engine_ws_dispatch.py` — `_handle_jif()` 카운트다운 처리 추가
- 282줄 `if jstatus in _JIF_IGNORE_CODES: return` 제거.
- 카운트다운 코드 수신 시:
  1. `jangubun`(1/2=KRX, 6=NXT) + 현재 페이즈(`market_phase["krx"]`/`["nxt"]`)로 장개시/장마감 구분 (코드 22/42 중복 해결).
  2. 매핑 테이블에서 (라벨, remaining_sec) 조회.
  3. `engine_state.state.krx_countdown_override` / `nxt_countdown_override`에 `{label, remaining_sec, expires_at}` 저장. `expires_at` = 수신 시각 + remaining_sec + 여유 5초.
  4. `_broadcast("market-phase", get_market_phase())` 즉시 전송 (override 우선값 포함).
- 페이즈 전환 코드(11/21/31/41/51/52/54/55/56/57/58) 수신 시 해당 시장 override = None 초기화.
- **체크**: P16 — 카운트다운 처리 경로가 `_handle_jif()` 실제 실행 경로에 연결. P20 — 매핑 미포함 코드는 로그만 남기고 무시 (silent pass 금지 → `logger.debug`).

#### Step 1-4: `daily_time_scheduler.py` — 카운트다운 임계 시각 상수 정의
- 21-49줄 시간 상수 영역에 추가. 거래소 규정 → 코드 상수 (DB 아님, P24/P13).
  ```python
  # KRX 정규장 장마감 카운트다운 임계 (거래소 규정 — 사용자 조정 불가)
  # JIF에 10분전 코드 없으므로 10분전은 _TIMETABLE 보조 엔트리만 담당
  KRX_CLOSE_COUNTDOWN_10M = (15, 10)       # 15:10 장마감 10분전 (보조 전용)
  KRX_CLOSE_COUNTDOWN_5M  = (15, 15)       # 15:15 장마감 5분전
  KRX_CLOSE_COUNTDOWN_1M  = (15, 19)       # 15:19 장마감 1분전
  KRX_CLOSE_COUNTDOWN_10S = (15, 19, 50)   # 15:19:50 장마감 10초전

  # KRX 정규장 장개시 카운트다운 임계
  KRX_OPEN_COUNTDOWN_10M = (8, 50)         # 08:50 장개시 10분전
  KRX_OPEN_COUNTDOWN_5M  = (8, 55)         # 08:55 장개시 5분전
  KRX_OPEN_COUNTDOWN_1M  = (8, 59)         # 08:59 장개시 1분전
  KRX_OPEN_COUNTDOWN_10S = (8, 59, 50)     # 08:59:50 장개시 10초전

  # NXT 프리마켓 장마감 카운트다운 임계 (5분전이 최대)
  NXT_PRE_CLOSE_COUNTDOWN_5M  = (8, 45)    # 08:45 프리마켓 장마감 5분전
  NXT_PRE_CLOSE_COUNTDOWN_1M  = (8, 49)    # 08:49 프리마켓 장마감 1분전
  NXT_PRE_CLOSE_COUNTDOWN_10S = (8, 49, 50)

  # NXT 프리마켓 장개시 카운트다운 임계
  NXT_PRE_OPEN_COUNTDOWN_10M  = (7, 50)    # 07:50 프리마켓 장개시 10분전
  NXT_PRE_OPEN_COUNTDOWN_5M   = (7, 55)
  NXT_PRE_OPEN_COUNTDOWN_1M   = (7, 59)
  NXT_PRE_OPEN_COUNTDOWN_10S  = (7, 59, 50)

  # NXT 에프터마켓 장개시 카운트다운 임계 (→ 15:40)
  NXT_AFT_OPEN_COUNTDOWN_10M  = (15, 30)   # 15:30 에프터마켓 장개시 10분전
  NXT_AFT_OPEN_COUNTDOWN_5M   = (15, 35)
  NXT_AFT_OPEN_COUNTDOWN_1M   = (15, 39)
  NXT_AFT_OPEN_COUNTDOWN_10S  = (15, 39, 50)

  # NXT 에프터마켓 장마감 카운트다운 임계 (→ 20:00, 5분전이 최대)
  NXT_AFT_CLOSE_COUNTDOWN_5M  = (19, 55)   # 19:55 에프터마켓 장마감 5분전
  NXT_AFT_CLOSE_COUNTDOWN_1M  = (19, 59)
  NXT_AFT_CLOSE_COUNTDOWN_10S = (19, 59, 50)
  ```
- **체크**: P10 — 임계 시각 단일 소스. P24 — DB 아닌 코드 상수.

#### Step 1-5: `daily_time_scheduler.py` — `build_timetable_from_cache()` 카운트다운 엔트리 추가
- 953-965줄 entries 리스트에 `kind="countdown"` 신규 종류 추가:
  ```python
  # kind="countdown" — 카운트다운 갱신 전용 (페이즈 전환 아님, JIF 미수신 공백 보조)
  {"time": _to3(KRX_OPEN_COUNTDOWN_10M),  "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 10분전"},
  {"time": _to3(KRX_OPEN_COUNTDOWN_5M),   "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 5분전"},
  {"time": _to3(KRX_OPEN_COUNTDOWN_1M),   "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 1분전"},
  {"time": _to3(KRX_OPEN_COUNTDOWN_10S),  "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 10초전"},
  {"time": _to3(KRX_CLOSE_COUNTDOWN_10M), "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 10분전"},
  {"time": _to3(KRX_CLOSE_COUNTDOWN_5M),  "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 5분전"},
  {"time": _to3(KRX_CLOSE_COUNTDOWN_1M),  "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 1분전"},
  {"time": _to3(KRX_CLOSE_COUNTDOWN_10S), "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 10초전"},
  # NXT 프리마켓 장개시/장마감, 에프터마켓 장개시/장마감 동일 패턴
  ```
- **체크**: P23 — 엔트리 구조 일관 (`time`/`kind`/`market`/`ctx`). P24 — 함수 50줄 초과 시 헬퍼 분리 검토.

#### Step 1-6: `daily_time_scheduler.py` — `_timetable_event_fired()` countdown 분기 추가
- 1046-1052줄 `if kind == "direct" / elif kind == "phase"` 이후에 신규 분기:
  ```python
  elif kind == "countdown":
      # 보조 로직 — JIF 미수신 공백 시 카운트다운 갱신
      # JIF override가 활성 상태면 스킵 (JIF 1순위 — 중복 갱신 방지)
      market = entry["market"]
      override = _get_active_override(market)
      if override is not None:
          return  # JIF override 활성 → 보조 로직 스킵
      # override 없으면 calc_countdown()으로 보완값 계산 + 브로드캐스트
      phase_name = engine_state.state.market_phase.get(market, "")
      countdown = calc_countdown(market, phase_name)
      if countdown:
          from backend.app.services.engine_account_notify import _broadcast
          schedule_engine_task(
              _broadcast("market-phase", get_market_phase()),
              context=f"countdown 브로드캐스트 ({entry['ctx']})",
          )
  ```
- **체크**: P16 — 보조 경로 실제 실행 연결. P20 — override 만료 시 None → calc_countdown() 정상 작동.

#### Step 1-7: `daily_time_scheduler.py` — `_get_active_override()` 헬퍼 신설
- `calc_countdown()` 근처에 신설:
  ```python
  def _get_active_override(market: str) -> dict | None:
      """JIF override 활성 여부 반환 (만료 시 None — P20 폴백 금지).

      market: "krx" | "nxt"
      반환: {label, remaining_sec, expires_at} | None
      """
      override = (
          engine_state.state.krx_countdown_override if market == "krx"
          else engine_state.state.nxt_countdown_override
      )
      if override is None:
          return None
      expires_at = override.get("expires_at")
      if expires_at is None or _kst_now() >= expires_at:
          # 만료 — None 반환 (P20: 만료된 값 사용 금지)
          return None
      return override
  ```
- **체크**: P20 — 만료 시 None 반환 (폴백 아님). P24 — 순수 함수, 50줄 이하.

#### Step 1-8: `daily_time_scheduler.py` — `get_market_phase()` override 우선 적용
- 384-385줄 수정:
  ```python
  # JIF override 우선 (P10 SSOT — JIF 1순위), 없으면 calc_countdown() 보조
  krx_override = _get_active_override("krx")
  nxt_override = _get_active_override("nxt")
  phase["krx_countdown"] = krx_override if krx_override is not None else calc_countdown("krx", krx)
  phase["nxt_countdown"] = nxt_override if nxt_override is not None else calc_countdown("nxt", nxt)
  ```
- **체크**: P10 — JIF 1순위 SSOT. P16 — `get_market_phase()`가 모든 브로드캐스트 경로에서 호출되므로 override 자동 반영.

#### Step 1-9: `daily_time_scheduler.py` — 카운트다운 맵 누락 페이즈 보완 (방안 4-2)
- `_KRX_COUNTDOWN_MAP`(183-186)에 누락 항목 추가:
  ```python
  "종가 동시호가": (KRX_CLOSING_AUCTION_END, "장마감"),                    # → 15:30
  "장후 시간외": (KRX_AFTER_CLOSE_START, "시간외 종가매매 종료"),          # → 16:00
  "시간외 종가매매 종료 + 시간외 단일가매매 개시": (KRX_SINGLE_PRICE_END, "장 종료"),  # → 18:00
  ```
  - **착수 전 확인**: `KRX_CLOSING_AUCTION_END`, `KRX_AFTER_CLOSE_START`, `KRX_SINGLE_PRICE_END` 상수가 21-49줄에 존재하는지 확인. 없으면 기존 상수명으로 대체 (P10 — 새 하드코딩 금지).
- **체크**: P16 — 누락 페이즈 카운트다운 표시 경로 활성화.

#### Step 1-10: `daily_time_scheduler.py` — NXT 페이즈명 통일 (방안 4-3)
- `_NXT_COUNTDOWN_MAP`(194) `"애프터마켓 지속"` → `"애프터마켓"` 변경.
- `NXT_ACTIVE_PHASES`(236) `"애프터마켓 지속"` → `"애프터마켓"` 변경.
- `calc_timebased_market_phase()` 168-171줄: 18:00 분기 제거 (옵션 A — 제거).
  - `NXT_AFTERMARKET_MID_END`(42) 상수 + `build_timetable_from_cache()` 963줄 18:00 phase 엔트리도 함께 제거.
  - 사전조사 결과(`krx_nxt_market_hours.md`): 15:40~20:00 전체 "애프터마켓" 단일 구간 → 18:00 페이즈 전환 불필요.
- **체크**: P10/P23 — `_JIF_PHASE_MAP_NXT`(`engine_ws_dispatch.py` 224)는 이미 "애프터마켓" 사용 → 불일치 해소. P16 — 18:00 엔트리 제거 후에도 카운트다운은 `kind="countdown"` 엔트리로 갱신됨.

#### Step 1-11: 설계 문서 3.2 매핑 테이블 오류 수정
- `jif_countdown_design.md` 3.2절 KRX 장마감 매핑을 API 문서 기준으로 수정 (섹션 1.5 참조).
- **체크**: P10 — 문서-코드 불일치 해소.

### 3.2 S-1 테스트 계획

| 테스트 파일 | 테스트 항목 |
|-------------|-------------|
| `test_engine_ws_dispatch.py` | (S-2에서 정비 — S-1은 기존 테스트 깨지지 않는지만 확인) |
| `test_daily_time_scheduler.py` | 신규 추가: 카운트다운 엔트리 존재, `_get_active_override()` 만료/활성, `get_market_phase()` override 우선, `_NXT_COUNTDOWN_MAP`/`NXT_ACTIVE_PHASES` "애프터마켓" 통일, 18:00 엔트리 제거 |

### 3.3 S-1 런타임 검증 방법

1. `pytest backend/tests/test_engine_ws_dispatch.py backend/tests/test_daily_time_scheduler.py -v`
2. 런타임 기동 후 JIF 수신 로그(`[연결] JIF 수신: jangubun=..., jstatus=...`)에서:
   - 카운트다운 코드(22/42/44 등) 수신 시 카운트다운 브로드캐스트 로그 확인.
   - 페이즈 전환 코드 수신 시 override 초기화 로그 확인.
3. `python -W error::RuntimeWarning main.py` — async 함수 `await` 누락 검증 (ARCHITECTURE.md 금지 패턴).

### 3.4 S-1 사용자 결정 항목

| 항목 | 설계 문서 권장 | 사용자 확인 필요 |
|------|----------------|------------------|
| NXT 18:00 엔트리 처리 | 옵션 A(제거) — 15:40~20:00 단일 "애프터마켓" 구간이므로 18:00 페이즈 전환 불필요 | ☐ — UI 변화 없음 (NXT 칩이 "애프터마켓"으로 15:40~20:00 동일 표시) |
| `_JIF_IGNORE_CODES` 정리 방식 | `"53"`만 남기고 카운트다운 코드 전부 제거 | ☐ — UI 변화 없음 |

---

## 4. S-2: 프론트엔드 + 테스트 보완 (방안 4-1 + 테스트 정비)

### 4.1 구현 Step

#### Step 2-1: `header.ts` — `formatCountdown()` 포맷 확장 (방안 4-1)
- 74-82줄 수정:
  ```typescript
  // 변경 전
  if (remaining_sec >= 60) return `${label} ${Math.floor(remaining_sec / 60)}분 전`
  return `${label} ${remaining_sec}초 전`

  // 변경 후
  if (remaining_sec >= 60) {
    const min = Math.floor(remaining_sec / 60)
    const sec = remaining_sec % 60
    return sec > 0 ? `${label} ${min}분 ${sec}초 전` : `${label} ${min}분 전`
  }
  return `${label} ${remaining_sec}초 전`
  ```
- **체크**: P21 — 사용자가 "1분 30초 전" 상세 카운트다운 인지 가능. P23 — UI 패턴 일관.

#### Step 2-2: `test_engine_ws_dispatch.py` — JIF 카운트다운 코드 처리 검증으로 변경
- `test_jif_countdown_ignored`(369-376) → `test_jif_countdown_handled`로 변경:
  - jstatus=22 수신 시 `_apply_jif_phase` 미호출(페이즈 전환 아님) + override 저장 + 브로드캐스트 호출 검증.
- JIF constants 테스트(401-)에 `_JIF_COUNTDOWN_KRX`/`_JIF_COUNTDOWN_NXT` 매핑 완전성 검증 추가.
- **체크**: P16 — 카운트다운 처리 경로 테스트로 검증.

#### Step 2-3: `test_daily_time_scheduler.py` — 카운트다운 엔트리·override·맵·페이즈명 테스트 추가
- S-1에서 추가한 테스트 항목 보완 + 프론트엔드 포맷은 백엔드 테스트 범위 아님.
- **체크**: P22 — override 만료/활성 전환 정합성.

### 4.2 S-2 테스트 계획

| 테스트 파일 | 테스트 항목 |
|-------------|-------------|
| `test_engine_ws_dispatch.py` | `test_jif_countdown_ignored` → `test_jif_countdown_handled` 변경, 매핑 테이블 완전성 |
| `test_daily_time_scheduler.py` | S-1 테스트 항목 + override 만료 전환, 카운트다운 엔트리 수 검증 |

### 4.3 S-2 런타임 검증 방법

1. `npm run build` — 프론트엔드 빌드.
2. 브라우저에서 장마감 10분 전~10초 전 구간 헤더 칩 카운트다운 표시 확인:
   - "정규장 장마감 10분 전" → "5분 전" → "1분 30초 전" → "10초 전" 순차 표시.
3. `pytest backend/tests/test_engine_ws_dispatch.py backend/tests/test_daily_time_scheduler.py -v` 재실행.

### 4.4 S-2 사용자 결정 항목

| 항목 | 설계 문서 권장 | 사용자 확인 필요 |
|------|----------------|------------------|
| "X분 Y초 전" 포맷 | 90초 → "1분 30초 전" | ☐ — UI 개선 (사용자가 더 정확한 카운트다운 인지) |

---

## 5. 전체 검증 방법 (설계 문서 섹션 10 참조)

### 5.1 백엔드
- `pytest backend/tests/test_engine_ws_dispatch.py backend/tests/test_daily_time_scheduler.py -v`
- 런타임 기동 후 JIF 수신 로그에서 카운트다운 코드 수신 시 카운트다운 브로드캐스트 확인.
- `python -W error::RuntimeWarning main.py` — async `await` 누락 검증.

### 5.2 프론트엔드
- `npm run build`
- 브라우저에서 장마감 10분 전~10초 전 구간 헤더 칩 카운트다운 표시 확인.

---

## 6. 영향 범위 (6개 파일 — 설계 문서 섹션 8)

| 구분 | 파일 | 변경 내용 | 세션 |
|------|------|-----------|------|
| 백엔드 | `engine_state.py` | `krx_countdown_override`, `nxt_countdown_override` 필드 추가 | S-1 |
| 백엔드 | `engine_ws_dispatch.py` | JIF 카운트다운 매핑 테이블, `_handle_jif()` 카운트다운 처리, `_JIF_IGNORE_CODES` 정리 | S-1 |
| 백엔드 | `daily_time_scheduler.py` | 카운트다운 임계 시각 상수, `build_timetable_from_cache()` 카운트다운 엔트리, `_timetable_event_fired()` countdown 분기, `_get_active_override()` 헬퍼, `get_market_phase()` override 우선, 카운트다운 맵 보완, NXT 페이즈명 통일, 18:00 엔트리 제거 | S-1 |
| 프론트엔드 | `header.ts` | `formatCountdown()` "X분 Y초 전" 포맷 | S-2 |
| 테스트 | `test_engine_ws_dispatch.py` | JIF 카운트다운 코드 무시 검증 → 처리 검증으로 변경 | S-2 |
| 테스트 | `test_daily_time_scheduler.py` | 카운트다운 엔트리·override 우선·맵 보완·페이즈명 통일 테스트 | S-1 + S-2 |
| 문서 | `jif_countdown_design.md` | 3.2절 KRX 장마감 매핑 오류 수정 | S-1 |

### 6.1 거래 로직 영향
없음 — 카운트다운은 표시 전용. 매수/매도/주문 차단 로직은 `get_order_time_block_status()`가 담당하며 카운트다운과 무관.

---

## 7. 착수 전 최종 확인 항목 (설계 문서 섹션 9 + 사전조사 결과)

### 7.1 JIF 코드 매핑 — API 문서 재확인 완료 (섹션 1.5)
- `docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt` 114-144줄 기준:
  - KRX 장개시: 25=10분, 24=5분, 23=1분, 22=10초 ✅
  - KRX 장마감: 44=5분(최대), 43=1분, 42=10초 ✅ (10분전 코드 없음)
  - NXT 프리마켓 장개시: A5=10분, A4=5분, A3=1분, A2=10초 ✅
  - NXT 프리마켓 장마감: C4=5분(최대), C3=1분, C2=10초 ✅
  - NXT 에프터마켓 장개시: B5=10분, B4=5분, B3=1분, B2=10초 ✅
  - NXT 에프터마켓 장마감: D4=5분(최대), D3=1분, D2=10초 ✅

### 7.2 NXT 18:00 엔트리 처리 — 사전조사 완료
- `krx_nxt_market_hours.md` 확인: 15:40~20:00 전체 "애프터마켓" 단일 구간.
- 18:00은 KRX 장 종료 시점일 뿐 NXT 내부 페이즈 변화 아님.
- **결정**: 옵션 A(제거) — `NXT_AFTERMARKET_MID_END` 상수 + 18:00 phase 엔트리 + `calc_timebased_market_phase()` 18:00 분기 제거.

### 7.3 S-1 착수 전 추가 확인 (재심층 사전조사 시)
- `KRX_CLOSING_AUCTION_END`, `KRX_AFTER_CLOSE_START`, `KRX_SINGLE_PRICE_END` 상수명이 21-49줄에 실제 존재하는지 확인 (Step 1-9).
- `schedule_engine_task()` 시그니처 확인 (Step 1-6).
- `engine_account_notify._broadcast` 임포트 경로 확인 (Step 1-3, 1-6).

---

## 8. 참고 자료

- `docs/jif_countdown_design.md` — 설계 문서 (본 태스크 파일의 기준)
- `docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt` — JIF API 명세 (jangubun/jstatus 코드 정의)
- `docs/krx_nxt_market_hours.md` — KRX/NXT 시간대별 장 운영 정보
- `ARCHITECTURE.md` — 불변 원칙 24개 (P1~P24)
- `AGENTS.md` 섹션3 규칙 0-1 — 세션당 1단계 원칙
- `AGENTS.md` 섹션4 "다단계 작업 워크플로우" — 설계→태스크→구현 워크플로우
