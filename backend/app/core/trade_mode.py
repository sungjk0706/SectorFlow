from __future__ import annotations
# -*- coding: utf-8 -*-
"""
trade_mode(virtual|live) 판별.

- 실전·가상 공통: REG 에는 type "01"(주식체결 구코드)을 넣지 않는다 -- 실전에서 305005(미사용 타입).
  체결·현재가 실시간은 "0B"(주식체결) + 종목정보 "0g" -> ["0B","0g"].
  시장가 단일 운용으로 호가(02) 구독 불필요 -- 제거됨.

LIVE 수신 시 type "0B"는 engine_service._normalize_real_type 에서 "01"과 동일 처리 경로로 병합.
"""


def normalize_trade_mode(value: object | None) -> str:
    """투자모드 입력을 내부 표준값인 'virtual' 또는 'live'로 정규화한다.

    매핑: 'virtual'→'virtual', 'live'→'live', 그 외/None→'virtual' (fail-closed).
    """
    mode = str(value or "").strip().lower()
    if mode == "live":
        return "live"
    # 'virtual', 그 외/None → 'virtual' (fail-closed)
    return "virtual"


def effective_trade_mode(settings: dict | None) -> str:
    """엔진 캐시 또는 DB에서 로드한 플랫 dict에서 'virtual' | 'live' 반환.

    단일 소스: trade_mode 문자열 값만 참조한다.
    """
    s = settings or {}
    return normalize_trade_mode(s.get("trade_mode"))


def is_virtual_mode(settings: dict | None) -> bool:
    return effective_trade_mode(settings) == "virtual"
