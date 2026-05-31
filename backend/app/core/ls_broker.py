from __future__ import annotations
# -*- coding: utf-8 -*-
"""
LS증권 브로커 구현체 (LsBroker)

구조:
  - BrokerRouter: 기능별 Provider 매핑 중앙 라우터
  - LsBroker (이 파일): BrokerInterface로 캡슐화, BrokerRouter 위임
"""

import logging

from backend.app.core.broker_interface import BrokerInterface
from backend.app.core.broker_router import BrokerRouter

_log = logging.getLogger(__name__)


class LsBroker(BrokerInterface):
    """LS증권 브로커 (BrokerRouter 위임 패턴)"""

    def __init__(self, settings: dict):
        self._settings = settings
        self._router = BrokerRouter(settings)

    # ── 인증 ──────────────────────────────────────────────────────────────
    def get_access_token(self) -> str | None:
        """OAuth2 액세스 토큰 반환"""
        return self._router.auth.get_access_token()

    def ensure_token(self) -> bool:
        """토큰 유효성 확인, 만료 시 자동 갱신"""
        return self._router.auth.ensure_token()

    # ── 계좌 조회 ─────────────────────────────────────────────────────────
    def get_account_number(self) -> str | None:
        return self._router.account.get_account_number()

    def get_deposit_detail(self, acnt_no: str = "") -> dict | None:
        """예수금 상세 조회"""
        return self._router.account.get_deposit_detail(acnt_no)

    def get_balance_detail(self, qry_tp: str = "1", dmst_stex_tp: str = "KRX") -> dict | None:
        """계좌평가잔고내역 조회"""
        return self._router.account.get_balance_detail(qry_tp, dmst_stex_tp)

    def get_account_balance(self, acnt_no: str = "") -> dict:
        """계좌 잔고 통합 조회"""
        return self._router.account.get_account_balance(acnt_no)

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

    # ── WebSocket ─────────────────────────────────────────────────────────
    def get_ws_uri(self) -> str:
        """WebSocket URI"""
        return self._router.websocket.get_ws_uri()

    # ── 메타 ──────────────────────────────────────────────────────────────
    @property
    def broker_name(self) -> str:
        return "ls"
