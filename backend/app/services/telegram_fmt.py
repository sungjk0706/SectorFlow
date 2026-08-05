# -*- coding: utf-8 -*-
"""텔레그램 메시지 전용 숫자 포맷 모듈 (P10 SSOT, P23 일관성, P24 단순성).

프론트엔드 ui-styles.ts / ui-styles-cells.ts 의 포맷 규칙을 Python으로 동일 구현.
텔레그램 명령어 본문은 본 모듈의 함수만 사용 — 인라인 f-string 포맷(:,.2f 등)·수동 부호 처리 금지.

프론트엔드 원본 매핑 (1:1 대응 — 규칙 단일 진실 소스 = 프론트엔드):
  fmt_won(v)         ← fmtWon(v)            천 단위 콤마 + "원"
  fmt_comma(v)       ← fmtComma(v)          천 단위 콤마 (원 미포함)
  fmt_rate(v)        ← fmtRate(v) + "%"     부호 + 소수 2자리 + "%" (null → "-")
  fmt_score(v)       ← _formatScore(v)      정수면 정수, 실수면 소수 1자리
  fmt_signed_won(v)  ← sell-position.ts pnlText 패턴  양수 "+콤마원", 음수 "-콤마원", 0 "콤마원" (부호 없음)
  change_arrow(v)    ← changeArrow(v)       양수 "▲", 음수 "▼", 0 "" (빈 문자열)
  fmt_change(v)      ← createChangeCell 셀   arrow + fmt_comma(abs(v)) (0 → "0", null → "-")

주의:
  - fmt_rate 는 프론트 fmtRate 가 %를 호출부에서 붙이는 것과 달리 함수 내부에서 "%"까지 붙여 반환.
    텔레그램 메시지는 단일 문자열이므로 호출부 조합 최소화 (P24). 부호/자릿수 규칙은 프론트와 동일.
  - 0 처리는 프론트 기준 — fmt_signed_won(0) = "0원" (부호 없음), fmt_rate(0) = "0.00%" (부호 없음).
"""
from __future__ import annotations


def fmt_won(v) -> str:
    """금액 포맷 — 천 단위 콤마 + "원" (프론트엔드 fmtWon과 동일).

    예: 1000000 → "1,000,000원", None/invalid → "0원".
    """
    try:
        return f"{int(v or 0):,}원"
    except (ValueError, TypeError):
        return "0원"


def fmt_comma(v) -> str:
    """숫자 천 단위 콤마 (프론트엔드 fmtComma와 동일, "원" 미포함).

    예: 1000000 → "1,000,000", None/invalid → "0".
    """
    try:
        return f"{int(v or 0):,}"
    except (ValueError, TypeError):
        return "0"


def fmt_rate(v) -> str:
    """백분율 포맷 — 부호 + 소수 2자리 + "%" (프론트엔드 fmtRate + "%"와 동일 규칙).

    예: 3.7 → "+3.70%", -2.15 → "-2.15%", 0 → "0.00%", None → "-".
    """
    if v is None:
        return "-"
    try:
        f = float(v)
    except (ValueError, TypeError):
        return "-"
    if f > 0:
        return f"+{f:.2f}%"
    if f < 0:
        return f"{f:.2f}%"
    return "0.00%"


def fmt_score(v) -> str:
    """가산점 포맷 — 정수는 정수로, 실수는 소수 1자리 (프론트엔드 _formatScore와 동일).

    예: 5 → "5", 2.5 → "2.5", None/invalid → "0".
    """
    try:
        f = float(v or 0)
    except (ValueError, TypeError):
        return "0"
    if f == int(f):
        return str(int(f))
    return f"{f:.1f}"


def fmt_signed_won(v) -> str:
    """부호 붙인 금액 포맷 — 손익금 표시용 (프론트엔드 sell-position.ts pnlText 패턴과 동일).

    규칙: 양수 "+콤마원", 음수 "-콤마원", 0 "콤마원" (부호 없음 — 프론트 pnlText 기준).
    예: 32000 → "+32,000원", -5000 → "-5,000원", 0 → "0원", None → "0원".
    """
    try:
        n = int(v or 0)
    except (ValueError, TypeError):
        return "0원"
    if n > 0:
        return f"+{n:,}원"
    if n < 0:
        return f"{n:,}원"
    return "0원"


def change_arrow(v) -> str:
    """대비 화살표 — 양수 ▲, 음수 ▼, 0 빈 문자열 (프론트엔드 changeArrow와 동일)."""
    try:
        n = float(v or 0)
    except (ValueError, TypeError):
        return ""
    if n > 0:
        return "▲"
    if n < 0:
        return "▼"
    return ""


def fmt_change(v) -> str:
    """대비 포맷 — 화살표 + 천 단위 콤마 절대값 (프론트엔드 createChangeCell 셀 조합과 동일).

    규칙: 양수 "▲콤마", 음수 "▼콤마", 0 "0", None/invalid "-".
    예: 1200 → "▲1,200", -800 → "▼800", 0 → "0", None → "-".
    """
    if v is None:
        return "-"
    try:
        n = int(v)
    except (ValueError, TypeError):
        return "-"
    if n == 0:
        return "0"
    arrow = "▲" if n > 0 else "▼"
    return f"{arrow}{abs(n):,}"
