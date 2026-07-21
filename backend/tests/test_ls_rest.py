"""ls_rest.py 단위 테스트 — LS증권 REST API 클라이언트 검증.

LsTokenInfo: is_expired (정상/만료/issued_at=0)
LsRestAPI: __init__, __aenter__/__aexit__, ensure_client, ensure_token, get_token,
  _issue_token (성공/429/HTTP실패/토큰필드없음/크리덴셜없음),
  revoke_token (정상/HTTP실패/토큰없음/예외),
  call_api (GET/POST/429/예외/토큰없음),
  buy_order (성공/HTTP실패/429/예외),
  sell_order (성공/HTTP실패/예외),
  get_balance (call_api 위임)

의존성: httpx, broker_urls
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _mock_httpx_response(status_code=200, json_data=None, text="", headers=None):
    """httpx.Response mock 생성."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or ("{}" if json_data else "")
    resp.headers = headers or {}
    return resp


def _mock_httpx_client(post_side_effect=None, post_return=None, get_side_effect=None, get_return=None):
    """httpx.AsyncClient mock 생성."""
    client = AsyncMock()
    client.is_closed = False
    if post_side_effect:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=post_return)
    if get_side_effect:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_return)
    client.aclose = AsyncMock()
    return client


def _make_ls_rest(app_key="key", app_secret="secret", base_url="https://api.ls.com"):
    """LsRestAPI 인스턴스 생성."""
    from backend.app.core.ls_rest import LsRestAPI
    return LsRestAPI(app_key=app_key, app_secret=app_secret, base_url=base_url)


def _make_ls_token_info(access_token="tok", expires_in=86400):
    """LsTokenInfo 인스턴스 생성."""
    from backend.app.core.ls_rest import LsTokenInfo
    return LsTokenInfo(access_token=access_token, expires_in=expires_in, issued_at=time.time())


# ── LsTokenInfo.is_expired ─────────────────────────────────────────────────────

class TestLsTokenInfo:
    def test_not_expired(self):
        ti = _make_ls_token_info(expires_in=86400)
        assert ti.is_expired() is False

    def test_expired(self):
        ti = _make_ls_token_info(expires_in=100)
        assert ti.is_expired(buffer_seconds=200) is True

    def test_issued_at_zero(self):
        from backend.app.core.ls_rest import LsTokenInfo
        ti = LsTokenInfo(access_token="tok", expires_in=86400, issued_at=0.0)
        assert ti.is_expired() is True

    def test_custom_buffer(self):
        ti = _make_ls_token_info(expires_in=86400)
        assert ti.is_expired(buffer_seconds=0) is False


# ── LsRestAPI.__init__ ─────────────────────────────────────────────────────────

class TestLsRestInit:
    def test_init_stores_params(self):
        api = _make_ls_rest(app_key="  mykey  ", app_secret="  mysecret  ")
        assert api.app_key == "mykey"
        assert api.app_secret == "mysecret"
        assert api.base_url == "https://api.ls.com"
        assert api._token_info is None
        assert api._client is None

    def test_init_default_base_url(self):
        with patch("backend.app.core.ls_rest.build_broker_urls", MagicMock(return_value={"rest_base": "https://default.ls.com"})):
            from backend.app.core.ls_rest import LsRestAPI
            api = LsRestAPI(app_key="k", app_secret="s")
            assert api.base_url == "https://default.ls.com"

    def test_init_strips_trailing_slash(self):
        api = _make_ls_rest(base_url="https://api.ls.com/")
        assert api.base_url == "https://api.ls.com"

    def test_init_empty_credentials(self):
        api = _make_ls_rest(app_key="", app_secret="")
        assert api.app_key == ""
        assert api.app_secret == ""

    async def test_async_context_manager(self):
        api = _make_ls_rest()
        mock_client = _mock_httpx_client()
        with patch("backend.app.core.ls_rest.httpx.AsyncClient", return_value=mock_client):
            async with api as ctx:
                assert ctx is api
            mock_client.aclose.assert_called_once()
            assert api._client is None


# ── LsRestAPI.ensure_client ────────────────────────────────────────────────────

class TestLsRestEnsureClient:
    async def test_creates_new_client(self):
        api = _make_ls_rest()
        with patch("backend.app.core.ls_rest.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_httpx_client()
            mock_cls.return_value = mock_client
            await api.ensure_client()
            assert api._client is mock_client

    async def test_reuses_existing_client(self):
        api = _make_ls_rest()
        existing = _mock_httpx_client()
        api._client = existing
        api._loop = asyncio.get_running_loop()
        with patch("backend.app.core.ls_rest.httpx.AsyncClient") as mock_cls:
            await api.ensure_client()
            mock_cls.assert_not_called()
            assert api._client is existing

    async def test_creates_new_on_loop_change(self):
        api = _make_ls_rest()
        old_client = _mock_httpx_client()
        api._client = old_client
        api._loop = "old_loop"
        with patch("backend.app.core.ls_rest.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_httpx_client()
            mock_cls.return_value = mock_client
            await api.ensure_client()
            assert api._client is mock_client


# ── LsRestAPI.ensure_token / get_token ─────────────────────────────────────────

class TestLsRestEnsureToken:
    async def test_valid_token_returns_true(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        with patch.object(api, "_issue_token", AsyncMock()) as mock_issue:
            result = await api.ensure_token()
            assert result is True
            mock_issue.assert_not_called()

    async def test_expired_token_triggers_issue(self):
        api = _make_ls_rest()
        from backend.app.core.ls_rest import LsTokenInfo
        api._token_info = LsTokenInfo(access_token="tok", expires_in=100, issued_at=time.time())
        with patch.object(api, "_issue_token", AsyncMock(return_value=True)) as mock_issue:
            result = await api.ensure_token()
            assert result is True
            mock_issue.assert_called_once()

    async def test_no_token_triggers_issue(self):
        api = _make_ls_rest()
        api._token_info = None
        with patch.object(api, "_issue_token", AsyncMock(return_value=False)) as mock_issue:
            result = await api.ensure_token()
            assert result is False
            mock_issue.assert_called_once()

    def test_get_token_with_token(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info(access_token="my_tok")
        assert api.get_token() == "my_tok"

    def test_get_token_no_token(self):
        api = _make_ls_rest()
        api._token_info = None
        assert api.get_token() is None


# ── LsRestAPI._issue_token ─────────────────────────────────────────────────────

class TestLsRestIssueToken:
    async def test_success(self):
        api = _make_ls_rest()
        mock_resp = _mock_httpx_response(200, {"access_token": "new_tok", "expires_in": 86400})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api._issue_token()
            assert result is True
            assert api._token_info is not None
            assert api._token_info.access_token == "new_tok"

    async def test_no_credentials(self):
        api = _make_ls_rest(app_key="", app_secret="")
        result = await api._issue_token()
        assert result is False

    async def test_http_failure(self):
        api = _make_ls_rest()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api._issue_token()
            assert result is False

    async def test_token_field_missing(self):
        api = _make_ls_rest()
        mock_resp = _mock_httpx_response(200, {"other": "data"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api._issue_token()
            assert result is False
            assert api._token_info is None

    async def test_429_retry_then_success(self):
        api = _make_ls_rest()
        resp_429 = _mock_httpx_response(429)
        resp_200 = _mock_httpx_response(200, {"access_token": "tok", "expires_in": 3600})
        mock_client = _mock_httpx_client(post_side_effect=[resp_429, resp_200])
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch("backend.app.core.ls_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api._issue_token()
            assert result is True
            assert api._token_info.access_token == "tok"

    async def test_no_client(self):
        api = _make_ls_rest()
        api._client = None
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api._issue_token()
            assert result is False

    async def test_exception_retry(self):
        api = _make_ls_rest()
        mock_client = _mock_httpx_client(post_side_effect=[Exception("err"), Exception("err"), Exception("err")])
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch("backend.app.core.ls_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api._issue_token()
            assert result is False


# ── LsRestAPI.revoke_token ─────────────────────────────────────────────────────

class TestLsRestRevokeToken:
    async def test_success(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(200)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api.revoke_token()
            assert result is True
            assert api._token_info is None

    async def test_no_token(self, caplog):
        api = _make_ls_rest()
        api._token_info = None
        with caplog.at_level(logging.INFO, logger="backend.app.core.ls_rest"):
            result = await api.revoke_token()
            assert result is True
        assert "토큰 폐기 생략 — 발급된 토큰 없음" in caplog.text

    async def test_http_failure(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api.revoke_token()
            assert result is True
            assert api._token_info is None

    async def test_exception(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_client = _mock_httpx_client(post_side_effect=Exception("net error"))
        api._client = mock_client
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api.revoke_token()
            assert result is True
            assert api._token_info is None

    async def test_no_client(self, caplog):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        api._client = None
        with patch.object(api, "ensure_client", AsyncMock()):
            with caplog.at_level(logging.INFO, logger="backend.app.core.ls_rest"):
                result = await api.revoke_token()
                assert result is True
                assert api._token_info is None
        assert "토큰 폐기 생략 — HTTP 클라이언트 없음" in caplog.text


# ── LsRestAPI.call_api ─────────────────────────────────────────────────────────

class TestLsRestCallApi:
    async def test_get_success(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(200, {"data": "ok"})
        mock_client = _mock_httpx_client(get_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.call_api("https://api/test", method="GET")
            assert result == {"data": "ok"}

    async def test_post_success(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(200, {"data": "ok"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.call_api("https://api/test", method="POST", body={"key": "val"})
            assert result == {"data": "ok"}

    async def test_429_retry_then_success(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        resp_429 = _mock_httpx_response(429)
        resp_200 = _mock_httpx_response(200, {"ok": True})
        mock_client = _mock_httpx_client(post_side_effect=[resp_429, resp_200])
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
            patch("backend.app.core.ls_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api.call_api("https://api/test", method="POST")
            assert result == {"ok": True}

    async def test_http_500(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.call_api("https://api/test", method="POST")
            assert result is None

    async def test_exception(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_client = _mock_httpx_client(post_side_effect=[Exception("err"), Exception("err"), Exception("err")])
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
            patch("backend.app.core.ls_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api.call_api("https://api/test", method="POST")
            assert result is None

    async def test_no_token(self):
        api = _make_ls_rest()
        api._client = _mock_httpx_client()
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=False)),
        ):
            result = await api.call_api("https://api/test")
            assert result is None

    async def test_no_client(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        api._client = None
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api.call_api("https://api/test")
            assert result is None


# ── LsRestAPI.buy_order ────────────────────────────────────────────────────────

class TestLsRestBuyOrder:
    async def test_success(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(200, {"rsp_cd": "00000", "rsp_msg": "ok"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.buy_order("A005930", 10, 70000)
            assert result["rsp_cd"] == "00000"

    async def test_http_failure(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(500, {"rsp_cd": "error"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.buy_order("A005930", 10, 70000)
            assert result is not None  # returns data even on HTTP failure

    async def test_429_retry(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        resp_429 = _mock_httpx_response(429)
        resp_200 = _mock_httpx_response(200, {"rsp_cd": "00000"})
        mock_client = _mock_httpx_client(post_side_effect=[resp_429, resp_200])
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
            patch("backend.app.core.ls_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api.buy_order("A005930", 10, 70000)
            assert result["rsp_cd"] == "00000"

    async def test_exception(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_client = _mock_httpx_client(post_side_effect=[Exception("err"), Exception("err"), Exception("err")])
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
            patch("backend.app.core.ls_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api.buy_order("A005930", 10, 70000)
            assert result is None

    async def test_no_token(self):
        api = _make_ls_rest()
        api._client = _mock_httpx_client()
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=False)),
        ):
            result = await api.buy_order("A005930", 10, 70000)
            assert result is None

    async def test_no_client(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        api._client = None
        with patch.object(api, "ensure_client", AsyncMock()):
            result = await api.buy_order("A005930", 10, 70000)
            assert result is None

    async def test_rsp_cd_failure(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(200, {"rsp_cd": "10001", "rsp_msg": "fail"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.buy_order("A005930", 10, 70000)
            assert result["rsp_cd"] == "10001"


# ── LsRestAPI.sell_order ───────────────────────────────────────────────────────

class TestLsRestSellOrder:
    async def test_success(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(200, {"rsp_cd": "00000", "rsp_msg": "ok"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.sell_order("A005930", 10, 70000)
            assert result["rsp_cd"] == "00000"

    async def test_http_failure(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_resp = _mock_httpx_response(500, {"rsp_cd": "error"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
        ):
            result = await api.sell_order("A005930", 10, 70000)
            assert result is not None

    async def test_exception(self):
        api = _make_ls_rest()
        api._token_info = _make_ls_token_info()
        mock_client = _mock_httpx_client(post_side_effect=[Exception("err"), Exception("err"), Exception("err")])
        api._client = mock_client
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=True)),
            patch("backend.app.core.ls_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api.sell_order("A005930", 10, 70000)
            assert result is None

    async def test_no_token(self):
        api = _make_ls_rest()
        api._client = _mock_httpx_client()
        with (
            patch.object(api, "ensure_client", AsyncMock()),
            patch.object(api, "ensure_token", AsyncMock(return_value=False)),
        ):
            result = await api.sell_order("A005930", 10, 70000)
            assert result is None


# ── LsRestAPI.get_balance ─────────────────────────────────────────────────────

class TestLsRestAccountQueries:
    async def test_get_balance_delegates(self):
        api = _make_ls_rest()
        with patch.object(api, "call_api", AsyncMock(return_value={"data": "ok"})) as mock_call:
            result = await api.get_balance()
            assert result == {"data": "ok"}
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args[1]
            assert call_kwargs["method"] == "POST"

