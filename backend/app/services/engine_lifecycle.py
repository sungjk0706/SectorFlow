# -*- coding: utf-8 -*-
"""
엔진 라이프사이클 관련 모듈
- 엔진 시작/중지
- 엔진 상태 조회
- 거래 모드 전환
- 업종 매수 실행
"""
import asyncio
from typing import Any, Coroutine
import logging
from datetime import datetime
from backend.app.core.trade_mode import is_test_mode
from backend.app.core.constants import _KST
from backend.app.services import engine_state

logger = logging.getLogger(__name__)


# ── 엔진 라이프사이클 ─────────────────────────────────────────────────

async def start_engine(user_id: str = "") -> bool:
    """엔진 시작."""

    if engine_state.state.engine_task and not engine_state.state.engine_task.done():
        return False

    engine_state.state.engine_user_id = user_id
    engine_state.state.running = True
    engine_state.state.engine_task = asyncio.create_task(_engine_loop())

    # ── 테스트모드: 거래내역 기반 포지션 구축 ──────────────────────────────────
    # 테스트모드는 증권사 서버가 없으므로 trades 테이블(SSOT)에서 포지션 구축.
    # 실전투자 모드는 증권사 서버가 SSOT이므로 별도 대조 불필요.
    if is_test_mode(engine_state.state.integrated_system_settings_cache):
        logger.info("[연산] 테스트모드 - 거래내역 기반 포지션 구축")
        from backend.app.services import dry_run
        await dry_run._refresh_positions_if_dirty()

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
        logger.info("[연산] 엔진 루프 완료")
    except Exception as e:
        logger.error("[연산] 엔진 루프 오류: %s", e, exc_info=True)


async def stop_engine() -> None:
    """엔진 중지."""
    from backend.app.services.engine_sector_confirm import (
        cancel_recompute_timer,
        cancel_all_dynamic_unreg_timers,
        _PENDING_REG_CODES,
    )

    engine_state.state.running = False

    if engine_state.state.engine_stop_event:
        engine_state.state.engine_stop_event.set()

    # 디바운스 타이머 정리
    cancel_recompute_timer()

    # 동적 구독 상태 정리 — 잔존 타이머/대기 세트가 신규 세션으로 누출되는 것 방지 (P22 데이터 정합성)
    cancel_all_dynamic_unreg_timers()
    _PENDING_REG_CODES.clear()

    if engine_state.state.engine_task:
        engine_state.state.engine_task.cancel()
        try:
            await engine_state.state.engine_task
        except asyncio.CancelledError:
            pass
        engine_state.state.engine_task = None

    # 백그라운드 작업 일괄 취소
    current = asyncio.current_task()
    all_tasks = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    bg_names = ("daily_time_scheduler",)
    bg_tasks = [t for t in all_tasks if any(n in (t.get_name() or "") for n in bg_names)]
    if bg_tasks:
        logger.info("[연산] 백그라운드 작업 %d개 취소 중...", len(bg_tasks))
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        logger.info("[연산] 백그라운드 작업 취소 완료")

    # 모든 루프·태스크 취소 완료 후 큐 잔류 데이터 제거 (원칙16 살아있는 경로, 원칙22 데이터 정합성)
    from backend.app.services.core_queues import clear_all_queues
    clear_all_queues()

    # 테스트모드 가상 잔고: 엔진 중지 시 초기화하지 않음
    # (포지션·예수금은 사용자가 직접 초기화할 때만 리셋)


def reset_broker_session_state() -> None:
    """broker 변경 시 이전 증권사 세션 상태를 완전히 초기화한다.

    stop_engine() 이후, start_engine() 이전에 호출된다.
    일반 엔진 중지 시에는 호출되지 않는다 (포지션 등 사용자 데이터 보존).

    원칙 10 (SSOT): 이전 증권사 데이터를 완전히 제거하여 새 증권사 데이터가 단일 진실 원천이 됨.
    원칙 17 (플래그 단일 소스): 모든 증권사 세션 플래그를 단일 함수에서 일괄 초기화.
    원칙 11 (이벤트 기반): Events를 clear하여 새 증권사 기동 시 대기 상태로 복원.
    """
    # 구독 상태 플래그
    engine_state.state.ws_account_subscribed = False
    engine_state.state.quote_subscribed = False
    engine_state.state.ws_connection_status = False
    engine_state.state.account_rest_bootstrapped = False
    engine_state.state.login_ok = False
    engine_state.state.access_token = None

    # 계좌 데이터 (이전 증권사 데이터 무효화)
    engine_state.state.account_snapshot = {}
    engine_state.state.broker_rest_totals = {"total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_rate": 0.0}
    engine_state.state.positions = []
    engine_state.state.auto_trade = None

    # Events (새 증권사 기동 시 재설정될 때까지 대기 상태로 복원)
    engine_state.state.data_ready_event.clear()
    engine_state.state.bootstrap_event.clear()
    engine_state.state.sector_summary_ready_event.clear()
    engine_state.state.ws_reg_pipeline_done.clear()

    # 동적 구독 상태 초기화 (원칙 10 SSOT, 원칙 17 플래그 단일 소스)
    # 1. master_stocks_cache에서 동적 구독 플래그 + 파생 데이터 제거
    for entry in engine_state.state.master_stocks_cache.values():
        entry.pop("_subscribed_dynamic", None)
        entry.pop("order_ratio", None)
        entry.pop("program_net_buy", None)
        entry.pop("_filtered", None)

    # 2. 구독 대기 세트 초기화 — 재기동 시 잔존 대기 종목 제거 (P10 SSOT)
    from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES
    _PENDING_REG_CODES.clear()

    # 2. sector_summary_cache 초기화 — are_buy_targets_changed가 True 반환 유도
    engine_state.state.sector_summary_cache = None

    # 3. 동적 구독 해지 타이머 일괄 취소
    from backend.app.services.engine_sector_confirm import cancel_all_dynamic_unreg_timers
    cancel_all_dynamic_unreg_timers()


def is_engine_running() -> bool:
    """엔진이 현재 가동 중인지 확인한다."""
    return engine_state.state.running and engine_state.state.engine_task is not None and not engine_state.state.engine_task.done()


def get_engine_status() -> dict:
    """엔진 상태 반환."""
    from backend.app.services.daily_time_scheduler import get_market_phase
    # 실시간 구독 종목 수
    sub_count = sum(1 for entry in engine_state.state.master_stocks_cache.values() if entry.get("_subscribed", False))

    test_mode = is_test_mode(engine_state.state.integrated_system_settings_cache)
    ws = engine_state.state.connector_manager or engine_state.state.active_connector
    conn_ok = bool(ws and ws.is_connected())

    # broker별 실제 연결 상태 (state.broker_tokens 기반)
    broker_statuses: dict = {}
    for broker_id, token in engine_state.state.broker_tokens.items():
        ws_connected = False
        if engine_state.state.connector_manager:
            conn = engine_state.state.connector_manager.get_connector(broker_id)
            ws_connected = bool(conn and conn.is_connected())
        elif broker_id == "kiwoom" and engine_state.state.active_connector:
            ws_connected = engine_state.state.active_connector.is_connected()
        broker_statuses[broker_id] = {
            "token_valid": bool(token),
            "ws_connected": ws_connected,
        }

    return {
        "running": engine_state.state.running,
        "connected": conn_ok,
        "broker_connected": conn_ok,  # 프론트 매핑용 (하위 호환)
        "logged_in": engine_state.state.login_ok,
        "login_ok": engine_state.state.login_ok,  # 프론트 매핑용
        "broker_token_valid": bool(engine_state.state.access_token),  # 하위 호환
        "trade_mode": "test" if test_mode else "real",
        "is_test_mode": test_mode,  # 프론트 매핑용
        "engine_task_alive": engine_state.state.engine_task is not None and not engine_state.state.engine_task.done(),
        "stock_subscribed_count": sub_count,
        "ws_reg_total_estimate": sub_count,
        "broker_statuses": broker_statuses,  # broker별 실제 연결 상태
        "market_phase": get_market_phase(),  # 장 상태 (P21 사용자 투명성)
    }


# ── 투자 모드 전환 ─────────────────────────────────────────────────

async def on_trade_mode_switched() -> None:
    """투자모드 전환 시 호출 — 엔진 재기동 없이 계좌 구독 상태만 전환한다."""
    from backend.app.services import settlement_engine
    from backend.app.services.engine_ws import _subscribe_account_realtime, _subscribe_positions_stocks_realtime
    from backend.app.services.engine_account import _refresh_account_snapshot_meta, _broadcast_account

    _new_test = is_test_mode(engine_state.state.integrated_system_settings_cache)
    _mode_str = "테스트모드" if _new_test else "실전투자"
    logger.info("[연산] 투자모드 전환 — %s (엔진 재기동 없음)", _mode_str)

    # BrokerRouter를 통해 현재 연결된 커넥터 확인 (증권사 하드코딩 제거)
    ws = engine_state.state.connector_manager or engine_state.state.active_connector
    if not is_engine_running() or not ws or not ws.is_connected():
        return

    if _new_test:
        # 실전→테스트: 계좌 실시간 구독(00/04) 해제, 분석용 구독은 유지
        from backend.app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp("10")
        logger.info("[구독] 테스트모드 전환 — 계좌 실시간 구독 해제 완료")
        # Settlement Engine: 상태 로드 (모드 전환 시 복원 목적) + 만료 항목 정리 + 타이머 재스케줄
        # load_state는 기동 시(로드)와 모드 전환 시(복원) 양쪽에 사용되는 dual-purpose 함수
        await settlement_engine.load_state()
        logger.info("[연산] 테스트모드 전환 — 정산 엔진 상태 복원 완료")
    else:
        # 테스트→실전: Settlement Engine 상태 저장 + 타이머 취소
        await settlement_engine.save_state()
        logger.info("[연산] 실전투자 전환 — 정산 엔진 상태 저장 완료")
        # 테스트→실전: 계좌 실시간 구독(00/04) + 보유종목 실시간(0B) 등록
        await _subscribe_account_realtime()
        await _subscribe_positions_stocks_realtime()
        logger.info("[구독] 실전투자 전환 — 계좌 + 보유종목 실시간 구독 완료")

    # 모드 전환 후 계좌 스냅샷 즉시 갱신
    await _refresh_account_snapshot_meta()
    await _broadcast_account(reason="trade_mode_switch")

    # 엔진 상태 브로드캐스트 (프론트엔드 헤더 테스트모드 표시 갱신)
    await broadcast_engine_status()


# ── 업종 매수 ─────────────────────────────────────────────────────
# evaluate_buy_candidates는 buy_order_executor.py로 이전됨


async def _apply_pending_settings_on_startup() -> None:
    """엔진 미실행 중 변경된 설정이 있으면 기동 시 반영."""
    from backend.app.core.sector_stock_cache import load_pending_settings, clear_pending_settings
    from backend.app.services.engine_service import apply_settings_change

    try:
        pending = await load_pending_settings()
        if not pending:
            return
        logger.info("[연산] 엔진 기동 시 보류 설정 변경 적용: %s", sorted(pending))
        await apply_settings_change(pending)
        await clear_pending_settings()
        logger.info("[연산] 보류 설정 변경 적용 완료")
    except Exception as e:
        logger.error("[연산] 보류 설정 변경 적용 실패: %s", e, exc_info=True)


# ── 헬퍼 함수 ─────────────────────────────────────────────────

def log_message(msg: str) -> None:
    """로그 출력."""
    logger.info(msg)


def get_current_kst_time() -> str:
    """현재 KST 시간 반환."""
    return datetime.now(_KST).strftime("%H:%M:%S")


def schedule_engine_task(coro: Coroutine[Any, Any, Any], *, context: str) -> bool:
    """
    엔진 이벤트 루프에 코루틴을 안전하게 스케줄한다.
    UI 스레드(이벤트 루프 없음)에서 호출되는 경우 call_soon_threadsafe를 사용한다.
    """
    loop = engine_state.state.engine_loop_ref
    if loop and not loop.is_closed():
        try:
            def _create_with_callback():
                task = loop.create_task(coro)
                task.add_done_callback(lambda t: logger.warning("[시스템] %s 작업 실패: %s", context, t.exception()) if t.exception() else None)
            loop.call_soon_threadsafe(_create_with_callback)
            return True
        except Exception as e:
            logger.warning("[시스템] %s 예약 실패: %s", context, e, exc_info=True)
            try:
                coro.close()
            except Exception:
                logger.warning("[시스템] 코루틴 정리 실패", exc_info=True)
            return False
    try:
        task = asyncio.get_running_loop().create_task(coro)
        task.add_done_callback(lambda t: logger.warning("[시스템] %s 작업 실패: %s", context, t.exception()) if t.exception() else None)
        return True
    except Exception as e:
        logger.warning("[시스템] %s 요청 실패: %s", context, e, exc_info=True)
        try:
            coro.close()
        except Exception:
            logger.warning("[시스템] 코루틴 정리 실패", exc_info=True)
        return False


def sync_sell_overrides() -> None:
    """sell_per_symbol -> AutoTradeManager.ts_overrides 동기화."""
    if not engine_state.state.auto_trade or not isinstance(engine_state.state.integrated_system_settings_cache, dict):
        return
    sp = engine_state.state.integrated_system_settings_cache["sell_per_symbol"]
    engine_state.state.auto_trade.ts_overrides = dict(sp) if isinstance(sp, dict) else {}


async def broadcast_engine_status() -> None:
    """엔진 상태 dict 를 WS 구독자에게 전달."""
    from backend.app.services.engine_account_notify import broadcast_engine_status_ws
    await broadcast_engine_status_ws(get_engine_status())





