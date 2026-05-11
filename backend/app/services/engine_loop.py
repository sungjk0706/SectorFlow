# -*- coding: utf-8 -*-
"""
엔진 asyncio 메인 루프 -- 설정·브로커·WS 초기 연결.

`engine_service` 모듈 객체 `es`로 전역 상태를 읽고 갱신한다.
WS 연결/해제는 스케줄러(daily_time_scheduler)가 전적으로 관리한다.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from app.core.broker_factory import get_router
from app.core.engine_settings import get_engine_settings
from app.core.logger import get_logger
from app.core.trade_mode import is_test_mode
from app.services.trading import AutoTradeManager
from app.services.engine_cache import _load_caches_preboot

logger = get_logger("engine")


async def _cache_and_bootstrap(es: ModuleType, settings: dict) -> None:
    """캐시 선행 로드 → engine-ready WS 전송 → 부트스트랩 순차 실행.

    Cache_Preboot 실패 시 내부 try/except에서 경고 로그 후 계속 진행.
    Bootstrap은 Cache_Preboot 완료 이후에만 실행 (순차 의존 보존).
    """
    # ── 캐시 선행 로드 (WS 구간 안이면 내부에서 시세 0으로 적재) ──
    await _load_caches_preboot(es, settings)

    # ── 앱준비 즉시 실행 (필터링 완료 후 engine-ready 전송) ──
    await es._bootstrap_sector_stocks_async()

    # 앱준비(필터링) 완료 → 깨끗한 데이터로 브라우저에 engine-ready 전송
    try:
        from app.web.ws_manager import ws_manager
        ws_manager.broadcast("engine-ready", {"_v": 1, "ready": True})
        logger.info("[앱준비] 데이터준비 완료 -- 실시간 준비됨")
    except Exception:
        pass


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
        logger.warning("[엔진] 토큰 발급 예외: %s. 확정데이터 전용 모드로 기동.", e)
        return None


async def _get_all_tokens_async(router, es) -> None:
    """
    broker_config에 등장하는 모든 증권사 토큰을 병렬 발급한다.
    router._auth_cache에 이미 모든 증권사 AuthProvider가 등록되어 있다.
    발급된 토큰은 es._broker_tokens[broker_id]로 저장한다.
    """
    auth_cache: dict = getattr(router, "_auth_cache", {})
    if not auth_cache:
        return

    async def _fetch_one(broker_id: str, auth_provider) -> tuple[str, str | None]:
        try:
            token = await asyncio.to_thread(auth_provider.get_access_token)
            logger.info("[엔진] 키움증권 접속 완료")
            return broker_id, token
        except Exception as e:
            logger.warning("[엔진] %s 토큰 발급 실패: %s", broker_id.upper(), e)
            return broker_id, None

    results = await asyncio.gather(
        *[_fetch_one(bid, ap) for bid, ap in auth_cache.items()],
        return_exceptions=True,
    )

    if not hasattr(es, "_broker_tokens") or not isinstance(es._broker_tokens, dict):
        es._broker_tokens = {}

    for result in results:
        if isinstance(result, tuple):
            broker_id, token = result
            if token:
                es._broker_tokens[broker_id] = token


async def _load_broker_spec_async(spec_path: Path) -> list:
    """동기 파일 I/O(json.load)를 asyncio.to_thread()로 래핑하여 이벤트 루프 블로킹 방지.

    broker_specs/{broker}.json 파일을 비동기로 로드한다 [출처: engine_loop.py:113-122].
    실패 시 빈 리스트 반환 + 경고 로그 [출처: engine_loop.py:120].
    """
    def _sync_load() -> list:
        with open(spec_path, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        return await asyncio.to_thread(_sync_load)
    except Exception as e:
        logger.warning("[엔진] broker_specs 로드 실패: %s", e)
        return []


async def run_engine_loop(es: ModuleType) -> None:
    _t0 = time.perf_counter()

    es._login_ok              = False
    es._connector_manager     = None
    es._broker_tokens         = {}
    es._subscribed_stocks.clear()
    es._notify_reg_ack()
    es._cancel_price_trace_delayed_task()
    es._checked_stocks        = set()
    es._pending_stock_details = {}
    es._radar_cnsr_order = []
    es._sector_stock_layout = []
    from app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache([])
    es._avg_amt_5d = {}
    es._rest_radar_quote_cache = {}
    es._rest_radar_rest_once = set()
    es._running               = True
    es._engine_loop_ref       = asyncio.get_running_loop()
    # 세션 시작 시 거래대금 캐시 초기화 -- 전일 누적값 오염 방지
    es._latest_trade_amounts.clear()
    es._latest_trade_prices.clear()
    es._latest_strength.clear()
    # 캐시선행 플래그 초기화
    es._preboot_cache_loaded = False
    es._preboot_ready_event.clear()
    # 계좌 REST Lock 초기화 -- 이전 세션 잠금 상태 초기화
    es._account_rest_lock = None

    try:
        settings = await get_engine_settings(es._engine_user_id or None)
        es._settings_cache = settings
        logger.info("[기동시간] 설정 로드: %.0fms", (time.perf_counter() - _t0) * 1000)

        # 엔진 내부 준비 완료 시그널 — Uvicorn 리스닝 + 브라우저 열기 즉시 허용
        es._preboot_ready_event.set()

        # ── broker/router 생성 (settings만 필요, gather 이전에 준비) ──
        broker_nm: str = str(settings.get("broker", "kiwoom") or "kiwoom").lower().strip()
        _spec_path = (
            Path(__file__).resolve().parent.parent.parent
            / "data" / "broker_specs" / f"{broker_nm}.json"
        )
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
                es._log(f" [엔진] {_bk.upper()} API 키가 설정되지 않았습니다. 일반설정에서 입력하세요.")

        if not valid_brokers:
            es._log(f" [엔진] 유효한 API 키가 없습니다. 일반설정에서 증권사 API 키를 입력하세요.")
            es._running = False
            es._broadcast_engine_ws()
            return

        # REST/토큰 발급은 기준 증권사(broker_nm) 기준 유지
        api_key    = settings.get(f"{broker_nm}_app_key", "")
        api_secret = settings.get(f"{broker_nm}_app_secret", "")

        # ── 병렬 초기화: 캐시+앱준비 / 토큰 발급 / 브로커 스펙 로드 ──
        _t_parallel_start = time.perf_counter()

        _cache_result, token_result, broker_spec_result, _ = await asyncio.gather(
            _cache_and_bootstrap(es, settings),
            _get_token_async(router),
            _load_broker_spec_async(_spec_path),
            _get_all_tokens_async(router, es),
            return_exceptions=True,
        )

        _t_parallel_end = time.perf_counter()
        logger.info(
            "[엔진] [앱시작] 준비완료 -- %.0fms",
            (_t_parallel_end - _t_parallel_start) * 1000,
        )
        logger.info("[기동시간] 병렬 초기화: %.0fms", (_t_parallel_end - _t_parallel_start) * 1000)

        # ── gather 결과 반영: _cache_and_bootstrap ──
        if isinstance(_cache_result, BaseException):
            logger.warning("[엔진] 저장데이터+앱준비 예외: %s", _cache_result)

        # ── gather 결과 반영: broker_spec ──
        if isinstance(broker_spec_result, BaseException):
            es._broker_spec = []
            es._log(f" [엔진] broker_specs/{broker_nm}.json 로드 실패: {broker_spec_result}")
        elif isinstance(broker_spec_result, list):
            es._broker_spec = broker_spec_result
            acnt_no = settings.get(f"{broker_nm}_account_no", "") or settings.get("kiwoom_account_no", "")
            es._log(f"[엔진] {broker_nm.upper()} [키움증권] 설정로딩 -- TR {len(es._broker_spec)}개, 계좌: {acnt_no or '미설정'}")
        else:
            es._broker_spec = []

        # ── gather 결과 반영: token ──
        if isinstance(token_result, BaseException):
            es._log(f" [엔진] 토큰 발급 예외: {token_result}. 스냅샷 전용 모드로 기동.")
            es._access_token = None
        elif token_result:
            es._access_token = token_result
        else:
            es._log(f" [엔진] {broker_nm.upper()} 토큰 발급 실패. 스냅샷 전용 모드로 기동.")
            es._access_token = None

        # ── 계좌 조회용 REST = Router의 AuthProvider에서 REST API 인스턴스 공유 ──
        _auth_provider = router.auth
        if hasattr(_auth_provider, 'rest_api'):
            _is_test = is_test_mode(settings)
            es._rest_api = _auth_provider.rest_api
            es._rest_api._acnt_no = str(settings.get(f"{broker_nm}_account_no", "") or settings.get("kiwoom_account_no", "") or "")
            for spec in es._broker_spec:
                tr = spec.get("tr_id", "")
                if tr == "kt00001":
                    es._rest_api._deposit_tr_id = tr
                elif tr == "kt00018":
                    es._rest_api._balance_tr_id = tr
                elif tr == "ka00001":
                    es._rest_api._account_tr_id = tr
            es._log(f"[엔진] {broker_nm.upper()} REST API 인스턴스 연결 완료 (테스트모드={_is_test}, 토큰 단일 캐시)")

        # ── _rest_api 설정 후 적격종목 + 앱준비 재실행 (캐시 만료 시) ──
        if not es._sector_stock_layout and es._rest_api:
            try:
                from app.core.industry_map import (
                    fetch_ka10099_eligible_stocks, save_eligible_stocks_cache,
                )
                import app.core.industry_map as _ind_mod
                _fresh = await fetch_ka10099_eligible_stocks(es._rest_api)
                if _fresh:
                    _ind_mod._eligible_stock_codes = _fresh
                    await asyncio.to_thread(save_eligible_stocks_cache, _fresh)
                    logger.info(
                        "[앱준비] 매매적격종목 저장데이터 만료 -- ka10099 서버 다운로드 %d종목, 앱준비 재실행",
                        len(_fresh),
                    )
                    await es._bootstrap_sector_stocks_async()
            except Exception as _e:
                logger.warning("[앱준비] _rest_api 설정 후 ka10099 다운로드 실패: %s", _e)

        # ── _rest_api 설정 후 5일봉 캐시 갱신 필요 여부 재확인 ──
        if getattr(es, '_avg_amt_needs_bg_refresh', False):
            logger.info(
                "[앱준비][장외갱신] _rest_api 설정 완료 -- 5일 평균 저장데이터 갱신 예약 (%d종목)",
                len(es._avg_amt_5d),
            )
            asyncio.get_event_loop().create_task(es._bg_refresh_avg_amt_5d())

        _is_test_flag  = is_test_mode(settings)
        _mode_str      = "테스트모드" if _is_test_flag else "실전투자"
        _broker_str    = broker_nm.upper()
        _acnt_raw      = (
            settings.get(f"{broker_nm}_account_no")
            or settings.get("kiwoom_account_no")
            or "미설정"
        )
        _acnt_disp     = (_acnt_raw[:4] + "****") if len(_acnt_raw) >= 4 else _acnt_raw
        _real_warn     = " ★ 실제 자금 투입 ★" if not _is_test_flag else ""
        logger.info("[엔진] 기동 완료 -- %s %s / 계좌: %s%s", _broker_str, _mode_str, _acnt_disp, _real_warn)

        if es._access_token:
            es._auto_trade = AutoTradeManager(
                log_callback=es._log,
                get_settings_fn=es._get_settings,
            )
            es._sync_sell_overrides_from_settings()
            from app.services.daily_time_scheduler import is_ws_subscribe_window
            _should_connect_ws = is_ws_subscribe_window(settings)
            if _should_connect_ws:
                try:
                    # ConnectorManager 초기화 (다중 증권사 동시 연결 지원)
                    from app.core.connector_manager import ConnectorManager
                    _mgr = ConnectorManager(settings)
                    _mgr.set_message_callback(es._kiwoom_message_handler)
                    await _mgr.connect_all()
                    es._connector_manager = _mgr
                    # 하위 호환: 기존 변수에 개별 Connector 할당
                    es._kiwoom_connector = _mgr.get_connector("kiwoom")
                    logger.info("[엔진] 실시간 연결 완료")
                except Exception as e:
                    logger.error("[엔진] 실시간 연결 초기화 실패: %s", e)
                    es._connector_manager = None
                    es._kiwoom_connector = None
            else:
                logger.info("[엔진] 실시간 구독 구간 밖 또는 실시간 연결 OFF — Connector 연결 생략")

        logger.info("[기동시간] 전체 기동: %.0fms", (time.perf_counter() - _t0) * 1000)
        es._broadcast_engine_ws()  # 엔진 루프 진입 직후 헤더에 즉시 반영

        # ── 엔진 종료 대기 (WS 연결/해제는 스케줄러가 관리) ──
        es._engine_stop_event.clear()
        await es._engine_stop_event.wait()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        es._log(f" [엔진] 예외: {e}")
    finally:
        if getattr(es, "_connector_manager", None):
            await es._connector_manager.disconnect_all()
        else:
            if es._kiwoom_connector:
                await es._kiwoom_connector.disconnect()
        es._connector_manager = None
        es._kiwoom_connector = None
        es._rest_api  = None
        es._engine_loop_ref = None
        es._running   = False
        es._broadcast_engine_ws()
        es._log(f"[엔진] 정지됨 ({es._now_kst()})")
