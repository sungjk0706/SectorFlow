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

from app.web.deps import get_current_user

_log = logging.getLogger(__name__)


def _maybe_warning() -> dict:
    """장중(WS 구독 구간)이면 warning 필드를 반환, 아니면 빈 dict."""
    from app.services.daily_time_scheduler import is_ws_subscribe_window
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
    from app.core.sector_custom_data import load_custom_data
    from app.core.sector_mapping import get_merged_all_sectors
    from app.web.ws_manager import ws_manager

    custom = load_custom_data()
    merged = get_merged_all_sectors()

    # "업종명없음" 소속 종목 수 계산
    no_sector_count = 0
    if "업종명없음" in merged:
        from app.services.engine_service import get_all_sector_stocks
        stocks = get_all_sector_stocks()
        no_sector_count = sum(
            1 for s in stocks if s["sector"] == "업종명없음"
        )

    payload = {
        "_v": 1,
        "custom_data": {
            "sectors": dict(custom.sectors),
            "stock_moves": dict(custom.stock_moves),
            "deleted_sectors": list(custom.deleted_sectors),
        },
        "merged_sectors": merged,
        "no_sector_count": no_sector_count,
    }
    ws_manager.broadcast("sector-custom-changed", payload)



def _trigger_recompute() -> None:
    """업종순위 재계산 + sector-scores/sector-stocks-refresh WS 브로드캐스트."""
    try:
        from app.services.engine_service import recompute_sector_summary_now
        recompute_sector_summary_now()
        from app.services.engine_account_notify import (
            notify_desktop_sector_scores,
            notify_desktop_sector_stocks_refresh,
        )
        notify_desktop_sector_scores(force=True)
        notify_desktop_sector_stocks_refresh()
    except Exception as e:
        _log.warning("[업종관리] 업종순위 재계산 실패: %s", e)


# ── GET /api/sector-custom ───────────────────────────────────────────

@router.get("/all-stocks")
async def get_all_stocks(_: str = Depends(get_current_user)):
    """전체 종목(매매부적격 제외) 조회 — 업종분류 페이지 전용."""
    from app.services.engine_service import get_all_sector_stocks
    stocks = await asyncio.to_thread(get_all_sector_stocks)
    return {"stocks": stocks}


@router.get("")
async def get_sector_custom(_: str = Depends(get_current_user)):
    """Merged_View 전체 조회."""
    from app.core.sector_custom_data import load_custom_data
    from app.core.sector_mapping import get_merged_all_sectors

    custom = load_custom_data()
    merged = get_merged_all_sectors()

    # "업종명없음" 소속 종목 수 계산 (broadcast_sector_custom_changed와 동일 로직)
    no_sector_count = 0
    if "업종명없음" in merged:
        from app.services.engine_service import get_all_sector_stocks
        stocks = get_all_sector_stocks()
        no_sector_count = sum(
            1 for s in stocks if s["sector"] == "업종명없음"
        )

    return {
        "custom_data": {
            "sectors": dict(custom.sectors),
            "stock_moves": dict(custom.stock_moves),
            "deleted_sectors": list(custom.deleted_sectors),
        },
        "merged_sectors": merged,
        "no_sector_count": no_sector_count,
        "edit_window_open": True,
    }


# ── POST /api/sector-custom/rename ──────────────────────────────────

@router.post("/rename")
async def rename_sector(body: RenameRequest, _: str = Depends(get_current_user)):
    """업종명 변경."""
    try:
        from app.core.sector_custom_data import rename_sector as _rename
        _rename(body.old_name, body.new_name)
        broadcast_sector_custom_changed()
        _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/create ──────────────────────────────────

@router.post("/create")
async def create_sector(body: CreateRequest, _: str = Depends(get_current_user)):
    """신규 업종 등록."""
    try:
        from app.core.sector_custom_data import create_sector as _create
        _create(body.name)
        broadcast_sector_custom_changed()
        _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/delete ──────────────────────────────────

@router.post("/delete")
async def delete_sector(body: DeleteRequest, _: str = Depends(get_current_user)):
    """업종 삭제."""
    try:
        from app.core.sector_custom_data import delete_sector as _delete
        _delete(body.name)
        broadcast_sector_custom_changed()
        _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/move-stock ──────────────────────────────

@router.post("/move-stock")
async def move_stock(body: MoveStockRequest, _: str = Depends(get_current_user)):
    """종목 업종 이동."""
    try:
        from app.core.sector_custom_data import move_stock as _move
        _move(body.stock_code, body.target_sector)
        broadcast_sector_custom_changed()
        _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/move-stocks (배치) ───────────────────────

@router.post("/move-stocks")
async def move_stocks(body: MoveStocksRequest, _: str = Depends(get_current_user)):
    """종목 배치 업종 이동 — WS 이벤트 + 재계산 1회만 발생."""
    try:
        from app.core.sector_custom_data import move_stock as _move
        for code in body.stock_codes:
            _move(code, body.target_sector)
        broadcast_sector_custom_changed()
        _trigger_recompute()
        return {"ok": True, **_maybe_warning()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── POST /api/sector-custom/delete-cache ─────────────────────────────

@router.post("/delete-cache")
async def delete_cache(body: DeleteCacheRequest, _: str = Depends(get_current_user)):
    """캐시 파일 삭제. Edit_Window 제한 없음 (언제든 가능)."""
    cache_type = body.type
    if cache_type not in ("snapshot", "avg_amt"):
        return {"ok": False, "error": f"지원하지 않는 캐시 타입: {cache_type}"}

    try:
        if cache_type == "snapshot":
            files = [
                _DATA_DIR / "confirmed_snapshot_cache.json",
                _DATA_DIR / "stock_name_cache.json",
                _DATA_DIR / "sector_layout_cache.json",
            ]
        else:  # avg_amt
            files = [
                _DATA_DIR / "avg_amt_5d_cache.json",
            ]

        def _delete_files():
            deleted = []
            for f in files:
                if f.exists():
                    f.unlink()
                    deleted.append(f.name)
            return deleted

        deleted = await asyncio.to_thread(_delete_files)
        _log.info("[업종관리] 저장데이터 삭제 완료 (%s): %s", cache_type, deleted)

        # snapshot 캐시 삭제 후: 메모리 클리어 → fetch_unified_confirmed_data 재갱신 트리거
        if cache_type == "snapshot":
            try:
                from app.services import engine_service
                if getattr(engine_service, "_confirmed_refresh_running", False):
                    _log.info("[업종관리] 전종목 재조회 진행 중 — 재조회 생략")
                else:
                    engine_service._pending_stock_details.clear()
                    engine_service._sector_stock_layout.clear()
                    from app.services.engine_account_notify import _rebuild_layout_cache
                    _rebuild_layout_cache([])
                    import app.core.industry_map as _ind_mod
                    _ind_mod._eligible_stock_codes.clear()
                    from app.services.market_close_pipeline import fetch_unified_confirmed_data
                    asyncio.create_task(fetch_unified_confirmed_data(engine_service))
                    _log.info("[업종관리] 확정데이터 저장데이터 삭제 → 전종목 재조회 시작")
            except Exception as e2:
                _log.warning("[업종관리] 확정데이터 저장데이터 삭제 후 재조회 실패: %s", e2)

        # avg_amt 캐시 삭제 후 이벤트 파이프라인: 메모리 클리어 → 재구축 트리거
        elif cache_type == "avg_amt":
            try:
                from app.services import engine_service
                engine_service._avg_amt_5d.clear()
                engine_service._high_5d_cache.clear()
                engine_service._avg_amt_needs_bg_refresh = True
                engine_service._broadcast_avg_amt_progress(0, 0, status="cache_deleted")
                asyncio.create_task(engine_service.refresh_avg_amt_5d_cache())
                _log.info("[업종관리] 5일 저장데이터 삭제 → 재구축 시작")
            except Exception as e2:
                _log.warning("[업종관리] 5일 저장데이터 삭제 후 재구축 실패: %s", e2)

        return {"ok": True}
    except Exception as e:
        _log.error("[업종관리] 저장데이터 삭제 실패 (%s): %s", cache_type, e)
        return {"ok": False, "error": str(e)}
