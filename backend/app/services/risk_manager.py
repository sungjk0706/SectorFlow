# -*- coding: utf-8 -*-
"""
Risk Management Layer - 주문 전 리스크 통제

책임:
  1. 서킷브레이커: 연속 주문 실패 시 계좌 보호
  2. Max Exposure (최대 노출 한도): 잔여 예수금 및 현재 보유 총액 기반 한도 초과 방지
  3. Daily Loss Limit (일일 손실 한도): 당일 실현손실이 임계치 초과 시 매수 차단
  4. Single Stock Limit (단일 종목 한도): 한 종목에 대한 과도한 비중 제한

OMS(Order Management System)로 들어가기 전 필수 관문(Gateway) 역할을 수행합니다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import logging
from backend.app.services.circuit_breaker import get_circuit_breaker
from backend.app.services.trade_history import get_total_realized_pnl
from backend.app.core.trade_mode import is_test_mode
logger = logging.getLogger(__name__)


RISK_REJECT_MARKET_DROP = "risk_market_drop"
RISK_REJECT_MARKET_DATA = "risk_market_data"

MARKET_KOSPI = "0"
MARKET_KOSDAQ = "10"
_MARKET_DISPLAY_NAMES = {
    MARKET_KOSPI: "코스피",
    MARKET_KOSDAQ: "코스닥",
}


def normalize_market_type(market_type: str | None) -> str:
    """종목 시장 구분을 리스크 가드의 표준 코드로 정규화."""
    value = str(market_type or "").strip().upper()
    if value in (MARKET_KOSPI, "KOSPI", "코스피", "KS"):
        return MARKET_KOSPI
    if value in (MARKET_KOSDAQ, "KOSDAQ", "코스닥", "KQ"):
        return MARKET_KOSDAQ
    return ""


def get_market_guard_reason(market_type: str | None, status: "MarketGuardStatus") -> str:
    """시장 가드 상태에서 특정 종목에 적용할 차단 사유를 반환."""
    normalized = normalize_market_type(market_type)
    if normalized:
        return status.blocked_markets.get(normalized, "")
    if status.blocked_markets:
        return "시장 구분 확인 불가"
    return ""


def is_market_guard_reason(reason: str) -> bool:
    return reason.startswith((
        "코스피 급락 차단",
        "코스닥 급락 차단",
        "코스피 지수 자료 확인 불가",
        "코스닥 지수 자료 확인 불가",
        "시장 구분 확인 불가",
    ))


@dataclass(frozen=True)
class MarketGuardStatus:
    """매수 시장 가드의 현재 상태와 상태 전환 여부."""

    allowed: bool
    reason: str = ""
    reason_code: str = ""
    changed: bool = False
    blocked_markets: dict[str, str] = field(default_factory=dict)


def _notify_telegram(
    message: str,
    settings: dict | None,
    dedup_key: str | None = None,
) -> None:
    """텔레그램 알림을 NotificationWorker 큐로 전송. 예외 격리."""
    try:
        from backend.app.services.notification_worker import NotificationWorker
        msg = {
            "type": "telegram",
            "message": message,
            "settings": settings,
        }
        if dedup_key:
            msg["dedup_key"] = dedup_key
        NotificationWorker.get_instance().enqueue(msg)
    except Exception as e:
        logger.warning("[리스크] 텔레그램 알림 큐 등록 실패: %s", e, exc_info=True)


class RiskManager:
    """통합 리스크 관리자"""

    def __init__(self):
        self.circuit_breaker = get_circuit_breaker()
        self._active_market_block: dict[str, str | None] = {"buy": None, "sell": None}
        self._sync_thresholds()

    def _sync_thresholds(self) -> None:
        """engine_state 설정 캐시에서 리스크 임계치 동기화."""
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        self.daily_loss_limit = int(cache.get("daily_loss_limit", -500000) or -500000)
        self.max_single_stock_exposure = int(cache.get("max_single_stock_exposure", 20000000) or 20000000)
        # 신규 — 리스크 매니저 확장 (P13 메모리 상주)
        self.risk_manager_on = bool(cache.get("risk_manager_on", False))
        self.daily_loss_limit_on = bool(cache.get("daily_loss_limit_on", True))
        self.daily_loss_rate_limit_on = bool(cache.get("daily_loss_rate_limit_on", False))
        self.daily_loss_rate_limit = float(cache.get("daily_loss_rate_limit", -5.0) or -5.0)
        self.risk_block_buy_on = bool(cache.get("risk_block_buy_on", True))
        self.risk_block_sell_on = bool(cache.get("risk_block_sell_on", False))
        self.consecutive_loss_limit_on = bool(cache.get("consecutive_loss_limit_on", False))
        self.consecutive_loss_limit = int(cache.get("consecutive_loss_limit", 3) or 3)
        # 시장 지수 급락 가드 (P13 메모리 상주) — KOSPI/KOSDAQ 개별 토글이 독립 제어
        # 매수/매도 차단 여부는 기존 risk_block_buy_on/risk_block_sell_on 재사용
        self.market_guard_kospi_on = bool(cache.get("market_guard_kospi_on", False))
        self.market_guard_kospi_drop_threshold_pct = float(cache.get("market_guard_kospi_drop_threshold_pct", -5.0) or -5.0)
        self.market_guard_kosdaq_on = bool(cache.get("market_guard_kosdaq_on", False))
        self.market_guard_kosdaq_drop_threshold_pct = float(cache.get("market_guard_kosdaq_drop_threshold_pct", -5.0) or -5.0)

    async def _get_consecutive_loss_count(self, trade_mode: str) -> int:
        """최근 매도 거래 기준 연속 손실 횟수 반환.

        trade_history.get_sell_history()는 DESC 정렬(최신순).
        최신 매도부터 역순으로 realized_pnl < 0인 거래가 연속 몇 건인지 카운트.
        매도 이력이 없거나 최신 거래가 수익이면 0 반환.
        """
        from backend.app.services.trade_history import get_sell_history
        rows = await get_sell_history(trade_mode=trade_mode)
        count = 0
        for r in rows:
            pnl = int(r.get("realized_pnl", 0) or 0)
            if pnl < 0:
                count += 1
            else:
                break  # 연속 손실 끊김
        return count

    async def _check_extended_buy_risk(self, trade_mode: str, today_pnl: int) -> tuple[bool, str]:
        """신규 리스크 조건 검사 (risk_manager_on + risk_block_buy_on 시에만 호출).

        기존 일일 손실 한도/예수금/단일 종목 비중은 check_buy_order_allowed 본문에서
        항상 실행되므로 여기서는 신규 4개 조건만 검사.
        반환: (allowed, reason) — allowed=False 시 차단 사유.
        """
        from backend.app.services.trade_history import get_buy_history
        buy_rows = await get_buy_history(today_only=True, trade_mode=trade_mode)
        today_principal = sum(int(r.get("price", 0) or 0) * int(r.get("qty", 0) or 0) for r in buy_rows)

        # 1. 일일 손실률 한도
        if self.daily_loss_rate_limit_on and today_principal > 0:
            today_pnl_rate = today_pnl / today_principal * 100
            if today_pnl_rate <= self.daily_loss_rate_limit:
                logger.warning("[매매] 일일 손실률 한도 초과: 현재 %.2f%%, 한도 %.2f%%", today_pnl_rate, self.daily_loss_rate_limit)
                # P21 사용자 투명성 — 손실률 차단 상태 알림
                from backend.app.services.engine_state import state as engine_state
                _notify_telegram(
                    f"🛑 [자동매매 중단] 일일 손실률 한도 도달 — 당일 손실률 {today_pnl_rate:.2f}%, 한도 {self.daily_loss_rate_limit:.2f}%. 자동매매가 중단된 상태입니다.",
                    engine_state.integrated_system_settings_cache,
                )
                return False, "일일 손실률 한도 초과"

        # 2. 연속 손실 횟수
        if self.consecutive_loss_limit_on:
            consec_count = await self._get_consecutive_loss_count(trade_mode)
            if consec_count >= self.consecutive_loss_limit:
                logger.warning("[매매] 연속 손실 한도 초과: 현재 %d회, 한도 %d회", consec_count, self.consecutive_loss_limit)
                return False, f"연속 손실 한도 초과 ({consec_count}회)"

        return True, ""

    @staticmethod
    def _buy_market_data_required() -> bool:
        """현재 시간대에 KRX 지수 자료가 매수 가드에 필요한지 반환."""
        try:
            from backend.app.services.daily_time_scheduler import is_nxt_only_window
            return not is_nxt_only_window()
        except Exception:
            logger.warning("[리스크] 시장 시간대 확인 실패 — 지수 자료를 요구하는 안전 경로 적용", exc_info=True)
            return True

    def _collect_market_guard_blocks(self, *, require_data: bool = True) -> dict[str, str]:
        """KOSPI/KOSDAQ 시장 가드 결과를 시장별로 수집.

        한 시장의 차단이 다른 시장의 주문을 막지 않도록 결과를 모두 보존한다.
        """
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.index_data_cache
        checks = (
            (MARKET_KOSPI, "코스피", "001", self.market_guard_kospi_on, self.market_guard_kospi_drop_threshold_pct),
            (MARKET_KOSDAQ, "코스닥", "301", self.market_guard_kosdaq_on, self.market_guard_kosdaq_drop_threshold_pct),
        )
        blocked: dict[str, str] = {}
        for market_type, name, upcode, enabled, threshold in checks:
            if not enabled:
                continue
            index_data = cache.get(upcode)
            if not index_data:
                if require_data:
                    blocked[market_type] = f"{name} 지수 자료 확인 불가"
                else:
                    logger.debug("[리스크] %s 지수 자료 없음 — NXT 전용 시간대라 매수 가드 자료 부재 허용", name)
                continue
            try:
                drate = float(str(index_data.get("drate", "") or "").strip())
            except (ValueError, TypeError):
                if require_data:
                    logger.warning("[리스크] %s 등락률 변환 불가 — 해당 시장 매수 가드 차단: %r", name, index_data.get("drate"), exc_info=True)
                    blocked[market_type] = f"{name} 지수 자료 확인 불가"
                else:
                    logger.debug("[리스크] %s 등락률 변환 불가 — NXT 전용 시간대라 매수 가드 자료 부재 허용", name)
                continue
            if drate <= threshold:
                blocked[market_type] = f"{name} 급락 차단"
        return blocked

    def _check_market_drop(self, *, require_data: bool = True) -> tuple[bool, str]:
        """시장 지수 급락 가드의 호환용 요약 결과를 반환."""
        blocked = self._collect_market_guard_blocks(require_data=require_data)
        reason = next(iter(blocked.values()), "")
        return not blocked, reason

    @staticmethod
    def is_market_guard_reason(reason: str) -> bool:
        return is_market_guard_reason(reason)

    @staticmethod
    def _market_reason_code(reason: str) -> str:
        if "지수 자료 확인 불가" in reason or "시장 구분 확인 불가" in reason:
            return RISK_REJECT_MARKET_DATA
        if "급락" in reason:
            return RISK_REJECT_MARKET_DROP
        return ""

    @staticmethod
    def _format_market_block_summary(blocked_markets: dict[str, str], side: str) -> str:
        """시장별 차단과 매수 가능 시장을 함께 보여주는 요약 문구."""
        order_word = "매수" if side == "buy" else "매도"
        parts = []
        for market_type in (MARKET_KOSPI, MARKET_KOSDAQ):
            name = _MARKET_DISPLAY_NAMES[market_type]
            parts.append(blocked_markets.get(market_type, f"{name} {order_word} 가능"))
        return " · ".join(parts)

    async def _publish_market_block_state(
        self,
        side: str,
        blocked_markets: dict[str, str],
    ) -> bool:
        """시장별 가드 상태가 바뀐 경우에만 UI 갱신.

        로그·텔레그램은 차단↔해제 전환 시에만 출력 — 차단 상태가 유지되는 동안
        사유만 바뀌는 것(예: 급락 차단 ↔ 자료 확인 불가)은 노이즈이므로 건너뛴다.
        브로드캐스트는 사유 변경도 화면에 반영하도록 항상 전송.
        """
        active = tuple(sorted(blocked_markets.items())) or None
        active_blocks = getattr(self, "_active_market_block", {"buy": None, "sell": None})
        previous = active_blocks.get(side)
        if previous == active:
            return False
        active_blocks[side] = active
        self._active_market_block = active_blocks

        # 전환 여부 — 차단↔해제 경계를 넘을 때만 True (사유만 바뀐 차단→차단은 False)
        transitioned = bool(previous) != bool(active)

        from backend.app.services.engine_account_notify import _safe_broadcast
        if not blocked_markets:
            await _safe_broadcast("risk-block-status", {"blocked": False, "side": side})
            if transitioned and previous:
                logger.info("[매매] 시장 지수 가드 해제 — %s 주문을 다시 확인합니다.", side)
                _notify_telegram(
                    f"✅ [자동매매 재개] 시장 지수 가드 해제 — {side} 주문을 다시 확인합니다.",
                    self._settings_cache(),
                    dedup_key=f"risk-{side}-market-recovered",
                )
        else:
            reason = self._format_market_block_summary(blocked_markets, side)
            partial = side == "buy" and len(blocked_markets) < 2
            if transitioned:
                logger.warning("[매매] 시장 지수 가드 차단 상태 변경 — %s", reason)
                _notify_telegram(
                    f"🛑 [리스크차단] {side} 주문 차단 — {reason}",
                    self._settings_cache(),
                    dedup_key=f"risk-{side}-market-{active}",
                )
            await _safe_broadcast("risk-block-status", {
                "blocked": True,
                "side": side,
                "reason": reason,
                "partial": partial,
                "blocked_markets": list(blocked_markets.keys()),
            })
        return True

    def clear_market_block_state(self, side: str) -> None:
        """설정으로 차단이 해제된 경우 상태 전환 기준을 초기화."""
        active_blocks = getattr(self, "_active_market_block", {"buy": None, "sell": None})
        active_blocks[side] = None
        self._active_market_block = active_blocks

    @staticmethod
    def _settings_cache() -> dict:
        from backend.app.services.engine_state import state as engine_state
        return engine_state.integrated_system_settings_cache

    @classmethod
    def _get_stock_market_type(cls, stk_cd: str) -> str:
        from backend.app.services.engine_symbol_utils import get_stock_market
        return normalize_market_type(get_stock_market(stk_cd))

    async def check_buy_market_guard(self) -> MarketGuardStatus:
        """매수 후보와 주문 직전에서 공유하는 시장별 가드 상태."""
        self._sync_thresholds()
        blocked_markets = {} if not self.risk_block_buy_on else self._collect_market_guard_blocks(
            require_data=self._buy_market_data_required(),
        )
        reason = " / ".join(blocked_markets.values())
        changed = await self._publish_market_block_state("buy", blocked_markets)
        return MarketGuardStatus(
            allowed=not blocked_markets,
            reason=reason,
            reason_code=self._market_reason_code(next(iter(blocked_markets.values()), "")),
            changed=changed,
            blocked_markets=blocked_markets,
        )

    def get_buy_market_block_reason(
        self,
        market_type: str | None,
        status: MarketGuardStatus,
    ) -> str:
        """시장 상태에서 특정 종목에 적용할 매수 차단 사유를 반환."""
        return get_market_guard_reason(market_type, status)

    async def check_buy_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매수 주문 허용 여부 검사. 테스트/실전 모드 공통 호출.
        모드 분기는 돈 I/O(예수금·포지션 조회) 최소 지점에서만 수행 — 원칙 18.

        기존 체크(일일 손실 한도/예수금/단일 종목 비중)는 항상 실행.
        신규 조건(손실률/수익/수익률/연속손실)은 risk_manager_on + risk_block_buy_on 시에만 실행.
        """
        self._sync_thresholds()

        # 1. 서킷브레이커 검사 (공통 — 항상 동작)
        if not self.circuit_breaker.allow_request():
            return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"

        # 2. 일일 손실 한도 검사 (기본 관문 — daily_loss_limit_on ON 시에만, 기본 ON)
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        trade_mode = "test" if is_test_mode(cache) else "real"
        today_pnl = await get_total_realized_pnl(today_only=True, trade_mode=trade_mode)
        if self.daily_loss_limit_on and today_pnl <= self.daily_loss_limit:
            logger.warning("[매매] 일일 손실 한도 초과: 현재 %s, 한도 %s", f"{today_pnl:,}", f"{self.daily_loss_limit:,}")
            # P21 사용자 투명성 — 자동매매 중단 상태 텔레그램 알림 (매 건 전송)
            _notify_telegram(
                f"🛑 [자동매매 중단] 일일 손실 한도 도달 — 당일 손실 {today_pnl:,}원, 한도 {self.daily_loss_limit:,}원. 자동매매가 중단된 상태입니다.",
                cache,
            )
            return False, "일일 손실 한도 초과"

        # 3. 신규 리스크 조건 (risk_manager_on + risk_block_buy_on 시에만)
        if self.risk_manager_on and self.risk_block_buy_on:
            allowed, reason = await self._check_extended_buy_risk(trade_mode, today_pnl)
            if not allowed:
                return False, reason

        # 3-1. 시장 지수 급락 가드 — 주문 종목의 시장만 적용
        if self.risk_block_buy_on:
            market_status = await self.check_buy_market_guard()
            market_reason = self.get_buy_market_block_reason(
                self._get_stock_market_type(stk_cd),
                market_status,
            )
            if market_reason:
                return False, market_reason
        else:
            await self._publish_market_block_state("buy", {})

        order_amount = price * qty

        # 4. 예수금 잔액 검사 (모드 분기 — 돈 I/O, 항상 실행)
        withdrawable = self.get_withdrawable_deposit()
        if order_amount > withdrawable:
            logger.warning("[매매] 예수금 부족: 주문액 %s, 출금가능액 %s", f"{order_amount:,}", f"{withdrawable:,}")
            return False, "예수금 잔고 부족"

        # 5. 단일 종목 비중 한도 검사 (모드 분기 — 돈 I/O, 항상 실행)
        existing_position_amount = 0
        if is_test_mode(cache):
            from backend.app.services import dry_run
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            pos = await dry_run.get_position(stk_cd)
            if pos:
                existing_position_amount = int(pos.get("buy_amount", 0) or 0)
        else:
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            nk = _base_stk_cd(stk_cd)
            for p in engine_state.positions:
                if _base_stk_cd(str(p.get("stk_cd", "") or "")) == nk:
                    existing_position_amount = int(p.get("buy_amount", 0) or 0)
                    break
        total_after_buy = existing_position_amount + order_amount
        if self.max_single_stock_exposure > 0 and total_after_buy > self.max_single_stock_exposure:
            logger.warning("[매매] 단일 종목 비중 초과: %s 기존 %s + 주문 %s = %s, 한도 %s",
                           stk_cd, f"{existing_position_amount:,}", f"{order_amount:,}", f"{total_after_buy:,}", f"{self.max_single_stock_exposure:,}")
            return False, f"단일 종목 비중 한도 초과 ({stk_cd})"

        return True, "승인"

    def get_withdrawable_deposit(self) -> int:
        """주문 가능한 예수금/가용금액을 모드에 따라 반환.

        - 테스트모드: settlement_engine.get_available_cash()
        - 실전모드: account_snapshot['orderable']
        """
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        if is_test_mode(cache):
            from backend.app.services.settlement_engine import get_available_cash
            return get_available_cash()
        return int(engine_state.account_snapshot.get("orderable", 0) or 0)

    async def check_sell_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매도 주문 허용 여부 검사.

        매도는 리스크 축소 행위이지만, 사용자가 risk_block_sell_on 활성화 시
        수익/손실 한도 도달 시 매도도 차단 가능.
        서킷브레이커는 항상 동작 (계좌 보호 최소 안전장치).
        """
        self._sync_thresholds()

        # 1. 서킷브레이커 (항상 동작)
        if not self.circuit_breaker.allow_request():
            return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"

        # 2. 신규 매도 리스크 조건 (risk_manager_on + risk_block_sell_on 시에만)
        if self.risk_manager_on and self.risk_block_sell_on:
            from backend.app.services.engine_state import state as engine_state
            cache = engine_state.integrated_system_settings_cache
            trade_mode = "test" if is_test_mode(cache) else "real"
            today_pnl = await get_total_realized_pnl(today_only=True, trade_mode=trade_mode)

            # 일일 손실 한도 (매도 차단 시 손실 확대 위험 — daily_loss_limit_on ON 시에만)
            if self.daily_loss_limit_on and today_pnl <= self.daily_loss_limit:
                return False, "일일 손실 한도 초과 (매도 차단)"

            from backend.app.services.trade_history import get_buy_history
            buy_rows = await get_buy_history(today_only=True, trade_mode=trade_mode)
            today_principal = sum(int(r.get("price", 0) or 0) * int(r.get("qty", 0) or 0) for r in buy_rows)

            # 일일 손실률 한도
            if self.daily_loss_rate_limit_on and today_principal > 0:
                today_pnl_rate = today_pnl / today_principal * 100
                if today_pnl_rate <= self.daily_loss_rate_limit:
                    return False, "일일 손실률 한도 초과 (매도 차단)"

            # 연속 손실 횟수
            if self.consecutive_loss_limit_on:
                consec_count = await self._get_consecutive_loss_count(trade_mode)
                if consec_count >= self.consecutive_loss_limit:
                    return False, f"연속 손실 한도 초과 (매도 차단, {consec_count}회)"

        # 2-1. 시장 지수 급락 가드 (risk_block_sell_on 시에만)
        if self.risk_block_sell_on:
            blocked_markets = self._collect_market_guard_blocks(require_data=False)
            reason = next(iter(blocked_markets.values()), "")
            await self._publish_market_block_state("sell", blocked_markets)
            if reason:
                return False, f"{reason} (매도 차단)"
        else:
            await self._publish_market_block_state("sell", {})

        return True, "승인"

    def record_order_success(self) -> None:
        """주문 성공 시 서킷브레이커에 보고"""
        self.circuit_breaker.record_success()

    def record_order_failure(self) -> None:
        """주문 실패 시 서킷브레이커에 보고"""
        self.circuit_breaker.record_failure()


# 싱글톤 인스턴스
_risk_manager: Optional[RiskManager] = None

def get_risk_manager() -> RiskManager:
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager
