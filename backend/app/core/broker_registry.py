from __future__ import annotations
# -*- coding: utf-8 -*-
"""
브로커 Provider 레지스트리

증권사 식별자 → Provider 클래스 매핑.
새 증권사 추가 시 PROVIDER_REGISTRY dict에 한 줄만 추가하면 됨.

_create_provider() 팩토리 함수:
  - 레지스트리에서 Provider 클래스를 찾아 인스턴스 생성
  - AuthProvider는 증권사당 1개만 생성 (토큰 공유)
  - 다른 Provider는 auth_provider 주입 받음
"""

import logging
from typing import TYPE_CHECKING

from backend.app.core.broker_providers import AuthProvider
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 동일 증권사 강제 쌍 ───────────────────────────────────────────────
MUST_SAME_BROKER_PAIRS: list[tuple[str, str]] = [
    ("order", "account"),  # 주문과 계좌는 동일 증권사 필수
]

# ── Provider 레지스트리 ───────────────────────────────────────────────
# 새 증권사 추가 시 이 dict에 한 줄만 추가하면 됨.

def _lazy_kiwoom_registry() -> dict[str, type]:
    """순환 import 방지: 최초 접근 시 키움 Provider 클래스 로드."""
    from backend.app.core.kiwoom_providers import (
        KiwoomAuthProvider,
        KiwoomAccountProvider,
        KiwoomOrderProvider,
        KiwoomWebSocketProvider,
        KiwoomStockProvider,
    )
    # sector는 증권사와 무관한 사용자 커스텀 데이터이므로 broker_registry에서 제거
    return {
        "auth":      KiwoomAuthProvider,
        "account":   KiwoomAccountProvider,
        "order":     KiwoomOrderProvider,
        "websocket": KiwoomWebSocketProvider,
        "stock":     KiwoomStockProvider,
    }


def _lazy_ls_registry() -> dict[str, type]:
    """순환 import 방지: 최초 접근 시 LS Provider 클래스 로드."""
    from backend.app.core.ls_providers import (
        LsAuthProvider,
        LsAccountProvider,
        LsOrderProvider,
        LsWebSocketProvider,
    )
    return {
        "auth":      LsAuthProvider,
        "account":   LsAccountProvider,
        "order":     LsOrderProvider,
        "websocket": LsWebSocketProvider,
    }



# 지연 로딩 래퍼 -- 최초 접근 시 실제 클래스 로드
class _LazyRegistry(dict):
    """PROVIDER_REGISTRY['kiwoom'] 접근 시 lazy import 수행."""
    _loaded = False

    def _ensure(self) -> None:
        if not self._loaded:
            self._loaded = True
            self["kiwoom"] = _lazy_kiwoom_registry()
            self["ls"] = _lazy_ls_registry()

    def get(self, key, default=None):
        self._ensure()
        return super().get(key, default)

    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)

    def __contains__(self, key):
        self._ensure()
        return super().__contains__(key)

    def keys(self):
        self._ensure()
        return super().keys()


PROVIDER_REGISTRY: dict[str, dict[str, type]] = _LazyRegistry()


# ── Connector 레지스트리 ───────────────────────────────────────────────
# 증권사별 create_connector 함수 매핑

def _lazy_kiwoom_connector_registry() -> dict[str, callable]:
    """순환 import 방지: 최초 접근 시 키움 Connector 팩토리 로드."""
    from backend.app.core.kiwoom_connector import create_kiwoom_connector
    return {
        "create_connector": create_kiwoom_connector,
    }


def _lazy_ls_connector_registry() -> dict[str, callable]:
    """순환 import 방지: 최초 접근 시 LS Connector 팩토리 로드."""
    from backend.app.core.ls_connector import create_ls_connector
    return {
        "create_connector": create_ls_connector,
    }


class _LazyConnectorRegistry(dict):
    """CONNECTOR_REGISTRY['kiwoom'] 접근 시 lazy import 수행."""
    _loaded = False

    def _ensure(self) -> None:
        if not self._loaded:
            self._loaded = True
            self["kiwoom"] = _lazy_kiwoom_connector_registry()
            self["ls"] = _lazy_ls_connector_registry()

    def get(self, key, default=None):
        self._ensure()
        return super().get(key, default)

    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)

    def __contains__(self, key):
        self._ensure()
        return super().__contains__(key)

    def keys(self):
        self._ensure()
        return super().keys()


CONNECTOR_REGISTRY: dict[str, dict[str, callable]] = _LazyConnectorRegistry()


def _create_provider(
    feature: str,
    broker_name: str,
    settings: dict,
    auth_cache: dict[str, AuthProvider],
) -> object:
    """
    레지스트리에서 Provider 클래스를 찾아 인스턴스 생성.

    - auth: 증권사당 1개만 생성 (토큰 공유, auth_cache에 캐싱)
    - 그 외: auth_provider 주입 받아 생성
    """
    broker_providers = PROVIDER_REGISTRY.get(broker_name)
    if not broker_providers:
        if not broker_name:
            logger.warning("[BrokerRegistry] broker 설정이 비어있음")
            return None
        raise ValueError(f"지원하지 않는 증권사: {broker_name}")

    provider_cls = broker_providers.get(feature)
    if not provider_cls:
        raise ValueError(
            f"{broker_name}은(는) {feature} 기능을 지원하지 않습니다"
        )

    # Auth는 증권사당 1개만 생성 (토큰 공유)
    if feature == "auth":
        if broker_name not in auth_cache:
            auth_cache[broker_name] = provider_cls()
        return auth_cache[broker_name]

    # 다른 Provider는 auth_provider 주입
    if broker_name not in auth_cache:
        auth_cls = broker_providers.get("auth")
        if auth_cls:
            auth_cache[broker_name] = auth_cls()

    auth_provider = auth_cache.get(broker_name)
    return provider_cls(auth_provider=auth_provider)
