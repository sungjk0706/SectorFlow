# SectorFlow Handover

## 세션 개요 (최근)
- **2026-07-18**: HANDOVER 정합성 정리 — P-001 Step 3 완료 이관 (실제로는 2026-07-15 커밋 7e12f51에서 완료, HANDOVER 누락 분리). P-001 3단계 모두 완료로 미해결 문제 섹션에서 제거.
- **2026-07-18**: HANDOVER 정합성 정리 — P-001 Step 2 완료 이관 (실제로는 2026-07-15 커밋 7023c24/f5047b6에서 완료, HANDOVER 누락 분리).
- **2026-07-18**: P-NEW-5 완료 — 16개 모듈 state 참조 패턴 A→B 전환 (8세션). `engine_state.state.X` 참조로 통일, `patch("engine_state.state")` 전파 보장.
- **2026-07-18**: test_trading.py 테스트 격리 문제 해결 — `daily_time_scheduler.py` 패턴 B 전환 (전체 회귀 2928 passed).
- **2026-07-16**: P-NEW-1 해결 — 가산점 입력창 `input` 이벤트 실시간 clamp (슬라이더·버튼·타이핑 3경로 단일 범위).
- **2026-07-15**: P-001 Step 1·2·3 완료 — 틱 수신 빈 FID 0 폴백 제거 (None 유지), `_has_any_realtime_data` 검증, 업종 점수 None 폴백 제거 + 미수신 종목 제외.

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

## 해결 완료 문제 (참고용)

### P-001: 실시간 데이터 미수신 시 0 폴백 → 수신률 100% 왜곡 + 업종 점수 왜곡 (2026-07-15 완료)
- **현상**: 실시간 데이터 필드가 0 또는 "-"로 표시되는데 수신률은 100%로 표시. 0이 유효 데이터로 인식되어 업종 점수 왜곡.
- **근본 원인 (2단계 연쇄)**:
  - **원인 A**: 미수신 데이터를 0으로 폴백 저장 (P20 위반)
    - `engine_radar.py:73-77` — Step 1 해결 완료 (커밋 0c0d018)
    - `pipeline_compute.py:628-631` — Step 2 해결 완료 (커밋 7023c24, f5047b6)
    - `engine_ws_parsing.py:155-156`, `engine_account_rest.py:18-23` — **변경 안 함 (설계 결정)**: 파서 자체를 None 반환으로 변경하면 REST 잔고 경로 5곳에 영향. 틱 수신 경로에서만 빈 값 체크 후 None 저장하는 방식으로 원인 A 해결 (계획서 3-1 결정 1).
  - **원인 B**: 수신률 계산이 0과 None 구분 안 함 (P22 위반) — `pipeline_compute.py:112-118` `_has_any_realtime_data`
    - Step 1·2 완료로 틱 수신 경로에서 빈 값이 None으로 저장되어 기존 `is not None` 체크가 정상 동작. **검증 완료** (test_pipeline_compute.py:54-79, 6개 케이스).
  - **원인 C (Step 3)**: `sector_calculator.py:69,78`에서 None을 0으로 폴백 — 원인 A·B 수정 후에도 업종 점수에 0 왜곡 잔존.
    - Step 3 해결 완료 (커밋 7e12f51) — None 유지 + 미수신 종목 `continue` 제외 + 단위 테스트 6개 추가.
- **영향 경로**: 0 폴백 → 수신률 100% 왜곡 → 임계값 통과 → 업종순위 계산 시작 → 1·2·3차 가산점 모두 0 왜곡 포함 → 업종 점수 순위 왜곡
- **관련 원칙**: P10, P20, P21, P22, P23
- **검증 완료**: 틱 일부만 수신 시 수신률이 100%가 아닌 실제 비율 표시, 0/- 표시 종목이 일관되게 "-" 표시, 업종 점수 순위가 0 왜곡 없이 계산 (test_sector_calculator.py `TestComputeSectorScoresNoneExclusion` 6개 케이스)

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
