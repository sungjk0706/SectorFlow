# -*- coding: utf-8 -*-
"""
레이더/작전 테이블용 실시간 시세 오버레이 및 REAL 01 거래대금 반영.

`engine_service` 모듈 전역 dict를 인자로 받아 갱신한다 -- 순환 import 없이 호출부에서 주입.
"""
from __future__ import annotations

from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd, _resolve_bucket_key


def overlay_radar_row_with_live_price(
    row: dict,
    latest_trade_prices: dict,
    latest_trade_amounts: dict[str, int],
    rest_quote_by_nk: dict[str, dict] | None = None,
) -> dict:
    """
    REAL 01(FID 10) 캐시로 현재가·거래대금만 보강.
    등락률·대비·sign·체결강도는 키움 서버 FID로만 갱신(REAL 01 본문) -- 클라이언트 재계산 없음.
    """
    out = dict(row)
    cd = str(out.get("code", "") or "").strip()
    if not cd:
        return out
    nk = _format_kiwoom_reg_stk_cd(cd)
    lp = latest_trade_prices.get(nk)
    if lp and int(lp) > 0:
        out["cur_price"] = int(lp)
        out.pop("quote_src", None)
    # REAL 01 캐시(FID 14) -- 부분 틱에서 행 dict에 없을 수 있어 보강
    if nk in latest_trade_amounts:
        out["trade_amount"] = int(latest_trade_amounts[nk] or 0)

    if (not lp or int(lp) <= 0) and rest_quote_by_nk:
        rq = rest_quote_by_nk.get(nk)
        if isinstance(rq, dict):
            cp = int(rq.get("cur_price") or 0)
            if cp > 0:
                out["cur_price"] = cp
                if rq.get("prev_close"):
                    out["prev_close"] = int(rq["prev_close"])
                if "change" in rq:
                    out["change"] = int(rq.get("change") or 0)
                if "change_rate" in rq:
                    out["change_rate"] = float(rq.get("change_rate") or 0.0)
                if rq.get("trade_amount"):
                    out["trade_amount"] = int(rq.get("trade_amount") or 0)
                if rq.get("strength"):
                    out["strength"] = str(rq.get("strength") or "-")
                if rq.get("sign"):
                    out["sign"] = str(rq.get("sign") or "3")
                out["quote_src"] = "rest"
    return out


def apply_real01_volume_amount_to_radar_rows(
    raw_cd: str,
    vals: dict,
    latest_trade_amounts: dict[str, int],
    pending_stock_details: dict,
    *,
    is_0b_tick: bool = True,
) -> None:
    """거래대금 캐시가 있으면 행 dict에 패치. 0으로 덮지 않음."""
    nk = _format_kiwoom_reg_stk_cd(raw_cd)

    def _patch_row(ed: dict) -> None:
        cached_amt = latest_trade_amounts.get(nk)
        if cached_amt is not None:
            ed["trade_amount"] = cached_amt

    pend_key = _resolve_bucket_key(raw_cd, pending_stock_details)
    if pend_key and pending_stock_details[pend_key].get("status") == "active":
        _patch_row(pending_stock_details[pend_key])
