# 설정 키 영향 매트릭스

> 작성일: 2026-07-26
> 세션: COUPLING-S2 (C-02)
> 기준 파일: `backend/app/core/settings_defaults.py`, `backend/app/core/settings_file.py`, `backend/app/core/settings_store.py`, `backend/app/core/engine_settings.py`, `backend/app/services/engine_config.py`, `backend/app/services/engine_state.py`
> 원칙: P10 SSOT, P20 폴백 금지, P21 사용자 투명성, P22 데이터 정합성, P23 일관성, P24 단순성
> 상태: 조사 전수 완료 + COUPLING-S2 후속 수정 완료 (2026-07-27 — #3~#6/#2 5건 처리) + COUPLING-S2 잔여 3건 완료 (2026-07-27 — #1/#2/#5 단일화 우선순위 항목)

---

## 1. 목적과 범위

각 설정 키가 **DB 원본 → 정규화 → 메모리 캐시 → 서비스 소비자 → API 응답 → UI 표시**까지 거치는 변환·소비 경로를 실제 코드 참조로 확정한다. 본 세션은 매트릭스 작성까지만 수행하며, 특정 키의 읽기 경계 좁히기는 후속 세션에서 위험도가 높은 1개 키만 별도 승인 후 진행한다.

### 조사 범위 (실제 코드 기준)

- 기본값 SSOT: `settings_defaults.py` `DEFAULT_USER_SETTINGS`(66키) · `DEFAULT_SYSTEM_CONFIG`(17키)
- DB I/O: `settings_file.py` `load_integrated_system_settings()` / `load_selected_settings()` / `save_settings()` / `save_selected_settings()` + 마이그레이션 11개 + 암호화/복호화
- 저장 검증·증분저장: `settings_store.py` `apply_settings_updates()` + 타임테이블 순서 검증 + 리스크/구독 한도 수치 검증 + 민감값 마스킹(`build_masked_settings_dict`)
- 정규화: `engine_settings.py` `build_engine_settings_dict()` → 9개 `_build_*` 그룹 함수 + `_pick_broker_credentials()` + `_decrypt_field()`
- 메모리 캐시: `engine_state.state.integrated_system_settings_cache: dict` (line 184, 초기값 `{}`)
- 캐시 갱신·조회: `engine_config.py` `refresh_engine_integrated_system_settings_cache()` / `get_settings_snapshot()` / `_sync_nws_settings_to_state()` / `_mask_sensitive_settings()` / `TRADE_MODE_KEYS`
- 변경 후처리 디스패처: `engine_service.py` `apply_settings_change()` + 7개 `_apply_*` 그룹 헬퍼 + 2개 조기 종료 헬퍼(`_handle_broker_change`, `_handle_trade_mode_change`)
- API 라우트: `web/routes/settings.py` `GET /api/settings` · `PATCH /api/settings/{field_name}`
- 엔진 소비자: `engine_state` import 38개 파일(세션 COUPLING-S1 전수) 중 `integrated_system_settings_cache` 직접 참조 28개 파일
- 프론트엔드 타입 SSOT: `frontend/src/types/index.ts` `AppSettings`(line 98)
- 프론트엔드 매니저: `frontend/src/settings.ts` `SettingsManager` + `MASKED_FIELDS` + `extractDirty()`
- 프론트엔드 API 클라: `frontend/src/api/client.ts` `getSettings()` / `patchSettingField()`
- WS 설정 변경: `frontend/src/binding.ts` `settings-changed` 이벤트 → `uiStore.applySettingsChanged()`
- UI 페이지: `general-settings-*-tab.ts` 7개 탭 + `buy-settings.ts` + `sell-settings.ts` + `sector-settings.ts`

### 조사 방법

- `integrated_system_settings_cache.get("키")` / `integrated_system_settings_cache["키"]` 두 패턴으로 backend/app 전수 grep
- `DEFAULT_USER_SETTINGS` 키 정의와 `build_engine_settings_dict()` `_build_*` 그룹 매핑을 1:1 대조
- API 라우트의 GET/PATCH 응답 경로와 `apply_settings_change()` 디스패처 분기 순서 추적
- 프론트엔드 `saveSection()` 호출부를 각 탭별로 grep하여 UI→PATCH 키 전수 추출
- 테스트 파일 3개(`test_settings_store.py` 13 클래스, `test_settings_file_integration.py` 6 클래스, `test_settings_boost_order_ratio.py`) 구조 확인

### 파이프라인 6단계 정의 (본 매트릭스의 열 기준)

| 단계 | 위치 | 비고 |
|------|------|------|
| **1. DB 원본** | `integrated_system_settings` 테이블 (key, value, value_type) | `value_type ∈ {boolean, number, json, string}` |
| **2. 기본값 보충** | `settings_defaults.DEFAULT_USER_SETTINGS` / `DEFAULT_SYSTEM_CONFIG` | DB 누락 시 채움 (P10 SSOT) |
| **3. 정규화** | `engine_settings.build_engine_settings_dict()` 9개 `_build_*` 그룹 | 타입 캐스팅 + 복호화 + 키 rename + 파생 필드 생성 |
| **4. 메모리 캐시** | `engine_state.state.integrated_system_settings_cache` | `.clear() + .update(normalized)` 갱신 |
| **5. 서비스 소비자** | `engine_config`, `engine_service`, `trading`, `buy_order_executor`, `engine_loop`, `engine_cache`, `engine_snapshot`, `daily_time_scheduler`, `market_close_pipeline`, `engine_sector_confirm`, `sector_data_provider`, `connector_manager`, `broker_router`, `kiwoom_connector`, `ls_connector`, `kiwoom_providers`, `ls_providers`, `telegram_bot`, `trade_history`, `engine_account_notify`, `engine_ws_reg`, `engine_strategy_core`, `engine_lifecycle`, `engine_ws`, `engine_ws_dispatch`, `ws_subscribe_control`, `engine_bootstrap`, `pipeline_compute`, `pipeline_compute_tick_handlers`, `settlement_engine`, `engine_account` | `cache["키"]` 직접 read 또는 `cache.get("키", 기본)` read |
| **6. API 응답** | `GET /api/settings` `build_masked_settings_dict()` + `PATCH /api/settings/{field}` `apply_settings_updates()` → `apply_settings_change()` 디스패처 | 마스킹/검증/후처리 |
| **7. UI 표시·저장** | `AppSettings` 타입 + 7개 설정 탭 + WS `settings-changed` 이벤트 | `saveSection({키:값})` → PATCH |

---

## 2. 파이프라인 전체 흐름

### 2.1 기동 시 (읽기 경로)

```
app.py lifespan
  → load_integrated_system_settings()  [settings_file.py]
      → _load_db_settings()            [DB SELECT *]
      → DEFAULT_USER_SETTINGS / DEFAULT_SYSTEM_CONFIG 보충
      → _apply_all_migrations() (11개, 1회만)
      → _decrypt_encrypt_fields()      [암호화 필드 복호화]
      → return flat dict
  → build_engine_settings_dict(flat)   [engine_settings.py]
      → 9개 _build_* 그룹 + _pick_broker_credentials()
      → 타입 캐스팅 + 키 rename + 파생 필드(_credential_states, broker_config 등)
      → return normalized dict
  → state.integrated_system_settings_cache.clear() + .update(normalized)
  → _sync_nws_settings_to_state(normalized)
      → news_keywords_cache / news_boost_score / news_boost_ttl_sec 별도 state 속성 동기화 (P13)
```

### 2.2 저장 시 (PATCH 경로)

```
PATCH /api/settings/{field_name} {value}
  → apply_settings_updates({field_name: value})  [settings_store.py]
      → _compute_select_keys()                   [타임테이블 그룹 키 확장]
      → load_selected_settings()                 [DB 증분 로드 + 복호화]
      → _prepare_save_payload()                  [None/빈문자열 무시, broker 허용값, 시간 형식, 암호화]
      → _validate_timetable_order()              [2그룹 순서 검증]
      → _validate_numeric_fields()               [구독 한도 + 리스크 + 뉴스 + 일별 요약 범위]
      → save_selected_settings(to_save)          [DB INSERT OR REPLACE]
      → journal.record_settings_change()         [저널링]
      → return changed_keys: set[str]
  → if 엔진 실행 중:
      → apply_settings_change(changed_keys)      [engine_service.py 디스패처]
          → refresh_engine_integrated_system_settings_cache()  [캐시 전체 재구성]
          → _handle_broker_change() (조기 종료) 또는
          → _handle_trade_mode_change() (조기 종료) 또는
          → notify_desktop_settings_toggled(changed_dict)      [WS 브로드캐스트]
          → _apply_virtual_balance_change / _apply_5d_download_toggle /
             _apply_time_schedule_change / _apply_timetable_change /
             _apply_sector_ui_change / _apply_telegram_toggle
          → invalidate_buy_snapshot()
  → else (엔진 미실행):
      → save_pending_settings(changed_keys)      [sector_stock_cache.py]
      → refresh_engine_integrated_system_settings_cache()
      → notify_desktop_settings_toggled(changed_dict)
      → tele_on인 경우 telegram_bot start/stop
```

### 2.3 읽기 시 (GET 경로 — UI 표시)

```
GET /api/settings
  → build_masked_settings_dict()  [settings_store.py]
      → load_integrated_system_settings()   [DB 로드 + 마이그레이션 + 복호화]
      → classify_secret_fields()             [_ENCRYPT_FIELDS 상태 분류]
      → 민감필드 → "***" 치환
      → auto_trading_effective / encryption_key_state / secret_field_states 추가
      → return masked dict
  → 프론트 AppSettings 타입으로 수신 → uiStore.settings 저장
```

> **주의**: GET은 `load_integrated_system_settings()`(DB 직접 로드)를 사용하고, PATCH 후처리와 엔진 소비는 `state.integrated_system_settings_cache`(메모리)를 사용. 두 경로는 `refresh_engine_integrated_system_settings_cache()`가 갱신 시 동기화하므로 P10 SSOT 유지. 단 GET은 매 요청마다 DB를 읽으므로 캐시와 일시적 불일치 가능 (저장 직후 GET 시 캐시 갱신 완료 전이면 마스킹 dict에 이전 값 노출 가능성 — 후속 검토 대상).

---

## 3. 설정 키 그룹별 매트릭스

> 각 키의 열: **기본값(SSOT) | DB 타입 | 정규화 변환 | 캐시 read 경로 | 캐시 write 경로 | PATCH 후처리 | UI 소비자**
> 캐시 read는 `cache["키"]`(직접, KeyMissing 위험) 또는 `cache.get("키", 기본)`(안전)로 구분 표기.
> `[rename]` = 정규화 단계에서 키 이름이 바뀜. `[derive]` = 정규화 단계에서 파생 생성된 키(원본 DB에 없음).

### 3.1 자동매매 토글·시간 (8키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | 캐시 write | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|------------|--------------|-----|
| `time_scheduler_on` | `False` | boolean | `bool()` | `trading.py:437,646` (write=False 강제) | `trading.py` 2곳 | `_apply_time_schedule_change` | auto-trade-tab master toggle |
| `auto_buy_on` | `False` | boolean | `bool()` | `engine_account.py` (auto_buy_effective) | refresh 전체 | `_apply_time_schedule_change` | time-settings-tab |
| `auto_sell_on` | `False` | boolean | `bool()` | `engine_account.py` (auto_sell_effective) | refresh 전체 | `_apply_time_schedule_change` | time-settings-tab |
| `buy_time_start` | `"09:00"` | string | `str()[:5]` | `daily_time_scheduler.py` (타이머 예약) | refresh 전체 | `_apply_time_schedule_change` | time-settings-tab |
| `buy_time_end` | `"15:20"` | string | `str()[:5]` | `daily_time_scheduler.py` | refresh 전체 | `_apply_time_schedule_change` | time-settings-tab |
| `sell_time_start` | `"09:00"` | string | `str()[:5]` | `daily_time_scheduler.py` | refresh 전체 | `_apply_time_schedule_change` | time-settings-tab |
| `sell_time_end` | `"15:20"` | string | `str()[:5]` | `daily_time_scheduler.py` | refresh 전체 | `_apply_time_schedule_change` | time-settings-tab |
| `[derive] auto_buy_effective` | — | — | `auto_buy_effective(d)` | `engine_config.get_settings_snapshot()` | — | `notify_desktop_header_refresh` | 헤더 칩 |

> `time_scheduler_on`은 `trading.py`에서 리스크/일일한도 초과 시 `cache["time_scheduler_on"] = False`로 직접 write (거래 관련 산재, COUPLING-S1 "변경 금지" 분류와 동일).

### 3.2 투자모드·증권사·가상잔고 (5키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | 캐시 write | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|------------|--------------|-----|
| `broker` | `"kiwoom"` | string | `str()` (저장 시 `broker_registry` 허용값 검증) | `broker_router.py:67,97`, `daily_time_scheduler.py:1294`, `engine_loop.py:58` | refresh 전체 | `_handle_broker_change` (조기 종료, 엔진 재기동) | api-settings-tab |
| `trade_mode` | `"test"` | string | `effective_trade_mode(merged)` | `engine_cache.py:110`, `engine_config.TRADE_MODE_KEYS` | refresh 전체 | `_handle_trade_mode_change` (조기 종료, 계좌 구독 전환) | account-tab |
| `test_virtual_deposit` | `10000000` | number | `int()` | `engine_cache.py:112` | refresh 전체 | `_apply_virtual_balance_change` (Settlement Engine reset) | account-tab |
| `test_virtual_balance` | `10000000` | number | `int()` | `engine_service.py:139` (settlement reset) | refresh 전체 | `_apply_virtual_balance_change` | account-tab |
| `confirmed_data_broker` | `""` | string | `str().strip()` | `engine_loop.py:65` | refresh 전체 | (디스패처 미처리 — 변경 시 엔진 재기동 필요?) | (UI 노출 없음) |

> `confirmed_data_broker`는 PATCH 후처리 디스패처에 분기가 없음. 빈 문자열이 아니면 `engine_loop`가 해당 증권사로 확정 시세 다운로드. 변경 시 재기동 없이는 적용 안 됨 (P21 투명성 후속 검토 대상 — 사용자가 변경해도 안내 없음).

### 3.3 매수 설정 (12키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `max_daily_total_buy_on` | `False` | boolean | `bool()` | `engine_strategy_core.py:39`, `buy_order_executor.py:114` | (일반 브로드캐스트) | buy-settings |
| `max_daily_total_buy_amt` | `0` | number | `int()` | `engine_strategy_core.py:40`, `buy_order_executor.py:113` | (일반) | buy-settings |
| `max_stock_cnt_on` | `True` | boolean | `bool(flat.get(...)) if in flat else ...` (마이그레이션 추론) | `buy_order_executor.py:99` | (일반) | buy-settings |
| `max_stock_cnt` | `5` | number | `int()` | `buy_order_executor.py:98` | (일반) | buy-settings |
| `buy_amt_on` | `True` | boolean | 마이그레이션 추론 | `buy_order_executor.py:109` | (일반) | buy-settings |
| `buy_amt` | `1000000` | number | `int()` | `buy_order_executor.py:108` | (일반) | buy-settings |
| `rebuy_block_on` | `True` | boolean | `bool()` | `buy_order_executor.py:39` | `_apply_sector_ui_change` (buy_targets 재분류) | buy-settings |
| `rebuy_block_period` | `"today"` | string | `str()` | (운영 참조 미발견 — `buy_order_executor` 내부) | (일반) | buy-settings |
| `boost_high_breakout_on` | `False` | boolean | `bool()` | (파이프라인 compute) | `_apply_sector_ui_change` | (buy-settings 또는 별도) |
| `boost_high_breakout_score` | `1.0` | number | `max(float(), 0)` | (파이프라인) | `_apply_sector_ui_change` | buy-settings |
| `boost_order_ratio_on` | `False` | boolean | `bool()` | (파이프라인) | `_apply_sector_ui_change` | buy-settings |
| `boost_order_ratio_pct` | `20` | number | `max(-100, min(100, _raw_pct))` + 레거시 `boost_order_ratio_side` 분기 | (파이프라인) | `_apply_sector_ui_change` | buy-settings |

> `_build_buy_settings`는 `flat`를 추가 인자로 받아 `_on` 키 마이그레이션 추론 분기 수행 (P10 SSOT 예외 — `merged` 직접 접근이 아닌 `flat.get()` 분기). `boost_order_ratio_side`는 레거시 키로 `_build_boost_settings`에서만 참조 (저장 시 제거 마이그레이션은 없음 — 후속 검토).

### 3.4 매수 가산점 — 뉴스 호재 NWS (4키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `boost_news_on` | `False` | boolean | `bool()` | (파이프라인) | `_apply_sector_ui_change` | news-settings-tab |
| `boost_news_score` | `1.0` | number | `max(float(), 0)` | (파이프라인) | `_apply_sector_ui_change` | news-settings-tab |
| `news_boost_ttl_sec` | `300` | number | `int()` | `engine_state.news_boost_ttl_sec` (별도 속성, `_sync_nws_settings_to_state`) | (일반) → `_sync_nws_settings_to_state` | news-settings-tab |
| `news_keywords` | (기본 문자열) | string | `str() or ""` | `engine_state.news_keywords_cache` (별도 속성 — 쉼표 split list) | (일반) → `_sync_nws_settings_to_state` | news-settings-tab |

> NWS 4키는 `engine_settings` 정규화 후 캐시에도 저장되지만, **틱 단계 DB 조회 금지(P13)**를 위해 `_sync_nws_settings_to_state()`가 `engine_state.news_keywords_cache` / `news_boost_score` / `news_boost_ttl_sec` 3개 별도 속성으로 추가 동기화. 즉 NWS 키는 캐시 dict + state 속성 **이중 상주** (P10 SSOT 후속 검토 대상 — 단, 성능 최적화 목적이므로 변경 금지 범주).

### 3.5 리스크 매니저 (9키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `risk_manager_on` | `False` | boolean | `bool()` | `risk_manager.py` | (일반) | auto-trade-tab |
| `daily_loss_limit_on` | `True` | boolean | `bool()` | `risk_manager.py` | (일반) | auto-trade-tab |
| `daily_loss_limit` | `-500000` | number | `int()` | `risk_manager.py` | (일반, 수치 검증 `-1e9~0`) | auto-trade-tab |
| `daily_loss_rate_limit_on` | `False` | boolean | `bool()` | `risk_manager.py` | (일반) | auto-trade-tab |
| `daily_loss_rate_limit` | `-5.0` | number | `float()` | `risk_manager.py` | (일반, 수치 검증 `-100~0`) | auto-trade-tab |
| `risk_block_buy_on` | `True` | boolean | `bool()` | `risk_manager.py` | (일반) | auto-trade-tab |
| `risk_block_sell_on` | `False` | boolean | `bool()` | `risk_manager.py` | (일반) | auto-trade-tab |
| `consecutive_loss_limit_on` | `False` | boolean | `bool()` | `risk_manager.py` | (일반) | auto-trade-tab |
| `consecutive_loss_limit` | `3` | number | `int()` | `risk_manager.py` | (일반, 수치 검증 `1~100`) | auto-trade-tab |

> `max_single_stock_exposure` / `max_position_size` 2키는 3.6에서 별도 표기 (정규화 그룹이 다름).

### 3.6 레거시 리스크 한도 (2키 — _build_risk_settings)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `max_single_stock_exposure` | `20000000` | number | `int()` | `risk_manager.py:37,146` (**살아있는 매수 차단 로직** — 단일 종목 비중 한도) | (일반) | (UI 노출 없음) |
| `max_position_size` | ~~`0`~~ | — | — | — | — | — |
| `max_daily_loss_limit` | ~~`-500000`~~ | — | — | — | — | — |

> **COUPLING-S2 후속 수정 (2026-07-27):**
> - `max_position_size`: 운영 참조 0건 → DEFAULT + DB 마이그레이션 + engine_settings에서 제거 완료.
> - `max_single_stock_exposure`: **매트릭스 원 판정 "dead read" 부정확** — `risk_manager.py:146`에서 살아있는 매수 차단 로직에 사용 중. 제거 금지, SSOT 위반 아님. ARCHITECTURE.md:872 "레거시 호환" 명시 정정 완료.
> - `max_daily_loss_limit`: `daily_loss_limit`과 동일 기준. `risk_manager.py`가 `daily_loss_limit`의 폴백 기본값으로만 사용 → DEFAULT + engine_settings + risk_manager + DB 마이그레이션에서 제거 완료 (safe-trade 절차 적용). `daily_loss_limit`이 SSOT.

### 3.7 매도 설정 (9키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `tp_apply` | `False` | boolean | `bool()` | (매도 실행 경로) | (일반) | sell-settings |
| `tp_val` | `0` | number | `float()` | (매도 실행) | (일반) | sell-settings |
| `loss_apply` | `False` | boolean | `bool()` → `[rename] loss_cut_apply` | (매도 실행, rename 후) | (일반) | sell-settings |
| `loss_val` | `0` | number | `float()` → `[rename] loss_cut_value` + 부호 마이그레이션(양수→음수) | (매도 실행) | (일반, 수치 검증 `-100~0`) | sell-settings |
| `ts_apply` | `False` | boolean | `bool()` → `[rename] trailing_stop_apply` | (매도 실행) | (일반) | sell-settings |
| `ts_start_val` | `0` | number | `float()` → `[rename] trailing_start_value` | (매도 실행) | (일반) | sell-settings |
| `ts_drop_val` | `0` | number | `float()` → `[rename] trailing_drop_value` + 부호 마이그레이션 | (매도 실행) | (일반, 수치 검증 `-100~0`) | sell-settings |
| `sell_price_type` | `"mkt"` | string | `str()` | (매도 실행) | (일반) | sell-settings |
| `sell_offset` | `0` | number | `int()` | (매도 실행) | (일반) | sell-settings |
| `sell_custom_qty` | `0` | number | `int()` | (매도 실행) | (일반) | sell-settings |
| `sell_qty_type` | `"%"` | string | `str()` | (매도 실행) | (일반) | sell-settings |

> `loss_val` / `ts_drop_val`은 `_build_sell_settings`에서 rename과 동시에 부호 규약(P23 후안 B)을 따름. 마이그레이션(`_migrate_loss_val_to_negative`, `_migrate_ts_drop_val_to_negative`)이 DB 로드 시 양수→음수 변환을 1회 수행. **주의**: `_build_sell_settings`가 `loss_cut_apply` / `trailing_stop_apply` 등으로 rename하므로, 캐시에는 rename 후 키가 들어있고 UI(`AppSettings`)는 rename 전 원본 키(`loss_apply`, `ts_apply` 등)를 사용 — 매핑 주의 필요 (후속 검토 대상).

### 3.8 업종순위·필터 (10키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `sector_min_rise_ratio_pct` | `60.0` | number | `float()` | `engine_sector_confirm.py:153,224`, `sector_data_provider.py:265` | `_apply_sector_ui_change` | sector-settings |
| `buy_block_rise_on` | `True` | boolean | 마이그레이션 추론 | (파이프라인) | `_apply_sector_ui_change` | sector-settings |
| `buy_block_rise_pct` | `7.0` | number | `float()` (수치 검증 아님 — 양수 허용) | (파이프라인) | `_apply_sector_ui_change` | sector-settings |
| `buy_block_fall_on` | `True` | boolean | 마이그레이션 추론 | (파이프라인) | `_apply_sector_ui_change` | sector-settings |
| `buy_block_fall_pct` | `-7.0` | number | `float()` (수치 검증 `-100~0`, 음수만) | (파이프라인) | `_apply_sector_ui_change` | sector-settings |
| `sector_min_trade_amt` | `0.0` | number | `float()` (수치 검증 `1~100000`) | `engine_sector_confirm.py:117,225`, `sector_data_provider.py:74,266`, `engine_config.py:84` (변경 감지) | `_apply_sector_ui_change` + `on_filter_settings_changed` | sector-settings |
| `sector_max_targets` | `3` | number | `int()` | `engine_account_notify.py:320`, `engine_snapshot.py:63`, `web/routes/ws.py:118` | `_apply_sector_ui_change` | sector-settings |
| `sector_sort_keys` | `["score"]` | json | 외래/기관 net 제거 필터 | (파이프라인) | `_apply_sector_ui_change` | sector-settings |
| `sector_stock_layout` | `[]` | json (runtime) | (정규화 제외 — `_RUNTIME_ONLY_KEYS` 보존) | `market_close_pipeline.py:106,1148`, `engine_cache.py:43,54`, `web/routes/settings.py:129,140` | (레이아웃 재계산은 `_apply_sector_ui_change` 외부 — 별도 경로) | (UI 간접) |
| `sector_start_threshold_pct` | `70.0` | number | `float()` | `pipeline_compute.py:598` | (일반) | sector-settings |

> `sector_stock_layout`은 `build_engine_settings_dict()` 결과에 **없음** (정규화 제외). `refresh_engine_integrated_system_settings_cache`가 `_RUNTIME_ONLY_KEYS=("sector_stock_layout",)` 보존. 즉 런타임 전용 키로 DB에 저장되지 않고 캐시에만 상주 — P10 SSOT 예외 (후속 검토 대상 — 원본이 어디인지 명확하지 않음).

### 3.9 업종 점수 슬라이더 (3키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `sector_bonus_rise_ratio_slider` | `0` | number | `int()` | `engine_sector_confirm.py:157,226`, `sector_data_provider.py:267` | `_apply_sector_ui_change` | sector-settings |
| `sector_bonus_relative_strength_slider` | `0` | number | `int()` | `engine_sector_confirm.py:158,227`, `sector_data_provider.py:268` | `_apply_sector_ui_change` | sector-settings |
| `sector_bonus_trade_amount_slider` | `0` | number | `int()` | `engine_sector_confirm.py:159,228`, `sector_data_provider.py:269` | `_apply_sector_ui_change` | sector-settings |

### 3.10 주문 간격 (4키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `buy_interval_on` | `False` | boolean | `bool()` | (order_interval 헬퍼) | (일반) | buy-settings |
| `buy_interval_sec` | `30` | number | `int()` + 레거시 `buy_interval_min` 변환 분기 | (order_interval) | (일반) | buy-settings |
| `sell_interval_on` | `False` | boolean | `bool()` | (order_interval) | (일반) | sell-settings |
| `sell_interval_sec` | `30` | number | `int()` | (order_interval) | (일반) | sell-settings |

> `buy_interval_min` 레거시 키는 `_migrate_order_intervals`에서만 참조, DB 저장 시 제거 마이그레이션은 명시되지 않음 (후속 검토).

### 3.11 수신율 임계값·구독 한도 (2키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `sector_start_threshold_pct` | `70.0` | number | `float()` | `pipeline_compute.py:598` | (일반) | sector-settings |
| `subscribe.max_0b_count` | `200` | number | `int()` (수치 검증 `1~1000`) | `engine_ws_reg.py:258` | (일반) | time-settings-tab |

### 3.12 종목별 매도·브로커 매핑 (2키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `sell_per_symbol` | `{}` | json | `normalize_symbol_override_map()` (종목코드 6자리 zero-pad) | `engine_lifecycle.py:326` | (일반) | (sell-settings 종목별) |
| `broker_config` | `{}` | json | `[derive] _normalize_broker_config()` — `{websocket,order,sector,auth}` 모두 현재 broker로 채움 | `broker_router.py:65,97`, `engine_loop.py:58`, `connector_manager.py:40`, `engine_snapshot.py:78` | (일반 — 변경 시 의도적 무효화 경로 없음) | (UI 노출 없음) |

> `broker_config`는 DB에 `{}`로 저장되어도 정규화가 모든 값을 현재 `broker`로 파생 채움. 즉 DB 원본과 캐시 내용이 다름 (P10 SSOT — 파생은 정규화 시점에 재계산, 원본은 빈 dict 유지). 사용자가 임의 브로커 매핑을 저장하는 경로는 현재 없음 (코드 주석 "기본값: 동일 브로커 사용").

### 3.13 장마감 스케줄러 토글 (2키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `scheduler_market_close_on` | `True` | boolean | `bool()` | `market_close_pipeline.py:1025` | `_apply_timetable_change` (재빌드) | time-settings-tab |
| `scheduler_5d_download_on` | `True` | boolean | `bool()` | (파이프라인) | `_apply_5d_download_toggle` (ON 시 즉시 트리거) | (UI 노출 탭 미확정) |

### 3.14 타임테이블 (4키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `timetable.realtime_reset` | `"07:58"` | string | `str()[:5]` | `daily_time_scheduler.py` (타임테이블 빌드) | `_apply_timetable_change` + `_validate_pre_open_order` (rt ≤ ws ≤ krx < 09:00) | time-settings-tab |
| `timetable.ws_prestart` | `"07:59"` | string | `str()[:5]` | `daily_time_scheduler.py` | `_apply_timetable_change` + 순서 검증 | time-settings-tab |
| `timetable.krx_pre_subscribe` | `"08:59"` | string | `str()[:5]` | `daily_time_scheduler.py` | `_apply_timetable_change` + 순서 검증 | time-settings-tab |
| `timetable.confirmed_download` | `"20:40"` | string | `str()[:5]` | `daily_time_scheduler.py` | `_apply_timetable_change` + `_validate_post_close_order` (> 20:00) | time-settings-tab |

> 4키는 `_TIME_FIELDS` frozenset에 등록되어 `HH:MM` 형식 검증 + 2그룹 순서 검증(장 전 3키, 장 후 1키) 통과해야 저장. 순서 위반 시 `ValueError` → PATCH 422.

### 3.15 UI 설정 (1키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `ui_price_flash_on` | `True` | boolean | (정규화 제외 — `_build_*` 어디에도 없음) | (프론트엔드 uiStore에서만 소비) | (일반) | display-settings-tab |

> `ui_price_flash_on`은 `build_engine_settings_dict()` 9개 `_build_*` 그룹 어디에도 포함되지 않음. 즉 정규화를 거치지 않고 DB 원본이 캐시에 그대로 주입되는지, 아니면 누락되는지 후속 확인 필요. 프론트엔드 `AppSettings`에는 선언되어 있고 `display-settings-tab`에서 저장. 백엔드 캐시 read 경로가 없으므로 **프론트엔드 전용 키**일 가능성 (후속 검토 — 정규화 누락인지 의도인지).

### 3.16 수익현황 요약 범위 (1키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `daily_summary_days` | `20` | number | (정규화 제외 — `_build_*` 미포함) | `trade_history.py:190,213`, `engine_snapshot.py:139` | (일반, 수치 검증 `0~365`) | (수익현황 페이지) |

> `daily_summary_days`도 `build_engine_settings_dict()`에 미포함. DB 원본이 캐시에 주입되는 경로 확인 필요. 캐시 read는 3곳에서 `cache.get("daily_summary_days", 20)` 안전 패턴 사용.

### 3.17 텔레그램 (5키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|----|--------|---------|--------|-----------|--------------|-----|
| `tele_on` | `False` | boolean | `bool()` + `[derive] telegram_on` (동일값 복제) | `engine_service.py:247`, `web/routes/settings.py:71`, `app.py:149` | `_apply_telegram_toggle` (start/stop) + 엔진 미실행 시에도 즉시 반영 | telegram-tab |
| `telegram_chat_id` | `""` | string | `str()` | `telegram_bot.py` | (일반) | telegram-tab |
| `telegram_bot_token_test` | `""` | string (암호화) | `_decrypt_field()[0]` | `telegram_bot.py` | (일반, 암호화 저장) | telegram-tab (password) |
| `telegram_bot_token_real` | `""` | string (암호화) | `_decrypt_field()[0]` | `telegram_bot.py` | (일반, 암호화 저장) | telegram-tab (password) |
| `[derive] telegram_on` | — | — | `bool(merged["tele_on"])` | `get_settings_snapshot()` 호환용 | — | (동일) |

> `tele_on`과 `telegram_on`은 동일 의미 복제 키 (P10 SSOT 위반 후보 — `engine_config.get_settings_snapshot()`이 양쪽 모두 채움). `_build_telegram_settings`가 `telegram_on = bool(tele_on)` 파생 생성. 마이그레이션에 `telegram_on` 제거는 없음. 후속 검토 대상.

### 3.18 증권사 자격증명 (동적 — 증권사별)

| 키 패턴 | 기본값 | DB 타입 | 정규화 | 캐시 read | PATCH 후처리 | UI |
|---------|--------|---------|--------|-----------|--------------|-----|
| `{broker}_app_key` | (없음) | string (암호화) | `_decrypt_field()` + `[derive] _credential_states[broker].app_key` | `kiwoom_connector.py:536`, `ls_connector.py:827`, `kiwoom_providers.py:36`, `ls_providers.py:23` | (일반, 암호화 저장) | api-settings-tab (password) |
| `{broker}_app_secret` | (없음) | string (암호화) | `_decrypt_field()` + `[derive] _credential_states[broker].app_secret` | `kiwoom_connector.py:537`, `ls_connector.py:828`, `kiwoom_providers.py:37`, `ls_providers.py:24` | (일반, 암호화 저장) | api-settings-tab (password) |
| `{broker}_account_no` | (없음) | string | `str().strip()` | `kiwoom_providers.py:42` | (일반) | api-settings-tab |
| `[derive] _credential_states` | — | — | `{broker: {app_key, app_secret}}` SecretValueState.name | `engine_settings.py:110` (`broker_credential_state()` SSOT) | — | (api-settings 배지 표시) |
| `[derive] _broker_specs` | — | json (DB `_broker_specs:{name}`) | (정규화 통과) | `broker_router.py:77` | (일반) | (UI 노출 없음) |

> `kiwoom_app_key` / `kiwoom_app_secret` / `ls_app_key` / `ls_app_secret` / `telegram_bot_token_test` / `telegram_bot_token_real` 6키가 `_ENCRYPT_FIELDS` frozenset (암호화 대상). `kiwoom_account_no` / `ls_account_no`는 암호화 대상 아님 (민감값이지만 평문 저장 — 후속 검토).

### 3.19 시스템 설정 (DEFAULT_SYSTEM_CONFIG 17키)

| 키 | 기본값 | DB 타입 | 정규화 | 캐시 read | UI |
|----|--------|---------|--------|-----------|-----|
| `krx_open_time` 등 마켓 시간 11키 | (고정값) | string | (정규화 제외 — `_build_*` 미포함) | (운영 참조 미발견 — `daily_time_scheduler.py` 코드 상수가 SSOT) | (UI 노출 없음) |
| `db_connection_timeout` | `30` | number | (정규화 제외) | (DB 연결 설정) | 없음 |
| `db_retry_count` | `3` | number | (정규화 제외) | (DB 재시도) | 없음 |
| `db_retry_delay` | `1.0` | number | (정규화 제외) | (DB 재시도) | 없음 |
| `cache_size` | `1000` | number | (정규화 제외) | (캐시 크기) | 없음 |
| `log_level` | `"INFO"` | string | (정규화 제외) | (로깅 설정) | 없음 |

> **P10 SSOT 위반 후보**: `krx_open_time` 등 마켓 시간 11키는 `DEFAULT_SYSTEM_CONFIG`에 정의되어 DB에 저장되지만, 실제 장 시간 판정은 `daily_time_scheduler.py:21-49`의 **코드 상수**가 SSOT. 즉 DB 값을 바꿔도 적용되지 않음 (사용자가 UI에서 변경할 수도 없음). `ARCHITECTURE.md`가 "거래소 고정 7개 시간은 코드 상수로 유지"라고 명시하므로 의도적이나, DB에 중복 저장은 P10 위반. 후속 검토 대상 (별도 승인 시 DB에서 제거 또는 코드 상수 제거).

---

## 4. 단계별 변환 규칙 요약

### 4.1 정규화 단계 (`build_engine_settings_dict`) 변환 패턴

| 패턴 | 적용 키 | 비고 |
|------|---------|------|
| `bool(merged["키"])` | 대부분의 `_on` 토글 | P10 SSOT 준수 |
| `int(merged["키"])` | 정수형 설정 | |
| `float(merged["키"])` | 소수형 설정 | |
| `str(merged["키"])[:5]` | 시간 필드 8키 | `HH:MM` 5자리 |
| `str(merged["키"]).strip()` | broker, account_no, confirmed_data_broker | |
| `max(float(), 0)` | boost 점수 4키 | 음수 차단 |
| `max(-100, min(100, _raw_pct))` | `boost_order_ratio_pct` | 범위 클램프 |
| `[rename]` | `loss_apply→loss_cut_apply`, `ts_apply→trailing_stop_apply`, `loss_val→loss_cut_value`, `ts_start_val→trailing_start_value`, `ts_drop_val→trailing_drop_value` | UI는 원본 키, 캐시는 rename 후 |
| `[derive]` | `telegram_on`, `auto_buy_effective`, `auto_sell_effective`, `auto_trading_effective`, `_credential_states`, `broker_config`, `auto_trading_effective` | 원본 DB에 없음 |
| 마이그레이션 추론 (`flat.get()`) | `buy_amt_on`, `max_stock_cnt_on`, `buy_block_rise_on`, `buy_block_fall_on`, `buy_interval_sec` | P10 SSOT 예외 — `merged` 직접 접근 아님 |

### 4.2 저장 검증 (`apply_settings_updates`) 규칙

| 검증 | 대상 키 | 실패 시 |
|------|---------|---------|
| `None` 무시 | 모든 키 | 경고 로그, 저장 안 함 |
| 빈 문자열 무시 | 모든 키 | 경고 로그, 기존 값 유지 (P20 — 빈 값 폴백 금지) |
| `broker` 허용값 | `broker` | `ValueError` → 422 |
| `HH:MM` 형식 | `_TIME_FIELDS` 8키 | 경고 로그, 무시 |
| 타임테이블 순서 (장 전 3키) | `timetable.realtime_reset/ws_prestart/krx_pre_subscribe` | `ValueError` → 422 |
| 타임테이블 순서 (장 후 1키) | `timetable.confirmed_download` | `ValueError` → 422 |
| 구독 한도 범위 | `subscribe.max_0b_count` (1~1000) | `ValueError` → 422 |
| 리스크 정수 범위 | `daily_loss_limit` (-1e9~0), `consecutive_loss_limit` (1~100) | `ValueError` → 422 |
| 리스크 소수 범위 | `daily_loss_rate_limit`, `sector_min_trade_amt`, `loss_val`, `ts_drop_val`, `buy_block_fall_pct` (모두 음수만) | `ValueError` → 422 |
| 뉴스 점수 범위 | `boost_news_score` (0~100) | `ValueError` → 422 |
| 뉴스 TTL 범위 | `news_boost_ttl_sec` (0~3600) | `ValueError` → 422 |
| 뉴스 키워드 길이 | `news_keywords` (≤2000자) | `ValueError` → 422 |
| 일별 요약 범위 | `daily_summary_days` (0~365) | `ValueError` → 422 |
| 암호화 | `_ENCRYPT_FIELDS` 6키 | `EncryptionError` → 422 (구조화 detail) |

> **검증 누락 후보**: `buy_block_rise_pct`는 양수만 허용되어야 하나 `_RISK_FLOAT_KEYS`에 없음 (음수 범위가 아님). `tp_val` / `ts_start_val` / `sell_offset` / `sell_custom_qty` / `max_daily_total_buy_amt` / `max_single_stock_exposure` / `max_position_size` / `test_virtual_deposit` / `test_virtual_balance` 등 수치 키의 범위 검증 미존재. 후속 검토 대상.

### 4.3 PATCH 후처리 디스패처 분기 (`apply_settings_change`)

| 분기 | 트리거 키 | 동작 | 조기 종료 |
|------|-----------|------|-----------|
| 캐시 갱신 | 모든 변경 | `refresh_engine_integrated_system_settings_cache` | 아니오 |
| broker 변경 | `broker` | 엔진 재기동 | **예** |
| 투자모드 전환 | `TRADE_MODE_KEYS={trade_mode}` | 계좌 구독 전환 | **예** |
| 일반 브로드캐스트 | 위 2개 미해당 | `notify_desktop_settings_toggled(changed_dict)` | 아니오 |
| 가상 예수금 | `test_virtual_balance`, `test_virtual_deposit` | Settlement Engine reset + 계좌 스냅샷 | 아니오 |
| 5d 다운로드 토글 | `scheduler_5d_download_on` | ON 시 즉시 트리거 | 아니오 |
| 시간 스케줄 | `time_scheduler_on`, `auto_buy_on`, `auto_sell_on`, `buy_time_*`, `sell_time_*` | 타이머 재예약 | 아니오 |
| 타임테이블 | `timetable.*` 4키, `scheduler_market_close_on` | 재빌드 + 재예약 | 아니오 |
| 업종 UI | `sector_*`, `buy_block_*`, `boost_*`, `rebuy_block_on` 등 | 업종 점수 재계산 + `on_filter_settings_changed` | 아니오 |
| 텔레그램 | `tele_on` | 폴링 start/stop | 아니오 |
| 매수 스냅샷 무효화 | 모든 변경 | `invalidate_buy_snapshot()` | 아니오 |

> **후처리 누락 후보**: `confirmed_data_broker` 변경 시 디스패처 분기 없음 (재기동 필요하나 안내 없음 — P21). `ui_price_flash_on`은 프론트 전용이므로 백엔드 후처리 불필요. `sell_per_symbol` / `broker_config` / `sell_price_type` / `sell_offset` / `sell_qty_type` / `loss_val` / `ts_*` / `tp_*` / `loss_apply` / `tp_apply` / `risk_manager_*` / `daily_loss_*` / `consecutive_loss_*` / `risk_block_*` / `max_*` / `buy_amt*` / `buy_interval*` / `sell_interval*` / `news_boost_ttl_sec` / `news_keywords` / `daily_summary_days` / `telegram_chat_id` / `telegram_bot_token_*` / `{broker}_*` / `sector_start_threshold_pct` / `sector_sort_keys` / `subscribe.max_0b_count` 등은 일반 브로드캐스트만 수행 (매수/매도 실행 경로에 즉시 반영되는지 별도 검증 필요).

---

## 5. 프론트엔드 소비 매핑

### 5.1 UI 탭별 saveSection 키

| 탭 파일 | 저장 키 |
|---------|---------|
| `general-settings-account-tab.ts` | `trade_mode`, `test_virtual_deposit`, `test_virtual_balance` |
| `general-settings-api-settings-tab.ts` | `broker`, `kiwoom_app_key`, `kiwoom_app_secret`, `kiwoom_account_no`, `ls_app_key`, `ls_app_secret`, `ls_account_no` |
| `general-settings-auto-trade-tab.ts` | `risk_manager_on`, `daily_loss_limit`, `daily_loss_limit_on`, `daily_loss_rate_limit`, `daily_loss_rate_limit_on`, `consecutive_loss_limit`, `consecutive_loss_limit_on`, `risk_block_buy_on`, `risk_block_sell_on`, `time_scheduler_on` |
| `general-settings-display-settings-tab.ts` | `ui_price_flash_on` |
| `general-settings-news-settings-tab.ts` | `news_keywords`, `news_boost_ttl_sec` |
| `general-settings-telegram-tab.ts` | `tele_on`, `telegram_chat_id`, `telegram_bot_token_test`, `telegram_bot_token_real` |
| `general-settings-time-settings-tab.ts` | `buy_time_start`, `buy_time_end`, `sell_time_start`, `sell_time_end`, `auto_buy_on`, `auto_sell_on`, `scheduler_market_close_on`, `subscribe.max_0b_count`, `timetable.*` (4키) |
| `buy-settings.ts` | `buy_amt`, `buy_amt_on`, `max_stock_cnt`, `max_stock_cnt_on`, `max_daily_total_buy_on`, `max_daily_total_buy_amt`, `rebuy_block_on`, `rebuy_block_period`, `buy_interval_on`, `buy_interval_sec`, `tp_*`, `loss_*`, `ts_*`, `boost_*` |
| `sell-settings.ts` | `tp_apply`, `tp_val`, `loss_apply`, `loss_val`, `ts_apply`, `ts_start_val`, `ts_drop_val`, `sell_price_type`, `sell_offset`, `sell_custom_qty`, `sell_qty_type`, `sell_interval_on`, `sell_interval_sec`, `sell_per_symbol` |
| `sector-settings.ts` | `sector_min_rise_ratio_pct`, `sector_min_trade_amt`, `sector_max_targets`, `sector_start_threshold_pct`, `sector_sort_keys`, `sector_bonus_*_slider` (3키), `buy_block_rise_*`, `buy_block_fall_*`, `boost_high_breakout_*`, `boost_order_ratio_*`, `boost_program_net_buy_*` |

### 5.2 마스킹 필드 (`MASKED_FIELDS`)

```typescript
// frontend/src/settings.ts:12
export const MASKED_FIELDS = new Set([
  'kiwoom_app_key', 'kiwoom_app_secret',
  'ls_app_key', 'ls_app_secret',
  'telegram_bot_token_test', 'telegram_bot_token_real',
])
```

> 백엔드 `_ENCRYPT_FIELDS`(6키)와 1:1 대응 (P10 SSOT — 양쪽 6키 동일). 단, 백엔드 `_mask_sensitive_settings`(`engine_config.py:116`)는 broker에 따라 동적 키(`{broker}_app_key` 등)도 마스킹하므로, 프론트 `MASKED_FIELDS`는 고정 6키만 포함. 증권사 추가 시 프론트 업데이트 필요 (후속 검토 — 동적 마스킹 SSOT화).

### 5.3 WS `settings-changed` 이벤트

- 백엔드: `notify_desktop_settings_toggled(changed_dict)` → WS 전송
- 프론트: `binding.ts:179` `settingsClient.onEvent('settings-changed', applySettingsChanged)`
- `uiStore.applySettingsChanged(data)` (line 146): `delta` 플래그 있으면 증분 갱신, 없으면 전체 교체

---

## 6. 테스트 커버리지

### 6.1 백엔드 설정 테스트 (3개 파일)

| 파일 | 클래스 | 커버 범위 |
|------|--------|-----------|
| `test_settings_store.py` | 8 클래스 | `normalize_stk_cd_key`, `normalize_symbol_override_map`, `_validate_timetable_order` (2그룹), `apply_settings_updates` (증분 저장), `subscribe.max_0b_count` 검증, 리스크 매니저 검증, `build_masked_settings_dict`, `daily_summary_days` 검증 |
| `test_settings_file_integration.py` | 6 클래스 | DB 로드/저장, P20 전파, `classify_secret_fields`, 암호화 정책 |
| `test_settings_boost_order_ratio.py` | 5 테스트 | `boost_order_ratio_*` 저장/정규화 |

### 6.2 캐시 소비자 테스트 (integrated_system_settings_cache 모킹 22개 파일)

`test_trading.py`(20), `test_daily_time_scheduler.py`(24), `test_engine_sector_confirm.py`(11), `test_engine_snapshot.py`(12), `test_pipeline_compute.py`(13), `test_buy_order_executor.py`(13), `test_risk_manager.py`(22), `test_engine_settings.py`(7), `test_engine_loop.py`(5), `test_web_routes.py`(8), `test_broker_router.py`(8), `test_telegram_bot.py`(15), `test_engine_bootstrap.py`(3), `test_market_close_pipeline.py`(4), `test_engine_ws.py`(3), `test_engine_cache.py`(2), `test_engine_state_groups.py`(2), `test_engine_ws_dispatch.py`(5), `test_engine_ws_dispatch_isolation.py`(3), `test_trade_history.py`(6), `test_web_app.py`(2), `test_web_ws_routes.py`(8), `test_web_stock_classification.py`(1), `test_settlement_engine.py`(1), `test_settlement_verification.py`(1), `test_dry_run_fill_event.py`(1), `test_connector_manager.py`(2), `test_ls_connector.py`(2), `test_kiwoom_connector.py`(2), `test_ls_providers.py`(1), `test_kiwoom_providers.py`(1), `test_sector_data_provider.py`(3), `test_settings_boost_order_ratio.py`(5)

> 캐시 모킹은 `state.integrated_system_settings_cache`를 dict로 직접 채워 테스트. 즉 캐시 소비자가 실제 `build_engine_settings_dict()` 정규화를 거치지 않고 테스트되는 경우가 많음 (P22 데이터 정합성 — 정규화 누락 키 테스트 시 주의).

---

## 7. 발견 사항 요약

### 7.1 P10 SSOT 위반 후보 (별도 승인 시 검토)

| 순위 | 항목 | 비고 | 상태 |
|------|------|------|------|
| 1 | `max_daily_loss_limit` vs `daily_loss_limit` 중복 의미 | 주석이 "동일 기준" 명시. `risk_manager.py`가 `daily_loss_limit`의 폴백 기본값으로만 사용 | ☑ 완료 (safe-trade 절차 적용, `daily_loss_limit` SSOT화) |
| 2 | `max_single_stock_exposure` / `max_position_size` | **매트릭스 원 판정 부정확** — `max_single_stock_exposure`는 살아있는 매수 차단 로직(`risk_manager.py:146`). 제거 금지. `max_position_size`만 dead read | ☑ `max_position_size` 제거 / `max_single_stock_exposure` 유지+정정 |
| 3 | `tele_on` vs `[derive] telegram_on` 복제 | `telegram_on` 파생 제거 + `telegram_bot.py` dead key 제거 + `get_settings_snapshot()` 호환 채움 제거 | ☑ 완료 |
| 4 | `DEFAULT_SYSTEM_CONFIG` 마켓 시간 14키 vs `daily_time_scheduler.py` 코드 상수 | DB에 저장되나 코드 상수가 SSOT. DB 값 변경 무효 (매트릭스 원 "11키" → 실제 14키) | ☑ 완료 |
| 5 | `boost_order_ratio_side` 레거시 | `_build_boost_settings` 변환 분기 제거 + DB 마이그레이션 | ☑ 완료 |
| 6 | `buy_interval_min` 레거시 | `_migrate_order_intervals` 변환 분기 제거(`_build_order_intervals`로 단순화) + DB 마이그레이션 | ☑ 완료 |

### 7.2 P20/P21 후속 검토 대상

| 항목 | 비고 |
|------|------|
| ~~`confirmed_data_broker` PATCH 후처리 누락~~ | **해결 완료** — `_handle_broker_change` 감지 조건 확장, 변경 시 엔진 재기동 (P21) |
| ~~수치 범위 검증 누락 키~~ | **해결 완료** — `_TRADE_FLOAT_KEYS` + `_TRADE_INT_KEYS` 추가 (8개 키 범위 검증) |
| ~~`sector_stock_layout` 원본 SSOT 미명확~~ | **해결 완료** — 원본 SSOT는 `master_stocks_cache`의 sector 필드, 코드 주석에 명확화 (P22) |
| `ui_price_flash_on` 정규화 누락 | `build_engine_settings_dict()` 미포함, 백엔드 캐시 read 없음 — 프론트 전용 키인지 정규화 누락인지 확인 필요 |
| `daily_summary_days` 정규화 누락 | `build_engine_settings_dict()` 미포함, 캐시 read 3곳 — 정규화 통과 경로 확인 필요 |
| GET `/api/settings` 캐시 미사용 | 매 요청 DB 직접 로드, 캐시와 일시적 불일치 가능 (저장 직후 GET 시) |

### 7.3 P23 일관성 후속 검토

| 항목 | 비고 |
|------|------|
| `_build_sell_settings` rename 키와 UI 원본 키 불일치 | 캐시는 `loss_cut_apply` 등, UI는 `loss_apply` 등 — 매핑 주의 |
| `MASKED_FIELDS` 고정 6키 vs 백엔드 동적 마스킹 | 증권사 추가 시 프론트 업데이트 필요 |
| NWS 4키 캐시 dict + state 속성 이중 상주 | 성능 최적화 목적, 변경 금지 범주이나 문서화 필요 |

### 7.4 단일화 우선순위 (후속 세션별 승인 후 진행)

| 순위 | 항목 | 위험도 | 비고 | 상태 |
|------|------|--------|------|------|
| 1 | `sector_stock_layout` 원본 SSOT 명확화 | 중간 | 런타임 파생 데이터 — 원본 SSOT는 `master_stocks_cache`의 sector 필드. 코드 주석에 SSOT 명확화 (settings_defaults/engine_config/engine_cache/market_close_pipeline). P22 준수 — 파생 데이터는 원본에서 파생. | ☑ 완료 |
| 2 | `confirmed_data_broker` PATCH 후처리 추가 | 중간 | P21 투명성 — `_handle_broker_change` 감지 조건을 `{"broker", "confirmed_data_broker"}`로 확장, 변경 시 엔진 재기동 (broker와 동일 패턴, P23 일관성). | ☑ 완료 |
| 3 | `max_daily_loss_limit` 제거 (safe-trade) / `max_single_stock_exposure` 유지+정정 / `max_position_size` 제거 | 낮음 | `max_position_size` 제거 완료, `max_single_stock_exposure` 정정 완료, `max_daily_loss_limit` 제거 완료 (safe-trade 절차 적용) | ☑ 완료 |
| 4 | `tele_on` / `telegram_on` 중복 제거 | 낮음 | `telegram_on` 파생 제거 + `telegram_bot.py` dead key 제거 + `get_settings_snapshot()` 호환 채움 제거 | ☑ 완료 |
| 5 | 수치 범위 검증 누락 키 추가 | 낮음 | `_validate_numeric_fields` 확장 — `_TRADE_FLOAT_KEYS`(buy_block_rise_pct/tp_val/ts_start_val, 0~100) + `_TRADE_INT_KEYS`(sell_offset/sell_custom_qty/max_daily_total_buy_amt/test_virtual_deposit/test_virtual_balance, 0~상한) 추가. 후안 B 부호 규칙 준수 (상승/익절 양수). | ☑ 완료 |

> 본 세션은 매트릭스 작성까지만 수행. 위 후속 항목은 각각 별도 세션에서 승인 후 진행 권장. 거래 관련 산재(`trading.py`의 `time_scheduler_on` write)는 COUPLING-S1과 동일하게 변경 금지 범주.

---

## 8. 결론

본 매트릭스는 `DEFAULT_USER_SETTINGS` 66키 + `DEFAULT_SYSTEM_CONFIG` 17키 + 동적 증권사 자격증명 + 파생 키(`_credential_states`, `broker_config`, `auto_*_effective`, `telegram_on` 등)의 전체 파이프라인 경로를 실제 코드 참조로 확정했다.

**핵심 발견**:
1. 파이프라인 6단계(DB → 기본값 → 정규화 → 캐시 → 서비스 → API/UI) 중 **정규화 단계**가 가장 복잡 — 9개 `_build_*` 그룹이 rename/derive/마이그레이션 추론 분기를 수행.
2. **P10 SSOT 위반 후보 6건** 식별 (중복 의미·dead read·레거시 잔존) — 전부 해결 완료.
3. **P21 투명성 후보 1건** (`confirmed_data_broker` 변경 시 사용자 안내 없음) — 해결 완료 (`_handle_broker_change` 감지 조건 확장, 엔진 재기동).
4. **검증 누락 키 다수** 식별 (수치 범위 검증 미존재) — 해결 완료 (`_TRADE_FLOAT_KEYS` + `_TRADE_INT_KEYS` 8개 키 추가).
5. `sector_stock_layout` 원본 SSOT 명확화 — 해결 완료 (런타임 파생 데이터, 원본은 `master_stocks_cache`의 sector 필드, P22 준수).
6. 캐시 소비자 28개 파일이 `integrated_system_settings_cache` 직접 참조 — 거래 관련 산재 1건(`trading.py`의 `time_scheduler_on` write)은 COUPLING-S1과 동일 변경 금지.

**COUPLING-S2 전체 완료** — 단일화 우선순위 5개 항목(#1~#5) 전부 해결. 백엔드 테스트 2779 passed (회귀 0건) + 런타임 기동 검증 pass (RuntimeWarning 0건).
