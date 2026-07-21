# -*- coding: utf-8 -*-
"""
LS증권 Provider 구현체
"""
from __future__ import annotations
import logging
from backend.app.core.broker_providers import (
    AuthProvider, AccountProvider, OrderProvider, WebSocketProvider
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


# ── Account Provider ──────────────────────────────────────────────────
class LsAccountProvider(AccountProvider):
    def __init__(self, auth_provider: AuthProvider):
        from backend.app.services.engine_state import state
        self._rest_api = getattr(auth_provider, "rest_api", None)
        self._acnt_no = str(state.integrated_system_settings_cache.get("ls_account_no", "") or "")

    async def get_account_number(self) -> str | None:
        return self._acnt_no

    async def get_deposit_detail(self, acnt_no: str = "") -> dict | None:
        if not self._rest_api:
            return None
        return await self._rest_api.get_balance(cts_expcode="")

    async def get_balance_detail(self, qry_tp: str = "1", dmst_stex_tp: str = "KRX") -> dict | None:
        if not self._rest_api:
            return None
        return await self._rest_api.get_balance(cts_expcode="")

    async def get_account_balance(self, acnt_no: str = "") -> dict:
        _empty: dict = {
            "success": False,
            "summary": {
                "tot_eval": 0, "tot_pnl": 0, "tot_buy": 0,
                "deposit": 0, "orderable": 0, "withdrawable": 0, "total_rate": 0.0,
            },
            "stock_list": [], "raw_data": {},
        }
        if not self._rest_api:
            return _empty

        res = await self._rest_api.get_balance(cts_expcode="")
        if not res or res.get("rsp_cd") not in ("00040", "00000"):
            logger.warning("[연결] %s 잔고 조회 실패: %s", _BROKER_DISPLAY, res.get("rsp_msg") if res else "응답 없음")
            return _empty

        outblock = res.get("t0424OutBlock", {})
        deposit = int(outblock.get("sunamt1") or 0)
        tot_eval = int(outblock.get("tappamt") or 0)
        tot_buy = int(outblock.get("mamt") or 0)
        tot_pnl = int(outblock.get("tdtsunik") or 0)

        total_rate = 0.0
        if tot_buy > 0:
            total_rate = round((tot_eval / tot_buy - 1.0) * 100, 2)

        stock_list = []
        for item in res.get("t0424OutBlock1", []):
            stk_cd = item.get("expcode", "").strip()
            qty = int(item.get("janqty") or 0)
            if qty <= 0:
                continue
            stock_list.append({
                "stk_cd": stk_cd,
                "stk_nm": item.get("hname", "").strip(),
                "qty": qty,
                "buy_price": int(item.get("pamt") or 0),
                "eval_price": int(item.get("price") or 0),
                "eval_amt": int(item.get("appamt") or 0),
                "eval_pnl": int(item.get("dtsunik") or 0),
                "eval_rate": float(item.get("sunikrt") or 0.0),
            })

        return {
            "success": True,
            "summary": {
                "tot_eval": tot_eval,
                "tot_pnl": tot_pnl,
                "tot_buy": tot_buy,
                "deposit": deposit,
                "orderable": deposit,
                "withdrawable": deposit,
                "total_rate": total_rate,
            },
            "stock_list": stock_list,
            "raw_data": {"t0424": res},
        }


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
