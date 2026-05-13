# -*- coding: utf-8 -*-
"""
계좌 수익률, 종목명 조회
종목명: 로컬 stock_name_cache.json (장마감 파이프라인에서 갱신)
"""
import httpx as requests
from typing import Optional
from app.core.logger import get_logger
from app.core.trade_mode import effective_trade_mode, is_test_mode

logger = get_logger("data_manager")


def _get_rest_base() -> str:
    """BrokerRouter의 AuthProvider에서 REST base URL 획득."""
    from app.core.broker_factory import get_router
    try:
        settings = _load_kiwoom_settings() or {}
        auth = get_router(settings).auth
        if hasattr(auth, "rest_api") and hasattr(auth.rest_api, "base_url"):
            return auth.rest_api.base_url
    except Exception:
        logger.warning("[데이터관리] base_url 조회 실패", exc_info=True)
    return "https://api.kiwoom.com"


def _norm_stk_cd(stk_cd: str) -> str:
    """캐시 키용. 순수 숫자만 6자리로; 비숫자 포함(0120G0)은 숫자만 남기면 001200과 충돌하므로 원문 유지."""
    s = str(stk_cd).strip().lstrip("A")
    if not s:
        return ""
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s.upper()


def _load_kiwoom_settings() -> Optional[dict]:
    """
    로컬 settings.json에서 키움 설정 로드 (동기 버전).
    실패 시 None 반환.
    """
    try:
        from app.core.settings_file import load_settings
        from app.core.encryption import decrypt_value

        flat = load_settings()

        def _dec(v) -> str:
            if not v:
                return ""
            s = str(v)
            return decrypt_value(s) if s.startswith("gAAAA") else s

        tm = effective_trade_mode(flat)
        k = _dec(flat.get("kiwoom_app_key_real")) or _dec(flat.get("kiwoom_app_key"))
        s = _dec(flat.get("kiwoom_app_secret_real")) or _dec(flat.get("kiwoom_app_secret"))
        a = str(flat.get("kiwoom_account_no_real") or flat.get("kiwoom_account_no") or "")

        return {
            "kiwoom_app_key":    k,
            "kiwoom_app_secret": s,
            "kiwoom_account_no": a,
            "test_mode":         tm == "test",
            "trade_mode":        tm,
        }
    except Exception:
        return None


def get_stock_name(stk_cd: str, access_token: Optional[str] = None) -> str:
    """종목코드 -> 종목명. 로컬 stock_name_cache.json에서만 조회."""
    norm = _norm_stk_cd(stk_cd)
    if not norm:
        return "알수없음"
    from app.core.sector_stock_cache import load_stock_name_cache
    name_map = load_stock_name_cache() or {}
    return name_map.get(norm, norm)


def get_account_profit_rate(access_token: str) -> dict:
    """
    계좌 수익률 조회 -- 키움 REST API (kt00018: 계좌평가잔고내역) 직접 호출.
    토큰 없거나 API 실패 시 빈 dict 반환 (엔진 루프 중단 없음).
    """
    _empty = {
        "success": False,
        "summary": {"tot_eval": 0, "tot_pnl": 0, "tot_buy": 0, "total_rate": 0.0},
        "stock_list": [],
        "raw_data": {},
    }

    if not access_token:
        return _empty

    try:
        settings = _load_kiwoom_settings()
        if not settings:
            return _empty

        host = _get_rest_base()
        acnt_no = str(settings.get("kiwoom_account_no", "") or "")

        url = f"{host}/api/dostk/acnt"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {access_token}",
            "api-id": "kt00018",
        }
        body: dict = {}
        if acnt_no:
            body["acnt_no"] = acnt_no

        resp = requests.post(url, headers=headers, json=body or None, timeout=10)
        if resp.status_code != 200:
            logger.debug("[데이터관리] kt00018 실패함: %s", resp.status_code)
            return _empty

        data = resp.json()
        body_data = data.get("body") or data

        stock_items = body_data.get("acnt_evlt_remn_indv_tot", [])
        stock_list = []
        for item in (stock_items if isinstance(stock_items, list) else []):
            try:
                qty = int(str(item.get("rmnd_qty", 0)).replace(",", "") or 0)
                if qty <= 0:
                    continue
                stock_list.append({
                    "stk_cd":    str(item.get("stk_cd", "")).strip().lstrip("A"),
                    "stk_nm":    item.get("stk_nm", ""),
                    "qty":       qty,
                    "buy_price": int(str(item.get("buy_uv", 0)).replace(",", "") or 0),
                    "cur_price": int(str(item.get("cur_pric", 0)).replace(",", "") or 0),
                    "buy_amt":   int(str(item.get("buy_amt", 0)).replace(",", "") or 0),
                    "pnl_amt":   int(str(item.get("evlt_ploss", 0)).replace(",", "") or 0),
                    "pnl_rate":  float(str(item.get("prft_rt", 0)).replace(",", "").replace("%", "") or 0),
                })
            except Exception:
                continue

        def _ni(v) -> int:
            try:
                return int(str(v).replace(",", "") or 0)
            except (ValueError, TypeError):
                return 0

        def _nf(v) -> float:
            try:
                return float(str(v).replace(",", "").replace("%", "") or 0)
            except (ValueError, TypeError):
                return 0.0

        tot_eval   = _ni(body_data.get("tot_evlt_amt", 0))
        tot_pnl    = _ni(body_data.get("tot_evlt_pl",  0))
        tot_buy    = _ni(body_data.get("tot_pur_amt",  0))
        total_rate = _nf(body_data.get("tot_prft_rt",  0))

        return {
            "success":    True,
            "summary":    {
                "tot_eval":   tot_eval,
                "tot_pnl":    tot_pnl,
                "tot_buy":    tot_buy,
                "total_rate": total_rate,
            },
            "stock_list": stock_list,
            "raw_data":   body_data,
        }

    except Exception as e:
        logger.debug("[데이터관리] 계좌수익률 조회 예외: %s", e)
        return _empty


def get_main_account_info(access_token: str) -> list:
    """
    계좌 메인 정보 -- [예수금, 주문가능, 출금가능(pymn), "0", "0.00%"] 문자열 리스트.
    키움 REST API kt00001(예수금상세현황) 직접 호출.
    실패 시 ["0","0","0","0","0.00%"] 반환.
    """
    _fallback = ["0", "0", "0", "0", "0.00%"]

    if not access_token:
        return _fallback

    try:
        settings = _load_kiwoom_settings()
        if not settings:
            return _fallback

        host = _get_rest_base()
        acnt_no = str(settings.get("kiwoom_account_no", "") or "")

        url = f"{host}/api/dostk/acnt"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {access_token}",
            "api-id": "kt00001",
        }
        body: dict = {"qry_tp": "3"}
        if acnt_no:
            body["acnt_no"] = acnt_no

        resp = requests.post(url, headers=headers, json=body, timeout=10)
        if resp.status_code != 200:
            return _fallback

        data = resp.json()
        body_data = data.get("body") or data

        if int(str(body_data.get("return_code", 0)).replace(",", "") or 0) != 0:
            logger.debug("[데이터관리] kt00001 오류 메시지: %s", body_data.get("return_msg", ""))
            return _fallback

        def _n(v) -> str:
            try:
                return f"{int(str(v).replace(',', '') or 0):,}"
            except (ValueError, TypeError):
                return "0"

        deposit = _n(body_data.get("entr", body_data.get("d2_entra", 0)))
        orderable = _n(body_data.get("ord_alow_amt", 0))
        withdrawable = _n(body_data.get("pymn_alow_amt", 0))

        return [deposit, orderable, withdrawable, "0", "0.00%"]

    except Exception as e:
        logger.debug("[데이터관리] 메인계좌정보 조회 예외: %s", e)
        return _fallback
