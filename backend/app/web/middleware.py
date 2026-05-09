# -*- coding: utf-8 -*-
"""
페이지 컨텍스트 유틸리티

미들웨어 대신 각 라우트에서 직접 호출하는 헬퍼 함수.
WebSocket/WS/CORS와 충돌 없음.
"""
from __future__ import annotations

from typing import Optional
from fastapi import Request

VALID_PAGE_CONTEXTS = frozenset({
    "sector_analysis",
    "realtime_quote",
    "trading",
    "account",
})


def get_page_context(request: Request) -> Optional[str]:
    """
    X-Page-Context 헤더에서 page context를 추출.
    유효한 페이지 식별자만 반환, 나머지는 None.
    """
    page_ctx = request.headers.get("x-page-context", "")
    if page_ctx in VALID_PAGE_CONTEXTS:
        return page_ctx
    return None
