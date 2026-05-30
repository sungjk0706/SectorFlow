# -*- coding: utf-8 -*-
"""
레이더/종목 관련 모듈
- 레이더 종목 관리
- 종목 상태 관리
- 실시간 데이터 보강
"""
import asyncio
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import (
    # _pending_stock_details 제거: _radar_cnsr_order + _master_stocks_cache로 대체
    _sector_stock_layout,
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_latest_trade_prices, _latest_trade_amounts, _rest_radar_quote_cache)
    _shared_lock,
    _radar_cnsr_order,
    _invalidate_sector_stocks_cache,
    _rest_radar_rest_once,
    _checked_stocks,
    _settings_cache,
    _positions,
)

logger = get_logger("engine_radar")


# ── 레이더/종목 조회 ─────────────────────────────────────────────────

def get_pending_stocks() -> list:
    """활성 상태의 종목 목록 반환."""
    # _pending_stock_details 제거: _radar_cnsr_order + _master_stocks_cache로 대체
    from backend.app.services.engine_state import _master_stocks_cache
    result = []
    for cd in _radar_cnsr_order:
        if cd in _master_stocks_cache:
            stock = _master_stocks_cache[cd].copy()
            stock["status"] = "active"  # _radar_cnsr_order에 있으면 active
            result.append(stock)
    return result


def get_sector_stock_layout() -> list[tuple[str, str]]:
    """업종 종목 레이아웃 반환."""
    return list(_sector_stock_layout)


def get_avg_amt_5d_map() -> dict[str, int]:
    """5일 평균 거래대금 맵 반환."""
    from backend.app.services.engine_state import _master_stocks_cache
    return {cd: stock.get("avg_5d_trade_amount", 0) for cd, stock in _master_stocks_cache.items()}


def get_high_5d_cache() -> dict[str, int]:
    """5일 전고점 캐시 반환."""
    from backend.app.services.engine_state import _master_stocks_cache
    return {cd: int(stock.get("high_5d_price", 0) or 0) for cd, stock in _master_stocks_cache.items()}


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
    """FID 13·14가 있는 틱에서만 캐시 갱신. 없으면 캐시가 있을 때만 행 보강(0으로 덮지 않음)."""
    from backend.app.services import engine_radar_ops

    async with _shared_lock:
        engine_radar_ops.apply_real01_volume_amount_to_radar_rows(
            raw_cd,
            vals,
            {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 전달
            {},  # _pending_stock_details 제거: 빈 dict 전달
            is_0b_tick=is_0b_tick,
        )


# ── 레이더 종목 관리 ─────────────────────────────────────────────────

async def _mark_radar_exited(stk_cd: str) -> None:
    """
    레이더 목록에서 종목 제거.
    _pending_stock_details 제거: _radar_cnsr_order에서만 제거
    """
    from backend.app.services.engine_symbol_utils import _normalize_stk_cd_rest

    nk = _normalize_stk_cd_rest(str(stk_cd).strip().lstrip("A"))
    rm: str | None = None
    if nk in _radar_cnsr_order:
        rm = nk
    else:
        for k in list(_radar_cnsr_order):
            if _normalize_stk_cd_rest(str(k)) == nk:
                rm = k
                break
    if rm is not None:
        _radar_cnsr_order[:] = [x for x in _radar_cnsr_order if x != rm]
        if _clear_radar_rest_bootstrap_for_stk_cd:
            await _clear_radar_rest_bootstrap_for_stk_cd(rm)
        if _invalidate_sector_stocks_cache:
            _invalidate_sector_stocks_cache()


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
        _rest_radar_rest_once.discard(nk)


async def _clear_radar_and_ready_memory() -> None:
    """레이더 및 레디 메모리 초기화."""
    from backend.app.services.engine_account_notify import _rebuild_layout_cache

    async with _shared_lock:
        # _pending_stock_details 제거: clear() 제거
        _radar_cnsr_order.clear()
        _sector_stock_layout.clear()
        # 실시간 틱 데이터 캐시 clear() 로직 삭제 (_rest_radar_quote_cache)
    _rebuild_layout_cache(_sector_stock_layout)
    _checked_stocks.clear()
    _rest_radar_rest_once.clear()
    if _invalidate_sector_stocks_cache:
        _invalidate_sector_stocks_cache()


async def _tracked_ui_stock_codes() -> set[str]:
    """보유·레이더 종목코드(6자리 정규화) -- 시세 표시 대상."""
    from backend.app.services import dry_run
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd

    from backend.app.core.trade_mode import is_test_mode

    out: set[str] = set()
    pos = await dry_run.get_positions() if is_test_mode(_settings_cache) else list(_positions)
    for p in pos:
        if int(p.get("qty", 0) or 0) > 0:
            c = _format_broker_reg_stk_cd(str(p.get("stk_cd", "") or ""))
            if c:
                out.add(c)
    # _pending_stock_details 제거: _radar_cnsr_order 사용
    for k in _radar_cnsr_order:
        c = _format_broker_reg_stk_cd(str(k))
        if c:
            out.add(c)
    return out
