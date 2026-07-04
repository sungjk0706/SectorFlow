# -*- coding: utf-8 -*-
"""
엔진 부트스트랩 흐름.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
engine_service의 함수가 필요하면 lazy import (`from backend.app.services import engine_service`).
"""
from __future__ import annotations
import asyncio
from backend.app.core.logger import get_logger
import backend.app.services.engine_state as _st
logger = get_logger("engine")

# 구독 동시성 상한 (앱 기동 시 일회성 구독 준비)
_subscribe_semaphore = asyncio.Semaphore(50)

# ── 앱준비 단계 정의 (하드코딩 금지 — len()으로 total 산출) ──
BOOTSTRAP_STAGES = [
    (1, "레이아웃 저장데이터 확인"),
    (2, "섹터 매핑 로드"),
    (3, "KRX 확정데이터 로드 중"),
    (4, "시세 데이터 반영"),
    (5, "5일 평균 저장데이터 로드"),
    (6, "앱준비 완료"),
]


async def _broadcast_bootstrap_stage(
    stage_id: int, stage_name: str,
    progress: dict | None = None,
) -> None:
    """부트스트랩 단계 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        payload = {
            "_v": 1,
            "stage_id": stage_id,
            "stage_name": stage_name,
            "total": len(BOOTSTRAP_STAGES),
        }
        if progress is not None:
            payload["progress"] = progress
        await ws_manager.broadcast("bootstrap-stage", payload)
    except Exception as e:
        logger.warning("[시작] stage 브로드캐스트 실패 %s: %s", stage_name, e, exc_info=True)


# _bootstrap_sector_stocks_async 함수 삭제: _load_caches_preboot로 단일화 완료


async def _deferred_sector_summary() -> None:
    """업종순위 후순위 계산 — _bootstrap_event.set() 이후 비동기 실행.

    compute_full_sector_summary()를 직접 await 호출.
    _sector_summary_ready_event.set()은 engine_sector_confirm에서 수행 (여기서 제거됨).
    완료 후 WS 3종 전송.
    """
    try:
        # 항상 전체 재계산 수행 (스켈레톤 캐시 모드 제거)
        from backend.app.domain.sector_calculator import compute_full_sector_summary
        from backend.app.domain.buy_filter import build_buy_targets_from_settings
        from backend.app.services.sector_data_provider import get_sector_summary_inputs
        _inputs = await get_sector_summary_inputs()
        if _inputs.get("all_codes"):
            # 단일 소스 진리: _integrated_system_settings_cache 직접 사용
            _trim_trade = float(_st._integrated_system_settings_cache["sector_trim_trade_amt_pct"])
            _trim_change = float(_st._integrated_system_settings_cache["sector_trim_change_rate_pct"])
            _kwargs = dict(
                min_rise_ratio=float(_st._integrated_system_settings_cache["sector_min_rise_ratio_pct"]) / 100.0,
                min_avg_amt_eok=float(_st._integrated_system_settings_cache["sector_min_trade_amt"]),
                sector_weights=_st._integrated_system_settings_cache["sector_weights"],
                trim_trade_amt_pct=_trim_trade,
                trim_change_rate_pct=_trim_change,
            )
            _sector_summary = await compute_full_sector_summary(**_inputs, **_kwargs)
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            _held_codes = {_base_stk_cd(cd) for cd in _st.checked_stocks}
            _result = build_buy_targets_from_settings(
                _sector_summary.sectors,
                _st._integrated_system_settings_cache,
                held_codes=_held_codes,
            )
            import backend.app.services.engine_service as _es
            _es._sector_summary_cache = _result
            logger.debug("[시작] 업종순위 후순위 계산 완료 -- %d개 섹터", len(_result.sectors))

            # WS broadcast — 이미 연결된 클라이언트에게 전송
            try:
                from backend.app.services.engine_account_notify import (
                    notify_desktop_sector_scores,
                    notify_desktop_sector_stocks_refresh,
                    notify_buy_targets_update,
                )
                from backend.app.web.ws_manager import ws_manager
                _client_cnt = ws_manager.client_count
                await notify_desktop_sector_scores(force=True)
                await asyncio.gather(
                    notify_desktop_sector_stocks_refresh(),
                    notify_buy_targets_update(),
                )
                logger.debug("[시작] 업종순위 화면전송 완료 (접속화면=%d)", _client_cnt)
            except Exception as e:
                logger.error("[시작] UI 초기 전송 실패: %s", e, exc_info=True)
        else:
            # 종목 없음 — 이벤트만 발행 (대기 해제)
            _st._sector_summary_ready_event.set()
    except Exception as _e:
        logger.warning("[시작] 업종순위 후순위 계산 실패(무시): %s", _e, exc_info=True)
        _st._sector_summary_ready_event.set()  # 실패해도 대기 해제


async def _notify_close_data_ui() -> None:
    """장외 확정 데이터 갱신 -- UI 알림 트리거."""
    try:
        from backend.app.services import engine_account_notify as _account_notify
        try:
            await _account_notify.notify_desktop_buy_radar_only()
        except Exception as e:
            logger.warning("[시작] 매수후보 갱신 실패: %s", e, exc_info=True)
        try:
            await _account_notify.notify_desktop_sector_refresh()
            logger.debug("[시작][장외갱신] 섹터 분석 패널 갱신 트리거")
        except Exception as e:
            logger.warning("[시작] 섹터 갱신 실패: %s", e, exc_info=True)
    except Exception as _e:
        logger.warning("[시작][장외갱신] 확정 데이터 갱신 실패(무시): %s", _e, exc_info=True)





async def _login_post_pipeline() -> None:
    """LOGIN 성공 후: 잔고 조회 -> 보유종목 REG -> WS 구독 등록."""
    from backend.app.services import engine_service as es
    _st._ws_reg_pipeline_done.clear()
    logger.info("[시작] 로그인 후 파이프라인 진입")
    try:
        await es._cleanup_stale_ws_subscriptions_on_session_ready()

        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
        from backend.app.core.trade_mode import is_test_mode
        _in_ws_window = await is_ws_subscribe_window(_st._integrated_system_settings_cache)

        if is_test_mode(_st._integrated_system_settings_cache):
            logger.info("[시작] 파이프라인 -- 테스트모드 -- REST 잔고 조회 생략 (가상잔고 사용)")
        elif not _in_ws_window:
            if not _st._account_rest_bootstrapped:
                logger.info("[시작] 파이프라인 -- REST 잔고 선행 조회 시작")
                from backend.app.services.engine_service import _update_account_memory
                await _update_account_memory(_st._integrated_system_settings_cache)
                logger.info("[시작] 파이프라인 -- REST 잔고 선행 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.info("[시작] 파이프라인 -- 잔고 이미 앱준비 완료 -- 재조회 생략 (보유 %d종목)", len(_st._positions))
        else:
            if not _st._positions and not _st._account_rest_bootstrapped:
                logger.debug("[시작] 파이프라인 -- 실시간 구독 구간이나 포지션 미적재 -- REST 잔고 1회 조회")
                from backend.app.services.engine_service import _update_account_memory
                await _update_account_memory(_st._integrated_system_settings_cache)
                logger.debug("[시작] 파이프라인 -- REST 잔고 1회 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.debug("[시작] 파이프라인 -- 실시간 구독 구간 -- REST 잔고 조회 생략 (실시간 수신, 보유 %d종목)", len(_st._positions))

        all_stocks = _st.state.master_stocks_cache.copy()
        stale = {cd for cd, entry in all_stocks.items() if entry.get("_subscribed", False)}
        if stale:
            logger.debug("[시작] 새 세션 -- 0B 구독 상태 초기화 %d종목 (강제 재등록)", len(stale))
            for cd in stale:
                if cd in _st.state.master_stocks_cache:
                    entry = _st.state.master_stocks_cache[cd]
                    entry.pop("_subscribed", None)

        from backend.app.services import engine_account_notify as _account_notify


        if _in_ws_window:
            # Connector 연결 확인 및 구독
            ws = _st.state.connector_manager or _st.state.active_connector
            if ws and ws.is_connected():
                # 실시간 구독 전 종목 필터링 상태(_filtered)를 최신화하기 위해 1회 재계산
                await es.recompute_sector_summary_now()
                await es._run_sector_reg_pipeline()
                await es._ensure_ws_subscriptions_for_positions()

            await _account_notify.notify_desktop_sector_refresh()
            await _account_notify.notify_desktop_sector_stocks_refresh()
        else:
            _st._ws_reg_pipeline_done.set()
            await _account_notify.notify_desktop_sector_refresh(force=True)
            await _account_notify.notify_desktop_sector_stocks_refresh()
    except Exception as _e:
        logger.error("[시작] 로그인 후 파이프라인 예외: %s", _e, exc_info=True)


async def _run_sector_reg_pipeline() -> None:
    """REG 파이프라인 -- engine_service에서 위임."""
    from backend.app.services import engine_service as es
    await es._run_sector_reg_pipeline()



