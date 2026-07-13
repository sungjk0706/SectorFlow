# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-14: 보유종목/수익현황 페이지 평가손익·수익률 실시간 불일치 해결 — computeHoldingsSummary 공통 함수 도입 (P22/P10/P23/P21)**
  - **현상**: 보유종목 페이지 상단 요약 배지와 수익현황 페이지 계좌현황 섹션의 평가손익/수익률이 개별 종목 합산 값과 크게 불일치 (예: 개별 합산 +268,968원 vs 요약 -900원).
  - **근본 원인**: 두 페이지의 요약/계좌현황은 백엔드 계좌 스냅샷(`account.total_pnl`)을 표시했으나, 개별 종목 행은 프론트엔드에서 실시간 틱 가격(`sectorStocks[code].cur_price`)으로 재계산. 0B 틱 시 계좌 스냅샷은 갱신되지 않고 프론트엔드도 틱 이벤트에 반응하지 않아 요약이 마지막 체결 시점 값에 머물러 있었음.
  - **수정 파일**: 프론트엔드 3개 파일 — `profit-shared.ts`, `sell-position.ts`, `profit-overview.ts`
  - **변경 내용**: (1) `profit-shared.ts` — `computeHoldingsSummary(positions, sectorStocks)` 공통 순수 함수 추가 (평가금액=`sum(현재가×수량)`, 매입금액=`sum(매입가×수량)`, 평가손익=평가금액−매입금액, 수익률=평가손익/매입금액×100 가중평균). `AccountValsParams`에 `positions`/`sectorStocks` 필드 추가. `renderAccountVals`에서 `account.total_pnl` 대신 `computeHoldingsSummary` 사용. (2) `sell-position.ts` — `renderSummary`가 `computeHoldingsSummary` 사용. `onRealDataTick`에서 보유종목 틱 시 `renderSummary` 호출 (별도 `_summaryRafId` rAF 배칭). `unmount`에 `_summaryRafId` 정리 추가. (3) `profit-overview.ts` — `renderAccountVals`에 `positions`/`sectorStocks` 전달. rAF 콜백을 `flushRender` 함수로 추출. `real-data-tick` 리스너 추가 (보유종목 틱 시 `_dirtyAccount=true` 후 `flushRender`). `unmount`에 리스너 정리 추가.
  - **영향 범위**: 프론트엔드 3개 파일 (+104/-45). 백엔드/테스트 영향 없음. `pages` 디렉토리에서 `total_pnl`/`total_eval_amount`/`total_pnl_rate` 직접 사용 0건 확인. `hotStore.ts`/`uiStore.ts`의 스냅샷 동등성 비교 로직은 유지 (참조 변경 감지용, 계산과 무관).
  - **검증**: `npm run build` 1.75s 에러 없음 (60 modules transformed). `npm test` 101 passed (7 files, 6.16s). 잔존 프로세스 0건 (규칙 5-1 준수, 내가 띄운 프로세스 기준).
  - **커밋**: `8dd84a8`

- **2026-07-14: 업종 점수 순위별 차등 점수제 전환 (프론트엔드) — 설정 만점 입력란 3개 + 점수 정수 표시 (P10/P16/P21/P23)**
  - **현상**: 백엔드에서 업종 점수가 순위별 차등 점수제로 전환되었으나, 프론트엔드 설정 화면에 만점 입력란이 없고 업종순위 테이블의 점수가 소수점으로 표시됨.
  - **근본 원인**: (1) `types/index.ts:147-151` — `AppSettings`에 만점 키 3개가 없어 설정 저장/불러오기 불가. (2) `sector-settings.ts:129-141` — ④ 섹션이 안내문만 있고 입력란 없음. (3) `sector-ranking-list.ts:152` + `data-table.ts:273,484,789,854` — 점수를 `toFixed(1)`로 소수점 표시.
  - **수정 파일**: 프론트엔드 4개 파일 — `types/index.ts`, `sector-settings.ts`, `sector-ranking-list.ts`, `data-table.ts`
  - **변경 내용**: (1) `types/index.ts` — `AppSettings`에 신규 키 3개(`sector_bonus_rise_ratio_max`, `sector_bonus_relative_strength_max`, `sector_bonus_trade_amount_max`) 추가, `SectorScoreRow` 주석 "0~300"/"0~100" → "0~만점 합"/"0~만점" 갱신. (2) `sector-settings.ts` — ④ 섹션 안내문 → 만점 입력란 3개(1차=10, 2차=7, 3차=5) + 안내문("1위=만점, 2위=만점-1, ... 0점까지 1점씩 차감")으로 변경, `NUM_KEYS`에 3개 키 추가, `syncFromSettings` 동기화, `unmount` 정리. (3) `sector-ranking-list.ts:152` — `final_score.toFixed(1)` → `String(s.final_score)` (정수). (4) `data-table.ts` — "종합점수" 표시 4곳 `score.toFixed(1)` → `score` (정수).
  - **영향 범위**: 프론트엔드 4개 파일 (+41/-17). 백엔드/테스트 영향 없음. 업종순위 설정 패널 ④ 섹션만 변경, 다른 설정 섹션(①②③⑤)은 영향 없음.
  - **검증**: `npm run build` 1.54s 에러 없음 (60 modules transformed). `npm test` 101 passed (7 files, 7.16s). `score.toFixed`/`final_score.toFixed` 잔존 0건 확인. 사용자 UI 확인 — 업종순위 설정 ④ 섹션 만점 입력란 3개 정상 표시, 값 변경 시 업종 순위 실시간 갱신, 점수 정수 표시 정상. 잔존 프로세스 0건 (규칙 5-1 준수, 내가 띄운 프로세스 기준).
  - **커밋**: `17b9300`

- **2026-07-14: 업종 점수 순위별 차등 점수제 전환 (백엔드) — rank_to_score 제거 + rank_to_tiered_score 도입 + 사용자 설정 만점 3개 (P10/P16/P21/P23/P24)**
  - **현상**: 업종 점수가 `rank_to_score`(0~100점) 방식으로 계산되어 인접 순위 간 격차가 1.67%로 미세했으며, 사용자가 각 조건(1·2·3차)의 중요도를 조절할 수 있는 장치가 없었음.
  - **근본 원인**: `backend/app/domain/sector_score.py:15-53` — `rank_to_score` 함수가 `(N-rank+1)/N×100` 공식으로 0~100점을 부여하여 순위 간 격차가 미세했고, 만점을 사용자가 설정할 수 있는 구조가 없었음.
  - **수정 파일**: 백엔드 7개 파일 + 테스트 5개 파일 + ARCHITECTURE.md — `sector_score.py`, `settings_defaults.py`, `engine_settings.py`, `sector_calculator.py`, `engine_sector_confirm.py`, `sector_data_provider.py`, `engine_service.py` + `test_sector_score.py`, `test_sector_calculator.py`, `test_sector_calculator_integration.py`, `test_engine_sector_confirm.py`, `test_sector_data_provider.py`
  - **변경 내용**: (1) `sector_score.py` — `rank_to_score` 제거 (P16 dead code), 신규 함수 `rank_to_tiered_score(values, max_score)` 추가 (`max(0, max_score-rank+1)` — 1위=만점, 2위=만점-1, ..., 0점까지 1점씩 차감), `calculate_bonus_scores` 시그니처에 만점 파라미터 3개 추가, 1차/3차 tiered 점수 적용, 2차 종목 백분위→업종 평균→업종 간 순위→tiered 변환, 컷오프(min_rise_ratio) 2패스 구조 유지. (2) `settings_defaults.py` — 신규 키 3개(기본값 1차=10, 2차=7, 3차=5). (3) `engine_settings.py` — 3개 키 검증 로직. (4) `sector_calculator.py` — `compute_full_sector_summary` 시그니처 + 만점값 전달. (5) `engine_sector_confirm.py` — 증분/전체 재계산 시 만점값 전달. (6) `sector_data_provider.py` — `recompute_sector_summary_now` 시 만점값 전달. (7) `engine_service.py` — `_SECTOR_UI_KEYS`에 3개 키 추가 → 설정 변경 시 자동 재계산. (8) `ARCHITECTURE.md` — `rank_to_score` 참조 3건 → `rank_to_tiered_score` 갱신 (Code Removal Rules), 점수 범위 0~300 → 0~만점 합. (9) 테스트 5개 파일 — `rank_to_score` 테스트 제거, `rank_to_tiered_score` 테스트 8개 추가, 점수 검증값 변경, 설정 캐시에 새 키 3개 추가.
  - **영향 범위**: 백엔드 7개 파일 + 테스트 5개 파일 + ARCHITECTURE.md (+254/-110). 프론트엔드 영향 없음 (별도 세션). `execute_buy`/`execute_sell` 주문 경로 수정 없음 (P15 준수). 거래 모드: 테스트모드.
  - **검증**: ruff (수정 파일 12개) All checks passed. pytest 백엔드 전체 2737 passed, 50 warnings (기존 mock 경고, 내 수정과 무관). 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 225ms 기동, 에러/Traceback/RuntimeWarning 없음, `[업종] 업종순위 재계산 (3단계 누적 가산점)` + `재계산 완료` 로그 확인. `rank_to_score` 잔존 — `.py` 파일 0건, ARCHITECTURE.md 0건 (계획서는 역사적 로그로 유지). 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `b106a71`

- **2026-07-14: 백엔드 JSON 직렬화 단일 소스 통일 — json_utils.py 범용 dumps/loads 추가 + 10개 파일 30건 직접 호출 교체 (P10/P23/P24)**
  - **현상**: 백엔드 10개 파일에서 `json_utils.py`의 중앙화 함수(`encode/decode_json_field`)가 있음에도 직접 `json.loads/dumps` 호출 (30건). `ensure_ascii=False` 누락 3건으로 한글 데이터 유니코드 이스케이프 저장 위험. P10(SSOT)·P23(일관성) 위반.
  - **근본 원인**: `json_utils.py` docstring이 "Repository Boundary 단일화" 선언만 하고 범용 WS 메시지·파일 파싱용 함수 부재 → 모든 호출처가 `import json` 후 직접 호출. 선언-실행 불일치.
  - **수정 파일**: 백엔드 11개 파일 — `json_utils.py`, `settings_file.py`, `sector_stock_cache.py`, `stock_tables.py`, `market_close_pipeline.py`, `ws_manager.py`, `ws.py`, `ws_orders.py`, `ws_settings.py`, `kiwoom_connector.py`, `ls_connector.py`
  - **변경 내용**: (1) `json_utils.py` — 범용 `dumps(obj, *, ensure_ascii=False, sort_keys=False)` + `loads(text)` 추가, `encode/decode_json_field`는 DB 전용 타입 검증 함수로 유지, docstring "전역 JSON 유틸 + DB 전용 타입 검증"으로 갱신. (2) DB 저장/조회 12건 — `encode_json_field`/`decode_json_field`/`loads` 교체. (3) WS 메시지 12건 — `dumps`/`loads` 교체. (4) 증권사 WS 5건 — `dumps`/`loads` 교체. (5) 파일 I/O 1건 — `loads` 교체. (6) `settings_file.py:296-318` `_parse_value` 이중 파싱(`json.loads` 후 `decode_json_field` 재호출) → `loads` 1회 + `isinstance` 검증으로 단순화 (P24). (7) `except (json.JSONDecodeError, ValueError)` → `except ValueError` 5곳 통일 (`json` import 제거 후 참조 불가, `JSONDecodeError`는 `ValueError` 서브클래스). (8) `stock_tables.py` 기존 미사용 `import sqlite3` 제거 (ruff F401 기존 실패, 규칙 4-1로 수정 전 실패 확인).
  - **영향 범위**: 백엔드 11개 파일 (+97/-80). 프론트엔드/테스트 영향 없음. `encode_json_field`/`decode_json_field` 시그니처 unchanged — 기존 호출처 호환. `ensure_ascii=False`가 3건에 새로 적용되어 한글 데이터 저장 방식 변경 (유니코드 이스케이프 → 직접 한글 저장, 정상 방향).
  - **검증**: ruff (수정 파일 11개) All checks passed. pytest 백엔드 전체 2734 passed, 50 warnings (10.06s). 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 181ms 기동, 에러/Traceback/RuntimeWarning 없음, `[업종] 업종순위 재계산 (3단계 누적 가산점)` + `재계산 완료` 로그 확인. grep 잔존 `json.loads/dumps` 직접 호출 — `json_utils.py` 자신 2건만 (단일 소스 구현, 정상). 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `5afe492`

- **2026-07-14: 프론트엔드 설정 페이지 요약 라벨 가독성 일괄 개선 — createStepLabel 공통 컴포넌트 승격 + 3개 페이지 통일 (P16/P21/P23)**
  - **현상**: 업종순위 설정 ①~⑤ 단계 요약 라벨이 11px(`small`) + #9e9e9e(`disabled`, 비활성 색상)로 가독성 저하. 종목분류 페이지 설명 라벨 2곳도 동일 문제. 일반설정 페이지의 `createDescText`와 3개 페이지가 각각 다른 폰트/색상 패턴 사용 (P23 위반).
  - **근본 원인**: (1) `sector-settings.ts:17-25` 내부 헬퍼 `createStepLabel`이 `FONT_SIZE.small`(11px) + `COLOR.disabled`(#9e9e9e) 사용 — 활성 정보에 비활성 색상. (2) `stock-classification.ts:347-352` `descLabel` 함수가 `FONT_SIZE.badge`(11px) + `COLOR.tertiary`(#666) 사용. (3) `stock-classification.ts:367-370` 인라인 `descLabel`이 `FONT_SIZE.small`(11px) + `COLOR.disabled`(#9e9e9e) 사용. (4) `general-settings.ts:296-297` 두 행 라벨이 붙어 있어 가독성 저하.
  - **수정 파일**: 프론트엔드 4개 파일 — `settings-common.ts`, `sector-settings.ts`, `stock-classification.ts`, `general-settings.ts`
  - **변경 내용**: (1) `settings-common.ts` — `createStepLabel` 공통 컴포넌트 추가 (12px `desc` + #333 `neutral` 검정 + 번호 없는 변형 지원 `extraStyle` 파라미터). (2) `sector-settings.ts` — 내부 헬퍼 제거, 공통 컴포넌트 import, ①~④ 단계 텍스트 축약 (⑤는 변경 없음), 미사용 `FONT_WEIGHT` import 제거. (3) `stock-classification.ts` — `descLabel` 함수 제거 (P16 dead code), 인라인 `descLabel` 2곳 → `createStepLabel` 사용. (4) `general-settings.ts` — 자동매매 탭 2행 라벨 1행 통합. (5) `sector-settings.ts` ④ 가산점 설명 블록 — `createDescText` 5행 분리 + intro/1차 행 여백 추가.
  - **영향 범위**: 프론트엔드 4개 파일 (+40/-39). 백엔드/테스트 영향 없음. P16(dead code 제거)·P21(사용자 투명성 가독성)·P23(일관성) 위반 해결.
  - **검증**: `npm run build` 806ms~2.88s 에러 없음. `npm test` 101 passed (7 files). 잔존 프로세스 0건 (규칙 5-1 준수, 내가 띄운 프로세스 기준).
  - **커밋**: `bf526b3`

- **2026-07-14: ARCHITECTURE.md 섹션6 업종 점수 3단계 누적 가산점 시스템으로 갱신 — 구 가중치/트리밍 설명 제거 + 6.2 재작성 + 6.3 트리밍 섹션 제거 + 섹션 번호 재정렬 (P10/P23)**
  - **현상**: 업종 점수 가산점제 전환(Phase 1~3 + 잔존 정리) 완료 후에도 ARCHITECTURE.md 섹션 5.2/6.1~6.3이 제거된 구 가중치/트리밍 시스템을 설명 중 — 코드-문서 불일치 (P10/P23 위반, Code Removal Rules 위반).
  - **근본 원인**: `ARCHITECTURE.md:686-724` — `total_trade_amount`/`scored_trade_amount`/`scored_rise_ratio`/`metric_scores`/`MetricDef`/`trim_change_rate_pct`/`trim_trade_amt_pct`/`normalize_weight_values`/`calculate_weighted_scores`/`sector_weights` 구 심볼 잔존. `ARCHITECTURE.md:598` 흐름도에도 `calculate_weighted_scores()` + 별도 컷오프 단계로 구 시스템 흐름 잔존.
  - **수정 파일**: `ARCHITECTURE.md` (1개 파일)
  - **변경 내용**: (1) 섹션 5.2 흐름도 L598 — `calculate_weighted_scores()` + 별도 컷오프 단계 → `calculate_bonus_scores() — 3단계 누적 가산점 (0~300) + 컷오프 내부 적용` (옵션 C 2패스 흐름 명시). (2) 섹션 6.1 데이터 모델 L681-689 — `total_trade_amount`/`scored_*`/`metric_scores` 제거 → `avg_trade_amount`/`avg_ratio_5d_pct`/`bonus_rise_ratio`/`bonus_relative_strength`/`bonus_trade_amount` 추가, `final_score` 0~300 명시. (3) 섹션 6.2 L698-727 — "가중치 점수 시스템" → "3단계 누적 가산점 시스템" 전면 재작성 (3개 단계 표, `rank_to_score`/`percentile_to_score` 함수 설명, 옵션 C 2패스 계산 과정 6단계, P22 모집단 정합성 노트). (4) 섹션 6.3 L729 — 트리밍 섹션 제거 + 섹션 번호 재정렬 (6.4→6.3 필터링, 6.5→6.4 증분 연산, 6.6→6.5 가산점).
  - **영향 범위**: ARCHITECTURE.md 1개 파일 (+36/-33). 프로덕션 코드/테스트/프론트엔드 영향 없음 (문서 전용). P10(SSOT)·P23(일관성)·Code Removal Rules 위반 해결.
  - **검증**: ARCHITECTURE.md에서 제거된 심볼(`scored_*`/`total_trade_amount`/`metric_scores`/`MetricDef`/`DEFAULT_METRICS`/`trim_*`/`normalize_weight_values`/`calculate_weighted_scores`/`sector_weights`) 잔존 0건 확인. "가중치 슬라이더/트리밍" 1건 잔존는 L700 "기존 ... 제거하고"로 제거됨을 명시하는 정당한 참조. `docs/plan_*.md` 잔존는 계획서 역사적 로그(Code Removal Rules 규칙3 유지 대상). 잔존 프로세스 0건 (규칙 5-1 준수). 문서 전용 수정이므로 pytest/빌드/런타임 검증 불필요 (코드 동작 영향 없음).
  - **커밋**: `cc41d64`
  - **전수 검증 보고**: 본 세션 시작 시 GLM-5.2 Max 모델로 업종 점수 가산점제 전환 작업 전체(Phase 1 백엔드 11파일 + Phase 2 프론트엔드 8파일 + Phase 3-A 핵심 테스트+버그 수정 + Phase 3-B mock/설정 테스트 6개 + 1순위 total_trade_amount 제거 + 2순위 test_settings_file_integration 정리) 전수 검증 수행. 결과: pytest 2734 passed, ruff(수정 파일 20개) All checks passed, npm run build 1.98s, npm test 101 passed, 런타임 기동 정상 (394ms, `[업종] 업종순위 재계산 (3단계 누적 가산점)` 로그 확인). 제거된 심볼 소스 코드 잔존 0건. 계획서-구현 일치 (경미한 차이 2건: 섹션 번호 ④⑤ 배치, 계획서 명시 3개 테스트 파일 미수정 — 둘 다 정당). 유일한 미해결 = ARCHITECTURE.md 구 시스템 잔존 → 본 세션에서 해결 완료.

- **2026-07-13: 업종 점수 가산점제 전환 잔존 정리 — total_trade_amount 하위 호환 필드 제거 + test_settings_file_integration sector_weights 테스트 데이터 전환 (P10/P16/P20/P23)**
  - **현상**: (1) Phase 1에서 WS payload에 `total_trade_amount`+`avg_trade_amount` 동시 전송(하위 호환), Phase 2 완료로 프론트엔드는 `avg_trade_amount`만 사용 중이나 백엔드가 불필요한 `total_trade_amount` 필드 잔존. (2) `test_settings_file_integration.py` 2개 메서드가 Phase 1에서 제거된 `sector_weights` 키를 테스트 데이터로 사용 중.
  - **근본 원인**: (1) `backend/app/services/sector_data_provider.py:225` — `"total_trade_amount": sc.avg_trade_amount,  # 하위 호환 (Phase 2에서 제거)` 1줄 잔존. (2) `backend/tests/test_settings_file_integration.py:101/177` — `sector_weights` JSON save/load 테스트 데이터가 제거된 키 참조 (P10/P23 위반).
  - **수정 파일**: 백엔드 2개 파일 — `sector_data_provider.py`, `test_settings_file_integration.py`
  - **변경 내용**: (1) `sector_data_provider.py` L225 — `total_trade_amount` 하위 호환 필드 1줄 제거, `avg_trade_amount` 단일 전송. (2) `test_settings_file_integration.py` — `test_loads_json_value_from_db`/`test_saves_json_to_db` 2개 메서드 테스트 데이터 `sector_weights`(`{"rise_ratio": 0.6, "total_trade_amount": 0.4}`) → `sell_per_symbol`(`{"005930": {"tp_val": 10.0}}`) 전환.
  - **영향 범위**: 백엔드 2개 파일. 프론트엔드 영향 없음 (이미 `avg_trade_amount`만 참조). 프로덕션 코드 변경 1줄(필드 제거) + 테스트 2개 메서드.
  - **검증**: pytest 전체 백엔드 2734 passed. ruff All checks passed. 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 에러/Traceback/RuntimeWarning 없음, `[업종] 업종순위 재계산 (3단계 누적 가산점)` + `재계산 완료` 로그 확인, 95ms 기동. 프론트엔드 `npm run build` ✓ built in 2.31s. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `c851a04`

- **2026-07-13: 업종 점수 누적 가산점제 전환 Phase 3-B (테스트) — mock/설정 테스트 6개 파일 전환 (P10/P16/P23/P24)**
  - **현상**: Phase 1(백엔드)에서 제거된 함수/필드(`calculate_weighted_scores`/`normalize_weight_values`/`scored_*`/`sector_weights`/`sector_trim_*`/`migrate_rank_primary_to_weights`/`_migrate_sector_weights`)를 6개 테스트 파일이 참조하여 41건 실패 + 1건 수집 에러.
  - **근본 원인**: (1) `test_engine_sector_confirm.py` 8곳 — `patch("...calculate_weighted_scores")`가 존재하지 않는 속성 patch → `AttributeError`. (2) `test_settings_file.py` — 제거된 2개 함수 import → `ImportError` (수집 에러). (3) `test_engine_settings.py` L102 — `build_engine_settings_dict`가 `sector_weights` 키 더 이상 생성 안 함 → `KeyError`. (4) `test_buy_filter.py` 헬퍼 — `SectorScore(total_trade_amount=..., scored_trade_amount=..., scored_rise_ratio=...)` 3 필드 제거 → `TypeError`. (5) `test_telegram_bot.py` 2곳 — mock에 `scored_trade_amount` 설정, 프로덕션은 `avg_trade_amount` 읽음 → format 오류. (6) `test_sector_data_provider.py` — `scored_trade_amount` mock 속성 + `sector_trim_*`/`sector_weights` settings_cache (프로덕션 미사용 dead data).
  - **수정 파일**: 백엔드 테스트 5개 파일 수정 + 1개 파일 삭제 — `test_engine_sector_confirm.py`, `test_engine_settings.py`, `test_buy_filter.py`, `test_telegram_bot.py`, `test_sector_data_provider.py`, `test_settings_file.py`(삭제)
  - **변경 내용**: (1) `test_engine_sector_confirm.py` — `_make_sector_score` 헬퍼 MagicMock → 실제 `SectorScore` 객체 반환, 7개 테스트 `calculate_weighted_scores` patch → `calculate_bonus_scores` patch, `test_min_rise_ratio_cutoff` patch 제거(실제 `calculate_bonus_scores` 실행, 통합 테스트 전환), 11개 settings_cache에서 `sector_trim_*`/`sector_weights` 3줄씩 제거. (2) `test_settings_file.py` — 파일 전체 삭제 (제거된 2개 함수 테스트만 존재). (3) `test_engine_settings.py` — `sector_weights` 단언문 1줄 제거. (4) `test_buy_filter.py` — `_sector` 헬퍼 `total_trade_amount`→`avg_trade_amount`, `scored_trade_amount`/`scored_rise_ratio` 파라미터+필드 제거. (5) `test_telegram_bot.py` — L1167/1220 `scored_trade_amount` → `avg_trade_amount`. (6) `test_sector_data_provider.py` — `scored_trade_amount` mock 3줄 제거, `sector_trim_*`/`sector_weights` 3줄 제거.
  - **영향 범위**: 백엔드 테스트 5개 파일 수정+1개 파일 삭제. 프로덕션 코드 변경 없음. `test_settings_file_integration.py`의 `sector_weights` 테스트 데이터는 Phase 3-B 범위 제외 (별도 세션 정리 권장).
  - **검증**: pytest 6개 파일 291 passed. pytest 전체 백엔드 2734 passed. ruff All checks passed. 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 에러/Traceback/RuntimeWarning 없음, `[업종] 업종순위 재계산 (3단계 누적 가산점)` + `재계산 완료` 로그 확인, 247ms 기동. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `bafa4e6`

- **2026-07-13: 업종 점수 누적 가산점제 전환 Phase 3-A (테스트) — 핵심 점수 로직 테스트 3개 파일 전환 + percentile_to_score 반전 버그 수정 (P10/P16/P22/P23/P24)**
  - **현상**: Phase 1(백엔드)+Phase 2(프론트엔드) 완료 후 테스트 파일들이 제거된 함수/필드(`calculate_weighted_scores`/`normalize_weight_values`/`scored_*`/`sector_weights`/`trim_*`/`metric_scores`)를 참조하여 실패. 추가로 조사 중 `percentile_to_score` 반전 버그 발견 — 최대값이 0점, 최소값이 100점 부여 (계획서 의도와 반대).
  - **근본 원인**: (1) Phase 1에서 함수/필드 제거 시 테스트 미전환. (2) `sector_score.py:85` 공식 `(rank-1)/(n-1)*100`이 내림차순 정렬에서 rank=1(최대값)에게 0점 부여 — 계획서 의도("가장 많이 오른 종목 = 100점")와 반대. (3) `compute_sector_scores`가 Phase 1에서 랭킹 수행 제외(랭킹은 `compute_full_sector_summary`로 이관)되었으나 기존 테스트 2건이 여전히 `sc.rank`/`sc.final_score` 검증.
  - **수정 파일**: 백엔드 4개 파일 — `sector_score.py`, `test_sector_score.py`, `test_sector_calculator.py`, `test_sector_calculator_integration.py`
  - **변경 내용**: (1) `sector_score.py:85` — 공식 `(rank-1)/(n-1)*100` → `(n-rank)/(n-1)*100` 수정. 최대값=100점, 최소값=0점. (2) `test_sector_score.py` 전면 재작성 — `TestNormalizeWeightValues`/`TestCalculateWeightedScores` 제거, `TestPercentileToScore`(7테스트)/`TestCalculateBonusScores`(12테스트) 신규, 헬퍼 `_make_sector_score`/`_make_stock` 추가, import 수정. (3) `test_sector_calculator.py` — `TestComputeSectorScoresTrimming`/`TestComputeSectorScoresWeights` 제거, `TestComputeSectorScoresNoTrimWeights`(2테스트) 신규, `TestComputeFullSectorSummary::test_bonus_fields_populated_by_full_summary` 신규, 기존 2테스트 rank 검증 수정/제거. (4) `test_sector_calculator_integration.py` — `test_weighted_scores_calculated` → `test_bonus_scores_calculated` 재작성 (`compute_full_sector_summary` 사용, `final_score <= 300.0`, `bonus_*` 0~100 검증).
  - **영향 범위**: 백엔드 4개 파일. 2차 가산점 점수 반전 → 정상 수정으로 업종 순위가 "많이 오른 종목들이 많은 업종"에 높은 점수 부여하도록 정상화. 기존 DB 점수는 다음 재계산 시 자동 갱신. Phase 3-B 대상 6개 파일은 이번 세션 미수정 (기존 실패로 기록).
  - **검증**: pytest 3개 파일 62 passed. ruff All checks passed. 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 에러/Traceback/RuntimeWarning 없음, `[업종] 업종순위 재계산 (3단계 누적 가산점)` + `재계산 완료` 로그 확인, 103ms 기동. 전체 백엔드 테스트(Phase 3-B 6개 제외) 2443 passed. 프론트엔드 빌드 ✓ built in 1.79s. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: (본 커밋)

- **2026-07-13: 업종 점수 누적 가산점제 전환 Phase 2 (프론트엔드) — 가중치 슬라이더+트리밍 UI 제거 + 가산점 안내문 + avg_trade_amount 전환 (P10/P16/P20/P21/P23/P24)**
  - **현상**: Phase 1(백엔드) 완료 후 프론트엔드가 구 가중치 슬라이더/트리밍 UI와 `total_trade_amount` 필드 참조 중. 백엔드가 전송하는 신규 가산점 필드(`bonus_rise_ratio`/`bonus_relative_strength`/`bonus_trade_amount`/`avg_trade_amount`) 미사용.
  - **근본 원인**: 프론트엔드 8개 파일이 구 점수 시스템 기반. `sector-settings.ts`에 ④ 극단값 제외+⑤ 가중치 슬라이더 섹션 잔존, `sector-ranking-list.ts:155`가 `total_trade_amount` 참조, `types/index.ts`·`uiStore.ts`·`binding.ts`에 `sector_weights`/`sector_trim_*`/`normalized_weights` 잔존.
  - **수정 파일**: 프론트엔드 6개 파일 수정 + 2개 파일 삭제 — `types/index.ts`, `uiStore.ts`, `binding.ts`, `sector-settings.ts`, `sector-ranking-list.ts`, `sliderConvert.ts`(삭제), `sliderConvert.test.ts`(삭제). `sector-stock.ts`/`hotStore.ts`는 `final_score`만 참조로 변경 불필요.
  - **변경 내용**: (1) `types/index.ts` — `AppSettings`에서 `sector_weights`/`sector_trim_*` 3필드 제거, `SectorScoreRow`에 `avg_trade_amount` 명명변경+가산점 3필드 추가, `SectorStatus.normalized_weights` 제거. (2) `uiStore.ts` — `normalizedWeights` 필드+초기값 제거. (3) `binding.ts` — `normalized_weights` 수신 처리 3줄 제거. (4) `sector-settings.ts` — ④ 극단값 제외+⑤ 가중치 슬라이더 섹션 전체 제거, 관련 함수 3개+변수 3개+import 4개 제거, `NUM_KEYS`에서 `sector_trim_*` 2개 제거, `syncFromSettings` 가중치/트리밍 동기화 제거, uiStore 구독 normalizedWeights 갱신 제거, unmount dualSlider.destroy 제거, "가산점 자동 계산" 안내문 추가+섹션 번호 재정렬(⑥→⑤). (5) `sector-ranking-list.ts` — `total_trade_amount`→`avg_trade_amount`, 헤더 "종합점수"→"가산점". (6) `sliderConvert.ts`+`sliderConvert.test.ts` 삭제.
  - **영향 범위**: 프론트엔드 6개 파일 수정+2개 파일 삭제. 백엔드 프로덕션 코드 변경 없음. 백엔드 WS payload `total_trade_amount` 하위 호환 필드는 별도 세션에서 제거 예정. Phase 3(테스트 전환) 대기.
  - **검증**: `npm run build` 성공 (✓ built in 1.50s, 60 modules transformed). `npm test` 7 test files 101 tests passed. 프론트엔드 전체 잔존 참조 0건 확인 (`total_trade_amount`/`sector_weights`/`sector_trim`/`normalized_weights`/`sliderConvert` 검색). 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: `2bd0ee9`

- **2026-07-13: 업종 점수 누적 가산점제 전환 Phase 1 (백엔드) — 3단계 가산점 + 트리밍 제거 + 가중치 슬라이더 제거 (P10/P16/P20/P21/P22/P23/P24)**
  - **현상**: 기존 업종 점수 시스템이 2개 지표 가중치 슬라이더 방식 — 상승비율 이진 판단 정보 손실, 가중치 주관 왜곡, 종목 수 비대칭 트리밍 미작동(4종목 업종 round(4×0.1)=0).
  - **근본 원인**: `sector_score.py:77-130` 가중치 합산 방식, `sector_calculator.py:137-166` 트리밍 로직, `models.py:76-99` MetricDef/DEFAULT_METRICS 구조. 절대값 기반 점수의 근본적 한계.
  - **수정 파일**: 백엔드 11개 파일 — `models.py`, `sector_score.py`, `sector_calculator.py`, `engine_sector_confirm.py`, `sector_data_provider.py`, `engine_account_notify.py`, `settings_defaults.py`, `engine_settings.py`, `settings_file.py`, `telegram_bot.py`, `engine_service.py`
  - **변경 내용**: (1) `sector_score.py` — `normalize_weight_values`/`calculate_weighted_scores` 제거, `calculate_bonus_scores` 신규 (옵션 C 2패스: 1차/3차 계산→컷오프→2차 계산→종합 0~300점), `percentile_to_score` 신규 (0~100 완전 백분위). (2) `models.py` — `MetricDef`/`DEFAULT_METRICS` 제거, `SectorScore` 필드 수정 (`scored_*`/`metric_scores` 제거, `total_trade_amount`→`avg_trade_amount` 명명 변경, `bonus_rise_ratio`/`bonus_relative_strength`/`bonus_trade_amount` 신규). (3) `sector_calculator.py` — `sector_weights`/`trim_*` 파라미터 제거, 트리밍 로직 30줄 제거, `calculate_bonus_scores` 호출. (4) `engine_sector_confirm.py` — 컷오프 로직 `calculate_bonus_scores` 내부로 이관, `sector_weights`/`trim_*` 변수 제거. (5) `sector_data_provider.py` — WS payload 가산점 3필드+`avg_trade_amount` 추가, `total_trade_amount` 하위 호환 유지. (6) `engine_account_notify.py` — `normalized_weights` 전송 제거. (7) `settings_defaults.py`/`engine_settings.py`/`settings_file.py` — `sector_weights`/`sector_trim_*` 기본값/처리/마이그레이션 제거. (8) `telegram_bot.py` — `scored_trade_amount`→`avg_trade_amount`. (9) `engine_service.py` — `_SECTOR_UI_KEYS`에서 `sector_weights`/`sector_trim_*` 제거.
  - **영향 범위**: 백엔드 11개 파일. 프론트엔드는 Phase 1에서 WS payload 하위 호환 유지(`total_trade_amount`+`avg_trade_amount` 동시 전송, `final_score` 필드명 유지)로 영향 없음. 테스트는 Phase 3에서 전환 예정 (현재 기존 함수명 참조로 실패 예상).
  - **검증**: py_compile 11개 파일 통과. ruff All checks passed. 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 에러/Traceback/RuntimeWarning 없음, `[업종] 업종순위 재계산 (3단계 누적 가산점)` + `[업종] 재계산 완료` 로그 확인, 127ms 기동. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: (본 커밋)

- **2026-07-13: AGENTS.md 섹션4 세션 시작 절차 신설 — HANDOVER.md 자동 확인 강제 (P21)**
  - **현상**: 세션 시작 시 사용자가 "핸드오버 확인해줘"라고 별도 요청해야만 HANDOVER.md를 확인하는 구조. 미요청 시 진행 중 작업(업종 점수 가산점제 등) 상태를 놓칠 위험.
  - **근본 원인**: 섹션4에 세션 시작 절차 명시 부재. 규칙 6(다음 세션 연속성)은 "HANDOVER.md를 먼저 확인"만 언급하고 자동 수행 의무 미명시.
  - **수정 파일**: `AGENTS.md`, `HANDOVER.md` (2개 파일)
  - **변경 내용**: (1) 섹션4 상단에 "세션 시작 절차" 신설 — HANDOVER.md 자동 확인 강제, 현재 상태 간략 보고, 사용자 지시 대기, 완료 작업 정리(규칙 7 연계). (2) 규칙 6을 새 절차 참조로 간결화.
  - **영향 범위**: 프로덕션 코드 변경 없음. 이후 모든 세션 시작 시 HANDOVER.md 자동 확인.
  - **검증**: AGENTS.md 섹션4 구조 확인. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: (본 커밋)

- **2026-07-13: 수익 상세 페이지 요약/통계 카드 폰트 크기 통일 — 상단 라벨 11px→14px + 하단 라벨/값 12px→14px (P23)**
  - **현상**: 수익 상세 페이지 상단 요약 카드(당일/당월/누적 손익) 라벨이 11px(badge)로 너무 작았고, 하단 통계 카드 6개도 12px(label)로 작았음. 상단 라벨이 손익금액(14px)보다 작아 위계 반전.
  - **근본 원인**: `profit-shared.ts:82` 상단 카드 라벨이 `FONT_SIZE.badge`(11px, 배지/경고용)로 설정되어 카드 제목 역할과 불일치. `profit-detail.ts:467-472` 하단 통계 카드 라벨/값이 `FONT_SIZE.label`(12px)로 설정.
  - **수정 파일**: `frontend/src/pages/profit-shared.ts`, `frontend/src/pages/profit-detail.ts` (2개 파일)
  - **변경 내용**: 상단 카드 라벨 `FONT_SIZE.badge`(11px) → `FONT_SIZE.section`(14px). 하단 통계 카드 라벨/값 `FONT_SIZE.label`(12px) → `FONT_SIZE.section`(14px). 상단/하단 14px 통일.
  - **영향 범위**: `createSummaryCards`는 `profit-detail.ts`에서만 사용 → 다른 페이지 영향 없음.
  - **검증**: `npm run build` 성공 (✓ built in 2.07s). 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: (본 커밋)

- **2026-07-13: 에이전트/스킬 아키텍처 원칙 실행 절차 구체화 — 24원칙 체크리스트 + safe-trade P15/P16/P18 + 금지패턴 5개 + 잔존 프로세스 규칙 5-1 (P10/P16/P20/P21/P23)**
  - **현상**: 에이전트 스킬과 AGENTS.md가 24개 원칙 중 일부만 실행 절차로 구체화하여 사각지대 존재. safe-trade에 거래 핵심 원칙 누락, AGENTS.md에 실행 가능한 체크리스트 부재, 금지 패턴 5개 미참조, 용어 사전 미참조.
  - **근본 원인**: 각 스킬이 개별 원칙만 부분 명시, AGENTS.md 섹션2가 원칙 번호 나열만으로 실행 불가. 사용자가 코딩 지식 없으므로 에이전트 자력 준수 불가.
  - **수정 파일**: AGENTS.md, .devin/skills/{safe-trade,backend-fix,problem-solve,frontend-fix,db-backup}/SKILL.md, HANDOVER.md (7개 파일)
  - **변경 내용**: (1) AGENTS.md 섹션2 체크리스트 신설 — 백엔드 14항목+프론트엔드 3항목+금지패턴 5항목. (2) AGENTS.md 섹션3 규칙 5-1 신설 — 세션 종료 전 잔존 프로세스 완전 종료 강제. (3) safe-trade P15/P16/P18 추가. (4) backend-fix 금지 패턴 5개+RuntimeWarning 검증 추가. (5) problem-solve 사전조사 P10/P16/P20/P21/P22/P23/P24 구체화. (6) frontend-fix P21/P23 추가. (7) 5개 스킬 용어 사전(부록 L) 참조 추가. (8) HANDOVER.md 직전 완료 작업 2건 축소+미해결 문제 6건 삭제.
  - **영향 범위**: 프로덕션 코드 변경 없음. 이후 모든 코드 수정 시 에이전트가 24원칙 체크리스트로 점검. 거래 로직 수정 시 P15/P16/P18 강제 준수.
  - **검증**: git diff 7개 파일 114줄 추가/71줄 삭제. 잔존 프로세스 0건 확인(규칙 5-1 준수). 오타 1건 수정(safe-trade "반도시"→"반드시").
  - **커밋**: `77af288`

## 현재 상태
- **백엔드**: Settlement Engine, RiskManager Phase 1, exchange_calendars 교체, 유령 포지션 재발 방지, 테스트모드 6개월 보관 정책, JIF 경계 이벤트 즉시 갱신 — 모두 완료 (git history 참조)
- **프론트엔드**: 더미 데이터 삭제, 차트 툴팁, 색상 체계 통일, 수익현황/수익상세 기간 전환, DataTable 컬럼 너비 안정화, applyIndexRefresh dead code 제거 + applyIndexData market_phase 갱신 — 모두 완료, `npm run build` 통과 (git history 참조)
- **테스트**: 백엔드 pytest 56 passed (test_engine_ws_dispatch.py). 커버리지 Phase 1~3 완료
- **규칙/문서 정리**: AGENTS.md 4섹션 구조, 아키텍처 원칙 24개, .devin/workflows 제거 + skills 통합 — 완료 (2026-07-13)

## 진행 중 작업

### 보유종목/수익현황 페이지 평가손익·수익률 실시간 불일치 해결 — 완료
- **상태**: 프론트엔드 3개 파일 수정 완료 (`8dd84a8`). 빌드 + 테스트 통과. 사용자 UI 확인 대기.
- **내용**: `computeHoldingsSummary` 공통 함수로 두 페이지(보유종목 요약 배지 + 수익현황 계좌현황)가 개별 종목 행과 동일한 데이터 소스(positions + sectorStocks)·공식으로 평가손익/수익률 계산. `real-data-tick` 이벤트에 반응하여 실시간 갱신.
- **대기**: 사용자 브라우저 UI 확인 — (1) 보유종목 페이지 개별 합산=요약 일치, (2) 수익현황 계좌현황=보유종목 요약 일치, (3) 실시간 가격 변동 시 두 페이지 갱신.

### 업종 점수 순위별 차등 점수제 전환 — 백엔드+프론트엔드 완료
- **상태**: 백엔드 전환(`b106a71`) + 프론트엔드 전환(`17b9300`) 완료. 사용자 UI 확인 완료. 본 전환 작업 완료.
- **배경**: 기존 3단계 누적 가산점(0~300, `rank_to_score`)은 인접 순위 간 격차가 1.67%로 미세하여 순위 구분이 애매했음. 사용자가 각 조건의 중요도를 조절할 수 없었음.
- **전환 내용**: `rank_to_score`(0~100) → `rank_to_tiered_score`(0~사용자 설정 만점). 1위=만점, 2위=만점-1, ..., 0점까지 1점씩 차감. 사용자 설정 만점 3개(1차=10, 2차=7, 3차=5 기본값). 컷오프(min_rise_ratio) 2패스 구조 유지.
- **백엔드 완료** (`b106a71`): `sector_score.py`(`rank_to_score` 제거, `rank_to_tiered_score` 도입), `settings_defaults.py`/`engine_settings.py`(신규 키 3개), `sector_calculator.py`/`engine_sector_confirm.py`/`sector_data_provider.py`(만점값 전달), `engine_service.py`(`_SECTOR_UI_KEYS` 추가 → 설정 변경 시 자동 재계산), ARCHITECTURE.md(참조 갱신), 테스트 5개 파일. pytest 2737 passed + ruff 0건 + 런타임 기동 통과.
- **프론트엔드 완료** (`17b9300`): `types/index.ts`(신규 키 3개), `sector-settings.ts`(④ 섹션 만점 입력란 3개), `sector-ranking-list.ts`+`data-table.ts`(점수 정수 표시). `npm run build` 1.54s + `npm test` 101 passed 통과. 사용자 UI 확인 완료.

### 업종 점수 누적 가산점제 전환 (구 작업 — 완료)
- **계획서**: `docs/plan_sector_bonus_points.md` (895줄 — 2026-07-13 갱신)
- **상태**: Phase 1~3-B + 잔존 정리 + ARCHITECTURE.md 갱신 + 전수 검증 완료. 이후 순위별 차등 점수제로 재전환 완료 (상단 참조).
- **추가 개선점**: 3차 가산점 median 대안(편향 모니터링 후 전환 검토) — 순위별 차등 점수제 전환 후에는 median 대안 불필요 (순위 기반이므로 절대값 왜곡 영향 없음)

### 아키텍처 전수 점검 — B-09 완료, 20개 미시작 (일시 보류)
- **완료**: B-01~B-09, F-01 (P0 전체 + B-06~B-09)
- **미시작**: B-10~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-10 (엔진 계좌/서비스) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 중복 로직 정리 — 2순위 (백엔드 설정 로드/마스킹 단일화)
- **상태**: 중복 로직 전수 조사 완료 (백엔드 8건 + 프론트엔드 9건 = 17건 식별). 1순위(JSON 직렬화 통일) 완료 (커밋 `5afe492`).
- **2순위**: 백엔드 설정 로드/마스킹/복호화 로직 단일화 — `engine_settings.py`로 통합
  - `settings_store.py:220-251`(`build_masked_settings_dict`)와 `engine_config.py:117-133`(`_mask_sensitive_settings`) 마스킹 중복
  - `engine_settings.py:28-39`(`_dec`)와 `settings_file.py:141-145` 복호화 유사 패턴
  - 영향 파일: 3개 (`engine_settings.py`, `settings_store.py`, `engine_config.py`)
- **3순위 이후**: 프론트엔드 숫자/소수점 포맷팅 통일 → 프론트엔드 설정 페이지 행 스타일 공통화 → 프론트엔드 날짜 포맷팅 공통화 → 백엔드 종목코드 정규화 → 백엔드 REG 페이로드 → 백엔드 KST 타임존 → 기타 LOW 항목
- **참고**: 각 항목은 세션당 1단계 원칙(규칙 0-1)에 따라 한 세션에 하나씩 진행

### 아키텍처 전수 점검 (일시 보류)
- B-10: 엔진 계좌/서비스 (`engine_account.py`, `engine_account_rest.py`, `engine_account_notify.py`, `engine_service.py`)
- `docs/architecture_audit_plan.md` 체크리스트 사용, 발견 문제를 섹션 7에 등록
- 이후 B-11 (P1) → B-12~B-19 (P2) → B-20~B-23 (P3) → F-02~F-07 순서

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결**
  - 상세 조사 기록: `docs/ghost_position_investigation.md` ([A]~[I] 미조사 항목)
  - 재발 방지 조치 (2026-07-10, 코드 확인 완료):
    - `test_positions` 테이블 제거 — `stock_tables.py:141`, DB 저장 로직 전체 제거
    - `trades` 기반 SSOT 전환 — `dry_run.py:38-68`, `trade_history.py:549`
    - `execute_sell()` 런타임 가드 — `trading.py:418-436` (유령 포지션 차단 + Telegram 알림)
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 수동 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성

## 테스트 실행 원칙 (필수 준수)

### 1. 실행 명령어 (통일)
```
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- `timeout_method = signal` 필수 — `thread` 방식은 asyncio C-level wait를 interrupt하지 못해 hang 시 프로세스가 영구 블록됨
- `pytest.ini`에 전역 설정되어 있으므로 CLI에서 생략 가능

### 2. 자동 hang 체크 원칙 (에이전트 필수 강제 — 수동 개입 금지)
- **a. 10초마다 진행 상태 자동 체크**: 테스트 실행 후 `command_status`로 주기적 확인
- **b. 10초 이상 로그/출력 멈추면 즉시 hang 간주**: 대기 없이 강제 종료 결정
- **c. hang 감지 시 즉시 프로세스 강제 종료**: SIGTERM/Ctrl+C로 프로세스 종료
- **d. hang 원인 자동 분석**: 종료 후 로그/코드 분석하여 원인 보고
- **e. 위 모든 과정은 에이전트가 자동 수행**: 사용자 확인 대기 금지, 수동 개입 금지
- 정상 완료: "✅ N passed in N.Ns"
- hang 감지: "❌ 10초 이상 응답 없음 — 강제 종료 및 원인 분석 시작"

### 3. 테스트 hang 방지 코딩 원칙 (근본 원인별)

#### 원인 A: 실제 asyncio 동기화 프리미티브 (Lock/Event/wait_for)
- **금지**: 테스트에서 실제 `asyncio.Lock()`, `asyncio.Event()`, `asyncio.wait_for()` 사용
- **해결**: `MagicMock` + `AsyncMock`으로 교체
  - Lock: `lock.__aenter__ = AsyncMock(return_value=lock)`, `lock.__aexit__ = AsyncMock(return_value=None)`
  - Event: `ev.wait = AsyncMock()`, `ev.clear/set = MagicMock()`
  - wait_for: 즉시 반환 또는 즉시 `TimeoutError` 발생시키는 async 함수로 patch

#### 원인 B: asyncio.create_task 백그라운드 태스크
- **금지**: 테스트에서 `asyncio.create_task()`가 실제 실행되는 것을 허용
- **해결**: `patch("module.asyncio.create_task")`로 mock 교체, `add_done_callback` 속성 포함

#### 원인 C: NotificationWorker / 백그라운드 워커 싱글톤
- **금지**: `_fire_and_forget_telegram` 등이 실제 `NotificationWorker.get_instance()`를 호출하여 백그라운드 태스크 생성
- **해결**: autouse fixture에서 `patch("module._fire_and_forget_telegram")` 처리

#### 원인 D: 실제 DB I/O (aiosqlite)
- **금지**: 테스트에서 `get_db_connection()`이 실제 DB에 연결
- **해결**: autouse fixture에서 `patch("backend.app.db.database.get_db_connection")` 처리

#### 원인 E: pytest-asyncio 이벤트 루프 간섭
- **금지**: conftest.py에 async fixture 사용 (이벤트 루프 정리 중 hang 유발)
- **금지**: conftest.py에서 `asyncio.sleep` 전역 patch (pytest-asyncio 내부 동작 간섭)
- **해결**: conftest.py는 동기 fixture만 사용, 캐시 리셋 등 최소 기능만 유지

### 4. run_command 사용 시
- `Blocking: false` + `WaitMsBeforeAsync: 20000` — hang 감지 시 명령 취소 가능
- 또는 subprocess + `proc.wait(timeout=N)` + `proc.kill()` 패턴 사용
