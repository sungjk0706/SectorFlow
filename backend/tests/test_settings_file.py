"""settings_file.py 단위 테스트 — 마이그레이션 로직 검증."""
from __future__ import annotations

from backend.app.core.settings_file import (
    migrate_rank_primary_to_weights,
    _migrate_sector_weights,
)


# ── migrate_rank_primary_to_weights ─────────────────────────────────────────────

class TestMigrateRankPrimaryToWeights:
    def test_total_trade_amount_primary(self):
        result = migrate_rank_primary_to_weights("total_trade_amount")
        assert result == {"total_trade_amount": 0.7, "rise_ratio": 0.3}

    def test_rise_ratio_primary(self):
        result = migrate_rank_primary_to_weights("rise_ratio")
        assert result == {"rise_ratio": 0.7, "total_trade_amount": 0.3}

    def test_unknown_primary_returns_default(self):
        result = migrate_rank_primary_to_weights("unknown")
        assert result == {"total_trade_amount": 0.5, "rise_ratio": 0.5}

    def test_empty_string_returns_default(self):
        result = migrate_rank_primary_to_weights("")
        assert result == {"total_trade_amount": 0.5, "rise_ratio": 0.5}


# ── _migrate_sector_weights ──────────────────────────────────────────────────────

class TestMigrateSectorWeights:
    def test_already_has_sector_weights_no_migration(self):
        merged = {"sector_weights": {"rise_ratio": 0.6, "total_trade_amount": 0.4}}
        raw_data = {"sector_weights": {"rise_ratio": 0.6, "total_trade_amount": 0.4}}
        result, dirty = _migrate_sector_weights(merged, raw_data)
        assert dirty is False
        assert result is merged

    def test_migrate_from_rank_primary_total_trade_amount(self):
        merged = {}
        raw_data = {"sector_rank_primary": "total_trade_amount"}
        result, dirty = _migrate_sector_weights(merged, raw_data)
        assert dirty is True
        assert result["sector_weights"] == {"total_trade_amount": 0.7, "rise_ratio": 0.3}

    def test_migrate_from_rank_primary_rise_ratio(self):
        merged = {}
        raw_data = {"sector_rank_primary": "rise_ratio"}
        result, dirty = _migrate_sector_weights(merged, raw_data)
        assert dirty is True
        assert result["sector_weights"] == {"rise_ratio": 0.7, "total_trade_amount": 0.3}

    def test_no_sector_weights_no_rank_primary_no_migration(self):
        merged = {"other_key": 123}
        raw_data = {"other_key": 123}
        result, dirty = _migrate_sector_weights(merged, raw_data)
        assert dirty is False
        assert "sector_weights" not in result

    def test_empty_rank_primary_no_migration(self):
        merged = {}
        raw_data = {"sector_rank_primary": ""}
        result, dirty = _migrate_sector_weights(merged, raw_data)
        assert dirty is False
        assert "sector_weights" not in result
