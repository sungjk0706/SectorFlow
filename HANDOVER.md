# HANDOVER — SectorFlow

## 완료 단계
- 2026-07-01: 헤더 투자모드 인디케이터 위치 개선 — 빌드 검증 + 사용자 화면 확인 완료
  - **modeChip 위치 이동**: 증권사 칩 뒤 → 로고(`🌊 SectorFlow`) 바로 우측으로 이동. `margin-right:auto`를 modeChip에 부여하여 좌측 그룹(로고+모드)과 우측 그룹(나머지 칩) 분리.
  - **시각적 강조**: `font-size:12px`, `padding:4px 12px`, `font-weight:700`로 다른 칩보다 한 단계 크고 굵게 표시.
  - **파일**: `frontend/src/layout/header.ts:116-129`
- 2026-07-01: 앱 기동 지연 근본 원인 분석 및 수정 완료 — 코드 기반 검증 완료
  - **수정 1: SectorFlow.command health check URL 수정** — `curl -s http://localhost:8000/health` → `http://localhost:8000/api/health` (`SectorFlow.command:51`). 잘못된 URL로 인한 30초 타임아웃 대기 제거.
  - **수정 2: SPA fallback catch-all 라우트에서 /api/* 경로 404 반환** — `backend/app/web/app.py:313-314`에 `api/` 가드 추가. 존재하지 않는 API 경로가 `index.html` 200으로 응답하던 silent fallback 제거. 아키텍처 원칙 7(왜곡 금지), 20(폴백 금지) 부합.
- 2026-06-30: 앱 기동 시간 증가 근본 원인 분석 및 수정안 1~4 적용 완료 — 코드 기반 검증 완료
- 2026-06-30: 실시간 데이터 비동기화 근본 원인 분석 및 수정 완료 — 코드 기반 검증 완료
- 2026-06-30: WS 브로드캐스트 정리 — pipeline_gateway.py 데드 코드 제거, 배치 전송 모듈 파일 삭제 및 import 제거, ws_manager.py _state_queue/_event_queue/_flush_loop 전면 제거 — 코드 기반 검증 완료
- 2026-06-30: 업종지수 실시간 데이터 처리 및 헤더 표시 구현 — 코드 기반 검증 완료
- 2026-06-30: 매수 시도 누락 버그 수정 — evaluate_buy_candidates() 호출이 스켈레톤 모드(비활성) 경로에만 배치되어 실제 운영 경로에서 매수 시도가 발생하지 않던 문제 수정 — 코드 기반 검증 완료
- 2026-07-01: 설정 관리 및 텔레그램 알림 리팩토링 (3개 수정안) — 코드 기반 검증 완료
  - **수정안 1: settings.py 하드코딩 개선** — `apply_settings_updates()`가 `set[str]` 반환, `engine_service.apply_settings_change(changed_keys)`로 전달
  - **수정안 2: 텔레그램 채널 분리** — `telegram_bot_token` → `telegram_bot_token_test` + `telegram_bot_token_real` 분리, `[테스트모드]` 접두사 제거, `_select_token()`이 trade_mode 기반 토큰 선택, 레거시 마이그레이션(`_migrate_telegram_token_split`) 추가
  - **수정안 3: Pending Changes 도입** — 엔진 미실행 시 설정 변경을 `system_state_cache`에 저장(`save_pending_settings`), 엔진 기동 시 `load_pending_settings` → `apply_settings_change` → `clear_pending_settings` 적용

## 현재 상태
- 2026-07-01: 보유주식 평가 손익금(`total_pnl`)/수익률(`total_pnl_rate`) 프론트엔드 업데이트 디버깅 진행 중
  - **초기 스냅샷 데이터 정합성 확인 완료**: 백엔드 계산값 ↔ 프론트엔드 수신값 ↔ positions 합산 모두 일치 (`total_pnl=-1498`, `total_pnl_rate=-0.01`, `total_eval=9988860`, `total_buy=9990358`)
  - **시세 미수신으로 실시간 업데이트 검증 불가**: 현재 17:54, KRX 마감(15:30) 이후. `applyAccountUpdate` 호출 없음.
  - **디버그 로그 추가 완료** (코드 수정만, 원인 수정 아님):
    - `backend/app/services/engine_account.py:369-371`: `_refresh_account_snapshot_meta`에 `pos_count`, `total_buy`, `total_eval`, `total_pnl`, `total_pnl_rate` 로깅
    - `backend/app/services/engine_account_notify.py:474-477`: `broadcast_account_update`에 `reason`, `snapshot_changed`, `changed_pos`, `removed`, `snap total_pnl` vs `prev total_pnl`, `snap total_pnl_rate` vs `prev total_pnl_rate` 로깅
    - `backend/app/services/engine_account_notify.py:489`: `active_pages`, `profit_overview`, `sell_position` 활성 여부 로깅
    - `frontend/src/stores/hotStore.ts:123-126`: `applyAccountUpdate`에 `total_pnl`, `total_pnl_rate`, `total_eval_amount` incoming/prev 값 및 `snapSame` 결과 로깅
    - `frontend/src/stores/hotStore.ts:620-626`: `applyInitialSnapshotHot`에 account 값 및 positions 합산 로깅
  - **발견된 잠재적 문제**: `build_account_snapshot_meta`(`engine_account_rest.py:254-273`) 반환값에 `accumulated_investment` 키 없음. `_refresh_account_snapshot_meta`가 `state.account_snapshot["accumulated_investment"]`를 설정하지만 `build_account_snapshot_meta`가 새 dict 반환 시 유실됨. 경량화 페이로드에서 `accumulated_investment=None` → 프론트엔드 `snapSame` 비교 시 `null !== 숫자`로 첫 업데이트는 통과하나, 이후 `initial_deposit`으로 fallback. 수정 전 조사 필요.
- 이전 수정사항 코드 기반 검증 완료 (py_compile 12개 파일, tsc --noEmit, npm run build). 런타임 검증은 장중 실시간 데이터 수신 시 필요.

## 다음 단계 (런타임 검증 필요)
### 우선: 보유주식 평가 손익금/수익률 실시간 업데이트 디버깅 (장중 검증 필요)
1. **장중(09:00~15:30) 앱 기동 후 백엔드 로그 확인**:
   - `[DEBUG broadcast_account_update]` 로그가 출력되는지 확인
   - `reason=price_tick`인지 확인
   - `snapshot_changed=True`인지 확인 — `False`면 `_snap_equal`이 같다고 판단한 것
   - `snap total_pnl` vs `prev total_pnl` 값 비교
   - `active_pages`에 `profit-overview` 포함되어 있는지 확인
2. **프론트엔드 콘솔 로그 확인**:
   - `[DEBUG applyAccountUpdate]` 로그가 출력되는지 확인
   - `incoming total_pnl` vs `prev total_pnl` 값 비교
   - `snapSame` 결과 확인 — `true`면 UI 업데이트 안 됨
3. **원인 분석 후 수정 방향 결정**:
   - 시나리오 A: `broadcast_account_update` 호출 안 됨 → 상위 호출 경로 문제 (`engine_ws_dispatch.py:304-319`)
   - 시나리오 B: `snapshot_changed=False` → `_snap_equal` 문제 (값이 같다고 판단)
   - 시나리오 C: `active_pages`에 `profit-overview` 없음 → `notifyPageActive` 문제
   - 시나리오 D: `snapSame=true` → 프론트엔드 strict equality 문제 (floating-point precision)
4. **`accumulated_investment` 유실 문제 검토**: `build_account_snapshot_meta` 반환값에 `accumulated_investment` 추가 필요 여부 결정

### 기존 런타임 검증 항목
5. **업종지수 실시간 데이터 수신 확인**: 장중 실시간 데이터 수신 시 헤더에 코스피/코스닥 지수 표시 확인 필요. LS IJ_ `upcode` 필드값이 "001"/"101"인지 실제 수신 시 확인 필요.
6. **매수 시도 로그 확인**: 장중 실시간 틱 발생 시 매수 시도 로그(`[섹터매수] 매수 시도: ...`) 확인 필요.
7. **실시간 데이터 동기화 확인**: 업종순위 페이지와 매수설정 페이지를 각각 띄움 (dual layout). 같은 종목의 시세가 두 테이블에서 동시에 같은 값으로 표시되는지 확인 필요.
8. **텔레그램 채널 분리 확인**: 설정 페이지 → 텔레그램 탭에서 "테스트 봇 토큰" / "실전 봇 토큰" 입력 필드 2개 표시 확인. 테스트모드/실전모드 각각에서 메시지가 해당 봇으로만 전송되는지 확인.
9. **Pending Changes 확인**: 엔진 미실행 상태에서 설정 변경 후 엔진 시작 → 로그에 `[Pending] 엔진 기동 시 보류 설정 변경 적용` 메시지 확인.
10. **레거시 토큰 마이그레이션 확인**: 기존 DB에 `telegram_bot_token`이 있는 경우 앱 시작 시 자동 분리(`telegram_bot_token_test`/`telegram_bot_token_real`) 확인.

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
