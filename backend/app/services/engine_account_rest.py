# -*- coding: utf-8 -*-
"""
계좌·포지션 REST(kt00001/kt00018) 병합 및 스냅샷 메타 계산 -- 엔진 전역을 직접 두지 않는다.

상태(_positions 등)는 호출부(engine_service)가 인자로 넘기고, 여기서는 동일 입력에 동일 출력만 보장한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd, _real_item_stk_cd
from app.services.engine_ws_parsing import _parse_fid10_price, _rest_row_float, _rest_row_int


def _parse_int_loose(v) -> int:
    try:
        return int(str(v).replace(",", "") or 0)
    except (ValueError, TypeError):
        return 0


def _parse_float_loose(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", "") or 0)
    except (ValueError, TypeError):
        return 0.0


def merge_positions_from_rest(
    stock_list: list,
    latest_trade_prices: dict,
) -> list:
    """
    REST kt00018 잔고 반영. 수량·매입·종목명은 REST 기준.
    현재가: latest_trade_prices(REAL 01 등 실시간)에 값이 있으면 항상 우선 -- REST 현재가로 덮지 않음.
    """
    merged: list = []
    for r in stock_list:
        if not isinstance(r, dict):
            continue
        cd = str(r.get("stk_cd", "")).strip().lstrip("A")
        if not cd:
            continue
        qty = _rest_row_int(r, "qty", "rmnd_qty")
        if qty <= 0:
            continue
        buy = _rest_row_int(r, "buy_price", "buy_uv", "pur_pric")
        rest_px = _rest_row_int(r, "cur_price", "cur_pric", "cur_prc")
        live_px = latest_trade_prices.get(cd)
        if live_px and int(live_px) > 0:
            cur = int(live_px)
        else:
            cur = rest_px
        ba = _rest_row_int(r, "buy_amount", "buy_amt", "pur_amt")
        if ba <= 0:
            ba = buy * qty
        row = {
            "stk_cd":     cd,
            "stk_nm":     str(r.get("stk_nm", cd)).strip(),
            "qty":        qty,
            "avail_qty":  _rest_row_int(r, "avail_qty", "trde_able_qty") or qty,
            "buy_price":  buy,
            "pur_pric":   buy,
            "cur_price":  cur,
            "buy_amount": ba,
            "pnl_amount": _rest_row_int(r, "pnl_amount", "evltv_prft", "evlt_ploss"),
            "pnl_rate":   _rest_row_float(r, "pnl_rate", "prft_rt"),
            "eval_amount": _rest_row_int(r, "eval_amount", "evlt_amt", "evltv_amt"),
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


def recalc_broker_totals_from_positions(positions: list, broker_rest_totals: dict) -> dict:
    """
    REAL 01 틱마다 positions 합산으로 총평가·총손익·총수익률 실시간 갱신.
    총매입은 REST 기준 고정(buy_amount 합산).
    """
    tot_eval = 0
    tot_buy = 0
    tot_pnl = 0
    for p in positions:
        if int(p.get("qty", 0) or 0) > 0:
            tot_eval += int(p.get("eval_amount", 0) or 0)
            tot_buy += int(p.get("buy_amount", 0) or 0)
            tot_pnl += int(p.get("pnl_amount", 0) or 0)
    tot_rate = round(tot_pnl / tot_buy * 100, 2) if tot_buy else 0.0
    return {
        "total_eval": tot_eval,
        "total_pnl":  tot_pnl,
        "total_buy":  broker_rest_totals.get("total_buy", tot_buy),  # REST 기준 유지
        "total_rate": tot_rate,
    }


def _real04_is_stock_item(item: dict) -> bool:
    """
    REAL 04 item 필드가 종목코드인지 계좌번호인지 구분.
    키움 공식: item이 'A005930' 형태(알파벳+숫자) -> 종목, 숫자만 -> 계좌번호.
    """
    raw = ""
    item_field = item.get("item")
    if isinstance(item_field, (list, tuple)) and item_field:
        raw = str(item_field[0] or "").strip()
    elif item_field is not None:
        raw = str(item_field).strip()
    if not raw:
        return False
    # 알파벳 포함(A005930 등) -> 종목코드
    return not raw.isdigit()


def real04_official_account_delta(vals: dict) -> dict:
    """
    키움 공식 안내: REAL 04 계좌 단위 레코드 FID (item=계좌번호일 때만 호출)
      930=예수금, 932=총평가금액, 933=총손익, 934=총수익률.
    키가 있을 때만 반환(부분 갱신).
    """
    if not isinstance(vals, dict):
        return {}
    out: dict = {}
    if "930" in vals:
        out["deposit"] = _parse_int_loose(vals.get("930"))
    if "932" in vals:
        out["total_eval"] = _parse_int_loose(vals.get("932"))
    if "933" in vals:
        out["total_pnl"] = _parse_int_loose(vals.get("933"))
    if "934" in vals:
        out["total_rate"] = _parse_float_loose(vals.get("934"))
    return out


def real04_official_apply_position_line(
    item: dict,
    vals: dict,
    positions: list,
    latest_trade_prices: dict,
) -> None:
    """
    키움 공식 안내: 종목 단위 REAL 04 (item=종목코드일 때만 호출)
      930=보유수량, 931=매입단가, 932=매입금액, 933=가능수량,
      950=평가손익, 8019=수익률(%), 10=현재가.
    현재가는 REAL 0B(체결가) 우선 -- 이미 캐시가 있으면 FID 10으로 덮지 않음.
    평가금액은 현재가×보유수량으로 계산.
    """
    raw_cd = _real_item_stk_cd(item, vals)
    if not raw_cd:
        return
    stk_nm = str(vals.get("302", "") or "").strip()
    cur_price = _parse_fid10_price(vals)
    live = latest_trade_prices.get(raw_cd)
    prefer_01 = live is not None and int(live) > 0

    qty       = _parse_int_loose(vals.get("930")) if "930" in vals else None
    buy_price = _parse_int_loose(vals.get("931")) if "931" in vals else None
    buy_amt   = _parse_int_loose(vals.get("932")) if "932" in vals else None
    avail_qty = _parse_int_loose(vals.get("933")) if "933" in vals else None
    pnl_amt   = _parse_int_loose(vals.get("950")) if "950" in vals else None
    pnl_rate  = _parse_float_loose(vals.get("8019")) if "8019" in vals else None

    # 기존 포지션에서 매칭 시도
    matched = None
    for s in positions:
        if _format_kiwoom_reg_stk_cd(str(s.get("stk_cd", "") or "")) == raw_cd:
            matched = s
            break

    # 장중 재기동 시 _positions가 비어있을 수 있음 -- REAL 04 종목 레코드로 신규 추가
    if matched is None:
        _qty_new = qty if (qty is not None and qty > 0) else 0
        if _qty_new <= 0:
            return  # 수량 0이면 추가 불필요
        matched = {
            "stk_cd":     raw_cd,
            "stk_nm":     stk_nm or raw_cd,
            "qty":        _qty_new,
            "avail_qty":  avail_qty if avail_qty is not None else _qty_new,
            "buy_price":  buy_price or 0,
            "pur_pric":   buy_price or 0,
            "cur_price":  cur_price if (not prefer_01 and cur_price > 0) else (latest_trade_prices.get(raw_cd) or 0),
            "buy_amount": buy_amt or 0,
            "pnl_amount": pnl_amt or 0,
            "pnl_rate":   pnl_rate or 0.0,
            "eval_amount": 0,
            "sum_cmsn":   0,
            "tax":        0,
            "hold_ratio": 0.0,
        }
        _px = matched["cur_price"]
        if _px > 0 and _qty_new > 0:
            matched["eval_amount"] = _px * _qty_new
        positions.append(matched)
        return

    # 기존 포지션 갱신
    if stk_nm:
        matched["stk_nm"] = stk_nm
    if not prefer_01 and cur_price > 0:
        matched["cur_price"] = cur_price
        latest_trade_prices[raw_cd] = cur_price
    if qty is not None and qty > 0:
        matched["qty"] = qty
    if buy_price is not None and buy_price > 0:
        matched["buy_price"] = buy_price
        matched["pur_pric"]  = buy_price
    if buy_amt is not None and buy_amt > 0:
        matched["buy_amount"] = buy_amt
    if avail_qty is not None:
        matched["avail_qty"] = avail_qty
    if pnl_amt is not None:
        matched["pnl_amount"] = pnl_amt
    if pnl_rate is not None:
        matched["pnl_rate"] = pnl_rate
    # 평가금액: 현재가×보유수량 계산 (별도 FID 없음 -- 키움 공식 답변)
    _px = matched.get("cur_price", 0) or 0
    _qty = matched.get("qty", 0) or 0
    if _px > 0 and _qty > 0:
        matched["eval_amount"] = _px * _qty


def build_account_snapshot_meta(
    account_snapshot: dict,
    broker_rest_totals: dict,
    positions: list,
    price_source_ws: bool,
    trade_mode: str = "real",
) -> dict:
    """
    스냅샷 시각·보유종목수·가격소스만 갱신.
    총평가·총손익·총매입·총수익률은 broker_rest_totals만 사용(REST kt00018 또는 REAL 04 공식 FID 932~934) -- 포지션 합산 없음.
    예수금·주문가능은 kt00001(entr·ord_alow_amt) 또는 REAL 930 추정치.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    dep = int(account_snapshot.get("deposit", 0) or 0)
    ord_a = int(account_snapshot.get("orderable", 0) or 0)
    init_dep = int(account_snapshot.get("initial_deposit", 0) or 0)
    tot = broker_rest_totals
    ps = "websocket" if price_source_ws else "rest_bootstrap"
    t_eval = int(tot.get("total_eval", 0))
    t_pnl = int(tot.get("total_pnl", 0))
    t_buy = int(tot.get("total_buy", 0))
    t_sell = int(tot.get("total_sell", 0))
    t_rate = float(tot.get("total_rate", 0.0))
    return {
        "broker":           account_snapshot.get("broker", "kiwoom"),
        "trade_mode":       trade_mode,
        "deposit":          dep,
        "orderable":        ord_a,
        "initial_deposit":  init_dep,
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
    """실시간 체결(REAL 01) -- 체결가 반영 + 평가손익·수익률·평가금액 실시간 재계산. 가격 변경 시에만 True."""
    if price <= 0:
        return False
    key = _format_kiwoom_reg_stk_cd(stk_cd)
    for s in positions:
        if _format_kiwoom_reg_stk_cd(str(s.get("stk_cd", "") or "")) == key:
            if int(s.get("cur_price", 0) or 0) == price:
                return False  # 가격 변경 없음 — 재계산 스킵
            s["cur_price"] = price
            # 평가손익·수익률·평가금액 실시간 재계산 (수수료+세금 반영)
            qty = int(s.get("qty", 0) or 0)
            buy_amt = int(s.get("buy_amount", 0) or 0)
            if qty > 0 and buy_amt > 0:
                cmsn = int(s.get("sum_cmsn", s.get("pur_cmsn", 0)) or 0)
                tax = int(s.get("tax", 0) or 0)
                eval_amt = price * qty
                pnl = eval_amt - buy_amt - cmsn - tax
                rate = round(pnl / buy_amt * 100, 2) if buy_amt else 0.0
                s["eval_amount"] = eval_amt
                s["pnl_amount"] = pnl
                s["pnl_rate"] = rate
            return True
    return False


def parse_kt00001_deposit(
    deposit_raw: dict | None,
) -> tuple[bool, dict, int, int, int]:
    """
    kt00001 응답 파싱. (성공 여부, dep_body, deposit, orderable, withdrawable).
    deposit: entr(HTS 상단 예수금과 동일) 우선, 없으면 d2_entra.
    orderable: ord_alow_amt. withdrawable: pymn_alow_amt(출금가능, 실질 현금 기준 권장).
    실패 시 (False, dep_body 또는 {}, 0, 0, 0).
    """
    if not deposit_raw:
        return False, {}, 0, 0, 0
    dep_body = deposit_raw.get("body") or deposit_raw
    if _parse_int_loose(dep_body.get("return_code", 0)) != 0:
        return False, dep_body, 0, 0, 0
    deposit = _parse_int_loose(dep_body.get("entr", dep_body.get("d2_entra", 0)))
    orderable = _parse_int_loose(dep_body.get("ord_alow_amt", 0))
    withdrawable = _parse_int_loose(dep_body.get("pymn_alow_amt", 0))
    return True, dep_body, deposit, orderable, withdrawable


def parse_kt00018_balance(
    balance_raw: dict | None,
    deposit: int,
) -> tuple[int, int, int, int, float, list]:
    """
    kt00018 응답에서 합계·종목 리스트 추출.
    Returns (deposit, tot_eval, tot_pnl, tot_buy, total_rate, stock_list).
    deposit 은 kt00001 값이 0일 때 prsm_dpst_aset_amt 로 보완될 수 있음.
    """
    tot_eval = 0
    tot_pnl = 0
    tot_buy = 0
    total_rate = 0.0
    stock_list: list = []
    dep_out = deposit
    if not balance_raw:
        return dep_out, tot_eval, tot_pnl, tot_buy, total_rate, stock_list
    bal = balance_raw.get("body") or balance_raw

    if _parse_int_loose(bal.get("return_code", 0)) == 0:
        tot_eval = _parse_int_loose(bal.get("tot_evlt_amt", 0))
        tot_pnl = _parse_int_loose(bal.get("tot_evlt_pl", 0))
        tot_buy = _parse_int_loose(bal.get("tot_pur_amt", 0))
        total_rate = _parse_float_loose(bal.get("tot_prft_rt", 0))
        if not dep_out:
            dep_out = _parse_int_loose(bal.get("prsm_dpst_aset_amt", 0))

    for item in bal.get("acnt_evlt_remn_indv_tot", []):
        stk_cd = str(item.get("stk_cd", "")).strip().lstrip("A")
        if not stk_cd:
            continue
        qty = _parse_int_loose(item.get("rmnd_qty", 0))
        if qty <= 0:
            continue
        crd = str(item.get("crd_tp", "") or "").strip()
        # evltv_prft: 실제 API 키. evlt_ploss는 구버전 호환용 폴백
        _pnl = _parse_int_loose(item.get("evltv_prft", item.get("evlt_ploss", 0)))
        _rate = _parse_float_loose(item.get("prft_rt", 0))
        _buy_uv = _parse_int_loose(item.get("pur_pric", item.get("buy_uv", 0)))
        _cur = _parse_int_loose(item.get("cur_prc", item.get("cur_pric", 0)))
        _buy_amt = _parse_int_loose(item.get("pur_amt", item.get("buy_amt", 0)))
        _pur_cmsn = _parse_int_loose(item.get("pur_cmsn", 0))
        _sell_cmsn = _parse_int_loose(item.get("sell_cmsn", 0))
        _tax = _parse_int_loose(item.get("tax", 0))
        # sum_cmsn: 매수+매도 수수료 합계 -- HTS 수수료 컬럼과 일치
        _sum_cmsn = _parse_int_loose(item.get("sum_cmsn", _pur_cmsn + _sell_cmsn))
        _avail_qty = _parse_int_loose(item.get("trde_able_qty", item.get("trd_able_qty", qty)))
        _hold_ratio = _parse_float_loose(item.get("poss_rt", 0))
        stock_list.append({
            "stk_cd":     stk_cd,
            "stk_nm":     str(item.get("stk_nm", stk_cd)).strip(),
            "qty":        qty,
            "avail_qty":  _avail_qty,
            "buy_price":  _buy_uv,
            "pur_pric":   _buy_uv,
            "cur_price":  _cur,
            "buy_amount": _buy_amt,
            "pnl_amount": _pnl,
            "pnl_rate":   _rate,
            "eval_amount": _parse_int_loose(item.get("evlt_amt", item.get("evltv_amt", 0))),
            "crd_tp":     crd,
            "pur_cmsn":   _pur_cmsn,
            "sell_cmsn":  _sell_cmsn,
            "sum_cmsn":   _sum_cmsn,
            "tax":        _tax,
            "hold_ratio": _hold_ratio,
        })

    return dep_out, tot_eval, tot_pnl, tot_buy, total_rate, stock_list
