# -*- coding: utf-8 -*-
"""
실시간 통신 구독 제어 모듈 — 지수(0J), 실시간시세(0B) 독립 제어.

인메모리 상태 관리 + REG/UNREG 오케스트레이션.
각 grp_no는 독립적으로 REG/UNREG — 한쪽 해지가 다른 쪽에 영향 없음.

grp_no 매핑:
| grp | 용도         | type |
|-----|-------------|------|
| 2   | 지수 실시간  | 0J   |
| 4   | 종목 시세    | 0B   |
| 10  | 계좌         | 00, 04 |
"""
from __future__ import annotations
import asyncio
import time
import logging
from backend.app.services import engine_state
from backend.app.services.engine_lifecycle import schedule_engine_task
logger = logging.getLogger(__name__)

# ── 인메모리 상태 ──────────────────────────────────────────────────────────
# 상태는 engine_state.py의 state에 통합 관리 (단일 소스 진리)

# ── 동시 변경 직렬화 ──────────────────────────────────────────────────────
_lock: asyncio.Lock | None = None

def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


# ---------------------------------------------------------------------------
# 상태 조회
# ---------------------------------------------------------------------------

def get_subscribe_status() -> dict[str, bool]:
    """현재 구독 상태 반환."""
    return {
        "quote_subscribed": engine_state.state.quote_subscribed,
        "index_subscribed": engine_state.state.index_subscribed,
    }


# ---------------------------------------------------------------------------
# 상태 변경 + 실시간 통신 전송
# ---------------------------------------------------------------------------

def _set_status(
    quote: bool | None = None,
    index: bool | None = None,
) -> None:
    """상태 변경 시에만 실시간 통신 ws-subscribe-status 전송."""
    changed = False
    if quote is not None and quote != engine_state.state.quote_subscribed:
        engine_state.state.quote_subscribed = quote
        changed = True
    if index is not None and index != engine_state.state.index_subscribed:
        engine_state.state.index_subscribed = index
        changed = True

    if changed:
        from backend.app.services.engine_account_notify import _broadcast
        schedule_engine_task(_broadcast("ws-subscribe-status", {
            "_v": 1,
            "quote_subscribed": engine_state.state.quote_subscribed,
            "index_subscribed": engine_state.state.index_subscribed,
        }), context="ws-subscribe-status 전송")


def broadcast_ws_connection_status(connected: bool) -> None:
    """키움 실시간 통신 연결/해제 상태를 화면으로 전송 (상태 변경 시에만)."""
    if engine_state.state.ws_connection_status == connected:
        return  # 상태 변경 없음 → 전송 생략
    engine_state.state.ws_connection_status = connected
    from backend.app.services.engine_account_notify import _broadcast
    schedule_engine_task(_broadcast("ws-connection-status", {
        "_v": 1,
        "connected": connected,
        "timestamp": time.time(),
    }), context="ws-connection-status 전송")


# ---------------------------------------------------------------------------
# 계좌 구독 보장 (실전매매 멱등)
# ---------------------------------------------------------------------------

async def _ensure_account_subscription() -> None:
    """실전매매에서 어떤 구독이든 시작하면 계좌(grp 10) 구독도 함께 보장 (멱등).

    가상매매에서는 계좌 구독 안 함.
    """
    from backend.app.core.trade_mode import is_virtual_mode
    if is_virtual_mode(engine_state.state.integrated_system_settings_cache):
        return

    # 이미 구독 중이면 작업 없음 (멱등)
    if engine_state.state.ws_account_subscribed:
        return

    from backend.app.services import engine_ws_reg
    try:
        await engine_ws_reg.subscribe_account_realtime()
        logger.info("[구독] 실전매매 — 계좌(그룹 10) 구독 보장")
    except Exception as e:
        logger.debug("[구독] 계좌 구독 보장 실패: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# 구독 시작 — 멱등 REG 등록
# ---------------------------------------------------------------------------

async def start_quote() -> dict:
    """grp 4(0B) REG 등록. 이미 활성이면 작업 없음 (멱등).

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _get_lock():
        if engine_state.state.quote_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        if not _ws_connected():
            return {"ok": False, "message": "실시간 통신 미연결 상태"}

        from backend.app.services import engine_ws_reg
        from backend.app.services.daily_time_scheduler import is_nxt_only_window
        try:
            await engine_ws_reg.subscribe_sector_stocks_0b(nxt_only=is_nxt_only_window())
            _set_status(quote=True)
            # 계좌 구독 보장 — 실전매매에서만 (1차 경로 분리)
            from backend.app.core.trade_mode import is_virtual_mode
            if not is_virtual_mode(engine_state.state.integrated_system_settings_cache):
                await _ensure_account_subscription()
            logger.info("[구독] 실시간시세(0B, 그룹 4) 구독 시작")
            return {"ok": True, "status": get_subscribe_status()}
        except Exception as e:
            logger.debug("[구독] 실시간시세 구독 시작 실패: %s", e, exc_info=True)
            return {"ok": False, "message": str(e)}


# ---------------------------------------------------------------------------
# 구독 해지 — grp 단위 독립 UNREG
# ---------------------------------------------------------------------------

async def stop_quote() -> dict:
    """grp 4(0B)만 UNREG. quote_subscribed만 False.

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _get_lock():
        if not engine_state.state.quote_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        from backend.app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp("4")
        _set_status(quote=False)
        logger.info("[구독] 실시간시세(0B, 그룹 4) 구독 해지")
        return {"ok": True, "status": get_subscribe_status()}


# ---------------------------------------------------------------------------
# 파이프라인 통합 — 설정 기반 조건부 REG
# ---------------------------------------------------------------------------

async def run_conditional_reg_pipeline() -> None:
    """index_auto_subscribe / quote_auto_subscribe에 따라 조건부 REG.

    시간대 자의적 판정 제거 — 설정 기반으로만 동작 (사용자 설정 존중).
    모두 false면 종료.
    """
    async with _get_lock():
        from backend.app.services import engine_ws_reg
        from backend.app.services.daily_time_scheduler import is_nxt_only_window

        try:
            await engine_ws_reg.subscribe_sector_stocks_0b(nxt_only=is_nxt_only_window())
            _set_status(quote=True)
            logger.info("[구독] 실시간시세(0B) 자동 구독")
        except Exception as e:
            logger.debug("[구독] 실시간시세 자동 구독 실패: %s", e, exc_info=True)

        try:
            index_ok = await engine_ws_reg.subscribe_index_realtime()
            if index_ok:
                _set_status(index=True)
                logger.info("[구독] 업종지수(0J) 자동 구독")
        except Exception as e:
            logger.debug("[구독] 업종지수 자동 구독 실패: %s", e, exc_info=True)

        # 실전매매에서 구독 시작했으면 계좌 구독 보장 — 1차 경로 분리
        from backend.app.core.trade_mode import is_virtual_mode
        if not is_virtual_mode(engine_state.state.integrated_system_settings_cache):
            await _ensure_account_subscription()


# ---------------------------------------------------------------------------
# 잔존 구독 정리 — 새 세션 시 인메모리 구독 상태 초기화 (최선 노력)
# ---------------------------------------------------------------------------

async def cleanup_stale_subscriptions() -> None:
    """새 세션 시작 시 인메모리 구독 상태 초기화 (최선 노력).

    서버 측 구독은 다음 REG의 refresh='0'(reset_first=True)이 덮어씀.
    인메모리 상태(_subscribed 플래그)만 초기화 — UNREG 미전송.
    실시간 통신 미연결 시 생략 + 경고 로그.
    """
    if not _ws_connected():
        logger.warning("[구독] 잔존 구독 정리 생략 — 실시간 미연결")
        return

    # 서버 측 구독은 다음 REG의 refresh='0'(reset_first=True)이 덮어씀.
    # REMOVE ACK 대기 없이 인메모리 상태만 초기화 — 장외 시간 90초 지연 응답으로 인한 이벤트 오염 방지.
    for entry in engine_state.state.master_stocks_cache.values():
        entry.pop("_subscribed", None)
    _set_status(quote=False, index=False)
    logger.debug("[구독] 잔존 구독 정리 — 전체 끄기 (메모리 리셋, 서버 측은 다음 구독 등록 갱신=0으로 덮어씀)")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _ws_connected() -> bool:
    """실시간 통신 연결 + 로그인 완료 여부."""
    return bool(engine_state.state.connector_manager and engine_state.state.connector_manager.is_connected() and engine_state.state.login_ok)
