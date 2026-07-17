# 설계서: 1일봉차트 확정 다운로드 시간 DB 타임테이블 통합

> **상태**: 설계 완료 · 구현 승인 대기
> **작성일**: 2026-07-18
> **전신**: 이전 세션 검토(방식 A/B 비교) + 사용자 확정 "아키텍처 원칙 완전 부합 방안(방식 A)" 채택
> **관련 원칙**: P10(SSOT) · P14(단일 타이머) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 1. 배경 및 목적

### 1-1. 현재 구조 (문제 상황)
- 1일봉차트 확정시세 다운로드 시간(`confirmed_download_time`, 기본값 `"20:40"`)은 별도 설정 키 + 별도 타이머로 관리
- 타임테이블 스케줄러(`timetable.*` 3개 키 + 거래소 고정 7개 시간)와 **이중 타이머 구조**
  - 타임테이블 타이머: `state.timetable_timer_handle` (단일 call_later)
  - 확정 다운로드 타이머: `state.ws_subscribe_timer_handles` (리스트, 사실상 1개만 사용)
- `schedule_ws_subscribe_timers()` 함수가 사실상 `confirmed_download_time` 타이머만 담당 (다른 타이머들은 이전 다단계 작업에서 모두 제거됨, 주석 1145-1173 참조)
- 시간 설정 키 네임스페이스 불일치: `timetable.*` 3개 vs 일반 키 `confirmed_download_time` 1개

### 1-2. 목적
- 모든 시간 스케줄을 단일 타임테이블(`_TIMETABLE` 리스트 + 단일 call_later)로 일원화
- 시간 설정 키를 `timetable.*` 네임스페이스로 단일화 (P10 SSOT, P23 일관성)
- 단일 타이머 유지 (P14)
- 사용자 체감 변화 없음 — UI 입력칸, 다운로드 실행 시간, 토글 ON/OFF 동작 모두 기존과 동일

### 1-3. 사용자 확정 사항
1. `confirmed_download_time` → `timetable.confirmed_download` 로 키 이름 변경
2. DB 마이그레이션 포함 (db-backup 스크립트로 백업 후 진행)
3. `build_timetable_from_cache()`에 11번째 항목 추가
4. `schedule_ws_subscribe_timers()`에서 confirmed_download 분기 제거
5. 멱등성 가드 추가 (`last_confirmed_download_date`)
6. 토글 OFF 시 타임테이블 엔트리 스킵
7. 순서 검증 2그룹 분리 (사전 준비 3개 < 09:00, 확정 다운로드 > 20:00)

### 1-4. 사용자 확인 사항 (변경 없음)
- 다운로드 실행 시간: 기존과 동일 (기본 20:40)
- 토글 ON/OFF 동작: 기존과 동일 (`scheduler_market_close_on` 토글)
- UI 입력칸: 시간 설정 탭 "1일봉차트 자동다운로드" 섹션 그대로 유지
- 사용자가 체감하는 변화 없음 (내부 타이머 통합만)

---

## 2. 아키텍처 원칙 준수

| 원칙 | 준수 내용 |
|---|---|
| **P10 (SSOT)** | 모든 시간 스케줄 키를 `timetable.*` 네임스페이스로 단일화. 단일 타임테이블(`_TIMETABLE`) + 단일 타이머(`timetable_timer_handle`)로 일원화. `ws_subscribe_timer_handles` 제거 |
| **P14 (단일 타이머)** | `state.timetable_timer_handle` 1개만 유지. `state.ws_subscribe_timer_handles` 리스트 제거 (전체 검색 후 제거 결정) |
| **P16 (살아있는 경로)** | 토글 OFF 시 타임테이블 엔트리를 빌드 단계에서 스킵 — dead path(콜백 호출 후 아무 동작 없음) 제거. 실행 경로에 있는 엔트리만 타임테이블에 존재 |
| **P20 (폴백 금지)** | 기존 `_cache_time()` 패턴 그대로 사용 — 캐시에 키 없으면 `DEFAULT_USER_SETTINGS` 기본값, 그것도 없으면 `ValueError`. silent `except: pass` 금지 |
| **P21 (사용자 투명성)** | UI에 이미 표시됨 (시간 설정 탭). 순서 검증 에러 시 422 응답 → 토스트 메시지로 사용자 안내 (기존 패턴 유지) |
| **P22 (데이터 정합성)** | `state.last_confirmed_download_date` 멱등성 가드 추가 — 같은 날 중복 다운로드 차단. 기존 `last_realtime_reset_date` 패턴과 동일 |
| **P23 (일관성)** | 시간 키 모두 `timetable.*` 패턴. 타임테이블 엔트리 모두 동일 dict 구조(`time`/`kind`/`action`/`ctx`). 저장 함수 `scheduleTimetableSave()`로 통합. `_on_confirmed_download()` 콜백 재사용 — 신규 함수 작성 금지 |
| **P24 (단순성)** | `schedule_ws_subscribe_timers()` 사실상 confirmed_download_time만 담당 → 통합 시 함수 축소/제거. 단일 타임테이블 + 단일 타이머. 함수 50줄 이하 유지 |

---

## 3. 키 변경 계획

### 3-1. 시간 키 (timetable.* 네임스페이스)

| 기존 키 | 신규 키 | 기본값 | 비고 |
|---------|---------|--------|------|
| `confirmed_download_time` | `timetable.confirmed_download` | `"20:40"` | DB 마이그레이션 대상 |

### 3-2. 토글 키 (유지 — 시간이 아닌 ON/OFF)

| 키 | 기본값 | 비고 |
|----|--------|------|
| `scheduler_market_close_on` | `True` | 1일봉 다운로드 ON/OFF 토글. 시간이 아닌 토글이므로 `timetable.*` 네임스페이스 대상 아님 (P23 — 시간 키만 timetable.* 적용) |
| `scheduler_5d_download_on` | `True` | 5일 거래대금/최고가 롤링 다운로드 토글. 동일하게 유지 |

### 3-3. DB 마이그레이션 절차 (db-backup 스킬 선행)

1. **db-backup 스킬 호출**: `stocks.db`, `stocks.db-shm`, `stocks.db-wal` 타임스탬프 백업
2. **일회성 마이그레이션 스크립트** (구현 세션에서 실행):
   - `integrated_system_settings` 테이블에서 `key='confirmed_download_time'` 행을 `key='timetable.confirmed_download'`로 UPDATE
   - 값은 그대로 유지 (사용자 설정값 보존)
   - 마이그레이션 전후 행 수 검증 (1행 → 1행)
   - 실패 시 백업에서 즉시 복원
3. **DEFAULT_USER_SETTINGS 동기화**: `settings_defaults.py`에서 `confirmed_download_time` 제거, `timetable.confirmed_download` 추가
4. **engine_settings.py 동기화**: `result["timetable.confirmed_download"]`로 변경, 기본값 `"20:40"` 명시

---

## 4. 백엔드 설계

### 4-1. 타임테이블 엔트리 추가 (build_timetable_from_cache)
**파일**: `backend/app/services/daily_time_scheduler.py`

`build_timetable_from_cache()`에 11번째 항목 추가:

```python
# 11번째 항목 — 확정 데이터 다운로드 (timetable.confirmed_download)
# 토글 OFF 시 엔트리 스킵 (P16 살아있는 경로 — dead path 제거)
scheduler_close_on = bool(settings.get("scheduler_market_close_on", True))
if scheduler_close_on:
    cd = _cache_time("timetable.confirmed_download")
    entries.append({
        "time": cd,
        "kind": "direct",
        "action": _on_confirmed_download,
        "ctx": f"확정 데이터 다운로드 ({cd[0]:02d}:{cd[1]:02d})",
    })
```

- `cd = _cache_time("timetable.confirmed_download")` — 기존 `_cache_time()` 패턴 그대로 사용 (P23 일관성)
- `kind="direct"` — 사전 트리거 3개와 동일 패턴 (P23)
- `_on_confirmed_download()` 콜백 재사용 — 신규 함수 작성 금지 (P23 공통 자산 재사용)
- 토글 OFF 시 엔트리 자체 스킵 → 콜백 내부 게이트 불필요 (P16 — dead path 제거)

### 4-2. 멱등성 가드 추가 (P22)
**파일**: `backend/app/services/engine_state.py` + `backend/app/services/daily_time_scheduler.py`

#### 신규 state 필드
`engine_state.py`에 추가:
```python
last_confirmed_download_date: str | None = None  # 확정 다운로드 멱등성 가드 (P22)
```

#### 가드 위치
`_on_confirmed_download()` 진입부:
```python
async def _on_confirmed_download() -> None:
    try:
        today_str = _kst_now().strftime("%Y%m%d")
        if state.last_confirmed_download_date == today_str:
            logger.debug("[스케줄] 확정 다운로드 오늘 이미 실행 — 스킵 (P22)")
            return
        logger.info("[스케줄] 확정 시세 다운로드 시각 도달 → 확정 데이터 다운로드 트리거")
        _fire_unified_confirmed_fetch()
        state.last_confirmed_download_date = today_str
    except Exception as e:
        logger.warning("[스케줄] 확정 데이터 다운로드 콜백 오류: %s", e, exc_info=True)
```

#### 기존 패턴 일관성 (P23)
- `_on_realtime_fields_reset()`의 `state.last_realtime_reset_date` 패턴과 동일 (이미 라인 813에서 사용 중)
- `_init_ws_subscribe_state()`의 `state.last_ws_subscribe_start_date`와 동일

#### 자정 리셋
- 자정 처리 시점(기존 `_apply_auto_toggle_on_startup` 또는 별도 자정 트리거)에서 `last_confirmed_download_date = None` 리셋
- 기존 `last_realtime_reset_date` 리셋 패턴과 동일하게 처리

### 4-3. schedule_ws_subscribe_timers() 처리
**파일**: `backend/app/services/daily_time_scheduler.py`

- `confirmed_download_time` 분기(라인 1154-1166) 제거
- 함수 자체가 사실상 빈 함수 → **함수 전체 제거** 검토
- 단, `state.ws_subscribe_timer_handles` 리스트가 다른 용도로 사용되는지 전체 검색 후 제거 결정 (P16 — dead code 방치 금지)
- 제거 대상: `schedule_ws_subscribe_timers()` 함수 + `_fire_confirmed_download()` 동기 래퍼 (타임테이블이 직접 `_on_confirmed_download()` 호출하므로 래퍼 불필요, P24 단순성)

### 4-4. engine_service.py 설정 변경 감지
**파일**: `backend/app/services/engine_service.py`

#### 변경 전
```python
_WS_SCHEDULE_KEYS = {"confirmed_download_time", "scheduler_market_close_on"}
if changed_keys & _WS_SCHEDULE_KEYS:
    await _dts.schedule_ws_subscribe_timers(new_settings)
    ...
```

#### 변경 후
```python
# _WS_SCHEDULE_KEYS 제거 (confirmed_download_time 키 자체 제거)
# _TIMETABLE_KEYS에 timetable.confirmed_download + scheduler_market_close_on 추가
_TIMETABLE_KEYS = {
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
    "timetable.confirmed_download",      # 신규 — 시간 키
    "scheduler_market_close_on",         # 신규 — 토글 변경 시 타임테이블 재빌드 필요
}
if changed_keys & _TIMETABLE_KEYS:
    # 기존 재빌드 + 재예약 로직 (변경 없음)
    _dts_mod._TIMETABLE = build_timetable_from_cache(state.integrated_system_settings_cache)
    _schedule_next_timetable_event()
```

- `scheduler_market_close_on` 토글 변경 시에도 타임테이블 재빌드 필요 (엔트리 스킵/추가)
- 기존 `_WS_SCHEDULE_KEYS` 분기의 "활성→구간밖 즉시 구독 해제" / "비활성→구간안 즉시 구독 시작" 로직은 `scheduler_market_close_on`만 남으므로 별도 분기 유지 검토 (또는 `_TIMETABLE_KEYS` 분기 내부로 통합)

### 4-5. 부트스트랩 catch-up 처리
**파일**: `backend/app/services/daily_time_scheduler.py` (라인 686-711)

#### 현재 로직
- 단절 구간 기동 시 `confirmed_download_time`과 현재 시각 비교 → 캐시 날짜 ≠ 최근 확정 거래일이면 자동 다운로드

#### 통합 후 처리
- 키 참조만 `timetable.confirmed_download`로 변경
- 멱등성 가드(`last_confirmed_download_date`)가 이미 중복 방지하므로 부트스트랩 catch-up 로직은 단순화:
  - 단절 구간 + 캐시 날짜 ≠ 최근 확정 거래일 + `last_confirmed_download_date != today` → `_fire_unified_confirmed_fetch()` 호출
  - 멱등성 가드가 중복 실행 차단 (P22)

#### 주의
- 부트스트랩 catch-up은 타임테이블 타이머와 별도 경로 — `_init_ws_subscribe_state()` 내 유지 (P16 — 기동 시 누락 방지 보완 경로)
- 타임테이블 타이머는 "다음 미래 이벤트"만 예약하므로 기동 시 이미 지난 20:40는 부트스트랩이 담당 (기존 패턴과 동일)

### 4-6. 순서 검증 로직 조정 (settings_store.py)
**파일**: `backend/app/core/settings_store.py`

#### 현재 검증 조건
```python
_TIMETABLE_ORDER_KEYS = (
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
)
# 검증: rt <= ws <= krx < 09:00
```

#### 신규 검증 조건 (2개 그룹 분리)
```python
# 그룹 1: 장 전 사전 준비 (기존 3개 키)
_TIMETABLE_PRE_OPEN_KEYS = (
    "timetable.realtime_reset",
    "timetable.ws_prestart",
    "timetable.krx_pre_subscribe",
)
# 검증: rt <= ws <= krx < 09:00

# 그룹 2: 장 후 확정 다운로드 (신규 1개 키)
_TIMETABLE_POST_CLOSE_KEYS = (
    "timetable.confirmed_download",
)
# 검증: confirmed_download > 20:00 (NXT 장마감 이후만 허용)
```

#### 이유
- 20:40는 09:00 이전 조건과 양립 불가 → 동일 검증식에 넣으면 P20 위반 (무조건 실패)
- 장 후 다운로드는 NXT 장마감(20:00) 이후만 의미 있으므로 별도 하한선 검증
- 상한선은 두지 않음 (사용자가 23:50까지 설정 가능 — 증권사 확정 데이터 준비 지연 대비)

#### 구현 방식
- `_validate_timetable_order()`를 2개 검증 단계로 분리 (또는 2개 함수로 분리)
- `_TIME_FIELDS`에 `timetable.confirmed_download` 추가, `confirmed_download_time` 제거
- `select_keys` 확장: `timetable.confirmed_download`가 data에 있으면 그룹 2 검증용으로 추가

### 4-7. settings_defaults.py 변경
**파일**: `backend/app/core/settings_defaults.py`

#### 변경 전 (라인 19-20)
```python
# 웹소켓
"confirmed_download_time": "20:40",
```

#### 변경 후
```python
# 타임테이블 — 장 후 확정 다운로드 (P10 SSOT, P23 일관성)
"timetable.confirmed_download": "20:40",
```

- 기존 `timetable.*` 3개 키(라인 121-123) 바로 아래에 추가하여 네임스페이스 일관성 유지

### 4-8. engine_settings.py 변경
**파일**: `backend/app/core/engine_settings.py` (라인 278-279)

#### 변경 전
```python
result["confirmed_download_time"] = str(merged.get("confirmed_download_time", "20:40"))[:5]
```

#### 변경 후
```python
result["timetable.confirmed_download"] = str(merged.get("timetable.confirmed_download", "20:40"))[:5]
```

---

## 5. 프론트엔드 설계

### 5-1. 키 참조 변경 (general-settings.ts)
**파일**: `frontend/src/pages/general-settings.ts`

#### 변경 대상
- `vals.confirmed_download_time` → `vals['timetable.confirmed_download']` (4곳: 라인 118, 121, 312, 967)
- `scheduleConfirmedDlSave()` — `scheduleTimetableSave()`와 동일 패턴으로 통합 (P23 일관성)
  - 단, `scheduleTimetableSave()`의 순서 검증 에러 처리(422 응답) 동일 적용
- `syncFromSettings()` (라인 967): `r.confirmed_download_time` → `r['timetable.confirmed_download']`

#### scheduleConfirmedDlSave 통합
```typescript
// 기존 scheduleConfirmedDlSave() 제거 → scheduleTimetableSave() 호출로 통일
confirmedDlSlot = createTimeSlot(confirmedDlH, confirmedDlM, (h, m) => {
  confirmedDlH = h; confirmedDlM = m; updateTimeSlotDisplay(confirmedDlSlot!, h, m)
  scheduleTimetableSave('timetable.confirmed_download', `${h}:${m}`)
})
```

- 기존 `scheduleTimetableSave()` 함수 시그니처 재사용 (P23)
- 422 검증 에러 토스트 자동 적용 (기존 `scheduleTimetableSave`가 이미 `toastResult` 호출)

### 5-2. UI 변경 (없음)
- 시간 슬롯 UI는 그대로 (이미 시간 설정 탭에 있음)
- 토글 UI도 그대로 (`scheduler_market_close_on` 키 유지)
- 사용자 체감 변화 없음 — 내부 키 이름만 변경

### 5-3. types/index.ts 변경
**파일**: `frontend/src/types/index.ts` (라인 150)

- `AppSettings` 인터페이스에서 `confirmed_download_time` 제거
- `timetable.confirmed_download` 추가 (기존 `timetable.*` 3개 키 옆)

---

## 6. 테스트 변경

### 6-1. test_daily_time_scheduler.py (27곳)
- `confirmed_download_time` → `timetable.confirmed_download` 치환
- `schedule_ws_subscribe_timers()` 관련 테스트 → 타임테이블 기반 테스트로 전환
- 멱등성 가드 테스트 추가 (같은 날 2회 호출 시 2회째 스킵)
- 토글 OFF 시 타임테이블 엔트리 스킵 테스트 추가
- `build_timetable_from_cache()` 11번째 항목 빌드 테스트 추가

### 6-2. test_engine_settings.py (5곳)
- 키 이름 치환 (`confirmed_download_time` → `timetable.confirmed_download`)
- `_TIMETABLE_KEYS` 변경 반영 — `timetable.confirmed_download` + `scheduler_market_close_on` 추가

### 6-3. test_settings_store.py (3곳)
- `_TIMETABLE_ORDER_KEYS` 2그룹 분리에 맞춘 순서 검증 테스트
- `timetable.confirmed_download` > 20:00 검증 테스트 추가
- `timetable.confirmed_download` ≤ 20:00 시 422 에러 테스트 추가

---

## 7. 세션 분할 계획 (AGENTS.md 섹션3 규칙 0-1: 세션당 1단계)

| 세션 | 작업 범위 | 검증 |
|---|---|---|
| **1세션 (본 설계서)** | 설계서 작성 — 검토 결과(이전 세션) + 사용자 확정 7항목 반영 | 설계서 완성 |
| **2세션** | 심층 사전조사 + 태스크 파일 작성 — 대상 파일별 의존성·영향 범위 식별, 태스크 파일에 단계별 검증 항목 명시 | 태스크 파일 완성 |
| **3세션** | DB 마이그레이션 + 백엔드 키 변경 — db-backup 스크립트 백업 → 마이그레이션 스크립트 실행 → `settings_defaults.py`/`engine_settings.py`/`settings_store.py` 키 변경 + 순서 검증 2그룹 분리 → 테스트 수정 | py_compile + ruff + test_settings_store + test_engine_settings + 런타임 기동 RuntimeWarning 0건 + 잔존 프로세스 0건 |
| **4세션** | 타임테이블 통합 + 멱등성 가드 — `build_timetable_from_cache()` 11번째 항목 추가 + 토글 연동 + `_on_confirmed_download()` 멱등성 가드 + `schedule_ws_subscribe_timers()` 분기 제거 (또는 함수 제거) + `engine_service.py` 설정 변경 감지 키 이동 + 부트스트랩 catch-up 키 참조 변경 → 테스트 수정 | py_compile + ruff + test_daily_time_scheduler + 전체 회귀 + 런타임 기동 RuntimeWarning 0건 + 잔존 프로세스 0건 |
| **5세션** | 프론트엔드 키 참조 변경 + 저장 함수 통합 — `general-settings.ts` 키 참조 변경 + `scheduleConfirmedDlSave()` → `scheduleTimetableSave()` 통합 + `types/index.ts` 변경 + 테스트 갱신 → 최종 검증 + 계획서 삭제 | typecheck + build + vitest + 브라우저 확인 (사용자) + 계획서 2개 삭제 (규칙 11) |

### 세션 분할 이유
- **3세션 분리**: DB 마이그레이션은 되돌리기 어려운 작업 → 백업 + 키 변경 + 검증을 한 세션에서 완료하여 마이그레이션 실패 시 즉시 복원 가능
- **4세션 분리**: 타임테이블 통합은 백엔드 핵심 로직 변경 → 멱등성 가드 + 토글 연동 + 부트스트랩 catch-up을 한 세션에서 완료하여 일관성 유지
- **5세션 분리**: 프론트엔드는 단일 파일 변경 + 최종 검증 + 계획서 삭제 (규칙 11)

---

## 8. 위험 요소 및 완화

| 위험 | 완화 |
|------|------|
| DB 마이그레이션 실패 | db-backup 스킬로 백업 후 진행, 실패 시 즉시 복원. 마이그레이션 전후 행 수 검증 (1행 → 1행) |
| 기존 사용자 설정값 손실 | UPDATE 시 값은 그대로 유지, key만 변경. 마이그레이션 전후 값 비교 검증 |
| 멱등성 가드 자정 리셋 누락 | 기존 `last_realtime_reset_date` 리셋 위치와 동일하게 처리. 리셋 누락 시 다음 날 다운로드 안 됨 → 런타임 기동 시 가드 리셋 보완 |
| 부트스트랩 catch-up과 타임테이블 타이머 중복 | 멱등성 가드가 2차 차단 (이중 안전장치). 부트스트랩이 먼저 실행되더라도 가드가 타임테이블 타이머의 중복 호출 차단 |
| `schedule_ws_subscribe_timers()` 제거 시 다른 호출자 영향 | 제거 전 전체 검색으로 호출자 확인 (P16). 호출자가 있으면 함수 유지 + 내부만 단순화 |
| `_fire_confirmed_download()` 동기 래퍼 제거 시 영향 | 타임테이블이 직접 `_on_confirmed_download()` 비동기 호출 → `schedule_engine_task()`로 래핑 필요. 기존 `_fire_confirmed_download()` 패턴 확인 후 결정 |
| 토글 OFF 시 부트스트랩 catch-up 동작 | 부트스트랩 catch-up은 `scheduler_market_close_on` 토글 확인 후 실행 (토글 OFF 시 스킵). 타임테이블 엔트리 스킵과 일관성 유지 |

---

## 9. 아키텍처 원칙 부합 검증 (최종)

| 원칙 | 부합 | 비고 |
|------|------|------|
| P10 SSOT | ✅ 완전 | 모든 시간 키 `timetable.*`, 단일 타임테이블 + 단일 타이머 |
| P14 단일 타이머 | ✅ 완전 | `state.timetable_timer_handle` 1개, `ws_subscribe_timer_handles` 제거 |
| P16 살아있는 경로 | ✅ 완전 | 토글 OFF 시 엔트리 스킵 (dead path 제거). 부트스트랩 catch-up 유지 (기동 시 누락 방지) |
| P20 폴백 금지 | ✅ 완전 | `_cache_time()` 패턴, 누락 시 ValueError. silent `except: pass` 금지 |
| P21 사용자 투명성 | ✅ 완전 | UI에 이미 표시됨. 순서 검증 에러 토스트 유지 |
| P22 데이터 정합성 | ✅ 완전 | `last_confirmed_download_date` 멱등성 가드. 자정 리셋 |
| P23 일관성 | ✅ 완전 | 시간 키 모두 `timetable.*`, 엔트리 동일 dict 구조, 저장 함수 통합, 콜백 재사용 |
| P24 단순성 | ✅ 완전 | `schedule_ws_subscribe_timers()` 제거, 단일 타임테이블, 함수 50줄 이하 |

---

## 10. 사용자 체감 변화 (없음)

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| 다운로드 실행 시간 | 20:40 (기본값) | 20:40 (동일) |
| 토글 ON/OFF 동작 | `scheduler_market_close_on` 토글 | `scheduler_market_close_on` 토글 (동일) |
| UI 입력칸 위치 | 시간 설정 탭 "1일봉차트 자동다운로드" 섹션 | 동일 (변경 없음) |
| UI 입력칸 동작 | 시간 슬롯 + 토글 | 동일 (변경 없음) |
| 저장 동작 | 자동 저장 + 토스트 | 동일 (변경 없음) |
| 순서 검증 에러 | 422 → 토스트 메시지 | 동일 (검증 조건만 2그룹 분리, 에러 표시 패턴 동일) |

> 사용자가 체감하는 변화는 없음. 내부 타이머 통합 + 키 네임스페이스 일원화만 수행.

---

## 11. 참조 규칙

- AGENTS.md 섹션3 규칙 0 (승인 전 수정 금지)
- AGENTS.md 섹션3 규칙 0-1 (세션당 1단계)
- AGENTS.md 섹션3 규칙 0-2 (수정 전 사전조사)
- AGENTS.md 섹션3 규칙 0-3 (사용자 승인 없는 롤백 금지) — DB 마이그레이션 실패 시 복원은 사용자 승인 후 진행
- AGENTS.md 섹션4 "다단계 작업 워크플로우" (설계→태스크→구현 3세션)
- AGENTS.md 섹션4 규칙 11 (계획서 삭제) — 5세션에서 설계서 + 태스크 파일 삭제
- Safety Rules 2 (DB 스키마 변경 전 백업) — db-backup 스킬 선행
- P10/P14/P16/P20/P21/P22/P23/P24 (아키텍처 불변 원칙)
