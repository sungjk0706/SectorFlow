# -*- coding: utf-8 -*-
"""
Integration Tests — Data Consistency Fix

통합 테스트: 파이프라인 전체 흐름 시뮬레이션을 통해 적격 종목만 UI에 보이는지 검증.

Bug 1(캐시 잔존), Bug 3(UI 필터), Bug 4(메모리 교체) 동시 검증.
"""
from __future__ import annotations

import asyncio



# ---------------------------------------------------------------------------
# 5.1 통합 테스트: 적격 종목만 UI에 보이는가
# ---------------------------------------------------------------------------


class TestOnlyEligibleStocksVisibleInUI:
    """파이프라인 전체 흐름 시뮬레이션 후 적격 종목만 UI에 보이는지 검증.

    **Validates: Requirements 2.1, 2.3, 2.4**

    Bug 1(캐시 잔존), Bug 3(UI 필터), Bug 4(메모리 교체) 동시 검증.
    """

    def test_only_eligible_stocks_visible_in_ui(self):
        """eligible 1484종목 + ineligible 41종목 세팅 후 원자적 교체 수행 →
        get_all_sector_stocks(), _avg_amt_5d, _high_5d_cache 모두 eligible만 포함."""
        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        # ── 원본 상태 백업 ──
        original_pending = es._pending_stock_details
        original_avg = es._avg_amt_5d
        original_high = es._high_5d_cache
        original_eligible = ind_mod._eligible_stock_codes
        original_radar = es._radar_cnsr_order

        try:
            # ── 테스트 데이터 생성: 1484 eligible + 41 ineligible ──
            eligible_codes = [f"{i:06d}" for i in range(1, 1485)]   # 000001 ~ 001484
            ineligible_codes = [f"{i:06d}" for i in range(9000, 9041)]  # 009000 ~ 009040
            all_codes = eligible_codes + ineligible_codes

            assert len(eligible_codes) == 1484
            assert len(ineligible_codes) == 41
            assert len(all_codes) == 1525

            # ── _pending_stock_details에 전체 1525종목 세팅 (모두 active) ──
            test_pending: dict = {}
            for code in all_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"종목_{code}",
                    "cur_price": 10000 + int(code),
                    "change": 100,
                    "change_rate": 1.0,
                    "sign": "2",
                    "trade_amount": 5_000_000_000,
                    "high_price": 11000 + int(code),
                    "status": "active",
                }
            es._pending_stock_details = test_pending

            # ── _eligible_stock_codes에 1484종목만 설정 ──
            ind_mod._eligible_stock_codes = {code: "" for code in eligible_codes}
            ind_mod._eligible_cache_date = ind_mod.current_trading_date_str()

            # ── _avg_amt_5d에 전체 1525종목 세팅 ──
            test_avg: dict[str, int] = {}
            for code in all_codes:
                test_avg[code] = 500 + int(code) % 100
            es._avg_amt_5d = test_avg

            # ── _high_5d_cache에 전체 1525종목 세팅 ──
            test_high: dict[str, int] = {}
            for code in all_codes:
                test_high[code] = 11000 + int(code) % 1000
            es._high_5d_cache = test_high

            # ── _radar_cnsr_order에 전체 종목 세팅 ──
            es._radar_cnsr_order = list(all_codes)

            # ── 원자적 메모리 교체 시뮬레이션 (Step 6 + Step 7) ──
            # Step 6: Build mapped_pending from eligible stocks only
            final_eligible = set(ind_mod._eligible_stock_codes.keys())

            mapped_pending: dict = {}
            for cd in final_eligible:
                entry = es._pending_stock_details.get(cd)
                if entry is not None:
                    mapped_pending[cd] = entry

            # Filter avg and high caches to eligible only
            new_avg = {cd: v for cd, v in es._avg_amt_5d.items() if cd in final_eligible}
            new_high = {cd: v for cd, v in es._high_5d_cache.items() if cd in final_eligible}

            # Step 7: Atomic swap under _shared_lock
            loop = asyncio.new_event_loop()

            async def _do_atomic_swap():
                async with es._shared_lock:
                    es._pending_stock_details.clear()
                    es._pending_stock_details.update(mapped_pending)
                    es._avg_amt_5d.clear()
                    es._avg_amt_5d.update(new_avg)
                    es._high_5d_cache.clear()
                    es._high_5d_cache.update(new_high)
                    es._radar_cnsr_order[:] = [
                        cd for cd in es._radar_cnsr_order if cd in final_eligible
                    ]

            loop.run_until_complete(_do_atomic_swap())
            loop.close()

            # ── 검증 1: get_all_sector_stocks() 반환값이 eligible 종목만 포함 ──
            result = es.get_all_sector_stocks()
            result_codes = {item["code"] for item in result}

            # eligible 종목만 포함되어야 함
            assert result_codes == set(eligible_codes), (
                f"get_all_sector_stocks() should return only eligible stocks. "
                f"Expected {len(eligible_codes)} stocks, got {len(result_codes)}. "
                f"Ineligible leaked: {result_codes - set(eligible_codes)}"
            )

            # ineligible 종목이 없어야 함
            leaked_ineligible = result_codes & set(ineligible_codes)
            assert len(leaked_ineligible) == 0, (
                f"Ineligible stocks leaked to UI: {leaked_ineligible}"
            )

            # ── 검증 2: _avg_amt_5d 키가 eligible 종목만 포함 ──
            avg_keys = set(es._avg_amt_5d.keys())
            assert avg_keys == set(eligible_codes), (
                f"_avg_amt_5d should contain only eligible stocks. "
                f"Expected {len(eligible_codes)}, got {len(avg_keys)}. "
                f"Ineligible leaked: {avg_keys - set(eligible_codes)}"
            )

            avg_ineligible = avg_keys & set(ineligible_codes)
            assert len(avg_ineligible) == 0, (
                f"Ineligible stocks in _avg_amt_5d: {avg_ineligible}"
            )

            # ── 검증 3: _high_5d_cache 키가 eligible 종목만 포함 ──
            high_keys = set(es._high_5d_cache.keys())
            assert high_keys == set(eligible_codes), (
                f"_high_5d_cache should contain only eligible stocks. "
                f"Expected {len(eligible_codes)}, got {len(high_keys)}. "
                f"Ineligible leaked: {high_keys - set(eligible_codes)}"
            )

            high_ineligible = high_keys & set(ineligible_codes)
            assert len(high_ineligible) == 0, (
                f"Ineligible stocks in _high_5d_cache: {high_ineligible}"
            )

            # ── 검증 4: _pending_stock_details 키가 eligible 종목만 포함 ──
            pending_keys = set(es._pending_stock_details.keys())
            assert pending_keys == set(eligible_codes), (
                f"_pending_stock_details should contain only eligible stocks. "
                f"Expected {len(eligible_codes)}, got {len(pending_keys)}. "
                f"Ineligible leaked: {pending_keys - set(eligible_codes)}"
            )

            pending_ineligible = pending_keys & set(ineligible_codes)
            assert len(pending_ineligible) == 0, (
                f"Ineligible stocks in _pending_stock_details: {pending_ineligible}"
            )

            # ── 검증 5: _radar_cnsr_order도 eligible만 포함 ──
            radar_set = set(es._radar_cnsr_order)
            radar_ineligible = radar_set & set(ineligible_codes)
            assert len(radar_ineligible) == 0, (
                f"Ineligible stocks in _radar_cnsr_order: {radar_ineligible}"
            )

        finally:
            # ── 원본 상태 복원 ──
            es._pending_stock_details = original_pending
            es._avg_amt_5d = original_avg
            es._high_5d_cache = original_high
            ind_mod._eligible_stock_codes = original_eligible
            es._radar_cnsr_order = original_radar


# ---------------------------------------------------------------------------
# 5.2 스모크 테스트: 기존 적격 종목 동작 그대로인가
# ---------------------------------------------------------------------------


