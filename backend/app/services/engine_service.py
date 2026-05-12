# -*- coding: utf-8 -*-
"""
자동매매 엔진 오케스트레이터 (메모리 전용 버전)
- 기동 시 settings.json에서 브로커 확인 -> broker_specs/{broker}.json 메모리 로드
- WebSocket(REG/REAL, 키움 공식 타입 00·01·04·0g): 주문체결·체결가·잔고·종목정보(상·하한 등) -- 보유·레이더·작전의 현재가·매매 판단·화면 표시
  모니터링 표시: WebSocket REAL(FID 10) 우선. 모니터링 최초 등록 시에만 ka10001 1회(주기 REST 없음).
- REST(kt00001/kt00018): 예수금·주문가능·잔고 수량·매입가 부트스트랩, 수동 동기화, 주문 API 전용
  (REST 현재가로 _positions 를 덮어쓰지 않음 -- REAL 01 캐시 _latest_trade_prices 우선)
- 레이더 종목명: WS FID 302와 불일치 시 data_manager.get_stock_name -- **ka10100 우선**, 실패 시 ka10001/ka00198(키움 권장·공식 종목정보)
- 업종별 종목 **실시간(REG)**: 웹소켓은 **종목당 1건** 순차 전송(ACK 후 다음); 20개 묶음 REG가 아님. 기동 로그의 `N~M번 등록 처리`는 요약용.
- DB 저장 없음: 모든 상태는 프로세스 메모리에 유지
"""
import asyncio
import json
import sys
import time
from collections import OrderedDict
from pathlib import Path
from datetime import datetime, timezone

from app.core.engine_settings import get_engine_settings
from app.core.trade_mode import is_test_mode
from app.core.avg_amt_cache import (
    load_avg_amt_cache,
    load_avg_amt_cache_v2,
    save_avg_amt_cache,
    save_avg_amt_cache_v2,
    avg_from_v2,
)
from app.core.sector_stock_cache import (
    load_layout_cache,
    save_layout_cache,
    load_snapshot_cache,
    save_snapshot_cache,
)
from app.core.kiwoom_connector import KiwoomConnector
from app.core.logger import get_logger
from app.services.trading import AutoTradeManager
from app.services import data_manager
from app.services.auto_trading_effective import auto_buy_effective, auto_sell_effective
from app.services.engine_account_rest import (
    apply_last_price_to_positions_inplace,
    broker_totals_from_summary,
    build_account_snapshot_meta,
    merge_positions_from_rest,
    parse_kt00018_balance,
    parse_kt00001_deposit,
    real04_official_account_delta,
    real04_official_apply_position_line,
    recalc_broker_totals_from_positions,
)
from app.services.engine_ws_parsing import (
    _normalize_kiwoom_real_type,
    _parse_fid10_price,
    _parse_ws_fid12_to_percent,
    _ws_fid_int,
    _ws_fid_key_present,
    _ws_fid_raw,
    _ws_int,
)
from app.services.engine_symbol_utils import (
    _base_stk_cd,
    _format_kiwoom_reg_stk_cd,
    _normalize_stk_cd_rest,
    _real_item_stk_cd,
    _resolve_bucket_key,
    _to_al_stk_cd,
    get_ws_subscribe_code,
)
from app.services.engine_trade_audit import audit_trade_decision
from app.services.engine_ws_fill_followup import run_after_order_fill_ws
from app.services import engine_account_notify as _account_notify
from app.services import engine_radar_ops
from app.services import engine_loop
from app.services import engine_strategy_core
from app.services import engine_ws_dispatch
from app.services import dry_run
from app.services import settlement_engine

# ── 모듈 분리 (하위 호환 유지) ──────────────────────────────────────────
# engine_bootstrap: 앱준비 흐름 함수
# engine_cache: 캐시 오케스트레이션
# engine_state: 상태 프록시 (이 모듈의 전역 변수를 __getattr__로 위임)
import app.services.engine_bootstrap as _engine_bootstrap
import app.services.engine_cache as _engine_cache

broadcast_account_update = _account_notify.broadcast_account_update
broadcast_engine_status_ws = _account_notify.broadcast_engine_status_ws
notify_desktop_trade_price = _account_notify.notify_desktop_trade_price
register_account_ws_queue = _account_notify.register_account_ws_queue
register_desktop_account_notifier = _account_notify.register_desktop_account_notifier
register_desktop_buy_radar_notifier = _account_notify.register_desktop_buy_radar_notifier
register_desktop_account_tabs_refresh = _account_notify.register_desktop_account_tabs_refresh
register_desktop_header_refresh_notifier = _account_notify.register_desktop_header_refresh_notifier
register_desktop_trade_price_notifier = _account_notify.register_desktop_trade_price_notifier
notify_desktop_account_tabs_refresh = _account_notify.notify_desktop_account_tabs_refresh
notify_desktop_buy_radar_only = _account_notify.notify_desktop_buy_radar_only
register_engine_ws_queue = _account_notify.register_engine_ws_queue
unregister_account_ws_queue = _account_notify.unregister_account_ws_queue
unregister_engine_ws_queue = _account_notify.unregister_engine_ws_queue
# 지수 노티파이어
register_desktop_index_notifier = _account_notify.register_desktop_index_notifier
register_desktop_sector_notifier = _account_notify.register_desktop_sector_notifier
notify_desktop_index_refresh = _account_notify.notify_desktop_index_refresh
notify_desktop_sector_refresh = _account_notify.notify_desktop_sector_refresh
notify_desktop_sector_scores = _account_notify.notify_desktop_sector_scores
register_desktop_settings_toggled_notifier = _account_notify.register_desktop_settings_toggled_notifier
notify_desktop_settings_toggled = _account_notify.notify_desktop_settings_toggled
# WS 신규 이벤트 노티파이어
notify_snapshot_history_update = _account_notify.notify_snapshot_history_update
notify_buy_targets_update = _account_notify.notify_buy_targets_update
notify_desktop_sector_stocks_refresh = _account_notify.notify_desktop_sector_stocks_refresh

logger = get_logger("engine")

# ── LRU 캐시 유틸리티 (메모리 제한용) ────────────────────────────────────────
class LRUCache(dict):
    """최대 크기를 가진 LRU(Least Recently Used) 캐시.

    dict를 상속받아 기존 코드와 호환성 유지.
    maxsize 초과 시 가장 오래된 항목 자동 삭제.
    """
    def __init__(self, maxsize: int = 1000, *args, **kwargs):
        self._maxsize = maxsize
        self._order: OrderedDict = OrderedDict()
        super().__init__(*args, **kwargs)
        # 초기 데이터가 있으면 순서에 추가
        for key in self:
            self._order[key] = None

    def __getitem__(self, key):
        value = super().__getitem__(key)
        # 접근 시 순서 갱신
        self._order.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self._order.move_to_end(key)
        else:
            self._order[key] = None
            # 크기 초과 시 가장 오래된 항목 삭제
            if len(self._order) > self._maxsize:
                oldest = next(iter(self._order))
                del self._order[oldest]
                super().__delitem__(oldest)
        super().__setitem__(key, value)

    def __delitem__(self, key):
        if key in self._order:
            del self._order[key]
        super().__delitem__(key)

    def clear(self):
        self._order.clear()
        super().clear()

    def get(self, key, default=None):
        if key in self:
            self._order.move_to_end(key)
            return super().__getitem__(key)
        return default

    def pop(self, key, *args):
        if key in self._order:
            del self._order[key]
        return super().pop(key, *args)


_running = False
_connector_manager: "ConnectorManager | None" = None  # type: ignore[name-defined]
_kiwoom_connector: KiwoomConnector | None = None
_broker_tokens: dict[str, str] = {}  # {broker_id: access_token}
_engine_task: asyncio.Task | None = None
_engine_loop_ref: asyncio.AbstractEventLoop | None = None
_access_token: str | None = None
_login_ok = False
_checked_stocks: set = set()

_shared_lock = asyncio.Lock()

# 최대 3000종목 (관심 종목 상세 정보)
_pending_stock_details: LRUCache = LRUCache(maxsize=3000)
_radar_cnsr_order: list[str] = []
_sector_stock_layout: list[tuple[str, str]] = []
_avg_amt_5d: dict[str, int] = {}

# 5일 전고점 캐시 — 장전 앱준비 시 1회 적재, 장중 읽기 전용
_high_5d_cache: dict[str, int] = {}       # {종목코드: 5일전고점(원)}

# 호가 잔량 캐시 — WS 0D 수신 시 갱신 (최대 2000종목)
_orderbook_cache: LRUCache = LRUCache(maxsize=2000)  # {종목코드: (매수잔량, 매도잔량)}

# 0D 구독 중인 종목 집합 — diff 계산용
_subscribed_0d_stocks: set[str] = set()

# 실시간 체결가/거래대금 캐시 (최대 2500종목)
_latest_trade_prices: LRUCache = LRUCache(maxsize=2500)
_latest_trade_amounts: LRUCache = LRUCache(maxsize=2500)
_sector_dirty_codes: set[str] = set()
_filtered_sector_codes: set[str] | None = None
# 체결 강도 캐시 (최대 2500종목)
_latest_strength: LRUCache = LRUCache(maxsize=2500)

# ── get_sector_stocks() 증분 캐시 (Phase 1, Req 1) ──────────────────────
_sector_stocks_cache: list | None = None
_sector_stocks_dirty: bool = True
_sector_stocks_last_invalidated: float = 0.0
_MIN_CACHE_LIFETIME_SEC: float = 1.0


def _invalidate_sector_stocks_cache(force: bool = False) -> None:
    """캐시 무효화 — 종목 추가/제거, 순위 변경, 필터 변경 시 호출.
    
    Args:
        force: True면 1초 제한 무시하고 강제 무효화 (사용자 설정 변경 시 사용)
    """
    global _sector_stocks_dirty, _sector_stocks_last_invalidated
    now = time.monotonic()
    if not force and now - _sector_stocks_last_invalidated < _MIN_CACHE_LIFETIME_SEC:
        return  # 1초 내 재무효화 방지
    _sector_stocks_dirty = True
    _sector_stocks_last_invalidated = now

# ── get_buy_targets_snapshot() 증분 캐시 (Phase 1, Req 2) ────────────────
_buy_targets_snapshot_cache: list | None = None
_buy_targets_cache_ref: object | None = None  # 캐시 구축 시점의 _sector_summary_cache 참조

# REST 호가 캐시 (최대 1500종목)
_rest_radar_quote_cache: LRUCache = LRUCache(maxsize=1500)
_rest_radar_rest_once: set[str] = set()

_rest_api_thread_sem: asyncio.Semaphore | None = None

# ── 계좌 브로드캐스트 coalescing (Phase 2 최적화) ─────────────────────────
_ACCOUNT_BROADCAST_COALESCE_SEC: float = 0.5  # 0.5초 동안 모아서 1회만 전송
_account_broadcast_pending_reason: str | None = None
_account_broadcast_timer: asyncio.TimerHandle | None = None


def _get_rest_api_thread_sem() -> asyncio.Semaphore:
    global _rest_api_thread_sem
    if _rest_api_thread_sem is None:
        _rest_api_thread_sem = asyncio.Semaphore(1)
    return _rest_api_thread_sem

_ws_account_subscribed: bool = False
_account_rest_bootstrapped: bool = False
_account_rest_lock: asyncio.Lock | None = None


def _get_account_rest_lock() -> asyncio.Lock:
    global _account_rest_lock
    if _account_rest_lock is None:
        _account_rest_lock = asyncio.Lock()
    return _account_rest_lock

_broker_rest_totals: dict = {
    "total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_rate": 0.0,
}
_latest_stock_info: dict = {}
_auto_trade: AutoTradeManager | None = None
_engine_user_id: str = ""
_last_ws_limit_warn_ts: float = 0.0
_settings_cache: dict = {}

_subscribed_stocks: set[str] = set()
_ws_reg_pipeline_done: asyncio.Event = asyncio.Event()
_bootstrap_event: asyncio.Event = asyncio.Event()
_sector_summary_ready_event: asyncio.Event = asyncio.Event()

# 현대적 안정성을 위한 상태 이벤트
_engine_ready_event: asyncio.Event = asyncio.Event()
_server_ready_event: asyncio.Event = asyncio.Event()

_avg_amt_refresh_running: bool = False
_preboot_cache_loaded: bool = False
_preboot_ready_event: asyncio.Event = asyncio.Event()
_engine_stop_event: asyncio.Event = asyncio.Event()

_reg_seq_lock: asyncio.Lock | None = None
_reg_ack_event: asyncio.Event = asyncio.Event()
_reg_ack_return_code: str = ""
_REG_POST_ACK_GAP_SEC = 0.35
_REG_RATE_LIMIT_RESUB_SEC = 30.0
_REG_STOCK_LOG_CHUNK_SIZE = 20
_REG_REAL_DEBUG_EXTRA_LOG = False

_AVG_AMT_CHUNK_SIZE = 50
_INDUSTRY_CHUNK_SIZE = 10

_latest_index: dict[str, dict] = {}
_latest_industry_index: dict[str, dict] = {}
_sector_summary_cache: "SectorSummary | None" = None  # type: ignore[name-defined]
_sector_buy_last_ts: dict[str, float] = {}


_broker_spec: list = []
_rest_api: "KiwoomRestAPI | None" = None  # type: ignore[name-defined]
_account_snapshot: dict = {}
_positions: list = []
_snapshot_history: list = []

# ── 하위 호환 re-export: engine_bootstrap 함수 ──
_bootstrap_sector_stocks_async = _engine_bootstrap._bootstrap_sector_stocks_async
_notify_close_data_ui = _engine_bootstrap._notify_close_data_ui
_deferred_close_data_refresh = _engine_bootstrap._notify_close_data_ui  # 하위 호환 별칭
refresh_avg_amt_5d_cache = _engine_bootstrap.refresh_avg_amt_5d_cache
_chunked_fetch_full_5d = _engine_bootstrap._chunked_fetch_full_5d
_refresh_avg_amt_5d_cache_inner = _engine_bootstrap._refresh_avg_amt_5d_cache_inner
_broadcast_avg_amt_progress = _engine_bootstrap._broadcast_avg_amt_progress
_bg_refresh_avg_amt_5d = _engine_bootstrap._bg_refresh_avg_amt_5d
_login_post_pipeline = _engine_bootstrap._login_post_pipeline




async def _ws_send_reg_unreg_and_wait_ack(payload: dict) -> tuple[bool, str]:
    """
    키움 공식: REG/UNREG 1건 전송 후 응답(ACK, return_code 포함) 수신까지 대기한 뒤 다음 전송.
    Returns (True, return_code) if ACK 수신, (False, "") if 타임아웃(응답 없음).
    """
    global _reg_seq_lock, _reg_ack_return_code

    if _reg_seq_lock is None:
        _reg_seq_lock = asyncio.Lock()
    async with _reg_seq_lock:
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
            await asyncio.wait_for(_reg_ack_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            _reg_ack_event.clear()
            logger.warning(
                "[실시간연결] 구독 응답 대기 시간 초과(10s) -- trnm=%s",
                payload.get("trnm"),
            )
            await asyncio.sleep(_REG_POST_ACK_GAP_SEC)
            return False, ""
        rc = _reg_ack_return_code
        await asyncio.sleep(_REG_POST_ACK_GAP_SEC)
        return True, rc


def _notify_reg_ack(return_code: str = "") -> None:
    """`engine_ws_dispatch` REG/UNREG 응답 처리 끝에서 호출 -- 순차 전송 대기 해제."""
    global _reg_ack_return_code
    try:
        _reg_ack_return_code = return_code
        _reg_ack_event.set()
    except Exception:
        pass


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
    if sent:
        logger.debug("[실시간연결] 구독해지 전송 완료 grp_no=%s", payload.get("grp_no"))
    else:
        logger.warning("[실시간연결] 구독해지 전송 실패 grp_no=%s", payload.get("grp_no"))
    return sent


# ── 5일 평균 거래대금 갱신 (단일 진입점) ─────────────────────────────────


def _update_avg_amt_5d(new_data: dict[str, int], *, merge: bool = False) -> None:
    """_avg_amt_5d 갱신 후 필터 자동 재계산."""
    global _filtered_sector_codes
    if not merge:
        _avg_amt_5d.clear()
    _avg_amt_5d.update(new_data)
    _filtered_sector_codes = _compute_filtered_codes()
    _invalidate_sector_stocks_cache()
    logger.info(
        "[5일평균] 갱신 완료 -- %d종목, 필터 통과 %s개",
        len(_avg_amt_5d),
        len(_filtered_sector_codes) if _filtered_sector_codes is not None else "전체",
    )


def _compute_filtered_codes() -> set[str] | None:
    """sector_stock_layout에서 사용자 필터를 적용하여 조건 통과 종목 코드 집합을 반환."""
    global _filtered_sector_codes
    settings = _get_settings()

    # 설정값 검증 및 안전장치
    raw_val = settings.get("sector_min_trade_amt")
    try:
        min_amt_억 = float(raw_val) if raw_val is not None else 0.0
    except (TypeError, ValueError):
        logger.warning("[거래대금필터] 설정값 파싱 실패: %s", raw_val)
        min_amt_억 = 0.0
    min_amt_억 = max(0.0, min_amt_억)

    min_amt_won = min_amt_억 * 1_0000_0000
    codes = {
        _format_kiwoom_reg_stk_cd(v)
        for t, v in _sector_stock_layout
        if t == "code" and v
    }
    codes.discard("")

    if min_amt_won <= 0:
        _filtered_sector_codes = None
        return None

    # 거래대금 캐시가 비어있으면 필터 비활성화
    if not _avg_amt_5d:
        logger.warning("[거래대금필터] 5일거래대금 캐시 비어있음 - 필터 비활성화")
        _filtered_sector_codes = None
        return None

    filtered = set()
    for cd in codes:
        avg_raw = int(_avg_amt_5d.get(cd, 0) or 0)
        avg_won = avg_raw * 1_000_000
        if avg_won >= min_amt_won:
            filtered.add(cd)

    logger.info("[거래대금필터] 설정 %.0f억 → 필터 통과 %d/%d종목", min_amt_억, len(filtered), len(codes))

    if not filtered:
        logger.warning("[거래대금필터] 최소금액 %.1f억 설정됐으나 통과 종목 0개", min_amt_억)
    _filtered_sector_codes = filtered
    return filtered


# ── WS 구독 시작 시 실시간 필드 초기화 ─────────────────────────────────


_REALTIME_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")


async def _reset_realtime_fields() -> None:
    """WS 구독 시작 시 실시간 필드를 None으로 초기화하고 실시간 캐시 3종을 비운다."""
    async with _shared_lock:
        count = len(_pending_stock_details)
        for entry in _pending_stock_details.values():
            for f in _REALTIME_FIELDS:
                entry[f] = None
        _latest_trade_amounts.clear()
        _latest_trade_prices.clear()
        _latest_strength.clear()
        _orderbook_cache.clear()
        _subscribed_0d_stocks.clear()
        _rest_radar_quote_cache.clear()
        _rest_radar_rest_once.clear()
        _snapshot_history.clear()
        # 보유종목 현재가 초기화 (전일 종가 혼입 방지)
        for pos in _positions:
            pos["cur_price"] = 0
    logger.info(
        "[엔진] 실시간 필드 및 REST 보완 저장데이터, 수익 이력 초기화 완료 -- %d종목, 실시간/REST 저장데이터 전체 클리어",
        count,
    )
    notify_desktop_sector_stocks_refresh()
    _broadcast_account("realtime_reset")


def get_pending_stocks() -> list:
    return [e for e in _pending_stock_details.values() if e.get("status") == "active"]


def get_sector_stock_layout() -> list[tuple[str, str]]:
    return list(_sector_stock_layout)


def get_avg_amt_5d_map() -> dict[str, int]:
    return dict(_avg_amt_5d)


def get_high_5d_cache() -> dict[str, int]:
    return dict(_high_5d_cache)


async def get_account_snapshot() -> dict:
    async with _shared_lock:
        snap = dict(_account_snapshot)
    if not snap or "trade_mode" not in snap:
        _is_test = is_test_mode(_settings_cache)
        snap.setdefault("trade_mode", "test" if _is_test else "real")
        if _is_test:
            snap.setdefault("accumulated_investment", settlement_engine.get_accumulated_investment())
            snap.setdefault("orderable", settlement_engine.get_orderable())
            snap.setdefault("initial_deposit", settlement_engine.get_accumulated_investment())  # 누적투자금과 동일
        for k in ("total_buy", "total_eval", "total_pnl",
                   "total_buy_amount", "total_eval_amount"):
            snap.setdefault(k, 0)
        for k in ("total_rate", "total_pnl_rate"):
            snap.setdefault(k, 0.0)
        snap.setdefault("position_count", 0)
    return snap


def get_trade_mode() -> str:
    return "test" if is_test_mode(_settings_cache) else "real"


async def get_positions() -> list:
    if is_test_mode(_settings_cache):
        return dry_run.get_positions()
    async with _shared_lock:
        return list(_positions)


def get_total_buy_amount() -> int:
    if is_test_mode(_settings_cache):
        return sum(int(p.get("buy_amt", 0) or 0) for p in dry_run.get_positions())
    return int(_broker_rest_totals.get("total_buy", 0) or 0)


def get_total_eval_amount() -> int:
    if is_test_mode(_settings_cache):
        return sum(int(p.get("eval_amt", 0) or 0) for p in dry_run.get_positions())
    return int(_broker_rest_totals.get("total_eval", 0) or 0)


def get_total_pnl() -> int:
    if is_test_mode(_settings_cache):
        return sum(int(p.get("pnl_amount", 0) or 0) for p in dry_run.get_positions())
    return int(_broker_rest_totals.get("total_pnl", 0) or 0)


def get_total_pnl_rate() -> float:
    if is_test_mode(_settings_cache):
        total_buy = get_total_buy_amount()
        total_pnl = get_total_pnl()
        return round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0
    return float(_broker_rest_totals.get("total_rate", 0.0) or 0.0)


def get_snapshot_history() -> list:
    return list(_snapshot_history)


def get_buy_limit_status() -> dict:
    """매수 한도 상태를 dict로 반환 (프론트 배지용)."""
    settings = _settings_cache or {}
    daily_buy_spent = 0
    if _auto_trade:
        _auto_trade._ensure_daily_buy_counter()
        daily_buy_spent = _auto_trade._daily_buy_spent
    return {"daily_buy_spent": daily_buy_spent}


def _broadcast_buy_limit_status() -> None:
    """매수 한도 상태를 WS로 브로드캐스트."""
    global _buy_targets_snapshot_cache
    _buy_targets_snapshot_cache = None  # 일일한도 상태 변경 → 매수후보 캐시 무효화
    try:
        from app.services.engine_account_notify import _broadcast, notify_buy_targets_update
        _broadcast("buy-limit-status", get_buy_limit_status())
        notify_buy_targets_update()
    except Exception as e:
        logger.warning("[실시간연결] 매수한도 화면전송 실패: %s", e)


def _ws_live() -> bool:
    return bool(_kiwoom_connector and _kiwoom_connector.is_connected() and _login_ok)


def _get_settings() -> dict:
    return _settings_cache


def get_settings_snapshot() -> dict:
    global _settings_cache
    if isinstance(_settings_cache, dict) and _settings_cache:
        d = dict(_settings_cache)
    else:
        from app.core.settings_file import load_settings
        d = dict(load_settings())
    if "tele_on" not in d:
        d["tele_on"] = bool(d.get("telegram_on", False))
    if "telegram_on" not in d:
        d["telegram_on"] = bool(d.get("tele_on", False))
    # 헤더 칩용: 백엔드 실제 유효 상태 (시간 범위 + 공휴일 + 마스터 스위치 반영)
    from app.services.auto_trading_effective import (
        auto_buy_effective, auto_sell_effective, auto_trading_effective,
    )
    d["auto_buy_effective"] = auto_buy_effective(d)
    d["auto_sell_effective"] = auto_sell_effective(d)
    d["auto_trading_effective"] = auto_trading_effective(d)
    return d


# ── 모니터링 / 매수대기 관리 ─────────────────────────────────────────────────

def _overlay_radar_row_with_live_price(row: dict) -> dict:
    """
    REAL 01(FID 10) 캐시로 현재가·거래량·거래대금만 보강.
    등락률·대비·sign·체결강도는 키움 서버 FID로만 갱신(REAL 01 본문) -- 클라이언트 재계산 없음(키움 공식 실시간 동기화 가이드).
    REAL이 아직 없을 때만 _rest_radar_quote_cache(등록 시 1회 ka10001)로 표시 보완.

    NOTE: dict() 복사는 Python GIL 하에서 원자적이므로 lock 불필요.
    """
    tp = dict(_latest_trade_prices)
    ta = dict(_latest_trade_amounts)
    rc = dict(_rest_radar_quote_cache)
    return engine_radar_ops.overlay_radar_row_with_live_price(
        row, tp, ta, rc,
    )


async def _apply_real01_volume_amount_to_radar_rows(raw_cd: str, vals: dict, *, is_0b_tick: bool = True) -> None:
    """FID 13·14가 있는 틱에서만 캐시 갱신. 없으면 캐시가 있을 때만 행 보강(0으로 덮지 않음)."""
    async with _shared_lock:
        engine_radar_ops.apply_real01_volume_amount_to_radar_rows(
            raw_cd,
            vals,
            _latest_trade_amounts,
            _pending_stock_details,
            is_0b_tick=is_0b_tick,
        )




def get_sector_scores_snapshot() -> tuple[list[dict], int]:
    """업종 분석 순위 스냅샷 반환 — UI 업종분석 카드용.
    
    Returns: (scores_list, ranked_sectors_count)
    - scores_list: 전체 업종 목록 (rank=0 포함)
    - ranked_sectors_count: 순위 있는 업종 수 (rank > 0)
    """
    ss = _sector_summary_cache
    if not ss:
        return [], 0
    out: list[dict] = []
    ranked_count = 0
    for sc in ss.sectors:
        out.append({
            "rank": sc.rank,
            "sector": sc.sector,
            "final_score": round(sc.final_score, 1),
            "total_trade_amount": sc.total_trade_amount,
            "rise_ratio": round(sc.rise_ratio * 100, 1),
            "total": sc.total,
            "rise_count": sc.rise_count,
        })
        if sc.rank > 0:
            ranked_count += 1
    return out, ranked_count


def recompute_sector_summary_now() -> None:
    """설정 변경 시 즉시 _sector_summary_cache 재계산 (10초 루프 대기 없이)."""
    global _sector_summary_cache
    if not is_running():
        return
    try:
        from app.services.engine_sector_score import compute_full_sector_summary
        from app.services.engine_sector_confirm import cancel_pending_recompute
        settings = _get_settings()
        trim_trade = float(settings.get("sector_trim_trade_amt_pct", 0) or 0)
        trim_change = float(settings.get("sector_trim_change_rate_pct", 0) or 0)
        _ss = compute_full_sector_summary(
            **get_sector_summary_inputs(),
            sort_keys=settings.get("sector_sort_keys") or None,
            min_rise_ratio=float(settings.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
            block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
            block_fall_pct=float(settings.get("buy_block_fall_pct", 7.0)),
            min_strength=float(settings.get("buy_min_strength", 0)),
            min_trade_amt_won=float(settings.get("sector_min_trade_amt", 0.0)) * 1_0000_0000,
            index_guard_kospi_on=bool(settings.get("buy_index_guard_kospi_on", False)),
            index_guard_kosdaq_on=bool(settings.get("buy_index_guard_kosdaq_on", False)),
            index_kospi_drop=float(settings.get("buy_index_kospi_drop", 2.0)),
            index_kosdaq_drop=float(settings.get("buy_index_kosdaq_drop", 2.0)),
            max_sectors=int(settings.get("sector_max_targets", 3)),
            sector_weights=settings.get("sector_weights"),
            trim_trade_amt_pct=trim_trade,
            trim_change_rate_pct=trim_change,
            # 가산점 파라미터
            high_5d_cache=_high_5d_cache,
            orderbook_cache=_orderbook_cache,
            boost_high_on=bool(settings.get("boost_high_breakout_on", False)),
            boost_high_score=float(settings.get("boost_high_breakout_score", 1.0)),
            boost_order_ratio_on=bool(settings.get("boost_order_ratio_on", False)),
            boost_order_ratio_pct=float(settings.get("boost_order_ratio_pct", 20.0)),
            boost_order_ratio_score=float(settings.get("boost_order_ratio_score", 1.0)),
        )
        _sector_summary_cache = _ss
        _invalidate_sector_stocks_cache()
        # 디바운스 대기 중인 재계산 취소 (이전 설정으로 덮어쓰기 방지)
        cancel_pending_recompute()
        logger.info("[엔진] 섹터 요약 즉시 재계산 완료")

        # 매수후보 WS 브로드캐스트 + 매수 판단 (항상 실행)
        from app.services.engine_account_notify import notify_buy_targets_update
        notify_buy_targets_update()
        _try_sector_buy()
    except Exception as e:
        logger.warning("[엔진] 섹터 요약 즉시 재계산 실패: %s", e)





def get_sector_summary_inputs() -> dict:
    """
    engine_sector_score.compute_full_sector_summary 호출에 필요한 데이터 스냅샷 반환.
    buy_widget 폴링 또는 엔진 루프에서 사용.

    sector_mapping 기반 56개 투자 섹터 자체 집계 구조.
    industry_map / latest_industry_index 제거됨.

    NOTE: dict()/list() 복사는 Python GIL 하에서 원자적이므로 lock 불필요.
    """
    snap_pending = dict(_pending_stock_details)
    snap_prices = dict(_latest_trade_prices)
    snap_amounts = dict(_latest_trade_amounts)
    snap_avg = dict(_avg_amt_5d)
    snap_strength = dict(_latest_strength)
    snap_layout = list(_sector_stock_layout)
    snap_index = dict(_latest_index)

    merged_details: dict = {}
    merged_details.update(snap_pending)

    filter_set = _filtered_sector_codes  # 5일 평균 거래대금 필터 통과 종목 (None=전체)
    all_codes_raw = [v for t, v in snap_layout if t == "code"]
    if filter_set is not None:
        # filter_set은 _format_kiwoom_reg_stk_cd 포맷 — 동일 함수로 비교
        all_codes = [c for c in all_codes_raw if _format_kiwoom_reg_stk_cd(c) in filter_set]
    else:
        all_codes = all_codes_raw

    return {
        "all_codes":         all_codes,
        "trade_prices":      snap_prices,
        "trade_amounts":     snap_amounts,
        "avg_amt_5d":        snap_avg,
        "strengths":         snap_strength,
        "stock_details":     merged_details,
        "latest_index":      snap_index,
    }


def _get_orderbook(code: str) -> tuple[int, int] | None:
    """호가잔량 (bid, ask) 튜플 반환. 캐시 없으면 None."""
    return _orderbook_cache.get(code)


def get_buy_targets_snapshot() -> list[dict]:
    """매수후보 카드 스냅샷 반환 (통과 + 차단 종목 모두 포함).

    _sector_summary_cache 참조가 동일하면 캐시 직접 반환 (Req 2).
    """
    global _buy_targets_snapshot_cache, _buy_targets_cache_ref

    ss = _sector_summary_cache
    if not ss:
        return []

    # 참조 동일 → 캐시 유효
    if _buy_targets_snapshot_cache is not None and ss is _buy_targets_cache_ref:
        return _buy_targets_snapshot_cache

    # ── 캐시 재구축 ──
    from app.services.engine_symbol_utils import get_stock_market as _get_mkt
    from app.services.engine_symbol_utils import is_nxt_enabled as _is_nxt
    from app.services.daily_time_scheduler import is_krx_after_hours
    _after_hours = is_krx_after_hours()
    out: list[dict] = []

    # ── 보유 종목 코드 set: 실시간 잔고에서 직접 계산 (_checked_stocks 의존 제거) ──
    if is_test_mode(_settings_cache):
        _holding_codes = dry_run.position_codes()
    else:
        _holding_codes = {
            _format_kiwoom_reg_stk_cd(str(p.get("stk_cd", "")))
            for p in _positions
            if int(p.get("qty", 0) or 0) > 0
        }
    _bought_today_set = _auto_trade._bought_today if _auto_trade else set()

    # ── 일일매수한도 도달 여부 (잔여 < 1회 매수금액도 포함) ──
    _max_daily = int((_settings_cache or {}).get("max_daily_total_buy_amt", 0) or 0)
    _buy_amt_unit = int((_settings_cache or {}).get("buy_amt", 0) or 0)
    _daily_spent_now = _auto_trade._daily_buy_spent if _auto_trade else 0
    if _max_daily > 0:
        _daily_remain = max(0, _max_daily - _daily_spent_now)
        _daily_limit_hit = _daily_remain <= 0 or (_buy_amt_unit > 0 and _daily_remain < _buy_amt_unit)
    else:
        _daily_limit_hit = False

    # 가드 통과 종목
    for t in sorted(ss.buy_targets, key=lambda t: t.rank):
        s = t.stock
        # 장외 시간 KRX 단독 종목 제외
        if _after_hours and not _is_nxt(s.code):
            continue
        _pend = _pending_stock_details.get(s.code, {})
        # 통과 종목의 매수 제한 사유 표시 (실시간 잔고 기반)
        _reason = (
            "보유중" if s.code in _holding_codes
            else "금일매수" if s.code in _bought_today_set
            else "일일한도" if _daily_limit_hit
            else t.reason
        )
        out.append({
            "rank": t.rank,
            "name": s.name,
            "code": s.code,
            "sector": s.sector,
            "change": s.change,
            "change_rate": s.change_rate,
            "cur_price": s.cur_price,
            "strength": s.strength,
            "trade_amount": s.trade_amount,
            "boost_score": round(s.boost_score, 1),
            "order_ratio": _get_orderbook(s.code),
            "high_5d": _high_5d_cache.get(s.code, 0),
            "guard_pass": True,
            "reason": _reason,
            "market_type": _get_mkt(s.code) or "",
            "nxt_enable": _is_nxt(s.code),
        })
    # 가드 차단 종목
    for t in sorted(ss.blocked_targets, key=lambda t: t.rank):
        s = t.stock
        # 장외 시간 KRX 단독 종목 제외
        if _after_hours and not _is_nxt(s.code):
            continue
        _pend = _pending_stock_details.get(s.code, {})
        out.append({
            "rank": t.rank,
            "name": s.name,
            "code": s.code,
            "sector": s.sector,
            "change": s.change,
            "change_rate": s.change_rate,
            "cur_price": s.cur_price,
            "strength": s.strength,
            "trade_amount": s.trade_amount,
            "boost_score": round(s.boost_score, 1),
            "order_ratio": _get_orderbook(s.code),
            "high_5d": _high_5d_cache.get(s.code, 0),
            "guard_pass": False,
            "reason": t.reason,
            "market_type": _get_mkt(s.code) or "",
            "nxt_enable": _is_nxt(s.code),
        })

    _buy_targets_snapshot_cache = out
    _buy_targets_cache_ref = ss
    return _buy_targets_snapshot_cache


def get_position_pnl_pct_for_code(stk_cd: str) -> float | None:
    """보유 잔고에 있으면 수익률(%), 없으면 None."""
    from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd

    nk = _format_kiwoom_reg_stk_cd(str(stk_cd or "").strip())
    if not nk:
        return None
    # 테스트모드: dry_run 가상 잔고에서 조회
    if is_test_mode(_settings_cache):
        pos = dry_run.get_position(nk)
        if pos and int(pos.get("qty", 0) or 0) > 0:
            try:
                return float(pos.get("pnl_rate") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return None
    for p in _positions:
        pcd = _format_kiwoom_reg_stk_cd(str(p.get("stk_cd", "") or ""))
        if pcd != nk:
            continue
        if int(p.get("qty", 0) or 0) <= 0:
            return None
        try:
            return float(p.get("pnl_rate") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return None


def get_sector_stocks() -> list:
    """업종별 종목 시세 테이블용 — 캐시 유효 시 참조 직접 반환, dirty 시 재구축."""
    global _sector_stocks_cache, _sector_stocks_dirty

    if not _sector_stocks_dirty and _sector_stocks_cache is not None:
        return _sector_stocks_cache

    # ── dirty: 캐시 재구축 (필터 + 정렬 1회) ──
    filter_set = _filtered_sector_codes
    from app.services.engine_symbol_utils import get_stock_market as _get_mkt
    from app.services.engine_symbol_utils import is_nxt_enabled as _is_nxt
    from app.core.sector_mapping import get_merged_sector as _get_sector

    merged: dict[str, dict] = {}
    snap_avg = _avg_amt_5d

    for cd, e in _pending_stock_details.items():
        if filter_set is not None and cd not in filter_set:
            continue
        if e.get("status") != "active":
            continue
        # 시세 없는 빈 엔트리 제외
        if int(e.get("cur_price") or 0) <= 0 and (not e.get("name") or e.get("name") == cd):
            continue
        # 정적 보강 필드를 원본 dict에 직접 패치 (참조 공유)
        avg5d_raw = int(snap_avg.get(cd, 0) or 0)
        e["avg_amt_5d"] = avg5d_raw * 1_000_000
        e["market_type"] = _get_mkt(cd) or ""
        e["nxt_enable"] = _is_nxt(cd)
        e["sector"] = _get_sector(cd)
        merged[cd] = e

    # 업종 분석 순위 기준 정렬
    sector_order: dict[str, int] = {}
    ss = _sector_summary_cache
    if ss:
        for sc in ss.sectors:
            sector_order[sc.sector] = sc.rank

    result = list(merged.values())
    result.sort(key=lambda r: sector_order.get(r.get("sector", ""), 9999))

    _sector_stocks_cache = result
    _sector_stocks_dirty = False
    return _sector_stocks_cache


def get_all_sector_stocks() -> list[dict]:
    """전체 종목(매매부적격 제외) — _filtered_sector_codes 필터 미적용.

    업종분류 커스텀 페이지 전용. 각 종목: { code, name, sector(get_merged_sector 기반) }
    """
    snapshot = dict(_pending_stock_details)

    from app.core.sector_mapping import get_merged_sector
    import app.core.industry_map as _ind_mod
    elig = _ind_mod._eligible_stock_codes  # {코드: ""} — 빈 dict이면 필터 미적용

    result: list[dict] = []
    for cd, entry in snapshot.items():
        if entry.get("status") != "active":
            continue  # 매매부적격(관리종목, 거래정지, exited 등) 제외
        if elig and cd not in elig:
            continue  # 적격 필터: eligible이 비어있으면 필터 미적용 (하위 호환)
        try:
            sector = get_merged_sector(cd)
        except Exception:
            sector = ""
        result.append({
            "code": cd,
            "name": entry.get("name", ""),
            "sector": sector,
        })
    return result


def get_latest_trade_price_for_ui(stk_cd: str) -> int:
    """REAL 01 체결 캐시 기준 현재가 -- 매수 표 행·시세 정합 검증용."""
    nk = _format_kiwoom_reg_stk_cd(str(stk_cd or "").strip())
    if not nk:
        return 0
    v = _latest_trade_prices.get(nk)
    if v is None:
        return 0
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return 0
    return iv if iv > 0 else 0


async def _drop_rest_radar_quote_for_nk(nk: str) -> None:
    """REAL 체결가가 들어오면 REST 보완 캐시 제거 -- 항상 실시간 우선."""
    global _rest_radar_quote_cache
    async with _shared_lock:
        _rest_radar_quote_cache.pop(nk, None)


async def _clear_radar_rest_bootstrap_for_stk_cd(stk_cd: str) -> None:
    """모니터링에서 종목이 완전히 빠질 때 -- 다음 등록 시 REST 1회를 다시 허용."""
    global _rest_radar_quote_cache, _rest_radar_rest_once
    nk = _format_kiwoom_reg_stk_cd(str(stk_cd).strip().lstrip("A"))
    if nk:
        async with _shared_lock:
            _rest_radar_quote_cache.pop(nk, None)
        _rest_radar_rest_once.discard(nk)


async def _mark_radar_exited(stk_cd: str) -> None:
    """
    레이더 목록에서 종목 제거.
    pending 키는 6자리 정규화.
    """
    global _radar_cnsr_order
    nk = _normalize_stk_cd_rest(str(stk_cd).strip().lstrip("A"))
    rm: str | None = None
    if nk in _pending_stock_details:
        rm = nk
    else:
        for k in list(_pending_stock_details.keys()):
            if _normalize_stk_cd_rest(str(k)) == nk:
                rm = k
                break
    if rm is not None:
        nm = _pending_stock_details[rm].get("name", rm)
        async with _shared_lock:
            _pending_stock_details[rm]["status"] = "exited"  # 삭제 대신 마킹 -- 시세 테이블 유지
        _radar_cnsr_order[:] = [x for x in _radar_cnsr_order if x != rm]
        await _clear_radar_rest_bootstrap_for_stk_cd(rm)
        _invalidate_sector_stocks_cache()
        logger.debug("[모니터링] ⚫ 조건 이탈·목록 제거: %s (%s)", nm, rm)


async def clear_exited_from_radar() -> int:
    """모니터링에서 이탈 종목 전체 삭제. 삭제된 개수 반환."""
    global _radar_cnsr_order
    to_del = [cd for cd, e in _pending_stock_details.items() if e.get("status") == "exited"]
    async with _shared_lock:
        for cd in to_del:
            del _pending_stock_details[cd]
    if to_del:
        ds = set(to_del)
        _radar_cnsr_order[:] = [x for x in _radar_cnsr_order if x not in ds]
        _invalidate_sector_stocks_cache()
        logger.info("[모니터링] 이탈 종목 %d개 정리 완료", len(to_del))
    return len(to_del)


def _merge_positions_from_rest(stock_list: list) -> list:
    """
    REST kt00018 잔고 반영. 수량·매입·종목명은 REST 기준.
    현재가: _latest_trade_prices(REAL 01 등 실시간)에 값이 있으면 항상 우선 -- REST 현재가로 덮지 않음.
    change/change_rate: _pending_stock_details 캐시에서 보완 (첫 틱 전 0 표시 방지).
    """
    result = merge_positions_from_rest(stock_list, _latest_trade_prices)
    for pos in result:
        cd = _format_kiwoom_reg_stk_cd(str(pos.get("stk_cd", "") or ""))
        if not cd:
            continue
        src = _pending_stock_details.get(cd)
        if src:
            if "change" not in pos or pos.get("change") == 0:
                pos["change"] = src.get("change", 0)
            if "change_rate" not in pos or pos.get("change_rate") == 0:
                pos["change_rate"] = src.get("change_rate", 0.0)
            if "sign" not in pos:
                pos["sign"] = src.get("sign", "3")
    return result


def _apply_broker_totals_from_summary(summary: dict) -> None:
    """REST kt00018 루트 합계 -- 실시간 이벤트에서 임의 합산하지 않고 이 값만 갱신."""
    global _broker_rest_totals
    _broker_rest_totals = broker_totals_from_summary(summary)


def _refresh_account_snapshot_meta() -> None:
    """
    스냅샷 시각·보유종목수·가격소스만 갱신.
    총평가·총손익·총매입·총수익률은 _broker_rest_totals만 사용(REST kt00018 또는 REAL 04 공식 FID 932~934) -- 포지션 합산 없음.
    테스트모드: 가상 예수금을 deposit/orderable에 반영.
    """
    global _account_snapshot
    _is_test = is_test_mode(_settings_cache)
    pos = dry_run.get_positions() if _is_test else _positions

    if _is_test:
        # 테스트모드: settlement_engine 누적투자금/주문가능금액 반영 + 포지션 합산으로 totals 구성
        accumulated_investment = settlement_engine.get_accumulated_investment()
        orderable = settlement_engine.get_orderable()
        total_buy = sum(int(p.get("buy_amt", 0) or 0) for p in pos)
        total_eval = sum(int(p.get("eval_amt", 0) or 0) for p in pos)
        total_pnl = total_eval - total_buy
        total_rate = round((total_pnl / total_buy) * 100, 2) if total_buy > 0 else 0.0

        _account_snapshot["accumulated_investment"] = accumulated_investment
        _account_snapshot["orderable"] = orderable
        _account_snapshot["initial_deposit"] = accumulated_investment  # 누적투자금과 동일
        
        test_totals = {
            "total_eval": total_eval,
            "total_pnl": total_pnl,
            "total_buy": total_buy,
            "total_rate": total_rate,
        }
        snap = build_account_snapshot_meta(
            _account_snapshot, test_totals, pos, _ws_live(),
            trade_mode="test",
        )
    else:
        snap = build_account_snapshot_meta(
            _account_snapshot, _broker_rest_totals, pos, _ws_live(),
            trade_mode="real",
        )
    
    _account_snapshot = snap


def _apply_last_price_to_positions(stk_cd: str, price: int) -> bool:
    """실시간 체결(REAL 01) -- 체결가 반영 + 평가손익·수익률·평가금액 실시간 재계산. 보유에 반영되면 True."""
    global _broker_rest_totals
    # 테스트모드: dry_run 가상 잔고에 현재가 반영 (6자리 정규화)
    if is_test_mode(_settings_cache):
        nk = _format_kiwoom_reg_stk_cd(str(stk_cd or "").strip())
        return dry_run.update_price(nk, price) if nk else False
    
    hit = apply_last_price_to_positions_inplace(_positions, stk_cd, price)
    if hit:
        _broker_rest_totals = recalc_broker_totals_from_positions(_positions, _broker_rest_totals)
    return hit


def _apply_balance_realtime(item: dict, vals: dict) -> None:
    """
    실시간 잔고(04) -- item 필드로 계좌/종목 레코드 구분 후 처리.
    계좌 단위(item=계좌번호): FID 930~934 계좌 합계 갱신.
    종목 단위(item=종목코드): FID 930~933·950·8019·10 포지션 갱신.
    """
    global _account_snapshot, _broker_rest_totals
    from app.services.engine_account_rest import _real04_is_stock_item
    if _real04_is_stock_item(item):
        # 종목 단위 레코드 -- 보유수량·매입단가·평가손익 등 갱신
        _prev_len = len(_positions)
        real04_official_apply_position_line(item, vals, _positions, _latest_trade_prices)
        if len(_positions) != _prev_len:
            from app.services.engine_account_notify import _rebuild_positions_cache
            _rebuild_positions_cache(_positions)
    else:
        # 계좌 단위 레코드 -- 예수금·총평가·총손익 등 갱신
        delta = real04_official_account_delta(vals)
        if delta:
            if "deposit" in delta:
                _account_snapshot["deposit"] = int(delta["deposit"])
            if "total_eval" in delta:
                _broker_rest_totals["total_eval"] = int(delta["total_eval"])
            if "total_pnl" in delta:
                _broker_rest_totals["total_pnl"] = int(delta["total_pnl"])
            if "total_rate" in delta:
                _broker_rest_totals["total_rate"] = float(delta["total_rate"])
    
    _refresh_account_snapshot_meta()
    _broadcast_account(reason="balance_04")


def _on_fill_after_ws() -> None:
    """주문체결(00) 완료 직후 -- REST 없이 메모리·매도조건만 갱신."""

    def _sell_if_applicable() -> None:
        if is_test_mode(_settings_cache):
            pos = dry_run.get_positions()
        else:
            pos = _positions
        if pos and _auto_trade and auto_sell_effective(_settings_cache) and _access_token:
            _auto_trade.check_sell_conditions(pos, _settings_cache, _access_token)

    run_after_order_fill_ws(
        0.0,
        _refresh_account_snapshot_meta,
        lambda reason=None: _broadcast_account(reason=reason),
        _sell_if_applicable,
        is_dry_run=is_test_mode(_settings_cache),
    )


def _tracked_ui_stock_codes() -> set[str]:
    """보유·레이더 종목코드(6자리 정규화) -- 시세 표시 대상."""
    out: set[str] = set()
    pos = dry_run.get_positions() if is_test_mode(_settings_cache) else list(_positions)
    for p in pos:
        if int(p.get("qty", 0) or 0) > 0:
            c = _format_kiwoom_reg_stk_cd(str(p.get("stk_cd", "") or ""))
            if c:
                out.add(c)
    for k in _pending_stock_details.keys():
        c = _format_kiwoom_reg_stk_cd(str(k))
        if c:
            out.add(c)
    return out


def _log_tracked_prices_snapshot(tag: str) -> None:
    """호환용 노-op -- 과거 REG 후 지연 진단용이었으나 숨은 백그라운드 로직 제거로 미사용."""
    del tag


def _schedule_delayed_price_trace_snapshot() -> None:
    """호환용 노-op -- 지연 시세 스냅샷 백그라운드 제거."""


def _cancel_price_trace_delayed_task() -> None:
    """호환용 노-op."""


async def _subscribe_account_realtime() -> None:
    """계좌 실시간 구독(주문체결·잔고) — engine_ws_reg 모듈로 위임."""
    from app.services import engine_ws_reg
    await engine_ws_reg.subscribe_account_realtime(sys.modules[__name__])


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
    from app.services import engine_ws_reg, ws_subscribe_control
    await engine_ws_reg.subscribe_positions_stocks_realtime(sys.modules[__name__])
    # REG 실행 후 인메모리 상태 동기화
    if _subscribed_stocks:
        ws_subscribe_control._set_status(quote=True)


async def _subscribe_radar_stocks_realtime() -> None:
    """
    레이더 종목 REG -- 시장가 운용으로 호가(02) 불필요, 제거됨.
    0B는 _subscribe_sector_stocks_0b 에서 이미 커버됨.
    """
    logger.debug("[구독등록] 레이더 종목 -- 시장가 운용으로 호가 생략")


async def _subscribe_all_tracked_stocks_realtime() -> None:
    """보유 + 레이더 -- 조건 전환 등 전체 재동기화 시에만."""
    await _subscribe_positions_stocks_realtime()
    await _subscribe_radar_stocks_realtime()


def _item_cd_is_position(item_cd: str, pos_keep: set[str]) -> bool:
    for p in pos_keep:
        if _format_kiwoom_reg_stk_cd(p) == item_cd:
            return True
    return False


def _item_cd_tracked_radar_or_ready(item_cd: str) -> bool:
    """
    모니터링 pending에 올라간 종목 -- 비보유여도 실시간(REG) 유지해야 HTS와 시세가 맞는다.
    잔고 REST 반영 후 UNREG 스윕 등에서 UNREG 대상에서 제외한다.
    """
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


async def _cleanup_stale_ws_subscriptions_on_session_ready() -> None:
    """로그인 직후 1회: 잔존 구독 정리 + 비보유 종목 UNREG 스윕."""
    if not _kiwoom_connector or not _kiwoom_connector.is_connected():
        return
    # 잔존 구독 정리 (grp_no=5,2,4 UNREG best-effort)
    from app.services import ws_subscribe_control
    await ws_subscribe_control.cleanup_stale_subscriptions(sys.modules[__name__])

    if _account_rest_bootstrapped:
        n = await _sweep_unreg_subscribed_except_positions_and_tracked()
        if n:
            logger.debug("[구독정리] 비보유·미추적 종목 구독해지 %d건", n)
    else:
        logger.debug("[구독정리] 계좌 조회 전 -- 구독해지 생략")




async def _subscribe_sector_stocks_0b() -> None:
    """필터 통과 종목 + 보유종목 0B REG — engine_ws_reg 모듈로 위임.

    REG 성공 후 ws_subscribe_control 상태를 동기화하여
    프론트엔드 구독 표시가 실제 상태와 일치하도록 한다.
    """
    from app.services import engine_ws_reg, ws_subscribe_control
    await engine_ws_reg.subscribe_sector_stocks_0b(sys.modules[__name__])
    # REG 실행 후 인메모리 상태 동기화 → WS 브로드캐스트
    ws_subscribe_control._set_status(quote=True)


async def _on_filter_settings_changed() -> None:
    """필터 설정 변경 시 diff 기반 증분 구독 갱신 + 업종순위 재계산 + WS 3종 전송.

    흐름:
    1. _compute_filtered_codes() → old/new diff (added, removed)
    2. old == new → 스킵 (WS 없음, WS 없음)
    3. WS 구독 구간 + quote 활성: REG added 먼저 → UNREG removed 나중에
    4. _subscribed_stocks 증분 갱신 (add/discard, clear 금지)
    5. recompute_sector_summary_now() → 업종순위 + 매수후보 재계산
    6. WS 3종: sector-stocks-refresh, sector-scores, buy-targets-update
    """
    global _filtered_sector_codes
    old_codes = _filtered_sector_codes.copy() if _filtered_sector_codes is not None else None
    new_codes = _compute_filtered_codes()

    logger.info(
        "[앱준비][필터변경] 이전=%d, 신규=%d, 변경없음=%s",
        len(old_codes or set()), len(new_codes or set()), old_codes == new_codes,
    )

    if old_codes == new_codes:
        logger.debug("[앱준비][필터변경] 필터 통과 종목 변경 없음 -- 구독 변경 생략")
        return

    # === 설정 변경 시 강제 캐시 무효화 (1초 제한 무시) ===
    _invalidate_sector_stocks_cache(force=True)
    logger.info("[앱준비][필터변경] 캐시 강제 무효화 완료")
    # ==================================================
    
    added = (new_codes or set()) - (old_codes or set())
    removed = (old_codes or set()) - (new_codes or set())
    logger.info(
        "[앱준비][필터변경] 필터 통과 종목 변경 -- 추가 %d, 제거 %d (총 %d → %d)",
        len(added), len(removed), len(old_codes or set()), len(new_codes or set()),
    )

    # ── WS 구독 증분 갱신: 구독 구간 + quote 활성 상태에서만 ──
    from app.services.daily_time_scheduler import is_ws_subscribe_window
    from app.services import ws_subscribe_control
    from app.services.engine_ws_reg import build_0b_reg_payloads, build_0b_remove_payloads

    if is_ws_subscribe_window(_settings_cache) and ws_subscribe_control.get_subscribe_status()["quote_subscribed"]:
        # ── 1) REG added 먼저 (새 종목 실시간 데이터 즉시 수신) ──
        if added:
            reg_targets = [cd for cd in added if cd not in _subscribed_stocks]
            if reg_targets:
                for cd in reg_targets:
                    _subscribed_stocks.add(cd)
                reg_ws_codes = [get_ws_subscribe_code(cd) for cd in reg_targets]
                payloads = build_0b_reg_payloads(reg_ws_codes, reset_first=False)
                _CHUNK = 100
                ok_cnt = fail_cnt = 0
                for ci, payload in enumerate(payloads):
                    chunk = reg_targets[ci * _CHUNK : (ci + 1) * _CHUNK]
                    ack_ok, _rc = await _ws_send_reg_unreg_and_wait_ack(payload)
                    if ack_ok:
                        ok_cnt += len(chunk)
                    else:
                        fail_cnt += len(chunk)
                        for cd in chunk:
                            _subscribed_stocks.discard(cd)
                        logger.warning(
                            "[앱준비][필터변경] 구독등록 응답 시간 초과 (청크 %d) -- %d종목 구독 롤백",
                            ci + 1, len(chunk),
                        )
                logger.info(
                    "[앱준비][필터변경] 구독등록 완료 -- 추가 %d / 성공 %d / 실패 %d",
                    len(reg_targets), ok_cnt, fail_cnt,
                )

        # ── 2) UNREG removed 나중에 (기존 종목 해지) ──
        if removed:
            unreg_targets = [cd for cd in removed if cd in _subscribed_stocks]
            if unreg_targets:
                unreg_ws_codes = [get_ws_subscribe_code(cd) for cd in unreg_targets]
                payloads = build_0b_remove_payloads(unreg_ws_codes)
                _CHUNK = 100
                ok_cnt = fail_cnt = 0
                for ci, payload in enumerate(payloads):
                    chunk = unreg_targets[ci * _CHUNK : (ci + 1) * _CHUNK]
                    ack_ok, _rc = await _ws_send_reg_unreg_and_wait_ack(payload)
                    if ack_ok:
                        ok_cnt += len(chunk)
                        for cd in chunk:
                            _subscribed_stocks.discard(cd)
                    else:
                        fail_cnt += len(chunk)
                        logger.warning(
                            "[앱준비][필터변경] 구독해지 응답 시간 초과 (청크 %d) -- %d종목 (다음 변경 시 재시도)",
                            ci + 1, len(chunk),
                        )
                logger.info(
                    "[앱준비][필터변경] 구독해지 완료 -- 제거 %d / 성공 %d / 실패 %d",
                    len(unreg_targets), ok_cnt, fail_cnt,
                )
    elif not is_ws_subscribe_window(_settings_cache):
        logger.debug("[앱준비][필터변경] 실시간 구독 구간 외 -- 구독 변경 생략 (필터 결과만 갱신)")
    else:
        logger.debug("[앱준비][필터변경] 실시간 구독 해지 상태 -- 구독 변경 생략")

    # ── 업종순위 + 매수후보 재계산 ──
    try:
        recompute_sector_summary_now()
    except Exception as e:
        logger.warning("[앱준비][필터변경] 업종순위 재계산 실패: %s", e)

    # ── WS 3종 전송 ──
    try:
        notify_desktop_sector_stocks_refresh()
    except Exception:
        pass
    try:
        notify_desktop_sector_scores(force=True)
    except Exception:
        pass
    try:
        notify_buy_targets_update()
    except Exception:
        pass


async def _run_sector_reg_pipeline() -> None:
    try:
        if not _kiwoom_connector or not _kiwoom_connector.is_connected() or not _login_ok:
            return
        # 구독 제어 모듈에 위임 (설정 기반 조건부 REG)
        from app.services import ws_subscribe_control
        await ws_subscribe_control.run_conditional_reg_pipeline(sys.modules[__name__])
    except Exception as e:
        logger.warning("[앱준비] 실시간 구독 파이프라인 실패: %s", e)
    finally:
        _ws_reg_pipeline_done.set()
        logger.info("[앱준비] 실시간 구독 준비 완료 -- 단건 구독 허용")
        if _ws_live():
            _refresh_account_snapshot_meta()


async def _fetch_market_map_async() -> None:
    """
    시장구분(코스피/코스닥) + NXT 중복상장 캐시 적재.
    당일 캐시 파일이 있으면 즉시 로드 (키움 조회 없음).
    캐시 없으면 ka10099 REST 조회 후 캐시 저장.
    """
    from app.services.engine_symbol_utils import set_market_map, get_market_map_version, set_nxt_enable_map
    from app.core.sector_stock_cache import load_market_map_cache, save_market_map_cache

    # 1. 저장데이터 로딩 → 즉시 적재
    cached = load_market_map_cache()
    if cached:
        market_map, nxt_map = cached
        set_market_map(market_map)
        set_nxt_enable_map(nxt_map)
        total_nxt = sum(1 for v in nxt_map.values() if v)
        logger.info(
            "[시장구분] 저장데이터 로드 -- %d종목 (ver=%d) / NXT %d종목",
            len(market_map), get_market_map_version(), total_nxt,
        )
        return

    # 2. 캐시 미스 → 키움 REST 조회
    import sys as _sys
    api = getattr(_sys.modules[__name__], "_rest_api", None)
    if api is None:
        logger.warning("[시장구분] 서버 미연결 -- 시장 구분 저장데이터 적재 생략")
        return
    try:
        new_market_map: dict[str, str] = {}
        new_nxt_map: dict[str, bool] = {}
        for i, (mrkt_tp, label) in enumerate(( ("0", "코스피"), ("10", "코스닥") )):
            if i > 0:
                await asyncio.sleep(1.5)  # 연속 호출 429 방지
            async with _get_rest_api_thread_sem():
                rows = await asyncio.to_thread(api.fetch_ka10099_full, mrkt_tp)
            nxt_cnt = 0
            for cd, nxt_enable, mkt_code in rows:
                new_market_map[cd] = mkt_code
                new_nxt_map[cd] = nxt_enable
                if nxt_enable:
                    nxt_cnt += 1
            logger.info("[시장구분] %s %d종목 적재 (NXT중복상장 %d종목)", label, len(rows), nxt_cnt)
        set_market_map(new_market_map)
        set_nxt_enable_map(new_nxt_map)
        save_market_map_cache(new_market_map, new_nxt_map)
        total_nxt = sum(1 for v in new_nxt_map.values() if v)
        logger.info(
            "[시장구분] REST 조회 완료 -- 총 %d종목 (ver=%d) / NXT %d종목 KRX단독 %d종목",
            len(new_market_map), get_market_map_version(), total_nxt, len(new_nxt_map) - total_nxt,
        )
    except Exception as e:
        logger.warning("[시장구분] 캐시 적재 실패 (무시): %s", e)


async def _subscribe_index_realtime() -> None:
    """코스피·코스닥 업종지수 0J REG — engine_ws_reg 모듈로 위임."""
    from app.services import engine_ws_reg
    await engine_ws_reg.subscribe_index_realtime(sys.modules[__name__])



async def _ensure_ws_subscriptions_for_positions() -> None:
    """로그인 직후 계좌 실시간 구독 + 보유종목 시세 구독을 하는 함수.

    테스트모드: 계좌 구독(00/04) 스킵, 보유종목 시세(0B)만 구독.
    실전투자: 계좌 구독 + 보유종목 시세 모두 구독.
    """
    try:
        if not _kiwoom_connector or not _kiwoom_connector.is_connected() or not _login_ok:
            return
        if not is_test_mode(_settings_cache):
            await _subscribe_account_realtime()
        else:
            logger.info("[엔진] 테스트모드 -- 계좌 실시간 구독(00/04) 생략")
        await _subscribe_positions_stocks_realtime()
    except Exception as e:
        logger.warning("[엔진] 실시간 구독 전송 실패함: %s", e)
    finally:
        if _ws_live():
            _refresh_account_snapshot_meta()


async def on_trade_mode_switched() -> None:
    """거래모드 전환 시 호출 -- 엔진 재기동 없이 계좌 구독 상태만 전환한다."""
    _new_test = is_test_mode(_settings_cache)
    _mode_str = "테스트모드" if _new_test else "실전투자"
    logger.info("[엔진] 거래모드 전환 -> %s (엔진 재기동 없음)", _mode_str)

    if not is_running() or not _kiwoom_connector or not _kiwoom_connector.is_connected():
        return

    if _new_test:
        # 실전→테스트: 계좌 실시간 구독(00/04) 해제, 분석용 구독은 유지
        from app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp(sys.modules[__name__], "10")
        logger.info("[엔진] 테스트모드 전환 -- 계좌 실시간 구독(grp_no=10) 해제 완료")
        # Settlement Engine: 파일에서 상태 복원 + 만료 항목 정리 + 타이머 재스케줄
        settlement_engine.restore_state()
        logger.info("[엔진] 테스트모드 전환 -- Settlement Engine 상태 복원 완료")
    else:
        # 테스트→실전: Settlement Engine 상태 저장 + 타이머 취소
        settlement_engine.save_state()
        logger.info("[엔진] 실전모드 전환 -- Settlement Engine 상태 저장 완료")
        # 테스트→실전: 계좌 실시간 구독(00/04) + 보유종목 실시간(0B) 등록
        await _subscribe_account_realtime()
        await _subscribe_positions_stocks_realtime()
        logger.info("[엔진] 실전모드 전환 -- 계좌 실시간 구독(00/04) + 보유종목 실시간(0B) 등록 완료")

    # 모드 전환 후 계좌 스냅샷 즉시 갱신
    _refresh_account_snapshot_meta()
    _broadcast_account(reason="trade_mode_switch")


def _broadcast_account(reason: str | None = None) -> None:
    """데이터 갱신 후 UI/WS -- 페이로드 전송은 engine_account_notify.
    
    Phase 2 최적화: 0.5초 coalescing 적용 - 테스트모드에서 매수/매도/정산 
    빈번한 브로드캐스트를 모아서 1회만 전송하여 UI 깜빡임 감소.
    """
    global _account_broadcast_pending_reason, _account_broadcast_timer
    
    # 이유 저장 (마지막 이유만 기록)
    _account_broadcast_pending_reason = reason or "coalesced"
    
    # 기존 타이머 취소
    if _account_broadcast_timer is not None:
        _account_broadcast_timer.cancel()
    
    # 0.5초 후 실제 브로드캐스트
    try:
        loop = asyncio.get_running_loop()
        _account_broadcast_timer = loop.call_later(
            _ACCOUNT_BROADCAST_COALESCE_SEC,
            _apply_delayed_account_broadcast
        )
    except RuntimeError:
        # 이벤트 루프 없음 - 즉시 실행 (초기화 시)
        _apply_delayed_account_broadcast()


def _apply_delayed_account_broadcast() -> None:
    """0.5초 지연 후 실제 계좌 브로드캐스트 수행."""
    global _account_broadcast_pending_reason, _account_broadcast_timer
    
    reason = _account_broadcast_pending_reason
    _account_broadcast_pending_reason = None
    _account_broadcast_timer = None
    
    if reason is None:
        return
    
    try:
        pos = dry_run.get_positions() if is_test_mode(_settings_cache) else list(_positions)
        broadcast_account_update(
            reason,
            snapshot=dict(_account_snapshot),
            positions=pos,
        )
    except Exception as e:
        logger.debug("[계좌브로드캐스트] 지연 전송 실패: %s", e)


def _broadcast_engine_ws() -> None:
    """엔진 상태 dict 를 WS 구독자에게 전달."""
    broadcast_engine_status_ws(get_status())


# ── 매수 파이프라인 헬퍼 ────────────────────────────────────────────


async def _delayed_resubscribe_stock_after_rate_limit(norm_cd: str) -> None:
    """105110 직후 재시도하지 않고, 일정 시간 뒤 필요한 종목만 REG 재전송 -- 시장가 운용으로 no-op."""
    pass


def _log(msg: str) -> None:
    if is_test_mode(_settings_cache) and not msg.startswith("[테스트모드]"):
        msg = f"[테스트모드] {msg}"
    logger.info(msg)


def _now_kst() -> str:
    return datetime.now().strftime("%H:%M:%S")



# ── 민감 정보 마스킹 대상 키 ────────────────────────────────────────────
_SENSITIVE_SETTINGS_KEYS: frozenset[str] = frozenset({
    "kiwoom_app_key",
    "kiwoom_app_secret",
    "kiwoom_app_key_real",
    "kiwoom_app_secret_real",
    "telegram_bot_token",
})


def _mask_sensitive_settings(settings: dict) -> dict:
    """설정 딕셔너리에서 API 키·시크릿·토큰 등 민감 필드를 '***'로 마스킹한 복사본을 반환한다."""
    masked = dict(settings)
    for key in _SENSITIVE_SETTINGS_KEYS:
        if key in masked and masked[key]:
            masked[key] = "***"
    return masked


# ── initial-snapshot 종목 데이터 필드 필터링 ─────────────────────────────────
_SNAPSHOT_STOCK_FIELDS = {
    "code", "name", "cur_price", "change", "change_rate", "strength",
    "trade_amount", "sector", "avg_amt_5d", "market_type", "nxt_enable",
}


def _filter_stock_fields(stocks: list[dict]) -> list[dict]:
    """initial-snapshot용 종목 데이터 필드 필터링."""
    return [{k: v for k, v in s.items() if k in _SNAPSHOT_STOCK_FIELDS} for s in stocks]


def _get_trade_history_for_snapshot(side: str) -> list:
    """initial-snapshot용 체결 이력 반환. 현재 trade_mode 기준 필터."""
    from app.services import trade_history
    mode = get_trade_mode()
    if side == "sell":
        return trade_history.get_sell_history(trade_mode=mode)
    return trade_history.get_buy_history(trade_mode=mode)


def _get_daily_summary_for_snapshot() -> list:
    """initial-snapshot용 20거래일 일별 요약 반환."""
    from app.services import trade_history
    return trade_history.get_daily_summary(days=20, trade_mode=get_trade_mode())


async def build_initial_snapshot() -> dict:
    """WS 연결 시 클라이언트에게 보낼 메타 상태 스냅샷을 조립한다.

    sector_stocks는 별도 이벤트(sector-stocks-refresh)로 분할 전송하므로 여기서는 빈 리스트.
    """

    async def _safe(fn, default):
        """getter 호출을 감싸서 실패하면 기본값을 돌려준다."""
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as exc:
            logger.warning("[확정데이터] %s 호출 실패 — 기본값 사용: %s", fn.__name__, exc)
            return default

    positions = await _safe(get_positions, [])
    account_snap = await _safe(get_account_snapshot, {})

    from app.services import ws_subscribe_control
    from app.services.daily_time_scheduler import get_market_phase

    # 항상 최신 설정을 파일에서 직접 로드 (캐시 사용 안함)
    from app.core.settings_file import load_settings_async
    _raw_settings = await load_settings_async()

    scores_snapshot = await _safe(get_sector_scores_snapshot, ([], 0))
    scores_list, ranked_count = scores_snapshot if isinstance(scores_snapshot, tuple) else (scores_snapshot, 0)
    
    snapshot: dict = {
        "_v":               1,
        "account":          account_snap,
        "positions":        positions,
        "sector_stocks":    [],  # 분할 전송 — sector-stocks-refresh 이벤트로 별도 전송
        "sector_scores":    scores_list,
        "sector_status":    {"total_stocks": len(scores_list), "max_targets": int(_settings_cache.get("sector_max_targets", 3) or 3), "ranked_sectors_count": ranked_count},
        "buy_targets":      await _safe(get_buy_targets_snapshot, []),
        "settings":         _mask_sensitive_settings(_raw_settings),
        "status":           await _safe(get_status, {}),
        "snapshot_history": await _safe(get_snapshot_history, []),
        "sell_history":     await _safe(lambda: _get_trade_history_for_snapshot("sell"), []),
        "buy_history":      await _safe(lambda: _get_trade_history_for_snapshot("buy"), []),
        "daily_summary":    await _safe(lambda: _get_daily_summary_for_snapshot(), []),
        "buy_limit_status": await _safe(get_buy_limit_status, {"daily_buy_spent": 0}),
        "ws_subscribe_status": ws_subscribe_control.get_subscribe_status(),
        "bootstrap_done":   _bootstrap_event.is_set() or _preboot_cache_loaded,
        "market_phase":     get_market_phase(),
        "broker_config":    _raw_settings.get("broker_config", {}),
        "avg_amt_refresh":  {
            "running": _avg_amt_refresh_running,
            "current": 0,
            "total": sum(1 for t, _ in _sector_stock_layout if t == "code") if _avg_amt_refresh_running else 0,
        } if _avg_amt_refresh_running else None,
    }

    # Delta 캐시 초기화 — sector_stocks는 분할 전송 시점에 초기화
    try:
        from app.services.engine_account_notify import init_sent_caches
        init_sent_caches([], positions, account_snap)
    except Exception as e:
        logger.warning("[확정데이터] delta 저장데이터 초기화 실패: %s", e)

    try:
        payload_bytes = len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
        logger.info("[확정데이터] 메타 크기 %d bytes", payload_bytes)
    except Exception as exc:
        logger.warning("[확정데이터] 크기 측정 실패: %s", exc)

    return snapshot


async def build_sector_stocks_payload() -> dict:
    """sector-stocks-refresh 이벤트용 종목 데이터 페이로드를 조립한다."""
    sector_stocks = get_sector_stocks()
    filtered = _filter_stock_fields(sector_stocks)

    # Delta 캐시 초기화 (종목 데이터 기준)
    try:
        from app.services.engine_account_notify import init_sent_caches
        init_sent_caches(sector_stocks, await get_positions(), await get_account_snapshot())
    except Exception:
        pass

    from app.services.daily_time_scheduler import is_krx_after_hours
    return {"_v": 1, "stocks": filtered, "krx_after_hours": is_krx_after_hours()}


def _sync_sell_overrides_from_settings() -> None:
    """sell_per_symbol -> AutoTradeManager.ts_overrides 동기화."""
    global _auto_trade, _settings_cache
    if not _auto_trade or not isinstance(_settings_cache, dict):
        return
    sp = _settings_cache.get("sell_per_symbol")
    _auto_trade.ts_overrides = dict(sp) if isinstance(sp, dict) else {}


def _schedule_engine_coro(coro: asyncio.coroutines, *, context: str) -> bool:
    """
    엔진 이벤트 루프에 코루틴을 안전하게 스케줄한다.
    UI 스레드(이벤트 루프 없음)에서 호출되는 경우 call_soon_threadsafe를 사용한다.
    """
    global _engine_loop_ref
    loop = _engine_loop_ref
    if loop and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(lambda: loop.create_task(coro))
            return True
        except Exception as e:
            logger.warning("[엔진] %s 스케줄 실패함: %s", context, e)
            try:
                coro.close()
            except Exception:
                pass
            return False
    try:
        asyncio.get_running_loop().create_task(coro)
        return True
    except Exception as e:
        logger.warning("[엔진] %s 요청 실패함: %s", context, e)
        try:
            coro.close()
        except Exception:
            pass
        return False


def _position_codes_with_qty() -> set[str]:
    """보유 수량이 있는 종목 코드(레이더·작전 REG 해제 시 유지 대상)."""
    if is_test_mode(_settings_cache):
        return dry_run.position_codes()
    out: set[str] = set()
    for s in list(_positions):
        try:
            cd = str(s.get("stk_cd", "")).strip()
            if cd and int(s.get("qty", 0) or 0) > 0:
                out.add(cd)
        except (TypeError, ValueError):
            continue
    return out


async def _clear_radar_and_ready_memory() -> None:
    global _pending_stock_details, _checked_stocks, _radar_cnsr_order
    global _rest_radar_quote_cache, _rest_radar_rest_once, _sector_stock_layout
    async with _shared_lock:
        _pending_stock_details = {}
        _radar_cnsr_order = []
        _sector_stock_layout.clear()
        _rest_radar_quote_cache.clear()
    from app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache(_sector_stock_layout)
    _checked_stocks = set()
    _rest_radar_rest_once.clear()
    _invalidate_sector_stocks_cache()


async def _kiwoom_message_handler(payload: dict) -> None:
    """KiwoomConnector에서 호출되는 핸들러.

    _KiwoomSocket._recv_loop → _on_ws_message(async) → 이 함수(async).
    create_task 없이 await 직접 호출 — 순서 보장, 태스크 폭발 없음.
    """
    if not isinstance(payload, dict):
        return
    trnm = payload.get("trnm", "")
    if trnm in ("REAL", "LOGIN", "REG", "UNREG", "REMOVE"):
        await _handle_ws_data(payload)


async def _subscribe_stock_realtime_when_ready(stk_cd: str) -> None:
    """
    모니터링 등록 시점이 LOGIN 이전이면 REG가 무력화될 수 있어,
    WS 연결·로그인 성공 후 REG를 보내도록 짧게 재시도한다.
    기동 시 배치 파이프라인(_run_sector_reg_pipeline) 완료 전에는
    단건 REG를 보내지 않음 -- 배치가 이미 커버하므로 중복 블로킹 방지.
    시장가 운용으로 호가(02) REG 제거됨 -- 0B는 배치에서 커버.
    """
    stk_cd = str(stk_cd).strip().lstrip("A")
    if not stk_cd:
        return
    # 배치 파이프라인 완료 대기 (최대 120초)
    try:
        await asyncio.wait_for(_ws_reg_pipeline_done.wait(), timeout=120.0)
    except asyncio.TimeoutError:
        pass
    # 배치에서 이미 구독됐으면 단건 불필요 (0B 기준)
    item_cd = _format_kiwoom_reg_stk_cd(stk_cd)
    if item_cd in _subscribed_stocks:
        logger.debug("[실시간] 단건 REG 생략(배치 완료) -- %s", item_cd)
        return
    # 배치에 포함되지 않은 신규 모니터링 종목 — 단건 0B REG 전송
    if not _ws_live():
        logger.debug("[실시간] 단건 REG 생략 — WS 미연결/미로그인 %s", item_cd)
        return
    from app.services.engine_ws_reg import build_0b_reg_payloads
    ws_code = get_ws_subscribe_code(item_cd)
    payloads = build_0b_reg_payloads([ws_code], reset_first=False)
    if payloads:
        ok, rc = await _ws_send_reg_unreg_and_wait_ack(payloads[0])
        if ok:
            _subscribed_stocks.add(item_cd)
            logger.debug("[실시간] 단건 0B REG 완료 -- %s (return_code=%s)", item_cd, rc)
        else:
            logger.warning("[실시간] 단건 0B REG 실패 -- %s", item_cd)


async def _handle_ws_data(data: dict) -> None:
    """WebSocket `data` 페이로드 처리 -- 본문은 `engine_ws_dispatch`에 위임."""
    await engine_ws_dispatch.handle_ws_data(data, sys.modules[__name__])


async def _fetch_account_data(settings: dict) -> dict:
    """
    키움 REST API로 실계좌 잔고/평가 조회.
    - 영속 _rest_api 인스턴스를 재사용해 토큰 중복 발급 방지
    - 토큰 없으면 즉시 실패 반환 (0원 stub 금지)
    - deposit -> balance 순차 호출 + 0.5초 간격으로 429 예방
    """
    import sys
    _EMPTY = {"success": False, "summary": {}, "stock_list": []}

    # es(engine_service 모듈) 속성으로 접근 -- global 선언과 모듈 속성 불일치 방지
    _self = sys.modules[__name__]
    api = getattr(_self, "_rest_api", None)
    if api is None:
        logger.warning("[계좌] _rest_api 없음 -- 엔진 기동 완료 전 호출. 계좌 조회 건너뜀.")
        return _EMPTY

    # ── 토큰 유효성 먼저 확인 ─────────────────────────────────────────────
    async with _get_rest_api_thread_sem():
        token_ok = await asyncio.to_thread(api._ensure_token)
    if not token_ok:
        logger.warning(
            "[계좌] 유효한 토큰 없음 (au10001 발급 실패) -- 계좌 조회 건너뜀. "
            "이전 값을 그대로 유지합니다. (0원 표시 방지)"
        )
        return _EMPTY

    token_preview = (api._token_info.token[:10] + "...") if api._token_info else "?"
    logger.info("[계좌] 토큰 유효 확인 (%s) -- 계좌 조회 시작", token_preview)

    acnt_no = str(getattr(api, "_acnt_no", "") or settings.get("kiwoom_account_no", "") or "")

    # ── deposit -> (0.5초 대기) -> balance 순차 호출로 429 예방 ─────────────
    try:
        async with _get_rest_api_thread_sem():
            deposit_raw = await asyncio.to_thread(api.get_deposit_detail, acnt_no)
        await asyncio.sleep(0.5)
        async with _get_rest_api_thread_sem():
            balance_raw = await asyncio.to_thread(api.get_balance_detail)
    except Exception as e:
        logger.warning("[계좌] API 호출 예외: %s", e)
        return _EMPTY

    if not deposit_raw:
        logger.warning("[계좌] 예수금 응답 없음 (kt00001 실패함) -- 조회 중단")
        return _EMPTY

    ok_dep, dep_body, deposit, orderable, _withdrawable = parse_kt00001_deposit(deposit_raw)
    if not ok_dep:
        logger.warning(
            "[계좌] kt00001 오류 return_code=%s 메시지=%s",
            dep_body.get("return_code"), dep_body.get("return_msg", ""),
        )
        return _EMPTY

    deposit, tot_eval, tot_pnl, tot_buy, total_rate, stock_list = parse_kt00018_balance(
        balance_raw, deposit
    )

    logger.info(
        "[계좌] 조회 완료 -- 총평가 %s원 | 손익 %s원 | 매입 %s원 | 예수금 %s원 | 종목 %d개",
        f"{tot_eval:,}", f"{tot_pnl:,}", f"{tot_buy:,}", f"{deposit:,}", len(stock_list),
    )

    return {
        "success": True,
        "summary": {
            "tot_eval":     tot_eval,
            "tot_pnl":      tot_pnl,
            "tot_buy":      tot_buy,
            "deposit":      deposit,
            "orderable":    orderable,
            "total_rate":   total_rate,
        },
        "stock_list": stock_list,
        "raw_data":   dep_body,
    }


async def _update_account_memory(settings: dict) -> None:
    """
    Kiwoom REST(kt00001/18)로 예수금·주문가능·잔고·증권사 합계(tot_*)를 부트스트랩한다.
    합계는 포지션 합산하지 않고 API 루트 합계만 _broker_rest_totals 에 저장한다.
    현재가는 REAL 01 캐시 우선 (REST로 _latest_trade_prices 를 오염시키지 않음).
    Lock으로 동시 호출 직렬화 -- 기동 시 _run_snapshot_and_sell_check + _login_post_pipeline 경쟁 방지.
    """
    global _account_snapshot, _positions, _snapshot_history, _account_rest_bootstrapped

    lock = _get_account_rest_lock()
    if lock.locked():
        logger.info("[계좌] REST 조회 중복 요청 -- 선행 조회 완료까지 대기")
    async with lock:
        # lock 대기 중 선행 조회가 완료됐으면 중복 호출 스킵
        if _account_rest_bootstrapped:
            logger.info("[계좌] REST 조회 -- 선행 조회에서 이미 완료됨, 중복 생략")
            return
        await _update_account_memory_inner(settings)


async def _update_account_memory_inner(settings: dict) -> None:
    """_update_account_memory 실제 구현 (Lock 내부에서 호출)."""
    global _account_snapshot, _positions, _snapshot_history, _account_rest_bootstrapped

    s = settings or {}
    broker = str(s.get("broker", "kiwoom") or "kiwoom")
    need_reload = False
    if broker == "kiwoom":
        if not s.get("kiwoom_app_key") or not s.get("kiwoom_app_secret"):
            need_reload = True
    if need_reload:
        s = await get_engine_settings(_engine_user_id or None)

    yield_data = await _fetch_account_data(s)

    if not yield_data.get("success"):
        logger.warning(
            "[계좌] 조회 실패함 -- 기존 스냅샷 유지 (총평가=%s원)",
            f"{_account_snapshot.get('total_eval', 0):,}",
        )
        return

    stock_list = yield_data.get("stock_list", [])
    summary    = yield_data.get("summary", {})

    _apply_broker_totals_from_summary(summary)
    # 테스트모드: 실전 잔고로 _positions 덮어쓰지 않음 -- dry_run 가상 잔고 격리
    if is_test_mode(s):
        logger.info("[계좌] 테스트모드 -- 실전 잔고 %d건 무시, dry_run 가상 잔고 유지", len(stock_list))
    else:
        # 수량·매입은 REST, 현재가는 REAL 01 우선 (REST로 _latest_trade_prices 를 오염시키지 않음)
        merged = _merge_positions_from_rest(stock_list)
        async with _shared_lock:
            _positions = merged
        from app.services.engine_account_notify import _rebuild_positions_cache
        _rebuild_positions_cache(merged)

    _account_rest_bootstrapped = True
    async with _shared_lock:
        _account_snapshot["broker"] = "kiwoom"
        _account_snapshot["deposit"] = int(summary.get("deposit", 0) or 0)
        _account_snapshot["orderable"] = int(summary.get("orderable", 0) or 0)

    # WS 구독 보강은 _login_post_pipeline / _run_snapshot_and_sell_check 에서 명시적으로 호출.
    # 여기서 호출하면 _account_rest_lock 안에서 _reg_seq_lock 을 잡는 중첩 락 -> 데드락 위험.
    if _ws_live():
        try:
            n_unreg = await _sweep_unreg_subscribed_except_positions_and_tracked()
            if n_unreg:
                logger.info(
                    "[구독정리] 잔고 반영 후 미보유·미추적 종목 구독해지 %d건 (추적 종목 제외)",
                    n_unreg,
                )
        except Exception as e:
            logger.warning("[엔진] 웹소켓 실시간 구독 정리 실패함: %s", e)
    _refresh_account_snapshot_meta()

    notify_desktop_account_tabs_refresh()
    _ps = _account_snapshot.get("price_source", "?")
    _ps_kr = (
        "웹소켓(실시간)"
        if _ps == "websocket"
        else "REST초기화"
        if _ps == "rest_bootstrap"
        else str(_ps)
    )
    _log(
        f"[계좌] 갱신 완료 -- 평가금: {_account_snapshot.get('total_eval', 0):,}원 | "
        f"손익: {_account_snapshot.get('total_pnl', 0):,}원 | 포지션: {_account_snapshot.get('position_count', 0)}개 | "
        f"가격소스: {_ps_kr}"
    )


async def _run_snapshot_and_sell_check(force_rest: bool = False) -> None:
    """
    매도 조건 검사 + (선택) REST 부트스트랩.
    - force_rest=True: 수동 동기화·엔진 최초 기동 -- kt00001/18 (예수금·수량·매입).
    - 부트스트랩 전 또는 WS 미연결: REST 조회.
    - WS 연결·부트스트랩 완료 후 force_rest=False: REST 생략, 스냅샷 메타만 갱신(합계는 마지막 REST 유지).
    """
    await engine_strategy_core.run_snapshot_and_sell_check(force_rest, sys.modules[__name__])


async def _engine_loop() -> None:
    await engine_loop.run_engine_loop(sys.modules[__name__])


async def start_engine(user_id: str = "") -> bool:
    global _engine_task, _running, _engine_user_id
    if _engine_task and not _engine_task.done():
        return False
    _engine_user_id = user_id
    _running        = True
    _engine_task    = asyncio.create_task(_engine_loop())
    _broadcast_engine_ws()
    return True





def _try_sector_buy() -> None:
    """
    이벤트 기반 매수 판단 — 실시간 데이터 변경 시 _do_sector_recompute()에서 호출.
    auto_buy_effective(시간 범위 + auto_buy_on + 마스터 스위치) 통과 시 매수 실행.
    쿨다운: sector_buy_cooldown_sec(기본 90초).
    """
    import time as _time
    global _sector_buy_last_ts

    if not _running:
        return

    ss = _sector_summary_cache
    if not ss or not ss.buy_targets:
        return

    settings = _get_settings()

    # ── 자동매수 게이트 (auto_buy_on + 시간 범위 + 마스터 스위치 통합 체크) ──
    if not auto_buy_effective(settings):
        return

    # ── 전역 조건 사전 체크 ──────────────────────────────────────────
    _max_limit = int(settings.get("max_stock_cnt", 5) or 5)
    if is_test_mode(settings):
        _pos_for_cnt = dry_run.get_positions()
    else:
        _pos_for_cnt = _positions
    _holding_cnt = sum(1 for p in _pos_for_cnt if int(p.get("qty", 0)) > 0)
    if _holding_cnt >= _max_limit:
        return

    _buy_amt = int(settings.get("buy_amt", 0) or 0)
    if _buy_amt <= 0:
        return

    _max_daily = int(settings.get("max_daily_total_buy_amt", 0) or 0)
    if _max_daily > 0:
        _daily_remain = _max_daily - _auto_trade._daily_buy_spent
        if _daily_remain <= 0:
            return

    # ── 종목별 매수 시도 ─────────────────────────────────────────────
    cooldown = float(settings.get("sector_buy_cooldown_sec") or 90)
    now = _time.time()

    from app.services.daily_time_scheduler import is_krx_after_hours
    from app.services.engine_symbol_utils import is_nxt_enabled
    _after_hours = is_krx_after_hours()

    for bt in ss.buy_targets:
        s = bt.stock
        if not s.guard_pass:
            continue
        # 장외 시간 KRX 단독 종목 매수 차단
        if _after_hours and not is_nxt_enabled(s.code):
            continue
        last_ts = _sector_buy_last_ts.get(s.code, 0.0)
        if now - last_ts < cooldown:
            continue

        _sector_buy_last_ts[s.code] = now
        logger.info("[섹터매수] 매수 시도: %s(%s) 섹터=%s 등락률=%.2f%%",
                    s.name, s.code, s.sector, s.change_rate)
        try:
            from app.services.engine_symbol_utils import real01_trade_price_from_cache
            _price = real01_trade_price_from_cache(_latest_trade_prices, s.code)
            if _price <= 0:
                logger.debug("[섹터매수] %s 실시간 시세 없음 -- 생략", s.code)
                continue
            _ordered = _auto_trade.execute_buy(
                s.code, float(_price), _checked_stocks, _access_token,
                force_buy=False,
                reason=f"업종자동매수 업종={s.sector}",
            )
            if _ordered:
                logger.info("[섹터매수] 매수 주문 전송: %s(%s)", s.name, s.code)
                _holding_cnt += 1
                if _holding_cnt >= _max_limit:
                    break
                _auto_trade._ensure_daily_buy_counter()
                if _max_daily > 0 and _auto_trade._daily_buy_spent >= _max_daily:
                    break
        except Exception as e:
            logger.warning("[섹터매수] execute_buy 오류 %s: %s", s.code, e)








async def stop_engine() -> None:
    global _running, _engine_task
    _running = False
    _engine_stop_event.set()

    # 디바운스 타이머 정리
    from app.services.engine_sector_confirm import cancel_sector_confirm_timer
    cancel_sector_confirm_timer()

    if _engine_task:
        _engine_task.cancel()
        try:
            await _engine_task
        except asyncio.CancelledError:
            pass
        _engine_task = None

    # 백그라운드 태스크 일괄 취소
    current = asyncio.current_task()
    all_tasks = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    bg_names = ("daily_time_scheduler",)
    bg_tasks = [t for t in all_tasks if any(n in (t.get_name() or "") for n in bg_names)]
    if bg_tasks:
        logger.info("[엔진] 백그라운드 태스크 %d개 취소 중...", len(bg_tasks))
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        logger.info("[엔진] 백그라운드 태스크 취소 완료")

    # 테스트모드 가상 잔고: 엔진 중지 시 초기화하지 않음
    # (포지션·예수금은 사용자가 직접 초기화할 때만 리셋)


def is_running() -> bool:
    """엔진이 현재 가동 중인지 확인한다."""
    return _running and _engine_task is not None and not _engine_task.done()


# 연결 레벨 설정 키 -- 이 키가 변경되면 엔진 완전 재기동이 필요하다.
# trade_mode / test_mode / kiwoom_mock_mode / mode_real 은 여기 포함하지 않는다.
# 실전↔테스트 전환은 API 키·서버·WS 모두 동일하므로 캐시 갱신만으로 충분하다.
CONNECTION_LEVEL_KEYS: frozenset[str] = frozenset({
    "broker",
    "broker_config",
    "kiwoom_app_key",
    "kiwoom_app_secret",
    "kiwoom_account_no",
    "kiwoom_app_key_real",
    "kiwoom_app_secret_real",
    "kiwoom_account_no_real",
})

# 거래 모드 전환 키 -- 엔진 재기동 없이 캐시 갱신 + 계좌 구독 전환만 수행한다.
TRADE_MODE_KEYS: frozenset[str] = frozenset({
    "trade_mode",
    "kiwoom_mock_mode",
    "test_mode",
    "mode_real",
})


async def refresh_engine_settings_cache(user_id: str | None = None, *, use_root: bool = False) -> None:
    """
    설정 파일 저장 직후 호출: 디스크와 동일한 내용으로 _settings_cache 를 갱신한다.
    주기적 파일 재로드는 하지 않으며, UI/텔레그램 등 저장 이벤트에서만 동기화한다.

    use_root=True: 루트 data/settings.json 기준으로 갱신 (단일 프로필 데스크톱 기본).
    """
    global _settings_cache
    if not is_running():
        return
    uid_engine = (_engine_user_id or "").strip()

    if use_root:
        load_user = None
    else:
        uid_save = (user_id or "").strip()
        if uid_engine and uid_save and uid_engine != uid_save:
            return
        load_user = uid_save if uid_save else (uid_engine or None)

    try:
        # 필터 설정 변경 감지용 -- 갱신 전 값 보존
        old_min_amt = _settings_cache.get("sector_min_trade_amt", 0.0) if _settings_cache else 0.0

        fresh = await get_engine_settings(load_user if load_user else None)
        _settings_cache = fresh
        _sync_sell_overrides_from_settings()
        label = "root" if load_user is None else (load_user or uid_engine or "root")
        logger.info("[엔진] 설정 메모리 동기화 완료 (사용자=%s)", label)

        # 필터 설정(sector_min_trade_amt) 변경 시 WS 구독 동적 갱신
        new_min_amt = fresh.get("sector_min_trade_amt", 0.0)
        if old_min_amt != new_min_amt and _bootstrap_event.is_set():
            logger.info(
                "[엔진][필터] 최소 거래대금 설정 변경: %.1f → %.1f억",
                old_min_amt, new_min_amt,
            )
            _schedule_engine_coro(
                _on_filter_settings_changed(), context="필터 설정 변경",
            )
    except Exception as e:
        logger.warning("[엔진] 설정 메모리 동기화 실패: %s", e)


async def reload_engine_settings() -> None:
    """
    연결 레벨 설정 변경 시 호출.
    실행 중인 엔진을 완전 종료한 뒤 새 설정값으로 재기동한다.
    """
    global _engine_user_id
    if not is_running():
        logger.info("[엔진] 재로딩 요청 -- 엔진이 실행 중이 아님, 건너뜀")
        return
    uid = _engine_user_id
    logger.info("[엔진] 설정 변경 감지 -> 엔진 재기동 시작 (사용자=%s)", uid or "admin")
    await stop_engine()
    from app.core.broker_factory import reset_router
    reset_router()
    await asyncio.sleep(0.5)
    await start_engine(uid)
    logger.info("[엔진] 재기동 완료")


def get_status() -> dict:
    _is_test = is_test_mode(_settings_cache)
    tm = str(_settings_cache.get("trade_mode") or ("test" if _is_test else "real"))
    tracked = _tracked_ui_stock_codes()
    missing_real = sorted(
        c for c in tracked if not (_latest_trade_prices.get(c) or 0)
    )
    # 등록 한도 카운터: 0B(업종별 종목) + 지수 2 + 계좌 2 (02 호가 제거됨 -- 시장가 운용)
    _reg_total = len(_subscribed_stocks) + 2 + 2
    if _reg_total >= 190:
        import time as _time
        global _last_ws_limit_warn_ts
        _now_ts = _time.monotonic()
        if _now_ts - _last_ws_limit_warn_ts >= 60.0:
            _last_ws_limit_warn_ts = _now_ts
            logger.warning(
                "[한도경고] WebSocket 등록 총합 %d개 -- 200개 한도 근접 (0B=%d, 지수=2, 계좌=2)",
                _reg_total, len(_subscribed_stocks),
            )
    st: dict = {
        "running":         _running,
        "kiwoom_connected": _kiwoom_connector.is_connected() if _kiwoom_connector else False,
        "login_ok":        _login_ok,
        "pending_count":   len(_checked_stocks),
        "active_broker":   _settings_cache.get("broker", "kiwoom"),
        "trade_mode":      tm,
        "price_source":    _account_snapshot.get("price_source"),
        "ws_account_subscribed": _ws_account_subscribed,
        "account_bootstrapped":  _account_rest_bootstrapped,
        # 진단용 (비밀 미포함): WS·실시간 이슈 원인 추적
        "is_test_mode":    _is_test,
        "has_access_token":   bool(_access_token),
        "kiwoom_token_valid": bool(_broker_tokens.get("kiwoom")) or bool(_rest_api and _rest_api._token_info and not _rest_api._token_info.is_expired_soon()),
        "engine_task_alive": bool(_engine_task and not _engine_task.done()),
        # 시세 누락 진단: 보유·레이더·작전 종목 중 REAL 체결가 미저장 코드
        "tracked_stocks_count": len(tracked),
        "latest_trade_prices_count": len(_latest_trade_prices),
        "tracked_without_real_price": missing_real[:50],
        "stock_subscribed_count": len(_subscribed_stocks),
        "ws_reg_total_estimate": _reg_total,  # 전체 등록 수 추정 (한도 200개)
        "price_trace_enabled": False,
    }
    # ── 코스피·코스닥 지수 (헤더 표시용) ──
    kospi = _latest_index.get("001")
    kosdaq = _latest_index.get("101")
    if kospi:
        st["kospi"] = {"price": kospi.get("price", 0), "change": kospi.get("change", 0), "rate": kospi.get("rate", 0)}
    if kosdaq:
        st["kosdaq"] = {"price": kosdaq.get("price", 0), "change": kosdaq.get("change", 0), "rate": kosdaq.get("rate", 0)}
    # ── 지수 폴링 상태 (헤더 표시용) ──
    from app.services import daily_time_scheduler as _dts
    st["index_polling"] = _dts._index_poll_timer_handle is not None
    # ── 장 상태 (index-refresh 수신 시 marketPhase 동기화용) ──
    st["market_phase"] = _dts.get_market_phase()
    return st
