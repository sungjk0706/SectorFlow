# -*- coding: utf-8 -*-
"""
키움 WebSocket·REST 페이로드 파싱 -- 전역 엔진 상태 없음.

engine_service에서 분리된 순수 함수만 둔다 (로직·입출력 동일 유지).
"""
from __future__ import annotations


def _ws_int(vals: dict, key: str, default: int = 0) -> int:
    try:
        v = vals.get(key, default)
        if v is None:
            return default
        s = str(v).replace(",", "").replace("+", "").strip()
        if not s or s == "-":
            return default
        return int(float(s))
    except (ValueError, TypeError):
        return default


def _ws_fid_raw(vals: dict, fid: str):
    """REAL values -- FID 키가 문자열 '13' 또는 정수 13 인 경우 모두 조회."""
    if not isinstance(vals, dict):
        return None
    if fid in vals:
        return vals[fid]
    try:
        ik = int(str(fid).strip())
    except (ValueError, TypeError):
        return None
    return vals.get(ik)


def _ws_fid_key_present(vals: dict, fid: str) -> bool:
    return _ws_fid_raw(vals, fid) is not None


def _ws_fid_float(vals: dict, fid: str, default: float = 0.0) -> float:
    """REAL values FID -> float (지수 포인트 등 소수점 필요한 경우)."""
    v = _ws_fid_raw(vals, fid)
    if v is None:
        return default
    try:
        s = str(v).replace(",", "").replace("+", "").strip()
        if not s or s == "-":
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _ws_fid_int(vals: dict, fid: str, default: int = 0) -> int:
    v = _ws_fid_raw(vals, fid)
    if v is None:
        return default
    try:
        s = str(v).replace(",", "").replace("+", "").strip()
        if not s or s == "-":
            return default
        return int(float(s))
    except (ValueError, TypeError):
        return default


def _normalize_kiwoom_real_type(raw) -> str:
    """
    Kiwoom REAL 수신 type 정규화 -- 공식 코드는 01(체결가)·00·04 등.
    REG는 type 0B(주식체결)로 수신 -> 체결가 처리는 01과 동일 경로(아래 0B->01).
    구버전 수신값 0B는 01로 치환한다.
    0J(업종지수) -> "0j" 소문자 보존.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    # 대소문자 보존이 필요한 2글자 타입 처리
    if len(s) == 2 and s[0] == "0":
        if s[1] in ("j", "J"):
            return "0j"  # 업종지수 실시간
        if s[1] in ("d", "D"):
            return "0d"  # 주식호가잔량 (WS 0D)
    u = s.upper()
    if u == "0B":
        return "01"
    if s.isdigit():
        return s.zfill(2)
    return u


def _parse_kiwoom_price_scalar(v) -> int:
    """
    REAL 가격 FID -- '+8010', '-4780', '5,200' 등 부호·콤마 포함 값에서 크기만 추출.
    (키움은 등락 방향 표시로 FID10 앞에 부호가 붙는 경우가 있어 음수로 파싱되면 절댓값 사용.)
    """
    if v is None:
        return 0
    s = str(v).replace(",", "").strip()
    if not s or s in ("-", "+", ".", "-.", "+.", "--"):
        return 0
    s = s.lstrip("+").lstrip("-")
    if not s:
        return 0
    try:
        p = int(float(s))
    except (ValueError, TypeError):
        return 0
    return abs(p)


def _parse_fid10_price(vals: dict) -> int:
    """
    REAL 현재가 -- FID 10 우선, 비어 있으면 27·28(호가) 등 보조.
    부호는 _parse_kiwoom_price_scalar 에서 제거·절댓값 처리.
    """
    if not isinstance(vals, dict):
        return 0
    for fid in ("10", "27", "28"):
        raw = _ws_fid_raw(vals, fid)
        if raw is None:
            continue
        p = _parse_kiwoom_price_scalar(raw)
        if p > 0:
            return p
    return 0


def _rest_row_int(row: dict, *keys: str, default: int = 0) -> int:
    for k in keys:
        if k in row and row.get(k) is not None:
            try:
                return int(float(str(row.get(k)).replace(",", "").replace("+", "") or 0))
            except (ValueError, TypeError):
                pass
    return default


def _rest_row_float(row: dict, *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in row and row.get(k) is not None:
            try:
                return float(str(row.get(k)).replace(",", "").replace("%", "") or 0)
            except (ValueError, TypeError):
                pass
    return default


def _parse_ws_fid12_to_percent(v) -> float:
    """
    키움 WS FID 12 (등락율) -- API 제공 값 그대로 해석(키움 공식 가이드: 클라이언트 재계산 비권장).
    정수×1000 스케일(예: 3100 -> 3.10%) 또는 소수 퍼센트(3.15 -> 3.15%).
    JSON으로 온 11980.0 등 부동소수도 정수 스케일로 처리(문자열의 '.' 분기 사용 금지).
    """
    if v is None:
        return 0.0
    s = str(v).replace(",", "").replace("%", "").replace("+", "").strip()
    if not s or s == "0":
        return 0.0
    try:
        raw = float(s)
    except (ValueError, TypeError):
        return 0.0
    if raw == 0.0:
        return 0.0
    abs_raw = abs(raw)
    is_int_like = abs(raw - round(raw)) < 1e-6
    if is_int_like and abs_raw >= 100:
        result = abs_raw / 1000.0
    else:
        result = abs_raw
    if result > 1000.0:
        return 0.0
    return -result if raw < 0 else result


# ── NXT 관련 FID 파서 ─────────────────────────────────────────────────────────

def parse_fid9081_exchange(vals: dict) -> str:
    """
    FID 9081 -- 거래소 구분.
    '1' = KRX, '2' = NXT, '' = 미수신(구독 방식에 따라 없을 수 있음)
    """
    v = _ws_fid_raw(vals, "9081")
    if v is None:
        return ""
    s = str(v).strip()
    return s  # '1'=KRX, '2'=NXT


def parse_fid290_session(vals: dict) -> str:
    """
    FID 290 -- 장 구분(세션).
    KRX 정규장: '2'
    NXT 프리마켓: 'P' (08:00~09:00)
    NXT 애프터마켓: 'U' (15:30~18:00)
    """
    v = _ws_fid_raw(vals, "290")
    if v is None:
        return ""
    return str(v).strip()


def is_nxt_tick(vals: dict) -> bool:
    """체결 데이터가 NXT 거래소 체결인지 판단 (FID 9081 = '2')."""
    return parse_fid9081_exchange(vals) == "2"


def is_nxt_premarket(vals: dict) -> bool:
    """NXT 프리마켓 체결 여부 (FID 290 = 'P')."""
    return parse_fid290_session(vals) == "P"


def is_nxt_aftermarket(vals: dict) -> bool:
    """NXT 애프터마켓 체결 여부 (FID 290 = 'U')."""
    return parse_fid290_session(vals) == "U"
