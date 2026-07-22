# JIF 카운트다운 복구 설계 문서

> **작성일**: 2026-07-23
> **상태**: 설계 완료 (구현 대기)
> **관련 이슈**: 상단 헤더 KRX/NXT 시간대별 장운영정보(JIF) 카운트다운 상세 표시 누락
> **관련 파일**: `backend/app/services/engine_ws_dispatch.py`, `backend/app/services/daily_time_scheduler.py`, `backend/app/services/engine_state.py`, `frontend/src/layout/header.ts`

---

## 1. 배경 및 문제 현상

### 1.1 문제 현상
상단 헤더의 KRX/NXT 장 상태 칩에서 "정규장 장마감 3분 전 → 2분 → 1분 30초 → 10초" 같은 상세 카운트다운이 표시되지 않음.

### 1.2 근본 원인 (4곳)
- **원인 A**: JIF 카운트다운 코드(22~25, 42~44, A2~A5, B2~B5, C2~C4, D2~D4)가 `_JIF_IGNORE_CODES`에서 전부 무시됨 (`engine_ws_dispatch.py` 228-237줄).
- **원인 B**: "10초 주기 브로드캐스트"가 타임테이블 스케줄러로 대체되어 카운트다운 갱신이 고정 시각(11~12개)에만 발생 (`daily_time_scheduler.py` 896줄).
- **원인 C**: 표시 포맷이 "X분 전"/"X초 전" 이원화만 지원하여 "1분 30초 전" 미지원 (`header.ts` 74-82줄).
- **원인 D**: 카운트다운 맵 누락 페이즈 + NXT "애프터마켓"/"애프터마켓 지속" 페이즈명 불일치 (`daily_time_scheduler.py` 183-195줄, 236줄).

### 1.3 사전 조사 결과
- **NXT 18:00 전환 의미**: `krx_nxt_market_hours.md` 문서상 15:40~20:00 전체가 "애프터마켓" 단일 구간. 18:00은 KRX 장종료 시점일 뿐 NXT 내부 페이즈 변화 아님. JIF API 문서상 NXT는 `56`(에프터마켓 개시, 15:40) → `58`(에프터마켓 마감, 20:00)만 존재. 현재 코드의 `NXT_AFTERMARKET_MID_END = (18, 0)`와 "애프터마켓 지속" 페이즈명은 임의 분할 → P10/P23 위반.
- **JIF 코드 22/42 구분**: API 문서상 `22`=장개시10초전, `42`=장마감10초전으로 명확히 구분됨. `jangubun`(1/2=KRX)으로는 장개시/장마감 구분 불가 → 현재 페이즈(`engine_state.state.market_phase["krx"]`)로 판별 필요.

---

## 2. 설계 원칙

### 2.1 JIF 1순위
- JIF(증권사 장운영정보)가 카운트다운 데이터의 최우선 소스.
- JIF 카운트다운 코드 수신 시 즉시 카운트다운 표시 갱신 + override 저장.
- 증권사 공식 타이밍이므로 정확도 최고.

### 2.2 보조 로직은 공백 시에만
- 앱 자체 로직(`_TIMETABLE` 엔트리, `calc_countdown()`)은 보조 수단.
- 앱 기동 직후 또는 JIF 카운트다운 코드 사이 공백(예: 15:10 수신 후 15:11~15:14)에서만 작동.
- JIF override가 활성 상태면 보조 로직은 스킵 (중복 갱신 방지).

### 2.3 JIF 덮어쓰기 우선
- JIF 수신값이 있으면 보조 로직 값 무시.
- `get_market_phase()`에서 JIF override를 먼저 확인, 없으면 `calc_countdown()` 결과 사용.

### 2.4 아키텍처 원칙 부합
- **P10 (SSOT)**: 카운트다운 임계 시각은 코드 상수(거래소 규정)에서 단일 관리. override는 `engine_state` 단일 소스.
- **P11 (폴링 금지)**: 별도 타이머 없이 기존 `_TIMETABLE` 스케줄러 재사용 (`call_later` 이벤트 기반).
- **P14 (멀티스레드 금지)**: 타이머 1개 유지 (기존 `timetable_timer_handle`).
- **P16 (살아있는 경로)**: JIF 경로 + 타임테이블 보조 경로 모두 실제 실행 경로에 연결.
- **P20 (폴백 금지)**: override 만료 시 None 반환 (만료된 값 사용 금지).
- **P23 (일관성)**: 페이즈명 통일 ("애프터마켓"), `_TIMETABLE` 엔트리 구조 일관.
- **P24 (단순성)**: 별도 타이머 없이 기존 스케줄러 확장. 카운트다운 임계 시각은 사용자 조정 불가 → DB 대신 코드 상수.

---

## 3. 방안 1 — JIF 카운트다운 코드 무시 해제 + override 저장 (JIF 1순위)

### 3.1 대상 파일
`backend/app/services/engine_ws_dispatch.py`

### 3.2 카운트다운 코드 → (라벨, 남은초) 매핑 테이블 신설
`_JIF_IGNORE_CODES`(228줄)를 대체하여 신설.

```python
_JIF_COUNTDOWN_KRX: dict[str, tuple[str, int]] = {
    # 장개시 카운트다운 (→ 09:00) — 현재 페이즈가 "시가 동시호가"일 때
    "25": ("정규장 장개시", 600),   # 10분전 (08:50)
    "24": ("정규장 장개시", 300),   # 5분전  (08:55)
    "23": ("정규장 장개시", 60),    # 1분전  (08:59)
    "22": ("정규장 장개시", 10),    # 10초전 (08:59:50)
    # 장마감 카운트다운 (→ 15:20, 종가동시호가 개시) — 현재 페이즈가 "정규장"일 때
    # API 문서 기준: 44=5분전(최대), 10분전 코드 없음 → 10분전은 _TIMETABLE 보조 엔트리만 담당
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
    # 프리마켓 장마감 (→ 08:50)
    "C4": ("프리마켓 장마감", 300),
    "C3": ("프리마켓 장마감", 60),
    "C2": ("프리마켓 장마감", 10),
    # 에프터마켓 장개시 (→ 15:40)
    "B5": ("에프터마켓 장개시", 600),
    "B4": ("에프터마켓 장개시", 300),
    "B3": ("에프터마켓 장개시", 60),
    "B2": ("에프터마켓 장개시", 10),
    # 에프터마켓 장마감 (→ 20:00)
    "D4": ("에프터마켓 장마감", 300),
    "D3": ("에프터마켓 장마감", 60),
    "D2": ("에프터마켓 장마감", 10),
}
```

### 3.3 `_handle_jif()` 수정 (282줄)
`_JIF_IGNORE_CODES` 무시 분기 제거 후, JIF 수신 시 카운트다운 코드면:
1. 현재 페이즈(`market_phase["krx"]`/`["nxt"]`)로 장개시/장마감 구분 (코드 22/42 중복 해결).
2. 매핑 테이블에서 (라벨, remaining_sec) 조회.
3. `engine_state.state.krx_countdown_override` / `nxt_countdown_override`에 저장 + `expires_at`(수신 시각 + remaining_sec + 여유 5초) 함께 저장.
4. `_broadcast("market-phase", {krx_countdown: {...}, nxt_countdown: {...}})` 즉시 전송.
5. 페이즈 전환 코드(11/21/31/41/51/52/54/55/56/57/58) 수신 시 해당 시장 override 초기화.

### 3.4 `_JIF_IGNORE_CODES` 정리 (229-237줄)
- 카운트다운 코드(22~25, 42~44, A2~A5, B2~B5, C2~C4, D2~D4) 전부 제거.
- `"53"`(사용안함)만 남기거나 세트 자체 삭제 후 매핑 테이블 미포함 코드는 로그만 남기고 무시.

---

## 4. 방안 2 — _TIMETABLE 엔트리로 카운트다운 임계 시각 추가 (별도 타이머 없음)

### 4.1 대상 파일
`backend/app/services/daily_time_scheduler.py`

### 4.2 카운트다운 임계 시각 코드 상수 정의
21-49줄 시간 상수 영역에 추가. 거래소 규정이므로 사용자 조정 불가 → DB 대신 코드 상수 (P24 단순성, P13 메모리 상주 부합).

```python
# KRX 정규장 장마감 카운트다운 임계 (거래소 규정 — 사용자 조정 불가)
KRX_CLOSE_COUNTDOWN_10M = (15, 10)       # 15:10 장마감 10분전
KRX_CLOSE_COUNTDOWN_5M  = (15, 15)       # 15:15 장마감 5분전
KRX_CLOSE_COUNTDOWN_1M  = (15, 19)       # 15:19 장마감 1분전
KRX_CLOSE_COUNTDOWN_10S = (15, 19, 50)   # 15:19:50 장마감 10초전

# KRX 정규장 장개시 카운트다운 임계
KRX_OPEN_COUNTDOWN_10M = (8, 50)         # 08:50 장개시 10분전
KRX_OPEN_COUNTDOWN_5M  = (8, 55)         # 08:55 장개시 5분전
KRX_OPEN_COUNTDOWN_1M  = (8, 59)         # 08:59 장개시 1분전
KRX_OPEN_COUNTDOWN_10S = (8, 59, 50)     # 08:59:50 장개시 10초전

# NXT 프리마켓 장마감 카운트다운 임계
NXT_PRE_CLOSE_COUNTDOWN_5M  = (8, 45)    # 08:45 프리마켓 장마감 5분전
NXT_PRE_CLOSE_COUNTDOWN_1M  = (8, 49)    # 08:49 프리마켓 장마감 1분전
NXT_PRE_CLOSE_COUNTDOWN_10S = (8, 49, 50)

# NXT 프리마켓 장개시 카운트다운 임계
NXT_PRE_OPEN_COUNTDOWN_10M  = (7, 50)    # 07:50 프리마켓 장개시 10분전
# ... (에프터마켓 동일 패턴)
```

### 4.3 `build_timetable_from_cache()`에 카운트다운 엔트리 추가
953-965줄 entries 리스트에 `kind="countdown"` 신규 종류 추가.

```python
# kind="countdown" 신규 — 카운트다운 갱신 전용 (페이즈 전환 아님)
{"time": _to3(KRX_CLOSE_COUNTDOWN_10M), "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 10분전"},
{"time": _to3(KRX_CLOSE_COUNTDOWN_5M),  "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 5분전"},
# ... (장개시, NXT 동일)
```

### 4.4 `_timetable_event_fired()`에 `kind="countdown"` 분기 추가
1042-1052줄에 신규 분기 추가.

```python
elif kind == "countdown":
    # 보조 로직 — JIF 미수신 공백 시 카운트다운 갱신
    # JIF override가 활성 상태면 스킵 (JIF 1순위 — 중복 갱신 방지)
    market = entry["market"]
    override = engine_state.state.krx_countdown_override if market == "krx" else engine_state.state.nxt_countdown_override
    if override and not _override_expired(override):
        return  # JIF override 활성 → 보조 로직 스킵
    # override 없으면 calc_countdown()으로 보완값 계산 + 브로드캐스트
    phase = engine_state.state.market_phase[market]
    countdown = calc_countdown(market, phase)
    if countdown:
        _broadcast_countdown(market, countdown)
```

### 4.5 별도 타이머 없음
기존 `_schedule_next_timetable_event()`가 카운트다운 엔트리 포함 다음 이벤트 자동 예약. 타이머 1개 유지 (P14 부합). `while+sleep` 아닌 `call_later` 기반 (P11 부합).

---

## 5. 방안 3 — get_market_phase()에서 JIF override 우선 적용

### 5.1 대상 파일
`backend/app/services/daily_time_scheduler.py` (370-386줄 `get_market_phase()`)

### 5.2 수정 내용

```python
def get_market_phase():
    phase = {...}
    # JIF override 우선 (P10 SSOT — JIF 1순위)
    krx_override = _get_active_override("krx")
    nxt_override = _get_active_override("nxt")
    phase["krx_countdown"] = krx_override if krx_override else calc_countdown("krx", krx)
    phase["nxt_countdown"] = nxt_override if nxt_override else calc_countdown("nxt", nxt)
    return phase
```

### 5.3 override 만료 로직 (`_get_active_override()` 헬퍼)
- `expires_at` 경과 → None 반환 (P20 폴백 금지: 만료된 값 사용 금지).
- 페이즈 전환 코드 수신 시 override 즉시 초기화 (방안 1-3에서 처리).

### 5.4 engine_state 필드 추가
`engine_state.py` 110줄 부근에 추가.

```python
self.krx_countdown_override: dict | None = None  # {label, remaining_sec, expires_at}
self.nxt_countdown_override: dict | None = None
```

---

## 6. 방안 4 — 표시 포맷 + 맵 보완 + 페이즈명 통일

### 6.1 프론트엔드 포맷 확장
`frontend/src/layout/header.ts` 74-82줄 `formatCountdown()`.

```typescript
// 변경 전
remaining_sec >= 60 → "X분 전" (Math.floor, 90초 → "1분 전")
remaining_sec <  60 → "X초 전"

// 변경 후
remaining_sec >= 60 → "X분 Y초 전" (예: 90초 → "1분 30초 전")
remaining_sec <  60 → "X초 전"
```

### 6.2 KRX 카운트다운 맵 누락 페이즈 보완
`daily_time_scheduler.py` 183-186줄 `_KRX_COUNTDOWN_MAP`에 누락 항목 추가.

- `"종가 동시호가"` → (15:30, "장마감")
- `"장후 시간외"` → (16:00, "시간외 종가매매 종료")
- `"시간외 종가매매 종료 + 시간외 단일가매매 개시"` → (18:00, "장 종료")

### 6.3 NXT 페이즈명 통일
`daily_time_scheduler.py` 188-195줄 `_NXT_COUNTDOWN_MAP`, 236줄 `NXT_ACTIVE_PHASES`.

- 사전 조사 결과: 15:40~20:00 전체가 "애프터마켓" 단일 구간 (`krx_nxt_market_hours.md` 확인).
- `_NXT_COUNTDOWN_MAP`의 `"애프터마켓 지속"` → `"애프터마켓"`으로 변경.
- `NXT_ACTIVE_PHASES`의 `"애프터마켓 지속"` → `"애프터마켓"`으로 변경.
- `_JIF_PHASE_MAP_NXT`(`engine_ws_dispatch.py` 224줄)는 이미 `"애프터마켓"` 사용 → 불일치 해결 (P10/P23 부합).
- `_TIMETABLE`의 18:00 엔트리(`NXT_AFTERMARKET_MID_END`)는 페이즈 전환용이 아닌 카운트다운 갱신용으로 재분류 또는 제거 (착수 전 최종 확인 항목 참조).

---

## 7. 세션 분할 계획

방안 2가 별도 타이머 없이 기존 `_TIMETABLE` 엔트리 추가만으로 해결되어 3세션 → 2세션으로 단축.

### 7.1 1세션 (백엔드 핵심)
방안 1 + 방안 3 + 방안 2 + 방안 4-2/4-3 (백엔드 부분)

- `engine_ws_dispatch.py`: JIF 카운트다운 코드 매핑 테이블, `_handle_jif()` 카운트다운 처리, `_JIF_IGNORE_CODES` 정리
- `engine_state.py`: `krx_countdown_override`, `nxt_countdown_override` 필드 추가
- `daily_time_scheduler.py`:
  - 카운트다운 임계 시각 상수 정의
  - `build_timetable_from_cache()` 카운트다운 엔트리 추가
  - `_timetable_event_fired()` countdown 분기 추가
  - `get_market_phase()` override 우선 적용
  - `_get_active_override()` 헬퍼 신설
  - 카운트다운 맵 누락 페이즈 보완 (방안 4-2)
  - NXT 페이즈명 통일 (방안 4-3)
- 검증: `pytest test_engine_ws_dispatch.py test_daily_time_scheduler.py` + 런타임 기동

### 7.2 2세션 (프론트엔드 + 테스트 보완)
방안 4-1 + 테스트 정비

- `header.ts`: `formatCountdown()` "X분 Y초 전" 포맷 확장 (방안 4-1)
- `test_engine_ws_dispatch.py`: JIF 카운트다운 코드 무시 검증 → 처리 검증으로 변경
- `test_daily_time_scheduler.py`: 카운트다운 엔트리·override 우선·맵 보완·페이즈명 통일 테스트 추가
- 검증: `npm run build` + 브라우저 확인 + `pytest` 재실행

---

## 8. 영향 범위 (6개 파일)

| 구분 | 파일 | 변경 내용 |
|------|------|-----------|
| 백엔드 | `engine_ws_dispatch.py` | JIF 카운트다운 코드 매핑 테이블, `_handle_jif()` 카운트다운 처리, `_JIF_IGNORE_CODES` 정리 |
| 백엔드 | `engine_state.py` | `krx_countdown_override`, `nxt_countdown_override` 필드 추가 |
| 백엔드 | `daily_time_scheduler.py` | 카운트다운 임계 시각 상수, `build_timetable_from_cache()` 카운트다운 엔트리, `_timetable_event_fired()` countdown 분기, `get_market_phase()` override 우선, 카운트다운 맵 보완, NXT 페이즈명 통일 |
| 프론트엔드 | `header.ts` | `formatCountdown()` "X분 Y초 전" 포맷 |
| 테스트 | `test_engine_ws_dispatch.py` | JIF 카운트다운 코드 무시 검증 → 처리 검증으로 변경 |
| 테스트 | `test_daily_time_scheduler.py` | 카운트다운 엔트리·override 우선·맵 보완·페이즈명 통일 테스트 추가 |

### 8.1 거래 로직 영향
없음 — 카운트다운은 표시 전용. 매수/매도/주문 차단 로직은 `get_order_time_block_status()`가 담당하며 카운트다운과 무관.

---

## 9. 착수 전 최종 확인 항목

### 9.1 JIF 코드 22/42 매핑
- API 문서(`docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt` 114-122줄) 기준:
  - `22` = 장개시10초전
  - `23` = 장개시1분전
  - `24` = 장개시5분전
  - `25` = 장개시10분전
  - `42` = 장마감10초전
  - `43` = 장마감1분전
  - `44` = 장마감5분전
- 1세션 착수 전 API 문서 재확인하여 매핑 테이블 최종 확정.
- 특히 `42`=장마감10초전(60초 아님)인지, `43`=장마감1분전(60초)인지, `44`=장마감5분전(300초)인지 확인.
- 10분전 코드가 KRX 장마감에 존재하는지 여부 확인 (API 문서상 44=5분전이 최대, 10분전 코드 명시 없음 → KRX 장마감 10분전은 `_TIMETABLE` 보조 엔트리만 담당).

### 9.2 NXT 18:00 엔트리 처리
- `NXT_AFTERMARKET_MID_END = (18, 0)` 엔트리의 처리 방침 결정:
  - **옵션 A (제거)**: 페이즈명 통일 후 18:00 페이즈 전환이 불필요하므로 `_TIMETABLE`에서 제거.
  - **옵션 B (카운트다운용 유지)**: 18:00을 에프터마켓 장마감(20:00) 카운트다운 중간 갱신 시점으로 활용.
- 사전 조사 결과(`krx_nxt_market_hours.md`): 15:40~20:00 전체가 "애프터마켓" 단일 구간이므로 18:00 페이즈 전환은 의미 없음. 옵션 A(제거) 권장.

---

## 10. 검증 방법

### 10.1 백엔드
- `pytest test_engine_ws_dispatch.py test_daily_time_scheduler.py`
- 런타임 기동 후 JIF 수신 로그(`[연결] JIF 수신: jangubun=..., jstatus=...`)에서 카운트다운 코드(22/42/44 등) 수신 시 카운트다운 브로드캐스트 확인.

### 10.2 프론트엔드
- `npm run build`
- 브라우저에서 장마감 10분 전~10초 전 구간 헤더 칩 카운트다운 표시 확인.

---

## 11. 참고 자료

- `docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt` — JIF API 명세 (jangubun/jstatus 코드 정의)
- `docs/krx_nxt_market_hours.md` — KRX/NXT 시간대별 장 운영 정보
- `ARCHITECTURE.md` — 불변 원칙 24개 (P1~P24)
- `AGENTS.md` 섹션3 규칙 0-1 — 세션당 1단계 원칙
