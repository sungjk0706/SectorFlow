# -*- coding: utf-8 -*-
"""엔진 상태 라우터 — GET 엔드포인트는 WS initial-snapshot으로 대체됨."""
from __future__ import annotations
import logging
from fastapi import APIRouter, Query
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/health")
async def health_check():
    """서버 준비 상태 확인 - 현대적 안정성 패턴."""
    from backend.app.services.engine_state import state

    # 상태 확인
    is_server_ready = state.server_ready_event.is_set()
    is_engine_ready = state.engine_ready_event.is_set()
    is_bootstrap_done = state.bootstrap_event.is_set()
    is_running = state.running

    if is_server_ready and is_engine_ready:
        status = "ready"
        message = "엔진 준비 완료"
    elif state.confirmed_refresh_running:
        status = "downloading"
        message = "확정 데이터 다운로드 중"
    elif is_running:
        status = "initializing"
        message = "초기화 중..."
    else:
        status = "ready"
        message = "서버 준비 완료 (엔진 미실행)"
    
    # 진행 상황 상세
    progress = {
        "server_ready": is_server_ready,
        "engine_ready": is_engine_ready,
        "bootstrap_done": is_bootstrap_done,
        "data_loaded": is_bootstrap_done,  # 데이터 로드는 부트스트랩에 포함
        "broker_connected": bool(state.access_token),  # 토큰 발급 여부로 연결 상태 확인
    }
    
    return {
        "status": status,
        "message": message,
        "progress": progress,
        "timestamp": state.account_snapshot.get("timestamp") if state.account_snapshot else None,
    }



@router.get("/debug/sector-stock/{code}")
async def debug_sector_stock(code: str):
    """디버그용: 특정 종목의 실시간 데이터 상태 확인."""
    from backend.app.services.engine_state import state
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    nk = _base_stk_cd(code.strip())
    pend = state.master_stocks_cache.get(nk, {})
    in_filter = pend.get("_filtered", False)
    in_subscribed = pend.get("_subscribed", False)
    # 실시간 틱 데이터 캐시 읽기 로직 삭제 (캐시가 삭제되었으므로 읽기 불가, None 반환)
    tp = None
    ta = None
    st = None
    rq = None
    return {
        "code": nk,
        "in_filtered_sector_codes": in_filter,
        "in_subscribed_stocks": in_subscribed,
        "filtered_count": sum(1 for entry in state.master_stocks_cache.values() if entry.get("_filtered", False)),
        "subscribed_count": sum(1 for entry in state.master_stocks_cache.values() if entry.get("_subscribed", False)),
        "pending_status": pend.get("status") if pend else None,
        "pending_cur_price": pend.get("cur_price") if pend else None,
        "pending_change": pend.get("change") if pend else None,
        "pending_change_rate": pend.get("change_rate") if pend else None,
        "pending_strength": pend.get("strength") if pend else None,
        "pending_trade_amount": pend.get("trade_amount") if pend else None,
        "latest_trade_price": tp,
        "latest_trade_amount": ta,
        "latest_strength": st,
        "rest_quote_cache_exists": rq is not None,
    }


@router.get("/debug/ws-status")
async def debug_ws_status():
    """디버그용: WS 연결 상태 + 구독 현황 확인."""
    from backend.app.services.engine_state import state
    ws = state.active_connector
    return {
        "ws_connected": bool(ws and ws.is_connected()) if ws else False,
        "login_ok": state.login_ok,
        "running": state.running,
        "subscribed_stocks_count": sum(1 for entry in state.master_stocks_cache.values() if entry.get("_subscribed", False)),
        "filtered_sector_codes_count": sum(1 for entry in state.master_stocks_cache.values() if entry.get("_filtered", False)),
        # _radar_cnsr_order 삭제: subscribed_stocks_count로 대체
        "latest_trade_prices_count": 0,  # 실시간 틱 데이터 캐시 삭제로 0 반환
        "ws_reg_pipeline_done": state.ws_reg_pipeline_done.is_set(),
        "bootstrap_done": state.bootstrap_event.is_set(),
        "sector_confirmed": False,  # 확정 개념 제거됨
    }


@router.post("/debug/trigger-confirmed")
async def debug_trigger_confirmed():
    """디버그용: 통합 확정 조회 수동 트리거 (캐시 재생성)."""
    from backend.app.services.market_close_pipeline import fetch_unified_confirmed_data
    try:
        result = await fetch_unified_confirmed_data()
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/debug/sector-refresh-sample")
async def debug_sector_refresh_sample():
    """디버그용: sector-refresh WS 이벤트와 동일한 데이터를 직접 반환."""
    from backend.app.services.sector_data_provider import get_sector_stocks
    stocks = await get_sector_stocks()
    status = {}  # 확정 개념 제거됨
    # 삼성전자, SK하이닉스 찾기
    sample = {}
    for s in stocks:
        cd = s.get("code", "")
        if cd in ("005930", "000660"):
            sample[cd] = {
                "cur_price": s.get("cur_price"),
                "change": s.get("change"),
                "change_rate": s.get("change_rate"),
                "strength": s.get("strength"),
                "trade_amount": s.get("trade_amount"),
                "avg_amt_5d": s.get("avg_amt_5d"),
                "sector": s.get("sector"),
            }
    # WS 클라이언트 상태 확인
    from backend.app.web.ws_manager import ws_manager
    return {
        "total_stocks_in_response": len(stocks),
        "status": status,
        "sample_005930": sample.get("005930", "NOT_FOUND"),
        "sample_000660": sample.get("000660", "NOT_FOUND"),
        "ws_client_count": ws_manager.client_count,
    }


@router.get("/debug/orderbook-status")
async def debug_orderbook_status(
    codes: list[str] = Query(default=[], description="확인할 종목코드 리스트 (예: 068270,298380)"),
):
    """디버그용: 특정 종목의 호가잔량(0D) 구독 및 수신 상태 확인."""
    from backend.app.services.engine_state import state
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    from backend.app.services import data_manager

    result = {}
    for raw_code in codes:
        nk = _base_stk_cd(raw_code.strip())
        is_subscribed = state.master_stocks_cache.get(nk, {}).get("_subscribed_0d", False)
        stock_name = data_manager.get_stock_name(nk)

        result[nk] = {
            "name": stock_name,
            "subscribed_0d": is_subscribed,
            "orderbook_cached": False,
            "orderbook_data": None,
        }

    return {
        "stocks": result,
        "total_subscribed_0d": sum(1 for entry in state.master_stocks_cache.values() if entry.get("_subscribed_0d", False)),
    }
