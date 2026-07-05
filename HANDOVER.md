# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 설정 패널(업종순위·매수설정·매도설정) 여백 및 너비 일관성 정리**
  - `shell.ts:79`: `leftPanel`의 `scrollbar-gutter:stable` 제거 — 불필요한 ~15px 스크롤바 예약 공간 제거
  - `shell.ts:8`: `SETTINGS_PANEL_WIDTH = 340` 상수 정의 및 export (SSOT 원칙 준수)
  - `sector-ranking-page.ts`: mount 시 `tripleLeft`에 `SETTINGS_PANEL_WIDTH` 상수 기반 고정너비/padding 8px 적용, unmount 시 종목분류용 기본값 복원
  - 3개 페이지 좌측 패널 너비/여백 일관성 확보, 종목분류 페이지 영향 없음

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK (tsc + vite)
- **Git**: 작업 커밋 푸시 예정

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 3개 페이지 좌측 패널 너비/여백 일관성 확인, 종목분류 페이지 정상 표시 확인
- **장중 런타임 검증 (대기)**: 테스트모드 주문/체결 시퀀스 확인
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
