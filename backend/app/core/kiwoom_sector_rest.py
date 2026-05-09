# -*- coding: utf-8 -*-
"""
개별종목시세 REST API -- ka10086(일별주가).

- ka10086: 장마감 후 확정 종가·등락률·거래대금 조회 (종목별 개별 POST)
- 실시간: 엔진 WebSocket REG·REAL(REST 반복 폴링 아님).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

import httpx as requests

from app.core.broker_providers import UnifiedStockRecord
from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd, _base_stk_cd

if TYPE_CHECKING:
    from app.core.kiwoom_rest import KiwoomRestAPI

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


def fetch_ka10086_daily_price(
    api: "KiwoomRestAPI",
    stk_cd: str,
    qry_dt: str,
    *,
    http_timeout: float = 10.0,
    _raw_cd: str = "",  # 원본 코드 (로그용)
) -> Optional[dict]:
    """
    ka10086(일별주가요청) 단건 조회.
    장외 시간에도 전일 확정 종가·등락률·거래대금 반환.
    """
    if not api._ensure_token():
        return None

    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/mrkcond"

    raw = str(stk_cd).strip().upper()
    # 알파벳 코드(0082N0 등)도 그대로 사용, 변환하지 않음
    # 키움 API는 6자리 숫자 코드와 알파벳 코드 모두 지원
    api_cd = raw
    # SOR(KRX+NXT 합산) 데이터 조회: _AL 접미사 추가 (숫자 코드에만 적용)
    # 알파벳 코드는 이미 SOR 데이터로 조회됨
    if raw.isdigit():
        api_cd_sor = f"{raw.zfill(6)[-6:]}_AL"
    else:
        api_cd_sor = raw  # 알파벳 코드는 그대로 사용
    log_cd = _raw_cd or api_cd  # 로그용 코드 (원본 우선)

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {api._token_info.token}",
        "api-id": "ka10086",
        "cont-yn": "N",
        "next-key": "",
    }
    body = {"stk_cd": api_cd_sor, "qry_dt": qry_dt, "indc_tp": "1"}

    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=http_timeout)
            if resp.status_code == 429:
                wait = 8 * (attempt + 1)
                _log.warning("[ka10086] 429 -- %ds 대기 후 재시도 (%s/%s)", wait, log_cd, api_cd)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                _log.warning("[ka10086] 실패[HTTP] 코드=%s -- %s (api:%s)", resp.status_code, log_cd, api_cd)
                return None
            data = resp.json()
            rc = str(data.get("return_code", "0"))
            if rc not in ("0", "00"):
                _log.warning("[ka10086] 실패[API] rc=%s msg=%s -- %s (api:%s)", rc, data.get("return_msg", ""), log_cd, api_cd)
                return None
            rows = data.get("daly_stkpc") or []
            if not rows or not isinstance(rows, list):
                _log.warning("[ka10086] 실패[데이터없음] 응답행 없음 -- %s (api:%s)", log_cd, api_cd)
                return None
            row = rows[0]
            close_px = _si(row.get("clsprc") or row.get("close_pric") or row.get("cur_prc") or 0)
            if close_px <= 0:
                _log.warning("[ka10086] 실패[종가0] clsprc=%s -- %s (api:%s)", row.get("clsprc"), log_cd, api_cd)
                return None
            sign = str(row.get("pred_pre_sig") or row.get("sign") or "3").strip() or "3"
            change_raw = _si_signed(row.get("pred_rt") or row.get("change") or 0)
            change_rate = _pct(row.get("flu_rt") or row.get("change_rate") or 0)
            trade_amt = _si(row.get("amt_mn") or 0) * 1_000_000
            high_price = _si(row.get("high_pric") or 0)
            return {
                "cur_price": close_px,
                "sign": sign,
                "change": change_raw,
                "change_rate": change_rate,
                "trade_amount": trade_amt,
                "high_price": high_price,
                "prev_close": 0,
            }
        except Exception as e:
            _log.warning("[ka10086] 예외 시도%d %s/%s: %s", attempt + 1, log_cd, api_cd, e)
            time.sleep(0.3 * (attempt + 1))
    return None


def fetch_ka10086_sector_all(
    api: "KiwoomRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    *,
    interval_sec: float = 0.3,
    on_progress: "Callable[[int, int], None] | None" = None,
    resume_codes: "set[str] | None" = None,
) -> dict[str, dict]:
    """
    개별종목시세 전체 ka10086 순차 조회 -- 장외 시간 확정 데이터 채우기용.

    Args:
        resume_codes: 이전 세션에서 완료된 종목 코드들.
                      완료된 종목은 API 호출을 건너뛰고 snapshot에서 데이터 복원.
    """
    from app.core.sector_stock_cache import save_progress_cache, load_completed_stocks_from_snapshot

    result: dict[str, dict] = {}
    failed_codes: list[str] = []  # 실패 종목 추적
    total = len(krx_codes)

    # 이어받기: 완료된 종목 코드들
    completed_codes = resume_codes or set()
    starting_count = len(completed_codes)

    # 완료된 종목 데이터를 snapshot에서 복원
    if completed_codes:
        cached_data = load_completed_stocks_from_snapshot(completed_codes)
        result.update(cached_data)
        _log.info("[ka10086] 이어받기 -- snapshot에서 %d/%d종목 복원 완료",
                  len(cached_data), len(completed_codes))

    # 초기 진행률 표시 (이어받기인 경우)
    if on_progress and starting_count > 0:
        on_progress(starting_count, total)
        _log.info("[ka10086] 이어받기 -- %d/%d종목부터 계속 (복원 %d종목)",
                  starting_count, total, len(result))
    elif on_progress:
        on_progress(0, total)

    # 미완료 종목만 API 호출
    remaining_codes = [cd for cd in krx_codes if cd not in completed_codes]

    for cd in remaining_codes:
        detail = fetch_ka10086_daily_price(api, cd, qry_dt, _raw_cd=cd)  # 원본 코드 전달
        if detail:
            result[cd] = detail
        else:
            failed_codes.append(cd)  # 실패 종목 기록

        done = len(result)

        # 20종목마다 진행 저장 (이어받기 가능하도록)
        if (done - starting_count) % 20 == 0 and done > starting_count:
            save_progress_cache(qry_dt, list(result.keys()), krx_codes, result)
            _pct = int(done / total * 100) if total else 0
            _log.info("[ka10086] 전종목 확정시세 다운로드 중 (%d/%d, %d%%)", done, total, _pct)
            if on_progress:
                on_progress(done, total)

        # 마지막 종목이 아니면 간격 대기
        if done < total:
            time.sleep(interval_sec)

    # 마지막 진행 저장 (완료된 모든 종목)
    if result:
        save_progress_cache(qry_dt, list(result.keys()), krx_codes, result)

    if on_progress:
        on_progress(total, total)

    # 실패 종목 로그 출력 (분석용)
    if failed_codes:
        _log.warning("[ka10086] 실패 종목 %d개: %s", len(failed_codes), failed_codes)
    _log.info("[ka10086] 완료 -- 성공 %d/%d종목, 실패 %d종목 (이어받기 %d종목)",
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
                    from app.core.stock_filter import is_excluded
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
                time.sleep(0.5 * (attempt + 1))

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
                _log.info("[전종목목록] %s -- %d종목", label, count)
                break
            except Exception as e:
                _log.warning("[전종목목록] 예외 시도%d %s: %s", attempt + 1, label, e)
                time.sleep(0.5 * (attempt + 1))

        # 코스피→코스닥 사이 간격
        time.sleep(0.5)

    _log.info("[전종목목록] 전체 -- %d종목", len(result))
    return result
