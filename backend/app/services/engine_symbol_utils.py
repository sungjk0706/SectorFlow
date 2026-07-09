from __future__ import annotations
# -*- coding: utf-8 -*-
"""
키움·REST 종목코드 정규화 및 REAL item/9001 필드 해석 -- 전역 엔진 상태 없음.

engine_service에서 분리된 순수 함수만 둔다 (로직·입출력 동일 유지).
"""



def is_nxt_enabled(stk_cd: str) -> bool:
    """
    종목코드가 NXT 중복상장 종목인지 반환.
    `state.master_stocks_cache`에서 직접 조회.
    """
    from backend.app.services.engine_state import state
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    stock = state.master_stocks_cache.get(base, {})
    if stock:
        return bool(stock.get("nxt_enable", False))
    return False


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


def get_stock_market(stk_cd: str) -> str | None:
    """
    종목코드 -> 시장 구분 코드 반환.
    "0" = 코스피, "10" = 코스닥, None = 미확인
    """
    from backend.app.services.engine_state import state
    base = _base_stk_cd(stk_cd) if stk_cd else ""
    stock = state.master_stocks_cache.get(base, {})
    if stock:
        return stock.get("market")
    return None




def _base_stk_cd(stk_cd: str) -> str:
    """순수 종목코드 반환 (_AL/_NX 접미사 제거)."""
    s = str(stk_cd or "").strip().upper()
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


def _resolve_bucket_key(raw_cd: str, bucket: dict) -> str | None:
    """
    REAL 수신 종목코드와 레이더/작전 dict 키가 표기만 다를 때(6자리·접두 등) 실제 키 반환.
    """
    if not raw_cd or not bucket:
        return None
    if raw_cd in bucket:
        return raw_cd
    nk = _base_stk_cd(raw_cd)
    if nk in bucket:
        return nk
    for k in bucket:
        if _base_stk_cd(str(k)) == nk:
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
    return _base_stk_cd(str(v))


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
            return _base_stk_cd(str(alt))
    if isinstance(item.get("values"), dict):
        cd = _fid9001_to_stk_cd(item["values"])
        if cd:
            return cd
    raw = _parse_real_item_field(item.get("item"))
    if not raw:
        return ""
    s = str(raw).strip().upper()
    if s.isdigit() and len(s) > 6:
        return ""
    return _base_stk_cd(raw)
