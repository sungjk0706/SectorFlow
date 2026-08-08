"""market_close_pipeline.py 단위 테스트 — 장마감 후 확정 데이터 파이프라인.

hang 방지 원칙:
- DB 연결(get_db_connection, get_db_lock)을 AsyncMock으로 대체
- asyncio.sleep을 patch하여 실제 대기 방지
- broadcast_engine_status, schedule_engine_task 등 백그라운드 호출 mock
- state 객체를 MagicMock으로 대체
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core.broker_providers import UnifiedStockRecord
from backend.app.core.stock_filter import StockFilterEvaluation
from backend.app.services.market_close_pipeline import (
    _broadcast_confirmed_progress,
    _get_krx_only_codes,
    remove_krx_only_stocks,
    execute_unified_rolling_and_save,
    _apply_confirmed_to_memory,
    _run_post_confirmed_pipeline,
    _run_confirmed_pipeline,
    fetch_unified_confirmed_data,
    fetch_confirmed_data_only,
    fetch_5d_data_only,
    _update_layout_cache,
    _step5_download_daily_confirmed,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(code: str, name: str = "테스트", market: str = "0", nxt: bool = True) -> UnifiedStockRecord:
    return UnifiedStockRecord(code=code, name=name, market_code=market, nxt_enable=nxt, raw_item={})


def _make_eval(code: str, excluded: bool = False, reason: str = "") -> StockFilterEvaluation:
    return StockFilterEvaluation(code=code, excluded=excluded, primary_reason=reason, reasons=[reason] if reason else [], state_flags=[], diagnostic_flags=[], parsed_fields={})


def _mock_state(**overrides):
    """Create a mock state with sensible defaults."""
    ms = MagicMock()
    ms.master_stocks_cache = {}
    ms.integrated_system_settings_cache = {
        "sector_stock_layout": [],
        "scheduler_market_close_on": True,
        "broker": "kiwoom",
    }
    ms.broker_tokens = {}
    ms.confirmed_refresh_running_confirmed = False
    ms.confirmed_refresh_running_5d = False
    ms.confirmed_done = False
    ms.latest_filter_summary_meta = ""
    ms.connector_manager = None
    ms.login_ok = False
    for k, v in overrides.items():
        setattr(ms, k, v)
    return ms


def _mock_conn():
    """Create a mock DB connection with async cursor/executemany/commit/rollback."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=[])
    cursor.execute = AsyncMock()
    conn.execute = AsyncMock(return_value=cursor)
    conn.executemany = AsyncMock()
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    conn.cursor = MagicMock(return_value=cursor)
    return conn


# ── _broadcast_confirmed_progress ─────────────────────────────────────────────

class TestBroadcastConfirmedProgress:
    def test_puts_data_in_queue(self):
        mock_q = MagicMock()
        mock_q.full.return_value = False
        with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_q):
            _broadcast_confirmed_progress(5, 10, message="테스트", step=1)
            mock_q.put_nowait.assert_called_once()
            data = mock_q.put_nowait.call_args.args[0]
            assert data["type"] == "confirmed-progress"
            assert data["data"]["current"] == 5
            assert data["data"]["total"] == 10
            assert data["data"]["step"] == 1

    def test_completed_status(self):
        mock_q = MagicMock()
        mock_q.full.return_value = False
        with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_q):
            _broadcast_confirmed_progress(10, 10, message="완료", step=1)
            data = mock_q.put_nowait.call_args.args[0]
            assert data["data"]["status"] == "completed"

    def test_partial_status_with_failures(self):
        mock_q = MagicMock()
        mock_q.full.return_value = False
        with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_q):
            _broadcast_confirmed_progress(10, 10, message="완료", step=1, failed_count=2)
            data = mock_q.put_nowait.call_args.args[0]
            assert data["data"]["status"] == "partial"

    def test_queue_full_skips(self):
        mock_q = MagicMock()
        mock_q.full.return_value = True
        with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_q):
            _broadcast_confirmed_progress(5, 10)
            mock_q.put_nowait.assert_not_called()

    def test_with_loop_uses_threadsafe(self):
        mock_q = MagicMock()
        mock_q.full.return_value = False
        mock_loop = MagicMock()
        with patch("backend.app.services.core_queues.get_broadcast_queue", return_value=mock_q):
            _broadcast_confirmed_progress(5, 10, _loop=mock_loop)
            mock_loop.call_soon_threadsafe.assert_called_once()

    def test_exception_does_not_raise(self):
        with patch("backend.app.services.core_queues.get_broadcast_queue", side_effect=Exception("boom")):
            _broadcast_confirmed_progress(5, 10)


# ── _get_krx_only_codes ───────────────────────────────────────────────────────

class TestGetKrxOnlyCodes:
    def test_empty_cache_returns_empty(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.is_nxt_enabled", return_value=True):
            result = _get_krx_only_codes()
            assert result == []

    def test_subscribed_krx_only_codes(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"_subscribed": True},
            "000660": {"_subscribed": True},
            "035420": {"_subscribed": False},
        }
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.is_nxt_enabled", side_effect=lambda cd: cd != "005930"):
            result = _get_krx_only_codes()
            assert "005930" in result
            assert "000660" not in result

    def test_layout_codes_included(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_state.integrated_system_settings_cache["sector_stock_layout"] = [
            ("sector", "반도체"),
            ("code", "005930"),
            ("code", "000660"),
        ]
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.is_nxt_enabled", side_effect=lambda cd: cd == "005930"):
            result = _get_krx_only_codes()
            # 005930 is NXT-enabled, 000660 is not
            assert "000660" in result
            assert "005930" not in result


# ── remove_krx_only_stocks ────────────────────────────────────────────────────

class TestRemoveKrxOnlyStocks:
    @pytest.mark.asyncio
    async def test_no_ws_returns_skipped(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await remove_krx_only_stocks()
            assert result == {"removed": 0, "failed": 0, "skipped": True}

    @pytest.mark.asyncio
    async def test_no_krx_codes_returns_empty(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_ws)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=[]):
            result = await remove_krx_only_stocks()
            assert result == {"removed": 0, "failed": 0, "skipped": False}

    @pytest.mark.asyncio
    async def test_remove_success_clears_subscribed(self):
        """연결 관리자 위임 성공 시 _subscribed 제거 + removed 집계."""
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.unsubscribe_stocks = AsyncMock(return_value=True)
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]):
            result = await remove_krx_only_stocks()
            assert result["removed"] == 1
            assert result["failed"] == 0
            assert result["skipped"] is False
            # 원본 6자리 코드 그대로 전달 (변환은 각 커넥터 담당)
            mock_ws.unsubscribe_stocks.assert_awaited_once_with(["005930"])
            # _subscribed 제거 확인
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]

    @pytest.mark.asyncio
    async def test_remove_failure_keeps_subscribed(self):
        """연결 관리자 위임 실패 시 _subscribed 유지 + failed 집계."""
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.unsubscribe_stocks = AsyncMock(return_value=False)
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]):
            result = await remove_krx_only_stocks()
            assert result["removed"] == 0
            assert result["failed"] == 1
            # _subscribed 유지 확인
            assert mock_state.master_stocks_cache["005930"].get("_subscribed") is True

    @pytest.mark.asyncio
    async def test_remove_exception_counts_failed(self):
        """연결 관리자 예외 시 failed 집계 + _subscribed 유지."""
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.unsubscribe_stocks = AsyncMock(side_effect=Exception("boom"))
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]):
            result = await remove_krx_only_stocks()
            assert result["removed"] == 0
            assert result["failed"] == 1
            assert mock_state.master_stocks_cache["005930"].get("_subscribed") is True

    @pytest.mark.asyncio
    async def test_remove_passes_original_codes_untransformed(self):
        """원본 6자리 코드를 변환 없이 연결 관리자에 전달 (각 커넥터가 자사 규격으로 변환)."""
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.unsubscribe_stocks = AsyncMock(return_value=True)
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {
            "005930": {"_subscribed": True},
            "000660": {"_subscribed": True},
        }
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930", "000660"]):
            result = await remove_krx_only_stocks()
            assert result["removed"] == 2
            mock_ws.unsubscribe_stocks.assert_awaited_once_with(["005930", "000660"])
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]
            assert "_subscribed" not in mock_state.master_stocks_cache["000660"]


# ── execute_unified_rolling_and_save ──────────────────────────────────────────
# 세션 2: DB 저장은 market_close_storage.save_daily_confirmed에 위임.
# 본 테스트 클래스는 save_daily_confirmed를 mock하여 저장 성공·실패 시 메모리 반영 동작을 검증.
# DB 파라미터·트랜잭션·안전망 상세 검증은 test_market_close_storage.py 에서 수행.

class TestExecuteUnifiedRollingAndSave:
    @pytest.mark.asyncio
    async def test_save_success_updates_memory(self):
        """저장 성공 시 메모리 캐시에 확정값·파생값이 반영되는지 검증 (설계 5.4)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자", "cur_price": 0}}
        confirmed = {
            "005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000, "high_price": 51000},
        }
        save_result = {"success": True, "saved_codes": ["005930"], "derived": {"005930": (4000000, 51000)}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock, return_value=save_result) as mock_save:
            result = await execute_unified_rolling_and_save(confirmed, name_map={"005930": "삼성전자"}, qry_dt="20250106")
            assert result is True
            mock_save.assert_awaited_once()
            entry = mock_state.master_stocks_cache["005930"]
            assert entry["cur_price"] == 50000
            assert entry["change"] == 1000
            assert entry["change_rate"] == 2.0
            assert entry["trade_amount"] == 5000000
            assert entry["date"] == "20250106"
            assert entry["status"] == "active"
            assert entry["name"] == "삼성전자"
            # 파생값 반영 (저장 모듈이 계산·저장한 값)
            assert entry["avg_5d_trade_amount"] == 4000000
            assert entry["high_5d_price"] == 51000

    @pytest.mark.asyncio
    async def test_save_failure_returns_false_and_skips_memory(self):
        """저장 실패 시 False 반환 + 메모리 미갱신 (P20 폴백 금지, P22 정합성)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자", "cur_price": 100, "avg_5d_trade_amount": 0}}
        confirmed = {
            "005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000, "high_price": 51000},
        }
        save_result = {"success": False, "saved_codes": [], "derived": {}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock, return_value=save_result):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250106")
            assert result is False
            # 메모리 미갱신 — 기존값 유지
            assert mock_state.master_stocks_cache["005930"]["cur_price"] == 100

    @pytest.mark.asyncio
    async def test_empty_confirmed_returns_false(self):
        """빈 confirmed는 저장할 게 없으므로 False (P20 — 빈값을 성공으로 위장 금지)."""
        empty_result = {"success": False, "saved_codes": [], "derived": {}}
        with patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock, return_value=empty_result) as mock_save:
            result = await execute_unified_rolling_and_save({})
            assert result is False
            mock_save.assert_awaited_once()  # save_daily_confirmed 호출되어 _empty_result 반환

    @pytest.mark.asyncio
    async def test_no_date_returns_false(self):
        """date_str 확정 불가 시 False (P20 폴백 금지)."""
        with patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value=""), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock) as mock_save:
            result = await execute_unified_rolling_and_save({"005930": {"cur_price": 50000}})
            assert result is False
            mock_save.assert_not_awaited()  # date_str 없어 저장 시도 안 함

    @pytest.mark.asyncio
    async def test_memory_date_uses_qry_dt(self):
        """메모리 캐시 date가 qry_dt(데이터 기준일)로 설정되는지 검증 (P10/P22).

        retry_pipeline_catchup_after_bootstrap 스킵 판단에 사용되므로 정확해야 함.
        """
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자"}}
        confirmed = {
            "005930": {"dt": "20250105", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
        }
        save_result = {"success": True, "saved_codes": ["005930"], "derived": {"005930": (400, 8888)}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock, return_value=save_result):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250105")
            assert result is True
            # 메모리 date는 qry_dt(20250105)로 설정 — current_trading_day(20250106) 아님
            assert mock_state.master_stocks_cache["005930"]["date"] == "20250105"


# ── 세션 3: 커밋 후 메모리 반영 + 회복 경로 (설계 3.3) ──────────────────────

class TestSession3MemoryRecovery:
    """세션 3 — 저장 성공 후 메모리 반영·회복 경로 검증 (설계 3.3).

    검증 항목:
    - 메모리 반영 오류 후 DB 커밋 범위 재로드 회복
    - 재로드 오류 후 후속 계산 차단 (False 반환)
    - 확정 데이터 반영 시 기존 실시간 필드 보존
    """

    @pytest.mark.asyncio
    async def test_memory_reflect_error_triggers_db_reload(self):
        """메모리 반영 오류 시 DB 커밋 범위 재로드 회복 (설계 3.3)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자", "cur_price": 100}}
        confirmed = {"005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000, "high_price": 51000}}
        save_result = {"success": True, "saved_codes": ["005930"], "derived": {"005930": (4000000, 51000)}}
        reload_calls = []

        async def fake_reload(codes):
            reload_calls.append(codes)
            mock_state.master_stocks_cache["005930"]["cur_price"] = 50000
            mock_state.master_stocks_cache["005930"]["date"] = "20250106"

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock, return_value=save_result), \
             patch("backend.app.services.market_close_pipeline._apply_confirmed_to_memory", new_callable=AsyncMock, side_effect=RuntimeError("mem fail")), \
             patch("backend.app.services.market_close_pipeline._reload_confirmed_from_db", new=AsyncMock(side_effect=fake_reload)):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250106")
            assert result is True
            assert len(reload_calls) == 1
            assert "005930" in reload_calls[0]
            # 재로드 회복 후 메모리 갱신됨
            assert mock_state.master_stocks_cache["005930"]["cur_price"] == 50000

    @pytest.mark.asyncio
    async def test_reload_error_blocks_subsequent(self):
        """재로드 실패 시 False 반환 — 후속 업종 계산·매매 판단·화면 확정 중단 (설계 3.3)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자", "cur_price": 100}}
        confirmed = {"005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000, "high_price": 51000}}
        save_result = {"success": True, "saved_codes": ["005930"], "derived": {"005930": (4000000, 51000)}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock, return_value=save_result), \
             patch("backend.app.services.market_close_pipeline._apply_confirmed_to_memory", new_callable=AsyncMock, side_effect=RuntimeError("mem fail")), \
             patch("backend.app.services.market_close_pipeline._reload_confirmed_from_db", new_callable=AsyncMock, side_effect=RuntimeError("reload fail")):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250106")
            assert result is False  # 후속 계산 차단

    @pytest.mark.asyncio
    async def test_realtime_fields_preserved_on_memory_apply(self):
        """확정 데이터 반영 시 기존 실시간 필드 보존 (설계 3.3 — 불필요한 삭제 금지)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {
            "name": "삼성전자", "cur_price": 100, "strength": "85.50",
            "captured_at": "20250106-153000", "base_price": 49000, "target_price": 55000,
            "_subscribed": True, "sign": "2",
        }}
        confirmed = {"005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000, "high_price": 51000, "sign": "2"}}
        save_result = {"success": True, "saved_codes": ["005930"], "derived": {"005930": (4000000, 51000)}}
        mock_conn = _mock_conn()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_storage.save_daily_confirmed", new_callable=AsyncMock, return_value=save_result):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250106")
            assert result is True
            entry = mock_state.master_stocks_cache["005930"]
            # 확정값 반영
            assert entry["cur_price"] == 50000
            assert entry["date"] == "20250106"
            assert entry["avg_5d_trade_amount"] == 4000000
            assert entry["high_5d_price"] == 51000
            # 실시간 필드 보존 — 확정 데이터 반영으로 삭제되지 않음
            assert entry["strength"] == "85.50"
            assert entry["captured_at"] == "20250106-153000"
            assert entry["base_price"] == 49000
            assert entry["target_price"] == 55000
            assert entry["_subscribed"] is True


# ── _apply_confirmed_to_memory ────────────────────────────────────────────────

class TestApplyConfirmedToMemory:
    @pytest.mark.asyncio
    async def test_existing_entry_updates(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"name": "삼성전자", "cur_price": 0, "status": "inactive"},
        }
        confirmed = {"005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "sign": "2", "trade_amount": 5000000}}
        mock_conn = _mock_conn()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await _apply_confirmed_to_memory(confirmed, {})
            assert result == 1
            assert mock_state.master_stocks_cache["005930"]["cur_price"] == 50000
            assert mock_state.master_stocks_cache["005930"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_confirmed_codes_filter(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"name": "삼성전자", "cur_price": 0, "status": "inactive"},
            "000660": {"name": "SK하이닉스", "cur_price": 0, "status": "inactive"},
        }
        confirmed = {
            "005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000},
            "000660": {"cur_price": 100000, "change": 2000, "change_rate": 2.0, "trade_amount": 3000000},
        }
        mock_conn = _mock_conn()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await _apply_confirmed_to_memory(confirmed, {}, confirmed_codes={"005930"})
            assert result == 1
            assert mock_state.master_stocks_cache["000660"]["cur_price"] == 0

    @pytest.mark.asyncio
    async def test_new_entry_created(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        confirmed = {"005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "sign": "2", "trade_amount": 5000000}}
        mock_conn = _mock_conn()
        mock_detail = {"name": "삼성전자", "cur_price": 50000, "status": "active"}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.engine_strategy_core.make_detail", return_value=mock_detail):
            result = await _apply_confirmed_to_memory(confirmed, {}, name_map={"005930": "삼성전자"})
            assert result == 1
            assert "005930" in mock_state.master_stocks_cache

    @pytest.mark.asyncio
    async def test_strength_applied(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"name": "삼성전자", "cur_price": 0, "status": "inactive"},
        }
        confirmed = {"005930": {"cur_price": 50000, "change": 0, "change_rate": 0.0, "trade_amount": 0}}
        mock_conn = _mock_conn()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            await _apply_confirmed_to_memory(confirmed, {"005930": 85.5})
            assert mock_state.master_stocks_cache["005930"]["strength"] == "85.50"

    @pytest.mark.asyncio
    async def test_db_exception_continues(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"name": "삼성전자", "cur_price": 0, "status": "inactive"},
        }
        confirmed = {"005930": {"cur_price": 50000, "change": 0, "change_rate": 0.0, "trade_amount": 0}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, side_effect=Exception("DB fail")), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await _apply_confirmed_to_memory(confirmed, {})
            assert result == 1


# ── _run_post_confirmed_pipeline ──────────────────────────────────────────────
# 세션 2: _save_confirmed_cache (중복 재저장 경로) 제거.
# _run_post_confirmed_pipeline은 일별 계좌 스냅샷 저장만 수행.

class TestRunPostConfirmedPipeline:
    @pytest.mark.asyncio
    async def test_calls_save_daily_snapshot(self):
        """_save_daily_snapshot 호출 검증 (P25 격리 — 스냅샷 실패 시 파이프라인 중단 안 함)."""
        with patch("backend.app.services.market_close_pipeline._save_daily_snapshot", new_callable=AsyncMock) as mock_snap, \
             patch("backend.app.services.engine_account.get_trade_mode", return_value="virtual"):
            await _run_post_confirmed_pipeline()
            mock_snap.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snapshot_exception_does_not_raise(self):
        """스냅샷 저장 실패 시 예외 전파 없이 진행 (P25 격리)."""
        with patch("backend.app.services.market_close_pipeline._save_daily_snapshot", new_callable=AsyncMock, side_effect=Exception("boom")), \
             patch("backend.app.services.engine_account.get_trade_mode", return_value="virtual"):
            await _run_post_confirmed_pipeline()  # 예외 발생 안 함

    @pytest.mark.asyncio
    async def test_does_not_call_save_confirmed_cache(self):
        """중복 재저장 경로(_save_confirmed_cache)가 제거되었는지 회귀 검증 (설계 5.4 · 세션 2).

        _save_confirmed_cache는 세션 2에서 제거됨. 본 테스트는 함수가 더 이상 존재하지 않는지,
        그리고 _run_post_confirmed_pipeline이 메모리 전체 재저장을 수행하지 않는지 확인.
        """
        # _save_confirmed_cache 가 모듈에 존재하지 않는지 확인 (제거 검증)
        import backend.app.services.market_close_pipeline as mcp
        assert not hasattr(mcp, "_save_confirmed_cache"), "_save_confirmed_cache 가 제거되지 않았습니다 (세션 2 회귀)"
        # _run_post_confirmed_pipeline 호출 시 스냅샷만 수행 (DB 재저장 없음)
        with patch("backend.app.services.market_close_pipeline._save_daily_snapshot", new_callable=AsyncMock) as mock_snap, \
             patch("backend.app.services.engine_account.get_trade_mode", return_value="virtual"):
            await _run_post_confirmed_pipeline(eligible_codes={"005930"})
            mock_snap.assert_awaited_once()


# ── _update_layout_cache ──────────────────────────────────────────────────────

class TestUpdateLayoutCache:
    @pytest.mark.asyncio
    async def test_rebuilds_layout(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"sector": "반도체"},
            "000660": {"sector": "반도체"},
            "035420": {"sector": "자동차"},
        }
        mock_conn = _mock_conn()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache") as mock_rebuild:
            await _update_layout_cache(["005930", "000660", "035420"], {})
            layout = mock_state.integrated_system_settings_cache["sector_stock_layout"]
            sectors = [v for t, v in layout if t == "sector"]
            assert "반도체" in sectors
            assert "자동차" in sectors
            mock_rebuild.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_exception_continues(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"sector": "반도체"}}
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, side_effect=Exception("DB fail")), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"):
            await _update_layout_cache(["005930"], {})


# ── _run_confirmed_pipeline ───────────────────────────────────────────────────

class TestRunConfirmedPipeline:
    @pytest.mark.asyncio
    async def test_already_running_returns_skipped(self):
        mock_state = _mock_state()
        mock_state.confirmed_refresh_running_confirmed = True
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await _run_confirmed_pipeline("test")
            assert result == {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

    @pytest.mark.asyncio
    async def test_scheduler_off_returns_skipped(self):
        mock_state = _mock_state()
        mock_state.integrated_system_settings_cache["scheduler_market_close_on"] = False
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            result = await _run_confirmed_pipeline("test", check_scheduler=True)
            assert result == {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

    @pytest.mark.asyncio
    async def test_empty_records_returns_empty(self):
        mock_state = _mock_state()
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks = AsyncMock(return_value=[])
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector):
            result = await _run_confirmed_pipeline("test")
            assert result == {"fetched": 0, "failed": 0, "cached": False}

    @pytest.mark.asyncio
    async def test_fetch_all_stocks_exception_returns_empty(self):
        mock_state = _mock_state()
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks = AsyncMock(side_effect=Exception("API fail"))
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector):
            result = await _run_confirmed_pipeline("test")
            assert result == {"fetched": 0, "failed": 0, "cached": False}

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value="token123")
        mock_sector = MagicMock()
        records = [
            _make_record("005930", "삼성전자", "0", True),
            _make_record("000660", "SK하이닉스", "0", True),
        ]
        mock_sector.fetch_all_stocks = AsyncMock(return_value=records)
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250105", "response_date": "20250105"},
            "000660": {"close": 100000, "value": 3000000, "high": 101000, "volume": 30000, "change": 2000, "rate": 2.0, "sign": "2", "dt": "20250105", "response_date": "20250105"},
        })
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.core.stock_filter.evaluate_stock_filter", side_effect=lambda raw, code: _make_eval(code, excluded=False)), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.core.stock_classification_data.sync_sector_from_custom_sectors", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._update_layout_cache", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._apply_confirmed_to_memory", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.execute_unified_rolling_and_save", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.get_previous_trading_day_str", return_value="20250105"), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"):
            result = await _run_confirmed_pipeline("test")
            assert result["fetched"] == 2
            assert result["failed"] == 0
            assert result["cached"] is True

    @pytest.mark.asyncio
    async def test_time_guard_blocks_step5(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        records = [_make_record("005930", "삼성전자", "0", True)]
        mock_sector.fetch_all_stocks = AsyncMock(return_value=records)
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.core.stock_filter.evaluate_stock_filter", side_effect=lambda raw, code: _make_eval(code, excluded=False)), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.core.stock_classification_data.sync_sector_from_custom_sectors", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._update_layout_cache", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.is_heavy_operation_allowed", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"):
            result = await _run_confirmed_pipeline("test", check_time_guard=True)
            assert result == {"fetched": 0, "failed": 0, "cached": False}

    @pytest.mark.asyncio
    async def test_broker_token_registered_and_cleaned(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value="token123")
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks = AsyncMock(return_value=[])
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock) as mock_broadcast:
            await _run_confirmed_pipeline("test")
            # Token was registered and then cleaned up in finally
            assert "kiwoom" not in mock_state.broker_tokens
            # broadcast_engine_status called twice: once for register, once for cleanup
            assert mock_broadcast.await_count == 2

    @pytest.mark.asyncio
    async def test_broker_token_reused_when_startup_token_exists(self):
        """시나리오 9 (추가A): broker == confirmed_data_broker 시 startup 토큰 재사용 → pop 안 함.

        Lazy Auth 설계서 섹션 9 시나리오 9:
        broker=kiwoom, confirmed_data_broker=kiwoom (동일) → startup kiwoom 토큰 존재 →
        배치 진입 시 `_broker_name not in broker_tokens` 조건 False → _broker_token_registered=False →
        finally에서 pop 안 함 → 기존 kiwoom 토큰 유지 (재사용).
        """
        mock_state = _mock_state()
        mock_state.integrated_system_settings_cache["confirmed_data_broker"] = "kiwoom"
        mock_state.master_stocks_cache = {}
        mock_state.broker_tokens = {"kiwoom": "startup_token"}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value="batch_token")
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks = AsyncMock(return_value=[])
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock) as mock_broadcast:
            await _run_confirmed_pipeline("test")
            # 기존 startup 토큰 유지 — pop 안 함 (_broker_token_registered=False 경로)
            assert mock_state.broker_tokens.get("kiwoom") == "startup_token"
            # register/finally 모두 분기 진입 안 함 → broadcast 0회
            assert mock_broadcast.await_count == 0


# ── fetch_unified_confirmed_data ──────────────────────────────────────────────

class TestFetchUnifiedConfirmedData:
    @pytest.mark.asyncio
    async def test_delegates_to_run_confirmed_pipeline(self):
        with patch("backend.app.services.market_close_pipeline._run_confirmed_pipeline", new_callable=AsyncMock, return_value={"fetched": 10, "failed": 0, "cached": True}) as mock_run:
            result = await fetch_unified_confirmed_data()
            mock_run.assert_awaited_once()
            assert result["fetched"] == 10
            # Verify check_scheduler=True and check_time_guard=True
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["check_scheduler"] is True
            assert call_kwargs["check_time_guard"] is True


# ── fetch_confirmed_data_only ─────────────────────────────────────────────────

class TestFetchConfirmedDataOnly:
    @pytest.mark.asyncio
    async def test_delegates_to_run_confirmed_pipeline(self):
        with patch("backend.app.services.market_close_pipeline._run_confirmed_pipeline", new_callable=AsyncMock, return_value={"fetched": 5, "failed": 1, "cached": True}) as mock_run:
            result = await fetch_confirmed_data_only()
            mock_run.assert_awaited_once()
            assert result["fetched"] == 5
            # No check_scheduler or check_time_guard
            call_kwargs = mock_run.call_args.kwargs
            assert "check_scheduler" not in call_kwargs or call_kwargs["check_scheduler"] is False


# ── fetch_5d_data_only ────────────────────────────────────────────────────────
# 세션 2: DB 저장은 market_close_storage.save_5d_bars에 위임.
# 본 테스트 클래스는 save_5d_bars를 mock하여 다운로드 카운트·메모리 반영·저장 호출 여부를 검증.
# DB 파라미터(DELETE/안전망/행 정리) 상세 검증은 test_market_close_storage.py 에서 수행.

def _patch_5d_common(mock_state, mock_auth, mock_sector, *, save_result=None, current_td="20250107", prev_td="20250106"):
    """fetch_5d_data_only 테스트 공용 patch 컨텍스트 매니저 팩토리."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("backend.app.services.engine_state.state", mock_state))
    stack.enter_context(patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector))
    stack.enter_context(patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"))
    stack.enter_context(patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x))
    stack.enter_context(patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock))
    stack.enter_context(patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock))
    stack.enter_context(patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock))
    stack.enter_context(patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock))
    stack.enter_context(patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value=current_td))
    stack.enter_context(patch("backend.app.services.market_close_pipeline.get_previous_trading_day_str", return_value=prev_td))
    stack.enter_context(patch("asyncio.sleep", new_callable=AsyncMock))
    if save_result is not None:
        stack.enter_context(patch("backend.app.services.market_close_storage.save_5d_bars", new_callable=AsyncMock, return_value=save_result))
    return stack


class TestFetch5dDataOnly:
    @pytest.mark.asyncio
    async def test_already_running_returns_skipped(self):
        mock_state = _mock_state()
        mock_state.confirmed_refresh_running_5d = True
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await fetch_5d_data_only()
            assert result == {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

    @pytest.mark.asyncio
    async def test_no_active_codes_returns_empty(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            result = await fetch_5d_data_only()
            assert result == {"fetched": 0, "failed": 0, "cached": False}

    @pytest.mark.asyncio
    async def test_full_5d_download_success_calls_save_and_updates_memory(self):
        """저장 성공 시 save_5d_bars 호출 + 메모리 파생값 반영 검증 (설계 5.4)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
            "000660": {"status": "active", "name": "SK하이닉스"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value={
            "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
            "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
            "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
        })
        save_result = {
            "success": True,
            "saved_codes": ["005930", "000660"],
            "derived": {"005930": (3000000, 55000), "000660": (3000000, 55000)},
        }
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 2
        assert result["failed"] == 0
        # 메모리 파생값 반영 검증
        assert mock_state.master_stocks_cache["005930"]["avg_5d_trade_amount"] == 3000000
        assert mock_state.master_stocks_cache["005930"]["high_5d_price"] == 55000
        assert mock_state.master_stocks_cache["000660"]["avg_5d_trade_amount"] == 3000000

    @pytest.mark.asyncio
    async def test_5d_download_applies_derived_and_triggers_recompute(self):
        """다운로드 완료 후 종목별 파생값 갱신 + 재계산 호출 (설계서 5.3, 세션 4).

        save_5d_bars가 반환한 derived가 메모리 캐시에 반영되고,
        _post_recompute_notify가 호출되어 WS 전송 경로가 연결됨.
        """
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
            "000660": {"status": "active", "name": "SK하이닉스"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value={
            "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
            "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
            "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
        })
        save_result = {
            "success": True,
            "saved_codes": ["005930", "000660"],
            "derived": {"005930": (3000000, 55000), "000660": (3000000, 55000)},
        }
        post_recompute_mock = AsyncMock()
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result), \
             patch("backend.app.services.market_close_pipeline._post_recompute_notify", post_recompute_mock):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 2
        # 종목별 파생값 갱신 (설계서 5.3 단계 4·5)
        assert mock_state.master_stocks_cache["005930"]["avg_5d_trade_amount"] == 3000000
        assert mock_state.master_stocks_cache["005930"]["high_5d_price"] == 55000
        assert mock_state.master_stocks_cache["000660"]["avg_5d_trade_amount"] == 3000000
        # 재계산 + WS 전송 호출 (설계서 5.3 단계 7·8)
        post_recompute_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_5d_download_partial_failure_keeps_failed_derived(self):
        """일부 종목 다운로드 실패 시 실패 종목 파생값 미갱신, 성공 종목만 갱신 (설계서 5.3)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
            "000660": {"status": "active", "name": "SK하이닉스"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        # 005930 성공, 000660 실패 (None 반환)
        mock_sector.fetch_stock_5day_data = AsyncMock(side_effect=[
            {
                "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
            },
            None,
        ])
        save_result = {
            "success": True,
            "saved_codes": ["005930"],
            "derived": {"005930": (3000000, 55000)},
        }
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 1
        assert result["failed"] == 1
        # 성공 종목 — 파생값 갱신
        assert mock_state.master_stocks_cache["005930"]["avg_5d_trade_amount"] == 3000000
        # 실패 종목 — 파생값 미갱신 (키 없음)
        assert "avg_5d_trade_amount" not in mock_state.master_stocks_cache["000660"]

    @pytest.mark.asyncio
    async def test_save_failure_skips_memory_update(self):
        """save_5d_bars 실패 시 메모리 미갱신 (P22 정합성)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자", "avg_5d_trade_amount": 0, "high_5d_price": 0},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value={
            "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
            "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
            "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
        })
        save_result = {"success": False, "saved_codes": [], "derived": {}}
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 1
        # 메모리 미갱신 — 기존값(0) 유지
        assert mock_state.master_stocks_cache["005930"]["avg_5d_trade_amount"] == 0
        assert mock_state.master_stocks_cache["005930"]["high_5d_price"] == 0

    @pytest.mark.asyncio
    async def test_5d_api_returns_none_counts_failed(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value=None)
        save_result = {"success": True, "saved_codes": [], "derived": {}}
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 0
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_5d_api_exception_counts_failed(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(side_effect=Exception("API fail"))
        save_result = {"success": True, "saved_codes": [], "derived": {}}
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 0
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_5d_empty_arrays_counts_failed(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value={"amts_5d_array": [], "highs_5d_array": [], "dts_5d_array": []})
        save_result = {"success": True, "saved_codes": [], "derived": {}}
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 0
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_5d_memory_error_triggers_reload_recovery(self):
        """수동 5일 메모리 반영 오류 시 DB 재로드 회복 — 후속 업종 계산 진행 (설계 3.3, 세션 3)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"status": "active", "name": "삼성전자"}}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value={
            "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
            "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
            "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
        })
        save_result = {"success": True, "saved_codes": ["005930"], "derived": {"005930": (3000000, 55000)}}
        post_recompute_mock = AsyncMock()
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result), \
             patch("backend.app.services.market_close_pipeline._apply_5d_derived_to_memory", new_callable=AsyncMock, side_effect=RuntimeError("mem fail")), \
             patch("backend.app.services.market_close_pipeline._reload_confirmed_from_db", new_callable=AsyncMock) as reload_mock, \
             patch("backend.app.services.market_close_pipeline._post_recompute_notify", post_recompute_mock):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 1
        reload_mock.assert_awaited_once()
        # 재로드 회복 성공 → 후속 업종 계산 진행
        post_recompute_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_5d_reload_error_blocks_post_recompute(self):
        """수동 5일 재로드 실패 시 업종순위 재계산 중단 (설계 3.3, 세션 3)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"status": "active", "name": "삼성전자"}}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value={
            "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
            "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
            "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
        })
        save_result = {"success": True, "saved_codes": ["005930"], "derived": {"005930": (3000000, 55000)}}
        post_recompute_mock = AsyncMock()
        with _patch_5d_common(mock_state, mock_auth, mock_sector, save_result=save_result), \
             patch("backend.app.services.market_close_pipeline._apply_5d_derived_to_memory", new_callable=AsyncMock, side_effect=RuntimeError("mem fail")), \
             patch("backend.app.services.market_close_pipeline._reload_confirmed_from_db", new_callable=AsyncMock, side_effect=RuntimeError("reload fail")), \
             patch("backend.app.services.market_close_pipeline._post_recompute_notify", post_recompute_mock):
            result = await fetch_5d_data_only()
        assert result["fetched"] == 1
        # 재로드 실패 → 업종순위 재계산 중단
        post_recompute_mock.assert_not_awaited()


# ── _step5_download_daily_confirmed — B3-05-02 빈 폴백 제거 ────────────────────

class TestStep5DownloadDailyConfirmedEmptyFallback:
    """B3-05-02: 전종목 일봉 시세 다운로드 실패 시 빈 폴백(confirmed={}) 제거 검증.

    세션 5 — _step5는 다운로드+검증만 담당. 저장·화면·스냅샷은 총괄이 호출.
    빈 폴백으로 후속 파이프라인 진행 금지 → early return ({}, 0, total).
    _run_post_confirmed_pipeline 미호출, execute_unified_rolling_and_save 미호출.
    """

    @pytest.mark.asyncio
    async def test_fetch_exception_early_returns_without_post_pipeline(self):
        """fetch_all_stocks_daily_confirmed 예외 → early return, 후속 파이프라인 스킵 (P20)."""
        mock_state = _mock_state()
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(side_effect=Exception("API fail"))
        all_codes = ["005930", "000660"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        # early return — 빈 검증 결과, 실패 전체
        assert verified == {}
        assert fetched == 0
        assert failed == len(all_codes)
        assert set(failed_details.keys()) == set(all_codes)

    @pytest.mark.asyncio
    async def test_fetch_success_returns_verified_only(self):
        """fetch_all_stocks_daily_confirmed 성공 → 검증 통과 데이터만 반환 (세션 5 — 저장은 총괄이 호출)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250105", "response_date": "20250105"},
        })
        all_codes = ["005930"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        assert fetched == 1
        assert failed == 0
        assert "005930" in verified
        assert failed_details == {}
        # 세션 5: _step5는 저장·화면·스냅샷을 호출하지 않는다 (총괄 책임).
        # 반환된 검증 통과 데이터를 총괄이 저장에 전달한다.


# ── 세션 1: 다운로드 결과 계약 — 검증 실패 종목 분리 (설계 4.2) ──────────────────

class TestStep5DownloadVerificationFailure:
    """자동 일봉 다운로드 검증: cur_price=0 종목은 검증 실패로 분류, 저장·메모리 전달 제외 (설계 4.2).

    시나리오: 다운로드는 성공했으나 일부 종목의 cur_price=0 (미확정).
    검증 통과 종목만 저장·메모리 반영에 전달되어야 함.
    """

    @pytest.mark.asyncio
    async def test_zero_price_excluded_from_verified(self):
        """cur_price=0 종목은 검증 실패 — 반환 검증 결과에서 제외 (P22, 세션 5 — 저장은 총괄)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        # 005930은 정상(cur_price=50000), 000660은 cur_price=0 (미확정)
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250105", "response_date": "20250105"},
            "000660": {"close": 0, "value": 0, "high": 0, "volume": 0, "change": 0, "rate": 0.0, "sign": "3", "dt": "20250105", "response_date": "20250105"},
        })
        all_codes = ["005930", "000660"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        # 검증 통과 1종목, 검증 실패 1종목 → 실패 집합 포함
        assert fetched == 1
        assert failed == 1
        # 검증 통과 종목만 반환 — 000660(cur_price=0)은 제외 (설계 4.2)
        assert "005930" in verified
        assert "000660" not in verified
        assert "000660" in failed_details

    @pytest.mark.asyncio
    async def test_all_zero_price_returns_empty(self):
        """모든 종목 cur_price=0 → 검증 전부 실패 — 빈 검증 결과 반환 (P20 폴백 금지, 세션 5)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 0, "value": 0, "high": 0, "volume": 0, "change": 0, "rate": 0.0, "sign": "3", "dt": "20250105", "response_date": "20250105"},
            "000660": {"close": 0, "value": 0, "high": 0, "volume": 0, "change": 0, "rate": 0.0, "sign": "3", "dt": "20250105", "response_date": "20250105"},
        })
        all_codes = ["005930", "000660"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        # 검증 전부 실패 → 빈 검증 결과
        assert verified == {}
        assert fetched == 0
        assert failed == 2
        assert set(failed_details.keys()) == {"005930", "000660"}


class TestFetch5dVerificationFailure:
    """수동 5일 다운로드 검증: 유효값(>0)이 없는 종목은 검증 실패로 분류 (설계 4.2).

    시나리오: 배열은 비어있지 않으나 전부 0이면 확정되지 않은 데이터.
    """

    @pytest.mark.asyncio
    async def test_all_zero_arrays_count_failed(self):
        """배열은 있으나 전부 0 → 검증 실패, 실패 집합 포함 (P22)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
            "000660": {"status": "active", "name": "SK하이닉스"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        # 005930은 정상, 000660은 전부 0
        fetch_side_effects = [
            {
                "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
            },
            {
                "amts_5d_array": [0, 0, 0, 0, 0],
                "highs_5d_array": [0, 0, 0, 0, 0],
                "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
            },
        ]
        mock_sector.fetch_stock_5day_data = AsyncMock(side_effect=fetch_side_effects)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_pipeline.get_previous_trading_day_str", return_value="20250106"), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_storage.save_5d_bars", new_callable=AsyncMock) as mock_save_5d:
            # save_5d_bars는 검증 통과 종목만 받아야 함 — 호출 인자로 검증
            async def _capture_save(confirmed_5d, *, qry_dt=""):
                # 검증 통과 종목(005930)만 confirmed_5d에 있어야 함
                assert "000660" not in confirmed_5d, "검증 실패 종목이 저장 모듈에 전달됨 (설계 4.2 위반)"
                assert "005930" in confirmed_5d
                return {"success": True, "saved_codes": list(confirmed_5d.keys()), "derived": {}}
            mock_save_5d.side_effect = _capture_save
            result = await fetch_5d_data_only()
            # 005930 성공, 000660 검증 실패
            assert result["fetched"] == 1
            assert result["failed"] == 1
            mock_save_5d.assert_awaited_once()


# ── 세션 6 회귀 테스트 보완 — 설계 준수 명시 검증 ──────────────────────────────
# 갭1: 자동 일봉 저장 실패(cached=False) 시 업종재계산·화면전송 차단 (설계 3.3, 세션5)
# 갭2: 총괄 단계 호출 순서 — 저장→종목분류화면→스냅샷→업종재계산 (설계 5.4·5.7, 세션5)
# 갭3: _post_recompute_notify 내부 순서 — 수신율→종목분류갱신→업종재계산→활성연결갱신 (설계 5.7)


class TestRunConfirmedPipelineSaveFailureBlocksRecompute:
    """갭1: 자동 일봉 저장·메모리 반영·재로드 회복 중 실패(cached=False) 시
    업종순위 재계산·화면 확정 전송이 차단되는지 검증 (설계 3.3, 세션5 완료조건).
    """

    @pytest.mark.asyncio
    async def test_save_failure_blocks_step7_recompute(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value="token123")
        mock_sector = MagicMock()
        records = [_make_record("005930", "삼성전자", "0", True)]
        mock_sector.fetch_all_stocks = AsyncMock(return_value=records)
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2"},
        })
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.core.stock_filter.evaluate_stock_filter", side_effect=lambda raw, code: _make_eval(code, excluded=False)), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.core.stock_classification_data.sync_sector_from_custom_sectors", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._update_layout_cache", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.execute_unified_rolling_and_save", new_callable=AsyncMock, return_value=False), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._step7_recompute_and_broadcast", new_callable=AsyncMock) as step7_mock, \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.get_previous_trading_day_str", return_value="20250105"), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"):
            result = await _run_confirmed_pipeline("test")
        # 저장 실패 → cached=False
        assert result["cached"] is False
        # 설계 3.3: 저장·메모리 반영·재로드 회복 중 실패 시 업종 계산·화면 확정 중단
        step7_mock.assert_not_awaited()


class TestRunConfirmedPipelineStepOrder:
    """갭2: _run_confirmed_pipeline 총괄 단계 호출 순서 검증 (설계 5.4·5.7, 세션5 완료조건).
    순서: 저장 → 종목분류 화면 → 계좌 스냅샷 → 업종재계산+화면전송.
    """

    @pytest.mark.asyncio
    async def test_step_order_save_classification_snapshot_recompute(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value="token123")
        mock_sector = MagicMock()
        records = [_make_record("005930", "삼성전자", "0", True)]
        mock_sector.fetch_all_stocks = AsyncMock(return_value=records)
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250105", "response_date": "20250105"},
        })
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)

        # 순서 추적용 부모 Mock — 각 단계를 자식 AsyncMock으로 등록
        parent = MagicMock()
        parent.save = AsyncMock(return_value=True)
        parent.classification = AsyncMock()
        parent.snapshot = AsyncMock()
        parent.step7 = AsyncMock()

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.core.stock_filter.evaluate_stock_filter", side_effect=lambda raw, code: _make_eval(code, excluded=False)), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.core.stock_classification_data.sync_sector_from_custom_sectors", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._update_layout_cache", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new=parent.classification), \
             patch("backend.app.services.market_close_pipeline.execute_unified_rolling_and_save", new=parent.save), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new=parent.snapshot), \
             patch("backend.app.services.market_close_pipeline._step7_recompute_and_broadcast", new=parent.step7), \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.get_previous_trading_day_str", return_value="20250105"), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"):
            result = await _run_confirmed_pipeline("test")
        assert result["cached"] is True
        # 순서 검증 — parent.mock_calls 에는 parent.<attr>(...) 호출이 순서대로 기록.
        # 4단계(종목분류 매핑 저장)에서 classification 1회 → 6단계 save →
        # 6단계 후 확정데이터 반영 classification 1회 → snapshot → step7 (설계 5.4·5.7, 세션5)
        call_names = [c[0] for c in parent.mock_calls]
        assert call_names == ["classification", "save", "classification", "snapshot", "step7"], \
            f"단계 순서 이탈: {call_names}"


class TestPostRecomputeNotifyOrder:
    """갭3: _post_recompute_notify 내부 호출 순서 검증 (설계 5.7).
    순서: 수신율 계산 → 수신율 전송 → 종목분류 갱신 → 업종재계산 → 활성연결 갱신.
    """

    @pytest.mark.asyncio
    async def test_internal_call_order(self):
        from backend.app.services.market_close_pipeline import _post_recompute_notify
        # pipeline_compute 모듈 로드 시 broadcast_queue 필요 — 테스트용 큐 초기화
        from backend.app.services.core_queues import initialize_queues
        initialize_queues()

        parent = MagicMock()
        parent.calc_rate = AsyncMock()
        parent.send_rate = AsyncMock()
        parent.notify = AsyncMock()
        parent.recompute = AsyncMock()
        parent.refresh = AsyncMock()

        with patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new=parent.calc_rate), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new=parent.send_rate), \
             patch("backend.app.pipelines.pipeline_compute.get_current_receive_rate", return_value=99.0), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new=parent.notify), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new=parent.recompute), \
             patch("backend.app.services.page_subscription_targets.refresh_active_connections", new=parent.refresh):
            await _post_recompute_notify("test")
        call_names = [c[0] for c in parent.mock_calls]
        assert call_names == ["calc_rate", "send_rate", "notify", "recompute", "refresh"], \
            f"_post_recompute_notify 순서 이탈: {call_names}"


# ── 3단계: 자동 확정 자료의 부분 성공·날짜 정합성 처리 (설계서 4.2·4.3) ──────────

class TestStep5DateMismatch:
    """응답 기준일이 요청 기준일과 다르면 날짜 불일치 상태로 분류 (설계서 4.2)."""

    @pytest.mark.asyncio
    async def test_date_mismatch_excluded_from_verified(self):
        """응답일 ≠ 요청일 → verified 제외, failed_details 에 date_mismatch 기록 (설계서 4.2)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250104", "response_date": "20250104"},
        })
        all_codes = ["005930"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        assert fetched == 0
        assert failed == 1
        assert verified == {}
        assert failed_details.get("005930") == "date_mismatch"

    @pytest.mark.asyncio
    async def test_no_response_date_excluded_from_verified(self):
        """응답 기준일이 없으면 저장 성공으로 처리하지 않는다 (설계서 4.2)."""
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "", "response_date": None},
        })
        all_codes = ["005930"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        assert fetched == 0
        assert failed == 1
        assert verified == {}
        assert failed_details.get("005930") == "no_response_date"


class TestStep5FetchFailedStatus:
    """수신 실패(raw_payload=None) 종목은 verified 에서 제외 (설계서 4.3)."""

    @pytest.mark.asyncio
    async def test_fetch_failed_status_excluded(self):
        from backend.app.core.broker_providers import RawStockFetchResult
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": RawStockFetchResult(code="005930"),  # raw_payload=None → 실패
        })
        all_codes = ["005930"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        assert fetched == 0
        assert failed == 1
        assert verified == {}
        assert failed_details.get("005930") == "fetch_failed"


class TestStep5PartialSuccess:
    """일부 종목만 성공 — 성공 종목은 verified 에, 실패 종목은 failed_details 에 (설계서 4.3)."""

    @pytest.mark.asyncio
    async def test_partial_success_separates_success_and_failure(self):
        from backend.app.core.broker_providers import RawStockFetchResult
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": RawStockFetchResult(
                code="005930",
                raw_payload={"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250105"},
            ),
            "000660": RawStockFetchResult(code="000660"),  # raw_payload=None → 실패
        })
        all_codes = ["005930", "000660"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        # 성공 1종목, 실패 1종목 — 부분 성공을 전체 성공으로 표시하지 않음 (설계서 4.3)
        assert fetched == 1
        assert failed == 1
        assert "005930" in verified
        assert "000660" not in verified
        assert failed_details.get("000660") == "fetch_failed"
        # 정상 종목의 자료는 보존 (설계서 4.3)
        assert verified["005930"]["cur_price"] == 50000


class TestStep5MissingStockInResponse:
    """요청했으나 응답에 없는 종목 — 실패 집합에 no_data 로 포함 (설계서 4.3)."""

    @pytest.mark.asyncio
    async def test_missing_stock_counted_as_failed(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_sector = MagicMock()
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250105", "response_date": "20250105"},
        })
        all_codes = ["005930", "000660"]

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            verified, fetched, failed, failed_details = await _step5_download_daily_confirmed(
                "[test]", mock_sector, all_codes, qry_dt="20250105",
            )

        assert fetched == 1
        assert failed == 1
        assert "000660" in failed_details
        assert failed_details["000660"] == "no_data"


class TestStep3NameMissing:
    """전종목 목록 조회 결과에서 이름 없음을 구분 (설계서 4.1·4.6)."""

    @pytest.mark.asyncio
    async def test_name_missing_codes_tracked(self):
        from backend.app.services.market_close_pipeline import _step3_parse_confirmed
        mock_state = _mock_state()
        records = [
            _make_record("005930", "삼성전자", "0", True),
            _make_record("000660", "", "0", True),
            _make_record("005935", None, "0", True),
        ]
        confirmed_codes = {"005930", "000660", "005935"}

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            result = await _step3_parse_confirmed("[test]", records, confirmed_codes)

        assert result is not None
        name_map, market_map, name_missing_codes = result
        assert name_map["005930"] == "삼성전자"
        # 이름 없음 종목은 종목코드로 대체하지 않음 (설계서 5.1)
        assert name_map["000660"] == ""
        assert "000660" in name_missing_codes
        assert "005935" in name_missing_codes
        assert "005930" not in name_missing_codes


class TestMarkFailedStocksInMemory:
    """실패 종목 메모리 표시 — 이전 확정값이 최신 자료처럼 남지 않도록 (설계서 4.3·4.4)."""

    def test_failed_stock_marked_with_cleared_date(self):
        from backend.app.services.market_close_pipeline import _mark_failed_stocks_in_memory
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"name": "삼성전자", "date": "20250105", "cur_price": 50000, "status": "active"},
            "000660": {"name": "SK하이닉스", "date": "20250105", "cur_price": 100000, "status": "active"},
        }
        failed_details = {"000660": "fetch_failed"}

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            _mark_failed_stocks_in_memory(failed_details)

        # 실패 종목 — date 비움 (최신 자료로 오인 방지)
        assert mock_state.master_stocks_cache["000660"]["date"] == ""
        # 정상 종목 — 자료 보존 (설계서 4.3 — 부분 실패 때문에 삭제하지 않음)
        assert mock_state.master_stocks_cache["005930"]["date"] == "20250105"

    def test_nonexistent_stock_skipped(self):
        from backend.app.services.market_close_pipeline import _mark_failed_stocks_in_memory
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"name": "삼성전자", "date": "20250105"},
        }
        failed_details = {"999999": "fetch_failed"}

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            _mark_failed_stocks_in_memory(failed_details)

        # 캐시에 없는 종목 — 오류 없이 통과
        assert mock_state.master_stocks_cache["005930"]["date"] == "20250105"


class TestRunConfirmedPipelinePartialSuccess:
    """부분 성공 시 실패 종목 메모리 표시 — 정상 종목 보존·실패 종목 차단 (설계서 4.3)."""

    @pytest.mark.asyncio
    async def test_partial_success_marks_failed_and_preserves_normal(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"name": "삼성전자", "date": "20250104", "cur_price": 49000, "status": "active"},
            "000660": {"name": "SK하이닉스", "date": "20250104", "cur_price": 99000, "status": "active"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value="token123")
        mock_sector = MagicMock()
        records = [
            _make_record("005930", "삼성전자", "0", True),
            _make_record("000660", "SK하이닉스", "0", True),
        ]
        mock_sector.fetch_all_stocks = AsyncMock(return_value=records)
        # 005930만 정상, 000660은 응답일 불일치
        mock_sector.fetch_all_stocks_daily_confirmed = AsyncMock(return_value={
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2", "dt": "20250105", "response_date": "20250105"},
            "000660": {"close": 100000, "value": 3000000, "high": 101000, "volume": 30000, "change": 2000, "rate": 2.0, "sign": "2", "dt": "20250104", "response_date": "20250104"},
        })
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.core.stock_filter.evaluate_stock_filter", side_effect=lambda raw, code: _make_eval(code, excluded=False)), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.core.stock_classification_data.sync_sector_from_custom_sectors", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._update_layout_cache", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline._apply_confirmed_to_memory", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.execute_unified_rolling_and_save", new_callable=AsyncMock, return_value=True), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock), \
             patch("backend.app.services.market_close_pipeline.get_previous_trading_day_str", return_value="20250105"), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"):
            result = await _run_confirmed_pipeline("test")

        # 부분 성공 — fetched=1, failed=1 (전체 성공으로 표시하지 않음)
        assert result["fetched"] == 1
        assert result["failed"] == 1
        assert result["cached"] is True
        # 실패 종목(000660) — date 비움 (최신 자료로 오인 방지)
        assert mock_state.master_stocks_cache["000660"]["date"] == ""
