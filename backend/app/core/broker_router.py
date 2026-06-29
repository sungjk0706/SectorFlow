from __future__ import annotations
# -*- coding: utf-8 -*-
"""
BrokerRouter — 기능별 Provider 매핑 중앙 라우터.

- 시작 시 1회 생성, 이후 dict lookup O(1)
- 동일 증권사의 Provider는 AuthProvider 인스턴스 공유
- validate()로 설정 검증, summary()로 로그 출력
"""

import logging

from backend.app.core.broker_providers import (
    AccountProvider,
    AuthProvider,
    OrderProvider,
    WebSocketProvider,
)
from backend.app.core.broker_registry import (
    MUST_SAME_BROKER_PAIRS,
    PROVIDER_REGISTRY,
    _create_provider,
)

logger = logging.getLogger(__name__)

FEATURES = ("account", "order", "auth", "websocket")

# 기능 → 한글 표시 이름
_FEATURE_DISPLAY: dict[str, str] = {
    "account": "계좌",
    "order": "주문",
    "auth": "인증",
    "websocket": "웹소켓",
}


class BrokerRouter:
    """
    기능별 Provider 매핑 중앙 라우터.

    사용법:
        router = BrokerRouter()
        router.order.send_order(...)  # 전역 설정
        router.get_provider("order", "sector_ranking") # 페이지 오버라이드
    """

    # 페이지별 허용 기능 매핑 (해당 페이지가 사용하는 기능만)
    PAGE_FEATURES: dict[str, tuple[str, ...]] = {
        "realtime_quote":  ("websocket",),
        "trading":         ("order",),
        "account":         ("account", "auth"),
    }

    def __init__(self):
        self._providers: dict[str, object] = {}
        self._auth_cache: dict[str, AuthProvider] = {}
        self._broker_map: dict[str, str] = {}  # feature -> broker_name
        self._page_providers: dict[tuple[str, str], object] = {}  # (page, feature) -> Provider
        self._specs: dict[str, dict] = {}  # broker_name -> role_mappings
        self._load_specs()
        self._build()

    def _load_specs(self) -> None:
        """단일 소스 진리: state.integrated_system_settings_cache 직접 사용."""
        from backend.app.services.engine_state import state
        broker_config = state.integrated_system_settings_cache["broker_config"]
        default_broker = str(
            state.integrated_system_settings_cache["broker"]
        ).lower().strip()

        # 모든 사용 중인 broker의 spec 로드
        brokers_to_load = set([default_broker])
        for feature in FEATURES:
            broker_name = str(
                broker_config.get(feature, default_broker) or default_broker
            ).lower().strip()
            brokers_to_load.add(broker_name)

        # settings에 미리 로드된 spec 사용
        preloaded_specs = state.integrated_system_settings_cache.get("_broker_specs") or {}
        for broker_name in brokers_to_load:
            if not broker_name:
                continue
            if broker_name in preloaded_specs:
                spec_data = preloaded_specs[broker_name]
                if isinstance(spec_data, dict):
                    self._specs[broker_name] = spec_data.get("role_mappings", {})
                    logger.debug("[BrokerRouter] %s spec 로드 완료 (settings)", broker_name)
                else:
                    logger.warning("[BrokerRouter] %s spec 형식 오류: %s (기대: dict)", broker_name, type(spec_data))
            else:
                logger.warning("[BrokerRouter] %s spec 없음 (settings)", broker_name)

    def _build(self) -> None:
        """단일 소스 진리: state.integrated_system_settings_cache 직접 사용."""
        from backend.app.services.engine_state import state
        broker_config = state.integrated_system_settings_cache["broker_config"]
        default_broker = str(
            state.integrated_system_settings_cache["broker"]
        ).lower().strip()

        for feature in FEATURES:
            broker_name = str(
                broker_config.get(feature, default_broker) or default_broker
            ).lower().strip()

            provider = _create_provider(
                feature, broker_name, state.integrated_system_settings_cache, self._auth_cache
            )
            if provider:
                self._providers[feature] = provider
                self._broker_map[feature] = broker_name
            else:
                # broker 비어있음 → 기본 브로커로 폴백
                logger.warning("[BrokerRouter] broker 비어있음 — %s 폴백", default_broker)
                self._providers[feature] = _create_provider(
                    feature, default_broker, state.integrated_system_settings_cache, self._auth_cache
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
        from backend.app.services.engine_state import state
        messages: list[str] = []
        used_brokers = set(self._broker_map.values())

        # 인증 정보 존재 확인
        for broker_name in used_brokers:
            key = state.integrated_system_settings_cache.get(f"{broker_name}_app_key")
            secret = state.integrated_system_settings_cache.get(f"{broker_name}_app_secret")
            if not key or not secret:
                messages.append(
                    f"증권사 API 키가 설정되지 않았습니다. "
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
        """[브로커] 시세=설정됨, 계좌=설정됨, ... 형식 로그 문자열."""
        parts: list[str] = []
        for feature in FEATURES:
            broker_name = self._broker_map.get(feature, "")
            display_feature = _FEATURE_DISPLAY.get(feature, feature)
            parts.append(f"{display_feature}=설정됨")
        return "[증권사] " + ", ".join(parts)

    # ── 페이지 컨텍스트 지원 ──────────────────────────────────────────

    def get_provider(self, feature: str, page: str | None = None) -> object:
        """
        기능별 Provider 반환.
        - page=None → 전역 설정 (기존 동작)
        - page="sector_ranking" 등 → page_overrides 적용
        """
        from backend.app.services.engine_state import state
        if page is None:
            return self._providers[feature]

        cache_key = (page, feature)
        if cache_key in self._page_providers:
            return self._page_providers[cache_key]

        # page_overrides에서 해당 페이지·기능의 증권사 조회
        page_overrides = state.integrated_system_settings_cache.get("page_overrides") or {}
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
                feature, broker_name, state.integrated_system_settings_cache, self._auth_cache
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
        from backend.app.services.engine_state import state
        messages: list[str] = []
        page_overrides = state.integrated_system_settings_cache.get("page_overrides") or {}

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
                    feat_display = _FEATURE_DISPLAY.get(feature, feature)
                    messages.append(
                        f"{broker_name}은(는) {feat_display} 기능을 지원하지 않습니다"
                    )
                    continue
                # API 키 존재 확인
                key = _integrated_system_settings_cache.get(f"{broker_name}_app_key")
                secret = _integrated_system_settings_cache.get(f"{broker_name}_app_secret")
                if not key or not secret:
                    messages.append(f"증권사 API 키가 설정되지 않았습니다")

        # 매매 페이지: order 증권사 확인
        trading_config = page_overrides.get("trading") or {}
        if isinstance(trading_config, dict):
            pass  # order만 사용

        return messages
