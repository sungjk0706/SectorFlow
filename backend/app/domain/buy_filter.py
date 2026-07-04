# -*- coding: utf-8 -*-
"""
매수 후보 필터 - 매수 타겟 생성 및 가드 필터링 로직.
"""
from __future__ import annotations
from typing import Literal
from backend.app.domain.models import SectorSummary
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
    # ── 거래대금 순위 가산점 ──
    trade_amount_rank: int = -1,  # 0 = 매수후보 내 거래대금 1위, -1 = 순위 밖/보유 제외
    boost_trade_amount_rank_on: bool = False,
    boost_trade_amount_rank_score: float = 1.0,
) -> float:
    """종목 가산점 합계 계산. 항상 >= 0.0 반환.
    """
    score = 0.0

    # 1. 5일 전고가 돌파
    if boost_high_on:
        high_val = high_5d_cache.get(stock.code, 0)
        if high_val > 0 and stock.cur_price > high_val:
            score += boost_high_score

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

    # 3. 프로그램 순매수
    if boost_program_net_buy_on:
        net_buy = program_net_buy_cache.get(stock.code, 0)
        if net_buy > 0:
            score += boost_program_net_buy_score

    # 4. 거래대금 순위 (매수후보 내 보유 제외 후 거래대금 상위 1종목)
    if boost_trade_amount_rank_on and trade_amount_rank == 0:
        score += boost_trade_amount_rank_score

    return max(score, 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# 가드 필터링 함수
# ──────────────────────────────────────────────────────────────────────────────

def check_stock_guards(
    stock,  # StockScore 타입 (순환 import 방지를 위해 타입 힌트 생략)
    *,
    block_rise_pct: float = 7.0,
    block_fall_pct: float = 7.0,
    min_strength: float = 0.0,
) -> object:  # StockScore
    """
    개별 종목 매수 가드 적용.
    block_rise_pct: 이 값 이상 상승 시 차단
    block_fall_pct: 이 값 이상 하락 시 차단
    min_strength: 체결강도 최소 기준 (0=미적용)
    (5일평균거래대금 필터는 업종분석 단계에서 1차 처리됨 — 여기서 중복 체크하지 않음)
    """
    if stock.change_rate >= block_rise_pct:
        stock.guard_pass = False
        stock.guard_reason = "상승률"
        return stock
    if stock.change_rate <= -block_fall_pct:
        stock.guard_pass = False
        stock.guard_reason = "하락률"
        return stock
    if min_strength > 0 and stock.strength >= 0 and stock.strength < min_strength:
        stock.guard_pass = False
        stock.guard_reason = "체결강도"
        return stock
    stock.guard_pass = True
    stock.guard_reason = ""
    return stock


# ──────────────────────────────────────────────────────────────────────────────
# 매수 타겟 생성 함수
# ──────────────────────────────────────────────────────────────────────────────

# 전역 버전 카운터 (캐시 갱신 감지용)
_sector_summary_version_counter = 0


def create_buy_targets(
    sector_scores: list,  # list[SectorScore]
    *,
    sort_keys: list[Literal["strength", "change_rate", "trade_amount"]] | None = None,
    min_rise_ratio: float = 0.6,
    block_rise_pct: float = 7.0,
    block_fall_pct: float = 7.0,
    min_strength: float = 0.0,
    max_sectors: int = 3,
    # ── 가산점 관련 파라미터 (기본값 = 모든 가산점 OFF → boost_score=0.0) ──
    high_5d_cache: dict[str, int] | None = None,
    orderbook_cache: dict[str, tuple[int, int]] | None = None,
    program_net_buy_cache: dict[str, int] | None = None,
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_pct: float = 20.0,
    boost_order_ratio_score: float = 1.0,
    boost_program_net_buy_on: bool = False,
    boost_program_net_buy_score: float = 1.0,
    # ── 거래대금 순위 가산점 ──
    held_codes: set[str] | None = None,
    boost_trade_amount_rank_on: bool = False,
    boost_trade_amount_rank_score: float = 1.0,
) -> SectorSummary:
    """
    섹터 스코어 -> 매수 타겟 큐 생성.

    상위 max_sectors 개 섹터에 속한 종목을 모두 큐에 포함.
    순위 = '설정값에 가까운 정도' (부합 여부와 무관).
    개별 종목 가드(상승률/하락률) 미통과 -> blocked_targets (UI 표시용).
    지수 가드 발동 시 전체 blocked_targets.

    min_rise_ratio: 업종 순위 가중치 점수에서 이미 반영됨 (호환성 유지용 파라미터).
    sort_keys: 다단계 정렬 기준 리스트 (1순위→2순위→…).
    """
    global _sector_summary_version_counter

    # dataclass import
    from backend.app.domain.models import BuyTarget

    effective_keys: list[Literal["strength", "change_rate", "trade_amount"]] = list(sort_keys) if sort_keys else ["change_rate"]

    buy_targets: list = []
    blocked_targets: list = []
    sector_count = 0

    # 모든 섹터 종목을 하나의 풀로 모은 뒤 '설정값에 가까운 순서'로 정렬
    all_stocks: list = []

    for sc in sector_scores:
        # 순위 없는 업종(rank=0)은 매수대상 카운트에서 제외
        if sc.rank == 0:
            continue
        if sector_count >= max_sectors:
            break
        sector_count += 1

        # 개별 종목 가드 적용
        for s in sc.stocks:
            check_stock_guards(
                s,
                block_rise_pct=block_rise_pct,
                block_fall_pct=block_fall_pct,
                min_strength=min_strength,
            )
            all_stocks.append((s, sc))

    # ── 정렬: 다단계 기준 (sort_keys 순서대로) ────────────────────────────
    # 부합(guard_pass) 종목이 앞, 미부합 종목이 뒤.
    # 같은 그룹 내에서는 boost_score 내림차순 → sort_keys[0] → sort_keys[1] → … 순서로 내림차순 정렬.

    # ── 가산점 계산: 정렬 전 각 종목에 boost_score 설정 ──────────────────
    _h5d = high_5d_cache or {}
    _obc = orderbook_cache or {}
    _pnb = program_net_buy_cache or {}
    _held = held_codes or set()

    # ── 거래대금 순위 계산: 보유 종목 제외, Guard 통과 종목만 대상 ──
    _trade_amount_rank_map: dict[str, int] = {}
    if boost_trade_amount_rank_on:
        _eligible = [s for s, _ in all_stocks if s.guard_pass and s.code not in _held]
        _eligible.sort(key=lambda st: float(st.trade_amount), reverse=True)
        for i, st in enumerate(_eligible):
            _trade_amount_rank_map[st.code] = i  # 0 = 1위

    for s, _ in all_stocks:
        # Guard→Boost 최적화: Guard 미통과 종목은 Boost 계산 스킵
        if not s.guard_pass:
            s.boost_score = 0.0
            s.trade_amount_rank = -1
            continue
        s.boost_score = calculate_boost_score(
            s,
            high_5d_cache=_h5d,
            orderbook_cache=_obc,
            program_net_buy_cache=_pnb,
            boost_high_on=boost_high_on,
            boost_high_score=boost_high_score,
            boost_order_ratio_on=boost_order_ratio_on,
            boost_order_ratio_pct=boost_order_ratio_pct,
            boost_order_ratio_score=boost_order_ratio_score,
            boost_program_net_buy_on=boost_program_net_buy_on,
            boost_program_net_buy_score=boost_program_net_buy_score,
            trade_amount_rank=_trade_amount_rank_map.get(s.code, -1),
            boost_trade_amount_rank_on=boost_trade_amount_rank_on,
            boost_trade_amount_rank_score=boost_trade_amount_rank_score,
        )
        s.trade_amount_rank = _trade_amount_rank_map.get(s.code, -1)

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

    all_stocks.sort(key=_proximity_key)

    pass_rank = 1
    blocked_rank = 1
    for stock, sc in all_stocks:
        if not stock.guard_pass:
            target = BuyTarget(
                rank=blocked_rank,
                sector_rank=sc.rank,
                stock=stock,
                reason=stock.guard_reason,
            )
            blocked_targets.append(target)
            blocked_rank += 1
        else:
            pass_reason = ""
            target = BuyTarget(
                rank=pass_rank,
                sector_rank=sc.rank,
                stock=stock,
                reason=pass_reason,
            )
            buy_targets.append(target)
            pass_rank += 1

    _sector_summary_version_counter += 1

    # SectorSummary import
    from backend.app.domain.models import SectorSummary

    return SectorSummary(
        sectors=sector_scores,
        buy_targets=buy_targets,
        blocked_targets=blocked_targets,
        version=_sector_summary_version_counter,
    )


def build_buy_targets_from_settings(
    sector_scores: list,
    settings: dict,
    *,
    held_codes: set[str] | None = None,
) -> SectorSummary:
    from backend.app.services.engine_radar import get_high_price_5d_cache, get_orderbook_cache, get_program_net_buy_cache

    return create_buy_targets(
        sector_scores,
        sort_keys=settings.get("sector_sort_keys") or None,
        min_rise_ratio=float(settings.get("sector_min_rise_ratio_pct", 60.0)) / 100.0,
        block_rise_pct=float(settings.get("buy_block_rise_pct", 7.0)),
        block_fall_pct=float(settings.get("buy_block_fall_pct", 7.0)),
        min_strength=float(settings.get("buy_min_strength", 0)),
        max_sectors=int(settings.get("sector_max_targets", 3)),
        high_5d_cache=get_high_price_5d_cache(),
        orderbook_cache=get_orderbook_cache(),
        program_net_buy_cache=get_program_net_buy_cache(),
        boost_high_on=bool(settings.get("boost_high_breakout_on", False)),
        boost_high_score=float(settings.get("boost_high_breakout_score", 1.0)),
        boost_order_ratio_on=bool(settings.get("boost_order_ratio_on", False)),
        boost_order_ratio_pct=float(settings.get("boost_order_ratio_pct", 20.0)),
        boost_order_ratio_score=float(settings.get("boost_order_ratio_score", 1.0)),
        boost_program_net_buy_on=bool(settings.get("boost_program_net_buy_on", False)),
        boost_program_net_buy_score=float(settings.get("boost_program_net_buy_score", 1.0)),
        held_codes=held_codes,
        boost_trade_amount_rank_on=bool(settings.get("boost_trade_amount_rank_on", False)),
        boost_trade_amount_rank_score=float(settings.get("boost_trade_amount_rank_score", 1.0)),
    )
