# -*- coding: utf-8 -*-
"""
엔진 부트스트랩 흐름.

순환 import 방지: `import backend.app.services.engine_state as _st` 로 상태 접근.
engine_service의 함수가 필요하면 lazy import (`from backend.app.services import engine_service`).
"""
from __future__ import annotations

import asyncio

from backend.app.core.logger import get_logger
from backend.app.core.avg_amt_cache import (
    is_avg_amt_5d_map_usable,
    load_avg_amt_from_sector_summary_cache,
    load_avg_amt_cache,
    normalize_avg_amt_5d_value,
)
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
        
        if not stock_codes:
            from backend.app.db.crud import get_all_stocks
            _db_stocks = get_all_stocks()
            if _db_stocks:
                stock_codes = {row["code"]: "" for row in _db_stocks}
                logger.info("[시작] 적격종목 캐시 없음 -- DB stocks 테이블 기반 임시 복구 (%d종목)", len(stock_codes))

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
        _broadcast_bootstrap_stage(6, "앱준비 완료")
        _st._bootstrap_event.set()
        _st._sector_summary_ready_event.set()
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
        async with _st._shared_lock:
            for cd, detail in krx_rows:
                base = _format_kiwoom_reg_stk_cd(_base_stk_cd(cd))
                amt = int(detail.get("trade_amount") or 0)
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
            async with _st._shared_lock:
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
                            sector=detail.get("sector", "기타"),
                        )
                        entry["status"] = "active"
                        entry["base_price"] = int(detail.get("cur_price") or 0)
                        entry["target_price"] = int(detail.get("cur_price") or 0)
                        entry["captured_at"] = ""
                        entry["reason"] = "확정데이터 초기 로드"
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
                cd = _format_kiwoom_reg_stk_cd(row["code"])
                _avg_map[cd] = normalize_avg_amt_5d_value(row.get("avg_5d_trade_amount"))
                _high_map[cd] = int(row.get("high_5d_price") or 0)

            if not is_avg_amt_5d_map_usable(_avg_map):
                recovered_avg = load_avg_amt_from_sector_summary_cache()
                if is_avg_amt_5d_map_usable(recovered_avg):
                    _avg_map = recovered_avg
                    logger.warning("[시작] DB 5일평균 비정상 -- SectorSummary 캐시에서 복구 (%d종목)", len(_avg_map))
                else:
                    cached_result = load_avg_amt_cache()
                    if cached_result and is_avg_amt_5d_map_usable(cached_result[0]):
                        _avg_map, _high_map = cached_result
                        logger.warning("[시작] DB 5일평균 비정상 -- avg_amt 캐시에서 복구 (%d종목)", len(_avg_map))
            
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
            from backend.app.core.sector_mapping import get_merged_sector
            _entry = _esc.make_detail(_cd, _nm, 0, "3", 0, 0.0, sector=get_merged_sector(_cd))
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
                min_avg_amt_eok=float(_settings.get("sector_min_trade_amt", 0.0)),
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

