# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: `holiday_guard_on` 사용자 토글 제거 — 공휴일 차단 항상 활성화**
  - `is_trading_day_with_holiday_guard()` 제거, 모든 호출부 `is_trading_day()` 직접 호출로 변경
  - 백엔드: `trading_calendar.py`, `auto_trading_effective.py`, `daily_time_scheduler.py`(3곳), `engine_settings.py`, `settings_defaults.py`, `telegram_bot.py`(/휴일 명령어 제거), `test_dry_run_fill_event.py`
  - 프론트엔드: `general-settings.ts`(토글 행 제거, 배지는 유지), `types/index.ts`(타입 제거)
  - 커밋 `5e0fb93` 푸시 완료

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK (3.18s), `tsc --noEmit` OK, 백엔드 `py_compile` 7개 파일 OK
- **잔여 참조**: `holiday_guard`, `is_trading_day_with_holiday_guard`, `holidayToggle` — 모두 0건
- **Git**: `5e0fb93` 커밋 푸시 완료

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 일반설정 자동매매 탭에서 공휴일 토글 행 사라지고 설명 문구만 표시 확인, 비거래일 배지 정상 동작 확인
- **장중 런타임 검증 (대기)**: 테스트모드 주문/체결 시퀀스 확인
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
