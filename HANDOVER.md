# SectorFlow 작업 인계 문서

## 작업 날짜
2026-06-08

---

## 최신 작업 (2026-06-08) — buyTargets change_rate=0 문제 해결 시도 (미해결)

### 핵심
buyTargets(added)의 change_rate가 0으로 표시되는 문제 해결 시도
백엔드 master_stocks_cache 단일 소스 원칙 준수, null/0 구분 표준화

### 문제 현상
- buyTargets(added) 항목의 change_rate가 0으로 표시됨
- sectorStocks는 정상적인 change_rate 표시
- 로그 확인 결과 백엔드 master_stocks_cache 자체에 change_rate가 0.0으로 저장되어 있음
- 실시간 틱 수신 전에 buy-targets-delta가 전송되는 타이밍 문제

### 수정 내용

1. **백엔드 engine_account_notify.py** (buy-targets-delta 실시간 필드 제거)
   - added/changed 항목에서 실시간 필드 제거 (cur_price, change, change_rate, strength, trade_amount)
   - 종목 목록만 전송 (프론트엔드 sectorStocks 단일 소스 원칙 준수)
   - 비교 키에서 실시간 필드 제외

2. **프론트엔드 binding.ts** (실시간 필드 sectorStocks에서 가져오기)
   - changed 항목: sectorStocks에서 실시간 필드 병합
   - added 항목: sectorStocks에서 실시간 필드 병합
   - 백엔드 단일 소스 원칙 준수

3. **프론트엔드 hotStore.ts** (applyRealData buyTargets 업데이트 로직 복구)
   - sectorStocks 업데이트 시 buyTargets도 함께 업데이트
   - null이 아닐 때만 업데이트 (데이터 없음 표현)

4. **백엔드 kiwoom_stock_rest.py** (change_rate 초기값 null)
   - 전일종가 계산 실패 시 change_rate를 0.0에서 None으로 변경
   - null은 '아직 데이터 없음' 표현

5. **프론트엔드 ui-styles.ts** (null/0 구분 표준화)
   - fmtRate: null이면 '-' 표시, 0이면 '0.00' 표시
   - createRateCell: null이면 '-' 표시, 0이면 '0.00%' 표시

### 수정 파일
- `backend/app/services/engine_account_notify.py`
- `frontend/src/binding.ts`
- `frontend/src/stores/hotStore.ts`
- `backend/app/core/kiwoom_stock_rest.py`
- `frontend/src/components/common/ui-styles.ts`

### 아키텍처 원칙 준수
- 단일 소스 진리: 백엔드 master_stocks_cache → 프론트엔드 sectorStocks → buyTargets
- 실시간 데이터처리기반 표준 아키텍처: 모든 소비자가 단일 소스에서 직접 데이터 가져옴
- null/0 구분: null은 '아직 데이터 없음', 0은 진짜 0%

### 검증 결과
- 백엔드 py_compile: 성공
- 프론트엔드 npm run build: 성공

### 로그 확인 결과
```
[buy-targets-delta] added 종목: 457370, change_rate: 1.36
[buy-targets-delta] added 종목: 035720, change_rate: 0.0
[buy-targets-delta] added 종목: 032830, change_rate: 0.0
...
```
- 일부 종목: change_rate가 정상 값
- 대부분 종목: change_rate가 0.0
- 백엔드 master_stocks_cache 자체에 change_rate가 0.0으로 저장되어 있음

### 진짜 원인
- 업종 계산 로직이 실시간 틱 수신 완료 전에 실행됨
- master_stocks_cache에 실시간 틱 데이터가 아직 도착하지 않음
- change_rate가 0.0인 종목은 실시간 틱이 아직 수신되지 않은 종목

### 미해결 문제
- 실시간 틱 수신 완료 후 업종 계산을 실행하도록 타이밍 조정 필요
- 백엔드에서 실시간 틱 수신 완료를 감지하고 업종 계산을 지연시키는 로직 필요

---

## 이전 작업 (2026-06-08) — 증권사 변경 아키텍처 부합 수정 완료

### 핵심
증권사 변경 시 불완전한 핫-리로드 로직을 엔진 재기동으로 대체하여 단일 진입점 보장
증권사 하드코딩 제거, 아키텍처 원칙 4, 5, 9 준수

### 수정 내용

1. **증권사 변경 시 엔진 재기동 로직 구현** (`engine_service.py`)
   - 원인: `update_broker_credentials_live()`가 키움증권만 하드코딩되어 있고 불완전한 핫-리로드
   - 수정: `broker` 변경 시 `stop_engine()` → `start_engine()`으로 엔진 재기동 (단일 진입점 보장, 원칙 5)
   - 이유: 상태 정리 보장, 테스트 가능성 확보 (원칙 9)

2. **update_broker_credentials_live() 삭제** (`engine_lifecycle.py`)
   - 원인: 증권사 하드코딩 (키움증권만 처리), 아키텍처 원칙 4 위반
   - 수정: 함수 전체 삭제 (77줄)
   - 이유: 엔진 재기동으로 대체, 증권사 하드코딩 제거

3. **on_trade_mode_switched()에서 증권사 이름 제거** (`engine_lifecycle.py`)
   - 원인: `state.kiwoom_connector` 하드코딩
   - 수정: `state.connector_manager or state.kiwoom_connector`로 변경 (BrokerRouter 사용)
   - 이유: 증권사 하드코딩 제거 (원칙 4)

4. **schedule_engine_task() 호출 수정** (`engine_service.py`)
   - 원인: keyword-only 인자 `context`를 positional로 전달하여 TypeError
   - 수정: `schedule_engine_task(on_trade_mode_switched(), context="투자모드 전환")`
   - 이유: 함수 시그니처 준수

5. **engine_service.py에서 update_broker_credentials_live 참조 제거**
   - 원인: 모듈 레벨 참조 할당이 남아 있어 NameError 발생
   - 수정: `update_broker_credentials_live = update_broker_credentials_live` 라인 제거

6. **LS서버소켓 US3 체결 데이터 수신 로그 제거** (`ls_connector.py`)
   - 원인: 실시간 데이터 수신 시 과도한 로그 출력
   - 수정: 로그 라인 제거

7. **구독신청 간격 수정** (`ls_connector.py`)
   - 원인: 구독 속도 최적화 필요
   - 수정: 0.2초 → 0.05초로 변경

### 수정 파일
- `backend/app/services/engine_service.py`
- `backend/app/services/engine_lifecycle.py`
- `backend/app/core/ls_connector.py`

### 아키텍처 원칙 준수
- 원칙 4 (증권사 하드코딩 금지): 준수
- 원칙 5 (단일 소스 진리): 준수
- 원칙 9 (테스트모드 동등성): 준수

### 검증 결과
- `py_compile engine_service.py`: 성공
- `py_compile engine_lifecycle.py`: 성공
- `py_compile ls_connector.py`: 성공

---

## 이전 작업 (2026-06-07)

### 1. trading.py 변수 간소화
- `_change_rate_for_guard`, `_strength_val` 중간 변수 제거
- master_stocks_cache에서 직접 읽기로 변경
- 검증: py_compile, import 성공

### 2. strengths 캐시 제거
- `strengths` 캐시가 `master_stocks_cache`의 `strength` 필드와 중복
- 수정 파일: `sector_data_provider.py`, `sector_calculator.py`, `engine_sector_confirm.py`
- 검증: py_compile, import 성공

### 3. 불필요한 디버그 로그 삭제 (13개 파일)
- `db_writer.py`, `state_manager.py`, `backend_coalescing.py`, `engine_loop.py`, `core_queues.py`, `app.py`, `engine_cache.py`, `daily_time_scheduler.py`, `pipeline_oms.py`, `engine_sector_confirm.py`, `pipeline_compute.py`, `ws.py`, `settings_file.py`
- 검증: py_compile, import 성공

### 4. stock_5d_array 중복 저장 수정
- `INSERT OR REPLACE`로 매일 새 기준일 데이터 추가 시 이전 기준일 데이터 삭제하지 않는 문제 수정
- 수정 파일: `market_close_pipeline.py` (`_step2_roll_5d_arrays`)
- 기존 중복 데이터 2,715행 삭제 완료

### 5. stock_5d_array 미래 날짜 저장 수정
- 공휴일 시 `get_current_trading_day_str()`가 다음 거래일을 반환하여 미래 날짜 저장 문제 수정
- 수정 파일: `market_close_pipeline.py` (`fetch_5d_data_only`)

---

## 이전 작업 (2026-06-06)

### 1. 백엔드 모듈화
- domain/models.py, stock_filter.py, buy_filter.py 생성 (services/ 이동)
- domain/sector_score.py, sector_filter.py, sector_calculator.py 생성 (sector_score_analyzer.py 분리)
- pipelines/ 디렉토리 생성 (pipeline_compute.py, pipeline_oms.py, pipeline_gateway.py 이동)
- 찌꺼기 제거 완료 (원본 파일 삭제, 미사용 import 정리)
- 검증: py_compile, 앱 기동 성공

### 2. 종목분류 페이지 업종 변경 시 업종순위 테이블 UI 갱신 수정
- 원인: `pipeline_compute.py`의 `_handle_sector_recompute()`에서 업종순위 재계산 후 `notify_desktop_sector_scores()` 호출 누락
- 수정: `broadcast_queue` 직접 전송 제거, `notify_desktop_sector_scores(force=True)` 호출 추가
- 아키텍처 준수: 단일 진입점 원칙, 직접 호출 체인 유지

### 3. 프로그램 순매수 가산점 로직 추가
- 기능: 매수설정페이지에서 프로그램 순매수가 양수인 종목에 가산점 부여
- 수정 파일: `buy-settings.ts`, `settings_defaults.py`, `engine_settings.py`, `buy_filter.py`, `engine_radar.py`, `engine_sector_confirm.py`, `sector_calculator.py`, `engine_service.py`
- 아키텍처 준수: 단일 진입점 원칙, 직접 호출 체인 유지, 캐시 패턴 일관성

---

## 미해결/다음 단계
1. 실시간 틱 수신 완료 후 업종 계산을 실행하도록 타이밍 조정
2. 백엔드에서 실시간 틱 수신 완료를 감지하고 업종 계산을 지연시키는 로직 구현
3. buyTargets change_rate=0 문제 근본 해결

---

## 미해결 문제
- buyTargets(added)의 change_rate가 0으로 표시되는 문제
- 백엔드 master_stocks_cache에 실시간 틱 데이터가 아직 도착하지 않은 상태에서 업종 계산 실행
- 실시간 틱 수신 완료를 감지하는 로직 필요
