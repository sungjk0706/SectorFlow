# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-05: 재매수 차단 토글 OFF→ON 리셋 버그 근본 해결**
  - `buy-settings.ts:142`: `rebuy_block_on` 폴백 `true` 제거 → `!!r.rebuy_block_on` 으로 통일 (원칙 20 폴백 금지)
  - `buy-settings.ts:317`: onClick 토글 패턴 `!(vals.rebuy_block_on !== false)` → `!vals.rebuy_block_on` 으로 일치화
  - 검증: `npm run build` 성공 (51 modules), `npx vitest run` 109 tests passed

## 현재 상태
- **빌드**: `npm run build` 성공 (51 modules, buy-settings 6.93KB)
- **테스트**: 프론트엔드 109 tests passed
- **앱 기동**: 런타임 확인 필요 — 토글 OFF 시 정상 유지 여부 사용자 직접 확인 필요

## 다음 단계
- **장중 런타임 검증 (대기)**: 실시간 PnL, 업종지수, 매수 시도, 데이터 동기화, 텔레그램 분리, Pending Changes, 레거시 마이그레이션 — 장중 사용자 직접 확인 필요
- **WS 구독 분산 최적화 (대기)**: `ConnectorManager` 구현됨, 구독 분산 미구현 — `connector_manager.py`, `engine_ws_reg.py`

## 미해결 문제
- **일반설정 페이지 투자모드 탭 — 테스트 데이터 전체 초기화 실패**: 버튼 클릭 시 "초기화 실패" 오류 발생. 원인 미조사. `settings.py:58-134` `reset_test_data` 핸들러 확인 필요
