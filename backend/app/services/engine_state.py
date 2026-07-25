# -*- coding: utf-8 -*-
"""
엔진 전역 상태 저장소.

모든 engine_*.py 모듈은 이 파일에서 전역 상태를 직접 import한다.
순환 import 방지: 이 모듈은 다른 engine_*.py를 import하지 않는다.

속성 그룹 분류 (세션 10 — CACHE-STATE-IMPL-10, 70개 속성):
  A. 브로커 연결 (6)   — connector_manager, active_connector, broker_tokens,
                         access_token, login_ok, broker_spec
  B. 계좌 (11)          — engine_user_id, ws_account_subscribed, ws_connection_status,
                         quote_subscribed, account_rest_bootstrapped, broker_rest_totals,
                         auto_trade, broker_rest_apis, account_rest_lock,
                         account_snapshot, positions
  C. 업종 분석 (9)      — sector_summary_cache, master_stocks_cache, index_data_cache,
                         market_phase, krx_circuit_breaker_active, news_boost_cache,
                         news_keywords_cache, news_boost_score, news_boost_ttl_sec
  D. 스케줄러 (13)      — last_reset_date, krx_remove_done, confirmed_done,
                         auto_trade_timer_handles, midnight_timer_handle,
                         timetable_timer_handle, last_jif_received_at,
                         krx_countdown_override, nxt_countdown_override,
                         last_realtime_reset_date, last_ws_subscribe_start_date,
                         last_krx_pre_subscribe_date, last_confirmed_download_date
  E. 이벤트/락/상수 (18) — data_ready_event, token_ready_event, ws_reg_pipeline_done,
                         bootstrap_event, sector_summary_ready_event, engine_ready_event,
                         server_ready_event, preboot_ready_event, engine_stop_event,
                         ws_window_changed_event, reg_seq_lock, reg_ack_event,
                         reg_ack_return_code, rest_api_thread_sem,
                         _last_global_buy_ts, _last_global_sell_ts,
                         MIN_CACHE_LIFETIME_SEC, REG_POST_ACK_GAP_SEC
  F. 안전/기동 플래그 (13) — running, shutdown_requested, engine_task, engine_loop_ref,
                         realtime_latency_exceeded, position_build_failed, degraded_mode,
                         preboot_cache_loaded, confirmed_refresh_running,
                         confirmed_refresh_running_confirmed, confirmed_refresh_running_5d,
                         latest_filter_summary_meta, integrated_system_settings_cache

갱신 분산 주의 속성 (여러 파일에서 쓰기 — 향후 단일화 후보, 세션 10 조사 결과):
  - login_ok: 5곳 (kiwoom_connector, ls_connector ×2, engine_lifecycle, engine_loop,
                engine_ws_dispatch)
  - sector_summary_cache: 7곳 (engine_lifecycle, daily_time_scheduler ×2,
                engine_sector_confirm ×2, sector_data_provider, engine_snapshot)
  - confirmed_done: 5곳 (daily_time_scheduler 단일 파일 내 5곳)
  - positions: 3곳 (engine_account, engine_lifecycle, web/routes/settings)
  - broker_rest_totals: 3곳 (pipeline_compute_tick_handlers, engine_account,
                engine_lifecycle)
  - access_token: 3곳 (engine_lifecycle, engine_loop ×2)

D/E/F 소유권 계약 (세션 11 — CACHE-STATE-IMPL-11, 비거래 상태 단일화):
  단일화 완료 (헬퍼 경유, 외부 직접 쓰기 제거):
    - last_realtime_reset_date (D) → engine_snapshot._mark_realtime_reset_done()
        호출부: engine_cache, daily_time_scheduler ×2
    - confirmed_refresh_running_confirmed (F) → market_close_pipeline (소유 모듈 직접 쓰기)
        외부 예외 경로: daily_time_scheduler → _reset_confirmed_refresh_running() 헬퍼 경유
    - latest_filter_summary_meta (F) → market_close_pipeline._set_latest_filter_summary_meta()
        호출부: market_close_pipeline (4단계), web/app.py (기동 시 DB 캐시 로드)

  자연스러운 산재 (init/오류/성공 패턴 — 단일화 대상 아님):
    - running (F): engine_lifecycle(start/stop) + engine_loop(run/exit) — 라이프사이클 협업
    - degraded_mode (F): engine_lifecycle(초기화=False) + engine_loop(오류 시=True)
    - preboot_cache_loaded (F): engine_loop(초기화=False) + engine_cache(성공 시=True)
    - ws_reg_pipeline_done (E): engine_ws(set) + engine_bootstrap(set) — 준비 이벤트
    - sector_summary_ready_event (E): sector_data_provider + engine_sector_confirm — 준비 이벤트
    - confirmed_refresh_running_confirmed (F): market_close_pipeline 내 3곳 (소유 모듈)

  거래 관련 산재 (변경 금지 — 본 세션 범위 외):
    - integrated_system_settings_cache (F): 10+ 파일 (engine_config 전체 갱신 + 각 모듈 항목 수정)
    - _last_global_buy_ts / _last_global_sell_ts (E): order_interval + web/routes/settings

  상수 (쓰기 없음, 선언만):
    - MIN_CACHE_LIFETIME_SEC (E): 읽기 참조 0건 (사용 안 함 — 별도 승인 시 제거 검토)
    - REG_POST_ACK_GAP_SEC (E): 읽기만 존재 (engine_ws)

  미사용 / Dead code (별도 승인 시 제거 검토):
    - shutdown_requested (F): 선언만, 읽기/쓰기 0건
    - confirmed_refresh_running (F): 쓰기 0건, 읽기만 2건 (미구현 플래그)

Fallback 패턴 (세션 12 — active_connector 정리 인계):
  `engine_state.state.connector_manager or engine_state.state.active_connector`
  — 7개 파일 20곳 (engine_ws_reg ×6, engine_ws ×6, daily_time_scheduler ×3,
   engine_lifecycle ×2, engine_sector_confirm ×1, market_close_pipeline ×1,
   engine_bootstrap ×1)
  추가: engine_ws.py 2곳이 `if ... is_connected() else active_connector` 삼항 fallback.

Dead code 후보 (참조 0건 — 별도 승인 시 제거 검토):
  - shutdown_requested: 선언만 존재, 읽기/쓰기 참조 0건
  - confirmed_refresh_running: 쓰기 0건, 읽기만 2건 (미구현 플래그)
  - MIN_CACHE_LIFETIME_SEC: 읽기 참조 0건 (사용 안 함)
"""
import asyncio
from datetime import datetime
from typing import Any, TYPE_CHECKING
from backend.app.core.broker_connector import BrokerConnector
from backend.app.services.trading import AutoTradeManager
from backend.app.services.engine_utils import LazyEvent

if TYPE_CHECKING:
    from backend.app.core.connector_manager import ConnectorManager
    from backend.app.domain.models import SectorSummary


class EngineState:
    """엔진 전역 상태를 관리하는 싱글톤 클래스."""
    
    def __init__(self):
        # ── 엔진 상태 (그룹 F 안전/기동 + A 브로커 연결 + B engine_user_id) ──────
        self.running = False
        self.shutdown_requested: bool = False
        self.connector_manager: "ConnectorManager | None" = None  # type: ignore[name-defined]
        self.active_connector: BrokerConnector | None = None
        self.broker_tokens: dict[str, str] = {}  # {broker_id: access_token}
        self.engine_task: asyncio.Task | None = None
        self.engine_loop_ref: asyncio.AbstractEventLoop | None = None
        self.access_token: str | None = None
        self.login_ok = False
        self.engine_user_id: str = ""
        self.realtime_latency_exceeded: bool = False
        # ── 엔진 기동 상태 경고 (P21 사용자 투명성 — get_engine_status()로 프론트 전달) ──
        # position_build_failed: 테스트모드 포지션 구축 실패 (엔진은 계속 가동, 보유 종목 비어있음)
        # degraded_mode: 캐시 선행 로드 치명 오류로 감소 모드 기동 (종목 데이터 불완전)
        # 둘 다 엔진 재기동 시에만 해제 (start_engine에서 초기화하지 않으면 이전 세션 값 잔존 위험).
        self.position_build_failed: bool = False
        self.degraded_mode: bool = False

        # ── Locks & Events (그룹 E + B account_rest_lock + F preboot_cache_loaded) ──
        self.data_ready_event: LazyEvent = LazyEvent()
        self.token_ready_event: LazyEvent = LazyEvent()
        self.ws_reg_pipeline_done = LazyEvent()
        self.bootstrap_event = LazyEvent()
        self.sector_summary_ready_event = LazyEvent()
        self.engine_ready_event = LazyEvent()
        self.server_ready_event = LazyEvent()
        self.preboot_cache_loaded: bool = False
        self.preboot_ready_event = LazyEvent()
        self.engine_stop_event = LazyEvent()
        self.ws_window_changed_event = LazyEvent()
        self.reg_seq_lock: asyncio.Lock | None = None
        self.reg_ack_event = LazyEvent()
        self.reg_ack_return_code: str = ""
        self.rest_api_thread_sem: asyncio.Semaphore | None = None
        self.account_rest_lock: asyncio.Lock | None = None

        # ── 데이터 캐시 (그룹 C + E MIN_CACHE_LIFETIME_SEC + F confirmed_refresh_running*) ──
        self.MIN_CACHE_LIFETIME_SEC: float = 1.0
        self.sector_summary_cache: "SectorSummary | None" = None  # type: ignore[name-defined]
        self.confirmed_refresh_running: bool = False
        self.confirmed_refresh_running_confirmed: bool = False  # 확정시세 다운로드 전용
        self.confirmed_refresh_running_5d: bool = False         # 5거래일 일봉 다운로드 전용
        self.latest_filter_summary_meta: str = ""
        self.master_stocks_cache: dict[str, dict] = {}
        # ── 업종지수 실시간 캐시 (그룹 C, P10 SSOT — 종목 현재가/업종점수와 동일 패턴) ──
        # {upcode: {jisu, sign, change, drate}} — LS 지수IJ.txt 스펙 기준, 헤더 배지 표시 필드만 보관.
        # notify_index_data()가 틱 수신 시 갱신, WS 재연결 시 _send_initial_snapshot_delayed()가 재전송.
        self.index_data_cache: dict[str, dict[str, str]] = {}
        self.market_phase: dict = {
            "krx": "장개시전", "nxt": "장개시전",
        }
        self.krx_circuit_breaker_active: bool = False

        # ── 실시간 뉴스(NWS) 가산점 캐시 (그룹 C) ──────────────────────────────
        # news_boost_cache: {종목코드: (가산점, monotonic 타임스탬프)} — 5분 TTL (P10 SSOT)
        # news_keywords_cache: 호재 키워드 메모리 상주 (P13 — 틱 단계 DB 조회 금지)
        # news_boost_score / news_boost_ttl_sec: 설정 로더에서 갱신 (P13)
        self.news_boost_cache: dict[str, tuple[float, float]] = {}
        self.news_keywords_cache: list[str] = []
        self.news_boost_score: float = 1.0
        self.news_boost_ttl_sec: int = 300

        # ── 주문 간격 타이머 (그룹 E, 매수/매도 공통 — order_interval.py 헬퍼가 갱신) ──
        self._last_global_buy_ts: float = 0.0
        self._last_global_sell_ts: float = 0.0

        # ── 계좌 상태 (그룹 B + A broker_spec + F integrated_system_settings_cache) ──
        self.ws_account_subscribed: bool = False
        self.ws_connection_status: bool = False
        self.quote_subscribed: bool = False
        self.account_rest_bootstrapped: bool = False
        self.broker_rest_totals: dict = {
            "total_eval": 0, "total_pnl": 0, "total_buy": 0, "total_rate": 0.0,
        }
        self.auto_trade: AutoTradeManager | None = None
        self.integrated_system_settings_cache: dict = {}
        self.broker_spec: list = []
        self.broker_rest_apis: dict[str, Any] = {}  # {broker_id: RestApi}
        self.account_snapshot: dict = {}
        self.positions: list = []

        # ── 상수 (그룹 E) ────────────────────────────────────────────────────────
        self.REG_POST_ACK_GAP_SEC = 0.35

        # ── 스케줄러 상태 (그룹 D) ───────────────────────────────────────────────
        self.last_reset_date: str = ""
        self.krx_remove_done: bool = False
        self.confirmed_done: bool = False
        self.auto_trade_timer_handles: list = []
        self.midnight_timer_handle: asyncio.TimerHandle | None = None
        self.timetable_timer_handle: asyncio.TimerHandle | None = None  # 타임테이블 단일 타이머
        self.last_jif_received_at: datetime | None = None               # JIF 헬스체크용
        # ── JIF 카운트다운 override (그룹 D, P10 SSOT — JIF 1순위, 시간표 보조) ──
        # {label, remaining_sec, expires_at} | None — 만료 시 _get_active_override()가 None 반환 (P20).
        # expires_at는 만료 판정 전용 내부 필드 — _get_active_override() 반환 시 제외 (브로드캐스트 payload에 미포함).
        self.krx_countdown_override: dict | None = None
        self.nxt_countdown_override: dict | None = None
        # ── 사전 트리거 멱등성 가드 (그룹 D, 안 D 4단계 — 날짜 기반, P22 데이터 정합성) ──
        self.last_realtime_reset_date: str = ""        # 실시간 필드 초기화 실행 날짜 (YYYYMMDD)
        self.last_ws_subscribe_start_date: str = ""    # WS 구독 시작 실행 날짜 (YYYYMMDD)
        self.last_krx_pre_subscribe_date: str = ""     # KRX 사전 구독 실행 날짜 (YYYYMMDD)
        self.last_confirmed_download_date: str = ""    # 확정 데이터 다운로드 실행 날짜 (YYYYMMDD)

    async def on_filter_settings_changed(self) -> None:
        """필터 설정 변경 시 처리 (engine_sector 모듈 위임)."""
        from backend.app.services.sector_data_provider import _on_filter_settings_changed as _sector_on_filter
        await _sector_on_filter()


# ── 싱글톤 인스턴스 ─────────────────────────────────────────────────────
state = EngineState()


# ── 전역 상태 접근 헬퍼 (호환성 유지) ─────────────────────────────────────
def _get_rest_api_thread_sem() -> asyncio.Semaphore:
    if state.rest_api_thread_sem is None:
        state.rest_api_thread_sem = asyncio.Semaphore(1)
    return state.rest_api_thread_sem

def _get_account_rest_lock() -> asyncio.Lock:
    if state.account_rest_lock is None:
        state.account_rest_lock = asyncio.Lock()
    return state.account_rest_lock

def _notify_reg_ack(return_code: str = "") -> None:
    """`engine_ws_dispatch` REG/UNREG 응답 처리 끝에서 호출 -- 순차 전송 대기 해제."""
    state.reg_ack_return_code = return_code
    if state.reg_ack_event:
        state.reg_ack_event.set()


