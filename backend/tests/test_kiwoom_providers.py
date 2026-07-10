"""kiwoom_providers.py 단위 테스트 — 키움증권 Provider 구현체 검증.

KiwoomAuthProvider: __init__ 캐싱, get_access_token, ensure_token, broker_name, rest_api
KiwoomAccountProvider: __init__, get_account_number, get_deposit_detail, get_balance_detail, get_account_balance
KiwoomOrderProvider: send_order 위임
KiwoomStockProvider: __init__ 타입 검증, fetch_all_stocks, fetch_stock_daily_price, fetch_stock_5day_data,
  fetch_all_stocks_5day, fetch_all_stocks_daily_confirmed
KiwoomWebSocketProvider: get_ws_uri

의존성: state (lazy import), KiwoomRestAPI, kiwoom_order.send_order, kiwoom_stock_rest, build_broker_urls
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _mock_state(broker_rest_apis=None, settings_cache=None):
    """engine_state.state mock 생성."""
    mock = MagicMock()
    mock.broker_rest_apis = broker_rest_apis if broker_rest_apis is not None else {}
    mock.integrated_system_settings_cache = settings_cache if settings_cache is not None else {}
    return mock


def _mock_kiwoom_rest_api():
    """KiwoomRestAPI mock 생성."""
    api = AsyncMock()
    api._ensure_token = AsyncMock(return_value=True)
    api.get_access_token = AsyncMock(return_value="test_token_123")
    api.get_account_number = AsyncMock(return_value="12345678")
    api.get_deposit_detail = AsyncMock(return_value=None)
    api.get_balance_detail = AsyncMock(return_value=None)
    return api


# ── KiwoomAuthProvider ─────────────────────────────────────────────────────────

class TestKiwoomAuthProvider:
    def test_init_creates_new_rest_api_when_not_cached(self):
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            mock_api = MagicMock()
            mock_cls.return_value = mock_api
            provider = KiwoomAuthProvider()
            mock_cls.assert_called_once()
            assert provider._rest_api is mock_api

    def test_init_reuses_cached_rest_api(self):
        cached = MagicMock()
        state = _mock_state(broker_rest_apis={"kiwoom": cached})
        with (
            patch("backend.app.services.engine_state.state", state),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            provider = KiwoomAuthProvider()
            mock_cls.assert_not_called()
            assert provider._rest_api is cached

    def test_init_caches_new_rest_api_in_state(self):
        state = _mock_state()
        with (
            patch("backend.app.services.engine_state.state", state),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            mock_api = MagicMock()
            mock_cls.return_value = mock_api
            KiwoomAuthProvider()
            assert state.broker_rest_apis["kiwoom"] is mock_api

    def test_init_passes_app_key_and_secret(self):
        settings_cache = {"kiwoom_app_key": "mykey", "kiwoom_app_secret": "mysecret"}
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            KiwoomAuthProvider()
            call_args = mock_cls.call_args
            assert call_args[0][0] == "mykey"
            assert call_args[0][1] == "mysecret"

    def test_init_prefers_real_credentials(self):
        settings_cache = {
            "kiwoom_app_key": "simkey",
            "kiwoom_app_secret": "simsecret",
            "kiwoom_app_key_real": "realkey",
            "kiwoom_app_secret_real": "realsecret",
        }
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            KiwoomAuthProvider()
            call_args = mock_cls.call_args
            assert call_args[0][0] == "realkey"
            assert call_args[0][1] == "realsecret"

    def test_init_strips_whitespace_from_credentials(self):
        settings_cache = {"kiwoom_app_key": "  key  ", "kiwoom_app_secret": "  secret  "}
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            KiwoomAuthProvider()
            call_args = mock_cls.call_args
            assert call_args[0][0] == "key"
            assert call_args[0][1] == "secret"

    def test_init_handles_missing_credentials(self):
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            KiwoomAuthProvider()
            call_args = mock_cls.call_args
            assert call_args[0][0] == ""
            assert call_args[0][1] == ""

    def test_init_sets_acnt_no_from_settings(self):
        settings_cache = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            mock_api = MagicMock()
            mock_cls.return_value = mock_api
            provider = KiwoomAuthProvider()
            assert provider._rest_api._acnt_no == "12345678"

    def test_init_prefers_real_acnt_no(self):
        settings_cache = {
            "kiwoom_account_no": "sim_acnt",
            "kiwoom_account_no_real": "real_acnt",
        }
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI") as mock_cls,
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            mock_api = MagicMock()
            mock_cls.return_value = mock_api
            provider = KiwoomAuthProvider()
            assert provider._rest_api._acnt_no == "real_acnt"

    async def test_get_access_token_delegates(self):
        mock_api = _mock_kiwoom_rest_api()
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI", return_value=mock_api),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            provider = KiwoomAuthProvider()
            result = await provider.get_access_token()
        assert result == "test_token_123"
        mock_api.get_access_token.assert_called_once()

    async def test_ensure_token_delegates(self):
        mock_api = _mock_kiwoom_rest_api()
        mock_api._ensure_token = AsyncMock(return_value=True)
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI", return_value=mock_api),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            provider = KiwoomAuthProvider()
            result = await provider.ensure_token()
        assert result is True
        mock_api._ensure_token.assert_called_once()

    def test_broker_name_returns_kiwoom(self):
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI"),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            provider = KiwoomAuthProvider()
            assert provider.broker_name == "kiwoom"

    def test_rest_api_property_returns_rest_api(self):
        mock_api = MagicMock()
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.KiwoomRestAPI", return_value=mock_api),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAuthProvider
            provider = KiwoomAuthProvider()
            assert provider.rest_api is mock_api


# ── KiwoomAccountProvider ──────────────────────────────────────────────────────

class TestKiwoomAccountProvider:
    def test_init_extracts_acnt_no_from_settings(self):
        settings_cache = {"kiwoom_account_no": "12345678"}
        auth = MagicMock()
        auth.rest_api = MagicMock()
        with patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            assert provider._acnt_no == "12345678"

    def test_init_handles_missing_acnt_no(self):
        auth = MagicMock()
        auth.rest_api = MagicMock()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            assert provider._acnt_no == ""

    def test_init_no_auth_provider(self):
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(None)
            assert provider._rest_api is None
            assert provider._auth is None

    def test_init_with_auth_provider_extracts_rest_api(self):
        auth = MagicMock()
        mock_api = MagicMock()
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            assert provider._rest_api is mock_api
            assert provider._auth is auth

    async def test_get_account_number_success(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_account_number = AsyncMock(return_value="87654321")
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_number()
        assert result == "87654321"

    async def test_get_account_number_no_rest_api(self):
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(None)
            result = await provider.get_account_number()
        assert result is None

    async def test_get_deposit_detail_success(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_deposit_detail = AsyncMock(return_value={"body": {"return_code": "0"}})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_deposit_detail(acnt_no="12345")
        assert result == {"body": {"return_code": "0"}}
        mock_api.get_deposit_detail.assert_called_once_with(acnt_no="12345")

    async def test_get_deposit_detail_uses_default_acnt_no(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_deposit_detail = AsyncMock(return_value={"body": {}})
        auth.rest_api = mock_api
        settings_cache = {"kiwoom_account_no": "99999"}
        with patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            await provider.get_deposit_detail()
        mock_api.get_deposit_detail.assert_called_once_with(acnt_no="99999")

    async def test_get_deposit_detail_no_rest_api(self):
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(None)
            result = await provider.get_deposit_detail()
        assert result is None

    async def test_get_deposit_detail_sets_acnt_no_on_rest_api(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_deposit_detail = AsyncMock(return_value={})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            await provider.get_deposit_detail(acnt_no="77777")
        assert mock_api._acnt_no == "77777"

    async def test_get_balance_detail_success(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance_detail = AsyncMock(return_value={"body": {"return_code": "0"}})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_balance_detail()
        assert result == {"body": {"return_code": "0"}}

    async def test_get_balance_detail_with_params(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance_detail = AsyncMock(return_value={})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            await provider.get_balance_detail(qry_tp="2", dmst_stex_tp="NXT")
        mock_api.get_balance_detail.assert_called_once_with("2", "NXT")

    async def test_get_balance_detail_no_rest_api(self):
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(None)
            result = await provider.get_balance_detail()
        assert result is None


# ── KiwoomAccountProvider.get_account_balance ──────────────────────────────────

class TestKiwoomAccountProviderGetAccountBalance:
    async def test_no_rest_api_returns_empty(self):
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(None)
            result = await provider.get_account_balance()
        assert result["success"] is False
        assert result["stock_list"] == []
        assert result["summary"]["tot_eval"] == 0

    async def test_token_failure_returns_empty(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=False)
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is False

    async def test_deposit_none_returns_empty(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value=None)
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is False

    async def test_deposit_return_code_nonzero_returns_empty(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "1", "return_msg": "error"}
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is False

    async def test_success_with_stock_list(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {
                "return_code": "0",
                "entr": "5000000",
                "ord_alow_amt": "4000000",
                "pymn_alow_amt": "3000000",
            }
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "10000000",
                "tot_evlt_pl": "2000000",
                "tot_pur_amt": "8000000",
                "tot_prft_rt": "25.0%",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "005930", "stk_nm": "삼성전자", "rmnd_qty": "10", "buy_uv": "50000", "cur_pric": "60000", "buy_amt": "500000", "evlt_ploss": "100000", "prft_rt": "20.0%", "crd_tp": ""},
                    {"stk_cd": "035420", "stk_nm": "NAVER", "rmnd_qty": "5", "buy_uv": "200000", "cur_pric": "210000", "buy_amt": "1000000", "evlt_ploss": "50000", "prft_rt": "5.0%", "crd_tp": ""},
                ],
            }
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert result["summary"]["deposit"] == 5000000
        assert result["summary"]["orderable"] == 4000000
        assert result["summary"]["withdrawable"] == 3000000
        assert result["summary"]["tot_eval"] == 10000000
        assert result["summary"]["tot_pnl"] == 2000000
        assert result["summary"]["tot_buy"] == 8000000
        assert result["summary"]["total_rate"] == 25.0
        assert len(result["stock_list"]) == 2
        assert result["stock_list"][0]["stk_cd"] == "005930"
        assert result["stock_list"][0]["stk_nm"] == "삼성전자"
        assert result["stock_list"][0]["qty"] == 10
        assert result["stock_list"][0]["buy_price"] == 50000
        assert result["stock_list"][0]["cur_price"] == 60000
        assert result["stock_list"][0]["buy_amt"] == 500000
        assert result["stock_list"][0]["pnl_amt"] == 100000
        assert result["stock_list"][0]["pnl_rate"] == 20.0
        assert result["stock_list"][0]["crd_tp"] == ""

    async def test_success_filters_zero_qty(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "entr": "0", "ord_alow_amt": "0", "pymn_alow_amt": "0"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "0",
                "tot_evlt_pl": "0",
                "tot_pur_amt": "0",
                "tot_prft_rt": "0",
                "prsm_dpst_aset_amt": "10000000",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "005930", "stk_nm": "삼성전자", "rmnd_qty": "0", "buy_uv": "0", "cur_pric": "0", "buy_amt": "0", "evlt_ploss": "0", "prft_rt": "0", "crd_tp": ""},
                    {"stk_cd": "035420", "stk_nm": "NAVER", "rmnd_qty": "5", "buy_uv": "200000", "cur_pric": "210000", "buy_amt": "1000000", "evlt_ploss": "50000", "prft_rt": "5.0%", "crd_tp": ""},
                ],
            }
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert len(result["stock_list"]) == 1
        assert result["stock_list"][0]["stk_cd"] == "035420"
        # deposit이 0이므로 bal에서 prsm_dpst_aset_amt 사용
        assert result["summary"]["deposit"] == 10000000

    async def test_success_no_stocks(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "entr": "10000000", "ord_alow_amt": "0", "pymn_alow_amt": "0"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "0",
                "tot_evlt_pl": "0",
                "tot_pur_amt": "0",
                "tot_prft_rt": "0",
                "acnt_evlt_remn_indv_tot": [],
            }
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert result["stock_list"] == []
        assert result["summary"]["total_rate"] == 0.0

    async def test_balance_none_skips_stock_list(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "entr": "5000000", "ord_alow_amt": "0", "pymn_alow_amt": "0"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value=None)
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert result["stock_list"] == []
        assert result["summary"]["deposit"] == 5000000

    async def test_strips_a_prefix_from_stk_cd(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "entr": "0", "ord_alow_amt": "0", "pymn_alow_amt": "0"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "0", "tot_evlt_pl": "0", "tot_pur_amt": "0", "tot_prft_rt": "0",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "A005930", "stk_nm": "삼성전자", "rmnd_qty": "10", "buy_uv": "0", "cur_pric": "0", "buy_amt": "0", "evlt_ploss": "0", "prft_rt": "0", "crd_tp": ""},
                ],
            }
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["stock_list"][0]["stk_cd"] == "005930"

    async def test_skips_empty_stk_cd(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "entr": "0", "ord_alow_amt": "0", "pymn_alow_amt": "0"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "0", "tot_evlt_pl": "0", "tot_pur_amt": "0", "tot_prft_rt": "0",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "", "stk_nm": "", "rmnd_qty": "10"},
                    {"stk_cd": "005930", "stk_nm": "삼성전자", "rmnd_qty": "5"},
                ],
            }
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert len(result["stock_list"]) == 1
        assert result["stock_list"][0]["stk_cd"] == "005930"

    async def test_comma_values_parsed(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "entr": "5,000,000", "ord_alow_amt": "4,000,000", "pymn_alow_amt": "3,000,000"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "10,000,000", "tot_evlt_pl": "2,000,000", "tot_pur_amt": "8,000,000",
                "tot_prft_rt": "25.0%",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "005930", "stk_nm": "삼성전자", "rmnd_qty": "10", "buy_uv": "50,000", "cur_pric": "60,000", "buy_amt": "500,000", "evlt_ploss": "100,000", "prft_rt": "20.0%", "crd_tp": ""},
                ],
            }
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["summary"]["deposit"] == 5000000
        assert result["summary"]["tot_eval"] == 10000000
        assert result["stock_list"][0]["qty"] == 10
        assert result["stock_list"][0]["buy_price"] == 50000

    async def test_d2_entra_fallback(self):
        """entr이 없을 때 d2_entra 사용."""
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "d2_entra": "7000000", "ord_alow_amt": "0", "pymn_alow_amt": "0"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "tot_evlt_amt": "0", "tot_evlt_pl": "0", "tot_pur_amt": "0", "tot_prft_rt": "0", "acnt_evlt_remn_indv_tot": []}
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["summary"]["deposit"] == 7000000

    async def test_balance_return_code_nonzero_skips_summary(self):
        """balance return_code != 0이면 summary는 0, stock_list는 빈 배열."""
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api._ensure_token = AsyncMock(return_value=True)
        mock_api.get_deposit_detail = AsyncMock(return_value={
            "body": {"return_code": "0", "entr": "5000000", "ord_alow_amt": "0", "pymn_alow_amt": "0"}
        })
        mock_api.get_balance_detail = AsyncMock(return_value={
            "body": {"return_code": "1", "tot_evlt_amt": "999", "acnt_evlt_remn_indv_tot": []}
        })
        auth.rest_api = mock_api
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.kiwoom_providers.asyncio.sleep", new_callable=AsyncMock),
        ):
            from backend.app.core.kiwoom_providers import KiwoomAccountProvider
            provider = KiwoomAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert result["summary"]["tot_eval"] == 0
        assert result["summary"]["deposit"] == 5000000
        assert result["stock_list"] == []


# ── KiwoomOrderProvider ────────────────────────────────────────────────────────

class TestKiwoomOrderProvider:
    def test_init_with_auth(self):
        auth = MagicMock()
        from backend.app.core.kiwoom_providers import KiwoomOrderProvider
        provider = KiwoomOrderProvider(auth)
        assert provider._auth is auth

    def test_init_no_auth(self):
        from backend.app.core.kiwoom_providers import KiwoomOrderProvider
        provider = KiwoomOrderProvider(None)
        assert provider._auth is None

    async def test_send_order_delegates_to_kiwoom_order(self):
        from backend.app.core.kiwoom_providers import KiwoomOrderProvider
        provider = KiwoomOrderProvider(None)
        with patch("backend.app.core.kiwoom_order.send_order", new_callable=AsyncMock, return_value={"rt_cd": "0"}) as mock_send:
            result = await provider.send_order(
                {"setting": "val"}, "tok123", "BUY", "005930", 10, price=50000, trde_tp="3", orig_ord_no=""
            )
        assert result == {"rt_cd": "0"}
        mock_send.assert_called_once_with(
            {"setting": "val"}, "tok123", "BUY", "005930", 10,
            price=50000, trde_tp="3", orig_ord_no=""
        )

    async def test_send_order_default_params(self):
        from backend.app.core.kiwoom_providers import KiwoomOrderProvider
        provider = KiwoomOrderProvider(None)
        with patch("backend.app.core.kiwoom_order.send_order", new_callable=AsyncMock, return_value={}) as mock_send:
            await provider.send_order({}, "tok", "SELL", "000660", 5)
        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["price"] == 0
        assert call_kwargs.kwargs["trde_tp"] == "3"
        assert call_kwargs.kwargs["orig_ord_no"] == ""


# ── KiwoomStockProvider ────────────────────────────────────────────────────────

class TestKiwoomStockProvider:
    def test_init_with_auth(self):
        from backend.app.core.kiwoom_providers import KiwoomAuthProvider, KiwoomStockProvider
        auth = MagicMock(spec=KiwoomAuthProvider)
        mock_api = MagicMock()
        auth.rest_api = mock_api
        provider = KiwoomStockProvider(auth)
        assert provider._auth is auth
        assert provider._rest_api is mock_api

    def test_init_no_auth(self):
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        provider = KiwoomStockProvider(None)
        assert provider._auth is None
        assert provider._rest_api is None

    def test_init_wrong_auth_type_raises(self):
        wrong_auth = MagicMock()  # KiwoomAuthProvider가 아님
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        with pytest.raises(TypeError, match="KiwoomAuthProvider"):
            KiwoomStockProvider(wrong_auth)

    async def test_fetch_all_stocks_no_rest_api(self):
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        provider = KiwoomStockProvider(None)
        result = await provider.fetch_all_stocks()
        assert result == []

    async def test_fetch_all_stocks_delegates(self):
        from backend.app.core.kiwoom_providers import KiwoomAuthProvider, KiwoomStockProvider
        auth = MagicMock(spec=KiwoomAuthProvider)
        mock_api = MagicMock()
        auth.rest_api = mock_api
        provider = KiwoomStockProvider(auth)
        with patch("backend.app.core.kiwoom_stock_rest.fetch_ka10099_unified", new_callable=AsyncMock, return_value=[{"code": "005930"}]) as mock_fetch:
            result = await provider.fetch_all_stocks(http_timeout=30.0)
        assert result == [{"code": "005930"}]
        mock_fetch.assert_called_once_with(mock_api, http_timeout=30.0)

    async def test_fetch_stock_daily_price_no_rest_api(self):
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        provider = KiwoomStockProvider(None)
        result = await provider.fetch_stock_daily_price("005930", "20260711")
        assert result is None

    async def test_fetch_stock_daily_price_delegates(self):
        from backend.app.core.kiwoom_providers import KiwoomAuthProvider, KiwoomStockProvider
        auth = MagicMock(spec=KiwoomAuthProvider)
        mock_api = MagicMock()
        auth.rest_api = mock_api
        provider = KiwoomStockProvider(auth)
        with patch("backend.app.core.kiwoom_stock_rest.fetch_ka10081_daily_price", new_callable=AsyncMock, return_value={"close": "70000"}) as mock_fetch:
            result = await provider.fetch_stock_daily_price("005930", "20260711")
        assert result == {"close": "70000"}
        mock_fetch.assert_called_once_with(mock_api, "005930", "20260711")

    async def test_fetch_stock_5day_data_no_rest_api(self):
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        provider = KiwoomStockProvider(None)
        result = await provider.fetch_stock_5day_data("005930", "20260711")
        assert result is None

    async def test_fetch_stock_5day_data_delegates(self):
        from backend.app.core.kiwoom_providers import KiwoomAuthProvider, KiwoomStockProvider
        auth = MagicMock(spec=KiwoomAuthProvider)
        mock_api = MagicMock()
        auth.rest_api = mock_api
        provider = KiwoomStockProvider(auth)
        with patch("backend.app.core.kiwoom_stock_rest.fetch_ka10081_daily_5d_data", new_callable=AsyncMock, return_value={"avg_vol": "100000"}) as mock_fetch:
            result = await provider.fetch_stock_5day_data("005930", "20260711")
        assert result == {"avg_vol": "100000"}
        mock_fetch.assert_called_once_with(mock_api, "005930", "20260711")

    async def test_fetch_all_stocks_5day_no_rest_api(self):
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        provider = KiwoomStockProvider(None)
        result = await provider.fetch_all_stocks_5day(["005930"], "20260711")
        assert result == {}

    async def test_fetch_all_stocks_5day_delegates(self):
        from backend.app.core.kiwoom_providers import KiwoomAuthProvider, KiwoomStockProvider
        auth = MagicMock(spec=KiwoomAuthProvider)
        mock_api = MagicMock()
        auth.rest_api = mock_api
        provider = KiwoomStockProvider(auth)
        on_progress = MagicMock()
        with patch("backend.app.core.kiwoom_stock_rest.fetch_ka10081_all_stocks_5day", new_callable=AsyncMock, return_value={"005930": {}}) as mock_fetch:
            result = await provider.fetch_all_stocks_5day(["005930"], "20260711", interval_sec=0.5, on_progress=on_progress)
        assert result == {"005930": {}}
        mock_fetch.assert_called_once_with(mock_api, ["005930"], "20260711", interval_sec=0.5, on_progress=on_progress)

    async def test_fetch_all_stocks_daily_confirmed_no_rest_api(self):
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        provider = KiwoomStockProvider(None)
        result = await provider.fetch_all_stocks_daily_confirmed(["005930"], "20260711")
        assert result == {}

    async def test_fetch_all_stocks_daily_confirmed_delegates(self):
        from backend.app.core.kiwoom_providers import KiwoomAuthProvider, KiwoomStockProvider
        auth = MagicMock(spec=KiwoomAuthProvider)
        mock_api = MagicMock()
        auth.rest_api = mock_api
        provider = KiwoomStockProvider(auth)
        on_progress = MagicMock()
        with patch("backend.app.core.kiwoom_stock_rest.fetch_ka10081_all_stocks_daily_confirmed", new_callable=AsyncMock, return_value={"005930": {}}) as mock_fetch:
            result = await provider.fetch_all_stocks_daily_confirmed(["005930"], "20260711", interval_sec=0.5, on_progress=on_progress)
        assert result == {"005930": {}}
        mock_fetch.assert_called_once_with(mock_api, ["005930"], "20260711", interval_sec=0.5, on_progress=on_progress)


# ── KiwoomWebSocketProvider ────────────────────────────────────────────────────

class TestKiwoomWebSocketProvider:
    def test_init_with_auth(self):
        auth = MagicMock()
        from backend.app.core.kiwoom_providers import KiwoomWebSocketProvider
        provider = KiwoomWebSocketProvider(auth)
        assert provider._auth is auth

    def test_init_no_auth(self):
        from backend.app.core.kiwoom_providers import KiwoomWebSocketProvider
        provider = KiwoomWebSocketProvider(None)
        assert provider._auth is None

    def test_get_ws_uri_returns_broker_urls(self):
        from backend.app.core.kiwoom_providers import KiwoomWebSocketProvider
        provider = KiwoomWebSocketProvider(None)
        with patch("backend.app.core.broker_urls.build_broker_urls", return_value={"ws_uri": "wss://kiwoom.example.com/ws"}):
            uri = provider.get_ws_uri()
        assert uri == "wss://kiwoom.example.com/ws"

    def test_get_ws_uri_calls_with_kiwoom(self):
        from backend.app.core.kiwoom_providers import KiwoomWebSocketProvider
        provider = KiwoomWebSocketProvider(None)
        with patch("backend.app.core.broker_urls.build_broker_urls", return_value={"ws_uri": "wss://test"}) as mock_fn:
            provider.get_ws_uri()
            mock_fn.assert_called_once_with("kiwoom")
