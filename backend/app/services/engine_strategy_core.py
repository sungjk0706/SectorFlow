# -*- coding: utf-8 -*-
"""
매수 파이프라인 핵심 로직: 시장가 즉시 매수, 모니터링 종목 등록, 스냅샷·매도 검사, 실시간 통신 연결 시도.

engine_service 모듈의 전역 상태에 get_state/set_state로 접근한다.
"""
from __future__ import annotations
import logging
from backend.app.services import settlement_engine
from backend.app.services.engine_state import state
logger = logging.getLogger(__name__)


def make_detail(stk_cd: str, stk_nm: str, cur_price: int,
                 sign: str, change: int, change_rate: float,
                 trade_amount: int = 0, strength: str = "-", sector: str = "미분류") -> dict:
    """대기 종목 상세 딕셔너리 생성 헬퍼."""
    return {
        "code":        stk_cd,
        "name":        stk_nm if stk_nm else stk_cd,
        "cur_price":   cur_price,
        "sign":        sign,        # "1"상한 "2"상승 "3"보합 "4"하한 "5"하락
        "change":      change,
        "change_rate": change_rate,
        "trade_amount": trade_amount,
        "strength":    str(strength or "-"),
        "sector":      sector,
    }


def check_test_buy_power(price: int, qty: int, daily_spent: int) -> tuple[bool, str]:
    """
    테스트모드: 매수 전 예수금 검증.
    Settlement Engine의 check_buy_power를 호출하여 매수 가능 여부를 확인한다.
    반환: (ok, reason) -- ok=False이면 매수 거부 사유를 reason에 포함.
    """
    order_amount = price * qty
    _max_daily_on = bool(state.integrated_system_settings_cache.get("max_daily_total_buy_on", False))
    _max_daily = int(state.integrated_system_settings_cache["max_daily_total_buy_amt"])
    daily_limit = _max_daily if (_max_daily_on and _max_daily > 0) else 0
    ok, reason = settlement_engine.check_buy_power(order_amount, daily_limit, daily_spent)
    return ok, reason


async def reserve_test_buy_power(price: int, qty: int, daily_spent: int) -> tuple[bool, str, int]:
    """
    테스트모드: 매수 전 예수금 검증 + 즉시 차감 (TOCTOU 경쟁 상태 방지).
    Settlement Engine의 reserve_buy_power를 호출하여 매수 가능 여부 확인과 동시에
    _orderable에서 즉시 차감한다.
    반환: (ok, reason, cost) — cost는 차감된 금액 (롤백 시 release_buy_power에 전달).
    """
    order_amount = price * qty
    _max_daily_on = bool(state.integrated_system_settings_cache.get("max_daily_total_buy_on", False))
    _max_daily = int(state.integrated_system_settings_cache["max_daily_total_buy_amt"])
    daily_limit = _max_daily if (_max_daily_on and _max_daily > 0) else 0
    ok, reason, cost = await settlement_engine.reserve_buy_power(order_amount, daily_limit, daily_spent)
    return ok, reason, cost
