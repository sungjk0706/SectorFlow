# -*- coding: utf-8 -*-
"""
키움 주문 API - 매수/매도/정정/취소, 미체결조회
legacy_pc_engine/api_order.py 이식 (Settings 기반)
"""
from typing import Optional
import asyncio
import httpx
import logging
from backend.app.core.broker_urls import build_broker_urls, BROKER_DISPLAY_NAMES

logger = logging.getLogger(__name__)
_BROKER_DISPLAY = BROKER_DISPLAY_NAMES["kiwoom"]


async def _send_request(url: str, headers: dict, params: dict, max_retries: int = 3, delay: float = 1.0) -> Optional[httpx.Response]:
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(url, headers=headers, json=params, timeout=5)
                if r.status_code == 200:
                    return r
                logger.warning("[매매] %s 응답 코드 %s (시도=%d/%d) URL=%s", _BROKER_DISPLAY, r.status_code, attempt + 1, max_retries, url)
        except Exception as e:
            logger.warning("[매매] %s 통신 오류 (시도=%d/%d): %s", _BROKER_DISPLAY, attempt + 1, max_retries, e, exc_info=True)
        await asyncio.sleep(delay)
    logger.error("[매매] %s %d번 재시도 모두 실패 (URL=%s)", _BROKER_DISPLAY, max_retries, url)
    return None


def resolve_exchange(settings: dict, code: str) -> str:
    """
    주문 거래소 결정.
    종목코드 기반 자동 판단:
      · _NX 접미사 -> NXT
      · 설정에 exchange_mode='nxt' -> NXT
      · 그 외 -> SOR (KRX+NXT 자동 라우팅)
    """
    # _NX 접미사 종목은 NXT 직접 지정
    s = str(code or "").strip().upper()
    if s.endswith("_NX"):
        return "NXT"
    # 설정에서 명시적으로 거래소 지정한 경우
    exch = str(settings.get("exchange_mode") or "").strip().upper()
    if exch in ("KRX", "NXT", "SOR"):
        return exch
    return "SOR"  # 기본값: KRX+NXT 자동 라우팅


async def send_order(settings: dict, access_token: str, order_type: str, code: str, qty: int, price: int = 0, trde_tp: str = "3", orig_ord_no: str = "") -> dict:
    host = build_broker_urls("kiwoom")["rest_base"]
    exchange = resolve_exchange(settings, code)
    acnt_no = str(settings.get("kiwoom_account_no", "") or "")

    api_map = {"BUY": "kt10000", "SELL": "kt10001"}
    api_id = api_map.get(order_type.upper())
    if not api_id:
        return {"success": False, "msg": "알 수 없는 주문 타입", "data": None}

    ord_uv = "" if str(trde_tp) == "3" else str(price)
    # NXT 장외 시간대(프리마켓/애프터마켓)면 trde_tp 자동 조정
    if exchange == "NXT" and trde_tp in ("1", "3"):
        from backend.app.services.daily_time_scheduler import get_nxt_trde_tp
        trde_tp = get_nxt_trde_tp(trde_tp)
        if trde_tp in ("P", "U"):
            ord_uv = ""  # 장외 시간대는 가격 불필요
    params = {"acnt_no": acnt_no, "dmst_stex_tp": exchange, "stk_cd": str(code), "ord_qty": str(qty), "ord_uv": ord_uv, "trde_tp": str(trde_tp), "cond_uv": ""}

    url = f"{host}/api/dostk/ordr"
    headers = {"Content-Type": "application/json;charset=UTF-8", "authorization": f"Bearer {access_token}", "api-id": api_id}
    r = await _send_request(url, headers, params)
    if not r:
        return {"success": False, "msg": f"[{order_type}] 통신 장애", "data": None}
    data = r.json()
    ok = data.get("rt_cd") == "0"
    return {"success": ok, "msg": data.get("msg1", "알 수 없음"), "data": data}
