from __future__ import annotations
# -*- coding: utf-8 -*-
"""
엔진 캐시 오케스트레이션.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
"""

import asyncio

from backend.app.core.logger import get_logger
from backend.app.services.engine_state import (
    _sector_stock_layout,
    _shared_lock,
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_latest_trade_amounts, _rest_radar_quote_cache)
    _rest_radar_rest_once,
    # _pending_stock_details 제거
    _radar_cnsr_order,
    _high_5d_cache,
)

logger = get_logger("engine")


async def _load_caches_preboot(settings: dict) -> None:
    """캐시 선행 로드: 장외 시간에만 실행 (장중에는 실시간 데이터가 채움).
    REST 호출 없이 캐시 파일 → 메모리 직접 적재만 수행.

    독립적인 4개 캐시(레이아웃/스냅샷/5일평균/시장구분)를 asyncio.gather()로 병렬 로드.
    종목명 보강은 스냅샷 완료 후 실행 (의존성).
    """
    try:
        from backend.app.core.sector_stock_cache import (
            load_stock_name_cache,
        )
        from backend.app.core.industry_map import load_eligible_stocks_cache
        from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd, _base_stk_cd
        from backend.app.services.engine_strategy_core import make_detail

        # ── 테이블 초기화 ──
        from backend.app.db.models import create_sectors_table, create_user_settings_table
        from backend.app.db.stock_tables import create_master_stocks_table, migrate_add_high_price_column, migrate_add_nxt_enable_column

        # 테이블이 없으면 생성
        await create_sectors_table()
        await create_user_settings_table()
        await create_master_stocks_table()
        
        # 마이그레이션: high_price 컬럼 추가
        await migrate_add_high_price_column()
        # 마이그레이션: nxt_enable 컬럼 추가
        await migrate_add_nxt_enable_column()

        # sectors 테이블 초기화 로직
        async def _init_sectors():
            from backend.app.db.database import get_db_connection
            conn = await get_db_connection()
            try:
                await conn.execute("""
                    INSERT OR IGNORE INTO sectors (name)
                    SELECT DISTINCT sector FROM master_stocks_table
                    WHERE sector IS NOT NULL AND sector != '' AND sector != '기타'
                """)
                await conn.execute("INSERT OR IGNORE INTO sectors (name) VALUES ('기타')")
                await conn.commit()
            except Exception as e:
                logger.warning("[데이터준비] sectors 초기화 실패: %s", e)
        await _init_sectors()
        
        # ── master_stocks_table 로드 ──
        from backend.app.db.stock_tables import load_master_stocks_table
        _cached_snapshot, _sector_cache = await load_master_stocks_table()
        
        # master_stocks_table이 없으면 앱 기동 실패 (명확한 에러)
        if not _cached_snapshot:
            raise RuntimeError("master_stocks_table 테이블에 데이터가 없습니다. 장마감 후 다시 시도하세요.")
        
        # sector 캐시 및 마스터 캐시 저장
        import backend.app.services.engine_state as _st
        _st._sector_cache = _sector_cache
        _st._master_stocks_cache = _cached_snapshot
        
        # ── 5일평균/고가 로드 및 5일 배열 복원 ──
        _cached_avg = {}
        _cached_high_5d = {}
        _amts_5d_arrays = getattr(_st, "_amts_5d_arrays", {})
        _highs_5d_arrays = getattr(_st, "_highs_5d_arrays", {})
        
        for cd, detail in _cached_snapshot.items():
            _cached_avg[cd] = int(detail.get("avg_5d_trade_amount") or 0)
            _cached_high_5d[cd] = int(detail.get("high_price") or 0)
            # 5일봉 시계열 배열 복원
            if "amts_5d_array" in detail:
                _amts_5d_arrays[cd] = detail["amts_5d_array"]
            if "highs_5d_array" in detail:
                _highs_5d_arrays[cd] = detail["highs_5d_array"]
        
        # ── 적격종목 로드 (유지) ──
        _cached_eligible = await load_eligible_stocks_cache()

        # ── 레이아웃 적재 삭제 (master_stocks_table sector 컬럼으로 대체) ──

        # ── 스냅샷 적재 ──
        # _pending_stock_details 제거: _radar_cnsr_order에만 코드 추가
        if _cached_snapshot:
            async with _shared_lock:
                for cd, detail in _cached_snapshot.items():
                    base = _format_kiwoom_reg_stk_cd(_base_stk_cd(cd))
                    # 실시간 틱 데이터 저장 제거 (거래대금, REST 캐시 저장 안 함)
                    if base and int(detail.get("cur_price") or 0) > 0:
                        _rest_radar_rest_once.add(base)
                    if base not in _radar_cnsr_order:
                        _radar_cnsr_order.append(base)
            logger.debug("[데이터준비] 확정데이터 저장데이터 로드 -- %d종목", len(_cached_snapshot))

        # ── 종목명 보강 (스냅샷 완료 후 실행) ──
        # _pending_stock_details 제거: 종목명 보강 불필요 (_master_stocks_cache 사용)

        # ── 5일 평균 + 5일 전고점 적재 ──
        if _cached_avg is not None and sum(1 for v in _cached_avg.values() if int(v or 0) > 0) < 100:
            logger.info("[데이터준비] stocks DB 5일평균 비정상 -- 백그라운드 갱신 예정")

        if _cached_avg is not None:
            from backend.app.services.engine_sector import _update_avg_amt_5d
            _update_avg_amt_5d(_cached_avg)
            logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 로드 -- %d종목", len(_cached_avg))
        else:
            logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 미스 -- 백그라운드 갱신 예정")

        if _cached_high_5d:
            for key, value in _cached_high_5d.items():
                if key in _st._master_stocks_cache:
                    _st._master_stocks_cache[key]["high_5d_price"] = value
            logger.debug("[데이터준비] 5일고가 저장데이터 로드 -- %d종목", len(_cached_high_5d))

        # ── 시장구분 적재 제거 (master_stocks_cache 사용으로 대체) ──
        _total_nxt = sum(1 for v in _st._master_stocks_cache.values() if v.get("nxt_enable"))
        logger.debug("[데이터준비] 시장구분(마스터 캐시) 로드 완료 -- %d종목 (NXT %d)", len(_st._master_stocks_cache), _total_nxt)

        # ── 적격종목 적재 (앱준비 에서 get_eligible_stocks() 사용) ──
        if _cached_eligible:
            import backend.app.core.industry_map as _ind_mod
            _ind_mod._eligible_stock_codes = _cached_eligible
            # 매매적격종목 로그는 industry_map.py에서 이미 출력됨 (중복 제거)

        # 캐시선행 완료 플래그 — 앱준비 에서 중복 로드 스킵용
        import backend.app.services.engine_state as engine_state
        engine_state._preboot_cache_loaded = True
    except Exception as _cache_err:
        logger.info("[데이터준비] 저장데이터 로드 실패 (무시, 기존 흐름으로 진행): %s", _cache_err)
