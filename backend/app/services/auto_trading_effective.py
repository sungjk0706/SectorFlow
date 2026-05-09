# -*- coding: utf-8 -*-
"""
time_scheduler_on(마스터 스위치) + 매수/매도 개별 시간 범위 + auto_buy_on / auto_sell_on.
영속 필드 auto_trade_on 제거 후 엔진·API·WS에서 공통 사용.

v2: 작동시간을 매수/매도 각각 분리.
    - buy_time_start / buy_time_end  (매수 작동시간)
    - sell_time_start / sell_time_end (매도 작동시간)
    - time_scheduler_on 은 마스터 스위치로 유지.
    - 레거시 time_start / time_end 는 폴백으로만 참조.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

KST = timezone(timedelta(hours=9))

# 기본 장중 구간
BUY_OPEN_HM = "09:00"
BUY_CLOSE_HM = "15:20"
SELL_OPEN_HM = "09:00"
SELL_CLOSE_HM = "15:20"

# 하위호환 -- 레거시 키 폴백
OPEN_HM = "09:00"
CLOSE_HM = "15:20"


def _master_on(flat: Optional[dict[str, Any]]) -> bool:
    """마스터 스위치(time_scheduler_on) 체크. holiday_guard_on이면 공휴일 차단."""
    if not flat:
        return False
    if not bool(flat.get("time_scheduler_on", False)):
        return False
    # 공휴일 가드: ON이면 공휴일에 자동매매 차단
    if bool(flat.get("holiday_guard_on", True)):
        from app.core.trading_calendar import is_krx_holiday, kst_today
        if is_krx_holiday(kst_today()):
            return False
    return True


def _in_time_range(flat: dict[str, Any], start_key: str, end_key: str,
                   default_start: str, default_end: str,
                   now: Optional[datetime] = None) -> bool:
    """KST HH:MM 기준 시간 범위 안에 있는지 판단."""
    now_kst = now if now is not None else datetime.now(KST)
    hm = now_kst.strftime("%H:%M")
    try:
        start_str = str(
            flat.get(start_key)
            or default_start
        )[:5]
        end_str = str(
            flat.get(end_key)
            or default_end
        )[:5]
        return start_str <= hm <= end_str
    except Exception:
        return True


def schedule_allows_auto_trading(flat: Optional[dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """
    마스터 스위치 체크만 수행 (하위호환 유지).
    time_scheduler_on == False -> 항상 False.
    time_scheduler_on == True -> True (시간 범위는 매수/매도 각각에서 판단).
    """
    return _master_on(flat)


def auto_buy_effective(flat: Optional[dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """마스터 ON + 자동 매수 ON + 매수 작동시간 범위 안."""
    if not _master_on(flat):
        return False
    if not bool(flat.get("auto_buy_on", True)):
        return False
    return _in_time_range(flat, "buy_time_start", "buy_time_end",
                          BUY_OPEN_HM, BUY_CLOSE_HM, now)


def auto_sell_effective(flat: Optional[dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """마스터 ON + 자동 매도 ON + 매도 작동시간 범위 안."""
    if not _master_on(flat):
        return False
    if not bool(flat.get("auto_sell_on", True)):
        return False
    return _in_time_range(flat, "sell_time_start", "sell_time_end",
                          SELL_OPEN_HM, SELL_CLOSE_HM, now)


def auto_trading_effective(flat: Optional[dict[str, Any]], now: Optional[datetime] = None) -> bool:
    """
    API/헤더용: 자동 매수·매도 중 하나라도 유효하면 True.
    (마스터 OFF이거나 둘 다 OFF/시간 외면 False.)
    """
    return auto_buy_effective(flat, now) or auto_sell_effective(flat, now)
