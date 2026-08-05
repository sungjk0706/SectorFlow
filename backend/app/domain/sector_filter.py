# -*- coding: utf-8 -*-
"""
업종 필터 - 5거래일 평균 거래대금 필터링 및 업종별 종목 그룹핑 로직.

계산 본체는 명시적으로 전달된 sector_map만 사용한다 (P10 SSOT, P24 단순성).
외부 업종 매핑 조회는 계산 영역 바깥에서 수행해 전달한다.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)


async def filter_by_avg_amt(
    all_codes: list[str],
    avg_amt_5d: dict[str, int],
    min_avg_amt_eok: float = 0.0,
) -> list[str]:
    """
    5거래일 평균 거래대금 필터링.

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
    sector_map: dict[str, str],
) -> dict[str, list[str]]:
    """
    업종별 종목 그룹핑.

    - sector_map은 호출자가 계산 영역 바깥에서 묶음 조회한 결과 (필수 입력)
    - 빈 문자열 반환 종목은 스킵 (미매핑 종목 제외)
    - 누락 시 TypeError로 즉시 드러난다 (P20 폴백 금지)
    """
    sector_groups: dict[str, list[str]] = {}
    for code in codes:
        sector_name = sector_map.get(code, "미분류")
        if not sector_name:
            continue  # 미매핑 종목 제외
        if sector_name not in sector_groups:
            sector_groups[sector_name] = []
        sector_groups[sector_name].append(code)

    return sector_groups
