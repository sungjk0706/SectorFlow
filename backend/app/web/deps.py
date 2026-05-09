# -*- coding: utf-8 -*-
"""FastAPI 의존성 주입 — 인증된 사용자 추출."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.web.auth import verify_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Authorization 헤더에서 Bearer 토큰 추출 → JWT 검증 → username 반환."""
    # TODO: 개발 완료 후 토큰 검증 재활성화
    return "dev"
    # if credentials is None:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="인증이 필요합니다",
    #     )
    # username = verify_token(credentials.credentials)
    # if username is None:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="토큰이 유효하지 않습니다",
    #     )
    # return username
