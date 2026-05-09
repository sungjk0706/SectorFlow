# -*- coding: utf-8 -*-
"""
섹터 강도 스코어링 및 매수 타겟 큐 생성.

sector_mapping.py sector_custom.json 기반 업종 그룹핑:
  1. 전체 종목 코드를 sector_mapping.get_merged_sector() 로 커스텀 업종별 분류
  2. 섹터별 상승 종목 비율 / 평균 등락률 / 총 거래대금 계산
  3. 섹터 강도 순위 정렬
  4. 상위 섹터에서 종목 우선순위 정렬 → 매수 가드 적용 → 최종 타겟 큐 반환

이 모듈은 engine_service 전역 상태를 직접 참조하지 않는다.
호출 측(engine_service)이 필요한 데이터를 인자로 넘긴다 -- 순환 import 없음.
UI(buy_widget) 및 엔진 루프 양쪽에서 호출 가능.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from app.core import sector_mapping
from app.core.logger import get_logger

logger = get_logger("engine")


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class StockScore:
    """섹터 내 개별 종목 스코어."""
    code: str
    name: str
    sector: str
    change_rate: float          # 등락률 (%)
    trade_amount: int           # 당일 거래대금 (원)
    avg_amt_5d: int             # 5일 평균 거래대금 (원, ka10081 백만원×1_000_000 변환 후)
    ratio_5d_pct: float         # 5D거래대금비율 (%) = trade_amount / avg_amt_5d * 100
    strength: float             # 체결강도 (%, -1 = 미수신)
    cur_price: int              # 현재가
    change: int = 0             # 전일 대비 (원)
    market_type: str = ""       # 시장구분 ("0"=코스피, "10"=코스닥, ""=미확인)
    nxt_enable: bool = False    # KRX+NXT 중복상장 여부
    # 가드 결과
    guard_pass: bool = True
    guard_reason: str = ""      # 차단 사유 (빈 문자열 = 통과)
    # 가산점
    boost_score: float = 0.0    # 가산점 합계 (>= 0.0)


@dataclass
class SectorScore:
    """섹터 단위 강도 스코어."""
    sector: str
    total: int                  # 섹터 내 종목 수 (현재가 있는 종목만)
    rise_count: int             # 상승 종목 수 (change_rate > 0)
    rise_ratio: float           # 상승 비율 (0.0~1.0)
    avg_change_rate: float      # 평균 등락률 (%)
    total_trade_amount: int     # 섹터 총 거래대금 (원) — 표시용 (전체 종목 합산)
    avg_ratio_5d_pct: float     # 섹터 평균 5D거래대금비율 (%)
    rank: int = 0               # 강도 순위 (1=최강)
    stocks: list[StockScore] = field(default_factory=list)
    # ── 점수 계산용 (트리밍/필터 후 값) ──
    scored_trade_amount: int = 0        # 가중치 점수 계산에 사용되는 거래대금
    scored_rise_ratio: float = 0.0      # 가중치 점수 계산에 사용되는 상승비율
    # ── 업종 지수 기반 필드 (WS 0U) ──
    industry_code: str = ""             # 매칭된 업종코드 (예: "013")
    industry_up_ratio: float = 0.0      # 업종 상승종목비율 (0.0~1.0, 252/(252+255))
    industry_trade_amount: int = 0      # 업종 거래대금 (백만원, 0U FID 14)
    has_industry_data: bool = False     # 0U 데이터 매칭 여부
    # ── 신규 필드: 가중치 점수 시스템 ──
    final_score: float = 0.0                          # 가중치 최종 점수 (0.0~100.0)
    metric_scores: dict[str, float] = field(default_factory=dict)  # 지표별 정규화 점수


# ──────────────────────────────────────────────────────────────────────────────
# 가산점 계산 (순수 함수)
# ──────────────────────────────────────────────────────────────────────────────


def compute_boost_score(
    stock: StockScore,
    *,
    high_5d_cache: dict[str, int],
    orderbook_cache: dict[str, tuple[int, int]],
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_pct: float = 20.0,
    boost_order_ratio_score: float = 1.0,
) -> float:
    """종목 가산점 합계 계산. 항상 >= 0.0 반환."""
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

    return max(score, 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# 지표 정의 (MetricDef) 및 정규화 함수
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MetricDef:
    """업종 분석 지표 정의."""
    key: str                                    # 고유 키 (예: "total_trade_amount")
    label: str                                  # UI 표시명 (예: "거래대금")
    extract: Callable[[SectorScore], float]     # SectorScore에서 원시값 추출
    default_weight: float                       # 기본 가중치 (모든 지표 합 = 1.0)
    higher_is_better: bool = True               # True: 값이 클수록 좋음


DEFAULT_METRICS: list[MetricDef] = [
    MetricDef(
        key="total_trade_amount",
        label="거래대금",
        extract=lambda sc: float(sc.scored_trade_amount),
        default_weight=0.5,
    ),
    MetricDef(
        key="rise_ratio",
        label="상승종목비율",
        extract=lambda sc: sc.scored_rise_ratio,
        default_weight=0.5,
    ),
]


def normalize_metric(
    values: list[float],
    higher_is_better: bool = True,
) -> list[float]:
    """
    원시값 리스트를 0~100 min-max 정규화 점수로 변환.

    - min-max 선형 보간: score = (v - min) / (max - min) * 100
    - 모든 값이 동일하면 100 반환
    - 1개 업종이면 100 반환
    - higher_is_better=False 이면 역방향: score = (max - v) / (max - min) * 100
    - 소수점 첫째 자리 반올림
    """
    if not values:
        return []
    if len(values) == 1:
        return [100.0]

    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [100.0] * len(values)
    span = hi - lo
    if higher_is_better:
        return [round((v - lo) / span * 100.0, 1) for v in values]
    return [round((hi - v) / span * 100.0, 1) for v in values]


def normalize_weights(
    weights: dict[str, float],
    metrics: list[MetricDef] | None = None,
) -> dict[str, float]:
    """
    가중치 합이 1.0이 되도록 정규화.

    - 등록되지 않은 키는 무시
    - 음수 값은 0으로 클램프
    - 합이 0이면 기본 가중치 사용
    """
    if metrics is None:
        metrics = DEFAULT_METRICS
    # 등록된 키만 필터 + 음수 클램프
    clamped: dict[str, float] = {}
    for m in metrics:
        raw = weights.get(m.key, 0.0)
        clamped[m.key] = max(raw, 0.0)
    total = sum(clamped.values())
    if total == 0.0:
        # 폴백: 기본 가중치 사용
        return {m.key: m.default_weight for m in metrics}
    return {k: v / total for k, v in clamped.items()}


def compute_weighted_scores(
    sector_scores: list[SectorScore],
    metrics: list[MetricDef] | None = None,
    weights: dict[str, float] | None = None,
) -> None:
    """
    각 SectorScore에 정규화 점수 + 가중치 최종 점수를 계산하여 in-place 설정.

    1. 가중치 정규화 (합 = 1.0)
    2. 각 지표별 원시값 추출 → normalize_metric
    3. final_score = Σ(normalized_i × weight_i)
    4. final_score 내림차순 정렬, 동점 시 rise_ratio 정규화 점수로 타이브레이크
    5. rank 부여 (1-based)
    """
    if not sector_scores:
        return

    if metrics is None:
        metrics = DEFAULT_METRICS
    if weights is None:
        weights = {m.key: m.default_weight for m in metrics}

    # 1. 가중치 정규화
    norm_w = normalize_weights(weights, metrics)

    # 2. 각 지표별 원시값 추출 → 정규화 → metric_scores 저장
    for metric in metrics:
        raw_values = [metric.extract(sc) for sc in sector_scores]
        normalized = normalize_metric(raw_values, metric.higher_is_better)
        for sc, norm_val in zip(sector_scores, normalized):
            sc.metric_scores[metric.key] = norm_val

    # 3. final_score 계산
    for sc in sector_scores:
        sc.final_score = round(
            sum(sc.metric_scores.get(m.key, 0.0) * norm_w.get(m.key, 0.0) for m in metrics),
            1,
        )

    # 4. 정렬: final_score 내림차순, 동점 시 rise_ratio 내림차순, 최종 동점 시 업종명 오름차순(결정적 정렬)
    sector_scores.sort(
        key=lambda s: (-s.final_score, -s.metric_scores.get("rise_ratio", 0.0), s.sector),
    )

    # 5. rank 부여 (1-based)
    for i, sc in enumerate(sector_scores):
        sc.rank = i + 1


@dataclass
class BuyTarget:
    """매수 타겟 큐 항목."""
    rank: int                   # 전체 우선순위
    sector_rank: int            # 섹터 순위
    stock: StockScore
    reason: str = ""            # 타겟 선정 이유 요약


@dataclass
class SectorSummary:
    """섹터 스코어링 전체 결과 -- UI·엔진 양쪽에 전달."""
    sectors: list[SectorScore]          # 강도 순위 정렬
    buy_targets: list[BuyTarget]        # 매수 타겟 큐 (가드 통과 종목만)
    blocked_targets: list[BuyTarget]    # 가드 차단 종목 (UI 표시용)
    index_guard_active: bool = False    # 지수 연동 가드 발동 여부 (하나라도 발동)
    index_guard_reason: str = ""        # 발동 사유
    index_guard_kospi_hit: bool = False   # 코스피 가드 발동 여부
    index_guard_kosdaq_hit: bool = False  # 코스닥 가드 발동 여부


# ──────────────────────────────────────────────────────────────────────────────
# 종목 우선순위 정렬 기준
# ──────────────────────────────────────────────────────────────────────────────

SortKey = Literal["strength", "change_rate", "trade_amount"]

_SORT_LABEL: dict[SortKey, str] = {
    "strength":        "체결강도",
    "change_rate":     "등락률",
    "trade_amount":    "거래대금",
}

# 업종 순위 1차 정렬 기준
SectorRankPrimary = Literal["rise_ratio", "total_trade_amount"]

_SECTOR_RANK_LABEL: dict[SectorRankPrimary, str] = {
    "rise_ratio":          "상승비율",
    "total_trade_amount":  "총거래대금",
}

DEFAULT_SECTOR_RANK_PRIMARY: SectorRankPrimary = "rise_ratio"

DEFAULT_SORT_KEYS: list[SortKey] = ["change_rate", "trade_amount", "strength"]


def sort_key_label(key: SortKey) -> str:
    return _SORT_LABEL.get(key, key)


# ──────────────────────────────────────────────────────────────────────────────
# 핵심 계산 함수
# ──────────────────────────────────────────────────────────────────────────────

def compute_sector_scores(
    all_codes: list[str],
    *,
    trade_prices: dict[str, int],
    trade_amounts: dict[str, int],
    avg_amt_5d: dict[str, int],
    strengths: dict[str, str],
    stock_details: dict[str, dict],        # _pending_stock_details
    min_trade_amt_won: float = 0.0,                # 1차 필터: 최소 거래대금 (원 단위, 0=미적용)
    sector_weights: dict[str, float] | None = None,  # 가중치 기반 점수 계산용
    trim_trade_amt_pct: float = 0.0,       # 업종 내 종목 거래대금 트리밍 비율 (%)
    trim_change_rate_pct: float = 0.0,     # 업종 내 종목 등락률 트리밍 비율 (%)
) -> list[SectorScore]:
    """
    섹터별 강도 스코어 계산.

    그룹핑 방식:
      - sector_mapping.get_merged_sector(code) 로 종목코드 → 커스텀 업종 매핑
      - 빈 문자열 반환 종목은 스킵 (미매핑 종목 제외)

    데이터 우선순위:
      현재가: trade_prices(REAL) > stock_details
      거래대금: trade_amounts(FID29 합산 캐시) > stock_details trade_amount/acc_trde_prica
      등락률: stock_details
    """
    # 시장구분 캐시 참조
    from app.services.engine_symbol_utils import get_stock_market as _get_mkt
    from app.services.engine_symbol_utils import is_nxt_enabled as _is_nxt

    # 섹터별 종목 그룹핑 — Custom_Data > Auto_Mapping 우선순위 적용
    sector_groups: dict[str, list[str]] = {}
    for code in all_codes:
        sector_name = sector_mapping.get_merged_sector(code)
        if not sector_name:
            continue  # 미매핑 종목 제외
        if sector_name not in sector_groups:
            sector_groups[sector_name] = []
        sector_groups[sector_name].append(code)

    sector_scores: list[SectorScore] = []

    for sector, codes in sector_groups.items():
        stocks: list[StockScore] = []

        for code in codes:
            # 시세카드(pending_stock_details)에 등록된 종목만 대상
            # → 시세카드를 거치지 않은 종목이 매수후보에 올라가는 것을 방지
            if code not in stock_details:
                continue

            # 현재가 조회
            cur_price = int(trade_prices.get(code, 0) or 0)
            detail = stock_details.get(code, {})

            if cur_price <= 0:
                cur_price = int(detail.get("cur_price", 0) or 0)
            # cur_price 0도 유효한 데이터 -- WS 틱 미수신 상태일 뿐, 스킵하지 않음

            # 등락률
            change_rate = float(detail.get("change_rate", 0.0) or 0.0)

            # 전일 대비 (원)
            change = int(detail.get("change", 0) or 0)

            # 거래대금 (원 단위)
            ta_ws = int(trade_amounts.get(code, 0) or 0)
            ta = ta_ws
            if ta <= 0:
                ta = int(detail.get("trade_amount", 0) or 0)
            if ta <= 0:
                ta = int(detail.get("acc_trde_prica", 0) or 0)

            # 5일 평균 거래대금 (ka10081 백만원 단위 -> 원 단위)
            avg5d_raw = int(avg_amt_5d.get(code, 0) or 0)
            avg5d_won = avg5d_raw * 1_000_000

            # 5D거래대금비율
            ratio_5d = round(ta / avg5d_won * 100.0, 1) if avg5d_won > 0 and ta > 0 else 0.0

            # 체결강도
            st_raw = strengths.get(code) or detail.get("strength") or "-"
            try:
                strength_val = float(str(st_raw).replace("%", "").replace(",", "").strip())
            except (ValueError, TypeError):
                strength_val = -1.0

            # 종목명
            name = (
                detail.get("name")
                or ka_row.get("stk_nm")
                or ka_row.get("hname")
                or code
            )

            stocks.append(StockScore(
                code=code,
                name=str(name),
                sector=sector,
                change_rate=change_rate,
                trade_amount=ta,
                avg_amt_5d=avg5d_won,
                ratio_5d_pct=ratio_5d,
                strength=strength_val,
                cur_price=cur_price,
                change=change,
                market_type=_get_mkt(code) or "",
                nxt_enable=_is_nxt(code),
            ))

        if not stocks:
            continue

        # ── 5일평균거래대금 필터: 업종강도 계산 + 매수후보 모두 적용 ─────────
        if min_trade_amt_won > 0:
            filtered_stocks = [s for s in stocks if s.avg_amt_5d >= min_trade_amt_won]
        else:
            filtered_stocks = stocks

        if not filtered_stocks:
            continue

        # ── 표시용: 전체 종목 기준 실제 값 ─────────────────────────────────
        raw_rise_count = sum(1 for s in filtered_stocks if s.change_rate > 0)
        raw_total = len(filtered_stocks)
        raw_rise_ratio = raw_rise_count / raw_total if raw_total > 0 else 0.0
        raw_total_ta = sum(s.trade_amount for s in filtered_stocks)

        # ── 점수 계산용: 트리밍 후 값 ────────────────────────────────────────
        # ── 등락률 트리밍: 상하위 N% 종목 제외 후 상승비율 계산 ──
        _trim_cr_pct = max(trim_change_rate_pct, 0.0)
        if _trim_cr_pct > 0 and len(filtered_stocks) > 0:
            _n = len(filtered_stocks)
            _trim_cnt = round(_n * _trim_cr_pct / 100)
            if _trim_cnt * 2 < _n:
                _sorted_cr = sorted(filtered_stocks, key=lambda s: s.change_rate)
                _cr_trimmed = _sorted_cr[_trim_cnt : _n - _trim_cnt]
                scored_rise_count = sum(1 for s in _cr_trimmed if s.change_rate > 0)
                scored_total = len(_cr_trimmed)
                scored_rise_ratio = scored_rise_count / scored_total if scored_total > 0 else 0.0
            else:
                scored_rise_ratio = raw_rise_ratio
        else:
            scored_rise_ratio = raw_rise_ratio
        avg_cr = sum(s.change_rate for s in filtered_stocks) / len(filtered_stocks) if len(filtered_stocks) > 0 else 0.0
        # ── 거래대금 트리밍: 상하위 N% 종목 제외 후 합산 ──
        _trim_ta_pct = max(trim_trade_amt_pct, 0.0)
        if _trim_ta_pct > 0 and len(filtered_stocks) > 0:
            _n = len(filtered_stocks)
            _trim_cnt = round(_n * _trim_ta_pct / 100)
            if _trim_cnt * 2 < _n:
                _sorted_ta = sorted(filtered_stocks, key=lambda s: s.trade_amount)
                _ta_trimmed = _sorted_ta[_trim_cnt : _n - _trim_cnt]
                scored_ta = sum(s.trade_amount for s in _ta_trimmed)
            else:
                scored_ta = raw_total_ta
        else:
            scored_ta = raw_total_ta
        avg_r5d = sum(s.ratio_5d_pct for s in filtered_stocks) / len(filtered_stocks) if len(filtered_stocks) > 0 else 0.0

        sector_scores.append(SectorScore(
            sector=sector,
            total=raw_total,
            rise_count=raw_rise_count,
            rise_ratio=raw_rise_ratio,
            avg_change_rate=avg_cr,
            total_trade_amount=raw_total_ta,
            avg_ratio_5d_pct=avg_r5d,
            stocks=filtered_stocks,
            scored_trade_amount=scored_ta,
            scored_rise_ratio=scored_rise_ratio,
        ))

    # 가중치 기반 점수 계산 + 정렬 + 순위 부여
    compute_weighted_scores(sector_scores, weights=sector_weights)

    return sector_scores


def apply_stock_guards(
    stock: StockScore,
    *,
    block_rise_pct: float = 7.0,
    block_fall_pct: float = 7.0,
    min_strength: float = 0.0,
) -> StockScore:
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


def check_index_guard(
    latest_index: dict[str, dict],
    *,
    kospi_on: bool = False,
    kosdaq_on: bool = False,
    kospi_drop: float = 2.0,
    kosdaq_drop: float = 2.0,
) -> tuple[bool, str, bool, bool]:
    """
    지수 연동 가드 체크.
    반환: (발동여부, 사유문자열, 코스피발동, 코스닥발동)

    kospi_on / kosdaq_on: 개별 지수 가드 활성화 여부.
    """
    _kospi_on = kospi_on
    _kosdaq_on = kosdaq_on

    if not _kospi_on and not _kosdaq_on:
        return False, "", False, False

    kospi = latest_index.get("001", {})
    kosdaq = latest_index.get("101", {})
    kospi_rate = float(kospi.get("rate", 0.0) or 0.0)
    kosdaq_rate = float(kosdaq.get("rate", 0.0) or 0.0)

    kospi_hit = _kospi_on and kospi_rate <= -abs(kospi_drop)
    kosdaq_hit = _kosdaq_on and kosdaq_rate <= -abs(kosdaq_drop)

    triggered = kospi_hit or kosdaq_hit

    if not triggered:
        return False, "", False, False

    parts = []
    if kospi_hit:
        parts.append("코스피")
    if kosdaq_hit:
        parts.append("코스닥")
    reason = " / ".join(parts)
    return True, reason, kospi_hit, kosdaq_hit


def build_buy_targets(
    sector_scores: list[SectorScore],
    *,
    sort_keys: list[SortKey] | None = None,
    min_rise_ratio: float = 0.6,
    block_rise_pct: float = 7.0,
    block_fall_pct: float = 7.0,
    min_strength: float = 0.0,
    index_guard_kospi_hit: bool = False,
    index_guard_kosdaq_hit: bool = False,
    index_guard_reason: str = "",
    latest_index: dict[str, dict] | None = None,
    max_sectors: int = 3,
    # ── 가산점 관련 파라미터 (기본값 = 모든 가산점 OFF → boost_score=0.0) ──
    high_5d_cache: dict[str, int] | None = None,
    orderbook_cache: dict[str, tuple[int, int]] | None = None,
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_pct: float = 20.0,
    boost_order_ratio_score: float = 1.0,
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
    effective_keys: list[SortKey] = list(sort_keys) if sort_keys else ["change_rate"]

    buy_targets: list[BuyTarget] = []
    blocked_targets: list[BuyTarget] = []
    sector_count = 0

    # 모든 섹터 종목을 하나의 풀로 모은 뒤 '설정값에 가까운 순서'로 정렬
    all_stocks: list[tuple[StockScore, SectorScore]] = []

    for sc in sector_scores:
        # 순위 없는 업종(rank=0)은 매수대상 카운트에서 제외
        if sc.rank == 0:
            continue
        if sector_count >= max_sectors:
            break
        sector_count += 1

        # 개별 종목 가드 적용
        for s in sc.stocks:
            apply_stock_guards(
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
    for s, _ in all_stocks:
        s.boost_score = compute_boost_score(
            s,
            high_5d_cache=_h5d,
            orderbook_cache=_obc,
            boost_high_on=boost_high_on,
            boost_high_score=boost_high_score,
            boost_order_ratio_on=boost_order_ratio_on,
            boost_order_ratio_pct=boost_order_ratio_pct,
            boost_order_ratio_score=boost_order_ratio_score,
        )

    def _sort_value(s: "StockScore", key: SortKey) -> float:
        if key == "strength":
            return s.strength
        elif key == "trade_amount":
            return float(s.trade_amount)
        else:  # change_rate
            return s.change_rate

    def _proximity_key(pair: tuple["StockScore", "SectorScore"]) -> tuple:
        s, sc = pair
        is_blocked = 0 if s.guard_pass else 1
        return (is_blocked, -s.boost_score) + tuple(-_sort_value(s, k) for k in effective_keys)

    all_stocks.sort(key=_proximity_key)

    primary_label = sort_key_label(effective_keys[0]) if effective_keys else sort_key_label("change_rate")
    pass_rank = 1
    blocked_rank = 1
    for stock, sc in all_stocks:
        # 종목별 시장 가드: 해당 시장이 급락했을 때만 차단
        _stock_guard_hit = False
        if stock.market_type == "0" and index_guard_kospi_hit:
            _stock_guard_hit = True
        elif stock.market_type == "10" and index_guard_kosdaq_hit:
            _stock_guard_hit = True
        elif not stock.market_type and (index_guard_kospi_hit or index_guard_kosdaq_hit):
            # 시장 미확인 종목은 안전하게 차단
            _stock_guard_hit = True

        if _stock_guard_hit:
            target = BuyTarget(
                rank=blocked_rank,
                sector_rank=sc.rank,
                stock=stock,
                reason=index_guard_reason,
            )
            blocked_targets.append(target)
            blocked_rank += 1
        elif not stock.guard_pass:
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

    index_guard_active = index_guard_kospi_hit or index_guard_kosdaq_hit
    return SectorSummary(
        sectors=sector_scores,
        buy_targets=buy_targets,
        blocked_targets=blocked_targets,
        index_guard_active=index_guard_active,
        index_guard_reason=index_guard_reason,
        index_guard_kospi_hit=index_guard_kospi_hit,
        index_guard_kosdaq_hit=index_guard_kosdaq_hit,
    )


# ──────────────────────────────────────────────────────────────────────────────
# engine_service 에서 호출하는 통합 진입점
# ──────────────────────────────────────────────────────────────────────────────

def compute_full_sector_summary(
    all_codes: list[str],
    *,
    trade_prices: dict[str, int],
    trade_amounts: dict[str, int],
    avg_amt_5d: dict[str, int],
    strengths: dict[str, str],
    stock_details: dict[str, dict],
    latest_index: dict[str, dict],
    # 설정값
    sort_keys: list[SortKey] | None = None,
    min_rise_ratio: float = 0.6,
    block_rise_pct: float = 7.0,
    block_fall_pct: float = 7.0,
    min_strength: float = 0.0,
    min_trade_amt_won: float = 0.0,
    index_guard_kospi_on: bool = False,
    index_guard_kosdaq_on: bool = False,
    index_kospi_drop: float = 2.0,
    index_kosdaq_drop: float = 2.0,
    max_sectors: int = 3,
    sector_weights: dict[str, float] | None = None,
    trim_trade_amt_pct: float = 0.0,
    trim_change_rate_pct: float = 0.0,
    # ── 가산점 관련 파라미터 (pass-through → build_buy_targets) ──
    high_5d_cache: dict[str, int] | None = None,
    orderbook_cache: dict[str, tuple[int, int]] | None = None,
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_pct: float = 20.0,
    boost_order_ratio_score: float = 1.0,
) -> SectorSummary:
    """
    전체 파이프라인 한 번에 실행.
    engine_service 또는 buy_widget 폴링에서 호출.

    sector_mapping.get_merged_sector() 기반 커스텀 업종 그룹핑.
    """
    # 1. 섹터 스코어 계산
    sector_scores = compute_sector_scores(
        all_codes,
        trade_prices=trade_prices,
        trade_amounts=trade_amounts,
        avg_amt_5d=avg_amt_5d,
        strengths=strengths,
        stock_details=stock_details,
        min_trade_amt_won=min_trade_amt_won,
        sector_weights=sector_weights,
        trim_trade_amt_pct=trim_trade_amt_pct,
        trim_change_rate_pct=trim_change_rate_pct,
    )

    # ── 업종 컷오프: 상승비율 min_rise_ratio 미만 업종은 순위 없음(rank=0) ──
    if min_rise_ratio > 0:
        pass_sectors = [sc for sc in sector_scores if sc.rise_ratio >= min_rise_ratio]
        fail_sectors = [sc for sc in sector_scores if sc.rise_ratio < min_rise_ratio]
        # pass 그룹에만 순위 부여 (1부터)
        for i, sc in enumerate(pass_sectors):
            sc.rank = i + 1
        # fail 그룹은 순위 없음 (0)
        for sc in fail_sectors:
            sc.rank = 0
        # 표시 순서: pass 먼저, fail은 뒤에
        sector_scores = pass_sectors + fail_sectors

    # 2. 지수 가드 체크
    index_guard_active, index_guard_reason, _kospi_hit, _kosdaq_hit = check_index_guard(
        latest_index,
        kospi_on=index_guard_kospi_on,
        kosdaq_on=index_guard_kosdaq_on,
        kospi_drop=index_kospi_drop,
        kosdaq_drop=index_kosdaq_drop,
    )

    # 3. 매수 타겟 큐 생성
    summary = build_buy_targets(
        sector_scores,
        sort_keys=sort_keys,
        min_rise_ratio=min_rise_ratio,
        block_rise_pct=block_rise_pct,
        block_fall_pct=block_fall_pct,
        min_strength=min_strength,
        index_guard_kospi_hit=_kospi_hit,
        index_guard_kosdaq_hit=_kosdaq_hit,
        index_guard_reason=index_guard_reason,
        latest_index=latest_index,
        max_sectors=max_sectors,
        # 가산점 pass-through
        high_5d_cache=high_5d_cache,
        orderbook_cache=orderbook_cache,
        boost_high_on=boost_high_on,
        boost_high_score=boost_high_score,
        boost_order_ratio_on=boost_order_ratio_on,
        boost_order_ratio_pct=boost_order_ratio_pct,
        boost_order_ratio_score=boost_order_ratio_score,
    )

    return summary
