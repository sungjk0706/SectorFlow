from __future__ import annotations
from dataclasses import dataclass, field
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
    "거래정지",
    "불성실공시",
    "상장폐지",
    "상장폐지예고",
    "정리매매",
    "투자경고",
    "투자위험",
    "증거금100%",
]

# orderWarning 값별 사유 매핑 ("0" = 정상)
_ORDER_WARNING_REASONS: dict[str, str] = {
    "1": "ETF투자주의",
    "2": "정리매매",
    "3": "단기과열/투자주의",
    "4": "투자위험",
    "5": "투자경고",
}


# 사유(raw) → 표시명 매핑 — UI 표시 + 로그 출력 공용 (P10 SSOT, P23 일관성)
# raw 사유는 evaluate_stock_filter 내부에서 생성되는 문자열.
# 표시명은 사용자 친화적 일반 용어.
_REASON_DISPLAY_MAP: dict[str, str] = {
    # marketCode 계열 — "marketCode=8(ETF)" → "ETF"
    "marketCode=1(우선주)": "우선주(비주식)",
    "marketCode=2(인프라투융자)": "인프라투융자",
    "marketCode=3(ELW)": "ELW",
    "marketCode=4(뮤추얼펀드)": "뮤추얼펀드",
    "marketCode=5(신주인수권)": "신주인수권",
    "marketCode=6(리츠)": "리츠",
    "marketCode=7(신주인수권증서)": "신주인수권증서",
    "marketCode=8(ETF)": "ETF",
    "marketCode=9(하이일드펀드)": "하이일드펀드",
    "marketCode=30(K-OTC)": "K-OTC",
    "marketCode=50(코넥스)": "코넥스",
    "marketCode=60(ETN)": "ETN",
    "marketCode=70(손실제한ETN)": "손실제한ETN",
    "marketCode=80(금현물)": "금현물",
    "marketCode=90(변동성ETN)": "변동성ETN",
    # state 계열 — "state=관리종목" → "관리종목"
    "state=관리종목": "관리종목",
    "state=거래정지": "거래정지",
    "state=불성실공시": "불성실공시",
    "state=상장폐지": "상장폐지",
    "state=상장폐지예고": "상장폐지예고",
    "state=정리매매": "정리매매",
    "state=투자경고": "투자경고",
    "state=투자위험": "투자위험",
    "state=증거금100%": "증거금100%종목",
    # orderWarning 계열 — 이미 일반 용어
    "ETF투자주의": "ETF투자주의",
    "정리매매": "정리매매",
    "단기과열/투자주의": "단기과열/투자주의",
    "투자위험": "투자위험",
    "투자경고": "투자경고",
    # 기타
    "스팩": "스팩",
}


def to_display_reason(raw_reason: str) -> str:
    """raw 사유 문자열 → 사용자 친화적 표시명 변환.

    정확 매칭 우선, 실패 시 접두사 기반 매칭(fallback 아님 — 매핑 누락 시 raw 그대로 반환하여
    사용자에게 최소한의 정보라도 전달. P21 사용자 투명성).
    """
    if not raw_reason:
        return ""
    # 정확 매칭
    if raw_reason in _REASON_DISPLAY_MAP:
        return _REASON_DISPLAY_MAP[raw_reason]
    # 접두사 매칭: "marketCode=99(알수없음)" 등 매핑 누락 케이스
    for raw_prefix, display in _REASON_DISPLAY_MAP.items():
        if raw_reason.startswith(raw_prefix):
            return display
    # 우선주 계열 — "우선주(종목명)-우B" → "우선주"
    if raw_reason.startswith("우선주"):
        return "우선주"
    # 감리 계열 — "감리=감리지정" → "감리지정"
    if raw_reason.startswith("감리="):
        return raw_reason.split("=", 1)[1]
    # 상장주식수/전일종가 비정상 — 그대로 (이미 일반 용어)
    return raw_reason


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

    # non_equity_keywords 키워드 체크 제거 — marketCode 체크로 SSOT 단일 판정 (P10).
    # marketCode가 0/10(코스피/코스닥)이면 주식, 그 외는 비주식으로 이미 분류됨.
    # 종목명/분류 키워드 중복 체크는 사유 카운트를 부풀리는 원인이었음.

    if ow != "0":
        reasons.append(_ORDER_WARNING_REASONS.get(ow, f"orderWarning={ow}"))

    state_flags = _split_state_flags(state_raw)
    for part in state_flags:
        for kw in _BLOCKED_STATE_KEYWORDS:
            if kw in part:
                reasons.append(f"state={kw}")

    if "스팩" in name_raw or "spac" in name_raw.lower():
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



