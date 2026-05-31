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
from backend.app.services.engine_state import (
    _broker_tokens,
    _login_ok,
    _connector_manager,
    _subscribed_stocks,
    _checked_stocks,
    # _radar_cnsr_order 삭제
    _sector_stock_layout,
    # _avg_amt_5d 제거: _master_stocks_cache에서 직접 사용
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_rest_radar_quote_cache)
    _rest_radar_rest_once,
    _running,
    _engine_loop_ref,
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_latest_trade_amounts, _latest_trade_prices, _latest_strength)
    _preboot_cache_loaded,
    _preboot_ready_event,
    _account_rest_lock,
    _engine_user_id,
    _settings_cache,
    _broker_spec,
    _access_token,
    _rest_api,
    _avg_amt_needs_bg_refresh,
    _auto_trade,
    _kiwoom_connector,
    _engine_stop_event,
)

logger = get_logger("engine")


async def _cache_and_bootstrap(settings: dict) -> None:
    """캐시 선행 로드 → engine-ready WS 전송 → 부트스트랩 순차 실행.

    Cache_Preboot 실패 시 내부 try/except에서 경고 로그 후 계속 진행.
    Bootstrap은 Cache_Preboot 완료 이후에만 실행 (순차 의존 보존).
    적격종목 캐시 없으면 빈 상태로 초기화하고 상태 플래그 설정.
    """
    # ── 캐시 선행 로드 (WS 구간 안이면 내부에서 시세 0으로 적재) ──
    await _load_caches_preboot(settings)

    # ── 앱준비 백그라운드 실행 (Fire and Forget - 웹서버 기동 차단 방지) ──
    try:
        from backend.app.services.engine_bootstrap import _bootstrap_sector_stocks_async
        asyncio.create_task(_bootstrap_sector_stocks_async())
        logger.info("[시작] 앱준비 백그라운드 태스크 시작 (비차단)")
    except RuntimeError as e:
        # 적격종목 캐시 없는 경우: 빈 상태로 초기화하고 계속 진행
        logger.warning("[시작] 적격종목 캐시 없음: %s. 빈 상태로 초기화합니다.", e)
    except Exception as e:
        # 기타 예외: 경고 로그 후 계속 진행
        logger.warning("[시작] 앱준비 예외: %s. 계속 진행합니다.", e, exc_info=True)

    # 앱준비(필터링) 완료 여부와 상관없이 engine-ready 전송
    try:
        from backend.app.web.ws_manager import ws_manager
        ws_manager.broadcast("engine-ready", {"_v": 1, "ready": True})
        logger.info("[시작] 데이터준비 완료 -- 실시간 준비됨")
    except Exception:
        logger.warning("[시작] engine-ready 브로드캐스트 실패", exc_info=True)


async def _get_token_async(router) -> str | None:
    """동기 토큰 발급을 asyncio.to_thread()로 래핑하여 이벤트 루프 블로킹 방지.

    router.auth.get_access_token()은 내부에서 self._lock으로 토큰 캐시를 보호하며,
    requests.post() 동기 HTTP 호출을 수행한다 [출처: kiwoom_rest.py:86-89, 195].
    실패 시 None 반환 + 경고 로그 (스냅샷 전용 모드) [출처: engine_loop.py:131-133].
    """
    try:
        token = await asyncio.to_thread(router.auth.get_access_token)
        return token
    except Exception as e:
        logger.warning("[연결] 토큰 발급 예외: %s. 확정데이터 전용 모드로 기동.", e, exc_info=True)
        return None


async def _get_all_tokens_async(router) -> None:
    """
    broker_config에 등장하는 모든 증권사 토큰을 병렬 발급한다.
    router._auth_cache에 이미 모든 증권사 AuthProvider가 등록되어 있다.
    발급된 토큰은 _broker_tokens[broker_id]로 저장한다.
    """
    auth_cache: dict = getattr(router, "_auth_cache", {})
    if not auth_cache:
        return

    async def _fetch_one(broker_id: str, auth_provider) -> tuple[str, str | None]:
        try:
            token = await asyncio.to_thread(auth_provider.get_access_token)
            from backend.app.core.broker_registry import BROKER_DISPLAY_NAMES
            disp = BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper())
            logger.info("[연결] %s 접속 완료", disp)
            return broker_id, token
        except Exception as e:
            logger.warning("[연결] %s 토큰 발급 실패: %s", broker_id.upper(), e, exc_info=True)
            return broker_id, None

    results = await asyncio.gather(
        *[_fetch_one(bid, ap) for bid, ap in auth_cache.items()],
        return_exceptions=True,
    )

    _broker_tokens.clear()

    for result in results:
        if isinstance(result, tuple):
            broker_id, token = result
            if token:
                _broker_tokens[broker_id] = token


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
    logger.info("[엔진] run_engine_loop() 진입")
    import backend.app.services.engine_state as _es
    global _login_ok, _connector_manager, _broker_tokens, _subscribed_stocks
    global _checked_stocks  # _radar_cnsr_order 삭제
    global _sector_stock_layout  # _avg_amt_5d 제거
    global _rest_radar_rest_once, _running, _engine_loop_ref
    global _preboot_cache_loaded, _preboot_ready_event, _account_rest_lock
    global _engine_user_id, _settings_cache, _broker_spec, _access_token
    global _rest_api, _avg_amt_needs_bg_refresh, _auto_trade, _kiwoom_connector
    global _engine_stop_event

    _t0 = time.perf_counter()

    _login_ok = False
    _es._login_ok = False
    _connector_manager = None
    _broker_tokens.clear()
    _subscribed_stocks.clear()
    from backend.app.services.engine_state import _notify_reg_ack, _cancel_price_trace_delayed_task
    _notify_reg_ack()
    _cancel_price_trace_delayed_task()
    _checked_stocks.clear()
    # _radar_cnsr_order 삭제: clear() 제거
    _sector_stock_layout.clear()
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache([])
    # 실시간 틱 데이터 캐시 초기화 삭제 (_rest_radar_quote_cache.clear() 제거)
    _rest_radar_rest_once.clear()
    _running = True
    import backend.app.services.engine_state as _es
    _es._running = True
    _engine_loop_ref = asyncio.get_running_loop()
    # 실시간 틱 데이터 캐시 초기화 삭제 (캐시가 삭제되었으므로 초기화 불필요)
    # 캐시선행 플래그 초기화
    _preboot_cache_loaded = False
    _preboot_ready_event.clear()
    # 계좌 REST Lock 초기화 -- 이전 세션 잠금 상태 초기화
    _account_rest_lock = None

    # ── 전역 이벤트 버스 (Queues) 초기화 (Step 1: 파이프라인 아키텍처) ────
    from backend.app.services.core_queues import initialize_queues
    initialize_queues()
    logger.info("[엔진] 전역 이벤트 버스 (Queues) 초기화 완료")

    gateway_task = None
    oms_task = None
    compute_task = None

    try:
        # _settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = _settings_cache
        logger.info("[기동시간] 설정 로드: %.0fms", (time.perf_counter() - _t0) * 1000)

        # 엔진 내부 준비 완료 시그널 — Uvicorn 리스닝 + 브라우저 열기 즉시 허용
        _preboot_ready_event.set()

        # ── broker/router 생성 (settings만 필요, gather 이전에 준비) ──
        broker_nm: str = str(settings.get("broker", "") or "").lower().strip()
        router = get_router(settings)

        # ── API 키 검증: broker_config.websocket 기준 모든 증권사 확인 ──
        broker_config = settings.get("broker_config") or {}
        ws_val = str(broker_config.get("websocket") or broker_nm).lower().strip()
        ws_brokers = [b.strip() for b in ws_val.split(",") if b.strip()]

        valid_brokers = []
        for _bk in ws_brokers:
            _key = settings.get(f"{_bk}_app_key", "")
            _sec = settings.get(f"{_bk}_app_secret", "")
            if _key and _sec:
                valid_brokers.append(_bk)
            else:
                from backend.app.services.engine_service import _log
                _log(f" [시작] 증권사 API 키가 설정되지 않았습니다. 일반설정에서 입력하세요.")

        if not valid_brokers:
            from backend.app.services.engine_service import _log, _broadcast_engine_ws
            _log(f" [시작] 유효한 API 키가 없습니다. 일반설정에서 증권사 API 키를 입력하세요.")
            _broadcast_engine_ws()
            # 엔진 중단하지 않고 계속 진행 (테스트모드/스냅샷 전용 모드 허용)

        # REST/토큰 발급은 기준 증권사(broker_nm) 기준 유지

        # ── 병렬 초기화: 캐시+앱준비 / 토큰 발급 / 브로커 스펙 로드 ──
        _t_parallel_start = time.perf_counter()

        _broker_spec = await _load_broker_spec_async(broker_nm, settings)
        await _get_all_tokens_async(router)
        await _cache_and_bootstrap(settings)

        _t_parallel_end = time.perf_counter()
        logger.info(
            "[시작] [앱시작] 준비완료 -- %.0fms",
            (_t_parallel_end - _t_parallel_start) * 1000,
        )
        logger.info("[기동시간] 병렬 초기화: %.0fms", (_t_parallel_end - _t_parallel_start) * 1000)

        # ── broker_spec 결과 반영 ──
        if isinstance(_broker_spec, list):
            acnt_no = settings.get(f"{broker_nm}_account_no", "")
            from backend.app.services.engine_service import _log
            _log(f"[시작] 설정로딩 -- TR {len(_broker_spec)}개, 계좌: {acnt_no or '미설정'}")

        # ── token 결과 반영 ──
        token = _broker_tokens.get(broker_nm)
        if token:
            _access_token = token
        else:
            from backend.app.services.engine_service import _log
            _log(f" [연결] 증권사 토큰 발급 실패. 스냅샷 전용 모드로 기동.")
            _access_token = None

        # ── 계좌 조회용 REST = Router의 AuthProvider에서 REST 실시간 인스턴스 공유 ──
        _auth_provider = router.auth
        if hasattr(_auth_provider, 'rest_api'):
            _is_test = is_test_mode(settings)
            _rest_api = _auth_provider.rest_api
            _es._rest_api = _rest_api
            _rest_api._acnt_no = str(settings.get(f"{broker_nm}_account_no", "") or "")
            for spec in _broker_spec:
                tr = spec.get("tr_id", "")
                if tr == "kt00001":
                    _rest_api._deposit_tr_id = tr
                elif tr == "kt00018":
                    _rest_api._balance_tr_id = tr
                elif tr == "ka00001":
                    _rest_api._account_tr_id = tr
            from backend.app.services.engine_service import _log
            _log(f"[연결] 증권사 REST API 인스턴스 연결 완료 (테스트모드={_is_test}, 토큰 단일 캐시)")



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

        if _access_token:
            from backend.app.services.engine_service import _log, _get_settings, _sync_sell_overrides_from_settings
            _auto_trade = AutoTradeManager(
                log_callback=_log,
                get_settings_fn=_get_settings,
            )
            _sync_sell_overrides_from_settings()
            from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
            _should_connect_ws = await is_ws_subscribe_window(settings)
            if _should_connect_ws:
                try:
                    # ConnectorManager 초기화 (다중 증권사 동시 연결 지원)
                    from backend.app.core.connector_manager import ConnectorManager
                    _mgr = ConnectorManager(settings)
                    from backend.app.services.engine_service import _broker_message_handler
                    _mgr.set_message_callback(_broker_message_handler)

                    # ── Connector Queue 콜백 설정 (Step 1: tick_queue 연결) ────
                    from backend.app.services.core_queues import get_tick_queue
                    kiwoom_connector = _mgr.get_connector(broker_nm)
                    if kiwoom_connector and hasattr(kiwoom_connector, 'set_queue_callback'):
                        kiwoom_connector.set_queue_callback(get_tick_queue())
                        logger.info("[연결] Connector Queue 콜백 설정 완료 (tick_queue)")

                    await _mgr.connect_all()
                    _connector_manager = _mgr
                    # 하위 호환: 기존 변수에 개별 Connector 할당
                    _kiwoom_connector = kiwoom_connector
                    logger.info("[연결] 실시간 연결 완료")
                except Exception as e:
                    logger.error("[연결] 실시간 연결 초기화 실패: %s", e, exc_info=True)
                    _connector_manager = None
                    _kiwoom_connector = None
            else:
                logger.info("[연결] 실시간 구독 구간 밖 또는 실시간 연결 OFF — Connector 연결 생략")

        logger.info("[기동시간] 전체 기동: %.0fms", (time.perf_counter() - _t0) * 1000)
        import backend.app.services.engine_state as _engine_state
        _engine_state._access_token = _access_token
        _engine_state._connector_manager = _connector_manager
        _engine_state._kiwoom_connector = _kiwoom_connector

        from backend.app.services.engine_service import _broadcast_engine_ws
        _broadcast_engine_ws()  # 엔진 루프 진입 직후 헤더에 즉시 반영

        # ── 백그라운드 태스크로 파이프라인 루프 시작 (Step 7: 중앙 코디네이터 연동) ──
        # 테스트모드와 무관하게 항상 시작 (UI 전송 등 돈과 무관한 기능 실행)
        # 순서 보장: Ingestion -> Compute -> OMS -> Gateway
        from backend.app.services.pipeline_compute import start_compute_loop
        from backend.app.services.pipeline_oms import start_oms_loop
        from backend.app.services.pipeline_gateway import start_gateway_loop
        from backend.app.services import engine_service as es

        compute_task = asyncio.create_task(start_compute_loop(es))
        logger.info("[엔진] Compute Engine 루프 시작 (백그라운드 태스크)")

        oms_task = asyncio.create_task(start_oms_loop(es))
        logger.info("[엔진] OMS 루프 시작 (백그라운드 태스크)")

        gateway_task = asyncio.create_task(start_gateway_loop())
        logger.info("[엔진] Gateway 루프 시작 (백그라운드 태스크)")

        # ── 엔진 종료 대기 (WS 연결/해제는 스케줄러가 관리) ──
        _engine_stop_event.clear()
        await _engine_stop_event.wait()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        from backend.app.services.engine_service import _log
        _log(f" [시작] 예외: {e}")
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
        if _connector_manager:
            await _connector_manager.disconnect_all()
        else:
            if _kiwoom_connector:
                await _kiwoom_connector.disconnect()
        _connector_manager = None
        _kiwoom_connector = None
        _rest_api = None
        _running = False
        import backend.app.services.engine_state as _es
        _es._running = False
        from backend.app.services.engine_service import _broadcast_engine_ws, _log, _now_kst
        _broadcast_engine_ws()
        _log(f"[시작] 정지됨 ({_now_kst()})")
