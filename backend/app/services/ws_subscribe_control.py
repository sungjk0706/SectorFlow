from __future__ import annotations
# -*- coding: utf-8 -*-
"""
WS 구독 제어 모듈 — 지수(0J), 실시간시세(0B) 독립 제어.

인메모리 상태 관리 + REG/UNREG 오케스트레이션.
각 grp_no는 독립적으로 REG/UNREG — 한쪽 해지가 다른 쪽에 영향 없음.

grp_no 매핑:
| grp | 용도         | type |
|-----|-------------|------|
| 2   | 지수 실시간  | 0J   |
| 4   | 종목 시세    | 0B   |
| 10  | 계좌         | 00, 04 |
"""

import asyncio

from backend.app.core.logger import get_logger
from backend.app.services.engine_state import state
from backend.app.services.engine_lifecycle import schedule_engine_task

logger = get_logger("engine")

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
        "quote_subscribed": state.quote_subscribed,
    }


# ---------------------------------------------------------------------------
# 상태 변경 + WS 브로드캐스트
# ---------------------------------------------------------------------------

def _set_status(
    quote: bool | None = None,
) -> None:
    """상태 변경 시에만 WS ws-subscribe-status 브로드캐스트."""
    changed = False
    if quote is not None and quote != state.quote_subscribed:
        state.quote_subscribed = quote
        changed = True

    if changed:
        from backend.app.services.engine_account_notify import _broadcast
        schedule_engine_task(_broadcast("ws-subscribe-status", {
            "_v": 1,
            "quote_subscribed": state.quote_subscribed,
        }), context="ws-subscribe-status 브로드캐스트")


def broadcast_ws_connection_status(connected: bool) -> None:
    """Kiwoom WebSocket 연결/해제 상태를 프론트엔드로 브로드캐스트 (상태 변경 시에만)."""
    if state.ws_connection_status == connected:
        return  # 상태 변경 없음 → 전송 생략
    state.ws_connection_status = connected
    from backend.app.services.engine_account_notify import _broadcast
    schedule_engine_task(_broadcast("ws-connection-status", {
        "_v": 1,
        "connected": connected,
        "timestamp": asyncio.get_event_loop().time(),
    }), context="ws-connection-status 브로드캐스트")


# ---------------------------------------------------------------------------
# 계좌 구독 보장 (실전모드 멱등)
# ---------------------------------------------------------------------------

async def _ensure_account_subscription() -> None:
    """실전모드에서 어떤 구독이든 시작하면 계좌(grp 10) 구독도 함께 보장 (멱등).

    테스트모드에서는 계좌 구독 안 함.
    """
    from backend.app.core.trade_mode import is_test_mode
    if is_test_mode(state.integrated_system_settings_cache):
        return

    # 이미 구독 중이면 no-op (멱등)
    if state.ws_account_subscribed:
        return

    from backend.app.services import engine_ws_reg
    try:
        await engine_ws_reg.subscribe_account_realtime()
        logger.info("[구독제어] 실전모드 — 계좌(grp 10) 구독 보장 완료")
    except Exception as e:
        logger.warning("[구독제어] 계좌 구독 보장 실패: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# 구독 시작 — 멱등 REG 등록
# ---------------------------------------------------------------------------

async def start_quote() -> dict:
    """grp 4(0B) REG 등록. 이미 활성이면 no-op (멱등).

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _get_lock():
        if state.quote_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        if not _ws_connected():
            return {"ok": False, "message": "WS 미연결 상태"}

        from backend.app.services import engine_ws_reg
        try:
            await engine_ws_reg.subscribe_sector_stocks_0b()
            _set_status(quote=True)
            await _ensure_account_subscription()
            logger.info("[구독제어] 실시간시세(0B, grp 4) 구독 시작 완료")
            return {"ok": True, "status": get_subscribe_status()}
        except Exception as e:
            logger.warning("[구독제어] 실시간시세 구독 시작 실패: %s", e, exc_info=True)
            return {"ok": False, "message": str(e)}


# ---------------------------------------------------------------------------
# 구독 해지 — grp 단위 독립 UNREG
# ---------------------------------------------------------------------------

async def stop_industry() -> dict:
    """업종 구독 해지 — no-op (하위 호환용 stub).

    하위 호환을 위해 함수 시그니처 유지, 항상 성공 반환.
    """
    return {"ok": True, "status": get_subscribe_status()}


async def stop_quote() -> dict:
    """grp 4(0B)만 UNREG. quote_subscribed만 False.

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _get_lock():
        if not state.quote_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        from backend.app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp("4")
        _set_status(quote=False)
        logger.info("[구독제어] 실시간시세(0B, grp 4) UNREG 완료")
        return {"ok": True, "status": get_subscribe_status()}


# ---------------------------------------------------------------------------
# 파이프라인 통합 — 설정 기반 조건부 REG
# ---------------------------------------------------------------------------

async def run_conditional_reg_pipeline() -> None:
    """index_auto_subscribe / quote_auto_subscribe에 따라 조건부 REG.

    WS 구독 구간 외이면 REG 호출 없이 종료.
    모두 false면 종료.
    """
    from backend.app.services.daily_time_scheduler import is_ws_subscribe_window

    settings = state.integrated_system_settings_cache

    if not await is_ws_subscribe_window(settings):
        logger.debug("[구독제어] 실시간 구독 구간 외 — REG 파이프라인 생략")
        return

    async with _get_lock():
        from backend.app.services import engine_ws_reg

        try:
            await engine_ws_reg.subscribe_sector_stocks_0b()
            _set_status(quote=True)
            logger.info("[구독제어] 실시간시세(0B) 자동 구독 완료")
        except Exception as e:
            logger.warning("[구독제어] 실시간시세 자동 구독 실패: %s", e, exc_info=True)

        try:
            await engine_ws_reg.subscribe_index_realtime()
            logger.info("[구독제어] 업종지수(0J) 자동 구독 완료")
        except Exception as e:
            logger.warning("[구독제어] 업종지수 자동 구독 실패: %s", e, exc_info=True)

        # 실전모드에서 구독 시작했으면 계좌 구독 보장
        await _ensure_account_subscription()


# ---------------------------------------------------------------------------
# 잔존 구독 정리 — 새 세션 시 grp_no=5,2,4,10 UNREG (best-effort)
# ---------------------------------------------------------------------------

async def cleanup_stale_subscriptions() -> None:
    """새 세션 시작 시 grp_no=5,2,4,10 UNREG (best-effort).

    UNREG 완료 후 상태 false 설정.
    WS 미연결 시 스킵 + warning 로그.
    """
    if not _ws_connected():
        logger.warning("[구독제어] 잔존 구독 정리 생략 — 실시간 미연결")
        return

    # 서버 측 구독은 다음 REG의 refresh='0'(reset_first=True)이 덮어씀.
    # REMOVE ACK 대기 없이 인메모리 상태만 초기화 — 장외 시간 90초 지연 응답으로 인한 이벤트 오염 방지.
    from backend.app.services.engine_state import state
    all_stocks = state.master_stocks_cache.copy()
    for entry in all_stocks.values():
        entry.pop("_subscribed", None)
    _set_status(quote=False)
    logger.debug("[구독제어] 잔존 구독 정리 완료 — 전체 OFF (인메모리 초기화, 서버 측은 다음 REG refresh=0으로 덮어씀)")


# ---------------------------------------------------------------------------
# 설정 변경 즉시 반영
# ---------------------------------------------------------------------------

async def on_setting_changed(key: str, value: bool) -> None:
    """quote_auto_subscribe 변경 시 즉시 반영.

    WS 구독 구간 밖이면 설정만 저장 (구독 변경 없음).
    """
    from backend.app.services.daily_time_scheduler import is_ws_subscribe_window

    settings = state.integrated_system_settings_cache

    if not await is_ws_subscribe_window(settings):
        logger.info(
            "[구독제어] 설정 변경 %s=%s — 실시간 구독 구간 외, 구독 변경 없음",
            key, value,
        )
        return

    if key == "quote_auto_subscribe":
        # 토글 제거 — 구독은 엔진이 자동 관리. 수동 해지 차단.
        logger.debug("[구독제어] quote_auto_subscribe 변경 무시 (엔진 자동 관리)")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _ws_connected() -> bool:
    """WS 연결 + 로그인 완료 여부."""
    # ConnectorManager가 있으면 우선 사용 (키움/LS 모두 지원)
    if state.connector_manager is not None:
        return bool(state.connector_manager.is_connected() and state.login_ok)
    # 하위 호환: 키움 단독
    return bool(state.active_connector and state.active_connector.is_connected() and state.login_ok)
