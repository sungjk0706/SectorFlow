# -*- coding: utf-8 -*-
"""
섹터 관리 모듈
- 섹터 점수 관리
- 섹터 종목 관리
- 섹터 요약 재계산
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SectorManager:
    """섹터 관리자"""

    def __init__(self):
        self._sector_scores = {}  # 섹터 점수
        self._sector_stocks = {}  # 섹터 종목
        self._sector_summary = {}  # 섹터 요약
        self._buy_targets = []  # 매수 대상

    def get_sector_scores(self) -> dict:
        """섹터 점수 조회"""
        return dict(self._sector_scores)

    def update_sector_scores(self, scores: dict) -> None:
        """섹터 점수 업데이트"""
        self._sector_scores = scores
        logger.info("[섹터] 섹터 점수 업데이트")

    def get_sector_stocks(self) -> dict:
        """섹터 종목 조회"""
        return dict(self._sector_stocks)

    def update_sector_stocks(self, stocks: dict) -> None:
        """섹터 종목 업데이트"""
        self._sector_stocks = stocks
        logger.info("[섹터] 섹터 종목 업데이트")

    def get_sector_summary(self) -> dict:
        """섹터 요약 조회"""
        return dict(self._sector_summary)

    def update_sector_summary(self, summary: dict) -> None:
        """섹터 요약 업데이트"""
        self._sector_summary = summary
        logger.info("[섹터] 섹터 요약 업데이트")

    def get_buy_targets(self) -> list:
        """매수 대상 조회"""
        return list(self._buy_targets)

    def update_buy_targets(self, targets: list) -> None:
        """매수 대상 업데이트"""
        self._buy_targets = targets
        logger.info(f"[섹터] 매수 대상 업데이트: {len(targets)}개")

    def recompute_sector_summary(self) -> None:
        """섹터 요약 재계산"""
        # 섹터 점수와 종목 정보를 기반으로 요약 재계산
        # 실제 구현은 engine_service.py의 로직 참조
        logger.info("[섹터] 섹터 요약 재계산")

    def get_sector_score_for_stock(self, stock_code: str) -> Optional[float]:
        """종목의 섹터 점수 조회"""
        for sector, stocks in self._sector_stocks.items():
            if stock_code in stocks:
                return self._sector_scores.get(sector)
        return None

    def clear_sector_data(self) -> None:
        """섹터 데이터 초기화"""
        self._sector_scores.clear()
        self._sector_stocks.clear()
        self._sector_summary.clear()
        self._buy_targets.clear()
        logger.info("[섹터] 섹터 데이터 초기화")
