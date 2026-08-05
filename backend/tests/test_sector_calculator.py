"""sector_calculator.py 단위 테스트 — 전체 파이프라인 로직 검증.

compute_sector_scores 및 compute_full_sector_summary의 데이터 추출,
필터링, 그룹핑, 3단계 누적 가산점, 컷오프 로직을 런타임 경로로 검증.

계산 본체는 명시 입력만 사용하므로 DB·엔진 상태 의존 없이 자료를 직접 전달한다.
"""
from __future__ import annotations

import pytest

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
    change_rate: float | None = 0.0,
    change: int = 0,
    trade_amount: int | None = 0,
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


def _sector_map_from_stocks(stocks: dict[str, dict]) -> dict[str, str]:
    """종목 자료에서 종목 코드별 업종 이름 매핑 생성 (계산 영역 바깥에서 준비하는 자료 흉내)."""
    return {code: entry["sector"] for code, entry in stocks.items() if entry.get("sector")}


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
_ALL_SECTOR_MAP = _sector_map_from_stocks(_ALL_STOCKS)
_SEMI_SECTOR_MAP = _sector_map_from_stocks(_SEMI_STOCKS)

_AVG_AMT_5D = {
    "005930": 4000,
    "000660": 3000,
    "009150": 2000,
    "086790": 1000,
    "316140": 800,
}


# ── compute_sector_scores: 기본 동작 ──────────────────────────────────────────

class TestComputeSectorScoresBasic:

    async def test_empty_all_codes_returns_empty(self):
        result = await compute_sector_scores(
            [], trade_prices={}, trade_amounts={}, avg_amt_5d={},
            master_stocks_cache={}, sector_map={},
        )
        assert result == []

    async def test_empty_cache_returns_empty(self):
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache={}, sector_map=_ALL_SECTOR_MAP,
        )
        assert result == []

    async def test_single_sector_single_stock(self):
        stocks = {"005930": _SEMI_STOCKS["005930"]}
        result = await compute_sector_scores(
            ["005930"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert len(result) == 1
        sc = result[0]
        assert sc.sector == "반도체"
        assert sc.total == 1
        assert sc.rise_count == 1
        assert sc.rise_ratio == 1.0

    async def test_two_sectors_grouping(self):
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
        )
        assert len(result) == 2
        sectors = {sc.sector for sc in result}
        assert sectors == {"반도체", "은행"}

    async def test_rise_ratio_and_rise_count(self):
        result = await compute_sector_scores(
            _SEMI_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_SEMI_STOCKS, sector_map=_SEMI_SECTOR_MAP,
        )
        sc = result[0]
        assert sc.sector == "반도체"
        assert sc.rise_count == 2
        assert sc.total == 3
        assert sc.rise_ratio == pytest.approx(2 / 3, abs=0.01)

    async def test_avg_change_rate(self):
        result = await compute_sector_scores(
            _SEMI_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_SEMI_STOCKS, sector_map=_SEMI_SECTOR_MAP,
        )
        sc = result[0]
        expected = (2.5 + (-1.0) + 0.5) / 3
        assert sc.avg_change_rate == pytest.approx(expected, abs=0.01)

    async def test_returns_list_of_sector_score(self):
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
        )
        for sc in result:
            assert isinstance(sc, SectorScore)


# ── compute_sector_scores: 데이터 우선순위 ────────────────────────────────────

class TestComputeSectorScoresDataPriority:

    async def test_trade_prices_overrides_cache(self):
        stocks = {"005930": _SEMI_STOCKS["005930"]}
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={"005930": 75000},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        stock = result[0].stocks[0]
        assert stock.cur_price == 75000

    async def test_trade_amounts_overrides_cache(self):
        stocks = {"005930": _SEMI_STOCKS["005930"]}
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={"005930": 9_999_999_999},
            avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        stock = result[0].stocks[0]
        assert stock.trade_amount == 9_999_999_999

    async def test_cache_fallback_for_price(self):
        stocks = {"005930": _SEMI_STOCKS["005930"]}
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        stock = result[0].stocks[0]
        assert stock.cur_price == 70000

    async def test_cache_fallback_for_trade_amount(self):
        stocks = {"005930": _SEMI_STOCKS["005930"]}
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        stock = result[0].stocks[0]
        assert stock.trade_amount == 5_000_000_000


# ── compute_sector_scores: 체결강도 파싱 ──────────────────────────────────────

class TestComputeSectorScoresStrength:

    async def test_strength_string_with_percent_and_comma(self):
        entry = _stock_entry(sector="반도체", name="테스트", change_rate=1.0, trade_amount=1_000_000_000, cur_price=50000, strength="1,250.5%")
        stocks = {"005930": entry}
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        stock = result[0].stocks[0]
        assert stock.strength == 1250.5

    async def test_strength_dash_returns_minus_one(self):
        entry = _stock_entry(sector="반도체", name="테스트", change_rate=1.0, trade_amount=1_000_000_000, cur_price=50000, strength="-")
        stocks = {"005930": entry}
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        stock = result[0].stocks[0]
        assert stock.strength == -1.0


# ── compute_sector_scores: 필터링 ─────────────────────────────────────────────

class TestComputeSectorScoresFiltering:

    async def test_min_avg_amt_eok_filters_stocks(self):
        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
            min_avg_amt_eok=25,
        )
        for sc in result:
            for stock in sc.stocks:
                assert stock.avg_amt_5d >= 25

    async def test_min_avg_amt_eok_zero_no_filter(self):
        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
            min_avg_amt_eok=0.0,
        )
        total_stocks = sum(sc.total for sc in result)
        assert total_stocks == 5

    async def test_cache_miss_stock_skipped(self):
        # 은행 종목이 master_stocks_cache에 없으면 해당 업종 제외
        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_SEMI_STOCKS, sector_map=_ALL_SECTOR_MAP,
        )
        sectors = {sc.sector for sc in result}
        assert "은행" not in sectors
        assert "반도체" in sectors


# ── compute_sector_scores: 트리밍/가중치 제거 검증 ──────────────────────────────

class TestComputeSectorScoresNoTrimWeights:

    async def test_no_weights_or_trim_params_needed(self):
        """sector_weights/trim_* 파라미터 없이 정상 동작 (트리밍/가중치 제거 검증)."""
        result = await compute_sector_scores(
            _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
        )
        assert len(result) == 2
        for sc in result:
            assert isinstance(sc, SectorScore)

    async def test_avg_trade_amount_is_full_average(self):
        """트리밍 제거: avg_trade_amount가 전체 종목 기준 평균 (잘라내기 없음)."""
        result = await compute_sector_scores(
            _SEMI_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_SEMI_STOCKS, sector_map=_SEMI_SECTOR_MAP,
        )
        sc = result[0]
        expected = (5_000_000_000 + 3_000_000_000 + 1_000_000_000) / 3
        assert sc.avg_trade_amount == pytest.approx(expected, rel=0.01)


# ── compute_full_sector_summary ───────────────────────────────────────────────

class TestComputeFullSectorSummary:

    async def test_returns_sector_summary(self):
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
        )
        assert isinstance(result, SectorSummary)

    async def test_bonus_fields_populated_by_full_summary(self):
        """compute_full_sector_summary가 calculate_bonus_scores 호출로 bonus_* 필드 채움."""
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
        )
        # 업종 2개 → 만점 = 2, 만점 합 = 6 (슬라이더 기본값 0)
        n_sectors = len(result.sectors)
        max_total = n_sectors * 3
        for sc in result.sectors:
            assert sc.bonus_rise_ratio >= 0.0
            assert sc.bonus_trade_amount >= 0.0
            assert sc.bonus_relative_strength >= 0.0
            assert 0.0 <= sc.final_score <= float(max_total)
            expected = sc.bonus_rise_ratio + sc.bonus_relative_strength + sc.bonus_trade_amount
            assert sc.final_score == expected

    async def test_empty_input_returns_empty_summary(self):
        result = await compute_full_sector_summary(
            [], trade_prices={}, trade_amounts={}, avg_amt_5d={},
            master_stocks_cache={}, sector_map={},
        )
        assert isinstance(result, SectorSummary)
        assert result.sectors == []
        assert result.buy_targets == []
        assert result.blocked_targets == []

    async def test_min_rise_ratio_cutoff_pass(self):
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
            min_rise_ratio=0.6,
        )
        semi = next(sc for sc in result.sectors if sc.sector == "반도체")
        bank = next(sc for sc in result.sectors if sc.sector == "은행")
        assert semi.rise_ratio >= 0.6
        assert semi.rank >= 1
        assert bank.rise_ratio < 0.6
        assert bank.is_cutoff_passed is False

    async def test_min_rise_ratio_zero_no_cutoff(self):
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
            min_rise_ratio=0.0,
        )
        for sc in result.sectors:
            assert sc.rank > 0

    async def test_buy_targets_and_blocked_targets_empty(self):
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
        )
        assert result.buy_targets == []
        assert result.blocked_targets == []

    async def test_all_sectors_get_sequential_ranks(self):
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
            min_rise_ratio=0.6,
        )
        # 모든 업종에 1..N 순위 부여 (컷오프 미달 포함, is_cutoff_passed로 구분)
        all_ranks = [sc.rank for sc in result.sectors]
        assert all_ranks == list(range(1, len(result.sectors) + 1))


# ── P-001 Step 3: 미수신 종목(None) 제외 검증 ──────────────────────────────────

class TestComputeSectorScoresNoneExclusion:
    """change_rate 또는 trade_amount가 None인 미수신 종목은 업종 점수 계산에서 제외 (P20/P22)."""

    async def test_change_rate_none_stock_excluded(self):
        # 005930: 정상, 000660: change_rate=None (미수신)
        stocks = {
            "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=2.5, trade_amount=5_000_000_000, cur_price=70000),
            "000660": _stock_entry(sector="반도체", name="SK하이닉스", change_rate=None, trade_amount=3_000_000_000, cur_price=120000),
        }
        result = await compute_sector_scores(
            ["005930", "000660"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000, "000660": 3000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert len(result) == 1
        sc = result[0]
        # 000660 제외 → 1개만 남음
        assert sc.total == 1
        codes = {s.code for s in sc.stocks}
        assert codes == {"005930"}

    async def test_trade_amount_none_stock_excluded(self):
        # 005930: 정상, 000660: trade_amount=None (미수신)
        stocks = {
            "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=2.5, trade_amount=5_000_000_000, cur_price=70000),
            "000660": _stock_entry(sector="반도체", name="SK하이닉스", change_rate=-1.0, trade_amount=None, cur_price=120000),
        }
        result = await compute_sector_scores(
            ["005930", "000660"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000, "000660": 3000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert len(result) == 1
        sc = result[0]
        assert sc.total == 1
        codes = {s.code for s in sc.stocks}
        assert codes == {"005930"}

    async def test_all_stocks_none_returns_empty(self):
        # 전체 종목 change_rate=None → stocks 빈 리스트 → 업종 스킵
        stocks = {
            "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=None, trade_amount=5_000_000_000, cur_price=70000),
            "000660": _stock_entry(sector="반도체", name="SK하이닉스", change_rate=None, trade_amount=3_000_000_000, cur_price=120000),
        }
        result = await compute_sector_scores(
            ["005930", "000660"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000, "000660": 3000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert result == []

    async def test_zero_change_rate_not_excluded(self):
        # change_rate=0.0은 정상 수신 0% → 제외되지 않음 (None과 0 구분 — P22)
        stocks = {
            "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=0.0, trade_amount=5_000_000_000, cur_price=70000),
        }
        result = await compute_sector_scores(
            ["005930"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert len(result) == 1
        assert result[0].total == 1

    async def test_zero_trade_amount_not_excluded(self):
        # trade_amount=0은 정상 수신 0원 → 제외되지 않음 (None과 0 구분 — P22)
        stocks = {
            "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=2.5, trade_amount=0, cur_price=70000),
        }
        result = await compute_sector_scores(
            ["005930"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert len(result) == 1
        assert result[0].total == 1

    async def test_none_stock_no_type_error(self):
        # None 종목이 업종 점수 계산에서 제외되어 TypeError 미발생 확인
        stocks = {
            "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=2.5, trade_amount=None, cur_price=70000),
        }
        # 예외 없이 빈 결과 반환해야 함
        result = await compute_sector_scores(
            ["005930"], trade_prices={}, trade_amounts={}, avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert result == []


# ── 명시 입력 계약: master_stocks_cache·sector_map 필수 (설계서 4.1) ────────────
# 계산 본체가 외부 상태·조회 없이 전달받은 자료만으로 동작하는지 검증.
# 누락 시 TypeError로 즉시 드러나야 한다 (P20 폴백 금지).

class TestComputeSectorScoresExplicitInputsRequired:
    """master_stocks_cache·sector_map 누락 시 TypeError — 폴백으로 덮지 않고 즉시 오류."""

    async def test_missing_master_stocks_cache_raises(self):
        with pytest.raises(TypeError):
            await compute_sector_scores(
                _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
                sector_map=_ALL_SECTOR_MAP,
            )

    async def test_missing_sector_map_raises(self):
        with pytest.raises(TypeError):
            await compute_sector_scores(
                _ALL_CODES, trade_prices={}, trade_amounts={}, avg_amt_5d=_AVG_AMT_5D,
                master_stocks_cache=_ALL_STOCKS,
            )

    async def test_explicit_inputs_ignore_unrelated_state(self):
        # 명시 입력이 우선 — 다른 자료를 섞어도 결과는 명시 입력 기준
        stocks = {"005930": _SEMI_STOCKS["005930"]}
        result = await compute_sector_scores(
            ["005930"],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={"005930": 4000},
            master_stocks_cache=stocks, sector_map=_sector_map_from_stocks(stocks),
        )
        assert len(result) == 1
        sc = result[0]
        assert sc.sector == "반도체"
        stock = sc.stocks[0]
        assert stock.name == "삼성전자"
        assert stock.change_rate == 2.5

    async def test_explicit_inputs_full_summary(self):
        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=_AVG_AMT_5D,
            master_stocks_cache=_ALL_STOCKS, sector_map=_ALL_SECTOR_MAP,
            min_rise_ratio=0.6,
        )
        assert isinstance(result, SectorSummary)
        assert len(result.sectors) == 2
        # 순위 1..N 부여 확인
        all_ranks = [sc.rank for sc in result.sectors]
        assert all_ranks == list(range(1, len(result.sectors) + 1))
