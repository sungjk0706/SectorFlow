# -*- coding: utf-8 -*-
"""
키움증권 브로커 구현체 (KiwoomBroker)

구조:
  - KiwoomApi (kiwoom.py)     : 토큰 발급, 호가/종가, WebSocket 인증
  - KiwoomRestAPI (kiwoom_rest.py): 계좌 REST 조회 (토큰 내장)
  - KiwoomBroker (이 파일)    : 위 두 클래스를 BrokerInterface 로 캡슐화

get_account_balance() 가 공통 표준 반환 구조(data_manager.py 기준)의 진입점.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from app.core.broker_interface import BrokerInterface
from app.core.broker_urls import build_broker_urls
from app.core.kiwoom import KiwoomApi
from app.core.kiwoom_rest import KiwoomRestAPI
from app.core.kiwoom_order import send_order as _kiwoom_send_order

_log = logging.getLogger(__name__)


class KiwoomBroker(BrokerInterface):
    """키움증권 REST + WebSocket 브로커"""

    def __init__(self, settings: dict):
        self._settings = settings

        app_key    = (settings.get("kiwoom_app_key")    or "").strip()
        app_secret = (settings.get("kiwoom_app_secret") or "").strip()

        self._api       = KiwoomApi(settings)
        self._rest_api  = KiwoomRestAPI(app_key, app_secret)
        self._rest_api._acnt_no = str(settings.get("kiwoom_account_no", "") or "")
        self._acnt_no   = self._rest_api._acnt_no

    # ── 인증 ──────────────────────────────────────────────────────────────
    def get_access_token(self) -> Optional[str]:
        """[au10001] WebSocket 로그인용 토큰 -- KiwoomRestAPI와 동일 캐시 사용(이중 발급·429 예방)."""
        return self._rest_api.get_access_token()

    def ensure_token(self) -> bool:
        """토큰 유효성 확인, 만료 시 자동 갱신."""
        return self._rest_api._ensure_token()

    # ── 계좌 조회 ─────────────────────────────────────────────────────────
    def get_account_number(self) -> Optional[str]:
        return self._rest_api.get_account_number()

    def get_deposit_detail(self, acnt_no: str = "") -> Optional[dict]:
        resolved = acnt_no or self._acnt_no
        self._rest_api._acnt_no = resolved
        return self._rest_api.get_deposit_detail(acnt_no=resolved)

    def get_balance_detail(self, qry_tp: str = "1", dmst_stex_tp: str = "KRX") -> Optional[dict]:
        """계좌평가잔고내역 조회."""
        return self._rest_api.get_balance_detail(qry_tp, dmst_stex_tp)

    def get_account_balance(self, acnt_no: str = "") -> dict:
        """
        [공통 표준] 계좌 잔고 통합 조회.

        kt00001(예수금) + kt00018(평가잔고)를 결합해
        BrokerInterface에 정의된 표준 구조로 반환한다.
        data_manager.py 검증 필드명 사용:
          개별 종목: buy_uv, cur_pric, buy_amt, evlt_ploss, prft_rt
          합계     : acnt_evlt_remn_tot -> tot_evlt_amt, evlt_ploss_smamt, tot_buy_amt, prft_rt
        """
        _empty = {
            "success": False,
            "summary": {
                "tot_eval": 0, "tot_pnl": 0, "tot_buy": 0,
                "deposit": 0, "orderable": 0, "withdrawable": 0, "total_rate": 0.0,
            },
            "stock_list": [],
            "raw_data": {},
        }

        if not self._rest_api._ensure_token():
            _log.warning("[키움증권]  토큰 없음 (au10001 실패) -- 계좌잔고 조회 중단")
            return _empty

        resolved = acnt_no or self._acnt_no

        def _n(v) -> int:
            try:
                return int(str(v).replace(",", "") or 0)
            except (ValueError, TypeError):
                return 0

        def _f(v) -> float:
            try:
                return float(str(v).replace(",", "").replace("%", "") or 0)
            except (ValueError, TypeError):
                return 0.0

        # kt00001 -- 예수금 · 주문가능금액
        dep_raw = self._rest_api.get_deposit_detail(acnt_no=resolved)
        time.sleep(0.5)  # 429 예방
        # kt00018 -- 평가잔고 + 종목별 상세
        bal_raw = self._rest_api.get_balance_detail()

        if not dep_raw:
            _log.warning("[키움증권] kt00001 응답 없음")
            return _empty

        # kt00001 응답 -- body 래퍼 없음, 루트가 데이터
        dep_body = dep_raw.get("body") or dep_raw
        if _n(dep_body.get("return_code", 0)) != 0:
            _log.warning(
                "[키움증권] kt00001 오류 return_code=%s msg=%s",  
                dep_body.get("return_code"), dep_body.get("return_msg", ""),
            )
            return _empty

        deposit = _n(dep_body.get("entr", dep_body.get("d2_entra", 0)))  # HTS 상단 예수금과 동일(entr)
        orderable = _n(dep_body.get("ord_alow_amt", 0))
        withdrawable = _n(dep_body.get("pymn_alow_amt", 0))  # 출금가능, 실질 현금 기준 권장
        tot_eval   = 0
        tot_pnl    = 0
        total_rate = 0.0
        tot_buy    = 0

        # kt00018 응답 -- body 래퍼 없음, 합계가 루트에 직접 있음
        stock_list: list = []
        if bal_raw:
            bal = bal_raw.get("body") or bal_raw

            if _n(bal.get("return_code", 0)) == 0:
                # 합계 -- 루트 레벨 직접 접근
                tot_eval   = _n(bal.get("tot_evlt_amt", 0))
                tot_pnl    = _n(bal.get("tot_evlt_pl",  0))
                tot_buy    = _n(bal.get("tot_pur_amt",  0))
                total_rate = _f(bal.get("tot_prft_rt",  0))
                if not deposit:
                    deposit = _n(bal.get("prsm_dpst_aset_amt", 0))

            # 개별 종목
            for item in bal.get("acnt_evlt_remn_indv_tot", []):
                stk_cd = str(item.get("stk_cd", "")).strip().lstrip("A")
                if not stk_cd:
                    continue
                qty = _n(item.get("rmnd_qty", 0))
                if qty <= 0:
                    continue
                stock_list.append({
                    "stk_cd":    stk_cd,
                    "stk_nm":    str(item.get("stk_nm", stk_cd)).strip(),
                    "qty":       qty,
                    "buy_price": _n(item.get("buy_uv",     0)),
                    "cur_price": _n(item.get("cur_pric",   0)),
                    "buy_amt":   _n(item.get("buy_amt",    0)),
                    "pnl_amt":   _n(item.get("evlt_ploss", 0)),
                    "pnl_rate":  _f(item.get("prft_rt",    0)),
                    "crd_tp":    str(item.get("crd_tp", "") or "").strip(),
                })

        _log.info(
            "[키움증권] 잔고 조회 완료 -- 총평가 %s원 | 손익 %s원 | 종목 %d개",
            f"{tot_eval:,}", f"{tot_pnl:,}", len(stock_list),
        )
        return {
            "success": True,
            "summary": {
                "tot_eval":     tot_eval,
                "tot_pnl":      tot_pnl,
                "tot_buy":      tot_buy,
                "deposit":      deposit,
                "orderable":    orderable,
                "withdrawable": withdrawable,
                "total_rate":   total_rate,
            },
            "stock_list": stock_list,
            "raw_data":   dep_body,
        }

    # ── 주문 ──────────────────────────────────────────────────────────────
    def send_order(
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
        return _kiwoom_send_order(
            settings, access_token, order_type, code, qty,
            price=price, trde_tp=trde_tp, orig_ord_no=orig_ord_no,
        )

    # ── WebSocket ─────────────────────────────────────────────────────────
    def get_ws_uri(self) -> str:
        return build_broker_urls("kiwoom")["ws_uri"]

    # ── 메타 ──────────────────────────────────────────────────────────────
    @property
    def broker_name(self) -> str:
        return "kiwoom"
