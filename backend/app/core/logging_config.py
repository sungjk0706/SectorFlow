# -*- coding: utf-8 -*-
"""
앱 기동 시 1회 호출 -- loguru 기반 로깅 초기화.
"""
from __future__ import annotations

from typing import Any


def parse_log_level(raw: Any) -> str:
    valid = {"CRITICAL", "ERROR", "WARNING", "WARN", "INFO", "DEBUG"}
    s = str(raw or "INFO").strip().upper()
    return s if s in valid else "INFO"


def configure_app_logging() -> str:
    from app.config import get_settings
    from app.core.logger import setup_loguru

    level = parse_log_level(get_settings().LOG_LEVEL)
    setup_loguru(log_level=level)
    return level
