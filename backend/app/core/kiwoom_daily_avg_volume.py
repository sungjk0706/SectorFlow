# -*- coding: utf-8 -*-
"""
키움 REST API를 통한 5일 평균 거래대금 조회.

키움 전용 REST 호출 함수만 포함한다.
브로커 무관 캐시 함수는 avg_amt_cache.py로 분리되었다.

키움 REST 안내와의 정합:
- ka10081 일봉차트: 거래대금 필드명 trde_prica, 리스트 stk_dt_pole_chart_qry, 최신일이 0번(내림차순).
- ka20002 업종별 종목 시세: acc_trde_prica(당일 누적 거래대금, 백만원 단위).
- 차트 TR은 계정당 분당 호출 한도가 있어 종목 순차 호출 시 간격을 넉넉히 둔다(권고 30~60회/분).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx as requests

# ── 범용 캐시 모듈에서 re-import (하위 호환) ──────────────────────────────
from app.core.avg_amt_cache import (  # noqa: F401
    _CACHE_FILENAME,
    _DEFAULT_CACHE_PATH,
    KA10005_GAP_SEC,
    _kst_today_yyyymmdd,
    _norm_stk,
    load_avg_amt_cache,
    load_avg_amt_cache_v2,
    save_avg_amt_cache,
    save_avg_amt_cache_v2,
    avg_from_v2,
)

if TYPE_CHECKING:
    from app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)


# ── 내부 헬퍼 (REST 응답 파싱) ─────────────────────────────────────────────

def _high_from_row(row: dict[str, Any]) -> int:
    """ka10081 고가(high_pric) 추출. 실패 시 0."""
    v = str(row.get("high_pric", "")).replace(",", "").replace("+", "").strip()
    if v and v != "-":
        try:
            return abs(int(float(v)))
        except (ValueError, TypeError):
            return 0
    return 0


def _amt_from_row(row: dict[str, Any]) -> int:
    """ka10081 거래대금(trde_prica) 우선, 폴백 필드 순서로 추출."""
    for k in (
        "trde_prica",       # ka10081 공식 거래대금 필드
        "acml_tr_pbmn",
        "tr_pbmn",
        "trde_amt",
        "amt",
    ):
        if k not in row:
            continue
        try:
            v = str(row.get(k, "")).replace(",", "").replace("+", "").strip()
            if v and v != "-":
                return abs(int(float(v)))
        except (ValueError, TypeError):
            continue
    return 0


def _daily_rows_from_json(data: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    body = data.get("body") or data
    if not isinstance(body, dict):
        body = data
    for key in (
        "stk_dt_pole_chart_qry",  # ka10081 일봉차트
        "stk_day_pole",
        "stk_stk_day_pole",
        "day_pole",
        "output",
        "stk_dt_pole",
        "chart",
    ):
        rows = body.get(key)
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
    if isinstance(data.get("output"), list):
        return [r for r in data["output"] if isinstance(r, dict)]
    return []


def _ensure_descending_date_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    ka10081 스펙: 인덱스 0번이 최신일(내림차순).
    서버 응답이 오름차순으로 오는 경우를 방어 -- 날짜 필드 비교 후 자동 역순 처리.
    """
    if len(rows) < 2:
        return rows
    date_keys = ("stk_bsns_date", "dt", "date", "bass_dt", "trd_dt")
    d0 = dn = ""
    for k in date_keys:
        if rows[0].get(k):
            d0 = str(rows[0][k]).strip()
            dn = str(rows[-1][k]).strip()
            break
    if d0 and dn and d0 < dn:
        _log.warning(
            "[ka10081] 날짜 오름차순 감지 -- 자동 역순 처리 (d0=%s, d_last=%s)", d0, dn
        )
        return list(reversed(rows))
    return rows


def _avg_last_n_amounts(rows: list[dict[str, Any]], n: int = 5) -> int:
    """rows는 최신일이 앞(0번)인 내림차순(ka10081 스펙). 방어 정렬 후 평균 거래대금 반환."""
    rows = _ensure_descending_date_order(rows)
    amts: list[int] = []
    for r in rows[: max(n * 2, 20)]:
        v = _amt_from_row(r)
        if v > 0:
            amts.append(v)
        if len(amts) >= n:
            break
    if not amts:
        return 0
    return int(sum(amts[:n]) / min(len(amts), n))


# ── REST 호출 ─────────────────────────────────────────────────────────────────

def fetch_daily_5d_data(
    api: "KiwoomRestAPI", stk_cd: str
) -> tuple[list[int], list[int]]:
    """ka10081(_AL) 기반 5일치 거래대금+고가 조회. 1회 호출로 최대 600개 일봉에서 최근 5일 추출.

    Returns:
        (amounts_5d, highs_5d)
        amounts_5d: [백만원, ...] 최신→과거 (최대 5개)
        highs_5d:   [원, ...]   최신→과거 (최대 5개)
        실패 시 ([], []).
    """
    norm = _norm_stk(stk_cd)
    if not norm:
        return [], []
    if not api._ensure_token():
        return [], []
    token = api._token_info.token if api._token_info else ""
    if not token:
        return [], []
    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/chart"
    base_headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
    }

    def _try_chart_data(
        api_id: str,
        body: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[list[int], list[int]]:
        h = {**base_headers, "api-id": api_id}
        if extra_headers:
            h.update(extra_headers)
        try:
            resp = requests.post(url, headers=h, json=body, timeout=22)
            if resp.status_code != 200:
                return [], []
            data = resp.json() if resp.text else {}
            rc = str(data.get("return_code") or data.get("rt_cd") or "0")
            if rc not in ("0", "00", ""):
                return [], []
            rows = _daily_rows_from_json(data)
            rows = _ensure_descending_date_order(rows)
            amts: list[int] = []
            highs: list[int] = []
            for r in rows[: max(5 * 2, 20)]:
                v = _amt_from_row(r)
                if v > 0:
                    amts.append(v)
                    highs.append(_high_from_row(r))
                if len(amts) >= 5:
                    break
            return amts, highs
        except Exception as e:
            _log.debug("[%s] %s try fail: %s", api_id, norm, e)
            return [], []

    # ka10081: stk_cd, base_dt, upd_stkpc_tp 모두 문자열
    ka81_body = {
        "stk_cd": f"{norm}_AL",
        "base_dt": _kst_today_yyyymmdd(),
        "upd_stkpc_tp": "1",
    }
    ka81_headers = {"cont-yn": "N", "next-key": ""}
    amts, highs = _try_chart_data("ka10081", ka81_body, ka81_headers)
    if amts:
        return amts, highs

    _log.warning("[일봉차트] %s -- 5일 거래대금 미수신(ka10081 응답 형식 확인)", norm)
    return [], []


def rolling_update_with_ka20002(
    api: "KiwoomRestAPI",
    existing_v2: dict[str, list[int]],
    industry_codes: list[tuple[str, str]],
    *,
    gap_sec: float = 0.5,
) -> dict[str, list[int]]:
    """ka20002 삭제됨 — 기존 캐시를 그대로 반환."""
    return dict(existing_v2)
