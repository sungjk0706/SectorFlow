"""sector_score.py 단위 테스트 — 정규화 및 가중치 점수 계산 로직 검증."""
from __future__ import annotations

import pytest

from backend.app.domain.models import SectorScore
from backend.app.domain.sector_score import (
    normalize_metric_value,
    normalize_weight_values,
    calculate_weighted_scores,
)


# ── normalize_metric_value ──────────────────────────────────────────────────────

class TestNormalizeMetricValue:
    def test_empty_list_returns_empty(self):
        assert normalize_metric_value([]) == []

    def test_single_value_returns_100(self):
        assert normalize_metric_value([42.0]) == [100.0]

    def test_all_same_values_returns_100(self):
        assert normalize_metric_value([5.0, 5.0, 5.0]) == [100.0, 100.0, 100.0]

    def test_min_max_normalization_higher_is_better(self):
        result = normalize_metric_value([10.0, 20.0, 30.0], higher_is_better=True)
        assert result == [0.0, 50.0, 100.0]

    def test_min_max_normalization_lower_is_better(self):
        result = normalize_metric_value([10.0, 20.0, 30.0], higher_is_better=False)
        assert result == [100.0, 50.0, 0.0]

    def test_rounding_to_one_decimal(self):
        result = normalize_metric_value([0.0, 3.0, 7.0])
        assert result == [0.0, 42.9, 100.0]


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

    def test_tiebreak_by_rise_ratio_then_sector_name(self):
        scores = [
            self._make_sector_score("Z", scored_trade_amount=500, scored_rise_ratio=0.5),
            self._make_sector_score("A", scored_trade_amount=500, scored_rise_ratio=0.5),
        ]
        calculate_weighted_scores(scores)
        assert scores[0].sector == "A"
        assert scores[1].sector == "Z"
        assert scores[0].final_score == scores[1].final_score

    def test_custom_weights_affect_ranking(self):
        scores = [
            self._make_sector_score("A", scored_trade_amount=100, scored_rise_ratio=0.9),
            self._make_sector_score("B", scored_trade_amount=900, scored_rise_ratio=0.1),
        ]
        calculate_weighted_scores(scores, weights={"total_trade_amount": 1.0, "rise_ratio": 0.0})
        assert scores[0].sector == "B"
        calculate_weighted_scores(scores, weights={"total_trade_amount": 0.0, "rise_ratio": 1.0})
        assert scores[0].sector == "A"
