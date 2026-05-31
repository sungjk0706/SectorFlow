# Handover 문서

## 완료 단계

### 2026-05-31: 종목분류 페이지 업종 매핑 근본해결 완료
- **완료일**: 2026-05-31
- **작업**: 종목분류 페이지 업종 매핑 데이터 마이그레이션 및 아키텍처 수정
- **수정 파일**:
  - backend/app/services/engine_sector.py:172-178 - get_all_sector_stocks()를 _subscribed_stocks 기반에서 _master_stocks_cache 기반으로 변경
  - migrate_sector_from_legacy.py (신규 생성): 레거시 DB 업종 매핑 마이그레이션 스크립트
  - cleanup_orphan_sectors.py (신규 생성): 증거금 100% 종목 정리 스크립트
- **검증**:
  - py_compile 성공
  - 레거시 추출: 1458종목
  - master_stocks_table: 1367종목 (업종 매핑 완료)
  - custom_sector_mappings: 1367종목 (1:1 매핑)
  - 기타 업종 종목: 0종목
- **해결 효과**:
  - 실시간 파이프라인과 배치 파이프라인 분리 원칙 준수
  - 단일 소스 진리 준수: _master_stocks_cache 기반 데이터 소스
  - 업종 매핑 완료: 1367종목 모두 업종 분류 (바이오/제약 96종목, 반도체/소부장 88종목 등)
  - 증거금 100% 종목 136종목 정리
- **Git**: commit 83dac9f, push 완료

### 2026-05-31: 종목 이동 기능 델타 전송 원칙 준수 수정 완료
- **완료일**: 2026-05-31
- **작업**: 종목 이동 기능에서 델타 전송 원칙 준수 및 비동기 아키텍처 부합
- **수정 파일**:
  - backend/app/web/routes/stock_classification.py:264-281 - move-stocks 응답에 all_stocks 포함
  - frontend/src/types/index.ts:285-290 - StockClassificationMutationResponse 타입에 all_stocks 필드 추가
  - frontend/src/pages/stock-classification.ts:1403-1435 - onMoveStock()에서 서버 응답 기반 업데이트
- **검증**:
  - 백엔드 py_compile 성공
  - 프론트엔드 npm run build 성공
- **해결 효과**:
  - 델타 전송 원칙 준수: 응답에 필요한 데이터 포함
  - 비동기 아키텍처 부합: move_stock() 이미 비동기 함수
  - 낙관적 업데이트 제거: 서버 상태 기반 업데이트
  - 단일 소스 진리 준수: 서버 응답의 all_stocks가 단일 소스
- **Git**: commit 0f0d4ba, push 완료

### 2026-05-31: 확정시세 다운로드 아키텍처 분리 완료
- **완료일**: 2026-05-31
- **작업**: 확정시세 파이프라인과 5일봉 파이프라인 완전 분리
- **수정 파일**:
  - backend/app/core/kiwoom_stock_rest.py:
    - fetch_ka10081_all_stocks → fetch_ka10081_all_stocks_daily_confirmed (이름 변경)
    - fetch_ka10081_all_stocks_5day (신규 생성)
    - 내부 호출: fetch_ka10081_daily_5d_data → fetch_ka10081_daily_price (확정시세 전용)
  - backend/app/core/kiwoom_providers.py:
    - fetch_all_stocks_daily_confirmed 내부 호출 변경
    - fetch_all_stocks_5day 내부 호출 변경
  - backend/app/core/kiwoom_rest.py:
    - import 변경: fetch_ka10081_all_stocks → fetch_ka10081_all_stocks_daily_confirmed
- **검증**:
  - py_compile: 성공 (kiwoom_stock_rest.py, kiwoom_providers.py, kiwoom_rest.py)
  - 수동 확정시세 다운로드 테스트: 성공 (1367종목, 현재가/거래대금 정상 저장)
  - 수동 5일봉 다운로드 테스트: 성공 (기존 경고는 별도 문제)
- **해결 효과**:
  - 단일 책임 원칙 준수: 확정시세 전용 함수와 5일봉 전용 함수 분리
  - 실시간 파이프라인과 배치 파이프라인 분리 원칙 준수
  - 현재가, 거래대금 0 저장 문제 해결 (fetch_ka10081_daily_price 사용)
  - 두 파이프라인이 동일 수집 함수를 공유하지 않도록 구조 정리
- **아키텍처 원칙 준수**:
  - 단일 책임 원칙
  - 실시간 파이프라인과 배치 파이프라인 분리
  - 단일 소스 진리

### 2026-05-31: save_stock_name_cache NameError 근본해결 완료
- **완료일**: 2026-05-31
- **작업**: save_stock_name_cache 함수 호출 삭제 (NameError 해결)
- **수정 파일**:
  - backend/app/services/market_close_pipeline.py: line 899, 1340, 1649 호출 삭제
- **검증**:
  - save_stock_name_cache 참조 0건 확인 (프로젝트 전체 grep)
  - py_compile 통과 검증 성공
- **해결 효과**:
  - NameError: name 'save_stock_name_cache' is not defined 오류 해결
  - 단일 소스 진리 준수: 종목명은 master_stocks_table.name만 사용
  - JSON 파일 캐시 기능 완전 제거 (sector_stock_cache.py 삭제 시 이미 기능 삭제됨)
- **남은 검증** (사용자 직접 수행):
  - 수동 확정시세 다운로드 테스트
  - 수동 5일봉 다운로드 테스트
  - 앱 재기동 후 종목명 정상 표시 확인

### 2026-05-31: _radar_cnsr_order 제로-체크 설계 구현 완료
- **완료일**: 2026-05-31
- **작업**: _radar_cnsr_order 캐시 완전 삭제 및 제로-체크 설계 구현
- **수정 파일** (14개):
  - engine_bootstrap.py: _radar_cnsr_order.extend() → 직접 구독 호출
  - engine_cache.py: _radar_cnsr_order import 제거 → _subscribed_stocks.add()
  - engine_strategy_core.py: register_pending_stock() 함수 삭제
  - engine_sector.py: _radar_cnsr_order → _subscribed_stocks 대체 (3곳)
  - engine_ws_dispatch.py: _radar_cnsr_order 체크 삭제 (제로-체크 보장)
  - engine_account_notify.py: _radar_cnsr_order 체크 삭제
  - engine_ws.py: O(n) 순회 → O(1) set 조회
  - engine_radar.py: _radar_cnsr_order → _subscribed_stocks 대체 (4곳)
  - status.py: radar_cnsr_order_count 제거
  - engine_loop.py: global _radar_cnsr_order 선언 제거, clear() 제거
  - engine_service.py: _radar_cnsr_order import 제거
  - engine_state.py: _radar_cnsr_order 선언 제거
  - market_close_pipeline.py: _radar_cnsr_order → _subscribed_stocks 대체 (4곳)
  - engine_sector_confirm.py: _radar_cnsr_order → _subscribed_stocks 대체
- **검증**:
  - py_compile: 모든 수정 파일 컴파일 성공
  - 앱 기동 테스트: 84ms 기동 시간, 모든 루프 정상 시작
- **해결 효과**:
  - 단일 소스 진리: _subscribed_stocks + _master_stocks_cache만 사용
  - 제로-체크 보장: 실시간 틱 처리 경로에 체크 로직 없음
  - O(1) 성능: set 조회로 리스트 순회 제거
  - 아키텍처 원칙 준수 (단일 소스, 블로킹 금지)

### 2026-05-31: _radar_cnsr_order 삭제 설계 및 승인 완료
- **완료일**: 2026-05-31
- **작업**: _radar_cnsr_order 가짜 캐시 삭제를 위한 영향범위 분석 및 단일 마스터 캐시 직결 설계
- **조사 결과**:
  - _radar_cnsr_order: 앱 기동 시 master_stocks_table에서 Fresh Init, 장중 일부 컬럼 실시간 갱신, 앱 종료 시 명시적 해제 로직 없음
  - _sector_stock_layout: DB(master_stocks_table.sector)에서 Fresh Init, 장중 갱신 없음, 앱 종료 시 명시적 해제 로직 없음
  - _sector_summary_cache: 계산 결과로 Fresh Init, 장중 실시간 갱신, 앱 종료 시 명시적 해제 로직 없음
- **영향범위**: 쓰기 6개 파일, 읽기 10개 파일, 선언 1개 파일 총 17개 위치 식별
- **마이그레이션 계획**: 7개 경로(구독 신청, 업종 계산, 실시간 틱 처리, 레이더/모니터링, 초기화/정리, 상태 노출, import 정리)별 단일 마스터 캐시 직결 설계
- **제로-체크 보장**: 구독 신청 단계 필터링 단일 진입점으로 실시간 파이프라인 체크 로직 완전 삭제 설계
- **승인 상태**: 사용자 승인 완료 (초슬림 아키텍처 정석 평가)
- **다음 단계**: 7개 경로 순차적 코드 수정 (17개 파일 위치)

### 2026-05-31: load_settings() 캐싱 로직 추가 및 이름 변경 완료
- **완료일**: 2026-05-31
- **작업**: load_settings() 함수에 캐싱 로직 추가 및 load_integrated_system_settings()로 이름 변경
- **수정 파일**:
  - backend/app/core/settings_file.py:186-268 - load_integrated_system_settings() 함수 생성 (캐싱 로직 추가)
  - backend/app/core/settings_file.py:268 - 하위 호환성 별칭 추가 (load_settings = load_integrated_system_settings)
  - backend/app/core/settings_file.py:376-384 - update_settings() 캐시 무효화 로직 추가
- **검증**:
  - py_compile 검증: 성공 (settings_file.py, settings_store.py, engine_settings.py, telegram_bot.py, dry_run.py, app.py)
- **해결 효과**:
  - 최초 1회만 DB 조회, 이후 캐시된 데이터 반환
  - "설정 매번 DB 쿼리 금지: 메모리 상주" 원칙 준수
  - 이름 일관성 확보 (load_integrated_system_settings)
  - 하위 호환성 유지 (load_settings 별칭)
- **남은 작업**:
  - 앱 기동 테스트로 로그 중복 출력 해결 확인
  - "[설정] DB integrated_system_settings 로드 완료" 로그 1회만 출력되는지 확인

### 2026-05-31: 설정 로드 중복 문제 근본 해결 완료
- **완료일**: 2026-05-31
- **작업**: "[설정] DB integrated_system_settings 로드 완료" 로그 중복 출력 문제 근본 해결
- **수정 파일** (14개):
  - backend/app/web/app.py:87-90 - _settings_cache 초기화 보장
  - backend/app/services/engine_loop.py:212-214 - load_settings() 호출 제거
  - backend/app/services/engine_bootstrap.py:155-157, 225-227, 308-310 - load_settings() 호출 제거
  - backend/app/services/daily_time_scheduler.py:189-191, 220-222, 360-364, 705-707, 785-788, 949-951, 1076-1078, 1124-1125, 998-1000 - load_settings_async() 호출 제거
  - backend/app/services/ws_subscribe_control.py:184-187, 237-241 - load_settings() 호출 제거
  - backend/app/services/data_manager.py:47-51 - load_settings() 호출 제거
  - backend/app/services/engine_config.py:28-34 - load_settings() 호출 제거
  - backend/app/services/market_close_pipeline.py:1249-1250 - load_settings() 호출 제거
  - backend/app/services/settlement_engine.py:212-215 - load_settings_async() 호출 제거
  - backend/app/services/engine_snapshot.py:41, 68-69 - load_settings_async() 호출 제거
  - backend/app/services/telegram_bot.py:301-305 - load_settings() 호출 제거
  - backend/app/web/routes/settings.py:75-78 - load_settings_async() 호출 제거
  - backend/app/core/settings_file.py:354-356 - load_settings_async() 함수 제거
  - backend/app/core/industry_map.py:54-57 - load_settings_async() 호출 제거
  - backend/app/core/settings_store.py:351-353, 456-457 - load_settings_async() 호출 제거
- **검증**:
  - py_compile 검증: 성공 (모든 수정 파일 컴파일 오류 없음)
  - load_settings_async 잔여 검색: 0건 (모든 호출 제거 완료)
  - 앱 기동 테스트: 성공
    - "[설정] DB integrated_system_settings 로드 완료" 로그 1회만 출력 확인
    - 백엔드 포트 8000, 프론트엔드 포트 5173 정상 실행
    - WebSocket 연결, 초기화 이벤트 정상 전송
- **해결 효과**:
  - 단일 소스 진리 준수: app.py에서 _settings_cache 초기화 후 모든 설정 조회는 메모리 캐시에서만 수행
  - "설정 매번 DB 쿼리 금지: 메모리 상주" 원칙 준수
  - 로그 중복 출력 문제 해결 (기존 다중 호출 → 단일 호출)
  - 아키텍처 원칙 준수

### 2026-05-31: load_master_stocks_table() tuple 반환 버그 근본해결 완료
- **완료일**: 2026-05-31
- **작업**: load_master_stocks_table() sector_cache 중복 제거 및 tuple 반환 버그 해결
- **수정 파일**:
  - backend/app/db/stock_tables.py: sector_cache 변수 제거, 반환 타입을 dict[str, dict]으로 변경
  - backend/app/services/engine_bootstrap.py: sector_cache 언패킹 제거, sector_cache 사용 로직 제거, loaded_data에서 sector 직접 조회
- **검증**: py_compile 성공, 앱 기동 성공 (1503종목 로드 완료)
- **해결 효과**:
  - AttributeError: 'tuple' object has no attribute 'items' 오류 해결
  - 단일 소스 진리 준수: master_stocks_table.sector 컬럼만 사용
  - 중복 캐시 제거: sector_cache 제거
  - 아키텍처 원칙 준수

### 2026-05-31: _sector_stocks_cache 삭제 완료
- **완료일**: 2026-05-31
- **작업**: `_sector_stocks_cache` 캐시 완전 삭제 및 `_master_stocks_cache` 기반 실시간 필터링으로 대체
- **수정 파일**:
  - engine_sector.py: get_sector_stocks() 함수를 실시간 필터링/정렬으로 수정, _invalidate_sector_stocks_cache() 함수 제거, 호출 제거 (3곳)
  - engine_state.py: _sector_stocks_cache, _sector_stocks_dirty, _sector_stocks_last_invalidated 선언 제거, _invalidate_sector_stocks_cache 함수 정의 제거
  - engine_service.py: _sector_stocks_cache, _sector_stocks_dirty, _sector_stocks_last_invalidated, _invalidate_sector_stocks_cache import 제거
  - engine_account_notify.py: 이미 get_sector_stocks() 호출 사용 중 (변경 없음)
  - engine_snapshot.py: _invalidate_sector_stocks_cache import 및 호출 제거
  - status.py: get_sector_stocks() 호출에 await 추가
  - stock_classification_data.py: _invalidate_sector_stocks_cache 호출 제거 (3곳: rename_sector, delete_sector, move_stock)
  - engine_bootstrap.py: _invalidate_sector_stocks_cache import 및 호출 제거 (2곳)
  - engine_strategy_core.py: _invalidate_sector_stocks_cache import 및 호출 제거 (1곳)
  - engine_sector_confirm.py: _invalidate_sector_stocks_cache 호출 제거 (3곳)
  - daily_time_scheduler.py: _invalidate_sector_stocks_cache 호출 제거 (2곳)
  - engine_radar.py: _invalidate_sector_stocks_cache import 및 호출 제거 (2곳)
- **검증**: py_compile 성공 (수정한 12개 파일 모두 컴파일 오류 없음)
- **해결 효과**:
  - 메모리 낭비 해결 (중복 캐시 제거)
  - 데이터 불일치 가능성 제거 (단일 진실 공급원: _master_stocks_cache)
  - 아키텍처 원칙 준수 (단일 소스 원칙)
- **남은 작업**:
  - 앱 기동 테스트로 업종순위 페이지 정상 동작 확인
  - WS 이벤트 정상 전송 확인

### 2026-05-31: _pending_stock_details 캐시 제거 완료
- **완료일**: 2026-05-31
- **작업**: `_pending_stock_details` 캐시 완전 제거 (4단계까지 완료)
- **수정 파일**:
  - 1단계: 준비 작업 및 Git 백업
  - 2단계: 읽기 대체 (6개 그룹: engine_radar.py, engine_sector.py, engine_account.py, trading.py, engine_sector_score.py, engine_ws_dispatch.py, engine_snapshot.py)
  - 3단계: 쓰기 위치 제거 (5개 파일: engine_radar.py, engine_strategy_core.py, engine_bootstrap.py, engine_cache.py, market_close_pipeline.py)
  - 4단계: 캐시 선언 제거 (engine_state.py) 및 import 제거 (16개 파일)
- **검증**: py_compile 성공
- **해결 효과**:
  - 메모리 낭비 해결 (중복 캐시 제거)
  - 데이터 불일치 가능성 제거 (단일 진실 공급원: _master_stocks_cache, _radar_cnsr_order)
  - 아키텍처 원칙 준수 (단일 소스 원칙)
- **커밋**:
  - c07fcbd: 4단계 완료: _pending_stock_details 캐시 삭제
  - 95c2c05: 버그 수정: engine_sector.py에 _radar_cnsr_order import 누락 추가

### 2026-05-31: _high_5d_cache 제거 및 단일 소스 진리 준수 완료
- **완료일**: 2026-05-31
- **작업**: `_high_5d_cache` 별도 캐시 제거, `_master_stocks_cache`의 `high_5d_price`를 단일 소스로 사용
- **수정 파일**:
  - engine_cache.py: `_high_5d_cache` import 제거
  - market_close_pipeline.py: `_high_5d_cache` 사용 제거 (2곳)
  - engine_sector_confirm.py: `get_high_5d_cache()` 함수 사용 (2곳)
  - market_close_pipeline_v2.py, v3.py: 백업 파일이므로 수정 제외
- **검증**: py_compile 성공
- **해결 효과**:
  - 단일 소스 진리 원칙 준수 (_master_stocks_cache)
  - 중복 캐시 제거로 메모리 절약
- **커밋**: 0e8f989

### 2026-05-31: engine_sector_confirm.py 기능 및 의존성 조사 완료
- **완료일**: 2026-05-31
- **작업**: engine_sector_confirm.py 기능, 의존성, 사용처, 아키텍처 판단 조사
- **조사 결과**:
  - 주요 기능: 업종 점수 증분 재계산 및 0D 호가 구독 delta 갱신
  - 의존성: _sector_summary_cache, _radar_cnsr_order, _stock_rising_state, _subscribed_0d_stocks
  - 사용처: engine_bootstrap.py, engine_sector.py, engine_ws_dispatch.py, engine_lifecycle.py
  - 아키텍처 판단: 원칙 위반 없음, 삭제 권장 안 함 (핵심 실시간 모듈)

### 2026-05-31: engine_sector_confirm.py 설계 의도 대비 조사 완료
- **완료일**: 2026-05-31
- **작업**: 설계 의도(5일평균거래대금 필터링 → 구독 → 업종순위 계산) 대비 현재 코드 조사
- **조사 결과**:
  - 설계 의도: sector_min_trade_amt 필터링 → 필터링 통과 종목만 구독 → 구독 종목만 업종순위 계산
  - 현재 코드: _radar_cnsr_order에 모든 종목 추가 → _radar_cnsr_order 기준 업종순위 계산 → sector_min_trade_amt 필터링은 계산 단계에서 적용
  - 일치 여부: 아니오
  - 불일치 상세:
    - engine_bootstrap.py:158-164: 모든 종목을 _radar_cnsr_order에 추가 (필터링 없음)
    - engine_sector.py:96-114: _radar_cnsr_order에 있는 모든 종목을 stock_details로 반환
    - engine_sector_score.py:307: 계산 단계에서 min_avg_amt_eok 필터링 적용
    - engine_ws_dispatch.py:295-297: _radar_cnsr_order에 있는 모든 종목 구독
  - 근본 원인: _radar_cnsr_order가 필터링된 종목 목록이 아니라 전체 종목 목록으로 사용됨
  - 결론: 설계 위반 예, 수정 필요 예

### 2026-05-31: 중복 캐시 제거 및 _master_stocks_cache 단일화 완료
- **완료일**: 2026-05-31
- **작업**: `_avg_amt_5d`, `_high_5d_cache`, `_sector_cache` 중복 캐시 제거 및 `_master_stocks_cache` 단일화
- **수정 파일**:
  - backend/app/services/engine_state.py: `_avg_amt_5d`, `_high_5d_cache`, `_sector_cache` 선언 삭제
  - backend/app/services/engine_sector.py: `_avg_amt_5d` 읽기 → `_master_stocks_cache` 변경
  - backend/app/services/engine_radar.py: `get_avg_amt_5d_map()`, `get_high_5d_cache()` → `_master_stocks_cache`에서 읽도록 변경
  - backend/app/services/engine_service.py: `_avg_amt_5d`, `_high_5d_cache` import 제거
  - backend/app/services/engine_bootstrap.py: `_high_5d_cache`, `_sector_cache` 쓰기/읽기 → `_master_stocks_cache` 변경
  - backend/app/services/engine_cache.py: `_high_5d_cache` 쓰기 → `_master_stocks_cache` 변경
  - backend/app/services/engine_loop.py: `_avg_amt_5d.clear()` 제거
  - backend/app/services/market_close_pipeline.py: `_avg_amt_5d`, `_high_5d_cache` 쓰기/읽기 → `_master_stocks_cache` 변경
  - backend/app/services/market_close_pipeline_v2.py: `_avg_amt_5d`, `_high_5d_cache` 쓰기/읽기 → `_master_stocks_cache` 변경
  - backend/app/services/market_close_pipeline_v3.py: `_avg_amt_5d`, `_high_5d_cache` 쓰기/읽기 → `_master_stocks_cache` 변경
- **검증**: py_compile 성공 (수정한 10개 파일 모두 컴파일 오류 없음)
- **해결 효과**:
  - 메모리 낭비 해결 (중복 캐시 제거)
  - 데이터 불일치 가능성 제거 (단일 진실 공급원: _master_stocks_cache)
  - 아키텍처 원칙 준수 (단일 소스 원칙)
- **남은 작업**:
  - 앱 기동 테스트로 실제 동작 확인 필요

### 2026-05-31: DB 타입 INTEGER 전환 마이그레이션 준비 완료
- **완료일**: 2026-05-31
- **작업**: master_stocks_table.avg_5d_trade_amount 컬럼 타입 REAL → INTEGER 변경
- **수정 파일**:
  - backend/app/db/migration_v3.py: avg_5d_trade_amount REAL → INTEGER
  - backend/app/db/stock_tables.py: avg_5d_trade_amount REAL → INTEGER, float() → int()
  - backend/app/db/crud.py: float() → int()
  - run_migration_v4.py: 마이그레이션 실행 스크립트 신규 생성
- **검증**: py_compile 성공
- **백업**: backend/data/stocks.db.backup 생성 완료
- **해결 효과**:
  - DB 타입과 메모리 타입 통일 (INTEGER)
  - float() 변환 코드 제거로 타입 불일치 해결
  - avg_amt_cache.py 함수 유지 (API String → int 변환용)
- **남은 작업**:
  - 마이그레이션 실행: `python3 run_migration_v4.py`
  - 앱 기동 시 자동 실행되도록 main.py에 마이그레이션 호출 추가

### 2026-05-31: avg_amt_cache.py 미사용 함수 정리 완료
- **완료일**: 2026-05-31
- **작업**: load_high_5d_from_cache 함수 및 미사용 함수 주석 삭제
- **수정 파일**:
  - backend/app/core/avg_amt_cache.py: load_high_5d_from_cache 함수 삭제, 미사용 함수 주석 삭제
- **검증**: 백엔드 py_compile 성공
- **해결 효과**:
  - 미사용 코드 제거로 코드베이스 정리
  - 사용 중인 함수만 유지 (normalize_avg_amt_5d_value, is_avg_amt_5d_map_usable, normalize_avg_amt_5d_map)
  - 아키텍처 원칙 준수 (단일 소스 원칙: master_stocks_table)

### 2026-05-31: load_avg_amt_from_sector_summary_cache 함수 삭제로 ModuleNotFoundError 근본해결 완료
- **완료일**: 2026-05-31
- **작업**: 존재하지 않는 sector_summary_cache 모듈 의존 제거
- **수정 파일**:
  - backend/app/core/avg_amt_cache.py: load_avg_amt_from_sector_summary_cache 함수 삭제
  - backend/app/services/market_close_pipeline.py: import 및 호출 삭제
  - backend/app/services/engine_cache.py: import 및 호출 삭제
  - backend/app/services/market_close_pipeline_v2.py: import 및 호출 삭제
  - backend/app/services/market_close_pipeline_v3.py: import 및 호출 삭제
  - backend/app/services/patch_cache2.py: deprecated 마크
- **검증**: 백엔드 py_compile 성공
- **해결 효과**:
  - ModuleNotFoundError: No module named 'backend.app.core.sector_summary_cache' 오류 해결
  - 아키텍처 원칙 준수 (단일 소스 원칙: master_stocks_table)
  - 이전 아키텍처 잔재 제거

### 2026-05-31: 상단헤더바 확정시세다운로드 인디케이터 이모지 중복 표시 버그 근본해결 완료
- **완료일**: 2026-05-31
- **작업**: 백엔드 메시지에서 UI 이모지(⏳) 제거
- **수정 파일**:
  - backend/app/services/market_close_pipeline.py: 모든 ⏳ 이모지 제거 (8건)
  - backend/app/services/market_close_pipeline_v2.py: 모든 ⏳ 이모지 제거 (14건)
  - backend/app/services/market_close_pipeline_v3.py: 모든 ⏳ 이모지 제거 (14건)
- **검증**: 백엔드 py_compile 성공, 프론트엔드 npm run build 성공
- **해결 효과**:
  - 백엔드와 프론트엔드 이모지 중복 표시 문제 해결
  - 아키텍처 원칙 준수 (UI 요소는 프론트엔드 전담, 백엔드는 순수 데이터/로직)
  - 단일 책임 원칙 준수

### 2026-05-31: 매매적격종목 확정시세 다운로드 오류 근본해결 완료
- **완료일**: 2026-05-31
- **작업**: kiwoom_stock_rest.py 변수 미정의 오류 및 market_close_pipeline.py await 누락 오류 해결
- **수정 파일**:
  - backend/app/core/kiwoom_stock_rest.py:
    - line 236-241: resume_codes 관련 로직 정리 (starting_count, completed_codes 미정의 문제 해결)
    - line 262: cur_done = starting_count + done_count → cur_done = done_count
    - line 265: cur_done > starting_count 조건 제거
    - line 274: remaining_codes = [cd for cd in krx_codes if cd not in completed_codes] → remaining_codes = krx_codes
  - backend/app/services/market_close_pipeline.py:
    - line 677: load_avg_amt_from_sector_summary_cache() → await load_avg_amt_from_sector_summary_cache()
    - line 1591: recompute_sector_summary_now() → await recompute_sector_summary_now()
    - line 1593: notify_desktop_sector_stocks_refresh() → await notify_desktop_sector_stocks_refresh()
- **검증**: 백엔드 py_compile 성공
- **해결 효과**:
  - NameError: name 'completed_codes' is not defined 오류 해결
  - AttributeError: 'coroutine' object has no attribute 'values' 오류 해결
  - RuntimeWarning 코루틴 미await 경고 해결
  - 아키텍처 원칙 준수 (모든 I/O는 async def, 코루틴은 반드시 await)

### 2026-05-31: _radar_cnsr_order 필터링 근본 해결 완료
- **완료일**: 2026-05-31
- **작업**: sector_min_trade_amt 필터링을 구독 단계에서 적용하여 설계 의도 준수
- **수정 파일**:
  - backend/app/services/engine_bootstrap.py:157-183 (기존 158-164)
    - krx_rows에서 _radar_cnsr_order.extend() 전에 sector_min_trade_amt 필터링 추가
    - 설정값 로드 후 avg_5d_trade_amount >= min_amt 조건으로 필터링
  - backend/app/services/engine_bootstrap.py:228-253 (기존 211-215)
    - 누락 종목 추가 시 sector_min_trade_amt 필터링 추가
    - _master_stocks_cache에서 avg_5d_trade_amount 조회 후 필터링
  - backend/app/services/engine_cache.py:102-127 (기존 111-112)
    - 스냅샷 로드 시 sector_min_trade_amt 필터링 추가
    - settings 파라미터에서 설정값 로드 후 필터링 적용
  - backend/app/services/market_close_pipeline.py:458-516 (기존 504-505)
    - 함수 시작 부분에 설정값 로드 추가 (min_amt)
    - 확정 데이터 추가 시 pending에서 avg_5d_trade_amount 조회 후 필터링
  - backend/app/services/market_close_pipeline.py:1897-1919 (기존 1888-1889)
    - 5일평균 데이터 다운로드 후 avg5d 계산 값으로 필터링
    - avg5d >= min_amt 조건으로 _radar_cnsr_order에 추가
- **검증**: py_compile 성공 (engine_bootstrap.py, engine_cache.py, market_close_pipeline.py 모두 통과)
- **해결 효과**:
  - 단일 소스 진리 준수: _radar_cnsr_order는 이제 필터링된 종목만 포함
  - 필터링 조건: sector_min_trade_amt (사용자 설정) 사용
  - 구독: _radar_cnsr_order 기반으로만 신청 (engine_ws_dispatch.py에서 확인)
  - 계산: _radar_cnsr_order 기반으로만 수행 (engine_sector.py에서 확인)
  - 불필요한 틱 데이터 처리량 감소, 실시간 성능 개선
- **남은 작업**:
  - 앱 기동 테스트로 필터링 동작 확인 (구독 종목 수 감소 확인)

### 2026-05-31: sector_stock_cache.py 삭제 및 master_stocks_table 기반 캐시 통합 완료
- **완료일**: 2026-05-31
- **작업**: sector_stock_cache.py 완전 삭제 및 모든 캐시 기능을 master_stocks_table로 통합
- **수정 파일**:
  - backend/app/db/migration_v4.py (생성) - downloaded_at 컬럼 추가 마이그레이션
  - backend/app/web/app.py - migration_v4 호출 추가
  - backend/app/db/stock_tables.py - load_progress_cache, clear_progress_cache, load_stock_name_cache 추가
  - backend/app/core/kiwoom_stock_rest.py - 이어받기 로직을 master_stocks_table 기반으로 수정
  - backend/app/services/market_close_pipeline.py - import 변경, save_filter_summary_cache 호출 제거
  - backend/app/services/market_close_pipeline_v2.py - import 변경, save_filter_summary_cache 호출 제거
  - backend/app/services/market_close_pipeline_v3.py - import 변경, save_filter_summary_cache, save_market_map_cache, save_stock_name_cache 호출 제거
  - backend/app/services/engine_sector.py - load_stock_name_cache import 변경
  - backend/app/services/data_manager.py - load_stock_name_cache import 변경
  - backend/app/services/engine_cache.py - load_stock_name_cache import 변경
  - backend/app/services/daily_time_scheduler.py - load_stock_name_cache import 변경
  - backend/app/web/routes/stock_classification.py - load_filter_summary_cache 호출 제거
  - backend/app/core/sector_stock_cache.py (삭제)
- **검증**: py_compile 성공 (모든 수정 파일 통과)
- **해결 효과**:
  - 단일 소스 진리 준수: 모든 캐시 기능이 master_stocks_table로 통합
  - 데이터 중복 제거: 종목명 캐시, 필터 요약 캐시, 마켓 맵 캐시, 이어받기 진행 캐시가 master_stocks_table 단일 소스로 관리
  - 이어받기 기능 유지: downloaded_at 컬럼으로 이어받기 로직 재구현
  - 아키텍처 원칙 준수 (단일 소스 원칙)

### 2026-05-31: settings_file.py load_settings 비동기화 완료
- **완료일**: 2026-05-31
- **작업**: load_settings 함수 비동기화 및 호출처 비동기 체인 확인
- **수정 파일**:
  - backend/app/core/settings_file.py:186 - load_settings 함수 async def로 변경 (이미 완료됨)
  - backend/app/core/settings_file.py:232 - 내부 save_settings 비동기 호출 확인 (이미 완료됨)
- **검증**:
  - load_settings 호출처 확인: 9개 위치 모두 await로 비동기 호출됨
  - 호출처 목록:
    - scratch/decrypt_keys.py:5
    - backend/app/services/dry_run.py:297
    - backend/app/services/engine_lifecycle.py:346
    - backend/app/services/telegram_bot.py:369
    - backend/app/core/settings_file.py:348 (update_settings 내부)
    - backend/app/core/settings_store.py:153, 253, 281
    - backend/app/core/engine_settings.py:18
    - backend/app/web/app.py:82
- **해결 효과**:
  - 아키텍처 원칙 준수 (모든 I/O는 async def)
  - 비동기 체인 일관성 보장

## 현재 상태
- **작업 중인 기능**: 업종순위 페이지 좌측 카드 레이아웃 설정 적용 문제 점검
- **진행률**: 90% (단위 불일치 해결 완료, async 호출 해결 완료, 앱 기동 테스트 완료)
- **최종 상태**:
  - engine_sector.py:108-109 - get_sector_summary_inputs()에서 원 단위를 억 단위로 변환
  - engine_sector.py:379-383 - _compute_filtered_codes()에서 원 단위를 억 단위로 변환
  - settings_store.py:447-449 - recompute_sector_summary_now()를 _schedule_engine_coro로 감싸서 async 실행 보장
  - py_compile 검증 성공
  - 앱 기동 테스트 완료: "업종목록 화면전송 -- 184종목" (필터 작동 확인)
- **수정 파일**:
  - backend/app/services/engine_sector.py:108-109 - 단위 변환 추가
  - backend/app/services/engine_sector.py:379-383 - 단위 변환 추가
  - backend/app/core/settings_store.py:447-449 - async 스케줄링 추가

## 다음 단계
- 업종순위 페이지 좌측 카드 레이아웃 설정 적용 점검
  - sector_weights 가중치 설정이 점수 계산에 반영되는지 확인
  - sector_trim_trade_amt_pct trim 설정이 적용되는지 확인
  - sector_trim_change_rate_pct trim 설정이 적용되는지 확인
  - sector_sort_keys 정렬 설정이 적용되는지 확인
  - sector_rank_primary 1차 정렬 기준이 적용되는지 확인
  - sector_min_rise_ratio_pct 상승종목비율 필터가 적용되는지 확인
  - boost_high_breakout_on/boost_order_ratio_on 가산점 설정이 적용되는지 확인
  - compute_sector_scores() 함수에서 각 설정값이 실제로 사용되는지 코드 추적
  - recompute_sector_summary_now()에서 설정값이 compute_full_sector_summary()에 전달되는지 확인

## 미해결 문제
- 업종순위 페이지 좌측 카드 레이아웃 설정부분에서 5일평균 최소 거래대금 필터만 작동, 다른 설정들은 작동하지 않음
  - sector_weights 가중치 설정 반영 여부 미확인
  - sector_trim_trade_amt_pct trim 설정 반영 여부 미확인
  - sector_trim_change_rate_pct trim 설정 반영 여부 미확인
  - 기타 설정값 반영 여부 미확인

## 2026-05-31: 캐시 필요성 토론 세션 완료
- **완료일**: 2026-05-31
- **작업**: _radar_cnsr_order, _sector_stock_layout, _sector_summary_cache 캐시 필요성 토론
- **최종 합의안**:
  1. 장 개시 5분 전 초기화 규칙 인정
     - 캐시가 UI 유실 방지용이 아님
     - 실제 의도: 장 개시 5분 전 과거 데이터 비워 왜곡 방지 (실전 매매 전처리 구조)
  2. 파이프라인 압축 효율성 인정
     - 거래대금/업종 순위로 20~30개 종목만 최종 판별하는 초슬림 파이프라인
     - 무거운 캐시 레이어가 필수적이지 않음
  3. 차기 세션 준비
     - 정밀 코드 기반 조사 먼저 진행
     - 컴팩트한 구조로 안전하게 마이그레이션 계획 수립
- **대상 캐시**:
  - _radar_cnsr_order: 원본 소스 없음 → DB 테이블화 필요
  - _sector_stock_layout: 원본(custom_sector_mappings) 있음 → 캐시 삭제 가능
  - _sector_summary_cache: 파연 결과 캐시 → 계산 비용 검토 필요

## 다음 에이전트 주의사항
- **추측 금지**: 코드 기반으로만 판단
- **사용자 의견 존중**: 사용자 지시 우선
- **단일 소스 원칙**: 데이터의 진리는 오직 master_stocks_table 하나임
- **sector 아키텍처 원칙**:
  - sector는 증권사와 무관한 사용자 커스텀 데이터
  - CustomSector는 DB(master_stocks_table)에서 직접 조회
- **업종 데이터 저장 구조**:
  - master_stocks_table.sector: 종목별 업종 매핑 (최종 원본)
  - sectors 테이블: 업종명 목록 (보조)
  - _sector_cache: 인메모리 읽기 전용 캐시
  - stock_classification.json: 사용하지 않음 (삭제됨)
- **ka10099 API 데이터 처리 원칙**:
  - upName 필드: 시스템에 1바이트도 유입 금지
  - marketCode 필드: market_map 테이블에 저장 (KOSPI/KOSDAQ 분류)
  - sector 필드: 사용자 커스텀 업종만 사용 (master_stocks_table.sector)
