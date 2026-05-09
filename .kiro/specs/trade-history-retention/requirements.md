# Requirements Document

## Introduction

SectorFlow의 체결 이력 파일(`trade_history.json`)은 현재 모든 매수/매도 기록을 무기한 보관한다. 시간이 지남에 따라 파일 크기가 무한히 증가하여 로드 성능과 디스크 사용량에 문제가 발생할 수 있다. 이 기능은 모드별 보관 제한(테스트모드 60거래일, 실전모드 5거래일)을 적용하여 저장 시 오래된 레코드를 자동으로 정리하고, 프론트엔드에서 사용자에게 현재 모드에 맞는 데이터 범위를 명확히 안내한다. 실전모드는 MTS/HTS에서 전체 이력을 조회할 수 있으므로 로컬 보관 기간을 짧게 유지한다.

## Glossary

- **Trade_History_Module**: `backend/app/services/trade_history.py` — 체결 이력 인메모리 저장 및 JSON 파일 I/O를 담당하는 백엔드 모듈
- **Retention_Limit**: 체결 이력 보관 기간. 모드에 따라 다름 — 테스트모드 최근 60개 고유 날짜, 실전모드 최근 5개 고유 날짜
- **Trim_Operation**: 보관 기한을 초과한 레코드를 인메모리 리스트 및 파일에서 제거하는 작업. 각 레코드의 `trade_mode` 필드에 해당하는 보관 기간을 적용. Cutoff는 저장된 레코드 자체의 고유 날짜를 기준으로 계산
- **Profit_Overview_Page**: `frontend/src/pages/profit-overview.ts` — 수익현황 페이지
- **Retention_Indicator**: 수익현황 페이지의 요약 카드 영역에 위치한 인라인 `<span>` 요소. 현재 거래 모드에 따라 보관 범위 텍스트를 동적으로 표시
- **Trade_Mode**: 현재 거래 모드. `"test"` 또는 `"real"` 값을 가짐. `appStore.settings.trade_mode` 기준

## Requirements

### Requirement 1: 모드별 보관 기한 상수 정의

**User Story:** As a developer, I want separate constants defining the retention limit per trade mode, so that the retention period is easy to locate and each mode's policy is explicit.

#### Acceptance Criteria

1. THE Trade_History_Module SHALL define a module-level constant `RETENTION_TRADING_DAYS_TEST` with the value 60
2. THE Trade_History_Module SHALL define a module-level constant `RETENTION_TRADING_DAYS_REAL` with the value 5
3. THE Trade_History_Module SHALL use `RETENTION_TRADING_DAYS_TEST` as the retention period for records where `trade_mode` equals `"test"`
4. THE Trade_History_Module SHALL use `RETENTION_TRADING_DAYS_REAL` as the retention period for records where `trade_mode` equals `"real"`

### Requirement 2: 저장 시 자동 트림 (모드별)

**User Story:** As a system operator, I want old trade records to be automatically removed on save per their trade mode's retention policy, so that the history file stays bounded without manual intervention.

#### Acceptance Criteria

1. WHEN the Trade_History_Module performs a file save operation, THE Trade_History_Module SHALL remove all records with `trade_mode` equal to `"test"` whose `date` is not among the most recent 60 unique dates present in the stored test-mode records
2. WHEN the Trade_History_Module performs a file save operation, THE Trade_History_Module SHALL remove all records with `trade_mode` equal to `"real"` whose `date` is not among the most recent 5 unique dates present in the stored real-mode records
3. THE Trade_History_Module SHALL determine the retained dates for each mode by collecting all unique `date` values from records of that mode, sorting them in descending order, and keeping only the most recent N dates (60 for test, 5 for real)
4. IF a mode has no records at all, THEN THE Trade_History_Module SHALL not delete any records for that mode (empty date set = no trimming)
5. THE Trade_History_Module SHALL apply the Trim_Operation to both the in-memory lists and the persisted JSON file atomically within the same save cycle
6. THE Trade_History_Module SHALL apply mode-specific retention independently — trimming test records at 60 dates does not affect real records, and trimming real records at 5 dates does not affect test records

### Requirement 3: 파일 로드 시 트림

**User Story:** As a system operator, I want stale records to be cleaned up on application startup, so that accumulated old data from previous runs is pruned immediately.

#### Acceptance Criteria

1. WHEN the Trade_History_Module loads history from the JSON file, THE Trade_History_Module SHALL apply the Trim_Operation (using unique dates present in the loaded records) before making data available for queries
2. WHEN the Trim_Operation removes records during load, THE Trade_History_Module SHALL persist the trimmed result back to the file

### Requirement 4: 프론트엔드 보관 범위 표시 (모드 동적)

**User Story:** As a user viewing the profit overview page, I want to see a clear indicator of the data retention range that reflects the current trade mode, so that I understand whether I am viewing 60 trading days (test) or 5 trading days (real) of data.

#### Acceptance Criteria

1. WHILE the Trade_Mode is `"test"`, THE Profit_Overview_Page SHALL display the Retention_Indicator with the text "최근 60거래일 데이터"
2. WHILE the Trade_Mode is `"real"`, THE Profit_Overview_Page SHALL display the Retention_Indicator with the text "최근 5거래일 데이터"
3. WHEN the Trade_Mode switches between `"test"` and `"real"`, THE Profit_Overview_Page SHALL update the Retention_Indicator text to match the new mode
4. THE Retention_Indicator SHALL be an inline `<span>` element within the summary cards area of the Profit_Overview_Page (not a shared/common component)
5. THE Retention_Indicator SHALL be positioned in the summary cards area so that the data range context is visible without scrolling
6. THE Retention_Indicator SHALL use a subdued visual style (small font size, muted color) to avoid distracting from primary data

### Requirement 5: 트림 후 데이터 무결성

**User Story:** As a developer, I want the trim operation to preserve data integrity, so that recent records and aggregation logic remain correct after trimming.

#### Acceptance Criteria

1. WHEN the Trim_Operation executes, THE Trade_History_Module SHALL preserve all test-mode records whose `date` is among the most recent 60 unique dates present in the stored test-mode records
2. WHEN the Trim_Operation executes, THE Trade_History_Module SHALL preserve all real-mode records whose `date` is among the most recent 5 unique dates present in the stored real-mode records
3. WHEN the Trim_Operation executes, THE Trade_History_Module SHALL maintain the chronological order of remaining records
4. IF the history file contains records without a valid `date` field, THEN THE Trade_History_Module SHALL remove those records during the Trim_Operation
5. FOR ALL valid trade records within their respective mode's retention window, saving then loading SHALL produce an equivalent set of records (round-trip property)
