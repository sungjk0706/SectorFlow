# -*- coding: utf-8 -*-
"""
계좌·엔진 상태 변경 알림 -- WebSocket 브로드캐스트 기반.

엔진 본체는 이미 갱신된 snapshot·positions·레이더/작전 목록 등 **데이터만** 넘기고,
이 모듈이 페이로드 조립·로깅·전송을 담당한다.

델타 비교만으로 전송 여부를 결정한다 — 변경 있으면 즉시 전송, 변경 없으면 생략.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from app.core.logger import get_logger
from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd

logger = get_logger("engine")

# ── 레거시 데스크톱 콜백 변수 (호환성 유지, 사용되지 않음) ──────────────────
_desktop_account_notifier: Callable[[str | None, dict], None] | None = None
_desktop_trade_price_notifier: Callable[[str, int], None] | None = None
_desktop_buy_radar_notifier: Callable[[], None] | None = None
_desktop_account_tabs_refresh: Callable[[], None] | None = None
_desktop_header_refresh_notifier: Callable[[], None] | None = None
_desktop_index_notifier: Callable[[], None] | None = None
_desktop_sector_notifier: Callable[[], None] | None = None
_desktop_settings_toggled_notifier: Callable[[], None] | None = None

# ── Set 캐시 (_is_relevant_code O(1) 조회용) ────────────────────────────────
_positions_code_set: set[str] = set()  # positions의 stk_cd 6자리 정규화 set
_layout_code_set: set[str] = set()  # sector_stock_layout에서 type=="code" 값 set

# ── 실시간 데이터 필드 정의 ─────────────────────────────────────────────────
_TICK_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")

# ── 압축(Conflation) 설정 ───────────────────────────────────────────────────
# 01/0B(시세) 타입: 동일 종목·동일 가격·50ms 이내 중복 틱 전송 생략
_CONFLATE_MS = 50
_conflate_cache: dict[str, dict] = {}  # code -> {"price": int, "ts": int}

# ── 브로드캐스트 압축 통계 (1초 윈도우) ────────────────────────────────────
_broadcast_stats: dict = {
    "window_start_ms": 0,
    "attempted": 0,
    "actual": 0,
}


def _record_broadcast(attempted: bool, actual: bool) -> None:
    """브로드캐스트 시도/실제 전송을 1초 윈도우에 누적."""
    global _broadcast_stats
    now = int(time.time() * 1000)
    st = _broadcast_stats
    if st["window_start_ms"] == 0:
        st["window_start_ms"] = now
    if now - st["window_start_ms"] >= 1000:
        _flush_broadcast_stats()
        st["window_start_ms"] = now
        st["attempted"] = 0
        st["actual"] = 0
    if attempted:
        st["attempted"] += 1
    if actual:
        st["actual"] += 1


def _flush_broadcast_stats() -> None:
    """1초 윈도우 브로드캐스트 집계 결과를 INFO 로깅."""
    global _broadcast_stats
    st = _broadcast_stats
    attempted = st["attempted"]
    if attempted == 0:
        return
    actual = st["actual"]
    ratio = (actual / attempted) * 100
    logger.info(
        "[통계] 1초 브로드캐스트 시도=%s 실제=%s 비율=%.1f%%",
        attempted, actual, ratio,
    )


def _should_conflate(item: dict) -> bool:
    """동일 종목, 동일 가격, 50ms 이내 중복 틱이면 True (전송 생략)."""
    msg_type = str(item.get("type", ""))
    norm = msg_type.strip().upper()
    if norm not in ("01", "0B"):
        return False
    vals = item.get("values", {})
    if not isinstance(vals, dict):
        return False
    raw_price = vals.get("10")
    if raw_price is None:
        return False
    try:
        price = int(str(raw_price).replace(",", "").replace("+", ""))
    except (ValueError, TypeError):
        return False
    raw_code = str(item.get("item") or "").strip()
    if not raw_code:
        return False
    try:
        from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
        nk = _format_kiwoom_reg_stk_cd(raw_code)
    except Exception:
        return False
    now = int(time.time() * 1000)
    last = _conflate_cache.get(nk)
    if last is not None and last["price"] == price and (now - last["ts"]) < _CONFLATE_MS:
        return True
    _conflate_cache[nk] = {"price": price, "ts": now}
    return False

# ── Delta 캐시 ──────────────────────────────────────────────────────────────
_position_sent_cache: dict[str, dict] = {}  # 보유종목별 마지막 전송 상태 (account-update delta)
_snapshot_sent_cache: dict = {}  # 마지막 전송한 account snapshot
_prev_scores_cache: list[dict] = []  # 마지막 전송한 sector-scores (delta 비교용)
_prev_sector_stock_codes: set[str] = set()  # 마지막 전송한 종목 코드 집합 (sector-stocks-delta용)
_prev_sent_cache: dict[str, dict] = {}  # 마지막 전송한 종목별 상태 캐시 (sector-stocks-refresh delta용)


# ── WS 브로드캐스트 헬퍼 (lazy import로 순환 임포트 방지) ──────────────────
def _broadcast(event_type: str, data: dict) -> None:
    """ws_manager.broadcast() 래퍼. 동기 함수 — await 불필요."""
    from app.web.ws_manager import ws_manager
    if "_v" not in data:
        data["_v"] = 1
    ws_manager.broadcast(event_type, data)


# ── Set 캐시 재구축 함수 ─────────────────────────────────────────────────────

def _rebuild_positions_cache(positions: list) -> None:
    """_positions 리스트로부터 _positions_code_set을 재구축한다. 예외 시 이전 캐시 유지."""
    global _positions_code_set
    try:
        _positions_code_set = {
            _format_kiwoom_reg_stk_cd(str(p.get("stk_cd", "")))
            for p in positions
            if str(p.get("stk_cd", "")).strip()
        }
    except Exception as e:
        logger.warning("[캐시] _positions_code_set 재구축 실패 (이전 캐시 유지): %s", e)


def _rebuild_layout_cache(layout: list) -> None:
    """_sector_stock_layout 리스트로부터 _layout_code_set을 재구축한다. 예외 시 이전 캐시 유지."""
    global _layout_code_set
    try:
        _layout_code_set = {v for t, v in layout if t == "code" and v}
    except Exception as e:
        logger.warning("[캐시] _layout_code_set 재구축 실패 (이전 캐시 유지): %s", e)


# ── 데스크톱 콜백 등록 함수 (no-op, 시그니처 유지) ──────────────────────────

def register_desktop_account_notifier(
    fn: Callable[[str | None, dict], None] | None,
) -> None:
    """레거시 no-op. 데스크톱 UI 제거로 더 이상 사용되지 않음."""
    pass


def register_desktop_trade_price_notifier(
    fn: Callable[[str, int], None] | None,
) -> None:
    """레거시 no-op."""
    pass


def register_desktop_buy_radar_notifier(fn: Callable[[], None] | None) -> None:
    """레거시 no-op."""
    pass


def register_desktop_account_tabs_refresh(fn: Callable[[], None] | None) -> None:
    """레거시 no-op."""
    pass


def register_desktop_header_refresh_notifier(
    fn: Callable[[], None] | None,
) -> None:
    """레거시 no-op."""
    pass


def register_desktop_index_notifier(fn: Callable[[], None] | None) -> None:
    """레거시 no-op."""
    pass


def register_desktop_sector_notifier(fn: Callable[[], None] | None) -> None:
    """레거시 no-op."""
    pass


def register_desktop_settings_toggled_notifier(fn: Callable[[], None] | None) -> None:
    """레거시 no-op."""
    pass


# ── WS 큐 등록 (레거시 호환 no-op) ────────────────────────────
# NOTE: 과거 WS 기반에서 WS 기반으로 전환됨. 함수명은 유지하되 내부는 no-op.

def register_account_ws_queue(q) -> None:
    """레거시 호환 no-op (WS→WS 전환)."""
    pass


def unregister_account_ws_queue(q) -> None:
    """레거시 호환 no-op (WS→WS 전환)."""
    pass


def register_engine_ws_queue(q) -> None:
    """레거시 호환 no-op (WS→WS 전환)."""
    pass


def unregister_engine_ws_queue(q) -> None:
    """레거시 호환 no-op (WS→WS 전환)."""
    pass


# ── Delta 계산 함수 ─────────────────────────────────────────────────────────


def _compute_position_delta(current_positions: list[dict]) -> tuple[list[dict], list[str]]:
    """현재 보유종목과 _position_sent_cache를 비교하여 변경/제거 목록 반환."""
    current_map = {}
    for p in current_positions:
        cd = str(p.get("stk_cd", "") or "").strip()
        if cd:
            current_map[cd] = p
    changed = []
    for code, pos in current_map.items():
        prev = _position_sent_cache.get(code)
        if prev is None or pos != prev:
            changed.append(pos)
    removed = [code for code in _position_sent_cache if code not in current_map]
    return changed, removed


def init_sent_caches(sector_stocks: list[dict], positions: list[dict], snapshot: dict) -> None:
    """initial-snapshot 전송 후 delta 캐시 초기화."""
    global _position_sent_cache, _snapshot_sent_cache, _prev_scores_cache, _prev_sector_stock_codes, _prev_buy_targets_map
    _prev_sector_stock_codes = {s.get("code", "") for s in sector_stocks if s.get("code", "")}
    _position_sent_cache = {}
    for p in positions:
        cd = str(p.get("stk_cd", "") or "").strip()
        if cd:
            _position_sent_cache[cd] = dict(p)
    _snapshot_sent_cache = dict(snapshot)
    _prev_scores_cache = []
    _prev_buy_targets_map = None
    # Set 캐시 동기화 — _is_relevant_code O(1) 조회용
    _rebuild_positions_cache(positions)


# ── 알림 함수 (WebSocket 브로드캐스트) ─────────────────────────────────────────────

def notify_desktop_header_refresh() -> None:
    """엔진 상태(connected, login_ok 등) 변경 시 헤더 갱신 → WS index-refresh."""
    try:
        import app.services.engine_service as _es
        payload = _es.get_status()
        payload["_v"] = 1
        _broadcast("index-refresh", payload)
    except Exception as e:
        logger.warning("[실시간연결] 헤더 갱신 화면전송 실패: %s", e)


def notify_desktop_settings_toggled() -> None:
    """텔레그램 등 외부에서 설정 토글 변경 시 → WS settings-changed."""
    try:
        import app.services.engine_service as _es
        payload = _es.get_settings_snapshot()
        payload["_v"] = 1
        _broadcast("settings-changed", payload)
    except Exception as e:
        logger.warning("[실시간] 설정 변경 화면전송 실패: %s", e)


def notify_desktop_index_refresh() -> None:
    """0J 지수 REAL 수신 후 헤더 지수 표시 갱신 → WS index-refresh."""
    try:
        import app.services.engine_service as _es
        payload = _es.get_status()
        payload["_v"] = 1
        _broadcast("index-refresh", payload)
    except Exception as e:
        logger.warning("[실시간연결] 헤더 갱신 화면전송 실패: %s", e)


def notify_desktop_sector_scores(*, force: bool = False) -> None:
    """업종 순위 + 상태만 전송 → WS sector-scores. delta 전송."""
    global _prev_scores_cache
    try:
        import app.services.engine_service as _es
        scores, ranked_count = _es.get_sector_scores_snapshot()

        # delta 계산: 변경된 섹터만 전송
        if not force and _prev_scores_cache:
            prev_map = {s["sector"]: s for s in _prev_scores_cache}
            changed = []
            for s in scores:
                prev = prev_map.get(s["sector"])
                if prev is None or s != prev:
                    changed.append(s)
            # 삭제된 섹터 감지 (이전에 있었는데 지금 없는 경우)
            cur_sectors = {s["sector"] for s in scores}
            removed = [s["sector"] for s in _prev_scores_cache if s["sector"] not in cur_sectors]

            if not changed and not removed:
                return  # 변경 없음 → 전송 생략

            payload = {
                "scores": scores,
                "status": {"total_stocks": len(scores), "max_targets": int(_es._settings_cache.get("sector_max_targets", 3) or 3), "ranked_sectors_count": ranked_count},
                "delta": True,
                "changed_sectors": [s["sector"] for s in changed],
                "removed_sectors": removed,
            }
        else:
            # 최초 전송 또는 force → 전체 스냅샷
            payload = {
                "scores": scores,
                "status": {"total_stocks": len(scores), "max_targets": int(_es._settings_cache.get("sector_max_targets", 3) or 3), "ranked_sectors_count": ranked_count},
            }

        _broadcast("sector-scores", payload)
        _prev_scores_cache = scores
    except Exception as e:
        logger.warning("[실시간] sector-scores 화면전송 실패: %s", e)


def notify_desktop_sector_refresh(*, force: bool = False) -> None:
    """sector-scores 전송 (sector-tick 제거 — real-data로 대체됨, Phase 6-C)."""
    notify_desktop_sector_scores(force=force)


def notify_desktop_trade_price(
    stk_cd: str, price: int,
    change: int = 0, change_rate: float = 0.0,
    strength: str = "-", trade_amount: int = 0,
) -> None:
    """REAL 체결가 → WS trade-price (확장 필드 포함)."""
    if price <= 0 or not stk_cd:
        return
    nk = _format_kiwoom_reg_stk_cd(stk_cd)
    try:
        _broadcast("trade-price", {
            "code": nk,
            "price": int(price),
            "change": int(change),
            "change_rate": float(change_rate),
            "strength": str(strength),
            "trade_amount": int(trade_amount),
        })
    except Exception as e:
        logger.warning("[실시간] 체결가 화면전송 실패: %s", e)


def _is_relevant_code(nk: str) -> bool:
    """프론트에서 실제 사용하는 종목 코드인지 판별 (섹터+보유+레이아웃). set O(1) 조회."""
    try:
        import app.services.engine_service as _es
        if nk in _es._pending_stock_details:
            return True
        if nk in _positions_code_set:
            return True
        if nk in _layout_code_set:
            return True
    except Exception as e:
        logger.error("[필터] 종목 %s 판별 실패: %s", nk, e)
    return False


def notify_raw_real_data(item: dict) -> None:
    """
    키움 실시간 메시지(REAL)를 가공 없이 브로드캐스트.
    프론트에 필요한 종목(섹터+보유+레이아웃)만 전송하여 렌더링 과부하 방지.
    01/0B 시세 타입은 동일 가격·50ms 이내 중복 틱을 압축(Conflation)하여 전송 생략.
    """
    if not item or not isinstance(item, dict):
        return
    _record_broadcast(attempted=True, actual=False)
    if _should_conflate(item):
        return
    raw_code = str(item.get("item") or "").strip()
    if raw_code:
        try:
            from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
            nk = _format_kiwoom_reg_stk_cd(raw_code)
            if not _is_relevant_code(nk):
                return
        except Exception as e:
            logger.error("[정규화] raw_code=%r 실패: %s", raw_code, e)
            return
    try:
        item["_ts"] = int(time.time() * 1000)
        _broadcast("real-data", item)
        _record_broadcast(attempted=False, actual=True)
    except Exception as e:
        logger.warning("[실시간] Raw 데이터 전송 실패: %s", e)


def notify_orderbook_update(code: str, bid: int, ask: int) -> None:
    """매수후보 종목의 호가잔량 변경 시 프론트에 즉시 전송 (이벤트 기반)."""
    try:
        _broadcast("orderbook-update", {"code": code, "bid": bid, "ask": ask})
    except Exception as e:
        logger.warning("[실시간] 호가잔량 화면전송 실패: %s", e)


def notify_desktop_buy_radar_only() -> None:
    """레이더 종목 변경 알림 — no-op.
    레이더 데이터는 account-update 이벤트에 radar_stocks로 포함되어 전송된다.
    매 틱마다 호출되므로 빈 이벤트도 보내지 않는다 (큐 과부하 방지)."""
    pass


def notify_desktop_sector_stocks_refresh() -> None:
    """필터 변경으로 종목 목록이 바뀌었을 때 delta 또는 전체 리스트를 WS로 전송."""
    global _prev_sector_stock_codes, _prev_sent_cache
    try:
        import app.services.engine_service as _es
        stocks = _es.get_sector_stocks()
        new_codes = {s.get("code", "") for s in stocks if s.get("code", "")}

        if not _prev_sector_stock_codes:
            # 초기 로드: 전체 리스트를 sector-stocks-refresh로 전송
            _broadcast("sector-stocks-refresh", {"stocks": stocks})
        else:
            added_codes = new_codes - _prev_sector_stock_codes
            removed_codes = _prev_sector_stock_codes - new_codes

            if not added_codes and not removed_codes:
                return  # 변경 없음 → 전송 생략

            # added: 전체 상세 정보 포함
            added_stocks = [s for s in stocks if s.get("code", "") in added_codes]
            # removed: 코드 리스트만
            _broadcast("sector-stocks-delta", {
                "added": added_stocks,
                "removed": list(removed_codes),
            })

        # _prev_sector_stock_codes 갱신
        _prev_sector_stock_codes = new_codes

        # delta 캐시도 새 목록 기준으로 리셋 (sector-tick 제거로 빈 딕셔너리)
        _prev_sent_cache = {}
        for s in stocks:
            code = s.get("code", "")
            if code:
                _prev_sent_cache[code] = {}
    except Exception as e:
        logger.warning("[실시간] sector-stocks-refresh 화면전송 실패: %s", e)


def notify_desktop_account_tabs_refresh() -> None:
    """계좌 탭(보유/미체결/수익/거래내역) 전환 시 1회 전체 새로고침 → WS account-tabs-refresh."""
    try:
        import app.services.engine_service as _es
        payload = _es.get_status()
        payload["_v"] = 1
        _broadcast("index-refresh", payload)
    except Exception as e:
        logger.warning("[실시간] 지수 갱신 화면전송 실패: %s", e)


def broadcast_account_update(
    reason: str | None,
    snapshot: dict,
    positions: list,
) -> None:
    """체결·잔고·실시간 시세 변경 시 → WS account-update (delta 방식)."""
    global _position_sent_cache, _snapshot_sent_cache
    if reason:
        logger.debug("[계좌화면전송] 시작 reason=%s", reason)

    changed_positions, removed_codes = _compute_position_delta(positions)
    snapshot_changed = snapshot != _snapshot_sent_cache

    if not changed_positions and not removed_codes and not snapshot_changed:
        if reason:
            logger.debug("[계좌화면전송] 변경 없음 -- 전송 생략 reason=%s", reason)
        return

    payload = {
        "snapshot": dict(snapshot),
        "changed_positions": changed_positions,
        "removed_codes": removed_codes,
    }

    try:
        _broadcast("account-update", payload)
    except Exception as e:
        logger.warning("[실시간연결] 계좌 화면전송 실패: %s", e)

    # 캐시 갱신
    _snapshot_sent_cache = dict(snapshot)
    _position_sent_cache = {}
    for p in positions:
        cd = str(p.get("stk_cd", "") or "").strip()
        if cd:
            _position_sent_cache[cd] = dict(p)

    if reason:
        cur_pairs = [
            (_format_kiwoom_reg_stk_cd(str(p.get("stk_cd", "") or "")), p.get("cur_price"))
            for p in positions
            if int(p.get("qty", 0) or 0) > 0
        ]
        logger.info(
            "[실시간연결] 계좌화면전송 사유=%s 총평가=%s 보유현재가=%s changed=%d removed=%d",
            reason, snapshot.get("total_eval"), cur_pairs,
            len(changed_positions), len(removed_codes),
        )


def notify_snapshot_history_update() -> None:
    """수익 이력이 새로 기록되면 전체 이력을 WS로 브로드캐스트한다."""
    try:
        import app.services.engine_service as _es
        _broadcast("snapshot-update", {"snapshot_history": _es.get_snapshot_history()})
    except Exception as e:
        logger.warning("[실시간] 수익 이력 화면전송 실패: %s", e)


_prev_buy_targets_map: dict[str, dict] | None = None

# 매수후보 비교 키: 순위·시세·가드 상태 등 변경 감지 대상 필드
_BUY_TARGET_CMP_KEYS = ("rank", "sector_rank", "cur_price", "change_rate", "strength", "trade_amount", "boost_score", "guard_pass", "reason")


def notify_buy_targets_update() -> None:
    """매수후보 목록 변경 시 delta만 WS로 브로드캐스트한다."""
    global _prev_buy_targets_map
    try:
        import app.services.engine_service as _es
        targets = _es.get_buy_targets_snapshot()

        # 현재 타겟을 code→dict 매핑으로 변환
        cur_map: dict[str, dict] = {}
        for t in targets:
            code = t.get("code", "")
            if code:
                cur_map[code] = t

        # 초기 상태 (캐시 없음): 전체 리스트 전송
        if _prev_buy_targets_map is None:
            _prev_buy_targets_map = cur_map
            _broadcast("buy-targets-update", {"buy_targets": targets})
            return

        # delta 계산
        prev_codes = set(_prev_buy_targets_map.keys())
        cur_codes = set(cur_map.keys())

        added = [cur_map[c] for c in (cur_codes - prev_codes)]
        removed = list(prev_codes - cur_codes)
        changed = []
        for code in cur_codes & prev_codes:
            cur_t = cur_map[code]
            prev_t = _prev_buy_targets_map[code]
            if any(cur_t.get(k) != prev_t.get(k) for k in _BUY_TARGET_CMP_KEYS):
                changed.append(cur_t)

        if not added and not removed and not changed:
            return  # 변경 없음 → 전송 생략

        _prev_buy_targets_map = cur_map
        _broadcast("buy-targets-delta", {"added": added, "removed": removed, "changed": changed})
    except Exception as e:
        logger.warning("[실시간] 매수후보 화면전송 실패: %s", e)


def broadcast_engine_status_ws(engine_status: dict) -> None:
    """엔진 상태 변경 시 모든 WS 구독자에게 push."""
    try:
        if "_v" not in engine_status:
            engine_status["_v"] = 1
        _broadcast("engine-status", engine_status)
    except Exception:
        pass
    notify_desktop_header_refresh()


def notify_ws_subscribe_status(status: dict) -> None:
    """WS 구독 상태 변경 시 WS 브로드캐스트. ws_subscribe_control._set_status()에서 사용."""
    _broadcast("ws-subscribe-status", {"_v": 1, **status})
