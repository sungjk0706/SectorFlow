# -*- coding: utf-8 -*-
"""
키움증권 REST/REAL04 응답 파싱 — P4(증권사명 침투 금지)에 따라 공통 services에서 분리.

키움 전용 파싱 로직(parse_kt00001_deposit, parse_kt00018_balance, real04_official_*)은
본 모듈에 단일 진실 소스로 보관한다. engine_account 계좌
조회 경로가 이 함수들을 재사용한다.

전역 엔진 상태 없음 — 동일 입력에 동일 출력만 보장.
"""
from __future__ import annotations
from backend.app.services.engine_symbol_utils import _base_stk_cd, _real_item_stk_cd
from backend.app.services.engine_ws_parsing import _parse_fid10_price


def _parse_int_loose(v) -> int:
    try:
        return int(str(v).replace(",", "") or 0)
    except (ValueError, TypeError):
        return 0


def _parse_float_loose(v) -> float:
    try:
        cleaned = str(v).replace(",", "").replace("%", "").replace("+", "").strip()
        return float(cleaned or 0)
    except (ValueError, TypeError):
        return 0.0


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
        if _base_stk_cd(str(s.get("stk_cd", "") or "")) == raw_cd:
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
    if qty is not None and qty > 0:
        matched["qty"] = qty
    if buy_price is not None and buy_price > 0:
        matched["buy_price"] = buy_price
        matched["pur_pric"] = buy_price
    if buy_amt is not None and buy_amt > 0:
        matched["buy_amount"] = buy_amt
    if avail_qty is not None and avail_qty > 0:
        matched["avail_qty"] = avail_qty
    if pnl_amt is not None:
        matched["pnl_amount"] = pnl_amt
    if pnl_rate is not None:
        matched["pnl_rate"] = pnl_rate

    # 평가금액 실시간 재계산 (현재가 × 보유수량)
    _px = matched.get("cur_price", 0) or 0
    _qty = matched.get("qty", 0) or 0
    if _px > 0 and _qty > 0:
        matched["eval_amount"] = _px * _qty


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
        stk_cd = str(item.get("stk_cd", "")).strip()
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
