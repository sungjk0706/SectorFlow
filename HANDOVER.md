# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: mypy 전체 에러 3건 근본 해결 (원칙 10, 20)**
  - `mypy.ini` 신규 생성: `explicit_package_bases = True` + `[mypy-exchange_calendars] ignore_missing_imports` + `[mypy-jose] ignore_missing_imports` — 외부 라이브러리 stubs 누락 2건 해결
  - `types-python-jose` stubs 패키지 설치 + `requirements.txt` 추가
  - `ws.py:61-63`: 존재하지 않는 `get_all_sector_stocks_from_cache()` 폴백 호출 제거 — 원칙 20 (폴백 금지), 원칙 10 (SSOT: master_stocks_cache가 단일 소스)
  - 검증: mypy 106 files 0 errors, pytest 108 passed

## 현재 상태
- **빌드**: 백엔드 py_compile OK
- **테스트**: pytest 108 passed, 0 failed
- **정적 분석**: mypy 106 files 0 errors (import-untyped 0, attr-defined 0), ruff 기존 F401 11건 (수정과 무관)
- **Git**: 미커밋

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 테스트모드 매수/매도 시 체결가 로그에서 슬리피지 적용 확인 (예: 70,000원 매수 → 70,100원 체결)
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리

