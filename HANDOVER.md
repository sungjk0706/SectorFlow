# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 테스트모드 시장가 주문 슬리피지 적용 (원칙 18 동등성 강화)**
  - `dry_run.py:103-140`: 호가단위 테이블(`_TICK_TABLE`), `_tick_size()`, `_apply_slippage()`, `estimate_fill_price()` 추가
  - `dry_run.py:196`: `fake_fill_event` 내부에 슬리피지 적용 (매수 +1틱, 매도 -1틱, 하한가 보호)
  - `trading.py:251`: `execute_buy` buy_qty 계산 시 슬리피지 예상가 사용
  - `trading.py:282`: `check_test_buy_power` 검증가에 슬리피지 반영
  - `trading.py:336-337`: fill_price(일일누적/거래이력)에 슬리피지 적용
  - `trading.py:516-517`: `execute_sell` 체결이력 가격에 슬리피지 적용
  - `test_dry_run_fill_event.py`: 슬리피지 검증 테스트 18개 추가, 기존 2개 수정
  - 검증: pytest 108 passed, ruff all checks passed, mypy 수정 파일 0 에러

## 현재 상태
- **빌드**: 백엔드 py_compile OK
- **테스트**: pytest 108 passed, 0 failed
- **정적 분석**: ruff all checks passed
- **Git**: `ff5753a` 커밋 푸시 완료

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 테스트모드 매수/매도 시 체결가 로그에서 슬리피지 적용 확인 (예: 70,000원 매수 → 70,100원 체결)
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- **mypy 사전 에러 9개 (기존 코드)**: 본 작업과 무관하나 `--explicit-package-bases` 옵션 시 4개 파일에서 9개 에러 발생
  - `engine_ws_reg.py:259,394`: `engine_service.get_positions` 속성 없음 `[attr-defined]`
  - `engine_ws_dispatch.py:211,214,216`: `engine_state.realtime_latency_exceeded` 속성 없음 `[attr-defined]`
  - 조사 필요: 실제 런타임에서 사용 여부 및 동적 속성 추가 경로 확인

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리

