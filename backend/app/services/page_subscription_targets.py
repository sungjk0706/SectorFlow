# -*- coding: utf-8 -*-
"""화면별 구독 대상 저장소 — 페이지 이름 기반 대상 관리.

프론트엔드가 종목 코드를 직접 보내지 않고 화면 이름만 전달할 수 있도록,
백엔드가 화면에 맞는 대상 자료를 한 곳에서 관리한다.

저장 원칙 (태스크 1세션):
  - 실제 종목 자료·실시간 값은 기존 마스터 캐시·sector_summary_cache·positions 원본을 그대로 쓴다.
  - 이 저장소에는 화면용 종목 전체 자료를 복사하지 않고
    "페이지별 대상 코드 집합·준비 상태·변경 번호"만 보관한다.
  - 보유 종목 대상은 보유 종목·수익 현황 두 화면이 같은 원본 결과를 공유한다.
  - 페이지별 대상 집합은 파생 결과이며 직접 수정하는 진실 소스로 만들지 않는다.
  - 계산되지 않은 상태와 대상이 실제로 없는 상태를 구분한다.

갱신 원칙:
  - 원본 변경 이벤트에서만 갱신 (폴링 금지).
  - 이전 대상과 새 대상이 같으면 변경 번호를 올리지 않는다.
  - 대상이 달라지면 변경 번호를 올리고 추가·제거 코드를 비교한다.
  - 계산 실패 시 이전 정상 대상을 빈 목록으로 덮어쓰지 않고 실패 상태를 기록한다.

범위 (1세션): 대상 관리·갱신 진입점·초기 생성만.
  WebSocket 전달·재연결·프론트엔드 전환은 2·3세션에서 연결한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.app.services import engine_state

logger = logging.getLogger(__name__)

# ── 화면 키·자료 유형 (단일 진실 소스) ──────────────────────────────────────

PAGE_SECTOR_RANKING = "sector-ranking"
PAGE_BUY_TARGET = "buy-target"
PAGE_SELL_POSITION = "sell-position"
PAGE_PROFIT_OVERVIEW = "profit-overview"
PAGE_PROFIT_DETAIL = "profit-detail"
PAGE_STOCK_CLASSIFICATION = "stock-classification"
PAGE_STOCK_DETAIL = "stock-detail"
PAGE_SETTINGS = "settings"

# 허용 화면 키 — 이 8개만 저장소에 생성된다.
ALLOWED_PAGE_KEYS: frozenset[str] = frozenset({
    PAGE_SECTOR_RANKING,
    PAGE_BUY_TARGET,
    PAGE_SELL_POSITION,
    PAGE_PROFIT_OVERVIEW,
    PAGE_PROFIT_DETAIL,
    PAGE_STOCK_CLASSIFICATION,
    PAGE_STOCK_DETAIL,
    PAGE_SETTINGS,
})

# 자료 유형
DATA_STOCK_SUBSCRIPTION = "stock-subscription"
DATA_TRADE_HISTORY = "trade-history"
DATA_CLASSIFICATION = "classification"
DATA_DAILY_BARS = "daily-bars"
DATA_SETTINGS = "settings"

# 화면별 자료 유형 매핑
_PAGE_DATA_TYPE: dict[str, str] = {
    PAGE_SECTOR_RANKING: DATA_STOCK_SUBSCRIPTION,
    PAGE_BUY_TARGET: DATA_STOCK_SUBSCRIPTION,
    PAGE_SELL_POSITION: DATA_STOCK_SUBSCRIPTION,
    PAGE_PROFIT_OVERVIEW: DATA_STOCK_SUBSCRIPTION,
    PAGE_PROFIT_DETAIL: DATA_TRADE_HISTORY,
    PAGE_STOCK_CLASSIFICATION: DATA_CLASSIFICATION,
    PAGE_STOCK_DETAIL: DATA_DAILY_BARS,
    PAGE_SETTINGS: DATA_SETTINGS,
}

# 종목 실시간 구독 화면 — 코드 집합을 관리한다.
STOCK_SUBSCRIPTION_PAGES: frozenset[str] = frozenset({
    PAGE_SECTOR_RANKING,
    PAGE_BUY_TARGET,
    PAGE_SELL_POSITION,
    PAGE_PROFIT_OVERVIEW,
})

# 자료 중심 화면 — 준비 상태·변경 번호만 관리한다.
DATA_PAGES: frozenset[str] = frozenset({
    PAGE_PROFIT_DETAIL,
    PAGE_STOCK_CLASSIFICATION,
    PAGE_STOCK_DETAIL,
    PAGE_SETTINGS,
})


@dataclass
class PageTargetState:
    """단일 화면의 대상 상태."""

    page: str
    data_type: str
    # 종목 실시간 구독 화면: 정렬된 코드 목록 (안정화 — 비교·전송 결과 흔들림 방지).
    # 자료 중심 화면: 빈 목록 (코드 집합 없음).
    codes: list[str] = field(default_factory=list)
    ready: bool = False
    failed: bool = False
    change_no: int = 0
    last_update_reason: str = ""

    def codes_set(self) -> set[str]:
        """코드 집합 반환 (비교용)."""
        return set(self.codes)


@dataclass
class RefreshResult:
    """단일 화면 갱신 결과 — 호출자가 후속 작업(전달·스냅샷)에 사용."""

    page: str
    changed: bool
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: bool = False
    ready: bool = False
    change_no: int = 0


class PageTargetRegistry:
    """화면별 대상 상태 저장소 — 싱글턴."""

    def __init__(self) -> None:
        self._states: dict[str, PageTargetState] = {}

    # ── 조회 ────────────────────────────────────────────────────────────

    def get(self, page: str) -> PageTargetState | None:
        """화면 상태 반환. 허용되지 않은 키는 None."""
        if page not in ALLOWED_PAGE_KEYS:
            return None
        return self._states.get(page)

    def get_codes(self, page: str) -> list[str]:
        """종목 구독 화면의 정렬된 코드 목록 반환."""
        st = self._states.get(page)
        return list(st.codes) if st else []

    def get_change_no(self, page: str) -> int:
        """자료 중심 화면의 변경 번호 반환."""
        st = self._states.get(page)
        return st.change_no if st else 0

    def is_ready(self, page: str) -> bool:
        """화면 대상 계산 완료 여부."""
        st = self._states.get(page)
        return st.ready if st else False

    def all_pages(self) -> list[str]:
        """허용 화면 키 전체 (정렬)."""
        return sorted(ALLOWED_PAGE_KEYS)

    # ── 초기화 ──────────────────────────────────────────────────────────

    def _ensure_state(self, page: str) -> PageTargetState | None:
        """허용된 화면 키의 상태 객체를 생성/반환. 허용되지 않은 키는 None."""
        if page not in ALLOWED_PAGE_KEYS:
            logger.warning("[구독대상] 허용되지 않은 화면 키 — 저장소 생성 안 함: %s", page)
            return None
        st = self._states.get(page)
        if st is None:
            st = PageTargetState(page=page, data_type=_PAGE_DATA_TYPE[page])
            self._states[page] = st
        return st

    def reset(self) -> None:
        """재기동 시 이전 메모리 대상 목록을 신뢰하지 않고 모두 비운다."""
        self._states.clear()

    # ── 갱신 ────────────────────────────────────────────────────────────

    async def refresh(self, reason: str, pages: set[str] | None = None) -> dict[str, RefreshResult]:
        """공통 대상 갱신 진입점.

        Args:
            reason: 갱신 원인 (로그·상태 기록용).
            pages: 갱신할 화면 집합. None이면 허용 화면 전체.

        Returns:
            {page: RefreshResult} — 각 화면별 갱신 결과.
            허용되지 않은 화면 키는 결과에서 제외된다.
        """
        target_pages = pages if pages is not None else set(ALLOWED_PAGE_KEYS)
        results: dict[str, RefreshResult] = {}

        # 보유 종목 대상은 보유 종목·수익 현황이 같은 원본을 공유 — 한 번만 파생.
        hold_codes: list[str] | None = None
        hold_ready: bool | None = None
        hold_failed: bool = False

        for page in sorted(target_pages):
            if page not in ALLOWED_PAGE_KEYS:
                logger.warning("[구독대상] 갱신 스킵 — 허용되지 않은 화면 키: %s", page)
                continue

            if page in STOCK_SUBSCRIPTION_PAGES:
                results[page] = await self._refresh_stock_subscription(
                    page, reason, hold_codes, hold_ready, hold_failed,
                )
                # 보유 종목 파생 결과를 수익 현황이 재사용하도록 캐싱.
                if page == PAGE_SELL_POSITION:
                    st = self._states.get(page)
                    if st is not None:
                        hold_codes = list(st.codes)
                        hold_ready = st.ready
                        hold_failed = st.failed
            else:
                results[page] = await self._refresh_data_page(page, reason)

        return results

    async def _refresh_stock_subscription(
        self,
        page: str,
        reason: str,
        hold_codes: list[str] | None,
        hold_ready: bool | None,
        hold_failed: bool,
    ) -> RefreshResult:
        """종목 실시간 구독 화면 갱신 — 코드 집합 파생·비교."""
        st = self._ensure_state(page)
        if st is None:
            return RefreshResult(page=page, changed=False, failed=True)

        try:
            new_codes, ready = await self._derive_codes(
                page, hold_codes, hold_ready, hold_failed,
            )
        except Exception as e:
            # 실패 시 이전 정상 대상 보존 — 빈 목록으로 덮어쓰지 않음.
            st.failed = True
            st.last_update_reason = f"{reason} (실패: {e})"
            logger.warning("[구독대상] %s 대상 계산 실패 — 이전 대상 유지: %s", page, e, exc_info=True)
            return RefreshResult(
                page=page, changed=False, failed=True,
                ready=st.ready, change_no=st.change_no,
            )

        if not ready:
            # 원본이 아직 준비되지 않음 — 빈 목록으로 성공 처리하지 않음.
            st.last_update_reason = f"{reason} (원본 미준비)"
            return RefreshResult(
                page=page, changed=False, failed=False,
                ready=False, change_no=st.change_no,
            )

        new_set = set(new_codes)
        prev_set = st.codes_set()
        changed = new_set != prev_set

        if changed:
            added = sorted(new_set - prev_set)
            removed = sorted(prev_set - new_set)
            st.codes = sorted(new_codes)
            st.change_no += 1
            st.failed = False
            st.ready = True
            st.last_update_reason = reason
            return RefreshResult(
                page=page, changed=True, added=added, removed=removed,
                failed=False, ready=True, change_no=st.change_no,
            )

        # 동일 대상 — 변경 번호 올리지 않음.
        st.failed = False
        st.ready = True
        st.last_update_reason = reason
        return RefreshResult(
            page=page, changed=False, failed=False,
            ready=True, change_no=st.change_no,
        )

    async def _derive_codes(
        self,
        page: str,
        hold_codes: list[str] | None,
        hold_ready: bool | None,
        hold_failed: bool,
    ) -> tuple[list[str], bool]:
        """화면별 원본에서 대상 코드 파생.

        Returns:
            (codes, ready) — ready=False면 원본 미준비 (빈 목록으로 성공 처리 금지).
        """
        if page == PAGE_SECTOR_RANKING:
            return await self._derive_sector_ranking()
        if page == PAGE_BUY_TARGET:
            return await self._derive_buy_target()
        if page == PAGE_SELL_POSITION:
            return await self._derive_hold_codes()
        if page == PAGE_PROFIT_OVERVIEW:
            # 보유 종목 대상 집합 재사용 — 아직 파생되지 않았으면 직접 파생.
            if hold_codes is not None and hold_ready is not None:
                return list(hold_codes), hold_ready
            return await self._derive_hold_codes()
        # 도달 불가 — ALLOWED_PAGE_KEYS로 제한됨.
        return [], False

    async def _derive_sector_ranking(self) -> tuple[list[str], bool]:
        """업종 순위 — 기존 필터 계산 결과(all_filter_codes) 재사용."""
        cache = engine_state.state.master_stocks_cache
        if not cache:
            return [], False
        from backend.app.services.sector_data_provider import get_sector_summary_inputs
        inputs = await get_sector_summary_inputs()
        codes = inputs.get("all_filter_codes", [])
        return list(codes), True

    async def _derive_buy_target(self) -> tuple[list[str], bool]:
        """매수 후보 — 기존 매수 후보 조회 결과에서 코드만 추출."""
        ss = engine_state.state.sector_summary_cache
        if ss is None:
            return [], False
        from backend.app.services.sector_data_provider import get_buy_targets_sector_stocks
        targets = await get_buy_targets_sector_stocks()
        codes = [str(t.get("code", "")).strip() for t in targets if t.get("code")]
        return codes, True

    async def _derive_hold_codes(self) -> tuple[list[str], bool]:
        """보유 종목 — 기존 보유 목록에서 수량 양수만 추출.

        원본 준비 여부:
          - 테스트 모드: 모의투자 보유 목록이 start_engine에서 준비되므로 ready.
          - 실전 모드: 잔고 조회(REST) 완료 후 ready. 조회 전에는 미준비.
        """
        from backend.app.core.trade_mode import is_test_mode
        from backend.app.services.engine_account import get_held_codes

        settings = engine_state.state.integrated_system_settings_cache
        if is_test_mode(settings):
            codes = await get_held_codes()
            return sorted(codes), True
        # 실전 모드 — 잔고 조회 완료 여부로 준비 상태 판별.
        if not engine_state.state.account_rest_bootstrapped:
            return [], False
        codes = await get_held_codes()
        return sorted(codes), True

    async def _refresh_data_page(self, page: str, reason: str) -> RefreshResult:
        """자료 중심 화면 갱신 — 준비 상태·변경 번호만 갱신.

        자료 전체를 복사·비교하지 않고 원본 변경 이벤트에서 변경 번호를 올린다.
        (원본 자체가 단일 진실 소스이므로 여기서는 버전 표시만 담당.)
        """
        st = self._ensure_state(page)
        if st is None:
            return RefreshResult(page=page, changed=False, failed=True)

        # 자료 중심 화면은 원본이 존재하면 준비된 것으로 본다.
        ready = self._is_data_source_ready(page)
        if not ready:
            st.last_update_reason = f"{reason} (원본 미준비)"
            return RefreshResult(
                page=page, changed=False, failed=False,
                ready=False, change_no=st.change_no,
            )

        st.change_no += 1
        st.failed = False
        st.ready = True
        st.last_update_reason = reason
        return RefreshResult(
            page=page, changed=True, failed=False,
            ready=True, change_no=st.change_no,
        )

    def _is_data_source_ready(self, page: str) -> bool:
        """자료 중심 화면의 원본 준비 여부."""
        if page == PAGE_PROFIT_DETAIL:
            # 매수·매도 이력 원본 — 앱 기동 후 항상 준비 (trade_history 모듈).
            return True
        if page == PAGE_STOCK_CLASSIFICATION:
            # 분류 원본 — 마스터 캐시 준비 후 항상 준비.
            return bool(engine_state.state.master_stocks_cache)
        if page == PAGE_STOCK_DETAIL:
            # 5일 일봉 원본 — 마스터 캐시 준비 후 항상 준비.
            return bool(engine_state.state.master_stocks_cache)
        if page == PAGE_SETTINGS:
            # 설정 저장소 — 캐시 로드 후 항상 준비.
            return bool(engine_state.state.integrated_system_settings_cache)
        return False

    # ── 초기 생성 ────────────────────────────────────────────────────────

    async def initialize_all(self, reason: str = "앱 준비 후 초기 생성") -> dict[str, RefreshResult]:
        """앱 준비·로그인 후 전체 화면 대상 초기 생성.

        재기동 시 이전 메모리 대상을 신뢰하지 않고 현재 원본에서 다시 만든다.
        초기 계산 실패가 전체 앱 기동을 중단하지 않도록 실패는 해당 화면에 격리한다.
        """
        self.reset()
        return await self.refresh(reason)


# ── 싱글턴 ────────────────────────────────────────────────────────────────

page_targets = PageTargetRegistry()


async def initialize_page_targets() -> None:
    """앱 준비 후 화면별 대상 초기 생성 — 엔진 기동 흐름에서 호출.

    업종 순위 요약이 준비된 뒤에 매수 후보 원본이 확정되므로
    sector_summary_ready_event 대기 후 초기 생성한다.
    초기 생성 실패는 전체 기동을 중단하지 않는다 (P25 격리된 실패).
    """
    try:
        from backend.app.services.engine_lifecycle import is_engine_running
        if not is_engine_running():
            logger.info("[구독대상] 엔진 미실행 — 초기 생성 생략")
            return
        # 업종 순위 요약 준비 대기 — 매수 후보 원본 확정 보장.
        if not engine_state.state.sector_summary_ready_event.is_set():
            logger.info("[구독대상] 업종 순위 요약 준비 대기 중")
            await engine_state.state.sector_summary_ready_event.wait()
        results = await page_targets.initialize_all()
        ready_count = sum(1 for r in results.values() if r.ready)
        failed_count = sum(1 for r in results.values() if r.failed)
        logger.info(
            "[구독대상] 초기 생성 완료 — 준비 %d, 실패 %d, 전체 %d",
            ready_count, failed_count, len(results),
        )
    except Exception as e:
        logger.warning("[구독대상] 초기 생성 실패 — 전체 기동은 계속: %s", e, exc_info=True)


async def refresh_page_targets(
    reason: str, pages: set[str] | None = None,
) -> dict[str, RefreshResult]:
    """원본 변경 시 화면별 대상 갱신 — 2세션에서 각 변경 지점에 연결할 공통 진입점."""
    return await page_targets.refresh(reason, pages)


# ── 활성 연결 갱신·초기 스냅샷 전송 (2세션) ──────────────────────────────────

async def _build_data_page_snapshot(page: str) -> dict | None:
    """자료 중심 화면의 초기 스냅샷 페이로드 조립.

    자료 전체는 원본이 단일 진실 소스이므로 여기서는 원본에서 조회하여 전송용 페이로드만 만든다.
    반환 None — 원본 미준비 또는 조회 실패 (빈 스냅샷으로 성공 처리하지 않음).
    """
    if page == PAGE_PROFIT_DETAIL:
        # 매수·매도 이력 + 일별 요약 — initial-snapshot과 동일 원본.
        from backend.app.services.engine_initial_data import (
            _get_trade_history_for_snapshot, _get_daily_summary_for_snapshot,
        )
        buy_history = await _get_trade_history_for_snapshot("buy")
        sell_history = await _get_trade_history_for_snapshot("sell")
        daily_summary = await _get_daily_summary_for_snapshot()
        return {
            "buy_history": buy_history,
            "sell_history": sell_history,
            "daily_summary": daily_summary,
        }
    if page == PAGE_STOCK_CLASSIFICATION:
        # 분류 자료 — stock-classification-changed 페이로드와 동일.
        from backend.app.core.stock_classification_data import load_custom_data
        from backend.app.core.sector_mapping import get_merged_all_sectors
        from backend.app.services.sector_data_provider import get_all_sector_stocks
        from backend.app.core.sector_stock_cache import assemble_filter_summary
        import backend.app.services.engine_state as _es

        custom = load_custom_data()
        merged = await get_merged_all_sectors()
        stocks = await get_all_sector_stocks()
        no_sector_count = sum(1 for s in stocks if s.get("sector") == "미분류")
        filter_summary = assemble_filter_summary(
            getattr(_es.state, "latest_filter_summary_meta", ""), len(stocks)
        )
        return {
            "custom_data": {
                "sectors": dict(custom.sectors),
                "stock_moves": dict(custom.stock_moves),
            },
            "merged_sectors": merged,
            "no_sector_count": no_sector_count,
            "filter_summary": filter_summary,
            "all_stocks": stocks,
        }
    if page == PAGE_STOCK_DETAIL:
        # 5일 일봉 — HTTP /api/stock-detail/5d-array 원본과 동일 형태.
        # master_stocks_table에서 종목명/시장구분/NXT여부를 JOIN하고
        # stock_5d_bars에서 각 종목 최근 5행을 날짜 내림차순으로 조회.
        # 거래대금은 백만원 단위, 고가는 원 단위 (DB 저장 단위 그대로).
        from collections import defaultdict
        from backend.app.db.database import get_db_connection
        conn = await get_db_connection()
        cursor = await conn.execute(
            "SELECT code, name, market AS market_type, nxt_enable "
            "FROM master_stocks_table ORDER BY code"
        )
        master_rows = await cursor.fetchall()
        cursor = await conn.execute(
            "SELECT code, dt, trade_amount, high_price "
            "FROM stock_5d_bars ORDER BY code, dt DESC"
        )
        bar_rows = await cursor.fetchall()
        bars_by_code: dict[str, list] = defaultdict(list)
        latest_dt = ""
        for r in bar_rows:
            bars_by_code[r["code"]].append({
                "dt": r["dt"],
                "trade_amount": r["trade_amount"],
                "high_price": r["high_price"],
            })
            if not latest_dt or r["dt"] > latest_dt:
                latest_dt = r["dt"]
        items = []
        for row in master_rows:
            items.append({
                "code": row["code"],
                "name": row["name"] or "",
                "market_type": row["market_type"] if row["market_type"] is not None else "",
                "nxt_enable": bool(row["nxt_enable"] or 0),
                "bars": bars_by_code.get(row["code"], [])[:5],
            })
        return {"date": latest_dt, "items": items}
    if page == PAGE_SETTINGS:
        # 마스킹된 설정 스냅샷 — settings-changed와 동일 원본.
        from backend.app.services.engine_config import _mask_sensitive_settings
        return _mask_sensitive_settings(engine_state.state.integrated_system_settings_cache)
    return None


async def _send_stock_subscription_snapshot(ws, page: str, codes: list[str]) -> None:
    """종목 실시간 화면의 초기 스냅샷 전송 — 대상 종목 전체를 한 번에."""
    from backend.app.web.ws_manager import ws_manager
    from backend.app.services.engine_initial_data import build_master_cache_snapshot
    try:
        snapshot = await build_master_cache_snapshot(codes)
        await ws_manager.send_to(ws, "master-cache-snapshot", snapshot)
    except Exception as e:
        logger.warning("[구독대상] %s 초기 스냅샷 전송 실패: %s", page, e, exc_info=True)


async def _send_data_page_snapshot(ws, page: str) -> None:
    """자료 중심 화면의 초기 스냅샷 전송."""
    from backend.app.web.ws_manager import ws_manager
    try:
        payload = await _build_data_page_snapshot(page)
        if payload is None:
            logger.info("[구독대상] %s 자료 스냅샷 미전송 — 원본 미준비", page)
            return
        # 자료 화면별 전용 이벤트명으로 전송 (프론트엔드가 3세션에서 수신).
        event_name = _DATA_PAGE_SNAPSHOT_EVENT.get(page, "page-data-snapshot")
        await ws_manager.send_to(ws, event_name, {"page": page, "data": payload})
    except Exception as e:
        logger.warning("[구독대상] %s 자료 스냅샷 전송 실패: %s", page, e, exc_info=True)


# 자료 중심 화면별 스냅샷 이벤트명 — 프론트엔드(3세션)가 수신하여 화면 갱신.
_DATA_PAGE_SNAPSHOT_EVENT: dict[str, str] = {
    PAGE_PROFIT_DETAIL: "profit-detail-snapshot",
    PAGE_STOCK_CLASSIFICATION: "stock-classification-snapshot",
    PAGE_STOCK_DETAIL: "stock-detail-snapshot",
    PAGE_SETTINGS: "settings-snapshot",
}


async def handle_page_active(ws, page: str, codes: list[str] | None) -> None:
    """페이지 활성화 처리 — 페이지 이름만으로 저장소 대상 조회 후 구독·스냅샷 전송.

    Args:
        ws: WebSocket 연결
        page: 화면 키 (8개 허용 키 중 하나)
        codes: 프론트엔드가 명시한 종목 코드 목록 (None 또는 빈 리스트 → 저장소에서 조회).
               기존 codes 명시 메시지는 전환 기간 동안 호환 — 명시된 경우 그대로 사용.
    """
    from backend.app.web.ws_manager import ws_manager

    if page not in ALLOWED_PAGE_KEYS:
        # 지원하지 않는 페이지 이름 — 기존 처리 규칙 유지 (호환).
        return

    ws_manager.set_active_page(ws, page)

    # 종목 실시간 구독 화면 — 저장소에서 대상 코드 조회.
    if page in STOCK_SUBSCRIPTION_PAGES:
        # codes 명시 시 호환 (전환 기간) — 명시되지 않았으면 저장소에서 조회.
        if codes:
            use_codes = codes
        else:
            st = page_targets.get(page)
            if st is None or not st.ready:
                # 저장소 미준비 — 빈 스냅샷을 정상 데이터처럼 보내지 않음.
                logger.info("[구독대상] %s 활성화 — 저장소 미준비 (스냅샷 생략)", page)
                return
            use_codes = page_targets.get_codes(page)

        newly_subscribed = ws_manager.subscribe_codes(ws, page, use_codes)
        if newly_subscribed:
            # 신규 구독 종목에만 초기 스냅샷 전송 (유지 종목은 이미 보고 있음).
            await _send_stock_subscription_snapshot(ws, page, sorted(newly_subscribed))
        elif use_codes:
            # 같은 종목을 다른 연결이 이미 구독 중이어도 이 연결에는 초기 스냅샷 필요.
            await _send_stock_subscription_snapshot(ws, page, use_codes)
        return

    # 자료 중심 화면 — 자료 스냅샷 전송 (종목 실시간 구독 없음).
    await _send_data_page_snapshot(ws, page)


async def refresh_active_connections(
    reason: str, pages: set[str] | None = None,
) -> dict[str, RefreshResult]:
    """원본 변경 시 대상 갱신 + 활성 연결에 추가·제거·스냅샷 전달.

    태스크 2세션 §6 — 원본 변경 시 갱신 진입점을 각 변경 지점에 연결.
    갱신 결과의 added/removed를 활성 연결에 적용:
      - 종목 실시간 화면: diff 기반 갱신 (추가 종목 스냅샷, 제거 종목 해지, 유지 종목 그대로)
      - 자료 중심 화면: 변경 시 자료 스냅샷 재전송
    대상 변경이 없으면 중복 전송 없음.
    실패 시 다른 페이지·다른 연결 전송 중단 없음 (P25 격리된 실패).
    """
    results = await page_targets.refresh(reason, pages)
    if not results:
        return results

    from backend.app.web.ws_manager import ws_manager

    for page, result in results.items():
        # 변경 없으면 구독 해지·재등록·스냅샷 반복 없음.
        if not result.changed:
            continue
        # 원본 미준비 또는 실패 — 활성 연결 갱신 생략 (빈 스냅샷으로 덮지 않음).
        if not result.ready or result.failed:
            continue

        active_clients = ws_manager.get_clients_for_page(page)
        if not active_clients:
            continue

        if page in STOCK_SUBSCRIPTION_PAGES:
            # 종목 실시간 화면 — diff 기반 갱신.
            new_codes = page_targets.get_codes(page)
            for ws in active_clients:
                if ws not in ws_manager._clients:
                    continue
                try:
                    newly_subscribed, _removed = ws_manager.update_subscription_diff(
                        ws, page, new_codes,
                    )
                    if newly_subscribed:
                        await _send_stock_subscription_snapshot(
                            ws, page, sorted(newly_subscribed),
                        )
                except Exception as e:
                    logger.warning(
                        "[구독대상] %s 활성 연결 갱신 실패 — 다음 변경에서 재시도: %s",
                        page, e, exc_info=True,
                    )
        else:
            # 자료 중심 화면 — 자료 스냅샷 재전송.
            for ws in active_clients:
                if ws not in ws_manager._clients:
                    continue
                try:
                    await _send_data_page_snapshot(ws, page)
                except Exception as e:
                    logger.warning(
                        "[구독대상] %s 자료 스냅샷 재전송 실패: %s",
                        page, e, exc_info=True,
                    )

    return results
