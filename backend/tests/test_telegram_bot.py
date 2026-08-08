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
    apply_telegram_polling_change,
    TELEGRAM_POLLING_KEYS,
)
from backend.app.services.telegram_fmt import (
    fmt_won,
    fmt_rate,
    fmt_score,
    fmt_signed_won,
    fmt_change,
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
        with patch("backend.app.services.engine_utils.asyncio.create_task", side_effect=swallow_coro_returning(mock_task)):
            bot.start()
        assert bot._running is True
        assert bot._task is mock_task

    def test_start_skips_if_task_already_running(self):
        bot = TelegramBot()
        existing_task = MagicMock()
        existing_task.done.return_value = False
        bot._task = existing_task
        bot._running = True
        with patch("backend.app.services.engine_utils.asyncio.create_task") as mock_create:
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
        with patch("backend.app.services.engine_utils.asyncio.create_task", side_effect=swallow_coro_returning(new_task)):
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
                "telegram_bot_token_virtual": "plain_test_token",
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
                "telegram_bot_token_virtual": "gAAAAencrypteddata",
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
                "telegram_bot_token_virtual": "gAAAAencrypteddata",
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
                "telegram_bot_token_virtual": "gAAAAencrypteddata",
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
                "telegram_bot_token_virtual": "test_tok",
                "telegram_bot_token_live": "real_tok",
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
                "telegram_bot_token_virtual": "same_token",
                "telegram_bot_token_live": "same_token",
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
                "telegram_bot_token_virtual": "",
                "telegram_bot_token_live": "real_tok",
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
                "telegram_bot_token_virtual": "  spaced_token  ",
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
                "telegram_bot_token_virtual": "tok",
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
    async def test_cmd_buy_routes_to_buy_history(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_buy_history", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "매수")
        mock_cmd.assert_called_once_with("tok", "123")

    @pytest.mark.asyncio
    async def test_cmd_sell_routes_to_sell_history(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_sell_history", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "매도")
        mock_cmd.assert_called_once_with("tok", "123")

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
    async def test_cmd_today_routes_to_period_pnl_today(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_period_pnl", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "당일")
        mock_cmd.assert_called_once_with("tok", "123", "당일")

    @pytest.mark.asyncio
    async def test_cmd_5day_routes_to_period_pnl_5day(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_period_pnl", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "5일")
        mock_cmd.assert_called_once_with("tok", "123", "5일")

    @pytest.mark.asyncio
    async def test_cmd_month_routes_to_period_pnl_month(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_period_pnl", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "당월")
        mock_cmd.assert_called_once_with("tok", "123", "당월")

    @pytest.mark.asyncio
    async def test_cmd_cumulative_routes_to_period_pnl_cumulative(self):
        bot = TelegramBot()
        with patch.object(bot, "_cmd_period_pnl", new_callable=AsyncMock) as mock_cmd:
            await bot._handle_command("tok", "123", "누적")
        mock_cmd.assert_called_once_with("tok", "123", "누적")

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
        # 기간별 손익 명령어 포함 확인
        assert "당일" in text
        assert "5일" in text
        assert "당월" in text
        assert "누적" in text


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


# ── TelegramBot._cmd_buy_history ────────────────────────────────────────────────

class TestCmdBuyHistory:
    @pytest.mark.asyncio
    async def test_no_records_sends_empty_message(self):
        bot = TelegramBot()
        with patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[]), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_history("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "내역 없음" in text

    @pytest.mark.asyncio
    async def test_with_records_sends_list(self):
        bot = TelegramBot()
        records = [
            {"date": "2026-07-31", "time": "09:15", "stk_nm": "삼성전자", "price": 80000,
             "qty": 10, "total_amt": 800000, "sector": "반도체", "buy_rank": 1},
            {"date": "2026-07-31", "time": "09:20", "stk_nm": "SK하이닉스", "price": 120000,
             "qty": 5, "total_amt": 600000, "sector": "반도체", "buy_rank": 2},
        ]
        with patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, return_value=records), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_history("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "매수 체결 내역" in text
        assert "삼성전자" in text
        assert "SK하이닉스" in text
        assert "80,000원" in text
        assert "반도체" in text

    @pytest.mark.asyncio
    async def test_exception_sends_error(self):
        bot = TelegramBot()
        with patch("backend.app.services.trade_history.get_buy_history", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_history("tok", "123")
        mock_send.assert_called_once()
        assert "오류" in mock_send.call_args[0][2]


# ── TelegramBot._cmd_sell_history ───────────────────────────────────────────────

class TestCmdSellHistory:
    @pytest.mark.asyncio
    async def test_no_records_sends_empty_message(self):
        bot = TelegramBot()
        with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=[]), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sell_history("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "내역 없음" in text

    @pytest.mark.asyncio
    async def test_with_records_sends_list(self):
        bot = TelegramBot()
        records = [
            {"date": "2026-07-31", "time": "10:00", "stk_nm": "삼성전자", "price": 85000,
             "qty": 10, "total_amt": 850000, "realized_pnl": 50000, "pnl_rate": 6.25,
             "reason": "익절"},
        ]
        with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, return_value=records), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sell_history("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "매도 체결 내역" in text
        assert "삼성전자" in text
        assert "85,000원" in text
        assert "+50,000원" in text
        assert "익절" in text

    @pytest.mark.asyncio
    async def test_exception_sends_error(self):
        bot = TelegramBot()
        with patch("backend.app.services.trade_history.get_sell_history", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sell_history("tok", "123")
        mock_send.assert_called_once()
        assert "오류" in mock_send.call_args[0][2]


# ── TelegramBot._cmd_period_pnl ─────────────────────────────────────────────────

class TestCmdPeriodPnl:
    """기간별 실현 손익 명령어 (당일/5일/당월/누적) — P10 SSOT, P21 투명성."""

    def _setup_test_mode(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"trade_mode": "virtual"}
        return mock_state

    @pytest.mark.asyncio
    async def test_today_period(self):
        bot = TelegramBot()
        mock_state = self._setup_test_mode()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(50_000, 500_000)) as mock_pnl, \
             patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=__import__("datetime").date(2026, 7, 31)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_period_pnl("tok", "123", "당일")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "당일 실현 손익" in text
        assert "+50,000원" in text or "+5만원" in text
        # date_from/date_to가 get_chart_reference_trading_day() 기준 당일로 설정되었는지 확인 (P10 SSOT)
        assert mock_pnl.call_args.kwargs.get("date_from") == "2026-07-31"
        assert mock_pnl.call_args.kwargs.get("date_to") == "2026-07-31"

    @pytest.mark.asyncio
    async def test_5day_period(self):
        bot = TelegramBot()
        mock_state = self._setup_test_mode()
        from datetime import date
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(120_000, 1_000_000)) as mock_pnl, \
             patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=date(2026, 7, 31)), \
             patch("backend.app.core.trading_calendar.get_recent_trading_days", return_value=[date(2026, 7, 25), date(2026, 7, 28), date(2026, 7, 29), date(2026, 7, 30), date(2026, 7, 31)]), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_period_pnl("tok", "123", "5일")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "5일 실현 손익" in text
        # date_from/date_to가 5거래일 범위로 설정되었는지 확인
        assert mock_pnl.call_args.kwargs.get("date_from") == "2026-07-25"
        assert mock_pnl.call_args.kwargs.get("date_to") == "2026-07-31"

    @pytest.mark.asyncio
    async def test_month_period(self):
        bot = TelegramBot()
        mock_state = self._setup_test_mode()
        from datetime import date
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(300_000, 2_000_000)) as mock_pnl, \
             patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=date(2026, 7, 31)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_period_pnl("tok", "123", "당월")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "당월 실현 손익" in text
        # date_from이 당월 1일인지 확인
        assert mock_pnl.call_args.kwargs.get("date_from") == "2026-07-01"
        assert mock_pnl.call_args.kwargs.get("date_to") == "2026-07-31"

    @pytest.mark.asyncio
    async def test_cumulative_period(self):
        bot = TelegramBot()
        mock_state = self._setup_test_mode()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(500_000, 5_000_000)) as mock_pnl, \
             patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=__import__("datetime").date(2026, 7, 31)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_period_pnl("tok", "123", "누적")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "누적 실현 손익" in text
        # 누적은 date_from/date_to 미지정
        assert not mock_pnl.call_args.kwargs.get("date_from")
        assert not mock_pnl.call_args.kwargs.get("date_to")

    @pytest.mark.asyncio
    async def test_real_mode_omits_rate(self):
        """실전매매 — 수익률은 증권사 서버 SSOT이므로 앱에서 재계산 금지 (AGENTS.md)."""
        bot = TelegramBot()
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"trade_mode": "live"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(500_000, 5_000_000)), \
             patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=__import__("datetime").date(2026, 7, 31)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_period_pnl("tok", "123", "누적")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "증권사 확인" in text
        # 가상매매 수익률 표시 없음
        assert "%)" not in text

    @pytest.mark.asyncio
    async def test_exception_sends_error(self):
        bot = TelegramBot()
        mock_state = self._setup_test_mode()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=__import__("datetime").date(2026, 7, 31)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_period_pnl("tok", "123", "당일")
        mock_send.assert_called_once()
        assert "오류" in mock_send.call_args[0][2]

    @pytest.mark.asyncio
    async def test_today_period_premarket(self):
        """08:00 프리마켓 개시 전 — get_chart_reference_trading_day()가 직전 거래일 반환 (P10 SSOT).

        프론트엔드 getTradingToday()와 동일 동작 — 06:47에 당일 손익 조회 시 직전 거래일 기준으로 집계.
        시나리오: 목 2026-07-30 06:47 → get_chart_reference_trading_day() → 수 2026-07-29 (직전 거래일).
        """
        bot = TelegramBot()
        mock_state = self._setup_test_mode()
        from datetime import date
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.trade_history.get_realized_pnl_summary", new_callable=AsyncMock, return_value=(80_000, 800_000)) as mock_pnl, \
             patch("backend.app.core.trading_calendar.get_chart_reference_trading_day", return_value=date(2026, 7, 29)), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_period_pnl("tok", "123", "당일")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "당일 실현 손익" in text
        # 직전 거래일(수 2026-07-29) 기준으로 date_from/date_to 설정 — 프론트 getTradingToday()와 동일 (P10 SSOT)
        assert mock_pnl.call_args.kwargs.get("date_from") == "2026-07-29"
        assert mock_pnl.call_args.kwargs.get("date_to") == "2026-07-29"


# ── TelegramBot._cmd_status_full ────────────────────────────────────────────────

class TestCmdStatusFull:
    @pytest.mark.asyncio
    async def test_status_with_snapshot(self):
        """상태 명령어 — 엔진·스케줄·스위치 + 리스크만 (계좌 제외, 잔고와 분리)."""
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
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "CLOSED"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"trade_mode": "live"}
        mock_state.krx_circuit_breaker_active = False
        mock_state.market_phase = {}
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": True}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=True), \
             patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "가동중" in text
        assert "ON" in text
        assert "자동매매 가능" in text
        # 계좌 내용 제거 확인 (잔고 명령어와 분리)
        assert "예수금" not in text
        assert "주문가능" not in text
        assert "보유 종목 평가" not in text

    @pytest.mark.asyncio
    async def test_status_without_snapshot(self):
        """상태 명령어 — 계좌 스냅샷 없어도 정상 동작 (계좌 미조회)."""
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
        mock_cb = MagicMock()
        mock_cb.get_state.return_value = "CLOSED"
        mock_rm = MagicMock()
        mock_rm.circuit_breaker = mock_cb
        mock_state = MagicMock()
        mock_state.krx_circuit_breaker_active = False
        mock_state.market_phase = {}
        with patch("backend.app.services.engine_lifecycle.get_engine_status", return_value={"running": False}), \
             patch("backend.app.core.settings_file.load_integrated_system_settings", new_callable=AsyncMock, return_value=flat), \
             patch("backend.app.services.telegram_bot.auto_trading_effective", return_value=False), \
             patch("backend.app.services.risk_manager.get_risk_manager", return_value=mock_rm), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_status_full("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "정지" in text
        assert "스냅샷 없음" not in text  # 계좌 미조회로 스냅샷 메시지 없음

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
        """실전매매 — 예수금(deposit) + 주문가능(orderable) + 평가/실현 손익 표시 (P10/P21/P23)."""
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
        mock_state.integrated_system_settings_cache = {"trade_mode": "live"}
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
        """가상매매 — 누적 투자금(initial_deposit) + 주문가능(orderable) + 평가/실현 손익 표시 (P10/P21/P23).

        가상매매에서는 deposit이 SSOT가 아니므로 "예수금" 라벨 사용 금지.
        프론트엔드 profit-shared.ts renderAccountVals와 동일 기준.
        실현 수익률 분모 = 매수원금 합계(realized_buy_total) — 양 모드 공통 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT).
        """
        bot = TelegramBot()
        snap = {
            "deposit": 0,  # 가상매매에서는 의미 없는 값
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
        mock_state.integrated_system_settings_cache = {"trade_mode": "virtual"}
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
        # 누적 실현 손익 — 분모 = realized_buy_total(8,000,000) — 양 모드 공통 (P10 SSOT)
        assert "누적 총 실현 손익금" in text
        assert "150,000" in text
        assert "누적 총 실현 수익률" in text
        # 150,000 / 8,000,000 * 100 = 1.875% → :.2f 표시 1.88%
        assert "1.88" in text
        # 가상매매에서는 "예수금" 라벨이 나오면 안 됨 (P23 일관성)
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
    async def test_sector_no_cache(self):
        bot = TelegramBot()
        mock_state = MagicMock()
        mock_state.sector_summary_cache = None
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "업종 데이터가 아직 없습니다" in text

    @pytest.mark.asyncio
    async def test_sector_with_data(self):
        from backend.app.domain.models import StockScore, SectorScore, SectorSummary
        bot = TelegramBot()
        stocks = [
            StockScore(code="005930", name="삼성전자", sector="반도체",
                       change_rate=2.5, trade_amount=5_0000_0000, avg_amt_5d=4_0000_0000,
                       strength=120.0, cur_price=80000, boost_score=3.0),
            StockScore(code="000660", name="SK하이닉스", sector="반도체",
                       change_rate=1.0, trade_amount=3_0000_0000, avg_amt_5d=2_0000_0000,
                       strength=80.0, cur_price=120000, boost_score=1.0),
        ]
        sector1 = SectorScore(sector="반도체", total=10, rise_count=8, rise_ratio=0.8,
                              avg_change_rate=2.5, avg_trade_amount=500_000_000,
                              rank=1, final_score=8.5, stocks=stocks)
        summary = SectorSummary(sectors=[sector1], buy_targets=[], blocked_targets=[])

        mock_state = MagicMock()
        mock_state.sector_summary_cache = summary
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "업종 상위 5" in text
        assert "반도체" in text
        assert "가산점 8.5/" in text  # 획득/만점 형식
        assert "삼성전자" in text  # boost_score 높은 순 최대 5개
        assert "SK하이닉스" in text

    @pytest.mark.asyncio
    async def test_sector_stocks_sorted_by_boost_score(self):
        """종목이 boost_score 내림차순으로 표시되는지 확인."""
        from backend.app.domain.models import StockScore, SectorScore, SectorSummary
        bot = TelegramBot()
        stocks = [
            StockScore(code="A", name="저가산점", sector="업종1",
                       change_rate=5.0, trade_amount=1000, avg_amt_5d=1000,
                       strength=10.0, cur_price=1000, boost_score=0.5),
            StockScore(code="B", name="고가산점", sector="업종1",
                       change_rate=1.0, trade_amount=1000, avg_amt_5d=1000,
                       strength=10.0, cur_price=1000, boost_score=5.0),
        ]
        sector1 = SectorScore(sector="업종1", total=2, rise_count=1, rise_ratio=0.5,
                              avg_change_rate=3.0, avg_trade_amount=1000,
                              rank=1, final_score=5.0, stocks=stocks)
        summary = SectorSummary(sectors=[sector1], buy_targets=[], blocked_targets=[])

        mock_state = MagicMock()
        mock_state.sector_summary_cache = summary
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        text = mock_send.call_args[0][2]
        # 고가산점이 저가산점보다 먼저 표시
        assert text.index("고가산점") < text.index("저가산점")

    @pytest.mark.asyncio
    async def test_sector_max_five_stocks(self):
        """종목이 최대 5개까지만 표시되는지 확인."""
        from backend.app.domain.models import StockScore, SectorScore, SectorSummary
        bot = TelegramBot()
        stocks = [
            StockScore(code=f"C{i}", name=f"종목{i}", sector="업종1",
                       change_rate=1.0, trade_amount=1000, avg_amt_5d=1000,
                       strength=10.0, cur_price=1000, boost_score=float(i))
            for i in range(8)
        ]
        sector1 = SectorScore(sector="업종1", total=8, rise_count=4, rise_ratio=0.5,
                              avg_change_rate=1.0, avg_trade_amount=1000,
                              rank=1, final_score=5.0, stocks=stocks)
        summary = SectorSummary(sectors=[sector1], buy_targets=[], blocked_targets=[])

        mock_state = MagicMock()
        mock_state.sector_summary_cache = summary
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        text = mock_send.call_args[0][2]
        # 종목 0~7 중 boost_score 높은 7,6,5,4,3만 표시 (5개)
        assert "종목7" in text
        assert "종목3" in text
        assert "종목2" not in text  # 6번째부터 제외

    @pytest.mark.asyncio
    async def test_sector_empty_sectors_list(self):
        bot = TelegramBot()
        mock_summary = MagicMock()
        mock_summary.sectors = []

        mock_state = MagicMock()
        mock_state.sector_summary_cache = mock_summary
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "업종 데이터가 아직 없습니다" in text

    @pytest.mark.asyncio
    async def test_sector_exception_sends_error(self):
        bot = TelegramBot()
        mock_state = MagicMock()
        del mock_state.sector_summary_cache  # 접근 시 AttributeError 발생
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text

    @pytest.mark.asyncio
    async def test_sector_top_five_only(self):
        """상위 5개 업종만 표시되는지 확인 (하위 업종 제거)."""
        from backend.app.domain.models import SectorScore, SectorSummary
        bot = TelegramBot()
        sectors = [
            SectorScore(sector=f"업종{i+1}", total=10, rise_count=5, rise_ratio=0.5,
                        avg_change_rate=float(i), avg_trade_amount=100_000_000,
                        rank=i + 1, final_score=float(10 - i), stocks=[])
            for i in range(8)
        ]
        summary = SectorSummary(sectors=sectors, buy_targets=[], blocked_targets=[])

        mock_state = MagicMock()
        mock_state.sector_summary_cache = summary
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_sector("tok", "123")
        text = mock_send.call_args[0][2]
        assert "업종1" in text  # 상위 1
        assert "업종5" in text  # 상위 5
        assert "업종6" not in text  # 6위부터 제외
        assert "하위" not in text  # 하위 섹션 제거됨


# ── TelegramBot._cmd_buy_candidates ─────────────────────────────────────────────

class TestCmdBuyCandidates:
    @pytest.mark.asyncio
    async def test_no_targets_sends_empty_message(self):
        bot = TelegramBot()
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "후보 없음" in text

    @pytest.mark.asyncio
    async def test_with_targets_sends_list(self):
        bot = TelegramBot()
        targets = [
            {"rank": 1, "name": "삼성전자", "cur_price": 80000, "change": 1200,
             "change_rate": 1.5, "strength": 120.0, "trade_amount": 5_0000_0000,
             "sector": "반도체", "guard_pass": True, "boost_score": 2.0},
            {"rank": 2, "name": "SK하이닉스", "cur_price": 120000, "change": -600,
             "change_rate": -0.5, "strength": 80.0, "trade_amount": 3_0000_0000,
             "sector": "반도체", "guard_pass": True, "boost_score": 1.0},
        ]
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "매수 후보 TOP 2" in text
        assert "삼성전자" in text
        assert "SK하이닉스" in text
        assert "▲" in text  # 상승 등락률
        assert "▼" in text  # 하락 등락률
        assert "가산점" in text
        assert "[반도체]" in text

    @pytest.mark.asyncio
    async def test_blocked_targets_excluded(self):
        """guard_pass=False (차단 종목)는 표시에서 제외되는지 확인."""
        bot = TelegramBot()
        targets = [
            {"rank": 1, "name": "통과종목", "change": 100, "change_rate": 1.0,
             "sector": "업종1", "guard_pass": True, "boost_score": 1.0},
            {"rank": 2, "name": "차단종목", "change": 200, "change_rate": 2.0,
             "sector": "업종1", "guard_pass": False, "boost_score": 2.0},
        ]
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        text = mock_send.call_args[0][2]
        assert "통과종목" in text
        assert "차단종목" not in text
        assert "매수 후보 TOP 1" in text

    @pytest.mark.asyncio
    async def test_max_ten_targets(self):
        """최대 10위까지만 표시되는지 확인."""
        bot = TelegramBot()
        targets = [
            {"rank": i, "name": f"종목{i}", "change": 0, "change_rate": 0.0,
             "sector": "업종1", "guard_pass": True, "boost_score": 0.0}
            for i in range(1, 13)
        ]
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        text = mock_send.call_args[0][2]
        assert "종목1" in text
        assert "종목10" in text
        assert "종목11" not in text
        assert "매수 후보 TOP 10" in text

    @pytest.mark.asyncio
    async def test_exception_sends_error(self):
        bot = TelegramBot()
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, side_effect=Exception("fail")), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "오류" in text

    @pytest.mark.asyncio
    async def test_none_realtime_fields_shows_misusin(self):
        """틱 미수신 시 None 필드가 "미수신"으로 표시되는지 확인 (P20 폴백 금지)."""
        bot = TelegramBot()
        targets = [
            {"rank": 1, "name": "테스트", "cur_price": None, "change": None,
             "change_rate": None, "strength": None, "trade_amount": None,
             "sector": "", "guard_pass": True, "boost_score": 0.0},
        ]
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "미수신" in text  # 대비/등락률 미수신

    @pytest.mark.asyncio
    async def test_boost_score_displayed_with_max(self):
        """가산점이 획득/만점 형식으로 표시되는지 확인."""
        bot = TelegramBot()
        targets = [
            {"rank": 1, "name": "테스트", "change": 100, "change_rate": 1.0,
             "sector": "업종1", "guard_pass": True, "boost_score": 2.5},
        ]
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}  # 모든 boost off → 만점 0
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks", new_callable=AsyncMock, return_value=targets), \
             patch("backend.app.services.engine_state.state", mock_state), \
             patch.object(bot, "_send", new_callable=AsyncMock) as mock_send:
            await bot._cmd_buy_candidates("tok", "123")
        text = mock_send.call_args[0][2]
        assert "가산점 2.5/0" in text  # 만점 0 (모든 boost off) — fmt_score(0.0) = "0" (프론트 _formatScore와 동일)


# ── fmt_won / fmt_rate / fmt_score / fmt_signed_won / fmt_change ──────────────
# 프론트엔드 ui-styles.ts / ui-styles-cells.ts 포맷 규칙과 1:1 대응 (P10 SSOT, P23 일관성).

class TestFmtWon:
    """fmt_won — 프론트엔드 fmtWon과 동일 (천 단위 콤마 + '원')."""

    def test_zero(self):
        assert fmt_won(0) == "0원"

    def test_none(self):
        assert fmt_won(None) == "0원"

    def test_under_10k_uses_comma(self):
        assert fmt_won(5000) == "5,000원"

    def test_millions_uses_full_comma(self):
        assert fmt_won(1_000_000) == "1,000,000원"
        assert fmt_won(50_000_000) == "50,000,000원"

    def test_over_100m_uses_full_comma(self):
        assert fmt_won(200_000_000) == "200,000,000원"

    def test_negative_over_100m(self):
        assert fmt_won(-500_000_000) == "-500,000,000원"

    def test_invalid_returns_zero(self):
        assert fmt_won("abc") == "0원"


class TestFmtRate:
    """fmt_rate — 프론트엔드 fmtRate + '%'와 동일 (부호 + 소수 2자리 + '%')."""

    def test_positive(self):
        assert fmt_rate(7.0) == "+7.00%"

    def test_negative(self):
        assert fmt_rate(-5.0) == "-5.00%"

    def test_zero(self):
        assert fmt_rate(0) == "0.00%"

    def test_none_returns_dash(self):
        assert fmt_rate(None) == "-"

    def test_invalid_returns_dash(self):
        assert fmt_rate("abc") == "-"


class TestFmtScore:
    """fmt_score — 프론트엔드 _formatScore와 동일 (정수면 정수, 실수면 소수 1자리)."""

    def test_integer(self):
        assert fmt_score(5) == "5"

    def test_float(self):
        assert fmt_score(2.5) == "2.5"

    def test_zero_float_treated_as_integer(self):
        assert fmt_score(0.0) == "0"

    def test_none(self):
        assert fmt_score(None) == "0"

    def test_invalid(self):
        assert fmt_score("abc") == "0"


class TestFmtSignedWon:
    """fmt_signed_won — 프론트엔드 sell-position.ts pnlText 패턴과 동일.
    양수 '+콤마원', 음수 '-콤마원', 0 '콤마원' (부호 없음)."""

    def test_positive(self):
        assert fmt_signed_won(32000) == "+32,000원"

    def test_negative(self):
        assert fmt_signed_won(-5000) == "-5,000원"

    def test_zero_no_sign(self):
        assert fmt_signed_won(0) == "0원"

    def test_none(self):
        assert fmt_signed_won(None) == "0원"

    def test_invalid(self):
        assert fmt_signed_won("abc") == "0원"


class TestFmtChange:
    """fmt_change — 프론트엔드 createChangeCell 셀 조합과 동일 (▲/▼ + 콤마 절대값)."""

    def test_positive(self):
        assert fmt_change(1200) == "▲1,200"

    def test_negative(self):
        assert fmt_change(-800) == "▼800"

    def test_zero(self):
        assert fmt_change(0) == "0"

    def test_none_returns_dash(self):
        assert fmt_change(None) == "-"

    def test_invalid_returns_dash(self):
        assert fmt_change("abc") == "-"


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
            "trade_mode": "virtual",
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
        assert "매매모드: 가상매매" in text
        assert "09:00~15:20" in text

    def test_real_mode_label(self):
        flat = self._full_flat()
        flat["trade_mode"] = "live"
        text = _build_settings_lines(flat)
        assert "매매모드: 실전매매" in text

    def test_buy_section_includes_active_conditions(self):
        text = _build_settings_lines(self._full_flat())
        assert "최대 종목: 5개" in text
        assert "종목당 금액" in text
        assert "재매수 차단: today" in text
        # 매수 차단(개별 종목 단위) — 매수 조건 섹션에 표시 (P23 책임 분리)
        assert "상승 차단: +7.00%" in text
        assert "하락 차단: -7.00%" in text
        # 일일 총매수 한도 OFF → 미포함
        assert "일일 총매수 한도" not in text

    def test_buy_section_no_conditions_shows_placeholder(self):
        flat = self._full_flat()
        for k in (
            "max_stock_cnt_on", "buy_amt_on", "max_daily_total_buy_on", "rebuy_block_on",
            "buy_block_rise_on", "buy_block_fall_on",
        ):
            flat[k] = False
        text = _build_settings_lines(flat)
        assert "제한 없음" in text

    def test_buy_section_omits_blocks_when_off(self):
        flat = self._full_flat()
        flat["buy_block_rise_on"] = False
        flat["buy_block_fall_on"] = False
        text = _build_settings_lines(flat)
        assert "상승 차단" not in text
        assert "하락 차단" not in text

    def test_sell_section_includes_tp_only(self):
        text = _build_settings_lines(self._full_flat())
        assert "익절: +5.00%" in text
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
        assert "트레일링: 시작 +10.00% / 하락 -3.00%" in text

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
        assert "종목 최대 노출: 20,000,000" in text

    def test_sector_section_includes_all_fields(self):
        text = _build_settings_lines(self._full_flat())
        assert "최소 상승 비율: +60.00%" in text
        assert "최대 업종 수: 3개" in text
        assert "수신률 임계값: +70.00%" in text
        # 매수 차단(개별 종목 단위)은 업종 필터 섹션에서 분리 — 업종 섹션 본문에 미포함 (P23 책임 분리)
        sector_part = text.split("업종 필터", 1)[1]
        assert "상승 차단" not in sector_part
        assert "하락 차단" not in sector_part

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
            "trade_mode": "virtual",
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
            await apply_telegram_polling_change({"telegram_bot_token_virtual"})
        mock_bot.stop_async.assert_called_once()
        mock_bot.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_change_with_polling_stopped_starts_only(self):
        """tele_on=True + 토큰 변경 + 폴링 미실행 → start만 (stop 불필요)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.telegram_bot.telegram_bot") as mock_bot:
            mock_state.integrated_system_settings_cache = {"tele_on": True}
            mock_bot.is_running = False
            await apply_telegram_polling_change({"telegram_bot_token_live"})
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
            await apply_telegram_polling_change({"telegram_bot_token_virtual"})
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
            "telegram_bot_token_virtual",
            "telegram_bot_token_live",
            "telegram_chat_id",
        })
