# SectorFlow Handover

## 세션 개요
- 날짜: 2026-07-17 (계좌 잔액 검증 테스트 태스크 파일 작성 — 다단계 작업 2세션, P10/P16/P20/P22/P24)
- 작업: 다단계 작업 워크플로우 2세션(심층 사전조사 + 태스크 파일 작성) — 1세션 디자인 파일 기반으로 심층 사전조사(settlement_engine 전역 변수 격리/stock_tables DB 연결 주입/_broadcast_delta 패치 위치/_insert_trade 직접 호출) → 기존 공통 자산 확인(test_dry_run.py/test_dry_run_fill_event.py 패턴 재사용) → 태스크 파일 작성 완료.
- 상태: 계좌 잔액 검증 테스트 태스크 파일 작성(2세션) 완료. 3세션(구현) 승인 대기.
- **참조 규칙**: AGENTS.md 섹션4 "다단계 작업 워크플로우 (설계 → 태스크 → 구현)"
- **참조 문서**: `backend/docs/settlement_verification_design.md` (디자인 파일) + `docs/plan_settlement_verification.md` (태스크 파일)

## 직전 완료 작업
- **계좌 잔액 검증 테스트 태스크 파일 작성 (다단계 2세션)**: 코드 수정 없음 (심층 사전조사 + 태스크 파일 작성만)
  - 심층 사전조사: settlement_engine 모듈 전역 변수 격리 방식(`_loaded=True` + 변수 직접 할당, 기존 test_dry_run.py 패턴) / stock_tables DB 연결 주입 방식(`save_settlement_state`가 db_writer 큐 경유 → 테스트 환경 무한 대기 → `_persist` no-op 패치) / `_broadcast_delta` 패치 위치(테스트 파일 내 fixture, conftest 아님) / `trade_history._insert_trade` 직접 호출 가능(DB 저장은 execute_db_write 패치 필요).
  - 기존 공통 자산 확인(P23): `_noop_async` 헬퍼 / `_setup_dry_run_env` fixture 패턴 / `_do_buy`/`_do_sell` 헬퍼 / conftest.py 전역 캐시 초기화 — 모두 기존 자산 재사용, 신규 패턴 생성 없음.
  - 태스크 파일 278줄 작성: 심층 사전조사 결과(의존성/영향범위/원칙부합/공통자산) + 구현 상세(S1~S6 시나리오별 + fixture 상세) + 세션 분할(3세션 단일 구현) + 검증 계획 + 사용자 결정 항목(S6 포함 여부) + 아키텍처 원칙 검토.
- **계좌 잔액 검증 테스트 설계 (다단계 1세션, 이전 세션)**: 사전조사 + 디자인 파일 366줄 작성. 근본 원인 후보 3개 식별(A/B/C). 디자인 파일: `backend/docs/settlement_verification_design.md`
- **카운트다운 SSOT 통합 검증 + 계획서 삭제 (이전 세션, 커밋 `9a2af87`)**: pytest 2789개 통과 + `npm run build` 성공 + 런타임 기동 RuntimeWarning 0건 + 계획서 파일 2개 삭제. 카운트다운 SSOT 다단계 작업 완전 완료.

## 다음 세션 진행 대기: 계좌 잔액 검증 테스트 (다단계 작업 — 설계→태스크→구현)

### 단계 진행 상황
- **1세션 (완료)**: 설계 검토 + 디자인 파일 작성 — 사전조사(settlement_engine/dry_run/trade_history 소스 추적 + DB 실제 값 확인) → 근본 원인 후보 3개 식별(A/B/C) → 사용자 요구사항 3건 확인 → 디자인 파일 작성. 디자인 파일: `backend/docs/settlement_verification_design.md`
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성 — 디자인 파일 기반으로 심층 사전조사(규칙 0-2 4항목 + 디자인 섹션 7 항목) → 기존 공통 자산 확인 → 세션 분할 + 태스크 파일 작성. 태스크 파일: `docs/plan_settlement_verification.md`
- **3세션 (승인 대기)**: 구현 — `backend/tests/test_settlement_verification.py` 신규 작성 (S1~S6 테스트 함수 7개 + fixture + 헬퍼, ~300줄). **S6(실제 DB 재현) 포함 확정** — 원본 DB 읽기 전용 복사본 사용. 검증: pytest + 기존 회귀 + ruff + py_compile.

### 참조 문서
- **디자인 파일**: `backend/docs/settlement_verification_design.md` (검증 테스트 방식 + 시나리오 S1~S6 + 의심 경로 검증 + P10/P16/P20/P22/P24 원칙 검토 + 회귀 테스트 기반 구축)
- **태스크 파일**: `docs/plan_settlement_verification.md` (심층 사전조사 결과 + 구현 상세 + 세션 분할 + 검증 계획 + 사용자 결정 항목)

### 승인 대기 항목
- **3세션(구현) 진행 승인**: 태스크 파일에 대한 사용자 승인 후 3세션 진행. 승인 전 다음 세션 진행 금지(규칙 0).
- **S6(실제 DB 재현) 포함 여부**: **확정 — 포함** (사용자 결정 2026-07-17). 원본 DB는 읽기 전용 복사본으로 보호.

## 이전 세션 완료 작업 (커밋 완료)
- 3단계: 백엔드 수신률 KRX/NXT 분리 집계 + 임계값 게이트 옵션 C (8개 파일) — 구현 + 검증 + 커밋 완료.
- 분리 작업 자체는 구독 로직 미변경 확인 (git diff 확정). 본 문제와 무관.

## 완료된 다단계 작업: 카운트다운 SSOT 구현 (안 3 — 백엔드 카운트다운 SSOT) ✅

### 단계 진행 상황
- **1세션 (완료)**: 설계 검토 + 디자인 파일 작성 — 3안 비교(안 1 JIF 카운트다운 코드 처리 / 안 2 현상 유지 / 안 3 백엔드 카운트다운 SSOT) → 안 3 추천 → 사용자 안 3 확정. 디자인 파일: `backend/docs/architecture_countdown_supplement_design.md` (삭제됨)
- **2세션 (완료)**: 심층 사전조사 + 태스크 파일 작성 — WS 메시지 흐름 파악 + 기존 시간표 상수 재사용 확인 + 구현 상세 + 세션 분할 + 테스트 계획. 태스크 파일: `docs/plan_countdown_supplement.md` (삭제됨)
- **3세션 (Step 1, 완료, 커밋 `9bd99ef`)**: 백엔드 구현 + 테스트 — `calc_countdown()` 신규 + 상수 3개 + `get_market_phase()` 필드 추가 + 테스트 9개. 검증 통과 (py_compile + ruff + pytest 167개 + 런타임 기동 RuntimeWarning 없음 + 잔존 프로세스 0건).
- **4세션 (Step 2, 완료, 커밋 `bf992fb`)**: 프론트엔드 구현 + 빌드 — 4개 파일 수정 (34 insertions, 44 deletions). `types/index.ts`/`uiStore.ts`/`binding.ts` 타입 정의에 countdown 필드 추가 + `header.ts`에서 `KRX_COUNTDOWN`/`NXT_COUNTDOWN`/`COUNTDOWN_THRESHOLD_MIN`/`computeCountdown()` 제거 + `formatCountdown()` 신규 + 호출부 2곳 수정 + 30초 setInterval 유지(수신값 재적용). 검증 통과 (`npm run build` 성공 + 잔존 참조 0건).
- **5세션 (Step 3, 완료, 커밋 대기)**: 통합 검증 + 계획서 삭제 — pytest 2789개 통과 + `npm run build` 성공 + 런타임 기동 RuntimeWarning 0건 + WS market-phase 메시지 `krx_countdown`/`nxt_countdown` 필드 존재 확인 + 잔존 프로세스 0건 + 계획서 파일 2개 삭제. 상세는 "직전 완료 작업" 섹션 참조.

### 참조 문서
- 디자인 파일·태스크 파일: 구현 완료 후 삭제됨 (규칙: 계획서 삭제). 설계/구현 상세는 git history(`9bd99ef`/`bf992fb`) 참조.

### 차기 권장 (별도 세션)
- **장 시간대 브라우저 카운트다운 칩 확인**: 카운트다운 대상 페이즈 진입 시점(08:50, 15:10, 19:50 등)에 백엔드+프론트엔드 기동 후 헤더 카운트다운 칩 실시간 표시 확인. 현재 시각(휴장일 새벽)은 확인 불가.

---

## 이전 세션 진행 대기: 장 상태 관리 안 D 구현 (하이브리드 — JIF + 주기적 계산)

### 단계 진행 상황
- **1단계** (완료): JIF jstatus 코드 맵핑 사전 검증 — LS증권 API 스펙 문서 조회. 결과는 2단계 태스크 파일에 통합.
- **2단계** (완료, 커밋 `b54edca`): JIF 핸들러 확장 (`_handle_jif()` 장 상태 전환 처리 추가) + `_apply_market_phase()` 분리 + 테스트 11개. 구현 + 검증 + 커밋 완료.
  - **태스크 파일**: `docs/plan_session_state_jif_handler.md`
  - **런타임 JIF 검증 대기 (장 시간대 별도 진행)**: 임시 INFO 로그(`[연결] JIF 수신: jangubun=%s, jstatus=%s`)로 장 시작 시점(08:00~09:00, 15:20~15:40, 20:00) 실제 push 코드 확인 필요. **현재 장 마감 시간이라 런타임 JIF 검증 불가 — 다음 장 시간대에 별도 진행**. 맵핑 테이블과 불일치 시 3단계 진행 전 맵 수정.
- **3단계** (완료, 커밋 `6533a79`): 주기 태스크 추가 + 11개 타이머 제거 + 주기적 시간 계산으로 전환 + 테스트 8개 추가. 구현 + 검증 + 커밋 완료.
  - **태스크 파일**: `docs/plan_session_state_periodic_task.md` (11개 타이머 제거 + 10초 간격 주기 태스크 + 기동/종료 연결 + 테스트 계획 + 런타임 검증 방법)
  - **수정 범위**: 3개 파일 — `daily_time_scheduler.py` (타이머 제거 + 주기 태스크), `engine_state.py` (핸들 필드), `test_daily_time_scheduler.py` (테스트 수정 3개 + 신규 8개)
- **4단계** (태스크 파일 작성 완료, **구현 승인 대기**): WS/NXT 시간 조정 — 07:59 WS 구독 사전 트리거 + 07:58 실시간 필드 초기화 분리 + NXT 09:00:30 초 단위 예외.
  - **태스크 파일**: `docs/plan_session_state_phase_timing.md` (WS 07:59 사전 트리거 + 필드 초기화 07:58 분리 + NXT 09:00:30 초 단위 예외 + 멱등성 가드 + 보완 경로 + 테스트 계획 + 런타임 검증 방법)
  - **사용자 결정 사항 4건**: WS 구독 "phase 08:00 유지 + WS만 07:59", 필드 초기화 "07:58 단독 트리거", NXT "NXT만 초 단위 예외", jstatus 52 문구 "4단계에서 제외 (별도 세션)"
  - **수정 범위 예정**: 3개 파일 — `daily_time_scheduler.py` (상수 3개 + calc NXT 예외 + `_on_realtime_fields_reset()` 신규 + `_on_ws_subscribe_start()` 수정 + `_check_prestart_triggers()` 신규 + `_market_phase_periodic_loop()` 수정 + `_init_ws_subscribe_state()` 수정), `engine_state.py` (필드 2개), `engine_cache.py` (플래그 동기화 1줄) + `test_daily_time_scheduler.py` (기존 수정 + 신규 3 클래스)
  - **jstatus 52 표시 문구 수정**: 본 4단계에서 제외 (사용자 결정 — 별도 세션에서 P23 용어 통일 검토 포함 진행)
  - **4단계 사전 검토 항목 (계획서에 없음 — 구현 시 함께 검토)**:
    1. **일반 설정 페이지 > API 설정 탭 "실시간 연결 토글" 제거 검토**: 사용자 판단 — 불필요한 토글, 제거하는 것이 깔끔함. NXT 구독은 항상 07:59에 자동으로 이루어져야 함 (수동 토글 불필요). 4단계 구현 시 `ws_subscribe_on` 설정 키 + UI 토글 제거 범위 조사 후 승인받아 진행.
    2. **NXT 종목 구독 신청 시간 07:59 고정값 확정**: 설정에서 변경할 필요 없이 고정값 처리. 4단계 상수 `WS_SUBSCRIBE_PRESTART_TIME = (7, 59)`와 연계 — 설정 기반 가변 시각이 아닌 고정 상수로 확정.

### 참조 문서
- **설계 검토**: `backend/docs/architecture_session_state_design.md` (4안 비교표 + 안 D 동작 원리 + 표준 검토 근거)
- **2단계 구현 계획**: `docs/plan_session_state_jif_handler.md`
- **3단계 구현 계획**: `docs/plan_session_state_periodic_task.md`
- **4단계 구현 계획**: `docs/plan_session_state_phase_timing.md`

### 승인 대기 항목
- **런타임 JIF 검증**: 장 시작 시점(08:00~09:00, 15:20~15:40, 20:00)에 임시 INFO 로그로 실제 push되는 jstatus 코드 확인 → 맵핑 테이블 검증. 검증 후 INFO→DEBUG 조정.
- **4단계 런타임 통합 검증**: 장 시간대에 JIF push + 주기 태스크 실제 동작 확인 (페이즈 전환 시 `[장상태]` 로그 + 10초 간격 동작).
- **4단계 사전 검토 — 실시간 연결 토글 제거**: 일반 설정 페이지 > API 설정 탭의 "실시간 연결 토글" 제거 검토 (사용자 판단: 불필요, NXT 구독은 항상 07:59 자동). 4단계 구현 시 조사 후 승인.
- **4단계 사전 검토 — NXT 구독 시간 07:59 고정**: NXT 종목 구독 신청 시간을 설정 가변이 아닌 07:59 고정값으로 확정.
- NXT 09:00:30 수정 포함 여부 (3단계에서 제외 — 별도 검토, JIF 1순위가 보완).
- WS 07:55/07:59 조정 포함 여부 (3단계에서 제외 — 별도 검토).

---

## 이전 세션 진행 대기: KRX 수신률 미표시 문제 추가 조사 (타이머 미실행 근본 원인)

### 문제 개요 (사용자 보고)
- **현상**: 앱을 NXT 프리마켓 08:00 이전에 기동한 후, 10:50경 확인하니 NXT 수신률만 표시되어 있고 KRX 수신률 표시가 없었음.
- **기대 동작**: 09:00 정규장 시작 후 KRX 수신률도 표시되어야 함.

### 3차 조사 핵심 발견 (이번 세션)
- **08:00 타이머도 미실행** (사실 11): 08:29:59에 실행된 "NXT 프리마켓 진입 (08:00)" 로그는 08:30 타이머가 대신 실행된 것. 08:00~08:30 28분 공백도 이로 설명됨.
- **08:30 타이머 정상 실행** (사실 11): 같은 이벤트 루프에서 08:30 타이머는 정상 실행됨.
- **자동매매 타이머 정상 실행** (사실 12): 08:01:59에 자동매매 시간 전환 타이머 정상 실행. 같은 루프에서 일부만 실패.
- **15분 로그 공백 = 자연스러운 현상** (사실 13): 08:50 이후 양 시장 비거래 구간이라 틱 없음. 이벤트 루프 블록 아님.
- **타이머 예약 로그 DEBUG 레벨** (사실 14): INFO 로그에 타이머 예약/실행 추적 정보가 전혀 남지 않음. 원인 특정의 주요 장애물.
- **07:50~09:00 설정 변경 없음** (사실 15): PATCH 0건, `schedule_ws_subscribe_timers()`는 기동 시 1회만 호출.
- **타이머 핸들 리스트 교체/손실 경로 없음** (사실 16): 코드상 `.clear()`, `.append()`만 사용, 리스트 객체 교체 경로 없음.

### 배제된 가능성 (3차 조사)
- 이벤트 루프 전체 블록 — 아님 (자동매매 타이머 정상 실행)
- 타이머 핸들 리스트 교체/손실 — 코드상 경로 없음
- 설정 변경에 의한 타이머 재예약 — 07:50~09:00 사이 설정 변경 없음
- 15분 로그 공백 = 이벤트 루프 블록 — 아님 (비거래 구간 정상)

### 여전히 남은 가능성 (3차 조사)
- `schedule_ws_subscribe_timers()` 재호출 (DEBUG 로그로 추적 불가) — 재호출 시 `delay_mp <= 0`인 타이머가 재예약되지 않아 08:00/09:00 미실행 가능. 하지만 재호출 트리거 코드 경로 미발견.
- asyncio `call_later` 타이머 관리 이슈 (macOS/Python 3.12) — 08:30 정상 실행이므로 단순 플랫폼 버그 단정 어려움.

### 다음 세션 조사 방향 (조사 보고서 기준 — 상세는 `docs/krx_receive_rate_missing_investigation.md` 참조)
1. **DEBUG → INFO 로그 승격 먼저 적용** (⭐⭐⭐ 최우선 전제 작업): 타이머 예약/실행/재호출 추적 가능하도록 로그 승격. 근본 원인 추적의 전제 조건.
2. **08:00, 09:00 타이머만 실패한 근본 원인 추적** (⭐⭐⭐ 최고 중요도, P10/P16 핵심): INFO 승격 후 재발 시 추적.
3. **`schedule_ws_subscribe_timers()` 재호출 경로 전수 추적** (⭐⭐⭐ 최고 중요도): 현재 코드상 재호출 트리거 미발견 — INFO 승격 후 런타임 추적 필요.
4. **타이머 통합(aba9e92) 이전/이후 비교** (⭐ 보통): 과거 09:00 전용 타이머 vs 현재 market_phase 타이머 의존 구조 신뢰성 비교, 회귀 여부 최종 확인.
5. **JIF 폴백 경로 활용 가능성** (⭐ 보통): JIF 이벤트를 market_phase 갱신 폴백으로 활용 가능성 검토 (수정 방안 수립 시).

### 이번 세션 조사로 확정된 사실 (상세는 조사 보고서 참조)
- 09:00 `_on_krx_market_open()` 미호출 확정 (로그 부재)
- `state.market_phase["krx"]` 미갱신 확정 (타이머 미실행)
- `is_nxt_only_window()` True 유지 확정 → KRX 수신률 0/0 고정
- 틱은 정상 수신 중 확정 (09:07 매매 발생)
- 분리 작업(1·2·3단계) 자체는 구독 로직 미변경 확정 (git diff)
- JIF 핸들러는 market_phase 갱신 안 함 확정 (폴백 경로 부재 = P16 위반)
- **08:00 타이머도 미실행 확정** (08:30 타이머가 대신 처리)
- **08:30 타이머 정상 실행 확정** (같은 루프에서 일부만 실패)
- **자동매매 타이머 정상 실행 확정** (같은 루프에서 다른 타이머 시스템은 정상)
- **15분 로그 공백 = 자연스러운 현상 확정** (비거래 구간, 이벤트 루프 블록 아님)
- **타이머 예약 로그 DEBUG 레벨 = 추적 불가 확정** (INFO 승격 필요)
- **07:50~09:00 설정 변경 없음 확정** (PATCH 0건)
- **타이머 핸들 리스트 교체/손실 경로 없음 확정** (코드상)

### 관련 파일
- `backend/app/pipelines/pipeline_compute.py` — `_handle_real_01_tick()` (dirty 세팅), `_sector_recompute_loop_impl()` Phase 2 (수신율 갱신 로그), `_calculate_receive_rate()` (분리 계산)
- `backend/app/services/sector_data_provider.py` — `get_sector_summary_inputs()` (krx_codes/nxt_codes 분리 반환, is_nxt_only_window 분기)
- `backend/app/services/daily_time_scheduler.py` — `is_nxt_only_window()` (market_phase 기반 판단)
- `backend/logs/trading_2026-07-16.log` — 08:30~10:52 구간 로그

### 계획서 경로
- **`docs/plan_krx_nxt_receive_rate_separation.md`** — 3단계 구현 계획서 (사전조사 결과 + 단계별 파일 목록 + 검증 방법 + 사용자 승인 항목)

### 사용자 승인 완료 항목 (이전 세션)
- **7-1 임계값 게이트 정책 (3단계)**: 옵션 C(시간대별 분기) 승인 — NXT-only 구간은 NXT 수신률만 기준, 정규장은 KRX/NXT 양쪽 모두 임계값 도달 시(AND).
- **7-2 진행 방식**: 분리 진행 (규칙 0-1 준수) 승인.
- **7-3 1단계 시작**: 승인 → 1단계 완료됨.

### 핵심 발견 (사전조사 결과 — 3단계 구현 시 참고)
1. **수신률 단일 집계**: `_received_codes: set[str]` 단일 세트로 KRX/NXT 구분 없이 종목코드만 저장 (pipeline_compute.py:34). 틱 수신 시 FID 9081(KRX='1'/NXT='2') 확인 없이 추가 (line 581). 정규장에서 KRX/NXT 개별 수신 상태를 알 수 없음 (P10/P21 위반).
2. **시간대 SSOT 이미 존재**: `is_nxt_only_window()`, `is_nxt_premarket_window()`, `is_nxt_aftermarket_window()`, `KRX_INACTIVE_PHASES`, `NXT_ACTIVE_PHASES` (daily_time_scheduler.py:46~193) — 새 시간 상수 불필요 (P10/P23).
3. **FID 9081 파서 존재**: `parse_fid9081_exchange()` (engine_ws_parsing.py:181) — '1'=KRX, '2'=NXT, ''=미수신. 단, `_AL` 통합 구독 시 빈 문자열 케이스 가능성 → 3단계 구현 전 실제 틱 로그 확인 권장.
4. **progress-bar.ts 2인스턴스 가능**: `createProgressBar()` 인터페이스로 독립 인스턴스 2개 생성 가능, 개별 `setValue`/`setThreshold` 호출 가능.
5. **임계값 게이트 핵심 로직**: `_sector_threshold_passed` (pipeline_compute.py:41) — 단일 수신률 기준. 분리 시 시간대별 분기 정책(옵션 C, 승인됨) 적용.

### 3단계 구현 계획 (계획서 섹션 3)
- **1단계 (프론트엔드 공통 컴포넌트 추출)**: ✅ 완료 — sector-stock.ts 인라인 카운트 → `createMarketCountRow` 공통 컴포넌트 추출.
- **2단계 (프론트엔드 수신률 분리 배지)**: ✅ 완료 — sector-settings.ts 수신률 표시 KRX/NXT 분리 배지 + 진행 바 2인스턴스. uiStore.receiveRate 타입 {krx, nxt} 분리. binding.ts 단일 수신률 양쪽 동일 매핑.
- **3단계 (백엔드 수신률 분리 집계 + 임계값 게이트)**: `_received_codes` KRX/NXT 2세트 분리, `_calculate_receive_rate()` 시간대별 분리 계산, `_send_receive_rate()` 전송 구조 변경, 임계값 게이트 시간대별 분기 정책(옵션 C, 승인됨). 테스트 전면 수정. **2단계에서 준비한 {krx, nxt} 구조에 분리 데이터 연동**.

### 승인 대기 상태
- 3단계 시작 승인 대기 — 사용자가 "진행해" 등 실행 지시어를 줄 때까지 코드 수정 금지 (AGENTS.md 섹션3 규칙 0).
- 3단계 임계값 게이트 정책은 이미 옵션 C로 승인됨 — 3단계 시작 시 재승인 불필요 (단, 3단계 시작 자체는 별도 승인 필요).
- 3단계는 백엔드 핵심 로직 변경(수신률 집계 + 임계값 게이트) — 백엔드 수정 시 safe-trade 스킬 + 테스트 + 런타임 기동 검증 필수.
- **3차 조사 후 승인 대기**: DEBUG → INFO 로그 승격 적용 (타이머 미실행 원인 추적의 전제 작업). 사용자가 "진행해" 등 실행 지시어를 줄 때까지 코드 수정 금지.

---

## 직전 완료 작업 (이번 세션)

### 3차 조사: 09:00 타이머 미실행 근본 원인 심층 추적 (문서 업데이트 only — 코드 수정 없음)

**배경**: 2차 조사까지 09:00 타이머 미실행을 확인했으나 근본 원인 미확인. 3차 조사에서 타이머 미실행 패턴을 심층 추적.

**조사 내용**:
- 08:00 타이머도 미실행 확인 (08:29:59에 08:30 타이머가 대신 실행 → 누적 페이즈 변경 감지)
- 08:30 타이머 정상 실행 확인 (같은 이벤트 루프에서 일부만 실패)
- 자동매매 타이머 정상 실행 확인 (08:01:59, 별도 타이머 시스템)
- 15분 로그 공백(08:45~09:00) = 비거래 구간 정상 현상 확인 (이벤트 루프 블록 아님)
- 타이머 예약 로그 DEBUG 레벨 = 추적 불가 확인 (INFO 승격 필요)
- 07:50~09:00 설정 변경(PATCH) 0건 확인
- 타이머 핸들 리스트 교체/손실 경로 코드상 없음 확인
- `schedule_ws_subscribe_timers()` 재호출 트리거 코드 경로 미발견 (DEBUG 로그로 런타임 추적 불가)

**결과**: 근본 원인 여전히 미확인. 단, 08:00/09:00 타이머만 선택적 미실행 패턴 확정. DEBUG → INFO 로그 승격이 원인 특정의 전제 조건임을 확인.

**수정 내용**: 문서 업데이트 only (코드 수정 없음)
- `docs/krx_receive_rate_missing_investigation.md`: 확인된 사실 10건 → 16건 확장 (사실 11~16 추가), 타임라인 08:00 타이머 미실행/08:02 자동매매 타이머 정상 실행 추가, 미확인 항목 3차 조사 결과로 갱신, 다음 세션 조사 방향 INFO 승격 최우선 반영, 수정 방안 2단계 접근(추적 가능성 + 타이머 의존도 감소)으로 재구성
- `HANDOVER.md`: 세션 개요 3세션으로 갱신, 3차 조사 핵심 발견 + 배제된 가능성 + 남은 가능성 추가, 확정된 사실 7건 → 13건 확장

**다음 세션**: DEBUG → INFO 로그 승격 적용 후 재발 시 근본 원인 추적 (승인 대기).

---

## 직전 완료 작업 (이전 세션)

### 3단계: 백엔드 수신률 KRX/NXT 분리 집계 + 임계값 게이트 옵션 C (8개 파일)

**배경**: KRX/NXT 수신률 분리 집계 + 분리 배지 표시 3단계 구현의 최종 단계. 1·2단계에서 프론트엔드 분리 표시 준비 완료. 3단계에서 백엔드 수신률을 단일 집계에서 KRX/NXT 분리 집계로 변경. **FID 9081 틱 분석 방식 대신 `nxt_enable` 필드 기반 단순 방식 채택** (P10 SSOT, P24 단순성 — 틱 분석 불필요, sector-stock.ts 카운트와 동일 기준).

**수정 내용**:
- **`backend/app/pipelines/pipeline_compute.py`**: `_received_codes` 단일 세트 → `_received_codes_krx`/`_received_codes_nxt` 2세트 분리. 틱 수신 시 `is_nxt_enabled(nk_px)`로 분기 (FID 9081 불필요). `_current_receive_rate` → `{krx: {received, total, pct}, nxt: {received, total, pct}}` 분리 구조. `_calculate_receive_rate()` 시간대별 분리 계산 (NXT-only 구간 krx_codes 빈 리스트 → KRX 0/0, NXT만 산출). `_calc_market_receive_rate()` 헬퍼 추출 (단일 시장 수신률 계산, 함수 50줄 이하 유지). `_send_receive_rate()` 분리 구조 전송. `get_current_receive_rate()` 분리 구조 반환 (깊은 복사). Phase 1 임계값 게이트 옵션 C — `is_nxt_only_window()` 분기: NXT-only 구간 NXT 수신률만 기준, 정규장 KRX/NXT 양쪽 모두 도달 시(AND). Phase 2 로그 KRX/NXT 분리 출력.
- **`backend/app/services/sector_data_provider.py`**: `get_sector_summary_inputs()`에 `krx_codes`/`nxt_codes` 분리 반환 추가 (`nxt_enable` 필드 기반, P10 SSOT). `all_codes`는 기존 업종 점수 계산용 유지. `recompute_sector_summary_now()`에서 `compute_full_sector_summary()` 호출 시 `krx_codes`/`nxt_codes` 제외 (dict comprehension 필터).
- **`backend/app/services/engine_sector_confirm.py`**: `_full_recompute()`에서 `compute_full_sector_summary()` 호출 시 `krx_codes`/`nxt_codes` 제외.
- **`backend/app/services/telegram_bot.py`**: 업종 강도 요약 `compute_full_sector_summary()` 호출 시 `krx_codes`/`nxt_codes` 제외.
- **`frontend/src/binding.ts`**: `receive-rate` 이벤트 분리 구조 매핑 (`{krx, nxt}` → `uiStore.receiveRate`). `sector-scores` 이벤트 `receive_rate` 분리 구조 매핑.
- **`frontend/src/stores/uiStore.ts`**: `applyInitialSnapshotUI` 주석 3단계 상태로 갱신 (분리 구조 자동 처리는 2단계에서 이미 준비됨).
- **`backend/tests/test_pipeline_compute.py`**: `TestReceiveRate`/`TestCalculateReceiveRate`/`TestSectorRecomputeLoopImpl`/`TestSectorThresholdGate` 분리 구조로 전면 수정. NXT-only 구간 임계값 통과 테스트, 정규장 AND 정책 KRX만 통과 시 게이트 유지 테스트 추가.
- **`backend/tests/test_engine_snapshot.py`**: `get_current_receive_rate` mock 반환값 분리 구조로 변경.

**자동 연동 (추가 수정 불필요)**:
- `engine_account_notify.py`: `get_current_receive_rate()` 호출 → 분리 구조 자동 연동. `prev_receive_rate` 비교 Python `==` 중첩 dict 자동 처리. `status.receive_rate` 전송 자동 연동.
- `engine_snapshot.py`: `get_current_receive_rate()` 호출 → `receive_rate` 분리 구조 자동 연동.
- `ws.py`: `get_current_receive_rate()` 호출 → `receive_rate` 분리 구조 자동 연동.
- `market_close_pipeline.py`: `_calculate_receive_rate()`/`_send_receive_rate()`/`get_current_receive_rate()` 호출 → 분리 구조 자동 연동.

**유지 대상 (변경 안 함)**:
- 임계값 게이트 플래그 `_sector_threshold_passed` — 단일 플래그 유지 (시간대별 분기 로직만 추가).
- `is_nxt_tick()`/`parse_fid9081_exchange()` — FID 9081 기반 방식은 채택하지 않음 (`nxt_enable` 방식이 더 단순하고 일관됨).

**검증**: pytest 2746개 전체 통과 + 런타임 기동 (`python -W error::RuntimeWarning main.py`) RuntimeWarning 없음 + Traceback/TypeError 없음 + 수신률 분리 로그 정상 출력 ("KRX: 100.0%, NXT: 100.0%, 임계값: 95.0%"). 프론트엔드 빌드 성공 (63 modules, 1.81s). 잔존 프로세스 0건.

**위반 원칙 해결**: P10 (SSOT — `nxt_enable` 필드 단일 소스, FID 9081 중복 관리 없음), P21 (사용자 투명성 — KRX/NXT 개별 수신 상태 표시, 정규장 양쪽 대기 상태 명시), P22 (데이터 정합성 — `market_phase` 기반 파생), P23 (일관성 — sector-stock.ts 카운트와 동일 `nxt_enable` 기준, `is_nxt_only_window()` 재사용), P24 (단순성 — FID 9081 틱 분석 대신 `is_nxt_enabled()` 1회 조회, 함수 50줄 이하).

**수정 후 화면 변화**: 업종순위 설정 ② 영역 — 기존(2단계) KRX/NXT 진행 바 2개가 같은 수치 → KRX/NXT 진행 바 2개가 서로 다른 실제 수치. 정규장에서 "KRX는 80%인데 NXT는 40%"처럼 양쪽 진행도 개별 확인. 업종순위 계산 시작 시점 — 정규장에서 양쪽 모두 임계값 도달 시 시작, 한쪽 늦으면 "대기 중" 상태로 표시.

**영향 범위**: 백엔드 4개 파일 + 프론트엔드 2개 파일 + 테스트 2개 파일. DB 영향 없음.

---

## 직전 완료 작업 (이전 세션)

### 2단계: 프론트엔드 수신률 분리 배지 + 진행 바 2인스턴스 — sector-settings.ts (4개 파일)

**배경**: KRX/NXT 수신률 분리 집계 + 분리 배지 표시 3단계 구현의 2단계. 1단계에서 추출한 `createMarketCountRow` 공통 컴포넌트를 재사용하여 sector-settings.ts의 단일 수신률 표시를 KRX/NXT 분리 배지 + 진행 바 2인스턴스로 변경. 백엔드 분리(3단계) 전 과도기 — 단일 수신률을 양쪽에 동일 매핑.

**수정 내용**:
- **`frontend/src/stores/uiStore.ts`**: `ReceiveRateEntry` 인터페이스 추가. `receiveRate` 타입을 `{krx: ReceiveRateEntry | null; nxt: ReceiveRateEntry | null} | null`로 변경. `applySnapshot`에서 단일/분리 양쪽 호환 매핑 (백엔드가 단일 전송 시 양쪽 동일, 분리 전송 시 그대로 사용).
- **`frontend/src/binding.ts`**: `receive-rate`/`sector-scores` 이벤트에서 단일 수신률을 KRX/NXT 양쪽에 동일 매핑 (`{krx: single, nxt: single}`). 3단계에서 백엔드가 분리 데이터 전송 시 자동 연동.
- **`frontend/src/pages/sector-settings.ts`**: 단일 진행 바 → KRX/NXT 2행 분리 배지 + 진행 바 2인스턴스. `createMarketCountRow` 재사용 (showKrx/showNxt 옵션으로 각 시장 세그먼트만 표시). `marketPhase.is_nxt_only` 기반 활성/비활성 전환 (NXT-only 구간 KRX 회색 opacity 0.3). 상태 라벨 옵션 C 정책(AND) 적용 — 정규장 양쪽 임계값 도달 시 "진행 중", NXT-only 구간은 NXT만 기준. 기존 "수신 N종목 / 미수신 N종목" 단일 표시 제거 → KRX/NXT 각 행에 배지+카운트+진행바 통합.
- **`frontend/src/components/common/market-count-row.ts`**: `_appendNxtSegment`에 `isFirst` 파라미터 추가 — NXT 단독 행(sector-settings NXT 행) 시 좌측 여백(marginLeft 14px) 제거. sector-stock.ts에서는 NXT가 항상 KRX/합계 다음이므로 기존 동작 보존.

**유지 대상 (변경 안 함)**:
- 임계치 입력란(thresholdInput) — 1행 그대로 유지.
- 가산점 슬라이더/매수대상 설정 — ③④⑤ 영향 없음.
- 백엔드 수신률 집계 로직 — 3단계에서 수정.

**검증**: typecheck 통과 + build 성공 (63 modules transformed, exit 0, 2.09s). 브라우저 확인 — 사용자 승인 후 커밋.

**위반 원칙 해결**: P21 (사용자 투명성 — KRX/NXT 개별 수신 상태 표시, NXT-only 구간 KRX 비활성 명시), P23 (일관성 — 1단계 공통 컴포넌트 재사용, 진행 바 기존 컴포넌트 2인스턴스).

**수정 후 화면 변화**: 업종순위 설정 ② 영역 — 기존 단일 "수신 N종목 / 미수신 N종목" + 진행 바 1개 → KRX/NXT 2행 분리 배지(KRX: N종목 / NXT▲: N종목) + 진행 바 2개(각각 % 표시 + 임계치 마커). 정규장 양쪽 활성, NXT-only 구간 KRX 회색. 2단계에서는 양쪽 같은 수치 (3단계에서 개별 수치 연동).

**영향 범위**: 프론트엔드 4개 파일. 백엔드/DB 영향 없음.

---

## 직전 완료 작업 (이전 세션)

### 1단계: 프론트엔드 공통 컴포넌트 추출 — sector-stock.ts KRX/NXT/코스피/코스닥 카운트 (2개 파일)

### 보유종목 테이블 수수료·세금 컬럼 삭제 + 매수금액 라벨 병기 (2개 파일)

**배경**: 보유종목 테이블의 "세금" 컬럼이 모든 종목에서 0으로 표시됨. 조사 결과: (1) 세금은 매도 시에만 부과되므로 보유 중인 종목은 구조상 항상 0 (테스트 모드: `_position_from_lots()` 하드코딩 0, 실전 모드: 키움 kt00018 응답에 tax 필드 미존재). (2) "수수료" 컬럼은 매수금액(buy_amt = buy_amount + total_fee)에 이미 포함된 비용의 중복 표시. (3) "매수금액" 라벨만으로는 수수료 포함 여부를 사용자가 알 수 없어 P21(사용자 투명성) 위반 소지.

**근본 원인**: `frontend/src/pages/sell-position.ts:51-62` — COLUMNS 배열에 세금·수수료 컬럼 2개가 의미 없이/중복 표시되고, 매수금액 라벨이 수수료 포함 여부를 명시하지 않음.

**수정 내용**:
- **`frontend/src/pages/sell-position.ts`**: COLUMNS 배열에서 "수수료"(total_fee)·"세금"(tax) 컬럼 정의 2개 제거. "매수금액" 라벨 → "매수금액(수수료 포함)" 병기.
- **`frontend/src/types/index.ts`**: Position 인터페이스에서 `total_fee?`, `tax?` 옵션 필드 2개 제거 (sell-position.ts에서만 사용되었으므로).

**유지 대상 (변경 안 함)**:
- `table-config.ts`의 `tax`/`fee` ColumnType — `profit-shared.ts`(매도 이력 테이블)에서 사용 중.
- 백엔드 `engine_account_notify.py:542`의 `_MIN_POSITION_KEYS` 포함 `tax`/`total_fee` — 데이터 전송 구조 (프론트 미사용 필드는 무시됨, SSOT 위반 아님).
- `trades` 테이블 DB 스키마의 `fee`, `tax` 컬럼 — 매도 이력/수익 분석에 사용되므로 변경 금지.

**검증**: `npm run build` 성공 (62 modules transformed, exit 0). 잔존 참조 확인: `total_fee` 프론트엔드에서 완전 제거, `r.tax`/`d.tax` 잔존은 profit-shared.ts·canvas-profit-chart.ts의 매도 이력 기반 데이터로 정상 유지 대상.

**위반 원칙 해결**: P21 (사용자 투명성 — 매수금액에 수수료 포함 여부 명시, 의미 없는 0 표시 컬럼 제거로 오인 방지), P24 (단순성 — 중복·의미 없는 컬럼 제거).

**수정 후 화면 변화**: 보유종목 테이블에서 "수수료"·"세금" 컬럼 2개 사라짐. 컬럼 순서 `... 매수금액(수수료 포함) | 평가손익 ...`로 변경. 매수금액 값 자체는 기존과 동일(수수료 포함 총매입가).

**영향 범위**: 프론트엔드 2개 파일. 백엔드/DB 영향 없음.

---

## 미해결 문제 P-NEW-1: 직접 타이핑 시 슬라이더/저장값 범위 불일치 → 해결 완료 (2026-07-16)

**이슈 ID**: P-NEW-1 (신규 등록 2026-07-16, 해결 2026-07-16)
**상태**: 해결 완료 — `input` 이벤트 실시간 clamp 적용. 빌드 검증 완료.

**문제**: `createNumInput` 공통 컴포넌트에서 사용자가 입력창에 직접 타이핑할 때 `min`/`max` 범위 clamp가 적용되지 않아, 짝이 되는 슬라이더(`-100~+100`)와 저장값이 불일치. 예: 가산점 입력창에 `150` 또는 `-200`을 직접 타이핑하면 그대로 `onChange`로 저장되지만 슬라이더는 `-100~+100` 범위.

**근본 원인**: `frontend/src/components/common/setting-row.ts:224-228` — `input` 이벤트 핸들러가 `Number(raw) || 0`로 변환만 하고 `min`/`max` clamp 없이 `onChange` 전달. 반면 ▲/▼ 버튼(235-236줄)은 `Math.min(maxVal, ...)` / `Math.max(minVal, ...)` clamp 적용. 두 경로(직접 타이핑 vs 버튼)의 허용 범위가 분리 관리됨.

**위반 원칙**: P10 (SSOT — 값 허용 범위가 슬라이더·버튼·직접 타이핑 3경로에서 단일 지정되지 않고 분리 관리).

**수정 이력 (롤백 포함 — AGENTS.md 섹션3 규칙 0-3 준수)**:
1. **1차 시도 (커밋 `0dee1e6`, 롤백됨)**: `blur` 시점 clamp 적용. "타이핑 중간값 잘림 방지"를 사유로 포커스 잃을 때 보정.
2. **롤백 사유**: 사용자 지적 — "바깥 클릭을 해야 되돌아가는 건 표준 아키텍처가 아닐 것 같다". 실제 문제 분석:
   - blur 전에 저장 버튼 누르면 범위 밖 값이 그대로 저장됨 (input 이벤트에서 clamp 없이 onChange 호출하므로).
   - 타이핑 중 입력창과 슬라이더가 불일치 상태로 방치됨.
   - "타이핑 중간값 잘림"은 실제로 미미함 — `-100` 입력 과정(`-`, `-1`, `-10`, `-100`)은 전부 범위 내, `150` 입력 시 `150` 순간 보정되는 것이 자연스러운 즉시 피드백.
   - 숫자 입력창 + 슬라이더 짝에서는 input 이벤트 실시간 clamp가 표준 패턴.
3. **2차 적용 (현재)**: `blur` 리스너 제거 → `input` 이벤트 핸들러에 실시간 clamp 추가. 범위 밖 값 입력 즉시 보정 + 슬라이더와 항상 일치 + 저장값 항상 유효.

**수정 내용** (2026-07-16 2차 적용):
- `frontend/src/components/common/setting-row.ts:224-238` — `input` 이벤트 핸들러에서 `Number(raw) || 0` 후 `Math.min(maxVal, Math.max(minVal, parsed))`로 clamp. `Math.round(... * 100) / 100`로 소수점 2자리 반올림 (▲/▼ 버튼과 동일 패턴, P23 일관성). 보정된 경우(`clamped !== parsed`)에만 `input.value` 갱신 — 범위 내 타이핑 시 커서 위치 보존.
- `blur` 리스너 제거 (1차 시도 코드 롤백).
- 기존 호출부 보존: `min`/`max` 미지정 시 기본값 `0`/`Infinity` → 기존 동작 보존. 가산점 3개 입력창만 `min:-100, max:100`으로 실제 clamp 적용.

**검증**: `npm run build` 성공 (62 modules transformed, exit 0, 1.97s). 브라우저 확인 대기 — 가산점 입력창에 `150` 또는 `-200` 타이핑 즉시 `+100`/`-100`으로 보정되는지, 슬라이더와 일치하는지, 범위 내 타이핑 시 커서 튐 현상 없는지.

**수정 후 화면 변화**: 가산점 입력창에 범위 밖 값(`150`, `-200` 등)을 직접 타이핑하면 즉시 `+100`/`-100`으로 보정 (바깥 클릭 불필요). 슬라이더·▲/▼ 버튼·직접 타이핑 3경로 모두 `-100~+100` 단일 범위로 통일.

**영향 범위**: 프론트엔드 1개 파일(`setting-row.ts`). `createNumInput` 사용 모든 호출부(buy-settings 8곳, sell-settings 4곳, sector-settings 6곳)에 동일 적용 — 기본값 `min:0, max:Infinity`이므로 기존 동작 보존.

---

## 다음 세션 진행 대기: 실시간 체결 불가 시간대 주문 일시 중단

**문제**: NXT 장마감(20:00) 후 ~ 확정 다운로드(20:40) 전 구간에서 업종별 종목 시세 테이블과 보유종목 테이블의 실시간 필드가 0과 -로 혼용 표시됨.

**근본 원인**: `load_master_stocks_table()`에서 DB NULL을 로드할 때 필드마다 변환 방식이 불일치 — `cur_price`/`change`는 `int(... or 0)` 폴백으로 0 변환, `change_rate`/`trade_amount`는 None 보존. 이로 인해 같은 "데이터 없음" 상태가 0과 None 두 값으로 분리 관리됨 (P10 SSOT 위반, P20 폴백 금지 위반, P23 일관성 위반).

**수정 내용**:
1. `backend/app/db/stock_tables.py` 348-349줄: `cur_price`/`change`의 `int(... or 0)` 폴백 제거 → `int(...) if ... is not None else None` 패턴으로 `change_rate`/`trade_amount`와 통일
2. `backend/app/services/market_close_pipeline.py` 825-840줄: 신규 종목 초기값 `cur_price: 0, change: 0, change_rate: 0.0, trade_amount: 0` → `None` 4개 통일
3. `backend/tests/test_stock_tables.py`: NULL 보존 테스트 추가 (`test_load_null_realtime_fields_preserved`)

**검증**: 백엔드 테스트 264개 통과 + 런타임 기동 (RuntimeWarning 에러 없음, 1340종목 로드, 99ms 기동) + 잔존 프로세스 0건.

**위반 원칙**: P10 (SSOT — "데이터 없음" 단일 기준 None 통일), P20 (폴백 금지 — or 0 폴백 제거), P23 (일관성 — 4개 실시간 필드 동일 패턴).

**수정 후 화면 변화**: 20:00~20:40 구간에서 모든 실시간 필드가 동일하게 "-"로 표시 (현재가·대비의 "0"이 "-"로 통일). 20:40 이후 확정 데이터 채워지면 실제 값 표시.

---

## 다음 세션 진행 대기: 실시간 체결 불가 시간대 주문 일시 중단

### 계획서 경로
- **`docs/plan_order_suspension_by_time.md`** — 구현 계획서 (사전조사 결과 + 구현 Step 1~10 + 세션 분할 + 사용자 결정 항목)

### 핵심 발견 (사전조사 결과)
1. **현재 차단 누락 구간**: `is_krx_after_hours()`가 "시가 동시호가"(08:50~09:00), "종가 동시호가"(15:20~15:30)를 차단하지 않음.
2. **매도 경로 시간 체크 전무**: `execute_sell()`에 시간 체크가 전혀 없어 동시호가 시간대에 손절/익절 매도 주문이 들어갈 수 있음.
3. **매수 경로 P16 위반 소지**: 시간 체크가 `buy_order_executor.py` 외부에만 있고 `execute_buy()` 내부에는 없어 수동 매수(force_buy) 시 우회 가능.
4. **기존 자산 재사용 가능**: `KRX_INACTIVE_PHASES` frozenset에 이미 "시가 동시호가", "종가 동시호가" 포함 — 새 시간 상수 불필요 (P10/P23).

### 사용자 결정 필요 항목 (계획서 섹션 3)
다음 세션 시작 전 사용자가 결정해야 할 5가지:
1. **3-1 NXT 종목 처리**: A) 전부 차단 / B) KRX·NXT 분리 차단 (15:40~16:00 NXT 애프터마켓 매매 허용 여부)
2. **3-2 시간외 거래 구간**: 장전/장후 시간외 시장가 주문 차단 포함 여부
3. **3-3 ±5초 여유 적용**: A) phase 산정 / B) 주문 체크 시점 (추천 B)
4. **3-4 수동 매수 차단**: 동시호가 시간대 수동 매수도 차단 여부
5. **3-5 매도 차단**: 동시호가 시간대 매도도 차단 여부 (권장: 차단)

### 구현 세션 분할 (계획서 섹션 6)
- 세션 1: Step 1 (시간대 차단 판별 함수) + Step 4 (설정 키 추가)
- 세션 2: Step 2 (execute_buy 내부 체크) + Step 3 (execute_sell 내부 체크)
- 세션 3: Step 5 (WS 이벤트) + Step 8 (바인딩)
- 세션 4: Step 6 (설정 토글) + Step 7 (헤더 칩)

### 승인 대기 상태
- 사용자가 5가지 결정 항목을 확정하고 "진행해" 등 실행 지시어를 줄 때까지 코드 수정 금지 (AGENTS.md 섹션3 규칙 0).
- 거래 로직 수정이므로 safe-trade 스킬 필수 (P15 단일 주문 경로, P16 살아있는 경로, P18 테스트모드 동등성).

---

## 직전 완료 작업 (이전 세션)

### 실시간 시세 0/- 혼용 근본 해결 — DB NULL→None 보존 통일 (3개 파일)

**문제**: NXT 장마감(20:00) 후 ~ 확정 다운로드(20:40) 전 구간에서 업종별 종목 시세 테이블과 보유종목 테이블의 실시간 필드가 0과 -로 혼용 표시됨.

**근본 원인**: `load_master_stocks_table()`에서 DB NULL을 로드할 때 필드마다 변환 방식이 불일치 — `cur_price`/`change`는 `int(... or 0)` 폴백으로 0 변환, `change_rate`/`trade_amount`는 None 보존. 이로 인해 같은 "데이터 없음" 상태가 0과 None 두 값으로 분리 관리됨 (P10 SSOT 위반, P20 폴백 금지 위반, P23 일관성 위반).

**수정 내용**:
1. `backend/app/db/stock_tables.py` 348-349줄: `cur_price`/`change`의 `int(... or 0)` 폴백 제거 → `int(...) if ... is not None else None` 패턴으로 `change_rate`/`trade_amount`와 통일
2. `backend/app/services/market_close_pipeline.py` 825-840줄: 신규 종목 초기값 `cur_price: 0, change: 0, change_rate: 0.0, trade_amount: 0` → `None` 4개 통일
3. `backend/tests/test_stock_tables.py`: NULL 보존 테스트 추가 (`test_load_null_realtime_fields_preserved`)

**검증**: 백엔드 테스트 264개 통과 + 런타임 기동 (RuntimeWarning 에러 없음, 1340종목 로드, 99ms 기동) + 잔존 프로세스 0건.

**위반 원칙**: P10 (SSOT — "데이터 없음" 단일 기준 None 통일), P20 (폴백 금지 — or 0 폴백 제거), P23 (일관성 — 4개 실시간 필드 동일 패턴).

**수정 후 화면 변화**: 20:00~20:40 구간에서 모든 실시간 필드가 동일하게 "-"로 표시 (현재가·대비의 "0"이 "-"로 통일). 20:40 이후 확정 데이터 채워지면 실제 값 표시.

---

## 직전 완료 작업 (이전 세션)

### 상단 요약 배지 위계 분리 + 색상/라벨 일관성 개선 (2개 파일)

**배경**: 사용자 보고 "보유주식 평가금액 숫자가 빨간색". 조사 결과 공통 배지 컴포넌트(`badge.ts`)의 `createBadge`에서 숫자 기본색이 `COLOR.up`(빨강)으로 고정되어, 색상을 따로 지정하지 않은 모든 배지(평가금액·주문가능금액·일일매수금액·동시보유한도) 숫자가 빨강으로 표시되던 문제. 추가로 라벨·숫자·단위가 같은 크기·같은 색으로 붙어 있어 시각적 위계가 없었고, 보유종목 3개 배지 라벨 길이가 제각각이라 숫자 위치가 정렬되지 않아 일관성 부족.

**수정 내용**:
- **`frontend/src/components/common/badge.ts`** (공통 배지 컴포넌트):
  - 숫자 기본색 `COLOR.up`(빨강) → `COLOR.neutral`(`#333`, 검정) 근본 해결 — 단순 수치가 빨강으로 표시되던 문제 해결.
  - 위계 분리: 숫자 13px 굵게(600, 중심), 라벨 13px 회색, 단위 11px 회색(보조), 상태 13px 회색.
  - 요소 간 gap 16px + `justifyContent: center` 중앙 정렬 + `alignItems: baseline` 하단 맞춤.
  - `updateBadge`에 `statusNumber`/`statusLabel` 옵션 추가 — "(N종목)"에서 N만 파란색(`COLOR.down`) 강조, 나머지 회색. 괄호 안 공백 추가 "( 4 종목 )".
- **`frontend/src/pages/sell-position.ts`** (보유종목 페이지):
  - 평가금액 배지: `statusText` → `statusNumber`/`statusLabel` 옵션으로 변경 (종목 수 파란색 강조).
  - 라벨 자세하게 통일: "보유주식 평가금액" → "보유주식 평가금액 합계", "평가손익" → "보유주식 평가손익 합계", "수익률" → "보유주식 평가수익률" (3개 라벨 길이 비슷 → 숫자 위치 정렬 → 일관성).

**검증 결과**:
- typecheck 통과, 빌드 성공 (642ms~2.09s).
- 브라우저 확인: 사용자가 "훨씬 좋아보인다" 확인.

**영향 범위**: 프론트엔드 2개 파일. 백엔드/DB 영향 없음.
- 보유종목 페이지 배지 3개 + 매수후보 페이지 배지 3개에 일괄 적용 (공통 컴포넌트 수정).
- 손익/수익률 배지 색상은 기존대로 유지 (이미 색상 따로 지정 → 영향 없음).

**아키텍처 원칙 부합**:
- P10 (SSOT): 잘못된 기본색(`COLOR.up`)을 단일 진실 소스에서 수정 — 모든 배지에 일관 적용.
- P20 (폴백 금지): 빨강을 폴백으로 덮지 않고 기본값 자체를 근본 수정.
- P21 (사용자 투명성): 단순 수치(평가금액 등)가 손익색(빨강)으로 오인되던 것을 해결.
- P23 (일관성): 공통 배지 컴포넌트 1곳 수정으로 2페이지 6배지 일관성 확보. 라벨 길이 통일로 숫자 위치 정렬.

## 직전 완료 작업 (이전 세션)

### 실시간 자동 연결 토글 라벨 + 설명 개선 (1개 파일)

**배경**: 기존 라벨 "실시간 연결"은 토글 역할(자동 연결 ON/OFF)이 직관적으로 드러나지 않았고, 설명 텍스트 "실시간 데이터 자동 연결 스위치 — OFF면 수동 연결만 가능"은 ON 시 언제 연결/해제되는지 안내가 없어 P21(사용자 투명성) 미흡. 사용자 제안으로 라벨 + 설명 모두 동작을 정확히 표기하도록 개선.

**수정 내용**:
- **`frontend/src/pages/general-settings.ts`**:
  - 라벨 "실시간 연결" → "실시간 자동 연결" (토글이 자동 연결 스위치임을 직관적으로 표시).
  - 설명 "실시간 데이터 자동 연결 스위치 — OFF면 수동 연결만 가능" → "ON: 거래일 오전 8시 자동 연결 → 오후 8시 자동 해제 (주말·공휴일 제외) / OFF: 자동 연결 안 함" (백엔드 NXT_ACTIVE_PHASES 08:00~20:00 기준 정확 표기).

**검증 결과**:
- typecheck 통과, 빌드 성공 (743ms).

**영향 범위**: 프론트엔드 1개 파일 2줄. 백엔드/DB 영향 없음.

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): 토글 ON 시 동작 시간을 사용자에게 명시 — 강화.
- P23 (일관성): 기존 설명 텍스트 패턴(createDescText) 유지.

### 기동 시 자동 다운로드 스킵 로직 무력화 근본 해결 — 기준일 SSOT 통일 (3개 파일)

**배경**: 사용자 보고 "앱 기동 시마다 오늘 이미 다운로드한 데이터가 있어도 무조건 다시 자동 다운로드 실행". 조사 결과, 토글 커밋(`b3d2611`)이 아닌 같은 날 새벽 머지된 `f50ce9f`가 원인. `f50ce9f`는 5일봉 미확정 당일 행 유입 차단을 위해 다운로드 파이프라인의 기준일을 `get_kst_today_str()`(달력 오늘)에서 `get_previous_trading_day_str(get_current_trading_day_str())`(가장 최근 확정된 거래일 = 직전 거래일)로 변경. 이에 따라 `master_stocks_table.date`에 직전 거래일이 저장되게 되었으나, 기동 스킵 로직(`retry_pipeline_catchup_after_bootstrap`)은 여전히 `get_current_trading_day_str()`(달력 오늘)과 비교하여 항상 불일치 → 무조건 다운로드 트리거. P10(SSOT) 위반 — 다운로드 파이프라인·수동 확인 API는 직전 거래일 기준으로 변경되었으나 기동 스킵 로직만 누락.

**수정 내용**:
- **`backend/app/services/daily_time_scheduler.py`** (`retry_pipeline_catchup_after_bootstrap`):
  - 비교 기준일을 `get_current_trading_day_str()`(달력 오늘)에서 `get_previous_trading_day_str(get_current_trading_day_str())`(가장 최근 확정된 거래일)로 변경 — 다운로드 파이프라인과 동일 기준(P10 SSOT).
  - 변수명 `_current_trading_day` → `_latest_confirmed_day`, `_cache_is_today` → `_cache_is_fresh`로 변경 (의미 반영, P23 용어 일관성).
  - 로그 메시지 "현재 거래일" → "최근 확정 거래일" 3곳 변경.
  - 기준일 변경 이유를 설명하는 주석 추가 (다운로드 파이프라인·수동 API와 동일 기준 P10 SSOT).
- **`backend/app/services/market_close_pipeline.py`** (`execute_unified_rolling_and_save` 주석):
  - `f50ce9f`에서 작성된 주석 "장 후 실행 시 date=오늘(07-15 확정)… 스킵 판단이 정확하게 동작함"이 코드 동작과 불일치(실제로는 항상 직전 거래일 저장)하던 것을 정정 (P21 사용자 투명성 + 주석/코드 일치).
- **`backend/tests/test_daily_time_scheduler.py`** (`TestRetryPipelineCatchup`):
  - `test_disconnected_cache_outdated_triggers_fetch`: 캐시 date `20250105` → `20250104`로 변경. (is_trading_day=True 모킹 시 current 20250106의 직전 거래일=20250105이므로, 캐시 20250105는 이제 fresh가 되어 트리거하지 않음. outdated 케이스를 만들려면 20250104 필요.)
  - `test_disconnected_cache_today_sets_done` → `test_disconnected_cache_fresh_sets_done`로 메서드명 변경 + 캐시 date `20250106` → `20250105`로 변경. (캐시 20250105 = 최근 확정 거래일 20250105 → 일치 → 스킵. "today"가 아닌 "fresh"로 의미 정정.)
  - 각 테스트에 캐시 date와 최근 확정 거래일의 관계를 설명하는 주석 추가.

**검증 결과**:
- pytest 전체 2742개 통과 (5.88s). test_daily_time_scheduler 4개 + test_market_close_pipeline 188개 포함.
- 런타임 기동 정상 (`-W error::RuntimeWarning` 모드, RuntimeWarning 0건, 서버 정상 기동 + Uvicorn 리스닝 확인).
- 런타임 로그로 스킵 동작 확인: `23:10:52 [스케줄] 단절 구간 기동 — 캐시(20260715) = 최근 확정 거래일(20260715) 확정 다운로드 시각 경과 (스킵)` — 23:10 기동 시 current_trading_day=20260716(20:00 이후라 다음 거래일), previous=20260715, 캐시=20260715 → 일치 → 스킵. 수정 전이라면 캐시(20260715) ≠ 현재거래일(20260716)로 무조건 다운로드 트리거했을 것.
- 잔존 프로세스 0건 + lock 파일 정리 완료.

**영향 범위**: 백엔드 2개 파일 + 테스트 1개 파일. 프론트엔드/DB 영향 없음(스키마 변경 없음, 백업 불필요). 매수/매도/업종 점수/수신률 로직에 영향 없음 — 기동 시 다운로드 스킵 여부 판단만 수정.

**아키텍처 원칙 부합**:
- P10 (SSOT): 다운로드 파이프라인·수동 확인 API·기동 스킵 로직 3곳 모두 동일 기준일(가장 최근 확정된 거래일) 사용으로 통일. 기존에는 기동 스킵 로직만 달력 오늘 기준이어서 SSOT 위반.
- P16 (살아있는 경로): 스킵 로직이 실제 기동 실행 경로에서 호출됨 확인 (`engine_cache._load_caches_preboot` → `retry_pipeline_catchup_after_bootstrap`).
- P20 (폴백 금지): 스킵이 안 된다고 다른 곳에서 억지로 막지 않음 — 기준일 비교 1곳만 수정하여 근본 해결.
- P21 (사용자 투명성): `f50ce9f`의 불일치 주석을 정정하여 주석/코드 일치 복원. 사용자 모르게 스킵 로직이 망가져 있던 것을 규명+해결.
- P23 (일관성): 변수명/로그 메시지를 실제 의미("최근 확정 거래일")에 맞게 정정.

## 직전 완료 작업 (이전 세션)

### Connector dead code 제거 — _realtime_enabled / _auto_trade_enabled 2계열 (6개 파일)

**배경**: 사전조사 중 `set_realtime_enabled()`/`is_realtime_enabled()`가 Connector에 플래그를 저장하기만 하고 프로덕션 코드에서 한 곳도 읽지 않는 dead code(P16 위반)임을 발견. 동일 패턴의 `_auto_trade_enabled` 계열도 dead code. 실제 의사결정은 `ws_subscribe_on`(WS 연결 게이트, engine_loop.py:304)과 `time_scheduler_on`(자동매매 타이머)이 담당하므로 Connector 플래그는 중복 저장이었음. 사용자 승인 하에 2계열 모두 제거.

**수정 내용**:
- **`backend/app/core/broker_connector.py`**: 기본 구현 스텁 `set_auto_trade_enabled`/`set_realtime_enabled` 2개 메서드 제거.
- **`backend/app/core/kiwoom_connector.py`**: `_realtime_enabled`/`_auto_trade_enabled` 필드 2개 + `is_realtime_enabled`/`set_realtime_enabled`/`is_auto_trade_enabled`/`set_auto_trade_enabled` 메서드 4개 제거.
- **`backend/app/core/ls_connector.py`**: 동일하게 필드 2개 + 메서드 4개 제거.
- **`backend/app/services/engine_service.py`**: `set_realtime_enabled()` 호출 1곳 + `set_auto_trade_enabled()` 호출 1곳 제거. 주석 번호 재정렬 (3)→(2), (4)→(3)).
- **`backend/tests/test_kiwoom_connector.py`**: `_realtime_enabled`/`_auto_trade_enabled` assertion 2개 + `test_realtime_get_set`/`test_auto_trade_get_set` 테스트 메서드 2개 제거.
- **`backend/tests/test_ls_connector.py`**: assertion 2개 + `TestLsConnectorSettings` 클래스 전체(테스트 4개) 제거.

**검증 결과**:
- 잔존 참조 0건 확인 (grep 전체 코드베이스).
- pytest 전체 2742개 통과 (0.70s).
- 런타임 기동 정상 (`-W error::RuntimeWarning` 모드, 에러/Traceback/RuntimeWarning 없음, 앱 시작 완료 + Uvicorn 리스닝 확인).
- 잔존 프로세스 0건 + lock 파일 정리 완료.

**영향 범위**: 백엔드 4개 파일 + 테스트 2개 파일. 프론트엔드/DB 영향 없음. 실시간 연결 토글(ws_subscribe_on) 및 자동매매 토글(time_scheduler_on) 동작 변경 없음 — 실제 게이트는 engine_loop.py의 `is_ws_subscribe_window()`와 daily_time_scheduler의 타이머가 담당하므로.

**아키텍처 원칙 부합**:
- P16 (살아있는 경로): 저장된 플래그를 아무도 읽지 않는 dead code 제거 → 강화.
- P24 (단순성): Connector에서 의미 없는 필드/메서드 2쌍씩 감소 → 강화.
- P10 (SSOT): 실제 의사결정은 ws_subscribe_on/time_scheduler_on 단일 소스가 담당, Connector 플래그는 중복 저장이었음 → 제거로 강화.

## 직전 완료 작업 (이전 세션)

### 1일봉차트 자동다운로드 토글 추가 + 라벨 개선 (2개 파일) — 커밋 `b3d2611`

**배경**: 일반설정 API 설정 탭의 "1일봉챠트 시세 다운로드" 행에 시간 입력란만 있고 ON/OFF 토글이 없어, 사용자가 자동 다운로드를 끄거나 켤 수 없었음. 백엔드에는 이미 `scheduler_market_close_on` 토글 설정값과 게이트 로직(`market_close_pipeline.py:1003`)이 구현되어 있었으나, 프론트엔드에 UI가 없어 P21(사용자 투명성) 위반 상태. 사용자 제안으로 토글 추가 + 라벨에 "자동다운로드" 명시.

**수정 내용**:
- **`frontend/src/pages/general-settings.ts`**:
  - 모듈 상태에 `confirmedDlToggle` 참조 추가.
  - `renderApiSettingsTab`의 confirmedDlRow 행 구조 변경: 라벨 왼쪽, 오른쪽에 [시간 슬롯 + 토글] 배치 (기존 "실시간 연결" 행 패턴과 동일 정렬).
  - 라벨 "1일봉챠트 시세 다운로드" → "1일봉차트 자동다운로드" (챠트→차트 오타 수정 + "자동다운로드" 추가).
  - 토글 ON/OFF 시 `scheduler_market_close_on` 즉시 저장 + 시간 슬롯 활성화/비활성화 (`setDisabled`).
  - 저장 실패 시 롤백 처리 (토글 + 시간 슬롯 상태 복원).
  - 설명 문구 "장마감 후 확정 시세 다운로드 시간" → "장마감 후 자동 다운로드 시간 (기본값 20:40) — OFF 시 수동 다운로드만 가능".
  - `syncFromSettings`에 토글 상태 동기화 + 시간 슬롯 활성화/비활성화 연동 추가.
  - `setDisabled` import 추가 (`ui-styles`).
- **`backend/app/services/engine_service.py`**:
  - `_WS_SCHEDULE_KEYS`에 `scheduler_market_close_on` 추가 — 토글 변경 시 타이머 즉시 재예약.

**검증 결과**:
- typecheck 통과, 빌드 성공.
- 백엔드 테스트 186개 전체 통과 (test_engine_settings + test_daily_time_scheduler).
- 백엔드 런타임 기동 정상 (포트 8000).

**영향 범위**: 프론트엔드 1개 파일 + 백엔드 1개 파일. 새 설정 키 추가 없이 기존 `scheduler_market_close_on` 재사용 (P10 SSOT 준수).

**아키텍처 원칙 부합**:
- P10 (SSOT): 새 키 만들지 않고 기존 `scheduler_market_close_on` 재사용.
- P16 (살아있는 경로): 이미 게이트가 동작 중, UI만 추가하여 호출 경로 연결.
- P21 (사용자 투명성): 백엔드 토글을 UI에 노출하여 사용자가 자동 다운로드 제어 가능.
- P23 (일관성): 기존 행 정렬 패턴(실시간 연결, 플래시 효과 행)과 동일 구조 유지.
- P24 (단순성): 백엔드 변경 1줄, 프론트엔드 UI만 추가.

## 직전 완료 작업 (이전 세션)

### 발견 문제 기록 의무에 '개선점' 추가 + 롤백 사유 기록 의무 신설 — AGENTS.md 규칙 9 + 5개 스킬 (6개 파일)

**배경**: AGENTS.md 규칙 9 "작업 중 발견 문제 기록 의무"는 위반/오류/버그/dead code/폴백 패턴 중심이며, problem-solve 스킬에는 이미 "개선점"이 언급되어 있어 양쪽 불일치 (P23 위반 소지). 사용자 제안으로 "아키텍처 원칙에 부합하는 더 나은 구조(개선점)"를 기록 대상에 추가.

**수정 내용**:
- **AGENTS.md 규칙 9 본문**: "아키텍처 위반(P원칙), 오류, 잠재적 버그, dead code, 폴백 패턴, 아키텍처 원칙에 부합하는 더 나은 구조(개선점) 등"으로 확장.
- **AGENTS.md 규칙 9 하위 항목 신설 "개선점 인정 기준 (P24 준수)"**: 주관적 취향이 아닌 객관적 근거 있는 것만 — (a) 특정 P원칙에 부합하여 정량적으로 더 단순/일관/정합 (b) 기존 공통 자산 재사용으로 중복 제거 (c) 명확한 중복·dead code·폴백 회피 가능. 근거 없는 "더 좋을 것 같음"은 기록 대상 아님.
- **AGENTS.md 규칙 9 기록 형식**: "위반 원칙 번호" → "위반/부합 원칙 번호(개선점의 경우)" 확장. 세션 종료 보고 문구 "N건의 신규 문제" → "N건의 신규 문제/개선점" 확장.
- **5개 스킬 파일** (problem-solve, backend-fix, frontend-fix, safe-trade, db-backup) "작업 중 발견 문제 기록 의무" 섹션: 동일 문구로 통일. problem-solve는 95행 기존 "개선점" 단어에 조건 명시 보완 (객관적 근거, P24 준수, AGENTS.md 상세 참조).

**검증 결과**: grep으로 6개 파일 동일 문구 확인 완료. 구 문구("폴백 패턴 등") 잔존 0건.

**영향 범위**: 문서 파일 6개만 변경. 코드 변경 없음.

**아키텍처 원칙 부합**:
- P10 (SSOT): AGENTS.md 규칙 9가 단일 진실 소스, 5개 스킬은 "상세 규칙은 AGENTS.md 섹션4 규칙 9 참조" 역참조.
- P23 (일관성): 6개 파일 동일 문구, problem-solve 기존 "개선점"과 AGENTS.md 본문 정합.
- P24 (단순성): 개선점 인정 기준으로 남발 방지, 규칙 비대화 회피.

### 롤백 사유 기록 의무 신설 + 롤백으로 증상 덮기 금지 — AGENTS.md 규칙 0-3 + problem-solve 스킬 (2개 파일)

**배경**: AGENTS.md 규칙 0-3 "사용자 승인 없는 롤백 절대 금지"는 승인 자체는 담당하나, 승인 후 **사유 기록** (git commit 메시지, HANDOVER.md)은 명시되어 있지 않았음. 나중에 git log나 HANDOVER.md만 보는 사람이 "왜 이전 상태로 되돌아갔지?" 오인하는 빈틈. 또한 problem-solve 스킬에 롤백과 근본 해결의 관계 미명시.

**수정 내용**:
- **AGENTS.md 규칙 0-3 하위 항목 신설 "롤백 사유 기록 의무 (강제)"**: 사용자 승인받아 롤백 진행한 경우, (1) git commit 메시지에 사유·되돌린 대상·영향 범위 상세 기록 ("revert" 한 단어로 끝내지 않음), (2) HANDOVER.md "직전 완료 작업" 섹션에 롤백 내용과 사유 명시.
- **problem-solve/SKILL.md 7항 "근본 원인 식별"**: "롤백으로 증상 덮기 금지" 추가 — 롤백 후에도 근본 원인이 남아있으면 재발. 롤백이 적절한 경우(잘못된 변경 되돌림, 승인받은 경우)와 부적절한 경우(증상 회피용) 구분 명시. AGENTS.md 규칙 0-3 역참조.

**검증 결과**: grep으로 4개 스킬(problem-solve/backend-fix/frontend-fix/safe-trade) "기존 로직 롤백 여부 확인" 항목이 "AGENTS.md 섹션3 규칙 0-3 준수" 역참조 확인 → 0-3에 하위 항목 추가하면 자동 전파 구조 정상.

**영향 범위**: 문서 파일 2개만 변경. 코드 변경 없음. 4개 스킬은 역참조 구조로 개별 수정 불필요 (P10 SSOT 유지).

**아키텍처 원칙 부합**:
- P10 (SSOT): AGENTS.md 규칙 0-3이 단일 진실 소스, 4개 스킬은 역참조로 자동 전파.
- P23 (일관성): problem-solve "롤백으로 증상 덮기 금지"가 AGENTS.md 0-3 역참조로 정합.
- P24 (단순성): 이미 존재하는 규칙 1·2(승인 없는 롤백 금지, 로직 변경 보고 의무)는 중복 추가하지 않고, 빈틈(기록 의무)만 보완.

## 직전 완료 작업 (이전 세션)

### 수익상세페이지 상단 카드 3→4 확장 + 기간별 색상 차별화 + 하단 통계 연동 (3개 파일) — 커밋 `09629b8`

**배경**: 수익상세페이지 상단 요약 카드가 당일/당월/누적 3개이며, 선택 시 모두 동일 파랑 색상이라 어떤 기간을 보고 있는지 시각적 구분이 안 됨. 수익현황(overview) 차트에는 이미 '직전' 버튼이 있어 두 페이지 간 빠른 범위 옵션이 불일치. 사용자 제안으로 '직전' 카드 추가 + 4카드 색상 차별화 + 하단 6개 통계 카드 색상 연동.

**수정 내용**:
- **`frontend/src/components/common/ui-styles.ts`**: 기간 구분 전용 색 3종 추가 (기존 의미 색 success/warning/up/kosdaq과 충돌 회피). `periodPrev`(#0097a7 청록)/`periodPrevBg`(#e0f7fa), `periodMonth`(#7b1fa2 보라)/`periodMonthBg`(#f3e5f5), `periodTotal`(#455a64 슬레이트)/`periodTotalBg`(#eceff1). 당일은 기존 `down`/`downBg` 재사용.
- **`frontend/src/pages/profit-shared.ts`**: `SummaryCardEls` 인터페이스에 `prevPnlEl`/`prevRateEl`/`prevCard` 추가. `SummaryCardCallbacks`에 `onPrevClick` 추가. `createSummaryCards` 3카드→4카드 확장 (CARD_TITLES = 당일/직전/당월/누적). `updateSummaryCards`에 직전 손익 계산 추가 — dailySummary에서 오늘보다 이전 날짜 중 가장 최근 항목 추출 (O(n) 단일 패스, 백엔드 추가 호출 없이 기존 데이터에서 파생).
- **`frontend/src/pages/profit-detail.ts`**:
  - `SelectedView` 타입에 `'prev'` 추가. `loadProfitDetailView` validViews 및 from/to 검증 조건에 'prev' 포함.
  - `applyCardStyle`을 카드별 보더/배경 색상 받도록 변경. `updateCardSelection`이 4카드 각각 해당 색상 적용.
  - 신규 `updateStatCardSelection()` — 하단 6개 통계 카드 색상을 상단 선택 기간과 동일 색으로 연동. `selectedView === null`(수동 날짜) 시 회색(borderLight/surfaceLight) 복귀.
  - `onPrevClick` 핸들러 — `api.getPrevTradingDay()` 비동기 조회 후 `filterByDate(prev.date)`. await 중 다른 카드 클릭 시 덮어쓰기 방지 가드(`if (selectedView !== 'prev') return`) 추가.
  - 하단 통계 카드 생성 시 `statCardEls` 배열에 push하여 색상 연동 대상 관리. unmount에서 초기화.
  - `api` import 추가 (`../api/client`).

**검증 결과**:
- typecheck 통과, 빌드 성공 (62 modules).
- 테스트 108개 전체 통과 (기존 실패 없음, profit 관련 테스트는 없으나 전체 회귀 확인).

**영향 범위**: 프론트엔드 3개 파일. 백엔드 변경 없음 (기존 `getPrevTradingDay` API 재사용). profit-overview는 `createSummaryCards` 미사용이라 영향 없음. 공유 함수 `createSummaryCards`의 실제 사용처는 profit-detail 1곳.

**아키텍처 원칙 부합**:
- P10 (SSOT): 공유 함수 1곳에서 4카드 관리, 직전 손익은 기존 dailySummary에서 파생 (중복 저장 금지).
- P21 (사용자 투명성): 하단 통계 색상 연동으로 "현재 보는 기간" 상단/하단 양쪽 시각화, 수동 날짜 시 회색 복귀로 상태 명확.
- P23 (일관성): overview 차트 '직전' 버튼과 detail '직전' 카드 일치, 기존 의미 색 충돌 회피한 신규 기간 구분 색 추가.
- P24 (단순성): 보더+옅은 배경으로 손익 텍스트 색(빨강/파랑)과 충돌 회피, 직전 손익 O(n) 단일 패스 추출.

## 다음 세션 작업
- **최우선: P-001 Step 2 진행 — 사용자 승인 후**
  - Step 1 완료. `engine_radar.py:73-77` 틱 수신 폴백 제거 완료.
  - Step 2 (세션 2): `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + `_has_any_realtime_data` 검증. 영향 범위 중간.
  - Step 3 (세션 3): `sector_calculator.py:69,78` 업종 점수 폴백 제거. 영향 범위 넓음.
  - 각 Step 시작 시 사용자 명시적 승인 필요.
- **다운로드 완료 시간 표시 (제안2)**: 1일봉/5일봉 다운로드 버튼 우측에 가장 최근 다운로드 완료 시간 표시. 백엔드 신규 기능 필요 — 현재 DB에 다운로드 완료 시간 저장소 없음 (`master_stocks_table.date`/`stock_5d_bars.dt`는 거래일이지 다운로드 시각 아님). 사전조사: 다운로드 파이프라인 완료 지점, 저장소 설계(system_state_cache 또는 신규 테이블), P10 SSOT/P22 정합성 점검 후 설계 제안.
- 실전모드 보관 기준(`RETENTION_TRADING_DAYS_REAL = 90`) 추후 논의 — 사용자가 "증권사 서버에 데이터가 다 있으니 추후 논의"라고 명시.
- 기존 발견 문제: `notify_raw_real_data` dead code (P16) 별도 검토 필요 시 사용자 지시.
- 사용자 UI 확인 후 추가 컬럼 너비 조정이 필요하면 해당 페이지만 override로 진행.

## 현재 상태

### 1. 조사 범위
| 화면 | 파일 | 종류 |
|---|---|---|
| 매수 후보 | `frontend/src/pages/buy-target.ts` | DataTable |
| 보유 종목 | `frontend/src/pages/sell-position.ts` | DataTable |
| 수익 상세(매수/매도/드릴다운) | `frontend/src/pages/profit-detail.ts`, `frontend/src/pages/profit-shared.ts` | DataTable |
| 종목 상세 5일 데이터 | `frontend/src/pages/stock-detail.ts` | DataTable |
| 업종별 종목 시세 | `frontend/src/pages/sector-stock.ts` | DataTable |
| 업종 분류(검색/업종목록/종목목록) | `frontend/src/pages/stock-classification.ts` | DataTable |
| 일반 설정 명령어 안내 | `frontend/src/pages/general-settings.ts` | DataTable |
| 업종 순위 리스트 | `frontend/src/pages/sector-ranking-list.ts` | HTML div/flex |
| 수익 현황 업종별 종목 | `frontend/src/pages/profit-overview.ts` | HTML div/flex |

### 2. 핵심 공통 자산
- `frontend/src/components/common/table-config.ts` — `ColumnType`, `COLUMN_WIDTH`
- `frontend/src/components/common/data-table.ts` — `DataTable`, `ColumnDef`, `createColumnWidthManager`
- `frontend/src/components/common/auto-width.ts` — `estimateTextWidth`, `computeColWidths`, `widthsToPercentages`, `KOREAN_SCALE`
- `frontend/src/components/common/ui-styles.ts` — 셀 스타일, 공통 컬럼 팩토리

### 3. DB 데이터 특성
- `master_stocks_table.name`: 최대 14자, 평균 4.8자, 99% ≤ 9자
- `master_stocks_table.sector`: 최대 13자, 평균 6.8자
- `master_stocks_table.code`: 6자
- `stock_5d_bars.trade_amount`: 최대 33,936,947 (8자리)
- `stock_5d_bars.high_price`: 최대 3,015,000 (7자리)
- `trades.price`: 최대 1,858,500 (7자리)
- `trades.qty`: 최대 532 (3자리)
- `trades.total_amt`: 최대 5,128,949원
- `trades.fee`: 최대 771원
- `trades.tax`: 최대 10,280원
- `trades.realized_pnl`: 최대 157,700원
- `trades.pnl_rate`: 최대 5.47%

### 4. 해결된 문제
- `종목명` 컬럼이 전체 테이블에서 과도하게 넓게 표시되던 문제.
  - 원인: `auto-width.ts`의 `estimateTextWidth`가 한글 폭을 `fontSize * 0.75 * 1.8`로 과대 추정하고, `ColumnDef`의 `minWidth`/`maxWidth`가 페이지별로 제각각이며, `종목명`의 `maxWidth`가 200으로 큼.
  - 조치: `KOREAN_SCALE` 1.4 조정, `COLUMN_WIDTH` 표준 상수 적용, `종목명` `maxWidth` 140으로 축소.
- 숫자 컬럼(`현재가`, `거래대금(억)`, `대비`, `체결강도` 등)이 `maxWidth` 80~95에 묶여 있던 문제.
  - 조치: `ColumnType`별 표준 `minWidth`/`maxWidth` 적용, `type` 필드 추가로 `createColumnWidthManager`가 자동 적용.
- 매수후보/업종별종목실시간시세에서 숫자 컬럼이 과도하게 넓고 종목명이 좁은 문제.
  - 조치: 페이지 override로 숫자 컬럼 축소, 종목명 확대.
- 프순매 컬럼 단위 표기 누락 (P23 일관성 위반).
  - 조치: "프순매" → "프.순.매(백)" 라벨 변경, 너비 조정.
- 호가잔량비 글자와 숫자가 붙어 있어 행 간 비교 어려움 + % 단위 반복 표시.
  - 조치: flex container로 좌/우 분리 정렬, %는 컬럼명으로 이동, 보합 케이스 추가.

## 미해결 문제

### P-NEW-1: 가산점 입력창 직접 타이핑 시 슬라이더/저장값 범위 불일치 (P10 SSOT)

**현상**: 업종순위 설정 패널 ④ 가산점 가중치 조절 (3단계) 섹션의 3개 입력창에 -150 등 범위 밖 값을 직접 타이핑하면, 입력창·저장값은 -150이 되나 슬라이더는 브라우저 `<input type="range">`에 의해 -100으로 clamp되어 표시됨. ▲/▼ 버튼은 이번 세션에서 -100~+100 clamp 적용 완료되었으나, 직접 타이핑 경로는 미처리.

**근본 원인**: `frontend/src/components/common/setting-row.ts:224-228` — `createNumInput`의 `input` 이벤트 핸들러가 `Number(raw) || 0`로 변환만 하고 `min`/`max` clamp 없이 `options.onChange(currentValue)` 호출. 반면 슬라이더(`<input type="range">`)는 브라우저가 자체 clamp. 같은 값(`sector_bonus_*_slider`)의 허용 범위가 입력창(무제한)과 슬라이더(-100~+100) 두 경로에서 불일치 (P10 SSOT 위반).

**수정 방안 (제안)**: `createNumInput`의 `input` 이벤트 핸들러 및 `setValue`에 `min`/`max` clamp 추가. 단, 타이핑 도중 중간 상태(`-`만 입력 시 `Number('-')=NaN → 0` 튐)는 별도 처리 필요 — blur 시점에만 clamp 적용하는 방식이 P21(사용자 편집 보호)과 양립 가능.

**영향 범위**: 프론트엔드 1개 파일 (`setting-row.ts`). 기존 호출부 동작 보존 필요 (min/max 미지정 시 clamp 무효).

**위반 원칙**: P10 (SSOT — 가산점 값 허용 범위가 입력창 타이핑 경로와 슬라이더 경로에서 불일치).

---

### P-001: 실시간 데이터 미수신 시 0 폴백 → 수신률 100% 왜곡 + 업종 점수 왜곡

**현상**: HD현대 등 종목의 실시간 데이터 필드가 0 또는 "-"로 표시되는데, 업종순위 계산 임계치 수신률은 100%로 표시됨. 사용자 지적: "0을 데이터로 인식해서 왜곡".

**근본 원인 (2단계 연쇄, 코드 경로로 모두 확정)**

#### 원인 A — 미수신 데이터를 0으로 폴백 저장 (P20 폴백 금지 위반)
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/services/engine_ws_parsing.py:155-156` | `parse_change_rate_to_percent(None)` → `0.0` 반환. 빈 문자열·"0"도 모두 `0.0` 반환. |
| `backend/app/services/engine_account_rest.py:21-22` | `_parse_float_loose(None)` → `0.0` 반환. |
| `backend/app/services/engine_radar.py:75` | 틱 수신 시 FID 12(등락률) 값이 비어 있으면 `parse_change_rate_to_percent`를 거쳐 `entry["change_rate"] = 0.0` 저장. None이 아닌 0.0 저장. |
| `backend/app/services/engine_radar.py:77` | 틱 수신 시 FID 14(거래대금) 값이 비어 있으면 `_parse_float_loose`를 거쳐 `entry["trade_amount"] = 0` 저장. None이 아닌 0 저장. |

#### 원인 B — 수신률 계산이 0과 None을 구분하지 않음 (P22 데이터 정합성 위반)
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/pipelines/pipeline_compute.py:97` | `_has_any_realtime_data()`가 `entry.get(f) is not None`로만 판정. `0.0`/`0`은 None이 아니므로 "수신됨"으로 카운트. |
| `backend/app/pipelines/pipeline_compute.py:118-126` | `received_count`에 0으로 폴백된 종목이 포함됨. 결과: 실제 수신되지 않은 종목이 수신률 100%에 포함. |

**수신률 100%가 업종순위 계산 시작 조건과 연결되는 경로 (확정)**
1. `pipeline_compute.py:704` — Phase 1 루프에서 `_calculate_receive_rate()` 호출.
2. `pipeline_compute.py:706` — `_current_receive_rate["pct"]`를 `current_pct`로 읽음.
3. `pipeline_compute.py:716` — `if current_pct >= threshold_pct:` 수신률이 임계값 이상이면 통과.
4. `pipeline_compute.py:721` — `mark_sector_threshold_passed()` 호출 → 이후 sector-scores 전송 허용.
5. `pipeline_compute.py:722` — `request_sector_recompute(None)` 호출 → 콜드 스타트 1회 전체 재계산 트리거.
6. `engine_account_notify.py:273-276` — `is_sector_threshold_passed()`가 False면 sector-scores 전송 차단, True면 허용.

**확정된 사실**: 0으로 폴백된 종목이 수신률을 100%로 끌어올리고, 100%가 임계값 통과 조건이 되어 업종순위 계산이 시작됨. 실제로는 데이터가 부족해도 임계값이 통과됨.

**0이 섞인 데이터가 업종 점수 계산에 미치는 영향 (확정)**
| 코드 경로 | 확인된 사실 |
|---|---|
| `backend/app/domain/sector_calculator.py:69` | `change_rate = float(detail.get("change_rate", 0) or 0)` — 0이 유효 데이터로 StockScore에 저장. |
| `backend/app/domain/sector_calculator.py:78` | `ta = int(detail.get("trade_amount", 0) or 0)` — 0이 유효 데이터로 StockScore에 저장. |
| `backend/app/domain/sector_calculator.py:129` | `raw_rise_count = sum(1 for s in filtered_stocks if s.change_rate > 0)` — 0은 상승 종목에서 제외되어 `rise_ratio`(상승비율)를 낮춤. |
| `backend/app/domain/sector_calculator.py:132-133` | `raw_total_ta = sum(s.trade_amount ...)` → `avg_ta = raw_total_ta // raw_total` — 0이 거래대금 합산에 포함되어 `avg_trade_amount`를 낮춤. |
| `backend/app/domain/sector_calculator.py:134` | `avg_cr = sum(s.change_rate ...) / len(filtered_stocks)` — 0이 평균 등락률에 포함되어 `avg_change_rate`를 낮춤. |
| `backend/app/domain/sector_score.py:106-107` | `rise_values = [sc.rise_ratio ...]` → 1차 가산점(상승비율 순위) 계산에 0으로 왜곡된 `rise_ratio` 사용. |
| `backend/app/domain/sector_score.py:112-113` | `ta_values = [float(sc.avg_trade_amount) ...]` → 3차 가산점(거래대금 순위) 계산에 0으로 왜곡된 `avg_trade_amount` 사용. |
| `backend/app/domain/sector_score.py:142` | `all_entries.append((stock.change_rate, sc.sector))` → 2차 가산점(가중 순위 합)에 0인 `change_rate` 포함. |

**확정된 사실**: 0으로 폴백된 데이터가 1차·2차·3차 가산점 모두에 영향을 줌. 업종 점수 순위가 왜곡됨.

**현재가 0 표시 경로 (확정)**
- 틱 처리 `pipeline_compute.py:553` — `last_px <= 0`이면 틱 차단. 틱 경로로는 0이 들어가지 않음.
- 현재가 0은 초기 스냅샷/REST 로드 시점에 0으로 저장된 것이 화면에 남아있는 상태에서, 이후 해당 종목으로 틱이 아직 수신되지 않았을 때 발생.

**수정계획서**: `docs/plan_P001_fix.md` (2026-07-15 작성 완료)

**진행 상황**:
- **Step 1 완료 (2026-07-15)**: `engine_radar.py:73-77` 틱 수신 폴백 제거. 빈 FID 12/14 → None 유지. 검증 완료 (py_compile + 테스트 107개 통과 + 런타임 기동 정상).
- **Step 2 대기**: `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + 수신률 판정 검증.
- **Step 3 대기**: `sector_calculator.py:69,78` 업종 점수 폴백 제거.

**수정 방안 (수정계획서 기반)**
- **원인 A 해결 (Step 1, 2)**: `parse_change_rate_to_percent`·`_parse_float_loose` 자체는 변경하지 않음(REST 경로 호환성). 틱 수신 경로(`engine_radar.py:73-77`, `pipeline_compute.py:576`)에서 빈 문자열 체크 후 None 저장. (P20 폴백 금지 준수)
- **원인 B 해결 (Step 2)**: `_has_any_realtime_data`(`pipeline_compute.py:97`)는 `is not None` 체크 유지. 원인 A 수정 후 None이 저장되므로 `!= 0` 불필요. (정상 0% 등락률 오분류 방지)
- **업종 점수 왜곡 해결 (Step 3)**: `sector_calculator.py:69,78`에서 None을 0으로 폴백하지 않고 None 유지. 미수신 종목(change_rate 또는 trade_amount가 None)은 점수 계산에서 제외. (P22 데이터 정합성 준수)
- **연쇄 영향 조사 완료**: `parse_change_rate_to_percent` 호출처 2곳(둘 다 틱 경로), `_parse_float_loose` 호출처 6곳(1곳 틱, 5곳 REST), `sector_calculator.py` None 폴백, `trading.py` None 안전, 프론트엔드 null 안전, 보유종목 평가 안전. 상세는 수정계획서 섹션 2 참조.

**세션 분할 (수정계획서 기반)**
- Step 1 (세션 1): `engine_radar.py:73-77` 틱 수신 폴백 제거. 영향 범위 좁음.
- Step 2 (세션 2): `pipeline_compute.py:576` 보유종목 틱 폴백 제거 + 수신률 판정 검증. 영향 범위 중간.
- Step 3 (세션 3): `sector_calculator.py:69,78` 업종 점수 폴백 제거. 영향 범위 넓음.
- **HANDOVER 원안 대비 변경**: 원안(1단계=원인 B, 2단계=원인 A)은 정상 0% 등락률 오분류 결함이 있어 순서 변경. 원안의 `!= 0` 판정식도 동일 이유로 제거.

**검증 방법 (수정 후)**
- 백엔드 런타임 기동 후, 틱이 일부만 수신된 상태에서 수신률이 100%가 아닌 실제 비율로 표시되는지 확인.
- 화면에서 0/- 로 표시되던 종목이 데이터 미수신 시 일관되게 "-"로 표시되는지 확인.
- 업종 점수 순위가 0 왜곡 없이 계산되는지 확인.

**관련 원칙**: P10(SSOT), P20(폴백 금지), P21(사용자 투명성), P22(데이터 정합성), P23(일관성).
**조사 세션**: 2026-07-15.

## 참고 사항
- `master_stocks_table`의 `cur_price`, `change`, `change_rate`, `trade_amount`는 현재 스냅샷에서 비어 있어, 수치 기준은 `stock_5d_bars`와 `trades`를 사용함.
- `auto-width.ts`의 `KOREAN_SCALE` 조정은 너비 추정 정확도에 큰 영향을 줌. 변경 없이는 `종목명` 9자만 되어도 150px 이상을 요구해 공간 낭비가 큼.
- `sector-ranking-list.ts`와 `profit-overview.ts`는 `DataTable`이 아니므로 별도 처리 필요.
- 컬럼 너비 공통 상수(`COLUMN_WIDTH`)는 min/max px 경계값이며, 실제 비율은 데이터 기반 px→% 정규화로 페이지별 컬럼 구성에 자동 적응함. per-page override는 `ColumnDef`의 `minWidth`/`maxWidth` 필드로 이미 지원.
