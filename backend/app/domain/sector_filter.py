# -*- coding: utf-8 -*-
"""
업종 필터 - 5일평균거래대금 필터링 및 업종별 종목 그룹핑 로직.
"""
from __future__ import annotations
from backend.app.core import sector_mapping
import logging
logger = logging.getLogger(__name__)


async def filter_by_avg_amt(
    all_codes: list[str],
    avg_amt_5d: dict[str, int],
    min_avg_amt_eok: float = 0.0,
) -> list[str]:
    """
    5일평균거래대금 필터링.

    - avg_amt_5d는 백만원 단위
    - min_avg_amt_eok는 억 단위
    - 필터링 후 코드 리스트 반환
    """
    if min_avg_amt_eok <= 0:
        return all_codes.copy()

    filtered_codes = []
    for code in all_codes:
        # 단일 소스 진리: avg_5d_trade_amount는 백만원 단위, 필터링 시 억 단위 변환
        avg5d_million = int(avg_amt_5d.get(code, 0) or 0)
        avg5d_eok = avg5d_million // 100  # 백만원 → 억단위 변환
        if avg5d_eok >= min_avg_amt_eok:
            filtered_codes.append(code)

    return filtered_codes


async def group_by_sector(
    codes: list[str],
) -> dict[str, list[str]]:
    """
    업종별 종목 그룹핑.

    - sector_mapping.get_merged_sectors_batch()로 종목코드 → 커스텀 업종 일괄 매핑
    - 빈 문자열 반환 종목은 스킵 (미매핑 종목 제외)
    """
    sectors_map = await sector_mapping.get_merged_sectors_batch(codes)

    sector_groups: dict[str, list[str]] = {}
    for code in codes:
        sector_name = sectors_map.get(code, "미분류")
        if not sector_name:
            continue  # 미매핑 종목 제외
        if sector_name not in sector_groups:
            sector_groups[sector_name] = []
        sector_groups[sector_name].append(code)

    return sector_groups
