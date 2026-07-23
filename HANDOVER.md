# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. 이전 세션의 완료 작업, 현재 상태, 다음 세션에서 이어서 진행할 항목을 기록.

---

## 세션 개요

| 날짜 | 세션 | 작업 | 상태 |
|------|------|------|------|
| 2026-07-23 | T3-S18 | 수익상세 페이지 매수/매도 금액 라벨 명확화 + 승률/수익률 카드 순서 교환 (P21/P23) | 완료 |
| 2026-07-23 | T3-S16 | B5-08-01/02/04 trading.py 매매 로직 (schedule_engine_task 교체 + 평균매입가 분기 주석 + 실시간 지연 fail-closed) | 완료 |
| 2026-07-23 | T3-S15 | A3-07-08/09/10 통계 카드 / 라우트 변경 / addEventListener 격리 | 완료 |
| 2026-07-23 | T3-S14 | B3-05-03/04 silent except 제거 + exc_info 11곳 보강 | 완료 |

> P25 전수 조사(9세션) + 수정(Tier 1/2/3, 17세션) 전체 완료. 계획서/태스크 파일은 규칙 11에 따라 삭제됨. 조사 보고서 `docs/p25_isolated_failure_investigation.md`는 역사적 기록으로 유지.

---

## 직전 완료 작업

### T3-S18 수익상세 페이지 매수/매도 금액 라벨 명확화 + 승률/수익률 카드 순서 교환 — 완료 (2026-07-23) — P21 사용자 투명성 / P23 일관성 (프론트엔드, frontend-fix 스킬)

**세션**: 단일 세션. 프론트엔드 라벨/카드 순서 수정만 (로직 변경 없음).

**배경**: 수익상세 페이지 하단 통계 카드 "매수금액"이 수수료 포함임이 라벨에 명시되지 않아, 사용자가 "투자금 100만원인데 매수금액이 100만원을 초과"로 오해하는 문제. 사전 조사(코드 + DB 거래 데이터) 결과:
- orderable(주문가능금액)은 정산 엔진이 수수료 포함 차감하므로 초과하지 않음 (정상 동작).
- "매수금액 100만원 초과"는 매도 회수금을 재매수에 사용한 당일 누적 지출의 정상적 증가.
- 원인은 UI 라벨 모호성 (P21 사용자 투명성 위반) + 매수/매도 금액의 비대칭 표시 (매수는 수수료 포함, 매도는 실수령).

**작업 내용** (2건, 2개 파일):
1. **라벨 명확화 (P21/P23)** — `profit-detail-mount.ts` 하단 통계 카드 6개 라벨 + `profit-columns.ts` 매수/매도 내역 테이블 컬럼 라벨 변경:
   - 하단 통계 카드: "매수금액" → "당일 매수 지출(수수료 포함)", "매도금액" → "당일 매도 수령(실수령)"
   - 매수 내역 테이블: "매수금액" → "매수 지출(수수료 포함)"
   - 매도 내역 테이블: "매수금액" → "매수 지출(수수료 포함)", "매도금액" → "매도 수령(실수령)"
   - 보유종목 페이지의 "매수금액(수수료 포함)" 표현과 일관성 유지 (P23). 하단 통계 카드는 "당일 합계"이므로 "당일" 포함, 테이블 개별 거래 행은 "당일" 제외.
2. **승률/수익률 카드 순서 교환** — `profit-detail-mount.ts` buildStatRow 마지막 두 카드 순서 교체. `STAT_LABELS` 배열 순서 + state 참조 할당(`statAvgRateEl`/`statWinRateEl` 인덱스)을 함께 교체하여 인덱스 정합성 유지 (P22).

**수정 파일**: 2개 (프론트엔드).
- `frontend/src/pages/profit-detail-mount.ts` (STAT_LABELS 라벨 변경 + 승률/수익률 카드 순서 교환)
- `frontend/src/pages/profit-columns.ts` (BUY_COLS/SELL_COLS 컬럼 라벨 변경)

**아키텍처 원칙 부합**:
- P21 (사용자 투명성): "매수금액"이 수수료 포함인지, "매도금액"이 실수령인지 라벨에 명시. 사용자가 "투자금 100만원인데 매수금액이 100만원을 넘었다"고 오해하는 것 방지.
- P22 (데이터 정합성): 승률/수익률 카드 교환 시 라벨과 state 참조를 함께 교체하여 값이 엉뚱한 카드에 들어가지 않도록 보장.
- P23 (일관성): 보유종목 페이지 "매수금액(수수료 포함)"과 동일 표현. 하단 통계 카드(당일 합계)와 테이블(개별 거래)의 "당일" 포함/제외 기준 일관.

**영향 범위**: 프론트엔드 2개 파일. 백엔드/테스트 영향 없음. 라벨 텍스트 + 카드 순서만 변경 (로직/계산 변경 없음) → 규칙 0-4 해당 없음. 롤백 아님 (신규 라벨 명확화) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 수익상세 페이지 하단 통계 카드 6개 순서: 총 건수 / 당일 매수 지출(수수료 포함) / 당일 매도 수령(실수령) / 실현손익 / **수익률** / **승률** (기존: 승률 → 수익률 순).
- 매수 내역 탭 컬럼 헤더: "매수 지출(수수료 포함)" (기존: "매수금액").
- 매도 내역 탭 컬럼 헤더: "매수 지출(수수료 포함)" + "매도 수령(실수령)" (기존: "매수금액" + "매도금액").
- 값 자체는 변화 없음 (라벨/순서만 변경).

**검증**:
- `npm run typecheck` (tsc --noEmit) 통과 ✓
- `npm run build` (tsc -b + vite build) 통과 — 76 modules, 1.96s ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 없음.

**보류 수정안** (본 세션에서 보류, 후속 세션 대기):
- **수정안 A (한도 수수료 포함 통일)** — `_daily_buy_spent`/`_symbol_daily_buy_spent`를 수수료 포함(`total_amt`) 기준으로 변경. 한도 설정 의미가 "순수 매수가"에서 "수수료 포함 지출액"으로 변경되므로 규칙 0-4 승인 필수. **다음 세션 진행 예정**.
- **수정안 C (매수 수량 계산 수수료 반영)** — `buy_qty` 계산 시 수수료 여유분 확보. 현재 버그는 아니나 P22 강화. 별도 세션 대기.

---

### B5-08-01/02/04 trading.py 매매 로직 — schedule_engine_task 교체 + 평균매입가 분기 주석 + 실시간 지연 fail-closed — 완료 (2026-07-23) — P23 일관성 / P20 폴백 금지 / P25 격리된 실패 (Tier 3 마지막 세션, LOW 3건, 백엔드, safe-trade)

**세션**: 단일 세션. 백엔드 코드 수정 (safe-trade 스킬 + backend-fix 스킬). Tier 3 마지막 세션.

**배경**: P25 수정 계획 Tier 3 마지막 세션. A3-07-08/09/10 완료 후 진행. trading.py 매매 로직 3건 — 사전조사 → 수정 계획 보고(3건 각각 옵션 제시) → 승인(B5-08-01 진행, B5-08-02 옵션 A, B5-08-04 옵션 A) → 수정 진행.

**작업 내용** (3건, 2개 파일):
1. **B5-08-01 (LOW, P23) 완료** — `trading.py:474-482` (매수), `trading.py:663-671` (매도) `asyncio.create_task` → `schedule_engine_task` 교체. ARCHITECTURE.md 금지 패턴 2 준수. 매매 로직 변경 없음 (태스크 스케줄링 인프라만). `schedule_engine_task`가 동일 기능(create_task + add_done_callback) + 코루틴 정리(coro.close()) + 예외 로깅 보장. 테스트 패치도 함께 변경 (`test_trading.py:202`).
2. **B5-08-02 (LOW, P18) 완료 — 옵션 A (현행 유지 + 주석 명시)** — `trading.py:571-580` 평균매입가 조회 테스트/실전 분기에 주석 추가. 테스트모드는 `build_positions_from_trades`로 유령 포지션 차단 검사(qty 부족 시 매도 중단)를 수행하는 안전장치이므로 분기가 의도적임을 명시. 매매 로직 변경 없음.
3. **B5-08-04 (LOW, P20/P25) 완료 — 옵션 A (fail-closed 전환)** — `trading.py:203-213` (매수), `trading.py:705-715` (매도) 실시간 지연 체크 fail-open → fail-closed 전환. 체크 자체 실패 시 매수/매도 차단 (안전 우선). 지연 상태 확인 불가 시 시스템 장애 상황이므로 안전 차단이 합리적. **핵심 매매 로직 변경 (규칙 0-4 승인 완료)**.

**수정 파일**: 2개 (백엔드).
- `backend/app/services/trading.py` (B5-08-01 매수/매도 schedule_engine_task 교체, B5-08-02 평균매입가 분기 주석, B5-08-04 매수/매도 실시간 지연 fail-closed)
- `backend/tests/test_trading.py` (B5-08-01 패치 변경: asyncio.create_task → schedule_engine_task + MagicMock import 제거)

**아키텍처 원칙 부합**:
- P15 (단일 주문 경로): `execute_buy()`/`execute_sell()` 경로 유지. `schedule_engine_task`는 태스크 스케줄링만 변경, 주문 경로 변경 없음.
- P16 (살아있는 경로): `schedule_engine_task`의 `add_done_callback`이 실제 실행 경로에 연결됨.
- P18 (테스트모드 동등성): B5-08-02 옵션 A로 현행 유지. 테스트/실전 조회 분기는 "조회"이며 돈 I/O가 아님 — 유령 포지션 차단 검사는 테스트모드 안전장치로 명시.
- P20 (폴백 금지): B5-08-04 fail-closed로 폴백 금지 강화. 체크 실패 시 silent pass 대신 안전 차단 + 로깅.
- P23 (일관성): `schedule_engine_task` 사용으로 코드베이스 일관성 향상 (engine_sector_confirm.py:392, daily_time_scheduler.py 등 기존 패턴과 일치).
- P25 (격리된 실패): `schedule_engine_task`의 예외 처리 + 코루틴 정리 보장. fail-closed로 시스템 장애 시 안전 차단.

**안전 확인 (safe-trade 스킬)**:
- 거래 모드: **테스트모드** (코드 변경 없이 현행 유지). `is_test_mode()` 플래그로 보호됨.
- API 키 하드코딩: 없음.
- 주문 경로: `execute_buy()`/`execute_sell()` 단일 경로 유지 (P15). 테스트모드 `dry_run.fake_send_order()` / 실전 `router.order.send_order()` 2개만 허용.
- RiskManager/CircuitBreaker: `execute_buy()`/`execute_sell()` 내부 호출 유지 (P16).
- 테스트모드 동등성: 안전장치 생략 없음 (P18).
- **원칙 15/16/18 준수 여부**: 모두 준수.

**영향 범위**: 백엔드 2개 파일. 프론트엔드 영향 없음. 핵심 매매 로직 변경 (B5-08-04) — 규칙 0-4 승인 완료. 롤백 아님 (신규 보호 코드 추가 + 인프라 일관성 교체) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4 — B5-08-04 핵심 로직 변경)**:
- **정상 상황**: 변화 없음. 실시간 통신 정상 시 매수/매도 동일 동작.
- **시스템 장애 상황 (실시간 지연 상태 확인 불가)**:
  - **변경 전**: 매수/매도가 계속 진행됨 (fail-open). 지연 중단 게이트가 우회될 소지.
  - **변경 후**: 매수/매도가 차단됨 (fail-closed). 화면 상단에 "실시간 지연" 칩 표시 + 매수 후보 목록에 차단 종목 표시 안 됨. 안전 우선.
- **사용자가 확인할 수 있는 영향**: 시스템 장애 상황에서 매수 후보 목록이 비어있을 수 있음. 정상 상황에서는 변화 없음.

**검증**:
- `python -m py_compile backend/app/services/trading.py` 통과 ✓
- `python -m pytest backend/tests/test_trading.py -x -q` 통과 — 52 passed in 0.54s ✓
- `python -m pytest backend/tests/test_settlement_verification.py backend/tests/test_settlement_engine.py -x -q` 통과 — 56 passed in 0.82s ✓
- `.venv/bin/ruff check backend/app/services/trading.py backend/tests/test_trading.py` 통과 — All checks passed ✓
- `python -W error::RuntimeWarning main.py` 런타임 기동 통과 — 에러/Traceback/RuntimeWarning 없음, 220ms 기동, 정산 대조 완료(주문가능 870,541원 일치), 실시간 구독 정상 ✓

**작업 중 발견 문제**: 없음.

---

### A3-07-08/09/10 통계 카드 / 라우트 변경 / addEventListener 격리 — 완료 (2026-07-23) — P25 격리된 실패 (Tier 3 다섯째 세션, LOW 3건, 프론트엔드)

**세션**: 단일 세션. 프론트엔드 코드 수정 (frontend-fix 스킬). 세션 라벨 T3-S15.

**배경**: P25 수정 계획 Tier 3 다섯째 세션. B3-05-03/04 완료 후 진행. 사전조사 → 수정 계획 보고(87개 addEventListener 전수 조사 + 고위험 분류) → 승인(옵션 A + createSummaryCards 포함) → 수정 진행.

**작업 내용** (3건, 14개 파일):
1. **A3-07-08 (LOW) 완료** — `profit-shared.ts:76-106` createSummaryCards 4카드 루프 per-card try/catch + 더미 push. buildStatRow는 T2-S10에서 이미 완료되었으나, 동일 패턴의 createSummaryCards가 누락되어 있었음 (T2-S10 누락분 보완).
2. **A3-07-09 (LOW) 완료** — `router.ts:105-109` notifyRouteChange cb 루프 per-cb try/catch + console.error. 리스너 1(setActiveRoute) throw 시 리스너 2(settingsCard 마운트) 스킵 방지.
3. **A3-07-10 (LOW) 완료** — 87개 addEventListener 전수 조사 → 고위험 46개 식별 → 옵션 A(공통 컴포넌트 chokepoint) 적용. 6개 공통 컴포넌트 + 6개 페이지 파일에서 try/catch 적용.
   - **공통 컴포넌트 (6파일)**: button.ts(4개 click 핸들러), setting-row-inputs.ts(9개 input/change 핸들러), setting-row.ts(2개 spin 버튼), setting-row-controls.ts(2개 토글/라디오), settings-common.ts(3개 시간 선택), create-slider.ts(3개 input/commit 핸들러)
   - **페이지 고위험 (6파일)**: profit-overview-mount.ts(1개 real-data-tick), sell-position.ts(1개 real-data-tick), buy-target.ts(3개 real-data-tick/orderbook/program), sector-stock.ts(1개 real-data-tick), header.ts(3개 매매 차단 상태 칩 해제), main.ts(3개 beforeunload WS disconnect)
   - **저위험 41개 제외**: hover(mouseenter/mouseleave), scroll, mousemove, animationend, keydown-Enter/focusNext, 단순 DOM 제거 — P24 단순성 준수

**수정 파일**: 14개 (프론트엔드).
- `frontend/src/pages/profit-shared.ts` (createSummaryCards per-card try/catch + 더미 push)
- `frontend/src/router.ts` (notifyRouteChange per-cb try/catch)
- `frontend/src/components/common/button.ts` (4개 click 핸들러 try/catch)
- `frontend/src/components/common/setting-row-inputs.ts` (9개 onChange/onEnter 핸들러 try/catch)
- `frontend/src/components/common/setting-row.ts` (2개 spin 버튼 onUp/onDown try/catch)
- `frontend/src/components/common/setting-row-controls.ts` (2개 토글/라디오 핸들러 try/catch)
- `frontend/src/components/common/settings-common.ts` (3개 시간 선택 핸들러 try/catch)
- `frontend/src/components/common/create-slider.ts` (3개 input/commit 핸들러 try/catch)
- `frontend/src/pages/profit-overview-mount.ts` (real-data-tick try/catch)
- `frontend/src/pages/sell-position.ts` (real-data-tick try/catch)
- `frontend/src/pages/buy-target.ts` (3개 틱 핸들러 try/catch)
- `frontend/src/pages/sector-stock.ts` (real-data-tick try/catch)
- `frontend/src/layout/header.ts` (3개 칩 해제 핸들러 try/catch)
- `frontend/src/main.ts` (beforeunload 3개 WS disconnect 개별 try/catch)

**아키텍처 원칙 부합**:
- P25 (격리된 실패): 핸들러 throw 시 console.error 로깅 + 다른 핸들러/이벤트 계속 동작. 공통 컴포넌트 chokepoint로 36개 핸들러를 6개 파일에서 보호.
- P20 (폴백 금지): silent `except: pass` 없음 — 모든 catch에 `console.error` 명시 로깅.
- P23 (일관성): T2-S10의 per-item try/catch + console.error 패턴과 동일. 공통 컴포넌트에서 일관된 에러 메시지 형식(`[컴포넌트명] 핸들러 error`).
- P24 (단순성): 공통 컴포넌트 chokepoint로 수정 지점 최소화 (87개 → 14개 파일). 저위험 41개 제외로 범위 과대 방지.
- P21 (사용자 투명성): 설정 변경 실패 시 콘솔 에러로 원인 추적 가능. 매매 차단 상태 칩 해제 실패 시 로깅.
- P16 (살아있는 경로): 모든 try/catch는 실제 이벤트 핸들러 경로에 연결됨 (dead code 아님).

**영향 범위**: 프론트엔드 14개 파일. 백엔드/테스트 영향 없음. 핵심 매매 로직 아님 (이벤트 핸들러 예외 처리만 추가) → 규칙 0-4 해당 없음. 롤백 아님 (신규 보호 코드 추가) → 규칙 0-3 해당 없음.

**UI 기준 화면 변화 (규칙 0-4)**:
- 정상 동작 변화 없음.
- 비정상 상황에서만 개선:
  - 수익 상세 페이지 요약 카드(당일/직전/당월/누적 손익) 생성 중 오류 시: 해당 카드만 '-' 표시, 나머지 카드 정상 표시 (기존에는 전체 카드 누락 가능).
  - 페이지 이동 시 오류: 좌측 설정 패널이 정상 전환됨 (기존에는 첫 리스너 오류 시 좌측 패널 미갱신).
  - 설정 입력 중 오류: 콘솔에 에러 기록, 다른 설정 입력 계속 가능 (기존에는 오류 전파로 입력 기능 중단 가능).
  - 실시간 시세 갱신 중 오류: 해당 틱만 누락, 이후 틱 정상 처리 (기존에는 브라우저 전역 에러).
  - 매매 차단 상태 칩 해제 클릭 오류: 콘솔에 에러 기록 (기존에는 브라우저 전역 에러).

**검증**:
- `npm run typecheck` (tsc --noEmit) 통과 ✓
- `npm run build` (tsc -b + vite build) 통과 — 76 modules, 1.71s ✓
- 브라우저 검증: 사용자 확인 대기

**작업 중 발견 문제**: 없음.

---

## 다음 세션 진행 대기

**다음 세션: 수정안 A (한도 수수료 포함 통일)** — 사용자 승인 완료. T3-S18 조사에서 도출된 보류 수정안.

**수정안 A 상세**:
- **대상**: `backend/app/services/trading.py`의 `_daily_buy_spent`, `_symbol_daily_buy_spent` 계산/로드
- **변경**: 매수 성공 후 `_daily_buy_spent`에 `spent + fee` 누적 (현재는 `spent`만). `_load_daily_buy_state`에서도 `total_amt`(수수료 포함) 합으로 로드. `_symbol_daily_buy_spent`도 동일하게 `total_amt` 기준.
- **효과**: 한도 체크(`max_daily_total_buy_amt`, `buy_amt`)가 "실제 지출액" 기준이 되도록 통일 (P22).
- **주의 (규칙 0-4)**: 사용자가 설정한 한도의 의미가 "순수 매수가 기준"에서 "수수료 포함 지출액 기준"으로 변경됨. UI 기준 설명 + 승인 필수. safe-trade 스킬 + backend-fix 스킬 적용.
- **영향 범위**: `trading.py` (3곳), 기동 시 로드 1곳. 테스트 코드 수정 필요.

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
