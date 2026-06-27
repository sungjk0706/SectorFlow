from __future__ import annotations
# -*- coding: utf-8 -*-
"""
엔진 캐시 오케스트레이션.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
"""

import asyncio

from backend.app.core.logger import get_logger
from backend.app.services.engine_state import state

logger = get_logger("engine")

# 구독 동시성 상한 (앱 기동 시 일회성 구독 준비)
_subscribe_semaphore = asyncio.Semaphore(50)


async def _load_caches_preboot(settings: dict) -> None:
    """캐시 선행 로드: 장외 시간에만 실행 (장중에는 실시간 데이터가 채움).
    REST 호출 없이 캐시 파일 → 메모리 직접 적재만 수행.

    단일 파이프라인: DB 로드 → 업종 레이아웃 구성 → 5일 메트릭 연산 → 필터링 → 구독.
    """
    try:
        from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd, _base_stk_cd
        from backend.app.services.engine_strategy_core import make_detail

        # ── master_stocks_table 로드 ──
        from backend.app.db.stock_tables import load_master_stocks_table
        _cached_snapshot = await load_master_stocks_table()
        
        # master_stocks_table이 없으면 앱 기동 실패 (명확한 에러)
        if not _cached_snapshot:
            raise RuntimeError("master_stocks_table 테이블에 데이터가 없습니다. 장마감 후 다시 시도하세요.")
        
        # 마스터 캐시 저장 (_sector_cache 제거)
        state.master_stocks_cache = _cached_snapshot

        # ── 업종 레이아웃 자동 구성 (engine_bootstrap.py에서 이동) ──
        from collections import defaultdict
        from itertools import chain

        sector_groups: defaultdict[str, list[str]] = defaultdict(list)
        for code in _cached_snapshot.keys():
            sector = _cached_snapshot[code].get("sector", "기타")
            sector_groups[sector].append(code)

        # 섹터 순서: 기존 레이아웃의 섹터 순서를 최대한 유지하고 신규 섹터는 뒤에 추가
        old_layout: list[tuple[str, str]] = state.integrated_system_settings_cache["sector_stock_layout"]
        old_sector_order = list(dict.fromkeys(v for t, v in old_layout if t == "sector"))
        new_sectors = [s for s in sector_groups if s not in old_sector_order]
        final_sector_order = [s for s in old_sector_order if s in sector_groups] + new_sectors

        # auto_layout - 커스텀 업종 순서 보장
        sector_blocks = map(
            lambda sec: [("sector", sec)] + list(map(lambda cd: ("code", cd), sector_groups[sec])),
            final_sector_order
        )
        auto_layout: list[tuple[str, str]] = list(chain.from_iterable(sector_blocks))
        state.integrated_system_settings_cache["sector_stock_layout"] = auto_layout

        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache(auto_layout)
        logger.debug(
            "[데이터준비] 업종 매핑 기반 자동 구성 -- %d종목 / %d섹터",
            sum(1 for t, _ in auto_layout if t == "code"),
            len(sector_groups),
        )

        # ── 5일평균/고가 로드 및 메모리 반영 (단일 루프 통합) ──
        _cached_avg = {}
        _cached_high_5d = {}

        for cd, detail in _cached_snapshot.items():
            # 단일 소스 진리: 백만원 단위 그대로 저장
            avg_amt = int(detail.get("avg_5d_trade_amount") or 0)
            high_price = int(detail.get("high_price") or 0)
            _cached_avg[cd] = avg_amt
            _cached_high_5d[cd] = high_price
            # 즉시 메모리 반영 (단일 루프로 통합)
            if high_price > 0:
                if cd in state.master_stocks_cache:
                    state.master_stocks_cache[cd]["high_5d_price"] = high_price

        # eligible_stocks_cache 로드 제거: master_stocks_table이 단일 소스

        # ── [수정] 기동 시 단건 실시간 구독 신청 루프 및 asyncio.gather 제거 ──
        # 로그인 이후 배치 파이프라인에서 일괄 등록되므로 기동 단계에서는 스킵합니다.
        logger.info("[데이터준비] 선행 캐시 로드 완료 (메모리 반영 및 인덱싱 완료)")

        # ── 5일 평균 + 5일 전고점 적재 ──
        if _cached_avg is not None and sum(1 for v in _cached_avg.values() if int(v or 0) > 0) < 100:
            logger.info("[데이터준비] stocks DB 5일평균 비정상 -- 백그라운드 갱신 예정")

        # _update_avg_amt_5d 제거: _master_stocks_cache가 단일 소스
        if _cached_avg is not None:
            logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 로드 -- %d종목", len(_cached_avg))
        else:
            logger.debug("[데이터준비] 5일거래대금평균/고가 저장데이터 미스 -- 백그라운드 갱신 예정")

        # ── 시장구분 적재 제거 (master_stocks_cache 사용으로 대체) ──
        all_stocks = state.master_stocks_cache.copy()
        _total_nxt = sum(1 for v in all_stocks.values() if v.get("nxt_enable"))
        logger.debug("[데이터준비] 시장구분(마스터 캐시) 로드 완료 -- %d종목 (NXT %d)", len(all_stocks), _total_nxt)

        # eligible_stocks_cache 적재 제거: master_stocks_table이 단일 소스

        # 캐시선행 완료 플래그 — 앱준비 에서 중복 로드 스킵용
        state.preboot_cache_loaded = True

        # ── 기동 완료 로직 이관 (engine_bootstrap.py _bootstrap_sector_stocks_async에서 이관) ──
        # 테스트모드: Settlement Engine 초기화 (기본값 설정)
        if state.integrated_system_settings_cache["trade_mode"] == "test":
            from backend.app.services import settlement_engine
            initial_deposit = state.integrated_system_settings_cache["test_virtual_deposit"]
            settlement_engine.init(initial_deposit)
            logger.debug("[데이터준비] Settlement Engine 초기화 완료 (테스트모드)")

        import backend.app.services.engine_account_notify as _an
        _an._prev_scores_cache = []

        # 기동 완료 플래그 설정
        state.bootstrap_event.set()

        state.data_ready_event.set()

        # 업종순위 캐시 초기 계산 — 기동 시 무조건 1회 수행
        # (WS 구간 내: 이후 _login_post_pipeline이 재계산, WS 구간 외: 유일한 계산 경로)
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        await recompute_sector_summary_now()

        # 앱준비 완료 → 기동 시 스킵된 장마감 파이프라인 데이터동기화중 재시도
        try:
            from backend.app.services.daily_time_scheduler import retry_pipeline_catchup_after_bootstrap
            await retry_pipeline_catchup_after_bootstrap()
        except Exception as _catchup_err:
            logger.warning("[데이터준비] 데이터동기화중 재시도 실패(무시): %s", _catchup_err, exc_info=True)

    except Exception as _cache_err:
        logger.info("[데이터준비] 저장데이터 로드 실패 (무시, 기존 흐름으로 진행): %s", _cache_err)
