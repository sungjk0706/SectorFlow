# -*- coding: utf-8 -*-
"""
엔진 라이프사이클 관련 모듈
- 엔진 시작/중지
- 엔진 상태 조회
- 거래 모드 전환
- 섹터 매수 실행
"""
import asyncio
import time
from backend.app.core.logger import get_logger
from backend.app.core.trade_mode import is_test_mode
from backend.app.services.auto_trading_effective import auto_buy_effective
from backend.app.services.engine_state import (
    _engine_task,
    _running,
    _state_manager,
    _engine_user_id,
    _engine_stop_event,
    _kiwoom_connector,
    _kiwoom_auth_provider,
    _connector_manager,
    _login_ok,
    _integrated_system_settings_cache,
    _auto_trade,
    _sector_summary_cache,
    _positions,
    # 실시간 틱 데이터 캐시 삭제로 import 제거 (_latest_trade_prices)
    _checked_stocks,
    _access_token,
    # _sector_buy_last_ts 제거: _master_stocks_cache[code]["_last_buy_ts"]로 통합
    _master_stocks_cache,
    _engine_loop_ref,
)

logger = get_logger("engine_lifecycle")


# ── 엔진 라이프사이클 ─────────────────────────────────────────────────

async def start_engine(user_id: str = "") -> bool:
    """엔진 시작."""
    global _engine_task, _running, _state_manager, _engine_user_id, _kiwoom_auth_provider
    from backend.app.services.state_manager import StateManager
    from backend.app.core.kiwoom_providers import KiwoomAuthProvider
    
    if _engine_task and not _engine_task.done():
        return False

    # StateManager 초기화
    if _state_manager is None:
        _state_manager = StateManager()
        await _state_manager.start()
        logger.info("[엔진] StateManager 초기화 완료")

    # KiwoomAuthProvider 초기화 (단일 인스턴스)
    if _kiwoom_auth_provider is None:
        _kiwoom_auth_provider = KiwoomAuthProvider()
        logger.info("[엔진] KiwoomAuthProvider 초기화 완료")

    _engine_user_id = user_id
    _running = True
    logger.info("[엔진] start_engine() - asyncio.create_task(_engine_loop()) 호출 직전")
    _engine_task = asyncio.create_task(_engine_loop())
    logger.info("[엔진] start_engine() - asyncio.create_task(_engine_loop()) 호출 완료")
    
    _broadcast_engine_ws()
    return True


async def _engine_loop() -> None:
    """엔진 메인 루프."""
    from backend.app.services import engine_loop
    
    logger.info("[엔진] _engine_loop() 진입, run_engine_loop() 호출 직전")
    try:
        await engine_loop.run_engine_loop()
        logger.info("[엔진] _engine_loop() 완료, run_engine_loop() 반환 후")
    except Exception as e:
        logger.error("[엔진] _engine_loop() 예외 발생: %s", e, exc_info=True)


async def stop_engine() -> None:
    """엔진 중지."""
    global _running, _engine_task
    from backend.app.services.engine_sector_confirm import cancel_sector_confirm_timer
    
    _running = False
    
    if _engine_stop_event:
        _engine_stop_event.set()

    # 디바운스 타이머 정리
    cancel_sector_confirm_timer()

    if _engine_task:
        _engine_task.cancel()
        try:
            await _engine_task
        except asyncio.CancelledError:
            pass
        _engine_task = None

    # 백그라운드 태스크 일괄 취소
    current = asyncio.current_task()
    all_tasks = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    bg_names = ("daily_time_scheduler",)
    bg_tasks = [t for t in all_tasks if any(n in (t.get_name() or "") for n in bg_names)]
    if bg_tasks:
        logger.info("[시작] 백그라운드 태스크 %d개 취소 중...", len(bg_tasks))
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        logger.info("[시작] 백그라운드 태스크 취소 완료")

    # 테스트모드 가상 잔고: 엔진 중지 시 초기화하지 않음
    # (포지션·예수금은 사용자가 직접 초기화할 때만 리셋)


def is_running() -> bool:
    """엔진이 현재 가동 중인지 확인한다."""
    return _running and _engine_task is not None and not _engine_task.done()


def get_status() -> dict:
    """엔진 상태 반환."""
    # 실시간 구독 종목 수
    import backend.app.services.engine_state as _es
    sub_count = sum(1 for entry in _es._master_stocks_cache.values() if entry.get("_subscribed", False))
    
    test_mode = is_test_mode(_es._integrated_system_settings_cache)
    ws = _es._connector_manager or _es._kiwoom_connector
    conn_ok = bool(ws and ws.is_connected())
    
    return {
        "running": _es._running,
        "connected": conn_ok,
        "broker_connected": conn_ok,  # 프론트 매핑용
        "logged_in": _es._login_ok,
        "login_ok": _es._login_ok,  # 프론트 매핑용
        "broker_token_valid": bool(_es._access_token),  # 토큰 발급 성공 여부
        "trade_mode": "test" if test_mode else "real",
        "is_test_mode": test_mode,  # 프론트 매핑용
        "engine_task_alive": _es._engine_task is not None and not _es._engine_task.done(),
        "stock_subscribed_count": sub_count,
        "ws_reg_total_estimate": sub_count,
    }


# ── 거래 모드 전환 ─────────────────────────────────────────────────

async def on_trade_mode_switched() -> None:
    """거래모드 전환 시 호출 -- 엔진 재기동 없이 계좌 구독 상태만 전환한다."""
    from backend.app.services import settlement_engine
    from backend.app.services.engine_ws import _subscribe_account_realtime, _subscribe_positions_stocks_realtime
    from backend.app.services.engine_account import _refresh_account_snapshot_meta, _broadcast_account
    
    _new_test = is_test_mode(_integrated_system_settings_cache)
    _mode_str = "테스트모드" if _new_test else "실전투자"
    logger.info("[연결] 거래모드 전환 -> %s (엔진 재기동 없음)", _mode_str)

    if not is_running() or not _kiwoom_connector or not _kiwoom_connector.is_connected():
        return

    if _new_test:
        # 실전→테스트: 계좌 실시간 구독(00/04) 해제, 분석용 구독은 유지
        from backend.app.services.engine_ws_reg import _unreg_grp
        await _unreg_grp(None, "10")
        logger.info("[구독] 테스트모드 전환 -- 계좌 실시간 구독(grp_no=10) 해제 완료")
        # Settlement Engine: 파일에서 상태 복원 + 만료 항목 정리 + 타이머 재스케줄
        settlement_engine.restore_state()
        logger.info("[시작] 테스트모드 전환 -- Settlement Engine 상태 복원 완료")
    else:
        # 테스트→실전: Settlement Engine 상태 저장 + 타이머 취소
        settlement_engine.save_state()
        logger.info("[시작] 실전모드 전환 -- Settlement Engine 상태 저장 완료")
        # 테스트→실전: 계좌 실시간 구독(00/04) + 보유종목 실시간(0B) 등록
        await _subscribe_account_realtime()
        await _subscribe_positions_stocks_realtime()
        logger.info("[구독] 실전모드 전환 -- 계좌 실시간 구독(00/04) + 보유종목 실시간(0B) 등록 완료")

    # 모드 전환 후 계좌 스냅샷 즉시 갱신
    await _refresh_account_snapshot_meta()
    _broadcast_account(reason="trade_mode_switch")
    
    # 엔진 상태 브로드캐스트 (프론트엔드 헤더 테스트모드 표시 갱신)
    _broadcast_engine_ws()


# ── 섹터 매수 ─────────────────────────────────────────────────────

async def _try_sector_buy() -> None:
    """
    이벤트 기반 매수 판단 — 실시간 데이터 변경 시 _do_sector_recompute()에서 호출.
    auto_buy_effective(시간 범위 + auto_buy_on + 마스터 스위치) 통과 시 매수 실행.
    쿨다운: sector_buy_cooldown_sec(기본 90초).
    """
    # _sector_buy_last_ts 제거: _master_stocks_cache[code]["_last_buy_ts"]로 통합
    from backend.app.services import dry_run
    from backend.app.services.daily_time_scheduler import is_krx_after_hours
    from backend.app.services.engine_symbol_utils import is_nxt_enabled
    import backend.app.services.engine_service as _es

    if not _running:
        return

    if not _auto_trade:
        return

    ss = _sector_summary_cache
    if not ss or not ss.buy_targets:
        return

    # ── 자동매수 게이트 (auto_buy_on + 시간 범위 + 마스터 스위치 통합 체크) ──
    if not auto_buy_effective(_es._integrated_system_settings_cache):
        return

    # ── 전역 조건 사전 체크 ──────────────────────────────────────────
    _max_limit = int(_es._integrated_system_settings_cache.get("max_stock_cnt", 5) or 5)
    if is_test_mode(_es._integrated_system_settings_cache):
        _pos_for_cnt = await dry_run.get_positions()
    else:
        _pos_for_cnt = _positions
    _holding_cnt = sum(1 for p in _pos_for_cnt if int(p.get("qty", 0)) > 0)
    if _holding_cnt >= _max_limit:
        return

    _buy_amt = int(_es._integrated_system_settings_cache.get("buy_amt", 0) or 0)
    if _buy_amt <= 0:
        return

    _max_daily = int(_es._integrated_system_settings_cache.get("max_daily_total_buy_amt", 0) or 0)
    if _max_daily > 0:
        _daily_remain = _max_daily - _auto_trade._daily_buy_spent
        if _daily_remain <= 0:
            return

    # ── 종목별 매수 시도 ─────────────────────────────────────────────
    cooldown = float(_es._integrated_system_settings_cache.get("sector_buy_cooldown_sec") or 90)
    now = time.time()

    _after_hours = is_krx_after_hours()

    for bt in ss.buy_targets:
        s = bt.stock
        if not s.guard_pass:
            continue
        # 장외 시간 KRX 단독 종목 매수 차단
        if _after_hours and not is_nxt_enabled(s.code):
            continue
        # _sector_buy_last_ts 제거: _master_stocks_cache[code]["_last_buy_ts"]로 통합
        last_ts = _master_stocks_cache.get(s.code, {}).get("_last_buy_ts", 0.0)
        if now - last_ts < cooldown:
            continue

        _master_stocks_cache[s.code]["_last_buy_ts"] = now
        
        logger.info("[섹터매수] 매수 시도: %s(%s) 섹터=%s 등락률=%.2f%%",
                    s.name, s.code, s.sector, s.change_rate)
        try:
            # 실시간 틱 데이터 캐시 삭제로 인해 현재가 조회 불가 (항상 0 반환)
            _price = 0
            if _price <= 0:
                logger.debug("[섹터매수] %s 실시간 시세 없음 -- 생략", s.code)
                continue
            _ordered = await _auto_trade.execute_buy(
                s.code, float(_price), _checked_stocks, _access_token,
                force_buy=False,
                reason=f"업종자동매수 업종={s.sector}",
            )
            if _ordered:
                logger.info("[섹터매수] 매수 주문 전송: %s(%s)", s.name, s.code)
                _holding_cnt += 1
                if _holding_cnt >= _max_limit:
                    break
                await _auto_trade._ensure_daily_buy_counter()
                if _max_daily > 0 and _auto_trade._daily_buy_spent >= _max_daily:
                    break
        except Exception as e:
            logger.warning("[섹터매수] execute_buy 오류 %s: %s", s.code, e, exc_info=True)


# ── 헬퍼 함수 ─────────────────────────────────────────────────

def _log(msg: str) -> None:
    """로그 출력."""
    logger.info(msg)


def _now_kst() -> str:
    """현재 KST 시간 반환."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


def _schedule_engine_coro(coro: asyncio.coroutines, *, context: str) -> bool:
    """
    엔진 이벤트 루프에 코루틴을 안전하게 스케줄한다.
    UI 스레드(이벤트 루프 없음)에서 호출되는 경우 call_soon_threadsafe를 사용한다.
    """
    loop = _engine_loop_ref
    if loop and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(lambda: loop.create_task(coro))
            return True
        except Exception as e:
            logger.warning("[데이터] %s 스케줄 실패함: %s", context, e, exc_info=True)
            try:
                coro.close()
            except Exception:
                logger.warning("[데이터] coroutine 정리 실패", exc_info=True)
            return False
    try:
        asyncio.get_running_loop().create_task(coro)
        return True
    except Exception as e:
        logger.warning("[데이터] %s 요청 실패함: %s", context, e, exc_info=True)
        try:
            coro.close()
        except Exception:
            logger.warning("[데이터] coroutine 정리 실패", exc_info=True)
        return False


def _sync_sell_overrides_from_settings() -> None:
    """sell_per_symbol -> AutoTradeManager.ts_overrides 동기화."""
    if not _auto_trade or not isinstance(_integrated_system_settings_cache, dict):
        return
    sp = _integrated_system_settings_cache.get("sell_per_symbol")
    _auto_trade.ts_overrides = dict(sp) if isinstance(sp, dict) else {}


def _broadcast_engine_ws() -> None:
    """엔진 상태 dict 를 WS 구독자에게 전달."""
    from backend.app.services.engine_account_notify import broadcast_engine_status_ws
    broadcast_engine_status_ws(get_status())


async def _delayed_resubscribe_stock_after_rate_limit(norm_cd: str) -> None:
    """105110 직후 재시도하지 않고, 일정 시간 뒤 필요한 종목만 REG 재전송 -- 시장가 운용으로 no-op."""
    pass


async def update_broker_credentials_live() -> None:
    """[근본 해결] 엔진 재기동 없이 실행 중인 REST 및 커넥터 인스턴스에 인증키를 즉시 핫-리로드하고 토큰 재발급을 가동한다."""
    import backend.app.services.engine_state as es
    from backend.app.core.settings_store import load_integrated_system_settings_for_editing
    from backend.app.core.broker_factory import reset_router

    _log("[설정] 무중단 실시간 자격 증명 핫-리로드 시작")

    # 1. 암호화 필드가 복호화된 평문 설정 딕셔너리 로드
    raw_settings = await load_integrated_system_settings_for_editing()
    broker_nm = str(es._integrated_system_settings_cache.get("broker", "kiwoom")).lower().strip()
    
    app_key = str(raw_settings.get(f"{broker_nm}_app_key") or "").strip()
    app_secret = str(raw_settings.get(f"{broker_nm}_app_secret") or "").strip()
    acnt_no = str(raw_settings.get(f"{broker_nm}_account_no") or "").strip()
    
    if not app_key or not app_secret:
        _log("[경고] 주입할 유효한 API Key 또는 Secret이 존재하지 않습니다.")
        return

    # 2. 실행 중인 KiwoomRestAPI 전역 인스턴스 내부 변수 즉시 갱신
    if es._rest_api:
        es._rest_api.app_key = app_key
        es._rest_api.app_secret = app_secret
        es._rest_api._acnt_no = acnt_no
        es._rest_api._token_info = None  # 이전의 실패 만료 상태 리셋
        _log("[설정] KiwoomRestAPI 인스턴스 자격 증명 핫-갱신 완료")
        
    # 3. 실행 중인 실시간 WebSocket 커넥터 내부 변수 즉시 갱신
    if es._kiwoom_connector:
        es._kiwoom_connector._app_key = app_key
        es._kiwoom_connector._app_secret = app_secret
        _log("[설정] KiwoomConnector 인스턴스 자격 증명 핫-갱신 완료")

    # 4. Broker Router 캐시 초기화
    reset_router()
    
    # 5. 비동기 백그라운드 태스크로 즉시 토큰 발급 및 파이프라인 언블로킹 시도
    es._token_ready_event.clear()  # 이전 대기 상태로 초기화
    asyncio.create_task(_retry_token_issuance_live(broker_nm))


async def _retry_token_issuance_live(broker_nm: str) -> None:
    """갱신된 자격 증명으로 즉각 토큰 발급을 재시도하고 이벤트를 브로드캐스팅한다."""
    import backend.app.services.engine_state as es
    
    _log("[연결] 갱신된 API Key 기반 실시간 토큰 발급 요청 중...")
    
    if not es._rest_api:
        _log("[오류] REST API 인스턴스가 존재하지 않아 토큰 요청을 중단합니다.")
        return
        
    try:
        # requests.post() 동기 통신을 이벤트 루프 차단 없이 비동기 백그라운드 실행
        success = await es._rest_api._ensure_token()
        if success and es._rest_api._token_info:
            new_token = es._rest_api._token_info.token
            es._access_token = new_token
            es._login_ok = True
            es._broker_tokens[broker_nm] = new_token
            
            _log(f"[연결] 증권사 토큰 재발급 성공! (토큰: {new_token[:10]}...)")
            
            # 대기 중인 모든 파이프라인에 인증 완료 신호 전파
            es._token_ready_event.set()
            
            # 실시간 웹소켓 커넥터가 끊겨 있거나 사용 불가 상태였다면 새 토큰으로 재연결 시도
            if es._kiwoom_connector and not es._kiwoom_connector.is_connected():
                _log("[연결] 새 토큰 기반 실시간 웹소켓 커넥터 연결 재시도 시작")
                asyncio.create_task(es._kiwoom_connector.connect())
        else:
            _log(f"[경고] 토큰 발급 응답 실패 - success={success}, token_info={es._rest_api._token_info}")
    except Exception as e:
        _log(f"[오류] 토큰 실시간 재발급 중 예외 발생: {e}")
