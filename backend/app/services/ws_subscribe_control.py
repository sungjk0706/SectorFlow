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
from __future__ import annotations

import asyncio
from types import ModuleType

from app.core.logger import get_logger

logger = get_logger("engine")

# ── 인메모리 상태 ──────────────────────────────────────────────────────────
_index_subscribed: bool = False      # grp 2, 0J 활성 여부
_quote_subscribed: bool = False      # grp 4, 0B 활성 여부

# ── 동시 변경 직렬화 ──────────────────────────────────────────────────────
_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# 상태 조회
# ---------------------------------------------------------------------------

def get_subscribe_status() -> dict[str, bool]:
    """현재 구독 상태 반환."""
    return {
        "index_subscribed": _index_subscribed,
        "quote_subscribed": _quote_subscribed,
    }


# ---------------------------------------------------------------------------
# 상태 변경 + WS 브로드캐스트
# ---------------------------------------------------------------------------

def _set_status(
    index: bool | None = None,
    quote: bool | None = None,
) -> None:
    """상태 변경 시에만 WS ws-subscribe-status 브로드캐스트."""
    global _index_subscribed, _quote_subscribed

    changed = False
    if index is not None and index != _index_subscribed:
        _index_subscribed = index
        changed = True
    if quote is not None and quote != _quote_subscribed:
        _quote_subscribed = quote
        changed = True

    if changed:
        from app.services.engine_account_notify import _broadcast
        _broadcast("ws-subscribe-status", {
            "_v": 1,
            "index_subscribed": _index_subscribed,
            "quote_subscribed": _quote_subscribed,
        })


def broadcast_ws_connection_status(connected: bool) -> None:
    """Kiwoom WebSocket 연결/해제 상태를 프론트엔드로 브로드캐스트."""
    from app.services.engine_account_notify import _broadcast
    _broadcast("ws-connection-status", {
        "_v": 1,
        "connected": connected,
        "timestamp": asyncio.get_event_loop().time(),
    })
    logger.debug("[구독제어] WS 연결 상태 화면전송: %s", connected)


# ---------------------------------------------------------------------------
# 계좌 구독 보장 (실전모드 멱등)
# ---------------------------------------------------------------------------

async def _ensure_account_subscription(es: ModuleType) -> None:
    """실전모드에서 어떤 구독이든 시작하면 계좌(grp 10) 구독도 함께 보장 (멱등).

    테스트모드에서는 계좌 구독 안 함.
    """
    from app.core.trade_mode import is_test_mode
    settings = getattr(es, "_settings_cache", None) or {}
    if is_test_mode(settings):
        return

    # 이미 구독 중이면 no-op (멱등)
    if getattr(es, "_ws_account_subscribed", False):
        return

    from app.services import engine_ws_reg
    try:
        await engine_ws_reg.subscribe_account_realtime(es)
        logger.info("[구독제어] 실전모드 — 계좌(grp 10) 구독 보장 완료")
    except Exception as e:
        logger.warning("[구독제어] 계좌 구독 보장 실패: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# 구독 시작 — 멱등 REG 등록
# ---------------------------------------------------------------------------

async def start_industry(es: ModuleType) -> dict:
    """업종 구독 — no-op (하위 호환용 stub).

    하위 호환을 위해 함수 시그니처 유지, 항상 성공 반환.
    """
    logger.debug("[구독제어] 업종 구독 비활성화 — sector_mapping 기반 자체 집계 사용")
    return {"ok": True, "status": get_subscribe_status()}


async def start_index(es: ModuleType) -> dict:
    """grp 2(0J) REG 등록. 이미 활성이면 no-op (멱등).

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _lock:
        if _index_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        if not _ws_connected(es):
            return {"ok": False, "message": "WS 미연결 상태"}

        from app.services import engine_ws_reg
        try:
            await engine_ws_reg.subscribe_index_realtime(es)
            _set_status(index=True)
            await _ensure_account_subscription(es)
            logger.info("[구독제어] 지수(0J, grp 2) 구독 시작 완료")
            return {"ok": True, "status": get_subscribe_status()}
        except Exception as e:
            logger.warning("[구독제어] 지수 구독 시작 실패: %s", e, exc_info=True)
            return {"ok": False, "message": str(e)}


async def start_quote(es: ModuleType) -> dict:
    """grp 4(0B) REG 등록. 이미 활성이면 no-op (멱등).

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _lock:
        if _quote_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        if not _ws_connected(es):
            return {"ok": False, "message": "WS 미연결 상태"}

        from app.services import engine_ws_reg
        try:
            await engine_ws_reg.subscribe_sector_stocks_0b(es)
            _set_status(quote=True)
            await _ensure_account_subscription(es)
            logger.info("[구독제어] 실시간시세(0B, grp 4) 구독 시작 완료")
            return {"ok": True, "status": get_subscribe_status()}
        except Exception as e:
            logger.warning("[구독제어] 실시간시세 구독 시작 실패: %s", e, exc_info=True)
            return {"ok": False, "message": str(e)}


# ---------------------------------------------------------------------------
# 구독 해지 — grp 단위 독립 UNREG
# ---------------------------------------------------------------------------

async def stop_industry(es: ModuleType) -> dict:
    """업종 구독 해지 — no-op (하위 호환용 stub).

    하위 호환을 위해 함수 시그니처 유지, 항상 성공 반환.
    """
    return {"ok": True, "status": get_subscribe_status()}


async def stop_index(es: ModuleType) -> dict:
    """grp 2(0J)만 UNREG. index_subscribed만 False.

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _lock:
        if not _index_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        from app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp(es, "2")
        _set_status(index=False)
        logger.info("[구독제어] 지수(0J, grp 2) UNREG 완료")
        return {"ok": True, "status": get_subscribe_status()}


async def stop_quote(es: ModuleType) -> dict:
    """grp 4(0B)만 UNREG. quote_subscribed만 False.

    Returns:
        {"ok": True, "status": {...}} on success,
        {"ok": False, "message": "..."} on error.
    """
    async with _lock:
        if not _quote_subscribed:
            return {"ok": True, "status": get_subscribe_status()}

        from app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp(es, "4")
        _set_status(quote=False)
        logger.info("[구독제어] 실시간시세(0B, grp 4) UNREG 완료")
        return {"ok": True, "status": get_subscribe_status()}


# ---------------------------------------------------------------------------
# 파이프라인 통합 — 설정 기반 조건부 REG
# ---------------------------------------------------------------------------

async def run_conditional_reg_pipeline(es: ModuleType) -> None:
    """index_auto_subscribe / quote_auto_subscribe에 따라 조건부 REG.

    WS 구독 구간 외이면 REG 호출 없이 종료.
    모두 false면 종료.
    """
    from app.services.daily_time_scheduler import is_ws_subscribe_window
    from app.core.settings_file import load_settings

    settings = load_settings()

    if not is_ws_subscribe_window(settings):
        logger.debug("[구독제어] 실시간 구독 구간 외 — REG 파이프라인 생략")
        return

    index_auto = True  # 토글 제거 — 지수 구독은 엔진이 항상 자동 관리
    quote_auto = True  # 토글 제거 — 구독은 엔진이 항상 자동 관리

    if not index_auto and not quote_auto:
        logger.debug("[구독제어] 모든 자동구독 OFF — REG 없이 파이프라인 완료")
        return

    async with _lock:
        from app.services import engine_ws_reg

        if index_auto:
            try:
                await engine_ws_reg.subscribe_index_realtime(es)
                _set_status(index=True)
                logger.info("[구독제어] 지수(0J) 자동 구독 완료")
            except Exception as e:
                logger.warning("[구독제어] 지수 자동 구독 실패: %s", e, exc_info=True)

        if quote_auto:
            try:
                await engine_ws_reg.subscribe_sector_stocks_0b(es)
                _set_status(quote=True)
                logger.info("[구독제어] 실시간시세(0B) 자동 구독 완료")
            except Exception as e:
                logger.warning("[구독제어] 실시간시세 자동 구독 실패: %s", e, exc_info=True)

        # 실전모드에서 하나라도 구독 시작했으면 계좌 구독 보장
        if index_auto or quote_auto:
            await _ensure_account_subscription(es)


# ---------------------------------------------------------------------------
# 잔존 구독 정리 — 새 세션 시 grp_no=5,2,4,10 UNREG (best-effort)
# ---------------------------------------------------------------------------

async def cleanup_stale_subscriptions(es: ModuleType) -> None:
    """새 세션 시작 시 grp_no=5,2,4,10 UNREG (best-effort).

    UNREG 완료 후 상태 false 설정.
    WS 미연결 시 스킵 + warning 로그.
    """
    if not _ws_connected(es):
        logger.warning("[구독제어] 잔존 구독 정리 생략 — 실시간 미연결")
        return

    # 서버 측 구독은 다음 REG의 refresh='0'(reset_first=True)이 덮어씀.
    # REMOVE ACK 대기 없이 인메모리 상태만 초기화 — 장외 시간 90초 지연 응답으로 인한 이벤트 오염 방지.
    subscribed = getattr(es, "_subscribed_stocks", None)
    if subscribed:
        subscribed.clear()

    _set_status(index=False, quote=False)
    logger.debug("[구독제어] 잔존 구독 정리 완료 — 전체 OFF (인메모리 초기화, 서버 측은 다음 REG refresh=0으로 덮어씀)")


# ---------------------------------------------------------------------------
# 설정 변경 즉시 반영
# ---------------------------------------------------------------------------

async def on_setting_changed(key: str, value: bool, es: ModuleType) -> None:
    """index_auto_subscribe / quote_auto_subscribe 변경 시 즉시 반영.

    WS 구독 구간 밖이면 설정만 저장 (구독 변경 없음).
    각 설정은 독립 처리 — 상대편 auto_subscribe 강제 false 없음.
    """
    logger.debug("[구독제어] 설정 변경 수신 %s=%s", key, value)
    from app.services.daily_time_scheduler import is_ws_subscribe_window
    from app.core.settings_file import load_settings

    settings = load_settings()

    if not is_ws_subscribe_window(settings):
        logger.info(
            "[구독제어] 설정 변경 %s=%s — 실시간 구독 구간 외, 구독 변경 없음",
            key, value,
        )
        return

    if key == "index_auto_subscribe":
        # 토글 제거 — 지수 구독은 엔진이 자동 관리. 수동 해지 차단.
        logger.debug("[구독제어] index_auto_subscribe 변경 무시 (엔진 자동 관리)")

    elif key == "quote_auto_subscribe":
        # 토글 제거 — 구독은 엔진이 자동 관리. 수동 해지 차단.
        logger.debug("[구독제어] quote_auto_subscribe 변경 무시 (엔진 자동 관리)")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _ws_connected(es: ModuleType) -> bool:
    """WS 연결 + 로그인 완료 여부."""
    # ConnectorManager가 있으면 우선 사용 (키움/LS 모두 지원)
    mgr = getattr(es, "_connector_manager", None)
    if mgr is not None:
        return bool(mgr.is_connected() and getattr(es, "_login_ok", False))
    # 하위 호환: 키움 단독
    ws = getattr(es, "_kiwoom_connector", None)
    login_ok = getattr(es, "_login_ok", False)
    return bool(ws and ws.is_connected() and login_ok)
