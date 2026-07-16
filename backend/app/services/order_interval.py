# -*- coding: utf-8 -*-
"""
주문 간격 게이트 공통 헬퍼 — 매수/매도 양쪽에서 호출 (P23 공통 자산).

매수: buy_order_executor.evaluate_buy_candidates() 진입 시 사전 체크
매도: trading.check_sell_conditions() for-loop 진입 전 사전 체크
"""
import time
from backend.app.services.engine_state import state


def check_order_interval(settings: dict, kind: str) -> bool:
    """
    주문 간격 게이트 — 간격 내면 False 반환 (호출측에서 return).
    kind: "buy" | "sell"
    반환: True=통과(주문 시도 가능), False=차단(간격 내)
    """
    _on = bool(settings.get(f"{kind}_interval_on", False))
    if not _on:
        return True
    _sec = int(settings.get(f"{kind}_interval_sec", 0) or 0)
    if _sec <= 0:
        return True
    _last_ts = state._last_global_buy_ts if kind == "buy" else state._last_global_sell_ts
    if _last_ts <= 0:
        return True  # 최초 주문 — 타이머 미설정
    return (time.time() - _last_ts) >= _sec


def mark_order_executed(kind: str) -> None:
    """
    주문 전송 성공 시 타이머 갱신.
    kind: "buy" | "sell"
    """
    _now = time.time()
    if kind == "buy":
        state._last_global_buy_ts = _now
    else:
        state._last_global_sell_ts = _now
