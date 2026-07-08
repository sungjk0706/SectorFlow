# -*- coding: utf-8 -*-
"""
텔레그램 알림 (동기 + 비동기)
"""
import logging
import httpx

from backend.app.core.trade_mode import is_test_mode

logger = logging.getLogger(__name__)


def _select_token(settings: dict | None) -> str:
    """trade_mode에 따라 테스트/실전 봇 토큰 선택 (채널 분리)."""
    settings = settings or {}
    if is_test_mode(settings):
        return (settings.get("telegram_bot_token_test") or "").strip()
    return (settings.get("telegram_bot_token_real") or "").strip()


def send_msg(message: str, settings: dict | None = None) -> bool:
    """
    텔레그램 메시지 전송 (동기). settings에 telegram_bot_token_test/real, telegram_chat_id 필요.
    tele_on 이 True 일 때만 전송.
    """
    settings = settings or {}
    if not settings.get("tele_on", False):
        return False
    token   = _select_token(settings)
    chat_id = (settings.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return False
    try:
        url    = f"https://api.telegram.org/bot{token}/sendMessage"
        params = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        res = httpx.post(url, data=params, timeout=5)
        return res.status_code == 200
    except Exception as e:
        logger.warning("[알림] 메시지 동기 전송 실패: %s", e, exc_info=True)
        return False


async def send_msg_async(message: str, settings: dict | None = None, msg_type: str = "general") -> bool:
    """
    텔레그램 메시지 비동기 전송.
    tele_on 이 True 일 때만 전송. msg_type 은 로깅 참고용.
    """
    settings = settings or {}
    if not settings.get("tele_on", False):
        return False
    token   = _select_token(settings)
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
        logger.debug(f"[알림] 메시지 전송 실패함: {e}")
        return False
