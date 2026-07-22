# -*- coding: utf-8 -*-
"""
업종 데이터 제공자 - 업종 요약 계산 관련 함수

단일 소스 진리 원칙: master_stocks_cache 직접 접근
"""
import logging
from backend.app.services import engine_state

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 업종 요약 계산 관련 함수
# ──────────────────────────────────────────────────────────────────────────────

async def get_sector_summary_inputs() -> dict:
    """업종 요약 계산 입력 데이터 반환.

    단일 소스 진리: master_stocks_cache를 직접 참조하므로 스냅샷 제거.
    NXT-only 구간(08:00~08:50, 15:40~20:00) 거래일에는 NXT-enabled 종목만 포함.
    정규장(09:00~15:20)에는 전체 종목 포함.

    KRX/NXT 분리 (P10 SSOT — nxt_enable 필드 기반, P23 일관성 — sector-stock.ts 카운트와 동일 기준):
    - krx_codes: KRX 단독 상장 종목 (nxt_enable=False)
    - nxt_codes: NXT 중복상장 종목 (nxt_enable=True)
    - all_codes: krx_codes + nxt_codes (업종 점수 계산용 — NXT-only 구간에는 NXT 종목만 포함)
    - all_filter_codes: NXT 필터링 전 전체 종목 (구독 대상 식별용 — NXT-only 구간에도 KRX 종목 포함)
    """
    from backend.app.services.engine_symbol_utils import is_nxt_enabled as _is_nxt
    from backend.app.services.daily_time_scheduler import is_nxt_only_window

    # 우측테이블의 종목들을 그대로 사용 (단일 소스 진리)
    # get_sector_stocks는 이미 5일평균거래대금 필터링된 종목들만 반환
    sector_stocks_list = await get_sector_stocks()

    # all_filter_codes: NXT 필터링 전 전체 종목 — 구독 대상 식별용 (P10 SSOT)
    # NXT-only 구간에서도 KRX 단독 종목이 구독 대상에서 누락되지 않도록 필터링 전 리스트 보존
    all_filter_codes = [entry["code"] for entry in sector_stocks_list]

    # NXT-only 구간(08:00~09:00, 15:30~20:00) 거래일: NXT-enabled 종목만 포함
    # KRX 단독 종목은 틱 수신 불가하므로 업종 점수 및 수신율에서 제외
    if is_nxt_only_window():
        sector_stocks_list = [
            entry for entry in sector_stocks_list
            if _is_nxt(entry["code"])
        ]

    # KRX/NXT 분리 — nxt_enable 필드 기반 (P10 SSOT, P23 일관성)
    krx_codes = [entry["code"] for entry in sector_stocks_list if not _is_nxt(entry["code"])]
    nxt_codes = [entry["code"] for entry in sector_stocks_list if _is_nxt(entry["code"])]
    all_codes = krx_codes + nxt_codes

    # 필터링된 종목만 avg_amt_5d 추출
    avg_amt_5d = {entry["code"]: int(entry.get("avg_amt_5d", 0) or 0)
                  for entry in sector_stocks_list}

    return {
        "all_codes": all_codes,  # 업종 점수 계산용 (NXT-only 구간에는 NXT 종목만)
        "all_filter_codes": all_filter_codes,  # 구독 대상 식별용 (NXT 필터링 전 전체)
        "krx_codes": krx_codes,  # KRX 단독 상장 종목 (수신률 분리 집계용)
        "nxt_codes": nxt_codes,  # NXT 중복상장 종목 (수신률 분리 집계용)
        "trade_prices": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "trade_amounts": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "avg_amt_5d": avg_amt_5d,
    }


async def get_sector_stocks() -> list:
    """업종별 종목 시세 테이블용 — _master_stocks_cache 기반 실시간 필터링/정렬."""
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.core.sector_mapping import get_merged_sectors_batch

    # 5일평균거래대금 필터링 (백엔드에서 필터링 수행 - 단일 소스 진리)
    min_avg_amt_eok = float(engine_state.state.integrated_system_settings_cache["sector_min_trade_amt"])

    merged: dict[str, dict] = {}

    # 단일 소스 진리: state.master_stocks_cache가 종목 데이터의 단일 소스

    # 1차 필터링: 시세/이름 없는 엔트리 제거 + 5일평균거래대금 필터링
    valid_codes: list[str] = []
    for cd in engine_state.state.master_stocks_cache:
        e = engine_state.state.master_stocks_cache.get(cd, {}).copy()
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
    ss = engine_state.state.sector_summary_cache
    if ss:
        for sc in ss.sectors:
            sector_order[sc.sector] = sc.rank

    result = list(merged.values())
    result.sort(key=lambda r: sector_order.get(r.get("sector", ""), 9999))

    return result


async def get_buy_targets_sector_stocks() -> list:
    """매수 후보 테이블용 — _sector_summary_cache.buy_targets + blocked_targets 반환 (guard_pass 필드 포함)."""
    ss = engine_state.state.sector_summary_cache
    if not ss:
        return []

    # buy_targets와 blocked_targets 통합 (단일 소스 진리: _sector_summary_cache)
    result = [_build_target_entry(bt) for bt in ss.buy_targets]
    result.extend(_build_target_entry(bt) for bt in ss.blocked_targets)
    return result


def _build_target_entry(bt) -> dict:
    """매수 후보/차단 후보 공통 엔트리 생성 — master_stocks_cache 실시간 데이터 병합."""
    s = bt.stock
    cache_entry = engine_state.state.master_stocks_cache.get(s.code, {})
    return {
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
        "trade_amount_rank": s.trade_amount_rank,
        "high_5d": int(cache_entry.get("high_5d_price", 0) or 0),
        "order_ratio": cache_entry.get("order_ratio"),
        "program_net_buy": cache_entry.get("program_net_buy"),
    }


async def get_all_sector_stocks() -> list[dict]:
    """전체 종목(매매부적격 제외) — 업종분류 커스텀 페이지 전용.

    각 종목: { code, name, sector(get_merged_sector 기반), market_type, nxt_enable }
    """
    from backend.app.core.sector_mapping import get_merged_sectors_batch
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt

    # 단일 소스 진리: state.master_stocks_cache만 사용 (실시간 구독 상태와 분리)

    valid_codes: list[str] = []
    for cd, entry in engine_state.state.master_stocks_cache.items():
        if entry.get("status") != "active":
            continue
        valid_codes.append(cd)

    # 업종 배치 조회: N회 개별 await → 1회 배치 호출
    sectors_map = await get_merged_sectors_batch(valid_codes)

    result: list[dict] = []
    for cd in valid_codes:
        entry = engine_state.state.master_stocks_cache[cd]
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
    - scores_list: 전체 업종 목록 (모든 업종에 순위 부여, is_cutoff_passed 포함)
    - ranked_sectors_count: 컷오프 통과 업종 수 (is_cutoff_passed=True)
    """
    ss = engine_state.state.sector_summary_cache
    if not ss:
        return [], 0
    out: list[dict] = []
    ranked_count = 0
    for sc in ss.sectors:
        out.append({
            "rank": sc.rank,
            "sector": sc.sector,
            "final_score": round(sc.final_score, 1),
            "bonus_rise_ratio": round(sc.bonus_rise_ratio, 1),
            "bonus_relative_strength": round(sc.bonus_relative_strength, 1),
            "bonus_trade_amount": round(sc.bonus_trade_amount, 1),
            "avg_trade_amount": sc.avg_trade_amount,
            "rise_ratio": round(sc.rise_ratio * 100, 1),
            "total": sc.total,
            "is_cutoff_passed": sc.is_cutoff_passed,
        })
        if sc.is_cutoff_passed:
            ranked_count += 1
    return out, ranked_count


async def recompute_sector_summary_now() -> None:
    """설정 변경 시 즉시 _sector_summary_cache 재계산 (10초 루프 대기 없이).

    매수 시도는 실시간 틱 기반 업종순위 증분 업데이트(_incremental_recompute)에서 수행됨.
    """
    from backend.app.domain.sector_calculator import compute_full_sector_summary
    from backend.app.domain.buy_filter import build_buy_targets_from_settings
    from backend.app.services.engine_sector_confirm import cancel_sector_recompute
    from backend.app.services.engine_lifecycle import is_engine_running
    from backend.app.services.engine_account_notify import notify_desktop_sector_scores, notify_buy_targets_update, notify_desktop_sector_stocks_refresh

    logger.info("[업종] 업종순위 재계산 진입, 실행중=%s", is_engine_running())
    if not is_engine_running():
        logger.info("[업종] 엔진 미실행으로 종료")
        return
    try:
        logger.info("[업종] 업종순위 재계산 (3단계 누적 가산점)")
        _inputs = await get_sector_summary_inputs()
        # krx_codes/nxt_codes는 수신률 분리 집계 전용, all_filter_codes는 구독 대상 식별 전용
        # — compute_full_sector_summary에는 all_codes만 전달
        _compute_inputs = {k: v for k, v in _inputs.items() if k not in ("krx_codes", "nxt_codes", "all_filter_codes")}
        _sector_summary = await compute_full_sector_summary(
            **_compute_inputs,
            min_rise_ratio=float(engine_state.state.integrated_system_settings_cache["sector_min_rise_ratio_pct"]) / 100.0,
            min_avg_amt_eok=float(engine_state.state.integrated_system_settings_cache["sector_min_trade_amt"]),
            rise_ratio_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_rise_ratio_slider"]),
            relative_strength_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_relative_strength_slider"]),
            trade_amount_slider=int(engine_state.state.integrated_system_settings_cache["sector_bonus_trade_amount_slider"]),
        )
        from backend.app.services import engine_account
        _held = await engine_account.get_held_codes()
        _bought_today: set[str] = set()
        if engine_state.state.auto_trade is not None:
            _bought_today = set(engine_state.state.auto_trade._bought_today.keys())
        _ss = build_buy_targets_from_settings(
            _sector_summary.sectors,
            engine_state.state.integrated_system_settings_cache,
            held_codes=_held,
            bought_today_codes=_bought_today,
        )
        engine_state.state.sector_summary_cache = _ss
        cancel_sector_recompute()

        # ── 5일평균최소거래대금(N억원) 이상 종목 마킹 ──
        # all_filter_codes(NXT 필터링 전 전체) 사용 — NXT-only 구간에도 KRX 종목 _filtered 플래그 유지
        _filtered_codes = set(_inputs["all_filter_codes"])
        for cd, entry in engine_state.state.master_stocks_cache.items():
            if cd in _filtered_codes:
                entry["_filtered"] = True
            else:
                entry.pop("_filtered", None)

        await notify_desktop_sector_scores(force=True)
        await notify_desktop_sector_stocks_refresh(force=True)
        await notify_buy_targets_update()
        logger.info("[업종] 재계산 완료")
        engine_state.state.sector_summary_ready_event.set()
    except Exception as e:
        logger.warning("[업종] 재계산 실패: %s", e, exc_info=True)
        engine_state.state.sector_summary_ready_event.set()


async def _on_filter_settings_changed() -> None:
    """필터 설정 변경 시 업종순위 재계산 + 실시간 통신 전송.

    recompute_sector_summary_now() 내부에서 알림 3종 및 예외 처리가 이미 수행되므로
    중복 try/except를 제거한다.
    """
    await recompute_sector_summary_now()
