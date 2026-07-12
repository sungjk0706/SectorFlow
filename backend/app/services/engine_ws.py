# -*- coding: utf-8 -*-
"""
WebSocket 구독 관련 모듈
- REG/UNREG/REMOVE 메시지 전송
- 실시간 구독 관리
- 증권사 메시지 핸들러
"""
import asyncio
import logging
from backend.app.services.engine_state import state

logger = logging.getLogger(__name__)


def _ws_live() -> bool:
    """WebSocket 연결 상태 확인."""
    ws = state.connector_manager or state.active_connector
    return bool(ws and ws.is_connected())


# ── REG/UNREG/REMOVE 전송 ─────────────────────────────────────────────────

async def _ws_send_reg_unreg_and_wait_ack(payload: dict, *, sender=None) -> tuple[bool, str]:
    """
    증권사 공식: REG/UNREG 1건 전송 후 응답(ACK, return_code 포함) 수신까지 대기한 뒤 다음 전송.
    Returns (True, return_code) if ACK 수신, (False, "") if 시간 초과(응답 없음).

    Args:
        payload: 전송할 REG/UNREG 페이로드.
        sender: 송신할 커넥터 (증권사 커넥터). None이면 state에서 자동 해결.
    """
    if state.reg_seq_lock is None:
        state.reg_seq_lock = asyncio.Lock()

    async with state.reg_seq_lock:
        if state.reg_ack_event:
            state.reg_ack_event.clear()
        state.reg_ack_return_code = ""

        _sender = sender if sender is not None else (
            state.connector_manager if state.connector_manager and state.connector_manager.is_connected() else state.active_connector
        )

        if not _sender or not _sender.is_connected():
            return False, ""

        sent = await _sender.send_message(payload)
        if not sent:
            return False, ""

        try:
            if state.reg_ack_event:
                await asyncio.wait_for(state.reg_ack_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            if state.reg_ack_event:
                state.reg_ack_event.clear()
            logger.warning("[구독] 구독 응답 대기 시간 초과(10초) — 메시지유형=%s", payload.get("trnm"))
            return False, ""

        rc = state.reg_ack_return_code
        await asyncio.sleep(state.REG_POST_ACK_GAP_SEC)
        return True, rc




async def _ws_send_remove_fire_and_forget(payload: dict, *, sender=None) -> bool:
    """REMOVE 페이로드를 ACK 대기 없이 즉시 전송한다.

    _reg_seq_lock을 획득하지 않으므로 서버 측 90초 지연 응답이
    REG/UNREG ACK 대기를 막지 않는다.
    다음 REG의 refresh='0'이 서버 구독 상태를 덮어쓰므로 ACK 불필요.

    Args:
        payload: 전송할 REMOVE 페이로드.
        sender: 송신할 커넥터 (증권사 커넥터). None이면 state에서 자동 해결.
    """
    _sender = sender if sender is not None else (
        state.connector_manager if state.connector_manager and state.connector_manager.is_connected() else state.active_connector
    )

    if not _sender or not _sender.is_connected():
        return False

    sent = await _sender.send_message(payload)
    if not sent:
        logger.warning("[구독] 구독해지 전송 실패 (그룹=%s)", payload.get("grp_no"))
    return sent


# ── 증권사 메시지 핸들러 ─────────────────────────────────────────────────

async def _broker_message_handler(payload: dict) -> None:
    """증권사 커넥터에서 호출되는 핸들러.

    _BrokerSocket._recv_loop → _on_ws_message(async) → 이 함수(async).
    create_task 없이 await 직접 호출 — 순서 보장, 작업 폭발 없음.
    """
    if not isinstance(payload, dict):
        return
    trnm = payload.get("trnm", "")
    if trnm in ("LOGIN", "REG", "UNREG", "REMOVE", "JIF"):
        await _handle_ws_data(payload)


async def _handle_ws_data(data: dict) -> None:
    """WebSocket `data` 페이로드 처리 — 본문은 `engine_ws_dispatch`에 위임."""
    from backend.app.services import engine_ws_dispatch
    await engine_ws_dispatch.handle_ws_data(data)


# ── 실시간 구독 ─────────────────────────────────────────────────────────

async def _subscribe_stock_realtime_when_ready(stk_cd: str) -> None:
    """
    모니터링 등록 시점이 LOGIN 이전이면 REG가 무력화될 수 있어,
    실시간 통신 연결·로그인 성공 후 REG를 보내도록 짧게 재시도한다.
    기동 시 배치 파이프라인(_run_sector_reg_pipeline) 완료 전에는
    단건 REG를 보내지 않음 — 배치가 이미 커버하므로 중복 블로킹 방지.
    시장가 운용으로 호가(02) REG 제거됨 — 0B는 배치에서 커버.
    """
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    
    stk_cd = str(stk_cd).strip()
    if not stk_cd:
        return
    
    # 배치 파이프라인 완료 대기 (이벤트 구동 - 시간 초과 제거)
    if state.ws_reg_pipeline_done:
        await state.ws_reg_pipeline_done.wait()

    # 배치에서 이미 구독됐으면 단건 불필요 (0B 기준)
    item_cd = _base_stk_cd(stk_cd)
    if state.master_stocks_cache.get(item_cd, {}).get("_subscribed"):
        return

    # 배치에 포함되지 않은 신규 모니터링 종목 — 단건 0B REG 전송
    ws = state.connector_manager or state.active_connector
    if not ws or not ws.is_connected():
        return

    if item_cd in state.master_stocks_cache:
        state.master_stocks_cache[item_cd]["_subscribed"] = True

    ok = await ws.subscribe_stocks([item_cd])
    if ok:
        pass
    else:
        if item_cd in state.master_stocks_cache:
            state.master_stocks_cache[item_cd].pop("_subscribed", None)
        logger.warning("[구독] 단건 종목 구독 실패 — %s", item_cd)


async def _subscribe_account_realtime() -> None:
    """계좌 실시간 구독(주문체결·잔고) — engine_ws_reg 모듈로 위임."""
    from backend.app.services import engine_ws_reg
    await engine_ws_reg.subscribe_account_realtime()


def _log_reg_stock_chunk(scope: str, start_ord: int, end_ord: int, ca: int, cs: int, cf: int) -> None:
    logger.info(
        "[구독] %s %d~%d번 처리 완료 — 성공 %d건, 이미 구독 생략 %d건, 실패 %d건",
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
    await engine_ws_reg.subscribe_positions_stocks_realtime()
    # REG 실행 후 인메모리 상태 동기화
    if any(entry.get("_subscribed", False) for entry in state.master_stocks_cache.values()):
        ws_subscribe_control._set_status(quote=True)


async def _subscribe_sector_stocks_0b() -> None:
    """필터 통과 종목 + 보유종목 0B REG — engine_ws_reg 모듈로 위임.

    REG 성공 후 ws_subscribe_control 상태를 동기화하여
    프론트엔드 구독 표시가 실제 상태와 일치하도록 한다.
    """
    from backend.app.services import engine_ws_reg, ws_subscribe_control
    await engine_ws_reg.subscribe_sector_stocks_0b()
    # REG 실행 후 인메모리 상태 동기화 → 실시간 통신 전송
    ws_subscribe_control._set_status(quote=True)


async def _ensure_ws_subscriptions_for_positions() -> None:
    """로그인 직후 계좌 실시간 구독 + 보유종목 시세 구독을 하는 함수.

    테스트모드: 계좌 구독(00/04) 생략, 보유종목 시세(0B)만 구독.
    실전투자: 계좌 구독 + 보유종목 시세 모두 구독.
    """
    from backend.app.core.trade_mode import is_test_mode
    from backend.app.services.engine_account import _refresh_account_snapshot_meta

    try:
        ws = state.connector_manager or state.active_connector
        if not ws or not ws.is_connected() or not state.login_ok:
            return
        if not is_test_mode(state.integrated_system_settings_cache):
            await _subscribe_account_realtime()
        else:
            logger.info("[구독] 테스트모드 — 계좌 실시간 구독 생략")
        await _subscribe_positions_stocks_realtime()
    except Exception as e:
        logger.warning("[구독] 실시간 구독 전송 실패: %s", e, exc_info=True)
    finally:
        if _ws_live():
            await _refresh_account_snapshot_meta()


async def _run_sector_reg_pipeline() -> None:
    """실시간 구독 파이프라인 실행."""
    try:
        ws = state.connector_manager or state.active_connector
        if not ws or not ws.is_connected() or not state.login_ok:
            return
        # 구독 제어 모듈에 위임 (설정 기반 조건부 REG)
        from backend.app.services import ws_subscribe_control
        await ws_subscribe_control.run_conditional_reg_pipeline()
    except Exception as e:
        logger.warning("[연산] 실시간 구독 파이프라인 실패: %s", e, exc_info=True)
    finally:
        if state.ws_reg_pipeline_done:
            state.ws_reg_pipeline_done.set()
        logger.info("[연산] 실시간 구독 준비 완료 — 단건 구독 허용")
        from backend.app.services.engine_account import _refresh_account_snapshot_meta
        if _ws_live():
            await _refresh_account_snapshot_meta()


async def _cleanup_stale_ws_subscriptions_on_session_ready() -> None:
    """로그인 직후 1회: 잔존 구독 정리 (grp_no=5,2,4 UNREG 최선 노력)."""
    ws = state.connector_manager or state.active_connector
    if not ws or not ws.is_connected():
        return

    from backend.app.services import ws_subscribe_control
    await ws_subscribe_control.cleanup_stale_subscriptions()


async def subscribe_dynamic_data(codes: list[str]) -> None:
    """동적 데이터(0D, PGM, UH1, UPH 등) 실시간 구독 등록을 커넥터에 위임합니다."""
    from backend.app.services.engine_state import state
    ws = state.connector_manager or state.active_connector
    logger.info("[구독] 호가·프로그램매매 구독 시작 — 종목: %s", codes)
    if not ws or not ws.is_connected() or not state.login_ok:
        logger.warning("[구독] 호가·프로그램매매 구독 실패 — 연결=%s, 로그인=%s", ws.is_connected() if ws else False, state.login_ok)
        return
    if hasattr(ws, "subscribe_dynamic"):
        await ws.subscribe_dynamic(codes)


async def unsubscribe_dynamic_data(codes: list[str]) -> None:
    """동적 데이터 실시간 구독 해지를 커넥터에 위임합니다."""
    from backend.app.services.engine_state import state
    ws = state.connector_manager or state.active_connector
    if not ws or not ws.is_connected() or not state.login_ok:
        return
    if hasattr(ws, "unsubscribe_dynamic"):
        await ws.unsubscribe_dynamic(codes)
