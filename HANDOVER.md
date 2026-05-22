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
  - `backend/app/web/routes/sector_custom.py` (수정)
- 검증 결과:
  - Python 컴파일: SUCCESS
  - 파이프라인 루프 동작: SUCCESS
  - 컨트롤 큐 연동: SUCCESS

### 4단계: 2차 리팩토링 P0-1 컨트롤 큐 PriorityQueue + Yielding
- 완료일: 2026-05-23
- 수정 파일:
  - `backend/app/services/core_queues.py` (PriorityQueue 전환, 튜플 언패킹)
  - `backend/app/web/routes/settings.py` (우선순위 0 튜플 구조)
  - `backend/app/web/routes/sector_custom.py` (우선순위 1 튜플 구조)
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
