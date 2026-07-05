# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 재매수 차단 토글 ON→OFF 초기화 근본 원인 제거**
  - `settings.ts:72-76`: `saveSection()` API 성공 후 로컬 store에 저장값 반영 (기존: WS 이벤트로만 갱신 → `onSync()`가 stale 값으로 토글 덮어쓰기)
  - `settings.py:47-62`: 엔진 미실행 시 `refresh_engine_integrated_system_settings_cache` + `notify_desktop_settings_toggled` WS 브로드캐스트 추가 (기존: `save_pending_settings`만 호출 → WS 누락)
  - `buy-settings.ts`: 5개 토글 `autoSave` → `saveImmediate` 전환 (sell-settings와 패턴 일치화)
  - 검증: `npm run build` OK (51 modules), `py_compile` OK

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK, 백엔드 `py_compile` OK
- **테스트**: 런타임 테스트 미실행 (이전 세션: 백엔드 79 passed, 프론트엔드 109 passed)
- **앱 기동**: 토글 ON/OFF 유지 여부 사용자 직접 확인 필요

## 다음 단계
- **장중 런타임 검증 (대기)**: 실시간 PnL, 업종지수, 매수 시도, 데이터 동기화, 텔레그램 분리, Pending Changes, 레거시 마이그레이션 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`

## 미해결 문제
- 없음

## 개선 필요 영역
- **`engine_service.py` `__getattr__` 폴백 제거 (장기)**: PEP 562 `__getattr__`이 `state` 속성으로 위임하는 폴백 경로. `_broadcast_buy_limit_status` 미 import로 `AttributeError` 발생한 사례가 폴백의 취약성 입증. 별도 세션에서 `es._xxx` 접근 전체 조사 후 `es.state.xxx` 또는 직접 import로 일괄 변경 필요. `settings.py`, `trading.py`, `engine_loop.py`, `engine_snapshot.py` 등 다수 파일 영향
