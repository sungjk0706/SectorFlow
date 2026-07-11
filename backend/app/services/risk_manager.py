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
from typing import Optional
import logging
from backend.app.services.circuit_breaker import get_circuit_breaker
from backend.app.services.trade_history import get_total_realized_pnl
from backend.app.core.trade_mode import is_test_mode
logger = logging.getLogger(__name__)


class RiskManager:
    """통합 리스크 관리자"""

    def __init__(self):
        self.circuit_breaker = get_circuit_breaker()
        self._sync_thresholds()

    def _sync_thresholds(self) -> None:
        """engine_state 설정 캐시에서 리스크 임계치 동기화."""
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        self.max_daily_loss_limit = int(cache.get("max_daily_loss_limit", -500000) or -500000)
        self.daily_loss_limit = int(
            cache.get("daily_loss_limit", self.max_daily_loss_limit) or self.max_daily_loss_limit
        )
        self.max_single_stock_exposure = int(cache.get("max_single_stock_exposure", 20000000) or 20000000)

    async def check_buy_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매수 주문 허용 여부 검사. 테스트/실전 모드 공통 호출.
        모드 분기는 돈 I/O(예수금·포지션 조회) 최소 지점에서만 수행 — 원칙 18.
        """
        self._sync_thresholds()

        # 1. 서킷브레이커 검사 (공통)
        if not self.circuit_breaker.allow_request():
            return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"

        # 2. 일일 손실 한도 검사 (공통 — trade_history에 모드 구분 있음)
        from backend.app.services.engine_state import state as engine_state
        cache = engine_state.integrated_system_settings_cache
        trade_mode = "test" if is_test_mode(cache) else "real"
        today_pnl = await get_total_realized_pnl(today_only=True, trade_mode=trade_mode)
        if today_pnl <= self.daily_loss_limit:
            logger.warning("[매매] 일일 손실 한도 초과: 현재 %s, 한도 %s", f"{today_pnl:,}", f"{self.daily_loss_limit:,}")
            return False, "일일 손실 한도 초과"

        order_amount = price * qty

        # 3. 예수금 잔액 검사 (모드 분기 — 돈 I/O)
        withdrawable = self.get_withdrawable_deposit()
        if order_amount > withdrawable:
            logger.warning("[매매] 예수금 부족: 주문액 %s, 출금가능액 %s", f"{order_amount:,}", f"{withdrawable:,}")
            return False, "예수금 잔고 부족"

        # 4. 단일 종목 비중 한도 검사 (모드 분기 — 돈 I/O)
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

    def check_sell_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매도 주문 허용 여부 검사.
        (매도는 리스크 축소 행위이므로 비교적 관대하게 허용하지만, 서킷브레이커는 확인)
        """
        if not self.circuit_breaker.allow_request():
            return False, f"서킷브레이커 차단 상태 ({self.circuit_breaker.get_state()})"
            
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
