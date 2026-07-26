# C-07 종목코드 정규화 표현의 의미 경계

> 작성일: 2026-07-26
> 기준 계획서: `docs/coupling-audit-plan.md` C-07, 실행 태스크: `docs/coupling-audit-tasks.md` COUPLING-S7
> 상태: ☑ 완료 (조사·매트릭스 문서만 작성, 코드 수정 없음)
> 대상 원칙: P10 SSOT, P16 살아있는 경로, P20 입력 오류 의미 보존, P22 데이터 정합성, P23 용어·타입 일관성, P24 단순성

---

## 1. 조사 범위 및 방법

### 1.1 대상 함수 4종

| 함수 | 파일:줄 | 계층 | 언어 |
|------|---------|------|------|
| `normalize_stk_cd_key(code)` | `backend/app/core/settings_store.py:25` | core | Python |
| `_base_stk_cd(stk_cd)` | `backend/app/services/engine_symbol_utils.py:50` | services | Python |
| `_norm_stk_cd(stk_cd)` | `backend/app/services/data_manager.py:11` | services | Python |
| `normalizeStockCode(code)` | `frontend/src/stores/hotStore.ts:15` | frontend | TypeScript |

### 1.2 조사 방법

- 네 함수명 전수 grep (`backend`·`frontend`·`tests`·`docs`)
- 각 함수 정의부 전체 읽기 + 호출부 컨텍스트 추출
- 관련 테스트 파일 직접 단위 테스트 케이스·patch 사용 패턴 분석
- `normalize_symbol_override_map` (중간 래퍼) 경로 추적 → `apply_settings_updates` 설정 저장 경로 확인
- `state.master_stocks_cache` 키 생성 경로 추적 (`market_close_pipeline`에서 `_base_stk_cd`로 키 생성 확인)
- 백엔드/프론트엔드 경계·입력 도메인·출력 계약 비교

---

## 2. 함수별 정의 및 구현

### 2.1 `normalize_stk_cd_key` — `core/settings_store.py:25`

```python
def normalize_stk_cd_key(code: str) -> str:
    s = str(code).strip()
    if s.isdigit():
        return s.zfill(6)
    return s
```

- **입력**: `str` (int 입력도 `str()` 강제 허용 — 테스트 `test_int_input` 케이스 존재)
- **동작**: 공백 strip → 순수 숫자면 `zfill(6)` (패딩만, 잘라내기 없음) → 비숫자는 그대로
- **출력**: 숫자 입력은 최소 6자리 zero-padded (길이 유지, 8자리 입력 → 8자리 유지); 비숫자는 strip된 원문
- **용도**: 설정 키 정규화 — `sell_per_symbol` dict의 키를 6자리로 정규화
- **docstring**: 없음
- **특이**: 접미사(_AL/_NX) 제거 안 함, 대소문자 변환 안 함, `[-6:]` 잘라내기 안 함 (zfill만)

### 2.2 `_base_stk_cd` — `services/engine_symbol_utils.py:50`

```python
def _base_stk_cd(stk_cd: str) -> str:
    """순수 종목코드 반환 (_AL/_NX 접미사 제거)."""
    s = str(stk_cd or "").strip().upper()
    for suffix in ("_AL", "_NX"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s
```

- **입력**: `str` (None-safe — `stk_cd or ""` 가드)
- **동작**: strip + upper → `_AL`/`_NX` 접미사 1회 제거 → 순수 숫자면 `zfill(6)[-6:]` (패딩 후 마지막 6자리) → 비숫자는 upper 그대로
- **출력**: 숫자 입력은 정확히 6자리 zero-padded (7자리+ 잘라냄); 비숫자는 upper + 접미사 제거
- **용도**: 엔진 전 경로 종목코드 정규화 — WS 구독 코드, REAL item 파싱, 캐시 키 조회, 틱 핸들러 매칭, 계좌 파싱, 매매/리스크/드라이런/파이프라인
- **docstring**: "순수 종목코드 반환 (_AL/_NX 접미사 제거)"
- **특이**: `_AL`/`_NX` 접미사 제거는 NXT 중복상장 슬롯 의미론 (KRX+NXT 통합 슬롯 1개). `[-6:]` 잘라내기는 7자리+ 계좌번호 오입력 방지 (`_real_item_stk_cd`에서 명시적 7자리 초과 스킵 로직과 연계)

### 2.3 `_norm_stk_cd` — `services/data_manager.py:11`

```python
def _norm_stk_cd(stk_cd: str) -> str:
    """캐시 키용. 순수 숫자만 6자리로; 비숫자 포함(0120G0)은 숫자만 남기면 001200과 충돌하므로 원문 유지."""
    s = str(stk_cd).strip()
    if not s:
        return ""
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s.upper()
```

- **입력**: `str` (None 안전하지 않음 — `str(None)` = "None" 이론적 위험이나 실제 호출부는 str 인입)
- **동작**: strip → 빈 입력 → "" → 순수 숫자면 `zfill(6)[-6:]` → 비숫자는 upper (접미사 제거 안 함)
- **출력**: 숫자 입력은 정확히 6자리 zero-padded; 비숫자는 upper; 빈 입력은 ""
- **용도**: 종목명 조회 캐시 키 — `get_stock_name()`에서 `state.master_stocks_cache` 조회용
- **docstring**: "캐시 키용. 순수 숫자만 6자리로; 비숫자 포함(0120G0)은 숫자만 남기면 001200과 충돌하므로 원문 유지."
- **특이**: `_base_stk_cd`와 거의 동일하나 `_AL`/`_NX` 접미사 제거만 빠짐. 단일 호출부. docstring이 비숫자 보존 이유(충돌 방지)를 명시

### 2.4 `normalizeStockCode` — `frontend/stores/hotStore.ts:15`

```typescript
export function normalizeStockCode(code: string | undefined | null): string {
  if (!code) return ''
  let cd = code.includes('_') ? code.split('_')[0] : code
  if (cd.startsWith('A')) cd = cd.substring(1)
  if (/^\d+$/.test(cd) && cd.length < 6) {
    cd = cd.padStart(6, '0')
  }
  return cd
}
```

- **입력**: `string | undefined | null` (null-safe)
- **동작**: 빈/null → "" → `_` split 첫 부분 (모든 `_` 접미사 제거) → `A` 접두사 제거 → 순수 숫자 & 길이<6이면 `padStart(6,'0')` → 그 외 그대로
- **출력**: 숫자 입력은 6자리 미만만 zero-padded (6자리 이상은 길이 유지, 잘라내기 없음); `A` 접두사 제거; `_` 접미사 제거; 비숫자는 그대로 (대소문자 변환 없음)
- **용도**: 프론트 Store/페이지 종목코드 정규화 — `sectorStocks` Record 키, position 인덱스 매칭, buyTargets 매칭, real-data 디스패치, orderbook/program update
- **docstring**: "종목코드 정규화 헬퍼"
- **특이**: `A` 접두사 제거는 KRX REST 응답 형식(A005930) 전용. `_` split은 `_AL`/`_NX`뿐 아니라 모든 `_` 접미사 제거 (더 넓음). 대소문자 변환 안 함. 잘라내기 안 함 (padStart만)

---

## 3. 비교 매트릭스

| 항목 | `normalize_stk_cd_key` | `_base_stk_cd` | `_norm_stk_cd` | `normalizeStockCode` |
|------|------------------------|----------------|----------------|---------------------|
| 파일 | `core/settings_store.py:25` | `services/engine_symbol_utils.py:50` | `services/data_manager.py:11` | `frontend/stores/hotStore.ts:15` |
| 계층 | core | services | services | frontend |
| 언어 | Python | Python | Python | TypeScript |
| 입력 타입 | `str` (int 허용) | `str` (None-safe) | `str` (None 위험) | `string \| undefined \| null` |
| 공백 strip | O | O | O | X (`!code` 가드만) |
| 대소문자 | 그대로 | upper | upper | 그대로 |
| `_AL`/`_NX` 접미사 제거 | X | O (1회) | X | X (`_` split으로 모든 `_` 제거) |
| `A` 접두사 제거 | X | X | X | O |
| 숫자 패딩 | `zfill(6)` (길이 유지) | `zfill(6)[-6:]` (truncate) | `zfill(6)[-6:]` (truncate) | `padStart(6,'0')` if len<6 (길이 유지) |
| 빈 입력 | "" | "" (None-safe) | "" | "" |
| 비숫자 처리 | 그대로 | upper | upper | 그대로 |
| 용도 | 설정 키 (`sell_per_symbol`) | 엔진 전 경로 종목코드 | 종목명 캐시 키 | 프론트 Store/페이지 |
| 호출부 수 | 1 (간접) | 25+ | 1 | 30+ |
| 직접 단위 테스트 | O (6 cases) | X (patch 기반) | O (6 cases) | X |

---

## 4. 호출부 전수 조사

### 4.1 `normalize_stk_cd_key` 호출부 (1건, 간접)

- `backend/app/core/settings_store.py:37` — `normalize_symbol_override_map()` 내부
  - `normalize_symbol_override_map()` 호출부: `settings_store.py:284` — `apply_settings_updates()`에서 `sell_per_symbol` dict 키 정규화
- **도메인**: 사용자가 설정 UI에서 입력한 종목별 매도 설정 dict의 키. 6자리 미만 숫자 입력(예: "5930")을 "005930"으로 정규화. `_AL`/`_NX` 접미사·`A` 접두사는 설정 UI에서 입력되지 않음.

### 4.2 `_base_stk_cd` 호출부 (25+건)

**core (역참조 — C-06 조사 범위):**
- `backend/app/core/kiwoom_account_parsing.py:99` — 키움 REST/REAL04 파싱 시 종목코드 매칭
- `backend/app/core/ls_connector.py:236` — `_convert_ls_to_internal()` UH1 호가 종목코드 정규화
- `backend/app/core/ls_connector.py:256` — `_convert_ls_to_internal()` UPH 프로그램매매 코드 정규화
- `backend/app/core/ls_connector.py:777` — `_format_code()` LS 형식 변환 전 베이스 코드 추출

**services:**
- `engine_symbol_utils.py` 내부 (5건): `is_nxt_enabled:16`, `get_ws_subscribe_code:29`, `get_stock_market:43`, `_fid9001_to_stk_cd:82`, `_real_item_stk_cd:113/124`
- `engine_ws_reg.py:269/277/413` — REG 구독 코드 리스트 정규화 (3건)
- `engine_account_broadcast.py:92` — 계좌 브로드캐스트 시 포지션 종목코드 정규화
- `engine_account.py:430/436` — 포지션 코드 집합 구성 (2건)
- `engine_radar.py:61` — 레이더 종목코드 정규화
- `engine_ws_dispatch.py:71` — REG 응답 처리 시 item 코드 정규화
- `trading.py:528/603/619/759` — 매매 로직 종목코드 매칭 (4건, safe-trade 범위)
- `engine_account_rest.py:28/154/156` — REST 계좌 응답 종목코드 정규화 (3건)
- `risk_manager.py:140/142` — 리스크 매니저 포지션 매칭 (2건)
- `engine_account_notify.py:109` — 계좌 알림 종목코드 정규화
- `market_close_pipeline.py:98/109/250/285/428/440/442/496/608/632/1136/1247` — 장마감 파이프라인 전 종목코드 정규화 (12건, 캐시 키 생성 포함)
- `dry_run.py:226/255/277/298` — 드라이런 종목코드 정규화 (4건)

**web:**
- `ws_manager.py:226` — real-data 브로드캐스트 시 item 코드 정규화
- `routes/status.py:58` — 디버그 엔드포인트 `/debug/sector-stock/{code}` 입력 정규화

**pipelines:**
- `pipeline_compute_tick_handlers.py:194/225/278/314/361` — 틱 핸들러 포지션/종목코드 매칭 (5건)

**도메인**: WS 구독 코드, REAL/REG 파싱, `state.master_stocks_cache` 키 조회/생성, 틱 핸들러 매칭, 계좌 파싱, 매매/리스크/파이프라인 전 경로. `_AL`/`_NX` 접미사(NXT 중복상장 슬롯)와 7자리+ 계좌번호 오입력 모두 처리.

### 4.3 `_norm_stk_cd` 호출부 (1건)

- `backend/app/services/data_manager.py:24` — `get_stock_name()` 내부
- **도메인**: 종목명 조회 캐시 키. `state.master_stocks_cache`에서 종목명 조회. 단일 호출부, 단일 목적.

### 4.4 `normalizeStockCode` 호출부 (30+건)

**hotStore.ts 내부 (15건):**
- `stocksToMap:29` — 배열 → Record 변환 키
- `rebuildBuyTargetIndex:70` — buyTargets 인덱스 Map 키
- `rebuildPositionIndex:79` — positions 인덱스 Map 키
- `getBuyTargetIndex:86` — 인덱스 조회
- `getPositionIndex:90` — 인덱스 조회
- `applyAccountUpdate:159/162/171/209/212/220` — positions delta 처리 (6건)
- `applyRealData:296` — real-data 디스패치 코드
- `applyOrderbookUpdate:437` — 호가 업데이트 코드
- `applyProgramUpdate:466` — 프로그램 매매 업데이트 코드
- `applyBuyTargetsUpdate:555/573/639` — buyTargets 매칭 (3건)
- `applySellTargetsUpdate:674/721` — sellTargets 처리 (2건)

**binding.ts (5건):**
- `binding.ts:106/107/112/115/130` — buy-targets-delta 처리

**pages (9건):**
- `stock-classification-master.ts:203` — sectorStocks 조회
- `stock-classification-center.ts:146` — sectorStocks 조회
- `sell-position.ts:31/42/62/80` — positions sectorStocks 매칭 (4건)
- `profit-shared.ts:423` — positions 종목코드
- `profit-columns.ts:17/39` — daily drilldown sectorStocks 매칭 (2건)

**도메인**: 프론트 Store/페이지의 종목코드 매칭. `A` 접두사(KRX REST 응답) 제거, `_` 접미사 제거. 백엔드에서 넘어온 코드와 프론트 입력 모두 처리.

---

## 5. 테스트 커버리지

### 5.1 직접 단위 테스트 존재

| 함수 | 테스트 파일 | 케이스 수 | 비고 |
|------|------------|----------|------|
| `normalize_stk_cd_key` | `test_settings_store.py:23-42` | 6 | digit padded, already 6, non-digit passthrough, strips whitespace, empty, int input |
| `_norm_stk_cd` | `test_data_manager.py:17-36` | 6 | empty, pure digit short, exact, long truncates, non-digit uppercased, strips whitespace |
| `_base_stk_cd` | (직접 단위 테스트 없음) | — | patch 기반 간접 검증 (test_ls_connector 9건, test_pipeline_compute 16건, test_market_close_pipeline 40건 등) |
| `normalizeStockCode` | (직접 단위 테스트 없음) | — | hotStore.test.ts에 직접 케이스 없음 |

### 5.2 patch 사용 패턴 (`_base_stk_cd`)

- `test_ls_connector.py:382/399/408/645/666/678/689/712/733/967/973/979` — 9건, `return_value="005930"` 또는 `side_effect=["005930","000660"]`
- `test_web_ws_manager.py:444` — 1건
- `test_pipeline_compute.py:515/529/548/559/577/590/603/616/629/858/867/884/909/936/968` — 15건+
- `test_market_close_pipeline.py:135/148/163/302/353/394/434/470/505/545/575/595/609/625/638/689/705/720/753/768/850/888/998/1057/1113/1155/...` — 40건+, `side_effect=lambda x: x` (통과)

### 5.3 테스트 커버리지 관찰

- `normalize_stk_cd_key`와 `_norm_stk_cd`는 직접 단위 테스트로 입력·출력 계약 명시 검증
- `_base_stk_cd`는 patch 기반 간접 검증만 — 호출부가 많아 patch로 동작을 고정하는 패턴. 정규화 규칙 자체(접미사 제거·truncate)의 직접 단위 테스트 부재
- `normalizeStockCode`는 직접 단위 테스트 부재 — `p25_isolated_failure_investigation.md:579-599`에서 `code.includes('_')` 시 `code` undefined throw 가능성 식별됨

---

## 6. 의미 경계 분석 (통합 가능성 판정)

### 6.1 `normalize_stk_cd_key` vs `_base_stk_cd`

**차이점:**
- 접미사 제거: `_base_stk_cd`는 `_AL`/`_NX` 제거, `normalize_stk_cd_key`는 제거 안 함
- 대소문자: `_base_stk_cd`는 upper, `normalize_stk_cd_key`는 그대로
- 잘라내기: `_base_stk_cd`는 `[-6:]`, `normalize_stk_cd_key`는 zfill만 (길이 유지)

**도메인 차이:**
- `normalize_stk_cd_key` 입력: 사용자가 설정 UI에서 입력한 종목코드 (6자리 미만 가능, `_AL`/`_NX`·`A` 접두사 없음)
- `_base_stk_cd` 입력: WS/REAL/REG 파싱 결과, 계좌번호 오입력 가능, `_AL`/`_NX` 접미사 가능

**판정: ⊘ 통합 금지**
- 설정 키 도메인과 엔진 코드 도메인의 입력 계약이 다름
- `normalize_stk_cd_key`에 `[-6:]` truncate 추가 시 기존 설정 키 호환성 위험 (8자리 입력 케이스가 있으면 데이터 정합성 P22 위반)
- 접미사 제거 추가 시 설정 UI에서 입력되지 않는 접미사 처리 로직이 dead path가 됨 (P16 위반)

### 6.2 `_base_stk_cd` vs `_norm_stk_cd`

**차이점:**
- 접미사 제거: `_base_stk_cd`는 `_AL`/`_NX` 제거, `_norm_stk_cd`는 제거 안 함
- 나머지(upper, `[-6:]`, 빈 입력 처리)는 동일

**도메인 분석:**
- `_norm_stk_cd` 호출부: `get_stock_name()` 단 1건 — 종목명 조회 캐시 키
- `state.master_stocks_cache` 키는 `market_close_pipeline`에서 `_base_stk_cd`로 생성 (접미사 제거된 6자리)
- 따라서 `_norm_stk_cd`에 `_AL`/`_NX` 접미사 입력이 오면 현재도 캐시 미스 발생 (캐시 키는 접미사 제거된 형태)
- `_norm_stk_cd`가 접미사 제거를 안 하는 것이 의도적이라면 docstring에 명시되어야 하나, 현재 docstring은 비숫자 보존 이유만 설명 (접미사 미언급)

**판정: ⊘ 현 단계에서 독립 통합 금지, 단 이동 시 함께 검토 권장**
- 단일 호출부라 위험은 낮으나, C-06 후보 2(`_base_stk_cd` core 이동)와 중복되는 범위
- `_base_stk_cd`가 `core/symbol_utils.py`로 이동 시 `_norm_stk_cd`를 이 함수로 통합 검토 권장 (단, `_norm_stk_cd`의 접미사 미제거가 의도적이면 통합 금지 → 별도 승인 시 접미사 입력 경로 확인 필요)

### 6.3 `_base_stk_cd` vs `normalizeStockCode`

**차이점:**
- `A` 접두사 제거: `normalizeStockCode`만 제거 (KRX REST 응답 A005930 형식)
- 접미사 제거 범위: `_base_stk_cd`는 `_AL`/`_NX`만, `normalizeStockCode`는 모든 `_` split
- 대소문자: `_base_stk_cd`는 upper, `normalizeStockCode`는 그대로
- 잘라내기: `_base_stk_cd`는 `[-6:]`, `normalizeStockCode`는 padStart만 (길이 유지)

**판정: ⊘ 통합 금지 (물리적 불가)**
- 언어/경계 다름 (Python vs TypeScript, 백엔드 vs 프론트)
- 백엔드 코드를 프론트에서 import 불가하므로 물리적 통합 불가
- `A` 접두사 제거는 프론트 전용 정책 (KRX REST 응답 형식) — 백엔드 REAL/REG 경로에서는 `A` 접두사가 오지 않으므로 백엔드 `_base_stk_cd`에 추가하면 dead path (P16 위반)
- P23 일관성 측면: 프론트 `normalizeStockCode`가 백엔드 `_base_stk_cd`와 의미 동일하게 유지되어야 하는지는 별도 검토 대상이나, `A` 접두사·대소문자·잘라내기 차이는 각 환경의 입력 도메인 차이로 정당화됨

### 6.4 `normalize_stk_cd_key` vs `_norm_stk_cd`

**차이점:**
- 잘라내기: `_norm_stk_cd`는 `[-6:]`, `normalize_stk_cd_key`는 zfill만
- 대소문자: `_norm_stk_cd`는 upper, `normalize_stk_cd_key`는 그대로
- 빈 입력: `_norm_stk_cd`는 명시적 "" 반환, `normalize_stk_cd_key`는 strip 후 빈 문자열 → `isdigit()` False → "" 반환 (동일 결과)

**판정: ⊘ 통합 금지**
- 용도가 다름 (설정 키 vs 종목명 캐시 키)
- `normalize_stk_cd_key`는 설정 영속 데이터의 키 정규화 — truncate 추가 시 기존 설정 호환성 위험

---

## 7. 아키텍처 원칙 점검

### 7.1 P10 SSOT

- 종목코드 정규화 규칙이 4곳에 분산되어 있으나, 각 함수의 입력 도메인(설정 키/엔진 코드/종목명 캐시/프론트 Store)이 다르고 출력 계약(접미사/접두사/truncate/upper)이 다름
- 동일 데이터의 다중 표현이 아님 — 각 도메인의 SSOT는 유지됨
- **준수** (단, `_base_stk_cd`와 `_norm_stk_cd`는 거의 동일하므로 단일화 후보 — 6.2항 참조)

### 7.2 P16 살아있는 경로

- 4개 함수 모두 실제 호출부 존재, dead code 없음
- **준수**

### 7.3 P20 폴백 금지

- 모든 함수가 빈 입력을 ""로 반환하나 이는 폴백이 아니라 정상 경로의 빈 값 의미 보존
- 비숫자 입력을 숫자로 강제 변환하는 폴백 없음 — `_norm_stk_cd` docstring이 비숫자 보존 이유(충돌 방지)를 명시
- **준수**

### 7.4 P22 데이터 정합성

- `state.master_stocks_cache` 키는 `_base_stk_cd`로 생성 (접미사 제거된 6자리)
- `_norm_stk_cd`가 접미사 제거 안 함 → `_AL`/`_NX` 입력 시 캐시 미스 가능 (단, `get_stock_name` 호출부에서 접미사 입력 경로 확인 필요)
- `normalize_stk_cd_key`가 truncate 안 함 → 8자리 입력 시 설정 키가 8자리로 저장 (설정 도메인에서 8자리 입력이 발생하는지 확인 필요)
- **부분 준수** — 잠재 정합성 위험 2건 식별 (별도 승인 시 검토)

### 7.5 P23 일관성

- 함수명 유사 (`normalize_stk_cd_key`/`_base_stk_cd`/`_norm_stk_cd`/`normalizeStockCode`)하나 구현 차이
- 용어 사전 부록 M에 "종목코드" 단일 용어 있으나 정규화 규칙은 사전에 없음
- `_AL`/`_NX` 접미사 의미(NXT 중복상장 슬롯)가 도메인에 명시 필요 — 현재 `_base_stk_cd` docstring에만 명시
- **부분 준수** — 접미사 의미 문서화 권장

### 7.6 P24 단순성

- 4개 유사 함수 중복 관찰
- 그러나 각 입력 계약이 다르므로 단순 병합은 P22(데이터 정합성) 위반 초래
- `_base_stk_cd`와 `_norm_stk_cd`는 거의 동일(`_AL`/`_NX` 제거만 차이) — 단일화 후보 (6.2항)
- **부분 준수** — 단일화 후보 1건 식별

---

## 8. 개선 후보

> 모든 후보는 별도 사용자 승인 후 진행. 본 세션은 조사만 수행.

### 8.1 후보 1: `_base_stk_cd` core 이동 + `_norm_stk_cd` 통합 검토 (낮음, P23/P24)

- **내용**: `_base_stk_cd`를 `core/symbol_utils.py`(신규)로 이동 — C-06 후보 2와 중복
- **효과**: core→services 역참조 5건 제거 (C-06 조사 결과), `_norm_stk_cd` 단일 호출부 통합 가능
- **위험**: 낮음 (순수 함수, 단일 호출부)
- **승인 전 확인**: `_norm_stk_cd`의 접미사 미제거가 의도적인지 (`get_stock_name` 호출부에서 `_AL`/`_NX` 입력 경로 확인)
- **의존**: C-06 후보 2 (동일 범위)

### 8.2 후보 2: `normalizeStockCode` 직접 단위 테스트 추가 (낮음, P21/P25)

- **내용**: `frontend/tests/stores/hotStore.test.ts`에 `normalizeStockCode` 직접 케이스 추가
- **효과**: `code` undefined 시 throw 가능성 식별 (`p25_isolated_failure_investigation.md:579-599`) → 가드 추가 검토
- **위험**: 낮음 (테스트만 추가, 코드 수정은 별도 승인)
- **케이스**: 빈/null/undefined, `A` 접두사, `_` 접미사, 숫자 패딩, 비숫자, 6자리 이상

### 8.3 후보 3: `normalize_stk_cd_key` truncate 정책 docstring 명시 (낮음, P21)

- **내용**: `normalize_stk_cd_key`에 docstring 추가 — zfill만 하고 truncate 안 하는 이유 명시
- **효과**: 설정 키 도메인의 입력 계약 문서화 (사용자 입력은 6자리 미만만 정규화, 8자리 입력은 설정 도메인에서 발생하지 않음)
- **위험**: 낮음 (docstring만)

### 8.4 후보 4: `_base_stk_cd` 직접 단위 테스트 추가 (낮음, P21)

- **내용**: `backend/tests/test_engine_symbol_utils.py`(신규 또는 기존)에 `_base_stk_cd` 직접 케이스 추가
- **효과**: 현재 patch 기반 간접 검증만 — 접미사 제거·truncate·None-safe 계약 직접 명시
- **위험**: 낮음 (테스트만 추가)

---

## 9. 변경 금지 항목

1. **`normalize_stk_cd_key`의 truncate 추가 금지** — 설정 키 영속 데이터 호환성 위험 (P22)
2. **`normalize_stk_cd_key`의 접미사 제거 추가 금지** — 설정 UI에서 `_AL`/`_NX` 입력되지 않으므로 dead path (P16)
3. **`_base_stk_cd`의 `A` 접두사 제거 추가 금지** — 백엔드 REAL/REG 경로에서 `A` 접두사 오지 않으므로 dead path (P16)
4. **`normalizeStockCode`의 `[-6:]` truncate 추가 금지** — 프론트에서 7자리+ 입력 시 표시 깨짐 위험 (P21)
5. **4개 함수의 단순 병합 금지** — 각 입력 도메인·출력 계약이 다르므로 P22 위반 (본 문서 6항 참조)
6. **`_norm_stk_cd`의 접미사 제거 추가는 별도 승인 전 금지** — `get_stock_name` 호출부의 접미사 입력 경로 확인 전까지 (P22)

---

## 10. 핵심 발견 요약

1. **4개 함수는 이름이 유사하나 입력 도메인·출력 계약이 다름** — 설정 키(사용자 입력, 6자리 미만) / 엔진 코드(WS/REAL 파싱, `_AL`/`_NX` 접미사, 7자리+ 오입력) / 종목명 캐시 키(조회 전용) / 프론트 Store(KRX REST `A` 접두사, `_` 접미사)
2. **`_base_stk_cd`와 `_norm_stk_cd`는 거의 동일** — `_AL`/`_NX` 제거만 차이. 단일화 후보이나 C-06 후보 2(core 이동)와 중복 범위
3. **`_base_stk_cd`는 25+ 호출부로 사실상 엔진 종목코드 정규화의 SSOT** — core 역참조 5건 발생 (C-06 조사 결과, 후보 1과 중복)
4. **`normalizeStockCode` 직접 단위 테스트 부재** — `code` undefined 시 throw 가능성 식별됨 (p25 조사)
5. **`_base_stk_cd` 직접 단위 테스트 부재** — patch 기반 간접 검증만
6. **`normalize_stk_cd_key` truncate 정책 미문서화** — zfill만 하고 truncate 안 하는 이유가 docstring에 없음
7. **`_AL`/`_NX` 접미사 의미(NXT 중복상장 슬롯)가 `_base_stk_cd` docstring에만 명시** — 다른 함수·도메인에서 미문서화

---

## 11. 판정 요약

| 함수쌍 | 판정 | 사유 |
|--------|------|------|
| `normalize_stk_cd_key` vs `_base_stk_cd` | ⊘ 통합 금지 | 입력 도메인 다름 (설정 키 vs 엔진 코드), truncate 정책 다름 |
| `normalize_stk_cd_key` vs `_norm_stk_cd` | ⊘ 통합 금지 | 용도 다름 (설정 키 vs 종목명 캐시), truncate 정책 다름 |
| `_base_stk_cd` vs `_norm_stk_cd` | ⊘ 독립 통합 금지, 이동 시 검토 | 거의 동일하나 C-06 후보 2와 중복, 접미사 미제거 의도 확인 필요 |
| `_base_stk_cd` vs `normalizeStockCode` | ⊘ 통합 금지 (물리적 불가) | 언어/경계 다름 (Python vs TypeScript), `A` 접두사 정책 다름 |
| 4개 전체 통합 | ⊘ 통합 금지 | 각 입력 도메인·출력 계약 다름, 단순 병합 시 P22 위반 |

**결론:** 4개 함수 모두 현 단계에서 통합 금지 (⊘). 단, `_base_stk_cd` core 이동(C-06 후보 2) 진행 시 `_norm_stk_cd` 통합 검토를 함께 진행 권장. 독립 개선은 직접 단위 테스트 추가(후보 2·4)와 docstring 명시(후보 3)가 낮은 위험 후보.

---

## 12. 참조

- `docs/coupling-audit-plan.md` C-07 (131-159줄)
- `docs/coupling-audit-tasks.md` COUPLING-S7 (294-322줄)
- `docs/coupling-broker-core-backref.md` — C-06 조사 결과, `_base_stk_cd` 역참조 5건 (162-163, 173, 186, 248, 292-295, 334줄)
- `docs/coupling-settings-impact-matrix.md` — `normalize_stk_cd_key` 설정 파이프라인 (456줄)
- `docs/duplication-audit-plan.md` — 종목코드 정규화 중복 관찰 (88줄)
- `docs/p25_isolated_failure_investigation.md` — `normalizeStockCode` throw 가능성 (579-599줄)
- `backend/app/core/settings_store.py:25-38` — `normalize_stk_cd_key`·`normalize_symbol_override_map`
- `backend/app/services/engine_symbol_utils.py:50-59` — `_base_stk_cd`
- `backend/app/services/data_manager.py:11-18` — `_norm_stk_cd`
- `frontend/src/stores/hotStore.ts:15-23` — `normalizeStockCode`
- `backend/tests/test_settings_store.py:23-42` — `normalize_stk_cd_key` 직접 테스트
- `backend/tests/test_data_manager.py:17-36` — `_norm_stk_cd` 직접 테스트
