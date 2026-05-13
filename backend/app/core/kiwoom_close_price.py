# -*- coding: utf-8 -*-
"""
ka10086(일별주가요청)으로 직전 영업일 확정 종가 조회.

키움 공식 답변 기준:
- ka10001은 장마감 후 cur_prc 미반환 -> 종가 조회 불가.
- ka10086 daly_stkpc[0].close_pric = 직전 영업일 확정 종가 (HTS와 일치).
- qry_dt에 비영업일 입력 시 빈 배열 반환 -> 앱에서 직전 영업일을 계산해서 요청.
- close_pric, pred_rt, flu_rt 모두 부호 포함 문자열 -> 절댓값 처리 필요.
- amt_mn: 거래대금 백만원 단위.
- 종목당 1회 호출, 호출 간격 1.05초 권장(분당 ~57회).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

import httpx as requests

if TYPE_CHECKING:
    from app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)

KA10086_GAP_SEC = 1.05  # 분당 ~57회 이하


try:
    from zoneinfo import ZoneInfo
    def _kst_today() -> datetime:
        return datetime.now(ZoneInfo("Asia/Seoul"))
except Exception:
    def _kst_today() -> datetime:
        return datetime.now()


def _kst_today_str() -> str:
    dt = _kst_today()
    return dt.strftime("%Y%m%d")


def _prev_weekday_yyyymmdd(from_date: Optional[str] = None) -> str:
    """
    직전 영업일 날짜 반환 -- YYYYMMDD 형식 (주말·공휴일 건너뜀).
    키움 REST API는 비영업일 날짜 입력 시 빈 배열을 반환하므로
    앱에서 직전 영업일을 계산해서 요청해야 함.
    from_date: None이면 오늘 기준.
    """
    from app.core.trading_calendar import prev_business_date, kst_today
    from datetime import datetime as _dt

    if from_date:
        try:
            base = _dt.strptime(from_date, "%Y%m%d").date()
        except ValueError:
            base = kst_today()
    else:
        base = kst_today()

    # 오늘이고 장 시작 전(09:00 이전)이면 어제부터 시작
    now = _kst_today()
    now_naive = now.replace(tzinfo=None) if hasattr(now, 'replace') else now
    if base == now_naive.date() and now_naive.hour < 9:
        base = base

    return prev_business_date(base).strftime("%Y%m%d")


def _parse_close_row(row: dict[str, Any]) -> Optional[dict]:
    """
    ka10086 daly_stkpc 한 행에서 종가·대비·등락률·거래대금 추출.
    키움 공식: close_pric, pred_rt, flu_rt 모두 부호 포함 문자열 -> 절댓값.
    amt_mn: 백만원 단위.
    """
    if not isinstance(row, dict):
        return None

    def _abs_int(v) -> int:
        try:
            s = str(v or "").replace(",", "").replace("+", "").strip()
            if not s or s == "-":
                return 0
            return abs(int(float(s)))
        except (ValueError, TypeError):
            return 0

    def _signed_float(v) -> float:
        try:
            s = str(v or "").replace(",", "").replace("%", "").strip()
            if not s:
                return 0.0
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    def _sign_from_str(v) -> str:
        """부호 문자열에서 키움 sign 코드 반환: 2=상승, 5=하락, 3=보합."""
        s = str(v or "").strip()
        if s.startswith("+") and _abs_int(v) > 0:
            return "2"
        if s.startswith("-") and _abs_int(v) > 0:
            return "5"
        return "3"

    close = _abs_int(row.get("close_pric"))
    if close <= 0:
        return None

    pred_rt_raw = row.get("pred_rt", "0")
    change = _abs_int(pred_rt_raw)
    sign = _sign_from_str(pred_rt_raw)
    rate = _signed_float(row.get("flu_rt", "0"))
    # amt_mn: 백만원 -> 억원 표시는 UI에서 처리, 여기선 원 단위로 변환
    amt_mn = _abs_int(row.get("amt_mn", "0"))
    trade_amount = amt_mn * 1_000_000  # 백만원 -> 원

    return {
        "cur_price":    close,
        "change":       change,
        "change_rate":  rate,
        "sign":         sign,
        "trade_amount": trade_amount,
        "date":         str(row.get("date", "")).strip(),
    }


def fetch_close_price_ka10086(
    api: "KiwoomRestAPI",
    stk_cd: str,
    qry_dt: Optional[str] = None,
) -> Optional[dict]:
    """
    ka10086으로 직전 영업일 확정 종가 조회.
    qry_dt: None이면 직전 평일 자동 계산.
    반환: {cur_price, change, change_rate, sign, trade_amount, date} 또는 None.
    """
    norm = str(stk_cd or "").strip().lstrip("A")
    if not norm:
        return None
    if not api._ensure_token():
        return None
    token = api._token_info.token if api._token_info else ""
    if not token:
        return None

    target_dt = qry_dt or _prev_weekday_yyyymmdd()
    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/mrkcond"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka10086",
        "cont-yn": "N",
        "next-key": "",
    }
    body = {
        "stk_cd": norm,
        "qry_dt": target_dt,
        "indc_tp": "1",  # 1: 금액(백만원)
    }

    # 빈 응답 방어: 임시공휴일 등 라이브러리 미반영 케이스 대비 최대 5회 재시도
    for attempt in range(5):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=15)
            if resp.status_code == 429:
                _log.warning("[ka10086] 429 rate limit -- %s", norm)
                time.sleep(3)
                continue
            if resp.status_code != 200:
                _log.debug("[ka10086] HTTP %s -- %s", resp.status_code, norm)
                return None
            data = resp.json()
            rows = data.get("daly_stkpc") or []
            if not rows:
                # 데이터 없음 -> 하루 앞으로 재시도 (임시공휴일 등 방어)
                dt = datetime.strptime(target_dt, "%Y%m%d") - timedelta(days=1)
                target_dt = dt.strftime("%Y%m%d")
                body["qry_dt"] = target_dt
                _log.debug("[ka10086] 데이터 없음 -- %s 재시도 qry_dt=%s", norm, target_dt)
                continue
            row = rows[0]  # 최신일이 0번(내림차순)
            result = _parse_close_row(row)
            if result:
                _log.debug("[ka10086] %s 종가=%s 날짜=%s", norm, result["cur_price"], result["date"])
            return result
        except Exception as e:
            _log.debug("[ka10086] %s 예외: %s", norm, e)
            return None

    _log.warning("[ka10086] %s -- 5회 시도 후 데이터 없음", norm)
    return None


def fetch_close_prices_sequential(
    api: "KiwoomRestAPI",
    codes: list[str],
    *,
    gap_sec: float = KA10086_GAP_SEC,
    qry_dt: Optional[str] = None,
) -> dict[str, dict]:
    """
    전체 종목 확정 종가 순차 조회.
    반환: {정규화종목코드: {cur_price, change, change_rate, sign, trade_amount, date}}
    """
    out: dict[str, dict] = {}
    target_dt = qry_dt or _prev_weekday_yyyymmdd()
    total = len(codes)

    _log.info("[ka10086] 확정 종가 순차 조회 시작 -- %d종목 qry_dt=%s", total, target_dt)

    for i, raw in enumerate(codes):
        norm = str(raw or "").strip().lstrip("A")
        if not norm:
            continue
        result = fetch_close_price_ka10086(api, norm, qry_dt=target_dt)
        if result:
            out[norm] = result
        if i + 1 < total:
            time.sleep(gap_sec)
        if (i + 1) % 20 == 0 or i + 1 == total:
            _log.info("[ka10086] %d/%d 완료 -- 성공 %d종목", i + 1, total, len(out))

    _log.info("[ka10086] 확정 종가 조회 완료 -- %d/%d종목", len(out), total)
    return out
