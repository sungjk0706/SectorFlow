# SectorFlow 중복 정의 조사 후속 실행 태스크

> 작성일: 2026-07-26
> 기준 계획서: `docs/duplication-audit-plan.md`
> 상태: 실행 대기
> 원칙: D-01~D-06을 각각 독립 세션으로 수행한다. 각 세션은 사용자 실행 승인 후 해당 대상만 조사·수정·검증하고, 완료 시 커밋과 `HANDOVER.md` 갱신 후 종료한다.

---

## 1. 공통 실행 규칙

- 이 문서는 `duplication-audit-plan.md`의 D-01~D-06을 세션 단위로 구체화한다.
- 상태 표기:
  - `☐` 미시작
  - `◐` 진행 중
  - `☑` 완료
  - `⊘` 통합하지 않고 유지
- 한 세션에서는 하나의 D 항목만 수행한다. 다른 항목의 개선·정리·리팩터링을 함께 진행하지 않는다.
- 각 세션은 수정 전에 대상 코드·전체 참조·관련 테스트·기존 공통 자산을 다시 확인한다.
- 중복처럼 보이더라도 의미·오류 경계·표시 요구사항이 다르면 억지로 통합하지 않고 `⊘`로 기록한다.
- 정상 경로의 값이나 오류 의미를 빈 값·`None`·임의 fallback으로 바꾸지 않는다(P20).
- 새 공통 경로를 만들면 실제 호출부에 연결되었는지 확인한다(P16). 사용되지 않는 래퍼나 추상화는 만들지 않는다.
- 삭제·이동하는 함수·타입·상수의 이름으로 `backend`, `frontend`, `tests`, `docs` 전체를 재검색하고, 관련 docstring·주석·테스트 설명도 함께 정리한다.
- DB는 조사·수정 대상에서 제외한다. 거래 실행 경로는 변경하지 않으며, 거래 관련 호출부에 영향이 발견되면 해당 세션을 중단하고 별도 승인을 받는다.
- 세션 완료 조건은 대상 검증 통과, 변경사항 검토, 커밋, `HANDOVER.md` 갱신이다.

---

## 2. 전체 세션 진행 현황

| 세션 | 우선순위 | 대상 | 계획 상태 | 핵심 검증 |
|---|---|---|---|---|
| DUP-S1 | 높음 | D-01 암호화 키 파생 | ☐ | 암호화 상태별 테스트, 백엔드 전체 테스트, RuntimeWarning 승격 기동 |
| DUP-S2 | 높음 | D-02 시간 기본값 | ☐ | 관련 프론트엔드 테스트, typecheck, build, 화면 대조 |
| DUP-S3 | 중간 | D-03 HTTP Mock 헬퍼 | ☐ | 대상 테스트, 백엔드 전체 테스트 |
| DUP-S4 | 중간 | D-04 금액 변환 표시 | ☐ | 관련 프론트엔드 테스트, typecheck, build, 화면 대조 |
| DUP-S5 | 낮음~중간 | D-05 `CellWithPrevContent` 타입 | ☐ | typecheck, build |
| DUP-S6 | 낮음 | D-06 색상값 반복 | ☐ | typecheck, build, 화면 색상 대조 |

---

## 3. 세션별 실행 태스크

### 세션 DUP-S1 — D-01 암호화 키 파생 경로 통합

**상태:** ☐ 미시작
**대상 원칙:** P10 SSOT, P16 살아있는 경로, P20 오류 의미 보존, P24 단순성, P25 격리된 실패

#### 대상 코드

- `backend/app/core/encryption.py`
  - `_get_fernet()`
  - `get_key_state()`
  - PBKDF2HMAC, SHA256, salt, iterations, key slicing, Fernet 생성 과정
- 관련 암호화 테스트와 실제 소비자 전체 참조
  - `backend/tests/test_encryption.py`
  - `encrypt_secret()` / `decrypt_secret()` 호출부
  - 설정·엔진·텔레그램 등 암호화 상태 소비 경로

#### 수정 내용

1. 두 함수가 공유해야 하는 키 파생·Fernet 생성의 최소 공통 경로를 확정한다.
2. 이미 존재하는 공개 암호화 API와 상태 모델을 우선 재사용하고, 새 공통 함수가 실제 두 호출부에서 사용되도록 연결한다.
3. 키가 없거나 짧은 경우의 `MISSING`, 파생·Fernet 초기화 실패의 `INVALID`, 정상 상태의 `AVAILABLE` 의미를 유지한다.
4. 키 원문·예외가 외부로 노출되지 않도록 하며, 기존 암호문과 호환되는 salt·iterations·입력 절단 규칙을 변경하지 않는다.
5. 실제 Fernet 사용 경로와 상태 확인 경로의 오류 경계를 확인하고, 의미가 달라지는 부분은 별도 통합하지 않는다.
6. 제거·이동된 내부 로직의 이름과 설명을 전체 저장소에서 재검색한다.

#### 검증 방법

- 암호화·복호화의 정상, 키 없음, 짧은 키, 잘못된 키, 복호화 실패 상태별 관련 테스트
- `backend/tests/test_encryption.py` 및 암호화 소비자 관련 대상 테스트
- `.venv/bin/python -m pytest backend/tests -q`
- `.venv/bin/python -W error::RuntimeWarning main.py` 기동
- 런타임 종료 후 잔존 프로세스 0건 확인
- 기존 암호문을 새 경로로 복호화할 수 있는지 회귀 확인

---

### 세션 DUP-S2 — D-02 프론트엔드 시간 기본값 정렬

**상태:** ☐ 미시작
**대상 원칙:** P10 SSOT, P21 사용자 투명성, P23 일관성, P24 단순성

#### 대상 코드

- 기준값
  - `backend/app/core/settings_defaults.py`의 매수·매도 종료 기본값 `15:20`
- 불일치 후보
  - `frontend/src/pages/general-settings-time-settings-tab.ts`의 `15:00` fallback
- 같은 설정을 사용하는 화면·판정 경로
  - `frontend/src/utils/order-block-status.ts`
  - `frontend/src/layout/header.ts`
- 관련 설정 타입, API 변환, 프론트엔드 테스트 전체 참조

#### 수정 내용

1. 저장된 설정이 존재할 때는 기존 설정값을 그대로 사용하는지 먼저 확인한다.
2. 백엔드 기본값과 프론트엔드 fallback의 역할을 구분하고, fallback이 실제 기본값을 대신하는 경우에만 `15:20` 기준으로 정렬한다.
3. 시간 설정 화면, 주문 가능/차단 판정, 헤더 표시가 동일한 기준을 사용하도록 확인한다.
4. 설정 키·타입·정상 데이터 흐름은 변경하지 않고, 화면 fallback 불일치만 최소 수정한다.
5. UI 문구는 표준 용어를 유지하고, 사용자가 주문 차단 시각을 다르게 보게 되는 상태가 남지 않는지 확인한다.

#### 검증 방법

- 시간 설정 탭, 주문 차단 상태, 헤더 시간 표시 관련 프론트엔드 테스트
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 저장된 시간 설정이 있는 경우 기존 값 표시 확인
- 설정값이 비어 기본값을 사용하는 경우 설정 화면·주문 상태·헤더가 모두 `15:20`으로 일치하는지 확인

---

### 세션 DUP-S3 — D-03 백엔드 HTTP Mock 헬퍼 통합 검토

**상태:** ☐ 미시작
**대상 원칙:** P23 공통 자산 재사용, P24 단순성, P25 테스트 격리

#### 대상 코드

- `backend/tests/test_kiwoom_rest.py`
  - `_mock_httpx_response()` / `_mock_httpx_client()` 관련 정의와 호출부
- `backend/tests/test_ls_rest.py`
  - `_mock_httpx_response()` / `_mock_httpx_client()` 관련 정의와 호출부
- `backend/tests/test_kiwoom_order.py`
  - `_mock_httpx_response()` / `_mock_httpx_client()` 관련 정의와 호출부
- 세 파일의 response status, JSON, headers, async context manager, 예외·호출 검증 옵션

#### 수정 내용

1. 세 헬퍼의 시그니처·반환 구조·옵션 차이와 증권사별 테스트 계약을 비교한다.
2. 기존 테스트 공통 자산 위치와 import 방향을 확인한 뒤, 가장 작은 공통 테스트 헬퍼로 통합 가능한 범위만 확정한다.
3. 공통화가 가능하면 중복 구현을 하나의 테스트 공통 자산으로 이동하고 세 테스트 영역의 호출부를 전환한다.
4. 키움·LS별 요청·응답 의미와 테스트 격리는 유지한다. 차이를 숨기기 위한 과도한 범용 옵션이나 증권사 공통 운영 코드 침투는 만들지 않는다.
5. 시그니처 차이 때문에 공통화가 오히려 복잡해지면 변경하지 않고 D-03을 `⊘`로 기록한다.
6. 이동·삭제한 헬퍼 이름과 관련 테스트 설명을 전체 저장소에서 재검색한다.

#### 검증 방법

- `backend/tests/test_kiwoom_rest.py`
- `backend/tests/test_ls_rest.py`
- `backend/tests/test_kiwoom_order.py`
- `.venv/bin/python -m pytest backend/tests -q`
- Mock 호출 횟수, 요청 인자, 응답 상태·본문, 예외 전파 및 async context manager 동작 회귀 확인
- 공통 테스트 헬퍼가 운영 코드에 import되지 않는지 확인

---

### 세션 DUP-S4 — D-04 프론트엔드 금액 변환·표시 로직 공통화

**상태:** ☐ 미시작
**대상 원칙:** P23 공통 UI 자산 재사용, P24 단순성, P21 사용자 표시 일관성

#### 대상 코드

- `frontend/src/components/common/ui-styles-cells.ts`
  - 공통 `createAmountCell` 및 금액 포맷 관련 로직
- `frontend/src/pages/stock-detail.ts`
  - 페이지 전용 금액 셀 생성·단위 변환·표시 로직
- `frontend/src/pages/profit-overview-sector-pnl.ts`
  - 수익·업종 손익 금액 표시 로직
- 관련 `ui-styles.ts`, 공통 포맷 함수, 테스트와 화면 호출부

#### 수정 내용

1. 백만원→억 단위 변환, `ko-KR` 소수점 1자리 표시, 색상·부호·레이아웃 요구사항을 각각 비교한다.
2. 기존 `createAmountCell`과 공통 포맷 자산이 페이지별 요구사항을 손실 없이 수용하는지 확인한다.
3. 공통 함수가 실제 중복을 줄이면서도 단위·양수/음수 색상·부호·레이아웃 의미를 보존할 때만 호출부를 전환한다.
4. 공통 함수로 흡수할 수 없는 페이지 전용 요구사항은 별도 로직으로 유지하고, 이름만 같은 함수로 억지 통합하지 않는다.
5. 금액의 단위, 반올림, 음수 표시, 색상, 셀 정렬 및 빈 값 처리의 기존 사용자 표시를 변경하지 않는다.

#### 검증 방법

- 종목 상세·수익/업종 손익 관련 프론트엔드 테스트
- 금액 변환 경계값(0, 양수, 음수, 소수)과 표시 문자열 회귀 테스트
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 종목 상세와 수익 화면의 단위·소수점·부호·색상·정렬 대조

---

### 세션 DUP-S5 — D-05 `CellWithPrevContent` 타입 중복 검토

**상태:** ☐ 미시작
**대상 원칙:** P23 타입 일관성, P24 단순성, P16 실제 의존 방향

#### 대상 코드

- `frontend/src/components/virtual-scroller.ts`의 `CellWithPrevContent`
- `frontend/src/components/common/data-table-fixed.ts`의 `CellWithPrevContent`
- 두 타입의 필드·선택성·제네릭 여부·사용처 전체
- 공통 타입을 둘 수 있는 기존 `components/common/` 타입 자산과 import 방향

#### 수정 내용

1. 두 타입이 구조적으로 동일한지와 각 파일의 렌더링 계약이 같은지 확인한다.
2. 공통 타입으로 이동할 경우 `virtual-scroller`가 common 컴포넌트를 역참조하거나 의존 방향이 악화되지 않는지 확인한다.
3. 동일 계약이며 의존 방향이 단순해지는 경우에만 공통 타입으로 이동하고 두 파일의 import를 전환한다.
4. 필드 의미·수명·렌더링 책임이 다르거나 파일 분할 구조가 복잡해지면 중복을 유지하고 D-05를 `⊘`로 기록한다.
5. 타입 이동 시 잔존 정의·주석·import를 정리하고 실제 사용처 전체를 재검색한다.

#### 검증 방법

- `CellWithPrevContent` 정의·참조 전체 검색
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 가상 스크롤과 고정 데이터 테이블의 렌더링·이전 콘텐츠 표시 회귀 확인

---

### 세션 DUP-S6 — D-06 색상값 중복 검토 및 의미 보존

**상태:** ☐ 미시작
**대상 원칙:** P23 공통 색상 자산, P24 단순성, P21 사용자 표시 일관성

#### 대상 코드

- `frontend/src/pages/stock-classification-header.ts`
  - `#157347` 2회 사용 위치
- 비교 후보
  - `frontend/src/layout/header.ts`의 bootstrap chip 색상
  - `frontend/src/components/common/ui-styles.ts`의 `COLOR` 팔레트
- 색상 상수·스타일·호출부 전체와 관련 화면 테스트

#### 수정 내용

1. `#157347` 두 사용처가 같은 시각적 의미와 변경 수명주기를 갖는지 확인한다.
2. 기존 `COLOR` 팔레트에 동일한 의미의 공통 색상이 있으면 우선 재사용한다.
3. 동일 의미가 확정되면 화면 내부 상수 또는 기존 공통 팔레트로 중복을 제거하고 두 표시가 동일하게 유지되도록 연결한다.
4. bootstrap chip, 팔레트 값처럼 값만 같고 의미·수명주기가 다른 색상은 불필요하게 전역화하지 않는다.
5. 색상 변경 시 화면의 상태 의미·대비·가독성을 유지하고, 통합 실익이 없으면 D-06을 `⊘`로 기록한다.

#### 검증 방법

- `#157347` 및 관련 색상 상수 전체 검색
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- 브라우저에서 종목분류 헤더의 두 표시 색상과 관련 헤더/팔레트 색상 대조
- 색상 의미가 상태 표시와 일치하고 기존 화면 대비·가독성이 유지되는지 확인

---

## 4. 세션 종료 기록

각 세션 종료 시 다음을 해당 세션의 커밋과 `HANDOVER.md`에 기록한다.

- 수행한 D 항목과 실제 변경 파일
- 통합 또는 유지(`⊘`) 결정과 그 근거
- 관련 테스트·typecheck/build·런타임 검증 결과
- 다음 세션에서 이어갈 대상과 주의사항
- 거래 경로·DB·비밀정보를 변경하지 않았는지 여부
