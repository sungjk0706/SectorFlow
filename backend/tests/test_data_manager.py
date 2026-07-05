"""data_manager.py 단위 테스트 — 계좌 수익률, 종목명 조회, 브로커 설정 로드 검증.

hang 방지 원칙:
- httpx.AsyncClient를 mock으로 대체 (실제 HTTP 요청 금지)
- engine_state.state를 mock으로 대체
- encryption.decrypt_value를 mock으로 대체
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.data_manager import (
    _norm_stk_cd,
    get_stock_name,
    get_account_profit_rate,
    get_main_account_info,
    _load_broker_settings,
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


# ── _load_broker_settings ─────────────────────────────────────────────────────

class TestLoadBrokerSettings:
    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.effective_trade_mode")
    @patch("backend.app.core.encryption.decrypt_value")
    @patch("backend.app.services.engine_state.state")
    async def test_success(self, mock_state, mock_decrypt, mock_trade_mode):
        mock_state.integrated_system_settings_cache = {
            "broker": "kiwoom",
            "kiwoom_app_key": "gAAAAencrypted_key",
            "kiwoom_app_secret": "gAAAAencrypted_secret",
            "kiwoom_account_no": "12345678",
        }
        mock_decrypt.return_value = "decrypted_value"
        mock_trade_mode.return_value = "test"

        result = await _load_broker_settings()
        assert result is not None
        assert result["broker"] == "kiwoom"
        assert result["kiwoom_app_key"] == "decrypted_value"
        assert result["kiwoom_app_secret"] == "decrypted_value"
        assert result["kiwoom_account_no"] == "12345678"
        assert result["trade_mode"] == "test"

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.effective_trade_mode")
    @patch("backend.app.core.encryption.decrypt_value")
    @patch("backend.app.services.engine_state.state")
    async def test_plain_text_key_not_decrypted(self, mock_state, mock_decrypt, mock_trade_mode):
        mock_state.integrated_system_settings_cache = {
            "broker": "kiwoom",
            "kiwoom_app_key": "plain_key",
            "kiwoom_app_secret": "plain_secret",
            "kiwoom_account_no": "87654321",
        }
        mock_trade_mode.return_value = "real"

        result = await _load_broker_settings()
        assert result is not None
        assert result["kiwoom_app_key"] == "plain_key"
        assert result["kiwoom_app_secret"] == "plain_secret"
        assert result["trade_mode"] == "real"

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.effective_trade_mode")
    @patch("backend.app.services.engine_state.state")
    async def test_exception_returns_none(self, mock_state, mock_trade_mode):
        mock_state.integrated_system_settings_cache = {}
        mock_trade_mode.side_effect = Exception("boom")

        result = await _load_broker_settings()
        assert result is None

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.effective_trade_mode")
    @patch("backend.app.core.encryption.decrypt_value")
    @patch("backend.app.services.engine_state.state")
    async def test_empty_values(self, mock_state, mock_decrypt, mock_trade_mode):
        mock_state.integrated_system_settings_cache = {
            "broker": "kiwoom",
            "kiwoom_app_key": "",
            "kiwoom_app_secret": "",
            "kiwoom_account_no": "",
        }
        mock_trade_mode.return_value = "test"

        result = await _load_broker_settings()
        assert result is not None
        assert result["kiwoom_app_key"] == ""
        assert result["kiwoom_app_secret"] == ""
        assert result["kiwoom_account_no"] == ""


# ── get_account_profit_rate ───────────────────────────────────────────────────

class TestGetAccountProfitRate:
    @pytest.mark.asyncio
    async def test_no_access_token_returns_empty(self):
        result = await get_account_profit_rate("")
        assert result["success"] is False
        assert result["stock_list"] == []

    @pytest.mark.asyncio
    async def test_none_access_token_returns_empty(self):
        result = await get_account_profit_rate(None)
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_success_response(self, mock_state, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {
            "broker": "kiwoom",
            "kiwoom_account_no": "12345678",
        }
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "body": {
                "acnt_evlt_remn_indv_tot": [
                    {
                        "stk_cd": "005930",
                        "stk_nm": "삼성전자",
                        "rmnd_qty": "100",
                        "buy_uv": "50,000",
                        "cur_pric": "60,000",
                        "buy_amt": "5,000,000",
                        "evlt_ploss": "1,000,000",
                        "prft_rt": "20.5%",
                    },
                    {
                        "stk_cd": "000660",
                        "stk_nm": "SK하이닉스",
                        "rmnd_qty": "0",
                        "buy_uv": "0",
                        "cur_pric": "0",
                        "buy_amt": "0",
                        "evlt_ploss": "0",
                        "prft_rt": "0%",
                    },
                ],
                "tot_evlt_amt": "6,000,000",
                "tot_evlt_pl": "1,000,000",
                "tot_pur_amt": "5,000,000",
                "tot_prft_rt": "20.0%",
            }
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_account_profit_rate("test_token")
        assert result["success"] is True
        assert len(result["stock_list"]) == 1
        assert result["stock_list"][0]["stk_cd"] == "005930"
        assert result["stock_list"][0]["qty"] == 100
        assert result["stock_list"][0]["pnl_rate"] == 20.5
        assert result["summary"]["tot_eval"] == 6000000
        assert result["summary"]["tot_pnl"] == 1000000
        assert result["summary"]["tot_buy"] == 5000000
        assert result["summary"]["total_rate"] == 20.0

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_non_200_returns_empty(self, mock_state, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "123"}
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_account_profit_rate("test_token")
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_exception_returns_empty(self, mock_state, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "123"}
        mock_rest_base.side_effect = Exception("network error")

        result = await get_account_profit_rate("test_token")
        assert result["success"] is False

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_no_body_key_uses_data_directly(self, mock_state, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": ""}
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "acnt_evlt_remn_indv_tot": [],
            "tot_evlt_amt": "0",
            "tot_evlt_pl": "0",
            "tot_pur_amt": "0",
            "tot_prft_rt": "0%",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_account_profit_rate("test_token")
        assert result["success"] is True
        assert result["stock_list"] == []

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_stock_item_parse_exception_skipped(self, mock_state, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "123"}
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "body": {
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "005930", "stk_nm": "삼성전자", "rmnd_qty": "10", "buy_uv": "1", "cur_pric": "2", "buy_amt": "3", "evlt_ploss": "4", "prft_rt": "5%"},
                    {"stk_cd": "BAD", "rmnd_qty": "not_a_number"},
                ],
                "tot_evlt_amt": "0",
                "tot_evlt_pl": "0",
                "tot_pur_amt": "0",
                "tot_prft_rt": "0%",
            }
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_account_profit_rate("test_token")
        assert result["success"] is True
        assert len(result["stock_list"]) == 1


# ── get_main_account_info ─────────────────────────────────────────────────────

class TestGetMainAccountInfo:
    @pytest.mark.asyncio
    async def test_no_access_token_returns_fallback(self):
        result = await get_main_account_info("")
        assert result == ["0", "0", "0", "0", "0.00%"]

    @pytest.mark.asyncio
    async def test_none_access_token_returns_fallback(self):
        result = await get_main_account_info(None)
        assert result == ["0", "0", "0", "0", "0.00%"]

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager._load_broker_settings", new_callable=AsyncMock)
    async def test_settings_none_returns_fallback(self, mock_load):
        mock_load.return_value = None
        result = await get_main_account_info("token")
        assert result == ["0", "0", "0", "0", "0.00%"]

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.data_manager._load_broker_settings", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_success_response(self, mock_state, mock_load, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "12345678"}
        mock_load.return_value = {"broker": "kiwoom"}
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "body": {
                "return_code": "0",
                "entr": "1,000,000",
                "ord_alow_amt": "800,000",
                "pymn_alow_amt": "500,000",
            }
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_main_account_info("token")
        assert result[0] == "1,000,000"
        assert result[1] == "800,000"
        assert result[2] == "500,000"
        assert result[3] == "0"
        assert result[4] == "0.00%"

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.data_manager._load_broker_settings", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_non_zero_return_code_returns_fallback(self, mock_state, mock_load, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "123"}
        mock_load.return_value = {"broker": "kiwoom"}
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "body": {
                "return_code": "1",
                "return_msg": "에러",
            }
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_main_account_info("token")
        assert result == ["0", "0", "0", "0", "0.00%"]

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.data_manager._load_broker_settings", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_non_200_returns_fallback(self, mock_state, mock_load, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "123"}
        mock_load.return_value = {"broker": "kiwoom"}
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_main_account_info("token")
        assert result == ["0", "0", "0", "0", "0.00%"]

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.data_manager._load_broker_settings", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_exception_returns_fallback(self, mock_state, mock_load, mock_rest_base):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "123"}
        mock_load.return_value = {"broker": "kiwoom"}
        mock_rest_base.side_effect = Exception("network error")

        result = await get_main_account_info("token")
        assert result == ["0", "0", "0", "0", "0.00%"]

    @pytest.mark.asyncio
    @patch("backend.app.services.data_manager.httpx.AsyncClient")
    @patch("backend.app.services.data_manager._get_rest_base", new_callable=AsyncMock)
    @patch("backend.app.services.data_manager._load_broker_settings", new_callable=AsyncMock)
    @patch("backend.app.services.engine_state.state")
    async def test_d2_entra_fallback(self, mock_state, mock_load, mock_rest_base, mock_client_cls):
        mock_state.integrated_system_settings_cache = {"broker": "kiwoom", "kiwoom_account_no": "123"}
        mock_load.return_value = {"broker": "kiwoom"}
        mock_rest_base.return_value = "https://api.kiwoom.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "body": {
                "return_code": "0",
                "d2_entra": "2,000,000",
                "ord_alow_amt": "1,500,000",
                "pymn_alow_amt": "1,000,000",
            }
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await get_main_account_info("token")
        assert result[0] == "2,000,000"
