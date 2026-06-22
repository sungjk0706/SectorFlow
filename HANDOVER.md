# HANDOVER.md

## 완료 단계
1. profit-overview 계좌현황 섹션 실시간 갱신 조사 완료
2. 경량화 페이로드 changed_positions 필드 확인 완료
3. 백엔드 계산 로직 검증 완료
4. _SNAPSHOT_CMP_KEYS 의존성 분석 완료
5. build_account_snapshot_meta 필드 매핑 분석 완료
6. 프론트엔드 사용 필드 확인 완료
7. 근본 해결 방안 제시 완료
8. 프로젝트 전체 total_buy_amount 사용 위치 조사 완료
9. broadcast_account_update 호출 직전 snapshot 디버그 로그 추가 완료

## 현재 상태
- 백엔드 디버그 로그 추가 완료 (engine_account_notify.py 489줄)
- 백엔드 재기동 후 실제 로그 확인 대기 중
- total_buy_amount만 변경되고 다른 필드는 동일한 사례 확인 필요

## 다음 단계
1. 백엔드 재기동
2. 수익현황 페이지 접속
3. 실시간 시세 변동 시 터미널 로그 확인
4. total_buy_amount만 변경되고 total_eval_amount, total_pnl, total_pnl_rate는 동일한 사례 확인
5. 해당 사례가 없으면 _SNAPSHOT_CMP_KEYS의 total_buy_amount가 비교에 의미 없는 중복 항목인지 조사

## 미해결 문제
- profit-overview 계좌현황 섹션 실시간 갱신 문제 근본 해결 미완료
- 백엔드/프론트엔드 total_buy_amount 의존성 정리 필요

## 핵심 발견
- _SNAPSHOT_CMP_KEYS에 total_buy_amount 포함 (engine_account_notify.py 222줄)
- 경량화 페이로드에서 total_buy_amount 제거 (engine_account_notify.py 556줄 주석)
- 프론트엔드 hotStore에서 total_buy_amount 비교 (hotStore.ts 231줄)
- 실제 UI에서 total_buy_amount 미사용

## 제안된 해결 방안
1. 백엔드 _SNAPSHOT_CMP_KEYS에서 total_buy_amount 제거
2. 프론트엔드 hotStore에서 total_buy_amount 비교 제거
3. 프론트엔드 types에서 total_buy_amount 제거 (선택적)

## 디버그 로그 위치
- backend/app/services/engine_account_notify.py 489줄
- print(f"[DEBUG] broadcast_account_update snapshot: total_buy_amount={snapshot.get('total_buy_amount')}, total_eval_amount={snapshot.get('total_eval_amount')}, total_pnl={snapshot.get('total_pnl')}, total_pnl_rate={snapshot.get('total_pnl_rate')}")
