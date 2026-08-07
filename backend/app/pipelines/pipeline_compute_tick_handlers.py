"""
Compute Engine 틱 핸들러 — pipeline_compute.py에서 분리 (P24 단순성).

본 모듈은 틱 타입별 leaf 핸들러와 배치 코얼레싱을 담당.
상태(state)·수신 세트·플래그는 pipeline_compute 모듈의 전역을 참조하며,
테스트의 patch("...pipeline_compute.state") 경로가 유효하도록
지연 import로 pipeline_compute 모듈 속성을 읽는다.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


# ── 배치 코얼레싱 ────────────────────────────────────────────────────────────

def _coalesce_real_items(
    items: list,
    latest_01_by_code: dict[str, dict],
) -> list[dict]:
    """REAL 이벤트 내 개별 아이템 코얼레싱 — 01 타입은 최신 1개만 유지, 나머지는 remaining.

    Args:
        items: 단일 REAL 이벤트의 data 아이템 리스트.
        latest_01_by_code: 종목코드별 최신 01 아이템을 누적하는 dict (in-place 갱신).
    Returns:
        remaining_items: 01이 아닌 아이템 + code 없는 01 아이템.
    """
    from backend.app.services.engine_ws_parsing import _normalize_real_type

    remaining_items: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        msg_type = item.get("type")
        norm_type = _normalize_real_type(msg_type)

        if norm_type == "01":
            code = str(item.get("code") or item.get("item") or "").strip()
            if code:
                latest_01_by_code[code] = item
            else:
                remaining_items.append(item)
        else:
            remaining_items.append(item)
    return remaining_items


def _coalesce_batch(batch: list) -> list:
    """배치 내 동일 종목 01 틱 코얼레싱 — 최신 데이터만 유지.

    01(체결) 타입 틱은 동일 종목코드에 대해 최신 1개만 처리.
    0d, 0j, PGM 등 다른 타입은 모두 유지.
    """
    _latest_01_by_code: dict[str, dict] = {}
    other_queue_items: list[dict] = []

    for queue_item in batch:
        if not isinstance(queue_item, dict):
            other_queue_items.append(queue_item)
            continue

        trnm = queue_item.get("trnm")
        if trnm != "REAL":
            other_queue_items.append(queue_item)
            continue

        real_data = queue_item.get("data")
        if isinstance(real_data, list):
            items = real_data
        elif isinstance(real_data, dict):
            items = [real_data]
        else:
            items = []

        remaining_items = _coalesce_real_items(items, _latest_01_by_code)
        if remaining_items:
            other_queue_items.append({"trnm": "REAL", "data": remaining_items})

    result = other_queue_items
    if _latest_01_by_code:
        result.append({"trnm": "REAL", "data": list(_latest_01_by_code.values())})

    return result


# ── REAL 틱 타입별 leaf 핸들러 ────────────────────────────────────────────────

async def _handle_real_0j_tick(item: dict, vals: dict) -> None:
    """0J 업종지수 틱 처리 — 저장 없이 즉시 화면에 전송."""
    try:
        upcode = str(item.get("item", "") or "").strip()
        if not upcode:
            return
        jisu = str(vals.get("10", "") or "").strip()
        change = str(vals.get("11", "") or "").strip()
        drate = str(vals.get("12", "") or "").strip()
        sign = str(vals.get("25", "") or "").strip()
        if not jisu:
            return
        from backend.app.services.engine_account_notify import notify_index_data
        await notify_index_data(upcode, jisu, change, drate, sign)
    except Exception as e:
        logger.error("[연산] 업종지수 틱(0J) 처리 오류: %s", e, exc_info=True)


def _apply_01_radar_and_receive_rate(
    raw_cd: str,
    nk_px: str,
    vals: dict,
    is_0b_tick: bool,
) -> None:
    """0B/01 틱 — 레이더 행 갱신 + 업종 점수 증분 재계산 트리거 + 수신 세트 추가.

    수신 세트/플래그는 pipeline_compute 모듈 전역을 갱신 (P10 SSOT).
    """
    if not (is_0b_tick and any(f in vals for f in ("10", "11", "12", "14", "17", "228"))):
        return
    from backend.app.services.engine_radar import (
        _apply_real01_volume_amount_to_radar_rows,
    )
    _apply_real01_volume_amount_to_radar_rows(raw_cd, vals, is_0b_tick=is_0b_tick)
    if not nk_px:
        return
    import backend.app.pipelines.pipeline_compute as _pc
    from backend.app.services.engine_sector_confirm import request_sector_recompute
    from backend.app.services.engine_symbol_utils import is_nxt_enabled
    request_sector_recompute(nk_px)
    # KRX/NXT 분리 수신 세트 추가 (P10 SSOT — nxt_enable 필드 기반, P23 일관성)
    if is_nxt_enabled(nk_px):
        _pc._received_codes_nxt.add(nk_px)
    else:
        _pc._received_codes_krx.add(nk_px)
    _pc._receive_rate_dirty = True
    _pc._receive_rate_event.set()


async def _apply_01_price_to_positions(
    nk_px: str,
    raw_cd: str,
    last_px: int,
    diff,
    rate,
) -> bool:
    """보유종목 현재가 반영 — 평가손익·수익률 실시간 재계산.

    Returns: 보유종목 가격 갱신 발생 여부.
    """
    import backend.app.pipelines.pipeline_compute as _pc
    from backend.app.core.trade_mode import is_test_mode
    from backend.app.services import dry_run
    from backend.app.services.engine_account_rest import (
        apply_last_price_to_positions_inplace,
        recalc_broker_totals_from_positions,
    )

    state = _pc.state
    _price_hit = False
    if is_test_mode(state.integrated_system_settings_cache):
        _price_hit = await dry_run.update_price(nk_px, last_px)
        if _price_hit:
            _dr_pos = await dry_run.get_position(nk_px)
            if _dr_pos:
                _dr_pos["change"] = diff
                _dr_pos["change_rate"] = rate
    else:
        _price_hit = apply_last_price_to_positions_inplace(state.positions, raw_cd, last_px)
        if _price_hit:
            state.broker_rest_totals = recalc_broker_totals_from_positions(
                state.positions, state.broker_rest_totals
            )
    return _price_hit


async def _handle_real_01_tick(
    item: dict,
    vals: dict,
    broadcast_queue: asyncio.Queue,
) -> bool:
    """
    0B/01 체결 틱 처리.

    Returns: 보유종목 가격 갱신 발생 여부 (계좌 전송 필요 시 True).
    """
    _price_hit = False
    _ts = int(time.time() * 1000)
    try:
        from backend.app.services.engine_symbol_utils import (
            _base_stk_cd,
            _real_item_stk_cd,
        )
        from backend.app.services.engine_ws_dispatch import _check_realtime_latency
        from backend.app.services.engine_ws_parsing import (
            _parse_fid10_price,
            _ws_fid_int,
            _ws_fid_raw,
            parse_change_rate_to_percent,
        )

        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return False

        nk_px = _base_stk_cd(raw_cd)
        last_px = _parse_fid10_price(vals)
        is_0b_tick = str(item.get("type", "")).strip().upper() in ("0B", "01")

        if not nk_px or last_px <= 0:
            _check_realtime_latency(_ts)
            return False

        # ── 1. 화면으로 실시간 틱 데이터 전송 ──
        item["item"] = raw_cd
        item["_ts"] = _ts
        try:
            broadcast_queue.put_nowait({"type": "real-data", "data": item})
        except asyncio.QueueFull:
            logger.warning("[연산] 전송 큐 가득 참 — 화면 데이터 누락 (종목코드=%s)", raw_cd)

        # ── 2. 레이더 행 갱신 + 업종 점수 증분 재계산 트리거 ──
        _apply_01_radar_and_receive_rate(raw_cd, nk_px, vals, is_0b_tick)

        # ── 3. 보유종목 현재가 반영 — 평가손익·수익률 실시간 재계산 ──
        _raw11 = _ws_fid_raw(vals, "11")
        diff = _ws_fid_int(vals, "11") if _raw11 is not None and str(_raw11).strip() and str(_raw11).strip() != "-" else None
        _raw12 = _ws_fid_raw(vals, "12")
        rate = parse_change_rate_to_percent(_raw12) if _raw12 is not None and str(_raw12).strip() else None
        _price_hit = await _apply_01_price_to_positions(nk_px, raw_cd, last_px, diff, rate)

        # ── 4. 자동매도 조건 검사 요청 → 주문 실행 큐로 이동 (결정 3) ──
        # 시세 처리 루프가 매도 주문·가상 체결(0.5초)에 블록되지 않도록
        # 매도 조건 검사는 주문 실행 루프가 큐에서 꺼내 처리 (W1·W2)
        if _price_hit:
            from backend.app.services.core_queues import get_order_queue
            try:
                get_order_queue().put_nowait({"type": "sell_check", "codes": [nk_px]})
            except asyncio.QueueFull:
                # W1 무한 쌓기 방지 — 가득 시 경고 로그 + 드롭 (W8 폴백 금지, 명시적 드롭)
                logger.warning("[연산] 주문 큐 가득 참 — 매도 조건 검사 요청 드롭 (종목코드=%s)", nk_px)

        # ── 5. 지연 측정 ──
        _check_realtime_latency(_ts)

    except Exception as e:
        logger.error("[연산] 체결 틱(0B/01) 처리 오류: %s", e, exc_info=True)
    return _price_hit


async def _handle_real_0d_tick(
    item: dict,
    vals: dict,
    broadcast_queue: asyncio.Queue,
) -> None:
    """0D 호가 틱 처리 (호가 잔량 테이블)."""
    try:
        import backend.app.pipelines.pipeline_compute as _pc
        from backend.app.services.engine_account_notify import notify_orderbook_update
        from backend.app.services.engine_symbol_utils import (
            _base_stk_cd,
            _real_item_stk_cd,
        )
        from backend.app.services.engine_ws_parsing import _ws_fid_int

        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return

        nk = _base_stk_cd(raw_cd)
        bid = _ws_fid_int(vals, "125", 0)  # 총 매수호가잔량
        ask = _ws_fid_int(vals, "121", 0)  # 총 매도호가잔량

        if bid < 0 or ask < 0:
            return

        # 매수 후보 종목이면 호가잔량비 변경을 프론트에 즉시 전송
        cache = _pc.state.master_stocks_cache
        if nk not in cache:
            logger.warning("[연산] 호가 틱(0D) 수신 종목이 캐시에 없음 (종목=%s) — 비정상. 틱 스킵.", nk)
            return
        cache_entry = cache[nk]
        if cache_entry.get("_subscribed_dynamic", False):
            cache_entry["order_ratio"] = [bid, ask]
            await notify_orderbook_update(nk, bid, ask)

    except Exception as e:
        logger.error("[연산] 호가 틱(0D) 처리 오류: %s", e, exc_info=True)


async def _handle_real_pgm_tick(
    item: dict,
    vals: dict,
    broadcast_queue: asyncio.Queue,
) -> None:
    """PGM 프로그램 순매수 틱 처리."""
    try:
        import backend.app.pipelines.pipeline_compute as _pc
        from backend.app.services.engine_account_notify import notify_program_update
        from backend.app.services.engine_symbol_utils import (
            _base_stk_cd,
            _real_item_stk_cd,
        )

        raw_cd = _real_item_stk_cd(item, vals)
        if not raw_cd:
            return

        nk = _base_stk_cd(raw_cd)
        tval_str = vals.get("tval")
        if tval_str is None:
            logger.warning("[연산] PGM 순매수 데이터 누락 (tval 필드 없음, 종목=%s) — 틱 생략. 화면에 순매수 0이 잘못 표시되지 않도록 갱신을 생략합니다.", nk)
            return
        try:
            tval = int(tval_str)
        except (ValueError, TypeError):
            logger.warning("[연산] PGM 순매수 데이터 오류 (tval=%r, 종목=%s) — 틱 스킵. 화면에 순매수 0이 잘못 표시되지 않도록 갱신을 생략합니다.", tval_str, nk)
            return

        # 매수 후보 종목이면 프로그램 순매수 변경을 프론트에 즉시 전송
        cache = _pc.state.master_stocks_cache
        if nk not in cache:
            logger.warning("[연산] PGM 틱 수신 종목이 캐시에 없음 (종목=%s) — 비정상. 틱 스킵.", nk)
            return
        cache_entry = cache[nk]
        if cache_entry.get("_subscribed_dynamic", False):
            cache_entry["program_net_buy"] = tval
            await notify_program_update(nk, tval)

    except Exception as e:
        logger.error("[연산] 프로그램 순매수 틱(PGM) 처리 오류: %s", e, exc_info=True)


def _recompute_boost_scores_for_hits(ss, hit_codes: list[str], settings: dict) -> list[float]:
    """hit 종목의 boost_score 재계산 — news-hit payload용 (수정안 3, P10 SSOT).

    calculate_boost_score() 전체 재호출로 4개 가산점 정확 합산.
    master_stocks_cache[code]["news_boost"] 갱신 후 호출되므로 뉴스 가산점 포함.
    P7: hit_codes만 재계산 (단일 뉴스 매칭 수 = 소수), 매수후보 전체 순회 아님.
    P23: build_buy_targets_from_settings()와 동일한 캐시 조회·설정 매핑 패턴.
    """
    from backend.app.domain.buy_filter import calculate_boost_score
    from backend.app.services.engine_radar import (
        get_high_price_5d_cache,
        get_news_boost_cache,
        get_orderbook_cache,
        get_program_net_buy_cache,
    )
    high_5d = get_high_price_5d_cache()
    obc = get_orderbook_cache()
    pnb = get_program_net_buy_cache()
    nbc = get_news_boost_cache()
    hit_set = set(hit_codes)
    result: list[float] = []
    for bt in ss.buy_targets:
        if bt.stock.code in hit_set:
            new_bs = calculate_boost_score(
                bt.stock,
                high_5d_cache=high_5d,
                orderbook_cache=obc,
                program_net_buy_cache=pnb,
                boost_high_on=bool(settings.get("boost_high_breakout_on", False)),
                boost_high_score=float(settings.get("boost_high_breakout_score", 1.0)),
                boost_order_ratio_on=bool(settings.get("boost_order_ratio_on", False))
                    and bt.stock.guard_pass,
                boost_order_ratio_pct=float(settings.get("boost_order_ratio_pct", 20.0)),
                boost_order_ratio_score=float(settings.get("boost_order_ratio_score", 1.0)),
                boost_program_net_buy_on=bool(settings.get("boost_program_net_buy_on", False))
                    and bt.stock.guard_pass,
                boost_program_net_buy_score=float(settings.get("boost_program_net_buy_score", 1.0)),
                news_boost_cache=nbc,
                boost_news_on=True,  # A안: _handle_nws_news 진입 시 이미 boost_news_on=True 확인됨
                boost_news_score=float(settings.get("boost_news_score", 1.0)),
            )
            bt.stock.boost_score = new_bs
            result.append(new_bs)
    return result


async def _handle_nws_news(item: dict) -> None:
    """NWS 실시간 뉴스 처리 — 호재 키워드 매칭 시 master_stocks_cache[code] 갱신 (5분 TTL) + news-hit 브로드캐스트.

    JIF와 동일하게 tick_queue를 우회하여 engine_ws_dispatch → 본 핸들러 직접 호출 (P23).
    P7: 매 뉴스마다 매수후보 전체 순회 금지 — buy_target_codes set O(1) 조회.
    P10: news_boost 단일 전달 경로 = news-hit 이벤트 (buy-targets-delta에서는 제외).
        boost_score도 본 이벤트로 즉시 갱신 (10초 재계산 루프 대기 없이 실시간 반영).
        news_boost는 master_stocks_cache[code] 필드로 통합 (별도 캐시 제거).
    P13: 키워드 사전·boost_news_on 토글은 메모리 상주 (engine_state + integrated_system_settings_cache).
    P20: code 빈 뉴스는 폴백 없이 스킵 + debug 로깅. 종목명 부재 시 빈 문자열(명시적 값).
    P21: boost_news_on=False 시 감지 자체 수행 안 함 — 📰 안 뜸, 알림 안 옴, 가산점 안 더함 (3동작 완전 일치).
    P25: NWS 처리 실패가 다른 틱 처리 블로킹 금지. _safe_broadcast 실패 시에도 캐시 갱신·로그 정상 완료.
    """
    import time

    from backend.app.services import engine_state
    from backend.app.services.engine_symbol_utils import _base_stk_cd
    try:
        # A안: boost_news_on=False 시 뉴스 호재 감지 자체 수행 안 함 (P21 투명성 — 3동작 완전 일치)
        settings = engine_state.state.integrated_system_settings_cache
        if not bool(settings.get("boost_news_on", False)):
            return  # 토글 OFF: 📰 안 뜸, 알림 안 옴, 가산점 안 더함

        title = str(item.get("title", "")).strip()
        code_raw = str(item.get("code", "")).strip()
        if not title:
            return
        if not code_raw:
            logger.debug("[연산] 뉴스 제목 수신 (종목코드 없음, 생략): %s", title[:60])
            return

        # 복수 종목코드 파싱 (공백/쉼표 구분, 최대 240자)
        codes = [_base_stk_cd(c.strip()) for c in code_raw.replace(",", " ").split() if c.strip()]
        codes = [c for c in codes if c]
        if not codes:
            logger.debug("[연산] 뉴스 제목 수신 (유효 종목코드 없음, 생략): %s", title[:60])
            return

        # 호재 키워드 매칭 (메모리 상주 사전, P13)
        keywords = engine_state.state.news_keywords_cache
        if not keywords:
            return  # 키워드 미설정 시 가산점 부여 안 함 (P20 폴백 금지)
        matched_keywords = [kw for kw in keywords if kw in title]
        if not matched_keywords:
            return  # 호재 키워드 미포함 시 스킵 (자연스러운 경로, silent 아님)

        # 매수후보 테이블 내 종목만 가산점 부여 (수정안 1 — master_stocks_cache → buy_targets 기준)
        # P10/P21: 사용자 설계 의도("매수후보 테이블에 올라온 종목만 알림") 준수.
        # P7: buy_target_codes set 구축 후 O(1) 조회 (매수후보 수 = 소수, 매 뉴스마다 set 구축 비용 미미).
        ss = engine_state.state.sector_summary_cache
        if not ss:
            return  # 매수후보 미생성 시 가산점 부여 대상 없음
        buy_target_codes = {bt.stock.code for bt in ss.buy_targets}
        score = engine_state.state.news_boost_score
        now = time.monotonic()
        hit_codes = []
        master_cache = engine_state.state.master_stocks_cache
        for code in codes:
            if code in buy_target_codes:  # O(1) 조회 (P7)
                # P10 SSOT — news_boost를 master_stocks_cache 필드로 통합
                entry = master_cache.get(code)
                if entry is not None:
                    entry["news_boost"] = score
                    entry["news_boost_ts"] = now
                hit_codes.append(code)
        if hit_codes:
            logger.info("[연산] 뉴스 가산점 부여 — 종목=%s 키워드 매칭: %s", hit_codes, title[:60])
            # 수정안 3: hit 종목의 boost_score 즉시 재계산 (10초 루프 대기 없이 실시간 반영, P10 SSOT).
            # calculate_boost_score() 전체 재호출 — 4개 가산점 정확 합산, master_stocks_cache[code]["news_boost"]
            # 갱신 후이므로 뉴스 가산점 포함. hit 종목만 재계산 (P7 — hit_codes는 단일 뉴스 매칭 수, 소수).
            boost_scores = _recompute_boost_scores_for_hits(ss, hit_codes, settings)
            # news-hit WS 이벤트 브로드캐스트 — news_boost + boost_score 단일 전달 경로 (P10 SSOT).
            # buy-targets-delta에서는 news_boost 제외(세션 1)하고 본 이벤트로만 전달.
            # P7: 1회 O(len(hit_codes)). P25: _safe_broadcast 내부 예외 처리 — 전송 실패 시에도
            # 캐시 갱신·로그는 정상 완료(엔진 루프 블로킹 금지).
            # P20: 종목명 부재 시 빈 문자열(명시적 값, 폴백 아님).
            master_cache = engine_state.state.master_stocks_cache
            names = [master_cache.get(c, {}).get("name", "") for c in hit_codes]
            scores = [score for _ in hit_codes]
            from backend.app.services.engine_account_notify import _safe_broadcast
            await _safe_broadcast("news-hit", {
                "codes": hit_codes,
                "names": names,
                "scores": scores,
                "boost_scores": boost_scores,
                "title": title,
                "matched_keywords": matched_keywords,
            })

    except Exception as e:
        logger.error("[연산] 뉴스(NWS) 처리 오류: %s", e, exc_info=True)
