"""data_manager.py 단위 테스트 — 종목명 조회 검증.

hang 방지 원칙:
- engine_state.state를 mock으로 대체

참고: 종목코드 정규화(_norm_stk_cd)는 core/symbol_utils._base_stk_cd로 통합됨 (P10 SSOT).
_base_stk_cd 직접 단위 테스트는 test_engine_symbol_utils.py::TestBaseStkCd 참조.
"""
from __future__ import annotations

from unittest.mock import patch

from backend.app.services.data_manager import (
    get_stock_name,
)


# ── get_stock_name ────────────────────────────────────────────────────────────

class TestGetStockName:
    @patch("backend.app.services.engine_state.state")
    def test_empty_code_returns_unknown(self, mock_state):
        assert get_stock_name("") == "알수없음"

    @patch("backend.app.services.engine_state.state")
    def test_found_in_cache(self, mock_state):
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자"}}
        assert get_stock_name("005930") == "삼성전자"

    @patch("backend.app.services.engine_state.state")
    def test_not_in_cache_returns_code(self, mock_state):
        mock_state.master_stocks_cache = {}
        assert get_stock_name("005930") == "005930"

    @patch("backend.app.services.engine_state.state")
    def test_entry_without_name_returns_code(self, mock_state):
        mock_state.master_stocks_cache = {"005930": {}}
        assert get_stock_name("005930") == "005930"

    @patch("backend.app.services.engine_state.state")
    def test_normalizes_code_before_lookup(self, mock_state):
        mock_state.master_stocks_cache = {"000123": {"name": "테스트"}}
        assert get_stock_name("123") == "테스트"
