# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 설정값과 런타임 게이트 분리 — 비거래일 토글 강제 OFF 제거**
  - `general-settings.ts`: syncFromSettings 토글 forceOff 제거, handleWsToggle/handleMasterToggle/autoBuyToggle/autoSellToggle shouldForceOff 다이얼로그 제거
  - `daily_time_scheduler.py`: `_apply_auto_toggle_on_startup` ws_subscribe_on 강제 변경 제거, `_on_ws_subscribe_end` ws_subscribe_on=False 제거, `_on_ws_subscribe_start` ws_subscribe_on=True 제거, `_restore_from_holiday_flag` 함수 전체 제거
  - 런타임 게이트 유지: `is_ws_subscribe_window()`, `_on_ws_subscribe_start` 스킵, `auto_trading_effective._master_on()`
  - 원칙 10 (SSOT), 원칙 20 (폴백 금지) 부합

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK (3.79s), 백엔드 `py_compile` OK
- **테스트**: `pytest` 90 passed (이전 세션), 이번 수정 테스트 미실행
- **앱 기동**: 런타임 검증 미수행 (원칙 19 — 사용자 직접 확인 필요)
- **Git**: `3f1f109` push 완료 (origin/main 동기화됨)

## 다음 단계
- **일반설정 자동매매 탭 동일 문제 조사 (대기)**: 이번 수정에서 API 설정 탭의 토글 강제 OFF를 제거했으나, 자동매매 탭의 `time_scheduler_on` 토글도 동일한 패턴(`forceOff ? false`)으로 강제 OFF되어 있었음. 이미 이번 수정에서 함께 제거했으나, 자동매매 탭에 추가적인 강제 OFF 경로나 다이얼로그가 있는지 독립 조사 필요 — `general-settings.ts` 자동매매 탭 렌더링 로직, `handleMasterToggle` 외 다른 핸들러 확인
- **비거래일 런타임 검증 (대기)**: `SectorFlow.command` 기동 후 비거래일에 토글이 사용자 설정값 유지하는지, 배지/시간 비활성화 정상 동작하는지 확인 — 사용자 직접 확인 필요
- **장중 런타임 검증 (대기)**: 테스트모드 주문/체결 시퀀스, `has_open_buy` 상태, `_recent_sells` 처리, 텔레그램 알림 정상 동작 확인 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`
- **파사드 임포트 정리 (선택적)**: `engine_service.py`의 재내보내기 함수들을 직접 import로 변경. 현재 동작에는 문제 없으나 코드 명확성 향상 목적

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
