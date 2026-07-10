"""telegram.py 단위 테스트 — 토큰 선택 + 메시지 전송 검증.

_select_token: test/real 모드에 따른 토큰 선택
send_msg_async: tele_on 게이트, 토큰/chat_id 누락, httpx 전송, 예외 처리

의존성: is_test_mode (trade_mode), httpx.AsyncClient
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── _select_token ──────────────────────────────────────────────────────────────

class TestSelectToken:
    def test_test_mode_returns_test_token(self):
        from backend.app.services.telegram import _select_token
        settings = {
            "trade_mode": "test",
            "telegram_bot_token_test": "test_token_123",
            "telegram_bot_token_real": "real_token_456",
        }
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            assert _select_token(settings) == "test_token_123"

    def test_real_mode_returns_real_token(self):
        from backend.app.services.telegram import _select_token
        settings = {
            "trade_mode": "real",
            "telegram_bot_token_test": "test_token_123",
            "telegram_bot_token_real": "real_token_456",
        }
        with patch("backend.app.services.telegram.is_test_mode", return_value=False):
            assert _select_token(settings) == "real_token_456"

    def test_none_settings_returns_empty(self):
        from backend.app.services.telegram import _select_token
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            assert _select_token(None) == ""

    def test_empty_settings_returns_empty(self):
        from backend.app.services.telegram import _select_token
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            assert _select_token({}) == ""

    def test_missing_test_token_returns_empty(self):
        from backend.app.services.telegram import _select_token
        settings = {"trade_mode": "test", "telegram_bot_token_real": "real"}
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            assert _select_token(settings) == ""

    def test_missing_real_token_returns_empty(self):
        from backend.app.services.telegram import _select_token
        settings = {"trade_mode": "real", "telegram_bot_token_test": "test"}
        with patch("backend.app.services.telegram.is_test_mode", return_value=False):
            assert _select_token(settings) == ""

    def test_whitespace_token_stripped(self):
        from backend.app.services.telegram import _select_token
        settings = {"trade_mode": "test", "telegram_bot_token_test": "  token_with_spaces  "}
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            assert _select_token(settings) == "token_with_spaces"

    def test_none_token_value_returns_empty(self):
        from backend.app.services.telegram import _select_token
        settings = {"trade_mode": "test", "telegram_bot_token_test": None}
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            assert _select_token(settings) == ""


# ── send_msg_async ──────────────────────────────────────────────────────────────

class TestSendMsgAsync:
    @pytest.mark.asyncio
    async def test_tele_off_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        result = await send_msg_async("test", {"tele_on": False})
        assert result is False

    @pytest.mark.asyncio
    async def test_tele_missing_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        result = await send_msg_async("test", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_none_settings_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        result = await send_msg_async("test", None)
        assert result is False

    @pytest.mark.asyncio
    async def test_missing_token_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        settings = {"tele_on": True, "telegram_chat_id": "12345"}
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            result = await send_msg_async("test", settings)
        assert result is False

    @pytest.mark.asyncio
    async def test_missing_chat_id_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "token",
            "trade_mode": "test",
        }
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            result = await send_msg_async("test", settings)
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_token_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "",
            "telegram_chat_id": "12345",
            "trade_mode": "test",
        }
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            result = await send_msg_async("test", settings)
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_chat_id_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "token",
            "telegram_chat_id": "",
            "trade_mode": "test",
        }
        with patch("backend.app.services.telegram.is_test_mode", return_value=True):
            result = await send_msg_async("test", settings)
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_send_returns_true(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "test_token",
            "telegram_chat_id": "12345",
            "trade_mode": "test",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        with (
            patch("backend.app.services.telegram.is_test_mode", return_value=True),
            patch("backend.app.services.telegram.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await send_msg_async("Hello", settings)
        assert result is True

    @pytest.mark.asyncio
    async def test_non_200_status_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "test_token",
            "telegram_chat_id": "12345",
            "trade_mode": "test",
        }
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        with (
            patch("backend.app.services.telegram.is_test_mode", return_value=True),
            patch("backend.app.services.telegram.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await send_msg_async("Hello", settings)
        assert result is False

    @pytest.mark.asyncio
    async def test_httpx_exception_returns_false(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "test_token",
            "telegram_chat_id": "12345",
            "trade_mode": "test",
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("connection error"))
        with (
            patch("backend.app.services.telegram.is_test_mode", return_value=True),
            patch("backend.app.services.telegram.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await send_msg_async("Hello", settings)
        assert result is False

    @pytest.mark.asyncio
    async def test_real_mode_uses_real_token(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "test_token",
            "telegram_bot_token_real": "real_token",
            "telegram_chat_id": "12345",
            "trade_mode": "real",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        with (
            patch("backend.app.services.telegram.is_test_mode", return_value=False),
            patch("backend.app.services.telegram.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await send_msg_async("Hello", settings)
        assert result is True
        # URL에 real_token이 사용되었는지 확인
        call_args = mock_client.post.call_args
        assert "real_token" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_msg_type_does_not_affect_sending(self):
        from backend.app.services.telegram import send_msg_async
        settings = {
            "tele_on": True,
            "telegram_bot_token_test": "test_token",
            "telegram_chat_id": "12345",
            "trade_mode": "test",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        with (
            patch("backend.app.services.telegram.is_test_mode", return_value=True),
            patch("backend.app.services.telegram.httpx.AsyncClient", return_value=mock_client),
        ):
            result1 = await send_msg_async("Hello", settings, msg_type="buy")
            result2 = await send_msg_async("Hello", settings, msg_type="sell")
        assert result1 is True
        assert result2 is True
