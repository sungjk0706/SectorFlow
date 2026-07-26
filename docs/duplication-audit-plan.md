# SectorFlow 중복 정의 조사 후속 수정계획서

> 작성일: 2026-07-26
> 상태: 조사 완료 / 수정 대기
> 원칙: 본 문서는 계획만 기록하며, 이번 세션에서는 실제 코드·설정·DB를 수정하지 않음.

---

## 1. 조사 목적

프로젝트 전체에서 동일한 값·함수·로직·타입·import가 여러 위치에 독립적으로 정의되어 있는지 점검했다. 특히 KST 상수, 거래 시간, 색상, 설정 기본값, 암호화 로직, 테스트 헬퍼를 중심으로 확인했다.

## 2. 조사 범위

- 백엔드 운영 코드: `backend/app/`
- 백엔드 테스트: `backend/tests/`
- 프론트엔드 운영 코드: `frontend/src/`
- 프론트엔드 테스트: `frontend/tests/`
- 참고: `HANDOVER.md`, `ARCHITECTURE.md`, `docs/architecture_audit_plan.md`, `docs/architecture_audit_tasks.md`

이번 조사에서는 코드 검색, 정의 위치 확인, 관련 호출부·공통 자산·최근 인계 기록 대조를 수행했다.

## 3. 조사 결론

### 3.1 중복 없음으로 확인된 항목

- KST 타임존은 `backend/app/core/constants.py`의 `_KST` 한 곳에만 정의되어 있음.
- 수수료·세금 운영 상수는 `backend/app/core/constants.py`에 집중되어 있음.
- KRX/NXT 고정 거래 시간은 `backend/app/services/daily_time_scheduler.py`에 집중되어 있음.
- 프론트엔드 공통 색상·폰트는 대부분 `frontend/src/components/common/ui-styles.ts`를 사용함.
- 최근 HANDOVER에 기록된 KST 통합, 투자모드 정규화, 암호화 임시 래퍼 제거 결과와 충돌하는 잔존 정의는 확인되지 않음.
- 운영 코드의 클래스·Pydantic 모델·주요 프론트엔드 상태 타입에서 동일한 타입의 명백한 중복은 확인되지 않음.

### 3.2 우선 수정 검토 대상

#### D-01. 암호화 키 파생 로직 중복 — 높음

- 위치: `backend/app/core/encryption.py`
- 대상: `_get_fernet()`, `get_key_state()`
- 중복: PBKDF2HMAC, SHA256, salt, iterations, key slicing, Fernet 생성 과정
- 원칙: P10, P24
- 계획: 키 파생 과정을 하나의 내부 공통 경로로 통합하되, 키 상태 확인과 실제 Fernet 사용의 오류 의미는 유지한다.
- 검증: 암호화·복호화 상태별 백엔드 테스트, 전체 백엔드 테스트, RuntimeWarning 승격 기동

#### D-02. 프론트엔드 시간 기본값 불일치 — 높음

- 기준값: `backend/app/core/settings_defaults.py`의 매수·매도 종료 `15:20`
- 불일치 후보: `frontend/src/pages/general-settings-time-settings-tab.ts`의 fallback `15:00`
- 관련 사용처: `frontend/src/utils/order-block-status.ts`, `frontend/src/layout/header.ts`는 `15:20`
- 원칙: P10, P21, P23
- 계획: 시간 기본값의 SSOT를 확인한 뒤, 화면 fallback을 동일 기준으로 정렬한다. 설정값이 실제로 존재하는 정상 경로의 동작은 변경하지 않는다.
- 검증: 프론트엔드 관련 테스트, typecheck, build, 브라우저에서 시간 설정·주문 상태·헤더 표시 대조

#### D-03. 백엔드 테스트 HTTP Mock 헬퍼 중복 — 중간

- 위치: `backend/tests/test_kiwoom_rest.py`, `test_ls_rest.py`, `test_kiwoom_order.py`
- 대상: `_mock_httpx_response()`, `_mock_httpx_client()`
- 계획: 세 테스트 영역의 필요한 옵션 차이를 유지할 수 있는지 확인한 뒤 공통 테스트 자산으로 통합한다. 증권사별 테스트 격리는 유지한다.
- 원칙: P23, P24
- 검증: 대상 테스트 및 백엔드 전체 테스트

#### D-04. 프론트엔드 금액 변환 로직 중복 — 중간

- 위치: `frontend/src/components/common/ui-styles-cells.ts`, `frontend/src/pages/stock-detail.ts`, `frontend/src/pages/profit-overview-sector-pnl.ts`
- 대상: 백만원→억 단위 변환 및 `ko-KR` 소수점 1자리 표시 로직, 공통 `createAmountCell`과 페이지 전용 셀 생성 로직
- 계획: 공통 함수가 페이지별 단위·색상·부호·레이아웃 요구사항을 모두 수용할 수 있는지 먼저 확인한다. 단순히 이름만 합치거나 UI 레이아웃을 변경하지 않는다.
- 원칙: P23, P24
- 검증: 수익·종목 상세 관련 프론트엔드 테스트, typecheck, build, 브라우저 표시 확인

#### D-05. 동일 프론트엔드 내부 타입 — 낮음~중간

- 위치: `frontend/src/components/virtual-scroller.ts`, `frontend/src/components/common/data-table-fixed.ts`
- 대상: `CellWithPrevContent`
- 계획: 공통 타입으로 이동할 실익과 의존 방향을 확인한다. 파일 분할 구조를 악화시키면 유지한다.
- 원칙: P23, P24
- 검증: typecheck, build

#### D-06. 동일 색상값 반복 — 낮음

- 위치: `frontend/src/pages/stock-classification-header.ts`의 `#157347` 2회
- 참고: `frontend/src/layout/header.ts`의 bootstrap chip 색상과 `COLOR` 팔레트의 일부 값도 중복 후보이나, 화면별 의미가 달라 별도 검토 대상
- 계획: 공통 색상으로 승격할 필요가 있는지 확인하고, 단일 사용 영역의 의미 전용 색상은 불필요하게 전역화하지 않는다.
- 원칙: P23, P24
- 검증: 프론트엔드 typecheck, build, 브라우저 색상 확인

### 3.3 추가 확인만 필요한 후보

- 종목코드 정규화: `normalize_stk_cd_key()`, `_base_stk_cd()`, `_norm_stk_cd()`는 유사하지만 접미사 제거·캐시 키·설정 키라는 목적 차이가 있어 즉시 통합하지 않는다.
- 증권사 재연결 백오프 배열은 공통 패턴이나 최대 재시도 횟수가 달라 의도적 차이 가능성이 있다.
- 테스트의 `0.00015`, `0.002`는 공통 상수와 동일하지만, 일부는 기준값 고정 검증·설명용 fixture이므로 운영 상수 중복과 구분해 판단한다.
- 여러 파일에 반복되는 일반적인 `datetime`, `asyncio`, `logging` import는 필요한 의존성 선언으로서 중복 위반으로 보지 않는다.

## 4. 실행 순서 계획

세션당 한 단계 원칙에 따라 다음 순서로 별도 세션에서 진행한다.

1. **다음 세션: D-01만 구현·검증**
   - 암호화 키 파생 로직 중복 제거
   - 관련 테스트 및 런타임 검증
2. 이후 별도 세션: **D-02만 구현·검증**
   - 시간 기본값 불일치 정리
   - 프론트엔드 빌드·브라우저 확인
3. 이후 별도 세션: **D-03만 구현·검증**
   - 테스트 Mock 헬퍼 통합 여부 결정 및 적용
4. 이후 별도 세션: **D-04만 구현·검증**
   - 금액 변환 공통화 여부 결정 및 적용
5. D-05·D-06 및 추가 후보는 우선순위 재검토 후 별도 승인 시 진행

각 단계는 사전조사와 사용자 실행 승인 후에만 코드 수정을 시작한다. 이번 세션에서는 어떤 코드 수정도 수행하지 않는다.

## 5. 안전·아키텍처 점검

- P10: KST·설정·색상·암호화 파생 로직의 SSOT 유지
- P16: 새 공통 경로를 만들 경우 실제 호출부에 연결되는지 확인
- P20: 시간 fallback 정리 시 정상값을 임의의 빈값·None으로 덮지 않음
- P21: 주문 가능 시간 표시 불일치를 해소하여 사용자 표시와 실제 판정의 차이를 줄임
- P23: 기존 공통 자산을 우선 재사용하고, 증권사별 경계를 침범하지 않음
- P24: 단순한 중복 제거만 수행하며, 의미가 다른 로직을 억지로 합치지 않음
- P25: 암호화 상태·브로커 테스트 격리와 기존 오류 경계를 유지

## 6. 참고 파일

- `backend/app/core/constants.py`
- `backend/app/core/encryption.py`
- `backend/app/core/settings_defaults.py`
- `backend/app/services/engine_symbol_utils.py`
- `backend/app/services/data_manager.py`
- `backend/tests/test_kiwoom_rest.py`
- `backend/tests/test_ls_rest.py`
- `backend/tests/test_kiwoom_order.py`
- `frontend/src/components/common/ui-styles.ts`
- `frontend/src/components/common/ui-styles-cells.ts`
- `frontend/src/components/virtual-scroller.ts`
- `frontend/src/components/common/data-table-fixed.ts`
- `frontend/src/pages/general-settings-time-settings-tab.ts`
- `frontend/src/utils/order-block-status.ts`
- `frontend/src/layout/header.ts`
- `frontend/src/pages/stock-classification-header.ts`
- `frontend/src/pages/stock-detail.ts`
- `frontend/src/pages/profit-overview-sector-pnl.ts`
- `HANDOVER.md`
- `ARCHITECTURE.md`
