# -*- coding: utf-8 -*-
"""
LS증권 Provider 구현체
"""
from __future__ import annotations
import logging
from backend.app.core.broker_providers import (
    AccountProvider, AuthProvider, OrderProvider, WebSocketProvider
)
from backend.app.core import ls_account_parsing
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
        ot_lower = (order_type or "").lower()

        # 정정·취소는 원주문번호 필수 — 빈 값 시 즉시 실패 (설계서 결정 5)
        if ot_lower in ("modify", "cancel") and not str(orig_ord_no or "").strip():
            return {"success": False, "error": "원주문번호 없음"}

        if ot_lower == 'buy':
            res = await self._rest_api.buy_order(
                stock_code=f"A{code}",
                quantity=qty,
                price=float(price),
                order_type=hoga_gb
            )
            out_block_key = "CSPAT00601OutBlock2"
        elif ot_lower == 'sell':
            res = await self._rest_api.sell_order(
                stock_code=f"A{code}",
                quantity=qty,
                price=float(price),
                order_type=hoga_gb
            )
            out_block_key = "CSPAT00601OutBlock2"
        elif ot_lower == 'modify':
            res = await self._rest_api.modify_order(
                stock_code=f"A{code}",
                orig_ord_no=orig_ord_no,
                quantity=qty,
                price=float(price),
                order_type=hoga_gb
            )
            out_block_key = "CSPAT00701OutBlock2"
        elif ot_lower == 'cancel':
            res = await self._rest_api.cancel_order(
                stock_code=f"A{code}",
                orig_ord_no=orig_ord_no,
                quantity=qty
            )
            out_block_key = "CSPAT00801OutBlock2"
        else:
            return {"success": False, "error": f"Unsupported order_type: {order_type}"}

        if res and res.get("rsp_cd") in ("00040", "00000"):
            # 주문 성공 — OutBlock2에서 주문번호(OrdNo) 추출 (TR별 키 상이)
            block2 = res.get(out_block_key, {})
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
    """LS증권 계좌 데이터 파싱 — 파싱 모듈 위임.

    parse_deposit·parse_balance는 ls_account_parsing 모듈의 함수 호출 위임 (1단계 완성).
    실시간 3개 메서드(is_realtime_stock_item·apply_realtime_position_line·
    compute_realtime_account_delta)는 SC1 메시지 구조 확정 후 4단계에서 완성 —
    1단계에서는 스텁(빈 반환)으로 NotImplementedError 제거.
    """

    def __init__(self, auth_provider: AuthProvider | None = None):
        # AccountProvider는 순수 파싱 위임이므로 auth_provider 불필요.
        # _create_provider가 auth_provider 주입 패턴으로 호출하므로 시그니처만 맞춤.
        pass

    @property
    def broker_name(self) -> str:
        return "ls"

    def parse_deposit(self, raw: dict) -> tuple:
        """t0424 응답에서 예수금 추출 — ls_account_parsing.parse_t0424_deposit 위임."""
        return ls_account_parsing.parse_t0424_deposit(raw)

    def parse_balance(self, raw: dict, deposit) -> tuple:
        """t0424 응답에서 잔고·보유종목 추출 — ls_account_parsing.parse_t0424_balance 위임."""
        return ls_account_parsing.parse_t0424_balance(raw, deposit)

    def is_realtime_stock_item(self, item: dict) -> bool:
        """LS SC1 메시지 종목 판별 — ls_account_parsing._sc1_is_stock_item 위임.

        SC1은 항상 종목 단위 주문체결 메시지 — item 필드(종목코드) 존재 시 True.
        """
        return ls_account_parsing._sc1_is_stock_item(item)

    def apply_realtime_position_line(self, item, vals, positions, extra) -> None:
        """LS SC1 체결 메시지 보유 종목 반영 — ls_account_parsing.sc1_apply_position_line 위임.

        결정 4: SC1 체결(11) 시 extra["t0424_stock_list"]로 보유 종목 갱신.
        자체 델타 계산 금지 (P18 실전 SSOT).
        """
        return ls_account_parsing.sc1_apply_position_line(item, vals, positions, extra)

    def compute_realtime_account_delta(self, vals: dict) -> dict:
        """LS SC1 계좌 단위 갱신 — ls_account_parsing.sc1_account_delta 위임.

        결정 4: deposit·ordablemny 필드 기반 계좌 갱신.
        """
        return ls_account_parsing.sc1_account_delta(vals)
