# -*- coding: utf-8 -*-
"""엔진 상태 라우터 — GET 엔드포인트는 WS initial-snapshot으로 대체됨."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/health")
async def health_check():
    """서버 준비 상태 확인 - 현대적 안정성 패턴."""
    from app.services import engine_service as es
    
    # 상태 확인
    is_server_ready = es._server_ready_event.is_set()
    is_engine_ready = es._engine_ready_event.is_set()
    is_bootstrap_done = es._bootstrap_event.is_set()
    is_running = es._running
    
    if is_server_ready and is_engine_ready:
        status = "ready"
        message = "엔진 준비 완료"
    elif is_running:
        status = "initializing"
        message = "초기화 중..."
    else:
        status = "error"
        message = "엔진 실행 중지"
    
    # 진행 상황 상세
    progress = {
        "server_ready": is_server_ready,
        "engine_ready": is_engine_ready,
        "bootstrap_done": is_bootstrap_done,
        "data_loaded": is_bootstrap_done,  # 데이터 로드는 부트스트랩에 포함
        "broker_connected": bool(es._access_token),  # 토큰 발급 여부로 연결 상태 확인
    }
    
    return {
        "status": status,
        "message": message,
        "progress": progress,
        "timestamp": es._account_snapshot.get("timestamp") if es._account_snapshot else None,
    }


@router.get("/debug/sector-stock/{code}")
async def debug_sector_stock(code: str):
    """디버그용: 특정 종목의 실시간 데이터 상태 확인."""
    from app.services import engine_service as es
    from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
    nk = _format_kiwoom_reg_stk_cd(code.strip())
    pend = es._pending_stock_details.get(nk)
    in_filter = nk in es._filtered_sector_codes
    in_subscribed = nk in es._subscribed_stocks
    tp = es._latest_trade_prices.get(nk)
    ta = es._latest_trade_amounts.get(nk)
    st = es._latest_strength.get(nk)
    rq = es._rest_radar_quote_cache.get(nk)
    return {
        "code": nk,
        "in_filtered_sector_codes": in_filter,
        "in_subscribed_stocks": in_subscribed,
        "filtered_count": len(es._filtered_sector_codes),
        "subscribed_count": len(es._subscribed_stocks),
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
    from app.services import engine_service as es
    ws = es._kiwoom_connector
    return {
        "ws_connected": bool(ws and ws.is_connected()) if ws else False,
        "login_ok": es._login_ok,
        "running": es._running,
        "subscribed_stocks_count": len(es._subscribed_stocks),
        "filtered_sector_codes_count": len(es._filtered_sector_codes),
        "pending_stock_details_count": len(es._pending_stock_details),
        "latest_trade_prices_count": len(es._latest_trade_prices),
        "ws_reg_pipeline_done": es._ws_reg_pipeline_done.is_set(),
        "bootstrap_done": es._bootstrap_event.is_set(),
        "sector_confirmed": False,  # 확정 개념 제거됨
    }


@router.post("/debug/trigger-confirmed")
async def debug_trigger_confirmed():
    """디버그용: 통합 확정 조회 수동 트리거 (캐시 재생성)."""
    import asyncio
    from app.services import engine_service as es
    from app.services.market_close_pipeline import fetch_unified_confirmed_data
    try:
        result = await fetch_unified_confirmed_data(es)
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/debug/sector-refresh-sample")
async def debug_sector_refresh_sample():
    """디버그용: sector-refresh WS 이벤트와 동일한 데이터를 직접 반환."""
    from app.services import engine_service as es
    stocks = es.get_sector_stocks()
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
    from app.web.ws_manager import ws_manager
    return {
        "total_stocks_in_response": len(stocks),
        "status": status,
        "sample_005930": sample.get("005930", "NOT_FOUND"),
        "sample_000660": sample.get("000660", "NOT_FOUND"),
        "ws_client_count": ws_manager.client_count,
    }
