# P-001: 실시간 데이터 미수신 시 0 폴백 → 수신률 100% 왜곡 + 업종 점수 왜곡 수정계획서

> **작성일**: 2026-07-15
> **상태**: 사전조사 완료, 단계별 수정계획 수립 완료, 사용자 승인 대기
> **승인 상태**: 각 Step 시작 시 별도 승인 필요
> **관련 원칙**: P10 (SSOT), P16 (살아있는 경로), P20 (폴백 금지), P21 (사용자 투명성), P22 (데이터 정합성), P23 (일관성), P24 (단순성)

---

## 1. 배경 및 목표

### 1-1. 현상

- HD현대 등 종목의 실시간 데이터 필드가 0 또는 "-"로 표시되는데, 업종순위 계산 임계치 수신률은 100%로 표시됨.
- 사용자 지적: "0을 데이터로 인식해서 왜곡".

### 1-2. 근본 원인 (2단계 연쇄)

#### 원인 A — 미수신 데이터를 0으로 폴백 저장 (P20 폴백 금지 위반)

WS 구독 시작 시 `_reset_realtime_fields()`(`engine_snapshot.py:147-160`)가 `change_rate`, `trade_amount`를 `None`으로 초기화합니다. 이후 틱 수신 시 FID 값이 빈 문자열이면 파서가 `0.0`/`0`을 반환하여 `None`이 아닌 `0`으로 덮어씁니다.

| 코드 경로 | 확인된 사실 |
|---|---|
| `engine_ws_parsing.py:155-156` | `parse_change_rate_to_percent(None)` → `0.0` 반환. 빈 문자열·"0"도 `0.0` 반환. |
| `engine_account_rest.py:18-23` | `_parse_float_loose(None)` → `0.0` 반환. |
| `engine_radar.py:73-75` | FID 12 존재 시 `parse_change_rate_to_percent(vals["12"])` → 빈 값이면 `0.0` 저장. |
| `engine_radar.py:76-77` | FID 14 존재 시 `int(_parse_float_loose(vals["14"]))` → 빈 값이면 `0` 저장. |
| `pipeline_compute.py:576` | FID 12 키 없으면 `0.0` 할당. 빈 값이면 `parse_change_rate_to_percent` → `0.0` 저장. |

#### 원인 B — 수신률 계산이 0과 None을 구분하지 않음 (P22 데이터 정합성 위반)

| 코드 경로 | 확인된 사실 |
|---|---|
| `pipeline_compute.py:91-97` | `_has_any_realtime_data()`가 `entry.get(f) is not None`로만 판정. `0.0`/`0`은 None이 아니므로 "수신됨"으로 카운트. |
| `pipeline_compute.py:118-126` | `received_count`에 0으로 폴백된 종목이 포함됨. |

#### 수신률 100% → 업종순위 계산 시작 경로

1. `pipeline_compute.py:704` — `_calculate_receive_rate()` 호출.
2. `pipeline_compute.py:706` — `current_pct = _current_receive_rate["pct"]`.
3. `pipeline_compute.py:716` — `if current_pct >= threshold_pct:` 임계값 통과.
4. `pipeline_compute.py:721` — `mark_sector_threshold_passed()` → sector-scores 전송 허용.
5. `pipeline_compute.py:722` — `request_sector_recompute(None)` → 콜드 스타트 1회 전체 재계산.
6. `engine_account_notify.py:273-276` — `is_sector_threshold_passed()`가 False면 sector-scores 전송 차단.

#### 업종 점수 왜곡 경로

| 코드 경로 | 확인된 사실 |
|---|---|
| `sector_calculator.py:69` | `change_rate = float(detail.get("change_rate", 0) or 0)` — None을 0.0으로 폴백. |
| `sector_calculator.py:78` | `ta = int(detail.get("trade_amount", 0) or 0)` — None을 0으로 폴백. |
| `sector_calculator.py:129` | `raw_rise_count = sum(1 for s in filtered_stocks if s.change_rate > 0)` — 0은 상승 종목에서 제외 → rise_ratio 왜곡. |
| `sector_calculator.py:132-134` | `raw_total_ta`, `avg_ta`, `avg_cr`에 0 포함 → 평균 왜곡. |
| `sector_score.py:106-107` | 1차 가산점(상승비율 순위)에 왜곡된 `rise_ratio` 사용. |
| `sector_score.py:112-113` | 3차 가산점(거래대금 순위)에 왜곡된 `avg_trade_amount` 사용. |
| `sector_score.py:142` | 2차 가산점(가중 순위 합)에 0인 `change_rate` 포함. |

### 1-3. 목표

1. **틱 수신 경로에서 빈 FID 값을 0이 아닌 None으로 저장** (P20 폴백 금지 준수).
2. **수신률 계산이 None과 0을 정확히 구분** (P22 데이터 정합성 준수).
3. **업종 점수 계산에서 미수신 종목(None)을 0으로 폴백하지 않고 제외 또는 별도 처리** (P22 준수).
4. **UI에서 미수신 종목이 일관되게 "-"로 표시** (P21 사용자 투명성 준수).

---

## 2. 사전조사 결과 (수정 영향 범위 전수 조사)

### 2-1. `parse_change_rate_to_percent` 호출처 (프로덕션 코드 2곳)

| 호출처 | 파일:줄 | 경로 | None 반환 시 영향 |
|---|---|---|---|
| 틱 처리 (보유종목) | `pipeline_compute.py:576` | 틱 수신 | `rate`가 None → `_dr_pos["change_rate"] = None` 저장. UI에서 "-" 표시. |
| 틱 처리 (레이더) | `engine_radar.py:75` | 틱 수신 | `entry["change_rate"] = None` 저장. 수신률 계산에서 미수신으로 카운트. |

**결론**: 두 호출처 모두 틱 수신 경로이므로, None 반환으로 변경해도 REST 잔고 경로에 영향 없음.

### 2-2. `_parse_float_loose` 호출처 (프로덕션 코드 6곳)

| 호출처 | 파일:줄 | 경로 | None 반환 시 영향 |
|---|---|---|---|
| 틱 처리 (레이더) | `engine_radar.py:77` | 틱 수신 | `entry["trade_amount"] = None` 저장. 수신률 계산에서 미수신으로 카운트. |
| REST 잔고 (total_rate) | `engine_account_rest.py:144` | REST | `out["total_rate"] = None`. 계좌 요약에 영향. |
| REST 잔고 (pnl_rate) | `engine_account_rest.py:174` | REST | `pnl_rate = None`. 보유종목 평가에 영향. |
| REST 잔고 (total_rate) | `engine_account_rest.py:355` | REST | `total_rate = None`. 계좌 요약에 영향. |
| REST 잔고 (_rate) | `engine_account_rest.py:369` | REST | `_rate = None`. 보유종목 평가에 영향. |
| REST 잔고 (_hold_ratio) | `engine_account_rest.py:379` | REST | `_hold_ratio = None`. 보유종목 비율에 영향. |

**결론**: `_parse_float_loose` 자체를 None 반환으로 변경하면 REST 잔고 경로 5곳에 영향. 따라서 **`_parse_float_loose` 자체는 변경하지 않고**, 틱 수신 경로(`engine_radar.py:77`)에서만 빈 값 체크 후 None 저장.

### 2-3. `_parse_int_loose` 호출처

`_parse_int_loose`는 `engine_account_rest.py` 내 REST 잔고 파싱에만 사용 (틱 수신 경로에서 사용 안 함). P-001과 무관. **변경하지 않음**.

### 2-4. 확정 데이터 경로 (참고 — P-001과 간접적만 관련)

| 코드 경로 | 패턴 | 비고 |
|---|---|---|
| `daily_time_scheduler.py:987-1010` (`_apply_detail_to_entry`) | "0값은 덮지 않음" (`if rate != 0.0:`, `if amt > 0:`) | 보수적 패턴. 0을 미수신으로 취급. |
| `market_close_pipeline.py:471-491` (`apply_confirmed_to_cache` 엔트리 존재 시) | 무조건 덮기 (`entry["change_rate"] = rate`) | P23 일관성 위반 (두 경로 패턴 불일치). |

**결론**: 확정 데이터 경로는 장마감 후에만 실행되므로, 장중 수신률 왜곡에는 영향을 주지 않음. 단, `market_close_pipeline.py`의 무조건 덮기 패턴은 별도 P23 이슈로 기록.

### 2-5. `sector_calculator.py` 폴백 (2차 왜곡 원인)

| 코드 경로 | 현재 코드 | 문제 |
|---|---|---|
| `sector_calculator.py:69` | `change_rate = float(detail.get("change_rate", 0) or 0)` | None을 0.0으로 폴백. 원인 A 수정 후에도 여전히 0이 점수에 섞임. |
| `sector_calculator.py:78` | `ta = int(detail.get("trade_amount", 0) or 0)` | None을 0으로 폴백. 동일. |

**결론**: 원인 A 수정만으로는 업종 점수 왜곡이 해결되지 않음. `sector_calculator.py`에서도 None을 0으로 폴백하지 않도록 수정 필요.

### 2-6. `trading.py` None 처리 (안전)

| 코드 경로 | 현재 코드 | None 처리 |
|---|---|---|
| `trading.py:218-219` | `_change_rate = state.master_stocks_cache.get(stk_cd, {}).get("change_rate")` 후 `if _change_rate is not None:` | None이면 등락률 가드 체크 스킵. **이미 None 안전**. |

**결론**: `trading.py`는 원인 A 수정 후 자연스럽게 올바르게 동작. 수정 불필요.

### 2-7. 프론트엔드 None 처리 (안전)

| 코드 경로 | 현재 코드 | None 처리 |
|---|---|---|
| `buy-target.ts:33` | `t.change_rate != null ? Number(t.change_rate) : null` | null → "-" 표시. **이미 null 안전**. |
| `sector-stock.ts:31,34` | `item.stock.change_rate != null ? Number(item.stock.change_rate) : null` | 동일. |
| `hotStore.ts:460` | `nullifyFields(stock, ['cur_price', 'change', 'change_rate', ...])` | WS 구독 시작 시 프론트엔드에서도 null 초기화. |

**결론**: 프론트엔드는 백엔드에서 None을 보내면 자동으로 "-" 표시. **수정 불필요**.

### 2-8. 보유종목 평가 경로 (안전)

| 코드 경로 | 현재 코드 | None 처리 |
|---|---|---|
| `dry_run.py:220-232` (`_recalc_pnl`) | `cur = int(pos.get("cur_price") or avg)` | cur_price가 None이면 avg(매입가) 사용. change_rate 미사용. |
| `engine_snapshot.py:163-177` (`_reset_realtime_fields`) | `pos["change_rate"] = None` | WS 구독 시작 시 None 초기화. |

**결론**: 보유종목 평가는 change_rate를 직접 사용하지 않으므로 안전. 단, `pipeline_compute.py:584`에서 `_dr_pos["change_rate"] = rate`에 None이 저장될 수 있으며, 이는 UI에서 "-"로 표시됨 (정상 동작).

### 2-9. `notify_desktop_trade_price` / `notify_raw_real_data` (dead code)

- `notify_desktop_trade_price` (`engine_account_notify.py:350`): 프로덕션 호출처 없음. 테스트에서만 호출.
- `notify_raw_real_data` (`engine_account_notify.py:385`): 프로덕션 호출처 없음. 테스트에서만 호출.

**결론**: P-001 수정과 무관. 별도 P16(살아있는 경로) 이슈로 기록.

---

## 3. 수정 방안

### 3-1. 핵심 설계 결정

#### 결정 1: `parse_change_rate_to_percent` / `_parse_float_loose` 자체를 변경하지 않음

**이유**: `_parse_float_loose`는 REST 잔고 경로 5곳에서 사용. 자체를 None 반환으로 변경하면 REST 경로 전체에 영향. 대신 **틱 수신 경로에서만 빈 값 체크 후 None 저장**.

`parse_change_rate_to_percent`는 호출처 2곳 모두 틱 경로이므로 자체 변경도 가능하지만, 일관성(P23)을 위해 `_parse_float_loose`와 동일하게 호출부에서 처리.

#### 결정 2: 원인 A(폴백 제거)를 먼저 수정, 원인 B는 `is not None` 체크 유지

**이유**: HANDOVER.md의 세션 분할 추천(1단계=원인 B, 2단계=원인 A)은 **치명적 결함**이 있음:
- 원인 B를 먼저 수정하여 `!= 0` 체크를 추가하면, **정상 수신된 0% 등락률**을 미수신으로 오분류함.
- 장 시작 직후 등락률 0%는 정상 데이터이며, 이를 미수신으로 처리하면 수신률이 과소 산출되는 **새로운 왜곡** 발생.
- 원인 A를 먼저 수정하면 틱 수신 경로에서 빈 값이 None으로 저장되므로, 기존 `is not None` 체크만으로 0과 None이 정확히 구분됨.

#### 결정 3: "빈 문자열"과 "0"을 구분

**이유**: FID 값이 빈 문자열(`""`)이면 미수신, `"0"`이면 정상 0%로 처리해야 함.
- 빈 문자열 → None 저장 (미수신)
- `"0"` → `parse_change_rate_to_percent("0")` → `0.0` 저장 (정상 수신)
- `"1.5"` → `1.5` 저장 (정상 수신)

#### 결정 4: `sector_calculator.py`에서 None을 0으로 폴백하지 않음

**이유**: 원인 A 수정으로 `master_stocks_cache`에 None이 저장되어도, `sector_calculator.py:69,78`에서 `or 0` 폴백으로 다시 0이 되면 왜곡이 해결되지 않음. None인 종목은 점수 계산에서 제외해야 함.

### 3-2. 세션 분할 (3단계)

> **규칙 0-1 (세션당 1단계 원칙) 준수**: 각 단계는 별도 세션에서 진행.

| 단계 | 세션 | 수정 범위 | 영향 범위 | 위험도 |
|---|---|---|---|---|
| Step 1 | 세션 1 | `engine_radar.py:73-77` (틱 수신 폴백 제거) | 틱 수신 경로만. 좁음. | 낮음 |
| Step 2 | 세션 2 | `pipeline_compute.py:576` (보유종목 틱 폴백 제거) + `_has_any_realtime_data` 검증 | 틱 수신 + 수신률 계산. 중간. | 중간 |
| Step 3 | 세션 3 | `sector_calculator.py:69,78` (업종 점수 폴백 제거) | 업종 점수 계산. 넓음. | 높음 |

---

## 4. 단계별 수정 상세

### Step 1: 틱 수신 경로 폴백 제거 — `engine_radar.py`

> **세션**: 1
> **수정 파일**: `backend/app/services/engine_radar.py`
> **영향 범위**: 틱 수신 시 `master_stocks_cache`의 `change_rate`, `trade_amount` 필드만.

#### 4-1-1. 수정 대상: `engine_radar.py:73-77`

**변경 전**:
```python
if "12" in vals:
    from backend.app.services.engine_ws_parsing import parse_change_rate_to_percent
    entry["change_rate"] = parse_change_rate_to_percent(vals["12"])
if "14" in vals:
    entry["trade_amount"] = int(_parse_float_loose(vals["14"]))
```

**변경 후**:
```python
if "12" in vals:
    from backend.app.services.engine_ws_parsing import parse_change_rate_to_percent
    _raw12 = str(vals["12"]).strip()
    if _raw12:
        entry["change_rate"] = parse_change_rate_to_percent(vals["12"])
    # 빈 문자열이면 None 유지 (미수신 — P20 폴백 금지)
if "14" in vals:
    _raw14 = str(vals["14"]).strip()
    if _raw14:
        entry["trade_amount"] = int(_parse_float_loose(vals["14"]))
    # 빈 문자열이면 None 유지 (미수신 — P20 폴백 금지)
```

#### 4-1-2. 연쇄 영향 조사

| 확인 항목 | 결과 |
|---|---|
| `entry["change_rate"]`를 읽는 곳 | `sector_calculator.py:69`, `trading.py:218`, `_has_any_realtime_data` — 모두 None 처리 가능 또는 Step 3에서 수정. |
| `entry["trade_amount"]`를 읽는 곳 | `sector_calculator.py:78`, `get_trade_amount_cache()` (`engine_radar.py:18`), `_has_any_realtime_data` — `get_trade_amount_cache`는 `int(... or 0)` 폴백 사용. |
| `parse_change_rate_to_percent` 자체 | 변경하지 않음. 빈 문자열 체크는 호출부에서 수행. |
| `_parse_float_loose` 자체 | 변경하지 않음. 빈 문자열 체크는 호출부에서 수행. |
| REST 잔고 경로 | 영향 없음. |

#### 4-1-3. 검증 방법

1. **단위 테스트**: `test_engine_ws_parsing.py`의 기존 테스트 통과 확인 (파서 자체 미변경).
2. **단위 테스트 (신규)**: `engine_radar.py`의 `_apply_real01_volume_amount_to_radar_rows`에 대해:
   - FID 12 = 빈 문자열 → `entry["change_rate"]`가 None 유지.
   - FID 12 = "0" → `entry["change_rate"]`가 `0.0`.
   - FID 12 = "1.5" → `entry["change_rate"]`가 `1.5`.
   - FID 14 = 빈 문자열 → `entry["trade_amount"]`가 None 유지.
   - FID 14 = "1000" → `entry["trade_amount"]`가 `1000`.
3. **런타임 기동**: `.venv/bin/python main.py` 테스트모드 기동, 10-30초 대기 후 로그 확인.
4. **잔존 프로세스 정리**: `ps aux | grep python | grep -v grep`로 0건 확인.

---

### Step 2: 보유종목 틱 폴백 제거 + 수신률 판정 검증 — `pipeline_compute.py`

> **세션**: 2
> **수정 파일**: `backend/app/pipelines/pipeline_compute.py`
> **영향 범위**: 보유종목 틱 처리 + 수신률 계산.

#### 4-2-1. 수정 대상 A: `pipeline_compute.py:576`

**변경 전**:
```python
rate = parse_change_rate_to_percent(_ws_fid_raw(vals, "12")) if _ws_fid_key_present(vals, "12") else 0.0
```

**변경 후**:
```python
_raw12 = _ws_fid_raw(vals, "12") if _ws_fid_key_present(vals, "12") else ""
rate = parse_change_rate_to_percent(_raw12) if _raw12 and str(_raw12).strip() else None
```

**영향**: `rate`가 None이면 `_dr_pos["change_rate"] = None` (pipeline_compute.py:584). UI에서 "-" 표시. `_recalc_pnl`은 change_rate 미사용이므로 평가에 영향 없음.

#### 4-2-2. 수정 대상 B: `_has_any_realtime_data` (`pipeline_compute.py:91-97`) — 검증만 수행

**변경 없음**. Step 1 완료 후 틱 수신 경로에서 빈 값이 None으로 저장되므로, 기존 `is not None` 체크가 정상 동작함:
- None → 미수신 (카운트 제외)
- `0.0` → 정상 수신된 0% (카운트 포함)
- `1.5` → 정상 수신 (카운트 포함)

**검증**: 단위 테스트로 None/0.0/1.5 각 케이스에 대한 수신률 카운트 확인.

#### 4-2-3. 연쇄 영향 조사

| 확인 항목 | 결과 |
|---|---|
| `rate`를 사용하는 곳 | `pipeline_compute.py:584` (`_dr_pos["change_rate"] = rate`). None 저장 시 UI "-" 표시. |
| `_dr_pos`의 change_rate를 읽는 곳 | 프론트엔드 `sell-position.ts` — `!= null` 체크로 안전. |
| `_has_any_realtime_data` | 변경 없음. Step 1 후 정상 동작. |
| `_calculate_receive_rate` | 변경 없음. `_has_any_realtime_data` 결과에 의존. |

#### 4-2-4. 검증 방법

1. **단위 테스트 (신규)**: `_has_any_realtime_data`에 대해:
   - `change_rate=None, trade_amount=None` → False (미수신).
   - `change_rate=0.0, trade_amount=None` → True (정상 수신 0%).
   - `change_rate=None, trade_amount=1000` → True (정상 수신).
   - `change_rate=0.0, trade_amount=0` → True (정상 수신 0%/0원).
2. **단위 테스트 (신규)**: `_calculate_receive_rate`에 대해:
   - 일부 종목만 None → 수신률이 100% 미만.
   - 전체 종목이 None → 수신률 0%.
3. **런타임 기동**: 테스트모드 기동, 수신률이 100%가 아닌 실제 비율로 표시되는지 로그 확인.
4. **잔존 프로세스 정리**: 0건 확인.

---

### Step 3: 업종 점수 계산 폴백 제거 — `sector_calculator.py`

> **세션**: 3
> **수정 파일**: `backend/app/domain/sector_calculator.py`
> **영향 범위**: 업종 점수 계산 전체. 가장 넓은 영향.

#### 4-3-1. 수정 대상: `sector_calculator.py:60-78`

**변경 전**:
```python
# 현재가 조회
cur_price = int(trade_prices.get(code, 0) or 0)
detail = state.master_stocks_cache.get(code, {})

if cur_price <= 0:
    cur_price = int(detail.get("cur_price", 0) or 0)
# cur_price 0도 유효한 데이터 -- WS 틱 미수신 상태일 뿐, 스킵하지 않음

# 등락률: master_stocks_cache(change_rate) 사용 (단일 소스 진리)
change_rate = float(detail.get("change_rate", 0) or 0)

# 전일 대비 (원)
change = int(detail.get("change", 0) or 0)

# 거래대금 (원 단위) - WS 틱 우선, master_stocks_cache trade_amount fallback
ta_ws = int(trade_amounts.get(code, 0) or 0)
ta = ta_ws
if ta <= 0:
    ta = int(detail.get("trade_amount", 0) or 0)
```

**변경 후**:
```python
# 현재가 조회
cur_price = int(trade_prices.get(code, 0) or 0)
detail = state.master_stocks_cache.get(code, {})

if cur_price <= 0:
    cur_price = int(detail.get("cur_price", 0) or 0)

# 등락률: master_stocks_cache(change_rate) 사용 (단일 소스 진리)
# None = 실시간 데이터 미수신 — 0으로 폴백하지 않고 None 유지 (P20/P22)
_change_rate_raw = detail.get("change_rate")
change_rate = float(_change_rate_raw) if _change_rate_raw is not None else None

# 전일 대비 (원)
change = int(detail.get("change", 0) or 0)

# 거래대금 (원 단위) - WS 틱 우선, master_stocks_cache trade_amount fallback
# None = 실시간 데이터 미수신 — 0으로 폴백하지 않고 None 유지 (P20/P22)
ta_ws = int(trade_amounts.get(code, 0) or 0)
ta = ta_ws
if ta <= 0:
    _ta_raw = detail.get("trade_amount")
    ta = int(_ta_raw) if _ta_raw is not None else None
```

#### 4-3-2. 하위 로직 수정: 미수신 종목 제외

`change_rate` 또는 `trade_amount`가 None인 종목은 업종 점수 계산에서 제외해야 함. `sector_calculator.py:101-114`의 `StockScore` 생성 전에 필터 추가:

**변경 전** (sector_calculator.py:101-114):
```python
stocks.append(StockScore(
    code=code,
    name=str(name),
    sector=sector,
    change_rate=change_rate,
    trade_amount=ta,
    ...
))
```

**변경 후**:
```python
# 미수신 종목(change_rate 또는 trade_amount가 None)은 업종 점수 계산에서 제외 (P22)
if change_rate is None or ta is None:
    continue

stocks.append(StockScore(
    code=code,
    name=str(name),
    sector=sector,
    change_rate=change_rate,
    trade_amount=ta,
    ...
))
```

#### 4-3-3. 연쇄 영향 조사

| 확인 항목 | 결과 |
|---|---|
| `StockScore.change_rate` 타입 | `float`에서 `float \| None`로 변경 가능성. 단, 제외 필터 추가 후에는 None이 StockScore에 들어가지 않음. |
| `sector_calculator.py:129` (`raw_rise_count`) | 제외 필터 후 0으로 폴백된 종목이 없으므로 정상 동작. |
| `sector_calculator.py:132-134` (`avg_ta`, `avg_cr`) | 동일. 미수신 종목이 제외되므로 평균 왜곡 해결. |
| `sector_score.py:106-107,112-113,142` | 상위에서 None이 제거된 데이터만 들어오므로 수정 불필요. |
| `filtered_stocks` (sector_calculator.py:120-123) | 5일평균거래대금 필터. 미수신 종목 제외 후에도 동일 로직 적용. |
| 업종별 종목 수 (`raw_total`) | 미수신 종목 제외로 종목 수가 감소할 수 있음. 이는 정상 — 수신된 종목 기준으로 점수 계산. |
| UI 표시 | 업종 순위 리스트에서 미수신 종목이 제외되어 표시. 사용자에게 투명 (P21). |

#### 4-3-4. 검증 방법

1. **단위 테스트 (신규)**: `sector_calculator.py`에 대해:
   - 일부 종목 `change_rate=None` → 해당 종목이 `stocks`에서 제외.
   - 일부 종목 `trade_amount=None` → 해당 종목이 `stocks`에서 제외.
   - 전체 종목 `change_rate=None` → `stocks`가 빈 리스트 → `if not stocks: continue` 분기.
2. **단위 테스트 (기존)**: `test_sector_calculator.py` 기존 테스트 통과 확인.
3. **런타임 기동**: 테스트모드 기동, 업종 점수가 0 왜곡 없이 계산되는지 로그 확인.
4. **UI 확인**: 업종 순위 화면에서 미수신 종목이 제외되고, 수신된 종목 기준으로 순위가 표시되는지 확인.
5. **잔존 프로세스 정리**: 0건 확인.

---

## 5. 전체 검증 항목 (모든 Step 완료 후)

### 5-1. 백엔드 검증

| 항목 | 방법 | 기대 결과 |
|---|---|---|
| 틱 수신 빈 값 | 단위 테스트 | 빈 문자열 → None 저장, "0" → 0.0 저장. |
| 수신률 계산 | 단위 테스트 + 런타임 | 미수신 종목이 수신률에서 제외. 100% 왜곡 해결. |
| 업종 점수 | 단위 테스트 + 런타임 | 미수신 종목이 점수 계산에서 제외. 0 왜곡 해결. |
| 등락률 가드 | 런타임 | `trading.py:218`에서 None이면 가드 스킵 (이미 안전). |

### 5-2. 프론트엔드 검증 (UI 확인)

| 항목 | 화면 | 기대 결과 |
|---|---|---|
| 미수신 종목 등락률 | 매수 후보, 업종별 종목 | "-" 표시 (백엔드에서 None 전송 시). |
| 미수신 종목 거래대금 | 매수 후보, 업종별 종목 | "-" 표시. |
| 수신률 표시 | 업종 순위 화면 | 실제 수신 비율 표시 (100% 왜곡 해결). |
| 업종 순위 | 업종 순위 화면 | 미수신 종목 제외 후 순위 표시. |

### 5-3. 런타임 검증

- `.venv/bin/python main.py` 테스트모드 기동 후 10-30초 대기.
- 로그에서 수신률이 100%가 아닌 실제 비율로 표시되는지 확인.
- 잔존 프로세스 0건 확인 후 세션 종료.

---

## 6. 위험 분석 및 대응

### 6-1. 위험: 미수신 종목 제외 시 업종별 종목 수 급감

**상황**: WS 구독 직후 대부분의 종목이 미수신 상태. `sector_calculator.py`에서 미수신 종목을 제외하면 `filtered_stocks`가 빈 리스트가 될 수 있음.

**대응**: `sector_calculator.py:116-117`의 `if not stocks: continue` 분기가 이미 존재. 빈 리스트면 해당 업종의 점수 계산을 스킵. 수신률 임계값 게이트(`pipeline_compute.py:716`)가 충족된 후에만 업종순위 계산이 시작되므로, 충분한 종목이 수신된 후에만 점수가 계산됨.

### 6-2. 위험: `get_trade_amount_cache()`의 None 처리

**상황**: `engine_radar.py:18` — `get_trade_amount_cache()`가 `int(stock.get("trade_amount", 0) or 0)`로 None을 0으로 폴백.

**대응**: 이 함수는 `sector_calculator.py:75`의 `trade_amounts.get(code, 0)` 경로로 사용됨. `sector_calculator.py:76-78`에서 `ta_ws = int(trade_amounts.get(code, 0) or 0)` → 0, `if ta <= 0:` → `detail.get("trade_amount")`에서 None 확인. Step 3 수정으로 None이 유지되므로 정상 동작.

### 6-3. 위험: 기존 테스트 실패

**상황**: `test_engine_ws_parsing.py:295` — `assert parse_change_rate_to_percent(None) == 0.0`. 파서 자체는 변경하지 않으므로 이 테스트는 통과함.

**대응**: `test_engine_account_rest.py:61` — `assert _parse_float_loose(None) == 0.0`. 동일하게 파서 자체 미변경으로 통과. 신규 테스트는 호출부(`engine_radar.py`, `pipeline_compute.py`)의 빈 값 처리를 검증.

---

## 7. 관련 원칙 준수 체크리스트

### Step 1 (`engine_radar.py`)

- [ ] **P20 (폴백 금지)**: 빈 문자열을 0으로 폴백하지 않고 None 유지.
- [ ] **P22 (데이터 정합성)**: 미수신 데이터가 0이 아닌 None으로 저장.
- [ ] **P23 (일관성)**: `parse_change_rate_to_percent`/`_parse_float_loose` 자체 미변경으로 REST 경로 일관성 유지.
- [ ] **P24 (단순성)**: 빈 문자열 체크 2줄 추가. 복잡도 증가 최소.

### Step 2 (`pipeline_compute.py`)

- [ ] **P20 (폴백 금지)**: FID 12 키 없을 때 0.0이 아닌 None 할당.
- [ ] **P22 (데이터 정합성)**: `_has_any_realtime_data`가 None과 0을 정확히 구분.
- [ ] **P21 (사용자 투명성)**: 수신률이 실제 비율로 표시되어 사용자에게 투명.

### Step 3 (`sector_calculator.py`)

- [ ] **P20 (폴백 금지)**: None을 0으로 폴백하지 않음.
- [ ] **P22 (데이터 정합성)**: 미수신 종목을 점수 계산에서 제외.
- [ ] **P21 (사용자 투명성)**: 업종 순위가 미수신 종목 왜곡 없이 표시.
- [ ] **P24 (단순성)**: None 체크 + `continue` 2줄 추가. 복잡도 증가 최소.

---

## 8. HANDOVER.md 원안 대비 변경 사항

| 항목 | HANDOVER 원안 | 본 계획서 | 이유 |
|---|---|---|---|
| 세션 분할 순서 | 1단계=원인 B, 2단계=원인 A | 1단계=원인 A(틱), 2단계=원인 B(검증), 3단계=점수 | 원인 B 먼저 시 정상 0% 오분류 발생. |
| 원인 B 판정식 | `is not None and != 0` | `is not None` 유지 | 원인 A 수정 후 None이 저장되므로 `!= 0` 불필요. |
| `parse_change_rate_to_percent` 변경 | None 반환으로 변경 | 변경하지 않음 | REST 경로 호환성. 호출부에서 빈 값 체크. |
| `_parse_float_loose` 변경 | None 반환으로 변경 | 변경하지 않음 | REST 경로 5곳 영향. 호출부에서 빈 값 체크. |
| `sector_calculator.py` | 수정 방안에 미포함 | Step 3로 추가 | None을 0으로 폴백하여 2차 왜곡 발생. |
| 단계 수 | 2단계 | 3단계 | `sector_calculator.py` 수정 추가. |

---

## 9. 추후 검토 사항 (P-001 범위 외)

| 항목 | 관련 원칙 | 비고 |
|---|---|---|
| `market_close_pipeline.py:471-491` 무조건 덮기 패턴 | P23 (일관성) | `daily_time_scheduler.py`의 "0값은 덮지 않음" 패턴과 불일치. 별도 이슈. |
| `notify_desktop_trade_price` / `notify_raw_real_data` dead code | P16 (살아있는 경로) | 프로덕션 호출처 없음. 별도 이슈. |
| `trading.py:218` None 시 등락률 가드 스킵 | P21 (사용자 투명성) | 미수신 종목 매수 허용 여부 별도 검토. |
| `engine_radar.py:18` `get_trade_amount_cache()` None 폴백 | P20 (폴백 금지) | `int(stock.get("trade_amount", 0) or 0)` — None을 0으로 폴백. 별도 검토. |

---

## 10. 참조 코드 경로 요약

| 파일 | 줄 | 설명 |
|---|---|---|
| `engine_snapshot.py` | 144-160 | `_reset_realtime_fields` — WS 구독 시작 시 None 초기화. |
| `engine_radar.py` | 73-77 | 틱 수신 FID 12/14 처리 — Step 1 수정 대상. |
| `pipeline_compute.py` | 91-97 | `_has_any_realtime_data` — Step 2 검증 대상. |
| `pipeline_compute.py` | 118-126 | `_calculate_receive_rate` — 수신률 계산. |
| `pipeline_compute.py` | 576 | 보유종목 틱 rate — Step 2 수정 대상. |
| `pipeline_compute.py` | 704-722 | 수신률 임계값 게이트 — 업종순위 계산 시작. |
| `sector_calculator.py` | 60-114 | 업종 점수 계산 — Step 3 수정 대상. |
| `sector_calculator.py` | 129-135 | rise_ratio, avg_ta, avg_cr 계산 — 왜곡 경로. |
| `sector_score.py` | 106-142 | 1차/2차/3차 가산점 — 왜곡 전파 경로. |
| `trading.py` | 218-231 | 등락률 가드 — None 안전 (수정 불필요). |
| `engine_ws_parsing.py` | 150-167 | `parse_change_rate_to_percent` — 변경하지 않음. |
| `engine_account_rest.py` | 18-23 | `_parse_float_loose` — 변경하지 않음. |
| `daily_time_scheduler.py` | 987-1010 | `_apply_detail_to_entry` — "0값은 덮지 않음" 패턴 (참고). |
| `market_close_pipeline.py` | 471-491 | `apply_confirmed_to_cache` — 무조건 덮기 패턴 (별도 이슈). |
