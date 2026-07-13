"""sector_calculator DB 연동 통합 테스트.

in-memory SQLite를 사용하여 compute_sector_scores()가
master_stocks_table에서 데이터를 읽고 정상적으로 점수를 계산하는지 검증.
"""
from __future__ import annotations

import pytest
import aiosqlite

from backend.app.db import database
from backend.app.services.engine_state import state
from backend.app.domain.sector_calculator import (
    compute_sector_scores,
    compute_full_sector_summary,
)


@pytest.fixture
async def in_memory_db():
    """in-memory SQLite 연결 생성 및 테이블 스키마 구성."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS master_stocks_table (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT,
            sector TEXT,
            cur_price INTEGER,
            change INTEGER,
            change_rate REAL,
            trade_amount INTEGER,
            avg_5d_trade_amount INTEGER,
            high_5d_price INTEGER,
            date TEXT,
            nxt_enable INTEGER DEFAULT 0
        )
    ''')

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS custom_sectors (
            stock_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            hidden INTEGER DEFAULT 0
        )
    ''')

    await conn.execute('''
        CREATE TABLE IF NOT EXISTS sectors (
            name TEXT PRIMARY KEY
        )
    ''')

    # 테스트 데이터 삽입 — 반도체 업종 3종목, 자동차 업종 2종목
    test_stocks = [
        ("005930", "삼성전자", "0", "반도체", 70000, 1500, 2.5, 500000, 50000, 72000, "2025-07-04", 1),
        ("000660", "SK하이닉스", "0", "반도체", 120000, -1200, -1.0, 800000, 80000, 125000, "2025-07-04", 1),
        ("009950", "SK하이닉스2", "0", "반도체", 90000, 450, 0.5, 300000, 30000, 95000, "2025-07-04", 0),
        ("005270", "현대차", "0", "자동차", 250000, 5000, 2.0, 400000, 40000, 260000, "2025-07-04", 0),
        ("000270", "기아", "0", "자동차", 100000, 2000, 2.1, 350000, 35000, 105000, "2025-07-04", 0),
    ]

    for code, name, market, sector, cur_price, change, change_rate, ta, avg5d, high5d, date, nxt in test_stocks:
        await conn.execute(
            "INSERT INTO master_stocks_table (code, name, market, sector, cur_price, change, change_rate, trade_amount, avg_5d_trade_amount, high_5d_price, date, nxt_enable) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (code, name, market, sector, cur_price, change, change_rate, ta, avg5d, high5d, date, nxt),
        )

    await conn.execute("INSERT OR IGNORE INTO sectors (name) VALUES ('반도체')")
    await conn.execute("INSERT OR IGNORE INTO sectors (name) VALUES ('자동차')")
    await conn.commit()

    # database 모듈의 전역 연결을 in-memory로 교체
    original_conn = database._db_connection
    database._db_connection = conn

    yield conn

    # 정리
    database._db_connection = original_conn
    await conn.close()


@pytest.fixture
def setup_master_cache():
    """engine_state.master_stocks_cache에 테스트 데이터 주입."""
    original_cache = state.master_stocks_cache.copy()

    state.master_stocks_cache = {
        "005930": {"name": "삼성전자", "sector": "반도체", "cur_price": 70000, "change": 1500, "change_rate": 2.5, "trade_amount": 500000, "market": "0", "nxt_enable": True},
        "000660": {"name": "SK하이닉스", "sector": "반도체", "cur_price": 120000, "change": -1200, "change_rate": -1.0, "trade_amount": 800000, "market": "0", "nxt_enable": True},
        "009950": {"name": "SK하이닉스2", "sector": "반도체", "cur_price": 90000, "change": 450, "change_rate": 0.5, "trade_amount": 300000, "market": "0", "nxt_enable": False},
        "005270": {"name": "현대차", "sector": "자동차", "cur_price": 250000, "change": 5000, "change_rate": 2.0, "trade_amount": 400000, "market": "0", "nxt_enable": False},
        "000270": {"name": "기아", "sector": "자동차", "cur_price": 100000, "change": 2000, "change_rate": 2.1, "trade_amount": 350000, "market": "0", "nxt_enable": False},
    }

    yield state.master_stocks_cache

    state.master_stocks_cache = original_cache


class TestComputeSectorScoresDBIntegration:

    @pytest.mark.asyncio
    async def test_returns_sector_scores_for_each_sector(self, in_memory_db, setup_master_cache):
        """두 개 업종(반도체, 자동차)에 대해 SectorScore가 반환되는지 확인."""
        all_codes = ["005930", "000660", "009950", "005270", "000270"]
        avg_amt_5d = {
            "005930": 50000,  # 백만원 단위 = 500억
            "000660": 80000,
            "009950": 30000,
            "005270": 40000,
            "000270": 35000,
        }

        result = await compute_sector_scores(
            all_codes,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
        )

        sector_names = [s.sector for s in result]
        assert "반도체" in sector_names
        assert "자동차" in sector_names

    @pytest.mark.asyncio
    async def test_rise_ratio_calculation(self, in_memory_db, setup_master_cache):
        """반도체 업종의 상승 비율이 정확한지 확인 (2/3 상승 = 0.667)."""
        all_codes = ["005930", "000660", "009950"]
        avg_amt_5d = {"005930": 50000, "000660": 80000, "009950": 30000}

        result = await compute_sector_scores(
            all_codes,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
        )

        semiconductor = next(s for s in result if s.sector == "반도체")
        assert semiconductor.total == 3
        assert semiconductor.rise_count == 2  # 삼성전자(+2.5), SK하이닉스2(+0.5) 상승
        assert abs(semiconductor.rise_ratio - 2 / 3) < 0.01

    @pytest.mark.asyncio
    async def test_filter_by_min_avg_amt(self, in_memory_db, setup_master_cache):
        """min_avg_amt_eok 필터가 동작하는지 확인 — 500억 이상만 통과."""
        all_codes = ["005930", "000660", "009950", "005270", "000270"]
        avg_amt_5d = {
            "005930": 50000,  # 500억
            "000660": 80000,  # 800억
            "009950": 30000,  # 300억 → 필터링됨
            "005270": 40000,  # 400억 → 필터링됨
            "000270": 35000,  # 350억 → 필터링됨
        }

        result = await compute_sector_scores(
            all_codes,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
            min_avg_amt_eok=500,
        )

        # 500억 이상 = 005930(500억), 000660(800억)만 통과 → 반도체만 존재
        sector_names = [s.sector for s in result]
        assert "반도체" in sector_names
        assert "자동차" not in sector_names

        semiconductor = next(s for s in result if s.sector == "반도체")
        assert semiconductor.total == 2

    @pytest.mark.asyncio
    async def test_stocks_not_in_master_cache_are_skipped(self, in_memory_db, setup_master_cache):
        """master_stocks_cache에 없는 종목은 제외되는지 확인."""
        all_codes = ["005930", "999999"]  # 999999는 cache에 없음
        avg_amt_5d = {"005930": 50000, "999999": 10000}

        result = await compute_sector_scores(
            all_codes,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
        )

        semiconductor = next(s for s in result if s.sector == "반도체")
        codes = [s.code for s in semiconductor.stocks]
        assert "005930" in codes
        assert "999999" not in codes

    @pytest.mark.asyncio
    async def test_trade_amounts_override_master_cache(self, in_memory_db, setup_master_cache):
        """trade_amounts 인자가 master_stocks_cache의 거래대금보다 우선하는지 확인."""
        all_codes = ["005930"]
        avg_amt_5d = {"005930": 50000}

        result = await compute_sector_scores(
            all_codes,
            trade_prices={"005930": 75000},
            trade_amounts={"005930": 999999},
            avg_amt_5d=avg_amt_5d,
        )

        semiconductor = next(s for s in result if s.sector == "반도체")
        stock = semiconductor.stocks[0]
        assert stock.trade_amount == 999999
        assert stock.cur_price == 75000

    @pytest.mark.asyncio
    async def test_bonus_scores_calculated(self, in_memory_db, setup_master_cache):
        """3단계 누적 가산점이 계산되어 final_score가 부여되는지 확인."""
        all_codes = ["005930", "000660", "009950", "005270", "000270"]
        avg_amt_5d = {
            "005930": 50000, "000660": 80000, "009950": 30000,
            "005270": 40000, "000270": 35000,
        }

        result = await compute_full_sector_summary(
            all_codes,
            trade_prices={},
            trade_amounts={},
            avg_amt_5d=avg_amt_5d,
            latest_index={},
        )

        for s in result.sectors:
            assert s.final_score >= 0.0
            assert s.final_score <= 22.0
            assert 0.0 <= s.bonus_rise_ratio <= 10.0
            assert 0.0 <= s.bonus_relative_strength <= 7.0
            assert 0.0 <= s.bonus_trade_amount <= 5.0

    @pytest.mark.asyncio
    async def test_empty_codes_returns_empty_list(self, in_memory_db, setup_master_cache):
        """빈 코드 리스트 입력 시 빈 결과 반환."""
        result = await compute_sector_scores(
            [],
            trade_prices={},
            trade_amounts={},
            avg_amt_5d={},
        )
        assert result == []
