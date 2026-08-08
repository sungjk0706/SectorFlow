# -*- coding: utf-8 -*-
"""
LS증권 Provider 구현체
"""
from __future__ import annotations
import logging
from backend.app.core.broker_providers import (
    AccountProvider, AuthProvider, OrderProvider, WebSocketProvider
)
from backend.app.core.ls_rest import LsRestAPI
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES

logger = logging.getLogger(__name__)

_BROKER_DISPLAY = BROKER_DISPLAY_NAMES["ls"]

# ── Auth Provider ─────────────────────────────────────────────────────
class LsAuthProvider(AuthProvider):
    def __init__(self):
        from backend.app.services.engine_state import state
        _existing = state.broker_rest_apis.get("ls")
        if _existing is None:
            app_key = (state.integrated_system_settings_cache.get("ls_app_key") or "").strip()
            app_secret = (state.integrated_system_settings_cache.get("ls_app_secret") or "").strip()
            _existing = LsRestAPI(app_key, app_secret)
            state.broker_rest_apis["ls"] = _existing
        self._rest_api = _existing

    async def get_access_token(self) -> str | None:
        # 토큰 갱신 시도
        ok = await self._rest_api.ensure_token()
        if ok:
            return self._rest_api.get_token()
        return None

    async def ensure_token(self) -> bool:
        return await self._rest_api.ensure_token()

    @property
    def broker_name(self) -> str:
        return "ls"

    @property
    def rest_api(self) -> LsRestAPI:
        return self._rest_api


# ── Order Provider ────────────────────────────────────────────────────
class LsOrderProvider(OrderProvider):
    def __init__(self, auth_provider: AuthProvider):
        self._rest_api = getattr(auth_provider, "rest_api", None)

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
        # LS증권은 추상 인터페이스와 다른 파라미터 구조를 가짐
        # 내부적으로 LS API 파라미터로 변환하여 호출
        if not self._rest_api:
            return {"success": False, "error": "LS Rest API Not initialized"}

        hoga_gb = trde_tp  # 호가구분 매핑

        if order_type == 'buy':
            res = await self._rest_api.buy_order(
                stock_code=f"A{code}",
                quantity=qty,
                price=float(price),
                order_type=hoga_gb
            )
        elif order_type == 'sell':
            res = await self._rest_api.sell_order(
                stock_code=f"A{code}",
                quantity=qty,
                price=float(price),
                order_type=hoga_gb
            )
        else:
            return {"success": False, "error": f"Unsupported order_type: {order_type}"}

        if res and res.get("rsp_cd") in ("00040", "00000"):
            # 주문 성공
            # LS증권 CSPAT00601OutBlock2에서 주문번호(OrdNo) 반환
            block2 = res.get("CSPAT00601OutBlock2", {})
            order_no = str(block2.get("OrdNo", ""))
            return {
                "success": True,
                "order_no": order_no,
                "raw_res": res
            }
        
        err_msg = res.get("rsp_msg") if res else "Network Error"
        return {"success": False, "error": err_msg, "raw_res": res}


# ── WebSocket Provider ────────────────────────────────────────────────
class LsWebSocketProvider(WebSocketProvider):
    def __init__(self, auth_provider: AuthProvider):
        pass


# ── Account Provider ────────────────────────────────────────────────────────
class LsAccountProvider(AccountProvider):
    """LS증권 계좌 데이터 파싱 — 최소 인터페이스 구현.

    LS 실전 체결·잔고 응답 구조가 확정되지 않은 메서드는 NotImplementedError로 두고
    G-2(LS 실전 체결·잔고 구현) 보완 갭에서 완성한다.
    LS는 소켓 연결 시 계좌 등록을 수행하므로 실시간 계좌 파싱은 LS 실시간 메시지
    형식에 맞춰 G-2에서 구현 예정.
    """

    def __init__(self, auth_provider: AuthProvider | None = None):
        # AccountProvider는 순수 파싱 위임이므로 auth_provider 불필요.
        # _create_provider가 auth_provider 주입 패턴으로 호출하므로 시그니처만 맞춤.
        pass

    @property
    def broker_name(self) -> str:
        return "ls"

    def parse_deposit(self, raw: dict) -> tuple:
        # LS 실전 예수금 조회 응답 구조 확정 후 G-2에서 구현.
        raise NotImplementedError("LS 예수금 파싱은 G-2(LS 실전 체결·잔고 구현)에서 완성 예정")

    def parse_balance(self, raw: dict, deposit) -> tuple:
        # LS 실전 잔고 조회 응답 구조 확정 후 G-2에서 구현.
        raise NotImplementedError("LS 잔고 파싱은 G-2(LS 실전 체결·잔고 구현)에서 완성 예정")

    def is_realtime_stock_item(self, item: dict) -> bool:
        # LS 실시간 메시지 형식 확정 후 G-2에서 구현.
        raise NotImplementedError("LS 실시간 종목 판별은 G-2(LS 실전 체결·잔고 구현)에서 완성 예정")

    def apply_realtime_position_line(self, item, vals, positions, extra) -> None:
        # LS 실시간 보유 종목 반영 형식 확정 후 G-2에서 구현.
        raise NotImplementedError("LS 실시간 보유 종목 반영은 G-2(LS 실전 체결·잔고 구현)에서 완성 예정")

    def compute_realtime_account_delta(self, vals: dict) -> dict:
        # LS 실시간 계좌 단위 갱신 형식 확정 후 G-2에서 구현.
        raise NotImplementedError("LS 실시간 계좌 갱신은 G-2(LS 실전 체결·잔고 구현)에서 완성 예정")
