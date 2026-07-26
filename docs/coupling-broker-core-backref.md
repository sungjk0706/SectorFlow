# C-06 브로커 core 구현의 services 역참조

> 작성일: 2026-07-26
> 기준 계획서: `docs/coupling-audit-plan.md` C-06
> 상태: 조사 완료 (코드 수정 없음 — 문서만 작성)
> 대상 원칙: P4 증권사명 공통 침투 금지, P10 SSOT, P16 살아있는 경로, P23 계층 일관성, P24 단순성, P25 격리된 실패

---

## 1. 조사 범위 및 방법

### 1.1 조사 대상 파일

| 파일 | 줄 수 | 역할 |
|------|-------|------|
| `backend/app/core/broker_connector.py` | 107 | `BrokerConnector` 추상 인터페이스 — connect/disconnect/subscribe/send_message + ACK/동적/지수 구독 기본 구현 |
| `backend/app/core/broker_providers.py` | 72 | `AuthProvider`/`OrderProvider`/`WebSocketProvider` 서브 인터페이스 + `UnifiedStockRecord` 데이터클래스 |
| `backend/app/core/broker_registry.py` | 173 | Provider·Connector 레지스트리 — `_LazyBrokerRegistry` 지연 로딩(순환 import 방지) + `_create_provider` 팩토리 |
| `backend/app/core/broker_factory.py` | 36 | `get_router()` 싱글턴 + `reset_router()` 캐시 초기화 |
| `backend/app/core/broker_router.py` | 166 | `BrokerRouter` — 기능별 Provider 매핑 + `validate()` 자격증명/동일증권사 강제쌍 검증 |
| `backend/app/core/connector_manager.py` | 290 | `ConnectorManager` — 다중 증권사 WS Connector 생성·연결·구독 라우팅·재연결 복원 |
| `backend/app/core/kiwoom_connector.py` | 540 | 키움 WS 커넥터 — `_KiwoomSocket` 내부 소켓 + `KiwoomConnector` + `create_kiwoom_connector()` 팩토리 |
| `backend/app/core/ls_connector.py` | 832 | LS WS 커넥터 — `_LsSocket` + LS→내부 형식 변환 + `LsConnector` + `create_ls_connector()` 팩토리 |
| `backend/app/core/kiwoom_providers.py` | (참조) | 키움 Provider 4종 — AuthProvider가 `state.broker_rest_apis` 재사용 |
| `backend/app/core/ls_providers.py` | (참조) | LS Provider 3종 — AuthProvider가 `state.broker_rest_apis` 재사용 |
| `backend/app/core/kiwoom_account_parsing.py` | (참조) | 키움 REST/REAL04 파싱 — `engine_symbol_utils`·`engine_ws_parsing` 역참조 |
| `backend/app/core/kiwoom_order.py` | (참조) | 키움 주문 — `daily_time_scheduler.get_nxt_trde_tp` 역참조 (NXT 장외 시간대 trde_tp 조정) |
| `backend/app/core/engine_settings.py` | (참조) | 자격증명 상태 조회 — `state.integrated_system_settings_cache._credential_states` 역참조 |
| `backend/app/core/journal.py` | (참조) | 저널링 — `engine_utils.LazyLock` 역참조 |
| `backend/app/core/sector_mapping.py` | (참조) | 업종 매핑 — `state.master_stocks_cache` 역참조 |
| `backend/app/core/stock_classification_data.py` | (참조) | 종목 분류 — `state.master_stocks_cache` 역참조 3곳 |

참조된 services 계층:

| 파일 | 줄 수 | 역할 |
|------|-------|------|
| `backend/app/services/engine_state.py` | 239 | 엔진 전역 상태 싱글톤 — 69개 속성 + `_notify_reg_ack()` 헬퍼 |
| `backend/app/services/engine_ws.py` | 203 | REG/UNREG/REMOVE 전송 — `_ws_send_reg_unreg_and_wait_ack()` (ACK 대기) + `_ws_send_remove_fire_and_forget()` |
| `backend/app/services/engine_ws_reg.py` | 490 | 키움 REG 페이로드 빌더 5종 + 구독 함수 + `restore_subscriptions_after_reconnect()` |
| `backend/app/services/ws_subscribe_control.py` | 225 | 구독 제어 — `broadcast_ws_connection_status()` (상태 변경 시에만 WS 전송) + `_set_status()` |
| `backend/app/services/daily_time_scheduler.py` | 1510 | 스케줄러 — `_trigger_reg_pipeline()` (로그인 후 REG 재실행) + `get_nxt_trde_tp()` |
| `backend/app/services/engine_symbol_utils.py` | 124 | 종목코드 정규화 — `_base_stk_cd()` (순수) + `get_ws_subscribe_code()` (state 의존) + `is_nxt_enabled()` |
| `backend/app/services/engine_ws_parsing.py` | 172 | WS 파싱 순수 함수 — `_parse_fid10_price()` 등 |
| `backend/app/services/engine_utils.py` | (참조) | `LazyLock`/`LazyEvent` 유틸 |
| `backend/app/services/auto_trading_effective.py` | (참조) | `auto_trading_effective` — `settings_store.py`가 역참조 |

### 1.2 조사 방법

- `core/` 디렉터리 전체에서 `services` 키워드 grep → 50건 식별 (역참조 33건 + 주석/docstring 17건)
- `kiwoom_connector.py`·`ls_connector.py` 전체 읽기 → 역참조 호출부 줄 범위·컨텍스트 추출
- `broker_connector.py`·`broker_providers.py`·`broker_registry.py`·`broker_factory.py`·`broker_router.py`·`connector_manager.py` 전체 읽기 → 공통 인터페이스·레지스트리·팩토리 경로 확정
- 참조된 services 함수 정의부 전수 추적 — `broadcast_ws_connection_status`/`_notify_reg_ack`/`_trigger_reg_pipeline`/`_ws_send_*`/`build_*_payloads`/`get_ws_subscribe_code`/`_base_stk_cd`/`_parse_fid10_price`/`restore_subscriptions_after_reconnect`
- `engine_loop.py` WS 구간 감지 루프(`engine_loop.py:300-389`) 추적 — `ConnectorManager()` 생성·`set_message_callback`·`set_queue_callback`·`connect_all`·`disconnect_all` 단일 경로 확인
- `engine_ws_dispatch.py` ACK 처리 경로 추적 — `_notify_reg_ack()` 호출 2곳 (REG/UNREG/REMOVE 응답 → `reg_ack_event.set()`)
- `state.broker_rest_apis` 전수 grep — engine_loop 초기화 1곳 + providers 재사용 2곳 + connector 재사용 2곳 + engine_account 조회 1곳
- 테스트 파일 역참조 patch 패턴 전수 grep — `test_kiwoom_connector.py` 32건, `test_ls_connector.py` 19건, `test_daily_time_scheduler.py` 4건, `test_web_routes.py` 3건, `test_market_close_pipeline.py` 2건
- `try/except` 패턴 점검 → silent `except: pass` 0건, 모든 역참조 호출이 `logger.warning(..., exc_info=True)`로 격리

---

## 2. 시스템 아키텍처 개요

### 2.1 계층 구조 (이상적)

```
┌─────────────────────────────────────────────────┐
│ services/ (엔진 로직, 상태, 스케줄러, WS 오케스트레이션) │
│   ↓ core/ 인터페이스만 참조 (BrokerConnector ABC)     │
├─────────────────────────────────────────────────┤
│ core/ (브로커 공통 인터페이스 + 증권사별 구현)            │
│   broker_connector.py (ABC)                       │
│   broker_providers.py (ABC)                       │
│   broker_registry.py (레지스트리)                    │
│   broker_factory.py (팩토리)                       │
│   broker_router.py (라우터)                        │
│   connector_manager.py (다중 커넥터 관리)             │
│   kiwoom_connector.py / ls_connector.py (구현)     │
└─────────────────────────────────────────────────┘
```

### 2.2 실제 의존 방향 (역참조 포함)

```
services/ ──→ core/ (정방향 — 인터페이스·레지스트리·커넥터 사용)
   │
   │  ←── core/ 역참조 (C-06 대상) ──┐
   │                                   │
   ▼                                   ▼
engine_state.state                  kiwoom_connector.py
engine_ws._ws_send_*                ls_connector.py
engine_ws_reg.build_*_payloads      kiwoom_providers.py / ls_providers.py
ws_subscribe_control.broadcast_*    kiwoom_account_parsing.py
daily_time_scheduler._trigger_*     kiwoom_order.py
engine_symbol_utils._base_stk_cd    broker_router.py / connector_manager.py
engine_ws_parsing._parse_fid10_     engine_settings.py / journal.py
auto_trading_effective              sector_mapping.py / stock_classification_data.py
                                    settings_store.py
```

### 2.3 기동·연결 경로 (engine_loop.py:300-389)

```
1. is_ws_subscribe_window(settings) → True 시
2. ConnectorManager() 생성
   2a. _build() → state.integrated_system_settings_cache["broker_config"]["websocket"] 읽기
   2b. CONNECTOR_REGISTRY.get(broker_name)["create_connector"]()
       → create_kiwoom_connector() / create_ls_connector()
       → state.integrated_system_settings_cache에서 app_key/app_secret 읽기 (역참조 1)
3. set_message_callback(_broker_message_handler)  — services→core 정방향
4. set_queue_callback(tick_queue)                 — services→core 정방향
5. connect_all()
   → 각 Connector.connect()
      5a. _get_token_async()
          → state.broker_rest_apis.get(broker_id) (역참조 2)
          → router._auth_cache에서 AuthProvider.rest_api 재사용 (core 내부)
      5b. _socket.connect() + LOGIN (키움) / 소켓 연결=로그인 (LS)
      5c. state.login_ok = True (LS만, 역참조 3)
      5d. _notify_reg_ack() (LS만, 역참조 4)
      5e. _trigger_reg_pipeline() (LS만, 역참조 5)
      5f. subscribe_jif() / subscribe_news() (LS만)
      5g. broadcast_ws_connection_status(True) (역참조 6)
6. 재연결 시 (_on_socket_disconnect → _reconnect_loop)
   → state.login_ok = False (역참조 7)
   → broadcast_ws_connection_status(False) (역참조 8)
   → 재연결 성공 시 state.login_ok = True (LS) + broadcast_ws_connection_status(True)
   → _on_reconnect_success(broker_id) → ConnectorManager._on_reconnect_success
     → engine_ws_reg.restore_subscriptions_after_reconnect(broker_id) (services→services, core 경유)
```

---

## 3. 역참조 전수 매트릭스

### 3.1 kiwoom_connector.py (19건)

| 줄 | 참조 대상 (services) | 유형 | 용도 | 제거 가능성 |
|----|---------------------|------|------|------------|
| 242 | `ws_subscribe_control.broadcast_ws_connection_status(True)` | G | connect() 성공 시 WS 상태 브로드캐스트 | 콜백 인터페이스로 전환 가능 (중간 위험) |
| 260 | `ws_subscribe_control.broadcast_ws_connection_status(False)` | G | disconnect() 시 WS 상태 브로드캐스트 | 콜백 인터페이스로 전환 가능 (중간 위험) |
| 285 | `engine_ws_reg.build_0b_reg_payloads` | E | subscribe_stocks() 키움 0B REG 페이로드 빌더 | core/kiwoom_ws_reg.py로 이동 가능 (낮음, P4) |
| 286 | `engine_ws._ws_send_reg_unreg_and_wait_ack` | D | subscribe_stocks() ACK 대기 전송 | 커넥터가 ACK 프로토콜 직접 구현 시 제거 (높은 위험) |
| 287 | `engine_symbol_utils.get_ws_subscribe_code` | F | subscribe_stocks() 종목코드 → WS 구독 코드 변환 | state 의존(is_nxt_enabled) → 이동 불가 |
| 305 | `engine_ws_reg.build_0b_remove_payloads` | E | unsubscribe_stocks() 0B REMOVE 빌더 | core/kiwoom_ws_reg.py로 이동 가능 (낮음, P4) |
| 306 | `engine_ws._ws_send_remove_fire_and_forget` | D | unsubscribe_stocks() fire-and-forget | 커넥터가 직접 send_message로 전송 시 제거 (중간) |
| 307 | `engine_symbol_utils.get_ws_subscribe_code` | F | unsubscribe_stocks() 코드 변환 | state 의존 → 이동 불가 |
| 329 | `engine_ws_reg.build_0d_reg_payloads` | E | subscribe_dynamic() 0D REG 빌더 | core/kiwoom_ws_reg.py로 이동 가능 (낮음, P4) |
| 330 | `engine_ws._ws_send_reg_unreg_and_wait_ack` | D | subscribe_dynamic() ACK 대기 | 커넥터 직접 구현 시 제거 (높은 위험) |
| 349 | `engine_ws_reg.build_0d_remove_payloads` | E | unsubscribe_dynamic() 0D REMOVE 빌더 | core/kiwoom_ws_reg.py로 이동 가능 (낮음, P4) |
| 350 | `engine_ws._ws_send_reg_unreg_and_wait_ack` | D | unsubscribe_dynamic() ACK 대기 | 커넥터 직접 구현 시 제거 (높은 위험) |
| 365 | `engine_ws_reg.build_index_reg_payload` | E | subscribe_index() 0J REG 빌더 | core/kiwoom_ws_reg.py로 이동 가능 (낮음, P4) |
| 366 | `engine_ws._ws_send_reg_unreg_and_wait_ack` | D | subscribe_index() ACK 대기 | 커넥터 직접 구현 시 제거 (높은 위험) |
| 389 | `engine_state.state.login_ok = False` | A | _on_socket_disconnect() 로그인 상태 초기화 | 콜백 인터페이스로 전환 가능 (중간) |
| 394 | `ws_subscribe_control.broadcast_ws_connection_status(False)` | G | _on_socket_disconnect() WS 상태 브로드캐스트 | 콜백 인터페이스로 전환 가능 (중간) |
| 450 | `ws_subscribe_control.broadcast_ws_connection_status(True)` | G | _reconnect_loop() 재연결 성공 시 WS 상태 | 콜백 인터페이스로 전환 가능 (중간) |
| 503 | `engine_state.state.broker_rest_apis.get("kiwoom")` | C | _get_token_async() REST API 인스턴스 재사용 | 의존성 주입으로 전환 가능 (중간, P10) |
| 535 | `engine_state.state.integrated_system_settings_cache.get(...)` | B | create_kiwoom_connector() app_key/app_secret 읽기 | 의존성 주입으로 전환 가능 (낮음) |

### 3.2 ls_connector.py (14건)

| 줄 | 참조 대상 (services) | 유형 | 용도 | 제거 가능성 |
|----|---------------------|------|------|------------|
| 235 | `engine_symbol_utils._base_stk_cd` | F | _convert_ls_to_internal() UH1 호가 종목코드 정규화 | 순수 함수 → core로 이동 가능 (낮음, P23) |
| 255 | `engine_symbol_utils._base_stk_cd` | F | _convert_ls_to_internal() UPH 프로그램매매 코드 정규화 | 순수 함수 → core로 이동 가능 (낮음, P23) |
| 381 | `engine_state.state.login_ok = True` | A | connect() 로그인 상태 설정 (LS는 소켓 연결=로그인) | 콜백 인터페이스로 전환 가능 (중간) |
| 383 | `engine_state._notify_reg_ack()` | H | connect() REG ACK 대기 해제 (LS 전용) | 콜백 인터페이스로 전환 가능 (중간) |
| 386 | `daily_time_scheduler._trigger_reg_pipeline()` | H | connect() REG 파이프라인 트리거 (LS 전용) | 콜백 인터페이스로 전환 가능 (중간) |
| 403 | `ws_subscribe_control.broadcast_ws_connection_status(True)` | G | connect() WS 상태 브로드캐스트 | 콜백 인터페이스로 전환 가능 (중간) |
| 421 | `ws_subscribe_control.broadcast_ws_connection_status(False)` | G | disconnect() WS 상태 브로드캐스트 | 콜백 인터페이스로 전환 가능 (중간) |
| 650 | `engine_state.state.login_ok = False` | A | _on_socket_disconnect() 로그인 상태 초기화 | 콜백 인터페이스로 전환 가능 (중간) |
| 655 | `ws_subscribe_control.broadcast_ws_connection_status(False)` | G | _on_socket_disconnect() WS 상태 브로드캐스트 | 콜백 인터페이스로 전환 가능 (중간) |
| 699 | `engine_state.state.login_ok = True` | A | _reconnect_loop() 재연결 성공 시 로그인 상태 | 콜백 인터페이스로 전환 가능 (중간) |
| 716 | `ws_subscribe_control.broadcast_ws_connection_status(True)` | G | _reconnect_loop() 재연결 성공 시 WS 상태 | 콜백 인터페이스로 전환 가능 (중간) |
| 776 | `engine_symbol_utils._base_stk_cd` | F | _format_code() LS 형식 변환 전 베이스 코드 추출 | 순수 함수 → core로 이동 가능 (낮음, P23) |
| 787 | `engine_state.state.broker_rest_apis.get("ls")` | C | _get_token_async() REST API 인스턴스 재사용 | 의존성 주입으로 전환 가능 (중간, P10) |
| 825 | `engine_state.state.integrated_system_settings_cache.get(...)` | B | create_ls_connector() app_key/app_secret 읽기 | 의존성 주입으로 전환 가능 (낮음) |

### 3.3 기타 core 파일 역참조 (부수적)

| 파일 | 줄 | 참조 대상 | 유형 | 비고 |
|------|----|----------|------|------|
| `broker_router.py` | 64, 96 | `engine_state.state.integrated_system_settings_cache` | B | BrokerRouter 생성 시 설정 읽기 — 팩토리·라우터는 설정 기반 구성이 본질 |
| `connector_manager.py` | 39 | `engine_state.state.integrated_system_settings_cache["broker_config"]` | B | _build() 시 설정 읽기 — 본질적 |
| `connector_manager.py` | 111 | `engine_ws_reg.restore_subscriptions_after_reconnect` | D | 재연결 복원 — services 오케스트레이션 위임 (정방향에 가까움) |
| `kiwoom_providers.py` | 32 | `engine_state.state.broker_rest_apis` | C | AuthProvider 생성 시 REST API 재사용/초기화 |
| `ls_providers.py` | 20 | `engine_state.state.broker_rest_apis` | C | AuthProvider 생성 시 REST API 재사용/초기화 |
| `kiwoom_account_parsing.py` | 12 | `engine_symbol_utils._base_stk_cd, _real_item_stk_cd` | F | 키움 REST/REAL04 파싱 — 순수 함수 역참조 |
| `kiwoom_account_parsing.py` | 13 | `engine_ws_parsing._parse_fid10_price` | F | 키움 REAL04 가격 파싱 — 순수 함수 역참조 |
| `kiwoom_order.py` | 63 | `daily_time_scheduler.get_nxt_trde_tp` | H | NXT 장외 시간대 trde_tp 조정 — 스케줄러 시간표 기반 |
| `engine_settings.py` | 109 | `engine_state.state.integrated_system_settings_cache._credential_states` | B | 자격증명 상태 조회 |
| `journal.py` | 19 | `engine_utils.LazyLock` | F | 지연 락 유틸 |
| `sector_mapping.py` | 24 | `engine_state.state.master_stocks_cache` | A | 업종 매핑 시 종목 캐시 조회 |
| `stock_classification_data.py` | 37, 71, 122 | `engine_state.state.master_stocks_cache` | A | 종목 분류 데이터 로드 |
| `settings_store.py` | 21 | `auto_trading_effective` | F | 설정 저장 시 자동매매 유효성 검증 |

### 3.4 역참조 유형 분류

| 유형 | 설명 | 건수 | 핵심 특성 |
|------|------|------|----------|
| A | 상태 동기화 (state.login_ok, state.master_stocks_cache) | 8 | 연결 생명주기 이벤트 — 단일 진실 소유는 engine_state |
| B | 설정 읽기 (state.integrated_system_settings_cache) | 5 | 팩토리·라우터·커넥터 생성 시 API 키·broker_config |
| C | 토큰/REST API 재사용 (state.broker_rest_apis) | 4 | 중복 발급 방지 — P10 SSOT 목적 |
| D | REG/UNREG 전송 + ACK 대기 (engine_ws._ws_send_*) | 6 | 키움만 — reg_seq_lock + reg_ack_event + 10초 타임아웃 |
| E | 키움 REG 페이로드 빌더 (engine_ws_reg.build_*) | 5 | 키움만 — 키움 규격이 공통 services에 침투 (P4 위반 후보) |
| F | 순수 함수 유틸 (engine_symbol_utils, engine_ws_parsing, engine_utils) | 8 | 상태 의존성에 따라 이동 가능/불가 분리 |
| G | WS 상태 브로드캐스트 (ws_subscribe_control.broadcast_ws_connection_status) | 6 | 상태 변경 게이트 내장 — 중복 전송 방지 (P10) |
| H | LS 전용 로그인 후처리 (_notify_reg_ack + _trigger_reg_pipeline + get_nxt_trde_tp) | 3 | LS는 소켓 연결=로그인, 키움은 LOGIN 단계 분리 |

---

## 4. 아키텍처 원칙 점검

### 4.1 P4 (증권사명 공통 침투 금지)

- **위반 후보 1건**: `engine_ws_reg.py`에 키움 전용 REG 페이로드 빌더 5종(`build_0b_reg_payloads`/`build_0b_remove_payloads`/`build_0d_reg_payloads`/`build_0d_remove_payloads`/`build_index_reg_payload`)이 공통 services에 위치. 키움 규격(grp_no="4"/"7"/"2", refresh="0"/"1", type=["0B"]/["0D"]/["0J"])이 services 계층에 침투.
  - 단, `build_account_reg_payload`는 키움 계좌(00/04) 전용이나 services에 위치.
  - LS는 자체 페이로드 조립(`header`/`body` 구조)을 `ls_connector.py` 내부 `_convert_ls_to_internal`에 캡슐화 → P4 준수.
- **준수 확인**: 공통 로직(`broker_connector.py`·`broker_providers.py`·`broker_registry.py`·`broker_factory.py`·`broker_router.py`·`connector_manager.py`)에 `kiwoom_`/`ls_` 접두사 침투 0건. 증권사별 코드는 `core/kiwoom_*.py`·`core/ls_*.py`에 분리.
- **판정**: 즉시 P4 위반으로 단정하지 않음. 키움 REG 빌더 이동은 별도 승인 시 검토 (개선 후보 1).

### 4.2 P10 (SSOT)

- **state.login_ok**: 단일 소유(engine_state). 5곳 갱신(kiwoom_connector 1, ls_connector 3, engine_lifecycle, engine_loop, engine_ws_dispatch)이나 단일 진실 소스 유지. 역참조는 "갱신만" 수행 → P10 준수.
- **state.ws_connection_status**: 단일 소유. `broadcast_ws_connection_status()`가 상태 변경 게이트 역할(`if state.ws_connection_status == connected: return`) → 중복 전송 방지. P10 준수.
- **state.broker_rest_apis**: 단일 소유. engine_loop에서 초기화(engine_loop.py:259), providers/connector가 재사용만. 중복 토큰 발급 방지 → P10 준수.
- **state.integrated_system_settings_cache**: 단일 소유. 팩토리·라우터·커넥터가 읽기만. P10 준수.
- **키움 REG 페이로드 빌더**: services에 단일 소스로 존재 → SSOT 측면은 준수. 단, 계층 분리 측면 위반 (P23).

### 4.3 P16 (살아있는 경로)

- 모든 역참조는 실제 호출 경로. dead code 0건.
- `try/except`로 감싼 역참조도 "실패 시에도 연결은 유지"하는 살아있는 경로 (P25 격리).
- `create_kiwoom_connector()`·`create_ls_connector()` 팩토리는 `CONNECTOR_REGISTRY` 경유로 `ConnectorManager._create_single()`에서 호출 → 살아있는 경로.

### 4.4 P20 (폴백 금지)

- **준수 확인**: 역참조 호출부의 `try/except`는 "폴백"이 아니라 "격리된 실패(P25)".
  - `kiwoom_connector.py:242-245`: `broadcast_ws_connection_status(True)` 실패 시 `logger.warning` 후 연결은 유지 → 상태 전송 실패를 연결 실패로 덮지 않음.
  - `ls_connector.py:381-389`: `state.login_ok=True` + `_notify_reg_ack()` + `_trigger_reg_pipeline()`를 한 try 블록에서 감쌈 → 세 가지가 함께 실패해도 소켓 연결 자체는 유지. 단, 로그인 상태가 설정되지 않으면 후속 REG 파이프라인이 실행되지 않음 → "로그인 성공"의 의미가 약화될 수 있으나, 재연결 루프에서 복구 가능.
- **silent `except: pass` 0건**: 모든 except 블록이 `logger.warning(..., exc_info=True)`로 로깅.

### 4.5 P23 (계층 일관성)

- **위반 (본 C-06 핵심)**: core가 services를 import → 의존 방향 역전. 33건 역참조.
- **세부 위반 패턴**:
  - (a) 커넥터가 엔진 상태를 직접 갱신 (state.login_ok) — 연결 생명주기 이벤트가 커넥터에서 발생하므로 구조적 불가피성 존재.
  - (b) 커넥터가 WS 오케스트레이션 함수 직접 호출 (engine_ws._ws_send_*, ws_subscribe_control.broadcast_*) — ACK 프로토콜·상태 브로드캐스트가 services에 캡슐화됨.
  - (c) 키움 규격이 services에 침투 (engine_ws_reg.build_*) — P4와 교차 위반.
  - (d) 순수 함수가 services에 위치 (engine_symbol_utils._base_stk_cd, engine_ws_parsing._parse_fid10_price) — core에서도 필요한 순수 함수가 services에 있어 역참조 발생.
- **일관성 관찰**: 키움·LS 커넥터 구조가 거의 동일(내부 소켓 클래스 + 커넥터 클래스 + 팩토리) → 패턴 일관성 유지. 단, 키움만 ACK 대기/REMOVE fire-and-forget 분리, LS는 ACK 미지원(`supports_ack=False`).

### 4.6 P24 (단순성)

- **중복 최소화**: 키움·LS 커넥터 구조 유사 → 중복 제거됨. 단, 키움 REG 빌더 5종이 services에, LS 변환 로직이 core에 분산 → 비대칭.
- **불필요한 추상화**: `BrokerConnector` ABC의 기본 구현(`subscribe_dynamic`/`unsubscribe_dynamic`/`subscribe_index`/`subscribe_stocks`/`unsubscribe_stocks`/`send_message`가 `return False`/`pass`)은 커넥터가 오버라이드 → 살아있는 경로.
- **함수 길이**: `ls_connector.py` 832줄 (500줄 초과, C-09 범위와 중복). `kiwoom_connector.py` 540줄 (500줄 초과). 분할 검토 대상이나 본 세션 범위 외.

### 4.7 P25 (격리된 실패)

- **준수 확인**: 모든 역참조 호출이 `try/except + logger.warning(exc_info=True)`로 격리.
  - 커넥터 연결/재연결 실패가 엔진 전체를 중단하지 않음.
  - `ConnectorManager.connect_all()`이 `asyncio.gather(..., return_exceptions=True)`로 각 커넥터 독립 격리.
  - `ConnectorManager._build()`에서 개별 커넥터 생성 실패 시 `ValueError`를 `logger.warning`으로 격리 후 다음 커넥터 생성 계속.
- **재연결 루프 격리**: 키움 10회/LS 20회 지수 백오프 (1→2→4→8→16→32초). 최대 횟수 초과 시 `logger.error` 후 중단 → 엔진 루프는 계속.

---

## 5. 핵심 발견

### 5.1 역참조의 구조적 불가피성

커넥터는 "연결 생명주기 이벤트 발생 주체"이나, "엔진 상태·WS 오케스트레이션"은 services에 캡슐화됨. 이 분리 자체가 역참조를 발생시킴.

- **state.login_ok 갱신**: 연결/해제/재연결 이벤트는 커넥터 내부에서 발생 → 커넥터가 state를 갱신해야 함. ConnectorManager가 외부에서 감지하기 어려움(재연결 루프는 커넥터 내부 태스크).
- **broadcast_ws_connection_status**: 연결 상태 변화를 UI에 통지하는 단일 게이트. 커넥터가 직접 호출하는 것이 가장 빠름. ConnectorManager 경유 시 재연결 루프 내 이벤트 전파 경로가 복잡해짐.
- **LS 전용 로그인 후처리**: LS는 소켓 연결=로그인(별도 LOGIN 단계 없음) → connect() 완료 시점에 _notify_reg_ack + _trigger_reg_pipeline을 즉시 호출해야 함. 키움은 LOGIN 응답을 engine_ws_dispatch에서 처리 → 커넥터가 후처리할 필요 없음.

### 5.2 키움 vs LS 비대칭

| 항목 | 키움 | LS |
|------|------|-----|
| LOGIN 단계 | 별도 (LOGIN 메시지 → 응답) | 없음 (소켓 연결=로그인) |
| ACK 프로토콜 | supports_ack=True, _ws_send_reg_unreg_and_wait_ack 사용 | supports_ack=False, fire-and-forget |
| REG 페이로드 빌더 | services/engine_ws_reg.build_* (역참조) | ls_connector 내부 조립 (P4 준수) |
| 로그인 후처리 | engine_ws_dispatch에서 (커넥터 외부) | ls_connector.connect()에서 직접 (역참조 H) |
| 재연결 횟수 | 10회 | 20회 |
| 메시지 변환 | 키움 REAL 형식 그대로 | _convert_ls_to_internal (LS→내부 변환) |

비대칭은 증권사 API 명세 차이에서 발생. 키움은 ACK 기반 순차 전송, LS는 fire-and-forget. 이 차이가 역참조 패턴 차이를 만듦.

### 5.3 순수 함수의 계층 위치 문제

`engine_symbol_utils._base_stk_cd` (순수 함수, 상태 의존 0)와 `engine_ws_parsing._parse_fid10_price` (순수 함수)는 core에서도 필요 → services에 있어 역참조 발생.

- `_base_stk_cd`: 6자리 종목코드 정규화 (_AL/_NX 접미사 제거). 순수 함수 → core로 이동 가능.
- `get_ws_subscribe_code`: `_base_stk_cd` + `is_nxt_enabled()` (state.master_stocks_cache 조회) → 상태 의존 → 이동 불가.
- `_parse_fid10_price`: REAL values에서 가격 추출. 순수 함수 → core로 이동 가능.

이동 시 `engine_symbol_utils`·`engine_ws_parsing`의 다른 함수들이 state 의존하므로, 순수 함수만 별도 모듈(`core/symbol_utils.py` 등)로 분리해야 함 → 중간 작업량.

### 5.4 키움 REG 빌더의 P4/P23 교차 위반

`engine_ws_reg.py`의 키움 REG 빌더 5종은 키움 규격(grp_no, refresh, type)을 services에 침투시킴.

- 키움 커넥터만 호출 → 사실상 키움 전용.
- LS는 자체 페이로드 조립 → 빌더 미사용.
- 이동 대상: `core/kiwoom_ws_reg.py` (신규)로 이동 시 키움 커넥터가 core 내부 참조로 전환 → 역참조 5건 제거.
- 단, `engine_ws_reg.py`의 구독 함수(`subscribe_sector_stocks_0b` 등)는 state 기반 → services에 잔류.

### 5.5 ConnectorManager의 하이브리드 위치

`connector_manager.py`는 core에 위치하나:
- `_build()`에서 `state.integrated_system_settings_cache` 읽기 (역참조 B)
- `_on_reconnect_success()`에서 `engine_ws_reg.restore_subscriptions_after_reconnect` 호출 (역참조 D)

ConnectorManager는 "다중 커넥터 관리"라는 core 책임과 "엔진 상태 기반 구독 복원"이라는 services 책임을 혼합. 전자는 core, 후자는 services가 본질 → ConnectorManager 자체가 계층 경계에 위치.

---

## 6. 개선 후보 (우선순위 낮음~중간)

> 본 세션은 조사만 수행. 개선 적용은 별도 승인 후 진행.

### 6.1 (낮음, P4/P23) 키움 REG 페이로드 빌더 이동

- **대상**: `engine_ws_reg.build_0b_reg_payloads`/`build_0b_remove_payloads`/`build_0d_reg_payloads`/`build_0d_remove_payloads`/`build_index_reg_payload`/`build_account_reg_payload`
- **이동처**: `core/kiwoom_ws_reg.py` (신규)
- **효과**: 키움 규격이 services에서 제거 → P4 준수. kiwoom_connector 역참조 5건(E) 제거.
- **위험**: 낮음. 빌더는 순수 함수(입력→페이로드 dict)이므로 이동 후 호출부 import 경로만 변경.
- **잔류**: `engine_ws_reg.py`의 구독 함수(`subscribe_sector_stocks_0b` 등)는 state 기반이므로 services에 잔류.
- **테스트 영향**: `test_engine_ws_reg.py` 146줄 중 빌더 테스트만 이동. `test_kiwoom_connector.py`의 patch 경로 변경.

### 6.2 (낮음, P23) 순수 함수 유틸 core로 이동

- **대상**: `engine_symbol_utils._base_stk_cd`, `engine_ws_parsing._parse_fid10_price` (외 순수 함수)
- **이동처**: `core/symbol_utils.py` (신규) 또는 기존 `core/` 유틸
- **효과**: kiwoom_account_parsing 역참조 2건, ls_connector 역참조 3건(F) 제거.
- **위험**: 낮음. 순수 함수 이동이나, 호출부가 다수(engine_ws_reg, engine_ws_dispatch, market_close_pipeline 등) → 전수 import 경로 변경 필요.
- **주의**: `get_ws_subscribe_code`/`is_nxt_enabled`/`get_stock_market`은 state 의존 → 이동 불가. 순수 함수만 분리.

### 6.3 (중간, P23) 연결 생명주기 콜백 인터페이스

- **대상**: `state.login_ok` 갱신, `broadcast_ws_connection_status` 호출
- **방안**: `BrokerConnector`에 `on_connected`/`on_disconnected`/`on_reconnected` 콜백 인터페이스 추가. ConnectorManager가 콜백을 등록하고, 콜백 내부에서 state 갱신·브로드캐스트 수행.
- **효과**: kiwoom 역참조 4건(A/G), ls 역참조 6건(A/G) 제거.
- **위험**: 중간. 커넥터 내부 재연결 루프에서 발생하는 이벤트를 ConnectorManager가 감지하려면 콜백이 커넥터 내부에서 호출되어야 함 → 콜백 등록 시점·순서 보장 필요. 재연결 루프 중 콜백 실패 시 격리(P25) 유지 필요.
- **단점**: 콜백 인터페이스 추가 → 추상화 증가. 단순성(P24)과 교차.

### 6.4 (중간, P23) LS 전용 로그인 후처리 콜백

- **대상**: ls_connector.py:381-389의 `state.login_ok=True` + `_notify_reg_ack()` + `_trigger_reg_pipeline()`
- **방안**: LS 커넥터 connect() 완료 후 `on_login_complete` 콜백 호출. ConnectorManager가 LS 전용 후처리를 콜백에서 수행.
- **효과**: ls 역참조 2건(H) 제거.
- **위험**: 중간. ConnectorManager가 LS 전용 후처리를 알아야 함 → 증권사별 특수성이 ConnectorManager로 침투 위험(P4). 단, 콜백 이름으로 추상화 시 P4 위험 완화.
- **대안**: LS 커넥터가 `supports_login_phase = False` 속성 노출 → ConnectorManager가 "로그인 단계 없는 커넥터" 후처리를 일반화.

### 6.5 (관찰, 현행 유지) state.broker_rest_apis 재사용

- **현황**: 커넥터·Provider가 동일 REST API 인스턴스 재사용 → 중복 토큰 발급 방지.
- **판정**: P10 SSOT 준수. 역참조이나 단일 진실 소스 유지 목적이므로 현행 유지 적합.
- **개선 시**: 의존성 주입(커넥터 생성 시 rest_api 인자 전달)으로 전환 시 역참조 4건(C) 제거 가능. 단, engine_loop 초기화 순서(broker_rest_apis 생성 시점)와 커넥터 생성 시점의 의존성을 명시적으로 관리해야 함 → 중간 작업량.

---

## 7. 변경 금지 항목

1. **state.login_ok 단일 소유** (engine_state) — 5곳 갱신이나 단일 진실 소스. 역참조 제거 시에도 갱신 주체는 단일화 유지.
2. **state.broker_rest_apis 재사용 패턴** — 중복 토큰 발급 방지 (P10). engine_loop 초기화 1곳 + 재사용 5곳.
3. **broadcast_ws_connection_status 상태 변경 게이트** — `if state.ws_connection_status == connected: return`으로 중복 전송 방지 (P10).
4. **키움 ACK 대기 프로토콜** (`_ws_send_reg_unreg_and_wait_ack`) — `reg_seq_lock` + `reg_ack_event` + 10초 타임아웃 + `REG_POST_ACK_GAP_SEC` 0.35초. 키움 서버 규격.
5. **LS 소켓 연결=로그인 의미론** — LS는 별도 LOGIN 단계 없음. connect() 완료=로그인 완료.
6. **커넥터 내부 재연결 루프의 지수 백오프** — 키움 10회/LS 20회. 1→2→4→8→16→32초.
7. **Producer-Consumer Queue 누락 정책** — 큐 가득 시 가장 오래된 데이터 폐기(`get_nowait` + `put_nowait`). 최신 데이터 유지.
8. **try/except + logger.warning(exc_info=True) 격리 패턴** — P25 일관성. silent except 0건.
9. **CONNECTOR_REGISTRY 지연 로딩** — `_LazyBrokerRegistry`로 순환 import 방지. 최초 접근 시 로더 실행.
10. **ConnectorManager.connect_all()의 asyncio.gather(return_exceptions=True)** — 각 커넥터 독립 격리.

---

## 8. 테스트 커버리지

### 8.1 커넥터 테스트 (역참조 patch 전수 커버)

| 테스트 파일 | 줄 수 | 역참조 patch 건수 | 비고 |
|------------|-------|------------------|------|
| `test_kiwoom_connector.py` | 970 | 32 | broadcast_ws_connection_status 5, _ws_send_* 11, build_*_payloads 6, get_ws_subscribe_code 6, 기타 4 |
| `test_ls_connector.py` | 1077 | 19 | _base_stk_cd 9, broadcast_ws_connection_status 5, _notify_reg_ack 1, _trigger_reg_pipeline 1, 기타 3 |
| `test_kiwoom_providers.py` | 291 | (별도) | state.broker_rest_apis 재사용 패턴 |
| `test_ls_providers.py` | 279 | (별도) | state.broker_rest_apis 재사용 패턴 |
| `test_connector_manager.py` | 560 | (별도) | 다중 커넥터 라우팅·재연결 복원 |
| `test_broker_router.py` | 341 | (별도) | Provider 매핑·검증 |

### 8.2 services 측 테스트

| 테스트 파일 | 줄 수 | 비고 |
|------------|-------|------|
| `test_engine_ws.py` | 475 | _ws_send_reg_unreg_and_wait_ack, _ws_send_remove_fire_and_forget |
| `test_engine_ws_reg.py` | 146 | build_*_payloads, restore_subscriptions_after_reconnect |
| `test_engine_ws_parsing.py` | 294 | _parse_fid10_price 등 순수 함수 |
| `test_daily_time_scheduler.py` | (대형) | _trigger_reg_pipeline 4건 |

### 8.3 테스트 patch 패턴 관찰

- 커넥터 테스트는 services 역참조를 `patch("backend.app.services.<module>.<func>", MagicMock()/AsyncMock())`로 전수 모킹 → 역참조 결합도가 테스트에 명시.
- 역참조 제거 시 patch 경로 변경 필요 → 테스트 수정 비용 발생.
- 단, 순수 함수 이동(6.2) 시 patch 경로 변경만으로 테스트 유지 가능.

---

## 9. 검증

- **코드 수정 없음** → 런타임 검증(테스트·RuntimeWarning 기동) 생략.
- **정적 대조**:
  - `core/` 디렉터리 `services` 키워드 grep → 50건 식별 (역참조 33건 + 주석/docstring 17건).
  - 역참조 33건 분류: kiwoom_connector 19건, ls_connector 14건.
  - 부수적 역참조 17건: broker_router 2, connector_manager 2, kiwoom_providers 1, ls_providers 1, kiwoom_account_parsing 2, kiwoom_order 1, engine_settings 1, journal 1, sector_mapping 1, stock_classification_data 3, settings_store 1, engine_settings 1.
  - 테스트 patch 패턴 grep → 60건 이상 식별 (커넥터 테스트 51건 + services 테스트 9건+).
- **P4 점검**: 공통 로직(`broker_connector.py` 등 6파일)에 `kiwoom_`/`ls_` 접두사 침투 0건. 키움 REG 빌더의 services 침투 1건(위반 후보).
- **P10 점검**: state.login_ok/ws_connection_status/broker_rest_apis/integrated_system_settings_cache 단일 소유 확인.
- **P16 점검**: dead code 0건. 모든 역참조 실제 호출 경로.
- **P20 점검**: silent `except: pass` 0건. 모든 except `logger.warning(exc_info=True)`.
- **P25 점검**: 모든 역참조 try/except 격리. ConnectorManager.gather(return_exceptions=True).

---

## 10. 결론

C-06 역참조는 33건(키움 19 + LS 14)으로 광범위하나, 대부분 "연결 생명주기 이벤트"와 "ACK 프로토콜"이라는 구조적 불가피성에서 발생. P10/P16/P20/P25는 준수. P4/P23 위반은 키움 REG 빌더 1건(낮은 위험 이동 가능)과 계층 분리 자체(구조적).

개선 후보 5건 식별:
1. 키움 REG 빌더 이동 (낮음, P4/P23) — 1순위 권장.
2. 순수 함수 유틸 core 이동 (낮음, P23).
3. 연결 생명주기 콜백 인터페이스 (중간, P23).
4. LS 전용 로그인 후처리 콜백 (중간, P23).
5. state.broker_rest_apis 재사용 (현행 유지 적합).

후속 개선은 5개 후보 중 1개만 별도 승인 후 진행 권장. 1순위: 키움 REG 빌더 이동 (낮은 위험, P4/P23 동시 개선).
