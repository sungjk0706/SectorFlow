"""sector_stock_cache.py 단위 테스트 — assemble_filter_summary 표시 문자열 조립.

순수 함수이므로 mock 불필요. 상위 8개 표시 동작 검증 (P21 사용자 투명성).
"""
from __future__ import annotations

import json

from backend.app.core.sector_stock_cache import assemble_filter_summary


class TestAssembleFilterSummary:
    def test_empty_meta_returns_default(self):
        assert assemble_filter_summary("", 0) == ""
        assert assemble_filter_summary("", 100) == "매매 가능 100종목"

    def test_meta_without_top_reasons(self):
        meta = json.dumps({
            "raw_rows": 100, "unique_codes": 100,
            "excluded_count": 30, "pct": 30.0,
            "duplicate_count": 0, "top_reasons": [],
        })
        result = assemble_filter_summary(meta, 70)
        assert "전체 100종목 → 매매 가능 70종목 (제외 30종목, 30%)" == result

    def test_top_reasons_all_displayed_when_under_8(self):
        meta = json.dumps({
            "unique_codes": 100, "excluded_count": 30, "pct": 30.0,
            "top_reasons": [
                {"k": "ETF", "v": 10},
                {"k": "관리종목", "v": 5},
            ],
        })
        result = assemble_filter_summary(meta, 70)
        assert "주요 제외: ETF 10개, 관리종목 5개" in result

    def test_top_reasons_truncated_to_8(self):
        """meta에 10개 사유가 있어도 표시는 상위 8개만."""
        reasons = [{"k": f"사유{i}", "v": 100 - i} for i in range(10)]
        meta = json.dumps({
            "unique_codes": 100, "excluded_count": 50, "pct": 50.0,
            "top_reasons": reasons,
        })
        result = assemble_filter_summary(meta, 50)
        # 8개만 표시 — 사유0~사유7
        assert "사유7 93개" in result
        assert "사유8" not in result
        assert "사유9" not in result

    def test_pct_rounding(self):
        meta = json.dumps({
            "unique_codes": 4295, "excluded_count": 3014, "pct": 70.2,
            "top_reasons": [{"k": "ETF", "v": 1160}],
        })
        result = assemble_filter_summary(meta, 1281)
        assert "(제외 3014종목, 70%)" in result
