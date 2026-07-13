# -*- coding: utf-8 -*-
"""
업종 점수 계산 - 3단계 누적 가산점 시스템.

1차 가산점: 업종 내 상승 종목 비율 순위 (0~100)
2차 가산점: 통과 업종 종목들 상대평가 백분위 평균 (0~100)
3차 가산점: 업종 거래대금 순위 (0~100)
종합 점수 = 1차 + 2차 + 3차 (0~300)
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
        score = round((rank - 1) / (n - 1) * 100.0, 1)
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
) -> None:
    """
    3단계 누적 가산점 계산 — 옵션 C 2패스 방식.

    1패스:
      1. 1차 가산점: 업종 간 상승비율 순위 → rank_to_score (0~100)
      2. 3차 가산점: 업종 간 거래대금 순위 → rank_to_score (0~100)
      3. 임시 합산(1차+3차) 기반 정렬

    컷오프:
      4. min_rise_ratio 미만 업종 rank=0 (컷오프)

    2패스:
      5. 2차 가산점: 통과 업종(rank>0) 종목들만 모집단 → 백분위 점수 → 업종별 평균 (0~100)

    종합:
      6. final_score = 1차 + 2차 + 3차 (0~300)
      7. final_score 내림차순 재정렬, 동점 시 2차→1차→업종명 타이브레이크
      8. rank 부여 (1-based, 컷오프 미달 업종은 rank=0)
    """
    if not sector_scores:
        return

    # ── 1패스: 1차 + 3차 가산점 ──
    # 1차 가산점: 업종 간 상승비율 순위
    rise_values = [sc.rise_ratio for sc in sector_scores]
    rise_scores = rank_to_score(rise_values, higher_is_better=True)
    for sc, score in zip(sector_scores, rise_scores):
        sc.bonus_rise_ratio = score

    # 3차 가산점: 업종 간 평균 거래대금 순위
    ta_values = [float(sc.avg_trade_amount) for sc in sector_scores]
    ta_scores = rank_to_score(ta_values, higher_is_better=True)
    for sc, score in zip(sector_scores, ta_scores):
        sc.bonus_trade_amount = score

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

        for sc in sector_scores:
            if sc.rank > 0 and sc.sector in sector_scores_sum:
                cnt = sector_scores_cnt[sc.sector]
                sc.bonus_relative_strength = round(sector_scores_sum[sc.sector] / cnt, 1) if cnt > 0 else 0.0
            else:
                sc.bonus_relative_strength = 0.0
    else:
        # 통과 업종 없음 → 모든 업종 2차 가산점 = 0
        for sc in sector_scores:
            sc.bonus_relative_strength = 0.0

    # ── 종합 점수: 1차 + 2차 + 3차 (0~300) ──
    for sc in sector_scores:
        sc.final_score = round(
            sc.bonus_rise_ratio + sc.bonus_relative_strength + sc.bonus_trade_amount,
            1,
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
