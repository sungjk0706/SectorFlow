# SectorFlow Handover

## 세션 개요 (최근)
- **2026-07-18**: 종목 구독 200개 한도 설정 키 이관 Step 1 (백엔드) 완료. `subscribe.max_0b_count` 설정 키 추가 (기본값 200, 범위 1~1000). 백엔드 4파일 수정: (1) `settings_defaults.py` — 신규 키 기본값 200 추가. (2) `engine_settings.py` — 타입 캐스팅 `int(_v if _v is not None else 200)` 추가 (P20 폴백 금지 패턴 준수). (3) `engine_ws_reg.py:258` — 하드코딩 `_WS_0B_LIMIT = 200` → `int(engine_state.state.integrated_system_settings_cache.get("subscribe.max_0b_count", 200))` 교체 (P10 SSOT, P13 메모리 상주). (4) `settings_store.py` — `apply_settings_updates()` 내 범위 검증 추가 (1~1000 외 ValueError → 422 차단, P20/P22). 테스트 6개 신규 추가: `test_engine_ws.py` 한도 적용 로직 2개 (설정값 반영 + 기본값 200 폴백), `test_settings_store.py` 범위 검증 4개 (0/1001/비정수 거부 + 유효범위 통과). 검증: py_compile OK + 런타임 기동 OK (RuntimeWarning 0건) + 전체 회귀 2935 passed / 0 failed.
- **2026-07-18 (이전)**: 09:00 KRX 구독 중복 요청 제거 + 200개 한도 설정화 설계서 작성. (1) `daily_time_scheduler.py` `_on_krx_market_open()`에 조건부 스킵 추가 — 08:59 사전 구독 성공 시 09:00 구독 스킵, 실패/누락 시 09:00 복구 구독 수행 (P16). (2) `docs/architecture_subscribe_limit_config_design.md` 작성 (379줄) + `docs/plan_subscribe_limit_config.md` 태스크 파일 작성 (374줄) — 3단계 세션 분할 (백엔드 → 프론트엔드 → 문서 갱신).

## 현재 상태 (빌드/테스트 스냅샷)
- **백엔드**: pytest 2935 passed / 0 failed
- **런타임**: `python -W error::RuntimeWarning main.py` 기동 성공, RuntimeWarning 0건
- **프론트엔드**: `npm run build` 성공

## 다음 세션 진행 대기

### 구현 대기 (Step 1 완료, Step 2 대기)
- **종목 구독 한도 설정 키 이관 Step 2 (프론트엔드)**: `docs/plan_subscribe_limit_config.md` 섹션 3 참조. 2파일 수정: (1) `frontend/src/types/index.ts` — `'subscribe.max_0b_count'?: number` 타입 정의 추가. (2) `frontend/src/pages/general-settings.ts` — `createNumInput` import 추가 + `scheduleSubscribeLimitSave()` 신규 저장 함수 + "구독 한도" 섹션 UI 추가 (시간 설정 탭 내 타임테이블 섹션 이후). 검증: `npm run build` + 브라우저 UI 확인 (기본값 200 표시, 값 변경 저장, 1~1000 범위 clamp). Step 3은 문서 갱신 + 계획서 2파일 삭제.

### 기타 대기 항목
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
