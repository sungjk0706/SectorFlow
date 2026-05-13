# -*- coding: utf-8 -*-
"""
BrokerRouter — 기능별 Provider 매핑 중앙 라우터.

- 시작 시 1회 생성, 이후 dict lookup O(1)
- 동일 증권사의 Provider는 AuthProvider 인스턴스 공유
- validate()로 설정 검증, summary()로 로그 출력
"""
from __future__ import annotations

import logging

from app.core.broker_providers import (
    AccountProvider,
    AuthProvider,
    OrderProvider,
    SectorProvider,
    WebSocketProvider,
)
from app.core.broker_registry import (
    BROKER_DISPLAY_NAMES,
    MUST_SAME_BROKER_PAIRS,
    PROVIDER_REGISTRY,
    _create_provider,
)

logger = logging.getLogger(__name__)

FEATURES = ("account", "order", "sector", "auth", "websocket")

# 기능 → 한글 표시 이름
_FEATURE_DISPLAY: dict[str, str] = {
    "account": "계좌",
    "order": "주문",
    "sector": "업종",
    "auth": "인증",
    "websocket": "웹소켓",
}


class BrokerRouter:
    """
    기능별 Provider 매핑 중앙 라우터.

    사용법:
        router = BrokerRouter(settings)
        router.sector.fetch_daily_price("005930", "20240101")  # 전역 설정
        router.get_provider("sector", "sector_analysis") # 페이지 오버라이드
    """

    # 페이지별 허용 기능 매핑 (해당 페이지가 사용하는 기능만)
    PAGE_FEATURES: dict[str, tuple[str, ...]] = {
        "sector_analysis": ("sector",),
        "realtime_quote":  ("websocket",),
        "trading":         ("order",),
        "account":         ("account", "auth"),
    }

    def __init__(self, settings: dict):
        self._settings = settings
        self._providers: dict[str, object] = {}
        self._auth_cache: dict[str, AuthProvider] = {}
        self._broker_map: dict[str, str] = {}  # feature -> broker_name
        self._page_providers: dict[tuple[str, str], object] = {}  # (page, feature) -> Provider
        self._build(settings)

    def _build(self, settings: dict) -> None:
        """설정 기반으로 Provider 인스턴스 생성 및 캐싱."""
        broker_config = settings.get("broker_config") or {}
        default_broker = str(
            settings.get("broker", "kiwoom") or "kiwoom"
        ).lower().strip()

        for feature in FEATURES:
            broker_name = str(
                broker_config.get(feature, default_broker) or default_broker
            ).lower().strip()
            try:
                self._providers[feature] = _create_provider(
                    feature, broker_name, settings, self._auth_cache
                )
                self._broker_map[feature] = broker_name
            except ValueError as e:
                # 미등록 증권사 → 기본 브로커로 폴백
                logger.warning("[BrokerRouter] %s — %s 폴백", e, default_broker)
                self._providers[feature] = _create_provider(
                    feature, default_broker, settings, self._auth_cache
                )
                self._broker_map[feature] = default_broker

    # ── Property 접근자 (dict lookup O(1)) ────────────────────────────

    @property
    def account(self) -> AccountProvider:
        return self._providers["account"]  # type: ignore[return-value]

    @property
    def order(self) -> OrderProvider:
        return self._providers["order"]  # type: ignore[return-value]

    @property
    def sector(self) -> SectorProvider:
        return self._providers["sector"]  # type: ignore[return-value]

    @property
    def auth(self) -> AuthProvider:
        return self._providers["auth"]  # type: ignore[return-value]

    @property
    def websocket(self) -> WebSocketProvider:
        return self._providers["websocket"]  # type: ignore[return-value]

    # ── 검증 ──────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        설정 검증. 경고/오류 메시지 리스트 반환.

        검증 항목:
        1. 각 증권사의 app_key/app_secret 존재 확인
        2. 주문-계좌 동일 증권사 경고
        3. 미지원 증권사/기능 조합 (이미 _build에서 ValueError)
        """
        messages: list[str] = []
        used_brokers = set(self._broker_map.values())

        # 인증 정보 존재 확인
        for broker_name in used_brokers:
            key = self._settings.get(f"{broker_name}_app_key")
            secret = self._settings.get(f"{broker_name}_app_secret")
            if not key or not secret:
                display = BROKER_DISPLAY_NAMES.get(broker_name, broker_name)
                messages.append(
                    f"{display} API 키가 설정되지 않았습니다. "
                    f"일반설정에서 입력하세요."
                )

        # 동일 증권사 강제 쌍 검증
        for feat_a, feat_b in MUST_SAME_BROKER_PAIRS:
            broker_a = self._broker_map.get(feat_a, "")
            broker_b = self._broker_map.get(feat_b, "")
            if broker_a and broker_b and broker_a != broker_b:
                name_a = _FEATURE_DISPLAY.get(feat_a, feat_a)
                name_b = _FEATURE_DISPLAY.get(feat_b, feat_b)
                messages.append(
                    f"{name_a}과 {name_b} 기능은 동일 증권사를 사용해야 합니다"
                )

        return messages

    def summary(self) -> str:
        """[브로커] 시세=키움증권, 계좌=키움증권, ... 형식 로그 문자열."""
        parts: list[str] = []
        for feature in FEATURES:
            broker_name = self._broker_map.get(feature, "kiwoom")
            display_broker = BROKER_DISPLAY_NAMES.get(
                broker_name, broker_name
            )
            display_feature = _FEATURE_DISPLAY.get(feature, feature)
            parts.append(f"{display_feature}={display_broker}")
        return "[증권사] " + ", ".join(parts)

    # ── 페이지 컨텍스트 지원 ──────────────────────────────────────────

    def get_provider(self, feature: str, page: str | None = None) -> object:
        """
        기능별 Provider 반환.
        - page=None → 전역 설정 (기존 동작)
        - page="sector_analysis" 등 → page_overrides 적용
        """
        if page is None:
            return self._providers[feature]

        cache_key = (page, feature)
        if cache_key in self._page_providers:
            return self._page_providers[cache_key]

        # page_overrides에서 해당 페이지·기능의 증권사 조회
        page_overrides = self._settings.get("page_overrides") or {}
        page_config = page_overrides.get(page) or {}
        broker_name = page_config.get(feature)

        if not broker_name:
            # 오버라이드 없음 → 전역 Provider 반환
            return self._providers[feature]

        broker_name = str(broker_name).lower().strip()
        # 전역과 동일한 증권사면 전역 Provider 재사용
        if broker_name == self._broker_map.get(feature):
            return self._providers[feature]

        # 오버라이드 증권사의 Provider 생성
        try:
            provider = _create_provider(
                feature, broker_name, self._settings, self._auth_cache
            )
            self._page_providers[cache_key] = provider
            return provider
        except ValueError as e:
            logger.warning("[BrokerRouter] 페이지 오버라이드 폴백: %s", e)
            return self._providers[feature]

    def invalidate_page(self, page: str | None = None) -> None:
        """페이지별 Provider 캐시 무효화. page=None이면 전체 무효화."""
        if page is None:
            self._page_providers.clear()
        else:
            keys_to_remove = [k for k in self._page_providers if k[0] == page]
            for k in keys_to_remove:
                del self._page_providers[k]

    def validate_page_overrides(self) -> list[str]:
        """page_overrides 설정 검증. 경고 메시지 리스트 반환."""
        messages: list[str] = []
        page_overrides = self._settings.get("page_overrides") or {}

        for page, config in page_overrides.items():
            if page not in self.PAGE_FEATURES:
                continue
            if not isinstance(config, dict):
                continue
            allowed = self.PAGE_FEATURES[page]
            for feature, broker_name in config.items():
                if feature not in allowed:
                    continue
                broker_name = str(broker_name).lower().strip()
                # Provider 구현 존재 확인
                broker_providers = PROVIDER_REGISTRY.get(broker_name)
                if not broker_providers or feature not in broker_providers:
                    display = BROKER_DISPLAY_NAMES.get(broker_name, broker_name)
                    feat_display = _FEATURE_DISPLAY.get(feature, feature)
                    messages.append(
                        f"{display}은(는) {feat_display} 기능을 지원하지 않습니다"
                    )
                    continue
                # API 키 존재 확인
                key = self._settings.get(f"{broker_name}_app_key")
                secret = self._settings.get(f"{broker_name}_app_secret")
                if not key or not secret:
                    display = BROKER_DISPLAY_NAMES.get(broker_name, broker_name)
                    messages.append(f"{display} API 키가 설정되지 않았습니다")

        # 매매 페이지: order 증권사 확인
        trading_config = page_overrides.get("trading") or {}
        if isinstance(trading_config, dict):
            pass  # order만 사용

        return messages
