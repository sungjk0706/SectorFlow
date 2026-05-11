# -*- coding: utf-8 -*-
"""
키움·REST 종목코드 정규화 및 REAL item/9001 필드 해석 -- 전역 엔진 상태 없음.

engine_service에서 분리된 순수 함수만 둔다 (로직·입출력 동일 유지).
"""
from __future__ import annotations

# ── 시장 구분 캐시 ────────────────────────────────────────────────────────────
# 로그인 후 ka10099 로 적재. { "005930": "0", "035720": "10" }
# "0" = 코스피, "10" = 코스닥
# 기존 로직 완전 독립 -- 읽기 전용 접근만 허용.
_market_map: dict[str, str] = {}
_market_map_version: int = 0  # set_market_map 호출 시마다 증가 -- UI 갱신 감지용

# ── NXT 중복상장 캐시 ─────────────────────────────────────────────────────────
# 로그인 후 ka10001 순차 조회로 적재. { "005930": True, "000660": True, "999999": False }
# True = KRX+NXT 중복상장, False = KRX 단독
_nxt_enable_map: dict[str, bool] = {}


def set_nxt_enable_map(new_map: dict[str, bool]) -> None:
    """로그인 후 engine_service 에서 1회 호출 -- NXT 중복상장 캐시 교체."""
    global _nxt_enable_map
    _nxt_enable_map = dict(new_map)


def is_nxt_enabled(stk_cd: str) -> bool:
    """
    종목코드가 NXT 중복상장 종목인지 반환.
    캐시 미적재 시 False (KRX 단독으로 처리).
    """
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    return _nxt_enable_map.get(base, False)


def filter_krx_only_stocks(
    codes: list[str],
    *,
    is_after_hours: bool | None = None,
) -> list[str]:
    """
    KRX 장외 시간대에 KRX 단독 종목을 제외한 종목 코드 리스트 반환.
    - is_after_hours=None → is_krx_after_hours() 자동 호출
    - is_after_hours=True → KRX 단독 종목 제외
    - is_after_hours=False → 원본 그대로 반환
    """
    if is_after_hours is None:
        from app.services.daily_time_scheduler import is_krx_after_hours
        is_after_hours = is_krx_after_hours()
    if not is_after_hours:
        return codes
    return [cd for cd in codes if is_nxt_enabled(cd)]


def get_ws_subscribe_code(stk_cd: str) -> str:
    """
    웹소켓 구독 시 사용할 종목코드 반환.
    - NXT 중복상장: '005930_AL' (KRX+NXT 통합, 슬롯 1개)
    - KRX 단독: '005930' (접미사 없음)
    """
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    if not base:
        return stk_cd
    if is_nxt_enabled(base):
        return f"{base}_AL"
    return base


def set_market_map(new_map: dict[str, str]) -> None:
    """로그인 후 engine_service 에서 1회 호출 -- 기존 캐시 교체."""
    global _market_map, _market_map_version
    _market_map = dict(new_map)
    _market_map_version += 1


def get_market_map_version() -> int:
    """현재 시장 구분 캐시 버전 반환 -- UI 에서 변경 감지용."""
    return _market_map_version


def get_stock_market(stk_cd: str) -> str | None:
    """
    종목코드 -> 시장 구분 코드 반환.
    "0" = 코스피, "10" = 코스닥, None = 미확인
    """
    if not _market_map:
        return None
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    return _market_map.get(base)


def real01_trade_price_from_cache(latest_trade_prices: dict, stk_cd: str) -> int:
    """
    REAL type=01 체결로만 갱신되는 `_latest_trade_prices` 캐시에서 현재가.
    임의 가정 금지 -- 없거나 0이면 0 반환.
    """
    if not latest_trade_prices:
        return 0
    nk = _format_kiwoom_reg_stk_cd(stk_cd)
    p = latest_trade_prices.get(nk)
    if p and int(p) > 0:
        return int(p)
    for k, v in latest_trade_prices.items():
        if _format_kiwoom_reg_stk_cd(str(k)) == nk and v and int(v) > 0:
            return int(v)
    return 0


def _format_kiwoom_reg_stk_cd(stk_cd: str) -> str:
    """
    키움 WebSocket REG 의 item 종목코드 -- 공식 예시는 6자리 숫자(선행 0 유지).
    보유 REST 등에서 'A006910' / '006910' 모두 허용.
    _AL / _NX 접미사는 제거하고 순수 6자리 반환 (수신 파싱용).
    """
    s = str(stk_cd or "").strip().upper().lstrip("A")
    # _AL / _NX 접미사 제거
    for suffix in ("_AL", "_NX"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s


def _base_stk_cd(stk_cd: str) -> str:
    """순수 6자리 종목코드 반환 (A 접두사·_AL/_NX 접미사 제거)."""
    s = str(stk_cd or "").strip().upper().lstrip("A")
    for suffix in ("_AL", "_NX"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.isdigit():
        return s.zfill(6)[-6:]
    return s


def _to_al_stk_cd(stk_cd: str) -> str:
    """6자리 종목코드 -> KRX+NXT 통합 구독용 _AL 접미사 코드 반환. 예: '005930' -> '005930_AL'"""
    base = _base_stk_cd(stk_cd)
    if not base:
        return stk_cd
    return f"{base}_AL"


def is_nxt_code(stk_cd: str) -> bool:
    """종목코드가 NXT 전용(_NX 접미사)인지 판단."""
    return str(stk_cd or "").strip().upper().endswith("_NX")


def _normalize_stk_cd_rest(code: str) -> str:
    """종목코드 정규화 (A 접두사·_AL/_NX 접미사 제거).
    알파벳 포함 여부에 따라 처리 분기 (2024년 신규 종목코드 대응).
    """
    s = str(code).strip().upper().lstrip("A")
    for suffix in ("_AL", "_NX"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    # 알파벳 포함 여부에 따라 정규화 분기
    if s.isdigit():
        # 기존 숫자코드: 6자리 패딩
        return s.zfill(6)[-6:]
    else:
        # 알파벳 코드: 원문 대문자 유지
        return s


def _resolve_bucket_key(raw_cd: str, bucket: dict) -> str | None:
    """
    REAL 수신 종목코드와 레이더/작전 dict 키가 표기만 다를 때(6자리·접두 등) 실제 키 반환.
    """
    if not raw_cd or not bucket:
        return None
    if raw_cd in bucket:
        return raw_cd
    nk = _format_kiwoom_reg_stk_cd(raw_cd)
    if nk in bucket:
        return nk
    for k in bucket:
        if _format_kiwoom_reg_stk_cd(str(k)) == nk:
            return str(k)
    return None


def _dict_get_fid(d: dict | None, fid: str):
    """JSON 키가 '9001' 또는 정수 9001 인 경우 모두 조회."""
    if not isinstance(d, dict):
        return None
    if fid in d:
        return d[fid]
    try:
        ik = int(str(fid).strip())
    except (ValueError, TypeError):
        return None
    return d.get(ik)


def _fid9001_to_stk_cd(vals: dict) -> str:
    """REAL values(또는 item 루트)에서 FID 9001 -> 6자리 종목코드."""
    if not isinstance(vals, dict):
        return ""
    v = _dict_get_fid(vals, "9001")
    if v is None or str(v).strip() == "":
        return ""
    return _format_kiwoom_reg_stk_cd(str(v))


def _parse_real_item_field(item_field) -> str:
    """REAL 항목 상위 필드 item -- ['263750'] 또는 '263750'·계좌번호 등."""
    if item_field is None:
        return ""
    if isinstance(item_field, (list, tuple)) and len(item_field) > 0:
        return str(item_field[0] or "").strip()
    return str(item_field).strip()


def _real_item_stk_cd(item: dict, vals: dict) -> str:
    """
    REAL 체결·호가 등 -- values 의 FID 9001 우선, 없으면 item·루트 보조 필드.
    키움은 체결(01/0B)에서 item 만 채우고 values 에 9001 이 없는 경우가 있다.
    item 루트에 9001·jmcode·stk_cd 가 오는 페이로드도 수용한다.
    숫자 7자리 초과는 계좌번호 등으로 보고 해당 후보만 스킵.
    """
    if isinstance(vals, dict):
        cd = _fid9001_to_stk_cd(vals)
        if cd:
            return cd
    if not isinstance(item, dict):
        return ""
    cd = _fid9001_to_stk_cd(item)
    if cd:
        return cd
    for k in ("jmcode", "stk_cd", "code", "종목코드"):
        alt = item.get(k)
        if alt is not None and str(alt).strip():
            return _format_kiwoom_reg_stk_cd(str(alt))
    if isinstance(item.get("values"), dict):
        cd = _fid9001_to_stk_cd(item["values"])
        if cd:
            return cd
    raw = _parse_real_item_field(item.get("item"))
    if not raw:
        return ""
    s = str(raw).strip().upper().lstrip("A")
    if s.isdigit() and len(s) > 6:
        return ""
    return _format_kiwoom_reg_stk_cd(raw)
