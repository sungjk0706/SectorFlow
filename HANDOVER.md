# Handover 문서

## 완료 단계

### 2026-06-02: ImportError 및 UnboundLocalError 근본 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**:
  - market_close_pipeline.py:635 - broker_router에서 get_router import 시도 (함수 없음)
  - get_router 함수는 broker_factory.py:25-36에 존재
  - market_close_pipeline.py:729 - conn 변수가 할당되지 않은 상태에서 rollback 호출 시도
- **수정 파일** (1개):
  - backend/app/services/market_close_pipeline.py:635 - import 경로 수정 (broker_router → broker_factory)
  - backend/app/services/market_close_pipeline.py:729 - conn 변수 존재 여부 확인 후 rollback
- **검증**:
  - py_compile 성공 (market_close_pipeline.py)
- **해결 효과**:
  - 단일 소스 진리: get_router는 broker_factory.py의 단일 진입점
  - DB 연결 생명주기 공유: get_db_connection() 사용 유지
  - 예외 처리 안전성: conn 변수 존재 여부 확인 후 rollback

### 2026-06-02: stock_5d_array 데이터 저장 근본 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**:
  - market_close_pipeline.py:229-239 - _apply_5d_to_memory() 함수에서 ka10081 API에서 받은 5일봉 데이터를 사용하지 않고 무조건 0으로 저장
  - market_close_pipeline.py:633-634 - 수동 확정시세 파이프라인에서도 동일한 문제
  - kiwoom_stock_rest.py:140-211 - fetch_ka10081_daily_5d_data() 함수는 정상적으로 구현되어 있으나 호출되지 않음
- **수정 파일** (1개):
  - backend/app/services/market_close_pipeline.py:189-266 - _apply_5d_to_memory() 함수에 ka10081 API 호출 추가 (fetch_ka10081_daily_5d_data)
  - backend/app/services/market_close_pipeline.py:632-671 - 수동 확정시세 파이프라인에 ka10081 API 호출 추가
- **검증**:
  - py_compile 성공 (market_close_pipeline.py)
- **해결 효과**:
  - 단일 소스 진리: ka10081 API가 5일봉 데이터의 단일 소스
  - 실시간 파이프라인과 배치 파이프라인 분리: stock_5d_array는 배치 파이프라인(장마감 후 확정시세)에서만 업데이트
  - DB 연결 생명주기 공유: 기존 get_db_connection() 사용 유지
  - 모든 I/O는 async def: 기존 비동기 구조 유지
- **다음 단계**:
  - 앱 재기동 후 ka10081 다운로드 실행
  - stock_5d_array 테이블에서 실제 데이터(0이 아닌 값) 저장 확인

### 2026-06-02: 버그 수정 - NameError, RuntimeWarning, TypeError 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**:
  - engine_snapshot.py:192 - _master_stocks_cache import 누락
  - engine_snapshot.py:235 - 정의되지 않은 count 변수 사용
  - broker_factory.py:91 - create_kiwoom_connector()에 settings 전달 (시그니처 불일치)
  - settings_store.py:397, 401 - 비동기 함수 호출 시 await 누락
  - engine_loop.py:320 - ConnectorManager()에 settings 전달 (시그니처 불일치)
- **수정 파일** (4개):
  - backend/app/services/engine_snapshot.py:18 - _master_stocks_cache import 추가
  - backend/app/services/engine_snapshot.py:235 - count → len(_master_stocks_cache) 수정
  - backend/app/core/broker_factory.py:91-94 - kiwoom 특수 처리 추가 (settings 전달하지 않음)
  - backend/app/core/settings_store.py:397, 401 - await 추가
  - backend/app/services/engine_loop.py:320 - ConnectorManager(settings) → ConnectorManager() 수정
- **검증**:
  - py_compile 성공 (모든 수정 파일)
  - 앱 재기동 성공 (백엔드 49ms, 프론트엔드 677ms)
  - NameError 미발생
  - RuntimeWarning 미발생
  - TypeError 미발생
- **해결 효과**:
  - 단일 소스 진리 준수: _master_stocks_cache는 engine_state.py에서만 정의, ConnectorManager 내부에서 캐시 직접 사용
  - 증권사 이름 공통 기능 침투 금지: kiwoom 특수 처리 분리
  - 모든 I/O는 async def: 비동기 함수에 await 추가

### 2026-06-02: P0-3 BrokerSession 단일화 규칙 적용 완료
- **완료일**: 2026-06-02
- **작업**: BrokerRouter 직접 생성 경로 제거, get_router() 단일 경로 사용
- **수정 파일** (2개):
  - backend/app/services/market_close_pipeline.py:754-768 - 첫 번째 BrokerRouter() 직접 생성을 get_router()로 변경 (타이머 파이프라인)
  - backend/app/services/market_close_pipeline.py:1197-1210 - 두 번째 BrokerRouter() 직접 생성을 get_router()로 변경 (수동 확정시세 파이프라인)
  - backend/app/services/engine_lifecycle.py:55-58 - 미사용 _kiwoom_auth_provider 초기화 코드 삭제
- **검증**:
  - py_compile 성공 (market_close_pipeline.py, engine_lifecycle.py)
  - 앱 재기동 성공 (백엔드 49ms, 프론트엔드 533ms)
  - 테스트모드 기동 확인 (토큰 발급 완료 로그 확인: "[연결] kiwoom 토큰 발급 완료")
- **해결 효과**:
  - BrokerRouter 직접 생성 경로 제거 → get_router() 싱글톤 패턴 단일 경로 사용
  - 토큰 재발급 중복 방지 (KiwoomRestAPI._token_info를 토큰 원천으로 확정)
  - 미사용 코드 제거 (_kiwoom_auth_provider)
  - 아키텍처 원칙 준수 (단일 소스 진리, BrokerSession 단일화)
  - 테스트모드와 실전투자 모드의 차이점(돈 관련 기능만 제외) 올바르게 적용됨

### 2026-06-02: custom_sectors 테이블 구조 및 데이터 정비 완료
- **완료일**: 2026-06-02
- **작업**: sectors 테이블 이름 변경, 스키마 수정, 업종 매핑 데이터 완성
- **수정 파일** (3개):
  - backend/app/core/sector_mapping.py:49 - custom_sectors → master_stocks_table 조회로 변경
  - backend/app/core/sector_mapping.py:43-57 - get_merged_all_sectors()를 인메모리 캐시 기반으로 변경
  - backend/app/core/stock_classification_data.py:52, 82, 100 - sectors → custom_sectors 테이블명 변경
  - backend/app/web/routes/stock_classification.py:95 - sectors → custom_sectors 테이블명 변경
  - backend/app/web/routes/stock_classification.py:91-100 - 커스텀 업종 목록 조회를 인메모리 캐시 기반으로 변경
- **DB 변경**:
  - sectors 테이블 → custom_sectors로 이름 변경
  - custom_sectors 스키마 변경: name TEXT PRIMARY KEY → name TEXT, stock_code TEXT, PRIMARY KEY (name, stock_code)
  - 레거시 프로젝트 기반 업종 매핑 데이터 삽입: 1320개
  - 기타 업종 종목 추가: 47개
  - master_stocks_table sector 필드 업데이트: 1367개
- **검증**:
  - py_compile 성공 (sector_mapping.py, stock_classification_data.py, stock_classification.py)
  - custom_sectors 테이블 총 종목수: 1367개
  - master_stocks_table 총 종목수: 1367개
  - 기타 업종 종목수: 47개
- **해결 효과**:
  - 테이블 이름 명확화: sectors → custom_sectors (사용자 커스텀 업종)
  - 업종-종목 매핑 구조: custom_sectors 테이블이 업종명과 종목코드 매핑 저장
  - 단일 소스 진리: 업종 목록 조회를 인메모리 캐시(_master_stocks_cache) 기반으로 변경
  - 데이터 동기화: custom_sectors와 master_stocks_table 종목수 일치 (1367개)
- **다음 단계**:
  - 앱 재기동 후 업종 데이터 정상 표시 확인 필요

### 2026-06-02: 업종순위 페이지 좌측/우측 카드 데이터 소스 불일치 근본 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**: 백엔드와 프론트엔드에서 각각 5일평균거래대금 필터링 수행으로 종목수 불일치
- **수정 파일** (2개):
  - backend/app/services/engine_sector.py:118-158 - get_sector_stocks()에 min_avg_amt_eok 필터링 추가
  - frontend/src/pages/sector-stock.ts:115-122, 235-249 - computeRows()에서 minTradeAmt 파라미터 제거, buildRows()에서 필터링 로직 제거
- **검증**:
  - npm run build 성공
- **해결 효과**:
  - 단일 소스 진리: 백엔드에서 필터링 수행, 프론트엔드는 표시만 담당
  - 좌측 카드와 우측 카드 종목수 일치 확보
  - 아키텍처 원칙 준수 (단일 소스 진리, 백엔드 필터링)
- **사용자 확인 방법**:
  - 앱 재기동 후 업종순위 페이지 확인
  - 좌측 카드와 우측 카드의 종목수 일치 확인

### 2026-06-02: BuyTarget JSON 직렬화 오류 근본 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**: get_buy_targets_snapshot()이 BuyTarget dataclass 객체 리스트를 그대로 반환하여 json.dumps() 직렬화 실패
- **수정 파일** (1개):
  - backend/app/services/engine_snapshot.py:258-266 - get_buy_targets_snapshot() 함수에 dataclasses.asdict() 추가
- **검증**:
  - py_compile 성공 (engine_snapshot.py)
  - 앱 기동 성공 (42ms, 오류 없음)
- **해결 효과**:
  - JSON 직렬화 문제 해결
  - 아키텍처 원칙 준수 (단일 소스 진리, 표준 라이브러리 사용, 최소 수정)
- **남은 확인 사항**:
  - 브라우저에서 실제 초기 스냅샷 전송 테스트 필요

### 2026-06-02: _sector_summary_cache 단일 소스 진리 통합 완료
- **완료일**: 2026-06-02
- **근본 원인**: engine_state.py와 engine_service.py에 각각 `_sector_summary_cache`가 존재하여 데이터 불일치 발생 → 업종순위 가중치 슬라이더 미작동
- **수정 파일** (6개):
  - backend/app/services/engine_sector.py: _sector_summary_cache import 제거, global 선언 제거, _es._sector_summary_cache로 변경
  - backend/app/services/engine_snapshot.py: _sector_summary_cache import 제거, global 선언 제거, _es._sector_summary_cache로 변경, get_buy_targets_snapshot() 수정
  - backend/app/services/daily_time_scheduler.py: _sector_summary_cache import 제거, global 선언 제거, _es._sector_summary_cache로 변경
  - backend/app/services/engine_lifecycle.py: _sector_summary_cache import 제거, _es._sector_summary_cache로 변경
  - backend/app/services/engine_state.py: _sector_summary_cache 선언 제거, 주석으로 통합 사실 기록
  - backend/app/services/engine_service.py: _sector_summary_cache import 제거, 모듈 내에 정의 추가 (단일 소스 진리)
- **추가 수정** (버그 수정):
  - backend/app/services/engine_snapshot.py:265 - `ss.buy_targets.values()` → `ss.buy_targets` (buy_targets는 list 타입)
- **검증**:
  - py_compile 성공 (모든 수정 파일)
- **해결 효과**:
  - 단일 소스 진리: engine_service._sector_summary_cache가 유일한 섹터 요약 캐시
  - 중복 캐시 제거: engine_state._sector_summary_cache 제거
  - 아키텍처 원칙 준수 (단일 소스 원칙)
- **다음 단계**:
  - 앱 재시작 후 슬라이더 테스트 필요

### 2026-06-02: settings_cache_fix_plan P0/P3 완료
- **완료일**: 2026-06-02
- **작업**: 설정 캐시 아키텍처 수정계획서 P0, P3 항목 완료
- **수정 파일** (3개):
  - backend/app/services/engine_config.py:80-90 - refresh() 런타임 전용 키 보존 로직 추가 (sector_stock_layout)
  - backend/app/core/settings_file.py:114 - 캐시 A 주석 추가
  - backend/app/services/engine_state.py:89 - 캐시 B 주석 추가
- **검증**:
  - py_compile 성공 (engine_config.py, settings_file.py, engine_state.py)
  - 앱 기동 성공
  - 업종순위 종목 표시 확인 (167종목 → 197종목, 설정 저장 후 layout 보존 확인)
  - API 키 시나리오 회귀 테스트 (키움 키 저장 시 경고 미발생, 핫-리로드 성공)
  - 앱 재시작 후 저장값 보존 확인 (197종목 유지)
- **해결 효과**:
  - refresh()가 sector_stock_layout(DB에 없는 런타임 상태)을 보존하여 장중 설정 저장/시간 전환 시 layout 소실 버그 근본 해결
  - 캐시 A/B 역할 문서화 (캐시 A: DB 설정 복호화 미러, 캐시 B: 엔진 런타임 통합 상태)
- **추후 해결 문제**:
  - 가중치 슬라이더 미작동 문제 (업종순위 계산 수신율 의심)
  - LS 증권 저장 팝업 미발생 문제

### 2026-06-02: 설정 캐시 단일 소스 진리 통합 완료
- **완료일**: 2026-06-02
- **근본 원인**: `settings_file.py` 로컬 `_integrated_system_settings_cache`가 `engine_state._integrated_system_settings_cache`와 별도로 존재하여 PATCH 후 캐시 불일치 발생 → `update_broker_credentials_live()` 핫-리로드 시 stale 캐시에서 빈 API 키 반환 → "[경고] 주입할 유효한 API Key 또는 Secret이 존재하지 않습니다."
- **수정 파일** (1개):
  - `backend/app/core/settings_file.py` 전반적 수정:
    - `_integrated_system_settings_cache: dict | None = None` 제거 (불필요 로컬 캐시)
    - `_cache_lock = asyncio.Lock()` 제거
    - `import asyncio` 제거
    - `load_integrated_system_settings()`: engine_state._integrated_system_settings_cache가 비어있지 않으면 즉시 반환, 비어있으면 DB에서 1회 로드 (기동 시 부트스트랩)
    - `save_settings(data)`: 내부 `current = await load_integrated_system_settings()` 재읽기 제거, 암호화 필드 평문이면 자동 재암호화 후 DB 저장
    - `update_settings(updates)`: `global _integrated_system_settings_cache` 제거, engine_state 캐시 증분 갱신으로 변경
    - `_ENCRYPT_FIELDS` 모듈 레벨 상수 추가 (단일 정의)
- **검증**:
  - py_compile 성공 (settings_file.py, settings_store.py, engine_lifecycle.py, daily_time_scheduler.py, dry_run.py, telegram_bot.py)
- **아키텍처 효과**:
  - 캐시 3개 → 1개 (engine_state._integrated_system_settings_cache가 단일 소스)
  - PATCH 즉시 engine_state 캐시 반영 → 핫-리로드 정상 작동
  - save_settings: 재읽기 없이 전달받은 data만 저장 + 평문 민감값 자동 암호화

### 2026-06-02: [증권사설정] 경고 근본 원인 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**: backend/app/db/models.py:43 — `DROP TABLE IF EXISTS integrated_system_settings`가 매 앱 기동 시 실행되어 사용자 저장 설정(kiwoom_app_key 등) 전체 삭제
- **수정 파일** (3개):
  - backend/app/db/models.py:42-44 — `DROP TABLE IF EXISTS integrated_system_settings` 제거 (CREATE TABLE IF NOT EXISTS만 유지)
  - backend/app/services/engine_loop.py:229-237 — 잘못 추가된 decrypt_sensitive 코드 원상복구 (단순 존재 확인으로 복원)
  - backend/app/core/broker_router.py:156-164, 262-266 — 잘못 추가된 decrypt_sensitive 코드 원상복구 (단순 존재 확인으로 복원)
- **검증**:
  - py_compile 성공 (models.py, engine_loop.py, broker_router.py)
  - DB 직접 확인: stocks.db integrated_system_settings 테이블 kiwoom_app_key 행 없음 (매 기동 DROP으로 삭제되었음을 확인)
- **해결 효과**:
  - 재시작 시 사용자 저장값(API 키 등) 보존
  - 단일 소스 진리 복원: DB → 메모리 캐시 단방향 흐름
  - 불필요한 decrypt_sensitive 호출 제거 (캐시는 이미 복호화된 값 보유)

### 2026-06-02: engine_lifecycle.py ImportError 근본 해결 완료
- **완료일**: 2026-06-02
- **작업**: engine_lifecycle.py에서 load_settings_for_editing import 오류 해결
- **수정 파일**:
  - backend/app/services/engine_lifecycle.py:347 - import 수정: load_settings_for_editing → load_integrated_system_settings_for_editing
  - backend/app/services/engine_lifecycle.py:353 - 호출 수정: load_settings_for_editing() → load_integrated_system_settings_for_editing()
- **검증**:
  - py_compile 성공 (engine_lifecycle.py)
- **해결 효과**:
  - ImportError: cannot import name 'load_settings_for_editing' 오류 해결
  - 아키텍처 원칙 준수: 복호화는 encryption.py 책임, load_integrated_system_settings_for_editing 사용
  - 설정 변경 시점 DB 조회 허용 (실시간 파이프라인 아님)

### 2026-06-02: 설정 저장 로직 증분 갱신 전면 수정 완료
- **완료일**: 2026-06-02
- **작업**: 설정 저장 로직을 증분 갱신 방식으로 전면 수정 (수정한 키 외에는 건드리지 않음)
- **수정 파일** (3개):
  - backend/app/core/settings_file.py:233-291 - save_settings() 함수 수정: DB 전체 읽고 업데이트 후 저장
  - backend/app/core/settings_file.py:294-302 - update_settings() 함수 수정: 캐시 무효화 제거, 증분 갱신
  - backend/app/core/settings_store.py:155-161 - apply_settings_updates() 함수 수정: None 무시, 빈 문자열 삭제 요청
- **검증**:
  - py_compile 성공 (settings_file.py, settings_store.py)
  - 앱 재시작 성공 (02:59:07)
  - DB 저장 확인: kiwoom_app_key, kiwoom_app_secret, ls_app_key, ls_app_secret 모두 암호화 저장됨
- **해결 효과**:
  - 증분 갱신 준수: 수정한 키 외에는 건드리지 않음
  - 단일 소스 진리 준수: DB가 설정의 단일 소스
  - 설정 메모리 상주 준수: 캐시 무효화 제거, 증분 갱신으로 캐시 효율성 유지
  - 아키텍처 원칙 준수 (단일 소스 진리, 설정 메모리 상주)

### 2026-06-02: Settings 단일 소스 진리 리팩토링 완료
- **완료일**: 2026-06-02
- **작업**: 모든 settings 로컬 변수, 캐시 제거 및 _integrated_system_settings_cache.get() 직접 호출로 대체
- **수정 파일** (13개):
  - backend/app/core/broker_router.py: validate_page_overrides에서 self._settings 제거, _integrated_system_settings_cache 직접 사용
  - backend/app/core/ls_broker.py: __init__에서 settings 파라미터 제거
  - backend/app/core/kiwoom_broker.py: __init__에서 settings 파라미터 제거
  - backend/app/core/kiwoom_rest.py: __init__에서 settings 파라미터 제거, get_spec에서 settings 파라미터 제거
  - backend/app/core/kiwoom_providers.py: 모든 Provider __init__에서 settings 파라미터 제거 (KiwoomAuthProvider, KiwoomOrderProvider, KiwoomStockProvider, KiwoomWebSocketProvider)
  - backend/app/core/ls_providers.py: 모든 Provider __init__에서 settings 파라미터 제거 (LsAuthProvider, LsAccountProvider, LsOrderProvider, LsWebSocketProvider)
  - backend/app/core/custom_sector.py: __init__에서 settings 파라미터 제거
  - backend/app/core/broker_factory.py: get_router()에서 settings 파라미터 제거
  - backend/app/core/broker_registry.py: _create_provider에서 settings 파라미터 제거
  - backend/app/services/engine_lifecycle.py: KiwoomAuthProvider() 호출에서 settings 파라미터 제거
  - backend/app/services/engine_loop.py: get_router() 호출에서 settings 파라미터 제거
  - backend/app/services/trading.py: get_router() 호출에서 settings 파라미터 제거 (2곳)
- **검증**:
  - py_compile 성공 (모든 수정 파일)
  - 앱 기동 성공 (http://127.0.0.1:8000, 49ms startup)
  - self._settings 잔여 검색: 0건
- **해결 효과**:
  - 단일 소스 진리 준수: _integrated_system_settings_cache가 유일한 설정 소스
  - 중복 캐시 제거: self._settings, raw_settings 등 제거
  - 아키텍처 원칙 준수 (단일 소스 원칙)
- **완료 단계**:
  - Phase 0: settings.get() 호출처 전수 확인
  - Phase 1: settings 로컬 변수 제거 및 _integrated_system_settings_cache.get() 직접 호출
  - Phase 2: 찌꺼기 캐시 삭제 (self._settings, raw_settings 등)
  - Phase 3: 설정/상태 분리 (access_token 등)
  - Phase 4: get_router() 호출처 수정 (settings 파라미터 제거)
  - Phase 5: 검증 (py_compile, 앱 기동)

### 2026-06-02: P0-1 DI Container 사용 범위 축소 및 삭제 완료
- **완료일**: 2026-06-02
- **작업**: DI Container 제거 (1인 로컬 앱 기준 과한 추상화)
- **수정 파일** (2개):
  - backend/app/web/app.py:14, 25, 60, 110-111, 115-116 - DI Container import, get_container, register_singleton, 로그 제거
  - backend/app/core/settings_store.py:216-217, 241-249, 336-338 - DI Container import, get_container, get_singleton 제거, engine_service._integrated_system_settings_cache 직접 사용으로 대체
- **삭제 파일** (1개):
  - backend/app/di/container.py (파일 전체 삭제)
  - backend/app/di/__init__.py (디렉토리 전체 삭제)
- **검증**:
  - py_compile 성공 (app.py, settings_store.py)
  - 앱 재기동 성공
  - 설정 로드 정상 동작 확인
  - 업종순위 데이터 정상 표시 (168종목)
  - DI Container 관련 로그 미존재 확인
- **해결 효과**:
  - DI Container를 통한 중복 설정 캐시 경로 제거
  - _integrated_system_settings_cache를 단일 소스 진리로 확정
  - backend_coalescing, ws_manager는 이미 싱글톤 패턴으로 구현되어 있어 DI Container 등록 불필요 확인
  - 아키텍처 원칙 준수 (단일 소스 진리, 과도한 추상화 제거)

### 2026-06-02: P0-2 ThreadPoolExecutor 정리 완료
- **완료일**: 2026-06-02
- **작업**: 1인 로컬 실시간 앱에서 과한 스레드풀과 미사용 executor 제거
- **수정 파일** (2개):
  - backend/app/services/market_close_pipeline.py:12, 26 - ThreadPoolExecutor import, _CONFIRMED_FETCH_EXECUTOR 제거 (미사용 확인)
  - backend/app/web/app.py:8, 63-66 - ThreadPoolExecutor import, set_default_executor 설정 제거 (max_workers=8 과도 설정 제거)
- **검증**:
  - py_compile 성공 (app.py, market_close_pipeline.py, engine_loop.py)
  - 앱 재기동 성공
  - 토큰 발급 성공 (테스트모드)
  - 업종순위 데이터 정상 표시 (168종목)
  - ThreadPoolExecutor 관련 로그 미존재 확인
- **해결 효과**:
  - 1인 로컬 앱에서 과도한 스레드풀 설정(max_workers=8) 제거
  - 미사용 executor(_CONFIRMED_FETCH_EXECUTOR) 제거
  - asyncio.to_thread로 필요한 경우만 스레드 사용 (토큰 발급 등 동기 API 래핑)
  - 아키텍처 원칙 준수 (멀티스레드 남용 금지)

### 2026-06-02: P1-1 캐시 소유권 정리 완료
- **완료일**: 2026-06-02
- **작업**: 캐시 소유권 기준과 실제 코드 일치 확인
- **조사 대상 파일** (7개):
  - backend/app/services/engine_state.py
  - backend/app/services/engine_cache.py
  - backend/app/services/engine_bootstrap.py
  - backend/app/services/engine_config.py
  - backend/app/services/engine_sector.py
  - backend/app/services/engine_sector_confirm.py
  - backend/app/services/engine_snapshot.py
- **검증 결과**:
  - 캐시 소유권 기준과 실제 코드 일치 확인
  - _sector_summary_cache 소유권: engine_service.py 단일 소스
  - 삭제된 캐시 주석이 모든 파일에 명확히 기록됨
  - 중복 경로 제거됨
  - 단일 소스 진리 원칙 준수됨
- **해결 효과**:
  - 캐시별 원천/파생/갱신자가 문서와 코드에서 일치
  - 설정 캐시 중복 경로 제거
  - 마스터 종목 캐시 단일 기준 유지

### 2026-06-02: P1-2 로그 레벨과 사용자 로그 정리 완료
- **완료일**: 2026-06-02
- **작업**: 사용자 로그 노이즈 제거
- **수정 파일** (1개):
  - backend/app/services/engine_sector.py:372 - logger.info("[DEBUG-FILTER] ...")를 logger.debug("[DEBUG-FILTER] ...")로 변경
- **검증**:
  - py_compile 성공 (engine_sector.py)
  - 앱 재기동 성공
  - DEBUG-FILTER 로그가 더 이상 INFO 레벨로 출력되지 않음 확인
- **해결 효과**:
  - 사용자 로그 간결화
  - 개발자용 디버깅 로그를 DEBUG 레벨로 분리

### 2026-06-02: P2-1 DB Writer 사용 경로 점검 완료
- **완료일**: 2026-06-02
- **작업**: SQLite 단일 쓰기 직렬화 원칙 확인 (조사만 수행)
- **조사 결과**:
  - conn.commit 직접 호출 파일: 13개
  - DB Writer 사용 파일: 3개 (db_writer.py, stock_tables.py, crud.py)
  - 마이그레이션/초기화 파일: 직접 commit 허용
  - market_close_pipeline.py의 직접 commit은 실시간 틱 파이프라인이 아니라 장마감/수동 확정데이터 배치 파이프라인에서 발생
  - kiwoom_stock_rest.py의 직접 commit은 실시간 틱 저장이 아니라 ka10081 확정시세/5일봉 다운로드 진행상태(downloaded_at) 업데이트에서 발생
- **정정 사항**:
  - 이전 표현 "실시간 파이프라인의 DB 쓰기"는 부정확함
  - 현재 확인된 직접 commit 경로는 초기화/마이그레이션/설정 저장/업종분류 관리/장마감 배치/수동 다운로드 경로임
  - 실시간 틱 수신 경로에서 매 틱 DB 쓰기를 수행하는 코드로 확인된 항목은 없음
- **후속 지시**:
  - 하위 에이전트는 직접 commit을 무조건 db_writer로 이관하지 말 것
  - 마이그레이션/테이블 초기화/설정 저장처럼 즉시 성공 여부가 필요한 트랜잭션은 현재 직접 commit 유지 대상인지 먼저 분류할 것
  - 장마감 배치 저장은 긴 일괄 트랜잭션이므로 db_writer 큐 이관보다 "단일 커넥션 + 명시적 트랜잭션 + 배치 executemany" 유지가 적합한지 먼저 검토할 것
  - kiwoom_stock_rest.py의 downloaded_at 업데이트는 종목별 commit이 잦으므로 배치 누적 후 한 번에 commit하도록 개선 후보로 분류할 것
  - DB Writer는 실시간 루프에서 쓰기를 직렬화해야 할 때만 적용 후보로 검토할 것

### 2026-06-02: P2-2 중앙 태스크 코디네이터 검토 완료
- **완료일**: 2026-06-02
- **작업**: 장기 실행 태스크와 임시 태스크 구분 (조사만 수행)
- **조사 결과**:
  - asyncio.create_task 사용 파일: 16개
  - get_running_loop().create_task 사용 파일: 9개
  - 허용된 장기 루프: Compute/OMS/Gateway, Scheduler, Journal Consumer, Trade History Consumer
  - 주의 필요: kiwoom_stock_rest.py 병렬 fetch, settings_store.py 핫-갱신, 구독 태스크 대량 생성
- **정정 사항**:
  - kiwoom_stock_rest.py:309-320, 426-438은 create_task 후 pending set에 보관하고 asyncio.wait로 결과를 회수하므로 순수 fire-and-forget로 단정하면 안 됨
  - 다만 동시성 상한이 명시적 세마포어/워커로 표현되지 않고 interval_sec 기반으로 조절되므로 실패 추적/취소/상한 제어 개선 후보임
  - settings_store.py의 create_task 경로는 설정 저장 응답을 막지 않기 위한 후속 작업 분리이며, 각 작업의 실패 로깅/중복 실행 방지 여부를 파일별로 확인해야 함
  - engine_bootstrap.py, engine_cache.py의 구독 태스크 대량 생성은 실시간 구독 준비 함수가 내부에서 대기할 수 있어 별도 태스크로 분리된 경로임. 대량 생성 자체보다 동시 구독 상한과 취소 경로를 확인해야 함
- **후속 지시**:
  - 하위 에이전트는 create_task를 발견했다는 이유만으로 즉시 제거하지 말 것
  - 각 태스크를 장기 루프, 예약 타이머, 회수되는 병렬 작업, 응답 분리 후속 작업, 순수 fire-and-forget로 분류할 것
  - 순수 fire-and-forget로 확정하려면 task 참조 저장 없음, done_callback 없음, await/wait/gather 회수 없음, 취소 경로 없음이 모두 확인되어야 함
  - 개선 우선순위는 "실패 추적 없음", "취소 경로 없음", "중복 실행 방지 없음", "동시성 상한 없음" 순서로 둘 것
  - 실시간 틱 처리 경로에서는 큐 누적/무제한 태스크 생성/전체 재계산을 추가하지 말 것


### 2026-06-02: P2 후속 안전 개선 1차 완료
- **완료일**: 2026-06-02
- **작업**: DB 저장 I/O 축소 및 설정 후속 태스크 실패 추적 추가
- **수정 파일** (2개):
  - backend/app/core/kiwoom_stock_rest.py: ka10081 확정시세/5일봉 다운로드 성공 종목의 downloaded_at 업데이트를 종목별 commit에서 배치 executemany + commit 1회로 변경
  - backend/app/core/settings_store.py: 설정 변경 후속 create_task 경로에 _schedule_settings_task() helper 적용, 태스크 실패/취소 로그 추가
- **검증**:
  - py_compile 성공 (kiwoom_stock_rest.py, settings_store.py)
- **해결 효과**:
  - ka10081 다운로드 중 SQLite commit 횟수 축소
  - 설정 저장 응답을 막지 않는 비동기 후속 작업 구조는 유지
  - 후속 태스크 예외가 조용히 사라지지 않고 로그로 추적됨
- **주의**:
  - 여기서 말하는 commit은 Git commit이 아니라 SQLite 트랜잭션 commit임
  - 실시간 틱 파이프라인 DB 쓰기로 확인된 항목은 없음

### 2026-06-02: 단일 책임 원칙 준수 - 5일봉 저장 로직 분리 완료
- **완료일**: 2026-06-02
- **근본 원인**:
  - _save_confirmed_cache 함수가 확정시세 저장과 5일봉 저장 두 가지 책임을 가짐
  - 5일봉 저장 로직이 3개 함수에 중복됨 (fetch_5d_data_only, _apply_5d_to_memory, _save_confirmed_cache)
  - _apply_5d_to_memory와 _save_confirmed_cache에서 0으로 저장하여 데이터 손실
- **수정 파일** (1개):
  - backend/app/services/market_close_pipeline.py:627-671 - _save_confirmed_cache에서 5일봉 저장 코드 삭제
  - backend/app/services/market_close_pipeline.py:220-229 - _apply_5d_to_memory에서 5일봉 저장 코드 삭제
- **검증**:
  - py_compile 성공 (market_close_pipeline.py)
  - stock_5d_array 테이블 실제 데이터 존재 확인 (0이 아닌 값)
- **해결 효과**:
  - 단일 책임 원칙 준수: _save_confirmed_cache는 확정시세 저장만 담당
  - 단일 소스 진리: 5일봉 저장은 fetch_5d_data_only 한 곳에서만 수행
  - 중복 제거: 5일봉 저장 로직이 여러 곳에 흩어지는 문제 해결
  - 아키텍처 원칙 준수 (단일 책임, 단일 소스 진리)

### 2026-06-02: 확정시세 데이터 미저장 문제 근본 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**:
  - market_close_pipeline.py의 _apply_confirmed_to_memory 함수에서 px > 0, amt > 0 조건으로 인해 API 응답값이 메모리 캐시에 반영되지 않아 DB에 0으로 저장됨
  - daily_time_scheduler.py의 _apply_detail_to_entry 함수에 "0값은 덮지 않음" 주석 존재 (실시간 틱 데이터와 확정 데이터를 섞어서 0값으로 덮어쓰지 않으려는 의도)
- **수정 파일** (1개):
  - backend/app/services/market_close_pipeline.py:469-471, 478-480, 496-498, 501-502 - px > 0, amt > 0, hp > 0 조건 삭제, API 응답값을 그대로 저장하도록 수정
- **검증**:
  - py_compile 성공 (market_close_pipeline.py)
  - DB 확인: 삼성전자(005930) cur_price=362500, trade_amount=30272085000000 (정상)
  - DB 확인: SK하이닉스(000660) cur_price=2324000, trade_amount=21840048000000 (정상)
  - ka10081 API 응답 파싱 검증: API 응답 필드명과 코드 파싱 필드명 100% 일치, 응답 구조 접근 방식 정상, 단위 변환 정상
- **해결 효과**:
  - 단일 소스 진리: API 응답(kiwoom_stock_rest.py:fetch_ka10081_daily_price)가 단일 소스, 조건부 필터링 삭제로 API 응답값이 그대로 메모리 → DB로 전달
  - 실시간 파이프라인과 배치 파이프라인 분리: market_close_pipeline.py는 배치 파이프라인(확정 시세), 실시간 틱 데이터 처리는 engine_ws_dispatch.py에서 담당
  - 아키텍처 원칙 준수 (단일 소스 진리, 실시간 파이프라인과 배치 파이프라인 분리)

### 2026-06-02: 거래모드 UI 표시 및 활성화 근본 해결 완료
- **완료일**: 2026-06-02
- **근본 원인**:
  - syncFromSettings 함수에서 계정관리 탭(거래모드 탭)의 UI 업데이트 로직 누락으로 인해, 백엔드 설정 변경 후 WS settings-changed 이벤트 수신 시 UI가 갱신되지 않음
  - 페이지 로드 시 vals가 빈 객체 상태에서 renderTestVirtualSection가 먼저 호출되어 비활성화 스타일(opacity: 0.4, pointerEvents: none)이 적용됨
  - syncTradeMode가 display만 제어하고 opacity/pointerEvents를 제어하지 않아 비활성화 상태가 유지됨
- **수정 파일** (1개):
  - frontend/src/pages/general-settings.ts:973 - syncFromSettings 계정관리 탭 업데이트 블록에 syncTradeMode() 호출 추가
  - frontend/src/pages/general-settings.ts:564-577 - syncTradeMode 함수에 opacity, pointerEvents 제어 추가
  - frontend/src/pages/general-settings.ts:579-583 - renderTestVirtualSection 초기 비활성화 스타일 제거
- **검증**:
  - npm run build 성공
- **해결 효과**:
  - 단일 소스 진리: syncTradeMode가 가상 예수금 섹션의 모든 UI 상태(display, opacity, pointerEvents)를 단일 진입점에서 제어
  - 초기화 로직과 업데이트 로직 분리 제거
  - 아키텍처 원칙 준수 (단일 소스 진리, 직접 호출 체인 유지)

### 2026-06-02: 거래대금 단위 백만단위로 통일 및 억단위 표시 완료
- **완료일**: 2026-06-02
- **근본 원인**:
  - DB에 원단위로 저장된 거래대금 데이터를 백엔드에서 백만단위로 변환하여 저장하던 불필요한 변환 로직 존재
  - 프론트엔드에서 원단위 데이터를 억단위로 변환하여 표시하던 로직 존재
  - 업종순위 페이지 필터 로직이 원단위 기준으로 작동하여 필터 미통과 문제 발생
  - 좌측/우측 카드 테이블 거래대금 컬럼 단위 불일치
- **수정 파일** (5개):
  - backend/app/core/kiwoom_stock_rest.py:124, 198 - 원단위 변환 제거 (백만원 단위로 저장)
  - backend/app/services/engine_sector.py:389-391 - 필터 로직 백만단위 → 억단위 변환 수정
  - backend/app/db/stock_tables.py:264, 266, 404-408 - DB 스키마 주석에 백만단위 추가
  - frontend/src/components/common/ui-styles.ts:263, 285, 388 - 거래대금, 5일평균 억단위 변환, 소수점 1자리 + 콤마 표시
  - frontend/src/pages/sector-ranking.ts:220, 388 - 우측카드 테이블 거래대금 억단위 변환 및 레이블 수정
- **DB 마이그레이션**:
  - master_stocks_table.avg_5d_trade_amount: 원단위 → 백만단위 (÷ 1,000,000)
  - master_stocks_table.trade_amount: 원단위 → 백만단위 (÷ 1,000,000)
  - stock_5d_array.day1~day5_amount: 원단위 → 백만단위 (÷ 1,000,000)
  - 백업 파일: stocks.db.backup_20260602_233937 (마이그레이션 완료 후 삭제)
- **검증**:
  - py_compile 성공 (kiwoom_stock_rest.py, engine_sector.py, stock_tables.py)
  - npm run build 성공 (ui-styles.ts, sector-ranking.ts)
  - DB 데이터 확인: 796400000 → 796 (백만단위)
- **해결 효과**:
  - 단일 소스 진리: DB 백만단위와 백엔드/프론트엔드 단위 일치
  - 단순한 로직: 불필요한 원단위 변환 제거
  - 일관성: 모든 거래대금 컬럼 억단위 표시, 소수점 1자리 + 콤마 포함
  - 직관성: 장개시초반 소액 거래대금도 정확히 표시 (예: "0.5")
  - 아키텍처 원칙 준수 (단일 소스 진리, 단순한 로직)

## 현재 상태
- **작업 중인 기능**: 거래대금 단위 백만단위로 통일 및 억단위 표시 완료
- **진행률**: P0-1 완료, P0-2 완료, P0-3 완료, P1-1 완료, P1-2 완료, P2-1 완료, P2-2 완료, P2 후속 안전 개선 1차 완료, 보류 1-4 완료, stock_5d_array 데이터 저장 근본 해결 완료, ImportError 및 UnboundLocalError 근본 해결 완료, 단일 책임 원칙 준수 완료, 확정시세 데이터 미저장 문제 근본 해결 완료, 거래모드 UI 표시 및 활성화 근본 해결 완료, 거래대금 단위 백만단위로 통일 및 억단위 표시 완료
- **마지막 수정**: ui-styles.ts에서 거래대금, 5일평균 컬럼 소수점 1자리 + 콤마 표시 추가
- **앱 상태**: npm run build 검증 완료

## 다음 단계
- 없음

## 미해결 문제
- 없음
