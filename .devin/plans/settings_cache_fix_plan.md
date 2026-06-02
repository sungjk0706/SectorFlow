# 설정 캐시 아키텍처 수정계획서 (실행 가능 완성본)

캐시 A(설정 DB 미러)와 캐시 B(엔진 런타임 통합 상태)의 역할을 분리·문서화하고, 이미 적용된 API 키 버그 수정을 확정하며, 검증 과정에서 발견한 `refresh()`의 `sector_stock_layout` 소실 버그를 근본 해결하는 계획.

> 작성일: 2026-06-02 · 모든 항목 파일:줄번호로 코드 확인됨(추정 없음)
> 정본 위치: 프로젝트 `.windsurf/plans/settings_cache_fix_plan.md`에도 동기화 예정

---

## 0. 캐시 구조 (검증됨)

| 캐시 | 위치 | 담는 것 | 갱신 경로 |
|---|---|---|---|
| 캐시 A | `settings_file.py:115` | DB 설정 복호화 미러 (RAW 필드명) | Cache-Aside (load 시 채움, save 시 무효화) |
| 캐시 B | `engine_state.py:89` | 가공설정(RAW+PROCESSED) + 런타임 전용 상태(`sector_stock_layout`) | `refresh()`(`engine_config.py:54`) + 증분(`settings_store.py:236`) |

- 두 캐시는 다른 데이터를 담는 정상 구조. `.windsurfrules:120` "단일 소스 진리"와 부합.
- 캐시 B는 `engine_state.py:58` 주석대로 `sector_stock_layout`(DB에 없는 런타임 상태)을 통합 보유.

---

## 1. 완료된 수정 (API 키 버그) — 검증됨, 변경 불필요

### 근본 원인
`save_settings()`가 DB 커밋 후 캐시 A를 무효화하지 않아, 핫-리로드 시 stale 캐시 A가 빈 키 반환 → `[경고] 주입할 유효한 API Key 또는 Secret이 존재하지 않습니다.`

### 적용된 수정 (`settings_file.py`)
- `:6` `import asyncio` 복원
- `:107-111` `_ENCRYPT_FIELDS` 단일 상수
- `:115-116` 캐시 A + `_cache_lock` (모듈 소유, Cache-Aside)
- `:119-198` `load_integrated_system_settings()` — 락 내부 캐시 확인 → DB 로드 → 캐시 저장
- `:238-241` `save_settings()` 재암호화 (캐시 A가 복호화값 보유 → DB 암호화 저장 위해 필수)
- `:286-289` `save_settings()` 커밋 직후 `_integrated_system_settings_cache = None` (무효화 — 핵심 수정)
- `:292-297` `update_settings()` — engine_state 의존 제거

### 흐름 검증 (단계 추적 완료)
PATCH → `apply_settings_updates`(`settings_store.py:142`) → `save_settings` 커밋 + 캐시 A 무효화 → 캐시 B 증분(`settings_store.py:236`) → `update_broker_credentials_live`(`engine_lifecycle.py:344`) → `load()` 재조회 → fresh 키 → 경고 미발생.

---

## 2. 검증 결과: 안전 확인 (조치 불필요)

### 2-1. PROCESSED 전용 키 startup 안전성
- `buy_amount`/`max_stock_count`/`loss_cut_*` 등 PROCESSED 이름: 설정 캐시에서 **읽는 곳 없음**(엔진은 RAW 이름 `buy_amt`/`max_stock_cnt`만 사용 — `engine_lifecycle.py:219,228`). → 무관.
- `broker_config`(PROCESSED 전용, `engine_settings.py:187` 생성, DB엔 없음): 기동 시 읽히나 **전 지점 폴백 존재**:
  - `engine_loop.py:226` `or broker_nm`
  - `broker_router.py:77` `or default_broker`
  - `connector_manager.py:40` `or ...get("broker","kiwoom")`
  - `engine_snapshot.py:94` 기본 `{}`
- 결론: 첫 refresh 이전에도 폴백으로 정상 동작. **P1 불필요**.

---

## 3. 발견된 실제 버그: refresh()가 sector_stock_layout 소실 (P0)

### 사실 (코드 확인)
- `refresh_engine_integrated_system_settings_cache`(`engine_config.py:81-82`):
  ```python
  _integrated_system_settings_cache.clear()      # sector_stock_layout 포함 전체 삭제
  _integrated_system_settings_cache.update(fresh) # fresh=build 결과 (layout 없음)
  ```
- `build_engine_settings_dict`(`engine_settings.py:48-193`)는 `sector_stock_layout`을 **포함하지 않음**(전수 확인).
- `sector_stock_layout`은 캐시 B에만 존재하는 런타임 상태이며 DB에도 없음 → refresh 후 **복원 불가**.

### 영향
- `sector_stock_layout` 읽기 지점이 빈 값이 됨:
  - `engine_sector.py:360` `_compute_filtered_codes` (매수 대상 선정 핵심) → 빈 코드셋
  - `engine_bootstrap.py:418` 워치리스트 구성
  - `market_close_pipeline.py:101` KRX 단독 종목 병합
- refresh 트리거(장중 발생): 설정 저장(`after_settings_persisted`), 텔레그램 토글(`telegram_bot.py:312`), 자동매매 시간 전환(`daily_time_scheduler.py:919`).
- 즉 장중 설정 저장/시간 전환 시 layout이 사라져 매수 로직이 일시 마비됨.

### 런타임 전용 키 범위 (검증됨)
- 캐시 B 쓰기 11곳 중 build 결과에 없는 키는 **`sector_stock_layout` 하나뿐**.
- 나머지(`time_scheduler_on`/`auto_buy_on`/`auto_sell_on`/`ws_subscribe_on`)는 build 결과 포함(`engine_settings.py:53,55,56,163`)이라 refresh가 정상 복원.

### 근본 해결안
`refresh()`가 clear/update 시 런타임 전용 키를 보존하도록 수정.

수정 대상: `backend/app/services/engine_config.py:80-82`
```python
fresh = await get_engine_settings(load_user if load_user else None)
# 런타임 전용 상태 보존 (build 결과에 없는 키)
_RUNTIME_ONLY_KEYS = ("sector_stock_layout",)
preserved = {
    k: _integrated_system_settings_cache.get(k)
    for k in _RUNTIME_ONLY_KEYS
    if k in _integrated_system_settings_cache
}
_integrated_system_settings_cache.clear()
_integrated_system_settings_cache.update(fresh)
_integrated_system_settings_cache.update(preserved)
```
- 영향 파일: `engine_config.py` 1개.
- `_RUNTIME_ONLY_KEYS`는 주석으로 "build_engine_settings_dict 결과에 없는 캐시 B 전용 런타임 상태"임을 명시.

---

## 4. 작업 항목 (우선순위)

### [P0] refresh() 런타임 키 보존 — 위 3번 근본 해결안 적용
- 파일: `engine_config.py:80-82`
- 착수 전: `git add -A && git commit` (롤백 지점 — 현재 미커밋 상태이므로 필수)

### [P3] 문서화 (코드 동작 변경 없음)
- `settings_file.py:115` 캐시 A 선언부 주석: "DB 설정 복호화 미러(RAW). Cache-Aside. save 시 무효화."
- `engine_state.py:89` 캐시 B 선언부 주석: "엔진 런타임 통합 상태(가공설정+sector_stock_layout). refresh()로 갱신, 런타임 키는 보존."

> P1/P2는 검증 결과 불필요로 종결(2-1 참조 및 직접 쓰기 무해 확인).

---

## 5. 절대 금지 (재발 방지)

- 캐시 B 제거 — 35파일 303곳 사용 + 런타임 상태 보유, 불가
- `settings_file.py` → `engine_state` import (역방향 의존)
- 캐시 A에 PROCESSED/런타임 값 저장
- `sector_stock_layout`을 DB/캐시 A로 이동
- 승인 없는 코드 변경 · 추측 표현(`.windsurfrules:227-235`)

---

## 6. 의존 방향

```
허용:  engine_* → settings_store → settings_file → DB
금지:  settings_file → engine_state
```

---

## 7. 검증 절차 (P0 적용 후 필수)

1. `./.venv/bin/python -m py_compile backend/app/services/engine_config.py`
2. 앱 기동: `/Users/sungjk0706/Desktop/SectorFlow/SectorFlow.command`
3. layout 보존 확인:
   - 엔진 가동 → 업종순위 종목 표시 확인
   - 일반설정에서 임의 값 저장(refresh 트리거)
   - `_compute_filtered_codes` 로그(`engine_sector.py:365` `[DEBUG-FILTER] sector_stock_layout len`)가 **0이 아닌 값 유지** 확인
4. API 키 시나리오(회귀): `kiwoom_app_key`/`secret` 저장 → `[경고] 주입할 유효한 API Key...` 미발생
5. 앱 재시작 후 저장값 보존 확인

---

## 부록. 핵심 위치 (검증됨)

| 항목 | 파일:줄 | 역할 |
|---|---|---|
| 캐시 A | `settings_file.py:115` | DB 설정 복호화 미러(RAW) |
| `load_integrated_system_settings()` | `settings_file.py:119` | 캐시 A 읽기(Cache-Aside, 락 내부) |
| `save_settings()` | `settings_file.py:228` | DB 저장 + 재암호화 + 캐시 A 무효화 |
| `apply_settings_updates()` | `settings_store.py:142` | PATCH + 암호화 + 캐시 B 증분 |
| `load_..._for_editing()` | `settings_store.py:279` | 복호화 편집용 |
| 캐시 B | `engine_state.py:89` | 엔진 런타임 통합 상태 |
| `refresh_engine_..._cache()` | `engine_config.py:54` | 캐시 B 정식 갱신 (**P0 수정 대상**) |
| `build_engine_settings_dict()` | `engine_settings.py:23` | RAW→(RAW+PROCESSED) 가공 (layout 미포함) |
| `_compute_filtered_codes()` | `engine_sector.py:340` | layout 기반 매수 대상 선정 |
| `update_broker_credentials_live()` | `engine_lifecycle.py:344` | 무중단 자격증명 핫-리로드 |
</CodeContent>
<parameter name="EmptyFile">false
