"""data_manager.py 단위 테스트 — 종목명 조회, REST 기본 주소 조회 검증.

hang 방지 원칙:
- engine_state.state를 mock으로 대체
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from backend.app.services.data_manager import (
    _norm_stk_cd,
    get_stock_name,
    _get_rest_base,
)


# ── _norm_stk_cd ──────────────────────────────────────────────────────────────

class TestNormStkCd:
    def test_empty_string(self):
        assert _norm_stk_cd("") == ""

    def test_pure_digit_short(self):
        assert _norm_stk_cd("123") == "000123"

    def test_pure_digit_exact(self):
        assert _norm_stk_cd("005930") == "005930"

    def test_pure_digit_long_truncates(self):
        assert _norm_stk_cd("00005930") == "005930"

    def test_non_digit_uppercased(self):
        assert _norm_stk_cd("0120g0") == "0120G0"

    def test_strips_whitespace(self):
        assert _norm_stk_cd("  005930  ") == "005930"


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


# ── _get_rest_base ────────────────────────────────────────────────────────────

class TestGetRestBase:
    @pytest.mark.asyncio
    @patch("backend.app.core.broker_urls.build_broker_urls")
    @patch("backend.app.core.broker_factory.get_router")
    @patch("backend.app.services.engine_state.state")
    async def test_auth_provider_has_base_url(self, mock_state, mock_get_router, mock_build_urls):
        mock_auth = MagicMock()
        mock_auth.rest_api.base_url = "https://api.kiwoom.com"
        mock_router = MagicMock()
        mock_router.auth = mock_auth
        mock_get_router.return_value = mock_router

        result = await _get_rest_base()
        assert result == "https://api.kiwoom.com"

    @pytest.mark.asyncio
    @patch("backend.app.core.broker_urls.build_broker_urls")
    @patch("backend.app.core.broker_factory.get_router")
    @patch("backend.app.services.engine_state.state")
    async def test_auth_provider_exception_falls_back(self, mock_state, mock_get_router, mock_build_urls):
        mock_get_router.side_effect = Exception("router error")
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}
        mock_build_urls.return_value = {"rest_base": "https://fallback.kiwoom.com"}

        result = await _get_rest_base()
        assert result == "https://fallback.kiwoom.com"

    @pytest.mark.asyncio
    @patch("backend.app.core.broker_urls.build_broker_urls")
    @patch("backend.app.core.broker_factory.get_router")
    @patch("backend.app.services.engine_state.state")
    async def test_auth_no_rest_api_attr(self, mock_state, mock_get_router, mock_build_urls):
        mock_auth = MagicMock(spec=[])
        mock_router = MagicMock()
        mock_router.auth = mock_auth
        mock_get_router.return_value = mock_router
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom"}
        mock_build_urls.return_value = {"rest_base": "https://fb.kiwoom.com"}

        result = await _get_rest_base()
        assert result == "https://fb.kiwoom.com"
