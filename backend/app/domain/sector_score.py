# -*- coding: utf-8 -*-
"""
업종 점수 계산 - 3단계 누적 가산점 시스템 (순위별 차등 점수, 만점 자동화).

1차 가산점: 업종 간 상승비율 순위 → tiered 점수 (0~조정 만점)
2차 가산점: 통과 업종 종목들 가중 순위 합(Weighted Rank Sum) → 업종 간 순위 → tiered 점수 (0~조정 만점)
3차 가산점: 업종 간 거래대금 순위 → tiered 점수 (0~조정 만점)
종합 점수 = 1차 + 2차 + 3차 (0~조정 만점 합, float)

만점 = 업종 수 × (1 + 슬라이더/100) — 업종 수에서 자동 도출 (P10 SSOT).
슬라이더 -100% → 조정 만점 0 → 해당 가산점 무효화 (사용자 의도적, P20 폴백 아님).
tiered 점수: 1위 = 조정 만점, 2위 = 조정 만점 - 1, ..., 조정 만점 순위 = 1, 그 아래 = 0.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)


def rank_to_tiered_score(
    values: list[float],
    max_score: float = 10.0,
    higher_is_better: bool = True,
) -> list[float]:
    """
    원시값 리스트를 순위별 차등 점수로 변환 (float 반환).

    - 1위 = max_score, 2위 = max_score - 1, ..., max_score 순위 = 1, 그 아래 = 0
    - 동점 처리: 같은 값은 같은 순위, 다음 순위 건너뜀 (표준 순위)
    - 빈 리스트면 빈 리스트, N=1이면 [max_score]
    - 소수점 점수 허용 (슬라이더 비율 적용 시 조정 만점이 소수 가능)
    """
    if not values:
        return []
    n = len(values)
    if n == 1:
        return [float(max_score)]

    indexed = list(enumerate(values))
    indexed.sort(key=lambda x: x[1], reverse=higher_is_better)

    scores: list[float] = [0.0] * n
    rank = 1
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        score = max(0.0, max_score - (rank - 1))
        for k in range(i, j):
            orig_idx = indexed[k][0]
            scores[orig_idx] = float(score)
        rank += (j - i)
        i = j

    return scores


def calculate_bonus_scores(
    sector_scores: list,  # list[SectorScore]
    *,
    min_rise_ratio: float = 0.0,
    # ── 슬라이더 (-100~+100, 기본값 0) — 조정 만점 = 업종 수 × (1 + slider/100) ──
    rise_ratio_slider: int = 0,
    relative_strength_slider: int = 0,
    trade_amount_slider: int = 0,
) -> None:
    """
    3단계 누적 가산점 계산 — 만점 자동화 + 슬라이더 + 가중 순위 합.

    만점 = len(sector_scores) × (1 + slider/100)
      - slider=0 → 만점 = 업종 수 (기본)
      - slider=-50 → 만점 = 업종 수 × 0.5
      - slider=-100 → 만점 = 0 (해당 가산점 무효화)

    1패스:
      1. 1차 가산점: 업종 간 상승비율 순위 → rank_to_tiered_score (0~조정 만점)
      2. 3차 가산점: 업종 간 거래대금 순위 → rank_to_tiered_score (0~조정 만점)
      3. 임시 합산(1차+3차) 기반 정렬

    컷오프:
      4. min_rise_ratio 미만 업종 is_cutoff_passed=False, rank=0 (임시 호환)

    2패스:
      5. 2차 가산점: 통과 업종(is_cutoff_passed) 종목들 가중 순위 합
         - 모든 종목 상승률 내림차순 정렬 → 순위 1..N
         - 가중치 = (N - 순위 + 1) / N
         - 업종별 가중치 합산 → 업종 간 순위 → rank_to_tiered_score (0~조정 만점)

    종합:
      6. final_score = 1차 + 2차 + 3차 (float)
      7. final_score 내림차순 재정렬, 동점 시 2차→1차→업종명 타이브레이크
      8. rank 부여 — 통과 업종 1, 2, 3..., 미달 업종 rank=0 유지 (임시 호환)
    """
    if not sector_scores:
        return

    n_sectors = len(sector_scores)

    # ── 조정 만점 계산: 업종 수 × (1 + 슬라이더/100) ──
    adjusted_rise_max = n_sectors * (1.0 + rise_ratio_slider / 100.0)
    adjusted_relative_max = n_sectors * (1.0 + relative_strength_slider / 100.0)
    adjusted_trade_max = n_sectors * (1.0 + trade_amount_slider / 100.0)

    # ── 1패스: 1차 + 3차 가산점 (순위별 차등 점수) ──
    # 1차 가산점: 업종 간 상승비율 순위
    rise_values = [sc.rise_ratio for sc in sector_scores]
    rise_scores = rank_to_tiered_score(rise_values, max_score=adjusted_rise_max, higher_is_better=True)
    for sc, score in zip(sector_scores, rise_scores):
        sc.bonus_rise_ratio = float(score)

    # 3차 가산점: 업종 간 평균 거래대금 순위
    ta_values = [float(sc.avg_trade_amount) for sc in sector_scores]
    ta_scores = rank_to_tiered_score(ta_values, max_score=adjusted_trade_max, higher_is_better=True)
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

    # ── 컷오프: min_rise_ratio 미만 업종 is_cutoff_passed=False, rank=0 ──
    for sc in sector_scores:
        if min_rise_ratio > 0 and sc.rise_ratio < min_rise_ratio:
            sc.is_cutoff_passed = False
            sc.rank = 0  # 임시 호환 — Step 2에서 rank 정상 부여로 전환
        else:
            sc.is_cutoff_passed = True
            sc.rank = 1  # 임시 — 최종 rank는 종합 점수 정렬 후 부여

    # ── 2패스: 2차 가산점 — 통과 업종(is_cutoff_passed) 종목들 가중 순위 합 ──
    passed_sectors = [sc for sc in sector_scores if sc.is_cutoff_passed]

    if passed_sectors and adjusted_relative_max > 0:
        # 통과 업종의 모든 종목을 하나의 모집단으로 수집
        all_entries: list[tuple[float, str]] = []  # (change_rate, sector_name)
        for sc in passed_sectors:
            for stock in sc.stocks:
                all_entries.append((stock.change_rate, sc.sector))

        if all_entries:
            n_stocks = len(all_entries)
            # 상승률 내림차순 정렬 → 순위 1, 2, ..., N
            all_entries.sort(key=lambda x: x[0], reverse=True)

            # 각 종목의 가중치 = (N - 순위 + 1) / N
            # 업종별 가중치 합산
            sector_weight_sum: dict[str, float] = {}
            for rank_pos, (change_rate, sector_name) in enumerate(all_entries, start=1):
                weight = (n_stocks - rank_pos + 1) / n_stocks
                sector_weight_sum[sector_name] = sector_weight_sum.get(sector_name, 0.0) + weight

            # 통과 업종 간 가중 합 순위 → tiered 점수 부여
            passed_sector_names = [sc.sector for sc in passed_sectors]
            passed_weight_values = [sector_weight_sum.get(name, 0.0) for name in passed_sector_names]
            relative_scores = rank_to_tiered_score(
                passed_weight_values, max_score=adjusted_relative_max, higher_is_better=True
            )

            # tiered 점수를 각 업종에 할당
            for sc, tiered_score in zip(passed_sectors, relative_scores):
                sc.bonus_relative_strength = float(tiered_score)
        else:
            # 통과 업종에 종목이 없음 → 2차 가산점 = 0
            for sc in passed_sectors:
                sc.bonus_relative_strength = 0.0

        # 미통과 업종 2차 가산점 = 0
        for sc in sector_scores:
            if not sc.is_cutoff_passed:
                sc.bonus_relative_strength = 0.0
    else:
        # 통과 업종 없음 또는 조정 만점 0 → 모든 업종 2차 가산점 = 0
        for sc in sector_scores:
            sc.bonus_relative_strength = 0.0

    # ── 종합 점수: 1차 + 2차 + 3차 (float) ──
    for sc in sector_scores:
        sc.final_score = (
            sc.bonus_rise_ratio + sc.bonus_relative_strength + sc.bonus_trade_amount
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

    # ── rank 부여 (임시 호환: 통과 업종 1, 2, 3..., 미달 업종 rank=0 유지) ──
    current_rank = 0
    for sc in sector_scores:
        if not sc.is_cutoff_passed:
            continue  # 컷오프 미달 — rank=0 유지
        current_rank += 1
        sc.rank = current_rank
