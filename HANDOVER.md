# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: shouldForceOff() 잔류 제거 + 죽은 코드 정리 (원칙 16 위반)**
  - `general-settings.ts`: `shouldForceOff()` 적용 3곳 제거 — `updateWsTimeDisabled`(377줄), `buyTimeHandle.setEnabled`(895줄), `sellTimeHandle.setEnabled`(902줄). 배지 표시용 `updateHolidayBadges`는 유지
  - `settings_defaults.py`: `auto_off_by_holiday` 기본값 제거 (어디에서도 사용 안 함)
  - `engine_settings.py`: `auto_off_by_holiday` 로드 제거
  - `kiwoom_connector.py`/`ls_connector.py`: `_holiday_block_enabled` 필드, `is_holiday_block_enabled()`, `set_holiday_block_enabled()` 제거
  - `broker_connector.py`: `set_holiday_block_enabled()` 기본 구현 제거
  - `engine_service.py`: `ws.set_holiday_block_enabled()` 호출 2곳 제거 (215줄, 229-237줄 블록)
  - `general-settings.ts`: 자동매수/매도 TimePairInput 다음 비거래일 배지 추가 (275, 315줄) — API 설정 탭과 일관성
  - 원칙 10 (SSOT), 원칙 16 (구현 배선), 원칙 20 (폴백 금지) 부합

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK (6.36s), 백엔드 `py_compile` OK
- **테스트**: `pytest` 90 passed (6.83s)
- **앱 기동**: 런타임 검증 미수행 (원칙 19 — 사용자 직접 확인 필요)
- **Git**: `8bef287` push 완료 (origin/main 동기화됨)

## 다음 단계
- **비거래일 런타임 검증 (대기)**: `SectorFlow.command` 기동 후 비거래일에 토글이 사용자 설정값 유지하는지, 배지 정상 동작하는지 확인 — 사용자 직접 확인 필요
- **장중 런타임 검증 (대기)**: 테스트모드 주문/체결 시퀀스, `has_open_buy` 상태, `_recent_sells` 처리, 텔레그램 알림 정상 동작 확인 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`
- **파사드 임포트 정리 (선택적)**: `engine_service.py`의 재내보내기 함수들을 직접 import로 변경. 현재 동작에는 문제 없으나 코드 명확성 향상 목적

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
