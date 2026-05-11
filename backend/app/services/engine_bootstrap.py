# -*- coding: utf-8 -*-
"""
엔진 부트스트랩 흐름.

순환 import 방지: `import app.services.engine_state as _st` 로 상태 접근.
engine_service의 함수가 필요하면 lazy import (`from app.services import engine_service`).
"""
from __future__ import annotations

import asyncio

from app.core.logger import get_logger
import app.services.engine_state as _st

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
        from app.web.ws_manager import ws_manager
        payload = {
            "_v": 1,
            "stage_id": stage_id,
            "stage_name": stage_name,
            "total": len(BOOTSTRAP_STAGES),
        }
        if progress is not None:
            payload["progress"] = progress
        ws_manager.broadcast("bootstrap-stage", payload)
    except Exception:
        pass


async def _bootstrap_sector_stocks_async() -> None:
    """
    업종맵(ka10099) 기반 전체 종목 초기 시세 로드.
    캐시 데이터가 있으면 REST API 없이도 부트스트랩 완료 가능.
    """
    _st._bootstrap_event.clear()
    _st._sector_summary_ready_event.clear()

    # ── 테스트모드: Settlement Engine 상태 복원 ──
    if (_st._settings_cache or {}).get("trade_mode") == "test":
        from app.services import settlement_engine
        settlement_engine._load()
        logger.info("[앱준비] Settlement Engine 상태 복원 완료 (테스트모드)")

    from app.services.engine_symbol_utils import _base_stk_cd
    from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
    from app.core.sector_stock_cache import (
        load_layout_cache, save_layout_cache,
        load_snapshot_cache,
    )
    from app.core.avg_amt_cache import load_avg_amt_cache

    # ── 0단계: 레이아웃 캐시 확인 → 사용 시 업종맵 API 스킵 ──────────────
    _broadcast_bootstrap_stage(1, "레이아웃 저장데이터 확인")
    _preboot_hit = _st._preboot_cache_loaded and len(_st._sector_stock_layout) > 0

    if _preboot_hit:
        # 데이터준비에서 이미 레이아웃·확정데이터·5일평균 로드 완료 — 파일 재로드 스킵
        logger.info(
            "[앱준비] 데이터준비 사용 -- %d종목 (레이아웃·확정데이터·5일평균 재로드 생략)",
            sum(1 for t, _ in _st._sector_stock_layout if t == "code"),
        )
        _broadcast_bootstrap_stage(2, "섹터 매핑 로드")
    elif (_layout_cached := load_layout_cache()):
        _st._sector_stock_layout[:] = _layout_cached
        logger.info(
            "[앱준비] 레이아웃 저장데이터 로드 -- %d종목 (업종맵 API 생략)",
            sum(1 for t, _ in _layout_cached if t == "code"),
        )
        _broadcast_bootstrap_stage(2, "섹터 매핑 로드")
    else:
        _broadcast_bootstrap_stage(2, "섹터 매핑 로드")
        # ka10099 종목코드 목록 + sector_custom.json 기반 그룹핑
        from app.core.industry_map import get_eligible_stocks
        from app.core.sector_mapping import get_merged_sector
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
            logger.info(
                "[앱준비] 업종 매핑 기반 자동 구성 -- %d종목 / %d섹터",
                sum(1 for t, _ in auto_layout if t == "code"),
                len(sector_groups),
            )
            save_layout_cache(auto_layout)
        else:
            logger.info("[앱준비] 섹터 매핑 데이터 없음 -- 레이아웃 자동 구성 생략")

    codes: list[str] = [v for t, v in _st._sector_stock_layout if t == "code"]
    if not codes:
        logger.info("[앱준비] 업종맵 종목 없음 -- 초기화 생략")
        return

    # ── WS 구독 구간 판정 (구간 안이면 확정데이터 시세 초기화) ──
    try:
        from app.services.daily_time_scheduler import is_ws_subscribe_window
        _in_ws_window = is_ws_subscribe_window(_st._settings_cache)
    except Exception:
        _in_ws_window = False

    # ── 2단계: 확정데이터 캐시 확인 → 사용 시 UI 즉시 표시 ──────────────────
    _broadcast_bootstrap_stage(3, "KRX 확정데이터 로드 중")
    krx_rows: list[tuple[str, dict]] = []

    _preboot_snapshot_hit = _preboot_hit and len(_st._pending_stock_details) > 0

    if _preboot_snapshot_hit:
        # 데이터준비에서 이미 확정데이터 → 메모리 적재 완료 — 파일 재로드 + 버킷 세팅 스킵
        logger.info("[앱준비] 데이터준비 사용 -- 확정데이터·거래대금 데이터 재로드 생략 (%d종목)", len(_st._pending_stock_details))
        _broadcast_bootstrap_stage(4, "시세 데이터 반영")
    elif (_snapshot_cached := load_snapshot_cache()):
        krx_rows = _snapshot_cached
        logger.info("[앱준비] 확정데이터 저장데이터 로드 -- %d종목 (UI 즉시 표시)", len(krx_rows))
    else:
        logger.info("[앱준비] 확정데이터 저장데이터 실패 -- 로드 생략 (장마감 후 ka10086 확정 조회로 갱신)")

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

        logger.info(
            "[거래대금·초기화] REST 버킷 세팅 완료 -- 005930=%s",
            f"{_st._latest_trade_amounts.get('005930', 0):,}",
        )

        if krx_rows:
            from app.services import engine_strategy_core
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
            logger.info("[앱준비] 확정데이터 반영 완료 -- %d행 (화면 표시)", len(krx_rows))
        else:
            logger.warning("[앱준비] 확정데이터 없음 -- 화면 표시 생략")

        if krx_rows:
            logger.info("[앱준비] 확정데이터 저장데이터 로드 -- 백그라운드 REST 갱신 생략 (저장데이터 사용)")

    # ── 7단계: 5일 평균 거래대금 ──────
    _broadcast_bootstrap_stage(5, "5일 평균 저장데이터 로드")
    _st._avg_amt_needs_bg_refresh = False
    if _preboot_hit and len(_st._avg_amt_5d) > 0:
        # 데이터준비에서 이미 5일 평균 로드 완료 — 파일 재로드 스킵
        logger.info(
            "[앱준비] 데이터준비 사용 -- 5일거래대금평균/고가 재로드 생략 (%d종목)", len(_st._avg_amt_5d)
        )
    else:
        try:
            _avg_result = load_avg_amt_cache()
            if _avg_result is not None:
                _avg_map, _high_map = _avg_result
                _st._update_avg_amt_5d(_avg_map)
                if _high_map:
                    _st._high_5d_cache.clear()
                    _st._high_5d_cache.update(_high_map)
                # ── 불완전 캐시 판정 (is_cache_valid() 통과 후 구조 검증) ──
                _incomplete = False
                if not _high_map:
                    logger.warning("[앱준비] 저장데이터 불완전 -- high_5d 없음")
                    _incomplete = True
                elif len(_high_map) != len(_avg_map):
                    logger.warning("[앱준비] 저장데이터 불완전 -- high_5d 종목수(%d) ≠ avg_map 종목수(%d)", len(_high_map), len(_avg_map))
                    _incomplete = True
                else:
                    # 배열 길이 < 5 검사는 v2 원본에서 해야 함
                    from app.core.avg_amt_cache import load_avg_amt_cache_v2
                    _v2_result = load_avg_amt_cache_v2()
                    _v2_raw = _v2_result[0] if _v2_result else None
                    if _v2_raw:
                        _short = sum(1 for arr in _v2_raw.values() if len(arr) < 5)
                        if _short > 0:
                            logger.warning("[앱준비] 저장데이터 불완전 -- 배열 길이 < 5인 종목 %d개", _short)
                            _incomplete = True
                        _zero_high = sum(1 for v in _high_map.values() if v == 0)
                        if _zero_high > len(_high_map) * 0.5:
                            logger.warning("[앱준비] 저장데이터 불완전 -- high_5d=0 종목 %d/%d (50%% 초과)", _zero_high, len(_high_map))
                            _incomplete = True
                if _incomplete:
                    _st._avg_amt_needs_bg_refresh = True
                logger.info(
                    "[앱준비] 5일 평균 거래대금 저장데이터 로드 -- %d종목, high_5d=%d%s",
                    len(_st._avg_amt_5d), len(_high_map),
                    " (불완전 -- 갱신 예정)" if _incomplete else "",
                )
            else:
                # 캐시 만료 — stale v2 데이터가 있으면 일단 로드 (즉시 필터 동작)
                from app.core.avg_amt_cache import load_avg_amt_cache_v2, avg_from_v2
                _stale_result = load_avg_amt_cache_v2()
                stale_v2 = _stale_result[0] if _stale_result else None
                if stale_v2 and len(stale_v2) > 100:
                    avg_map = avg_from_v2(stale_v2)
                    _st._update_avg_amt_5d(avg_map)
                    logger.info(
                        "[앱준비] 5일 평균 저장데이터 만료 -- stale 데이터 즉시 로드 (%d종목, 백그라운드 갱신 예정)",
                        len(avg_map),
                    )
                    _st._avg_amt_needs_bg_refresh = True
                else:
                    logger.info(
                        "[앱준비] 5일 평균 거래대금 저장데이터 미스 -- 빈 맵으로 시작 (백그라운드 구축 예정)"
                    )
                    _st._avg_amt_needs_bg_refresh = True
        except Exception as e:
            logger.warning("[앱준비] 5일 평균 거래대금 적재 실패: %s", e)
            _st._avg_amt_needs_bg_refresh = True

    try:
        from app.services import engine_account_notify as _account_notify
        _account_notify.notify_desktop_buy_radar_only()
    except Exception:
        pass
    _src = "섹터매핑" if len(_st._sector_stock_layout) > 0 else "없음"
    _snapshot_count = len(_st._pending_stock_details) if _preboot_hit else len(krx_rows)
    _layout_count = sum(1 for t, _ in _st._sector_stock_layout if t == "code")
    _avg_count = len(_st._avg_amt_5d)
    _filtered_count = len(_st._filtered_sector_codes) if _st._filtered_sector_codes else 0
    
    logger.info(
        "[앱준비] 모든 준비 완료 -- 총 %d종목 "
        "(레이아웃=%d, 확정데이터=%d, 5일평균=%d, 필터통과=%d, 소스=%s)",
        len(codes), _layout_count, _snapshot_count, _avg_count, _filtered_count, _src,
    )

    # ── 8단계: 장외 시간 앱 시작 시 확정 데이터 갱신 ────
    try:
        from datetime import datetime, timezone, timedelta
        from app.core.trading_calendar import is_krx_holiday, kst_today
        from app.core.trade_mode import is_test_mode
        _KST = timezone(timedelta(hours=9))
        _h = datetime.now(_KST).hour
        _is_holiday = is_krx_holiday(kst_today())
        _is_off_market = _is_holiday or _h >= 20 or _h < 8 or (_h >= 15 and datetime.now(_KST).minute >= 30)
        if _is_off_market and not is_test_mode(_st._settings_cache) and _st._rest_api:
            logger.info(
                "[앱준비][장외갱신] 장외 시간(%02d시, 휴일=%s) -- ka10086 백그라운드 갱신 예약 (0B REG 비블로킹)",
                _h, _is_holiday,
            )
            asyncio.get_event_loop().create_task(_notify_close_data_ui())

        if _st._avg_amt_needs_bg_refresh:
            logger.info(
                "[앱준비][장외갱신] 5일 평균 저장데이터 갱신 필요 플래그 설정됨 (%d종목) -- _rest_api 설정 후 예약 예정",
                len(_st._avg_amt_5d),
            )
    except Exception as _e:
        logger.warning("[앱준비][장외갱신] 갱신 예약 실패(무시): %s", _e)

    # ── 확정 상태 초기화 (제거됨 — 실시간 연동 전환) ──
    _st._sector_summary_cache = None
    _st._filtered_sector_codes = _st._compute_filtered_codes()
    _st._invalidate_sector_stocks_cache()
    logger.info(
        "[앱준비] 필터 통과 종목 %d개",
        len(_st._filtered_sector_codes or set()),
    )

    # ── 필터 통과 종목 중 _pending_stock_details에 없는 종목 빈 엔트리 추가 ──
    # WS 실시간 데이터 수신을 위해 엔트리가 존재해야 함
    _filter_set = _st._filtered_sector_codes or set()
    _missing = _filter_set - set(_st._pending_stock_details.keys())
    if _missing:
        from app.services import engine_strategy_core as _esc
        from app.core.sector_stock_cache import load_stock_name_cache as _load_names
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
        logger.debug("[앱준비] 필터 통과 빈 엔트리 추가 -- %d종목 (실시간 수신 대기)", len(_missing))

    _broadcast_bootstrap_stage(6, "앱준비 완료")
    _st._bootstrap_event.set()
    logger.info("[앱준비] 앱준비 완료 플래그 설정")

    # engine-ready WS는 engine_loop.py에서 1회만 전송 — 여기서는 중복 전송하지 않음

    # ── 업종순위 후순위 계산 (create_task — WS 전송을 블로킹하지 않음) ──
    _task = asyncio.create_task(_deferred_sector_summary())
    _task.add_done_callback(lambda t: t.exception() if t.exception() else None)

    # 앱준비 완료 → 섹터 재계산 트리거 (이벤트 기반)
    from app.services import engine_service
    from app.services.engine_sector_confirm import recompute_sector_for_code
    # WS 구간 안이면 delta 비교 캐시 초기화 (전일 데이터 잔존 방지)
    if _in_ws_window:
        import app.services.engine_account_notify as _an
        _an._prev_scores_cache = []
    recompute_sector_for_code(None)  # 전체 재계산

    # 앱준비 완료 → 기동 시 스킵된 장마감 파이프라인 데이터동기화중 재시도
    try:
        from app.services.daily_time_scheduler import retry_pipeline_catchup_after_bootstrap
        retry_pipeline_catchup_after_bootstrap()
    except Exception as _catchup_err:
        logger.warning("[앱준비] 데이터동기화중 재시도 실패(무시): %s", _catchup_err)


async def _deferred_sector_summary() -> None:
    """업종순위 후순위 계산 — _bootstrap_event.set() 이후 비동기 실행.

    compute_full_sector_summary()는 CPU-bound이므로 asyncio.to_thread()로
    별도 스레드에서 실행하여 이벤트 루프 블로킹을 방지한다.
    완료 후 _sector_summary_ready_event.set() + WS 3종 전송.
    """
    try:
        from app.services.engine_sector_score import compute_full_sector_summary
        _inputs = _st.get_sector_summary_inputs()
        if _inputs.get("all_codes"):
            _settings = _st._settings_cache or {}
            # 앱준비 시점에 _settings_cache가 아직 빈 딕셔너리일 수 있음
            # → 설정 파일에서 직접 로드하여 사용자 설정값 반영 보장
            if not _settings:
                from app.core.settings_file import load_settings
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
            logger.info("[앱준비] 업종순위 후순위 계산 완료 -- %d개 섹터", len(_result.sectors))

            # 이벤트 발행 — _send_stocks_delayed()가 대기 중이면 해제
            _st._sector_summary_ready_event.set()

            # WS broadcast — 이미 연결된 클라이언트에게 전송
            try:
                from app.services.engine_account_notify import (
                    notify_desktop_sector_scores,
                    notify_desktop_sector_stocks_refresh,
                    notify_buy_targets_update,
                )
                from app.web.ws_manager import ws_manager
                _client_cnt = ws_manager.client_count
                notify_desktop_sector_scores(force=True)
                notify_desktop_sector_stocks_refresh()
                notify_buy_targets_update()
                logger.info("[앱준비] 업종순위 화면전송 완료 (접속화면=%d)", _client_cnt)
            except Exception:
                pass
        else:
            # 종목 없음 — 이벤트만 발행 (대기 해제)
            _st._sector_summary_ready_event.set()
    except Exception as _e:
        logger.warning("[앱준비] 업종순위 후순위 계산 실패(무시): %s", _e)
        _st._sector_summary_ready_event.set()  # 실패해도 대기 해제


async def _notify_close_data_ui() -> None:
    """장외 확정 데이터 갱신 -- UI 알림 트리거."""
    try:
        from app.services import engine_account_notify as _account_notify
        try:
            _account_notify.notify_desktop_buy_radar_only()
        except Exception:
            pass
        try:
            _account_notify.notify_desktop_sector_refresh()
            logger.info("[앱준비][장외갱신] 섹터 분석 패널 갱신 트리거")
        except Exception:
            pass
    except Exception as _e:
        logger.warning("[앱준비][장외갱신] 확정 데이터 갱신 실패(무시): %s", _e)


async def refresh_avg_amt_5d_cache() -> None:
    """
    장 마감 후 5일 평균 거래대금 캐시 갱신.
    - v2 캐시 있으면: ka20002 롤링 갱신 (약 30초)
    - v2 캐시 없으면: ka10086 × 5영업일 병렬 호출로 최초 구축 (백그라운드, Chunk 단위)
    Chunk 단위로 세마포어를 acquire/release하여 다른 REST 호출을 블로킹하지 않음.
    """
    # 스케줄러 토글 OFF 시 5일봉 전체 다운로드 스킵
    _settings = _st._settings_cache or {}
    if not _settings.get("scheduler_5d_download_on", True):
        logger.info("[전종목5일챠트] scheduler_5d_download_on=OFF — 전종목5일챠트 다운로드 생략")
        return

    if _st._avg_amt_refresh_running:
        logger.info("[전종목5일챠트] 이미 진행 중 -- 생략")
        return
    _st._avg_amt_refresh_running = True
    try:
        await _refresh_avg_amt_5d_cache_inner()
    finally:
        _st._avg_amt_refresh_running = False


async def _chunked_fetch_full_5d(
    sector_prov, codes: list[str], on_progress=None,
    *,
    resume_completed: "set[str] | None" = None,
    resume_v2: "dict[str, list[int]] | None" = None,
    resume_high_cache: "dict[str, int] | None" = None,
    resume_high_5d_arr: "dict[str, list[int]] | None" = None,
    date_str: str = "",
) -> tuple[dict[str, list[int]], dict[str, int], dict[str, list[int]]]:
    """Chunk 단위로 세마포어를 acquire/release하며 ka10081(_AL) × 1회 순차 호출.
    다른 REST 호출(잔고, 시세 등)이 Chunk 사이에 끼어들 수 있음.
    진행률 콜백은 메인 이벤트 루프에서 호출 (워커 스레드 안전).

    Args:
        sector_prov: SectorProvider 인터페이스 (broker_providers.py 경유)
        resume_*: 이어받기 복원 데이터 (없으면 처음부터)
        date_str: 진행 파일 저장용 거래일 (YYYYMMDD)

    Returns:
        (v2_data, high_cache, high_5d_arr)
        v2_data:     {종목코드: [5일치 거래대금 배열, 백만원, 오래된→최신]}
        high_cache:  {종목코드: max(5일 고가)}
        high_5d_arr: {종목코드: [5일치 고가 배열, 원, 오래된→최신]}
    """
    import time
    from app.core.avg_amt_cache import _norm_stk, KA10005_GAP_SEC, save_avg_amt_progress
    result: dict[str, list[int]] = dict(resume_v2 or {})
    high_cache: dict[str, int] = dict(resume_high_cache or {})
    high_5d_arr: dict[str, list[int]] = dict(resume_high_5d_arr or {})
    completed_set: set[str] = set(resume_completed or set())
    total = len(codes)
    starting_count = len(completed_set)
    if starting_count > 0:
        logger.info("[ka10081] 이어받기 — %d/%d종목 복원, 나머지 %d종목 다운로드",
                    starting_count, total, total - starting_count)
    else:
        logger.info("[ka10081] 전종목 5일 거래대금/고가 다운로드 시작 — 대상 %d종목", total)
    remaining_codes = [cd for cd in codes if _norm_stk(cd) not in completed_set]
    for chunk_start in range(0, len(remaining_codes), _st._AVG_AMT_CHUNK_SIZE):
        chunk = remaining_codes[chunk_start : chunk_start + _st._AVG_AMT_CHUNK_SIZE]
        def _sync_chunk(c=chunk):
            out_amts: dict[str, list[int]] = {}
            out_highs: dict[str, int] = {}
            out_high_arr: dict[str, list[int]] = {}
            for i, raw in enumerate(c):
                nk = _norm_stk(raw)
                if not nk:
                    continue
                amts, highs = sector_prov.fetch_daily_5d_data(nk)
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
                if i + 1 < len(c):
                    time.sleep(KA10005_GAP_SEC)
            return out_amts, out_highs, out_high_arr
        async with _st._get_rest_api_thread_sem():
            chunk_amts, chunk_highs, chunk_high_arr = await asyncio.to_thread(_sync_chunk)
        result.update(chunk_amts)
        high_cache.update(chunk_highs)
        high_5d_arr.update(chunk_high_arr)
        completed_set.update(chunk_amts.keys())
        # 진행률 콜백은 메인 이벤트 루프에서 호출 (WS broadcast 안전)
        done = starting_count + chunk_start + len(chunk)
        done = min(done, total)
        pct = int(done / total * 100) if total else 0
        logger.info("[ka10081] 전종목 5일거래대금/고가 다운로드 중 (%d/%d, %d%%)", done, total, pct)
        # Chunk 완료마다 진행 파일 저장 (이어받기 가능하도록)
        if date_str:
            save_avg_amt_progress(
                date_str, list(completed_set), codes,
                result, high_cache, high_5d_arr,
            )
        if on_progress:
            try:
                on_progress(done, total)
            except Exception:
                pass
    success = len(result)
    failed = total - success
    valid_high = sum(1 for v in high_cache.values() if v > 0)
    logger.info("[ka10081] 전종목 5일 거래대금/고가 다운로드 완료 — 성공 %d종목, 실패 %d종목, 유효고가 %d종목", success, failed, valid_high)
    return result, high_cache, high_5d_arr


async def _refresh_avg_amt_5d_cache_inner() -> None:
    """refresh_avg_amt_5d_cache 내부 구현. 플래그 관리는 외부에서."""
    from app.core.avg_amt_cache import (
        load_avg_amt_cache_v2, save_avg_amt_cache_v2, avg_from_v2,
    )
    from app.services import engine_account_notify as _account_notify

    if not _st._rest_api:
        logger.debug("[전종목5일챠트] REST API 없음 -- 생략 (엔진 준비 중)")
        return

    from app.core.industry_map import get_real_industry_codes

    industry_codes: list[tuple[str, str]] = []
    try:
        real_codes_raw = get_real_industry_codes()
        if real_codes_raw:
            for item in real_codes_raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    industry_codes.append((str(item[0]), str(item[1])))
    except Exception as e:
        logger.warning("[전종목5일챠트] 실제 업종코드 로딩 실패: %s", e)

    _v2_result = load_avg_amt_cache_v2()
    existing_v2 = _v2_result[0] if _v2_result else None

    # v2 캐시 존재 + 유통기한 유효 → 장마감 파이프라인 롤링 갱신에 맡기고 스킵
    # v2 캐시 존재 + 유통기한 만료 → 무시하고 ka10086 전체 구축 진행
    if existing_v2 and len(existing_v2) > 100:
        from app.core.avg_amt_cache import _DEFAULT_CACHE_PATH
        from app.core.trading_calendar import is_cache_valid
        _cached_date = ""
        try:
            import json as _json
            _raw = _json.loads(_DEFAULT_CACHE_PATH.read_text(encoding="utf-8"))
            _cached_date = _raw.get("date", "")
        except Exception:
            pass
        if _cached_date and is_cache_valid(_cached_date):
            # high_5d도 같은 JSON에서 직접 추출 (파일 재읽기 없음)
            _h5d_raw = _raw.get("high_5d")
            if isinstance(_h5d_raw, dict) and _h5d_raw:
                _h5d = {str(k): int(v) for k, v in _h5d_raw.items() if isinstance(v, (int, float))}
                _st._high_5d_cache.clear()
                _st._high_5d_cache.update(_h5d)
                logger.info("[전종목5일챠트] v2 저장데이터 유효 (%d종목, date=%s) -- 생략, high_5d %d종목 복원", len(existing_v2), _cached_date, len(_h5d))
            else:
                logger.info("[전종목5일챠트] v2 저장데이터 유효 (%d종목, date=%s) -- 생략 (high_5d 없음)", len(existing_v2), _cached_date)
            return
        else:
            logger.info("[전종목5일챠트] v2 저장데이터 만료 (%d종목, date=%s) -- 전체 구축 진행", len(existing_v2), _cached_date)

    # v2 만료 시에도 전체 구축 진행 (위에서 유효하면 이미 return됨)
    from app.core.avg_amt_cache import _norm_stk
    from app.core.industry_map import get_eligible_stocks
    _elig = get_eligible_stocks()
    if not _elig:
        logger.warning("[전종목5일챠트] 매매적격종목 없음 -- 구축 생략")
        return
    all_codes = list(dict.fromkeys(_norm_stk(_cd) for _cd in _elig if _norm_stk(_cd)))

    # 이어받기: 진행 파일 로드
    from app.core.avg_amt_cache import load_avg_amt_progress, clear_avg_amt_progress
    from app.core.trading_calendar import current_trading_date_str
    _today_str = current_trading_date_str()
    _ws_start = str((_st._settings_cache or {}).get("ws_subscribe_start") or "07:50")
    _resume = load_avg_amt_progress(_today_str, all_codes, _ws_start)
    if _resume:
        _r_completed, _r_v2, _r_high, _r_high_arr = _resume
        logger.info("[전종목5일챠트] 이어받기 — %d/%d종목 복원, 나머지 %d종목 다운로드",
                    len(_r_completed), len(all_codes), len(all_codes) - len(_r_completed))
    else:
        _r_completed, _r_v2, _r_high, _r_high_arr = set(), {}, {}, {}

    logger.info("[전종목5일챠트] v2 저장데이터 없거나 만료 -- %d종목 ka10086 Chunk 구축 시작 (Chunk=%d종목)",
                len(all_codes), _st._AVG_AMT_CHUNK_SIZE)
    _broadcast_avg_amt_progress(len(_r_completed), len(all_codes), status="downloading")
    try:
        from app.core.broker_factory import get_router
        _sector_prov = get_router(_st._settings_cache or {}).sector
        v2_data, high_cache, high_5d_arr = await _chunked_fetch_full_5d(
            _sector_prov, all_codes,
            on_progress=_broadcast_avg_amt_progress,
            resume_completed=_r_completed,
            resume_v2=_r_v2,
            resume_high_cache=_r_high,
            resume_high_5d_arr=_r_high_arr,
            date_str=_today_str,
        )
        from app.core.avg_amt_cache import _kst_today_yyyymmdd
        save_avg_amt_cache_v2(v2_data, _kst_today_yyyymmdd(), high_5d=high_cache, high_5d_arr=high_5d_arr)
        clear_avg_amt_progress()
        avg_map = avg_from_v2(v2_data)

        # ── 완전한 매핑 단계 (적격종목 × 시세 × 5일데이터 × 업종) ──────────
        from app.core.sector_mapping import get_merged_sector
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
            "[전종목5일챠트] 전체 구축 완료 -- %d종목 (매핑완료=%d), HighCache %d종목 적재 (유효 %d), 부적격 %d종목 제거",
            len(avg_map), len(fully_mapped), len(new_high), valid_high_count, len(ineligible_codes),
        )
    except Exception as e:
        logger.error("[전종목5일챠트] 전체 구축 실패: %s", e)

    try:
        from app.services.engine_service import recompute_sector_summary_now
        recompute_sector_summary_now()
        _account_notify.notify_desktop_sector_refresh()
        _account_notify.notify_desktop_sector_stocks_refresh()
        _account_notify.notify_desktop_sector_scores(force=True)
    except Exception:
        pass
    _broadcast_avg_amt_progress(1, 1, status="completed")


def _broadcast_avg_amt_progress(current: int, total: int, *, status: str = "") -> None:
    """5일 평균 거래대금 구축 진행률 브로드캐스트.

    status 값: downloading, completed, failed, partial, cache_deleted, token_pending, requested
    """
    try:
        from app.web.ws_manager import ws_manager
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
    except Exception:
        pass


async def _bg_refresh_avg_amt_5d() -> None:
    """5일 평균 거래대금 캐시 갱신 — 백그라운드 태스크. 실패 시 60초 간격 최대 3회 재시도."""
    if _st._avg_amt_refresh_running:
        logger.info("[bg_전종목5일챠트] 이미 갱신 진행 중 -- 생략")
        return
    _MAX_RETRIES = 3
    _RETRY_INTERVAL = 60
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info("[bg_전종목5일챠트] 백그라운드 5일 평균 거래대금 갱신 시작 (시도 %d/%d)", attempt, _MAX_RETRIES)
            _broadcast_avg_amt_progress(0, 1, status="downloading")
            await refresh_avg_amt_5d_cache()
            logger.info("[bg_전종목5일챠트] 백그라운드 5일 평균 거래대금 갱신 완료")
            _st._avg_amt_needs_bg_refresh = False
            _broadcast_avg_amt_progress(1, 1, status="completed")
            return
        except Exception as e:
            logger.error("[bg_전종목5일챠트] 백그라운드 갱신 실패 (시도 %d/%d): %s", attempt, _MAX_RETRIES, e)
            if attempt < _MAX_RETRIES:
                logger.info("[bg_전종목5일챠트] %d초 후 재시도", _RETRY_INTERVAL)
                await asyncio.sleep(_RETRY_INTERVAL)
            else:
                logger.error("[bg_전종목5일챠트] 최대 재시도 횟수 초과 -- 다음 기동까지 대기")
                _broadcast_avg_amt_progress(1, 1, status="failed")


async def _login_post_pipeline() -> None:
    """LOGIN 성공 후: 잔고 조회 -> 보유종목 REG -> WS 구독 등록."""
    from app.services import engine_service as es
    _st._ws_reg_pipeline_done.clear()
    logger.info("[앱준비] 로그인 후 파이프라인 진입")
    try:
        await es._cleanup_stale_ws_subscriptions_on_session_ready()

        from app.services.daily_time_scheduler import is_ws_subscribe_window
        from app.core.trade_mode import is_test_mode
        _in_ws_window = is_ws_subscribe_window(_st._settings_cache)

        if is_test_mode(_st._settings_cache):
            logger.info("[앱준비] 파이프라인 -- 테스트모드 -- REST 잔고 조회 생략 (가상잔고 사용)")
        elif not _in_ws_window:
            if not _st._account_rest_bootstrapped:
                import sys as _sys
                for _wait in range(3):
                    if getattr(_sys.modules.get("app.services.engine_service"), "_rest_api", None) is not None:
                        break
                    await asyncio.sleep(1.0)
                logger.info("[앱준비] 파이프라인 -- REST 잔고 선행 조회 시작")
                await es._update_account_memory(_st._settings_cache)
                logger.info("[앱준비] 파이프라인 -- REST 잔고 선행 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.info("[앱준비] 파이프라인 -- 잔고 이미 앱준비 완료 -- 재조회 생략 (보유 %d종목)", len(_st._positions))
        else:
            if not _st._positions and not _st._account_rest_bootstrapped:
                import sys as _sys
                for _wait in range(3):
                    if getattr(_sys.modules.get("app.services.engine_service"), "_rest_api", None) is not None:
                        break
                    await asyncio.sleep(1.0)
                logger.debug("[앱준비] 파이프라인 -- 실시간 구독 구간이나 포지션 미적재 -- REST 잔고 1회 조회")
                await es._update_account_memory(_st._settings_cache)
                logger.debug("[앱준비] 파이프라인 -- REST 잔고 1회 조회 완료 (보유 %d종목)", len(_st._positions))
            else:
                logger.debug("[앱준비] 파이프라인 -- 실시간 구독 구간 -- REST 잔고 조회 생략 (실시간 수신, 보유 %d종목)", len(_st._positions))

        from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
        wl_codes: set[str] = set()
        for t, v in _st._sector_stock_layout:
            if t != "code":
                continue
            wl_codes.add(_format_kiwoom_reg_stk_cd(v))
        stale = wl_codes & _st._subscribed_stocks
        if stale:
            logger.debug("[앱준비] 새 세션 -- 0B 구독 상태 초기화 %d종목 (강제 재등록)", len(stale))
            _st._subscribed_stocks -= stale

        from app.services import engine_account_notify as _account_notify
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
        logger.error("[앱준비] 로그인 후 파이프라인 예외: %s", _e, exc_info=True)


async def _run_sector_reg_pipeline() -> None:
    """REG 파이프라인 -- engine_service에서 위임."""
    from app.services import engine_service as es
    await es._run_sector_reg_pipeline()

