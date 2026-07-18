# SectorFlow Handover

## 세션 개요 (최근)
- **2026-07-18**: HANDOVER 최종 정리 — P-001 3단계 모두 완료 확인(2026-07-15 커밋 7e12f51 등) 및 미해결 문제에서 제거. 세션 개요 누적 6건 → 1건 축소.

## 현재 상태 (빌드/테스트 스냅샷)
- **백엔드**: pytest 2928 passed / 0 failed
- **런타임**: `python -W error::RuntimeWarning main.py` 기동 성공, RuntimeWarning 0건
- **프론트엔드**: `npm run build` 성공

## 다음 세션 진행 대기

### 1. KRX 수신률 미표시 문제 추가 조사 (타이머 미실행 근본 원인)
- 3차 조사 완료, 근본 원인 미확인 (08:00/09:00 타이머만 선택적 미실행 패턴 확정)
- **다음**: DEBUG → INFO 로그 승격 적용 후 재발 시 근본 원인 추적 (승인 대기)
- **조사 보고서**: `docs/krx_receive_rate_missing_investigation.md`

### 2. 기타 대기 항목
- **다운로드 완료 시간 표시 (제안2)**: 1일봉/5일봉 다운로드 버튼 우측에 최근 다운로드 완료 시간 표시. 백엔드 신규 기능 필요 (저장소 설계 사전조사 후 제안).
- **실전모드 보관 기준** (`RETENTION_TRADING_DAYS_REAL = 90`): 추후 논의.
- **`notify_raw_real_data` dead code (P16)**: 별도 검토 필요 시 사용자 지시.
- **추가 컬럼 너비 조정**: 사용자 UI 확인 후 필요 시 해당 페이지만 override로 진행.

## DB 데이터 특성 (참고)
- `master_stocks_table.name`: 최대 14자, 평균 4.8자, 99% ≤ 9자
- `master_stocks_table.sector`: 최대 13자, 평균 6.8자
- `master_stocks_table.code`: 6자
- `stock_5d_bars.trade_amount`: 최대 33,936,947 (8자리)
- `stock_5d_bars.high_price`: 최대 3,015,000 (7자리)
- `trades.price`: 최대 1,858,500 (7자리)
- `trades.qty`: 최대 532 (3자리)
- `trades.total_amt`: 최대 5,128,949원
- `trades.pnl_rate`: 최대 5.47%

## 참고 사항
- `master_stocks_table`의 `cur_price`/`change`/`change_rate`/`trade_amount`는 현재 스냅샷에서 비어 있어, 수치 기준은 `stock_5d_bars`와 `trades`를 사용.
- `auto-width.ts`의 `KOREAN_SCALE` 조정은 너비 추정 정확도에 큰 영향을 줌. 변경 없이는 `종목명` 9자만 되어도 150px 이상을 요구해 공간 낭비가 큼.
- `sector-ranking-list.ts`와 `profit-overview.ts`는 `DataTable`이 아니므로 별도 처리 필요.
- 컬럼 너비 공통 상수(`COLUMN_WIDTH`)는 min/max px 경계값이며, 실제 비율은 데이터 기반 px→% 정규화로 페이지별 컬럼 구성에 자동 적응함. per-page override는 `ColumnDef`의 `minWidth`/`maxWidth` 필드로 이미 지원.
