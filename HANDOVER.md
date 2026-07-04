# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 종목수 불일치 정밀 검증 완료** — 코드 버그 아님 확인
  - `_apply_confirmed_to_memory`(`market_close_pipeline.py:354`) 새 엔트리 생성 경로(`:405-433`)는 dead code — Step 4(`:867-893`)에서 `confirmed_codes` 전체 종목 캐시 생성 후 호출되므로 도달 불가
  - 런타임 로그 2일치 교차 검증: 07-03 타이머, 07-04 수동 모두 Step 4 = 다운로드 = 메모리 반영 = 1339종목 (실패 0건)
  - Step 5 다운로드 실패 시 가격 미갱신 종목 발생 가능하나 캐시 종목수는 항상 `confirmed_codes`와 일치

## 현재 상태
- **정적 분석**: ruff 0건, mypy 0건, eslint 0 errors (23 warnings)
- **테스트**: pytest 58 passed, vitest 46 passed
- **앱 기동**: `SectorFlow.command` 기동 정상 — 백엔드 721ms, WS 3채널 연결, UI 정상 표시 확인 (2026-07-05 휴장일)

## 다음 단계
- **장중 런타임 검증 (대기)**: 실시간 PnL, 업종지수, 매수 시도, 데이터 동기화, 텔레그램 분리, Pending Changes, 레거시 마이그레이션 — 장중 사용자 직접 확인 필요

## 미해결 문제
- 없음 (종목수 불일치 2026-07-05 해결 완료)

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

### 5. 백업/복구 자동화 (우선순위 낮음)
- **현상**: `stocks.db` 수동 백업만 가능, 자동 백업 스크립트 없음
- **위치**: `backend/data/stocks.db` (단일 파일)
- **영향**: DB 손상 시 복구 불가 (외부 요인: 디스크 손상, 실수 삭제, 하드웨어)
- **안정성 확인**: WAL 모드 활성화 (`database.py:24`), 단일 커넥션 공유, 비동기 I/O로 데이터 무결성 보장. 로직은 안정적이나 외부 위험 대응용 백업 필요
- **관련 파일**: `SectorFlow.command`, `backend/app/db/database.py`

### 6. 테스트 자동화 인프라 구축 (2026-07-04, 부분 미해결)
- **현상**: pytest + Vitest 기반 단위 테스트 인프라 구축. 총 104 passed.
  - **Python backend**: `test_sector_score.py` (17개 passed), `test_settings_file.py` (9개 passed), `test_sector_calculator.py` (31개 passed) — pytest 58 passed (hang 해결 완료)
  - **TypeScript frontend**: `sliderConvert.test.ts` (11개), `router.test.ts` (11개), `settings.test.ts` (14개), `store.test.ts` (10개) — vitest 46 passed
- **위치**: `backend/tests/`, `frontend/tests/`, `pytest.ini`, `frontend/vitest.config.ts`
- **남은 사항**: 프론트엔드 컴포넌트/UI 테스트 (jsdom 환경 활용), 백엔드 통합 테스트 (DB 의존성 포함)
- **관련 파일**: `backend/tests/test_sector_score.py`, `backend/tests/test_settings_file.py`, `backend/tests/test_sector_calculator.py`, `frontend/tests/**/*.test.ts`, `pytest.ini`, `frontend/vitest.config.ts`

### 7. 토큰 검증 재활성화 (개발 완료 단계에서 진행)
- **상태**: 의도적 개발 전략 — 현재 인증 우회는 버그/누락이 아님
- **이유**: 개발 단계에서 기능 테스트/디버깅 편의를 위해 인증 우회
- **백엔드 인프라**: `auth.py` (토큰 발급/검증/만료 처리), `POST /api/auth/login` 엔드포인트 — 모두 구현 완료
- **프론트엔드**: 로그인 페이지 미구현 (의도적) — 개발 완료 단계에서 추가 예정
- **TODO 주석 8건**: `deps.py:13`, `ws.py:164`, `ws_orders.py:18`, `ws_settings.py:18`, `client.ts:18,29,40,69` — 개발 완료 후 재활성화
- **재활성화 조건**: 프론트엔드 로그인 페이지 구현 완료 후 백엔드/프론트엔드 동시 재활성화 필요
