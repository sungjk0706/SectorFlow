"""kiwoom_providers.py 단위 테스트 — 키움증권 Provider 구현체 검증.

KiwoomAuthProvider: __init__ 캐싱, get_access_token, ensure_token, broker_name, rest_api
KiwoomOrderProvider: send_order 위임
KiwoomStockProvider: __init__ 타입 검증, fetch_all_stocks, fetch_stock_5day_data,
  fetch_all_stocks_daily_confirmed
KiwoomWebSocketProvider: __init__

의존성: state (lazy import), KiwoomRestAPI, kiwoom_order.send_order, kiwoom_stock_rest, build_broker_urls
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


# ── KiwoomOrderProvider ────────────────────────────────────────────────────────

class TestKiwoomOrderProvider:
    def test_init_with_auth(self):
        auth = MagicMock()
        from backend.app.core.kiwoom_providers import KiwoomOrderProvider
        provider = KiwoomOrderProvider(auth)

    def test_init_no_auth(self):
        from backend.app.core.kiwoom_providers import KiwoomOrderProvider
        provider = KiwoomOrderProvider(None)

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
        assert provider._rest_api is mock_api

    def test_init_no_auth(self):
        from backend.app.core.kiwoom_providers import KiwoomStockProvider
        provider = KiwoomStockProvider(None)
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

    def test_init_no_auth(self):
        from backend.app.core.kiwoom_providers import KiwoomWebSocketProvider
        provider = KiwoomWebSocketProvider(None)
