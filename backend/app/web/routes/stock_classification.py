# -*- coding: utf-8 -*-
"""업종분류 커스텀 REST API 라우터.

8개 엔드포인트:
  GET  /api/stock-classification            — Merged_View 전체 조회
  POST /api/stock-classification/rename     — 업종명 변경
  POST /api/stock-classification/create     — 신규 업종 등록
  POST /api/stock-classification/delete     — 업종 삭제
  POST /api/stock-classification/move-stock — 종목 이동 (단건)
  POST /api/stock-classification/move-stocks — 종목 이동 (배치)
  POST /api/stock-classification/delete-cache — 캐시 삭제
"""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from backend.app.web.deps import get_current_user
logger = logging.getLogger(__name__)


async def _maybe_warning() -> dict:
    """장중(WS 구독 구간)이면 warning 필드를 반환, 아니면 빈 dict."""
    from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
    if await is_ws_subscribe_window():
        return {"warning": "장중 변경은 즉시 매매에 반영됩니다"}
    return {}


router = APIRouter(prefix="/api/stock-classification", tags=["stock-classification"])

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"


# ── Request 모델 ─────────────────────────────────────────────────────

class RenameRequest(BaseModel):
    old_name: str
    new_name: str

class CreateRequest(BaseModel):
    name: str

class DeleteRequest(BaseModel):
    name: str

class MoveStockRequest(BaseModel):
    stock_code: str
    target_sector: str

class MoveStocksRequest(BaseModel):
    stock_codes: list[str]
    target_sector: str


# ── WS 브로드캐스트 헬퍼 (Task 3.4) ────────────────────────────────

async def broadcast_stock_classification_changed() -> None:
    """stock-classification-changed WS 이벤트 브로드캐스트.

    메모리 캐시(_master_stocks_cache)에서 데이터를 조회하여 실시간 스냅샷 전송.
    """
    from backend.app.core.sector_mapping import get_merged_all_sectors
    from backend.app.web.ws_manager import ws_manager

    merged = await get_merged_all_sectors()

    # all_stocks: get_all_sector_stocks() SSOT 함수 사용 (status==active 필터 + get_merged_sector 기반)
    stocks = []
    filter_summary = ""
    try:
        from backend.app.services.sector_data_provider import get_all_sector_stocks
        import backend.app.services.engine_state as _es
        from backend.app.core.sector_stock_cache import assemble_filter_summary
        stocks = await get_all_sector_stocks()
        filter_summary = assemble_filter_summary(
            getattr(_es.state, "latest_filter_summary_meta", ""), len(stocks)
        )
    except Exception as e:
        logger.warning("[업종] 전체 종목 조회 실패: %s", e)

    # all_stocks 결과 기반으로 업종별 종목수 및 미분류 수 계산 (SSOT 일관성)
    sector_counts: dict[str, int] = {}
    no_sector_count = 0
    for s in stocks:
        sector = s.get("sector", "미분류")
        if sector == "미분류":
            no_sector_count += 1
        else:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

    # 커스텀 업종 목록 (all_stocks 결과 + sectors 테이블에서 추출)
    custom_sectors = {}
    for s in stocks:
        sector = s.get("sector")
        if sector and sector != "" and sector != "미분류":
            custom_sectors[sector] = ""

    # stock_moves: custom_sectors 테이블에서 실제 매핑 조회
    stock_moves = {}
    try:
        from backend.app.db.database import get_db_connection
        conn = await get_db_connection()
        cursor = await conn.execute("SELECT stock_code, name FROM custom_sectors WHERE hidden = 0")
        rows = await cursor.fetchall()
        for row in rows:
            stock_moves[row["stock_code"]] = row["name"]
        # sectors 테이블에서 빈 업종도 포함
        cursor = await conn.execute("SELECT name FROM sectors")
        for row in await cursor.fetchall():
            if row["name"] not in custom_sectors:
                custom_sectors[row["name"]] = ""
    except Exception as e:
        logger.warning("[업종] 종목 이동 조회 실패: %s", e)

    payload = {
        "_v": 1,
        "custom_data": {
            "sectors": custom_sectors,
            "stock_moves": stock_moves,
        },
        "merged_sectors": merged,
        "sector_counts": sector_counts,
        "no_sector_count": no_sector_count,
        "filter_summary": filter_summary,
        "all_stocks": stocks,
    }
    try:
        from backend.app.services.core_queues import get_broadcast_queue
        q = get_broadcast_queue()
        if not q.full():
            q.put_nowait({"type": "stock-classification-changed", "data": payload})
    except Exception:
        await ws_manager.broadcast("stock-classification-changed", payload)



async def _trigger_recompute() -> None:
    """업종순위 재계산 신호 전송 (Step 6: 컨트롤 플레인 우회 배관 연동)."""
    try:
        from backend.app.services.core_queues import get_control_queue

        # P0-1: PriorityQueue 전환 - 우선순위 1 (차순위) 튜플 구조
        control_queue = get_control_queue()
        import time
        await control_queue.put((1, time.monotonic(), {
            "type": "RECOMPUTE_SECTOR",
            "payload": {},
        }))
    except Exception as e:
        logger.warning("[업종] 업종순위 재계산 신호 전송 실패: %s", e)


# ── GET /api/stock-classification ───────────────────────────────────────────

@router.get("/all-stocks")
async def get_all_stocks(_: str = Depends(get_current_user)):
    """전체 종목(매매부적격 제외) 조회 — 업종분류 페이지 전용."""
    from backend.app.services.sector_data_provider import get_all_sector_stocks
    stocks = await get_all_sector_stocks()
    return {"stocks": stocks}


@router.get("")
async def get_stock_classification(_: str = Depends(get_current_user)):
    """Merged_View 전체 조회."""
    from backend.app.core.stock_classification_data import load_custom_data
    from backend.app.core.sector_mapping import get_merged_all_sectors

    custom = load_custom_data()
    merged = await get_merged_all_sectors()

    # "미분류" 소속 종목 수 계산 (broadcast_stock_classification_changed와 동일 로직)
    no_sector_count = 0
    filter_summary = ""
    try:
        from backend.app.services.sector_data_provider import get_all_sector_stocks
        import backend.app.services.engine_state as _es
        from backend.app.core.sector_stock_cache import assemble_filter_summary
        stocks = await get_all_sector_stocks()
        if "미분류" in merged:
            no_sector_count = sum(
                1 for s in stocks if s["sector"] == "미분류"
            )
        filter_summary = assemble_filter_summary(
            getattr(_es.state, "latest_filter_summary_meta", ""), len(stocks)
        )
    except Exception as e:
        logger.warning("[업종] 필터 요약 생성 실패: %s", e, exc_info=True)

    return {
        "custom_data": {
            "sectors": dict(custom.sectors),
            "stock_moves": dict(custom.stock_moves),
        },
        "merged_sectors": merged,
        "no_sector_count": no_sector_count,
        "filter_summary": filter_summary,
        "edit_window_open": True,
    }


# ── POST /api/stock-classification/rename ──────────────────────────────────

@router.post("/rename")
async def rename_sector(body: RenameRequest, _: str = Depends(get_current_user)):
    """업종명 변경."""
    try:
        from backend.app.core.stock_classification_data import rename_sector as _rename
        await _rename(body.old_name, body.new_name)
        await broadcast_stock_classification_changed()
        await _trigger_recompute()
        return {"ok": True, **await _maybe_warning()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/stock-classification/create ──────────────────────────────────

@router.post("/create")
async def create_sector(body: CreateRequest, _: str = Depends(get_current_user)):
    """신규 업종 등록."""
    try:
        from backend.app.core.stock_classification_data import create_sector as _create
        await _create(body.name)
        await broadcast_stock_classification_changed()
        await _trigger_recompute()
        return {"ok": True, **await _maybe_warning()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/stock-classification/delete ──────────────────────────────────

@router.post("/delete")
async def delete_sector(body: DeleteRequest, _: str = Depends(get_current_user)):
    """업종 삭제."""
    try:
        from backend.app.core.stock_classification_data import delete_sector as _delete
        await _delete(body.name)
        await broadcast_stock_classification_changed()
        await _trigger_recompute()
        return {"ok": True, **await _maybe_warning()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/stock-classification/move-stock ──────────────────────────────

@router.post("/move-stock")
async def move_stock(body: MoveStockRequest, _: str = Depends(get_current_user)):
    """종목 업종 이동."""
    try:
        from backend.app.core.stock_classification_data import move_stock as _move
        await _move(body.stock_code, body.target_sector)
        await broadcast_stock_classification_changed()
        await _trigger_recompute()
        return {"ok": True, **await _maybe_warning()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/stock-classification/move-stocks (배치) ───────────────────────

@router.post("/move-stocks")
async def move_stocks(body: MoveStocksRequest, _: str = Depends(get_current_user)):
    """종목 배치 업종 이동 — WS 이벤트 + 재계산 1회만 발생."""
    try:
        from backend.app.core.stock_classification_data import move_stock as _move
        from backend.app.services.sector_data_provider import get_all_sector_stocks
        
        for code in body.stock_codes:
            await _move(code, body.target_sector)
        
        # 응답에 all_stocks 포함 (델타 전송 원칙 준수)
        stocks = await get_all_sector_stocks()
        
        await broadcast_stock_classification_changed()
        await _trigger_recompute()
        return {"ok": True, "all_stocks": stocks, **await _maybe_warning()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/stock-classification/trigger-confirmed-download ──────────────────

@router.post("/trigger-confirmed-download")
async def trigger_confirmed_download(_: str = Depends(get_current_user)):
    """수동 1일봉 차트 시세 다운로드 실행"""
    try:
        from backend.app.services.engine_state import state
        if state.confirmed_refresh_running:
            return {"ok": False, "error": "1일봉 차트 시세 다운로드가 이미 진행 중입니다."}

        state.integrated_system_settings_cache["sector_stock_layout"] = []
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        from backend.app.services.market_close_pipeline import fetch_confirmed_data_only
        _task = asyncio.create_task(fetch_confirmed_data_only())
        _task.add_done_callback(lambda t: logger.warning("[업종] 1일봉 차트 다운로드 작업 실패: %s", t.exception()) if t.exception() else None)
        logger.info("[업종] 수동 1일봉 차트 시세 다운로드 시작")
        return {"ok": True}
    except Exception as e:
        logger.error("[업종] 수동 1일봉 차트 시세 다운로드 실패: %s", e)
        return {"ok": False, "error": str(e)}


# ── POST /api/stock-classification/trigger-5d-download ────────────────────────

@router.post("/trigger-5d-download")
async def trigger_5d_download(_: str = Depends(get_current_user)):
    """수동 5일봉 거래대금,고가 다운로드 실행"""
    try:
        from backend.app.services.engine_state import state
        if state.confirmed_refresh_running_5d:
            return {"ok": False, "error": "5일봉 다운로드가 이미 진행 중입니다."}

        from backend.app.services.market_close_pipeline import fetch_5d_data_only
        _task = asyncio.create_task(fetch_5d_data_only())
        _task.add_done_callback(lambda t: logger.warning("[업종] 5일봉 다운로드 작업 실패: %s", t.exception()) if t.exception() else None)
        logger.info("[업종] 수동 5일봉 거래대금,고가 다운로드 시작")
        return {"ok": True}
    except Exception as e:
        logger.error("[업종] 수동 5일봉 거래대금,고가 다운로드 실패: %s", e)
        return {"ok": False, "error": str(e)}


# ── GET /api/stock-classification/download-data-exists ────────────────────────

@router.get("/download-data-exists")
async def check_download_data_exists(_: str = Depends(get_current_user)):
    """수동 다운로드 대상 거래일의 데이터 저장 여부 확인.

    가장 최근 확정된 거래일(소속 거래일의 직전 거래일) 기준으로
    1일봉 시세(master_stocks_table.date)와 5일봉(stock_5d_bars.dt) 데이터
    존재 여부를 반환. 프론트엔드에서 수동 다운로드 버튼 클릭 시 사전 확인용 (P21).

    다운로드 파이프라인이 qry_dt=직전 거래일을 사용하므로, 이 API도 동일 기준으로
    일관성 유지 (P10 SSOT). 장 전 실행 시 07-15가 아닌 07-14 기준으로 존재 여부 판단.
    """
    from backend.app.db.database import get_db_connection
    from backend.app.core.trading_calendar import (
        get_current_trading_day_str,
        get_previous_trading_day_str,
    )

    # 가장 최근 확정된 거래일 — 다운로드 파이프라인의 qry_dt와 동일 기준 (P10)
    trading_day = get_previous_trading_day_str(get_current_trading_day_str())
    conn = await get_db_connection()

    cursor = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM master_stocks_table WHERE date = ?",
        (trading_day,),
    )
    row = await cursor.fetchone()
    confirmed_exists = (row["cnt"] if row else 0) > 0

    cursor = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM stock_5d_bars WHERE dt = ?",
        (trading_day,),
    )
    row = await cursor.fetchone()
    bars_5d_exists = (row["cnt"] if row else 0) > 0

    return {
        "trading_day": trading_day,
        "confirmed_exists": confirmed_exists,
        "5d_exists": bars_5d_exists,
    }


