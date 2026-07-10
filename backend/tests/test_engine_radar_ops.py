"""engine_radar_ops.py 단위 테스트 — 레이더/작전 테이블 실시간 시세 오버레이 검증.

overlay_radar_row_with_live_price()와 apply_real01_volume_amount_to_radar_rows()의
실시간 가격/거래대금 보강 로직을 검증.
"""
from __future__ import annotations

from backend.app.services.engine_radar_ops import (
    apply_real01_volume_amount_to_radar_rows,
    overlay_radar_row_with_live_price,
)


# ── overlay_radar_row_with_live_price ──────────────────────────────────────────

class TestOverlayRadarRowWithLivePrice:
    def test_empty_code_returns_original(self):
        row = {"code": "", "cur_price": 50000}
        result = overlay_radar_row_with_live_price(row, {}, {})
        assert result == row

    def test_no_code_key_returns_original(self):
        row = {"cur_price": 50000}
        result = overlay_radar_row_with_live_price(row, {}, {})
        assert result == row

    def test_live_price_updates_cur_price(self):
        row = {"code": "005930", "cur_price": 0}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 70000}, {}
        )
        assert result["cur_price"] == 70000

    def test_live_price_zero_ignored(self):
        row = {"code": "005930", "cur_price": 50000}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 0}, {}
        )
        assert result["cur_price"] == 50000

    def test_live_price_negative_ignored(self):
        row = {"code": "005930", "cur_price": 50000}
        result = overlay_radar_row_with_live_price(
            row, {"005930": -1}, {}
        )
        assert result["cur_price"] == 50000

    def test_trade_amount_updated(self):
        row = {"code": "005930", "cur_price": 70000}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 70000}, {"005930": 123456}
        )
        assert result["trade_amount"] == 123456

    def test_trade_amount_zero_cached(self):
        row = {"code": "005930", "cur_price": 70000}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 70000}, {"005930": 0}
        )
        assert result["trade_amount"] == 0

    def test_quote_src_removed_when_live_price(self):
        row = {"code": "005930", "cur_price": 0, "quote_src": "rest"}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 70000}, {}
        )
        assert "quote_src" not in result

    def test_strips_code_whitespace(self):
        row = {"code": "  005930  ", "cur_price": 0}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 70000}, {}
        )
        assert result["cur_price"] == 70000

    def test_al_suffix_normalized(self):
        row = {"code": "005930_AL", "cur_price": 0}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 70000}, {}
        )
        assert result["cur_price"] == 70000

    def test_rest_quote_fallback_when_no_live_price(self):
        row = {"code": "005930", "cur_price": 0}
        rest = {"005930": {"cur_price": 68000, "change": 500, "change_rate": 0.7}}
        result = overlay_radar_row_with_live_price(
            row, {}, {}, rest_quote_by_nk=rest
        )
        assert result["cur_price"] == 68000
        assert result["change"] == 500
        assert result["change_rate"] == 0.7
        assert result["quote_src"] == "rest"

    def test_rest_quote_with_trade_amount_and_strength(self):
        row = {"code": "005930", "cur_price": 0}
        rest = {
            "005930": {
                "cur_price": 68000,
                "trade_amount": 999,
                "strength": "123.4",
                "sign": "2",
            }
        }
        result = overlay_radar_row_with_live_price(
            row, {}, {}, rest_quote_by_nk=rest
        )
        assert result["cur_price"] == 68000
        assert result["trade_amount"] == 999
        assert result["strength"] == "123.4"
        assert result["sign"] == "2"

    def test_rest_quote_cur_price_zero_ignored(self):
        row = {"code": "005930", "cur_price": 50000}
        rest = {"005930": {"cur_price": 0}}
        result = overlay_radar_row_with_live_price(
            row, {}, {}, rest_quote_by_nk=rest
        )
        assert result["cur_price"] == 50000

    def test_rest_quote_not_dict_ignored(self):
        row = {"code": "005930", "cur_price": 50000}
        rest = {"005930": "not_a_dict"}
        result = overlay_radar_row_with_live_price(
            row, {}, {}, rest_quote_by_nk=rest
        )
        assert result["cur_price"] == 50000

    def test_rest_quote_missing_key_ignored(self):
        row = {"code": "005930", "cur_price": 50000}
        rest = {"999999": {"cur_price": 68000}}
        result = overlay_radar_row_with_live_price(
            row, {}, {}, rest_quote_by_nk=rest
        )
        assert result["cur_price"] == 50000

    def test_rest_quote_none_ignored(self):
        row = {"code": "005930", "cur_price": 50000}
        result = overlay_radar_row_with_live_price(
            row, {}, {}, rest_quote_by_nk=None
        )
        assert result["cur_price"] == 50000

    def test_live_price_takes_precedence_over_rest(self):
        row = {"code": "005930", "cur_price": 0}
        rest = {"005930": {"cur_price": 68000}}
        result = overlay_radar_row_with_live_price(
            row, {"005930": 70000}, {}, rest_quote_by_nk=rest
        )
        assert result["cur_price"] == 70000

    def test_original_row_not_mutated(self):
        row = {"code": "005930", "cur_price": 0}
        original = dict(row)
        overlay_radar_row_with_live_price(row, {"005930": 70000}, {})
        assert row == original


# ── apply_real01_volume_amount_to_radar_rows ───────────────────────────────────

class TestApplyReal01VolumeAmount:
    def test_patches_active_pending_row(self):
        pending = {"005930": {"status": "active", "trade_amount": 0}}
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {"005930": 555}, pending
        )
        assert pending["005930"]["trade_amount"] == 555

    def test_skips_inactive_pending_row(self):
        pending = {"005930": {"status": "inactive", "trade_amount": 100}}
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {"005930": 555}, pending
        )
        assert pending["005930"]["trade_amount"] == 100

    def test_no_cached_amount_no_patch(self):
        pending = {"005930": {"status": "active", "trade_amount": 100}}
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {}, pending
        )
        assert pending["005930"]["trade_amount"] == 100

    def test_cached_amount_zero_patched(self):
        pending = {"005930": {"status": "active", "trade_amount": 100}}
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {"005930": 0}, pending
        )
        assert pending["005930"]["trade_amount"] == 0

    def test_no_matching_pending_key(self):
        pending = {"999999": {"status": "active", "trade_amount": 100}}
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {"005930": 555}, pending
        )
        assert pending["999999"]["trade_amount"] == 100

    def test_al_suffix_resolved(self):
        pending = {"005930": {"status": "active", "trade_amount": 0}}
        apply_real01_volume_amount_to_radar_rows(
            "005930_AL", {}, {"005930": 555}, pending
        )
        assert pending["005930"]["trade_amount"] == 555

    def test_empty_pending_dict(self):
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {"005930": 555}, {}
        )
        # no exception

    def test_empty_raw_cd(self):
        pending = {"005930": {"status": "active", "trade_amount": 0}}
        apply_real01_volume_amount_to_radar_rows(
            "", {}, {"005930": 555}, pending
        )
        assert pending["005930"]["trade_amount"] == 0

    def test_is_0b_tick_true_default(self):
        pending = {"005930": {"status": "active", "trade_amount": 0}}
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {"005930": 555}, pending, is_0b_tick=True
        )
        assert pending["005930"]["trade_amount"] == 555

    def test_is_0b_tick_false(self):
        pending = {"005930": {"status": "active", "trade_amount": 0}}
        apply_real01_volume_amount_to_radar_rows(
            "005930", {}, {"005930": 555}, pending, is_0b_tick=False
        )
        assert pending["005930"]["trade_amount"] == 555
