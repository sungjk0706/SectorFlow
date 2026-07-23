"""broker_router.py 단위 테스트 — BrokerRouter 기능별 Provider 매핑 라우터 검증.

_load_specs / _build / properties / validate / summary 동작 검증.
의존성: _create_provider, PROVIDER_REGISTRY, state.integrated_system_settings_cache를 mock으로 대체.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from backend.app.core.broker_router import BrokerRouter, FEATURES, _FEATURE_DISPLAY


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _mock_settings(
    broker="kiwoom",
    broker_config=None,
    app_key="test_key",
    app_secret="test_secret",
    preloaded_specs=None,
    page_overrides=None,
):
    """테스트용 integrated_system_settings_cache dict 생성.

    broker_config이 제공되지 않으면 build_engine_settings_dict와 동일하게
    모든 feature를 broker로 채운 정규화된 dict 생성 (P20 폴백 금지 준수).
    """
    if broker_config is None:
        broker_config = {
            "websocket": broker,
            "order": broker,
            "sector": broker,
            "auth": broker,
        }
    else:
        # 부분 broker_config 병합 — 누락 feature는 기본 broker로 채움 (P20 정규화 준수)
        full = {
            "websocket": broker,
            "order": broker,
            "sector": broker,
            "auth": broker,
        }
        full.update(broker_config)
        broker_config = full
    settings = {
        "broker": broker,
        "broker_config": broker_config,
        f"{broker}_app_key": app_key,
        f"{broker}_app_secret": app_secret,
        "_broker_specs": preloaded_specs or {},
    }
    if page_overrides is not None:
        settings["page_overrides"] = page_overrides
    return settings


def _make_router(settings=None, create_provider_side_effect=None):
    """BrokerRouter 인스턴스 생성 — _create_provider를 mock으로 대체.

    create_provider_side_effect: None → 기본 MagicMock 반환,
                                 list → 순차적으로 다른 provider 반환,
                                 callable → 해당 함수 호출.
    """
    if create_provider_side_effect is None:
        mock_provider = MagicMock()
        create_provider_side_effect = [mock_provider] * len(FEATURES)

    settings = settings or _mock_settings()
    mock_state = MagicMock()
    mock_state.integrated_system_settings_cache = settings

    with (
        patch("backend.app.services.engine_state.state", mock_state),
        patch("backend.app.core.broker_router._create_provider", side_effect=create_provider_side_effect),
    ):
        router = BrokerRouter()

    return router, mock_state


# ── __init__ / _load_specs ─────────────────────────────────────────────────────

class TestInitAndLoadSpecs:
    def test_init_creates_empty_dicts(self):
        """__init__ → 내부 dict 초기화 후 _load_specs + _build 호출."""
        router, _ = _make_router()
        assert isinstance(router._providers, dict)
        assert isinstance(router._auth_cache, dict)
        assert isinstance(router._broker_map, dict)
        assert isinstance(router._page_providers, dict)
        assert isinstance(router._specs, dict)

    def test_load_specs_with_preloaded(self):
        """preloaded_specs에 spec이 있으면 _specs에 로드됨."""
        specs = {
            "kiwoom": {"role_mappings": {"tr_id_1": "KT00001"}},
        }
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        assert router._specs["kiwoom"] == {"tr_id_1": "KT00001"}

    def test_load_specs_spec_format_error(self):
        """spec 형식이 dict가 아닌 경우 → 경고 로그, _specs에 미추가."""
        specs = {"kiwoom": "not_a_dict"}
        settings = _mock_settings(preloaded_specs=specs)
        with (
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.core.broker_router._create_provider", return_value=MagicMock()),
            patch("backend.app.core.broker_router.logger") as mock_logger,
        ):
            mock_state.integrated_system_settings_cache = settings
            BrokerRouter()

        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("형식 오류" in m for m in warning_msgs)

    def test_load_specs_spec_missing(self):
        """preloaded_specs에 broker가 없는 경우 → 경고 로그."""
        settings = _mock_settings(preloaded_specs={})
        with (
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.core.broker_router._create_provider", return_value=MagicMock()),
            patch("backend.app.core.broker_router.logger") as mock_logger,
        ):
            mock_state.integrated_system_settings_cache = settings
            BrokerRouter()

        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("설정 없음" in m for m in warning_msgs)

    def test_load_specs_empty_broker_name_skipped(self):
        """broker_name이 빈 문자열이면 스킵됨."""
        settings = _mock_settings(broker="")
        with (
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.core.broker_router._create_provider", return_value=MagicMock()),
        ):
            mock_state.integrated_system_settings_cache = settings
            router = BrokerRouter()

        # 빈 broker_name은 brokers_to_load에 포함되지만 스킵됨
        assert "" not in router._specs

    def test_load_specs_broker_config_override(self):
        """broker_config에 feature별 다른 broker가 있으면 모두 로드 대상."""
        specs = {
            "kiwoom": {"role_mappings": {"tr1": "KT1"}},
            "ls": {"role_mappings": {"tr2": "LS1"}},
        }
        settings = _mock_settings(
            broker="kiwoom",
            broker_config={"order": "ls"},
            preloaded_specs=specs,
        )
        router, _ = _make_router(settings=settings)
        assert "kiwoom" in router._specs
        assert "ls" in router._specs


# ── _build ─────────────────────────────────────────────────────────────────────

class TestBuild:
    def test_build_creates_all_feature_providers(self):
        """_build → 모든 feature에 대해 provider 생성."""
        router, _ = _make_router()
        assert len(router._providers) == len(FEATURES)
        for feat in FEATURES:
            assert feat in router._providers
            assert feat in router._broker_map

    def test_build_provider_none_raises_value_error(self):
        """_create_provider가 None 반환 → ValueError 전파 (P20 폴백 금지).

        정상 경로에서는 _normalize_broker_config가 모든 feature를 채우므로
        None 반환은 불가능. 비정상 상태를 폴백으로 덮지 않고 에러 전파.
        """
        mock_provider = MagicMock()
        # 첫 호출은 None, 이후는 mock_provider
        side_effect = [None] + [mock_provider] * (len(FEATURES) * 2)
        settings = _mock_settings(broker="kiwoom")
        with (
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.core.broker_router._create_provider", side_effect=side_effect),
        ):
            mock_state.integrated_system_settings_cache = settings
            with pytest.raises(ValueError, match="지원하지 않는 증권사"):
                BrokerRouter()

    def test_build_broker_map_set_correctly(self):
        """_broker_map에 feature → broker_name 매핑이 설정됨."""
        settings = _mock_settings(broker="kiwoom")
        router, _ = _make_router(settings=settings)
        for feat in FEATURES:
            assert router._broker_map[feat] == "kiwoom"

    def test_build_with_broker_config_override(self):
        """broker_config에서 특정 feature의 broker를 다르게 설정."""
        settings = _mock_settings(
            broker="kiwoom",
            broker_config={"order": "ls"},
        )
        # _create_provider가 feature별로 다른 provider 반환
        providers = {feat: MagicMock() for feat in FEATURES}

        def side_effect(feat, bn, s, ac):
            return providers[feat]

        with (
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.core.broker_router._create_provider", side_effect=side_effect),
        ):
            mock_state.integrated_system_settings_cache = settings
            router = BrokerRouter()

        assert router._broker_map["order"] == "ls"
        assert router._broker_map["auth"] == "kiwoom"


# ── Property 접근자 ────────────────────────────────────────────────────────────

class TestProperties:
    def test_order_property(self):
        router, _ = _make_router()
        assert router.order is router._providers["order"]

    def test_auth_property(self):
        router, _ = _make_router()
        assert router.auth is router._providers["auth"]

    def test_websocket_property(self):
        router, _ = _make_router()
        assert router.websocket is router._providers["websocket"]


# ── validate ───────────────────────────────────────────────────────────────────

class TestValidate:
    def test_validate_no_api_key_returns_message(self):
        """API 키가 없으면 경고 메시지 반환."""
        settings = _mock_settings(app_key="", app_secret="")
        router, mock_state = _make_router(settings=settings)
        # validate 내부에서 state를 다시 import하므로 mock_state 유지
        with patch("backend.app.services.engine_state.state", mock_state):
            messages = router.validate()
        assert any("API 키" in m for m in messages)

    def test_validate_with_api_key_no_message(self):
        """API 키가 있으면 메시지 없음 (동일 증권사 쌍이므로)."""
        settings = _mock_settings(app_key="key", app_secret="secret")
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            messages = router.validate()
        assert len(messages) == 0

    def test_validate_returns_list(self):
        """validate는 항상 list를 반환함."""
        settings = _mock_settings()
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            result = router.validate()
        assert isinstance(result, list)


# ── summary ────────────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_format(self):
        """summary → '[증권사] 계좌=설정됨, 주문=설정됨, ...' 형식."""
        router, _ = _make_router()
        result = router.summary()
        assert result.startswith("[증권사] ")
        for feat in FEATURES:
            display = _FEATURE_DISPLAY[feat]
            assert f"{display}=설정됨" in result

    def test_summary_contains_all_features(self):
        """summary에 모든 feature의 한글 이름이 포함됨."""
        router, _ = _make_router()
        result = router.summary()
        for feat in FEATURES:
            assert _FEATURE_DISPLAY[feat] in result

    def test_summary_comma_separated(self):
        """summary는 쉼표로 구분됨."""
        router, _ = _make_router()
        result = router.summary()
        assert ", " in result


# ── PAGE_FEATURES 클래스 변수 ──────────────────────────────────────────────────

class TestPageFeatures:
    def test_page_features_contains_realtime_quote(self):
        assert "realtime_quote" in BrokerRouter.PAGE_FEATURES
        assert "websocket" in BrokerRouter.PAGE_FEATURES["realtime_quote"]

    def test_page_features_contains_trading(self):
        assert "trading" in BrokerRouter.PAGE_FEATURES
        assert "order" in BrokerRouter.PAGE_FEATURES["trading"]
