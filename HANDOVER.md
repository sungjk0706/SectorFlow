# HANDOVER — SectorFlow

## 완료 단계
- 2026-07-01: 헤더 투자모드 인디케이터 위치 개선 — 빌드 검증 + 사용자 화면 확인 완료
  - **modeChip 위치 이동**: 증권사 칩 뒤 → 로고(`🌊 SectorFlow`) 바로 우측으로 이동. `margin-right:auto`를 modeChip에 부여하여 좌측 그룹(로고+모드)과 우측 그룹(나머지 칩) 분리.
  - **시각적 강조**: `font-size:12px`, `padding:4px 12px`, `font-weight:700`로 다른 칩보다 한 단계 크고 굵게 표시.
  - **파일**: `frontend/src/layout/header.ts:127-135`
- 2026-07-01: 앱 기동 지연 근본 원인 분석 및 수정 완료 — 코드 기반 검증 완료
  - **수정 1: SectorFlow.command health check URL 수정** — `curl -s http://localhost:8000/health` → `http://localhost:8000/api/health` (`SectorFlow.command:51`). 잘못된 URL로 인한 30초 타임아웃 대기 제거.
  - **수정 2: SPA fallback catch-all 라우트에서 /api/* 경로 404 반환** — `backend/app/web/app.py:313-317`에 `api/` 가드 추가. 존재하지 않는 API 경로가 `index.html` 200으로 응답하던 silent fallback 제거. 아키텍처 원칙 7(왜곡 금지), 20(폴백 금지) 부합.
- 2026-06-30: 앱 기동 시간 증가 근본 원인 분석 및 수정안 1~4 적용 완료 — 코드 기반 검증 완료
- 2026-06-30: 실시간 데이터 비동기화 근본 원인 분석 및 수정 완료 — 코드 기반 검증 완료
- 2026-06-30: WS 브로드캐스트 정리 — pipeline_gateway.py 데드 코드 제거, 배치 전송 모듈 파일 삭제 및 import 제거, ws_manager.py _state_queue/_event_queue/_flush_loop 전면 제거 — 코드 기반 검증 완료
- 2026-06-30: 업종지수 실시간 데이터 처리 및 헤더 표시 구현 — 코드 기반 검증 완료
- 2026-06-30: 매수 시도 누락 버그 수정 — evaluate_buy_candidates() 호출이 스켈레톤 모드(비활성) 경로에만 배치되어 실제 운영 경로에서 매수 시도가 발생하지 않던 문제 수정 — 코드 기반 검증 완료
- 2026-07-01: 설정 관리 및 텔레그램 알림 리팩토링 (3개 수정안) — 코드 기반 검증 완료
  - **수정안 1: settings.py 하드코딩 개선** — `apply_settings_updates()`가 `set[str]` 반환, `engine_service.apply_settings_change(changed_keys)`로 전달
  - **수정안 2: 텔레그램 채널 분리** — `telegram_bot_token` → `telegram_bot_token_test` + `telegram_bot_token_real` 분리, `[테스트모드]` 접두사 제거, `_select_token()`이 trade_mode 기반 토큰 선택, 레거시 마이그레이션(`_migrate_telegram_token_split`) 추가
  - **수정안 3: Pending Changes 도입** — 엔진 미실행 시 설정 변경을 `system_state_cache`에 저장(`save_pending_settings`), 엔진 기동 시 `load_pending_settings` → `apply_settings_change` → `clear_pending_settings` 적용

- 2026-07-04: 업종순위 로직 8aee1b8 기준 복원 + sector_weights 폴백 제거 — py_compile + npm run build 검증 완료
  - **git checkout 복원**: `sector_calculator.py`, `settings_file.py`, `sector-ranking.ts` 3개 파일
  - **수동 복원**: `models.py` (DEFAULT_METRICS, SectorScore, SectorRankPrimary), `settings_defaults.py` (sector_weights 기본값), `engine_settings.py` (sector_weights fallback), `sector_data_provider.py` (snapshot 반환 필드), `types/index.ts` (SectorScoreRow), `sliderConvert.ts` (의존 유틸)
  - **폴백 제거**: `backend/app/core/engine_settings.py:132`에서 `merged.get("sector_weights") or {...}` → `merged["sector_weights"]`로 변경. DEFAULT_USER_SETTINGS가 항상 sector_weights를 보장하므로 or 폴백은 도달 불가능. 원칙 #20(폴백 금지) 준수.
  - **커밋**: `5a11d34` — 푸시 완료
- 2026-07-04: 코딩 에이전트 도구 인프라 구축 — 4개 우선순위 설치 및 설정 완료
  - **우선순위 1: ruff + mypy 설치** — `.venv/bin/pip install ruff mypy`. ruff 521 errors, mypy 14 errors (기존 코드, 별도 수정 필요)
  - **우선순위 2: requirements.txt 생성** — `.venv/bin/pip freeze > requirements.txt` (61개 패키지)
  - **우선순위 3: 테스트 코드 작성** — `backend/tests/test_sector_score.py` (17개), `backend/tests/test_settings_file.py` (9개). pytest 26 passed. `pytest.ini` 설정 (asyncio_mode=auto)
  - **우선순위 4: eslint 설치** — `eslint`, `@typescript-eslint/*`, `@eslint/js`, `globals` 설치. `eslint.config.js` flat config 생성. 9 errors, 23 warnings (기존 코드, 별도 수정 필요)

- 2026-07-04: mypy 에러 0건 달성 — 모든 에러 타입 수정 완료
  - **수정 파일 (13개)**:
    - `backend/app/core/kiwoom_stock_rest.py` — `list(rows[:5])` 캐스팅 (assignment)
    - `backend/app/web/ws_manager.py` — `filtered_values` 타입 annotation + `subscribed_fids` None guard (no-redef)
    - `backend/app/web/routes/stock_classification.py` — `sector_counts` 타입 annotation (var-annotated)
    - `backend/app/core/ls_connector.py` — `change`/`drate` → `change_str`/`drate_str` 변수명 변경 (assignment)
    - `backend/app/services/engine_ws_reg.py` — missing return 추가 (return-value)
    - `backend/app/services/engine_ws.py` — truthy-function 조건 제거
    - `backend/app/services/engine_snapshot.py` — `get_position_pnl_pct_for_code` async 변환 (await-not-async)
    - `backend/app/services/engine_radar.py` — 타입 annotation + truthy-function 제거 + `Any` import
    - `backend/app/services/engine_config.py` — truthy-function 제거
    - `backend/app/services/engine_account.py` — async 변환, 변수명 충돌 해결, truthy-function 3건, lambda 시그니처 수정, keyword arg 수정
    - `backend/app/services/engine_service.py` — `schedule_engine_task` keyword arg 수정
    - `backend/app/services/market_close_pipeline.py` — `_eta` float annotation 2건
    - `backend/app/core/journal.py` — stats 카운터 별도 int 변수 분리
  - **검증**: `.venv/bin/mypy backend/app/ --ignore-missing-imports --explicit-package-bases` — 에러 0건
- 2026-07-04: engine_service.py 파사드 re-export 누락 12개 함수 수정 — 앱 기동 ImportError 해결
  - **원인**: mypy 수정 과정에서 `engine_service.py`의 re-export 블록에서 누락된 함수들 발생
  - **누락 함수 및 추가 위치**:
    - `start_engine`, `stop_engine` → `engine_lifecycle` import 블록에 추가
    - `_get_settings` → `engine_config` import 블록에 추가
    - `get_sector_stocks`, `get_buy_targets_sector_stocks`, `get_all_sector_stocks`, `get_sector_scores_snapshot`, `get_sector_summary_inputs` → `sector_data_provider` import 블록에 추가
    - `build_initial_snapshot`, `build_sector_stocks_payload` → `engine_snapshot` import 블록에 추가
    - `_update_account_memory` → `engine_account` import 블록에 추가
    - `_broker_message_handler` → `engine_ws` import 블록에 추가 (신규)
  - **수정 파일**: `backend/app/services/engine_service.py:25-72`
  - **검증**: 모든 import 성공, `from backend.app.web.app import app` 성공, mypy 0건 유지
  - **남은 사항**: `SectorFlow.command`로 실제 앱 기동 후 런타임 에러 없음 확인 필요 (사용자가 직접 실행)
- 2026-07-04: ruff lint 에러 0건 달성 — F401, F821, F841, E402 전면 수정 완료
  - **F401 (13건)**: `engine_service.py` facade re-export 12건에 `# noqa: F401` 추가, `market_close_pipeline.py` 1건 `StockFilterEvaluation` import 제거 (문자열 annotation이므로 런타임 불필요)
  - **F821 (3건)**: `engine_state.py`에 `TYPE_CHECKING` block 추가 — `ConnectorManager`, `AuthProvider`, `SectorScore` import
  - **F841 (16건)**: 12개 파일에서 미사용 지역변수 제거 — `broker_router.py`(`broker_name`), `kiwoom_stock_rest.py`(`high_price_5d`), `settings_store.py`(`legacy_k`, `legacy_s`), `engine_account.py`(`settings`), `engine_sector_confirm.py`(`inputs`, `logger`), `engine_snapshot.py`(`payload_bytes`), `engine_ws_dispatch.py`(`iy`, `sample_s`, `msg`, `ok_rc`, `typ`, `grp` 6건), `status.py`(`ob_data`), `ws_manager.py`(`payload_bytes`)
  - **E402 (308건/72파일)**: PEP 8 header 재배치 — encoding comment → docstring → `from __future__` → imports 순서로 72개 파일 header 일괄 수정. `engine_service.py`, `pipeline_compute.py`, `web/app.py`, `ws_manager.py`는 import 사이 변수 할당으로 인한 E402 별도 수동 수정
  - **검증**: `.venv/bin/ruff check backend/app/` — 0건 (All checks passed), `.venv/bin/mypy backend/app/ --ignore-missing-imports --explicit-package-bases` — 0건 (106 source files), `import backend.app.web.app` — Import OK

- 2026-07-04: eslint 9 errors 수정 완료 — `npm run build` 검증 통과
  - **수정 파일 (4개)**:
    - `frontend/src/api/client.ts` — `RequestInit` 타입을 `globalThis.RequestInit`으로 변경 (no-undef), 불필요한 이스케이프 제거 (no-useless-escape)
    - `frontend/src/pages/sector-ranking.ts` — `HTMLCollectionOf` 타입을 `globalThis.HTMLCollectionOf`로 변경 (no-undef)
    - `frontend/src/pages/stock-classification.ts` — 상수 binary expression 단순화 (no-constant-binary-expression), 빈 catch block에 주석 추가 (no-empty)
    - `frontend/src/types/index.ts` — `namespace` 선언을 `interface` + `export type`으로 변경 (@typescript-eslint/no-namespace)
  - **검증**: `npx eslint src/` — 0 errors, `npm run build` — 성공

- 2026-07-04: sector_calculator.py 파이프라인 테스트 커버리지 확대 — 31개 테스트 작성 (실행 시 hang 발생)
  - **신규 파일**: `backend/tests/test_sector_calculator.py` — 31개 테스트
  - **커버 범위**: `compute_sector_scores` + `compute_full_sector_summary` 전체 파이프라인
    - 빈 입력, 단일/다중 업종, 데이터 우선순위, 평균거래대금 필터링, min-max 트리밍, 비율 계산, 체결강도 파싱, 가중치 효과, 요약 계산
  - **테스트 방식**: `state.master_stocks_cache` 직접 조작으로 DB 의존성 제거, pytest fixture로 캐시 백업/복원
  - **추가 파일**: `conftest.py` (프로젝트 루트) — pytest 모듈 발견용 빈 파일 (이후 삭제됨)
  - **검증**: `pytest --collect-only` 57개 정상 수집(0.29s). `test_settings_file.py` 9 passed, `test_sector_score.py` 17 passed. **`test_sector_calculator.py` 31개 테스트 실행 시 hang 발생** (원인: `engine_state.py:45-46`의 `asyncio.Event()` 즉시 생성 vs pytest-asyncio per-test 루프 불일치)

- 2026-07-05: `is_skeleton_mode` dead code 전면 제거 — py_compile 검증 완료, pytest hang 발견 (코드 수정 자체는 정상)
  - **수정 1: `models.py` 필드 제거** — `SectorSummary` dataclass에서 `is_skeleton_mode: bool = False` 필드 제거. (`backend/app/domain/models.py:69`)
  - **수정 2: `engine_sector_confirm.py` 조건문 제거** — `if existing.is_skeleton_mode:` 블록 및 `_skeleton_incremental_update()` 호출 + return 제거. 항상 False인 dead branch. (`backend/app/services/engine_sector_confirm.py:94-98`)
  - **수정 3: `engine_sector_confirm.py` 함수 전체 제거** — `_skeleton_incremental_update()` 함수 전체 제거. 유일한 호출처가 제거되어 완전한 dead code. (`backend/app/services/engine_sector_confirm.py:207-325`)
  - **검증**: 잔여 문자열 검색 0건, `py_compile` 성공. **주의**: `pytest backend/tests/test_sector_calculator.py` 실행 시 hang 발생 (원인: `engine_state.py:45-46`의 `asyncio.Event()` 즉시 생성 vs pytest-asyncio per-test 루프 불일치). 코드 수정 자체는 정상이나 테스트 실행 환경 문제로 인해 31 passed 검증 불가.
  - **아키텍처 부합**: 원칙 16(구현 = 살아있는 경로에 배선됨), 원칙 10(SSOT), 원칙 20(폴백 금지), 원칙 17(플래그 단일 소스)

- 2026-07-04: Vitest 설치 및 프론트엔드 핵심 유틸 단위 테스트 — 46 passed, `npm run build` 검증 통과
  - **설치**: `vitest@^3.2.6`, `jsdom` (devDependencies)
  - **신규 테스트 파일 (4개)**:
    - `frontend/tests/utils/sliderConvert.test.ts` — 11개 테스트 (서버↔화면값 변환, round-trip)
    - `frontend/tests/router.test.ts` — 11개 테스트 (resolveRoute: 레거시 리다이렉트, 빈 해시, 알 수 없는 경로)
    - `frontend/tests/settings.test.ts` — 14개 테스트 (extractDirty: 변경 감지, 마스킹 필드 제외, MASKED_FIELDS 검증)
    - `frontend/tests/stores/store.test.ts` — 10개 테스트 (createStore: 초기값, setState, 구독자 통지, Object.is 비교, 구독 해제)
  - **수정**: `frontend/tsconfig.json` — `include`에 `"tests"` 추가 (테스트 파일 타입 검사 범위 포함)
  - **검증**: `npx vitest --run` — 46 passed (4 files), `npm run build` — 성공

- 2026-07-05: AI 메모리 최적화 — user_rules 통합 및 중복 제거 완료
  - **user_rules (user_global) 업데이트**: 기존 "문제해결 참고서"만 있던 user_rules에 프로젝트 개요, 아키텍처 불변 원칙 20개 요약, 핵심 워크룰 8개, 금지 패턴(Python/TypeScript/공통), 시장 정보, 세션 시작 체크리스트, 테스트 점검 프로세스 통합. 새 세션 시작 시 코딩 AI 에이전트가 프로젝트 맥락을 자동 인지
  - **Memory 2 (3993bd1d) 업데이트**: "문제해결 참고서" 섹션 삭제 (user_rules에 통합으로 중복 제거), `[협업/문서화]` 섹션 → `[Git 관리]`로 재분류 (1인 개발에 맞지 않는 협업 규칙 제거, CHANGELOG/API 문서화 삭제, 커밋 메시지 규칙만 유지)
  - **Memory 4 (d2bb739f) 삭제**: "테스트 실행 및 점검 프로세스"가 user_rules에 통합되어 완전 중복 → 삭제
  - **현재 메모리 구성**: user_global (항상 로드, 프로젝트 가이드+문제해결), Memory 1 (아키텍처 상세), Memory 2 (실행 가이드 상세), Memory 3 (업종순위 로직 변경 계획)

- 2026-07-05: ARCHITECTURE.md 스켈레톤 구현 기법 7건 문서-코드 불일치 수정 — 잔여 검색 0건
  - **수정 내용**: `is_skeleton_mode` dead code 전면 제거(2026-07-05) 후 ARCHITECTURE.md 미동기화 7건 수정. 구체적 구현 기법은 ARCHITECTURE.md(설계도)에서 제거하고 HANDOVER.md(작업 일지)에서 관리.
  - **수정 파일**: `ARCHITECTURE.md` 7개 위치:
    - line 505: 파이프라인 다이어그램에서 `스켈레톤 모드 → _skeleton_incremental_update()` 행 제거
    - line 612: SectorSummary 구조도에서 `├── is_skeleton_mode` 행 제거
    - line 649: 증분 연산 모드 표에서 `스켈레톤 증분` 행 제거
    - line 651-657: 스켈레톤 델타 연산 (4대 상태 전환) 표 전체 제거
    - line 1149: 모듈 설명 `업종 재계산 (증분/스켈레톤)` → `업종 재계산 (증분)` 수정
    - line 1445-1451: `### 4.4 스켈레톤 증분 연산` 섹션 전체 제거
    - line 1680: 변경 로그에서 `Per-tick 제거: → 스켈레톤 증분 연산 도입` 행 제거
  - **검증**: ARCHITECTURE.md 내 `skeleton|스켈레톤|is_skeleton_mode|_skeleton_incremental_update` 검색 0건. `backend/app` 전체 동일 검색 0건 (주석 1건은 정상). frontend 프로젝트 코드 0건.
  - **아키텍처 부합**: 원칙 16(구현 = 살아있는 경로에 배선됨), 원칙 10(SSOT), 원칙 20(폴백 금지), 원칙 17(플래그 단일 소스)

- 2026-07-05: 루트 폴더 구조 정리 — 불필요 파일/폴더 7개 삭제, requirements.txt 단일화, 빌드 산물 정리
  - **삭제 파일/폴더 (7개)**:
    - `ARCHITECTURE.md.backup` — 과거 백업 파일, 코드/문서 참조 없음
    - `conftest.py` (루트) — 0바이트 빈 파일, pytest.ini가 testpaths 지정하여 불필요
    - `memory_monitor_log.txt` — 2026-07-03 1회성 로그, 코드 참조 없음
    - `backend/protobuf/` (event.proto + event_pb2.py) — 앱 코드에서 import 없음
    - `backend/scripts/` — 원본 소스 없음, pyc만 잔류
    - `requirements.txt` (루트) — `pip freeze` 일회성 출력, SSOT 위반 → `backend/requirements.txt`로 단일화
  - **수정 파일**: `backend/requirements.txt` — protobuf 줄 제거 (사용처 없음)
  - **빌드 산물 정리**: `.DS_Store` 3개, `frontend/dist/`, `frontend/tsconfig.tsbuildinfo`
  - **검증**: py_compile main.py ✅, tsc --noEmit ✅, pytest 개별 파일 26 passed (test_settings_file.py 9 + test_sector_score.py 17), test_sector_calculator.py hang 발생, vitest 46 passed ✅

## 현재 상태
- **2026-07-05 01:44 기준**: ARCHITECTURE.md 스켈레톤 불일치 7건 수정 완료. ruff 0건, mypy 0건, eslint 0 errors (23 warnings). pytest 개별 파일 26 passed (test_settings_file.py 9 + test_sector_score.py 17), test_sector_calculator.py hang 발생 (미해결), vitest 46 passed. **pytest 전체 실행 시 hang 문제 발생 (미해결)**
  - 앱 기동 로그 정상: `[시작] 데이터준비 완료`, `[업종순위] 재계산 완료`, `[시작] 기동 완료`, `Application startup complete`
  - WS 연결 성공: prices, settings, orders 3개 채널 연결 확인
  - **해결된 에러**: `ImportError: cannot import name 'build_initial_snapshot'` → re-export 추가로 해결
  - **검증 완료**: 모든 import 성공, `from backend.app.web.app import app` 성공, mypy 0건
- 2026-07-02: 계좌현황 브로드캐스트 아키텍처 위반 4건 근본 수정 완료 — py_compile + tsc --noEmit 검증 완료, 런타임 검증 필요 (장중)
  - **위반 1 수정: `create_task` 분리 제거** — `_broadcast_account`를 `async def`로 변경, `loop.create_task(_do_broadcast_account())` 제거, `_do_broadcast_account`를 `_broadcast_account`에 통합. 모든 호출처(7개 파일)에 `await` 추가. (`engine_account.py:449-461`)
  - **위반 2 수정: `try-except` 삼키기 `logger.debug` → `logger.warning` 승격** — `engine_account.py:461`, `settlement_engine.py:257`
  - **위반 3 수정: DEBUG 로그 제거** — `engine_account.py:367-370`, `engine_account_notify.py:473-477,489`, `hotStore.ts:123-127`
  - **위반 4 수정: docstring 불일치 해결** — `_refresh_account_snapshot_meta` docstring 수정. (`engine_account.py:312-317`)
  - **추가 수정: `_dryrun_post_sell_broadcast` async화** — `trading.py:520`에 `await` 추가.
- 2026-07-02: 실시간 PnL 업데이트 사망 경로 리팩토링 완료 — py_compile 검증 완료, 런타임 검증 필요 (장중)
  - **근본 원인**: `_normalize_real_type("0B")`이 `"01"`을 반환하므로 `norm == "0B"` 조건 미충족 → 체결 틱 silently drop
  - **해결**: `_handle_real_01` 로직을 `pipeline_compute.py._handle_real_01_tick`로 이관. `engine_ws_dispatch.py._handle_real_01`은 stub화.
  - **수정 파일**: `pipeline_compute.py:378-518`, `engine_ws_dispatch.py:210-219`

## 다음 단계

### 1순위: pytest hang 해결 (코드 수정 필요)
- **원인**: `engine_state.py:45-46`에서 `asyncio.Event()`를 `EngineState.__init__` 시점에 즉시 생성. 모듈 로드 시점의 이벤트 루프에 영구 바인딩됨. pytest-asyncio는 각 테스트마다 새 루프 생성 → 루프 불일치로 teardown 단계에서 hang.
- **해결 방안**: `data_ready_event`와 `token_ready_event`를 `LazyEvent` 패턴으로 전환 (`engine_utils.py:9-32` 참조). 수정 범위: `engine_state.py:45-46` 2줄.
- **검증**: `pytest backend/tests/test_sector_calculator.py` — 31개 테스트 hang 없이 통과해야 함. `pytest --tb=short` 전체 실행 시 57개 테스트 통과해야 함.
- **관련 파일**: `engine_state.py:45-46`, `engine_utils.py:9-32`, `pytest.ini`, `backend/tests/`

### 2순위: 토큰 검증 재활성화 (TODO 주석 8건)
- **대상**: `deps.py:13`, `ws.py:164`, `ws_orders.py:18`, `ws_settings.py:18`, `client.ts:18,29,40,69`
- **조건**: 개발 완료 후 재활성화

### 3순위: 종목수 불일치 (런타임 확인 필요)
- **대상**: `_apply_confirmed_to_memory`(`market_close_pipeline.py:357`)에서 새 엔트리 생성 의심
- **조건**: 장중 런타임 확인 필요 (우선순위 낮음)

### 완료된 항목 (참고용)
- **앱 기동 확인 (완료)**: WS 초기 스냅샷 전송 성공, `ImportError` 미발생, 프론트엔드 데이터 정상 표시 확인됨
- **정적 분석 (완료)**: ruff 0건, mypy 0건, eslint 0 errors (23 warnings)
- **Vitest (완료)**: 4개 파일 46개 테스트 작성, `npm run build` 성공
- **ARCHITECTURE.md 스켈레톤 불일치 (완료)**: 7건 수정, 잔여 검색 0건 (2026-07-05)
- **장중 런타임 검증 (대기)**: 실시간 PnL, 업종지수, 매수 시도, 데이터 동기화, 텔레그램 분리, Pending Changes, 레거시 마이그레이션 — 장중 사용자 직접 확인 필요

## 미해결 문제
- **pytest 전체 실행 시 hang (2026-07-05 발견, 원인 특정 완료)**: `pytest --tb=short` 전체 실행 시 무한 대기 발생. 개별 파일 실행 시 `test_settings_file.py` 9 passed (0.59s), `test_sector_score.py` 17 passed (0.72s) 정상 종료. **`test_sector_calculator.py` 단독 실행 시 10초 초과 hang 발생**.
  - **원인 특정 완료 (2026-07-05 01:15 코드 기반 확인)**: `engine_state.py:45-46`에서 `asyncio.Event()`를 `EngineState.__init__` 시점에 즉시 생성. 모듈 로드 시점의 이벤트 루프에 영구 바인딩됨. pytest-asyncio 1.4.0 (`asyncio_mode=auto`, `asyncio_default_test_loop_scope=function`)은 각 테스트마다 새 루프 생성 → 루프 불일치로 teardown 단계에서 hang. `test_settings_file.py`와 `test_sector_score.py`는 `engine_state`를 import하지 않아 hang 미발생.
  - **해결 방안**: `data_ready_event`와 `token_ready_event`를 `LazyEvent` 패턴으로 전환 (`engine_utils.py:9-32` 참조). 수정 범위: `engine_state.py:45-46` 2줄.
  - `pytest --collect-only` 실행 결과: 57개 정상 수집 (0.29s) — 수집 단계 hang 아님
  - `pytest -x --timeout=10` 실행 불가: pytest-timeout 플러그인 미설치
  - `pytest --asyncio-mode=auto` 설정과 pytest-asyncio 버전(1.4.0) 호환성 확인: 루프 스코프 불일치가 원인
  - 루트 `conftest.py` 삭제 영향 확인: `pytest.ini`의 `testpaths = backend/tests`로 대체 정상
  - 관련 파일: `pytest.ini`, `backend/tests/`, `backend/tests/__init__.py`, `backend/app/services/engine_state.py:45-46`
- **TODO 주석 8건 (토큰 검증 재활성화)**: `deps.py:13`, `ws.py:164`, `ws_orders.py:18`, `ws_settings.py:18`, `client.ts:18,29,40,69`. 모두 "개발 완료 후 토큰 검증 재활성화" 관련. (라인 번호 2026-07-05 코드 기반 재확인)
- **종목수 불일치**: `_apply_confirmed_to_memory`(`market_close_pipeline.py:357`)에서 새 엔트리 생성 의심. 런타임 확인 필요 (우선순위 낮음).
- **ARCHITECTURE.md 문서-코드 불일치 (2026-07-05 해결 완료)**: 스켈레톤 구현 기법 7건 불일치 수정 완료. 잔여 검색 0건. 상세 내용은 완료 단계 참조.

## 개선 필요 영역 (코드 기반 확인)

### 1. 단일 종목 비중 한도 (이미 구현됨)
- **현상**: `risk_manager.py:39,90-92`에서 `max_single_stock_exposure` 로직 이미 구현됨. `settings_defaults.py:61`, `engine_settings.py:79`에서 설정값 관리. TODO 주석 없음.

### 2. 리스크 임계치 (설정값 관리됨)
- **현상**: `max_daily_loss_limit`, `max_total_exposure_ratio` 등이 `settings_defaults.py:60,62`, `engine_settings.py:78,80`에서 설정값 관리됨. 하드코딩 아님.

### 3. 다중 증권사 WS 동시 구독 (ConnectorManager 구현됨)
- **현상**: `connector_manager.py:18`에서 `ConnectorManager` 클래스 구현됨. 다중 증권사 WS 연결 지원. 구독 분산 최적화는 미구현 상태.
- **위치**: `backend/app/core/connector_manager.py`, `backend/app/services/engine_ws_reg.py`
- **영향**: 종목 구독이 단일 증권사에 집중 시 WS 세션 한도 도달 가능
- **관련 파일**: `connector_manager.py`, `engine_ws_reg.py`, `kiwoom_connector.py`, `ls_connector.py`

### 4. 프론트엔드 프레임워크 (Vanilla TypeScript 사용 중)
- **현상**: Vanilla TypeScript로 구현, 컴포넌트 재사용성 및 상태관리 한계
- **위치**: `frontend/src/` 전체
- **영향**: 페이지 간 공통 로직 중복, 상태 동기화 복잡도 증가
- **관련 파일**: `frontend/src/binding.ts`, `frontend/src/stores/`, `frontend/src/pages/`

### 5. 백업/복구 자동화 (수동 백업만 가능)
- **현상**: `stocks.db` 수동 백업만 가능, 자동 백업 스크립트 없음
- **위치**: `backend/data/stocks.db` (단일 파일)
- **영향**: DB 손상 시 복구 불가
- **관련 파일**: `SectorFlow.command`, `backend/app/db/database.py`

### 6. 테스트 자동화 인프라 구축 (2026-07-04, 부분 미해결)
- **현상**: pytest + Vitest 기반 단위 테스트 인프라 구축. 총 72 passed, 31 hang.
  - **Python backend**: `test_sector_score.py` (17개 passed), `test_settings_file.py` (9개 passed) — pytest 26 passed. `test_sector_calculator.py` (31개) — hang 발생 (미해결)
  - **TypeScript frontend**: `sliderConvert.test.ts` (11개), `router.test.ts` (11개), `settings.test.ts` (14개), `store.test.ts` (10개) — vitest 46 passed
- **위치**: `backend/tests/`, `frontend/tests/`, `pytest.ini`, `frontend/vitest.config.ts`
- **남은 사항**: 프론트엔드 컴포넌트/UI 테스트 (jsdom 환경 활용), 백엔드 통합 테스트 (DB 의존성 포함)
- **관련 파일**: `backend/tests/test_sector_score.py`, `backend/tests/test_settings_file.py`, `backend/tests/test_sector_calculator.py`, `frontend/tests/**/*.test.ts`, `pytest.ini`, `frontend/vitest.config.ts`
