# -*- coding: utf-8 -*-
"""auto_trading_effective.py 단위 테스트 — auto_buy_reject_reason 사유 분기 검증.

auto_buy_effective의 사유코드 분해 로직이 각 하위 조건별로 올바른 사유코드를
반환하는지 검증 (P10 SSOT — auto_buy_effective와 동일 조건).
"""
from __future__ import annotations
from datetime import datetime
from unittest.mock import patch

import pytest

from backend.app.services.auto_trading_effective import (
    auto_buy_effective, auto_buy_reject_reason,
)
from backend.app.services.trading import (
    BUY_OK, BUY_REJECT_AUTO_BUY_OFF, BUY_REJECT_BUY_TIME_OUT,
    BUY_REJECT_MASTER_OFF, BUY_REJECT_NON_TRADING_DAY, BUY_REJECT_RISK_CIRCUIT,
)
from backend.app.core.constants import _KST


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _settings(**overrides):
    s = {
        "time_scheduler_on": True,
        "auto_buy_on": True,
        "buy_time_start": "09:00",
        "buy_time_end": "15:30",
    }
    s.update(overrides)
    return s


# ── auto_buy_reject_reason 사유 분기 ──────────────────────────────────────────

class TestAutoBuyRejectReason:
    """auto_buy_reject_reason이 각 하위 조건별로 올바른 사유코드를 반환하는지 검증."""

    def test_flat_none_returns_master_off(self):
        """설정 None → BUY_REJECT_MASTER_OFF (자동매매 OFF)."""
        assert auto_buy_reject_reason(None) == BUY_REJECT_MASTER_OFF

    def test_master_off_returns_master_off(self):
        """time_scheduler_on=False → BUY_REJECT_MASTER_OFF (자동매매 OFF)."""
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.krx_circuit_breaker_active = False
            reason = auto_buy_reject_reason(_settings(time_scheduler_on=False))
        assert reason == BUY_REJECT_MASTER_OFF

    def test_non_trading_day_returns_non_trading_day(self):
        """비거래일(공휴일/주말) → BUY_REJECT_NON_TRADING_DAY (휴일/주말)."""
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=False), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.krx_circuit_breaker_active = False
            reason = auto_buy_reject_reason(_settings())
        assert reason == BUY_REJECT_NON_TRADING_DAY

    def test_krx_circuit_breaker_returns_risk_circuit(self):
        """KRX 서킷브레이커 발동 → BUY_REJECT_RISK_CIRCUIT (서킷브레이커)."""
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.krx_circuit_breaker_active = True
            reason = auto_buy_reject_reason(_settings())
        assert reason == BUY_REJECT_RISK_CIRCUIT

    def test_auto_buy_off_returns_auto_buy_off(self):
        """auto_buy_on=False → BUY_REJECT_AUTO_BUY_OFF (자동매수 OFF)."""
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.krx_circuit_breaker_active = False
            reason = auto_buy_reject_reason(_settings(auto_buy_on=False))
        assert reason == BUY_REJECT_AUTO_BUY_OFF

    def test_time_out_returns_buy_time_out(self):
        """매수 작동시간 범위 외 → BUY_REJECT_BUY_TIME_OUT (자동매수 시간외)."""
        # 현재 시각이 09:00~15:30 범위 밖인 시각으로 now 파라미터 전달
        _out_of_range = datetime(2026, 7, 30, 8, 0, tzinfo=_KST)  # 08:00 (개시 전)
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.krx_circuit_breaker_active = False
            reason = auto_buy_reject_reason(_settings(), now=_out_of_range)
        assert reason == BUY_REJECT_BUY_TIME_OUT

    def test_all_pass_returns_empty(self):
        """모든 조건 통과 → 빈 문자열(=BUY_OK, 매수 유효)."""
        _in_range = datetime(2026, 7, 30, 10, 0, tzinfo=_KST)  # 10:00 (장중)
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.krx_circuit_breaker_active = False
            reason = auto_buy_reject_reason(_settings(), now=_in_range)
        assert reason == BUY_OK

    def test_auto_buy_effective_delegates_to_reject_reason(self):
        """auto_buy_effective가 auto_buy_reject_reason에 위임 — 일관성 검증 (P10 SSOT)."""
        _in_range = datetime(2026, 7, 30, 10, 0, tzinfo=_KST)
        _out_of_range = datetime(2026, 7, 30, 8, 0, tzinfo=_KST)
        with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.krx_circuit_breaker_active = False
            # 유효 시 일치 검증
            assert auto_buy_effective(_settings(), now=_in_range) is True
            assert auto_buy_reject_reason(_settings(), now=_in_range) == BUY_OK
            # 시간외 시 일치 검증
            assert auto_buy_effective(_settings(), now=_out_of_range) is False
            assert auto_buy_reject_reason(_settings(), now=_out_of_range) == BUY_REJECT_BUY_TIME_OUT
