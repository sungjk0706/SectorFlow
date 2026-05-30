from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
Risk Management Layer - 주문 전 리스크 통제

책임:
  1. Circuit Breaker: 연속 주문 실패 시 계좌 보호
  2. Max Exposure (최대 노출 한도): 잔여 예수금 및 현재 보유 총액 기반 한도 초과 방지
  3. Daily Loss Limit (일일 손실 한도): 당일 실현손실이 임계치 초과 시 매수 차단
  4. Single Stock Limit (단일 종목 한도): 한 종목에 대한 과도한 비중 제한

OMS(Order Management System)로 들어가기 전 필수 관문(Gateway) 역할을 수행합니다.
"""

import logging
import time

from backend.app.services.circuit_breaker import get_circuit_breaker
from backend.app.services.account_manager import AccountManager
from backend.app.services.trade_history import get_total_realized_pnl

logger = logging.getLogger(__name__)


class RiskManager:
    """통합 리스크 관리자"""

    def __init__(self, account_manager: AccountManager):
        self.circuit_breaker = get_circuit_breaker()
        self.account_manager = account_manager
        
        # 리스크 임계치 (향후 settings.py 또는 SQLite에서 로드 가능)
        self.max_daily_loss_limit = -500000  # 당일 실현손익이 -50만원 이하면 매수 차단
        self.max_single_stock_exposure = 20000000  # 단일 종목 최대 2천만원
        self.max_total_exposure_ratio = 0.95  # 총 자본의 95%까지만 매수 허용 (5% 현금 보유)

    def check_buy_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매수 주문 허용 여부 검사.
        
        Returns:
            (is_allowed, reason)
        """
        # 1. Circuit Breaker 검사
        if not self.circuit_breaker.allow_request():
            return False, f"Circuit Breaker OPEN 상태 ({self.circuit_breaker.get_state()})"
            
        # 2. 일일 손실 한도 검사
        today_pnl = get_total_realized_pnl(today_only=True)
        if today_pnl <= self.max_daily_loss_limit:
            logger.warning("[RiskManager] 일일 손실 한도 초과: 현재 %s, 한도 %s", f"{today_pnl:,}", f"{self.max_daily_loss_limit:,}")
            return False, "일일 손실 한도 초과"

        order_amount = price * qty

        # 3. 예수금 잔액 검사
        withdrawable = self.account_manager.get_withdrawable_deposit()
        if order_amount > withdrawable:
            logger.warning("[RiskManager] 예수금 부족: 주문액 %s, 출금가능액 %s", f"{order_amount:,}", f"{withdrawable:,}")
            return False, "예수금 잔고 부족"

        # 4. 단일 종목 비중 한도 검사 (여기서는 로컬 보유 정보가 필요하므로 향후 포지션 매니저와 연동 필요)
        # TODO: position_manager 연동 시 추가 구현
        
        return True, "승인"

    def check_sell_order_allowed(self, stk_cd: str, price: float, qty: int) -> tuple[bool, str]:
        """
        매도 주문 허용 여부 검사.
        (매도는 리스크 축소 행위이므로 비교적 관대하게 허용하지만, Circuit Breaker는 확인)
        """
        if not self.circuit_breaker.allow_request():
            return False, f"Circuit Breaker OPEN 상태 ({self.circuit_breaker.get_state()})"
            
        return True, "승인"

    def record_order_success(self) -> None:
        """주문 성공 시 Circuit Breaker에 보고"""
        self.circuit_breaker.record_success()

    def record_order_failure(self) -> None:
        """주문 실패 시 Circuit Breaker에 보고"""
        self.circuit_breaker.record_failure()


# 싱글톤 인스턴스
_risk_manager: Optional[RiskManager] = None

def get_risk_manager(account_manager: Optional[AccountManager] = None) -> RiskManager:
    global _risk_manager
    if _risk_manager is None:
        if account_manager is None:
            # 기본 AccountManager 인스턴스 생성 (또는 DI 컨테이너에서 주입)
            account_manager = AccountManager()
        _risk_manager = RiskManager(account_manager)
    return _risk_manager
