from __future__ import annotations
# -*- coding: utf-8 -*-
"""
섹터 점수 계산 - 정규화 및 가중치 계산 로직.
"""

from typing import Literal

from backend.app.core.logger import get_logger

logger = get_logger("engine")


def normalize_metric_value(
    values: list[float],
    higher_is_better: bool = True,
) -> list[float]:
    """
    원시값 리스트를 0~100 min-max 정규화 점수로 변환.

    - min-max 선형 보간: score = (v - min) / (max - min) * 100
    - 모든 값이 동일하면 100 반환
    - 1개 업종이면 100 반환
    - higher_is_better=False 이면 역방향: score = (max - v) / (max - min) * 100
    - 소수점 첫째 자리 반올림
    """
    if not values:
        return []
    if len(values) == 1:
        return [100.0]

    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [100.0] * len(values)
    span = hi - lo
    if higher_is_better:
        return [round((v - lo) / span * 100.0, 1) for v in values]
    return [round((hi - v) / span * 100.0, 1) for v in values]


def normalize_weight_values(
    weights: dict[str, float],
    metrics: list | None = None,  # list[MetricDef]
) -> dict[str, float]:
    """
    가중치 합이 1.0이 되도록 정규화.

    - 등록되지 않은 키는 무시
    - 음수 값은 0으로 클램프
    - 합이 0이면 기본 가중치 사용
    """
    if metrics is None:
        from backend.app.domain.models import DEFAULT_METRICS
        metrics = DEFAULT_METRICS
    # 등록된 키만 필터 + 음수 클램프
    clamped: dict[str, float] = {}
    for m in metrics:
        raw = weights.get(m.key, 0.0)
        clamped[m.key] = max(raw, 0.0)
    total = sum(clamped.values())
    if total == 0.0:
        # 폴백: 기본 가중치 사용
        return {m.key: m.default_weight for m in metrics}
    return {k: v / total for k, v in clamped.items()}


def calculate_weighted_scores(
    sector_scores: list,  # list[SectorScore]
    metrics: list | None = None,  # list[MetricDef]
    weights: dict[str, float] | None = None,
) -> None:
    """
    각 SectorScore에 정규화 점수 + 가중치 최종 점수를 계산하여 in-place 설정.

    1. 가중치 정규화 (합 = 1.0)
    2. 각 지표별 원시값 추출 → normalize_metric
    3. final_score = Σ(normalized_i × weight_i)
    4. final_score 내림차순 정렬, 동점 시 rise_ratio 정규화 점수로 타이브레이크
    5. rank 부여 (1-based)
    """
    if not sector_scores:
        return

    if metrics is None:
        from backend.app.domain.models import DEFAULT_METRICS
        metrics = DEFAULT_METRICS
    if weights is None:
        weights = {m.key: m.default_weight for m in metrics}

    # 1. 가중치 정규화
    norm_w = normalize_weight_values(weights, metrics)

    # 2. 각 지표별 원시값 추출 → 정규화 → metric_scores 저장
    for metric in metrics:
        raw_values = [metric.extract(sc) for sc in sector_scores]
        normalized = normalize_metric_value(raw_values, metric.higher_is_better)
        for sc, norm_val in zip(sector_scores, normalized):
            sc.metric_scores[metric.key] = norm_val

    # 3. final_score 계산
    for sc in sector_scores:
        sc.final_score = round(
            sum(sc.metric_scores.get(m.key, 0.0) * norm_w.get(m.key, 0.0) for m in metrics),
            1,
        )

    # 4. 정렬: final_score 내림차순, 동점 시 rise_ratio 내림차순, 최종 동점 시 업종명 오름차순(결정적 정렬)
    sector_scores.sort(
        key=lambda s: (-s.final_score, -s.metric_scores.get("rise_ratio", 0.0), s.sector),
    )

    # 5. rank 부여 (1-based)
    for i, sc in enumerate(sector_scores):
        sc.rank = i + 1
