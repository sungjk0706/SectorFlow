# -*- coding: utf-8 -*-
"""계좌 상태 account-update WS 브로드캐스트 — 페이지별 페이로드 분리.

체결·잔고·실시간 시세 변경 시 delta 방식으로 전송하며, 활성 페이지(수익현황/매도포지션)에
따라 경량화 페이로드 또는 전체 페이로드를 선택적으로 전송한다.
"""
from __future__ import annotations
import logging
from backend.app.services.engine_symbol_utils import _base_stk_cd
from backend.app.services.engine_account_notify import (
    notify_cache,
    _compute_position_delta,
    _snap_equal,
    _safe_broadcast,
    _rebuild_positions_cache,
    _POSITION_CMP_KEYS,
)

logger = logging.getLogger(__name__)


async def broadcast_account_update(positions: list[dict], snapshot: dict, reason: str | None = None) -> None:
    """체결·잔고·실시간 시세 변경 시 → WS account-update (delta 방식, 페이지별 페이로드 분리)."""
    changed_positions, removed_codes = _compute_position_delta(positions)
    snapshot_changed = not _snap_equal(snapshot, notify_cache.snapshot_sent)
    if not changed_positions and not removed_codes and not snapshot_changed:
        return

    from backend.app.web.ws_manager import ws_manager
    active_pages = ws_manager.get_active_pages()

    await _broadcast_account_to_pages(changed_positions, removed_codes, snapshot, active_pages)
    _update_account_notify_cache(positions, snapshot)
    _log_account_broadcast(reason, snapshot, positions, changed_positions, removed_codes, active_pages)


async def _broadcast_account_to_pages(changed_positions, removed_codes, snapshot, active_pages) -> None:
    """활성 페이지에 맞춰 account-update 페이로드 전송 (수익현황 경량화 / 매도포지션 전체)."""
    from backend.app.web.ws_manager import ws_manager
    profit_overview_active = "profit-overview" in active_pages
    sell_position_active = "sell-position" in active_pages

    # 수익현황 페이지만 활성: 경량화 페이로드 전송
    if profit_overview_active and not sell_position_active:
        lightweight_payload = _build_lightweight_payload_for_profit_overview(snapshot, changed_positions, removed_codes)
        try:
            await ws_manager.broadcast_to_pages("account-update", lightweight_payload, {"profit-overview"})
        except Exception as e:
            logger.warning("[시스템] 수익현황 경량화 페이로드 전송 실패: %s", e, exc_info=True)
        return

    # sell-position 페이지 활성 또는 두 페이지 모두 활성: 전체 페이로드 전송
    payload = {
        "snapshot": dict(snapshot),
        "changed_positions": changed_positions,
        "removed_codes": removed_codes,
    }
    target_pages = set()
    if sell_position_active:
        target_pages.add("sell-position")
    if profit_overview_active and sell_position_active:
        target_pages.add("profit-overview")

    if target_pages:
        try:
            await ws_manager.broadcast_to_pages("account-update", payload, target_pages)
        except Exception as e:
            logger.warning("[시스템] 계좌 화면 전송 실패: %s", e, exc_info=True)
    else:
        await _safe_broadcast("account-update", payload)


def _update_account_notify_cache(positions: list[dict], snapshot: dict) -> None:
    """전송 후 delta 캐시 갱신 — snapshot_sent·position_sent·positions_code_set 동기화."""
    notify_cache.snapshot_sent = dict(snapshot)
    notify_cache.position_sent = {}
    for p in positions:
        cd = str(p.get("stk_cd", "") or "").strip()
        if cd:
            notify_cache.position_sent[cd] = dict(p)
    # notify_cache.positions_code_set 동기화 — real-data 필터링용 O(1) Set 캐시
    _rebuild_positions_cache(positions)


def _log_account_broadcast(reason, snapshot, positions, changed_positions, removed_codes, active_pages) -> None:
    """계좌 화면 전송 로그 (price_tick 사유는 제외)."""
    if not reason or reason.startswith("price_tick"):
        return
    profit_overview_active = "profit-overview" in active_pages
    sell_position_active = "sell-position" in active_pages
    cur_pairs = [
        (_base_stk_cd(str(p.get("stk_cd", "") or "")), p.get("cur_price"))
        for p in positions
        if int(p.get("qty", 0) or 0) > 0
    ]
    logger.info(
        "[시스템] 계좌 화면 전송 사유=%s 총평가=%s 보유현재가=%s 변경=%d 제거=%d 수익개요=%s 매도포지션=%s",
        reason, snapshot.get("total_eval"), cur_pairs,
        len(changed_positions), len(removed_codes),
        profit_overview_active, sell_position_active,
    )


def _build_lightweight_payload_for_profit_overview(snapshot: dict, changed_positions: list[dict], removed_codes: list[str]) -> dict:
    """수익현황 페이지용 경량화 페이로드 생성 — snapshot 핵심 필드 + 보유종목 최소 필드만 포함."""
    lightweight_snapshot = {
        "deposit": snapshot.get("deposit"),
        "orderable": snapshot.get("orderable"),
        "accumulated_investment": snapshot.get("accumulated_investment"),
        "initial_deposit": snapshot.get("initial_deposit"),
        "total_eval_amount": snapshot.get("total_eval_amount"),
        "total_pnl": snapshot.get("total_pnl"),
        "total_pnl_rate": snapshot.get("total_pnl_rate"),
    }
    lightweight_positions = [
        {k: p.get(k) for k in _POSITION_CMP_KEYS}
        for p in changed_positions
    ]
    return {
        "snapshot": lightweight_snapshot,
        "position_count": snapshot.get("position_count", 0),
        "changed_positions": lightweight_positions,
        "removed_codes": removed_codes,
    }
