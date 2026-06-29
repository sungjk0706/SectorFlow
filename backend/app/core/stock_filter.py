from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re
# -*- coding: utf-8 -*-
"""
매매 부적격 종목 필터 — ka10099 응답 기반 입구 컷.

판정 기준:
  0. marketCode ∉ {"0","10"} → 비주식 종목 (ETF/ETN/ELW/리츠 등)
  1. orderWarning ≠ "0"  → 투자경고/위험/주의/정리매매/단기과열
  2. state 에 위험 키워드 포함 → 관리종목, 거래정지, 불성실공시, 상장폐지, 정리매매, 증거금100%
  3. 종목코드 끝자리 ≠ "0" → 우선주
  4. 종목명에 "스팩" 포함 → SPAC (기업인수목적회사)
  5. auditInfo ≠ "" AND ≠ "정상" → 감리지정/감리비정상/투자주의환기종목
"""


# marketCode 화이트리스트 — 코스피("0")와 코스닥("10")만 매매 적격
_ALLOWED_MARKET_CODES: set[str] = {"0", "10"}

# marketCode → 라벨 매핑 (차단 사유 표시용)
_MARKET_CODE_LABELS: dict[str, str] = {
    "1": "우선주", "2": "인프라투융자", "3": "ELW", "4": "뮤추얼펀드",
    "5": "신주인수권", "6": "리츠", "7": "신주인수권증서", "8": "ETF",
    "9": "하이일드펀드", "30": "K-OTC", "50": "코넥스", "60": "ETN",
    "70": "손실제한ETN", "80": "금현물", "90": "변동성ETN",
}

# state 필드에서 차단할 키워드 (부분 일치, '|' 구분 복합 상태 대응)
_BLOCKED_STATE_KEYWORDS: list[str] = [
    "관리종목",
    "관리(감리)",
    "감리",
    "거래정지",
    "불성실공시",
    "상장폐지예고",
    "상장폐지",
    "정리매매",
    "단기과열",
    "투자경고",
    "투자위험",
    "투자유의",
    "투자주의",
    "투자환기",
    "위험예고",
    "초저유동성",
    "이상급등",
    "상장주식수부족",
    "증거금100%",
    "증거금50%",
    "증거금40%",
]

# orderWarning 값별 사유 매핑 ("0" = 정상)
_ORDER_WARNING_REASONS: dict[str, str] = {
    "1": "ETF투자주의",
    "2": "정리매매",
    "3": "단기과열/투자주의",
    "4": "투자위험",
    "5": "투자경고",
}


@dataclass
class StockFilterEvaluation:
    code: str
    excluded: bool
    primary_reason: str = ""
    reasons: list[str] = field(default_factory=list)
    state_flags: list[str] = field(default_factory=list)
    diagnostic_flags: list[str] = field(default_factory=list)
    parsed_fields: dict[str, str | int | bool | None] = field(default_factory=dict)


def _split_state_flags(state_raw: str) -> list[str]:
    state = str(state_raw or "").strip()
    if not state or state == "정상":
        return []
    parts = [p.strip() for p in re.split(r"[|/,]", state) if p.strip()]
    return parts or [state]


def _positive_int_string(value: object) -> tuple[bool, int | None]:
    raw = str(value or "").strip()
    if not raw:
        return False, None
    normalized = raw.replace(",", "")
    if normalized.startswith("+"):
        normalized = normalized[1:]
    if not normalized.isdigit():
        return False, None
    parsed = int(normalized)
    return parsed > 0, parsed


def _stock_name(item: dict) -> str:
    return str(item.get("hname") or item.get("stk_nm") or item.get("name") or "").strip()


def _preferred_reason(name_raw: str, company_class: str) -> str:
    clean_name = re.sub(r"\(.*?\)$", "", name_raw).strip()
    suffixes = ["우선주", "우B", "우C", "우D", "우E", "우F", "우"]
    for suffix in suffixes:
        if clean_name.endswith(suffix) and len(clean_name) > len(suffix) + 1:
            return f"우선주(종목명)-{suffix}"
    upper_name = clean_name.upper()
    upper_class = company_class.upper()
    for keyword in ("PREFERRED", "PRF"):
        if keyword in upper_name or keyword in upper_class:
            return f"우선주(영문표기)-{keyword}"
    if "우선" in company_class:
        return f"우선주(회사분류)-{company_class}"
    return ""


def evaluate_stock_filter(item: dict, stk_cd: str) -> StockFilterEvaluation:
    reasons: list[str] = []
    diagnostic_flags: list[str] = []
    mc = str(item.get("marketCode") or "").strip()
    market_name = str(item.get("marketName") or "").strip()
    ow = str(item.get("orderWarning") or "0").strip()
    state_raw = str(item.get("state") or "").strip()
    name_raw = _stock_name(item)
    company_class = str(item.get("companyClassName") or "").strip()
    audit = str(item.get("auditInfo") or "").strip()
    list_count_raw = str(item.get("listCount") or "").strip()
    last_price_raw = str(item.get("lastPrice") or "").strip()
    reg_day = str(item.get("regDay") or "").strip()
    nxt_enable = str(item.get("nxtEnable") or "").strip().upper()

    if mc and mc not in _ALLOWED_MARKET_CODES:
        label = _MARKET_CODE_LABELS.get(mc, mc)
        reasons.append(f"marketCode={mc}({label})")

    non_equity_keywords = ["etf", "etn", "elw", "리츠", "reit", "k-otc", "k otc", "kots", "코넥스"]
    market_name_lower = market_name.lower()
    name_lower = name_raw.lower()
    company_class_lower = company_class.lower()
    for kw in non_equity_keywords:
        if kw in market_name_lower or kw in name_lower or kw in company_class_lower:
            reasons.append(f"비주식분류={kw}")
            break

    if ow != "0":
        reasons.append(_ORDER_WARNING_REASONS.get(ow, f"orderWarning={ow}"))

    state_flags = _split_state_flags(state_raw)
    for part in state_flags:
        for kw in _BLOCKED_STATE_KEYWORDS:
            if kw in part:
                reasons.append(f"state={kw}")

    if "스팩" in name_raw or "spac" in name_lower:
        reasons.append("스팩")

    preferred = _preferred_reason(name_raw, company_class)
    if preferred:
        reasons.append(preferred)
    if stk_cd and stk_cd.isdigit() and stk_cd[-1] != "0" and not preferred:
        diagnostic_flags.append("우선주의심(코드끝자리)")

    if audit and audit != "정상":
        reasons.append(f"감리={audit}")

    list_count_value = None
    if list_count_raw:
        list_count_ok, list_count_value = _positive_int_string(list_count_raw)
        if not list_count_ok:
            reasons.append(f"상장주식수비정상={list_count_raw}")

    last_price_ok, last_price_value = _positive_int_string(last_price_raw)
    if not last_price_ok:
        reasons.append(f"전일종가비정상={last_price_raw or 'EMPTY'}")

    if nxt_enable == "N":
        diagnostic_flags.append("NXT불가")

    primary_reason = reasons[0] if reasons else ""
    return StockFilterEvaluation(
        code=stk_cd,
        excluded=bool(reasons),
        primary_reason=primary_reason,
        reasons=list(dict.fromkeys(reasons)),
        state_flags=state_flags,
        diagnostic_flags=diagnostic_flags,
        parsed_fields={
            "marketCode": mc,
            "marketName": market_name,
            "orderWarning": ow,
            "state": state_raw,
            "name": name_raw,
            "companyClassName": company_class,
            "auditInfo": audit,
            "listCount": list_count_raw,
            "listCountValue": list_count_value,
            "lastPrice": last_price_raw,
            "lastPriceValue": last_price_value,
            "regDay": reg_day,
            "nxtEnable": nxt_enable,
        },
    )


def is_excluded(item: dict, stk_cd: str) -> tuple[bool, str]:
    """
    ka10099 응답의 개별 종목 dict 를 받아 매매 부적격 여부를 판정.

    Parameters
    ----------
    item : dict
        ka10099 응답 list 내 개별 종목 딕셔너리.
    stk_cd : str
        6자리 종목코드 (정규화 완료된 값).

    Returns
    -------
    (excluded: bool, reason: str)
        excluded=True 이면 매매 부적격. reason 에 사유 문자열.
    """
    result = evaluate_stock_filter(item, stk_cd)
    return result.excluded, result.primary_reason


def is_excluded_with_ka10100(
    item: dict,
    stk_cd: str,
    ka10100_data: dict | None = None,
) -> tuple[bool, str]:
    """
    ka10100 데이터를 활용한 2차 필터링.

    Parameters
    ----------
    item : dict
        ka10099 응답의 개별 종목 딕셔너리
    stk_cd : str
        6자리 종목코드 (정규화 완료된 값)
    ka10100_data : Optional[dict]
        ka10100 응답 데이터 (없으면 1차 필터링만 수행)

    Returns
    -------
    (excluded: bool, reason: str)
        excluded=True 이면 매매 부적격. reason 에 사유 문자열.
    """
    # 1차 필터링 수행
    excluded, reason = is_excluded(item, stk_cd)
    if excluded:
        return excluded, reason

    # ka10100 데이터가 없으면 1차 필터링 결과만 반환
    if not ka10100_data:
        return False, ""

    # 2차 필터링: companyClassName 우선주 판별 보강
    company_class = str(ka10100_data.get("companyClassName") or "").strip()
    if company_class and "우선주" in company_class:
        return True, f"우선주(ka10100)-{company_class}"

    # 2차 필터링: listCount 검증
    list_count = str(ka10100_data.get("listCount") or "").strip()
    if list_count and (list_count == "0000000000000000" or list_count == "0"):
        return True, f"상장주식수비정상(ka10100)={list_count}"

    # 2차 필터링: lastPrice 검증
    last_price = str(ka10100_data.get("lastPrice") or "").strip()
    if last_price and (last_price == "00000000" or last_price == "0"):
        return True, f"전일종가비정상(ka10100)={last_price}"

    return False, ""



