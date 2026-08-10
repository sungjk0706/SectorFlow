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
    """알림 레이어 델타 캐시 통합 클래스 — 동일 사용자 모든 WS 연결이 공유하는 단일 delta SSOT.

    책임 경계 (세션 6):
      본 캐시는 **전역 delta 기준점**을 담당한다. SectorFlow는 1인 로컬 자동매매 앱으로
      다중 WS 연결(다중 탭/재연결)은 모두 동일 사용자·동일 계정·동일 데이터를 바라본다.
      따라서 delta 기준점을 연결별로 분리하지 않고 전역 SSOT 1개로 통일한다 (P10 SSOT,
      P24 단순성). 업계 표준 FastAPI ConnectionManager 패턴과 shared-websocket 패턴도
      동일 사용자의 다중 연결을 단일 논리 세션으로 묶어 동일 payload를 전송한다.

    초기화 경쟁 제거 (세션 6 수정):
      - `_initialized` 플래그로 `init_sent_caches`의 멱등성을 보장한다.
      - 첫 WS 연결이 `init_sent_caches`를 호출해 기준점을 설정하면 `_initialized=True`.
      - 이후 다중 연결이 `init_sent_caches`를 호출해도 `_initialized=True`이면 스킵 —
        첫 연결이 설정한 기준점이 유지되어 덮어쓰기 경쟁으로 인한 false positive delta
        방지 (P22 데이터 정합성, 세션 5 시나리오 2·3 결함 해소).

    재초기화 경로 (세션 6 수정):
      - `_reset_realtime_fields`는 장마감·개시 등 엔진 전체 재초기화 시점에만 호출.
      - `clear_all()`이 `_initialized=False`로 리셋 → 다음 `init_sent_caches`가 정상 재설정.
      - clear_all 직후 delta 계산 시 모든 항목이 changed로 나오는 것은 정상 —
        첫 delta는 전체 데이터로 전송되어 정합성 보장 (P25 격리, 세션 5 시나리오 4 정상화).

    시나리오 테스트 5건은 `test_engine_account_notify.py::TestNotifyCacheConcurrencyScenarios` 참조.
    실전 주문 경로에는 영향 없음.
    """
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
        self._initialized = False

    def clear_all(self):
        """모든 캐시 초기화 + _initialized 리셋.

        엔진 전체 재초기화 시점(_reset_realtime_fields)에만 호출되며,
        호출 후 다음 init_sent_caches가 정상적으로 기준점을 재설정한다.
        """
        self.position_sent.clear()
        self.snapshot_sent.clear()
        self.prev_scores = []
        self.prev_sector_stock_codes.clear()
        self.prev_sent.clear()
        self.prev_buy_targets_map = None
        self.positions_code_set.clear()
        self.layout_code_set.clear()
        self.buy_targets_code_set.clear()
        self._initialized = False


# 전역 인스턴스 1개만 생성
notify_cache = NotificationCache()


# ── 실시간 데이터 필드 정의 ─────────────────────────────────────────────────
_TICK_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")

# ── Delta 캐시 (notify_cache로 통합됨) ──────────────────────────────────────


# ── WS/HTTP 최신성 계약 ─────────────────────────────────────────────────────
# revision은 데이터 그룹별 서버 단조 증가값이다. _v는 payload 버전이므로
# 최신성 비교에 사용하지 않는다. 이 모듈이 HTTP 조회와 WS 전송의 공통 소유자다.
_FRESHNESS_GROUPS = ("account", "buy_targets", "sector_scores", "sector_stocks", "trade_history")
_freshness_revisions = {group: 0 for group in _FRESHNESS_GROUPS}


def _next_revision(group: str) -> int:
    if group not in _freshness_revisions:
        raise ValueError(f"알 수 없는 최신성 그룹: {group}")
    _freshness_revisions[group] += 1
    return _freshness_revisions[group]


def get_freshness(group: str) -> dict[str, str | int]:
    """HTTP 조회가 반환할 현재 서버 기준 최신성 메타데이터."""
    if group not in _freshness_revisions:
        raise ValueError(f"알 수 없는 최신성 그룹: {group}")
    return {"group": group, "revision": _freshness_revisions[group]}


def get_freshness_snapshot(groups: tuple[str, ...] = _FRESHNESS_GROUPS) -> dict[str, dict[str, str | int]]:
    """초기 스냅샷용 그룹별 최신성 메타데이터."""
    return {group: get_freshness(group) for group in groups}


# ── WS 브로드캐스트 헬퍼 (lazy import로 순환 임포트 방지) ──────────────────
async def _broadcast(event_type: str, data: dict, *, group: str | None = None, revision: int | None = None) -> None:
    """ws_manager.broadcast() 래퍼 및 데이터 그룹 revision 부착."""
    from backend.app.web.ws_manager import ws_manager
    if "_v" not in data:
        data["_v"] = 1
    if group is not None:
        data["freshness"] = {"group": group, "revision": revision if revision is not None else _next_revision(group)}
    await ws_manager.broadcast(event_type, data)


async def _safe_broadcast(
    event_type: str,
    payload: dict | None,
    *,
    group: str | None = None,
    revision: int | None = None,
) -> None:
    """안전한 브로드캐스트 전송 (예외 처리 통합)."""
    if payload is not None:
        try:
            await _broadcast(event_type, payload, group=group, revision=revision)
        except Exception as e:
            logger.debug(f"[시스템] {event_type} 화면 전송 실패: {e}", exc_info=True)


async def publish_buy_gate_status(reason: str = "", reason_code: str = "") -> None:
    """전역 매수 차단 상태를 후보 행과 분리하여 전송한다."""
    from backend.app.services.engine_state import state
    from backend.app.core.trade_mode import is_virtual_mode

    state.buy_gate_reason = reason
    await _safe_broadcast("buy-gate-status", {
        "blocked": bool(reason),
        "reason": reason,
        "reason_code": reason_code,
        "mode": "virtual" if is_virtual_mode(state.integrated_system_settings_cache) else "live",
    })


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
_POSITION_CMP_KEYS = ("stk_cd", "stk_nm", "qty", "avg_price", "buy_amount", "buy_amt", "total_fee", "tax", "cur_price", "buy_date")

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
    """initial-snapshot 전송 후 delta 캐시 초기화.

    멱등성 가드 (세션 6 — P22 데이터 정합성):
      `_initialized=True`이면 스킵하여 다중 WS 연결의 동시 초기화 경쟁을 차단한다.
      첫 연결이 설정한 기준점이 유지되며, 이후 연결의 init_sent_caches 호출은 no-op.
      재초기화는 `clear_all()`이 `_initialized=False`로 리셋한 이후에만 수행된다.
    """
    if notify_cache._initialized:
        return
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
    notify_cache._initialized = True


# ── 알림 함수 (WebSocket 브로드캐스트) ─────────────────────────────────────────────

async def notify_desktop_header_refresh() -> None:
    """엔진 상태(connected, login_ok 등) 변경 시 헤더 갱신 → WS engine-status."""
    from backend.app.services.engine_lifecycle import get_engine_status
    payload = get_engine_status()
    payload["_v"] = 1
    await _safe_broadcast("engine-status", payload)


async def notify_index_data(upcode: str, jisu: str, change: str, drate: str, sign: str) -> None:
    """업종지수 실시간 데이터 → 캐시 갱신 + WS index-data 브로드캐스트.

    P10 SSOT: state.index_data_cache에 마지막 수신값 보관 (종목 현재가/업종점수와 동일 패턴).
    WS 재연결 시 _send_initial_snapshot_delayed()가 이 캐시에서 재전송.
    엔진 상태(broker_statuses)는 engine-status 이벤트로 별도 전송되므로 index-data에 미포함.
    """
    from backend.app.services import engine_state
    # 캐시 갱신 (P25 격리된 실패 — 캐시 실패해도 브로드캐스트는 진행)
    try:
        engine_state.state.index_data_cache[upcode] = {
            "jisu": jisu, "sign": sign, "change": change, "drate": drate,
        }
    except Exception:
        logger.warning("[알림] 업종지수 캐시 갱신 실패: upcode=%s", upcode, exc_info=True)
    try:
        from backend.app.services.buy_order_executor import refresh_buy_market_guard_and_recompute
        await refresh_buy_market_guard_and_recompute()
    except Exception:
        logger.warning("[리스크] 업종지수 갱신 후 매수 가드 재평가 실패", exc_info=True)
    await _safe_broadcast("index-data", {
        "upcode": upcode,
        "jisu": jisu,
        "change": change,
        "drate": drate,
        "sign": sign,
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
    """업종 순위 + 상태 전송 → WS sector-scores. delta 전송.

    전송 정책 (P22 데이터 정합성, P21 사용자 투명성):
      - 임계값 미통과 시: "대기 중" 상태 전송 (빈 scores + status.waiting=true).
        프론트가 "데이터 수신 대기 중"임을 인지 → 장 초반 "갑자기 변동" 인지 완화.
      - 임계값 통과 시: 항상 전송 (delta "변경 없음"이어도 전송 생략하지 않음).
        두 패널(업종순위/종목시세)이 같은 sectorScores 기반으로 갱신되므로,
        전송 생략 시 가운데 순위와 우측 행 순서의 타이밍 불일치가 발생 (P22 위반).
        0.2초마다 항상 전송하여 두 패널 동기화 보장.

    수신율은 receive-rate 이벤트가 단일 소스(P10 SSOT) — sector-scores에서 중복 전송 제거.
    """
    # ── 수신율 임계값 게이트 — 미통과 시 "대기 중" 상태 전송 (P21 투명성) ──
    # 임계값 통과 후 첫 전송이 전체 데이터가 되도록 delta 비교 캐시 클리어.
    threshold_passed = True
    try:
        from backend.app.pipelines.pipeline_compute import is_sector_threshold_passed
        threshold_passed = is_sector_threshold_passed()
    except Exception as e:
        logger.debug("[시스템] 수신율 임계값 게이트 조회 실패 (전송 허용): %s", e)

    if not threshold_passed:
        # 임계값 미통과: "대기 중" 상태 전송 (빈 scores + waiting 플래그)
        notify_cache.prev_scores = []
        payload = {
            "scores": [],
            "status": {
                **_build_sector_score_status([], 0),
                "waiting": True,
            },
        }
        await _safe_broadcast("sector-scores", payload, group="sector_scores")
        return

    from backend.app.services.sector_data_provider import get_sector_scores_snapshot
    scores, ranked_count = get_sector_scores_snapshot()

    # delta 계산: 변경된 업종만 전송 (단, 변경 없어도 전체 데이터로 항상 전송 — P22 정합성)
    # delta "변경 없음" 시 전송을 생략하면 두 패널(업종순위/종목시세)이 옛 sectorScores를
    # 유지하게 되어 타이밍 불일치 발생. 0.2초마다 항상 전체 전송하여 동기화 보장.
    if not force and notify_cache.prev_scores:
        delta_payload = _build_sector_score_delta_payload(scores, ranked_count)
        if delta_payload is not None:
            # 변경 감지: delta 전송
            payload = delta_payload
        else:
            # 변경 없음: 전체 데이터로 전송 (생략하지 않음 — P22 정합성)
            payload = _build_sector_score_full_payload(scores, ranked_count)
    else:
        # 최초 전송 또는 force → 전체 데이터
        payload = _build_sector_score_full_payload(scores, ranked_count)

    await _safe_broadcast("sector-scores", payload, group="sector_scores")
    notify_cache.prev_scores = scores


def _build_sector_score_delta_payload(scores: list, ranked_count: int) -> dict | None:
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

    if not changed and not removed:
        return None  # 변경 없음 → 전송 생략

    return {
        "changed_scores": changed,
        "status": _build_sector_score_status(scores, ranked_count),
        "delta": True,
        "changed_sectors": [s["sector"] for s in changed],
        "removed_sectors": removed,
    }


def _build_sector_score_full_payload(scores: list, ranked_count: int) -> dict:
    """전체 데이터 페이로드 조립 (최초 전송 또는 force)."""
    return {
        "scores": scores,
        "status": _build_sector_score_status(scores, ranked_count),
    }


def _build_sector_score_status(scores: list, ranked_count: int) -> dict:
    """sector-scores 공통 status 블록 조립."""
    from backend.app.services.engine_state import state
    return {
        "total_stocks": len(scores),
        "max_targets": int(state.integrated_system_settings_cache.get("sector_max_targets", 3)),
        "ranked_sectors_count": ranked_count,
    }


async def notify_desktop_sector_refresh(*, force: bool = False) -> None:
    """sector-scores 전송 (sector-tick 제거 — real-data로 대체됨, Phase 6-C)."""
    await notify_desktop_sector_scores(force=force)


async def notify_orderbook_update(code: str, bid: int, ask: int) -> None:
    """호가잔량 변경 시 구독 페이지에 master-cache-delta 전송 (마스터 캐시 단일 시세 소스).

    기존 orderbook-update 이벤트를 master-cache-delta로 대체 (설계 결정 3).
    백엔드 master_stocks_cache 갱신은 호출부에서 이미 수행 — 본 함수는 전송만 담당.
    """
    from backend.app.web.ws_manager import ws_manager
    await ws_manager.broadcast_to_code_subscribers(
        "master-cache-delta",
        {"code": code, "fields": {"order_ratio": [bid, ask]}},
        code,
    )


async def notify_desktop_sector_stocks_refresh(*, force: bool = False) -> None:
    """종목 목록 또는 데이터가 변경되었을 때 구독 클라이언트에 master-cache-snapshot 전송.

    마스터 캐시 단일 시세 소스 (설계 결정 1·3):
      - 각 클라이언트의 구독 종목에 대해 master-cache-snapshot 전송
      - 구독자가 없으면 전송 생략 (페이지별 구독 push 모델)
      - 기존 sector-stocks-refresh/sector-stocks-delta 이벤트를 master-cache-snapshot으로 대체

    Args:
        force: True 시 전 종목 데이터 변경 (확정시세/5거래일 일봉 다운로드 등).
               새 모델에서는 구독 종목 snapshot 전송으로 동일 효과.
    """
    from backend.app.web.ws_manager import ws_manager
    from backend.app.services.engine_initial_data import build_master_cache_snapshot

    # 각 클라이언트의 구독 종목에 대해 snapshot 전송
    for ws, codes in list(ws_manager._client_subscribed_codes.items()):
        if not codes or ws not in ws_manager._clients:
            continue
        try:
            snapshot = await build_master_cache_snapshot(list(codes))
            await ws_manager.send_to(ws, "master-cache-snapshot", snapshot)
        except Exception as e:
            logger.debug("[시스템] master-cache-snapshot 전송 실패: %s", e, exc_info=True)

    # notify_cache 갱신 (기존 호환성 — delta 기준점 유지)
    from backend.app.services.sector_data_provider import get_sector_stocks
    stocks = await get_sector_stocks()
    new_codes = {s.get("code", "") for s in stocks if s.get("code", "")}
    notify_cache.prev_sector_stock_codes = new_codes
    notify_cache.prev_sent = {}
    for s in stocks:
        code = s.get("code", "")
        if code:
            notify_cache.prev_sent[code] = {}


def _clear_non_guard_reject_reasons() -> None:
    """통과 종목에 남은 전역·실행 사유를 제거하고 종목 가드 사유만 남긴다."""
    from backend.app.services.engine_state import state

    ss = state.sector_summary_cache
    if not ss:
        return
    for bt in ss.buy_targets:
        if bt.stock.guard_pass:
            bt.reject_reason = ""


# 매수 후보 delta 비교 키 — 정적 필드만 포함 (실시간·이벤트 필드는 sectorStocks SSOT에서 파생).
# P10(SSOT) + P22(데이터 정합성) + P23(일관성): 프론트 applyBuyTargetsUpdate same 비교 키와 동일 기준.
# 실시간 필드(cur_price/change/change_rate/strength/trade_amount)는 매 틱마다 변하므로
# delta changed 판정에서 제외 — 틱 디스패치가 별도 경로(real-data-tick)로 갱신 담당.
# news_boost는 뉴스 호재 이벤트 기반 갱신이므로 news-hit 이벤트가 단일 전달 경로(P10).
#   상수명 REALTIME은 틱 실시간 필드 의미이나, delta 제외 대상 그룹으로 함께 묶어
#   일괄 pop 루프를 재사용(P24 중복 제거). news_boost만 별도 상수로 분리 시 코드 증가.
_BUY_TARGET_REALTIME_KEYS = ("cur_price", "change", "change_rate", "strength", "trade_amount", "news_boost")
_BUY_TARGET_CMP_KEYS = (
    "rank", "boost_score", "guard_pass", "reject_reason",
    "order_ratio", "program_net_buy", "high_5d",
)


async def notify_buy_targets_update() -> None:
    """매수 후보 목록 변경 시 delta만 WS로 브로드캐스트한다.

    Payload 계약 (세션 8):
      - added/changed 항목은 **정적 필드만** 전송. 실시간 필드(`_BUY_TARGET_REALTIME_KEYS`)는
        `_BUY_TARGET_REALTIME_KEYS` 리스트 기반으로 일괄 제거 (P24 중복 제거 — 2곳 하드코딩 → 상수).
      - 프론트엔드는 sectorStocks(실시간 SSOT)에서 실시간 필드를 재결합하여 단일 소스 일관성 유지.
      - removed: 종목 코드 문자열 리스트만 전송 (정적·실시간 필드 모두 불필요).
      - changed 판정: `_BUY_TARGET_CMP_KEYS`(정적 필드) 기준. 실시간 필드·news_boost 제외.
        `news_boost`는 news-hit 이벤트가 단일 전달(P10 SSOT) — delta changed에서 제외.
      - 초기 상태(prev_buy_targets_map is None): buy-targets-update 전체 리스트 전송 (실시간 필드·news_boost 포함).
        이후 sector-stocks-refresh → 프론트 rebindBuyTargetsRealtime이 실시간 필드 정정.
    """
    _clear_non_guard_reject_reasons()

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
        await _safe_broadcast("buy-targets-update", {"buy_targets": targets}, group="buy_targets")
        return

    # delta 계산
    prev_codes = set(notify_cache.prev_buy_targets_map.keys())
    cur_codes = set(cur_map.keys())

    # added 항목: 정적 필드만 전송 (실시간 필드 제거 — 프론트엔드 sectorStocks 단일 소스)
    added = []
    for c in cur_codes - prev_codes:
        item = cur_map[c].copy()
        for key in _BUY_TARGET_REALTIME_KEYS:
            item.pop(key, None)
        added.append(item)
    removed = list(prev_codes - cur_codes)
    # changed 항목: 정적 필드만 전송 (실시간 필드 제거) + 정적 필드 기준 변경 감지
    changed = []
    for code in cur_codes & prev_codes:
        cur_t = cur_map[code].copy()
        for key in _BUY_TARGET_REALTIME_KEYS:
            cur_t.pop(key, None)
        prev_t = notify_cache.prev_buy_targets_map[code]
        if any(cur_t.get(k) != prev_t.get(k) for k in _BUY_TARGET_CMP_KEYS):
            changed.append(cur_t)

    if not added and not removed and not changed:
        return  # 변경 없음 → 전송 생략

    notify_cache.prev_buy_targets_map = cur_map
    await _safe_broadcast("buy-targets-delta", {"added": added, "removed": removed, "changed": changed}, group="buy_targets")


async def broadcast_engine_status_ws(engine_status: dict) -> None:
    """엔진 상태 변경 시 모든 WS 구독자에게 push (engine-status 이벤트)."""
    if "_v" not in engine_status:
        engine_status["_v"] = 1
    await _safe_broadcast("engine-status", engine_status)


async def notify_program_update(code: str, net_buy: int) -> None:
    """프로그램 순매수 변경 시 구독 페이지에 master-cache-delta 전송 (마스터 캐시 단일 시세 소스).

    기존 program-update 이벤트를 master-cache-delta로 대체 (설계 결정 3).
    """
    from backend.app.web.ws_manager import ws_manager
    await ws_manager.broadcast_to_code_subscribers(
        "master-cache-delta",
        {"code": code, "fields": {"program_net_buy": net_buy}},
        code,
    )
