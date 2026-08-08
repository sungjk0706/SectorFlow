# -*- coding: utf-8 -*-
"""
초기 데이터 관련 모듈
- 초기 데이터 생성
- 업종 종목 페이로드 생성
- 데이터 필드 필터링
- 실시간 필드 초기화
"""
import asyncio
import logging
from typing import TYPE_CHECKING
from backend.app.services import engine_state

if TYPE_CHECKING:
    from backend.app.domain.models import SectorSummary

logger = logging.getLogger(__name__)


# ── 초기 데이터 생성 ─────────────────────────────────────────────────────

async def build_initial_snapshot() -> dict:
    """WS 연결 시 클라이언트에게 보낼 메타 상태 데이터를 조립한다.

    sector_stocks는 별도 이벤트(sector-stocks-refresh)로 분할 전송하므로 여기서는 빈 리스트.
    """
    from backend.app.services import ws_subscribe_control
    from backend.app.services.daily_time_scheduler import get_market_phase
    from backend.app.services.engine_account import (
        get_positions, get_account_snapshot,
        get_buy_limit_status, _refresh_account_snapshot_meta,
    )
    from backend.app.services.sector_data_provider import get_sector_scores_snapshot, get_buy_targets_sector_stocks
    from backend.app.services.engine_config import _mask_sensitive_settings
    from backend.app.services.engine_lifecycle import get_engine_status
    from backend.app.pipelines.pipeline_compute import get_current_receive_rate

    async def _safe(fn, default):
        """getter 호출을 감싸서 실패하면 기본값을 돌려준다."""
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as exc:
            logger.warning("[시스템] %s 호출 실패 — 기본값 사용: %s", fn.__name__, exc, exc_info=True)
            return default

    await _safe(_refresh_account_snapshot_meta, None)
    positions = await _safe(get_positions, [])
    account_snap = await _safe(get_account_snapshot, {})

    # 단일 소스 진리: _integrated_system_settings_cache 직접 사용

    scores_snapshot = await _safe(get_sector_scores_snapshot, ([], 0))
    scores_list, ranked_count = scores_snapshot if isinstance(scores_snapshot, tuple) else (scores_snapshot, 0)

    # 종목수 일치 보장: master_stocks_table 기준
    total_stocks_count = len(engine_state.state.master_stocks_cache)

    snapshot: dict = {
        "_v":               1,
        "account":          account_snap,
        "positions":        positions,
        "sector_stocks":    [],  # 분할 전송 — sector-stocks-refresh 이벤트로 별도 전송
        "sector_scores":    scores_list,
        "sector_status":    {"total_stocks": total_stocks_count, "max_targets": int(engine_state.state.integrated_system_settings_cache["sector_max_targets"]), "ranked_sectors_count": ranked_count},
        # buy_targets: 실시간 필드 포함 전체 리스트. 이후 sector-stocks-refresh →
        # 프론트 rebindBuyTargetsRealtime이 sectorStocks 기준으로 실시간 필드 정정 (P10 SSOT).
        # 별도 buy-targets-update 이벤트도 동일 payload 재전송 (WS delta 메커니즘 기반점 확보).
        "buy_targets":      await _safe(get_buy_targets_sector_stocks, []),
        "settings":         _mask_sensitive_settings(engine_state.state.integrated_system_settings_cache),
        "status":           get_engine_status(),
        "sell_history":     await _safe(lambda: _get_trade_history_for_snapshot("sell"), []),
        "buy_history":      await _safe(lambda: _get_trade_history_for_snapshot("buy"), []),
        "daily_summary":    await _safe(lambda: _get_daily_summary_for_snapshot(), []),
        "buy_limit_status": await _safe(get_buy_limit_status, {"daily_buy_spent": 0}),
        "ws_subscribe_status": ws_subscribe_control.get_subscribe_status(),
        "bootstrap_done":   engine_state.state.bootstrap_event.is_set() if engine_state.state.bootstrap_event else engine_state.state.preboot_cache_loaded,
        "market_phase":     get_market_phase(),
        "receive_rate":     get_current_receive_rate(),
        "broker_config":    engine_state.state.integrated_system_settings_cache["broker_config"],
        "avg_amt_refresh":  None,
    }
    from backend.app.services.engine_account_notify import get_freshness_snapshot
    snapshot["freshness"] = get_freshness_snapshot()


    # Delta 캐시 초기화 — sector_stocks는 분할 전송 시점에 초기화
    try:
        from backend.app.services.engine_account_notify import init_sent_caches
        init_sent_caches([], positions, account_snap)
    except Exception as e:
        logger.warning("[시스템] 증분 캐시 리셋 실패: %s", e, exc_info=True)

    return snapshot


async def build_sector_stocks_payload() -> dict:
    """sector-stocks-refresh 이벤트용 종목 데이터 페이로드를 조립한다.

    DEPRECATED: 마스터 캐시 단일 시세 소스 전환 후 build_master_cache_snapshot 사용.
    호환성 유지 — ws.py 초기 연결 시 여전히 호출됨 (4세션 프론트 전환 후 제거 예정).
    """
    from backend.app.services.sector_data_provider import get_sector_stocks
    from backend.app.services.engine_account import get_positions, get_account_snapshot

    sector_stocks = await get_sector_stocks()
    filtered = _filter_stock_fields(sector_stocks)

    # Delta 캐시 초기화 (종목 데이터 기준)
    try:
        from backend.app.services.engine_account_notify import init_sent_caches
        init_sent_caches(sector_stocks, await get_positions(), await get_account_snapshot())
    except Exception:
        logger.warning("[시스템] 증분 캐시 초기화 실패", exc_info=True)

    from backend.app.services.engine_account_notify import get_freshness
    return {"_v": 1, "stocks": filtered, "freshness": get_freshness("sector_stocks")}


# ── 마스터 캐시 snapshot 필드 — 프론트 MasterStock 타입과 동일 ──────────────
_MASTER_CACHE_FIELDS = (
    "code", "name", "cur_price", "change", "change_rate", "strength",
    "trade_amount", "sector", "avg_amt_5d", "market_type", "nxt_enable",
    "order_ratio", "program_net_buy", "news_boost", "high_5d",
)


async def build_master_cache_snapshot(codes: list[str]) -> dict:
    """master-cache-snapshot 이벤트용 페이로드 — 요청된 codes의 마스터 캐시 데이터.

    마스터 캐시 단일 시세 소스 (설계 결정 1·3):
      - 전 종목이 아닌 요청된 codes만 전송 (페이지별 구독, P24 단순성)
      - 필터 미달 종목도 포함 (보유종목 052690 결함 해결 — 설계 9.1)
      - 공통 실시간 데이터만 (시세·호가·PGM·뉴스), 매수 순위·차단·가산점 제외 (사용자 결정 3)

    Args:
        codes: 구독 신청한 종목 코드 리스트
    """
    from backend.app.core.sector_mapping import get_merged_sectors_batch
    from backend.app.services.engine_symbol_utils import (
        get_stock_market as _get_mkt,
        is_nxt_enabled as _is_nxt,
    )

    cache = engine_state.state.master_stocks_cache
    valid_codes = [c for c in codes if c and c in cache]
    if not valid_codes:
        return {"_v": 1, "stocks": []}

    # 업종 배치 조회
    sectors_map = await get_merged_sectors_batch(valid_codes)

    stocks: list[dict] = []
    for cd in valid_codes:
        entry = cache[cd]
        avg5d_million = int(entry.get("avg_5d_trade_amount", 0) or 0)
        high5d = int(entry.get("high_5d_price", 0) or 0)
        item = {
            "code": cd,
            "name": entry.get("name", ""),
            "cur_price": entry.get("cur_price"),
            "change": entry.get("change"),
            "change_rate": entry.get("change_rate"),
            "strength": entry.get("strength"),
            "trade_amount": entry.get("trade_amount"),
            "sector": sectors_map.get(cd, "미분류"),
            "avg_amt_5d": avg5d_million,  # 백만원 단위 유지 (get_sector_stocks와 동일 — 프론트 fmtMillionsToBillion이 억 변환 단일 담당, 이중 나눗셈 방지)
            "market_type": _get_mkt(cd) or "",
            "nxt_enable": _is_nxt(cd),
            "order_ratio": entry.get("order_ratio"),
            "program_net_buy": entry.get("program_net_buy"),
            "news_boost": entry.get("news_boost"),
            "high_5d": high5d,
        }
        stocks.append(item)

    return {"_v": 1, "stocks": stocks}


# ── 데이터 필드 필터링 ─────────────────────────────────────────────

_SNAPSHOT_STOCK_FIELDS = {
    "code", "name", "cur_price", "change", "change_rate", "strength",
    "trade_amount", "sector", "avg_amt_5d", "market_type", "nxt_enable",
    "sign",
}


def _filter_stock_fields(stocks: list[dict]) -> list[dict]:
    """initial-snapshot용 종목 데이터 필드 필터링."""
    return [{k: v for k, v in s.items() if k in _SNAPSHOT_STOCK_FIELDS} for s in stocks]


async def _get_trade_history_for_snapshot(side: str) -> list:
    """initial-snapshot용 체결 이력 반환. 현재 trade_mode 기준 필터."""
    from backend.app.services import trade_history
    from backend.app.services.engine_account import get_trade_mode
    
    mode = get_trade_mode()
    if side == "sell":
        return await trade_history.get_sell_history(trade_mode=mode)
    return await trade_history.get_buy_history(trade_mode=mode)


async def _get_daily_summary_for_snapshot() -> list:
    """initial-snapshot용 N거래일(사용자 설정) 일별 요약 반환."""
    from backend.app.services import trade_history
    from backend.app.services.engine_account import get_trade_mode

    days = int(engine_state.state.integrated_system_settings_cache.get("daily_summary_days", 20))
    return await trade_history.get_daily_summary(days=days, trade_mode=get_trade_mode())


# ── 실시간 필드 초기화 ─────────────────────────────────────────────

_REALTIME_FIELDS = (
    "cur_price", "change", "change_rate", "trade_amount", "strength",
    "order_ratio", "program_net_buy", "news_boost", "sign",
)


async def _reset_realtime_fields() -> None:
    """WS 구독 시작 시 실시간 필드와 뉴스 만료 시각을 None으로 초기화한다."""
    from backend.app.core.trade_mode import is_virtual_mode
    from backend.app.services import dry_run
    from backend.app.services.engine_account_notify import (
        notify_cache,
        notify_desktop_sector_stocks_refresh,
        _broadcast,
    )
    from backend.app.services.engine_account import _broadcast_account

    for entry in engine_state.state.master_stocks_cache.values():
        for f in _REALTIME_FIELDS:
            entry[f] = None
        entry["news_boost_ts"] = None
    # 보유종목 실시간 필드 초기화 (전일 종가 혼입 방지)
    for pos in engine_state.state.positions:
        pos["cur_price"] = None
        pos["change"] = None
        pos["change_rate"] = None
        pos["bid_depth"] = None
        pos["ask_depth"] = None

    # 가상매매 가상 보유종목 실시간 필드 초기화
    if is_virtual_mode(engine_state.state.integrated_system_settings_cache):
        for pos in dry_run._test_positions.values():
            pos["cur_price"] = None
            pos["change"] = None
            pos["change_rate"] = None
            pos["bid_depth"] = None
            pos["ask_depth"] = None

    # 업종지수 실시간 캐시 초기화 (전일 잔존 부호·지수·대비·등락률 제거 — P22 정합성)
    engine_state.state.index_data_cache.clear()

    # 업종 점수 캐시 초기화 (실시간 데이터 재계산 유도)
    _set_sector_summary(None, "engine_initial_data.reset_realtime_fields")
    # 캡슐화된 notify_cache.clear_all() 호출로 결합성 제거.
    # 본 시점은 엔진 전체 재초기화(장마감·개시 등)이며 다중 WS 연결 동시 초기화 정상.
    # clear_all은 _initialized=False로 리셋 → 다음 init_sent_caches가 정상 재설정.
    # clear_all 직후 첫 delta는 전체 데이터로 전송되어 정합성 보장 (P25 격리).
    notify_cache.clear_all()

    # DB master_stocks_table 실시간 필드 초기화 (과거 데이터 혼입 방지)
    try:
        from backend.app.db.database import get_db_connection, get_db_lock
        async with get_db_lock():
            conn = await get_db_connection()
            await conn.execute("""
                UPDATE master_stocks_table
                SET cur_price = NULL,
                    change = NULL,
                    change_rate = NULL,
                    trade_amount = NULL
            """)
            await conn.commit()
        logger.info("[시스템] DB 전종목 마스터 테이블 실시간 필드 리셋")
    except Exception as db_err:
        logger.error("[시스템] DB 전종목 마스터 테이블 실시간 필드 리셋 실패: %s", db_err, exc_info=True)
    logger.info(
        "[시스템] 실시간 필드 및 REST 보완 저장 데이터, 수익 이력 리셋 완료 — %d종목, 실시간/REST 저장 데이터 전체 클리어",
        len(engine_state.state.master_stocks_cache),
    )
    await notify_desktop_sector_stocks_refresh()
    await _broadcast_account("realtime_reset")
    await _broadcast("realtime-reset", {})


async def _reset_program_net_buy_only() -> None:
    """정규장 마감 시 프로그램 순매수만 초기화하고 화면에 갱신한다."""
    from backend.app.services.engine_account_notify import notify_desktop_sector_stocks_refresh

    for entry in engine_state.state.master_stocks_cache.values():
        entry["program_net_buy"] = None
    await notify_desktop_sector_stocks_refresh()
    logger.info(
        "[시스템] 정규장 마감 프로그램 순매수 단독 초기화 완료 — %d종목",
        len(engine_state.state.master_stocks_cache),
    )


def _mark_realtime_reset_done(date_str: str | None = None) -> None:
    """``last_realtime_reset_date`` 갱신 (단일 소유자 — 세션 11 CACHE-STATE-IMPL-11).

    실시간 필드 초기화(``_reset_realtime_fields``) 완료 후 중복 실행 방지용
    날짜 플래그(YYYYMMDD)를 설정한다. 모든 ``last_realtime_reset_date`` 쓰기는
    본 함수에서만 수행한다 (P10 SSOT — 그룹 D 소유권 계약).

    호출부:
      - ``engine_cache._load_caches_preboot`` — WS 구독 구간 내 기동 시 DB 로드 후
      - ``daily_time_scheduler._on_pre_ws_subscribe`` — 07:58 사전 트리거
      - ``daily_time_scheduler._on_ws_subscribe_start`` — 07:59/08:00 phase 변경

    Args:
        date_str: YYYYMMDD 형식. None이면 ``_kst_now()``로 계산.
                  호출부에서 이미 ``today_str``을 계산한 경우 전달하여 일관성 유지.
    """
    if date_str is None:
        from backend.app.services.daily_time_scheduler import _kst_now
        date_str = _kst_now().strftime("%Y%m%d")
    engine_state.state.last_realtime_reset_date = date_str


def _set_sector_summary(summary: "SectorSummary | None", source: str) -> None:
    """``sector_summary_cache`` 단일 쓰기 경로 (COUPLING-S1 후속 단일화 — C-01).

    모든 ``sector_summary_cache`` 쓰기는 본 함수에서만 수행한다 (P10 SSOT).
    ``None`` 할당(리셋)과 ``SectorSummary`` 할당(갱신) 모두 커버하며,
    참조 교체 방식(R5.6)을 유지한다.

    호출부 (운영 7곳):
      - ``engine_lifecycle.reset_broker_session_state`` — 재기동 시 리셋
      - ``daily_time_scheduler._on_pre_ws_subscribe`` — 07:58 사전 리셋
      - ``daily_time_scheduler._on_ws_subscribe_start`` — 구독 구간 내 시작 리셋
      - ``engine_initial_data._reset_realtime_fields`` — WS 구독 시작 시 리셋
      - ``engine_sector_confirm._incremental_recompute`` — 증분 재계산 갱신
      - ``engine_sector_confirm._full_recompute`` — 전체 재계산 갱신
      - ``sector_data_provider.recompute_sector_summary`` — 사용자 요청 재계산 갱신

    Args:
        summary: 새 ``SectorSummary`` 객체. ``None``이면 캐시 리셋.
        source: 갱신 출처 식별자 (P21 사용자 투명성 + 디버깅).
    """
    engine_state.state.sector_summary_cache = summary
    logger.debug("[업종] sector_summary_cache 갱신 — source=%s", source)
