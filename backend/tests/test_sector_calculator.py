"""sector_calculator.py 단위 테스트 — 전체 파이프라인 로직 검증.

compute_sector_scores 및 compute_full_sector_summary의 데이터 추출,
필터링, 그룹핑, 3단계 누적 가산점, 컷오프 로직을 런타임 경로로 검증.
mock 없이 state.master_stocks_cache 직접 주입으로 DB 의존성 회피.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from backend.app.services.engine_state import state
from backend.app.domain.sector_calculator import (
    compute_sector_scores,
    compute_full_sector_summary,
)
from backend.app.domain.models import SectorScore, SectorSummary


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _stock_entry(
    *,
    sector: str,
    name: str,
    change_rate: float = 0.0,
    change: int = 0,
    trade_amount: int = 0,
    cur_price: int = 0,
    strength: str = "-",
    market: str = "0",
    nxt_enable: bool = False,
) -> dict:
    return {
        "sector": sector,
        "name": name,
        "change_rate": change_rate,
        "change": change,
        "trade_amount": trade_amount,
        "cur_price": cur_price,
        "strength": strength,
        "market": market,
        "nxt_enable": nxt_enable,
    }


@pytest.fixture
def cache():
    orig = dict(state.master_stocks_cache)
    state.master_stocks_cache.clear()
    yield state.master_stocks_cache
    state.master_stocks_cache.clear()
    state.master_stocks_cache.update(orig)


@pytest.fixture(autouse=True)
def _mock_db_connection():
    """get_db_connection을 mock하여 실제 DB 접근 차단 — 개별 테스트 실행 시 hang 방지."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB not available in unit test"))
    with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield


# ── 공통 테스트 데이터 ─────────────────────────────────────────────────────────

_SEMI_CODES = ["005930", "000660", "009150"]
_BANK_CODES = ["086790", "316140"]
_ALL_CODES = _SEMI_CODES + _BANK_CODES

_SEMI_STOCKS = {
    "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=2.5, change=1700, trade_amount=5_000_000_000, cur_price=70000, strength="120.5%"),
    "000660": _stock_entry(sector="반도체", name="SK하이닉스", change_rate=-1.0, change=-1200, trade_amount=3_000_000_000, cur_price=120000, strength="80.0%"),
    "009150": _stock_entry(sector="반도체", name="삼성전기", change_rate=0.5, change=450, trade_amount=1_000_000_000, cur_price=90000, strength="50.0%"),
}
_BANK_STOCKS = {
    "086790": _stock_entry(sector="은행", name="하나금융지주", change_rate=1.0, change=500, trade_amount=800_000_000, cur_price=50000, strength="90.0%"),
    "316140": _stock_entry(sector="은행", name="우리금융지주", change_rate=-0.5, change=-150, trade_amount=600_000_000, cur_price=30000, strength="60.0%"),
}
_ALL_STOCKS = {**_SEMI_STOCKS, **_BANK_STOCKS}

_AVG_AMT_5D = {
    "005930": 4000,
    "000660": 3000,
    "009150": 2000,
    "086790": 1000,
    "316140": 800,
}


def _populate_cache(cache_obj: dict, stocks: dict | None = None) -> None:
    if stocks is None:
        stocks = _ALL_STOCKS
    cache_obj.update(dict(stocks))


# ── compute_sector_scores: 기본 동작 ──────────────────────────────────────────

class TestComputeSectorScoresBasic:

    async def test_empty_all_codes_returns_empty(self, cache):
        result = await compute_sector_scores(
            [], trade_prices={}, trade_amounts={}, avg_amt_5d={},
        )
        assert result == []

    async def test_empty_cache_returns_empty(self, cache):
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
        )
        assert result == []

    async def test_single_sector_single_stock(self, cache):
        _populate_cache(cache, {"005930": _SEMI_STOCKS["005930"]})
        result = await compute_sector_scores(
            ["005930"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000},
        )
        assert len(result) == 1
        sc = result[0]
        assert sc.sector == "반도체"
        assert sc.total == 1
        assert sc.rise_count == 1
        assert sc.rise_ratio == 1.0

    async def test_two_sectors_grouping(self, cache):
        _populate_cache(cache)
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
        )
        assert len(result) == 2
        sectors = {sc.sector for sc in result}
        assert sectors == {"반도체", "은행"}

    async def test_rise_ratio_and_rise_count(self, cache):
        _populate_cache(cache, _SEMI_STOCKS)
        result = await compute_sector_scores(
            _SEMI_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
        )
        sc = result[0]
        assert sc.sector == "반도체"
        assert sc.rise_count == 2
        assert sc.total == 3
        assert sc.rise_ratio == pytest.approx(2 / 3, abs=0.01)

    async def test_avg_change_rate(self, cache):
        _populate_cache(cache, _SEMI_STOCKS)
        result = await compute_sector_scores(
            _SEMI_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
        )
        sc = result[0]
        expected = (2.5 + (-1.0) + 0.5) / 3
        assert sc.avg_change_rate == pytest.approx(expected, abs=0.01)

    async def test_returns_list_of_sector_score(self, cache):
        _populate_cache(cache)
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
        )
        for sc in result:
            assert isinstance(sc, SectorScore)


# ── compute_sector_scores: 데이터 우선순위 ────────────────────────────────────

class TestComputeSectorScoresDataPriority:

    async def test_trade_prices_overrides_cache(self, cache):
        _populate_cache(cache, {"005930": _SEMI_STOCKS["005930"]})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={"005930": 75000},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        assert stock.cur_price == 75000

    async def test_trade_amounts_overrides_cache(self, cache):
        _populate_cache(cache, {"005930": _SEMI_STOCKS["005930"]})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={"005930": 9_999_999_999},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        assert stock.trade_amount == 9_999_999_999

    async def test_cache_fallback_for_price(self, cache):
        _populate_cache(cache, {"005930": _SEMI_STOCKS["005930"]})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        assert stock.cur_price == 70000

    async def test_cache_fallback_for_trade_amount(self, cache):
        _populate_cache(cache, {"005930": _SEMI_STOCKS["005930"]})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        assert stock.trade_amount == 5_000_000_000


# ── compute_sector_scores: ratio_5d_pct 계산 ──────────────────────────────────

class TestComputeSectorScoresRatio5d:

    async def test_ratio_5d_pct_calculation(self, cache):
        _populate_cache(cache, {"005930": _SEMI_STOCKS["005930"]})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        avg5d_won = 4000 * 1_000_000
        expected = round(5_000_000_000 / avg5d_won * 100.0, 1)
        assert stock.ratio_5d_pct == expected

    async def test_ratio_5d_pct_zero_avg_returns_zero(self, cache):
        _populate_cache(cache, {"005930": _SEMI_STOCKS["005930"]})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 0},
        )
        stock = result[0].stocks[0]
        assert stock.ratio_5d_pct == 0.0

    async def test_ratio_5d_pct_zero_trade_amount_returns_zero(self, cache):
        entry = _stock_entry(sector="반도체", name="테스트", change_rate=1.0, trade_amount=0, cur_price=50000)
        _populate_cache(cache, {"005930": entry})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        assert stock.ratio_5d_pct == 0.0


# ── compute_sector_scores: 체결강도 파싱 ──────────────────────────────────────

class TestComputeSectorScoresStrength:

    async def test_strength_string_with_percent_and_comma(self, cache):
        entry = _stock_entry(sector="반도체", name="테스트", change_rate=1.0, trade_amount=1_000_000_000, cur_price=50000, strength="1,250.5%")
        _populate_cache(cache, {"005930": entry})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        assert stock.strength == 1250.5

    async def test_strength_dash_returns_minus_one(self, cache):
        entry = _stock_entry(sector="반도체", name="테스트", change_rate=1.0, trade_amount=1_000_000_000, cur_price=50000, strength="-")
        _populate_cache(cache, {"005930": entry})
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
        )
        stock = result[0].stocks[0]
        assert stock.strength == -1.0


# ── compute_sector_scores: 필터링 ─────────────────────────────────────────────

class TestComputeSectorScoresFiltering:

    async def test_min_avg_amt_eok_filters_stocks(self, cache):
        _populate_cache(cache)
        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            min_avg_amt_eok=25,
        )
        for sc in result:
            for stock in sc.stocks:
                assert stock.avg_amt_5d >= 25

    async def test_min_avg_amt_eok_zero_no_filter(self, cache):
        _populate_cache(cache)
        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            min_avg_amt_eok=0.0,
        )
        total_stocks = sum(sc.total for sc in result)
        assert total_stocks == 5

    async def test_cache_miss_stock_skipped(self, cache):
        _populate_cache(cache, _SEMI_STOCKS)
        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
        )
        sectors = {sc.sector for sc in result}
        assert "은행" not in sectors
        assert "반도체" in sectors


# ── compute_sector_scores: 트리밍/가중치 제거 검증 ──────────────────────────────

class TestComputeSectorScoresNoTrimWeights:

    async def test_no_weights_or_trim_params_needed(self, cache):
        """sector_weights/trim_* 파라미터 없이 정상 동작 (트리밍/가중치 제거 검증)."""
        _populate_cache(cache)
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
        )
        assert len(result) == 2
        for sc in result:
            assert isinstance(sc, SectorScore)

    async def test_avg_trade_amount_is_full_average(self, cache):
        """트리밍 제거: avg_trade_amount가 전체 종목 기준 평균 (잘라내기 없음)."""
        _populate_cache(cache, _SEMI_STOCKS)
        result = await compute_sector_scores(
            _SEMI_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
        )
        sc = result[0]
        expected = (5_000_000_000 + 3_000_000_000 + 1_000_000_000) / 3
        assert sc.avg_trade_amount == pytest.approx(expected, rel=0.01)


# ── compute_full_sector_summary ───────────────────────────────────────────────

class TestComputeFullSectorSummary:

    async def test_returns_sector_summary(self, cache):
        _populate_cache(cache)
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            latest_index={},
        )
        assert isinstance(result, SectorSummary)

    async def test_bonus_fields_populated_by_full_summary(self, cache):
        """compute_full_sector_summary가 calculate_bonus_scores 호출로 bonus_* 필드 채움."""
        _populate_cache(cache)
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            latest_index={},
        )
        for sc in result.sectors:
            assert sc.bonus_rise_ratio >= 0.0
            assert sc.bonus_trade_amount >= 0.0
            assert sc.bonus_relative_strength >= 0.0
            assert 0.0 <= sc.final_score <= 300.0
            expected = round(
                sc.bonus_rise_ratio + sc.bonus_relative_strength + sc.bonus_trade_amount, 1,
            )
            assert sc.final_score == expected

    async def test_empty_input_returns_empty_summary(self, cache):
        result = await compute_full_sector_summary(
            [], trade_prices={}, trade_amounts={}, avg_amt_5d={}, latest_index={},
        )
        assert isinstance(result, SectorSummary)
        assert result.sectors == []
        assert result.buy_targets == []
        assert result.blocked_targets == []

    async def test_min_rise_ratio_cutoff_pass(self, cache):
        _populate_cache(cache)
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            latest_index={},
            min_rise_ratio=0.6,
        )
        semi = next(sc for sc in result.sectors if sc.sector == "반도체")
        bank = next(sc for sc in result.sectors if sc.sector == "은행")
        assert semi.rise_ratio >= 0.6
        assert semi.rank >= 1
        assert bank.rise_ratio < 0.6
        assert bank.rank == 0

    async def test_min_rise_ratio_zero_no_cutoff(self, cache):
        _populate_cache(cache)
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            latest_index={},
            min_rise_ratio=0.0,
        )
        for sc in result.sectors:
            assert sc.rank > 0

    async def test_buy_targets_and_blocked_targets_empty(self, cache):
        _populate_cache(cache)
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            latest_index={},
        )
        assert result.buy_targets == []
        assert result.blocked_targets == []

    async def test_pass_sectors_get_sequential_ranks(self, cache):
        _populate_cache(cache)
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            latest_index={},
            min_rise_ratio=0.6,
        )
        pass_sectors = [sc for sc in result.sectors if sc.rank > 0]
        ranks = [sc.rank for sc in pass_sectors]
        assert ranks == list(range(1, len(pass_sectors) + 1))
