# -*- coding: utf-8 -*-
"""
업종 점수 계산 - 3단계 누적 가산점 시스템 (순위별 차등 점수).

1차 가산점: 업종 내 상승 종목 비율 순위 → tiered 점수 (0~만점)
2차 가산점: 통과 업종 종목들 상대평가 백분위 평균 순위 → tiered 점수 (0~만점)
3차 가산점: 업종 거래대금 순위 → tiered 점수 (0~만점)
종합 점수 = 1차 + 2차 + 3차 (0~만점 합)

tiered 점수: 1위 = 만점, 2위 = 만점-1, ..., 만점 순위 = 1, 그 아래 = 0
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)


def rank_to_tiered_score(
    values: list[float],
    max_score: int = 10,
    higher_is_better: bool = True,
) -> list[int]:
    """
    원시값 리스트를 순위별 차등 점수로 변환.

    - 1위 = max_score, 2위 = max_score - 1, ..., max_score 순위 = 1, 그 아래 = 0
    - 동점 처리: 같은 값은 같은 순위, 다음 순위 건너뜀 (표준 순위)
    - 빈 리스트면 빈 리스트, N=1이면 [max_score]
    - 정수 반환 (소수점 없음)
    """
    if not values:
        return []
    n = len(values)
    if n == 1:
        return [max_score]

    indexed = list(enumerate(values))
    indexed.sort(key=lambda x: x[1], reverse=higher_is_better)

    scores = [0] * n
    rank = 1
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        score = max(0, max_score - rank + 1)
        for k in range(i, j):
            orig_idx = indexed[k][0]
            scores[orig_idx] = score
        rank += (j - i)
        i = j

    return scores


def percentile_to_score(
    values: list[float],
    higher_is_better: bool = True,
) -> list[float]:
    """
    원시값 리스트를 백분위 점수(0~100)로 변환.

    - 가장 큰 값 = 100, 가장 작은 값 = 0 (완전 0~100 스케일)
    - 동점 처리: 같은 값은 같은 점수
    - 빈 리스트면 빈 리스트, N=1이면 100점
    - 공식: (rank - 1) / (N - 1) × 100 (동점 시 그룹 내 최고 점수)
    """
    if not values:
        return []
    n = len(values)
    if n == 1:
        return [100.0]

    indexed = list(enumerate(values))
    indexed.sort(key=lambda x: x[1], reverse=higher_is_better)

    scores = [0.0] * n
    rank = 1
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        # 동점 그룹에 동일한 점수 부여 (그룹 내 최고 순위 기준)
        # 공식: (n - rank) / (n - 1) × 100 — rank=1(최대값)이 100점, rank=n(최소값)이 0점
        score = round((n - rank) / (n - 1) * 100.0, 1)
        for k in range(i, j):
            orig_idx = indexed[k][0]
            scores[orig_idx] = score
        rank += (j - i)
        i = j

    return scores


def calculate_bonus_scores(
    sector_scores: list,  # list[SectorScore]
    *,
    min_rise_ratio: float = 0.0,
    max_rise_ratio_score: int = 10,
    max_relative_strength_score: int = 7,
    max_trade_amount_score: int = 5,
) -> None:
    """
    3단계 누적 가산점 계산 — 옵션 C 2패스 방식 (순위별 차등 점수).

    1패스:
      1. 1차 가산점: 업종 간 상승비율 순위 → rank_to_tiered_score (0~max_rise_ratio_score)
      2. 3차 가산점: 업종 간 거래대금 순위 → rank_to_tiered_score (0~max_trade_amount_score)
      3. 임시 합산(1차+3차) 기반 정렬

    컷오프:
      4. min_rise_ratio 미만 업종 rank=0 (컷오프) — 기존 로직 유지

    2패스:
      5. 2차 가산점: 통과 업종(rank>0) 종목들만 모집단 → 백분위 점수 → 업종별 평균
         → 업종 간 순위 → rank_to_tiered_score (0~max_relative_strength_score)

    종합:
      6. final_score = 1차 + 2차 + 3차 (0~만점 합)
      7. final_score 내림차순 재정렬, 동점 시 2차→1차→업종명 타이브레이크
      8. rank 부여 (1-based, 컷오프 미달 업종은 rank=0)
    """
    if not sector_scores:
        return

    # ── 1패스: 1차 + 3차 가산점 (순위별 차등 점수) ──
    # 1차 가산점: 업종 간 상승비율 순위
    rise_values = [sc.rise_ratio for sc in sector_scores]
    rise_scores = rank_to_tiered_score(rise_values, max_score=max_rise_ratio_score, higher_is_better=True)
    for sc, score in zip(sector_scores, rise_scores):
        sc.bonus_rise_ratio = float(score)

    # 3차 가산점: 업종 간 평균 거래대금 순위
    ta_values = [float(sc.avg_trade_amount) for sc in sector_scores]
    ta_scores = rank_to_tiered_score(ta_values, max_score=max_trade_amount_score, higher_is_better=True)
    for sc, score in zip(sector_scores, ta_scores):
        sc.bonus_trade_amount = float(score)

    # 임시 합산(1차+3차) 기반 정렬 — 컷오프 전 순서 확정
    sector_scores.sort(
        key=lambda s: (
            -(s.bonus_rise_ratio + s.bonus_trade_amount),
            -s.bonus_rise_ratio,
            -s.bonus_trade_amount,
            s.sector,
        ),
    )

    # ── 컷오프: min_rise_ratio 미만 업종 rank=0 ──
    if min_rise_ratio > 0:
        for sc in sector_scores:
            if sc.rise_ratio < min_rise_ratio:
                sc.rank = 0
            else:
                sc.rank = 1  # 임시 — 최종 rank는 종합 점수 정렬 후 부여
    else:
        for sc in sector_scores:
            sc.rank = 1  # 임시 — 컷오프 없으면 전부 통과

    # ── 2패스: 2차 가산점 — 통과 업종(rank>0) 종목들만 모집단 ──
    passed_sectors = [sc for sc in sector_scores if sc.rank > 0]

    if passed_sectors:
        # 통과 업종의 모든 종목을 하나의 모집단으로 수집
        all_changes: list[float] = []
        stock_to_sector: list[str] = []  # 각 종목이 속한 업종명
        for sc in passed_sectors:
            for stock in sc.stocks:
                all_changes.append(stock.change_rate)
                stock_to_sector.append(sc.sector)

        # 모집단 백분위 점수 계산
        percentile_scores = percentile_to_score(all_changes, higher_is_better=True)

        # 업종별 백분위 점수 평균
        sector_scores_sum: dict[str, float] = {}
        sector_scores_cnt: dict[str, int] = {}
        for sector_name, pct_score in zip(stock_to_sector, percentile_scores):
            sector_scores_sum[sector_name] = sector_scores_sum.get(sector_name, 0.0) + pct_score
            sector_scores_cnt[sector_name] = sector_scores_cnt.get(sector_name, 0) + 1

        # 업종별 평균 백분위 계산
        sector_avg_pct: dict[str, float] = {}
        for sector_name in sector_scores_sum:
            cnt = sector_scores_cnt[sector_name]
            sector_avg_pct[sector_name] = round(sector_scores_sum[sector_name] / cnt, 1) if cnt > 0 else 0.0

        # 통과 업종 간 평균 백분위 순위 → tiered 점수 부여
        passed_sector_names = [sc.sector for sc in passed_sectors]
        passed_avg_values = [sector_avg_pct.get(name, 0.0) for name in passed_sector_names]
        relative_scores = rank_to_tiered_score(
            passed_avg_values, max_score=max_relative_strength_score, higher_is_better=True
        )

        # tiered 점수를 각 업종에 할당
        for sc, tiered_score in zip(passed_sectors, relative_scores):
            sc.bonus_relative_strength = float(tiered_score)

        # 미통과 업종(rank=0) 2차 가산점 = 0
        for sc in sector_scores:
            if sc.rank == 0:
                sc.bonus_relative_strength = 0.0
    else:
        # 통과 업종 없음 → 모든 업종 2차 가산점 = 0
        for sc in sector_scores:
            sc.bonus_relative_strength = 0.0

    # ── 종합 점수: 1차 + 2차 + 3차 ──
    for sc in sector_scores:
        sc.final_score = float(
            int(sc.bonus_rise_ratio) + int(sc.bonus_relative_strength) + int(sc.bonus_trade_amount)
        )

    # ── 종합 점수 기반 재정렬 ──
    sector_scores.sort(
        key=lambda s: (
            -s.final_score,
            -s.bonus_relative_strength,
            -s.bonus_rise_ratio,
            s.sector,
        ),
    )

    # ── rank 부여 (1-based, 컷오프 미달 업종은 rank=0) ──
    current_rank = 0
    for sc in sector_scores:
        if sc.rank == 0:
            continue  # 컷오프 미달 — rank=0 유지
        current_rank += 1
        sc.rank = current_rank
