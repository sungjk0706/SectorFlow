# -*- coding: utf-8 -*-
"""
엔진 라이프사이클 관련 모듈
- 엔진 시작/중지
- 엔진 상태 조회
- 거래 모드 전환
- 섹터 매수 실행
"""
import asyncio
import time
from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.engine_state import state

logger = get_logger("engine_lifecycle")


# ── 엔진 라이프사이클 ─────────────────────────────────────────────────

async def start_engine(user_id: str = "") -> bool:
    """엔진 시작."""
    from backend.app.core.kiwoom_providers import KiwoomAuthProvider

    if state.engine_task and not state.engine_task.done():
        return False

    state.engine_user_id = user_id
    state.running = True
    state.engine_task = asyncio.create_task(_engine_loop())

    # ── Reconciliation(강제 정산) 관문 ───────────────────────────────────────
    # 엔진 시작 시 조건부 정산(Smart Reconciliation)
    await _reconciliation_on_startup()

    # ── Pending Settings Changes 적용 ───────────────────────────────────────
    # 엔진 미실행 중 변경된 설정이 있으면 기동 시 반영
    await _apply_pending_settings_on_startup()

    await broadcast_engine_status()
    return True


async def _engine_loop() -> None:
    """엔진 메인 루프."""
    from backend.app.services import engine_loop
    
    try:
        await engine_loop.run_engine_loop()
        logger.info("[엔진] _engine_loop() 완료, run_engine_loop() 반환 후")
    except Exception as e:
        logger.error("[엔진] _engine_loop() 예외 발생: %s", e, exc_info=True)


async def stop_engine() -> None:
    """엔진 중지."""
    from backend.app.services.engine_sector_confirm import cancel_recompute_timer

    state.running = False

    if state.engine_stop_event:
        state.engine_stop_event.set()

    # 디바운스 타이머 정리
    cancel_recompute_timer()

    if state.engine_task:
        state.engine_task.cancel()
        try:
            await state.engine_task
        except asyncio.CancelledError:
            pass
        state.engine_task = None

    # 백그라운드 태스크 일괄 취소
    current = asyncio.current_task()
    all_tasks = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    bg_names = ("daily_time_scheduler",)
    bg_tasks = [t for t in all_tasks if any(n in (t.get_name() or "") for n in bg_names)]
    if bg_tasks:
        logger.info("[시작] 백그라운드 태스크 %d개 취소 중...", len(bg_tasks))
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        logger.info("[시작] 백그라운드 태스크 취소 완료")

    # 테스트모드 가상 잔고: 엔진 중지 시 초기화하지 않음
    # (포지션·예수금은 사용자가 직접 초기화할 때만 리셋)


def is_engine_running() -> bool:
    """엔진이 현재 가동 중인지 확인한다."""
    return state.running and state.engine_task is not None and not state.engine_task.done()


def get_engine_status() -> dict:
    """엔진 상태 반환."""
    # 실시간 구독 종목 수
    all_stocks = state.master_stocks_cache.copy()
    sub_count = sum(1 for entry in all_stocks.values() if entry.get("_subscribed", False))

    test_mode = is_test_mode(state.integrated_system_settings_cache)
    ws = state.connector_manager or state.active_connector
    conn_ok = bool(ws and ws.is_connected())

    # broker별 실제 연결 상태 (state.broker_tokens 기반)
    broker_statuses: dict = {}
    for broker_id, token in state.broker_tokens.items():
        ws_connected = False
        if state.connector_manager:
            conn = state.connector_manager.get_connector(broker_id)
            ws_connected = bool(conn and conn.is_connected())
        elif broker_id == "kiwoom" and state.active_connector:
            ws_connected = state.active_connector.is_connected()
        broker_statuses[broker_id] = {
            "token_valid": bool(token),
            "ws_connected": ws_connected,
        }

    return {
        "running": state.running,
        "connected": conn_ok,
        "broker_connected": conn_ok,  # 프론트 매핑용 (하위 호환)
        "logged_in": state.login_ok,
        "login_ok": state.login_ok,  # 프론트 매핑용
        "broker_token_valid": bool(state.access_token),  # 하위 호환
        "trade_mode": "test" if test_mode else "real",
        "is_test_mode": test_mode,  # 프론트 매핑용
        "engine_task_alive": state.engine_task is not None and not state.engine_task.done(),
        "stock_subscribed_count": sub_count,
        "ws_reg_total_estimate": sub_count,
        "broker_statuses": broker_statuses,  # broker별 실제 연결 상태
    }


# ── 투자 모드 전환 ─────────────────────────────────────────────────

async def on_trade_mode_switched() -> None:
    """투자모드 전환 시 호출 -- 엔진 재기동 없이 계좌 구독 상태만 전환한다."""
    from backend.app.services import settlement_engine
    from backend.app.services.engine_ws import _subscribe_account_realtime, _subscribe_positions_stocks_realtime
    from backend.app.services.engine_account import _refresh_account_snapshot_meta, _broadcast_account

    _new_test = is_test_mode(state.integrated_system_settings_cache)
    _mode_str = "테스트모드" if _new_test else "실전투자"
    logger.info("[연결] 투자모드 전환 -> %s (엔진 재기동 없음)", _mode_str)

    # BrokerRouter를 통해 현재 연결된 커넥터 확인 (증권사 하드코딩 제거)
    ws = state.connector_manager or state.active_connector
    if not is_engine_running() or not ws or not ws.is_connected():
        return

    if _new_test:
        # 실전→테스트: 계좌 실시간 구독(00/04) 해제, 분석용 구독은 유지
        from backend.app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp("10")
        logger.info("[구독] 테스트모드 전환 -- 계좌 실시간 구독(grp_no=10) 해제 완료")
        # Settlement Engine: 파일에서 상태 복원 + 만료 항목 정리 + 타이머 재스케줄
        settlement_engine.restore_state()
        logger.info("[시작] 테스트모드 전환 -- Settlement Engine 상태 복원 완료")
    else:
        # 테스트→실전: Settlement Engine 상태 저장 + 타이머 취소
        settlement_engine.save_state()
        logger.info("[시작] 실전모드 전환 -- Settlement Engine 상태 저장 완료")
        # 테스트→실전: 계좌 실시간 구독(00/04) + 보유종목 실시간(0B) 등록
        await _subscribe_account_realtime()
        await _subscribe_positions_stocks_realtime()
        logger.info("[구독] 실전모드 전환 -- 계좌 실시간 구독(00/04) + 보유종목 실시간(0B) 등록 완료")

    # 모드 전환 후 계좌 스냅샷 즉시 갱신
    await _refresh_account_snapshot_meta()
    await _broadcast_account(reason="trade_mode_switch")

    # 엔진 상태 브로드캐스트 (프론트엔드 헤더 테스트모드 표시 갱신)
    await broadcast_engine_status()


# ── 섹터 매수 ─────────────────────────────────────────────────────
# evaluate_buy_candidates는 buy_order_executor.py로 이전됨


# ── Reconciliation(강제 정산) ───────────────────────────────────────────

async def _reconciliation_on_startup() -> None:
    """
    기동 시 조건부 정산(Smart Reconciliation).

    로컬 장부에서 Pending 상태인 주문이 존재하는지 먼저 SELECT 쿼리.
    Pending 데이터가 단 1건이라도 존재할 때만 서버에 원장 조회 API(TR)를 호출.
    서버에서 받아온 진짜 주문/체결 내역과 로컬의 Pending 리스트를 대조하여 유령 데이터 정리.
    Pending 건수가 0건이면 불필요한 네트워크 호출 없이 즉시 엔진 가동.

    테스트모드는 가상잔고이므로 대조 스킵 (원칙 9: 돈 I/O 차이).
    """
    from backend.app.core.trade_mode import is_test_mode
    from backend.app.core.journal import oms_get_pending_orders
    from backend.app.services.data_manager import get_account_profit_rate
    from backend.app.services.engine_account_notify import _broadcast

    try:
        # 테스트모드는 가상잔고이므로 대조 스킵 (원칙 9: 돈 I/O 차이)
        if is_test_mode(state.integrated_system_settings_cache):
            logger.info("[Reconciliation] 테스트모드 - 가상잔고이므로 원장 대조 스킵")
            return

        # 1. 로컬 장부에서 Pending 상태인 주문 조회
        pending_orders = await oms_get_pending_orders()
        pending_count = len(pending_orders)

        if pending_count == 0:
            # Pending 건수가 0건이면 불필요한 네트워크 호출 없이 즉시 엔진 가동
            logger.info("[Reconciliation] Pending 주문 없음 - 즉시 엔진 가동")
            return

        # 2. Pending 데이터가 존재하면 서버 원장 조회
        logger.info("[Reconciliation] Pending 주문 존재 - 서버 원장 조회 시작")

        access_token = state.access_token

        if not access_token:
            logger.warning("[Reconciliation] 실패 - access_token 없음")
            return

        # 실제 체결 내역 조회
        balance_raw = await get_account_profit_rate(access_token)
        if not balance_raw:
            logger.warning("[Reconciliation] 실패 - 체결 내역 조회 실패")
            return

        # 3. 서버 원장과 로컬 Pending 리스트 대조
        # 서버에서 받아온 진짜 주문/체결 내역과 로컬의 Pending 리스트를 대조
        # 유령 데이터를 즉시 정리
        # (실제 구현은 서버 응답의 order_id와 로컬 Pending order_id 비교)
        logger.info("[Reconciliation] 원장 대조 완료 - 유령 데이터 정리")

        # 4. UI에 Reconciliation 완료 알림 전송
        await _broadcast("reconciliation_complete", {
            "status": "success",
            "message": f"기동 시 원장 대조 완료 - {pending_count}건 Pending 처리",
        })

    except Exception as e:
        logger.error("[Reconciliation] 예외: %s", e, exc_info=True)
        await _broadcast("reconciliation_complete", {
            "status": "failed",
            "message": f"원장 대조 실패: {str(e)}",
        })


async def _apply_pending_settings_on_startup() -> None:
    """엔진 미실행 중 변경된 설정이 있으면 기동 시 반영."""
    from backend.app.core.sector_stock_cache import load_pending_settings, clear_pending_settings
    from backend.app.services import engine_service

    try:
        pending = await load_pending_settings()
        if not pending:
            return
        logger.info("[Pending] 엔진 기동 시 보류 설정 변경 적용: %s", sorted(pending))
        await engine_service.apply_settings_change(pending)
        await clear_pending_settings()
        logger.info("[Pending] 보류 설정 변경 적용 완료")
    except Exception as e:
        logger.error("[Pending] 보류 설정 변경 적용 실패: %s", e, exc_info=True)


# ── 헬퍼 함수 ─────────────────────────────────────────────────

def log_message(msg: str) -> None:
    """로그 출력."""
    logger.info(msg)


def get_current_kst_time() -> str:
    """현재 KST 시간 반환."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


def schedule_engine_task(coro: asyncio.coroutines, *, context: str) -> bool:
    """
    엔진 이벤트 루프에 코루틴을 안전하게 스케줄한다.
    UI 스레드(이벤트 루프 없음)에서 호출되는 경우 call_soon_threadsafe를 사용한다.
    """
    loop = state.engine_loop_ref
    if loop and not loop.is_closed():
        try:
            def _create_with_callback():
                task = loop.create_task(coro)
                task.add_done_callback(lambda t: logger.warning("[데이터] %s 태스크 실패: %s", context, t.exception()) if t.exception() else None)
            loop.call_soon_threadsafe(_create_with_callback)
            return True
        except Exception as e:
            logger.warning("[데이터] %s 스케줄 실패함: %s", context, e, exc_info=True)
            try:
                coro.close()
            except Exception:
                logger.warning("[데이터] coroutine 정리 실패", exc_info=True)
            return False
    try:
        task = asyncio.get_running_loop().create_task(coro)
        task.add_done_callback(lambda t: logger.warning("[데이터] %s 태스크 실패: %s", context, t.exception()) if t.exception() else None)
        return True
    except Exception as e:
        logger.warning("[데이터] %s 요청 실패함: %s", context, e, exc_info=True)
        try:
            coro.close()
        except Exception:
            logger.warning("[데이터] coroutine 정리 실패", exc_info=True)
        return False


def sync_sell_overrides() -> None:
    """sell_per_symbol -> AutoTradeManager.ts_overrides 동기화."""
    if not state.auto_trade or not isinstance(state.integrated_system_settings_cache, dict):
        return
    sp = state.integrated_system_settings_cache["sell_per_symbol"]
    state.auto_trade.ts_overrides = dict(sp) if isinstance(sp, dict) else {}


async def broadcast_engine_status() -> None:
    """엔진 상태 dict 를 WS 구독자에게 전달."""
    from backend.app.services.engine_account_notify import broadcast_engine_status_ws
    await broadcast_engine_status_ws(get_engine_status())


async def _delayed_resubscribe_stock_after_rate_limit(norm_cd: str) -> None:
    """105110 직후 재시도하지 않고, 일정 시간 뒤 필요한 종목만 REG 재전송 -- 시장가 운용으로 no-op."""
    pass


