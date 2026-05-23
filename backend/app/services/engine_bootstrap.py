# -*- coding: utf-8 -*-
"""
엔진 부트스트랩 흐름.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
engine_service의 함수가 필요하면 lazy import (`from backend.app.services import engine_service`).
"""
from __future__ import annotations

import asyncio

from backend.app.core.logger import get_logger
import backend.app.services.engine_state as _st

logger = get_logger("engine")

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
    업종맵(ka10099) 기반 전체 종목 초기 시세 로드.
    캐시 데이터가 있으면 REST API 없이도 부트스트랩 완료 가능.
    """
    _already_ready = _st._bootstrap_event.is_set()
    if not _already_ready:
        _st._bootstrap_event.clear()
        _st._sector_summary_ready_event.clear()

    # ── 테스트모드: Settlement Engine 상태 복원 ──
    if (_st._settings_cache or {}).get("trade_mode") == "test":
        from backend.app.services import settlement_engine
        settlement_engine._load()
        logger.debug("[시작] Settlement Engine 상태 복원 완료 (테스트모드)")

    from backend.app.services.engine_symbol_utils import _base_stk_cd
    from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
    from backend.app.core.sector_stock_cache import (
        load_layout_cache, save_layout_cache,
    )
    from backend.app.db.crud import get_all_stocks
    from backend.app.core.avg_amt_cache import load_avg_amt_cache

    # ── 0단계: 레이아웃 캐시 확인 → 사용 시 업종맵 API 스킵 ──────────────
    _broadcast_bootstrap_stage(1, "레이아웃 저장데이터 확인")
    _preboot_hit = _st._preboot_cache_loaded and len(_st._sector_stock_layout) > 0

    if _preboot_hit:
        # 데이터준비에서 이미 레이아웃·확정데이터·5일평균 로드 완료 — 파일 재로드 스킵
        logger.debug(
            "[시작] 데이터준비 사용 -- %d종목 (레이아웃·확정데이터·5일평균 재로드 생략)",
            sum(1 for t, _ in _st._sector_stock_layout if t == "code"),
        )
        _broadcast_bootstrap_stage(2, "섹터 매핑 로드")
    elif (_layout_cached := load_layout_cache()):
        _st._sector_stock_layout[:] = _layout_cached
        from backend.app.services.engine_account_notify import _rebuild_layout_cache
        _rebuild_layout_cache(_st._sector_stock_layout)
        logger.debug(
            "[시작] 레이아웃 저장데이터 로드 -- %d종목 (업종맵 API 생략)",
            sum(1 for t, _ in _layout_cached if t == "code"),
        )
        _broadcast_bootstrap_stage(2, "섹터 매핑 로드")
    else:
        _broadcast_bootstrap_stage(2, "섹터 매핑 로드")
        # ka10099 종목코드 목록 + stock_classification.json 기반 그룹핑
        from backend.app.core.industry_map import get_eligible_stocks
        from backend.app.core.sector_mapping import get_merged_sector
        stock_codes = get_eligible_stocks()  # {종목코드: ""} — 키만 사용

        if stock_codes:
            auto_layout: list[tuple[str, str]] = []
            sector_groups: dict[str, list[str]] = {}
            for stk_cd in stock_codes.keys():
                merged = get_merged_sector(stk_cd) or "기타"
                if merged not in sector_groups:
                    sector_groups[merged] = []
                sector_groups[merged].append(stk_cd)
            for sector_name, stk_codes in sector_groups.items():
                auto_layout.append(("sector", sector_name))
                for cd in stk_codes:
                    auto_layout.append(("code", cd))
            _st._sector_stock_layout[:] = auto_layout
            from backend.app.services.engine_account_notify import _rebuild_layout_cache
            _rebuild_layout_cache(_st._sector_stock_layout)
            logger.debug(
                "[시작] 업종 매핑 기반 자동 구성 -- %d종목 / %d섹터",
                sum(1 for t, _ in auto_layout if t == "code"),
                len(sector_groups),
            )
            save_layout_cache(auto_layout)
        else:
            logger.debug("[시작] 섹터 매핑 데이터 없음 -- 레이아웃 자동 구성 생략")

    codes: list[str] = [v for t, v in _st._sector_stock_layout if t == "code"]
    if not codes:
        logger.debug("[시작] 업종맵 종목 없음 -- 초기화 생략")
        return

    # ── WS 구독 구간 판정 (구간 안이면 확정데이터 시세 초기화) ──
    try:
        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
        _in_ws_window = is_ws_subscribe_window(_st._settings_cache)
    except Exception:
        logger.warning("[시작] WS 구독 구간 판정 실패", exc_info=True)
        _in_ws_window = False

    # ── 2단계: 확정데이터 캐시 확인 → 사용 시 UI 즉시 표시 ──────────────────
    _broadcast_bootstrap_stage(3, "KRX 확정데이터 로드 중")
    krx_rows: list[tuple[str, dict]] = []

    _preboot_snapshot_hit = _preboot_hit and len(_st._pending_stock_details) > 0

    if _preboot_snapshot_hit:
        # 데이터준비에서 이미 확정데이터 → 메모리 적재 완료 — 파일 재로드 + 버킷 세팅 스킵
        logger.debug("[시작] 데이터준비 사용 -- 확정데이터·거래대금 데이터 재로드 생략 (%d종목)", len(_st._pending_stock_details))
        _broadcast_bootstrap_stage(4, "시세 데이터 반영")
    elif (_db_stocks := get_all_stocks()):
        # DB 데이터를 기존 krx_rows 형식(list[tuple[str, dict]])으로 변환
        krx_rows = []
        for stock in _db_stocks:
            detail = {
                "name": stock.get("name", stock["code"]),
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
            krx_rows.append((stock["code"], detail))
        logger.debug("[시작] DB 확정데이터 로드 -- %d종목 (UI 즉시 표시)", len(krx_rows))
    else:
        logger.debug("[시작] DB 확정데이터 실패 -- 로드 생략 (장마감 후 ka10086 확정 조회로 갱신)")

    if not _preboot_snapshot_hit:
        # ── 4단계: 거래대금 버킷 세팅 및 화면 표시 ──────────────────────────
        _broadcast_bootstrap_stage(4, "시세 데이터 반영")
        for cd, detail in krx_rows:
            base = _format_kiwoom_reg_stk_cd(_base_stk_cd(cd))
            amt = int(detail.get("trade_amount") or 0)
            async with _st._shared_lock:
                if amt > 0:
                    _st._latest_trade_amounts[base] = amt
                if base and int(detail.get("cur_price") or 0) > 0:
                    _st._rest_radar_quote_cache[base] = detail
            if base and int(detail.get("cur_price") or 0) > 0:
                _st._rest_radar_rest_once.add(base)

        logger.debug(
            "[시작] REST 버킷 세팅 완료 -- 005930=%s",
            f"{_st._latest_trade_amounts.get('005930', 0):,}",
        )

        if krx_rows:
            from backend.app.services import engine_strategy_core
            for stk_cd, detail in krx_rows:
                base = _format_kiwoom_reg_stk_cd(_base_stk_cd(stk_cd))
                if base and base not in _st._pending_stock_details:
                    entry = engine_strategy_core.make_detail(
                        base,
                        detail.get("name", base) or base,
                        int(detail.get("cur_price") or 0),
                        detail.get("sign", "3"),
                        int(detail.get("change") or 0),
                        float(detail.get("change_rate") or 0.0),
                        prev_close=int(detail.get("prev_close") or 0),
                        trade_amount=int(detail.get("trade_amount") or 0),
                        strength=detail.get("strength", "-"),
                    )
                    entry["status"] = "active"
                    entry["base_price"] = int(detail.get("cur_price") or 0)
                    entry["target_price"] = int(detail.get("cur_price") or 0)
                    entry["captured_at"] = ""
                    entry["reason"] = "확정데이터 초기 로드"
                    async with _st._shared_lock:
                        _st._pending_stock_details[base] = entry
                        _st._radar_cnsr_order.append(base)
            logger.debug("[시작] 확정데이터 반영 완료 -- %d행 (화면 표시)", len(krx_rows))
        else:
            logger.warning("[시작] 확정데이터 없음 -- 화면 표시 생략")

        if krx_rows:
            logger.debug("[시작] 확정데이터 저장데이터 로드 -- 백그라운드 REST 갱신 생략 (저장데이터 사용)")

    # ── 7단계: 5일 평균 거래대금 ──────
    _broadcast_bootstrap_stage(5, "5일 평균 저장데이터 로드")
    _st._avg_amt_needs_bg_refresh = False
    if _preboot_hit and len(_st._avg_amt_5d) > 0:
        # 데이터준비에서 이미 5일 평균 로드 완료 — 파일 재로드 스킵
        logger.debug(
            "[시작] 데이터준비 사용 -- 5일거래대금평균/고가 재로드 생략 (%d종목)", len(_st._avg_amt_5d)
        )
    else:
        # ── 5일 평균 및 고가 데이터 DB에서 로드 ──
        from backend.app.db.crud import get_all_stocks
        _db_stocks = get_all_stocks()
        if _db_stocks:
            _avg_map = {}
            _high_map = {}
            for row in _db_stocks:
                cd = row["code"]
                _avg_map[cd] = int(row.get("avg_5d_trade_amount") or 0)
                _high_map[cd] = int(row.get("high_price") or 0)
            
            _st._update_avg_amt_5d(_avg_map)
            _st._high_5d_cache.clear()
            _st._high_5d_cache.update(_high_map)
            _snapshot_valid = True
            logger.info("[시작] DB에서 5일 평균 및 고가 데이터 로드 완료 -- %d종목", len(_avg_map))
        else:
            logger.warning("[시작] DB 데이터 없음 -- 빈 맵으로 시작 (수동 다운로드 필요)")
            _snapshot_valid = False

    try:
        from backend.app.services import engine_account_notify as _account_notify
        _account_notify.notify_desktop_buy_radar_only()
    except Exception as e:
        logger.warning("[시작] 매수후보 갱신 실패: %s", e, exc_info=True)
    _src = "섹터매핑" if len(_st._sector_stock_layout) > 0 else "없음"
    _snapshot_count = len(_st._pending_stock_details) if _preboot_hit else len(krx_rows)
    _layout_count = sum(1 for t, _ in _st._sector_stock_layout if t == "code")
    _avg_count = len(_st._avg_amt_5d)
    _filtered_count = len(_st._filtered_sector_codes) if _st._filtered_sector_codes else 0
    
    logger.info(
        "[시작] 모든 준비 완료 -- 총 %d종목 "
        "(레이아웃=%d, 확정데이터=%d, 5일평균=%d, 필터통과=%d, 소스=%s)",
        len(codes), _layout_count, _snapshot_count, _avg_count, _filtered_count, _src,
    )

    # ── 8단계: 장외 시간 앱 시작 시 확정 데이터 갱신 ────
    try:
        from datetime import datetime, timezone, timedelta
        from backend.app.core.trading_calendar import is_krx_holiday, kst_today
        from backend.app.core.trade_mode import is_test_mode
        _KST = timezone(timedelta(hours=9))
        _h = datetime.now(_KST).hour
        _is_holiday = is_krx_holiday(kst_today())
        _is_off_market = _is_holiday or _h >= 20 or _h < 8 or (_h >= 15 and datetime.now(_KST).minute >= 30)
        if _is_off_market and not is_test_mode(_st._settings_cache) and _st._rest_api:
            logger.debug(
                "[시작][장외갱신] 장외 시간(%02d시, 휴일=%s) -- ka10086 백그라운드 갱신 예약 (0B REG 비블로킹)",
                _h, _is_holiday,
            )
            asyncio.get_event_loop().create_task(_notify_close_data_ui())

        if _st._avg_amt_needs_bg_refresh:
            logger.debug(
                "[시작][장외갱신] 5일 평균 저장데이터 갱신 필요 플래그 설정됨 (%d종목) -- _rest_api 설정 후 예약 예정",
                len(_st._avg_amt_5d),
            )
    except Exception as _e:
        logger.warning("[시작][장외갱신] 갱신 예약 실패(무시): %s", _e, exc_info=True)

    # ── 확정 상태 초기화 (제거됨 — 실시간 연동 전환) ──
    _st._sector_summary_cache = None
    _st._filtered_sector_codes = _st._compute_filtered_codes()
    _st._invalidate_sector_stocks_cache()
    logger.debug(
        "[시작] 필터 통과 종목 %d개",
        len(_st._filtered_sector_codes or set()),
    )

    # ── 필터 통과 종목 중 _pending_stock_details에 없는 종목 빈 엔트리 추가 ──
    # WS 실시간 데이터 수신을 위해 엔트리가 존재해야 함
    _filter_set = _st._filtered_sector_codes or set()
    _missing = _filter_set - set(_st._pending_stock_details.keys())
    if _missing:
        from backend.app.services import engine_strategy_core as _esc
        from backend.app.core.sector_stock_cache import load_stock_name_cache as _load_names
        _name_map = _load_names() or {}
        for _cd in _missing:
            _nm = _name_map.get(_cd, _cd)
            _entry = _esc.make_detail(_cd, _nm, 0, "3", 0, 0.0)
            _entry["status"] = "active"
            _entry["base_price"] = 0
            _entry["target_price"] = 0
            _entry["captured_at"] = ""
            _entry["reason"] = "필터 통과 빈 엔트리"
            async with _st._shared_lock:
                _st._pending_stock_details[_cd] = _entry
                _st._radar_cnsr_order.append(_cd)
        logger.debug("[시작] 필터 통과 빈 엔트리 추가 -- %d종목 (실시간 수신 대기)", len(_missing))

    _broadcast_bootstrap_stage(6, "앱준비 완료")
    _st._bootstrap_event.set()
    logger.info("[시작] 앱준비 완료 플래그 설정")

    # engine-ready WS는 engine_loop.py에서 1회만 전송 — 여기서는 중복 전송하지 않음

    # ── 업종순위 후순위 계산 (create_task — WS 전송을 블로킹하지 않음) ──
    _task = asyncio.create_task(_deferred_sector_summary())
    _task.add_done_callback(lambda t: t.exception() if t.exception() else None)

    # 앱준비 완료 → 섹터 재계산 트리거 (이벤트 기반)
    from backend.app.services.engine_sector_confirm import recompute_sector_for_code
    # WS 구간 안이면 delta 비교 캐시 초기화 (전일 데이터 잔존 방지)
    if _in_ws_window:
        import backend.app.services.engine_account_notify as _an
        _an._prev_scores_cache = []
    recompute_sector_for_code(None)  # 전체 재계산

    # 앱준비 완료 → 기동 시 스킵된 장마감 파이프라인 데이터동기화중 재시도
    try:
        from backend.app.services.daily_time_scheduler import retry_pipeline_catchup_after_bootstrap
        retry_pipeline_catchup_after_bootstrap()
    except Exception as _catchup_err:
        logger.warning("[시작] 데이터동기화중 재시도 실패(무시): %s", _catchup_err, exc_info=True)


async def _deferred_sector_summary() -> None:
    """업종순위 후순위 계산 — _bootstrap_event.set() 이후 비동기 실행.

    compute_full_sector_summary()는 CPU-bound이므로 asyncio.to_thread()로
    별도 스레드에서 실행하여 이벤트 루프 블로킹을 방지한다.
    완료 후 _sector_summary_ready_event.set() + WS 3종 전송.
    """
    try:
        # 항상 전체 재계산 수행 (스켈레톤 캐시 모드 제거)
        from backend.app.services.engine_sector_score import compute_full_sector_summary
        _inputs = _st.get_sector_summary_inputs()
        if _inputs.get("all_codes"):
            _settings = _st._settings_cache or {}
            # 앱준비 시점에 _settings_cache가 아직 빈 딕셔너리일 수 있음
            # → 설정 파일에서 직접 로드하여 사용자 설정값 반영 보장
            if not _settings:
                from backend.app.core.settings_file import load_settings
                _settings = load_settings()
            _trim_trade = float(_settings.get("sector_trim_trade_amt_pct", 0) or 0)
            _trim_change = float(_settings.get("sector_trim_change_rate_pct", 0) or 0)
            _kwargs = dict(
                sort_keys=_settings.get("sector_sort_keys") or None,
                min_rise_ratio=float(_settings.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
                block_rise_pct=float(_settings.get("buy_block_rise_pct", 7.0)),
                block_fall_pct=float(_settings.get("buy_block_fall_pct", 7.0)),
                min_strength=float(_settings.get("buy_min_strength", 0)),
                min_trade_amt_won=float(_settings.get("sector_min_trade_amt", 0.0)) * 1_0000_0000,
                max_sectors=int(_settings.get("sector_max_targets", 3)),
                sector_weights=_settings.get("sector_weights"),
                trim_trade_amt_pct=_trim_trade,
                trim_change_rate_pct=_trim_change,
                index_guard_kospi_on=bool(_settings.get("buy_index_guard_kospi_on", False)),
                index_guard_kosdaq_on=bool(_settings.get("buy_index_guard_kosdaq_on", False)),
                index_kospi_drop=float(_settings.get("buy_index_kospi_drop", 2.0)),
                index_kosdaq_drop=float(_settings.get("buy_index_kosdaq_drop", 2.0)),
            )
            _result = await asyncio.to_thread(
                compute_full_sector_summary, **_inputs, **_kwargs
            )
            _st._sector_summary_cache = _result
            _st._invalidate_sector_stocks_cache()
            logger.debug("[시작] 업종순위 후순위 계산 완료 -- %d개 섹터", len(_result.sectors))
            
            # 영속성 캐시에 저장
            from backend.app.core.sector_summary_cache import save_sector_summary_cache
            save_sector_summary_cache(_result)

            # 이벤트 발행 — _send_stocks_delayed()가 대기 중이면 해제
            _st._sector_summary_ready_event.set()

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
                notify_desktop_sector_stocks_refresh()
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


async def refresh_avg_amt_5d_cache() -> None:
    """
    장 마감 후 5일 평균 거래대금 캐시 갱신.
    - v2 캐시 있으면: ka20002 롤링 갱신 (약 30초)
    - v2 캐시 없으면: ka10086 × 5영업일 병렬 호출로 최초 구축 (백그라운드, Chunk 단위)
    Chunk 단위로 세마포어를 acquire/release하여 다른 REST 호출을 블로킹하지 않음.
    """
    try:
        logger.info("[DEBUG] refresh_avg_amt_5d_cache START")
        # 스케줄러 토글 OFF 시 5일봉 전체 다운로드 스킵
        # 단, _avg_amt_needs_bg_refresh=True면 강제 실행 (삭제 직후 호출 등)
        _settings = _st._settings_cache or {}
        force_run = getattr(_st, "_avg_amt_needs_bg_refresh", False)
        scheduler_on = _settings.get("scheduler_5d_download_on", True)
        existing_task = getattr(_st, "_avg_amt_refresh_task", None)
        already_running = existing_task is not None and not existing_task.done()
        logger.info("[DEBUG] refresh_avg_amt_5d_cache STATE: scheduler_5d_download_on=%s, force_run=%s, existing_task=%s, done=%s", scheduler_on, force_run, existing_task is not None, existing_task.done() if existing_task else None)
        if not scheduler_on and not force_run:
            logger.info("[DEBUG] refresh_avg_amt_5d_cache SKIP 이유: scheduler_5d_download_on=OFF")
            return
        
        # 정규장 차단 서킷 브레이커 (Phase 2.1 단계 3)
        from backend.app.services.daily_time_scheduler import is_heavy_operation_allowed
        if not is_heavy_operation_allowed():
            logger.info("[시작] 안전 구역(20:30~연결시작전) 외 시간대 진입으로 인한 5일거래대금 다운로드 스킵")
            return
        if already_running:
            logger.info("[DEBUG] refresh_avg_amt_5d_cache CANCEL EXISTING TASK")
            existing_task.cancel()
            try:
                await existing_task
            except asyncio.CancelledError:
                logger.info("[DEBUG] refresh_avg_amt_5d_cache TASK CANCELLED")
        _st._avg_amt_refresh_task = asyncio.current_task()
        try:
            logger.info("[DEBUG] refresh_avg_amt_5d_cache EXECUTE START")
            await _refresh_avg_amt_5d_cache_inner(force_run=force_run)
            logger.info("[DEBUG] refresh_avg_amt_5d_cache EXECUTE COMPLETE")
        finally:
            _st._avg_amt_refresh_task = None
    except Exception as e:
        logger.error("[DEBUG] refresh_avg_amt_5d_cache EXCEPTION: %s", e, exc_info=True)
        raise


async def _chunked_fetch_full_5d(
    sector_prov, codes: list[str], on_progress=None,
    *,
    resume_completed: "set[str] | None" = None,
    resume_v2: "dict[str, list[int]] | None" = None,
    resume_high_cache: "dict[str, int] | None" = None,
    resume_high_5d_arr: "dict[str, list[int]] | None" = None,
    resume_latest_dict: "dict[str, dict] | None" = None,
    date_str: str = "",
) -> tuple[dict[str, list[int]], dict[str, int], dict[str, list[int]], dict[str, dict[str, Any]]]:
    """Chunk 단위로 세마포어를 acquire/release하며 ka10081(_AL) × 1회 순차 호출.
    다른 REST 호출(잔고, 시세 등)이 Chunk 사이에 끼어들 수 있음.
    진행률 콜백은 메인 이벤트 루프에서 호출 (워커 스레드 안전).

    Args:
        sector_prov: SectorProvider 인터페이스 (broker_providers.py 경유)
        resume_*: 이어받기 복원 데이터 (없으면 처음부터)
        date_str: 진행 파일 저장용 거래일 (YYYYMMDD)

    Returns:
        (v2_data, high_cache, high_5d_arr, latest_dict)
        v2_data:     {종목코드: [5일치 거래대금 배열, 백만원, 오래된→최신]}
        high_cache:  {종목코드: max(5일 고가)}
        high_5d_arr: {종목코드: [5일치 고가 배열, 원, 오래된→최신]}
        latest_dict: {종목코드: 최신 1일차 차트 데이터 dict}
    """
    import time
    from backend.app.core.avg_amt_cache import _norm_stk, KA10005_GAP_SEC, save_avg_amt_progress
    result: dict[str, list[int]] = dict(resume_v2 or {})
    high_cache: dict[str, int] = dict(resume_high_cache or {})
    high_5d_arr: dict[str, list[int]] = dict(resume_high_5d_arr or {})
    latest_dict: dict[str, dict[str, Any]] = dict(resume_latest_dict or {})
    completed_set: set[str] = set(resume_completed or set())
    total = len(codes)
    starting_count = len(completed_set)
    if starting_count > 0:
        logger.debug("[시작] 이어받기 — %d/%d종목 복원, 나머지 %d종목 다운로드",
                    starting_count, total, total - starting_count)
    else:
        logger.debug("[시작] 전종목 5일 거래대금/고가 다운로드 시작 — 대상 %d종목", total)
    remaining_codes = [cd for cd in codes if _norm_stk(cd) not in completed_set]
    MINI_CHUNK = 1
    for chunk_start in range(0, len(remaining_codes), MINI_CHUNK):
        chunk = remaining_codes[chunk_start : chunk_start + MINI_CHUNK]
        def _sync_chunk(c=chunk):
            out_amts: dict[str, list[int]] = {}
            out_highs: dict[str, int] = {}
            out_high_arr: dict[str, list[int]] = {}
            out_latest: dict[str, dict[str, Any]] = {}
            for i, raw in enumerate(c):
                nk = _norm_stk(raw)
                if not nk:
                    continue
                res = sector_prov.fetch_daily_5d_data(nk)
                if len(res) == 2:
                    amts, highs = res
                    latest_row = None
                else:
                    amts, highs, latest_row = res
                
                if latest_row:
                    out_latest[nk] = latest_row

                if not amts:
                    continue
                # 최신→과거 → 오래된→최신 (v2 캐시 형식)
                amt_arr = list(reversed(amts))
                high_arr = list(reversed(highs))
                if any(v > 0 for v in amt_arr):
                    out_amts[nk] = amt_arr
                # 고가 캐시: 배열 최대값
                if high_arr:
                    max_high = max(high_arr)
                    out_highs[nk] = max_high if max_high > 0 else 0
                    out_high_arr[nk] = high_arr
                else:
                    out_highs[nk] = 0
                # MINI_CHUNK가 1이므로 스레드 내 time.sleep은 실행되지 않음
            return out_amts, out_highs, out_high_arr, out_latest
        
        async with _st._get_rest_api_thread_sem():
            chunk_amts, chunk_highs, chunk_high_arr, chunk_latest = await asyncio.to_thread(_sync_chunk)
            
        # 이벤트 루프에 명시적 제어권 양보 및 키움 API 호출 제한(초당 3회) 준수
        await asyncio.sleep(KA10005_GAP_SEC)
        
        result.update(chunk_amts)
        high_cache.update(chunk_highs)
        high_5d_arr.update(chunk_high_arr)
        latest_dict.update(chunk_latest)
        completed_set.update(chunk_amts.keys())
        
        # 진행률 계산
        done = starting_count + chunk_start + len(chunk)
        done = min(done, total)
        pct = int(done / total * 100) if total else 0
        
        # 로그는 스팸 방지를 위해 DEBUG 레벨로 하향 조정
        logger.debug("[시작] 전종목 5일거래대금/고가 다운로드 중 (%d/%d, %d%%)", done, total, pct)
        
        # 진행 상태 파일 저장은 디스크 I/O 부하 방지를 위해 20건마다 또는 마지막에만 수행
        if date_str and (chunk_start % 20 == 0 or done == total):
            save_avg_amt_progress(
                date_str, list(completed_set), codes,
                result, high_cache, high_5d_arr, latest_dict
            )
            
        # UI 진행률(웹소켓 브로드캐스트)은 매 건마다 즉각 호출하여 부드럽게 표시
        if on_progress:
            try:
                on_progress(done, total)
            except Exception:
                logger.warning("[시작] 진행률 콜백 실패", exc_info=True)
                
    success = len(result)
    failed = total - success
    valid_high = sum(1 for v in high_cache.values() if v > 0)
    logger.debug("[시작] 전종목 5일 거래대금/고가 다운로드 완료 — 성공 %d종목, 실패 %d종목, 유효고가 %d종목", success, failed, valid_high)
    return result, high_cache, high_5d_arr, latest_dict


async def _refresh_avg_amt_5d_cache_inner(force_run: bool = False) -> None:
    """_chunked_fetch_full_5d 실행 및 결과 병합 (최대 600개 일봉 → 5일 추출).
    - 기존 캐시가 없거나 전일 데이터면 다시 받음. (Chunked 방식 + 이어받기)
    """
    from backend.app.core.avg_amt_cache import (
        load_avg_amt_progress, save_avg_amt_cache_v2, clear_avg_amt_progress,
        avg_from_v2
    )
    _st._avg_amt_needs_bg_refresh = False

    # 정규장 차단 서킷 브레이커 (Phase 2.1 단계 3)
    from backend.app.services.daily_time_scheduler import is_heavy_operation_allowed
    if not is_heavy_operation_allowed():
        logger.info("[시작] 안전 구역(20:30~연결시작전) 외 시간대 진입으로 인한 5일거래대금 내부 다운로드 스킵")
        return

    all_codes = [v for t, v in _st._sector_stock_layout if t == "code"]
    if not all_codes:
        return

    if not force_run:
        # 로컬 데이터 완전성 검증 (방안 1: 중복 다운로드 방지)
        from backend.app.core.avg_amt_cache import load_avg_amt_cache_v2
        _existing_v2_result = load_avg_amt_cache_v2()
        if _existing_v2_result:
            _existing_v2, _existing_high_arr = _existing_v2_result
            # 종목수 충분(전체 종목의 90% 이상) 및 배열 길이 5 이상 검증
            if len(_existing_v2) >= len(all_codes) * 0.9:
                _short_arrays = sum(1 for arr in _existing_v2.values() if len(arr) < 5)
                if _short_arrays == 0:
                    logger.info("[시작] 로컬 데이터 완전함 -- 다운로드 스킵 (%d종목, 배열 길이 ≥ 5)", len(_existing_v2))
                    return
                else:
                    logger.warning("[시작] 로컬 데이터 불완전 -- 배열 길이 < 5인 종목 %d개, 다운로드 진행", _short_arrays)
            else:
                logger.warning("[시작] 로컬 데이터 부족 -- 저장된 종목수(%d) < 전체 종목수(%d), 다운로드 진행", len(_existing_v2), len(all_codes))

    # 이어받기: 진행 파일 로드
    from backend.app.core.avg_amt_cache import load_avg_amt_progress, clear_avg_amt_progress
    from backend.app.core.trading_calendar import current_trading_date_str
    _today_str = current_trading_date_str()
    _ws_start = str((_st._settings_cache or {}).get("ws_subscribe_start") or "07:50")
    _resume = load_avg_amt_progress(_today_str, all_codes, _ws_start)
    if _resume:
        _r_completed, _r_v2, _r_high, _r_high_arr = _resume
        logger.debug("[시작] 이어받기 — %d/%d종목 복원, 나머지 %d종목 다운로드",
                    len(_r_completed), len(all_codes), len(all_codes) - len(_r_completed))
    else:
        _r_completed, _r_v2, _r_high, _r_high_arr = set(), {}, {}, {}

    logger.debug("[시작] v2 저장데이터 없거나 만료 -- %d종목 ka10086 Chunk 구축 시작 (Chunk=%d종목)",
                len(all_codes), _st._AVG_AMT_CHUNK_SIZE)
    _broadcast_avg_amt_progress(len(_r_completed), len(all_codes), status="downloading")
    try:
        from backend.app.core.broker_factory import get_router
        _sector_prov = get_router(_st._settings_cache or {}).sector
        v2_data, high_cache, high_5d_arr, latest_dict = await _chunked_fetch_full_5d(
            _sector_prov, all_codes,
            on_progress=_broadcast_avg_amt_progress,
            resume_completed=_r_completed,
            resume_v2=_r_v2,
            resume_high_cache=_r_high,
            resume_high_5d_arr=_r_high_arr,
            date_str=_today_str,
        )
        from backend.app.core.avg_amt_cache import _kst_today_yyyymmdd
        save_avg_amt_cache_v2(v2_data, _kst_today_yyyymmdd(), high_5d=high_cache, high_5d_arr=high_5d_arr)
        clear_avg_amt_progress()
        avg_map = avg_from_v2(v2_data)

        # ── 초기 시세 스냅샷 자동 구축 (최신 차트 데이터 활용) ──
        # 장 시작 전이나 실시간 수신 전에도 UI에 종목 현재가, 등락률, 거래대금이 표시되도록 세팅
        async with _st._shared_lock:
            for cd, row in latest_dict.items():
                if cd in _st._pending_stock_details:
                    cur_prc = abs(int(row.get("cur_prc", 0) or 0))
                    pred_pre = int(row.get("pred_pre", 0) or 0)
                    pred_pre_sig = str(row.get("pred_pre_sig", "3") or "3")
                    if pred_pre_sig in ("4", "5"):
                        pred_pre = -abs(pred_pre)
                    else:
                        pred_pre = abs(pred_pre)
                    base_prc = cur_prc - pred_pre
                    rate = round((pred_pre / base_prc) * 100, 2) if base_prc > 0 else 0.0
                    trde_prica = int(row.get("trde_prica", 0) or 0)
                    
                    _st._pending_stock_details[cd]["cur_price"] = cur_prc
                    _st._pending_stock_details[cd]["sign"] = pred_pre_sig
                    _st._pending_stock_details[cd]["change"] = pred_pre
                    _st._pending_stock_details[cd]["change_rate"] = rate
                    _st._pending_stock_details[cd]["trade_amount"] = abs(trde_prica)
                    _st._pending_stock_details[cd]["prev_close"] = base_prc

        # ── 완전한 매핑 단계 (적격종목 × 시세 × 5일데이터 × 업종) ──────────
        from backend.app.core.sector_mapping import get_merged_sector
        eligible_set = set(all_codes)

        # 적격 종목별 3가지 매핑 확인: 시세 + 5일데이터 + 업종
        fully_mapped: set[str] = set()
        for cd in eligible_set:
            # 1) 시세 확인: _pending_stock_details에 entry 존재
            if cd not in _st._pending_stock_details:
                continue
            # 2) 5일데이터 매핑: avg_map + high_cache에 존재
            if cd not in avg_map and cd not in high_cache:
                continue
            # 3) 업종명 매핑: get_merged_sector(cd) 유효
            sector = get_merged_sector(cd)
            if not sector:
                continue
            fully_mapped.add(cd)

        # 적격 기준으로 avg_map, high_cache 필터
        new_avg = {cd: v for cd, v in avg_map.items() if cd in fully_mapped}
        new_high = {cd: v for cd, v in high_cache.items() if cd in fully_mapped}

        # ── 원자적 메모리 교체 (_shared_lock 내부) ──────────────────────────
        async with _st._shared_lock:
            _st._avg_amt_5d.clear()
            _st._avg_amt_5d.update(new_avg)
            _st._high_5d_cache.clear()
            _st._high_5d_cache.update(new_high)
            # _pending_stock_details에서 부적격 종목 제거
            ineligible_codes = [
                cd for cd in _st._pending_stock_details if cd not in eligible_set
            ]
            for cd in ineligible_codes:
                del _st._pending_stock_details[cd]
            _st._radar_cnsr_order[:] = [
                cd for cd in _st._radar_cnsr_order if cd in eligible_set
            ]

        valid_high_count = sum(1 for v in new_high.values() if v > 0)
        logger.info(
            "[시작] 전체 구축 완료 -- %d종목 (매핑완료=%d), HighCache %d종목 적재 (유효 %d), 부적격 %d종목 제거",
            len(avg_map), len(fully_mapped), len(new_high), valid_high_count, len(ineligible_codes),
        )
    except Exception as e:
        logger.error("[시작] 전체 구축 실패: %s", e, exc_info=True)

    try:
        from backend.app.services.engine_service import recompute_sector_summary_now
        from backend.app.services import engine_account_notify as _account_notify
        recompute_sector_summary_now()
        _account_notify.notify_desktop_sector_refresh()
        _account_notify.notify_desktop_sector_stocks_refresh()
        _account_notify.notify_desktop_sector_scores(force=True)
    except Exception as e:
        logger.error("[시작] 후처리 실패: %s", e, exc_info=True)
    _broadcast_avg_amt_progress(1, 1, status="completed")


def _broadcast_avg_amt_progress(current: int, total: int, *, status: str = "") -> None:
    """5일 평균 거래대금 구축 진행률 브로드캐스트.

    status 값: downloading, completed, failed, partial, cache_deleted, token_pending, requested
    """
    try:
        from backend.app.web.ws_manager import ws_manager
        done = current >= total
        pct = int(current / total * 100) if total > 0 else 0
        _status = status if status else ("completed" if done else "downloading")
        if _status == "downloading" and total > 0:
            _msg = f"전종목 5일 거래대금/고가 데이터 다운로드 중 ({current:,}/{total:,}, {pct}%)"
        elif _status == "completed":
            _msg = "전종목 5일 거래대금/고가 데이터 다운로드 완료"
        else:
            _msg = ""
        payload: dict = {
            "_v": 1,
            "current": current,
            "total": total,
            "done": done,
            "status": _status,
        }
        if _msg:
            payload["message"] = _msg
        ws_manager.broadcast("avg-amt-progress", payload)
    except Exception as e:
        logger.warning("[시작] 진행률 전송 실패: %s", e, exc_info=True)


async def _bg_refresh_avg_amt_5d() -> None:
    """5일 평균 거래대금 캐시 갱신 — 백그라운드 태스크. 실패 시 60초 간격 최대 3회 재시도."""
    existing_task = getattr(_st, "_avg_amt_refresh_task", None)
    if existing_task is not None and not existing_task.done():
        logger.info("[시작] 이미 갱신 진행 중 -- 생략")
        return
    _MAX_RETRIES = 3
    _RETRY_INTERVAL = 60
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info("[시작] 백그라운드 5일 평균 거래대금 갱신 시작 (시도 %d/%d)", attempt, _MAX_RETRIES)
            _broadcast_avg_amt_progress(0, 1, status="downloading")
            await refresh_avg_amt_5d_cache()
            logger.info("[시작] 백그라운드 5일 평균 거래대금 갱신 완료")
            _st._avg_amt_needs_bg_refresh = False
            _broadcast_avg_amt_progress(1, 1, status="completed")
            return
        except Exception as e:
            logger.error("[시작] 백그라운드 갱신 실패 (시도 %d/%d): %s", attempt, _MAX_RETRIES, e, exc_info=True)
            if attempt < _MAX_RETRIES:
                logger.info("[시작] %d초 후 재시도", _RETRY_INTERVAL)
                await asyncio.sleep(_RETRY_INTERVAL)
            else:
                logger.error("[시작] 최대 재시도 횟수 초과 -- 다음 기동까지 대기")
                _broadcast_avg_amt_progress(1, 1, status="failed")


async def _login_post_pipeline() -> None:
    """LOGIN 성공 후: 잔고 조회 -> 보유종목 REG -> WS 구독 등록."""
    from backend.app.services import engine_service as es
    _st._ws_reg_pipeline_done.clear()
    logger.info("[시작] 로그인 후 파이프라인 진입")
    try:
        await es._cleanup_stale_ws_subscriptions_on_session_ready()

        from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
        from backend.app.core.trade_mode import is_test_mode
        _in_ws_window = is_ws_subscribe_window(_st._settings_cache)

        if is_test_mode(_st._settings_cache):
            logger.info("[시작] 파이프라인 -- 테스트모드 -- REST 잔고 조회 생략 (가상잔고 사용)")
        elif not _in_ws_window:
            if not _st._account_rest_bootstrapped:
                import sys as _sys
                for _wait in range(3):
                    if getattr(_sys.modules.get("app.services.engine_service"), "_rest_api", None) is not None:
                        break
                    await asyncio.sleep(1.0)
                logger.info("[시작] 파이프라인 -- REST 잔고 선행 조회 시작")
                await es._update_account_memory(_st._settings_cache)
                logger.info("[시작] 파이프라인 -- REST 잔고 선행 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.info("[시작] 파이프라인 -- 잔고 이미 앱준비 완료 -- 재조회 생략 (보유 %d종목)", len(_st._positions))
        else:
            if not _st._positions and not _st._account_rest_bootstrapped:
                import sys as _sys
                for _wait in range(3):
                    if getattr(_sys.modules.get("app.services.engine_service"), "_rest_api", None) is not None:
                        break
                    await asyncio.sleep(1.0)
                logger.debug("[시작] 파이프라인 -- 실시간 구독 구간이나 포지션 미적재 -- REST 잔고 1회 조회")
                await es._update_account_memory(_st._settings_cache)
                logger.debug("[시작] 파이프라인 -- REST 잔고 1회 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.debug("[시작] 파이프라인 -- 실시간 구독 구간 -- REST 잔고 조회 생략 (실시간 수신, 보유 %d종목)", len(_st._positions))

        from backend.app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
        wl_codes: set[str] = set()
        for t, v in _st._sector_stock_layout:
            if t != "code":
                continue
            wl_codes.add(_format_kiwoom_reg_stk_cd(v))
        stale = wl_codes & _st._subscribed_stocks
        if stale:
            logger.debug("[시작] 새 세션 -- 0B 구독 상태 초기화 %d종목 (강제 재등록)", len(stale))
            _st._subscribed_stocks -= stale

        from backend.app.services import engine_account_notify as _account_notify
        # 시장구분 + NXT 캐시 적재 (저장데이터 로딩시 즉시, 미스 시 키움 REST 조회)
        await es._fetch_market_map_async()

        if _in_ws_window:
            # 키움 Connector 연결 확인 및 키움 구독
            if es._kiwoom_connector and es._kiwoom_connector.is_connected():
                await es._run_sector_reg_pipeline()
                await es._ensure_ws_subscriptions_for_positions()

            _account_notify.notify_desktop_sector_refresh()
            _account_notify.notify_desktop_sector_stocks_refresh()
        else:
            _st._ws_reg_pipeline_done.set()
            await _account_notify.notify_desktop_sector_refresh(force=True)
            _account_notify.notify_desktop_sector_stocks_refresh()
    except Exception as _e:
        logger.error("[시작] 로그인 후 파이프라인 예외: %s", _e, exc_info=True)


async def _run_sector_reg_pipeline() -> None:
    """REG 파이프라인 -- engine_service에서 위임."""
    from backend.app.services import engine_service as es
    await es._run_sector_reg_pipeline()

