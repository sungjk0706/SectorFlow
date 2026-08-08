# -*- coding: utf-8 -*-
"""
범용 숫자 파싱 유틸리티 — 증권사 무관한 문자열→숫자 변환.

_parse_float_loose는 단순 문자열 파싱 유틸리티이나 과거 키움 전용 모듈에
위치해 공통 로직이 우발적으로 키움 모듈을 참조하게 된 사례.
공통 모듈로 이동하여 증권사 침투 문제를 해결 (W12 단순성).

전역 상태 없음 — 동일 입력에 동일 출력만 보장.
"""
from __future__ import annotations


def _parse_float_loose(v) -> float:
    try:
        cleaned = str(v).replace(",", "").replace("%", "").replace("+", "").strip()
        return float(cleaned or 0)
    except (ValueError, TypeError):
        return 0.0
