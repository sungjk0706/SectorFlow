# -*- coding: utf-8 -*-
"""
업종/섹터 관련 모듈
- 업종 점수 계산
- 업종 종목 관리
- 필터 설정 관리
"""
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import (
    # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음
    # _radar_cnsr_order 삭제: _master_stocks_cache의 "_subscribed" 사용
    # _sector_stocks_cache 제거
    # _sector_stocks_dirty 제거
    _integrated_system_settings_cache,
    # _sector_stock_layout 제거: _integrated_system_settings_cache["sector_stock_layout"]로 통합
    # _buy_targets_snapshot_cache 제거: _sector_summary_cache.buy_targets와 중복
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_latest_trade_prices, _latest_trade_amounts, _latest_strength)
)
from backend.app.services.engine_ws import _ws_send_reg_unreg_and_wait_ack

logger = get_logger("engine_sector")


# ── 업종/섹터 관련 ─────────────────────────────────────────────────

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
            "total_trade_amount": sc.total_trade_amount,
            "rise_ratio": round(sc.rise_ratio * 100, 1),
            "total": sc.total,
        })
        if sc.rank > 0:
            ranked_count += 1
    return out, ranked_count


async def recompute_sector_summary_now() -> None:
    """설정 변경 시 즉시 _sector_summary_cache 재계산 (10초 루프 대기 없이)."""
    from backend.app.services.engine_sector_score import compute_full_sector_summary
    from backend.app.services.engine_sector_confirm import cancel_pending_recompute
    from backend.app.services.engine_lifecycle import is_running
    from backend.app.services.engine_account_notify import notify_desktop_sector_scores
    import backend.app.services.engine_service as _es

    logger.info("[업종순위] recompute_sector_summary_now 진입, is_running=%s", is_running())
    if not is_running():
        logger.info("[업종순위] 엔진 미실행으로 종료")
        return
    try:
        trim_trade = float(_es._integrated_system_settings_cache.get("sector_trim_trade_amt_pct", 0) or 0)
        trim_change = float(_es._integrated_system_settings_cache.get("sector_trim_change_rate_pct", 0) or 0)
        sector_weights = _es._integrated_system_settings_cache.get("sector_weights") or {}
        logger.info("[업종순위] 재계산 sector_weights: %s", sector_weights)
        _ss = await compute_full_sector_summary(
            **get_sector_summary_inputs(),
            sort_keys=_es._integrated_system_settings_cache.get("sector_sort_keys") or None,
            min_rise_ratio=float(_es._integrated_system_settings_cache.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
            block_rise_pct=float(_es._integrated_system_settings_cache.get("buy_block_rise_pct", 7.0)),
            block_fall_pct=float(_es._integrated_system_settings_cache.get("buy_block_fall_pct", 7.0)),
            min_strength=float(_es._integrated_system_settings_cache.get("buy_min_strength", 0)),
            min_avg_amt_eok=float(_es._integrated_system_settings_cache.get("sector_min_trade_amt", 0.0)),
            max_sectors=int(_es._integrated_system_settings_cache.get("sector_max_targets", 3)),
            sector_weights=_es._integrated_system_settings_cache.get("sector_weights") or {},
            trim_trade_amt_pct=trim_trade,
            trim_change_rate_pct=trim_change,
        )
        _es._sector_summary_cache = _ss
        cancel_pending_recompute()
        # _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음
        notify_desktop_sector_scores(force=True)
        logger.info("[업종순위] 재계산 완료")
    except Exception as e:
        logger.warning("[업종순위] 재계산 실패: %s", e, exc_info=True)


def get_sector_summary_inputs() -> dict:
    """업종 요약 계산 입력 데이터 반환."""
    # _radar_cnsr_order 삭제: _master_stocks_cache의 "_subscribed" 사용
    from backend.app.services.engine_state import _master_stocks_cache
    stock_details = {}
    # _master_stocks_cache의 모든 종목 사용 (실시간 구독 의존성 제거)
    for cd, entry in _master_stocks_cache.items():
        stock = entry.copy()
        stock["status"] = "active"
        stock_details[cd] = stock
    # _avg_amt_5d 제거: _master_stocks_cache에서 직접 추출
    # 단일 소스 진리: _master_stocks_cache에 이미 억 단위로 저장됨
    avg_amt_5d = {cd: int(entry.get("avg_5d_trade_amount", 0) or 0) for cd, entry in _master_stocks_cache.items()}
    return {
        "all_codes": list(_master_stocks_cache.keys()),
        "trade_prices": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "trade_amounts": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "avg_amt_5d": avg_amt_5d,
        "strengths": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "stock_details": stock_details,
        "latest_index": {},
    }


async def get_sector_stocks() -> list:
    """업종별 종목 시세 테이블용 — _master_stocks_cache 기반 실시간 필터링/정렬."""
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.core.sector_mapping import get_merged_sector as _get_sector
    import backend.app.services.engine_service as _es_ref

    # eligible_stocks_cache 제거: master_stocks_table이 단일 소스
    # sector_min_trade_amt 필터링은 _master_stocks_cache의 avg_5d_trade_amount로 수행

    # 5일평균거래대금 필터링 (백엔드에서 필터링 수행 - 단일 소스 진리)
    min_avg_amt_eok = float(_es_ref._integrated_system_settings_cache.get("sector_min_trade_amt", 0.0))

    merged: dict[str, dict] = {}
    from backend.app.services.engine_state import _master_stocks_cache

    # 단일 소스 진리: _master_stocks_cache가 종목 데이터의 단일 소스
    # _filtered_sector_codes 제거: sector_stock_layout 의존성 제거
    for cd in _master_stocks_cache.keys():
        if cd not in _master_stocks_cache:
            continue
        e = _master_stocks_cache[cd].copy()
        e["code"] = cd  # master_stocks_cache는 code를 KEY로만 보유 -- 값 dict에 명시 (프론트 stocksToMap/delta 식별용)
        e["status"] = "active"
        # 시세 없는 빈 엔트리 제외
        if int(e.get("cur_price") or 0) <= 0 and (not e.get("name") or e.get("name") == cd):
            continue
        # 정적 보강 필드
        # 단일 소스 진리: avg_5d_trade_amount는 백만원 단위, 필터링 시 억 단위 변환
        avg5d_million = int(e.get("avg_5d_trade_amount", 0) or 0)
        e["avg_amt_5d"] = avg5d_million // 100  # 백만원 → 억단위 변환
        # 5일평균거래대금 필터링 (백엔드에서 필터링 수행)
        if min_avg_amt_eok > 0 and e["avg_amt_5d"] < min_avg_amt_eok:
            continue
        e["market_type"] = _get_mkt(cd) or ""
        e["nxt_enable"] = _is_nxt(cd)
        e["sector"] = await _get_sector(cd)
        merged[cd] = e

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


async def get_all_sector_stocks() -> list[dict]:
    """전체 종목(매매부적격 제외) — 업종분류 커스텀 페이지 전용.

    각 종목: { code, name, sector(get_merged_sector 기반), market_type, nxt_enable }
    """
    from backend.app.core.sector_mapping import get_merged_sector
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.db.stock_tables import load_stock_name_cache
    from backend.app.services.engine_state import _master_stocks_cache

    # 단일 소스 진리: _master_stocks_cache만 사용 (실시간 구독 상태와 분리)
    name_map = await load_stock_name_cache() or {}

    result: list[dict] = []
    for cd, entry in _master_stocks_cache.items():
        if entry.get("status") != "active":
            continue  # 매매부적격(관리종목, 거래정지, exited 등) 제외
        try:
            sector = await get_merged_sector(cd)
        except Exception:
            logger.warning("[데이터] 종목 %s 섹터 분류 실패", cd, exc_info=True)
            sector = ""

        name = entry.get("name", "")
        if not name:
            name = name_map.get(cd.upper(), cd)

        result.append({
            "code": cd,
            "name": name,
            "sector": sector,
            "market_type": _get_mkt(cd) or "",
            "nxt_enable": _is_nxt(cd),
        })
    return result


# _invalidate_sector_stocks_cache 제거: _sector_stocks_cache 삭제로 더 이상 필요 없음


# get_all_sector_stocks_from_cache 삭제 (master_stocks_table로 대체)


async def _on_filter_settings_changed() -> None:
    """필터 설정 변경 시 업종순위 재계산 + WS 전송.

    sector_stock_layout 의존성 제거: 단일 소스(_master_stocks_cache) 기반 필터링
    """
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
        notify_buy_targets_update()
    except Exception:
        logger.warning("[데이터] 매수후보 화면전송 실패", exc_info=True)


# _compute_filtered_codes() 삭제: sector_stock_layout 의존성 제거
# _filtered_sector_codes 전역 변수 삭제: 단일 소스(_master_stocks_cache) 기반 필터링
