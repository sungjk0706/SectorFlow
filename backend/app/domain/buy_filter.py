# -*- coding: utf-8 -*-
"""
매수 후보 필터 - 매수 타겟 생성 및 가드 필터링 로직.
"""
from __future__ import annotations
from typing import Literal
from backend.app.domain.models import SectorSummary


def compute_stock_boost_max(
    *,
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_score: float = 1.0,
    boost_program_net_buy_on: bool = False,
    boost_program_net_buy_score: float = 1.0,
    boost_news_on: bool = False,
    boost_news_score: float = 1.0,
) -> float:
    """종목 가산점 만점 — 활성화된 가산점 점수 합 (P10 SSOT).

    calculate_boost_score가 부여할 수 있는 최대 점수. 텔레그램 등 외부 표시가
    동일 만점 기준을 사용. 각 가산점은 on일 때만 점수 부여 가능하므로
    만점 = 활성화된 가산점 점수 합.
    """
    total = 0.0
    if boost_high_on:
        total += max(0.0, float(boost_high_score))
    if boost_order_ratio_on:
        total += max(0.0, float(boost_order_ratio_score))
    if boost_program_net_buy_on:
        total += max(0.0, float(boost_program_net_buy_score))
    if boost_news_on:
        total += max(0.0, float(boost_news_score))
    return total


def calculate_boost_score(
    stock,  # StockScore 타입 (순환 import 방지를 위해 타입 힌트 생략)
    *,
    high_5d_cache: dict[str, int],
    orderbook_cache: dict[str, tuple[int, int]],
    program_net_buy_cache: dict[str, int],
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_pct: float = 20.0,
    boost_order_ratio_score: float = 1.0,
    boost_program_net_buy_on: bool = False,
    boost_program_net_buy_score: float = 1.0,
    # ── 4. 뉴스 호재 가산점 (NWS) ──
    news_boost_cache: dict[str, float] | None = None,
    boost_news_on: bool = False,
    boost_news_score: float = 1.0,
) -> float:
    """종목 가산점 합계 계산. 항상 >= 0.0 반환.
    각 가산점 트리거 여부는 stock.boost_*_triggered 필드에 설정 (매수 근거 표시용).
    """
    score = 0.0
    # 트리거 필드 매 호출 시 초기화 (stale 상태 방지 — P22 정합성)
    stock.boost_high_triggered = False
    stock.boost_order_ratio_triggered = False
    stock.boost_news_triggered = False
    stock.boost_program_triggered = False

    # 1. 5거래일 고가 돌파
    if boost_high_on:
        high_val = high_5d_cache.get(stock.code, 0)
        if high_val > 0 and stock.cur_price is not None and stock.cur_price > high_val:
            score += boost_high_score
            stock.boost_high_triggered = True

    # 2. 잔량비율
    if boost_order_ratio_on:
        if boost_order_ratio_pct != 0:
            ob = orderbook_cache.get(stock.code)
            if ob is not None:
                bid, ask = ob
                if boost_order_ratio_pct > 0:
                    numerator, denominator = bid, ask
                else:
                    numerator, denominator = ask, bid
                if denominator > 0:
                    ratio = numerator / denominator
                    if ratio >= 1 + (abs(boost_order_ratio_pct) / 100):
                        score += boost_order_ratio_score
                        stock.boost_order_ratio_triggered = True

    # 3. 프로그램 순매수
    if boost_program_net_buy_on:
        net_buy = program_net_buy_cache.get(stock.code, 0)
        if net_buy > 0:
            score += boost_program_net_buy_score
            stock.boost_program_triggered = True

    # 4. 뉴스 호재 (NWS — news_boost_cache는 만료 항목 제거된 유효 항목만 포함)
    if boost_news_on:
        _nbc = news_boost_cache or {}
        news_score = _nbc.get(stock.code, 0.0)
        if news_score > 0:
            score += boost_news_score
            stock.boost_news_triggered = True

    return max(score, 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# 가드 필터링 함수
# ──────────────────────────────────────────────────────────────────────────────

def is_change_rate_blocked(
    change_rate: float,
    *,
    block_rise_on: bool = True,
    block_rise_pct: float = 7.0,
    block_fall_on: bool = True,
    block_fall_pct: float = -7.0,
) -> tuple[bool, str]:
    """
    등락률 기반 매수 차단 판정 (순수 함수 — 객체 변이 없음).
    check_stock_guards()와 trading.py execute_buy() 양쪽이 공유하는 단일 판정 소스 (W3 SSOT).
    반환: (blocked, reason) — reason은 "" | "상승률" | "하락률".
    block_rise_pct: 이 값 이상 상승 시 차단 (양수, 0 이하이면 검사 비활성)
    block_fall_pct: 이 값 이하 하락 시 차단 (음수, 후안 B 부호 규약, 0 이상이면 검사 비활성)
    """
    if block_rise_on and block_rise_pct > 0 and change_rate >= block_rise_pct:
        return True, "상승률"
    if block_fall_on and block_fall_pct < 0 and change_rate <= block_fall_pct:
        return True, "하락률"
    return False, ""


def check_stock_guards(
    stock,  # StockScore 타입 (순환 import 방지를 위해 타입 힌트 생략)
    *,
    block_rise_on: bool = True,
    block_rise_pct: float = 7.0,
    block_fall_on: bool = True,
    block_fall_pct: float = -7.0,
) -> object:  # StockScore
    """
    개별 종목 매수 가드 적용 (얇은 래퍼).
    판정 로직은 is_change_rate_blocked()에 위임하고, 본 함수는 StockScore의
    guard_pass/guard_reason 필드만 설정한다. 기존 시그니처·동작 유지 (호환성).
    block_rise_on: 상승률 차단 활성화 여부 (토글)
    block_rise_pct: 이 값 이상 상승 시 차단 (양수)
    block_fall_on: 하락률 차단 활성화 여부 (토글)
    block_fall_pct: 이 값 이하 하락 시 차단 (음수, 후안 B 부호 규약)
    (5거래일 평균 거래대금 필터는 업종분석 단계에서 1차 처리됨 — 여기서 중복 체크하지 않음)
    """
    blocked, reason = is_change_rate_blocked(
        stock.change_rate,
        block_rise_on=block_rise_on,
        block_rise_pct=block_rise_pct,
        block_fall_on=block_fall_on,
        block_fall_pct=block_fall_pct,
    )
    stock.guard_pass = not blocked
    stock.guard_reason = reason
    return stock


# ──────────────────────────────────────────────────────────────────────────────
# 매수 타겟 생성 함수
# ──────────────────────────────────────────────────────────────────────────────

# 전역 버전 카운터 (캐시 갱신 감지용)
_sector_summary_version_counter = 0


def apply_buy_block_guards(
    stock_sector_pairs: list,  # list[(StockScore, SectorScore)] — select_top_sector_stocks 출력
    *,
    block_rise_on: bool = True,
    block_rise_pct: float = 7.0,
    block_fall_on: bool = True,
    block_fall_pct: float = -7.0,
    rebuy_block_on: bool = True,
    held_codes: set[str] | None = None,
    bought_today_codes: set[str] | None = None,
) -> None:
    """
    종목 단위 차단 마킹 (in-place 변이, 반환 없음).
    (1) check_stock_guards()로 상승/하락률 차단 적용,
    (2) rebuy_block_on 시 보유/금일매수 종목 guard_pass=False 마킹.
    차단 조건 추가 시 이 함수만 변경 (P8 파이프 단계 · P22 guard_pass 단일 설정점).
    """
    _held = held_codes or set()
    _bought_today = bought_today_codes or set()

    for s, _ in stock_sector_pairs:
        check_stock_guards(
            s,
            block_rise_on=block_rise_on,
            block_rise_pct=block_rise_pct,
            block_fall_on=block_fall_on,
            block_fall_pct=block_fall_pct,
        )

    # ── 보유/금일매수 종목: 재매수 차단 ON 시에만 차단 마킹 (SSOT: trading.py execute_buy 게이트와 동일 조건) ──
    # rebuy_block_on=False → 보유/금일매수 종목도 매수 후보에 포함 (사용자 설정: 재매수 허용)
    # guard_pass=False → blocked_targets 로 이동, UI 제한 컬럼 "차단" 표시
    if rebuy_block_on:
        for s, _ in stock_sector_pairs:
            if s.code in _held:
                s.guard_pass = False
                s.guard_reason = "보유중"
            elif s.code in _bought_today:
                s.guard_pass = False
                s.guard_reason = "금일매수"


def rank_buy_targets(
    stock_sector_pairs: list,  # list[(StockScore, SectorScore)] — 차단 마킹 완료
    *,
    sort_keys: list[Literal["strength", "change_rate", "trade_amount"]] | None = None,
    high_5d_cache: dict[str, int] | None = None,
    orderbook_cache: dict[str, tuple[int, int]] | None = None,
    program_net_buy_cache: dict[str, int] | None = None,
    news_boost_cache: dict[str, float] | None = None,
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_pct: float = 20.0,
    boost_order_ratio_score: float = 1.0,
    boost_program_net_buy_on: bool = False,
    boost_program_net_buy_score: float = 1.0,
    boost_news_on: bool = False,
    boost_news_score: float = 1.0,
    sector_scores: list | None = None,  # list[SectorScore] — SectorSummary.sectors 원본
    prev_targets_map: dict[str, str] | None = None,  # code → 이전 reject_reason (보존용)
) -> SectorSummary:
    """
    종목 단위 순위·생성.
    (1) calculate_boost_score 가산점 계산,
    (2) proximity 정렬(부합 종목 앞, 미부합 뒤, 가산점·sort_keys 내림차순),
    (3) BuyTarget/blocked_targets 분류,
    (4) SectorSummary 생성.
    업종 선택·차단 판정 수행 안 함 (P8 파이프 단계).
    """
    global _sector_summary_version_counter

    from backend.app.domain.models import BuyTarget

    effective_keys: list[Literal["strength", "change_rate", "trade_amount"]] = list(sort_keys) if sort_keys else ["change_rate"]

    # ── 가산점 계산: 정렬 전 각 종목에 boost_score 설정 ──────────────────
    _h5d = high_5d_cache or {}
    _obc = orderbook_cache or {}
    _pnb = program_net_buy_cache or {}
    _nbc = news_boost_cache or {}

    for s, _ in stock_sector_pairs:
        # 차단 종목도 가산점 계산 (5거래일 고가; 잔량비/프순매는 구독 세션 제한으로 통과 종목만)
        _is_blocked = not s.guard_pass
        s.boost_score = calculate_boost_score(
            s,
            high_5d_cache=_h5d,
            orderbook_cache=_obc,
            program_net_buy_cache=_pnb,
            boost_high_on=boost_high_on,
            boost_high_score=boost_high_score,
            boost_order_ratio_on=boost_order_ratio_on and not _is_blocked,
            boost_order_ratio_pct=boost_order_ratio_pct,
            boost_order_ratio_score=boost_order_ratio_score,
            boost_program_net_buy_on=boost_program_net_buy_on and not _is_blocked,
            boost_program_net_buy_score=boost_program_net_buy_score,
            news_boost_cache=_nbc,
            boost_news_on=boost_news_on,
            boost_news_score=boost_news_score,
        )

    # ── 정렬: 다단계 기준 (sort_keys 순서대로) ────────────────────────────
    # 부합(guard_pass) 종목이 앞, 미부합 종목이 뒤.
    # 같은 그룹 내에서는 boost_score 내림차순 → sort_keys[0] → sort_keys[1] → … 순서로 내림차순 정렬.
    def _sort_value(s, key: Literal["strength", "change_rate", "trade_amount"]) -> float:
        if key == "strength":
            return s.strength
        elif key == "trade_amount":
            return float(s.trade_amount)
        else:  # change_rate
            return s.change_rate

    def _proximity_key(pair) -> tuple:
        s, sc = pair
        is_blocked = 0 if s.guard_pass else 1
        return (is_blocked, -s.boost_score) + tuple(-_sort_value(s, k) for k in effective_keys)

    stock_sector_pairs.sort(key=_proximity_key)

    buy_targets: list = []
    blocked_targets: list = []
    pass_rank = 1
    blocked_rank = 1
    for stock, sc in stock_sector_pairs:
        if not stock.guard_pass:
            # 차단 종목: guard_reason 사용. 보유중/금일매수 등 가드 사유는 guard_pass 전환 시 재설정되므로 보존하지 않음.
            target = BuyTarget(
                rank=blocked_rank,
                sector_rank=sc.rank,
                stock=stock,
                reject_reason=stock.guard_reason,
            )
            blocked_targets.append(target)
            blocked_rank += 1
        else:
            target = BuyTarget(
                rank=pass_rank,
                sector_rank=sc.rank,
                stock=stock,
                reject_reason="",
            )
            buy_targets.append(target)
            pass_rank += 1

    _sector_summary_version_counter += 1

    return SectorSummary(
        sectors=sector_scores if sector_scores is not None else [],
        buy_targets=buy_targets,
        blocked_targets=blocked_targets,
        version=_sector_summary_version_counter,
    )


def build_buy_targets_from_settings(
    sector_scores: list,
    settings: dict,
    *,
    held_codes: set[str] | None = None,
    bought_today_codes: set[str] | None = None,
    prev_targets_map: dict[str, str] | None = None,
) -> SectorSummary:
    """설정 → 3단계 순차 호출 배선 (어댑터).
    (1) select_top_sector_stocks: 업종 단위 선택,
    (2) apply_buy_block_guards: 종목 차단 마킹,
    (3) rank_buy_targets: 종목 순위·생성.
    시그니처 유지 (호출부 3곳 영향 없음).
    """
    from backend.app.domain.sector_calculator import select_top_sector_stocks
    from backend.app.services.engine_radar import (
        get_high_price_5d_cache,
        get_orderbook_cache,
        get_program_net_buy_cache,
        get_news_boost_cache,
    )

    pairs = select_top_sector_stocks(
        sector_scores,
        max_sectors=int(settings.get("sector_max_targets", 3)),
    )
    apply_buy_block_guards(
        pairs,
        block_rise_on=bool(settings.get("buy_block_rise_on", True)),
        block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
        block_fall_on=bool(settings.get("buy_block_fall_on", True)),
        block_fall_pct=float(settings.get("buy_block_fall_pct", -7.0)),
        rebuy_block_on=bool(settings.get("rebuy_block_on", True)),
        held_codes=held_codes,
        bought_today_codes=bought_today_codes,
    )
    return rank_buy_targets(
        pairs,
        sort_keys=settings.get("sector_sort_keys") or None,
        high_5d_cache=get_high_price_5d_cache(),
        orderbook_cache=get_orderbook_cache(),
        program_net_buy_cache=get_program_net_buy_cache(),
        news_boost_cache=get_news_boost_cache(),
        boost_high_on=bool(settings.get("boost_high_breakout_on", False)),
        boost_high_score=float(settings.get("boost_high_breakout_score", 1.0)),
        boost_order_ratio_on=bool(settings.get("boost_order_ratio_on", False)),
        boost_order_ratio_pct=float(settings.get("boost_order_ratio_pct", 20.0)),
        boost_order_ratio_score=float(settings.get("boost_order_ratio_score", 1.0)),
        boost_program_net_buy_on=bool(settings.get("boost_program_net_buy_on", False)),
        boost_program_net_buy_score=float(settings.get("boost_program_net_buy_score", 1.0)),
        boost_news_on=bool(settings.get("boost_news_on", False)),
        boost_news_score=float(settings.get("boost_news_score", 1.0)),
        sector_scores=sector_scores,
        prev_targets_map=prev_targets_map,
    )


def apply_incremental_buy_target_update(
    summary: SectorSummary,
    events: list[dict],
    settings: dict,
    *,
    held_codes: set[str] | None = None,
    bought_today_codes: set[str] | None = None,
    prev_targets_map: dict[str, str] | None = None,
) -> SectorSummary:
    """이벤트 기반 증분 갱신 — 변경 업종 종목만 추가/제거 후 재정렬.

    기존 매수후보에서 변경되지 않은 업종의 종목은 그대로 유지하고,
    통과→탈락·상위 N개 이탈 업종의 종목만 제거,
    탈락→통과·상위 N개 진입 업종의 종목만 추가한다 (설계서 결정 3).

    기존 build_buy_targets_from_settings 전체 재생성은 콜드 스타트·설정 변경 경로에서 유지.
    본 함수는 매수후보 갱신 루프(3단계)에서 이벤트 소비 시 호출.

    Args:
        summary: 기존 SectorSummary (캐시 — sectors + buy_targets + blocked_targets).
        events: 매수후보 갱신 이벤트 리스트. 일반 이벤트 항목:
            {"sector": 업종명, "action": "add"|"remove", "reason": str, "stock_codes": list[str]}
            후보 집합 불일치 시 {"action": "reconcile", "reason": str}.
        settings: 매수설정 (가드·가산점·정렬 기준).
        held_codes: 보유 종목 코드 집합 (재매수 차단용).
        bought_today_codes: 금일 매수 종목 코드 집합 (재매수 차단용).
        prev_targets_map: code → 이전 reject_reason (보존용).

    Returns:
        갱신된 SectorSummary (sectors는 기존 유지, buy_targets·blocked_targets 재구성).
    """
    if any(event.get("action") == "reconcile" for event in events):
        return build_buy_targets_from_settings(
            summary.sectors,
            settings,
            held_codes=held_codes,
            bought_today_codes=bought_today_codes,
            prev_targets_map=prev_targets_map,
        )

    from backend.app.services.engine_radar import (
        get_high_price_5d_cache,
        get_orderbook_cache,
        get_program_net_buy_cache,
        get_news_boost_cache,
    )

    # 1. 제거·추가 업종 집합 추출
    remove_sectors: set[str] = {e["sector"] for e in events if e["action"] == "remove"}
    add_sectors: set[str] = {e["sector"] for e in events if e["action"] == "add"}

    # 2. 업종명 → SectorScore 매핑 (캐시 sectors 기준)
    sector_by_name: dict[str, object] = {sc.sector: sc for sc in summary.sectors}

    # 3. 기존 buy_targets + blocked_targets에서 (stock, sector) 페어 재구성
    #    제거 업종 종목은 제외 (설계서 결정 3 — 통과→탈락·상위 N개 이탈 종목 제거)
    pairs: list = []
    for target in list(summary.buy_targets) + list(summary.blocked_targets):
        stock = target.stock
        sector_name = getattr(stock, "sector", "")
        if sector_name in remove_sectors:
            continue
        sc = sector_by_name.get(sector_name)
        if sc is None:
            # 업종이 캐시에서 사라진 경우 — 유지 불가, 스킵
            continue
        pairs.append((stock, sc))

    # 4. 추가 업종 종목 페어 구성 + 가드 적용 (새 종목만)
    #    탈락→통과·상위 N개 진입 업종의 종목을 매수후보에 추가 (설계서 결정 3)
    add_pairs: list = []
    for sector_name in add_sectors:
        sc = sector_by_name.get(sector_name)
        if sc is None:
            continue
        for s in sc.stocks:
            add_pairs.append((s, sc))

    if add_pairs:
        apply_buy_block_guards(
            add_pairs,
            block_rise_on=bool(settings.get("buy_block_rise_on", True)),
            block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
            block_fall_on=bool(settings.get("buy_block_fall_on", True)),
            block_fall_pct=float(settings.get("buy_block_fall_pct", -7.0)),
            rebuy_block_on=bool(settings.get("rebuy_block_on", True)),
            held_codes=held_codes,
            bought_today_codes=bought_today_codes,
        )
        pairs.extend(add_pairs)

    # 5. 재정렬 — rank_buy_targets 호출 (갱신 이벤트 시에만 재정렬 — 설계서 결정 4)
    return rank_buy_targets(
        pairs,
        sort_keys=settings.get("sector_sort_keys") or None,
        high_5d_cache=get_high_price_5d_cache(),
        orderbook_cache=get_orderbook_cache(),
        program_net_buy_cache=get_program_net_buy_cache(),
        news_boost_cache=get_news_boost_cache(),
        boost_high_on=bool(settings.get("boost_high_breakout_on", False)),
        boost_high_score=float(settings.get("boost_high_breakout_score", 1.0)),
        boost_order_ratio_on=bool(settings.get("boost_order_ratio_on", False)),
        boost_order_ratio_pct=float(settings.get("boost_order_ratio_pct", 20.0)),
        boost_order_ratio_score=float(settings.get("boost_order_ratio_score", 1.0)),
        boost_program_net_buy_on=bool(settings.get("boost_program_net_buy_on", False)),
        boost_program_net_buy_score=float(settings.get("boost_program_net_buy_score", 1.0)),
        boost_news_on=bool(settings.get("boost_news_on", False)),
        boost_news_score=float(settings.get("boost_news_score", 1.0)),
        sector_scores=summary.sectors,
        prev_targets_map=prev_targets_map,
    )
