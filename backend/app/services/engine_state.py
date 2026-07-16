# -*- coding: utf-8 -*-
"""
엔진 전역 상태 저장소.

모든 engine_*.py 모듈은 이 파일에서 전역 상태를 직접 import한다.
순환 import 방지: 이 모듈은 다른 engine_*.py를 import하지 않는다.
"""
import asyncio
from typing import Any, TYPE_CHECKING
from backend.app.core.broker_connector import BrokerConnector
from backend.app.services.trading import AutoTradeManager
from backend.app.services.engine_utils import LazyEvent

if TYPE_CHECKING:
    from backend.app.core.connector_manager import ConnectorManager
    from backend.app.core.broker_providers import AuthProvider
    from backend.app.domain.models import SectorSummary


class EngineState:
    """엔진 전역 상태를 관리하는 싱글톤 클래스."""
    
    def __init__(self):
        # ── 엔진 상태 ───────────────────────────────────────────────────────────
        self.running = False
        self.shutdown_requested: bool = False
        self.connector_manager: "ConnectorManager | None" = None  # type: ignore[name-defined]
        self.active_connector: BrokerConnector | None = None
        self.active_auth_provider: "AuthProvider | None" = None  # type: ignore[name-defined]
        self.broker_tokens: dict[str, str] = {}  # {broker_id: access_token}
        self.engine_task: asyncio.Task | None = None
        self.engine_loop_ref: asyncio.AbstractEventLoop | None = None
        self.access_token: str | None = None
        self.login_ok = False
        self.engine_user_id: str = ""
        self.last_ws_limit_warn_ts: float = 0.0
        self.realtime_latency_exceeded: bool = False
        self.avg_amt_needs_bg_refresh: bool = False
        self.refresh_account_snapshot_meta = None
        self.update_account_memory = None

        # ── Locks & Events ───────────────────────────────────────────────────────
        self.data_ready_event: LazyEvent = LazyEvent()
        self.token_ready_event: LazyEvent = LazyEvent()
        self.ws_reg_pipeline_done = LazyEvent()
        self.bootstrap_event = LazyEvent()
        self.sector_summary_ready_event = LazyEvent()
        self.engine_ready_event = LazyEvent()
        self.server_ready_event = LazyEvent()
        self.preboot_cache_loaded: bool = False
        self.preboot_ready_event = LazyEvent()
        self.engine_stop_event = LazyEvent()
        self.ws_window_changed_event = LazyEvent()
        self.reg_seq_lock: asyncio.Lock | None = None
        self.reg_ack_event = LazyEvent()
        self.reg_ack_return_code: str = ""
        self.rest_api_thread_sem: asyncio.Semaphore | None = None
        self.account_rest_lock: asyncio.Lock | None = None

        # ── 데이터 캐시 ────────────────────────────────────────────────────────
        self.MIN_CACHE_LIFETIME_SEC: float = 1.0
        self.sector_summary_cache: "SectorSummary | None" = None  # type: ignore[name-defined]
        self.confirmed_refresh_running: bool = False
        self.confirmed_refresh_running_confirmed: bool = False  # 확정시세 다운로드 전용
        self.confirmed_refresh_running_5d: bool = False         # 5일봉 다운로드 전용
        self.confirmed_refresh_message: str = ""
        self.latest_filter_summary: str = ""
        self.latest_filter_summary_meta: str = ""
        self.master_stocks_cache: dict[str, dict] = {}
        self.market_phase: dict = {
            "krx": "장개시전", "nxt": "장개시전",
        }
        self.krx_circuit_breaker_active: bool = False

        # ── 주문 간격 타이머 (매수/매도 공통 — order_interval.py 헬퍼가 갱신) ──
        self._last_global_buy_ts: float = 0.0
        self._last_global_sell_ts: float = 0.0

        # ── 계좌 상태 ───────────────────────────────────────────────────────────
        self.ws_account_subscribed: bool = False
        self.ws_connection_status: bool = False
        self.quote_subscribed: bool = False
        self.account_rest_bootstrapped: bool = False
        self.broker_rest_totals: dict = {
            "total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_rate": 0.0,
        }
        self.latest_stock_info: dict = {}
        self.auto_trade: AutoTradeManager | None = None
        self.integrated_system_settings_cache: dict = {}
        self.broker_spec: list = []
        self.broker_rest_apis: dict[str, Any] = {}  # {broker_id: RestApi}
        self.account_snapshot: dict = {}
        self.positions: list = []
        self.snapshot_history: list = []

        # ── 상수 ────────────────────────────────────────────────────────────────
        self.REG_POST_ACK_GAP_SEC = 0.35
        self.REG_RATE_LIMIT_RESUB_SEC = 30.0
        self.REG_STOCK_LOG_CHUNK_SIZE = 20
        self.REG_REAL_DEBUG_EXTRA_LOG = False
        self.AVG_AMT_CHUNK_SIZE = 50
        self.INDUSTRY_CHUNK_SIZE = 10

        # ── 스케줄러 상태 ───────────────────────────────────────────────────────
        self.last_reset_date: str = ""
        self.krx_remove_done: bool = False
        self.confirmed_done: bool = False
        self.ws_subscribe_timer_handles: list = []
        self.ws_subscribe_window_active: bool | None = None
        self.auto_trade_timer_handles: list = []
        self.midnight_timer_handle: asyncio.TimerHandle | None = None
        self.market_phase_periodic_task: asyncio.Task | None = None
        # ── 사전 트리거 멱등성 가드 (안 D 4단계 — 날짜 기반, P22 데이터 정합성) ──
        self.last_realtime_reset_date: str = ""        # 실시간 필드 초기화 실행 날짜 (YYYYMMDD)
        self.last_ws_subscribe_start_date: str = ""    # WS 구독 시작 실행 날짜 (YYYYMMDD)

    async def on_filter_settings_changed(self) -> None:
        """필터 설정 변경 시 처리 (engine_sector 모듈 위임)."""
        from backend.app.services.sector_data_provider import _on_filter_settings_changed as _sector_on_filter
        await _sector_on_filter()


# ── 싱글톤 인스턴스 ─────────────────────────────────────────────────────
state = EngineState()


# ── 전역 상태 접근 헬퍼 (호환성 유지) ─────────────────────────────────────
def _get_rest_api_thread_sem() -> asyncio.Semaphore:
    if state.rest_api_thread_sem is None:
        state.rest_api_thread_sem = asyncio.Semaphore(1)
    return state.rest_api_thread_sem

def _get_account_rest_lock() -> asyncio.Lock:
    if state.account_rest_lock is None:
        state.account_rest_lock = asyncio.Lock()
    return state.account_rest_lock

def _notify_reg_ack(return_code: str = "") -> None:
    """`engine_ws_dispatch` REG/UNREG 응답 처리 끝에서 호출 -- 순차 전송 대기 해제."""
    state.reg_ack_return_code = return_code
    if state.reg_ack_event:
        state.reg_ack_event.set()


