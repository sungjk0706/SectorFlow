# 태스크 파일: 뉴스 가산점 근본 구현

> 상태: 작성 완료 · 사용자 승인 대기 (구현 세션 시작 전 결정 항목 5건 확정 필요)
> 작성일: 2026-07-28
> 기준 설계서: `docs/news-boost-fix-design-v2.md` (v2 — 잘못된 로직 제거)
> 다단계 진행: 설계 ✅ (`news-boost-fix-design-v2.md`) · 세부 태스크 작성 ✅ · 구현 대기 (세션 1~5)
> 관련 원칙: P7, P10, P11, P16, P20, P21, P22, P23, P24, P25
> 관련 파일: `backend/app/services/engine_account_notify.py`, `backend/app/services/sector_data_provider.py`, `backend/app/pipelines/pipeline_compute_tick_handlers.py`, `frontend/src/stores/hotStore.ts`, `frontend/src/binding.ts`, `frontend/src/pages/buy-target-columns.ts` 외 세션별 목록 참조
> 관련 API/이벤트 스펙: `buy-targets-update`, `buy-targets-delta`, `news-hit`(신설), `_BUY_TARGET_CMP_KEYS`, `_BUY_TARGET_REALTIME_KEYS`, `news_boost_cache`, `boost_score`

---

## 0. 사전조사 결과 요약

> 본 요약은 설계서(`docs/news-boost-fix-design-v2.md`) 섹션 1·3·4를 실행 관점으로 재정리. 각 구현 세션 시작 시 변경 전 재검색(규칙 0-2). 코드 라인은 설계서 작성일(2026-07-28) 기준이며 구현 시점에 미확인 변경이 있을 수 있음.

### 0.1 의존성

| 파일 | 확인된 호출·변경 관계 | 기준 라인 |
|---|---|---:|
| `backend/app/services/engine_account_notify.py` | `_BUY_TARGET_REALTIME_KEYS`(delta 제외 키)와 `_BUY_TARGET_CMP_KEYS`(changed 판정 키) 정의. 현재 `news_boost`가 cmp_keys에 포함("세션 8 결함 B 수정" 주석, 잘못된 수정). delta의 added/changed에서 `_BUY_TARGET_REALTIME_KEYS` 일괄 제거(P24 패턴 이미 존재). | 362-366, 378, 411, 419, 422 |
| `backend/app/services/sector_data_provider.py` | `_build_target_entry`에서 `news_boost_cache`를 읽어 buy_targets 엔트리에 `news_boost` 필드로 끼워넣기. 초기 스냅샷(`buy-targets-update`) 전송에 사용 → D-1 채택 시 유지, delta에서는 제외 필요. | 125-174 |
| `backend/app/pipelines/pipeline_compute_tick_handlers.py` | `_handle_nws_news()`가 뉴스 수신 시 `news_boost_cache` 갱신 + 로그. 현재 브로드캐스트 없음 → `news-hit` 브로드캐스트 추가 위치. | 340, 377-385 |
| `backend/app/domain/buy_filter.py` | `calculate_boost_score`가 `news_boost_cache` 기반 `boost_score` 산출(순위 정렬용). **유지 대상** — news_boost/boost_score 분리의 핵심. | 22, 57-62, 130, 190 |
| `backend/app/services/engine_radar.py` | `get_news_boost_cache()` 노출. **유지**. | 26, 34-35 |
| `backend/app/services/engine_state.py` | `news_boost_cache` 보관. **유지**. | 16-17, 151-157 |
| `frontend/src/stores/hotStore.ts` | `applyBuyTargetsUpdate` same 비교에 `news_boost` 포함(잘못된 로직 #3). `applyBuyTargetsDelta`/`applyBuyTargetsUpdate`의 `normalizeStockCode` + `setState` 패턴 → `applyNewsHit` action이 동일 패턴 재사용. | 530, 562 |
| `frontend/src/binding.ts` | WS 이벤트 핸들러 등록 위치. `circuit-breaker-open` 등 기존 패턴 → `news-hit` 핸들러 추가. | 244-249 |
| `frontend/src/pages/buy-target-columns.ts` | 📰 아이콘 렌더링(현재 `news_boost > 0` 표시). **변경 없음**(설계 4.2) — 툴팁 연결은 세션 4에서 동일 파일에 추가 가능. | 104-106 |
| `frontend/src/components/common/info-tooltip.ts` | 공통 툴팁 컴포넌트(재사용 후보, P23). 📰 아이콘 툴팁에 재사용 검토. | 14, 69 |
| `frontend/src/components/common/ui-styles.ts` | 툴팁 스타일 토큰 보관(재사용 후보). | 216-242 |
| `frontend/src/components/common/toast.ts` | 토스트 단일 슬롯 컴포넌트(UI-TOAST-DIALOG-MACOS-01 완료). `showToast(type, msg, duration)` 재사용. | — |
| `frontend/src/types/index.ts` | `news_boost` 타입 이미 존재. `NewsHitEvent` 타입 추가(선택). | 63, 209 |
| `backend/tests/test_engine_account_notify.py` | `_BUY_TARGET_CMP_KEYS`/`_BUY_TARGET_REALTIME_KEYS` 검증 테스트. `test_cmp_keys_excludes_realtime_and_includes_news_boost`(news_boost 포함 기대) · `test_delta_changed_news_boost_triggers_change` → 수정/제거 대상. | 25-26, 632-786 |
| `backend/tests/test_pipeline_compute_nws_handler.py` | NWS 핸들러 단위 테스트. `news-hit` 브로드캐스트 검증 추가. | 16-72 |
| `frontend/tests/stores/hotStore.test.ts` | `news_boost 변경 시 setState 발화` 테스트 + `applyNewsHit` 단위 테스트 추가/수정. | 305-418 |
| `backend/tests/test_sector_data_provider.py` | `_build_target_entry`의 `news_boost` 필드 검증. 초기 스냅샷 유지 시 현행 유지, delta 제외 시 추가 검증. | 168-225 |

### 0.2 영향 범위

- **백엔드 핵심**: `buy-targets-delta`의 `changed` 판정에서 `news_boost` 제외, NWS 처리 경로에 `news-hit` 브로드캐스트 추가. 업종 재계산 로직(`_flush_sector_recompute_impl`)·매수 후보 선정 알고리즘·`boost_score` 산출은 변경 없음.
- **백엔드 연관**: `news_boost_cache` 단일 진실 소스 유지, `calculate_boost_score`의 `news_boost_cache` 참조 유지(순위용). `engine_radar.get_news_boost_cache()` 유지.
- **프론트엔드**: `hotStore.buyTargets`의 `news_boost` 갱신 경로 단일화(`applyNewsHit`만), `applyBuyTargetsUpdate` same 비교에서 `news_boost` 제거, 📰 컬럼 즉시 갱신 + 토스트 팝업 + 툴팁.
- **DB**: 스키마 변경 없음(안전 규칙 1 준수). `news_boost_cache`는 메모리 상태.
- **거래 안전**: 매수·매도 로직, 주문 단일 경로(`execute_buy()`/`execute_sell()`), 리스크 임계값, 브로커 연결은 범위에서 제외. `boost_score`가 순위에 미치는 영력은 기존 설계 의도(체결 틱 시 반영) 유지.

### 0.3 아키텍처 원칙 부합

- **P7 ✅**: 뉴스 처리는 O(1) 캐시 갱신 + `news-hit` 브로드캐스트 1회(O(len(hit_codes))). per-tick 재계산 안 함.
- **P10 ✅**: `news_boost` 단일 전달 경로 = `news-hit` 이벤트. `buy-targets-delta`에서 제거. `news_boost_cache` 단일 진실 소스 유지. `news_boost`(표시용)와 `boost_score`(순위용) 완전 분리.
- **P11 ✅**: 이벤트 기반(NWS 수신 → 즉시 브로드캐스트). `while + sleep` 폴링 미도입.
- **P16 ✅**: `news-hit` 브로드캐스트가 `_handle_nws_news` 실제 실행 경로에 연결. dead code 아님.
- **P20 ✅**: 종목명 부재 시 빈 문자열(명시적 값, 폴백 아님). silent `except: pass` 금지 — `_safe_broadcast` 내부 `logger.warning(..., exc_info=True)` 유지.
- **P21 ✅**: 📰 컬럼 즉시 갱신(체결 틱 대기 제거) + 토스트 팝업으로 사용자 인지. 툴팁으로 호재 정보 추가 노출.
- **P22 ✅**: `news_boost`(표시용)와 `boost_score`(순위용)의 파생 관계 명확 — 동일 `news_boost_cache`에서 독립 경로로 산출.
- **P23 ✅**: `news-hit`(kebab-case, 기존 41개 이벤트 컨벤션), `applyNewsHit`(camelCase) — 네이밍 일관. 공통 툴팁·토스트 컴포넌트 재사용.
- **P24 ✅**: delta 제외 키 패턴(`_BUY_TARGET_REALTIME_KEYS` 일괄 제거) 재사용. 동일 갱신 로직 중복 제거. 신규 상수 도입은 최소.
- **P25 ✅**: `_safe_broadcast` 내부 예외 처리 — 브로드캐스트 실패 시 뉴스 처리·엔진 루프 블로킹 금지. 프론트 `setState` updater는 store listener 루프에서 보호.

### 0.4 기존 공통 자산 확인

- **재사용**: `_safe_broadcast()`, `schedule_engine_task()`, `logger.info("[연산] 뉴스 가산점 부여 — ...")`(기존 로그), `_BUY_TARGET_REALTIME_KEYS` delta 제외 패턴, `normalizeStockCode()`, `hotStore.setState`, `showToast(type, msg, duration)`, `frontend/src/components/common/info-tooltip.ts`, `frontend/src/components/common/ui-styles.ts` 툴팁 토큰, `frontend/src/components/common/toast.ts`.
- **재사용(테스트)**: `fresh_engine` 픽스처, `_mock_helpers.py` awaitable mock 헬퍼, 기존 `applyBuyTargetsDelta`/`applyBuyTargetsUpdate` 단위 테스트 패턴.
- **신규 생성 제한**: 새 SSOT·새 주문 함수·새 이벤트 버스·새 DB 테이블·중복 색상/상수/normalize 함수 금지. `news-hit` 이벤트 1개·`applyNewsHit` action 1개·(선택) `NewsHitEvent` 타입 1개만 신규. `_BUY_TARGET_DELTA_EXCLUDE_KEYS` 신규 상수는 기존 `_BUY_TARGET_REALTIME_KEYS` 재사용 여부를 세션 1에서 최종 결정(P24 단순성 우선).

---

## 1. 단계 분할

> 규칙: 한 세션에는 한 단계만 진행(규칙 0-1). 각 세션은 태스크 확인 → 사용자 승인 → 수정/문서화 → 해당 단계 검증 → 커밋 및 인계 순서. 아래 파일 목록은 조사 결과 기준이며, 실제 구현 세션 시작 시 변경 전 재검색(규칙 0-2).

### 세션 1 — 백엔드: 잘못된 로직 #1·#2·#4 제거 (cmp_keys + delta에서 news_boost 제거)

- **목표**: `buy-targets-delta`의 `changed` 판정에서 `news_boost`를 제외해 업종 재계산 경로와 뉴스 갱신 경로를 분리한다. 잘못된 로직 #4(`notify_buy_targets_update`의 `news_boost` changed 전송)는 #1 제거로 자연 제거.
- **수정 파일 목록**:
  - `backend/app/services/engine_account_notify.py`
  - `backend/app/services/sector_data_provider.py` (delta 제외 로직 연동 확인)
  - `backend/tests/test_engine_account_notify.py`
  - 필요 시 `backend/tests/test_sector_data_provider.py`
- **파일별 변경점**:
  - `_BUY_TARGET_CMP_KEYS`에서 `"news_boost"` 제거. "세션 8 결함 B 수정" 주석 제거(코드 제거 규칙 — 잘못된 수정이었으므로) 및 docstring/인접 주석 동기화.
  - delta의 `added`/`changed` 항목에서 `news_boost` 제외. 두 안 중 하나 선택(세션 1 사전조사 시 최종 결정, P24 단순성 우선):
    - **안 A(권장, 단순)**: 기존 `_BUY_TARGET_REALTIME_KEYS`에 `"news_boost"` 추가 → 기존 일괄 제거 루프(line 411, 419)가 자동 적용. 단, 상수명 "REALTIME"의 의미가 `news_boost`(뉴스 이벤트 기반)와 미묘히 어긋나는 점은 주석로 명시.
    - **안 B(의미 명확, 코드 증가)**: 신규 상수 `_BUY_TARGET_DELTA_EXCLUDE_KEYS = _BUY_TARGET_REALTIME_KEYS + ("news_boost",)` 도입 후 제거 루프를 신규 상수 기반으로 전환.
  - `_build_target_entry`의 `news_boost` 필드는 **유지**(초기 스냅샷 `buy-targets-update`용, 결정 5 = D-1 전제). 단, delta 경로에서는 제외되도록 위 안 A/B와 연동.
  - `test_cmp_keys_excludes_realtime_and_includes_news_boost` → `news_boost` 제거 반영으로 수정(테스트명도 재검토). `test_delta_changed_news_boost_triggers_change` → 제거 또는 "delta에서 news_boost 미전송" 검증으로 전환.
- **변경하지 않을 범위**: `_handle_nws_news()` 브로드캐스트(세션 2), `calculate_boost_score`(유지), 프론트엔드(세션 3), 매수 후보 선정 알고리즘, 주문 경로.
- **검증 방법**: `.venv/bin/python -m pytest backend/tests/test_engine_account_notify.py backend/tests/test_sector_data_provider.py -q -W error::RuntimeWarning` → 전체 백엔드 테스트 `.venv/bin/python -m pytest backend/tests -q -W error::RuntimeWarning` → `.venv/bin/python -W error::RuntimeWarning main.py` 런타임 기동(0-1-3 잔존 프로세스 0건 확인).
- **합격 기준**: `buy-targets-delta`의 `changed`에 `news_boost`가 포함되지 않음을 테스트가 고정. 초기 `buy-targets-update`에는 `news_boost` 포함(D-1). 기존 정상 테스트 전부 통과. RuntimeWarning 0건. 런타임 기동 정상.
- **실패 시 중단 기준**: delta 제외 로직 변경이 초기 스냅샷 전송까지 영향을 주어 초기 로드 시 `news_boost`가 누락되거나, 기존 `changed` 판정 필드가 의도치 않게 제외됨. 안 A·B 모두 기존 패턴을 훼손할 경우 사용자 결정 항목으로 인계.
- **커밋 단위**: cmp_keys/delta에서 news_boost 제거 + 주석 정리 + 테스트 수정.
- **다음 세션 인계 조건**: 백엔드 단위·전체 테스트·런타임 기동·잔존 프로세스 0건 검증 통과가 `HANDOVER.md`에 기록됨.

### 세션 2 — 백엔드: `news-hit` WS 이벤트 브로드캐스트 추가 (news_boost 전달 경로 신설)

- **목표**: `_handle_nws_news()`가 뉴스 호재 매칭 시 `news-hit` 이벤트를 브로드캐스트해 `news_boost` 단일 전달 경로(P10)를 확보한다. `news_boost`(표시용)와 `boost_score`(순위용) 분리의 백엔드 측 완료.
- **수정 파일 목록**:
  - `backend/app/pipelines/pipeline_compute_tick_handlers.py`
  - `backend/tests/test_pipeline_compute_nws_handler.py`
  - 필요 시 `backend/app/services/engine_account_notify.py`(`_safe_broadcast` import 경로 확인)
- **파일별 변경점**:
  - `_handle_nws_news()`의 `hit_codes` 처리 블록에 `await _safe_broadcast("news-hit", {codes, names, scores, ...})` 추가. `names`는 `engine_state.state.master_stocks_cache`에서 조회(부재 시 빈 문자열, P20).
  - payload 필드: `{codes, names, scores}` + (결정 4 = 포함 시) `title`. `scores`는 동일 `news_boost_score` 값의 리스트.
  - P23 네이밍: `news-hit`(kebab-case, 기존 41개 이벤트 컨벤션 일치). P25: `_safe_broadcast` 내부 예외 처리 유지 — 브로드캐스트 실패 시 뉴스 처리 정상 완료. P7: 브로드캐스트 1회 O(len(hit_codes)).
  - 테스트: `news-hit` 브로드캐스트 호출·payload·`hit_codes` 빈 경우 미전송을 검증. `_safe_broadcast` 실패 시 뉴스 처리가 중단되지 않음(P25) 검증.
- **변경하지 않을 범위**: 세션 1의 cmp_keys/delta 변경 결과 유지, `calculate_boost_score`(유지), 프론트엔드(세션 3), 주문 경로.
- **검증 방법**: `.venv/bin/python -m pytest backend/tests/test_pipeline_compute_nws_handler.py -q -W error::RuntimeWarning` → 전체 백엔드 테스트 → `.venv/bin/python -W error::RuntimeWarning main.py` 런타임 기동 + 잔존 프로세스 0건.
- **합격 기준**: 뉴스 호재 매칭 시 `news-hit`이 1회 브로드캐스트, `hit_codes` 빈 경우 미전송, 브로드캐스트 실패 시에도 `news_boost_cache` 갱신·로그는 정상 완료. RuntimeWarning 0건.
- **실패 시 중단 기준**: `_safe_broadcast`가 await 누락 또는 `create_task` 무분별 분리(금지 패턴)로 호출되거나, 브로드캐스트 실패가 뉴스 처리·엔진 루프를 블로킹(P25 위반).
- **커밋 단위**: `news-hit` 브로드캐스트 추가 + 테스트.
- **다음 세션 인계 조건**: 백엔드 전체 검증 + 런타임 기동 통과가 `HANDOVER.md`에 기록됨. 프론트엔드는 아직 `news-hit`을 수신하지 못하므로 세션 3 완료 전까지 화면 변화 없음(내부 개선).

### 세션 3 — 프론트엔드: `applyNewsHit()` action + binding 핸들러 + same 비교 제거 (잘못된 로직 #3)

- **목표**: 프론트 `hotStore`가 `news-hit`을 수신해 해당 종목의 `news_boost`만 patch. `applyBuyTargetsUpdate` same 비교에서 `news_boost` 제거(잘못된 로직 #3)로 갱신 경로 단일화(P10).
- **수정 파일 목록**:
  - `frontend/src/stores/hotStore.ts`
  - `frontend/src/binding.ts`
  - `frontend/src/types/index.ts` (`NewsHitEvent` 타입 추가, 선택)
  - `frontend/tests/stores/hotStore.test.ts`
- **파일별 변경점**:
  - `hotStore.ts`: `applyNewsHit(data: { codes, names, scores, ... })` action 추가. `normalizeStockCode` + `hotStore.setState` 패턴(`applyBuyTargetsDelta`/`applyBuyTargetsUpdate`와 동일, P23). `buyTargets` 중 해당 code의 `news_boost`만 patch.
  - `hotStore.ts`: `applyBuyTargetsUpdate` same 비교에서 `&& p.news_boost === n.news_boost` 제거(잘못된 로직 #3). 다른 정적 필드 변경 없으면 setState 발화 안 함.
  - `binding.ts`: `pricesClient.onEvent('news-hit', ...)` 핸들러 추가 → `applyNewsHit(data)` 호출. `circuit-breaker-open` 패턴 참조(설계 3.5).
  - `types/index.ts`: `NewsHitEvent` 타입 추가(선택, P23 타입 일관).
  - 테스트: `news_boost 변경 시 applyBuyTargetsUpdate에서 setState 발화 안 함` 검증(잘못된 로직 #3 제거 확인), `applyNewsHit` 단위 테스트(해당 종목만 patch·미해당 종목은 불변·빈 codes 안전).
- **변경하지 않을 범위**: 📰 아이콘 렌더링 로직(`buy-target-columns.ts`, 세션 4에서 툴팁 추가), 토스트(세션 4), 백엔드, 주문 경로.
- **검증 방법**: `cd frontend && npm run typecheck && npm run test && npm run build`.
- **합격 기준**: `applyNewsHit`이 해당 종목의 `news_boost`만 갱신, `applyBuyTargetsUpdate`는 `news_boost` 변경을 무시, typecheck/test/build 전부 통과.
- **실패 시 중단 기준**: `applyNewsHit`이 `buyTargets` 전체를 재할당하거나 미해당 종목을 변경, same 비교 제거가 다른 정적 필드 변경 감지에 영향. `normalizeStockCode` 재사용 불가 시 새 정규화 함수 생성 여부를 사용자 결정 항목으로 인계(P10/P23).
- **커밋 단위**: `applyNewsHit` action + binding 핸들러 + same 비교 제거 + 테스트.
- **다음 세션 인계 조건**: 프론트 typecheck/test/build 통과가 `HANDOVER.md`에 기록됨. 📰 컬럼 즉시 갱신 동작은 세션 4 툴팁·토스트 연결 후 브라우저 최종 확인.

### 세션 4 — 프론트엔드: 토스트 팝업 + 📰 아이콘 툴팁 연결 (결정 1 = B 전제)

- **목표**: 뉴스 호재 발생을 토스트 팝업으로 사용자에게 즉시 알리고(P21), 📰 아이콘에 마우스 호버 시 호재 정보(뉴스 제목 또는 종목명)를 툴팁으로 표시.
- **수정 파일 목록**:
  - `frontend/src/binding.ts` (토스트 호출 추가)
  - `frontend/src/pages/buy-target-columns.ts` (📰 아이콘 툴팁 추가)
  - 필요 시 `frontend/src/stores/hotStore.ts` (`news_boost`와 함께 뉴스 제목 캐시 보관 — 결정 4·6에 따라)
  - 관련 프론트 테스트
- **파일별 변경점**:
  - `binding.ts`의 `news-hit` 핸들러에서 `showToast('info', message, duration)` 호출(결정 2 포맷, 결정 3 지속 시간). `showToast`는 `components/common/toast.ts` 재사용(UI-TOAST-DIALOG-MACOS-01 단일 슬롯).
  - `buy-target-columns.ts`의 📰 아이콘에 툴팁 연결. 공통 자산 `components/common/info-tooltip.ts` 재사용을 우선(P23) — 불가 시 HTML `title` 속성 최소 대체. 툴팁 내용 = 결정 6(뉴스 제목 / 종목명 / 호재 안내 문구 중 선택).
  - 결정 4 = 포함(title) 시: `applyNewsHit`이 `title`을 `buyTargets[i]`에 보관(`news_boost_title` 등 신규 필드)하고 툴팁이 이를 표시. 결정 4 = 미포함 시: 툴팁은 종목명 + "뉴스 호재" 안내 문구만.
  - 테스트: 토스트 호출·포맷·지속 시간 검증, 📰 아이콘 툴팁 렌더링 검증.
- **변경하지 않을 범위**: 백엔드(세션 2 완료 상태 유지, 단 결정 4 = 포함 시 세션 2 payload에 `title` 추가 필요 — 세션 2 인계 조건과 충돌 시 세션 2로 회신), `applyNewsHit` 핵심 로직(세션 3), 주문 경로.
- **검증 방법**: `cd frontend && npm run typecheck && npm run test && npm run build` → 브라우저에서 뉴스 호재 시 토스트 팝업 + 📰 아이콘 호버 툴팁 확인(사용자 직접 확인 항목).
- **합격 기준**: 토스트가 단일 슬롯으로 정상 표시(포맷·지속 시간 일치), 📰 아이콘 호버 시 툴팁이 호재 정보 표시, typecheck/test/build 통과.
- **실패 시 중단 기준**: `info-tooltip.ts` 재사용이 📰 인라인 아이콘 문맥에 부적합하거나, `title` 필드 추가가 백엔드 payload 계약(결정 4)과 불일치. 툴팁 내용(결정 6) 미확정 시 사용자 결정 항목으로 인계.
- **커밋 단위**: 토스트 + 툴팁 연결 + 테스트.
- **다음 세션 인계 조건**: 프론트 build 통과 + 브라우저 확인 완료가 `HANDOVER.md` "사용자 직접 확인 항목"에 기록됨.

### 세션 5 — 문서 갱신 (이벤트 계약·파이프라인 경계·정규화 추적·아키텍처)

- **목표**: `news-hit` 이벤트 신설 및 `buy-targets-delta` payload 변경을 결합도 문서에 반영해 코드-문서 일치(P21·P23)를 유지.
- **수정 파일 목록**:
  - `docs/coupling-ws-event-contract-index.md` (`news-hit` 등록, 이벤트 41→42, `buy-targets-delta` payload에서 `news_boost` 제거 명시)
  - `docs/coupling-pipeline-boundary.md` (NWS 처리 경로 갱신 — 독립 이벤트, 체결 틱 의존성 제거)
  - `docs/coupling-stock-code-normalization.md` (`applyNewsHit`의 `normalizeStockCode` 추적 추가)
  - `ARCHITECTURE.md` (NWS 처리 흐름도 갱신 + `_BUY_TARGET_CMP_KEYS` 설명 갱신)
- **파일별 변경점**:
  - WS 이벤트 인덱스: `news-hit` 행 추가(payload 필드, 송신 위치, 수신 핸들러). `buy-targets-delta` 행의 payload에서 `news_boost` 제거.
  - 파이프라인 경계: NWS → `news_boost_cache` 갱신 → `news-hit` 브로드캐스트 경로를 명시. 체결 틱 의존성 제거.
  - 정규화 추적: `applyNewsHit`이 `normalizeStockCode`를 사용함을 추가.
  - ARCHITECTURE.md: 설계서 v2의 분리 구조도(섹션 2.3)를 아키텍처 문서로 이관 요약. `_BUY_TARGET_CMP_KEYS`에서 `news_boost` 제거 반영.
- **변경하지 않을 범위**: 코드(세션 1~4 결과 유지), `AGENTS.md`(설계 4.4 명시 — 변경 없음), 다른 결합도 문서.
- **검증 방법**: 문서 내 이벤트 수·payload 필드가 코드와 일치하는지 교차 검증. 백엔드·프론트 전체 검증 재실행으로 회귀 없음 확인(문서만 변경이지만 안전망).
- **합격 기준**: 이벤트 인덱스가 42개, `news-hit` payload가 코드와 일치, `buy-targets-delta` payload 명세에서 `news_boost` 제거, ARCHITECTURE.md의 NWS 흐름이 설계서 v2와 일치.
- **실패 시 중단 기준**: 문서 갱신 중 코드와 불일치 발견 → 세션 1~4 결과에 영향이면 해당 세션으로 회신. 문서 갱신 범위가 4개 문서를 초과할 경우 사용자 결정 항목으로 인계.
- **커밋 단위**: 문서 갱신 4건.
- **다음 세션 인계 조건**: 다단계 워크플로우 전체 완료. `HANDOVER.md` "다음 세션 진행 대기"에서 NEWS-BOOST 항목 제거. 설계서·태스크 파일 삭제 여부를 규칙 10에 따라 확인(최종 커밋).

---

## 2. 사용자 결정 항목

> 설계서 `docs/news-boost-fix-design-v2.md` 섹션 6에서 이관. 구현 세션 시작 전 확정 필요. 사용자가 "토스트 팝업 + 툴팁" 명시로 결정 1은 B로 확정. 나머지는 권장값과 함께 대기.

| # | 항목 | 옵션 | 권장 | 현재 상태 |
|---|------|------|------|-----------|
| 1 | 토스트 팝업 포함 여부 | A(토스트 없음) / B(토스트 포함) | B | **확정: B**(사용자 명시 "토스트 팝업 + 툴팁") |
| 2 | 토스트 메시지 포맷 | 단일: `📰 뉴스 호재: <종목명>` / 복수2: `📰 뉴스 호재: A, B` / 복수3+: `📰 뉴스 호재: A 외 N종목` | 설계서 제안 포맷 그대로 | 대기(구현 세션 4 시작 전 확정) |
| 3 | 토스트 지속 시간 | 2500ms(기본 info) / 4000ms | 4000ms(사용자 인지 시간 확보) | 대기 |
| 4 | `news-hit` payload에 뉴스 제목 포함 여부 | 미포함 `{codes, names, scores}` / 포함 `{codes, names, scores, title}` | 포함(툴팁에 뉴스 제목 표시 시 필요) — 단, 백엔드 세션 2에서 `title` 추가 필요 | 대기(툴팁 내용=결정 6과 연동) |
| 5 | 초기 스냅샷(`buy-targets-update`)의 `news_boost` 필드 | D-1(유지, 초기 로드 시 캐시 반영) / D-2(제거, 초기 0.0 후 `news-hit`로만 갱신) | D-1(사용자 경험 저하 방지) | 대기(세션 1 시작 전 확정, D-1 전제로 태스크 작성) |
| 6 | 📰 아이콘 툴팁 내용 (신규 — 설계서에 없음, 사용자 "툴팁" 명시로 추가) | (a) 뉴스 제목 / (b) 종목명 + "뉴스 호재" 안내 / (c) 호재 키워드 | (a) 뉴스 제목(결정 4 = 포함 시) — 사용자가 호재 구체 내용을 인지하는 데 가장 유용 | 대기(결정 4와 함께 확정) |

**고정 전제**: 매수·매도 로직, 주문 단일 경로, 리스크 임계값, 브로커 연결, DB 스키마는 변경하지 않는다. `boost_score` 순위 반영 시점(체결 틱 시)은 기존 설계 의도 유지.

---

## 3. 테스트 계획

### 백엔드 공통
- 관련 단위 테스트: `test_engine_account_notify.py`, `test_sector_data_provider.py`, `test_pipeline_compute_nws_handler.py`.
- 전체 백엔드 테스트: `.venv/bin/python -m pytest backend/tests -q -W error::RuntimeWarning`.
- 런타임 기동: `.venv/bin/python -W error::RuntimeWarning main.py` — RuntimeWarning 0건, 잔존 프로세스 0건(0-1-3).
- 실전 주문·실전 계좌 연결은 실행하지 않는다.

### 프론트엔드 공통
- `cd frontend && npm run typecheck`.
- `cd frontend && npm run test`.
- `cd frontend && npm run build`.
- 브라우저 확인(세션 4 완료 후): 뉴스 호재 시 📰 컬럼 즉시 갱신 + 토스트 팝업 + 📰 아이콘 호버 툴팁.

### 핵심 합격 기준
- `buy-targets-delta`의 `changed`에 `news_boost` 미포함(세션 1).
- 뉴스 호재 시 `news-hit` 1회 브로드캐스트, 실패 시 뉴스 처리 정상 완료(세션 2, P25).
- `applyNewsHit`이 해당 종목의 `news_boost`만 patch, `applyBuyTargetsUpdate`는 `news_boost` 변경 무시(세션 3, P10).
- 📰 컬럼이 체결 틱 대기 없이 즉시 갱신 + 토스트·툴팁 정상 동작(세션 4, P21).
- 문서의 이벤트 수·payload가 코드와 일치(세션 5, P23).

---

## 4. 런타임 검증 방법

1. 테스트모드 설정 유지 상태에서 백엔드 기동.
2. 화면에서 매수 후보 📰 컬럼·순위 변동 확인.
3. 뉴스 호재(또는 모의 뉴스 이벤트) 발생 시: 📰 컬럼 즉시 갱신, 토스트 팝업, 📰 호버 시 툴팁 표시 확인.
4. 체결 틱 도착 후 `boost_score` 기반 순위가 자연 반영되는지 확인(세션 1~4 완료 후).
5. 검증 중 실전모드 전환이나 실제 주문은 수행하지 않는다.
6. 백엔드 변경 세션(1·2)은 테스트·런타임 기동·잔존 프로세스 0건까지 완료 후 다음 세션으로 넘김. 프론트 변경 세션(3·4)은 typecheck·test·build와 브라우저 확인까지 완료.

---

## 5. 실패·중단 기준과 인계 규칙

- `news_boost` 갱신 경로가 2개 共存 상태로 되돌아가지 않도록(세션 1·3) — P10 위반 시 즉시 중단.
- `_safe_broadcast` await 누락·`create_task` 무분별 분리·`except: pass`(금지 패턴) 발견 시 즉시 중단.
- 브로드캐스트·렌더링 실패가 엔진 루프·store listener 루프를 블로킹하면 P25 위반 → 중단.
- DB 스키마 변경 필요 시 `stocks.db`·`stocks.db-shm`·`stocks.db-wal` 백업 승인 전 진행 금지(안전 규칙 2).
- 코드 제거 시 참조 주석·docstring·테스트 파일까지 동기화(AGENTS.md 섹션2 코드 제거 규칙). `news_boost` 잔존 참조 전체 코드베이스 검색(backend + frontend + tests + docs).
- 각 세션 종료 후 변경 파일·검증 결과·미해결 문제·다음 세션 경로를 `HANDOVER.md`에 기록(인덱스 역할, 상세는 git 커밋 메시지). 다음 세션은 사용자 승인 후 시작(규칙 0).
- 5세션 전부 완료 후 최종 커밋에서 설계서(`news-boost-fix-design-v2.md`)·본 태스크 파일의 삭제 여부를 규칙 10에 따라 확인.

---

## 6. 바로잡음 로그

> 구현 중 태스크 기재 오류 발견 시 원인 + 수정 기록(규칙: 선택 섹션, 필요시만 갱신).
> (현재 없음)
