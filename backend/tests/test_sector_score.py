"""sector_score.py 단위 테스트 — 3단계 누적 가산점 시스템 검증 (순위별 차등 점수).

rank_to_tiered_score(순위별 차등), percentile_to_score(백분위 기반),
calculate_bonus_scores(3단계 누적 가산점 + 컷오프 + 순위 부여) 로직 검증.
"""
from __future__ import annotations

from backend.app.domain.models import SectorScore, StockScore
from backend.app.domain.sector_score import (
    rank_to_tiered_score,
    percentile_to_score,
    calculate_bonus_scores,
)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_stock(
    code: str,
    sector: str,
    change_rate: float,
    trade_amount: int = 1_000_000,
) -> StockScore:
    return StockScore(
        code=code, name=code, sector=sector, change_rate=change_rate,
        trade_amount=trade_amount, avg_amt_5d=1000, ratio_5d_pct=0.0,
        strength=0.0, cur_price=50000,
    )


def _make_sector_score(
    sector: str,
    *,
    rise_ratio: float = 0.5,
    avg_trade_amount: int = 1_000_000,
    stocks: list[StockScore] | None = None,
    total: int | None = None,
) -> SectorScore:
    if stocks is None:
        stocks = []
    if total is None:
        total = len(stocks) if stocks else 10
    rise_count = sum(1 for s in stocks if s.change_rate > 0) if stocks else int(rise_ratio * total)
    avg_change = sum(s.change_rate for s in stocks) / len(stocks) if stocks else 0.0
    return SectorScore(
        sector=sector, total=total, rise_count=rise_count, rise_ratio=rise_ratio,
        avg_change_rate=avg_change, avg_trade_amount=avg_trade_amount,
        avg_ratio_5d_pct=0.0, stocks=stocks,
    )


# ── rank_to_tiered_score ──────────────────────────────────────────────────────

class TestRankToTieredScore:
    def test_empty_list_returns_empty(self):
        assert rank_to_tiered_score([], max_score=10) == []

    def test_single_value_returns_max_score(self):
        assert rank_to_tiered_score([42.0], max_score=10) == [10]

    def test_all_same_values_returns_max_score(self):
        """모든 값이 동일하면 공동 1위 → 모두 만점."""
        assert rank_to_tiered_score([5.0, 5.0, 5.0], max_score=10) == [10, 10, 10]

    def test_tiered_score_formula_5_values(self):
        """5개 업종, max_score=10: 1위=10, 2위=9, 3위=8, 4위=7, 5위=6."""
        values = [30.0, 10.0, 50.0, 20.0, 40.0]  # 50=1위, 40=2위, 30=3위, 20=4위, 10=5위
        result = rank_to_tiered_score(values, max_score=10, higher_is_better=True)
        assert result == [8, 6, 10, 7, 9]

    def test_higher_is_better_false(self):
        """lower_is_better: 작은 값이 1위."""
        values = [10.0, 20.0, 30.0]  # 10=1위, 20=2위, 30=3위
        result = rank_to_tiered_score(values, max_score=10, higher_is_better=False)
        assert result == [10, 9, 8]

    def test_tie_values_same_rank_same_score(self):
        """동점: 같은 값은 같은 순위, 다음 순위 건너뜀."""
        # A=50(1위), B=50(1위), C=30(3위), D=20(4위)
        values = [50.0, 50.0, 30.0, 20.0]
        result = rank_to_tiered_score(values, max_score=10, higher_is_better=True)
        # 1위: 10, 3위: 10-3+1=8, 4위: 10-4+1=7
        assert result == [10, 10, 8, 7]

    def test_score_zero_below_max_score_rank(self):
        """max_score 순위 이하 = 0점. max_score=3, 5개 업종: 1위=3, 2위=2, 3위=1, 4위=0, 5위=0."""
        values = [50.0, 40.0, 30.0, 20.0, 10.0]
        result = rank_to_tiered_score(values, max_score=3, higher_is_better=True)
        assert result == [3, 2, 1, 0, 0]

    def test_max_score_zero_all_zero(self):
        """max_score=0 → 모든 업종 0점."""
        values = [50.0, 40.0, 30.0]
        result = rank_to_tiered_score(values, max_score=0, higher_is_better=True)
        assert result == [0, 0, 0]


# ── percentile_to_score ─────────────────────────────────────────────────────────

class TestPercentileToScore:
    def test_empty_list_returns_empty(self):
        assert percentile_to_score([]) == []

    def test_single_value_returns_100(self):
        assert percentile_to_score([42.0]) == [100.0]

    def test_all_same_values_returns_100(self):
        """모든 값 동일 → 모두 100점 (공동 최상위)."""
        assert percentile_to_score([5.0, 5.0, 5.0]) == [100.0, 100.0, 100.0]

    def test_full_scale_0_to_100(self):
        """3개 값: 최대=100, 중간=50, 최소=0 (완전 0~100 스케일)."""
        values = [10.0, 20.0, 30.0]
        result = percentile_to_score(values, higher_is_better=True)
        assert result == [0.0, 50.0, 100.0]

    def test_higher_is_better_false(self):
        """lower_is_better: 작은 값이 100점."""
        values = [10.0, 20.0, 30.0]
        result = percentile_to_score(values, higher_is_better=False)
        assert result == [100.0, 50.0, 0.0]

    def test_tie_values_get_highest_score(self):
        """동점: 같은 값은 그룹 내 최고 점수. [30,30,10] → 30s=100, 10=0."""
        values = [30.0, 30.0, 10.0]
        result = percentile_to_score(values, higher_is_better=True)
        assert result == [100.0, 100.0, 0.0]

    def test_five_values_spread(self):
        """5개 값: 1위=100, 2위=75, 3위=50, 4위=25, 5위=0."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = percentile_to_score(values, higher_is_better=True)
        assert result == [0.0, 25.0, 50.0, 75.0, 100.0]


# ── calculate_bonus_scores ──────────────────────────────────────────────────────

class TestCalculateBonusScores:
    def test_empty_list_no_error(self):
        calculate_bonus_scores([])

    def test_single_sector_gets_rank_1_and_full_score(self):
        """단일 업종: 1차=10, 3차=5, 2차=7(단일 종목 백분위=100 → 단일 업종 tiered=7) → final=22."""
        sc = _make_sector_score(
            "반도체", rise_ratio=0.8, avg_trade_amount=1_000_000,
            stocks=[_make_stock("A", "반도체", 2.5)],
        )
        calculate_bonus_scores([sc])
        assert sc.rank == 1
        assert sc.bonus_rise_ratio == 10.0
        assert sc.bonus_trade_amount == 5.0
        assert sc.bonus_relative_strength == 7.0
        assert sc.final_score == 22.0

    def test_bonus_rise_ratio_ranking(self):
        """1차 가산점: rise_ratio 순위 → rank_to_tiered_score (기본 만점 10)."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", rise_ratio=0.7, stocks=[_make_stock("b1", "B", 1.0)]),
            _make_sector_score("C", rise_ratio=0.5, stocks=[_make_stock("c1", "C", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        a = next(s for s in scores if s.sector == "A")
        b = next(s for s in scores if s.sector == "B")
        c = next(s for s in scores if s.sector == "C")
        # rise_ratio: B(0.7)=1위=10, C(0.5)=2위=9, A(0.3)=3위=8
        assert b.bonus_rise_ratio == 10.0
        assert c.bonus_rise_ratio == 9.0
        assert a.bonus_rise_ratio == 8.0

    def test_bonus_trade_amount_ranking(self):
        """3차 가산점: avg_trade_amount 순위 → rank_to_tiered_score (기본 만점 5)."""
        scores = [
            _make_sector_score("A", avg_trade_amount=100, stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", avg_trade_amount=900, stocks=[_make_stock("b1", "B", 1.0)]),
            _make_sector_score("C", avg_trade_amount=500, stocks=[_make_stock("c1", "C", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        a = next(s for s in scores if s.sector == "A")
        b = next(s for s in scores if s.sector == "B")
        c = next(s for s in scores if s.sector == "C")
        # 거래대금: B(900)=1위=5, C(500)=2위=4, A(100)=3위=3
        assert b.bonus_trade_amount == 5.0
        assert c.bonus_trade_amount == 4.0
        assert a.bonus_trade_amount == 3.0

    def test_cutoff_min_rise_ratio_sets_rank_zero(self):
        """min_rise_ratio 미만 업종 rank=0, 2차 가산점=0."""
        scores = [
            _make_sector_score("통과", rise_ratio=0.8, stocks=[_make_stock("p1", "통과", 2.0)]),
            _make_sector_score("탈락", rise_ratio=0.2, stocks=[_make_stock("f1", "탈락", -1.0)]),
        ]
        calculate_bonus_scores(scores, min_rise_ratio=0.5)
        passed = next(s for s in scores if s.sector == "통과")
        failed = next(s for s in scores if s.sector == "탈락")
        assert passed.rank == 1
        assert failed.rank == 0
        assert failed.bonus_relative_strength == 0.0

    def test_second_bonus_uses_passed_sectors_only(self):
        """2차 가산점: 통과 업종 종목들만 모집단 → 백분위 평균 → tiered 점수."""
        # 통과 업종 2개: 반도체(종목 +3, +1), 은행(종목 +2, -1)
        # 탈락 업종 1개: 자동차(종목 +10, -5) — 모집단에서 제외
        scores = [
            _make_sector_score("반도체", rise_ratio=0.8, avg_trade_amount=500,
                               stocks=[_make_stock("s1", "반도체", 3.0), _make_stock("s2", "반도체", 1.0)]),
            _make_sector_score("은행", rise_ratio=0.6, avg_trade_amount=300,
                               stocks=[_make_stock("b1", "은행", 2.0), _make_stock("b2", "은행", -1.0)]),
            _make_sector_score("자동차", rise_ratio=0.2, avg_trade_amount=900,
                               stocks=[_make_stock("a1", "자동차", 10.0), _make_stock("a2", "자동차", -5.0)]),
        ]
        calculate_bonus_scores(scores, min_rise_ratio=0.5)
        semi = next(s for s in scores if s.sector == "반도체")
        bank = next(s for s in scores if s.sector == "은행")
        auto = next(s for s in scores if s.sector == "자동차")
        # 자동차는 탈락 → rank=0, 2차=0
        assert auto.rank == 0
        assert auto.bonus_relative_strength == 0.0
        # 통과 업종 종목 모집단: [3, 1, 2, -1] → 백분위(hib=True)
        # 정렬: 3(1위)=100, 2(2위)=66.7, 1(3위)=33.3, -1(4위)=0
        # 반도체 평균: (100 + 33.3) / 2 = 66.65 → round = 66.7
        # 은행 평균: (66.7 + 0) / 2 = 33.35 → round = 33.4
        # 업종 간 순위: 반도체(66.7)=1위, 은행(33.4)=2위
        # tiered 점수 (max_relative_strength_score=7): 반도체=7, 은행=6
        assert semi.bonus_relative_strength == 7.0
        assert bank.bonus_relative_strength == 6.0

    def test_final_score_is_sum_of_three_bonuses(self):
        """final_score = 1차 + 2차 + 3차 (정수 합)."""
        sc = _make_sector_score(
            "반도체", rise_ratio=0.8, avg_trade_amount=1_000_000,
            stocks=[_make_stock("s1", "반도체", 2.5)],
        )
        calculate_bonus_scores([sc])
        expected = int(sc.bonus_rise_ratio) + int(sc.bonus_relative_strength) + int(sc.bonus_trade_amount)
        assert sc.final_score == float(expected)

    def test_final_score_range_0_to_max_sum(self):
        """final_score 범위: 0 ~ 만점 합 (기본 10+7+5=22)."""
        scores = [
            _make_sector_score("A", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", rise_ratio=0.7, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 2.0)]),
        ]
        calculate_bonus_scores(scores)
        for sc in scores:
            assert 0.0 <= sc.final_score <= 22.0

    def test_sort_order_by_final_score_descending(self):
        """종합 점수 기반 내림차순 정렬."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
            _make_sector_score("C", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("c1", "C", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        assert scores[0].final_score >= scores[1].final_score >= scores[2].final_score

    def test_tiebreak_by_relative_strength_then_name(self):
        """final_score 동점 시 2차 가산점 → 업종명 순 타이브레이크."""
        # 두 업종 모두 rise_ratio=0.5, avg_trade_amount=500 → 1차/3차 동점
        # 종목 change_rate 동일 → 2차 동점 → 업종명 알파벳순
        scores = [
            _make_sector_score("Z", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("z1", "Z", 1.0)]),
            _make_sector_score("A", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("a1", "A", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        assert scores[0].sector == "A"
        assert scores[1].sector == "Z"
        assert scores[0].final_score == scores[1].final_score

    def test_rank_assignment_sequential_for_passed(self):
        """통과 업종에 1, 2, 3... 순차 rank 부여."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
            _make_sector_score("C", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("c1", "C", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        passed = [s for s in scores if s.rank > 0]
        ranks = [s.rank for s in passed]
        assert ranks == list(range(1, len(passed) + 1))

    def test_no_passed_sectors_all_second_bonus_zero(self):
        """모든 업종 컷오프 탈락 → 2차 가산점 전부 0."""
        scores = [
            _make_sector_score("A", rise_ratio=0.1, stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", rise_ratio=0.2, stocks=[_make_stock("b1", "B", 2.0)]),
        ]
        calculate_bonus_scores(scores, min_rise_ratio=0.5)
        for sc in scores:
            assert sc.rank == 0
            assert sc.bonus_relative_strength == 0.0

    def test_no_cutoff_all_sectors_ranked(self):
        """min_rise_ratio=0 → 모든 업종 통과, 순차 rank 부여."""
        scores = [
            _make_sector_score("A", rise_ratio=0.1, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
        ]
        calculate_bonus_scores(scores, min_rise_ratio=0.0)
        for sc in scores:
            assert sc.rank > 0

    def test_custom_max_scores(self):
        """사용자 설정 만점으로 점수 범위 변경."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
        ]
        calculate_bonus_scores(
            scores,
            max_rise_ratio_score=20,
            max_relative_strength_score=15,
            max_trade_amount_score=10,
        )
        b = next(s for s in scores if s.sector == "B")
        # B는 1위 → 1차=20, 3차=10, 2차=15 (단일 종목 → 단일 업종 tiered=15)
        assert b.bonus_rise_ratio == 20.0
        assert b.bonus_trade_amount == 10.0
        assert b.bonus_relative_strength == 15.0
        assert b.final_score == 45.0

    def test_max_score_zero_disables_dimension(self):
        """만점=0 → 해당 차수 모든 업종 0점."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
        ]
        calculate_bonus_scores(
            scores,
            max_rise_ratio_score=0,
            max_relative_strength_score=0,
            max_trade_amount_score=0,
        )
        for sc in scores:
            assert sc.bonus_rise_ratio == 0.0
            assert sc.bonus_relative_strength == 0.0
            assert sc.bonus_trade_amount == 0.0
            assert sc.final_score == 0.0
