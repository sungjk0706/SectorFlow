"""engine_account_rest.py 단위 테스트 — REST 파싱·포지션 병합·스냅샷 메타 계산 순수 함수 검증.

모든 함수는 전역 상태 없이 입력→출력만 검증한다.
"""
from __future__ import annotations

from backend.app.services.engine_account_rest import (
    _parse_int_loose,
    _parse_float_loose,
    merge_positions_from_rest,
    broker_totals_from_summary,
    recalc_broker_totals_from_positions,
    _real04_is_stock_item,
    real04_official_account_delta,
    real04_official_apply_position_line,
    build_account_snapshot_meta,
    apply_last_price_to_positions_inplace,
    parse_kt00001_deposit,
    parse_kt00018_balance,
)


# ── _parse_int_loose ─────────────────────────────────────────────────────────────

class TestParseIntLoose:
    def test_plain(self):
        assert _parse_int_loose("1000") == 1000

    def test_with_comma(self):
        assert _parse_int_loose("1,000") == 1000

    def test_int_input(self):
        assert _parse_int_loose(500) == 500

    def test_none(self):
        assert _parse_int_loose(None) == 0

    def test_empty(self):
        assert _parse_int_loose("") == 0

    def test_invalid(self):
        assert _parse_int_loose("abc") == 0


# ── _parse_float_loose ────────────────────────────────────────────────────────────

class TestParseFloatLoose:
    def test_plain(self):
        assert _parse_float_loose("1.5") == 1.5

    def test_with_comma(self):
        assert _parse_float_loose("1,500.5") == 1500.5

    def test_with_percent(self):
        assert _parse_float_loose("1.5%") == 1.5

    def test_with_plus(self):
        assert _parse_float_loose("+1.5") == 1.5

    def test_none(self):
        assert _parse_float_loose(None) == 0.0

    def test_empty(self):
        assert _parse_float_loose("") == 0.0

    def test_invalid(self):
        assert _parse_float_loose("abc") == 0.0


# ── merge_positions_from_rest ─────────────────────────────────────────────────────

class TestMergePositionsFromRest:
    def test_empty_list(self):
        assert merge_positions_from_rest([], {}) == []

    def test_non_dict_skipped(self):
        assert merge_positions_from_rest(["not_dict"], {}) == []

    def test_missing_stk_cd_skipped(self):
        assert merge_positions_from_rest([{"qty": "100"}], {}) == []

    def test_zero_qty_skipped(self):
        result = merge_positions_from_rest([{"stk_cd": "005930", "qty": "0"}], {})
        assert result == []

    def test_basic_merge(self):
        stock_list = [{"stk_cd": "005930", "stk_nm": "삼성전자", "qty": "100", "buy_price": "70000"}]
        result = merge_positions_from_rest(stock_list, {})
        assert len(result) == 1
        pos = result[0]
        assert pos["stk_cd"] == "005930"
        assert pos["stk_nm"] == "삼성전자"
        assert pos["qty"] == 100
        assert pos["buy_price"] == 70000
        assert pos["buy_amount"] == 70000 * 100  # buy * qty

    def test_al_suffix_stripped(self):
        result = merge_positions_from_rest([{"stk_cd": "005930_AL", "qty": "10"}], {})
        assert result[0]["stk_cd"] == "005930"

    def test_buy_amount_from_field(self):
        stock_list = [{"stk_cd": "005930", "qty": "100", "buy_amount": "5000000"}]
        result = merge_positions_from_rest(stock_list, {})
        assert result[0]["buy_amount"] == 5000000

    def test_avail_qty_defaults_to_qty(self):
        stock_list = [{"stk_cd": "005930", "qty": "50"}]
        result = merge_positions_from_rest(stock_list, {})
        assert result[0]["avail_qty"] == 50


# ── broker_totals_from_summary ────────────────────────────────────────────────────

class TestBrokerTotalsFromSummary:
    def test_full_summary(self):
        summary = {"tot_eval": 10000000, "tot_pnl": 500000, "tot_buy": 9500000, "total_rate": 5.26}
        result = broker_totals_from_summary(summary)
        assert result == {
            "total_eval": 10000000,
            "total_pnl": 500000,
            "total_buy": 9500000,
            "total_rate": 5.26,
        }

    def test_empty_summary(self):
        result = broker_totals_from_summary({})
        assert result == {"total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_rate": 0.0}

    def test_string_values(self):
        summary = {"tot_eval": "10000000", "tot_pnl": "500000"}
        result = broker_totals_from_summary(summary)
        assert result["total_eval"] == 10000000
        assert result["total_pnl"] == 500000


# ── recalc_broker_totals_from_positions ───────────────────────────────────────────

class TestRecalcBrokerTotalsFromPositions:
    def test_empty_positions(self):
        result = recalc_broker_totals_from_positions([], {"total_buy": 1000})
        assert result["total_eval"] == 0
        assert result["total_pnl"] == 0
        assert result["total_buy"] == 1000  # REST 기준 유지
        assert result["total_rate"] == 0.0

    def test_with_positions(self):
        positions = [
            {"qty": 10, "eval_amount": 800000, "buy_amount": 700000, "pnl_amount": 100000},
            {"qty": 5, "eval_amount": 400000, "buy_amount": 350000, "pnl_amount": 50000},
        ]
        result = recalc_broker_totals_from_positions(positions, {"total_buy": 1050000})
        assert result["total_eval"] == 1200000
        assert result["total_pnl"] == 150000
        assert result["total_buy"] == 1050000  # REST 기준 유지
        assert result["total_rate"] == round(150000 / 1050000 * 100, 2)

    def test_zero_qty_skipped(self):
        positions = [{"qty": 0, "eval_amount": 100, "buy_amount": 50, "pnl_amount": 10}]
        result = recalc_broker_totals_from_positions(positions, {"total_buy": 50})
        assert result["total_eval"] == 0
        assert result["total_pnl"] == 0


# ── _real04_is_stock_item ──────────────────────────────────────────────────────────

class TestReal04IsStockItem:
    def test_stock_code_with_alpha(self):
        assert _real04_is_stock_item({"item": "A005930"}) is True

    def test_stock_code_list(self):
        assert _real04_is_stock_item({"item": ["A005930"]}) is True

    def test_account_number_digits(self):
        assert _real04_is_stock_item({"item": "12345678"}) is False

    def test_empty_item(self):
        assert _real04_is_stock_item({"item": ""}) is False

    def test_missing_item(self):
        assert _real04_is_stock_item({}) is False

    def test_none_item(self):
        assert _real04_is_stock_item({"item": None}) is False


# ── real04_official_account_delta ──────────────────────────────────────────────────

class TestReal04OfficialAccountDelta:
    def test_all_fids(self):
        vals = {"930": "5000000", "932": "10000000", "933": "500000", "934": "5.5"}
        result = real04_official_account_delta(vals)
        assert result == {
            "deposit": 5000000,
            "total_eval": 10000000,
            "total_pnl": 500000,
            "total_rate": 5.5,
        }

    def test_partial_fids(self):
        vals = {"930": "3000000"}
        result = real04_official_account_delta(vals)
        assert result == {"deposit": 3000000}

    def test_empty(self):
        assert real04_official_account_delta({}) == {}

    def test_non_dict(self):
        assert real04_official_account_delta(None) == {}


# ── real04_official_apply_position_line ────────────────────────────────────────────

class TestReal04OfficialApplyPositionLine:
    def test_new_position_added(self):
        item = {"item": "A005930", "9001": "005930"}
        vals = {"930": "100", "931": "70000", "932": "7000000", "10": "80000", "302": "삼성전자"}
        positions = []
        real04_official_apply_position_line(item, vals, positions, {})
        assert len(positions) == 1
        pos = positions[0]
        assert pos["stk_cd"] == "005930"
        assert pos["stk_nm"] == "삼성전자"
        assert pos["qty"] == 100
        assert pos["buy_price"] == 70000
        assert pos["cur_price"] == 80000
        assert pos["eval_amount"] == 80000 * 100

    def test_zero_qty_not_added(self):
        item = {"item": "A005930", "9001": "005930"}
        vals = {"930": "0"}
        positions = []
        real04_official_apply_position_line(item, vals, positions, {})
        assert len(positions) == 0

    def test_existing_position_updated(self):
        item = {"item": "A005930", "9001": "005930"}
        vals = {"930": "200", "931": "75000", "932": "15000000", "10": "85000", "302": "삼성전자"}
        positions = [{"stk_cd": "005930", "stk_nm": "삼성전자", "qty": 100, "buy_price": 70000,
                       "cur_price": 80000, "buy_amount": 7000000, "eval_amount": 8000000,
                       "pnl_amount": 1000000, "pnl_rate": 14.29, "avail_qty": 100}]
        real04_official_apply_position_line(item, vals, positions, {})
        assert len(positions) == 1
        pos = positions[0]
        assert pos["qty"] == 200
        assert pos["buy_price"] == 75000
        assert pos["cur_price"] == 85000
        assert pos["eval_amount"] == 85000 * 200

    def test_prefer_01_price_over_fid10(self):
        item = {"item": "A005930", "9001": "005930"}
        vals = {"930": "100", "10": "80000"}
        positions = []
        real04_official_apply_position_line(item, vals, positions, {"005930": 90000})
        assert positions[0]["cur_price"] == 90000

    def test_empty_item_no_change(self):
        positions = [{"stk_cd": "005930", "qty": 10}]
        real04_official_apply_position_line({}, {}, positions, {})
        assert len(positions) == 1


# ── build_account_snapshot_meta ────────────────────────────────────────────────────

class TestBuildAccountSnapshotMeta:
    def test_basic(self):
        snap = {"broker": "kiwoom", "deposit": 5000000, "orderable": 4000000, "initial_deposit": 5000000}
        totals = {"total_eval": 10000000, "total_pnl": 500000, "total_buy": 9500000, "total_sell": 0, "total_rate": 5.26}
        positions = [{"qty": 10}, {"qty": 5}]
        result = build_account_snapshot_meta(snap, totals, positions, True, "real")
        assert result["broker"] == "kiwoom"
        assert result["trade_mode"] == "real"
        assert result["deposit"] == 5000000
        assert result["total_eval"] == 10000000
        assert result["total_pnl"] == 500000
        assert result["total_buy"] == 9500000
        assert result["total_rate"] == 5.26
        assert result["total_buy_amount"] == 9500000
        assert result["total_eval_amount"] == 10000000
        assert result["total_pnl_rate"] == 5.26
        assert result["position_count"] == 2
        assert result["price_source"] == "websocket"

    def test_price_source_rest(self):
        result = build_account_snapshot_meta({}, {"total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_sell": 0, "total_rate": 0.0}, [], False, "test")
        assert result["price_source"] == "rest_bootstrap"
        assert result["trade_mode"] == "test"

    def test_zero_qty_not_counted(self):
        positions = [{"qty": 10}, {"qty": 0}, {"qty": 5}]
        result = build_account_snapshot_meta({}, {"total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_sell": 0, "total_rate": 0.0}, positions, True, "real")
        assert result["position_count"] == 2


# ── apply_last_price_to_positions_inplace ───────────────────────────────────────────

class TestApplyLastPriceToPositionsInplace:
    def test_price_updated(self):
        positions = [{"stk_cd": "005930", "qty": 10, "cur_price": 70000, "buy_amount": 700000}]
        result = apply_last_price_to_positions_inplace(positions, "005930", 80000)
        assert result is True
        assert positions[0]["cur_price"] == 80000
        assert positions[0]["eval_amount"] == 80000 * 10
        assert positions[0]["pnl_amount"] == 80000 * 10 - 700000

    def test_no_change(self):
        positions = [{"stk_cd": "005930", "qty": 10, "cur_price": 80000, "buy_amount": 700000}]
        result = apply_last_price_to_positions_inplace(positions, "005930", 80000)
        assert result is False

    def test_zero_price(self):
        positions = [{"stk_cd": "005930", "qty": 10, "cur_price": 70000}]
        result = apply_last_price_to_positions_inplace(positions, "005930", 0)
        assert result is False

    def test_not_found(self):
        positions = [{"stk_cd": "005930", "qty": 10, "cur_price": 70000}]
        result = apply_last_price_to_positions_inplace(positions, "999999", 80000)
        assert result is False

    def test_al_suffix_match(self):
        positions = [{"stk_cd": "005930", "qty": 10, "cur_price": 70000, "buy_amount": 700000}]
        result = apply_last_price_to_positions_inplace(positions, "005930_AL", 80000)
        assert result is True

    def test_with_cmsn_and_tax(self):
        positions = [{"stk_cd": "005930", "qty": 10, "cur_price": 70000, "buy_amount": 700000, "sum_cmsn": 5000, "tax": 3000}]
        result = apply_last_price_to_positions_inplace(positions, "005930", 80000)
        assert result is True
        assert positions[0]["pnl_amount"] == 80000 * 10 - 700000
        assert positions[0]["total_fee"] == 5000
        assert positions[0]["buy_amt"] == 700000 + 5000


# ── parse_kt00001_deposit ───────────────────────────────────────────────────────────

class TestParseKt00001Deposit:
    def test_success(self):
        raw = {"body": {"return_code": "0", "entr": "5000000", "ord_alow_amt": "4000000", "pymn_alow_amt": "3000000"}}
        ok, body, dep, orderable, withdrawable = parse_kt00001_deposit(raw)
        assert ok is True
        assert dep == 5000000
        assert orderable == 4000000
        assert withdrawable == 3000000

    def test_d2_entra_fallback(self):
        raw = {"body": {"return_code": "0", "d2_entra": "2000000", "ord_alow_amt": "1000000", "pymn_alow_amt": "500000"}}
        ok, body, dep, orderable, withdrawable = parse_kt00001_deposit(raw)
        assert ok is True
        assert dep == 2000000

    def test_error_return_code(self):
        raw = {"body": {"return_code": "1"}}
        ok, body, dep, orderable, withdrawable = parse_kt00001_deposit(raw)
        assert ok is False
        assert dep == 0

    def test_none_input(self):
        ok, body, dep, orderable, withdrawable = parse_kt00001_deposit(None)
        assert ok is False
        assert dep == 0

    def test_no_body_key(self):
        raw = {"return_code": "0", "entr": "5000000", "ord_alow_amt": "4000000", "pymn_alow_amt": "3000000"}
        ok, body, dep, orderable, withdrawable = parse_kt00001_deposit(raw)
        assert ok is True
        assert dep == 5000000


# ── parse_kt00018_balance ───────────────────────────────────────────────────────────

class TestParseKt00018Balance:
    def test_success(self):
        raw = {
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "10000000",
                "tot_evlt_pl": "500000",
                "tot_pur_amt": "9500000",
                "tot_prft_rt": "5.26",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "005930", "stk_nm": "삼성전자", "rmnd_qty": "100", "pur_pric": "70000", "cur_prc": "80000", "pur_amt": "7000000", "evltv_prft": "1000000", "prft_rt": "14.29"},
                ],
            }
        }
        dep, tot_eval, tot_pnl, tot_buy, total_rate, stock_list = parse_kt00018_balance(raw, 5000000)
        assert dep == 5000000
        assert tot_eval == 10000000
        assert tot_pnl == 500000
        assert tot_buy == 9500000
        assert total_rate == 5.26
        assert len(stock_list) == 1
        assert stock_list[0]["stk_cd"] == "005930"
        assert stock_list[0]["qty"] == 100

    def test_none_input(self):
        dep, tot_eval, tot_pnl, tot_buy, total_rate, stock_list = parse_kt00018_balance(None, 5000000)
        assert dep == 5000000
        assert tot_eval == 0
        assert stock_list == []

    def test_error_return_code(self):
        raw = {"body": {"return_code": "1", "acnt_evlt_remn_indv_tot": []}}
        dep, tot_eval, tot_pnl, tot_buy, total_rate, stock_list = parse_kt00018_balance(raw, 5000000)
        assert tot_eval == 0
        assert stock_list == []

    def test_zero_qty_skipped(self):
        raw = {
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "0",
                "tot_evlt_pl": "0",
                "tot_pur_amt": "0",
                "tot_prft_rt": "0",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "005930", "rmnd_qty": "0"},
                ],
            }
        }
        _, _, _, _, _, stock_list = parse_kt00018_balance(raw, 0)
        assert stock_list == []

    def test_deposit_fallback_from_balance(self):
        raw = {
            "body": {
                "return_code": "0",
                "tot_evlt_amt": "0",
                "tot_evlt_pl": "0",
                "tot_pur_amt": "0",
                "tot_prft_rt": "0",
                "prsm_dpst_aset_amt": "3000000",
                "acnt_evlt_remn_indv_tot": [],
            }
        }
        dep, _, _, _, _, _ = parse_kt00018_balance(raw, 0)
        assert dep == 3000000
