# SectorFlow Handover

## 직전 완료 작업 (최근 2건)
- **2026-07-22 (최근)**: 실전모드 dead code 정리 — `*_real` 키 + `AccountProvider` 계층 전체 제거 (P16/P24). **수정 파일 11개** (백엔드 8파일 + 테스트 5파일): (1) `engine_settings.py` — `_pick_real_or_legacy`/`_pick_account_no`/`_pick_kiwoom_cred` 함수 제거, `_pick_broker_credentials` 단순화 (real 키 우선 로직 + `_real` 키 결과 저장 제거), `_normalize_broker_config`에서 `"account"` 키 제거. (2) `kiwoom_providers.py` — `KiwoomAuthProvider`에서 `kiwoom_app_key_real`/`kiwoom_app_secret_real`/`kiwoom_account_no_real` 우선 로직 제거 (단일 키 직접 사용), `KiwoomAccountProvider` 클래스 전체 제거 (호출처 0건), 미사용 import 제거 (`AccountProvider`/`asyncio`). (3) `kiwoom_connector.py` — `create_kiwoom_connector`에서 real 키 우선 로직 제거. (4) `broker_registry.py` — `KiwoomAccountProvider`/`LsAccountProvider` import 및 등록 제거, `MUST_SAME_BROKER_PAIRS` 빈 리스트로 변경. (5) `broker_router.py` — `FEATURES`에서 `"account"` 제거, `PAGE_FEATURES`에서 `"account"` 페이지 제거, `account` 프로퍼티 제거, `AccountProvider` import 제거. (6) `ls_providers.py` — `LsAccountProvider` 클래스 전체 제거, `AccountProvider` import 제거. (7) `broker_providers.py` — `AccountProvider` ABC 클래스 전체 제거. (8) `kiwoom_account_parsing.py` — docstring에서 `KiwoomAccountProvider` 참조 제거. 테스트: `test_engine_settings.py`(real 키 테스트 5개 제거/갱신), `test_kiwoom_providers.py`(real 키 테스트 2개 제거 + `TestKiwoomAccountProvider`/`TestKiwoomAccountProviderGetAccountBalance` 전체 제거), `test_kiwoom_connector.py`(real 키 테스트 1개 제거), `test_ls_providers.py`(`TestLsAccountProvider`/`TestGetAccountBalance` 전체 제거), `test_broker_router.py`(account 관련 테스트 갱신/제거). **근본 원인**: `*_real` 키(kiwoom_app_key_real 등)가 UI에서 설정 불가, DB에 저장되지 않으므로 항상 None — dead code. `KiwoomAccountProvider`/`LsAccountProvider`는 `get_router().account` 호출처 0건 — engine_account.py가 REST API 직접 사용. **해결**: 모든 `*_real` 키 참조 제거 → 단일 키(`kiwoom_account_no` 등)만 유지, `AccountProvider` 계층 전체 제거 (ABC + 구현체 + 등록 + 라우터 기능). **검증**: pytest 2783개 통과 (0 실패, 회귀 없음) + py_compile OK + 부트 검증 (FEATURES/MUST_SAME_BROKER_PAIRS/real 키 부재/AccountProvider import 부재 확인) + FastAPI 앱 임포트 정상 (37 라우트). **UI에서 달라지는 점**: 없음 — 화면 변화 없는 코드 정리. **다음 세션**: 별도 예정 없음 — 사용자 지시 대기.
- **2026-07-22 (이전)**: 매수 간격 타이머 문제 근본 수정 — `are_buy_targets_changed` 사용처 분리 + snapshot rank 추가 (P11/P23). **수정 파일 4개** (백엔드 2파일 + 테스트 2파일): (1) `backend/app/services/engine_sector_confirm.py` — `are_buy_targets_changed` 사용처 2곳(증분 재계산 L187-192 / 전체 재계산 L248-252) 분리. 구독 갱신(`sync_dynamic_subscriptions`)은 guard_pass 집합 변동 시만 호출(현행 유지), 매수 시도(`evaluate_buy_candidates`)는 `are_buy_targets_changed`와 분리하여 업종 점수/순위 변동 시 항상 호출. (2) `backend/app/services/buy_order_executor.py` — `_last_global_snapshot` dict에 `ranks` 튜플(`(code, rank)` 쌍) 추가. 매수 후보 순서 변동 시 snapshot 불일치 → 매수 기회 재평가. (3) `backend/tests/test_buy_order_executor.py` — `test_same_buyable_codes_different_order_skips` → `test_same_buyable_codes_different_order_retries`로 변경 (정렬 순서만 바뀌어도 재시도, await_count 0→2). (4) `backend/tests/test_engine_sector_confirm.py` — `test_prev_cache_targets_unchanged_skips_sync` 기대값 변경 (evaluate_buy_candidates 호출됨, `assert_not_called` → `assert_called_once`). **근본 원인**: 매수 1건 성공 후 30초가 지나도 다음 매수가 시도되지 않음. (1) `are_buy_targets_changed`가 guard_pass 종목코드 집합 변동 시만 True → 업종 점수/순위가 변해도 False → `evaluate_buy_candidates` 호출 안 됨. (2) `_last_global_snapshot`에 rank 미포함 → 매수 후보 순서가 변해도 snapshot 일치 → `evaluate_buy_candidates` 내부에서 return. **해결**: 매수 시도를 구독 갱신에서 분리하여 업종 점수/순위 변동 시 항상 `evaluate_buy_candidates` 호출 → `check_order_interval("buy")`가 30초 경과 확인 → 통과 시 매수 시도. 타이머(`call_later`) 없이 순수 이벤트 체인 유지 (틱 → 업종 재계산 → 점수 변동 → evaluate_buy_candidates → check_order_interval 간격 판정). 매도는 이미 틱 기반으로 정상 동작하므로 수정 불필요. **검증**: pytest 2839개 통과 (0 실패, 회귀 없음) + py_compile OK + 임포트 검증 (RuntimeWarning 없음) + FastAPI 앱 임포트 정상 (37 라우트) + 잔존 프로세스 0건. **UI에서 달라지는 점**: "매수 주문 간격 30초" 설정 시 매수 1건 → 30초 대기 → 업종 점수 변동이 발생하는 다음 틱에서 다음 매수 1건 시도 (이전: 30초가 지나도 업종 점수만 변하고 guard_pass 집합이 같으면 매수 시도 안 됨). **다음 세션**: 별도 예정 없음 — 사용자 지시 대기.

## 현재 상태 (빌드/테스트 스냅샷)
- **백엔드**: pytest 2783 passed / 0 failed
- **런타임**: `python -W error::RuntimeWarning main.py` 기동 성공, RuntimeWarning 0건
- **프론트엔드**: `npm run build` 성공 (snapshot_history 계열 dead code 제거 반영)
- **문서**: `docs/architecture_audit_tasks.md` — 아키텍처 전수 조사 실행 추적용 태스크 파일. B-22 + B-23 완료 반영. 다음 세션부터 B-10-b 착수 가능.

## 다음 세션 진행 대기

### 아키텍처 위반 전수 조사 (다단계 작업 — 진행 중)
- **현재 단계**: B-22 + B-23 완료 → 다음 세션 B-10-b 착수 가능
- **기준 문서**: `ARCHITECTURE.md` (24개 불변 원칙) + `docs/architecture_audit_plan.md` (30세션 분할 계획 + 과거 해결 이력) + `docs/architecture_audit_tasks.md` (실행 추적용 체크리스트)
- **진행 현황**: 30세션 중 19세션 완료 (B-01~B-14, B-16~B-23, F-01) + 3세션 부분 완료 (B-10-a/B-14-a/B-15-a) + 8세션 잔여 (B-10-b, B-13, B-14-b, B-15-b, F-02~F-07)
- **다음 세션 추천**: **B-10-b (P1 — 엔진 계좌/서비스 잔여 6건)** — B-10-a 완료 후 잔여 위반 6건. 조사 체크리스트 + 검증 단계는 태스크 파일 섹션 "세션 B-10" 참조.
- **이후 세션 순서**: B-10-b → B-13 → B-14-b → B-15-b → F-02 → F-03 → F-04-a/b (분할) → F-05 → F-06-a/b (분할) → F-07
- **세션 진행 규칙**: 각 세션은 AGENTS.md 규칙 0-1(세션당 1단계) 준수 — 한 세션에서 1세션만 진행 후 검증·커밋·HANDOVER 갱신·사용자 보고 후 종료. 다음 세션은 다음 기회에 이어서.
- **분할 권장 세션**: F-04 (3145줄), F-06 (6803줄) — 각 a/b 서브세션 분할 권장 (태스크 파일에 분할 제안 명시)
- **위반 사항 기록**: 각 세션에서 위반 발견 시 `architecture_audit_plan.md` 섹션 7 "발견된 문제 기록"에 ID 부여 기록 (예: `B10-01`). 심각도(CRITICAL/HIGH/MEDIUM/LOW)·상태(발견/수정중/해결/보류) 분류는 태스크 파일 섹션 5 참조.
- **완료 정의** (태스크 파일 섹션 6 = plan 섹션 9): 30세션 모두 완료 + 모든 CRITICAL/HIGH 해결 + 24개 원칙 위반 0건 + 백엔드 런타임 기동 검증 + 프론트엔드 빌드 + pytest 전체 통과

### 리스크 매니저 확장 (다단계 작업 진행 중)
- **현재 단계**: 1세션 (설계) + 2세션 (태스크 파일) + 3세션 (구현 Step 1 — 백엔드 설정 계층 + 사유코드) 완료 → 4세션 (구현 Step 2 — RiskManager 확장) 승인 대기
- **참조 문서**: `docs/architecture_risk_manager_extension_design.md` (862줄, 설계 완료) + `docs/plan_risk_manager_extension.md` (605줄, 태스크 완료)
- **사전조사 발견 오류 3건** (태스크 파일 0절): (1) `test_risk_manager.py` 이미 존재 — "신규" → "기존 확장", (2) UI 칩 색상 `COLOR.downBg`(파랑) → `COLOR.upBg`(빨강) 수정 제안, (3) `check_sell_order_allowed` async 변환 시 기존 테스트 3개 갱신 필요
- **다음 세션**: 4세션 구현 Step 2 — RiskManager 확장 + 매도 체크 async 변환 + WS 브로드캐스트 (2파일: `risk_manager.py`, `trading.py` 매도 체크 부분 + 테스트 2파일: `test_risk_manager.py` 기존 확장, `test_trading.py` 매도 체크 갱신). 핵심 로직 변경 (규칙 0-4 + 0-5 적용 — 사용자 승인 필수).
- **이후 세션들**: 5세션(프론트엔드 5파일) → 6세션(통합 검증 + 문서 갱신 + 계획서 삭제) — 각 세션당 1단계 원칙 준수

### 일일 손실 한도 개선 (다단계 작업 진행 중 — 3단계)
- **현재 단계**: 1단계(`createMoneyInput` 음수 지원) + 2단계(백엔드 `daily_loss_limit_on` 키 추가) 완료 → 3단계(프론트엔드 토글 + `createMoneyInput` 교체) 대기
- **1단계 완료**: `frontend/src/components/common/setting-row.ts` — `createMoneyInput`에 `min`/`max` 옵션 추가 + `fmtMoney()` 헬퍼로 음수 콤마 포맷. 기존 양수 사용처 영향 없음.
- **2단계 완료**: 백엔드 3파일(`settings_defaults.py`, `engine_settings.py`, `risk_manager.py`) + 프론트엔드 타입 1파일(`types/index.ts`) + 테스트 2파일. `daily_loss_limit_on` 기본값 True로 기존 동작 유지. OFF 시 매수/매도 손실 한도 체크 스킵.
- **3단계 대기 (다음 세션)**: `frontend/src/pages/general-settings.ts` — 일일 손실 한도 행(524-539줄)을 `createToggleLabelControlsRow` + `createMoneyInput`(음수, `min: -1000000000, max: 0`)으로 교체. `dailyLossToggle`/`dailyLossControls` 변수 추가(60줄 근처). 다른 리스크 설정(손실률/수익/수익률/연속손실)과 동일 패턴(P23 일관성).

### 기타 대기 항목
- **TOCTOU 데이터 정정 2건 (별도 승인 필요)**: 2026-07-22 `_ensure_loaded()` TOCTOU 경쟁 상태 코드 수정 완료. 잔여 데이터 정정 2건 — (1) `settlement_state.orderable` 유령 매도 대금 포함 정정, (2) `trades` 테이블 매도 3건 qty 2배 정정. 실제 데이터를 건드리는 작업이므로 사용자 승인 필수.
- **NXT 메인마켓 미갱신 (09:00:30)**: 2026-07-22 조사 중 발견. `calc_timebased_market_phase()`가 09:00:30에 NXT="메인마켓" 산정하나, 09:00:30에 `_broadcast_market_phase()`를 호출할 타임테이블 이벤트 없음 → NXT 페이즈가 재기동 전까지 "정규장 준비"로 고정 (카운트다운 표시 영향). 주문 중단 칩과는 무관 (KRX 활성 상태에서 주문 허용). 별도 세션에서 09:00:30 타임테이블 이벤트 추가 또는 주기적 브로드캐스트 검토 필요.
- **다운로드 완료 시간 표시 (제안2)**: 1일봉/5일봉 다운로드 버튼 우측에 최근 다운로드 완료 시간 표시. 백엔드 신규 기능 필요 (저장소 설계 사전조사 후 제안).
- **실전모드 보관 기준** (`RETENTION_TRADING_DAYS_REAL = 90`): 추후 논의.
- **`notify_raw_real_data` dead code (P16)**: 별도 검토 필요 시 사용자 지시.
- **추가 컬럼 너비 조정**: 사용자 UI 확인 후 필요 시 해당 페이지만 override로 진행.
- **`sector_calculator.py:132` 코드 주석-코드 불일치 (P10/P23)**: 2026-07-18 ARCHITECTURE.md 6.2절 불일치 수정 세션 중 발견. 주석 "순위/백분위 기반 점수이므로 불필요" → 실제 2차 가산점은 "가중 순위 합" 방식 (백분위 미사용). 사용자가 "문서만 수정, 코드 변경 없음" 명시하여 코드 주석은 수정 안 함. 사용자 승인 시 별도 세션에서 코드 주석 1줄 갱신 권장.
- **`kiwoom_rest.py` `except Exception as e:` 8곳 `exc_info=True` 누락 (P23)**: 2026-07-21 B-15-b 세션 중 발견. `kiwoom_connector.py`(12/12 보유)와 일관성 위반. B-15-a 세션에서 누락됨 (B15-03/B15-04는 `kiwoom_connector.py`에만 적용). 별도 세션에서 8곳에 `exc_info=True` 추가 권장.
- **`auth.py:30` `verify_token` dead code (P16)**: 2026-07-22 B-22-b 세션 중 발견. B-22-b에서 deps.py/ws.py의 주석 처리된 `verify_token` 호출 코드를 제거하면서 `verify_token` 함수 자체의 호출처가 0건이 됨 (auth.py:30 정의만 남음). `create_access_token`/`authenticate_user`는 살아있는 경로 (routes/auth.py에서 호출). 별도 세션에서 `verify_token` 함수 제거 또는 프로덕션 전환 시 재활성화 검토 필요.
- **`sector_data_provider.py:154`·`sector_calculator.py:28/169` `get_merged_sector` 참조 주석 (P23)**: 2026-07-22 B-22-b 세션 중 발견. B-21-c에서 `get_merged_sector` 함수 제거되었으나 3곳의 주석/docstring이 여전히 해당 함수 참조. 별도 세션에서 주석 정정 권장 (Code Removal Rules 준수).

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
- `sector-ranking-list.ts`는 `createDataTable` 기반으로 전환 완료 (CSS Grid + 가상 스크롤 + rowFooter 진행 바). `profit-overview.ts`는 여전히 `DataTable`이 아니므로 별도 처리 필요 시 별도 세션 진행.
- 컬럼 너비 공통 상수(`COLUMN_WIDTH`)는 min/max px 경계값이며, 실제 비율은 데이터 기반 px→% 정규화로 페이지별 컬럼 구성에 자동 적응함. per-page override는 `ColumnDef`의 `minWidth`/`maxWidth` 필드로 이미 지원.
