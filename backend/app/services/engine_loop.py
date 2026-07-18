# -*- coding: utf-8 -*-
"""
엔진 asyncio 메인 루프 -- 설정·브로커·WS 초기 연결.

`engine_state` 및 각 전문 모듈에서 직접 import하여 전역 상태를 읽고 갱신한다.
WS 연결/해제는 스케줄러(daily_time_scheduler)가 전적으로 관리한다.
"""
from __future__ import annotations
import asyncio
import time
from backend.app.core.broker_factory import get_router
from backend.app.core.broker_providers import AuthProvider
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
import logging
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.trading import AutoTradeManager
from backend.app.services.engine_cache import _load_caches_preboot
from backend.app.services import engine_state
logger = logging.getLogger(__name__)


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
        logger.info("[연산] 데이터 준비 완료 — 실시간 준비됨")
    except Exception:
        logger.warning("[연산] 엔진 준비 브로드캐스트 실패", exc_info=True)


async def _get_all_tokens_async(router) -> None:
    """
    broker_config에 등장하는 모든 증권사 토큰을 병렬 발급한다.
    router._auth_cache에 없는 증권사(stock 전용 등)도 _create_provider로 생성하여 발급.
    발급된 토큰은 state.broker_tokens[broker_id]로 저장한다.
    """
    auth_cache: dict[str, AuthProvider] = getattr(router, "_auth_cache", {})

    # broker_config + confirmed_data_broker의 모든 증권사 수집 (auth_cache에 없는 stock 증권사 포함)
    # 캐시는 app.py 시작 시 build_engine_settings_dict로 정규화되어
    # broker_config가 항상 dict로 존재함 (P20 폴백 금지).
    broker_config = engine_state.state.integrated_system_settings_cache["broker_config"]
    all_broker_ids = set(auth_cache.keys())
    for _feat, _bname in broker_config.items():
        _bname = str(_bname or "").lower().strip()
        if _bname:
            all_broker_ids.add(_bname)
    _confirmed_broker = str(
        engine_state.state.integrated_system_settings_cache.get("confirmed_data_broker") or ""
    ).lower().strip()
    if _confirmed_broker:
        all_broker_ids.add(_confirmed_broker)

    # API 키가 설정된 증권사만 발급 대상
    valid_broker_ids = []
    for bid in all_broker_ids:
        _key = engine_state.state.integrated_system_settings_cache.get(f"{bid}_app_key", "")
        _sec = engine_state.state.integrated_system_settings_cache.get(f"{bid}_app_secret", "")
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
                    engine_state.state.integrated_system_settings_cache, auth_cache,
                )
            assert auth_provider is not None
            token = await auth_provider.get_access_token()
            return broker_id, token
        except Exception as e:
            logger.warning("[연결] %s 토큰 발급 실패: %s", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()), e, exc_info=True)
            return broker_id, None

    results = await asyncio.gather(
        *[_fetch_one(bid) for bid in valid_broker_ids],
        return_exceptions=True,
    )

    engine_state.state.broker_tokens.clear()

    for result in results:
        if isinstance(result, tuple):
            broker_id, token = result
            if token:
                engine_state.state.broker_tokens[broker_id] = token


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
                    logger.warning("[연산] 역할 매핑 형식 오류: %s (기대: 사전 형식)", type(role_mappings))
                    return []
            else:
                logger.warning("[연산] 증권사 명세 형식 오류: %s (기대: 사전 형식)", type(spec))
                return []
        return []
    except Exception as e:
        logger.warning("[연산] 증권사 스펙 로드 실패: %s", e, exc_info=True)
        return []


async def run_engine_loop() -> None:

    _t0 = time.perf_counter()

    engine_state.state.login_ok = False
    engine_state.state.connector_manager = None
    engine_state.state.broker_tokens.clear()
    engine_state.state.token_ready_event.clear()
    # _master_stocks_cache에서 "_subscribed" 제거
    for entry in engine_state.state.master_stocks_cache.values():
        entry.pop("_subscribed", None)
    from backend.app.services.engine_state import _notify_reg_ack
    _notify_reg_ack()
    engine_state.state.integrated_system_settings_cache["sector_stock_layout"] = []
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache([])
    engine_state.state.running = True
    engine_state.state.engine_loop_ref = asyncio.get_running_loop()
    # 캐시선행 플래그 초기화
    engine_state.state.preboot_cache_loaded = False
    engine_state.state.preboot_ready_event.clear()
    # 계좌 REST Lock 초기화 -- 이전 세션 잠금 상태 초기화
    engine_state.state.account_rest_lock = None

    # 전역 이벤트 버스 (Queues)는 app.py lifespan에서 이미 초기화됨

    try:
        # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = engine_state.state.integrated_system_settings_cache

        # ── WS 구독 상태 초기화 (표준 기동 순서: 초기화 → 연결 → 구독) ──
        # 엔진 루프의 WS 연결/구독/틱 수신 이전에 실행 보장 (경쟁 조건 제거, P22 데이터 정합성).
        # preboot_cache_loaded=False 상태이므로 _reset_realtime_fields()는 자동 스킵되고
        # engine_cache._load_caches_preboot()에서 캐시 로드 후 수행됨.
        # schedule_engine_task()가 정상 동작하도록 engine_loop_ref 설정 이후에 실행.
        from backend.app.services.daily_time_scheduler import _init_ws_subscribe_state
        await _init_ws_subscribe_state()

        # 엔진 내부 준비 완료 시그널 — Uvicorn 리스닝 + 브라우저 열기 즉시 허용
        engine_state.state.preboot_ready_event.set()

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
                from backend.app.services.engine_lifecycle import log_message
                log_message(f" [구동] {BROKER_DISPLAY_NAMES.get(_bk, _bk)} API 키가 설정되지 않았습니다. 일반설정에서 입력하세요.")

        if not valid_brokers:
            from backend.app.services.engine_lifecycle import log_message, broadcast_engine_status
            log_message(f" [구동] 유효한 API 키가 없습니다 (대상: {', '.join(BROKER_DISPLAY_NAMES.get(b, b) for b in ws_brokers)}). 일반설정에서 증권사 API 키를 입력하세요.")
            await broadcast_engine_status()
            # 엔진 중단하지 않고 계속 진행 (테스트모드/스냅샷 전용 모드 허용)

        # REST/토큰 발급은 기준 증권사(broker_nm) 기준 유지

        # ── 병렬 초기화: 캐시+앱준비 / 토큰 발급 / 브로커 스펙 로드 ──
        _t_parallel_start = time.perf_counter()

        # 3개 독립 파이프라인 병렬 실행 — broker_spec은 gather 완료 후 사용
        async def _load_spec():
            engine_state.state.broker_spec = await _load_broker_spec_async(broker_nm, settings)

        await asyncio.gather(
            _cache_and_bootstrap(settings),
            _get_all_tokens_async(router),
            _load_spec(),
        )

        # 토큰 발급 phase 완료 시그널 — WS 유니캐스트가 stale broker_statuses를
        # 전송하지 않도록 보장 (token_ready_event.wait()에서 대기 중인 태스크가 깨어남)
        engine_state.state.token_ready_event.set()

        # 가상 예수금 로드는 _cache_and_bootstrap(→ engine_cache)에서 load_state로 수행

        _t_parallel_end = time.perf_counter()
        logger.info(
            "[연산] 준비 완료 — %.0fms",
            (_t_parallel_end - _t_parallel_start) * 1000,
        )

        # ── broker_spec 결과 반영 ──
        if isinstance(engine_state.state.broker_spec, list):
            acnt_no = settings.get(f"{broker_nm}_account_no", "")
            from backend.app.services.engine_lifecycle import log_message
            log_message(f"[연산] 설정 로딩 — TR {len(engine_state.state.broker_spec)}개, 계좌: {acnt_no or '미설정'}")

        # ── token 결과 반영 ──
        token = engine_state.state.broker_tokens.get(broker_nm)
        if token:
            engine_state.state.access_token = token
        else:
            from backend.app.services.engine_lifecycle import log_message
            log_message(f" [연결] {BROKER_DISPLAY_NAMES.get(broker_nm, broker_nm)} 토큰 발급 실패. 스냅샷 전용 모드로 기동.")
            engine_state.state.access_token = None

        # ── 계좌 조회용 REST = Router의 AuthProvider에서 REST 실시간 인스턴스 공유 ──
        _auth_provider = router.auth
        if hasattr(_auth_provider, 'rest_api'):
            _is_test = is_test_mode(settings)
            # 증권사별 state 분리
            _rest_api = _auth_provider.rest_api
            _rest_api._acnt_no = str(settings.get(f"{broker_nm}_account_no", "") or "")
            for spec in engine_state.state.broker_spec:
                tr = spec.get("tr_id", "")
                if tr == "kt00001":
                    _rest_api._deposit_tr_id = tr
                elif tr == "kt00018":
                    _rest_api._balance_tr_id = tr
                elif tr == "ka00001":
                    _rest_api._account_tr_id = tr
            engine_state.state.broker_rest_apis[broker_nm] = _rest_api
            from backend.app.services.engine_lifecycle import log_message
            log_message(f"[연결] {BROKER_DISPLAY_NAMES.get(broker_nm, broker_nm)} 연결 완료 (테스트모드={_is_test})")



        _is_test_flag  = is_test_mode(settings)
        _mode_str      = "테스트모드" if _is_test_flag else "실전투자"
        _broker_str    = BROKER_DISPLAY_NAMES.get(broker_nm, "증권사")
        _acnt_raw      = (
            settings.get(f"{broker_nm}_account_no")
            or "미설정"
        )
        _acnt_disp     = (_acnt_raw[:4] + "****") if len(_acnt_raw) >= 4 else _acnt_raw
        _real_warn     = " ★ 실제 자금 투입 ★" if not _is_test_flag else ""
        logger.info("[연산] 기동 완료 — %s %s / 계좌: %s%s", _broker_str, _mode_str, _acnt_disp, _real_warn)

        if engine_state.state.access_token:
            from backend.app.services.engine_lifecycle import sync_sell_overrides as _sync_sell_overrides_from_settings
            from backend.app.services.engine_config import _get_settings
            engine_state.state.auto_trade = AutoTradeManager(
                get_settings_fn=_get_settings,
            )
            _sync_sell_overrides_from_settings()

        from backend.app.services.engine_account import _broadcast_buy_limit_status
        try:
            await _broadcast_buy_limit_status()
        except Exception:
            logger.warning("[연산] 매수 한도 브로드캐스트 실패", exc_info=True)

        from backend.app.services.engine_lifecycle import broadcast_engine_status as _broadcast_engine_ws
        await _broadcast_engine_ws()

        # ── 백그라운드 태스크로 파이프라인 루프 시작 (Step 7: 중앙 코디네이터 연동) ──
        # 테스트모드와 무관하게 항상 시작 (UI 전송 등 돈과 무관한 기능 실행)
        # 순서 보장: Ingestion -> Compute
        # Gateway 루프는 app.py에서 독립적으로 시작 (파이프라인 독립성 보장)
        from backend.app.pipelines.pipeline_compute import start_compute_loop

        await start_compute_loop()

        # ── WS 구간 변화 감지 루프 (WS 연결/해제 단일 책임) ──
        engine_state.state.engine_stop_event.clear()
        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window

        while not engine_state.state.engine_stop_event.is_set():
            _settings = engine_state.state.integrated_system_settings_cache
            _should_connect_ws = await is_ws_subscribe_window(_settings) if engine_state.state.access_token else False

            if _should_connect_ws:
                if engine_state.state.connector_manager is None:
                    try:
                        from backend.app.core.connector_manager import ConnectorManager
                        from backend.app.services.engine_ws import _broker_message_handler
                        from backend.app.services.core_queues import get_tick_queue
                        _mgr = ConnectorManager()
                        _mgr.set_message_callback(_broker_message_handler)
                        tick_queue = get_tick_queue()
                        for connector in _mgr._connectors.values():
                            if hasattr(connector, 'set_queue_callback'):
                                connector.set_queue_callback(tick_queue)
                        logger.info("[연결] 커넥터 큐 콜백 설정 완료 (틱 큐)")
                        engine_state.state.connector_manager = _mgr
                        engine_state.state.active_connector = _mgr.get_connector(broker_nm)
                        await _mgr.connect_all()
                        if _mgr.is_connected():
                            logger.info("[연결] 실시간 연결 완료")
                        else:
                            logger.warning("[연결] 실시간 연결 실패 — 재연결 루프 기동 중")
                        await _broadcast_engine_ws()
                    except Exception as e:
                        logger.error("[연결] 실시간 연결 초기화 실패: %s", e, exc_info=True)
                        engine_state.state.connector_manager = None
                        engine_state.state.active_connector = None
            else:
                if engine_state.state.connector_manager is not None:
                    try:
                        if hasattr(engine_state.state.connector_manager, 'disconnect_all'):
                            await engine_state.state.connector_manager.disconnect_all()
                        engine_state.state.connector_manager = None
                        engine_state.state.active_connector = None
                        logger.info("[연결] 실시간 연결 해제 완료")
                        await _broadcast_engine_ws()
                    except Exception as e:
                        logger.error("[연결] 실시간 연결 해제 실패: %s", e, exc_info=True)

            stop_wait = asyncio.create_task(engine_state.state.engine_stop_event.wait())
            change_wait = asyncio.create_task(engine_state.state.ws_window_changed_event.wait())
            done, pending = await asyncio.wait(
                [stop_wait, change_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
            engine_state.state.ws_window_changed_event.clear()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        from backend.app.services.engine_lifecycle import log_message
        log_message(f" [구동] 예외: {e}")
        logger.warning("[연산] 엔진 루프 예외", exc_info=True)
    finally:
        # ── 백그라운드 태스크 종료 (Step 7: 중앙 코디네이터 연동) ───────────────
        # start_compute_loop()는 _compute_task/_sector_recompute_task 서브태스크를
        # 생성 후 즉시 반환하므로, 외부 태스크 취소로는 실제 루프가 종료되지 않음.
        # stop_compute_loop()를 호출하여 _compute_running=False + 서브태스크 취소 보장.
        from backend.app.pipelines.pipeline_compute import stop_compute_loop
        try:
            await stop_compute_loop()
        except Exception as e:
            logger.warning("[연산] 계산 루프 종료 실패: %s", e, exc_info=True)

        logger.info("[연산] 백그라운드 태스크 종료 완료")

        # ── Event Bus 종료 ───────────────────────────────────────────────────
        if engine_state.state.connector_manager:
            await engine_state.state.connector_manager.disconnect_all()
        else:
            if engine_state.state.active_connector:
                await engine_state.state.active_connector.disconnect()
        engine_state.state.connector_manager = None
        engine_state.state.active_connector = None
        # 증권사별 REST API 클라이언트 정리
        for _broker_id, _rest_api in engine_state.state.broker_rest_apis.items():
            try:
                await _rest_api.revoke_token()
            except Exception as e:
                logger.warning("[연산] %s 토큰 폐기 실패: %s", BROKER_DISPLAY_NAMES.get(_broker_id, _broker_id), e)
            if hasattr(_rest_api, '_reset_client'):
                await _rest_api._reset_client()
            elif hasattr(_rest_api, '_client') and _rest_api._client:
                await _rest_api._client.aclose()
        engine_state.state.broker_rest_apis.clear()
        engine_state.state.broker_tokens.clear()
        engine_state.state.running = False
        from backend.app.services.engine_lifecycle import broadcast_engine_status, log_message, get_current_kst_time
        await broadcast_engine_status()
        log_message(f"[연산] 정지됨 ({get_current_kst_time()})")
