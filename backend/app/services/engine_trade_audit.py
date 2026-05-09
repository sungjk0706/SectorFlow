# -*- coding: utf-8 -*-
"""
엔진 매매 판단 감사 로그.

사용자가 매수 설정 등 UI에 저장한 값과, 그 시점의 수치·조건 만족 여부를
한 줄 JSON으로 남겨 사고 시 원인 추적이 가능하게 한다.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.logger import get_logger

logger = get_logger("engine")

_AUDIT_KEYS = (
    "buy_amt",
    "max_daily_total_buy_amt",
    "max_stock_cnt",
    "auto_buy_on",
    "auto_sell_on",
    "buy_time_start",
    "buy_time_end",
    "sell_time_start",
    "sell_time_end",
)


def _pick_settings(settings: dict | None) -> dict[str, Any]:
    if not settings:
        return {}
    return {k: settings.get(k) for k in _AUDIT_KEYS if k in settings}


def audit_trade_decision(
    *,
    event: str,
    stk_cd: str | None = None,
    settings: dict | None = None,
    extra: dict[str, Any] | None = None,
    reason_ko: str | None = None,
) -> None:
    """[매매판단기록] 판단·실행 근거 로그. reason_ko는 UI 설정 기준 한국어 근거 문장."""
    payload: dict[str, Any] = {
        "event": event,
        "settings_snapshot": _pick_settings(settings),
    }
    if stk_cd is not None:
        payload["stk_cd"] = stk_cd
    if extra:
        payload.update(extra)
    if reason_ko:
        payload["reason_ko"] = reason_ko
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        line = str(payload)
    if reason_ko:
        logger.info("[매매판단기록] %s", reason_ko)
    logger.info("[매매판단기록] %s", line)
