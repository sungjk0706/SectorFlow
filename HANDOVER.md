# SectorFlow Handover

## 세션 개요 (최근)
- **2026-07-18**: 시간 설정 탭 라벨/설명 문구 정리 완료. 1파일 수정: `frontend/src/pages/general-settings.ts`. (1) 사전 준비 시간 섹션 — 제목 "장 시작 전 사전 준비 시간" → "사전 준비 시간 설정", 설명 문구 제목 중복 제거("너무 늦으면 실시간 데이터가 누락될 수 있습니다."만 남김). (2) 3개 입력칸 라벨/설명 갱신 — "실시간 항목 초기화"→"실시간 데이터 필드 초기화" + "장 시작 전 필드를 비워 새 데이터를 받을 준비를 합니다", "구독 사전 시작"→"NXT 종목 구독 신청" + "NXT 프리마켓 시작 전 구독을 미리 신청합니다", "정규장 사전 구독"→"KRX 종목 추가 구독" + "KRX 정규장 시작 전 KRX 단독 종목 구독을 추가합니다". (3) 1일봉차트 자동다운로드 단일 항목 섹션 제목 제거 — 행 라벨 "1일봉차트 자동다운로드"만 유지 (P24 단순성, 다중 행 섹션은 제목 유지 예외적 단순화). 검증: `npm run typecheck` + `npm run build` 성공.
- **2026-07-18 (이전)**: 종목 구독 한도 설정 키 이관 Step 2 (프론트엔드) 완료. 2파일 수정: (1) `frontend/src/types/index.ts` — `AppSettings`에 `'subscribe.max_0b_count'?: number` 명시적 타입 추가 (P23 일관성). (2) `frontend/src/pages/general-settings.ts` — `createNumInput` import 추가 + 모듈 상태 변수 `subscribeMaxInput` + 시간 설정 탭 끝(거래소 고정 시간 참고 박스 이후)에 "구독 한도" 섹션 추가 + `syncFromSettings` 값 동기화. UI: "종목 동시 구독 최대 개수" 입력칸 (기본값 200, 범위 1~1000, 10 단위 스핀, 자동 저장, UI clamp + 백엔드 422 이중 방어). 검증: `npm run build` 성공 (tsc 타입체크 + vite 빌드, 타입 오류 0건).
- **2026-07-18 (이전)**: 종목 구독 200개 한도 설정 키 이관 Step 1 (백엔드) 완료. `subscribe.max_0b_count` 설정 키 추가 (기본값 200, 범위 1~1000). 백엔드 4파일 수정: (1) `settings_defaults.py` — 신규 키 기본값 200 추가. (2) `engine_settings.py` — 타입 캐스팅 `int(_v if _v is not None else 200)` 추가 (P20 폴백 금지 패턴 준수). (3) `engine_ws_reg.py:258` — 하드코딩 `_WS_0B_LIMIT = 200` → `int(engine_state.state.integrated_system_settings_cache.get("subscribe.max_0b_count", 200))` 교체 (P10 SSOT, P13 메모리 상주). (4) `settings_store.py` — `apply_settings_updates()` 내 범위 검증 추가 (1~1000 외 ValueError → 422 차단, P20/P22). 테스트 6개 신규 추가: `test_engine_ws.py` 한도 적용 로직 2개 (설정값 반영 + 기본값 200 폴백), `test_settings_store.py` 범위 검증 4개 (0/1001/비정수 거부 + 유효범위 통과). 검증: py_compile OK + 런타임 기동 OK (RuntimeWarning 0건) + 전체 회귀 2935 passed / 0 failed.
- **2026-07-18 (이전)**: 09:00 KRX 구독 중복 요청 제거 + 200개 한도 설정화 설계서 작성. (1) `daily_time_scheduler.py` `_on_krx_market_open()`에 조건부 스킵 추가 — 08:59 사전 구독 성공 시 09:00 구독 스킵, 실패/누락 시 09:00 복구 구독 수행 (P16). (2) `docs/architecture_subscribe_limit_config_design.md` 작성 (379줄) + `docs/plan_subscribe_limit_config.md` 태스크 파일 작성 (374줄) — 3단계 세션 분할 (백엔드 → 프론트엔드 → 문서 갱신).

## 현재 상태 (빌드/테스트 스냅샷)
- **백엔드**: pytest 2935 passed / 0 failed
- **런타임**: `python -W error::RuntimeWarning main.py` 기동 성공, RuntimeWarning 0건
- **프론트엔드**: `npm run build` 성공

## 다음 세션 진행 대기

### 구현 대기 (Step 2 완료, Step 3 대기)
- **종목 구독 한도 설정 키 이관 Step 3 (문서 갱신 + 계획서 삭제)**: `docs/plan_subscribe_limit_config.md` 섹션 1.3 참조. 1파일 수정 + 2파일 삭제: (1) `ARCHITECTURE.md` 5.1절 "WS 구독 대상" — `subscribe.max_0b_count` 설정 키 언급 추가. (2) `ARCHITECTURE.md` 6.3절 "필터링" — "200개 한도" 표현 → "설정 가능 한도(기본 200)"로 수정. (3) `docs/architecture_subscribe_limit_config_design.md` 삭제. (4) `docs/plan_subscribe_limit_config.md` 삭제. 검증: `ARCHITECTURE.md` 내 "200개 한도" 잔존 표현 grep 확인 + 계획서 2파일 삭제 확인. **브라우저 UI 확인 보류**: Step 2 빌드는 통과했으나 브라우저 실화면 확인(기본값 200 표시, 값 변경 저장, 1~1000 clamp 동작)은 사용자가 직접 진행 권장 — Step 3 세션에서 사용자 확인 후 진행하거나 별도 세션에서 확인.

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
