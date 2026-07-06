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
from backend.app.core.logger import get_logger
from backend.app.services.engine_symbol_utils import _base_stk_cd
logger = get_logger("engine")


# ── NotificationCache: 알림 레이어 델타 캐시 통합 클래스 ─────────────────────────
class NotificationCache:
    """알림 레이어 델타 캐시 통합 클래스 - 생명주기 관리 단순화."""
    def __init__(self):
        self.position_sent = {}
        self.snapshot_sent = {}
        self.prev_scores = []
        self.prev_sector_stock_codes = set()
        self.prev_sent = {}
        self.prev_buy_targets_map = None
        self.positions_code_set = set()
        self.layout_code_set = set()
        self.buy_targets_code_set = set()
        self.prev_receive_rate = None

    def clear_all(self):
        """모든 캐시 초기화."""
        self.position_sent.clear()
        self.snapshot_sent.clear()
        self.prev_scores = []
        self.prev_sector_stock_codes.clear()
        self.prev_sent.clear()
        self.prev_buy_targets_map = None
        self.positions_code_set.clear()
        self.layout_code_set.clear()
        self.buy_targets_code_set.clear()
        self.prev_receive_rate = None


# 전역 인스턴스 1개만 생성
notify_cache = NotificationCache()


# ── 레거시 데스크톱 콜백 변수 (호환성 유지, 사용되지 않음) ──────────────────
_desktop_account_notifier: Callable[[str | None, dict], None] | None = None
_desktop_trade_price_notifier: Callable[[str, int], None] | None = None
_desktop_buy_radar_notifier: Callable[[], None] | None = None
_desktop_account_tabs_refresh: Callable[[], None] | None = None
_desktop_header_refresh_notifier: Callable[[], None] | None = None
_desktop_index_notifier: Callable[[], None] | None = None
_desktop_sector_notifier: Callable[[], None] | None = None
_desktop_settings_toggled_notifier: Callable[[], None] | None = None


# ── 실시간 데이터 필드 정의 ─────────────────────────────────────────────────
_TICK_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")

# ── Delta 캐시 (notify_cache로 통합됨) ──────────────────────────────────────


# ── WS 브로드캐스트 헬퍼 (lazy import로 순환 임포트 방지) ──────────────────
async def _broadcast(event_type: str, data: dict) -> None:
    """ws_manager.broadcast() 래퍼."""
    from backend.app.web.ws_manager import ws_manager
    if "_v" not in data:
        data["_v"] = 1
    await ws_manager.broadcast(event_type, data)


async def _safe_broadcast(event_type: str, payload: dict | None) -> None:
    """안전한 브로드캐스트 전송 (예외 처리 통합)"""
    if payload is not None:
        try:
            await _broadcast(event_type, payload)
        except Exception as e:
            logger.warning(f"[시스템] {event_type} 화면 전송 실패: {e}", exc_info=True)


# ── Set 캐시 재구축 함수 ─────────────────────────────────────────────────────

def _rebuild_positions_cache(positions: list) -> None:
    """_positions 리스트로부터 notify_cache.positions_code_set을 재구축한다. 예외 시 이전 캐시 유지."""
    try:
        notify_cache.positions_code_set = {
            _base_stk_cd(str(p.get("stk_cd", "")))
            for p in positions
            if str(p.get("stk_cd", "")).strip()
        }
    except Exception:
        logger.warning("[시스템] 보유종목 캐시 재구축 실패 (이전 캐시 유지)", exc_info=True)


def _rebuild_layout_cache(layout: list) -> None:
    """_sector_stock_layout 리스트로부터 notify_cache.layout_code_set을 재구축한다. 예외 시 이전 캐시 유지."""
    try:
        # 기존 set 객체 주소 유지, 내부만 갱신 (주소 스왑 금지)
        notify_cache.layout_code_set.clear()
        notify_cache.layout_code_set.update({v for t, v in layout if t == "code" and v})
    except Exception:
        logger.warning("[시스템] 레이아웃 캐시 재구축 실패 (이전 캐시 유지)", exc_info=True)




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


# Position delta 비교 키: 프론트엔드가 실제 사용하는 필드만 비교
_POSITION_CMP_KEYS = ("stk_cd", "stk_nm", "qty", "buy_price", "avg_price", "cur_price", "pnl_amount", "pnl_rate")

# Snapshot delta 비교 키: 프론트엔드가 실제 사용하는 필드만 비교
_SNAPSHOT_CMP_KEYS = ("deposit", "orderable", "accumulated_investment",
                      "total_buy_amount", "total_eval_amount", "total_pnl", "total_pnl_rate")


def _pos_equal(a: dict, b: dict) -> bool:
    """두 position dict가 필수 필드 기준으로 동등한지 판단."""
    return all(a.get(k) == b.get(k) for k in _POSITION_CMP_KEYS)


def _snap_equal(a: dict, b: dict) -> bool:
    """두 snapshot dict가 필수 필드 기준으로 동등한지 판단."""
    return all(a.get(k) == b.get(k) for k in _SNAPSHOT_CMP_KEYS)


def _compute_position_delta(current_positions: list[dict]) -> tuple[list[dict], list[str]]:
    """현재 보유종목과 notify_cache.position_sent를 비교하여 변경/제거 목록 반환."""
    current_map = {}
    for p in current_positions:
        cd = str(p.get("stk_cd", "") or "").strip()
        if cd:
            current_map[cd] = p
    changed = []
    for code, pos in current_map.items():
        prev = notify_cache.position_sent.get(code)
        if prev is None or not _pos_equal(prev, pos):
            changed.append(pos)
    removed = [code for code in notify_cache.position_sent if code not in current_map]
    return changed, removed


def init_sent_caches(sector_stocks: list[dict], positions: list[dict], snapshot: dict) -> None:
    """initial-snapshot 전송 후 delta 캐시 초기화."""
    notify_cache.prev_sector_stock_codes = {s.get("code", "") for s in sector_stocks if s.get("code", "")}
    notify_cache.position_sent = {}
    for p in positions:
        cd = str(p.get("stk_cd", "") or "").strip()
        if cd:
            notify_cache.position_sent[cd] = dict(p)
    notify_cache.snapshot_sent = dict(snapshot)
    notify_cache.prev_scores = []
    notify_cache.prev_buy_targets_map = None
    # Set 캐시 동기화 — _is_relevant_code O(1) 조회용
    _rebuild_positions_cache(positions)


# ── 알림 함수 (WebSocket 브로드캐스트) ─────────────────────────────────────────────

async def notify_desktop_header_refresh() -> None:
    """엔진 상태(connected, login_ok 등) 변경 시 헤더 갱신 → WS index-data."""
    from backend.app.services.engine_lifecycle import get_engine_status
    payload = get_engine_status()
    payload["_v"] = 1
    await _safe_broadcast("index-data", payload)


async def notify_index_data(upcode: str, jisu: str, change: str, drate: str, sign: str) -> None:
    """업종지수 실시간 데이터 → WS index-data 브로드캐스트 (저장 없이 pass-through).

    broker_statuses를 항상 포함하여 프론트엔드 헤더 칩 상태를 갱신한다.
    """
    from backend.app.services.engine_lifecycle import get_engine_status
    broker_statuses = get_engine_status().get("broker_statuses", {})
    await _safe_broadcast("index-data", {
        "upcode": upcode,
        "jisu": jisu,
        "change": change,
        "drate": drate,
        "sign": sign,
        "broker_statuses": broker_statuses,
    })


async def notify_desktop_settings_toggled(changed_keys_dict: dict | None = None) -> None:
    """텔레그램 등 외부에서 설정 토글 변경 시 → WS settings-changed (증분 전송 지원)."""
    if changed_keys_dict:
        payload = {
            "_v": 1,
            "delta": True,
            "changed": changed_keys_dict
        }
    else:
        from backend.app.services.engine_config import get_settings_snapshot
        payload = get_settings_snapshot()
        payload["_v"] = 1
    await _safe_broadcast("settings-changed", payload)


async def notify_desktop_sector_scores(*, force: bool = False) -> None:
    """업종 순위 + 상태 + 수신율 전송 → WS sector-scores. delta 전송."""
    from backend.app.services.engine_state import state
    from backend.app.services.sector_data_provider import get_sector_scores_snapshot
    scores, ranked_count = get_sector_scores_snapshot()

    # 수신율 가져오기 (pipeline_compute.py에서 이벤트 기반으로 갱신)
    receive_rate = None
    try:
        from backend.app.pipelines.pipeline_compute import get_current_receive_rate
        receive_rate = get_current_receive_rate()
    except Exception as e:
        logger.warning("[시스템] 수신율 조회 실패 (None으로 진행): %s", e)

    # delta 계산: 변경된 섹터만 전송
    if not force and notify_cache.prev_scores:
        prev_map = {s["sector"]: s for s in notify_cache.prev_scores}
        changed = []
        for s in scores:
            prev = prev_map.get(s["sector"])
            if prev is None or s != prev:
                changed.append(s)
        # 삭제된 섹터 감지 (이전에 있었는데 지금 없는 경우)
        cur_sectors = {s["sector"] for s in scores}
        removed = [s["sector"] for s in notify_cache.prev_scores if s["sector"] not in cur_sectors]

        # 메모리 클리닝: 임시 변수 삭제
        del prev_map, cur_sectors

        # 수신율 변경 감지
        receive_rate_changed = receive_rate != notify_cache.prev_receive_rate

        if not changed and not removed and not receive_rate_changed:
            return  # 변경 없음 → 전송 생략

        payload = {
            "changed_scores": changed,
            "status": {
                "total_stocks": len(scores),
                "max_targets": int(state.integrated_system_settings_cache["sector_max_targets"]),
                "ranked_sectors_count": ranked_count,
                "receive_rate": receive_rate
            },
            "delta": True,
            "changed_sectors": [s["sector"] for s in changed],
            "removed_sectors": removed,
        }

        # 메모리 클리닝: 임시 리스트 삭제
        del changed, removed
    else:
        # 최초 전송 또는 force → 전체 스냅샷
        payload = {
            "scores": scores,
            "status": {
                "total_stocks": len(scores),
                "max_targets": int(state.integrated_system_settings_cache["sector_max_targets"]),
                "ranked_sectors_count": ranked_count,
                "receive_rate": receive_rate
            },
        }

    await _safe_broadcast("sector-scores", payload)
    notify_cache.prev_scores = scores
    notify_cache.prev_receive_rate = receive_rate


async def notify_desktop_sector_refresh(*, force: bool = False) -> None:
    """sector-scores 전송 (sector-tick 제거 — real-data로 대체됨, Phase 6-C)."""
    await notify_desktop_sector_scores(force=force)


async def notify_desktop_trade_price(
    stk_cd: str, price: int,
    change: int = 0, change_rate: float = 0.0,
    strength: str = "-", trade_amount: int = 0,
) -> None:
    """REAL 체결가 → WS trade-price (확장 필드 포함)."""
    if price <= 0 or not stk_cd:
        return
    nk = _base_stk_cd(stk_cd)
    payload = {
        "code": nk,
        "price": int(price),
        "change": int(change),
        "change_rate": float(change_rate),
        "strength": str(strength),
        "trade_amount": int(trade_amount),
    }
    await _safe_broadcast("trade-price", payload)


def _is_relevant_code(nk: str) -> bool:
    """프론트에서 실제 사용하는 종목 코드인지 판별 (섹터+보유+레이아웃). set O(1) 조회."""
    try:
        # _radar_cnsr_order 삭제: 제로-체크 보장 (구독된 종목만 틱 수신)
        if nk in notify_cache.positions_code_set:
            return True
        if nk in notify_cache.layout_code_set:
            return True
        if nk in notify_cache.buy_targets_code_set:
            return True
    except Exception as e:
        logger.error("[시스템] 종목 %s 판별 실패: %s", nk, e, exc_info=True)
    return False


async def notify_raw_real_data(item: dict) -> None:
    """
    키움 실시간 메시지(REAL)를 가공 없이 브로드캐스트.
    프론트에 필요한 종목(섹터+보유+레이아웃)만 전송하여 렌더링 과부하 방지.
    """
    if not item or not isinstance(item, dict):
        return
    vals = item.get("values", {})
    if not isinstance(vals, dict):
        vals = {}
        
    try:
        from backend.app.services.engine_symbol_utils import _real_item_stk_cd
        nk = _real_item_stk_cd(item, vals)
        if not nk:
            return
            
        if not _is_relevant_code(nk):
            return
    except Exception as e:
        logger.error("[시스템] 종목코드 추출 실패: %s", e, exc_info=True)
        return
            
    # [수정] 프론트엔드 및 ws_manager가 정상 작동할 수 있도록 원본 코드를 정규화된 코드로 교체
    item["item"] = nk
    
    item["_ts"] = int(time.time() * 1000)
    await _safe_broadcast("real-data", item)


async def notify_orderbook_update(code: str, bid: int, ask: int) -> None:
    """매수후보 종목의 호가잔량 변경 시 프론트에 즉시 전송 (이벤트 기반)."""
    payload = {"code": code, "bid": bid, "ask": ask}
    await _safe_broadcast("orderbook-update", payload)


async def notify_desktop_buy_radar_only() -> None:
    """레이더 종목 변경 알림 — no-op.
    레이더 데이터는 account-update 이벤트에 radar_stocks로 포함되어 전송된다.
    매 틱마다 호출되므로 빈 이벤트도 보내지 않는다 (큐 과부하 방지)."""
    pass


async def notify_desktop_sector_stocks_refresh(*, force: bool = False) -> None:
    """종목 목록 또는 데이터가 변경되었을 때 delta 또는 전체 리스트를 WS로 전송.

    Args:
        force: True 시 delta 계산 없이 전체 스냅샷 전송 (확정시세/5일봉 다운로드 등 전 종목 데이터 변경 시).
    """
    from backend.app.services.sector_data_provider import get_sector_stocks
    stocks = await get_sector_stocks()
    new_codes = {s.get("code", "") for s in stocks if s.get("code", "")}

    if force or not notify_cache.prev_sector_stock_codes:
        # 전체 리스트를 sector-stocks-refresh로 전송
        await _safe_broadcast("sector-stocks-refresh", {"stocks": stocks})
    else:
        added_codes = new_codes - notify_cache.prev_sector_stock_codes
        removed_codes = notify_cache.prev_sector_stock_codes - new_codes

        if not added_codes and not removed_codes:
            return  # 변경 없음 → 전송 생략

        # added: 전체 상세 정보 포함
        added_stocks = [s for s in stocks if s.get("code", "") in added_codes]
        # removed: 코드 리스트만
        await _safe_broadcast("sector-stocks-delta", {
            "added": added_stocks,
            "removed": list(removed_codes),
        })

    # notify_cache.prev_sector_stock_codes 갱신
    notify_cache.prev_sector_stock_codes = new_codes

    # delta 캐시도 새 목록 기준으로 리셋 (sector-tick 제거로 빈 딕셔너리)
    notify_cache.prev_sent = {}
    for s in stocks:
        code = s.get("code", "")
        if code:
            notify_cache.prev_sent[code] = {}


async def notify_desktop_account_tabs_refresh() -> None:
    """계좌 탭(보유/미체결/수익/거래내역) 전환 시 1회 전체 새로고침 → WS account-tabs-refresh."""
    from backend.app.services.engine_lifecycle import get_engine_status
    payload = get_engine_status()
    payload["_v"] = 1
    await _safe_broadcast("index-data", payload)


async def broadcast_account_update(positions: list[dict], snapshot: dict, reason: str | None = None) -> None:
    """체결·잔고·실시간 시세 변경 시 → WS account-update (delta 방식, 페이지별 페이로드 분리)."""
    changed_positions, removed_codes = _compute_position_delta(positions)
    snapshot_changed = not _snap_equal(snapshot, notify_cache.snapshot_sent)

    if not changed_positions and not removed_codes and not snapshot_changed:
        return

    # 페이지별 페이로드 분리
    from backend.app.web.ws_manager import ws_manager

    active_pages = ws_manager.get_active_pages()
    profit_overview_active = "profit-overview" in active_pages
    sell_position_active = "sell-position" in active_pages

    # 수익현황 페이지만 활성: 경량화 페이로드 전송
    if profit_overview_active and not sell_position_active:
        lightweight_payload = _build_lightweight_payload_for_profit_overview(snapshot, changed_positions, removed_codes)
        try:
            await ws_manager.broadcast_to_pages("account-update", lightweight_payload, {"profit-overview"})
        except Exception as e:
            logger.warning("[시스템] 수익현황 경량화 페이로드 전송 실패: %s", e, exc_info=True)
    # sell-position 페이지 활성 또는 두 페이지 모두 활성: 전체 페이로드 전송
    else:
        payload = {
            "snapshot": dict(snapshot),
            "changed_positions": changed_positions,
            "removed_codes": removed_codes,
        }
        target_pages = set()
        if sell_position_active:
            target_pages.add("sell-position")
        if profit_overview_active and sell_position_active:
            target_pages.add("profit-overview")

        if target_pages:
            try:
                await ws_manager.broadcast_to_pages("account-update", payload, target_pages)
            except Exception as e:
                logger.warning("[시스템] 계좌 화면 전송 실패: %s", e, exc_info=True)
        else:
            await _safe_broadcast("account-update", payload)

    # 캐시 갱신
    notify_cache.snapshot_sent = dict(snapshot)
    notify_cache.position_sent = {}
    for p in positions:
        cd = str(p.get("stk_cd", "") or "").strip()
        if cd:
            notify_cache.position_sent[cd] = dict(p)
    # notify_cache.positions_code_set 동기화 — real-data 필터링용 O(1) Set 캐시
    _rebuild_positions_cache(positions)

    if reason and not reason.startswith("price_tick"):
        cur_pairs = [
            (_base_stk_cd(str(p.get("stk_cd", "") or "")), p.get("cur_price"))
            for p in positions
            if int(p.get("qty", 0) or 0) > 0
        ]
        logger.info(
            "[시스템] 계좌 화면 전송 사유=%s 총평가=%s 보유현재가=%s changed=%d removed=%d profit-overview=%s sell-position=%s",
            reason, snapshot.get("total_eval"), cur_pairs,
            len(changed_positions), len(removed_codes),
            profit_overview_active, sell_position_active,
        )


def _build_lightweight_payload_for_profit_overview(snapshot: dict, changed_positions: list[dict], removed_codes: list[str]) -> dict:
    """수익현황 페이지용 경량화 페이로드 생성.

    - snapshot: total_buy_amount 제거, total_eval_amount, total_pnl, total_pnl_rate 유지
    - changed_positions: 보유종목 표시에 필요한 최소 필드(stk_cd, stk_nm, qty, cur_price)만 포함
    """
    # snapshot 필터링
    lightweight_snapshot = {
        "deposit": snapshot.get("deposit"),
        "orderable": snapshot.get("orderable"),
        "accumulated_investment": snapshot.get("accumulated_investment"),
        "initial_deposit": snapshot.get("initial_deposit"),
        "total_eval_amount": snapshot.get("total_eval_amount"),
        "total_pnl": snapshot.get("total_pnl"),
        "total_pnl_rate": snapshot.get("total_pnl_rate"),
    }

    position_count = snapshot.get("position_count", 0)

    # changed_positions: 보유종목 리스트 갱신에 필요한 최소 필드만 추출
    _MIN_POSITION_KEYS = ("stk_cd", "stk_nm", "qty", "cur_price", "pnl_amount", "pnl_rate", "eval_amount")
    lightweight_positions = [
        {k: p.get(k) for k in _MIN_POSITION_KEYS}
        for p in changed_positions
    ]

    return {
        "snapshot": lightweight_snapshot,
        "position_count": position_count,
        "changed_positions": lightweight_positions,
        "removed_codes": removed_codes,
    }


async def notify_snapshot_history_update() -> None:
    """수익 이력 WS 브로드캐스트 — 프론트엔드 미사용으로 no-op."""
    pass


# 매수후보 비교 키: 순위·시세·가드 상태 등 변경 감지 대상 필드
_BUY_TARGET_CMP_KEYS = ("rank", "cur_price", "change_rate", "strength", "trade_amount", "boost_score", "guard_pass", "reason", "order_ratio", "program_net_buy", "high_5d", "avg_amt_5d")


async def notify_buy_targets_update() -> None:
    """매수후보 목록 변경 시 delta만 WS로 브로드캐스트한다."""
    from backend.app.services.sector_data_provider import get_buy_targets_sector_stocks

    targets = await get_buy_targets_sector_stocks()

    # 현재 타겟을 code→dict 매핑으로 변환
    cur_map: dict[str, dict] = {}
    for t in targets:
        code = t.get("code", "")
        if code:
            cur_map[code] = t

    # buy_targets_code_set 갱신 (_is_relevant_code 필터링용)
    notify_cache.buy_targets_code_set.clear()
    notify_cache.buy_targets_code_set.update(cur_map.keys())

    # 초기 상태 (캐시 없음): 전체 리스트 전송
    if notify_cache.prev_buy_targets_map is None:
        notify_cache.prev_buy_targets_map = cur_map
        await _safe_broadcast("buy-targets-update", {"buy_targets": targets})
        return

    # delta 계산
    prev_codes = set(notify_cache.prev_buy_targets_map.keys())
    cur_codes = set(cur_map.keys())

    # added 항목: 종목 목록만 전송 (실시간 필드 제외)
    added = []
    for c in cur_codes - prev_codes:
        item = cur_map[c].copy()
        # 실시간 필드 제거: 프론트엔드 sectorStocks 단일 소스
        for key in ['cur_price', 'change', 'change_rate', 'strength', 'trade_amount']:
            item.pop(key, None)
        added.append(item)
    removed = list(prev_codes - cur_codes)
    # changed 항목: 종목 목록만 전송 (실시간 필드 제외)
    changed = []
    for code in cur_codes & prev_codes:
        cur_t = cur_map[code].copy()
        # 실시간 필드 제거: 프론트엔드 sectorStocks 단일 소스
        for key in ['cur_price', 'change', 'change_rate', 'strength', 'trade_amount']:
            cur_t.pop(key, None)
        prev_t = notify_cache.prev_buy_targets_map[code]
        # 비교 키에서 실시간 필드 제외
        cmp_keys = [k for k in _BUY_TARGET_CMP_KEYS if k not in ['cur_price', 'change_rate', 'strength', 'trade_amount']]
        if any(cur_t.get(k) != prev_t.get(k) for k in cmp_keys):
            changed.append(cur_t)

    if not added and not removed and not changed:
        return  # 변경 없음 → 전송 생략

    notify_cache.prev_buy_targets_map = cur_map
    await _safe_broadcast("buy-targets-delta", {"added": added, "removed": removed, "changed": changed})


async def broadcast_engine_status_ws(engine_status: dict) -> None:
    """엔진 상태 변경 시 모든 WS 구독자에게 push (index-data 통일)."""
    if "_v" not in engine_status:
        engine_status["_v"] = 1
    await _safe_broadcast("index-data", engine_status)


async def notify_ws_subscribe_status(status: dict) -> None:
    """WS 구독 상태 변경 시 WS 브로드캐스트. ws_subscribe_control._set_status()에서 사용."""
    payload = {"_v": 1, **status}
    await _safe_broadcast("ws-subscribe-status", payload)


async def notify_program_update(code: str, net_buy: int) -> None:
    """프로그램 순매수 변경 시 WS로 브로드캐스트."""
    payload = {"code": code, "net_buy": net_buy}
    await _safe_broadcast("program-update", payload)
