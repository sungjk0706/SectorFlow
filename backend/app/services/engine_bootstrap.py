from __future__ import annotations
# -*- coding: utf-8 -*-
"""
엔진 부트스트랩 흐름.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
engine_service의 함수가 필요하면 lazy import (`from backend.app.services import engine_service`).
"""

import asyncio

from backend.app.core.logger import get_logger
import backend.app.services.engine_state as _st

logger = get_logger("engine")

# 구독 동시성 상한 (앱 기동 시 일회성 구독 준비)
_subscribe_semaphore = asyncio.Semaphore(50)

# ── 앱준비 단계 정의 (하드코딩 금지 — len()으로 total 산출) ──
BOOTSTRAP_STAGES = [
    (1, "레이아웃 저장데이터 확인"),
    (2, "섹터 매핑 로드"),
    (3, "KRX 확정데이터 로드 중"),
    (4, "시세 데이터 반영"),
    (5, "5일 평균 저장데이터 로드"),
    (6, "앱준비 완료"),
]


def _broadcast_bootstrap_stage(
    stage_id: int, stage_name: str,
    progress: dict | None = None,
) -> None:
    """부트스트랩 단계 브로드캐스트."""
    try:
        from backend.app.web.ws_manager import ws_manager
        payload = {
            "_v": 1,
            "stage_id": stage_id,
            "stage_name": stage_name,
            "total": len(BOOTSTRAP_STAGES),
        }
        if progress is not None:
            payload["progress"] = progress
        ws_manager.broadcast("bootstrap-stage", payload)
    except Exception as e:
        logger.warning("[시작] stage 브로드캐스트 실패 %s: %s", stage_name, e, exc_info=True)


async def _bootstrap_sector_stocks_async() -> None:
    """
    DB 기반 전체 종목 초기 시세 로드 (Read-Only Cache).
    기동 시 무조건 master_stocks_table에서 Eager 로딩.
    """
    try:
        _already_ready = _st._bootstrap_event.is_set()
        if not _already_ready:
            _st._bootstrap_event.clear()
            _st._sector_summary_ready_event.clear()

        # ── 테스트모드: Settlement Engine 상태 복원 ──
        if (_st._integrated_system_settings_cache or {}).get("trade_mode") == "test":
            from backend.app.services import settlement_engine
            await settlement_engine._load()
            logger.debug("[시작] Settlement Engine 상태 복원 완료 (테스트모드)")

        from backend.app.services.engine_symbol_utils import _base_stk_cd
        from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd

        # ── 0단계: master_stocks_table 기반 Eager 로딩 ───────────────────────
        _broadcast_bootstrap_stage(1, "DB 마스터 로드 중")
        logger.info("[시작] master_stocks_table에서 전체 종목 Eager 로딩 시작...")

        # _load_caches_preboot에서 이미 로드된 _master_stocks_cache 재사용 (중복 DB 조회 제거)
        loaded_data = _st._master_stocks_cache

        if not loaded_data:
            logger.warning("[시작] master_stocks_table에 데이터 없음 -- 장마감 후 수동 확정시세 실행 필요")
            _broadcast_bootstrap_stage(6, "앱준비 완료")
            _st._bootstrap_event.set()
            _st._sector_summary_ready_event.set()
            from backend.app.services import engine_service
            engine_service._data_ready_event.set()
            return

        logger.info("[시작] master_stocks_table %d종목 메모리 Eager 로딩 완료!", len(loaded_data))
        _broadcast_bootstrap_stage(2, "섹터 매핑 로드")

        # ── 1단계: 업종별 레이아웃 자동 구성 ───────────────────────────────
        from collections import defaultdict
        from itertools import chain

        sector_groups: defaultdict[str, list[str]] = defaultdict(list)
        for code in loaded_data.keys():
            sector = loaded_data[code].get("sector", "기타")
            sector_groups[sector].append(code)

        # 섹터 순서: 기존 레이아웃의 섹터 순서를 최대한 유지하고 신규 섹터는 뒤에 추가
        # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
        old_layout: list[tuple[str, str]] = _st._integrated_system_settings_cache.get("sector_stock_layout", [])
        old_sector_order = list(dict.fromkeys(v for t, v in old_layout if t == "sector"))
        new_sectors = [s for s in sector_groups if s not in old_sector_order]
        final_sector_order = [s for s in old_sector_order if s in sector_groups] + new_sectors

        # auto_layout - 커스텀 업종 순서 보장
        sector_blocks = map(
            lambda sec: [("sector", sec)] + list(map(lambda cd: ("code", cd), sector_groups[sec])),
            final_sector_order
        )
        auto_layout: list[tuple[str, str]] = list(chain.from_iterable(sector_blocks))
        _st._integrated_system_settings_cache["sector_stock_layout"] = auto_layout

        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache(auto_layout)
        logger.debug(
            "[시작] 업종 매핑 기반 자동 구성 -- %d종목 / %d섹터",
            sum(1 for t, _ in auto_layout if t == "code"),
            len(sector_groups),
        )

        codes: list[str] = [v for t, v in auto_layout if t == "code"]
        if not codes:
            logger.debug("[시작] 업종맵 종목 없음 -- 업종 요약정보 생성 계속 진행")
            # early return 제거: 업종 요약정보는 codes와 무관하게 생성

        # ── WS 구독 구간 판정 ─────────────────────────────────────────────
        try:
            from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
            _in_ws_window = await is_ws_subscribe_window(_st._integrated_system_settings_cache)
        except Exception:
            logger.warning("[시작] WS 구독 구간 판정 실패", exc_info=True)
            _in_ws_window = False

        # ── 2단계: 시세 데이터 반영 ─────────────────────────────────────────
        _broadcast_bootstrap_stage(3, "시세 데이터 반영")
        krx_rows: list[tuple[str, dict]] = [(code, data) for code, data in loaded_data.items()]

        # 거래대금 버킷 세팅
        filtered = filter(
            lambda x: _format_kiwoom_reg_stk_cd(_base_stk_cd(x[0])) and int(x[1].get("cur_price") or 0) > 0,
            krx_rows
        )
        bases_to_add = list(map(lambda x: _format_kiwoom_reg_stk_cd(_base_stk_cd(x[0])), filtered))
        # _rest_radar_rest_once 제거: 읽기 코드 없음, 기능 부재
        # async with _st._shared_lock:
        #     for item in bases_to_add:
        #         _st._rest_radar_rest_once.add(item)

        logger.debug("[시작] REST 버킷 세팅 완료")

        # 화면 표시용 엔트리 생성
        # _radar_cnsr_order 삭제: 필터링된 종목만 바로 구독 신청
        # sector_min_trade_amt 필터링 적용 (설계 의도 준수)
        if krx_rows:
            # 단일 소스 진리: _integrated_system_settings_cache 직접 사용
            min_amt = float(_st._integrated_system_settings_cache.get("sector_min_trade_amt", 0.0) or 0.0)

            # 필터링 적용 후 바로 구독 신청
            filtered_codes = []
            for code, data in krx_rows:
                base = _format_kiwoom_reg_stk_cd(_base_stk_cd(code))
                if not base:
                    continue
                if min_amt > 0:
                    # 단일 소스 진리: 원 단위 그대로 필터링 시 억 단위 변환
                    avg_amt = (data.get("avg_5d_trade_amount", 0) or 0) // 100_000_000
                    if avg_amt >= min_amt:
                        filtered_codes.append(base)
                else:
                    filtered_codes.append(base)

            # 필터링된 종목만 바로 구독 신청
            for code in filtered_codes:
                try:
                    from backend.app.services.engine_ws import _subscribe_stock_realtime_when_ready
                    async def _subscribe_with_semaphore():
                        async with _subscribe_semaphore:
                            await _subscribe_stock_realtime_when_ready(code)
                    _task = asyncio.get_running_loop().create_task(_subscribe_with_semaphore())
                    _task.add_done_callback(lambda t: logger.warning("[구독] 구독 실패: %s", t.exception()) if t.exception() else None)
                except RuntimeError as e:
                    logger.error("[구독] task 생성 실패 %s: %s", code, e)
            logger.debug("[시작] 확정데이터 반영 완료 -- %d행 (화면 표시, 필터링: %d종목)", len(krx_rows), len(filtered_codes))
        else:
            logger.info("[시작] 확정데이터 없음 -- 화면 표시 생략")

        # ── 3단계: 5일 평균 거래대금 ───────────────────────────────────────
        _broadcast_bootstrap_stage(4, "5일 평균 로드")
        _avg_map = {}
        _high_map = {}

        # master_stocks_table에서 5일평균 로드
        for code, data in loaded_data.items():
            # 단일 소스 진리: _master_stocks_cache에서 직접 사용
            avg_amt = data.get("avg_5d_trade_amount", 0) or 0
            high_price = data.get("high_price", 0)
            if avg_amt > 0:
                _avg_map[code] = avg_amt
            if high_price > 0:
                _high_map[code] = high_price

        # _update_avg_amt_5d 제거: _master_stocks_cache가 단일 소스
        for key, value in _high_map.items():
            if key in _st._master_stocks_cache:
                _st._master_stocks_cache[key]["high_5d_price"] = value
        logger.info("[시작] 5일평균 로드 완료 -- %d종목", len(_avg_map))

        try:
            from backend.app.services import engine_account_notify as _account_notify
            _account_notify.notify_desktop_buy_radar_only()
        except Exception as e:
            logger.warning("[시작] 매수후보 갱신 실패: %s", e, exc_info=True)

        _layout_count = sum(1 for t, _ in auto_layout if t == "code")
        from backend.app.services.engine_state import _master_stocks_cache
        _avg_count = len([cd for cd, stock in _master_stocks_cache.items() if stock.get("avg_5d_trade_amount", 0) > 0])

        logger.info(
            "[시작] 모든 준비 완료 -- 총 %d종목 (레이아웃=%d, 5일평균=%d)",
            len(codes), _layout_count, _avg_count,
        )

        # ── 필터 계산 및 빈 엔트리 추가 ─────────────────────────────────────
        # _compute_filtered_codes 제거: sector_stock_layout 의존성 제거
        # 단일 소스(_master_stocks_cache) 기반 필터링
        # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음

        # sector_min_trade_amt 필터링 적용 (설계 의도 준수)
        min_amt = float(_st._integrated_system_settings_cache.get("sector_min_trade_amt", 0.0) or 0.0)
        _missing = set(_st._master_stocks_cache.keys())
        if _missing and min_amt > 0:
            # 단일 소스 진리: avg_5d_trade_amount는 백만원 단위, 필터링 시 억 단위 변환
            filtered_missing = []
            for code in _missing:
                avg_amt_million = _master_stocks_cache.get(code, {}).get("avg_5d_trade_amount", 0) or 0
                avg_amt_eok = avg_amt_million // 100  # 백만원 → 억단위 변환
                if avg_amt_eok >= min_amt:
                    filtered_missing.append(code)
            _missing = set(filtered_missing)

        if _missing:
            for code in _missing:
                try:
                    from backend.app.services.engine_ws import _subscribe_stock_realtime_when_ready
                    async def _subscribe_with_semaphore():
                        async with _subscribe_semaphore:
                            await _subscribe_stock_realtime_when_ready(code)
                    _task = asyncio.get_running_loop().create_task(_subscribe_with_semaphore())
                    _task.add_done_callback(lambda t: logger.warning("[구독] 구독 실패: %s", t.exception()) if t.exception() else None)
                except RuntimeError as e:
                    logger.error("[구독] task 생성 실패 %s: %s", code, e)
            logger.debug("[시작] 필터 통과 빈 엔트리 추가 -- %d종목", len(_missing))

        _broadcast_bootstrap_stage(5, "앱준비 완료")
        _st._bootstrap_event.set()
        logger.info("[시작] 앱준비 완료 플래그 설정")

        from backend.app.services import engine_service
        engine_service._data_ready_event.set()
        logger.info("[시작] 데이터 준비 완료 플래그 설정")

        # ── 업종순위 계산 ───────────────────────────────────────────
        # _deferred_sector_summary() 제거: recompute_sector_for_code() 단일 경로 사용
        # _in_ws_window 조건 제거: 업종 요약정보는 _in_ws_window와 무관하게 생성
        from backend.app.services.engine_sector_confirm import recompute_sector_for_code
        import backend.app.services.engine_account_notify as _an
        _an._prev_scores_cache = []
        recompute_sector_for_code(None)

        # 앱준비 완료 → 기동 시 스킵된 장마감 파이프라인 데이터동기화중 재시도
        try:
            from backend.app.services.daily_time_scheduler import retry_pipeline_catchup_after_bootstrap
            await retry_pipeline_catchup_after_bootstrap()
        except Exception as _catchup_err:
            logger.warning("[시작] 데이터동기화중 재시도 실패(무시): %s", _catchup_err, exc_info=True)

    except RuntimeError as e:
        # RuntimeError 내부 처리 - 외부로 전파 방지
        logger.warning("[부트스트랩] 런타임 에러: 빈 상태로 안전하게 기동을 계속합니다.")
        # 이벤트 설정하여 시스템이 계속 진행할 수 있도록 함
        _broadcast_bootstrap_stage(6, "앱준비 완료")
        _st._bootstrap_event.set()
        # _sector_summary_ready_event.set() 제거: 업종 요약정보 생성 완료 시 engine_sector_confirm에서 설정
        from backend.app.services import engine_service
        engine_service._data_ready_event.set()
    except Exception as e:
        # 기타 예외 내부 처리 - 외부로 전파 방지
        logger.warning("[부트스트랩] 예외 발생: 빈 상태로 안전하게 기동을 계속합니다. %s", e, exc_info=True)
        # 이벤트 설정하여 시스템이 계속 진행할 수 있도록 함
        _broadcast_bootstrap_stage(6, "앱준비 완료")
        _st._bootstrap_event.set()
        # _sector_summary_ready_event.set() 제거: 업종 요약정보 생성 완료 시 engine_sector_confirm에서 설정
        from backend.app.services import engine_service
        engine_service._data_ready_event.set()


async def _deferred_sector_summary() -> None:
    """업종순위 후순위 계산 — _bootstrap_event.set() 이후 비동기 실행.

    compute_full_sector_summary()는 CPU-bound이므로 asyncio.to_thread()로
    별도 스레드에서 실행하여 이벤트 루프 블로킹을 방지한다.
    완료 후 _sector_summary_ready_event.set() + WS 3종 전송.
    """
    try:
        # 항상 전체 재계산 수행 (스켈레톤 캐시 모드 제거)
        from backend.app.services.engine_sector_score import compute_full_sector_summary
        from backend.app.services.engine_sector import get_sector_summary_inputs
        _inputs = get_sector_summary_inputs()
        if _inputs.get("all_codes"):
            # 단일 소스 진리: _integrated_system_settings_cache 직접 사용
            _trim_trade = float(_st._integrated_system_settings_cache.get("sector_trim_trade_amt_pct", 0) or 0)
            _trim_change = float(_st._integrated_system_settings_cache.get("sector_trim_change_rate_pct", 0) or 0)
            _kwargs = dict(
                sort_keys=_st._integrated_system_settings_cache.get("sector_sort_keys") or None,
                min_rise_ratio=float(_st._integrated_system_settings_cache.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
                block_rise_pct=float(_st._integrated_system_settings_cache.get("buy_block_rise_pct", 7.0)),
                block_fall_pct=float(_st._integrated_system_settings_cache.get("buy_block_fall_pct", 7.0)),
                min_strength=float(_st._integrated_system_settings_cache.get("buy_min_strength", 0)),
                min_avg_amt_eok=float(_st._integrated_system_settings_cache.get("sector_min_trade_amt", 0.0)),
                max_sectors=int(_st._integrated_system_settings_cache.get("sector_max_targets", 3)),
                sector_weights=_st._integrated_system_settings_cache.get("sector_weights") or {},
                trim_trade_amt_pct=_trim_trade,
                trim_change_rate_pct=_trim_change,
            )
            _result = await compute_full_sector_summary(**_inputs, **_kwargs)
            import backend.app.services.engine_service as _es
            _es._sector_summary_cache = _result
            # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음
            logger.debug("[시작] 업종순위 후순위 계산 완료 -- %d개 섹터", len(_result.sectors))

            # 영속성 캐시 저장 삭제 (메모리 캐시로 대체)

            # _sector_summary_ready_event.set() 제거: 업종 요약정보 생성 완료 시 engine_sector_confirm에서 설정

            # WS broadcast — 이미 연결된 클라이언트에게 전송
            try:
                from backend.app.services.engine_account_notify import (
                    notify_desktop_sector_scores,
                    notify_desktop_sector_stocks_refresh,
                    notify_buy_targets_update,
                )
                from backend.app.web.ws_manager import ws_manager
                _client_cnt = ws_manager.client_count
                notify_desktop_sector_scores(force=True)
                await notify_desktop_sector_stocks_refresh()
                notify_buy_targets_update()
                logger.debug("[시작] 업종순위 화면전송 완료 (접속화면=%d)", _client_cnt)
            except Exception as e:
                logger.error("[시작] UI 초기 전송 실패: %s", e, exc_info=True)
        else:
            # 종목 없음 — 이벤트만 발행 (대기 해제)
            _st._sector_summary_ready_event.set()
    except Exception as _e:
        logger.warning("[시작] 업종순위 후순위 계산 실패(무시): %s", _e, exc_info=True)
        _st._sector_summary_ready_event.set()  # 실패해도 대기 해제


async def _notify_close_data_ui() -> None:
    """장외 확정 데이터 갱신 -- UI 알림 트리거."""
    try:
        from backend.app.services import engine_account_notify as _account_notify
        try:
            _account_notify.notify_desktop_buy_radar_only()
        except Exception as e:
            logger.warning("[시작] 매수후보 갱신 실패: %s", e, exc_info=True)
        try:
            _account_notify.notify_desktop_sector_refresh()
            logger.debug("[시작][장외갱신] 섹터 분석 패널 갱신 트리거")
        except Exception as e:
            logger.warning("[시작] 섹터 갱신 실패: %s", e, exc_info=True)
    except Exception as _e:
        logger.warning("[시작][장외갱신] 확정 데이터 갱신 실패(무시): %s", _e, exc_info=True)





async def _login_post_pipeline() -> None:
    """LOGIN 성공 후: 잔고 조회 -> 보유종목 REG -> WS 구독 등록."""
    from backend.app.services import engine_service as es
    _st._ws_reg_pipeline_done.clear()
    logger.info("[시작] 로그인 후 파이프라인 진입")
    try:
        await es._cleanup_stale_ws_subscriptions_on_session_ready()

        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
        from backend.app.core.trade_mode import is_test_mode
        _in_ws_window = await is_ws_subscribe_window(_st._integrated_system_settings_cache)

        if is_test_mode(_st._integrated_system_settings_cache):
            logger.info("[시작] 파이프라인 -- 테스트모드 -- REST 잔고 조회 생략 (가상잔고 사용)")
        elif not _in_ws_window:
            if not _st._account_rest_bootstrapped:
                for _wait in range(3):
                    if _st._rest_api is not None:
                        break
                    await asyncio.sleep(1.0)
                logger.info("[시작] 파이프라인 -- REST 잔고 선행 조회 시작")
                from backend.app.services.engine_service import _update_account_memory
                await _update_account_memory(_st._integrated_system_settings_cache)
                logger.info("[시작] 파이프라인 -- REST 잔고 선행 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.info("[시작] 파이프라인 -- 잔고 이미 앱준비 완료 -- 재조회 생략 (보유 %d종목)", len(_st._positions))
        else:
            if not _st._positions and not _st._account_rest_bootstrapped:
                for _wait in range(3):
                    if _st._rest_api is not None:
                        break
                    await asyncio.sleep(1.0)
                logger.debug("[시작] 파이프라인 -- 실시간 구독 구간이나 포지션 미적재 -- REST 잔고 1회 조회")
                from backend.app.services.engine_service import _update_account_memory
                await _update_account_memory(_st._integrated_system_settings_cache)
                logger.debug("[시작] 파이프라인 -- REST 잔고 1회 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.debug("[시작] 파이프라인 -- 실시간 구독 구간 -- REST 잔고 조회 생략 (실시간 수신, 보유 %d종목)", len(_st._positions))

        from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
        wl_codes: set[str] = set()
        # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
        for t, v in _st._integrated_system_settings_cache.get("sector_stock_layout", []):
            if t != "code":
                continue
            wl_codes.add(_format_kiwoom_reg_stk_cd(v))
        stale = {cd for cd, entry in _st._master_stocks_cache.items() if entry.get("_subscribed", False) and cd in wl_codes}
        if stale:
            logger.debug("[시작] 새 세션 -- 0B 구독 상태 초기화 %d종목 (강제 재등록)", len(stale))
            for cd in stale:
                if cd in _st._master_stocks_cache:
                    _st._master_stocks_cache[cd].pop("_subscribed", None)

        from backend.app.services import engine_account_notify as _account_notify
        # 시장구분 + NXT 캐시 적재 (저장데이터 로딩시 즉시, 미스 시 키움 REST 조회)
        await es._fetch_market_map_async()

        if _in_ws_window:
            # 키움 Connector 연결 확인 및 키움 구독
            if es._kiwoom_connector and es._kiwoom_connector.is_connected():
                await es._run_sector_reg_pipeline()
                await es._ensure_ws_subscriptions_for_positions()

            _account_notify.notify_desktop_sector_refresh()
            await _account_notify.notify_desktop_sector_stocks_refresh()
        else:
            _st._ws_reg_pipeline_done.set()
            await _account_notify.notify_desktop_sector_refresh(force=True)
            await _account_notify.notify_desktop_sector_stocks_refresh()
    except Exception as _e:
        logger.error("[시작] 로그인 후 파이프라인 예외: %s", _e, exc_info=True)


async def _run_sector_reg_pipeline() -> None:
    """REG 파이프라인 -- engine_service에서 위임."""
    from backend.app.services import engine_service as es
    await es._run_sector_reg_pipeline()



