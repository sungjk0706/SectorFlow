# -*- coding: utf-8 -*-
"""
텔레그램 알림 (동기 + 비동기)
"""
import logging
import httpx

from app.core.trade_mode import is_test_mode

logger = logging.getLogger(__name__)

# 테스트모드 메시지 접두사
_TEST_PREFIX = "[테스트모드] "


def _prefix_if_test(message: str, settings: dict | None) -> str:
    """테스트모드면 메시지 앞에 [테스트모드] 접두사 추가."""
    if settings and is_test_mode(settings) and not message.startswith(_TEST_PREFIX):
        return f"{_TEST_PREFIX}{message}"
    return message


def send_msg(message: str, settings: dict | None = None) -> bool:
    """
    텔레그램 메시지 전송 (동기). settings에 telegram_bot_token, telegram_chat_id 필요.
    tele_on 이 True 일 때만 전송.
    """
    settings = settings or {}
    if not settings.get("tele_on", False):
        return False
    message = _prefix_if_test(message, settings)
    token   = (settings.get("telegram_bot_token") or "").strip()
    chat_id = (settings.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return False
    try:
        url    = f"https://api.telegram.org/bot{token}/sendMessage"
        params = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        res = httpx.post(url, data=params, timeout=5)
        return res.status_code == 200
    except Exception:
        return False


async def send_msg_async(message: str, settings: dict | None = None, msg_type: str = "general") -> bool:
    """
    텔레그램 메시지 비동기 전송.
    tele_on 이 True 일 때만 전송. msg_type 은 로깅 참고용.
    """
    settings = settings or {}
    if not settings.get("tele_on", False):
        return False
    message = _prefix_if_test(message, settings)

    token   = (settings.get("telegram_bot_token") or "").strip()
    chat_id = (settings.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return False

    try:
        url    = f"https://api.telegram.org/bot{token}/sendMessage"
        params = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(url, data=params)
        return res.status_code == 200
    except Exception as e:
        logger.debug(f"[텔레그램] 메시지 전송 실패함: {e}")
        return False
