# 뉴스 가산점 로직 근본 설계 (v2 — 잘못된 로직 제거)

> **상태**: 설계 단계 (코드 수정 금지)
> **작성일**: 2026-07-28
> **이전 문서**: `docs/news-boost-fix-design.md` (v1 — 폐기, "1줄 추가 + 잘못된 로직 유지" 방식)
> **관련 규칙**: P7, P10(SSOT), P11, P16, P21, P22, P23, P24, P25
> **다단계 워크플로우**: 설계(본 파일) → 태스크 분할 → 구현 (세션당 1단계)

---

## 0. v1 폐기 사유

v1은 `_handle_nws_news()`에 `notify_buy_targets_update()` 1줄 추가하는 방식이었으나, **근본 해결이 아님**:

1. **잘못된 로직 유지**: `news_boost`가 `buy-targets-delta`의 `changed` 배열로 전달되는 구조를 그대로 둠. 이 구조는 `prev_buy_targets_map` 캐시 기반 delta 계산에 의존하므로, 뉴스 갱신이 캐시 상태에 영향 받음.
2. **업종 재계산 경로 공유**: `notify_buy_targets_update()`는 원래 `_flush_sector_recompute_impl()` 전용 설계. 뉴스가 이를 호출하면 캐시 일관성 시나리오가 복잡해지고, 향후 `_flush_sector_recompute_impl()` 변경 시 뉴스 경로에 예기치 않은 영향.
3. **P10(SSOT) 위반 잔존**: `news_boost`의 갱신 경로가 2개(뉴스 이벤트, 체결 틱 기반 재계산)共存. 단일 진실 소스 아님.

v2는 **잘못된 로직 자체를 제거**하고 `news_boost`를 뉴스 이벤트 전용 독립 상태로 재설계.

---

## 1. 잘못된 로직 정의 (제거 대상)

### 1.1 잘못된 로직 #1 — `_BUY_TARGET_CMP_KEYS`에 `news_boost` 포함

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" lines="362-366" />

```python
_BUY_TARGET_CMP_KEYS = (
    "rank", "boost_score", "guard_pass", "reason", "order_ratio",
    "program_net_buy", "high_5d", "avg_amt_5d", "news_boost",  # ← 잘못됨
)
```

**왜 잘못됐는가**:
- `news_boost`는 뉴스 이벤트로만 갱신되는 독립 상태. 업종 재계산(체결 틱 기반)과 무관해야 함.
- `cmp_keys`에 포함되면 `news_boost`가 변경될 때마다 `buy-targets-delta`의 `changed`로 전달됨.
- 하지만 `notify_buy_targets_update()`는 `_flush_sector_recompute_impl()`에서만 호출되므로, 뉴스가 발생해도 체결 틱이 들어와야 `changed`로 전달됨 → **체결 틱 의존성 발생**.

**"세션 8 결함 B 수정" 주석의 오류** (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" lines="378" />):
- 세션 8에서는 "news_boost 변경 시 화면 갱신 보장"을 위해 cmp_keys에 추가.
- 하지만 이는 **잘못된 해결** — news_boost를 업종 재계산 경로에 끼워넣어 갱신을 보장하려 했음.
- 올바른 해결은 news_boost를 **독립 WS 이벤트**로 전달하는 것.

### 1.2 잘못된 로직 #2 — `_build_target_entry`에서 `news_boost` 필드 생성

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/sector_data_provider.py" lines="174" />

```python
"news_boost": _nbc.get(s.code, 0.0),  # ← 잘못됨
```

**왜 잘못됐는가**:
- `news_boost`를 `buy_targets` 엔트리에 끼워넣어, `news_boost`가 `sector_summary_cache`의 파생 필드처럼 보이게 함.
- 실제로는 `news_boost_cache` (독립 상태)에서 읽으나, 전달 경로가 `buy-targets-update`/`buy-targets-delta`로 라우팅되어 **뉴스 갱신이 업종 재계산 경로에 종속**.
- P10(SSOT) 위반 — `news_boost`의 진실 소스는 `news_boost_cache`이나, 표현 경로가 `buy_targets` 엔트리로 이중화.

### 1.3 잘못된 로직 #3 — 프론트 same 비교에 `news_boost` 포함

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/hotStore.ts" lines="562" />

```typescript
&& p.news_boost === n.news_boost  // ← 잘못됨
```

**왜 잘못됐는가**:
- `applyBuyTargetsUpdate`의 same 비교에 `news_boost` 포함 → `buy-targets-update` 전체 리스트 수신 시 `news_boost` 변경 감지.
- 하지만 `news_boost`는 뉴스 이벤트로 갱신되어야 하는데, `buy-targets-update` 경로로도 갱신되므로 갱신 경로 2개 共存 (P10 위반).

### 1.4 잘못된 로직 #4 — `calculate_boost_score`에서 `news_boost_cache` 사용

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/domain/buy_filter.py" lines="57-62" />

```python
if boost_news_on:
    _nbc = news_boost_cache or {}
    news_score = _nbc.get(stock.code, 0.0)
    if news_score > 0:
        score += boost_news_score
```

**이것은 올바름 (유지)**:
- `boost_score` (순위 정렬용)는 업종 재계산 시점의 `news_boost_cache`를 반영해야 함.
- 뉴스 호재가 순위에 반영되는 시점은 다음 체결 틱 시 자연스럽게 (P11 이벤트 기반).
- 이것은 `boost_score`의 설계 의도(순위 정렬용 누적 가산점)에 부합.

→ **제거 대상 아님. 유지.**

---

## 2. 올바른 흐름 설계

### 2.1 설계 원칙

1. **`news_boost` (표시용)와 `boost_score` (순위용) 완전 분리**
   - `news_boost`: 뉴스 이벤트로만 갱신, 📰 컬럼 표시용, 즉시 반영
   - `boost_score`: 업종 재계산 시 `news_boost_cache` 기반 산출, 순위 정렬용, 체결 틱 시 반영
2. **`news_boost` 단일 전달 경로 = `news-hit` WS 이벤트** (신설)
3. **업종 재계산 경로에서 `news_boost` 제거** — `buy-targets-delta`의 `changed`에서 `news_boost` 제외
4. **P7 준수** — 뉴스 처리는 O(1) 캐시 갱신 + 1회 브로드캐스트
5. **P25 준수** — 브로드캐스트 실패가 뉴스 처리/엔진 루프 블로킹 금지

### 2.2 제안 흐름 (옵션 D — 독립 이벤트)

```
NWS 뉴스 수신 (호재 키워드 매칭 + 매수후보 종목)
  ↓
_handle_nws_news()
  ├─ news_boost_cache 갱신 (메모리만, O(1)) — 기존 유지
  ├─ logger.info("[연산] 뉴스 가산점 부여 — ...") — 기존 유지
  └─ ★ 신규: _safe_broadcast("news-hit", {codes, names, scores}) ★
      ↓
binding.ts → applyNewsHit({codes, names, scores}) — 신규 action
  ↓
hotStore.setState: buyTargets[i].news_boost = score (해당 종목만 patch)
  ↓
buy-target-columns.ts render → 📰 아이콘 즉시 표시
```

**업종 재계산 경로 (체결 틱 기반, 기존 유지)**:
```
REAL 체결 틱 → request_sector_recompute → _flush_sector_recompute_impl
  ├─ compute_sector_scores (증분)
  ├─ calculate_bonus_scores
  ├─ build_buy_targets_from_settings
  │   └─ calculate_boost_score → news_boost_cache 반영 → boost_score 갱신 (순위용)
  ├─ notify_desktop_sector_scores
  └─ notify_buy_targets_update()
      └─ buy-targets-delta (changed에서 news_boost 제외 — 잘못된 로직 #1 제거)
```

### 2.3 분리 구조도

```
┌─────────────────────────────────────────────────────────────────┐
│ news_boost_cache (단일 진실 소스, P10)                            │
│   writer: _handle_nws_news()                                     │
│   readers:                                                       │
│     1. get_news_boost_cache() → news-hit 이벤트 (표시용, 즉시)    │
│     2. calculate_boost_score() → boost_score (순위용, 체결 틱 시) │
└─────────────────────────────────────────────────────────────────┘
        │                                       │
        ▼                                       ▼
┌──────────────────────┐         ┌──────────────────────────────┐
│ news-hit WS 이벤트   │         │ buy-targets-delta WS 이벤트  │
│ (신설, 뉴스 즉시)     │         │ (기존, 체결 틱 시)            │
│ payload:             │         │ payload:                     │
│   {codes, names,     │         │   {added, removed, changed}  │
│    scores}           │         │   changed에서 news_boost 제외 │
└──────────────────────┘         └──────────────────────────────┘
        │                                       │
        ▼                                       ▼
┌──────────────────────┐         ┌──────────────────────────────┐
│ applyNewsHit()       │         │ applyBuyTargetsDelta()       │
│ (신규 action)         │         │ (기존)                       │
│ buyTargets[i]        │         │ buyTargets 전체 머지          │
│   .news_boost patch  │         │   (news_boost 제외)           │
└──────────────────────┘         └──────────────────────────────┘
```

### 2.4 초기 스냅샷 (buy-targets-update) 처리

초기 로드 시 `buy-targets-update` 전체 리스트 전송 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" lines="398-401" />). 이때 `news_boost` 필드 포함 여부:

**옵션 D-1 (권장)**: 초기 스냅샷에는 `news_boost` 포함 (초기 로드 시 캐시 상태 반영)
- `_build_target_entry`에서 `news_boost` 필드 유지 (초기 로드용)
- 단, `buy-targets-delta`의 `changed`에서는 `news_boost` 제외 (잘못된 로직 #1 제거)
- 프론트 same 비교에서 `news_boost` 제거 (잘못된 로직 #3 제거) — 초기 로드 후 뉴스 이벤트로만 갱신

**옵션 D-2**: 초기 스냅샷에서도 `news_boost` 제거, 초기에는 모두 0.0으로 시작 후 `news-hit`로 갱신
- 단점: 초기 로드 시 이미 캐시에 있는 뉴스 호재가 표시 안 됨 (사용자 경험 저하)

→ **D-1 채택**: 초기 스냅샷은 `news_boost` 포함, 이후 갱신은 `news-hit` 단일 경로.

---

## 3. 잘못된 로직 제거 상세

### 3.1 제거 #1 — `_BUY_TARGET_CMP_KEYS`에서 `news_boost` 제거

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" lines="362-366" />

**변경**:
```python
_BUY_TARGET_CMP_KEYS = (
    "rank", "boost_score", "guard_pass", "reason", "order_ratio",
    "program_net_buy", "high_5d", "avg_amt_5d",
    # news_boost 제거 — news-hit 이벤트로 단일 전달 (P10 SSOT)
)
```

**효과**:
- `buy-targets-delta`의 `changed` 판정에서 `news_boost` 제외
- 뉴스 호재 발생해도 체결 틱 시 `buy-targets-delta`에 `news_boost` 변경분 미포함
- `news_boost` 갱신은 `news-hit` 이벤트만 담당 (단일 경로, P10)

**주의**: `boost_score`는 여전히 cmp_keys에 포함 → 뉴스 호재로 인한 순위 변동은 다음 체결 틱 시 `boost_score` 변경으로 `changed` 전송됨 (올바른 동작).

### 3.2 제거 #2 — `_build_target_entry`의 `news_boost` 필드는 초기 스냅샷만 유지

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/sector_data_provider.py" lines="174" />

**유지** (초기 스냅샷용):
- `buy-targets-update` (초기 전체 리스트)에는 `news_boost` 포함
- 초기 로드 시 캐시 상태 반영

**delta에서 제외** (3.1과 연동):
- `buy-targets-delta`의 `added`/`changed` 항목은 `_BUY_TARGET_REALTIME_KEYS` 제거와 동일 패턴으로 `news_boost` 제거
- 신규 상수 `_BUY_TARGET_DELTA_EXCLUDE_KEYS = _BUY_TARGET_REALTIME_KEYS + ("news_boost",)` 도입 검토 (P24 중복 제거)

### 3.3 제거 #3 — 프론트 same 비교에서 `news_boost` 제거

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/hotStore.ts" lines="562" />

**변경**:
```typescript
// 제거: && p.news_boost === n.news_boost
```

**효과**:
- `applyBuyTargetsUpdate` 수신 시 `news_boost` 변경 무시 (다른 정적 필드 변경 없으면 setState 발화 안 함)
- `news_boost` 갱신은 `applyNewsHit()` action만 담당 (단일 경로, P10)

### 3.4 제거 #4 — `notify_buy_targets_update()`의 `news_boost` changed 전송 로직

3.1의 cmp_keys 제거로 자연 제거됨. 별도 코드 변경 불필요.

### 3.5 신규 — `news-hit` WS 이벤트 + `applyNewsHit()` action

#### 백엔드: `_handle_nws_news()`에 브로드캐스트 추가

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/pipelines/pipeline_compute_tick_handlers.py" lines="384-385" />

**추가**:
```python
if hit_codes:
    logger.info("[연산] 뉴스 가산점 부여 — 종목=%s 키워드 매칭: %s", hit_codes, title[:60])
    # news-hit 브로드캐스트 — news_boost 단일 전달 경로 (P10 SSOT)
    from backend.app.services.engine_account_notify import _safe_broadcast
    names = [engine_state.state.master_stocks_cache.get(c, {}).get("name", "") for c in hit_codes]
    await _safe_broadcast("news-hit", {
        "codes": hit_codes,
        "names": names,
        "scores": [score] * len(hit_codes),  # 동일 score (news_boost_score)
    })
```

**P25 준수**: `_safe_broadcast` 내부 예외 처리 — 브로드캐스트 실패 시 뉴스 처리 정상 완료.
**P7 준수**: O(len(hit_codes)) 브로드캐스트 1회.
**P23 네이밍**: `news-hit` (kebab-case, 기존 41개 이벤트 컨벤션 일치).

#### 프론트엔드: `binding.ts`에 핸들러 추가

<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/binding.ts" lines="244-249" /> (circuit-breaker-open 패턴 참조)

**추가**:
```typescript
pricesClient.onEvent('news-hit', (data) => {
  applyNewsHit(data as { codes: string[]; names: string[]; scores: number[] })
})
```

#### 프론트엔드: `hotStore.ts`에 `applyNewsHit()` action 추가

```typescript
export function applyNewsHit(data: { codes: string[]; names: string[]; scores: number[] }): void {
  const { codes, names, scores } = data
  hotStore.setState((state) => {
    const codeToScore = new Map<string, number>()
    codes.forEach((c, i) => codeToScore.set(normalizeStockCode(c), scores[i]))
    const buyTargets = state.buyTargets.map(t => {
      const score = codeToScore.get(normalizeStockCode(t.code))
      return score !== undefined ? { ...t, news_boost: score } : t
    })
    return { buyTargets }
  })
}
```

**P23 일관성**: `applyBuyTargetsDelta`/`applyBuyTargetsUpdate`와 동일한 `normalizeStockCode` + `hotStore.setState` 패턴.
**P25 준수**: `setState` 내부 updater 본문은 store.ts listener 루프에서 보호됨 (P25 조사 문서 A2-04-01).

#### 토스트 팝업 (옵션 — 사용자 결정)

`binding.ts`의 `news-hit` 핸들러에서 `showToast` 호출 가능:
```typescript
pricesClient.onEvent('news-hit', (data) => {
  applyNewsHit(data as ...)
  const d = data as { codes: string[]; names: string[]; scores: number[] }
  const label = d.names.length <= 2 ? d.names.join(', ') : `${d.names[0]} 외 ${d.names.length - 1}종목`
  showToast('info', `📰 뉴스 호재: ${label}`, 4000)
})
```

---

## 4. 영향 범위

### 4.1 백엔드 변경

| 파일 | 변경 | 위험도 | 규칙 |
|------|------|--------|------|
| `backend/app/services/engine_account_notify.py` | `_BUY_TARGET_CMP_KEYS`에서 `news_boost` 제거 + delta에서 `news_boost` 제거 로직 | 중간 | P10, P22 |
| `backend/app/pipelines/pipeline_compute_tick_handlers.py` | `_handle_nws_news()`에 `news-hit` 브로드캐스트 추가 | 낮음 | P25, P7 |
| `backend/app/services/sector_data_provider.py` | `_build_target_entry`의 `news_boost` 필드는 유지 (초기 스냅샷용) | 없음 | — |

### 4.2 프론트엔드 변경

| 파일 | 변경 | 위험도 | 규칙 |
|------|------|--------|------|
| `frontend/src/stores/hotStore.ts` | `applyBuyTargetsUpdate` same 비교에서 `news_boost` 제거 + `applyNewsHit()` action 추가 | 중간 | P10, P23, P25 |
| `frontend/src/binding.ts` | `news-hit` 이벤트 핸들러 추가 | 낮음 | P23 |
| `frontend/src/types/index.ts` | `NewsHitEvent` 타입 추가 (선택) | 낮음 | — |
| `frontend/src/pages/buy-target-columns.ts` | 변경 없음 | 없음 | — |
| `frontend/src/components/common/toast.ts` | 변경 없음 (재사용) | 없음 | — |

### 4.3 테스트 변경

| 파일 | 변경 |
|------|------|
| `backend/tests/test_engine_account_notify.py` | `test_cmp_keys_excludes_realtime_and_includes_news_boost` 수정 (news_boost 제거 반영) + `test_delta_changed_news_boost_triggers_change` 제거/수정 (더 이상 delta로 전송 안 함) |
| `backend/tests/test_pipeline_compute_nws_handler.py` | `news-hit` 브로드캐스트 검증 테스트 추가 |
| `frontend/tests/stores/hotStore.test.ts` | `news_boost 변경 시 setState 발화` 테스트 수정 (applyBuyTargetsUpdate에서는 발화 안 함, applyNewsHit에서 발화) + `applyNewsHit` 단위 테스트 추가 |

### 4.4 문서 변경

| 파일 | 변경 |
|------|------|
| `docs/coupling-ws-event-contract-index.md` | `news-hit` 이벤트 등록 (이벤트 41→42개) + `buy-targets-delta` payload에서 `news_boost` 제거 명시 |
| `docs/coupling-pipeline-boundary.md` | NWS 처리 경로 갱신 (독립 이벤트, 체결 틱 의존성 제거) |
| `docs/coupling-stock-code-normalization.md` | `applyNewsHit`의 code 정규화 추적 추가 |
| `ARCHITECTURE.md` | NWS 처리 흐름도 갱신 + `_BUY_TARGET_CMP_KEYS` 설명 갱신 |
| `AGENTS.md` | 변경 없음 |

### 4.5 영향 받지 않는 파일

- `backend/app/services/engine_sector_confirm.py` — 재계산 로직 변경 없음
- `backend/app/domain/buy_filter.py` — `calculate_boost_score` 유지 (boost_score 순위용)
- `backend/app/services/engine_radar.py` — `get_news_boost_cache()` 유지
- `backend/app/services/buy_order_executor.py` — `evaluate_buy_candidates()` 변경 없음
- `backend/data/stocks.db` — DB 스키마 변경 없음 (안전 규칙 1 준수)

---

## 5. 규칙 준수 체크리스트

### 백엔드 수정 시

- [ ] **P7 (블로킹 금지)**: 뉴스마다 전체 재계산 안 함 — `news-hit` 브로드캐스트 1회 (O(len(hit_codes)))
- [ ] **P10 (SSOT)**: `news_boost` 단일 전달 경로 = `news-hit` 이벤트. `buy-targets-delta`에서 제거. `news_boost_cache` 단일 진실 소스 유지.
- [ ] **P11 (폴링 금지)**: 이벤트 기반 (NWS 수신 → 즉시 브로드캐스트)
- [ ] **P16 (살아있는 경로)**: `news-hit` 브로드캐스트가 `_handle_nws_news` 실제 경로에 연결
- [ ] **P20 (폴백 금지)**: `names`에서 종목명 부재 시 빈 문자열 (폴백 아닌 명시적 값)
- [ ] **P22 (데이터 정합성)**: `news_boost` (표시용)와 `boost_score` (순위용) 분리 — 파생 관계 명확
- [ ] **P23 (네이밍)**: `news-hit` (kebab-case), `applyNewsHit` (camelCase) — 기존 컨벤션 일치
- [ ] **P25 (격리된 실패)**: `_safe_broadcast` 내부 예외 처리 — 브로드캐스트 실패 시 뉴스 처리 정상 완료

### 프론트엔드 수정 시

- [ ] **P10 (SSOT)**: `news_boost` 갱신은 `applyNewsHit()`만 담당. `applyBuyTargetsUpdate` same 비교에서 제거.
- [ ] **P21 (사용자 투명성)**: 📰 컬럼 즉시 갱신 — 체결 틱 대기 제거
- [ ] **P23 (일관성)**: `applyNewsHit`은 `applyBuyTargetsDelta`/`applyBuyTargetsUpdate`와 동일 패턴 (normalizeStockCode + setState)
- [ ] **P25 (격리된 실패)**: `applyNewsHit`의 setState updater는 store.ts listener 루프에서 보호됨

### 금지 패턴 5개

- [ ] `asyncio.run()` 사용 금지 — `await _safe_broadcast()` 직접 호출
- [ ] `create_task` 무분별 분리 금지 — `await` 직접 호출
- [ ] `except Exception: pass` 금지 — `_safe_broadcast` 내부 `logger.warning(..., exc_info=True)` 유지
- [ ] async 함수 `await` 누락 금지 — `_safe_broadcast`는 async, `await` 필수
- [ ] dead code 방치 금지 — `test_delta_changed_news_boost_triggers_change` 제거/수정 (더 이상 delta로 전송 안 함)

### 코드 제거 규칙 (AGENTS.md 섹션2)

- [ ] **참조 주석 정리**: "세션 8 결함 B 수정" 주석 제거 (잘못된 수정이었으므로)
- [ ] **불일치 금지**: `_BUY_TARGET_CMP_KEYS`에서 `news_boost` 제거 시 docstring/주석 동기화
- [ ] **검색 범위**: `news_boost` 잔존 참조 전체 코드베이스 검색 (backend + frontend + tests + docs)
- [ ] **테스트 파일 포함**: `test_engine_account_notify.py`/`hotStore.test.ts`의 news_boost 관련 테스트 동기화

---

## 6. 결정 필요 사항 (사용자 승인 전)

### 결정 1: 토스트 팝업 포함 여부

| 옵션 | 변경 범위 | 사용자 경험 |
|------|-----------|-------------|
| A (토스트 없음) | `news-hit` 이벤트 + `applyNewsHit`만 | 📰 컬럼 즉시 갱신만 |
| B (토스트 포함) | + `binding.ts`에서 `showToast` 호출 | 📰 컬럼 + 토스트 팝업 (P21 강화) |

### 결정 2: 토스트 메시지 포맷 (결정 1 = B 시)

- 단일 종목: `📰 뉴스 호재: 삼성전자`
- 복수 종목 (2개): `📰 뉴스 호재: 삼성전자, SK하이닉스`
- 복수 종목 (3개 이상): `📰 뉴스 호재: 삼성전자 외 2종목`

### 결정 3: 토스트 지속 시간 (결정 1 = B 시)

- 2500ms (기본 info)
- 4000ms (권장 — 사용자 인지 시간 확보)

### 결정 4: `news-hit` payload에 뉴스 제목 포함 여부

- 미포함: `{codes, names, scores}` — 토스트에 종목명만
- 포함: `{codes, names, scores, title}` — 토스트에 뉴스 제목 일부 표시 가능

### 결정 5: 초기 스냅샷(buy-targets-update)의 `news_boost` 필드

- D-1 (권장): 유지 — 초기 로드 시 캐시 상태 반영
- D-2: 제거 — 초기에는 모두 0.0, `news-hit`로만 갱신 (초기 로드 시 호재 미표시 단점)

---

## 7. 다음 단계 (사용자 승인 후)

1. **태스크 분할 세션**: 본 설계 기반 구현 태스크 분할 (세션당 1단계 원칙)
   - 태스크 1: 백엔드 — `_BUY_TARGET_CMP_KEYS`에서 `news_boost` 제거 + delta에서 제거 + 테스트 수정
   - 태스크 2: 백엔드 — `_handle_nws_news()`에 `news-hit` 브로드캐스트 추가 + 테스트
   - 태스크 3: 프론트엔드 — `applyNewsHit()` action + `binding.ts` 핸들러 + same 비교 제거 + 테스트
   - 태스크 4 (결정 1=B 시): 토스트 팝업 연결
   - 태스크 5: 문서 갱신 (`coupling-ws-event-contract-index.md` 등)
2. **구현 세션**: 태스크별 세션 진행 (세션당 1단계)
3. **검증**: `.venv/bin/python -m pytest backend/tests -q` + `.venv/bin/python -W error::RuntimeWarning main.py` + `cd frontend && npm run typecheck` + `cd frontend && npm run test`

---

## 8. 참조

- 현재 NWS 핸들러: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/pipelines/pipeline_compute_tick_handlers.py" />
- 매수후보 브로드캐스트: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py" />
- 매수후보 엔트리 생성: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/sector_data_provider.py" />
- 가산점 계산: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/domain/buy_filter.py" />
- 프론트엔드 store: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/hotStore.ts" />
- 프론트엔드 binding: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/binding.ts" />
- 토스트 컴포넌트: <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/components/common/toast.ts" />
- v1 설계(폐기): <ref_file file="/Users/sungjk0706/Desktop/SectorFlow/docs/news-boost-fix-design.md" />
