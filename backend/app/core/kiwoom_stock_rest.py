# -*- coding: utf-8 -*-
"""
개별종목시세 REST API — ka10086(일별주가).

- ka10086: 장마감 후 확정 종가·등락률·거래대금 조회 (종목별 개별 POST)
- 실시간: 엔진 WebSocket REG·REAL(REST 반복 폴링 아님).
"""
from __future__ import annotations
import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional
from backend.app.core.broker_providers import UnifiedStockRecord
if TYPE_CHECKING:
    from backend.app.core.kiwoom_rest import KiwoomRestAPI

logger = logging.getLogger(__name__)


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


async def fetch_ka10081_daily_price(
    api: "KiwoomRestAPI",
    stk_cd: str,
    qry_dt: str,
    *,
    http_timeout: float = 15.0,
    _raw_cd: str = "",  # 원본 코드 (로그용)
) -> Optional[dict]:
    """
    ka10081(주식일봉차트조회요청) 단건 조회.
    장외 시간 확정 종가·등락률·거래대금만 반환 (1일봉).
    """
    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/chart"

    raw = str(stk_cd).strip().upper()
    api_cd = raw
    if raw.isdigit():
        api_cd_sor = f"{raw.zfill(6)[-6:]}_AL"
    else:
        api_cd_sor = raw
    log_cd = _raw_cd or api_cd

    body = {"stk_cd": api_cd_sor, "base_dt": qry_dt, "upd_stkpc_tp": "1"}

    resp, hit_429 = await api._call_api(
        url=url,
        api_id="ka10081",
        body=body,
        timeout=http_timeout,
        label=f"ka10081-{log_cd}",
    )

    if not resp:
        return None

    try:
        data = resp.json()
        rows = data.get("stk_dt_pole_chart_qry") or []
        if not rows or not isinstance(rows, list):
            logger.warning("[다운로드] 실패(데이터 없음) 응답 없음 — %s (API:%s)", log_cd, api_cd)
            return None

        # 내림차순(최신순) 정렬 보장
        if rows and len(rows) > 1 and "dt" in rows[0] and "dt" in rows[-1]:
            if str(rows[0]["dt"]) < str(rows[-1]["dt"]):
                rows = list(reversed(rows))

        latest = rows[0]
        close_px = _si(latest.get("cur_prc") or 0)
        if close_px <= 0:
            logger.warning("[다운로드] 실패(종가 0) 현재가=%s — %s (API:%s)", latest.get("cur_prc"), log_cd, api_cd)
            return None

        change_raw = _si_signed(latest.get("pred_pre") or 0)
        # 등락률 = 전일대비 / (현재가 - 전일대비) × 100
        prev_close_calc = close_px - change_raw
        if prev_close_calc > 0:
            change_rate = round((change_raw / prev_close_calc) * 100, 2)
        else:
            change_rate = None

        sign = str(latest.get("pred_pre_sig") or "3").strip()

        trade_amt = _si(latest.get("trde_prica") or 0)  # 백만원 단위
        high_price = _si(latest.get("high_pric") or 0)

        return {
            "cur_price": close_px,
            "sign": sign,
            "change": change_raw,
            "change_rate": change_rate,
            "trade_amount": trade_amt,
            "high_price": high_price,
        }
    except Exception as e:
        logger.warning("[다운로드] 데이터 해석 오류 %s/%s: %s", log_cd, api_cd, e)
        return None


async def fetch_ka10081_daily_5d_data(
    api: "KiwoomRestAPI",
    stk_cd: str,
    qry_dt: str,
    *,
    http_timeout: float = 15.0,
    _raw_cd: str = "",  # 원본 코드 (로그용)
) -> Optional[dict]:
    """
    ka10081(주식일봉차트조회요청) 단건 조회.
    최근 5개 일봉에서 5일 평균 거래대금 및 최고가를 계산 반환.
    """
    base = api.base_url.rstrip("/")
    url = f"{base}/api/dostk/chart"

    raw = str(stk_cd).strip().upper()
    api_cd = raw
    if raw.isdigit():
        api_cd_sor = f"{raw.zfill(6)[-6:]}_AL"
    else:
        api_cd_sor = raw
    log_cd = _raw_cd or api_cd

    body = {"stk_cd": api_cd_sor, "base_dt": qry_dt, "upd_stkpc_tp": "1"}

    all_rows: list[dict] = []
    cont_yn = "N"
    next_key = ""

    while True:
        resp, hit_429 = await api._call_api(
            url=url,
            api_id="ka10081",
            body=body,
            timeout=http_timeout,
            cont_yn=cont_yn,
            next_key=next_key,
            label=f"ka10081-5d-{log_cd}",
        )

        if not resp:
            break

        try:
            data = resp.json()
            page_rows = data.get("stk_dt_pole_chart_qry") or []
            if not isinstance(page_rows, list):
                break
            all_rows.extend(page_rows)
        except Exception as e:
            logger.warning("[다운로드] 데이터 해석 오류 %s/%s: %s", log_cd, api_cd, e)
            break

        if len(all_rows) >= 5:
            break

        resp_cont_yn = resp.headers.get("cont-yn", "N")
        resp_next_key = resp.headers.get("next-key", "")
        if resp_cont_yn == "Y" and resp_next_key:
            cont_yn = "Y"
            next_key = resp_next_key
            await asyncio.sleep(0.3)
        else:
            break

    if not all_rows:
        logger.warning("[다운로드] 실패[데이터없음] 응답행 없음 — %s (api:%s)", log_cd, api_cd)
        return None

    try:
        rows = all_rows

        # 내림차순(최신순) 정렬 보장
        if rows and len(rows) > 1 and "dt" in rows[0] and "dt" in rows[-1]:
            if str(rows[0]["dt"]) < str(rows[-1]["dt"]):
                rows = list(reversed(rows))

        # 최근 5개 추출 (신규 상장 종목 지원: 부족한 날짜는 None으로 채움)
        recent_5: list[dict | None] = list(rows[:5])
        if len(recent_5) < 5:
            logger.info("[다운로드] 데이터 부족 — %d개 (필요 5개) — %s (신규 상장으로 간주, 부족한 날짜는 비어있음)", len(recent_5), log_cd)
            while len(recent_5) < 5:
                recent_5.append(None)

        # 5일 고가/거래대금 추출 (데이터 없으면 None)
        highs_5d = [_si(r.get("high_pric")) if r is not None else None for r in recent_5]
        amts_5d = [_si(r.get("trde_prica")) if r is not None else None for r in recent_5]  # 백만원 단위

        return {
            "amts_5d_array": amts_5d,
            "highs_5d_array": highs_5d,
        }
    except Exception as e:
        logger.warning("[다운로드] 데이터 해석 오류 %s/%s: %s", log_cd, api_cd, e)
        return None


async def fetch_ka10081_all_stocks_daily_confirmed(
    api: "KiwoomRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    *,
    interval_sec: float = 0.3,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> dict[str, dict]:
    """
    전체 종목 ka10081 순차 조회 — 확정시세 전용.
    """
    result: dict[str, dict] = {}
    failed_codes: list[str] = []
    total = len(krx_codes)

    if on_progress:
        on_progress(0, total)

    for cd in krx_codes:
        try:
            detail = await fetch_ka10081_daily_price(api, cd, qry_dt, _raw_cd=cd)
            if detail:
                result[cd] = detail
            else:
                failed_codes.append(cd)
        except Exception as e:
            logger.warning("[다운로드] 조회 오류 %s: %s", cd, e)
            failed_codes.append(cd)

        if on_progress:
            on_progress(len(result), total)

        _pct = int(len(result) / total * 100) if total else 0
        logger.info("[다운로드] 진행 중: %d/%d (%d%%)", len(result), total, _pct)

        await asyncio.sleep(interval_sec)

    if on_progress:
        on_progress(total, total)

    if failed_codes:
        logger.warning("[다운로드] 실패 종목 %d개: %s", len(failed_codes), failed_codes)
    logger.info("[다운로드] 다운로드 완료 — 성공 %d/%d종목, 실패 %d종목",
              len(result), total, len(failed_codes))
    return result


async def fetch_ka10081_all_stocks_5day(
    api: "KiwoomRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    *,
    interval_sec: float = 0.3,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> dict[str, dict]:
    """
    전체 종목 ka10081 순차 조회 — 5일봉 전용.
    """
    result: dict[str, dict] = {}
    failed_codes: list[str] = []
    total = len(krx_codes)

    if on_progress:
        on_progress(0, total)

    for cd in krx_codes:
        try:
            detail = await fetch_ka10081_daily_5d_data(api, cd, qry_dt, _raw_cd=cd)
            if detail:
                result[cd] = detail
            else:
                failed_codes.append(cd)
        except Exception as e:
            logger.warning("[다운로드] 조회 오류 %s: %s", cd, e)
            failed_codes.append(cd)

        if on_progress:
            on_progress(len(result), total)

        _pct = int(len(result) / total * 100) if total else 0
        logger.info("[다운로드] 진행 중: %d/%d (%d%%)", len(result), total, _pct)

        await asyncio.sleep(interval_sec)

    if on_progress:
        on_progress(total, total)

    if failed_codes:
        logger.warning("[다운로드] 실패 종목 %d개: %s", len(failed_codes), failed_codes)
    logger.info("[다운로드] 다운로드 완료 — 성공 %d/%d종목, 실패 %d종목",
              len(result), total, len(failed_codes))
    return result


async def fetch_ka10099_unified(
    api: "KiwoomRestAPI",
    *,
    http_timeout: float = 15.0,
) -> list[UnifiedStockRecord]:
    """
    ka10099 코스피+코스닥 2회 호출 → 통합 파싱 결과 반환.

    각 item에서 종목코드·종목명·업종명·시장구분을 한꺼번에 추출.
    **is_excluded() 호출 금지** — 모든 item을 무조건 파싱.
    필터링은 파이프라인 Step 3에서 1회만 수행한다.
    """
    result: list[UnifiedStockRecord] = []

    for mrkt_tp, label in (("0", "코스피"), ("10", "코스닥")):
        base = api.base_url.rstrip("/")
        url = f"{base}/api/dostk/stkinfo"

        cont_yn = "N"
        next_key = ""
        market_count = 0
        retry_count = 0
        max_retries = 3

        while True:
            body = {"mrkt_tp": mrkt_tp}
            resp, hit_429 = await api._call_api(
                url=url,
                api_id="ka10099",
                body=body,
                timeout=http_timeout,
                cont_yn=cont_yn,
                next_key=next_key,
                label=f"ka10099-unified-{label}",
            )

            if not resp:
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning("[다운로드] %s 오류 (시도=%d): 재시도 예정", label, retry_count)
                    await asyncio.sleep(2)
                    continue
                else:
                    logger.warning("[다운로드] %s — 호출 실패 (최대 재시도 초과), 연속 조회 중단", label)
                    break

            try:
                data = resp.json()
                items = data.get("list") or []
                count = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    cd = str(item.get("code") or "").strip().lstrip("A")
                    if not cd:
                        continue
                    if cd.isdigit():
                        c6 = cd.zfill(6)[-6:]
                    else:
                        c6 = cd.upper()

                    # 종목명 파싱
                    nm = ""
                    for key in ("name", "hname", "stk_nm"):
                        v = item.get(key)
                        if v and str(v).strip():
                            nm = str(v).strip()
                            break

                    # 시장구분
                    mc = str(item.get("marketCode") or "").strip()

                    # NXT 중복상장 여부
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
                logger.info("[다운로드] %s — %d종목 (누적 %d)", label, count, market_count)
                
                # 연속 조회 확인
                resp_cont_yn = resp.headers.get("cont-yn", "N")
                resp_next_key = resp.headers.get("next-key", "")
                
                if resp_cont_yn == "Y" and resp_next_key:
                    cont_yn = "Y"
                    next_key = resp_next_key
                    logger.info("[다운로드] %s — 연속 조회 계속 (다음 키: %s)", label, next_key[:20] + "..." if len(next_key) > 20 else next_key)
                else:
                    break  # while 루프 종료
            except Exception as e:
                logger.warning("[다운로드] 데이터 해석 오류 %s: %s", label, e)
                break
            
            # 연속 조회 종료 확인
            if cont_yn == "N":
                break

        # 코스피→코스닥 사이 간격
        await asyncio.sleep(0.5)

    logger.info("[다운로드] 전체 — %d종목", len(result))
    return result


