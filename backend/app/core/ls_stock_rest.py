from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.app.core.broker_providers import UnifiedStockRecord

if TYPE_CHECKING:
    from backend.app.core.ls_rest import LsRestAPI

_log = logging.getLogger(__name__)

_MARKET_PATH = "/stock/market-data"
_CHART_PATH = "/stock/chart"
_ETC_PATH = "/stock/etc"

_T1404_LABELS: dict[str, str] = {
    "1": "관리종목",
    "2": "불성실공시",
    "3": "투자유의",
    "4": "투자환기",
}
_T1405_LABELS: dict[str, str] = {
    "1": "투자경고",
    "2": "거래정지",
    "3": "정리매매",
    "4": "투자주의",
    "5": "투자위험",
    "6": "위험예고",
    "7": "단기과열",
    "8": "이상급등",
    "9": "상장주식수부족",
}


def _s(value: object) -> str:
    return str(value or "").strip()


def _si(value: object) -> int:
    raw = _s(value).replace(",", "")
    if not raw:
        return 0
    try:
        return abs(int(float(raw)))
    except Exception:
        return 0


def _sf(value: object) -> float:
    raw = _s(value).replace(",", "")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _code(value: object) -> str:
    raw = _s(value).lstrip("A").upper()
    if not raw:
        return ""
    if raw.isdigit():
        return raw.zfill(6)[-6:]
    return raw


def _items(data: dict, block_name: str) -> list[dict]:
    block = data.get(block_name)
    if isinstance(block, list):
        return [item for item in block if isinstance(item, dict)]
    if isinstance(block, dict):
        return [block]
    return []


def _first_item(data: dict, *block_names: str) -> dict:
    for block_name in block_names:
        items = _items(data, block_name)
        if items:
            return items[0]
    return {}


def _price_from_master(item: dict) -> str:
    for key in ("jnilclose", "recprice", "price"):
        value = _s(item.get(key))
        if _si(value) > 0:
            return value
    return ""


def _market_code(item: dict) -> str:
    etfgubun = _s(item.get("etfgubun"))
    if etfgubun == "1":
        return "8"
    if etfgubun == "2":
        return "60"
    gubun = _s(item.get("gubun"))
    if gubun == "1":
        return "0"
    if gubun == "2":
        return "10"
    return gubun


async def _call_pages(
    api: "LsRestAPI",
    path: str,
    tr_cd: str,
    body: dict,
    out_block: str,
    *,
    cts_block: str = "",
    cts_field: str = "cts_shcode",
    interval_sec: float = 1.0,
    timeout: float = 15.0,
    max_pages: int = 100,
) -> list[dict]:
    result: list[dict] = []
    tr_cont = "N"
    tr_cont_key = ""
    in_block = next(iter(body), "")

    for _ in range(max_pages):
        res = await api.call_tr(
            path,
            tr_cd,
            body,
            tr_cont=tr_cont,
            tr_cont_key=tr_cont_key,
            timeout=timeout,
        )
        if not res:
            break

        data = res.get("data") or {}
        result.extend(_items(data, out_block))

        next_cont = _s(res.get("tr_cont")).upper()
        next_key = _s(res.get("tr_cont_key"))
        if next_cont != "Y" or not next_key:
            break

        if cts_block and in_block:
            cts_raw = _first_item(data, cts_block).get(cts_field)
            if isinstance(cts_raw, str):
                cts_value = _s(cts_raw)
                if not cts_value:
                    _log.warning("[LS부적격목록] %s 연속조회 키 누락 — %s.%s 비어있음, 페이지 중단", tr_cd, cts_block, cts_field)
                    break
            else:
                cts_value = cts_raw
                if cts_value is None:
                    _log.warning("[LS부적격목록] %s 연속조회 키 누락 — %s.%s 비어있음, 페이지 중단", tr_cd, cts_block, cts_field)
                    break
            body[in_block][cts_field] = cts_value

        tr_cont = "Y"
        tr_cont_key = next_key
        await asyncio.sleep(max(interval_sec, 1.0))
    else:
        _log.warning("[LS부적격목록] %s 최대 페이지(%d) 도달 — 강제 중단", tr_cd, max_pages)

    return result


async def fetch_ls_t8436_unified(api: "LsRestAPI", *, http_timeout: float = 15.0) -> list[UnifiedStockRecord]:
    body = {"t8436InBlock": {"gubun": "0"}}
    res = await api.call_tr(_ETC_PATH, "t8436", body, timeout=http_timeout)
    if not res:
        return []

    data = res.get("data") or {}
    records: list[UnifiedStockRecord] = []
    for item in _items(data, "t8436OutBlock"):
        code = _code(item.get("shcode") or item.get("expcode"))
        if not code:
            continue
        name = _s(item.get("hname"))
        market_code = _market_code(item)
        last_price = _price_from_master(item)
        raw_item = dict(item)
        if _s(item.get("spac_gubun")).upper() == "Y" and "스팩" not in name:
            name = f"{name}스팩"
        raw_item.update({
            "code": code,
            "name": name,
            "stk_nm": name,
            "marketCode": market_code,
            "lastPrice": last_price,
            "nxtEnable": "",
        })
        records.append(UnifiedStockRecord(
            code=code,
            name=name,
            market_code=market_code,
            nxt_enable=False,
            raw_item=raw_item,
        ))
    _log.info("[LS전종목목록] t8436 — %d종목", len(records))
    return records


async def fetch_ls_t1404_codes(api: "LsRestAPI") -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for gubun in ("0", "1", "2"):
        for jongchk in ("1", "2", "3", "4"):
            label = _T1404_LABELS.get(jongchk, f"t1404-{jongchk}")
            body = {"t1404InBlock": {"gubun": gubun, "jongchk": jongchk, "cts_shcode": ""}}
            items = await _call_pages(api, _MARKET_PATH, "t1404", body, "t1404OutBlock1", cts_block="t1404OutBlock")
            for item in items:
                code = _code(item.get("shcode"))
                if code:
                    result.setdefault(code, []).append(label)
            _log.info("[LS부적격목록] t1404 gubun=%s jongchk=%s(%s) — %d종목", gubun, jongchk, label, len(items))
            await asyncio.sleep(1.0)
    return result


async def fetch_ls_t1405_codes(api: "LsRestAPI") -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for gubun in ("0", "1", "2"):
        for jongchk in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            label = _T1405_LABELS.get(jongchk, f"t1405-{jongchk}")
            body = {"t1405InBlock": {"gubun": gubun, "jongchk": jongchk, "cts_shcode": ""}}
            items = await _call_pages(api, _MARKET_PATH, "t1405", body, "t1405OutBlock1", cts_block="t1405OutBlock")
            for item in items:
                code = _code(item.get("shcode"))
                if code:
                    result.setdefault(code, []).append(label)
            _log.info("[LS부적격목록] t1405 gubun=%s jongchk=%s(%s) — %d종목", gubun, jongchk, label, len(items))
            await asyncio.sleep(1.0)
    return result


async def fetch_ls_t1410_codes(api: "LsRestAPI") -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for gubun in ("0", "1", "2"):
        body = {"t1410InBlock": {"gubun": gubun, "cts_shcode": ""}}
        items = await _call_pages(api, _MARKET_PATH, "t1410", body, "t1410OutBlock1", cts_block="t1410OutBlock")
        for item in items:
            code = _code(item.get("shcode"))
            if code:
                result.setdefault(code, []).append("초저유동성")
        _log.info("[LS부적격목록] t1410 gubun=%s — %d종목", gubun, len(items))
        await asyncio.sleep(1.0)
    return result


_T1411_JKRATE_LABELS: dict[str, str] = {
    "5": "증거금40%",
    "1": "증거금100%",
}


async def fetch_ls_t1411_codes(api: "LsRestAPI") -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for gubun in ("0", "1", "2"):
        for jkrate, label in _T1411_JKRATE_LABELS.items():
            body = {"t1411InBlock": {"gubun": gubun, "jongchk": "1", "jkrate": jkrate, "shcode": "", "idx": 0}}
            items = await _call_pages(api, _ETC_PATH, "t1411", body, "t1411OutBlock1", cts_block="t1411OutBlock", cts_field="idx")
            for item in items:
                code = _code(item.get("shcode"))
                if code:
                    result.setdefault(code, []).append(label)
            _log.info("[LS부적격목록] t1411 gubun=%s jkrate=%s(%s) — %d종목", gubun, jkrate, label, len(items))
            await asyncio.sleep(1.0)
    return result


async def fetch_ls_ineligible_codes(api: "LsRestAPI") -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    fetchers = (fetch_ls_t1404_codes, fetch_ls_t1405_codes, fetch_ls_t1410_codes, fetch_ls_t1411_codes)
    _log.info("[LS부적격목록] 4개 TR 동시 조회 시작 (TR별 독립 TPS)")
    results = await asyncio.gather(
        *[fetcher(api) for fetcher in fetchers],
        return_exceptions=True,
    )
    for fetcher, res in zip(fetchers, results):
        if isinstance(res, Exception):
            _log.warning("[LS부적격목록] %s 실패: %s", fetcher.__name__, res)
            continue
        for code, labels in res.items():
            result.setdefault(code, []).extend(labels)
        _log.info("[LS부적격목록] %s 완료 — %d종목", fetcher.__name__, len(res))
    _log.info("[LS부적격목록] 통합 — %d종목", len(result))
    return result


async def fetch_ls_all_stocks_unified(api: "LsRestAPI", *, http_timeout: float = 15.0) -> list[UnifiedStockRecord]:
    records = await fetch_ls_t8436_unified(api, http_timeout=http_timeout)
    if not records:
        return []
    ineligible_map = await fetch_ls_ineligible_codes(api)
    if ineligible_map:
        for record in records:
            labels = ineligible_map.get(record.code)
            if labels:
                state_str = "|".join(dict.fromkeys(labels))
                record.raw_item["state"] = state_str
    _log.info("[LS전종목목록] 전종목 반환 — %d종목 (부적격 state 주입 %d종목)", len(records), len(ineligible_map))
    return records


def _daily_rows(data: dict) -> list[dict]:
    for block_name in ("t8451OutBlock1", "t8410OutBlock1"):
        rows = _items(data, block_name)
        if rows:
            return rows
    return []


def _close_value(item: dict) -> int:
    for key in ("close", "price", "recprice", "jongga"):
        value = _si(item.get(key))
        if value > 0:
            return value
    return 0


def _change_value(item: dict, close_px: int) -> int:
    for key in ("change", "diff", "signvalue"):
        raw = _s(item.get(key)).replace(",", "")
        if raw:
            try:
                return int(float(raw))
            except Exception:
                pass
    prev_close = _si(item.get("jnilclose") or item.get("preclose"))
    if close_px > 0 and prev_close > 0:
        return close_px - prev_close
    return 0


def _trade_amount(item: dict) -> int:
    for key in ("value", "trvalue", "trde_prica", "amount"):
        value = _si(item.get(key))
        if value > 0:
            return value
    return 0


def _daily_dict(row: dict) -> dict | None:
    close_px = _close_value(row)
    if close_px <= 0:
        return None
    change = _change_value(row, close_px)
    sign = "3"
    if change > 0:
        sign = "2"
    elif change < 0:
        sign = "5"
    prev_close = close_px - change
    change_rate = round((change / prev_close) * 100, 2) if prev_close > 0 else _sf(row.get("diff"))
    return {
        "cur_price": close_px,
        "sign": sign,
        "change": change,
        "change_rate": change_rate,
        "trade_amount": _trade_amount(row),
        "high_price": _si(row.get("high") or row.get("high_pric")),
    }


async def fetch_ls_daily_price(api: "LsRestAPI", stk_cd: str, qry_dt: str) -> dict | None:
    code = _code(stk_cd)
    if not code:
        return None
    body = {
        "t8451InBlock": {
            "shcode": code,
            "gubun": "2",
            "qrycnt": 1,
            "sdate": qry_dt,
            "edate": qry_dt,
            "cts_date": "",
            "comp_yn": "N",
            "sujung": "Y",
            "exchgubun": "K",
        }
    }
    res = await api.call_tr(_CHART_PATH, "t8451", body, timeout=15.0)
    if not res:
        return None
    rows = _daily_rows(res.get("data") or {})
    if not rows:
        return None
    return _daily_dict(rows[0])


async def fetch_ls_daily_price_t8410(api: "LsRestAPI", stk_cd: str, qry_dt: str) -> dict | None:
    code = _code(stk_cd)
    if not code:
        return None
    body = {
        "t8410InBlock": {
            "shcode": code,
            "gubun": "2",
            "qrycnt": 1,
            "sdate": qry_dt,
            "edate": qry_dt,
            "cts_date": "",
            "comp_yn": "N",
            "sujung": "Y",
        }
    }
    res = await api.call_tr(_CHART_PATH, "t8410", body, timeout=15.0)
    if not res:
        return None
    rows = _daily_rows(res.get("data") or {})
    if not rows:
        return None
    return _daily_dict(rows[0])


async def fetch_ls_stock_5day_data(api: "LsRestAPI", stk_cd: str, qry_dt: str) -> dict | None:
    code = _code(stk_cd)
    if not code:
        return None
    body = {
        "t8451InBlock": {
            "shcode": code,
            "gubun": "2",
            "qrycnt": 5,
            "sdate": "",
            "edate": qry_dt,
            "cts_date": "",
            "comp_yn": "N",
            "sujung": "Y",
            "exchgubun": "K",
        }
    }
    res = await api.call_tr(_CHART_PATH, "t8451", body, timeout=15.0)
    if not res:
        return None
    rows = _daily_rows(res.get("data") or {})[:5]
    if not rows:
        return None
    return {
        "amts_5d_array": [_trade_amount(row) for row in rows],
        "highs_5d_array": [_si(row.get("high") or row.get("high_pric")) for row in rows],
    }


async def fetch_ls_stock_5day_data_t8410(api: "LsRestAPI", stk_cd: str, qry_dt: str) -> dict | None:
    code = _code(stk_cd)
    if not code:
        return None
    body = {
        "t8410InBlock": {
            "shcode": code,
            "gubun": "2",
            "qrycnt": 5,
            "sdate": "",
            "edate": qry_dt,
            "cts_date": "",
            "comp_yn": "N",
            "sujung": "Y",
        }
    }
    res = await api.call_tr(_CHART_PATH, "t8410", body, timeout=15.0)
    if not res:
        return None
    rows = _daily_rows(res.get("data") or {})[:5]
    if not rows:
        return None
    return {
        "amts_5d_array": [_trade_amount(row) for row in rows],
        "highs_5d_array": [_si(row.get("high") or row.get("high_pric")) for row in rows],
    }


async def fetch_ls_all_stocks_daily_confirmed(
    api: "LsRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    interval_sec: float = 1.0,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    total = len(krx_codes)
    gap = max(interval_sec, 0.5)
    for idx, raw_code in enumerate(krx_codes, start=1):
        code = _code(raw_code)
        if not code:
            if on_progress:
                on_progress(idx, total)
            continue
        try:
            if idx % 2 == 1:
                data = await fetch_ls_daily_price(api, code, qry_dt)
            else:
                data = await fetch_ls_daily_price_t8410(api, code, qry_dt)
            if data:
                result[code] = data
        except Exception as exc:
            _log.warning("[LS일봉] %s 조회 실패: %s", code, exc)
        if on_progress:
            on_progress(idx, total)
        if idx < total:
            await asyncio.sleep(gap)
    _log.info("[LS일봉] 완료 — 요청 %d, 성공 %d (t8451/t8410 교차 호출)", total, len(result))
    return result


async def fetch_ls_all_stocks_5day(
    api: "LsRestAPI",
    krx_codes: list[str],
    qry_dt: str,
    interval_sec: float = 1.0,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    total = len(krx_codes)
    gap = max(interval_sec, 0.5)
    for idx, raw_code in enumerate(krx_codes, start=1):
        code = _code(raw_code)
        if not code:
            if on_progress:
                on_progress(idx, total)
            continue
        try:
            if idx % 2 == 1:
                data = await fetch_ls_stock_5day_data(api, code, qry_dt)
            else:
                data = await fetch_ls_stock_5day_data_t8410(api, code, qry_dt)
            if data:
                result[code] = data
        except Exception as exc:
            _log.warning("[LS5일봉] %s 조회 실패: %s", code, exc)
        if on_progress:
            on_progress(idx, total)
        if idx < total:
            await asyncio.sleep(gap)
    _log.info("[LS5일봉] 완료 — 요청 %d, 성공 %d (t8451/t8410 교차 호출)", total, len(result))
    return result
