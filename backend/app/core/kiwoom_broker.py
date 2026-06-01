from __future__ import annotations
# -*- coding: utf-8 -*-
"""
키움증권 브로커 구현체 (KiwoomBroker)

BrokerRouter 위임 패턴:
  - KiwoomBroker는 BrokerInterface 구현체로 하위 호환성 유지
  - 실제 기능은 BrokerRouter의 Provider들에 위임
  - 단일 소스 진리: BrokerRouter가 유일한 진입점
"""

import asyncio
import logging
from backend.app.core.trade_mode import is_test_mode
from typing import Optional

from backend.app.core.broker_interface import BrokerInterface

_log = logging.getLogger(__name__)


class KiwoomBroker(BrokerInterface):
    """키움증권 REST + WebSocket 브로커 (BrokerRouter 위임 패턴)"""

    def __init__(self):
        from backend.app.core.broker_router import BrokerRouter
        self._router = BrokerRouter()

    # ── 인증 ──────────────────────────────────────────────────────────────
    async def get_access_token(self) -> Optional[str]:
        """[au10001] WebSocket 로그인용 토큰 -- BrokerRouter.auth 위임."""
        return await self._router.auth.get_access_token()

    async def ensure_token(self) -> bool:
        """토큰 유효성 확인, 만료 시 자동 갱신 -- BrokerRouter.auth 위임."""
        return await self._router.auth.ensure_token()

    # ── 계좌 조회 ─────────────────────────────────────────────────────────
    async def get_account_number(self) -> Optional[str]:
        """계좌번호 조회 -- BrokerRouter.account 위임."""
        return await self._router.account.get_account_number()

    async def get_deposit_detail(self, acnt_no: str = "") -> Optional[dict]:
        """예수금 상세 조회 -- BrokerRouter.account 위임."""
        return await self._router.account.get_deposit_detail(acnt_no)

    async def get_balance_detail(self, qry_tp: str = "1", dmst_stex_tp: str = "KRX") -> Optional[dict]:
        """계좌평가잔고내역 조회 -- BrokerRouter.account 위임."""
        return await self._router.account.get_balance_detail(qry_tp, dmst_stex_tp)

    async def get_account_balance(self, acnt_no: str = "") -> dict:
        """
        [공통 표준] 계좌 잔고 통합 조회 -- BrokerRouter.account 위임.
        """
        return await self._router.account.get_account_balance(acnt_no)

    # ── 주문 ──────────────────────────────────────────────────────────────
    async def send_order(
        self,
        settings: dict,
        access_token: str,
        order_type: str,
        code: str,
        qty: int,
        price: int = 0,
        trde_tp: str = "3",
        orig_ord_no: str = "",
    ) -> dict:
        """주문 실행 -- BrokerRouter.order 위임."""
        return await self._router.order.send_order(
            settings, access_token, order_type, code, qty,
            price=price, trde_tp=trde_tp, orig_ord_no=orig_ord_no,
        )

    # ── WebSocket ─────────────────────────────────────────────────────────
    def get_ws_uri(self) -> str:
        """WebSocket 접속 URI -- BrokerRouter.websocket 위임."""
        return self._router.websocket.get_ws_uri()

    # ── 메타 ──────────────────────────────────────────────────────────────
    @property
    def broker_name(self) -> str:
        """증권사 식별자."""
        return "kiwoom"
