# -*- coding: utf-8 -*-
"""
환경 변수 설정 -- 로컬 settings.json 기반 운영.
암호화·텔레그램 등 시스템 전역 변수만 유지.
"""
import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

logger = logging.getLogger(__name__)

_ROOT    = Path(__file__).resolve().parent.parent.parent
_BACKEND = Path(__file__).resolve().parent.parent

_ENV_PATHS = [
    _ROOT / ".env",
    _BACKEND / ".env",
]


def _load_all_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        for p in _ENV_PATHS:
            if p.is_file():
                load_dotenv(p, override=False)
    except Exception as e:
        logger.warning(".env 환경변수 로드 실패함: %s", e)


_load_all_dotenv()


def _resolve_env_file() -> str:
    for p in _ENV_PATHS:
        if p.is_file():
            return str(p)
    return str(_ROOT / ".env")


class Settings(BaseSettings):
    # Encryption
    ENCRYPTION_KEY: str = ""

    # 관리자 계정 (사용하지 않음 - 관리자모드 제거됨)
    # ADMIN_USERNAME: str = "admin"
    # ADMIN_PASSWORD: str = "1234"

    # Kiwoom REST API (엔진 테스트용 .env 폴백)
    # URL 상수는 broker_urls.py (Single Source of Truth) 참조.
    KIWOOM_BASE_URL: str = "https://api.kiwoom.com"
    KIWOOM_APP_KEY: str = ""
    KIWOOM_APP_SECRET: str = ""
    KIWOOM_ACCOUNT_NO: str = ""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Engine
    LOG_LEVEL: str = "INFO"
    TRADING_LOG_PATH: str = "logs/trading.log"

    model_config = {
        "env_file": _resolve_env_file(),
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    try:
        return Settings()
    except Exception as e:
        logger.error("[설정] 설정값 로드 실패함: %s", e)
        return Settings.model_construct(ENCRYPTION_KEY="")
