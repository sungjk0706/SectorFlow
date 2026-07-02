from __future__ import annotations
# -*- coding: utf-8 -*-
"""
엔진 asyncio 메인 루프 -- 설정·브로커·WS 초기 연결.

`engine_service` 모듈 객체 `es`로 전역 상태를 읽고 갱신한다.
WS 연결/해제는 스케줄러(daily_time_scheduler)가 전적으로 관리한다.
"""

import asyncio
import json
import time
from pathlib import Path

from backend.app.core.broker_factory import get_router
from backend.app.core.engine_settings import get_engine_settings
from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.trading import AutoTradeManager
from backend.app.services.engine_cache import _load_caches_preboot
from backend.app.services.engine_state import state

logger = get_logger("engine")


async def _cache_and_bootstrap(settings: dict) -> None:
    """캐시 선행 로드 → engine-ready WS 전송 → 부트스트랩 순차 실행.

    Cache_Preboot 실패 시 내부 try/except에서 경고 로그 후 계속 진행.
    Bootstrap은 Cache_Preboot 완료 이후에만 실행 (순차 의존 보존).
    적격종목 캐시 없으면 빈 상태로 초기화하고 상태 플래그 설정.
    """
    # ── 캐시 선행 로드 (WS 구간 안이면 내부에서 시세 0으로 적재) ──
    # _load_caches_preboot 내부에서 모든 기동 로직 완료 (단일 파이프라인)
    await _load_caches_preboot(settings)

    # 앱준비 완료 여부와 상관없이 engine-ready 전송
    try:
        from backend.app.web.ws_manager import ws_manager
        await ws_manager.broadcast("engine-ready", {"_v": 1, "ready": True})
        logger.info("[시작] 데이터준비 완료 -- 실시간 준비됨")
    except Exception:
        logger.warning("[시작] engine-ready 브로드캐스트 실패", exc_info=True)


async def _get_all_tokens_async(router) -> None:
    """
    broker_config에 등장하는 모든 증권사 토큰을 병렬 발급한다.
    router._auth_cache에 없는 증권사(stock 전용 등)도 _create_provider로 생성하여 발급.
    발급된 토큰은 state.broker_tokens[broker_id]로 저장한다.
    """
    from backend.app.services.engine_state import state
    auth_cache: dict = getattr(router, "_auth_cache", {})

    # broker_config + confirmed_data_broker의 모든 증권사 수집 (auth_cache에 없는 stock 증권사 포함)
    broker_config = state.integrated_system_settings_cache.get("broker_config") or {}
    all_broker_ids = set(auth_cache.keys())
    for _feat, _bname in broker_config.items():
        _bname = str(_bname or "").lower().strip()
        if _bname:
            all_broker_ids.add(_bname)
    _confirmed_broker = str(
        state.integrated_system_settings_cache.get("confirmed_data_broker") or ""
    ).lower().strip()
    if _confirmed_broker:
        all_broker_ids.add(_confirmed_broker)

    # API 키가 설정된 증권사만 발급 대상
    valid_broker_ids = []
    for bid in all_broker_ids:
        _key = state.integrated_system_settings_cache.get(f"{bid}_app_key", "")
        _sec = state.integrated_system_settings_cache.get(f"{bid}_app_secret", "")
        if _key and _sec:
            valid_broker_ids.append(bid)

    if not valid_broker_ids:
        return

    async def _fetch_one(broker_id: str) -> tuple[str, str | None]:
        try:
            auth_provider = auth_cache.get(broker_id)
            if auth_provider is None:
                from backend.app.core.broker_registry import _create_provider
                auth_provider = _create_provider(
                    "auth", broker_id,
                    state.integrated_system_settings_cache, auth_cache,
                )
            token = await auth_provider.get_access_token()
            from backend.app.core.broker_registry import BROKER_DISPLAY_NAMES
            disp = BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper())
            logger.info("[연결] %s 토큰 발급 완료", disp)
            return broker_id, token
        except Exception as e:
            logger.warning("[연결] %s 토큰 발급 실패: %s", broker_id.upper(), e, exc_info=True)
            return broker_id, None

    results = await asyncio.gather(
        *[_fetch_one(bid) for bid in valid_broker_ids],
        return_exceptions=True,
    )

    state.broker_tokens.clear()

    for result in results:
        if isinstance(result, tuple):
            broker_id, token = result
            if token:
                state.broker_tokens[broker_id] = token


async def _load_broker_spec_async(broker_nm: str, settings: dict) -> list:
    """SQLite DB에서 broker_specs를 로드.

    broker_specs 테이블에서 해당 증권사의 스펙을 로드한다.
    role_mappings(dict)에서 list로 변환하여 반환.
    실패 시 빈 리스트 반환 + 경고 로그.
    """
    try:
        _broker_specs = settings.get("_broker_specs", {})
        if broker_nm in _broker_specs:
            spec = _broker_specs[broker_nm]
            if isinstance(spec, dict):
                role_mappings = spec.get("role_mappings", {})
                if isinstance(role_mappings, dict):
                    return list(role_mappings.values())  # dict → list 변환
                else:
                    logger.warning("[시작] role_mappings 형식 오류: %s (기대: dict)", type(role_mappings))
                    return []
            else:
                logger.warning("[시작] broker_specs 형식 오류: %s (기대: dict)", type(spec))
                return []
        return []
    except Exception as e:
        logger.warning("[시작] broker_specs 로드 실패: %s", e, exc_info=True)
        return []


async def run_engine_loop() -> None:
    from backend.app.services.engine_state import state

    _t0 = time.perf_counter()

    state.login_ok = False
    state.connector_manager = None
    state.broker_tokens.clear()
    state.token_ready_event.clear()
    # _master_stocks_cache에서 "_subscribed" 제거
    all_stocks = state.master_stocks_cache.copy()
    for entry in all_stocks.values():
        entry.pop("_subscribed", None)
    from backend.app.services.engine_state import _notify_reg_ack
    _notify_reg_ack()
    state.checked_stocks.clear()
    state.integrated_system_settings_cache["sector_stock_layout"] = []
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache([])
    state.running = True
    state.engine_loop_ref = asyncio.get_running_loop()
    # 캐시선행 플래그 초기화
    state.preboot_cache_loaded = False
    state.preboot_ready_event.clear()
    # 계좌 REST Lock 초기화 -- 이전 세션 잠금 상태 초기화
    state.account_rest_lock = None

    # 전역 이벤트 버스 (Queues)는 app.py lifespan에서 이미 초기화됨

    gateway_task = None
    oms_task = None
    compute_task = None

    try:
        # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = state.integrated_system_settings_cache

        # 엔진 내부 준비 완료 시그널 — Uvicorn 리스닝 + 브라우저 열기 즉시 허용
        state.preboot_ready_event.set()

        # ── broker/router 생성 (단일 소스 진리: _integrated_system_settings_cache 직접 사용) ──
        broker_nm: str = str(settings["broker"]).lower().strip()
        router = get_router()

        # ── API 키 검증: broker_config.websocket 기준 모든 증권사 확인 ──
        broker_config = settings["broker_config"]
        ws_val = str(broker_config.get("websocket") or broker_nm).lower().strip()
        ws_brokers = [b.strip() for b in ws_val.split(",") if b.strip()]

        valid_brokers = []
        for _bk in ws_brokers:
            _key = settings.get(f"{_bk}_app_key", "")
            _sec = settings.get(f"{_bk}_app_secret", "")
            if _key and _sec:
                valid_brokers.append(_bk)
            else:
                from backend.app.services.engine_service import log_message
                log_message(f" [시작] 증권사 API 키가 설정되지 않았습니다. 일반설정에서 입력하세요.")

        if not valid_brokers:
            from backend.app.services.engine_service import log_message, broadcast_engine_status
            log_message(f" [시작] 유효한 API 키가 없습니다. 일반설정에서 증권사 API 키를 입력하세요.")
            await broadcast_engine_status()
            # 엔진 중단하지 않고 계속 진행 (테스트모드/스냅샷 전용 모드 허용)

        # REST/토큰 발급은 기준 증권사(broker_nm) 기준 유지

        # ── 병렬 초기화: 캐시+앱준비 / 토큰 발급 / 브로커 스펙 로드 ──
        _t_parallel_start = time.perf_counter()

        # 3개 독립 파이프라인 병렬 실행 — broker_spec은 gather 완료 후 사용
        async def _load_spec():
            state.broker_spec = await _load_broker_spec_async(broker_nm, settings)

        await asyncio.gather(
            _cache_and_bootstrap(settings),
            _get_all_tokens_async(router),
            _load_spec(),
        )

        # 토큰 발급 phase 완료 시그널 — WS 유니캐스트가 stale broker_statuses를
        # 전송하지 않도록 보장 (token_ready_event.wait()에서 대기 중인 태스크가 깨어남)
        state.token_ready_event.set()

        # 가상 예수금 로컬 DB 복원 (init()은 _cache_and_bootstrap 내부에서 완료)
        from backend.app.services import settlement_engine
        await settlement_engine.restore_state()

        _t_parallel_end = time.perf_counter()
        logger.info(
            "[시작] [앱시작] 준비완료 -- %.0fms",
            (_t_parallel_end - _t_parallel_start) * 1000,
        )

        # ── broker_spec 결과 반영 ──
        if isinstance(state.broker_spec, list):
            acnt_no = settings.get(f"{broker_nm}_account_no", "")
            from backend.app.services.engine_service import log_message
            log_message(f"[시작] 설정로딩 -- TR {len(state.broker_spec)}개, 계좌: {acnt_no or '미설정'}")

        # ── token 결과 반영 ──
        token = state.broker_tokens.get(broker_nm)
        if token:
            state.access_token = token
        else:
            from backend.app.services.engine_service import log_message
            log_message(f" [연결] 증권사 토큰 발급 실패. 스냅샷 전용 모드로 기동.")
            state.access_token = None

        # ── 계좌 조회용 REST = Router의 AuthProvider에서 REST 실시간 인스턴스 공유 ──
        _auth_provider = router.auth
        if hasattr(_auth_provider, 'rest_api'):
            _is_test = is_test_mode(settings)
            # 증권사별 state 분리
            _rest_api = _auth_provider.rest_api
            _rest_api._acnt_no = str(settings.get(f"{broker_nm}_account_no", "") or "")
            for spec in state.broker_spec:
                tr = spec.get("tr_id", "")
                if tr == "kt00001":
                    _rest_api._deposit_tr_id = tr
                elif tr == "kt00018":
                    _rest_api._balance_tr_id = tr
                elif tr == "ka00001":
                    _rest_api._account_tr_id = tr
            state.broker_rest_apis[broker_nm] = _rest_api
            from backend.app.services.engine_service import log_message
            log_message(f"[연결] {broker_nm} 증권사 연결 완료 (테스트모드={_is_test})")



        _is_test_flag  = is_test_mode(settings)
        _mode_str      = "테스트모드" if _is_test_flag else "실전투자"
        _broker_str    = "증권사"
        _acnt_raw      = (
            settings.get(f"{broker_nm}_account_no")
            or "미설정"
        )
        _acnt_disp     = (_acnt_raw[:4] + "****") if len(_acnt_raw) >= 4 else _acnt_raw
        _real_warn     = " ★ 실제 자금 투입 ★" if not _is_test_flag else ""
        logger.info("[시작] 기동 완료 -- %s %s / 계좌: %s%s", _broker_str, _mode_str, _acnt_disp, _real_warn)

        if state.access_token:
            from backend.app.services.engine_service import log_message, _get_settings, _sync_sell_overrides_from_settings
            state.auto_trade = AutoTradeManager(
                log_callback=log_message,
                get_settings_fn=_get_settings,
            )
            _sync_sell_overrides_from_settings()

        from backend.app.services.engine_service import _broadcast_engine_ws
        await _broadcast_engine_ws()

        # ── 백그라운드 태스크로 파이프라인 루프 시작 (Step 7: 중앙 코디네이터 연동) ──
        # 테스트모드와 무관하게 항상 시작 (UI 전송 등 돈과 무관한 기능 실행)
        # 순서 보장: Ingestion -> Compute
        # Gateway 루프는 app.py에서 독립적으로 시작 (파이프라인 독립성 보장)
        from backend.app.pipelines.pipeline_compute import start_compute_loop
        from backend.app.services import engine_service as es

        compute_task = asyncio.create_task(start_compute_loop(es))

        # ── WS 구간 변화 감지 루프 (WS 연결/해제 단일 책임) ──
        state.engine_stop_event.clear()
        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window

        while not state.engine_stop_event.is_set():
            _settings = state.integrated_system_settings_cache
            _should_connect_ws = await is_ws_subscribe_window(_settings) if state.access_token else False

            if _should_connect_ws:
                if state.connector_manager is None:
                    try:
                        from backend.app.core.connector_manager import ConnectorManager
                        from backend.app.services.engine_service import _broker_message_handler
                        from backend.app.services.core_queues import get_tick_queue
                        _mgr = ConnectorManager()
                        _mgr.set_message_callback(_broker_message_handler)
                        tick_queue = get_tick_queue()
                        for connector in _mgr._connectors.values():
                            if hasattr(connector, 'set_queue_callback'):
                                connector.set_queue_callback(tick_queue)
                        logger.info("[연결] Connector Queue 콜백 설정 완료 (tick_queue)")
                        state.connector_manager = _mgr
                        state.active_connector = _mgr.get_connector(broker_nm)
                        await _mgr.connect_all()
                        logger.info("[연결] 실시간 연결 완료")
                        await _broadcast_engine_ws()
                    except Exception as e:
                        logger.error("[연결] 실시간 연결 초기화 실패: %s", e, exc_info=True)
                        state.connector_manager = None
                        state.active_connector = None
            else:
                if state.connector_manager is not None:
                    try:
                        if hasattr(state.connector_manager, 'disconnect_all'):
                            await state.connector_manager.disconnect_all()
                        state.connector_manager = None
                        state.active_connector = None
                        logger.info("[연결] 실시간 연결 해제 완료")
                        await _broadcast_engine_ws()
                    except Exception as e:
                        logger.error("[연결] 실시간 연결 해제 실패: %s", e, exc_info=True)

            stop_wait = asyncio.create_task(state.engine_stop_event.wait())
            change_wait = asyncio.create_task(state.ws_window_changed_event.wait())
            done, pending = await asyncio.wait(
                [stop_wait, change_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
            state.ws_window_changed_event.clear()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        from backend.app.services.engine_service import log_message
        log_message(f" [시작] 예외: {e}")
        logger.warning("[시작] 엔진 루프 예외", exc_info=True)
    finally:
        # ── 백그라운드 태스크 종료 (Step 7: 중앙 코디네이터 연동) ───────────────
        if gateway_task:
            gateway_task.cancel()
        if oms_task:
            oms_task.cancel()
        if compute_task:
            compute_task.cancel()

        try:
            if gateway_task:
                await gateway_task
        except asyncio.CancelledError:
            pass
        try:
            if oms_task:
                await oms_task
        except asyncio.CancelledError:
            pass
        try:
            if compute_task:
                await compute_task
        except asyncio.CancelledError:
            pass

        logger.info("[엔진] 백그라운드 태스크 종료 완료")

        # ── Event Bus 종료 ───────────────────────────────────────────────────
        if state.connector_manager:
            await state.connector_manager.disconnect_all()
        else:
            if state.active_connector:
                await state.active_connector.disconnect()
        state.connector_manager = None
        state.active_connector = None
        # 증권사별 REST API 클라이언트 정리
        for _broker_id, _rest_api in state.broker_rest_apis.items():
            try:
                await _rest_api.revoke_token()
            except Exception as e:
                logger.warning("[엔진] %s 토큰 폐기 실패: %s", _broker_id, e)
            if hasattr(_rest_api, '_reset_client'):
                await _rest_api._reset_client()
            elif hasattr(_rest_api, '_client') and _rest_api._client:
                await _rest_api._client.aclose()
        state.broker_rest_apis.clear()
        state.broker_tokens.clear()
        state.running = False
        from backend.app.services.engine_service import broadcast_engine_status, log_message, get_current_kst_time
        await broadcast_engine_status()
        log_message(f"[시작] 정지됨 ({get_current_kst_time()})")
