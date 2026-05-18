# -*- coding: utf-8 -*-
"""
계좌 관리 모듈
- 계좌 정보 조회
- 잔고 업데이트
- 예수금 관리
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AccountManager:
    """계좌 관리자"""

    def __init__(self):
        self._account_snapshot = {}  # 계좌 스냅샷
        self._deposit = 0  # 예수금
        self._withdrawable_deposit = 0  # 출금 가능 예수금

    def get_account_snapshot(self) -> dict:
        """계좌 스냅샷 조회"""
        return dict(self._account_snapshot)

    def update_account_snapshot(self, snapshot: dict) -> None:
        """계좌 스냅샷 업데이트"""
        self._account_snapshot = snapshot
        logger.info("[계좌] 계좌 스냅샷 업데이트")

    def get_deposit(self) -> int:
        """예수금 조회"""
        return self._deposit

    def update_deposit(self, deposit: int, withdrawable: int) -> None:
        """예수금 업데이트"""
        self._deposit = deposit
        self._withdrawable_deposit = withdrawable
        logger.info(f"[계좌] 예수금 업데이트: {deposit}원 (출금 가능: {withdrawable}원)")

    def get_withdrawable_deposit(self) -> int:
        """출금 가능 예수금 조회"""
        return self._withdrawable_deposit

    def get_total_buy_amount(self) -> int:
        """총 매입 금액 조회"""
        return self._account_snapshot.get("total_buy_amount", 0)

    def get_total_eval_amount(self) -> int:
        """총 평가 금액 조회"""
        return self._account_snapshot.get("total_eval_amount", 0)

    def get_total_pnl(self) -> int:
        """총 손익 조회"""
        return self._account_snapshot.get("total_pnl", 0)

    def get_total_pnl_rate(self) -> float:
        """총 손익률 조회"""
        return self._account_snapshot.get("total_pnl_rate", 0.0)

    def clear_account_data(self) -> None:
        """계좌 데이터 초기화"""
        self._account_snapshot.clear()
        self._deposit = 0
        self._withdrawable_deposit = 0
        logger.info("[계좌] 계좌 데이터 초기화")
