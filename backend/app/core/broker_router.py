# -*- coding: utf-8 -*-
"""
BrokerRouter — 기능별 Provider 매핑 중앙 라우터.

- 시작 시 1회 생성, 이후 dict lookup O(1)
- 동일 증권사의 Provider는 AuthProvider 인스턴스 공유
- validate()로 설정 검증, summary()로 로그 출력
"""
from __future__ import annotations
import logging
from backend.app.core.broker_providers import (
    AuthProvider,
    OrderProvider,
    WebSocketProvider,
)
from backend.app.core.broker_registry import (
    MUST_SAME_BROKER_PAIRS,
    _create_provider,
)
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES

logger = logging.getLogger(__name__)

FEATURES = ("order", "auth", "websocket")

# 기능 → 한글 표시 이름
_FEATURE_DISPLAY: dict[str, str] = {
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
    """

    # 페이지별 허용 기능 매핑 (해당 페이지가 사용하는 기능만)
    PAGE_FEATURES: dict[str, tuple[str, ...]] = {
        "realtime_quote":  ("websocket",),
        "trading":         ("order",),
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
        """단일 소스 진리: state.integrated_system_settings_cache 직접 사용.

        캐시는 app.py 시작 시 build_engine_settings_dict로 정규화되어
        broker_config의 모든 feature 키가 항상 설정되어 있음 (P20 폴백 금지).
        """
        from backend.app.services.engine_state import state
        broker_config = state.integrated_system_settings_cache["broker_config"]
        default_broker = str(
            state.integrated_system_settings_cache["broker"]
        ).lower().strip()

        # 모든 사용 중인 broker의 spec 로드
        brokers_to_load = set([default_broker])
        for feature in FEATURES:
            broker_name = str(broker_config[feature]).lower().strip()
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
                else:
                    logger.warning("[설정] %s 설정 형식 오류: %s (기대: 사전 형식)", BROKER_DISPLAY_NAMES.get(broker_name, broker_name), type(spec_data))
            else:
                logger.warning("[설정] %s 설정 없음", BROKER_DISPLAY_NAMES.get(broker_name, broker_name))

    def _build(self) -> None:
        """단일 소스 진리: state.integrated_system_settings_cache 직접 사용.

        캐시는 app.py 시작 시 build_engine_settings_dict로 정규화되어
        broker_config의 모든 feature 키가 항상 설정되어 있음 (P20 폴백 금지).
        """
        from backend.app.services.engine_state import state
        broker_config = state.integrated_system_settings_cache["broker_config"]

        for feature in FEATURES:
            broker_name = str(broker_config[feature]).lower().strip()

            provider = _create_provider(
                feature, broker_name, state.integrated_system_settings_cache, self._auth_cache
            )
            if provider is None:
                # _create_provider는 broker_name이 빈 문자열일 때만 None 반환.
                # _normalize_broker_config가 모든 feature를 채우므로 정상 경로 도달 불가 (P20).
                raise ValueError(f"지원하지 않는 증권사: {broker_name!r}")
            self._providers[feature] = provider
            self._broker_map[feature] = broker_name

    # ── Property 접근자 (dict lookup O(1)) ────────────────────────────

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
                    "증권사 API 키가 설정되지 않았습니다. "
                    "일반설정에서 입력하세요."
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
            display_feature = _FEATURE_DISPLAY.get(feature, feature)
            parts.append(f"{display_feature}=설정됨")
        return "[증권사] " + ", ".join(parts)
