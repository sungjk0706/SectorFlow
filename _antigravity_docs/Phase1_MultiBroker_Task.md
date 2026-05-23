# [Phase 1] 다중 증권사 전환 어댑터 작업 지시서 (하위 AI 전용)

- `[ ]` **1. 주 사용 증권사(Primary Broker) 식별자 상태 동기화**
  - 대상 파일: `frontend/src/stores/uiStore.ts`, `frontend/src/types.ts`
  - 내용: `AppSettings` 타입 및 스토어에 `broker` (string, 기본값 'kiwoom') 필드 추가. 백엔드 `settings_store.py`의 최상위 `broker` 설정값과 1:1 매핑됨.

- `[ ]` **2. 일반설정 UI (`general-settings.ts`) 2단계 개조**
  - 대상 파일: `frontend/src/pages/general-settings.ts`
  - 내용: 
    - **Step 2A (통신망 전환용):** 폼 최상단에 **[주 사용 증권사 선택]** 라디오 버튼 추가 (키움증권 / LS증권). 이 값이 변경되면 `broker` 키로 즉시 백엔드에 저장 요청(전체 시스템 통신망이 즉시 전환됨).
    - **Step 2B (API 키 보관용):** 그 아래 API 설정 섹션에 `[키움 API] / [LS API]` 탭형 UI 생성. 이 탭을 누르는 행위는 단순히 입력칸(키움: `kiwoom_app_key_real` 등, LS: `ls_app_key_real` 등)을 교체해서 보여주는 시각적 역할만 수행함.

- `[ ]` **3. 헤더 UI (`header.ts`, `header.ui.ts`) 개조**
  - 대상 파일: `frontend/src/layout/header.ts`, `frontend/src/layout/header.ui.ts`
  - 내용:
    - 하드코딩된 '키움증권', '키움실시간' 텍스트를 제거.
    - `props.settings.broker` (주 사용 증권사) 값을 읽어와 `BROKER_LABELS`, `BROKER_COLORS` 기반으로 메인 뱃지 1개만 렌더링 (예: "LS증권").
    - 백엔드 상태(`status`)에서 내려주는 연결 플래그(`kiwoom_token_valid` 등)를 메인 증권사 뱃지의 On/Off 스위치로 임시 맵핑. (향후 백엔드에서 공통 플래그로 개선하기 전까지 시각적 대응).

- `[ ]` **4. 최종 테스트 및 검증**
  - `npm run test` 를 통해 68개 유닛 테스트 통과 여부 확인.
  - 앱 구동 후 설정 화면에서 **'주 사용 증권사'**를 LS로 바꿨을 때 헤더가 즉시 LS증권으로 변하는지 검증.
  - API 탭에서 키움과 LS 양쪽에 각각 다른 값을 입력하고 저장하여 충돌 없이 독립적으로 저장되는지 검증.
