# -*- coding: utf-8 -*-
"""market_close_storage.py 단위 테스트 — 장마감 확정데이터 저장 전담 모듈.

세션 2에서 market_close_pipeline.py 의 저장 로직을 분리하여 생성된 모듈.
본 테스트는 DB 파라미터·트랜잭션·안전망·행 정리·롤백을 직접 검증한다.
메모리 반영(pipeline 측) 검증은 test_market_close_pipeline.py 에서 수행.

검증 대상:
- save_daily_confirmed: 자동 일봉 확정시세 단일 트랜잭션 저장
- save_5d_bars: 수동 5거래일 일봉 단일 트랜잭션 저장
- 안전망: 소속 거래일(미확정 당일) 행 저장 차단 (P22)
- 행 정리: qry_dt 기준 과거·미래 행 DELETE (P22/P24)
- 같은 날 재실행: INSERT OR REPLACE 덮어쓰기 (P22)
- 저장 오류: 롤백 + 실패 결과 반환 (P20)
- 빈 입력: 저장 시도 없이 실패 결과 반환 (P20 — 빈값을 성공으로 위장 금지)
"""
from __future__ import annotations

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.market_close_storage import (
    save_daily_confirmed,
    save_5d_bars,
)


# ── 공통 달력 mock — _prune_5d_bars 의 get_recent_trading_days 반환 ────────────
# qry_dt=20250106 기준 최근 5거래일. oldest_dt=20250102.
_RECENT_5_JAN06 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]
_RECENT_5_JAN05 = [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_conn():
    """aiosqlite 연결 mock — execute/executemany/commit/rollback 모두 AsyncMock."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    # cursor 반환 — fetchall 지원
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=[])
    conn.execute.return_value = cursor
    return conn


def _mock_lock():
    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=lock)
    lock.__aexit__ = AsyncMock(return_value=None)
    return lock


def _mock_cursor_with_rows(rows):
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    return cursor


# ── save_daily_confirmed ──────────────────────────────────────────────────────

class TestSaveDailyConfirmed:
    @pytest.mark.asyncio
    async def test_empty_confirmed_returns_failure(self):
        """빈 confirmed는 저장할 게 없으므로 실패 (P20 — 빈값을 성공으로 위장 금지)."""
        result = await save_daily_confirmed({}, qry_dt="20250106")
        assert result["success"] is False
        assert result["saved_codes"] == []
        assert result["derived"] == {}

    @pytest.mark.asyncio
    async def test_no_qry_dt_returns_failure(self):
        """qry_dt 없고 현재 거래일도 없으면 실패 (P20 폴백 금지)."""
        with patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value=""):
            result = await save_daily_confirmed({"005930": {"cur_price": 50000}})
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_save_success_returns_derived(self):
        """저장 성공 시 saved_codes + derived(파생값) 반환 (설계 5.4)."""
        mock_conn = _mock_conn()
        # 1st fetchall: stock_5d_bars 재계산용 행, 2nd fetchall: master_stocks_table market 정보
        cursor = _mock_cursor_with_rows([])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=_RECENT_5_JAN06), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106", name_map={"005930": "삼성전자"})
        assert result["success"] is True
        assert "005930" in result["saved_codes"]
        assert "005930" in result["derived"]
        mock_conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_same_day_upsert_uses_api_dt(self):
        """같은 날 재실행 시 INSERT OR REPLACE로 당일 행 덮어쓰기, dt는 API 실제 거래일 우선 (P10/P22)."""
        mock_conn = _mock_conn()
        existing_bars = [
            {"code": "005930", "dt": "20250106", "trade_amount": 999, "high_price": 9999},
            {"code": "005930", "dt": "20250105", "trade_amount": 200, "high_price": 2000},
        ]
        # fetchall 순서: 5d bars → 기존 요약값 → market 정보 (세션 4 — 5일 완전성·요약값 대조)
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, [], []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=_RECENT_5_JAN06), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106")
        assert result["success"] is True
        # 1st executemany: stock_5d_bars INSERT OR REPLACE (당일 1행)
        bars_call = mock_conn.executemany.call_args_list[0]
        bars_params = bars_call.args[1][0]
        assert bars_params[0] == "005930"
        assert bars_params[1] == "20250106"  # dt = detail.dt (API 실제 거래일)
        assert bars_params[2] == 555
        assert bars_params[3] == 8888

    @pytest.mark.asyncio
    async def test_api_returns_previous_day_uses_api_dt_not_qry_dt(self):
        """장마감 전 실행 시 API가 어제 일봉을 latest로 반환 → dt는 API 실제 거래일 (P10/P22)."""
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[[{"code": "005930", "dt": "20250105", "trade_amount": 200, "high_price": 2000}], [], []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=_RECENT_5_JAN06), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250105", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 200, "high_price": 2000},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106")
        assert result["success"] is True
        bars_call = mock_conn.executemany.call_args_list[0]
        bars_params = bars_call.args[1][0]
        assert bars_params[1] == "20250105"  # detail.dt 우선 — qry_dt(20250106) 아님

    @pytest.mark.asyncio
    async def test_safety_net_blocks_current_trading_day_bar(self):
        """안전망: API가 소속 거래일(미확정 당일) 행을 반환하면 저장 차단 (P22)."""
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[[], []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=_RECENT_5_JAN05), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 0, "change_rate": 0.0, "trade_amount": 0, "high_price": 50000},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250105")
        assert result["success"] is True
        # stock_5d_bars INSERT OR REPLACE가 호출되지 않아야 함 (안전망이 20250106 행 차단)
        bars_calls = [
            call for call in mock_conn.executemany.call_args_list
            if "stock_5d_bars" in str(call)
        ]
        assert len(bars_calls) == 0

    @pytest.mark.asyncio
    async def test_prunes_past_and_future_bars_before_insert(self):
        """qry_dt 기준 최근 5거래일 외 과거·미래 행을 INSERT 전에 DELETE (설계 7, 세션 4 — 자동·수동 공통 보관 정책)."""
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[[], [], []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=_RECENT_5_JAN06), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106")
        assert result["success"] is True
        delete_calls = [
            call for call in mock_conn.execute.call_args_list
            if "DELETE FROM stock_5d_bars" in str(call) and "dt <" in str(call) and "dt >" in str(call)
        ]
        assert len(delete_calls) == 1
        delete_params = delete_calls[0].args[1]
        assert delete_params[0] == "20250102"  # oldest_dt (과거 기준 — 5거래일 밖)
        assert delete_params[1] == "20250106"  # qry_dt (미래 기준)

    @pytest.mark.asyncio
    async def test_master_date_uses_qry_dt(self):
        """master_stocks_table.date가 qry_dt(데이터 기준일)로 설정 (P10/P22)."""
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[[], [], []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=_RECENT_5_JAN05), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250105", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250105")
        assert result["success"] is True
        master_calls = [
            call for call in mock_conn.executemany.call_args_list
            if "master_stocks_table" in str(call) and "INSERT INTO" in str(call)
        ]
        assert len(master_calls) == 1
        master_params = master_calls[0].args[1][0]
        # params: (code, name, cur_price, change, change_rate, today_amt, avg_5d, high_5d, date, market)
        assert master_params[8] == "20250105"  # date = qry_dt

    @pytest.mark.asyncio
    async def test_db_exception_rolls_back_and_returns_failure(self):
        """저장 중 DB 오류 시 롤백 + 실패 결과 반환 (P20 — 예외를 성공으로 위장 금지)."""
        mock_conn = _mock_conn()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250105", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250105")
        assert result["success"] is False
        assert result["saved_codes"] == []
        assert result["derived"] == {}
        mock_conn.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recalc_derived_from_5d_bars(self):
        """avg_5d/high_5d가 stock_5d_bars 최근 5행에서 재계산되어 derived에 포함 (P10 SSOT)."""
        mock_conn = _mock_conn()
        # 1st fetchall: stock_5d_bars 행 (5행), 2nd fetchall: 기존 요약값, 3rd fetchall: master market 정보
        # dt 필드 포함 — 5일 완전성 검증 (세션 4)
        existing_bars = [
            {"code": "005930", "dt": "20250106", "trade_amount": 555, "high_price": 8888},  # 당일
            {"code": "005930", "dt": "20250105", "trade_amount": 400, "high_price": 7000},
            {"code": "005930", "dt": "20250104", "trade_amount": 300, "high_price": 6000},
            {"code": "005930", "dt": "20250103", "trade_amount": 200, "high_price": 5000},
            {"code": "005930", "dt": "20250102", "trade_amount": 100, "high_price": 4000},
        ]
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, [], []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=_RECENT_5_JAN06), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        # (555+400+300+200+100) // 5 = 311
        assert avg_5d == 311
        # max(8888, 7000, 6000, 5000, 4000) = 8888
        assert high_5d == 8888


# ── save_5d_bars ──────────────────────────────────────────────────────────────

class TestSave5dBars:
    @pytest.mark.asyncio
    async def test_empty_input_returns_failure(self):
        """빈 confirmed_5d는 저장할 게 없으므로 실패 (P20)."""
        result = await save_5d_bars({}, qry_dt="20250106")
        assert result["success"] is False
        assert result["saved_codes"] == []
        assert result["derived"] == {}

    @pytest.mark.asyncio
    async def test_no_qry_dt_returns_failure(self):
        """qry_dt 없으면 실패 (P20 폴백 금지)."""
        result = await save_5d_bars({"005930": {"amts_5d_array": [100], "highs_5d_array": [200], "dts_5d_array": ["20250106"]}}, qry_dt="")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_save_success_returns_derived(self):
        """저장 성공 시 saved_codes + derived 반환 (설계 5.4)."""
        mock_conn = _mock_conn()
        recent_5 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=recent_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                    "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        assert "005930" in result["saved_codes"]
        avg_5d, high_5d = result["derived"]["005930"]
        # (5000000+4000000+3000000+2000000+1000000) // 5 = 3000000
        assert avg_5d == 3000000
        # max(51000, 52000, 53000, 54000, 55000) = 55000
        assert high_5d == 55000
        mock_conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safety_net_blocks_current_trading_day_bar(self):
        """5거래일 일봉 안전망: 소속 거래일(미확정 당일) 행은 저장에서 제외 (P22)."""
        mock_conn = _mock_conn()
        recent_5 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250106"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=recent_5):
            # 첫 번째(최신)가 소속 거래일(20250106) — 미확정 행
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [0, 4000000, 3000000, 2000000, 1000000],
                    "highs_5d_array": [50000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250105")
        assert result["success"] is True
        # stock_5d_bars INSERT OR REPLACE 호출에서 20250106 행이 제외되었는지 검증
        bars_calls = [
            call for call in mock_conn.executemany.call_args_list
            if "stock_5d_bars" in str(call)
        ]
        assert len(bars_calls) == 1
        bars_params = bars_calls[0].args[1]
        dts_saved = [p[1] for p in bars_params]
        assert "20250106" not in dts_saved  # 미확정 당일 행은 저장되지 않아야 함
        assert "20250105" in dts_saved      # 직전 거래일 행은 저장되어야 함

    @pytest.mark.asyncio
    async def test_deletes_past_and_future_bars(self):
        """qry_dt 기준 최근 5거래일 외 과거 행 + qry_dt보다 큰 미래 행 DELETE (P22/P24)."""
        mock_conn = _mock_conn()
        recent_5 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=recent_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                    "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        delete_calls = [
            call for call in mock_conn.execute.call_args_list
            if "DELETE FROM stock_5d_bars" in str(call) and "dt <" in str(call) and "dt >" in str(call)
        ]
        assert len(delete_calls) == 1
        delete_params = delete_calls[0].args[1]
        assert delete_params[0] == "20250102"  # oldest_dt (과거 기준)
        assert delete_params[1] == "20250106"  # qry_dt (미래 기준)

    @pytest.mark.asyncio
    async def test_db_exception_rolls_back_and_returns_failure(self):
        """저장 중 DB 오류 시 롤백 + 실패 결과 반환 (P20)."""
        mock_conn = _mock_conn()
        mock_conn.executemany = AsyncMock(side_effect=Exception("DB error"))
        recent_5 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=recent_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                    "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is False
        assert result["saved_codes"] == []
        assert result["derived"] == {}
        mock_conn.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_arrays_in_stock_produce_none_derived(self):
        """빈 배열 종목은 avg_5d=None, high_5d=None 파생값 (P20 폴백 금지 — 빈값을 0으로 위장하지 않음)."""
        mock_conn = _mock_conn()
        recent_5 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=recent_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [],
                    "highs_5d_array": [],
                    "dts_5d_array": [],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d is None
        assert high_5d is None


# ── save_5d_bars: 5일 완전성·파생값 (설계서 4.5, 세션 4) ──────────────────────

class TestSave5dBarsCompleteness:
    """5일 완전성 검증·파생값 저장 (설계서 4.5, 세션 4)."""

    _RECENT_5 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]

    @pytest.mark.asyncio
    async def test_complete_5d_returns_derived(self):
        """5일 전부 수신·숫자값 누락 없음 → 파생값 계산 (설계서 4.5)."""
        mock_conn = _mock_conn()
        # 기존 요약값 조회 결과 — 첫 저장이므로 0, 0 (불일치 아님)
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                    "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d == 3000000
        assert high_5d == 55000

    @pytest.mark.asyncio
    async def test_insufficient_5d_returns_none_derived(self):
        """5일 미만 수신 → 파생값 None (P20 폴백 금지, 설계서 4.5)."""
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000],  # 2일만
                    "highs_5d_array": [51000, 52000],
                    "dts_5d_array": ["20250106", "20250105"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d is None  # 파생값 None (P20)
        assert high_5d is None

    @pytest.mark.asyncio
    async def test_missing_day_skipped_to_none_derived(self):
        """거래일 누락 + 예상 외 행 제거 → 행 수 부족 → 파생값 None (P20 폴백 금지).

        예상 외 거래일(20250107) 행은 저장 단계에서 제거되어 4행만 남으므로
        행 수 부족 → 파생값 None (설계서 4.5).
        """
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5):
            # 20250104 누락, 20250107 추가 (예상 외 — 저장 단계에서 제거됨)
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                    "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250103", "20250102", "20250107"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d is None
        assert high_5d is None

    @pytest.mark.asyncio
    async def test_numeric_missing_returns_none_derived(self):
        """거래일은 5일 전부지만 거래대금 0 → 파생값 None (설계서 4.5)."""
        mock_conn = _mock_conn()
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000, 0, 2000000, 1000000],  # 0은 누락
                    "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d is None
        assert high_5d is None

    @pytest.mark.asyncio
    async def test_complete_5d_returns_derived_even_with_different_existing_summary(self):
        """5일 완전 + 기존 요약값과 달라도 → 파생값 계산 (버그 수정 — 갱신 후 값은 항상 일치).

        과거에는 기존 요약값과 불일치 시 summary_mismatch를 반환했으나, 매일 5일 윈도우가
        밀리는 정상 변화를 불일치로 오판하는 버그가 있어 제거되었다.
        """
        mock_conn = _mock_conn()
        # 기존 요약값 — 계산값(3000000, 55000)과 다르지만 이제 무시됨
        existing_summary = [{"code": "005930", "avg_5d_trade_amount": 9999999, "high_5d_price": 11111}]
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(return_value=existing_summary)
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5):
            confirmed_5d = {
                "005930": {
                    "amts_5d_array": [5000000, 4000000, 3000000, 2000000, 1000000],
                    "highs_5d_array": [51000, 52000, 53000, 54000, 55000],
                    "dts_5d_array": ["20250106", "20250105", "20250104", "20250103", "20250102"],
                },
            }
            result = await save_5d_bars(confirmed_5d, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d == 3000000
        assert high_5d == 55000


# ── save_daily_confirmed: 5일 완전성·파생값 (설계서 4.5, 세션 4) ──────────────

class TestSaveDailyConfirmedCompleteness:
    """자동 일봉 경로의 5일 완전성·파생값 (설계서 4.5, 세션 4 — 자동·수동 같은 규칙)."""

    _RECENT_5 = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5), date(2025, 1, 6)]

    @pytest.mark.asyncio
    async def test_complete_5d_returns_derived(self):
        """5일 전부 수신 → 파생값 계산 (설계서 4.5)."""
        mock_conn = _mock_conn()
        # fetchall 순서: 5d bars(5행) → market 정보(빈)
        # 기존 요약값 조회는 제거됨 (버그 수정 — 요약값 대조 제거)
        existing_bars = [
            {"code": "005930", "dt": "20250106", "trade_amount": 555, "high_price": 8888},
            {"code": "005930", "dt": "20250105", "trade_amount": 400, "high_price": 7000},
            {"code": "005930", "dt": "20250104", "trade_amount": 300, "high_price": 6000},
            {"code": "005930", "dt": "20250103", "trade_amount": 200, "high_price": 5000},
            {"code": "005930", "dt": "20250102", "trade_amount": 100, "high_price": 4000},
        ]
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d == 311
        assert high_5d == 8888

    @pytest.mark.asyncio
    async def test_insufficient_5d_returns_none_derived(self):
        """5일 미만 → 파생값 None (P20 폴백 금지, 설계서 4.5)."""
        mock_conn = _mock_conn()
        # 5d bars가 2행만 — 5일 미만
        # fetchall 순서: 5d bars(2행) → market 정보(빈) — 기존 요약값 조회 제거됨
        existing_bars = [
            {"code": "005930", "dt": "20250106", "trade_amount": 555, "high_price": 8888},
            {"code": "005930", "dt": "20250105", "trade_amount": 400, "high_price": 7000},
        ]
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d is None  # 파생값 None (P20)
        assert high_5d is None

    @pytest.mark.asyncio
    async def test_complete_5d_returns_derived_even_with_different_existing_summary(self):
        """5일 완전 + 기존 요약값과 달라도 → 파생값 계산 (버그 수정 — 갱신 후 값은 항상 일치).

        과거에는 기존 요약값과 불일치 시 summary_mismatch를 반환했으나, 매일 5일 윈도우가
        밀리는 정상 변화를 불일치로 오판하는 버그가 있어 제거되었다.
        """
        mock_conn = _mock_conn()
        existing_bars = [
            {"code": "005930", "dt": "20250106", "trade_amount": 555, "high_price": 8888},
            {"code": "005930", "dt": "20250105", "trade_amount": 400, "high_price": 7000},
            {"code": "005930", "dt": "20250104", "trade_amount": 300, "high_price": 6000},
            {"code": "005930", "dt": "20250103", "trade_amount": 200, "high_price": 5000},
            {"code": "005930", "dt": "20250102", "trade_amount": 100, "high_price": 4000},
        ]
        # 기존 요약값 — 계산값(311, 8888)과 다르지만 이제 무시됨 (조회 자체가 제거됨)
        cursor = MagicMock()
        cursor.fetchall = AsyncMock(side_effect=[existing_bars, []])
        mock_conn.execute = AsyncMock(return_value=cursor)
        with patch("backend.app.services.market_close_storage.get_db_connection", new_callable=AsyncMock, return_value=mock_conn), \
             patch("backend.app.services.market_close_storage.get_db_lock", return_value=_mock_lock()), \
             patch("backend.app.services.market_close_storage.get_current_trading_day_str", return_value="20250107"), \
             patch("backend.app.services.market_close_storage.get_recent_trading_days", return_value=self._RECENT_5), \
             patch("backend.app.services.market_close_storage._base_stk_cd", side_effect=lambda x: x):
            confirmed = {
                "005930": {"dt": "20250106", "cur_price": 50000, "change": 1000, "change_rate": 2.0, "trade_amount": 555, "high_price": 8888},
            }
            result = await save_daily_confirmed(confirmed, qry_dt="20250106")
        assert result["success"] is True
        avg_5d, high_5d = result["derived"]["005930"]
        assert avg_5d == 311
        assert high_5d == 8888
