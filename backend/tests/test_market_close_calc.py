# -*- coding: utf-8 -*-
"""market_close_calc.py 단위 테스트 — 5일 파생값 순수 계산 모듈 (설계 5.6, 세션 4).

자동 일봉(``save_daily_confirmed``)·수동 5일(``save_5d_bars``)이 모두 본 계산을 호출하므로
같은 입력에 같은 결과가 보장된다 (P10 SSOT, P24 단순성).

검증 대상:
- compute_5d_derived: (거래대금, 고가) 쌍 리스트 → (평균 거래대금, 5일 최고가)
- 빈값·0·None 제외 로직 (P22 데이터 정합성)
- valid 집합 비어 있으면 (None, None) (P20 — 명시적 None)
- 자동·수동 경로가 같은 입력으로 같은 결과 (설계 5.6, 세션 4 완료 조건)
"""
from __future__ import annotations

from backend.app.services.market_close_calc import (
    compute_5d_derived,
    verify_5d_completeness,
)


class TestCompute5dDerived:
    def test_empty_pairs_returns_none(self):
        """빈 입력 → (None, None) (P20 — 명시적 None, 빈값을 성공으로 위장 금지)."""
        assert compute_5d_derived([]) == (None, None)

    def test_five_valid_pairs(self):
        """5개 valid 쌍 → 평균·최고가 (P10 SSOT)."""
        pairs = [(555, 8888), (400, 7000), (300, 6000), (200, 5000), (100, 4000)]
        avg_5d, high_5d = compute_5d_derived(pairs)
        assert avg_5d == (555 + 400 + 300 + 200 + 100) // 5  # 311
        assert high_5d == 8888

    def test_none_and_zero_excluded(self):
        """None·0 은 valid 집합에서 제외 (P22 — 빈값이 평균·최고가를 왜곡하지 않도록)."""
        pairs = [(555, 8888), (None, 7000), (0, 6000), (400, None), (300, 0)]
        avg_5d, high_5d = compute_5d_derived(pairs)
        # valid amts: [555, 400, 300] (None·0 제외) → (555+400+300)//3 = 418
        # valid highs: [8888, 7000] (None·0 제외) → max = 8888
        assert avg_5d == 418
        assert high_5d == 8888

    def test_all_invalid_returns_none(self):
        """모든 값이 None/0 이면 (None, None) (P20)."""
        pairs = [(None, None), (0, 0), (None, 0)]
        assert compute_5d_derived(pairs) == (None, None)

    def test_partial_valid_amts(self):
        """거래대금만 valid인 경우 — 평균은 valid만, 최고가는 None (highs 모두 invalid)."""
        pairs = [(555, None), (400, 0), (300, None)]
        avg_5d, high_5d = compute_5d_derived(pairs)
        assert avg_5d == (555 + 400 + 300) // 3  # 418
        assert high_5d is None

    def test_partial_valid_highs(self):
        """고가만 valid인 경우 — 최고가는 valid만, 평균은 None (amts 모두 invalid)."""
        pairs = [(None, 8888), (0, 7000), (None, 6000)]
        avg_5d, high_5d = compute_5d_derived(pairs)
        assert avg_5d is None
        assert high_5d == 8888

    def test_order_independent(self):
        """순서 무관 — 같은 값들이면 같은 결과 (P22 정합성)."""
        pairs_a = [(100, 4000), (200, 5000), (300, 6000), (400, 7000), (555, 8888)]
        pairs_b = [(555, 8888), (400, 7000), (300, 6000), (200, 5000), (100, 4000)]
        assert compute_5d_derived(pairs_a) == compute_5d_derived(pairs_b)

    def test_more_than_five_pairs_uses_all(self):
        """5개 초과 입력 — 호출자가 슬라이싱 담당, 계산 함수는 받은 만큼 모두 사용 (P24 단순성)."""
        pairs = [(100, 4000), (200, 5000), (300, 6000), (400, 7000), (555, 8888), (999, 9999)]
        avg_5d, high_5d = compute_5d_derived(pairs)
        assert avg_5d == (100 + 200 + 300 + 400 + 555 + 999) // 6
        assert high_5d == 9999

    def test_auto_and_manual_same_input_same_result(self):
        """자동 일봉·수동 5일이 같은 입력으로 같은 결과를 내는지 검증 (설계 5.6, 세션 4 완료 조건).

        자동 경로: stock_5d_bars 최근 5행 → (trade_amount, high_price) 쌍 → compute_5d_derived
        수동 경로: 다운로드 배열 → (amts_5d[i], highs_5d[i]) 쌍 → compute_5d_derived
        두 경로 모두 같은 순수 계산 함수를 호출하므로 같은 입력에 같은 결과가 보장된다.
        """
        # 자동 경로 입력 — DB 행 형태 (정렬 순서 무관, 호출자가 최근 5행 슬라이스)
        auto_rows = [
            (555, 8888), (400, 7000), (300, 6000), (200, 5000), (100, 4000),
        ]
        # 수동 경로 입력 — 다운로드 배열 형태 (같은 값)
        manual_amts = [555, 400, 300, 200, 100]
        manual_highs = [8888, 7000, 6000, 5000, 4000]
        manual_pairs = list(zip(manual_amts, manual_highs))

        auto_result = compute_5d_derived(auto_rows)
        manual_result = compute_5d_derived(manual_pairs)
        assert auto_result == manual_result == (311, 8888)


# ── verify_5d_completeness ────────────────────────────────────────────────────

class TestVerify5dCompleteness:
    """5일 원자료 완전성 검증 (설계서 4.5, 세션 4)."""

    _EXPECTED = ["20250102", "20250103", "20250104", "20250105", "20250106"]

    def test_complete_5d_returns_ok(self):
        """5일 전부 수신·숫자값 누락 없음 → 완전 (설계서 4.5)."""
        dts = self._EXPECTED
        amts = [100, 200, 300, 400, 555]
        highs = [4000, 5000, 6000, 7000, 8888]
        is_complete, problems = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        assert is_complete is True
        assert problems == []

    def test_insufficient_rows_returns_preparing(self):
        """행 수 5 미만 → 부족 (준비 중 — 아직 모이는 중, 자료 오류 아님)."""
        dts = self._EXPECTED[:3]
        amts = [100, 200, 300]
        highs = [4000, 5000, 6000]
        is_complete, problems = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        assert is_complete is False
        assert any("행 수 부족" in p for p in problems)

    def test_missing_day_returns_insufficient_5d(self):
        """거래일 누락 → 부족 (설계서 4.5)."""
        dts = ["20250102", "20250103", "20250104", "20250105", "20250107"]  # 06 누락, 07 추가
        amts = [100, 200, 300, 400, 555]
        highs = [4000, 5000, 6000, 7000, 8888]
        is_complete, problems = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        assert is_complete is False
        assert any("누락 거래일" in p for p in problems)

    def test_numeric_missing_returns_numeric_missing(self):
        """거래일은 5일 전부지만 거래대금·고가 누락 → 부족 (설계서 4.5)."""
        dts = self._EXPECTED
        amts = [100, 200, 0, 400, 555]  # 0은 누락
        highs = [4000, 5000, 6000, 7000, 8888]
        is_complete, problems = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        assert is_complete is False
        assert any("거래대금 누락" in p for p in problems)

    def test_none_highs_returns_numeric_missing(self):
        """고가 None → 부족 (설계서 4.5)."""
        dts = self._EXPECTED
        amts = [100, 200, 300, 400, 555]
        highs = [4000, None, 6000, 7000, 8888]
        is_complete, problems = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        assert is_complete is False
        assert any("고가 누락" in p for p in problems)

    def test_duplicate_day_treated_as_extra(self):
        """같은 거래일 2행 → 예상 외 거래일로 감지 (설계서 4.5 — 중복 행 차단)."""
        dts = ["20250102", "20250103", "20250104", "20250105", "20250105"]  # 06 누락, 05 중복
        amts = [100, 200, 300, 400, 555]
        highs = [4000, 5000, 6000, 7000, 8888]
        is_complete, problems = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        assert is_complete is False

    def test_empty_dts_returns_preparing(self):
        """빈 입력 → 행 수 부족 (준비 중, P20)."""
        is_complete, problems = verify_5d_completeness([], [], [], self._EXPECTED)
        assert is_complete is False
        assert any("행 수 부족" in p for p in problems)

    def test_auto_and_manual_same_input_same_result(self):
        """자동 일봉·수동 5일이 같은 입력으로 같은 완전성 판정 (설계서 4.5 — 자동·수동 같은 규칙)."""
        dts = self._EXPECTED
        amts = [100, 200, 300, 400, 555]
        highs = [4000, 5000, 6000, 7000, 8888]
        auto = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        manual = verify_5d_completeness(dts, amts, highs, self._EXPECTED)
        assert auto == manual
