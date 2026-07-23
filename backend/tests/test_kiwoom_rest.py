"""kiwoom_rest.py 단위 테스트 — 키움증권 REST API 클라이언트 검증.

TokenInfo: is_expired_soon (정상/만료임박/짧은dt/파싱예외)
KiwoomRestAPI: __init__, __aenter__/__aexit__, _get_client, _reset_client,
  _ensure_token, _call_api (429/성공/HTTP오류/예외/토큰없음),
  _issue_token (성공/429/HTTP실패/토큰필드없음/크리덴셜없음),
  revoke_token, get_access_token, get_auth_headers,
  _request (성공/429/예외), _paginated_request (단일/연속조회/토큰없음),
  get_account_number, get_deposit_detail, get_balance_detail,
  fetch_ka10081_daily_price, fetch_ka10081_sector_all, fetch_market_stock_name_map,
  fetch_ka20001_index (정상/부호처리/None), fetch_ka10099_full (정상/숫자/알파벳/빈),
  fetch_ka10099_market_code_list, fetch_market_stock_list,
  fetch_ka10001_nxt_enable (정상/중첩/실패), fetch_nxt_enable_map
kiwoom_try_token: 성공/크리덴셜없음/HTTP실패/토큰필드없음/예외

의존성: httpx, broker_urls, broker_factory, kiwoom_stock_rest
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import logging
import pytest
from datetime import datetime, timezone, timedelta
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


def _mock_httpx_client(post_side_effect=None, post_return=None, is_closed=False):
    """httpx.AsyncClient mock 생성."""
    client = AsyncMock()
    client.is_closed = is_closed
    if post_side_effect:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=post_return)
    client.aclose = AsyncMock()
    return client


def _make_kiwoom_rest(app_key="key", app_secret="secret", base_url="https://api.kiwoom.com"):
    """KiwoomRestAPI 인스턴스 생성."""
    from backend.app.core.kiwoom_rest import KiwoomRestAPI
    return KiwoomRestAPI(app_key=app_key, app_secret=app_secret, base_url=base_url)


def _make_token_info(expires_dt="20990101000000"):
    """TokenInfo 인스턴스 생성 (기본: 먼 미래 만료)."""
    from backend.app.core.kiwoom_rest import TokenInfo
    return TokenInfo(token="test_token", expires_dt=expires_dt)


# ── TokenInfo.is_expired_soon ──────────────────────────────────────────────────

class TestTokenInfo:
    def test_not_expired(self):
        ti = _make_token_info("20990101000000")
        assert ti.is_expired_soon() is False

    def test_expired_soon(self):
        # 만료 시간이 현재 + 30분 (buffer 1시간보다 작음)
        now = datetime.now(timezone(timedelta(hours=9)))
        exp = now + timedelta(minutes=30)
        dt = exp.strftime("%Y%m%d%H%M%S")
        ti = _make_token_info(dt)
        assert ti.is_expired_soon() is True

    def test_short_dt_returns_true(self):
        ti = _make_token_info("209901")
        assert ti.is_expired_soon() is True

    def test_parse_error_returns_true(self):
        ti = _make_token_info("invalid_date!!")
        assert ti.is_expired_soon() is True

    def test_custom_buffer(self):
        # buffer 0 → 먼 미래면 만료 아님
        ti = _make_token_info("20990101000000")
        assert ti.is_expired_soon(buffer_seconds=0) is False


# ── KiwoomRestAPI.__init__ ─────────────────────────────────────────────────────

class TestKiwoomRestInit:
    def test_init_stores_params(self):
        api = _make_kiwoom_rest(app_key="  mykey  ", app_secret="  mysecret  ")
        assert api.app_key == "mykey"
        assert api.app_secret == "mysecret"
        assert api.base_url == "https://api.kiwoom.com"
        assert api._token_info is None
        assert api._client is None
        assert api._acnt_no == ""

    def test_init_default_base_url(self):
        from backend.app.core.kiwoom_rest import KiwoomRestAPI
        api = KiwoomRestAPI(app_key="k", app_secret="s")
        assert api.base_url != ""

    def test_init_strips_trailing_slash(self):
        api = _make_kiwoom_rest(base_url="https://api.kiwoom.com/")
        assert api.base_url == "https://api.kiwoom.com"

    def test_init_empty_credentials(self):
        api = _make_kiwoom_rest(app_key="", app_secret="")
        assert api.app_key == ""
        assert api.app_secret == ""

    async def test_async_context_manager(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_reset_client", AsyncMock()):
            async with api as ctx:
                assert ctx is api


# ── KiwoomRestAPI._get_client / _reset_client ──────────────────────────────────

class TestKiwoomRestClient:
    async def test_get_client_creates_new(self):
        api = _make_kiwoom_rest()
        with patch("backend.app.core.kiwoom_rest.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_httpx_client()
            mock_cls.return_value = mock_client
            client = await api._get_client()
            assert client is mock_client
            mock_cls.assert_called_once()

    async def test_get_client_reuses_existing(self):
        api = _make_kiwoom_rest()
        existing = _mock_httpx_client(is_closed=False)
        api._client = existing
        with patch("backend.app.core.kiwoom_rest.httpx.AsyncClient") as mock_cls:
            client = await api._get_client()
            assert client is existing
            mock_cls.assert_not_called()

    async def test_reset_client_closes_and_clears(self):
        api = _make_kiwoom_rest()
        mock_client = _mock_httpx_client(is_closed=False)
        api._client = mock_client
        await api._reset_client()
        mock_client.aclose.assert_called_once()
        assert api._client is None

    async def test_reset_client_no_client(self):
        api = _make_kiwoom_rest()
        api._client = None
        await api._reset_client()
        assert api._client is None

    async def test_reset_client_already_closed(self):
        api = _make_kiwoom_rest()
        mock_client = _mock_httpx_client(is_closed=True)
        api._client = mock_client
        await api._reset_client()
        mock_client.aclose.assert_not_called()
        assert api._client is None


# ── KiwoomRestAPI._ensure_token ────────────────────────────────────────────────

class TestKiwoomRestEnsureToken:
    async def test_valid_token_returns_true(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        with patch.object(api, "_issue_token", AsyncMock()) as mock_issue:
            result = await api._ensure_token()
            assert result is True
            mock_issue.assert_not_called()

    async def test_expired_token_triggers_issue(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info("20000101000000")
        with patch.object(api, "_issue_token", AsyncMock(return_value=True)) as mock_issue:
            result = await api._ensure_token()
            assert result is True
            mock_issue.assert_called_once()

    async def test_no_token_triggers_issue(self):
        api = _make_kiwoom_rest()
        api._token_info = None
        with patch.object(api, "_issue_token", AsyncMock(return_value=False)) as mock_issue:
            result = await api._ensure_token()
            assert result is False
            mock_issue.assert_called_once()


# ── KiwoomRestAPI._call_api ────────────────────────────────────────────────────

class TestKiwoomRestCallApi:
    async def test_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"data": "ok"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            resp, hit_429 = await api._call_api("https://api/test", "ka00001")
            assert resp is mock_resp
            assert hit_429 is False

    async def test_429_then_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        resp_429 = _mock_httpx_response(429)
        resp_200 = _mock_httpx_response(200, {"data": "ok"})
        mock_client = _mock_httpx_client(post_side_effect=[resp_429, resp_200])
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            resp, hit_429 = await api._call_api("https://api/test", "ka00001")
            assert resp is resp_200
            assert hit_429 is True
            # adaptive delay should have increased
            assert api._api_delay > api._API_DELAY_MIN

    async def test_http_500_returns_none(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            resp, hit_429 = await api._call_api("https://api/test", "ka00001")
            assert resp is None
            assert hit_429 is False

    async def test_exception_retry_then_fail(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_client = _mock_httpx_client(post_side_effect=[Exception("net error"), Exception("net error"), Exception("net error")])
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch.object(api, "_reset_client", AsyncMock()),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            resp, hit_429 = await api._call_api("https://api/test", "ka00001")
            assert resp is None
            assert hit_429 is False

    async def test_no_token_returns_none(self):
        api = _make_kiwoom_rest()
        api._token_info = None
        with patch.object(api, "_ensure_token", AsyncMock(return_value=False)):
            resp, hit_429 = await api._call_api("https://api/test", "ka00001")
            assert resp is None
            assert hit_429 is False

    async def test_success_decreases_api_delay(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        api._api_delay = 1.0
        mock_resp = _mock_httpx_response(200, {"data": "ok"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            await api._call_api("https://api/test", "ka00001")
            assert api._api_delay < 1.0


# ── KiwoomRestAPI._issue_token ─────────────────────────────────────────────────

class TestKiwoomRestIssueToken:
    async def test_success(self):
        api = _make_kiwoom_rest()
        mock_resp = _mock_httpx_response(200, {"token": "new_tok", "expires_dt": "20990101000000"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            result = await api._issue_token()
            assert result is True
            assert api._token_info is not None
            assert api._token_info.token == "new_tok"

    async def test_no_credentials(self):
        api = _make_kiwoom_rest(app_key="", app_secret="")
        result = await api._issue_token()
        assert result is False

    async def test_http_failure(self):
        api = _make_kiwoom_rest()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            result = await api._issue_token()
            assert result is False

    async def test_token_field_missing(self):
        api = _make_kiwoom_rest()
        mock_resp = _mock_httpx_response(200, {"return_msg": "some error", "return_code": "8030"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            result = await api._issue_token()
            assert result is False
            assert api._token_info is None

    async def test_429_retry_then_success(self):
        api = _make_kiwoom_rest()
        resp_429 = _mock_httpx_response(429)
        resp_200 = _mock_httpx_response(200, {"token": "tok", "expires_dt": "20990101000000"})
        mock_client = _mock_httpx_client(post_side_effect=[resp_429, resp_200])
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api._issue_token()
            assert result is True
            assert api._token_info.token == "tok"

    async def test_access_token_field(self):
        api = _make_kiwoom_rest()
        mock_resp = _mock_httpx_response(200, {"access_token": "alt_tok", "expires_dt": "20990101000000"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            result = await api._issue_token()
            assert result is True
            assert api._token_info.token == "alt_tok"

    async def test_exception_continues_retry(self):
        api = _make_kiwoom_rest()
        mock_client = _mock_httpx_client(post_side_effect=[Exception("err"), Exception("err"), Exception("err")])
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch.object(api, "_reset_client", AsyncMock()),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api._issue_token()
            assert result is False


# ── KiwoomRestAPI.revoke_token ─────────────────────────────────────────────────

class TestKiwoomRestRevokeToken:
    async def test_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            result = await api.revoke_token()
            assert result is True
            assert api._token_info is None

    async def test_no_token(self, caplog):
        api = _make_kiwoom_rest()
        api._token_info = None
        with caplog.at_level(logging.INFO, logger="backend.app.core.kiwoom_rest"):
            result = await api.revoke_token()
            assert result is True
        assert "토큰 폐기 생략 — 발급된 토큰 없음" in caplog.text

    async def test_http_failure_still_returns_true(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            result = await api.revoke_token()
            assert result is True
            assert api._token_info is None

    async def test_exception_still_returns_true(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_client = _mock_httpx_client(post_side_effect=Exception("net error"))
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            result = await api.revoke_token()
            assert result is True
            assert api._token_info is None


# ── KiwoomRestAPI.get_access_token / get_auth_headers ──────────────────────────

class TestKiwoomRestAccess:
    async def test_get_access_token_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        with patch.object(api, "_ensure_token", AsyncMock(return_value=True)):
            token = await api.get_access_token()
            assert token == "test_token"

    async def test_get_access_token_failure(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_ensure_token", AsyncMock(return_value=False)):
            token = await api.get_access_token()
            assert token is None

    async def test_get_auth_headers_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        with patch.object(api, "_ensure_token", AsyncMock(return_value=True)):
            headers = await api.get_auth_headers("ka00001")
            assert headers is not None
            assert "authorization" in headers
            assert headers["api-id"] == "ka00001"

    async def test_get_auth_headers_failure(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_ensure_token", AsyncMock(return_value=False)):
            headers = await api.get_auth_headers("ka00001")
            assert headers is None


# ── KiwoomRestAPI._request ─────────────────────────────────────────────────────

class TestKiwoomRestRequest:
    async def test_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"acctNo": "12345"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            data = await api._request("ka00001")
            assert data is not None
            assert data["acctNo"] == "12345"

    async def test_no_token(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_ensure_token", AsyncMock(return_value=False)):
            data = await api._request("ka00001")
            assert data is None

    async def test_http_500(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            data = await api._request("ka00001")
            assert data is None

    async def test_exception(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_client = _mock_httpx_client(post_side_effect=Exception("err"))
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch.object(api, "_reset_client", AsyncMock()),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            data = await api._request("ka00001")
            assert data is None

    async def test_exception_retry_then_success(self):
        """B4-06-02: _request 예외 시 _call_api 패턴대로 재시도 후 성공 검증."""
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        resp_200 = _mock_httpx_response(200, {"ok": True})
        mock_client = _mock_httpx_client(post_side_effect=[Exception("first err"), resp_200])
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch.object(api, "_reset_client", AsyncMock()),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            data = await api._request("ka00001")
            assert data is not None
            assert data["ok"] is True

    async def test_429_retry_then_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        resp_429 = _mock_httpx_response(429)
        resp_200 = _mock_httpx_response(200, {"ok": True})
        mock_client = _mock_httpx_client(post_side_effect=[resp_429, resp_200])
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            data = await api._request("ka00001")
            assert data is not None
            assert data["ok"] is True


# ── KiwoomRestAPI._paginated_request ───────────────────────────────────────────

class TestKiwoomRestPaginatedRequest:
    async def test_single_page(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"body": {"acnt_evlt_remn_indv_tot": [{"item": 1}]}})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            data = await api._paginated_request("kt00018", body={"qry_tp": "1"})
            assert data is not None
            assert data["body"]["acnt_evlt_remn_indv_tot"] == [{"item": 1}]

    async def test_no_token(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_ensure_token", AsyncMock(return_value=False)):
            data = await api._paginated_request("kt00018")
            assert data is None

    async def test_multi_page(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        resp1 = _mock_httpx_response(200, {"body": {"acnt_evlt_remn_indv_tot": [{"item": 1}]}}, headers={"cont-yn": "Y", "next-key": "key1"})
        resp2 = _mock_httpx_response(200, {"body": {"acnt_evlt_remn_indv_tot": [{"item": 2}]}}, headers={"cont-yn": "N", "next-key": ""})
        mock_client = _mock_httpx_client(post_side_effect=[resp1, resp2])
        with (
            patch.object(api, "_get_client", AsyncMock(return_value=mock_client)),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            data = await api._paginated_request("kt00018", body={"qry_tp": "1"})
            assert data is not None
            items = data["body"]["acnt_evlt_remn_indv_tot"]
            assert len(items) == 2

    async def test_http_failure(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(500)
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with patch.object(api, "_get_client", AsyncMock(return_value=mock_client)):
            data = await api._paginated_request("kt00018")
            assert data is None


# ── KiwoomRestAPI.get_account_number / get_deposit_detail / get_balance_detail ─

class TestKiwoomRestAccount:
    async def test_get_account_number_success(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_request", AsyncMock(return_value={"acctNo": "12345"})):
            result = await api.get_account_number()
            assert result == "12345"

    async def test_get_account_number_from_body(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_request", AsyncMock(return_value={"body": {"acctNo": "67890"}})):
            result = await api.get_account_number()
            assert result == "67890"

    async def test_get_account_number_no_data(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_request", AsyncMock(return_value=None)):
            result = await api.get_account_number()
            assert result is None

    async def test_get_deposit_detail_success(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_request", AsyncMock(return_value={"data": "ok"})) as mock_req:
            result = await api.get_deposit_detail(acnt_no="12345")
            assert result == {"data": "ok"}
            call_body = mock_req.call_args[1].get("body", {})
            assert call_body.get("qry_tp") == "3"
            assert call_body.get("acnt_no") == "12345"

    async def test_get_deposit_detail_no_acnt(self):
        api = _make_kiwoom_rest()
        api._acnt_no = "default_acnt"
        with patch.object(api, "_request", AsyncMock(return_value={"data": "ok"})) as mock_req:
            await api.get_deposit_detail()
            call_body = mock_req.call_args[1].get("body", {})
            assert call_body.get("acnt_no") == "default_acnt"

    async def test_get_balance_detail_delegates(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "_paginated_request", AsyncMock(return_value={"data": "ok"})) as mock_pag:
            result = await api.get_balance_detail()
            assert result == {"data": "ok"}
            mock_pag.assert_called_once()


# ── KiwoomRestAPI.fetch_ka10081_* / fetch_market_stock_name_map ────────────────

class TestKiwoomRestFetch:
    async def test_fetch_ka10081_daily_price_delegates(self):
        api = _make_kiwoom_rest()
        with patch("backend.app.core.kiwoom_rest._ka10081_fetch_single", AsyncMock(return_value={"close": 70000})) as mock_fn:
            result = await api.fetch_ka10081_daily_price("005930", "20260711")
            assert result == {"close": 70000}
            mock_fn.assert_called_once_with(api, "005930", "20260711")

    async def test_fetch_ka10081_sector_all_delegates(self):
        api = _make_kiwoom_rest()
        with patch("backend.app.core.kiwoom_rest._ka10081_fetch_all", AsyncMock(return_value={"005930": {}})) as mock_fn:
            result = await api.fetch_ka10081_sector_all(["005930"], "20260711")
            assert result == {"005930": {}}
            mock_fn.assert_called_once()

    async def test_fetch_market_stock_name_map_raises(self):
        api = _make_kiwoom_rest()
        with pytest.raises(NotImplementedError):
            await api.fetch_market_stock_name_map()


# ── KiwoomRestAPI.fetch_ka20001_index ──────────────────────────────────────────

class TestKiwoomRestFetchIndex:
    async def test_success(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {
            "cur_prc": "2,500", "pred_pre": "10", "flu_rt": "0.4",
            "pred_pre_sig": "2", "rising": "500", "fall": "300",
        })
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka20001_index("0", "001")
            assert result is not None
            assert result["price"] == 2500.0
            assert result["change"] == 10.0
            assert result["rate"] == 0.4
            assert result["up_count"] == 500
            assert result["down_count"] == 300

    async def test_negative_sign_4(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {
            "cur_prc": "2,500", "pred_pre": "10", "flu_rt": "0.4",
            "pred_pre_sig": "4", "rising": "300", "fall": "500",
        })
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka20001_index("0", "001")
            assert result["change"] == -10.0
            assert result["rate"] == -0.4

    async def test_negative_sign_5(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {
            "cur_prc": "2,500", "pred_pre": "10", "flu_rt": "0.4",
            "pred_pre_sig": "5", "rising": "300", "fall": "500",
        })
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka20001_index("0", "001")
            assert result["change"] < 0

    async def test_resp_none(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        with patch.object(api, "_call_api", AsyncMock(return_value=(None, False))):
            result = await api.fetch_ka20001_index("0", "001")
            assert result is None

    async def test_json_parse_failure(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("parse error")
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka20001_index("0", "001")
            assert result is None

    async def test_pric_fallback(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {
            "pric": "3,000", "pred_pre": "20", "flu_rt": "0.7",
            "pred_pre_sig": "2", "rising": "100", "fall": "50",
        })
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka20001_index("0", "001")
            assert result["price"] == 3000.0


# ── KiwoomRestAPI.fetch_ka10099_full / fetch_ka10099_market_code_list / fetch_market_stock_list ─

class TestKiwoomRestFetchMarketCode:
    async def test_success_numeric(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {
            "list": [
                {"code": "005930", "nxtEnable": "Y", "marketCode": "0"},
                {"code": "000660", "nxtEnable": "N", "marketCode": "0"},
            ]
        })
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10099_full("0")
            assert len(result) == 2
            assert result[0] == ("005930", True, "0")
            assert result[1] == ("000660", False, "0")

    async def test_success_alpha_code(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {
            "list": [
                {"code": "A0017J0", "nxtEnable": "Y", "marketCode": "10"},
            ]
        })
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10099_full("10")
            assert len(result) == 1
            assert result[0] == ("0017J0", True, "10")

    async def test_resp_none_returns_empty(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        with patch.object(api, "_call_api", AsyncMock(return_value=(None, False))):
            result = await api.fetch_ka10099_full("0")
            assert result == []

    async def test_empty_list(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"list": []})
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10099_full("0")
            assert result == []

    async def test_no_list_key(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {})
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10099_full("0")
            assert result == []

    async def test_short_code_padded(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {
            "list": [{"code": "5930", "nxtEnable": "N", "marketCode": "0"}]
        })
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10099_full("0")
            assert result[0][0] == "005930"

    async def test_exception_returns_empty(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("parse error")
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10099_full("0")
            assert result == []

    async def test_market_code_list_delegates(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "fetch_ka10099_full", AsyncMock(return_value=[("005930", True, "0"), ("000660", False, "0")])):
            result = await api.fetch_ka10099_market_code_list("0")
            assert result == ["005930", "000660"]

    async def test_market_stock_list_delegates(self):
        api = _make_kiwoom_rest()
        with patch.object(api, "fetch_ka10099_full", AsyncMock(return_value=[("005930", True, "0")])):
            result = await api.fetch_market_stock_list("0")
            assert result == [("005930", True, "0")]


# ── KiwoomRestAPI.fetch_ka10001_nxt_enable / fetch_nxt_enable_map ──────────────

class TestKiwoomRestFetchNxtEnable:
    async def test_success_direct(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"nxtEnable": "Y"})
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10001_nxt_enable("005930")
            assert result == "Y"

    async def test_success_nested_output(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"output": {"nxtEnable": "N"}})
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10001_nxt_enable("005930")
            assert result == "N"

    async def test_success_nested_output_list(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"output1": [{"nxtEnable": "Y"}]})
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10001_nxt_enable("005930")
            assert result == "Y"

    async def test_resp_none_returns_empty(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        with patch.object(api, "_call_api", AsyncMock(return_value=(None, False))):
            result = await api.fetch_ka10001_nxt_enable("005930")
            assert result == ""

    async def test_exception_returns_empty(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("parse error")
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10001_nxt_enable("005930")
            assert result == ""

    async def test_no_nxt_enable_returns_N(self):
        api = _make_kiwoom_rest()
        api._token_info = _make_token_info()
        mock_resp = _mock_httpx_response(200, {"other": "data"})
        with patch.object(api, "_call_api", AsyncMock(return_value=(mock_resp, False))):
            result = await api.fetch_ka10001_nxt_enable("005930")
            assert result == "N"

    async def test_fetch_nxt_enable_map(self):
        api = _make_kiwoom_rest()
        with (
            patch.object(api, "fetch_ka10001_nxt_enable", AsyncMock(side_effect=["Y", "N"])),
            patch("backend.app.core.kiwoom_rest.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await api.fetch_nxt_enable_map(["005930", "000660"])
            assert result == {"005930": True, "000660": False}

    async def test_fetch_nxt_enable_map_empty(self):
        api = _make_kiwoom_rest()
        result = await api.fetch_nxt_enable_map([])
        assert result == {}


# ── kiwoom_try_token ───────────────────────────────────────────────────────────

class TestKiwoomTryToken:
    async def test_success(self):
        mock_resp = _mock_httpx_response(200, {"token": "new_tok"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with (
            patch("backend.app.core.kiwoom_rest.build_broker_urls", MagicMock(return_value={"token_url": "https://api/token"})),
            patch("backend.app.core.kiwoom_rest.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            from backend.app.core.kiwoom_rest import kiwoom_try_token
            success, token, err = await kiwoom_try_token("key", "secret")
            assert success is True
            assert token == "new_tok"
            assert err is None

    async def test_no_credentials(self):
        from backend.app.core.kiwoom_rest import kiwoom_try_token
        with patch("backend.app.core.kiwoom_rest.build_broker_urls", MagicMock(return_value={"token_url": "https://api/token"})):
            success, token, err = await kiwoom_try_token("", "")
            assert success is False
            assert token is None
            assert "App Key" in err["err_msg"]

    async def test_http_failure(self):
        mock_resp = _mock_httpx_response(500, {"error": "server error"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with (
            patch("backend.app.core.kiwoom_rest.build_broker_urls", MagicMock(return_value={"token_url": "https://api/token"})),
            patch("backend.app.core.kiwoom_rest.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            from backend.app.core.kiwoom_rest import kiwoom_try_token
            success, token, err = await kiwoom_try_token("key", "secret")
            assert success is False
            assert token is None
            assert err["status"] == 500

    async def test_token_field_missing(self):
        mock_resp = _mock_httpx_response(200, {"return_msg": "8030 error", "return_code": "8030"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with (
            patch("backend.app.core.kiwoom_rest.build_broker_urls", MagicMock(return_value={"token_url": "https://api/token"})),
            patch("backend.app.core.kiwoom_rest.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            from backend.app.core.kiwoom_rest import kiwoom_try_token
            success, token, err = await kiwoom_try_token("key", "secret")
            assert success is False
            assert token is None
            assert "8030" in err["err_msg"]

    async def test_access_token_field(self):
        mock_resp = _mock_httpx_response(200, {"access_token": "alt_tok"})
        mock_client = _mock_httpx_client(post_return=mock_resp)
        with (
            patch("backend.app.core.kiwoom_rest.build_broker_urls", MagicMock(return_value={"token_url": "https://api/token"})),
            patch("backend.app.core.kiwoom_rest.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            from backend.app.core.kiwoom_rest import kiwoom_try_token
            success, token, err = await kiwoom_try_token("key", "secret")
            assert success is True
            assert token == "alt_tok"

    async def test_exception(self):
        with (
            patch("backend.app.core.kiwoom_rest.build_broker_urls", MagicMock(return_value={"token_url": "https://api/token"})),
            patch("backend.app.core.kiwoom_rest.httpx.AsyncClient", side_effect=Exception("conn error")),
        ):
            from backend.app.core.kiwoom_rest import kiwoom_try_token
            success, token, err = await kiwoom_try_token("key", "secret")
            assert success is False
            assert token is None
            assert "conn error" in err["err_msg"]
