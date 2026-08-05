"""core/symbol_utils.py 단위 테스트 — 종목코드 정규화 SSOT (P10).

_base_stk_cd는 core/symbol_utils.py가 단일 진실 소스.
engine_symbol_utils.py는 본 모듐에서 재수출 (P16 살아있는 경로).
"""
from __future__ import annotations

from backend.app.core.symbol_utils import _base_stk_cd
from backend.app.services.engine_symbol_utils import _base_stk_cd as _re_exported


class TestBaseStkCdSsot:
    """core.symbol_utils._base_stk_cd가 SSOT임을 검증 (P10)."""

    def test_core_and_reexport_are_same_object(self):
        """engine_symbol_utils 재수출이 동일 함수 객체 참조 (P10 단일 정의)."""
        assert _base_stk_cd is _re_exported

    def test_plain_6digit(self):
        assert _base_stk_cd("005930") == "005930"

    def test_al_suffix_stripped(self):
        assert _base_stk_cd("005930_AL") == "005930"

    def test_nx_suffix_stripped(self):
        assert _base_stk_cd("005930_NX") == "005930"

    def test_short_padded(self):
        assert _base_stk_cd("5930") == "005930"

    def test_lowercase_suffix_uppercased(self):
        assert _base_stk_cd("005930_al") == "005930"

    def test_empty(self):
        assert _base_stk_cd("") == ""

    def test_none_safe(self):
        assert _base_stk_cd(None) == ""

    def test_non_digit_passthrough_upper(self):
        assert _base_stk_cd("A005930") == "A005930"

    def test_non_digit_lower_uppercased(self):
        assert _base_stk_cd("0120g0") == "0120G0"

    def test_strips_whitespace(self):
        assert _base_stk_cd("  005930  ") == "005930"

    def test_long_digit_truncated_to_6(self):
        assert _base_stk_cd("00005930") == "005930"
