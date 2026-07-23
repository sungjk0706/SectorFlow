"""ls_providers.py 단위 테스트 — LS증권 Provider 구현체 검증.

LsAuthProvider: __init__ 캐싱, get_access_token, ensure_token, broker_name, rest_api
LsOrderProvider: send_order (buy/sell/unsupported), 성공/실패

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
