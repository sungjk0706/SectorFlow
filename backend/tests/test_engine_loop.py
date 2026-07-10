"""engine_loop.py 단위 테스트 — 엔진 asyncio 메인 루프 검증.

_cache_and_bootstrap / _get_all_tokens_async / _load_broker_spec_async /
run_engine_loop 동작 검증.
hang 방지: asyncio.create_task / asyncio.gather / asyncio.wait를 mock으로 대체,
engine_stop_event.is_set()을 True로 설정하여 while 루프 진입 차단.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services import engine_loop
from backend.app.core.broker_providers import AuthProvider


class _AwaitableMock(MagicMock):
    """MagicMock that supports `await` expression — __await__ returns empty iterator.

    asyncio.create_task의 반환값을 mock할 때 사용.
    finally 블록에서 `await compute_task`가 가능하도록 __await__ 구현.
    """
    def __await__(self):
        return iter([])


@pytest.fixture(autouse=True)
def _mock_pipeline_compute():
    """pipeline_compute 모듈 import 시 get_broadcast_queue() 실패 방지.

    pipeline_compute.py가 모듈 로드 시점에 get_broadcast_queue()를 호출하므로
    sys.modules에 mock 모듈을 주입하여 import 실패를 차단.
    """
    mock_mod = MagicMock()
    mock_mod.start_compute_loop = MagicMock()
    with patch.dict(sys.modules, {"backend.app.pipelines.pipeline_compute": mock_mod}):
        yield


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _mock_state(
    broker="kiwoom",
    broker_config=None,
    app_key="test_key",
    app_secret="test_secret",
    access_token=None,
    broker_tokens=None,
    broker_spec=None,
    confirmed_data_broker="",
):
    """engine_state.state mock 생성."""
    mock = MagicMock()
    bc = broker_config or {"websocket": broker}
    mock.integrated_system_settings_cache = {
        "broker": broker,
        "broker_config": bc,
        f"{broker}_app_key": app_key,
        f"{broker}_app_secret": app_secret,
        f"{broker}_account_no": "12345678",
        "confirmed_data_broker": confirmed_data_broker,
        "trade_mode": "test",
        "test_virtual_deposit": 10000000,
    }
    mock.broker_tokens = broker_tokens if broker_tokens is not None else {}
    mock.broker_spec = broker_spec if broker_spec is not None else []
    mock.broker_rest_apis = {}
    mock.master_stocks_cache = {}
    mock.access_token = access_token
    mock.login_ok = True
    mock.connector_manager = None
    mock.active_connector = None
    mock.running = False
    mock.auto_trade = None
    mock.preboot_cache_loaded = False

    # Events — MagicMock으로 대체 (LazyEvent 지연 초기화 우회)
    mock.token_ready_event = MagicMock()
    mock.preboot_ready_event = MagicMock()
    mock.engine_stop_event = MagicMock()
    mock.engine_stop_event.is_set.return_value = True  # while 루프 즉시 종료
    mock.ws_window_changed_event = MagicMock()
    mock.engine_loop_ref = None
    mock.account_rest_lock = None

    return mock


def _mock_router(with_rest_api=False):
    """BrokerRouter mock 생성.

    with_rest_api=False → auth에 rest_api 속성 없음 (REST API 경로 스킵).
    with_rest_api=True → auth.rest_api 반환 (TR ID 할당 테스트용).
    """
    router = MagicMock()
    router._auth_cache = {}
    if with_rest_api:
        mock_rest_api = MagicMock()
        mock_rest_api._acnt_no = ""
        mock_rest_api._deposit_tr_id = ""
        mock_rest_api._balance_tr_id = ""
        mock_rest_api._account_tr_id = ""
        # finally 블록에서 await 호출되는 메서드는 AsyncMock으로 설정
        mock_rest_api.revoke_token = AsyncMock()
        mock_rest_api._reset_client = AsyncMock()
        mock_auth = MagicMock()
        mock_auth.rest_api = mock_rest_api
        router.auth = mock_auth
    else:
        # spec=AuthProvider → hasattr(auth, 'rest_api') == False
        router.auth = MagicMock(spec=AuthProvider)
    return router


# ── _cache_and_bootstrap ───────────────────────────────────────────────────────

class TestCacheAndBootstrap:
    @pytest.mark.asyncio
    async def test_load_caches_preboot_called(self):
        """_cache_and_bootstrap → _load_caches_preboot 호출."""
        settings = {"trade_mode": "test"}
        with (
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock) as mock_load,
            patch("backend.app.web.ws_manager.ws_manager") as mock_ws,
        ):
            mock_ws.broadcast = AsyncMock()
            await engine_loop._cache_and_bootstrap(settings)

        mock_load.assert_awaited_once_with(settings)

    @pytest.mark.asyncio
    async def test_broadcast_engine_ready_success(self):
        """broadcast 성공 → info 로그."""
        settings = {"trade_mode": "test"}
        with (
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch("backend.app.web.ws_manager.ws_manager") as mock_ws,
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            mock_ws.broadcast = AsyncMock()
            await engine_loop._cache_and_bootstrap(settings)

        mock_ws.broadcast.assert_awaited_once_with("engine-ready", {"_v": 1, "ready": True})
        info_msgs = [str(c) for c in mock_logger.info.call_args_list]
        assert any("데이터 준비 완료" in m for m in info_msgs)

    @pytest.mark.asyncio
    async def test_broadcast_exception_handled(self):
        """broadcast 예외 → warning 로그, 계속 진행."""
        settings = {"trade_mode": "test"}
        with (
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch("backend.app.web.ws_manager.ws_manager") as mock_ws,
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            mock_ws.broadcast = AsyncMock(side_effect=Exception("WS error"))
            await engine_loop._cache_and_bootstrap(settings)

        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("브로드캐스트 실패" in m for m in warning_msgs)

    @pytest.mark.asyncio
    async def test_broadcast_payload_correct(self):
        """broadcast 페이로드가 정확한지 확인."""
        settings = {"trade_mode": "test"}
        with (
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch("backend.app.web.ws_manager.ws_manager") as mock_ws,
        ):
            mock_ws.broadcast = AsyncMock()
            await engine_loop._cache_and_bootstrap(settings)

        call_args = mock_ws.broadcast.call_args
        assert call_args.args[0] == "engine-ready"
        assert call_args.args[1] == {"_v": 1, "ready": True}


# ── _get_all_tokens_async ──────────────────────────────────────────────────────

class TestGetAllTokensAsync:
    @pytest.mark.asyncio
    async def test_no_valid_brokers_returns_early(self):
        """유효한 API 키가 없는 증권사만 있으면 early return."""
        mock_state = _mock_state(app_key="", app_secret="")
        router = MagicMock()
        router._auth_cache = {}

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock) as mock_gather,
        ):
            await engine_loop._get_all_tokens_async(router)

        mock_gather.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_success_stored_in_state(self):
        """토큰 발급 성공 → state.broker_tokens에 저장."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {}  # clear 가능한 dict

        auth_provider = MagicMock()
        auth_provider.get_access_token = AsyncMock(return_value="token_123")

        router = MagicMock()
        router._auth_cache = {"kiwoom": auth_provider}

        with (
            patch.object(engine_loop, "state", mock_state),
        ):
            # asyncio.gather가 실제로 실행되도록 create_task 없이 직접 호출
            await engine_loop._get_all_tokens_async(router)

        assert mock_state.broker_tokens.get("kiwoom") == "token_123"

    @pytest.mark.asyncio
    async def test_token_failure_returns_none(self):
        """토큰 발급 실패 → broker_tokens에 저장 안함."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {}

        auth_provider = MagicMock()
        auth_provider.get_access_token = AsyncMock(side_effect=Exception("Auth failed"))

        router = MagicMock()
        router._auth_cache = {"kiwoom": auth_provider}

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            await engine_loop._get_all_tokens_async(router)

        assert "kiwoom" not in mock_state.broker_tokens
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("토큰 발급 실패" in m for m in warning_msgs)

    @pytest.mark.asyncio
    async def test_auth_cache_miss_creates_provider(self):
        """auth_cache에 없는 증권사 → _create_provider로 생성."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {}

        new_auth_provider = MagicMock()
        new_auth_provider.get_access_token = AsyncMock(return_value="new_token")

        router = MagicMock()
        router._auth_cache = {}  # 빈 캐시

        with (
            patch.object(engine_loop, "state", mock_state),
            patch("backend.app.core.broker_registry._create_provider", return_value=new_auth_provider) as mock_cp,
        ):
            await engine_loop._get_all_tokens_async(router)

        mock_cp.assert_called_once()
        assert mock_state.broker_tokens.get("kiwoom") == "new_token"

    @pytest.mark.asyncio
    async def test_confirmed_data_broker_collected(self):
        """confirmed_data_broker도 토큰 발급 대상에 포함."""
        mock_state = _mock_state(confirmed_data_broker="ls")
        mock_state.integrated_system_settings_cache["ls_app_key"] = "ls_key"
        mock_state.integrated_system_settings_cache["ls_app_secret"] = "ls_secret"
        mock_state.broker_tokens = {}

        kiwoom_auth = MagicMock()
        kiwoom_auth.get_access_token = AsyncMock(return_value="kw_token")
        ls_auth = MagicMock()
        ls_auth.get_access_token = AsyncMock(return_value="ls_token")

        router = MagicMock()
        router._auth_cache = {"kiwoom": kiwoom_auth, "ls": ls_auth}

        with patch.object(engine_loop, "state", mock_state):
            await engine_loop._get_all_tokens_async(router)

        assert mock_state.broker_tokens.get("kiwoom") == "kw_token"
        assert mock_state.broker_tokens.get("ls") == "ls_token"

    @pytest.mark.asyncio
    async def test_broker_tokens_cleared_before_set(self):
        """기존 broker_tokens가 clear된 후 새 토큰 저장."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {"old_broker": "old_token"}

        auth_provider = MagicMock()
        auth_provider.get_access_token = AsyncMock(return_value="new_token")

        router = MagicMock()
        router._auth_cache = {"kiwoom": auth_provider}

        with patch.object(engine_loop, "state", mock_state):
            await engine_loop._get_all_tokens_async(router)

        assert "old_broker" not in mock_state.broker_tokens
        assert mock_state.broker_tokens.get("kiwoom") == "new_token"

    @pytest.mark.asyncio
    async def test_empty_broker_name_in_config_skipped(self):
        """broker_config에서 빈 문자열 증권사는 스킵됨."""
        mock_state = _mock_state(broker_config={"websocket": "", "order": "kiwoom"})
        mock_state.broker_tokens = {}

        auth_provider = MagicMock()
        auth_provider.get_access_token = AsyncMock(return_value="token")

        router = MagicMock()
        router._auth_cache = {"kiwoom": auth_provider}

        with patch.object(engine_loop, "state", mock_state):
            await engine_loop._get_all_tokens_async(router)

        # 빈 문자열은 수집되지 않음 — kiwoom만 토큰 발급
        assert mock_state.broker_tokens.get("kiwoom") == "token"


# ── _load_broker_spec_async ────────────────────────────────────────────────────

class TestLoadBrokerSpecAsync:
    @pytest.mark.asyncio
    async def test_valid_spec_returns_list(self):
        """정상 spec → role_mappings.values() 리스트 반환."""
        settings = {
            "_broker_specs": {
                "kiwoom": {"role_mappings": {"tr1": {"tr_id": "kt00001"}, "tr2": {"tr_id": "kt00018"}}},
            },
        }
        result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_broker_not_in_specs_returns_empty(self):
        """broker가 _broker_specs에 없으면 빈 리스트."""
        settings = {"_broker_specs": {}}
        result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_broker_specs_key_returns_empty(self):
        """_broker_specs 키 자체가 없으면 빈 리스트."""
        settings = {}
        result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert result == []

    @pytest.mark.asyncio
    async def test_spec_not_dict_returns_empty(self):
        """spec이 dict가 아닌 경우 → 빈 리스트 + 경고 로그."""
        settings = {"_broker_specs": {"kiwoom": "not_a_dict"}}
        with patch.object(engine_loop, "logger") as mock_logger:
            result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert result == []
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("broker_specs 형식 오류" in m for m in warning_msgs)

    @pytest.mark.asyncio
    async def test_role_mappings_not_dict_returns_empty(self):
        """role_mappings가 dict가 아닌 경우 → 빈 리스트 + 경고 로그."""
        settings = {"_broker_specs": {"kiwoom": {"role_mappings": "not_a_dict"}}}
        with patch.object(engine_loop, "logger") as mock_logger:
            result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert result == []
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("role_mappings 형식 오류" in m for m in warning_msgs)

    @pytest.mark.asyncio
    async def test_empty_role_mappings_returns_empty_list(self):
        """role_mappings가 빈 dict → 빈 리스트."""
        settings = {"_broker_specs": {"kiwoom": {"role_mappings": {}}}}
        result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        """예외 발생 → 빈 리스트 + 경고 로그."""
        # settings.get이 예외를 발생시키도록 MagicMock 사용
        settings = MagicMock()
        settings.get.side_effect = RuntimeError("unexpected")
        with patch.object(engine_loop, "logger") as mock_logger:
            result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert result == []
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("스펙 로드 실패" in m for m in warning_msgs)

    @pytest.mark.asyncio
    async def test_role_mappings_missing_key_returns_empty(self):
        """spec dict에 role_mappings 키가 없으면 빈 dict로 처리 → 빈 리스트."""
        settings = {"_broker_specs": {"kiwoom": {"other_key": "value"}}}
        result = await engine_loop._load_broker_spec_async("kiwoom", settings)
        assert result == []


# ── run_engine_loop — 초기화 및 정리 ───────────────────────────────────────────

class TestRunEngineLoopInit:
    @pytest.mark.asyncio
    async def test_state_initialized(self):
        """run_engine_loop → state 초기화 (login_ok, running, etc.)."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True  # 루프 즉시 종료

        mock_router = _mock_router()
        # rest_api 속성 없음 → hasattr False

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack") as mock_notify,
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "AutoTradeManager") as mock_atm,
        ):
            mock_state.access_token = None  # AutoTradeManager 생성 경로 우회
            await engine_loop.run_engine_loop()

        assert mock_state.login_ok is False
        assert mock_state.running is False  # finally에서 False 설정
        assert mock_state.connector_manager is None
        assert mock_state.account_rest_lock is None

    @pytest.mark.asyncio
    async def test_preboot_ready_event_set(self):
        """run_engine_loop → preboot_ready_event.set() 호출."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        mock_state.preboot_ready_event.set.assert_called()

    @pytest.mark.asyncio
    async def test_token_ready_event_set_after_gather(self):
        """gather 완료 후 token_ready_event.set() 호출."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock) as mock_gather,
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        mock_gather.assert_awaited_once()
        mock_state.token_ready_event.set.assert_called()

    @pytest.mark.asyncio
    async def test_no_valid_brokers_logs_warning(self):
        """유효한 API 키가 없으면 경고 로그 + broadcast_engine_status 호출."""
        mock_state = _mock_state(app_key="", app_secret="")
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message") as mock_log,
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock) as mock_bes,
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        log_msgs = [str(c) for c in mock_log.call_args_list]
        assert any("유효한 API 키가 없습니다" in m for m in log_msgs)
        # broadcast_engine_status가 "유효한 API 키 없음" 경로에서 호출됨
        assert mock_bes.await_count >= 2  # 경고 경로 1회 + finally 1회

    @pytest.mark.asyncio
    async def test_token_success_sets_access_token(self):
        """토큰 발급 성공 → state.access_token 설정."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {"kiwoom": "valid_token"}
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        # _get_all_tokens_async가 호출 시 broker_tokens에 토큰 설정 (clear 후 복원)
        async def _set_token(router):
            mock_state.broker_tokens["kiwoom"] = "valid_token"

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", side_effect=_set_token),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "AutoTradeManager"),
        ):
            await engine_loop.run_engine_loop()

        assert mock_state.access_token == "valid_token"

    @pytest.mark.asyncio
    async def test_token_failure_sets_access_token_none(self):
        """토큰 발급 실패 → state.access_token = None + 스냅샷 전용 모드 로그."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {}  # 토큰 없음
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message") as mock_log,
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            await engine_loop.run_engine_loop()

        assert mock_state.access_token is None
        log_msgs = [str(c) for c in mock_log.call_args_list]
        assert any("스냅샷 전용 모드" in m for m in log_msgs)

    @pytest.mark.asyncio
    async def test_finally_clears_broker_rest_apis(self):
        """finally → broker_rest_apis.clear() + broker_tokens.clear() 호출."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_rest_api = MagicMock()
        mock_rest_api.revoke_token = AsyncMock()
        mock_rest_api._reset_client = AsyncMock()
        mock_state.broker_rest_apis = {"kiwoom": mock_rest_api}

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        mock_rest_api.revoke_token.assert_awaited_once()
        assert len(mock_state.broker_rest_apis) == 0

    @pytest.mark.asyncio
    async def test_finally_running_set_false(self):
        """finally → state.running = False."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        assert mock_state.running is False

    @pytest.mark.asyncio
    async def test_cancelled_error_handled(self):
        """asyncio.CancelledError → 조용히 처리 (pass)."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            # CancelledError는 except에서 pass 처리됨 → finally 실행
            await engine_loop.run_engine_loop()

        # finally에서 running = False 설정됨
        assert mock_state.running is False

    @pytest.mark.asyncio
    async def test_general_exception_handled(self):
        """일반 예외 → log_message + warning 로그."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock, side_effect=RuntimeError("unexpected")),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message") as mock_log,
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            await engine_loop.run_engine_loop()

        log_msgs = [str(c) for c in mock_log.call_args_list]
        assert any("예외" in m for m in log_msgs)
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("엔진 루프 예외" in m for m in warning_msgs)


# ── run_engine_loop — REST API / spec 처리 ─────────────────────────────────────

class TestRunEngineLoopRestApi:
    @pytest.mark.asyncio
    async def test_rest_api_tr_ids_assigned(self):
        """broker_spec의 tr_id에 따라 REST API에 TR ID 할당."""
        mock_state = _mock_state()
        mock_state.broker_spec = [
            {"tr_id": "kt00001"},
            {"tr_id": "kt00018"},
            {"tr_id": "ka00001"},
        ]
        _spec_list = mock_state.broker_spec
        mock_state.broker_tokens = {"kiwoom": "valid_token"}
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router(with_rest_api=True)

        async def _set_token(router):
            mock_state.broker_tokens["kiwoom"] = "valid_token"

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", side_effect=_set_token),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=_spec_list),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "AutoTradeManager"),
        ):
            await engine_loop.run_engine_loop()

        mock_rest_api = mock_router.auth.rest_api
        assert mock_rest_api._deposit_tr_id == "kt00001"
        assert mock_rest_api._balance_tr_id == "kt00018"
        assert mock_rest_api._account_tr_id == "ka00001"
        # broker_rest_apis는 finally에서 clear()되므로 TR ID 할당만 검증

    @pytest.mark.asyncio
    async def test_auto_trade_created_with_token(self):
        """access_token이 있으면 AutoTradeManager 생성됨."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {"kiwoom": "valid_token"}
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()  # rest_api 없음

        async def _set_token(router):
            mock_state.broker_tokens["kiwoom"] = "valid_token"

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", side_effect=_set_token),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides") as mock_sync,
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "AutoTradeManager") as mock_atm_cls,
        ):
            await engine_loop.run_engine_loop()

        mock_atm_cls.assert_called_once()
        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_auto_trade_without_token(self):
        """access_token이 없으면 AutoTradeManager 생성 안함."""
        mock_state = _mock_state()
        mock_state.broker_tokens = {}
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides") as mock_sync,
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "AutoTradeManager") as mock_atm_cls,
        ):
            await engine_loop.run_engine_loop()

        mock_atm_cls.assert_not_called()
        mock_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_buy_limit_status_called(self):
        """_broadcast_buy_limit_status 호출됨."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock) as mock_bbl,
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        mock_bbl.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broadcast_buy_limit_exception_handled(self):
        """_broadcast_buy_limit_status 예외 → warning 로그."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock, side_effect=Exception("broadcast fail")),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("매수 한도 브로드캐스트 실패" in m for m in warning_msgs)


# ── run_engine_loop — 계좌번호 마스킹 ──────────────────────────────────────────

class TestRunEngineLoopAccountMasking:
    @pytest.mark.asyncio
    async def test_account_number_masked_in_log(self):
        """계좌번호가 4자리 이상이면 마스킹됨 (앞 4자리 + ****)."""
        mock_state = _mock_state()
        mock_state.integrated_system_settings_cache["kiwoom_account_no"] = "12345678"
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        info_msgs = [str(c) for c in mock_logger.info.call_args_list]
        assert any("1234****" in m for m in info_msgs)

    @pytest.mark.asyncio
    async def test_short_account_number_not_masked(self):
        """계좌번호가 4자리 미만이면 마스킹 안함."""
        mock_state = _mock_state()
        mock_state.integrated_system_settings_cache["kiwoom_account_no"] = "123"
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=True),
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        info_msgs = [str(c) for c in mock_logger.info.call_args_list]
        assert any("123" in m and "****" not in m.split("계좌:")[1] for m in info_msgs if "계좌:" in m)

    @pytest.mark.asyncio
    async def test_real_mode_warning_in_log(self):
        """실전모드 → '★ 실제 자금 투입 ★' 경고 포함."""
        mock_state = _mock_state()
        mock_state.engine_stop_event.is_set.return_value = True

        mock_router = _mock_router()

        with (
            patch.object(engine_loop, "state", mock_state),
            patch.object(engine_loop, "get_router", return_value=mock_router),
            patch.object(engine_loop, "is_test_mode", return_value=False),  # 실전모드
            patch.object(engine_loop, "_load_caches_preboot", new_callable=AsyncMock),
            patch.object(engine_loop, "_get_all_tokens_async", new_callable=AsyncMock),
            patch.object(engine_loop, "_load_broker_spec_async", new_callable=AsyncMock, return_value=[]),
            patch.object(engine_loop.asyncio, "gather", new_callable=AsyncMock),
            patch.object(engine_loop.asyncio, "create_task", return_value=_AwaitableMock()),
            patch("backend.app.services.engine_state._notify_reg_ack"),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_lifecycle.log_message"),
            patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_lifecycle.sync_sell_overrides"),
            patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock),
            patch("backend.app.services.engine_config._get_settings"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock),
            patch.object(engine_loop, "logger") as mock_logger,
        ):
            mock_state.access_token = None
            await engine_loop.run_engine_loop()

        info_msgs = [str(c) for c in mock_logger.info.call_args_list]
        assert any("실제 자금 투입" in m for m in info_msgs)
