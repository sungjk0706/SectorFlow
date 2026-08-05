"""sector_calculator 연동 테스트 — 계산 본체와 업종 매핑 자료의 연동 검증.

계산 본체는 DB·엔진 상태를 직접 참조하지 않는다 (설계서 4.1 입력 계약).
본 테스트는 계산 본체가 전달받은 종목 자료·업종 매핑만으로 정상 동작하는지 검증하며,
DB 기반 업종 매핑 기능 자체는 test_sector_mapping.py에서 별도 검증한다 (역할 분리).
"""
from __future__ import annotations

import pytest

from backend.app.domain.sector_calculator import (
    compute_sector_scores,
    compute_full_sector_summary,
)


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
    """종목 자료에서 종목 코드별 업종 이름 매핑 생성 (서비스 경계에서 준비하는 자료 흉내)."""
    return {code: entry["sector"] for code, entry in stocks.items() if entry.get("sector")}


# ── 공통 테스트 데이터 — 반도체 3종목, 자동차 2종목 ──────────────────────────────

_STOCKS = {
    "005930": _stock_entry(sector="반도체", name="삼성전자", change_rate=2.5, change=1500, trade_amount=500000, cur_price=70000, market="0", nxt_enable=True),
    "000660": _stock_entry(sector="반도체", name="SK하이닉스", change_rate=-1.0, change=-1200, trade_amount=800000, cur_price=120000, market="0", nxt_enable=True),
    "009950": _stock_entry(sector="반도체", name="SK하이닉스2", change_rate=0.5, change=450, trade_amount=300000, cur_price=90000, market="0", nxt_enable=False),
    "005270": _stock_entry(sector="자동차", name="현대차", change_rate=2.0, change=5000, trade_amount=400000, cur_price=250000, market="0", nxt_enable=False),
    "000270": _stock_entry(sector="자동차", name="기아", change_rate=2.1, change=2000, trade_amount=350000, cur_price=100000, market="0", nxt_enable=False),
}
_SECTOR_MAP = _sector_map_from_stocks(_STOCKS)
_ALL_CODES = list(_STOCKS.keys())


class TestComputeSectorScoresIntegration:
    """명시 입력(종목 자료·업종 매핑) 기반 연동 — DB·엔진 상태 의존 없음."""

    @pytest.mark.asyncio
    async def test_returns_sector_scores_for_each_sector(self):
        """두 개 업종(반도체, 자동차)에 대해 SectorScore가 반환되는지 확인."""
        avg_amt_5d = {
            "005930": 50000,  # 백만원 단위 = 500억
            "000660": 80000,
            "009950": 30000,
            "005270": 40000,
            "000270": 35000,
        }

        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
            master_stocks_cache=_STOCKS, sector_map=_SECTOR_MAP,
        )

        sector_names = [s.sector for s in result]
        assert "반도체" in sector_names
        assert "자동차" in sector_names

    @pytest.mark.asyncio
    async def test_rise_ratio_calculation(self):
        """반도체 업종의 상승 비율이 정확한지 확인 (2/3 상승 = 0.667)."""
        all_codes = ["005930", "000660", "009950"]
        avg_amt_5d = {"005930": 50000, "000660": 80000, "009950": 30000}

        result = await compute_sector_scores(
            all_codes,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
            master_stocks_cache=_STOCKS, sector_map=_SECTOR_MAP,
        )

        semiconductor = next(s for s in result if s.sector == "반도체")
        assert semiconductor.total == 3
        assert semiconductor.rise_count == 2  # 삼성전자(+2.5), SK하이닉스2(+0.5) 상승
        assert abs(semiconductor.rise_ratio - 2 / 3) < 0.01

    @pytest.mark.asyncio
    async def test_filter_by_min_avg_amt(self):
        """min_avg_amt_eok 필터가 동작하는지 확인 — 500억 이상만 통과."""
        avg_amt_5d = {
            "005930": 50000,  # 500억
            "000660": 80000,  # 800억
            "009950": 30000,  # 300억 → 필터링됨
            "005270": 40000,  # 400억 → 필터링됨
            "000270": 35000,  # 350억 → 필터링됨
        }

        result = await compute_sector_scores(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
            master_stocks_cache=_STOCKS, sector_map=_SECTOR_MAP,
            min_avg_amt_eok=500,
        )

        # 500억 이상 = 005930(500억), 000660(800억)만 통과 → 반도체만 존재
        sector_names = [s.sector for s in result]
        assert "반도체" in sector_names
        assert "자동차" not in sector_names

        semiconductor = next(s for s in result if s.sector == "반도체")
        assert semiconductor.total == 2

    @pytest.mark.asyncio
    async def test_stocks_not_in_master_cache_are_skipped(self):
        """master_stocks_cache에 없는 종목은 제외되는지 확인."""
        all_codes = ["005930", "999999"]  # 999999는 cache에 없음
        avg_amt_5d = {"005930": 50000, "999999": 10000}

        result = await compute_sector_scores(
            all_codes,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
            master_stocks_cache=_STOCKS, sector_map=_SECTOR_MAP,
        )

        semiconductor = next(s for s in result if s.sector == "반도체")
        codes = [s.code for s in semiconductor.stocks]
        assert "005930" in codes
        assert "999999" not in codes

    @pytest.mark.asyncio
    async def test_trade_amounts_override_master_cache(self):
        """trade_amounts 인자가 master_stocks_cache의 거래대금보다 우선하는지 확인."""
        all_codes = ["005930"]
        avg_amt_5d = {"005930": 50000}

        result = await compute_sector_scores(
            all_codes,
            trade_prices={"005930": 75000},
            trade_amounts={"005930": 999999},
            avg_amt_5d=avg_amt_5d,
            master_stocks_cache=_STOCKS, sector_map=_SECTOR_MAP,
        )

        semiconductor = next(s for s in result if s.sector == "반도체")
        stock = semiconductor.stocks[0]
        assert stock.trade_amount == 999999
        assert stock.cur_price == 75000

    @pytest.mark.asyncio
    async def test_bonus_scores_calculated(self):
        """3단계 누적 가산점이 계산되어 final_score가 부여되는지 확인."""
        avg_amt_5d = {
            "005930": 50000, "000660": 80000, "009950": 30000,
            "005270": 40000, "000270": 35000,
        }

        result = await compute_full_sector_summary(
            _ALL_CODES,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
            master_stocks_cache=_STOCKS, sector_map=_SECTOR_MAP,
        )

        for s in result.sectors:
            assert s.final_score >= 0.0
            assert s.final_score <= 22.0
            assert 0.0 <= s.bonus_rise_ratio <= 10.0
            assert 0.0 <= s.bonus_relative_strength <= 7.0
            assert 0.0 <= s.bonus_trade_amount <= 5.0

    @pytest.mark.asyncio
    async def test_empty_codes_returns_empty_list(self):
        """빈 코드 리스트 입력 시 빈 결과 반환."""
        result = await compute_sector_scores(
            [],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={},
            master_stocks_cache=_STOCKS, sector_map=_SECTOR_MAP,
        )
        assert result == []
