# -*- coding: utf-8 -*-
"""계좌 상태 WS 브로드캐스트 — 페이지별 이벤트 분리 (P23 일관성).

체결·잔고·실시간 시세 변경 시 delta 방식으로 전송하며, 활성 페이지에 따라
별도 이벤트로 분리하여 전송한다 (각 이벤트 단일 payload 계약 — P23).
- 수익현황 페이지 활성 → `account-summary-update` (경량화 payload: snapshot 7필드 + 보유종목 최소 필드)
- 매도포지션 페이지 활성 → `account-update` (전체 payload: snapshot 전체 + 보유종목 전체 필드)
- 활성 페이지 없음 → `account-update` (전체 payload, 폴백)
"""
from __future__ import annotations
import logging
from backend.app.services.engine_symbol_utils import _base_stk_cd
from backend.app.services.engine_account_notify import (
    notify_cache,
    _compute_position_delta,
    _snap_equal,
    _safe_broadcast,
    _next_revision,
    _rebuild_positions_cache,
    _POSITION_CMP_KEYS,
)

logger = logging.getLogger(__name__)


async def broadcast_account_update(positions: list[dict], snapshot: dict, reason: str | None = None) -> None:
    """체결·잔고·실시간 시세 변경 시 → WS account-update / account-summary-update (delta 방식, 페이지별 이벤트 분리)."""
    changed_positions, removed_codes = _compute_position_delta(positions)
    snapshot_changed = not _snap_equal(snapshot, notify_cache.snapshot_sent)
    if not changed_positions and not removed_codes and not snapshot_changed:
        return

    from backend.app.web.ws_manager import ws_manager
    active_pages = ws_manager.get_active_pages()

    revision = _next_revision("account")
    await _broadcast_account_to_pages(changed_positions, removed_codes, snapshot, active_pages, revision)
    _update_account_notify_cache(positions, snapshot)
    _log_account_broadcast(reason, snapshot, positions, changed_positions, removed_codes, active_pages)

    # 보유 종목 변경 시 화면별 구독 대상 갱신 + 활성 연결 갱신 (태스크 2세션).
    # 보유 종목·수익 현황 대상이 바뀌면 활성 연결의 구독을 자동으로 최신화.
    # price_tick 사유는 빈번하므로 보유 종목 코드 집합이 실제로 바뀐 경우에만 갱신.
    if reason and not reason.startswith("price_tick"):
        try:
            from backend.app.services.page_subscription_targets import refresh_active_connections
            await refresh_active_connections(
                reason, {"sell-position", "profit-overview"},
            )
        except Exception as e:
            logger.warning("[시스템] 보유 종목 구독 대상 갱신 실패: %s", e, exc_info=True)


async def _broadcast_account_to_pages(changed_positions, removed_codes, snapshot, active_pages, revision: int = 0) -> None:
    """활성 페이지에 맞춰 이벤트 분리 전송 (P23 — 각 이벤트 단일 payload 계약).

    - 수익현황만 활성 → `account-summary-update` (경량화 payload)
    - 매도포지션 활성 (또는 두 페이지 모두 활성) → `account-update` (전체 payload)
    - 활성 페이지 없음 → `account-update` (전체 payload, 폴백)
    """
    from backend.app.web.ws_manager import ws_manager
    profit_overview_active = "profit-overview" in active_pages
    sell_position_active = "sell-position" in active_pages

    # 수익현황 페이지만 활성: account-summary-update 경량화 이벤트 전송
    if profit_overview_active and not sell_position_active:
        lightweight_payload = _build_lightweight_payload_for_profit_overview(snapshot, changed_positions, removed_codes)
        try:
            lightweight_payload["freshness"] = {"group": "account", "revision": revision}
            await ws_manager.broadcast_to_pages("account-summary-update", lightweight_payload, {"profit-overview"})
        except Exception as e:
            logger.warning("[시스템] 수익현황 경량화 페이로드 전송 실패: %s", e, exc_info=True)
        return

    # sell-position 페이지 활성 또는 두 페이지 모두 활성: account-update 전체 페이로드 전송
    payload = {
        "snapshot": dict(snapshot),
        "changed_positions": changed_positions,
        "removed_codes": removed_codes,
        "freshness": {"group": "account", "revision": revision},
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
        await _safe_broadcast("account-update", payload, group="account", revision=revision)


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
    """계좌 화면 전송 로그 (price_tick 사유는 제외).

    보유 종목 변경·제거가 있으면 INFO(의미 있는 변화), 없으면 DEBUG(고빈도 정상 heartbeat).
    snapshot만 바뀐 경우(총평가 변동 등)도 INFO — 사용자가 잔고 변화를 콘솔에서 확인 가능.
    """
    if not reason or reason.startswith("price_tick"):
        return
    profit_overview_active = "profit-overview" in active_pages
    sell_position_active = "sell-position" in active_pages
    cur_pairs = [
        (_base_stk_cd(str(p.get("stk_cd", "") or "")), p.get("cur_price"))
        for p in positions
        if int(p.get("qty", 0) or 0) > 0
    ]
    has_position_change = bool(changed_positions) or bool(removed_codes)
    log_level = logging.INFO if has_position_change else logging.DEBUG
    logger.log(
        log_level,
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
