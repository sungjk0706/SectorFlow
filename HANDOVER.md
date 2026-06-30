# HANDOVER — SectorFlow

## 완료 단계
- 2026-06-30: 앱 기동 시간 증가 근본 원인 분석 및 수정안 1~4 적용 완료 — 코드 기반 검증 완료
- 2026-06-30: 실시간 데이터 비동기화 근본 원인 분석 및 수정 완료 — 코드 기반 검증 완료
- 2026-06-30: WS 브로드캐스트 정리 — pipeline_gateway.py 데드 코드 제거, 배치 전송 모듈 파일 삭제 및 import 제거, ws_manager.py _state_queue/_event_queue/_flush_loop 전면 제거 — 코드 기반 검증 완료
- 2026-06-30: 업종지수 실시간 데이터 처리 및 헤더 표시 구현 — 코드 기반 검증 완료
- 2026-06-30: 매수 시도 누락 버그 수정 — evaluate_buy_candidates() 호출이 스켈레톤 모드(비활성) 경로에만 배치되어 실제 운영 경로에서 매수 시도가 발생하지 않던 문제 수정 — 코드 기반 검증 완료

## 현재 상태
모든 수정사항 코드 기반 검증 완료. 런타임 검증은 장중 실시간 데이터 수신 시 필요.

## 다음 단계 (장중 런타임 검증 필요)
1. **업종지수 실시간 데이터 수신 확인**: 장중 실시간 데이터 수신 시 헤더에 코스피/코스닥 지수 표시 확인 필요. LS IJ_ `upcode` 필드값이 "001"/"101"인지 실제 수신 시 확인 필요.
2. **매수 시도 로그 확인**: 장중 실시간 틱 발생 시 매수 시도 로그(`[섹터매수] 매수 시도: ...`) 확인 필요.
3. **실시간 데이터 동기화 확인**: 업종순위 페이지와 매수설정 페이지를 각각 띄움 (dual layout). 같은 종목의 시세가 두 테이블에서 동시에 같은 값으로 표시되는지 확인 필요.

## 미해결 문제
- **`is_skeleton_mode` 항상 False (dead code)**: `models.py:75`에서 `is_skeleton_mode: bool = False` 기본값 설정. `engine_sector_confirm.py:110-112`에서 체크 및 `_skeleton_incremental_update()` 호출. `is_skeleton_mode`를 `True`로 설정하는 코드 없음 → `_skeleton_incremental_update()` 경로는 절대 실행되지 않음. 스켈레톤 모드가 의도된 용도인지 아키텍처 재검토 필요. 현재는 일반 증분 재계산 경로가 정상 동작하므로 기능에 영향 없음.
- **TODO 주석 8건 (토큰 검증 재활성화)**: `deps.py:16`, `ws.py:176`, `ws_orders.py:23`, `ws_settings.py:23`, `client.ts:18,29,40,66`. 모두 "개발 완료 후 토큰 검증 재활성화" 관련.
- **종목수 불일치**: `_apply_confirmed_to_memory`(`market_close_pipeline.py:359`)에서 새 엔트리 생성 의심. 런타임 확인 필요 (우선순위 낮음).
- **ARCHITECTURE.md 문서-코드 불일치 3건**:
  - **4.4 스켈레톤 증분 연산** (line 1392-1398): 스켈레톤 증분 연산을 구현된 최적화로 기재하나, 실제 `is_skeleton_mode`가 항상 `False`이므로 dead code. 문서에서 제거 또는 "미구현" 표기 필요.
  - **4.5 섹션** (line 1400-1406): 정리 완료 — ARCHITECTURE.md에서 섹션 4.5 제거 및 코드에서 관련 참조 전면 제거 완료.
  - **변경 로그** (line 1635): "스켈레톤 증분 연산 도입"으로 기재되어 있으나 실제 dead code이므로 문서-코드 불일치.

## 개선 필요 영역 (코드 기반 확인)

### 1. 단일 종목 비중 한도 (이미 구현됨)
- **현상**: `risk_manager.py:39,90-92`에서 `max_single_stock_exposure` 로직 이미 구현됨. `settings_defaults.py:55`, `engine_settings.py:79`에서 설정값 관리. TODO 주석 없음.

### 2. 리스크 임계치 (설정값 관리됨)
- **현상**: `max_daily_loss_limit`, `max_total_exposure_ratio` 등이 `settings_defaults.py:54,56`, `engine_settings.py:78,80`에서 설정값 관리됨. 하드코딩 아님.

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

### 6. 테스트 자동화 부재 (테스트 파일 없음)
- **현상**: 수동 테스트만 수행, pytest 기반 단위/통합 테스트 없음
- **위치**: `backend/tests/` 디렉토리는 존재하나 테스트 파일 없음 (비어 있음)
- **영향**: 코드 변경 시 회귀 위험, 안전장치 검증 불가
- **관련 파일**: `backend/app/domain/`, `backend/app/services/risk_manager.py`, `backend/app/services/settlement_engine.py`
