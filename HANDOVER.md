# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 테스트모드 동등성 근본해결 계획서 작성 완료**
  - 정밀 조사 완료: `dry_run.py`, `trading.py`, `engine_ws_dispatch.py`, `engine_account.py`, `engine_ws_fill_followup.py`, `settlement_engine.py`, `risk_manager.py`, `circuit_breaker.py`, `kiwoom_order.py` 전체 읽기
  - 동등성 위반 5가지 + 사전 존재 버그 3가지 발견 (B1~B3: `_on_fill_after_ws`의 `state.refresh_account_snapshot_meta`/`state.update_account_memory`가 항상 `None` → 실전 모드에서도 체결 후 계좌 갱신/매도검사 동작 안 함)
  - 8단계 수정 계획서 작성 → `docs/TEST_MODE_EQUIVALENCE_PLAN.md`

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK, 백엔드 `py_compile` OK
- **테스트**: `pytest` 79 passed
- **앱 기동**: 정상 기동 확인 (테스트모드, LS증권/키움증권 토큰 발급, 업종순위 재계산 완료, WS 3채널 연결 성공)
- **Git**: 9 commits push 완료 (origin/main 동기화됨)

## 다음 단계
- **테스트모드 동등성 근본해결 — 구현 진행 (최우선)**: `docs/TEST_MODE_EQUIVALENCE_PLAN.md` 계획서 대로 Step 1~8 순차 구현. 사용자 승인 후 시작
- **장중 런타임 검증 (대기)**: 실시간 PnL, 업종지수, 매수 시도, 데이터 동기화, 텔레그램 분리, Pending Changes, 레거시 마이그레이션 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`
- **파사드 임포트 정리 (선택적)**: `engine_service.py`의 재내보내기 함수들을 직접 import로 변경. 현재 동작에는 문제 없으나 코드 명확성 향상 목적

## 미해결 문제
- **테스트모드 동등성 위반 (원칙 18)**: `fake_send_order`가 주문 접수와 체결을 한 번에 처리. 상세 조사 결과 및 8단계 수정 계획 → `docs/TEST_MODE_EQUIVALENCE_PLAN.md` 참조

## 테스트모드 동등성 조사 결과 (2026-07-05 조사 완료, 구현 대기)

- **동등성 위반 5가지 + 사전 존재 버그 3가지 (B1~B3) 발견**
- **사전 버그 B1~B3 요약**: `state.refresh_account_snapshot_meta`/`state.update_account_memory`가 `engine_state.py:40-41`에서 `None` 초기화 후 영원히 할당되지 않음 → `_on_fill_after_ws()`에서 `None()` 호출 → `TypeError` → `engine_ws_dispatch.py:365` except에서 silent catch → **실전 모드에서도 체결 후 계좌 갱신/매도검사 동작 안 함**
- **수정 계획 8단계**: `docs/TEST_MODE_EQUIVALENCE_PLAN.md` 참조

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
