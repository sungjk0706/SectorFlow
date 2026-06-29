# HANDOVER — SectorFlow

## 완료 단계

### 아키텍처 최적화 (2026-06-30 완료, 커밋 `2abb184`)
- **uvloop 도입**: `main.py:65`에 `loop="uvloop"` 설정 — C 기반 libuv 이벤트 루프로 콜백 디스패치 속도 2-4x 향상
- **PYTHONASYNCIODEBUG 명시적 비활성화**: `main.py:10`에 `os.environ.pop("PYTHONASYNCIODEBUG", None)` — 디버그 모드 오염 방지
- **SQLite mmap_size PRAGMA 추가**: `database.py:27`에 `PRAGMA mmap_size = 268435456` (256MB) — DB 읽기 시 디스크 I/O 대신 메모리 매핑
- **Compute Loop task 오버헤드 제거**: `pipeline_compute.py:164-167` — 매 틱마다 `asyncio.ensure_future()` 2개 생성 + `asyncio.wait()` + cancel하던 패턴을 `asyncio.wait_for(timeout=0.5)` + `get_nowait()` 드레인으로 교체. task 생성/소멸 오버헤드 제거
  - **주의**: `asyncio.timeout()`은 uvloop에서 호환되지 않음 (`TypeError: 'Timeout' object does not support the context manager protocol`). `asyncio.wait_for()` 사용 필수
- **tracemalloc 메모리 모니터링 추가**: `backend/app/core/memory_monitor.py` 신규 파일 — 앱 시작 시 tracemalloc 활성화, 장마감/앱 종료 시 상위 10개 할당 지점 로그 출력. 성능 영향 없음

## 현재 상태
- 앱 정상 기동 확인 (uvloop 적용, tracemalloc 로그 출력 확인됨)
- 종목수 1359 → 1361 불일치 조사는 이전 세션에서 진행 중이었으나, 현재 우선순위 낮음

## 미해결 문제
- **TODO 주석 7건**: `deps.py:16`, `ws.py:159`, `ws_orders.py:23`, `ws_settings.py:23`, `client.ts:18,29,40,66`, `risk_manager.py:64`
- **종목수 불일치**: `_apply_confirmed_to_memory`에서 새 엔트리 생성 의심 (이전 세션 조사)

## 개선 필요 영역 (ARCHITECTURE.md 기반)

### 1. 단일 종목 비중 한도 미구현
- **현상**: `risk_manager.py:64`에 TODO 주석 존재, `max_single_stock_exposure` 로직 미구현
- **위치**: `backend/app/services/risk_manager.py` — `RiskManager.check_buy_order_allowed()`
- **영향**: 단일 종목에 과도한 자금 집중 가능
- **관련 파일**: `risk_manager.py`, `account_manager.py`, `engine_state.py`

### 2. 리스크 임계치 하드코딩
- **현상**: `max_daily_loss_limit = -500000`, `max_total_exposure_ratio = 0.95` 등이 하드코딩
- **위치**: `backend/app/services/risk_manager.py` — `RiskManager.__init__()`
- **영향**: 사용자가 리스크 한도를 설정 UI에서 변경 불가
- **관련 파일**: `risk_manager.py`, `settings_defaults.py`, `settings_store.py`, `engine_settings.py`

### 3. 다중 증권사 WS 동시 구독 로드밸런싱
- **현상**: `ConnectorManager`로 다중 증권사 WS 연결은 지원되나, 구독 분산 최적화 미구현
- **위치**: `backend/app/core/connector_manager.py`, `backend/app/services/engine_ws_reg.py`
- **영향**: 종목 구독이 단일 증권사에 집중 시 WS 세션 한도 도달 가능
- **관련 파일**: `connector_manager.py`, `engine_ws_reg.py`, `kiwoom_connector.py`, `ls_connector.py`

### 4. 프론트엔드 프레임워크 검토
- **현상**: Vanilla TypeScript로 구현, 컴포넌트 재사용성 및 상태관리 한계
- **위치**: `frontend/src/` 전체
- **영향**: 페이지 간 공통 로직 중복, 상태 동기화 복잡도 증가
- **관련 파일**: `frontend/src/binding.ts`, `frontend/src/stores/`, `frontend/src/pages/`

### 5. 백업/복구 자동화
- **현상**: `stocks.db` 수동 백업만 가능, 자동 백업 스크립트 없음
- **위치**: `backend/data/stocks.db` (단일 파일)
- **영향**: DB 손상 시 복구 불가
- **관련 파일**: `SectorFlow.command`, `backend/app/db/database.py`

### 6. 테스트 자동화 부재
- **현상**: 수동 테스트만 수행, pytest 기반 단위/통합 테스트 없음
- **위치**: `backend/` 전체 (테스트 디렉토리 없음)
- **영향**: 코드 변경 시 회귀 위험, 안전장치 검증 불가
- **관련 파일**: `backend/app/domain/`, `backend/app/services/risk_manager.py`, `backend/app/services/settlement_engine.py`
