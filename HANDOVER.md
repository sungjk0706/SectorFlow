# SectorFlow HANDOVER

> 세션 간 작업 인계 문서. **인덱스 역할만 수행** (규칙 8-2). 상세 구현 내역은 git 커밋 메시지 + docs/ 참조.

---

## 세션 개요

| 날짜 | 세션 | 작업 | 상태 |
|------|------|------|------|
| 2026-07-24 | CLEAN-02 | 프로젝트 폴더 추가 용량 정리 — 캐시/PDF/DB백업/worktree 고아브랜치 정리(18MB) + .venv 개발도구 제거(113MB) + 방치 브랜치 삭제 = 총 131MB 절감 (339MB→208MB) — P24/P25 | 완료 |
| 2026-07-24 | CLEAN-01 | 프로젝트 폴더 용량 정리 — 캐시 22MB 삭제 + DB 백업 파일 9.6MB 정리(최근 1세트만 남김) + 백업 자동 정리 로직 추가(기동 시 최근 1세트만 유지) — P10/P16/P22/P25 | 완료 |
| 2026-07-24 | GS-S4 | 일반설정 탭 재분류 다단계 워크플로우 4세션 — Step 2 UI 변경 (5→7개 탭, 토글 이동, 상태 배지, 뉴스/화면 탭 신설) — P21/P23/P24 | 완료 (워크플로우 전체 완료) |
| 2026-07-24 | GS-S3 | 일반설정 탭 재분류 다단계 워크플로우 3세션 — Step 1 파일 분할 (1443줄 → 7개 파일, 순수 이동) — P10/P23/P24 | 완료 |
| 2026-07-24 | GS-S2 | 일반설정 탭 재분류 다단계 워크플로우 2세션 — 심층 사전조사 + 태스크 파일 작성 — P10/P23/P24 | 완료 |
| 2026-07-24 | GS-S1 | 일반설정 탭 재분류 다단계 워크플로우 1세션 — 설계 검토 + 디자인 파일 작성 (옵션 A: 5→7개 탭, 작은 배지, 파일 분할 통합) — P21/P23/P24 | 완료 |
| 2026-07-24 | UI-01 | 매수설정 가산점 행 순서 교체 (5일고가→뉴스→프로그램순매수→호가잔량비) — UI 개선 4항목 중 항목1 단독 완료, 항목2+3+4는 다단계 워크플로우 대기 | 완료 |
| 2026-07-24 | SKILL-03 | backend-fix/frontend-fix/safe-trade 스킬에 problem-solve 섹션 1-1 참조 추가 (영역 특화 질문 카테고리 명시) — P10/P23/P24 | 완료 |

> 일반설정 탭 재분류 다단계 워크플로우(세션 1~4) 전체 완료. 계획서/설계 문서는 규칙 11에 따라 삭제됨.
> NWS 실시간 뉴스 매수 가산점 다단계 워크플로우(세션 1~7) 전체 완료. 계획서/설계 문서는 규칙 11에 따라 삭제됨.
> 체결강도 매수차단 제거 다단계 워크플로우(세션 1~5) 전체 완료. 계획서/설계 문서는 규칙 11에 따라 삭제됨.
> P25 전수 조사(9세션) + 수정(Tier 1/2/3, 17세션) 전체 완료. 조사 보고서 `docs/p25_isolated_failure_investigation.md`는 역사적 기록으로 유지.

---

## 직전 완료 작업

### CLEAN-02 프로젝트 폴더 추가 용량 정리 + .venv 경량화 (2026-07-24)
- **작업**: CLEAN-01 이후 추가 용량 정리 2단계. (1) 1단계(A+D+DB백업+worktree): 화면 빌드 결과(`frontend/dist` 556K) + 빌드 캐시(`tsconfig.tsbuildinfo`) + 테스트 임시(`.pytest_cache`) + Python 캐시 9개(`backend/**/__pycache__`) + `.DS_Store` 3개 삭제. 키움 REST API 문서 PDF(15MB) 삭제. DB 백업 3개(`stocks.db.20260723_234321.backup` 외 2개, 1.2MB) 삭제. 미사용 worktree 2개(`amber-einstein`/`enamel-camshaft`) + 고아 브랜치 2개 + `.git/filter-repo` 잔재 정리. (2) 2단계(.venv 경량화): 실행 파일(`SectorFlow.command`/`main.py`)이 호출하지 않는 개발 도구 제거 — mypy/mypyc(38MB 바이너리 포함)/ruff/pytest 4종/coverage/pygments + mypy/pytest 전용 의존성 7개. `typing_extensions`는 실행 패키지(fastapi/pydantic)가 필요하므로 유지.
- **수정**: 코드 변경 없음 (삭제 전용). `.venv` 패키지 제거만 수행 (pip uninstall).
- **안전장치**: (1) 삭제 전 git 추적 여부 전수 확인 — PDF/dist/DB백업/.DS_Store 모두 `.gitignore` 등록 비추적 파일, git 영향 0. (2) worktree는 `git worktree remove --force`로 정상 경로 제거, 브랜치는 main에 이미 흡수됨(929 커밋 앞섬, 브랜치만의 새 커밋 0개) 확인 후 삭제. (3) .venv 패키지 제거 전 의존성 그래프 분석 — 공유 의존성(`typing_extensions`)은 실행 패키지가 필요하므로 유지, mypy/pytest 전용 의존성만 제거. (4) 제거 후 실행 필수 패키지 13개 import 검증 + 백엔드 앱 로드 검증(라우트 35개 정상) 통과.
- **검증**: `.venv/bin/python -c "import fastapi, uvicorn, pydantic, ..."` 전부 통과 / `from backend.app.web.app import app` 로드 성공(라우트 35개) / 프로그램 실행 영향 없음 확인 / 사용자 사전 압축 백업 완료 상태에서 진행
- **효과**: 전체 339MB → 208MB (131MB 절감, 39% 감소). `.venv` 197MB → 84MB (113MB 절감). `docs` 15MB → 904KB. `backend` 8.8MB → 6.7MB. 향후 에이전트가 mypy/pytest 실행 시 일시적 재설치 필요 (사용자 직접 조작 불필요).
- **보류**: C(.git history에서 HANDOVER.md 과거 버전 제거, 10~12MB 절감 가능) — 이미 7월 8일 filter-repo 실행 이력이 있어 복잡도 가중, 위험 대비 이익 작아 보류. `.git` 50MB 이상 시 재검토.

### CLEAN-01 프로젝트 폴더 용량 정리 + 백업 자동 정리 로직 (2026-07-24)
- **작업**: (1) 캐시 4종 삭제 — `.mypy_cache`(15M) + `backend/tests/__pycache__`(6.5M) + `.pytest_cache`(316K) + `.ruff_cache`(28K) = 약 22MB. (2) DB 백업 파일 정리 — `backend/data/`의 `.backup` 파일 9세트(27개) 중 최근 1세트(20260723_234321)만 남기고 8세트(24개) 삭제 = 약 9.6MB. (3) 백업 자동 정리 로직 추가 — `backend/app/db/database.py`에 `cleanup_old_backups(keep=1)` 함수 추가, `backend/app/web/app.py` lifespan startup에서 DB 초기화 직후 호출. 매 기동 시 최근 1세트(db/shm/wal 3종)만 남기고 오래된 백업 자동 삭제.
- **수정**: `backend/app/db/database.py` (+59줄: `_db_dir()` 경로 계산 + `cleanup_old_backups()` 정리 함수), `backend/app/web/app.py` (+7줄: startup에서 호출, P25 격리 try/except), `backend/tests/test_db_backup_cleanup.py` (신규 115줄: 6개 테스트 케이스).
- **안전장치**: `stocks.db` 본체·`-shm`·`-wal`·`sectorflow.db`는 절대 삭제 금지 (P22 — `.backup` 확장자만 대상). 정리 실패 시 기동 블로킹 않고 warning 로깅 (P25). DB 경로 계산을 `get_db_connection`과 동일 방식으로 같은 모듈에 배치 (P10 SSOT).
- **검증**: pytest 6/6 통과 / ruff 통과 / mypy 통과(수정 파일) / 런타임 기동 확인(239ms, 백업 정리 관련 에러 없음) / 커밋 (해시는 git log 참조)
- **효과**: `backend/data/` 12MB → 2.4MB. 향후 마이그레이션 백업 누적 방지.

> GS-S4, GS-S3, UI-01, SKILL-03, SKILL-02, SKILL-01, NWS-S7, NWS-S6, T4-S01, MEM-01, T3-S31/S32 등 이전 완료 작업 상세는 git history 참조 (규칙 7 — 직전 완료 작업 최근 1~2건 유지).

---

## 다음 세션 진행 대기

**사용자 지시 시 진행 가능 항목 (audit 문서 잔여)**:
- B-13 보류 5건 (B13-03/04/06/07/08, LOW/INFO 등급) — `docs/architecture_audit_plan.md` 섹션 7 참조
- B21-01 보류 (암호화 폴백, 사용자 승인 대기 — 보안 동작 변화, UI 기준 설명 필요)
- F-03 보류 4건 (F03-07/08/09/10) — `docs/architecture_audit_tasks.md` F-03 섹션 참조
- F-04 잔여 파일 분할 (stock-classification.ts 1618줄) — general-settings.ts는 본 워크플로우(Step 1+2)에서 분할 완료
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
