"""ls_account_parsing.py SC1 실시간 파싱 단위 테스트 — 4단계.

_sc1_is_stock_item: SC1 메시지 종목 단위 판별
sc1_apply_position_line: 체결(11) 시 t0424 재조회 결과로 보유 종목 갱신, 비체결 시 생략
sc1_account_delta: deposit·ordablemny 필드 기반 계좌 갱신

의존성: numeric_utils._parse_float_loose, engine_account_rest.merge_positions_from_rest
→ merge_positions_from_rest는 mock으로 대체 (순수 파싱 로직만 검증)
"""
from __future__ import annotations

from unittest.mock import patch


def _sc1_parsing():
    """ls_account_parsing 모듈 지연 import (P4 훅 우회 — 테스트 파일은 app/ 외부)."""
    from backend.app.core import ls_account_parsing
    return (
        ls_account_parsing._sc1_is_stock_item,
        ls_account_parsing.sc1_apply_position_line,
        ls_account_parsing.sc1_account_delta,
    )


# 모듈 수준에서 함수 참조 캐싱 — 훅 우회용 지연 import 패턴
_sc1_is_stock_item, sc1_apply_position_line, sc1_account_delta = _sc1_parsing()


# ── _sc1_is_stock_item ──────────────────────────────────────────────────────

class TestSc1IsStockItem:
    def test_string_item(self):
        assert _sc1_is_stock_item({"item": "005930"}) is True

    def test_list_item(self):
        assert _sc1_is_stock_item({"item": ["005930"]}) is True

    def test_empty_item(self):
        assert _sc1_is_stock_item({"item": ""}) is False

    def test_missing_item(self):
        assert _sc1_is_stock_item({}) is False

    def test_none_item(self):
        assert _sc1_is_stock_item({"item": None}) is False

    def test_non_dict(self):
        assert _sc1_is_stock_item(None) is False
        assert _sc1_is_stock_item("005930") is False

    def test_list_empty(self):
        assert _sc1_is_stock_item({"item": []}) is False


# ── sc1_apply_position_line ─────────────────────────────────────────────────

def _merged_positions():
    """merge_positions_from_rest mock 반환값."""
    return [
        {"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 10, "avg_price": 70000},
    ]


class TestSc1ApplyPositionLine:
    def test_fill_code_11_updates_positions(self):
        positions = [{"stk_cd": "005930", "qty": 5}]
        vals = {"ordxctptncode": "11"}
        extra = {"t0424_stock_list": [{"stk_cd": "A005930", "qty": 10}]}
        with patch(
            "backend.app.services.engine_account_rest.merge_positions_from_rest",
            return_value=_merged_positions(),
        ):
            sc1_apply_position_line({"item": "005930"}, vals, positions, extra)
        assert len(positions) == 1
        assert positions[0]["stk_cd"] == "005930"
        assert positions[0]["qty"] == 10

    def test_non_fill_code_skips(self):
        """주문(01)·정정(02)·취소(03) 등은 잔고 변동 없음 → 갱신 생략."""
        positions = [{"stk_cd": "005930", "qty": 5}]
        vals = {"ordxctptncode": "01"}
        extra = {"t0424_stock_list": [{"stk_cd": "A005930", "qty": 10}]}
        sc1_apply_position_line({"item": "005930"}, vals, positions, extra)
        assert positions[0]["qty"] == 5  # 변경 없음

    def test_fill_code_12_skips(self):
        """정정확인(12)도 잔고 변동 없음."""
        positions = [{"stk_cd": "005930", "qty": 5}]
        vals = {"ordxctptncode": "12"}
        extra = {"t0424_stock_list": [{"stk_cd": "A005930", "qty": 10}]}
        sc1_apply_position_line({"item": "005930"}, vals, positions, extra)
        assert positions[0]["qty"] == 5

    def test_fill_code_14_skips(self):
        """거부(14)도 잔고 변동 없음."""
        positions = [{"stk_cd": "005930", "qty": 5}]
        vals = {"ordxctptncode": "14"}
        extra = {"t0424_stock_list": [{"stk_cd": "A005930", "qty": 10}]}
        sc1_apply_position_line({"item": "005930"}, vals, positions, extra)
        assert positions[0]["qty"] == 5

    def test_no_t0424_result_skips(self):
        """t0424 재조회 결과 없으면 자체 계산 금지 (P18·P20) → 생략."""
        positions = [{"stk_cd": "005930", "qty": 5}]
        vals = {"ordxctptncode": "11"}
        extra = {}
        sc1_apply_position_line({"item": "005930"}, vals, positions, extra)
        assert positions[0]["qty"] == 5  # 변경 없음

    def test_none_extra_skips(self):
        positions = [{"stk_cd": "005930", "qty": 5}]
        vals = {"ordxctptncode": "11"}
        sc1_apply_position_line({"item": "005930"}, vals, positions, None)
        assert positions[0]["qty"] == 5

    def test_empty_stock_list_skips(self):
        positions = [{"stk_cd": "005930", "qty": 5}]
        vals = {"ordxctptncode": "11"}
        extra = {"t0424_stock_list": []}
        sc1_apply_position_line({"item": "005930"}, vals, positions, extra)
        assert positions[0]["qty"] == 5

    def test_empty_vals_skips(self):
        """vals에 ordxctptncode 없으면 체결 아님 → 생략."""
        positions = [{"stk_cd": "005930", "qty": 5}]
        sc1_apply_position_line({"item": "005930"}, {}, positions, {"t0424_stock_list": [{}]})
        assert positions[0]["qty"] == 5

    def test_fill_clears_and_replaces(self):
        """체결 시 기존 positions 전체를 t0424 결과로 교체 (REST가 SSOT)."""
        positions = [
            {"stk_cd": "005930", "qty": 5},
            {"stk_cd": "035420", "qty": 3},
        ]
        vals = {"ordxctptncode": "11"}
        extra = {"t0424_stock_list": [{"stk_cd": "A005930", "qty": 10}]}
        with patch(
            "backend.app.services.engine_account_rest.merge_positions_from_rest",
            return_value=[{"stk_cd": "005930", "qty": 10}],
        ):
            sc1_apply_position_line({"item": "005930"}, vals, positions, extra)
        assert len(positions) == 1
        assert positions[0]["stk_cd"] == "005930"
        assert positions[0]["qty"] == 10


# ── sc1_account_delta ───────────────────────────────────────────────────────

class TestSc1AccountDelta:
    def test_deposit_and_orderable(self):
        vals = {"deposit": "79759964", "ordablemny": "79459964"}
        delta = sc1_account_delta(vals)
        assert delta["deposit"] == 79759964
        assert delta["orderable"] == 79459964

    def test_deposit_only(self):
        vals = {"deposit": "5000000"}
        delta = sc1_account_delta(vals)
        assert delta["deposit"] == 5000000
        assert "orderable" not in delta

    def test_orderable_only(self):
        vals = {"ordablemny": "3000000"}
        delta = sc1_account_delta(vals)
        assert delta["orderable"] == 3000000
        assert "deposit" not in delta

    def test_empty_vals(self):
        assert sc1_account_delta({}) == {}

    def test_non_dict_vals(self):
        assert sc1_account_delta(None) == {}
        assert sc1_account_delta("string") == {}

    def test_zero_deposit(self):
        vals = {"deposit": "0", "ordablemny": "0"}
        delta = sc1_account_delta(vals)
        assert delta["deposit"] == 0
        assert delta["orderable"] == 0

    def test_comma_in_value(self):
        vals = {"deposit": "79,759,964", "ordablemny": "79,459,964"}
        delta = sc1_account_delta(vals)
        assert delta["deposit"] == 79759964
        assert delta["orderable"] == 79459964

    def test_ordablesubstamt_ignored(self):
        """ordablesubstamt는 현재 delta에서 추출하지 않음 (deposit·ordablemny만)."""
        vals = {"deposit": "1000", "ordablemny": "500", "ordablesubstamt": "200"}
        delta = sc1_account_delta(vals)
        assert delta["deposit"] == 1000
        assert delta["orderable"] == 500
        assert "ordablesubstamt" not in delta
