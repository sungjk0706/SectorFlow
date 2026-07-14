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
    _save_confirmed_cache,
    _run_confirmed_pipeline,
    fetch_unified_confirmed_data,
    fetch_confirmed_data_only,
    fetch_5d_data_only,
    _update_layout_cache,
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
    ms.confirmed_refresh_message = ""
    ms.confirmed_done = False
    ms.latest_filter_summary_meta = ""
    ms.connector_manager = None
    ms.active_connector = None
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state):
            result = await remove_krx_only_stocks()
            assert result == {"removed": 0, "failed": 0, "skipped": True}

    @pytest.mark.asyncio
    async def test_no_krx_codes_returns_empty(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_ws)
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=[]):
            result = await remove_krx_only_stocks()
            assert result == {"removed": 0, "failed": 0, "skipped": False}

    @pytest.mark.asyncio
    async def test_remove_with_ack_success(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.supports_ack.return_value = True
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]), \
             patch("backend.app.services.market_close_pipeline.get_ws_subscribe_code", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.build_0b_remove_payloads", return_value=[{"test": True}]), \
             patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", new_callable=AsyncMock, return_value=(True, "")):
            result = await remove_krx_only_stocks()
            assert result["removed"] == 1
            assert result["failed"] == 0
            assert result["skipped"] is False

    @pytest.mark.asyncio
    async def test_remove_without_ack_success(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.supports_ack.return_value = False
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]), \
             patch("backend.app.services.market_close_pipeline.get_ws_subscribe_code", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.build_0b_remove_payloads", return_value=[{"test": True}]), \
             patch("backend.app.services.engine_ws._ws_send_remove_fire_and_forget", new_callable=AsyncMock, return_value=True):
            result = await remove_krx_only_stocks()
            assert result["removed"] == 1
            assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_remove_failure_counts_failed(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.supports_ack.return_value = True
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]), \
             patch("backend.app.services.market_close_pipeline.get_ws_subscribe_code", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.build_0b_remove_payloads", return_value=[{"test": True}]), \
             patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", new_callable=AsyncMock, return_value=(False, "ERR")):
            result = await remove_krx_only_stocks()
            assert result["removed"] == 0
            assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_remove_exception_counts_failed(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_ws.supports_ack.return_value = True
        mock_state = _mock_state(connector_manager=mock_ws)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]), \
             patch("backend.app.services.market_close_pipeline.get_ws_subscribe_code", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.build_0b_remove_payloads", return_value=[{"test": True}]), \
             patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", new_callable=AsyncMock, side_effect=Exception("boom")):
            result = await remove_krx_only_stocks()
            assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_no_payloads_returns_empty(self):
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_ws)
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.services.market_close_pipeline._get_krx_only_codes", return_value=["005930"]), \
             patch("backend.app.services.market_close_pipeline.get_ws_subscribe_code", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline.build_0b_remove_payloads", return_value=[]):
            result = await remove_krx_only_stocks()
            assert result == {"removed": 0, "failed": 0, "skipped": False}


# ── execute_unified_rolling_and_save ──────────────────────────────────────────

class TestExecuteUnifiedRollingAndSave:
    @pytest.mark.asyncio
    async def test_empty_confirmed_returns_true(self):
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"):
            result = await execute_unified_rolling_and_save({})
            assert result is True
            mock_conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_confirmed_data(self):
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=cursor)
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자"}}
        confirmed = {
            "005930": {"cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000, "high_price": 51000},
        }
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await execute_unified_rolling_and_save(confirmed, name_map={"005930": "삼성전자"})
            assert result is True
            mock_conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_rolls_back_and_reraises(self):
        mock_conn = _mock_conn()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"):
            with pytest.raises(Exception, match="DB error"):
                await execute_unified_rolling_and_save({"005930": {"cur_price": 50000}})
            mock_conn.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_same_day_upsert_no_duplicate(self):
        """같은 날 재실행 시 INSERT OR REPLACE로 당일 행 덮어쓰기 (P10/P22 — 세로 행 구조).

        API가 반환한 일봉의 실제 dt(=qry_dt와 동일)를 stock_5d_bars.dt로 사용.
        """
        mock_conn = _mock_conn()
        cursor = MagicMock()
        # 1st fetchall: stock_5d_bars existing rows (당일 + 직전일들), 2nd fetchall: master_stocks_table mkt rows
        existing_bars = [
            {"code": "005930", "trade_amount": 999, "high_price": 9999},  # 당일 (qry_dt와 같은 날)
            {"code": "005930", "trade_amount": 200, "high_price": 2000},  # 직전1일
            {"code": "005930", "trade_amount": 300, "high_price": 3000},  # 직전2일
        ]
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자"}}
        confirmed = {
            "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
        }
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250106")
            assert result is True
            # 1st executemany: stock_5d_bars INSERT OR REPLACE (당일 1행)
            bars_call = mock_conn.executemany.call_args_list[0]
            bars_params = bars_call.args[1][0]
            # (code, dt, trade_amount, high_price) — dt는 API 실제 거래일 우선
            assert bars_params[0] == "005930"
            assert bars_params[1] == "20250106"  # dt = detail.dt (API 실제 거래일 = qry_dt)
            assert bars_params[2] == 555   # trade_amount = 새 당일 값
            assert bars_params[3] == 8888  # high_price = 새 당일 고가

    @pytest.mark.asyncio
    async def test_new_day_insert_new_row(self):
        """새 거래일 실행 시 새 행 추가 — 기존 행은 그대로 유지 (세로 행 구조, rolling 제거).

        API가 반환한 일봉의 실제 dt(=qry_dt와 동일)를 stock_5d_bars.dt로 사용.
        """
        mock_conn = _mock_conn()
        cursor = MagicMock()
        # 기존 행: 직전1일~직전3일 (당일 행 없음)
        existing_bars = [
            {"code": "005930", "trade_amount": 200, "high_price": 2000},
            {"code": "005930", "trade_amount": 300, "high_price": 3000},
        ]
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자"}}
        confirmed = {
            "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 999, "high_price": 9999},
        }
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250106")
            assert result is True
            bars_call = mock_conn.executemany.call_args_list[0]
            bars_params = bars_call.args[1][0]
            assert bars_params[0] == "005930"
            assert bars_params[1] == "20250106"  # dt = detail.dt (API 실제 거래일 = qry_dt)
            assert bars_params[2] == 999   # trade_amount = 새 당일 값
            assert bars_params[3] == 9999  # high_price = 새 당일 고가

    @pytest.mark.asyncio
    async def test_api_returns_previous_day_uses_api_dt_not_qry_dt(self):
        """장마감 전 실행 시 API가 어제 일봉을 latest로 반환하는 경우 회귀 방지 (P10/P22).

        qry_dt=20250106(달력 오늘)이지만 API가 아직 20250105(직전 거래일) 일봉을
        latest로 반환하면, stock_5d_bars에는 20250105 행으로 저장되어야 함.
        과거 버그: qry_dt(달력 오늘)를 그대로 dt로 써서 20250105 값을 20250106 행에
        기록 → 20250105 행과 동일값 중복 발생.
        """
        mock_conn = _mock_conn()
        cursor = MagicMock()
        # 기존 행: 20250105(직전 거래일) 이미 존재
        existing_bars = [
            {"code": "005930", "trade_amount": 200, "high_price": 2000},
        ]
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"name": "삼성전자"}}
        # API가 20250105 일봉을 latest로 반환 → dt="20250105"
        confirmed = {
            "005930": {"dt": "20250105", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 200, "high_price": 2000},
        }
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await execute_unified_rolling_and_save(confirmed, qry_dt="20250106")
            assert result is True
            bars_call = mock_conn.executemany.call_args_list[0]
            bars_params = bars_call.args[1][0]
            assert bars_params[0] == "005930"
            # 핵심: dt는 qry_dt(20250106)가 아니라 API 실제 거래일(20250105)이어야 함
            assert bars_params[1] == "20250105"  # detail.dt 우선 — 중복 행 생성 차단
            assert bars_params[2] == 200   # trade_amount
            assert bars_params[3] == 2000  # high_price


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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, side_effect=Exception("DB fail")), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await _apply_confirmed_to_memory(confirmed, {})
            assert result == 1


# ── _run_post_confirmed_pipeline ──────────────────────────────────────────────

class TestRunPostConfirmedPipeline:
    @pytest.mark.asyncio
    async def test_calls_save_confirmed_cache(self):
        with patch("backend.app.services.market_close_pipeline._save_confirmed_cache", new_callable=AsyncMock) as mock_save:
            await _run_post_confirmed_pipeline()
            mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("backend.app.services.market_close_pipeline._save_confirmed_cache", new_callable=AsyncMock, side_effect=Exception("boom")):
            await _run_post_confirmed_pipeline()


# ── _save_confirmed_cache ─────────────────────────────────────────────────────

class TestSaveConfirmedCache:
    @pytest.mark.asyncio
    async def test_empty_cache_returns_false(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        with patch("backend.app.services.market_close_pipeline.state", mock_state):
            result = await _save_confirmed_cache()
            assert result is False

    @pytest.mark.asyncio
    async def test_no_active_rows_returns_false(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "inactive", "name": "삼성전자"},
        }
        with patch("backend.app.services.market_close_pipeline.state", mock_state):
            result = await _save_confirmed_cache()
            assert result is False

    @pytest.mark.asyncio
    async def test_save_success(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 5000000, "avg_5d_trade_amount": 4000000, "high_5d_price": 51000, "sector": "반도체"},
        }
        mock_conn = _mock_conn()
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await _save_confirmed_cache()
            assert result is True
            mock_conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_with_skip_codes(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자", "cur_price": 50000, "change": 0, "change_rate": 0.0, "trade_amount": 0, "avg_5d_trade_amount": 0, "high_5d_price": 0, "sector": "반도체"},
            "000660": {"status": "active", "name": "SK하이닉스", "cur_price": 100000, "change": 0, "change_rate": 0.0, "trade_amount": 0, "avg_5d_trade_amount": 0, "high_5d_price": 0, "sector": "반도체"},
        }
        mock_conn = _mock_conn()
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await _save_confirmed_cache(skip_codes={"005930"})
            assert result is True

    @pytest.mark.asyncio
    async def test_save_with_eligible_codes(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자", "cur_price": 50000, "change": 0, "change_rate": 0.0, "trade_amount": 0, "avg_5d_trade_amount": 0, "high_5d_price": 0, "sector": "반도체"},
            "000660": {"status": "active", "name": "SK하이닉스", "cur_price": 100000, "change": 0, "change_rate": 0.0, "trade_amount": 0, "avg_5d_trade_amount": 0, "high_5d_price": 0, "sector": "반도체"},
        }
        mock_conn = _mock_conn()
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x):
            result = await _save_confirmed_cache(eligible_codes={"005930"})
            assert result is True

    @pytest.mark.asyncio
    async def test_db_exception_returns_true_with_warning(self):
        # _save_confirmed_cache catches DB exception in inner try/except and returns True
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자", "cur_price": 50000, "change": 0, "change_rate": 0.0, "trade_amount": 0, "avg_5d_trade_amount": 0, "high_5d_price": 0, "sector": "반도체"},
        }
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, side_effect=Exception("DB fail")), \
             patch("backend.app.services.market_close_pipeline.get_current_trading_day_str", return_value="20250106"):
            result = await _save_confirmed_cache()
            # Inner except catches the DB error, logs warning, and returns True
            assert result is True


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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state):
            result = await _run_confirmed_pipeline("test")
            assert result == {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

    @pytest.mark.asyncio
    async def test_scheduler_off_returns_skipped(self):
        mock_state = _mock_state()
        mock_state.integrated_system_settings_cache["scheduler_market_close_on"] = False
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
            "005930": {"close": 50000, "value": 5000000, "high": 51000, "volume": 100000, "change": 1000, "rate": 2.0, "sign": "2"},
            "000660": {"close": 100000, "value": 3000000, "high": 101000, "volume": 30000, "change": 2000, "rate": 2.0, "sign": "2"},
        })
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
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
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.services.engine_account_notify._rebuild_layout_cache"), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.engine_lifecycle.broadcast_engine_status", new_callable=AsyncMock) as mock_broadcast:
            await _run_confirmed_pipeline("test")
            # Token was registered and then cleaned up in finally
            assert "kiwoom" not in mock_state.broker_tokens
            # broadcast_engine_status called twice: once for register, once for cleanup
            assert mock_broadcast.await_count == 2


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

class TestFetch5dDataOnly:
    @pytest.mark.asyncio
    async def test_already_running_returns_skipped(self):
        mock_state = _mock_state()
        mock_state.confirmed_refresh_running_5d = True
        with patch("backend.app.services.market_close_pipeline.state", mock_state):
            result = await fetch_5d_data_only()
            assert result == {"fetched": 0, "failed": 0, "cached": False, "skipped": True}

    @pytest.mark.asyncio
    async def test_no_active_codes_returns_empty(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {}
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"):
            result = await fetch_5d_data_only()
            assert result == {"fetched": 0, "failed": 0, "cached": False}

    @pytest.mark.asyncio
    async def test_full_5d_download_success(self):
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
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        # 최근 5개 거래일 mock — 오래된 행 정리 로직 검증용
        from datetime import date
        recent_5_days = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"), \
             patch("backend.app.core.trading_calendar.get_recent_trading_days", return_value=recent_5_days), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await fetch_5d_data_only()
            assert result["fetched"] == 2
            assert result["failed"] == 0
            # 오래된 행 정리 검증 — DELETE FROM stock_5d_bars WHERE dt < '20250102' 호출 확인
            delete_calls = [
                call for call in mock_conn.execute.call_args_list
                if "DELETE FROM stock_5d_bars" in str(call)
            ]
            assert len(delete_calls) == 1
            assert "20250102" in str(delete_calls[0])

    @pytest.mark.asyncio
    async def test_5d_api_returns_none(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {
            "005930": {"status": "active", "name": "삼성전자"},
        }
        mock_auth = MagicMock()
        mock_auth.get_access_token = AsyncMock(return_value=None)
        mock_sector = MagicMock()
        mock_sector.fetch_stock_5day_data = AsyncMock(return_value=None)
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"), \
             patch("asyncio.sleep", new_callable=AsyncMock):
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
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"), \
             patch("asyncio.sleep", new_callable=AsyncMock):
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
        mock_conn = _mock_conn()
        mock_lock = MagicMock()
        mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
        mock_lock.__aexit__ = AsyncMock(return_value=None)
        with patch("backend.app.services.market_close_pipeline.state", mock_state), \
             patch("backend.app.core.broker_registry._create_provider", side_effect=lambda kind, *a, **kw: mock_auth if kind == "auth" else mock_sector), \
             patch("backend.app.services.market_close_pipeline._broadcast_confirmed_progress"), \
             patch("backend.app.db.database.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.db.database.get_db_lock", return_value=mock_lock), \
             patch("backend.app.services.market_close_pipeline._base_stk_cd", side_effect=lambda x: x), \
             patch("backend.app.services.market_close_pipeline._run_post_confirmed_pipeline", new_callable=AsyncMock), \
             patch("backend.app.web.routes.stock_classification.broadcast_stock_classification_changed", new_callable=AsyncMock), \
             patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_stocks_refresh", new_callable=AsyncMock), \
             patch("backend.app.core.trading_calendar.get_kst_today_str", return_value="20250106"), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await fetch_5d_data_only()
            assert result["fetched"] == 0
            assert result["failed"] == 1
