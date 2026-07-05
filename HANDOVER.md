# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: mypy 미해결 에러 5건 근본 해결 (원칙 10, 16, 17)**
  - `engine_ws_reg.py:259,394`: `get_positions` import 경로를 `engine_service`(파사드, 재내보내기 없음) → `engine_account`(실제 정의)로 변경 — ImportError 근본 해결, 원칙 10 SSOT
  - `engine_ws_dispatch.py:211,214,216`: `engine_state.realtime_latency_exceeded`(모듈 속성) → `state.realtime_latency_exceeded`(인스턴스 속성)로 변경 — 플래그 단일 소스 통합, 원칙 17. 주문체결(00) 지연 감지가 `trading.py` 게이트에 정상 도달, 원칙 16
  - 검증: ruff passed, mypy 수정 파일 0 에러 (기존 9개 → 4개, 5개 해소), pytest 108 passed

## 현재 상태
- **빌드**: 백엔드 py_compile OK
- **테스트**: pytest 108 passed, 0 failed
- **정적 분석**: ruff all checks passed
- **Git**: `ff5753a` 커밋 (슬리피지), mypy 수정 미커밋

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 테스트모드 매수/매도 시 체결가 로그에서 슬리피지 적용 확인 (예: 70,000원 매수 → 70,100원 체결)
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- **mypy 잔여 에러 4개 (기존 코드)**: `--explicit-package-bases` 옵션 시 2개 파일에서 4개 에러
  - `telegram_bot.py:359,410`: `engine_service.get_account_snapshot` 속성 없음 `[attr-defined]`
  - `trading.py:161`: 모듈에 `_positions` 속성 없음 `[attr-defined]`
  - `trading.py:462`: 모듈에 `get_positions` 속성 없음 `[attr-defined]`
  - 조사 필요: 파사드 재내보내기 누락 또는 직접 import 필요

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리

