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

async def get_sector_summary_inputs(codes: list[str] | None = None) -> dict:
    """업종 요약 계산 입력 데이터 반환.

    단일 소스 진리: master_stocks_cache를 직접 참조하므로 스냅샷 제거.
    NXT-only 구간(08:00~08:50, 15:40~20:00) 거래일에는 NXT-enabled 종목만 포함.
    정규장(09:00~15:20)에는 전체 종목 포함.

    ``codes``가 주어지면 해당 업종의 재계산 후보만 검사한다. 후보 자체에도
    동일한 1차 필터를 적용하므로 필터 미통과 종목이 업종 점수에 들어가지 않는다.
    전체 재계산에서만 master_stocks_cache 전체를 기준으로 후보를 만든다.

    KRX/NXT 분리 (P10 SSOT — nxt_enable 필드 기반, P23 일관성 — sector-stock.ts 카운트와 동일 기준):
    - krx_codes: KRX 단독 상장 종목 (nxt_enable=False)
    - nxt_codes: NXT 중복상장 종목 (nxt_enable=True)
    - all_codes: krx_codes + nxt_codes (업종 점수 계산용 — NXT-only 구간에는 NXT 종목만 포함)
    - all_filter_codes: NXT 필터링 전 전체 종목 (구독 대상 식별용 — NXT-only 구간에도 KRX 종목 포함)

    캐시 직접 읽기: 종목 코드와 avg_amt_5d(백만원)만 필요하므로 복사·필드명 변환·업종
    조회·정렬 없이 필터링한다. 증분 재계산은 전달받은 후보만 검사해 전체 종목 순회를 피한다.
    """
    from backend.app.services.engine_symbol_utils import is_nxt_enabled as _is_nxt
    from backend.app.services.daily_time_scheduler import is_nxt_only_window

    min_avg_amt_eok = float(engine_state.state.integrated_system_settings_cache["sector_min_trade_amt"])

    # 캐시에서 직접 필터링 — get_sector_stocks()와 동일 기준 (시세/이름 없는 엔트리 제거 + 거래대금 필터)
    all_filter_codes: list[str] = []
    avg_amt_5d: dict[str, int] = {}
    cache = engine_state.state.master_stocks_cache
    source_codes = codes if codes is not None else cache.keys()
    for cd in source_codes:
        entry = cache.get(cd)
        if entry is None:
            continue
        if int(entry.get("cur_price") or 0) <= 0 and (not entry.get("name") or entry.get("name") == cd):
            continue
        avg5d_million = int(entry.get("avg_5d_trade_amount", 0) or 0)
        avg5d_eok = avg5d_million // 100
        if min_avg_amt_eok > 0 and avg5d_eok < min_avg_amt_eok:
            continue
        all_filter_codes.append(cd)
        avg_amt_5d[cd] = avg5d_million  # 백만원 단위 (sector_calculator.py:89와 동일)

    # NXT-only 구간(08:00~09:00, 15:30~20:00) 거래일: NXT-enabled 종목만 포함
    # KRX 단독 종목은 틱 수신 불가하므로 업종 점수 및 수신율에서 제외
    if is_nxt_only_window():
        filtered_codes = [cd for cd in all_filter_codes if _is_nxt(cd)]
    else:
        filtered_codes = all_filter_codes

    # KRX/NXT 분리 — nxt_enable 필드 기반 (P10 SSOT, P23 일관성)
    krx_codes = [cd for cd in filtered_codes if not _is_nxt(cd)]
    nxt_codes = [cd for cd in filtered_codes if _is_nxt(cd)]
    all_codes = krx_codes + nxt_codes

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
    """업종별 종목 시세 테이블용 — master_stocks_cache 기반 필터링/정렬.

    작은 그릇 패턴 (길 B): 원본 캐시 엔트리를 통째로 복사하지 않고 화면에 필요한 필드만
    새 dict에 담아 반환. 단위는 원본(백만원) 그대로 유지 — 프론트 fmtMillionsToBillion이
    백만원→억 변환을 담당하므로 백엔드에서 단위 변환 금지 (정수 나눗셈 정밀도 손실 방지).
    """
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt, is_nxt_enabled as _is_nxt
    from backend.app.core.sector_mapping import get_merged_sectors_batch

    # 5거래일 평균 거래대금 필터링 (백엔드에서 필터링 수행 - 단일 소스 진리)
    min_avg_amt_eok = float(engine_state.state.integrated_system_settings_cache["sector_min_trade_amt"])
    cache = engine_state.state.master_stocks_cache

    # 1차 필터링: 시세/이름 없는 엔트리 제거 + 5거래일 평균 거래대금 필터링
    valid_codes: list[str] = []
    for cd in cache:
        entry = cache.get(cd, {})
        if int(entry.get("cur_price") or 0) <= 0 and (not entry.get("name") or entry.get("name") == cd):
            continue
        avg5d_million = int(entry.get("avg_5d_trade_amount", 0) or 0)
        avg5d_eok = avg5d_million // 100
        if min_avg_amt_eok > 0 and avg5d_eok < min_avg_amt_eok:
            continue
        valid_codes.append(cd)

    # 업종 배치 조회: N회 개별 await → 1회 배치 호출
    sectors_map = await get_merged_sectors_batch(valid_codes)

    # 작은 그릇: 화면에 필요한 필드만 담기 (단위는 원본 그대로 — 백만원)
    result: list[dict] = []
    for cd in valid_codes:
        entry = cache[cd]
        result.append({
            "code": cd,
            "name": entry.get("name", ""),
            "cur_price": entry.get("cur_price"),
            "change": entry.get("change"),
            "change_rate": entry.get("change_rate"),
            "strength": entry.get("strength"),
            "trade_amount": entry.get("trade_amount"),
            "sector": sectors_map.get(cd, "미분류"),
            "avg_amt_5d": int(entry.get("avg_5d_trade_amount", 0) or 0),  # 백만원 단위 유지 (프론트가 억 변환)
            "market_type": _get_mkt(cd) or "",
            "nxt_enable": _is_nxt(cd),
            "order_ratio": entry.get("order_ratio"),
            "program_net_buy": entry.get("program_net_buy"),
            "news_boost": entry.get("news_boost"),
            "high_5d": int(entry.get("high_5d_price", 0) or 0),
        })

    # 업종 분석 순위 기준 정렬
    sector_order: dict[str, int] = {}
    ss = engine_state.state.sector_summary_cache
    if ss:
        for sc in ss.sectors:
            sector_order[sc.sector] = sc.rank

    result.sort(key=lambda r: sector_order.get(r.get("sector", ""), 9999))

    return result


async def get_buy_targets_sector_stocks() -> list:
    """매수 후보 테이블용 — _sector_summary_cache.buy_targets + blocked_targets 반환 (guard_pass 필드 포함)."""
    ss = engine_state.state.sector_summary_cache
    if not ss:
        return []

    # 뉴스 가산점 캐시 — 엔트리별 중복 조회 방지를 위해 한 번만 조회 (P7)
    from backend.app.services.engine_radar import get_news_boost_cache
    news_boost_cache = get_news_boost_cache()

    # buy_targets와 blocked_targets 통합 (단일 소스 진리: _sector_summary_cache)
    result = [_build_target_entry(bt, news_boost_cache) for bt in ss.buy_targets]
    result.extend(_build_target_entry(bt, news_boost_cache) for bt in ss.blocked_targets)
    return result


def _build_target_entry(bt, news_boost_cache: dict[str, float] | None = None) -> dict:
    """매수 후보/차단 후보 공통 엔트리 생성 — master_stocks_cache 실시간 데이터 병합.

    필드 표시 규칙 (세션 8 — payload 계약 명시, P22 데이터 정합성):
      - 정적·식별 필드 (항상 값 존재):
          code, name, sector, market_type, nxt_enable, rank, guard_pass, reject_reason,
          boost_score
      - 실시간 파생 필드 (sectorStocks SSOT에서 파생 — null 허용):
          cur_price, change, change_rate, strength, trade_amount
          - null = 틱 미수신 (테스트모드 기동 직후, 장 전, 구독 지연 등)
          - 프론트 buyTargets는 sectorStocks 기준 rebindBuyTargetsRealtime으로 재결합
      - 원천 부재 표시 규칙 (P20 폴백 금지 — 명시적 "데이터 없음" 표시):
          high_5d: int(cache_entry.get("high_5d_price", 0) or 0) — 0 = 원천 부재/미다운로드
                   (5거래일 일봉 다운로드 전 또는 데이터 없음. 0은 유효 주가가 아니므로
                   프론트 buy-target.ts는 high_5d > 0 조건으로 표시 여부 판단)
          news_boost: 0.0 = 미부여 (뉴스 호재 캐시에 종목 코드 부재 시)
                      (0은 "가산점 없음"의 명시적 값이지 폴백이 아님 — 부재와 부여 안 함을 동일 취급)
          order_ratio: None = 호가잔량 미수신 (orderbook-update 이벤트로 갱신 전)
          program_net_buy: None = 프로그램 순매수 미수신 (program-update 이벤트로 갱신 전)

    avg_amt_5d 제거 (T1 설계 수정 — avg_amt_5d 주인은 SectorStock, 매수후보에서 불필요.
    업종분류 get_all_sector_stocks()에서 master_stocks_cache["avg_5d_trade_amount"]를
    억 단위로 변환하여 전송 — 우측 패널 표시용).
    """
    s = bt.stock
    cache_entry = engine_state.state.master_stocks_cache.get(s.code, {})
    _nbc = news_boost_cache or {}
    return {
        "code": s.code,
        "name": s.name,
        "cur_price": cache_entry.get("cur_price"),
        "change_rate": cache_entry.get("change_rate"),
        "change": cache_entry.get("change"),
        "strength": cache_entry.get("strength"),
        "trade_amount": cache_entry.get("trade_amount"),
        "market_type": s.market_type,
        "nxt_enable": s.nxt_enable,
        "sector": s.sector,
        "rank": bt.rank,
        "guard_pass": s.guard_pass,
        "reject_reason": bt.reject_reason,
        "boost_score": s.boost_score,
        "high_5d": int(cache_entry.get("high_5d_price", 0) or 0),
        "news_boost": _nbc.get(s.code, 0.0),
        "order_ratio": cache_entry.get("order_ratio"),
        "program_net_buy": cache_entry.get("program_net_buy"),
    }


async def get_all_sector_stocks(*, include_realtime: bool = False) -> list[dict]:
    """전체 종목(매매부적격 제외) — 업종분류 커스텀 페이지 전용.

    각 종목: { code, name, sector(get_merged_sectors_batch 기반), market_type, nxt_enable,
              avg_amt_5d(5거래일 평균 거래대금 — 백만원 단위, 프론트가 억 변환 담당) }
    include_realtime=True 시 추가: cur_price, change, change_rate, strength, trade_amount,
              order_ratio, program_net_buy, news_boost, high_5d (마스터 캐시 snapshot 생성용).

    avg_amt_5d (T1 설계 수정 — SectorStock 주인, P10 SSOT):
      - 데이터 소스: master_stocks_cache[cd]["avg_5d_trade_amount"] (백만원 단위)
      - 단위: 백만원 그대로 전송 (get_sector_stocks/build_master_cache_snapshot과 동일 — 프론트 fmtMillionsToBillion이 억 변환 단일 담당)
      - 0 = 원천 부재/미다운로드 (5거래일 일봉 전) 표시 규칙 유지 (P20 폴백 금지)
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
        avg5d_million = int(entry.get("avg_5d_trade_amount", 0) or 0)
        item = {
            "code": cd,
            "name": entry.get("name", ""),
            "sector": sectors_map.get(cd, "미분류"),
            "market_type": _get_mkt(cd) or "",
            "nxt_enable": _is_nxt(cd),
            "avg_amt_5d": avg5d_million,  # 백만원 단위 유지 (프론트 fmtMillionsToBillion이 억 변환 단일 담당)
        }
        if include_realtime:
            item["cur_price"] = entry.get("cur_price")
            item["change"] = entry.get("change")
            item["change_rate"] = entry.get("change_rate")
            item["strength"] = entry.get("strength")
            item["trade_amount"] = entry.get("trade_amount")
            item["order_ratio"] = entry.get("order_ratio")
            item["program_net_buy"] = entry.get("program_net_buy")
            item["news_boost"] = entry.get("news_boost")
            item["high_5d"] = int(entry.get("high_5d_price", 0) or 0)
        result.append(item)
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
        from backend.app.services.engine_initial_data import _set_sector_summary
        _set_sector_summary(_ss, "sector_data_provider.recompute_sector_summary")
        cancel_sector_recompute()

        # ── 5거래일 평균 최소 거래대금(N억원) 이상 종목 마킹 ──
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
        # 화면별 구독 대상 갱신 + 활성 연결에 추가·제거·스냅샷 전달 (태스크 2세션).
        # 업종 순위·매수 후보 대상이 바뀌면 활성 연결의 구독을 자동으로 최신화.
        from backend.app.services.page_subscription_targets import refresh_active_connections
        await refresh_active_connections(
            "업종 재계산",
            {"sector-ranking", "buy-target"},
        )
        logger.info("[업종] 재계산 종료")
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


async def recompute_buy_targets_only() -> None:
    """매수 차단·가산점 설정 변경 시 경량 재순위 — 업종 스코어 캐시 재사용, 매수 후보만 재생성.

    업종 스코어·컷오프·순위는 불변이므로 compute_full_sector_summary 생략 (설계서 섹션 5-8).
    sector_summary_cache.sectors 재사용 → build_buy_targets_from_settings만 재실행 →
    notify_buy_targets_update()로 UI 갱신 (P21 사용자 투명성).
    """
    from backend.app.domain.buy_filter import build_buy_targets_from_settings
    from backend.app.services.engine_lifecycle import is_engine_running
    from backend.app.services.engine_account_notify import notify_buy_targets_update
    from backend.app.services.engine_initial_data import _set_sector_summary

    logger.info("[매수후보] 경량 재순위 진입, 실행중=%s", is_engine_running())
    if not is_engine_running():
        logger.info("[매수후보] 엔진 미실행으로 종료")
        return
    _cached = engine_state.state.sector_summary_cache
    if _cached is None or not _cached.sectors:
        logger.warning("[매수후보] 업종 스코어 캐시 미구축 — 경량 재순위 생략 (다음 전체 재계산에서 갱신)")
        return
    try:
        from backend.app.services import engine_account
        _held = await engine_account.get_held_codes()
        _bought_today: set[str] = set()
        if engine_state.state.auto_trade is not None:
            _bought_today = set(engine_state.state.auto_trade._bought_today.keys())
        _ss = build_buy_targets_from_settings(
            _cached.sectors,
            engine_state.state.integrated_system_settings_cache,
            held_codes=_held,
            bought_today_codes=_bought_today,
        )
        _set_sector_summary(_ss, "sector_data_provider.recompute_buy_targets_only")
        await notify_buy_targets_update()
        # 매수 후보 대상 갱신 + 활성 연결 갱신 (태스크 2세션).
        from backend.app.services.page_subscription_targets import refresh_active_connections
        await refresh_active_connections("매수 후보 경량 재순위", {"buy-target"})
        logger.info("[매수후보] 경량 재순위 종료")
    except Exception as e:
        logger.warning("[매수후보] 경량 재순위 실패: %s", e, exc_info=True)
