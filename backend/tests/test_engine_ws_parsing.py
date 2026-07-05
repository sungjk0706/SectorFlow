"""engine_ws_parsing.py 단위 테스트 — WS·REST 페이로드 파싱 순수 함수 검증.

모든 함수는 전역 상태 없이 입력→출력만 검증한다.
"""
from __future__ import annotations

from backend.app.services.engine_ws_parsing import (
    _ws_int,
    _ws_fid_raw,
    _ws_fid_key_present,
    _ws_fid_float,
    _ws_fid_int,
    _normalize_real_type,
    _parse_price_scalar,
    _parse_fid10_price,
    _rest_row_int,
    _rest_row_float,
    parse_change_rate_to_percent,
    parse_fid9081_exchange,
    parse_fid290_session,
    is_nxt_tick,
    is_nxt_premarket,
    is_nxt_aftermarket,
)


# ── _ws_int ──────────────────────────────────────────────────────────────────

class TestWsInt:
    def test_plain_int(self):
        assert _ws_int({"price": "8010"}, "price") == 8010

    def test_with_comma(self):
        assert _ws_int({"price": "8,010"}, "price") == 8010

    def test_with_plus_sign(self):
        assert _ws_int({"price": "+8010"}, "price") == 8010

    def test_float_string(self):
        assert _ws_int({"price": "8010.5"}, "price") == 8010

    def test_none_value(self):
        assert _ws_int({"price": None}, "price", default=99) == 99

    def test_missing_key(self):
        assert _ws_int({}, "price", default=42) == 42

    def test_empty_string(self):
        assert _ws_int({"price": ""}, "price") == 0

    def test_dash_only(self):
        assert _ws_int({"price": "-"}, "price") == 0

    def test_invalid_string(self):
        assert _ws_int({"price": "abc"}, "price", default=5) == 5


# ── _ws_fid_raw ───────────────────────────────────────────────────────────────

class TestWsFidRaw:
    def test_string_key(self):
        assert _ws_fid_raw({"13": "val"}, "13") == "val"

    def test_int_key_fallback(self):
        assert _ws_fid_raw({13: "val"}, "13") == "val"

    def test_missing_key(self):
        assert _ws_fid_raw({}, "13") is None

    def test_non_dict_input(self):
        assert _ws_fid_raw(None, "13") is None
        assert _ws_fid_raw("not_dict", "13") is None

    def test_invalid_fid(self):
        assert _ws_fid_raw({"13": "val"}, "abc") is None


# ── _ws_fid_key_present ───────────────────────────────────────────────────────

class TestWsFidKeyPresent:
    def test_present_string_key(self):
        assert _ws_fid_key_present({"10": "100"}, "10") is True

    def test_present_int_key(self):
        assert _ws_fid_key_present({10: "100"}, "10") is True

    def test_absent(self):
        assert _ws_fid_key_present({}, "10") is False

    def test_none_value_is_absent(self):
        assert _ws_fid_key_present({"10": None}, "10") is False


# ── _ws_fid_float ──────────────────────────────────────────────────────────────

class TestWsFidFloat:
    def test_plain_float(self):
        assert _ws_fid_float({"12": "1.5"}, "12") == 1.5

    def test_with_comma(self):
        assert _ws_fid_float({"12": "1,500.5"}, "12") == 1500.5

    def test_with_plus(self):
        assert _ws_fid_float({"12": "+1.5"}, "12") == 1.5

    def test_missing(self):
        assert _ws_fid_float({}, "12", default=9.9) == 9.9

    def test_dash(self):
        assert _ws_fid_float({"12": "-"}, "12") == 0.0

    def test_none_value(self):
        assert _ws_fid_float({"12": None}, "12", default=3.14) == 3.14

    def test_int_key(self):
        assert _ws_fid_float({12: "2.5"}, "12") == 2.5


# ── _ws_fid_int ────────────────────────────────────────────────────────────────

class TestWsFidInt:
    def test_plain_int(self):
        assert _ws_fid_int({"13": "100"}, "13") == 100

    def test_with_comma(self):
        assert _ws_fid_int({"13": "1,000"}, "13") == 1000

    def test_float_string(self):
        assert _ws_fid_int({"13": "100.9"}, "13") == 100

    def test_missing(self):
        assert _ws_fid_int({}, "13", default=77) == 77

    def test_dash(self):
        assert _ws_fid_int({"13": "-"}, "13") == 0

    def test_int_key(self):
        assert _ws_fid_int({13: "42"}, "13") == 42


# ── _normalize_real_type ───────────────────────────────────────────────────────

class TestNormalizeRealType:
    def test_none(self):
        assert _normalize_real_type(None) == ""

    def test_empty(self):
        assert _normalize_real_type("") == ""

    def test_0b_to_01(self):
        assert _normalize_real_type("0B") == "01"

    def test_0j_lowercase_preserved(self):
        assert _normalize_real_type("0j") == "0j"

    def test_0J_uppercase_to_0j(self):
        assert _normalize_real_type("0J") == "0j"

    def test_0d_lowercase_preserved(self):
        assert _normalize_real_type("0d") == "0d"

    def test_0D_uppercase_to_0d(self):
        assert _normalize_real_type("0D") == "0d"

    def test_single_digit_zfill(self):
        assert _normalize_real_type("1") == "01"

    def test_double_digit_upper(self):
        assert _normalize_real_type("00") == "00"

    def test_04_upper(self):
        assert _normalize_real_type("04") == "04"

    def test_80_upper(self):
        assert _normalize_real_type("80") == "80"


# ── _parse_price_scalar ────────────────────────────────────────────────────────

class TestParsePriceScalar:
    def test_plain(self):
        assert _parse_price_scalar("8010") == 8010

    def test_with_comma(self):
        assert _parse_price_scalar("5,200") == 5200

    def test_with_plus(self):
        assert _parse_price_scalar("+8010") == 8010

    def test_with_minus(self):
        assert _parse_price_scalar("-4780") == 4780

    def test_none(self):
        assert _parse_price_scalar(None) == 0

    def test_empty(self):
        assert _parse_price_scalar("") == 0

    def test_dash(self):
        assert _parse_price_scalar("-") == 0

    def test_plus_only(self):
        assert _parse_price_scalar("+") == 0

    def test_dot_only(self):
        assert _parse_price_scalar(".") == 0

    def test_double_dash(self):
        assert _parse_price_scalar("--") == 0

    def test_float_string(self):
        assert _parse_price_scalar("8010.5") == 8010

    def test_invalid(self):
        assert _parse_price_scalar("abc") == 0


# ── _parse_fid10_price ──────────────────────────────────────────────────────────

class TestParseFid10Price:
    def test_fid10_present(self):
        assert _parse_fid10_price({"10": "8010"}) == 8010

    def test_fid10_with_sign(self):
        assert _parse_fid10_price({"10": "+8010"}) == 8010

    def test_fid10_zero_fallback_to_27(self):
        assert _parse_fid10_price({"10": "0", "27": "7000"}) == 7000

    def test_fid10_missing_fallback_to_28(self):
        assert _parse_fid10_price({"28": "6000"}) == 6000

    def test_all_missing(self):
        assert _parse_fid10_price({}) == 0

    def test_non_dict(self):
        assert _parse_fid10_price(None) == 0
        assert _parse_fid10_price("not_dict") == 0

    def test_fid10_zero_and_no_fallback(self):
        assert _parse_fid10_price({"10": "0"}) == 0


# ── _rest_row_int ───────────────────────────────────────────────────────────────

class TestRestRowInt:
    def test_first_key(self):
        assert _rest_row_int({"qty": "100"}, "qty") == 100

    def test_second_key_fallback(self):
        assert _rest_row_int({"rmnd_qty": "200"}, "qty", "rmnd_qty") == 200

    def test_with_comma(self):
        assert _rest_row_int({"qty": "1,000"}, "qty") == 1000

    def test_with_plus(self):
        assert _rest_row_int({"qty": "+500"}, "qty") == 500

    def test_none_value(self):
        assert _rest_row_int({"qty": None}, "qty", default=9) == 9

    def test_missing_all_keys(self):
        assert _rest_row_int({}, "qty", "rmnd_qty", default=42) == 42

    def test_invalid_value(self):
        assert _rest_row_int({"qty": "abc"}, "qty", default=7) == 7


# ── _rest_row_float ──────────────────────────────────────────────────────────────

class TestRestRowFloat:
    def test_plain(self):
        assert _rest_row_float({"rate": "1.5"}, "rate") == 1.5

    def test_with_percent(self):
        assert _rest_row_float({"rate": "1.5%"}, "rate") == 1.5

    def test_with_comma(self):
        assert _rest_row_float({"rate": "1,500.5"}, "rate") == 1500.5

    def test_second_key_fallback(self):
        assert _rest_row_float({"prft_rt": "2.5"}, "rate", "prft_rt") == 2.5

    def test_missing(self):
        assert _rest_row_float({}, "rate", default=9.9) == 9.9

    def test_none_value(self):
        assert _rest_row_float({"rate": None}, "rate", default=3.14) == 3.14


# ── parse_change_rate_to_percent ────────────────────────────────────────────────

class TestParseChangeRateToPercent:
    def test_none(self):
        assert parse_change_rate_to_percent(None) == 0.0

    def test_zero(self):
        assert parse_change_rate_to_percent("0") == 0.0

    def test_plain_positive(self):
        assert parse_change_rate_to_percent("1.5") == 1.5

    def test_with_percent_sign(self):
        assert parse_change_rate_to_percent("1.5%") == 1.5

    def test_with_plus(self):
        assert parse_change_rate_to_percent("+1.5") == 1.5

    def test_with_minus(self):
        assert parse_change_rate_to_percent("-1.5") == -1.5

    def test_with_down_arrow(self):
        assert parse_change_rate_to_percent("▼1.5") == -1.5

    def test_with_up_arrow(self):
        assert parse_change_rate_to_percent("▲1.5") == 1.5

    def test_with_comma(self):
        assert parse_change_rate_to_percent("1,500") == 1.5

    def test_int_like_above_100_scaled(self):
        assert parse_change_rate_to_percent("1500") == 1.5

    def test_int_like_below_100_not_scaled(self):
        assert parse_change_rate_to_percent("50") == 50.0

    def test_float_not_scaled(self):
        assert parse_change_rate_to_percent("1.5") == 1.5

    def test_empty_string(self):
        assert parse_change_rate_to_percent("") == 0.0

    def test_invalid(self):
        assert parse_change_rate_to_percent("abc") == 0.0

    def test_above_1000_returns_zero(self):
        assert parse_change_rate_to_percent("1500.5") == 0.0


# ── parse_fid9081_exchange ──────────────────────────────────────────────────────

class TestParseFid9081Exchange:
    def test_krx(self):
        assert parse_fid9081_exchange({"9081": "1"}) == "1"

    def test_nxt(self):
        assert parse_fid9081_exchange({"9081": "2"}) == "2"

    def test_missing(self):
        assert parse_fid9081_exchange({}) == ""

    def test_int_key(self):
        assert parse_fid9081_exchange({9081: "1"}) == "1"


# ── parse_fid290_session ────────────────────────────────────────────────────────

class TestParseFid290Session:
    def test_krx_regular(self):
        assert parse_fid290_session({"290": "2"}) == "2"

    def test_nxt_premarket(self):
        assert parse_fid290_session({"290": "P"}) == "P"

    def test_nxt_aftermarket(self):
        assert parse_fid290_session({"290": "U"}) == "U"

    def test_missing(self):
        assert parse_fid290_session({}) == ""

    def test_int_key(self):
        assert parse_fid290_session({290: "2"}) == "2"


# ── is_nxt_tick ──────────────────────────────────────────────────────────────────

class TestIsNxtTick:
    def test_nxt(self):
        assert is_nxt_tick({"9081": "2"}) is True

    def test_krx(self):
        assert is_nxt_tick({"9081": "1"}) is False

    def test_missing(self):
        assert is_nxt_tick({}) is False


# ── is_nxt_premarket ──────────────────────────────────────────────────────────────

class TestIsNxtPremarket:
    def test_premarket(self):
        assert is_nxt_premarket({"290": "P"}) is True

    def test_regular(self):
        assert is_nxt_premarket({"290": "2"}) is False

    def test_missing(self):
        assert is_nxt_premarket({}) is False


# ── is_nxt_aftermarket ─────────────────────────────────────────────────────────────

class TestIsNxtAftermarket:
    def test_aftermarket(self):
        assert is_nxt_aftermarket({"290": "U"}) is True

    def test_regular(self):
        assert is_nxt_aftermarket({"290": "2"}) is False

    def test_missing(self):
        assert is_nxt_aftermarket({}) is False
