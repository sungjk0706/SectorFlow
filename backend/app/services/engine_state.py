# -*- coding: utf-8 -*-
"""
엔진 전역 상태 저장소.

모든 engine_*.py 모듈은 이 파일에서 전역 상태를 직접 import한다.
순환 import 방지: 이 모듈은 다른 engine_*.py를 import하지 않는다.
"""
import asyncio
from backend.app.core.kiwoom_connector import KiwoomConnector
from backend.app.core.kiwoom_providers import KiwoomAuthProvider
from backend.app.services.trading import AutoTradeManager
from backend.app.services.engine_utils import LazyLock, LazyEvent
from backend.app.services.state_manager import StateManager, OrderStatus

# ── StateManager ─────────────────────────────────────────────────────────
_state_manager: StateManager | None = None

# ── 엔진 상태 ───────────────────────────────────────────────────────────
_running = False
_connector_manager: "ConnectorManager | None" = None  # type: ignore[name-defined]
_kiwoom_connector: KiwoomConnector | None = None
_kiwoom_auth_provider: KiwoomAuthProvider | None = None
_broker_tokens: dict[str, str] = {}  # {broker_id: access_token}
_engine_task: asyncio.Task | None = None
_engine_loop_ref: asyncio.AbstractEventLoop | None = None
_access_token: str | None = None
_login_ok = False
_checked_stocks: set = set()
_engine_user_id: str = ""
_last_ws_limit_warn_ts: float = 0.0
_realtime_latency_exceeded: bool = False
_avg_amt_needs_bg_refresh: bool = False
# _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음
_refresh_account_snapshot_meta = None
_update_account_memory = None

# ── Locks & Events ───────────────────────────────────────────────────────
_shared_lock = LazyLock()
_realtime_state: str = "IDLE"
_data_ready_event: asyncio.Event = asyncio.Event()
_token_ready_event: asyncio.Event = asyncio.Event()
_ws_reg_pipeline_done = LazyEvent()
_bootstrap_event = LazyEvent()
_sector_summary_ready_event = LazyEvent()
_engine_ready_event = LazyEvent()
_server_ready_event = LazyEvent()
_preboot_cache_loaded: bool = False
_preboot_ready_event = LazyEvent()
_engine_stop_event = LazyEvent()
_reg_seq_lock: asyncio.Lock | None = None
_reg_ack_event = LazyEvent()
_reg_ack_return_code: str = ""
_rest_api_thread_sem: asyncio.Semaphore | None = None
_account_rest_lock: asyncio.Lock | None = None

# ── 데이터 캐시 ────────────────────────────────────────────────────────
# _radar_cnsr_order 삭제
_sector_stock_layout: list[tuple[str, str]] = []
# _avg_amt_5d 제거: _master_stocks_cache에서 직접 사용
# _amts_5d_arrays, _highs_5d_arrays 제거: stock_5d_array 테이블에서 직접 읽도록 대체
_subscribed_0d_stocks: set[str] = set()
# 실시간 틱 데이터 캐시 삭제 (_latest_trade_prices, _latest_trade_amounts, _latest_strength)
_filtered_sector_codes: set[str] | None = None
# 실시간 틱 데이터 캐시 삭제 (_latest_strength)
# _sector_stocks_cache 제거: _master_stocks_cache 기반 실시간 필터링으로 대체
# _sector_stocks_dirty 제거
# _sector_stocks_last_invalidated 제거
_MIN_CACHE_LIFETIME_SEC: float = 1.0
_buy_targets_snapshot_cache: list | None = None
_buy_targets_cache_ref: object | None = None
# 실시간 틱 데이터 캐시 삭제 (_rest_radar_quote_cache)
_rest_radar_rest_once: set[str] = set()
_sector_summary_cache: "SectorSummary | None" = None  # type: ignore[name-defined]
_sector_buy_last_ts: dict[str, float] = {}
_stock_rising_state: dict[str, bool] = {}
_sector_score_index: dict[str, "SectorScore"] = {}  # type: ignore[name-defined]
_confirmed_refresh_running: bool = False
_confirmed_refresh_running_confirmed: bool = False  # 확정시세 다운로드 전용
_confirmed_refresh_running_5d: bool = False         # 5일봉 다운로드 전용
_confirmed_refresh_message: str = ""
_latest_filter_summary: str = ""
_master_stocks_cache: dict[str, dict] = {}

# ── 계좌 상태 ───────────────────────────────────────────────────────────
_ws_account_subscribed: bool = False
_account_rest_bootstrapped: bool = False
_broker_rest_totals: dict = {
    "total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_rate": 0.0,
}
_latest_stock_info: dict = {}
_auto_trade: AutoTradeManager | None = None
_settings_cache: dict = {}
_subscribed_stocks: set[str] = set()
_broker_spec: list = []
_rest_api: "KiwoomRestAPI | None" = None  # type: ignore[name-defined]
_account_snapshot: dict = {}
_positions: list = []
_snapshot_history: list = []

# ── 상수 ────────────────────────────────────────────────────────────────
_REG_POST_ACK_GAP_SEC = 0.35
_REG_RATE_LIMIT_RESUB_SEC = 30.0
_REG_STOCK_LOG_CHUNK_SIZE = 20
_REG_REAL_DEBUG_EXTRA_LOG = False
_AVG_AMT_CHUNK_SIZE = 50
_INDUSTRY_CHUNK_SIZE = 10
_ACCOUNT_BROADCAST_COALESCE_SEC: float = 0.0
_account_broadcast_pending_reason: str | None = None
_account_broadcast_timer: asyncio.TimerHandle | None = None

# ── 전역 상태 접근 헬퍼 ─────────────────────────────────────────────────
def _get_rest_api_thread_sem() -> asyncio.Semaphore:
    global _rest_api_thread_sem
    if _rest_api_thread_sem is None:
        _rest_api_thread_sem = asyncio.Semaphore(1)
    return _rest_api_thread_sem

def _get_account_rest_lock() -> asyncio.Lock:
    global _account_rest_lock
    if _account_rest_lock is None:
        _account_rest_lock = asyncio.Lock()
    return _account_rest_lock

def _get_realtime_state() -> str:
    return _realtime_state

def _set_realtime_state(state: str) -> None:
    global _realtime_state
    if _realtime_state == state:
        return
    _realtime_state = state
    from backend.app.core.logger import get_logger
    logger = get_logger("engine")
    logger.info("[REALTIME_STATE] 상태 변경: %s", state)
    from backend.app.services import engine_account_notify as _account_notify
    if state == "WAITING_FIRST_TICK":
        _account_notify._broadcast("realtime-state", {"status": "waiting"})
    elif state == "LIVE":
        _account_notify._broadcast("realtime-state", {"status": "live"})

def _on_filter_settings_changed() -> None:
    """필터 설정 변경 시 처리 (engine_sector 모듈 위임)."""
    from backend.app.services.engine_sector import _on_filter_settings_changed as _sector_on_filter
    import asyncio
    loop = asyncio.get_running_loop()
    loop.create_task(_sector_on_filter())

def _cancel_price_trace_delayed_task() -> None:
    """호환용 노-op."""
    pass

def _notify_reg_ack(return_code: str = "") -> None:
    """`engine_ws_dispatch` REG/UNREG 응답 처리 끝에서 호출 -- 순차 전송 대기 해제."""
    global _reg_ack_return_code
    try:
        _reg_ack_return_code = return_code
        if _reg_ack_event:
            _reg_ack_event.set()
    except Exception:
        from backend.app.core.logger import get_logger
        logger = get_logger(__name__)
        logger.warning("[연결] REG ACK 상태 설정 실패", exc_info=True)

# _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음
