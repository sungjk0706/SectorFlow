# -*- coding: utf-8 -*-
"""
엔진 캐시 오케스트레이션.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
"""
from __future__ import annotations
import asyncio
import logging
from backend.app.services import engine_state
logger = logging.getLogger(__name__)


async def _load_caches_preboot(settings: dict) -> None:
    """캐시 선행 로드: 장외 시간에만 실행 (장중에는 실시간 데이터가 채움).
    REST 호출 없이 캐시 파일 → 메모리 직접 적재만 수행.

    단일 파이프라인: DB 로드 → 업종 레이아웃 구성 → 5일 메트릭 연산 → 필터링 → 구독.
    """
    try:

        # ── master_stocks_table 로드 ──
        from backend.app.db.stock_tables import load_master_stocks_table
        _cached_snapshot = await load_master_stocks_table()
        
        # master_stocks_table이 없으면 앱 기동 실패 (명확한 에러)
        if not _cached_snapshot:
            raise RuntimeError("master_stocks_table 테이블에 데이터가 없습니다. 장마감 후 다시 시도하세요.")
        
        # 마스터 캐시 저장 (_sector_cache 제거)
        engine_state.state.master_stocks_cache = _cached_snapshot

        # ── 업종 레이아웃 자동 구성 (engine_bootstrap.py에서 이동) ──
        from collections import defaultdict
        from itertools import chain

        sector_groups: defaultdict[str, list[str]] = defaultdict(list)
        for code in _cached_snapshot.keys():
            sector = _cached_snapshot[code].get("sector", "미분류")
            sector_groups[sector].append(code)

        # 업종 순서: 기존 레이아웃의 업종 순서를 최대한 유지하고 신규 업종는 뒤에 추가
        old_layout: list[tuple[str, str]] = engine_state.state.integrated_system_settings_cache["sector_stock_layout"]
        old_sector_order = list(dict.fromkeys(v for t, v in old_layout if t == "sector"))
        new_sectors = [s for s in sector_groups if s not in old_sector_order]
        final_sector_order = [s for s in old_sector_order if s in sector_groups] + new_sectors

        # auto_layout - 커스텀 업종 순서 보장
        sector_blocks = map(
            lambda sec: [("sector", sec)] + list(map(lambda cd: ("code", cd), sector_groups[sec])),
            final_sector_order
        )
        auto_layout: list[tuple[str, str]] = list(chain.from_iterable(sector_blocks))
        engine_state.state.integrated_system_settings_cache["sector_stock_layout"] = auto_layout

        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache(auto_layout)
        logger.debug(
            "[데이터] 업종 매핑 기반 자동 구성 — %d종목 / %d업종",
            sum(1 for t, _ in auto_layout if t == "code"),
            len(sector_groups),
        )

        # ── 5일평균/고가 로드 및 메모리 반영 (단일 루프 통합) ──
        _cached_avg = {}
        _cached_high_5d = {}

        for cd, detail in _cached_snapshot.items():
            # 단일 소스 진리: 백만원 단위 그대로 저장
            avg_amt = int(detail.get("avg_5d_trade_amount") or 0)
            high_5d = int(detail.get("high_5d_price") or 0)
            _cached_avg[cd] = avg_amt
            _cached_high_5d[cd] = high_5d
            # 즉시 메모리 반영 (단일 루프로 통합)
            if high_5d > 0:
                if cd in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[cd]["high_5d_price"] = high_5d

        # ── [수정] 기동 시 단건 실시간 구독 신청 루프 및 asyncio.gather 제거 ──
        # 로그인 이후 배치 파이프라인에서 일괄 등록되므로 기동 단계에서는 스킵합니다.
        logger.info("[데이터] 선행 캐시 로드 완료 (메모리 반영 및 인덱싱 완료)")

        # ── 5일 평균 + 5일 전고점 적재 ──
        if sum(1 for v in _cached_avg.values() if int(v or 0) > 0) < 100:
            logger.warning("[데이터] 주식 DB 5일평균 비정상 — 백그라운드 갱신 예정")

        logger.debug("[데이터] 5일거래대금평균/고가 저장데이터 로드 — %d종목", len(_cached_avg))

        # ── 시장구분 적재 제거 (master_stocks_cache 사용으로 대체) ──
        _total_nxt = sum(1 for v in engine_state.state.master_stocks_cache.values() if v.get("nxt_enable"))
        logger.debug("[데이터] 시장구분(마스터 캐시) 로드 완료 — %d종목 (NXT %d)", len(engine_state.state.master_stocks_cache), _total_nxt)

        # 캐시선행 완료 플래그 — 앱준비 에서 중복 로드 스킵용
        engine_state.state.preboot_cache_loaded = True

        # ── WS 구독 구간 내 기동 시 실시간 필드 초기화 (DB 로드 이후 실행 보장) ──
        # _init_ws_subscribe_state()와 경쟁하지 않도록 preboot_cache_loaded 플래그로 조정
        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
        _in_ws_window = await is_ws_subscribe_window(settings)
        if _in_ws_window:
            from backend.app.services.engine_snapshot import _reset_realtime_fields
            await _reset_realtime_fields()
            # ── 4단계: 사전 트리거 멱등성 플래그 동기화 (중복 실행 방지) ──
            from backend.app.services.daily_time_scheduler import _kst_now
            engine_state.state.last_realtime_reset_date = _kst_now().strftime("%Y%m%d")
            logger.info("[데이터] 실시간 통신 구독 구간 — 실시간 필드 초기화 완료 (DB 로드 후)")

        # ── 기동 완료 로직 ──
        # 테스트모드: Settlement Engine 상태 로드 (설정 test_virtual_deposit 우선, DB 없으면 초기화)
        if engine_state.state.integrated_system_settings_cache["trade_mode"] == "test":
            from backend.app.services import settlement_engine
            initial_deposit = engine_state.state.integrated_system_settings_cache["test_virtual_deposit"]
            await settlement_engine.load_state(initial_deposit=initial_deposit)
            logger.debug("[데이터] 정산 엔진 상태 로드 완료 (테스트모드)")
            # 기동 시 정합성 대조 — fake_fill_event 태스크 실패로 인한 잔고 불일치 복구 (B5-08-03, P22)
            await settlement_engine.reconcile_with_trades()

        from backend.app.services.engine_account_notify import notify_cache
        notify_cache.prev_scores = []

        # 기동 완료 플래그 설정
        engine_state.state.bootstrap_event.set()

        engine_state.state.data_ready_event.set()

        # 업종순위 캐시 초기 계산
        # WS 구간 내: _init_ws_subscribe_state가 _sector_summary_cache를 클리어하므로
        #   1차 계산 결과가 무효화됨. _login_post_pipeline에서 계산하므로 여기서는 스킵.
        #   UI 블로킹 방지를 위해 sector_summary_ready_event만 set.
        # WS 구간 외: 유일한 계산 경로이므로 반드시 수행.
        if _in_ws_window:
            engine_state.state.sector_summary_ready_event.set()
            logger.info("[데이터] 실시간 통신 구독 구간 — 업종순위 계산 생략 (로그인 후 파이프라인에서 수행)")
        else:
            from backend.app.services.sector_data_provider import recompute_sector_summary_now
            _task = asyncio.create_task(recompute_sector_summary_now())
            _task.add_done_callback(lambda t: logger.warning("[데이터] 업종순위 계산 작업 실패: %s", t.exception()) if t.exception() else None)
            logger.info("[데이터] 업종순위 계산 백그라운드 실행 (섹터 요약 준비 이벤트 대기)")

        # 앱준비 완료 → 기동 시 스킵된 장마감 파이프라인 데이터동기화중 재시도
        # 백그라운드 실행: data_ready_event / bootstrap_event 이미 set() 상태이므로
        # WS 핸들러가 정상 동작하며, catch-up이 블로킹하지 않음
        try:
            from backend.app.services.daily_time_scheduler import retry_pipeline_catchup_after_bootstrap
            _task2 = asyncio.create_task(retry_pipeline_catchup_after_bootstrap())
            _task2.add_done_callback(lambda t: logger.warning("[데이터] 데이터동기화중 재시도 작업 실패: %s", t.exception()) if t.exception() else None)
        except Exception as _catchup_err:
            logger.warning("[데이터] 데이터동기화중 재시도 실패(무시): %s", _catchup_err, exc_info=True)

    except Exception as _cache_err:
        # 치명 오류 (master_stocks_table 없음 포함)를 "무시하고 진행"하지 않음 (P20 폴백 금지).
        # log-and-rethrow — 호출자(engine_loop.py:34)에서 "감소 모드로 기동" 에러 로그 +
        # engine-ready 화면 전송(P21) 처리. 빈 캐시로 정상인 척 진행하는 것 차단.
        logger.error("[데이터] 캐시 선행 로드 치명 오류: %s", _cache_err, exc_info=True)
        raise
