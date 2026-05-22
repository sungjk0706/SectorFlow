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
from __future__ import annotations

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
    # ── 0) marketCode 화이트리스트 체크 ──────────────────────────────
    mc = str(item.get("marketCode") or "").strip()
    if mc and mc not in _ALLOWED_MARKET_CODES:
        label = _MARKET_CODE_LABELS.get(mc, mc)
        return True, f"marketCode={mc}({label})"

    # ── 1) orderWarning 체크 ─────────────────────────────────────────
    ow = str(item.get("orderWarning") or "0").strip()
    if ow != "0":
        reason = _ORDER_WARNING_REASONS.get(ow, f"orderWarning={ow}")
        return True, reason

    # ── 2) state 키워드 체크 (복합 상태 '|' 구분 대응) ────────────────
    state_raw = str(item.get("state") or "").strip()
    if state_raw:
        for part in state_raw.split("|"):
            part = part.strip()
            for kw in _BLOCKED_STATE_KEYWORDS:
                if kw in part:
                    return True, f"state={part}"

    # ── 3) 우선주 체크 (종목코드 끝자리 ≠ "0") ──────────────────────
    # 2024년부터 영문 혼용 종목코드(예: 0052D0, 12345A 등)가 도입되어, 
    # 끝자리가 0이 아니라고 무조건 우선주로 필터링하면 안 됩니다.
    # 기존 숫자 6자리 코드인 경우에만 우선주(끝자리 0 아님)를 필터링합니다.
    if stk_cd and stk_cd.isdigit() and stk_cd[-1] != "0":
        return True, "우선주"
    # 영문 혼용 코드이면서 우선주인 경우(보통 K, M 등을 배정받거나 이름에 '우' 포함)는 
    # 별도의 정밀 필터링(종목명 검사 등)이 필요하지만, 
    # 일단 '알파벳 포함 정상 종목'이 억울하게 입구컷 당하는 치명적 버그를 방지합니다.
    if stk_cd and not stk_cd.isdigit() and stk_cd[-1] in ("K", "M", "L"):
        # 기존 우선주 영문 배정 규칙에 해당하는 경우만 우선주로 간주
        return True, "우선주(영문)"

    # ── 4) 스팩(SPAC) 종목명 체크 ────────────────────────────────────
    name_raw = str(
        item.get("hname") or item.get("stk_nm") or item.get("name") or ""
    ).strip()
    if "스팩" in name_raw:
        return True, "스팩"

    # ── 5) auditInfo 감리 체크 ───────────────────────────────────────
    audit = str(item.get("auditInfo") or "").strip()
    if audit and audit != "정상":
        return True, f"감리={audit}"

    return False, ""
