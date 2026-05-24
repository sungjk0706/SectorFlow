# -*- coding: utf-8 -*-
"""SectorSummary 영속성 캐시 - 업종순위/매수후보 데이터 저장 및 복원"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from backend.app.services.engine_sector_score import (
    SectorSummary,
    SectorScore,
    StockScore,
    BuyTarget,
)
from backend.app.db.cache_db import get_kv, set_kv

logger = logging.getLogger(__name__)


def save_sector_summary_cache(summary: SectorSummary) -> None:
    """SectorSummary를 JSON 파일에 저장"""
    if summary is None:
        return
    try:
        data = {
            "sectors": [_sector_score_to_dict(s) for s in summary.sectors],
            "buy_targets": [_buy_target_to_dict(t) for t in summary.buy_targets],
            "blocked_targets": [_buy_target_to_dict(t) for t in summary.blocked_targets],
            "index_guard_active": summary.index_guard_active,
            "index_guard_reason": summary.index_guard_reason,
            "index_guard_kospi_hit": summary.index_guard_kospi_hit,
            "index_guard_kosdaq_hit": summary.index_guard_kosdaq_hit,
        }
        set_kv("sector_summary_cache", data)
        logger.debug("[SectorSummaryCache] SQLite 저장 완료")
    except Exception as e:
        logger.error(f"[SectorSummaryCache] SQLite 저장 실패: {e}", exc_info=True)


def load_sector_summary_cache() -> Optional[SectorSummary]:
    """SQLite에서 SectorSummary 복원"""
    try:
        data = get_kv("sector_summary_cache")
        if not data:
            return None
        
        sectors = [_dict_to_sector_score(s) for s in data.get("sectors", [])]
        buy_targets = [_dict_to_buy_target(t) for t in data.get("buy_targets", [])]
        blocked_targets = [_dict_to_buy_target(t) for t in data.get("blocked_targets", [])]
        
        summary = SectorSummary(
            sectors=sectors,
            buy_targets=buy_targets,
            blocked_targets=blocked_targets,
            index_guard_active=data.get("index_guard_active", False),
            index_guard_reason=data.get("index_guard_reason", ""),
            index_guard_kospi_hit=data.get("index_guard_kospi_hit", False),
            index_guard_kosdaq_hit=data.get("index_guard_kosdaq_hit", False),
        )
        logger.info(f"[SectorSummaryCache] SQLite 복원 완료 - sectors: {len(sectors)}, buy_targets: {len(buy_targets)}")
        return summary
    except Exception as e:
        logger.error(f"[SectorSummaryCache] SQLite 복원 실패: {e}", exc_info=True)
        return None


def _stock_score_to_dict(stock: StockScore) -> dict:
    """StockScore를 dict로 변환"""
    return {
        "code": stock.code,
        "name": stock.name,
        "sector": stock.sector,
        "change_rate": stock.change_rate,
        "trade_amount": stock.trade_amount,
        "avg_amt_5d": stock.avg_amt_5d,
        "ratio_5d_pct": stock.ratio_5d_pct,
        "strength": stock.strength,
        "cur_price": stock.cur_price,
        "change": stock.change,
        "market_type": stock.market_type,
        "nxt_enable": stock.nxt_enable,
        "guard_pass": stock.guard_pass,
        "guard_reason": stock.guard_reason,
        "boost_score": stock.boost_score,
    }


def _dict_to_stock_score(data: dict) -> StockScore:
    """dict를 StockScore로 변환"""
    return StockScore(
        code=data.get("code", ""),
        name=data.get("name", ""),
        sector=data.get("sector", ""),
        change_rate=data.get("change_rate", 0.0),
        trade_amount=data.get("trade_amount", 0),
        avg_amt_5d=data.get("avg_amt_5d", 0),
        ratio_5d_pct=data.get("ratio_5d_pct", 0.0),
        strength=data.get("strength", -1.0),
        cur_price=data.get("cur_price", 0),
        change=data.get("change", 0),
        market_type=data.get("market_type", ""),
        nxt_enable=data.get("nxt_enable", False),
        guard_pass=data.get("guard_pass", True),
        guard_reason=data.get("guard_reason", ""),
        boost_score=data.get("boost_score", 0.0),
    )


def _sector_score_to_dict(sector: SectorScore) -> dict:
    """SectorScore를 dict로 변환"""
    return {
        "sector": sector.sector,
        "total": sector.total,
        "rise_count": sector.rise_count,
        "rise_ratio": sector.rise_ratio,
        "avg_change_rate": sector.avg_change_rate,
        "total_trade_amount": sector.total_trade_amount,
        "avg_ratio_5d_pct": sector.avg_ratio_5d_pct,
        "rank": sector.rank,
        "stocks": [_stock_score_to_dict(s) for s in sector.stocks],
        "scored_trade_amount": sector.scored_trade_amount,
        "scored_rise_ratio": sector.scored_rise_ratio,
        "industry_code": sector.industry_code,
        "industry_up_ratio": sector.industry_up_ratio,
        "industry_trade_amount": sector.industry_trade_amount,
        "has_industry_data": sector.has_industry_data,
        "final_score": sector.final_score,
        "metric_scores": sector.metric_scores,
    }


def _dict_to_sector_score(data: dict) -> SectorScore:
    """dict를 SectorScore로 변환"""
    stocks = [_dict_to_stock_score(s) for s in data.get("stocks", [])]
    return SectorScore(
        sector=data.get("sector", ""),
        total=data.get("total", 0),
        rise_count=data.get("rise_count", 0),
        rise_ratio=data.get("rise_ratio", 0.0),
        avg_change_rate=data.get("avg_change_rate", 0.0),
        total_trade_amount=data.get("total_trade_amount", 0),
        avg_ratio_5d_pct=data.get("avg_ratio_5d_pct", 0.0),
        rank=data.get("rank", 0),
        stocks=stocks,
        scored_trade_amount=data.get("scored_trade_amount", 0),
        scored_rise_ratio=data.get("scored_rise_ratio", 0.0),
        industry_code=data.get("industry_code", ""),
        industry_up_ratio=data.get("industry_up_ratio", 0.0),
        industry_trade_amount=data.get("industry_trade_amount", 0),
        has_industry_data=data.get("has_industry_data", False),
        final_score=data.get("final_score", 0.0),
        metric_scores=data.get("metric_scores", {}),
    )


def _buy_target_to_dict(target: BuyTarget) -> dict:
    """BuyTarget를 dict로 변환"""
    return {
        "rank": target.rank,
        "sector_rank": target.sector_rank,
        "stock": _stock_score_to_dict(target.stock),
        "reason": target.reason,
    }


def _dict_to_buy_target(data: dict) -> BuyTarget:
    """dict를 BuyTarget로 변환"""
    stock_data = data.get("stock", {})
    stock = _dict_to_stock_score(stock_data)
    return BuyTarget(
        rank=data.get("rank", 0),
        sector_rank=data.get("sector_rank", 0),
        stock=stock,
        reason=data.get("reason", ""),
    )
