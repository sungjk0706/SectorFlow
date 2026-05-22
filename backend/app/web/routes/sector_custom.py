# -*- coding: utf-8 -*-
"""업종분류 커스텀 REST API 라우터.

8개 엔드포인트:
  GET  /api/sector-custom            — Merged_View 전체 조회
  POST /api/sector-custom/rename     — 업종명 변경
  POST /api/sector-custom/create     — 신규 업종 등록
  POST /api/sector-custom/delete     — 업종 삭제
  POST /api/sector-custom/move-stock — 종목 이동 (단건)
  POST /api/sector-custom/move-stocks — 종목 이동 (배치)
  POST /api/sector-custom/delete-cache — 캐시 삭제
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.web.deps import get_current_user

_log = logging.getLogger(__name__)


def _maybe_warning() -> dict:
    """장중(WS 구독 구간)이면 warning 필드를 반환, 아니면 빈 dict."""
    from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
    if is_ws_subscribe_window():
        return {"warning": "장중 변경은 즉시 매매에 반영됩니다"}
    return {}


router = APIRouter(prefix="/api/sector-custom", tags=["sector-custom"])

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

class DeleteCacheRequest(BaseModel):
    type: str  # "snapshot" | "avg_amt"


# ── WS 브로드캐스트 헬퍼 (Task 3.4) ────────────────────────────────

def broadcast_sector_custom_changed() -> None:
    """sector-custom-changed WS 이벤트 브로드캐스트.

    현재 Custom_Data + merged_sectors + no_sector_count를 페이로드로 전송.
    """
    from backend.app.core.sector_custom_data import load_custom_data
    from backend.app.core.sector_mapping import get_merged_all_sectors
    from backend.app.web.ws_manager import ws_manager

    custom = load_custom_data()
    merged = get_merged_all_sectors()

    # "업종명없음" 소속 종목 수 계산
    no_sector_count = 0
    filter_summary = ""
    try:
        from backend.app.services.engine_service import get_all_sector_stocks
        import backend.app.services.engine_service as es
        stocks = get_all_sector_stocks()
        if "업종명없음" in merged:
            no_sector_count = sum(
                1 for s in stocks if s["sector"] == "업종명없음"
            )
        filter_summary = getattr(es, "_latest_filter_summary", "")
    except Exception:
        pass

    payload = {
        "_v": 1,
        "custom_data": {
            "sectors": dict(custom.sectors),
            "stock_moves": dict(custom.stock_moves),
            "deleted_sectors": list(custom.deleted_sectors),
        },
        "merged_sectors": merged,
        "no_sector_count": no_sector_count,
        "filter_summary": filter_summary,
    }
    try:
        from backend.app.services.core_queues import get_broadcast_queue
        q = get_broadcast_queue()
        if not q.full():
            q.put_nowait({"type": "sector-custom-changed", "data": payload})
    except Exception:
        ws_manager.broadcast("sector-custom-changed", payload)



async def _trigger_recompute() -> None:
    """업종순위 재계산 신호 전송 (Step 6: 컨트롤 플레인 우회 배관 연동)."""
    try:
        from backend.app.services.core_queues import get_control_queue

        control_queue = get_control_queue()
        await control_queue.put({
            "type": "RECOMPUTE_SECTOR",
            "payload": {},
        })
    except Exception as e:
        _log.warning("[업종관리] 업종순위 재계산 신호 전송 실패: %s", e)


# ── GET /api/sector-custom ───────────────────────────────────────────

@router.get("/all-stocks")
async def get_all_stocks(_: str = Depends(get_current_user)):
    """전체 종목(매매부적격 제외) 조회 — 업종분류 페이지 전용."""
    from backend.app.services.engine_service import get_all_sector_stocks
    stocks = await asyncio.to_thread(get_all_sector_stocks)
    return {"stocks": stocks}


@router.get("")
async def get_sector_custom(_: str = Depends(get_current_user)):
    """Merged_View 전체 조회."""
    from backend.app.core.sector_custom_data import load_custom_data
    from backend.app.core.sector_mapping import get_merged_all_sectors

    custom = load_custom_data()
    merged = get_merged_all_sectors()

    # "업종명없음" 소속 종목 수 계산 (broadcast_sector_custom_changed와 동일 로직)
    no_sector_count = 0
    filter_summary = ""
    try:
        from backend.app.services.engine_service import get_all_sector_stocks
        import backend.app.services.engine_service as es
        stocks = get_all_sector_stocks()
        if "업종명없음" in merged:
            no_sector_count = sum(
                1 for s in stocks if s["sector"] == "업종명없음"
            )
        filter_summary = getattr(es, "_latest_filter_summary", "")
    except Exception:
        pass

    return {
        "custom_data": {
            "sectors": dict(custom.sectors),
            "stock_moves": dict(custom.stock_moves),
            "deleted_sectors": list(custom.deleted_sectors),
        },
        "merged_sectors": merged,
        "no_sector_count": no_sector_count,
        "filter_summary": filter_summary,
        "edit_window_open": True,
    }


# ── POST /api/sector-custom/rename ──────────────────────────────────

@router.post("/rename")
async def rename_sector(body: RenameRequest, _: str = Depends(get_current_user)):
    """업종명 변경."""
    try:
        from backend.app.core.sector_custom_data import rename_sector as _rename
        _rename(body.old_name, body.new_name)
        broadcast_sector_custom_changed()
        await _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/create ──────────────────────────────────

@router.post("/create")
async def create_sector(body: CreateRequest, _: str = Depends(get_current_user)):
    """신규 업종 등록."""
    try:
        from backend.app.core.sector_custom_data import create_sector as _create
        _create(body.name)
        broadcast_sector_custom_changed()
        await _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/delete ──────────────────────────────────

@router.post("/delete")
async def delete_sector(body: DeleteRequest, _: str = Depends(get_current_user)):
    """업종 삭제."""
    try:
        from backend.app.core.sector_custom_data import delete_sector as _delete
        _delete(body.name)
        broadcast_sector_custom_changed()
        await _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/move-stock ──────────────────────────────

@router.post("/move-stock")
async def move_stock(body: MoveStockRequest, _: str = Depends(get_current_user)):
    """종목 업종 이동."""
    try:
        from backend.app.core.sector_custom_data import move_stock as _move
        _move(body.stock_code, body.target_sector)
        broadcast_sector_custom_changed()
        await _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/move-stocks (배치) ───────────────────────

@router.post("/move-stocks")
async def move_stocks(body: MoveStocksRequest, _: str = Depends(get_current_user)):
    """종목 배치 업종 이동 — WS 이벤트 + 재계산 1회만 발생."""
    try:
        from backend.app.core.sector_custom_data import move_stock as _move
        for code in body.stock_codes:
            _move(code, body.target_sector)
        broadcast_sector_custom_changed()
        await _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/trigger-snapshot-download ──────────────────

@router.post("/trigger-snapshot-download")
async def trigger_snapshot_download(_: str = Depends(get_current_user)):
    """수동 확정시세 다운로드 실행"""
    try:
        from backend.app.services import engine_service
        if getattr(engine_service, "_confirmed_refresh_running", False):
            return {"ok": False, "error": "전종목 재조회가 이미 진행 중입니다."}
        
        engine_service._pending_stock_details.clear()
        engine_service._sector_stock_layout.clear()
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache([])
        import backend.app.core.industry_map as _ind_mod
        _ind_mod._eligible_stock_codes.clear()
        from backend.app.services.market_close_pipeline import fetch_unified_confirmed_data
        asyncio.create_task(fetch_unified_confirmed_data(engine_service))
        _log.info("[업종관리] 수동 확정데이터 다운로드 시작")
        return {"ok": True}
    except Exception as e:
        _log.error("[업종관리] 수동 확정데이터 다운로드 실패: %s", e)
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/trigger-avg-amt-download ──────────────────

@router.post("/trigger-avg-amt-download")
async def trigger_avg_amt_download(_: str = Depends(get_current_user)):
    """수동 5일 거래대금 다운로드 실행"""
    try:
        from backend.app.services import engine_service
        engine_service._avg_amt_5d.clear()
        engine_service._high_5d_cache.clear()
        engine_service._avg_amt_needs_bg_refresh = True
        engine_service._broadcast_avg_amt_progress(0, 0, status="cache_deleted")
        asyncio.create_task(engine_service.refresh_avg_amt_5d_cache())
        _log.info("[업종관리] 수동 5일 거래대금 다운로드 시작")
        return {"ok": True}
    except Exception as e:
        _log.error("[업종관리] 수동 5일 거래대금 다운로드 실패: %s", e)
        return {"ok": False, "error": str(e)}
