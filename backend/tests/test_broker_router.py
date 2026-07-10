"""broker_router.py 단위 테스트 — BrokerRouter 기능별 Provider 매핑 라우터 검증.

_load_specs / _build / properties / validate / summary / get_provider /
invalidate_page / validate_page_overrides / get_spec 동작 검증.
의존성: _create_provider, PROVIDER_REGISTRY, state.integrated_system_settings_cache를 mock으로 대체.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
    """테스트용 integrated_system_settings_cache dict 생성."""
    bc = broker_config or {}
    settings = {
        "broker": broker,
        "broker_config": bc,
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
        assert any("spec 없음" in m for m in warning_msgs)

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
            broker_config={"account": "ls"},
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

    def test_build_provider_none_falls_back_to_default(self):
        """_create_provider가 None 반환 → 기본 broker로 폴백."""
        mock_provider = MagicMock()
        # 첫 호출은 None, 이후는 mock_provider
        side_effect = [None] + [mock_provider] * (len(FEATURES) * 2)
        settings = _mock_settings(broker="kiwoom")
        with (
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.core.broker_router._create_provider", side_effect=side_effect) as mock_cp,
            patch("backend.app.core.broker_router.logger") as mock_logger,
        ):
            mock_state.integrated_system_settings_cache = settings
            router = BrokerRouter()

        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("폴백" in m for m in warning_msgs)

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
            broker_config={"account": "ls"},
        )
        # _create_provider가 feature별로 다른 provider 반환
        providers = {feat: MagicMock() for feat in FEATURES}
        side_effect = lambda feat, bn, s, ac: providers[feat]

        with (
            patch("backend.app.services.engine_state.state") as mock_state,
            patch("backend.app.core.broker_router._create_provider", side_effect=side_effect),
        ):
            mock_state.integrated_system_settings_cache = settings
            router = BrokerRouter()

        assert router._broker_map["account"] == "ls"
        assert router._broker_map["order"] == "kiwoom"


# ── Property 접근자 ────────────────────────────────────────────────────────────

class TestProperties:
    def test_account_property(self):
        router, _ = _make_router()
        assert router.account is router._providers["account"]

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

    def test_validate_order_account_different_brokers(self):
        """order와 account가 다른 증권사면 경고 메시지."""
        settings = _mock_settings(
            broker="kiwoom",
            broker_config={"account": "ls"},
            app_key="key",
            app_secret="secret",
        )
        # ls의 API 키도 추가
        settings["ls_app_key"] = "ls_key"
        settings["ls_app_secret"] = "ls_secret"

        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            messages = router.validate()
        assert any("동일 증권사" in m for m in messages)

    def test_validate_order_account_same_broker_no_message(self):
        """order와 account가 같은 증권사면 메시지 없음."""
        settings = _mock_settings(app_key="key", app_secret="secret")
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            messages = router.validate()
        assert not any("동일 증권사" in m for m in messages)

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


# ── get_provider ───────────────────────────────────────────────────────────────

class TestGetProvider:
    def test_get_provider_no_page_returns_global(self):
        """page=None → 전역 provider 반환."""
        router, _ = _make_router()
        result = router.get_provider("order")
        assert result is router._providers["order"]

    def test_get_provider_no_override_returns_global(self):
        """page_overrides에 해당 feature 없으면 전역 provider 반환."""
        settings = _mock_settings(page_overrides={})
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            result = router.get_provider("order", page="trading")
        assert result is router._providers["order"]

    def test_get_provider_same_broker_returns_global(self):
        """page_overrides의 broker가 전역과 동일하면 전역 provider 반환."""
        settings = _mock_settings(
            broker="kiwoom",
            page_overrides={"trading": {"order": "kiwoom"}},
        )
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            result = router.get_provider("order", page="trading")
        assert result is router._providers["order"]

    def test_get_provider_different_broker_creates_new(self):
        """page_overrides의 broker가 다르면 새 provider 생성."""
        settings = _mock_settings(
            broker="kiwoom",
            page_overrides={"trading": {"order": "ls"}},
        )
        settings["ls_app_key"] = "ls_key"
        settings["ls_app_secret"] = "ls_secret"

        mock_new_provider = MagicMock()
        router, mock_state = _make_router(settings=settings)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_router._create_provider", return_value=mock_new_provider) as mock_cp,
        ):
            result = router.get_provider("order", page="trading")

        assert result is mock_new_provider
        mock_cp.assert_called_once()

    def test_get_provider_cached(self):
        """동일 (page, feature) 쌍은 캐시에서 반환."""
        settings = _mock_settings(
            broker="kiwoom",
            page_overrides={"trading": {"order": "ls"}},
        )
        settings["ls_app_key"] = "ls_key"
        settings["ls_app_secret"] = "ls_secret"

        mock_new_provider = MagicMock()
        router, mock_state = _make_router(settings=settings)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_router._create_provider", return_value=mock_new_provider) as mock_cp,
        ):
            result1 = router.get_provider("order", page="trading")
            result2 = router.get_provider("order", page="trading")

        assert result1 is result2
        mock_cp.assert_called_once()  # _create_provider는 1회만 호출

    def test_get_provider_value_error_falls_back(self):
        """_create_provider가 ValueError → 전역 provider 폴백."""
        settings = _mock_settings(
            broker="kiwoom",
            page_overrides={"trading": {"order": "ls"}},
        )
        settings["ls_app_key"] = "ls_key"
        settings["ls_app_secret"] = "ls_secret"

        router, mock_state = _make_router(settings=settings)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_router._create_provider", side_effect=ValueError("unsupported")),
            patch("backend.app.core.broker_router.logger") as mock_logger,
        ):
            result = router.get_provider("order", page="trading")

        assert result is router._providers["order"]
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("폴백" in m for m in warning_msgs)

    def test_get_provider_empty_page_config_returns_global(self):
        """page_overrides에 page가 있지만 config가 빈 dict → 전역 provider."""
        settings = _mock_settings(page_overrides={"trading": {}})
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            result = router.get_provider("order", page="trading")
        assert result is router._providers["order"]


# ── invalidate_page ─────────────────────────────────────────────────────────────

class TestInvalidatePage:
    def test_invalidate_specific_page(self):
        """특정 페이지의 캐시만 무효화."""
        router, _ = _make_router()
        router._page_providers[("trading", "order")] = MagicMock()
        router._page_providers[("account", "auth")] = MagicMock()

        router.invalidate_page("trading")

        assert ("trading", "order") not in router._page_providers
        assert ("account", "auth") in router._page_providers

    def test_invalidate_all_pages(self):
        """page=None → 전체 무효화."""
        router, _ = _make_router()
        router._page_providers[("trading", "order")] = MagicMock()
        router._page_providers[("account", "auth")] = MagicMock()

        router.invalidate_page(None)

        assert len(router._page_providers) == 0

    def test_invalidate_nonexistent_page_no_error(self):
        """존재하지 않는 페이지 무효화 → 에러 없음."""
        router, _ = _make_router()
        router.invalidate_page("nonexistent")
        # no exception

    def test_invalidate_empty_cache_no_error(self):
        """빈 캐시 무효화 → 에러 없음."""
        router, _ = _make_router()
        router.invalidate_page(None)
        # no exception


# ── validate_page_overrides ─────────────────────────────────────────────────────

class TestValidatePageOverrides:
    def test_no_page_overrides_returns_empty(self):
        """page_overrides 없음 → 빈 리스트."""
        settings = _mock_settings()
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            messages = router.validate_page_overrides()
        assert messages == []

    def test_unsupported_page_skipped(self):
        """PAGE_FEATURES에 없는 페이지는 스킵됨."""
        settings = _mock_settings(page_overrides={"unknown_page": {"order": "kiwoom"}})
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            messages = router.validate_page_overrides()
        assert messages == []

    def test_non_dict_config_skipped(self):
        """config가 dict가 아닌 경우 스킵됨."""
        settings = _mock_settings(page_overrides={"trading": "not_a_dict"})
        router, mock_state = _make_router(settings=settings)
        with patch("backend.app.services.engine_state.state", mock_state):
            messages = router.validate_page_overrides()
        assert messages == []

    def test_feature_not_in_allowed_skipped(self):
        """페이지의 허용 기능이 아닌 feature는 스킵됨."""
        # trading 페이지는 ("order",)만 허용 — "auth"는 스킵
        settings = _mock_settings(page_overrides={"trading": {"auth": "kiwoom"}})
        router, mock_state = _make_router(settings=settings)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_router.PROVIDER_REGISTRY", {"kiwoom": {"auth": MagicMock}}),
        ):
            messages = router.validate_page_overrides()
        assert messages == []

    def test_unsupported_broker_feature_returns_message(self):
        """브로커가 해당 기능을 지원하지 않으면 메시지 반환."""
        settings = _mock_settings(page_overrides={"trading": {"order": "kiwoom"}})
        router, mock_state = _make_router(settings=settings)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_router.PROVIDER_REGISTRY", {"kiwoom": {}}),  # order 없음
        ):
            messages = router.validate_page_overrides()
        assert any("지원하지 않습니다" in m for m in messages)

    def test_no_api_key_returns_message(self):
        """API 키가 없으면 메시지 반환."""
        settings = _mock_settings(
            broker="kiwoom",
            app_key="",
            app_secret="",
            page_overrides={"trading": {"order": "kiwoom"}},
        )
        router, mock_state = _make_router(settings=settings)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_router.PROVIDER_REGISTRY", {"kiwoom": {"order": MagicMock}}),
        ):
            messages = router.validate_page_overrides()
        assert any("API 키" in m for m in messages)

    def test_valid_override_no_message(self):
        """정상적인 override → 메시지 없음."""
        settings = _mock_settings(
            broker="kiwoom",
            page_overrides={"trading": {"order": "kiwoom"}},
        )
        router, mock_state = _make_router(settings=settings)
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_router.PROVIDER_REGISTRY", {"kiwoom": {"order": MagicMock}}),
        ):
            messages = router.validate_page_overrides()
        assert messages == []


# ── get_spec ───────────────────────────────────────────────────────────────────

class TestGetSpec:
    def test_get_spec_with_feature(self):
        """feature 지정 → 해당 feature의 broker에서 spec 조회."""
        specs = {"kiwoom": {"role_mappings": {"tr_deposit": "KT00001"}}}
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        result = router.get_spec("tr_deposit", feature="account")
        assert result == "KT00001"

    def test_get_spec_without_feature(self):
        """feature 미지정 → _broker_map의 첫 번째 broker 사용."""
        specs = {"kiwoom": {"role_mappings": {"tr_balance": "KT00018"}}}
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        result = router.get_spec("tr_balance")
        assert result == "KT00018"

    def test_get_spec_not_found_returns_none(self):
        """존재하지 않는 role_key → None."""
        specs = {"kiwoom": {"role_mappings": {"tr_deposit": "KT00001"}}}
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        result = router.get_spec("nonexistent_key", feature="account")
        assert result is None

    def test_get_spec_empty_broker_map_returns_none(self):
        """_broker_map이 비어있으면 None."""
        specs = {"kiwoom": {"role_mappings": {"tr_deposit": "KT00001"}}}
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        router._broker_map = {}
        result = router.get_spec("tr_deposit")
        assert result is None

    def test_get_spec_no_specs_for_broker_returns_none(self):
        """해당 broker의 spec이 없으면 None."""
        settings = _mock_settings(preloaded_specs={})
        router, _ = _make_router(settings=settings)
        result = router.get_spec("tr_deposit", feature="account")
        assert result is None

    def test_get_spec_value_is_none_returns_none(self):
        """role_mappings에서 값이 None이면 None 반환."""
        specs = {"kiwoom": {"role_mappings": {"tr_deposit": None}}}
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        result = router.get_spec("tr_deposit", feature="account")
        assert result is None

    def test_get_spec_value_converted_to_str(self):
        """spec 값이 int 등이면 str로 변환 반환."""
        specs = {"kiwoom": {"role_mappings": {"tr_deposit": 12345}}}
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        result = router.get_spec("tr_deposit", feature="account")
        assert result == "12345"
        assert isinstance(result, str)

    def test_get_spec_feature_not_in_broker_map(self):
        """feature가 _broker_map에 없으면 첫 번째 broker 사용."""
        specs = {"kiwoom": {"role_mappings": {"tr_deposit": "KT00001"}}}
        settings = _mock_settings(preloaded_specs=specs)
        router, _ = _make_router(settings=settings)
        result = router.get_spec("tr_deposit", feature="nonexistent_feature")
        # _broker_map의 첫 번째 broker 사용
        assert result == "KT00001"


# ── PAGE_FEATURES 클래스 변수 ──────────────────────────────────────────────────

class TestPageFeatures:
    def test_page_features_contains_realtime_quote(self):
        assert "realtime_quote" in BrokerRouter.PAGE_FEATURES
        assert "websocket" in BrokerRouter.PAGE_FEATURES["realtime_quote"]

    def test_page_features_contains_trading(self):
        assert "trading" in BrokerRouter.PAGE_FEATURES
        assert "order" in BrokerRouter.PAGE_FEATURES["trading"]

    def test_page_features_contains_account(self):
        assert "account" in BrokerRouter.PAGE_FEATURES
        assert "account" in BrokerRouter.PAGE_FEATURES["account"]
        assert "auth" in BrokerRouter.PAGE_FEATURES["account"]
