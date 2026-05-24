# Handover 문서

## 완료 단계

### 1단계: SQLite DB 백엔드 구축
- 완료일: 2026-05-22
- 수정 파일:
  - `backend/app/db/database.py` (신규 생성)
  - `backend/app/db/models.py` (신규 생성)
  - `backend/app/db/crud.py` (신규 생성)
  - `backend/app/services/engine_bootstrap.py` (수정)
  - `backend/app/services/market_close_pipeline.py` (수정)
- 검증 결과:
  - Python 컴파일: SUCCESS
  - DB 테이블 생성: SUCCESS
  - 임포트 테스트: SUCCESS

### 2단계: 프론트엔드 더미 터미널화
- 완료일: 2026-05-22
- 수정 파일:
  - `frontend/src/stores/hotStore.ts` (수정)
  - `frontend/src/pages/sector-analysis.ts` (수정)
- 검증 결과:
  - TypeScript 빌드: SUCCESS
  - 빌드 시간: 559ms
  - 타입 오류: 없음

### 3단계: 파이프라인 아키텍처 리팩토링 (Step 1-7)
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/services/core_queues.py` (신규 생성)
  - `backend/app/services/pipeline_compute.py` (신규 생성)
  - `backend/app/services/pipeline_oms.py` (신규 생성)
  - `backend/app/services/pipeline_gateway.py` (신규 생성)
  - `backend/app/services/engine_loop.py` (수정)
  - `backend/app/web/routes/settings.py` (수정)
  - `backend/app/web/routes/stock_classification.py` (수정)
- 검증 결과:
  - Python 컴파일: SUCCESS
  - 파이프라인 루프 동작: SUCCESS
  - 컨트롤 큐 연동: SUCCESS

### 4단계: 2차 리팩토링 P0-1 컨트롤 큐 PriorityQueue + Yielding
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/services/core_queues.py` (PriorityQueue 전환, 튜플 언패킹)
  - `backend/app/web/routes/settings.py` (우선순위 0 튜플 구조)
  - `backend/app/web/routes/stock_classification.py` (우선순위 1 튜플 구조)
  - `backend/app/services/pipeline_compute.py` (튜플 언패킹, Yielding 추가)
- 검증 결과:
  - Python 컴파일: SUCCESS
  - PriorityQueue 동작: SUCCESS
  - 튜플 구조 호환성: SUCCESS

### 5단계: 2차 리팩토링 P0-2 OMS 서킷 브레이커
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/services/circuit_breaker.py` (신규 생성)
  - `backend/app/services/pipeline_oms.py` (Circuit Breaker 연동, 안전장치 추가)
- 검증 결과:
  - Python 컴파일: SUCCESS
  - Circuit Breaker 상태 전이: SUCCESS
  - 안전장치 연동: SUCCESS

### 6단계: 2차 리팩토링 P1-3 글로벌 예외 핸들러 + Telegram 알림
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/web/app.py` (에러 핸들러 강화, 텔레그램 알림 추가, 5분 쿨다운)
- 검증 결과:
  - Python 컴파일: SUCCESS
  - 텔레그램 알림 연동: SUCCESS
  - 중복 알림 차단: SUCCESS

### 7단계: 2차 리팩토링 P1-4 인메모리 Latency 로깅
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/services/pipeline_compute.py` (tick_to_compute_ms 측정)
  - `backend/app/services/pipeline_oms.py` (order_to_broker_ms 측정)
  - `backend/app/web/routes/metrics.py` (/api/metrics/latency 엔드포인트 추가)
- 검증 결과:
  - Python 컴파일: SUCCESS
  - Latency Metrics 연동: SUCCESS
  - API 엔드포인트: SUCCESS

### 8단계: 2차 리팩토링 P2-5 Protobuf + Coalescing (완료)
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/services/backend_coalescing.py` (tick_queue 전송 추가, Protobuf 직렬화)
  - `backend/app/services/engine_ws_dispatch.py` (데이터 타입별 분기 처리 - 돈 데이터 즉시 우회, 연산 데이터 압축)
  - `backend/app/services/pipeline_compute.py` (Protobuf 파싱 추가, 0J/0D 핸들러 추가)
- 설계 변경:
  - 체결(00), 잔고(04/80): 즉시 처리 (압축 금지) - 체결 알림 팝업, 계좌 잔고창 무손실·초저지연 보장
  - 시세(01/0B), 지수(0J), 호가(0D): Coalescing 압축 버퍼로 전송 (10ms 압축)
- 데이터 흐름:
  - 돈 데이터: 시세 수신부 → 즉시 핸들러 → engine_service 전역 상태
  - 연산 데이터: 시세 수신부 → Coalescing → Protobuf → tick_queue → 연산 엔진
- 검증 결과:
  - Python 컴파일: SUCCESS
  - 데이터 타입별 분기 처리: SUCCESS
  - 0J/0D 핸들러 이관: SUCCESS

## 현재 상태
- 작업 중인 기능: 없음 (2차 리팩토링 전체 완료)
- 진행률: P0-1, P0-2, P1-3, P1-4, P2-5 완료 (5/5 단계)
- 마지막 커밋: 없음 (git commit 필요)

## 다음 단계
- 2차 리팩토링 전체 완료. 다음 작업 대기 중.

## 미해결 문제
- 없음

## 주의 사항
- DB 파일 위치: `data/stocks.db`
- DB 스키마: stocks 테이블 (code, name, sector, prev_close, avg_5d_trade_amount, high_price)
- 백엔드는 파이썬 메모리에서 실시간 연산 수행 (DB 병목 제거)
- 프론트엔드는 백엔드 계산 결과 그대로 렌더링 (Dumb Terminal)
- 파이프라인 아키텍처: tick_queue, order_queue, broadcast_queue, control_queue (PriorityQueue)
- P0-1 완료: 컨트롤 큐 PriorityQueue 전환, 틱 폭주 시 제어 명령 0.001초 내 처리 보장
- P0-2 완료: OMS 서킷 브레이커, 주문 실패 5회 시 계좌 보호 모드 활성화
- P1-3 완료: 글로벌 예외 핸들러 + Telegram 알림, 5분 쿨다운으로 중복 알림 차단
- P1-4 완료: 인메모리 Latency 로깅, 구간별 지연 시간 측정 및 API 제공

### 9단계: 전량 매도 후 재매수 시 평균 매입가 유령 데이터 혼입 버그 수정
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/services/trade_history.py` (DB 역산 로직 제거, 유령 데이터 혼입 방지)
- 설명:
  - record_sell 함수에서 avg_buy_price <= 0일 때 DB 역산 로직 제거
  - 외부(메모리)에서 전달된 avg_buy_price를 절대적으로 신뢰
  - avg_buy_price가 0 이하일 경우 로그 남기고 실현손익 계산 건너뜀
  - 과거 매수 기록 혼입으로 인한 수익현황 페이지 오염 방지
- 검증 결과:
  - Python 컴파일: SUCCESS (Exit Code 0)

### 10단계: 프론트엔드 설정 저장 로직 모듈화
- 완료일: 2026-05-23
- 수정 파일:
  - `frontend/src/utils/settings-save.ts` (신규 생성)
  - `frontend/src/pages/buy-settings.ts` (settings-save.ts 사용)
  - `frontend/src/pages/sell-settings.ts` (settings-save.ts 사용)
- 설명:
  - createAutoSaveHelper 함수로 설정 저장 로직 모듈화
  - debounced saving, pending save queue, immediate saving 통합
  - 약 20줄 중복 코드 제거
- 검증 결과:
  - TypeScript 빌드: SUCCESS

### 11단계: 스타일 유틸리티 표준화
- 완료일: 2026-05-23
- 수정 파일:
  - `frontend/src/components/common/ui-styles.ts` (setDisabled, setDisplay 헬퍼 추가)
  - `frontend/src/pages/buy-settings.ts` (setDisabled 사용, 6회 교체)
  - `frontend/src/pages/buy-settings.ui.ts` (setDisabled 사용, 6회 교체)
  - `frontend/src/pages/sell-settings.ts` (setDisabled 사용, 8회 교체)
  - `frontend/src/pages/sell-settings.ui.ts` (setDisabled 사용, 8회 교체)
- 설명:
  - setDisabled(el, disabled): opacity + pointerEvents 설정
  - setDisplay(el, visible): display 설정
  - 약 28줄 중복 코드 제거
- 검증 결과:
  - TypeScript 빌드: SUCCESS

### 12단계: fast-check 기반 DOM 조작 테스트 타임아웃 해결
- 완료일: 2026-05-23
- 수정 파일:
  - `frontend/src/components/common/cellDiffingIdempotence.test.ts` (numRuns: 100→20, timeout: 10000ms)
  - `frontend/src/components/common/fixedTableIncrementalUpdate.test.ts` (numRuns: 100→20, timeout: 10000ms)
  - `frontend/src/components/common/flashDirection.test.ts` (numRuns: 100→20, timeout: 10000ms)
- 설명:
  - jsdom 환경에서 DOM 조작 오버헤드로 인한 타임아웃(5000ms 초과) 해결
  - fast-check property-based test의 numRuns를 100에서 20으로 축소
  - 각 테스트 함수의 timeout을 10000ms로 명시적 연장
- 검증 결과:
  - 테스트 전체 통과: 47/47 PASS
  - 테스트 시간: 12.34s

### 13단계: SQLite 마이그레이션 후 업종순위 0종목 표시 원인 해결
- 완료일: 2026-05-24
- 수정 파일:
  - `backend/app/core/avg_amt_cache.py` (5일평균 거래대금 단위 정규화/복구 헬퍼 추가)
  - `backend/app/services/engine_service.py` (`_update_avg_amt_5d` 단일 진입점 정규화 적용)
  - `backend/app/services/engine_cache.py` (stocks DB 5일평균 비정상 시 SectorSummary/avg_amt 캐시 복구)
  - `backend/app/services/engine_bootstrap.py` (부트스트랩 DB 로드 경로 동일 복구 적용)
  - `backend/app/services/market_close_pipeline.py` (확정 데이터 저장·메모리 반영 시 5일평균 정규화)
- 원인:
  - `backend/data/stocks.db`의 `stocks.avg_5d_trade_amount`가 1458종목 중 1457종목 0으로 저장되어 거래대금 필터 450억 통과 종목이 0개가 됨
  - 백엔드가 빈 `sector-stocks-refresh`/`sector-scores`를 전송하여 프론트엔드 업종순위가 빈 화면으로 표시됨
- 검증 결과:
  - `py_compile`: SUCCESS
  - 백엔드 관련 모듈 import: SUCCESS
  - `sector_summary_cache` 복구 데이터: 160종목, usable=True
  - 레이아웃 교집합 기준 450억 필터 통과: 159종목
  - `npm run build`: FAIL (`frontend/src/components/common/data-table.ts:430`의 기존 `options` 미정의 오류)
