"""ls_providers.py 단위 테스트 — LS증권 Provider 구현체 검증.

LsAuthProvider: __init__ 캐싱, get_access_token, ensure_token, broker_name, rest_api
LsAccountProvider: __init__, get_account_number, get_deposit_detail, get_balance_detail, get_account_balance
LsOrderProvider: send_order (buy/sell/unsupported), 성공/실패
LsWebSocketProvider: get_ws_uri

의존성: state (lazy import), LsRestAPI, build_broker_urls
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _mock_state(broker_rest_apis=None, settings_cache=None):
    """engine_state.state mock 생성."""
    mock = MagicMock()
    mock.broker_rest_apis = broker_rest_apis if broker_rest_apis is not None else {}
    mock.integrated_system_settings_cache = settings_cache if settings_cache is not None else {}
    return mock


def _mock_ls_rest_api():
    """LsRestAPI mock 생성."""
    api = AsyncMock()
    api.ensure_token = AsyncMock(return_value=True)
    api.get_token = MagicMock(return_value="test_token_123")
    api.get_balance = AsyncMock(return_value=None)
    api.buy_order = AsyncMock(return_value=None)
    api.sell_order = AsyncMock(return_value=None)
    return api


# ── LsAuthProvider ─────────────────────────────────────────────────────────────

class TestLsAuthProvider:
    def test_init_creates_new_rest_api_when_not_cached(self):
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.ls_providers.LsRestAPI") as mock_cls,
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            mock_api = MagicMock()
            mock_cls.return_value = mock_api
            provider = LsAuthProvider()
            mock_cls.assert_called_once()
            assert provider._rest_api is mock_api

    def test_init_reuses_cached_rest_api(self):
        cached = MagicMock()
        state = _mock_state(broker_rest_apis={"ls": cached})
        with (
            patch("backend.app.services.engine_state.state", state),
            patch("backend.app.core.ls_providers.LsRestAPI") as mock_cls,
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            provider = LsAuthProvider()
            mock_cls.assert_not_called()
            assert provider._rest_api is cached

    def test_init_caches_new_rest_api_in_state(self):
        state = _mock_state()
        with (
            patch("backend.app.services.engine_state.state", state),
            patch("backend.app.core.ls_providers.LsRestAPI") as mock_cls,
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            mock_api = MagicMock()
            mock_cls.return_value = mock_api
            LsAuthProvider()
            assert state.broker_rest_apis["ls"] is mock_api

    def test_init_passes_app_key_and_secret(self):
        settings_cache = {"ls_app_key": "mykey", "ls_app_secret": "mysecret"}
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
            patch("backend.app.core.ls_providers.LsRestAPI") as mock_cls,
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            LsAuthProvider()
            call_args = mock_cls.call_args
            assert call_args[0][0] == "mykey"
            assert call_args[0][1] == "mysecret"

    def test_init_strips_whitespace_from_credentials(self):
        settings_cache = {"ls_app_key": "  key  ", "ls_app_secret": "  secret  "}
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
            patch("backend.app.core.ls_providers.LsRestAPI") as mock_cls,
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            LsAuthProvider()
            call_args = mock_cls.call_args
            assert call_args[0][0] == "key"
            assert call_args[0][1] == "secret"

    def test_init_handles_missing_credentials(self):
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.ls_providers.LsRestAPI") as mock_cls,
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            LsAuthProvider()
            call_args = mock_cls.call_args
            assert call_args[0][0] == ""
            assert call_args[0][1] == ""

    @pytest.mark.asyncio
    async def test_get_access_token_success(self):
        mock_api = _mock_ls_rest_api()
        mock_api.ensure_token = AsyncMock(return_value=True)
        mock_api.get_token = MagicMock(return_value="token_abc")
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.ls_providers.LsRestAPI", return_value=mock_api),
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            provider = LsAuthProvider()
            token = await provider.get_access_token()
        assert token == "token_abc"

    @pytest.mark.asyncio
    async def test_get_access_token_failure_returns_none(self):
        mock_api = _mock_ls_rest_api()
        mock_api.ensure_token = AsyncMock(return_value=False)
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.ls_providers.LsRestAPI", return_value=mock_api),
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            provider = LsAuthProvider()
            token = await provider.get_access_token()
        assert token is None

    @pytest.mark.asyncio
    async def test_ensure_token_delegates(self):
        mock_api = _mock_ls_rest_api()
        mock_api.ensure_token = AsyncMock(return_value=True)
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.ls_providers.LsRestAPI", return_value=mock_api),
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            provider = LsAuthProvider()
            result = await provider.ensure_token()
        assert result is True

    def test_broker_name_returns_ls(self):
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.ls_providers.LsRestAPI"),
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            provider = LsAuthProvider()
            assert provider.broker_name == "ls"

    def test_rest_api_property_returns_rest_api(self):
        mock_api = MagicMock()
        with (
            patch("backend.app.services.engine_state.state", _mock_state()),
            patch("backend.app.core.ls_providers.LsRestAPI", return_value=mock_api),
        ):
            from backend.app.core.ls_providers import LsAuthProvider
            provider = LsAuthProvider()
            assert provider.rest_api is mock_api


# ── LsAccountProvider ──────────────────────────────────────────────────────────

class TestLsAccountProvider:
    def test_init_extracts_acnt_no_from_settings(self):
        settings_cache = {"ls_account_no": "12345678"}
        auth = MagicMock()
        auth.rest_api = MagicMock()
        with (
            patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)),
        ):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            assert provider._acnt_no == "12345678"

    def test_init_handles_missing_acnt_no(self):
        auth = MagicMock()
        auth.rest_api = MagicMock()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            assert provider._acnt_no == ""

    def test_init_preserves_whitespace_acnt_no(self):
        # 소스 코드: str(... or "") — strip() 호출 없음
        settings_cache = {"ls_account_no": "  12345  "}
        auth = MagicMock()
        auth.rest_api = MagicMock()
        with patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            assert provider._acnt_no == "  12345  "

    def test_init_no_rest_api(self):
        auth = MagicMock()
        del auth.rest_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            assert provider._rest_api is None

    @pytest.mark.asyncio
    async def test_get_account_number_returns_acnt_no(self):
        settings_cache = {"ls_account_no": "999999"}
        auth = MagicMock()
        auth.rest_api = MagicMock()
        with patch("backend.app.services.engine_state.state", _mock_state(settings_cache=settings_cache)):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_number()
        assert result == "999999"

    @pytest.mark.asyncio
    async def test_get_deposit_detail_no_rest_api_returns_none(self):
        auth = MagicMock()
        del auth.rest_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_deposit_detail()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_deposit_detail_success(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={"rsp_cd": "00000", "data": "ok"})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_deposit_detail()
        assert result == {"rsp_cd": "00000", "data": "ok"}

    @pytest.mark.asyncio
    async def test_get_deposit_detail_failure_rsp_cd(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={"rsp_cd": "99999", "rsp_msg": "err"})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_deposit_detail()
        assert result == {"rsp_cd": "99999", "rsp_msg": "err"}

    @pytest.mark.asyncio
    async def test_get_balance_detail_no_rest_api_returns_none(self):
        auth = MagicMock()
        del auth.rest_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_balance_detail()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_balance_detail_success(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={"rsp_cd": "00040", "data": "balance"})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_balance_detail()
        assert result == {"rsp_cd": "00040", "data": "balance"}

    @pytest.mark.asyncio
    async def test_get_balance_detail_none_response(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value=None)
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_balance_detail()
        assert result is None


# ── get_account_balance ────────────────────────────────────────────────────────

class TestGetAccountBalance:
    @pytest.mark.asyncio
    async def test_no_rest_api_returns_empty(self):
        auth = MagicMock()
        del auth.rest_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is False
        assert result["stock_list"] == []
        assert result["summary"]["tot_eval"] == 0

    @pytest.mark.asyncio
    async def test_failure_rsp_cd_returns_empty(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={"rsp_cd": "99999", "rsp_msg": "err"})
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_none_response_returns_empty(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value=None)
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_success_with_stock_list(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={
            "rsp_cd": "00000",
            "t0424OutBlock": {
                "sunamt1": "5000000",
                "tappamt": "10000000",
                "mamt": "8000000",
                "tdtsunik": "2000000",
            },
            "t0424OutBlock1": [
                {"expcode": "005930", "hname": "삼성전자", "janqty": "10", "pamt": "50000", "price": "60000", "appamt": "600000", "dtsunik": "100000", "sunikrt": "20.0"},
                {"expcode": "035420", "hname": "NAVER", "janqty": "5", "pamt": "200000", "price": "210000", "appamt": "1050000", "dtsunik": "50000", "sunikrt": "5.0"},
            ],
        })
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert result["summary"]["deposit"] == 5000000
        assert result["summary"]["tot_eval"] == 10000000
        assert result["summary"]["tot_buy"] == 8000000
        assert result["summary"]["tot_pnl"] == 2000000
        assert result["summary"]["total_rate"] == 25.0
        assert len(result["stock_list"]) == 2
        assert result["stock_list"][0]["stk_cd"] == "005930"
        assert result["stock_list"][0]["stk_nm"] == "삼성전자"
        assert result["stock_list"][0]["qty"] == 10
        assert result["stock_list"][0]["buy_price"] == 50000
        assert result["stock_list"][0]["eval_price"] == 60000
        assert result["stock_list"][0]["eval_rate"] == 20.0

    @pytest.mark.asyncio
    async def test_success_filters_zero_qty(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={
            "rsp_cd": "00040",
            "t0424OutBlock": {
                "sunamt1": "0", "tappamt": "0", "mamt": "0", "tdtsunik": "0",
            },
            "t0424OutBlock1": [
                {"expcode": "005930", "hname": "삼성전자", "janqty": "0", "pamt": "0", "price": "0", "appamt": "0", "dtsunik": "0", "sunikrt": "0"},
                {"expcode": "035420", "hname": "NAVER", "janqty": "5", "pamt": "200000", "price": "210000", "appamt": "1050000", "dtsunik": "50000", "sunikrt": "5.0"},
            ],
        })
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert len(result["stock_list"]) == 1
        assert result["stock_list"][0]["stk_cd"] == "035420"

    @pytest.mark.asyncio
    async def test_success_no_stocks(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={
            "rsp_cd": "00000",
            "t0424OutBlock": {
                "sunamt1": "10000000", "tappamt": "0", "mamt": "0", "tdtsunik": "0",
            },
            "t0424OutBlock1": [],
        })
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        assert result["stock_list"] == []
        assert result["summary"]["total_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_total_rate_calculation(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.get_balance = AsyncMock(return_value={
            "rsp_cd": "00000",
            "t0424OutBlock": {
                "sunamt1": "0", "tappamt": "1100000", "mamt": "1000000", "tdtsunik": "100000",
            },
            "t0424OutBlock1": [],
        })
        auth.rest_api = mock_api
        with patch("backend.app.services.engine_state.state", _mock_state()):
            from backend.app.core.ls_providers import LsAccountProvider
            provider = LsAccountProvider(auth)
            result = await provider.get_account_balance()
        assert result["success"] is True
        # total_rate = round((1100000 / 1000000 - 1.0) * 100, 2) = 10.0
        assert result["summary"]["total_rate"] == 10.0


# ── LsOrderProvider ────────────────────────────────────────────────────────────

class TestLsOrderProvider:
    @pytest.mark.asyncio
    async def test_no_rest_api_returns_failure(self):
        auth = MagicMock()
        del auth.rest_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        result = await provider.send_order({}, "token", "buy", "005930", 10, price=50000)
        assert result["success"] is False
        assert "Not initialized" in result["error"]

    @pytest.mark.asyncio
    async def test_buy_order_success(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.buy_order = AsyncMock(return_value={
            "rsp_cd": "00000",
            "CSPAT00601OutBlock2": {"OrdNo": "12345"},
        })
        auth.rest_api = mock_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        result = await provider.send_order({}, "token", "buy", "005930", 10, price=50000, trde_tp="3")
        assert result["success"] is True
        assert result["order_no"] == "12345"
        mock_api.buy_order.assert_called_once_with(stock_code="A005930", quantity=10, price=50000.0, order_type="3")

    @pytest.mark.asyncio
    async def test_sell_order_success(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.sell_order = AsyncMock(return_value={
            "rsp_cd": "00040",
            "CSPAT00601OutBlock2": {"OrdNo": "67890"},
        })
        auth.rest_api = mock_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        result = await provider.send_order({}, "token", "sell", "005930", 10, price=50000, trde_tp="3")
        assert result["success"] is True
        assert result["order_no"] == "67890"
        mock_api.sell_order.assert_called_once_with(stock_code="A005930", quantity=10, price=50000.0, order_type="3")

    @pytest.mark.asyncio
    async def test_buy_order_failure_rsp_cd(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.buy_order = AsyncMock(return_value={
            "rsp_cd": "99999",
            "rsp_msg": "잔액부족",
        })
        auth.rest_api = mock_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        result = await provider.send_order({}, "token", "buy", "005930", 10, price=50000)
        assert result["success"] is False
        assert result["error"] == "잔액부족"

    @pytest.mark.asyncio
    async def test_sell_order_failure_rsp_cd(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.sell_order = AsyncMock(return_value={
            "rsp_cd": "99999",
            "rsp_msg": "주문불가",
        })
        auth.rest_api = mock_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        result = await provider.send_order({}, "token", "sell", "005930", 10, price=50000)
        assert result["success"] is False
        assert result["error"] == "주문불가"

    @pytest.mark.asyncio
    async def test_none_response_returns_network_error(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.buy_order = AsyncMock(return_value=None)
        auth.rest_api = mock_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        result = await provider.send_order({}, "token", "buy", "005930", 10, price=50000)
        assert result["success"] is False
        assert result["error"] == "Network Error"

    @pytest.mark.asyncio
    async def test_buy_prepends_a_prefix(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.buy_order = AsyncMock(return_value={"rsp_cd": "00000", "CSPAT00601OutBlock2": {"OrdNo": "1"}})
        auth.rest_api = mock_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        await provider.send_order({}, "token", "buy", "005930", 10, price=50000)
        call_kwargs = mock_api.buy_order.call_args.kwargs
        assert call_kwargs["stock_code"] == "A005930"

    @pytest.mark.asyncio
    async def test_sell_prepends_a_prefix(self):
        auth = MagicMock()
        mock_api = AsyncMock()
        mock_api.sell_order = AsyncMock(return_value={"rsp_cd": "00000", "CSPAT00601OutBlock2": {"OrdNo": "1"}})
        auth.rest_api = mock_api
        from backend.app.core.ls_providers import LsOrderProvider
        provider = LsOrderProvider(auth)
        await provider.send_order({}, "token", "sell", "035420", 5, price=200000)
        call_kwargs = mock_api.sell_order.call_args.kwargs
        assert call_kwargs["stock_code"] == "A035420"


# ── LsWebSocketProvider ────────────────────────────────────────────────────────

class TestLsWebSocketProvider:
    def test_get_ws_uri_returns_broker_urls(self):
        auth = MagicMock()
        from backend.app.core.ls_providers import LsWebSocketProvider
        provider = LsWebSocketProvider(auth)
        with patch("backend.app.core.broker_urls.build_broker_urls", return_value={"ws_uri": "wss://ls.example.com/ws"}):
            uri = provider.get_ws_uri()
        assert uri == "wss://ls.example.com/ws"

    def test_get_ws_uri_calls_with_ls(self):
        auth = MagicMock()
        from backend.app.core.ls_providers import LsWebSocketProvider
        provider = LsWebSocketProvider(auth)
        with patch("backend.app.core.broker_urls.build_broker_urls", return_value={"ws_uri": "wss://test"}) as mock_fn:
            provider.get_ws_uri()
            mock_fn.assert_called_once_with("ls")
