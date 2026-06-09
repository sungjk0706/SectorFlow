from __future__ import annotations
# -*- coding: utf-8 -*-
"""
섹터 관련 데이터 모델.

순환 import 방지를 위해 dataclass와 상수를 별도 파일로 분리.
"""

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Literal


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
    avg_amt_5d: int             # 5일 평균 거래대금 (억 단위)
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
    scored_trade_amount: int = 0        # 가중치 점수 계산에 사용되는 거래대금 평균 (원)
    scored_rise_ratio: float = 0.0      # 가중치 점수 계산에 사용되는 상승비율
    # ── 신규 필드: 가중치 점수 시스템 ──
    final_score: float = 0.0                          # 가중치 최종 점수 (0.0~100.0)
    metric_scores: dict[str, float] = field(default_factory=dict)  # 지표별 정규화 점수


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
    is_skeleton_mode: bool = False     # 스켈레톤 캐시 모드 여부 (실시간 틱 기반 증분 연산용)
    version: int = 1                    # 버전 관리 필드 (캐시 갱신 감지용)


# ──────────────────────────────────────────────────────────────────────────────
# 지표 정의 (MetricDef)
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
