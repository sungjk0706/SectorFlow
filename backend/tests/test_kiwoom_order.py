"""kiwoom_order.py 단위 테스트 — 주문 거래소 결정, HTTP 재시도, 주문 전송.

resolve_exchange: _NX 접미사, exchange_mode 설정, 기본 SOR
_send_request: httpx 재시도 로직, HTTP 200 반환, 예외 처리, 최대 재시도 실패
send_order: BUY/SELL 라우팅, 알 수 없는 주문 타입, NXT trde_tp 조정, 통신 장애, 성공/실패

의존성: build_broker_urls, httpx.AsyncClient, get_nxt_trde_tp (lazy import)
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _mock_httpx_response(status_code=200, json_data=None):
    """httpx.Response mock 생성."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _mock_httpx_client(response=None, side_effect=None):
    """httpx.AsyncClient 컨텍스트 매니저 mock 생성.

    side_effect가 설정되면 post 호출 시 예외 발생.
    """
    mock_client = AsyncMock()
    if side_effect:
        mock_client.post = AsyncMock(side_effect=side_effect)
    else:
        mock_client.post = AsyncMock(return_value=response)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    return mock_client


# ── resolve_exchange ───────────────────────────────────────────────────────────

class TestResolveExchange:
    def test_nx_suffix_returns_nxt(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({}, "005930_NX") == "NXT"

    def test_nx_suffix_case_insensitive(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({}, "005930_nx") == "NXT"

    def test_nx_suffix_with_whitespace(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({}, "  005930_NX  ") == "NXT"

    def test_exchange_mode_krx(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({"exchange_mode": "KRX"}, "005930") == "KRX"

    def test_exchange_mode_nxt(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({"exchange_mode": "nxt"}, "005930") == "NXT"

    def test_exchange_mode_sor(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({"exchange_mode": "SOR"}, "005930") == "SOR"

    def test_no_exchange_mode_returns_sor(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({}, "005930") == "SOR"

    def test_empty_code_returns_sor(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({}, "") == "SOR"

    def test_none_code_returns_sor(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({}, None) == "SOR"

    def test_invalid_exchange_mode_returns_sor(self):
        from backend.app.core.kiwoom_order import resolve_exchange
        assert resolve_exchange({"exchange_mode": "INVALID"}, "005930") == "SOR"


# ── _send_request ──────────────────────────────────────────────────────────────

class TestSendRequest:
    @pytest.mark.asyncio
    async def test_success_returns_response(self):
        from backend.app.core.kiwoom_order import _send_request
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0"})
        mock_client = _mock_httpx_client(response=mock_resp)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, max_retries=3)
        assert result is mock_resp

    @pytest.mark.asyncio
    async def test_non_200_retries_then_fails(self):
        from backend.app.core.kiwoom_order import _send_request
        mock_resp = _mock_httpx_response(500, {})
        mock_client = _mock_httpx_client(response=mock_resp)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, max_retries=2, delay=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_retries_then_fails(self):
        from backend.app.core.kiwoom_order import _send_request
        mock_client = _mock_httpx_client(side_effect=Exception("network error"))
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, max_retries=2, delay=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_success_on_second_attempt(self):
        from backend.app.core.kiwoom_order import _send_request
        mock_resp_ok = _mock_httpx_response(200, {"rt_cd": "0"})
        mock_resp_fail = _mock_httpx_response(500, {})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_resp_fail, mock_resp_ok])
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, max_retries=3, delay=0)
        assert result is mock_resp_ok

    @pytest.mark.asyncio
    async def test_single_retry_success(self):
        from backend.app.core.kiwoom_order import _send_request
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0"})
        mock_client = _mock_httpx_client(response=mock_resp)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, max_retries=1, delay=0)
        assert result is mock_resp


# ── send_order ─────────────────────────────────────────────────────────────────

class TestSendOrder:
    @pytest.mark.asyncio
    async def test_buy_success(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = _mock_httpx_client(response=mock_resp)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "BUY", "005930", 10, price=50000)
        assert result["success"] is True
        assert result["msg"] == "OK"

    @pytest.mark.asyncio
    async def test_sell_success(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0", "msg1": "SELL OK"})
        mock_client = _mock_httpx_client(response=mock_resp)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "SELL", "005930", 10, price=50000)
        assert result["success"] is True
        assert result["msg"] == "SELL OK"

    @pytest.mark.asyncio
    async def test_unknown_order_type_returns_failure(self):
        from backend.app.core.kiwoom_order import send_order
        settings = {"kiwoom_account_no": "12345678"}
        with patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}):
            result = await send_order(settings, "token123", "CANCEL", "005930", 10)
        assert result["success"] is False
        assert "알 수 없는 주문 타입" in result["msg"]

    @pytest.mark.asyncio
    async def test_rt_cd_non_zero_returns_failure(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = _mock_httpx_response(200, {"rt_cd": "1", "msg1": "잔액부족"})
        mock_client = _mock_httpx_client(response=mock_resp)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "BUY", "005930", 10, price=50000)
        assert result["success"] is False
        assert result["msg"] == "잔액부족"

    @pytest.mark.asyncio
    async def test_communication_failure_returns_failure(self):
        from backend.app.core.kiwoom_order import send_order
        mock_client = _mock_httpx_client(side_effect=Exception("network error"))
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "BUY", "005930", 10, price=50000)
        assert result["success"] is False
        assert "통신 장애" in result["msg"]

    @pytest.mark.asyncio
    async def test_nxt_trde_tp_adjusted(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = _mock_httpx_client(response=mock_resp)
        settings = {"kiwoom_account_no": "12345678", "exchange_mode": "NXT"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
            patch("backend.app.services.daily_time_scheduler.get_nxt_trde_tp", return_value="P"),
        ):
            result = await send_order(settings, "token123", "BUY", "005930", 10, price=50000, trde_tp="3")
        assert result["success"] is True
        # trde_tp가 "P"로 조정되었는지 확인 (post 호출 인수 검증)
        call_args = mock_client.post.call_args
        sent_params = call_args.kwargs.get("json") or call_args.args[1] if len(call_args.args) > 1 else {}
        if "json" in call_args.kwargs:
            sent_params = call_args.kwargs["json"]
        assert sent_params["trde_tp"] == "P"
        assert sent_params["ord_uv"] == ""

    @pytest.mark.asyncio
    async def test_nxt_trde_tp_u_clears_price(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = _mock_httpx_client(response=mock_resp)
        settings = {"kiwoom_account_no": "12345678", "exchange_mode": "NXT"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
            patch("backend.app.services.daily_time_scheduler.get_nxt_trde_tp", return_value="U"),
        ):
            result = await send_order(settings, "token123", "BUY", "005930", 10, price=50000, trde_tp="1")
        assert result["success"] is True
        call_args = mock_client.post.call_args
        sent_params = call_args.kwargs.get("json", {})
        assert sent_params["trde_tp"] == "U"
        assert sent_params["ord_uv"] == ""

    @pytest.mark.asyncio
    async def test_sor_trde_tp_not_adjusted(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = _mock_httpx_client(response=mock_resp)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "BUY", "005930", 10, price=50000, trde_tp="3")
        assert result["success"] is True
        call_args = mock_client.post.call_args
        sent_params = call_args.kwargs.get("json", {})
        assert sent_params["trde_tp"] == "3"
        # trde_tp="3"이면 ord_uv는 항상 "" (소스: ord_uv = "" if trde_tp == "3" else str(price))
        assert sent_params["ord_uv"] == ""

    @pytest.mark.asyncio
    async def test_order_type_case_insensitive(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = _mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = _mock_httpx_client(response=mock_resp)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "buy", "005930", 10, price=50000)
        assert result["success"] is True
