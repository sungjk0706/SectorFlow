# Bugfix Requirements Document

## Introduction

호가잔량(0D) 구독/해지 로직이 업종순위 재계산 경로(`_flush_sector_recompute_impl`)에 직접 결합되어 있어, 체결 틱이 올 때마다 불필요한 REMOVE/REG가 반복 전송되는 버그를 수정한다. 구독/해지는 오직 `guard_pass` 상태 변경 시에만 발생해야 하며, 업종순위 변동과는 완전히 무관해야 한다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 체결 틱이 수신되어 업종순위가 재계산될 때 THEN `_buy_targets_changed()`가 종목코드 집합만 비교하여 guard_pass 상태 변화 없이도 변경으로 감지한다

1.2 WHEN `_sync_0d_subscriptions()`가 호출될 때 THEN 전체 매수후보(buy_targets)를 구독 대상으로 삼아 guard_pass=False인 종목까지 구독 등록한다

1.3 WHEN 업종순위만 변동하고 guard_pass 상태는 변하지 않았을 때 THEN 불필요한 REMOVE + REG 페이로드가 반복 전송된다

### Expected Behavior (Correct)

2.1 WHEN 매수후보 테이블에서 종목의 guard_pass가 False→True로 변경될 때 THEN the system SHALL 해당 종목에 대해서만 호가잔량(0D) 구독을 신청한다

2.2 WHEN 매수후보 테이블에서 종목의 guard_pass가 True→False로 변경될 때 THEN the system SHALL 해당 종목에 대해서만 호가잔량(0D) 구독을 해지한다

2.3 WHEN 업종순위만 변동하고 guard_pass 상태가 변하지 않았을 때 THEN the system SHALL 호가잔량 구독/해지를 수행하지 않는다

2.4 WHEN `_sync_0d_subscriptions()`가 구독 대상을 결정할 때 THEN the system SHALL guard_pass=True인 종목만 구독 대상 집합에 포함한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 체결 틱이 수신될 때 THEN the system SHALL CONTINUE TO 업종 점수 증분 재계산을 정상 수행한다

3.2 WHEN 업종순위가 변경될 때 THEN the system SHALL CONTINUE TO 매수후보(buy_targets)를 정상 재산출한다

3.3 WHEN guard_pass=True인 종목이 이미 구독 중일 때 THEN the system SHALL CONTINUE TO 중복 REG를 전송하지 않는다 (delta 방식 유지)

3.4 WHEN WS가 미연결 상태일 때 THEN the system SHALL CONTINUE TO 구독/해지를 조용히 스킵한다
