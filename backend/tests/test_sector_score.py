"""sector_score.py 단위 테스트 — 3단계 누적 가산점 시스템 검증 (만점 자동화 + 슬라이더 + 가중 순위 합).

rank_to_tiered_score(순위별 차등, float 반환),
calculate_bonus_scores(3단계 누적 가산점 + 만점 자동화 + 슬라이더 + 가중 순위 합 + 컷오프 + is_cutoff_passed) 로직 검증.
"""
from __future__ import annotations

from backend.app.domain.models import SectorScore, StockScore
from backend.app.domain.sector_score import (
    rank_to_tiered_score,
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
        assert rank_to_tiered_score([42.0], max_score=10) == [10.0]

    def test_all_same_values_returns_max_score(self):
        """모든 값이 동일하면 공동 1위 → 모두 만점."""
        assert rank_to_tiered_score([5.0, 5.0, 5.0], max_score=10) == [10.0, 10.0, 10.0]

    def test_tiered_score_formula_5_values(self):
        """5개 업종, max_score=10: 1위=10, 2위=9, 3위=8, 4위=7, 5위=6."""
        values = [30.0, 10.0, 50.0, 20.0, 40.0]  # 50=1위, 40=2위, 30=3위, 20=4위, 10=5위
        result = rank_to_tiered_score(values, max_score=10, higher_is_better=True)
        assert result == [8.0, 6.0, 10.0, 7.0, 9.0]

    def test_higher_is_better_false(self):
        """lower_is_better: 작은 값이 1위."""
        values = [10.0, 20.0, 30.0]  # 10=1위, 20=2위, 30=3위
        result = rank_to_tiered_score(values, max_score=10, higher_is_better=False)
        assert result == [10.0, 9.0, 8.0]

    def test_tie_values_same_rank_same_score(self):
        """동점: 같은 값은 같은 순위, 다음 순위 건너뜀."""
        # A=50(1위), B=50(1위), C=30(3위), D=20(4위)
        values = [50.0, 50.0, 30.0, 20.0]
        result = rank_to_tiered_score(values, max_score=10, higher_is_better=True)
        # 1위: 10, 3위: 10-3+1=8, 4위: 10-4+1=7
        assert result == [10.0, 10.0, 8.0, 7.0]

    def test_score_zero_below_max_score_rank(self):
        """max_score 순위 이하 = 0점. max_score=3, 5개 업종: 1위=3, 2위=2, 3위=1, 4위=0, 5위=0."""
        values = [50.0, 40.0, 30.0, 20.0, 10.0]
        result = rank_to_tiered_score(values, max_score=3, higher_is_better=True)
        assert result == [3.0, 2.0, 1.0, 0.0, 0.0]

    def test_max_score_zero_all_zero(self):
        """max_score=0 → 모든 업종 0점."""
        values = [50.0, 40.0, 30.0]
        result = rank_to_tiered_score(values, max_score=0, higher_is_better=True)
        assert result == [0.0, 0.0, 0.0]

    def test_float_max_score(self):
        """소수점 만점 허용 (슬라이더 비율 적용). max_score=7.5, 3개 업종."""
        values = [30.0, 10.0, 20.0]  # 30=1위, 20=2위, 10=3위
        result = rank_to_tiered_score(values, max_score=7.5, higher_is_better=True)
        # 인덱스 순: 30→7.5(1위), 10→5.5(3위), 20→6.5(2위)
        assert result == [7.5, 5.5, 6.5]


# ── calculate_bonus_scores ──────────────────────────────────────────────────────

class TestCalculateBonusScores:
    def test_empty_list_no_error(self):
        calculate_bonus_scores([])

    def test_single_sector_max_score_equals_sector_count(self):
        """단일 업종: 만점 = 업종 수 = 1. 1차=1, 3차=1, 2차=1(단일 종목 가중치=1.0 → 단일 업종 tiered=1) → final=3."""
        sc = _make_sector_score(
            "반도체", rise_ratio=0.8, avg_trade_amount=1_000_000,
            stocks=[_make_stock("A", "반도체", 2.5)],
        )
        calculate_bonus_scores([sc])
        assert sc.rank == 1
        assert sc.is_cutoff_passed is True
        assert sc.bonus_rise_ratio == 1.0  # 만점 = 1 (업종 수)
        assert sc.bonus_trade_amount == 1.0
        assert sc.bonus_relative_strength == 1.0  # 단일 종목 가중치 1.0 → 단일 업종 tiered 만점
        assert sc.final_score == 3.0

    def test_bonus_rise_ratio_ranking_auto_max(self):
        """1차 가산점: rise_ratio 순위 → 만점 = 업종 수 = 3. 1위=3, 2위=2, 3위=1."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", rise_ratio=0.7, stocks=[_make_stock("b1", "B", 1.0)]),
            _make_sector_score("C", rise_ratio=0.5, stocks=[_make_stock("c1", "C", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        a = next(s for s in scores if s.sector == "A")
        b = next(s for s in scores if s.sector == "B")
        c = next(s for s in scores if s.sector == "C")
        # rise_ratio: B(0.7)=1위=3, C(0.5)=2위=2, A(0.3)=3위=1
        assert b.bonus_rise_ratio == 3.0
        assert c.bonus_rise_ratio == 2.0
        assert a.bonus_rise_ratio == 1.0

    def test_bonus_trade_amount_ranking_auto_max(self):
        """3차 가산점: avg_trade_amount 순위 → 만점 = 업종 수 = 3."""
        scores = [
            _make_sector_score("A", avg_trade_amount=100, stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", avg_trade_amount=900, stocks=[_make_stock("b1", "B", 1.0)]),
            _make_sector_score("C", avg_trade_amount=500, stocks=[_make_stock("c1", "C", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        a = next(s for s in scores if s.sector == "A")
        b = next(s for s in scores if s.sector == "B")
        c = next(s for s in scores if s.sector == "C")
        # 거래대금: B(900)=1위=3, C(500)=2위=2, A(100)=3위=1
        assert b.bonus_trade_amount == 3.0
        assert c.bonus_trade_amount == 2.0
        assert a.bonus_trade_amount == 1.0

    def test_cutoff_min_rise_ratio_sets_is_cutoff_passed_false(self):
        """min_rise_ratio 미만 업종 is_cutoff_passed=False, 2차 가산점=0 (rank는 모든 업종에 부여)."""
        scores = [
            _make_sector_score("통과", rise_ratio=0.8, stocks=[_make_stock("p1", "통과", 2.0)]),
            _make_sector_score("탈락", rise_ratio=0.2, stocks=[_make_stock("f1", "탈락", -1.0)]),
        ]
        calculate_bonus_scores(scores, min_rise_ratio=0.5)
        passed = next(s for s in scores if s.sector == "통과")
        failed = next(s for s in scores if s.sector == "탈락")
        assert passed.is_cutoff_passed is True
        assert failed.is_cutoff_passed is False
        assert failed.bonus_relative_strength == 0.0

    def test_second_bonus_weighted_rank_sum(self):
        """2차 가산점: 가중 순위 합 (Weighted Rank Sum).
        통과 업종 2개: 반도체(종목 +3, +1), 은행(종목 +2, -1)
        탈락 업종 1개: 자동차(종목 +10, -5) — 모집단에서 제외
        모집단 4종목: [3, 1, 2, -1] 상승률 내림차순 정렬
        순위: 3(1위), 2(2위), 1(3위), -1(4위)
        가중치 = (4 - 순위 + 1) / 4: 3→1.0, 2→0.75, 1→0.5, -1→0.25
        반도체 합 = 1.0 + 0.5 = 1.5
        은행 합 = 0.75 + 0.25 = 1.0
        업종 간 순위: 반도체(1.5)=1위, 은행(1.0)=2위
        만점 = 전체 업종 수 = 3 → tiered: 반도체=3.0(1위), 은행=2.0(2위)
        """
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
        # 자동차는 탈락 → is_cutoff_passed=False, 2차=0 (rank는 모든 업종에 부여)
        assert auto.is_cutoff_passed is False
        assert auto.bonus_relative_strength == 0.0
        # 만점 = 전체 업종 수 = 3 (슬라이더 기본값 0)
        # 반도체 가중 합 1.5 = 1위 → tiered = 3.0
        # 은행 가중 합 1.0 = 2위 → tiered = 2.0
        assert semi.bonus_relative_strength == 3.0
        assert bank.bonus_relative_strength == 2.0

    def test_final_score_is_sum_of_three_bonuses_float(self):
        """final_score = 1차 + 2차 + 3차 (float 합, int 변환 없음)."""
        sc = _make_sector_score(
            "반도체", rise_ratio=0.8, avg_trade_amount=1_000_000,
            stocks=[_make_stock("s1", "반도체", 2.5)],
        )
        calculate_bonus_scores([sc])
        expected = sc.bonus_rise_ratio + sc.bonus_relative_strength + sc.bonus_trade_amount
        assert sc.final_score == expected

    def test_final_score_range_with_slider(self):
        """슬라이더 적용 시 final_score 범위: 0 ~ 조정 만점 합.
        업종 2개, 슬라이더 전부 0 → 만점 = 2, 조정 만점 합 = 6.
        """
        scores = [
            _make_sector_score("A", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", rise_ratio=0.7, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 2.0)]),
        ]
        calculate_bonus_scores(scores)
        for sc in scores:
            assert 0.0 <= sc.final_score <= 6.0  # 만점 2 × 3차수 = 6

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
        """final_score 동점 시 2차 가산점 → 업종명 순 타이브레이크.
        가중 순위 합에서 동일한 가중 합을 갖도록 종목 분포 설계:
        A: [3.0, 0.0] → 모집단 순위 1(3.0), 4(0.0) → 가중치 1.0 + 0.25 = 1.25
        Z: [2.0, 1.0] → 모집단 순위 2(2.0), 3(1.0) → 가중치 0.75 + 0.5 = 1.25
        → 2차 가산점 동점, 1차/3차도 동점 → final_score 동점 → 업종명 알파벳순
        """
        scores = [
            _make_sector_score("Z", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("z1", "Z", 2.0), _make_stock("z2", "Z", 1.0)]),
            _make_sector_score("A", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("a1", "A", 3.0), _make_stock("a2", "A", 0.0)]),
        ]
        calculate_bonus_scores(scores)
        assert scores[0].sector == "A"
        assert scores[1].sector == "Z"
        assert scores[0].final_score == scores[1].final_score

    def test_rank_assignment_sequential_for_all_sectors(self):
        """모든 업종에 1, 2, 3... 순차 rank 부여 (컷오프 미달 포함, is_cutoff_passed로 구분)."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
            _make_sector_score("C", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("c1", "C", 1.0)]),
        ]
        calculate_bonus_scores(scores)
        ranks = [s.rank for s in scores]
        assert ranks == list(range(1, len(scores) + 1))

    def test_no_passed_sectors_all_second_bonus_zero(self):
        """모든 업종 컷오프 탈락 → 2차 가산점 전부 0, is_cutoff_passed=False (rank는 부여됨)."""
        scores = [
            _make_sector_score("A", rise_ratio=0.1, stocks=[_make_stock("a1", "A", 1.0)]),
            _make_sector_score("B", rise_ratio=0.2, stocks=[_make_stock("b1", "B", 2.0)]),
        ]
        calculate_bonus_scores(scores, min_rise_ratio=0.5)
        for sc in scores:
            assert sc.is_cutoff_passed is False
            assert sc.bonus_relative_strength == 0.0
        # 모든 업종에 순위 부여 (1, 2)
        ranks = [s.rank for s in scores]
        assert ranks == [1, 2]

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
            assert sc.is_cutoff_passed is True
            assert sc.rank > 0
        # 모든 업종 순차 rank
        ranks = [s.rank for s in scores]
        assert ranks == list(range(1, len(scores) + 1))

    # ── 슬라이더 테스트 ──

    def test_slider_negative_50_halves_max_score(self):
        """슬라이더 -50% → 조정 만점 = 업종 수 × 0.5.
        업종 4개, 슬라이더 -50% → 1차 조정 만점 = 2.0
        1위=2.0, 2위=1.0, 3위=0.0, 4위=0.0
        """
        scores = [
            _make_sector_score("A", rise_ratio=0.1, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
            _make_sector_score("C", rise_ratio=0.5, avg_trade_amount=500,
                               stocks=[_make_stock("c1", "C", 1.0)]),
            _make_sector_score("D", rise_ratio=0.3, avg_trade_amount=300,
                               stocks=[_make_stock("d1", "D", 0.0)]),
        ]
        calculate_bonus_scores(scores, rise_ratio_slider=-50, trade_amount_slider=-50, relative_strength_slider=-50)
        b = next(s for s in scores if s.sector == "B")
        # B는 rise_ratio 1위 → 조정 만점 2.0
        assert b.bonus_rise_ratio == 2.0

    def test_slider_negative_100_disables_dimension(self):
        """슬라이더 -100% → 조정 만점 = 0 → 해당 가산점 무효화 (P20 폴백 아님)."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
        ]
        calculate_bonus_scores(
            scores,
            rise_ratio_slider=-100,
            relative_strength_slider=-100,
            trade_amount_slider=-100,
        )
        for sc in scores:
            assert sc.bonus_rise_ratio == 0.0
            assert sc.bonus_relative_strength == 0.0
            assert sc.bonus_trade_amount == 0.0
            assert sc.final_score == 0.0

    def test_slider_positive_50_increases_max_score(self):
        """슬라이더 +50% → 조정 만점 = 업종 수 × 1.5.
        업종 2개, 1차 슬라이더 +50% → 조정 만점 = 3.0
        1위=3.0, 2위=2.0
        """
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
        ]
        calculate_bonus_scores(scores, rise_ratio_slider=50)
        b = next(s for s in scores if s.sector == "B")
        a = next(s for s in scores if s.sector == "A")
        # B rise_ratio 1위 → 3.0, A 2위 → 2.0
        assert b.bonus_rise_ratio == 3.0
        assert a.bonus_rise_ratio == 2.0

    def test_slider_only_rise_ratio_negative_100(self):
        """1차 슬라이더만 -100% → 1차=0, 2차/3차 정상."""
        scores = [
            _make_sector_score("A", rise_ratio=0.3, avg_trade_amount=100,
                               stocks=[_make_stock("a1", "A", 0.5)]),
            _make_sector_score("B", rise_ratio=0.9, avg_trade_amount=900,
                               stocks=[_make_stock("b1", "B", 3.0)]),
        ]
        calculate_bonus_scores(scores, rise_ratio_slider=-100)
        for sc in scores:
            assert sc.bonus_rise_ratio == 0.0
            # 2차/3차는 정상 (만점 = 업종 수 = 2)
            assert sc.bonus_trade_amount > 0.0
        # final_score = 0 + 2차 + 3차
        for sc in scores:
            assert sc.final_score == sc.bonus_relative_strength + sc.bonus_trade_amount

    # ── 가중 순위 합 알고리즘 상세 테스트 ──

    def test_weighted_rank_sum_top_concentration(self):
        """상위 집중도 반영: 1개 1위 + 9개 꼴찌 업종 vs 균등 업종.
        업종 X: 종목 [10.0, -5.0, -5.0, -5.0, -5.0, -5.0, -5.0, -5.0, -5.0, -5.0] (1위 1개, 나머지 꼴찌)
        업종 Y: 종목 [9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0] (균등 분포)
        모집단 20종목, 상승률 내림차순:
        10(X), 9(Y), 8(Y), 7(Y), 6(Y), 5(Y), 4(Y), 3(Y), 2(Y), 1(Y), 0(Y), -5(X×9)
        순위: 10→1, 9→2, 8→3, ..., 0→11, -5→12~20 (동점 9개)
        가중치 = (20 - 순위 + 1) / 20
        X: 10(순위1)=1.0 + -5×9(순위12, 동점그룹 최고순위)=9×(20-12+1)/20=9×0.45=4.05 → 합 5.05
        Y: 9(순위2)=0.95 + 8(순위3)=0.9 + ... + 0(순위11)=0.5 → 합 = 0.95+0.9+0.85+0.8+0.75+0.7+0.65+0.6+0.55+0.5 = 7.25
        Y가 더 높음 → 균등 분포가 상위 집중도 더 높음 (가중 순위 합이 평균의 문제 해결 확인)
        """
        x_stocks = [_make_stock("x0", "X", 10.0)] + [_make_stock(f"x{i}", "X", -5.0) for i in range(1, 10)]
        y_stocks = [_make_stock(f"y{i}", "Y", float(9 - i)) for i in range(10)]
        scores = [
            _make_sector_score("X", rise_ratio=0.5, avg_trade_amount=500, stocks=x_stocks),
            _make_sector_score("Y", rise_ratio=0.5, avg_trade_amount=500, stocks=y_stocks),
        ]
        calculate_bonus_scores(scores)
        x = next(s for s in scores if s.sector == "X")
        y = next(s for s in scores if s.sector == "Y")
        # Y의 가중 합(7.25) > X의 가중 합(5.05) → Y가 1위
        assert y.bonus_relative_strength > x.bonus_relative_strength

    def test_passed_sector_no_stocks_second_bonus_zero(self):
        """통과 업종에 종목이 없으면 2차 가산점 = 0."""
        scores = [
            _make_sector_score("A", rise_ratio=0.8, avg_trade_amount=500, stocks=[]),
            _make_sector_score("B", rise_ratio=0.6, avg_trade_amount=300, stocks=[]),
        ]
        calculate_bonus_scores(scores, min_rise_ratio=0.5)
        for sc in scores:
            assert sc.is_cutoff_passed is True
            assert sc.bonus_relative_strength == 0.0
