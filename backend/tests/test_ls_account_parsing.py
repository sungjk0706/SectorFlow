"""ls_account_parsing.py 단위 테스트 — LS t0424 응답 파싱 검증.

parse_t0424_deposit: 예수금 추출 (sunamt1), 반환 튜플 구조 검증
parse_t0424_balance: 합계 + 종목 배열 파싱, 키움 파싱과 동일 튜플 구조 검증

의존성: numeric_utils._parse_float_loose (순수 함수)
→ 별도 mock 없이 실제 함수 호출 (부작용 없는 순수 파싱)
"""
from __future__ import annotations

import pytest

from backend.app.core.ls_account_parsing import (
    parse_t0424_deposit,
    parse_t0424_balance,
    _strip_a_prefix,
)


# ── t0424 응답 fixture ─────────────────────────────────────────────────────────

def _t0424_response(
    *,
    rsp_cd: str = "00000",
    sunamt1: int = 5_000_000,
    tappamt: int = 12_000_000,
    tdtsunik: int = 1_500_000,
    mamt: int = 10_500_000,
    sunikrt: float = 14.28,
    items: list | None = None,
) -> dict:
    """t0424 표준 응답 생성 — 합계 블록 + 종목 배열."""
    if items is None:
        items = [
            {
                "expcode": "A005930",
                "hname": "삼성전자",
                "janqty": 10,
                "mdposqt": 10,
                "pamt": 70000,
                "price": 75000,
                "mamt": 700000,
                "appamt": 750000,
                "dtsunik": 50000,
                "sunikrt": 7.14,
                "janrt": 6.25,
            },
            {
                "expcode": "A035420",
                "hname": "NAVER",
                "janqty": 5,
                "mdposqt": 5,
                "pamt": 200000,
                "price": 210000,
                "mamt": 1000000,
                "appamt": 1050000,
                "dtsunik": 50000,
                "sunikrt": 5.0,
                "janrt": 8.75,
            },
        ]
    return {
        "rsp_cd": rsp_cd,
        "rsp_msg": "정상처리되었습니다" if rsp_cd == "00000" else "오류",
        "t0424OutBlock": {
            "sunamt1": sunamt1,
            "sunamt": 17_000_000,
            "tappamt": tappamt,
            "tdtsunik": tdtsunik,
            "mamt": mamt,
            "sunikrt": sunikrt,
        },
        "t0424OutBlock1": items,
    }


# ── _strip_a_prefix ────────────────────────────────────────────────────────────

class TestStripAPrefix:
    def test_strips_uppercase_a(self):
        assert _strip_a_prefix("A005930") == "005930"

    def test_strips_lowercase_a(self):
        assert _strip_a_prefix("a005930") == "005930"

    def test_no_prefix(self):
        assert _strip_a_prefix("005930") == "005930"

    def test_empty(self):
        assert _strip_a_prefix("") == ""

    def test_none(self):
        assert _strip_a_prefix(None) == ""


# ── parse_t0424_deposit ────────────────────────────────────────────────────────

class TestParseT0424Deposit:
    def test_success_extracts_sunamt1(self):
        raw = _t0424_response(sunamt1=5_000_000)
        ok, body, deposit, orderable, withdrawable = parse_t0424_deposit(raw)
        assert ok is True
        assert deposit == 5_000_000
        assert orderable == 0  # 실시간 SC1 보완 전 0
        assert withdrawable == 0  # LS 실전 응답 확인 후 보완

    def test_returns_body_block(self):
        raw = _t0424_response()
        ok, body, *_ = parse_t0424_deposit(raw)
        assert ok is True
        assert isinstance(body, dict)
        assert "sunamt1" in body

    def test_empty_raw_returns_failure(self):
        ok, body, deposit, orderable, withdrawable = parse_t0424_deposit(None)
        assert ok is False
        assert body == {}
        assert deposit == 0
        assert orderable == 0
        assert withdrawable == 0

    def test_empty_dict_returns_failure(self):
        ok, body, deposit, *_ = parse_t0424_deposit({})
        assert ok is False
        assert deposit == 0

    def test_error_rsp_cd_returns_failure(self):
        raw = _t0424_response(rsp_cd="99999")
        ok, body, deposit, *_ = parse_t0424_deposit(raw)
        assert ok is False
        assert deposit == 0

    def test_comma_in_sunamt1_parsed(self):
        raw = _t0424_response(sunamt1="1,234,567")
        ok, _, deposit, *_ = parse_t0424_deposit(raw)
        assert ok is True
        assert deposit == 1_234_567

    def test_tuple_length_is_5(self):
        """키움 parse_kt00001_deposit과 동일 튜플 길이 (ok, body, deposit, orderable, withdrawable)."""
        raw = _t0424_response()
        result = parse_t0424_deposit(raw)
        assert isinstance(result, tuple)
        assert len(result) == 5


# ── parse_t0424_balance ────────────────────────────────────────────────────────

class TestParseT0424Balance:
    def test_success_extracts_totals(self):
        raw = _t0424_response(
            tappamt=12_000_000,
            tdtsunik=1_500_000,
            mamt=10_500_000,
            sunikrt=14.28,
        )
        deposit, tot_eval, tot_pnl, tot_buy, total_rate, stock_list = parse_t0424_balance(raw, 5_000_000)
        assert deposit == 5_000_000  # 전달받은 deposit 유지
        assert tot_eval == 12_000_000
        assert tot_pnl == 1_500_000
        assert tot_buy == 10_500_000
        assert total_rate == pytest.approx(14.28)
        assert isinstance(stock_list, list)

    def test_deposit_supplement_from_sunamt1_when_zero(self):
        """deposit이 0으로 전달되면 t0424 합계 sunamt1으로 보완."""
        raw = _t0424_response(sunamt1=3_000_000)
        deposit, *_ = parse_t0424_balance(raw, 0)
        assert deposit == 3_000_000

    def test_stock_list_extracts_items(self):
        raw = _t0424_response()
        _, _, _, _, _, stock_list = parse_t0424_balance(raw, 5_000_000)
        assert len(stock_list) == 2
        samsung = stock_list[0]
        assert samsung["stk_cd"] == "005930"  # A 접두어 제거
        assert samsung["stk_nm"] == "삼성전자"
        assert samsung["qty"] == 10
        assert samsung["avail_qty"] == 10
        assert samsung["avg_price"] == 70000
        assert samsung["cur_price"] == 75000
        assert samsung["buy_amount"] == 700000
        assert samsung["pnl_amount"] == 50000
        assert samsung["pnl_rate"] == pytest.approx(7.14)
        assert samsung["eval_amount"] == 750000
        assert samsung["hold_ratio"] == pytest.approx(6.25)

    def test_stock_list_keys_match_kiwoom(self):
        """키움 parse_kt00018_balance stock_list 항목과 동일 dict 키 검증 (결정 3)."""
        raw = _t0424_response()
        _, _, _, _, _, stock_list = parse_t0424_balance(raw, 5_000_000)
        expected_keys = {
            "stk_cd", "stk_nm", "qty", "avail_qty", "avg_price",
            "cur_price", "buy_amount", "pnl_amount", "pnl_rate",
            "eval_amount", "hold_ratio",
        }
        for item in stock_list:
            assert expected_keys.issubset(item.keys()), f"누락 키: {expected_keys - item.keys()}"

    def test_tuple_length_is_6(self):
        """키움 parse_kt00018_balance와 동일 튜플 길이 (deposit, tot_eval, tot_pnl, tot_buy, total_rate, stock_list)."""
        raw = _t0424_response()
        result = parse_t0424_balance(raw, 5_000_000)
        assert isinstance(result, tuple)
        assert len(result) == 6

    def test_empty_raw_returns_zeros(self):
        deposit, tot_eval, tot_pnl, tot_buy, total_rate, stock_list = parse_t0424_balance(None, 5_000_000)
        assert deposit == 5_000_000
        assert tot_eval == 0
        assert tot_pnl == 0
        assert tot_buy == 0
        assert total_rate == 0.0
        assert stock_list == []

    def test_empty_dict_returns_zeros(self):
        deposit, tot_eval, *_ = parse_t0424_balance({}, 5_000_000)
        assert deposit == 5_000_000
        assert tot_eval == 0

    def test_error_rsp_cd_returns_zeros(self):
        raw = _t0424_response(rsp_cd="99999")
        _, tot_eval, tot_pnl, tot_buy, _, stock_list = parse_t0424_balance(raw, 5_000_000)
        assert tot_eval == 0
        assert tot_pnl == 0
        assert tot_buy == 0
        assert stock_list == []

    def test_zero_qty_item_skipped(self):
        """수량 0 종목은 stock_list에서 제외 (키움 파싱과 동일)."""
        items = [
            {"expcode": "A005930", "hname": "삼성전자", "janqty": 0, "mdposqt": 0,
             "pamt": 70000, "price": 75000, "mamt": 0, "appamt": 0,
             "dtsunik": 0, "sunikrt": 0, "janrt": 0},
            {"expcode": "A035420", "hname": "NAVER", "janqty": 5, "mdposqt": 5,
             "pamt": 200000, "price": 210000, "mamt": 1000000, "appamt": 1050000,
             "dtsunik": 50000, "sunikrt": 5.0, "janrt": 8.75},
        ]
        raw = _t0424_response(items=items)
        _, _, _, _, _, stock_list = parse_t0424_balance(raw, 5_000_000)
        assert len(stock_list) == 1
        assert stock_list[0]["stk_cd"] == "035420"

    def test_missing_expcode_skipped(self):
        """종목번호 없는 항목은 제외."""
        items = [
            {"expcode": "", "hname": "빈종목", "janqty": 10, "mdposqt": 10,
             "pamt": 70000, "price": 75000, "mamt": 700000, "appamt": 750000,
             "dtsunik": 50000, "sunikrt": 7.14, "janrt": 6.25},
            {"expcode": "A005930", "hname": "삼성전자", "janqty": 10, "mdposqt": 10,
             "pamt": 70000, "price": 75000, "mamt": 700000, "appamt": 750000,
             "dtsunik": 50000, "sunikrt": 7.14, "janrt": 6.25},
        ]
        raw = _t0424_response(items=items)
        _, _, _, _, _, stock_list = parse_t0424_balance(raw, 5_000_000)
        assert len(stock_list) == 1

    def test_dict_items_wrapped_to_list(self):
        """t0424OutBlock1이 단일 dict로 오는 경우 리스트로 래핑 처리."""
        items = {"expcode": "A005930", "hname": "삼성전자", "janqty": 10, "mdposqt": 10,
                 "pamt": 70000, "price": 75000, "mamt": 700000, "appamt": 750000,
                 "dtsunik": 50000, "sunikrt": 7.14, "janrt": 6.25}
        raw = _t0424_response(items=items)  # type: ignore[arg-type]
        _, _, _, _, _, stock_list = parse_t0424_balance(raw, 5_000_000)
        assert len(stock_list) == 1
        assert stock_list[0]["stk_cd"] == "005930"

    def test_comma_in_numeric_fields_parsed(self):
        """숫자 필드의 콤마(,) 정상 파싱."""
        items = [
            {"expcode": "A005930", "hname": "삼성전자", "janqty": "1,000", "mdposqt": "1,000",
             "pamt": "70,000", "price": "75,000", "mamt": "70,000,000", "appamt": "75,000,000",
             "dtsunik": "5,000,000", "sunikrt": "7.14", "janrt": "6.25"},
        ]
        raw = _t0424_response(items=items)
        _, _, _, _, _, stock_list = parse_t0424_balance(raw, 5_000_000)
        assert stock_list[0]["qty"] == 1000
        assert stock_list[0]["avg_price"] == 70000
        assert stock_list[0]["buy_amount"] == 70_000_000
        assert stock_list[0]["pnl_amount"] == 5_000_000
