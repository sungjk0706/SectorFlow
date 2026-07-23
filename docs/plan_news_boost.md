# 태스크 파일: 실시간 뉴스(NWS) 매수 가산점 구현

> **상태**: 3세션 구현 완료 (4~7세션 대기)
> **작성일**: 2026-07-24 (2세션) / 3세션 구현 2026-07-24
> **설계서**: `docs/architecture_news_boost_design.md`
> **다단계 워크플로우**: 1세션(설계) ✅ → 2세션(사전조사+태스크) ✅ → 3세션(백엔드 NWS 인프라) ✅ → 4~7세션(구현 대기)
> **관련 원칙**: P4 · P7 · P10 · P11 · P13 · P15 · P16 · P20 · P21 · P22 · P23 · P24 · P25

---

## 0. 사전조사 결과 요약 (2세션)

### 0.1 의존성 (규칙 0-2 항목1)

**백엔드 10파일 + 프론트엔드 4파일 + 신규 1파일 + 테스트 1파일**

| 파일 | 변경점 | 기준 라인 |
|---|---|---|
| `backend/app/core/ls_connector.py` | `_TR_KOR` NWS 추가 / `_convert_ls_to_internal()` NWS 케이스 / `_recv_loop()` JIF 우회 조건 확장 / `subscribe_news()` 메서드 / `connect()` 구독 호출 / 재연결 루프 재구독 | 24, 298, 134, 651, 384, 741 |
| `backend/app/pipelines/pipeline_compute_tick_handlers.py` | `_handle_real_nws_tick()` 핸들러 추가 | 336 이후 |
| `backend/app/pipelines/pipeline_compute.py` | import + 디스패치 분기 | 33, 506 |
| `backend/app/services/engine_state.py` | `news_boost_cache` + `news_keywords_cache` + `news_boost_score` + `news_boost_ttl_sec` 필드 | 68 이후 |
| `backend/app/services/engine_radar.py` | `get_news_boost_cache()` getter | 36 이후 |
| `backend/app/domain/buy_filter.py` | `calculate_boost_score()` 4번째 가산점 / `create_buy_targets()` 파라미터 / `build_buy_targets_from_settings()` 전달 | 51, 110, 264/277/284 |
| `backend/app/services/sector_data_provider.py` | 매수후보 딕셔너리 `news_boost` 필드 | 153 이후 |
| `backend/app/core/engine_settings.py` | `_build_boost_settings()` NWS 설정 + 반환 dict | 249, 257 |
| `backend/app/core/settings_defaults.py` | `DEFAULT_USER_SETTINGS` NWS 기본값 4개 | 48 이후 |
| `backend/app/core/settings_store.py` | `_validate_numeric_fields()` NWS 필드 검증 | 321 |
| `frontend/src/types/index.ts` | `AppSettings` 4개 키 / `SectorStock` `news_boost` 필드 | 196, 57 |
| `frontend/src/pages/buy-settings.ts` | 모듈 상태 3개 / `syncBoost()` 뉴스 동기화 / `buildBoostSection()` 4번째 행 | 52, 106, 224 |
| `frontend/src/pages/buy-target.ts` | COLUMNS 📰뉴스 컬럼 (5일고가 앞) | 100 앞 |
| `frontend/src/pages/general-settings.ts` | `renderAutoTradeTab()` "화면 표시" 이후 키워드 섹션 + TTL | 691 이후 |
| `frontend/src/components/common/tag-chip.ts` | **신규** 태그 칩 입력 컴포넌트 | 신규 파일 |
| `backend/tests/test_buy_filter.py` | news 가산점 케이스 | 기존 파일 |

### 0.2 영향 범위 (규칙 0-2 항목2)
- 백엔드 10파일 + 프론트엔드 4파일 + 신규 1파일 + 테스트 1파일
- DB 스키마 변경 **없음** (설정 키만 `integrated_system_settings` 테이블에 증분 추가)
- 거래 로직(`execute_buy`/`execute_sell`) 변경 **없음** (P15 부합 — 가산점은 매수 점수에만 가산)

### 0.3 아키텍처 원칙 부합 (규칙 0-2 항목3)
P4 ✅ P7 ✅ P10 ✅ P11 ✅ P13 ✅ P15 ✅ P16 ✅ P20 ✅ P21 ✅ P22 ✅ P23 ✅ P24 ✅ P25 ✅
(상세 검토 내용은 설계서 섹션 5 참조)

### 0.4 기존 공통 자산 확인 (규칙 0-2 항목4)
**재사용**:
- `subscribe_jif()` / `subscribe_index()` 구독 패턴 (`ls_connector.py:606-650`)
- `get_program_net_buy_cache()` getter 패턴 (`engine_radar.py:33-35`)
- `calculate_boost_score()` 3개 가산점 패턴 (`buy_filter.py:8-53`)
- `_build_boost_settings()` 설정 빌드 패턴 (`engine_settings.py:235-258`)
- `createToggleLabelControlsRow` / `createNumInput` / `sectionTitle` / `createDescText` / `setDisabled` (프론트엔드 공통)
- `COLOR.up` / `FONT_SIZE.body` / `FONT_WEIGHT.bold` (표준 색상/폰트)

**신규 생성**: 태그 칩 입력 컴포넌트 (`components/common/tag-chip.ts`) — 기존에 chip/tag-input 컴포넌트 없음

---

## 1. 단계 분할 (세션당 1단계, 규칙 0-1)

### 3세션: 백엔드 NWS 인프라 ✅

**목표**: NWS 메시지 수신 → `news_boost_cache` 갱신까지의 경로 구축

> **바로잡음 (3세션 구현 중 발견)**: 태스크 작성 시 NWS 디스패치 위치를 `pipeline_compute.py`로 잘못 기재.
> NWS는 JIF와 동일하게 tick_queue를 우회하여 `engine_ws_dispatch.py` → `handle_ws_data()` 경로로 처리됨.
> `pipeline_compute.py`에 분기를 넣으면 도달하지 않는 죽은 코드(P16 위반)가 됨.
> 설계서 섹션 3.7.1이 이미 "디스패치 위치 확인 필요"로 명시했으나 태스크 작성 시 확인 누락.
> 수정: `pipeline_compute.py` 제외, `engine_ws.py` + `engine_ws_dispatch.py` 추가 (6파일).

**수정 파일 (6파일)**:
1. `backend/app/core/ls_connector.py`
   - `_TR_KOR`에 `"NWS": "실시간뉴스"` 추가
   - `_convert_ls_to_internal()`에 `elif tr_cd == "NWS":` 블록 추가 (title, code 추출, title 빈값 스킵)
   - `_recv_loop()` JIF 우회 조건을 `if internal_msg.get("trnm") in ("JIF", "NWS"):`로 수정
   - `subscribe_news()` / `unsubscribe_news()` 메서드 추가 (JIF 패턴, tr_key="NWS001")
   - `connect()` 내 `subscribe_news()` 호출 추가 (JIF 구독 직후, try/except + logger.warning)
   - 재연결 루프에 `subscribe_news()` 재구독 추가 (JIF 재구독 직후)

2. `backend/app/pipelines/pipeline_compute_tick_handlers.py`
   - `_handle_nws_news(item)` 핸들러 추가 (설계서 기준 함수명 — NWS는 values 구조가 아님)
     - title/code 추출, code 빈값 스킵 + `logger.debug()` (P20)
     - `engine_state.state.news_keywords_cache` 메모리 조회 (P13)
     - 키워드 매칭 (title에 키워드 포함 여부)
     - code 파싱 (복수 종목코드, 공백/쉼표 구분, 최대 240자)
     - `master_stocks_cache` O(1) 조회로 매수후보 내 종목 필터 (P7)
     - `news_boost_cache` 갱신 (code: (score, timestamp)) — 5분 TTL
     - `logger.info()`로 종목+제목 로깅 (P21)
     - try/except + `logger.error(exc_info=True)` (P25, P20)

3. `backend/app/services/engine_ws.py` (태스크에서 누락됨 — 바로잛음)
   - `_broker_message_handler()` trnm 필터에 `"NWS"` 추가 (JIF와 동일 경로)

4. `backend/app/services/engine_ws_dispatch.py` (태스크에서 누락됨 — 바로잃음)
   - `handle_ws_data()`에 `elif trnm == "NWS":` 분기 추가 → `_handle_nws_news(data)` 호출

5. `backend/app/services/engine_state.py`
   - 신규 필드 4개 추가
     - `news_boost_cache: dict[str, tuple[float, float]]` (score, timestamp_monotonic)
     - `news_keywords_cache: list[str]`
     - `news_boost_score: float`
     - `news_boost_ttl_sec: int`

6. `backend/app/services/engine_radar.py`
   - `get_news_boost_cache()` getter 추가
     - 만료 항목 lazy 제거 (monotonic 시간 비교)
     - `engine_state.state.news_boost_ttl_sec` 참조 (기본 300)
     - 만료된 항목 del 후 유효 항목만 반환

**검증**: py_compile ✅ + ruff ✅ + mypy (신규 에러 없음) ✅ + 런타임 기동 정상 (157ms, RuntimeWarning 없음) ✅ + 잔존 프로세스 0건 ✅ + 기존 테스트 2834개 통과 ✅ + NWS 핸들러 기능 테스트 6개 통과 ✅

---

### 4세션: 백엔드 가산점 로직 + 설정

**목표**: `news_boost_cache` → 매수 가산점 반영 + 설정 기본값/검증/동기화

**수정 파일 (6파일)**:
1. `backend/app/domain/buy_filter.py`
   - 라인 51 이후: `calculate_boost_score()`에 4번째 가산점 로직 추가
     - `if boost_news_on: news_score = news_boost_cache.get(stock.code, 0.0); if news_score > 0: score += boost_news_score`
   - 라인 110 이후: `create_buy_targets()` 시그니처에 `news_boost_cache`, `boost_news_on`, `boost_news_score` 파라미터 추가
   - 라인 264: `build_buy_targets_from_settings()` import에 `get_news_boost_cache` 추가
   - 라인 277: `news_boost_cache=get_news_boost_cache()` 전달 추가
   - 라인 284 이후: `boost_news_on`, `boost_news_score` 설정 파라미터 전달 추가

2. `backend/app/services/sector_data_provider.py`
   - 라인 153 이후: 매수후보 딕셔너리에 `"news_boost": cache_entry.get("news_boost")` 추가
   - **주의**: `news_boost`는 `master_stocks_cache`가 아닌 `news_boost_cache`에서 조회 — `_build_target_entry()` 내에서 `get_news_boost_cache()` 호출 후 O(1) 조회

3. `backend/app/core/engine_settings.py`
   - 라인 249 이후: `_build_boost_settings()`에 NWS 설정 로직 추가 (boost_news_score, news_boost_ttl_sec, news_keywords 파싱)
   - 라인 257 이후: 반환 dict에 `boost_news_on`, `boost_news_score`, `news_boost_ttl_sec`, `news_keywords` 키 추가

4. `backend/app/core/settings_defaults.py`
   - 라인 48 이후: NWS 기본값 4개 추가
     - `"boost_news_on": False`
     - `"boost_news_score": 1.0`
     - `"news_boost_ttl_sec": 300`
     - `"news_keywords": "수주,최대실적,특허,공급계약,무상증자,세계최초,MOU,FDA승인,독점공급,대규모수주"`

5. `backend/app/core/settings_store.py`
   - 라인 321 이후: `_validate_numeric_fields()`에 NWS 필드 검증 추가
     - `boost_news_score`: 0~100 범위
     - `news_boost_ttl_sec`: 0~3600 범위
     - `news_keywords`: 2000자 이하

6. `backend/app/services/engine_state.py` (설정 동기화)
   - 설정 로드 시점 (`backend/app/web/app.py` 라인 88-95 `build_engine_settings_dict()` 호출 후)에 `news_keywords_cache`, `news_boost_score`, `news_boost_ttl_sec`를 `engine_state.state`에 동기화
   - **주의**: 기존 `integrated_system_settings_cache` 갱신 로직과 동일 위치에서 갱신

**검증**: py_compile + ruff + typecheck + 런타임 기동 + 테스트 (기존 69개 통과 유지)

---

### 5세션: 프론트엔드 매수설정 + 매수후보 테이블

**목표**: 매수설정 가산점 토글/점수 UI + 매수후보 📰뉴스 컬럼

**수정 파일 (3파일)**:
1. `frontend/src/types/index.ts`
   - 라인 196 이후: `AppSettings`에 4개 키 추가
     - `boost_news_on: boolean`
     - `boost_news_score: number`
     - `news_boost_ttl_sec: number`
     - `news_keywords: string`
   - 라인 57 이후: `SectorStock`에 `news_boost?: number` 필드 추가

2. `frontend/src/pages/buy-settings.ts`
   - 라인 52 이후: 모듈 상태 3개 추가 (`boostNewsToggle`, `boostNewsScoreInput`, `boostNewsControls`)
   - 라인 106 이후: `syncBoost()`에 뉴스 동기화 추가 (기존 3개 패턴 동일)
   - 라인 224 이후: `buildBoostSection()`에 4번째 가산점 행 추가 (기존 3개와 동일 패턴: `createNumInput` + `createToggleLabelControlsRow`)
   - unmount()에 뉴스 참조 null 처리 추가

3. `frontend/src/pages/buy-target.ts`
   - 라인 100 앞 (5일고가 컬럼 앞): 📰뉴스 컬럼 추가
     - `key: 'news_boost', label: '📰뉴스', align: 'center', type: 'news', maxWidth: 70`
     - render: `news_boost > 0` 시 📰 이모지 + `COLOR.up` + tooltip 점수 표시, 미부여 시 빈칸

**검증**: typecheck + 빌드 + 브라우저 확인 (매수설정 4번째 가산점 행, 매수후보 📰뉴스 컬럼)

---

### 6세션: 프론트엔드 일반설정 키워드 칩 + TTL

**목표**: 일반설정 자동매매 탭에 호재 키워드 편집 섹션 + TTL 입력

**수정 파일 (2파일)**:
1. `frontend/src/components/common/tag-chip.ts` (신규)
   - 태그 칩 입력 컴포넌트: 입력 필드 + 추가 버튼 + 칩 나열(× 삭제)
   - API: `createTagChip({ initialTags: string[], onChange: (tags: string[]) => void }): { el: HTMLElement, setTags: (tags: string[]) => void }`
   - 칩 스타일: `COLOR.up` 테두리/배경 (호재 직관적 표현, P23)
   - 입력: Enter 또는 추가 버튼 시 신규 칩 추가, × 클릭 시 삭제
   - 중복 키워드 방지

2. `frontend/src/pages/general-settings.ts`
   - import에 `createTagChip` 추가
   - 모듈 상태에 `newsKeywordsTagChip`, `newsTtlInput` 추가
   - `renderAutoTradeTab()` 라인 691 이후에 신규 섹션 추가:
     - `sectionTitle('실시간 뉴스 설정')`
     - `createDescText('뉴스 제목에 포함된 호재 키워드 감지 시 매수 가산점 부여. 키워드는 쉼표로 구분하여 입력.')`
     - `buildNewsKeywordsRow()` — 키워드 칩 (vals.news_keywords 쉼표 문자열 ↔ 칩 배열 변환, 저장 시 쉼표 문자열로 재조합하여 `settingsMgr.saveSection`)
     - `buildNewsTtlRow()` — TTL 숫자 입력 (`createNumInput`, 라벨 "뉴스 가산점 유지 시간(초)", 기본 300)
   - `syncFromSettings()`에 뉴스 키워드/TTL 동기화 추가

**검증**: typecheck + 빌드 + 브라우저 확인 (일반설정 자동매매 탭 키워드 칩 편집 + TTL 입력)

---

### 7세션: 테스트 + 런타임 검증

**목표**: 단위 테스트 + 통합 런타임 검증

**수정 파일 (4파일)**:
1. `backend/tests/test_buy_filter.py`
   - `calculate_boost_score()` news 케이스 추가:
     - 가산점 부여 (news_boost_cache에 종목 있음, boost_news_on=True)
     - 가산점 미부여 (boost_news_on=False)
     - 빈 캐시 (news_boost_cache={})
     - TTL 만료 (만료된 항목은 getter에서 제거됨)

2. NWS 핸들러 단위 테스트 (신규 테스트 파일 또는 기존 파일)
   - 키워드 매칭 (title에 키워드 포함 시 캐시 갱신)
   - code 빈값 스킵 (logger.debug 호출 확인)
   - 복수 code 파싱 (공백/쉼표 구분)
   - 매수후보 외 종목 무시 (master_stocks_cache에 없는 code)

3. LS connector 테스트 (기존 파일 또는 신규)
   - `subscribe_news()` 모의 메시지
   - `_convert_ls_to_internal()` NWS 케이스 (title/code 추출, title 빈값 None 반환)

4. `sector_data_provider.py` 테스트
   - 매수후보 딕셔너리 `news_boost` 필드 포함 확인

**검증**:
- 백엔드: py_compile + ruff + typecheck + 테스트 전체 통과 + 런타임 기동
- 프론트엔드: typecheck + 빌드
- 런타임: LS 모의투자 WebSocket 연결 후 NWS 구독 ACK + 모의 뉴스 수신 → 가산점 부여 로그 확인 → 매수후보 테이블 📰 표시 확인
- 잔존 프로세스 0건

---

## 2. 세션별 검증 체크리스트 (공통)

각 세션 종료 시:
- [ ] 백엔드 수정: py_compile + ruff + typecheck + 런타임 기동 (137ms 이내) + 잔존 프로세스 0건
- [ ] 프론트엔드 수정: typecheck + 빌드 + 브라우저 확인
- [ ] 테스트: 기존 테스트 전체 통과 유지 + 신규 테스트 통과
- [ ] 커밋 + HANDOVER.md 갱신
- [ ] 설계서/태스크 파일은 7세션 완료 후 규칙 11에 따라 삭제

## 3. 아키텍처 원칙 체크리스트 (각 세션 수정 시)

- [ ] P1-P3 (async 일관성): 모든 I/O는 `async def`, 동기 함수 금지
- [ ] P4 (증권사명 침투 금지): NWS 로직은 `ls_connector.py`에 격리
- [ ] P5 (EventBus 금지): 직접 호출 체인 유지
- [ ] P7 (블로킹 금지): `master_stocks_cache` O(1) 조회, 만료 lazy 제거
- [ ] P11 (폴링 금지): WebSocket 이벤트 기반, `while+sleep` 없음
- [ ] P13 (설정 메모리 상주): 키워드/점수/TTL 메모리 상주, 틱 단계 DB 조회 금지
- [ ] P15 (단일 주문 경로): 가산점은 매수 점수에만 가산, 매도 로직 우회 없음
- [ ] P16 (살아있는 경로): 구독→변환→핸들러→캐시→가산점→매수후보 전 경로 연결
- [ ] P20 (폴백 금지): code 빈값 스킵 + debug 로깅, `except: pass` 금지
- [ ] P21 (사용자 투명성): 매수설정 토글/점수 + 일반설정 키워드 + 매수후보 📰뉴스 컬럼
- [ ] P22 (데이터 정합성): `news_boost_cache` 파생 데이터, TTL 만료 시 자동 제거
- [ ] P23 (일관성): JIF 패턴/PGM 캐시 패턴/기존 가산점 패턴 재사용, 용어 "뉴스"/"호재 키워드"
- [ ] P24 (단순성): 기존 패턴에 4번째 추가, 신규 추상화 최소화 (tag-chip만 신규)
- [ ] P25 (격리된 실패): NWS 실패 시 `logger.warning()` 후 계속, 키움-only 0점

## 4. 금지 패턴 5개 (수정 후 확인)

- [ ] `asyncio.run()` 사용 금지
- [ ] `create_task` 무분별 분리 금지 → `schedule_engine_task()` 사용
- [ ] `except Exception: pass` 금지 → `logger.warning(..., exc_info=True)`
- [ ] async 함수 `await` 누락 금지
- [ ] dead code 방치 금지
