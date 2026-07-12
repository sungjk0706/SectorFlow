"""stock_filter.py 단위 테스트 — 매매 부적격 종목 필터 (순수 함수, mock 불필요)."""
from __future__ import annotations

import pytest
from backend.app.core.stock_filter import (
    StockFilterEvaluation,
    _split_state_flags,
    _positive_int_string,
    _stock_name,
    _preferred_reason,
    evaluate_stock_filter,
    is_excluded,
    is_excluded_with_ka10100,
    to_display_reason,
)


# ── _split_state_flags ──────────────────────────────────────────────

class TestSplitStateFlags:
    def test_empty_string(self):
        assert _split_state_flags("") == []

    def test_none(self):
        assert _split_state_flags(None) == []

    def test_normal(self):
        assert _split_state_flags("정상") == []

    def test_single_keyword(self):
        assert _split_state_flags("관리종목") == ["관리종목"]

    def test_pipe_separated(self):
        result = _split_state_flags("관리종목|거래정지")
        assert result == ["관리종목", "거래정지"]

    def test_slash_separated(self):
        result = _split_state_flags("관리종목/거래정지")
        assert result == ["관리종목", "거래정지"]

    def test_comma_separated(self):
        result = _split_state_flags("관리종목,거래정지")
        assert result == ["관리종목", "거래정지"]

    def test_strips_whitespace(self):
        result = _split_state_flags("  관리종목  |  거래정지  ")
        assert result == ["관리종목", "거래정지"]

    def test_unknown_state_returns_itself(self):
        result = _split_state_flags("알수없음")
        assert result == ["알수없음"]


# ── _positive_int_string ────────────────────────────────────────────

class TestPositiveIntString:
    def test_empty(self):
        assert _positive_int_string("") == (False, None)

    def test_none(self):
        assert _positive_int_string(None) == (False, None)

    def test_positive(self):
        ok, val = _positive_int_string("50000")
        assert ok is True and val == 50000

    def test_zero(self):
        ok, val = _positive_int_string("0")
        assert ok is False and val == 0

    def test_with_comma(self):
        ok, val = _positive_int_string("50,000")
        assert ok is True and val == 50000

    def test_with_plus_prefix(self):
        ok, val = _positive_int_string("+50000")
        assert ok is True and val == 50000

    def test_negative(self):
        ok, val = _positive_int_string("-100")
        assert ok is False and val is None

    def test_non_digit(self):
        ok, val = _positive_int_string("abc")
        assert ok is False and val is None

    def test_float_string(self):
        ok, val = _positive_int_string("50000.5")
        assert ok is False and val is None


# ── _stock_name ─────────────────────────────────────────────────────

class TestStockName:
    def test_hname(self):
        assert _stock_name({"hname": "삼성전자"}) == "삼성전자"

    def test_stk_nm_fallback(self):
        assert _stock_name({"stk_nm": "삼성전자"}) == "삼성전자"

    def test_name_fallback(self):
        assert _stock_name({"name": "삼성전자"}) == "삼성전자"

    def test_hname_priority(self):
        assert _stock_name({"hname": "A", "stk_nm": "B", "name": "C"}) == "A"

    def test_empty(self):
        assert _stock_name({}) == ""

    def test_none_values(self):
        assert _stock_name({"hname": None, "stk_nm": None, "name": "X"}) == "X"

    def test_strips_whitespace(self):
        assert _stock_name({"hname": "  삼성전자  "}) == "삼성전자"


# ── _preferred_reason ───────────────────────────────────────────────

class TestPreferredReason:
    def test_suffix_우선주(self):
        assert "우선주(종목명)-우선주" in _preferred_reason("삼성전자우선주", "")

    def test_suffix_우B(self):
        result = _preferred_reason("삼성전자우B", "")
        assert "우선주(종목명)-우B" in result

    def test_suffix_우(self):
        result = _preferred_reason("삼성전자우", "")
        assert "우선주(종목명)-우" in result

    def test_short_name_no_match(self):
        # len(clean_name) <= len(suffix) + 1 → 매칭 안 함
        assert _preferred_reason("우", "") == ""

    def test_parenthesis_removed(self):
        """괄호 접미사 제거 후 우선주 접미사 매칭 — '삼성전자우선주(1우)' → '삼성전자우선주'."""
        result = _preferred_reason("삼성전자우선주(1우)", "")
        assert "우선주(종목명)-우선주" in result

    def test_english_preferred(self):
        result = _preferred_reason("SAMSUNG PREFERRED", "")
        assert "우선주(영문표기)-PREFERRED" in result

    def test_english_prf(self):
        result = _preferred_reason("SAMSUNG PRF", "")
        assert "우선주(영문표기)-PRF" in result

    def test_company_class_우선(self):
        result = _preferred_reason("삼성전자", "우선주")
        assert "우선주(회사분류)-우선주" in result

    def test_no_preferred(self):
        assert _preferred_reason("삼성전자", "보통주") == ""


# ── evaluate_stock_filter ───────────────────────────────────────────

class TestEvaluateStockFilter:
    def _normal_item(self) -> dict:
        """매매 적격 정상 종목 기본 데이터."""
        return {
            "marketCode": "0",
            "marketName": "코스피",
            "orderWarning": "0",
            "state": "정상",
            "hname": "삼성전자",
            "companyClassName": "보통주",
            "auditInfo": "",
            "listCount": "5,977,325",
            "lastPrice": "70000",
            "regDay": "20240101",
            "nxtEnable": "Y",
        }

    def test_normal_stock_not_excluded(self):
        result = evaluate_stock_filter(self._normal_item(), "005930")
        assert result.excluded is False
        assert result.primary_reason == ""
        assert result.reasons == []

    def test_non_equity_market_code(self):
        item = self._normal_item()
        item["marketCode"] = "8"
        result = evaluate_stock_filter(item, "123456")
        assert result.excluded is True
        assert "marketCode=8(ETF)" in result.reasons

    def test_non_equity_market_code_unknown(self):
        item = self._normal_item()
        item["marketCode"] = "99"
        result = evaluate_stock_filter(item, "123456")
        assert result.excluded is True
        assert any("marketCode=99" in r for r in result.reasons)

    def test_order_warning(self):
        item = self._normal_item()
        item["orderWarning"] = "2"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert "정리매매" in result.reasons

    def test_order_warning_unknown(self):
        item = self._normal_item()
        item["orderWarning"] = "9"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert any("orderWarning=9" in r for r in result.reasons)

    def test_state_blocked_keyword(self):
        item = self._normal_item()
        item["state"] = "관리종목"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert "state=관리종목" in result.reasons

    def test_state_composite(self):
        item = self._normal_item()
        item["state"] = "관리종목|투자위험"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert "state=관리종목" in result.reasons
        assert "state=투자위험" in result.reasons

    def test_spac_name(self):
        item = self._normal_item()
        item["hname"] = "한국스팩 1호"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert "스팩" in result.reasons

    def test_spac_english(self):
        item = self._normal_item()
        item["hname"] = "KOREA SPAC"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert "스팩" in result.reasons

    def test_preferred_stock_by_name(self):
        item = self._normal_item()
        item["hname"] = "삼성전자우선주"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert any("우선주(종목명)" in r for r in result.reasons)

    def test_preferred_stock_code_diagnostic(self):
        """종목코드 끝자리 ≠ '0'이면 diagnostic_flag 추가 (reasons 아님)."""
        item = self._normal_item()
        result = evaluate_stock_filter(item, "005935")
        assert result.excluded is False
        assert "우선주의심(코드끝자리)" in result.diagnostic_flags

    def test_audit_not_normal(self):
        item = self._normal_item()
        item["auditInfo"] = "감리지정"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert "감리=감리지정" in result.reasons

    def test_list_count_abnormal(self):
        item = self._normal_item()
        item["listCount"] = "0"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert any("상장주식수비정상" in r for r in result.reasons)

    def test_last_price_empty(self):
        item = self._normal_item()
        item["lastPrice"] = ""
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert any("전일종가비정상" in r for r in result.reasons)

    def test_last_price_zero(self):
        item = self._normal_item()
        item["lastPrice"] = "0"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is True
        assert any("전일종가비정상" in r for r in result.reasons)

    def test_nxt_enable_N_diagnostic(self):
        item = self._normal_item()
        item["nxtEnable"] = "N"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is False
        assert "NXT불가" in result.diagnostic_flags

    def test_parsed_fields_populated(self):
        result = evaluate_stock_filter(self._normal_item(), "005930")
        assert result.parsed_fields["marketCode"] == "0"
        assert result.parsed_fields["name"] == "삼성전자"
        assert result.parsed_fields["orderWarning"] == "0"
        assert result.parsed_fields["lastPriceValue"] == 70000

    def test_reasons_deduplicated(self):
        """동일 사유 중복 제거 확인."""
        item = self._normal_item()
        item["state"] = "관리종목|관리종목"
        result = evaluate_stock_filter(item, "005930")
        # "state=관리종목"이 한 번만 나와야 함
        assert result.reasons.count("state=관리종목") == 1

    def test_non_equity_keyword_in_name_not_excluded(self):
        """non_equity_keywords 제거 — marketCode=0(코스피)이면 종목명에 ETF가 있어도 제외 안 함.
        실제 ETF는 marketCode=8로 잡힘 (P10 SSOT 단일 판정)."""
        item = self._normal_item()
        item["hname"] = "KODEX ETF"
        result = evaluate_stock_filter(item, "005930")
        assert result.excluded is False

    def test_code_field_set(self):
        result = evaluate_stock_filter(self._normal_item(), "005930")
        assert result.code == "005930"


# ── is_excluded ─────────────────────────────────────────────────────

class TestIsExcluded:
    def _normal_item(self) -> dict:
        return {
            "marketCode": "0",
            "orderWarning": "0",
            "state": "정상",
            "hname": "삼성전자",
            "companyClassName": "보통주",
            "auditInfo": "",
            "listCount": "100000",
            "lastPrice": "70000",
        }

    def test_normal(self):
        excluded, reason = is_excluded(self._normal_item(), "005930")
        assert excluded is False
        assert reason == ""

    def test_excluded(self):
        item = self._normal_item()
        item["orderWarning"] = "5"
        excluded, reason = is_excluded(item, "005930")
        assert excluded is True
        assert reason == "투자경고"


# ── is_excluded_with_ka10100 ────────────────────────────────────────

class TestIsExcludedWithKa10100:
    def _normal_item(self) -> dict:
        return {
            "marketCode": "0",
            "orderWarning": "0",
            "state": "정상",
            "hname": "삼성전자",
            "companyClassName": "보통주",
            "auditInfo": "",
            "listCount": "100000",
            "lastPrice": "70000",
        }

    def test_1st_filter_excluded(self):
        """1차 필터에서 제외되면 2차 필터 수행 없이 반환."""
        item = self._normal_item()
        item["orderWarning"] = "5"
        excluded, reason = is_excluded_with_ka10100(item, "005930", {})
        assert excluded is True
        assert reason == "투자경고"

    def test_no_ka10100_data(self):
        """ka10100_data가 None이면 1차 필터 결과만 반환."""
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", None)
        assert excluded is False
        assert reason == ""

    def test_ka10100_preferred_stock(self):
        """ka10100 companyClassName에 '우선주' 포함 시 제외."""
        ka = {"companyClassName": "우선주"}
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", ka)
        assert excluded is True
        assert "우선주(ka10100)" in reason

    def test_ka10100_list_count_zero(self):
        """ka10100 listCount가 0 또는 0000000000000000이면 제외."""
        ka = {"listCount": "0000000000000000"}
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", ka)
        assert excluded is True
        assert "상장주식수비정상(ka10100)" in reason

    def test_ka10100_list_count_single_zero(self):
        ka = {"listCount": "0"}
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", ka)
        assert excluded is True
        assert "상장주식수비정상(ka10100)" in reason

    def test_ka10100_last_price_zero(self):
        """ka10100 lastPrice가 0 또는 00000000이면 제외."""
        ka = {"lastPrice": "00000000"}
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", ka)
        assert excluded is True
        assert "전일종가비정상(ka10100)" in reason

    def test_ka10100_last_price_single_zero(self):
        ka = {"lastPrice": "0"}
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", ka)
        assert excluded is True
        assert "전일종가비정상(ka10100)" in reason

    def test_ka10100_all_normal(self):
        """ka10100 데이터가 정상이면 제외되지 않음."""
        ka = {"companyClassName": "보통주", "listCount": "100000", "lastPrice": "70000"}
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", ka)
        assert excluded is False
        assert reason == ""

    def test_ka10100_empty_company_class(self):
        """companyClassName이 빈 경우 제외되지 않음."""
        ka = {"companyClassName": ""}
        excluded, reason = is_excluded_with_ka10100(self._normal_item(), "005930", ka)
        assert excluded is False


# ── to_display_reason ───────────────────────────────────────────────

class TestToDisplayReason:
    def test_empty(self):
        assert to_display_reason("") == ""

    def test_market_code_etf(self):
        assert to_display_reason("marketCode=8(ETF)") == "ETF"

    def test_market_code_etn(self):
        assert to_display_reason("marketCode=60(ETN)") == "ETN"

    def test_market_code_elw(self):
        assert to_display_reason("marketCode=3(ELW)") == "ELW"

    def test_market_code_reits(self):
        assert to_display_reason("marketCode=6(리츠)") == "리츠"

    def test_market_code_unknown_prefix(self):
        """매핑 누락 marketCode — raw 그대로 반환 (P21 투명성)."""
        assert to_display_reason("marketCode=99(알수없음)") == "marketCode=99(알수없음)"

    def test_state_keyword(self):
        assert to_display_reason("state=관리종목") == "관리종목"

    def test_state_margin_100(self):
        assert to_display_reason("state=증거금100%") == "증거금100%종목"

    def test_state_trading_halt(self):
        assert to_display_reason("state=거래정지") == "거래정지"

    def test_order_warning(self):
        assert to_display_reason("정리매매") == "정리매매"

    def test_preferred_stock_by_name(self):
        assert to_display_reason("우선주(종목명)-우B") == "우선주"

    def test_preferred_stock_english(self):
        assert to_display_reason("우선주(영문표기)-PREFERRED") == "우선주"

    def test_audit(self):
        assert to_display_reason("감리=감리지정") == "감리지정"

    def test_spac(self):
        assert to_display_reason("스팩") == "스팩"

    def test_unmapped_returns_raw(self):
        """매핑에 없는 사유는 raw 그대로 반환 (P21 투명성 — 최소 정보 전달)."""
        assert to_display_reason("상장주식수비정상=0") == "상장주식수비정상=0"
