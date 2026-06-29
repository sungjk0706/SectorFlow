# HANDOVER — SectorFlow

## 완료 단계

### 1. LS증권 확정시세 다운로드 삭제 — 키움 단일 경로 통합 (완료)

#### 배경
- `confirmed_data_broker` 설정으로 확정시세 다운로드 증권사를 별도 선택 가능했던 하이브리드 아키텍처 제거
- 확정시세 다운로드(전종목 목록, 부적격 필터링, 1일봉, 5일봉)를 키움증권 단일 경로로 통합
- LS API 키/주문/계좌/실시간 기능은 유지

#### 백엔드 설정 계층 (그룹 A)
- **`settings_defaults.py:40`** — `confirmed_data_broker: "kiwoom"` 기본값 삭제
- **`settings_store.py:170`** — broker 검증 조건에서 `confirmed_data_broker` 제거 (`if k in ("broker", "confirmed_data_broker")` → `if k == "broker"`)
- **`engine_settings.py:50`** — `confirmed_data_broker` 엔진 설정 결과 필드 삭제
- **`engine_settings.py:183`** — `stock_broker = "kiwoom"` 고정 (기존 `stock_broker = broker`에서 변경)

#### 백엔드 파이프라인 계층 (그룹 B)
- **`market_close_pipeline.py:768-772`** — `_run_confirmed_pipeline` 브로커 선택에서 `confirmed_data_broker` 참조 제거
- **`market_close_pipeline.py:1220-1224`** — `fetch_5d_data_only` 브로커 선택에서 `confirmed_data_broker` 참조 제거

#### 백엔드 엔진 서비스 (그룹 C)
- **`engine_service.py:208-211`** — `confirmed_data_broker` 변경 감지 블록 전체 삭제

#### 백엔드 LS 다운로드 로직 삭제 (그룹 D)
- **`ls_providers.py`** — `LsStockProvider`의 4개 다운로드 메서드 삭제: `fetch_stock_daily_price`, `fetch_stock_5day_data`, `fetch_all_stocks_5day`, `fetch_all_stocks_daily_confirmed`
- **`ls_stock_rest.py`** — 6개 다운로드 함수 삭제: `fetch_ls_daily_price`, `fetch_ls_daily_price_t8410`, `fetch_ls_stock_5day_data`, `fetch_ls_stock_5day_data_t8410`, `fetch_ls_all_stocks_daily_confirmed`, `fetch_ls_all_stocks_5day`
- **`ls_stock_rest.py`** — 6개 헬퍼 함수 삭제: `_daily_rows`, `_close_value`, `_change_value`, `_trade_amount`, `_daily_dict`
- **`ls_stock_rest.py`** — `_CHART_PATH` 상수 삭제, `Callable` import 삭제

#### 프론트엔드 타입 (그룹 E)
- **`types/index.ts:89`** — `AppSettings.confirmed_data_broker` 타입 정의 삭제

#### 프론트엔드 UI (그룹 F)
- **`general-settings.ts`** — 변수 2개 삭제: `confirmedDataBrokerRadios`, `confirmedDataBrokerSaving`
- **`general-settings.ts`** — "다운로드 증권사" 라디오 버튼 렌더링 블록 + 설명 텍스트 삭제
- **`general-settings.ts`** — `handleConfirmedDataBrokerChange()` 함수 삭제
- **`general-settings.ts`** — `syncConfirmedDataBrokerRadios()` 함수 삭제
- **`general-settings.ts`** — `handleBrokerChange` 내 `syncConfirmedDataBrokerRadios()` 호출 삭제
- **`general-settings.ts`** — `applySettingsToUI` 내 `confirmed_data_broker` 동기화 및 `syncConfirmedDataBrokerRadios()` 호출 삭제

#### 유지된 LS 기능
- LS API 키 입력 UI (`ls_app_key`, `ls_app_secret`, `ls_account_no`) — 유지
- LS API 탭 버튼 — 유지
- `LsAuthProvider`, `LsAccountProvider`, `LsOrderProvider`, `LsWebSocketProvider` — 유지
- `LsStockProvider.fetch_all_stocks()` (전종목 목록) — 유지
- `fetch_ls_ineligible_codes()` (부적격 종목 필터링) — 유지
- `fetch_ls_all_stocks_unified()` — 유지
- `broker_registry.py` LS 레지스트리 — 유지
- `settings_file.py` / `settings_store.py` LS API 키 암호화 필드 — 유지
- `frontend/src/settings.ts` `MASKED_FIELDS` LS 키 — 유지

#### 검증
- `confirmed_data_broker` 소스 코드 잔여 0건 (로그 파일 제외)
- LS 다운로드 함수 잔여 0건
- 프론트엔드 `confirmedDataBroker` 관련 잔여 0건
- `npm run build` 성공 (tsc + vite)
- 백엔드 import 성공 (`engine_settings`, `ls_stock_rest`, `ls_providers`, `settings_defaults`)
- `DEFAULT_USER_SETTINGS`에 `confirmed_data_broker` 키 없음 확인

## 현재 상태
- LS증권 확정시세 다운로드 삭제 완료 — 코드 수정 완료, 빌드/import 검증 통과
- **앱 재기동 필요** — 재기동 전까지 메모리 캐시에 이전 `broker_config` 남아 있어 LS로 다운로드 시도 가능
- 재기동 후 `broker_config["stock"]` = `"kiwoom"` 고정되어 키움 단일 경로 동작

## 다음 단계
- **앱 재기동 후 런타임 확인 (최우선)**:
  - 확정시세 다운로드 시 `broker=kiwoom`으로 동작 확인
  - 일반설정 페이지에서 "다운로드 증권사" 라디오 버튼 미표시 확인
  - API 설정 탭에서 "LS API" 탭 정상 표시 확인
  - LS API 키 입력 필드 정상 표시 확인
- **종목수 1359 → 1361 불일치 조사** (별도 세션에서 진행 필요)
  - `_apply_confirmed_to_memory`에서 새 엔트리 생성 의심
  - `_save_confirmed_cache`가 eligible_codes 없이 호출 시 전체 메모리 캐시 UPSERT

## 미해결 문제
- **재기동 전 캐시 잔류**: 앱 재기동 전까지 `_integrated_system_settings_cache`에 이전 `broker_config` (stock=ls) 남아 있음 — 재기동 후 자동 해결
- **종목수 1359 → 1361 불일치**: `_apply_confirmed_to_memory`에서 새 엔트리 생성 의심, 별도 조사 필요
- **TODO 주석 7건**: `deps.py:16`, `ws.py:159`, `ws_orders.py:23`, `ws_settings.py:23`, `client.ts:18,29,40,66`, `risk_manager.py:64`
