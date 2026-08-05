# -*- coding: utf-8 -*-
"""FastAPI 의존성 주입 — 인증된 사용자 추출.

현재 개발 모드로 항상 'dev' 반환. 프로덕션 전환 시 토큰 검증 로직 추가 필요.
"""
from __future__ import annotations
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Authorization 헤더에서 Bearer 토큰 추출 → JWT 검증 → username 반환.

    현재 개발 모드: 항상 'dev' 반환 (토큰 검증 비활성화).
    """
    return "dev"
