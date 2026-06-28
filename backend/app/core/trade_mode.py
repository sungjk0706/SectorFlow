from __future__ import annotations
# -*- coding: utf-8 -*-
"""
trade_mode(test|real) 판별 및 종목 REG type 목록.

- 실전·테스트 공통: REG 에는 type "01"(주식체결 구코드)을 넣지 않는다 -- 실전에서 305005(미사용 타입).
  체결·현재가 실시간은 "0B"(주식체결) + 종목정보 "0g" -> ["0B","0g"].
  시장가 단일 운용으로 호가(02) 구독 불필요 -- 제거됨.

REAL 수신 시 type "0B"는 engine_service._normalize_real_type 에서 "01"과 동일 처리 경로로 병합.
"""


def effective_trade_mode(settings: dict | None) -> str:
    """엔진 캐시 또는 DB에서 로드한 플랫 dict에서 'test' | 'real' 반환.

    단일 소스: trade_mode 문자열 값만 참조한다.
    하위 호환: 기존 'mock' 값도 'test'로 매핑한다.
    """
    s = settings or {}
    tm = str(s.get("trade_mode") or "").strip().lower()
    if tm == "real":
        return "real"
    if tm in ("test", "mock"):
        return "test"
    return "test"


def is_test_mode(settings: dict | None) -> bool:
    return effective_trade_mode(settings) == "test"


def stock_reg_types(_settings: dict | None) -> list[str]:
    """
    종목별 REG type 배열 -- 실전: REG '01' 미지원, 체결은 '0B'(주식체결) 사용.
    test·실전 동일 조합; trade_mode 는 URL·토큰·자격증명 선택에만 사용된다.
    시장가 단일 운용으로 호가(02) 구독 불필요 -- 제거됨.
    """
    return ["0B", "0g"]
