# -*- coding: utf-8 -*-
"""
time_scheduler_on(마스터 스위치) + 매수/매도 개별 시간 범위 + auto_buy_on / auto_sell_on.
엔진·API·WS에서 공통 사용하는 자동매매 유효성 판정 모듈.

v2: 작동시간을 매수/매도 각각 분리.
    - buy_time_start / buy_time_end  (매수 작동시간)
    - sell_time_start / sell_time_end (매도 작동시간)
    - time_scheduler_on 은 마스터 스위치로 유지.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
import logging
from backend.app.core.constants import _KST
logger = logging.getLogger(__name__)


def _master_reject_reason(flat: dict[str, Any] | None) -> str:
    """마스터 게이트 사유 판정 — 통과 시 빈 문자열, 차단 시 사유코드 (P10 SSOT).

    _master_on의 단일 진실 소스 — bool 래퍼(_master_on)와 사우 판정(auto_buy_reject_reason)이
    모두 이 함수에 위임하여 조건 분기가 한 곳에서만 정의됨.
    """
    from backend.app.services.trading import (
        BUY_REJECT_MASTER_OFF, BUY_REJECT_NON_TRADING_DAY, BUY_REJECT_RISK_CIRCUIT,
    )
    if not flat:
        return BUY_REJECT_MASTER_OFF
    if not bool(flat["time_scheduler_on"]):
        return BUY_REJECT_MASTER_OFF
    from backend.app.core.trading_calendar import is_trading_day, get_kst_today
    if not is_trading_day(get_kst_today()):
        return BUY_REJECT_NON_TRADING_DAY
    from backend.app.services.engine_state import state
    if state.krx_circuit_breaker_active:
        return BUY_REJECT_RISK_CIRCUIT
    return ""


def _master_on(flat: dict[str, Any] | None) -> bool:
    """마스터 스위치(time_scheduler_on) 체크. 공휴일/주말 차단.
    KRX 서킷브레이커/사이드카 발동 중이면 임시 차단."""
    return _master_reject_reason(flat) == ""


def _in_time_range(flat: dict[str, Any], start_key: str, end_key: str,
                   now: datetime | None = None) -> bool:
    """KST HH:MM 기준 시간 범위 안에 있는지 판단."""
    now_kst = now if now is not None else datetime.now(_KST)
    hm = now_kst.strftime("%H:%M")
    try:
        start_str = str(flat[start_key])[:5]
        end_str = str(flat[end_key])[:5]
        return start_str <= hm <= end_str
    except (KeyError, TypeError) as e:
        logger.warning("[자동매매] 시간 범위 설정 오류 — %s: %s (시작시간설정=%s, 종료시간설정=%s)",
                       type(e).__name__, e, start_key, end_key)
        return False


def auto_buy_reject_reason(flat: dict[str, Any] | None, now: datetime | None = None) -> str:
    """auto_buy_effective 사유 판정 — 유효 시 빈 문자열, 무효 시 사유코드 반환 (P10 SSOT).

    auto_buy_effective와 동일 조건을 사유코드로 분해. buy_order_executor에서
    전역 차단 사유 UI "원인" 컬럼 표시용 (P21 사용자 투명성).
    마스터 게이트는 _master_reject_reason에 위임 — 조건 분기 단일 진실 소스.
    """
    from backend.app.services.trading import BUY_REJECT_AUTO_BUY_OFF, BUY_REJECT_BUY_TIME_OUT
    _master_reason = _master_reject_reason(flat)
    if _master_reason:
        return _master_reason
    assert flat is not None  # _master_reject_reason 통과 → flat은 None 아님
    if not bool(flat["auto_buy_on"]):
        return BUY_REJECT_AUTO_BUY_OFF
    if not _in_time_range(flat, "buy_time_start", "buy_time_end", now):
        return BUY_REJECT_BUY_TIME_OUT
    return ""


def auto_buy_effective(flat: dict[str, Any] | None, now: datetime | None = None) -> bool:
    """마스터 ON + 자동 매수 ON + 매수 작동시간 범위 안."""
    return auto_buy_reject_reason(flat, now) == ""


def auto_sell_effective(flat: dict[str, Any] | None, now: datetime | None = None) -> bool:
    """마스터 ON + 자동 매도 ON + 매도 작동시간 범위 안."""
    if not _master_on(flat):
        return False
    assert flat is not None
    if not bool(flat["auto_sell_on"]):
        return False
    return _in_time_range(flat, "sell_time_start", "sell_time_end", now)


def auto_trading_effective(flat: dict[str, Any] | None, now: datetime | None = None) -> bool:
    """
    API/헤더용: 자동 매수·매도 중 하나라도 유효하면 True.
    (마스터 OFF이거나 둘 다 OFF/시간 외면 False.)
    """
    return auto_buy_effective(flat, now) or auto_sell_effective(flat, now)
