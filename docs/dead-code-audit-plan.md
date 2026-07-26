# SectorFlow 데드코드·불필요 참조 전수조사 수정계획서

> 작성일: 2026-07-26
> 상태: 조사 완료 / 수정 대기
> 원칙: 본 문서는 조사 결과와 후속 계획만 기록하며, 이번 세션에서는 소스 코드·테스트 코드·설정·DB를 수정하지 않음.

---

## 1. 조사 목적

프로젝트 전체에서 실제 실행 경로에 연결되지 않은 함수·변수·상수·타입·인터페이스·import와 주석 처리된 코드 블록을 확인했다. 단순한 텍스트 검색 결과를 그대로 데드코드로 확정하지 않고, 프레임워크 등록 경로·테스트 사용 여부·추상 인터페이스 계약·동적 참조를 함께 대조했다.

특히 다음을 구분했다.

- **운영 경로 참조 0건**: 실제 삭제 검토 우선 대상
- **운영 코드에서는 미사용이나 테스트에서 사용**: 운영 dead path 후보이지만 테스트 계약을 먼저 정리해야 하는 대상
- **정적 분석 오탐**: 추상 메서드·FastAPI 데코레이터·동적 설정·외부 계약 때문에 유지되는 대상
- **데드코드와 별개인 품질 신호**: lint 오류·undefined name 등은 별도 수정 항목으로 기록

## 2. 조사 범위와 방법

### 2.1 대상

- 백엔드 운영 코드: `backend/app/`
- 백엔드 테스트·스크립트: `backend/tests/`, `backend/scripts/`
- 프론트엔드 운영 코드: `frontend/src/`
- 프론트엔드 테스트: `frontend/tests/`
- 참고 문서: `AGENTS.md`, `ARCHITECTURE.md`, `HANDOVER.md`, `docs/architecture_audit_plan.md`, `docs/architecture_audit_tasks.md`

### 2.2 수행한 확인

- Python 정의·참조 전체 검색
- `vulture backend` 정적 분석(신뢰도 60% 및 80% 기준)
- `pyflakes backend` 미사용 import/변수 및 이름 오류 확인
- TypeScript `npm run typecheck` 실행(`noUnusedLocals`, `noUnusedParameters` 활성화)
- ESLint 실행
- 주석 처리된 실행 코드·TODO/DEPRECATED/legacy 표기 검색
- 기존 아키텍처 감사 및 F-07 타입 정리 이력과 대조
- 라우트·예외 핸들러·추상 메서드·테스트 전용 함수의 실제 사용 경로 확인

## 3. 조사 결론

### 3.1 운영 코드에서 우선 확인할 dead-code 후보

아래 항목은 현재 운영 코드의 정상 호출 경로에서 참조되지 않거나, 정의·쓰기만 확인된 후보이다. 삭제 확정이 아니라 후속 별도 세션에서 사용 의도와 외부 계약을 확인한 뒤 처리한다.

| ID | 우선순위 | 위치 | 후보 | 확인 결과 | 관련 원칙 |
|---|---|---|---|---|---|
| DC-01 | 중간 | `backend/app/core/settings_defaults.py:178` | `DEFAULT_BROKER_CREDENTIALS` | ☑ 제거 — 정의 1건만 확인. 전체 코드·테스트 참조 0건. `coupling-settings-impact-matrix.md` 문서 참조 정리 | P16, P24 |
| DC-02 | 중간 | `backend/app/services/engine_state.py:111` | `EngineState.shutdown_requested` | ☑ 제거 — 운영 코드 읽기·쓰기 참조 0건. dead code 메타 테스트·mock 정리 | P16, P24 |
| DC-03 | 중간 | `backend/app/services/engine_state.py:146` | `EngineState.MIN_CACHE_LIFETIME_SEC` | ☑ 제거 — 운영 읽기 참조 0건. 선언·메타 테스트 정리 | P16, P24 |
| DC-04 | 낮음 | `backend/app/services/engine_state.py:148` | `EngineState.confirmed_refresh_running` | ☑ 제거 — 쓰기 0건, 읽기 2건을 `confirmed_refresh_running_confirmed`/`_5d` 실제 플래그로 전환 후 제거. P21 사용자 투명성 복원 (다운로드 중 상태 표시), P16 중복 다운로드 차단 복원 | P16, P21, P24 |
| DC-05 | 낮음 | `backend/app/core/ls_rest.py:212` | `LsRestAPI.call_api` | ⊘ 보류 — 운영 코드 참조 0건이나 테스트 7개 메서드(`TestLsRestCallApi`) 존재. 테스트 계약 확인 필요 | P16, P24 |
| DC-06 | 낮음 | `backend/app/web/ws_manager.py:8` | `asyncio` import | ☑ 제거 — 파일 내 사용 0건으로 pyflakes가 확정 보고. import 제거 완료 | P16, P24 |
| DC-13 | 낮음 | `backend/app/config.py:47,48,52` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADING_LOG_PATH` | ☑ 제거 (DC-S7) — Pydantic Settings 필드이나 소비처 0건. 텔레그램 설정 SSOT는 settings.json(DB) → `engine_settings._build_telegram_settings()`, 로그 경로는 `logger.py:158` 고정. P10(중복 SSOT)/P21(사용자 착각 유발) 위반 → 제거 완료 | P10, P16, P21, P24 |

> `DC-02`~`DC-04`는 기존 `engine_state.py` 문서에 이미 dead-code 후보로 기록되어 있어 새 발견이 아니라 잔여 항목 재확인이다. 삭제 시 해당 문서·메타 테스트·참조 주석을 함께 정리해야 한다.

### 3.2 운영 코드에서는 미사용이나 테스트에서만 사용되는 함수

전체 프로젝트 기준으로 호출 0건은 아니므로 “정의만 있고 전체 호출 0건”으로 확정하지 않았다. 다만 프로덕션 실행 경로에는 연결되지 않아, 테스트가 해당 API의 유지 계약인지 먼저 결정해야 한다.

| ID | 위치 | 함수/상수 | 현재 사용 | 후속 검토 |
|---|---|---|---|---|
| DC-07 | `backend/app/core/kiwoom_stock_rest.py:282` | `fetch_ka10081_all_stocks_5day` | ☑ 제거 — 운영 경로 `fetch_ka10081_daily_5d_data`(단건) 사용, batch wrapper는 테스트 전용 | 제거 완료 (DC-S3) |
| DC-08 | `backend/app/services/circuit_breaker.py:116` | `reset_circuit_breaker` | ☑ 제거 — 운영 경로 0건, `CircuitBreaker.reset()` 메서드가 실제 reset 담당, 모듈 래퍼는 테스트 전용 (P16) | 제거 완료 (DC-S4) |
| DC-09 | `backend/app/services/engine_account.py:56,65` | `get_total_buy_amount`, `get_total_pnl` | ☑ 제거 — 운영 경로 0건, 테스트 전용 (P16). `_refresh_account_snapshot_meta`가 인라인 합산으로 동일 기능 수행 | 제거 완료 (DC-S5) |
| DC-10 | `backend/app/services/engine_ws_parsing.py:150,162` | `parse_fid9081_exchange`, `parse_fid290_session` | ☑ 제거 — FID 9081/290 운영 코드 참조 0건, NXT 준비용 미사용 파서 | 제거 완료 (DC-S3) |
| DC-11 | `backend/app/services/settlement_engine.py:55` | `check_buy_power` | ☑ 제거 — 운영 경로 0건, `reserve_buy_power`가 동일 검증+즉시 차감으로 대체 (P15/P16) | 제거 완료 (DC-S4) |
| DC-12 | `backend/app/core/settings_store.py:112,431` | `changed_keys_general_save`, `load_integrated_system_settings_for_editing` | ☑ 제거 — 운영 경로 0건, 테스트 전용 (P16). `changed_keys_general_save` 제거 시 cascading dead code 3개(`general_save_payload_from_flat`, `_payload_values_equal`, `_account_field_or_legacy_flat`) 함께 제거. `apply_settings_updates`는 `_compute_changed_keys`로 독립적 변경 추적 수행 | 제거 완료 (DC-S5) |

### 3.3 정적 분석에서 발견된 미사용 변수·매개변수

#### 운영 코드

| 위치 | 항목 | 판단 |
|---|---|---|
| `backend/app/core/broker_connector.py:55,60` | 추상 메서드 매개변수 `data_types` | ☑ 오탐 확정 (DC-S7) — 추상 브로커 계약 시그니처. 구현(kiwoom/ls)은 `subscribe_stocks`로 위임하며 `data_types` 무시. 테스트 4건(`test_kiwoom_connector.py:520,527`, `test_ls_connector.py:623,630`)이 `subscribe("005930", ["0B"])` 형태로 호출. 운영은 `subscribe_stocks`/`subscribe_dynamic`/`subscribe_index` 사용. 추상 계약 + 테스트 경로 활성 → 유지 (P16, 계획 섹션5 보류 항목) |
| `backend/app/core/kiwoom_connector.py:271,275` | `data_types` | ☑ 오탐 확정 (DC-S7) — 상동. 구현부 `subscribe`/`unsubscribe`는 `subscribe_stocks([code])`로 위임, `data_types`는 하위 호환성용 무시 |
| `backend/app/core/ls_connector.py:432,436` | `data_types` | ☑ 오탐 확정 (DC-S7) — 상동 |
| `backend/app/web/deps.py:13` | `credentials` | ☑ 오탐 확정 (DC-S7) — 개발 모드 인증 자리표시자. `HTTPBearer` 의존성으로 토큰 추출 시그니처 유지, 프로덕션 전환 시 검증 로직 추가 예정. DC-S7 규칙3 — 보안 설계 과제로 유지 |
| `backend/app/services/engine_utils.py:54` | `args` | ☑ 오탐 확정 (DC-S7) — `async __aexit__(self, *args)` 프로토콜 필수 시그니처. `*args`는 `(exc_type, exc_val, exc_tb)` 캡처. async context manager 계약 → 유지 |
| `backend/app/config.py:47,48,52` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADING_LOG_PATH` | ☑ 제거 (DC-13, DC-S7) — Pydantic Settings 필드이나 소비처 0건. 텔레그램 설정 SSOT는 settings.json(DB) → `engine_settings._build_telegram_settings()`, 로그 경로는 `logger.py:158` 고정. P10(중복 SSOT)/P21(사용자 착각 유발) 위반 → 제거 완료 |
| `backend/app/config.py:54` | `model_config` | ☑ 오탐 확정 (DC-S7) — Pydantic BaseSettings 메타 설정(env_file/encoding/case_sensitive/extra). 런타임 필수 → 유지 |
| `backend/app/core/stock_filter.py:126` | `parsed_fields` | ☑ 오탐 확정 (DC-S7) — `StockFilterEvaluation` dataclass 필드. `stock_filter.py:235`에서 설정, `test_stock_filter.py:283-288`에서 검증. vulture 60%는 dataclass 필드 접근 미추적 오탐 → 유지 |
| `backend/app/domain/models.py:53` | `sector_rank` | ☑ 오탐 확정 (DC-S7) — `BuyTarget` dataclass 필드. `buy_filter.py:247,256`에서 설정, `test_buy_filter.py:507`에서 검증 → 유지 |
| `backend/app/domain/models.py:64` | `version` | ☑ 오탐 확정 (DC-S7) — `SectorSummary` dataclass 필드. `buy_filter.py:263,272`에서 카운터 증가+설정, `test_buy_filter.py:514`에서 검증 → 유지 |

#### 테스트·스크립트 코드

`pyflakes`와 `vulture`에서 다음 유형이 확인되었다. 운영 기능과 분리된 후속 테스트 품질 정리 대상으로 기록한다.

- `backend/tests/test_data_manager.py`: `pytest`, `MagicMock` 미사용 import
- `backend/tests/test_engine_ws_dispatch_isolation.py`: `asyncio` 미사용 import
- `backend/tests/test_engine_state_groups.py`: `subprocess` 미사용 import
- `backend/tests/test_kiwoom_rest.py`, `test_kiwoom_providers.py`: 미사용 지역 변수·import
- `backend/tests/test_engine_loop.py`: `AwaitableMock`, `mock_sw` 미사용
- `backend/tests/test_daily_time_scheduler.py`: countdown 상수 import 및 `sched_ctx` 미사용
- `backend/tests/test_notification_worker.py`: `mock_task` 미사용 및 `raise` 뒤 unreachable code
- `backend/tests/test_pipeline_compute.py`: `seconds` 미사용
- `backend/tests/test_sector_calculator_integration.py`: `setup_master_cache` fixture 미사용
- `backend/tests/test_settlement_verification.py`: `task` 미사용
- `backend/tests/test_broker_change.py`: `_UNREG_BATCH_PENDING` 미사용
- `backend/scripts/migrate_realized_pnl_cash.py`: `sys` 미사용 import
- `backend/tests/test_buy_order_executor.py`: 다수의 `reset_cash_gate` fixture 매개변수 미사용. fixture 자동 적용 여부를 확인한 뒤 매개변수만 제거할지 판단

### 3.4 프론트엔드 함수·변수·타입·인터페이스 조사 결과

- `frontend/tsconfig.json`에서 `noUnusedLocals: true`, `noUnusedParameters: true`가 활성화되어 있다.
- `npm run typecheck`는 통과했다. 따라서 컴파일러 기준의 일반적인 미사용 지역 변수·매개변수·import는 현재 발견되지 않았다.
- 기존 F-07에서 확인된 미사용 타입 5개와 필드는 이미 제거되었으며, 현재 잔존 여부는 확인되지 않았다.
- 내보낸 타입·인터페이스는 `types/index.ts`, 페이지 공통 모듈, 공통 컴포넌트에서 실제 import/구조 타입으로 사용되는 것을 확인했다. 이번 조사에서 “정의만 있고 전체 프로젝트 참조 0건”으로 확정할 프론트엔드 타입은 발견하지 못했다.
- `vulture`/`pyflakes`에 대응하는 프론트엔드 전용 export 사용 분석 도구는 프로젝트 의존성에 없으므로, export된 public API는 텍스트 참조만으로 삭제 확정하지 않았다.

### 3.5 주석 처리된 죽은 코드 블록

실행 코드가 통째로 주석 처리된 블록은 백엔드 운영 코드와 프론트엔드 `src`에서 확정하지 못했다. 검색된 주석은 대부분 설명·계산식·레거시 호환 문서였다.

다만 아래는 후속 확인 대상이다.

- `backend/app/web/routes/ws_settings.py:18`
- `backend/app/web/routes/ws_orders.py:18`

두 파일의 `# TODO: 개발 완료 후 토큰 검증 재활성화`는 주석 처리된 코드 블록은 아니지만, 인증 검증이 비활성화된 상태를 나타낸다. 데드코드 삭제 대상이 아니라 보안·운영 전환 과제로 분리해야 한다.

### 3.6 정적 분석의 오탐 또는 별도 품질 이슈

- `backend/app/core/settings_file.py:344`의 `SecretValueState` pyflakes undefined 보고 — ☑ 근본 해결 (DC-S7). 원인: `_classify_secret()` 반환 타입 문자열 주석 `"SecretValueState"`가 모듈 스코프에서 미정의(함수 내부 임포트). 근본 해결: `TYPE_CHECKING` 블록에서 `SecretValueState` 타입 임포트 추가, 런타임 임포트는 함수 본문 유지. pyflakes 0경고 확인.
- FastAPI 라우트·예외 핸들러·SPA fallback·WebSocket 엔드포인트는 일반 호출 검색과 vulture에서 미사용 함수처럼 보이지만 데코레이터/라우터 등록으로 살아 있는 진입점이다. 예: `backend/app/web/routes/*`, `backend/app/web/app.py`.
- 브로커 추상 메서드 `subscribe`, `unsubscribe`, `receive`는 자식 구현·인터페이스 계약 대상이므로 vulture 결과만으로 삭제하지 않는다.
- `frontend/src/components/common/info-tooltip.ts:99`의 ESLint no-unused-expressions 오류 — ☑ 근본 해결 (DC-S7). 원인: `popup ? close() : open()` 삼항식이 함수호출 표현식으로 평가. 근본 해결: `if (popup) close() else open()` 분기로 전환. ESLint 0경고 확인.

## 4. 우선순위별 후속 수정 계획

### 4.1 1순위: 운영 경로 0건 후보 재확인

1. `DC-01`, `DC-05`, `DC-06`의 전체 참조와 외부 계약을 다시 확인한다.
2. `DC-02`~`DC-04`는 `engine_state` 문서·메타 테스트·주석까지 함께 검토한다.
3. 삭제 시 거래 경로·엔진 기동·브로커 연결에 영향이 없는지 관련 테스트를 먼저 작성하거나 기존 테스트의 의도를 확인한다.
4. 승인된 별도 세션에서 한 묶음씩 수정하고, 참조 주석·docstring·메타 테스트를 함께 정리한다.

### 4.2 2순위: 테스트 전용 함수·미사용 테스트 자산

- DC-07~DC-12는 테스트만 삭제하면 회귀 보호가 약해질 수 있으므로, 운영 호출 경로가 정말 불필요한지 확인한 후 API 유지/삭제를 결정한다.
- 테스트 import·fixture 매개변수·지역 변수는 기능 테스트에 영향을 주지 않는지 확인 후 별도 테스트 품질 세션에서 정리한다.

### 4.3 보류

- 인증 placeholder(`credentials`)와 인증 재활성화 TODO는 데드코드 삭제가 아니라 보안 설계·사용자 승인 과제다.
- FastAPI 진입점, 브로커 추상 메서드, 동적 설정·모델 필드는 프레임워크·외부 계약 확인 전 삭제하지 않는다.
- 프론트엔드 export 타입은 현재 typecheck 통과 상태이므로 별도 TypeScript export graph 도구 도입 없이 삭제하지 않는다.

## 5. 아키텍처 원칙 점검

- **P10 SSOT**: 정의만 남은 설정 상수·상태 필드를 제거할 때 다른 설정 저장소나 파생 상태를 새로 만들지 않는다.
- **P16 살아있는 경로**: 실제 호출 경로가 있는 라우트·추상 메서드·테스트 계약은 정적 분석만으로 dead code 처리하지 않는다.
- **P20 폴백 금지**: 미사용 정리 과정에서 인증·설정·암호화의 정상 경로를 임의의 빈값/None 폴백으로 바꾸지 않는다.
- **P21 사용자 투명성**: 주문·인증·엔진 상태에 연결된 플래그를 삭제할 경우 UI와 로그의 상태 표시를 먼저 확인한다.
- **P22 데이터 정합성**: 상태 변수·모델 필드 제거 시 DB/브로커 응답/프론트 계약과의 불일치를 차단한다.
- **P23 일관성**: 기존 공통 타입·추상 계약·테스트 fixture를 우선 재사용하고, 삭제된 항목의 주석·문서 참조도 함께 정리한다.
- **P24 단순성**: 운영 호출 0건인 후보부터 검토하며, 테스트 전용·프레임워크 진입점까지 일괄 삭제하지 않는다.
- **P25 격리된 실패**: 데드코드 정리로 한 태스크나 브로커 구성요소의 실패가 전체 기동을 막지 않도록 관련 런타임 검증을 수행한다.

## 6. 후속 검증 계획

코드 수정 승인 후 별도 세션에서 대상별로 다음을 수행한다.

- 백엔드 관련 테스트 및 전체 `pytest`
- `python -W error::RuntimeWarning main.py` 기동 검증
- 프론트엔드 `typecheck`, `build`, 테스트
- 제거 대상 이름의 전체 저장소 잔존 검색
- 라우트/데코레이터/추상 메서드 등록 확인
- 기존 DB 파일은 읽기만 하며 삭제·덮어쓰기하지 않음

이번 세션에서 실행한 검증은 문서·조사 전용이며 소스 수정은 없었다.

## 7. 참고 파일

- `backend/app/core/settings_defaults.py`
- `backend/app/core/ls_rest.py`
- `backend/app/web/ws_manager.py`
- `backend/app/services/engine_state.py`
- `backend/app/core/settings_store.py`
- `backend/app/services/circuit_breaker.py`
- `backend/app/services/engine_account.py`
- `backend/app/services/engine_ws_parsing.py`
- `backend/app/services/settlement_engine.py`
- `frontend/src/types/index.ts`
- `frontend/tsconfig.json`
- `HANDOVER.md`
- `docs/architecture_audit_plan.md`
- `docs/architecture_audit_tasks.md`
