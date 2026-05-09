# -*- coding: utf-8 -*-
"""
sector_custom.json 기반 종목 → 업종 매핑 모듈.

sector_custom.json의 stock_moves / sectors / deleted_sectors 3개 필드만으로
최종 업종을 결정한다. Auto_Mapping(eligible_stocks_cache.json) 의존성 없음.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


# ── Merged (sector_custom.json 전용) API ──────────────────────────────


def get_merged_sector(stock_code: str) -> str:
    """sector_custom.json 기반 종목 → 최종 업종명.

    1. stock_moves[stock_code] 존재 → 해당 값
    2. 없으면 → 빈 문자열
    3. sectors 리네임 1회 적용
    4. deleted_sectors 필터 → 빈 문자열 반환
    """
    from app.core.sector_custom_data import load_custom_data_readonly

    custom = load_custom_data_readonly()

    # 1) stock_moves 조회, 없으면 빈 문자열
    sector = custom.stock_moves.get(stock_code, "")

    # 2) sectors 리네임 1회 적용 (덮어쓰기 방식, 체인 없음)
    sector = custom.sectors.get(sector, sector)

    # 3) deleted_sectors 필터
    if sector in custom.deleted_sectors:
        return "업종명없음"

    return sector or "업종명없음"


def get_merged_all_sectors() -> list[str]:
    """sector_custom.json 기반 전체 업종 목록 (정렬).

    sectors values + stock_moves values → 고유 수집
    → deleted_sectors 제거 → 빈 문자열 제거 → 정렬
    """
    from app.core.sector_custom_data import load_custom_data_readonly

    custom = load_custom_data_readonly()

    # sectors values + stock_moves values에서 고유 업종명 수집
    result: set[str] = set(custom.sectors.values())
    result.update(custom.stock_moves.values())

    # deleted_sectors 제거
    result -= set(custom.deleted_sectors)

    # 빈 문자열 제거
    result.discard("")

    return sorted(result)
