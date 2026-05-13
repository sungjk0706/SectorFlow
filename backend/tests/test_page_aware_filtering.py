# -*- coding: utf-8 -*-
"""Property-based test: Page-Aware Filtering (Property 17).

Feature: hts-level-optimization, Property 17: 페이지별 필터링 정확성

Validates that _is_code_relevant_for_page returns the correct boolean result
based on page-specific rules for any combination of active_page and stock code.

Rules:
- sector-analysis: layout 종목 + pending 종목만 True
- buy-target: buyTargets + blockedTargets 종목만 True (캐시 미초기화 시 True 폴백)
- sell-position: positions 종목만 True
- profit-overview / settings / buy-settings / sell-settings / general-settings / sector-custom: always False
- unknown page or no active_page: always True (safe fallback)

**Validates: Requirements 17.4, 17.5, 17.6, 17.7, 17.8**
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Pre-import: mock engine_service to avoid import chain issues ─────────────
# engine_service → trading → telegram uses `dict | None` (Python 3.10+ syntax)
# We create a minimal mock module to satisfy the lazy imports in _is_code_relevant_for_page

_mock_es = types.ModuleType("app.services.engine_service")
_mock_es._pending_stock_details = {}  # type: ignore[attr-defined]
_mock_es._sector_summary_cache = None  # type: ignore[attr-defined]
_mock_es._positions = []  # type: ignore[attr-defined]
_mock_es._sector_stock_layout = []  # type: ignore[attr-defined]

# Register mock before any import that might trigger the chain
if "app.services.engine_service" not in sys.modules:
    sys.modules["app.services.engine_service"] = _mock_es

from hypothesis import given, settings
from hypothesis import strategies as st

import app.services.engine_account_notify as ean
from app.web.ws_manager import WSManager


# ── Strategies ───────────────────────────────────────────────────────────────

# Generate realistic 6-digit stock codes (Korean market style)
stock_code_strategy = st.from_regex(r"[0-9]{6}", fullmatch=True)

# Known page identifiers
KNOWN_PAGES = [
    "sector-analysis",
    "buy-target",
    "sell-position",
    "profit-overview",
    "settings",
    "buy-settings",
    "sell-settings",
    "general-settings",
    "sector-custom",
]

# Pages that always return False
FALSE_PAGES = frozenset({
    "profit-overview",
    "settings",
    "buy-settings",
    "sell-settings",
    "general-settings",
    "sector-custom",
})

# Generate unknown page names (not in KNOWN_PAGES)
unknown_page_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=20,
).filter(lambda p: p not in KNOWN_PAGES)


# ── Minimal mock for SectorSummary / BuyTarget / StockScore ──────────────────

@dataclass
class _MockStockScore:
    code: str
    name: str = "테스트"
    sector: str = "테스트업종"
    change_rate: float = 0.0
    trade_amount: int = 0
    avg_amt_5d: int = 0
    ratio_5d_pct: float = 0.0
    strength: float = 0.0
    cur_price: int = 10000


@dataclass
class _MockBuyTarget:
    rank: int = 1
    sector_rank: int = 1
    stock: _MockStockScore = None  # type: ignore

    def __post_init__(self):
        if self.stock is None:
            self.stock = _MockStockScore(code="000000")


@dataclass
class _MockSectorSummary:
    buy_targets: list = None  # type: ignore
    blocked_targets: list = None  # type: ignore
    sectors: list = None  # type: ignore

    def __post_init__(self):
        if self.buy_targets is None:
            self.buy_targets = []
        if self.blocked_targets is None:
            self.blocked_targets = []
        if self.sectors is None:
            self.sectors = []


# ── Property 17: Page-Aware Filtering ────────────────────────────────────────


@given(
    code=stock_code_strategy,
    layout_codes=st.lists(stock_code_strategy, min_size=0, max_size=30),
    pending_codes=st.lists(stock_code_strategy, min_size=0, max_size=10),
)
@settings(max_examples=200, deadline=None)
def test_sector_analysis_page_filters_by_layout_and_pending(
    code: str,
    layout_codes: list[str],
    pending_codes: list[str],
):
    """Property 17: sector-analysis 페이지는 layout 종목 + pending 종목만 True.

    **Validates: Requirements 17.4**
    """
    mgr = WSManager()

    # Set up state on the mock engine_service module
    layout_code_set = set(layout_codes)
    pending_stock_details = {c: {"status": "active"} for c in pending_codes}

    # Expected: code in layout_code_set OR code in pending_stock_details
    expected = code in layout_code_set or code in pending_stock_details

    # Directly set module-level state (the function uses lazy imports)
    original_layout = ean._layout_code_set
    original_pending = _mock_es._pending_stock_details
    try:
        ean._layout_code_set = layout_code_set
        _mock_es._pending_stock_details = pending_stock_details
        result = mgr._is_code_relevant_for_page("sector-analysis", code)
    finally:
        ean._layout_code_set = original_layout
        _mock_es._pending_stock_details = original_pending

    assert result == expected, (
        f"sector-analysis: code={code}, layout={layout_codes}, "
        f"pending={pending_codes}, expected={expected}, got={result}"
    )


@given(
    code=stock_code_strategy,
    buy_target_codes=st.lists(stock_code_strategy, min_size=0, max_size=20),
    blocked_target_codes=st.lists(stock_code_strategy, min_size=0, max_size=10),
)
@settings(max_examples=200, deadline=None)
def test_buy_target_page_filters_by_buy_targets(
    code: str,
    buy_target_codes: list[str],
    blocked_target_codes: list[str],
):
    """Property 17: buy-target 페이지는 buyTargets + blockedTargets 종목만 True.

    **Validates: Requirements 17.5**
    """
    mgr = WSManager()

    # Build mock SectorSummary with buy_targets and blocked_targets
    buy_targets = [_MockBuyTarget(stock=_MockStockScore(code=c)) for c in buy_target_codes]
    blocked_targets = [_MockBuyTarget(stock=_MockStockScore(code=c)) for c in blocked_target_codes]
    mock_ss = _MockSectorSummary(buy_targets=buy_targets, blocked_targets=blocked_targets)

    # Expected: code in buy_target_codes OR code in blocked_target_codes
    expected = code in buy_target_codes or code in blocked_target_codes

    original_ss = _mock_es._sector_summary_cache
    try:
        _mock_es._sector_summary_cache = mock_ss
        result = mgr._is_code_relevant_for_page("buy-target", code)
    finally:
        _mock_es._sector_summary_cache = original_ss

    assert result == expected, (
        f"buy-target: code={code}, buy_targets={buy_target_codes}, "
        f"blocked={blocked_target_codes}, expected={expected}, got={result}"
    )


@given(
    code=stock_code_strategy,
)
@settings(max_examples=100, deadline=None)
def test_buy_target_page_fallback_when_cache_none(
    code: str,
):
    """Property 17: buy-target 페이지에서 캐시 미초기화 시 True 반환 (안전 폴백).

    **Validates: Requirements 17.5**
    """
    mgr = WSManager()

    original_ss = _mock_es._sector_summary_cache
    try:
        _mock_es._sector_summary_cache = None
        result = mgr._is_code_relevant_for_page("buy-target", code)
    finally:
        _mock_es._sector_summary_cache = original_ss

    assert result is True, (
        f"buy-target with None cache should return True (safe fallback), got {result}"
    )


@given(
    code=stock_code_strategy,
    position_codes=st.lists(stock_code_strategy, min_size=0, max_size=30),
)
@settings(max_examples=200, deadline=None)
def test_sell_position_page_filters_by_positions(
    code: str,
    position_codes: list[str],
):
    """Property 17: sell-position 페이지는 positions 종목만 True.

    **Validates: Requirements 17.6**
    """
    mgr = WSManager()

    # Build positions code set (already normalized 6-digit codes)
    positions_code_set = set(position_codes)

    # Expected: code in positions_code_set
    expected = code in positions_code_set

    original_set = ean._positions_code_set
    try:
        ean._positions_code_set = positions_code_set
        result = mgr._is_code_relevant_for_page("sell-position", code)
    finally:
        ean._positions_code_set = original_set

    assert result == expected, (
        f"sell-position: code={code}, positions={position_codes}, "
        f"expected={expected}, got={result}"
    )


@given(
    code=stock_code_strategy,
    page=st.sampled_from(list(FALSE_PAGES)),
)
@settings(max_examples=200, deadline=None)
def test_non_realdata_pages_always_return_false(
    code: str,
    page: str,
):
    """Property 17: profit-overview / settings 계열 페이지는 항상 False.

    **Validates: Requirements 17.7, 17.8**
    """
    mgr = WSManager()

    result = mgr._is_code_relevant_for_page(page, code)

    assert result is False, (
        f"Page '{page}' should always return False for any code, "
        f"but got True for code={code}"
    )


@given(
    code=stock_code_strategy,
    page=unknown_page_strategy,
)
@settings(max_examples=200, deadline=None)
def test_unknown_page_always_returns_true(
    code: str,
    page: str,
):
    """Property 17: 알 수 없는 페이지는 항상 True (안전 폴백).

    **Validates: Requirements 17.8**
    """
    mgr = WSManager()

    result = mgr._is_code_relevant_for_page(page, code)

    assert result is True, (
        f"Unknown page '{page}' should always return True (safe fallback), "
        f"but got False for code={code}"
    )
