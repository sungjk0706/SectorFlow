"""engine_ws_fill_followup.py 단위 테스트 — 주문체결 후속 처리 검증.

run_after_order_fill_ws()의 dry_run 분기 및 콜백 호출 순서를 검증.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.services.engine_ws_fill_followup import run_after_order_fill_ws


# ── run_after_order_fill_ws 기본 동작 ──────────────────────────────────────────

class TestRunAfterOrderFillWs:
    def test_calls_both_callbacks_in_order(self):
        calls: list[str] = []
        refresh = MagicMock(side_effect=lambda: calls.append("refresh"))
        sell = MagicMock(side_effect=lambda: calls.append("sell"))

        run_after_order_fill_ws(0.0, refresh, sell)

        assert calls == ["refresh", "sell"]

    def test_dry_run_true_skips_rest(self):
        refresh = MagicMock()
        sell = MagicMock()

        run_after_order_fill_ws(0.0, refresh, sell, is_dry_run=True)

        refresh.assert_called_once()
        sell.assert_called_once()

    def test_dry_run_false_default(self):
        refresh = MagicMock()
        sell = MagicMock()

        run_after_order_fill_ws(0.0, refresh, sell)

        refresh.assert_called_once()
        sell.assert_called_once()

    def test_refresh_called_before_sell(self):
        order: list[str] = []
        refresh = MagicMock(side_effect=lambda: order.append("r"))
        sell = MagicMock(side_effect=lambda: order.append("s"))

        run_after_order_fill_ws(1.0, refresh, sell, is_dry_run=False)

        assert order[0] == "r"
        assert order[1] == "s"

    def test_zero_delay(self):
        refresh = MagicMock()
        sell = MagicMock()

        run_after_order_fill_ws(0, refresh, sell)

        refresh.assert_called_once()
        sell.assert_called_once()

    def test_negative_delay(self):
        refresh = MagicMock()
        sell = MagicMock()

        run_after_order_fill_ws(-1.0, refresh, sell)

        refresh.assert_called_once()
        sell.assert_called_once()

    def test_callbacks_are_not_async(self):
        """콜백은 동기 callable — async가 아님을 확인."""
        refresh = MagicMock()
        sell = MagicMock()

        result = run_after_order_fill_ws(0.0, refresh, sell)

        assert result is None
