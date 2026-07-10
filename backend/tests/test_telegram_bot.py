"""telegram_bot.py 단위 테스트 — 양방향 Bot Command 리스너 검증.

대상:
  _mask_telegram_url: URL 토큰 마스킹
  _normalize_chat_id: chat ID 정규화
  TelegramBot: 폴링 루프, 설정 조회, 명령어 라우터, 명령어 핸들러

의존성: httpx.AsyncClient, asyncio.create_task/wait_for/gather, engine_state, settings_file 등
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.telegram_bot import (
    TelegramBot,
    _mask_telegram_url,
    _normalize_chat_id,
)


# ── _mask_telegram_url ──────────────────────────────────────────────────────────

class TestMaskTelegramUrl:
    def test_masks_token_in_url(self):
        url = "https://api.telegram.org/bot123456:ABC-DEF/getUpdates"
        result = _mask_telegram_url(url)
        assert "123456:ABC-DEF" not in result
        assert "***" in result
        assert "getUpdates" in result

    def test_empty_string_returns_empty(self):
        assert _mask_telegram_url("") == ""

    def test_none_returns_none(self):
        assert _mask_telegram_url(None) is None

    def test_no_url_returns_unchanged(self):
        s = "some random error message"
        assert _mask_telegram_url(s) == s

    def test_case_insensitive(self):
        url = "https://API.TELEGRAM.ORG/botTOKEN/getUpdates"
        result = _mask_telegram_url(url)
        assert "TOKEN" not in result
        assert "***" in result

    def test_multiple_urls_all_masked(self):
        s = "https://api.telegram.org/botAAA/ and https://api.telegram.org/botBBB/"
        result = _mask_telegram_url(s)
        assert "AAA" not in result
        assert "BBB" not in result
        assert result.count("***") == 2

    def test_preserves_surrounding_text(self):
        s = "Error connecting to https://api.telegram.org/botSECRET/sendMessage failed"
        result = _mask_telegram_url(s)
        assert "SECRET" not in result
        assert result.startswith("Error connecting to ")
        assert result.endswith(" failed")


# ── _normalize_chat_id ──────────────────────────────────────────────────────────

class TestNormalizeChatId:
    def test_numeric_string(self):
        assert _normalize_chat_id("12345") == "12345"

    def test_strips_whitespace(self):
        assert _normalize_chat_id("  12345  ") == "12345"

    def test_empty_string_returns_empty(self):
        assert _normalize_chat_id("") == ""

    def test_none_returns_empty(self):
        assert _normalize_chat_id(None) == ""

    def test_non_numeric_returns_original(self):
        assert _normalize_chat_id("abc") == "abc"

    def test_float_string_returns_original(self):
        # int("12345.0") raises ValueError → 원본 문자열 반환
        assert _normalize_chat_id("12345.0") == "12345.0"

    def test_negative_number(self):
        assert _normalize_chat_id("-100") == "-100"

    def test_strips_then_converts(self):
        assert _normalize_chat_id("  999  ") == "999"


# ── TelegramBot.__init__ ────────────────────────────────────────────────────────

class TestTelegramBotInit:
    def test_defaults(self):
        bot = TelegramBot()
        assert bot._task is None
        assert bot._running is False
        assert bot._offsets == {}
        assert bot._last_poll_ok_mon is None
        assert bot._last_poll_err_mon is None
        assert bot._last_poll_err_msg == ""


# ── TelegramBot.get_poll_ok_age_sec ─────────────────────────────────────────────

class TestGetPollOkAgeSec:
    def test_none_when_no_poll(self):
        bot = TelegramBot()
        assert bot.get_poll_ok_age_sec() is None

    def test_returns_elapsed_seconds(self):
        bot = TelegramBot()
        bot._last_poll_ok_mon = time.monotonic() - 5.0
        age = bot.get_poll_ok_age_sec()
        assert age is not None
        assert age >= 4.9


# ── TelegramBot.start ───────────────────────────────────────────────────────────

class TestStart:
    def test_start_creates_task_and_sets_running(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        with patch("backend.app.services.telegram_bot.asyncio.create_task", return_value=mock_task):
            bot.start()
        assert bot._running is True
        assert bot._task is mock_task

    def test_start_skips_if_task_already_running(self):
        bot = TelegramBot()
        existing_task = MagicMock()
        existing_task.done.return_value = False
        bot._task = existing_task
        bot._running = True
        with patch("backend.app.services.telegram_bot.asyncio.create_task") as mock_create:
            bot.start()
        mock_create.assert_not_called()
        assert bot._task is existing_task

    def test_start_creates_new_task_if_previous_done(self):
        bot = TelegramBot()
        old_task = MagicMock()
        old_task.done.return_value = True
        bot._task = old_task
        new_task = MagicMock()
        new_task.done.return_value = False
        with patch("backend.app.services.telegram_bot.asyncio.create_task", return_value=new_task):
            bot.start()
        assert bot._task is new_task
        assert bot._running is True


# ── TelegramBot.stop ────────────────────────────────────────────────────────────

class TestStop:
    def test_stop_sets_running_false(self):
        bot = TelegramBot()
        bot._running = True
        bot.stop()
        assert bot._running is False

    def test_stop_cancels_task(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        bot._task = mock_task
        bot._running = True
        bot.stop()
        mock_task.cancel.assert_called_once()
        assert bot._running is False

    def test_stop_clears_poll_ok_mon(self):
        bot = TelegramBot()
        bot._last_poll_ok_mon = 123.45
        bot.stop()
        assert bot._last_poll_ok_mon is None

    def test_stop_no_task_no_error(self):
        bot = TelegramBot()
        bot.stop()
        assert bot._running is False
        assert bot._last_poll_ok_mon is None


# ── TelegramBot.stop_async ──────────────────────────────────────────────────────

class TestStopAsync:
    @pytest.mark.asyncio
    async def test_stop_async_sets_running_false(self):
        bot = TelegramBot()
        bot._running = True
        await bot.stop_async()
        assert bot._running is False

    @pytest.mark.asyncio
    async def test_stop_async_cancels_and_awaits_task(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        bot._task = mock_task

        async def fake_wait_for(coro, timeout):
            return None

        with patch("backend.app.services.telegram_bot.asyncio.wait_for", side_effect=fake_wait_for):
            await bot.stop_async()
        mock_task.cancel.assert_called_once()
        assert bot._task is None

    @pytest.mark.asyncio
    async def test_stop_async_handles_cancelled_error(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = False

        async def fake_wait_for(coro, timeout):
            raise asyncio_cancelled_error()

        with patch("backend.app.services.telegram_bot.asyncio.wait_for", side_effect=fake_wait_for):
            await bot.stop_async()
        assert bot._task is None

    @pytest.mark.asyncio
    async def test_stop_async_handles_timeout_error(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = False

        async def fake_wait_for(coro, timeout):
            raise asyncio_timeout_error()

        with patch("backend.app.services.telegram_bot.asyncio.wait_for", side_effect=fake_wait_for):
            await bot.stop_async()
        assert bot._task is None

    @pytest.mark.asyncio
    async def test_stop_async_no_task(self):
        bot = TelegramBot()
        await bot.stop_async()
        assert bot._running is False
        assert bot._task is None

    @pytest.mark.asyncio
    async def test_stop_async_task_already_done(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = True
        bot._task = mock_task
        await bot.stop_async()
        mock_task.cancel.assert_not_called()
        assert bot._task is None

    @pytest.mark.asyncio
    async def test_stop_async_clears_poll_ok_mon(self):
        bot = TelegramBot()
        bot._last_poll_ok_mon = 999.0
        await bot.stop_async()
        assert bot._last_poll_ok_mon is None


def asyncio_cancelled_error():
    import asyncio
    return asyncio.CancelledError()


def asyncio_timeout_error():
    import asyncio
    return asyncio.TimeoutError()


# ── TelegramBot._fetch_enabled_settings ─────────────────────────────────────────

class TestFetchEnabledSettings:
    def test_tele_off_returns_empty(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.integrated_system_settings_cache = {"tele_on": False}
            result = bot._fetch_enabled_settings()
        assert result == []

    def test_no_chat_id_returns_empty(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "",
            }
            result = bot._fetch_enabled_settings()
        assert result == []

    def test_plain_test_token(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_value") as mock_decrypt:
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "12345",
                "telegram_bot_token_test": "plain_test_token",
            }
            mock_decrypt.return_value = ""
            result = bot._fetch_enabled_settings()
        assert len(result) == 1
        assert result[0]["telegram_bot_token"] == "plain_test_token"
        assert result[0]["telegram_chat_id"] == "12345"
        assert result[0]["telegram_on"] is True
        assert result[0]["_profile"] == "root"

    def test_encrypted_token_decrypted(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_value", return_value="decrypted_token") as mock_decrypt:
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "999",
                "telegram_bot_token_test": "gAAAAencrypteddata",
            }
            result = bot._fetch_enabled_settings()
        assert len(result) == 1
        assert result[0]["telegram_bot_token"] == "decrypted_token"
        mock_decrypt.assert_called_once_with("gAAAAencrypteddata")

    def test_both_test_and_real_tokens(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_value", return_value=""):
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "555",
                "telegram_bot_token_test": "test_tok",
                "telegram_bot_token_real": "real_tok",
            }
            result = bot._fetch_enabled_settings()
        assert len(result) == 2
        tokens = [r["telegram_bot_token"] for r in result]
        assert "test_tok" in tokens
        assert "real_tok" in tokens

    def test_duplicate_tokens_deduplicated(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_value", return_value=""):
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "555",
                "telegram_bot_token_test": "same_token",
                "telegram_bot_token_real": "same_token",
            }
            result = bot._fetch_enabled_settings()
        assert len(result) == 1
        assert result[0]["telegram_bot_token"] == "same_token"

    def test_empty_token_skipped(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_value", return_value=""):
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "555",
                "telegram_bot_token_test": "",
                "telegram_bot_token_real": "real_tok",
            }
            result = bot._fetch_enabled_settings()
        assert len(result) == 1
        assert result[0]["telegram_bot_token"] == "real_tok"

    def test_whitespace_token_stripped(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_value", return_value=""):
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "555",
                "telegram_bot_token_test": "  spaced_token  ",
            }
            result = bot._fetch_enabled_settings()
        assert len(result) == 1
        assert result[0]["telegram_bot_token"] == "spaced_token"

    def test_chat_id_normalized(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_value", return_value=""):
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "  007788  ",
                "telegram_bot_token_test": "tok",
            }
            result = bot._fetch_enabled_settings()
        assert result[0]["telegram_chat_id"] == "7788"


# ── TelegramBot._poll_one ───────────────────────────────────────────────────────

class TestPollOne:
    @pytest.mark.asyncio
    async def test_http_200_ok_with_message_calls_handle_command(self):
        bot = TelegramBot()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "message": {
                        "chat": {"id": 12345},
                        "text": "자동",
                    },
                },
            ],
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_called_once_with("tok", "12345", "자동", "root")
        assert bot._offsets["tok"] == 101
        assert bot._last_poll_ok_mon is not None

    @pytest.mark.asyncio
    async def test_non_200_status_returns_silently(self):
        bot = TelegramBot()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_ok_false_returns_silently(self):
        bot = TelegramBot()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": False, "result": []}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_network_exception_does_not_crash(self):
        bot = TelegramBot()
        bot._running = True
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_not_called()
        assert bot._running is True  # should not stop on regular exception

    @pytest.mark.asyncio
    async def test_atexit_runtime_error_stops_polling(self):
        bot = TelegramBot()
        bot._running = True
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("atexit already called"))

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client):
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        assert bot._running is False

    @pytest.mark.asyncio
    async def test_unauthorized_chat_id_skipped(self):
        bot = TelegramBot()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 200,
                    "message": {
                        "chat": {"id": 99999},
                        "text": "자동",
                    },
                },
            ],
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_text_skipped(self):
        bot = TelegramBot()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 300,
                    "message": {
                        "chat": {"id": 12345},
                        "text": "",
                    },
                },
            ],
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_channel_post_handled(self):
        bot = TelegramBot()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 400,
                    "channel_post": {
                        "chat": {"id": 12345},
                        "text": "상태",
                    },
                },
            ],
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_called_once_with("tok", "12345", "상태", "root")

    @pytest.mark.asyncio
    async def test_offset_advances(self):
        bot = TelegramBot()
        bot._offsets["tok"] = 500
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {"update_id": 500, "message": {"chat": {"id": 12345}, "text": "자동"}},
                {"update_id": 501, "message": {"chat": {"id": 12345}, "text": "매수"}},
            ],
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock):
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        assert bot._offsets["tok"] == 502

    @pytest.mark.asyncio
    async def test_no_message_and_no_channel_post_skipped(self):
        bot = TelegramBot()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {"update_id": 600},
            ],
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client), \
             patch.object(bot, "_handle_command", new_callable=AsyncMock) as mock_handle:
            await bot._poll_one({
                "telegram_bot_token": "tok",
                "telegram_chat_id": "12345",
                "_profile": "root",
            })
        mock_handle.assert_not_called()


# ── TelegramBot._handle_command (라우터) ────────────────────────────────────────

class TestHandleCommand:
    @pytest.mark.asyncio
    async def test_cmd_auto_routes_to_toggle_master(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_toggle_auto_master", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "auto")
        mock_cmd.assert_called_once_with("tok", "123", None)

    @pytest.mark.asyncio
    async def test_cmd_korean_auto_routes_to_toggle_master(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_toggle_auto_master", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "자동")
        mock_cmd.assert_called_once_with("tok", "123", None)

    @pytest.mark.asyncio
    async def test_cmd_buy_routes_to_toggle_buy(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_toggle_auto_buy", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "매수")
        mock_cmd.assert_called_once_with("tok", "123", None)

    @pytest.mark.asyncio
    async def test_cmd_sell_routes_to_toggle_sell(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_toggle_auto_sell", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "매도")
        mock_cmd.assert_called_once_with("tok", "123", None)

    @pytest.mark.asyncio
    async def test_cmd_trade_routes_to_send(self):
        bot = TelegramBot()
        with patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._handle_command("tok", "123", "거래")
        mock_send.assert_called_once()
        assert "제거되었습니다" in mock_send.call_args[0][2]

    @pytest.mark.asyncio
    async def test_cmd_trade_english_routes_to_send(self):
        bot = TelegramBot()
        with patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._handle_command("tok", "123", "trade")
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_status_routes_to_status_full(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_status_full", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "상태")
        mock_cmd.assert_called_once_with("tok", "123", None)

    @pytest.mark.asyncio
    async def test_cmd_status_english_routes_to_status_full(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_status_full", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "status")
        mock_cmd.assert_called_once_with("tok", "123", None)

    @pytest.mark.asyncio
    async def test_cmd_hyunhwang_routes_to_status_full(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_status_full", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "현황")
        mock_cmd.assert_called_once_with("tok", "123", None)

    @pytest.mark.asyncio
    async def test_cmd_balance_routes_to_account(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_account", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "잔고")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_balance_english_routes_to_account(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_account", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "balance")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_account_routes_to_account(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_account", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "계좌")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_account_english_routes_to_account(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_account", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "account")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_sector_routes_to_sector(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_sector", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "업종")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_sector_english_routes_to_sector(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_sector", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "sector")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_candidate_routes_to_buy_candidates(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_buy_candidates", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "후보")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_candidate_english_routes_to_buy_candidates(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_buy_candidates", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "candidate")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_profit_routes_to_discontinued(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_profit_discontinued", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "수익")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_profit_english_routes_to_discontinued(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_profit_discontinued", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "profit")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_help_routes_to_help(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_help", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "도움말")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_help_english_routes_to_help(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_help", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "help")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_start_routes_to_help(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_help", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "start")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_slash_prefix_stripped(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_help", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "/help")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_unknown_cmd_routes_to_send_error(self):
        bot = TelegramBot()
        with patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._handle_command("tok", "123", "xyz")
        mock_send.assert_called_once()
        assert "알 수 없는" in mock_send.call_args[0][2]

    @pytest.mark.asyncio
    async def test_empty_text_returns_silently(self):
        bot = TelegramBot()
        with patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._handle_command("tok", "123", "")
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_profile_passed_through(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_toggle_auto_master", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "자동", "custom_profile")
        mock_cmd.assert_called_once_with("tok", "123", "custom_profile")

    @pytest.mark.asyncio
    async def test_uppercase_english_command_lowered(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_help", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "HELP")
        mock_cmd.assert_called_once_with("tok", "123")


# ── TelegramBot._send ───────────────────────────────────────────────────────────

class TestSend:
    @pytest.mark.asyncio
    async def test_send_calls_httpx_post(self):
        bot = TelegramBot()
        mock_client = AsyncMock()
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client):
            await bot._send("tok", "123", "hello")
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "sendMessage" in call_args[0][0]
        assert call_args[1]["data"]["chat_id"] == "123"
        assert call_args[1]["data"]["text"] == "hello"
        assert call_args[1]["data"]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_send_exception_does_not_crash(self):
        bot = TelegramBot()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("network error"))

        with patch("backend.app.services.telegram_bot.httpx.AsyncClient", return_value=mock_client):
            await bot._send("tok", "123", "hello")


# ── TelegramBot._cmd_help ───────────────────────────────────────────────────────

class TestCmdHelp:
    @pytest.mark.asyncio
    async def test_help_sends_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_help("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "SectorFlow Bot" in text
        assert "자동" in text
        assert "매수" in text
        assert "매도" in text
        assert "도움말" in text


# ── TelegramBot._toggle_setting_bool ────────────────────────────────────────────

class TestToggleSettingBool:
    @pytest.mark.asyncio
    async def test_toggle_false_to_true(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.settings_file.update_settings", new_callable=AsyncMock) as mock_update, \
             patch("backend.app.services.engine_config.refresh_engine_integrated_system_settings_cache", new_callable=AsyncMock) as mock_refresh, \
             patch("backend.app.services.engine_account_notify.notify_desktop_header_refresh", new_callable=AsyncMock) as mock_hdr, \
             patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new_callable=AsyncMock) as mock_tgl:
            mock_state.integrated_system_settings_cache = {"time_scheduler_on": False}
            result = await bot._toggle_setting_bool("time_scheduler_on", "자동매매 마스터")
        assert result is True
        mock_update.assert_called_once_with({"time_scheduler_on": True})
        mock_refresh.assert_called_once()
        mock_hdr.assert_called_once()
        mock_tgl.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_true_to_false(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.settings_file.update_settings", new_callable=AsyncMock) as mock_update, \
             patch("backend.app.services.engine_config.refresh_engine_integrated_system_settings_cache", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_header_refresh", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new_callable=AsyncMock):
            mock_state.integrated_system_settings_cache = {"auto_buy_on": True}
            result = await bot._toggle_setting_bool("auto_buy_on", "자동 매수")
        assert result is False
        mock_update.assert_called_once_with({"auto_buy_on": False})


# ── TelegramBot._cmd_toggle_auto_master ─────────────────────────────────────────

class TestCmdToggleAutoMaster:
    @pytest.mark.asyncio
    async def test_toggle_on_sends_on_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, return_value=True) as mock_toggle, \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_master("tok", "123")
        mock_toggle.assert_called_once_with("time_scheduler_on", "자동매매 마스터")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ON" in text

    @pytest.mark.asyncio
    async def test_toggle_off_sends_off_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, return_value=False), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_master("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "OFF" in text

    @pytest.mark.asyncio
    async def test_exception_sends_error_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, side_effect=Exception("DB error")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_master("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text


# ── TelegramBot._cmd_toggle_auto_buy ────────────────────────────────────────────

class TestCmdToggleAutoBuy:
    @pytest.mark.asyncio
    async def test_toggle_on_sends_on_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, return_value=True), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_buy("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ON" in text
        assert "자동 매수" in text

    @pytest.mark.asyncio
    async def test_toggle_off_sends_off_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, return_value=False), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_buy("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "OFF" in text

    @pytest.mark.asyncio
    async def test_exception_sends_error_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_buy("tok", "123")
        mock_send.assert_called_once()
        assert "오류" in mock_send.call_args[0][2]


# ── TelegramBot._cmd_toggle_auto_sell ───────────────────────────────────────────

class TestCmdToggleAutoSell:
    @pytest.mark.asyncio
    async def test_toggle_on_sends_on_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, return_value=True), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_sell("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ON" in text
        assert "자동 매도" in text

    @pytest.mark.asyncio
    async def test_toggle_off_sends_off_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, return_value=False), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_sell("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "OFF" in text

    @pytest.mark.asyncio
    async def test_exception_sends_error_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_toggle_setting_bool", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_toggle_auto_sell("tok", "123")
        mock_send.assert_called_once()
        assert "오류" in mock_send.call_args[0][2]


# ── TelegramBot._cmd_status_full ────────────────────────────────────────────────

class TestCmdStatusFull:
    @pytest.mark.asyncio
    async def test_status_with_snapshot(self):
        bot = TelegramBot()
        flat = {
            "time_scheduler_on": True,
            "auto_buy_on": True,
            "auto_sell_on": False,
            "buy_time_start": "09:00",
            "buy_time_end": "15:20",
            "sell_time_start": "09:00",
            "sell_time_end": "15:20",
        }
        snap = {
            "deposit": 5_000_000,
            "total_eval": 800_000,
            "total_pnl": 100_000,
            "total_rate": 14.29,
            "position_count": 3,
            "snapshot_at": "2026-07-11T10:30:00",
        }
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": True}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value=snap), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=True), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "가동중" in text
        assert "ON" in text
        assert "예수금" in text
        assert "5,000,000" in text

    @pytest.mark.asyncio
    async def test_status_without_snapshot(self):
        bot = TelegramBot()
        flat = {
            "time_scheduler_on": False,
            "auto_buy_on": False,
            "auto_sell_on": False,
            "buy_time_start": "09:00",
            "buy_time_end": "15:20",
            "sell_time_start": "09:00",
            "sell_time_end": "15:20",
        }
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": False}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value={}), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=False), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "스냅샷 없음" in text
        assert "정지" in text

    @pytest.mark.asyncio
    async def test_status_exception_sends_error(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_lifecycle.get_engine_status", side_effect=Exception("engine fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text


# ── TelegramBot._cmd_account ────────────────────────────────────────────────────

class TestCmdAccount:
    @pytest.mark.asyncio
    async def test_account_with_snapshot(self):
        bot = TelegramBot()
        snap = {
            "deposit": 1_000_000,
            "total_eval": 2_000_000,
            "total_pnl": -50_000,
            "total_rate": -2.5,
            "position_count": 5,
            "snapshot_at": "2026-07-11T14:00:00",
        }
        with patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value=snap), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_account("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "계좌 현황" in text
        assert "1,000,000" in text
        assert "-50,000" in text
        assert "5" in text

    @pytest.mark.asyncio
    async def test_account_empty_snapshot(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value={}), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_account("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "계좌 데이터가 없습니다" in text

    @pytest.mark.asyncio
    async def test_account_exception_sends_error(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_account("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text


# ── TelegramBot._cmd_sector ─────────────────────────────────────────────────────

class TestCmdSector:
    @pytest.mark.asyncio
    async def test_sector_no_data(self):
        bot = TelegramBot()
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock, return_value={"all_codes": []}), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "종목 데이터가 없습니다" in text

    @pytest.mark.asyncio
    async def test_sector_with_data(self):
        bot = TelegramBot()
        inputs = {"all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {}}

        mock_sector1 = MagicMock()
        mock_sector1.rank = 1
        mock_sector1.sector = "반도체"
        mock_sector1.avg_change_rate = 2.5
        mock_sector1.rise_count = 8
        mock_sector1.total = 10
        mock_sector1.scored_trade_amount = 500_000_000

        mock_summary = MagicMock()
        mock_summary.sectors = [mock_sector1]

        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock, return_value=inputs), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new_callable=AsyncMock, return_value=mock_summary), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "업종 분석 요약" in text
        assert "반도체" in text
        assert "상위" in text

    @pytest.mark.asyncio
    async def test_sector_empty_sectors_list(self):
        bot = TelegramBot()
        inputs = {"all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {}}
        mock_summary = MagicMock()
        mock_summary.sectors = []

        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock, return_value=inputs), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new_callable=AsyncMock, return_value=mock_summary), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "업종 데이터가 아직 없습니다" in text

    @pytest.mark.asyncio
    async def test_sector_exception_sends_error(self):
        bot = TelegramBot()
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text

    @pytest.mark.asyncio
    async def test_sector_with_lower_sectors(self):
        bot = TelegramBot()
        inputs = {"all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}, "latest_index": {}}

        sectors = []
        for i in range(8):
            s = MagicMock()
            s.rank = i + 1
            s.sector = f"업종{i+1}"
            s.avg_change_rate = float(i)
            s.rise_count = i
            s.total = 10
            s.scored_trade_amount = 100_000_000 * (i + 1)
            sectors.append(s)

        mock_summary = MagicMock()
        mock_summary.sectors = sectors

        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock, return_value=inputs), \
             patch("backend.app.domain.sector_calculator.compute_full_sector_summary", new_callable=AsyncMock, return_value=mock_summary), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "하위" in text


# ── TelegramBot._cmd_buy_candidates ─────────────────────────────────────────────

class TestCmdBuyCandidates:
    @pytest.mark.asyncio
    async def test_no_targets_sends_empty_message(self):
        bot = TelegramBot()
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=[]), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "후보 없음" in text

    @pytest.mark.asyncio
    async def test_with_targets_sends_list(self):
        bot = TelegramBot()
        targets = [
            {"rank": 1, "name": "삼성전자", "cur_price": 80000, "change_rate": 1.5, "strength": 120.0, "trade_amount": 5_0000_0000, "sector": "반도체"},
            {"rank": 2, "name": "SK하이닉스", "cur_price": 120000, "change_rate": -0.5, "strength": 80.0, "trade_amount": 3_0000_0000, "sector": "반도체"},
        ]
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "매수 후보 TOP 2" in text
        assert "삼성전자" in text
        assert "SK하이닉스" in text
        assert "▲" in text
        assert "▼" in text

    @pytest.mark.asyncio
    async def test_exception_sends_error(self):
        bot = TelegramBot()
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text

    @pytest.mark.asyncio
    async def test_zero_strength_omits_strength_text(self):
        bot = TelegramBot()
        targets = [
            {"rank": 1, "name": "테스트", "cur_price": 50000, "change_rate": 0.0, "strength": -1, "trade_amount": 0, "sector": ""},
        ]
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "체결강도" not in text


# ── TelegramBot._cmd_profit_discontinued ────────────────────────────────────────

class TestCmdProfitDiscontinued:
    @pytest.mark.asyncio
    async def test_sends_discontinued_message(self):
        bot = TelegramBot()
        with patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_profit_discontinued("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "제거되었습니다" in text
        assert "실현 손익" in text
