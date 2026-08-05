# -*- coding: utf-8 -*-
"""
엔진 asyncio 메인 루프 -- 설정·브로커·WS 초기 연결.

`engine_state` 및 각 전문 모듈에서 직접 import하여 전역 상태를 읽고 갱신한다.
WS 연결/해제는 스케줄러(daily_time_scheduler)가 전적으로 관리한다.
"""
from __future__ import annotations
import asyncio
import time
from backend.app.core.broker_factory import get_router
from backend.app.core.broker_providers import AuthProvider
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
from backend.app.core.auth_utils import should_continue_recovery
from backend.app.core.constants import TOKEN_RECOVERY_INTERVAL_SEC, TOKEN_RECOVERY_MAX_ATTEMPTS
import logging
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.trading import AutoTradeManager
from backend.app.services.engine_cache import _load_caches_preboot
from backend.app.services import engine_state
logger = logging.getLogger(__name__)


async def _establish_realtime_connection() -> None:
    """실시간 연결을 1회 시도한다 (자의적 시간대 판정 제거 — 항상 연결 시도).

    access_token이 있으면 ConnectorManager를 생성·연결. 없으면 연결 안됨 상태 유지.
    연결 성공 여부와 무관하게 반환 — 이후 엔진 루프는 종료 신호만 대기 (P16 살아있는 경로).
    토큰 회복 루프에서도 호출 — 토큰 회복 성공 시 즉시 연결 맺기 (빈틈 없음).
    """
    if not engine_state.state.access_token:
        return
    if engine_state.state.connector_manager is not None:
        return  # 이미 연결됨 — 중복 연결 방지
    try:
        from backend.app.core.connector_manager import ConnectorManager
        from backend.app.services.engine_ws import _broker_message_handler
        from backend.app.services.core_queues import get_tick_queue
        from backend.app.services.engine_lifecycle import broadcast_engine_status as _broadcast_engine_ws
        _mgr = ConnectorManager()
        _mgr.set_message_callback(_broker_message_handler)
        tick_queue = get_tick_queue()
        for connector in _mgr._connectors.values():
            if hasattr(connector, 'set_queue_callback'):
                connector.set_queue_callback(tick_queue)
        logger.info("[연결] 커넥터 큐 콜백 설정 (틱 큐)")
        engine_state.state.connector_manager = _mgr
        await _mgr.connect_all()
        if _mgr.is_connected():
            logger.info("[연결] 실시간 연결")
        else:
            logger.warning("[연결] 실시간 연결 실패 — 재연결 루프 기동 중")
        await _broadcast_engine_ws()
    except Exception as e:
        logger.error("[연결] 실시간 연결 초기화 실패: %s", e, exc_info=True)
        engine_state.state.connector_manager = None


async def _cache_and_bootstrap(settings: dict) -> None:
    """캐시 선행 로드 → engine-ready WS 전송 → 부트스트랩 순차 실행.

    Cache_Preboot 실패 시 try/except에서 에러 로그 후 계속 진행 (P25 격리된 실패).
    engine-ready 브로드캐스트는 캐시 로드 성공/실패 무관 항상 실행 (P21 사용자 투명성).
    Bootstrap은 Cache_Preboot 완료 이후에만 실행 (순차 의존 보존).
    적격종목 캐시 없으면 빈 상태로 초기화하고 상태 플래그 설정.
    """
    # ── 캐시 선행 로드 (WS 구간 안이면 내부에서 시세 0으로 적재) ──
    # _load_caches_preboot 내부에서 모든 기동 로직 완료 (단일 파이프라인)
    try:
        await _load_caches_preboot(settings)
    except Exception:
        engine_state.state.degraded_mode = True
        logger.error("[연산] 캐시 선행 로드 치명 오류 — 감소 모드로 기동", exc_info=True)

    # 앱준비 완료 여부와 상관없이 engine-ready 전송 (P21 사용자 투명성)
    try:
        from backend.app.web.ws_manager import ws_manager
        await ws_manager.broadcast("engine-ready", {"_v": 1, "ready": True})
        logger.info("[연산] 데이터 로드 — 실시간 준비됨")
    except Exception:
        logger.warning("[연산] 엔진 준비 브로드캐스트 실패", exc_info=True)


async def _get_all_tokens_async(router) -> None:
    """
    startup 인증 대상인 활성 broker 1개의 토큰만 발급한다 (Lazy Authentication).

    - 발급 대상 = settings["broker"] 단일 항목.
      startup 비배치 소비자는 engine_loop.py run_engine_loop()의
      broker_tokens.get(broker_nm) 단일 지점이며, broker_nm = settings["broker"]이다.
    - confirmed_data_broker는 startup에서 제외하고 market_close_pipeline 자체 Lazy Auth에 위임.
    - router._auth_cache에 없는 증권사도 _create_provider로 생성하여 발급.
    - 발급된 토큰은 state.broker_tokens[broker_id]로 저장한다.
    - 실패 종류(일시/영구)는 state.token_failure_kind에 저장 (5세션 — run_engine_loop 분기용).
      성공 시 None, 실패 시 "transient"/"permanent".
    """
    auth_cache: dict[str, AuthProvider] = getattr(router, "_auth_cache", {})

    # 활성 broker 1개만 발급 대상 (Lazy Authentication)
    # confirmed_data_broker는 startup에서 제외 — 배치 경로가 자체 발급 담당.
    broker_id = str(
        engine_state.state.integrated_system_settings_cache.get("broker") or ""
    ).lower().strip()

    # API 키가 설정된 활성 broker만 발급 대상
    valid_broker_ids: list[str] = []
    if broker_id:
        _key = engine_state.state.integrated_system_settings_cache.get(f"{broker_id}_app_key", "")
        _sec = engine_state.state.integrated_system_settings_cache.get(f"{broker_id}_app_secret", "")
        if _key and _sec:
            valid_broker_ids.append(broker_id)

    if not valid_broker_ids:
        return

    async def _fetch_one(broker_id: str) -> tuple[str, str | None, str | None]:
        try:
            auth_provider = auth_cache.get(broker_id)
            if auth_provider is None:
                from backend.app.core.broker_registry import _create_provider
                auth_provider = _create_provider(
                    "auth", broker_id,
                    engine_state.state.integrated_system_settings_cache, auth_cache,
                )
            assert auth_provider is not None
            # rest_api의 _issue_token() 직접 호출 — 실패 종류(일시/영구) 취득 (3·4세션).
            # AuthProvider.get_access_token()은 실패 시 None만 반환하므로 종류를 알 수 없음.
            rest_api = getattr(auth_provider, "rest_api", None)
            if rest_api is not None and hasattr(rest_api, "_issue_token"):
                ok, failure_kind = await rest_api._issue_token()
                if ok:
                    # 토큰 값은 get_token/get_access_token 경유로 취득 (증권사별 필드 차이)
                    token = None
                    if hasattr(rest_api, "get_token"):
                        token = rest_api.get_token()
                    elif hasattr(rest_api, "get_access_token"):
                        token = await rest_api.get_access_token()
                    return broker_id, token, None
                return broker_id, None, failure_kind
            # rest_api가 없는 경우 기존 get_access_token() 경유 (실패 종류 미상 — 일시로 간주)
            token = await auth_provider.get_access_token()
            if token:
                return broker_id, token, None
            return broker_id, None, "transient"
        except Exception as e:
            logger.warning("[연결] %s 토큰 발급 실패: %s", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()), e, exc_info=True)
            return broker_id, None, "transient"

    results = await asyncio.gather(
        *[_fetch_one(bid) for bid in valid_broker_ids],
        return_exceptions=True,
    )

    engine_state.state.broker_tokens.clear()

    last_failure_kind: str | None = None

    for result in results:
        if isinstance(result, tuple):
            broker_id, token, failure_kind = result
            last_failure_kind = failure_kind
            if token:
                engine_state.state.broker_tokens[broker_id] = token
                last_failure_kind = None

    # 실패 종류를 state에 저장 — run_engine_loop 분기용 (5세션)
    engine_state.state.token_failure_kind = last_failure_kind


async def _token_recovery_loop(router, broker_nm: str) -> None:
    """백그라운드 토큰 회복 루프 (설계서 결정 2·5).

    시작 시 토큰 발급이 일시 실패한 경우에만 진입. 30초 간격 최대 10회(약 5분) 재시도.
    회복 성공 시 state.access_token 설정 + 화면에 정상 모드 전환 알림.
    10회 후에도 실패 시 연결 안됨 상태 유지 + "수동 재시작 필요" 안내.
    중복 루프 방지: state.token_recovery_in_progress 플래그로 단일 진입 보장 (P17).
    """
    from backend.app.services.engine_lifecycle import broadcast_engine_status, log_message

    engine_state.state.token_recovery_in_progress = True
    broker_display = BROKER_DISPLAY_NAMES.get(broker_nm, broker_nm)

    try:
        for attempt in range(TOKEN_RECOVERY_MAX_ATTEMPTS):
            if not should_continue_recovery(attempt):
                break
            # 엔진 종료 요청 시 루프 즉시 종료
            if engine_state.state.engine_shutdown_requested:
                log_message(f" [연결] {broker_display} 토큰 회복 루프 중단 — 엔진 종료 요청.")
                return
            await asyncio.sleep(TOKEN_RECOVERY_INTERVAL_SEC)
            if engine_state.state.engine_shutdown_requested:
                log_message(f" [연결] {broker_display} 토큰 회복 루프 중단 — 엔진 종료 요청.")
                return

            try:
                await _get_all_tokens_async(router)
            except Exception as e:
                logger.warning("[연결] %s 토큰 회복 시도 %d 실패: %s", broker_display, attempt + 1, e, exc_info=True)
                continue

            # _get_all_tokens_async는 state에 토큰·실패 종류를 저장 (반환값 없음)
            token = engine_state.state.broker_tokens.get(broker_nm)
            failure_kind = engine_state.state.token_failure_kind

            if token:
                # 회복 성공 — 정상 모드 전환
                engine_state.state.access_token = token
                engine_state.state.token_failure_kind = None
                engine_state.state.token_recovery_in_progress = False
                # ── 관리자 누락 방지 — 부팅 시 토큰이 없어 생성되지 않았던 관리자를 ──
                # 회복 성공 시점에 생성 (부팅 시 이미 생성된 경우 중복 생성 방지).
                if engine_state.state.auto_trade is None:
                    from backend.app.services.engine_lifecycle import sync_sell_overrides as _sync_sell_overrides_from_settings
                    from backend.app.services.engine_config import _get_settings
                    engine_state.state.auto_trade = AutoTradeManager(
                        get_settings_fn=_get_settings,
                    )
                    _sync_sell_overrides_from_settings()
                    # 매수 한도 화면 갱신 — 관리자 생성 전에는 0원으로 표시되었으므로
                    # 생성 즉시 실제 거래내역 기반 값으로 갱신 (P21 사용자 투명성).
                    try:
                        from backend.app.services.engine_account import _broadcast_buy_limit_status
                        await _broadcast_buy_limit_status()
                    except Exception:
                        logger.warning("[연결] 토큰 회복 후 매수 한도 브로드캐스트 실패", exc_info=True)
                log_message(f" [연결] {broker_display} 토큰 회복 성공. 정상 모드 전환.")
                # 토큰 회복 성공 시 즉시 실시간 연결 시도 (자의적 시간대 판정 제거 — 항상 연결).
                # 엔진 루프의 구간 감지 루프가 제거되었으므로, 여기서 직접 연결을 맺어야
                # 회복 후 데이터 흐름이 끊기지 않는다 (P16 살아있는 경로).
                await _establish_realtime_connection()
                await broadcast_engine_status()
                return

            # 영구 실패로 전환된 경우 회복 루프 즉시 종료 (사용자 액션 필요)
            if failure_kind == "permanent":
                engine_state.state.access_token = None
                engine_state.state.token_failure_kind = "permanent"
                engine_state.state.token_recovery_in_progress = False
                log_message(f" [연결] {broker_display} 토큰 회복 중 영구 실패 감지. API 키 확인 필요. 연결 안됨 상태 유지.")
                await broadcast_engine_status()
                return

        # 10회 후에도 실패 — 연결 안됨 상태 유지
        engine_state.state.token_recovery_in_progress = False
        log_message(f" [연결] {broker_display} 토큰 회복 {TOKEN_RECOVERY_MAX_ATTEMPTS}회 실패. 수동 재시작 필요. 연결 안됨 상태 유지.")
        await broadcast_engine_status()
    except asyncio.CancelledError:
        engine_state.state.token_recovery_in_progress = False
        log_message(f" [연결] {broker_display} 토큰 회복 루프 취소됨.")
        raise
    except Exception as e:
        engine_state.state.token_recovery_in_progress = False
        logger.warning("[연결] %s 토큰 회복 루프 오류: %s", broker_display, e, exc_info=True)


async def _load_broker_spec_async(broker_nm: str, settings: dict) -> list:
    """SQLite DB에서 broker_specs를 로드.

    broker_specs 테이블에서 해당 증권사의 스펙을 로드한다.
    role_mappings(dict)에서 list로 변환하여 반환.
    실패 시 빈 리스트 반환 + 경고 로그.
    """
    try:
        _broker_specs = settings.get("_broker_specs", {})
        if broker_nm in _broker_specs:
            spec = _broker_specs[broker_nm]
            if isinstance(spec, dict):
                role_mappings = spec.get("role_mappings", {})
                if isinstance(role_mappings, dict):
                    return list(role_mappings.values())  # dict → list 변환
                else:
                    logger.warning("[연산] 역할 매핑 형식 오류: %s (기대: 사전 형식)", type(role_mappings))
                    return []
            else:
                logger.warning("[연산] 증권사 명세 형식 오류: %s (기대: 사전 형식)", type(spec))
                return []
        return []
    except Exception as e:
        logger.warning("[연산] 증권사 스펙 로드 실패: %s", e, exc_info=True)
        return []


async def run_engine_loop() -> None:

    engine_state.state.login_ok = False
    engine_state.state.connector_manager = None
    engine_state.state.broker_tokens.clear()
    engine_state.state.token_ready_event.clear()
    # _master_stocks_cache에서 "_subscribed" 제거
    for entry in engine_state.state.master_stocks_cache.values():
        entry.pop("_subscribed", None)
    from backend.app.services.engine_state import _notify_reg_ack
    _notify_reg_ack()
    engine_state.state.integrated_system_settings_cache["sector_stock_layout"] = []
    from backend.app.services.engine_account_notify import _rebuild_layout_cache
    _rebuild_layout_cache([])
    engine_state.state.running = True
    engine_state.state.engine_loop_ref = asyncio.get_running_loop()
    # 캐시선행 플래그 초기화
    engine_state.state.preboot_cache_loaded = False
    engine_state.state.preboot_ready_event.clear()
    # 계좌 REST Lock 초기화 -- 이전 세션 잠금 상태 초기화
    engine_state.state.account_rest_lock = None
    # 토큰 회복 루프 상태 초기화 — 이전 세션 잔존 방지 (5세션)
    engine_state.state.token_recovery_in_progress = False
    engine_state.state.token_failure_kind = None

    # 전역 이벤트 버스 (Queues)는 app.py lifespan에서 이미 초기화됨

    try:
        # state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = engine_state.state.integrated_system_settings_cache

        # ── WS 구독 상태 초기화 (표준 기동 순서: 초기화 → 연결 → 구독) ──
        # 엔진 루프의 WS 연결/구독/틱 수신 이전에 실행 보장 (경쟁 조건 제거, P22 데이터 정합성).
        # preboot_cache_loaded=False 상태이므로 _reset_realtime_fields()는 자동 스킵되고
        # engine_cache._load_caches_preboot()에서 캐시 로드 후 수행됨.
        # schedule_engine_task()가 정상 동작하도록 engine_loop_ref 설정 이후에 실행.
        from backend.app.services.daily_time_scheduler import _init_ws_subscribe_state
        await _init_ws_subscribe_state()

        # 엔진 내부 준비 완료 시그널 — Uvicorn 리스닝 + 브라우저 열기 즉시 허용
        engine_state.state.preboot_ready_event.set()

        # ── broker/router 생성 (단일 소스 진리: _integrated_system_settings_cache 직접 사용) ──
        broker_nm: str = str(settings["broker"]).lower().strip()
        router = get_router()

        # ── API 키 검증: broker_config.websocket 기준 모든 증권사 확인 ──
        broker_config = settings["broker_config"]
        ws_val = str(broker_config.get("websocket") or broker_nm).lower().strip()
        ws_brokers = [b.strip() for b in ws_val.split(",") if b.strip()]

        valid_brokers = []
        for _bk in ws_brokers:
            _key = settings.get(f"{_bk}_app_key", "")
            _sec = settings.get(f"{_bk}_app_secret", "")
            if _key and _sec:
                valid_brokers.append(_bk)
            else:
                from backend.app.services.engine_lifecycle import log_message
                log_message(f" [구동] {BROKER_DISPLAY_NAMES.get(_bk, _bk)} API 키가 설정되지 않았습니다. 일반설정에서 입력하세요.")

        if not valid_brokers:
            from backend.app.services.engine_lifecycle import log_message, broadcast_engine_status
            log_message(f" [구동] 유효한 API 키가 없습니다 (대상: {', '.join(BROKER_DISPLAY_NAMES.get(b, b) for b in ws_brokers)}). 일반설정에서 증권사 API 키를 입력하세요.")
            await broadcast_engine_status()
            # 엔진 중단하지 않고 계속 진행 (테스트모드/연결 안됨 상태 허용)

        # REST/토큰 발급은 기준 증권사(broker_nm) 기준 유지

        # ── 병렬 초기화: 캐시+앱준비 / 토큰 발급 / 브로커 스펙 로드 ──
        _t_parallel_start = time.perf_counter()

        # 3개 독립 파이프라인 병렬 실행 — broker_spec은 gather 완료 후 사용
        # _get_all_tokens_async는 state.token_failure_kind를 설정 (5세션) — gather와 분리하여
        # 테스트에서 _get_all_tokens_async를 직접 mock할 수 있도록 별도 await.
        async def _load_spec():
            engine_state.state.broker_spec = await _load_broker_spec_async(broker_nm, settings)

        await asyncio.gather(
            _cache_and_bootstrap(settings),
            _load_spec(),
        )
        # 토큰 발급은 캐시 로드와 독립 — gather 이후 직접 실행 (state.token_failure_kind 설정)
        await _get_all_tokens_async(router)

        # 토큰 발급 phase 완료 시그널 — WS 유니캐스트가 stale broker_statuses를
        # 전송하지 않도록 보장 (token_ready_event.wait()에서 대기 중인 태스크가 깨어남)
        engine_state.state.token_ready_event.set()

        # 화면별 구독 대상 초기 생성 — 업종 순위 요약 준비 후 원본에서 대상 구축.
        # 백그라운드 실행: sector_summary_ready_event 대기 후 초기화하므로 기동 블로킹 없음.
        from backend.app.services.page_subscription_targets import initialize_page_targets
        _page_targets_task = asyncio.create_task(initialize_page_targets())
        _page_targets_task.add_done_callback(
            lambda t: logger.warning("[구독대상] 초기 생성 작업 실패: %s", t.exception()) if t.exception() else None
        )

        # 가상 예수금 로드는 _cache_and_bootstrap(→ engine_cache)에서 load_state로 수행

        _t_parallel_end = time.perf_counter()
        logger.info(
            "[연산] 엔진 준비 — %.0fms",
            (_t_parallel_end - _t_parallel_start) * 1000,
        )

        # ── broker_spec 결과 반영 ──
        if isinstance(engine_state.state.broker_spec, list):
            acnt_no = settings.get(f"{broker_nm}_account_no", "")
            from backend.app.services.engine_lifecycle import log_message
            log_message(f"[연산] 설정 로딩 — TR {len(engine_state.state.broker_spec)}개, 계좌: {acnt_no or '미설정'}")

        # ── token 결과 반영 (실패 종류별 분기 — 5세션) ──
        token = engine_state.state.broker_tokens.get(broker_nm)
        _failure_kind = engine_state.state.token_failure_kind
        if token:
            engine_state.state.access_token = token
            engine_state.state.token_failure_kind = None
        elif _failure_kind == "permanent":
            # 영구 실패 — 회복 루프 진입 없이 즉시 연결 안됨 상태 (사용자 액션 유도)
            from backend.app.services.engine_lifecycle import log_message, broadcast_engine_status
            engine_state.state.access_token = None
            engine_state.state.token_failure_kind = "permanent"
            log_message(f" [연결] {BROKER_DISPLAY_NAMES.get(broker_nm, broker_nm)} 토큰 발급 영구 실패. API 키 확인 필요. 연결 안됨 상태로 기동.")
            await broadcast_engine_status()
        else:
            # 일시 실패 — 백그라운드 회복 루프 진입
            from backend.app.services.engine_lifecycle import log_message
            engine_state.state.access_token = None
            engine_state.state.token_failure_kind = "transient"
            # 중복 루프 방지 — 이미 회복 루프 진행 중이면 추가 생성 금지 (P17 단일 소스)
            if not engine_state.state.token_recovery_in_progress:
                from backend.app.services.engine_lifecycle import schedule_engine_task
                log_message(f" [연결] {BROKER_DISPLAY_NAMES.get(broker_nm, broker_nm)} 토큰 발급 일시 실패. 백그라운드 회복 루프 시작. 연결 안됨 상태로 기동.")
                schedule_engine_task(
                    _token_recovery_loop(router, broker_nm),
                    context="token-recovery-loop",
                )

        # ── 계좌 조회용 REST = Router의 AuthProvider에서 REST 실시간 인스턴스 공유 ──
        _auth_provider = router.auth
        if hasattr(_auth_provider, 'rest_api'):
            _is_test = is_test_mode(settings)
            # 증권사별 state 분리
            _rest_api = _auth_provider.rest_api
            _rest_api._acnt_no = str(settings.get(f"{broker_nm}_account_no", "") or "")
            for spec in engine_state.state.broker_spec:
                tr = spec.get("tr_id", "")
                if tr == "kt00001":
                    _rest_api._deposit_tr_id = tr
                elif tr == "kt00018":
                    _rest_api._balance_tr_id = tr
                elif tr == "ka00001":
                    _rest_api._account_tr_id = tr
            engine_state.state.broker_rest_apis[broker_nm] = _rest_api
            from backend.app.services.engine_lifecycle import log_message
            log_message(f"[연결] {BROKER_DISPLAY_NAMES.get(broker_nm, broker_nm)} 연결 (테스트모드={_is_test})")



        _is_test_flag  = is_test_mode(settings)
        _mode_str      = "테스트모드" if _is_test_flag else "실전투자"
        _broker_str    = BROKER_DISPLAY_NAMES.get(broker_nm, "증권사")
        _acnt_raw      = (
            settings.get(f"{broker_nm}_account_no")
            or "미설정"
        )
        _acnt_disp     = (_acnt_raw[:4] + "****") if len(_acnt_raw) >= 4 else _acnt_raw
        _real_warn     = " ★ 실제 자금 투입 ★" if not _is_test_flag else ""
        logger.info("[연산] 엔진 기동 — %s %s / 계좌: %s%s", _broker_str, _mode_str, _acnt_disp, _real_warn)

        if engine_state.state.access_token:
            from backend.app.services.engine_lifecycle import sync_sell_overrides as _sync_sell_overrides_from_settings
            from backend.app.services.engine_config import _get_settings
            engine_state.state.auto_trade = AutoTradeManager(
                get_settings_fn=_get_settings,
            )
            _sync_sell_overrides_from_settings()

        from backend.app.services.engine_account import _broadcast_buy_limit_status
        try:
            await _broadcast_buy_limit_status()
        except Exception:
            logger.warning("[연산] 매수 한도 브로드캐스트 실패", exc_info=True)

        from backend.app.services.engine_lifecycle import broadcast_engine_status as _broadcast_engine_ws
        await _broadcast_engine_ws()

        # ── 백그라운드 태스크로 파이프라인 루프 시작 (Step 7: 중앙 코디네이터 연동) ──
        # 테스트모드와 무관하게 항상 시작 (UI 전송 등 돈과 무관한 기능 실행)
        # 순서 보장: Ingestion -> Compute
        # Gateway 루프는 app.py에서 독립적으로 시작 (파이프라인 독립성 보장)
        from backend.app.pipelines.pipeline_compute import start_compute_loop

        await start_compute_loop()

        # ── 실시간 연결 (자의적 시간대 판정 제거 — 기동 시 1회 연결 시도) ──
        # access_token이 있으면 즉시 증권사 실시간 연결 시도.
        # 연결 해제는 장마감(20:00) 이벤트(_on_ws_subscribe_end)가 직접 수행.
        # 토큰 회복 루프 성공 시에도 _establish_realtime_connection()이 직접 연결 맺음.
        engine_state.state.engine_stop_event.clear()
        await _establish_realtime_connection()

        # 엔진 종료 신호만 대기 — 중간 시간대 재판정 루프 제거 (P24 단순성, P16 살아있는 경로).
        await engine_state.state.engine_stop_event.wait()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        from backend.app.services.engine_lifecycle import log_message
        log_message(f" [구동] 예외: {e}")
        logger.warning("[연산] 엔진 루프 예외", exc_info=True)
    finally:
        # ── 백그라운드 태스크 종료 (Step 7: 중앙 코디네이터 연동) ───────────────
        # start_compute_loop()는 _compute_task/_sector_recompute_task 서브태스크를
        # 생성 후 즉시 반환하므로, 외부 태스크 취소로는 실제 루프가 종료되지 않음.
        # stop_compute_loop()를 호출하여 _compute_running=False + 서브태스크 취소 보장.
        from backend.app.pipelines.pipeline_compute import stop_compute_loop
        try:
            await stop_compute_loop()
        except Exception as e:
            logger.warning("[연산] 계산 루프 종료 실패: %s", e, exc_info=True)

        logger.info("[연산] 백그라운드 태스크 종료")

        # ── Event Bus 종료 ───────────────────────────────────────────────────
        # P25 격리된 실패 — 연결 해제 실패가 이후 REST 정리 루프를 블로킹하지 않도록 per-step try/except.
        if engine_state.state.connector_manager:
            try:
                await engine_state.state.connector_manager.disconnect_all()
            except Exception as e:
                logger.warning("[연산] 실시간 연결 일괄 해제 실패: %s", e, exc_info=True)
        engine_state.state.connector_manager = None
        # 증권사별 REST API 클라이언트 정리 — per-broker 격리 (P25)
        # 한 증권사 토큰 폐기/클라이언트 정리 실패가 다른 증권사 정리를 차단하지 않음.
        for _broker_id, _rest_api in engine_state.state.broker_rest_apis.items():
            try:
                await _rest_api.revoke_token()
            except Exception as e:
                logger.warning("[연산] %s 토큰 폐기 실패: %s", BROKER_DISPLAY_NAMES.get(_broker_id, _broker_id), e, exc_info=True)
            try:
                if hasattr(_rest_api, '_reset_client'):
                    await _rest_api._reset_client()
                elif hasattr(_rest_api, '_client') and _rest_api._client:
                    await _rest_api._client.aclose()
            except Exception as e:
                logger.warning("[연산] %s REST 클라이언트 정리 실패: %s", BROKER_DISPLAY_NAMES.get(_broker_id, _broker_id), e, exc_info=True)
        engine_state.state.broker_rest_apis.clear()
        engine_state.state.broker_tokens.clear()
        engine_state.state.running = False
        # 토큰 회복 루프 진행 플래그만 해제 — token_failure_kind는 다음 기동 시 시작 부분에서 초기화 (5세션)
        engine_state.state.token_recovery_in_progress = False
        from backend.app.services.engine_lifecycle import broadcast_engine_status, log_message, get_current_kst_time
        await broadcast_engine_status()
        log_message(f"[연산] 정지됨 ({get_current_kst_time()})")
