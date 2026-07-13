# HANDOVER — SectorFlow

## 직전 완료 작업
- **2026-07-13: 업종 점수 누적 가산점제 전환 Phase 3-B (테스트) — mock/설정 테스트 6개 파일 전환 (P10/P16/P23/P24)**
  - **현상**: Phase 1(백엔드)에서 제거된 함수/필드(`calculate_weighted_scores`/`normalize_weight_values`/`scored_*`/`sector_weights`/`sector_trim_*`/`migrate_rank_primary_to_weights`/`_migrate_sector_weights`)를 6개 테스트 파일이 참조하여 41건 실패 + 1건 수집 에러.
  - **근본 원인**: (1) `test_engine_sector_confirm.py` 8곳 — `patch("...calculate_weighted_scores")`가 존재하지 않는 속성 patch → `AttributeError`. (2) `test_settings_file.py` — 제거된 2개 함수 import → `ImportError` (수집 에러). (3) `test_engine_settings.py` L102 — `build_engine_settings_dict`가 `sector_weights` 키 더 이상 생성 안 함 → `KeyError`. (4) `test_buy_filter.py` 헬퍼 — `SectorScore(total_trade_amount=..., scored_trade_amount=..., scored_rise_ratio=...)` 3 필드 제거 → `TypeError`. (5) `test_telegram_bot.py` 2곳 — mock에 `scored_trade_amount` 설정, 프로덕션은 `avg_trade_amount` 읽음 → format 오류. (6) `test_sector_data_provider.py` — `scored_trade_amount` mock 속성 + `sector_trim_*`/`sector_weights` settings_cache (프로덕션 미사용 dead data).
  - **수정 파일**: 백엔드 테스트 5개 파일 수정 + 1개 파일 삭제 — `test_engine_sector_confirm.py`, `test_engine_settings.py`, `test_buy_filter.py`, `test_telegram_bot.py`, `test_sector_data_provider.py`, `test_settings_file.py`(삭제)
  - **변경 내용**: (1) `test_engine_sector_confirm.py` — `_make_sector_score` 헬퍼 MagicMock → 실제 `SectorScore` 객체 반환, 7개 테스트 `calculate_weighted_scores` patch → `calculate_bonus_scores` patch, `test_min_rise_ratio_cutoff` patch 제거(실제 `calculate_bonus_scores` 실행, 통합 테스트 전환), 11개 settings_cache에서 `sector_trim_*`/`sector_weights` 3줄씩 제거. (2) `test_settings_file.py` — 파일 전체 삭제 (제거된 2개 함수 테스트만 존재). (3) `test_engine_settings.py` — `sector_weights` 단언문 1줄 제거. (4) `test_buy_filter.py` — `_sector` 헬퍼 `total_trade_amount`→`avg_trade_amount`, `scored_trade_amount`/`scored_rise_ratio` 파라미터+필드 제거. (5) `test_telegram_bot.py` — L1167/1220 `scored_trade_amount` → `avg_trade_amount`. (6) `test_sector_data_provider.py` — `scored_trade_amount` mock 3줄 제거, `sector_trim_*`/`sector_weights` 3줄 제거.
  - **영향 범위**: 백엔드 테스트 5개 파일 수정+1개 파일 삭제. 프로덕션 코드 변경 없음. `test_settings_file_integration.py`의 `sector_weights` 테스트 데이터는 Phase 3-B 범위 제외 (별도 세션 정리 권장).
  - **검증**: pytest 6개 파일 291 passed. pytest 전체 백엔드 2734 passed. ruff All checks passed. 런타임 기동 `.venv/bin/python -W error::RuntimeWarning main.py` — 에러/Traceback/RuntimeWarning 없음, `[업종] 업종순위 재계산 (3단계 누적 가산점)` + `재계산 완료` 로그 확인, 247ms 기동. 잔존 프로세스 0건 (규칙 5-1 준수).
  - **커밋**: (본 커밋)

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

### 업종 점수 누적 가산점제 전환 — Phase 1(백엔드)+Phase 2(프론트엔드)+Phase 3-A(테스트 3개)+Phase 3-B(테스트 6개) 완료
- **계획서**: `docs/plan_sector_bonus_points.md` (895줄 — 2026-07-13 갱신)
- **상태**: Phase 1(백엔드 전환) + Phase 2(프론트엔드 전환) + Phase 3-A(핵심 점수 로직 테스트 3개) + Phase 3-B(mock/설정 테스트 6개) 완료. 본 전환 작업 완료.
- **Phase 1 완료**: 백엔드 11개 파일 전환 — 3단계 누적 가산점(0~300), 트리밍 제거, 가중치 슬라이더 제거. 런타임 기동 검증 통과.
- **Phase 2 완료**: 프론트엔드 6개 파일 수정+2개 파일 삭제 — 가중치 슬라이더/트리밍 UI 제거, "가산점 자동 계산" 안내문 추가, `avg_trade_amount` 전환, `normalizedWeights` 제거, `sliderConvert.ts` 삭제. `npm run build`+`npm test` 101 passed 통과.
- **Phase 3-A 완료**: 백엔드 테스트 3개 파일 전환 — `test_sector_score.py`(전면 재작성, 27테스트), `test_sector_calculator.py`(클래스 2제거+1신규, 28테스트), `test_sector_calculator_integration.py`(테스트 1 재작성, 7테스트). `percentile_to_score` 반전 버그 수정(`sector_score.py:85`). pytest 62 passed + ruff 0건 + 런타임 기동 통과.
- **Phase 3-B 완료**: 백엔드 테스트 5개 파일 수정+1개 파일 삭제 — `test_engine_sector_confirm.py`(헬퍼 실제 `SectorScore` 전환+7개 patch 교체+`test_min_rise_ratio_cutoff` 통합 테스트 전환+11개 settings_cache 정리), `test_settings_file.py`(삭제), `test_engine_settings.py`(`sector_weights` 단언 제거), `test_buy_filter.py`(`_sector` 헬퍼 전환), `test_telegram_bot.py`(2줄 `scored_trade_amount`→`avg_trade_amount`), `test_sector_data_provider.py`(dead mock/data 6줄 제거). pytest 6개 파일 291 passed + 전체 2734 passed + ruff 0건 + 런타임 기동 통과.
- **WS payload 하위 호환**: Phase 1에서 `total_trade_amount`+`avg_trade_amount` 동시 전송, `final_score` 필드명 유지. Phase 2 완료로 프론트엔드는 `avg_trade_amount` 사용 중. `total_trade_amount` 하위 호환 필드는 별도 세션에서 백엔드 제거 예정.
- **잔존 정리 항목**: `test_settings_file_integration.py`의 `sector_weights` 테스트 데이터 (별도 세션 정리 권장)
- **추가 개선점**: 3차 가산점 median 대안(편향 모니터링 후 전환 검토)

### 아키텍처 전수 점검 — B-09 완료, 20개 미시작 (일시 보류)
- **완료**: B-01~B-09, F-01 (P0 전체 + B-06~B-09)
- **미시작**: B-10~B-11 (P1), B-12~B-19 (P2), B-20~B-23 (P3), F-02~F-07 (P1~P3)
- 다음 세션: B-10 (엔진 계좌/서비스) — `docs/architecture_audit_plan.md` 체크리스트 사용

## 다음 단계

### 1순위: 백엔드 WS payload `total_trade_amount` 하위 호환 필드 제거 — 승인 대기
- **상태**: Phase 1에서 `total_trade_amount`+`avg_trade_amount` 동시 전송(하위 호환), Phase 2 완료로 프론트엔드는 `avg_trade_amount` 사용 중. `total_trade_amount` 하위 호환 필드 제거 가능.
- **수정 파일**: `sector_data_provider.py` L225 (`"total_trade_amount": sc.avg_trade_amount,  # 하위 호환` 제거)
- **검증**: pytest + ruff + 런타임 기동 + 프론트엔드 빌드

### 2순위: `test_settings_file_integration.py` `sector_weights` 테스트 데이터 정리 — 승인 대기
- **상태**: Phase 3-B 범위 제외. `sector_weights`를 JSON save/load 테스트 데이터로 사용 중 (L101/106/107/178/182). 제거된 키 사용으로 P23 관점에서 정리 권장.
- **검증**: pytest + ruff

### 3순위: 아키텍처 전수 점검 P1 세션 (B-10)
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
