# -*- coding: utf-8 -*-
"""
자동매매 실행 / 매도조건 판단
legacy_pc_engine/logic_auto_trade.py 이식 (설정은 get_settings_fn, PyQt5 제거)
"""
import asyncio
import time
import logging
from datetime import datetime

from backend.app.services import data_manager
from backend.app.services.auto_trading_effective import auto_buy_effective, auto_sell_effective
from backend.app.core.broker_factory import get_router
from backend.app.core import broker_registry
from backend.app.core.trade_mode import is_test_mode
from backend.app.core import journal as _journal
from backend.app.services import dry_run
from backend.app.services import trade_history
from backend.app.services.engine_symbol_utils import _base_stk_cd
from backend.app.services.risk_manager import get_risk_manager
from backend.app.core.constants import BUY_COMMISSION
from backend.app.domain.buy_filter import is_change_rate_blocked

logger = logging.getLogger(__name__)


# ── 매수 실패 사유코드 (P23 일관성 — buy_order_executor 소비) ──────────────
# 빈 문자열 = 성공
BUY_OK = ""

# 전체 차단 사유 (차순위 시도 무의미 → 루프 종료)
BUY_REJECT_DAILY_STATE = "daily_state"           # 일일 매수 상태 로드 실패
BUY_REJECT_REALTIME_LATENCY = "realtime_latency" # 실시간 지연 200ms 초과
BUY_REJECT_AUTO_BUY_OFF = "auto_buy_off"         # 자동매수 OFF (auto_buy_on=False)
BUY_REJECT_MASTER_OFF = "master_off"             # 자동매매 OFF (time_scheduler_on=False)
BUY_REJECT_BUY_TIME_OUT = "buy_time_out"         # 자동매수 시간외 (buy_time 범위 외)
BUY_REJECT_NON_TRADING_DAY = "non_trading_day"   # 휴일/주말 (비거래일)
BUY_REJECT_MAX_HOLDING = "max_holding"           # 최대 보유 종목 수 초과
BUY_REJECT_BUY_AMT_ZERO = "buy_amt_zero"         # 종목당 1회 매수금액 설정값 0
BUY_REJECT_DAILY_LIMIT = "daily_limit"           # 일일 매수 한도 초과
BUY_REJECT_RISK_CIRCUIT = "risk_circuit"         # 서킷브레이커 차단
BUY_REJECT_RISK_LOSS = "risk_loss"               # 일일 손실 한도 초과
BUY_REJECT_RISK_LOSS_RATE = "risk_loss_rate"     # 일일 손실률 한도 초과
BUY_REJECT_RISK_CONSEC_LOSS = "risk_consec_loss" # 연속 손실 한도 초과
BUY_REJECT_RISK_CASH = "risk_cash"               # 예수금 부족 (잔액 0)
BUY_REJECT_RISK_MARKET_DROP = "risk_market_drop" # 시장 지수 급락
BUY_REJECT_RISK_MARKET_DATA = "risk_market_data" # 시장 지수 자료 확인 불가
BUY_REJECT_TEST_CASH = "test_cash"               # 테스트 예수금 검증 실패
BUY_REJECT_ORDER_FAIL = "order_fail"             # 주문 전송 실패
BUY_REJECT_ORDER_BUSY = "order_busy"             # 주문 직렬화 잠금 점유 중 (다른 주문 처리 중)
BUY_REJECT_FILL_TIMEOUT = "fill_timeout"         # 주문 체결 응답 타임아웃 (접수 후 체결 응답 미수신)

# 종목별 차단 사유 (차순위 시도 유효 → continue)
BUY_REJECT_TIME_BLOCKED = "time_blocked"         # 체결 불가 시간대 (nxt 여부)
BUY_REJECT_REBUY = "rebuy"                       # 재매수 차단
BUY_REJECT_OPEN_ORDER = "open_order"             # 미체결 주문 존재
BUY_REJECT_SIGNAL_INTERVAL = "signal_interval"   # 30초 연속신호 차단
BUY_REJECT_PRICE_ZERO = "price_zero"             # 현재가 ≤ 0
BUY_REJECT_RISE_GUARD = "rise_guard"             # 등락률 상승 가드
BUY_REJECT_FALL_GUARD = "fall_guard"             # 등락률 하락 가드
BUY_REJECT_RISK_SINGLE = "risk_single"           # 단일 종목 비중 초과

# 조건부 사유 (buy_order_executor에서 잔액 재조회로 전체/종목별 판별)
BUY_REJECT_QTY_ZERO = "qty_zero"                 # buy_qty ≤ 0 (잔액 0이면 전체, 단가 비싸면 종목별)

# 전체 차단 사유 집합 (frozenset — P10 SSOT, 사유 분류의 단일 진실 소스)
BUY_GLOBAL_REJECT_REASONS: frozenset[str] = frozenset({
    BUY_REJECT_DAILY_STATE,
    BUY_REJECT_REALTIME_LATENCY,
    BUY_REJECT_AUTO_BUY_OFF,
    BUY_REJECT_MASTER_OFF,
    BUY_REJECT_BUY_TIME_OUT,
    BUY_REJECT_NON_TRADING_DAY,
    BUY_REJECT_MAX_HOLDING,
    BUY_REJECT_BUY_AMT_ZERO,
    BUY_REJECT_DAILY_LIMIT,
    BUY_REJECT_RISK_CIRCUIT,
    BUY_REJECT_RISK_LOSS,
    BUY_REJECT_RISK_LOSS_RATE,
    BUY_REJECT_RISK_CONSEC_LOSS,
    BUY_REJECT_RISK_CASH,
    BUY_REJECT_RISK_MARKET_DROP,
    BUY_REJECT_RISK_MARKET_DATA,
    BUY_REJECT_TEST_CASH,
    BUY_REJECT_ORDER_FAIL,
    BUY_REJECT_ORDER_BUSY,
    BUY_REJECT_FILL_TIMEOUT,
})

# ── 매수 차단 사유 → UI "원인" 컬럼 표시 텍스트 (P10 SSOT, P21 사용자 투명성) ──
# buy_order_executor에서 bt.reject_reason 설정 시 사용. 매핑 없음 = 표시 생략.
BUY_REJECT_REASON_TEXT: dict[str, str] = {
    BUY_REJECT_MAX_HOLDING:       "최대 보유종목 초과",
    BUY_REJECT_DAILY_LIMIT:       "일일 매수한도 초과",
    BUY_REJECT_BUY_AMT_ZERO:      "종목당 1회 매수금액 0",
    BUY_REJECT_RISK_CASH:         "예수금 부족",
    BUY_REJECT_DAILY_STATE:       "일일 상태 오류",
    BUY_REJECT_RISK_CIRCUIT:      "서킷브레이커",
    BUY_REJECT_RISK_LOSS:         "일일 손실 한도",
    BUY_REJECT_RISK_LOSS_RATE:    "일일 손실률 한도",
    BUY_REJECT_RISK_CONSEC_LOSS:  "연속 손실 한도",
    BUY_REJECT_RISK_MARKET_DROP:  "시장 지수 급락",
    BUY_REJECT_RISK_MARKET_DATA:  "시장 지수 자료 확인 불가",
    BUY_REJECT_RISK_SINGLE:       "단일 종목 비중 초과",
    BUY_REJECT_OPEN_ORDER:        "미체결 주문 존재",
    BUY_REJECT_SIGNAL_INTERVAL:   "연속신호 차단",
    BUY_REJECT_QTY_ZERO:          "매수수량 0",
    BUY_REJECT_ORDER_FAIL:        "주문 전송 실패",
    BUY_REJECT_ORDER_BUSY:        "주문 처리 중",
    BUY_REJECT_FILL_TIMEOUT:      "주문 응답 시간 초과",
    BUY_REJECT_TEST_CASH:         "테스트 잔고 부족",
    BUY_REJECT_AUTO_BUY_OFF:      "자동매수 OFF",
    BUY_REJECT_MASTER_OFF:        "자동매매 OFF",
    BUY_REJECT_BUY_TIME_OUT:      "자동매수 시간외",
    BUY_REJECT_NON_TRADING_DAY:   "휴일/주말",
    BUY_REJECT_REALTIME_LATENCY:  "실시간 지연",
    BUY_REJECT_TIME_BLOCKED:      "체결 불가 시간대",
    BUY_REJECT_REBUY:             "재매수 차단",
    BUY_REJECT_PRICE_ZERO:        "현재가 0",
    BUY_REJECT_RISE_GUARD:        "상승률 가드",
    BUY_REJECT_FALL_GUARD:        "하락률 가드",
}


def _map_risk_reason_to_code(risk_reason: str) -> str:
    """RiskManager 거부 사유 문자열 → 사유코드 매핑 (P23 일관성).

    알 수 없는 사유는 보수적으로 전체 차단 분류 (P20 폴백 금지 — 추정 아님, 보수적 차단).
    """
    if "서킷브레이커" in risk_reason:
        return BUY_REJECT_RISK_CIRCUIT
    if "일일 손실 한도" in risk_reason:
        return BUY_REJECT_RISK_LOSS
    if "일일 손실률 한도" in risk_reason:
        return BUY_REJECT_RISK_LOSS_RATE
    if "연속 손실 한도" in risk_reason:
        return BUY_REJECT_RISK_CONSEC_LOSS
    if "지수 자료 확인 불가" in risk_reason:
        return BUY_REJECT_RISK_MARKET_DATA
    if "시장 지수 급락" in risk_reason or "KOSPI 급락" in risk_reason or "KOSDAQ 급락" in risk_reason:
        return BUY_REJECT_RISK_MARKET_DROP
    if "예수금 부족" in risk_reason:
        return BUY_REJECT_RISK_CASH
    if "단일 종목 비중" in risk_reason:
        return BUY_REJECT_RISK_SINGLE
    logger.warning("[매매] RiskManager 알 수 없는 사유 — 전체 차단 분류: %s", risk_reason)
    return BUY_REJECT_RISK_CIRCUIT


def _fire_and_forget_telegram(message: str, settings: dict | None) -> None:
    """텔레그램 알림을 NotificationWorker 큐로 전송. 예외 격리."""
    try:
        from backend.app.services.notification_worker import NotificationWorker
        NotificationWorker.get_instance().enqueue({
            "type": "telegram",
            "message": message,
            "settings": settings,
        })
    except Exception as e:
        logger.warning("[알림] 알림 큐 등록 실패: %s", e, exc_info=True)


async def _broadcast_daily_buy_state_status(*, failed: bool) -> None:
    """일일 매수 상태 로드 성공/실패를 화면에 전송 (P21 사용자 투명성).

    매수 배지에 "차단: 일일 상태 오류" 반영 — 매수 전용 (매도는 해당 없음).
    P23(일관성): risk-block-status 브로드캐스트 패턴과 동일 (_safe_broadcast 사용).
    """
    try:
        from backend.app.services.engine_account_notify import _safe_broadcast
        await _safe_broadcast("daily-buy-state-status", {"failed": failed})
    except Exception:
        logger.warning("[매매] daily-buy-state-status 브로드캐스트 실패", exc_info=True)


async def _broadcast_test_cash_failed(*, stk_cd: str, reason: str) -> None:
    """테스트모드 예수금 검증 실패를 화면에 전송 (P21 사용자 투명성).

    사후 1회성 이벤트 — 매수상태 배지(지속 상태 전용)가 아닌 헤더 칩으로 알림.
    P23(일관성): _broadcast_daily_buy_state_status 패턴과 동일 (_safe_broadcast 사용).
    P18(테스트모드 동등성): 테스트모드 전용 사유이므로 실전모드에서는 호출되지 않음.
    """
    try:
        from backend.app.services.engine_account_notify import _safe_broadcast
        await _safe_broadcast("test-cash-failed", {"failed": True, "stk_cd": stk_cd, "reason": reason})
    except Exception:
        logger.warning("[매매] test-cash-failed 브로드캐스트 실패", exc_info=True)


async def _broadcast_circuit_breaker_recovered() -> None:
    """서킷브레이커 복구(HALF_OPEN → CLOSED) 시 헤더 칩 해제 (P21 사용자 투명성).

    서킷브레이커는 전용 스위치 없이 60초 후 자동 복구하므로, 복구 시점에 칩도 자동 해제.
    마스터 스위치 ON과 무관 — 서킷브레이커 상태 자체가 SSOT (P10).
    P23(일관성): circuit-breaker-open 브로드캐스트 패턴과 동일 (_safe_broadcast 사용).
    """
    try:
        from backend.app.services.engine_account_notify import _safe_broadcast
        await _safe_broadcast("circuit-breaker-open", {"message": ""})
    except Exception:
        logger.warning("[매매] circuit-breaker-open 해제 브로드캐스트 실패", exc_info=True)


async def _broadcast_test_cash_resolved() -> None:
    """테스트모드 매수 성공 시 잔고 부족 칩 해제 (P21 사용자 투명성).

    잔고 부족 상태가 해소되었으므로 칩도 자동 해제 — 수동 클릭 대기 불필요.
    P23(일관성): _broadcast_test_cash_failed 패턴과 동일 (_safe_broadcast 사용).
    P18(테스트모드 동등성): 테스트모드 전용 사유이므로 실전모드에서는 호출되지 않음.
    """
    try:
        from backend.app.services.engine_account_notify import _safe_broadcast
        await _safe_broadcast("test-cash-failed", {"failed": False})
    except Exception:
        logger.warning("[매매] test-cash-failed 해제 브로드캐스트 실패", exc_info=True)


async def _broadcast_order_fill_timeout(*, stk_cd: str, stk_nm: str, side: str) -> None:
    """주문 체결 응답 타임아웃을 화면에 전송 (P21 사용자 투명성, 결정 3).

    주문은 접수되었으나 체결 응답이 타임아웃 내 오지 않음 — 재시도 없이 알림 후 대기.
    P23(일관성): risk-block-status 브로드캐스트 패턴과 동일 (_safe_broadcast 사용).
    P18(테스트모드 동등성): 모드 무관 동일 동작.
    """
    try:
        from backend.app.services.engine_account_notify import _safe_broadcast
        _side_nm = "매수" if side.upper() == "BUY" else "매도"
        await _safe_broadcast("order-fill-timeout", {
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "side": _side_nm,
            "message": f"{stk_nm}({_base_stk_cd(stk_cd)}) {_side_nm} 주문 응답 시간 초과",
        })
    except Exception:
        logger.warning("[매매] order-fill-timeout 브로드캐스트 실패", exc_info=True)


async def _handle_order_failure() -> None:
    """주문 전송 실패 공통 후처리 — RiskManager 실패 보고 + 서킷브레이커 차단 시 마스터 스위치 강제 OFF.

    매수/매도 execute_* 주문 전송 실패 공통 후처리 (P24 중복 제거).
    record_order_failure() → circuit_breaker OPEN 시 time_scheduler_on=False +
    circuit-breaker-open 브로드캐스트 + header_refresh + settings_toggled + 에러 로그.
    P16(살아있는 경로): execute_buy/execute_sell 내부에서 호출.
    P18(테스트모드 동등성): 모드 무관 동일 동작.
    P25(격리된 실패): 리스크 매니저 실패 시 warning 로그 후 차단.
    """
    try:
        risk_mgr = get_risk_manager()
        risk_mgr.record_order_failure()
        # 서킷브레이커 차단 시 마스터 스위치 강제 OFF
        if risk_mgr.circuit_breaker.get_state() == "OPEN":
            from backend.app.services.engine_state import state
            from backend.app.services.engine_account_notify import _broadcast, notify_desktop_header_refresh, notify_desktop_settings_toggled
            state.integrated_system_settings_cache["time_scheduler_on"] = False
            await _broadcast("circuit-breaker-open", {
                "message": "서킷브레이커 차단 — 자동매매 마스터 스위치 강제 OFF",
            })
            await notify_desktop_header_refresh()
            await notify_desktop_settings_toggled({"time_scheduler_on": False})
            logger.error("[매매] 서킷브레이커 차단 — 자동매매 마스터 스위치 강제 OFF")
    except Exception:
        logger.warning("[매매] 리스크 관리자 실패 보고 실패", exc_info=True)


class AutoTradeManager:
    """자동매매 관리 - get_settings_fn으로 매번 최신 설정 로드."""

    def __init__(self, get_settings_fn=None):
        self.highest_prices: dict = {}
        self.get_settings_fn = get_settings_fn or (lambda: {})
        # ── 종목별 매도 설정 오버라이드 (기존 로직 유지) ────────────────────────
        self.ts_overrides: dict = {}
        # ────────────────────────────────────────────────────────────────────────
        self._recent_sells: set = set()  # 매도 주문 전송 완료 종목 — 체결/실패 확인까지 재주문 차단
        self._buy_state: dict = {}
        self._daily_buy_date: str = ""
        self._daily_buy_spent: int | None = None  # None = 로드 실패 (매수 차단)
        self._bought_today: dict[str, float] = {}  # stk_cd -> buy timestamp
        # ── 글로벌 주문 락: 매수·매도 공통 주문 직렬화 (한 번에 하나의 주문만 실행, P22) ──
        self._order_lock: asyncio.Lock | None = None
        # ── 체결 응답 대기: 주문 접수 후 체결·잔고 응답 수신까지 대기 (결정 2, P22 정합성) ──
        # 잠금은 체결 응답 수신 후 해제 — 한 번에 하나의 주문만 잔고에 영향.
        # _fill_event: 현재 대기 중인 주문의 체결 응답 이벤트 (잠금으로 1주문만 실행되므로 단일)
        # _fill_awaiting_cd: 대기 중인 주문의 종목코드 (on_fill_update에서 일치 시 이벤트 설정)
        self._fill_event: asyncio.Event | None = None
        self._fill_awaiting_cd: str | None = None

    async def _load_daily_buy_state(self) -> tuple[int | None, dict[str, float]]:
        """기동 시 trade_history에서 오늘 매수 합계 + 매수 종목 timestamp dict 로드.
        한도 체크 기준 = trade_history.total_amt (테스트: 수수료 포함 / 실전: 순수 매수가).
        실패 시 spent=None 반환 — 호출부에서 매수 차단."""
        try:
            rows = await trade_history.get_buy_history(today_only=True)
            # total_amt 사용 — trade_history.record_buy 공식과 단일 기준 (P10 SSOT, P22 정합성)
            spent = sum(int(r.get("total_amt", 0) or 0) for r in rows)
            bought_today: dict[str, float] = {}
            for r in rows:
                cd = str(r.get("stk_cd", "")).strip()
                if cd:
                    ts_str = r.get("ts") or r.get("date", "")
                    try:
                        ts_dt = datetime.fromisoformat(ts_str)
                        bought_today[cd] = ts_dt.timestamp()
                    except (ValueError, TypeError):
                        logger.warning("[매매] 일일 매수 상태 — %s 시각 해석 실패 (시각=%r), 해당 종목 건너뜀", cd, ts_str)
            return spent, bought_today
        except Exception:
            logger.critical("[매매] 일일 매수 상태 로드 실패 — 매수 차단 모드 진입: %s", exc_info=True)
            return None, {}

    async def _ensure_daily_buy_counter(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_buy_date != today:
            self._daily_buy_date = today
            self._daily_buy_spent, self._bought_today = await self._load_daily_buy_state()
            if self._daily_buy_spent is None:
                logger.critical(
                    "[매매] 일일 매수 상태 로드 실패 — 날짜=%s 매수 차단 모드 (trade_history 조회 실패)",
                    today,
                )
                # P21(사용자 투명성): 일일 매수 상태 로드 실패를 화면에 알림 — 매수 배지 "차단: 일일 상태 오류"
                await _broadcast_daily_buy_state_status(failed=True)
            else:
                logger.info(
                    "[매매] 일일 매수 상태 로드 — 날짜=%s 누적매수=%s원 종목수=%d",
                    today, f"{self._daily_buy_spent:,}", len(self._bought_today),
                )
                # P21: 로드 성공 시 차단 해제 알림 (이전 실패 상태가 화면에 남아있지 않도록)
                await _broadcast_daily_buy_state_status(failed=False)

    # ── 체결 응답 대기 (결정 2 — 주문 접수 후 체결·잔고 응답 수신까지 대기) ──────
    # 타임아웃: 키움 10초 / LS 15초 (결정 5 — 재시도 폐지 후 타임아웃은 알림 시점 기준)
    # 증권사별 값은 broker_registry.BROKER_TIMEOUTS에서 단일 관리 (P10).

    def _fill_timeout_for(self, settings: dict) -> float:
        """설정의 증권사별 체결 응답 타임아웃 반환 (P18 — 모드 무관 동일)."""
        broker = str(settings.get("broker", "") or "").lower()
        return broker_registry.BROKER_TIMEOUTS.get(broker, broker_registry.BROKER_TIMEOUT_DEFAULT)

    def _begin_fill_await(self, stk_cd: str) -> None:
        """체결 응답 대기 시작 — 이벤트 생성 (가상 체결 동기 호출 전 또는 실전 주문 전송 전 호출).

        반드시 가상 체결(fake_fill_event) 동기 호출 또는 실전 주문 전송 전에 호출.
        on_fill_update가 체결 응답 수신 시 self._fill_event.set() 호출.
        """
        self._fill_event = asyncio.Event()
        self._fill_awaiting_cd = _base_stk_cd(str(stk_cd))

    async def _end_fill_await(
        self, stk_cd: str, stk_nm: str, side: str, settings: dict,
    ) -> bool:
        """체결 응답 대기 완료 — 이벤트 대기 + 타임아웃 처리 (결정 2, P22 정합성).

        잠금 해제 시점을 체결 응답 수신 후로 이동 — 한 번에 하나의 주문만 잔고에 영향.
        테스트모드: 가상 체결 이벤트(fake_fill_event) → on_fill_update가 이벤트 설정.
        실전모드: 실시간 체결 이벤트(키움 "00" / LS 체결 채널) → on_fill_update가 이벤트 설정.
        타임아웃 시 사용자 알림(화면 + 텔레그램) 후 False 반환 (잠금은 호출자 try/finally로 해제).

        반환: True=체결 응답 수신, False=타임아웃 (사용자 알림 완료)
        """
        if self._fill_event is None:
            return True  # 대기 미시작 — 대기 없이 진행 (호출 순서 오류 안전 장치)
        timeout = self._fill_timeout_for(settings)
        try:
            await asyncio.wait_for(self._fill_event.wait(), timeout=timeout)
            logger.info("[매매] [체결응답] %s(%s) %s 체결 응답 수신 — 잠금 해제", stk_nm, stk_cd, side)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "[매매] [체결응답 타임아웃] %s(%s) %s — %s초 내 체결 응답 미수신. 알림 후 잠금 해제.",
                stk_nm, stk_cd, side, timeout,
            )
            _fire_and_forget_telegram(
                f"⚠️ [주문 응답 시간 초과] {stk_nm}({_base_stk_cd(stk_cd)}) {side} 주문 체결 응답이 {timeout}초 내 오지 않았습니다.",
                settings,
            )
            await _broadcast_order_fill_timeout(stk_cd=stk_cd, stk_nm=stk_nm, side=side)
            return False
        finally:
            self._fill_event = None
            self._fill_awaiting_cd = None

    async def execute_buy(self, stk_cd: str, current_price: float,
                    access_token: str, reason: str = "") -> tuple[bool, str]:
        """
        매수 주문 실행 (글로벌 주문 락으로 직렬화 — 즉시 시도, 점유 시 차단).
        reason: 매수 사유 (체결 이력 기록용 — 가산점 통합 문자열).
        반환값: (True, "")=주문 전송 성공, (False, 사유코드)=가드에 의해 차단/실패
        결정 6: 잠금이 이미 점유 중이면 대기하지 않고 즉시 차단 반환 (다음 평가 주기 재시도).
        """
        if self._order_lock is None:
            self._order_lock = asyncio.Lock()
        if self._order_lock.locked():
            logger.info("[매매] [매수차단] %s 주문 처리 중 — 즉시 차단 (다음 주기 재시도)", stk_cd)
            return False, BUY_REJECT_ORDER_BUSY
        await self._order_lock.acquire()
        try:
            return await self._execute_buy_locked(stk_cd, current_price, access_token, reason)
        finally:
            self._order_lock.release()

    async def _execute_buy_locked(self, stk_cd: str, current_price: float,
                    access_token: str, reason: str = "") -> tuple[bool, str]:
        """
        매수 주문 실행 본문 (글로벌 주문 락 내부 — 매수·매도 공통 직렬화).
        TOCTOU 경쟁 상태 방지: reserve_buy_power로 검증+즉시 차감을 원자적 수행.
        반환값: (True, "")=주문 전송 성공, (False, 사유코드)=가드에 의해 차단/실패
        """
        settings = self._to_trade_settings(self.get_settings_fn())
        raw_all = self.get_settings_fn()
        await self._ensure_daily_buy_counter()

        # ── 일일 매수 상태 로드 실패 시 매수 차단 (P20 폴백 금지) ──────────────
        if self._daily_buy_spent is None:
            logger.critical("[매매] [매수차단] %s 일일 매수 상태 로드 실패 — 매수 불가", stk_cd)
            return False, BUY_REJECT_DAILY_STATE

        # ── 실시간 지연 중단 게이트 (fail-closed — P20/P25 안전 우선) ──────────
        # 체크 자체가 실패하면 매수 차단: 지연 상태를 확인할 수 없는 상황은
        # 시스템 장애이므로 안전 차단이 합리적 (지연 중단 게이트 의도 존중).
        try:
            from backend.app.services.engine_state import state as engine_state
            if engine_state.realtime_latency_exceeded:
                logger.info("[매매] [실시간지연] %s 매수 차단 — 실시간 통신 지연 200ms 초과", stk_cd)
                return False, BUY_REJECT_REALTIME_LATENCY
        except Exception:
            logger.warning("[매매] [매수차단] 실시간 지연 체크 실패 — 안전 차단 (fail-closed)", exc_info=True)
            return False, BUY_REJECT_REALTIME_LATENCY

        # 스케줄 자동매매 게이트: 자동매매 비활성화 시 주문 생략
        if not settings["is_auto"]:
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            logger.info("[매매] [자동매매 비활성화] %s(%s) 주문 생략 (출처=자동신호)", stk_nm, stk_cd)
            return False, BUY_REJECT_AUTO_BUY_OFF
        # ── 체결 불가 시간대 주문 게이트 (P15 단일 경로, P16 살아있는 경로) ──
        if self._is_order_time_blocked(stk_cd):
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            logger.info("[매매] [주문차단] %s(%s) 체결 불가 시간대 — 동시호가/장외", stk_nm, stk_cd)
            return False, BUY_REJECT_TIME_BLOCKED
        # ── 재매수 차단 (설정 기반: ON/OFF + 차단 기간) ──────────────────────
        rebuy_block_on = bool(settings.get("rebuy_block_on", True))
        if rebuy_block_on:
            rebuy_period = str(settings.get("rebuy_block_period", "today"))
            last_buy_ts = self._bought_today.get(stk_cd)
            if last_buy_ts is not None:
                if rebuy_period == "today":
                    logger.info("[매매] [매수차단] %s 오늘 이미 매수한 종목입니다.", stk_cd)
                    return False, BUY_REJECT_REBUY
                else:
                    _period_hours = float(rebuy_period.rstrip("h")) if rebuy_period.endswith("h") else 24.0
                    _elapsed = time.time() - last_buy_ts
                    if _elapsed < _period_hours * 3600:
                        _remain_min = int((_period_hours * 3600 - _elapsed) / 60)
                        logger.info("[매매] [매수차단] %s 재매수 차단 중 (남은 %d분 / 차단 %.0f시간)", stk_cd, _remain_min, _period_hours)
                        return False, BUY_REJECT_REBUY

        state = self._buy_state.get(stk_cd, {"last_req_ts": 0.0, "has_open_buy": False})
        last_ts = float(state.get("last_req_ts", 0) or 0)
        has_open_buy = bool(state.get("has_open_buy", False))
        now = time.time()
        MIN_INTERVAL = 30.0

        if has_open_buy:
            logger.info("[매매] [매수차단] %s 매수 주문이 이미 처리 중입니다.", stk_cd)
            return False, BUY_REJECT_OPEN_ORDER
        if now - last_ts < MIN_INTERVAL:
            logger.info("[매매] [연속신호 차단] %s 연속 신호 감지. 차단.", stk_cd)
            return False, BUY_REJECT_SIGNAL_INTERVAL

        # ── 실제 잔고 보유종목 수 기준으로 최대보유종목수 체크 ─────────────
        # 테스트모드: 모의투자 가상 잔고 / 실전투자: 키움 실제 잔고
        # max_stock_cnt_on=False → 제한 없음 (사용자 선택)
        max_limit = settings["max_limit"]
        max_limit_on = bool(raw_all.get("max_stock_cnt_on", True))
        from backend.app.services.engine_account import get_positions as _get_positions
        _positions_for_count = await _get_positions()
        holding_count = sum(
            1 for p in _positions_for_count
            if int(p.get("qty", 0)) > 0
        )
        if max_limit_on and holding_count >= max_limit:
            logger.info("[매매] [매수제한] 잔고 보유종목 %d종목 ≥ 최대 %d종목. %s 매수 차단.", holding_count, max_limit, stk_cd)
            return False, BUY_REJECT_MAX_HOLDING

        # ── 종목당 1회 매수금액 (buy_amt_on=False → 한도 없음) ──
        buy_amt_on = bool(raw_all.get("buy_amt_on", True))
        buy_amt = settings.get("buy_amt", 0)
        max_daily_total = int(settings.get("max_daily_total_buy_amt", 0) or 0)
        max_daily_on = bool(settings.get("max_daily_total_buy_on", False))
        if buy_amt_on:
            if buy_amt <= 0:
                return False, BUY_REJECT_BUY_AMT_ZERO
            # ── 종목당 1회 매수금액 (재매수 차단은 rebuy_block_on이 담당) ──
            # 일일 한도 내에서 실제 사용 가능 금액 계산 (잔여 한도가 종목당 1회 매수금액보다 적으면 잔여 한도만큼만 매수)
            if max_daily_on and max_daily_total > 0:
                daily_remain = max(0, max_daily_total - self._daily_buy_spent)
                if daily_remain <= 0:
                    logger.info("[매매] [일일매수한도] %s 차단. 잔여 0원 / 한도 %s원", stk_cd, f"{max_daily_total:,}")
                    return False, BUY_REJECT_DAILY_LIMIT
                effective_buy_amt = min(int(buy_amt), daily_remain)
            else:
                effective_buy_amt = int(buy_amt)
        else:
            # buy_amt_on=False → 종목당 1회 매수금액 없음, 일일 한도만 적용
            if max_daily_on and max_daily_total > 0:
                daily_remain = max(0, max_daily_total - self._daily_buy_spent)
                if daily_remain <= 0:
                    logger.info("[매매] [일일매수한도] %s 차단. 잔여 0원 / 한도 %s원", stk_cd, f"{max_daily_total:,}")
                    return False, BUY_REJECT_DAILY_LIMIT
                effective_buy_amt = daily_remain
            else:
                # 한도 없음 — 주문가능 금액이 실제 상한 (아래 _orderable 체크에서 산출)
                effective_buy_amt = None

        if current_price <= 0:
            logger.info("[매매] [매수제한] %s 서버 현재가 미수신(<=0). 주문 차단.", stk_cd)
            return False, BUY_REJECT_PRICE_ZERO

        # ── 등락률 + 거래대금 가드 (설정값 기반) ──────────────────────────────
        # 단일 소스 진리: master_stocks_cache에서 직접 읽기
        from backend.app.services.engine_state import state

        # 등락률 가드 — is_change_rate_blocked() 단일 판정 소스 (P10 SSOT, W3 중복 제거)
        # 이중 게이트 의도 보존 (설계서 5-7): 후보 생성 시점(apply_buy_block_guards)과
        # 주문 직전(execute_buy) 양쪽 차단 판정 유지 — 등락률 변동 방어.
        _change_rate = state.master_stocks_cache.get(stk_cd, {}).get("change_rate")
        if _change_rate is not None:
            _blocked, _block_kind = is_change_rate_blocked(
                _change_rate,
                block_rise_on=bool(raw_all.get("buy_block_rise_on", True)),
                block_rise_pct=float(raw_all.get("buy_block_rise_pct", 7.0)),
                block_fall_on=bool(raw_all.get("buy_block_fall_on", True)),
                block_fall_pct=float(raw_all.get("buy_block_fall_pct", -7.0)),
            )
            if _blocked:
                _block_reason = f"{_block_kind} {_change_rate:+.1f}%"
                _reject_code = (
                    BUY_REJECT_RISE_GUARD if _block_kind == "상승률" else BUY_REJECT_FALL_GUARD
                )
                stk_nm_g = data_manager.get_stock_name(stk_cd, access_token)
                logger.info("[매매] [등락률가드] %s(%s) 등락률 %s — 매수 차단", stk_nm_g, stk_cd, _block_reason)
                return False, _reject_code

        # ── 주문가능 금액 내에서 최대한 매수 (buy_amt는 한도, 의무 지출액 아님) ──
        _orderable = get_risk_manager().get_withdrawable_deposit()
        # effective_buy_amt=None → 종목당 1회 매수금액 없음 → 주문가능 금액이 상한
        _max_available = min(effective_buy_amt, _orderable) if effective_buy_amt is not None else _orderable
        _est_buy_price = dry_run.estimate_fill_price(int(current_price), "BUY") if is_test_mode(raw_all) else int(current_price)
        # 수수료 여유분 확보 (P10 SSOT — reserve_buy_power의 cost 공식과 정합, P22 정합성)
        from backend.app.services import settlement_engine
        buy_qty = settlement_engine.max_buy_qty_for_budget(
            _est_buy_price, _max_available, is_test_mode(raw_all),
        )
        if buy_qty <= 0:
            return False, BUY_REJECT_QTY_ZERO

        # 시장가 단일 운용
        trde_tp = "3"
        order_price = 0
        order_type = "시장가"

        # ── RiskManager 게이트 (테스트/실전 공통 — 모드 분기는 RiskManager 내부에서 처리) ──
        risk_mgr = get_risk_manager()
        _allowed, _risk_reason = await risk_mgr.check_buy_order_allowed(
            stk_cd, float(current_price), buy_qty
        )
        if not _allowed:
            _reason_code = _map_risk_reason_to_code(_risk_reason)
            logger.info("[매매] [리스크차단] %s 매수 차단 — %s (사유코드=%s)", stk_cd, _risk_reason, _reason_code)
            # 시장 가드는 리스크 매니저가 상태 전환 시에만 알림·화면 상태를 전송한다.
            # 종목별·기타 리스크 사유는 기존 주문 경로 알림을 유지한다.
            _market_reject_codes = {BUY_REJECT_RISK_MARKET_DROP, BUY_REJECT_RISK_MARKET_DATA}
            if _reason_code not in _market_reject_codes:
                _blocked_stk_nm = data_manager.get_stock_name(stk_cd, access_token)
                _fire_and_forget_telegram(
                    f"🛑 [리스크차단] {_blocked_stk_nm}({stk_cd}) 매수 차단 — {_risk_reason}",
                    self.get_settings_fn(),
                )
                from backend.app.services.engine_account_notify import _safe_broadcast
                await _safe_broadcast("risk-block-status", {
                    "blocked": True,
                    "side": "buy",
                    "reason": _risk_reason,
                })
            return False, _reason_code

        self._buy_state[stk_cd] = {"last_req_ts": now, "has_open_buy": True}
        stk_nm = data_manager.get_stock_name(stk_cd, access_token)

        logger.info("[매매] [매수주문] %s(%s) 매수신호 감지. %s %d주 주문전송.", stk_nm, stk_cd, order_type, buy_qty)
        _fire_and_forget_telegram(f"🚀 [자동매매] {stk_nm} {buy_qty}주 매수 주문 전송.", self.get_settings_fn())

        # ── 테스트모드: 예수금 검증 + 즉시 차감 (TOCTOU 경쟁 상태 방지, P22) ────
        _reserved_cost: int = 0
        if is_test_mode(raw_all):
            from backend.app.services.engine_strategy_core import reserve_test_buy_power
            _check_price = int(order_price) if order_price > 0 else int(current_price)
            _check_price = dry_run.estimate_fill_price(_check_price, "BUY")
            ok, _reject_reason, _reserved_cost = await reserve_test_buy_power(
                _check_price, buy_qty, self._daily_buy_spent,
            )
            if not ok:
                logger.info("[매매] 매수 거부: %s (%s)", stk_cd, _reject_reason)
                self._buy_state[stk_cd]["has_open_buy"] = False
                # P21(사용자 투명성): 테스트 예수금 검증 실패를 화면에 알림 — 헤더 칩 "⚠ 테스트 잔고 부족"
                await _broadcast_test_cash_failed(stk_cd=stk_cd, reason=_reject_reason)
                return False, BUY_REJECT_TEST_CASH

        # ── 테스트모드 가드: 테스트모드면 실전 서버에 절대 주문 안 보냄 ─────────
        if is_test_mode(raw_all):
            _dry_price = int(order_price) if order_price > 0 else int(current_price)
            res = await dry_run.fake_send_order(
                raw_all, access_token, "BUY", stk_cd, buy_qty, _dry_price, trde_tp,
            )
            await dry_run.set_stock_name(stk_cd, stk_nm)
        else:
            res = await get_router().order.send_order(raw_all, access_token, "BUY", stk_cd, buy_qty, int(order_price), trde_tp)

        if not (res and res.get("success")):
            self._buy_state[stk_cd]["has_open_buy"] = False
            logger.info("[매매] [매수실패] %s 주문 전송 실패. 잠금 해제.", stk_nm)
            _fire_and_forget_telegram(f"⚠️ [매수실패] {stk_nm}({stk_cd}) 주문 전송 실패. 잠금 해제.", raw_all)
            # ── 사전 차감 롤백 (주문 실패 시 정합성 보장, P22) ──
            if _reserved_cost > 0:
                await settlement_engine.release_buy_power(_reserved_cost)
                _reserved_cost = 0
            await _handle_order_failure()
            return False, BUY_REJECT_ORDER_FAIL

        # ── 체결 응답 대기 시작 (결정 2 — 가상 체결 예약/WS 응답 전에 이벤트 생성) ──
        self._begin_fill_await(stk_cd)

        # ── 저널링: 주문 요청 기록 ─────────────────────────────────────────────
        order_id = res.get("order_id", f"buy_{stk_cd}_{int(time.time())}")
        _mode = "test" if is_test_mode(raw_all) else "real"
        await _journal.record_order_request(
            order_id=order_id,
            stock_code=stk_cd,
            side="buy",
            quantity=buy_qty,
            price=float(order_price) if order_price > 0 else float(current_price),
            trade_mode=_mode,
        )

        fill_price = int(order_price) if order_price > 0 else int(current_price)
        if is_test_mode(raw_all):
            fill_price = dry_run.estimate_fill_price(fill_price, "BUY")
        # 일일 누적 한도 기준 = trade_history.record_buy의 total_amt 공식과 동일 (P10/P22)
        # 테스트모드: 수수료 포함 / 실전모드: 순수 매수가 (P18 — 실전은 증권사 서버가 SSOT, 앱 수수료 계산 금지)
        _base = int(buy_qty * fill_price)
        _fee = round(_base * BUY_COMMISSION) if is_test_mode(raw_all) else 0
        spent = _base + _fee
        self._daily_buy_spent += max(0, spent)

        # ── 매수 성공 즉시 _bought_today 반영 (테스트/실전 공통 — 원칙 18 동등성) ──
        if stk_cd not in self._bought_today:
            self._bought_today[stk_cd] = time.time()
            logger.info("[매매] [매수기억] %s 주문 성공! 금일 매수 이력 저장.", stk_nm)

        # ── 체결 이력 기록 ────────────────────────────────────────────────────
        # P20(폴백 금지): reason은 buy_order_executor가 가산점 통합 문자열로 명시 전달.
        # 가산점 미발생 시 빈 문자열 그대로 저장 (자동매수 폴백 제거).
        _mode = "test" if is_test_mode(raw_all) else "real"
        await trade_history.record_buy(
            stk_cd=stk_cd, stk_nm=stk_nm,
            price=fill_price, qty=buy_qty,
            reason=reason, trade_mode=_mode,
        )

        # ── 매수 한도 상태 WS 브로드캐스트 (account-update보다 선행) ────────
        # buy-limit-status가 먼저 전송되어 uiStore.buyLimitStatus가 갱신된 후,
        # account-update가 hotStore를 갱신할 때 updateBadges()가 최신 daily_buy_spent 사용
        try:
            from backend.app.services.engine_account import _broadcast_buy_limit_status
            await _broadcast_buy_limit_status()
        except Exception:
            logger.warning("[매매] 매수 한도 전송 실패", exc_info=True)

        # ── 테스트모드: 가상 체결 동기 대기 (실전 WS "00"과 동일한 downstream, P18 동등성) ──
        # 주문 흐름 내에서 가상 체결 완료까지 대기 — "주문 → 대기 → 응답 → 다음" 흐름 (결정 4).
        # fake_fill_event 내부에서 on_fill_update가 _fill_event를 설정 → _end_fill_await가 즉시 통과.
        if is_test_mode(raw_all):
            _dry_fill_price = int(order_price) if order_price > 0 else int(current_price)
            await dry_run.fake_fill_event("BUY", stk_cd, buy_qty, _dry_fill_price, stk_nm, pre_reserved=True)

        t_str = datetime.now().strftime("%H:%M:%S")
        fmt_price = f"{fill_price:,}"
        logger.info(
            "[매매] [%s] [매수주문] %s | %s | %s주 | 단가: %s원 | 일일누적매수 %s원",
            t_str, stk_nm, order_type, f"{buy_qty:,}", fmt_price, f"{self._daily_buy_spent:,}",
        )

        # ── RiskManager 성공 보고 ─────────────────────────────────────────────
        try:
            risk_mgr = get_risk_manager()
            prev_state = risk_mgr.circuit_breaker.get_state()
            risk_mgr.record_order_success()
            new_state = risk_mgr.circuit_breaker.get_state()
            if prev_state == "HALF_OPEN" and new_state == "CLOSED":
                logger.info("[매매] 서킷브레이커 복구 — 복구시도 → 정상")
                _fire_and_forget_telegram("✅ [OMS] 서킷브레이커 복구 완료 — 주문 정상 작동 재개", self.get_settings_fn())
                await _broadcast_circuit_breaker_recovered()
        except Exception:
            logger.warning("[매매] 리스크 관리자 성공 보고 실패", exc_info=True)

        # ── 테스트모드 매수 성공 시 잔고 부족 칩 해제 (P21) ──
        if is_test_mode(raw_all):
            await _broadcast_test_cash_resolved()

        # ── 체결·잔고 응답 대기 (결정 2 — 잠금 해제 시점을 체결 응답 후로 이동) ──
        # 테스트모드: 가상 체결(fake_fill_event) → on_fill_update가 이벤트 설정.
        # 실전모드: WS "00" 체결 이벤트 → on_fill_update가 이벤트 설정.
        # 타임아웃 시 사용자 알림 후 차단 반환 — 주문은 접수되었으나 체결 미확정 (P21 투명성).
        _fill_ok = await self._end_fill_await(stk_cd, stk_nm, "매수", raw_all)
        if not _fill_ok:
            return False, BUY_REJECT_FILL_TIMEOUT

        return True, BUY_OK

    async def on_fill_update(
        self, stk_cd: str, side: str, unex_qty: int, access_token: str | None = None
    ) -> None:
        nk = _base_stk_cd(str(stk_cd or ""))
        state = self._buy_state.get(stk_cd, {"last_req_ts": 0.0, "has_open_buy": False})
        state["last_req_ts"] = time.time()
        try:
            unex = int(unex_qty)
        except (ValueError, TypeError):
            logger.warning("[매매] [체결업데이트] %s 미체결수량 해석 실패 (원본=%r) — 체결 처리 중단", stk_cd, unex_qty)
            self._buy_state[stk_cd] = state
            return

        if str(side) == "1" and unex == 0:
            state["has_open_buy"] = False
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            logger.info("[매매] [매수체결] %s 체결 확인!", stk_nm)
            _fire_and_forget_telegram(
                f"✅ [매수체결] {stk_nm}({stk_cd}) 매수 체결!",
                self.get_settings_fn(),
            )
        elif str(side) == "2" and unex == 0:
            # 매도 체결 완료 — 재매도 차단 해제
            self._recent_sells.discard(nk)
            stk_nm = data_manager.get_stock_name(stk_cd, access_token)
            logger.info("[매매] [매도체결] %s(%s) 매도 체결!", stk_nm, stk_cd)
            _fire_and_forget_telegram(
                f"💰 [매도체결] {stk_nm}({stk_cd}) 매도 체결!",
                self.get_settings_fn(),
            )
        elif str(side) in ("3", "4"):
            state["has_open_buy"] = False
        self._buy_state[stk_cd] = state

        # ── 체결 응답 대기 이벤트 설정 (결정 2 — 잠금 해제 시점을 체결 응답 후로) ──
        # 전량 체결(side 1/2, unex=0) 또는 취소·거부(side 3/4) 시 대기 중인 주문이면 이벤트 설정.
        # 종목코드 일치 시에만 설정 — 다른 종목의 체결 응답으로 오해 방지 (P22 정합성).
        _is_fill_done = (str(side) in ("1", "2") and unex == 0) or str(side) in ("3", "4")
        if _is_fill_done and self._fill_event is not None and self._fill_awaiting_cd == nk:
            self._fill_event.set()

    async def execute_sell(
        self,
        stk_cd: str,
        cur_price: float,
        stk_nm: str,
        reason: str,
        qty: int,
        pnl_rate: float,
        trade_settings: dict,
        base_settings: dict,
        access_token: str,
    ) -> bool:
        """trade_settings: _to_trade_settings (is_sell_mkt 등). base_settings: engine_settings (kiwoom/telegram용).

        반환: True=주문 전송 성공, False=차단/실패 (check_sell_conditions에서 건별 간격 적용에 사용).
        결정 1·6: 글로벌 주문 락으로 매수·매도 공통 직렬화 — 즉시 시도, 점유 시 차단 반환.
        """
        if not trade_settings.get("is_sell_auto", False):
            return False
        if self._order_lock is None:
            self._order_lock = asyncio.Lock()
        if self._order_lock.locked():
            logger.info("[매매] [매도차단] %s(%s) 주문 처리 중 — 즉시 차단 (다음 주기 재시도)", stk_nm, stk_cd)
            return False
        await self._order_lock.acquire()
        try:
            return await self._execute_sell_locked(
                stk_cd, cur_price, stk_nm, reason, qty, pnl_rate,
                trade_settings, base_settings, access_token,
            )
        finally:
            self._order_lock.release()

    async def _execute_sell_locked(
        self,
        stk_cd: str,
        cur_price: float,
        stk_nm: str,
        reason: str,
        qty: int,
        pnl_rate: float,
        trade_settings: dict,
        base_settings: dict,
        access_token: str,
    ) -> bool:
        """매도 주문 실행 본문 (글로벌 주문 락 내부 — 매수·매도 공통 직렬화).

        반환: True=주문 전송 성공, False=차단/실패.
        """
        # ── 체결 불가 시간대 주문 게이트 — 매도 동일 적용 (P15/P16) ──
        if self._is_order_time_blocked(stk_cd):
            logger.info("[매매] [주문차단] %s(%s) 체결 불가 시간대 — 매도 중단", stk_nm, stk_cd)
            return False
        # 시장가 단일 운용
        order_type = "시장가"

        logger.info("[매매] [매도주문] %s %s. %s %d주 (단가: 시장가)", stk_nm, reason, order_type, qty)
        _fire_and_forget_telegram(f"[자동매매] {stk_nm}({stk_cd}) {reason} 발동! {qty}주 매도 전송.", base_settings)

        trde_tp = "3"
        order_price = 0  # 시장가
        self._recent_sells.add(stk_cd)

        # ── 평균매입가를 주문 전에 미리 조회 (주문 후 포지션 삭제되면 조회 불가) ──
        # P18 참고: 테스트/실전 분기는 "조회"이며 돈 I/O가 아님. 엄격 해석상 미세 위반 소지
        # 있으나 현행 유지 — 테스트모드는 build_positions_from_trades로 유령 포지션
        # 차단 검사(qty 부족 시 매도 중단)를 수행하는 안전장치이므로 분기가 의도적.
        # 실전모드는 get_positions()로 브로커 잔고를 직접 조회.
        _mode = "test" if is_test_mode(base_settings) else "real"
        _avg_buy = 0
        _buy_date = ""
        try:
            if _mode == "test":
                from backend.app.services import trade_history
                _computed = await trade_history.build_positions_from_trades("test")
                _computed_pos = _computed.get(_base_stk_cd(stk_cd))
                if not _computed_pos or int(_computed_pos.get("qty", 0)) < qty:
                    logger.critical(
                        "[매매] trades 기준 포지션 없음/수량 부족 — %s 매도 중단 (유령 포지션 차단)",
                        stk_cd,
                    )
                    _fire_and_forget_telegram(
                        f"⚠️ [매도중단] {stk_nm}({stk_cd}) trades에 매수 기록 없음 — 유령 포지션 의심",
                        base_settings,
                    )
                    return False
                _avg_buy = int(_computed_pos.get("avg_price", 0))
                _buy_date = str(_computed_pos.get("buy_date", "") or "")
            else:
                from backend.app.services.engine_account import get_positions as _get_positions
                for _p in await _get_positions():
                    if _base_stk_cd(str(_p.get("stk_cd", ""))) == stk_cd:
                        _avg_buy = int(_p.get("avg_price", 0))
                        _buy_date = str(_p.get("buy_date", "") or "")
                        break
        except Exception:
            logger.warning("[매매] 평균 매수가 조회 실패", exc_info=True)

        # ── 테스트모드 가드: 테스트모드면 실전 서버에 절대 주문 안 보냄 ─────────
        if is_test_mode(base_settings):
            _dry_sell_price = int(order_price) if order_price > 0 else int(cur_price)
            result = await dry_run.fake_send_order(
                base_settings, access_token, "SELL", stk_cd, qty, _dry_sell_price, trde_tp,
            )
        else:
            result = await get_router().order.send_order(base_settings, access_token, "SELL", stk_cd, qty, int(order_price), trde_tp)

        if not result.get("success"):
            self._recent_sells.discard(stk_cd)
            logger.info("[매매] [매도] %s 주문 전송 실패: %s", stk_nm, result.get('msg', '알 수 없음'))
            _fire_and_forget_telegram(f"⚠️ [매도실패] {stk_nm}({stk_cd}) 주문 전송 실패: {result.get('msg', '알 수 없음')}", base_settings)
            await _handle_order_failure()
            return False

        # ── 체결 응답 대기 시작 (결정 2 — 가상 체결 예약/WS 응답 전에 이벤트 생성) ──
        self._begin_fill_await(stk_cd)

        # ── 매도 주문 전송 성공 — 간격 타이머 갱신 (P22: 실제 실행만 기록) ──
        from backend.app.services.order_interval import mark_order_executed
        mark_order_executed("sell")

        # ── 저널링: 주문 요청 기록 ─────────────────────────────────────────────
        order_id = result.get("order_id", f"sell_{stk_cd}_{int(time.time())}")
        await _journal.record_order_request(
            order_id=order_id,
            stock_code=stk_cd,
            side="sell",
            quantity=qty,
            price=float(order_price) if order_price > 0 else float(cur_price),
            trade_mode=_mode,
        )

        t_str = datetime.now().strftime("%H:%M:%S")
        logger.info("[매매] [%s] [매도주문] %s | %s | %s | %s주 | 평가손익: %s%%", t_str, stk_nm, reason, order_type, f"{qty:,}", pnl_rate)

        # ── 체결 이력 기록 ────────────────────────────────────────────────────
        _sell_price = int(order_price) if order_price > 0 else int(cur_price)
        if _mode == "test":
            _sell_price = dry_run.estimate_fill_price(_sell_price, "SELL")
        await trade_history.record_sell(
            stk_cd=stk_cd, stk_nm=stk_nm,
            price=_sell_price, qty=qty,
            avg_buy_price=_avg_buy, reason=reason,
            pnl_rate=pnl_rate, trade_mode=_mode,
            buy_date=_buy_date,
        )

        # ── 테스트모드: 가상 체결 동기 대기 (실전 WS "00"과 동일한 downstream, P18 동등성) ──
        # 주문 흐름 내에서 가상 체결 완료까지 대기 — "주문 → 대기 → 응답 → 다음" 흐름 (결정 4).
        # fake_fill_event 내부에서 on_fill_update가 _fill_event를 설정 → _end_fill_await가 즉시 통과.
        if is_test_mode(base_settings):
            _dry_sell_price = int(order_price) if order_price > 0 else int(cur_price)
            await dry_run.fake_fill_event("SELL", stk_cd, qty, _dry_sell_price, stk_nm)

        # ── RiskManager 성공 보고 ─────────────────────────────────────────────
        try:
            risk_mgr = get_risk_manager()
            prev_state = risk_mgr.circuit_breaker.get_state()
            risk_mgr.record_order_success()
            new_state = risk_mgr.circuit_breaker.get_state()
            if prev_state == "HALF_OPEN" and new_state == "CLOSED":
                logger.info("[매매] 서킷브레이커 복구 — 복구시도 → 정상")
                _fire_and_forget_telegram("✅ [OMS] 서킷브레이커 복구 완료 — 주문 정상 작동 재개", self.get_settings_fn())
                await _broadcast_circuit_breaker_recovered()
        except Exception:
            logger.warning("[매매] 리스크 관리자 성공 보고 실패", exc_info=True)

        # ── 체결·잔고 응답 대기 (결정 2 — 잠금 해제 시점을 체결 응답 후로 이동) ──
        # 테스트모드: 가상 체결(fake_fill_event) → on_fill_update가 이벤트 설정.
        # 실전모드: WS "00" 체결 이벤트 → on_fill_update가 이벤트 설정.
        # 타임아웃 시 사용자 알림 후 차단 반환 — 주문은 접수되었으나 체결 미확정 (P21 투명성).
        _fill_ok = await self._end_fill_await(stk_cd, stk_nm, "매도", base_settings)
        if not _fill_ok:
            return False

        return True  # 매도 주문 전송 성공

    async def check_sell_conditions(self, stock_list: list, base_settings: dict, access_token: str) -> None:
        """매도 조건 순회 — 1건 매도 성공 후 루프 종료 (건별 간격 적용).

        sell_interval_on 시 사용자 설정 간격(초) 대기 — 매도 1건마다 간격 적용 (P21 UI 일치).
        매도 성공 시 break — 다음 check_sell_conditions 호출 시 check_order_interval이 간격 판정.
        매도 실패 시 continue — 차순위 종목 시도.
        """
        settings = self._to_trade_settings(base_settings)
        if not settings.get("is_sell_auto", False):
            return

        # ── 실시간 지연 중단 게이트 (fail-closed — P20/P25 안전 우선) ──────────
        # 체크 자체가 실패하면 매도 차단: 지연 상태를 확인할 수 없는 상황은
        # 시스템 장애이므로 안전 차단이 합리적 (매수 게이트와 동일 정책, P23 일관성).
        try:
            from backend.app.services.engine_state import state as engine_state
            if engine_state.realtime_latency_exceeded:
                logger.info("[매매] [실시간지연] 매도 조건 전체 차단 — 실시간 통신 지연 200ms 초과")
                return
        except Exception:
            logger.warning("[매매] [매도차단] 실시간 지연 체크 실패 — 안전 차단 (fail-closed)", exc_info=True)
            return

        # ── RiskManager 매도 차단 체크 ───────────────────────────────────
        try:
            risk_mgr = get_risk_manager()
            allowed, reason = await risk_mgr.check_sell_order_allowed("", 0, 0)
            if not allowed:
                logger.info("[매매] [리스크차단] 매도 조건 전체 차단 — %s", reason)
                # P21 사용자 투명성 — 차단 사유 텔레그램 알림 + WS 브로드캐스트
                _fire_and_forget_telegram(
                    f"🛑 [리스크차단] 매도 전체 차단 — {reason}",
                    base_settings,
                )
                from backend.app.services.engine_account_notify import _safe_broadcast
                await _safe_broadcast("risk-block-status", {
                    "blocked": True,
                    "side": "sell",
                    "reason": reason,
                })
                return
        except Exception:
            logger.warning("[매매] 리스크 관리자 체크 실패 — 매도 전체 중단", exc_info=True)
            return

        # ── 매도 주문 간격 게이트 (토글 ON 시, 건별 적용) ───────────────
        from backend.app.services.order_interval import check_order_interval
        if not check_order_interval(base_settings, "sell"):
            return

        for stock in stock_list:
            s = dict(settings)
            stk_cd = _base_stk_cd(str(stock.get("stk_cd", "") or ""))
            stk_nm = stock.get("stk_nm", "")
            if not stk_cd:
                continue
            # 매도 주문 전송 완료 종목 — 재주문 차단
            if stk_cd in self._recent_sells:
                continue

            cur_price_raw = stock.get("cur_price")
            pnl_rate_raw = stock.get("pnl_rate")
            # 시세 미수신(cur_price/pnl_rate None) — 평가 불가, 매도 조건 검사 스킵 (P25 격리된 실패)
            if cur_price_raw is None or pnl_rate_raw is None:
                logger.debug(
                    "시세 미수신 — 매도 조건 평가 스킵 stk_cd=%s stk_nm=%s",
                    stk_cd, stk_nm,
                )
                continue
            cur_price = float(str(cur_price_raw).replace(",", ""))
            qty = int(str(stock.get("qty", 0)).replace(",", ""))
            pnl_rate = float(pnl_rate_raw)
            # 서버 손익값만 사용: 표준 키(pnl_amount) 우선, 하위 호환 키(pnl_amt) 보조.
            # NOTE: 아래 `or 0`은 폴백이 아님 — pnl_rate is None인 종목은 위 가드에서 continue되어
            # 이 줄에 도달 불가. 도달한 종목은 cur_price/pnl_rate가 모두 非-None이므로 pnl_amount도 非-None.
            # 나중에 "여기도 폴백이 남아있다"고 오해하여 재수정하지 말 것 (P20 위반 아님).
            pnl_amt = float(stock.get("pnl_amount", stock.get("pnl_amt", 0)) or 0)

            override = self.ts_overrides.get(stk_cd, {}) if isinstance(self.ts_overrides, dict) else {}
            if override:
                for key in (
                    "tp_val", "tp_apply",
                    "ts_start_val", "ts_drop_val",
                    "ts_apply", "loss_apply",
                    "sell_custom_qty", "sell_qty_type", "loss_val",
                ):
                    if override.get(key) is not None:
                        s[key] = override[key]
                if override.get("order_type") in ("시장가", "지정가"):
                    s["is_sell_mkt"] = override["order_type"] == "시장가"
                tp_v = float(s.get("tp_val") or 0)
                s["chk_tp"] = bool(s.get("tp_apply", True)) and tp_v > 0
                s["chk_loss"] = bool(s.get("loss_apply"))
                s["chk_ts"] = bool(s.get("ts_apply"))

            if qty <= 0:
                continue
            custom_qty = s.get("sell_custom_qty", 0)
            custom_type = s.get("sell_qty_type", "%")
            sell_qty = max(1, int(qty * (custom_qty / 100.0))) if custom_type == "%" and custom_qty > 0 else min(qty, custom_qty) if custom_qty > 0 else qty

            if stk_cd not in self.highest_prices or pnl_rate > self.highest_prices[stk_cd]["pnl_rate"]:
                self.highest_prices[stk_cd] = {"price": cur_price, "pnl_rate": pnl_rate, "pnl_amt": pnl_amt}

            max_reached = self.highest_prices[stk_cd]
            highest_price = max_reached["price"]

            if s.get("chk_loss", False):
                loss_val = float(s.get("loss_val") or 0)
                hit_sl = pnl_rate <= loss_val
                if hit_sl:
                    try:
                        _sold = await self.execute_sell(stk_cd, cur_price, stk_nm, "손절 발동", sell_qty, pnl_rate, s, base_settings, access_token)
                    except Exception:
                        logger.error("[매매] 손절 실행 실패", exc_info=True)
                        _sold = False
                    if _sold:
                        logger.debug("[매매] 매도 1건 — 주문 간격 대기")
                        break  # 1건 매도 성공 — 건별 간격 적용
                    continue  # 실패 시 차순위

            if s.get("chk_tp", False):
                tp_val = float(s.get("tp_val") or 0)
                hit_tp = pnl_rate >= tp_val
                if hit_tp:
                    try:
                        _sold = await self.execute_sell(stk_cd, cur_price, stk_nm, "익절 발동", sell_qty, pnl_rate, s, base_settings, access_token)
                    except Exception:
                        logger.error("[매매] 익절 실행 실패", exc_info=True)
                        _sold = False
                    if _sold:
                        logger.debug("[매매] 매도 1건 — 주문 간격 대기")
                        break  # 1건 매도 성공 — 건별 간격 적용
                    continue  # 실패 시 차순위

            if s.get("chk_ts", False):
                ts_start_val = float(s.get("ts_start_val") or 0)
                ts_drop_val = float(s.get("ts_drop_val") or 0)

                if max_reached["pnl_rate"] >= ts_start_val:
                    drop_rate = ((cur_price - highest_price) / highest_price * 100) if highest_price > 0 else 0
                    if drop_rate <= ts_drop_val:
                        try:
                            _sold = await self.execute_sell(stk_cd, cur_price, stk_nm, "T/S 익절", sell_qty, pnl_rate, s, base_settings, access_token)
                        except Exception:
                            logger.error("[매매] T/S 익절 실행 실패", exc_info=True)
                            _sold = False
                        if _sold:
                            logger.debug("[매매] 매도 1건 — 주문 간격 대기")
                            break  # 1건 매도 성공 — 건별 간격 적용
                        continue  # 실패 시 차순위

    def _is_order_time_blocked(self, stk_cd: str) -> bool:
        """체결 불가 시간대 주문 게이트 헬퍼 (시간 판별).

        동기 함수 — 시간 계산만 수행 (P1-P3 async 일관성 위반 아님).
        P15(단일 주문 경로): execute_buy/execute_sell 내부에서만 호출.
        """
        from backend.app.services.daily_time_scheduler import is_order_blocked_by_time
        return is_order_blocked_by_time(stk_cd)

    def _to_trade_settings(self, raw: dict) -> dict:
        """engine_settings 형식을 logic_auto_trade 호환 형식으로 변환."""
        r = raw
        tp_val = float(r["tp_val"])
        tp_on = bool(r["tp_apply"])
        return {
            "is_auto": auto_buy_effective(r),
            "is_sell_auto": auto_sell_effective(r),
            "max_limit": int(r["max_stock_cnt"]),
            "max_limit_on": bool(r.get("max_stock_cnt_on", True)),
            "buy_amt": int(r["buy_amt"]),
            "buy_amt_on": bool(r.get("buy_amt_on", True)),
            "max_daily_total_buy_on": bool(r.get("max_daily_total_buy_on", False)),
            "max_daily_total_buy_amt": int(r["max_daily_total_buy_amt"]),
            "rebuy_block_on": bool(r.get("rebuy_block_on", True)),
            "rebuy_block_period": str(r.get("rebuy_block_period", "today")),
            "is_sell_mkt": r["sell_price_type"] == "mkt",
            "sell_offset": int(r["sell_offset"]),
            "sell_custom_qty": int(r["sell_custom_qty"]),
            "sell_qty_type": r["sell_qty_type"],
            "tp_val": tp_val,
            "tp_apply": tp_on,
            "chk_tp": tp_on and tp_val > 0,
            "chk_loss": bool(r["loss_apply"]),
            "loss_val": float(r["loss_val"]),
            "ts_apply": bool(r["ts_apply"]),
            "chk_ts": bool(r["ts_apply"]),
            "ts_start_val": float(r["ts_start_val"]),
            "ts_drop_val": float(r["ts_drop_val"]),
        }

