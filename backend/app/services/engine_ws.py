# -*- coding: utf-8 -*-
"""
WebSocket 구독 관련 모듈
- REG/UNREG/REMOVE 메시지 전송
- 실시간 구독 관리
- 브로커 메시지 핸들러
"""
import asyncio
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import (
    _connector_manager,
    _kiwoom_connector,
    _reg_seq_lock,
    _reg_ack_return_code,
    _reg_ack_event,
    _REG_POST_ACK_GAP_SEC,
    _ws_reg_pipeline_done,
    _subscribed_stocks,
    _settings_cache,
    _login_ok,
    _refresh_account_snapshot_meta,
    _account_rest_bootstrapped,
    _pending_stock_details,
)

logger = get_logger("engine_ws")


def _ws_live() -> bool:
    """WebSocket 연결 상태 확인."""
    return bool(_connector_manager or _kiwoom_connector)


# ── REG/UNREG/REMOVE 전송 ─────────────────────────────────────────────────

async def _ws_send_reg_unreg_and_wait_ack(payload: dict) -> tuple[bool, str]:
    """
    브로커 공식: REG/UNREG 1건 전송 후 응답(ACK, return_code 포함) 수신까지 대기한 뒤 다음 전송.
    Returns (True, return_code) if ACK 수신, (False, "") if 타임아웃(응답 없음).
    """
    global _reg_seq_lock, _reg_ack_return_code
    if _reg_seq_lock is None:
        _reg_seq_lock = asyncio.Lock()
    
    async with _reg_seq_lock:
        if _reg_ack_event:
            _reg_ack_event.clear()
        _reg_ack_return_code = ""
        
        _sender = _connector_manager if _connector_manager and _connector_manager.is_connected() else _kiwoom_connector
        
        if not _sender or not _sender.is_connected():
            return False, ""
        
        sent = await _sender.send_message(payload)
        if not sent:
            await asyncio.sleep(_REG_POST_ACK_GAP_SEC)
            return False, ""
        
        try:
            if _reg_ack_event:
                await asyncio.wait_for(_reg_ack_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            if _reg_ack_event:
                _reg_ack_event.clear()
            logger.warning(
                "[연결] 구독 응답 대기 시간 초과(10s) -- trnm=%s",
                payload.get("trnm"),
            )
            await asyncio.sleep(_REG_POST_ACK_GAP_SEC)
            return False, ""
        
        rc = _reg_ack_return_code
        await asyncio.sleep(_REG_POST_ACK_GAP_SEC)
        return True, rc




async def _ws_send_remove_fire_and_forget(payload: dict) -> bool:
    """REMOVE 페이로드를 ACK 대기 없이 즉시 전송한다.

    _reg_seq_lock을 획득하지 않으므로 서버 측 90초 지연 응답이
    REG/UNREG ACK 대기를 막지 않는다.
    다음 REG의 refresh='0'이 서버 구독 상태를 덮어쓰므로 ACK 불필요.
    """
    _sender = _connector_manager if _connector_manager and _connector_manager.is_connected() else _kiwoom_connector
    
    if not _sender or not _sender.is_connected():
        return False
    
    sent = await _sender.send_message(payload)
    if not sent:
        logger.warning("[연결] 구독해지 전송 실패 grp_no=%s", payload.get("grp_no"))
    return sent


# ── 브로커 메시지 핸들러 ─────────────────────────────────────────────────

async def _broker_message_handler(payload: dict) -> None:
    """BrokerConnector에서 호출되는 핸들러.

    _BrokerSocket._recv_loop → _on_ws_message(async) → 이 함수(async).
    create_task 없이 await 직접 호출 — 순서 보장, 태스크 폭발 없음.
    """
    if not isinstance(payload, dict):
        return
    trnm = payload.get("trnm", "")
    if trnm in ("REAL", "LOGIN", "REG", "UNREG", "REMOVE"):
        await _handle_ws_data(payload)


async def _handle_ws_data(data: dict) -> None:
    """WebSocket `data` 페이로드 처리 -- 본문은 `engine_ws_dispatch`에 위임."""
    from backend.app.services import engine_ws_dispatch
    await engine_ws_dispatch.handle_ws_data(data)


# ── 실시간 구독 ─────────────────────────────────────────────────────────

async def _subscribe_stock_realtime_when_ready(stk_cd: str) -> None:
    """
    모니터링 등록 시점이 LOGIN 이전이면 REG가 무력화될 수 있어,
    WS 연결·로그인 성공 후 REG를 보내도록 짧게 재시도한다.
    기동 시 배치 파이프라인(_run_sector_reg_pipeline) 완료 전에는
    단건 REG를 보내지 않음 -- 배치가 이미 커버하므로 중복 블로킹 방지.
    시장가 운용으로 호가(02) REG 제거됨 -- 0B는 배치에서 커버.
    """
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd, get_ws_subscribe_code
    
    stk_cd = str(stk_cd).strip().lstrip("A")
    if not stk_cd:
        return
    
    # 배치 파이프라인 완료 대기 (이벤트 구동 - 타임아웃 제거)
    if _ws_reg_pipeline_done:
        await _ws_reg_pipeline_done.wait()
    
    # 배치에서 이미 구독됐으면 단건 불필요 (0B 기준)
    item_cd = _format_broker_reg_stk_cd(stk_cd)
    if item_cd in _subscribed_stocks:
        logger.debug("[데이터] 단건 REG 생략(배치 완료) -- %s", item_cd)
        return
    
    # 배치에 포함되지 않은 신규 모니터링 종목 — 단건 0B REG 전송
    if not _ws_live():
        logger.debug("[데이터] 단건 REG 생략 — WS 미연결/미로그인 %s", item_cd)
        return
    
    from backend.app.services.engine_ws_reg import build_0b_reg_payloads
    ws_code = get_ws_subscribe_code(item_cd)
    payloads = build_0b_reg_payloads([ws_code], reset_first=False)
    if payloads:
        ok, rc = await _ws_send_reg_unreg_and_wait_ack(payloads[0])
        if ok:
            _subscribed_stocks.add(item_cd)
            logger.debug("[데이터] 단건 0B REG 완료 -- %s (return_code=%s)", item_cd, rc)
        else:
            logger.warning("[데이터] 단건 0B REG 실패 -- %s", item_cd)


async def _subscribe_account_realtime() -> None:
    """계좌 실시간 구독(주문체결·잔고) — engine_ws_reg 모듈로 위임."""
    from backend.app.services import engine_ws_reg
    await engine_ws_reg.subscribe_account_realtime(None)


def _log_reg_stock_chunk(scope: str, start_ord: int, end_ord: int, ca: int, cs: int, cf: int) -> None:
    logger.info(
        "[구독등록] %s %d~%d번 처리 완료 -- 서버 응답 성공 %d건, 이미구독 생략 %d건, 실패·미전송 %d건",
        scope,
        start_ord,
        end_ord,
        ca,
        cs,
        cf,
    )


async def _subscribe_positions_stocks_realtime() -> None:
    """보유 종목 0B REG — engine_ws_reg 모듈로 위임."""
    from backend.app.services import engine_ws_reg, ws_subscribe_control
    await engine_ws_reg.subscribe_positions_stocks_realtime(None)
    # REG 실행 후 인메모리 상태 동기화
    if _subscribed_stocks:
        ws_subscribe_control._set_status(quote=True)


async def _subscribe_radar_stocks_realtime() -> None:
    """
    레이더 종목 REG -- 시장가 운용으로 호가(02) 불필요, 제거됨.
    0B는 _subscribe_sector_stocks_0b 에서 이미 커버됨.
    """
    pass


async def _subscribe_all_tracked_stocks_realtime() -> None:
    """보유 + 레이더 -- 조건 전환 등 전체 재동기화 시에만."""
    await _subscribe_positions_stocks_realtime()
    await _subscribe_radar_stocks_realtime()


async def _subscribe_sector_stocks_0b() -> None:
    """필터 통과 종목 + 보유종목 0B REG — engine_ws_reg 모듈로 위임.

    REG 성공 후 ws_subscribe_control 상태를 동기화하여
    프론트엔드 구독 표시가 실제 상태와 일치하도록 한다.
    """
    from backend.app.services import engine_ws_reg, ws_subscribe_control
    await engine_ws_reg.subscribe_sector_stocks_0b(None)
    # REG 실행 후 인메모리 상태 동기화 → WS 브로드캐스트
    ws_subscribe_control._set_status(quote=True)


async def _ensure_ws_subscriptions_for_positions() -> None:
    """로그인 직후 계좌 실시간 구독 + 보유종목 시세 구독을 하는 함수.

    테스트모드: 계좌 구독(00/04) 스킵, 보유종목 시세(0B)만 구독.
    실전투자: 계좌 구독 + 보유종목 시세 모두 구독.
    """
    from backend.app.core.trade_mode import is_test_mode
    from backend.app.services.engine_account_notify import _refresh_account_snapshot_meta
    
    try:
        if not _kiwoom_connector or not _kiwoom_connector.is_connected() or not _login_ok:
            return
        if not is_test_mode(_settings_cache):
            await _subscribe_account_realtime()
        else:
            logger.info("[구독] 테스트모드 -- 계좌 실시간 구독(00/04) 생략")
        await _subscribe_positions_stocks_realtime()
    except Exception as e:
        logger.warning("[연결] 실시간 구독 전송 실패함: %s", e, exc_info=True)
    finally:
        if _ws_live():
            await _refresh_account_snapshot_meta()


async def _run_sector_reg_pipeline() -> None:
    """실시간 구독 파이프라인 실행."""
    try:
        if not _kiwoom_connector or not _kiwoom_connector.is_connected() or not _login_ok:
            return
        # 구독 제어 모듈에 위임 (설정 기반 조건부 REG)
        from backend.app.services import ws_subscribe_control
        await ws_subscribe_control.run_conditional_reg_pipeline(None)
    except Exception as e:
        logger.warning("[시작] 실시간 구독 파이프라인 실패: %s", e, exc_info=True)
    finally:
        if _ws_reg_pipeline_done:
            _ws_reg_pipeline_done.set()
        logger.info("[시작] 실시간 구독 준비 완료 -- 단건 구독 허용")
        if _ws_live() and _refresh_account_snapshot_meta:
            await _refresh_account_snapshot_meta()


async def _cleanup_stale_ws_subscriptions_on_session_ready() -> None:
    """로그인 직후 1회: 잔존 구독 정리 + 비보유 종목 UNREG 스윕."""
    if not _kiwoom_connector or not _kiwoom_connector.is_connected():
        return
    
    # 잔존 구독 정리 (grp_no=5,2,4 UNREG best-effort)
    from backend.app.services import ws_subscribe_control
    await ws_subscribe_control.cleanup_stale_subscriptions(None)

    if _account_rest_bootstrapped:
        await _sweep_unreg_subscribed_except_positions_and_tracked()


def _item_cd_is_position(item_cd: str, pos_keep: set[str]) -> bool:
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd
    for p in pos_keep:
        if _format_broker_reg_stk_cd(p) == item_cd:
            return True
    return False


def _item_cd_tracked_radar_or_ready(item_cd: str) -> bool:
    """
    모니터링 pending에 올라간 종목 -- 비보유여도 실시간(REG) 유지해야 HTS와 시세가 맞는다.
    잔고 REST 반영 후 UNREG 스윕 등에서 UNREG 대상에서 제외한다.
    """
    from backend.app.services.engine_symbol_utils import _normalize_stk_cd_rest
    
    nk = _normalize_stk_cd_rest(str(item_cd).strip().lstrip("A"))
    if not nk or nk == "000000":
        return False
    for k in _pending_stock_details.keys():
        if _normalize_stk_cd_rest(str(k).strip().lstrip("A")) == nk:
            return True
    return False


async def _sweep_unreg_subscribed_except_positions_and_tracked() -> int:
    """비보유·비추적 종목 정리 -- 시장가 운용으로 호가(02) 제거됨, 현재 no-op."""
    return 0
