# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: createSelect 공통 컴포넌트 추가 및 buy-settings raw select 교체**
  - `setting-row.ts`: `createSelect` 드롭다운 셀렉트 공통 컴포넌트 추가 — `createNumInput`/`createMoneyInput`과 동일 스타일, `width:121px` + `box-sizing:border-box`
  - `buy-settings.ts`: 재매수 차단 기간 raw `<select>` → `createSelect` 교체, 인라인 스타일 및 raw DOM 조작 제거
  - 검증: `npm run build` exit code 0

## 현재 상태
- **빌드**: tsc + vite build 성공 (exit code 0)
- **커밋**: `94fbae4` push 완료
- **앱 기동**: 매수설정 페이지 재매수 차단 콤보박스 너비 정렬 런타임 확인 필요

## 다음 단계
- **장중 런타임 검증 (대기)**: 실시간 PnL, 업종지수, 매수 시도, 데이터 동기화, 텔레그램 분리, Pending Changes, 레거시 마이그레이션 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`

## 미해결 문제
- 없음
