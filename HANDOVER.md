# SectorFlow Handover

## 직전 완료 작업 (최근 2건)
- **2026-07-22 (최근)**: `auth.py` `verify_token` dead code 제거 (P16). **수정 파일 1개** (백엔드 1파일): `backend/app/web/auth.py` — `verify_token` 함수(30-39행) 제거 + 미사용 `JWTError` import 제거. **근본 원인**: B-22-b 세션에서 deps.py/ws.py의 주석 처리된 `verify_token` 호출 코드 제거 후 호출처 0건이 됨 (auth.py:30 정의만 남음 = P16 dead code). `create_access_token`/`authenticate_user`는 살아있는 경로 (routes/auth.py에서 호출). **검증**: py_compile OK + pytest 2783 passed / 0 failed + `python -W error::RuntimeWarning main.py` 기동 성공 (RuntimeWarning 0건). **UI에서 달라지는 점**: 없음 — 호출되지 않는 함수 제거만. **다음 세션**: HANDOVER 기타 대기 항목 2번 `kiwoom_rest.py` `exc_info=True` 누락 8곳 (P23) 진행 예정.
- **2026-07-22 (이전)**: 일일 손실 한도 개선 3단계 확인 + P20 폴백 제거 5곳 (P20/P23). **수정 파일 1개** (프론트엔드 1파일): `frontend/src/pages/general-settings.ts` refreshUI 함수 1236/1242/1248/1254/1260행 — `Number(r.xxx ?? 기본값) || 기본값` → `Number(r.xxx ?? 기본값)`. **근본 원인**: `|| 기본값` 폴백이 0(유효값, "한도 없음")을 기본값으로 잘못 덮어쓰는 P20 위반. `?? 기본값`(null/undefined 초기값)은 P20 위반 아님 — 유지. **해결**: 0이 서버값으로 오면 0 그대로 화면 표시. 5곳 모두 동일 패턴 일괄 수정 (P23 일관성). **3단계 심층 조사**: 일일 손실 한도 행의 `createToggleLabelControlsRow` + `createMoneyInput`(음수) + 토글 기본 ON 교체가 이미 구현 완료 상태였음 — 추가 코드 수정 없이 확인만 수행. **검증**: `npm run typecheck` 통과 + `npm run build` 성공 (2.30s). **UI에서 달라지는 점**: 일일 손실 한도를 0으로 설정 시 화면에 0으로 표시됨 (이전에는 -500000으로 잘못 표시).

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

### 기타 대기 항목
- **NXT 메인마켓 미갱신 (09:00:30)**: 2026-07-22 조사 중 발견. `calc_timebased_market_phase()`가 09:00:30에 NXT="메인마켓" 산정하나, 09:00:30에 `_broadcast_market_phase()`를 호출할 타임테이블 이벤트 없음 → NXT 페이즈가 재기동 전까지 "정규장 준비"로 고정 (카운트다운 표시 영향). 주문 중단 칩과는 무관 (KRX 활성 상태에서 주문 허용). 별도 세션에서 09:00:30 타임테이블 이벤트 추가 또는 주기적 브로드캐스트 검토 필요.
- **다운로드 완료 시간 표시 (제안2)**: 1일봉/5일봉 다운로드 버튼 우측에 최근 다운로드 완료 시간 표시. 백엔드 신규 기능 필요 (저장소 설계 사전조사 후 제안).
- **실전모드 보관 기준** (`RETENTION_TRADING_DAYS_REAL = 90`): 추후 논의.
- **`notify_raw_real_data` dead code (P16)**: 별도 검토 필요 시 사용자 지시.
- **추가 컬럼 너비 조정**: 사용자 UI 확인 후 필요 시 해당 페이지만 override로 진행.
- **`sector_calculator.py:132` 코드 주석-코드 불일치 (P10/P23)**: 2026-07-18 ARCHITECTURE.md 6.2절 불일치 수정 세션 중 발견. 주석 "순위/백분위 기반 점수이므로 불필요" → 실제 2차 가산점은 "가중 순위 합" 방식 (백분위 미사용). 사용자가 "문서만 수정, 코드 변경 없음" 명시하여 코드 주석은 수정 안 함. 사용자 승인 시 별도 세션에서 코드 주석 1줄 갱신 권장.
- **`kiwoom_rest.py` `except Exception as e:` 8곳 `exc_info=True` 누락 (P23)**: 2026-07-21 B-15-b 세션 중 발견. `kiwoom_connector.py`(12/12 보유)와 일관성 위반. B-15-a 세션에서 누락됨 (B15-03/B15-04는 `kiwoom_connector.py`에만 적용). 별도 세션에서 8곳에 `exc_info=True` 추가 권장.
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
