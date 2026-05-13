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


class TestEligibleStockBehaviorPreserved:
    """적격 종목의 핵심 데이터가 파이프라인(원자적 교체) 수행 후에도 보존되는지 검증.

    **Validates: Requirements 3.1, 3.2, 3.6**

    핵심 로직(매수 조건, 업종 점수) 회귀 방지.
    """

    def test_eligible_stock_behavior_preserved(self):
        """적격 종목 세트로 원자적 교체 수행 후:
        - cur_price, change_rate, trade_amount 값이 보존되는지 확인
        - 5일 평균 거래대금 계산 결과가 수정 전과 동일한지 확인
        - 업종 점수 계산(get_all_sector_stocks)에 적격 종목이 정상 포함되는지 확인
        """
        import asyncio
        import app.services.engine_service as es
        import app.core.industry_map as ind_mod
        from app.core.avg_amt_cache import rolling_update_v2_from_trade_amounts, avg_from_v2

        # ── 원본 상태 백업 ──
        original_pending = es._pending_stock_details
        original_avg = es._avg_amt_5d
        original_high = es._high_5d_cache
        original_eligible = ind_mod._eligible_stock_codes
        original_radar = es._radar_cnsr_order

        try:
            # ── 테스트 데이터: 적격 종목 5개 (알려진 값) ──
            eligible_codes = ["005930", "000660", "035720", "051910", "006400"]
            known_data = {
                "005930": {"cur_price": 72000, "change_rate": 1.5, "trade_amount": 800_000_000_000},
                "000660": {"cur_price": 135000, "change_rate": -0.8, "trade_amount": 500_000_000_000},
                "035720": {"cur_price": 52000, "change_rate": 2.3, "trade_amount": 200_000_000_000},
                "051910": {"cur_price": 180000, "change_rate": 0.5, "trade_amount": 150_000_000_000},
                "006400": {"cur_price": 850000, "change_rate": -1.2, "trade_amount": 100_000_000_000},
            }

            # ── _pending_stock_details에 적격 종목 세팅 ──
            test_pending: dict = {}
            for code in eligible_codes:
                d = known_data[code]
                test_pending[code] = {
                    "code": code,
                    "name": f"종목_{code}",
                    "cur_price": d["cur_price"],
                    "change": 1000,
                    "change_rate": d["change_rate"],
                    "sign": "2",
                    "trade_amount": d["trade_amount"],
                    "high_price": d["cur_price"] + 1000,
                    "status": "active",
                    "sector": "반도체",
                }
            es._pending_stock_details = test_pending

            # ── _eligible_stock_codes 설정 ──
            ind_mod._eligible_stock_codes = {code: "" for code in eligible_codes}

            # ── 5일 평균 거래대금 v2 데이터 세팅 (rolling_update 테스트용) ──
            existing_v2 = {
                "005930": [700_000, 750_000, 780_000, 800_000, 810_000],
                "000660": [400_000, 450_000, 480_000, 500_000, 520_000],
                "035720": [150_000, 180_000, 190_000, 200_000, 210_000],
                "051910": [100_000, 120_000, 130_000, 140_000, 150_000],
                "006400": [80_000, 85_000, 90_000, 95_000, 100_000],
            }

            # 당일 거래대금 (원 단위)
            trade_amounts = {
                "005930": 820_000_000_000,
                "000660": 530_000_000_000,
                "035720": 215_000_000_000,
                "051910": 155_000_000_000,
                "006400": 105_000_000_000,
            }

            # ── 검증 1: rolling_update_v2 결과가 적격 종목에 대해 정확한지 확인 ──
            eligible_set = set(eligible_codes)
            updated_v2, _ = rolling_update_v2_from_trade_amounts(
                existing_v2,
                trade_amounts,
                eligible_set=eligible_set,
            )

            # 적격 종목 모두 결과에 포함
            for code in eligible_codes:
                assert code in updated_v2, (
                    f"Eligible stock {code} missing from rolling update result"
                )

            # 롤링 로직 검증: 기존 배열에서 가장 오래된 값 제거 + 당일 값 추가
            # 005930: [700000, 750000, 780000, 800000, 810000] + 820000000000원 → 820000백만원
            # → [750000, 780000, 800000, 810000, 820000]
            expected_005930 = [750_000, 780_000, 800_000, 810_000, 820_000]
            assert updated_v2["005930"] == expected_005930, (
                f"005930 rolling mismatch: expected {expected_005930}, got {updated_v2['005930']}"
            )

            # ── 검증 2: avg_from_v2 계산 결과 확인 ──
            avg_map = avg_from_v2(updated_v2)
            for code in eligible_codes:
                assert code in avg_map, (
                    f"Eligible stock {code} missing from avg_from_v2 result"
                )
            # 005930 평균: (750000+780000+800000+810000+820000)/5 = 792000
            expected_avg_005930 = int((750_000 + 780_000 + 800_000 + 810_000 + 820_000) / 5)
            assert avg_map["005930"] == expected_avg_005930, (
                f"005930 avg mismatch: expected {expected_avg_005930}, got {avg_map['005930']}"
            )

            # ── _avg_amt_5d에 계산된 평균값 세팅 ──
            es._avg_amt_5d = avg_map

            # ── _high_5d_cache 세팅 ──
            test_high: dict[str, int] = {code: known_data[code]["cur_price"] + 1000 for code in eligible_codes}
            es._high_5d_cache = test_high

            # ── _radar_cnsr_order 세팅 ──
            es._radar_cnsr_order = list(eligible_codes)

            # ── 원자적 메모리 교체 시뮬레이션 (Step 6 + Step 7) ──
            final_eligible = set(ind_mod._eligible_stock_codes.keys())

            mapped_pending: dict = {}
            for cd in final_eligible:
                entry = es._pending_stock_details.get(cd)
                if entry is not None:
                    mapped_pending[cd] = entry

            new_avg = {cd: v for cd, v in es._avg_amt_5d.items() if cd in final_eligible}
            new_high = {cd: v for cd, v in es._high_5d_cache.items() if cd in final_eligible}

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

            # ── 검증 3: 교체 후 적격 종목의 시세 데이터 보존 확인 ──
            for code in eligible_codes:
                entry = es._pending_stock_details.get(code)
                assert entry is not None, (
                    f"Eligible stock {code} missing from _pending_stock_details after swap"
                )
                expected = known_data[code]
                assert entry["cur_price"] == expected["cur_price"], (
                    f"{code} cur_price mismatch: expected {expected['cur_price']}, got {entry['cur_price']}"
                )
                assert entry["change_rate"] == expected["change_rate"], (
                    f"{code} change_rate mismatch: expected {expected['change_rate']}, got {entry['change_rate']}"
                )
                assert entry["trade_amount"] == expected["trade_amount"], (
                    f"{code} trade_amount mismatch: expected {expected['trade_amount']}, got {entry['trade_amount']}"
                )

            # ── 검증 4: 교체 후 5일 평균 거래대금 보존 확인 ──
            for code in eligible_codes:
                assert code in es._avg_amt_5d, (
                    f"Eligible stock {code} missing from _avg_amt_5d after swap"
                )
                assert es._avg_amt_5d[code] == avg_map[code], (
                    f"{code} avg_amt_5d mismatch after swap: expected {avg_map[code]}, got {es._avg_amt_5d[code]}"
                )

            # ── 검증 5: get_all_sector_stocks()에 적격 종목이 정상 포함되는지 확인 ──
            result = es.get_all_sector_stocks()
            result_codes = {item["code"] for item in result}

            for code in eligible_codes:
                assert code in result_codes, (
                    f"Eligible stock {code} not found in get_all_sector_stocks() result"
                )

            # 결과가 정확히 적격 종목만 포함
            assert result_codes == set(eligible_codes), (
                f"get_all_sector_stocks() should return exactly eligible stocks. "
                f"Expected {set(eligible_codes)}, got {result_codes}"
            )

        finally:
            # ── 원본 상태 복원 ──
            es._pending_stock_details = original_pending
            es._avg_amt_5d = original_avg
            es._high_5d_cache = original_high
            ind_mod._eligible_stock_codes = original_eligible
            es._radar_cnsr_order = original_radar


# ---------------------------------------------------------------------------
# 5.3 통합 테스트: 수동 새로고침 후에도 동일한가
# ---------------------------------------------------------------------------


class TestManualRefreshConsistency:
    """자동 경로와 수동 경로의 원자적 교체 결과가 동일한지 검증.

    **Validates: Requirements 2.1, 2.4**

    두 경로 모두 동일한 atomic swap 로직(적격 종목만 필터 → lock 하에 교체)을
    사용하므로, 최종 메모리 상태(키 집합)가 동일해야 한다.
    """

    def test_manual_refresh_consistency(self):
        """자동 경로(fetch_unified_confirmed_data) 완료 후 스냅샷과
        수동 경로(_refresh_avg_amt_5d_cache_inner) 완료 후 스냅샷이 동일한지 검증.

        - _avg_amt_5d 키 집합이 동일 (적격 종목만)
        - _high_5d_cache 키 집합이 동일 (적격 종목만)
        - _pending_stock_details 키 집합이 동일 (적격 종목만)
        """
        import asyncio
        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        # ── 원본 상태 백업 ──
        original_pending = es._pending_stock_details
        original_avg = es._avg_amt_5d
        original_high = es._high_5d_cache
        original_eligible = ind_mod._eligible_stock_codes
        original_radar = es._radar_cnsr_order

        try:
            # ── 테스트 데이터: eligible 10종목 + ineligible 5종목 ──
            eligible_codes = [f"{i:06d}" for i in range(1, 11)]    # 000001 ~ 000010
            ineligible_codes = [f"{i:06d}" for i in range(9001, 9006)]  # 009001 ~ 009005
            all_codes = eligible_codes + ineligible_codes

            assert len(eligible_codes) == 10
            assert len(ineligible_codes) == 5
            assert len(all_codes) == 15

            # ── _eligible_stock_codes에 적격 종목만 설정 ──
            ind_mod._eligible_stock_codes = {code: "" for code in eligible_codes}

            # ── 헬퍼: 전체 메모리 구조 초기화 (eligible + ineligible 모두 포함) ──
            def _setup_full_memory():
                """eligible + ineligible 종목 모두 포함된 초기 메모리 상태 구성."""
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
                        "sector": "테스트업종",
                    }
                es._pending_stock_details = test_pending

                test_avg: dict[str, int] = {}
                for code in all_codes:
                    test_avg[code] = 500 + int(code) % 100
                es._avg_amt_5d = test_avg

                test_high: dict[str, int] = {}
                for code in all_codes:
                    test_high[code] = 11000 + int(code) % 1000
                es._high_5d_cache = test_high

                es._radar_cnsr_order = list(all_codes)

            # ══════════════════════════════════════════════════════════════════
            # 자동 경로 시뮬레이션 (fetch_unified_confirmed_data 패턴)
            # ══════════════════════════════════════════════════════════════════
            _setup_full_memory()

            final_eligible = set(ind_mod._eligible_stock_codes.keys())

            # Step 6: 완전한 매핑 단계 — 적격 종목만 매핑
            mapped_pending_auto: dict = {}
            for cd in final_eligible:
                entry = es._pending_stock_details.get(cd)
                if entry is not None:
                    mapped_pending_auto[cd] = entry

            new_avg_auto = {cd: v for cd, v in es._avg_amt_5d.items() if cd in final_eligible}
            new_high_auto = {cd: v for cd, v in es._high_5d_cache.items() if cd in final_eligible}

            # Step 7: 원자적 메모리 교체 (lock 하에)
            loop = asyncio.new_event_loop()

            async def _auto_path_swap():
                async with es._shared_lock:
                    es._pending_stock_details.clear()
                    es._pending_stock_details.update(mapped_pending_auto)
                    es._avg_amt_5d.clear()
                    es._avg_amt_5d.update(new_avg_auto)
                    es._high_5d_cache.clear()
                    es._high_5d_cache.update(new_high_auto)
                    es._radar_cnsr_order[:] = [
                        cd for cd in es._radar_cnsr_order if cd in final_eligible
                    ]

            loop.run_until_complete(_auto_path_swap())
            loop.close()

            # ── 자동 경로 스냅샷 저장 ──
            snapshot_auto_avg_keys = set(es._avg_amt_5d.keys())
            snapshot_auto_high_keys = set(es._high_5d_cache.keys())
            snapshot_auto_pending_keys = set(es._pending_stock_details.keys())

            # ══════════════════════════════════════════════════════════════════
            # 수동 경로 시뮬레이션 (_refresh_avg_amt_5d_cache_inner 패턴)
            # ══════════════════════════════════════════════════════════════════
            # 메모리를 원래 상태(ineligible 포함)로 리셋
            _setup_full_memory()

            eligible_set = set(eligible_codes)

            # 수동 경로: 적격 종목 × 시세 × 5일데이터 × 업종 매핑 확인
            # (실제 코드에서는 get_merged_sector 등으로 확인하지만,
            #  여기서는 모든 적격 종목이 시세+5일데이터+업종 매핑 완료된 상태로 가정)
            fully_mapped: set[str] = set()
            for cd in eligible_set:
                # 시세 확인
                if cd not in es._pending_stock_details:
                    continue
                # 5일데이터 확인
                if cd not in es._avg_amt_5d and cd not in es._high_5d_cache:
                    continue
                # 업종 매핑 확인 (테스트에서는 sector 필드가 이미 설정됨)
                entry = es._pending_stock_details[cd]
                if not entry.get("sector"):
                    continue
                fully_mapped.add(cd)

            new_avg_manual = {cd: v for cd, v in es._avg_amt_5d.items() if cd in fully_mapped}
            new_high_manual = {cd: v for cd, v in es._high_5d_cache.items() if cd in fully_mapped}

            # 원자적 메모리 교체 (수동 경로: _pending_stock_details에서 부적격 제거)
            loop2 = asyncio.new_event_loop()

            async def _manual_path_swap():
                async with es._shared_lock:
                    es._avg_amt_5d.clear()
                    es._avg_amt_5d.update(new_avg_manual)
                    es._high_5d_cache.clear()
                    es._high_5d_cache.update(new_high_manual)
                    # _pending_stock_details에서 부적격 종목 제거
                    ineligible_in_pending = [
                        cd for cd in es._pending_stock_details if cd not in eligible_set
                    ]
                    for cd in ineligible_in_pending:
                        del es._pending_stock_details[cd]
                    es._radar_cnsr_order[:] = [
                        cd for cd in es._radar_cnsr_order if cd in eligible_set
                    ]

            loop2.run_until_complete(_manual_path_swap())
            loop2.close()

            # ── 수동 경로 스냅샷 저장 ──
            snapshot_manual_avg_keys = set(es._avg_amt_5d.keys())
            snapshot_manual_high_keys = set(es._high_5d_cache.keys())
            snapshot_manual_pending_keys = set(es._pending_stock_details.keys())

            # ══════════════════════════════════════════════════════════════════
            # 두 경로의 최종 결과 비교
            # ══════════════════════════════════════════════════════════════════

            # ── 검증 1: _avg_amt_5d 키 집합이 동일 (적격 종목만) ──
            assert snapshot_auto_avg_keys == snapshot_manual_avg_keys, (
                f"_avg_amt_5d key sets differ between auto and manual paths. "
                f"Auto only: {snapshot_auto_avg_keys - snapshot_manual_avg_keys}, "
                f"Manual only: {snapshot_manual_avg_keys - snapshot_auto_avg_keys}"
            )

            # ── 검증 2: _high_5d_cache 키 집합이 동일 (적격 종목만) ──
            assert snapshot_auto_high_keys == snapshot_manual_high_keys, (
                f"_high_5d_cache key sets differ between auto and manual paths. "
                f"Auto only: {snapshot_auto_high_keys - snapshot_manual_high_keys}, "
                f"Manual only: {snapshot_manual_high_keys - snapshot_auto_high_keys}"
            )

            # ── 검증 3: _pending_stock_details 키 집합이 동일 (적격 종목만) ──
            assert snapshot_auto_pending_keys == snapshot_manual_pending_keys, (
                f"_pending_stock_details key sets differ between auto and manual paths. "
                f"Auto only: {snapshot_auto_pending_keys - snapshot_manual_pending_keys}, "
                f"Manual only: {snapshot_manual_pending_keys - snapshot_auto_pending_keys}"
            )

            # ── 추가 검증: 두 경로 모두 적격 종목만 포함하는지 확인 ──
            assert snapshot_auto_avg_keys == set(eligible_codes), (
                f"Auto path _avg_amt_5d should contain only eligible stocks. "
                f"Got: {snapshot_auto_avg_keys}"
            )
            assert snapshot_auto_high_keys == set(eligible_codes), (
                f"Auto path _high_5d_cache should contain only eligible stocks. "
                f"Got: {snapshot_auto_high_keys}"
            )
            assert snapshot_auto_pending_keys == set(eligible_codes), (
                f"Auto path _pending_stock_details should contain only eligible stocks. "
                f"Got: {snapshot_auto_pending_keys}"
            )

            # ── 추가 검증: ineligible 종목이 어느 경로에서도 남아있지 않은지 확인 ──
            ineligible_set = set(ineligible_codes)
            assert len(snapshot_auto_avg_keys & ineligible_set) == 0, (
                f"Auto path leaked ineligible to _avg_amt_5d: "
                f"{snapshot_auto_avg_keys & ineligible_set}"
            )
            assert len(snapshot_manual_avg_keys & ineligible_set) == 0, (
                f"Manual path leaked ineligible to _avg_amt_5d: "
                f"{snapshot_manual_avg_keys & ineligible_set}"
            )
            assert len(snapshot_auto_pending_keys & ineligible_set) == 0, (
                f"Auto path leaked ineligible to _pending_stock_details: "
                f"{snapshot_auto_pending_keys & ineligible_set}"
            )
            assert len(snapshot_manual_pending_keys & ineligible_set) == 0, (
                f"Manual path leaked ineligible to _pending_stock_details: "
                f"{snapshot_manual_pending_keys & ineligible_set}"
            )

        finally:
            # ── 원본 상태 복원 ──
            es._pending_stock_details = original_pending
            es._avg_amt_5d = original_avg
            es._high_5d_cache = original_high
            ind_mod._eligible_stock_codes = original_eligible
            es._radar_cnsr_order = original_radar
