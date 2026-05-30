# -*- coding: utf-8 -*-
"""
업종/섹터 관련 모듈
- 업종 점수 계산
- 업종 종목 관리
- 필터 설정 관리
"""
from backend.app.core.logger import get_logger
from backend.app.services.engine_state import (
    _sector_summary_cache,
    _invalidate_sector_stocks_cache,
    _pending_stock_details,
    _filtered_sector_codes,
    _sector_stocks_cache,
    _sector_stocks_dirty,
    _subscribed_stocks,
    _settings_cache,
    _sector_stock_layout,
    _buy_targets_snapshot_cache,
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
    ss = _sector_summary_cache
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
    global _sector_summary_cache
    from backend.app.services.engine_sector_score import compute_full_sector_summary
    from backend.app.services.engine_sector_confirm import cancel_pending_recompute
    from backend.app.services.engine_config import _get_settings
    from backend.app.services.engine_lifecycle import is_running
    
    logger.info("[업종순위] recompute_sector_summary_now 진입, is_running=%s", is_running())
    if not is_running():
        logger.info("[업종순위] 엔진 미실행으로 종료")
        return
    try:
        settings = _get_settings()
        trim_trade = float(settings.get("sector_trim_trade_amt_pct", 0) or 0)
        trim_change = float(settings.get("sector_trim_change_rate_pct", 0) or 0)
        sector_weights = settings.get("sector_weights") or {}
        logger.info("[업종순위] 재계산 sector_weights: %s", sector_weights)
        _ss = await compute_full_sector_summary(
            **get_sector_summary_inputs(),
            sort_keys=settings.get("sector_sort_keys") or None,
            min_rise_ratio=float(settings.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
            block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
            block_fall_pct=float(settings.get("buy_block_fall_pct", 7.0)),
            min_strength=float(settings.get("buy_min_strength", 0)),
            min_avg_amt_eok=float(settings.get("sector_min_trade_amt", 0.0)),
            max_sectors=int(settings.get("sector_max_targets", 3)),
            sector_weights=settings.get("sector_weights") or {},
            trim_trade_amt_pct=trim_trade,
            trim_change_rate_pct=trim_change,
        )
        _sector_summary_cache = _ss
        cancel_pending_recompute()
        if _invalidate_sector_stocks_cache:
            _invalidate_sector_stocks_cache()
        logger.info("[업종순위] 재계산 완료")
    except Exception as e:
        logger.warning("[업종순위] 재계산 실패: %s", e, exc_info=True)


def get_sector_summary_inputs() -> dict:
    """업종 요약 계산 입력 데이터 반환."""
    return {
        "all_codes": list(_pending_stock_details.keys()),
        "trade_prices": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "trade_amounts": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "avg_amt_5d": _avg_amt_5d,
        "strengths": {},  # 실시간 틱 데이터 캐시 삭제로 빈 dict 반환
        "stock_details": dict(_pending_stock_details),
        "latest_index": {},
    }


async def get_sector_stocks() -> list:
    """업종별 종목 시세 테이블용 — 캐시 유효 시 참조 직접 반환, dirty 시 재구축."""
    global _sector_stocks_cache, _sector_stocks_dirty
    from backend.app.core.industry_map import load_eligible_stocks_cache_from_db
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.core.sector_mapping import get_merged_sector as _get_sector
    
    if not _sector_stocks_dirty and _sector_stocks_cache is not None:
        return _sector_stocks_cache

    # ── dirty: 캐시 재구축 (eligible_stocks_cache 기준 필터 + 정렬 1회) ──
    eligible_stocks = await load_eligible_stocks_cache_from_db() or {}
    filter_set = set(eligible_stocks.keys()) if eligible_stocks else None

    merged: dict[str, dict] = {}
    from backend.app.services.engine_state import _master_stocks_cache

    for cd, e in _pending_stock_details.items():
        if filter_set is not None and cd not in filter_set:
            continue
        if _filtered_sector_codes is not None and cd not in _filtered_sector_codes:
            continue
        if e.get("status") != "active":
            continue
        # 시세 없는 빈 엔트리 제외
        if int(e.get("cur_price") or 0) <= 0 and (not e.get("name") or e.get("name") == cd):
            continue
        # 정적 보강 필드를 원본 dict에 직접 패치 (참조 공유)
        avg5d_raw = int(_master_stocks_cache.get(cd, {}).get("avg_5d_trade_amount", 0) or 0)
        e["avg_amt_5d"] = avg5d_raw
        e["market_type"] = _get_mkt(cd) or ""
        e["nxt_enable"] = _is_nxt(cd)
        e["sector"] = await _get_sector(cd)
        merged[cd] = e

    # 업종 분석 순위 기준 정렬
    sector_order: dict[str, int] = {}
    ss = _sector_summary_cache
    if ss:
        for sc in ss.sectors:
            sector_order[sc.sector] = sc.rank

    result = list(merged.values())
    result.sort(key=lambda r: sector_order.get(r.get("sector", ""), 9999))

    _sector_stocks_cache = result
    _sector_stocks_dirty = False
    return result


async def get_all_sector_stocks() -> list[dict]:
    """전체 종목(매매부적격 제외) — 업종분류 커스텀 페이지 전용.

    각 종목: { code, name, sector(get_merged_sector 기반), market_type, nxt_enable }
    """
    from backend.app.core.sector_mapping import get_merged_sector
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.core.sector_stock_cache import load_stock_name_cache

    snapshot = dict(_pending_stock_details)
    name_map = await load_stock_name_cache() or {}

    result: list[dict] = []
    for cd, entry in snapshot.items():
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


def _invalidate_sector_stocks_cache(force: bool = False) -> None:
    """업종 종목 캐시 무효화."""
    global _sector_stocks_dirty, _buy_targets_snapshot_cache
    _sector_stocks_dirty = True
    _buy_targets_snapshot_cache = None  # 매수후보 캐시도 무효화


# get_all_sector_stocks_from_cache 삭제 (master_stocks_table로 대체)


async def _on_filter_settings_changed() -> None:
    """필터 설정 변경 시 diff 기반 증분 구독 갱신 + 업종순위 재계산 + WS 3종 전송.

    흐름:
    1. _compute_filtered_codes() → old/new diff (added, removed)
    2. old == new → 스킵 (WS 없음, WS 없음)
    3. WS 구독 구간 + quote 활성: REG added 먼저 → UNREG removed 나중에
    4. _subscribed_stocks 증분 갱신 (add/discard, clear 금지)
    5. recompute_sector_summary_now() → 업종순위 + 매수후보 재계산
    6. WS 3종: sector-stocks-refresh, sector-scores, buy-targets-update
    """
    from backend.app.services.daily_time_scheduler import is_ws_subscribe_window
    from backend.app.services import ws_subscribe_control
    from backend.app.services.engine_ws_reg import build_0b_reg_payloads, build_0b_remove_payloads
    from backend.app.services.engine_symbol_utils import get_ws_subscribe_code
    from backend.app.services.engine_account_notify import (
        notify_desktop_sector_stocks_refresh,
        notify_desktop_sector_scores,
        notify_buy_targets_update,
    )
    
    old_codes = _filtered_sector_codes.copy() if _filtered_sector_codes is not None else None
    new_codes = _compute_filtered_codes()

    logger.info(
        "[시작][필터변경] 이전=%d, 신규=%d, 변경없음=%s",
        len(old_codes or set()), len(new_codes or set()), old_codes == new_codes,
    )

    if old_codes == new_codes:
        return

    # === 설정 변경 시 강제 캐시 무효화 (1초 제한 무시) ===
    _invalidate_sector_stocks_cache(force=True)
    logger.info("[시작][필터변경] 캐시 강제 무효화 완료")
    # ==================================================
    
    added = (new_codes or set()) - (old_codes or set())
    removed = (old_codes or set()) - (new_codes or set())
    logger.info(
        "[시작][필터변경] 필터 통과 종목 변경 -- 추가 %d, 제거 %d (총 %d → %d)",
        len(added), len(removed), len(old_codes or set()), len(new_codes or set()),
    )

    # ── WS 구독 증분 갱신: 구독 구간 + quote 활성 상태에서만 ──
    if await is_ws_subscribe_window(_settings_cache) and ws_subscribe_control.get_subscribe_status()["quote_subscribed"]:
        # ── 1) REG added 먼저 (새 종목 실시간 데이터 즉시 수신) ──
        if added:
            reg_targets = [cd for cd in added if cd not in _subscribed_stocks]
            if reg_targets:
                for cd in reg_targets:
                    _subscribed_stocks.add(cd)
                reg_ws_codes = [get_ws_subscribe_code(cd) for cd in reg_targets]
                payloads = build_0b_reg_payloads(reg_ws_codes, reset_first=False)
                _CHUNK = 100
                ok_cnt = fail_cnt = 0
                for ci, payload in enumerate(payloads):
                    chunk = reg_targets[ci * _CHUNK : (ci + 1) * _CHUNK]
                    if _ws_send_reg_unreg_and_wait_ack:
                        ack_ok, _rc = await _ws_send_reg_unreg_and_wait_ack(payload)
                    else:
                        ack_ok = False
                    if ack_ok:
                        ok_cnt += len(chunk)
                    else:
                        fail_cnt += len(chunk)
                        for cd in chunk:
                            _subscribed_stocks.discard(cd)
                        logger.warning(
                            "[시작][필터변경] 구독등록 응답 시간 초과 (청크 %d) -- %d종목 구독 롤백",
                            ci + 1, len(chunk),
                        )
                logger.info(
                    "[시작][필터변경] 구독등록 완료 -- 추가 %d / 성공 %d / 실패 %d",
                    len(reg_targets), ok_cnt, fail_cnt,
                )

        # ── 2) UNREG removed 나중에 (기존 종목 해지) ──
        if removed:
            unreg_targets = [cd for cd in removed if cd in _subscribed_stocks]
            if unreg_targets:
                unreg_ws_codes = [get_ws_subscribe_code(cd) for cd in unreg_targets]
                payloads = build_0b_remove_payloads(unreg_ws_codes)
                _CHUNK = 100
                ok_cnt = fail_cnt = 0
                for ci, payload in enumerate(payloads):
                    chunk = unreg_targets[ci * _CHUNK : (ci + 1) * _CHUNK]
                    if _ws_send_reg_unreg_and_wait_ack:
                        ack_ok, _rc = await _ws_send_reg_unreg_and_wait_ack(payload)
                    else:
                        ack_ok = False
                    if ack_ok:
                        ok_cnt += len(chunk)
                        for cd in chunk:
                            _subscribed_stocks.discard(cd)
                    else:
                        fail_cnt += len(chunk)
                        logger.warning(
                            "[시작][필터변경] 구독해지 응답 시간 초과 (청크 %d) -- %d종목 (다음 변경 시 재시도)",
                            ci + 1, len(chunk),
                        )
                logger.info(
                    "[시작][필터변경] 구독해지 완료 -- 제거 %d / 성공 %d / 실패 %d",
                    len(unreg_targets), ok_cnt, fail_cnt,
                )
    elif not await is_ws_subscribe_window(_settings_cache):
        pass

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


def _compute_filtered_codes() -> set[str] | None:
    """sector_stock_layout에서 사용자 필터를 적용하여 조건 통과 종목 코드 집합을 반환."""
    global _filtered_sector_codes
    from backend.app.services.engine_symbol_utils import _format_broker_reg_stk_cd
    from backend.app.services.engine_config import _get_settings
    
    settings = _get_settings()

    # 설정값 검증 및 안전장치
    raw_val = settings.get("sector_min_trade_amt")
    try:
        min_amt_eok = float(raw_val) if raw_val is not None else 0.0
    except (TypeError, ValueError):
        logger.warning("[거래대금필터] 설정값 파싱 실패: %s", raw_val)
        min_amt_eok = 0.0
    min_amt_eok = max(0.0, min_amt_eok)

    codes = {
        _format_broker_reg_stk_cd(v)
        for t, v in _sector_stock_layout
        if t == "code" and v
    }
    codes.discard("")

    logger.info("[DEBUG-FILTER] _sector_stock_layout len: %d, codes len: %d", len(_sector_stock_layout), len(codes))

    if min_amt_eok <= 0:
        _filtered_sector_codes = None
        return None

    # 거래대금 캐시가 비어있으면 필터 비활성화
    from backend.app.services.engine_state import _master_stocks_cache
    if not _master_stocks_cache:
        logger.warning("[거래대금필터] master_stocks_cache 비어있음 - 필터 비활성화")
        _filtered_sector_codes = None
        return None

    filtered = set()
    for cd in codes:
        avg_eok = int(_master_stocks_cache.get(cd, {}).get("avg_5d_trade_amount", 0) or 0)
        if avg_eok >= min_amt_eok:
            filtered.add(cd)

    logger.info("[거래대금필터] 설정 %.0f억 → 필터 통과 %d/%d종목", min_amt_eok, len(filtered), len(codes))

    if not filtered:
        logger.warning("[거래대금필터] 최소금액 %.1f억 설정됐으나 통과 종목 0개", min_amt_eok)
    _filtered_sector_codes = filtered
    return filtered


def _update_avg_amt_5d(new_data: dict[str, int], *, merge: bool = False) -> None:
    """_master_stocks_cache의 avg_5d_trade_amount 갱신 후 필터 자동 재계산."""
    global _filtered_sector_codes
    from backend.app.services.engine_state import _master_stocks_cache
    
    normalized = {k: int(v or 0) for k, v in new_data.items() if v}
    for key, value in normalized.items():
        if key in _master_stocks_cache:
            _master_stocks_cache[key]["avg_5d_trade_amount"] = value
    _filtered_sector_codes = _compute_filtered_codes()
    if _invalidate_sector_stocks_cache:
        _invalidate_sector_stocks_cache()
    logger.info(
        "[5일평균] 갱신 완료 -- %d종목, 필터 통과 %s개",
        len(normalized),
        len(_filtered_sector_codes) if _filtered_sector_codes is not None else "전체",
    )
