# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 테스트모드 동등성 근본해결 구현 완료 (Step 1~8)**
  - `docs/TEST_MODE_EQUIVALENCE_PLAN.md` 8단계 계획 전체 구현
  - `dry_run.py`: `fake_send_order` 주문 접수만, `fake_fill_event` 실전 WS 00 동일 체인 추가
  - `trading.py`: `_dryrun_post_*_broadcast` 제거, `on_fill_update` 테스트모드 분기 제거
  - `engine_account.py`: `_on_fill_after_ws` 사전 버그 B1~B3 수정 (None callable TypeError)
  - `test_dry_run_fill_event.py`: 11개 단위 테스트 추가, 무한 대기 원인 분석 및 DB I/O stub 해결

## 현재 상태
- **빌드**: 백엔드 `py_compile` OK
- **테스트**: `pytest` 90 passed in 5.26s (신규 11개 포함)
- **앱 기동**: 런타임 검증 미수행 (원칙 19 — 사용자 직접 확인 필요)
- **Git**: 10 commits push 완료 (origin/main 동기화됨)

## 다음 단계
- **장중 런타임 검증 (대기)**: `SectorFlow.command` 기동 후 테스트모드 주문/체결 시퀀스, `has_open_buy` 상태, `_recent_sells` 처리, 텔레그램 알림 정상 동작 확인 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`
- **파사드 임포트 정리 (선택적)**: `engine_service.py`의 재내보내기 함수들을 직접 import로 변경. 현재 동작에는 문제 없으나 코드 명확성 향상 목적

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
