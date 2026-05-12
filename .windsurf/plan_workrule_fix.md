# SectorFlow 워크룰 위반 수정 — 상세 단계별 실행 계획서

> 작성 시점: 2026-05-12  
> 이전 세션 확인 사실 기반  
> 다음 세션에서 즉시 이어서 실행 가능하도록 작성  
> 워크룰 원본: `/Users/sungjk0706/Desktop/SectorFlow/.kiro/steering/sectorflow-rules.md`

---

## 1. 확인된 위반 사항 요약 (코드 근거 포함)

### 위반 1: 예외 삼키기 (try-except: pass) — 10개 파일, 17개 지점

#### 1-1. `engine_ws_dispatch.py` — 4건 (실시간 체결 경로)
- **라인 271**: `except RuntimeError: pass`
  - 함수: `_handle_reg_real` 내부
  - 원인: `asyncio.get_running_loop().create_task(es._delayed_resubscribe_stock_after_rate_limit(norm))` 실패 시 이벤트 루프 미실행
  - 코드:
    ```python
    try:
        asyncio.get_running_loop().create_task(
            es._delayed_resubscribe_stock_after_rate_limit(norm)
        )
    except RuntimeError:
        pass
    ```
  - 위험도: 중간 — 재구독 누락 시 해당 종목 실시간 미수신

- **라인 335**: `except (ValueError, TypeError): pass`
  - 함수: `_handle_real_01` 내부
  - 원인: `_update_strength_buckets(es, nk_px, float(strength), abs(_ws_fid_int(vals, "13", 0)))` 파싱 실패
  - 코드:
    ```python
    try:
        _update_strength_buckets(es, nk_px, float(strength), abs(_ws_fid_int(vals, "13", 0)))
    except (ValueError, TypeError):
        pass
    ```
  - 위험도: 낮음 — 체결강도 버킷 누락

- **라인 387**: `except (ValueError, TypeError): pass`
  - 함수: `_handle_real_01` 내부 (WL 경로)
  - 원인: `_update_strength_buckets(es, nk_px, float(str(sv).strip()), abs(_ws_fid_int(vals, "13", 0)))` 파싱 실패
  - 코드:
    ```python
    try:
        _update_strength_buckets(es, nk_px, float(str(sv).strip()), abs(_ws_fid_int(vals, "13", 0)))
    except (ValueError, TypeError):
        pass
    ```
  - 위험도: 낮음 — 체결강도 버킷 누락

- **라인 404**: `except (ValueError, TypeError): pass`
  - 함수: `_handle_real_00` 내부
  - 원인: `int(str(vals.get("902", "0")).replace(",", "").replace("+", "") or 0)` 파싱 실패
  - 코드:
    ```python
    try:
        unex = int(str(vals.get("902", "0")).replace(",", "").replace("+", "") or 0)
    except (ValueError, TypeError):
        unex = 0
    ```
  - 위험도: 중간 — `unex = 0` fallback은 존재하나 로그 없음

#### 1-2. `engine_account_notify.py` — 2건 (브로드캐스트/필터 경로)
- **라인 298-299**: `except Exception: pass`
  - 함수: `_is_relevant_code` 내부
  - 원인: `_es._pending_stock_details`, `_positions_code_set`, `_layout_code_set` 접근 중 예외
  - 코드:
    ```python
    try:
        import app.services.engine_service as _es
        if nk in _es._pending_stock_details:
            return True
        if nk in _positions_code_set:
            return True
        if nk in _layout_code_set:
            return True
    except Exception:
        pass
    return False
    ```
  - 위험도: 중간 — 예외 시 `False` 반환(필터 통과) 가능성

- **라인 318-319**: `except Exception: pass`
  - 함수: `notify_raw_real_data` 내부
  - 원인: `_format_kiwoom_reg_stk_cd(raw_code)` 실패
  - 코드:
    ```python
    try:
        from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
        nk = _format_kiwoom_reg_stk_cd(raw_code)
        if not _is_relevant_code(nk):
            return
    except Exception:
        pass
    ```
  - 위험도: 중간 — 예외 시 후속 브로드캐스트 계속 진행

#### 1-3. `engine_strategy_core.py` — 2건 (전략/구독 경로)
- **라인 42-43**: `except Exception: pass`
  - 함수: `_resolve_stock_name` 내부
  - 원인: `data_manager.get_stock_name(stk_cd, access_token)` REST 조회 실패
  - 코드:
    ```python
    try:
        rest_nm = (data_manager.get_stock_name(stk_cd, access_token) or "").strip()
    except Exception:
        rest_nm = ""
    ```
  - 위험도: 낮음 — `rest_nm = ""` fallback 존재

- **라인 116-117**: `except RuntimeError: pass`
  - 함수: `make_detail` 내부
  - 원인: `asyncio.get_running_loop().create_task(es._subscribe_stock_realtime_when_ready(stk_cd))` 실패
  - 코드:
    ```python
    try:
        _task = asyncio.get_running_loop().create_task(es._subscribe_stock_realtime_when_ready(stk_cd))
        _task.add_done_callback(lambda t: logger.warning("[구독등록] 구독 실패: %s", t.exception()) if t.exception() else None)
    except RuntimeError:
        pass
    ```
  - 위험도: 중간 — 실시간 구독 누락

#### 1-4. `engine_bootstrap.py` — 7건 (부트스트랩/브로드캐스트 경로)
- **라인 44-45**: `_broadcast_bootstrap_stage` 내 WS 브로드캐스트
  - 코드:
    ```python
    try:
        ws_manager.broadcast("bootstrap-stage", payload)
    except Exception:
        pass
    ```
- **라인 272-273**: `notify_desktop_buy_radar_only` 호출
  - 코드:
    ```python
    try:
        _account_notify.notify_desktop_buy_radar_only()
    except Exception:
        pass
    ```
- **라인 425-426**: 부트스트랩 완료 후 섹터/종목/매수후보 전송
  - 코드:
    ```python
    try:
        notify_desktop_sector_scores(force=True)
        notify_desktop_sector_stocks_refresh()
        notify_buy_targets_update()
    except Exception:
        pass
    ```
- **라인 441-442**: 장외 확정 매수후보 갱신
  - 코드:
    ```python
    try:
        _account_notify.notify_desktop_buy_radar_only()
    except Exception:
        pass
    ```
- **라인 447-448**: 장외 확정 섹터 갱신
  - 코드:
    ```python
    try:
        _account_notify.notify_desktop_sector_refresh()
    except Exception:
        pass
    ```
- **라인 705-706**: 5일평균 완료 후 섹터 요약 갱신
  - 코드:
    ```python
    try:
        recompute_sector_summary_now()
        _account_notify.notify_desktop_sector_refresh()
        _account_notify.notify_desktop_sector_stocks_refresh()
        _account_notify.notify_desktop_sector_scores(force=True)
    except Exception:
        pass
    ```
- **라인 736-737**: `_broadcast_avg_amt_progress` 브로드캐스트
  - 코드:
    ```python
    try:
        ws_manager.broadcast("avg-amt-progress", payload)
    except Exception:
        pass
    ```

#### 1-5. `trading.py` — 1건 (텔레그램 알림 경로)
- **라인 32-33**: `except Exception: pass`
  - 함수: `_notify` 내부
  - 원인: `NotificationWorker.get_instance().enqueue(...)` 실패
  - 코드:
    ```python
    try:
        NotificationWorker.get_instance().enqueue({
            "type": "telegram",
            "message": message,
            "settings": settings,
        })
    except Exception:
        pass
    ```

#### 1-6. `market_close_pipeline.py` — 1건 (진행률 브로드캐스트)
- **라인 52-53**: `except Exception: pass`
  - 함수: `broadcast_confirmed_progress` 내부
  - 원인: WS 브로드캐스트 실패
  - 코드:
    ```python
    try:
        if _loop is not None:
            ws_manager.broadcast_threadsafe("confirmed-progress", payload, _loop)
        else:
            ws_manager.broadcast("confirmed-progress", payload)
    except Exception:
        pass
    ```

---

### 위반 2: 실시간 지연 측정 및 자동매매 중단 로직 미구현

- **관련 파일**:
  - `engine_account_notify.py` 라인 321: `_ts = int(time.time() * 1000)` 주입 존재
  - `engine_ws_dispatch.py`: `_handle_real_01`, `_handle_real_00` 진입점
  - `trading.py`: `AutoTradeManager` 클래스
  - 프론트엔드 `binding.ts`: 지연 측정 코드 미확인
  - 프론트엔드 `appStore.ts`: 지연 상태 미확인

- **확인 사실**:
  - 백엔드에서 `_ts`는 `notify_raw_real_data`의 `real-data` 메시지에만 주입됨
  - 체결 처리 경로(`_handle_real_01`, `_handle_real_00`) 내부에는 `_ts` 미주입
  - 50ms/200ms 측정 로직 전무
  - `_realtime_latency_exceeded` 플래그 전무
  - 자동매매 중단 로직 전무

---

### 위반 3: 프론트엔드 `.map()` 전체 재생성

- **파일**: `frontend/src/stores/appStore.ts`
- **라인 496**: `updates.sectorOrder = scores.map(s => s.sector)`
- **함수**: `applySectorScores`
- **코드 맥락**:
  ```typescript
  const updates: Partial<AppState> = { sectorStatus: data.status ?? null }
  if (!same) {
    updates.sectorScores = scores
    updates.sectorOrder = scores.map(s => s.sector)
  }
  appStore.setState(updates)
  ```
- **문제**: `same` 비교는 `sectorScores` 배열 비교이며, `sectorOrder`는 항상 새 배열 생성됨. 동일한 순서의 업종이라도 매번 새 배열 참조

---

### 위반 4: 프론트엔드 `innerHTML = ''`

- **파일 1**: `frontend/src/pages/sector-analysis.ts`
- **라인 35**: `maxTargetsStatusEl.innerHTML = ''`
- **함수**: `updateMaxTargetsStatus`
- **코드 맥락**:
  ```typescript
  function updateMaxTargetsStatus(scores: SectorScoreRow[]): void {
    if (!maxTargetsStatusEl) return
    const passed = scores.filter(s => s.rank > 0).length
    const cutoff = scores.filter(s => s.rank === 0).length
    maxTargetsStatusEl.innerHTML = ''
    maxTargetsStatusEl.style.gap = '4px'
    // ... appendChild 이어짐
  ```

- **파일 2**: `frontend/src/components/common/data-table.ts`
- **라인 215**: `tbody.innerHTML = ''`
- **함수**: `renderEmpty`
- **코드 맥락**:
  ```typescript
  function renderEmpty() {
    tbody.innerHTML = ''
    const tr = document.createElement('tr')
    // ...
  }
  ```

---

### 위반 5: 실시간 체결 처리 경로에서 무거운 로깅 금지

- **원칙**: 체결 틱 하나하나에 `print`나 과도한 로그 파일 쓰기를 하지 마세요.
- **이유**: 초당 수백 건의 체결이 들어오는데 매번 로그를 남기면 앱이 느려집니다. 꼭 필요한 경고나 오류만 최소한으로 기록하세요.
- **확인 필요 파일**:
  - `engine_ws_dispatch.py`: `_handle_real_01`, `_handle_real_00`
  - `engine_account_notify.py`: `notify_raw_real_data`
- **현재 상태**: 위반 1 수정 과정에서 `logger.warning` 추가됨. 초당 수백 건 호출 가능한 경로에 `warning` 레벨 로그가 추가되었는지 재검토 필요.

---

### 위반 6: 네트워크 복구 시 버퍼링(끊긴 데이터 모아두기) 방식 금지

- **원칙**: 네트워크가 끊겼다 돌아왔을 때, 못 받은 데이터를 모았다가 순서대로 넣으려는 로직을 만들지 마세요.
- **이유**: 시간 순서가 꼬일 위험이 큽니다. 차라리 최신 전체 데이터(스냅샷)를 다시 받아 덮어쓰는 게 안전합니다.
- **확인 필요 파일**:
  - 프론트엔드 WS 재연결 로직
  - `engine_ws_dispatch.py`: 구독 해제/재구독 경로
- **현재 상태**: 미확인

---

### 위반 7: 장중(거래 시간)에 프리페치(미리 다른 화면 로드) 금지

- **원칙**: 사용자가 현재 보지 않는 다른 페이지의 데이터를 미리 불러오는 기능을 장중에 돌리지 마세요.
- **이유**: 거래 데이터 처리로 이미 바쁜데 리소스를 낭비하면 오히려 부하가 늘어납니다. 캐시(한번 본 페이지는 빠르게)만 허용하세요.
- **확인 필요 파일**:
  - 프론트엔드 라우터 및 데이터 로드 로직
- **현재 상태**: 미확인

---

### 위반 8: 사용자가 보고 있지 않은 화면에 실시간 데이터를 계속 보내지 마세요

- **원칙**: 백엔드에서 "지금 이 클라이언트가 어떤 페이지를 보고 있는지" 판단해서, 보고 있지 않은 화면의 데이터는 아예 전송하지 마세요.
- **이유**: 불필요한 네트워크 트래픽과 프론트엔드 부하를 줄입니다.
- **예외**: 매수후보/보유종목 등은 거의 항상 보낼 수 있도록 예외 처리 필요.
- **확인 필요 파일**:
  - `engine_account_notify.py`: 브로드캐스트 필터 `_is_relevant_code`
  - `engine_ws_dispatch.py`: WS 메시지 분기
- **현재 상태**: `_is_relevant_code`가 필터링하나, "현재 페이지" 기준 필터링인지는 미확인

---

### 위반 9: 자동매매 조건 판단을 프론트엔드에서 하지 마세요

- **원칙**: 매수/매도 조건 충족 여부나 실제 주문 실행은 반드시 백엔드(서버)에서만 처리하게 하세요.
- **이유**: 프론트엔드는 화면 표시만 담당해야 안전합니다. 사용자가 브라우저를 꺼도 백엔드에서 매매가 계속 되어야 합니다.
- **확인 필요 파일**:
  - `trading.py`: `AutoTradeManager`
  - 프론트엔드: 매매 관련 로직 유무
- **현재 상태**: `trading.py`에서 백엔드 처리 확인. 프론트엔드에서 매매 판단 로직 미확인.

---

### 위반 10: 실시간 가격 변동 로그 숨기기

- **원칙**: 주식 가격이 바뀔 때마다 매번 그 내용을 콘솔이나 로그 파일에 기록하지 마세요.
- **이유**: 초당 수백 번 기록하면 앱이 무거워지고, 필요 없는 파일만 커집니다.
- **수정 방향**:
  - 실시간 가격 변동 관련 기록을 모두 끄거나, 로그 레벨을 "경고/오류"만 남기도록 변경.
  - 단, 나중에 문제를 찾기 위해 임시로 다시 켤 수 있는 방법(예: 환경 변수나 설정 파일)은 남겨둘 것.
- **참고 (선택, 다음 단계로 미룸)**: 이번 수정이 끝난 후에는 사용자가 직접 "로그 켜기/끄기"를 선택할 수 있는 화면 토글을 추가하는 것을 고려할 것.
- **현재 상태**: 미확인

---

## 2. Phase별 상세 실행 계획

> **공통 프로세스 (모든 Phase/서브 Phase 필수)**
>
> 각 서브 Phase(예: Phase 1-1)는 아래 **6단계**를 반드시 순차 수행합니다.  
> **Step 6(검증) 완료 후 사용자 승인 없이 다음 서브 Phase로 진행할 수 없습니다.**
>
> | 단계 | 명칭 | 내용 | 산출물 |
> |------|------|------|--------|
> | Step 1 | **조사** | 대상 파일 정밀 읽기, 주변 코드 맥락 파악, 호출처/호출자 추적, 예외 발생 경로 분석 | 조사 메모 |
> | Step 2 | **분석** | 위반 원인 근본 분석, 영향 범위 평가, 수정 방안 2가지 이상 비교, 위험도 판정 | 분석 보고 |
> | Step 3 | **수정계획보고** | 사용자에게 "함수명(UI용어) + 수정 내용 + 영향 범위 + 롤백 방안" 보고, **승인 요청** | 보고서 |
> | | | **보고 규칙**: 함수명과 함께 해당 기능의 UI 용어를 반드시 병기. 예: `_handle_real_01`(실시간 체결 0B/01 처리), `_broadcast_bootstrap_stage`(부트스트랩 진행률 브로드캐스트) | |
> | Step 4 | **승인 게이트** | 사용자가 "진행" 또는 "보류/수정" 명시적 응답. **승인 없으면 절대 수정 실행 금지** | 승인 기록 |
> | Step 5 | **수정** | 승인된 계획에 따라 코드 수정. 한 번에 한 파일만 수정 권장 | diff |
> | Step 6 | **검증** | 단위 테스트, 로그 확인, 회귀 테스트, 성능 측정. 결과를 보고서에 포함 | 검증 보고 |
>
> **Step 6 완료 후 필수**: 해당 서브 Phase 결과를 `HANDOVER.md`에 기록(없으면 신규 작성, 있으면 업데이트)
>
> ---

### 0단계: 세션 시작 (모든 세션 필수)

**새 세션이 시작되면 가장 먼저 실행:**

1. `HANDOVER.md` 읽기:
   - 경로: `/Users/sungjk0706/Desktop/SectorFlow/.windsurf/HANDOVER.md`
   - 없으면 "이전 작업 내역이 없습니다. 새로 시작할까요?" 대기 (워크룰 11절)
2. `HANDOVER.md`에서 이전 세션까지 완료된 서브 Phase 목록 확인
3. 다음에 진행할 서브 Phase 결정 → 사용자에게 보고 → 승인 시 해당 서브 Phase Step 1부터 시작
4. `HANDOVER.md`가 존재하나 완료된 Phase가 없으면 Phase 1-1 Step 1부터 시작

---

### Phase 1: 예외 삼키기(try-except: pass) 제거

#### Phase 1-1: `engine_ws_dispatch.py` — 실시간 체결 4건

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py`
- 조사 항목:
  1. 라인 271, 335, 387, 404의 정확한 코드 읽기 (이미 확인됨)
  2. 각 `except` 블록이 속한 함수의 상위 호출 스택 추적
     - `_handle_reg_real` (271): WS 메시지 `REG REAL` 응답 처리
     - `_handle_real_01` (335, 387): 실시간 체결(0B/01) 처리
     - `_handle_real_00` (404): 주문체결(00) 처리
  3. `logger` 객체 확인: `import logging; logger = logging.getLogger(__name__)` 존재 여부
  4. 실시간 경로에서 `logger.warning` 호출 시 지연 영향 측정(기존 로깅 방식 확인)

**Step 2 — 분석**
- 위반 원인: 예외 발생 시 아무런 기록 없이 처리 계속 → 장애 원인 추적 불가
- 영향 범위:
  - 271: 재구독 누락 → 해당 종목 실시간 미수신(중간 위험)
  - 335, 387: 체결강도 버킷 누락 → 전략 판단 정보 손실(낮은 위험)
  - 404: 미체결수량 0으로 fallback → 체결 콜백 정보 왜곡(중간 위험)
- 수정 방안 비교:
  - A) `logger.warning` 추가(권장): 기존 동작 유지 + 로그 기록
  - B) 예외를 상위로 전파: 실시간 경로 중단 → 비권장
- 위험도: 낮음~중간. `logger` 호출은 동기이나 메모리 버퍼 기록 수준으로 지연 미미

**Step 3 — 수정계획보고**
- 수정 내용: 4개 지점 `except: pass` → `except X as e: logger.warning/error(...)`
- 영향 범위: `engine_ws_dispatch.py` 단일 파일, 실시간 체결/재구독 경로
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 1-1 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 1-1 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py`
- 수정 대상: 라인 271, 335, 387, 404
- 규칙: `pass` 대신 최소한의 `logger.warning` 또는 `logger.error` 기록. 실시간 경로에서 `logger` 호출이 지연을 유발하지 않도록 확인(로거가 비동기 핸들러 사용 중인지 확인). `logger`가 동기 blocking이면 `sys.stderr.write` 또는 버퍼 기록 고려.

**수정 전/후 코드**:

- 라인 271:
  ```python
  # 수정 전
  try:
      asyncio.get_running_loop().create_task(
          es._delayed_resubscribe_stock_after_rate_limit(norm)
      )
  except RuntimeError:
      pass

  # 수정 후
  try:
      asyncio.get_running_loop().create_task(
          es._delayed_resubscribe_stock_after_rate_limit(norm)
      )
  except RuntimeError as e:
      logger.warning("[재구독] 루프 미실행 %s: %s", norm, e)
  ```

- 라인 335:
  ```python
  # 수정 전
          try:
              _update_strength_buckets(es, nk_px, float(strength), abs(_ws_fid_int(vals, "13", 0)))
          except (ValueError, TypeError):
              pass

  # 수정 후
          try:
              _update_strength_buckets(es, nk_px, float(strength), abs(_ws_fid_int(vals, "13", 0)))
          except (ValueError, TypeError) as e:
              logger.warning("[체결강도] %s 파싱 실패 strength=%r: %s", nk_px, strength, e)
  ```

- 라인 387:
  ```python
  # 수정 전
                  try:
                      _update_strength_buckets(es, nk_px, float(str(sv).strip()), abs(_ws_fid_int(vals, "13", 0)))
                  except (ValueError, TypeError):
                      pass

  # 수정 후
                  try:
                      _update_strength_buckets(es, nk_px, float(str(sv).strip()), abs(_ws_fid_int(vals, "13", 0)))
                  except (ValueError, TypeError) as e:
                      logger.warning("[체결강도WL] %s 파싱 실패 sv=%r: %s", nk_px, sv, e)
  ```

- 라인 404:
  ```python
  # 수정 전
    try:
        unex = int(str(vals.get("902", "0")).replace(",", "").replace("+", "") or 0)
    except (ValueError, TypeError):
        unex = 0

  # 수정 후
    try:
        unex = int(str(vals.get("902", "0")).replace(",", "").replace("+", "") or 0)
    except (ValueError, TypeError) as e:
        logger.warning("[미체결] %s 파싱 실패 902=%r: %s", raw_cd, vals.get("902"), e)
        unex = 0
  ```

**검증 방법**:
1. `grep -n "except.*pass" backend/app/services/engine_ws_dispatch.py` → 0건 확인
2. `scripts/test_realtime_data.py` 실행 또는 WS 체결 메시지 모의 전송
3. 잘못된 strength 값(예: `"-"`, `""`, `"abc"`) 주입 → `backend/logs/nohup.out`에서 `[체결강도]` warning 확인
4. 잘못된 902 값 주입 → `[미체결]` warning 확인
5. 정상 체결 메시지 처리 여부 확인(기능 회귀)

---

#### Phase 1-2: `engine_account_notify.py` — 브로드캐스트/필터 2건

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py`
- 조사 항목:
  1. 라인 298-299, 318-319의 정확한 코드 읽기
  2. 각 `except` 블록이 속한 함수의 호출처 추적
     - `_is_relevant_code` (298-299): `notify_raw_real_data`에서 호출
     - `notify_raw_real_data` (318-319): WS `real-data` 브로드캐스트 경로
  3. `_positions_code_set`, `_layout_code_set` 정의 위치 및 생명주기 확인
  4. `_format_kiwoom_reg_stk_cd`의 예외 발생 가능 시나리오 확인

**Step 2 — 분석**
- 위반 원인: 종목 필터링/정규화 실패 시 예외 무시 → 불필요한 브로드캐스트 또는 필터 통과
- 영향 범위:
  - 298-299: 예외 시 `False` 반환으로 인해 필터 통과 가능성(중간 위험)
  - 318-319: 예외 시 후속 브로드캐스트 계속 진행(중간 위험)
- 수정 방안 비교:
  - A) `logger.error` 추가 + 기존 반환값 유지(권장)
  - B) 예외 시 즉시 `return` 추가: 318-319는 이미 존재하나 298-299는 영향 있음
- 위험도: 중간. 브로드캐스트 경로에서 `logger.error` 호출은 비동기 핸들러 사용 시 지연 미미

**Step 3 — 수정계획보고**
- 수정 내용: 2개 지점 `except: pass` → `except X as e: logger.error(...)`
- 영향 범위: `engine_account_notify.py` 단일 파일, WS 브로드캐스트/필터 경로
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 1-2 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 1-2 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py`
- 수정 대상: 라인 298-299, 318-319
- 주의: `_is_relevant_code`는 `notify_raw_real_data`에서 호출되며, 이 함수는 WS `real-data` 브로드캐스트 경로. 성능 영향 최소화 필요.

**수정 전/후 코드**:

- 라인 298-299:
  ```python
  # 수정 전
    try:
        import app.services.engine_service as _es
        if nk in _es._pending_stock_details:
            return True
        if nk in _positions_code_set:
            return True
        if nk in _layout_code_set:
            return True
    except Exception:
        pass
    return False

  # 수정 후
    try:
        import app.services.engine_service as _es
        if nk in _es._pending_stock_details:
            return True
        if nk in _positions_code_set:
            return True
        if nk in _layout_code_set:
            return True
    except Exception as e:
        logger.error("[필터] 종목 %s 판별 실패: %s", nk, e)
    return False
  ```

- 라인 318-319:
  ```python
  # 수정 전
        try:
            from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
            nk = _format_kiwoom_reg_stk_cd(raw_code)
            if not _is_relevant_code(nk):
                return
        except Exception:
            pass

  # 수정 후
        try:
            from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
            nk = _format_kiwoom_reg_stk_cd(raw_code)
            if not _is_relevant_code(nk):
                return
        except Exception as e:
            logger.error("[정규화] raw_code=%r 실패: %s", raw_code, e)
            return
  ```

**검증 방법**:
1. `grep -n "except.*pass" backend/app/services/engine_account_notify.py` → 0건 확인
2. 잘못된 `raw_code`(예: `None`, `123`, `""`) 주입 → `[정규화]` error 로그 확인
3. `_es` 모듈 미로드 상태 시뮬레이션 → `[필터]` error 로그 확인
4. 정상 종목코드 브로드캐스트 여부 확인

---

#### Phase 1-3: `engine_strategy_core.py` — 전략/구독 2건

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_strategy_core.py`
- 조사 항목:
  1. 라인 42-43, 116-117의 정확한 코드 읽기
  2. `_resolve_stock_name`의 호출처: `make_detail` 및 기타 전략 함수
  3. `data_manager.get_stock_name`의 예외 발생 패턴(네트워크, 타임아웃, JSON 파싱 등)
  4. `make_detail`에서의 `create_task` 실패 원인(이벤트 루프 미실행 시)

**Step 2 — 분석**
- 위반 원인: 종목명 REST 실패/구독 등록 실패 시 무기명 처리
- 영향 범위:
  - 42-43: 종목명 조회 실패 시 힌트명 또는 종목코드 fallback(낮은 위험)
  - 116-117: 구독 등록 누락 → 실시간 미수신(중간 위험)
- 수정 방안 비교:
  - A) `logger.warning/error` 추가 + 기존 fallback 유지(권장)
  - B) 구독 실패 시 재시도 로직 추가: 복잡도 증가, 별도 Phase 고려
- 위험도: 낮음~중간

**Step 3 — 수정계획보고**
- 수정 내용: 2개 지점 `except: pass` → `except X as e: logger.warning/error(...)`
- 영향 범위: `engine_strategy_core.py` 단일 파일, 종목명/구독 경로
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 1-3 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 1-3 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_strategy_core.py`
- 수정 대상: 라인 42-43, 116-117

**수정 전/후 코드**:

- 라인 42-43:
  ```python
  # 수정 전
    try:
        rest_nm = (data_manager.get_stock_name(stk_cd, access_token) or "").strip()
    except Exception:
        rest_nm = ""

  # 수정 후
    try:
        rest_nm = (data_manager.get_stock_name(stk_cd, access_token) or "").strip()
    except Exception as e:
        logger.warning("[종목명] REST 조회 실패 %s: %s", stk_cd, e)
        rest_nm = ""
  ```

- 라인 116-117:
  ```python
  # 수정 전
        try:
            _task = asyncio.get_running_loop().create_task(es._subscribe_stock_realtime_when_ready(stk_cd))
            _task.add_done_callback(lambda t: logger.warning("[구독등록] 구독 실패: %s", t.exception()) if t.exception() else None)
        except RuntimeError:
            pass

  # 수정 후
        try:
            _task = asyncio.get_running_loop().create_task(es._subscribe_stock_realtime_when_ready(stk_cd))
            _task.add_done_callback(lambda t: logger.warning("[구독등록] 구독 실패: %s", t.exception()) if t.exception() else None)
        except RuntimeError as e:
            logger.error("[구독] task 생성 실패 %s: %s", stk_cd, e)
  ```

**검증 방법**:
1. `grep -n "except.*pass" backend/app/services/engine_strategy_core.py` → 0건 확인
2. REST 실패 시뮬레이션 → `[종목명]` warning 로그 확인
3. 이벤트 루프 미실행 상태에서 `make_detail` 호출 → `[구독]` error 로그 확인

---

#### Phase 1-4: `engine_bootstrap.py` — 부트스트랩 7건

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_bootstrap.py`
- 조사 항목:
  1. 7개 지점(44-45, 272-273, 425-426, 441-442, 447-448, 705-706, 736-737)의 정확한 코드 읽기
  2. 각 `except` 블록이 속한 함수의 호출 타이밍(부트스트랩 어느 단계)
  3. `ws_manager.broadcast`의 예외 발생 패턴(클라이언트 0명, 연결 끊김 등)
  4. `_account_notify.notify_desktop_*` 함수들의 예외 전파 여부

**Step 2 — 분석**
- 위반 원인: 부트스트랩/장외갱신/5일평균 후처리 시 WS 브로드캐스트 실패 무시
- 영향 범위:
  - 44-45, 736-737: 진행률 브로드캐스트 실패 → UI 진행 상태 미반영(낮은 위험)
  - 272-273, 441-442, 447-448: 매수후보/섹터 갱신 실패 → UI 데이터 구식(낮은 위험)
  - 425-426, 705-706: 부트스트랩/5일평균 완료 후 UI 초기 전송 실패 → 초기 화면 빈 상태(높은 위험)
- 수정 방안 비교:
  - A) 모든 지점 `logger.warning/error` 추가(권장)
  - B) 425-426, 705-706만 error, 나머지 warning으로 분리(세밀한 방안)
- 위험도: 낮음~높음(지점별 상이)

**Step 3 — 수정계획보고**
- 수정 내용: 7개 지점 `except: pass` → `except X as e: logger.warning/error(...)`
- 영향 범위: `engine_bootstrap.py` 단일 파일, 부트스트랩/장외갱신/5일평균 경로
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 1-4 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 1-4 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_bootstrap.py`
- 수정 대상: 라인 44-45, 272-273, 425-426, 441-442, 447-448, 705-706, 736-737
- 주의: 7개 지점 모두 WS 브로드캐스트 또는 알림 트리거. `logger` 레벨은 `warning`으로 통일하되, 부트스트랩 완료 후 초기 전송(425-426, 705-706)은 `error` 권장.

**수정 전/후 코드**:

- 라인 44-45:
  ```python
  # 수정 전
    try:
        ws_manager.broadcast("bootstrap-stage", payload)
    except Exception:
        pass

  # 수정 후
    try:
        ws_manager.broadcast("bootstrap-stage", payload)
    except Exception as e:
        logger.warning("[부트] stage 브로드캐스트 실패 %s: %s", stage_name, e)
  ```

- 라인 272-273:
  ```python
  # 수정 전
    try:
        _account_notify.notify_desktop_buy_radar_only()
    except Exception:
        pass

  # 수정 후
    try:
        _account_notify.notify_desktop_buy_radar_only()
    except Exception as e:
        logger.warning("[부트] 매수후보 갱신 실패: %s", e)
  ```

- 라인 425-426:
  ```python
  # 수정 전
            try:
                notify_desktop_sector_scores(force=True)
                notify_desktop_sector_stocks_refresh()
                notify_buy_targets_update()
            except Exception:
                pass

  # 수정 후
            try:
                notify_desktop_sector_scores(force=True)
                notify_desktop_sector_stocks_refresh()
                notify_buy_targets_update()
            except Exception as e:
                logger.error("[부트] UI 초기 전송 실패: %s", e)
  ```

- 라인 441-442:
  ```python
  # 수정 전
        try:
            _account_notify.notify_desktop_buy_radar_only()
        except Exception:
            pass

  # 수정 후
        try:
            _account_notify.notify_desktop_buy_radar_only()
        except Exception as e:
            logger.warning("[장외] 매수후보 갱신 실패: %s", e)
  ```

- 라인 447-448:
  ```python
  # 수정 전
        try:
            _account_notify.notify_desktop_sector_refresh()
            logger.info("[앱준비][장외갱신] 섹터 분석 패널 갱신 트리거")
        except Exception:
            pass

  # 수정 후
        try:
            _account_notify.notify_desktop_sector_refresh()
            logger.info("[앱준비][장외갱신] 섹터 분석 패널 갱신 트리거")
        except Exception as e:
            logger.warning("[장외] 섹터 갱신 실패: %s", e)
  ```

- 라인 705-706:
  ```python
  # 수정 전
    try:
        recompute_sector_summary_now()
        _account_notify.notify_desktop_sector_refresh()
        _account_notify.notify_desktop_sector_stocks_refresh()
        _account_notify.notify_desktop_sector_scores(force=True)
    except Exception:
        pass

  # 수정 후
    try:
        recompute_sector_summary_now()
        _account_notify.notify_desktop_sector_refresh()
        _account_notify.notify_desktop_sector_stocks_refresh()
        _account_notify.notify_desktop_sector_scores(force=True)
    except Exception as e:
        logger.error("[5일평균] 후처리 실패: %s", e)
  ```

- 라인 736-737:
  ```python
  # 수정 전
        ws_manager.broadcast("avg-amt-progress", payload)
    except Exception:
        pass

  # 수정 후
        ws_manager.broadcast("avg-amt-progress", payload)
    except Exception as e:
        logger.warning("[5일평균] 진행률 전송 실패: %s", e)
  ```

**검증 방법**:
1. `grep -n "except.*pass" backend/app/services/engine_bootstrap.py` → 0건 확인
2. `ws_manager.broadcast`를 monkey-patch로 `raise Exception("WS disconnect")` 설정
3. 부트스트랩 시뮬레이션 실행 → 각 지점별 로그 레벨 확인
4. 장외 갱신 트리거 실행 → `[장외]` warning 로그 확인

---

#### Phase 1-5: `trading.py` — 텔레그램 1건

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trading.py`
- 조사 항목:
  1. 라인 32-33의 정확한 코드 읽기
  2. `_notify` 함수의 호출처: `AutoTradeManager` 내 매수/매도/체결 알림
  3. `NotificationWorker`의 예외 발생 패턴(큐 가득, 텔레그램 API 실패, 설정 누락 등)
  4. 텔레그램 알림 실패가 매매 로직에 미치는 영향(없음 확인)

**Step 2 — 분석**
- 위반 원인: 텔레그램 알림 전송 실패 시 운영자 미인지
- 영향 범위: 알림 누락만, 매매 로직에는 직접 영향 없음(낮은 위험)
- 수정 방안 비교:
  - A) `logger.error` 추가(권장): 알림 누락 시 로그로 추적 가능
  - B) fallback 알림 방식(이메일/파일): 과잉 설계, 비권장
- 위험도: 낮음

**Step 3 — 수정계획보고**
- 수정 내용: 1개 지점 `except: pass` → `except Exception as e: logger.error(...)`
- 영향 범위: `trading.py` 단일 파일, 텔레그램 알림 경로
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 1-5 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 1-5 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trading.py`
- 수정 대상: 라인 32-33

**수정 전/후 코드**:

```python
# 수정 전
try:
    NotificationWorker.get_instance().enqueue({
        "type": "telegram",
        "message": message,
        "settings": settings,
    })
except Exception:
    pass

# 수정 후
try:
    NotificationWorker.get_instance().enqueue({
        "type": "telegram",
        "message": message,
        "settings": settings,
    })
except Exception as e:
    logger.error("[텔레그램] 알림 전송 실패: %s", e)
```

**검증 방법**:
1. `grep -n "except.*pass" backend/app/services/trading.py` → 0건 확인
2. `NotificationWorker.get_instance()` mock에서 예외 발생 → `[텔레그램]` error 로그 확인

---

#### Phase 1-6: `market_close_pipeline.py` — 진행률 1건

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/market_close_pipeline.py`
- 조사 항목:
  1. 라인 52-53의 정확한 코드 읽기
  2. `broadcast_confirmed_progress`의 호출처: 장종료 파이프라인 각 단계 완료 시
  3. `ws_manager.broadcast_threadsafe` vs `ws_manager.broadcast` 사용 조건
  4. 장종료 파이프라인 전체 흐름 및 이 지점의 위상

**Step 2 — 분석**
- 위반 원인: 장종료 진행률 브로드캐스트 실패 시 UI 미반영
- 영향 범위: 진행률 표시 누락, 파이프라인 자체는 계속 실행(낮은 위험)
- 수정 방안 비교:
  - A) `logger.warning` 추가(권장)
  - B) 실패 시 재시도: 장종료 파이프라인은 장시간 실행, 재시도 불필요
- 위험도: 낮음

**Step 3 — 수정계획보고**
- 수정 내용: 1개 지점 `except: pass` → `except Exception as e: logger.warning(...)`
- 영향 범위: `market_close_pipeline.py` 단일 파일, 진행률 브로드캐스트 경로
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 1-6 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 1-6 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/market_close_pipeline.py`
- 수정 대상: 라인 52-53

**수정 전/후 코드**:

```python
# 수정 전
try:
    if _loop is not None:
        ws_manager.broadcast_threadsafe("confirmed-progress", payload, _loop)
    else:
        ws_manager.broadcast("confirmed-progress", payload)
except Exception:
    pass

# 수정 후
try:
    if _loop is not None:
        ws_manager.broadcast_threadsafe("confirmed-progress", payload, _loop)
    else:
        ws_manager.broadcast("confirmed-progress", payload)
except Exception as e:
    logger.warning("[장종료] 진행률 전송 실패(step=%s): %s", step, e)
```

**검증 방법**:
1. `grep -n "except.*pass" backend/app/services/market_close_pipeline.py` → 0건 확인
2. 장종료 파이프라인 시뮬레이션 실행 → WS 연결 끊김 시 `[장종료]` warning 로그 확인

---

### Phase 2: 실시간 지연 측정 및 자동매매 중단 로직 구현

#### Phase 2-1: 백엔드 지연 측정

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일:
  1. `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py`
  2. `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_service.py`
  3. `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trading.py`
- 조사 항목:
  1. `_handle_real_01`, `_handle_real_00`의 함수 시작/끝 지점 확인
  2. `engine_service.py`의 전역 상태 변수 목록 및 초기화 위치
  3. `AutoTradeManager`의 신규 매수 주문 진입점 확인
  4. `time.perf_counter_ns()` vs `time.time_ns()` 성능 특성 비교
  5. 기존 `_ts` 주입 지점(`notify_raw_real_data`, 라인 321)과의 중복/충돌 여부

**Step 2 — 분석**
- 위반 원인: 수신→처리→전송 50ms/200ms 임계값 측정 및 자동매매 중단 로직 전무
- 영향 범위:
  - `engine_ws_dispatch.py`: 2개 함수 수정
  - `engine_service.py`: 전역 플래그 1개 추가
  - `trading.py`: 매수 주문 전 플래그 확인 추가
- 수정 방안 비교:
  - A) `perf_counter_ns()`로 wall-clock 측정(권장): GIL 블로킹 포함, 실제 경과 시간 반영
  - B) CPU 시간 측정: 시스템 부하 영향 배제하나 실제 지연 미반영
- 임계값 제안: 초기 50ms/200ms, 실제 운영 데이터 기반 조정 가능
- 위험도: 중간. 잘못된 임계값 설정 시 과도한 매매 중단 또는 지연 미감지

**Step 3 — 수정계획보고**
- 수정 내용:
  1. `engine_service.py`: `_realtime_latency_exceeded: bool = False` 추가
  2. `engine_ws_dispatch.py`: `_handle_real_01`, `_handle_real_00` 상단/하단에 지연 측정 추가
  3. `trading.py`: `AutoTradeManager` 매수 주문 전 플래그 확인
- 영향 범위: 3개 파일, 실시간 체결→자동매매 경로
- 롤백 방안: git revert 3개 파일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 2-1 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 2-1 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일 1: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py`
- 파일 2: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_service.py` (플래그 상태 추가)
- 파일 3: `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trading.py`

**작업 내용**:

1. `engine_service.py`에 전역 플래그 추가:
   ```python
   _realtime_latency_exceeded: bool = False
   ```

2. `engine_ws_dispatch.py` `_handle_real_01` 상단/하단에 시각 기록:
   ```python
   _start = time.perf_counter_ns()
   # ... 기존 처리 로직 ...
   _latency_us = (time.perf_counter_ns() - _start) // 1000
   if _latency_us > 200_000:
       logger.critical("[실시간지연] %s 체결 처리 %dms — 자동매매 중단 임계", nk_px, _latency_us // 1000)
       engine_service._realtime_latency_exceeded = True
   elif _latency_us > 50_000:
       logger.warning("[실시간지연] %s 체결 처리 %dms — 경고", nk_px, _latency_us // 1000)
   ```

3. `engine_ws_dispatch.py` `_handle_real_00`에도 동일하게 적용(주문체결 처리 지연 측정).

4. `trading.py` `AutoTradeManager` 내 신규 매수 주문 전 확인:
   ```python
   import app.services.engine_service as _es
   if getattr(_es, '_realtime_latency_exceeded', False):
       logger.critical("[자동매매] 실시간 지연 200ms 초과 — 신규 매수 중단")
       return  # 매수 주문 중단
   ```

5. 복구 메커니즘: 지연이 50ms 미만으로 10회 연속 정상 처리 시 `_realtime_latency_exceeded = False` 복원. 또는 수동 API 엔드포인트 추가.

**주의사항**:
- `time.perf_counter_ns()`는 CPU 시간이 아닌 wall-clock 시간이므로 GIL 블로킹에도 민감함
- 50ms 임계값이 너무 엄격할 수 있음(초기에는 100ms/500ms로 조정 가능)
- 자동매매 중단은 신규 매수만, 보유 종목 매도는 계속 허용

**검증 방법**:
1. `time.sleep(0.06)`을 `_handle_real_01`에 임시 삽입 → `[실시간지연] ... 경고` 로그 확인
2. `time.sleep(0.25)` 임시 삽입 → `[실시간지연] ... 중단` + `_realtime_latency_exceeded = True` 확인
3. 매수 시그널 발생 → `[자동매매] ... 중단` 로그 + 주문 미발생 확인
4. 지연 제거 후 연속 10회 정상 처리 → 매수 재개 확인

---

#### Phase 2-2: 프론트엔드 지연 측정

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일:
  1. `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/binding.ts`
  2. `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/appStore.ts`
- 조사 항목:
  1. `binding.ts`의 `real-data` 메시지 핸들러 위치 및 기존 코드
  2. `appStore.ts`의 `AppState` 인터페이스 정의 및 기존 상태 목록
  3. `_ts` 필드가 프론트엔드에서 어떻게 수신되는지 확인(타입, 존재 여부)
  4. `performance.now()`의 브라우저 지원 범위 및 정밀도

**Step 2 — 분석**
- 위반 원인: 프론트엔드에서 네트워크/처리 지연 분리 측정 없음
- 영향 범위: 2개 파일, WS 메시지 수신→UI 갱신 경로
- 수정 방안 비교:
  - A) `binding.ts`에서 측정 + `appStore.ts`에 상태 저장(권장)
  - B) 별도 지연 측정 유틸리티: 과잉 설계, 현재 필요 없음
- 위험도: 낮음. UI 상태 추가만, 비즈니스 로직 영향 없음

**Step 3 — 수정계획보고**
- 수정 내용:
  1. `appStore.ts`: `latencyMetrics` 상태 및 `setLatencyMetrics` 액션 추가
  2. `binding.ts`: `real-data` 핸들러에서 수신/처리 시각 기록 및 상태 갱신
- 영향 범위: 2개 파일, 프론트엔드 WS 메시지 처리 경로
- 롤백 방안: git revert 2개 파일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 2-2 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 2-2 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일 1: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/binding.ts`
- 파일 2: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/appStore.ts`

**작업 내용**:

1. `appStore.ts`에 상태 추가:
   ```typescript
   interface AppState {
     // ... 기존 상태 ...
     latencyMetrics: {
       network: number;      // ms
       processing: number; // ms
       lastUpdated: number; // timestamp
     } | null;
     setLatencyMetrics: (m: AppState['latencyMetrics']) => void;
   }
   ```

2. `binding.ts` `real-data` 메시지 핸들러 수정:
   ```typescript
   // 메시지 수신 시
   const receiveTime = performance.now();
   const backendTs = item._ts as number;
   const networkLatency = receiveTime - backendTs;
   
   // ... 처리 로직 ...
   
   const processingLatency = performance.now() - receiveTime;
   appStore.getState().setLatencyMetrics({
     network: networkLatency,
     processing: processingLatency,
     lastUpdated: Date.now(),
   });
   ```

3. 선택적: 지연 임계 초과 시 UI 상태바 색상 변경(빨간색) 또는 콘솔 경고.

**주의사항**:
- `_ts`는 `time.time() * 1000`(백엔드 시각). 클라이언트-서버 시차가 있을 수 있으나, 동일 세션 내에서는 상대값 추세로 충분
- `performance.now()`는 페이지 로드 후 경과 ms(부동소수점, 마이크로초 정밀도)

**검증 방법**:
1. Chrome DevTools → Network → throttling 3G 설정
2. WS `real-data` 메시지 수신 시 `latencyMetrics` 콘솔 출력 확인
3. `networkLatency`가 50ms 이상일 때 경고 출력 확인

---

### Phase 3: 프론트엔드 `.map()` 전체 재생성 제거

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/appStore.ts`
- 조사 항목:
  1. `applySectorScores` 함수의 전체 코드 읽기
  2. `same` 변수의 비교 로직 확인(`sectorScores` 배열 비교)
  3. `sectorOrder`를 구독하는 UI 컴포넌트 목록 추적
  4. Zustand의 불변성 기반 리렌더링 메커니즘 확인

**Step 2 — 분석**
- 위반 원인: `same` 비교는 `sectorScores`만, `sectorOrder`는 항상 새 배열
- 영향 범위: 동일 업종 순서 반복 시 불필요한 리렌더(낮은 위험)
- 수정 방안 비교:
  - A) `sectorOrder` 변경 여비교 후 조건부 갱신(권장): `some()`으로 O(n) 비교
  - B) `sectorOrder`를 `Record<string, number>`로 구조 변경: 근본적이나 영향 범위 큼
- 위험도: 낮음. 성능 최적화, 기능 변경 아님

**Step 3 — 수정계획보고**
- 수정 내용: `applySectorScores`에서 `sectorOrder` 조건부 갱신으로 변경
- 영향 범위: `appStore.ts` 단일 파일
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 3 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 3 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/appStore.ts`
- 수정 대상: `applySectorScores` 함수, 라인 496

**작업 내용**:

```typescript
// 수정 전 (라인 494-496)
const updates: Partial<AppState> = { sectorStatus: data.status ?? null }
if (!same) {
  updates.sectorScores = scores
  updates.sectorOrder = scores.map(s => s.sector)
}
appStore.setState(updates)

// 수정 후
const updates: Partial<AppState> = { sectorStatus: data.status ?? null }
if (!same) {
  updates.sectorScores = scores
  const newOrder = scores.map(s => s.sector)
  const currentOrder = appStore.getState().sectorOrder
  const orderChanged = !currentOrder
    || newOrder.length !== currentOrder.length
    || newOrder.some((s, i) => s !== currentOrder[i])
  if (orderChanged) {
    updates.sectorOrder = newOrder
  }
}
appStore.setState(updates)
```

**근거**:
- `same`은 `sectorScores` 배열 비교이며, `sectorOrder`는 이와 별도로 매번 새 배열 생성됨
- 동일한 업종 순서가 반복 전송될 때 `sectorOrder` 참조를 유지하면 Zustand 구독자의 불필요한 리렌더 방지
- `sectorOrder.some`은 최대 30~40개 업종 순회 → O(n), 무시할 수 있는 오버헤드

**검증 방법**:
1. 동일한 업종 점수 이벤트 2회 연속 전송
2. `console.log(appStore.getState().sectorOrder === 이전참조)` → `true` 확인
3. Chrome DevTools Profiler → `applySectorScores` 호출 시 `sectorOrder` 변경 없으면 관련 컴포넌트 리렌더 스킵 확인

---

### Phase 4: 프론트엔드 `innerHTML = ''` 제거

#### Phase 4-1: `sector-analysis.ts`

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/pages/sector-analysis.ts`
- 조사 항목:
  1. `updateMaxTargetsStatus` 함수의 전체 코드 읽기
  2. `maxTargetsStatusEl`의 초기화 위치 및 생명주기
  3. `innerHTML = ''` 호출 시 기존 이벤트 리스너/참조 누출 여부 확인
  4. 함수 호출 빈도(업종 점수 이벤트당 1회인지, 다중 호출인지)

**Step 2 — 분석**
- 위반 원인: `innerHTML = ''` 사용 시 DOM 완전 재구축, 이벤트 리스너 누출 위험
- 영향 범위: 업종 점수 상태 표시 영역(낮은 위험)
- 수정 방안 비교:
  - A) `removeChild` 루프(권장): 기존 방식과 가장 유사하나 안전
  - B) 상태 요소 미리 생성 + `textContent` 교체: 가장 효율적이나 코드 구조 변경 필요
- 위험도: 낮음

**Step 3 — 수정계획보고**
- 수정 내용: `maxTargetsStatusEl.innerHTML = ''` → `while (firstChild) removeChild`
- 영향 범위: `sector-analysis.ts` 단일 파일
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 4-1 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 4-1 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/pages/sector-analysis.ts`
- 수정 대상: `updateMaxTargetsStatus` 함수, 라인 35

**작업 내용**:

```typescript
// 수정 전 (라인 35)
maxTargetsStatusEl.innerHTML = ''

// 수정 후
while (maxTargetsStatusEl.firstChild) {
  maxTargetsStatusEl.removeChild(maxTargetsStatusEl.firstChild)
}
```

**또는 더 나은 방식** (이벤트 리스너 누출 방지):
```typescript
// 상태 요소를 미리 생성해두고 textContent만 교체
// (updateMaxTargetsStatus 외부에서 한 번만 생성)
const passedLabel = document.createElement('span')
const cutoffLabel = document.createElement('span')
// ... appendChild는 초기화 시 한 번만

function updateMaxTargetsStatus(scores: SectorScoreRow[]): void {
  if (!maxTargetsStatusEl) return
  const passed = scores.filter(s => s.rank > 0).length
  const cutoff = scores.filter(s => s.rank === 0).length
  passedLabel.textContent = `통과 ${passed}`
  cutoffLabel.textContent = `컷오프 ${cutoff}`
  // innerHTML 제거 불필요
}
```

**검증 방법**:
1. `grep -n "innerHTML.*=''" frontend/src/pages/sector-analysis.ts` → 0건 확인
2. 업종 점수 갱신 100회 반복 → Chrome Memory 탭에서 `maxTargetsStatusEl` 관련 노드 누출 없음 확인

---

#### Phase 4-2: `data-table.ts`

**[승인 게이트: Step 3 완료 후 사용자 승인 필요]**

**Step 1 — 조사**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/components/common/data-table.ts`
- 조사 항목:
  1. `renderEmpty` 함수의 전체 코드 읽기
  2. `renderEmpty`의 호출처(초기 마운트 vs 실시간 갱신) 확인
  3. `tbody`에 기존 이벤트 리스너/참조가 있는지 확인
  4. 워크룰 5-2 예외(초기 마운트) 적용 가능 여부 판정

**Step 2 — 분석**
- 위반 원인: `innerHTML = ''` 사용 시 DOM 재구축
- 영향 범위: 테이블 빈 상태 표시(낮은 위험)
- 수정 방안 비교:
  - A) `removeChild` 루프(권장): 안전한 DOM 제거
  - B) `renderEmpty` 호출 시 기존 `tr`의 `td.textContent`만 교체: `renderEmpty`가 매번 다른 메시지를 표시하지 않는 한 유효
- 워크룰 5-2 재확인: 초기 마운트만 호출된다면 위반 아닐 수 있으나, 통일성 위해 수정 권장
- 위험도: 낮음

**Step 3 — 수정계획보고**
- 수정 내용: `tbody.innerHTML = ''` → `while (firstChild) removeChild`
- 영향 범위: `data-table.ts` 단일 파일
- 롤백 방안: git revert 단일 커밋
- **승인 요청**: 위 내용에 동의하면 "Phase 4-2 진행"으로 회신

**Step 4 — 승인 게이트**
- 사용자가 "Phase 4-2 진행" 또는 "수정" 응답 시까지 대기
- **승인 없이는 Step 5(수정) 실행 금지**

**Step 5 — 수정**
- 파일: `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/components/common/data-table.ts`
- 수정 대상: `renderEmpty` 함수, 라인 215

**작업 내용**:

```typescript
// 수정 전 (라인 215)
function renderEmpty() {
  tbody.innerHTML = ''
  const tr = document.createElement('tr')
  // ...
}

// 수정 후
function renderEmpty() {
  while (tbody.firstChild) {
    tbody.removeChild(tbody.firstChild)
  }
  const tr = document.createElement('tr')
  // ...
}
```

**워크룰 5-2 재확인 필요사항**:
- `renderEmpty()`가 실시간 갱신 중(데이터 삭제 후) 호출되는지, 초기 마운트만 호출되는지 다시 확인
- 초기 마운트만 호출된다면 위반 아닐 수 있으나, 통일성을 위해 수정 권장

**검증 방법**:
1. `grep -n "innerHTML.*=''" frontend/src/components/common/data-table.ts` → 0건 확인
2. 테이블 빈 상태 렌더링 시 DOM 노드 정상 제거 확인

---

## 3. 실행 순서 및 의존성

```
Phase 1-1 ──┐  ← Step 6 완료 + 사용자 승인 후
Phase 1-2 ──┤  ← Step 6 완료 + 사용자 승인 후
Phase 1-3 ──┤  ← Step 6 완료 + 사용자 승인 후
Phase 1-4 ──┤  ← Step 6 완료 + 사용자 승인 후  (독립 병렬 가능)
Phase 1-5 ──┤  ← Step 6 완료 + 사용자 승인 후
Phase 1-6 ──┘  ← Step 6 완료 + 사용자 승인 후
      │
      ▼  [사용자 승인: "Phase 2 진행"]
Phase 2-1 (백엔드 지연 측정) ──→ Phase 2-2 (프론트 지연 측정)
      │                              │
      ▼                              ▼
Phase 3 (프론트 .map() 최적화)  Phase 4-1/4-2 (프론트 innerHTML 제거)
      │                              │
      └──────────────┬───────────────┘
                     ▼
              [사용자 승인: "통합 QA 진행"]
                     ▼
              Phase 5 (통합 QA)
```

### 승인 게이트 규칙

1. **서브 Phase 내부 승인**: 각 서브 Phase(1-1 ~ 4-2)의 Step 3(수정계획보고) 완료 후 사용자에게 보고 → **"Phase X-Y 진행" 명시적 승인 없이는 Step 5(수정) 절대 실행 금지**

2. **Phase 간 승인**:
   - Phase 1(6개 서브 Phase) 전체 완료 후 → 사용자 승인 → Phase 2 진행
   - Phase 2(2-1, 2-2) 완료 후 → 사용자 승인 → Phase 3, 4 진행
   - Phase 3, 4(4-1, 4-2) 완료 후 → 사용자 승인 → Phase 5(통합 QA) 진행

3. **병렬 가능 범위**:
   - Phase 1의 6개 서브 Phase는 서로 독립 → **동일한 사용자 승인 하에** 병렬 실행 가능
   - Phase 2-2, Phase 3, Phase 4-1/4-2는 서로 독립 → **동일한 사용자 승인 하에** 병렬 실행 가능

4. **롤백 정책**:
   - 각 서브 Phase는 별도 git 커밋으로 분리
   - 문제 발생 시 해당 서브 Phase 커밋만 revert
   - 통합 QA(Phase 5)에서 회귀 발견 시 → 해당 서브 Phase로 돌아가 재수정 → 재승인

5. **인계서(HANDOVER.md) 작성 규칙**:
   - **Step 6(검증) 완료 직후** → 반드시 `HANDOVER.md` 업데이트
   - 업데이트 내용: 완료된 서브 Phase, 확인된 사실, 다음 진행할 서브 Phase, 주의사항
   - 없으면 `/Users/sungjk0706/Desktop/SectorFlow/.windsurf/HANDOVER.md` 신규 작성
   - 다음 세션 시작 시 `HANDOVER.md`를 읽고 이어서 진행 (워크룰 11절)

- **Phase 1**의 6개 서브 Phase는 서로 독립 → 병렬 실행 가능
- **Phase 2-1**은 `engine_service.py` 상태 변경 필요 → Phase 1 완료 후 실행 권장
- **Phase 2-2, 3, 4**는 프론트엔드 수정 → 서로 독립, Phase 1과 병렬 가능
- **Phase 5**는 모든 수정 완료 후 실행

---

## 4. 최종 검증 체크리스트

### 백엔드
- [ ] `grep -rn "except.*pass" backend/app/services/engine_ws_dispatch.py backend/app/services/engine_account_notify.py backend/app/services/engine_strategy_core.py backend/app/services/engine_bootstrap.py backend/app/services/trading.py backend/app/services/market_close_pipeline.py` → 0건
- [ ] 의도적 예외 발생 시뮬레이션 → 각 지점별 `warning`/`error` 로그 출력
- [ ] 실시간 체결 처리 TPS 기존과 동일 또는 개선
- [ ] 지연 측정: 50ms → warning, 200ms → critical + 매매 중단
- [ ] 자동매매 중단 후 복구(연속 10회 정상 또는 수동 API)

### 프론트엔드
- [ ] `grep -rn "innerHTML.*=''" frontend/src/` → 0건 (초기 마운트 제외)
- [ ] 동일 업종 점수 이벤트 → `sectorOrder` 참조 동일성 유지
- [ ] `latencyMetrics` 상태 업데이트 확인
- [ ] TypeScript 컴파일 오류 없음: `npm run build` 또는 `tsc --noEmit`
- [ ] Chrome Memory 탭: DOM 노드 누출 없음

### 통합
- [ ] WS 브로드캐스트 전체 정상 동작
- [ ] 부트스트랩 완료 후 UI 초기화 정상
- [ ] 장종료 파이프라인 정상 종료
- [ ] 실시간 체결→화면 반영 지연 200ms 미만 유지

---

## 5. 인계서(HANDOVER.md) 작성/업데이트 규칙

### 작성 시기
- **Step 6(검증) 완료 후 즉시 작성/업데이트**
- 세션이 종료되기 전(사용자가 "그만"이라고 할 때) 마지막으로 업데이트
- Phase 전환(Phase 1 → Phase 2 등) 시에도 업데이트

### 파일 경로
`/Users/sungjk0706/Desktop/SectorFlow/.windsurf/HANDOVER.md`

### 포함 내용 (필수)
```markdown
# SectorFlow 워크룰 수정 — 세션 인계서

## 완료된 서브 Phase
- [x] Phase 1-1: engine_ws_dispatch.py — 예외 삼키기 4건 제거 (Step 1~6 완료, 검증 통과)
- [ ] Phase 1-2: engine_account_notify.py — 예외 삼키기 2건 (미시작)
- ...

## 다음 세션에서 진행할 서브 Phase
- Phase 1-2 Step 1부터 시작

## 확인된 사실 (중요)
- engine_ws_dispatch.py의 logger는 logging.getLogger(__name__) 사용
- _handle_real_01에서 logger.warning 호출 시 지연 미미 확인
- ...

## 주의사항 / 미해결 의문
- engine_bootstrap.py 425-426 지점은 error vs warning 레벨 논의 필요
- ...

## 마지막 업데이트
YYYY-MM-DD HH:MM
```

### 업데이트 방법
1. `HANDOVER.md` 존재 여부 확인
2. 존재하면 기존 내용 위에 덮어쓰기(또는 diff 형식으로 추가)
3. 없으면 신규 작성
4. 마지막 업데이트 시간 기록

---

## 6. 파일 경로 요약

| 파일 | 절대 경로 | 수정 Phase |
|------|-----------|------------|
| engine_ws_dispatch.py | `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py` | 1-1, 2-1 |
| engine_account_notify.py | `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_account_notify.py` | 1-2 |
| engine_strategy_core.py | `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_strategy_core.py` | 1-3 |
| engine_bootstrap.py | `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_bootstrap.py` | 1-4 |
| trading.py | `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/trading.py` | 1-5, 2-1 |
| market_close_pipeline.py | `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/market_close_pipeline.py` | 1-6 |
| engine_service.py | `/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_service.py` | 2-1 (상태 추가) |
| appStore.ts | `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/appStore.ts` | 2-2, 3 |
| binding.ts | `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/binding.ts` | 2-2 |
| sector-analysis.ts | `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/pages/sector-analysis.ts` | 4-1 |
| data-table.ts | `/Users/sungjk0706/Desktop/SectorFlow/frontend/src/components/common/data-table.ts` | 4-2 |

---

## 6. 이전 세션에서 확인한 코드 사실

- `engine_ws_dispatch.py` 271줄: `_handle_reg_real` 내 `except RuntimeError: pass` — 재구독 task 생성(실시간 종목 재구독 스케줄링)
- `engine_ws_dispatch.py` 335줄: `_handle_real_01` 내 `except (ValueError, TypeError): pass` — 체결강도 파싱(실시간 체결 0B/01 → 체결강도 버킷 갱신)
- `engine_ws_dispatch.py` 387줄: `_handle_real_01` 내 `except (ValueError, TypeError): pass` — 체결강도 WL 파싱(실시간 체결 0B/01 → WL 체결강도 버킷 갱신)
- `engine_ws_dispatch.py` 404줄: `_handle_real_00` 내 `except (ValueError, TypeError): pass` — 미체결수량 파싱(주문체결 00 → 미체결수량 갱신)
- `engine_account_notify.py` 298-299줄: `_is_relevant_code` 내 `except Exception: pass` — 관련 종목 판별(실시간 데이터 브로드캐스트 필터링)
- `engine_account_notify.py` 318-319줄: `notify_raw_real_data` 내 `except Exception: pass` — 종목코드 정규화(WS real-data 메시지 종목코드 변환)
- `engine_account_notify.py` 321줄: `notify_raw_real_data` 내 `_ts = int(time.time() * 1000)` — 지연 측정용 타임스탬프 주입(WS real-data 메시지에 지연 측정용 타임스탬프)
- `engine_strategy_core.py` 42-43줄: `_resolve_stock_name` 내 `except Exception: pass` — 종목명 REST 조회(종목명 조회 → 종목명 fallback)
- `engine_strategy_core.py` 116-117줄: `make_detail` 내 `except RuntimeError: pass` — 실시간 구독 등록(매수후보 종목 실시간 구독 등록)
- `engine_bootstrap.py` 44-45줄: `_broadcast_bootstrap_stage` 내 `except Exception: pass` — 부트스트랩 진행률 브로드캐스트(UI 부트스트랩 진행 상태)
- `engine_bootstrap.py` 272-273줄: `notify_desktop_buy_radar_only` 호출 내 `except Exception: pass` — 장외 확정 매수후보 갱신(UI 매수후보 목록)
- `engine_bootstrap.py` 425-426줄: 부트스트랩 완료 후 `except Exception: pass` — 섹터/종목/매수후보 초기 전송(UI 초기 데이터 로딩)
- `engine_bootstrap.py` 441-442줄: 장외 확정 매수후보 갱신 `except Exception: pass` — 장외 매수후보 브로드캐스트
- `engine_bootstrap.py` 447-448줄: 장외 확정 섹터 갱신 `except Exception: pass` — 장외 섹터 브로드캐스트(UI 업종 순위)
- `engine_bootstrap.py` 705-706줄: 5일평균 완료 후 `except Exception: pass` — 섹터 요약 갱신(UI 5일평균 거래대금 기반 업종 재계산)
- `engine_bootstrap.py` 736-737줄: `_broadcast_avg_amt_progress` 내 `except Exception: pass` — 5일평균 진행률 브로드캐스트(UI 5일평균 캐시 진행률)
- `trading.py` 32-33줄: `_notify` 내 `except Exception: pass` — 텔레그램 알림(자동매매 알림 전송)
- `market_close_pipeline.py` 52-53줄: `broadcast_confirmed_progress` 내 `except Exception: pass` — 장종료 진행률 브로드캐스트(UI 장종료 파이프라인 진행 상태)
- `appStore.ts` 496줄: `applySectorScores` 내 `updates.sectorOrder = scores.map(s => s.sector)` — 업종 순서 전체 재생성(업종 점수 상태 갱신 → UI 업종 순서)
- `sector-analysis.ts` 35줄: `updateMaxTargetsStatus` 내 `maxTargetsStatusEl.innerHTML = ''` — 업종 상태 DOM 초기화(UI 업종 점수 상태 표시 영역)
- `data-table.ts` 215줄: `renderEmpty` 내 `tbody.innerHTML = ''` — 테이블 빈 상태 DOM 초기화(UI 데이터 테이블 빈 상태)

---

*이 계획서는 `/Users/sungjk0706/Desktop/SectorFlow/.windsurf/plan_workrule_fix.md`에 저장되어 있습니다. 다음 세션에서는 이 파일을 읽고 Phase 1부터 순차적으로 실행하세요.*
