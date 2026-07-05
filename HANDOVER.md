# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: mypy 잔여 에러 4건 근본 해결 (원칙 10, 16, 18, 19)**
  - `telegram_bot.py:359,371,410,413`: `get_account_snapshot` import 경로 `engine_service`→`engine_account` 직접 import로 변경 + `await` 누락 수정 — Telegram 상태/잔고 조회 런타임 버그(coroutine 미실행) 동시 해결
  - `trading.py:154-156`: `_es_pos._positions`(존재하지 않는 속성) 참조 → `engine_account.get_positions()` 단일 호출로 대체 — SSOT 원칙 10, 중복 모드 분기 제거 (원칙 18)
  - `trading.py:453-454`: `engine_service.get_positions()` → `engine_account` 직접 import + `await` 추가 — 매도 평균매입가 조회 런타임 버그 해결
  - 검증: ruff passed, mypy attr-defined 0 에러 (기존 4개 → 0개), pytest 108 passed

## 현재 상태
- **빌드**: 백엔드 py_compile OK
- **테스트**: pytest 108 passed, 0 failed
- **정적 분석**: ruff all checks passed, mypy attr-defined 에러 0개
- **Git**: `beca1f4` 커밋 푸시 완료

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 테스트모드 매수/매도 시 체결가 로그에서 슬리피지 적용 확인 (예: 70,000원 매수 → 70,100원 체결)
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- **mypy `exchange_calendars` 라이브러리 stubs 누락 (1개)**: `trading_calendar.py:86` — `exchange_calendars` 패키지에 py.typed marker 또는 type stubs 없음. mypy `--explicit-package-bases` 실행 시 `[import-untyped]` 에러 발생. 다음 세션에서 조사 필요
  - 조사 순서: ① `exchange_calendars` 패키지 설치 여부 및 버전 확인 ② `types-exchange-calendars` 또는 커뮤니티 stubs 존재 여부 확인 ③ 없으면 mypy 설정에 `ignore_missing_imports = True` 또는 해당 줄에 `# type: ignore[import-untyped]` 적용 검토

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리

