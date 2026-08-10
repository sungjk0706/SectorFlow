"""buy_filter.py · sector_calculator.py 단위 테스트 — 매수 후보 필터링 및 타겟 생성 로직 검증.

check_stock_guards, calculate_boost_score의 가드 필터링, 가산점 계산 로직 검증.
TestBuildBuyTargetsFromSettings (30건)는 build_buy_targets_from_settings 어댑터 회귀 검증
(기존 create_buy_targets 30건 시그니처 갱신 — 설계서 섹션 8-2).
TestSelectTopSectorStocks · TestIsChangeRateBlocked · TestApplyBuyBlockGuards · TestRankBuyTargets는
분리 함수 단위 검증 (설계서 섹션 8-1).
"""
from __future__ import annotations

from unittest.mock import patch

from backend.app.domain.models import StockScore, SectorScore, SectorSummary
from backend.app.domain.buy_filter import (
    calculate_boost_score,
    check_stock_guards,
    is_change_rate_blocked,
    apply_buy_block_guards,
    rank_buy_targets,
    build_buy_targets_from_settings,
    apply_incremental_buy_target_update,
    compute_stock_boost_max,
)
from backend.app.domain.sector_calculator import select_top_sector_stocks


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _stock(
    code: str = "005930",
    name: str = "삼성전자",
    sector: str = "반도체",
    change_rate: float = 1.0,
    trade_amount: int = 1_000_000_000,
    avg_amt_5d: int = 40,
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
    avg_trade_amount: int = 3_000_000_000,
    is_cutoff_passed: bool = True,
) -> SectorScore:
    return SectorScore(
        sector=sector,
        total=total,
        rise_count=rise_count,
        rise_ratio=rise_ratio,
        avg_change_rate=avg_change_rate,
        avg_trade_amount=avg_trade_amount,
        rank=rank,
        is_cutoff_passed=is_cutoff_passed,
        stocks=stocks or [],
    )


# ── check_stock_guards ─────────────────────────────────────────────────────────

class TestCheckStockGuards:
    def test_pass_all_guards(self):
        stock = _stock(change_rate=2.0, strength=100.0)
        result = check_stock_guards(stock, block_rise_pct=7.0, block_fall_pct=-7.0)
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
        result = check_stock_guards(stock, block_fall_pct=-7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "하락률"

    def test_block_by_fall_pct_below_threshold(self):
        stock = _stock(change_rate=-8.0)
        result = check_stock_guards(stock, block_fall_pct=-7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "하락률"

    def test_pass_just_above_fall_threshold(self):
        stock = _stock(change_rate=-6.9)
        result = check_stock_guards(stock, block_fall_pct=-7.0)
        assert result.guard_pass is True

    def test_rise_takes_priority_over_fall(self):
        stock = _stock(change_rate=7.0)
        result = check_stock_guards(stock, block_rise_pct=7.0, block_fall_pct=-7.0)
        assert result.guard_pass is False
        assert result.guard_reason == "상승률"

    def test_block_rise_on_false_disables_check(self):
        stock = _stock(change_rate=10.0)
        result = check_stock_guards(stock, block_rise_on=False, block_rise_pct=7.0)
        assert result.guard_pass is True

    def test_block_rise_pct_zero_disables_check(self):
        stock = _stock(change_rate=10.0)
        result = check_stock_guards(stock, block_rise_on=True, block_rise_pct=0.0)
        assert result.guard_pass is True

    def test_block_fall_on_false_disables_check(self):
        stock = _stock(change_rate=-5.0)
        result = check_stock_guards(stock, block_fall_on=False, block_fall_pct=-7.0)
        assert result.guard_pass is True

    def test_block_fall_pct_zero_disables_check(self):
        stock = _stock(change_rate=-5.0)
        result = check_stock_guards(stock, block_fall_on=True, block_fall_pct=0.0)
        assert result.guard_pass is True

    def test_block_fall_pct_zero_passes_zero_change_rate(self):
        stock = _stock(change_rate=0.0)
        result = check_stock_guards(stock, block_fall_on=True, block_fall_pct=0.0)
        assert result.guard_pass is True

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
        assert stock.boost_high_triggered is False
        assert stock.boost_order_ratio_triggered is False
        assert stock.boost_news_triggered is False
        assert stock.boost_program_triggered is False

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
        assert stock.boost_high_triggered is True
        assert stock.boost_order_ratio_triggered is False
        assert stock.boost_news_triggered is False
        assert stock.boost_program_triggered is False

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
        assert stock.boost_high_triggered is False

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
        assert stock.boost_high_triggered is False

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
        assert stock.boost_order_ratio_triggered is True
        assert stock.boost_high_triggered is False

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
        assert stock.boost_order_ratio_triggered is False

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
        assert stock.boost_order_ratio_triggered is True

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
        assert stock.boost_order_ratio_triggered is False

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
        assert stock.boost_program_triggered is True
        assert stock.boost_high_triggered is False

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
        assert stock.boost_program_triggered is False

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
        assert stock.boost_high_triggered is True
        assert stock.boost_order_ratio_triggered is True
        assert stock.boost_program_triggered is True
        assert stock.boost_news_triggered is False

    def test_news_boost_when_in_cache_and_enabled(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
            news_boost_cache={"005930": 1.0},
            boost_news_on=True,
            boost_news_score=2.0,
        )
        assert score == 2.0
        assert stock.boost_news_triggered is True
        assert stock.boost_high_triggered is False

    def test_news_no_boost_when_disabled(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
            news_boost_cache={"005930": 1.0},
            boost_news_on=False,
            boost_news_score=2.0,
        )
        assert score == 0.0
        assert stock.boost_news_triggered is False

    def test_news_no_boost_when_cache_empty(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
            news_boost_cache={},
            boost_news_on=True,
            boost_news_score=2.0,
        )
        assert score == 0.0
        assert stock.boost_news_triggered is False

    def test_news_no_boost_when_stock_not_in_cache(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
            news_boost_cache={"000660": 1.0},
            boost_news_on=True,
            boost_news_score=2.0,
        )
        assert score == 0.0
        assert stock.boost_news_triggered is False

    def test_news_accumulates_with_other_boosts(self):
        stock = _stock(code="005930", cur_price=75000)
        score = calculate_boost_score(
            stock,
            high_5d_cache={"005930": 70000},
            orderbook_cache={"005930": (150, 100)},
            program_net_buy_cache={"005930": 500_000_000},
            news_boost_cache={"005930": 1.0},
            boost_high_on=True,
            boost_high_score=1.0,
            boost_order_ratio_on=True,
            boost_order_ratio_pct=20.0,
            boost_order_ratio_score=1.0,
            boost_program_net_buy_on=True,
            boost_program_net_buy_score=1.0,
            boost_news_on=True,
            boost_news_score=1.5,
        )
        assert score == 4.5
        assert stock.boost_high_triggered is True
        assert stock.boost_order_ratio_triggered is True
        assert stock.boost_program_triggered is True
        assert stock.boost_news_triggered is True

    def test_trigger_fields_reset_on_recompute(self):
        """이전 호출에서 True였던 트리거 필드가 재호출 시 조건 미충족이면 False로 리셋되는지 검증 (P22 정합성)."""
        stock = _stock(code="005930", cur_price=75000)
        # 1차 호출: 모든 가산점 트리거
        calculate_boost_score(
            stock,
            high_5d_cache={"005930": 70000},
            orderbook_cache={"005930": (150, 100)},
            program_net_buy_cache={"005930": 500_000_000},
            news_boost_cache={"005930": 1.0},
            boost_high_on=True,
            boost_order_ratio_on=True,
            boost_program_net_buy_on=True,
            boost_news_on=True,
        )
        assert stock.boost_high_triggered is True
        assert stock.boost_order_ratio_triggered is True
        assert stock.boost_program_triggered is True
        assert stock.boost_news_triggered is True
        # 2차 호출: 모든 가산점 OFF → 트리거 필드 모두 False로 리셋
        calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
        )
        assert stock.boost_high_triggered is False
        assert stock.boost_order_ratio_triggered is False
        assert stock.boost_program_triggered is False
        assert stock.boost_news_triggered is False

    def test_score_never_negative(self):
        stock = _stock(code="005930")
        score = calculate_boost_score(
            stock,
            high_5d_cache={},
            orderbook_cache={},
            program_net_buy_cache={},
        )
        assert score >= 0.0


# ── build_buy_targets_from_settings 회귀 어댑터 (기존 create_buy_targets 28건 갱신) ──

_DEFAULT_SETTINGS = {
    "sector_max_targets": 3,
    "buy_block_rise_on": True,
    "buy_block_rise_pct": 7.0,
    "buy_block_fall_on": True,
    "buy_block_fall_pct": -7.0,
    "rebuy_block_on": True,
    "sector_sort_keys": None,
    "boost_high_breakout_on": False,
    "boost_high_breakout_score": 1.0,
    "boost_order_ratio_on": False,
    "boost_order_ratio_pct": 20.0,
    "boost_order_ratio_score": 1.0,
    "boost_program_net_buy_on": False,
    "boost_program_net_buy_score": 1.0,
    "boost_news_on": False,
    "boost_news_score": 1.0,
}


def _settings(**overrides) -> dict:
    s = dict(_DEFAULT_SETTINGS)
    s.update(overrides)
    return s


def _build(
    sector_scores,
    *,
    settings=None,
    held_codes=None,
    bought_today_codes=None,
    high_5d_cache=None,
    orderbook_cache=None,
    program_net_buy_cache=None,
    news_boost_cache=None,
) -> SectorSummary:
    """build_buy_targets_from_settings 어댑터 회귀 테스트용 헬퍼.
    engine_radar 캐시 getter를 patch하여 순수 단위 테스트 보장."""
    _s = settings if settings is not None else _settings()
    with patch("backend.app.services.engine_radar.get_high_price_5d_cache", return_value=high_5d_cache or {}), \
         patch("backend.app.services.engine_radar.get_orderbook_cache", return_value=orderbook_cache or {}), \
         patch("backend.app.services.engine_radar.get_program_net_buy_cache", return_value=program_net_buy_cache or {}), \
         patch("backend.app.services.engine_radar.get_news_boost_cache", return_value=news_boost_cache or {}):
        return build_buy_targets_from_settings(
            sector_scores, _s,
            held_codes=held_codes, bought_today_codes=bought_today_codes,
        )


class TestBuildBuyTargetsFromSettings:
    def test_empty_sector_scores_returns_empty(self):
        result = _build([])
        assert result.buy_targets == []
        assert result.blocked_targets == []
        assert result.sectors == []

    def test_cutoff_failed_sectors_excluded(self):
        """is_cutoff_passed=False 업종은 매수 대상에서 제외 (rank가 아닌 is_cutoff_passed로 판단)."""
        s1 = _stock(code="A001", change_rate=1.0)
        sc = _sector(rank=2, is_cutoff_passed=False, stocks=[s1])
        result = _build([sc])
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
        result = _build(sectors, settings=_settings(sector_max_targets=2))
        codes = {t.stock.code for t in result.buy_targets}
        assert "A001" in codes
        assert "A002" in codes
        assert "A003" not in codes

    def test_guard_pass_goes_to_buy_targets(self):
        s1 = _stock(code="A001", change_rate=1.0)
        sc = _sector(rank=1, stocks=[s1])
        result = _build([sc])
        assert len(result.buy_targets) == 1
        assert result.buy_targets[0].stock.code == "A001"
        assert result.buy_targets[0].reject_reason == ""
        assert result.blocked_targets == []

    def test_guard_blocked_goes_to_blocked_targets(self):
        s1 = _stock(code="A001", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s1])
        result = _build([sc], settings=_settings(buy_block_rise_pct=7.0))
        assert result.buy_targets == []
        assert len(result.blocked_targets) == 1
        assert result.blocked_targets[0].stock.code == "A001"
        assert result.blocked_targets[0].reject_reason == "상승률"

    def test_mixed_pass_and_blocked(self):
        s_pass = _stock(code="A001", change_rate=1.0)
        s_block = _stock(code="A002", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s_pass, s_block])
        result = _build([sc], settings=_settings(buy_block_rise_pct=7.0))
        assert len(result.buy_targets) == 1
        assert len(result.blocked_targets) == 1
        assert result.buy_targets[0].stock.code == "A001"
        assert result.blocked_targets[0].stock.code == "A002"

    def test_pass_rank_starts_at_1(self):
        s1 = _stock(code="A001", change_rate=1.0)
        s2 = _stock(code="A002", change_rate=2.0)
        sc = _sector(rank=1, stocks=[s1, s2])
        result = _build([sc])
        assert result.buy_targets[0].rank == 1
        assert result.buy_targets[1].rank == 2

    def test_blocked_rank_starts_at_1(self):
        s1 = _stock(code="A001", change_rate=10.0)
        s2 = _stock(code="A002", change_rate=-10.0)
        sc = _sector(rank=1, stocks=[s1, s2])
        result = _build(
            [sc],
            settings=_settings(
                buy_block_rise_pct=7.0,
                buy_block_fall_pct=-7.0,
            ),
        )
        assert result.blocked_targets[0].rank == 1
        assert result.blocked_targets[1].rank == 2

    def test_sort_by_change_rate_descending(self):
        s1 = _stock(code="A001", change_rate=1.0)
        s2 = _stock(code="A002", change_rate=5.0)
        s3 = _stock(code="A003", change_rate=3.0)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = _build([sc], settings=_settings(sector_sort_keys=["change_rate"]))
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A003", "A001"]

    def test_sort_by_trade_amount_descending(self):
        s1 = _stock(code="A001", trade_amount=1_000_000)
        s2 = _stock(code="A002", trade_amount=5_000_000)
        s3 = _stock(code="A003", trade_amount=3_000_000)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = _build([sc], settings=_settings(sector_sort_keys=["trade_amount"]))
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A003", "A001"]

    def test_sort_by_strength_descending(self):
        s1 = _stock(code="A001", strength=50.0)
        s2 = _stock(code="A002", strength=200.0)
        s3 = _stock(code="A003", strength=100.0)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = _build([sc], settings=_settings(sector_sort_keys=["strength"]))
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A003", "A001"]

    def test_multi_sort_keys(self):
        s1 = _stock(code="A001", change_rate=5.0, trade_amount=1_000_000)
        s2 = _stock(code="A002", change_rate=5.0, trade_amount=5_000_000)
        s3 = _stock(code="A003", change_rate=3.0, trade_amount=9_000_000)
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        result = _build(
            [sc],
            settings=_settings(sector_sort_keys=["change_rate", "trade_amount"]),
        )
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A001", "A003"]

    def test_boost_score_affects_ordering(self):
        s1 = _stock(code="A001", change_rate=3.0, cur_price=75000)
        s2 = _stock(code="A002", change_rate=5.0, cur_price=65000)
        sc = _sector(rank=1, stocks=[s1, s2])
        result = _build(
            [sc],
            settings=_settings(
                sector_sort_keys=["change_rate"],
                boost_high_breakout_on=True,
                boost_high_breakout_score=10.0,
            ),
            high_5d_cache={"A001": 70000},
        )
        codes = [t.stock.code for t in result.buy_targets]
        assert codes[0] == "A001"

    def test_sector_rank_in_target(self):
        s1 = _stock(code="A001")
        sc = _sector(rank=2, stocks=[s1])
        result = _build([sc])
        assert result.buy_targets[0].sector_rank == 2

    def test_version_increments(self):
        s1 = _stock(code="A001")
        sc = _sector(rank=1, stocks=[s1])
        r1 = _build([sc])
        r2 = _build([sc])
        assert r2.version == r1.version + 1

    def test_pass_targets_before_blocked_in_proximity(self):
        s_pass = _stock(code="A001", change_rate=1.0)
        s_block = _stock(code="A002", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s_pass, s_block])
        result = _build([sc], settings=_settings(buy_block_rise_pct=7.0))
        assert len(result.buy_targets) == 1
        assert len(result.blocked_targets) == 1

    def test_blocked_stock_receives_high_breakout_boost(self):
        # 차단 종목이지만 5거래일 고가 돌파(75000 > 70000) → 가산점 부여
        s1 = _stock(code="A001", change_rate=10.0, cur_price=75000)
        sc = _sector(rank=1, stocks=[s1])
        result = _build(
            [sc],
            settings=_settings(
                buy_block_rise_pct=7.0,
                boost_high_breakout_on=True,
                boost_high_breakout_score=5.0,
            ),
            high_5d_cache={"A001": 70000},
        )
        # 차단 종목이지만 5거래일 고가 돌파(75000 > 70000) → 가산점 부여
        assert result.blocked_targets[0].stock.boost_score == 5.0

    def test_returns_sector_summary(self):
        s1 = _stock(code="A001")
        sc = _sector(rank=1, stocks=[s1])
        result = _build([sc])
        assert isinstance(result, SectorSummary)
        assert result.sectors == [sc]

    def test_held_stock_goes_to_blocked_targets(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_held = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_held, s_normal])
        result = _build(
            [sc],
            held_codes={"A002"},
            settings=_settings(sector_sort_keys=["change_rate"]),
        )
        assert [t.stock.code for t in result.buy_targets] == ["A001"]
        assert result.buy_targets[0].reject_reason == ""
        assert [t.stock.code for t in result.blocked_targets] == ["A002"]
        assert result.blocked_targets[0].reject_reason == "보유중"
        assert result.blocked_targets[0].stock.guard_pass is False

    def test_bought_today_goes_to_blocked_targets(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_bought = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_bought, s_normal])
        result = _build(
            [sc],
            bought_today_codes={"A002"},
            settings=_settings(sector_sort_keys=["change_rate"]),
        )
        assert [t.stock.code for t in result.buy_targets] == ["A001"]
        assert result.buy_targets[0].reject_reason == ""
        assert [t.stock.code for t in result.blocked_targets] == ["A002"]
        assert result.blocked_targets[0].reject_reason == "금일매수"
        assert result.blocked_targets[0].stock.guard_pass is False

    def test_held_and_blocked_both_in_blocked_targets(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_held = _stock(code="A002", change_rate=5.0)
        s_blocked = _stock(code="A003", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s_blocked, s_held, s_normal])
        result = _build(
            [sc],
            held_codes={"A002"},
            settings=_settings(
                buy_block_rise_pct=7.0,
                sector_sort_keys=["change_rate"],
            ),
        )
        assert [t.stock.code for t in result.buy_targets] == ["A001"]
        blocked_codes = [t.stock.code for t in result.blocked_targets]
        assert "A002" in blocked_codes
        assert "A003" in blocked_codes

    def test_held_stock_blocked_even_with_high_change_rate(self):
        s_normal = _stock(code="A001", change_rate=1.0)
        s_held = _stock(code="A002", change_rate=9.0)
        sc = _sector(rank=1, stocks=[s_held, s_normal])
        result = _build(
            [sc],
            held_codes={"A002"},
            settings=_settings(
                buy_block_rise_pct=10.0,
                sector_sort_keys=["change_rate"],
            ),
        )
        assert result.buy_targets[0].stock.code == "A001"
        assert result.buy_targets[0].rank == 1
        assert [t.stock.code for t in result.blocked_targets] == ["A002"]
        assert result.blocked_targets[0].reject_reason == "보유중"

    def test_held_takes_priority_over_rise_guard(self):
        """전역 조건(보유중)이 개별 가드(상승률)보다 우선 — SSOT: trading.py 실행 게이트와 동일 순서."""
        s_held = _stock(code="A002", change_rate=10.0)
        sc = _sector(rank=1, stocks=[s_held])
        result = _build(
            [sc],
            held_codes={"A002"},
            settings=_settings(buy_block_rise_pct=7.0),
        )
        assert result.blocked_targets[0].reject_reason == "보유중"

    def test_bought_today_takes_priority_over_fall_guard(self):
        """전역 조건(금일매수)이 개별 가드(하락률)보다 우선."""
        s_bought = _stock(code="A003", change_rate=-10.0)
        sc = _sector(rank=1, stocks=[s_bought])
        result = _build(
            [sc],
            bought_today_codes={"A003"},
            settings=_settings(buy_block_fall_pct=-7.0),
        )
        assert result.blocked_targets[0].reject_reason == "금일매수"

    def test_rebuy_block_off_held_stock_in_buy_targets(self):
        """rebuy_block_on=False → 보유 종목도 매수 후보에 포함."""
        s_normal = _stock(code="A001", change_rate=1.0)
        s_held = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_held, s_normal])
        result = _build(
            [sc],
            held_codes={"A002"},
            settings=_settings(
                rebuy_block_on=False,
                sector_sort_keys=["change_rate"],
            ),
        )
        codes = {t.stock.code for t in result.buy_targets}
        assert "A002" in codes
        assert "A001" in codes
        # 보유 종목의 guard_pass는 True, reason은 빈 문자열
        held_target = next(t for t in result.buy_targets if t.stock.code == "A002")
        assert held_target.stock.guard_pass is True
        assert held_target.reject_reason == ""

    def test_rebuy_block_off_bought_today_in_buy_targets(self):
        """rebuy_block_on=False → 금일매수 종목도 매수 후보에 포함."""
        s_normal = _stock(code="A001", change_rate=1.0)
        s_bought = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_bought, s_normal])
        result = _build(
            [sc],
            bought_today_codes={"A002"},
            settings=_settings(
                rebuy_block_on=False,
                sector_sort_keys=["change_rate"],
            ),
        )
        codes = {t.stock.code for t in result.buy_targets}
        assert "A002" in codes
        assert "A001" in codes
        bought_target = next(t for t in result.buy_targets if t.stock.code == "A002")
        assert bought_target.stock.guard_pass is True
        assert bought_target.reject_reason == ""

    def test_rebuy_block_off_no_blocked_targets_from_held(self):
        """rebuy_block_on=False → 보유 종목이 blocked_targets에 들어가지 않음."""
        s_held = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_held])
        result = _build(
            [sc],
            held_codes={"A002"},
            settings=_settings(rebuy_block_on=False),
        )
        assert [t.stock.code for t in result.blocked_targets] == []
        assert [t.stock.code for t in result.buy_targets] == ["A002"]

    def test_rebuy_block_on_default_blocks_held(self):
        """rebuy_block_on 미전달(기본값 True) → 보유 종목 차단 (기존 동작 유지)."""
        s_held = _stock(code="A002", change_rate=5.0)
        sc = _sector(rank=1, stocks=[s_held])
        result = _build([sc], held_codes={"A002"})
        assert [t.stock.code for t in result.blocked_targets] == ["A002"]
        assert result.blocked_targets[0].reject_reason == "보유중"


# ── select_top_sector_stocks (단위) ─────────────────────────────────────────────

class TestSelectTopSectorStocks:
    def test_cutoff_failed_sectors_excluded(self):
        s1 = _stock(code="A001", change_rate=1.0)
        sc_pass = _sector(sector="반도체", rank=1, stocks=[s1])
        sc_fail = _sector(sector="전기", rank=2, is_cutoff_passed=False, stocks=[_stock(code="A002")])
        pairs = select_top_sector_stocks([sc_pass, sc_fail], max_sectors=2)
        assert len(pairs) == 1
        assert pairs[0][0].code == "A001"

    def test_max_sectors_limit(self):
        s_a = [_stock(code="A001", change_rate=1.0)]
        s_b = [_stock(code="A002", change_rate=2.0)]
        s_c = [_stock(code="A003", change_rate=3.0)]
        sectors = [
            _sector(sector="A", rank=1, stocks=s_a),
            _sector(sector="B", rank=2, stocks=s_b),
            _sector(sector="C", rank=3, stocks=s_c),
        ]
        pairs = select_top_sector_stocks(sectors, max_sectors=2)
        codes = {p[0].code for p in pairs}
        assert "A001" in codes
        assert "A002" in codes
        assert "A003" not in codes

    def test_max_sectors_limits_ten_passed_sectors_to_seven(self):
        sectors = [
            _sector(sector=f"업종{i}", rank=i, stocks=[_stock(code=f"A{i:03d}")])
            for i in range(1, 11)
        ]

        pairs = select_top_sector_stocks(sectors, max_sectors=7)

        assert len(pairs) == 7

    def test_max_sectors_keeps_all_when_fewer_passed_sectors(self):
        sectors = [
            _sector(sector=f"업종{i}", rank=i, stocks=[_stock(code=f"A{i:03d}")])
            for i in range(1, 4)
        ]

        pairs = select_top_sector_stocks(sectors, max_sectors=7)

        assert len(pairs) == 3

    def test_empty_sector_scores_returns_empty(self):
        assert select_top_sector_stocks([]) == []


# ── is_change_rate_blocked (단위) ───────────────────────────────────────────────

class TestIsChangeRateBlocked:
    def test_rise_above_limit_blocks(self):
        blocked, reason = is_change_rate_blocked(
            8.0, block_rise_on=True, block_rise_pct=7.0,
        )
        assert blocked is True
        assert reason == "상승률"

    def test_fall_below_limit_blocks(self):
        blocked, reason = is_change_rate_blocked(
            -8.0, block_fall_on=True, block_fall_pct=-7.0,
        )
        assert blocked is True
        assert reason == "하락률"

    def test_within_range_passes(self):
        blocked, reason = is_change_rate_blocked(
            2.0,
            block_rise_on=True,
            block_rise_pct=7.0,
            block_fall_on=True,
            block_fall_pct=-7.0,
        )
        assert blocked is False
        assert reason == ""

    def test_block_rise_off_passes(self):
        blocked, reason = is_change_rate_blocked(
            10.0, block_rise_on=False, block_rise_pct=7.0,
        )
        assert blocked is False
        assert reason == ""

    def test_block_rise_pct_zero_disabled(self):
        blocked, reason = is_change_rate_blocked(
            10.0, block_rise_on=True, block_rise_pct=0.0,
        )
        assert blocked is False
        assert reason == ""


# ── apply_buy_block_guards (단위) ───────────────────────────────────────────────

class TestApplyBuyBlockGuards:
    def test_held_with_rebuy_block_on_blocked(self):
        s = _stock(code="A001", change_rate=1.0)
        sc = _sector(rank=1, stocks=[s])
        pairs = select_top_sector_stocks([sc])
        apply_buy_block_guards(pairs, rebuy_block_on=True, held_codes={"A001"})
        assert s.guard_pass is False
        assert s.guard_reason == "보유중"

    def test_bought_today_with_rebuy_block_on_blocked(self):
        s = _stock(code="A001", change_rate=1.0)
        sc = _sector(rank=1, stocks=[s])
        pairs = select_top_sector_stocks([sc])
        apply_buy_block_guards(pairs, rebuy_block_on=True, bought_today_codes={"A001"})
        assert s.guard_pass is False
        assert s.guard_reason == "금일매수"

    def test_rebuy_block_off_held_passes(self):
        s = _stock(code="A001", change_rate=1.0)
        sc = _sector(rank=1, stocks=[s])
        pairs = select_top_sector_stocks([sc])
        apply_buy_block_guards(pairs, rebuy_block_on=False, held_codes={"A001"})
        assert s.guard_pass is True
        assert s.guard_reason == ""


# ── rank_buy_targets (단위) ─────────────────────────────────────────────────────

class TestRankBuyTargets:
    def test_pass_targets_before_blocked(self):
        s_pass = _stock(code="A001", change_rate=1.0)
        s_block = _stock(code="A002", change_rate=10.0)
        s_pass.guard_pass = True
        s_pass.guard_reason = ""
        s_block.guard_pass = False
        s_block.guard_reason = "상승률"
        sc = _sector(rank=1, stocks=[s_pass, s_block])
        result = rank_buy_targets([(s_pass, sc), (s_block, sc)])
        assert [t.stock.code for t in result.buy_targets] == ["A001"]
        assert [t.stock.code for t in result.blocked_targets] == ["A002"]

    def test_boost_score_descending_order(self):
        s_low = _stock(code="A001", change_rate=1.0)
        s_high = _stock(code="A002", change_rate=2.0)
        s_low.boost_score = 1.0
        s_low.guard_pass = True
        s_low.guard_reason = ""
        s_high.boost_score = 5.0
        s_high.guard_pass = True
        s_high.guard_reason = ""
        sc = _sector(rank=1, stocks=[s_low, s_high])
        result = rank_buy_targets([(s_low, sc), (s_high, sc)])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A001"]

    def test_multi_sort_keys(self):
        s1 = _stock(code="A001", change_rate=5.0, trade_amount=1_000_000)
        s2 = _stock(code="A002", change_rate=5.0, trade_amount=5_000_000)
        s3 = _stock(code="A003", change_rate=3.0, trade_amount=9_000_000)
        for s in (s1, s2, s3):
            s.guard_pass = True
            s.guard_reason = ""
        sc = _sector(rank=1, stocks=[s1, s2, s3])
        pairs = [(s1, sc), (s2, sc), (s3, sc)]
        result = rank_buy_targets(pairs, sort_keys=["change_rate", "trade_amount"])
        codes = [t.stock.code for t in result.buy_targets]
        assert codes == ["A002", "A001", "A003"]


# ── compute_stock_boost_max (종목 가산점 만점 SSOT 헬퍼) ──────────────────────────

class TestComputeStockBoostMax:
    def test_all_disabled_max_zero(self):
        """모든 가산점 off → 만점 0."""
        assert compute_stock_boost_max() == 0.0

    def test_single_enabled(self):
        """단일 가산점 on → 해당 점수 = 만점."""
        assert compute_stock_boost_max(boost_high_on=True, boost_high_score=2.0) == 2.0

    def test_all_enabled_default_scores(self):
        """모든 가산점 on, 기본 점수 1.0 → 만점 4.0."""
        assert compute_stock_boost_max(
            boost_high_on=True, boost_order_ratio_on=True,
            boost_program_net_buy_on=True, boost_news_on=True,
        ) == 4.0

    def test_all_enabled_custom_scores(self):
        """모든 가산점 on, 커스텀 점수 → 만점 = 점수 합."""
        assert compute_stock_boost_max(
            boost_high_on=True, boost_high_score=1.5,
            boost_order_ratio_on=True, boost_order_ratio_score=2.0,
            boost_program_net_buy_on=True, boost_program_net_buy_score=0.5,
            boost_news_on=True, boost_news_score=3.0,
        ) == 7.0

    def test_negative_score_clamped_to_zero(self):
        """음수 점수는 0으로 clamp."""
        assert compute_stock_boost_max(boost_high_on=True, boost_high_score=-1.0) == 0.0

    def test_partial_enabled(self):
        """일부 가산점만 on → on된 점수 합."""
        assert compute_stock_boost_max(
            boost_high_on=False, boost_high_score=5.0,
            boost_news_on=True, boost_news_score=2.0,
        ) == 2.0

    def test_matches_calculate_boost_score_max(self):
        """compute_stock_boost_max이 calculate_boost_score가 부여할 수 있는 최대와 일치."""
        stock = _stock(code="T", change_rate=5.0)
        # 모든 트리거 조건 충족: cur_price > high_5d, 잔량비 충족, 순매수 > 0, 뉴스 호재
        high_5d = {stock.code: 1000}
        orderbook = {stock.code: (200, 100)}  # bid 200, ask 100 → ratio 2.0
        program = {stock.code: 1000}
        news = {stock.code: 1.0}
        stock.cur_price = 2000  # high_5d 돌파
        max_score = compute_stock_boost_max(
            boost_high_on=True, boost_high_score=1.0,
            boost_order_ratio_on=True, boost_order_ratio_score=1.5,
            boost_program_net_buy_on=True, boost_program_net_buy_score=2.0,
            boost_news_on=True, boost_news_score=2.5,
        )
        actual = calculate_boost_score(
            stock,
            high_5d_cache=high_5d, orderbook_cache=orderbook, program_net_buy_cache=program,
            news_boost_cache=news,
            boost_high_on=True, boost_high_score=1.0,
            boost_order_ratio_on=True, boost_order_ratio_pct=20.0, boost_order_ratio_score=1.5,
            boost_program_net_buy_on=True, boost_program_net_buy_score=2.0,
            boost_news_on=True, boost_news_score=2.5,
        )
        assert actual == max_score


# ── apply_incremental_buy_target_update ──────────────────────────────────────

def _incremental_update(
    summary: SectorSummary,
    events: list[dict],
    *,
    settings=None,
    held_codes=None,
    bought_today_codes=None,
) -> SectorSummary:
    """apply_incremental_buy_target_update 어댑터 — engine_radar 캐시 getter patch."""
    _s = settings if settings is not None else _settings()
    with patch("backend.app.services.engine_radar.get_high_price_5d_cache", return_value={}), \
         patch("backend.app.services.engine_radar.get_orderbook_cache", return_value={}), \
         patch("backend.app.services.engine_radar.get_program_net_buy_cache", return_value={}), \
         patch("backend.app.services.engine_radar.get_news_boost_cache", return_value={}):
        return apply_incremental_buy_target_update(
            summary, events, _s,
            held_codes=held_codes, bought_today_codes=bought_today_codes,
        )


def _summary_with_targets(
    sectors: list[SectorScore],
    buy_target_codes: list[str],
    blocked_target_codes: list[str] | None = None,
) -> SectorSummary:
    """섹터 stocks에서 코드로 BuyTarget을 구성해 SectorSummary 생성."""
    from backend.app.domain.models import BuyTarget
    stock_by_code: dict[str, StockScore] = {}
    sector_by_name: dict[str, SectorScore] = {}
    for sc in sectors:
        sector_by_name[sc.sector] = sc
        for s in sc.stocks:
            stock_by_code[s.code] = s

    buy_targets: list = []
    for i, code in enumerate(buy_target_codes, 1):
        s = stock_by_code[code]
        sc = sector_by_name[s.sector]
        buy_targets.append(BuyTarget(rank=i, sector_rank=sc.rank, stock=s))

    blocked: list = []
    for i, code in enumerate(blocked_target_codes or [], 1):
        s = stock_by_code[code]
        sc = sector_by_name[s.sector]
        blocked.append(BuyTarget(rank=i, sector_rank=sc.rank, stock=s))

    return SectorSummary(sectors=sectors, buy_targets=buy_targets, blocked_targets=blocked)


class TestApplyIncrementalBuyTargetUpdate:
    """apply_incremental_buy_target_update — 이벤트 기반 증분 갱신 (설계서 결정 3)."""

    def test_cutoff_out_removes_sector_stocks(self):
        """통과→탈락 전환 시 해당 업종 종목만 제거 (설계서 완료기준 5)."""
        semi_stock = _stock("005930", sector="반도체")
        auto_stock = _stock("005380", sector="자동차")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[auto_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi, auto], ["005930", "005380"])

        events = [{"sector": "자동차", "action": "remove", "reason": "cutoff_out", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events)

        result_codes = {t.stock.code for t in result.buy_targets}
        assert "005930" in result_codes  # 반도체 유지
        assert "005380" not in result_codes  # 자동차 제거

    def test_cutoff_in_adds_sector_stocks(self):
        """탈락→통과 전환 시 해당 업종 종목만 추가 (설계서 완료기준 6)."""
        semi_stock = _stock("005930", sector="반도체")
        auto_stock = _stock("005380", sector="자동차")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[auto_stock], is_cutoff_passed=True)
        # 기존: 반도체만 매수후보 (자동차는 이전에 탈락 상태였음)
        summary = _summary_with_targets([semi, auto], ["005930"])

        events = [{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events)

        result_codes = {t.stock.code for t in result.buy_targets}
        assert "005930" in result_codes  # 반도체 유지
        assert "005380" in result_codes  # 자동차 추가

    def test_top_n_in_adds_sector_stocks(self):
        """상위 N개 진입 시 해당 업종 종목 추가 (설계서 완료기준 7)."""
        semi_stock = _stock("005930", sector="반도체")
        auto_stock = _stock("005380", sector="자동차")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[auto_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi, auto], ["005930"])

        events = [{"sector": "자동차", "action": "add", "reason": "top_n_in", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events)

        result_codes = {t.stock.code for t in result.buy_targets}
        assert "005380" in result_codes

    def test_top_n_out_removes_sector_stocks(self):
        """상위 N개 이탈 시 해당 업종 종목 제거 (설계서 완료기준 7)."""
        semi_stock = _stock("005930", sector="반도체")
        auto_stock = _stock("005380", sector="자동차")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[auto_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi, auto], ["005930", "005380"])

        events = [{"sector": "자동차", "action": "remove", "reason": "top_n_out", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events)

        result_codes = {t.stock.code for t in result.buy_targets}
        assert "005380" not in result_codes
        assert "005930" in result_codes

    def test_unchanged_sector_stocks_preserved(self):
        """변경되지 않은 업종 종목은 그대로 유지 (설계서 완료기준 4)."""
        semi_stock = _stock("005930", sector="반도체")
        auto_stock = _stock("005380", sector="자동차")
        ship_stock = _stock("005880", sector="조선")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[auto_stock], is_cutoff_passed=True)
        ship = _sector("조선", rank=3, stocks=[ship_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi, auto, ship], ["005930", "005380", "005880"])

        # 자동차만 제거 — 반도체·조선은 유지
        events = [{"sector": "자동차", "action": "remove", "reason": "cutoff_out", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events)

        result_codes = {t.stock.code for t in result.buy_targets}
        assert result_codes == {"005930", "005880"}

    def test_multiple_events_batch(self):
        """여러 이벤트 동시 처리 — 추가·제거 혼합 배치."""
        semi_stock = _stock("005930", sector="반도체")
        auto_stock = _stock("005380", sector="자동차")
        ship_stock = _stock("005880", sector="조선")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[auto_stock], is_cutoff_passed=True)
        ship = _sector("조선", rank=3, stocks=[ship_stock], is_cutoff_passed=True)
        # 기존: 반도체 + 조선 (자동차는 탈락)
        summary = _summary_with_targets([semi, auto, ship], ["005930", "005880"])

        events = [
            {"sector": "조선", "action": "remove", "reason": "cutoff_out", "stock_codes": ["005880"]},
            {"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]},
        ]
        result = _incremental_update(summary, events)

        result_codes = {t.stock.code for t in result.buy_targets}
        assert result_codes == {"005930", "005380"}  # 조선 제거, 자동차 추가, 반도체 유지

    def test_rerank_after_update(self):
        """갱신 후 재정렬 — rank가 1부터 순차 부여됨 (설계서 결정 4)."""
        s1 = _stock("005930", sector="반도체", change_rate=5.0)
        s2 = _stock("005380", sector="자동차", change_rate=3.0)
        semi = _sector("반도체", rank=1, stocks=[s1], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[s2], is_cutoff_passed=True)
        summary = _summary_with_targets([semi, auto], ["005930"])

        events = [{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events, settings=_settings(sector_sort_keys=["change_rate"]))

        # change_rate 내림차순 정렬 — 005930(5.0)이 1위, 005380(3.0)이 2위
        codes_by_rank = [t.stock.code for t in result.buy_targets]
        assert codes_by_rank[0] == "005930"
        assert codes_by_rank[1] == "005380"
        assert result.buy_targets[0].rank == 1
        assert result.buy_targets[1].rank == 2

    def test_sectors_preserved(self):
        """증분 갱신 후 sectors는 기존 유지 (업종 점수는 업종순위 단계 역할)."""
        semi_stock = _stock("005930", sector="반도체")
        auto_stock = _stock("005380", sector="자동차")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[auto_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi, auto], ["005930"])

        events = [{"sector": "자동차", "action": "remove", "reason": "cutoff_out", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events)

        assert result.sectors == [semi, auto]  # sectors 참조 유지

    def test_empty_events_returns_reranked(self):
        """빈 이벤트 리스트 — 기존 종목만으로 재정렬 (제거·추가 없음)."""
        semi_stock = _stock("005930", sector="반도체")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi], ["005930"])

        result = _incremental_update(summary, [])

        result_codes = {t.stock.code for t in result.buy_targets}
        assert result_codes == {"005930"}

    def test_reconcile_rebuilds_from_current_sector_stocks(self):
        """후보 종목 집합 불일치 시 현재 선택 업종 종목으로 다시 구성."""
        from backend.app.domain.models import BuyTarget

        current_stock = _stock("005930", sector="반도체")
        stale_stock = _stock("005931", sector="반도체")
        semi = _sector("반도체", rank=1, stocks=[current_stock])
        stale_target = BuyTarget(rank=1, sector_rank=1, stock=stale_stock)
        summary = SectorSummary(
            sectors=[semi],
            buy_targets=[stale_target],
            blocked_targets=[],
        )

        result = _incremental_update(
            summary,
            [{"action": "reconcile", "reason": "stock_set_changed"}],
        )

        result_codes = {
            target.stock.code
            for target in result.buy_targets + result.blocked_targets
        }
        assert result_codes == {"005930"}

    def test_add_sector_not_in_cache_skipped(self):
        """추가 이벤트의 업종이 캐시 sectors에 없으면 스킵 (W8 폴백 금지 — 명시적 무시)."""
        semi_stock = _stock("005930", sector="반도체")
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi], ["005930"])

        events = [{"sector": "없는업종", "action": "add", "reason": "cutoff_in", "stock_codes": ["999999"]}]
        result = _incremental_update(summary, events)

        result_codes = {t.stock.code for t in result.buy_targets}
        assert result_codes == {"005930"}  # 기존만 유지

    def test_guard_applied_on_added_stocks(self):
        """추가 종목에 가드 적용 — 등락률 초과 시 blocked_targets로 이동."""
        semi_stock = _stock("005930", sector="반도체", change_rate=2.0)
        # 8% 상승 → 상승률 차단 (block_rise_pct=7.0)
        hot_stock = _stock("005380", sector="자동차", change_rate=8.0)
        semi = _sector("반도체", rank=1, stocks=[semi_stock], is_cutoff_passed=True)
        auto = _sector("자동차", rank=2, stocks=[hot_stock], is_cutoff_passed=True)
        summary = _summary_with_targets([semi, auto], ["005930"])

        events = [{"sector": "자동차", "action": "add", "reason": "cutoff_in", "stock_codes": ["005380"]}]
        result = _incremental_update(summary, events)

        buy_codes = {t.stock.code for t in result.buy_targets}
        blocked_codes = {t.stock.code for t in result.blocked_targets}
        assert "005930" in buy_codes  # 반도체는 통과 유지
        assert "005380" in blocked_codes  # 자동차는 등락률 초과로 차단
