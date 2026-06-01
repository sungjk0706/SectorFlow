from __future__ import annotations
# -*- coding: utf-8 -*-
"""
LS증권 Provider 구현체
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime

from backend.app.core.broker_providers import (
    AuthProvider, AccountProvider, OrderProvider, WebSocketProvider, UnifiedStockRecord
)
from backend.app.core.ls_rest import LsRestAPI
from backend.app.core.trading_calendar import get_kst_today_str

logger = logging.getLogger(__name__)

def _run_async(coro):
    """비동기 함수를 동기적으로 실행하기 위한 헬퍼. 
    (to_thread 로 호출된 별도 스레드에서만 사용해야 함)"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # 만약 비동기 루프 안에서 직접 호출되었다면 asyncio.create_task 등을 써야 하지만,
        # Provider 인터페이스는 동기 호출을 가정하므로, 보통 to_thread 안에서 실행됨.
        raise RuntimeError("비동기 루프 내에서 _run_async를 호출할 수 없습니다. asyncio.to_thread 내에서 사용하세요.")
    return asyncio.run(coro)

# ── Auth Provider ─────────────────────────────────────────────────────
class LsAuthProvider(AuthProvider):
    def __init__(self):
        from backend.app.services.engine_state import _integrated_system_settings_cache
        app_key = (_integrated_system_settings_cache.get("ls_app_key") or "").strip()
        app_secret = (_integrated_system_settings_cache.get("ls_app_secret") or "").strip()
        self._rest_api = LsRestAPI(app_key, app_secret)

    def get_access_token(self) -> str | None:
        # 토큰 갱신 시도 (asyncio.run 사용)
        ok = _run_async(self._rest_api.ensure_token())
        if ok:
            return self._rest_api.get_token()
        return None

    def ensure_token(self) -> bool:
        return _run_async(self._rest_api.ensure_token())

    @property
    def broker_name(self) -> str:
        return "ls"

    @property
    def rest_api(self) -> LsRestAPI:
        return self._rest_api


# ── Account Provider ──────────────────────────────────────────────────
class LsAccountProvider(AccountProvider):
    def __init__(self, auth_provider: AuthProvider):
        from backend.app.services.engine_state import _integrated_system_settings_cache
        self._rest_api = getattr(auth_provider, "rest_api", None)
        self._acnt_no = str(_integrated_system_settings_cache.get("ls_account_no", "") or "")

    def get_account_number(self) -> str | None:
        return self._acnt_no

    def get_deposit_detail(self, acnt_no: str = "") -> dict | None:
        if not self._rest_api:
            return None
        res = _run_async(self._rest_api.get_balance(cts_expcode=""))
        if not res or res.get("rsp_cd") not in ("00040", "00000"):
            return res
        return res

    def get_balance_detail(self, qry_tp: str = "1", dmst_stex_tp: str = "KRX") -> dict | None:
        if not self._rest_api:
            return None
        res = _run_async(self._rest_api.get_balance(cts_expcode=""))
        if not res or res.get("rsp_cd") not in ("00040", "00000"):
            return res
        return res

    def get_account_balance(self, acnt_no: str = "") -> dict:
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

        res = _run_async(self._rest_api.get_balance(cts_expcode=""))
        if not res or res.get("rsp_cd") not in ("00040", "00000"):
            logger.warning("[LS증권] 잔고 조회 실패: %s", res.get("rsp_msg") if res else "No Response")
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

    def send_order(self, order_type: int, acnt_no: str, code: str, qty: int, price: int, hoga_gb: str, **kwargs) -> dict:
        if not self._rest_api:
            return {"success": False, "error": "LS Rest API Not initialized"}

        # order_type (1: 신규매수, 2: 신규매도)
        if order_type == 1:
            res = _run_async(self._rest_api.buy_order(
                stock_code=f"A{code}",
                quantity=qty,
                price=float(price),
                order_type=hoga_gb
            ))
        elif order_type == 2:
            res = _run_async(self._rest_api.sell_order(
                stock_code=f"A{code}",
                quantity=qty,
                price=float(price),
                order_type=hoga_gb
            ))
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
        # LS OpenAPI WebSocket endpoint (production)
        return "wss://openapi.ls-sec.co.kr:9443/websocket"
