# SectorFlow Handover

## 세션 개요 (최근)
- **2026-07-18**: 리스크 매니저 확장 설계서 작성 완료 (1세션). 1파일 신규: `docs/architecture_risk_manager_extension_design.md` (862줄). 일반설정 자동매매 탭에 "전역매매설정 (리스크 매니저)" 섹션 추가 설계 — 수익금/수익률/손실률 기반 매매 중단 + 일일 손실 한도 UI 노출 + 연속 손실 횟수 중단 + 리스크 매니저 전체 토글 + 매수/매도 차단 체크박스. 핵심 설계 결정 7가지: (1) 손익 집계 기준 = 현금 기준 `get_total_realized_pnl` (기존 `daily_loss_limit`과 동일, P23 일관성), (2) 매도 차단 조건 배선 = `check_sell_order_allowed()` 내부 (P15 단일 경로, P16 살아있는 경로), (3) 매수 차단 조건 배선 = `check_buy_order_allowed()` 내부, (4) UI 차단 표시 = 기존 헤더 칩 패턴 재사용 (`circuit_breaker_open`/`order_time_blocked` 동일 패턴, 새 WS 이벤트 `risk_block_status`), (5) 일일 손실 한도 = 기존 `daily_loss_limit` 키 UI 노출 (레거시 `max_daily_loss_limit` 호환), (6) 매도 차단 기본값 = `risk_block_sell_on` False (손실 확대 방지, 사용자 명시적 ON), (7) 연속 손실 기준 = 최근 매도 `realized_pnl`(순수 차익) 음수 연속 건수. 신규 설정 키 12개 + 신규 사유코드 4개 (`BUY_REJECT_RISK_PROFIT`/`_LOSS_RATE`/`_PROFIT_RATE`/`_CONSEC_LOSS`, 모두 `BUY_GLOBAL_REJECT_REASONS` 추가). 영향 범위: 백엔드 5파일 수정 + 프론트엔드 4파일 수정 + 테스트 3파일 수정 + 1파일 신규. P10/P15/P16/P17/P20/P21/P22/P23/P24 9개 원칙 부합 분석 포함. 다음 세션: 태스크 파일 작성 (`docs/plan_risk_manager_extension.md`) 승인 대기.
- **2026-07-18 (이전)**: 다운로드 진행률 로그 1줄 갱신 방식 구현 완료. 4파일 수정: (1) `backend/app/core/logger.py` — `log_progress()` / `log_progress_end()` 헬퍼 추가 (TTY 시 `\r` 1줄 갱신, non-TTY 시 `\n` 출력으로 파이프 깨짐 방지, 파일은 DEBUG 기록), `_stdout_sink`에 `_progress_active` 상태 추가 — 진행률 `\r` 갱신 중 다른 로그 끼어들면 `\n`으로 진행 줄 종료 후 출력 (인터리브 커서 꼬임 방지, P23/P24). (2) `backend/app/core/kiwoom_stock_rest.py` — `fetch_ka10081_all_stocks_daily_confirmed` (264 라인) + `fetch_ka10081_all_stocks_5day` (311 라인) per-stock `logger.info("진행 중: N/M (X%)")` → `log_progress("[다운로드]", len(result), total, code=cd)` 교체 + 루프 종료 후 `log_progress_end()`. (3) `backend/app/services/market_close_pipeline.py` — `refresh_confirmed_5d_data` 직접 루프 (1270 라인) 동일 교체 + 루프 종료 후 `log_progress_end()`. (4) `backend/tests/test_logger.py` — `TestLogProgress` 6개 테스트 추가 (TTY `\r` 출력 + non-TTY `\n` 출력 + 0 total 안전 + `log_progress_end` 활성/비활성 + `_stdout_sink` 인터리브 `\n` 삽입). 효과: 1일봉 다운로드 1,356줄 INFO → 콘솔 1줄 `\r` 갱신 + 파일 0줄 (DEBUG). 시작/완료 1줄 INFO + 실패 per-stock WARNING 유지 (P21 사용자 투명성). 검증: py_compile 3파일 OK + pytest 172 passed (test_logger 40 + test_kiwoom_stock_rest 75 + test_market_close_pipeline 57) + 런타임 기동 OK + TTY/non-TTY/인터리브 콘솔 동작 확인.
- **2026-07-18 (이전)**: 종목 구독 한도 설정 키 이관 Step 3 (문서 갱신 + 계획서 삭제) 완료. 1파일 수정 + 2파일 삭제: (1) `ARCHITECTURE.md` 5.1절 "WS 구독 대상" — "200개 한도" → "설정 가능 한도 `subscribe.max_0b_count` 기본 200" (P10 SSOT, P21 사용자 투명성). (2) `ARCHITECTURE.md` 6.3절 "필터링" — 동일 표현 갱신. (3) `docs/architecture_subscribe_limit_config_design.md` 삭제 (tracked, git rm). (4) `docs/plan_subscribe_limit_config.md` 삭제 (untracked, rm). 검증: `ARCHITECTURE.md` 내 "200개 한도"/"_WS_0B_LIMIT" 잔존 표현 grep 0건 + `subscribe.max_0b_count` 2곳 명시 확인. 종목 구독 한도 설정 키 이관 3단계(백엔드→프론트엔드→문서) 전체 완료.
- **2026-07-18 (이전)**: 시간 설정 탭 라벨/설명 문구 정리 완료. 1파일 수정: `frontend/src/pages/general-settings.ts`. (1) 사전 준비 시간 섹션 — 제목 "장 시작 전 사전 준비 시간" → "사전 준비 시간 설정", 설명 문구 제목 중복 제거("너무 늦으면 실시간 데이터가 누락될 수 있습니다."만 남김). (2) 3개 입력칸 라벨/설명 갱신 — "실시간 항목 초기화"→"실시간 데이터 필드 초기화" + "장 시작 전 필드를 비워 새 데이터를 받을 준비를 합니다", "구독 사전 시작"→"NXT 종목 구독 신청" + "NXT 프리마켓 시작 전 구독을 미리 신청합니다", "정규장 사전 구독"→"KRX 종목 추가 구독" + "KRX 정규장 시작 전 KRX 단독 종목 구독을 추가합니다". (3) 1일봉차트 자동다운로드 단일 항목 섹션 제목 제거 — 행 라벨 "1일봉차트 자동다운로드"만 유지 (P24 단순성, 다중 행 섹션은 제목 유지 예외적 단순화). 검증: `npm run typecheck` + `npm run build` 성공.
- **2026-07-18 (이전)**: 종목 구독 한도 설정 키 이관 Step 2 (프론트엔드) 완료. 2파일 수정: (1) `frontend/src/types/index.ts` — `AppSettings`에 `'subscribe.max_0b_count'?: number` 명시적 타입 추가 (P23 일관성). (2) `frontend/src/pages/general-settings.ts` — `createNumInput` import 추가 + 모듈 상태 변수 `subscribeMaxInput` + 시간 설정 탭 끝(거래소 고정 시간 참고 박스 이후)에 "구독 한도" 섹션 추가 + `syncFromSettings` 값 동기화. UI: "종목 동시 구독 최대 개수" 입력칸 (기본값 200, 범위 1~1000, 10 단위 스핀, 자동 저장, UI clamp + 백엔드 422 이중 방어). 검증: `npm run build` 성공 (tsc 타입체크 + vite 빌드, 타입 오류 0건).
- **2026-07-18 (이전)**: 종목 구독 200개 한도 설정 키 이관 Step 1 (백엔드) 완료. `subscribe.max_0b_count` 설정 키 추가 (기본값 200, 범위 1~1000). 백엔드 4파일 수정: (1) `settings_defaults.py` — 신규 키 기본값 200 추가. (2) `engine_settings.py` — 타입 캐스팅 `int(_v if _v is not None else 200)` 추가 (P20 폴백 금지 패턴 준수). (3) `engine_ws_reg.py:258` — 하드코딩 `_WS_0B_LIMIT = 200` → `int(engine_state.state.integrated_system_settings_cache.get("subscribe.max_0b_count", 200))` 교체 (P10 SSOT, P13 메모리 상주). (4) `settings_store.py` — `apply_settings_updates()` 내 범위 검증 추가 (1~1000 외 ValueError → 422 차단, P20/P22). 테스트 6개 신규 추가: `test_engine_ws.py` 한도 적용 로직 2개 (설정값 반영 + 기본값 200 폴백), `test_settings_store.py` 범위 검증 4개 (0/1001/비정수 거부 + 유효범위 통과). 검증: py_compile OK + 런타임 기동 OK (RuntimeWarning 0건) + 전체 회귀 2935 passed / 0 failed.
- **2026-07-18 (이전)**: 09:00 KRX 구독 중복 요청 제거 + 200개 한도 설정화 설계서 작성. (1) `daily_time_scheduler.py` `_on_krx_market_open()`에 조건부 스킵 추가 — 08:59 사전 구독 성공 시 09:00 구독 스킵, 실패/누락 시 09:00 복구 구독 수행 (P16). (2) `docs/architecture_subscribe_limit_config_design.md` 작성 (379줄) + `docs/plan_subscribe_limit_config.md` 태스크 파일 작성 (374줄) — 3단계 세션 분할 (백엔드 → 프론트엔드 → 문서 갱신).

## 현재 상태 (빌드/테스트 스냅샷)
- **백엔드**: pytest 2935 passed / 0 failed
- **런타임**: `python -W error::RuntimeWarning main.py` 기동 성공, RuntimeWarning 0건
- **프론트엔드**: `npm run build` 성공

## 다음 세션 진행 대기

### 리스크 매니저 확장 (다단계 작업 진행 중)
- **현재 단계**: 1세션 (설계) 완료 → 2세션 (태스크 파일 작성) 승인 대기
- **참조 문서**: `docs/architecture_risk_manager_extension_design.md` (862줄, 설계 완료)
- **다음 세션**: `docs/plan_risk_manager_extension.md` 태스크 파일 작성 — 본 설계서를 구현 단위 태스크로 분할 (백엔드 → 프론트엔드 → 테스트 → 런타임 기동 검증 순서)
- **이후 세션들**: 태스크 파일 기반 단계별 구현 (각 세션당 1단계 원칙 준수)

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
