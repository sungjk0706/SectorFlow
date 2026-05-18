# -*- coding: utf-8 -*-
"""
캐시 관리 모듈
- LRU 캐시 관리
- 종목 상세 정보 캐시
- 체결가/거래대금 캐시
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)


class LRUCache(dict):
    """최대 크기를 가진 LRU(Least Recently Used) 캐시"""

    def __init__(self, maxsize: int = 1000, *args, **kwargs):
        self._maxsize = maxsize
        self._order: OrderedDict = OrderedDict()
        super().__init__(*args, **kwargs)
        # 초기 데이터가 있으면 순서에 추가
        for key in self:
            self._order[key] = None

    def __getitem__(self, key):
        value = super().__getitem__(key)
        # 접근 시 순서 갱신
        self._order.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self._order.move_to_end(key)
        else:
            self._order[key] = None
            # 크기 초과 시 가장 오래된 항목 삭제
            if len(self._order) > self._maxsize:
                oldest = next(iter(self._order))
                del self._order[oldest]
                super().__delitem__(oldest)
        super().__setitem__(key, value)

    def __delitem__(self, key):
        if key in self._order:
            del self._order[key]
        super().__delitem__(key)

    def clear(self):
        self._order.clear()
        super().clear()


class CacheManager:
    """캐시 관리자"""

    def __init__(self):
        # 종목 상세 정보 캐시 (최대 3000종목)
        self._pending_stock_details = LRUCache(maxsize=3000)

        # 실시간 체결가/거래대금 캐시 (최대 2500종목)
        self._latest_trade_prices = LRUCache(maxsize=2500)
        self._latest_trade_amounts = LRUCache(maxsize=2500)

        # 체결 강도 캐시 (최대 2500종목)
        self._latest_strength = LRUCache(maxsize=2500)

        # 5일 전고점 캐시
        self._high_5d_cache = {}

        # 5일 평균 거래대금 캐시
        self._avg_amt_5d = {}

    def get_pending_stock_details(self, stock_code: str) -> Optional[dict]:
        """종목 상세 정보 조회"""
        return self._pending_stock_details.get(stock_code)

    def set_pending_stock_details(self, stock_code: str, details: dict) -> None:
        """종목 상세 정보 저장"""
        self._pending_stock_details[stock_code] = details

    def get_latest_trade_price(self, stock_code: str) -> Optional[int]:
        """최근 체결가 조회"""
        return self._latest_trade_prices.get(stock_code)

    def set_latest_trade_price(self, stock_code: str, price: int) -> None:
        """최근 체결가 저장"""
        self._latest_trade_prices[stock_code] = price

    def get_latest_trade_amount(self, stock_code: str) -> Optional[int]:
        """최근 거래대금 조회"""
        return self._latest_trade_amounts.get(stock_code)

    def set_latest_trade_amount(self, stock_code: str, amount: int) -> None:
        """최근 거래대금 저장"""
        self._latest_trade_amounts[stock_code] = amount

    def get_latest_strength(self, stock_code: str) -> Optional[float]:
        """최근 체결 강도 조회"""
        return self._latest_strength.get(stock_code)

    def set_latest_strength(self, stock_code: str, strength: float) -> None:
        """최근 체결 강도 저장"""
        self._latest_strength[stock_code] = strength

    def get_high_5d(self, stock_code: str) -> Optional[int]:
        """5일 전고점 조회"""
        return self._high_5d_cache.get(stock_code)

    def set_high_5d(self, stock_code: str, high: int) -> None:
        """5일 전고점 저장"""
        self._high_5d_cache[stock_code] = high

    def get_avg_amt_5d(self, stock_code: str) -> Optional[int]:
        """5일 평균 거래대금 조회"""
        return self._avg_amt_5d.get(stock_code)

    def set_avg_amt_5d(self, stock_code: str, avg_amt: int) -> None:
        """5일 평균 거래대금 저장"""
        self._avg_amt_5d[stock_code] = avg_amt

    def clear_all_caches(self) -> None:
        """전체 캐시 초기화"""
        self._pending_stock_details.clear()
        self._latest_trade_prices.clear()
        self._latest_trade_amounts.clear()
        self._latest_strength.clear()
        self._high_5d_cache.clear()
        self._avg_amt_5d.clear()
        logger.info("[캐시] 전체 캐시 초기화")
