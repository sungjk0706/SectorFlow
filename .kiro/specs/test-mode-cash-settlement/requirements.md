# Requirements Document

## Introduction

테스트모드(가상 매매)에서 현실 증권시장의 현금 흐름을 정확히 시뮬레이션하기 위한 예수금 관리 및 매도대금 D+2 정산 시스템. 실제 증권시장에서는 매도대금이 즉시 재투자(매수)에 사용 가능하지만, 인출은 D+2 영업일 후에만 가능하다. 이 규칙을 테스트모드에 정확히 반영하여 실전과 동일한 자금 운용 제약을 적용한다.

## Glossary

- **Settlement_Engine**: 테스트모드 전용 정산 처리 모듈. 예수금 관리, 매도대금 인출 제한, D+2 정산 스케줄링을 담당한다.
- **Available_Cash**: 현재 즉시 매수에 사용 가능한 총 예수금(매수 가능 금액, Buying Power). 미정산 매도대금을 포함한다.
- **Pending_Withdrawal**: 매도 체결 후 아직 인출이 불가능한 금액. 매도일로부터 2영업일 후에 인출 가능 상태로 전환된다. Available_Cash에는 이미 포함되어 있으므로 매수에는 즉시 사용 가능하다.
- **Withdrawable_Cash**: 현재 인출 가능한 금액. `Available_Cash - 총 Pending_Withdrawal 합계`로 계산된다.
- **Settlement_Date**: 매도 체결일로부터 2영업일 후의 날짜. KRX 휴장일(주말, 공휴일, 근로자의 날)을 제외하고 계산한다.
- **Daily_Buy_Limit**: 사용자가 설정한 일일 최대 매수 가능 금액 (`max_daily_total_buy_amt`).
- **Effective_Buy_Power**: 실제 매수 가능 금액. `min(Available_Cash, Daily_Buy_Limit - 금일 누적 매수금액)`으로 계산된다.
- **Trading_Calendar**: 기존 `trading_calendar.py` 모듈. KRX 영업일 판별 및 다음 영업일 계산 함수를 제공한다.
- **Test_Mode**: `trade_mode == "test"` 상태. 실시간 시세는 실제 데이터를 사용하되 주문만 가상으로 처리하는 모드.
- **Securities_Transaction_Tax**: 증권거래세 및 농특세. 매도 시 매도금액의 0.20%를 부과한다 (코스피: 거래세 0.05% + 농특세 0.15%, 코스닥: 거래세 0.20%).
- **Sell_Commission**: 매도 수수료. 매도금액의 0.015%를 부과한다.
- **Buy_Commission**: 매수 수수료. 매수금액의 0.015%를 부과한다.
- **General_Settings_Page**: 일반설정 페이지의 '거래모드' 탭. 테스트모드 초기 예수금 입력란과 충전 기능을 포함한다.
- **Mode_State_Store**: 테스트모드와 실전모드 각각의 정산 상태(Available_Cash, Pending_Withdrawal 목록)를 독립적으로 저장하는 영속 저장소.

## Requirements

### Requirement 1: 예수금(Available Cash) 관리

**User Story:** As a 테스트모드 사용자, I want 초기 예수금을 설정하고 매수 시 자동 차감되도록, so that 실제 증권 계좌처럼 자금 한도 내에서만 매매할 수 있다.

#### Acceptance Criteria

1. WHEN 테스트모드가 시작될 때, THE Settlement_Engine SHALL General_Settings_Page의 초기 예수금 입력값(`test_virtual_deposit`)을 Available_Cash로 초기화한다.
2. WHEN 매수 주문이 체결될 때, THE Settlement_Engine SHALL 주문금액(체결가 × 수량)과 Buy_Commission(0.015%)의 합계를 Available_Cash에서 차감한다.
3. IF Available_Cash가 매수 주문금액 + Buy_Commission보다 부족하면, THEN THE Settlement_Engine SHALL 해당 매수 주문을 거부하고 "예수금 부족" 사유를 로그에 기록한다.
4. THE Settlement_Engine SHALL Available_Cash 잔액을 정수(원 단위)로 관리하며, 음수가 되지 않도록 보장한다.
5. WHEN 사용자가 General_Settings_Page에서 초기 예수금 값을 변경하고 "기본예수금으로 저장"을 실행하면, THE Settlement_Engine SHALL 해당 값을 `test_virtual_deposit`에 저장하고 Available_Cash를 동일 값으로 리셋한다.
6. WHEN 사용자가 General_Settings_Page에서 "충전" 버튼을 클릭하면, THE Settlement_Engine SHALL 입력된 금액을 현재 Available_Cash에 추가한다.

### Requirement 2: 매도대금 D+2 인출 제한

**User Story:** As a 테스트모드 사용자, I want 매도대금이 즉시 재투자(매수)에 사용 가능하되 인출은 2영업일 후에만 가능하도록, so that 현실 증권시장의 정산 규칙을 정확히 체험할 수 있다.

#### Acceptance Criteria

1. WHEN 매도 주문이 체결될 때, THE Settlement_Engine SHALL 매도 대금에서 Securities_Transaction_Tax(매도금액의 0.20%)와 Sell_Commission(매도금액의 0.015%)를 차감한 순매도대금을 즉시 Available_Cash에 추가한다.
2. WHEN 매도 주문이 체결될 때, THE Settlement_Engine SHALL 동일한 순매도대금을 Pending_Withdrawal로 기록하고, Trading_Calendar를 사용하여 매도일로부터 2영업일 후의 Settlement_Date를 설정한다.
3. WHILE Pending_Withdrawal 상태인 동안, THE Settlement_Engine SHALL 해당 금액을 Withdrawable_Cash 계산에서 제외한다.
4. WHEN Settlement_Date에 도달하면, THE Settlement_Engine SHALL 해당 Pending_Withdrawal 항목을 삭제하여 해당 금액이 인출 가능 상태로 전환되도록 한다.
5. THE Settlement_Engine SHALL 총 매도 비용을 매도금액의 약 0.215%(증권거래세+농특세 0.20% + 매도수수료 0.015%)로 계산한다.
6. THE Settlement_Engine SHALL 정산 스케줄링에 이벤트 기반 일회성 타이머(call_later)를 사용하며, 주기적 폴링을 사용하지 않는다.
7. WHEN 앱이 재시작될 때, THE Settlement_Engine SHALL 미정산 Pending_Withdrawal 목록을 파일에서 복원하고, 이미 Settlement_Date가 지난 항목은 즉시 삭제하여 인출 가능 상태로 전환한다.

### Requirement 3: 일일매수한도와 예수금 연동

**User Story:** As a 테스트모드 사용자, I want 매수 가능 금액이 예수금과 일일매수한도 중 작은 값으로 제한되도록, so that 두 조건을 모두 만족하는 범위에서만 매수가 실행된다.

#### Acceptance Criteria

1. WHEN 매수 주문 실행 전에, THE Settlement_Engine SHALL Effective_Buy_Power를 `min(Available_Cash, Daily_Buy_Limit - 금일 누적 매수금액)`으로 계산한다.
2. IF 매수 주문금액 + Buy_Commission이 Effective_Buy_Power를 초과하면, THEN THE Settlement_Engine SHALL 해당 매수 주문을 거부한다.
3. WHEN Daily_Buy_Limit이 0(무제한)으로 설정된 경우, THE Settlement_Engine SHALL Available_Cash만을 매수 가능 금액 상한으로 사용한다.

### Requirement 4: 영업일 기반 정산일 계산

**User Story:** As a 테스트모드 사용자, I want 정산일이 KRX 영업일 기준으로 정확히 계산되도록, so that 주말과 공휴일을 건너뛴 실제 정산 일정을 확인할 수 있다.

#### Acceptance Criteria

1. WHEN Settlement_Date를 계산할 때, THE Settlement_Engine SHALL Trading_Calendar의 기존 `_next_business_date()` 함수를 2회 연속 호출하여 D+2 영업일을 산출한다.
2. THE Settlement_Engine SHALL 주말(토·일), 한국 공휴일, 근로자의 날(5월 1일)을 비영업일로 처리한다.
3. WHEN 정산 타이머의 대기 시간을 계산할 때, THE Settlement_Engine SHALL Settlement_Date의 장 시작 시각(09:00 KST)까지의 초 단위 차이를 사용한다.

### Requirement 5: 테스트모드 데이터 초기화

**User Story:** As a 테스트모드 사용자, I want 모든 테스트 데이터를 한 번에 초기화할 수 있도록, so that 새로운 전략을 깨끗한 상태에서 테스트할 수 있다.

#### Acceptance Criteria

1. WHEN 사용자가 "테스트모드 데이터 초기화"를 실행하면, THE Settlement_Engine SHALL Available_Cash를 초기 예수금(`test_virtual_deposit`) 값으로 리셋한다.
2. WHEN 사용자가 "테스트모드 데이터 초기화"를 실행하면, THE Settlement_Engine SHALL 모든 Pending_Withdrawal 항목을 삭제하고 정산 타이머를 취소한다.
3. WHEN 사용자가 "테스트모드 데이터 초기화"를 실행하면, THE Settlement_Engine SHALL 테스트모드 거래 이력(매수/매도)과 가상 보유종목을 모두 삭제한다.
4. WHEN 초기화가 완료되면, THE Settlement_Engine SHALL WebSocket을 통해 프론트엔드에 계좌 스냅샷 갱신 이벤트를 브로드캐스트한다.

### Requirement 6: 정산 상태 조회 및 표시

**User Story:** As a 테스트모드 사용자, I want 매수 가능 금액, 인출 가능 금액, 정산 대기 금액을 구분하여 확인할 수 있도록, so that 자금 운용 현황과 정산 일정을 실시간으로 파악할 수 있다.

#### Acceptance Criteria

1. THE Settlement_Engine SHALL 계좌 스냅샷(AccountSnapshot)에 다음 필드를 포함하여 제공한다: `deposit`(매수 가능 금액 = Available_Cash), `withdrawable`(인출 가능 금액 = Withdrawable_Cash), `pending_withdrawal`(정산 대기 금액 = 총 Pending_Withdrawal 합계).
2. WHEN Available_Cash 또는 Pending_Withdrawal가 변경될 때, THE Settlement_Engine SHALL WebSocket delta 브로드캐스트를 통해 프론트엔드에 변경 사항을 전달한다.
3. THE Settlement_Engine SHALL 개별 Pending_Withdrawal 항목의 매도일, 종목코드, 종목명, 금액, Settlement_Date 정보를 조회 API로 제공한다.
4. THE Settlement_Engine SHALL 수익현황 페이지의 계좌 현황 영역에서 테스트모드일 때 "예수금" 라벨 대신 "매수 가능"(deposit), "인출 가능"(withdrawable), "정산 대기"(pending_withdrawal) 세 항목을 구분하여 표시한다.
5. WHEN 사용자가 정산 대기 목록을 조회하면, THE Settlement_Engine SHALL 각 미정산 항목별로 매도일, 금액, 예상 정산일(인출 가능 예정일)을 포함한 개별 목록을 반환한다.
6. THE Settlement_Engine SHALL 테스트모드에서 `_refresh_account_snapshot_meta()` 호출 시 `deposit`에 Available_Cash를, `withdrawable`에 Withdrawable_Cash(Available_Cash - 총 Pending_Withdrawal)를 설정한다.

### Requirement 7: 테스트모드와 실전모드 데이터 완전 분리

**User Story:** As a 사용자, I want 테스트모드와 실전모드의 정산 데이터가 완전히 분리되도록, so that 모드 전환 시 데이터가 섞이지 않고 각 모드를 독립적으로 운용할 수 있다.

#### Acceptance Criteria

1. WHILE trade_mode가 "real"인 동안, THE Settlement_Engine SHALL 예수금 차감, 인출 제한, D+2 스케줄링 로직을 실행하지 않는다.
2. WHEN trade_mode가 "test"에서 "real"로 전환될 때, THE Settlement_Engine SHALL 테스트모드의 Available_Cash와 Pending_Withdrawal 목록을 Mode_State_Store에 저장하고, 활성 정산 타이머를 중지한다.
3. WHEN trade_mode가 "real"에서 "test"로 전환될 때, THE Settlement_Engine SHALL Mode_State_Store에서 이전 테스트모드의 Available_Cash와 Pending_Withdrawal 데이터를 복원하고, Settlement_Date가 지난 항목을 즉시 삭제하여 인출 가능 상태로 전환한다.
4. WHILE trade_mode가 "real"인 동안, THE Settlement_Engine SHALL 실전 계좌 잔고만을 사용하며 테스트모드의 예수금 데이터를 참조하지 않는다.
5. THE Settlement_Engine SHALL 테스트모드와 실전모드의 정산 상태를 독립적으로 유지하여, 한 모드의 데이터 변경이 다른 모드에 영향을 주지 않도록 보장한다.

### Requirement 8: 인출 기능

**User Story:** As a 테스트모드 사용자, I want 예수금을 추가 충전하거나 가상 인출할 수 있도록, so that 다양한 자금 규모 시나리오를 유연하게 테스트할 수 있다.

#### Acceptance Criteria

1. WHERE 예수금 추가 충전 기능이 활성화된 경우, THE Settlement_Engine SHALL 사용자가 입력한 금액을 Available_Cash에 추가하고 변경 내역을 로그에 기록한다.
2. WHERE 예수금 추가 충전 기능이 활성화된 경우, THE Settlement_Engine SHALL 충전 후 변경된 Available_Cash를 WebSocket delta 브로드캐스트로 프론트엔드에 전달한다.
3. WHERE 가상 인출 기능이 활성화된 경우, THE Settlement_Engine SHALL 사용자가 입력한 금액을 Withdrawable_Cash 범위 내에서만 Available_Cash에서 차감한다.
4. IF 가상 인출 요청 금액이 Withdrawable_Cash를 초과하면, THEN THE Settlement_Engine SHALL 해당 인출을 거부하고 "인출 가능 금액 초과" 사유를 반환한다.
