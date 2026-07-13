# -*- coding: utf-8 -*-
"""
업종 계산기 - 업종 점수 계산 및 통합 진입점.
"""
from __future__ import annotations
from typing import Literal
import logging
from backend.app.domain.models import SectorSummary
from backend.app.domain.sector_filter import filter_by_avg_amt, group_by_sector
from backend.app.domain.sector_score import calculate_bonus_scores
from backend.app.services.engine_state import state
logger = logging.getLogger(__name__)


async def compute_sector_scores(
    all_codes: list[str],
    *,
    trade_prices: dict[str, int],
    trade_amounts: dict[str, int],
    avg_amt_5d: dict[str, int],
    min_avg_amt_eok: float = 0.0,                  # 1차 필터: 5일평균 최소 거래대금 (억 단위, 0=미적용)
) -> list:  # list[SectorScore]
    """
    업종별 강도 스코어 계산.

    단일 소스 진리: master_stocks_cache를 직접 참조.

    그룹핑 방식:
      - sector_mapping.get_merged_sector(code) 로 종목코드 → 커스텀 업종 매핑
      - 빈 문자열 반환 종목은 스킵 (미매핑 종목 제외)

    데이터 우선순위:
      현재가: trade_prices(REAL) > master_stocks_cache
      거래대금: trade_amounts(FID29 합산 캐시) > master_stocks_cache trade_amount/acc_trde_prica
      등락률: master_stocks_cache
    """
    # 시장구분 캐시 참조
    from backend.app.services.engine_symbol_utils import get_stock_market as _get_mkt
    from backend.app.services.engine_symbol_utils import is_nxt_enabled as _is_nxt

    # dataclass import
    from backend.app.domain.models import StockScore, SectorScore

    # ── 1차 필터: 5일평균거래대금 (업종 그룹핑 전 적용 - 단일 소스 진리) ──
    filtered_codes = await filter_by_avg_amt(all_codes, avg_amt_5d, min_avg_amt_eok)

    # 업종별 종목 그룹핑 — Custom_Data > Auto_Mapping 우선순위 적용
    sector_groups = await group_by_sector(filtered_codes)

    sector_scores: list = []

    for sector, codes in sector_groups.items():
        stocks: list = []

        for code in codes:
            # master_stocks_cache에 등록된 종목만 대상
            if code not in state.master_stocks_cache:
                continue

            # 현재가 조회
            cur_price = int(trade_prices.get(code, 0) or 0)
            detail = state.master_stocks_cache.get(code, {})

            if cur_price <= 0:
                cur_price = int(detail.get("cur_price", 0) or 0)
            # cur_price 0도 유효한 데이터 -- WS 틱 미수신 상태일 뿐, 스킵하지 않음

            # 등락률: master_stocks_cache(change_rate) 사용 (단일 소스 진리)
            change_rate = float(detail.get("change_rate", 0) or 0)

            # 전일 대비 (원)
            change = int(detail.get("change", 0) or 0)

            # 거래대금 (원 단위) - WS 틱 우선, master_stocks_cache trade_amount fallback
            ta_ws = int(trade_amounts.get(code, 0) or 0)
            ta = ta_ws
            if ta <= 0:
                ta = int(detail.get("trade_amount", 0) or 0)

            # 5일 평균 거래대금: avg_amt_5d dict는 master_stocks_cache["avg_5d_trade_amount"] = 백만원 단위
            avg5d_million = int(avg_amt_5d.get(code, 0) or 0)
            avg5d_eok = avg5d_million // 100  # 백만원 → 억 단위 변환
            avg5d_won = avg5d_million * 1_000_000  # 백만원 → 원 단위 변환 (비율 계산용)

            # 5D거래대금비율
            ratio_5d = round(ta / avg5d_won * 100.0, 1) if avg5d_won > 0 and ta > 0 else 0.0

            # 체결강도: master_stocks_cache(strength) 사용 (단일 소스 진리)
            st_raw = detail.get("strength", "-")
            try:
                strength_val = float(str(st_raw).replace("%", "").replace(",", "").strip())
            except (ValueError, TypeError):
                strength_val = -1.0

            # 종목명
            name = (
                detail.get("name")
                or code
            )

            stocks.append(StockScore(
                code=code,
                name=str(name),
                sector=sector,
                change_rate=change_rate,
                trade_amount=ta,
                avg_amt_5d=avg5d_eok,
                ratio_5d_pct=ratio_5d,
                strength=strength_val,
                cur_price=cur_price,
                change=change,
                market_type=_get_mkt(code) or "",
                nxt_enable=_is_nxt(code),
            ))

        if not stocks:
            continue

        # ── 5일평균거래대금 필터: 업종강도 계산 + 매수 후보 모두 적용 ─────────
        if min_avg_amt_eok > 0:
            filtered_stocks = [s for s in stocks if s.avg_amt_5d >= min_avg_amt_eok]
        else:
            filtered_stocks = stocks

        if not filtered_stocks:
            continue

        # ── 전체 종목 기준 실제 값 (트리밍 제거 — 순위/백분위 기반 점수이므로 불필요) ──
        raw_rise_count = sum(1 for s in filtered_stocks if s.change_rate > 0)
        raw_total = len(filtered_stocks)
        raw_rise_ratio = raw_rise_count / raw_total if raw_total > 0 else 0.0
        raw_total_ta = sum(s.trade_amount for s in filtered_stocks)
        avg_ta = raw_total_ta // raw_total if raw_total > 0 else 0
        avg_cr = sum(s.change_rate for s in filtered_stocks) / len(filtered_stocks) if len(filtered_stocks) > 0 else 0.0
        avg_r5d = sum(s.ratio_5d_pct for s in filtered_stocks) / len(filtered_stocks) if len(filtered_stocks) > 0 else 0.0

        sector_scores.append(SectorScore(
            sector=sector,
            total=raw_total,
            rise_count=raw_rise_count,
            rise_ratio=raw_rise_ratio,
            avg_change_rate=avg_cr,
            avg_trade_amount=avg_ta,
            avg_ratio_5d_pct=avg_r5d,
            stocks=filtered_stocks,
        ))

    return sector_scores


async def compute_full_sector_summary(
    all_codes: list[str],
    *,
    trade_prices: dict[str, int],
    trade_amounts: dict[str, int],
    avg_amt_5d: dict[str, int],
    latest_index: dict[str, dict],
    # 설정값
    sort_keys: list[Literal["strength", "change_rate", "trade_amount"]] | None = None,
    min_rise_ratio: float = 0.6,
    block_rise_pct: float = 7.0,
    block_fall_pct: float = 7.0,
    min_strength: float = 0.0,
    min_avg_amt_eok: float = 0.0,
    max_sectors: int = 3,
    # ── 업종 점수 3단계 누적 가산점 만점 (사용자 설정) ──
    max_rise_ratio_score: int = 10,
    max_relative_strength_score: int = 7,
    max_trade_amount_score: int = 5,
    # ── 가산점 관련 파라미터 (pass-through → build_buy_targets) ──
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
) -> SectorSummary:
    """
    전체 파이프라인 한 번에 실행.
    engine_bootstrap, engine_sector_confirm, sector_data_provider, telegram_bot에서 이벤트 기반 호출.

    sector_mapping.get_merged_sector() 기반 커스텀 업종 그룹핑.
    컷오프(min_rise_ratio)는 calculate_bonus_scores 내부에서 처리 (옵션 C 2패스).
    """
    # 1. 업종 스코어 계산 (컷오프는 calculate_bonus_scores 내부에서 처리)
    sector_scores = await compute_sector_scores(
        all_codes,
        trade_prices=trade_prices,
        trade_amounts=trade_amounts,
        avg_amt_5d=avg_amt_5d,
        min_avg_amt_eok=min_avg_amt_eok,
    )

    # 2. 3단계 누적 가산점 계산 + 컷오프 + 정렬 + 순위 부여
    calculate_bonus_scores(
        sector_scores,
        min_rise_ratio=min_rise_ratio,
        max_rise_ratio_score=max_rise_ratio_score,
        max_relative_strength_score=max_relative_strength_score,
        max_trade_amount_score=max_trade_amount_score,
    )

    return SectorSummary(
        sectors=sector_scores,
        buy_targets=[],
        blocked_targets=[],
    )
