# -*- coding: utf-8 -*-
"""
엔진 부트스트랩 흐름.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
각 전문 모듈에서 직접 lazy import.
"""
from __future__ import annotations
import logging
from backend.app.services.engine_state import state
logger = logging.getLogger(__name__)


async def _login_post_pipeline() -> None:
    """LOGIN 성공 후: 잔고 조회 -> 보유종목 REG -> WS 구독 등록."""
    from backend.app.services.sector_data_provider import recompute_sector_summary_now
    state.ws_reg_pipeline_done.clear()
    logger.info("[연산] 로그인 후 파이프라인 진입")
    try:
        from backend.app.services.engine_ws import _cleanup_stale_ws_subscriptions_on_session_ready
        await _cleanup_stale_ws_subscriptions_on_session_ready()

        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
        from backend.app.core.trade_mode import is_test_mode
        _in_ws_window = await is_ws_subscribe_window(state.integrated_system_settings_cache)

        if is_test_mode(state.integrated_system_settings_cache):
            logger.info("[연산] 파이프라인 — 테스트모드 — REST 잔고 조회 생략 (가상잔고 사용)")
        elif not _in_ws_window:
            if not state.account_rest_bootstrapped:
                logger.info("[연산] 파이프라인 — REST 잔고 선행 조회 시작")
                from backend.app.services.engine_account import _update_account_memory
                await _update_account_memory(state.integrated_system_settings_cache)
                logger.info("[연산] 파이프라인 — REST 잔고 선행 조회 완료 (보유 %d종목)", len(state.positions))
            else:
                logger.info("[연산] 파이프라인 — 잔고 이미 앱 준비 완료 — 재조회 생략 (보유 %d종목)", len(state.positions))
        else:
            if not state.positions and not state.account_rest_bootstrapped:
                from backend.app.services.engine_account import _update_account_memory
                await _update_account_memory(state.integrated_system_settings_cache)

        stale = {cd for cd, entry in state.master_stocks_cache.items() if entry.get("_subscribed", False)}
        if stale:
            logger.debug("[연산] 새 세션 — 0B 구독 상태 초기화 %d종목 (강제 재등록)", len(stale))
            for cd in stale:
                if cd in state.master_stocks_cache:
                    entry = state.master_stocks_cache[cd]
                    entry.pop("_subscribed", None)

        from backend.app.services import engine_account_notify as _account_notify

        if _in_ws_window:
            # Connector 연결 확인 및 구독
            ws = state.connector_manager or state.active_connector
            if ws and ws.is_connected():
                # 실시간 구독 전 종목 필터링 상태(_filtered)를 최신화하기 위해 1회 재계산
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

            await _account_notify.notify_desktop_sector_refresh()
            await _account_notify.notify_desktop_sector_stocks_refresh()
        else:
            state.ws_reg_pipeline_done.set()
            await _account_notify.notify_desktop_sector_refresh(force=True)
            await _account_notify.notify_desktop_sector_stocks_refresh()
    except Exception as _e:
        logger.error("[연산] 로그인 후 파이프라인 예외: %s", _e, exc_info=True)

