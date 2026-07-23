# -*- coding: utf-8 -*-
"""
레이더/종목 관련 모듈
- 종목 상태 관리
- 실시간 데이터 보강
"""
import logging
from backend.app.services import engine_state
from backend.app.core.kiwoom_account_parsing import _parse_float_loose

logger = logging.getLogger(__name__)


# ── 종목 조회 ─────────────────────────────────────────────────

def get_trade_amount_cache() -> dict[str, int | None]:
    """실시간 거래대금 캐시 반환 (master_stocks_cache 기반, 백만원 단위).

    None = 실시간 데이터 미수신 — 0으로 폴백하지 않고 None 유지 (P20 폴백 금지).
    """
    result: dict[str, int | None] = {}
    for cd, stock in engine_state.state.master_stocks_cache.items():
        ta = stock.get("trade_amount")
        result[cd] = int(ta) if ta is not None else None
    return result


def get_high_price_5d_cache() -> dict[str, int]:
    """5일 전고점 캐시 반환."""
    return {cd: int(stock.get("high_5d_price", 0) or 0) for cd, stock in engine_state.state.master_stocks_cache.items()}


def get_program_net_buy_cache() -> dict[str, int]:
    """프로그램 순매수 캐시 반환."""
    return {cd: int(stock.get("program_net_buy", 0) or 0) for cd, stock in engine_state.state.master_stocks_cache.items()}


def get_news_boost_cache() -> dict[str, float]:
    """뉴스 가산점 캐시 반환 — 만료된 항목 제외 (5분 TTL).

    P7: 캐시 크기는 매수후보 종목 수(수십~수백)로 제한. 만료 항목은 lazy 제거.
    P20: 만료된 항목은 폴백 없이 제거 후 유효 항목만 반환.
    """
    import time
    now = time.monotonic()
    ttl = engine_state.state.news_boost_ttl_sec
    cache = engine_state.state.news_boost_cache
    expired = [cd for cd, (_s, ts) in cache.items() if now - ts > ttl]
    for cd in expired:
        del cache[cd]
    return {cd: s for cd, (s, _ts) in cache.items()}


def get_orderbook_cache() -> dict[str, tuple[int, int]]:
    """호가잔량 캐시 반환 — (매수잔량, 매도잔량) 튜플. order_ratio=[bid, ask] 형식에서 변환."""
    result: dict[str, tuple[int, int]] = {}
    for cd, stock in engine_state.state.master_stocks_cache.items():
        ob = stock.get("order_ratio")
        if ob is not None and len(ob) == 2:
            try:
                result[cd] = (int(ob[0]), int(ob[1]))
            except (TypeError, ValueError):
                logger.warning("[레이더] 호가잔량 변환 실패 code=%s order_ratio=%s", cd, ob)
    return result


# ── 실시간 데이터 보강 ─────────────────────────────────────────────────

def _apply_real01_volume_amount_to_radar_rows(raw_cd: str, vals: dict, *, is_0b_tick: bool = True) -> None:
    """FID 데이터를 받아 master_stocks_cache의 실시간 필드를 직접 갱신합니다."""
    from backend.app.services.engine_symbol_utils import _base_stk_cd

    nk = _base_stk_cd(raw_cd)
    if not nk:
        return

    entry = engine_state.state.master_stocks_cache.get(nk)
    if not entry:
        return

    # 체결 데이터 (0B/01) 처리
    if is_0b_tick:
        if "10" in vals:
            val10_str = str(vals["10"]).replace("+", "")
            entry["cur_price"] = abs(int(float(val10_str)))
        if "11" in vals:
            val11_str = str(vals["11"]).strip()
            if val11_str.startswith("-"):
                entry["sign"] = "5"
            elif val11_str.startswith("+"):
                entry["sign"] = "2"
            else:
                entry["sign"] = "3"
            _chg = int(float(val11_str.replace("+", "").replace("-", "")))
            entry["change"] = -_chg if val11_str.startswith("-") else _chg
        if "12" in vals:
            from backend.app.services.engine_ws_parsing import parse_change_rate_to_percent
            _raw12 = str(vals["12"]).strip()
            if _raw12:
                entry["change_rate"] = parse_change_rate_to_percent(vals["12"])
            # 빈 문자열이면 None 유지 (미수신 — P20 폴백 금지)
        if "14" in vals:
            _raw14 = str(vals["14"]).strip()
            if _raw14:
                entry["trade_amount"] = int(_parse_float_loose(vals["14"]))
            # 빈 문자열이면 None 유지 (미수신 — P20 폴백 금지)
        if "228" in vals:
            entry["strength"] = str(vals["228"]).strip()
