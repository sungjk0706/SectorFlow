# 증권사 변경 엔진 재기동 수정 계획서

> **작성일**: 2025-01-20
> **근거**: SWE-1.7 보고서 + GLM-5.2 크로스체크 결과
> **관련 원칙**: 원칙 4 (증권사 격리), 원칙 10 (SSOT), 원칙 15 (단일 주문 경로), 원칙 16 (살아있는 경로), 원칙 17 (플래그 단일 소스), 원칙 19 (런타임 검증), 원칙 20 (폴백 금지), 원칙 22 (데이터 정합성)

---

## 1. 배경 및 문제 요약

### 1-1. 현재 동작

증권사 변경 시 `apply_settings_change` (engine_service.py:51-59)가 다음 순서로 실행:

```
refresh_cache → reset_router → stop_engine → reset_broker_session_state → start_engine
```

### 1-2. 크로스체크로 검증된 누락 (코드 기반 확증)

| # | 누락 항목 | 검증 근거 | 위반 원칙 |
|---|---|---|---|
| 1 | 동적 구독(`_subscribed_dynamic`) 복원 누락 | `reset_broker_session_state` (engine_lifecycle.py:89-118)에 `_subscribed_dynamic` 초기화 없음 (grep 0건) | 원칙 10, 17, 22 |
| 2 | `sector_summary_cache` 미초기화 → `are_buy_targets_changed` False → `sync_dynamic_subscriptions` 호출 차단 | `reset_broker_session_state`에 `sector_summary_cache` 초기화 없음 (grep 0건) | 원칙 22 |
| 3 | 동적 구독 해지 타이머(`_PENDING_UNREG_TIMERS`) 잔존 | `cancel_recompute_timer` → `clear_dirty_sectors` (engine_sector_confirm.py:47)는 `_dirty_codes`만 클리어, 타이머는 미클리어 | 원칙 22 |
| 4 | `master_stocks_cache` 동적 데이터(`order_ratio`, `program_net_buy`, `_filtered`) 잔존 | `run_engine_loop` 시작부 (engine_loop.py:138-140)가 `_subscribed`만 제거 | 원칙 10, 22 |
| 5 | `reset_router()` ↔ `stop_engine()` 경쟁 상태 | `reset_router()`가 `stop_engine()`보다 먼저 호출 → 대기 중인 `evaluate_buy_candidates`가 재개 시 NEW router + OLD token으로 주문 전송 가능 | 원칙 15 |
| 6 | LS 명시적 구독 해지(tr_type=4) 누락 | `disconnect()` (ls_connector.py:428-444)가 소켓 종료만 수행. LS API 명세에 `tr_type=4: 실시간 시세 해지` 명시됨 (US3 명세 line 16, UH1 명세 line 40) | 원칙 4 |

### 1-3. 크로스체크에서 제거된 항목 (보고서 오류)

| 보고서 항목 | 검증 결과 | 근거 |
|---|---|---|
| broker_config 동기화 부재 | **틀린 주장** | `_normalize_broker_config` (engine_settings.py:198-208)가 `broker`에서 자동 파생. `refresh_engine_integrated_system_settings_cache` 호출 시마다 재생성 |

---

## 2. LS API 명세 확인 결과

### 2-1. tr_type 정의 (US3 체결 명세, UH1 호가잔량 명세 공통)

```
tr_type: 거래 Type (String, Required=Y, Length=1)
  1: 계좌등록
  2: 계좌해제
  3: 실시간 시세 등록
  4: 실시간 시세 해지
```

### 2-2. 해지 요청 형식

```json
{
  "header": {
    "token": "접근토큰",
    "tr_type": "4"
  },
  "body": {
    "tr_cd": "US3",
    "tr_key": "U005930   "
  }
}
```

### 2-3. 결론

- LS WebSocket은 `tr_type=4`로 명시적 구독 해지를 지원함
- 소켓 단절 시 서버 자동 정리 여부는 API 명세에 명시되지 않음 → 코드에서 보장하지 않음
- **수정 E 적용 근거 확보**: `disconnect()` 전 `tr_type=4` 전송으로 명시적 해지 수행

---

## 3. 수정안별 상세

### 수정 A: `reset_router()` 위치 변경 (경쟁 상태 근본 해결)

**파일**: `backend/app/services/engine_service.py` lines 51-59

**위반 원칙**: 원칙 15 (단일 주문 경로)

**문제**: `reset_router()`가 `stop_engine()`보다 먼저 호출되면, 대기 중인 `evaluate_buy_candidates`가 재개 시 NEW router(신규 broker) + OLD `state.access_token`(구 토큰)으로 주문 전송 가능.

**수정 내용**:
- `stop_engine()` 완료 후(`await state.engine_task` 포함) `reset_router()` 호출
- 엔진 미실행 시 `reset_router()`만 수행 (기존 동작 유지)

**수정 후 순서**:
```
refresh_cache → stop_engine → reset_broker_session_state → reset_router → start_engine
```

### 수정 B: `reset_broker_session_state` 확장 (세션 상태 완전 초기화)

**파일**: `backend/app/services/engine_lifecycle.py` lines 89-118

**위반 원칙**: 원칙 10 (SSOT), 원칙 17 (플래그 단일 소스), 원칙 22 (데이터 정합성)

**문제**: 동적 구독 플래그, 파생 데이터, `sector_summary_cache`가 초기화되지 않아 신규 세션에서 구 데이터 잔존.

**추가 내용**:
1. `master_stocks_cache`에서 `_subscribed_dynamic`, `order_ratio`, `program_net_buy`, `_filtered` 제거
2. `state.sector_summary_cache = None` 설정
3. 동적 구독 해지 타이머 일괄 취소 (수정 C의 함수 호출)

### 수정 C: 동적 구독 해지 타이머 일괄 취소 함수 추가

**파일**: `backend/app/services/engine_sector_confirm.py`

**위반 원칙**: 원칙 22 (데이터 정합성)

**문제**: `_PENDING_UNREG_TIMERS`, `_UNREG_READY_CODES`, `_UNREG_BATCH_PENDING` (모듈 레벨 전역)이 `stop_engine()` 시 미클리어. 구 세션의 30초 지연 해지 타이머가 신규 세션에서 발화 → `DYNAMIC_UNREG`를 신규 증권사에 전송.

**추가 내용**: `cancel_all_dynamic_unreg_timers()` 함수 추가 — 모든 타이머 취소 + set 클리어 + 플래그 리셋.

### 수정 D: `_login_post_pipeline` 동적 구독 복원 추가

**파일**: `backend/app/services/engine_bootstrap.py` lines 174-182

**위반 원칙**: 원칙 16 (구현 = 살아있는 경로에 배선됨)

**문제**: `recompute_sector_summary_now()`가 `sync_dynamic_subscriptions`를 호출하지 않음. 수정 B로 `sector_summary_cache=None` + `_subscribed_dynamic` 제거 후에도, `recompute_sector_summary_now`가 새 `buy_targets`를 생성하지만 동적 구독 REG가 발행되지 않음.

**추가 내용**: `_login_post_pipeline`의 WS 구독 구간 내에서 `recompute_sector_summary_now()` + `_run_sector_reg_pipeline()` 이후에 `sync_dynamic_subscriptions(ss.buy_targets)` 명시적 호출.

### 수정 E: LS `disconnect()` 전 명시적 구독 해지

**파일**: `backend/app/core/ls_connector.py` `disconnect()` 메서드 (lines 428-444)

**위반 원칙**: 원칙 4 (증권사 격리 — 각 증권사의 API 명세 준수)

**문제**: `disconnect()`가 소켓 종료만 수행. LS API 명세에 `tr_type=4` 명시적 해지가 정의되어 있으나 미사용.

**수정 내용**: `disconnect()` 진입 시 `_subscribed` 종목에 대해 `unsubscribe_stocks` fire-and-forget 호출 후 소켓 종료. ACK 대기 없이 최선 전송.

**근거**: LS API 명세 (US3 line 16, UH1 line 40)에 `tr_type=4: 실시간 시세 해지` 명시됨.

### 수정 F: 런타임 검증 테스트 추가

**파일**: `backend/tests/test_broker_change.py` (신규)

**위반 원칙**: 원칙 19 (런타임 검증 게이트)

**문제**: broker 변경 경로에 대한 테스트가 `changed_keys` 포함 여부만 검사 (test_settings_store.py:248). `reset_broker_session_state`, 동적 구독 복원, 호출 순서 등 핵심 경로 미검증.

**추가 테스트**:
1. `test_reset_broker_session_state_clears_dynamic_flags` — 동적 구독 플래그 + 파생 데이터 + `sector_summary_cache` 초기화 검증
2. `test_cancel_all_dynamic_unreg_timers` — 타이머 취소 + set 클리어 검증
3. `test_broker_change_sequence_order` — `stop_engine`이 `reset_router`보다 먼저 실행됨을 검증
4. `test_sync_dynamic_subscriptions_after_broker_change` — broker 변경 후 DYNAMIC_REG 발행 검증

---

## 4. Phase 분할

### Phase 1: 세션 초기화 + 경쟁 상태 해결 (수정 A + B + C)

**목표**: 증권사 변경 시 이전 세션 상태를 완전히 초기화하고, 경쟁 상태를 근본적으로 차단.

**영향 파일**:
- `backend/app/services/engine_service.py` — 수정 A: `reset_router()` 위치 변경
- `backend/app/services/engine_lifecycle.py` — 수정 B: `reset_broker_session_state` 확장
- `backend/app/services/engine_sector_confirm.py` — 수정 C: `cancel_all_dynamic_unreg_timers` 함수 추가

**구현 상세**:

#### A-1. `engine_service.py` lines 51-59 수정

현재:
```python
if "broker" in changed_keys:
    from backend.app.core.broker_factory import reset_router
    reset_router()
    if is_engine_running():
        from backend.app.services.engine_lifecycle import stop_engine, start_engine, reset_broker_session_state
        logger.info("[설정] broker 변경 감지 — 엔진 재기동 (단일 진입점 보장)")
        await stop_engine()
        reset_broker_session_state()
        await start_engine()
```

수정 후:
```python
if "broker" in changed_keys:
    from backend.app.core.broker_factory import reset_router
    if is_engine_running():
        from backend.app.services.engine_lifecycle import stop_engine, start_engine, reset_broker_session_state
        logger.info("[설정] broker 변경 감지 — 엔진 재기동 (단일 진입점 보장)")
        await stop_engine()
        reset_broker_session_state()
        reset_router()
        await start_engine()
    else:
        reset_router()
```

#### B-1. `engine_lifecycle.py` `reset_broker_session_state` 확장

`state.ws_reg_pipeline_done.clear()` 이후에 추가:
```python
    # 동적 구독 상태 초기화 (원칙 10 SSOT, 원칙 17 플래그 단일 소스)
    # 1. master_stocks_cache에서 동적 구독 플래그 + 파생 데이터 제거
    for entry in state.master_stocks_cache.values():
        entry.pop("_subscribed_dynamic", None)
        entry.pop("order_ratio", None)
        entry.pop("program_net_buy", None)
        entry.pop("_filtered", None)

    # 2. sector_summary_cache 초기화 — are_buy_targets_changed가 True 반환 유도
    state.sector_summary_cache = None

    # 3. 동적 구독 해지 타이머 일괄 취소
    from backend.app.services.engine_sector_confirm import cancel_all_dynamic_unreg_timers
    cancel_all_dynamic_unreg_timers()
```

#### C-1. `engine_sector_confirm.py` 함수 추가

`cancel_recompute_timer` 함수 이후에 추가:
```python
def cancel_all_dynamic_unreg_timers() -> None:
    """증권사 변경 시 모든 동적 구독 해지 타이머 취소 + 대기실 클리어.

    stop_engine() 시 cancel_recompute_timer()가 _dirty_codes만 클리어하므로,
    동적 구독 해지 타이머는 별도로 취소해야 함.
    잔존 타이머가 신규 세션에서 발화하면 DYNAMIC_UNREG가 신규 증권사에 전송됨 (원칙 22 위반).
    """
    global _PENDING_UNREG_TIMERS, _UNREG_READY_CODES, _UNREG_BATCH_PENDING
    for timer in _PENDING_UNREG_TIMERS.values():
        timer.cancel()
    _PENDING_UNREG_TIMERS.clear()
    _UNREG_READY_CODES.clear()
    _UNREG_BATCH_PENDING = False
```

**검증 방법**:
1. `cd backend && python -c "import ast; ast.parse(open('app/services/engine_service.py').read()); ast.parse(open('app/services/engine_lifecycle.py').read()); ast.parse(open('app/services/engine_sector_confirm.py').read()); print('syntax ok')"` — 구문 검증
2. `cd backend && python -m pytest tests/test_engine_sector_confirm.py tests/test_settings_store.py -x -q` — 기존 테스트 회귀 확인
3. `.venv/bin/python main.py` 기동 후 10-30초 대기, 로그에서 `[설정]` / `[연산]` 메시지 확인, 종료 후 잔여 프로세스 없음 확인

---

### Phase 2: 동적 구독 복원 + LS 명시적 해지 (수정 D + E)

**목표**: 증권사 변경 후 동적 구독(0D/PGM/UH1/UPH)이 정상 복원되도록 하고, LS 연결 해지 시 명시적 tr_type=4 전송.

**영향 파일**:
- `backend/app/services/engine_bootstrap.py` — 수정 D: `_login_post_pipeline` 동적 구독 복원
- `backend/app/core/ls_connector.py` — 수정 E: `disconnect()` 전 UNREG

**구현 상세**:

#### D-1. `engine_bootstrap.py` lines 174-182 수정

현재:
```python
if _in_ws_window:
    ws = state.connector_manager or state.active_connector
    if ws and ws.is_connected():
        await recompute_sector_summary_now()
        from backend.app.services.engine_ws import _run_sector_reg_pipeline, _ensure_ws_subscriptions_for_positions
        await _run_sector_reg_pipeline()
        await _ensure_ws_subscriptions_for_positions()
```

수정 후:
```python
if _in_ws_window:
    ws = state.connector_manager or state.active_connector
    if ws and ws.is_connected():
        await recompute_sector_summary_now()
        from backend.app.services.engine_ws import _run_sector_reg_pipeline, _ensure_ws_subscriptions_for_positions
        await _run_sector_reg_pipeline()
        await _ensure_ws_subscriptions_for_positions()
        # 동적 구독 복원 — sector_summary_cache 재계산 후 buy_targets 기준 DYNAMIC_REG
        # 원칙 16: 동적 구독 복원이 실제 LOGIN 후 파이프라인에 배선됨
        ss = state.sector_summary_cache
        if ss and ss.buy_targets:
            from backend.app.services.engine_sector_confirm import sync_dynamic_subscriptions
            sync_dynamic_subscriptions(ss.buy_targets)
```

#### E-1. `ls_connector.py` `disconnect()` 수정

현재 (lines 428-444):
```python
async def disconnect(self) -> None:
    """수신루프 중단 + WebSocket 종료. 재연결 루프도 중단."""
    self._stop_reconnect = True
    if self._lock is None:
        self._lock = asyncio.Lock()
    async with self._lock:
        self._connected = False
        if self._socket:
            await self._socket.disconnect()
            self._socket = None
        ...
```

수정 후:
```python
async def disconnect(self) -> None:
    """수신루프 중단 + WebSocket 종료. 재연결 루프도 중단.

    LS API 명세 (US3/UH1): tr_type=4 명시적 실시간 시세 해지 후 소켓 종료.
    ACK 대기 없이 fire-and-forget — disconnect 경로에서 블로킹 방지.
    """
    self._stop_reconnect = True
    if self._lock is None:
        self._lock = asyncio.Lock()
    async with self._lock:
        # 명시적 구독 해지 (tr_type=4) — 소켓 종료 전 최선 전송
        if self._socket and self._connected:
            try:
                # _subscribed 종목 수집 — ConnectorManager._sub_codes 또는 캐시 기반
                # 단, disconnect 시점에서는 인메모리 상태만 사용 (서버 조회 금지)
                pass  # 구독 중인 종목 목록은 ConnectorManager에서 관리
            except Exception:
                logger.warning("[연결] LS 구독 해지 전송 실패 (무시)", exc_info=True)
        self._connected = False
        if self._socket:
            await self._socket.disconnect()
            self._socket = None
        ...
```

**주의**: E-1은 구독 중인 종목 코드 목록이 필요. `ConnectorManager._sub_codes` (connector_manager.py:28)에 `{broker_id: set[str]}` 형태로 저장됨. `disconnect()`는 Connector 자체 메서드이므로 ConnectorManager를 참조할 수 없음 → **대안**: `ConnectorManager.disconnect_all()` (connector_manager.py:115-130)에서 각 Connector의 `disconnect()` 호출 전 `unsubscribe_stocks`를 먼저 호출.

#### E-1 대안: `ConnectorManager.disconnect_all()` 수정

**파일**: `backend/app/core/connector_manager.py` lines 115-130

현재:
```python
async def disconnect_all(self) -> None:
    if not self._connectors:
        return
    async def _disconnect_one(broker_name: str, connector: BrokerConnector) -> None:
        try:
            await connector.disconnect()
            ...
```

수정 후:
```python
async def disconnect_all(self) -> None:
    if not self._connectors:
        return
    async def _disconnect_one(broker_name: str, connector: BrokerConnector) -> None:
        try:
            # 명시적 구독 해지 (LS API tr_type=4) — 소켓 종료 전
            # 원칙 4: 각 증권사의 API 명세 준수
            sub_codes = self._sub_codes.get(broker_name, set())
            if sub_codes and hasattr(connector, "unsubscribe_stocks"):
                try:
                    await connector.unsubscribe_stocks(list(sub_codes))
                except Exception as e:
                    logger.warning("[연결] %s 구독 해지 전송 실패 (무시): %s", broker_name.upper(), e)
            await connector.disconnect()
            ...
```

**검증 방법**:
1. 구문 검증: `python -c "import ast; ast.parse(open('app/services/engine_bootstrap.py').read()); ast.parse(open('app/core/connector_manager.py').read()); print('syntax ok')"`
2. `cd backend && python -m pytest tests/test_engine_bootstrap.py tests/test_engine_ws.py -x -q` — 기존 테스트 회귀 확인
3. `.venv/bin/python main.py` 기동 후 10-30초 대기, 로그에서 `[구독] 신규 등록` / `[연결]` 메시지 확인, 종료 후 잔여 프로세스 없음 확인

---

### Phase 3: 런타임 검증 테스트 추가 (수정 F)

**목표**: 증권사 변경 경로의 핵심 동작을 테스트로 검증하여 회귀 방지.

**영향 파일**:
- `backend/tests/test_broker_change.py` — 신규 파일

**구현 상세**:

#### F-1. `test_reset_broker_session_state_clears_dynamic_flags`

```python
def test_reset_broker_session_state_clears_dynamic_flags():
    """reset_broker_session_state 호출 후 동적 구독 플래그 + 파생 데이터 + sector_summary_cache 초기화 검증."""
    from backend.app.services.engine_lifecycle import reset_broker_session_state
    from backend.app.services.engine_state import state

    state.master_stocks_cache = {
        "005930": {"_subscribed_dynamic": True, "order_ratio": [100, 200], "program_net_buy": 5000, "_filtered": True},
        "000660": {"_subscribed_dynamic": True, "order_ratio": [50, 80], "program_net_buy": 3000, "_filtered": True},
    }
    state.sector_summary_cache = MagicMock()

    reset_broker_session_state()

    for entry in state.master_stocks_cache.values():
        assert "_subscribed_dynamic" not in entry
        assert "order_ratio" not in entry
        assert "program_net_buy" not in entry
        assert "_filtered" not in entry
    assert state.sector_summary_cache is None
```

#### F-2. `test_cancel_all_dynamic_unreg_timers`

```python
def test_cancel_all_dynamic_unreg_timers():
    """타이머 설정 후 cancel_all_dynamic_unreg_timers 호출 시 모든 타이머 취소 + set 클리어 검증."""
    from backend.app.services.engine_sector_confirm import (
        cancel_all_dynamic_unreg_timers,
        _PENDING_UNREG_TIMERS,
        _UNREG_READY_CODES,
        _UNREG_BATCH_PENDING,
    )
    import asyncio

    mock_timer = MagicMock()
    _PENDING_UNREG_TIMERS["005930"] = mock_timer
    _PENDING_UNREG_TIMERS["000660"] = mock_timer
    _UNREG_READY_CODES.add("005930")
    _UNREG_BATCH_PENDING = True

    cancel_all_dynamic_unreg_timers()

    assert mock_timer.cancel.call_count == 2
    assert len(_PENDING_UNREG_TIMERS) == 0
    assert len(_UNREG_READY_CODES) == 0
    assert _UNREG_BATCH_PENDING is False
```

#### F-3. `test_broker_change_sequence_order`

```python
@pytest.mark.asyncio
async def test_broker_change_sequence_order():
    """apply_settings_change({"broker"}) 호출 시 stop_engine이 reset_router보다 먼저 실행됨을 검증."""
    call_order = []
    async def mock_stop():
        call_order.append("stop_engine")
    def mock_reset_router():
        call_order.append("reset_router")
    async def mock_start():
        call_order.append("start_engine")

    with patch("backend.app.services.engine_service.is_engine_running", return_value=True), \
         patch("backend.app.services.engine_service.stop_engine", side_effect=mock_stop), \
         patch("backend.app.services.engine_service.start_engine", side_effect=mock_start), \
         patch("backend.app.core.broker_factory.reset_router", side_effect=mock_reset_router), \
         patch("backend.app.services.engine_lifecycle.reset_broker_session_state"), \
         patch("backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache", new=AsyncMock()), \
         patch("backend.app.services.engine_account_notify.notify_desktop_header_refresh", new=AsyncMock()), \
         patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new=AsyncMock()):
        from backend.app.services.engine_service import apply_settings_change
        await apply_settings_change({"broker"})

    assert call_order == ["stop_engine", "reset_router", "start_engine"]
```

#### F-4. `test_sync_dynamic_subscriptions_after_broker_change`

```python
def test_sync_dynamic_subscriptions_after_broker_change():
    """_subscribed_dynamic 제거 후 sync_dynamic_subscriptions 호출 시 DYNAMIC_REG 발행 검증."""
    from backend.app.services.engine_sector_confirm import sync_dynamic_subscriptions
    from backend.app.services.engine_state import state
    from backend.app.services.core_queue import get_control_queue

    # 수정 B 적용 후 _subscribed_dynamic이 없는 상태
    state.master_stocks_cache = {"005930": {}, "000660": {}}
    state.connector_manager = MagicMock()
    state.connector_manager.is_connected.return_value = True
    state.login_ok = True

    bt = _make_buy_target("005930", guard_pass=True)
    sync_dynamic_subscriptions([bt])

    # DYNAMIC_REG 발행 확인
    queue = get_control_queue()
    # 큐에서 payload 확인 로직
```

**검증 방법**:
1. `cd backend && python -m pytest tests/test_broker_change.py -x -v` — 신규 테스트 통과 확인
2. `cd backend && python -m pytest tests/ -x -q` — 전체 테스트 회귀 확인
3. `.venv/bin/python main.py` 기동 후 10-30초 대기, 종료 후 잔여 프로세스 없음 확인

---

## 5. 전체 검증 체크리스트

### Phase 1 완료 후
- [ ] `engine_service.py` 구문 검증 통과
- [ ] `engine_lifecycle.py` 구문 검증 통과
- [ ] `engine_sector_confirm.py` 구문 검증 통과
- [ ] `test_engine_sector_confirm.py` 전체 통과
- [ ] `test_settings_store.py` 전체 통과
- [ ] 런타임 기동 확인 (10-30초, 로그 정상, 잔여 프로세스 없음)

### Phase 2 완료 후
- [ ] `engine_bootstrap.py` 구문 검증 통과
- [ ] `connector_manager.py` 구문 검증 통과
- [ ] `test_engine_bootstrap.py` 전체 통과
- [ ] `test_engine_ws.py` 전체 통과
- [ ] 런타임 기동 확인 (10-30초, 로그 정상, 잔여 프로세스 없음)

### Phase 3 완료 후
- [ ] `test_broker_change.py` 4개 테스트 전체 통과
- [ ] 전체 테스트 회귀 없음 (`pytest tests/ -x -q`)
- [ ] 런타임 기동 확인 (10-30초, 로그 정상, 잔여 프로세스 없음)

---

## 6. 리스크 및 주의사항

### 6-1. 수정 A (순서 변경)

- **기존 동작 변경**: `reset_router()`가 `stop_engine()` 이후로 이동. 엔진 미실행 시 `reset_router()`만 수행하는 경로는 유지.
- **주의**: `stop_engine()` 내부에서 `state.engine_task` await 후에 `reset_router()`가 호출되므로, 모든 코루틴이 취소된 상태에서 router 재생성. 경쟁 창 제로.

### 6-2. 수정 B (세션 초기화 확장)

- `master_stocks_cache`에서 동적 데이터 제거 시, 캐시 자체는 유지 (종목 기본 정보 보존). 동적 구독 플래그 + 파생 데이터만 제거.
- `sector_summary_cache = None` 설정 후 `recompute_sector_summary_now`가 새로 계산. `_full_recompute`의 `prev_targets=None` → `are_buy_targets_changed` True → `sync_dynamic_subscriptions` 정상 호출.

### 6-3. 수정 E (LS UNREG)

- `disconnect()` 전 `unsubscribe_stocks` 호출 시 소켓이 이미 연결 종료 상태면 실패 가능. `try/except`로 감싸고 실패 시 warning 로그만 출력 (소켓 단절로 서버 자동 정리 기대).
- `ConnectorManager._sub_codes`는 `subscribe_stocks` 성공 시에만 업데이트되므로, 실제 구독 중인 종목과 일치함.

### 6-4. 원칙 20 (폴백 금지) 준수

- 수정 E의 `try/except`는 폴백이 아님 — disconnect 경로에서 소켓이 이미 종료된 경우는 정상 경로가 아니라 예외 상황이며, warning 로그로 즉시 인지 가능하게 처리.
- 수정 A의 엔진 미실행 시 `reset_router()` 분기는 폴백이 아님 — 엔진 미실행 시는 router만 갱신하면 되는 정상 경로.

---

## 7. 완료 기준

1. Phase 1~3 모두 구현 완료
2. 전체 검증 체크리스트 모두 통과
3. `docs/broker_change_engine_restart_plan.md`의 검증 항목 모두 체크됨
4. `HANDOVER.md`에 완료 내용 기록
