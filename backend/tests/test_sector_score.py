"""sector_score.py 단위 테스트 — 순위 기반 점수 및 가중치 점수 계산 로직 검증."""
from __future__ import annotations

import pytest

from backend.app.domain.models import SectorScore
from backend.app.domain.sector_score import (
    rank_to_score,
    normalize_weight_values,
    calculate_weighted_scores,
)


# ── rank_to_score ──────────────────────────────────────────────────────────────

class TestRankToScore:
    def test_empty_list_returns_empty(self):
        assert rank_to_score([]) == []

    def test_single_value_returns_100(self):
        assert rank_to_score([42.0]) == [100.0]

    def test_all_same_values_returns_100(self):
        """모든 값이 동일하면 공동 1위 → 모두 100점."""
        assert rank_to_score([5.0, 5.0, 5.0]) == [100.0, 100.0, 100.0]

    def test_rank_score_formula_5_values(self):
        """5개 업종: 1위=100, 2위=80, 3위=60, 4위=40, 5위=20."""
        values = [30.0, 10.0, 50.0, 20.0, 40.0]  # 50=1위, 40=2위, 30=3위, 20=4위, 10=5위
        result = rank_to_score(values, higher_is_better=True)
        assert result == [60.0, 20.0, 100.0, 40.0, 80.0]

    def test_higher_is_better_false(self):
        """lower_is_better: 작은 값이 1위."""
        values = [10.0, 20.0, 30.0]  # 10=1위, 20=2위, 30=3위
        result = rank_to_score(values, higher_is_better=False)
        assert result == [100.0, 66.7, 33.3]

    def test_tie_values_same_rank_same_score(self):
        """동점: 같은 값은 같은 순위, 다음 순위 건너뜀."""
        # A=50(1위), B=50(1위), C=30(3위), D=20(4위)
        values = [50.0, 50.0, 30.0, 20.0]
        result = rank_to_score(values, higher_is_better=True)
        # 1위: (4-1+1)/4*100 = 100, 3위: (4-3+1)/4*100 = 50, 4위: (4-4+1)/4*100 = 25
        assert result == [100.0, 100.0, 50.0, 25.0]

    def test_rounding_to_one_decimal(self):
        """소수점 첫째 자리 반올림 (3개 업종: 100, 66.7, 33.3)."""
        values = [3.0, 1.0, 2.0]
        result = rank_to_score(values, higher_is_better=True)
        assert result == [100.0, 33.3, 66.7]


# ── normalize_weight_values ─────────────────────────────────────────────────────

class TestNormalizeWeightValues:
    def test_already_normalized(self):
        weights = {"total_trade_amount": 0.5, "rise_ratio": 0.5}
        result = normalize_weight_values(weights)
        assert result["total_trade_amount"] == pytest.approx(0.5)
        assert result["rise_ratio"] == pytest.approx(0.5)

    def test_unnormalized_weights(self):
        weights = {"total_trade_amount": 3.0, "rise_ratio": 1.0}
        result = normalize_weight_values(weights)
        assert result["total_trade_amount"] == pytest.approx(0.75)
        assert result["rise_ratio"] == pytest.approx(0.25)

    def test_negative_values_clamped_to_zero(self):
        weights = {"total_trade_amount": -1.0, "rise_ratio": 1.0}
        result = normalize_weight_values(weights)
        assert result["total_trade_amount"] == pytest.approx(0.0)
        assert result["rise_ratio"] == pytest.approx(1.0)

    def test_all_zero_returns_default_weights(self):
        weights = {"total_trade_amount": 0.0, "rise_ratio": 0.0}
        result = normalize_weight_values(weights)
        assert result["total_trade_amount"] == pytest.approx(0.5)
        assert result["rise_ratio"] == pytest.approx(0.5)

    def test_unknown_keys_ignored(self):
        weights = {"total_trade_amount": 0.5, "rise_ratio": 0.5, "unknown_key": 99.0}
        result = normalize_weight_values(weights)
        assert "unknown_key" not in result
        assert len(result) == 2

    def test_default_settings_weights_normalize_to_half_half(self):
        """DEFAULT_USER_SETTINGS의 sector_weights가 정규화 후 50/50이 되는지 검증.
        레거시 trade_amount 키 사용 시 거래대금 가중치가 0이 되는 회귀 방지."""
        from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS
        sw = DEFAULT_USER_SETTINGS["sector_weights"]
        norm = normalize_weight_values(sw)
        assert norm["total_trade_amount"] == pytest.approx(0.5)
        assert norm["rise_ratio"] == pytest.approx(0.5)


# ── calculate_weighted_scores ───────────────────────────────────────────────────

class TestCalculateWeightedScores:
    def _make_sector_score(
        self,
        sector: str,
        scored_trade_amount: int = 0,
        scored_rise_ratio: float = 0.0,
    ) -> SectorScore:
        return SectorScore(
            sector=sector,
            total=10,
            rise_count=5,
            rise_ratio=0.5,
            avg_change_rate=1.0,
            total_trade_amount=scored_trade_amount,
            avg_ratio_5d_pct=0.0,
            scored_trade_amount=scored_trade_amount,
            scored_rise_ratio=scored_rise_ratio,
        )

    def test_empty_list_no_error(self):
        calculate_weighted_scores([])

    def test_single_sector_gets_rank_1(self):
        scores = [self._make_sector_score("반도체", scored_trade_amount=1000, scored_rise_ratio=0.8)]
        calculate_weighted_scores(scores)
        assert scores[0].rank == 1
        assert scores[0].final_score == 100.0

    def test_ranking_by_final_score_descending(self):
        scores = [
            self._make_sector_score("A", scored_trade_amount=100, scored_rise_ratio=0.3),
            self._make_sector_score("B", scored_trade_amount=900, scored_rise_ratio=0.7),
            self._make_sector_score("C", scored_trade_amount=500, scored_rise_ratio=0.5),
        ]
        calculate_weighted_scores(scores)
        assert scores[0].rank == 1
        assert scores[1].rank == 2
        assert scores[2].rank == 3
        assert scores[0].final_score >= scores[1].final_score >= scores[2].final_score

    def test_metric_scores_populated(self):
        scores = [
            self._make_sector_score("A", scored_trade_amount=100, scored_rise_ratio=0.3),
            self._make_sector_score("B", scored_trade_amount=900, scored_rise_ratio=0.7),
        ]
        calculate_weighted_scores(scores)
        for sc in scores:
            assert "total_trade_amount" in sc.metric_scores
            assert "rise_ratio" in sc.metric_scores

    def test_rank_score_values_correct(self):
        """3개 업종 순위 점수 검증: 1위=100, 2위=66.7, 3위=33.3."""
        scores = [
            self._make_sector_score("A", scored_trade_amount=100, scored_rise_ratio=0.3),
            self._make_sector_score("B", scored_trade_amount=900, scored_rise_ratio=0.7),
            self._make_sector_score("C", scored_trade_amount=500, scored_rise_ratio=0.5),
        ]
        calculate_weighted_scores(scores)
        # 거래대금 순위: B(900)=1위=100, C(500)=2위=66.7, A(100)=3위=33.3
        # 상승비율 순위: B(0.7)=1위=100, C(0.5)=2위=66.7, A(0.3)=3위=33.3
        # 가중치 50:50 → B: 100, C: 66.7, A: 33.3
        b = next(s for s in scores if s.sector == "B")
        c = next(s for s in scores if s.sector == "C")
        a = next(s for s in scores if s.sector == "A")
        assert b.final_score == 100.0
        assert c.final_score == 66.7
        assert a.final_score == 33.3

    def test_tiebreak_by_rise_ratio_then_sector_name(self):
        """final_score 동점 시 scored_rise_ratio 원시값 → 업종명 순으로 타이브레이크."""
        scores = [
            self._make_sector_score("Z", scored_trade_amount=500, scored_rise_ratio=0.5),
            self._make_sector_score("A", scored_trade_amount=500, scored_rise_ratio=0.5),
        ]
        calculate_weighted_scores(scores)
        assert scores[0].sector == "A"
        assert scores[1].sector == "Z"
        assert scores[0].final_score == scores[1].final_score

    def test_tiebreak_by_rise_ratio_raw_value(self):
        """final_score 동점 + 거래대금 동점 시, 상승비율 원시값이 높은 업종이 먼저."""
        scores = [
            self._make_sector_score("A", scored_trade_amount=500, scored_rise_ratio=0.3),
            self._make_sector_score("B", scored_trade_amount=500, scored_rise_ratio=0.7),
        ]
        calculate_weighted_scores(scores)
        # 거래대금 동점 → 순위 점수 동일 → final_score 동일
        # 타이브레이크: scored_rise_ratio 높은 B가 먼저
        assert scores[0].sector == "B"
        assert scores[1].sector == "A"

    def test_tiebreak_by_trade_amount_raw_value(self):
        """final_score 동점 + 상승비율 동점 시, 거래대금 원시값이 높은 업종이 먼저."""
        scores = [
            self._make_sector_score("A", scored_trade_amount=300, scored_rise_ratio=0.5),
            self._make_sector_score("B", scored_trade_amount=700, scored_rise_ratio=0.5),
        ]
        calculate_weighted_scores(scores)
        # 상승비율 동점 → 순위 점수 동일, 거래대금 순위 점수 다름 → final_score 다름
        # B가 거래대금 1위이므로 final_score 더 높음
        assert scores[0].sector == "B"
        assert scores[0].final_score > scores[1].final_score

    def test_custom_weights_affect_ranking(self):
        scores = [
            self._make_sector_score("A", scored_trade_amount=100, scored_rise_ratio=0.9),
            self._make_sector_score("B", scored_trade_amount=900, scored_rise_ratio=0.1),
        ]
        # 거래대금 100% → B가 1위 (거래대금 순위 1위 = 100점)
        calculate_weighted_scores(scores, weights={"total_trade_amount": 1.0, "rise_ratio": 0.0})
        assert scores[0].sector == "B"
        # 상승비율 100% → A가 1위 (상승비율 순위 1위 = 100점)
        calculate_weighted_scores(scores, weights={"total_trade_amount": 0.0, "rise_ratio": 1.0})
        assert scores[0].sector == "A"

    def test_tied_sectors_same_final_score(self):
        """동점 순위: 같은 원시값을 가진 업종들은 같은 final_score를 받음."""
        scores = [
            self._make_sector_score("A", scored_trade_amount=500, scored_rise_ratio=0.5),
            self._make_sector_score("B", scored_trade_amount=500, scored_rise_ratio=0.5),
            self._make_sector_score("C", scored_trade_amount=100, scored_rise_ratio=0.1),
        ]
        calculate_weighted_scores(scores)
        a = next(s for s in scores if s.sector == "A")
        b = next(s for s in scores if s.sector == "B")
        assert a.final_score == b.final_score
        # A, B 모두 1위(순위 점수 100), C는 3위(순위 점수 33.3)
        assert a.final_score == 100.0
        c = next(s for s in scores if s.sector == "C")
        assert c.final_score == 33.3
