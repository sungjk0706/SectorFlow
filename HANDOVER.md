# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 전 페이지 타이틀 라벨 통일**
  - 업종순위 3패널: `sector-settings.ts`(업종순위 설정), `sector-ranking-list.ts`(업종순위), `sector-stock.ts`(우측 grid 재배치: 좌측 필터 | 중앙 제목 | 우측 종목수)
  - `buy-settings.ts`(매수설정), `sell-settings.ts`(매도설정), `general-settings.ts`(일반설정), `profit-overview.ts`(수익현황 + 섹션 타이틀 sectionTitle로 통일)
  - `stock-classification.ts`: fontSize 오버라이드 제거 (15px 통일)
  - 페이지 타이틀: `createCardTitle`(15px), 섹션 타이틀: `sectionTitle`(14px) 계층 통일
  - 커밋 `478a1a6` 푸시 완료

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK (tsc + vite, 3.79s)
- **Git**: `478a1a6` 커밋 푸시 완료

## 다음 단계
- **브라우저 런타임 검증 (대기)**: 각 페이지 타이틀 표시 위치·크기 일관성 확인
- **장중 런타임 검증 (대기)**: 테스트모드 주문/체결 시퀀스 확인
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
