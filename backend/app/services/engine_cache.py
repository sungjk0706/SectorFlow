# -*- coding: utf-8 -*-
"""
엔진 캐시 오케스트레이션.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
"""
from __future__ import annotations

import asyncio
from types import ModuleType

from backend.app.core.logger import get_logger

logger = get_logger("engine")


async def _load_caches_preboot(es: ModuleType, settings: dict) -> None:
    """캐시 선행 로드: 장외 시간에만 실행 (장중에는 실시간 데이터가 채움).
    REST 호출 없이 캐시 파일 → 메모리 직접 적재만 수행.

    독립적인 4개 캐시(레이아웃/스냅샷/5일평균/시장구분)를 asyncio.gather()로 병렬 로드.
    종목명 보강은 스냅샷 완료 후 실행 (의존성).
    """
    try:
        from backend.app.core.sector_stock_cache import (
            load_layout_cache, load_snapshot_cache,
            load_stock_name_cache, load_market_map_cache,
        )
        from backend.app.core.avg_amt_cache import (
            is_avg_amt_5d_map_usable,
            load_avg_amt_from_sector_summary_cache,
            load_avg_amt_cache,
            normalize_avg_amt_5d_value,
        )
        from backend.app.core.industry_map import load_eligible_stocks_cache
        from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd, _base_stk_cd
        from backend.app.services.engine_strategy_core import make_detail

        # ── 5개 캐시 병렬 로드 ──
        from backend.app.db.models import create_stocks_table, create_sectors_table, create_system_settings_table
        from backend.app.db.crud import get_all_stocks
        
        # 테이블이 없으면 생성
        await asyncio.to_thread(create_stocks_table)
        await asyncio.to_thread(create_sectors_table)
        await asyncio.to_thread(create_system_settings_table)

        # sectors 테이블 초기화 로직
        def _init_sectors():
            from backend.app.db.database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO sectors (name)
                    SELECT DISTINCT sector FROM stocks
                    WHERE sector IS NOT NULL AND sector != '' AND sector != '기타'
                """)
                cursor.execute("INSERT OR IGNORE INTO sectors (name) VALUES ('기타')")
                conn.commit()
            except Exception as e:
                logger.warning("[데이터준비] sectors 초기화 실패: %s", e)
            finally:
                conn.close()
        await asyncio.to_thread(_init_sectors)
        
        _db_stocks = await asyncio.to_thread(get_all_stocks)
        _cached_layout, _cached_market, _cached_eligible = await asyncio.gather(
            asyncio.to_thread(load_layout_cache),
            asyncio.to_thread(load_market_map_cache),
            asyncio.to_thread(load_eligible_stocks_cache),
        )
        
        _cached_snapshot = []
        _cached_avg = {}
        _cached_high_5d = {}
        if _db_stocks:
            for stock in _db_stocks:
                cd = stock["code"]
                _cached_avg[cd] = normalize_avg_amt_5d_value(stock.get("avg_5d_trade_amount"))
                _cached_high_5d[cd] = int(stock.get("high_5d_price") or 0)
                detail = {
                    "name": stock.get("name", cd),
                    "sector": stock.get("sector", "기타"),
                    "cur_price": stock.get("cur_price", stock.get("prev_close", 0)),
                    "sign": stock.get("sign", "3"),
                    "change": stock.get("change", 0),
                    "change_rate": stock.get("change_rate", 0.0),
                    "prev_close": stock.get("prev_close", 0),
                    "trade_amount": stock.get("trade_amount", stock.get("avg_5d_trade_amount", 0)),
                    "high_price": stock.get("today_high_price", stock.get("high_5d_price", 0)),
                    "strength": stock.get("strength", "-"),
                }
                _cached_snapshot.append((cd, detail))

        # ── 레이아웃 적재 ──
        if _cached_layout:
            es._sector_stock_layout[:] = _cached_layout
            from backend.app.services.engine_account_notify import _rebuild_layout_cache
            _rebuild_layout_cache(_cached_layout)
            logger.debug("[데이터준비] 레이아웃 저장데이터 로드 -- %d종목",
                        sum(1 for t, _ in _cached_layout if t == "code"))

        # ── 스냅샷 적재 ──
        if _cached_snapshot:
            async with es._shared_lock:
                for cd, detail in _cached_snapshot:
                    base = _format_kiwoom_reg_stk_cd(_base_stk_cd(cd))
                    amt = int(detail.get("trade_amount") or 0)
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
                            sector=detail.get("sector", "기타"),
                        )
                        entry["status"] = "active"
                        entry["base_price"] = int(detail.get("cur_price") or 0)
                        entry["target_price"] = int(detail.get("cur_price") or 0)
                        entry["captured_at"] = ""
                        entry["reason"] = "저장데이터 선행 로드"
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
        if _cached_avg is not None and not is_avg_amt_5d_map_usable(_cached_avg):
            recovered_avg = await asyncio.to_thread(load_avg_amt_from_sector_summary_cache)
            if is_avg_amt_5d_map_usable(recovered_avg):
                _cached_avg = recovered_avg
                logger.warning("[데이터준비] stocks DB 5일평균 비정상 -- SectorSummary 캐시에서 복구 (%d종목)", len(_cached_avg))
            else:
                cached_result = await asyncio.to_thread(load_avg_amt_cache)
                if cached_result and is_avg_amt_5d_map_usable(cached_result[0]):
                    _cached_avg, _cached_high_5d = cached_result
                    logger.warning("[데이터준비] stocks DB 5일평균 비정상 -- avg_amt 캐시에서 복구 (%d종목)", len(_cached_avg))

        if _cached_avg is not None:
            es._update_avg_amt_5d(_cached_avg)
            logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 로드 -- %d종목", len(_cached_avg))
        else:
            from backend.app.core.avg_amt_cache import load_avg_amt_cache_v2, avg_from_v2
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
            from backend.app.services.engine_symbol_utils import set_market_map, set_nxt_enable_map
            _mkt_map, _nxt_map = _cached_market
            set_market_map(_mkt_map)
            set_nxt_enable_map(_nxt_map)
            _total_nxt = sum(1 for v in _nxt_map.values() if v)
            logger.debug("[데이터준비] 시장구분 저장데이터 로드 -- %d종목 (NXT %d)", len(_mkt_map), _total_nxt)

        # ── 적격종목 적재 (앱준비 에서 get_eligible_stocks() 사용) ──
        if _cached_eligible:
            import backend.app.core.industry_map as _ind_mod
            _ind_mod._eligible_stock_codes = _cached_eligible
            # 매매적격종목 로그는 industry_map.py에서 이미 출력됨 (중복 제거)

        # 캐시선행 완료 플래그 — 앱준비 에서 중복 로드 스킵용
        es._preboot_cache_loaded = True
    except Exception as _cache_err:
        logger.warning("[데이터준비] 저장데이터 로드 실패 (무시, 기존 흐름으로 진행): %s", _cache_err)
