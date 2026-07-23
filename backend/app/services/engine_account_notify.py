# -*- coding: utf-8 -*-
"""
계좌·엔진 상태 변경 알림 -- WebSocket 브로드캐스트 기반.

엔진 본체는 이미 갱신된 snapshot·positions·레이더/작전 목록 등 **데이터만** 넘기고,
이 모듈이 페이로드 조립·로깅·전송을 담당한다.

델타 비교만으로 전송 여부를 결정한다 — 변경 있으면 즉시 전송, 변경 없으면 생략.
"""
from __future__ import annotations
import logging
from backend.app.services.engine_symbol_utils import _base_stk_cd
logger = logging.getLogger(__name__)


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


# ── Delta 계산 함수 ─────────────────────────────────────────────────────────


# Position delta 비교 키: 프론트엔드가 실제 사용하는 필드만 비교
_POSITION_CMP_KEYS = ("stk_cd", "stk_nm", "qty", "buy_price", "avg_price", "buy_amount", "buy_amt", "total_fee", "tax", "cur_price", "buy_date")

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
    # Set 캐시 동기화 — positions_code_set O(1) 조회용
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
    # ── 수신율 임계값 게이트 — WS 구독 구간 내 임계값 미달 시 sector-scores 전송 차단 ──
    # 임계값 통과 후 첫 전송이 전체 스냅샷이 되도록 delta 비교 캐시 클리어.
    try:
        from backend.app.pipelines.pipeline_compute import is_sector_threshold_passed
        if not is_sector_threshold_passed():
            notify_cache.prev_scores = []
            return
    except Exception as e:
        logger.warning("[시스템] 수신율 임계값 게이트 조회 실패 (전송 허용): %s", e)

    from backend.app.services.sector_data_provider import get_sector_scores_snapshot
    scores, ranked_count = get_sector_scores_snapshot()

    # 수신율 가져오기 (pipeline_compute.py에서 이벤트 기반으로 갱신)
    receive_rate = _get_current_receive_rate()

    # delta 계산: 변경된 업종만 전송
    if not force and notify_cache.prev_scores:
        payload = _build_sector_score_delta_payload(scores, receive_rate, ranked_count)
        if payload is None:
            return  # 변경 없음 → 전송 생략
    else:
        # 최초 전송 또는 force → 전체 스냅샷
        payload = _build_sector_score_full_payload(scores, receive_rate, ranked_count)

    await _safe_broadcast("sector-scores", payload)
    notify_cache.prev_scores = scores
    notify_cache.prev_receive_rate = receive_rate


def _get_current_receive_rate():
    """pipeline_compute에서 수신율 조회. 실패 시 None."""
    try:
        from backend.app.pipelines.pipeline_compute import get_current_receive_rate
        return get_current_receive_rate()
    except Exception as e:
        logger.warning("[시스템] 수신율 조회 실패 (빈 값으로 진행): %s", e)
        return None


def _build_sector_score_delta_payload(scores: list, receive_rate, ranked_count: int) -> dict | None:
    """delta 페이로드 조립. 변경 없으면 None 반환."""
    prev_map = {s["sector"]: s for s in notify_cache.prev_scores}
    changed = []
    for s in scores:
        prev = prev_map.get(s["sector"])
        if prev is None or s != prev:
            changed.append(s)
    # 삭제된 업종 감지 (이전에 있었는데 지금 없는 경우)
    cur_sectors = {s["sector"] for s in scores}
    removed = [s["sector"] for s in notify_cache.prev_scores if s["sector"] not in cur_sectors]
    receive_rate_changed = receive_rate != notify_cache.prev_receive_rate

    if not changed and not removed and not receive_rate_changed:
        return None  # 변경 없음 → 전송 생략

    return {
        "changed_scores": changed,
        "status": _build_sector_score_status(scores, ranked_count, receive_rate),
        "delta": True,
        "changed_sectors": [s["sector"] for s in changed],
        "removed_sectors": removed,
    }


def _build_sector_score_full_payload(scores: list, receive_rate, ranked_count: int) -> dict:
    """전체 스냅샷 페이로드 조립 (최초 전송 또는 force)."""
    return {
        "scores": scores,
        "status": _build_sector_score_status(scores, ranked_count, receive_rate),
    }


def _build_sector_score_status(scores: list, ranked_count: int, receive_rate) -> dict:
    """sector-scores 공통 status 블록 조립."""
    from backend.app.services.engine_state import state
    return {
        "total_stocks": len(scores),
        "max_targets": int(state.integrated_system_settings_cache.get("sector_max_targets", 3)),
        "ranked_sectors_count": ranked_count,
        "receive_rate": receive_rate,
    }


async def notify_desktop_sector_refresh(*, force: bool = False) -> None:
    """sector-scores 전송 (sector-tick 제거 — real-data로 대체됨, Phase 6-C)."""
    await notify_desktop_sector_scores(force=force)


async def notify_orderbook_update(code: str, bid: int, ask: int) -> None:
    """매수 후보 종목의 호가잔량 변경 시 프론트에 즉시 전송 (이벤트 기반)."""
    payload = {"code": code, "bid": bid, "ask": ask}
    await _safe_broadcast("orderbook-update", payload)


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


# 매수 후보 비교 키: 순위·시세·가드 상태 등 변경 감지 대상 필드
_BUY_TARGET_CMP_KEYS = ("rank", "cur_price", "change_rate", "strength", "trade_amount", "boost_score", "guard_pass", "reason", "order_ratio", "program_net_buy", "high_5d", "avg_amt_5d")


async def notify_buy_targets_update() -> None:
    """매수 후보 목록 변경 시 delta만 WS로 브로드캐스트한다."""
    from backend.app.services.sector_data_provider import get_buy_targets_sector_stocks

    targets = await get_buy_targets_sector_stocks()

    # 현재 타겟을 code→dict 매핑으로 변환
    cur_map: dict[str, dict] = {}
    for t in targets:
        code = t.get("code", "")
        if code:
            cur_map[code] = t

    # buy_targets_code_set 갱신 (매수 후보 종목 코드 캐시)
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


async def notify_program_update(code: str, net_buy: int) -> None:
    """프로그램 순매수 변경 시 WS로 브로드캐스트."""
    payload = {"code": code, "net_buy": net_buy}
    await _safe_broadcast("program-update", payload)
