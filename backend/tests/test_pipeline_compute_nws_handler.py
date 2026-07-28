"""_handle_nws_news() 단위 테스트 — NWS 실시간 뉴스 핸들러 검증.

키워드 매칭, 종목코드 파싱, 매수후보 외 종목 필터링, 빈값 스킵 로직, news-hit 브로드캐스트 검증.
hang 방지 원칙: engine_state.state를 MagicMock으로 대체, 실제 asyncio 객체 사용 금지.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def _mock_engine_state():
    """engine_state.state를 mock으로 대체 — news 캐시/키워드/master_stocks_cache.
    _safe_broadcast도 AsyncMock으로 대체해 news-hit 브로드캐스트 호출 추적 (P25 격리).
    """
    mock_state = MagicMock()
    mock_state.news_boost_cache = {}
    mock_state.news_keywords_cache = ["수주", "특허", "MOU"]
    mock_state.news_boost_score = 1.0
    mock_state.news_boost_ttl_sec = 300
    mock_state.master_stocks_cache = {"005930": {}, "000660": {}}
    safe_broadcast_mock = AsyncMock()
    with patch("backend.app.services.engine_state.state", mock_state), \
         patch("backend.app.services.engine_account_notify._safe_broadcast", safe_broadcast_mock):
        mock_state._safe_broadcast = safe_broadcast_mock
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

    # ── news-hit 브로드캐스트 (세션 2) ─────────────────────────────────────────

    async def test_news_hit_broadcast_on_match(self, _mock_engine_state):
        """호재 매칭 시 news-hit 이벤트 1회 브로드캐스트 + payload 검증 (P10 단일 전달 경로)."""
        _mock_engine_state.master_stocks_cache = {
            "005930": {"name": "삼성전자"},
            "000660": {"name": "SK하이닉스"},
        }
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 SK하이닉스 수주 계약", "code": "005930 000660"})
        _mock_engine_state._safe_broadcast.assert_awaited_once()
        call = _mock_engine_state._safe_broadcast.await_args
        assert call.args[0] == "news-hit"
        payload = call.args[1]
        assert payload["codes"] == ["005930", "000660"]
        assert payload["names"] == ["삼성전자", "SK하이닉스"]
        assert payload["scores"] == [1.0, 1.0]
        assert payload["title"] == "삼성전자 SK하이닉스 수주 계약"

    async def test_news_hit_not_broadcast_when_no_hit(self, _mock_engine_state):
        """hit_codes 빈 경우(키워드 미매칭·매수후보 외) news-hit 미전송."""
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        # 키워드 미매칭
        await _handle_nws_news({"title": "삼성전자 실적 발표", "code": "005930"})
        # 매수후보 외 종목
        await _handle_nws_news({"title": "미래에셋 수주", "code": "999999"})
        _mock_engine_state._safe_broadcast.assert_not_awaited()

    async def test_news_hit_names_empty_string_when_name_missing(self, _mock_engine_state):
        """종목명 부재 시 빈 문자열 (P20 명시적 값, 폴백 아님)."""
        # fixture 기본 master_stocks_cache는 name 키 없는 빈 dict
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
        payload = _mock_engine_state._safe_broadcast.await_args.args[1]
        assert payload["names"] == [""]

    async def test_news_hit_broadcast_failure_does_not_block(self, _mock_engine_state):
        """P25 격리 — _safe_broadcast 실패 시에도 캐시 갱신·로그 정상 완료."""
        _mock_engine_state._safe_broadcast.side_effect = RuntimeError("ws down")
        from backend.app.pipelines.pipeline_compute_tick_handlers import _handle_nws_news
        # _safe_broadcast가 예외를 던지면(실제 _safe_broadcast는 내부에서 잡지만,
        # 본 테스트는 핸들러가 예외에 블로킹되지 않음을 검증) 캐시 갱신은 완료되어야 함.
        # 실제 _safe_broadcast는 예외를 잡아 warning 로그 후 반환하므로 side_effect 설정 시
        # 핸들러가 예외를 잡아 처리(P25)하는지 검증.
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
        assert "005930" in _mock_engine_state.news_boost_cache
