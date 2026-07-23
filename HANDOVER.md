# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. 이전 세션의 완료 작업, 현재 상태, 다음 세션에서 이어서 진행할 항목을 기록.

---

## 직전 완료 작업

### P25 전수 조사 세션 2: B1 엔진 코어 루프 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사 보고서 1파일 갱신. 조사만 수행 (코드 수정 없음).

**배경**: P25 전수 조사 9세션 중 세션 2. B1 엔진 코어 루프 영역(`engine_lifecycle.py`, `engine_loop.py`, `engine_ws_dispatch.py`, `engine_ws.py`, `engine_ws_fill_followup.py`, `engine_ws_parsing.py`, `engine_ws_reg.py` 7개) 조사. 우선순위 2위 — 매 틱·매 이벤트 통과 경로, 한 번 중단 시 자동매매 전체 정지 위험.

**조사 파일**: 7개 메인 파일 (engine_lifecycle 328줄, engine_loop 395줄, engine_ws_dispatch 401줄, engine_ws 271줄, engine_ws_fill_followup 29줄, engine_ws_parsing 218줄, engine_ws_reg 490줄) + 4개 보조 파일 (kiwoom_connector, ls_connector, app.py, engine_service — 호출자 격리 확인용)

**식별 위반 7건**:
- **B1-02-01 (HIGH)**: `engine_loop.py:304` while 루프 본문 내 `is_ws_subscribe_window` 호출이 try/except 없음. throw 시 외부 try(159)에서 catch → 엔진 루프 전체 종료. 한 번의 오류가 엔진을 영구 정지.
- **B1-02-02 (MEDIUM)**: `engine_loop.py:374,377` finally 블록 `disconnect_all()`/`disconnect()` 무보호. throw 시 후속 정리 스킵 → 엔진 상태 불일치.
- **B1-02-03 (MEDIUM)**: `engine_loop.py:387,389` finally 블록 REST 정리 루프에서 `_reset_client()`/`aclose()` 무보호. 한 증권사 실패 시 나머지 스킵.
- **B1-02-04 (HIGH)**: `engine_loop.py:31` `_cache_and_bootstrap`에서 `_load_caches_preboot` 무보호. throw 시 엔진 루프 종료. 캐시 로드 실패가 엔진 기동 전체 차단.
- **B1-02-05 (LOW)**: `engine_ws_dispatch.py:149-153` `_handle_real_00` 내 `on_fill_update`/`_on_fill_after_ws` 무보호. 호출자(pipeline_compute) 의존 — 세션 3에서 확인.
- **B1-02-06 (LOW)**: `engine_ws_dispatch.py:162` `_handle_real_balance` 내 `_apply_balance_realtime` 무보호. 호출자 의존 — 세션 3에서 확인.
- **B1-02-07 (LOW)**: `engine_lifecycle.py:38` `start_engine` 내 `_refresh_positions_if_dirty` 무보호. 주 호출자(app.py)는 격리 있으나 engine_service.py:93 경유 시 미확인 — 세션 6에서 확인.

**핵심 발견**:
- `schedule_engine_task` (engine_lifecycle.py:279-309) 중앙 격리 메커니즘은 P25 준수 (done_callback 로깅 + coro.close() 정리). 이 패턴을 사용하는 모든 경로는 격리 확보.
- 커넥터 recv 루프 (Kiwoom/LS)는 전체 루프 try/except, 비-연결오류 시 로깅+계속. P25 준수, P23 일관.
- 사전 위반 후보 `engine_loop.py:343-344` create_task 직접 호출은 **위반 아님**으로 확정 — 로컬 이벤트 대기 태스크, asyncio.wait + cancel로 정상 정리.
- `handle_ws_data` (engine_ws_dispatch.py:165-177)의 try/except가 LOGIN/REG/UNREG/REMOVE/JIF 핸들러를 격리. 양호.
- 엔진 루프의 취약점은 while 루프 본문 내 개별 무보호 호출(B1-02-01)과 finally 정리 루프의 무보호 호출(B1-02-02, B1-02-03). 이들은 한 예외가 엔진 전체를 종료시키거나 정리를 불완전하게 만듦.

**수정 방향 (참고용, 승인 시 별도 세션)**:
- B1-02-01: while 루프 본문을 try/except로 감싸고, 예외 시 로깅 + sleep(1) 후 계속. 루프 종료는 engine_stop_event에서만 유도
- B1-02-02: disconnect_all/disconnect를 try/except로 감싸고, 후속 정리는 항상 실행
- B1-02-03: _reset_client/aclose를 기존 revoke_token try/except 블록 내로 통합
- B1-02-04: _load_caches_preboot를 try/except로 감싸고, 실패 시 빈 캐시로 기동 또는 안전한 종료 + 프론트엔드 상태 전송(P21)
- B1-02-05~07: 세션 3/6에서 호출자 격리 확인 후 결정

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (조사 보고서 작성).

**다음 세션 대기 사항**: 세션 3 (B2 파이프라인 연산 루프 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 5에 결과 누적 예정. 세션 2에서 식별한 B1-02-05/06(호출자 의존)의 확인이 세션 3에서 pipeline_compute.py 호출부 격리 점검과 함께 수행될 예정.

---

### P25 전수 조사 세션 1: A1 WS 디스패치 조사 완료 (2026-07-23)

**세션**: 단일 세션. 조사 보고서 1파일 갱신. 조사만 수행 (코드 수정 없음).

**배경**: P25 전수 조사 9세션 중 세션 1. A1 WS 디스패치 영역(`frontend/src/api/ws.ts`, `frontend/src/binding.ts`) 조사. 우선순위 1위 — 매 이벤트 통과 경로, 한 핸들러 throw 시 전 채널 이벤트 수신 중단 위험.

**조사 파일**: `ws.ts`(261줄), `binding.ts`(338줄), `store.ts`(57줄 — F-02 fix 보호 범위 확인용)

**식별 위반 5건**:
- **A1-01-01 (CRITICAL)**: `ws.ts:193` `_dispatchMessage`의 `list.forEach(h => h(data))` 핸들러별 try/catch 없음. 한 핸들러 throw 시 forEach 중단 → 같은 event type 후속 핸들러 미실행 + 예외 상위 전파.
- **A1-01-02 (CRITICAL)**: `ws.ts:164-174` `_handleBinaryFrame`의 `for (const event of events)` 루프가 try 블록 내부. 한 이벤트 핸들러 throw 시 catch가 잡지만 루프 중단 → 같은 바이너리 프레임의 나머지 이벤트 모두 손실. real-data 고빈도 프레임이므로 한 종목 오류가 다른 종목 시세 갱신 차단.
- **A1-01-03 (MEDIUM)**: `ws.ts:172,181` catch 로그가 "디코딩 실패"/"파싱 실패"로 핸들러 예외와 혼동. P21/P23 위반.
- **A1-01-04 (HIGH)**: `binding.ts` 33개 onEvent 핸들러 전부 내부 try/catch 없음. F-02 fix(store.ts listener 루프)는 UI 렌더링 listener만 보호, binding.ts 핸들러 본문 로직 + setState updater 함수는 보호되지 않음. 고위험: `buy-targets-delta`, `sector-scores`, `sector-stocks-delta`, `circuit_breaker_open`.
- **A1-01-05 (LOW)**: `ws.ts:132-136` `_scheduleReconnect` setTimeout 콜백 try/catch 없음. `_connect` 동기 throw 시 재연결 루프 영구 중단.

**핵심 발견**: F-02 fix(store.ts:40-46 listener 루프 try/catch)는 UI 렌더링 listener만 보호. binding.ts 핸들러 본문 로직(destructuring, recalcTradeAmountRank, rebuildBuyTargetIndex) + setState updater 함수(`partial(state)` — store.ts:19)는 보호되지 않아, throw 시 store.ts를 넘어 ws.ts 디스패치 단계로 역전파 → A1-01-01/02 경로 합류.

**수정 방향 (참고용, 승인 시 별도 세션)**:
- A1-01-01: `forEach`를 try/catch 감싼 루프로 변경, 핸들러 throw 시 `console.error('[WS] handler error', type, e)` + 다른 핸들러 계속 실행
- A1-01-02: A1-01-01 수정으로 자연 해결 (핸들러 throw가 상위로 전파되지 않음)
- A1-01-03: 디코딩 catch와 핸들러 catch 분리 후 목적에 맞는 로그
- A1-01-04: 디스패치 격리 확보 시 핸들러 개별 try/catch는 선택적. 고위험 핸들러는 본문 try/catch 권장. 최종 방침은 수정 세션에서 결정
- A1-01-05: `_connect()` 호출 try/catch, 실패 시 `_scheduleReconnect` 재호출

**검증**: 조사만 수행 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (조사 보고서 작성).

**다음 세션 대기 사항**: 세션 2 (B1 엔진 코어 루프 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 4에 결과 누적 예정.

---

### P25 전수 조사 보고서 파일 생성 (2026-07-23)

**세션**: 단일 세션. 문서 1파일 신규 작성. 사전 검토(별도 파일 필요성) → 승인 → 파일 생성 → 커밋.

**배경**: P25 원칙 신규 추가 후, P25 관점 전수 조사 계획 수립. 9세션 예정. HANDOVER.md 단독 사용 시 규칙 7 롤링 윈도우(최근 3건 유지)로 초기 세션 조사 결과 소실 위험 → 별도 조사 보고서 파일 필요성 검토.

**검토 결과**:
- 규칙 11 (계획서 파일 삭제): `docs/plan_*.md`, `docs/architecture_*_design.md`는 완료 시 삭제. 단, `docs/*_investigation.md` (조사 보고서)는 삭제 제외 — 역사적 기록 유지
- 30세션 감사 파일(`architecture_audit_plan.md` 1221줄, `architecture_audit_tasks.md` 1105줄)은 24개 원칙 전체 대상. P25 단일 원칙 감사와 범위 혼재 방지를 위해 별도 파일 분리
- P24 단순성: 9세션은 단일 파일에 세션별 섹션으로 충분. plan+tasks 2분할 불필요

**생성 파일 1개**:
- `docs/p25_isolated_failure_investigation.md` (287줄)
  - 섹션 1: 조사 개요 (목적, P25 핵심 내용, 조사 범위 A/B/C, 조사 방식, 9세션 분할, 우선순위 기준, 사전 확인 위반 후보)
  - 섹션 2: P25 위반 매트릭스 빈 템플릿 (ID/영역/파일:줄/위반 내용/영향 범위/등급/관련 원칙/조사 세션/수정 승인) + 등급 정의(CRITICAL/HIGH/MEDIUM/LOW)
  - 섹션 3~10: 세션 1~8 기본 구조 (상태 미시작, 조사 파일, 조사 범위, 조사 결과/위반 목록 placeholder)
  - 섹션 11: 세션 9 교차 점검·총합 보고 (교차 원칙 매트릭스 빈 템플릿, 우선수정 추천 placeholder, 조사 완료 정의)
  - 섹션 12: 변경 이력

**문서 종류**: 조사 보고서 (`docs/*_investigation.md`) — 규칙 11 삭제 제외, 완료 후에도 유지

**HANDOVER.md 연동 규칙**:
- 각 세션 종료 시 `세션 개요`에 본 보고서 경로 참조 명시
- `다음 세션 진행 대기`에 현재 세션 번호 + 다음 세션 조사 영역 명시
- 조사 완료(9세션) 후에도 본 보고서는 유지, HANDOVER.md에서 해당 참조 제거

**검증**: 문서 신규 작성만 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (문서 작성).

**다음 세션 대기 사항**: 세션 1 (A1 WS 디스패치 조사) 진행 대기. 조사 보고서 `docs/p25_isolated_failure_investigation.md` 섹션 3에 결과 누적 예정.

---

### P25 (격리된 실패) 아키텍처 원칙 신규 추가 (2026-07-23)

**세션**: 단일 세션. 문서 2파일. 사전조사(기존 원칙 충돌/중복 분석) → 승인 → 문서 수정 → 커밋.

**배경**: 직전 세션에서 F-02(header.ts 장 상태 칩 렌더링 실패 → 앱 전체 중단) 근본 해결 완료. 해당 사례에서 "예외 전파 차단(fault isolation)"을 명시하는 기존 원칙이 없음을 확인 → P25 신규 추가.

**기존 원칙과의 관계 분석 (사전조사 결과)**:
- P7(블로킹): "느린 연산" 방지. P25는 "throw 전파 차단". 원인 다름.
- P9(파이프라인 독립): 파이프라인 간 독립. P25는 구성요소 간 격리. 범위 다름.
- P20(폴백 금지): "빈값 덮기 금지". P25는 "실패 전파 차단". 격리 시 에러 로그 출력하므로 폴백 아님.
- P24(단순성): 잠재 충돌 — P25는 "최소 전파 차단"에 국한, microservice식 과도 격리 추상화 금지 명시로 충돌 방지.
- 결론: P25가 다루는 "실패 전파 차단"을 직접 명시하는 기존 원칙 없음. 추가 타당.

**수정 내용 (2파일)**:
- `ARCHITECTURE.md`:
  - line 18: "불변 원칙 24개" → "불변 원칙 25개"
  - P24 이후에 P25 블록 추가 (내용/배경/구현 가이드/P24 균형/P20 구분 명시)
- `AGENTS.md`:
  - 섹션2: "24개" → "25개" (3곳), P 목록에 P25 추가, 사전조사 원칙 목록에 P25 추가
  - 백엔드 체크리스트: P25 항목 추가 (태스크/코루틴 실패 격리, schedule_engine_task 사용, 에러 로깅)
  - 프론트엔드 체크리스트: P25 항목 추가 (칩/컴포넌트 렌더링 실패 격리, store listener 루프 전파 차단, 에러 로깅)

**P25 핵심 내용**:
- 한 구성요소 실패가 전체 시스템 기동/운영 블로킹 금지
- 실패는 해당 구성요소에서 차단+로깅, 다른 구성요소 정상 작동 유지
- 격리 ≠ silent 무시 — 반드시 에러 로깅 (P20/P23과 일관)
- P24 균형: 최소 전파 차단에 국한, 과도한 격리 추상화 금지

**검증**: 문서 수정만 — typecheck/build 불필요. 잔존 프로세스 0건.

**화면 영향**: 없음 (문서 수정).

**다음 세션 대기 사항**: 없음.

---

### header.ts 장 상태 칩 렌더링 실패 → 앱 전체 중단 구조 근본 수정 (F-02 해결) (2026-07-23)

**세션**: 단일 세션. 프론트엔드 3파일. 사전조사 → 승인 → 수정 → 검증 → 커밋.

**문제 현상**: `PHASE_STYLE[phase]`가 undefined일 때 TypeError가 header의 `onStateChange`에서 throw → `store.setState` listener 루프에서 다른 listener/호출자로 전파 → 앱 전체 렌더링 중단(하얀 화면). 이전 세션에서 긴급 폴백 복구로 증상만 덮어둔 상태.

**근본 원인 (구조적)**:
1. `frontend/src/stores/store.ts:37-39` — listener 루프에 try/catch 없음. 하나의 listener throw가 다른 listener와 setState 호출자(WS 핸들러)까지 전파 → 앱 전체 중단. "undefined 하나가 전체 앱을 죽이는" 구조의 핵심.
2. `frontend/src/stores/uiStore.ts:85, 245` — 초기값/폴백값 `'CLOSED'`가 `PHASE_STYLE`에 없는 키. 부트스트랩 단계에서 항상 undefined 도달.
3. `frontend/src/layout/header.ts:102` — `|| PHASE_STYLE['장마감']` 폴백은 P20 위반 (정상 경로의 undefined를 폴밭으로 덮음). 긴급 조치일 뿐 근본 해결 아님.

**수정 내용 (3파일)**:
- `frontend/src/stores/store.ts:37-46` — listener 루프 try/catch 전파 차단. throw 시 `console.error('[Store] listener error', e)` 로깅(silent pass 아님), 다른 listener는 계속 실행. P16/P21.
- `frontend/src/stores/uiStore.ts:85, 245` — 초기값/폴백 `'CLOSED'` → `'장마감'` 통일 (안 B). P10/P23.
- `frontend/src/layout/header.ts:102-117` — 폴백 제거. undefined 시 `console.warn` 경고 + neutral 기본 스타일로 phase 문자열 그대로 표시. 정상 경로 폴밭 금지(P20), 칩만 기본 표시하고 나머지 화면 정상 작동(P21).

**아키텍처 원칙 부합**:
- P20 (폴백 금지): 정상 경로 폴백 제거. 단, "알 수 없는 phase(백엔드-프론트 불일치)"에 대한 기본 표시는 폴백이 아닌 에러 복구 표시로定位 — 경고 로그 + neutral 스타일.
- P21 (사용자 투명성): 칩 렌더링 실패 시 칩만 기본 표시, 나머지 헤더/화면 정상 작동.
- P22 (데이터 정합성): 초기값 'CLOSED' → '장마감'으로 백엔드 phase 문자열과 일치.
- P16 (살아있는 경로): store.ts try/catch는 silent except:pass 아님 — console.error 로깅.

**수정 파일 3개**:
- `frontend/src/stores/store.ts` — listener 루프 전파 차단
- `frontend/src/stores/uiStore.ts` — 초기값/폴백 '장마감' 통일 (2곳)
- `frontend/src/layout/header.ts` — 폴백 제거 + 명시적 안전 처리

**검증**:
- `npm run typecheck` exit 0
- `npm run build` 1.94s exit 0 (76 modules transformed)
- lint 스크립트 존재하지 않음 (package.json에 없음)
- 잔존 프로세스 0건

**화면 영향**:
- 앱 기동 시 헤더 장 상태 칩이 '장마감' 스타일로 정상 표시 (이전과 동일 외관)
- WS 수신 후 실제 phase로 갱신 (이전과 동일)
- 향후 백엔드가 알 수 없는 phase를 보내도 칩만 neutral 표시, 앱 전체 중단 없음 (구조적 개선)

**다음 세션 대기 사항**: 없음 (F-02 근본 해결 완료).

---

### header.ts 장 페이즈 폴백 제거 → 긴급 복구 (F-02 경미) (2026-07-23)

**세션**: 단일 세션. 프론트엔드 1파일. 사전조사 생략 (간단 수정, 사용자 지시) → 잘못된 분석으로 인한 긴급 롤백 포함.

**문제 현상**: `header.ts:102`의 `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` 폴백 — 백엔드가 알려진 페이즈만 보내므로 "도달 불가능한 dead code"로 판단. P20(폴백 금지) + P16(살아있는 경로) 위반 (경미 등급).

**사전 조사 결과** (승인 전 조사 — **누락 있음**):
- 백엔드 `calc_timebased_market_phase()` + `_JIF_PHASE_MAP_KRX/NXT`가 보내는 phase = KRX 13개 + NXT 9개 (중복 제외 19개)
- `PHASE_STYLE` 키 19개와 1:1 완전 일치 — 누락/과잉 없음
- ~~실제 도달 가능성 0, 화면 영향 없음~~ → **잘못된 결론**. 프론트엔드 초기값/폴백값 `'CLOSED'`를 누락함.

**1차 수정 (폴백 제거)**:
- `frontend/src/layout/header.ts:102` — `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` → `PHASE_STYLE[phase]`
- 커밋 `ce9e137` "fix: header.ts 장 페이즈 폴백 제거 — 도달 불가능 dead code (P20/P16)"

**긴급 롤백 사유** (사용자 보고: 하얀 화면):
- `uiStore.ts:85` 초기값 `marketPhase: { krx: 'CLOSED', nxt: 'CLOSED', ... }`
- `uiStore.ts:245` engine_status 폴백 `?? { krx: 'CLOSED', nxt: 'CLOSED', ... }`
- 앱 기동 직후 `header.ts:488`이 `onStateChange(uiStore.getState())` 즉시 호출 → `applyMarketPhaseChip(el, 'KRX', 'CLOSED', ...)` → `PHASE_STYLE['CLOSED']` = undefined → `s.bg` 접근 시 TypeError → 렌더링 전체 중단 → 하얀 화면
- **근본 원인**: 백엔드는 한국어 페이즈명(`장마감` 등)만 보내지만, 프론트엔드 초기값/폴백은 영문 `'CLOSED'` 사용 (P23 용어 통일 위반). 폴백은 "도달 불가능 dead code"가 아니라 **부트스트랩 단계에서 항상 도달 가능한 정상 분기**.

**2차 수정 (폴백 복구)**:
- `frontend/src/layout/header.ts:102` — `PHASE_STYLE[phase]` → `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` (원복)
- 커밋 `a5b357b` "revert: header.ts 장 페이즈 폴백 복구 — 부트스트랩 'CLOSED' phase 하얀 화면 원인"
- 롤백 사유 기록 (규칙 0-3): 커밋 메시지에 잘못된 분석 인정 + 사유 + 되돌린 대상 + 영향 범위 명시

**수정 파일 1개**:
- `frontend/src/layout/header.ts:102` — 최종 상태: 폴백 복원 (원래 코드로 회귀)

**검증**:
- 1차: `npm run typecheck` exit 0, `npm run build` 1.88s exit 0 (하지만 런타임 TypeError 발생 — 빌드 통과가 런타임 안전성 보장 아님)
- 2차: `npm run build` 631ms exit 0
- 잔존 프로세스 0건

**화면 영향**:
- 1차 수정 후: 앱 기동 시 하얀 화면 (TypeError로 렌더링 중단)
- 2차 복구 후: 정상 렌더링 복구. 부트스트랩 단계 'CLOSED' phase가 '장마감' 스타일로 표시 (기존 동작 회귀)

**교훈**:
- 빌드/typecheck 통과가 런타임 안전성을 보장하지 않음 — 부트스트랩 초기값/폴백값 경로는 별도 검증 필요
- "도달 불가능" 판단 시 백엔드 값뿐 아니라 프론트엔드 초기값/폴백값/기본값도 포함해야 함
- 사전조사 생략은 "간단 수정"이라도 위험 — 규칙 0-2(수정 전 사전조사 의무) 준수 필요

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 안 B 사전조사 — `uiStore.ts` 초기값/폴백 `'CLOSED'` → `'장마감'` 통일 (P10/P23). 사전조사 항목: `'CLOSED'`를 비교/참조하는 다른 코드 전체 검색. 근본 해결 완료 시 header.ts 폴백 제거 재검토.

---

### header.ts 장 페이즈 폴백 제거 (F-02 경미) (2026-07-23, 롤백됨)

**세션**: 단일 세션. 프론트엔드 1파일. 사전조사 생략 (간단 수정, 사용자 지시).

**문제 현상**: `header.ts:102`의 `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` 폴백 — 백엔드가 알려진 페이즈만 보내므로 도달 불가능한 dead code. P20(폴백 금지) + P16(살아있는 경로) 위반 (경미 등급).

**사전 조사 결과** (승인 전 조사):
- 백엔드 `calc_timebased_market_phase()` + `_JIF_PHASE_MAP_KRX/NXT`가 보내는 phase = KRX 13개 + NXT 9개 (중복 제외 19개)
- `PHASE_STYLE` 키 19개와 1:1 완전 일치 — 누락/과잉 없음
- 실제 도달 가능성 0, 화면 영향 없음

**수정 안**: 폴백 제거 → `PHASE_STYLE[phase]` 직접 참조.

**수정 파일 1개**:
- `frontend/src/layout/header.ts:102` — `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` → `PHASE_STYLE[phase]`

**원칙 부합**:
- P16 살아있는 경로: 도달 불가능한 dead code 제거
- P20 폴백 금지: 정상 경로의 누락을 폴백으로 덮는 패턴 제거
- P24 단순성: 1줄 변경

**검증**:
- `npm run typecheck` (tsc --noEmit) — exit 0
- `npm run build` (vite build) — 1.88s exit 0
- 잔존 프로세스 0건

**화면 영향**: 없음. 백엔드가 보내는 모든 phase가 PHASE_STYLE에 정의되어 있으므로 칩 스타일 표시 변화 없음.

**커밋**: `ce9e137` (이후 `a5b357b`로 롤백됨 — 상단 세션 참조).

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 롤백됨. 상단 "header.ts 장 페이즈 폴백 제거 → 긴급 복구" 세션 참조.

---

### 수신율 갱신 로그 1줄 \r 갱신 통일 (2026-07-23)

**세션**: 단일 세션. 백엔드 2파일 + 테스트 1파일.

**문제 현상**: 수신율 갱신 시마다 `logger.info`로 매번 새 줄 출력 → 장초반 틱 집중 수신 시 40~50줄 폭주, 파일 로그 용량 증가. 다운로드 진행률은 이미 `log_progress`로 1줄 `\r` 갱신 중이나 수신율만 예외 상태.

**근본 원인**: `pipeline_compute.py` Phase 1/Phase 2 루프의 수신율 갱신 로그가 `logger.info`로 매번 새 줄 출력. 파일에도 INFO로 누적되어 용량 증가.

**수정 안**: 다운로드 진행률 `log_progress` 패턴 재사용 (P23 일관성).
- 콘솔: `\r` 1줄 갱신 (TTY 아닐 때 `\n`)
- 파일: DEBUG 강하 (INFO 운영 시 파일 누적 안 됨 → 용량 절감)
- 임계값 통과 시점: 별도 `logger.info` 1줄 영구 기록 유지 (P21 투명성)
- Phase 2 구간도 동일 적용

**수정 파일 3개**:
- `backend/app/core/logger.py` — `log_receive_rate_progress` 헬퍼 신규 추가. KRX/NXT 이중 카운터 + 임계값 표시. `_progress_active` 플래그 공유, `log_progress_end` 재사용.
- `backend/app/pipelines/pipeline_compute.py` — Phase 1 대기 중 로그 → `log_receive_rate_progress(waiting=True)`, 임계값 통과 직전 `log_progress_end()` 추가 (커서 꼬임 방지), Phase 2 로그 → `log_receive_rate_progress(waiting=False)`.
- `backend/tests/test_logger.py` — `TestLogReceiveRateProgress` 4건 추가 (TTY 대기 중, TTY Phase 2, non-TTY, zero total).

**원칙 부합**:
- P10 SSOT: `_progress_active` 단일 플래그 유지, 수신율 데이터는 기존 `_current_receive_rate` 참조
- P16 살아있는 경로: 헬퍼가 실제 Phase 1/2 루프 호출 경로에 연결
- P21 사용자 투명성: 임계값 통과 시점 `logger.info` 영구 기록 유지
- P23 일관성: `log_progress`와 동일 패턴, 용어 "수신율/임계값" 유지
- P24 단순성: 신규 헬퍼 단일 역할, 20줄 이내

**검증**:
- `py_compile` 통과, `ruff` 신규 코드 통과 (기존 unused import 2건은 본 수정과 무관)
- `pytest backend/tests/test_logger.py` 42 passed (신규 4건 포함)
- 런타임 기동 (`-W error::RuntimeWarning`) 정상 — RuntimeWarning/Traceback 없음
- 콘솔 1줄 `\r` 갱신 확인, 파일 수신율 갱신 0건 / 임계값 통과 1건 확인
- 잔존 프로세스 0건

**화면 영향**: 없음 (로그 출력 방식 변경만, WS 수신율 broadcast 불변)

**커밋**: `fe150c9` refactor: 수신율 갱신 로그를 1줄 \r 갱신으로 통일 — 다운로드 진행률과 동일 패턴 (P23/P24)

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 완료. 다음 우선순위 작업 진행.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 override datetime JSON 직렬화 오류 근본 해결 (2026-07-23)

**세션**: 긴급 런타임 오류 수정 — 단일 세션. 백엔드 2파일.

**문제 현상**: JIF 카운트다운 수신 시 `TypeError: Object of type datetime is not JSON serializable` 발생. 이후 10초 주기 장상태 브로드캐스트마다 override 만료 전까지 동일 오류 반복 (조용히 실패 — P21 위반).

**근본 원인** (데이터 흐름):
1. `engine_ws_dispatch.py:335` — `expires_at = now + timedelta(...)` 로 datetime 객체 생성 후 override dict에 그대로 저장
2. `daily_time_scheduler.py:_get_active_override()` — 저장된 override dict를 expires_at 포함 그대로 반환
3. `daily_time_scheduler.py:get_market_phase()` — `phase["krx_countdown"]`에 datetime 포함 dict 삽입
4. `engine_ws_dispatch.py:343` — `_broadcast("market-phase", get_market_phase())` 가 datetime 포함 payload 전달
5. `ws_manager.py:160` — `dumps(...)` 직렬화 실패 → TypeError

**수정 안**: 안 A (P24 단순성, P10 SSOT) — `_get_active_override()` 반환 시 `expires_at` 제외, `{label, remaining_sec}`만 반환.
- 저장은 datetime 그대로 유지 (만료 판정 `_kst_now() >= expires_at`에 필요)
- 반환은 프론트엔드 타입과 정확 일치
- 안 B(ISO 문자열 변환)는 매 호출 시 파싱 오버헤드로 P24 위반 → 비추천

**수정 파일 2개**:
- `backend/app/services/daily_time_scheduler.py` — `_get_active_override()` 반환 + docstring
- `backend/app/services/engine_state.py` — 주석 보완 (expires_at 내부 전용 명시)

**원칙 부합**:
- P10 SSOT: 브로드캐스트 스키마 = 프론트엔드 타입 = {label, remaining_sec} 정합
- P16 살아있는 경로: JIF 즉시 브로드캐스트 + 10초 주기 브로드캐스트 모두 정상 복구
- P20 폴백 금지: 만료 판정 로직 유지, 폴백 도입 아님
- P21 사용자 투명성: 10초 주기 브로드캐스트 조용히 실패 문제 함께 해결 — 화면 장상태 갱신 정상화
- P24 단순성: 1줄 변경, 파싱 오버헤드 없음

**검증**:
- `pytest test_daily_time_scheduler.py test_engine_ws_dispatch.py` 286 passed
- 런타임 기동 정상 (RuntimeWarning 없음, TypeError 없음, 수신율 100% 도달)
- 잔존 프로세스 0건

**화면 영향**:
- 상단 헤더 카운트다운 칩: JIF 카운트다운 수신 시점(장개시 10분전/5분전/1분전/10초전 등)에 화면 갱신 정상 복구. 기존에는 카운트다운 수신 순간부터 만료 시까지 화면 장상태 갱신이 조용히 실패했음.
- 매수/매도 동작: 영향 없음 (카운트다운은 표시 전용)

**커밋**: `322b888` fix: JIF 카운트다운 override 반환 시 expires_at 제외 — datetime JSON 직렬화 오류 근본 해결

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: 긴급 오류 해결 완료. 이후 다음 우선순위 작업 진행.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 S-2 프론트엔드 + 테스트 보완 (2026-07-23)

**세션**: 다단계 작업 워크플로우 4세션 — `plan_jif_countdown.md` 기반 S-2 구현. 프론트엔드 3파일 + 테스트 1파일. JIF 카운트다운 복구 최종 세션.

**구현 내용 (Step 2-1 ~ 2-2)**:
1. `header.ts` — `formatCountdown()` 포맷 확장: 60초 이상일 때 "X분 Y초 전" 표시 (예: 90초 → "1분 30초 전"). sec=0이면 "X분 전" 유지.
2. `header.ts` — `PHASE_STYLE` "애프터마켓 지속" 항목 제거 (dead code — P16. 백엔드에서 더 이상 해당 페이즈명 사용 안 함).
3. `general-settings.ts` — `fixedTimes` "18:00 애프터마켓 지속 전환" 항목 제거 (백엔드 타임테이블에서 18:00 phase 엔트리 제거됨 — P10 SSOT 일치).
4. `sector-settings.ts` — 주석에서 "애프터마켓 지속" 제거 (P23 용어 통일).
5. `test_engine_ws_dispatch.py` — `_JIF_COUNTDOWN_KRX`/`_JIF_COUNTDOWN_NXT` 임포트 추가 + `TestJifConstants` 클래스에 매핑 완전성 검증 6건 추가:
   - 카운트다운 맵/페이즈 맵 중복 없음
   - 카운트다운 맵/무시 코드 중복 없음 (P20)
   - KRX 7개 / NXT 14개 엔트리 수 검증
   - remaining_sec 값 {600, 300, 60, 10} 일치 (API 문서 기준 — P10)
   - KRX 장마감 10분전 코드 없음 검증 (API 문서 — 44=5분전이 최대)

**수정 파일 4개**:
- 프론트엔드 3개: `header.ts`, `general-settings.ts`, `sector-settings.ts`
- 테스트 1개: `test_engine_ws_dispatch.py`

**검증**:
- `npm run build` 성공 (vite build, 76 modules, 945ms, 타입 오류 없음)
- `pytest backend/tests/test_engine_ws_dispatch.py backend/tests/test_daily_time_scheduler.py` 286 passed
- `pytest backend/tests/` 전체 2808 passed (이전 2802에서 6개 증가 — 신규 매핑 완전성 테스트 6건)
- 잔존 프로세스 0건

**화면 영향 (S-2 완료 후)**:
- 상단 헤더 카운트다운 칩: 90초 전일 때 "1분 30초 전"으로 더 정확하게 표시 (기존 "1분 전" → 개선)
- 설정 화면 "거래소 고정 시간" 안내: "18:00 애프터마켓 지속 전환" 항목 제거 (NXT 애프터마켓은 15:40~20:00 단일 구간)
- NXT 애프터마켓 칩: 15:40~20:00 동일 "애프터마켓" 표시 (UI 변화 없음, dead code 제거만)
- 매수/매도 동작: 영향 없음 (카운트다운은 표시 전용)

**JIF 카운트다운 복구 전체 완료 (S-1 + S-2)**:
- S-1: 백엔드 핵심 11 Step (engine_state.py, engine_ws_dispatch.py, daily_time_scheduler.py + 설계 문서 수정)
- S-2: 프론트엔드 3파일 + 테스트 1파일 (header.ts, general-settings.ts, sector-settings.ts, test_engine_ws_dispatch.py)
- 전체 수정 파일 8개 (백엔드 3 + 프론트엔드 3 + 테스트 2 + 문서 1)
- 태스크 파일(`docs/plan_jif_countdown.md`) + 설계 문서(`docs/jif_countdown_design.md`) 삭제 완료 (규칙 11 — 모든 단계 완료 후)

**잔존 프로세스**: 없음.

**다음 세션 대기 사항**: JIF 카운트다운 복구 전체 완료 + 태스크 파일/설계 문서 삭제 완료 (규칙 11). 이후 다음 우선순위 작업 진행.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 S-1 백엔드 핵심 구현 (2026-07-23)

**세션**: 다단계 작업 워크플로우 3세션 — `plan_jif_countdown.md` 기반 S-1 구현. 백엔드 핵심 11 Step + 테스트 보완.

**구현 내용 (Step 1-1 ~ 1-11)**:
1. `engine_state.py` — `krx_countdown_override`, `nxt_countdown_override` 필드 추가 (P10 SSOT — override 단일 소스)
2. `engine_ws_dispatch.py` — `_JIF_COUNTDOWN_KRX`/`_JIF_COUNTDOWN_NXT` 매핑 테이블 신설 (API 문서 기준) + `_JIF_IGNORE_CODES`에서 카운트다운 코드 전부 제거 ("53"만 남김)
3. `engine_ws_dispatch.py` — `_handle_jif()` 카운트다운 처리 추가 (override 저장 + 브로드캐스트) + 페이즈 전환 시 override 초기화
4. `daily_time_scheduler.py` — 카운트다운 임계 시각 상수 22개 정의 (KRX/NXT 장개시·장마감, 거래소 규정 코드 상수)
5. `daily_time_scheduler.py` — `build_timetable_from_cache()`에 `kind="countdown"` 엔트리 22개 추가 (타임테이블 12→33항목)
6. `daily_time_scheduler.py` — `_timetable_event_fired()`에 `kind="countdown"` 분기 추가 (JIF override 활성 시 스킵, 없으면 calc_countdown 보조)
7. `daily_time_scheduler.py` — `_get_active_override()` 헬퍼 신설 (만료 시 None 반환 — P20 폴백 금지)
8. `daily_time_scheduler.py` — `get_market_phase()` override 우선 적용 (JIF 1순위, calc_countdown 보조)
9. `daily_time_scheduler.py` — `_KRX_COUNTDOWN_MAP` 누락 페이즈 3개 보완 (종가 동시호가, 장후 시간외, 시간외 단일가 — `KRX_AFTER_HOURS_END` 사용)
10. `daily_time_scheduler.py` — NXT 페이즈명 "애프터마켓" 통일 ("애프터마켓 지속" 제거) + 18:00 엔트리/상수/분기 제거
11. `jif_countdown_design.md` 3.2절 KRX 장마감 매핑 오류 수정 (44=300초/43=60초/42=10초 — API 문서 기준)

**재심층 사전조사에서 발견·보고한 태스크 파일 오차 3건**:
- 발견 A: Step 1-9 상수명 `KRX_AFTER_CLOSE_START` → 실제 `KRX_AFTER_HOURS_END` 사용 (태스크 파일이 예견한 사항)
- 발견 B: 기존 테스트 2건 S-1에서 깨짐 → 규칙 0-1 준수를 위해 S-2 범위 일부를 S-1로 이동하여 수정
- 발견 C: `_KRX_COUNTDOWN_MAP` 라벨을 "장마감" 대신 "종가 동시호가 종료" 등 명확한 이름 사용 (P21/P23 — "장마감" 페이즈명과 혼동 방지)

**수정 파일 5개**:
- 백엔드 3개: `engine_state.py`, `engine_ws_dispatch.py`, `daily_time_scheduler.py`
- 테스트 2개: `test_engine_ws_dispatch.py` (1건 변경 + MagicMock import 추가), `test_daily_time_scheduler.py` (기존 6건 수정 + 신규 4 클래스 20건 추가)
- 문서 1개: `jif_countdown_design.md` (3.2절 매핑 오류 수정)

**검증**:
- `pytest backend/tests/` 2802 passed (이전 2782에서 20개 증가 — 신규 테스트 20건 반영, 기존 테스트 6건 수정)
- `python -W error::RuntimeWarning main.py` 런타임 기동 18초 — RuntimeWarning 없음, 타임테이블 33항목 빌드 확인, 스케줄러 정상 시작
- 잔존 프로세스 0건 확인

**화면 영향 (S-1 완료 후)**:
- 상단 헤더 칩: 카운트다운 코드 수신 시 즉시 "정규장 장마감 5분 전" 등 상세 카운트다운 표시 (JIF 기반 — 기존에는 무시됨)
- NXT 애프터마켓: 15:40~20:00 단일 "애프터마켓" 표시 (기존 18:00에 "애프터마켓 지속"으로 전환되던 것 제거 — UI 변화 없음, 동일 초록 칩 유지)
- 매수/매도 동작: 영향 없음 (카운트다운은 표시 전용, 주문 차단은 `get_order_time_block_status()` 담당)

**S-2 대기 사항 (프론트엔드 + 테스트 보완)**:
- `header.ts` — `formatCountdown()` "X분 Y초 전" 포맷 확장 (90초 → "1분 30초 전")
- `header.ts` — PHASE_STYLE "애프터마켓 지속" 항목 제거 (dead code — P16)
- `general-settings.ts` — timetable 표시 "18:00 애프터마켓 지속 전환" 항목 제거
- `sector-settings.ts` — 주석 "애프터마켓 지속" 제거
- `test_engine_ws_dispatch.py` — `_JIF_COUNTDOWN_KRX`/`_JIF_COUNTDOWN_NXT` 매핑 완전성 검증 추가
- `test_daily_time_scheduler.py` — override 만료 전환, 카운트다운 엔트리 수 검증 등 보완

**잔존 프로세스**: 없음 (런타임 기동 후 완전 종료 확인).

**다음 세션 대기 사항**: JIF 카운트다운 복구 S-2(프론트엔드 + 테스트 보완) 구현 — 다단계 작업 워크플로우 4세션. 태스크 파일(`docs/plan_jif_countdown.md`) 섹션 4 기반 진행. S-2 착수 전 재심층 사전조사(규칙 0-2) 수행 후 사용자 승인(규칙 0) 받아 Step 2-1~2-3 구현. 참조 문서: `docs/plan_jif_countdown.md`, `docs/jif_countdown_design.md`.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 태스크 파일 작성 (2026-07-23)

**세션**: 다단계 작업 워크플로우 2세션 — `jif_countdown_design.md` 기반 심층 사전조사 + 태스크 파일 작성. 코드 수정 없음 (조사·태스크 작성 전용 세션).

**심층 사전조사 결과 (규칙 0-2 4항목)**:
1. **의존성**: 6개 파일 수정 지점별 의존 호출자/참조자 식별 완료 (태스크 파일 섹션 1.1 표).
2. **영향범위**: 백엔드 3 + 프론트엔드 1 + 테스트 2 = 6파일. 거래 로직 영향 없음 (카운트다운은 표시 전용).
3. **아키텍처 원칙 부합**: P10/P11/P14/P16/P20/P23/P24 부합 확인 (태스크 파일 섹션 1.3 표).
4. **기존 공통 자산 확인**: `calc_countdown()`, `_TIMETABLE` 스케줄러, `_apply_market_phase()`, 시간 상수들 재사용 가능 확인 (태스크 파일 섹션 1.4 표).

**⚠️ 설계 문서 오류 발견 + 바로잡기**:
- 설계 문서 3.2의 KRX 장마감 JIF 매핑이 API 문서(`장운영정보JIF.txt` 114-122줄)와 불일치:
  - 설계: 44=600초(10분), 43=300초(5분), 42=60초(1분) — **오류**
  - API 실제: 44=300초(5분전, 최대), 43=60초(1분), 42=10초(10초) — KRX 장마감 10분전 코드 없음
- 태스크 파일에는 API 문서 기준 올바른 매핑 반영 (섹션 1.5 + Step 1-2).
- S-1 착수 시 설계 문서 3.2 매핑 테이블도 함께 수정 예정 (P10 SSOT — 문서-코드 불일치 해소, Step 1-11).

**산출물**: `docs/plan_jif_countdown.md` (태스크 파일, 427줄). 심층 사전조사 결과 + 2세션 분할 + 11개 구현 Step(S-1) + 3개 구현 Step(S-2) + 테스트 계획 + 런타임 검증 방법 + 사용자 결정 항목 + 착수 전 최종 확인 항목 포함.

**2세션 분할 (태스크 파일 섹션 2)**:
- S-1 (백엔드 핵심): 방안 1 + 3 + 2 + 4-2/4-3. Step 1-1~1-11 (engine_state.py, engine_ws_dispatch.py, daily_time_scheduler.py + 설계 문서 수정). 검증: pytest + 런타임 기동.
- S-2 (프론트엔드 + 테스트 보완): 방안 4-1 + 테스트 정비. Step 2-1~2-3 (header.ts, test_engine_ws_dispatch.py, test_daily_time_scheduler.py). 검증: npm run build + 브라우저 + pytest.

**영향 범위 (6개 파일 + 설계 문서 1)**:
| 구분 | 파일 | 변경 내용 | 세션 |
|------|------|-----------|------|
| 백엔드 | `engine_state.py` | override 필드 추가 | S-1 |
| 백엔드 | `engine_ws_dispatch.py` | JIF 카운트다운 매핑 테이블, `_handle_jif()` 처리, `_JIF_IGNORE_CODES` 정리 | S-1 |
| 백엔드 | `daily_time_scheduler.py` | 카운트다운 임계 상수, 타임테이블 엔트리, countdown 분기, override 헬퍼, get_market_phase override 우선, 맵 보완, 페이즈명 통일, 18:00 엔트리 제거 | S-1 |
| 프론트엔드 | `header.ts` | formatCountdown "X분 Y초 전" 포맷 | S-2 |
| 테스트 | `test_engine_ws_dispatch.py` | 카운트다운 코드 무시→처리 검증 변경 | S-2 |
| 테스트 | `test_daily_time_scheduler.py` | 카운트다운 엔트리·override·맵·페이즈명 테스트 | S-1+S-2 |
| 문서 | `jif_countdown_design.md` | 3.2절 KRX 장마감 매핑 오류 수정 | S-1 |

**거래 로직 영향**: 없음 — 카운트다운은 표시 전용. 매수/매도/주문 차단은 `get_order_time_block_status()` 담당.

**잔존 프로세스**: 없음 (조사·태스크 작성 전용 세션, 런타임 기동 없음).

**다음 세션 대기 사항**: JIF 카운트다운 복구 S-1(백엔드 핵심) 구현 — 다단계 작업 워크플로우 3세션. 태스크 파일(`docs/plan_jif_countdown.md`) 기반 진행. S-1 착수 전 재심층 사전조사(규칙 0-2) 수행 후 사용자 승인(규칙 0) 받아 Step 1-1~1-11 구현. 참조 문서: `docs/plan_jif_countdown.md`, `docs/jif_countdown_design.md`.

---

## 직전 완료 작업 (이전 세션)

### JIF 카운트다운 복구 설계 문서 작성 (2026-07-23)

**세션**: 상단 헤더 KRX/NXT 시간대별 장운영정보(JIF) 카운트다운 상세 표시 누락 문제 조사 + 설계 문서 작성. 코드 수정 없음 (조사·설계 전용 세션).

**산출물**: `docs/jif_countdown_design.md` (설계 문서, 326줄). 4개 방안 + 2세션 분할 계획 + 영향 범위 6개 파일 + 착수 전 최종 확인 항목 2건 포함. 상세 내용은 설계 문서 본문 참조.

---

## 직전 완료 작업 (이전 세션)

### order_time_guard_on 토글 제거 — 대안 A + 옵션 2 (2026-07-23)

**세션**: 6세션에 걸쳐 사용자가 설계한 "체결 불가 시간대 주문 차단" 토글 제거. P10(SSOT)/P16(살아있는 경로)/P23(일관성)/P24(단순성). 시장가 단일 운용에서 OFF의 의미 부재로 인한 제거 결정 (규칙 0-5 엄격 절차 적용).

**문제 배경**: SectorFlow는 시장가 주문만 사용. 체결 불가 시간대(동시호가·장외)에 시장가 주문을 전송해도 체결되지 않음. 토글 OFF의 유일한 효과 = 미체결 주문 적체(P22 위험) + 불필요한 API 호출/에러 로그. 사용자 이득 없음. 토글 ON이 항상 올바른 상태이므로 토글 자체가 무의미.

**사용자 결정**: 대안 A (토글 제거) + 옵션 2 (buy_order_executor.py의 is_krx_after_hours() → is_order_blocked_by_time() 교체). 옵션 2 선택으로 인해 is_krx_after_hours() 함수 정의도 dead code 제거.

**수정 파일 10개**:

백엔드 6개:
- `backend/app/core/settings_defaults.py:131-132` — `order_time_guard_on` 키 + 주석 제거 (2줄).
- `backend/app/services/daily_time_scheduler.py` — `get_order_time_block_status()` 토글 분기 4줄 제거 + docstring 갱신. `is_krx_after_hours()` 함수 정의 제거 (dead code — buy_order_executor.py에서 옵션 2 교체로 인해 실사용 0건).
- `backend/app/services/trading.py:820-831` — `_is_order_time_blocked()` 토글 분기 제거, 서명 `(self, stk_cd: str)` 단순화 (raw_settings 인자 제거). 호출부 2곳(L218 매수, L558 매도) 인자 수정.
- `backend/app/services/engine_service.py` — `_apply_order_time_guard_change()` 전체 제거 (16줄) + L69 호출부 제거.
- `backend/app/db/stock_tables.py:98-105` — `init_cache_tables()`에 idempotent DELETE 쿼리 추가 (`DELETE FROM integrated_system_settings WHERE key = 'order_time_guard_on'`). 스키마 변경 아님 (key-value row 삭제).
- `backend/app/services/buy_order_executor.py` — `_refresh_buyable_prices()`와 `evaluate_buy_candidates()`에서 `is_krx_after_hours()` + `is_nxt_enabled()` 이원화 판별 → `is_order_blocked_by_time(s.code)` 단일 호출로 통일. `_after_hours` 변수 제거.

프론트엔드 2개:
- `frontend/src/pages/general-settings.ts` — `buildOrderTimeGuardRow()` 함수 제거 (18줄) + L702 호출부 + L703 설명 텍스트 + L57 `orderTimeGuardToggle` 변수 선언 + L1210 sync 라인 제거.
- `frontend/src/types/index.ts:231-232` — `order_time_guard_on: boolean;` 필드 + 주석 제거.

테스트 2개:
- `backend/tests/test_daily_time_scheduler.py` — 토글 OFF 케이스 2건 제거 + `is_krx_after_hours` import 제거 + `TestIsKrxAfterHours` 클래스 전체 제거 (8 테스트).
- `backend/tests/test_buy_order_executor.py` — 36곳 `is_krx_after_hours` + `is_nxt_enabled` mock → `is_order_blocked_by_time` mock 교체. (False,False)→False 34곳, (True,False)→True 1곳, (True,True)→False 1곳.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 토글제거 | P10/P24 | 시장가 단일 운용에서 무의미한 토글 제거. 불필요한 분기 3곳 제거 (get_order_time_block_status, _is_order_time_blocked, _apply_order_time_guard_change 전체 제거). 코드 약 50줄 감소. |
| 일관성 | P23 | buy_order_executor.py의 is_krx_after_hours() + is_nxt_enabled() 이원화 판별 → is_order_blocked_by_time() 단일 함수로 통일. is_krx_after_hours() dead code 제거. |
| DB정리 | P10/P21 | integrated_system_settings 테이블에서 order_time_guard_on row 삭제 (idempotent DELETE). DB 잔존 시 코드=무시 vs DB=존재 진실 소스 분리 위험 제거. |

**검증**: `pytest backend/tests/` 2782 passed (이전 2792에서 10개 감소 — 제거한 테스트 10개 반영: TestIsKrxAfterHours 8건 + 토글 OFF 케이스 2건). `python -W error::RuntimeWarning main.py` 런타임 기동 15초+ RuntimeWarning 없음. `npm run typecheck`/`npm run build` 정상. DB에서 order_time_guard_on row 삭제 확인. 잔존 프로세스 0건.

**화면 영향**:
- 설정 페이지: "체결 불가 시간대 주문 차단" 토글 행 사라짐 (설정 항목 1개 감소).
- 상단 헤더 배지: 체결 불가 시간대에 항상 배지 표시 (이전에는 설정 OFF 시 숨김). "지금은 주문 불가 시간"이 항상 보여 더 명확.
- 매수 후보 목록: 양쪽 비활성 시간대(15:20~15:30, 20:00 이후)에 NXT 종목도 후보에서 제외 (옵션 2 적용 — 실제 거래 영향 없음, 어차피 주문 차단).
- 매수/매도 동작: 체결 불가 시간대 주문 안 함 — 기존 토글 ON일 때와 동일 (사용자 체감 차이 없음).

**잔존 프로세스**: 없음 (백엔드 기동 후 종료, 런타임 검증만 수행).

**다음 세션 대기 사항**: 특별한 대기 사항 없음. 필요 시 다음 개선 작업 지시.

## 사용자 결정 변경 (이전 세션 기록 — 2026-07-23)

### 옵션 C → 대안 A (토글 제거) 결정 전환

**검토 배경**: 옵션 C(통합 게이트 방식) 상세 구현 계획 보고 전, 사용자 제기 — "SectorFlow는 시장가 주문만 사용하는데, 체결 불가 시간대에 주문을 넣어도 체결이 안 되면 `order_time_guard_on` 토글 자체가 무의미하지 않은가? ON/OFF와 관계없이 무조건 차단하는 게 더 단순하고 명확하지 않은가?"

**검토 결과 (코드 수정 없음)**:
- 시장가 단일 운용 확인 (trading.py:360-363 매수, 561-568 매도 — `trde_tp="3"`, `order_type="시장가"`, 지정가 경로 없음).
- 체결 불가 시간대 시장가 체결 불가 — 코드 주석에 명시.
- 토글 OFF의 유일한 효과 = 미체결 주문 적체 + 불필요한 API 호출/에러 로그. 사용자 이득 없음.
- 결론: 토글 제거가 P24(단순성)/P10(SSOT)에 부합.

**사용자 결정: 대안 A (토글 제거) + 옵션 2 (buy_order_executor.py 교체)**:
- 6세션에 걸쳐 사용자가 직접 설계한 토글이나, 시장가 단일 운용에서 무의미하다는 검토에 동의.
- 설정 페이지 토글 제거 승인.
- DB row 제거 승인 — 기동 시 자동 정리(idempotent DELETE) 방식.
- 옵션 2 선택: buy_order_executor.py의 is_krx_after_hours() → is_order_blocked_by_time() 교체 (P23 일관성 + is_krx_after_hours() dead code 제거).

**구현 완료**: 위 "직전 완료 작업" 섹션 참조.

## 직전 완료 작업 (이전 세션)

### 주문 일시중단 배지 문구/표시 로직 정비 (2026-07-22)

**세션**: 헤더 "주문 일시중단" 배지 UI/UX 개선. P21/P16/P23. "NXT 전용 구간 (KRX 단독 종목 차단)" 문구의 모호성 해소 및 설정 OFF 시 배지 숨김.

**문제 현상**: 배지 문구 "주문 일시중단(NXT 전용 구간 (KRX 단독 종목 차단))"이 KRX 단독 종목만 차단하는지, NXT/KRX 모든 종목이 일시중단인지 명확하지 않았음. 또한 "체결 불가 시간대 주문 차단" 설정이 OFF인데도 배지가 계속 표시되어 실제 차단 상태와 불일치 (P16 살아있는 경로).

**수정 파일 4개**:
- `backend/app/services/daily_time_scheduler.py` — `get_order_time_block_status()`에서 `order_time_guard_on` OFF 시 `(False, "")` 반환. reason을 `"KRX 단독 종목 차단 · NXT 가능"` / `"KRX·NXT 모두 주문 불가"`로 변경.
- `backend/app/services/engine_service.py` — `apply_settings_change()`에 `_apply_order_time_guard_change()` 추가. `order_time_guard_on` 토글 변경 시 `order_time_blocked` 웹소켓 이벤트 즉시 브로드캐스트.
- `frontend/src/layout/header.ts` — 배지 텍스트를 `⏸ ${reason}`으로 변경. 중복/모호한 `주문 일시중단(` 접두사 제거.
- `backend/tests/test_daily_time_scheduler.py` — 새 reason 및 `order_time_guard_on=OFF` 케이스 테스트 추가/갱신.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 배지문구 | P21/P23 | KRX/NXT 각각 주문 가능 여부를 배지 문구만 보고도 파악 가능. KRX 단독 종목 차단 / NXT 가능, 또는 KRX·NXT 모두 주문 불가로 명시. |
| 배지숨김 | P16 | `order_time_guard_on` OFF 시 `get_order_time_block_status()`가 `(False, "")`를 반환하여 배지를 표시하지 않음. 실제 주문 게이트(`trading.py::_is_order_time_blocked`)와 동일한 설정 기준 적용. |

**검증**: `pytest backend/tests/` 2792 passed. `python -W error::RuntimeWarning main.py` 런타임 기동 15초+ RuntimeWarning 없음. `npm run typecheck`/`npm run build` 정상. 잔존 프로세스 0건.

**화면 영향**:
- NXT-only 시간대(예: 08:00~09:00, 15:40~20:00): `⏸ KRX 단독 종목 차단 · NXT 가능` 표시.
- KRX·NXT 모두 비활성 시간대(예: 15:20~15:30, 20:00 이후): `⏸ KRX·NXT 모두 주문 불가` 표시.
- "체결 불가 시간대 주문 차단" 설정 OFF: 배지 완전히 숨김. **[참고: 다음 세션 대안 A로 토글 제거 예정 — 이 동작은 사라짐]**

**잔존 프로세스**: 없음 (백엔드 기동 후 종료, 런타임 검증만 수행).

**다음 세션 대기 사항**: 특별한 대기 사항 없음 (대안 A 토글 제거는 다음 섹션에서 완료됨).

## 직전 완료 작업 (이전 세션)

### 상단 헤더 인디케이터 순서 재배치 — KRX/NXT 장 상태 칩 좌측 이동 (2026-07-22)

**세션**: 프론트엔드 헤더 UI 개선. P21/P23/P24. 단순 순서 변경 (로직 변경 없음).

**문제 현상**: 상단 헤더의 KRX/NXT 장 상태 칩이 증권사 칩(키움증권/키움실시간) 우측에 배치되어 있었음. KRX/NXT 칩은 장 페이즈명(`KRX 정규장`, `NXT 시간외 종가매매 종료 + 시간외 단일가매매 개시` 등)과 카운트다운(`KRX 정규장 30분 전`) 표시로 인해 가로 너비 변동이 가장 큰 칩. 이 칩이 중간에 있으면 우측의 모든 칩(증권사·설정·업종지수)이 좌우로 밀려 화면이 흔들리는 느낌 발생.

**수정 파일 1개**:
- `frontend/src/layout/header.ts:266-300` — 칩 생성 블록 순서 재배치. KRX/NXT 장 상태 칩과 KRX 알림 칩(서킷브레이커/사이드카)을 증권사 칩 블록 앞으로 이동. avgAmtChip(백그라운드 데이터 갱신)은 KRX/NXT 우측, 증권사 칩 좌측에 배치. modeChip의 `marginRight:auto` 유지 (좌·우 분할점 역할).

**변경 전 (좌→우)**: 로고 · 투자모드 ┃ 데이터갱신 · 키움증권 · 키움실시간 · KRX · NXT · KRX알림 · (이하 동일)
**변경 후 (좌→우)**: 로고 · 투자모드 ┃ KRX · NXT · KRX알림 · 데이터갱신 · 키움증권 · 키움실시간 · (이하 동일)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 헤더재배치 | P21/P23/P24 | KRX/NXT 장 상태 칩을 인디케이터 가장 좌측으로 이동. 가로 너비 변동이 큰 칩이 좌측에서 흡수되어 우측 칩들 위치 안정. 장 운영 상태(거래 가능 여부)가 가장 먼저 보이도록 정보 우선순위 정렬. KRX 알림 칩을 KRX/NXT와 함께 묶어 장 상태 그룹 응집성 향상. |

**검증**: `npm run typecheck` exit 0. `npm run build` exit 0 (763ms). 브라우저 확인 — 개발 서버(5173) 실행 중, KRX/NXT 칩이 키움증권 칩 왼쪽에 배치됨 확인 필요.

**화면 영향**: 상단 헤더 인디케이터 순서 변경. KRX/NXT 칩이 가장 좌측(투자모드 칩 우측 영역의 시작점)에 표시. 장 페이즈/카운트다운 변동 시 우측 칩들이 더 이상 좌우로 밀리지 않음.

**잔존 프로세스**: 없음 (프론트엔드 빌드만 수행, 런타임 기동 없음).

**다음 세션 대기 사항**: 없음. 신규 작업 대기.

## 직전 완료 작업 (이전 세션)

### 단계 B-연계: 프론트엔드 수익률 분모 buy_total_amt 동기화 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 B-연계 (프론트엔드). P22/P23/P21 해결. **수익률 SSOT/P22 일괄 정비 전체 완료 (단계 A·C·B-사전·B-본·B-연계 5세션).**

**문제 현상**: 단계 B-본에서 백엔드 per-trade realized_pnl을 현금 기준(`total_amt - buy_total_amt`)으로 전환. 분자(realized_pnl)는 sellHistory에서 그대로 읽어 자동 동기화되었으나, 프론트엔드 수익률 분모가 `avg_buy_price * qty`(수수료 미포함)로 백엔드 `buy_total_amt`(수수료 포함)와 불일치 (P22 위반).

**수정 파일 2개 (4곳)**:
- `frontend/src/pages/profit-detail-display.ts:149-150` — updateStatistics 가중평균 수익률 분모 `avg_buy_price * qty` → `buy_total_amt`. 주석 "백엔드 현금 기준 buy_total_amt 분모" 갱신.
- `frontend/src/pages/profit-shared.ts:175` — buildSectorDonutRows 업종별 분모 `avg_buy_price * qty` → `buy_total_amt`.
- `frontend/src/pages/profit-shared.ts:205` — buildSectorStockPnl 종목별 분모 `avg_buy_price * qty` → `buy_total_amt`.
- `frontend/src/pages/profit-shared.ts:295` — aggregatePnl 범위 손익 분모 `avg_buy_price * qty` → `buy_total_amt`.

**자동 동기화 (수정 불필요)**: `canvas-sector-donut.ts:202` — buildSectorDonutRows 출력의 `buyTotal` 필드 사용으로 #2 수정 시 자동 동기화.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| B-연계 | P22/P23/P21 | 프론트엔드 수익률 분모 4곳을 백엔드 현금 기준 buy_total_amt로 동기화. 분자(realized_pnl)는 B-본에서 이미 동기화. 백엔드/프론트엔드 공식 완전 일치. |

**검증**: `npm run typecheck` exit 0. `npm run build` exit 0 (2.02s, 76 modules). `npx vitest run` 8 files / 116 tests passed (7.58s). 프론트엔드 테스트는 buildSectorDonutRows/buildSectorStockPnl/aggregatePnl/updateStatistics 직접 커버 테스트 없음 (기존 테스트 영향 없음).

**화면 영향 (테스트모드)**: 수익현황/수익상세 페이지의 업종별 수익률·종목별 수익률·범위 손익 수익률·가중평균 수익률이 **테스트모드에서 약간 낮게** 표시됨 (분모에 매수 수수료 포함으로 분모 증가, 수익률 절대값 미세 감소). **실전모드는 수수료/세금이 0이므로 화면 수치 변화 없음.**

**잔존 프로세스**: 없음 (프론트엔드 빌드/테스트만 수행, 런타임 기동 없음).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 B-연계 섹션(5.2~5.5) 체크리스트 [x] 표시 + 섹션 6 전체 완료 조건 [x] 표시. (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**수익률 SSOT/P22 일괄 정비 전체 완료**:
| 단계 | 세션 | 위반 | 내용 |
|------|------|------|------|
| A | 1 | P10/P22/P21 | buildMonthlyDrilldown이 백엔드 dailySummary 직접 사용 (sellHistory 재집계 제거) |
| C | 2 | P22/P23/P10/P24 | computeWeightedRate 공통 함수 신설 + 7곳 호출부 통일 |
| B-사전 | 3 | P22/P18 | DB 백업 + 마이그레이션 방식 확정 |
| B-본 | 4 | P22/P21/P18/P10 | per-trade realized_pnl/pnl_rate 현금 기준 전환 + 마이그레이션 |
| B-연계 | 5 | P22/P23/P21 | 프론트엔드 분모 buy_total_amt 동기화 |

**다음 세션 대기 사항**: 없음 (일괄 정비 완료). 신규 작업 대기.

## 직전 완료 작업 (이전 세션)

### 단계 B-본: per-trade realized_pnl/pnl_rate 현금 기준 전환 + 마이그레이션 실행 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 B-본 (백엔드/DB). P22/P21/P18/P10 해결. 핵심 로직 변경(규칙 0-4/0-5) — UI 기준 변경 전/후 설명 + 사용자 승인 완료.

**문제 현상**: per-trade realized_pnl/pnl_rate가 순수 차익 기준(`(price - avg_buy_price) * qty`)으로 계산되나, get_total_realized_pnl(합계)은 현금 기준(`total_amt - buy_total_amt`) 사용. 같은 "실현손익"이 두 기준으로 혼재 (P22 위반). 순수 차익은 수수료/세금 미반영으로 실제 체감 수익률과 불일치 (P21 위반).

**수정 파일 3개 + 신규 1개**:
- `backend/app/services/trade_history.py:352-368` — record_sell의 realized_pnl/pnl_rate 공식 현금 기준 전환. `realized_pnl = sell_net - buy_total` (매도 실수령 - 매수 실지출, 수수료/세금 포함). `pnl_rate = round(realized_pnl / buy_total * 100, 2)`. `buy_principal` 변수 제거 (P24 단순성). 주석 "순수 차익" → "현금 기준 실현손익" 갱신.
- `backend/app/services/trade_history.py:517-518` — get_daily_summary의 buy_total 집계를 `avg_buy_price * qty` → `buy_total_amt` 로 변경 (수수료 포함, per-trade와 동일 기준).
- `backend/app/services/trade_history.py:647-650` — build_positions_from_trades docstring "순수 차익" → "현금 기준" 갱신.
- `backend/scripts/migrate_realized_pnl_cash.py` (신규) — trades 테이블 SELL 레코드 현금 기준 마이그레이션 스크립트. 조건: `side='SELL' AND avg_buy_price > 0 AND buy_total_amt > 0`. `realized_pnl = total_amt - buy_total_amt`, `pnl_rate = round(realized_pnl / buy_total_amt * 100, 2)`. idempotent, 스키마 변경 없음, 모드 무관 (P18). 실행 결과: 대상 0건 (현재 SELL 레코드 없음) → 갱신 없음. 향후 매도 시 현금 기준 적용.

**테스트 갱신**: `backend/tests/test_trade_history.py` — `_make_sell_rec` 헬퍼(270-282) + `test_daily_summary_no_duplicate_buy_total`(55-100) + `test_daily_summary_fee_tax_aggregation`(151-202) 주입 데이터 현금 기준으로 갱신.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| B-본 | P22/P21/P18/P10 | per-trade realized_pnl/pnl_rate를 현금 기준으로 전환. get_total_realized_pnl과 동일 기준 단일화. 실전/테스트 모드 동등 (실전은 fee/tax=0이므로 영향 없음). 마이그레이션 스크립트로 과거 데이터 일치 확보 (현재 0건). |

**검증**: `python -m py_compile` 성공. `pytest backend/tests/test_trade_history.py` 64 passed. `pytest backend/tests/` 2790 passed. `python -W error::RuntimeWarning main.py` 런타임 기동 — 앱 시작 완료, RuntimeWarning 에러 없음, 매수 0건/매도 0건 정상 로드.

**화면 영향 (테스트모드)**: 수익현황/수익상세 페이지의 실현손익(원)과 수익률(%)이 **테스트모드에서 더 낮게** 표시됨 (수수료/세금 반영). 예: 7만원 매수→6.9만원 매도 시 기존 −10,000원/−1.43% → 변경 후 −11,589원/−1.66%. **실전모드는 수수료/세금이 0이므로 화면 수치 변화 없음.** 일별 요약 수익률도 현금 기준으로 일관. 프론트엔드 분모 동기화는 단계 B-연계(세션 5)에서 처리.

**잔존 프로세스**: 없음 (백엔드 기동 후 종료, 런타임 검증만 수행).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 B-본 섹션(4.2~4.5) 체크리스트 [x] 표시 — 사전조사 항목·수정 체크리스트·검증·완료조건 모두 완료. (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**다음 세션 대기 사항**:
1. **단계 B-연계 실행 시작 승인** — 프론트엔드 공식 동기화 + 테스트 갱신 (프론트엔드/테스트). tasks.md 섹션 5 기반. 사전조사 항목: 프론트엔드가 sellHistory의 `realized_pnl`/`avg_buy_price`/`qty`를 사용하는 집계 지점, 분모를 `buy_total_amt`(수수료 포함)로 변경 필요 여부 확인. UI 수치 변화(테스트모드 수익률 낮아짐) 사전 안내 포함 (P21).

## 직전 완료 작업 (이전 세션)

### 단계 B-사전: DB 백업 + 마이그레이션 스크립트 설계 확정 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 B-사전 (백엔드/DB 사전 준비). 코드 수정 없음 (DB 백업 + 설계 보고만). P22/P18 준비.

**문제 현상**: 단계 B-본에서 per-trade realized_pnl/pnl_rate 공식을 현금 기준(수수료/세금 포함)으로 전환 예정. 이때 기존 trades 테이블 레코드가 순수 차익 기준으로 남아 과거/현재 데이터 불일치(P22 위반) 발생. 본 세션은 사전 준비(백업 + 마이그레이션 방식 확정).

**수행 작업** (코드 수정 없음):
- DB 백업 (db-backup 스킬): `stocks.db.20260722_230709.backup` (1.2M), `stocks.db-shm.20260722_230709.backup` (32K), `stocks.db-wal.20260722_230709.backup` (0B). 백엔드 미실행 상태에서 안전 백업.
- 사전조사 (규칙 0-2): trades 테이블 SELL 레코드 **0건** 확인. test_positions 3건은 평가손익 필드(pnl_amount/pnl_rate)이며 realized_pnl/buy_total_amt 없음 → 마이그레이션 대상 아님. trades 스키마(stock_tables.py:22-43)에 realized_pnl/pnl_rate/buy_total_amt 필드 모두 존재 → 스키마 변경 불필요.
- 마이그레이션 스크립트 설계 (옵션 2, 사용자 설계 승인 2026-07-22):
  - 대상: `trades` SELL 레코드 전체 (현재 0건, 향후 매도 발생 시 대상)
  - 조건: `side='SELL' AND avg_buy_price > 0 AND buy_total_amt > 0` (유령 데이터/0매입 제외, trade_history.py:340 안전장치와 동일 기준)
  - `realized_pnl = total_amt - buy_total_amt` (현금 기준)
  - `pnl_rate = round(realized_pnl / buy_total_amt * 100, 2)`
  - UPDATE 1건 (트랜잭션 단위), idempotent(멱등), 스키마 변경 없음, 모드 무관(P18)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| B-사전 | P22/P18 (준비) | DB 백업 + 마이그레이션 방식 확정으로 단계 B-본 실행 준비 완료. 과거/현재 데이터 기준 일치 기반 마련. |

**검증**: 코드 수정 없음. DB 백업 파일 3개 존재 확인. 마이그레이션 설계 사용자 승인 확보.

**화면 영향**: 없음. DB 백업 + 설계 보고만 수행.

**잔존 프로세스**: 없음 (DB 백업 + 문서 갱신만, 백엔드 기동 없음).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 B-사전 섹션(3.2~3.5) 체크리스트 [x] 표시 — 사전조사 항목·수정 체크리스트·검증·완료조건 모두 완료. (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**다음 세션 대기 사항**:
1. **단계 B-본 실행 시작 승인** — per-trade realized_pnl/pnl_rate 공식 현금 기준 전환 + 마이그레이션 실행 (백엔드/DB). 사용자 지시 순서: (1) per-trade 생성 공식 현금 기준 변경 → (2) 마이그레이션 스크립트 실행 → (3) 검증. 핵심 로직 변경이므로 규칙 0-4/0-5 적용 — UI 기준 변경 전/후 설명 + 승인 필수.

## 직전 완료 작업 (이전 세션)

### 단계 C: 공통 함수 computeWeightedRate 신설 + 7곳 호출부 통일 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 C (프론트엔드 단독). P22/P23/P10/P24 해결.

**문제 현상**: 동일한 수익률 공식(`Math.round(pnl / buyTotal * 10000) / 100`, 소수 2자리 반올림)이 프론트엔드 7곳에서 독립 구현. 한쪽 공식 변경 시 타측 불일치 위험 (P22/P23 위반). 작업 파일 예상 5곳에서 사전조사 결과 7곳으로 확정 (단계 A로 1곳 감소 + 조사로 3곳 추가 발견).

**수정 파일 4개**:
- `frontend/src/components/common/ui-styles.ts:90-96` — `computeWeightedRate(pnl, buyTotal): number` 공통 함수 신설. 구현: `buyTotal > 0 ? Math.round(pnl / buyTotal * 10000) / 100 : 0`. `fmtRate`/`pnlColor`/`rateColor` 등 동일 성격 공통 함수군 옆에 배치. profit-shared.ts ↔ canvas-sector-donut.ts 순환 참조 방지 (두 파일 모두 ui-styles.ts를 이미 import 중).
- `frontend/src/pages/profit-shared.ts:4,179-187,222-226,242-245,297-299,365-368` — import 라인에 `computeWeightedRate` 추가. 5곳 치환: buildSectorDonutRows(업종별 도넛 행 수익률), buildSectorStockPnl(종목별 수익률 + 업종 합계 수익률), aggregatePnl(범위 손익 집계 수익률), computeHoldingsSummary(보유종목 평가손익 수익률).
- `frontend/src/pages/profit-detail-display.ts:6,149-151` — import 라인에 `computeWeightedRate` 추가. updateStatistics의 가중평균 수익률 1곳 치환.
- `frontend/src/components/canvas-sector-donut.ts:8,203` — import 라인에 `computeWeightedRate` 추가. 도넛 차트 중앙 "누적 수익률" 1곳 치환.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| C | P22/P23/P10/P24 | 수익률 가중 평균 공식을 ui-styles.ts 1곳에서 정의. 7곳 호출부가 모두 공통 함수 사용. 백엔드 공식 변경 시(단계 B) 프론트엔드 동기화 지점 1곳 집중. |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.99s exit 0, `npx vitest run` 8 files / 116 tests passed (8.07s). 공식 동일하므로 화면 수치 변화 없음.

**화면 영향**: 없음. 모든 화면의 수익률(%) 수치가 그대로 표시. 공식을 하나로 모았을 뿐 계산 결과 동일.

**잔존 프로세스**: 없음 (프론트엔드 typecheck/build/vitest만 수행, 백엔드 기동 없음).

**작업 파일 갱신**: `docs/pnl_rate_ssot_tasks.md` 단계 C 섹션을 5곳 → 7곳 실제 내역으로 갱신 (사전조사 항목·체크리스트·검증·완료조건 모두 [x] 표시). (파일 삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제)

**다음 세션 대기 사항**:
1. **단계 B-사전 실행 시작 승인** — DB 백업 + 마이그레이션 방식 확정 (백엔드/DB). tasks.md 섹션 3 기반.
2. **마이그레이션 방식 결정 완료**: **옵션 2(1회 스크립트 실행)** 로 확정 (사용자 결정 2026-07-22). 기동 시 재계산(옵션 1)은 기각. 단계 B-사전 세션에서 DB 백업 후 1회 마이그레이션 스크립트 설계·실행.

## 직전 완료 작업 (이전 세션)

### 단계 A: buildMonthlyDrilldown SSOT 위반 해결 (2026-07-22)

**세션**: 수익률 계산 SSOT/P22 일괄 정비 단계 A (프론트엔드 단독). P10/P22/P21 해결.

**문제 현상**: 수익상세 페이지 "당월 일별 요약" 드릴다운이 백엔드 `dailySummary`의 per-day 수익률을 무시하고 sellHistory 원시 레코드에서 수익률을 재계산. 백엔드 공식 변경 시 드릴다운만 다른 수치 표시 위험 (P10/P22/P21 위반).

**수정 파일 4개**:
- `frontend/src/pages/profit-shared.ts:34-41,302-320` — `DailyDrilldownRow`에서 `buyTotal` 필드 제거 (표시되지 않는 dead data, P16). `buildMonthlyDrilldown` 시그니처 변경: `(sells, buys, yearMonth)` → `(dailySummary, yearMonth)`. dailySummary에서 `yearMonth` 접두사 필터 후 백엔드 per-day rate(`pnl_rate`) 직접 사용, 재계산 제거. `buildChartFromDailySummary`와 동일한 dailySummary 직접 사용 패턴 (P23 일관성).
- `frontend/src/pages/profit-detail-display.ts:19-21,106` — `hotStore` import 추가. `showDrilldown` 호출부를 `buildMonthlyDrilldown(state.sellHistory, state.buyHistory, yearMonth)` → `buildMonthlyDrilldown(hotStore.getState().dailySummary, yearMonth)`로 갱신.
- `frontend/src/pages/profit-detail-mount.ts:9-16,250-269,290-300` — `globalSettingsManager` import 추가. `ensureMonthlyDailySummary` 비동기 헬퍼 신설: mount 시 당월 범위(monthStart~today) dailySummary 조회 후 `hotStore.setState({ dailySummary: data })`. 수익현황 페이지의 `applyDateRange`와 동일한 `api.getDailySummary` + `hotStore.setState` 패턴 (P23). `flushDirtyRender`의 `dirtySummary` 분기에 드릴다운 갱신 추가 (dailySummary 기반이므로 summary 변경 시 드릴다운도 갱신).
- `frontend/src/pages/profit-detail.ts:19-28,147` — `ensureMonthlyDailySummary` import 추가. mount에서 `restoreInitialView` 후 `ensureMonthlyDailySummary(state, todayStr)` 호출.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| A | P10/P22/P21 | 드릴다운 per-day 수익률을 백엔드 dailySummary에서 직접 사용. 프론트엔드 재계산 제거. 수익현황에서 "당일"/"5일" 선택 후 진입해도 드릴다운은 항상 당월 전체 표시 (mount 시 당월 dailySummary 재조회). |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.86s exit 0, `npx vitest run` 8 files / 116 tests passed (9.25s).

**화면 영향**: 수익상세 페이지 "당월 일별 요약" 드릴다운의 수익률(%) 수치가 백엔드 기준값으로 표시. 기존 프론트엔드 재계산값에서 백엔드 dailySummary 값으로 변경. 표시 날짜 범위는 당월 전체로 유지 (수익현황에서 다른 범위 선택 후 진입해도 당월 전체 표시). 매도건수/매수건수/당일손익 수치는 동일 데이터 소스이므로 변화 없음.

**잔존 프로세스**: 없음 (프론트엔드 typecheck/build/vitest만 수행, 백엔드 기동 없음).

**다음 세션 대기 사항** (단계 C 완료로 갱신):
1. **단계 B-사전 전 마이그레이션 방식 사전 결정** — 옵션 1(기동 시 재계산) vs 옵션 2(1회 스크립트 실행). 단계 B-사전 세션 전까지 확정 필요.
2. **단계 B-사전 실행 시작 승인** — DB 백업 + 마이그레이션 방식 확정 (백엔드/DB). tasks.md 섹션 3 기반.

## 직전 완료 작업 (이전 세션)

### 수익률 계산 SSOT/P22 일괄 정비 — 설계 문서 + 작업 파일 작성 (2026-07-22)

**세션**: 다단계 작업 워크플로우 1단계(설계). 코드 수정 없음 (문서 2개 신규 작성).

**배경**: 이전 세션에서 수익상세 페이지 "수익률" 공식 불일치 해결(가중 평균 통일) 후, 심층 조사로 pnl_rate 계산 분산 3개 문제 식별. 본 세션은 설계 단계만 수행 (규칙 0-1 세션당 1단계).

**신규 파일 2개** (삭제됨 — 규칙 11, 일괄 정비 완료 시 계획서 삭제):
- `docs/pnl_rate_ssot_design.md` — 문제 정의(A/B/C), 해결 방향, 영향 범위, 원칙 준수 매핑, 위험/주의사항. 사용자 결정: 문제 B는 B-2(수수료/세금 포함 현금 기준 진짜 수익률)로 확정.
- `docs/pnl_rate_ssot_tasks.md` — 5세션 단계별 체크리스트(A → C → B-사전 → B-본 → B-연계). 사전조사/수정/검증/완료조건 포함.

**식별된 3개 문제**:
| ID | 위반 | 설명 |
|----|------|------|
| A | P10/P22/P21 | `buildMonthlyDrilldown`(profit-shared.ts:332)가 백엔드 dailySummary 무시하고 per-day rate 재계산. 백엔드가 이미 제공하므로 SSOT 위반. |
| B | P22/P21/P18 | pnl_rate가 수수료/세금 미포함(순수 차익). 테스트모드에서만 실제 수익률 과대 표시 → 모드 동등성 위반. 사용자 결정: B-2(현금 기준 통일)로 해결. |
| C | P22/P23 | 동일 pnl_rate 공식이 7곳에서 독립 구현. 공통 함수 computeWeightedRate 신설로 변경 지점 1곳 집중. |

**사용자 결정 사항**:
- 문제 B 해결 방향: **B-2**(수수료/세금 포함 현금 기준 진짜 수익률) 확정. B-1(용어 명확화)은 기각.
- 실행 순서: A → C → B 그대로 유지.

**다음 세션 대기 사항**:
1. **단계 A 실행 시작 승인** — buildMonthlyDrilldown SSOT 위반 해결 (프론트엔드 단독).
2. **단계 B-사전 전 마이그레이션 방식 사전 결정** — 옵션 1(기동 시 재계산) vs 옵션 2(1회 스크립트 실행). 단계 B-사전 세션 전까지 확정 필요.

**검증**: 코드 수정 없음 (문서만 작성). 설계 문서와 작업 파일 간 단계 분할·체크리스트·원칙 매핑 일치 확인.

**화면 영향**: 없음. 문서 작성만 수행.

**잔존 프로세스**: 없음. 다음 세션에서 단계 A 실행 시작 (tasks.md 섹션 1 기반).

## 직전 완료 작업 (이전 세션)

### 수익상세 페이지 통계 "평균 수익률" 가중 평균 통일 (2026-07-22)

**세션**: P22/P21 데이터 정합성 해결 1단계. 수익상세 페이지 내 "수익률" 용어 공식 불일치 해소.

**문제 현상**: 수익상세 페이지에서 같은 기간(당일)을 보고 있는데 두 카드의 수익률이 다르게 표시됨.
- 좌측상단 "당일 손익" 카드: 백엔드 일별 요약 `pnl_rate` = `realized_pnl / buy_total × 100` (금액 기준 가중 평균)
- 우측하단 "평균 수익률" 통계: `sum(건별 pnl_rate) / sellCount` (건수 기준 단순 산술 평균)
- 매도 건들의 매입금액이 서로 다르기 때문에 두 공식 결과가 항상 상이 → 사용자 혼란 (P21 위반), 같은 "수익률" 용어를 두 공식으로 혼용 (P22 위반).

**수정 파일 2개**:
- `frontend/src/pages/profit-detail-display.ts:148` — `avgRate` 계산식을 단순 산술 평균에서 가중 평균으로 변경. `buyTotal = sum(avg_buy_price × qty)`, `avgRate = pnl / buyTotal × 100` (소수 2자리 반올림). 좌측상단 카드가 사용하는 백엔드 공식(`backend/app/services/trade_history.py:527`)과 동일.
- `frontend/src/pages/profit-detail-mount.ts:183,189` — 통계 라벨 "평균 수익률" → "수익률"로 변경 (단순 평균 연상 방지). 주석도 동일 갱신.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 수익률 공식 통일 | P22/P21 | 수익상세 페이지 내 "수익률" 표시를 단일 공식(금액 기준 가중 평균)으로 통일. 좌측상단 카드와 우측하단 통계가 동일 기간에서 동일 수치 표시. |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.18s exit 0.

**화면 영향**: 수익상세 페이지 우측하단 통계의 "수익률" 수치가 변경됨. 기존 단순 평균 → 가중 평균. 좌측상단 "당일 손익" 카드의 %와 동일한 값으로 표시됨. 사용자가 "왜 두 수치가 다르지?" 혼란 해소.

**잔존 프로세스**: 없음 (프론트엔드 typecheck/build만 수행, 백엔드 기동 없음).

## 직전 완료 작업 (이전 세션)

### 문서 정리: audit 문서 최신화 + HANDOVER 미해결 문제 취소선 처리 (2026-07-22)

**세션**: 문서 정리 1단계. 코드 수정 없음 (문서만 업데이트).

**수정 파일 3개**:
- `HANDOVER.md` (197-200줄): "프론트엔드 — 용어 통일 잔존 (F06-10 범위 밖)" 미해결 문제 섹션에 취소선 + 해결 표시 추가. F-06-d 세션에서 이미 해결된 항목들을 문서에 반영 (잔여 "보유주식" 0건).
- `docs/architecture_audit_plan.md` (6곳): F-05/F-06 세션 섹션 파일 표 + 체크리스트 ☐→☑ 완료 표시. F05-01 백엔드 #3 해결 내역 추가. F05-07 보류→해결 (F-06-c/d). F05-08 잔여→완료 (파일 분할 완료). 세션 상태 표 + 진행률 (완료 24→26, 진행중 1→0, 미시작 5→4, 보류 2→1).
- `docs/architecture_audit_tasks.md` (5곳): 세션 현황 표 F-05/F-06 ☐→☑. 진행률 F-05/F-06/백엔드 #3 완료 반영. "잔여 6세션" → "잔여 4세션". F-05/F-06 세션 섹션 파일 [ ]→[x] + 체크리스트 [ ]→[x] + 검증 [ ]→[x].

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 문서 정리 | P21/P23 | audit 문서 2개가 구 버전 상태로 F-05/F-06을 미시작/진행중으로 표시 + HANDOVER 미해결 문제 섹션에 해결된 항목 취소선 누락. 실제 코드 상태(HANDOVER 최신)와 문서 불일치 해결. 잔여 보류 항목(B-13 5건, B21-01, F-03 4건, F-04 파일 분할, F-07)은 명확히 분리하여 추적 정보 보존. |

**검증**: 코드 수정 없음 (문서만 업데이트). 두 audit 파일 간 F-05/F-06 상태 일관성 확인 (모두 ☑ 완료, 진행률 수치 일치).

**화면 영향**: 없음. 문서 정리만 수행.

## 직전 완료 작업 (이전 세션)

### F-05-b: profit-detail.ts 파일 분할 (2026-07-22)

**세션**: F-05 (페이지 파일 분할) 1단계. P24 단순성 해결. F-05-a와 동일한 메인+re-export 패턴.

**수정 파일 4개**:
- `frontend/src/pages/profit-detail.ts` (메인): 674줄 → 166줄. `ProfitDetailState` 인터페이스 (모든 가변 상태를 단일 상태 객체로 관리 — P10 SSOT) + `createState()` 팩토리 + `mount`/`unmount` + `export default`. 분할 파일에서 사용하는 타입(`LowerTab`, `SelectedView`, `ProfitDetailState`) export. F-05-a 메인+re-export 패턴 준수.
- `frontend/src/pages/profit-detail-view.ts` (신규, 52줄): `PROFIT_DETAIL_VIEW_KEY`, `ProfitDetailViewState`, `loadProfitDetailView`, `saveProfitDetailView` 이관. 순수 이동.
- `frontend/src/pages/profit-detail-display.ts` (신규, 215줄): `applyCardStyle` + `updateStatCardSelection` + `updateCardSelection` + `updateDrilldownBtnStyle` + `setTabLabel` + `updateTabLabels` + `showDrilldown` + `filterByDate` + `filterByDateRange` + `updateStatistics` + `showTable` + `persistViewState` 이관. 모든 함수가 `state: ProfitDetailState` 인자를 받도록 시그니처만 변경, 로직 동일.
- `frontend/src/pages/profit-detail-mount.ts` (신규, 326줄): `buildSummaryRow` + `onDrilldownToggle` + `buildFilterRow` + `buildTabRow` + `buildTableContainer` + `buildStatRow` + `restoreInitialView` + `flushDirtyRender` + `subscribeProfitDetailStore` 이관. 모든 함수가 `state` 인자 사용.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F-05-b | P24 | profit-detail.ts 674줄 → 4개 파일 분할 (166/52/215/326줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (라우터 `./pages/profit-detail` 경로 + `export default { mount, unmount }` 시그니처). F-05-a 메인+re-export 패턴 준수 (상태 객체를 인자로 전달 — profit-overview 분할과 동일). |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.18s exit 0, `npx vitest run` 8 files / 116 tests passed (8.94s). 모든 파일 500줄 이하.

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 수익 상세 페이지의 모든 기능(요약 카드 당일/직전/당월/누적 손익, 드릴다운 당월 일별 요약, 매도/매수 탭, 날짜 범위 필터, 종목 검색, 통계 정보, 가상 스크롤 거래내역)이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-05-a: profit-overview.ts 파일 분할 + renderSectorStockPnl 함수 분할 (2026-07-22)

**세션**: F-05 (페이지 파일 분할) 1단계. P24 단순성 해결.

**수정 파일 4개**:
- `frontend/src/pages/profit-overview.ts` (메인): 742줄 → 175줄. `ProfitOverviewState` 인터페이스 (28개 가변 필드를 단일 상태 객체로 관리 — P10 SSOT) + `createState()` 팩토리 + `mount`/`unmount` + `export default`. 분할 파일에서 사용하는 타입을 export. F-06 메인+re-export 패턴 준수.
- `frontend/src/pages/profit-overview-date.ts` (신규, 62줄): `PROFIT_DATE_KEY`, `ProfitDateRange`, `loadProfitDateRange`, `saveProfitDateRange`, `defaultDateRange`, `initDateRange` 이관. 순수 이동.
- `frontend/src/pages/profit-overview-sector-pnl.ts` (신규, 219줄): `createAmountCell` (셀 헬퍼 — 헤더/행 공통, P23 일관성) + `createSectorHeader` (업종 헤더 5컬럼) + `createStockRow` (종목 행 5컬럼) + `renderSectorStockPnl` (orchestrator, 45줄 — 50줄 이하 달성) + `updateExpandToggleBtn` + `buildStockListSection` 이관. `renderSectorStockPnl` 146줄 → 5개 함수로 분할 (createAmountCell 25줄 + createSectorHeader 40줄 + createStockRow 35줄 + renderSectorStockPnl 45줄 + updateExpandToggleBtn 4줄).
- `frontend/src/pages/profit-overview-mount.ts` (신규, 377줄): `renderAccountVals`, `refreshFilteredViews`, `buildLeftColumn`, `buildAccountRows`, `buildAccountPanel`, `buildLowerSection`, `applyDateRange`, `buildProfitChart`, `buildDonutChart`, `flushRender`, `subscribeProfitOverviewStore` 이관. 순수 이동.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F-05-a | P24 | profit-overview.ts 742줄 → 4개 파일 분할 (175/62/219/377줄, 모두 500줄 이하). renderSectorStockPnl 146줄 → 5개 함수 분할 (최대 45줄, 모두 50줄 이하). 순수 이동(move) + 함수 분할만 수행, 동작 변경 없음. 외부 import 경로 유지 (라우터 `./pages/profit-overview` 경로 + `export default { mount, unmount }` 시그니처). F-06 메인+re-export 패턴 준수 (상태 객체를 인자로 전달 — data-table-fixed.ts의 options 인자 패턴과 동일). |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.73s exit 0, `npx vitest run` 8 files / 116 tests passed (8.09s). 모든 파일 500줄 이하, renderSectorStockPnl 45줄 (50줄 이하).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 수익현황 페이지의 모든 기능(일별 수익률 차트, 업종별 도넛 차트, 계좌 현황, 업종별 종목 수익, 전체보기 토글, 상세 분석 버튼)이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### 백엔드 #3: build_account_snapshot_meta accumulated_investment 누락 수정 (2026-07-22)

**세션**: 백엔드 정합성 버그 수정 1단계. P22 데이터 정합성 회복.

**수정 파일 2개**:
- `backend/app/services/engine_account_rest.py:131`: `build_account_snapshot_meta` 반환 dict에 `"accumulated_investment": account_snapshot.get("accumulated_investment")` 1줄 추가. 기존에 누락되어 호출부(engine_account.py:330)에서 `state.account_snapshot["accumulated_investment"]`를 set한 직후 반환 dict로 덮어쓰기(line 350)하면서 값이 사라지던 P22 위반 해결. 실전모드에서는 account_snapshot에 키가 없으므로 None 전달 (P20 폴백 금지 준수 — 0으로 덮지 않음).
- `backend/tests/test_engine_account_rest.py:288-302`: 새 테스트 2개 추가 — `test_accumulated_investment_passed_through` (테스트모드 값 전달 검증), `test_accumulated_investment_none_when_absent` (실전모드 None 전달 검증).

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| 백엔드 #3 | P22 | `build_account_snapshot_meta`가 매번 새 dict 반환 시 `accumulated_investment` 키 누락. 호출부에서 set 후 덮어쓰기로 값 소실 → broadcast가 None 전송. 반환 dict에 키 추가로 단일 흐름 유지 (settlement_engine → state.account_snapshot → broadcast → 프론트엔드). |

**검증**: `py_compile` OK. `pytest test_engine_account_rest.py` 63/63 passed (새 테스트 2개 포함). `pytest test_engine_account.py + test_engine_account_notify.py + test_settlement_verification.py` 62/62 passed. 런타임 기동(`-W error::RuntimeWarning`) 정상 — 에러/Traceback/RuntimeWarning 없음, "누적투자금: 10,000,000원" 정상 로드. 잔존 프로세스 0건.

**화면 영향**: 현재 화면 변화 없음 (프론트엔드 F05-01이 `initial_deposit` 사용 중이며 테스트모드에서는 initial_deposit == accumulated_investment). 향후 프론트엔드가 `accumulated_investment` 직접 사용 시 정확한 누적 투자금 표시 가능.

## 직전 완료 작업 (이전 세션)

### F-06-g (F06-03): ui-styles.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-03 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/ui-styles.ts` (메인): 581줄 → 252줄. 상수(FONT_FAMILY/FONT_SIZE/FONT_WEIGHT/COLOR) + 색상함수(rateColor/pnlColor/strengthColor/hexToRgba) + 기호/포맷함수(changeArrow/fmtRate/fmtComma/fmtWon) + positionTooltip + CELL_BORDER/ROW_HEIGHT/ROW_HEIGHT_PX + 다크폼(createDarkInput/createDarkSelect) + 헬퍼(setDisabled/setDisplay) + `export * from` cells/columns re-export. ColumnDef/COLUMN_WIDTH import 제거 (columns 파일로 이동).
- `frontend/src/components/common/ui-styles-cells.ts` (신규, 211줄): createStockNameCell + applyCell(private 이동) + CELL_PADDING(private 이동) + createHeaderCell + 11개 createCell 함수 (Seq/Code/Price/Change/Rate/Amount/Strength/AvgAmount/Number/Pnl). 메인의 COLOR/FONT_*/rateColor/pnlColor/strengthColor/changeArrow/fmtComma/fmtRate import.
- `frontend/src/components/common/ui-styles-columns.ts` (신규, 148줄): 8개 makeColumn (Seq/Code/Price/Change/Rate/Strength/Amount/AvgAmount) + createStockNameColumn. data-table(ColumnDef) + table-config(COLUMN_WIDTH) + 메인(COLOR) + cells(create* 함수) import.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-03 | P24 | ui-styles.ts 581줄 → 3개 파일 분할 (252/211/148줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (41곳: 컴포넌트 18 + 페이지 14 + 레이아웃 3 + 기타 6). F-06-e(data-table)/F-06-f(setting-row)와 동일한 메인+re-export 패턴. |

**검증**: `npm run typecheck` exit 0, `npm run build` 735ms exit 0, `npx vitest run` 8 files / 116 tests passed (4.18s). 잔여 ui-styles-cells/columns 참조: 메인 re-export(2곳) + columns 내부 import(1곳)만 (외부 누출 없음).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 페이지의 테이블 셀·컬럼·다크폼이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-06-f (F06-02): setting-row.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-02 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/setting-row.ts` (메인): 569줄 → 168줄. 상수(INPUT_WIDTH, TEXT_INPUT_WIDTH) + 공통 유틸(focusNext, applyInputBase, createSpinButtons — inputs에서 import하도록 export 추가) + createSettingRow + createSettingField + createFixedValue + `export * from` inputs/controls re-export. 사용처가 controls로 이동한 setDisabled/FONT_SIZE import 제거.
- `frontend/src/components/common/setting-row-inputs.ts` (신규, 243줄): createNumInput, createMoneyInput, createTextInput, createSelect 이관. 메인의 유틸(focusNext, applyInputBase, createSpinButtons, TEXT_INPUT_WIDTH) import.
- `frontend/src/components/common/setting-row-controls.ts` (신규, 191줄): createToggleBtn, createRadioGroup, createToggleLabelControlsRow 이관. 메인의 createSettingRow + ui-styles(COLOR, FONT_SIZE, setDisabled) import.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-02 | P24 | setting-row.ts 569줄 → 3개 파일 분할 (168/243/191줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (4개 설정 페이지: general/sector/sell/buy-settings). F-06-e(data-table.ts)와 동일한 메인+re-export 패턴. |

**검증**: `npm run typecheck` exit 0, `npm run build` 982ms exit 0, `npx vitest run` 8 files / 116 tests passed (6.07s). 잔여 setting-row 참조: 메인 + inputs + controls(상호 import) + 4 설정 페이지(동일 경로 유지) + docs 역사적 로그.

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 설정 화면(일반/업종/매수/매도)의 입력란·토글·라디오·드롭다운이 동일하게 동작.

## 직전 완료 작업 (이전 세션)

### F-06-e (F06-01): data-table.ts 파일 분할 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-01 (P24 단순성) 해결.

**수정 파일 3개**:
- `frontend/src/components/common/data-table.ts` (메인): 1045줄 → 176줄. 타입/인터페이스 + 공통 유틸리티(triggerFlash, isGroupRow, scoreColor, createColumnWidthManager) + createDataTable 팩토리만 잔류. 유틸리티 함수에 export 추가 (모드 파일에서 import).
- `frontend/src/components/common/data-table-fixed.ts` (신규, 454줄): createFixedMode + CellWithPrevContent 이관.
- `frontend/src/components/common/data-table-virtual.ts` (신규, 454줄): createVirtualScrollMode + RowWithKey 이관.

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-01 | P24 | data-table.ts 1045줄 → 3개 파일 분할 (176/454/454줄, 모두 500줄 이하). 순수 이동(move)만 수행, 동작 변경 없음. 외부 import 경로 유지 (9개 페이지 + ui-styles.ts + 테스트) |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.93s exit 0, `npx vitest run tests/components/data-table.ui.test.ts` 17/17 passed. 잔여 createFixedMode/createVirtualScrollMode 참조: 메인 + 각 모드 파일에서만 (외부 누출 없음).

**화면 영향**: 없음. 순수 파일 분할이며 외부 import 경로가 동일하게 유지되어 모든 페이지가 동일하게 동작.

## 미해결 문제 (발견 즉시 기록)

### P25 전수 조사 — 세션 2 (B1 엔진 코어 루프) 위반 7건 식별 (2026-07-23)
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` 섹션 2(매트릭스) + 섹션 4(세션 2 결과) 참조
- **B1-02-01 (HIGH)**: `engine_loop.py:304` while 루프 본문 내 `is_ws_subscribe_window` 무보호. throw 시 엔진 루프 전체 종료
- **B1-02-02 (MEDIUM)**: `engine_loop.py:374,377` finally 블록 `disconnect_all()`/`disconnect()` 무보호. throw 시 후속 정리 스킵
- **B1-02-03 (MEDIUM)**: `engine_loop.py:387,389` finally 블록 REST 정리 루프 `_reset_client()`/`aclose()` 무보호. 한 증권사 실패 시 나머지 스킵
- **B1-02-04 (HIGH)**: `engine_loop.py:31` `_load_caches_preboot` 무보호. throw 시 엔진 기동 전체 차단
- **B1-02-05 (LOW)**: `engine_ws_dispatch.py:149-153` `_handle_real_00` 내 `on_fill_update`/`_on_fill_after_ws` 무보호. 호출자 의존 — 세션 3에서 확인
- **B1-02-06 (LOW)**: `engine_ws_dispatch.py:162` `_handle_real_balance` 내 `_apply_balance_realtime` 무보호. 호출자 의존 — 세션 3에서 확인
- **B1-02-07 (LOW)**: `engine_lifecycle.py:38` `_refresh_positions_if_dirty` 무보호. 주 호출자는 격리 있으나 engine_service.py:93 경유 시 미확인 — 세션 6에서 확인
- 수정은 별도 승인 세션에서 진행 (조사는 보고까지만)

### P25 전수 조사 — 세션 1 (A1 WS 디스패치) 위반 5건 식별 (2026-07-23)
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` 섹션 2(매트릭스) + 섹션 3(세션 1 결과) 참조
- **A1-01-01 (CRITICAL)**: `ws.ts:193` `_dispatchMessage` 핸들러별 try/catch 없음. 한 핸들러 throw 시 같은 이벤트 후속 핸들러 미실행 + 예외 상위 전파
- **A1-01-02 (CRITICAL)**: `ws.ts:164-174` `_handleBinaryFrame` 루프가 try 내부 → 한 핸들러 throw 시 같은 바이너리 프레임 나머지 이벤트 손실
- **A1-01-03 (MEDIUM)**: `ws.ts:172,181` catch 로그가 핸들러 예외를 "파싱 실패"로 잘못 분류
- **A1-01-04 (HIGH)**: `binding.ts` 33개 핸들러 내부 try/catch 없음. F-02 fix는 listener 루프만 보호, 핸들러 본문은 미보호
- **A1-01-05 (LOW)**: `ws.ts:132-136` 재연결 setTimeout 콜백 try/catch 없음
- 수정은 별도 승인 세션에서 진행 (조사는 보고까지만)

### 프론트엔드 — profit-overview 통계 카드 avgRate 공식 일치 여부 — 해결됨 (2026-07-23 조사)
- ~~`frontend/src/pages/profit-overview-mount.ts:57`가 `filteredSellHistory`를 사용하며, profit-overview 페이지에도 동일한 통계 카드(평균 수익률)가 있는지 확인 필요~~ → 해결 (조사 완료). profit-overview에는 평균 수익률 통계 카드 자체가 없음(avgRate/statAvgRate/updateSummaryCards 0건). profit-overview의 수익률 계산 3곳(도넛 차트/종목 행/업종 헤더) 모두 `computeWeightedRate(pnl, buy_total_amt)` 단일 공식 사용 — profit-detail의 avgRate와 동일. P22/P21 위반 잔존 없음.

### 백엔드 버그 (F-05-a 조사 중 발견) — 해결됨 (2026-07-22)
- ~~`backend/app/services/engine_account_rest.py:125-144` `build_account_snapshot_meta`가 응답 dict에서 `accumulated_investment`를 **누락**~~ → 해결 (백엔드 #3 세션에서 반환 dict에 키 추가).

## 다음 세션 작업

**P25 전수 조사 세션 3 (B2 파이프라인 연산 루프 조사)**:
- 조사 파일: `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `pipeline_gateway.py`
- 조사 범위:
  - `pipeline_compute.py:209,214` create_task 직접 호출 (schedule_engine_task 미사용 — P23 위반 후보)
  - `pipeline_compute.py:247` `while True` 루프 내부 예외 격리
  - `_compute_loop_impl` / `_sector_recompute_loop_impl` 루프 실패 시 전파 경로
  - tick_handlers의 틱 핸들러 예외 전파 경로
  - **세션 2 연계**: B1-02-05/06 (`_handle_real_00`/`_handle_real_balance` 호출부인 pipeline_compute.py:487,492)의 격리 여부 확인
- 조사 보고서: `docs/p25_isolated_failure_investigation.md` 섹션 5에 결과 누적 예정
- 조사만 수행 (코드 수정 없음)

**P25 전수 조사 전체 진행률**: 2/9 세션 완료 (세션 1, 2 완료. 세션 3~9 대기)

**audit 문서에 기록된 잔여 항목 (사용자 지시 시 진행)**:
- B-13 보류 5건 (B13-03/04/06/07/08, LOW/INFO 등급) — `docs/architecture_audit_plan.md` 섹션 7 참조
- B21-01 보류 (암호화 폴백, 사용자 승인 대기 — 보안 동작 변화, UI 기준 설명 필요)
- F-03 보류 4건 (F03-07/08/09/10) — `docs/architecture_audit_tasks.md` F-03 섹션 참조
- F-04 잔여 파일 분할 (stock-classification.ts 1618줄, general-settings.ts 1390줄)
- F-07 미시작 (타입 및 유틸 5개 파일, 총 651줄)

---

## 직전 완료 작업 (이전 세션)

### F-06-d (F06-10 잔존): 용어 통일 마무리 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-10 잔존 2곳 해결 (프로젝트 전역 용어 통일 종료).

**수정 파일 2개**:
- `frontend/src/pages/profit-overview.ts:347`: UI 텍스트 "보유주식 평가금액 (" → "보유 종목 평가금액 (" (F06-10 잔존)
- `frontend/src/pages/profit-shared.ts:426`: 주석 "보유주식 평가금액/평가손익/수익률" → "보유 종목 평가금액/평가손익/수익률" (F06-10 잔존)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-10 잔존 | P23 | F06-10에서 account-labels.ts + sell-position.ts 완료 후 남은 2곳. UI 텍스트 1곳 + 주석 1곳. "보유주식" → "보유 종목" (용어 사전 준수). 프로젝트 전역 "보유주식" 잔존 0건 달성 |

**검증**: `npm run build` 612ms exit 0. 잔여 "보유주식" grep (frontend 전역): 0건 확인.

**화면 영향**:
- 수익 요약 페이지 계좌 현황 표: "보유주식 평가금액 (N종목)" → "보유 종목 평가금액 (N종목)"으로 표시 변경

## 직전 완료 작업 (이전 세션)

### F-06-c (F06-10/11/12): 용어 통일 + 색상 상수화 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-10 (P23 용어), F06-11/12 (P23 색상 상수화) 해결.

**수정 파일 5개**:
- `frontend/src/components/common/ui-styles.ts`: `hexToRgba(hex, alpha)` 공통 헬퍼 추가 (P23 공통 자산 — toast.ts + 향후 재사용)
- `frontend/src/components/common/toast.ts`: TYPE_CONFIG bg/border 8곳 하드코딩 rgba → `hexToRgba(COLOR.*, alpha)` (F06-12)
- `frontend/src/components/common/create-slider.ts`: 우측 트랙 기본색 `'#e9ecef'` → `COLOR.inactiveBg` (F06-11)
- `frontend/src/components/common/account-labels.ts`: "보유주식" → "보유 종목" 6곳 (F06-10)
- `frontend/src/pages/sell-position.ts`: "보유주식" → "보유 종목" 6곳 (주석 2 + 배지 라벨 4, F06-10)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-10 | P23 | UI 라벨 "보유주식" → "보유 종목" (용어 사전 준수). account-labels.ts 6곳 + sell-position.ts 6곳 |
| F06-11 | P23 | create-slider.ts 우측 트랙 하드코딩 `#e9ecef` → `COLOR.inactiveBg` (비활성 영역 의미 부합) |
| F06-12 | P23 | toast.ts TYPE_CONFIG 8곳 하드코딩 rgba → `hexToRgba(COLOR.*, alpha)` 공통 헬퍼 활용. 에러/정보 토스트 테두리 색상 톤이 표준 COLOR 팔레트로 통일 |

**검증**: `npm run build` 618ms exit 0. 잔여 "보유주식" grep: profit-overview.ts 1곳 + profit-shared.ts 1곳 (사용자 지시 범위 밖, 미해결 문제에 기록).

**화면 영향**:
- 계좌 현황 표 라벨: "보유주식 평가 금액" → "보유 종목 평가 금액" 등으로 표시 변경
- 보유 종목 페이지 요약 배지: "📊 보유주식 평가금액 합계" → "📊 보유 종목 평가금액 합계" 등
- 슬라이더 우측 트랙: 미세하게 더 진한 회색 (비활성 영역 의미 강화)
- 에러/정보 토스트 테두리: 기존 어두운 톤 → 표준 COLOR 톤 (약간 더 밝고 선명)

## 해결된 문제 (F-06-c 세션 발견)

### 프론트엔드 — 용어 통일 잔존 (F06-10 범위 밖) — 해결됨 (2026-07-22, F-06-d 세션)
- ~~`frontend/src/pages/profit-overview.ts:347` — `보유주식 평가금액 (` UI 텍스트 (P23 위반)~~ → 해결 ("보유 종목 평가금액 ("로 변경)
- ~~`frontend/src/pages/profit-shared.ts:426` — `// 보유주식 평가금액/...` 주석 (P23 위반)~~ → 해결 ("보유 종목 평가금액/..."로 변경)
- ~~사용자 지시(F06-10)가 account-labels.ts + sell-position.ts로 한정되었으므로 본 세션에서 제외. 다음 세션에서 profit-overview/profit-shared 동시 수정 권장.~~ → F-06-d 세션에서 해결 완료. 잔여 "보유주식" grep 0건 확인.

---

## 직전 완료 작업 (이전 세션)

### F-06-b (F06-06): data-table.ts callbackRan dead code 제거 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. F06-06 (P16 dead code) 해결.

**수정 파일 1개**:
- `frontend/src/components/common/data-table.ts` (1053→1045줄, -8줄): `callbackRan` 플래그 6곳(고정 모드 3곳 + 가상 스크롤 모드 3곳) 제거 → `rafId = -1` 센티넬 방식으로 대체

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-06 | P16 | `callbackRan` dead code — 프로덕션(비동기 rAF)에서는 항상 `false`로 남아 조건문이 항상 true인 dead code. 단, 테스트 환경(`vitest.setup.ts` 동기 rAF mock)에서는 살아있는 경로. 근본 원인: 프로덕션-테스트 rAF 동작 불일치. 해결: `rafId = -1` 센티넬을 rAF 호출 전에 설정하여 양 환경에서 동일하게 작동. `callbackRan` 6곳 전부 제거. 테스트 코드는 변경 없음. |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.77s exit 0, `npx vitest run tests/components/data-table.ui.test.ts` 17 tests passed (380ms). 잔여 `callbackRan` 참조 grep 0건 확인.

**화면 영향**: 없음. 렌더링 스케줄링 내부 로직만 변경하며, 테이블 표시/업데이트/플래시 등 사용자에게 보이는 동작은 동일.

## 다음 세션 작업

**잔여 F-06 (별도 세션 each)**:
- F06-01: `data-table.ts` 파일 분할 (1045줄 → ~500줄, fixed/virtual 모드 분리)
- F06-02: `setting-row.ts` 파일 분할 (569줄, 입력란 그룹 분리 검토)
- F06-03: `ui-styles.ts` 파일 분할 (564줄, 셀/컬럼 팩토리 분리 검토)
- F06-10 잔존: profit-overview.ts:347 + profit-shared.ts:426 "보유주식" → "보유 종목" (미해결 문제 참조)

---

## 직전 완료 작업 (이전 세션)

### F-06-a (F06-07/08): 공통 컴포넌트 dead code 제거 (2026-07-22)

**세션**: F-06 (P3 — 공통 컴포넌트) 1단계. dead code 2건 제거.

**수정 파일 2개**:
- `frontend/src/components/common/ui-styles.ts` (599→564줄, -35줄): `createStockNameColumnWithSectorLookup` 함수 제거 + unused import 제거 (`hotStore`, `normalizeStockCode`)
- `frontend/src/components/common/setting-row.ts` (635→569줄, -66줄): `createWsStatusBadge` + `createWsToggleGroup` 함수 제거

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F06-07 | P16 | `createStockNameColumnWithSectorLookup` dead code — `createStockNameColumn`(사용처 7개)과 기능 중복, 정의 외 호출 0건. 제거 |
| F06-08 | P16 | `createWsStatusBadge` + `createWsToggleGroup` dead code — 정의 외 호출 0건. 제거. F06-09(증권사 색상/이름 중복 정의 P10) 동시 해결 (brokerColors/brokerNames 하드코딩 함께 제거) |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.40s exit 0. 잔여 참조 grep 0건 확인 (createStockNameColumnWithSectorLookup / createWsStatusBadge / createWsToggleGroup).

**화면 영향**: 없음. 제거된 함수는 어떤 페이지에서도 호출되지 않았으므로 UI 변화 없음.

## 다음 세션 작업

**잔여 F-06 (별도 세션 each)**:
- F06-01: `data-table.ts` 파일 분할 (1054줄 → ~500줄, fixed/virtual 모드 분리)
- F06-02: `setting-row.ts` 파일 분할 (569줄, 입력란 그룹 분리 검토)
- F06-03: `ui-styles.ts` 파일 분할 (564줄, 셀/컬럼 팩토리 분리 검토)
- F06-10 잔존: profit-overview.ts:347 + profit-shared.ts:426 "보유주식" → "보유 종목" (미해결 문제 참조)

---

## 직전 완료 작업 (이전 세션)

### F-05-c (F05-08): 수익 페이지 컬럼 정의 분할 (2026-07-22)

**세션**: F-05-c (P3 — 수익 페이지) 1단계. F05-08 (파일 길이) 해결.

**수정 파일 3개**:
- `frontend/src/pages/profit-columns.ts` (신규, 111줄): 컬럼 정의 3개 이동 (BUY_COLS/SELL_COLS/createDrilldownCols)
- `frontend/src/pages/profit-shared.ts` (598→493줄, -105줄): 컬럼 정의 3개 제거 + unused import 6개 제거 (ColumnDef/fmtComma/createStockNameColumn/createCodeCell/createNumberCell/hotStore)
- `frontend/src/pages/profit-detail.ts` (672→674줄, +2줄): import 분할 (BUY_COLS/SELL_COLS/createDrilldownCols → profit-columns, 나머지 → profit-shared 유지)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F05-08 | P24 | `profit-shared.ts` 598줄 (500줄 초과) → 493줄 달성. 컬럼 정의 3개를 신규 `profit-columns.ts` (111줄)로 분할 |

**검증**: `npm run typecheck` exit 0, `npm run build` 1.07s exit 0 (profit-shared 13.84 kB, profit-detail 12.65 kB, profit-overview 21.94 kB). 잔여 참조 grep: profit-shared.ts에서 BUY_COLS/SELL_COLS/createDrilldownCols 0건 확인.

**화면 영향**: 없음. 수익 상세 페이지 매수/매도/드릴다운 테이블 표시 동일. 구조 개선만 수행.

## 다음 세션 작업

**잔여 (별도 세션 필요)**:
- `profit-overview.ts` 742줄 (500줄 초과) — `renderSectorStockPnl` 146줄 (135-280줄, P24 50줄의 2.9배) 분할 포함. 업종 그룹 헤더 + 종목 행 렌더 로직을 헬퍼로 분할.
- `profit-detail.ts` 674줄 (500줄 초과) — 별도 세션에서 추가 분할 검토.
- F05-07 "보유주식" → "보유 종목" 용어 통일 잔존: profit-overview.ts:347 + profit-shared.ts:426 (account-labels.ts, sell-position.ts는 F06-10에서 완료).

## 작업 여력

F-05-c(F05-08) 완료 후 작업 여력: **충분**. 잔여 profit-overview.ts/profit-detail.ts 파일 길이 분할 및 renderSectorStockPnl 분할은 규칙 0-1 세션당 1단계 준수를 위해 별도 세션에서 진행 권장.

---

## 직전 완료 작업 (이전 세션)

### F-05-a: 수익 페이지 폴백/중복/비동기 안전 (7건 해결, 2026-07-22)

**세션**: F-05 (P3 — 수익 페이지) 전반부. F-05-b(후반)는 다음 세션에서 진행.

**수정 파일 3개**:
- `frontend/src/pages/profit-shared.ts` (569→598줄): 공통 함수 추가(`buildSectorDonutRows`, `filterTradeRows`), 폴백 제거(F05-01/02)
- `frontend/src/pages/profit-overview.ts` (718→698줄): 중복 함수 제거(`buildSectorDonutData`, `filterSellHistoryByDate`), catch 로깅(F05-03/04), 레이스 가드(F05-11)
- `frontend/src/pages/profit-detail.ts` (667→654줄): 중복 함수 제거(`filterRows`), catch 로깅(F05-03/04)

**해결 건**:
| ID | 위반 | 설명 |
|----|------|------|
| F05-01 | P20 | `accumulated_investment ?? initial_deposit ?? 0` 3단 폴백 → `initial_deposit ?? 0` (테스트모드 동일 값) |
| F05-02 | P20 | `orderable ?? Math.max(0, deposit - todayBuyAmt)` 폴백 → `orderable ?? 0` (백엔드 항상 전송) |
| F05-03 | P20 | save 함수 `catch { }` 빈 블록 → `console.warn` 로깅 |
| F05-04 | P20 | load 함수 `catch { return null }` → `console.warn` 로깅 |
| F05-05 | P10/P23 | `buildSectorDonutData` 중복 → `buildSectorDonutRows` shared SSOT, `buildSectorStockPnl`이 재사용 |
| F05-06 | P23 | `filterSellHistoryByDate`/`filterRows` 중복 → `filterTradeRows` shared SSOT |
| F05-11 | P19 | `applyDateRange` 레이스 가드 추가 (`_applyDateRangeSeq` 시퀀스) |

**검증**: `npm run typecheck` exit 0, `npm run build` 2.06s exit 0, 잔여 참조 grep 0건. 브라우저 확인 권장.

---

## 직전 완료 작업 (이전 세션)

### F-04-e: P2 — stock-classification.ts + general-settings.ts 함수 분할 11건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/stock-classification.ts` (1617→1618줄, +1줄): F04-01 함수 4개 50줄 초과 분할 — **P24**
  - `buildTripleHeader` (71줄) → `buildHeaderLeft`/`buildHeaderCenter`/`buildHeaderRight` + 본문
  - `buildSectorManageCard` (280줄) → 여러 빌더로 분할 + **중복 퍼지 검색 로직 추출** (F04-16 해결)
  - `buildTripleCenter` (231줄) → 여러 빌더로 분할
  - `mount` (103줄) → `handleStockClassificationChange`/`handleStockDataChange`/`handleUiStoreChange` + 본문
- `frontend/src/pages/general-settings.ts` (1438→1390줄, 48줄 감소): F04-02/F04-04 함수 7개 50줄 초과 분할 — **P24**
  - `renderTimeSettingsTab` (217줄) → `buildBuyTimeRow`/`buildSellTimeRow`/`buildTimetableRow`(3행 중복 제거)/`buildConfirmedDownloadRow`/`buildFixedTimesBox`/`buildSubscribeMaxRow` + 본문
  - `renderAutoTradeTab` (328줄) → 14개 빌더로 분할 (`buildMasterToggleRow`, `buildAutoBuyRow`, `buildAutoSellRow`, `buildOrderTimeGuardRow`, `buildRiskManagerMasterRow`, `buildDailyLossRow` 등)
  - `renderTelegramTab` (87줄) → `buildTeleToggleRow`/`buildTeleInputRows`/`buildTeleSaveRow`/`buildTeleCommandTable` + 본문
  - `renderTestVirtualSection` (101줄) → `buildTestVirtualInputRow`/`buildTestVirtualSaveRow`/`buildTestVirtualInfoWrap`/`buildTestVirtualResetWrap` + 본문
  - `renderApiFields` (65줄) → `buildApiInputRows`/`buildApiSaveRow` + 본문
  - `syncFromSettings` (129줄) → `syncToggleInputRow`(공통 패턴 5회 반복 추출)/`syncRiskManager`/`syncTimetables`/`syncAutoTradeTab`/`syncTelegramTab`/`syncAccountTab`/`syncApiSettingsTab` + 본문 — **P23 DRY**
  - `mount` (67줄) → `buildTabPanels` + 본문

**해결 원칙**: P23 (일관성 — syncToggleInputRow 공통 패턴 추출, buildTimetableRow 3행 중복 제거), P24 (단순성 — 함수 50줄 이하)

**검증**:
- `npm run build` (tsc -b + vite build) — 성공 (2.20s, exit code 0)
- 분할된 11개 함수 모두 50줄 이하 확인 (Python 스크립트로 전수 검증)
- 빌드 에러 4건 발생 후 즉시 해결 (unused 모듈 변수 6개 제거: `timetableResetH/M`/`timetableWsH/M`/`timetableKrxH/M` — 읽히는 곳 없는 dead code, `buildTimetableRow` 타입 좁히기)

**화면 영향**: 없음. 업종분류 페이지 + 일반설정 페이지 모든 탭 표시/입력/저장 동작 동일. 구조 개선만 수행.

**부수적 정리**:
- F04-16 (P23) 해결: fuzzy 검색 로직 중복 → 공통 함수 추출 (F-04-a 보류 항목 해결)
- F04-02/F04-04 (P24) 해결: general-settings.ts 함수 7개 50줄 초과 → 모두 분할 (F-04-b 보류 항목 해결)
- F04-01/F04-03 (P24) 해결: stock-classification.ts 함수 4개 50줄 초과 → 모두 분할 (F-04-a 보류 항목 해결)
- unused 모듈 변수 6개 제거 (timetableResetH/M, timetableWsH/M, timetableKrxH/M — 쓰이지 않는 dead code)

**참고**: 파일 자체는 여전히 500줄 기준 초과 (stock-classification.ts 1618줄, general-settings.ts 1390줄). 본 세션은 "함수 분할"에 한정했으며, "파일 분할(멀티 파일)"은 별도 세션에서 다단계 워크플로우 적용 필요. 현재까지의 F-04 서브세션(a~e)은 모두 함수 단위 분할에 집중.

---

### F-04-d: P2 — sector-settings.ts 구조 분할 2건 (2026-07-22)

**수정 파일 1개**:
- `frontend/src/pages/sector-settings.ts` (503→466줄, 37줄 감소): F04-05 `mount()` 261줄 → 24줄, 7개 빌더 함수 + 2개 구독 함수 분할 (buildFilterSection/buildThresholdSection/buildReceiveProgressSection/buildCutoffSection/buildMaxScoreDisplay/buildBonusSection/buildMaxTargetsSection + startUiStoreSubscription/startHotStoreSubscription) — **P24**. F04-17 파일 503줄 → 466줄 (500줄 기준 해결) — **P24**. 가산점 슬라이더 3블록 중복 (각 13줄 × 3 = 39줄, 슬라이더 설정 완전 동일) → `createBonusSliderBlock` 헬퍼 1개 + 호출 3줄로 통합, 기존 `createBonusSliderRow` 제거 — **P23/P24**

**해결 원칙**: P23 (일관성 — buy-settings.ts 분할 패턴과 동일), P24 (단순성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (3.94s, exit code 0)
- 모든 함수 50줄 이하 (최장 buildReceiveProgressSection 39줄, createBonusSliderBlock 38줄)
- 파일 466줄 (500줄 기준 충족)
- 잔여 `createBonusSliderRow` grep 0건, `createDualLabelSlider` 직접 호출 1건(헬퍼 내)만

**화면 영향**: 없음. 업종순위 설정 패널 표시/입력/저장 동작 동일. 구조 개선만 수행.

**보류 항목 (F-04-d 범위외, 추후 세션)**:
- F-04-e (별도): stock-classification.ts + general-settings.ts 파일 분할 (구조 변경, 다단계 워크플로우 적용)

---

### F-04-c: P2 — 매수/매도 설정 페이지 buy-settings.ts + sell-settings.ts 4건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/buy-settings.ts` (425→452줄, +27줄): F04-12 `Number() || 기본값` 폴백 11건 → `??` (nullish coalescing). **가산점 점수 0 설정 후 새로고침 시 1.0으로 잘못 표시되는 버그 수정** (boost_high/order/program/trade_amount_score 4건). 나머지 7건(rise_pct/fall_pct/min_strength/max_daily_amt/max_stock_cnt/buy_amt/buy_interval_sec)도 동일 패턴으로 통일 — **P20/P21**. F04-06 `mount()` 233줄 → 5개 섹션 빌더 분할 (buildBuyBlockSection/buildBoostSection+buildBoostOrderBlock/buildBuyAmountSection/buildRebuySection/buildBuyIntervalSection), mount 본문 20줄 — **P24**. F04-07 `syncFromSettings` 92줄 → 5개 동기화 함수 분할 (syncBuyBlock/syncBoost/syncBuyAmount/syncRebuy/syncBuyInterval), 본문 13줄 — **P24**
- `frontend/src/pages/sell-settings.ts` (174→181줄, +7줄): F04-13 `Number() || 기본값` 폴백 5건 → `??` (일관성, 동작 버그 없음) — **P20**. F04-07 `mount()` 80줄 → 2개 섹션 빌더 분할 (buildSellTypeSection/buildSellIntervalSection), mount 본문 17줄 — **P24**

**해결 원칙**: P20 (폴백 금지), P21 (사용자 투명성 — 가산점 0 표시 버그), P24 (단순성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (2.05s, exit code 0)
- 잔여 `Number() ||` 폴백 grep 0건
- 모든 함수 50줄 이하 (최장 buildSellTypeSection 49줄)

**화면 영향**:
- 매수 가산점 점수 0 설정 시: 이전 화면 1.0 잘못 표시 → 이제 0 올바르게 표시 (버그 수정)
- 매수/매도 설정 페이지 표시/저장 동작: 동일 (구조 개선만, 사용자 동작 변화 없음)

**보류 항목 (F-04-c 범위외, 추후 세션)**:
- F04-14 (P23, INFO): 저장 호출 패턴 3종 혼재 (buy/sell: saveHelper.saveImmediate 미await / general: async/await saveSection / sector: autoSave 디바운스) — saveSection이 내부 try/catch로 reject하지 않으므로 안전. F-07 범위(settings-save.ts)와 연계 검토 권장
- F-04-e (별도): stock-classification.ts + general-settings.ts 파일 분할 (구조 변경, 다단계 워크플로우 적용)

---

### F-04-b: P2 — 설정 페이지 general-settings.ts + sector-settings.ts 4건 (2026-07-22)

**수정 파일 2개**:
- `frontend/src/pages/general-settings.ts` (1453→1448줄, 5줄 감소): F04-20 `.then()` 패턴 12개 → async/await 통일 (handleMasterToggle, dailyLoss/Rate/Profit/ProfitRate/ConsecLoss Input onChange 5개 + onToggle 5개, subscribeMaxInput onChange) — **P23**. F04-21 구독/정리를 `startSettingsSubscription`/`destroySettingsPage` 표준 유틸로 전환 (buy-settings/sell-settings와 동일 패턴) — **P23**. F04-23 거래일 조회 실패 시 조용한 폴백 → 사용자 알림 토스트 추가 ("거래일 조회 실패 — 거래일로 간주하여 자동매매를 허용합니다") — **P20/P21**
- `frontend/src/pages/sector-settings.ts` (509→501줄, 8줄 감소): F04-22 `initSettingsPage`/`startSettingsSubscription`/`destroySettingsPage` 표준 유틸로 전환 + **onSync 콜백 누락 해결** (기존 `createAutoSaveHelper(settingsMgr)`는 onSync 없이 생성 → 저장 후 동기화 누락 버그) — **P23**

**해결 원칙**: P20 (폴백 금지), P21 (사용자 투명성), P23 (일관성)

**검증**:
- `npm run typecheck` (tsc --noEmit) — 성공 (exit code 0)
- `npm run build` (vite build) — 성공 (1.94s, exit code 0)

**화면 영향**:
- 설정 저장 동작: 동일 (토글/입력 저장 방식 변함 없음)
- 거래일 조회 실패 시: 이전 화면 알림 없음 → 이제 "거래일 조회 실패" 토스트 표시 (자동매매는 여전히 거래일로 간주하여 허용)
- 업종순위 설정 저장 후: 이전 화면 갱신 누락 가능 → 이제 저장 후 즉시 갱신 (onSync 콜백 연결)

**보류 항목 (F-04-b 범위외, 추후 세션)**:
- F04-02/F04-04 (P24): general-settings.ts 파일 1448줄 / 함수 7개 50줄 초과 — 파일 분할은 별도 세션 필요 (구조 변경)
- F04-05 (P24): sector-settings.ts mount 함수 길이 — 분할 검토
- F04-06/F04-07 (P24): buy-settings/sell-settings 함수 길이 — 분할 검토
- F04-12/F04-13 (P20): buy-settings/sell-settings `Number() || 0` 폴백 — 사용자 설계 로직 판단 필요

---

### F-04-a: P2 — 설정 페이지 stock-classification.ts 5건 (2026-07-22)

**수정 파일 1개** (1617→1597줄, 20줄 감소):
- `frontend/src/pages/stock-classification.ts`: F04-08 `_testSetState` dead code 제거 (10줄, 사용처 없는 테스트 헬퍼) — **P16**. F04-09 전역 이벤트 리스너(`window mouseup`, `detailTableRef keydown`)를 명명된 핸들러로 변경 후 unmount 시 `removeEventListener` 제거 (메모리 누수 방지) — **P19**. F04-10 `_mounted` 플래그 추가, `onMoveStock` async 응답 후 store 업데이트 전 가드 (race condition 방지) — **P19**. F04-11 외부 미사용 export 9개 제거 (`parseBatchInput`, `resolveToken`, `getMoveSource`, `getMovableCount`, `createChip`, `addToStaging`, `removeFromStaging`, `clearStaging`, `buildMoveMessage` — 모두 파일 내부에서만 사용) — **P16/P24**. F04-19 제거된 코드 참조 주석 2건 정리 (`// import ... (removed)`, `// buildSchedulerCard removed.`) — **P23**

**해결 원칙**: P16 (살아있는 경로), P19 (비동기 누락/메모리 누수), P23 (주석 정리), P24 (단순성)

**검증**:
- `npm run build` (tsc -b + vite build) — 성공 (exit code 0)
- 타입 오류 없음, 빌드 산출물 정상 생성

**화면 영향**: 없음. 업종분류 페이지 표시/동작 동일. 구조 개선만 수행.

**보류 항목 (F-04-a 범위외, 추후 세션)**:
- F04-01/F04-03 (P24): stock-classification.ts 파일 1597줄 / 함수 4개 50줄 초과 (buildSectorManageCard 278줄, buildTripleCenter 231줄, mount 103줄, buildTripleHeader 71줄) — 파일 분할은 별도 세션 필요 (구조 변경)
- F04-15 (P10): 로컬 캐시/파생 상태 (cachedSectorStocksRef, cachedAllStocksMap, stockNameIndex, stagingSet, selectedStocks) — 성능 최적화 목적이므로 판단 필요
- F04-16 (P23): fuzzy 검색 로직 중복 (612-628줄, 684-694줄) — 공통 함수 추출 검토
- ~~F04-18 (P21): 업종 삭제 시 사용자 명시적 알림 부재 — 경미~~ → 해결 (2026-07-23 조사). `onDeleteSector`에 사전 확인 팝업(업종명+영향 명시) + 사후 성공/실패 토스트 + warning alert 3중 알림 구현됨. P21 위반 잔존 없음.

---

## 현재 진행 상황

### 아키텍처 전수 조사 진행률: 30/30 세션 완료 (100%, F-04-e 완료)

| 상태 | 세션 |
|------|------|
| 완료 | B-01~B-12, B-14~B-23, F-01, F-02, F-03, F-04 |
| 부분 완료 | B-13 (3건 해결, 5건 보류 LOW/INFO), F-04 (F-04-a 5건 + F-04-b 4건 + F-04-c 4건 + F-04-d 2건 + F-04-e 11건 해결, 잔여 파일 분할 별도) |
| 미시작 | F-05, F-06, F-07 |

**다음 세션**: F-05 (P3 — 수익 페이지 profit-overview.ts + profit-detail.ts + profit-shared.ts)

---

## 미해결 문제

### F-04-e 보류 항목 (F-04-e 범위외, 추후 세션)
- F04-01/F04-03 파일 분할 (P24): stock-classification.ts 1618줄 — 함수 분할은 완료, 파일 자체는 500줄 기준 초과. 멀티 파일 분할은 별도 세션 필요 (다단계 워크플로우)
- F04-02/F04-04 파일 분할 (P24): general-settings.ts 1390줄 — 함수 분할은 완료, 파일 자체는 500줄 기준 초과. 멀티 파일 분할은 별도 세션 필요 (다단계 워크플로우)

### F-04-d 보류 항목 (F-04-d 범위외, 추후 세션)
- ~~F-04-e (별도): stock-classification.ts + general-settings.ts 함수 분할~~ — **F-04-e 해결** (11건 함수 분할 완료, 파일 분할은 잔여)

### F-04-c 보류 항목 (F-04-c 범위외, 추후 세션)
- F04-14 (P23, INFO): 저장 호출 패턴 3종 혼재 (buy/sell: saveHelper.saveImmediate 미await / general: async/await saveSection / sector: autoSave 디바운스) — saveSection이 내부 try/catch로 reject하지 않으므로 안전. F-07 범위(settings-save.ts)와 연계 검토 권장
- ~~F-04-e (별도): stock-classification.ts + general-settings.ts 함수 분할~~ — **F-04-e 해결** (11건 함수 분할 완료)

### F-04-b 보류 항목 (F-04-b 범위외, 추후 세션)
- ~~F04-02/F04-04 (P24): general-settings.ts 함수 7개 50줄 초과~~ — **F-04-e 해결** (7개 함수 모두 분할, 파일 1448→1390줄)
- F04-06/F04-07 (P24): buy-settings/sell-settings 함수 길이 — 분할 검토
- F04-12/F04-13 (P20): buy-settings/sell-settings `Number() || 0` 폴백 — 사용자 설계 로직 판단 필요
- ~~F04-05 (P24): sector-settings.ts mount 함수 길이~~ — **F-04-d 해결** (mount 261→24줄)
- ~~F04-17 (P24): sector-settings.ts 파일 길이~~ — **F-04-d 해결** (503→466줄)

### F-04-a 보류 항목 (F-04-a 범위외, 추후 세션)
- ~~F04-01/F04-03 (P24): stock-classification.ts 함수 4개 50줄 초과~~ — **F-04-e 해결** (4개 함수 모두 분할)
- F04-15 (P10): 로컬 캐시/파생 상태 — 성능 최적화 목적이므로 판단 필요
- ~~F04-16 (P23): fuzzy 검색 로직 중복~~ — **F-04-e 해결** (공통 함수 추출)
- ~~F04-18 (P21): 업종 삭제 시 사용자 명시적 알림 부재 — 경미~~ → 해결 (2026-07-23 조사). `onDeleteSector`에 사전 확인 팝업 + 사후 토스트 + warning alert 3중 알림 구현됨. P21 위반 잔존 없음.

### F-03 보류 항목 (B그룹 4건, 추후 검토)
- F03-07 (P20/P22): sell-position.ts:59,73 — `sectorStock?.cur_price ?? p.cur_price` 폴백 (사용자 설계 로직, 규칙 0-5 적용 대상)
- F03-08 (P24): sector-stock.ts 653줄 — 500줄 기준 초과, 분할 시 별도 세션 필요
- F03-09 (P24): computeRows(115줄)/connectedCallback(263줄)/updateBadges(79줄)/mount(192줄) — 50줄 기준 초과
- F03-10 (P23): filterStocksBySearch가 페이지 파일에 정의, buy-target.ts 크로스 사용 — utils/ 이동 검토

### F-03 범위외 발견 (F-06 공통 컴포넌트 세션에서 처리)
- F03-11 (P16): card-header.ts:8-24 `createCardHeader` (margin 없는 버전) 사용처 없음, `createCardHeaderWithMargin`만 사용

### F-02 발견 경미 사항 (정보만 기록, 수정 여부 사용자 판단)
- **main.ts**: 주석 번호 중복 (이미 F-02에서 "6."→"7."로 정리 완료)
- **header.ts line 99**: `PHASE_STYLE[phase] || PHASE_STYLE['장마감']` — 알 수 없는 장 페이즈를 '장마감' 스타일로 처리하는 폴백 (P20 경미). 2026-07-23 폴백 제거 시도 → 하얀 화면 발생으로 롤백 (커밋 `ce9e137` → `a5b357b`). 근본 원인: 프론트엔드 초기값/폴백값 `'CLOSED'`가 PHASE_STYLE 키에 없음. **안 B(초기값 'CLOSED' → '장마감' 통일) 사전조사 후 근본 해결 예정 — 상단 직전 완료 작업 참조**.

### B-13 보류 항목 (5건, LOW/INFO)
- B-13 부분 완료. 잔여 5건은 LOW/INFO 등급으로 보류 중.

---

## 다음 세션 인계 사항

1. **F-05 (P3 — 수익 페이지)** 부터 시작. F-04-e 완료 (stock-classification.ts + general-settings.ts 함수 11건 분할).
   - F-05 대상: `profit-overview.ts` (718줄) + `profit-detail.ts` (667줄) + `profit-shared.ts` (569줄) — 총 1954줄
   - F-04 잔여: stock-classification.ts (1618줄) / general-settings.ts (1390줄) 파일 자체 분할 — 별도 세션 (멀티 파일 분할, 다단계 워크플로우)
2. 대상 원칙: P5, P10, P16, P19, P22, P23, P24
3. `architecture_audit_tasks.md` 섹션 F-05 체크리스트 참조
4. 세션당 1단계 원칙 준수 (AGENTS.md 규칙 0-1)
5. F-03 보류 항목 4건 (F03-07~F03-10) 참조
