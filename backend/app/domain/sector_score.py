# -*- coding: utf-8 -*-
"""
업종 점수 계산 - 순위 기반 점수 및 가중치 계산 로직.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)


def rank_to_score(
    values: list[float],
    higher_is_better: bool = True,
) -> list[float]:
    """
    원시값 리스트를 순위 기반 점수(0~100)로 변환.

    - 값이 클수록 좋으면: 큰 값이 1위 → 100점
    - 동점 처리: 같은 값은 같은 순위, 다음 순위는 건너뜀 (표준 순위)
    - 순위 점수 = (N - rank + 1) / N × 100
    - N=1이면 100점, 빈 리스트면 빈 리스트
    - 소수점 첫째 자리 반올림
    """
    if not values:
        return []
    n = len(values)
    if n == 1:
        return [100.0]

    # 값과 원래 인덱스 페어 생성 후 정렬
    indexed = list(enumerate(values))
    indexed.sort(key=lambda x: x[1], reverse=higher_is_better)

    # 동점 그룹별 순위 부여 (같은 값 = 같은 순위, 다음 순위 건너뜀)
    scores = [0.0] * n
    rank = 1
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        score = round((n - rank + 1) / n * 100.0, 1)
        for k in range(i, j):
            orig_idx = indexed[k][0]
            scores[orig_idx] = score
        rank += (j - i)
        i = j

    return scores


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
    각 SectorScore에 순위 점수 + 가중치 최종 점수를 계산하여 in-place 설정.

    1. 가중치 정규화 (합 = 1.0)
    2. 각 지표별 원시값 추출 → 순위 점수 변환 (rank_to_score)
    3. final_score = Σ(rank_score_i × weight_i)
    4. final_score 내림차순 정렬, 동점 시 상승비율 원시값 → 거래대금 원시값 → 업종명 타이브레이크
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

    # 2. 각 지표별 원시값 추출 → 순위 점수 변환 → metric_scores 저장
    for metric in metrics:
        raw_values = [metric.extract(sc) for sc in sector_scores]
        rank_scores = rank_to_score(raw_values, metric.higher_is_better)
        for sc, rank_val in zip(sector_scores, rank_scores):
            sc.metric_scores[metric.key] = rank_val

    # 3. final_score 계산
    for sc in sector_scores:
        sc.final_score = round(
            sum(sc.metric_scores.get(m.key, 0.0) * norm_w.get(m.key, 0.0) for m in metrics),
            1,
        )

    # 4. 정렬: final_score 내림차순, 동점 시 scored_rise_ratio 내림차순,
    #         동점 시 scored_trade_amount 내림차순, 최종 동점 시 업종명 오름차순(결정적 정렬)
    sector_scores.sort(
        key=lambda s: (
            -s.final_score,
            -s.scored_rise_ratio,
            -s.scored_trade_amount,
            s.sector,
        ),
    )

    # 5. rank 부여 (1-based)
    for i, sc in enumerate(sector_scores):
        sc.rank = i + 1
