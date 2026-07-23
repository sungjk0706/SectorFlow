"""_handle_nws_news() 단위 테스트 — NWS 실시간 뉴스 핸들러 검증.

키워드 매칭, 종목코드 파싱, 매수후보 외 종목 필터링, 빈값 스킵 로직 검증.
hang 방지 원칙: engine_state.state를 MagicMock으로 대체, 실제 asyncio 객체 사용 금지.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def _mock_engine_state():
    """engine_state.state를 mock으로 대체 — news 캐시/키워드/master_stocks_cache."""
    mock_state = MagicMock()
    mock_state.news_boost_cache = {}
    mock_state.news_keywords_cache = ["수주", "특허", "MOU"]
    mock_state.news_boost_score = 1.0
    mock_state.news_boost_ttl_sec = 300
    mock_state.master_stocks_cache = {"005930": {}, "000660": {}}
    with patch("backend.app.services.engine_state.state", mock_state):
        yield mock_state


# ── _handle_nws_news ──────────────────────────────────────────────────────────

class TestHandleNwsNews:
    async def test_keyword_match_updates_cache(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 대규모 수주 계약 체결", "code": "005930"})
        assert "005930" in _mock_engine_state.news_boost_cache
        score, _ts = _mock_engine_state.news_boost_cache["005930"]
        assert score == 1.0

    async def test_empty_title_skipped(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "", "code": "005930"})
        assert _mock_engine_state.news_boost_cache == {}

    async def test_empty_code_skipped(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 수주", "code": ""})
        assert _mock_engine_state.news_boost_cache == {}

    async def test_no_keyword_match_skipped(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 실적 발표", "code": "005930"})
        assert _mock_engine_state.news_boost_cache == {}

    async def test_empty_keywords_skipped(self, _mock_engine_state):
        _mock_engine_state.news_keywords_cache = []
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
        assert _mock_engine_state.news_boost_cache == {}

    async def test_multiple_codes_parsed(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 SK하이닉스 수주", "code": "005930 000660"})
        assert "005930" in _mock_engine_state.news_boost_cache
        assert "000660" in _mock_engine_state.news_boost_cache

    async def test_multiple_codes_comma_separated(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 SK하이닉스 수주", "code": "005930,000660"})
        assert "005930" in _mock_engine_state.news_boost_cache
        assert "000660" in _mock_engine_state.news_boost_cache

    async def test_stock_not_in_master_cache_ignored(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "미래에셋 수주", "code": "005930 999999"})
        assert "005930" in _mock_engine_state.news_boost_cache
        assert "999999" not in _mock_engine_state.news_boost_cache

    async def test_exception_does_not_propagate(self, _mock_engine_state):
        """P25 격리된 실패 — 핸들러 예외 시 호출자로 전파 차단."""
        _mock_engine_state.news_keywords_cache = Exception("boom")
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        # 예외 발생해도 함수는 정상 반환해야 함 (P25)
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
