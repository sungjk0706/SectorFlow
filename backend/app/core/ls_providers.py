# -*- coding: utf-8 -*-
"""
LS증권 Provider 구현체
"""
from __future__ import annotations
import logging
from backend.app.core.broker_providers import (
    AuthProvider, OrderProvider, WebSocketProvider
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
        self._auth = auth_provider

    def get_ws_uri(self) -> str:
        from backend.app.core.broker_urls import build_broker_urls
        return build_broker_urls("ls")["ws_uri"]
