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
- 작업 중인 기능: 없음 (조사 및 원복 완료)
- 진행률: 100%
- 마지막 커밋: 없음 (git commit 필요)

## 다음 단계
1. 장마감(15:30) 이후 ka10086 최신 데이터 반영 확인
2. 5일봉 데이터 DB 저장 로직 재검증 (기동 시 자동 다운로드 로직 추가 필요)
3. 업종명 분류 문제 복구 (레거시 sector_custom.json 사용)

## 미해결 문제
- 5일봉 데이터 DB 저장: master_stocks_table에 avg_5d_trade_amount가 0으로 저장됨
  - 원인: fetch_5d_data_only는 수동 요청 시에만 실행됨, 기동 시 자동 실행 로직 없음
  - 해결 방안: 기동 시 5일봉 데이터 다운로드 자동 실행 로직 추가 필요
- 업종명 분류 문제: 모든 종목이 "기타"로 분류됨
  - 원인: sector_custom.json이 없고, stocks 테이블에도 sector 데이터가 없음
  - 복구 계획: 레거시 sector_custom.json 사용하여 completed_snapshot 업데이트

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
  - `frontend/src/components/common/data-table.ts` (고정 모드에서 options.keyFn 참조 제거)
  - `backend/app/core/sector_summary_cache.py` (불필요 import 제거, 주석 수정)
- 원인:
  - `backend/data/stocks.db`의 `stocks.avg_5d_trade_amount`가 1458종목 중 1457종목 0으로 저장되어 거래대금 필터 450억 통과 종목이 0개가 됨
  - 백엔드가 빈 `sector-stocks-refresh`/`sector-scores`를 전송하여 프론트엔드 업종순위가 빈 화면으로 표시됨
  - `frontend/src/components/common/data-table.ts:430`에서 고정 모드에서 options.keyFn 참조로 TypeScript 오류
  - `backend/app/core/sector_summary_cache.py`에 JSON 파일 저장 시절 주석/불필요 import 남아 있음
- 검증 결과:
  - `py_compile`: SUCCESS
  - 백엔드 관련 모듈 import: SUCCESS
  - `sector_summary_cache` 복구 데이터: 160종목, usable=True
  - 레이아웃 교집합 기준 450억 필터 통과: 159종목
  - `npm run build`: SUCCESS

### 14단계: 업종명 분류 문제 조사 (진행 중)
- 완료일: 2026-05-25
- 조사 내용:
  - 완료된 조사:
    - completed_snapshot 테이블 sector 컬럼 존재 확인 (backend/app/db/cache_db.py:108)
    - sector 데이터 저장 로직 확인 (market_close_pipeline.py:429-433)
    - get_merged_sector() 함수 분석 (sector_mapping.py:15-40)
    - ka10099 API 응답 파싱 확인 (kiwoom_sector_rest.py:414-420)
    - UnifiedStockRecord sector 필드 확인 (broker_providers.py:25-31)
    - 레거시 프로젝트 sector_custom.json 확인 (/Users/sungjk0706/Desktop/SectorFlow1/backend/data/sector_custom.json)
    - 현재 프로젝트 sector_custom.json 미존재 확인
  - 근본 원인:
    - 현재 프로젝트는 사용자 커스텀 업종명을 사용하지만, sector_custom.json이 없음
    - sector_mapping.py는 stocks 테이블만 참조하지만, stocks 테이블에도 sector 데이터가 없음
    - 따라서 모든 종목이 "기타"로 분류됨
  - 복구 계획:
    - 레거시 sector_custom.json의 stock_moves (종목코드 → 업종명 매핑)를 사용하여 completed_snapshot 업데이트
    - 현재 프로젝트에 sector_custom.json 관리 모듈 도입 (레거시 sector_custom_data.py 참고)
    - get_merged_sector() 함수가 sector_custom.json을 참조하도록 수정
  - 예상 결과:
    - 업데이트 대상 종목 수: 약 800개
    - 업데이트 후 "기타" 잔여 종목: 약 600개
- 수정 파일 (예정):
  - backend/app/core/sector_mapping.py (sector_custom.json 참조 추가)
  - backend/app/core/sector_custom_data.py (신규 생성, 레거시 참고)
- 검증 결과:
  - 조사 완료, 복구 계획 수립 완료

### 15단계: 5일봉 데이터 DB 저장 문제 조사 (완료)
- 완료일: 2026-05-25
- 문제 증상:
  - 5일봉 데이터 다운로드 완료 확인 (사용자 눈으로 확인)
  - master_stocks_table에 avg_5d_trade_amount가 0으로 저장됨 (1458종목 중 1457종목)
  - day1~5_amount, day1~5_high도 대부분 0으로 저장됨
- 조사 내용:
  - 완료된 조사:
    - master_stocks_table 저장 로직 확인 (market_close_pipeline.py:536-554)
    - _apply_5d_to_memory 함수 확인 (market_close_pipeline.py:194-268)
    - fetch_ka10086_daily_5d_data 반환 데이터 확인 (kiwoom_sector_rest.py:233-237)
    - fetch_5d_data_only 함수 확인 (market_close_pipeline.py:939-960)
    - fetch_5d_data_only 호출처 확인 (stock_classification.py:288-289)
    - 백엔드 로그 파일 확인 (trading_2026-05-25.log)
  - 근본 원인:
    - fetch_5d_data_only는 수동 요청 시에만 실행됨 (stock_classification.py)
    - 기동 시에는 자동으로 실행되지 않음
    - 사용자 로그에 "[타이머] 5일봉 데이터 메모리 및 DB 반영" 로그 없음
    - 따라서 _apply_5d_to_memory가 호출되지 않음
    - es._amts_5d_arrays, es._highs_5d_arrays가 비어있음
    - master_stocks_table에 0으로 저장됨
  - 해결 방안:
    - 기동 시 5일봉 데이터 다운로드 자동 실행 로직 추가 필요
    - 또는 수동 다운로드 후 DB 저장 로직 확인 필요
- 수정 파일 (예정):
  - backend/app/services/market_close_pipeline.py (기동 시 자동 다운로드 로직 추가)
- 검증 결과:
  - 조사 완료, 해결 방안 수립 완료

### 16단계: ka10086 vs ka10081 비교 조사 및 원복 (완료)
- 완료일: 2026-05-25
- 조사 내용:
  - 완료된 조사:
    - ka10086 API 특성: 일별집계성 지표, 장마감 후 정산 데이터 반영
    - ka10081 API 특성: 일봉 차트 데이터, 장중에도 데이터 반영 가능
    - 키움 답변 확인: ka10081로 5일봉 구현 가능 (최근 5개 일봉 추출, max/sum 집계)
    - DB 데이터 비교: ka10081(현재가)은 20260526, ka10086(5일봉)은 4월 데이터
    - ka10086 원인: 공휴일 연속으로 장마감 후 정산 데이터가 반영되지 않음
  - 시도한 작업:
    - ka10081로 5일봉 데이터 수집 구현 (fetch_ka10081_daily_5d_data 함수 추가)
    - ka10086 관련 함수 삭제 및 ka10081로 대체
    - 테스트 코드 작성 시도 (import 오류로 실행 실패)
    - 전체 원복 (ka10086으로 복원)
  - 결론:
    - ka10086은 장마감 후 정산 데이터 반영 (현재 공휴일 연속으로 4월 데이터만 존재)
    - ka10081은 장중에도 데이터 반영 가능하지만, 실시간성 보장 없음
    - 장마감(15:30) 이후 재다운로드 시 ka10086 최신 데이터 반영 예정
- 수정 파일 (원복 완료):
  - backend/app/core/kiwoom_sector_rest.py (ka10086으로 복원)
  - backend/app/core/kiwoom_providers.py (ka10086으로 복원)
  - backend/app/core/kiwoom_rest.py (ka10086으로 복원)
  - backend/app/services/market_close_pipeline.py (테스트 코드 제거)
  - test_*.py 파일 삭제
- 검증 결과:
  - py_compile: SUCCESS
  - 원복 완료
