# -*- coding: utf-8 -*-
"""
LS증권 REST t0424 응답 파싱 — P4(증권사명 침투 금지)에 따라 공통 services에서 분리.

LS 전용 파싱 로직(parse_t0424_deposit, parse_t0424_balance, SC1 실시간 함수)은
본 모듈에 단일 진실 소스로 보관한다. engine_account 계좌
조회 경로가 이 함수들을 재사용한다.

전역 엔진 상태 없음 — 동일 입력에 동일 출력만 보장.
"""
from __future__ import annotations
from backend.app.core.numeric_utils import _parse_float_loose


def _parse_int_loose(v) -> int:
    try:
        return int(str(v).replace(",", "") or 0)
    except (ValueError, TypeError):
        return 0


def _strip_a_prefix(expcode: str) -> str:
    """LS 종목번호(expcode)에서 A 접두어 제거 — 'A005930' -> '005930'."""
    raw = str(expcode or "").strip()
    if raw and raw[0] in ("A", "a"):
        return raw[1:]
    return raw


def parse_t0424_deposit(
    raw: dict | None,
) -> tuple[bool, dict, int, int, int]:
    """
    t0424 응답 파싱(예수금 추출). (성공 여부, body, deposit, orderable, withdrawable).

    LS는 예수금 상세 전용 TR이 없으므로 t0424 합계 블록의 sunamt1(추정D2예수금)을
    예수금으로 추출 (결정 2). orderable·withdrawable은 0으로 초기화 —
    실시간 SC1 ordablemny 수신 시 보완 (4단계).
    실패 시 (False, body 또는 {}, 0, 0, 0).
    """
    if not raw:
        return False, {}, 0, 0, 0
    body = raw.get("t0424OutBlock") or raw.get("body") or raw
    rsp_cd = str(raw.get("rsp_cd", body.get("rsp_cd", "")) or "")
    # LS 성공 코드: "00000" (정상). 빈 응답 body도 실패 처리.
    if rsp_cd and rsp_cd not in ("00000", "0"):
        return False, body, 0, 0, 0
    deposit = _parse_int_loose(body.get("sunamt1", 0))
    orderable = 0  # 실시간 SC1 ordablemny로 보완 (4단계)
    withdrawable = 0  # LS 실전 응답 확인 후 보완 (G-3/G-5/G-6 범주)
    return True, body, deposit, orderable, withdrawable


def parse_t0424_balance(
    raw: dict | None,
    deposit: int,
) -> tuple[int, int, int, int, float, list]:
    """
    t0424 응답에서 합계·종목 리스트 추출.
    Returns (deposit, tot_eval, tot_pnl, tot_buy, total_rate, stock_list).

    합계 블록: sunamt(추정순자산)·tappamt(평가금액)·tdtsunik(평가손익)·mamt(매입금액).
    종목 배열: t0424OutBlock1 — expcode·hname·janqty·mdposqt·pamt·price·mamt·
              appamt·dtsunik·sunikrt·janrt.
    deposit은 t0424 합계 sunamt1 값이 0일 때 보완용으로 전달받는다.
    """
    tot_eval = 0
    tot_pnl = 0
    tot_buy = 0
    total_rate = 0.0
    stock_list: list = []
    dep_out = deposit
    if not raw:
        return dep_out, tot_eval, tot_pnl, tot_buy, total_rate, stock_list

    body = raw.get("t0424OutBlock") or raw.get("body") or raw
    rsp_cd = str(raw.get("rsp_cd", body.get("rsp_cd", "")) or "")
    # 오류 응답 코드 시 합계·종목 모두 스킵 — 빈 결과 반환 (P20 폴백 금지).
    if rsp_cd and rsp_cd not in ("00000", "0"):
        return dep_out, tot_eval, tot_pnl, tot_buy, total_rate, stock_list

    tot_eval = _parse_int_loose(body.get("tappamt", 0))
    tot_pnl = _parse_int_loose(body.get("tdtsunik", 0))
    tot_buy = _parse_int_loose(body.get("mamt", 0))
    total_rate = _parse_float_loose(body.get("sunikrt", 0))
    if not dep_out:
        dep_out = _parse_int_loose(body.get("sunamt1", 0))

    items = raw.get("t0424OutBlock1") or body.get("t0424OutBlock1") or []
    if isinstance(items, dict):
        items = [items]
    for item in items:
        if not isinstance(item, dict):
            continue
        stk_cd = _strip_a_prefix(item.get("expcode", ""))
        if not stk_cd:
            continue
        qty = _parse_int_loose(item.get("janqty", 0))
        if qty <= 0:
            continue
        stock_list.append({
            "stk_cd": stk_cd,
            "stk_nm": str(item.get("hname", stk_cd)).strip(),
            "qty": qty,
            "avail_qty": _parse_int_loose(item.get("mdposqt", qty)),
            "avg_price": _parse_int_loose(item.get("pamt", 0)),
            "cur_price": _parse_int_loose(item.get("price", 0)),
            "buy_amount": _parse_int_loose(item.get("mamt", 0)),
            "pnl_amount": _parse_int_loose(item.get("dtsunik", 0)),
            "pnl_rate": _parse_float_loose(item.get("sunikrt", 0)),
            "eval_amount": _parse_int_loose(item.get("appamt", 0)),
            "hold_ratio": _parse_float_loose(item.get("janrt", 0)),
        })

    return dep_out, tot_eval, tot_pnl, tot_buy, total_rate, stock_list


# ── SC1 실시간 파싱 (4단계 구현) ───────────────────────────────────────────
# SC1 주문체결 메시지 — ordxctptncode(주문체결유형코드)로 체결 여부 판별.
# 11=체결 → t0424 REST 재조회로 잔고 갱신 (자체 델타 계산 금지 — P18).
# 01/02/03/12/13/14 (주문·정정·취소·확인·거부) → 잔고 변동 없음.

# 주문체결유형코드 — 11만 잔고 변동, 나머지는 잔고 변동 없음.
_SC1_FILL_CODE = "11"


def _sc1_is_stock_item(item: dict) -> bool:
    """LS SC1 메시지는 항상 종목 단위 (주문체결 메시지).

    SC1은 종목별 주문체결 알림 — 계좌 단위 레코드가 별도로 오지 않고
    deposit·ordablemny 등 계좌 필드가 SC1 한 메시지에 함께 포함.
    종목 코드(item 필드)가 존재하면 종목 단위로 판별.
    """
    if not isinstance(item, dict):
        return False
    item_field = item.get("item")
    if item_field is None:
        return False
    if isinstance(item_field, (list, tuple)):
        if not item_field:
            return False
        raw = str(item_field[0] or "").strip()
    else:
        raw = str(item_field).strip()
    return bool(raw)


def sc1_apply_position_line(item, vals, positions, extra) -> None:
    """LS SC1 체결 메시지 보유 종목 반영 (결정 4).

    ordxctptncode=11(체결) 시 extra["t0424_stock_list"]로 보유 종목 갱신.
    자체 델타 계산 금지 (P18 실전 SSOT) — t0424 REST 재조회 결과를 extra로 전달받아 적용.
    01/02/03/12/13/14 (주문·정정·취소·확인·거부)는 잔고 변동 없음 → 갱신 생략.
    t0424 재조회 결과가 extra에 없으면 갱신 불가 → 폴백 없이 생략 (P20).
    """
    ordxct = str(vals.get("ordxctptncode", "") or "").strip() if isinstance(vals, dict) else ""
    if ordxct != _SC1_FILL_CODE:
        return  # 체결(11)만 잔고 변동

    stock_list = (extra or {}).get("t0424_stock_list") if extra else None
    if not stock_list:
        return  # t0424 재조회 결과 없음 → 자체 계산 금지 (P18·P20)

    # t0424 재조회 결과로 보유 종목 전체 재구성 — REST가 SSOT (P18).
    # merge_positions_from_rest는 수량·매입·종목명을 REST 기준으로 덮어쓰기.
    from backend.app.services.engine_account_rest import merge_positions_from_rest
    merged = merge_positions_from_rest(stock_list, {})
    positions.clear()
    positions.extend(merged)


def sc1_account_delta(vals: dict) -> dict:
    """LS SC1 계좌 단위 갱신 필드 반환 (결정 4).

    deposit(예수금)·ordablemny(주문가능현금) 필드 기반 계좌 갱신.
    이 2개 필드는 실서버에서 정상 값 수신 확인 (결정 4).
    체결 시 t0424 재조회로 확보한 예수금(sunamt1)이 최종 승리값.
    """
    if not isinstance(vals, dict):
        return {}
    out: dict = {}
    if "deposit" in vals:
        out["deposit"] = _parse_int_loose(vals.get("deposit"))
    if "ordablemny" in vals:
        out["orderable"] = _parse_int_loose(vals.get("ordablemny"))
    return out
