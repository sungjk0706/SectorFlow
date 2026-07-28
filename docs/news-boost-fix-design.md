# 뉴스 가산점 로직 근본 설계 (v1 — 폐기)

> **상태**: **폐기** — "1줄 추가 + 잘못된 로직 유지" 방식으로 근본 해결 아님. v2로 대체.
> **폐기일**: 2026-07-28
> **대체 문서**: `docs/news-boost-fix-design-v2.md`
> **작성일**: 2026-07-28
> **관련 규칙**: P7(블로킹 금지), P10(SSOT), P11(폴링 금지), P21(사용자 투명성), P25(격리된 실패)
> **다단계 워크플로우**: 설계(본 파일) → 태스크 분할 → 구현 (세션당 1단계)

---

## 1. 현재 로직의 문제점

### 1.1 현재 흐름 (문제 시나리오)

```
NWS 뉴스 수신 (호재 키워드 매칭 + 매수후보 종목)
  ↓
_handle_nws_news()
  ├─ news_boost_cache 갱신 (메모리만, O(1))
  └─ logger.info("[연산] 뉴스 가산점 부여 — ...")
  ↓
★ 대기 — 다음 REAL 체결 틱까지 무반응 ★
  ↓
REAL 체결 틱 (005930 등 임의 종목)
  ↓
request_sector_recompute(code) — _dirty_codes 마킹
  ↓
_phase2_batch_recompute_loop (0.2초 배치)
  ↓
_flush_sector_recompute_impl()
  ├─ compute_sector_scores (증분, DB + CPU)
  ├─ calculate_bonus_scores (CPU)
  ├─ build_buy_targets_from_settings
  │   └─ calculate_boost_score → news_boost_cache 반영 → boost_score 갱신
  ├─ notify_desktop_sector_scores
  └─ notify_buy_targets_update()
      └─ _safe_broadcast("buy-targets-delta", {changed: [{..., news_boost: 1.0}]})
          ↓
binding.ts → applyBuyTargetsDelta() → hotStore.setState({buyTargets})
  ↓
buy-target-columns.ts render → 📰 아이콘 표시
```

### 1.2 문제점 4가지

| # | 문제 | 규칙 위반 | 상세 |
|---|------|-----------|------|
| 1 | **체결 틱 의존성** | P21 (사용자 투명성) | 뉴스 호재 발생 후 사용자가 📰를 보려면 임의 종목의 체결 틱이 들어와야 함. 장중 수 초~수십 초 지연, 체결 없는 종목은 무한 대기 |
| 2 | **불필요한 업종 재계산 의존** | P24 (단순성) | news_boost 필드(📰 표시용)는 `_build_target_entry`에서 `news_boost_cache`를 직접 읽음 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/sector_data_provider.py" lines="174" />). 굳이 `compute_sector_scores` + `calculate_bonus_scores` 전체 파이프라인을 거칠 필요 없음 |
| 3 | **가산점 반영 경로 분리** | P10 (SSOT) | `news_boost` 필드(표시용)는 `news_boost_cache` 직접 조회, `boost_score` 필드(순위용)는 `calculate_boost_score`에서 `news_boost_cache` 기반 재계산. 두 경로 모두 `news_boost_cache`에 의존하지만 갱신 시점이 다름 |
| 4 | **사용자 인지 지연** | P21 | 사용자가 뉴스를 보고 "왜 📰가 안 뜨지?" 의문 발생 가능. 백엔드 로그는 즉시 출력되나 UI는 지연 |

### 1.3 현재 로직이 올바른 부분 (유지해야 할 것)

- `news_boost_cache` 단일 소스 (P10) — `_handle_nws_news`만 writer, `get_news_boost_cache`만 reader
- 5분 TTL 만료 처리 (`get_news_boost_cache`에서 lazy 제거, <ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_radar.py" lines="26-39" />)
- 매수후보 종목만 가산점 부여 (`master_stocks_cache` O(1) 조회, P7)
- 호재 키워드 매칭 (메모리 상주 `news_keywords_cache`, P13)
- P25 격리된 실패 (`_handle_nws_news` 전체 try/except)

---

## 2. 올바른 흐름 설계

### 2.1 설계 원칙

1. **뉴스 → 가산점 → 즉시 갱신** (체결 틱 대기 제거)
2. **업종 재계산 의존성 제거** — news_boost 필드 갱신은 업종 재계산과 독립
3. **P7 준수** — 뉴스마다 전체 재계산(무거운 작업) 금지
4. **P25 준수** — 뉴스 갱신 실패가 엔진 루프/체결 처리 블로킹 금지

### 2.2 제안 흐름 (옵션 C — 하이브리드)

```
NWS 뉴스 수신 (호재 키워드 매칭 + 매수후보 종목)
  ↓
_handle_nws_news()
  ├─ news_boost_cache 갱신 (메모리만, O(1)) — 기존 유지
  ├─ logger.info("[연산] 뉴스 가산점 부여 — ...") — 기존 유지
  └─ ★ 신규: notify_buy_targets_update() 즉시 호출 ★
      └─ _safe_broadcast("buy-targets-delta", {changed: [{..., news_boost: 1.0}]})
          ↓
binding.ts → applyBuyTargetsDelta() → hotStore.setState({buyTargets})
  ↓
buy-target-columns.ts render → 📰 아이콘 즉시 표시
```

**핵심 분리**:
- `news_boost` 필드 (📰 컬럼 표시용) → **즉시 갱신** (news_boost_cache 직접 조회)
- `boost_score` 필드 (순위 정렬용) → **기존 경로 유지** (다음 체결 틱 시 `calculate_boost_score`에서 반영)
- `evaluate_buy_candidates()` (매수 시도) → **기존 경로 유지** (체결 틱 기반, P11 이벤트 기반)

### 2.3 왜 boost_score/rank까지 즉시 갱신하지 않는가?

`boost_score` 재계산은 `build_buy_targets_from_settings()` → `create_buy_targets()` → `calculate_boost_score()` 체인을 거쳐야 함. 이는:
- `compute_sector_scores` (DB 배치 조회 + CPU)
- `calculate_bonus_scores` (CPU)
- `get_held_codes` (DB 또는 메모리)
- 전체 종목 정렬 (O(n log n))

뉴스마다 이 전체를 실행하면 **P7(블로킹 금지) 위반**. 뉴스 호재는 빈도가 높을 수 있고 (장중 수십~수백 건), 매 건마다 전체 재계산은 성능 저하.

대신, **다음 체결 틱 시 자연스럽게 반영**되는 기존 경로를 유지. 이는:
- 뉴스 직후 매수 폭주 방지 (사용자 보호)
- P11 이벤트 기반 원칙 유지 (체결 틱이 매수 타이밍의 자연스러운 트리거)
- P7 준수 (뉴스 처리는 O(1) + 브로드캐스트 1회)

### 2.4 사용자 경험

| 시점 | 사용자 인지 |
|------|-------------|
| 뉴스 수신 즉시 | 📰 아이콘 토스트 팝업 + 매수후보 테이블 📰 컬럼 즉시 표시 |
| 다음 체결 틱 | 매수 순위 변동 (뉴스 가산점 반영된 boost_score 기준 재정렬) + 매수 시도 |

---

## 3. 업종 재계산 의존성 제거

### 3.1 현재 의존성

`notify_buy_targets_update()`는 `_flush_sector_recompute_impl()` 내부에서만 호출 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_sector_confirm.py" lines="184,249" />). 이는:
- `_flush_sector_recompute_impl()`이 `sector_summary_cache`를 갱신한 후 `notify_buy_targets_update()` 호출
- `notify_buy_targets_update()`는 `get_buy_targets_sector_stocks()` → `_build_target_entry()`에서 `sector_summary_cache` 기반으로 엔트리 생성

### 3.2 제거 방안

`notify_buy_targets_update()`를 `_handle_nws_news()`에서 직접 호출. 이때:
- `sector_summary_cache`는 기존 상태 유지 (뉴스만으로 업종 점수 변동 없음)
- `_build_target_entry()`는 `news_boost_cache`를 직접 읽으므로 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/sector_data_provider.py" lines="174" />), `news_boost_cache` 갱신만으로 `news_boost` 필드 즉시 반영
- `prev_buy_targets_map` 캐시 기반 delta 계산 — `news_boost` 필드만 변경된 항목이 `changed` 배열로 전송

### 3.3 주의점 — prev_buy_targets_map 캐시 일관성

`notify_buy_targets_update()`는 `prev_buy_targets_map`과 `cur_map`을 비교하여 delta 계산 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" lines="404-429" />).

**시나리오 검증**:
1. 체결 틱 → `_flush_sector_recompute_impl()` → `notify_buy_targets_update()` 호출 → `prev_buy_targets_map` 갱신 (news_boost=0.0)
2. 뉴스 수신 → `_handle_nws_news()` → `news_boost_cache` 갱신 → `notify_buy_targets_update()` 호출
   - `cur_map`은 `news_boost_cache`에서 news_boost=1.0 읽음
   - `prev_buy_targets_map`은 news_boost=0.0
   - `_BUY_TARGET_CMP_KEYS`에 `news_boost` 포함 → changed 감지 → `buy-targets-delta` 전송
   - `prev_buy_targets_map` 갱신 (news_boost=1.0)
3. 다음 체결 틱 → `_flush_sector_recompute_impl()` → `notify_buy_targets_update()` 호출
   - `cur_map`은 여전히 news_boost=1.0 (TTL 내)
   - `prev_buy_targets_map`도 news_boost=1.0
   - changed 없음 → 전송 생략 (정상)

**결론**: 캐시 일관성 유지. `notify_buy_targets_update()`는 호출 순서에 무관하게 `prev_buy_targets_map` 기반 delta 계산.

### 3.4 동시성 고려 (P14, P25)

`_handle_nws_news()`와 `_flush_sector_recompute_impl()`은 모두 단일 이벤트 루프에서 실행 (P14 멀티스레드 금지). 동시 실행 없음. 다만:
- `_handle_nws_news()`는 `engine_ws_dispatch.handle_ws_data()`에서 `await` 직접 호출
- `_flush_sector_recompute_impl()`은 `_phase2_batch_recompute_loop()`에서 `await` 호출
- 둘 다 동일 루프에서 순차 실행 → `prev_buy_targets_map` 갱신 경쟁 없음

---

## 4. 영향 범위

### 4.1 백엔드 변경 (최소)

| 파일 | 변경 | 위험도 | 규칙 |
|------|------|--------|------|
| `backend/app/pipelines/pipeline_compute_tick_handlers.py` | `_handle_nws_news()` 끝에 `notify_buy_targets_update()` 호출 추가 | 낮음 | P25 (try/except 내부) |

**변경 상세**:
- 384-385번 줄 `if hit_codes:` 블록 내에 `await notify_buy_targets_update()` 추가
- `notify_buy_targets_update`는 이미 `_safe_broadcast` 내부 예외 처리 포함 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" lines="92-98" />)
- `_handle_nws_news` 전체 try/except 유지 → 브로드캐스트 실패 시 뉴스 처리는 정상 완료 (P25)

### 4.2 프론트엔드 변경 (없음 — 기존 경로 재사용)

| 파일 | 변경 | 비고 |
|------|------|------|
| `frontend/src/binding.ts` | 변경 없음 | `buy-targets-delta` 핸들러(106-108번 줄) 그대로 작동 |
| `frontend/src/stores/hotStore.ts` | 변경 없음 | `applyBuyTargetsDelta()` 그대로 작동 |
| `frontend/src/pages/buy-target-columns.ts` | 변경 없음 | `news_boost` 필드 렌더 그대로 작동 |

→ **프론트엔드 변경 불필요**. 백엔드에서 `buy-targets-delta` 이벤트가 즉시 발생하면 프론트는 자동 갱신.

### 4.3 토스트 팝업 (별도 옵션 — 사용자 결정 필요)

뉴스 호재 발생 시 토스트 팝업("📰 뉴스 호재: 종목명")은 **별도 WS 이벤트(`news-hit`) 신설 시에만 가능**. 본 설계의 핵심(체결 틱 의존성 제거)과는 독립적.

| 옵션 | 설명 | 권장 |
|------|------|------|
| A | 토스트 없음 — 📰 컬럼 즉시 갱신만 | 최소 변경 |
| B | `news-hit` WS 이벤트 신설 + 토스트 | 사용자 경험 강화 (P21) |

**옵션 B 선택 시 추가 변경**:
- `backend/app/pipelines/pipeline_compute_tick_handlers.py`: `_handle_nws_news()`에서 `_safe_broadcast("news-hit", {codes, names, title})` 추가
- `frontend/src/binding.ts`: `news-hit` 이벤트 핸들러 추가 → `showToast('info', '📰 뉴스 호재: ...', 4000)`
- `frontend/src/components/common/toast.ts`: 변경 없음 (재사용)
- `docs/coupling-ws-event-contract-index.md`: `news-hit` 이벤트 등록

### 4.4 테스트 변경

| 파일 | 변경 |
|------|------|
| `backend/tests/test_pipeline_compute_nws_handler.py` | `notify_buy_targets_update()` 호출 검증 테스트 추가 (기존 9개 테스트 + 신규 1~2개) |
| `backend/tests/test_engine_account_notify.py` | 영향 없음 — `notify_buy_targets_update()` 자체 로직 변경 없음 |

### 4.5 문서 변경

| 파일 | 변경 |
|------|------|
| `docs/coupling-pipeline-boundary.md` | NWS 처리 경로 갱신 (체결 틱 의존성 제거 명시) |
| `docs/coupling-ws-event-contract-index.md` | 옵션 B 선택 시 `news-hit` 이벤트 추가 |
| `ARCHITECTURE.md` | NWS 처리 흐름도 갱신 (해당 섹션) |
| `AGENTS.md` | 변경 없음 (검증 명령어 동일) |

### 4.6 영향 받지 않는 파일

- `backend/app/services/engine_account_notify.py` — `notify_buy_targets_update()` 로직 변경 없음
- `backend/app/services/engine_sector_confirm.py` — 재계산 로직 변경 없음
- `backend/app/services/sector_data_provider.py` — `_build_target_entry()` 변경 없음
- `backend/app/domain/buy_filter.py` — `calculate_boost_score()` 변경 없음
- `backend/app/services/engine_radar.py` — `get_news_boost_cache()` 변경 없음
- `backend/app/services/buy_order_executor.py` — `evaluate_buy_candidates()` 변경 없음
- `backend/data/stocks.db` — DB 스키마 변경 없음 (안전 규칙 1 준수)

---

## 5. 규칙 준수 체크리스트

### 백엔드 수정 시

- [ ] **P7 (블로킹 금지)**: 뉴스마다 전체 재계산 안 함 — `notify_buy_targets_update()`만 호출 (O(매수후보 수) + 브로드캐스트 1회)
- [ ] **P10 (SSOT)**: `news_boost_cache` 단일 소스 유지 — `_handle_nws_news`만 writer
- [ ] **P11 (폴링 금지)**: `while + sleep` 폴링 도입 없음 — 이벤트 기반 (NWS 수신 → 즉시 갱신)
- [ ] **P16 (살아있는 경로)**: `notify_buy_targets_update()` 호출이 실제 실행 경로에 연결됨
- [ ] **P21 (사용자 투명성)**: 📰 컬럼 즉시 갱신으로 사용자 인지 지연 제거
- [ ] **P25 (격리된 실패)**: `_handle_nws_news` try/except 유지, `_safe_broadcast` 내부 예외 처리 — 브로드캐스트 실패 시 뉴스 처리 정상 완료

### 금지 패턴 5개

- [ ] `asyncio.run()` 사용 금지 — `await notify_buy_targets_update()` 직접 호출
- [ ] `create_task` 무분별 분리 금지 — `await` 직접 호출 (동일 루프 순차 실행)
- [ ] `except Exception: pass` 금지 — 기존 `logger.error(..., exc_info=True)` 유지
- [ ] async 함수 `await` 누락 금지 — `notify_buy_targets_update()`는 async, `await` 필수
- [ ] dead code 방치 금지 — 신규 코드는 실제 호출 경로에 연결

---

## 6. 결정 필요 사항 (사용자 승인 전)

### 결정 1: 토스트 팝업 포함 여부

| 옵션 | 변경 범위 | 사용자 경험 |
|------|-----------|-------------|
| A (토스트 없음) | 백엔드 1줄 추가 | 📰 컬럼 즉시 갱신만 |
| B (토스트 포함) | 백엔드 + 프론트엔드 | 📰 컬럼 + 토스트 팝업 |

### 결정 2: 토스트 메시지 포맷 (옵션 B 선택 시)

- 단일 종목: `📰 뉴스 호재: 삼성전자`
- 복수 종목 (2개): `📰 뉴스 호재: 삼성전자, SK하이닉스`
- 복수 종목 (3개 이상): `📰 뉴스 호재: 삼성전자 외 2종목`

### 결정 3: 토스트 지속 시간 (옵션 B 선택 시)

- 2500ms (기본 info)
- 4000ms (권장 — 사용자 인지 시간 확보)
- 사용자 설정 가능 (별도 설정 추가 — 범위 확장)

### 결정 4: `news-hit` payload에 뉴스 제목 포함 여부 (옵션 B 선택 시)

- 미포함: `{codes, names}` — 토스트에 종목명만
- 포함: `{codes, names, title}` — 토스트에 뉴스 제목 일부 표시 가능 (예: "📰 삼성전자 대규모 수주")

---

## 7. 다음 단계 (사용자 승인 후)

1. **태스크 분할 세션**: 본 설계 기반으로 구현 태스크 분할 (세션당 1단계 원칙)
2. **구현 세션 1**: 백엔드 `_handle_nws_news()`에 `notify_buy_targets_update()` 호출 추가 + 테스트
3. **구현 세션 2** (옵션 B 선택 시): `news-hit` WS 이벤트 신설 + 프론트엔드 토스트 핸들러 + 테스트
4. **검증**: `.venv/bin/python -m pytest backend/tests -q` + `.venv/bin/python -W error::RuntimeWarning main.py` + `cd frontend && npm run typecheck`

---

## 8. 참조

- 현재 NWS 핸들러: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/pipelines/pipeline_compute_tick_handlers.py" />
- 매수후보 브로드캐스트: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" />
- 업종 재계산 루프: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_sector_confirm.py" />
- 프론트엔드 delta 핸들러: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/hotStore.ts" />
- 토스트 컴포넌트: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/components/common/toast.ts" />
