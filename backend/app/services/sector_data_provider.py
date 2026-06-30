# -*- coding: utf-8 -*-
"""
섹터 데이터 제공자 - 업종 요약 계산 관련 함수

단일 소스 진리 원칙: master_stocks_cache 직접 접근
"""

# ──────────────────────────────────────────────────────────────────────────────
# 업종 요약 계산 관련 함수
# ──────────────────────────────────────────────────────────────────────────────

async def get_sector_summary_inputs() -> dict:
    """업종 요약 계산 입력 데이터 반환.

    단일 소스 진리: master_stocks_cache를 직접 참조하므로 스냅샷 제거.
    NXT-only 구간(08:00~09:00, 15:30~20:00) 거래일에는 NXT-enabled 종목만 포함.
    정규장(09:00~15:30)에는 전체 종목 포함.
    """
    from backend.app.services.engine_symbol_utils import is_nxt_enabled as _is_nxt
    from backend.app.services.daily_time_scheduler import is_nxt_only_window

    # 우측테이블의 종목들을 그대로 사용 (단일 소스 진리)
    # get_sector_stocks는 이미 5일평균거래대금 필터링된 종목들만 반환
    sector_stocks_list = await get_sector_stocks()

    # NXT-only 구간(08:00~09:00, 15:30~20:00) 거래일: NXT-enabled 종목만 포함
    # KRX 단독 종목은 틱 수신 불가하므로 업종 점수 및 수신율에서 제외
    if is_nxt_only_window():
        sector_stocks_list = [
            entry for entry in sector_stocks_list
            if _is_nxt(entry["code"])
        ]

    # all_codes만 반환 (스냅샷 제거)
    all_codes = [entry["code"] for entry in sector_stocks_list]

    # 필터링된 종목만 avg_amt_5d 추출
    avg_amt_5d = {entry["code"]: int(entry.get("avg_amt_5d", 0) or 0)
                  for entry in sector_stocks_list}

    return {
        "all_codes": all_codes,  # 우측테이블의 종목만 반환
        "trade_prices": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "trade_amounts": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "avg_amt_5d": avg_amt_5d,
        "latest_index": {},
    }


async def get_sector_stocks() -> list:
    """업종별 종목 시세 테이블용 — _master_stocks_cache 기반 실시간 필터링/정렬."""
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.core.sector_mapping import get_merged_sectors_batch
    from backend.app.services.engine_state import state
    import backend.app.services.engine_service as _es_ref

    # 5일평균거래대금 필터링 (백엔드에서 필터링 수행 - 단일 소스 진리)
    min_avg_amt_eok = float(_es_ref._integrated_system_settings_cache["sector_min_trade_amt"])

    merged: dict[str, dict] = {}

    # 단일 소스 진리: state.master_stocks_cache가 종목 데이터의 단일 소스
    all_stocks = state.master_stocks_cache.copy()

    # 1차 필터링: 시세/이름 없는 엔트리 제거 + 5일평균거래대금 필터링
    valid_codes: list[str] = []
    for cd in all_stocks.keys():
        e = state.master_stocks_cache.get(cd, {}).copy()
        e["code"] = cd
        e["status"] = "active"
        if int(e.get("cur_price") or 0) <= 0 and (not e.get("name") or e.get("name") == cd):
            continue
        avg5d_million = int(e.get("avg_5d_trade_amount", 0) or 0)
        e["avg_amt_5d"] = avg5d_million
        high5d = int(e.get("high_5d_price", 0) or 0)
        e["high_5d"] = high5d
        avg5d_eok = avg5d_million // 100
        if min_avg_amt_eok > 0 and avg5d_eok < min_avg_amt_eok:
            continue
        e["market_type"] = _get_mkt(cd) or ""
        e["nxt_enable"] = _is_nxt(cd)
        merged[cd] = e
        valid_codes.append(cd)

    # 업종 배치 조회: 1353회 개별 await → 1회 배치 호출
    sectors_map = await get_merged_sectors_batch(valid_codes)
    for cd in valid_codes:
        merged[cd]["sector"] = sectors_map.get(cd, "미분류")

    # 업종 분석 순위 기준 정렬
    sector_order: dict[str, int] = {}
    import backend.app.services.engine_service as _es_ref2
    ss = _es_ref2._sector_summary_cache
    if ss:
        for sc in ss.sectors:
            sector_order[sc.sector] = sc.rank

    result = list(merged.values())
    result.sort(key=lambda r: sector_order.get(r.get("sector", ""), 9999))

    return result


async def get_buy_targets_sector_stocks() -> list:
    """매수후보 테이블용 — _sector_summary_cache.buy_targets + blocked_targets 반환 (guard_pass 필드 포함)."""
    import backend.app.services.engine_service as _es_ref
    from backend.app.services.engine_state import state
    ss = _es_ref._sector_summary_cache
    if not ss:
        return []

    # buy_targets와 blocked_targets 통합 (단일 소스 진리: _sector_summary_cache)
    result = []

    # buy_targets (guard_pass=True)
    for bt in ss.buy_targets:
        s = bt.stock
        # master_stocks_cache에서 실시간 데이터 병합
        cache_entry = state.master_stocks_cache.get(s.code, {})
        result.append({
            "code": s.code,
            "name": s.name,
            "cur_price": cache_entry.get("cur_price"),
            "change_rate": cache_entry.get("change_rate"),
            "change": cache_entry.get("change"),
            "strength": cache_entry.get("strength"),
            "trade_amount": cache_entry.get("trade_amount"),
            "avg_amt_5d": s.avg_amt_5d,
            "market_type": s.market_type,
            "nxt_enable": s.nxt_enable,
            "sector": s.sector,
            "rank": bt.rank,
            "guard_pass": s.guard_pass,
            "reason": bt.reason,
            "boost_score": s.boost_score,
            "high_5d": int(cache_entry.get("high_5d_price", 0) or 0),
            "order_ratio": cache_entry.get("order_ratio"),
            "program_net_buy": cache_entry.get("program_net_buy"),
        })

    # blocked_targets (guard_pass=False)
    for bt in ss.blocked_targets:
        s = bt.stock
        # master_stocks_cache에서 실시간 데이터 병합
        cache_entry = state.master_stocks_cache.get(s.code, {})
        result.append({
            "code": s.code,
            "name": s.name,
            "cur_price": cache_entry.get("cur_price"),
            "change_rate": cache_entry.get("change_rate"),
            "change": cache_entry.get("change"),
            "strength": cache_entry.get("strength"),
            "trade_amount": cache_entry.get("trade_amount"),
            "avg_amt_5d": s.avg_amt_5d,
            "market_type": s.market_type,
            "nxt_enable": s.nxt_enable,
            "sector": s.sector,
            "rank": bt.rank,
            "guard_pass": s.guard_pass,
            "reason": bt.reason,
            "boost_score": s.boost_score,
            "high_5d": int(cache_entry.get("high_5d_price", 0) or 0),
            "order_ratio": cache_entry.get("order_ratio"),
            "program_net_buy": cache_entry.get("program_net_buy"),
        })

    return result


async def get_all_sector_stocks() -> list[dict]:
    """전체 종목(매매부적격 제외) — 업종분류 커스텀 페이지 전용.

    각 종목: { code, name, sector(get_merged_sector 기반), market_type, nxt_enable }
    """
    from backend.app.core.sector_mapping import get_merged_sectors_batch
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.services.engine_state import state

    # 단일 소스 진리: state.master_stocks_cache만 사용 (실시간 구독 상태와 분리)

    all_stocks = state.master_stocks_cache.copy()
    valid_codes: list[str] = []
    for cd, entry in all_stocks.items():
        if entry.get("status") != "active":
            continue
        valid_codes.append(cd)

    # 업종 배치 조회: N회 개별 await → 1회 배치 호출
    sectors_map = await get_merged_sectors_batch(valid_codes)

    result: list[dict] = []
    for cd in valid_codes:
        entry = all_stocks[cd]
        result.append({
            "code": cd,
            "name": entry.get("name", ""),
            "sector": sectors_map.get(cd, "미분류"),
            "market_type": _get_mkt(cd) or "",
            "nxt_enable": _is_nxt(cd),
        })
    return result


def get_sector_scores_snapshot() -> tuple[list[dict], int]:
    """업종 분석 순위 스냅샷 반환 — UI 업종분석 카드용.
    
    Returns: (scores_list, ranked_sectors_count)
    - scores_list: 전체 업종 목록 (rank=0 포함)
    - ranked_sectors_count: 순위 있는 업종 수 (rank > 0)
    """
    # 로컬 바인딩(_sector_summary_cache)은 engine_state import 시점에 고정되어 업데이트 안 됨
    # engine_service._sector_summary_cache가 engine_sector_confirm이 업데이트하는 단일 소스
    import backend.app.services.engine_service as _es_ref
    ss = _es_ref._sector_summary_cache
    if not ss:
        return [], 0
    out: list[dict] = []
    ranked_count = 0
    for sc in ss.sectors:
        out.append({
            "rank": sc.rank,
            "sector": sc.sector,
            "final_score": round(sc.final_score, 1),
            "total_trade_amount": sc.scored_trade_amount,  # 평균 거래대금 (가중치 계산 기반과 일관성 유지)
            "rise_ratio": round(sc.rise_ratio * 100, 1),
            "total": sc.total,
        })
        if sc.rank > 0:
            ranked_count += 1
    return out, ranked_count


async def recompute_sector_summary_now() -> None:
    """설정 변경 시 즉시 _sector_summary_cache 재계산 (10초 루프 대기 없이).

    매수 시도는 실시간 틱 기반 업종순위 증분 업데이트(_incremental_recompute)에서 수행됨.
    """
    from backend.app.services.engine_state import state
    from backend.app.core.logger import get_logger
    logger = get_logger("engine_sector")
    from backend.app.domain.sector_calculator import compute_full_sector_summary
    from backend.app.domain.buy_filter import build_buy_targets_from_settings
    from backend.app.services.engine_sector_confirm import cancel_sector_recompute
    from backend.app.services.engine_lifecycle import is_engine_running
    from backend.app.services.engine_account_notify import notify_desktop_sector_scores, notify_buy_targets_update, notify_desktop_sector_stocks_refresh
    import backend.app.services.engine_service as _es

    logger.info("[업종순위] recompute_sector_summary_now 진입, is_running=%s", is_engine_running())
    if not is_engine_running():
        logger.info("[업종순위] 엔진 미실행으로 종료")
        return
    try:
        trim_trade = float(_es._integrated_system_settings_cache["sector_trim_trade_amt_pct"])
        trim_change = float(_es._integrated_system_settings_cache["sector_trim_change_rate_pct"])
        sector_weights = _es._integrated_system_settings_cache["sector_weights"]
        logger.info("[업종순위] 재계산 sector_weights: %s", sector_weights)
        _inputs = await get_sector_summary_inputs()
        _sector_summary = await compute_full_sector_summary(
            **_inputs,
            min_rise_ratio=float(_es._integrated_system_settings_cache["sector_min_rise_ratio_pct"]) / 100.0,
            min_avg_amt_eok=float(_es._integrated_system_settings_cache["sector_min_trade_amt"]),
            sector_weights=_es._integrated_system_settings_cache["sector_weights"],
            trim_trade_amt_pct=trim_trade,
            trim_change_rate_pct=trim_change,
        )
        _ss = build_buy_targets_from_settings(
            _sector_summary.sectors,
            _es._integrated_system_settings_cache,
        )
        _es._sector_summary_cache = _ss
        cancel_sector_recompute()

        # ── 5일평균최소거래대금(N억원) 이상 종목 마킹 ──
        # get_sector_stocks()에서 이미 필터링된 all_codes 재사용 — 불필요한 .copy() 및 재순회 제거
        _filtered_codes = set(_inputs["all_codes"])
        for cd, entry in state.master_stocks_cache.items():
            if cd in _filtered_codes:
                entry["_filtered"] = True
            else:
                entry.pop("_filtered", None)

        notify_desktop_sector_scores(force=True)
        await notify_desktop_sector_stocks_refresh(force=True)
        await notify_buy_targets_update()
        logger.info("[업종순위] 재계산 완료")
        _es._sector_summary_ready_event.set()
    except Exception as e:
        logger.warning("[업종순위] 재계산 실패: %s", e, exc_info=True)
        _es._sector_summary_ready_event.set()


async def _on_filter_settings_changed() -> None:
    """필터 설정 변경 시 업종순위 재계산 + WS 전송."""
    from backend.app.core.logger import get_logger
    logger = get_logger("engine_sector")
    from backend.app.services.engine_account_notify import (
        notify_desktop_sector_stocks_refresh,
        notify_desktop_sector_scores,
        notify_buy_targets_update,
    )

    # ── 업종순위 + 매수후보 재계산 ──
    try:
        await recompute_sector_summary_now()
    except Exception as e:
        logger.warning("[시작][필터변경] 업종순위 재계산 실패: %s", e, exc_info=True)

    # ── WS 3종 전송 ──
    try:
        await notify_desktop_sector_stocks_refresh()
    except Exception:
        logger.warning("[데이터] 업종목록 화면전송 실패", exc_info=True)
    try:
        notify_desktop_sector_scores(force=True)
    except Exception:
        logger.warning("[데이터] 업종점수 화면전송 실패", exc_info=True)
    try:
        await notify_buy_targets_update()
    except Exception:
        logger.warning("[데이터] 매수후보 화면전송 실패", exc_info=True)
