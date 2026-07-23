# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. **인덱스 역할만 수행** (규칙 8-2). 상세 구현 내역은 git 커밋 메시지 + docs/ 참조.

---

## 세션 개요

| 날짜 | 세션 | 작업 | 상태 |
|------|------|------|------|
| 2026-07-24 | NWS-S5 | 실시간 뉴스(NWS) 매수 가산점 프론트엔드 매수설정+매수후보 테이블 (다단계 워크플로우 5세션) — P21/P23/P24/P25 | 완료 (6세션 대기) |
| 2026-07-24 | NWS-S4 | 실시간 뉴스(NWS) 매수 가산점 백엔드 가산점 로직+설정 구현 (다단계 워크플로우 4세션) — P10/P13/P15/P16/P20/P21/P23/P24/P25 | 완료 (5세션 대기) |
| 2026-07-24 | NWS-S3 | 실시간 뉴스(NWS) 매수 가산점 백엔드 NWS 인프라 구현 (다단계 워크플로우 3세션) — P4/P7/P10/P11/P13/P16/P20/P21/P23/P25 | 완료 (4세션 대기) |
| 2026-07-24 | NWS-S2 | 실시간 뉴스(NWS) 매수 가산점 심층 사전조사 + 태스크 파일 작성 (다단계 워크플로우 2세션) — P4/P7/P10/P11/P13/P15/P16/P20/P21/P22/P23/P24/P25 | 사전조사+태스크 완료 (구현 대기) |
| 2026-07-23 | NWS-S1 | 실시간 뉴스(NWS) 매수 가산점 설계 — 디자인 파일 작성 (다단계 워크플로우 1세션) — P4/P7/P10/P11/P13/P15/P16/P20/P21/P22/P23/P24/P25 | 설계 완료 (구현 대기) |
| 2026-07-23 | T4-S01 | 매수설정 거래대금 순위 가산점 + 매수후보 거래대금 컬럼 제거 — P16/P21/P24 | 완료 |
| 2026-07-23 | MEM-01 | 메모리 문제해결 참고서 고유 내용 스킬 이관 + 메모리 삭제 — P10 SSOT | 완료 |
| 2026-07-23 | T3-S32 | 체결강도 매수차단 제거 문서 정리 (다단계 워크플로우 세션 5) — P10/P16/P21/P23/P24 | 완료 |
| 2026-07-23 | T3-S31 | 체결강도 매수차단 제거 프론트엔드 구현 (다단계 워크플로우 세션 4) — P16/P21/P23/P24 | 완료 |

> 체결강도 매수차단 제거 다단계 워크플로우(세션 1~5) 전체 완료. 계획서/설계 문서는 규칙 11에 따라 삭제됨.
> P25 전수 조사(9세션) + 수정(Tier 1/2/3, 17세션) 전체 완료. 조사 보고서 `docs/p25_isolated_failure_investigation.md`는 역사적 기록으로 유지.

---

## 직전 완료 작업

### NWS-S5 실시간 뉴스(NWS) 매수 가산점 프론트엔드 매수설정+매수후보 테이블 (2026-07-24)
- **작업**: 다단계 워크플로우 5세션(프론트엔드 매수설정+매수후보 테이블). 사전조사 중 태스크 파일에 누락된 의존성 1건 발견 — `table-config.ts`의 `ColumnType`에 `'news'` 타입이 없어 `buy-target.ts`에서 `type: 'news'` 사용 시 typecheck 실패. 태스크 파일 3파일 + 사전조사 발견 1파일 = 4파일 수정. 기존 3개 가산점 행 패턴 그대로 4번째 행 추가 (P23 일관성), 기존 공통 자산 재사용 (`createNumInput`, `createToggleLabelControlsRow`, `COLOR.up`, `FONT_SIZE.body`, `FONT_WEIGHT.bold`).
- **수정**: 프론트엔드 4파일 — `types/index.ts` (AppSettings 4키 + SectorStock news_boost 필드), `table-config.ts` (ColumnType 'news' + COLUMN_WIDTH 정의), `buy-settings.ts` (모듈 상태 3개 + syncBoost 뉴스 동기화 + buildBoostSection 4번째 행 + unmount null 처리), `buy-target.ts` (📰뉴스 컬럼 5일고가 앞)
- **영향 범위**: 매수설정 "매수 가산점 (+N)" 섹션 4번째 줄 "📰 뉴스 호재" 추가, 매수후보 표 "프.순.매"와 "5일고가" 사이에 "📰뉴스" 컬럼 추가. 기본값 `boost_news_on=False`이므로 사용자가 매수설정에서 켜기 전까지 기존 동작 유지. 거래 로직 변경 없음 (P15). DB 스키마 변경 없음.
- **사용자 결정**: table-config.ts 포함 4파일 계획 승인
- **검증**: typecheck 통과 / build 성공 (603ms, 77 modules, 타입 오류 없음) / lint 스크립트 package.json에 없음 (기존과 동일) / 개발 서버 5173 실행 중 (브라우저 확인 가능)

### NWS-S4 실시간 뉴스(NWS) 매수 가산점 백엔드 가산점 로직+설정 구현 (2026-07-24)
- **작업**: 다단계 워크플로우 4세션(백엔드 가산점 로직+설정). `news_boost_cache` → 매수 가산점 반영 + 설정 기본값/검증/동기화. 사전조사 중 태스크 파일의 동기화 위치 오류 발견 — 태스크 파일은 `engine_state.py`에 동기화하라고 기재했으나, `integrated_system_settings_cache` 갱신은 `engine_config.py`의 `refresh_engine_integrated_system_settings_cache()`에서 단일 소스로 수행 (P10/P17). 사용자 승인 하에 `engine_config.py`로 정정. 추가로 초기 기동 시 `app.py`에서도 동기화 필요 → `_sync_nws_settings_to_state()` 헬퍼로 추출하여 양쪽에서 호출 (P10 SSOT — 단일 로직, P24 단순성 — 중복 제거).
- **수정**: 백엔드 7파일 — `buy_filter.py` (4번째 가산점 로직 + `create_buy_targets` 파라미터 + `build_buy_targets_from_settings` 전달), `sector_data_provider.py` (매수후보 `news_boost` 필드, `get_news_boost_cache()` 한 번 조회 후 전달 P7), `engine_settings.py` (`_build_boost_settings()` NWS 설정 4개), `settings_defaults.py` (NWS 기본값 4개), `settings_store.py` (`_validate_numeric_fields()` NWS 검증 3개), `engine_config.py` (`_sync_nws_settings_to_state()` 헬퍼 + `refresh_engine_integrated_system_settings_cache()` 내 호출), `app.py` (초기 기동 시 헬퍼 호출)
- **영향 범위**: 매수 가산점 4번째 "📰뉴스 호재" 추가. 기본값 `boost_news_on=False`이므로 사용자가 매수설정에서 켜기 전까지 기존 동작 유지. 거래 로직 변경 없음 (P15). DB 스키마 변경 없음 (설정 키만 `integrated_system_settings` 테이블에 증분 추가).
- **사용자 결정**: 동기화 위치 `engine_config.py`로 정정 승인
- **검증**: py_compile 통과 / ruff 통과 / mypy 신규 에러 없음 / 런타임 기동 정상 (197ms, RuntimeWarning 없음) / 잔존 프로세스 0건 / 기존 테스트 2834개 통과 / buy_filter 테스트 54개 통과

### NWS-S3 실시간 뉴스(NWS) 매수 가산점 백엔드 NWS 인프라 구현 (2026-07-24)
- **작업**: 다단계 워크플로우 3세션(백엔드 NWS 인프라 구현). NWS 메시지 수신 → `news_boost_cache` 갱신 경로 구축. 사전조사 중 태스크 파일의 디스패치 위치 오류 발견 — NWS는 JIF와 동일하게 tick_queue 우회하여 `engine_ws_dispatch.py` 경로로 처리되나, 태스크 파일은 `pipeline_compute.py`에 분기를 넣도록 잘못 기재 (죽은 코드 P16 위반 발생). 설계서 섹션 3.7.1이 이미 "디스패치 위치 확인 필요"로 명시했으나 태스크 작성 시 확인 누락. 사용자 승인 하에 바로잡아 진행: `pipeline_compute.py` 제외, `engine_ws.py` + `engine_ws_dispatch.py` 추가.
- **수정**: 백엔드 6파일 — `ls_connector.py` (NWS 구독/변환/우회/재연결 6곳), `pipeline_compute_tick_handlers.py` (`_handle_nws_news()` 핸들러), `engine_ws.py` (trnm 필터 NWS 추가), `engine_ws_dispatch.py` (NWS 디스패치), `engine_state.py` (캐시 필드 4개), `engine_radar.py` (`get_news_boost_cache()` getter)
- **영향 범위**: NWS 수신 경로 구축만 (가산점 계산 연결은 4세션). 거래 로직 변경 없음 (P15). DB 스키마 변경 없음.
- **사용자 결정**: 태스크 파일 디스패치 위치 오류 바로잛아 진행 승인
- **검증**: py_compile 통과 / ruff 통과 / mypy 신규 에러 없음 / 런타임 기동 정상 (157ms, RuntimeWarning 없음) / 잔존 프로세스 0건 / 기존 테스트 2834개 통과 / NWS 핸들러 기능 테스트 6개 통과

### NWS-S2 실시간 뉴스(NWS) 매수 가산점 심층 사전조사 + 태스크 파일 작성 (2026-07-24)
- **작업**: 다단계 워크플로우 2세션(설계 기반 심층 사전조사 + 태스크 파일 작성). 규칙 0-2 4항목 의존성/영향범위/원칙부합/공통자산 조사. 백엔드 10파일+프론트엔드 4파일+신규 1파일(tag-chip.ts)+테스트 1파일 변경점 식별. 기존 공통 자산 재사용 확인(subscribe_jif 패턴, get_program_net_buy_cache 패턴, calculate_boost_score 패턴, createToggleLabelControlsRow/createNumInput 등). tag-chip 컴포넌트는 기존에 없어 신규 생성 필요. 5세션(3~7세션) 단계 분할 확정.
- **산출물**: `docs/plan_news_boost.md` (태스크 파일 — 3세션: 백엔드 NWS 인프라 / 4세션: 백엔드 가산점 로직+설정 / 5세션: 프론트엔드 매수설정+매수후보 테이블 / 6세션: 프론트엔드 일반설정 키워드 칩+TTL / 7세션: 테스트+런타임 검증)
- **사용자 결정**: 5세션 단계 분할 승인
- **검증**: 코드 수정 없음(사전조사+태스크만) / 커밋 대기

### NWS-S1 실시간 뉴스(NWS) 매수 가산점 설계 — 디자인 파일 작성 + 보완 (2026-07-23)
- **작업**: 다단계 워크플로우 1세션(설계 검토 + 디자인 파일 작성). 정적 키워드 사전 + 매수 가산점 전용 방향 설계. LLM 분류/악재 자동 손절/본문 2차 조회는 제외. 사용자 보완 요청 2건 반영(매수후보 테이블 📰뉴스 컬럼 추가 + 일반설정 키워드 칩 편집 UI).
- **산출물**: `docs/architecture_news_boost_design.md` (설계서 — 백엔드 10파일 + 프론트엔드 4파일 + 테스트 1파일 변경 설계, P4/P7/P10/P11/P13/P15/P16/P20/P21/P22/P23/P24/P25 부합 검토 포함)
- **사용자 결정**: 점수 유지 5분 / 키워드 편집 일반설정 자동매매 탭 / 키워드 칩+기본값 미리 채움 / 매수후보 내 종목만 / 📰뉴스 컬럼 5일고가 왼쪽 / LLM·악재손절 제외
- **검증**: 코드 수정 없음(설계만) / 커밋 대기

### T4-S01 매수설정 거래대금 순위 가산점 + 매수후보 거래대금 컬럼 제거 — 완료 (2026-07-23)
- **사유**: 업종순위 1차 5일평균 최소거래대금 필터로 이미 일정 수준 이상 종목만 매수후보 풀 진입. 매수후보 내 당일 거래대금 1위 1종목 가산점은 효과 범위 좁고 한계 효과. 당일 실시간 거래대금 컬럼도 다른 컬럼으로 종목 판단 충분 → 사용자 투명성(P21) 위반 아님.
- **수정**: 백엔드 7파일(buy_filter.py 가산점 로직/순위계산/파라미터, models.py 필드, engine_settings.py/settings_defaults.py 설정 키, sector_data_provider.py/engine_account_notify.py/engine_service.py 참조) + 프론트엔드 5파일(buy-settings.ts 토글/UI, buy-target.ts 컬럼, hotStore.ts recalcTradeAmountRank 함수, binding.ts import, types/index.ts 타입) + 테스트 2파일(관련 케이스 5개 제거) + DB 설정 키 2개 삭제
- **영향 범위**: 매수설정 "매수 가산점" 섹션(4→3 항목), 매수후보 테이블(10→9 컬럼, 하이라이트 제거). 업종순위 페이지/5일평균 필터/업종 점수 3차 가산점은 영향 없음.
- **검증**: DB 백업(20260723_234321) / py_compile 통과 / ruff 통과 / typecheck 통과 / 빌드 성공 / 테스트 69개 통과 / 런타임 기동 정상(137ms) / 잔존 프로세스 0건

### MEM-01 메모리 문제해결 참고서 고유 내용 스킬 이관 + 메모리 삭제 — 완료 (2026-07-23)
- 수정: backend-fix SKILL.md (1파일) — Python 실시간 금지 목록 + 테스트 hang 방지 원인 A-E 추가
- 삭제: 메모리 "SectorFlow 문제해결 참고서" (고유 내용 스킬 이관 완료, 나머지 AGENTS.md/스킬과 완전 중복)
- 검증: 스킬 파일 수정 확인 / 커밋 db79a21

### T3-S32 체결강도 매수차단 제거 문서 정리 — 완료 (2026-07-23)
- 수정: ARCHITECTURE.md + p25 문서 + HANDOVER.md (3파일), 삭제: 설계/태스크 파일 (2파일)
- 검증: 잔존 참조 0건 / 커밋 3433391

---

## 다음 세션 진행 대기

**다단계 작업 진행 중 — NWS 실시간 뉴스 매수 가산점 (설계 → 태스크 → 구현)**:
- **현재 단계**: 5세션(프론트엔드 매수설정+매수후보 테이블) 완료. 6세션(프론트엔드 일반설정 키워드 칩+TTL) 대기.
- **다음 세션 작업**: 6세션 — 프론트엔드 일반설정 자동매매 탭에 호재 키워드 편집 섹션 + TTL 입력 (tag-chip.ts 신규 컴포넌트 + general-settings.ts 키워드 칩+TTL). 키워드 칩 편집 UI + 뉴스 가산점 유지 시간 입력.
- **참조 문서**: `docs/architecture_news_boost_design.md` (설계서) + `docs/plan_news_boost.md` (태스크 파일 — 6~7세션 단계별 상세)

**사용자 지시 시 진행 가능 항목 (audit 문서 잔여)**:
- B-13 보류 5건 (B13-03/04/06/07/08, LOW/INFO 등급) — `docs/architecture_audit_plan.md` 섹션 7 참조
- B21-01 보류 (암호화 폴백, 사용자 승인 대기 — 보안 동작 변화, UI 기준 설명 필요)
- F-03 보류 4건 (F03-07/08/09/10) — `docs/architecture_audit_tasks.md` F-03 섹션 참조
- F-04 잔여 파일 분할 (stock-classification.ts 1618줄, general-settings.ts 1390줄)
- F-07 미시작 (타입 및 유틸 5개 파일, 총 651줄)

**참고 문서**:
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` (역사적 기록, 유지)
- 아키텍처 감사 계획: `docs/architecture_audit_plan.md`
- 아키텍처 감사 태스크: `docs/architecture_audit_tasks.md`

---

## 미해결 문제

### P21 갭: 미노출 4개 전체 차단 사유 백엔드 WS 미브로드캐스트 (2026-07-23 T3-S21 발견)
- **파일**: `backend/app/services/trading.py:204,216,222` (`BUY_REJECT_DAILY_STATE`/`BUY_REJECT_REALTIME_LATENCY`/`BUY_REJECT_AUTO_BUY_OFF`), `trading.py` `BUY_REJECT_TEST_CASH`/`BUY_REJECT_ORDER_FAIL` (사후 사유)
- **위반/부합 원칙**: P21 (사용자 투명성) 위반 — 4개 전체 차단 사유가 백엔드에서 WS 브로드캐스트되지 않아 프론트엔드 매수상태 배지(T3-S21)에서 표시 불가.
- **증상**: 일일 매수 상태 로드 실패(`daily_state`), 실시간 지연 200ms 초과(`realtime_latency`), 테스트 예수금 검증 실패(`test_cash`), 주문 전송 실패(`order_fail`) 발생 시 매수후보 화면의 "🚦 매수상태" 배지가 "매수 가능"으로 잘못 표시됨 (실제로는 차단됨).
- **근거**: T3-S21에서 매수상태 배지 추가 시 기존 uiStore 상태만 사용하기로 함 (P10 SSOT). 이 4개 사유는 백엔드에서 WS 이벤트로 전송되지 않으므로 프론트에서 알 수 없음.
- **수정 방향**: 별도 후속 세션에서 백엔드 `trading.py`에 WS 브로드캐스트 추가. `engine_state` 기반으로 `daily_state`/`realtime_latency` 상태를 WS 이벤트(`buy_block_status` 등 신규 또는 기존 `risk_block_status` 확장)로 전송 → 프론트 uiStore에 신규 상태 추가 → 매수상태 배지 우선순위 체인에 반영. `test_cash`/`order_fail`은 사후 사유이므로 별도 알림 방식 검토 필요.

### P18 갭: 테스트/실전 한도 체크 기준 상이 (2026-07-23 T3-S19 발견)
- **파일**: `backend/app/services/trading.py:141,147` (_load_daily_buy_state), `trading.py:450-457` (매수 후 누적), `backend/app/services/trade_history.py:270,280` (record_buy total_amt)
- **위반/부합 원칙**: P18 (테스트모드 동등성) 부분 위반 — 테스트모드는 수수료 포함 한도 체크, 실전모드는 수수료 제외 한도 체크로 기준 상이.
- **증상**: 테스트모드에서는 `_daily_buy_spent`/`_symbol_daily_buy_spent`가 `total_amt`(수수료 포함) 기준으로 누적/로드되어 settlement_engine 차감 기준과 일치. 실전모드에서는 trade_history의 `fee=0`, `total_amt=price*qty`이므로 한도 누적이 수수료 제외 기준 → settlement_engine(수수료 포함 차감)과 기준 불일치. 사용자는 현재 테스트모드 운영 중이므로 기능적 문제 없음.
- **근거**: 사용자 방향 지시 — "테스트모드: 수수료 포함 한도 체크, 실전모드: 증권사 데이터 그대로 사용, 수수료 계산 로직 불필요 → 별도 처리. 지금은 테스트모드만 운영 중이므로 테스트모드 기준으로 수정. 실전모드 수수료 대응은 실전 전환 직전 별도 세션에서 처리."
- **수정 방향**: 실전 전환 직전 별도 세션에서 실전모드 수수료 대응 필요. trade_history의 실전모드 fee=0 기록 문제도 함께 검토. 실전 브로커 수수료를 trade_history에 기록하는 방식 또는 trading.py에서 실전모드에도 BUY_COMMISSION 추정치를 적용하는 방식(A-2 원안) 중 선택 필요.
- **참고**: settlement_engine.py:65,78,112는 테스트/실전 무관 항상 BUY_COMMISSION 적용 중이므로, 실전 전환 시 trading.py 한도 체크만 실전 수수료 미반영 상태가 됨.

### virtual-scroller.ts renderRow 호출부 3곳 무보호 (2026-07-23 발견)
- **파일**: `frontend/src/components/virtual-scroller.ts`
- **위반/부합 원칙**: P25 (격리된 실패) 위반 소지, P23 (일관성) — 같은 파일 내 renderRange 루프는 격리했으나 다음 3곳은 무보호 상태로 잔존:
  - `updateItems` 루프 내 renderRow 2곳 (444줄 existing 경로, 451줄 new 경로)
  - `updateItemByKey` 내 renderRow (468줄)
  - `updateItem` 내 renderRow (499줄)
- **증상**: 가상 스크롤 아이템 증분 갱신 시 한 행 renderRow throw → updateItems/updateItemByKey/updateItem 루프 중단. renderRange와 동일 패턴 적용 시 해결.
- **수정 방향**: 후속 세션에서 사용자 승인 시 동일 패턴(per-item try/catch + console.error) 적용 권장 (P23 일관성).

### data-table-fixed.ts:290 셀 렌더 에러 로그 메시지 불일치 (2026-07-23 발견)
- **파일**: `frontend/src/components/common/data-table-fixed.ts:290`
- **위반/부합 원칙**: P23 (일관성) — 사전 존재 불일치.
- **증상**: `console.error('[data-table] cell render error:', err)` — 다른 4곳은 `console.error('[DataTable] cell render error', e)` (대소문자/콜론/변수명 불일치).
- **수정 방향**: 후속 세션에서 일관성 정비 시 통일 권장.

### B1-02-07 포지션 구축 실패 시 UI 사용자 알림 누락 (2026-07-23 발견)
- **파일**: `backend/app/services/engine_lifecycle.py:38-43` (start_engine try/except), `backend/app/services/engine_state.py` (state 필드), `backend/app/services/engine_lifecycle.py:162` (get_engine_status), 프론트엔드 `frontend/src/binding.ts` (engine-ready 핸들러)
- **위반/부합 원칙**: P21 (사용자 투명성) 부분 충족 — 백엔드 try/except로 `logger.warning("[연산] 테스트모드 포지션 구축 실패 — 엔진은 계속 가동")` 로그는 활성화되었으나, 화면에 "보유 종목 불러오기 실패, 엔진은 계속 가동 중" 상태를 명시적으로 표시하는 프론트엔드 경로 미구현.
- **증상**: 테스트모드에서 `_refresh_positions_if_dirty` 실패 시 (trade_history 조회 오류 등) 엔진은 계속 가동하나, 사용자 화면에는 정상 기동과 동일하게 `engine-ready`만 표시됨. 보유 종목 목록이 비어있어 사용자가 "왜 보유 종목이 안 보이지?" 의문 가능.
- **수정 방향**: engine_lifecycle.py:38 except 블록에서 `engine_state.state`에 포지션 구축 실패 플래그 설정 → get_engine_status() 반환값에 포함 → 프론트엔드 index-data/engine-ready 핸들러에서 UI 표시 (예: 엔진 상태 칩에 경고 표시). 백엔드 + 프론트엔드 변경이 필요하므로 별도 세션에서 승인 시 진행 권장.
- **참고**: B4-06-03 "감소 모드" 화면 명시 표시 미구현(아래 항목)과 동일 성격 — 백엔드는 로그로 상태 노출, UI 표시는 별도. 두 항목을 하나의 세션에서 통합 처리 가능.

### B4-06-03 "감소 모드" 화면 명시 표시 미구현 (2026-07-23 발견)
- **파일**: `backend/app/services/engine_loop.py:35`, `backend/app/services/engine_lifecycle.py:162` (get_engine_status), 프론트엔드 `frontend/src/binding.ts:244` (engine-ready 핸들러)
- **위반/부합 원칙**: P21 (사용자 투명성) 부분 충족 — 백엔드 log-and-rethrow로 engine_loop.py:35 "감소 모드로 기동" 에러 로그는 활성화되었으나, 화면에 "감소 모드" 상태를 명시적으로 표시하는 프론트엔드 경로 미구현.
- **증상**: 종목 마스터 DB가 비어있는 치명 상황에서 백엔드는 감소 모드로 기동하나, 사용자 화면에는 정상 기동과 동일하게 `engine-ready`만 표시됨. 사용자가 "왜 종목이 안 보이지?" 의문 가능.
- **수정 방향**: engine_loop.py:35 except 블록에서 `engine_state.state`에 감소 모드 플래그 설정 → get_engine_status() 반환값에 포함 → 프론트엔드 index-data 핸들러에서 UI 표시. 백엔드 + 프론트엔드 변경이 필요하므로 별도 세션에서 승인 시 진행 권장.
