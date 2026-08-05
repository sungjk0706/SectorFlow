"""_handle_nws_news() 단위 테스트 — NWS 실시간 뉴스 핸들러 검증.

키워드 매칭, 종목코드 파싱, 매수후보 외 종목 필터링, 빈값 스킵 로직, news-hit 브로드캐스트 검증.
A안: boost_news_on=False 시 감지 자체 수행 안 함 (📰 안 뜸, 알림 안 옴, 가산점 안 더함).
수정안 1: master_stocks_cache → sector_summary_cache.buy_targets 기준 필터링.
수정안 3: news-hit payload에 boost_scores(재계산된 총합) 포함.
hang 방지 원칙: engine_state.state를 MagicMock으로 대체, 실제 asyncio 객체 사용 금지.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.domain.models import BuyTarget, SectorSummary, StockScore


def _make_buy_target(code: str, name: str = "", *, guard_pass: bool = True) -> BuyTarget:
    """테스트용 BuyTarget 생성 — 실제 StockScore dataclass 사용 (calculate_boost_score 호환)."""
    stock = StockScore(
        code=code, name=name, sector="테스트", change_rate=0.0,
        trade_amount=0, avg_amt_5d=0, strength=0.0, cur_price=None,
        guard_pass=guard_pass,
    )
    return BuyTarget(rank=1, sector_rank=1, stock=stock)


def _make_sector_summary(codes: list[tuple[str, str]]) -> SectorSummary:
    """codes: [(code, name), ...] → buy_targets 포함 SectorSummary 생성."""
    targets = [_make_buy_target(cd, nm) for cd, nm in codes]
    return SectorSummary(sectors=[], buy_targets=targets, blocked_targets=[])


@pytest.fixture
def _mock_engine_state():
    """engine_state.state를 mock으로 대체 — news 캐시/키워드/매수후보/설정.
    _safe_broadcast도 AsyncMock으로 대체해 news-hit 브로드캐스트 호출 추적 (P25 격리).
    A안: integrated_system_settings_cache["boost_news_on"] = True (기본 켜짐).
    수정안 1: sector_summary_cache.buy_targets 기준 필터링 (005930, 000660 포함).
    """
    mock_state = MagicMock()
    mock_state.news_keywords_cache = ["수주", "특허", "MOU"]
    mock_state.news_boost_score = 1.0
    mock_state.news_boost_ttl_sec = 300
    # P10 SSOT — news_boost는 master_stocks_cache[code] 필드로 통합 (별도 캐시 제거)
    mock_state.master_stocks_cache = {"005930": {}, "000660": {}}
    # A안: boost_news_on=True 기본 (토글 OFF 테스트는 개별 케이스에서 override)
    mock_state.integrated_system_settings_cache = {
        "boost_news_on": True,
        "boost_news_score": 1.0,
    }
    # 수정안 1: 매수후보 기준 필터링 — 005930, 000660이 매수후보에 포함
    mock_state.sector_summary_cache = _make_sector_summary([
        ("005930", ""), ("000660", ""),
    ])
    safe_broadcast_mock = AsyncMock()
    with patch("backend.app.services.engine_state.state", mock_state), \
         patch("backend.app.services.engine_account_notify._safe_broadcast", safe_broadcast_mock):
        mock_state._safe_broadcast = safe_broadcast_mock
        yield mock_state


# ── _handle_nws_news ──────────────────────────────────────────────────────────

class TestHandleNwsNews:
    async def test_keyword_match_updates_cache(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 대규모 수주 계약 체결", "code": "005930"})
        # P10 SSOT — news_boost는 master_stocks_cache[code] 필드
        assert _mock_engine_state.master_stocks_cache["005930"]["news_boost"] == 1.0
        assert _mock_engine_state.master_stocks_cache["005930"]["news_boost_ts"] is not None

    async def test_empty_title_skipped(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "", "code": "005930"})
        assert all("news_boost" not in e for e in _mock_engine_state.master_stocks_cache.values())

    async def test_empty_code_skipped(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 수주", "code": ""})
        assert all("news_boost" not in e for e in _mock_engine_state.master_stocks_cache.values())

    async def test_no_keyword_match_skipped(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 실적 발표", "code": "005930"})
        assert all("news_boost" not in e for e in _mock_engine_state.master_stocks_cache.values())

    async def test_empty_keywords_skipped(self, _mock_engine_state):
        _mock_engine_state.news_keywords_cache = []
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
        assert all("news_boost" not in e for e in _mock_engine_state.master_stocks_cache.values())

    async def test_multiple_codes_parsed(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 SK하이닉스 수주", "code": "005930 000660"})
        assert _mock_engine_state.master_stocks_cache["005930"]["news_boost"] == 1.0
        assert _mock_engine_state.master_stocks_cache["000660"]["news_boost"] == 1.0

    async def test_multiple_codes_comma_separated(self, _mock_engine_state):
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 SK하이닉스 수주", "code": "005930,000660"})
        assert _mock_engine_state.master_stocks_cache["005930"]["news_boost"] == 1.0
        assert _mock_engine_state.master_stocks_cache["000660"]["news_boost"] == 1.0

    async def test_stock_not_in_buy_targets_ignored(self, _mock_engine_state):
        """수정안 1 — 매수후보에 없는 종목(999999)은 가산점 미부여 (master_stocks_cache 무관)."""
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "미래에셋 수주", "code": "005930 999999"})
        assert _mock_engine_state.master_stocks_cache["005930"]["news_boost"] == 1.0
        # 999999는 master_stocks_cache에 없음 (매수후보 외 종목)
        assert "999999" not in _mock_engine_state.master_stocks_cache

    async def test_boost_news_on_off_skips_detection(self, _mock_engine_state):
        """A안 — boost_news_on=False 시 감지 자체 수행 안 함 (📰 안 뜸, 알림 안 옴, 가산점 안 더함)."""
        _mock_engine_state.integrated_system_settings_cache = {"boost_news_on": False}
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 대규모 수주", "code": "005930"})
        assert all("news_boost" not in e for e in _mock_engine_state.master_stocks_cache.values())
        _mock_engine_state._safe_broadcast.assert_not_awaited()

    async def test_exception_does_not_propagate(self, _mock_engine_state):
        """P25 격리된 실패 — 핸들러 예외 시 호출자로 전파 차단."""
        _mock_engine_state.news_keywords_cache = Exception("boom")
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        # 예외 발생해도 함수는 정상 반환해야 함 (P25)
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})

    # ── news-hit 브로드캐스트 (세션 2 + 수정안 3) ──────────────────────────────

    async def test_news_hit_broadcast_on_match(self, _mock_engine_state):
        """호재 매칭 시 news-hit 이벤트 1회 브로드캐스트 + payload 검증 (P10 단일 전달 경로)."""
        _mock_engine_state.master_stocks_cache = {
            "005930": {"name": "삼성전자"},
            "000660": {"name": "SK하이닉스"},
        }
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 SK하이닉스 수주 계약", "code": "005930 000660"})
        _mock_engine_state._safe_broadcast.assert_awaited_once()
        call = _mock_engine_state._safe_broadcast.await_args
        assert call.args[0] == "news-hit"
        payload = call.args[1]
        assert payload["codes"] == ["005930", "000660"]
        assert payload["names"] == ["삼성전자", "SK하이닉스"]
        assert payload["scores"] == [1.0, 1.0]
        assert payload["title"] == "삼성전자 SK하이닉스 수주 계약"
        # 수정안 3: boost_scores 포함 (재계산된 총합, codes와 동일 순서)
        assert "boost_scores" in payload
        assert len(payload["boost_scores"]) == 2
        # 뉴스 가산점 1.0만 활성 (다른 가산점 OFF) → boost_score = 1.0
        assert payload["boost_scores"] == [1.0, 1.0]

    async def test_news_hit_not_broadcast_when_no_hit(self, _mock_engine_state):
        """hit_codes 빈 경우(키워드 미매칭·매수후보 외) news-hit 미전송."""
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        # 키워드 미매칭
        await _handle_nws_news({"title": "삼성전자 실적 발표", "code": "005930"})
        # 매수후보 외 종목
        await _handle_nws_news({"title": "미래에셋 수주", "code": "999999"})
        _mock_engine_state._safe_broadcast.assert_not_awaited()

    async def test_news_hit_names_empty_string_when_name_missing(self, _mock_engine_state):
        """종목명 부재 시 빈 문자열 (P20 명시적 값, 폴백 아님)."""
        # fixture 기본 master_stocks_cache는 name 키 없는 빈 dict
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
        payload = _mock_engine_state._safe_broadcast.await_args.args[1]
        assert payload["names"] == [""]

    async def test_news_hit_broadcast_failure_does_not_block(self, _mock_engine_state):
        """P25 격리 — _safe_broadcast 실패 시에도 캐시 갱신·로그 정상 완료."""
        _mock_engine_state._safe_broadcast.side_effect = RuntimeError("ws down")
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        # _safe_broadcast가 예외를 던지면(실제 _safe_broadcast는 내부에서 잡지만,
        # 본 테스트는 핸들러가 예외에 블로킹되지 않음을 검증) 캐시 갱신은 완료되어야 함.
        # 실제 _safe_broadcast는 예외를 잡아 warning 로그 후 반환하므로 side_effect 설정 시
        # 핸들러가 예외를 잡아 처리(P25)하는지 검증.
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
        assert _mock_engine_state.master_stocks_cache["005930"]["news_boost"] == 1.0

    async def test_boost_scores_reflected_in_buy_target_stock(self, _mock_engine_state):
        """수정안 3 — _recompute_boost_scores_for_hits가 bt.stock.boost_score 갱신 (P10 SSOT)."""
        from backend.app.pipelines.pipeline_compute_tick_handlers import (
            _handle_nws_news,
        )
        await _handle_nws_news({"title": "삼성전자 수주", "code": "005930"})
        ss = _mock_engine_state.sector_summary_cache
        samsung = next(bt for bt in ss.buy_targets if bt.stock.code == "005930")
        assert samsung.stock.boost_score == 1.0
        assert samsung.stock.boost_news_triggered is True
