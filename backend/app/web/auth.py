# -*- coding: utf-8 -*-
"""JWT 토큰 생성/검증 모듈."""
from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def _get_secret() -> str:
    """JWT 시크릿 키 — 환경변수 JWT_SECRET 우선, 없으면 Settings.ENCRYPTION_KEY 사용."""
    secret = os.environ.get("JWT_SECRET") or get_settings().ENCRYPTION_KEY
    if not secret:
        raise ValueError("JWT_SECRET 또는 ENCRYPTION_KEY가 설정되지 않았습니다")
    return secret


def create_access_token(username: str) -> str:
    """JWT 액세스 토큰 생성. 만료: 24시간."""
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def verify_token(token: str) -> str | None:
    """JWT 토큰 검증. 유효하면 username 반환, 아니면 None."""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None


def authenticate_user(username: str, password: str) -> bool:
    """사용자 인증. 고정값 admin/1234 사용 (관리자모드 제거 후 단순화)."""
    return username == "admin" and password == "1234"

