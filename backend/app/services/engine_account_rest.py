# -*- coding: utf-8 -*-
"""
계좌·포지션 REST(kt00001/kt00018) 병합 및 스냅샷 메타 계산 -- 엔진 전역을 직접 두지 않는다.

키움 전용 파싱 함수(parse_kt00001_deposit, parse_kt00018_balance, real04_official_*)는
P4(증권사명 침투 금지)에 따라 backend.app.core.kiwoom_providers 로 이동됨.
본 모듈은 증권사 공통 병합/메타 계산만 담당한다.

상태(_positions 등)는 호출부(engine_service)가 인자로 넘기고, 여기서는 동일 입력에 동일 출력만 보장한다.
"""
from __future__ import annotations
from datetime import datetime, timezone
from backend.app.services.engine_symbol_utils import _base_stk_cd
from backend.app.services.engine_ws_parsing import _rest_row_float, _rest_row_int


def merge_positions_from_rest(
    stock_list: list,
    latest_trade_prices: dict,
) -> list:
    """
    REST kt00018 잔고 반영. 수량·매입·종목명은 REST 기준.
    """
    merged: list = []
    for r in stock_list:
        if not isinstance(r, dict):
            continue
        cd = _base_stk_cd(str(r.get("stk_cd", "")).strip())
        if not cd:
            continue
        qty = _rest_row_int(r, "qty", "rmnd_qty")
        if qty <= 0:
            continue
        avg = _rest_row_int(r, "avg_price", "buy_price", "buy_uv", "pur_pric")
        cur = _rest_row_int(r, "cur_price", "cur_pric", "cur_prc")
        ba = _rest_row_int(r, "buy_amount", "buy_amt", "pur_amt")
        if ba <= 0:
            ba = avg * qty
        total_fee = _rest_row_int(r, "sum_cmsn", "pur_cmsn")
        buy_amt = ba + total_fee
        eval_amt = _rest_row_int(r, "eval_amount", "evlt_amt", "evltv_amt")
        pnl_amount = eval_amt - ba if eval_amt and ba else 0
        pnl_rate = round(pnl_amount / ba * 100, 2) if ba else 0.0
        row = {
            "stk_cd":     cd,
            "stk_nm":     str(r.get("stk_nm", cd)).strip(),
            "qty":        qty,
            "avail_qty":  _rest_row_int(r, "avail_qty", "trde_able_qty") or qty,
            "avg_price":  avg,
            "cur_price":  cur,
            "buy_amount": ba,
            "buy_amt":    buy_amt,
            "total_fee":  total_fee,
            "pnl_amount": pnl_amount,
            "pnl_rate":   pnl_rate,
            "eval_amount": eval_amt,
            "crd_tp":     str(r.get("crd_tp", "") or "").strip(),
            "pur_cmsn":   _rest_row_int(r, "pur_cmsn"),
            "sell_cmsn":  _rest_row_int(r, "sell_cmsn"),
            "sum_cmsn":   _rest_row_int(r, "sum_cmsn"),
            "tax":        _rest_row_int(r, "tax"),
            "hold_ratio": _rest_row_float(r, "hold_ratio", "poss_rt"),
        }
        merged.append(row)
    return merged


def broker_totals_from_summary(summary: dict) -> dict:
    """REST kt00018 루트 합계 -- 실시간 이벤트에서 임의 합산하지 않고 이 값만 갱신."""
    return {
        "total_eval": int(summary.get("tot_eval", 0) or 0),
        "total_pnl": int(summary.get("tot_pnl", 0) or 0),
        "total_buy": int(summary.get("tot_buy", 0) or 0),
        "total_rate": float(summary.get("total_rate", 0) or 0),
    }


def build_account_snapshot_meta(
    account_snapshot: dict,
    broker_rest_totals: dict,
    positions: list,
    price_source_ws: bool,
    trade_mode: str = "live",
) -> dict:
    """
    스냅샷 시각·보유종목수·가격소스만 갱신.
    총평가·총손익·총매입·총수익률은 broker_rest_totals만 사용(REST kt00018 또는 REAL 04 공식 FID 932~934) -- 포지션 합산 없음.
    예수금·주문가능은 kt00001(entr·ord_alow_amt) 또는 REAL 930 추정치.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    dep = account_snapshot.get("deposit")
    ord_a = account_snapshot.get("orderable")
    init_dep = account_snapshot.get("initial_deposit")
    tot = broker_rest_totals
    ps = "websocket" if price_source_ws else "rest_bootstrap"
    t_eval = tot.get("total_eval")
    t_pnl = tot.get("total_pnl")
    t_buy = tot.get("total_buy")
    t_sell = tot.get("total_sell")
    t_rate = tot.get("total_rate")
    return {
        "broker":           account_snapshot.get("broker", ""),
        "trade_mode":       trade_mode,
        "deposit":          dep,
        "orderable":        ord_a,
        "initial_deposit":  init_dep,
        "accumulated_investment": account_snapshot.get("accumulated_investment"),
        "total_eval":       t_eval,
        "total_pnl":        t_pnl,
        "total_buy":        t_buy,
        "total_sell":       t_sell,
        "total_rate":       t_rate,
        # 프론트엔드 호환 키
        "total_buy_amount":  t_buy,
        "total_sell_amount": t_sell,
        "total_eval_amount": t_eval,
        "total_pnl_rate":    t_rate,
        "position_count": len([p for p in positions if int(p.get("qty", 0) or 0) > 0]),
        "snapshot_at":    now_iso,
        "price_source":   ps,
    }


def apply_last_price_to_positions_inplace(
    positions: list,
    stk_cd: str,
    price: int,
) -> bool:
    """실시간 체결(REAL 01) -- 체결가(cur_price)만 반영. 평가손익·수익률·평가금액은
    증권사 서버가 보낸 값을 유지 (자체 계산 제거 — W7 실전 SSOT). 가격 변경 시에만 True."""
    if price <= 0:
        return False
    key = _base_stk_cd(stk_cd)
    for s in positions:
        if _base_stk_cd(str(s.get("stk_cd", "") or "")) == key:
            if int(s.get("cur_price", 0) or 0) == price:
                return False  # 가격 변경 없음
            s["cur_price"] = price
            return True
    return False


# ── 미체결 주문 파싱 (결정 6 — 엔진 기동 시 1회 조회) ──────────────────────────
# 공통 dict 키: ord_no·stk_cd·stk_nm·ord_qty·ord_price·unfilled_qty·
#              ord_status·orig_ord_no·ord_type(매도/매수)
# 파싱 함수는 각 증권사 전용 파싱 모듈로 이동됨 (P4 증권사명 침투 금지 · P23 일관성):
#   - 키움: backend.app.core.kiwoom_account_parsing.parse_kiwoom_unfilled_orders
#   - LS:   backend.app.core.ls_account_parsing.parse_ls_unfilled_orders
# 공통 서비스는 AccountProvider.parse_unfilled_orders 경유 호출 — 본 모듈에 파싱 함수 없음.
