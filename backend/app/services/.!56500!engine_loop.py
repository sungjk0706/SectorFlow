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
        ws_manager.broadcast("engine-ready", {"_v": 1, "ready": True})
        logger.info("[시작] 데이터준비 완료 -- 실시간 준비됨")
    except Exception:
        logger.warning("[시작] engine-ready 브로드캐스트 실패", exc_info=True)


async def _get_token_async(router) -> str | None:
    """토큰 발급 — async def get_access_token()을 await로 직접 호출.

    router.auth.get_access_token()은 async def이며 httpx.AsyncClient로 비동기 HTTP 호출을 수행한다.
    실패 시 None 반환 + 경고 로그 (스냅샷 전용 모드).
    """
    try:
        token = await router.auth.get_access_token()
        return token
    except Exception as e:
        logger.warning("[연결] 토큰 발급 예외: %s. 확정데이터 전용 모드로 기동.", e, exc_info=True)
        return None


async def _get_all_tokens_async(router) -> None:
    """
    broker_config에 등장하는 모든 증권사 토큰을 병렬 발급한다.
    router._auth_cache에 이미 모든 증권사 AuthProvider가 등록되어 있다.
    발급된 토큰은 state.broker_tokens[broker_id]로 저장한다.
    """
    from backend.app.services.engine_state import state
    auth_cache: dict = getattr(router, "_auth_cache", {})
    if not auth_cache:
        return

    async def _fetch_one(broker_id: str, auth_provider) -> tuple[str, str | None]:
        try:
            token = await auth_provider.get_access_token()
            from backend.app.core.broker_registry import BROKER_DISPLAY_NAMES
            disp = BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper())
            logger.info("[연결] %s 토큰 발급 완료", disp)
            return broker_id, token
        except Exception as e:
            logger.warning("[연결] %s 토큰 발급 실패: %s", broker_id.upper(), e, exc_info=True)
            return broker_id, None

    results = await asyncio.gather(
        *[_fetch_one(bid, ap) for bid, ap in auth_cache.items()],
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
    # _master_stocks_cache에서 "_subscribed" 제거
    all_stocks = state.master_stocks_cache.copy()
    for entry in all_stocks.values():
        entry.pop("_subscribed", None)
    from backend.app.services.engine_state import _notify_reg_ack, _cancel_price_trace_delayed_task
    _notify_reg_ack()
    _cancel_price_trace_delayed_task()
    state.checked_stocks.clear()
    # _radar_cnsr_order 삭제: clear() 제거
    # _sector_stock_layout 제거: state.integrated_system_settings_cache["sector_stock_layout"]로 통합
    state.integrated_system_settings_cache["sector_stock_layout"] = []
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache([])
    # 실시간 틱 데이터 캐시 초기화 삭제 (_rest_radar_quote_cache.clear() 제거)
    # _rest_radar_rest_once 제거: 읽기 코드 없음, 기능 부재
    state.running = True
    state.engine_loop_ref = asyncio.get_running_loop()
    # 실시간 틱 데이터 캐시 초기화 삭제 (캐시가 삭제되었으므로 초기화 불필요)
    # 캐시선행 플래그 초기화
    state.preboot_cache_loaded = False
    state.preboot_ready_event.clear()
    # 계좌 REST Lock 초기화 -- 이전 세션 잠금 상태 초기화
    state.account_rest_lock = None

