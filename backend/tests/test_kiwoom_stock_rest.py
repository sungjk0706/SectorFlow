"""kiwoom_stock_rest.py 단위 테스트 — 개별종목시세 REST API 검증.

_si (정상/콤마/플러스/빈값/대시/음수절대값/예외)
_si_signed (정상/음수부호보존/콤마/플러스/빈값/대시/예외)
fetch_ka10081_daily_price (정상/오름차순정렬/resp None/빈rows/비list/종가0/등락률계산/prev_close 0/파싱예외/숫자코드/알파벳코드/_raw_cd/sign기본값)
fetch_ka10081_daily_5d_data (정상5개/오름차순정렬/신규상장3개/resp None/빈rows/비list/파싱예외/연속조회2페이지/연속조회중단/정확히5개)
fetch_ka10081_all_stocks_daily_confirmed (정상/빈리스트/일부실패/on_progress/예외처리)
fetch_ka10081_all_stocks_5day (정상/빈리스트/일부실패/on_progress/예외처리)
fetch_ka10099_unified (정상/연속조회/재시도3회/빈list/비dict항목/코드없음/알파벳코드/종목명파싱/nxtEnable/코스닥)

의존성: KiwoomRestAPI._call_api, UnifiedStockRecord, asyncio.sleep
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _mock_api(base_url="https://api.kiwoom.com"):
    """KiwoomRestAPI mock 생성 — base_url 속성만 필요."""
    api = MagicMock()
    api.base_url = base_url
    api._call_api = AsyncMock()
    return api


def _mock_resp(json_data=None, headers=None):
    """httpx.Response mock 생성."""
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    return resp


def _make_daily_row(dt="20260710", cur_prc="70,000", pred_pre="+1,000",
                    pred_pre_sig="2", trde_prica="500,000", high_pric="72,000"):
    """ka10081 일봉 row 생성."""
    return {
        "dt": dt,
        "cur_prc": cur_prc,
        "pred_pre": pred_pre,
        "pred_pre_sig": pred_pre_sig,
        "trde_prica": trde_prica,
        "high_pric": high_pric,
    }


# ── _si ────────────────────────────────────────────────────────────────────────

class TestSi:
    def test_normal_int(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si(12345) == 12345

    def test_str_int(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("12345") == 12345

    def test_comma_removed(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("70,000") == 70000

    def test_plus_removed(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("+1,000") == 1000

    def test_empty_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("") == 0

    def test_dash_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("-") == 0

    def test_negative_returns_abs(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("-500") == 500

    def test_float_string(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("123.45") == 123

    def test_none_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si(None) == 0

    def test_invalid_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si
        assert _si("abc") == 0


# ── _si_signed ──────────────────────────────────────────────────────────────────

class TestSiSigned:
    def test_normal_int(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed(1000) == 1000

    def test_negative_preserved(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed("-500") == -500

    def test_comma_removed(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed("-1,500") == -1500

    def test_plus_removed(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed("+2,000") == 2000

    def test_empty_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed("") == 0

    def test_dash_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed("-") == 0

    def test_none_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed(None) == 0

    def test_invalid_returns_zero(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed("abc") == 0

    def test_float_string(self):
        from backend.app.core.kiwoom_stock_rest import _si_signed
        assert _si_signed("123.45") == 123


# ── fetch_ka10081_daily_price ──────────────────────────────────────────────────

class TestFetchKa10081DailyPrice:
    @pytest.mark.asyncio
    async def test_normal(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result is not None
        assert result["dt"] == "20260710"  # API 일봉의 실제 거래일 (P10/P22)
        assert result["cur_price"] == 70000
        assert result["sign"] == "2"
        assert result["change"] == 1000
        assert result["trade_amount"] == 500000
        assert result["high_price"] == 72000
        assert result["change_rate"] is not None

    @pytest.mark.asyncio
    async def test_dt_field_propagated_from_latest_row(self):
        """fetch_ka10081_daily_price가 latest 일봉의 dt를 반환값에 포함하는지 검증 (P10/P22).

        장마감 전 API가 어제 일봉을 latest로 반환할 때, 호출자가 이 dt를
        stock_5d_bars.dt로 사용해야 중복 행 생성이 차단됨.
        """
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        # qry_dt는 20260715(달력 오늘)이지만 API는 아직 20260714 일봉을 latest로 반환
        row = _make_daily_row(dt="20260714", cur_prc="70,000")
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260715")
        assert result is not None
        assert result["dt"] == "20260714"  # qry_dt가 아니라 API 실제 거래일

    @pytest.mark.asyncio
    async def test_ascending_sorted_reversed(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row_old = _make_daily_row(dt="20260709", cur_prc="69,000")
        row_new = _make_daily_row(dt="20260710", cur_prc="70,000")
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row_old, row_new]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result["cur_price"] == 70000

    @pytest.mark.asyncio
    async def test_descending_kept(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row_new = _make_daily_row(dt="20260710", cur_prc="70,000")
        row_old = _make_daily_row(dt="20260709", cur_prc="69,000")
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row_new, row_old]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result["cur_price"] == 70000

    @pytest.mark.asyncio
    async def test_resp_none(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        api._call_api.return_value = (None, False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_rows(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": []}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_rows_not_list(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": "not_a_list"}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_close_zero(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row(cur_prc="0")
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_change_rate_calculation(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row(cur_prc="70,000", pred_pre="+1,000")
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        expected = round((1000 / 69000) * 100, 2)
        assert result["change_rate"] == expected

    @pytest.mark.asyncio
    async def test_change_rate_none_when_prev_zero(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row(cur_prc="1,000", pred_pre="+1,000")
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result["change_rate"] is None

    @pytest.mark.asyncio
    async def test_parsing_exception(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        resp = _mock_resp()
        resp.json.side_effect = ValueError("bad json")
        api._call_api.return_value = (resp, False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_digit_code_padded(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        await fetch_ka10081_daily_price(api, "5930", "20260710")
        call_args = api._call_api.call_args
        body = call_args.kwargs["body"]
        assert body["stk_cd"] == "005930_AL"

    @pytest.mark.asyncio
    async def test_alphabet_code(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        await fetch_ka10081_daily_price(api, "A12345", "20260710")
        call_args = api._call_api.call_args
        body = call_args.kwargs["body"]
        assert body["stk_cd"] == "A12345"

    @pytest.mark.asyncio
    async def test_raw_cd_used_in_label(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        await fetch_ka10081_daily_price(api, "005930", "20260710", _raw_cd="RAW005")
        call_args = api._call_api.call_args
        assert "RAW005" in call_args.kwargs["label"]

    @pytest.mark.asyncio
    async def test_sign_default(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_price
        api = _mock_api()
        row = _make_daily_row(pred_pre_sig="")
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        result = await fetch_ka10081_daily_price(api, "005930", "20260710")
        assert result["sign"] == "3"


# ── fetch_ka10081_daily_5d_data ─────────────────────────────────────────────────

class TestFetchKa10081Daily5dData:
    @pytest.mark.asyncio
    async def test_normal_5_rows(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026071{i}") for i in range(5, 10)]
        rows = list(reversed(rows))
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": rows}), False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is not None
        assert len(result["amts_5d_array"]) == 5
        assert len(result["highs_5d_array"]) == 5
        assert len(result["dts_5d_array"]) == 5
        assert result["dts_5d_array"][0] == "20260719"  # 최신일이 첫 번째

    @pytest.mark.asyncio
    async def test_ascending_sorted_reversed(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026071{i}") for i in range(5, 10)]
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": rows}), False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is not None
        assert len(result["amts_5d_array"]) == 5

    @pytest.mark.asyncio
    async def test_new_listing_3_rows_padded(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026071{i}") for i in range(7, 10)]
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": rows}), False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is not None
        assert len(result["amts_5d_array"]) == 5
        assert result["amts_5d_array"][3] is None
        assert result["amts_5d_array"][4] is None
        assert result["highs_5d_array"][3] is None
        assert result["highs_5d_array"][4] is None
        assert result["dts_5d_array"][3] is None
        assert result["dts_5d_array"][4] is None

    @pytest.mark.asyncio
    async def test_resp_none(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        api._call_api.return_value = (None, False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_rows(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": []}), False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_rows_not_list(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": "not_a_list"}), False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_parsing_exception(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        resp = _mock_resp()
        resp.json.side_effect = ValueError("bad json")
        api._call_api.return_value = (resp, False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is None

    @pytest.mark.asyncio
    async def test_pagination_2_pages(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        page1_rows = [_make_daily_row(dt=f"2026070{i}") for i in range(1, 4)]
        page2_rows = [_make_daily_row(dt=f"202607{i}") for i in range(4, 7)]
        resp1 = _mock_resp({"stk_dt_pole_chart_qry": page1_rows}, {"cont-yn": "Y", "next-key": "key123"})
        resp2 = _mock_resp({"stk_dt_pole_chart_qry": page2_rows}, {"cont-yn": "N", "next-key": ""})
        api._call_api.side_effect = [(resp1, False), (resp2, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is not None
        assert len(result["amts_5d_array"]) == 5

    @pytest.mark.asyncio
    async def test_pagination_stops_when_no_cont(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026070{i}") for i in range(1, 4)]
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": rows}, {"cont-yn": "N"}), False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is not None
        assert len(result["amts_5d_array"]) == 5
        assert result["amts_5d_array"][3] is None

    @pytest.mark.asyncio
    async def test_exactly_5_rows_no_pagination(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_daily_5d_data
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026070{i}") for i in range(1, 6)]
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": rows}), False)
        result = await fetch_ka10081_daily_5d_data(api, "005930", "20260710")
        assert result is not None
        assert len(result["amts_5d_array"]) == 5
        assert api._call_api.call_count == 1


# ── fetch_ka10081_all_stocks_daily_confirmed ────────────────────────────────────

class TestFetchAllStocksDailyConfirmed:
    @pytest.mark.asyncio
    async def test_normal(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_daily_confirmed
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_daily_confirmed(api, ["005930", "005940"], "20260710")
        assert len(result) == 2
        assert "005930" in result
        assert "005940" in result

    @pytest.mark.asyncio
    async def test_empty_list(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_daily_confirmed
        api = _mock_api()
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_daily_confirmed(api, [], "20260710")
        assert result == {}

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_daily_confirmed
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.side_effect = [
            (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False),
            (None, False),
        ]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_daily_confirmed(api, ["005930", "FAIL01"], "20260710")
        assert len(result) == 1
        assert "005930" in result
        assert "FAIL01" not in result

    @pytest.mark.asyncio
    async def test_on_progress_called(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_daily_confirmed
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False)
        progress_calls = []
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            await fetch_ka10081_all_stocks_daily_confirmed(
                api, ["005930"], "20260710",
                on_progress=lambda done, total: progress_calls.append((done, total))
            )
        assert (0, 1) in progress_calls
        assert (1, 1) in progress_calls

    @pytest.mark.asyncio
    async def test_exception_continues(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_daily_confirmed
        api = _mock_api()
        row = _make_daily_row()
        api._call_api.side_effect = [
            Exception("network error"),
            (_mock_resp({"stk_dt_pole_chart_qry": [row]}), False),
        ]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_daily_confirmed(api, ["FAIL01", "005930"], "20260710")
        assert len(result) == 1
        assert "005930" in result


# ── fetch_ka10081_all_stocks_5day ───────────────────────────────────────────────

class TestFetchAllStocks5day:
    @pytest.mark.asyncio
    async def test_normal(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_5day
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026070{i}") for i in range(1, 6)]
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": rows}), False)
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_5day(api, ["005930", "005940"], "20260710")
        assert len(result) == 2
        assert "005930" in result
        assert "005940" in result

    @pytest.mark.asyncio
    async def test_empty_list(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_5day
        api = _mock_api()
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_5day(api, [], "20260710")
        assert result == {}

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_5day
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026070{i}") for i in range(1, 6)]
        api._call_api.side_effect = [
            (_mock_resp({"stk_dt_pole_chart_qry": rows}), False),
            (None, False),
        ]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_5day(api, ["005930", "FAIL01"], "20260710")
        assert len(result) == 1
        assert "005930" in result

    @pytest.mark.asyncio
    async def test_on_progress_called(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_5day
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026070{i}") for i in range(1, 6)]
        api._call_api.return_value = (_mock_resp({"stk_dt_pole_chart_qry": rows}), False)
        progress_calls = []
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            await fetch_ka10081_all_stocks_5day(
                api, ["005930"], "20260710",
                on_progress=lambda done, total: progress_calls.append((done, total))
            )
        assert (0, 1) in progress_calls
        assert (1, 1) in progress_calls

    @pytest.mark.asyncio
    async def test_exception_continues(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10081_all_stocks_5day
        api = _mock_api()
        rows = [_make_daily_row(dt=f"2026070{i}") for i in range(1, 6)]
        api._call_api.side_effect = [
            Exception("network error"),
            (_mock_resp({"stk_dt_pole_chart_qry": rows}), False),
        ]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10081_all_stocks_5day(api, ["FAIL01", "005930"], "20260710")
        assert len(result) == 1
        assert "005930" in result


# ── fetch_ka10099_unified ───────────────────────────────────────────────────────

class TestFetchKa10099Unified:
    @pytest.mark.asyncio
    async def test_normal_single_page(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        items = [
            {"code": "A005930", "name": "삼성전자", "marketCode": "0", "nxtEnable": "Y"},
            {"code": "A005940", "name": "현대차", "marketCode": "0", "nxtEnable": "N"},
        ]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 2
        assert result[0].code == "005930"
        assert result[0].name == "삼성전자"
        assert result[0].market_code == "0"
        assert result[0].nxt_enable is True
        assert result[1].nxt_enable is False

    @pytest.mark.asyncio
    async def test_pagination_2_pages(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        page1 = [{"code": "A005930", "name": "삼성전자"}]
        page2 = [{"code": "A005940", "name": "현대차"}]
        resp1 = _mock_resp({"list": page1}, {"cont-yn": "Y", "next-key": "key123"})
        resp2 = _mock_resp({"list": page2}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp1, False), (resp2, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 2
        assert result[0].code == "005930"
        assert result[1].code == "005940"

    @pytest.mark.asyncio
    async def test_retry_3_times(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        # 첫 2번 실패, 3번째 성공
        resp_ok = _mock_resp({"list": [{"code": "A005930", "name": "삼성전자"}]}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [
            (None, False), (None, False), (resp_ok, False),
            (resp_kosdaq, False),
        ]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 1
        assert result[0].code == "005930"

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        # 코스피 3번 모두 실패, 코스닥 정상
        resp_kosdaq = _mock_resp({"list": [{"code": "A123456", "name": "테스트"}]}, {"cont-yn": "N"})
        api._call_api.side_effect = [
            (None, False), (None, False), (None, False),
            (resp_kosdaq, False),
        ]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        # 코스피 실패, 코스닥 1건
        assert len(result) == 1
        assert result[0].code == "123456"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        resp_kospi = _mock_resp({"list": []}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert result == []

    @pytest.mark.asyncio
    async def test_non_dict_item_skipped(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        items = ["not_a_dict", 123, {"code": "A005930", "name": "삼성전자"}]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 1
        assert result[0].code == "005930"

    @pytest.mark.asyncio
    async def test_empty_code_skipped(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        items = [{"code": "", "name": "빈코드"}, {"code": "A005930", "name": "삼성전자"}]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 1
        assert result[0].code == "005930"

    @pytest.mark.asyncio
    async def test_alphabet_code(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        # lstrip("A")로 A 접두사 제거 → "BCDEF" (kiwoom_stock_rest.py:373)
        items = [{"code": "ABCDEF", "name": "알파벳"}]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 1
        assert result[0].code == "BCDEF"

    @pytest.mark.asyncio
    async def test_name_parsing_multiple_keys(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        items = [
            {"code": "A005930", "name": "이름1"},
            {"code": "A005940", "hname": "이름2"},
            {"code": "A005950", "stk_nm": "이름3"},
        ]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert result[0].name == "이름1"
        assert result[1].name == "이름2"
        assert result[2].name == "이름3"

    @pytest.mark.asyncio
    async def test_nxt_enable_y(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        items = [{"code": "A005930", "name": "삼성전자", "nxtEnable": "Y"}]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert result[0].nxt_enable is True

    @pytest.mark.asyncio
    async def test_nxt_enable_n(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        items = [{"code": "A005930", "name": "삼성전자", "nxtEnable": "N"}]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert result[0].nxt_enable is False

    @pytest.mark.asyncio
    async def test_kosdaq_items(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        resp_kospi = _mock_resp({"list": []}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": [{"code": "A123456", "name": "코스닥종목"}]}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 1
        assert result[0].name == "코스닥종목"

    @pytest.mark.asyncio
    async def test_parsing_exception_breaks(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        resp = _mock_resp()
        resp.json.side_effect = ValueError("bad json")
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        # 코스피 파싱 예외 → 빈 결과, 코스닥도 빈 → 0건
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_short_digit_code_padded(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        items = [{"code": "5930", "name": "짧은코드"}]
        resp_kospi = _mock_resp({"list": items}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert len(result) == 1
        assert result[0].code == "005930"

    @pytest.mark.asyncio
    async def test_raw_item_preserved(self):
        from backend.app.core.kiwoom_stock_rest import fetch_ka10099_unified
        api = _mock_api()
        raw = {"code": "A005930", "name": "삼성전자", "extra": "data"}
        resp_kospi = _mock_resp({"list": [raw]}, {"cont-yn": "N"})
        resp_kosdaq = _mock_resp({"list": []}, {"cont-yn": "N"})
        api._call_api.side_effect = [(resp_kospi, False), (resp_kosdaq, False)]
        with patch("backend.app.core.kiwoom_stock_rest.asyncio.sleep", new=AsyncMock()):
            result = await fetch_ka10099_unified(api)
        assert result[0].raw_item == raw
