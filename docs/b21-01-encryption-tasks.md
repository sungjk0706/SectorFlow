# 태스크 파일: B21-01 암호화 fail-closed 구현

> 상태: 작성 완료 · 사용자 승인 대기
> 작성일: 2026-07-26
> 기준 설계서: `docs/b21-01-encryption-design.md`
> 다단계 진행: 설계 ✅ (`docs/b21-01-encryption-design.md`) · 세부 태스크 작성 ✅ · 구현 대기 (8세션 예정)
> 관련 원칙: P10, P16, P20, P21, P22, P23, P24, P25
> 관련 파일: `backend/app/core/encryption.py`, `backend/app/core/settings_file.py`, `backend/app/core/settings_store.py`, `backend/app/web/routes/settings.py`, `backend/app/core/engine_settings.py`, `backend/app/services/telegram_bot.py`, `backend/app/core/broker_router.py`, `backend/app/core/kiwoom_connector.py`, `backend/app/core/ls_connector.py`, `frontend/src/api/client.ts`, `frontend/src/settings.ts`, `frontend/src/pages/general-settings.ts`, `frontend/src/pages/general-settings-api-settings-tab.ts`, `frontend/src/pages/general-settings-telegram-tab.ts`, 관련 테스트 파일
> 관련 API/이벤트 스펙: `PATCH /api/settings/{field_name}`, `GET /api/settings`, 기존 주문 단일 경로(`execute_buy()`/`execute_sell()`), 브로커 연결 경로(`broker_router.validate()` / `connector_manager.connect_all()`)

---

## 0. 사전조사 결과 요약

### 0.1 의존성

| 파일 | 확인된 호출·변경 관계 | 기준 라인 |
|---|---|---:|
| `backend/app/core/encryption.py` | 현재 `_get_fernet()`→`encrypt_value()`/`decrypt_value()`가 `str \| None` 반환. Fernet 미가용 시 평문/암호문 그대로 반환(폴백). 6개 호출부가 이 계약에 의존. | 12-57 |
| `backend/app/core/settings_file.py` | `_ENCRYPT_FIELDS`(단일 SSOT, 6필드). 전체 저장 `_collect_save_params()`→`_encrypt_field_or_raise()`(이미 fail-closed). 증분 저장 `save_selected_settings()`→`encrypt_value()` 직접 호출(폴백 허용 — 불일치). `_decrypt_encrypt_fields()`→`decrypt_value()`(None 시 빈문자열 폴백+경고 로그). | 204-208, 241-291, 348-363, 430-484 |
| `backend/app/core/settings_store.py` | `apply_settings_updates()`→`_prepare_save_payload()`→`_encrypt_field_or_raise()`(이미 fail-closed). `build_masked_settings_dict()`→`load_integrated_system_settings()`(복호화 포함). `load_integrated_system_settings_for_editing()`→`_decrypt_encrypt_fields()`. | 255-304, 377-430 |
| `backend/app/web/routes/settings.py` | `patch_setting_field()` — 예외 발생 시 `HTTPException(422, detail=f"유효하지 않은 설정값: {e}")` 문자열 detail. 구조화된 오류 코드 미지원. | 26-86 |
| `backend/app/core/engine_settings.py` | `_dec()` 헬퍼 — `decrypt_value()` 반환 None 시 빈문자열 폴백+경고 로그. `_pick_broker_credentials()`가 `_dec()`로 모든 증권사 자격 복호화. `build_engine_settings_dict()` 결과가 엔진 캐시·커넥터 생성 인자로 사용. | 24-53, 246-277 |
| `backend/app/services/telegram_bot.py` | `_fetch_enabled_settings()` — `gAAAA` 접두 시 `decrypt_value()` 호출, `(decrypt_value(raw_token) or "").strip()` 폴백. 평문 토큰도 허용. | 111-140 |
| `backend/app/core/broker_router.py` | `validate()` — `state.integrated_system_settings_cache`에서 `app_key`/`app_secret` 존재만 확인(빈 값 여부). 복호화 상태·키 상태 미확인. | 128-162 |
| `backend/app/core/kiwoom_connector.py` | `create_kiwoom_connector()` — `app_key`/`app_secret` 빈 값 시 `ValueError`. 복호화 실패·키 부재 구분 없음. | 533-535 |
| `backend/app/core/ls_connector.py` | `create_ls_connector()` — 동일 패턴. | 824-827 |
| `backend/app/services/engine_account.py` | `_resolve_account_settings()` — `app_key`/`app_secret` 누락 시 DB 재조회. 복호화 상태 미확인. | 228-238 |
| `frontend/src/api/client.ts` | `request()` — `body.detail`이 문자열인 경우만 추출. 구조화된 detail(객체) 미지원. | 31-45 |
| `frontend/src/settings.ts` | `saveSection()` — 저장 성공 시에만 store 반영. 실패 시 `SaveResult.error`에 메시지 전달(문자열). 마스킹 필드 집합 `MASKED_FIELDS`(6필드, 백엔드 `_ENCRYPT_FIELDS`와 동일 — P10 위반 가능성). | 9-32, 66-82 |
| `frontend/src/pages/general-settings-api-settings-tab.ts` | API 키 입력·저장. 암호화 상태 표시 없음. 저장 실패 시 `showSaveToast('error')`만 표시(상세 사유 미표시). | 98-123 |
| `frontend/src/pages/general-settings-telegram-tab.ts` | 텔레그램 토큰 입력·저장. 동일 패턴. | 53-76 |
| `backend/tests/test_encryption.py` | 현재 폴백 동작(평문 반환) 검증 — 신규 상태 모델로 전환 시 전면 수정. | 1-144 |
| `backend/tests/test_settings_file_integration.py` | `_encrypt_field_or_raise`/`_decrypt_encrypt_fields` 테스트. `encrypt_value`/`decrypt_value` mock 패턴 사용. | 340-385 |
| `backend/tests/test_settings_store.py` | `apply_settings_updates`/`build_masked_settings_dict`/`load_integrated_system_settings_for_editing` 테스트. `decrypt_value` mock 패턴. | 810-849 |
| `backend/tests/test_engine_settings.py` | `_dec()` 복호화 성공/실패(None) 테스트. `decrypt_value` mock 패턴. | 210-238 |
| `backend/tests/test_telegram_bot.py` | `_fetch_enabled_settings()` 암호문/평문 토큰 처리 테스트. `decrypt_value` mock 패턴. | 240-339 |
| `frontend/tests/api/client.test.ts` | 422 응답 detail 문자열 추출 테스트. 구조화 detail 미테스트. | 1-81 |
| `frontend/tests/settings.test.ts` | `saveSection` 422 detail 전파 테스트. 구조화 detail 미테스트. | 90-163 |

### 0.2 영향 범위

- **백엔드 핵심**: 암호화 상태 모델, 전체·증분 저장 경로 통합, 복호화 소비자(엔진 설정·텔레그램), 브로커 연결·주문 자격 검증.
- **백엔드 API**: `PATCH /api/settings/{field_name}` 오류 응답 구조화(기존 422 상태 유지 + detail 객체 추가).
- **프론트엔드**: API 클라이언트 오류 파싱, 설정 저장 실패 시 store 미반영, 일반설정 화면 암호화 상태 배너 + API/텔레그램 탭 상태 표시 + 키 백업 안내.
- **DB**: `stocks.db` 스키마 변경 없음. 기존 평문 값은 `plaintext_legacy` 상태로 분류(자동 마이그레이션·삭제 금지).
- **거래 안전**: 실전 거래 활성화 아님. 실전 브로커 인증정보 복호화 불가 시 연결·주문 차단 방향. 테스트 모드는 인증정보 불필요 경로 유지.

### 0.3 아키텍처 원칙 부합

- **P10 ✅**: `_ENCRYPT_FIELDS` 단일 정의 유지. 프론트엔드 `MASKED_FIELDS` 중복 정의는 백엔드에서 내려주는 필드 목록으로 단일화 검토(세션 6-7에서 확정). 암호화 키 상태·민감값 상태는 각각 단일 진실 소스.
- **P16 ✅**: 신규 상태 모델·검사 함수는 모두 살아있는 저장·복호화·연결 경로에 연결. dead code 미생성.
- **P20 ✅**: `encrypt_value`/`decrypt_value`의 평문/암호문 폴백 제거. `None`/빈문자열로 상태를 표현하지 않고 명시적 결과 모델 사용. `_decrypt_encrypt_fields`의 빈문자열 폴백도 상태 기반 차단으로 전환.
- **P21 ✅**: 암호화 키 상태·저장 차단 사유를 UI에 표시. 구조화된 오류 코드로 UI가 원인 판별 가능. 브로커 연결 차단 사유 UI 표시.
- **P22 ✅**: 기존 평문→암호문 전환 시 자동 마이그레이션 금지, 사용자 명시적 재저장 시에만 암호화. 복호화 불일치 시 즉시 차단.
- **P23 ✅**: 용어 사전 준수("업종"/"종목"). 기존 공통 UI 자산(토스트·설정 공통 컴포넌트·표준 색상) 재사용. 오류 코드 체계 일관.
- **P24 ✅**: 8세션 분할로 단계별 검증. 전체·증분 저장 경로 공통 검사 함수로 중복 제거(줄 수 단축보다 중복 제거 우선).
- **P25 ✅**: 암호화 키 미설정이 앱 전체 기동을 블로킹하지 않음. 비민감 설정·테스트 데이터 조회 정상 작동. 민감정보 저장·복호화·연결만 해당 범위에서 차단+로깅.

### 0.4 기존 공통 자산 확인

- **재사용**: `_ENCRYPT_FIELDS`(settings_file.py), `_encrypt_field_or_raise()`(fail-closed 의도 재사용), `HTTPException(422)`(기존 상태 체계 유지), `showSaveToast()`/`showToast()`(toast.ts), `createCardTitle()`/`sectionTitle()`/`createDescText()`(settings-common.ts), `COLOR`/`FONT_SIZE`(ui-styles.ts), `createDarkInput()`/`createTextInput()`(setting-row.ts), `extractDirty()`/`MASKED_FIELDS`(settings.ts), `broker_router.validate()`(기존 검증 프레임워크), `schedule_engine_task()`(태스크 격리).
- **재사용**: 테스트 픽스처 `in_memory_db`, `fresh_engine`, `AsyncMock`/`patch` 패턴.
- **신규 생성 제한**: 새 DB 테이블, 새 이벤트 버스, 새 주문 경로, 새 SSOT(암호화 키 상태는 encryption.py 내 단일 정의), 중복 마스킹 필드 목록(백엔드에서 내려주는 방향 검토). `encrypt_value`/`decrypt_value` 구식 함수는 신규 결과 모델 함수로 일괄 전환 후 제거(레거시 유지 금지 — P16).

---

## 1. 단계 분할

> 규칙: 한 세션에는 한 단계만 진행한다(규칙 0-1). 각 세션은 태스크 확인 → 사용자 승인 → 수정/문서화 → 해당 단계 검증 → 커밋 및 인계 순서로 진행한다. 아래 파일 목록은 조사 결과 기준이며, 실제 구현 세션 시작 시 변경 전 재검색한다.

### 세션 1 — 백엔드 암호화 상태 모델 + 결과 반환 API

- **목표**: `encryption.py`에 키 상태·민감값 상태 모델을 도입하고, 암호화·복호화 함수가 명시적 결과 객체를 반환하도록 전환한다. 폴백(평문/암호문 그대로 반환)을 제거한다.
- **수정 파일 목록**:
  - `backend/app/core/encryption.py`
  - `backend/tests/test_encryption.py`
- **파일별 변경점**:
  - `encryption.py`: `KeyState` 열거형(`AVAILABLE`/`MISSING`/`INVALID`), `SecretValueState` 열거형(`EMPTY`/`ENCRYPTED`/`PLAINTEXT_LEGACY`/`KEY_UNAVAILABLE`/`DECRYPT_FAILED`) 추가. `get_key_state()` 함수 추가(현재 키 상태 반환). `EncryptResult`/`DecryptResult` 결과 모델 추가(상태 + 선택적 값). `encrypt_secret()`/`decrypt_secret()` 신규 함수 추가(결과 객체 반환, 폴백 없음). 기존 `encrypt_value()`/`decrypt_value()`는 신규 함수 기반 래퍼로 재구현하되, 모든 호출부 전환 전까지 임시 유지(세션 2-4에서 전환 완료 후 제거 — P16 dead code 방지).
  - `test_encryption.py`: 신규 상태 모델 단위 테스트 추가(키 없음→`MISSING`, 잘못된 키→`INVALID`, 정상→`AVAILABLE`). `encrypt_secret`/`decrypt_secret` 결과 객체 테스트 추가(폴백 없음 검증). 기존 `encrypt_value`/`decrypt_value` 폴백 테스트는 래퍼 동작에 맞게 수정.
- **변경하지 않을 범위**: 저장 경로(settings_file.py), 설정 API, 복호화 소비자, 프론트엔드. 임시 래퍼 유지로 기존 호출부 동작 보존.
- **검증 방법**:
  - `.venv/bin/python -m pytest backend/tests/test_encryption.py -q -W error::RuntimeWarning`
  - `.venv/bin/python -m pytest backend/tests -q` (회귀 없음 — 임시 래퍼로 기존 동작 유지)
  - `.venv/bin/python -W error::RuntimeWarning main.py` 10s 기동 검증 (RuntimeWarning 없음)

### 세션 2 — 백엔드 저장 경로 통합 (전체·증분 동일 정책)

- **목표**: `settings_file.py`의 전체 저장(`save_settings`→`_collect_save_params`)과 증분 저장(`save_selected_settings`)이 동일한 fail-closed 암호화 검사를 통과하도록 통합한다. 복호화 경로도 상태 기반으로 전환한다.
- **수정 파일 목록**:
  - `backend/app/core/settings_file.py`
  - `backend/tests/test_settings_file_integration.py`
- **파일별 변경점**:
  - `settings_file.py`: `save_selected_settings()`의 직접 `encrypt_value()` 호출을 `_encrypt_field_or_raise()` 또는 신규 `encrypt_secret()` 경유 공통 검사로 전환. `_decrypt_encrypt_fields()`를 `decrypt_secret()` 결과 상태 기반 처리로 전환(`KEY_UNAVAILABLE`/`DECRYPT_FAILED`/`PLAINTEXT_LEGACY` 구분, 빈문자열 폴백 제거). 공통 저장 검사 헬퍼 추출(전체·증분 양쪽에서 호출 — P24 중복 제거). 기존 평문 값 감지 시 `PLAINTEXT_LEGACY` 분류(자동 마이그레이션·삭제 금지).
  - `test_settings_file_integration.py`: 증분 저장 평문 차단 테스트 추가. 비민감 설정 키 없음 상태에서 정상 저장 테스트 추가. `PLAINTEXT_LEGACY` 분류 테스트 추가. `KEY_UNAVAILABLE`/`DECRYPT_FAILED` 차단 테스트 추가. 기존 `encrypt_value`/`decrypt_value` mock 패턴을 신규 함수 mock으로 전환.
- **변경하지 않을 범위**: `encryption.py`(세션 1 완료), 설정 API 라우트, 복호화 소비자(engine_settings.py, telegram_bot.py), 프론트엔드.
- **검증 방법**:
  - `.venv/bin/python -m pytest backend/tests/test_settings_file_integration.py backend/tests/test_encryption.py -q -W error::RuntimeWarning`
  - `.venv/bin/python -m pytest backend/tests -q` (회귀 없음)
  - `.venv/bin/python -W error::RuntimeWarning main.py` 10s 기동 검증

### 세션 3 — 백엔드 설정 API 구조화 오류 응답

- **목표**: `PATCH /api/settings/{field_name}` 실패 시 기존 422 상태를 유지하되, `detail`을 구조화된 객체(`code`/`message`/`field`)로 반환한다. `settings_store.py`의 오류 전달 경로를 정리한다.
- **수정 파일 목록**:
  - `backend/app/core/settings_store.py`
  - `backend/app/web/routes/settings.py`
  - `backend/tests/test_settings_store.py`
- **파일별 변경점**:
  - `settings_store.py`: `apply_settings_updates()` 내 암호화 실패 시 신규 예외 클래스(`EncryptionError` — code/message/field 포함) 발생. 기존 `ValueError` 경로는 비암호화 검증(타임테블·리스크 범위) 유지. `_prepare_save_payload()`의 `_encrypt_field_or_raise` 호출 시 신규 예외로 래핑.
  - `settings.py`: `patch_setting_field()` 예외 처리에서 `EncryptionError` 감지 시 구조화된 `detail` 객체 반환(`{"code": ..., "message": ..., "field": ...}`). 기존 `ValueError`는 문자열 detail 유지(하위 호환). 오류 코드: `ENCRYPTION_KEY_MISSING`/`ENCRYPTION_KEY_INVALID`/`ENCRYPTION_FAILED`/`DECRYPTION_UNAVAILABLE`/`DECRYPTION_FAILED`/`PLAINTEXT_SECRET_REQUIRES_REENTRY`.
  - `test_settings_store.py`: 신규 예외 전파 테스트 추가. 기존 `decrypt_value` mock 패턴을 신규 함수 mock으로 전환.
- **변경하지 않을 범위**: `encryption.py`, `settings_file.py`(세션 1-2 완료), 복호화 소비자, 프론트엔드.
- **검증 방법**:
  - `.venv/bin/python -m pytest backend/tests/test_settings_store.py backend/tests/test_settings_file_integration.py -q -W error::RuntimeWarning`
  - `.venv/bin/python -m pytest backend/tests -q` (회귀 없음)
  - `.venv/bin/python -W error::RuntimeWarning main.py` 10s 기동 검증

### 세션 4 — 백엔드 복호화 소비자 전환 (엔진 설정·텔레그램)

- **목표**: `engine_settings.py`의 `_dec()` 헬퍼와 `telegram_bot.py`의 `_fetch_enabled_settings()`를 신규 `decrypt_secret()` 결과 기반으로 전환한다. 복호화 불가 시 빈문자열 폴백을 제거하고 상태 기반 차단·로깅으로 전환한다.
- **수정 파일 목록**:
  - `backend/app/core/engine_settings.py`
  - `backend/app/services/telegram_bot.py`
  - `backend/tests/test_engine_settings.py`
  - `backend/tests/test_telegram_bot.py`
- **파일별 변경점**:
  - `engine_settings.py`: `_dec()`를 `decrypt_secret()` 결과 상태 기반으로 전환. `ENCRYPTED`→평문 반환, `KEY_UNAVAILABLE`/`DECRYPT_FAILED`→빈문자열 대신 상태 로깅 + 빈값 유지(엔진 기동 차단 아님 — P25, 복호화 불가 자격은 세션 5에서 연결·주문 차단). `PLAINTEXT_LEGACY`→평문 반환(레거시 호환, 재저장 시 암호화). `_pick_broker_credentials()` 결과에 자격 상태 정보 추가(세션 5 연계).
  - `telegram_bot.py`: `_fetch_enabled_settings()`의 `(decrypt_value(raw_token) or "").strip()` 폴백 제거. `decrypt_secret()` 결과 기반으로 전환. 복호화 불가 토큰은 스킵 + 로깅(폴링 차단).
  - `test_engine_settings.py`: `_dec()` 신규 상태별 테스트 추가. 기존 `decrypt_value` mock 전환.
  - `test_telegram_bot.py`: 복호화 불가 토큰 스킵 테스트 추가. 기존 `decrypt_value` mock 전환.
- **변경하지 않을 범위**: `encryption.py`, `settings_file.py`, `settings_store.py`, API 라우트(세션 1-3 완료), 브로커 연결·주문 차단(세션 5), 프론트엔드.
- **검증 방법**:
  - `.venv/bin/python -m pytest backend/tests/test_engine_settings.py backend/tests/test_telegram_bot.py -q -W error::RuntimeWarning`
  - `.venv/bin/python -m pytest backend/tests -q` (회귀 없음)
  - `.venv/bin/python -W error::RuntimeWarning main.py` 10s 기동 검증 (RuntimeWarning 없음)

### 세션 5 — 백엔드 브로커 연결·주문 자격 검증 연계

- **목표**: 선택된 브로커의 인증정보가 복호화 불가(`KEY_UNAVAILABLE`/`DECRYPT_FAILED`)/재입력 필요(`PLAINTEXT_LEGACY`)인 경우 브로커 연결을 시작하지 않고, 주문 단일 경로에서 자격 상태를 확인하여 차단한다. 차단 사유를 UI에 전달 가능한 형태로 기록한다.
- **수정 파일 목록**:
  - `backend/app/core/broker_router.py`
  - `backend/app/core/kiwoom_connector.py`
  - `backend/app/core/ls_connector.py`
  - `backend/app/services/trading.py` (주문 단일 경로 — safe-trade 스킬 필수)
  - 관련 테스트 파일 (구현 세션에서 실제 경로 재확인)
- **파일별 변경점**:
  - `broker_router.py`: `validate()`에서 자격 상태 확인 추가(기존 빈 값 확인 확장 — 복호화 상태·키 상태 포함). 차단 사유 메시지에 구조화된 코드 추가.
  - `kiwoom_connector.py`/`ls_connector.py`: `create_*_connector()` 인자 검증 시 자격 상태 확인(빈 값 + 복호화 불가 구분).
  - `trading.py`: `execute_buy()`/`execute_sell()` 진입 전 자격 상태 확인(이미 검증된 브로커 자격 상태 사용 — 단일 경로 우회 금지 P15). 차단 시 사유 기록·표시.
  - 테스트: 자격 불가 시 연결 차단·주문 차단 시나리오 추가. 테스트 모드(인증정보 불필요 경로)는 차단 제외 검증.
- **변경하지 않을 범위**: 암호화 모델·저장 경로·API 응답·복호화 소비자(세션 1-4 완료), 프론트엔드. 실전 거래 활성화 아님.
- **검증 방법**:
  - `.venv/bin/python -m pytest backend/tests -k "broker_router or connector or trading" -q -W error::RuntimeWarning`
  - `.venv/bin/python -m pytest backend/tests -q` (회귀 없음)
  - `.venv/bin/python -W error::RuntimeWarning main.py` 10s 기동 검증
  - safe-trade 스킬: 모의투자/안전성 확인 절차 준수

### 세션 6 — 프론트엔드 API 클라이언트 구조화 오류 처리 + 저장 실패 시 store 미반영

- **목표**: API 클라이언트가 구조화된 `detail` 객체(문자열 + 객체 양쪽 호환)를 파싱하도록 전환한다. 설정 저장 실패 시 store에 평문 입력값을 성공 상태로 반영하지 않도록 수정한다.
- **수정 파일 목록**:
  - `frontend/src/api/client.ts`
  - `frontend/src/settings.ts`
  - `frontend/tests/api/client.test.ts`
  - `frontend/tests/settings.test.ts`
- **파일별 변경점**:
  - `client.ts`: `request()` 오류 처리에서 `body.detail`이 문자열인 경우 기존대로 추출, 객체인 경우 `detail.message`(또는 `detail.code` 기반 메시지 매핑) 추출. 하위 호환(문자열 detail) 유지.
  - `settings.ts`: `saveSection()` 저장 실패 시 기존 `store.setState` 미호출 확인(현재 코드도 성공 시에만 반영 — 검증 후 보강 필요 시 수정). `SaveResult`에 구조화 오류 코드 전달 옵션 추가(`errorCode`/`errorField`).
  - `client.test.ts`: 구조화된 detail 객체 파싱 테스트 추가. 기존 문자열 detail 테스트 유지(하위 호환).
  - `settings.test.ts`: 구조화 오류 전파 테스트 추가. 저장 실패 시 store 미반영 테스트 추가.
- **변경하지 않을 범위**: 백엔드(세션 1-5 완료), 프론트엔드 UI 컴포넌트(세션 7).
- **검증 방법**:
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm run test` (vitest)
  - `cd frontend && npm run build`

### 세션 7 — 프론트엔드 일반설정 UI 암호화 상태 표시 + 키 백업 안내

- **목표**: 일반설정 화면 상단에 암호화 상태 요약 배너를 추가하고, API 설정·텔레그램 탭에 민감값 상태·저장 제한 안내를 표시한다. 키 백업·복구 안내 문구를 추가한다. 기존 공통 UI 자산을 우선 재사용한다.
- **수정 파일 목록**:
  - `frontend/src/pages/general-settings.ts`
  - `frontend/src/pages/general-settings-api-settings-tab.ts`
  - `frontend/src/pages/general-settings-telegram-tab.ts`
  - `frontend/src/types/index.ts` (암호화 상태 타입 추가)
  - 관련 프론트엔드 테스트 파일 (구현 세션에서 실제 경로 재확인)
- **파일별 변경점**:
  - `general-settings.ts`: 화면 상단 암호화 상태 배너 추가(`available`/`missing`/`invalid` 표시). 기존 `createCardTitle()`/`sectionTitle()`/표준 색상 재사용. 신규 카드·색상 체계 미생성(P23).
  - `general-settings-api-settings-tab.ts`: 각 민감 필드 영역에 상태·저장 제한 안내 추가(`plaintext_legacy`/`key_unavailable`/`decrypt_failed` 표시). 저장 버튼 비활성화(키 없음 상태 알 시). 저장 실패 토스트에 구조화 오류 코드 기반 메시지 표시.
  - `general-settings-telegram-tab.ts`: 동일 패턴 적용.
  - `types/index.ts`: 암호화 상태 타입(`EncryptionStatus`/`SecretFieldStatus`) 추가. 백엔드 응답 스키마와 일치.
  - 테스트: 상태별 배너 표시·저장 제한 표시·구조화 오류 메시지 표시 테스트 추가.
  - 키 백업 안내 문구: 설계서 섹션 9.2 문구 적용. 기존 `createDescText()` 재사용.
- **변경하지 않을 범위**: 백엔드(세션 1-5 완료), 프론트엔드 API 클라이언트·settings.ts(세션 6 완료).
- **검증 방법**:
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm run test`
  - `cd frontend && npm run build`
  - 브라우저 확인: 일반설정 화면에서 암호화 상태 배너·API/텔레그램 탭 상태 표시·키 백업 안내 표시 (사용자 직접 확인 항목)

### 세션 8 — 전체 검증 게이트

- **목표**: 모든 단계 완료 후 설계서 섹션 10.4의 검증 게이트를 전부 실행하고, 잔존 위반 패턴(폴백·dead code·평문 저장)이 없는지 확인한다. 코드 수정 없음(발견 시 해당 세션으로 회귀).
- **수정 파일 목록**: 없음 (검증 전용 세션)
- **검증 방법**:
  - `.venv/bin/python -m pytest backend/tests -q` (전체 백엔드 테스트)
  - `.venv/bin/python -W error::RuntimeWarning main.py` 10-30s 기동 검증 (RuntimeWarning 없음)
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm run build`
  - `cd frontend && npm run test`
  - 잔존 패턴 grep: `encrypt_value`/`decrypt_value` 구식 함수 잔존 여부, `return plain`/`return cipher` 폴백 잔존 여부, silent `except: pass` 잔존 여부
  - 규칙 5-1: 잔존 프로세스 0건 확인
  - 사용자 직접 확인 항목: 브라우저에서 일반설정 화면 전체 탭 동작 확인

---

## 2. 사용자 결정 항목

> 설계서 `docs/b21-01-encryption-design.md`의 사용자 결정 사항 이관. 구현 중 추가 결정 시 누적 기록.

| # | 결정 사항 | 사용자 결정 | 비고 |
|---|---|---|---|
| 1 | B21-01 진행 방향 | **(a) 차단 방향** — Fernet 키 미설정·오류 시 민감정보 평문 저장/복호화 허용하지 않음 | 2026-07-26 B21-01-DESIGN-01 세션에서 사용자 승인. 설계서 전체가 이 방향 기준. |
| 2 | 기존 평문 데이터 처리 | 자동 마이그레이션·자동 삭제 금지. 사용자 명시적 재입력 시에만 암호화 저장 | 설계서 섹션 6. 사용자가 재입력 전 기존 값 유지 필요성 인지. |
| 3 | 앱 전체 기동 차단 여부 | 암호화 키 미설정만으로 앱 전체 기동 차단하지 않음(P25) | 설계서 섹션 8.1. 비민감 설정·테스트 데이터 조회 정상 작동. |
| 4 | 키 백업 책임 | 사용자가 암호화 키 별도 백업 의무. 앱 데이터 백업만으로는 복구 불가 | 설계서 섹션 9. UI에 안내 문구 표시. |

---

## 3. 테스트 계획 (설계서 섹션 10 기반)

> 각 세션의 검증 방법에 포함되는 테스트 케이스. 중복 기재 회피를 위해 본 섹션은 설계서 섹션 10을 참조 인덱스로 사용.

- **백엔드 단위 테스트**: 설계서 10.1 — 세션 1-2에서 추가.
- **저장 경로 테스트**: 설계서 10.2 — 세션 2-3에서 추가.
- **프론트엔드 테스트**: 설계서 10.3 — 세션 6-7에서 추가.
- **검증 게이트**: 설계서 10.4 — 세션 8에서 전체 실행.

---

## 4. 런타임 검증 방법

> 백엔드 변경 세션(1-5) 종료 시 공통 수행 항목.

- `.venv/bin/python -W error::RuntimeWarning main.py` 기동 — 10-30s 대기 후 종료
- 기동 로그 확인: 암호화 키 상태 로그, 복호화 실패 경고, 브로커 연결 차단 사유
- 규칙 5-1: `ps aux | grep -E "python|main.py|pytest" | grep -v grep` 잔존 프로세스 0건 확인
- 실전 거래 검증은 수행하지 않음(테스트 모드 + 연결·주문 차단 상태 기준)
