# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 테스트 데이터 전체 초기화 실패 근본 해결**
  - `engine_service.py:13-18`: `_broadcast_buy_limit_status` import 누락 추가 — `reset_test_data` 핸들러에서 `es._broadcast_buy_limit_status()` 호출 시 `AttributeError` 발생이 근본 원인
  - `settings.py:94,120`: `es._positions = []` → `es.state.positions = []`, `es._last_global_buy_ts = 0.0` → `es.state._last_global_buy_ts = 0.0` (원칙 10 SSOT 위반 수정)
  - `trading.py:357-359`: `engine_service` 경유 `_broadcast_buy_limit_status()` → `engine_account` 직접 import로 변경 (원칙 16 살아있는 경로 배선)
  - 검증: `py_compile` 3개 파일 OK, `pytest` 79 passed

## 현재 상태
- **빌드**: `py_compile` 3개 파일 OK (engine_service.py, settings.py, trading.py)
- **테스트**: 백엔드 79 passed, 프론트엔드 109 tests passed (이전 검증)
- **앱 기동**: 런타임 확인 필요 — 테스트 데이터 초기화 버튼 정상 동작 여부 사용자 직접 확인 필요

## 다음 단계
- **장중 런타임 검증 (대기)**: 실시간 PnL, 업종지수, 매수 시도, 데이터 동기화, 텔레그램 분리, Pending Changes, 레거시 마이그레이션 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`

## 미해결 문제
- 없음

## 개선 필요 영역
- **`engine_service.py` `__getattr__` 폴백 제거 (장기)**: PEP 562 `__getattr__`이 `state` 속성으로 위임하는 폴백 경로. `_broadcast_buy_limit_status` 미 import로 `AttributeError` 발생한 사례가 폴백의 취약성 입증. 별도 세션에서 `es._xxx` 접근 전체 조사 후 `es.state.xxx` 또는 직접 import로 일괄 변경 필요. `settings.py`, `trading.py`, `engine_loop.py`, `engine_snapshot.py` 등 다수 파일 영향
