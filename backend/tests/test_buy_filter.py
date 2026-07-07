"""buy_filter.py 단위 테스트 — 매수 후보 필터링 및 타겟 생성 로직 검증.

check_stock_guards, calculate_boost_score, create_buy_targets의
가드 필터링, 가산점 계산, 정렬, 타겟 분류 로직을 검증.
"""
from __future__ import annotations

import pytest

from backend.app.domain.models import StockScore, SectorScore, BuyTarget, SectorSummary
from backend.app.domain.buy_filter import (
    calculate_boost_score,
    check_stock_guards,
    create_buy_targets,
)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _stock(
    code: str = "005930",
    name: str = "삼성전자",
    sector: str = "반도체",
    change_rate: float = 1.0,
    trade_amount: int = 1_000_000_000,
    avg_amt_5d: int = 40,
    ratio_5d_pct: float = 10.0,
    strength: float = 100.0,
    cur_price: int = 70000,
    change: int = 700,
    market_type: str = "0",
    nxt_enable: bool = False,
) -> StockScore:
    return StockScore(
        code=code,
        name=name,
        sector=sector,
        change_rate=change_rate,
        trade_amount=trade_amount,
        avg_amt_5d=avg_amt_5d,
        ratio_5d_pct=ratio_5d_pct,
        strength=strength,
        cur_price=cur_price,
        change=change,
        market_type=market_type,
        nxt_enable=nxt_enable,
    )


def _sector(
    sector: str = "반도체",
    rank: int = 1,
    stocks: list[StockScore] | None = None,
    total: int = 3,
    rise_count: int = 2,
    rise_ratio: float = 0.67,
    avg_change_rate: float = 1.0,
    total_trade_amount: int = 3_000_000_000,
    avg_ratio_5d_pct: float = 10.0,
    scored_trade_amount: int = 3_000_000_000,
    scored_rise_ratio: float = 0.67,
) -> SectorScore:
    return SectorScore(
        sector=sector,
        total=total,
        rise_count=rise_count,
        rise_ratio=rise_ratio,
        avg_change_rate=avg_change_rate,
        total_trade_amount=total_trade_amount,
        avg_ratio_5d_pct=avg_ratio_5d_pct,
        rank=rank,
        stocks=stocks or [],
        scored_trade_amount=scored_trade_amount,
        scored_rise_ratio=scored_rise_ratio,
    )


# ── check_stock_guards ─────────────────────────────────────────────────────────

class TestCheckStockGuards:
    def test_pass_all_guards(self):
        stock = _stock(change_rate=2.0, strength=100.0)
        result = check_stock_guards(stock, block_rise_pct=7.0, block_fall_pct=7.0, min_strength=0.0)
        assert result.guard_pass is True
        assert result.guard_reason == ""

    def test_block_by_rise_pct(self):
        stock = _stock(change_rate=7.0)
        result = check_stock_guards(stock, block_rise_pct=7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "상승률"

    def test_block_by_rise_pct_above_threshold(self):
        stock = _stock(change_rate=8.5)
        result = check_stock_guards(stock, block_rise_pct=7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "상승률"

    def test_pass_just_below_rise_threshold(self):
        stock = _stock(change_rate=6.9)
        result = check_stock_guards(stock, block_rise_pct=7.0)
        assert result.guard_pass is True

    def test_block_by_fall_pct(self):
        stock = _stock(change_rate=-7.0)
        result = check_stock_guards(stock, block_fall_pct=7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "하락률"

    def test_block_by_fall_pct_below_threshold(self):
        stock = _stock(change_rate=-8.0)
        result = check_stock_guards(stock, block_fall_pct=7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "하락률"

    def test_pass_just_above_fall_threshold(self):
        stock = _stock(change_rate=-6.9)
        result = check_stock_guards(stock, block_fall_pct=7.0)
        assert result.guard_pass is True

    def test_block_by_min_strength(self):
        stock = _stock(strength=50.0)
        result = check_stock_guards(stock, min_strength=80.0)
        assert result.guard_pass is False
        assert result.guard_reason == "체결강도"

    def test_pass_min_strength_equal(self):
        stock = _stock(strength=80.0)
        result = check_stock_guards(stock, min_strength=80.0)
        assert result.guard_pass is True

    def test_min_strength_zero_disables_check(self):
        stock = _stock(strength=10.0)
        result = check_stock_guards(stock, min_strength=0.0)
        assert result.guard_pass is True

    def test_strength_minus_one_skips_strength_check(self):
        stock = _stock(strength=-1.0)
        result = check_stock_guards(stock, min_strength=80.0)
        assert result.guard_pass is True

    def test_rise_takes_priority_over_fall(self):
        stock = _stock(change_rate=7.0)
        result = check_stock_guards(stock, block_rise_pct=7.0, block_fall_pct=7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "상승률"

    def test_mutates_stock_in_place(self):
        stock = _stock(change_rate=10.0)
        result = check_stock_guards(stock, block_rise_pct=7.0)
        assert result is stock
        assert stock.guard_pass is False


# ── calculate_boost_score ──────────────────────────────────────────────────────

class TestCalculateBoostScore:
    def test_all_off_returns_zero(self):
        stock = _stock()
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
        )
        assert score == 0.0

    def test_high_breakout_boost(self):
        stock = _stock(code="005930", cur_price=75000)
        score = calculate_boost_score(
            stock,
            high_5d_cache={"005930": 70000},
            orderbook_cache={},
            program_net_buy_cache={},
            boost_high_on=True,
            boost_high_score=2.0,
        )
        assert score == 2.0

    def test_high_breakout_no_boost_when_below_high(self):
        stock = _stock(code="005930", cur_price=65000)
        score = calculate_boost_score(
            stock,
            high_5d_cache={"005930": 70000},
            orderbook_cache={},
            program_net_buy_cache={},
            boost_high_on=True,
            boost_high_score=1.0,
        )
        assert score == 0.0

    def test_high_breakout_no_boost_when_high_zero(self):
        stock = _stock(code="005930", cur_price=75000)
        score = calculate_boost_score(
            stock,
            high_5d_cache={"005930": 0},
            orderbook_cache={},
            program_net_buy_cache={},
            boost_high_on=True,
            boost_high_score=1.0,
        )
        assert score == 0.0

    def test_order_ratio_boost_positive_pct(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={"005930": (150, 100)},
            program_net_buy_cache={},
            boost_order_ratio_on=True,
            boost_order_ratio_pct=20.0,
            boost_order_ratio_score=1.5,
        )
        assert score == 1.5

    def test_order_ratio_no_boost_when_ratio_below_threshold(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={"005930": (110, 100)},
            program_net_buy_cache={},
            boost_order_ratio_on=True,
            boost_order_ratio_pct=20.0,
            boost_order_ratio_score=1.0,
        )
        assert score == 0.0

    def test_order_ratio_boost_negative_pct(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={"005930": (100, 150)},
            program_net_buy_cache={},
            boost_order_ratio_on=True,
            boost_order_ratio_pct=-20.0,
            boost_order_ratio_score=1.0,
        )
        assert score == 1.0

    def test_order_ratio_no_boost_when_denominator_zero(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={"005930": (100, 0)},
            program_net_buy_cache={},
            boost_order_ratio_on=True,
            boost_order_ratio_pct=20.0,
            boost_order_ratio_score=1.0,
        )
        assert score == 0.0

    def test_program_net_buy_boost(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={"005930": 500_000_000},
            boost_program_net_buy_on=True,
            boost_program_net_buy_score=1.0,
        )
        assert score == 1.0

    def test_program_net_buy_no_boost_when_zero(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={"005930": 0},
            boost_program_net_buy_on=True,
            boost_program_net_buy_score=1.0,
        )
        assert score == 0.0

    def test_trade_amount_rank_boost_first_place(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
            trade_amount_rank=0,
            boost_trade_amount_rank_on=True,
            boost_trade_amount_rank_score=2.0,
        )
        assert score == 2.0

    def test_trade_amount_rank_no_boost_when_not_first(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
            trade_amount_rank=1,
            boost_trade_amount_rank_on=True,
            boost_trade_amount_rank_score=1.0,
        )
        assert score == 0.0

    def test_multiple_boosts_accumulate(self):
        stock = _stock(code="005930", cur_price=75000)
        score = calculate_boost_score(
            stock,
            high_5d_cache={"005930": 70000},
            orderbook_cache={"005930": (150, 100)},
            program_net_buy_cache={"005930": 500_000_000},
            boost_high_on=True,
            boost_high_score=1.0,
            boost_order_ratio_on=True,
            boost_order_ratio_pct=20.0,
            boost_order_ratio_score=1.0,
            boost_program_net_buy_on=True,
            boost_program_net_buy_score=1.0,
        )
        assert score == 3.0

    def test_score_never_negative(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
        )
        assert score >= 0.0


# ── create_buy_targets ─────────────────────────────────────────────────────────

class TestCreateBuyTargets:
    def test_empty_sector_scores_returns_empty(self):
        result = create_buy_targets([])
        assert result.buy_targets == []
        assert result.blocked_targets == []
        assert result.sectors == []

    def test_rank_zero_sectors_excluded(self):
        s1 = _stock(code="A001", change_rate=1.0)
        sc = _sector(rank=0, stocks=[s1])
        result = create_buy_targets([sc])
        assert result.buy_targets == []
        assert result.blocked_targets == []

    def test_max_sectors_limit(self):
        stocks_a = [_stock(code="A001", change_rate=1.0)]
        stocks_b = [_stock(code="A002", change_rate=2.0)]
        stocks_c = [_stock(code="A003", change_rate=3.0)]
        sectors = [
            _sector(sector="A", rank=1, stocks=stocks_a),
            _sector(sector="B", rank=2, stocks=stocks_b),
            _sector(sector="C", rank=3, stocks=stocks_c),
        ]
        result = create_buy_targets(sectors, max_sectors=2)
        codes = {t.stock.code for t in result.buy_targets}
        assert "A001" in codes
        assert "A002" in codes
        assert "A003" not in codes

    def test_guard_pass_goes_to_buy_targets(self):
        s1 = _stock(code="A001", change_rate=1.0)
        sc = _sector(rank=1, stocks=[s1])
        result = create_buy_targets([sc])
        assert len(result.buy_targets) == 1
        assert result.buy_targets[0].stock.code == "A001"
        assert result.buy_targets[0].reason == ""
        assert result.blocked_targets == []

    def test_guard_blocked_goes_to_blocked_targets(self):
        s1 = _stock(code="A001", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s1])
        result = create_buy_targets([sc], block_rise_pct=7.0)
        assert result.buy_targets == []
        assert len(result.blocked_targets) == 1
        assert result.blocked_targets[0].stock.code == "A001"
        assert result.blocked_targets[0].reason == "상승률"

    def test_mixed_pass_and_blocked(self):
        s_pass = _stock(code="A001", change_rate=1.0)
        s_block = _stock(code="A002", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s_pass, s_block])
        result = create_buy_targets([sc], block_rise_pct=7.0)
        assert len(result.buy_targets) == 1
        assert len(result.blocked_targets) == 1
        assert result.buy_targets[0].stock.code == "A001"
        assert result.blocked_targets[0].stock.code == "A002"

    def test_pass_rank_starts_at_1(self):
        s1 = _stock(code="A001", change_rate=1.0)
        s2 = _stock(code="A002", change_rate=2.0)
        sc = _sector(rank=1, stocks=[s1, s2])
        result = create_buy_targets([sc])
        assert result.buy_targets[0].rank == 1
        assert result.buy_targets[1].rank == 2

    def test_blocked_rank_starts_at_1(self):
        s1 = _stock(code="A001", change_rate=10.0)
        s2 = _stock(code="A002", change_rate=-10.0)
        sc = _sector(rank=1, stocks=[s1, s2])
        result = create_buy_targets([sc], block_rise_pct=7.0, block_fall_pct=7.0)
        assert result.blocked_targets[0].rank == 1
        assert result.blocked_targets[1].rank == 2

    def test_sort_by_change_rate_descending(self):
        s1 = _stock(code="A001", change_rate=1.0)
        s2 = _stock(code="A002", change_rate=5.0)
        s3 = _stock(code="A003", change_rate=3.0)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = create_buy_targets([sc], sort_keys=["change_rate"])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A003", "A001"]

    def test_sort_by_trade_amount_descending(self):
        s1 = _stock(code="A001", trade_amount=1_000_000)
        s2 = _stock(code="A002", trade_amount=5_000_000)
        s3 = _stock(code="A003", trade_amount=3_000_000)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = create_buy_targets([sc], sort_keys=["trade_amount"])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A003", "A001"]

    def test_sort_by_strength_descending(self):
        s1 = _stock(code="A001", strength=50.0)
        s2 = _stock(code="A002", strength=200.0)
        s3 = _stock(code="A003", strength=100.0)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = create_buy_targets([sc], sort_keys=["strength"])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A003", "A001"]

    def test_multi_sort_keys(self):
        s1 = _stock(code="A001", change_rate=5.0, trade_amount=1_000_000)
        s2 = _stock(code="A002", change_rate=5.0, trade_amount=5_000_000)
        s3 = _stock(code="A003", change_rate=3.0, trade_amount=9_000_000)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = create_buy_targets([sc], sort_keys=["change_rate", "trade_amount"])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A001", "A003"]

    def test_boost_score_affects_ordering(self):
        s1 = _stock(code="A001", change_rate=3.0, cur_price=75000)
        s2 = _stock(code="A002", change_rate=5.0, cur_price=65000)
        sc = _sector(rank=1, stocks=[s1, s2])
        result = create_buy_targets(
            [sc],
            sort_keys=["change_rate"],
            high_5d_cache={"A001": 70000},
            boost_high_on=True,
            boost_high_score=10.0,
        )
        codes = [t.stock.code for t in result.buy_targets]
        assert codes[0] == "A001"

    def test_sector_rank_in_target(self):
        s1 = _stock(code="A001")
        sc = _sector(rank=2, stocks=[s1])
        result = create_buy_targets([sc])
        assert result.buy_targets[0].sector_rank == 2

    def test_version_increments(self):
        s1 = _stock(code="A001")
        sc = _sector(rank=1, stocks=[s1])
        r1 = create_buy_targets([sc])
        r2 = create_buy_targets([sc])
        assert r2.version == r1.version + 1

    def test_pass_targets_before_blocked_in_proximity(self):
        s_pass = _stock(code="A001", change_rate=1.0)
        s_block = _stock(code="A002", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s_pass, s_block])
        result = create_buy_targets([sc], block_rise_pct=7.0)
        assert len(result.buy_targets) == 1
        assert len(result.blocked_targets) == 1

    def test_trade_amount_rank_calculated_for_guard_pass_stocks(self):
        s1 = _stock(code="A001", trade_amount=1_000_000)
        s2 = _stock(code="A002", trade_amount=5_000_000)
        s3 = _stock(code="A003", trade_amount=3_000_000)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = create_buy_targets(
            [sc],
            boost_trade_amount_rank_on=True,
        )
        stock_map = {t.stock.code: t.stock for t in result.buy_targets}
        assert stock_map["A002"].trade_amount_rank == 0
        assert stock_map["A003"].trade_amount_rank == 1
        assert stock_map["A001"].trade_amount_rank == 2

    def test_trade_amount_rank_excludes_held_codes(self):
        s1 = _stock(code="A001", trade_amount=1_000_000)
        s2 = _stock(code="A002", trade_amount=5_000_000)
        sc = _sector(rank=1, stocks=[s1, s2])
        result = create_buy_targets(
            [sc],
            held_codes={"A002"},
            boost_trade_amount_rank_on=True,
        )
        stock_map = {t.stock.code: t.stock for t in result.buy_targets}
        assert stock_map["A001"].trade_amount_rank == 0
        assert stock_map["A002"].trade_amount_rank == -1

    def test_blocked_stock_boost_score_zero(self):
        s1 = _stock(code="A001", change_rate=10.0, cur_price=75000)
        sc = _sector(rank=1, stocks=[s1])
        result = create_buy_targets(
            [sc],
            block_rise_pct=7.0,
            high_5d_cache={"A001": 70000},
            boost_high_on=True,
            boost_high_score=5.0,
        )
        assert result.blocked_targets[0].stock.boost_score == 0.0

    def test_returns_sector_summary(self):
        s1 = _stock(code="A001")
        sc = _sector(rank=1, stocks=[s1])
        result = create_buy_targets([sc])
        assert isinstance(result, SectorSummary)
        assert result.sectors == [sc]

    def test_held_stock_sorted_after_normal_candidates(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_held = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_held, s_normal])
        result = create_buy_targets([sc], held_codes={"A002"}, sort_keys=["change_rate"])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A001", "A002"]
        assert result.buy_targets[0].reason == ""
        assert result.buy_targets[1].reason == "보유중"

    def test_bought_today_sorted_after_normal_candidates(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_bought = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_bought, s_normal])
        result = create_buy_targets([sc], bought_today_codes={"A002"}, sort_keys=["change_rate"])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A001", "A002"]
        assert result.buy_targets[0].reason == ""
        assert result.buy_targets[1].reason == "금일매수"

    def test_restricted_stocks_before_blocked_stocks(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_held = _stock(code="A002", change_rate=5.0)
        s_blocked = _stock(code="A003", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s_blocked, s_held, s_normal])
        result = create_buy_targets(
            [sc], held_codes={"A002"}, block_rise_pct=7.0, sort_keys=["change_rate"],
        )
        buy_codes = [t.stock.code for t in result.buy_targets]
        blocked_codes = [t.stock.code for t in result.blocked_targets]
        assert buy_codes == ["A001", "A002"]
        assert blocked_codes == ["A003"]

    def test_held_rank_higher_than_normal_but_sorted_after(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_held = _stock(code="A002", change_rate=9.0)
        sc = _sector(rank=1, stocks=[s_held, s_normal])
        result = create_buy_targets([sc], held_codes={"A002"}, block_rise_pct=10.0, sort_keys=["change_rate"])
        assert result.buy_targets[0].stock.code == "A001"
        assert result.buy_targets[0].rank == 1
        assert result.buy_targets[1].stock.code == "A002"
        assert result.buy_targets[1].rank == 2
