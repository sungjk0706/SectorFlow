# -*- coding: utf-8 -*-
"""
엔진 캐시 오케스트레이션.

순환 import 방지: `import app.services.engine_state as _st` 로 상태 접근.
"""
from __future__ import annotations

import asyncio
from types import ModuleType

from app.core.logger import get_logger
import app.services.engine_state as _st

logger = get_logger("engine")


async def _load_caches_preboot(es: ModuleType, settings: dict) -> None:
    """캐시 선행 로드: 장외 시간에만 실행 (장중에는 실시간 데이터가 채움).
    REST 호출 없이 캐시 파일 → 메모리 직접 적재만 수행.

    독립적인 4개 캐시(레이아웃/스냅샷/5일평균/시장구분)를 asyncio.gather()로 병렬 로드.
    종목명 보강은 스냅샷 완료 후 실행 (의존성).
    """
    try:
        from app.core.sector_stock_cache import (
            load_layout_cache, load_snapshot_cache,
            load_stock_name_cache, load_market_map_cache,
        )
        from app.core.avg_amt_cache import load_avg_amt_cache
        from app.core.industry_map import load_eligible_stocks_cache
        from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd, _base_stk_cd
        from app.services.engine_strategy_core import make_detail

        # ── 5개 캐시 병렬 로드 ──
        _cached_layout, _cached_snapshot, _cached_avg_result, _cached_market, _cached_eligible = await asyncio.gather(
            asyncio.to_thread(load_layout_cache),
            asyncio.to_thread(load_snapshot_cache),
            asyncio.to_thread(load_avg_amt_cache),
            asyncio.to_thread(load_market_map_cache),
            asyncio.to_thread(load_eligible_stocks_cache),
        )

        # avg_result 언패킹: (avg_map, high_5d_map) | None
        _cached_avg = _cached_avg_result[0] if _cached_avg_result else None
        _cached_high_5d = _cached_avg_result[1] if _cached_avg_result else None

        # ── 레이아웃 적재 ──
        if _cached_layout:
            es._sector_stock_layout[:] = _cached_layout
            logger.debug("[데이터준비] 레이아웃 저장데이터 로드 -- %d종목",
                        sum(1 for t, _ in _cached_layout if t == "code"))

        # ── 스냅샷 적재 ──
        if _cached_snapshot:
            for cd, detail in _cached_snapshot:
                base = _format_kiwoom_reg_stk_cd(_base_stk_cd(cd))
                amt = int(detail.get("trade_amount") or 0)
                async with es._shared_lock:
                    if amt > 0:
                        es._latest_trade_amounts[base] = amt
                    if base and int(detail.get("cur_price") or 0) > 0:
                        es._rest_radar_quote_cache[base] = detail
                if base and int(detail.get("cur_price") or 0) > 0:
                    es._rest_radar_rest_once.add(base)
                if base not in es._pending_stock_details:
                    entry = make_detail(
                        base, detail.get("name", base) or base,
                        int(detail.get("cur_price") or 0),
                        detail.get("sign", "3"),
                        int(detail.get("change") or 0),
                        float(detail.get("change_rate") or 0.0),
                        prev_close=int(detail.get("prev_close") or 0),
                        trade_amount=amt,
                        strength=detail.get("strength", "-"),
                    )
                    entry["status"] = "active"
                    entry["base_price"] = int(detail.get("cur_price") or 0)
                    entry["target_price"] = int(detail.get("cur_price") or 0)
                    entry["captured_at"] = ""
                    entry["reason"] = "저장데이터 선행 로드"
                    async with es._shared_lock:
                        es._pending_stock_details[base] = entry
                        es._radar_cnsr_order.append(base)
            logger.debug("[데이터준비] 확정데이터 저장데이터 로드 -- %d종목", len(_cached_snapshot))

        # ── 종목명 보강 (스냅샷 완료 후 실행) ──
        _name_map = await asyncio.to_thread(load_stock_name_cache)
        if _name_map:
            _patched = 0
            async with es._shared_lock:
                for cd, entry in es._pending_stock_details.items():
                    nm = _name_map.get(cd)
                    if nm and entry.get("name") in (cd, "", None):
                        entry["name"] = nm
                        _patched += 1
            if _patched:
                logger.debug("[데이터준비] 종목명 보강 -- %d종목", _patched)

        # ── 5일 평균 + 5일 전고점 적재 ──
        if _cached_avg is not None:
            es._update_avg_amt_5d(_cached_avg)
            logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 로드 -- %d종목", len(_cached_avg))
        else:
            from app.core.avg_amt_cache import load_avg_amt_cache_v2, avg_from_v2
            _stale_result = await asyncio.to_thread(load_avg_amt_cache_v2)
            _stale_v2 = _stale_result[0] if _stale_result else None
            if _stale_v2 and len(_stale_v2) > 100:
                _avg_map = avg_from_v2(_stale_v2)
                es._update_avg_amt_5d(_avg_map)
                logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 만료 -- stale 데이터 즉시 로드 (%d종목)", len(_avg_map))  
            else:
                logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 미스 -- 백그라운드 갱신 예정")

        if _cached_high_5d:
            es._high_5d_cache.clear()
            es._high_5d_cache.update(_cached_high_5d)
            logger.debug("[데이터준비] 5일고가 저장데이터 로드 -- %d종목", len(_cached_high_5d))

        # ── 시장구분 적재 ──
        if _cached_market:
            from app.services.engine_symbol_utils import set_market_map, set_nxt_enable_map
            _mkt_map, _nxt_map = _cached_market
            set_market_map(_mkt_map)
            set_nxt_enable_map(_nxt_map)
            _total_nxt = sum(1 for v in _nxt_map.values() if v)
            logger.debug("[데이터준비] 시장구분 저장데이터 로드 -- %d종목 (NXT %d)", len(_mkt_map), _total_nxt)

        # ── 적격종목 적재 (앱준비 에서 get_eligible_stocks() 사용) ──
        if _cached_eligible:
            import app.core.industry_map as _ind_mod
            _ind_mod._eligible_stock_codes = _cached_eligible
            # 매매적격종목 로그는 industry_map.py에서 이미 출력됨 (중복 제거)

        # 캐시선행 완료 플래그 — 앱준비 에서 중복 로드 스킵용
        es._preboot_cache_loaded = True
    except Exception as _cache_err:
        logger.warning("[데이터준비] 저장데이터 로드 실패 (무시, 기존 흐름으로 진행): %s", _cache_err)
