# -*- coding: utf-8 -*-
"""
LS증권 브로커 구현체 (LsBroker)

구조:
  - LsRestAPI (ls_rest.py): OAuth2 토큰 관리, REST API 호출, 주문 실행
  - LsBroker (이 파일): BrokerInterface로 캡슐화
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.app.core.broker_interface import BrokerInterface
from backend.app.core.ls_rest import LsRestAPI

_log = logging.getLogger(__name__)


class LsBroker(BrokerInterface):
    """LS증권 REST 브로커"""

    def __init__(self, settings: dict):
        self._settings = settings

        app_key = (settings.get("ls_app_key") or "").strip()
        app_secret = (settings.get("ls_app_secret") or "").strip()
        account_no = str(settings.get("ls_account_no", "") or "")

        self._rest_api = LsRestAPI(app_key, app_secret)
        self._acnt_no = account_no

    # ── 인증 ──────────────────────────────────────────────────────────────
    def get_access_token(self) -> Optional[str]:
        """OAuth2 액세스 토큰 반환"""
        return self._rest_api.get_token()

    def ensure_token(self) -> bool:
        """토큰 유효성 확인, 만료 시 자동 갱신"""
        # 비동기 메서드이므로 동기 컨텍스트에서는 False 반환
        # 실제 사용 시 async context에서 호출 필요
        return False

    # ── 계좌 조회 ─────────────────────────────────────────────────────────
    def get_account_number(self) -> Optional[str]:
        return self._acnt_no

    def get_deposit_detail(self, acnt_no: str = "") -> Optional[dict]:
        """예수금 상세 조회 - LS증권 미구현"""
        _log.warning("[LS증권] 예수금 조회 미구현")
        return None

    def get_balance_detail(self, qry_tp: str = "1", dmst_stex_tp: str = "KRX") -> Optional[dict]:
        """계좌평가잔고내역 조회 - LS증권 미구현"""
        _log.warning("[LS증권] 잔고 조회 미구현")
        return None

    def get_account_balance(self, acnt_no: str = "") -> dict:
        """
        [공통 표준] 계좌 잔고 통합 조회 - LS증권 미구현

        추후 LS증권 API 추가 시 구현 필요
        """
        _log.warning("[LS증권] 계좌 잔고 조회 미구현")
        return {
            "success": False,
            "summary": {
                "tot_eval": 0,
                "tot_pnl": 0,
                "tot_buy": 0,
                "deposit": 0,
                "orderable": 0,
                "withdrawable": 0,
                "total_rate": 0.0,
            },
            "stock_list": [],
            "raw_data": {},
        }

    # ── 주문 ──────────────────────────────────────────────────────────────
    def send_order(
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
        """
        주문 전송 - LS증권

        LS증권은 비동기 API이므로 현재는 동기 인터페이스만 제공
        실제 주문 실행은 async context에서 LsRestAPI 직접 호출 필요
        """
        _log.warning("[LS증권] 동기 주문 인터페이스 미구현 - async LsRestAPI 사용 필요")
        return {"success": False, "error": "async interface required"}

    async def send_order_async(
        self,
        stock_code: str,
        quantity: int,
        price: float,
        order_type: str = "00",  # 00:지정가
        side: str = "BUY",  # BUY or SELL
        member_code: str = "NXT",
    ) -> Optional[dict]:
        """
        비동기 주문 전송 (LS증권 전용)

        Args:
            stock_code: 종목코드 (A+종목코드 형식)
            quantity: 주문수량
            price: 주문가
            order_type: 호가유형코드 (00:지정가, 03:시장가)
            side: 매수/매도 (BUY/SELL)
            member_code: 회원사번호 (KRX, NXT)

        Returns:
            주문 결과
        """
        if side.upper() == "BUY":
            return await self._rest_api.buy_order(
                stock_code=stock_code,
                quantity=quantity,
                price=price,
                order_type=order_type,
                member_code=member_code,
            )
        else:  # SELL
            return await self._rest_api.sell_order(
                stock_code=stock_code,
                quantity=quantity,
                price=price,
                order_type=order_type,
                member_code=member_code,
            )

    # ── WebSocket ─────────────────────────────────────────────────────────
    def get_ws_uri(self) -> str:
        """WebSocket URI - LS증권 미구현"""
        _log.warning("[LS증권] WebSocket URI 미구현")
        return ""

    # ── 메타 ──────────────────────────────────────────────────────────────
    @property
    def broker_name(self) -> str:
        return "ls"
