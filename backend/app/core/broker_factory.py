# -*- coding: utf-8 -*-
"""
브로커 팩토리

- get_router(): 하이브리드 — 기능별 Provider 매핑 라우터 반환
- reset_router(): 설정 변경 시 라우터 재생성
"""
from __future__ import annotations
from typing import TYPE_CHECKING
import logging
if TYPE_CHECKING:
    from backend.app.core.broker_router import BrokerRouter

logger = logging.getLogger(__name__)

_router_cache: "BrokerRouter | None" = None


def get_router() -> "BrokerRouter":
    """BrokerRouter 싱글턴 반환. 시작 시 1회 생성, 이후 캐시."""
    global _router_cache
    if _router_cache is None:
        from backend.app.core.broker_router import BrokerRouter

        _router_cache = BrokerRouter()
        logger.info(_router_cache.summary())
        warnings = _router_cache.validate()
        for w in warnings:
            logger.warning("[설정] %s", w)
    return _router_cache


def reset_router() -> None:
    """설정 변경 시 라우터 캐시 초기화. 다음 get_router() 호출 시 재생성."""
    global _router_cache
    _router_cache = None
