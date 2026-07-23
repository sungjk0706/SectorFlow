"""engine_symbol_utils.py 단위 테스트 — 종목코드 정규화 및 REAL item 해석 순수 함수 검증.

state 의존 함수(is_nxt_enabled, get_ws_subscribe_code, get_stock_market)는
state.master_stocks_cache를 mock하여 검증.
"""
from __future__ import annotations

from unittest.mock import patch

from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    _dict_get_fid,
    _fid9001_to_stk_cd,
    _parse_real_item_field,
    _real_item_stk_cd,
    is_nxt_enabled,
    get_ws_subscribe_code,
    get_stock_market,
)


# ── _base_stk_cd ────────────────────────────────────────────────────────────────

class TestBaseStkCd:
    def test_plain_6digit(self):
        assert _base_stk_cd("005930") == "005930"

    def test_al_suffix(self):
        assert _base_stk_cd("005930_AL") == "005930"

    def test_nx_suffix(self):
        assert _base_stk_cd("005930_NX") == "005930"

    def test_short_padded(self):
        assert _base_stk_cd("5930") == "005930"

    def test_uppercase_al(self):
        assert _base_stk_cd("005930_al") == "005930"

    def test_empty(self):
        assert _base_stk_cd("") == ""

    def test_none(self):
        assert _base_stk_cd(None) == ""

    def test_non_digit(self):
        assert _base_stk_cd("A005930") == "A005930"

    def test_truncated_to_6(self):
        assert _base_stk_cd("00005930") == "005930"


# ── _dict_get_fid ─────────────────────────────────────────────────────────────────

class TestDictGetFid:
    def test_string_key(self):
        assert _dict_get_fid({"9001": "005930"}, "9001") == "005930"

    def test_int_key(self):
        assert _dict_get_fid({9001: "005930"}, "9001") == "005930"

    def test_missing(self):
        assert _dict_get_fid({}, "9001") is None

    def test_non_dict(self):
        assert _dict_get_fid(None, "9001") is None

    def test_invalid_fid(self):
        assert _dict_get_fid({"9001": "val"}, "abc") is None


# ── _fid9001_to_stk_cd ────────────────────────────────────────────────────────────

class TestFid9001ToStkCd:
    def test_plain(self):
        assert _fid9001_to_stk_cd({"9001": "005930"}) == "005930"

    def test_int_key(self):
        assert _fid9001_to_stk_cd({9001: "005930"}) == "005930"

    def test_al_suffix_stripped(self):
        assert _fid9001_to_stk_cd({"9001": "005930_AL"}) == "005930"

    def test_empty_value(self):
        assert _fid9001_to_stk_cd({"9001": ""}) == ""

    def test_missing(self):
        assert _fid9001_to_stk_cd({}) == ""

    def test_non_dict(self):
        assert _fid9001_to_stk_cd(None) == ""


# ── _parse_real_item_field ─────────────────────────────────────────────────────────

class TestParseRealItemField:
    def test_string(self):
        assert _parse_real_item_field("005930") == "005930"

    def test_list(self):
        assert _parse_real_item_field(["005930"]) == "005930"

    def test_list_with_none(self):
        assert _parse_real_item_field([None]) == ""

    def test_empty_list(self):
        assert _parse_real_item_field([]) == "[]"

    def test_none(self):
        assert _parse_real_item_field(None) == ""

    def test_string_with_whitespace(self):
        assert _parse_real_item_field("  005930  ") == "005930"


# ── _real_item_stk_cd ──────────────────────────────────────────────────────────────

class TestRealItemStkCd:
    def test_values_fid9001(self):
        item = {"values": {"9001": "005930"}}
        assert _real_item_stk_cd(item, item["values"]) == "005930"

    def test_item_fid9001(self):
        item = {"9001": "005930", "values": {}}
        assert _real_item_stk_cd(item, item.get("values", {})) == "005930"

    def test_jmcode_fallback(self):
        item = {"jmcode": "005930", "values": {}}
        assert _real_item_stk_cd(item, item.get("values", {})) == "005930"

    def test_stk_cd_fallback(self):
        item = {"stk_cd": "005930_AL", "values": {}}
        assert _real_item_stk_cd(item, item.get("values", {})) == "005930"

    def test_code_fallback(self):
        item = {"code": "005930", "values": {}}
        assert _real_item_stk_cd(item, item.get("values", {})) == "005930"

    def test_item_field_fallback(self):
        item = {"item": "005930", "values": {}}
        assert _real_item_stk_cd(item, item.get("values", {})) == "005930"

    def test_item_list_field(self):
        item = {"item": ["005930"], "values": {}}
        assert _real_item_stk_cd(item, item.get("values", {})) == "005930"

    def test_item_values_fid9001_fallback(self):
        item = {"item": "", "values": {"9001": "000660"}}
        assert _real_item_stk_cd(item, item.get("values", {})) == "000660"

    def test_account_number_skipped(self):
        item = {"item": "12345678", "values": {}}
        assert _real_item_stk_cd(item, item.get("values", {})) == ""

    def test_empty(self):
        assert _real_item_stk_cd({}, {}) == ""

    def test_non_dict_item(self):
        assert _real_item_stk_cd("not_dict", {}) == ""


# ── is_nxt_enabled (state mock) ────────────────────────────────────────────────────

class TestIsNxtEnabled:
    def test_nxt_enabled(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"nxt_enable": True}}
            assert is_nxt_enabled("005930") is True

    def test_nxt_disabled(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"nxt_enable": False}}
            assert is_nxt_enabled("005930") is False

    def test_stock_not_found(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {}
            assert is_nxt_enabled("999999") is False

    def test_empty_code(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"nxt_enable": True}}
            assert is_nxt_enabled("") is False


# ── get_ws_subscribe_code (state mock) ──────────────────────────────────────────────

class TestGetWsSubscribeCode:
    def test_nxt_enabled_returns_al(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"nxt_enable": True}}
            assert get_ws_subscribe_code("005930") == "005930_AL"

    def test_nxt_disabled_returns_plain(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"nxt_enable": False}}
            assert get_ws_subscribe_code("005930") == "005930"

    def test_empty_code(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {}
            assert get_ws_subscribe_code("") == ""


# ── get_stock_market (state mock) ───────────────────────────────────────────────────

class TestGetStockMarket:
    def test_kospi(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"market": "0"}}
            assert get_stock_market("005930") == "0"

    def test_kosdaq(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {"000660": {"market": "10"}}
            assert get_stock_market("000660") == "10"

    def test_not_found(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {}
            assert get_stock_market("999999") is None

    def test_empty_code(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = {}
            assert get_stock_market("") is None
