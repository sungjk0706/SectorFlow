# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 업종순위 페이지 triple 레이아웃 전환 (2컬럼 → 3컬럼)**
  - 신규 파일: `sector-settings.ts` (설정 입력만 담당), `sector-ranking-list.ts` (업종 순위 리스트만 담당), `sector-ranking-page.ts` (코디네이터 — 3패널 조율)
  - 삭제: `sector-ranking.ts` (기존 통합 파일)
  - 수정: `main.ts:55-59` — 라우트 `dual` → `triple`, `settingsCard` 제거, 코디네이터 로드
  - 패턴: `stock-classification.ts` 코디네이터 패턴과 동일 — 단일 PageModule이 `shell.tripleLeft/Center/Right`에 직접 빌드
  - flex 비율: `1:1:3` (좌 20%, 중앙 20%, 우측 60%) — 우측 테이블 컬럼 너비 확보
  - 원칙 10 (SSOT): `maxTargets`를 `uiStore.settings`에서 직접 읽음, 원칙 5 (직접 호출): store 구독만 사용

## 현재 상태
- **빌드**: 프론트엔드 `npm run build` OK (3.55s), 백엔드 미변경
- **테스트**: 프론트엔드 테스트 미실행 (기존 테스트에 sector-ranking 직접 참조 없음 확인됨)
- **앱 기동**: 사용자 확인 — 3컬럼 렌더링 OK, 우측 테이블 컬럼 너비 개선 확인됨
- **Git**: 커밋 미수행 (대기 중)

## 다음 단계
- **중앙 패널 너비 축소 검토 (대기)**: `1:0.7:3` 또는 `2:1:4` 비율로 중앙 업종순위 패널 축소 — 사용자 승인 대기
- **브라우저 런타임 검증 (대기)**: 업종 순위 클릭 → 종목 테이블 필터링, 설정 변경 → 순위 갱신, stock-classification 왕복 시 잔류물 없음 확인 — 사용자 직접 확인 필요
- **비거래일 런타임 검증 (대기)**: `SectorFlow.command` 기동 후 비거래일 토글/배지 확인
- **장중 런타임 검증 (대기)**: 테스트모드 주문/체결 시퀀스 확인
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현

## 미해결 문제
- 없음

## 개선 필요 영역
- **파사드 임포트 정리 (선택적)**: `engine_service.py`가 다수 모듈에서 함수를 재내보내기(facade) 하고 있음. 직접 import로 변경하면 순환 import 위험 없이 코드 명확성 향상 가능. 현재는 정상 동작하므로 우선순위 낮음
- **`rate_limit_per_sec` 미구현 (원칙 16 위반)**: `settings_defaults.py`:64, `engine_settings.py`:76에 설정값 존재하지만 실제 로직에서 사용하는 곳 없음. 현재 `await` 순차 처리 구조에서 추가 필요성은 낮으나, 설정값만 있고 동작 안 하는 상태는 원칙 16 위반. 별도 이슈로 분리
