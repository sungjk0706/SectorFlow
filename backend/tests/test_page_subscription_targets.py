"""page_subscription_targets.py 단위 테스트 — 화면별 구독 대상 저장소.

태스크 1세션(백엔드 대상 관리) 7절 요구사항 13개 전수 검증.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.services.page_subscription_targets import (
    page_targets,
    PageTargetRegistry,
    ALLOWED_PAGE_KEYS,
    STOCK_SUBSCRIPTION_PAGES,
    PAGE_SECTOR_RANKING,
    PAGE_BUY_TARGET,
    PAGE_SELL_POSITION,
    PAGE_PROFIT_OVERVIEW,
    PAGE_PROFIT_DETAIL,
    PAGE_STOCK_CLASSIFICATION,
    PAGE_STOCK_DETAIL,
    PAGE_SETTINGS,
    initialize_page_targets,
    refresh_page_targets,
)


# ── 공통 fixture ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_registry():
    """각 테스트 전 저장소 초기화 — 상태 누출 방지."""
    page_targets.reset()
    yield
    page_targets.reset()


def _mock_state(**overrides):
    """engine_state.state mock 생성."""
    mock = MagicMock()
    mock.master_stocks_cache = overrides.get("master_stocks_cache", {"005930": {"name": "삼성전자"}})
    mock.sector_summary_cache = overrides.get("sector_summary_cache", None)
    mock.integrated_system_settings_cache = overrides.get(
        "integrated_system_settings_cache", {"trade_mode": "virtual"}
    )
    mock.account_rest_bootstrapped = overrides.get("account_rest_bootstrapped", False)
    mode = str(mock.integrated_system_settings_cache.get("trade_mode", "virtual"))
    mock.account_context_mode = overrides.get("account_context_mode", mode)
    default_ready = mode == "virtual" or bool(mock.account_rest_bootstrapped)
    mock.account_context_ready = overrides.get("account_context_ready", default_ready)
    mock.account_context_reason = overrides.get("account_context_reason", "" if mode == "virtual" else "잔고 확인 미완료")
    mock.sector_summary_ready_event = overrides.get("sector_summary_ready_event", MagicMock(is_set=MagicMock(return_value=True)))
    return mock


# ── 1. 종목 실시간 4화면 대상 원본에서 코드 정확 추출 ──────────────────────

class TestStockSubscriptionDerivation:
    """종목 실시간 구독 4화면 — 원본에서 코드가 정확히 추출되는지."""

    async def test_sector_ranking_extracts_filter_codes(self):
        """업종 순위 — 기존 필터 계산 결과(all_filter_codes)에서 코드 추출."""
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"A": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["005930", "000660"]})):
            results = await reg.refresh("테스트", {PAGE_SECTOR_RANKING})
        assert results[PAGE_SECTOR_RANKING].ready
        assert reg.get_codes(PAGE_SECTOR_RANKING) == ["000660", "005930"]  # 정렬

    async def test_buy_target_extracts_target_codes(self):
        """매수 후보 — 기존 매수 후보 조회 결과에서 코드만 추출."""
        reg = PageTargetRegistry()
        ss = MagicMock()
        with patch("backend.app.services.engine_state.state", _mock_state(sector_summary_cache=ss)), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   new=AsyncMock(return_value=[{"code": "005930"}, {"code": "000660"}])):
            results = await reg.refresh("테스트", {PAGE_BUY_TARGET})
        assert results[PAGE_BUY_TARGET].ready
        assert reg.get_codes(PAGE_BUY_TARGET) == ["000660", "005930"]

    async def test_sell_position_extracts_positive_qty_codes(self):
        """보유 종목 — 기존 보유 목록에서 수량 양수 코드만 추출."""
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.get_held_codes",
                   new=AsyncMock(return_value={"005930", "000660"})):
            results = await reg.refresh("테스트", {PAGE_SELL_POSITION})
        assert results[PAGE_SELL_POSITION].ready
        assert reg.get_codes(PAGE_SELL_POSITION) == ["000660", "005930"]

    async def test_profit_overview_shares_hold_codes(self):
        """수익 현황 — 보유 종목 대상 집합을 재사용 (같은 원본 결과)."""
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.get_held_codes",
                   new=AsyncMock(return_value={"005930", "000660"})):
            results = await reg.refresh("테스트", {PAGE_SELL_POSITION, PAGE_PROFIT_OVERVIEW})
        assert results[PAGE_SELL_POSITION].ready
        assert results[PAGE_PROFIT_OVERVIEW].ready
        assert reg.get_codes(PAGE_PROFIT_OVERVIEW) == reg.get_codes(PAGE_SELL_POSITION)


# ── 2. 자료 중심 4화면 자료 변경 번호 정확 갱신 ────────────────────────────

class TestDataPageChangeNumber:
    """자료 중심 4화면 — 자료 변경 번호가 정확히 갱신되는지."""

    async def test_profit_detail_change_no_increments(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            r1 = await reg.refresh("이력 변경", {PAGE_PROFIT_DETAIL})
            r2 = await reg.refresh("이력 변경", {PAGE_PROFIT_DETAIL})
        assert r1[PAGE_PROFIT_DETAIL].changed
        assert r2[PAGE_PROFIT_DETAIL].changed
        assert r2[PAGE_PROFIT_DETAIL].change_no == r1[PAGE_PROFIT_DETAIL].change_no + 1

    async def test_stock_classification_change_no_increments(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            r1 = await reg.refresh("분류 변경", {PAGE_STOCK_CLASSIFICATION})
            r2 = await reg.refresh("분류 변경", {PAGE_STOCK_CLASSIFICATION})
        assert r1[PAGE_STOCK_CLASSIFICATION].changed
        assert r2[PAGE_STOCK_CLASSIFICATION].changed
        assert r2[PAGE_STOCK_CLASSIFICATION].change_no == r1[PAGE_STOCK_CLASSIFICATION].change_no + 1

    async def test_stock_detail_change_no_increments(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            r1 = await reg.refresh("일봉 갱신", {PAGE_STOCK_DETAIL})
            r2 = await reg.refresh("일봉 갱신", {PAGE_STOCK_DETAIL})
        assert r1[PAGE_STOCK_DETAIL].changed
        assert r2[PAGE_STOCK_DETAIL].changed
        assert r2[PAGE_STOCK_DETAIL].change_no == r1[PAGE_STOCK_DETAIL].change_no + 1

    async def test_settings_change_no_increments(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            r1 = await reg.refresh("설정 변경", {PAGE_SETTINGS})
            r2 = await reg.refresh("설정 변경", {PAGE_SETTINGS})
        assert r1[PAGE_SETTINGS].changed
        assert r2[PAGE_SETTINGS].changed
        assert r2[PAGE_SETTINGS].change_no == r1[PAGE_SETTINGS].change_no + 1


# ── 3. 동일 대상 재갱신 시 변경 번호 미증가 ────────────────────────────────

class TestNoChangeNoBumpOnSameCodes:
    """동일한 대상 재갱신 시 변경 번호가 올라가지 않는지."""

    async def test_same_codes_no_change_no_bump(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"A": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["005930", "000660"]})):
            r1 = await reg.refresh("1차", {PAGE_SECTOR_RANKING})
            r2 = await reg.refresh("2차 동일", {PAGE_SECTOR_RANKING})
        assert r1[PAGE_SECTOR_RANKING].changed
        assert not r2[PAGE_SECTOR_RANKING].changed
        assert r2[PAGE_SECTOR_RANKING].change_no == r1[PAGE_SECTOR_RANKING].change_no


# ── 4. 대상 추가·제거 시 이전·현재 집합 비교 정확 ──────────────────────────

class TestAddedRemovedComparison:
    """대상 추가·제거 시 이전·현재 집합 비교가 정확한지."""

    async def test_added_removed_codes_computed(self):
        reg = PageTargetRegistry()
        inputs_iter = iter([
            {"all_filter_codes": ["005930", "000660"]},
            {"all_filter_codes": ["005930", "035420"]},  # 000660 제거, 035420 추가
        ])
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"A": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(side_effect=lambda *a, **k: next(inputs_iter))):
            r1 = await reg.refresh("1차", {PAGE_SECTOR_RANKING})
            r2 = await reg.refresh("2차 변경", {PAGE_SECTOR_RANKING})
        assert r1[PAGE_SECTOR_RANKING].changed
        assert r2[PAGE_SECTOR_RANKING].changed
        assert r2[PAGE_SECTOR_RANKING].added == ["035420"]
        assert r2[PAGE_SECTOR_RANKING].removed == ["000660"]


# ── 5. 설정 변경으로 필터 대상 변경 시 새 대상 저장 ────────────────────────

class TestSettingsChangeUpdatesFilter:
    """설정 변경으로 필터 대상이 바뀌는 경우 새 대상이 저장되는지."""

    async def test_settings_change_new_filter_codes_stored(self):
        reg = PageTargetRegistry()
        inputs_iter = iter([
            {"all_filter_codes": ["005930"]},
            {"all_filter_codes": ["005930", "000660"]},  # 설정 변경 후 필터 확장
        ])
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"A": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(side_effect=lambda *a, **k: next(inputs_iter))):
            await reg.refresh("초기", {PAGE_SECTOR_RANKING})
            r2 = await reg.refresh("설정 변경", {PAGE_SECTOR_RANKING})
        assert r2[PAGE_SECTOR_RANKING].changed
        assert reg.get_codes(PAGE_SECTOR_RANKING) == ["000660", "005930"]


# ── 6. 매수 후보 변경으로 대상 변경 시 새 대상 저장 ────────────────────────

class TestBuyTargetChangeUpdates:
    """매수 후보 변경으로 대상이 바뀌는 경우 새 대상이 저장되는지."""

    async def test_buy_target_change_new_codes_stored(self):
        reg = PageTargetRegistry()
        targets_iter = iter([
            [{"code": "005930"}],
            [{"code": "005930"}, {"code": "000660"}],
        ])
        ss = MagicMock()
        with patch("backend.app.services.engine_state.state", _mock_state(sector_summary_cache=ss)), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   new=AsyncMock(side_effect=lambda *a, **k: next(targets_iter))):
            await reg.refresh("초기", {PAGE_BUY_TARGET})
            r2 = await reg.refresh("매수 후보 변경", {PAGE_BUY_TARGET})
        assert r2[PAGE_BUY_TARGET].changed
        assert reg.get_codes(PAGE_BUY_TARGET) == ["000660", "005930"]


# ── 7. 보유 종목 추가·부분 매도·전량 매도 ──────────────────────────────────

class TestHoldPositionChanges:
    """보유 종목 추가·부분 매도·전량 매도에서 보유 대상이 정확히 바뀌는지."""

    async def test_hold_add(self):
        reg = PageTargetRegistry()
        held_iter = iter([{"005930"}, {"005930", "000660"}])
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.get_held_codes",
                   new=AsyncMock(side_effect=lambda *a, **k: next(held_iter))):
            await reg.refresh("초기", {PAGE_SELL_POSITION})
            r2 = await reg.refresh("보유 추가", {PAGE_SELL_POSITION})
        assert r2[PAGE_SELL_POSITION].changed
        assert r2[PAGE_SELL_POSITION].added == ["000660"]

    async def test_hold_partial_sell(self):
        reg = PageTargetRegistry()
        # 005930 수량 0으로 부분 매도 → 제거
        held_iter = iter([{"005930", "000660"}, {"000660"}])
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.get_held_codes",
                   new=AsyncMock(side_effect=lambda *a, **k: next(held_iter))):
            await reg.refresh("초기", {PAGE_SELL_POSITION})
            r2 = await reg.refresh("부분 매도", {PAGE_SELL_POSITION})
        assert r2[PAGE_SELL_POSITION].changed
        assert r2[PAGE_SELL_POSITION].removed == ["005930"]

    async def test_hold_full_sell(self):
        reg = PageTargetRegistry()
        # 전량 매도 → 빈 집합 (실제 빈 대상 — ready 유지)
        held_iter = iter([{"005930"}, set()])
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.get_held_codes",
                   new=AsyncMock(side_effect=lambda *a, **k: next(held_iter))):
            await reg.refresh("초기", {PAGE_SELL_POSITION})
            r2 = await reg.refresh("전량 매도", {PAGE_SELL_POSITION})
        assert r2[PAGE_SELL_POSITION].changed
        assert reg.get_codes(PAGE_SELL_POSITION) == []
        assert reg.is_ready(PAGE_SELL_POSITION)  # 실제 빈 대상 — ready 유지


# ── 8. 매수·매도 이력 변경이 이력 자료 변경 번호만 갱신 ──────────────────────

class TestTradeHistoryOnlyUpdatesHistoryPage:
    """매수·매도 이력 변경이 이력 자료 변경 번호만 갱신하는지."""

    async def test_trade_history_change_does_not_touch_other_data_pages(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            # 이력 화면만 갱신
            r = await reg.refresh("이력 변경", {PAGE_PROFIT_DETAIL})
        assert r[PAGE_PROFIT_DETAIL].changed
        # 다른 자료 화면은 갱신되지 않음 — 상태 미생성
        assert reg.get(PAGE_STOCK_CLASSIFICATION) is None
        assert reg.get(PAGE_SETTINGS) is None


# ── 9. 분류 변경이 분류 자료 변경 번호만 갱신 ──────────────────────────────

class TestClassificationChangeOnlyUpdatesClassificationPage:
    """분류 변경이 분류 자료 변경 번호만 갱신하는지."""

    async def test_classification_change_does_not_touch_other_data_pages(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            r = await reg.refresh("분류 변경", {PAGE_STOCK_CLASSIFICATION})
        assert r[PAGE_STOCK_CLASSIFICATION].changed
        assert reg.get(PAGE_PROFIT_DETAIL) is None
        assert reg.get(PAGE_SETTINGS) is None


# ── 10. 장 마감 일봉 갱신이 일봉 자료 변경 번호를 갱신 ──────────────────────

class TestDailyBarsChangeUpdatesStockDetail:
    """장 마감 일봉 갱신이 일봉 자료 변경 번호를 갱신하는지."""

    async def test_daily_bars_change_increments_stock_detail_change_no(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            r1 = await reg.refresh("일봉 갱신 1", {PAGE_STOCK_DETAIL})
            r2 = await reg.refresh("일봉 갱신 2", {PAGE_STOCK_DETAIL})
        assert r1[PAGE_STOCK_DETAIL].change_no < r2[PAGE_STOCK_DETAIL].change_no


# ── 11. 설정 변경이 마스킹 설정 스냅샷(변경 번호)을 갱신 ────────────────────

class TestSettingsChangeUpdatesSettingsPage:
    """설정 변경이 마스킹 설정 스냅샷(변경 번호)을 갱신하는지."""

    async def test_settings_change_increments_settings_change_no(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            r1 = await reg.refresh("설정 변경 1", {PAGE_SETTINGS})
            r2 = await reg.refresh("설정 변경 2", {PAGE_SETTINGS})
        assert r1[PAGE_SETTINGS].change_no < r2[PAGE_SETTINGS].change_no


# ── 12. 계산 실패 시 이전 정상 상태 빈 목록 덮어쓰지 않음 ──────────────────

class TestFailurePreservesPreviousState:
    """계산 실패 시 이전 정상 상태를 빈 목록으로 덮어쓰지 않는지."""

    async def test_derive_failure_preserves_previous_codes(self):
        reg = PageTargetRegistry()
        inputs_iter = iter([
            {"all_filter_codes": ["005930", "000660"]},
            RuntimeError("원본 조회 실패"),
            {"all_filter_codes": ["005930", "000660"]},  # 복구 — 동일 대상
        ])
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"A": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(side_effect=lambda *a, **k: next(inputs_iter))):
            r1 = await reg.refresh("초기", {PAGE_SECTOR_RANKING})
            r_fail = await reg.refresh("실패", {PAGE_SECTOR_RANKING})
            r3 = await reg.refresh("복구", {PAGE_SECTOR_RANKING})
        assert r1[PAGE_SECTOR_RANKING].changed
        assert r_fail[PAGE_SECTOR_RANKING].failed
        assert not r_fail[PAGE_SECTOR_RANKING].changed
        # 이전 정상 대상 보존
        assert reg.get_codes(PAGE_SECTOR_RANKING) == ["000660", "005930"]
        # 복구 시 동일 대상 — 변경 번호 미증가
        assert not r3[PAGE_SECTOR_RANKING].changed
        assert reg.is_ready(PAGE_SECTOR_RANKING)

    async def test_source_not_ready_does_not_overwrite_with_empty(self):
        """원본 미준비 시 빈 목록으로 덮어쓰지 않음."""
        reg = PageTargetRegistry()
        # 1차: 캐시 있음 → 대상 생성
        # 2차: 캐시 비어있음 → 원본 미준비 → 이전 대상 유지
        cache_iter = iter([{"A": {}}, {}])
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.master_stocks_cache = next(cache_iter)
            mock_state.sector_summary_cache = None
            mock_state.integrated_system_settings_cache = {"trade_mode": "virtual"}
            mock_state.account_rest_bootstrapped = False
            with patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                       new=AsyncMock(return_value={"all_filter_codes": ["005930"]})):
                r1 = await reg.refresh("초기", {PAGE_SECTOR_RANKING})
                # 캐시 비움
                mock_state.master_stocks_cache = next(cache_iter)
                r2 = await reg.refresh("캐시 비어있음", {PAGE_SECTOR_RANKING})
        assert r1[PAGE_SECTOR_RANKING].ready
        assert not r2[PAGE_SECTOR_RANKING].ready
        # 이전 대상 보존 — 빈 목록으로 덮어쓰지 않음
        assert reg.get_codes(PAGE_SECTOR_RANKING) == ["005930"]


# ── 13. 페이지 대상 8개 외 키 저장되지 않음 ────────────────────────────────

class TestInvalidPageKeyRejected:
    """페이지 대상 8개 외의 키가 저장되지 않는지."""

    async def test_invalid_page_key_not_stored(self):
        reg = PageTargetRegistry()
        results = await reg.refresh("테스트", {"invalid-page", PAGE_SETTINGS})
        assert "invalid-page" not in results
        assert reg.get("invalid-page") is None

    def test_get_invalid_page_returns_none(self):
        reg = PageTargetRegistry()
        assert reg.get("unknown") is None
        assert reg.get_codes("unknown") == []
        assert reg.get_change_no("unknown") == 0
        assert not reg.is_ready("unknown")

    async def test_ensure_state_rejects_invalid_key(self):
        reg = PageTargetRegistry()
        assert reg._ensure_state("invalid") is None
        assert "invalid" not in reg._states


# ── 보충: 초기 생성·재기동·전체 갱신 ──────────────────────────────────────

class TestInitializeAll:
    """초기 생성 — 재기동 시 이전 메모리 목록 신뢰 안 함, 원본에서 재구축."""

    async def test_initialize_all_resets_and_rebuilds(self):
        reg = PageTargetRegistry()
        # 1차: 대상 생성
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"A": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["005930"]})):
            await reg.refresh("1차", {PAGE_SECTOR_RANKING})
        assert reg.get_codes(PAGE_SECTOR_RANKING) == ["005930"]
        # 2차: initialize_all — reset 후 재구축 (다른 대상)
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"B": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["000660"]})):
            await reg.initialize_all("재기동")
        assert reg.get_codes(PAGE_SECTOR_RANKING) == ["000660"]

    async def test_initialize_all_creates_all_allowed_pages(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": []})), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   new=AsyncMock(return_value=[])):
            await reg.initialize_all("초기")
        # 8개 화면 전부 상태 생성
        for page in ALLOWED_PAGE_KEYS:
            assert reg.get(page) is not None, f"{page} 상태 미생성"


class TestInitializePageTargetsEntryPoint:
    """initialize_page_targets 진입점 — 엔진 미실행 시 생략, 준비 대기."""

    async def test_engine_not_running_skips(self):
        with patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=False):
            await initialize_page_targets()
        # 초기화 생략 — 상태 미생성
        assert page_targets.get(PAGE_SECTOR_RANKING) is None

    async def test_waits_for_sector_summary_ready(self):
        ready_event = MagicMock()
        ready_event.is_set = MagicMock(return_value=False)
        ready_event.wait = AsyncMock()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=True), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True), \
             patch("backend.app.services.engine_account.get_held_codes", new=AsyncMock(return_value=set())), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": []})), \
             patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   new=AsyncMock(return_value=[])):
            mock_state.sector_summary_ready_event = ready_event
            mock_state.master_stocks_cache = {"A": {}}
            mock_state.sector_summary_cache = MagicMock()
            mock_state.integrated_system_settings_cache = {"trade_mode": "virtual"}
            mock_state.account_rest_bootstrapped = False
            await initialize_page_targets()
        ready_event.wait.assert_awaited_once()

    async def test_failure_does_not_raise(self):
        """초기 생성 실패 시 예외 전파 없이 로깅만."""
        with patch("backend.app.services.engine_lifecycle.is_engine_running", return_value=True), \
             patch("backend.app.services.engine_state.state", side_effect=RuntimeError("boom")):
            # 예외 발생하지 않음
            await initialize_page_targets()


class TestRefreshPageTargetsEntryPoint:
    """refresh_page_targets 공통 진입점."""

    async def test_refresh_entry_point_returns_results(self):
        with patch("backend.app.services.engine_state.state", _mock_state()):
            results = await refresh_page_targets("테스트", {PAGE_SETTINGS})
        assert PAGE_SETTINGS in results
        assert results[PAGE_SETTINGS].changed


# ── 보충: 자료 유형·상태 필드 ──────────────────────────────────────────────

class TestPageStateFields:
    """각 대상 상태 필드 — 자료 유형·준비 여부·갱신 원인."""

    async def test_data_type_assigned_correctly(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            await reg.refresh("테스트", ALLOWED_PAGE_KEYS)
        for page in STOCK_SUBSCRIPTION_PAGES:
            st = reg.get(page)
            assert st is not None
            assert st.data_type == "stock-subscription"
        assert reg.get(PAGE_PROFIT_DETAIL).data_type == "trade-history"
        assert reg.get(PAGE_STOCK_CLASSIFICATION).data_type == "classification"
        assert reg.get(PAGE_STOCK_DETAIL).data_type == "daily-bars"
        assert reg.get(PAGE_SETTINGS).data_type == "settings"

    async def test_last_update_reason_recorded(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state()):
            await reg.refresh("설정 저장", {PAGE_SETTINGS})
        assert reg.get(PAGE_SETTINGS).last_update_reason == "설정 저장"

    async def test_codes_sorted_stable(self):
        """코드 목록 순서 안정화 — 정렬."""
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state", _mock_state(master_stocks_cache={"A": {}})), \
             patch("backend.app.services.sector_data_provider.get_sector_summary_inputs",
                   new=AsyncMock(return_value={"all_filter_codes": ["005930", "000660", "035420"]})):
            await reg.refresh("테스트", {PAGE_SECTOR_RANKING})
        assert reg.get_codes(PAGE_SECTOR_RANKING) == ["000660", "005930", "035420"]


# ── 보충: 실전매매 보유 종목 준비 상태 ────────────────────────────────────

class TestRealModeHoldReadiness:
    """실전매매 — 잔고 조회 전 보유 종목 미준비, 조회 후 준비."""

    async def test_real_mode_not_bootstrapped_not_ready(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state",
                   _mock_state(integrated_system_settings_cache={"trade_mode": "live"},
                               account_rest_bootstrapped=False)), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=False):
            r = await reg.refresh("초기", {PAGE_SELL_POSITION})
        assert not r[PAGE_SELL_POSITION].ready
        assert not r[PAGE_SELL_POSITION].changed

    async def test_real_mode_bootstrapped_ready(self):
        reg = PageTargetRegistry()
        with patch("backend.app.services.engine_state.state",
                   _mock_state(integrated_system_settings_cache={"trade_mode": "live"},
                               account_rest_bootstrapped=True)), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_account.get_held_codes",
                   new=AsyncMock(return_value={"005930"})):
            r = await reg.refresh("잔고 조회 후", {PAGE_SELL_POSITION})
        assert r[PAGE_SELL_POSITION].ready
        assert reg.get_codes(PAGE_SELL_POSITION) == ["005930"]
