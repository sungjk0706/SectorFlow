"""engine_cache.py 단위 테스트 — _load_caches_preboot 캐시 선행 로드 검증.

DB 로드 → 업종 레이아웃 구성 → 5일 메트릭 연산 → WS 구간 분기 → 기동 완료 플래그 설정 검증.
hang 방지: asyncio.create_task를 mock으로 대체, 모든 async 의존성은 AsyncMock 처리.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services import engine_state


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_snapshot(num=5, with_high=True):
    """테스트용 master_stocks_table snapshot dict 생성."""
    snap = {}
    for i in range(num):
        code = f"00000{i}"
        snap[code] = {
            "sector": f"sector_{i % 2}",
            "avg_5d_trade_amount": 10000 * (i + 1),
            "high_5d_price": 50000 + i * 1000 if with_high else 0,
            "nxt_enable": i % 2 == 0,
        }
    return snap


def _make_settings(trade_mode="test", layout=None, virtual_deposit=10000000):
    """테스트용 settings dict 생성."""
    return {
        "trade_mode": trade_mode,
        "test_virtual_deposit": virtual_deposit,
        "sector_stock_layout": layout or [],
    }


def _apply_mocks(mock_state, settings=None, snapshot=None):
    """mock_state에 필요한 속성 설정."""
    mock_state.integrated_system_settings_cache = settings or _make_settings()
    mock_state.master_stocks_cache = {}
    mock_state.preboot_cache_loaded = False
    mock_state.bootstrap_event = MagicMock()
    mock_state.data_ready_event = MagicMock()
    mock_state.sector_summary_ready_event = MagicMock()
    # master_stocks_cache를 snapshot으로 사전 설정이 필요한 경우
    if snapshot is not None:
        mock_state.master_stocks_cache = snapshot


# ── _load_caches_preboot — 빈 snapshot / 예외 (B4-06-03: 치명 오류 전파) ──────────

class TestLoadCachesPrebootEmptyAndError:
    @pytest.mark.asyncio
    async def test_empty_snapshot_raises_runtime_error_propagated(self):
        """빈 snapshot → RuntimeError → log-and-rethrow (P20 폴백 금지, B4-06-03).

        치명 오류를 "무시하고 진행"하지 않고 호출자로 전파 — engine_loop.py에서
        "감소 모드로 기동" 에러 로그 + engine-ready 화면 전송 처리.
        """
        from backend.app.services import engine_cache

        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value={}),
            patch.object(engine_cache, "logger") as mock_logger,
        ):
            with pytest.raises(RuntimeError, match="master_stocks_table"):
                await engine_cache._load_caches_preboot(_make_settings())

        # error 로그로 치명 오류 기록 (warning 아님, P20)
        mock_logger.error.assert_called()
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_master_stocks_table_exception_propagated(self):
        """load_master_stocks_table 예외 → log-and-rethrow (P20 폴백 금지, B4-06-03)."""
        from backend.app.services import engine_cache

        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, side_effect=Exception("DB error")),
            patch.object(engine_cache, "logger") as mock_logger,
        ):
            with pytest.raises(Exception, match="DB error"):
                await engine_cache._load_caches_preboot(_make_settings())

        mock_logger.error.assert_called()
        mock_logger.warning.assert_not_called()


# ── _load_caches_preboot — 정상 로드 ───────────────────────────────────────────

class TestLoadCachesPrebootNormal:
    @pytest.mark.asyncio
    async def test_master_stocks_cache_set(self):
        """정상 snapshot → state.master_stocks_cache 설정."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task") as mock_create_task,
        ):
            mock_task = MagicMock()
            mock_task.add_done_callback = MagicMock()
            mock_create_task.return_value = mock_task

            await engine_cache._load_caches_preboot(_make_settings())

        assert mock_state.master_stocks_cache == snap

    @pytest.mark.asyncio
    async def test_preboot_cache_loaded_set_true(self):
        """정상 로드 → state.preboot_cache_loaded = True."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        assert mock_state.preboot_cache_loaded is True

    @pytest.mark.asyncio
    async def test_bootstrap_and_data_ready_events_set(self):
        """정상 로드 → bootstrap_event.set() + data_ready_event.set() 호출."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        mock_state.bootstrap_event.set.assert_called_once()
        mock_state.data_ready_event.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_rebuild_layout_cache_called(self):
        """정상 로드 → _rebuild_layout_cache 호출."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache") as mock_rebuild,
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        mock_rebuild.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_cache_prev_scores_reset(self):
        """정상 로드 → notify_cache.prev_scores = [] 설정."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        mock_notify = MagicMock()
        mock_notify.prev_scores = ["old_score"]
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache", mock_notify),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        assert mock_notify.prev_scores == []

    @pytest.mark.asyncio
    async def test_high_5d_price_reflected_in_master_cache(self):
        """정상 로드 → high_5d_price가 master_stocks_cache에 반영."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3, with_high=True)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        # master_stocks_cache에 high_5d_price가 설정됨 (load_master_stocks_table 반환값이 곧 cache)
        for code, detail in snap.items():
            if detail["high_5d_price"] > 0:
                assert mock_state.master_stocks_cache[code]["high_5d_price"] == detail["high_5d_price"]

    @pytest.mark.asyncio
    async def test_sector_layout_auto_configured(self):
        """정상 로드 → sector_stock_layout이 자동 구성됨."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(4)  # sector_0, sector_1, sector_0, sector_1
        mock_state = MagicMock()
        settings = _make_settings(layout=[("sector", "old_sector")])
        _apply_mocks(mock_state, settings=settings)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(settings)

        layout = mock_state.integrated_system_settings_cache["sector_stock_layout"]
        # auto_layout에 code 엔트리가 포함되어 있어야 함
        code_entries = [v for t, v in layout if t == "code"]
        assert len(code_entries) == 4
        # sector 엔트리도 포함
        sector_entries = [v for t, v in layout if t == "sector"]
        assert set(sector_entries) == {"sector_0", "sector_1"}


# ── _load_caches_preboot — WS 구간 분기 ────────────────────────────────────────

class TestLoadCachesPrebootWsWindow:
    @pytest.mark.asyncio
    async def test_ws_window_true_resets_realtime_fields(self):
        """WS 구간 True → _reset_realtime_fields 호출 + sector_summary_ready_event.set()."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True),
            patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock) as mock_reset,
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        mock_reset.assert_awaited_once()
        mock_state.sector_summary_ready_event.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_ws_window_false_creates_recompute_task(self):
        """WS 구간 False → recompute_sector_summary_now 태스크 생성."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task") as mock_create_task,
        ):
            mock_task = MagicMock()
            mock_task.add_done_callback = MagicMock()
            mock_create_task.return_value = mock_task

            await engine_cache._load_caches_preboot(_make_settings())

        # recompute_sector_summary_now 태스크와 catchup 태스크 — 최소 2회 create_task 호출
        assert mock_create_task.call_count >= 2
        # sector_summary_ready_event는 set되지 않음 (post-login에서 수행)
        mock_state.sector_summary_ready_event.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_ws_window_true_no_recompute_task(self):
        """WS 구간 True → recompute_sector_summary_now 태스크 생성 안함."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=True),
            patch("backend.app.services.engine_snapshot._reset_realtime_fields", new_callable=AsyncMock),
            patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute,
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        mock_recompute.assert_not_called()


# ── _load_caches_preboot — 테스트모드 분기 ─────────────────────────────────────

class TestLoadCachesPrebootTradeMode:
    @pytest.mark.asyncio
    async def test_test_mode_loads_settlement_state(self):
        """테스트모드 → settlement_engine.load_state 호출."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        settings = _make_settings(trade_mode="test", virtual_deposit=50000000)
        _apply_mocks(mock_state, settings=settings)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.settlement_engine.load_state", new_callable=AsyncMock) as mock_load_state,
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(settings)

        mock_load_state.assert_awaited_once_with(initial_deposit=50000000)

    @pytest.mark.asyncio
    async def test_real_mode_skips_settlement_state(self):
        """실전모드 → settlement_engine.load_state 미호출."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        settings = _make_settings(trade_mode="real")
        _apply_mocks(mock_state, settings=settings)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.settlement_engine.load_state", new_callable=AsyncMock) as mock_load_state,
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(settings)

        mock_load_state.assert_not_called()


# ── _load_caches_preboot — 5일평균/시장구분 ─────────────────────────────────────

class TestLoadCachesPrebootMetrics:
    @pytest.mark.asyncio
    async def test_avg_5d_below_100_warns(self):
        """5일평균 > 0 종목이 100개 미만 → warning 로그."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(50)  # 50종목 — 100 미만
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
            patch.object(engine_cache, "logger") as mock_logger,
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("비정상" in m for m in warning_msgs)

    @pytest.mark.asyncio
    async def test_nxt_enable_counted(self):
        """nxt_enable True인 종목 수가 로그에 포함됨."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(4)  # 0,2 → nxt_enable True (2종목)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
            patch.object(engine_cache, "logger") as mock_logger,
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("NXT" in m for m in debug_msgs)

    @pytest.mark.asyncio
    async def test_high_5d_zero_not_reflected(self):
        """high_5d_price == 0 → master_stocks_cache에 반영 안함."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3, with_high=False)  # 모든 high_5d = 0
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        # high_5d_price가 0이므로 cache에 추가 설정되지 않음 (원본에 없음)
        for code in snap:
            assert "high_5d_price" not in mock_state.master_stocks_cache[code] or \
                   mock_state.master_stocks_cache[code].get("high_5d_price") == 0


# ── _load_caches_preboot — catchup 태스크 ──────────────────────────────────────

class TestLoadCachesPrebootCatchup:
    @pytest.mark.asyncio
    async def test_catchup_task_created(self):
        """retry_pipeline_catchup_after_bootstrap 태스크 생성."""
        from backend.app.services import engine_cache

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", new_callable=AsyncMock) as mock_catchup,
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        mock_catchup.assert_called_once()

    @pytest.mark.asyncio
    async def test_catchup_exception_handled(self):
        """retry_pipeline_catchup_after_bootstrap 호출 실패 → warning 로그.

        patch를 호출 시 ImportError를 발생시키는 함수로 교체 → except 블록에서 처리.
        """
        from backend.app.services import engine_cache

        def _raise_import_error(*args, **kwargs):
            raise ImportError("missing")

        snap = _make_snapshot(3)
        mock_state = MagicMock()
        _apply_mocks(mock_state)
        with (
            patch.object(engine_state, "state", mock_state),
            patch("backend.app.db.stock_tables.load_master_stocks_table", new_callable=AsyncMock, return_value=snap),
            patch("backend.app.services.engine_account_notify._rebuild_layout_cache"),
            patch("backend.app.services.engine_account_notify.notify_cache"),
            patch("backend.app.services.daily_time_scheduler.is_ws_subscribe_window", new_callable=AsyncMock, return_value=False),
            patch("backend.app.services.daily_time_scheduler.retry_pipeline_catchup_after_bootstrap", _raise_import_error),
            patch.object(engine_cache.asyncio, "create_task", return_value=MagicMock(add_done_callback=MagicMock())),
            patch.object(engine_cache, "logger") as mock_logger,
        ):
            await engine_cache._load_caches_preboot(_make_settings())

        # catchup 실패는 내부 try/except에서 처리됨 — warning 로그
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("재시도" in m for m in warning_msgs)
