# 구현 계획서: KRX/NXT 수신률 분리 집계 + 분리 배지 표시

> **상태**: 사전조사 완료 · 구현 계획 수립 완료 · **사용자 승인 대기**
> **작성일**: 2026-07-16
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 1. 배경 및 목적

### 1-1. 문제 상황
- 현재 수신률 집계는 `_received_codes: set[str]` 단일 누적 세트로 KRX/NXT 구분 없이 종목코드만 저장 (pipeline_compute.py:34)
- 틱 수신 시 FID 9081(KRX='1'/NXT='2') 확인 없이 `_received_codes.add(nk_px)` (pipeline_compute.py:581)
- 정규장(09:00~15:20)에서 KRX 단독 + NXT 중복상장 종목이 통합 집계되어 **KRX/NXT 개별 수신 상태를 알 수 없음**
- 진행 바의 "수신 N종목 / 미수신 N종목" 표시도 단일 객체 (`{received, total, pct}`) — 분리 불가 (sector-settings.ts:152~204)
- 업종별 종목 시세 테이블에는 이미 KRX/NXT/코스피/코스닥 종목수 분리 표시가 인라인으로 구현되어 있으나 공통 컴포넌트가 아님 (sector-stock.ts:399~481)

### 1-2. 목적
- **NXT 전용 시간대(08:00~08:50, 15:40~20:00)**: NXT 종목만 수신률 계산, KRX 배지 비활성
- **KRX+NXT 동시 운용 시간대(09:00~15:20)**: KRX/NXT 각각 분리 집계, 분리된 배지로 표시
- **진행 바**: KRX/NXT 분리 배지 + 시간대에 따라 활성/비활성 배경색 전환
- 사용자가 정규장에서 "KRX는 다 됐는데 NXT는 덜 됐다"를 한눈에 파악 가능 (P21)

### 1-3. P원칙 관점
- **P10(SSOT)**: `_received_codes` 단일 세트 → KRX/NXT 혼재. 분리 시 2세트 또는 태그 부여, 중복 관리 금지
- **P21(사용자 투명성)**: 정규장에서 KRX/NXT 구분 불가 → 위반. 분리 후 사용자가 양쪽 수신 상태 개별 확인 가능
- **P22(데이터 정합성)**: `is_nxt_only` 파생 플래그 준수. 분리 수신률도 `market_phase` 기반 파생 유지
- **P23(일관성)**: KRX/NXT 표시가 3곳(sector-stock/header/수신률)에서 각각 다른 패턴 → 공통 컴포넌트 추출로 통일

---

## 2. 사전조사 결과 (심화)

### 2-1. 기존 시간 체계 SSOT (재사용 대상 — P23 공통 자산)

**파일**: `backend/app/services/daily_time_scheduler.py`

이미 KRX/NXT 시간대 상수와 `calc_timebased_market_phase()` SSOT, `is_nxt_only_window()` 파생 함수가 구현되어 있음. **새 시간 상수를 만들지 말고 기존 `market_phase` 값을 활용** (P10 SSOT).

#### 시간대별 수신률 집계 정책
| 시간대 | krx 페이즈 | nxt 페이즈 | is_nxt_only | KRX 집계 | NXT 집계 | 비고 |
|---|---|---|---|---|---|---|
| 00:00~08:00 | 장개시전 | 장개시전 | False | 비활성 | 비활성 | WS 구독 구간 아님 |
| 08:00~08:50 | 장전 대기 | 프리마켓 | **True** | 비활성 | **활성** | NXT-only 구간 |
| 08:50~09:00 | 동시호가 접수 | 정규장 준비 | False | 비활성 | 비활성 | WS 구독은 활성, 체결 없음 |
| 09:00~15:20 | 정규장 | 메인마켓 | False | **활성** | **활성** | 양쪽 분리 집계 |
| 15:20~15:30 | 종가 동시호가 | 조기 마감 | False | 비활성 | 비활성 | 체결 없음 |
| 15:30~15:40 | 체결 정산 | 단일가 매매 | False | 비활성 | 비활성 | KRX 단독 종목 구독해지 시점 |
| 15:40~18:00 | 장후 시간외 | 애프터마켓 | **True** | 비활성 | **활성** | NXT-only 구간 |
| 18:00~20:00 | 장 종료 | 애프터마켓 지속 | **True** | 비활성 | **활성** | NXT-only 구간 |
| 20:00~24:00 | 장마감 | 장마감 | False | 비활성 | 비활성 | WS 구독 종료 |

#### 재사용 가능 함수 (이미 존재)
- `is_nxt_only_window()` (daily_time_scheduler.py:181) — KRX 비활성 + NXT 활성
- `is_nxt_premarket_window()` (daily_time_scheduler.py:46) — NXT "프리마켓"
- `is_nxt_aftermarket_window()` (daily_time_scheduler.py:61) — NXT "애프터마켓"/"애프터마켓 지속"
- `KRX_INACTIVE_PHASES` / `NXT_ACTIVE_PHASES` (daily_time_scheduler.py:169~178) — 상수 세트
- `parse_fid9081_exchange()` (engine_ws_parsing.py:181) — FID 9081 거래소 구분 ('1'=KRX, '2'=NXT)
- `is_nxt_enabled(stk_cd)` (engine_symbol_utils.py:11) — 종목의 NXT 중복상장 여부

### 2-2. 현재 수신률 집계 로직 (pipeline_compute.py)

#### 데이터 흐름
```
[틱 수신]
  engine_ws_dispatch.handle_ws_data → REAL 0B/01
    → pipeline_compute._process_tick_0b_01 (line 519~)
      → _received_codes.add(nk_px) (line 581)  ← KRX/NXT 구분 없이 추가
      → _receive_rate_dirty = True (line 582)

[수신률 계산]
  _calculate_receive_rate() (line 104~138)
    → get_sector_summary_inputs() → all_codes (NXT-only 구간만 필터링됨)
    → all_codes 순회하며 _received_codes 또는 캐시 필드 유무로 카운트
    → _current_receive_rate = {received, total, pct}  ← 단일 객체

[전송]
  _send_receive_rate() (line 73~82) → WS "receive-rate" 이벤트 {pct, received, total}
  engine_account_notify.py:287~288 → sector-scores 이벤트 status.receive_rate에도 포함

[프론트엔드]
  binding.ts:274~277 → uiStore.receiveRate = {received, total, pct}
  sector-settings.ts:352~369 → receiveProgressBar.setValue(pct) + _fillReceiveCount(rate)
```

#### 연쇄 영향 파일 (KRX/NXT 분리 시 수정 필요)
| 파일 | 함수/변수 | 영향 |
|------|-----------|------|
| `backend/app/pipelines/pipeline_compute.py` | `_received_codes`, `_current_receive_rate`, `_calculate_receive_rate`, `_send_receive_rate`, `get_current_receive_rate`, `_process_tick_0b_01` | 핵심 수정 대상 |
| `backend/app/services/engine_account_notify.py:287~288, 308, 319, 336` | `get_current_receive_rate()` 호출, `prev_receive_rate` 비교, `status.receive_rate` 전송 | 전송 구조 변경 연동 |
| `backend/app/services/market_close_pipeline.py:965~967, 1389~1391` | `_calculate_receive_rate()`, `_send_receive_rate()` 호출 | 확정 데이터 갱신 시 분리 집계 연동 |
| `backend/app/services/sector_data_provider.py:16~51` | `get_sector_summary_inputs()` — all_codes 반환 | 정규장에서도 KRX/NXT 분리된 all_codes 반환 필요 |
| `backend/tests/test_pipeline_compute.py` | `_current_receive_rate`, `_received_codes`, `_calculate_receive_rate` 등 63개 참조 | 테스트 전면 수정 |

### 2-3. 임계값 게이트 정책 (_sector_threshold_passed)

#### 현재 구조
- `_sector_threshold_passed: bool` (pipeline_compute.py:41) — 단일 플래그
- Phase 1 루프(pipeline_compute.py:713~746)에서 단일 수신률 기준 임계값 통과 판정
- 통과 시 `mark_sector_threshold_passed()` → `is_sector_threshold_passed()`가 True 반환
- `is_sector_threshold_passed()` 사용처:
  - `engine_account_notify.py:273~274` — sector-scores 전송 차단
  - `ws.py:108~109` — WS 초기 스냅샷 전송 차단

#### 분리 시 정책 결정 필요사항 (사용자 승인 필수 — 핵심 로직 변경, AGENTS.md 규칙 0-4/0-5)

**옵션 A: 양쪽 모두 통과해야 게이트 해제 (AND 정책)**
- 장점: 보수적. KRX/NXT 모두 충분한 데이터 확보 후 업종순위 계산 시작
- 단점: NXT-only 구간(08:00~08:50)에서 KRX 종목이 수신될 리 없으므로 게이트가 영원히 해제되지 않음
- 보완: NXT-only 구간에서는 NXT 수신률만 기준 (시간대별 정책 분기)

**옵션 B: 하나라도 통과하면 게이트 해제 (OR 정책)**
- 장점: 빠른 시작. 어느 한쪽이라도 임계값 도달 시 업종순위 계산 시작
- 단점: KRX만 70% 도달해도 시작 → NXT 종목이 미수신 상태로 업종 점수에 포함될 위험
- 보완: 업종 점수 계산 자체는 미수신 종목 제외 로직이 이미 있음 (sector_calculator.py:85)

**옵션 C: 시간대별 분기 정책 (추천)**
- NXT-only 구간(08:00~08:50, 15:40~20:00): NXT 수신률만 기준
- 정규장(09:00~15:20): KRX/NXT 양쪽 모두 임계값 도달 시 게이트 해제 (AND)
- 비-WS 구간: 기존대로 항상 True (확정 데이터 기반)
- 장점: 시간대 의미에 정확히 부합. P21(투명성) — 사용자가 "왜 업종순위가 안 시작하지?" 의문 없음
- 단점: 정규장에서 KRX/NXT 중 한쪽이 늦게 도달하면 게이트 해제 지연 → 사용자에게 "대기 중" 표시 필요

**추천: 옵션 C (시간대별 분기)** — 기존 `is_nxt_only_window()` 재사용으로 P10/P24 준수

### 2-4. 프론트엔드 공통 컴포넌트 현황

#### 기존 컴포넌트 (재사용 검토)
| 컴포넌트 | 위치 | 사용처 | KRX/NXT 분리 지원 |
|----------|------|--------|-------------------|
| `createBadge` / `createBadgeRow` / `updateBadge` | components/common/badge.ts | buy-target.ts, sell-position.ts | 미지원 (단일 라벨+값+단위) |
| `createProgressBar` | components/common/progress-bar.ts | sector-settings.ts, header.ts | 미지원 (단일 바, 2인스턴스 생성은 가능) |
| `createStockNameCell` | components/common/ui-styles.ts:172 | 종목명 셀 (NXT 삼각 표시) | 셀 단위라 배지용 부적합 |
| sector-stock.ts 인라인 카운트 | sector-stock.ts:399~481 | sector-stock.ts만 사용 | **분리 표시 이미 구현되어 있으나 공통 컴포넌트 아님** |

#### P23 일관성 위반 사항
1. **같은 "KRX/NXT 종목수" 정보가 3곳에서 다른 패턴**:
   - sector-stock.ts: 인라인 4그룹 (KRX/NXT/코스피/코스닥)
   - header.ts: `applyMarketPhaseChip` 2개 (KRX/NXT 페이즈만, 종목수 없음)
   - sector-settings.ts: 인라인 2개 (수신/미수신 단일)
2. **NXT 시각 강조 패턴 불일치**:
   - sector-stock.ts 종목수: NXT 라벨 = `COLOR.up`(빨강) + ▲ 삼각
   - sector-stock.ts 종목명 셀: NXT 삼각 = `COLOR.up`(빨강) 우하단
   - header.ts 장 페이즈: NXT 칩 = 페이즈별 초록/회색 (빨강 없음)
3. **공통 컴포넌트 미추출**: sector-stock.ts의 KRX/NXT 카운트 표시가 재사용 가능한 형태로 추출되지 않음

#### progress-bar.ts 2인스턴스 생성 가능 여부
- `createProgressBar(color, options)` 인터페이스로 독립 인스턴스 2개 생성 가능 (이미 설계됨)
- `setValue(pct)`, `setThreshold(thresholdPct)` 개별 호출 가능
- **결론: 2인스턴스 생성 구조적 가능. 색상/임계치 개별 설정 가능**

### 2-5. sector-stock.ts 카운트 인라인 추출 영향 범위

#### 현재 구조 (sector-stock.ts:312~329, 399~481)
- `updateUI(rows)` 메서드에서 매 렌더링마다 `stocks.filter()`로 4개 카운트 계산
- DOM 참조: `titleKrxNumSpan`, `titleNxtNumSpan`, `titleKospiNumSpan`, `titleKosdaqNumSpan` (private 필드)
- `connectedCallback`에서 인라인 DOM 생성 (라벨+숫자+단위 span 조합)
- NXT 라벨: `COLOR.up`(빨강) + ▲ 삼각이모지 (sector-stock.ts:430~444)
- KRX/코스피/코스닥 라벨: `COLOR.neutral`(회색)
- 숫자: 모두 `COLOR.down`(파랑) + semibold

#### 추출 시 영향
- **단일 파일 내 변경**: sector-stock.ts만 수정 (다른 파일 참조 없음)
- **DOM 참조 구조 변경**: private 필드 → 공통 컴포넌트 핸들로 대체
- **렌더링 로직 보존**: `stocks.filter(s => !s.nxt_enable).length` 등 카운트 로직은 그대로 유지, 텍스트 갱신만 컴포넌트 메서드로 이동
- **테스트 영향**: sector-stock.ts에 대한 직접 단위 테스트 없음 (PBT용 export 함수만 별도)
- **Shadow DOM**: sector-stock.ts는 Shadow DOM 사용 → 공통 컴포넌트도 Shadow DOM 내에 삽입 가능 (컴포넌트 자체는 light DOM 요소)

---

## 3. 3단계 구현 계획

> **세션당 1단계 원칙 (AGENTS.md 섹션3 규칙 0-1)**: 각 단계는 별도 세션에서 진행. 한 세션에서 여러 단계 연속 진행 금지.

### 3-1. 1단계: 프론트엔드 공통 컴포넌트 추출 (sector-stock.ts KRX/NXT 카운트)

#### 목표
- sector-stock.ts의 인라인 KRX/NXT/코스피/코스닥 카운트 표시를 공통 컴포넌트로 추출
- 2단계(수신률 분리 배지)에서 재사용할 수 있는 기반 마련
- **기능 변경 없음** — 시각적 동작 100% 동일 유지 (P23 일관성 개선만)

#### 수정 파일 목록
| 파일 | 수정 내용 | 예상 영향 |
|------|-----------|-----------|
| `frontend/src/components/common/market-count-row.ts` (신규) | KRX/NXT/코스피/코스닥 카운트 행 공통 컴포넌트 생성 | 신규 파일 |
| `frontend/src/pages/sector-stock.ts` | 인라인 카운트 DOM 생성 → 공통 컴포넌트 호출로 대체 (lines 263~270, 312~329, 399~481) | 단일 파일, 기능 변경 없음 |

#### 컴포넌트 인터페이스 (설계안)
```typescript
// components/common/market-count-row.ts
export interface MarketCountRowHandle {
  el: HTMLElement
  /** 각 카운트 값만 갱신 (DOM 재구성 없음) */
  updateCounts(counts: { total: number; krx: number; nxt: number; kospi: number; kosdaq: number }): void
}

export function createMarketCountRow(options?: {
  showTotal?: boolean   // 합계 표시 (기본 true)
  showKrx?: boolean     // KRX 표시 (기본 true)
  showNxt?: boolean     // NXT 표시 (기본 true)
  showKospi?: boolean   // 코스피 표시 (기본 true)
  showKosdaq?: boolean  // 코스닥 표시 (기본 true)
}): MarketCountRowHandle
```

#### 검증 방법
1. `npm run build` — TypeScript 컴파일 + 번들링 성공
2. 브라우저 확인:
   - 업종별 종목 실시간 시세 테이블 상단 "합계 N종목 | KRX: N종목 | NXT▲: N종목 | 코스피: N종목 | 코스닥: N종목" 표시가 기존과 동일
   - NXT 라벨 빨강 + ▲ 삼각 유지
   - 숫자 파랑 + semibold 유지
   - 실시간 틱 수신 시 카운트 갱신 동작
3. 시간대별 확인 (가능한 경우):
   - NXT-only 구간: KRX 단독 종목 opacity 0.85 표시 유지
   - 정규장: 모든 종목 정상 표시

#### P원칙 체크
- [x] P10(SSOT): 카운트 계산 로직은 sector-stock.ts에 유지, 컴포넌트는 표시만 담당
- [x] P21(사용자 투명성): 시각적 동작 100% 동일 → 사용자 인지 변화 없음
- [x] P23(일관성): 공통 컴포넌트 추출로 향후 2단계 재사용 기반 마련
- [x] P24(단순성): 기능 변경 없이 구조만 분리, 함수 50줄 이하 유지

---

### 3-2. 2단계: 프론트엔드 수신률 분리 배지 + 진행 바 2인스턴스

#### 목표
- sector-settings.ts의 수신률 표시를 KRX/NXT 분리 배지로 변경
- `createProgressBar()` 2인스턴스(KRX용/NXT용) 생성
- 시간대(`marketPhase.is_nxt_only` 또는 `krx`/`nxt` 페이즈)에 따라 배지 활성/비활성 전환
- **1단계에서 추출한 `createMarketCountRow` 재사용** (P23 일관성)

#### 수정 파일 목록
| 파일 | 수정 내용 | 예상 영향 |
|------|-----------|-----------|
| `frontend/src/stores/uiStore.ts` | `receiveRate` 타입 변경 — KRX/NXT 분리 객체 (lines 54, 226) | uiStore 구독 모든 곳 영향 |
| `frontend/src/binding.ts` | `receive-rate` 이벤트 매핑 변경 — KRX/NXT 분리 객체 (lines 274~277) | 단일 이벤트 핸들러 |
| `frontend/src/pages/sector-settings.ts` | 진행 바 2인스턴스 생성 + 분리 배지 + 시간대별 활성/비활성 (lines 152~204, 352~369) | 단일 파일, UI 구조 변경 |
| `frontend/src/types/index.ts` | `receiveRate` 타입 정의 변경 (해당 인터페이스 있는 경우) | 타입 정의 |

#### uiStore.receiveRate 타입 변경안
```typescript
// 기존
receiveRate: { received: number; total: number; pct: number } | null

// 변경 후
receiveRate: {
  krx: { received: number; total: number; pct: number } | null
  nxt: { received: number; total: number; pct: number } | null
} | null
```

#### 시간대별 표시 시나리오
| 시간대 | KRX 배지 | NXT 배지 | KRX 진행 바 | NXT 진행 바 |
|--------|----------|----------|-------------|-------------|
| NXT-only (08:00~08:50, 15:40~20:00) | 비활성(회색/숨김) | 활성(파랑) | 숨김 또는 비활성 | 활성, 임계치 마커 |
| 정규장 (09:00~15:20) | 활성(파랑) | 활성(파랑) | 활성, 임계치 마커 | 활성, 임계치 마커 |
| 비-WS 구간 | 비활성 | 비활성 | 숨김 | 숨김 |

#### 검증 방법
1. `npm run build` — TypeScript 컴파일 성공 (타입 변경 연동)
2. 브라우저 확인:
   - sector-settings 페이지 진입 시 KRX/NXT 분리 배지 2개 표시
   - 진행 바 2개 (KRX용/NXT용) 개별 임계치 마커 표시
   - 비-WS 구간: 양쪽 배지 비활성, 진행 바 숨김 또는 0%
   - WS 구간 진입 시 실시간 수신률 갱신 — KRX/NXT 개별 카운트 표시
3. 시간대별 확인 (가능한 경우):
   - NXT-only 구간: NXT 배지만 활성, KRX 배지 비활성
   - 정규장: 양쪽 배지 활성, 개별 수신률 표시

#### P원칙 체크
- [x] P10(SSOT): 수신률 데이터는 백엔드에서 단일 소스 관리, 프론트엔드는 표시만
- [x] P21(사용자 투명성): KRX/NXT 개별 수신 상태 표시 → "왜 업종순위가 안 시작하지?" 의문 해소
- [x] P23(일관성): 1단계 공통 컴포넌트 재사용, 진행 바 기존 컴포넌트 2인스턴스
- [x] P24(단순성): 2인스턴스는 기존 컴포넌트 설계와 호환, 새 추상화 불필요

#### 주의사항
- **백엔드 수신률 분리(3단계) 완료 전까지는 더미 데이터 또는 단일 수신률을 양쪽에 동일 표시** — 2단계 단독 실행 시 시각적 분리만 구현, 데이터는 3단계에서 연동
- **또는 2단계와 3단계를 단일 세션에서 통합 진행** — 단, AGENTS.md 규칙 0-1(세션당 1단계) 위반 가능성. 사용자 승인 시 예외 허용 검토

---

### 3-3. 3단계: 백엔드 수신률 KRX/NXT 분리 집계 + 임계값 게이트 정책

#### 목표
- `_received_codes` 단일 세트 → KRX/NXT 분리 (또는 태그 부여)
- 틱 수신 시 `parse_fid9081_exchange()` 결과로 KRX/NXT 분기하여 추가
- `_calculate_receive_rate()` — 시간대에 따라 KRX-only / NXT-only / 양쪽 분리 계산
- `_send_receive_rate()` 전송 구조 변경 — `{krx: {received, total, pct}, nxt: {received, total, pct}}`
- 임계값 게이트 `_sector_threshold_passed` — 시간대별 분기 정책(옵션 C) 적용

#### 수정 파일 목록
| 파일 | 수정 내용 | 예상 영향 |
|------|-----------|-----------|
| `backend/app/pipelines/pipeline_compute.py` | `_received_codes` 분리, `_calculate_receive_rate()` 분리 계산, `_send_receive_rate()` 전송 구조 변경, `get_current_receive_rate()` 반환 구조 변경, `_process_tick_0b_01` 틱 분기 추가, 임계값 게이트 시간대별 분기 | 핵심 수정 대상, 다수 함수 |
| `backend/app/services/engine_account_notify.py` | `get_current_receive_rate()` 호출 구조 변경, `prev_receive_rate` 비교 로직 변경, `status.receive_rate` 전송 구조 변경 (lines 287~288, 308, 319, 336) | 전송 연동 |
| `backend/app/services/market_close_pipeline.py` | `_calculate_receive_rate()`, `_send_receive_rate()` 호출 구조 변경 (lines 965~967, 1389~1391) | 확정 데이터 갱신 연동 |
| `backend/app/services/sector_data_provider.py` | `get_sector_summary_inputs()` — 정규장에서도 KRX/NXT 분리된 all_codes 반환 (lines 16~51) | all_codes 구조 변경 |
| `backend/tests/test_pipeline_compute.py` | `_current_receive_rate`, `_received_codes`, `_calculate_receive_rate` 등 63개 참조 전면 수정 | 테스트 전면 수정 |
| `backend/tests/test_engine_account_notify.py` (해당 시) | `receive_rate` 관련 테스트 수정 | 테스트 연동 |

#### _received_codes 분리 설계안
```python
# 기존
_received_codes: set[str] = set()

# 변경안 A: 2세트 분리
_received_codes_krx: set[str] = set()
_received_codes_nxt: set[str] = set()

# 변경안 B: 태그 부여 (dict)
_received_codes: dict[str, str] = {}  # {code: "krx" | "nxt"}
```

**추천: 안 A (2세트 분리)** — P24(단순성) 우선, 집합 연산 명확

#### 틱 수신 분기 로직 (pipeline_compute.py:575~582)
```python
# 기존
if is_0b_tick and any(f in vals for f in ("10", "11", "12", "14", "17", "228")):
    _apply_real01_volume_amount_to_radar_rows(raw_cd, vals, is_0b_tick=is_0b_tick)
    if nk_px:
        request_sector_recompute(nk_px)
        _received_codes.add(nk_px)
        _receive_rate_dirty = True

# 변경안
if is_0b_tick and any(f in vals for f in ("10", "11", "12", "14", "17", "228")):
    _apply_real01_volume_amount_to_radar_rows(raw_cd, vals, is_0b_tick=is_0b_tick)
    if nk_px:
        request_sector_recompute(nk_px)
        # FID 9081로 KRX/NXT 분기 (P10 SSOT — engine_ws_parsing 재사용)
        from backend.app.services.engine_ws_parsing import parse_fid9081_exchange
        exchange = parse_fid9081_exchange(vals)
        if exchange == "2":
            _received_codes_nxt.add(nk_px)
        else:  # "1" 또는 빈 문자열 (구독 방식에 따라 없을 수 있음)
            _received_codes_krx.add(nk_px)
        _receive_rate_dirty = True
```

**주의**: FID 9081이 빈 문자열인 경우(구독 방식에 따라 없을 수 있음 — engine_ws_parsing.py:184 주석) — `_AL` 통합 구독 시 KRX/NXT 구분이 안 될 수 있음. 이 경우 `is_nxt_enabled(nk_px)`로 보충 판단 필요. **사전조사 추가 필요**: `_AL` 구독 시 FID 9081 실제 수신 여부

#### 임계값 게이트 시간대별 분기 (옵션 C)
```python
# pipeline_compute.py Phase 1 루프 (line 713~746)
async def _calculate_receive_rate() -> None:
    # 시간대별 분기
    from backend.app.services.daily_time_scheduler import is_nxt_only_window
    if is_nxt_only_window():
        # NXT-only 구간: NXT 수신률만 계산
        ...
    else:
        # 정규장 또는 비-WS 구간: KRX/NXT 분리 계산
        ...

# Phase 1 임계값 통과 판정 (line 729)
if is_nxt_only_window():
    # NXT 수신률만 기준
    if nxt_pct >= threshold_pct:
        mark_sector_threshold_passed()
else:
    # 정규장: KRX/NXT 양쪽 모두 임계값 도달 시 (AND)
    if krx_pct >= threshold_pct and nxt_pct >= threshold_pct:
        mark_sector_threshold_passed()
```

#### 검증 방법
1. `pytest backend/tests/test_pipeline_compute.py -v` — 수신률 계산/전송/임계값 게이트 테스트 전면 수정 후 통과
2. `pytest backend/tests/test_engine_account_notify.py -v` — sector-scores 전송 테스트 (해당 시)
3. 백엔드 런타임 기동 검증 (AGENTS.md 섹션3 규칙 5):
   - `python -W error::RuntimeWarning main.py` — async await 누락 검증
   - WS 구독 구간 진입 시 KRX/NXT 분리 수신률 로그 출력 확인
   - NXT-only 구간(08:00~08:50)에서 NXT 수신률만 계산되는지 확인
   - 정규장(09:00~15:20)에서 KRX/NXT 분리 수신률 계산되는지 확인
4. 프론트엔드(2단계 완료 후) 브라우저 확인:
   - KRX/NXT 분리 수신률 실시간 갱신
   - 임계값 게이트 통과 시 업종순위 계산 시작

#### P원칙 체크
- [x] P10(SSOT): `is_nxt_only_window()` 재사용, 새 시간 상수 생성 금지
- [x] P16(살아있는 경로): 틱 분기 로직이 실제 실행 경로에 연결, dead code 아님
- [x] P20(폴백 금지): FID 9081 빈 문자열 시 `is_nxt_enabled()`로 보충 — 폴백이 아닌 보조 판단 (주의 필요)
- [x] P21(사용자 투명성): 분리 수신률 표시로 사용자가 양쪽 상태 개별 확인
- [x] P22(데이터 정합성): 분리 수신률은 `market_phase` 기반 파생, 중복 저장 금지
- [x] P23(일관성): `parse_fid9081_exchange()`, `is_nxt_enabled()` 기존 함수 재사용
- [x] P24(단순성): 2세트 분리(안 A)가 dict 태그(안 B)보다 단순, 함수 50줄 이하 유지 검토

#### 핵심 로직 변경 승인 필요 (AGENTS.md 규칙 0-4/0-5)
- **임계값 게이트 정책 변경**: 단일 수신률 기준 → 시간대별 분기 정책 (옵션 C)
- **UI 기준 설명**: 
  - 변경 전: 수신률이 70% 도달하면 업종순위 계산 시작 (단일 기준)
  - 변경 후: 
    - NXT 전용 시간대(08:00~08:50, 15:40~20:00): NXT 수신률이 70% 도달하면 시작
    - 정규장(09:00~15:20): KRX/NXT 모두 70% 도달하면 시작 (양쪽 모두 충족해야 함)
  - 사용자 확인 영향: 정규장에서 KRX는 빨리 도달해도 NXT가 늦으면 업종순위 계산이 대기 중으로 표시됨 — "대기 중" 라벨로 투명성 확보
- **사용자 승인 필수**: 임계값 게이트는 업종순위 계산 시작 시점을 결정하는 핵심 로직. 승인 없이 수정 금지

---

## 4. 단계별 의존 관계

```
1단계 (프론트엔드 공통 컴포넌트 추출)
  ↓ 의존: 2단계에서 createMarketCountRow 재사용
2단계 (프론트엔드 수신률 분리 배지)
  ↓ 의존: 3단계에서 분리된 수신률 데이터 전송
3단계 (백엔드 수신률 분리 집계 + 임계값 게이트)
```

- **1단계는 독립 실행 가능** — 기능 변경 없이 구조 분리만
- **2단계는 1단계 완료 후 실행** — 공통 컴포넌트 재사용
- **3단계는 2단계 완료 후 실행** — 프론트엔드 분리 표시가 백엔드 분리 데이터와 연동
- **2단계와 3단계 통합 옵션**: 사용자 승인 시 단일 세션에서 통합 진행 가능 (AGENTS.md 규칙 0-1 예외)

---

## 5. 추가 발견 사항 (메인 작업과 무관)

### 5-1. FID 9081 빈 문자열 케이스 (사전조사 추가 필요)
- `engine_ws_parsing.py:184` 주석: "'' = 미수신(구독 방식에 따라 없을 수 있음)"
- `_AL` 통합 구독(KRX+NXT 슬롯 1개) 시 FID 9081이 실제로 수신되는지 확인 필요
- 3단계 구현 전 실제 틱 데이터 로그 확인 권장 — FID 9081 빈 문자열 빈도, `is_nxt_enabled()` 보충 판단 충분성

### 5-2. _AL 구독 시 수신률 분리 가능성
- `get_ws_subscribe_code()` (engine_symbol_utils.py:24~35) — NXT 중복상장 종목은 `{base}_AL` 통합 구독
- 통합 구독 시 단일 슬롯에서 KRX/NXT 체결이 모두 수신됨 — FID 9081로 분리 가능한지가 관건
- 분리 불가 시: `is_nxt_enabled()` 기준으로 NXT-enabled 종목은 양쪽 모두 카운트, KRX 단독 종목은 KRX만 카운트 (단순화)

### 5-3. engine_account_notify.py prev_receive_rate 비교 로직
- `engine_account_notify.py:308` — `receive_rate != notify_cache.prev_receive_rate`로 변경 감지
- 분리 객체로 변경 시 dict 비교가 아닌 중첩 dict 비교 — Python `==` 연산자로 자동 처리되나 테스트 검증 필요

---

## 6. 검증 체크리스트 (전체 완료 후)

### 백엔드
- [ ] `pytest backend/tests/test_pipeline_compute.py -v` 전체 통과
- [ ] `pytest backend/tests/test_engine_account_notify.py -v` (해당 시) 통과
- [ ] `python -W error::RuntimeWarning main.py` async await 누락 없음
- [ ] 런타임 기동 시 KRX/NXT 분리 수신률 로그 정상 출력
- [ ] NXT-only 구간: NXT 수신률만 계산, KRX 비활성
- [ ] 정규장: KRX/NXT 분리 수신률 계산, 양쪽 표시
- [ ] 임계값 게이트: 시간대별 분기 정책(옵션 C) 정상 동작

### 프론트엔드
- [ ] `npm run build` TypeScript 컴파일 성공
- [ ] sector-stock.ts: KRX/NXT/코스피/코스닥 카운트 표시 기존과 동일 (1단계)
- [ ] sector-settings.ts: KRX/NXT 분리 배지 2개 표시 (2단계)
- [ ] sector-settings.ts: 진행 바 2인스턴스 개별 임계치 마커 (2단계)
- [ ] 시간대별 배지 활성/비활성 전환 (2단계)
- [ ] 실시간 수신률 KRX/NXT 개별 갱신 (3단계 연동 후)

### 아키텍처 원칙
- [ ] P10(SSOT): 새 시간 상수 생성 없음, 기존 `market_phase`/`is_nxt_only_window()` 재사용
- [ ] P16(살아있는 경로): 틱 분기 로직 실제 실행 경로 연결
- [ ] P20(폴백 금지): FID 9081 빈 문자열 시 보조 판단만, silent except: pass 없음
- [ ] P21(사용자 투명성): KRX/NXT 개별 수신 상태 UI 표시
- [ ] P22(데이터 정합성): 분리 수신률 `market_phase` 기반 파생
- [ ] P23(일관성): 공통 컴포넌트 재사용, 기존 함수 재사용
- [ ] P24(단순성): 함수 50줄/파일 500줄/복잡도 10 이하 유지

---

## 7. 사용자 승인 대기 항목

### 7-1. 임계값 게이트 정책 (3단계 — 핵심 로직 변경, 규칙 0-4/0-5)
- **옵션 C(시간대별 분기) 추천** — NXT-only 구간은 NXT만, 정규장은 양쪽 모두(AND)
- 승인 전까지 3단계 수정 금지

### 7-2. 2단계/3단계 통합 진행 여부
- **분리 진행(권장)**: 1단계 → 2단계 → 3단계 각각 별도 세션 (규칙 0-1 준수)
- **통합 진행**: 2단계+3단계 단일 세션 (규칙 0-1 예외 승인 필요)
- 통합 시 이점: 프론트엔드 분리 표시와 백엔드 분리 데이터가 한 세션에서 연동 완료
- 분리 시 이점: 단계별 검증 명확, 롤백 범위 최소화

### 7-3. 1단계 시작 승인
- 1단계는 기능 변경 없이 구조 분리만 — 가장 낮은 위험
- 승인 시 sector-stock.ts 인라인 카운트 → 공통 컴포넌트 추출 진행
