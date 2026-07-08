# -*- coding: utf-8 -*-
"""
스냅샷/데이터 관련 모듈
- 초기 스냅샷 생성
- 업종 종목 페이로드 생성
- 데이터 필드 필터링
- 실시간 필드 초기화
"""
import asyncio
import time
from backend.app.core.logger import get_logger
import backend.app.services.engine_state as engine_state
from backend.app.services.engine_state import state

logger = get_logger("engine_snapshot")


# ── 스냅샷 생성 ─────────────────────────────────────────────────────

async def build_initial_snapshot() -> dict:
    """WS 연결 시 클라이언트에게 보낼 메타 상태 스냅샷을 조립한다.

    sector_stocks는 별도 이벤트(sector-stocks-refresh)로 분할 전송하므로 여기서는 빈 리스트.
    """
    from backend.app.services import ws_subscribe_control
    from backend.app.services.daily_time_scheduler import get_market_phase
    from backend.app.services.engine_account import (
        get_positions, get_account_snapshot, get_snapshot_history,
        get_buy_limit_status, _refresh_account_snapshot_meta,
    )
    from backend.app.services.sector_data_provider import get_sector_scores_snapshot, get_buy_targets_sector_stocks
    from backend.app.services.engine_config import _mask_sensitive_settings
    from backend.app.services.engine_lifecycle import get_engine_status
    from backend.app.pipelines.pipeline_compute import get_current_receive_rate

    async def _safe(fn, default):
        """getter 호출을 감싸서 실패하면 기본값을 돌려준다."""
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as exc:
            logger.warning("[시스템] %s 호출 실패 — 기본값 사용: %s", fn.__name__, exc, exc_info=True)
            return default

    _snapshot_t0 = time.perf_counter()
    await _safe(_refresh_account_snapshot_meta, None)
    positions = await _safe(get_positions, [])
    account_snap = await _safe(get_account_snapshot, {})

    # 단일 소스 진리: _integrated_system_settings_cache 직접 사용

    scores_snapshot = await _safe(get_sector_scores_snapshot, ([], 0))
    scores_list, ranked_count = scores_snapshot if isinstance(scores_snapshot, tuple) else (scores_snapshot, 0)

    # 종목수 일치 보장: master_stocks_table 기준
    total_stocks_count = len(state.master_stocks_cache)

    snapshot: dict = {
        "_v":               1,
        "account":          account_snap,
        "positions":        positions,
        "sector_stocks":    [],  # 분할 전송 — sector-stocks-refresh 이벤트로 별도 전송
        "sector_scores":    scores_list,
        "sector_status":    {"total_stocks": total_stocks_count, "max_targets": int(state.integrated_system_settings_cache["sector_max_targets"]), "ranked_sectors_count": ranked_count},
        "buy_targets":      await _safe(get_buy_targets_sector_stocks, []),
        "settings":         _mask_sensitive_settings(state.integrated_system_settings_cache),
        "status":           get_engine_status(),
        "snapshot_history": await _safe(get_snapshot_history, []),
        "sell_history":     await _safe(lambda: _get_trade_history_for_snapshot("sell"), []),
        "buy_history":      await _safe(lambda: _get_trade_history_for_snapshot("buy"), []),
        "daily_summary":    await _safe(lambda: _get_daily_summary_for_snapshot(), []),
        "buy_limit_status": await _safe(get_buy_limit_status, {"daily_buy_spent": 0}),
        "ws_subscribe_status": ws_subscribe_control.get_subscribe_status(),
        "bootstrap_done":   state.bootstrap_event.is_set() if state.bootstrap_event else state.preboot_cache_loaded,
        "market_phase":     get_market_phase(),
        "receive_rate":     get_current_receive_rate(),
        "broker_config":    state.integrated_system_settings_cache["broker_config"],
        "avg_amt_refresh":  None,
    }

    # Delta 캐시 초기화 — sector_stocks는 분할 전송 시점에 초기화
    try:
        from backend.app.services.engine_account_notify import init_sent_caches
        init_sent_caches([], positions, account_snap)
    except Exception as e:
        logger.warning("[시스템] delta 저장 데이터 초기화 실패: %s", e, exc_info=True)

    return snapshot


async def build_sector_stocks_payload() -> dict:
    """sector-stocks-refresh 이벤트용 종목 데이터 페이로드를 조립한다."""
    from backend.app.services.sector_data_provider import get_sector_stocks
    from backend.app.services.engine_account import get_positions, get_account_snapshot
    from backend.app.services.daily_time_scheduler import is_krx_after_hours
    
    sector_stocks = await get_sector_stocks()
    filtered = _filter_stock_fields(sector_stocks)

    # Delta 캐시 초기화 (종목 데이터 기준)
    try:
        from backend.app.services.engine_account_notify import init_sent_caches
        init_sent_caches(sector_stocks, await get_positions(), await get_account_snapshot())
    except Exception:
        logger.warning("[시스템] delta 캐시 초기화 실패", exc_info=True)

    return {"_v": 1, "stocks": filtered, "krx_after_hours": is_krx_after_hours()}


# ── 데이터 필드 필터링 ─────────────────────────────────────────────

_SNAPSHOT_STOCK_FIELDS = {
    "code", "name", "cur_price", "change", "change_rate", "strength",
    "trade_amount", "sector", "avg_amt_5d", "market_type", "nxt_enable",
}


def _filter_stock_fields(stocks: list[dict]) -> list[dict]:
    """initial-snapshot용 종목 데이터 필드 필터링."""
    return [{k: v for k, v in s.items() if k in _SNAPSHOT_STOCK_FIELDS} for s in stocks]


async def _get_trade_history_for_snapshot(side: str) -> list:
    """initial-snapshot용 체결 이력 반환. 현재 trade_mode 기준 필터."""
    from backend.app.services import trade_history
    from backend.app.services.engine_account import get_trade_mode
    
    mode = get_trade_mode()
    if side == "sell":
        return await trade_history.get_sell_history(trade_mode=mode)
    return await trade_history.get_buy_history(trade_mode=mode)


async def _get_daily_summary_for_snapshot() -> list:
    """initial-snapshot용 20거래일 일별 요약 반환."""
    from backend.app.services import trade_history
    from backend.app.services.engine_account import get_trade_mode
    
    return await trade_history.get_daily_summary(days=20, trade_mode=get_trade_mode())


# ── 실시간 필드 초기화 ─────────────────────────────────────────────

_REALTIME_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")


async def _reset_realtime_fields() -> None:
    """WS 구독 시작 시 실시간 필드를 None으로 초기화하고 실시간 캐시 3종을 비운다."""
    from backend.app.core.trade_mode import is_test_mode
    from backend.app.services import dry_run
    from backend.app.services.engine_account_notify import (
        notify_cache,
        notify_desktop_sector_stocks_refresh,
        _broadcast,
    )
    from backend.app.services.engine_account import _broadcast_account

    for entry in state.master_stocks_cache.values():
        for f in _REALTIME_FIELDS:
            entry[f] = None
    state.snapshot_history.clear()
    # 보유종목 실시간 필드 초기화 (전일 종가 혼입 방지)
    for pos in state.positions:
        pos["cur_price"] = None
        pos["change"] = None
        pos["change_rate"] = None
        pos["bid_depth"] = None
        pos["ask_depth"] = None

    # 테스트모드 가상 보유종목 실시간 필드 초기화
    if is_test_mode(state.integrated_system_settings_cache):
        for pos in dry_run._test_positions.values():
            pos["cur_price"] = None
            pos["change"] = None
            pos["change_rate"] = None
            pos["bid_depth"] = None
            pos["ask_depth"] = None

    # 업종 점수 캐시 초기화 (실시간 데이터 재계산 유도)
    state.sector_summary_cache = None
    # 캡슐화된 notify_cache.clear_all() 호출로 결합성 제거
    notify_cache.clear_all()

    # DB master_stocks_table 실시간 필드 초기화 (과거 데이터 혼입 방지)
    try:
        from backend.app.db.database import get_db_connection, get_db_lock
        async with get_db_lock():
            conn = await get_db_connection()
            await conn.execute("""
                UPDATE master_stocks_table
                SET cur_price = NULL,
                    change = NULL,
                    change_rate = NULL,
                    trade_amount = NULL
            """)
            await conn.commit()
        logger.info("[시스템] DB master_stocks_table 실시간 필드 초기화 완료")
    except Exception as db_err:
        logger.error("[시스템] DB master_stocks_table 실시간 필드 초기화 실패: %s", db_err, exc_info=True)
    logger.info(
        "[시스템] 실시간 필드 및 REST 보완 저장 데이터, 수익 이력 초기화 완료 — %d종목, 실시간/REST 저장 데이터 전체 클리어",
        len(state.master_stocks_cache),
    )
    await notify_desktop_sector_stocks_refresh()
    await _broadcast_account("realtime_reset")
    await _broadcast("realtime-reset", {})


# ── 기타 헬퍼 ─────────────────────────────────────────────────


async def get_position_pnl_pct_for_code(stk_cd: str) -> float | None:
    """보유 잔고에 있으면 수익률(%), 없으면 None."""
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    from backend.app.services import dry_run
    from backend.app.core.trade_mode import is_test_mode
    
    nk = _base_stk_cd(str(stk_cd or "").strip())
    if not nk:
        return None
    # 테스트모드: dry_run 가상 잔고에서 조회
    if is_test_mode(state.integrated_system_settings_cache):
        pos = await dry_run.get_position(nk)
        if pos and int(pos.get("qty", 0) or 0) > 0:
            try:
                return float(pos.get("pnl_rate") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return None
    for p in state.positions:
        pcd = _base_stk_cd(str(p.get("stk_cd", "") or ""))
        if pcd != nk:
            continue
        if int(p.get("qty", 0) or 0) <= 0:
            return None
        try:
            return float(p.get("pnl_rate") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return None
