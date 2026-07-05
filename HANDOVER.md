# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-06: 개발 완료 전 최종 점검 완료**
  - `pytest-cov`, `pytest-timeout` 설치 및 `pytest.ini`에 `timeout = 30` 추가
  - `requirements.txt`에 Test 섹션 추가 (pytest-cov, pytest-timeout)
  - 테스트 커버리지 측정: **전체 14%** (13833줄 중 1981줄 커버). 핵심 도메인 영역은 고커버리지: `sector_calculator.py` 97%, `sector_score.py` 100%, `sector_filter.py` 96%, `models.py` 100%, `settings_file.py` 70%, `trade_mode.py` 79%, `engine_state.py` 82%, `database.py` 88%. 미커버 파일들은 WS 엔진/브로커 커넥터/Web 라우트 등 I/O 계층
  - ESLint `no-explicit-any` 21개 경고 **전부 제거** (0 warnings):
    - `event.ts`: file-level eslint-disable 추가 (자동생성 protobuf 코드)
    - `ws.ts`: `EventHandler<T = any>` → `EventHandler<T = unknown>`, `onEvent` 제네릭 정리
    - `data-table.ts`: `CellWithPrevContent`, `RowWithKey` 인터페이스 도입, `rowKeyStore` 미사용 변수 제거
    - `virtual-scroller.ts`: `CellWithPrevContent` 인터페이스 도입
    - `canvas-profit-chart.ts`: `typeof ResizeObserver` 체크로 변경
    - `main.ts`: `declare global { Window.uiStore }` 확장
    - `stock-classification.ts`: `StockClassificationState['allStocks']` 타입 적용
    - `hotStore.ts`: `nullifyFields`를 `Record<string, unknown>` 기반으로 수정
  - 검증: tsc passed, vitest 109 passed, eslint 0 warnings (0 errors)

## 현재 상태
- **백엔드**: ruff all passed, mypy passed, pytest 108 passed, pytest-timeout 30s 적용, pytest-cov 설치됨 (전체 커버리지 14%)
- **프론트엔드**: tsc passed, vitest 109 passed, eslint 0 warnings (0 errors)
- **Git**: 커밋 푸시 완료

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 테스트모드 매수/매도 시 체결가 로그에서 슬리피지 적용 확인 (예: 70,000원 매수 → 70,100원 체결)
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현
- **테스트 커버리지 개선**: 아래 우선순위별 진행

## 미해결 문제
- 없음

## 개선 필요 영역 — 테스트 커버리지

### 현재 커버리지: 14% (13,833줄 중 1,981줄 커버)

### 고커버리지 영역 (유지)
- `sector_score.py` 100%, `models.py` 100%, `settings_defaults.py` 100%
- `sector_calculator.py` 97%, `sector_filter.py` 96%
- `test_dry_run_fill_event.py` 95%, `test_sector_calculator.py` 100%
- `database.py` 88%, `engine_state.py` 82%, `trade_mode.py` 79%
- `settings_file.py` 70%, `engine_utils.py` 68%

### 테스트 부족 영역 (우선순위별)

#### Priority 1 — 매매 핵심 로직 (0% 커버, 즉시 필요)
- `trading.py` (415줄, 12%) — 자동매매 실행 로직
- `buy_order_executor.py` (83줄, 10%) — 매수 주문 실행
- `buy_filter.py` (106줄, 0%) — 1차 종목 필터링
- `risk_manager.py` (71줄, 24%) — 리스크 관리
- `circuit_breaker.py` (50줄, 26%) — 서킷브레이커
- `settlement_engine.py` (124줄, 36%) — 정산 엔진

#### Priority 2 — 엔진/WS 계층 (0% 커버, 중기)
- `engine_ws_dispatch.py` (299줄, 0%) — WS 메시지 분기 + 0J REAL 감지
- `engine_account_notify.py` (316줄, 0%) — WS 브로드캐스트
- `engine_ws_parsing.py` (144줄, 12%) — WS 파싱
- `engine_ws_reg.py` (218줄, 0%) — WS 등록
- `engine_ws.py` (157줄, 17%) — WS 엔진
- `engine_account.py` (250줄, 20%) — 계좌 엔진
- `engine_account_rest.py` (203줄, 14%) — 계좌 REST
- `engine_symbol_utils.py` (106줄, 28%) — 심볼 유틸

#### Priority 3 — 파이프라인/스케줄러 (0% 커버, 중기)
- `market_close_pipeline.py` (712줄, 0%) — 장마감 파이프라인
- `pipeline_compute.py` (344줄, 0%) — 파이프라인 연산
- `pipeline_gateway.py` (86줄, 0%) — 파이프라인 게이트웨이
- `daily_time_scheduler.py` (601줄, 0%) — 시간 기반 스케줄러
- `data_manager.py` (136줄, 14%) — 데이터 관리

#### Priority 4 — 브로커 커넥터 (0% 커버, 장기)
- `kiwoom_connector.py` (416줄, 0%), `kiwoom_rest.py` (403줄, 0%), `kiwoom_order.py` (65줄, 0%), `kiwoom_providers.py` (146줄, 0%), `kiwoom_stock_rest.py` (235줄, 0%)
- `ls_connector.py` (528줄, 0%), `ls_rest.py` (305줄, 0%), `ls_providers.py` (98줄, 0%)
- `connector_manager.py` (168줄, 0%)

#### Priority 5 — Web 라우트 (0% 커버, 장기)
- `app.py` (180줄, 0%), `ws.py` (111줄, 0%), `ws_manager.py` (214줄, 0%)
- `settings.py` (98줄, 0%), `stock_classification.py` (192줄, 0%), `status.py` (75줄, 0%)
- `auth.py` (29줄, 0%), `account.py` (3줄, 0%), `market.py` (9줄, 0%)

#### Priority 6 — 유틸/기타 (0% 커버, 장기)
- `telegram.py` (42줄, 0%), `telegram_bot.py` (321줄, 0%)
- `trade_history.py` (264줄, 15%), `dry_run.py` (208줄, 54%)
- `journal.py` (155줄, 26%), `logger.py` (152줄, 18%)
- `encryption.py` (57줄, 21%), `sector_mapping.py` (66줄, 45%)

### 다음 세션에서 추가할 테스트 목록
1. `test_buy_filter.py` — `buy_filter.py` 1차 종목 필터링 로직 (거래대금 기준)
2. `test_risk_manager.py` — `risk_manager.py` 리스크 체크 로직
3. `test_circuit_breaker.py` — `circuit_breaker.py` 서킷브레이커 트리거
4. `test_settlement_engine.py` — `settlement_engine.py` 정산 계산
5. `test_trading.py` — `trading.py` 매수/매도 실행 분기 (테스트모드 동등성 검증)
6. `test_buy_order_executor.py` — `buy_order_executor.py` 주문 실행 경로
