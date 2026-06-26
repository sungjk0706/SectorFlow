# -*- coding: utf-8 -*-
"""
스냅샷/데이터 관련 모듈
- 초기 스냅샷 생성
- 업종 종목 페이로드 생성
- 데이터 필드 필터링
- 실시간 필드 초기화
"""
import asyncio
import json
import time
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import state

logger = get_logger("engine_snapshot")


# ── 스냅샷 생성 ─────────────────────────────────────────────────────

async def build_initial_snapshot() -> dict:
    """WS 연결 시 클라이언트에게 보낼 메타 상태 스냅샷을 조립한다.

    sector_stocks는 별도 이벤트(sector-stocks-refresh)로 분할 전송하므로 여기서는 빈 리스트.
    """
    from backend.app.services import ws_subscribe_control
    from backend.app.services.daily_time_scheduler import get_market_phase
    import backend.app.services.engine_state as _st
    from backend.app.services.engine_account import (
        get_positions, get_account_snapshot, get_snapshot_history,
        get_buy_limit_status, _refresh_account_snapshot_meta,
    )
    from backend.app.services.sector_data_provider import get_sector_scores_snapshot, get_sector_stocks, get_buy_targets_sector_stocks
    from backend.app.services.engine_config import _mask_sensitive_settings
    from backend.app.services.engine_lifecycle import get_engine_status

    async def _safe(fn, default):
        """getter 호출을 감싸서 실패하면 기본값을 돌려준다."""
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as exc:
            logger.warning("[데이터] %s 호출 실패 — 기본값 사용: %s", fn.__name__, exc, exc_info=True)
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
        "broker_config":    state.integrated_system_settings_cache["broker_config"],
        "avg_amt_refresh":  None,
    }

    # Delta 캐시 초기화 — sector_stocks는 분할 전송 시점에 초기화
    try:
        from backend.app.services.engine_account_notify import init_sent_caches
        init_sent_caches([], positions, account_snap)
    except Exception as e:
        logger.warning("[데이터] delta 저장데이터 초기화 실패: %s", e, exc_info=True)

    try:
        payload_bytes = len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
    except Exception as exc:
        logger.warning("[데이터] 크기 측정 실패: %s", exc, exc_info=True)

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
        logger.warning("[데이터] delta 캐시 초기화 실패", exc_info=True)

    return {"_v": 1, "stocks": filtered, "krx_after_hours": is_krx_after_hours()}


# ── 데이터 필드 필터링 ─────────────────────────────────────────────

_SNAPSHOT_STOCK_FIELDS = {
    "code", "name", "cur_price", "change", "change_rate", "strength",
    "trade_amount", "sector", "avg_amt_5d", "market_type", "nxt_enable",
}


def _filter_stock_fields(stocks: list[dict]) -> list[dict]:
    """initial-snapshot용 종목 데이터 필드 필터링."""
    return [{k: v for k, v in s.items() if k in _SNAPSHOT_STOCK_FIELDS} for s in stocks]


def _get_trade_history_for_snapshot(side: str) -> list:
    """initial-snapshot용 체결 이력 반환. 현재 trade_mode 기준 필터."""
    from backend.app.services import trade_history
    from backend.app.services.engine_account import get_trade_mode
    
    mode = get_trade_mode()
    if side == "sell":
        return trade_history.get_sell_history(trade_mode=mode)
    return trade_history.get_buy_history(trade_mode=mode)


def _get_daily_summary_for_snapshot() -> list:
    """initial-snapshot용 20거래일 일별 요약 반환."""
    from backend.app.services import trade_history
    from backend.app.services.engine_account import get_trade_mode
    
    return trade_history.get_daily_summary(days=20, trade_mode=get_trade_mode())


# ── 실시간 필드 초기화 ─────────────────────────────────────────────

# _pending_stock_details 제거: bid_depth, ask_depth 제거
_REALTIME_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength", "high_price")


async def _reset_realtime_fields() -> None:
    """WS 구독 시작 시 실시간 필드를 None으로 초기화하고 실시간 캐시 3종을 비운다."""
    # _buy_targets_snapshot_cache 제거: _sector_summary_cache.buy_targets와 중복
    from backend.app.core.trade_mode import is_test_mode
    from backend.app.services import dry_run
    from backend.app.services.engine_account_notify import (
        notify_cache,
        notify_desktop_sector_stocks_refresh,
        _broadcast,
    )
    from backend.app.services.engine_account import _broadcast_account
    # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음

    # _pending_stock_details 제거: 루프 제거 (이미 WS 틱 저장 제거됨)
    async with state.shared_lock:
        # 실시간 틱 데이터 캐시 clear() 로직 삭제 (_latest_trade_amounts, _latest_trade_prices, _latest_strength)
        # 호가잔량 캐시 삭제로 clear 로직 제거
        # _subscribed_0d_stocks 제거: state.master_stocks_cache에서 "_subscribed_0d" 제거
        all_stocks = state.master_stocks_cache.copy()
        for entry in all_stocks.values():
            entry.pop("_subscribed_0d", None)
            for f in _REALTIME_FIELDS:
                entry[f] = None
        # 실시간 틱 데이터 캐시 clear() 로직 삭제 (_rest_radar_quote_cache)
        # _rest_radar_rest_once 제거: 읽기 코드 없음, 기능 부재
        state.snapshot_history.clear()
        # 보유종목 실시간 필드 초기화 (전일 종가 혼입 방지)
        for pos in state.positions:
            pos["cur_price"] = None
            pos["change"] = None
            pos["change_rate"] = None
            pos["bid_depth"] = None
            pos["ask_depth"] = None
            pos["high_price"] = None

        # 테스트모드 가상 보유종목 실시간 필드 초기화
        if is_test_mode(state.integrated_system_settings_cache):
            for pos in dry_run._test_positions.values():
                pos["cur_price"] = None
                pos["change"] = None
                pos["change_rate"] = None
                pos["bid_depth"] = None
                pos["ask_depth"] = None
                pos["high_price"] = None

        # 업종 점수 캐시 초기화 (실시간 데이터 재계산 유도)
        import backend.app.services.engine_service as _es
        _es._sector_summary_cache = None
        # _buy_targets_snapshot_cache 제거: _sector_summary_cache.buy_targets와 중복
        # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음
        # 캡슐화된 notify_cache.clear_all() 호출로 결합성 제거
        notify_cache.clear_all()

        # engine_ws_dispatch.py 캐시 초기화 (메모리 누적 방지)
        try:
            import backend.app.services.engine_ws_dispatch as _ws_dispatch
            _ws_dispatch._realtime_required_fields_cache.clear()
            _ws_dispatch._realtime_first_tick_ts_map.clear()
        except Exception:
            pass  # import 실패 시 무시

        # DB master_stocks_table 실시간 필드 초기화 (과거 데이터 혼입 방지)
        try:
            from backend.app.db.database import get_db_connection
            conn = await get_db_connection()
            await conn.execute("""
                UPDATE master_stocks_table
                SET cur_price = NULL,
                    change = NULL,
                    change_rate = NULL,
                    trade_amount = NULL,
                    high_price = NULL
            """)
            await conn.commit()
            logger.info("[데이터] DB master_stocks_table 실시간 필드 초기화 완료")
        except Exception as db_err:
            logger.error("[데이터] DB master_stocks_table 실시간 필드 초기화 실패: %s", db_err, exc_info=True)
    logger.info(
        "[데이터] 실시간 필드 및 REST 보완 저장데이터, 수익 이력 초기화 완료 -- %d종목, 실시간/REST 저장데이터 전체 클리어",
        len(state.master_stocks_cache),
    )
    await notify_desktop_sector_stocks_refresh()
    _broadcast_account("realtime_reset")
    _broadcast("realtime-reset", {})

    # 실시간 상태를 WAITING_FIRST_TICK으로 설정
    _set_realtime_state("WAITING_FIRST_TICK")


def _set_realtime_state(new_state: str) -> None:
    """실시간 상태 설정."""
    state.realtime_state = new_state


def _get_realtime_state() -> str:
    """실시간 상태 반환."""
    return state.realtime_state or "UNKNOWN"


# ── 기타 헬퍼 ─────────────────────────────────────────────────

# get_buy_targets_snapshot 제거: get_buy_targets_sector_stocks로 대체
# 매수후보 테이블은 이제 master_stocks_cache 기반 상위 업종 필터링을 사용


def get_position_pnl_pct_for_code(stk_cd: str) -> float | None:
    """보유 잔고에 있으면 수익률(%), 없으면 None."""
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd
    from backend.app.services import dry_run
    from backend.app.core.trade_mode import is_test_mode
    
    nk = _format_broker_reg_stk_cd(str(stk_cd or "").strip())
    if not nk:
        return None
    # 테스트모드: dry_run 가상 잔고에서 조회
    if is_test_mode(state.integrated_system_settings_cache):
        pos = dry_run.get_position(nk)
        if pos and int(pos.get("qty", 0) or 0) > 0:
            try:
                return float(pos.get("pnl_rate") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return None
    for p in state.positions:
        pcd = _format_broker_reg_stk_cd(str(p.get("stk_cd", "") or ""))
        if pcd != nk:
            continue
        if int(p.get("qty", 0) or 0) <= 0:
            return None
        try:
            return float(p.get("pnl_rate") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return None


def get_latest_trade_price_for_ui(stk_cd: str) -> int:
    """REAL 01 체결 캐시 기준 현재가 -- 매수 표 행·시세 정합 검증용."""
    # 실시간 틱 데이터 캐시 삭제로 인해 항상 0 반환
    return 0


async def _run_snapshot_and_sell_check(force_rest: bool = False) -> None:
    """
    매도 조건 검사 + (선택) REST 부트스트랩.
    - force_rest=True: 수동 동기화·엔진 최초 기동 -- kt00001/18 (예수금·수량·매입).
    - 부트스트랩 전 또는 WS 미연결: REST 조회.
    - WS 연결·부트스트랩 완료 후 force_rest=False: REST 생략, 스냅샷 메타만 갱신(합계는 마지막 REST 유지).
    """
    from backend.app.services import engine_strategy_core
    
    await engine_strategy_core.run_snapshot_and_sell_check(force_rest, None)
