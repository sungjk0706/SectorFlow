# -*- coding: utf-8 -*-
"""
레이더/종목 관련 모듈
- 레이더 종목 관리
- 종목 상태 관리
- 실시간 데이터 보강
"""
import asyncio
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import state
from backend.app.services.engine_account_rest import _parse_float_loose

logger = get_logger("engine_radar")


# ── 레이더/종목 조회 ─────────────────────────────────────────────────

def get_pending_stocks() -> list:
    """활성 상태의 종목 목록 반환."""
    # _radar_cnsr_order 삭제: state.master_stocks_cache의 "_subscribed" 사용
    result = []
    for cd, entry in state.master_stocks_cache.items():
        if entry.get("_subscribed", False):
            stock = entry.copy()
            stock["status"] = "active"  # _subscribed 키가 있으면 active
            result.append(stock)
    return result


def get_sector_stock_layout() -> list[tuple[str, str]]:
    """업종 종목 레이아웃 반환."""
    # _sector_stock_layout 제거: state.integrated_system_settings_cache["sector_stock_layout"]로 통합
    return list(state.integrated_system_settings_cache.get("sector_stock_layout", []))


def get_avg_amt_5d_map() -> dict[str, int]:
    """5일 평균 거래대금 맵 반환."""
    return {cd: stock.get("avg_5d_trade_amount", 0) for cd, stock in state.master_stocks_cache.items()}


def get_high_5d_cache() -> dict[str, int]:
    """5일 전고점 캐시 반환."""
    return {cd: int(stock.get("high_5d_price", 0) or 0) for cd, stock in state.master_stocks_cache.items()}


# ── 실시간 데이터 보강 ─────────────────────────────────────────────────

def _overlay_radar_row_with_live_price(row: dict) -> dict:
    """
    REAL 01(FID 10) 캐시로 현재가·거래량·거래대금만 보강.
    등락률·대비·sign·체결강도는 브로커 서버 FID로만 갱신(REAL 01 본문) -- 클라이언트 재계산 없음(브로커 공식 실시간 동기화 가이드).
    실시간 틱 데이터 캐시 삭제로 REST 보완 캐시 사용 안 함.

    NOTE: dict() 복사는 Python GIL 하에서 원자적이므로 lock 불필요.
    """
    from backend.app.services import engine_radar_ops

    # 실시간 틱 데이터 캐시 읽기 로직 삭제 (캐시가 삭제되었으므로 빈 dict 반환)
    tp = {}
    ta = {}
    rc = {}

    return engine_radar_ops.overlay_radar_row_with_live_price(
        row, tp, ta, rc,
    )


async def _apply_real01_volume_amount_to_radar_rows(raw_cd: str, vals: dict, *, is_0b_tick: bool = True) -> None:
    """FID 데이터를 받아 master_stocks_cache의 실시간 필드를 직접 갱신합니다."""
    from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
    
    nk = _format_kiwoom_reg_stk_cd(raw_cd)
    if not nk:
        return
        
    async with state.shared_lock:
        entry = state.master_stocks_cache.get(nk)
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
                entry["change"] = abs(int(float(val11_str.replace("+", "").replace("-", ""))))
            if "12" in vals:
                entry["change_rate"] = _parse_float_loose(vals["12"])
            if "14" in vals:
                entry["trade_amount"] = int(_parse_float_loose(vals["14"]))
            if "17" in vals:
                entry["high_price"] = abs(int(_parse_float_loose(vals["17"])))
            if "228" in vals:
                entry["strength"] = str(vals["228"]).strip()


# ── 레이더 종목 관리 ─────────────────────────────────────────────────

async def _mark_radar_exited(stk_cd: str) -> None:
    """
    레이더 목록에서 종목 제거.
    _radar_cnsr_order 삭제: state.master_stocks_cache에서 "_subscribed" 제거
    """
    from backend.app.services.engine_symbol_utils import _normalize_stk_cd_rest

    nk = _normalize_stk_cd_rest(str(stk_cd).strip().lstrip("A"))
    rm: str | None = None
    if state.master_stocks_cache.get(nk, {}).get("_subscribed", False):
        rm = nk
    else:
        for k, entry in state.master_stocks_cache.items():
            if entry.get("_subscribed", False) and _normalize_stk_cd_rest(str(k)) == nk:
                rm = k
                break
    if rm is not None:
        if rm in state.master_stocks_cache:
            state.master_stocks_cache[rm].pop("_subscribed", None)
        if _clear_radar_rest_bootstrap_for_stk_cd:
            await _clear_radar_rest_bootstrap_for_stk_cd(rm)
        # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음


async def clear_exited_from_radar() -> int:
    """모니터링에서 이탈 종목 전체 삭제. 삭제된 개수 반환."""
    # _pending_stock_details 제거: _radar_cnsr_order만 관리하므로 삭제 불필요
    return 0


async def _drop_rest_radar_quote_for_nk(nk: str) -> None:
    """REAL 체결가가 들어오면 REST 보완 캐시 제거 -- 항상 실시간 우선."""
    # 실시간 틱 데이터 캐시 삭제로 pop 로직 삭제
    pass


async def _clear_radar_rest_bootstrap_for_stk_cd(stk_cd: str) -> None:
    """모니터링에서 종목이 완전히 빠질 때 -- 다음 등록 시 REST 1회를 다시 허용."""
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd

    nk = _format_broker_reg_stk_cd(str(stk_cd).strip().lstrip("A"))
    if nk:
        # 실시간 틱 데이터 캐시 삭제로 pop 로직 삭제
        # _rest_radar_rest_once 제거: 읽기 코드 없음, 기능 부재
        pass


async def _clear_radar_and_ready_memory() -> None:
    """레이더 및 레디 메모리 초기화."""
    from backend.app.services.engine_account_notify import _rebuild_layout_cache

    async with state.shared_lock:
        # _radar_cnsr_order 삭제: state.master_stocks_cache에서 "_subscribed" 제거
        for entry in state.master_stocks_cache.values():
            entry.pop("_subscribed", None)
        # _sector_stock_layout 제거: state.integrated_system_settings_cache["sector_stock_layout"]로 통합
        state.integrated_system_settings_cache["sector_stock_layout"] = []
        # 실시간 틱 데이터 캐시 clear() 로직 삭제 (_rest_radar_quote_cache)
    _rebuild_layout_cache([])
    state.checked_stocks.clear()
    # _rest_radar_rest_once 제거: 읽기 코드 없음, 기능 부재
    # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음


async def _tracked_ui_stock_codes() -> set[str]:
    """보유·레이더 종목코드(6자리 정규화) -- 시세 표시 대상."""
    from backend.app.services import dry_run
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd

    from backend.app.core.trade_mode import is_test_mode

    out: set[str] = set()
    pos = await dry_run.get_positions() if is_test_mode(state.integrated_system_settings_cache) else list(state.positions)
    for p in pos:
        if int(p.get("qty", 0) or 0) > 0:
            c = _format_broker_reg_stk_cd(str(p.get("stk_cd", "") or ""))
            if c:
                out.add(c)
    # _radar_cnsr_order 삭제: state.master_stocks_cache의 "_subscribed" 사용
    for k, entry in state.master_stocks_cache.items():
        if entry.get("_subscribed", False):
            c = _format_broker_reg_stk_cd(str(k))
            if c:
                out.add(c)
    return out
