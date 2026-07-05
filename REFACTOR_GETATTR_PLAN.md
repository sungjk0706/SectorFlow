# `__getattr__` 폴백 제거 및 SSOT 일원화 수정계획서

`engine_service.__getattr__` 및 `engine_state.__getattr__` 동적 속성 위임(PEP 562)을 제거하고, 16개 파일 148건의 `_{alias}._xxx` 접근 패턴을 직접 `state.xxx` 또는 직접 임포트로 일원화하는 작업.

---

## 수정 대상 분류 (3가지 카테고리)

### A. 런타임 AttributeError 위험 (7건, 6개 함수)

`es._xxx`로 호출하나 `engine_service` 모듈에도 없고 `state`에도 없는 함수들.

| 함수 | 실제 정의 | 접근 파일 | 라인 |
|------|----------|----------|------|
| `_ws_send_reg_unreg_and_wait_ack` | engine_ws.py:23 | market_close_pipeline.py:159 | |
| `_ws_send_remove_fire_and_forget` | engine_ws.py:64 | market_close_pipeline.py:162 | |
| `_cleanup_stale_ws_subscriptions_on_session_ready` | engine_ws.py:244 | engine_bootstrap.py:138 | |
| `_run_sector_reg_pipeline` | engine_ws.py:224 | engine_bootstrap.py:181,197 | |
| `_ensure_ws_subscriptions_for_positions` | engine_ws.py:199 | engine_bootstrap.py:182 | |
| `_apply_real01_volume_amount_to_radar_rows` | engine_radar.py:96 | pipeline_compute.py:455 | |

**수정 방식**: 각 호출처에서 `engine_ws` / `engine_radar` 모듈을 직접 임포트하여 함수 호출.

### B. SSOT 위반: 이중 정의 변수 (3종, 22건)

`engine_service.py` 모듈 변수와 `engine_state.py` state 속성이 같은 이름으로 이중 정의.

| 모듈 변수 (engine_service.py) | state 속성 (engine_state.py) | 접근 건수 |
|-------------------------------|------------------------------|----------|
| `_confirmed_refresh_running_confirmed` (line 67) | `state.confirmed_refresh_running_confirmed` (line 67) | 3건 |
| `_confirmed_refresh_running_5d` (line 68) | `state.confirmed_refresh_running_5d` (line 68) | 5건 |
| `_confirmed_refresh_message` (line 69) | `state.confirmed_refresh_message` (line 69) | 5건 |

**수정 방식**: `engine_service.py`에서 모듈 변수 3개 삭제. 모든 접근처를 `state.confirmed_refresh_running_confirmed` 등으로 변경.

### C. 정상 `__getattr__` 경유 속성 → `state.xxx` 직접 접근 (105건)

`__getattr__`가 정상 작동하지만 원칙 20(폴백 금지)에 따라 직접 `state.xxx`로 변경.

#### C1. `es._xxx` / `_es._xxx` → `es.state.xxx` (52건)

| 속성 | 파일 | 건수 |
|------|------|------|
| `_master_stocks_cache` | market_close_pipeline.py, settings.py, stock_classification_data.py, sector_mapping.py | 20 |
| `_integrated_system_settings_cache` | market_close_pipeline.py, settings.py, pipeline_compute.py, sector_data_provider.py | 17 |
| `_sector_summary_ready_event` | sector_data_provider.py, engine_sector_confirm.py | 3 |
| `_auto_trade` | settings.py, trading.py | 8 |
| `_snapshot_history` | settings.py | 1 |
| `_checked_stocks` | settings.py | 1 |
| `_confirmed_refresh_running` | stock_classification.py (getattr) | 1 |
| `_sector_summary_cache` | sector_data_provider.py, engine_sector_confirm.py, daily_time_scheduler.py, engine_bootstrap.py, engine_snapshot.py, settings.py | 12 |

**참고**: `_sector_summary_cache`는 `state`에 존재하지 않음. 별도 처리 필요 (항목 D 참조).

#### C2. `_st._xxx` / `engine_state._xxx` / `_es_state._xxx` → `state.xxx` (53건)

| 속성 | 파일 | 건수 |
|------|------|------|
| `_integrated_system_settings_cache` | engine_bootstrap.py, settlement_engine.py, data_manager.py, engine_ws_dispatch.py | 14 |
| `_master_stocks_cache` | market_close_pipeline.py, engine_ws_dispatch.py | 17 |
| `_broker_tokens` | market_close_pipeline.py | 6 |
| `_positions` | engine_bootstrap.py | 5 |
| `_sector_summary_ready_event` | engine_bootstrap.py | 2 |
| `_ws_reg_pipeline_done` | engine_bootstrap.py | 2 |
| `_account_rest_bootstrapped` | engine_bootstrap.py | 2 |
| `_REG_REAL_DEBUG_EXTRA_LOG` | engine_ws_dispatch.py | 2 |
| `_auto_trade` | engine_ws_dispatch.py | 2 |
| `_access_token` | engine_ws_dispatch.py | 1 |

### D. `_sector_summary_cache` SSOT 문제 (별도 처리)

`_sector_summary_cache`는 `engine_service.py:64`에만 모듈 변수로 존재. `state`에 정의되지 않음.
- 접근 12건: 모두 `engine_service._sector_summary_cache` 모듈 변수 직접 접근 (`__getattr__` 미경유)
- **수정 방식**: `engine_state.py`의 `EngineState.__init__`에 `self.sector_summary_cache: SectorSummary | None = None` 추가. `engine_service.py:64` 모듈 변수 삭제. 모든 접근을 `state.sector_summary_cache`로 변경.

### E. 모듈 직접 접근 함수 (7건, 정상 작동)

`engine_service.py`에 임포트되어 있어 `__getattr__` 없이 직접 접근되는 함수들.

| 함수 | 접근 파일 | 건수 |
|------|----------|------|
| `_refresh_account_snapshot_meta` | settlement_engine.py, settings.py, trading.py | 3 |
| `_broadcast_account` | settlement_engine.py, settings.py, trading.py | 4 |
| `_broadcast_buy_limit_status` | settings.py | 1 |

**수정 방식**: `engine_service.py` 파사드 임포트 유지 또는 각 파일에서 `engine_account` 직접 임포트. 파사드 패턴이므로 유지 허용.

### F. `engine_state` 모듈 함수 직접 접근 (4건, 정상 작동)

| 함수 | 접근 파일 | 건수 |
|------|----------|------|
| `_notify_reg_ack` | engine_ws_dispatch.py | 2 |
| `_get_account_rest_lock` | engine_account.py | 1 |
| `_set_realtime_state` | engine_snapshot.py | 1 |

**수정 방식**: `engine_state.py` 모듈 수준 헬퍼 함수이므로 유지. `__getattr__` 미경유.

### G. `es.state._last_global_buy_ts` (1건)

`settings.py:136` — `es.state._last_global_buy_ts = 0.0`. `state`의 `_last_global_buy_ts` 속성은 `engine_state.py:77`에 정의됨. 언더스코어가 붙어 있으나 `state` 직접 접근이므로 `__getattr__` 미경유. 그러나 속성명에서 언더스코어 제거 권장.

---

## 수정 단계 (순서 중요)

### 0단계: 사전 준비
- `git commit`으로 현재 상태 백업
- `pytest --timeout=30`으로 기본 테스트 통과 확인

### 1단계: `_sector_summary_cache`를 `state`로 이관 (D)
- `engine_state.py`: `EngineState.__init__`에 `self.sector_summary_cache: SectorSummary | None = None` 추가
- `engine_service.py:64`: `_sector_summary_cache` 모듈 변수 삭제
- 6개 파일 12건의 `_es._sector_summary_cache` → `state.sector_summary_cache` 변경
  - sector_data_provider.py (1건)
  - engine_sector_confirm.py (4건)
  - daily_time_scheduler.py (2건)
  - engine_bootstrap.py (1건)
  - engine_snapshot.py (1건)
  - settings.py (2건)
  - sector_data_provider.py:216 `_es_ref._sector_summary_cache` → `state.sector_summary_cache`
- **검증**: `grep -r "_sector_summary_cache" backend/`로 잔여 확인, `pytest`

### 2단계: SSOT 위반 변수 제거 (B)
- `engine_service.py:67-69`: 모듈 변수 3개 삭제
- `market_close_pipeline.py`: 12건 `es._confirmed_refresh_running_*` → `state.confirmed_refresh_running_*`
- `stock_classification.py`: 1건 `engine_service._confirmed_refresh_running_5d` → `state.confirmed_refresh_running_5d`
- **검증**: `grep -r "_confirmed_refresh_running" backend/`로 잔여 확인, `pytest`

### 3단계: 런타임 AttributeError 함수 수정 (A)
- `market_close_pipeline.py`: `from backend.app.services.engine_ws import _ws_send_reg_unreg_and_wait_ack, _ws_send_remove_fire_and_forget` 추가, `es._ws_send_*` → 직접 호출
- `engine_bootstrap.py`: `from backend.app.services.engine_ws import _cleanup_stale_ws_subscriptions_on_session_ready, _run_sector_reg_pipeline, _ensure_ws_subscriptions_for_positions` 추가, `es._xxx` → 직접 호출
- `pipeline_compute.py`: `from backend.app.services.engine_radar import _apply_real01_volume_amount_to_radar_rows` 추가, `es._apply_real01_*` → 직접 호출
- **검증**: `grep -r "es\._ws_send\|es\._cleanup_stale\|es\._run_sector_reg\|es\._ensure_ws\|es\._apply_real01" backend/`로 잔여 확인, `pytest`

### 4단계: `es._xxx` 속성 → `state.xxx` 변경 (C1)
- 파일별 순차 수정 (각 파일 수정 후 grep 검증):
  1. market_close_pipeline.py (19건: `_master_stocks_cache` 12, `_integrated_system_settings_cache` 7)
  2. settings.py (12건: `_master_stocks_cache` 3, `_integrated_system_settings_cache` 2, `_snapshot_history` 1, `_checked_stocks` 1, `_auto_trade` 5)
  3. stock_classification_data.py (3건)
  4. sector_mapping.py (2건)
  5. trading.py (3건: `_auto_trade`)
  6. pipeline_compute.py (1건: `_integrated_system_settings_cache`)
  7. sector_data_provider.py (10건: `_integrated_system_settings_cache` 7, `_sector_summary_ready_event` 2, `_sector_summary_cache` 1 — 1단계에서 처리)
  8. engine_sector_confirm.py (5건: `_sector_summary_cache` 4 — 1단계에서 처리, `_sector_summary_ready_event` 1)
  9. stock_classification.py (2건: `_confirmed_refresh_running` 1 — 2단계에서 처리, `_integrated_system_settings_cache` 1)
- **검증**: 각 파일별 `grep "es\._\|_es\._\|engine_service\._"`로 잔여 확인

### 5단계: `_st._xxx` / `engine_state._xxx` / `_es_state._xxx` → `state.xxx` 변경 (C2)
- 파일별 순차 수정:
  1. engine_bootstrap.py (21건)
  2. market_close_pipeline.py (18건: `_st._master_stocks_cache` 12, `_es_state._broker_tokens` 6)
  3. engine_ws_dispatch.py (13건)
  4. settlement_engine.py (1건)
  5. data_manager.py (1건)
- **검증**: `grep "_st\._\|engine_state\._\|_es_state\._" backend/`로 잔여 확인

### 6단계: `engine_state.__getattr__` 및 `engine_service.__getattr__` 제거
- `engine_state.py:156-162`: `__getattr__` 함수 삭제
- `engine_service.py:303-309`: `__getattr__` 함수 삭제
- **검증**: `python -c "import backend.app.services.engine_service"` import 테스트, `pytest`

### 7단계: 파사드 임포트 함수 정리 (E, 선택적)
- `_refresh_account_snapshot_meta`, `_broadcast_account`, `_broadcast_buy_limit_status` — 파사드 유지 또는 직접 임포트
- 사용자 승인 후 진행

### 8단계: 최종 검증
- `grep -r "es\._\|_es\._\|_st\._\|engine_state\._\|engine_service\._\|_es_state\._" backend/ --include="*.py"`로 전체 잔여 확인
- `pytest --timeout=30` 전체 테스트
- 앱 기동 테스트 (`SectorFlow.command`)

---

## 수정 순서 원칙

1. **사용처 먼저, 정의처 나중**: 모듈 변수/함수를 삭제하기 전에 모든 사용처를 먼저 변경
2. **파일 하나씩**: 한 번에 하나의 파일만 수정, 수정 후 즉시 grep 검증
3. **단계별 커밋**: 각 단계 완료 후 `git commit`
4. **1~2단계를 먼저**: `_sector_summary_cache` 이관과 SSOT 위반 변수 제거는 독립적이므로 먼저 처리
5. **3단계를 그 다음으로**: AttributeError 위험 함수는 긴급도가 높음
6. **4~5단계는 건수가 많음**: 파일별로 나누어 진행, 중간에 pytest로 회귀 확인
7. **6단계는 마지막**: 모든 사용처를 변경한 후에 `__getattr__` 제거

---

## 예상 영향 범위

- 수정 파일 수: 16개
- 수정 건수: ~148건 (중복 제거 후 실제 편집은 ~100건 내외)
- 위험도: 중간 (상태 변수 접근 경로 변경, 런타임 동작 변화 없음)
- 롤백: 각 단계별 `git commit` 기준으로 개별 롤백 가능
