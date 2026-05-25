# -*- coding: utf-8 -*-
"""
개별종목시세 REST API -- ka10086(일별주가).

- ka10086: 장마감 후 확정 종가·등락률·거래대금 조회 (종목별 개별 POST)
- 실시간: 엔진 WebSocket REG·REAL(REST 반복 폴링 아님).
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

import httpx as requests

from backend.app.core.broker_providers import UnifiedStockRecord

if TYPE_CHECKING:
    from backend.app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)


# UnifiedStockRecord는 app.core.broker_providers에서 정의 — 여기서 re-export


def _si(v: Any) -> int:
    try:
        s = str(v).replace(",", "").replace("+", "").strip()
        if not s or s == "-":
            return 0
        return abs(int(float(s)))
    except (ValueError, TypeError):
        return 0


def _si_signed(v: Any) -> int:
    """부호 보존 정수 파싱. pred_rt 등 부호 포함 문자열용."""
    try:
        s = str(v).replace(",", "").replace("+", "").strip()
        if not s or s == "-":
            return 0
        return int(float(s))  # abs() 없음 — 부호 보존
    except (ValueError, TypeError):
        return 0


def _pct(v: Any) -> float:
    try:
        s = str(v).replace("%", "").replace(",", "").strip()
        return float(s) if s else 0.0
    except (ValueError, TypeError):
        return 0.0


def fetch_ka10081_daily_and_5d_data(
    api: "KiwoomRestAPI",
    stk_cd: str,
    qry_dt: str,
    *,
    http_timeout: float = 10.0,
    _raw_cd: str = "",  # 원본 코드 (로그용)
) -> Optional[dict]:
    """
    ka10081(주식일봉차트조회요청) 단건 조회.
    장외 시간 확정 종가·등락률·거래대금만 반환 (5일데이터 제외).
    """
    if not api._ensure_token():
        return None

    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/chart"

    raw = str(stk_cd).strip().upper()
    api_cd = raw
    if raw.isdigit():
        api_cd_sor = f"{raw.zfill(6)[-6:]}_AL"
    else:
        api_cd_sor = raw
    log_cd = _raw_cd or api_cd

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {api._token_info.token}",
        "api-id": "ka10081",
        "cont-yn": "N",
        "next-key": "",
    }
    body = {"stk_cd": api_cd_sor, "base_dt": qry_dt, "upd_stkpc_tp": "1"}

    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=http_timeout)
            if resp.status_code == 429:
                wait = 8 * (attempt + 1)
                _log.warning("[ka10081] 429 -- %ds 대기 후 재시도 (%s/%s)", wait, log_cd, api_cd)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                _log.warning("[ka10081] 실패[HTTP] 코드=%s -- %s (api:%s)", resp.status_code, log_cd, api_cd)
                return None
            data = resp.json()
            rc = str(data.get("return_code") or data.get("rt_cd") or "0")
            if rc not in ("0", "00", ""):
                _log.warning("[ka10081] 실패[API] rc=%s msg=%s -- %s (api:%s)", rc, data.get("return_msg", ""), log_cd, api_cd)
                return None
                
            body_data = data.get("body") or data
            rows = body_data.get("stk_dt_pole_chart_qry") or body_data.get("output") or []
            if not rows or not isinstance(rows, list):
                _log.warning("[ka10081] 실패[데이터없음] 응답행 없음 -- %s (api:%s)", log_cd, api_cd)
                return None

            # 내림차순(최신순) 정렬 보장
            date_key = "stk_bsns_date" if "stk_bsns_date" in rows[0] else "dt" if "dt" in rows[0] else "date"
            if rows and len(rows) > 1 and date_key in rows[0] and date_key in rows[-1]:
                if str(rows[0][date_key]) < str(rows[-1][date_key]):
                    rows = list(reversed(rows))

            latest = rows[0]
            close_px = _si(latest.get("cur_prc") or 0)
            if close_px <= 0:
                _log.warning("[ka10081] 실패[종가0] cur_prc=%s -- %s (api:%s)", latest.get("cur_prc"), log_cd, api_cd)
                return None

            change_raw = _si_signed(latest.get("pred_pre") or 0)
            # 전일종가 = 현재가 - 전일대비 (예: 현재가 1000, 전일대비 100 -> 전일종가는 900)
            prev_close = close_px - change_raw
            if prev_close > 0:
                change_rate = round((change_raw / prev_close) * 100, 2)
            else:
                change_rate = 0.0
                
            sign = "3"
            if change_raw > 0:
                sign = "2"
            elif change_raw < 0:
                sign = "5"

            trade_amt = _si(latest.get("trde_prica") or 0) * 1_000_000
            high_price = _si(latest.get("high_pric") or 0)

            return {
                "cur_price": close_px,
                "sign": sign,
                "change": change_raw,
                "change_rate": change_rate,
                "trade_amount": trade_amt,
                "high_price": high_price,
                "prev_close": prev_close,
            }
        except Exception as e:
            _log.warning("[ka10081] 예외 시도%d %s/%s: %s", attempt + 1, log_cd, api_cd, e)
            # 지수 백오프: 1초, 2초, 4초
            backoff = min(2 ** attempt, 4)
            time.sleep(backoff)
    return None


def fetch_ka10081_daily_5d_data(
    api: "KiwoomRestAPI",
    stk_cd: str,
    qry_dt: str,
    *,
    http_timeout: float = 10.0,
    _raw_cd: str = "",  # 원본 코드 (로그용)
) -> Optional[dict]:
    """
    ka10081(주식일봉차트조회요청) 단건 조회.
    최근 5개 일봉에서 5일 평균 거래대금 및 최고가를 계산 반환.
    """
    if not api._ensure_token():
        return None

    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/chart"

    raw = str(stk_cd).strip().upper()
    api_cd = raw
    if raw.isdigit():
        api_cd_sor = f"{raw.zfill(6)[-6:]}_AL"
    else:
        api_cd_sor = raw
    log_cd = _raw_cd or api_cd

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {api._token_info.token}",
        "api-id": "ka10081",
        "cont-yn": "N",
        "next-key": "",
    }
    body = {"stk_cd": api_cd_sor, "base_dt": qry_dt, "upd_stkpc_tp": "1"}

    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=http_timeout)
            if resp.status_code == 429:
                wait = 8 * (attempt + 1)
                _log.warning("[ka10081-5d] 429 -- %ds 대기 후 재시도 (%s/%s)", wait, log_cd, api_cd)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                _log.warning("[ka10081-5d] 실패[HTTP] 코드=%s -- %s (api:%s)", resp.status_code, log_cd, api_cd)
                return None
            data = resp.json()
            rc = str(data.get("return_code") or data.get("rt_cd") or "0")
            if rc not in ("0", "00", ""):
                _log.warning("[ka10081-5d] 실패[API] rc=%s msg=%s -- %s (api:%s)", rc, data.get("return_msg", ""), log_cd, api_cd)
                return None

            body_data = data.get("body") or data
            rows = body_data.get("stk_dt_pole_chart_qry") or body_data.get("output") or []
            if not rows or not isinstance(rows, list):
                _log.warning("[ka10081-5d] 실패[데이터없음] 응답행 없음 -- %s (api:%s)", log_cd, api_cd)
                return None

            # 내림차순(최신순) 정렬 보장
            date_key = "stk_bsns_date" if "stk_bsns_date" in rows[0] else "dt" if "dt" in rows[0] else "date"
            if rows and len(rows) > 1 and date_key in rows[0] and date_key in rows[-1]:
                if str(rows[0][date_key]) < str(rows[-1][date_key]):
                    rows = list(reversed(rows))

            # 최근 5개 추출
            recent_5 = rows[:5]
            if len(recent_5) < 5:
                _log.warning("[ka10081-5d] 데이터 부족 -- %d개 (필요 5개) -- %s", len(recent_5), log_cd)
                return None

            # 5일 고가/거래대금 추출
            highs_5d = [_si(r.get("high_pric") or 0) for r in recent_5]
            amts_5d_raw = [_si(r.get("trde_prica") or 0) for r in recent_5]  # 백만원 단위
            amts_5d = [amt * 1_000_000 for amt in amts_5d_raw]  # 원단위 변환

            high_price_5d = max(highs_5d) if highs_5d else 0
            # 5일 평균 거래대금: 억원 단위로 저장 (원 ÷ 1억)
            avg_amt_5d = sum(amts_5d) // 5 // 100_000_000 if amts_5d else 0

            return {
                "high_price_5d": high_price_5d,
                "avg_amt_5d": avg_amt_5d,
                "highs_5d_array": highs_5d,
                "amts_5d_array": amts_5d,
            }
        except Exception as e:
            _log.warning("[ka10081-5d] 예외 시도%d %s/%s: %s", attempt + 1, log_cd, api_cd, e)
            backoff = min(2 ** attempt, 4)
            time.sleep(backoff)
    return None


def fetch_ka10081_sector_all(
    api: "KiwoomRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    *,
    interval_sec: float = 0.33,
    on_progress: "Callable[[int, int], None] | None" = None,
    resume_codes: "set[str] | None" = None,
) -> dict[str, dict]:
    """
    개별종목시세 전체 ka10081 순차 조회 -- 장외 시간 확정 데이터 및 5일 캐시 채우기용.
    """
    from backend.app.core.sector_stock_cache import save_progress_cache, load_completed_stocks_from_snapshot

    result: dict[str, dict] = {}
    failed_codes: list[str] = []
    total = len(krx_codes)

    completed_codes = resume_codes or set()
    starting_count = len(completed_codes)

    if completed_codes:
        cached_data = load_completed_stocks_from_snapshot(completed_codes)
        result.update(cached_data)
        _log.info("[ka10081] 이어받기 -- snapshot에서 %d/%d종목 복원 완료",
                  len(cached_data), len(completed_codes))

    if on_progress and starting_count > 0:
        on_progress(starting_count, total)
        _log.info("[ka10081] 이어받기 -- %d/%d종목부터 계속 (복원 %d종목)",
                  starting_count, total, len(result))
    elif on_progress:
        on_progress(0, total)

    remaining_codes = [cd for cd in krx_codes if cd not in completed_codes]

    for cd in remaining_codes:
        detail = fetch_ka10081_daily_5d_data(api, cd, qry_dt, _raw_cd=cd)
        if detail:
            result[cd] = detail
        else:
            failed_codes.append(cd)

        done = len(result)

        if (done - starting_count) % 20 == 0 and done > starting_count:
            save_progress_cache(qry_dt, list(result.keys()), krx_codes, result)
            _pct = int(done / total * 100) if total else 0
            _log.info("[ka10081] 전종목 5일봉 다운로드 중 (%d/%d, %d%%)", done, total, _pct)
            if on_progress:
                on_progress(done, total)

        if done < total:
            time.sleep(interval_sec)

    if result:
        save_progress_cache(qry_dt, list(result.keys()), krx_codes, result)

    if on_progress:
        on_progress(total, total)

    if failed_codes:
        _log.warning("[ka10081] 실패 종목 %d개: %s", len(failed_codes), failed_codes)
    _log.info("[ka10081] 완료 -- 성공 %d/%d종목, 실패 %d종목 (이어받기 %d종목)",
              len(result), total, len(failed_codes), starting_count)
    return result


def fetch_ka10099_stock_name_map(
    api: "KiwoomRestAPI",
    *,
    http_timeout: float = 15.0,
) -> dict[str, str]:
    """
    ka10099 코스피+코스닥 2회 호출 → {6자리 종목코드: 종목명} 매핑 반환.

    장마감 확정 데이터 파이프라인에서 새 엔트리 생성 시 종목명을 채우기 위한 용도.
    실패 시 빈 딕셔너리 (호출자는 종목코드를 종목명 대신 사용).
    """
    if not api._ensure_token():
        _log.warning("[ka10099-name] 토큰 없음 -- 종목명 매핑 생략")
        return {}

    result: dict[str, str] = {}

    for mrkt_tp, label in (("0", "코스피"), ("10", "코스닥")):
        base = api.base_url.rstrip("/")
        url = f"{base}/api/dostk/stkinfo"

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {api._token_info.token}",
            "api-id": "ka10099",
            "cont-yn": "N",
            "next-key": "",
        }
        body = {"mrkt_tp": mrkt_tp}

        for attempt in range(3):
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=http_timeout)
                if resp.status_code == 429:
                    wait = 8 * (attempt + 1)
                    _log.warning("[ka10099-name] 429 %s -- %ds 대기", label, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    _log.warning("[ka10099-name] HTTP %s -- %s", resp.status_code, label)
                    break
                data = resp.json()
                items = data.get("list") or []
                count = 0
                filtered = 0
                filter_reasons: dict[str, int] = {}
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    cd = str(item.get("code") or "").strip().lstrip("A")
                    if not cd:
                        continue
                    # 알파벳 포함 여부에 따라 정규화 분기 (2024년 신규 종목코드 대응)
                    if cd.isdigit():
                        c6 = cd.zfill(6)[-6:]  # 기존 숫자코드: 6자리 패딩
                    else:
                        c6 = cd.upper()  # 알파벳 코드: 원문 대문자 유지

                    # ── 매매 부적격 종목 필터 (입구 컷) ──────────────
                    from backend.app.core.stock_filter import is_excluded
                    excluded, reason = is_excluded(item, c6)
                    if excluded:
                        filtered += 1
                        filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                        continue

                    nm = ""
                    for key in ("name", "hname", "stk_nm"):
                        v = item.get(key)
                        if v and str(v).strip():
                            nm = str(v).strip()
                            break
                    if nm:
                        result[c6] = nm
                        count += 1
                _log.info(
                    "[ka10099-name] %s -- %d종목 종목명 수신, 부적격 제외 %d",
                    label, count, filtered,
                )
                if filter_reasons:
                    _log.info("[ka10099-name] %s 부적격 사유: %s", label, filter_reasons)
                break
            except Exception as e:
                _log.warning("[ka10099-name] 예외 시도%d %s: %s", attempt + 1, label, e)
                # 지수 백오프: 1초, 2초, 4초
                backoff = min(2 ** attempt, 4)
                time.sleep(backoff)

        # 코스피→코스닥 사이 간격
        time.sleep(0.5)

    _log.info("[ka10099-name] 전체 종목명 매핑 -- %d종목", len(result))
    return result


def fetch_ka10099_unified(
    api: "KiwoomRestAPI",
    *,
    http_timeout: float = 15.0,
) -> list[UnifiedStockRecord]:
    """
    ka10099 코스피+코스닥 2회 호출 → 통합 파싱 결과 반환.

    각 item에서 종목코드·종목명·업종명·시장구분을 한꺼번에 추출.
    **is_excluded() 호출 금지** — 모든 item을 무조건 파싱.
    필터링은 파이프라인 Step 3에서 1회만 수행한다.

    [출처: kiwoom_sector_rest.py:186-250 기존 fetch_ka10099_stock_name_map 패턴 재사용]
    """
    if not api._ensure_token():
        _log.warning("[전종목목록] 토큰 없음 -- 조회 생략")
        return []

    result: list[UnifiedStockRecord] = []

    for mrkt_tp, label in (("0", "코스피"), ("10", "코스닥")):
        base = api.base_url.rstrip("/")
        url = f"{base}/api/dostk/stkinfo"

        cont_yn = "N"
        next_key = ""
        market_count = 0

        while True:
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {api._token_info.token}",
                "api-id": "ka10099",
                "cont-yn": cont_yn,
                "next-key": next_key,
            }
            body = {"mrkt_tp": mrkt_tp}

            for attempt in range(3):
                try:
                    resp = requests.post(url, headers=headers, json=body, timeout=http_timeout)
                    if resp.status_code == 429:
                        wait = 8 * (attempt + 1)
                        _log.warning("[전종목목록] 429 %s -- %ds 대기", label, wait)
                        time.sleep(wait)
                        continue
                    if resp.status_code != 200:
                        _log.warning("[전종목목록] HTTP %s -- %s", resp.status_code, label)
                        break
                    data = resp.json()
                    items = data.get("list") or []
                    count = 0
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        cd = str(item.get("code") or "").strip().lstrip("A")
                        if not cd:
                            continue
                        # 알파벳 포함 여부에 따라 정규화 분기 (2024년 신규 종목코드 대응)
                        if cd.isdigit():
                            c6 = cd.zfill(6)[-6:]  # 기존 숫자코드: 6자리 패딩
                        else:
                            c6 = cd.upper()  # 알파벳 코드: 원문 대문자 유지

                        # 종목명 파싱 [출처: kiwoom_sector_rest.py:220-225]
                        nm = ""
                        for key in ("name", "hname", "stk_nm"):
                            v = item.get(key)
                            if v and str(v).strip():
                                nm = str(v).strip()
                                break

                        # 시장구분 [출처: stock_filter.py:62]
                        mc = str(item.get("marketCode") or "").strip()

                        # NXT 중복상장 여부 [출처: kiwoom_rest.py:621]
                        nxt = str(item.get("nxtEnable") or "N").strip().upper() == "Y"

                        result.append(UnifiedStockRecord(
                            code=c6,
                            name=nm,
                            market_code=mc,
                            nxt_enable=nxt,
                            raw_item=item,
                        ))
                        count += 1
                    market_count += count
                    _log.info("[전종목목록] %s -- %d종목 (누적 %d)", label, count, market_count)
                    
                    # 연속조회 확인
                    resp_cont_yn = resp.headers.get("cont-yn", "N")
                    resp_next_key = resp.headers.get("next-key", "")
                    
                    if resp_cont_yn == "Y" and resp_next_key:
                        cont_yn = "Y"
                        next_key = resp_next_key
                        _log.info("[전종목목록] %s -- 연속조회 계속 (next-key: %s)", label, next_key[:20] + "..." if len(next_key) > 20 else next_key)
                        break  # 다음 while 루프로 계속
                    else:
                        # 연속조회 종료
                        cont_yn = "N"
                        next_key = ""
                        break  # while 루프 종료
                except Exception as e:
                    _log.warning("[전종목목록] 예외 시도%d %s: %s", attempt + 1, label, e)
                    # 지수 백오프: 1초, 2초, 4초
                    backoff = min(2 ** attempt, 4)
                    time.sleep(backoff)
            else:
                # 재시도 모두 실패
                _log.warning("[전종목목록] %s -- 재시도 모두 실패, 연속조회 중단", label)
                break
            
            # 연속조회 종료 확인
            if cont_yn == "N":
                break

        # 코스피→코스닥 사이 간격
        time.sleep(0.5)

    _log.info("[전종목목록] 전체 -- %d종목", len(result))
    return result


def fetch_ka10100_stock_info(
    api: "KiwoomRestAPI",
    stk_cd: str,
    *,
    http_timeout: float = 10.0,
) -> Optional[dict]:
    """
    ka10100(종목정보조회) 단건 조회.

    Parameters
    ----------
    api : KiwoomRestAPI
        KiwoomRestAPI 인스턴스
    stk_cd : str
        종목코드 6자리
    http_timeout : float
        HTTP 타임아웃 (초)

    Returns
    -------
    Optional[dict]
        응답 데이터 딕셔너리 또는 None (실패 시)
    """
    if not api._ensure_token():
        _log.warning("[ka10100] 토큰 없음 -- 조회 생략")
        return None

    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/stkinfo"

    cont_yn = "N"
    next_key = ""
    result = None

    while True:
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {api._token_info.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10100",
        }
        body = {"stk_cd": stk_cd}

        for attempt in range(3):
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=http_timeout)
                if resp.status_code == 429:
                    wait = 8 * (attempt + 1)
                    _log.warning("[ka10100] 429 -- %ds 대기 (%s)", wait, stk_cd)
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    _log.warning("[ka10100] HTTP %s -- %s", resp.status_code, stk_cd)
                    break
                data = resp.json()
                result = data
                
                # 연속조회 확인
                resp_cont_yn = resp.headers.get("cont-yn", "N")
                resp_next_key = resp.headers.get("next-key", "")
                
                if resp_cont_yn == "Y" and resp_next_key:
                    cont_yn = "Y"
                    next_key = resp_next_key
                    _log.info("[ka10100] %s -- 연속조회 계속 (next-key: %s)", stk_cd, next_key[:20] + "..." if len(next_key) > 20 else next_key)
                    break  # 다음 while 루프로 계속
                else:
                    # 연속조회 종료
                    cont_yn = "N"
                    next_key = ""
                    break  # while 루프 종료
            except Exception as e:
                _log.warning("[ka10100] 예외 시도%d %s: %s", attempt + 1, stk_cd, e)
                # 지수 백오프: 1초, 2초, 4초
                backoff = min(2 ** attempt, 4)
                time.sleep(backoff)
        else:
            # 재시도 모두 실패
            _log.warning("[ka10100] %s -- 재시도 모두 실패", stk_cd)
            break
        
        # 연속조회 종료 확인
        if cont_yn == "N":
            break

    return result
