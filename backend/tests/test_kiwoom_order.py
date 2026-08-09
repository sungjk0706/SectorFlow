"""kiwoom_order.py 단위 테스트 — 주문 거래소 결정, HTTP 요청, 주문 전송.

resolve_exchange: _NX 접미사, exchange_mode 설정, 기본 SOR
_send_request: httpx 요청 로직, HTTP 200 반환, 예외 처리, 재시도 폐지(1회만 시도)
send_order: BUY/SELL 라우팅, 알 수 없는 주문 타입, NXT trde_tp 조정, 통신 장애, 성공/실패

의존성: build_broker_urls, httpx.AsyncClient, get_nxt_trde_tp (lazy import)
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.tests.httpx_mock_helpers import mock_httpx_client, mock_httpx_response


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
        mock_resp = mock_httpx_response(200, {"rt_cd": "0"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {})
        assert result is mock_resp

    @pytest.mark.asyncio
    async def test_non_200_fails_immediately(self):
        """재시도 폐지 — 500 응답 시 1회만 시도 후 즉시 None 반환 (설계서 결정 3)."""
        from backend.app.core.kiwoom_order import _send_request
        mock_resp = mock_httpx_response(500, {})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, delay=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_fails_immediately(self):
        """재시도 폐지 — 예외 발생 시 1회만 시도 후 즉시 None 반환 (설계서 결정 3)."""
        from backend.app.core.kiwoom_order import _send_request
        mock_client = mock_httpx_client(post_side_effect=Exception("network error"), as_context_manager=True)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, delay=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_single_attempt_success(self):
        """재시도 폐지 — 1회 시도로 성공 (설계서 결정 3)."""
        from backend.app.core.kiwoom_order import _send_request
        mock_resp = mock_httpx_response(200, {"rt_cd": "0"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        with (
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _send_request("http://test", {}, {}, delay=0)
        assert result is mock_resp


# ── send_order ─────────────────────────────────────────────────────────────────

class TestSendOrder:
    @pytest.mark.asyncio
    async def test_buy_success(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
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
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "SELL OK"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
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
            result = await send_order(settings, "token123", "INVALID", "005930", 10)
        assert result["success"] is False
        assert "알 수 없는 주문 타입" in result["msg"]

    @pytest.mark.asyncio
    async def test_rt_cd_non_zero_returns_failure(self):
        from backend.app.core.kiwoom_order import send_order
        mock_resp = mock_httpx_response(200, {"rt_cd": "1", "msg1": "잔액부족"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
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
        mock_client = mock_httpx_client(post_side_effect=Exception("network error"), as_context_manager=True)
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
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
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
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
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
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
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
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "buy", "005930", 10, price=50000)
        assert result["success"] is True


# ── send_order MODIFY/CANCEL (결정 5) ──────────────────────────────────────────

class TestSendOrderModifyCancel:
    @pytest.mark.asyncio
    async def test_modify_success(self):
        """정정 주문 성공 — kt10002 호출, mdfy_qty·mdfy_uv 파라미터 전송 (결정 5)."""
        from backend.app.core.kiwoom_order import send_order
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "정정 성공"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "MODIFY", "005930", 10, price=50000, orig_ord_no="99999")
        assert result["success"] is True
        assert result["msg"] == "정정 성공"
        # api-id 헤더가 kt10002인지 확인
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("api-id") == "kt10002"
        # 파라미터에 mdfy_qty·mdfy_uv·orig_ord_no 포함 확인
        sent_params = call_args.kwargs.get("json", {})
        assert sent_params["orig_ord_no"] == "99999"
        assert sent_params["mdfy_qty"] == "10"
        assert "mdfy_uv" in sent_params
        assert "mdfy_cond_uv" in sent_params
        # ord_qty는 MODIFY에서 사용 안 함
        assert "ord_qty" not in sent_params

    @pytest.mark.asyncio
    async def test_cancel_success(self):
        """취소 주문 성공 — kt10003 호출, cncl_qty 파라미터 전송 (결정 5)."""
        from backend.app.core.kiwoom_order import send_order
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "취소 성공"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "CANCEL", "005930", 10, orig_ord_no="99999")
        assert result["success"] is True
        assert result["msg"] == "취소 성공"
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("api-id") == "kt10003"
        sent_params = call_args.kwargs.get("json", {})
        assert sent_params["orig_ord_no"] == "99999"
        assert sent_params["cncl_qty"] == "10"
        # ord_qty는 CANCEL에서 사용 안 함
        assert "ord_qty" not in sent_params

    @pytest.mark.asyncio
    async def test_cancel_zero_qty_all_cancel(self):
        """취소 수량 '0' — 잔량 전부 취소 (설계서 3.2)."""
        from backend.app.core.kiwoom_order import send_order
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "취소 성공"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "CANCEL", "005930", 0, orig_ord_no="99999")
        assert result["success"] is True
        sent_params = mock_client.post.call_args.kwargs.get("json", {})
        assert sent_params["cncl_qty"] == "0"

    @pytest.mark.asyncio
    async def test_modify_empty_orig_ord_no_returns_failure(self):
        """정정 — 원주문번호 빈 값 시 즉시 실패 (결정 5)."""
        from backend.app.core.kiwoom_order import send_order
        settings = {"kiwoom_account_no": "12345678"}
        with patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}):
            result = await send_order(settings, "token123", "MODIFY", "005930", 10, price=50000, orig_ord_no="")
        assert result["success"] is False
        assert result["msg"] == "원주문번호 없음"
        assert result["data"] is None

    @pytest.mark.asyncio
    async def test_cancel_empty_orig_ord_no_returns_failure(self):
        """취소 — 원주문번호 빈 값 시 즉시 실패 (결정 5)."""
        from backend.app.core.kiwoom_order import send_order
        settings = {"kiwoom_account_no": "12345678"}
        with patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}):
            result = await send_order(settings, "token123", "CANCEL", "005930", 10, orig_ord_no="")
        assert result["success"] is False
        assert result["msg"] == "원주문번호 없음"
        assert result["data"] is None

    @pytest.mark.asyncio
    async def test_modify_whitespace_orig_ord_no_returns_failure(self):
        """정정 — 원주문번호 공백만 있을 때 즉시 실패 (결정 5)."""
        from backend.app.core.kiwoom_order import send_order
        settings = {"kiwoom_account_no": "12345678"}
        with patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}):
            result = await send_order(settings, "token123", "MODIFY", "005930", 10, price=50000, orig_ord_no="   ")
        assert result["success"] is False
        assert result["msg"] == "원주문번호 없음"

    @pytest.mark.asyncio
    async def test_modify_case_insensitive(self):
        """정정 — order_type 소문자도 동작 (대소문자 무관)."""
        from backend.app.core.kiwoom_order import send_order
        mock_resp = mock_httpx_response(200, {"rt_cd": "0", "msg1": "OK"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "modify", "005930", 10, price=50000, orig_ord_no="99999")
        assert result["success"] is True
        headers = mock_client.post.call_args.kwargs.get("headers", {})
        assert headers.get("api-id") == "kt10002"

    @pytest.mark.asyncio
    async def test_modify_communication_failure_returns_failure(self):
        """정정 — 통신 장애 시 실패 반환."""
        from backend.app.core.kiwoom_order import send_order
        mock_client = mock_httpx_client(post_side_effect=Exception("network error"), as_context_manager=True)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "MODIFY", "005930", 10, price=50000, orig_ord_no="99999")
        assert result["success"] is False
        assert "통신 장애" in result["msg"]

    @pytest.mark.asyncio
    async def test_modify_rt_cd_non_zero_returns_failure(self):
        """정정 — rt_cd != '0' 시 실패 반환."""
        from backend.app.core.kiwoom_order import send_order
        mock_resp = mock_httpx_response(200, {"rt_cd": "1", "msg1": "정정불가"})
        mock_client = mock_httpx_client(post_return=mock_resp, as_context_manager=True)
        settings = {"kiwoom_account_no": "12345678"}
        with (
            patch("backend.app.core.kiwoom_order.build_broker_urls", return_value={"rest_base": "https://api.kiwoom.com"}),
            patch("backend.app.core.kiwoom_order.httpx.AsyncClient", return_value=mock_client),
            patch("backend.app.core.kiwoom_order.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await send_order(settings, "token123", "MODIFY", "005930", 10, price=50000, orig_ord_no="99999")
        assert result["success"] is False
        assert result["msg"] == "정정불가"
