# -*- coding: utf-8 -*-
"""
업종 계산기 - 업종 점수 계산 및 통합 진입점.

계산 본체는 명시적으로 전달된 입력 자료만 사용한다 (P10 SSOT, P24 단순성).
엔진 상태·서비스·외부 조회는 계산 영역 바깥에서 준비해 전달한다.
"""
from __future__ import annotations
import logging
from backend.app.domain.models import SectorSummary
from backend.app.domain.sector_filter import filter_by_avg_amt, group_by_sector
from backend.app.domain.sector_score import calculate_bonus_scores
logger = logging.getLogger(__name__)


async def compute_sector_scores(
    all_codes: list[str],
    *,
    trade_prices: dict[str, int],
    trade_amounts: dict[str, int],
    avg_amt_5d: dict[str, int],
    master_stocks_cache: dict,
    sector_map: dict[str, str],
    min_avg_amt_eok: float = 0.0,                  # 1차 필터: 5거래일 평균 최소 거래대금 (억 단위, 0=미적용)
) -> list:  # list[SectorScore]
    """
    업종별 강도 스코어 계산.

    입력 계약 (명시적 입력만 사용 — 계산 본체는 외부 상태·조회를 직접 참조하지 않음):
      - master_stocks_cache: 종목별 이름·업종·현재가·등락률·체결강도·시장 구분·NXT 여부 자료
      - sector_map: 종목 코드별 업종 이름 자료 (group_by_sector에 전달)

    누락 불가 — master_stocks_cache·sector_map은 필수 입력. None을 폴백으로 덮지 않고
    즉시 TypeError로 드러난다 (P20 폴백 금지, P22 데이터 정합성).

    데이터 우선순위:
      현재가: trade_prices(REAL) > master_stocks_cache
      거래대금: trade_amounts(FID29 합산 캐시) > master_stocks_cache trade_amount/acc_trde_prica
      등락률: master_stocks_cache
    """
    # dataclass import
    from backend.app.domain.models import StockScore, SectorScore

    # ── 1차 필터: 5거래일 평균 거래대금 (업종 그룹핑 전 적용 - 단일 소스 진리) ──
    filtered_codes = await filter_by_avg_amt(all_codes, avg_amt_5d, min_avg_amt_eok)

    # 업종별 종목 그룹핑 — 전달받은 sector_map만 사용 (외부 조회 없음)
    sector_groups = await group_by_sector(filtered_codes, sector_map=sector_map)

    sector_scores: list = []

    for sector, codes in sector_groups.items():
        stocks: list = []

        for code in codes:
            # master_stocks_cache에 등록된 종목만 대상
            if code not in master_stocks_cache:
                continue

            # 현재가: trade_prices(REAL) > master_stocks_cache (P10 SSOT)
            # None = 실시간 데이터 미수신 — 0으로 폴백하지 않고 None 유지 (P20/P22)
            detail = master_stocks_cache.get(code, {})
            _tp_raw = trade_prices.get(code)
            cur_price = int(_tp_raw) if _tp_raw is not None else None
            if cur_price is None or cur_price <= 0:
                _cp_raw = detail.get("cur_price")
                cur_price = int(_cp_raw) if _cp_raw is not None else None

            # 등락률: master_stocks_cache(change_rate) 사용 (단일 소스 진리)
            # None = 실시간 데이터 미수신 — 0으로 폴백하지 않고 None 유지 (P20/P22)
            _change_rate_raw = detail.get("change_rate")
            change_rate = float(_change_rate_raw) if _change_rate_raw is not None else None

            # 전일 대비 (원)
            change = int(detail.get("change", 0) or 0)

            # 거래대금 (원 단위) - WS 틱 우선, master_stocks_cache trade_amount fallback
            # None = 실시간 데이터 미수신 — 0으로 폴백하지 않고 None 유지 (P20/P22)
            ta_raw = trade_amounts.get(code)
            ta_ws = int(ta_raw) if ta_raw is not None else None
            ta = ta_ws
            if ta is None or ta <= 0:
                _ta_raw = detail.get("trade_amount")
                ta = int(_ta_raw) if _ta_raw is not None else None

            # 미수신 종목(change_rate, trade_amount, cur_price 중 하나라도 None)은 업종 점수 계산에서 제외 (P20/P22)
            if change_rate is None or ta is None or cur_price is None:
                continue

            # 5거래일 평균 거래대금: avg_amt_5d dict는 master_stocks_cache["avg_5d_trade_amount"] = 백만원 단위
            avg5d_million = int(avg_amt_5d.get(code, 0) or 0)
            avg5d_eok = avg5d_million // 100  # 백만원 → 억 단위 변환

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

            # 시장 구분·NXT 여부: master_stocks_cache에서 직접 읽기 (engine_symbol_utils 의존 제거)
            stocks.append(StockScore(
                code=code,
                name=str(name),
                sector=sector,
                change_rate=change_rate,
                trade_amount=ta,
                avg_amt_5d=avg5d_eok,
                strength=strength_val,
                cur_price=cur_price,
                change=change,
                market_type=str(detail.get("market") or ""),
                nxt_enable=bool(detail.get("nxt_enable", False)),
            ))

        if not stocks:
            continue

        # ── 5거래일 평균 거래대금 필터: 업종강도 계산 + 매수 후보 모두 적용 ─────────
        if min_avg_amt_eok > 0:
            filtered_stocks = [s for s in stocks if s.avg_amt_5d >= min_avg_amt_eok]
        else:
            filtered_stocks = stocks

        if not filtered_stocks:
            continue

        # ── 필터링된 종목 기준 집계값 (순위 기반 점수이므로 트리밍 불필요) ──
        rise_count = sum(1 for s in filtered_stocks if s.change_rate > 0)
        total = len(filtered_stocks)
        rise_ratio = rise_count / total if total > 0 else 0.0
        total_ta = sum(s.trade_amount for s in filtered_stocks)
        avg_ta = total_ta // total if total > 0 else 0
        avg_cr = sum(s.change_rate for s in filtered_stocks) / len(filtered_stocks) if len(filtered_stocks) > 0 else 0.0

        sector_scores.append(SectorScore(
            sector=sector,
            total=total,
            rise_count=rise_count,
            rise_ratio=rise_ratio,
            avg_change_rate=avg_cr,
            avg_trade_amount=avg_ta,
            stocks=filtered_stocks,
        ))

    return sector_scores


async def compute_full_sector_summary(
    all_codes: list[str],
    *,
    trade_prices: dict[str, int],
    trade_amounts: dict[str, int],
    avg_amt_5d: dict[str, int],
    master_stocks_cache: dict,
    sector_map: dict[str, str],
    min_rise_ratio: float = 0.6,
    min_avg_amt_eok: float = 0.0,
    # ── 업종 점수 3단계 가산점 슬라이더 (-100~+100, 기본값 0) — 조정 만점 = 업종 수 × (1 + slider/100) ──
    rise_ratio_slider: int = 0,
    relative_strength_slider: int = 0,
    trade_amount_slider: int = 0,
) -> SectorSummary:
    """
    전체 파이프라인 한 번에 실행.
    engine_bootstrap, engine_sector_confirm, sector_data_provider, telegram_bot에서 이벤트 기반 호출.

    입력 계약: compute_sector_scores와 동일하게 master_stocks_cache·sector_map을 필수 명시 입력으로 받아 전달.
    누락 시 TypeError로 즉시 드러난다 (P20 폴백 금지).

    컷오프(min_rise_ratio)는 calculate_bonus_scores 내부에서 처리 (옵션 C 2패스).

    매수 타겟 생성은 build_buy_targets_from_settings에서 별도 수행.
    """
    # 1. 업종 스코어 계산 (컷오프는 calculate_bonus_scores 내부에서 처리)
    sector_scores = await compute_sector_scores(
        all_codes,
        trade_prices=trade_prices,
        trade_amounts=trade_amounts,
        avg_amt_5d=avg_amt_5d,
        master_stocks_cache=master_stocks_cache,
        sector_map=sector_map,
        min_avg_amt_eok=min_avg_amt_eok,
    )

    # 2. 3단계 누적 가산점 계산 + 컷오프 + 정렬 + 순위 부여
    calculate_bonus_scores(
        sector_scores,
        min_rise_ratio=min_rise_ratio,
        rise_ratio_slider=rise_ratio_slider,
        relative_strength_slider=relative_strength_slider,
        trade_amount_slider=trade_amount_slider,
    )

    return SectorSummary(
        sectors=sector_scores,
        buy_targets=[],
        blocked_targets=[],
    )


def select_top_sector_stocks(
    sector_scores: list,  # list[SectorScore] — calculate_bonus_scores 결과 (정렬됨)
    *,
    max_sectors: int = 3,
) -> list:  # list[tuple[StockScore, SectorScore]]
    """
    업종 단위 선택 종결점.

    is_cutoff_passed=False 업종 제외, max_sectors 개까지 업종의 종목을
    (stock, sector_score) 튜플 리스트로 평탄화. 차단·가산점·정렬 일체 수행 안 함.
    sector_scores 재정렬 금지 — 이미 calculate_bonus_scores에서 순위 부여됨.
    """
    pairs: list = []
    sector_count = 0
    for sc in sector_scores:
        if not sc.is_cutoff_passed:
            continue
        if sector_count >= max_sectors:
            break
        sector_count += 1
        for s in sc.stocks:
            pairs.append((s, sc))
    return pairs
