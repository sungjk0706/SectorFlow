"""telegram_bot.py 단위 테스트 — 양방향 Bot Command 리스너 검증.

대상:
  _mask_telegram_url: URL 토큰 마스킹
  _normalize_chat_id: chat ID 정규화
  TelegramBot: 폴링 루프, 설정 조회, 명령어 라우터, 명령어 핸들러

의존성: httpx.AsyncClient, asyncio.create_task/wait_for/gather, engine_state, settings_file 등
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.telegram_bot import (
    TelegramBot,
    _mask_telegram_url,
    _normalize_chat_id,
    _build_risk_status_lines,
    _build_settings_lines,
    _fmt_money,
    _fmt_pct,
    apply_telegram_polling_change,
    TELEGRAM_POLLING_KEYS,
)
from backend.app.core.encryption import SecretValueState, DecryptResult
from backend.tests._mock_helpers import swallow_coro_returning


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
        assert bot._last_poll_err_mon is None
        assert bot._last_poll_err_msg == ""


# ── TelegramBot.start ───────────────────────────────────────────────────────────

class TestStart:
    def test_start_creates_task_and_sets_running(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        with patch("backend.app.services.telegram_bot.asyncio.create_task", side_effect=swallow_coro_returning(mock_task)):
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
        with patch("backend.app.services.telegram_bot.asyncio.create_task", side_effect=swallow_coro_returning(new_task)):
            bot.start()
        assert bot._task is new_task
        assert bot._running is True


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
             patch("backend.app.core.encryption.decrypt_secret") as mock_decrypt:
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "12345",
                "telegram_bot_token_test": "plain_test_token",
            }
            result = bot._fetch_enabled_settings()
        assert len(result) == 1
        assert result[0]["telegram_bot_token"] == "plain_test_token"
        assert result[0]["telegram_chat_id"] == "12345"
        assert result[0]["_profile"] == "root"
        # 평문 토큰은 decrypt_secret을 호출하지 않음 (PLAINTEXT_LEGACY 호환).
        mock_decrypt.assert_not_called()

    def test_encrypted_token_decrypted(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_secret",
                   return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="decrypted_token")) as mock_decrypt:
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "999",
                "telegram_bot_token_test": "gAAAAencrypteddata",
            }
            result = bot._fetch_enabled_settings()
        assert len(result) == 1
        assert result[0]["telegram_bot_token"] == "decrypted_token"
        mock_decrypt.assert_called_once_with("gAAAAencrypteddata")

    def test_encrypted_token_key_unavailable_skipped(self):
        """gAAAA 토큰 + KEY_UNAVAILABLE → 스킵 + 경고 로그 (P20 폴백 제거, 폴링 차단)."""
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_secret",
                   return_value=DecryptResult(state=SecretValueState.KEY_UNAVAILABLE)), \
             patch("backend.app.services.telegram_bot.logger") as mock_logger:
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "999",
                "telegram_bot_token_test": "gAAAAencrypteddata",
            }
            result = bot._fetch_enabled_settings()
        assert result == []
        mock_logger.warning.assert_called_once()
        assert "암호화 키 없음/오류" in mock_logger.warning.call_args[0][0]

    def test_encrypted_token_decrypt_failed_skipped(self):
        """gAAAA 토큰 + DECRYPT_FAILED → 스킵 + 경고 로그."""
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_secret",
                   return_value=DecryptResult(state=SecretValueState.DECRYPT_FAILED)), \
             patch("backend.app.services.telegram_bot.logger") as mock_logger:
            mock_state.integrated_system_settings_cache = {
                "tele_on": True,
                "telegram_chat_id": "999",
                "telegram_bot_token_test": "gAAAAencrypteddata",
            }
            result = bot._fetch_enabled_settings()
        assert result == []
        mock_logger.warning.assert_called_once()
        assert "암호문 손상" in mock_logger.warning.call_args[0][0]

    def test_both_test_and_real_tokens(self):
        bot = TelegramBot()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.core.encryption.decrypt_secret"):
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
             patch("backend.app.core.encryption.decrypt_secret"):
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
             patch("backend.app.core.encryption.decrypt_secret"):
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
             patch("backend.app.core.encryption.decrypt_secret"):
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
             patch("backend.app.core.encryption.decrypt_secret"):
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
             patch("backend.app.core.settings_store.apply_settings_updates", new_callable=AsyncMock) as mock_update, \
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
             patch("backend.app.core.settings_store.apply_settings_updates", new_callable=AsyncMock) as mock_update, \
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
            "orderable": 4_000_000,
            "total_eval": 800_000,
            "total_pnl": 100_000,
            "total_rate": 14.29,
            "position_count": 3,
            "snapshot_at": "2026-07-11T10:30:00",
        }
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": True}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value=snap), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=True), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(200_000, 5_000_000)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "가동중" in text
        assert "ON" in text
        assert "예수금" in text
        assert "5,000,000" in text
        assert "주문가능" in text
        assert "4,000,000" in text
        # 라벨 명확화 + 누적 실현 손익 (P21/P23)
        assert "보유 종목 평가 금액" in text
        assert "누적 총 실현 손익금" in text
        assert "200,000" in text

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

    @pytest.mark.asyncio
    async def test_status_includes_risk_status_normal(self):
        """정상 상태 — 리스크 라인 '정상 (차단 없음)' 포함 (P21)."""
        bot = TelegramBot()
        flat = {
            "time_scheduler_on": True, "auto_buy_on": True, "auto_sell_on": False,
            "buy_time_start": "09:00", "buy_time_end": "15:20",
            "sell_time_start": "09:00", "sell_time_end": "15:20",
        }
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "CLOSED"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = False
        mock_state.market_phase = {}
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": True}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value={}), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=True), \
             patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        text = mock_send.call_args[0][2]
        assert "리스크 상태" in text
        assert "정상" in text
        assert "차단 없음" in text

    @pytest.mark.asyncio
    async def test_status_includes_risk_status_oms_cb_open(self):
        """OMS 서킷브레이커 OPEN — 매매 차단 중 + 사유 포함 (P21)."""
        bot = TelegramBot()
        flat = {
            "time_scheduler_on": False, "auto_buy_on": False, "auto_sell_on": False,
            "buy_time_start": "09:00", "buy_time_end": "15:20",
            "sell_time_start": "09:00", "sell_time_end": "15:20",
        }
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "OPEN"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = False
        mock_state.market_phase = {}
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": True}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value={}), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=False), \
             patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        text = mock_send.call_args[0][2]
        assert "매매 차단 중" in text
        assert "OMS 서킷브레이커" in text

    @pytest.mark.asyncio
    async def test_status_includes_risk_status_krx_cb_active(self):
        """KRX 서킷브레이커 발동 — 매매 차단 중 + alert 사유 포함 (P21)."""
        bot = TelegramBot()
        flat = {
            "time_scheduler_on": True, "auto_buy_on": True, "auto_sell_on": True,
            "buy_time_start": "09:00", "buy_time_end": "15:20",
            "sell_time_start": "09:00", "sell_time_end": "15:20",
        }
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "CLOSED"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = True
        mock_state.market_phase = {"krx_alert": "코스피 시장조치 1단계"}
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": True}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value={}), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=False), \
             patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        text = mock_send.call_args[0][2]
        assert "매매 차단 중" in text
        assert "KRX 서킷브레이커" in text
        assert "코스피 시장조치 1단계" in text


# ── _build_risk_status_lines ────────────────────────────────────────────────────

class TestBuildRiskStatusLines:
    """_build_risk_status_lines — 저장된 SSOT 기반 리스크 차단 상태 요약 (단계7)."""

    def test_normal_when_cb_closed_and_krx_inactive(self):
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "CLOSED"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = False
        mock_state.market_phase = {}
        with patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state):
            lines = _build_risk_status_lines()
        assert "정상" in lines
        assert "차단 없음" in lines

    def test_oms_cb_open_shows_block(self):
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "OPEN"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = False
        mock_state.market_phase = {}
        with patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state):
            lines = _build_risk_status_lines()
        assert "매매 차단 중" in lines
        assert "OMS 서킷브레이커" in lines
        assert "강제 OFF" in lines

    def test_oms_cb_half_open_shows_restricted(self):
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "HALF_OPEN"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = False
        mock_state.market_phase = {}
        with patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state):
            lines = _build_risk_status_lines()
        assert "매매 제한 중" in lines
        assert "복구 시도" in lines

    def test_krx_cb_active_shows_block_with_alert(self):
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "CLOSED"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = True
        mock_state.market_phase = {"krx_alert": "코스닥 시장조치 2단계"}
        with patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state):
            lines = _build_risk_status_lines()
        assert "매매 차단 중" in lines
        assert "KRX 서킷브레이커" in lines
        assert "코스닥 시장조치 2단계" in lines

    def test_krx_cb_active_without_alert_shows_block(self):
        """krx_alert가 빈 문자열이어도 차단 상태는 표시 (P20 폴백 금지 — 빈 값이어도 차단 사실은 표시)."""
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "CLOSED"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = True
        mock_state.market_phase = {"krx_alert": ""}
        with patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state):
            lines = _build_risk_status_lines()
        assert "매매 차단 중" in lines
        assert "KRX 서킷브레이커" in lines
        # 빈 alert는 " — " 구분자 없이 깔끔하게 표시
        assert " — " not in lines

    def test_oms_cb_open_takes_priority_over_krx(self):
        """OMS 서킷브레이커가 KRX보다 우선 (P23 — header.ts 칩 순서와 동일)."""
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "OPEN"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = True
        mock_state.market_phase = {"krx_alert": "코스피 시장조치"}
        with patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state):
            lines = _build_risk_status_lines()
        assert "OMS 서킷브레이커" in lines
        assert "KRX 서킷브레이커" not in lines

    def test_exception_returns_empty_string(self):
        """조회 실패 시 빈 문자열 반환 (P25 격리된 실패 — 상태 명령어 전체 중단 차단)."""
        with patch("backend.app.services.risk_manager.get_risk_manager", side_effect=Exception("boom")):
            lines = _build_risk_status_lines()
        assert lines == ""


# ── TelegramBot._cmd_account ────────────────────────────────────────────────────

class TestCmdAccount:
    @pytest.mark.asyncio
    async def test_account_real_mode_shows_deposit(self):
        """실전모드 — 예수금(deposit) + 주문가능(orderable) + 평가/실현 손익 표시 (P10/P21/P23)."""
        bot = TelegramBot()
        snap = {
            "deposit": 1_000_000,
            "orderable": 800_000,
            "total_eval": 2_000_000,
            "total_pnl": -50_000,
            "total_rate": -2.5,
            "position_count": 5,
            "snapshot_at": "2026-07-11T14:00:00",
        }
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"trade_mode": "real"}
        with patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value=snap), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(276_000, 10_000_000)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_account("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "계좌 현황" in text
        assert "예수금" in text
        assert "1,000,000" in text
        assert "주문가능" in text
        assert "800,000" in text
        # 라벨 명확화 — "총평가/총손익" 모호성 제거 (P23)
        assert "보유 종목 평가 금액" in text
        assert "보유 종목 평가 손익금" in text
        assert "보유 종목 평가 수익률" in text
        assert "-50,000" in text
        # 누적 실현 손익 (P21 — 프론트엔드와 동일 정보)
        assert "누적 총 실현 손익금" in text
        assert "276,000" in text
        assert "누적 총 실현 수익률" in text
        assert "5" in text

    @pytest.mark.asyncio
    async def test_account_test_mode_shows_initial_deposit(self):
        """테스트모드 — 누적 투자금(initial_deposit) + 주문가능(orderable) + 평가/실현 손익 표시 (P10/P21/P23).

        테스트모드에서는 deposit이 SSOT가 아니므로 "예수금" 라벨 사용 금지.
        프론트엔드 profit-shared.ts renderAccountVals와 동일 기준.
        실현 수익률 분모 = 누적투자금(accumulated_investment ?? initial_deposit).
        """
        bot = TelegramBot()
        snap = {
            "deposit": 0,  # 테스트모드에서는 의미 없는 값
            "initial_deposit": 10_000_000,
            "accumulated_investment": 10_000_000,
            "orderable": 9_500_000,
            "total_eval": 500_000,
            "total_pnl": 30_000,
            "total_rate": 6.38,
            "position_count": 2,
            "snapshot_at": "2026-07-11T14:00:00",
        }
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"trade_mode": "test"}
        with patch("backend.app.services.engine_account.get_account_snapshot", new_callable=AsyncMock, return_value=snap), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(150_000, 8_000_000)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_account("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "계좌 현황" in text
        assert "누적 투자금" in text
        assert "10,000,000" in text
        assert "주문가능" in text
        assert "9,500,000" in text
        # 라벨 명확화 (P23)
        assert "보유 종목 평가 금액" in text
        assert "보유 종목 평가 손익금" in text
        assert "보유 종목 평가 수익률" in text
        # 누적 실현 손익 — 테스트모드 분모 = accumulated_investment(10,000,000)
        assert "누적 총 실현 손익금" in text
        assert "150,000" in text
        assert "누적 총 실현 수익률" in text
        # 150,000 / 10,000,000 * 100 = 1.50%
        assert "1.50" in text
        # 테스트모드에서는 "예수금" 라벨이 나오면 안 됨 (P23 일관성)
        assert "예수금" not in text

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
        inputs = {"all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}}

        mock_sector1 = MagicMock()
        mock_sector1.rank = 1
        mock_sector1.sector = "반도체"
        mock_sector1.avg_change_rate = 2.5
        mock_sector1.rise_count = 8
        mock_sector1.total = 10
        mock_sector1.avg_trade_amount = 500_000_000

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
        inputs = {"all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}}
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
        inputs = {"all_codes": ["005930"], "trade_prices": {}, "trade_amounts": {}, "avg_amt_5d": {}}

        sectors = []
        for i in range(8):
            s = MagicMock()
            s.rank = i + 1
            s.sector = f"업종{i+1}"
            s.avg_change_rate = float(i)
            s.rise_count = i
            s.total = 10
            s.avg_trade_amount = 100_000_000 * (i + 1)
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


# ── _fmt_money / _fmt_pct ──────────────────────────────────────────────────────

class TestFmtMoney:
    def test_zero(self):
        assert _fmt_money(0) == "0"

    def test_none(self):
        assert _fmt_money(None) == "0"

    def test_under_10k_uses_comma(self):
        assert _fmt_money(5000) == "5,000"

    def test_10k_to_100m_uses_man(self):
        assert _fmt_money(1_000_000) == "100만"
        assert _fmt_money(50_000_000) == "5000만"

    def test_over_100m_uses_eok(self):
        assert _fmt_money(200_000_000) == "2.0억"

    def test_negative_over_100m(self):
        assert _fmt_money(-500_000_000) == "-5.0억"

    def test_invalid_returns_zero(self):
        assert _fmt_money("abc") == "0"


class TestFmtPct:
    def test_positive(self):
        assert _fmt_pct(7.0) == "+7.0%"

    def test_negative(self):
        assert _fmt_pct(-5.0) == "-5.0%"

    def test_zero(self):
        assert _fmt_pct(0) == "+0.0%"

    def test_invalid(self):
        assert _fmt_pct("abc") == "0.0%"


# ── _build_settings_lines ──────────────────────────────────────────────────────

class TestBuildSettingsLines:
    """_build_settings_lines — 주요 설정값 요약 (조회 전용, 단계8)."""

    def _full_flat(self):
        return {
            "time_scheduler_on": True,
            "auto_buy_on": True,
            "auto_sell_on": False,
            "buy_time_start": "09:00",
            "buy_time_end": "15:20",
            "sell_time_start": "09:00",
            "sell_time_end": "15:20",
            "trade_mode": "test",
            "max_stock_cnt_on": True,
            "max_stock_cnt": 5,
            "buy_amt_on": True,
            "buy_amt": 1_000_000,
            "max_daily_total_buy_on": False,
            "max_daily_total_buy_amt": 0,
            "rebuy_block_on": True,
            "rebuy_block_period": "today",
            "tp_apply": True,
            "tp_val": 5.0,
            "loss_apply": False,
            "loss_val": 0,
            "ts_apply": False,
            "ts_start_val": 0,
            "ts_drop_val": 0,
            "risk_manager_on": True,
            "daily_loss_limit_on": True,
            "daily_loss_limit": -500_000,
            "daily_loss_rate_limit_on": False,
            "daily_loss_rate_limit": -5.0,
            "consecutive_loss_limit_on": True,
            "consecutive_loss_limit": 3,
            "max_single_stock_exposure": 20_000_000,
            "sector_min_rise_ratio_pct": 60.0,
            "sector_min_trade_amt": 0.0,
            "sector_max_targets": 3,
            "sector_start_threshold_pct": 70.0,
            "buy_block_rise_on": True,
            "buy_block_rise_pct": 7.0,
            "buy_block_fall_on": True,
            "buy_block_fall_pct": -7.0,
        }

    def test_includes_all_section_headers(self):
        text = _build_settings_lines(self._full_flat())
        assert "자동매매" in text
        assert "매수 조건" in text
        assert "매도 조건" in text
        assert "리스크 관리" in text
        assert "업종 필터" in text

    def test_auto_section_shows_master_buy_sell_mode(self):
        text = _build_settings_lines(self._full_flat())
        assert "마스터: ON" in text
        assert "매수: ON" in text
        assert "매도: OFF" in text
        assert "투자모드: 테스트" in text
        assert "09:00~15:20" in text

    def test_real_mode_label(self):
        flat = self._full_flat()
        flat["trade_mode"] = "real"
        text = _build_settings_lines(flat)
        assert "투자모드: 실전" in text

    def test_buy_section_includes_active_conditions(self):
        text = _build_settings_lines(self._full_flat())
        assert "최대 종목: 5개" in text
        assert "종목당 금액" in text
        assert "재매수 차단: today" in text
        # 일일 총매수 한도 OFF → 미포함
        assert "일일 총매수 한도" not in text

    def test_buy_section_no_conditions_shows_placeholder(self):
        flat = self._full_flat()
        for k in ("max_stock_cnt_on", "buy_amt_on", "max_daily_total_buy_on", "rebuy_block_on"):
            flat[k] = False
        text = _build_settings_lines(flat)
        assert "제한 없음" in text

    def test_sell_section_includes_tp_only(self):
        text = _build_settings_lines(self._full_flat())
        assert "익절: +5.0%" in text
        # 손절/트레일링 OFF → 미포함
        assert "손절" not in text
        assert "트레일링" not in text

    def test_sell_section_no_conditions_shows_placeholder(self):
        flat = self._full_flat()
        flat["tp_apply"] = False
        text = _build_settings_lines(flat)
        assert "조건 없음" in text

    def test_sell_section_trailing_format(self):
        flat = self._full_flat()
        flat["ts_apply"] = True
        flat["ts_start_val"] = 10.0
        flat["ts_drop_val"] = -3.0
        text = _build_settings_lines(flat)
        assert "트레일링: 시작 +10.0% / 하락 -3.0%" in text

    def test_risk_section_with_manager_on(self):
        text = _build_settings_lines(self._full_flat())
        assert "리스크 매니저: ON" in text
        assert "일일 손실 한도" in text
        assert "연속 손실: 3회" in text
        # 손실률 OFF → 미포함
        assert "일일 손실률" not in text

    def test_risk_section_manager_off_omits_sub_conditions(self):
        flat = self._full_flat()
        flat["risk_manager_on"] = False
        text = _build_settings_lines(flat)
        assert "리스크 매니저" not in text
        assert "일일 손실 한도" not in text
        # 종목 최대 노출은 항상 표시
        assert "종목 최대 노출" in text

    def test_risk_section_always_shows_single_stock_exposure(self):
        text = _build_settings_lines(self._full_flat())
        assert "종목 최대 노출: 2000만" in text

    def test_sector_section_includes_all_fields(self):
        text = _build_settings_lines(self._full_flat())
        assert "최소 상승 비율: +60.0%" in text
        assert "최대 업종 수: 3개" in text
        assert "수신률 임계값: +70.0%" in text
        assert "상승 차단: +7.0%" in text
        assert "하락 차단: -7.0%" in text

    def test_sector_section_omits_blocks_when_off(self):
        flat = self._full_flat()
        flat["buy_block_rise_on"] = False
        flat["buy_block_fall_on"] = False
        text = _build_settings_lines(flat)
        assert "상승 차단" not in text
        assert "하락 차단" not in text

    def test_missing_keys_do_not_crash(self):
        """빈 dict에도 예외 없이 기본값 처리 (P25 격리된 실패)."""
        text = _build_settings_lines({})
        assert "자동매매" in text
        assert "매수 조건" in text
        assert "제한 없음" in text
        assert "조건 없음" in text


# ── _cmd_settings ──────────────────────────────────────────────────────────────

class TestCmdSettings:
    """_cmd_settings — 설정 조회 명령어 핸들러 (조회 전용, 단계8)."""

    @pytest.mark.asyncio
    async def test_settings_sends_summary(self):
        bot = TelegramBot()
        flat = {
            "time_scheduler_on": True,
            "auto_buy_on": True,
            "auto_sell_on": False,
            "buy_time_start": "09:00",
            "buy_time_end": "15:20",
            "sell_time_start": "09:00",
            "sell_time_end": "15:20",
            "trade_mode": "test",
            "max_stock_cnt_on": True,
            "max_stock_cnt": 5,
            "buy_amt_on": True,
            "buy_amt": 1_000_000,
            "rebuy_block_on": True,
            "rebuy_block_period": "today",
            "tp_apply": False,
            "loss_apply": False,
            "ts_apply": False,
            "risk_manager_on": False,
            "max_single_stock_exposure": 20_000_000,
            "sector_min_rise_ratio_pct": 60.0,
            "sector_min_trade_amt": 0.0,
            "sector_max_targets": 3,
            "sector_start_threshold_pct": 70.0,
            "buy_block_rise_on": True,
            "buy_block_rise_pct": 7.0,
            "buy_block_fall_on": True,
            "buy_block_fall_pct": -7.0,
        }
        with patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_settings("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "설정 조회" in text
        assert "변경은 UI에서만" in text
        assert "자동매매" in text
        assert "업종 필터" in text

    @pytest.mark.asyncio
    async def test_settings_exception_sends_error(self):
        bot = TelegramBot()
        with patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, side_effect=Exception("db fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_settings("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text


# ── _handle_command 라우터: 설정 명령어 ─────────────────────────────────────────

class TestHandleCommandSettingsRoute:
    @pytest.mark.asyncio
    async def test_cmd_settings_korean_routes(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_settings", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "설정")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_settings_english_routes(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_settings", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "/settings")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_settings_uppercase_english_lowered(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_settings", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "SETTINGS")
        mock_cmd.assert_called_once_with("tok", "123")


# ── _cmd_help: 설정 명령어 포함 ─────────────────────────────────────────────────

class TestCmdHelpSettings:
    @pytest.mark.asyncio
    async def test_help_includes_settings_command(self):
        bot = TelegramBot()
        with patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_help("tok", "123")
        text = mock_send.call_args[0][2]
        assert "설정" in text
        assert "조회" in text


# ── TelegramBot.is_running ──────────────────────────────────────────────────────

class TestIsRunning:
    def test_none_task(self):
        bot = TelegramBot()
        assert bot.is_running is False

    def test_running_task(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        bot._task = mock_task
        assert bot.is_running is True

    def test_done_task(self):
        bot = TelegramBot()
        mock_task = MagicMock()
        mock_task.done.return_value = True
        bot._task = mock_task
        assert bot.is_running is False


# ── apply_telegram_polling_change ───────────────────────────────────────────────

class TestApplyTelegramPollingChange:
    """단계3: 토큰 저장 후 폴링 재시작 — 설정 변경 시 start/stop/restart 단일 진입 검증."""

    @pytest.mark.asyncio
    async def test_non_telegram_keys_noop(self):
        with patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            await apply_telegram_polling_change({"sector_max_targets"})
        mock_bot.start.assert_not_called()
        mock_bot.stop_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_tele_on_true_starts_polling(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": True}
            mock_bot.is_running = False
            await apply_telegram_polling_change({"tele_on"})
        mock_bot.start.assert_called_once()
        mock_bot.stop_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_tele_on_false_stops_polling(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": False}
            mock_bot.stop_async = AsyncMock()
            await apply_telegram_polling_change({"tele_on"})
        mock_bot.stop_async.assert_called_once()
        mock_bot.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_change_with_polling_running_stops_and_starts(self):
        """tele_on=True + 토큰 변경 + 폴링 실행 중 → stop+start (즉시 재폴링)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": True}
            mock_bot.is_running = True
            mock_bot.stop_async = AsyncMock()
            await apply_telegram_polling_change({"telegram_bot_token_test"})
        mock_bot.stop_async.assert_called_once()
        mock_bot.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_change_with_polling_stopped_starts_only(self):
        """tele_on=True + 토큰 변경 + 폴링 미실행 → start만 (stop 불필요)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": True}
            mock_bot.is_running = False
            await apply_telegram_polling_change({"telegram_bot_token_real"})
        mock_bot.start.assert_called_once()
        mock_bot.stop_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_id_change_with_polling_running_stops_and_starts(self):
        """tele_on=True + chat_id 변경 + 폴링 실행 중 → stop+start."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": True}
            mock_bot.is_running = True
            mock_bot.stop_async = AsyncMock()
            await apply_telegram_polling_change({"telegram_chat_id"})
        mock_bot.stop_async.assert_called_once()
        mock_bot.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_change_with_tele_off_stops_only(self):
        """tele_on=False + 토큰 변경 → stop만 (이미 종료되어야 정상)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": False}
            mock_bot.stop_async = AsyncMock()
            await apply_telegram_polling_change({"telegram_bot_token_test"})
        mock_bot.stop_async.assert_called_once()
        mock_bot.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        """내부 예외 시 warning 로그 + 전파 차단 (P25)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot, \
             patch("backend.app.services.telegram_bot.logger") as mock_logger:
            mock_state.integrated_system_settings_cache = {"tele_on": True}
            mock_bot.is_running = False
            mock_bot.start.side_effect = Exception("boom")
            await apply_telegram_polling_change({"tele_on"})
        mock_logger.warning.assert_called_once()


# ── TELEGRAM_POLLING_KEYS 상수 ──────────────────────────────────────────────────

class TestTelegramPollingKeys:
    def test_contains_all_expected_keys(self):
        assert TELEGRAM_POLLING_KEYS == frozenset({
            "tele_on",
            "telegram_bot_token_test",
            "telegram_bot_token_real",
            "telegram_chat_id",
        })
