# HANDOVER — SectorFlow

## 현재 상태
- **종목수 1359 → 1361 불일치 조사 진행 중**
  - 실시간 테이블 비어있음 원인 확인 완료: `engine_snapshot.py:219-225`의 `_reset_realtime_fields()`가 정상 동작 (아키텍처 부합)
  - 종목수 불일치 원인 조사 중: `_apply_confirmed_to_memory`에서 새 엔트리 생성 의심, `_save_confirmed_cache`의 eligible_codes 전달 여부 확인 필요

## 미해결 문제
- **TODO 주석 7건**: `deps.py:16`, `ws.py:159`, `ws_orders.py:23`, `ws_settings.py:23`, `client.ts:18,29,40,66`, `risk_manager.py:64`

## 개선 필요 영역 (ARCHITECTURE.md 기반 — 다음 세션에서 정밀조사 후 수정)

### 1. 단일 종목 비중 한도 미구현
- **현상**: `risk_manager.py:64`에 TODO 주석 존재, `max_single_stock_exposure` 로직 미구현
- **위치**: `backend/app/services/risk_manager.py` — `RiskManager.check_buy_order_allowed()`
- **영향**: 단일 종목에 과도한 자금 집중 가능 (아키텍처 원칙상 필요한 안전장치)
- **조사 필요**: `position_manager` 또는 `_positions` 연동 방법, 노출액 계산 로직
- **관련 파일**: `risk_manager.py`, `account_manager.py`, `engine_state.py` (`_positions`)

### 2. 리스크 임계치 하드코딩
- **현상**: `max_daily_loss_limit = -500000`, `max_total_exposure_ratio = 0.95` 등이 하드코딩
- **위치**: `backend/app/services/risk_manager.py` — `RiskManager.__init__()`
- **영향**: 사용자가 리스크 한도를 설정 UI에서 변경 불가
- **조사 필요**: `settings_defaults.py`에 리스크 관련 설정 키 추가, `settings_store.py` 검증 로직, 프론트엔드 설정 UI 추가 여부
- **관련 파일**: `risk_manager.py`, `settings_defaults.py`, `settings_store.py`, `engine_settings.py`

### 3. 다중 증권사 WS 동시 구독 로드밸런싱
- **현상**: `ConnectorManager`로 다중 증권사 WS 연결은 지원되나, 구독 분산 최적화 미구현
- **위치**: `backend/app/core/connector_manager.py`, `backend/app/services/engine_ws_reg.py`
- **영향**: 종목 구독이 단일 증권사에 집중 시 WS 세션 한도 도달 가능
- **조사 필요**: 현재 구독 분배 로직 확인, 세션 한도 per 증권사, 로드밸런싱 전략 수립
- **관련 파일**: `connector_manager.py`, `engine_ws_reg.py`, `kiwoom_connector.py`, `ls_connector.py`

### 4. 프론트엔드 프레임워크 검토
- **현상**: Vanilla TypeScript로 구현, 컴포넌트 재사용성 및 상태관리 한계
- **위치**: `frontend/src/` 전체
- **영향**: 페이지 간 공통 로직 중복, 상태 동기화 복잡도 증가
- **조사 필요**: React/Svelte 마이그레이션 비용-편익 분석, 현재 `binding.ts` + `stores/` 구조의 유지보수성 평가
- **관련 파일**: `frontend/src/binding.ts`, `frontend/src/stores/`, `frontend/src/pages/`

### 5. 백업/복구 자동화
- **현상**: `stocks.db` 수동 백업만 가능, 자동 백업 스크립트 없음
- **위치**: `backend/data/stocks.db` (단일 파일)
- **영향**: DB 손상 시 복구 불가 (거래 이력, 설정, 가상 포지션 등 전체 유실)
- **조사 필요**: 일일 자동 백업 스크립트 작성, 백업 보관 기간, 복구 절차 문서화
- **관련 파일**: `SectorFlow.command`, `backend/app/db/database.py`

### 6. 모니터링 시스템 부재
- **현상**: 로그 기반 모니터링만 존재, 메모리/지연/에러 통계 대시보드 없음
- **위치**: 백엔드 전체
- **영향**: 장시간 구동 시 메모리 누수, 지연 스파이크 감지 어려움
- **조사 필요**: `tracemalloc` 기반 메모리 샘플링 구현, 지연 통계 수집, `/api/status` 확장 여부
- **관련 파일**: `engine_ws_dispatch.py` (`_check_realtime_latency`), `engine_state.py`, `status.py`

### 7. 테스트 자동화 부재
- **현상**: 수동 테스트만 수행, pytest 기반 단위/통합 테스트 없음
- **위치**: `backend/` 전체 (테스트 디렉토리 없음)
- **영향**: 코드 변경 시 회귀 위험, 안전장치 검증 불가
- **조사 필요**: 핵심 로직(업종 점수 계산, 매수/매도 게이트, 정산 엔진) 우선 테스트 작성, `conftest.py` 설정
- **관련 파일**: `backend/app/domain/` (순수 계산 로직), `backend/app/services/risk_manager.py`, `backend/app/services/settlement_engine.py`
