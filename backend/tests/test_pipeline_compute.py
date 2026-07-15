"""pipeline_compute.py 단위 테스트 — Compute Engine 틱 처리, 제어 신호, 수신율 계산 검증.

hang 방지 원칙:
- 실제 asyncio.Queue 사용 금지 → mock으로 대체
- asyncio.create_task / asyncio.gather / asyncio.sleep 사용 금지 → mock으로 대체
- engine_state.state를 mock으로 대체
"""
from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, DEFAULT, MagicMock, patch

def _close_coro(*args, **kwargs):
    """mock에 전달된 코루틴을 close하여 RuntimeWarning 방지."""
    for arg in args:
        if asyncio.iscoroutine(arg):
            arg.close()
    return DEFAULT


# Initialize queues before importing pipeline_compute (module-level get_broadcast_queue call)
from backend.app.services.core_queues import initialize_queues  # noqa: E402
initialize_queues()


from backend.app.pipelines.pipeline_compute import (  # noqa: E402
    _has_any_realtime_data,
    _calculate_receive_rate,
    get_current_receive_rate,
    _send_receive_rate,
    _process_control_signal,
    _handle_config_update,
    _handle_sector_recompute,
    _process_tick_data,
    _handle_real_tick,
    _handle_real_0j_tick,
    _handle_real_01_tick,
    _handle_real_0d_tick,
    _handle_real_pgm_tick,
    _check_realtime_latency,
    start_compute_loop,
    stop_compute_loop,
    _compute_loop_impl,
    _sector_recompute_loop_impl,
    is_sector_threshold_passed,
    reset_sector_threshold,
    mark_sector_threshold_passed,
)
import backend.app.pipelines.pipeline_compute as compute_mod  # noqa: E402


# ── _has_any_realtime_data ────────────────────────────────────────────────────

class TestHasAnyRealtimeData:
    def test_all_none_returns_false(self):
        entry = {"change_rate": None, "trade_amount": None}
        assert _has_any_realtime_data(entry) is False

    def test_change_rate_set_returns_true(self):
        entry = {"change_rate": 1.5, "trade_amount": None}
        assert _has_any_realtime_data(entry) is True

    def test_trade_amount_set_returns_true(self):
        entry = {"change_rate": None, "trade_amount": 1000000}
        assert _has_any_realtime_data(entry) is True

    def test_both_set_returns_true(self):
        entry = {"change_rate": 2.0, "trade_amount": 500000}
        assert _has_any_realtime_data(entry) is True

    def test_missing_fields_returns_false(self):
        entry = {}
        assert _has_any_realtime_data(entry) is False

    def test_zero_is_not_none(self):
        entry = {"change_rate": 0, "trade_amount": 0}
        assert _has_any_realtime_data(entry) is True


# ── get_current_receive_rate / _send_receive_rate ─────────────────────────────

class TestReceiveRate:
    def test_get_current_receive_rate_returns_copy(self):
        compute_mod._current_receive_rate = {
            "krx": {"received": 5, "total": 10, "pct": 50.0},
            "nxt": {"received": 3, "total": 8, "pct": 37.5},
        }
        result = get_current_receive_rate()
        assert result == {
            "krx": {"received": 5, "total": 10, "pct": 50.0},
            "nxt": {"received": 3, "total": 8, "pct": 37.5},
        }
        # Verify it's a copy
        result["krx"]["received"] = 999
        assert compute_mod._current_receive_rate["krx"]["received"] == 5

    @pytest.mark.asyncio
    async def test_send_receive_rate_puts_to_queue(self):
        # 3단계: 분리 구조 rate 전달 — module-level broadcast_queue 사용
        mock_bq = AsyncMock()
        mock_bq.put = AsyncMock()
        with patch.object(compute_mod, "broadcast_queue", mock_bq):
            rate = {
                "krx": {"received": 3, "total": 10, "pct": 30.0},
                "nxt": {"received": 2, "total": 5, "pct": 40.0},
            }
            await _send_receive_rate(rate)
            mock_bq.put.assert_awaited_once()
            call_args = mock_bq.put.call_args.args[0]
            assert call_args["type"] == "receive-rate"
            assert call_args["data"]["krx"]["received"] == 3
            assert call_args["data"]["nxt"]["received"] == 2

    @pytest.mark.asyncio
    async def test_send_receive_rate_direct(self):
        mock_bq = AsyncMock()
        mock_bq.put = AsyncMock()
        with patch.object(compute_mod, "broadcast_queue", mock_bq):
            rate = {
                "krx": {"received": 3, "total": 10, "pct": 30.0},
                "nxt": {"received": 2, "total": 5, "pct": 40.0},
            }
            await _send_receive_rate(rate)
            mock_bq.put.assert_awaited_once()
            call_args = mock_bq.put.call_args.args[0]
            assert call_args["type"] == "receive-rate"
            assert call_args["data"]["krx"]["pct"] == 30.0
            assert call_args["data"]["krx"]["received"] == 3
            assert call_args["data"]["krx"]["total"] == 10
            assert call_args["data"]["nxt"]["pct"] == 40.0
            assert call_args["data"]["nxt"]["received"] == 2
            assert call_args["data"]["nxt"]["total"] == 5


# ── _calculate_receive_rate ───────────────────────────────────────────────────

class TestCalculateReceiveRate:
    @pytest.mark.asyncio
    async def test_empty_codes_returns_early(self):
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock) as mock_inputs:
            mock_inputs.return_value = {"all_codes": [], "krx_codes": [], "nxt_codes": []}
            await _calculate_receive_rate()
            # 양쪽 모두 빈 codes → 0/0/0.0 (비활성 상태)
            assert compute_mod._current_receive_rate["krx"] == {"received": 0, "total": 0, "pct": 0.0}
            assert compute_mod._current_receive_rate["nxt"] == {"received": 0, "total": 0, "pct": 0.0}

    @pytest.mark.asyncio
    async def test_normal_calculation(self):
        # KRX 2종목(1종목 수신), NXT 1종목(1종목 수신) → KRX 50%, NXT 100%
        mock_cache = {
            "005930": {"change_rate": 1.5, "trade_amount": 1000000},  # KRX, 수신
            "000660": {"change_rate": None, "trade_amount": None},    # KRX, 미수신
            "035420": {"change_rate": -0.5, "trade_amount": 500000},  # NXT, 수신
        }
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock) as mock_inputs, \
             patch.object(compute_mod, "state", MagicMock(master_stocks_cache=mock_cache)):
            mock_inputs.return_value = {
                "all_codes": ["005930", "000660", "035420"],
                "krx_codes": ["005930", "000660"],
                "nxt_codes": ["035420"],
            }
            await _calculate_receive_rate()
            assert compute_mod._current_receive_rate["krx"]["received"] == 1
            assert compute_mod._current_receive_rate["krx"]["total"] == 2
            assert abs(compute_mod._current_receive_rate["krx"]["pct"] - 50.0) < 0.1
            assert compute_mod._current_receive_rate["nxt"]["received"] == 1
            assert compute_mod._current_receive_rate["nxt"]["total"] == 1
            assert abs(compute_mod._current_receive_rate["nxt"]["pct"] - 100.0) < 0.1

    @pytest.mark.asyncio
    async def test_no_received_data(self):
        # 모든 종목이 필드 미보유 → 0%
        mock_cache = {
            "005930": {"change_rate": None, "trade_amount": None},
            "000660": {"change_rate": None, "trade_amount": None},
        }
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock) as mock_inputs, \
             patch.object(compute_mod, "state", MagicMock(master_stocks_cache=mock_cache)):
            mock_inputs.return_value = {
                "all_codes": ["005930", "000660"],
                "krx_codes": ["005930", "000660"],
                "nxt_codes": [],
            }
            await _calculate_receive_rate()
            assert compute_mod._current_receive_rate["krx"]["received"] == 0
            assert compute_mod._current_receive_rate["krx"]["pct"] == 0.0
            assert compute_mod._current_receive_rate["nxt"]["received"] == 0
            assert compute_mod._current_receive_rate["nxt"]["total"] == 0

    @pytest.mark.asyncio
    async def test_all_received_data(self):
        # 모든 종목이 필드 보유 → 100% (장마감 후 확정 데이터 반영 상태)
        mock_cache = {
            "005930": {"change_rate": 1.5, "trade_amount": 1000000},
            "000660": {"change_rate": -0.5, "trade_amount": 500000},
        }
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock) as mock_inputs, \
             patch.object(compute_mod, "state", MagicMock(master_stocks_cache=mock_cache)):
            mock_inputs.return_value = {
                "all_codes": ["005930", "000660"],
                "krx_codes": ["005930"],
                "nxt_codes": ["000660"],
            }
            await _calculate_receive_rate()
            assert compute_mod._current_receive_rate["krx"]["received"] == 1
            assert compute_mod._current_receive_rate["krx"]["total"] == 1
            assert abs(compute_mod._current_receive_rate["krx"]["pct"] - 100.0) < 0.1
            assert compute_mod._current_receive_rate["nxt"]["received"] == 1
            assert compute_mod._current_receive_rate["nxt"]["total"] == 1
            assert abs(compute_mod._current_receive_rate["nxt"]["pct"] - 100.0) < 0.1

    @pytest.mark.asyncio
    async def test_missing_entry_in_cache(self):
        # krx_codes에 있으나 cache에 없는 종목은 미수신으로 카운트
        mock_cache = {
            "005930": {"change_rate": 1.5, "trade_amount": 1000000},
        }
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock) as mock_inputs, \
             patch.object(compute_mod, "state", MagicMock(master_stocks_cache=mock_cache)):
            mock_inputs.return_value = {
                "all_codes": ["005930", "000660"],
                "krx_codes": ["005930", "000660"],
                "nxt_codes": [],
            }
            await _calculate_receive_rate()
            assert compute_mod._current_receive_rate["krx"]["received"] == 1
            assert compute_mod._current_receive_rate["krx"]["total"] == 2
            assert abs(compute_mod._current_receive_rate["krx"]["pct"] - 50.0) < 0.1

    @pytest.mark.asyncio
    async def test_nxt_only_window_krx_empty(self):
        # NXT-only 구간: krx_codes가 빈 리스트 → KRX 0/0, NXT만 산출
        mock_cache = {
            "035420": {"change_rate": -0.5, "trade_amount": 500000},
            "005930": {"change_rate": None, "trade_amount": None},
        }
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock) as mock_inputs, \
             patch.object(compute_mod, "state", MagicMock(master_stocks_cache=mock_cache)):
            mock_inputs.return_value = {
                "all_codes": ["035420", "005930"],
                "krx_codes": [],
                "nxt_codes": ["035420", "005930"],
            }
            await _calculate_receive_rate()
            assert compute_mod._current_receive_rate["krx"]["received"] == 0
            assert compute_mod._current_receive_rate["krx"]["total"] == 0
            assert compute_mod._current_receive_rate["krx"]["pct"] == 0.0
            assert compute_mod._current_receive_rate["nxt"]["received"] == 1
            assert compute_mod._current_receive_rate["nxt"]["total"] == 2
            assert abs(compute_mod._current_receive_rate["nxt"]["pct"] - 50.0) < 0.1

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs", new_callable=AsyncMock, side_effect=Exception("boom")):
            await _calculate_receive_rate()


# ── _process_control_signal ───────────────────────────────────────────────────

class TestProcessControlSignal:
    @pytest.mark.asyncio
    async def test_update_config(self):
        mock_bq = AsyncMock()
        with patch("backend.app.pipelines.pipeline_compute._handle_config_update", new_callable=AsyncMock) as mock_handler:
            await _process_control_signal({"type": "UPDATE_CONFIG", "payload": {"key": "val"}}, mock_bq)
            mock_handler.assert_awaited_once_with({"key": "val"}, mock_bq)

    @pytest.mark.asyncio
    async def test_recompute_sector(self):
        mock_bq = AsyncMock()
        with patch("backend.app.pipelines.pipeline_compute._handle_sector_recompute", new_callable=AsyncMock) as mock_handler:
            await _process_control_signal({"type": "RECOMPUTE_SECTOR"}, mock_bq)
            mock_handler.assert_awaited_once_with(mock_bq)

    @pytest.mark.asyncio
    async def test_sector_recompute_with_code(self):
        mock_bq = AsyncMock()
        with patch("backend.app.services.engine_sector_confirm.request_sector_recompute") as mock_req:
            await _process_control_signal({"type": "sector_recompute", "code": "005930"}, mock_bq)
            mock_req.assert_called_once_with("005930")

    @pytest.mark.asyncio
    async def test_sector_recompute_no_code_skips(self):
        mock_bq = AsyncMock()
        with patch("backend.app.services.engine_sector_confirm.request_sector_recompute") as mock_req:
            await _process_control_signal({"type": "sector_recompute"}, mock_bq)
            mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_dynamic_reg(self):
        mock_bq = AsyncMock()
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {}, "000660": {}}
        from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()
        _PENDING_REG_CODES.update({"005930", "000660"})  # 대기 중 상태 시뮬레이션
        with patch("backend.app.services.engine_ws.subscribe_dynamic_data", new_callable=AsyncMock) as mock_sub, \
             patch("backend.app.services.engine_state.state", mock_state):
            await _process_control_signal({"type": "DYNAMIC_REG", "payload": {"codes": ["005930", "000660"]}}, mock_bq)
            mock_sub.assert_awaited_once_with(["005930", "000660"])
            assert mock_state.master_stocks_cache["005930"]["_subscribed_dynamic"] is True
            assert mock_state.master_stocks_cache["000660"]["_subscribed_dynamic"] is True
            # 구독 완료 후 대기 세트에서 제거됨 (P10 SSOT)
            assert "005930" not in _PENDING_REG_CODES
            assert "000660" not in _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()

    @pytest.mark.asyncio
    async def test_dynamic_unreg(self):
        mock_bq = AsyncMock()
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"_subscribed_dynamic": True}, "000660": {"_subscribed_dynamic": True}}
        from backend.app.services.engine_sector_confirm import _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()
        _PENDING_REG_CODES.add("005930")  # 005930이 대기 중이었을 수 있음
        with patch("backend.app.services.engine_ws.unsubscribe_dynamic_data", new_callable=AsyncMock) as mock_unsub, \
             patch("backend.app.services.engine_state.state", mock_state):
            await _process_control_signal({"type": "DYNAMIC_UNREG", "payload": {"codes": ["005930"]}}, mock_bq)
            mock_unsub.assert_awaited_once_with(["005930"])
            assert "_subscribed_dynamic" not in mock_state.master_stocks_cache["005930"]
            assert "_subscribed_dynamic" in mock_state.master_stocks_cache["000660"]
            # 해지 후 대기 세트에서도 제거됨
            assert "005930" not in _PENDING_REG_CODES
        _PENDING_REG_CODES.clear()

    @pytest.mark.asyncio
    async def test_unknown_signal_logs_warning(self):
        mock_bq = AsyncMock()
        await _process_control_signal({"type": "UNKNOWN"}, mock_bq)

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        mock_bq = AsyncMock()
        with patch("backend.app.pipelines.pipeline_compute._handle_config_update", new_callable=AsyncMock, side_effect=Exception("boom")):
            await _process_control_signal({"type": "UPDATE_CONFIG", "payload": {}}, mock_bq)


# ── _handle_config_update ─────────────────────────────────────────────────────

class TestHandleConfigUpdate:
    @pytest.mark.asyncio
    async def test_calls_notify_header_refresh(self):
        mock_bq = AsyncMock()
        with patch("backend.app.services.engine_account_notify.notify_desktop_header_refresh", new_callable=AsyncMock) as mock_notify:
            await _handle_config_update({}, mock_bq)
            mock_notify.assert_awaited_once()


# ── _handle_sector_recompute ──────────────────────────────────────────────────

class TestHandleSectorRecompute:
    @pytest.mark.asyncio
    async def test_calls_recompute(self):
        mock_bq = AsyncMock()
        with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock) as mock_recompute:
            await _handle_sector_recompute(mock_bq)
            mock_recompute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        mock_bq = AsyncMock()
        with patch("backend.app.services.sector_data_provider.recompute_sector_summary_now", new_callable=AsyncMock, side_effect=Exception("boom")):
            await _handle_sector_recompute(mock_bq)


# ── _process_tick_data ────────────────────────────────────────────────────────

class TestProcessTickData:
    @pytest.mark.asyncio
    async def test_real_trnm_calls_handle_real_tick(self):
        mock_bq = AsyncMock()
        data = {"trnm": "REAL", "data": [{"type": "01"}]}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_tick", new_callable=AsyncMock) as mock_handler:
            await _process_tick_data(data, mock_bq)
            mock_handler.assert_awaited_once_with(data, mock_bq)

    @pytest.mark.asyncio
    async def test_non_real_trnm_does_nothing(self):
        mock_bq = AsyncMock()
        data = {"trnm": "OTHER"}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_tick", new_callable=AsyncMock) as mock_handler:
            await _process_tick_data(data, mock_bq)
            mock_handler.assert_not_awaited()


# ── _handle_real_tick ─────────────────────────────────────────────────────────

class TestHandleRealTick:
    @pytest.mark.asyncio
    async def test_list_data(self):
        mock_bq = AsyncMock()
        data = {"data": [{"type": "01", "values": {}}, {"type": "0d", "values": {}}]}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_01_tick", new_callable=AsyncMock) as mock_01, \
             patch("backend.app.pipelines.pipeline_compute._handle_real_0d_tick", new_callable=AsyncMock) as mock_0d, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", side_effect=["01", "0d"]):
            await _handle_real_tick(data, mock_bq)
            assert mock_01.await_count == 1
            assert mock_0d.await_count == 1

    @pytest.mark.asyncio
    async def test_dict_data_wrapped_in_list(self):
        mock_bq = AsyncMock()
        data = {"data": {"type": "01", "values": {}}}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_01_tick", new_callable=AsyncMock) as mock_01, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="01"):
            await _handle_real_tick(data, mock_bq)
            mock_01.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_dict_data_empty_items(self):
        mock_bq = AsyncMock()
        data = {"data": "invalid"}
        await _handle_real_tick(data, mock_bq)

    @pytest.mark.asyncio
    async def test_non_dict_item_skipped(self):
        mock_bq = AsyncMock()
        data = {"data": ["not_a_dict", {"type": "01", "values": {}}]}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_01_tick", new_callable=AsyncMock) as mock_01, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="01"):
            await _handle_real_tick(data, mock_bq)
            mock_01.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_0j_tick_calls_handler(self):
        mock_bq = AsyncMock()
        data = {"data": {"type": "0j", "values": {"10": "2500"}}}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_0j_tick", new_callable=AsyncMock) as mock_0j, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="0j"):
            await _handle_real_tick(data, mock_bq)
            mock_0j.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pgm_tick_calls_handler(self):
        mock_bq = AsyncMock()
        data = {"data": {"type": "PGM", "values": {"tval": "1000"}}}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_pgm_tick", new_callable=AsyncMock) as mock_pgm, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="PGM"):
            await _handle_real_tick(data, mock_bq)
            mock_pgm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_type_00_calls_handle_real_00(self):
        mock_bq = AsyncMock()
        data = {"data": {"type": "00", "values": {"90001": "005930"}}}
        with patch("backend.app.services.engine_ws_dispatch._handle_real_00", new_callable=AsyncMock) as mock_00, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="00"):
            await _handle_real_tick(data, mock_bq)
            mock_00.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_type_04_calls_handle_real_balance(self):
        mock_bq = AsyncMock()
        data = {"data": {"type": "04", "values": {"90001": "005930"}}}
        with patch("backend.app.services.engine_ws_dispatch._handle_real_balance", new_callable=AsyncMock) as mock_bal, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="04"):
            await _handle_real_tick(data, mock_bq)
            mock_bal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_type_80_calls_handle_real_balance(self):
        mock_bq = AsyncMock()
        data = {"data": {"type": "80", "values": {"90001": "005930"}}}
        with patch("backend.app.services.engine_ws_dispatch._handle_real_balance", new_callable=AsyncMock) as mock_bal, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="80"):
            await _handle_real_tick(data, mock_bq)
            mock_bal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        mock_bq = AsyncMock()
        data = {"data": None}
        with patch("backend.app.services.engine_ws_parsing._normalize_real_type", side_effect=Exception("boom")):
            await _handle_real_tick(data, mock_bq)


# ── _handle_real_0j_tick ──────────────────────────────────────────────────────

class TestHandleReal0jTick:
    @pytest.mark.asyncio
    async def test_valid_tick_broadcasts(self):
        item = {"item": "001"}
        vals = {"10": "2500.5", "11": "10.5", "12": "0.5", "25": "2"}
        with patch("backend.app.services.engine_account_notify.notify_index_data", new_callable=AsyncMock) as mock_notify:
            await _handle_real_0j_tick(item, vals)
            mock_notify.assert_awaited_once_with("001", "2500.5", "10.5", "0.5", "2")

    @pytest.mark.asyncio
    async def test_empty_upcode_returns(self):
        item = {"item": ""}
        vals = {"10": "2500"}
        with patch("backend.app.services.engine_account_notify.notify_index_data", new_callable=AsyncMock) as mock_notify:
            await _handle_real_0j_tick(item, vals)
            mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_jisu_returns(self):
        item = {"item": "001"}
        vals = {"10": "", "11": "10", "12": "0.5", "25": "2"}
        with patch("backend.app.services.engine_account_notify.notify_index_data", new_callable=AsyncMock) as mock_notify:
            await _handle_real_0j_tick(item, vals)
            mock_notify.assert_not_awaited()


# ── _handle_real_0d_tick ──────────────────────────────────────────────────────

class TestHandleReal0dTick:
    @pytest.mark.asyncio
    async def test_subscribed_dynamic_calls_notify(self):
        item = {"item": "005930"}
        vals = {"125": "1000", "121": "800"}
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"_subscribed_dynamic": True}}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_int", side_effect=[1000, 800]), \
             patch("backend.app.services.engine_account_notify.notify_orderbook_update", new_callable=AsyncMock) as mock_notify, \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            await _handle_real_0d_tick(item, vals, AsyncMock())
            mock_notify.assert_awaited_once_with("005930", 1000, 800)

    @pytest.mark.asyncio
    async def test_not_subscribed_dynamic_skips(self):
        item = {"item": "005930"}
        vals = {"125": "1000", "121": "800"}
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"_subscribed_dynamic": False}}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_int", side_effect=[1000, 800]), \
             patch("backend.app.services.engine_account_notify.notify_orderbook_update", new_callable=AsyncMock) as mock_notify, \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            await _handle_real_0d_tick(item, vals, AsyncMock())
            mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_raw_cd_returns(self):
        item = {"item": ""}
        vals = {}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value=""):
            await _handle_real_0d_tick(item, vals, AsyncMock())

    @pytest.mark.asyncio
    async def test_negative_bid_ask_returns(self):
        item = {"item": "005930"}
        vals = {"125": "-1", "121": "100"}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_int", side_effect=[-1, 100]):
            await _handle_real_0d_tick(item, vals, AsyncMock())


# ── _handle_real_pgm_tick ─────────────────────────────────────────────────────

class TestHandleRealPgmTick:
    @pytest.mark.asyncio
    async def test_subscribed_dynamic_calls_notify(self):
        item = {"item": "005930"}
        vals = {"tval": "5000"}
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"_subscribed_dynamic": True}}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_account_notify.notify_program_update", new_callable=AsyncMock) as mock_notify, \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            await _handle_real_pgm_tick(item, vals, AsyncMock())
            mock_notify.assert_awaited_once_with("005930", 5000)

    @pytest.mark.asyncio
    async def test_not_subscribed_dynamic_skips(self):
        item = {"item": "005930"}
        vals = {"tval": "5000"}
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {}}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_account_notify.notify_program_update", new_callable=AsyncMock) as mock_notify, \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            await _handle_real_pgm_tick(item, vals, AsyncMock())
            mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_tval_defaults_to_zero(self):
        item = {"item": "005930"}
        vals = {"tval": "not_a_number"}
        mock_state = MagicMock()
        mock_state.master_stocks_cache = {"005930": {"_subscribed_dynamic": True}}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_account_notify.notify_program_update", new_callable=AsyncMock) as mock_notify, \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            await _handle_real_pgm_tick(item, vals, AsyncMock())
            mock_notify.assert_awaited_once_with("005930", 0)

    @pytest.mark.asyncio
    async def test_no_raw_cd_returns(self):
        item = {"item": ""}
        vals = {"tval": "100"}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value=""):
            await _handle_real_pgm_tick(item, vals, AsyncMock())


# ── _check_realtime_latency ───────────────────────────────────────────────────

class TestCheckRealtimeLatency:
    def test_under_50ms_no_flag(self):
        mock_state = MagicMock()
        mock_state.realtime_latency_exceeded = False
        with patch("backend.app.services.engine_ws_dispatch.state", mock_state):
            _check_realtime_latency(int(time.time() * 1000))
            assert mock_state.realtime_latency_exceeded is False

    def test_over_200ms_sets_flag(self):
        mock_state = MagicMock()
        mock_state.realtime_latency_exceeded = False
        old_ts = int(time.time() * 1000) - 250
        with patch("backend.app.services.engine_ws_dispatch.state", mock_state):
            _check_realtime_latency(old_ts)
            assert mock_state.realtime_latency_exceeded is True

    def test_recovery_clears_flag(self):
        mock_state = MagicMock()
        mock_state.realtime_latency_exceeded = True
        with patch("backend.app.services.engine_ws_dispatch.state", mock_state):
            _check_realtime_latency(int(time.time() * 1000))
            assert mock_state.realtime_latency_exceeded is False

    def test_50ms_warning_does_not_set_flag(self):
        mock_state = MagicMock()
        mock_state.realtime_latency_exceeded = False
        old_ts = int(time.time() * 1000) - 60
        with patch("backend.app.services.engine_ws_dispatch.state", mock_state):
            _check_realtime_latency(old_ts)
            assert mock_state.realtime_latency_exceeded is False


# ── start_compute_loop / stop_compute_loop ────────────────────────────────────

class TestStartComputeLoop:
    @pytest.mark.asyncio
    async def test_already_running_returns_early(self):
        compute_mod._compute_running = True
        mock_loop = MagicMock()
        with patch("asyncio.get_running_loop", return_value=mock_loop):
            await start_compute_loop()
            mock_loop.create_task.assert_not_called()
        compute_mod._compute_running = False

    @pytest.mark.asyncio
    async def test_start_creates_tasks(self):
        compute_mod._compute_running = False
        compute_mod._compute_task = None
        compute_mod._sector_recompute_task = None
        mock_loop = MagicMock()
        mock_task1 = MagicMock()
        mock_task2 = MagicMock()
        mock_loop.create_task.side_effect = [mock_task1, mock_task2]
        with patch("asyncio.get_running_loop", return_value=mock_loop):
            await start_compute_loop()
            for call in mock_loop.create_task.call_args_list:
                for arg in call.args:
                    if asyncio.iscoroutine(arg):
                        arg.close()
            assert compute_mod._compute_running is True
            assert compute_mod._compute_task is mock_task1
            assert compute_mod._sector_recompute_task is mock_task2
        compute_mod._compute_running = False
        compute_mod._compute_task = None
        compute_mod._sector_recompute_task = None


class TestStopComputeLoop:
    @pytest.mark.asyncio
    async def test_stop_with_no_tasks(self):
        compute_mod._compute_running = True
        compute_mod._compute_task = None
        compute_mod._sector_recompute_task = None
        await stop_compute_loop()
        assert compute_mod._compute_running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        compute_mod._compute_running = True
        class AwaitableTask:
            def __init__(self):
                self.cancel = MagicMock()
            def __await__(self):
                async def _noop():
                    return None
                return _noop().__await__()
        mock_task1 = AwaitableTask()
        mock_task2 = AwaitableTask()
        compute_mod._compute_task = mock_task2
        compute_mod._sector_recompute_task = mock_task1
        await stop_compute_loop()
        assert compute_mod._compute_running is False
        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()
        compute_mod._compute_task = None
        compute_mod._sector_recompute_task = None

    @pytest.mark.asyncio
    async def test_stop_handles_cancelled_error(self):
        compute_mod._compute_running = True
        class CancelledTask:
            def __init__(self):
                self.cancel = MagicMock()
            def __await__(self):
                async def _raise():
                    raise asyncio.CancelledError()
                return _raise().__await__()
        mock_task = CancelledTask()
        compute_mod._compute_task = mock_task
        compute_mod._sector_recompute_task = None
        await stop_compute_loop()
        assert compute_mod._compute_running is False
        compute_mod._compute_task = None


# ── _compute_loop_impl ────────────────────────────────────────────────────────

class TestComputeLoopImpl:
    @pytest.mark.asyncio
    async def test_loop_processes_tick_then_exits(self):
        compute_mod._compute_running = True
        mock_tick_q = MagicMock()
        mock_tick_q.get = AsyncMock(return_value={"trnm": "REAL", "data": {"type": "01", "values": {}}})
        mock_tick_q.task_done = MagicMock()
        mock_tick_q.get_nowait = MagicMock(side_effect=asyncio.QueueEmpty())
        mock_bq = MagicMock()
        mock_bq.put_nowait = MagicMock()
        mock_control_q = MagicMock()
        mock_control_q.get_nowait = MagicMock(side_effect=asyncio.QueueEmpty())

        call_count = 0
        async def _stop_after_one(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.get_tick_queue", return_value=mock_tick_q), \
             patch("backend.app.pipelines.pipeline_compute.get_broadcast_queue", return_value=mock_bq), \
             patch("backend.app.pipelines.pipeline_compute.get_control_queue", return_value=mock_control_q), \
             patch("backend.app.pipelines.pipeline_compute._process_tick_data", new_callable=AsyncMock, side_effect=_stop_after_one), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value={"trnm": "REAL", "data": {"type": "01", "values": {}}}, side_effect=_close_coro):
            await _compute_loop_impl()
            assert compute_mod._compute_running is False

    @pytest.mark.asyncio
    async def test_loop_timeout_no_data(self):
        compute_mod._compute_running = True
        mock_tick_q = MagicMock()
        mock_tick_q.task_done = MagicMock()
        mock_bq = MagicMock()
        mock_control_q = MagicMock()
        mock_control_q.get_nowait = MagicMock(side_effect=asyncio.QueueEmpty())

        timeout_count = 0
        async def _timeout_then_stop(*args, **kwargs):
            nonlocal timeout_count
            timeout_count += 1
            raise asyncio.TimeoutError()

        with patch("backend.app.pipelines.pipeline_compute.get_tick_queue", return_value=mock_tick_q), \
             patch("backend.app.pipelines.pipeline_compute.get_broadcast_queue", return_value=mock_bq), \
             patch("backend.app.pipelines.pipeline_compute.get_control_queue", return_value=mock_control_q), \
             patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=_timeout_then_stop), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=lambda *a, **kw: setattr(compute_mod, '_compute_running', False) if timeout_count >= 1 else None):
            await _compute_loop_impl()
            assert compute_mod._compute_running is False

    @pytest.mark.asyncio
    async def test_loop_handles_exception(self):
        compute_mod._compute_running = True
        mock_tick_q = MagicMock()
        mock_tick_q.task_done = MagicMock()
        mock_tick_q.get_nowait = MagicMock(side_effect=asyncio.QueueEmpty())
        mock_bq = MagicMock()
        mock_control_q = MagicMock()
        mock_control_q.get_nowait = MagicMock(side_effect=asyncio.QueueEmpty())

        call_count = 0
        async def _raise_then_stop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("tick processing error")
            compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.get_tick_queue", return_value=mock_tick_q), \
             patch("backend.app.pipelines.pipeline_compute.get_broadcast_queue", return_value=mock_bq), \
             patch("backend.app.pipelines.pipeline_compute.get_control_queue", return_value=mock_control_q), \
             patch("backend.app.pipelines.pipeline_compute._process_tick_data", new_callable=AsyncMock, side_effect=_raise_then_stop), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value={"trnm": "REAL", "data": {}}):
            await _compute_loop_impl()
            assert compute_mod._compute_running is False

    @pytest.mark.asyncio
    async def test_loop_processes_control_signal(self):
        compute_mod._compute_running = True
        mock_tick_q = MagicMock()
        mock_tick_q.task_done = MagicMock()
        mock_bq = MagicMock()
        mock_control_q = MagicMock()

        control_signals = [({"type": "UPDATE_CONFIG"}, {}, {"type": "UPDATE_CONFIG"})]
        call_idx = 0
        def _get_nowait():
            nonlocal call_idx
            if call_idx < len(control_signals):
                item = control_signals[call_idx]
                call_idx += 1
                return item
            raise asyncio.QueueEmpty()
        mock_control_q.get_nowait = _get_nowait
        mock_control_q.task_done = MagicMock()

        loop_count = 0
        async def _stop_after_control(*args, **kwargs):
            nonlocal loop_count
            loop_count += 1
            if loop_count >= 1:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.get_tick_queue", return_value=mock_tick_q), \
             patch("backend.app.pipelines.pipeline_compute.get_broadcast_queue", return_value=mock_bq), \
             patch("backend.app.pipelines.pipeline_compute.get_control_queue", return_value=mock_control_q), \
             patch("backend.app.pipelines.pipeline_compute._process_control_signal", new_callable=AsyncMock, side_effect=_stop_after_control), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=None):
            await _compute_loop_impl()


# ── _handle_real_01_tick ──────────────────────────────────────────────────────

class TestHandleReal01Tick:
    @pytest.mark.asyncio
    async def test_no_raw_cd_returns(self):
        item = {"type": "01"}
        vals = {"10": "50000"}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value=""):
            await _handle_real_01_tick(item, vals, AsyncMock())

    @pytest.mark.asyncio
    async def test_zero_price_returns(self):
        item = {"type": "01"}
        vals = {"10": "0"}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._parse_fid10_price", return_value=0):
            await _handle_real_01_tick(item, vals, AsyncMock())

    @pytest.mark.asyncio
    async def test_no_nk_px_returns(self):
        item = {"type": "01"}
        vals = {"10": "50000"}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value=""), \
             patch("backend.app.services.engine_ws_parsing._parse_fid10_price", return_value=50000):
            await _handle_real_01_tick(item, vals, AsyncMock())

    @pytest.mark.asyncio
    async def test_broadcasts_real_data(self):
        item = {"type": "01", "item": "005930"}
        vals = {"10": "50000", "11": "1000", "12": "2.0"}
        mock_bq = MagicMock()
        mock_bq.put_nowait = MagicMock()
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        mock_state.positions = []
        mock_state.auto_trade = None
        mock_state.access_token = None
        mock_state.realtime_latency_exceeded = False
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._parse_fid10_price", return_value=50000), \
             patch("backend.app.services.engine_ws_parsing.parse_change_rate_to_percent", return_value=2.0), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_int", return_value=1000), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_key_present", return_value=True), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_raw", return_value="2.0"), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account_rest.apply_last_price_to_positions_inplace", return_value=False), \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            await _handle_real_01_tick(item, vals, mock_bq)
            mock_bq.put_nowait.assert_called()

    @pytest.mark.asyncio
    async def test_price_hit_returns_true(self):
        item = {"type": "01", "item": "005930"}
        vals = {"10": "50000", "11": "1000", "12": "2.0"}
        mock_bq = MagicMock()
        mock_bq.put_nowait = MagicMock()
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        mock_state.positions = [{"stk_cd": "005930"}]
        mock_state.broker_rest_totals = {}
        mock_state.auto_trade = None
        mock_state.access_token = None
        mock_state.realtime_latency_exceeded = False
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._parse_fid10_price", return_value=50000), \
             patch("backend.app.services.engine_ws_parsing.parse_change_rate_to_percent", return_value=2.0), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_int", return_value=1000), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_key_present", return_value=True), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_raw", return_value="2.0"), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account_rest.apply_last_price_to_positions_inplace", return_value=True), \
             patch("backend.app.services.engine_account_rest.recalc_broker_totals_from_positions", return_value={}), \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            result = await _handle_real_01_tick(item, vals, mock_bq)
            assert result is True

    @pytest.mark.asyncio
    async def test_test_mode_price_hit(self):
        item = {"type": "01", "item": "005930"}
        vals = {"10": "50000", "11": "1000", "12": "2.0"}
        mock_bq = MagicMock()
        mock_bq.put_nowait = MagicMock()
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        mock_state.auto_trade = None
        mock_state.access_token = None
        mock_state.realtime_latency_exceeded = False
        mock_dry_run = MagicMock()
        mock_dry_run.update_price = AsyncMock(return_value=True)
        mock_dry_run.get_position = AsyncMock(return_value={"stk_cd": "005930"})
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._parse_fid10_price", return_value=50000), \
             patch("backend.app.services.engine_ws_parsing.parse_change_rate_to_percent", return_value=2.0), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_int", return_value=1000), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_key_present", return_value=True), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_raw", return_value="2.0"), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run", mock_dry_run), \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            result = await _handle_real_01_tick(item, vals, mock_bq)
            assert result is True
            mock_dry_run.update_price.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        item = {"type": "01"}
        vals = {}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", side_effect=Exception("boom")):
            await _handle_real_01_tick(item, vals, AsyncMock())

    @pytest.mark.asyncio
    async def test_broadcast_queue_full_handled(self):
        item = {"type": "01", "item": "005930"}
        vals = {"10": "50000"}
        mock_bq = MagicMock()
        mock_bq.put_nowait = MagicMock(side_effect=asyncio.QueueFull())
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        mock_state.positions = []
        mock_state.auto_trade = None
        mock_state.access_token = None
        mock_state.realtime_latency_exceeded = False
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"), \
             patch("backend.app.services.engine_ws_parsing._parse_fid10_price", return_value=50000), \
             patch("backend.app.services.engine_ws_parsing.parse_change_rate_to_percent", return_value=2.0), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_int", return_value=1000), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_key_present", return_value=False), \
             patch("backend.app.services.engine_ws_parsing._ws_fid_raw", return_value=""), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_account_rest.apply_last_price_to_positions_inplace", return_value=False), \
             patch("backend.app.pipelines.pipeline_compute.state", mock_state):
            await _handle_real_01_tick(item, vals, mock_bq)


# ── _handle_real_tick edge cases ──────────────────────────────────────────────

class TestHandleRealTickEdgeCases:
    @pytest.mark.asyncio
    async def test_non_dict_vals_defaulted_to_empty(self):
        mock_bq = AsyncMock()
        data = {"data": [{"type": "01", "values": "not_a_dict"}]}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_01_tick", new_callable=AsyncMock) as mock_01, \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="01"):
            await _handle_real_tick(data, mock_bq)
            mock_01.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_inner_exception_does_not_raise(self):
        mock_bq = AsyncMock()
        data = {"data": [{"type": "01", "values": {}}]}
        with patch("backend.app.pipelines.pipeline_compute._handle_real_01_tick", new_callable=AsyncMock, side_effect=Exception("inner boom")), \
             patch("backend.app.services.engine_ws_parsing._normalize_real_type", return_value="01"):
            await _handle_real_tick(data, mock_bq)


# ── _handle_real_0d_tick exception ────────────────────────────────────────────

class TestHandleReal0dTickException:
    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        item = {"item": "005930"}
        vals = {"125": "1000", "121": "800"}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", side_effect=Exception("boom")):
            await _handle_real_0d_tick(item, vals, AsyncMock())


# ── _handle_real_pgm_tick exception ───────────────────────────────────────────

class TestHandleRealPgmTickException:
    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        item = {"item": "005930"}
        vals = {"tval": "100"}
        with patch("backend.app.services.engine_symbol_utils._real_item_stk_cd", side_effect=Exception("boom")):
            await _handle_real_pgm_tick(item, vals, AsyncMock())


# ── _sector_recompute_loop_impl ───────────────────────────────────────────────

class TestSectorRecomputeLoopImpl:
    @pytest.mark.asyncio
    async def test_phase1_threshold_met_transitions_to_phase2(self):
        compute_mod._compute_running = True
        compute_mod._current_receive_rate = {
            "krx": {"received": 8, "total": 10, "pct": 80.0},
            "nxt": {"received": 4, "total": 5, "pct": 80.0},
        }
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 50.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 3:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute.get_current_receive_rate", return_value={
                 "krx": {"received": 8, "total": 10, "pct": 80.0},
                 "nxt": {"received": 4, "total": 5, "pct": 80.0},
             }), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.request_sector_recompute"), \
             patch("backend.app.services.engine_sector_confirm.has_dirty_sectors", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._flush_sector_recompute_impl", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }

    @pytest.mark.asyncio
    async def test_phase1_total_zero_continues(self):
        compute_mod._compute_running = True
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 50.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }

    @pytest.mark.asyncio
    async def test_phase1_received_zero_continues(self):
        compute_mod._compute_running = True
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 10, "pct": 0.0},
            "nxt": {"received": 0, "total": 5, "pct": 0.0},
        }
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 50.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }

    @pytest.mark.asyncio
    async def test_phase1_below_threshold_sends_rate(self):
        compute_mod._compute_running = True
        compute_mod._current_receive_rate = {
            "krx": {"received": 3, "total": 10, "pct": 30.0},
            "nxt": {"received": 1, "total": 5, "pct": 20.0},
        }
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 80.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock) as mock_send, \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)
            mock_send.assert_awaited()
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }

    @pytest.mark.asyncio
    async def test_phase1_nxt_only_window_nxt_only_threshold(self):
        """NXT-only 구간: NXT 수신률만 기준으로 임계값 통과 검증 (옵션 C)."""
        compute_mod._compute_running = True
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},  # KRX 비활성
            "nxt": {"received": 8, "total": 10, "pct": 80.0},  # NXT 80% → 임계값 50% 통과
        }
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 50.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 3:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute.get_current_receive_rate", return_value={
                 "krx": {"received": 0, "total": 0, "pct": 0.0},
                 "nxt": {"received": 8, "total": 10, "pct": 80.0},
             }), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=True), \
             patch("backend.app.services.engine_sector_confirm.request_sector_recompute"), \
             patch("backend.app.services.engine_sector_confirm.has_dirty_sectors", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._flush_sector_recompute_impl", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)
        # NXT-only 구간에서 NXT 수신률 80% ≥ 임계값 50% → 통과
        assert is_sector_threshold_passed() is True
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }

    @pytest.mark.asyncio
    async def test_phase1_regular_window_and_gate_krx_only_fails(self):
        """정규장: KRX만 통과, NXT 미달 → 게이트 해제 안 됨 (AND 정책)."""
        compute_mod._compute_running = True
        compute_mod._sector_threshold_passed = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 8, "total": 10, "pct": 80.0},  # KRX 80% → 통과
            "nxt": {"received": 1, "total": 5, "pct": 20.0},   # NXT 20% → 미달
        }
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 50.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)
        # 정규장 AND 정책: KRX 통과해도 NXT 미달 → 게이트 False 유지
        assert is_sector_threshold_passed() is False
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }

    @pytest.mark.asyncio
    async def test_phase1_exception_does_not_crash(self):
        compute_mod._compute_running = True
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 50.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock, side_effect=Exception("calc error")), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False

    @pytest.mark.asyncio
    async def test_cancelled_error_handled(self):
        compute_mod._compute_running = True
        mock_bq = MagicMock()

        async def _sleep_raise_cancel(seconds):
            raise asyncio.CancelledError()

        with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_raise_cancel):
            await _sector_recompute_loop_impl(mock_bq)
        compute_mod._compute_running = False


# ── 수신율 임계값 게이트 (SSOT 플래그) ─────────────────────────────────────────

class TestSectorThresholdGate:
    """is_sector_threshold_passed / reset_sector_threshold / mark_sector_threshold_passed 검증."""

    def setup_method(self):
        """각 테스트 전 플래그를 기본값(True)로 복원."""
        compute_mod._sector_threshold_passed = True

    def teardown_method(self):
        """각 테스트 후 플래그를 기본값(True)로 복원."""
        compute_mod._sector_threshold_passed = True

    def test_default_is_passed(self):
        """비-WS 구간 기본값: 임계값 통과 상태(True)."""
        assert is_sector_threshold_passed() is True

    def test_reset_sets_false(self):
        """reset_sector_threshold() → False 전환."""
        reset_sector_threshold()
        assert is_sector_threshold_passed() is False

    def test_mark_sets_true(self):
        """mark_sector_threshold_passed() → True 전환."""
        reset_sector_threshold()
        assert is_sector_threshold_passed() is False
        mark_sector_threshold_passed()
        assert is_sector_threshold_passed() is True

    @pytest.mark.asyncio
    async def test_phase1_marks_threshold_passed(self):
        """Phase 1 임계값 통과 시 mark_sector_threshold_passed() 호출 검증 (정규장 AND 정책)."""
        compute_mod._compute_running = True
        compute_mod._receive_rate_dirty = True
        compute_mod._sector_threshold_passed = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 8, "total": 10, "pct": 80.0},
            "nxt": {"received": 4, "total": 5, "pct": 80.0},
        }
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 50.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 3:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute.get_current_receive_rate", return_value={
                 "krx": {"received": 8, "total": 10, "pct": 80.0},
                 "nxt": {"received": 4, "total": 5, "pct": 80.0},
             }), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("backend.app.services.engine_sector_confirm.request_sector_recompute"), \
             patch("backend.app.services.engine_sector_confirm.has_dirty_sectors", return_value=False), \
             patch("backend.app.services.engine_sector_confirm._flush_sector_recompute_impl", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account_notify.notify_desktop_sector_scores", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)

        # Phase 1 통과 후 플래그가 True로 전환되었는지 검증
        assert is_sector_threshold_passed() is True
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }

    @pytest.mark.asyncio
    async def test_phase1_below_threshold_keeps_gate_false(self):
        """Phase 1 임계값 미달 시 플래그가 False로 유지됨 검증 (정규장 AND 정책)."""
        compute_mod._compute_running = True
        compute_mod._receive_rate_dirty = True
        compute_mod._current_receive_rate = {
            "krx": {"received": 3, "total": 10, "pct": 30.0},
            "nxt": {"received": 1, "total": 5, "pct": 20.0},
        }
        compute_mod._sector_threshold_passed = False
        mock_bq = MagicMock()

        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {"sector_start_threshold_pct": 80.0}

        sleep_count = 0
        async def _sleep_mock(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                compute_mod._compute_running = False

        with patch("backend.app.pipelines.pipeline_compute.state", mock_state), \
             patch("backend.app.pipelines.pipeline_compute._calculate_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.pipelines.pipeline_compute._send_receive_rate", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.is_nxt_only_window", return_value=False), \
             patch("asyncio.sleep", new_callable=AsyncMock, side_effect=_sleep_mock):
            await _sector_recompute_loop_impl(mock_bq)

        # 임계값 미달 → 플래그가 False로 유지
        assert is_sector_threshold_passed() is False
        compute_mod._compute_running = False
        compute_mod._receive_rate_dirty = False
        compute_mod._current_receive_rate = {
            "krx": {"received": 0, "total": 0, "pct": 0.0},
            "nxt": {"received": 0, "total": 0, "pct": 0.0},
        }


# ── notify_desktop_sector_scores 게이트 ────────────────────────────────────────

class TestNotifySectorScoresGate:
    """notify_desktop_sector_scores() 임계값 게이트 동작 검증."""

    def setup_method(self):
        compute_mod._sector_threshold_passed = True

    def teardown_method(self):
        compute_mod._sector_threshold_passed = True

    @pytest.mark.asyncio
    async def test_gate_blocks_when_threshold_not_passed(self):
        """임계값 미통과 시 notify_desktop_sector_scores() 전송 스킵."""
        from backend.app.services.engine_account_notify import notify_desktop_sector_scores, notify_cache
        compute_mod._sector_threshold_passed = False
        notify_cache.prev_scores = [{"sector": "반도체"}]

        with patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot") as mock_snapshot:
            await notify_desktop_sector_scores(force=True)
            mock_snapshot.assert_not_called()

        # delta 비교 캐시가 클리어되었는지 검증
        assert notify_cache.prev_scores == []

    @pytest.mark.asyncio
    async def test_gate_allows_when_threshold_passed(self):
        """임계값 통과 시 notify_desktop_sector_scores() 정상 전송."""
        from backend.app.services.engine_account_notify import notify_desktop_sector_scores
        compute_mod._sector_threshold_passed = True

        mock_scores = [{"sector": "반도체", "rank": 1, "final_score": 90.0}]
        with patch("backend.app.services.sector_data_provider.get_sector_scores_snapshot", return_value=(mock_scores, 1)), \
             patch("backend.app.services.engine_account_notify._safe_broadcast", new_callable=AsyncMock) as mock_broadcast, \
             patch("backend.app.pipelines.pipeline_compute.get_current_receive_rate", return_value={
                 "krx": {"received": 8, "total": 10, "pct": 80.0},
                 "nxt": {"received": 4, "total": 5, "pct": 80.0},
             }):
            await notify_desktop_sector_scores(force=True)
            mock_broadcast.assert_awaited_once()
