# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. **인덱스 역할만 수행** (규칙 8-2). 상세 구현 내역은 git 커밋 메시지 + docs/ 참조.

---

## 세션 개요

| 날짜 | 세션 | 작업 | 상태 |
|------|------|------|------|
| 2026-07-24 | UI-01 | 매수설정 가산점 행 순서 교체 (5일고가→뉴스→프로그램순매수→호가잔량비) — UI 개선 4항목 중 항목1 단독 완료, 항목2+3+4는 다단계 워크플로우 대기 | 완료 |
| 2026-07-24 | SKILL-03 | backend-fix/frontend-fix/safe-trade 스킬에 problem-solve 섹션 1-1 참조 추가 (영역 특화 질문 카테고리 명시) — P10/P23/P24 | 완료 |
| 2026-07-24 | SKILL-02 | AGENTS.md 섹션4 다단계 워크플로우 1세션 problem-solve 섹션 1-1 참조 연결 + 디자인 파일 "사용자 결정 항목" 의무화 — P10/P23 | 완료 |
| 2026-07-24 | SKILL-01 | problem-solve 스킬 "사용자 의도 파악 질문 프로세스" 섹션 1-1 신설 — P20/P23/P24 | 완료 |
| 2026-07-24 | NWS-S7 | 실시간 뉴스(NWS) 매수 가산점 테스트+런타임 검증 (다단계 워크플로우 7세션) — P16/P20/P22/P25 | 완료 (NWS 다단계 워크플로우 전체 완료) |

> NWS 실시간 뉴스 매수 가산점 다단계 워크플로우(세션 1~7) 전체 완료. 계획서/설계 문서는 규칙 11에 따라 삭제됨.
> 체결강도 매수차단 제거 다단계 워크플로우(세션 1~5) 전체 완료. 계획서/설계 문서는 규칙 11에 따라 삭제됨.
> P25 전수 조사(9세션) + 수정(Tier 1/2/3, 17세션) 전체 완료. 조사 보고서 `docs/p25_isolated_failure_investigation.md`는 역사적 기록으로 유지.

---

## 직전 완료 작업

### UI-01 매수설정 가산점 행 순서 교체 (2026-07-24)
- **작업**: 매수설정 "매수 가산점 (+N)" 섹션 행 순서를 사용자 요청대로 조정. 기존 5일고가→프로그램순매수→뉴스→호가잔량비 순서를 5일고가→뉴스→프로그램순매수→호가잔량비로 변경. 논리적 그룹(가격 돌파 → 뉴스 이벤트 → 프로그램 거래 → 호가 미시구조) 순서로 직관성 향상.
- **수정**: `frontend/src/pages/buy-settings.ts` `buildBoostSection` 내 프로그램 순매수 블록과 뉴스 호재 블록의 `appendChild` 순서만 맞바꿈 (12줄 삽입/12줄 삭제). 모듈 상태 참조(`boostProgramToggle`/`boostNewsToggle`)와 `syncBoost` 동기화는 DOM 순서 무관하므로 영향 없음.
- **검증**: typecheck 통과 / lint 스크립트 프로젝트에 없음 / build 성공 / 코드베이스 영향 범위 단일 파일 단일 함수 / 커밋 d89d4cb
- **다음 세션 인계**: 항목2(자동매수/매도 토글을 시간 설정 탭의 시간 라벨 우측으로 이동, 자동매매 탭에 상태 표시 배지 유지로 P21 보완) + 항목3("화면 표시" 섹션 이동) + 항목4(일반설정 탭 재분류, 옵션 A 추천: 뉴스 설정 탭+화면 설정 탭 신설)를 하나의 다단계 워크플로우(설계→태스크→구현)로 통합 진행. F-04 파일 분할(general-settings.ts 1443줄)도 설계 범위에 포함 권장.

### SKILL-03 backend-fix/frontend-fix/safe-trade 스킬에 problem-solve 섹션 1-1 참조 추가 (2026-07-24)
- **작업**: SKILL-01에서 신설한 problem-solve 섹션 1-1(사용자 의도 파악 질문 프로세스)을 3개 전문 스킬의 사전조사 섹션에 참조 추가. problem-solve가 기본 질문 프로세스를 정의하고 각 전문 스킬은 그것을 참조하며 영역 특화 질문을 추가하는 역할 분담 구조 확립 (P10 SSOT — 중복 기술 방지).
- **수정**: 3파일 각 1줄 추가 —
  - `backend-fix/SKILL.md`: 모호함 감지 시 5개 카테고리 선별 질문, 단일 버그는 경량 적용, 거래 로직 수정 시 safe-trade 거래 특화 질문 추가 적용 안내
  - `frontend-fix/SKILL.md`: 동일 + 프론트엔드 특성상 "UI 조작 위치/UX"와 "검증 기준(화면 확인 방법)" 카테고리 우선 검토 명시
  - `safe-trade/SKILL.md`: problem-solve 1-1 기본 카테고리 적용 후 거래 특화 3종(실전/모의 전환, 주문 경로 영향, 리스크 임계값) 추가 적용, 돈 직결이므로 모호성 적어도 임계값/모드 전환은 반드시 확인 명시
- **검증**: 세 스킬 모두 problem-solve 1-1 참조로 중복 기술 회피(P10) / 각 스킬 영역 특화 질문 유지(P23) / 과잉 질문 금지 원칙 명시(P24) / 코드베이스 영향 없음

### SKILL-02 AGENTS.md 섹션4 다단계 워크플로우 1세션 problem-solve 섹션 1-1 참조 연결 + 디자인 파일 "사용자 결정 항목" 의무화 (2026-07-24)
- **작업**: SKILL-01에서 신설한 problem-solve 섹션 1-1과 AGENTS.md 섹션4 1세션 사이 끊긴 참조 연결 + 디자인 파일 "사용자 결정 항목" 의무화.
- **수정**: `AGENTS.md` (1파일, 2줄 변경) — 1세션 step 2 problem-solve 섹션 1-1 적용 명시 / step 3 디자인 파일 "사용자 결정 항목" 섹션 의무화(2세션 태스크 파일로 전달)
- **검증**: problem-solve 1-1 "질문 결과 기록"과 일치 확인 / 1세션→2세션 "사용자 결정 항목" 연결 확인 / 코드베이스 영향 없음 / 커밋 d3cfc50

> SKILL-01, NWS-S7, NWS-S6, T4-S01, MEM-01, T3-S31/S32 등 이전 완료 작업 상세는 git history 참조 (규칙 7 — 직전 완료 작업 최근 1~2건 유지).

---

## 다음 세션 진행 대기

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
