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
from backend.app.core.logger import log_progress, log_progress_end
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


def _si_opt(v: Any) -> int | None:
    """누락·빈 문자열·해석 실패를 0이 아닌 None으로 전달 (W8 폴백 금지).

    설계서 4.1(응답 보존): 숫자로 해석할 수 없는 값은 0으로 바꾸지 않는다.
    "0"은 정상적인 0으로 반환하고, 빈 문자열·None·해석 실패는 None으로 반환.
    """
    try:
        s = str(v).replace(",", "").replace("+", "").strip()
        if not s or s == "-":
            return None
        return abs(int(float(s)))
    except (ValueError, TypeError):
        return None


def _si_signed_opt(v: Any) -> int | None:
    """부호 보존 정수 파싱 (누락 시 None). _si_opt의 부호 보존 버전."""
    try:
        s = str(v).replace(",", "").replace("+", "").strip()
        if not s or s == "-":
            return None
        return int(float(s))  # abs() 없음 — 부호 보존
    except (ValueError, TypeError):
        return None


def _build_ka10081_request(
    api: "KiwoomRestAPI", stk_cd: str, qry_dt: str, _raw_cd: str = ""
) -> tuple[str, dict, str, str]:
    """ka10081 요청 URL/body/로그용 코드 조합 (fetch_ka10081_daily_price/5d_data 공통)."""
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
    return url, body, log_cd, api_cd


def _ensure_descending_by_dt(rows: list[dict]) -> list[dict]:
    """일봉 rows를 내림차순(최신순) 정렬 보장 (dt 기준)."""
    if rows and len(rows) > 1 and "dt" in rows[0] and "dt" in rows[-1]:
        if str(rows[0]["dt"]) < str(rows[-1]["dt"]):
            return list(reversed(rows))
    return rows


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
    장외 시간 확정 종가·등락률·거래대금만 반환 (일봉).
    """
    url, body, log_cd, api_cd = _build_ka10081_request(api, stk_cd, qry_dt, _raw_cd)

    resp, _ = await api._call_api(
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

        rows = _ensure_descending_by_dt(rows)

        latest = rows[0]
        # 누락·빈 문자열·해석 실패를 0이 아닌 None으로 전달 (W8 폴백 금지, 설계서 4.1)
        close_px = _si_opt(latest.get("cur_prc"))
        change_raw = _si_signed_opt(latest.get("pred_pre"))
        trade_amt = _si_opt(latest.get("trde_prica"))  # 백만원 단위
        high_price = _si_opt(latest.get("high_pric"))
        # API가 반환한 일봉의 실제 거래일 (YYYYMMDD) — stock_5d_bars.dt 단일 진실 소스 (P10/P22)
        bar_dt = str(latest.get("dt") or "").strip() or None

        # 누락 감지 — 경고 로그만 유지 (설계서 4.1 응답 보존)
        if close_px is None:
            logger.warning("[다운로드] 숫자값 없음(종가) 현재가=%s — %s (API:%s)", latest.get("cur_prc"), log_cd, api_cd)
        if bar_dt is None:
            logger.warning("[다운로드] 응답 거래일 없음 — %s (API:%s)", log_cd, api_cd)
        if high_price is None:
            # 고가 누락을 종가로 대체하지 않음 (설계서 4.1, 5.2)
            logger.warning("[다운로드] 숫자값 없음(고가) — %s (API:%s)", log_cd, api_cd)
        if trade_amt is None:
            logger.warning("[다운로드] 숫자값 없음(거래대금) — %s (API:%s)", log_cd, api_cd)

        # 등락률 = 전일대비 / (현재가 - 전일대비) × 100
        if close_px is not None and change_raw is not None:
            prev_close_calc = close_px - change_raw
            if prev_close_calc > 0:
                change_rate = round((change_raw / prev_close_calc) * 100, 2)
            else:
                change_rate = None
        else:
            change_rate = None

        sign = str(latest.get("pred_pre_sig") or "3").strip()

        return {
            "dt": bar_dt,
            "cur_price": close_px,
            "sign": sign,
            "change": change_raw,
            "change_rate": change_rate,
            "trade_amount": trade_amt,
            "high_price": high_price,
        }
    except Exception as e:
        logger.warning("[다운로드] 데이터 해석 오류 %s/%s: %s", log_cd, api_cd, e, exc_info=True)
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
    최근 5개 일봉에서 5거래일 평균 거래대금, 최고가, 각 일봉의 거래일(dt)을 반환.
    """
    url, body, log_cd, api_cd = _build_ka10081_request(api, stk_cd, qry_dt, _raw_cd)

    all_rows: list[dict] = []
    cont_yn = "N"
    next_key = ""

    while True:
        resp, _ = await api._call_api(
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
            logger.warning("[다운로드] 데이터 해석 오류 %s/%s: %s", log_cd, api_cd, e, exc_info=True)
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
        rows = _ensure_descending_by_dt(all_rows)

        # 최근 5개 추출 (신규 상장 종목 지원: 부족한 날짜는 None으로 채움)
        recent_5: list[dict | None] = list(rows[:5])
        actual_count = len(recent_5)
        if actual_count < 5:
            logger.info("[다운로드] 데이터 부족 — %d개 (필요 5개) — %s (신규 상장으로 간주, 부족한 날짜는 비어있음)", actual_count, log_cd)
            while len(recent_5) < 5:
                recent_5.append(None)

        # 5거래일 고가/거래대금/거래일 추출 — 누락·해석 실패를 0이 아닌 None으로 전달 (W8 폴백 금지)
        highs_5d = [_si_opt(r.get("high_pric")) if r is not None else None for r in recent_5]
        amts_5d = [_si_opt(r.get("trde_prica")) if r is not None else None for r in recent_5]  # 백만원 단위
        dts_5d = [str(r.get("dt")).strip() or None if r is not None else None for r in recent_5]  # YYYYMMDD

        # 응답 기준일 (가장 최신 일봉의 dt) — 요청 기준일과 분리 (설계서 4.2)
        response_date = dts_5d[0] if dts_5d and dts_5d[0] else None

        # 누락 감지 — 경고 로그만 유지 (설계서 4.1, 4.5)
        if actual_count < 5:
            logger.warning("[다운로드] 5일 자료 부족 — %d개 (필요 5개) — %s", actual_count, log_cd)
        # 개별 일봉의 숫자값 누락 확인
        has_numeric_missing = any(
            (r is not None and (_si_opt(r.get("high_pric")) is None or _si_opt(r.get("trde_prica")) is None))
            for r in recent_5
        )
        if has_numeric_missing:
            logger.warning("[다운로드] 일봉 숫자값 누락 — %s", log_cd)
        if response_date is None:
            logger.warning("[다운로드] 응답 거래일 없음 — %s", log_cd)

        return {
            "amts_5d_array": amts_5d,
            "highs_5d_array": highs_5d,
            "dts_5d_array": dts_5d,
        }
    except Exception as e:
        logger.warning("[다운로드] 데이터 해석 오류 %s/%s: %s", log_cd, api_cd, e, exc_info=True)
        return None


async def _fetch_all_stocks_ka10081(
    api: "KiwoomRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    fetch_fn: "Callable[..., Any]",
    *,
    interval_sec: float = 0.3,
    on_progress: "Callable[[int, int, int, int], None] | None" = None,
) -> dict[str, dict]:
    """전체 종목 ka10081 순차 조회 공통 루프 (확정시세/5거래일 일봉 공통).

    설계서 4.3(부분 성공): 성공 종목만 반환하면서 실패 종목을 잃지 않도록
    종목별 결과와 실패 사유를 함께 반환. 진행률은 처리 수·성공 수·실패 수를 분리 (설계서 4.3).
    """
    success: dict[str, dict] = {}
    failures: dict[str, str] = {}
    total = len(krx_codes)
    processed = 0

    if on_progress:
        on_progress(0, 0, 0, total)

    for cd in krx_codes:
        try:
            detail = await fetch_fn(api, cd, qry_dt, _raw_cd=cd)
            if detail:
                success[cd] = detail
            else:
                failures[cd] = "no_data"
        except Exception as e:
            logger.warning("[다운로드] 조회 오류 %s: %s", cd, e, exc_info=True)
            failures[cd] = f"exception:{type(e).__name__}"

        processed += 1

        if on_progress:
            on_progress(processed, len(success), len(failures), total)

        log_progress("[다운로드]", processed, total, code=cd)

        await asyncio.sleep(interval_sec)

    if on_progress:
        on_progress(total, len(success), len(failures), total)
    log_progress_end()

    if failures:
        logger.warning("[다운로드] 실패 종목 %d개: %s", len(failures), list(failures.keys()))
    logger.info("[다운로드] 다운로드 종료 — 성공 %d/%d종목, 실패 %d종목",
              len(success), total, len(failures))
    return {
        "success": success,
        "failures": failures,
        "total": total,
        "success_count": len(success),
        "failed_count": len(failures),
    }


async def fetch_ka10081_all_stocks_daily_confirmed(
    api: "KiwoomRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    *,
    interval_sec: float = 0.3,
    on_progress: "Callable[[int, int, int, int], None] | None" = None,
) -> dict[str, dict]:
    """전체 종목 ka10081 순차 조회 — 확정시세 전용.

    반환값: {"success": {cd: detail}, "failures": {cd: reason}, "total": int, ...}
    설계서 4.3(부분 성공) — 성공·실패 종목을 함께 반환.
    """
    return await _fetch_all_stocks_ka10081(
        api, krx_codes, qry_dt, fetch_ka10081_daily_price,
        interval_sec=interval_sec, on_progress=on_progress,
    )


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
            resp, _ = await api._call_api(
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
                logger.warning("[다운로드] 데이터 해석 오류 %s: %s", label, e, exc_info=True)
                break
            
            # 연속 조회 종료 확인
            if cont_yn == "N":
                break

        # 코스피→코스닥 사이 간격
        await asyncio.sleep(0.5)

    logger.info("[다운로드] 전체 — %d종목", len(result))
    return result


