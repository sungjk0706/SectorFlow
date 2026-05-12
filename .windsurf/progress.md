# 진행 중인 작업 인계서

## 날짜: 2026-05-12 20:57 KST

---

## 이번 세션 완료한 수정

### 1. 전종목 확정시세 다운로드 날짜 오류 수정 ✅
**파일**: `backend/app/services/market_close_pipeline.py:608`
- **문제**: 오후 8시 이후 `current_trading_date_str()`가 다음 거래일을 반환 → API에 내일 날짜로 시세 요청 → 빈 데이터 반환
- **수정**: `qry_dt = kst_today_str()` 로 변경 (오늘 날짜 고정)

### 2. 오후 8시 구독 종료 시 확정 갱신 완료 표시 초기화 누락 수정 ✅
**파일**: `backend/app/services/daily_time_scheduler.py:713,722`
- **문제**: 오후 8시 실시간 구독 종료 시 확정 갱신 완료 표시가 초기화되지 않아 오후 8시 30분 갱신이 스킵됨
- **수정**: `_on_ws_subscribe_end()` global에 `_confirmed_done` 추가 + `_confirmed_done = False` 초기화

### 3. 5일 차트 갱신 오류 수정 ✅
**파일**: `backend/app/services/engine_bootstrap.py:579-589`
- **문제**: 존재하지 않는 `get_real_industry_codes` 함수 참조 → 매 기동 시 오류 후 60초 재시도
- **수정**: 해당 import 및 호출 블록 전체 제거 (이후 코드에서 미사용)

### 4. 앱준비 재실행 시 화면 로딩 오버레이 미해제 — 미해결 🔴

#### 현상
장마감 후 기동 시 매매적격종목 캐시 만료 → 앱준비 2번 실행 → 화면 "로딩 중..." 오버레이가 풀리지 않음  
(확정시세 다운로드 진행 칩은 상단에 보임)

#### 오버레이 조건 (`main.ts:154~159`)
```
settings === null  → "로딩 중..."
engineReady===false → "엔진 초기화 중..."
둘 다 아님 → 오버레이 해제
```

#### 트리거 흐름
```
engine_loop.py:244~258
  매매적격종목 캐시 만료 → ka10099 다운로드 → _bootstrap_sector_stocks_async() 재호출
    engine_bootstrap.py:53: _bootstrap_event.clear()  ← engineReady false
    engine_bootstrap.py:54: _sector_summary_ready_event.clear()
      ws.py:_send_stocks_delayed(): _sector_summary_ready_event.wait(timeout=120s) 재대기
        → 120초 동안 sector-stocks-refresh 미전송 → 화면 빈 상태 유지
```

#### 시도한 수정 (모두 효과 없음)
1. `engine_bootstrap.py:53~56`: `_already_ready=True`이면 `_bootstrap_event.clear()` 스킵 → 효과 없음
2. `engine_loop.py:259~264`: 2번째 앱준비 완료 후 `engine-ready` 재전송 추가 → 효과 없음  
3. `engine_bootstrap.py:53~56`: `_already_ready=True`이면 `_sector_summary_ready_event.clear()`도 스킵 → **현재 코드 상태, 미확인**

#### 현재 코드 상태 (`engine_bootstrap.py:53~56`)
```python
_already_ready = _st._bootstrap_event.is_set()
if not _already_ready:
    _st._bootstrap_event.clear()
    _st._sector_summary_ready_event.clear()
```

#### 다음 세션 조사 방향
1. 수정 3번(`_sector_summary_ready_event` clear 스킵)이 실제로 효과 있는지 재기동으로 확인
2. 효과 없으면: `_send_stocks_delayed`가 WS 연결 시 1회만 실행되는데, 2번째 앱준비 완료 후 업종목록/업종점수를 다시 broadcast하는 로직이 필요한지 검토
3. 근본 해결책 후보: `engine_loop.py:244~258`에서 2번째 앱준비 재실행 자체를 없애고, 매매적격종목만 갱신 후 필요한 데이터만 incremental 업데이트하는 방식으로 변경

---

## 날짜: 2026-05-12 19:51 KST

---

## 이번 세션 (2026-05-12 19:51) 조사 결과 및 수정 내역

### 조사 요약: 기동 후 실시간 데이터 수신 지연 원인

#### 확인된 사실
1. **`handle_ws_data_async` 오류** (nohup.out 09:29 기록)
   - 소스코드에 해당 함수명 없음 → 구버전 `.pyc` 캐시 잔재로 1회 발생
   - 현재 실행 중인 앱에서는 전혀 발생하지 않음 → **무시해도 됨**

2. **실시간 필드 초기화 원인**
   - `_reset_realtime_fields()` 가 기동 시 + WS 구독 구간 진입 시 호출됨
   - 모든 종목 `cur_price = None` 초기화 → 이후 틱이 와야만 채워짐
   - **이건 정상 설계** (전날 가격 오염 방지 목적)

3. **기동 후 첫 틱까지 3.2초** (19:45:01 구독완료 → 19:45:05 첫틱)
   - 정상 범위

4. **NXT 시간외 거래 틱 간격 수십 초**
   - 단일가 방식이므로 체결이 드물어 틱 자체가 드문 것 — **정상**

#### 발견·수정한 버그 ✅
**파일**: `backend/app/services/dry_run.py`

| 위치 | 버그 | 수정 |
|------|------|------|
| `_recalc_pnl()` line 267 | `int(pos.get("cur_price", avg))` → `cur_price=None`이면 `int(None)` 오류 | `int(pos.get("cur_price") or avg)` |
| `sell_position()` line 259 | 동일 패턴 | 동일 수정 |

**영향**: 기동 직후 `cur_price=None` 상태에서 틱이 오면 오류로 버려짐 → 수십 초간 현재가 미업데이트처럼 보임. 수정 후 해결됨.

#### 남아있는 DEBUG 로그 (제거 필요)
`engine_account_notify.py` line 316-322:
```python
if nk == "032830":
    logger.info("[DEBUG] 032830 _is_relevant_code check: ...")
```
→ **다음 세션 시작 시 제거할 것**

---

## 이전 세션: 실시간 데이터 필드 null 초기화 완료 ✅

### 완료한 작업

#### 1. 백엔드 수정 (`engine_service.py:466-481`)
| 항목 | 수정 전 | 수정 후 |
|:---|:---|:---|
| 실전 보유종목 | `cur_price = 0` | `cur_price = None` |
| 테스트모드 가상보유 | 초기화 없음 | `cur_price = None`, `change = None`, `change_rate = None` |
| 업종점수 캐시 | 초기화 없음 | `_sector_summary_cache = None` |
| 매수후보 캐시 | 초기화 없음 | `_buy_targets_snapshot_cache = None` |

#### 2. 백엔드 버그 수정 (`dry_run.py:287`)
- **문제**: `update_price()`에서 `cur_price=None`일 때 `int(None)` 에러
- **수정**: null 체크 추가
```python
# 수정 전
if int(pos.get("cur_price", 0)) == price:

# 수정 후
cur_price = pos.get("cur_price")
if cur_price is not None and int(cur_price) == price:
```

#### 3. 프론트엔드 수정 (`ui-styles.ts`)
| 함수 | 수정 내용 |
|:---|:---|
| `createPriceCell` | `number \| null \| undefined` → `!price` 시 "-" 표시 |
| `createRateCell` | null 시 "-" 표시 |
| `createStrengthCell` | null 시 "-" 표시 |
| `createAmountCell` | null 시 "-" 표시 |
| `makePriceColumn` | getter 타입 수정 |
| `makeRateColumn` | getter 타입 수정 |
| `makeStrengthColumn` | getter 타입 수정 |
| `makeAmountColumn` | getter 타입 수정 |

### 테스트 결과
- 앱 재기동 시 보유종목 `cur_price=None` 정상 초기화 확인
- 로그: `[실시간연결] 계좌화면전송 사유=realtime_reset 총평가=None 보유현재가=[('032830', None), ...]`

---

## 다음 세션에서 조사할 문제

### 프론트엔드 콘솔 경고

#### 1. 404 Not Found
```
Failed to load resource: the server responded with a status of 404 (Not Found)
```
- **위치**: `main.ts:188`
- **원인 추정**: 정적 리소스 파일 누락 또는 경로 문제

#### 2. real-data 네트워크 지연 경고
```
binding.ts:227 [WS] real-data 처리 지연: 5.40ms 011170_AL
binding.ts:230 [WS] real-data 네트워크 지연: 78ms 011170_AL
binding.ts:230 [WS] real-data 네트워크 지연: 80ms 247540_AL
binding.ts:230 [WS] real-data 네트워크 지연: 80ms 373220_AL
binding.ts:230 [WS] real-data 네트워크 지연: 81ms 005930_AL
binding.ts:230 [WS] real-data 네트워크 지연: 81ms 086520_AL
```

**코드 위치**: `frontend/src/binding.ts:227-230`
```typescript
// line 227
const now = performance.now()
const processDelay = now - payload._ts
if (processDelay > 5) {
  console.warn(`[WS] real-data 처리 지연: ${processDelay.toFixed(2)}ms ${item}`)
}

// line 230
const networkDelay = now - (payload._server_ts || 0)
if (networkDelay > 50) {
  console.warn(`[WS] real-data 네트워크 지연: ${networkDelay.toFixed(0)}ms ${item}`)
}
```

**해석**:
- **처리 지연 5.40ms**: 프론트엔드에서 메시지 수신 후 처리까지 5ms 이상 소요
- **네트워크 지연 78-81ms**: 백엔드 전송 시각(_server_ts)부터 프론트 수신까지 78ms 이상 소요
- **임계값**: 처리 지연 >5ms, 네트워크 지연 >50ms 시 경고 출력

**다음 세션 조사 방향**:
1. 네트워크 지연이 정상적인 WS 지연인지, 아니면 서버 처리 지연이 포함된 것인지 확인
2. `_server_ts`가 백엔드에서 언제 찍히는지 확인 (`ws_manager.py` 또는 `engine_ws_dispatch.py`)
3. 78-81ms 지연이 사용자 환경에서 문제가 되는 수준인지 판단 (일반적으로 100ms 미만은 양호)

---

## 이전 세션 내용

## 날짜: 2026-05-12 18:21 KST

---

## 이번 세션에서 완료한 수정

### 1. 프론트엔드 렌더링 버그 수정 (근본해결) ✅
**파일**: `frontend/src/stores/appStore.ts`
**내용**: `splice`로 `positions`/`buyTargets` 원본 배열을 변이(mutation)하던 버그 수정.
가상 스크롤러의 `oldItems[i] !== newItems[i]` 비교가 항상 같음을 반환해 `renderRow` 미호출됨.
**수정**: `[...positions]` 새 배열 복사 후 인덱스 대입으로 변경 → 렌더링 정상화 확인.

### 2. `_positions_code_set` 초기화 누락 수정 ✅
**파일**: `backend/app/services/engine_account_notify.py`
**내용**: `init_sent_caches` 호출 시 `_rebuild_positions_cache(positions)` 미호출 → `_positions_code_set` 비어있어 보유종목 틱이 필터링 제거됨.
**수정**: `init_sent_caches` 말미에 `_rebuild_positions_cache(positions)` 호출 추가.

### 3. 디버그 로그 전체 제거 ✅
`ws_manager.py`, `binding.ts`, `appStore.ts`, `sell-position.ts`에 추가했던 `[DEBUG-*]` 로그 전부 제거.

### 4. `broadcast()` 사전 필터링 최적화 ✅
**파일**: `backend/app/web/ws_manager.py` (`broadcast` 함수)
**내용**: 기존엔 모든 틱에 대해 `_encode_realdata()`(JSON+zlib) + `loop.create_task()` 후 task 내부에서 필터링했음.
**수정**: `broadcast()`에서 어떤 클라이언트도 필요 없는 틱은 encode/task 생성 전에 즉시 `return`. 이벤트 루프 부하 대폭 감소.

---

## 미해결 문제: 보유종목 현재가 MTS 불일치

### 현상
- **앱**: 300,000 (정규장 종가)
- **MTS**: 299,500 (NXT 현재가)
- 앱 재기동 시마다 발생. NXT 거래 시간(16:00~20:00) 중 발생.

### 파이프라인 분석 완료

#### 데이터 흐름 (두 경로가 존재)
```
Kiwoom REAL 0B/01 틱
  ├─ engine_ws_dispatch._handle_real_01()
  │    ├─ _latest_trade_prices[nk_px] = last_px   (line 299)
  │    ├─ apply_last_price_to_positions_inplace()  (line 360) → _positions 갱신
  │    └─ (account broadcast 없음, 메모리만 갱신)
  └─ notify_raw_real_data()  (line 513, handle_real 루프에서 먼저 호출)
       └─ _broadcast("real-data") → 프론트 applyRealData() → appStore.positions 즉시 갱신

Kiwoom REAL 04 잔고 틱
  └─ engine_ws_dispatch._handle_real_balance()
       └─ real04_official_apply_position_line()
            ├─ prefer_01 = _latest_trade_prices.get(raw_cd) > 0
            │    True  → cur_price 덮어쓰지 않음 ✅
            │    False → cur_price = FID10 (정규장 종가 300,000 가능) ⚠️
            └─ _broadcast_account(reason="balance_04") → 0.5s coalesce → account-update
                 └─ 프론트 applyAccountUpdate() → appStore.positions 덮어씀
```

#### 유력 원인 후보
1. **타이밍 문제**: 앱 재기동 직후 REAL 04가 REAL 0B보다 먼저 도착 → `_latest_trade_prices` 비어있음 → `prefer_01=False` → REAL 04 FID10(300,000)으로 `_positions` 덮어씀 → `account-update`로 프론트에 300,000 전달. 이후 REAL 0B가 오면 `applyRealData`로 299,500으로 복구되지만, 또 REAL 04가 오면 반복.

2. **`account-update` 타이밍**: `real-data`(즉시)보다 `account-update`(0.5s+0.1s 지연)가 늦게 오지만, `_apply_delayed_account_broadcast` 실행 시 `_positions[0]["cur_price"]`가 이미 299,500이면 문제없음. 단, REAL 04가 `_latest_trade_prices` 초기화 전에 반복 실행되면 300,000 재주입 가능.

### 다음 세션에서 해야 할 일

#### 검증 방법
백엔드 `engine_ws_dispatch.py` line 360 직후에 다음 로그 임시 추가:
```python
if nk_px == "032830":
    logger.info("[DEBUG-0B] 032830 REAL 0B price=%d _latest=%s", last_px, es._latest_trade_prices.get(nk_px))
```
백엔드 `real04_official_apply_position_line` 진입 시:
```python
if raw_cd == "032830":
    logger.info("[DEBUG-04] 032830 REAL 04 cur_price=%d prefer_01=%s live=%s", cur_price, prefer_01, live)
```

#### 예상 근본 수정 방향
`real04_official_apply_position_line`에서 `prefer_01` 판단 기준을 `_latest_trade_prices`가 아닌 **현재 `_positions[i]["cur_price"]`가 이미 0B로 갱신됐는지**로 변경하거나, 아니면 REAL 0B가 `_latest_trade_prices` 갱신 후 REAL 04가 덮어쓰지 못하도록 `_latest_trade_prices` 키 만료 타임스탬프 추가.

또는 더 단순한 해결: **`_reset_realtime_fields` 시 `_latest_trade_prices.clear()` 제거** (혹은 positions의 마지막 알려진 가격으로 초기화).

---

## 현재 코드 상태 (수정 파일 목록)

| 파일 | 상태 | 비고 |
|------|------|------|
| `backend/app/services/engine_account_notify.py` | ✅ 수정됨 | `_rebuild_positions_cache` 추가, DEBUG 로그 남아있음(line 316-322) |
| `backend/app/web/ws_manager.py` | ✅ 수정됨 | 사전 필터링 추가, DEBUG 로그 제거됨 |
| `frontend/src/stores/appStore.ts` | ✅ 수정됨 | splice→배열복사 수정, DEBUG 로그 제거됨 |
| `frontend/src/binding.ts` | ✅ 수정됨 | DEBUG 로그 제거됨 |
| `frontend/src/pages/sell-position.ts` | ✅ 수정됨 | DEBUG 로그 제거됨 |

### 주의: 아직 남아있는 DEBUG 로그
`engine_account_notify.py` line 316-322:
```python
if nk == "032830":
    logger.info("[DEBUG] 032830 _is_relevant_code check: pos=%s layout=%s pending=%s", ...)
```
→ 다음 세션 시작 시 제거 필요 (또는 활용해서 원인 파악 먼저).
