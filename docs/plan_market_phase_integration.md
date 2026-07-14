# 장운영정보(market_phase) 기반 개별 타이머 통합 수정 계획서

> **작성일**: 2026-07-14
> **상태**: 계획 완료, 단계별 진행 대기
> **승인 상태**: 사용자 승인 대기 (각 Step 시작 시 별도 승인 필요)
> **관련 원칙**: P10 (SSOT), P16 (살아있는 경로), P22 (데이터 정합성), P24 (단순성)

---

## 1. 배경 및 목표

### 1-1. 현재 상태

- 업종 점수 재계산 타이머 3개(08:00/09:00/15:30)는 이미 `_broadcast_market_phase()` 내 페이즈 변경 감지로 통합 완료 (수정 8, 커밋 `aba9e92`).
- 09:00 KRX 추가 구독, 15:30 KRX 해지도 `_broadcast_market_phase()`의 페이즈 변경 핸들러로 동작 중.
- NXT-only 구독 분리(그룹 A/B) 완료.

### 1-2. 목표

남은 개별 타이머를 `market_phase` 이벤트 기반으로 통합:
- `ws_subscribe_start` 타이머 → NXT "프리마켓" 진입 이벤트
- `ws_subscribe_end` 타이머 → NXT "장마감" 진입 이벤트
- JIF 경계/시간대 이벤트 처리 → 서킷브레이커/사이드카만 남기고 제거 (앱 내부 시계 로직이 페이즈 담당)
- `ws_subscribe_start`/`end` 설정 키 + UI 제거

### 1-3. 핵심 설계 원칙

**`is_ws_subscribe_window()` 함수 본문만 market_phase 기반으로 변경** — 호출처 8개 파일을 수정하지 않고도 전환 완료 (P24 단순성).

---

## 2. 현재 타이머 현황

### 2-1. `daily_time_scheduler.py` 타이머 목록

| 타이머 | 예약 시각 | 콜백 | 상태 |
|---|---|---|---|
| `ws_subscribe_start` | 사용자 설정 (기본 09:00) | `_on_ws_subscribe_start` | **제거 대상** |
| `ws_subscribe_end` | 사용자 설정 (기본 15:00) | `_on_ws_subscribe_end` | **제거 대상** |
| `confirmed_download_time` | 20:40 (기본) | `_on_confirmed_download` | 유지 |
| `market_phase` 전환 | 08:00~20:00 (11개) | `_broadcast_market_phase` | 유지 (백업) |
| `buy/sell` 시간 | 사용자 설정 | `_on_auto_trade_transition` | 유지 |
| `midnight` | 00:00 | `_on_midnight` | 유지 |

### 2-2. `is_ws_subscribe_window()` 호출처 (8개 파일)

- `engine_loop.py` 300-304행: WS 연결 루프
- `engine_bootstrap.py` 23-25행: LOGIN 후 파이프라인
- `engine_cache.py` 98-99행: 캐시 로드 후 실시간 필드 초기화
- `engine_service.py` 135행: 설정 변경 시 구간 재판정
- `ws_subscribe_control.py` 177-181행, 237-241행: 구독 파이프라인
- `stock_classification.py` 25-26행: 장중 변경 경고
- `ws_subscribe.py` 라우트 27-31행: 수동 구독 API

**모두 함수 본문만 변경하면 자동 적용 — 호출처 수정 불필요.**

---

## 3. 단계별 수정 계획

### Step 1: `is_ws_subscribe_window()` → market_phase 기반

**파일**: `backend/app/services/daily_time_scheduler.py` (283-324행)

**수정 내용**:
- 시간 비교(`ws_subscribe_start`/`end`) 제거
- `state.market_phase["nxt"]`가 `NXT_ACTIVE_PHASES` 또는 "정규장 준비"인지로 판단
- `ws_subscribe_on` 마스터 스위치 + 거래일 판단은 유지

**검증**: pytest (test_daily_time_scheduler.py) + 런타임 기동

**영향 범위**: 호출처 8개 파일 자동 적용, 수정 불필요

---

### Step 2: `_broadcast_market_phase()` 핸들러 추가 + 타이머 2개 제거

**파일**: `backend/app/services/daily_time_scheduler.py`

**수정 내용**:
1. `_broadcast_market_phase()` 552-559행 확장:
   - NXT "프리마켓" 진입 → `_on_ws_subscribe_start()` 호출 추가
   - NXT "장마감" 진입 → `_on_ws_subscribe_end()` 호출 추가
2. `schedule_ws_subscribe_timers()` 744-758행:
   - `ws_subscribe_start` 타이머 예약 제거 (744-753행)
   - `ws_subscribe_end` 타이머 예약 제거 (755-758행)
   - `confirmed_download_time` 타이머는 유지 (769-778행)
   - market_phase 전환 타이머 11개 유지 (789-799행)

**검증**: pytest + 런타임 기동 (장중이 아닌 시간대이므로 타이머 예약 로그 확인)

**영향 범위**: `_on_ws_subscribe_start`/`_end` 함수 본문은 수정 없이 재사용

---

### Step 3: `ws_subscribe_start`/`end` 설정 키 + UI 제거

**백엔드 (4파일)**:
- `settings_defaults.py` 21-22행: 기본값 2개 제거
- `settings_store.py`: 저장 페이로드 + `_TIME_FIELDS`에서 2개 제거
- `engine_settings.py`: 엔진 설정 dict에서 2개 제거
- `settings_file.py`: `_migrate_remove_ws_subscribe_window_keys()` 마이그레이션 함수 추가 (기존 `_migrate_*` 패턴 준수)

**프론트엔드 (2파일)**:
- `types/index.ts`: `AppSettings`에서 `ws_subscribe_start`/`end` 2개 필드 제거
- `general-settings.ts` 617-638행: "실시간 연결 시간" UI 블록 제거, `scheduleTimeSave` 함수 제거 (단일 호출처 사라지므로 P24), `wsTimeHandle` 변수/cleanup 제거

**백엔드 추가 (1파일)**:
- `engine_service.py` 131행: `_WS_SCHEDULE_KEYS`에서 `ws_subscribe_start`/`end` 2개 제거

**검증**: pytest (test_settings_store + test_engine_settings + test_settings_file_integration) + tsc + vite build + 런타임 기동

**영향 범위**: 기존 DB에 잔존하는 키는 다음 기동 시 마이그레이션으로 자동 DELETE

---

### Step 4: JIF 처리 단순화 (서킷브레이커/사이드카만 남김)

**파일**: `backend/app/services/engine_ws_dispatch.py` (199-350행)

**수정 내용**:
- 제거: `_JSTATUS_KRX_BOUNDARY`, `_JSTATUS_KRX_EVENT`, `_JSTATUS_NXT_BOUNDARY`, `_JSTATUS_NXT_EVENT` 매핑 상수
- 제거: KRX/NXT 경계 이벤트 → `_broadcast_market_phase()` 호출 (290-295행, 335-340행)
- 제거: KRX/NXT 시간대 이벤트 라벨 갱신 (320-329행, 342-349행)
- 유지: `_JSTATUS_KRX_ALERT`, `_KRX_CB_ACTIVATION_CODES`, `_KRX_CB_RELEASE_CODES` (서킷브레이커/사이드카)
- 유지: 서킷브레이커/사이드카 alert + 자동매매 임시중단/재개 로직 (297-318행)

**단순화后的 `_handle_jif`**:
```python
async def _handle_jif(data: dict) -> None:
    """JIF 장운영정보 수신 → 서킷브레이커/사이드카 alert만 처리.
    장운영 페이즈 전환은 앱 내부 시계 로직이 담당 (P10 SSOT).
    """
    jangubun = str(data.get("jangubun", "")).strip()
    jstatus = str(data.get("jstatus", "")).strip()
    if not jangubun or not jstatus:
        return
    if jangubun in ("1", "2"):
        alert = _JSTATUS_KRX_ALERT.get(jstatus, "__no_change__")
        if alert == "__no_change__":
            return
        # ... 기존 서킷브레이커/사이드카 처리 로직 유지 ...
```

**검증**: pytest (test_engine_ws.py) + 런타임 기동

**영향 범위**: JIF 경계 이벤트 제거로 market_phase 전환 최대 1분 지연 (시계 타이머가 백업)

---

### Step 5: 카운트다운 4/3/2분 전 — 프론트엔드 계산 (선택)

**파일**: `frontend/src/layout/header.ts` (71-92행)

**수정 내용**:
- `applyMarketPhaseChip`에서 `marketPhase.krx`/`nxt` 페이즈명과 현재 시각으로 남은 분 계산
- 10/5/4/3/2/1분 전 카운트다운 표시
- 백엔드 타이머 추가 없이 P24/P10 준수

**검증**: tsc + vite build + 브라우저 확인

**영향 범위**: UI 표시만, 백엔드 로직 변경 없음

---

## 4. 수정 파일 목록 및 예상 변경량

### 4-1. 백엔드 (6파일)

| 파일 | Step | 수정 내용 | 예상 변경량 |
|---|---|---|---|
| `daily_time_scheduler.py` | 1, 2 | `is_ws_subscribe_window` market_phase 기반, `_broadcast_market_phase` 핸들러 추가, 타이머 2개 제거 | ±80줄 |
| `engine_ws_dispatch.py` | 4 | JIF 처리 단순화 | -60줄 |
| `engine_service.py` | 3 | `_WS_SCHEDULE_KEYS` 2개 키 제거 | ±5줄 |
| `settings_defaults.py` | 3 | 기본값 2개 제거 | -2줄 |
| `settings_store.py` | 3 | 저장 페이로드 + `_TIME_FIELDS` 2개 제거 | ±10줄 |
| `settings_file.py` | 3 | 마이그레이션 함수 추가 | +20줄 |

### 4-2. 프론트엔드 (2파일)

| 파일 | Step | 수정 내용 | 예상 변경량 |
|---|---|---|---|
| `types/index.ts` | 3 | `AppSettings` 2개 필드 제거 | -2줄 |
| `general-settings.ts` | 3, 5 | UI 블록 제거, 카운트다운 계산 추가(선택) | -40줄 |

### 4-3. 테스트 (5파일)

| 파일 | Step | 수정 내용 | 예상 변경량 |
|---|---|---|---|
| `test_daily_time_scheduler.py` | 1, 2 | `is_ws_subscribe_window` 테스트, 타이머 제거 테스트, 핸들러 테스트 | ±100줄 |
| `test_engine_ws.py` | 4 | JIF 처리 단순화 테스트 | ±30줄 |
| `test_settings_store.py` | 3 | 2개 키 제거 | ±10줄 |
| `test_engine_settings.py` | 3 | 2개 키 제거 | ±10줄 |
| `test_engine_loop.py` | 1 | `is_ws_subscribe_window` 변경 반영 | ±20줄 |

### 4-4. 문서 (1파일)

| 파일 | 수정 내용 |
|---|---|
| `HANDOVER.md` | 각 Step 완료 시 갱신 |

**총 예상 변경량**: 백엔드 ±180줄, 프론트엔드 -40줄, 테스트 ±170줄

---

## 5. 리스크 및 대응 방안

| 리스크 | 영향 | 대응 방안 |
|---|---|---|
| JIF 경계 이벤트 제거 → market_phase 전환 최대 1분 지연 | 09:00 KRX 정규장 전환 시 KRX 단독 종목 재구독 지연 | 시계 타이머 11개가 백업으로 동작, 최대 1분 지연 수용 |
| 07:55 연결 불가 → 08:00 NXT 프리마켓 진입 시 연결 시작 | 08:00~08:01 사이 NXT 틱 누락 가능 | NXT 프리마켓 1분 틱 누락은 거래 영향 미미, 수용 |
| `is_ws_subscribe_window` market_phase 빈 문자열 시 False 반환 | 기동 직후 구독 구간 밖으로 판정 | `calc_timebased_market_phase()`가 기동 시 즉시 호출되므로 빈 문자열 상태 발생 안 함, 에러 로그로 모니터링 |
| `confirmed_download_time` 20:40과 NXT 장마감 20:00 관계 | 20:00 `_on_ws_subscribe_end`가 `confirmed_done=False` 설정, 20:40 다운로드 실행 | 기존과 동일한 40분 간격 유지, 의존성 변경 없음 |
| 키움 커넥터 JIF 미지원 | 키움 사용 시 서킷브레이커/사이드카 감지 불가 | 현재 LS증권만 사용 중, 키움 사용 시 별도 API 조사 필요 |
| 설정 키 제거 시 기존 DB 잔존 값 | 기존 사용자 DB에 `ws_subscribe_start`/`end` 잔존 | `settings_file.py` 마이그레이션 함수로 다음 기동 시 자동 DELETE |
| `engine_service.py` 설정 변경 핸들러 동작 변화 | `ws_subscribe_on` 토글 시에만 구간 재판정 | market_phase 기반으로 판정하므로 장중 토글 시 즉시 연결/해제, 기존과 동일 |
| NXT "장마감" 전환 감지 실패 | 20:00 시계 타이머 누락 시 WS 연결 해제 안 됨 | 시계 타이머 11개 중 20:00 포함, 백업 존재 |

---

## 6. 세션 분할 (규칙 0-1 준수)

| 세션 | Step | 내용 | 검증 |
|---|---|---|---|
| 1 | Step 1 | `is_ws_subscribe_window()` market_phase 기반 변경 | pytest + 런타임 기동 |
| 2 | Step 2 | `_broadcast_market_phase` 핸들러 추가 + 타이머 2개 제거 | pytest + 런타임 기동 |
| 3 | Step 3 | 설정 키 2개 + UI 제거 + 마이그레이션 | pytest + tsc + vite build |
| 4 | Step 4 | JIF 처리 단순화 | pytest + 런타임 기동 |
| 5 | Step 5 | 카운트다운 프론트엔드 계산 (선택) | tsc + vite build + 브라우저 확인 |

---

## 7. 아키텍처 원칙 부합 여부

### 7-1. P10 (SSOT) — 부합
`market_phase`가 구독 구간 판단의 단일 기준. `ws_subscribe_start`/`end` 시간 설정과 `market_phase` 이중 기준을 단일 기준으로 통합.

### 7-2. P24 (단순성) — 부합
타이머 2개 제거, JIF 처리 로직 단순화. `is_ws_subscribe_window()` 함수 본문만 변경하여 호출처 수정 최소화.

### 7-3. P22 (데이터 정합성) — 부합
`_reset_realtime_fields` → `recompute_sector_summary_now` → `subscribe_sector_stocks_0b` 순서가 `_broadcast_market_phase` 단일 핸들러 내에서 보장.

### 7-4. P16 (살아있는 경로) — 부합
`ws_subscribe_start`/`end` 설정 키가 UI에 표시되지만 실제 market_phase와 무관하게 동작하는 dead code 상태 해소.

### 7-5. P21 (사용자 투명성) — 부합
구독 시작/종료가 market_phase 전환 시점에 자동 발생, 화면의 장 상태 칩으로 사용자 인지 가능.

### 7-6. P5 (EventBus 금지) — 부합
`_broadcast_market_phase` 내 `if` 분기로 직접 핸들러 호출. 발행구독 패턴 도입 없음.

### 7-7. P20 (폴백 금지) — 부합
`is_ws_subscribe_window()`에서 `market_phase` 빈 문자열 시 에러 로그 처리, 폴백으로 덮지 않음.

---

## 8. JIF 명세서 요약 (참고)

### 8-1. 위치
`docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt`

### 8-2. 응답 필드
- `body.jangubun`: 장구분 (1=코스피, 2=코스닥, 6=NXT전용)
- `body.jstatus`: 장상태 (코드값)

### 8-3. jstatus 주요 코드

**공통 (KRX/NXT)**:
- 11: 장전동시호가개시
- 21: 장시작 / 41: 장마감
- 22~25: 장개시 10초/1분/5분/10분 전
- 42~44: 장마감 10초/1분/5분 전
- 51/52/54: 시간외종가/단일가 매매 개시/종료
- 55~58: 프리마켓/에프터마켓 개시/마감
- A2~A5, B2~B5, C2~C4, D2~D4: NXT 카운트다운

**KOSPI/KOSDAQ 전용 (서킷브레이커/사이드카)**:
- 61: 서킷브레이커 1단계 발동
- 62: 서킷브레이커 1단계 해제
- 63: 서킷브레이커 1단계 동시호가 종료
- 64: 사이드카 매도 발동 / 65: 사이드카 매도 해제
- 66: 사이드카 매수 발동 / 67: 사이드카 매수 해제
- 68: 서킷브레이커 2단계 발동
- 69: 서킷브레이커 3단계 발동, 당일 장종료
- 70: 서킷브레이커 2단계 해제
- 71: 서킷브레이커 2단계 동시호가 종료

### 8-4. 선택 수신
JIF 구독은 `tr_cd: "JIF"`, `tr_key: "0"` 하나로 모든 장운영정보 수신. 사이드카/서킷브레이커만 선택 수신 불가 — 앱 내부에서 `jstatus` 61~71만 처리하고 나머지 무시.

### 8-5. 키움 커넥터
`kiwoom_connector.py`에 JIF 구독/처리 코드 없음. 키움 사용 시 JIF 기반 사이드카/서킷브레이커 감지 불가. 별도 API 조사 필요.

---

## 9. 순서 보장 (P22 데이터 정합성)

### 9-1. NXT 프리마켓 진입 (08:00) 순서

```text
1. _reset_realtime_fields()        # 실시간 필드 초기화 (전일 확정 데이터 제거)
2. recompute_sector_summary_now()  # 업종 필터 최신화 (KRX 단독 종목 제외)
3. subscribe_sector_stocks_0b(nxt_only=True)  # NXT 종목만 구독
```

### 9-2. 현재 구조에서의 순서 보장 방식

- `_on_ws_subscribe_start`가 `_reset_realtime_fields` + `ws_window_changed_event.set()` 수행
- `engine_loop`가 이벤트 수신 후 WS 연결 → LOGIN → `_login_post_pipeline` → `run_conditional_reg_pipeline` → `subscribe_sector_stocks_0b(nxt_only=is_nxt_only_window())`
- `_on_nxt_premarket_start`가 `recompute_sector_summary_now` 수행

**Step 2 후순서**:
- `_broadcast_market_phase`에서 `_on_nxt_premarket_start`와 `_on_ws_subscribe_start`를 `schedule_engine_task`로 순차 예약
- `_on_nxt_premarket_start`: 재계산만
- `_on_ws_subscribe_start`: 초기화 + 연결 통지 → LOGIN → 구독

---

## 10. 진행 상태 추적

| Step | 상태 | 세션 | 커밋 | 검증 결과 |
|---|---|---|---|---|
| 1 | 완료 | 1 | `076a66b` | pytest 133+90 passed, 런타임 215ms OK |
| 2 | 완료 | 1 | `076a66b` | pytest 133+90 passed, 런타임 209ms OK |
| 3 | 대기 | - | - | - |
| 4 | 대기 | - | - | - |
| 5 | 대기 | - | - | - |

---

## 11. 다음 세션 시작 가이드

1. `HANDOVER.md` 확인
2. 본 계획서의 Step 1 내용 확인
3. 사용자 승인(실행 지시어) 대기
4. Step 1 사전조사 (규칙 0-2): 의존성/영향범위/아키텍처 원칙 부합 여부
5. Step 1 수정: `is_ws_subscribe_window()` market_phase 기반 변경
6. Step 1 검증: pytest + 런타임 기동
7. 잔존 프로세스 0건 확인 (규칙 5-1)
8. HANDOVER.md 갱신 + 사용자 보고
