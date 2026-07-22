# SectorFlow Handover

## 직전 완료 작업 (최근 2건)
- **2026-07-22 (최근)**: NXT 메인마켓 미갱신 수정 — 타임테이블 초 단위 지원 확장 + 09:00:30 phase 이벤트 추가. **수정 파일 2개** (백엔드 1 + 테스트 1): `backend/app/services/daily_time_scheduler.py`, `backend/tests/test_daily_time_scheduler.py`. **근본 원인 (이전 조사 확정)**: NXT 메인마켓 개시 JIF(`jangubun=6, jstatus=21`)가 증권사에서 수신되지 않음. 타임테이블이 `(h, m)` 분 단위만 지원하여 09:00:30 초 단위 이벤트 추가 불가 → JIF 누락 시 시간표 보완 경로가 메인마켓 전환 수행 못함 (약 51분간 UI에 "정규장 준비" 잘못 표시). **수정 내용**: (1) 상수 `NXT_MAINMARKET_START=(9,0,30)` 추가 — 기존 `NXT_PREP_NONE_END` + `NXT_MAINMARKET_START_SECOND`에서 파생 (P10 SSOT). (2) 헬퍼 `_to3()` (2-tuple→3-tuple 정규화) + `_fmt_hms()` (s=0→"HH:MM", s≠0→"HH:MM:SS") 추가. (3) `build_timetable_from_cache()` 모든 entry time을 `(h, m, s)` 3-tuple로 통일 + 09:00:30 NXT 메인마켓 phase 엔트리 신규 추가 (KRX 09:00 이후) — 항목 수 11→12 (toggle ON). (4) `_schedule_next_timetable_event()` `h, m = entry["time"]` → `h, m, s = entry["time"]`, `event_sec = h*3600 + m*60 + s` 초 단위 지원 + fallback path 3-tuple 대응. (5) 테스트 갱신 — 항목 수/인덱스 shift/3-tuple assertion + `_to3`/`_fmt_hms` 헬퍼 테스트 4개 + 09:00:00→09:00:30 예약(delay=30s) + 09:00:15→09:00:30 예약(delay=15s) 신규 테스트 2개. **검증**: pytest 2789 passed (2783+6 신규) / 0 failed, `python -W error::RuntimeWarning main.py` 기동 성공 RuntimeWarning 0건 — `[기동] 타임테이블 빌드 완료 — 12항목` + `[기동] 장 상태 계산 완료 | KRX: 정규장, NXT: 메인마켓` 로그 확인. **UI에서 달라지는 점**: NXT 칩이 09:00:30에 "정규장 준비"(회색) → "메인마켓"(초록)으로 JIF 수신 여부와 무관하게 정확히 전환 (이전: JIF 미수신 시 09:51:46 재기동 전까지 약 51분간 회색 고정). **거래 영향 없음**: `is_order_blocked_by_time()`이 KRX 활성 시 무조건 허용.
- **2026-07-22 (이전)**: NXT 메인마켓 미갱신 심층 조사 — 공식 시간 확인 + 실제 로그 검증 + jangubun=E 정체 확인 (코드 수정 없음 — 조사 전용). **수정 파일 1개** (문서 1파일): `HANDOVER.md`. **조사 1 (공식 개시 시간)**: nextrade.co.kr 공식 3곳(marketOverview, transactionSys, main) 모두 메인마켓 09:00:30~15:20 확인 — `NXT_MAINMARKET_START_SECOND=30` 상수 정확. KRX 09:00:00 vs NXT 09:00:30 차이는 공식 스펙 (KRX 시가 동시호가 체결 후 30초 대기). **조사 2 (로그 출력)**: JIF 수신 로그는 INFO 레벨(`engine_ws_dispatch.py:279`)로 정상 출력 중 — DEBUG→INFO 승격 불필요. `trading_2026-07-22.log`에서 24건 JIF 수신 확인. **조사 3 (실제 JIF 수신 패턴)**: 08:00:00 `jangubun=6, jstatus=55`(프리마켓 개시) ✅, 08:50:00 `jangubun=6, jstatus=57`(프리마켓 마감→정규장 준비) ✅ — 정상 수신. 그러나 **09:00:00~09:51:46 구간에 `jangubun=6` JIF가 단 한 건도 수신되지 않음** ❌. 09:00:00에 `jangubun=1/2, jstatus=21`(KRX 장시작)만 수신 → `[장상태] NXT: 정규장 준비 유지` 로그 확인. 09:51:46 엔진 재기동 시 `calc_timebased_market_phase()`가 09:00:30 이후이므로 NXT="메인마켓" 산정 → 우연히 해결 (약 51분간 잘못 표시). **조사 4 (jangubun=E 정체)**: `docs/api_specs/LS증권API/websocket/실시간/장운영정보JIF.txt` line 104 명시 — `E:일본주식오전`. 09:00:01.431 수신된 `jangubun=E, jstatus=21`은 일본주식 오전장 개시이며 NXT 메인마켓과 무관. 현재 코드에서 정상적으로 무시됨. **근본 원인 확정**: NXT 메인마켓 개시 JIF(`jangubun=6, jstatus=21`)가 증권사(키움)에서 수신되지 않음. 시간 기반 보완 경로(타임테이블)에 09:00:30 phase 이벤트가 없어 JIF 누락 시 메인마켓 전환 불가. **수정 방안 확정**: 타임테이블 `(h, m)` → `(h, m, s)` 초 단위 지원 확장 + 09:00:30 NXT 메인마켓 phase 이벤트 추가. **검증**: 문서 전용 변경이므로 런타임/빌드 검증 생략. **UI에서 달라지는 점**: 없음 — HANDOVER 문서 갱신만.

## 현재 상태 (빌드/테스트 스냅샷)
- **백엔드**: pytest 2789 passed / 0 failed
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

### 기타 대기 항목 (2026-07-22 — 3건 잔여)
- **다운로드 완료 시간 표시 (제안2)**: 2026-07-22 심층 조사 완료 — 유효 (미구현 제안). **현황**: 다운로드 완료 시간을 추적/저장하는 메커니즘 없음. `engine_state`에 `confirmed_refresh_running_confirmed`/`confirmed_refresh_running_5d`(bool, 진행 중 여부) + `last_confirmed_download_date`(YYYYMMDD, 시간 정보 없음)만 존재. `confirmed-progress` WS 메시지로 진행률 전송하나 완료 시 `status: "completed"` 후 프론트엔드에서 3초 후 자동 숨김 (uiStore.ts:103-111) — 영구 저장 없음. `download-data-exists` API는 데이터 존재 여부만 반환 (완료 시간 미포함). **구현 필요**: 백엔드 완료 시각 저장 필드/상태 + 프론트엔드 버튼 우측 표시 UI.
- **실전모드 보관 기준** (`RETENTION_TRADING_DAYS_REAL = 90`): 2026-07-22 심층 조사 완료 — 유효 (정책 논의 대상). `trade_history.py:32`에 정의, 주석에 "추후 논의 대상" 명시. `_trim_expired()`에서 `get_recent_trading_days(90)`로 컷오프 계산 후 `trade_mode='real' AND date < cutoff` 레코드 삭제 (메모리+DB 동시 정리). 테스트모드는 달력 6개월(`RETENTION_MONTHS_TEST=6`). 90거래일 ≈ 4.5개월. 코드 구현 완료·동작 중이나 보관 기간 적절성 논의 필요.
- **추가 컬럼 너비 조정**: 2026-07-22 심층 조사 완료 — 유효 (사용자 UI 확인 대기). **현황**: 컬럼 너비 시스템 구축 완료 — `table-config.ts` COLUMN_WIDTH(42개 타입 min/max px) + `auto-width.ts`(KOREAN_SCALE=1.4 데이터 기반 자동 폭) + `data-table.ts` ColumnDef.minWidth/maxWidth per-page override 지원. `createDataTable` 사용 8페이지(general-settings, sector-ranking-list, sector-stock, sell-position, profit-detail, stock-classification, buy-target, stock-detail). `profit-overview.ts`는 여전히 flex 기반 수동 레이아웃 (createDataTable 미사용, 별도 처리 필요 시 별도 세션). 사용자 UI 확인 후 특정 페이지 컬럼 너비 부적절 시 ColumnDef override로 조정 가능.

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
