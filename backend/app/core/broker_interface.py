# -*- coding: utf-8 -*-
"""
브로커 추상 인터페이스 (하위 호환 통합)

서브 인터페이스(AuthProvider, AccountProvider, OrderProvider,
WebSocketProvider)를 다중 상속하여 기존 코드가 BrokerInterface를 참조하는 곳에서
깨지지 않도록 유지한다.

새 코드는 BrokerRouter를 통해 개별 Provider를 사용하는 것을 권장.
"""
from __future__ import annotations

from abc import abstractmethod

from app.core.broker_providers import (
    AccountProvider,
    AuthProvider,
    OrderProvider,
    WebSocketProvider,
)


class BrokerInterface(
    AuthProvider,
    AccountProvider,
    OrderProvider,
    WebSocketProvider,
):
    """
    하위 호환용 통합 인터페이스.

    기존 코드가 BrokerInterface를 참조하는 곳에서 깨지지 않음.
    새 코드는 BrokerRouter의 개별 Provider property를 사용할 것.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """증권사 식별자 (예: 'kiwoom')."""
        ...
