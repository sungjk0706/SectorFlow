# Design Document — 이벤트 기반 델타 최적화

## Overview

SectorFlow의 실시간 데이터 파이프라인을 "이벤트 기반, 델타 전송, 증분 갱신" 원칙에 완전히 부합하도록 재설계한다. 백엔드 캐시 최적화(Phase 1), 델타 브로드캐스트(Phase 2), 비이벤트 패턴 제거(Phase 3), 프론트엔드 증분 DOM/상태 관리(Phase 4)로 구성된다.

---

## Phase 1: 백엔드 캐시 기반 증분 응답

### 1.1 종목 시세 목록 캐시 (Req 1)

**현재:** 매 호출마다 `_pending_stock_details` 전체를 dict 복사 → 필터 → 정렬 → 리스트 반환.

**설계:**
- 모듈 전역에 `_sector_stocks_cache: list | None = None` 유지
- 캐시 무효화 플래그: `_sector_stocks_dirty: bool = True`
- 무효화 트리거 (dirty = True):
  - 종목이 `_pending_stock_details`에 추가/제거될 때
  - `_sector_summary_cache` 참조가 교체될 때 (순위 변경)
  - `_filtered_sector_codes`가 변경될 때 (필터 변경)
- 무효화하지 않는 경우:
  - REAL 틱으로 가격/등락률/체결강도만 변경될 때 (이 값들은 `_pending_stock_details` 내부 dict에 이미 반영됨, 캐시 리스트의 각 항목이 같은 dict를 참조)
- 조회 시: dirty이면 재구축 후 캐시 저장, 아니면 캐시 직접 반환
- 캐시 항목은 `_pending_stock_details`의 dict 참조를 그대로 사용 (복사 없음)
- 정렬은 무효화 시에만 1회 수행

**참조 공유 방식:**
```
_pending_stock_details["005930"] = {"cur_price": 70000, ...}  # 원본
_sector_stocks_cache[0] = 위와 동일한 dict 참조  # 복사 아님
```
→ REAL 틱이 원본 dict의 cur_price를 변경하면, 캐시 리스트를 통해 조회해도 최신값이 보임.

### 1.2 매수후보 목록 캐시 (Req 2)

**현재:** 매 호출마다 `_sector_summary_cache.buy_targets` + `blocked_targets`를 순회하며 새 dict 리스트 생성.

**설계:**
- 모듈 전역에 `_buy_targets_snapshot_cache: list | None = None`
- 모듈 전역에 `_buy_targets_cache_ref: object | None = None` (마지막으로 캐시를 만든 시점의 `_sector_summary_cache` 참조)
- 조회 시: `_sector_summary_cache is _buy_targets_cache_ref`이면 캐시 반환
- `_sector_summary_cache`가 교체되면 다음 조회 시 자동 재구축

### 1.3 업종 점수 증분 재계산 (Req 3)

**현재:** `__ALL__` 플래그 시 `_full_recompute()` → `compute_full_sector_summary()` 호출 (56개 전체 업종).

**설계:**
- `__ALL__` 플래그가 있어도 `_sector_summary_cache`가 존재하면 증분 경로 사용
- 증분 경로: 모든 active 종목 코드를 dirty로 취급 → 해당 섹터만 재계산 → 기존 캐시와 병합
- `_sector_summary_cache`가 None(콜드 스타트)일 때만 `compute_full_sector_summary()` 1회 호출
- 이후 모든 재계산은 증분 경로로 처리

---

## Phase 2: 백엔드 델타 전용 브로드캐스트

### 2.1 필터 변경 시 델타 전송 (Req 4)

**현재:** 필터 변경 → `get_sector_stocks()` 전체 호출 → 전체 리스트 broadcast.

**설계:**
- 필터 변경 전 종목 코드 집합을 `_prev_sector_stock_codes: set[str]`에 보관
- 필터 변경 후 새 종목 코드 집합 계산
- `added = new_codes - prev_codes` → 추가된 종목의 상세 정보 포함
- `removed = prev_codes - new_codes` → 제거된 종목 코드만
- 이벤트: `"sector-stocks-delta"` → `{"added": [...], "removed": [...]}`
- 초기 연결(initial-snapshot) 시에만 전체 리스트 전송
- `_prev_sector_stock_codes` 갱신

### 2.2 매수후보 델타 전송 (Req 5)

**현재:** 매수후보 변경 → 전체 buy_targets 리스트 broadcast.

**설계:**
- `_prev_buy_targets_map: dict[str, dict]` — 이전 전송된 타겟의 코드→데이터 매핑
- 변경 감지: 코드 집합 비교 + 동일 코드의 필드값 비교
- 비교 키: `("rank", "sector_rank", "cur_price", "change_rate", "strength", "trade_amount", "boost_score", "guard_pass", "reason")`
- `added`: 새로 추가된 타겟 (전체 데이터)
- `removed`: 제거된 타겟 코드 리스트
- `changed`: 필드값이 변경된 타겟 (전체 데이터)
- 이벤트: `"buy-targets-delta"` → `{"added": [...], "removed": [...], "changed": [...]}`
- 초기 상태(캐시 없음) 시 전체 리스트 전송

### 2.3 체결 내역 단건 전송 (Req 6)

**현재:** 매수/매도 체결 → 전체 이력 리스트 broadcast.

**설계:**
- 매수 체결 시: `"buy-history-append"` → `{"trade": {새 거래 1건}}`
- 매도 체결 시: `"sell-history-append"` → `{"trade": {새 거래 1건}, "daily_summary": {해당 일자 요약}}`
- 전체 이력은 initial-snapshot에서만 전송
- 프론트엔드는 append 이벤트 수신 시 기존 배열 앞에 prepend

### 2.4 업종 점수 갱신 알림 최적화 (Req 7)

**현재:** `_full_recompute` 경로에서 `notify_desktop_sector_refresh()` → `notify_desktop_sector_tick()` → `get_sector_stocks()` 전체 복사.

**설계:**
- `_full_recompute` 완료 후에도 증분 경로와 동일하게 처리:
  - `notify_desktop_sector_scores()` (내부에서 이미 delta 비교)
  - dirty 종목에 대해 `notify_sector_tick_single()` 개별 호출
- `__ALL__` 플래그 시: `_pending_stock_details`의 모든 active 종목을 순회하며 `notify_sector_tick_single()` 호출
- `get_sector_stocks()` 전체 호출 경로 완전 제거

---

## Phase 3: 비이벤트 패턴 제거

### 3.1 지수 REST 폴링 이벤트 기반 전환 (Req 8)

**현재:** 09:00에 타이머로 폴링 중단, 15:30에 타이머로 폴링 재시작. 60초 재귀 타이머.

**설계:**
- 0J REAL 메시지 수신 시 플래그 설정: `_0j_real_receiving = True`
- 0J REAL 첫 수신 시: 지수 폴링 타이머 즉시 중단
- 09:00/15:30 고정 타이머 제거 (0J REAL 수신 여부로 자동 판단)
- 폴링 시작 조건: WS 구독 구간 내 + `_0j_real_receiving == False`
- 폴링 중단 조건: 0J REAL 메시지 1건 수신
- WS 구독 종료 시: 폴링도 함께 중단
- 엔진 기동 시: WS 구독 구간이면 폴링 시작 → 0J REAL 수신되면 자동 중단

---

## Phase 4: 프론트엔드 증분 DOM 및 상태 관리

### 4.1 수익 현황 테이블 증분 갱신 (Req 9)

**현재:** `showTable()` / `showDrilldown()`에서 `innerHTML = ''` 후 전체 재구축.

**설계:**
- 초기 마운트 시 DataTable 인스턴스 생성 (1회)
- 새 체결 도착 시: DataTable의 행 배열 앞에 새 행 prepend → `updateRows()` 호출
- 뷰 전환(테이블↔드릴다운): 두 컨테이너를 미리 생성, CSS `display` 토글
- `innerHTML = ''` 사용 금지 (초기 마운트 제외)

### 4.2 업종 커스텀 패널 증분 갱신 (Req 10)

**현재:** 패널 전환/갱신 시 `innerHTML = ''` 후 전체 재구축.

**설계:**
- 3개 패널(left, center, right) DOM을 마운트 시 1회 생성
- 패널 전환: CSS `display` 토글
- 목록 갱신: 이전 항목 집합과 비교 → 추가된 항목 DOM append, 제거된 항목 DOM remove
- 항목 내용 변경: 기존 DOM 요소의 textContent/value만 갱신

### 4.3 설정 페이지 탭 사전 렌더링 (Req 11)

**현재:** 탭 전환 시 `tabContent.innerHTML = ''` 후 선택된 탭 내용 재생성.

**설계:**
- 마운트 시 모든 탭 패널을 미리 생성하여 DOM에 추가 (display: none)
- 탭 클릭 시: 현재 탭 `display = 'none'`, 선택 탭 `display = ''`
- 설정값 변경 시: 해당 입력 요소의 value만 갱신 (DOM 재생성 없음)

### 4.4 계좌 보유종목 증분 배열 갱신 (Req 12)

**현재:** `applyAccountUpdate()`에서 `.map()` 전체 배열 재생성.

**설계:**
- `changed_positions` 수신 시:
  - 기존 배열에서 해당 `stk_cd` 인덱스 찾기
  - 있으면: `positions[idx] = newPosition` (splice 교체)
  - 없으면: `positions.push(newPosition)` (append)
- `removed_codes` 수신 시:
  - 해당 인덱스 역순으로 `positions.splice(idx, 1)`
- 변경 없으면: 배열 참조 그대로 유지 (setState 호출 안 함)

### 4.5 실시간 데이터 상태 관리 — 내부 컨테이너 변경 (Req 13)

**현재:** Zustand store + `Map<string, SectorStock>`. 매 틱마다 `new Map(sectorStocks)` 전체 복사.

**설계:**

**변경 방향:** 저장소(Zustand) 자체는 유지. 내부 컨테이너만 Map → 일반 객체로 변경하고, 갱신 방식을 "얕은 복사 + 해당 키만 교체"로 전환.

**새 구조:**
```typescript
// 기존: sectorStocks: Map<string, SectorStock>
// 변경: sectorStocks: Record<string, SectorStock>

// 업데이트 시:
setState({
  sectorStocks: { ...state.sectorStocks, [code]: updatedStock }
});
```

**마이그레이션 전략:**
1. 저장소 내부 컨테이너를 `Map<string, SectorStock>` → `Record<string, SectorStock>` (일반 객체)로 변경
2. 업데이트 로직: 기존 객체를 얕은 복사(`{ ...obj }`) 후 변경된 종목 코드의 값만 새 데이터로 교체
3. 읽기 방식: `.get(code)` → `obj[code]`, `Map.values()` → `Object.values(obj)` 로 일괄 변경
4. 페이지 단위로 순차 마이그레이션 (한 번에 전체 변경 금지)
5. 모든 페이지 전환 완료 후 Map 관련 잔여 코드 제거

**이점:**
- 매 틱: 얕은 복사 + 단일 키 교체 (O(1) 수준, 전체 Map 재생성 대비 극적 감소)
- 불변성 유지: 새 객체 참조 생성으로 Zustand 구독 정상 동작
- 메모리: 변경되지 않은 종목 데이터는 동일 참조 유지 (GC 부하 최소)
- 호환성: 저장소 구조 자체는 변경 없음, 내부 자료구조만 교체

---

## 이벤트 흐름도 (최종 상태)

```
키움 WS 서버
  → _recv_loop (JSON 파싱)
    → KiwoomConnector._on_ws_message (await 직접 호출)
      → _kiwoom_message_handler
        → handle_ws_data
          → _handle_real
            → notify_raw_real_data(item)  [프론트 즉시 전송]
            → _handle_real_01:
                ├─ _pending_stock_details[code] 갱신 (참조 교체)
                ├─ 보유종목이면: check_sell_conditions([해당 1종목])
                ├─ recompute_sector_for_code(code) → call_soon → flush:
                │   ├─ dirty 섹터만 증분 계산
                │   ├─ notify_desktop_sector_scores() [delta]
                │   ├─ notify_sector_tick_single(code) [개별]
                │   └─ notify_buy_targets_update() [delta]
                └─ (캐시 무효화 없음 — 가격만 변경)
            → _handle_real_0d:
                ├─ _orderbook_cache[code] 갱신
                └─ 매수후보이면: notify_orderbook_update(code, bid, ask)

프론트엔드:
  real-data → appStore setState({ sectorStocks: { ...prev, [code]: updated } }) → 구독 컴포넌트 갱신
  sector-scores → appStore.setState({sectorScores: delta})
  buy-targets-delta → appStore buyTargets 증분 갱신
  orderbook-update → appStore buyTargets[idx].order_ratio 교체
  buy-history-append → 기존 배열 앞에 prepend
  sell-history-append → 기존 배열 앞에 prepend
```

---

## 파일 변경 범위

| Phase | 백엔드 파일 | 프론트엔드 파일 |
|-------|------------|----------------|
| 1 | engine_service.py | — |
| 2 | engine_account_notify.py, engine_sector_confirm.py, trade_history.py | binding.ts, appStore.ts |
| 3 | daily_time_scheduler.py, engine_ws_dispatch.py | — |
| 4 | — | appStore.ts, profit-overview.ts, sector-custom.ts, general-settings.ts, binding.ts |
