from __future__ import annotations
# -*- coding: utf-8 -*-
"""
브로커 팩토리

- get_broker(settings): 하위 호환 — 기존 코드가 호출하는 곳에서 동작
- get_router(settings): 하이브리드 — 기능별 Provider 매핑 라우터 반환
- reset_router(): 설정 변경 시 라우터 재생성
"""

from typing import TYPE_CHECKING

from backend.app.core.broker_interface import BrokerInterface
from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import effective_trade_mode, is_test_mode

if TYPE_CHECKING:
    from backend.app.core.broker_router import BrokerRouter

logger = get_logger("broker_factory")

_router_cache: "BrokerRouter | None" = None


def get_router(settings: dict) -> "BrokerRouter":
    """BrokerRouter 싱글턴 반환. 시작 시 1회 생성, 이후 캐시."""
    global _router_cache
    if _router_cache is None:
        from backend.app.core.broker_router import BrokerRouter

        _router_cache = BrokerRouter(settings)
        logger.info(_router_cache.summary())
        warnings = _router_cache.validate()
        for w in warnings:
            logger.warning("[증권사설정] %s", w)
    return _router_cache


def reset_router() -> None:
    """설정 변경 시 라우터 캐시 초기화. 다음 get_router() 호출 시 재생성."""
    global _router_cache
    _router_cache = None


def get_broker(settings: dict) -> BrokerInterface:
    """하위 호환: 기존 코드가 get_broker()를 호출하는 곳에서 동작."""
    from backend.app.core.kiwoom_broker import KiwoomBroker
    from backend.app.core.ls_broker import LsBroker

    broker_name = str(settings.get("broker", "") or "").lower().strip()

    if broker_name == "ls":
        tm = effective_trade_mode(settings)
        logger.info(
            "[증권사설정] ls (trade_mode=%s, is_test=%s)",
            tm,
            is_test_mode(settings),
        )
        return LsBroker(settings)
    else:
        if broker_name not in ("kiwoom", ""):
            logger.warning(
                "[증권사설정] 지원 증권사: kiwoom, ls. 증권사=%r -> kiwoom 사용",
                broker_name,
            )
        tm = effective_trade_mode(settings)
        logger.info(
            "[증권사설정] %s (trade_mode=%s, is_test=%s)",
            broker_name,
            tm,
            is_test_mode(settings),
        )
        return KiwoomBroker(settings)


def create_connector(settings: dict):
    """설정 기반 BrokerConnector 생성."""
    from backend.app.core.broker_registry import CONNECTOR_REGISTRY

    broker_name = str(settings.get("broker", "") or "").lower().strip()
    logger.info("[증권사설정] %s 연결 준비", broker_name)

    connector_registry = CONNECTOR_REGISTRY.get(broker_name)
    if not connector_registry:
        raise ValueError(f"지원하지 않는 증권사: {broker_name}")

    create_connector_func = connector_registry.get("create_connector")
    if not create_connector_func:
        raise ValueError(f"{broker_name}은(는) create_connector를 제공하지 않습니다")

    return create_connector_func(settings)
