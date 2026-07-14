# -*- coding: utf-8 -*-
"""
업종 관련 데이터 모델.

순환 import 방지를 위해 dataclass와 상수를 별도 파일로 분리.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
@dataclass
class StockScore:
    """업종 내 개별 종목 스코어."""
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
    trade_amount_rank: int = -1 # 매수 후보 간 거래대금 순위 (0=1위, -1=미산정/비활성)


@dataclass
class SectorScore:
    """업종 단위 강도 스코어."""
    sector: str
    total: int                  # 업종 내 종목 수 (현재가 있는 종목만)
    rise_count: int             # 상승 종목 수 (change_rate > 0)
    rise_ratio: float           # 상승 비율 (0.0~1.0)
    avg_change_rate: float      # 평균 등락률 (%)
    avg_trade_amount: int       # 업종 평균 거래대금 (원)
    avg_ratio_5d_pct: float     # 업종 평균 5D거래대금비율 (%)
    rank: int = 0               # 강도 순위 (1=최강) — 모든 업종에 순위 부여, 컷오프 미달은 is_cutoff_passed=False로 구분
    is_cutoff_passed: bool = True  # 컷오프(min_rise_ratio) 통과 여부 — rank와 분리된 진실 소스 (P10)
    stocks: list[StockScore] = field(default_factory=list)
    # ── 3단계 누적 가산점 (만점 = 업종 수 × 슬라이더 비율, 가변) ──
    final_score: float = 0.0                  # 종합 가산점 = 1차 + 2차 + 3차 (float, 만점 가변)
    bonus_rise_ratio: float = 0.0             # 1차 가산점: 업종 간 상승비율 순위 → tiered (float)
    bonus_relative_strength: float = 0.0      # 2차 가산점: 통과 업종 종목들 가중 순위 합 → tiered (float)
    bonus_trade_amount: float = 0.0           # 3차 가산점: 업종 간 거래대금 순위 → tiered (float)


@dataclass
class BuyTarget:
    """매수 타겟 큐 항목."""
    rank: int                   # 전체 우선순위
    sector_rank: int            # 업종 순위
    stock: StockScore
    reason: str = ""            # 타겟 선정 이유 요약


@dataclass
class SectorSummary:
    """업종 스코어링 전체 결과 -- UI·엔진 양쪽에 전달."""
    sectors: list[SectorScore]          # 강도 순위 정렬
    buy_targets: list[BuyTarget]        # 매수 타겟 큐 (가드 통과 종목만)
    blocked_targets: list[BuyTarget]    # 가드 차단 종목 (UI 표시용)
    version: int = 1                    # 버전 관리 필드 (캐시 갱신 감지용)


# ──────────────────────────────────────────────────────────────────────────────
# 종목 우선순위 정렬 기준
# ──────────────────────────────────────────────────────────────────────────────

SortKey = Literal["strength", "change_rate", "trade_amount"]

_SORT_LABEL: dict[SortKey, str] = {
    "strength":        "체결강도",
    "change_rate":     "등락률",
    "trade_amount":    "거래대금",
}

DEFAULT_SORT_KEYS: list[SortKey] = ["change_rate", "trade_amount", "strength"]
