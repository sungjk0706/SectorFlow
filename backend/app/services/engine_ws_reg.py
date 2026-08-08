# -*- coding: utf-8 -*-
"""
키움 WebSocket REG/UNREG 구독 관리 — async 구독 함수 (state 기반).

페이로드 빌더 6종은 core/kiwoom_ws_reg.py로 이동됨 (COUPLING-S6 후속, P4/P23).
본 모듈은 state/connector에 의존하는 async 구독 오케스트레이션만 담당.
"""
from __future__ import annotations
import logging
import math
from backend.app.services.engine_symbol_utils import (
    _base_stk_cd,
    get_ws_subscribe_code,
    is_nxt_enabled,
)
from backend.app.services import engine_state
from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 헬퍼: 명시적 UNREG 전송
# ---------------------------------------------------------------------------

async def _unreg_grp(grp_no: str) -> bool:
    """해당 grp_no 전체를 UNREG(해지)한다.

    grp_no="4"(0B 종목)인 경우 등록된 종목 코드를 data에 포함하여 전송.
    그 외 grp는 data:[]로 전송.

    Args:
        grp_no: 해지할 구독 그룹 번호 (예: "4", "2", "5", "10")

    Returns:
        True if 성공(또는 등록 항목 없음), False if 실패/시간 초과.
    """
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected():
        return True

    # grp_no=4(0B): 등록된 종목 코드를 data에 포함
    if grp_no == "4":
        from backend.app.services.engine_ws import _ws_send_remove_fire_and_forget
        subscribed_codes = {cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_subscribed", False)}
        if subscribed_codes:
            stock_list = [get_ws_subscribe_code(cd) for cd in list(subscribed_codes)]
            _CHUNK = 100
            nchunks = math.ceil(len(stock_list) / _CHUNK)
            for ci in range(nchunks):
                chunk = stock_list[ci * _CHUNK : (ci + 1) * _CHUNK]
                payload = {
                    "trnm":    "REMOVE",
                    "grp_no":  grp_no,
                    "refresh": "1",
                    "data":    [{"item": chunk, "type": ["0B"]}],
                }
                try:
                    await _ws_send_remove_fire_and_forget(payload, sender=ws)
                except Exception as e:
                    logger.warning("[구독] 구독해지 청크 %d/%d 오류: %s", ci+1, nchunks, e, exc_info=True)
            for cd in subscribed_codes:
                if cd in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
            return True
    return True


async def subscribe_sector_stocks_0b(*, nxt_only: bool = False) -> None:
    """필터 통과 종목 + 보유종목 0B REG — 첫 청크 refresh='0'(기존 해지 후 등록), 이후 refresh='1'(누적 등록).

    engine_service.py of _subscribe_sector_stocks_0b() 이동 버전.
    보유종목 우선 등록, 200개 한도 적용, 이미 구독된 종목 제외.

    Args:
        nxt_only: True일 때 NXT 중복상장 종목(is_nxt_enabled=True)만 구독.
                  KRX 단독 종목은 08:59 _on_krx_pre_subscribe()에서 사전 구독.
    """
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected() or not engine_state.state.login_ok:
        return

    _WS_0B_LIMIT = int(engine_state.state.integrated_system_settings_cache.get("subscribe.max_0b_count", 200))

    # ── 1) 보유종목 코드 수집 (최우선) ──
    from backend.app.services.engine_account import get_positions
    positions = await get_positions()
    pos_codes_raw = [
        str(s.get("stk_cd", "")).strip()
        for s in positions
        if int(s.get("qty", 0) or 0) > 0 and str(s.get("stk_cd", "")).strip()
    ]
    pos_codes: list[str] = list(dict.fromkeys(
        _base_stk_cd(cd) for cd in pos_codes_raw if cd
    ))
    if nxt_only:
        pos_codes = [cd for cd in pos_codes if is_nxt_enabled(cd)]

    # ── 2) 필터 통과 종목 코드 수집 ──
    _raw_filter = {cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_filtered", False)}
    filtered_codes: list[str] = list(dict.fromkeys(
        _base_stk_cd(cd) for cd in _raw_filter if cd
    ))
    if nxt_only:
        filtered_codes = [cd for cd in filtered_codes if is_nxt_enabled(cd)]

    # ── 3) 합산 + 200개 한도 적용 (보유종목 우선) ──
    pos_set = set(pos_codes)
    filtered_only = [cd for cd in filtered_codes if cd not in pos_set]

    total_raw = len(pos_codes) + len(filtered_only)
    if total_raw > _WS_0B_LIMIT:
        allowed_filtered = max(0, _WS_0B_LIMIT - len(pos_codes))
        logger.warning(
            "[구독] 구독 한도 초과 — 보유 %d + 필터 %d = %d > %d, "
            "보유종목 우선 등록, 필터 통과 종목 %d개만 등록",
            len(pos_codes), len(filtered_only), total_raw,
            _WS_0B_LIMIT, allowed_filtered,
        )
        filtered_only = filtered_only[:allowed_filtered]

    # ── 4) 보유종목 별도 선행 REG ──
    pos_targets = [cd for cd in pos_codes if not engine_state.state.master_stocks_cache.get(cd, {}).get("_subscribed")]
    if pos_targets:
        for cd in pos_targets:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd]["_subscribed"] = True

        ok = await ws.subscribe_stocks(pos_targets)
        if ok:
            logger.info("[구독] 보유종목 구독 — %d종목", len(pos_targets))
        else:
            for cd in pos_targets:
                if cd in engine_state.state.master_stocks_cache:
                    entry = engine_state.state.master_stocks_cache[cd]
                    entry.pop("_subscribed", None)
            logger.warning("[구독] 보유종목 구독 실패 — %d종목 롤백", len(pos_targets))

    # ── 5) 필터 통과 종목 누적 REG ──
    filter_targets = [cd for cd in filtered_only if not engine_state.state.master_stocks_cache.get(cd, {}).get("_subscribed")]
    if not filter_targets:
        return

    for cd in filter_targets:
        if cd in engine_state.state.master_stocks_cache:
            engine_state.state.master_stocks_cache[cd]["_subscribed"] = True

    ok = await ws.subscribe_stocks(filter_targets)
    if ok:
        logger.info("[구독] 필터 종목 구독 — %d종목", len(filter_targets))
    else:
        for cd in filter_targets:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
        logger.warning("[구독] 필터 종목 구독 실패 — %d종목 롤백", len(filter_targets))


async def subscribe_index_realtime() -> bool:
    """코스피·코스닥 업종지수 실시간 구독 등록.

    커넥터의 subscribe_index() 메서드를 호출 (증권사별 내부 구현에 위임).
    Returns: True if 구독 성공, False otherwise.
    """
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected():
        logger.warning("[구독] 업종지수 구독 생략 — 연결 없음")
        return False

    if not hasattr(ws, "subscribe_index"):
        logger.warning("[구독] 업종지수 구독 생략 — 커넥터 미지원")
        return False

    try:
        ok = await ws.subscribe_index()
        if ok:
            logger.info("[구독] 업종지수 구독")
            return True
        else:
            logger.warning("[구독] 업종지수 구독 실패")
            return False
    except Exception as e:
        logger.warning("[구독] 업종지수 구독 실패: %s", e, exc_info=True)
        return False


async def subscribe_account_realtime() -> None:
    """계좌 단위 실시간 구독: 주문체결(00)·잔고(04) — refresh='0'으로 누적 등록.

    커넥터 subscribe_account()가 내부에서 증권사 분기 처리
    (키움: grp_no=10 계좌 구독 전송, LS: 소켓 연결·로그인 단계에서 자동 등록되므로 no-op).
    계좌번호 미설정 경고도 구현체 내부에서 수행.
    """
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected():
        return

    try:
        ok = await ws.subscribe_account()
        if ok:
            engine_state.state.ws_account_subscribed = True
            logger.info("[계좌] 계좌 구독 완료")
        else:
            logger.warning("[계좌] 계좌 구독 응답 시간 초과 또는 미지원")
    except Exception as e:
        logger.warning("[계좌] 계좌 구독 실패: %s", e, exc_info=True)


async def subscribe_positions_stocks_realtime() -> None:
    """보유 종목 0B REG — 이미 구독된 종목 제외, 누적 등록."""
    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected():
        logger.warning("[구독] 보유종목 구독 생략 — 연결 없음")
        return
    if not engine_state.state.login_ok:
        logger.warning("[구독] 보유종목 구독 생략 — 로그인 전 (로그인 후 재시도)")
        return

    from backend.app.services.engine_account import get_positions
    ordered: list[str] = []
    positions = await get_positions()
    for s in positions:
        cd = str(s.get("stk_cd", "")).strip()
        if cd and int(s.get("qty", 0)) > 0:
            ordered.append(cd)

    if not ordered:
        return

    norm_list = [_base_stk_cd(cd) for cd in ordered]
    logger.info("[구독] 보유종목 구독 대상 %d종목: %s", len(norm_list), norm_list)

    # 이미 구독 중인 종목 제외
    new_0b = [cd for cd in norm_list if not engine_state.state.master_stocks_cache.get(cd, {}).get("_subscribed")]
    if not new_0b:
        return

    for cd in new_0b:
        if cd in engine_state.state.master_stocks_cache:
            engine_state.state.master_stocks_cache[cd]["_subscribed"] = True

    ok = await ws.subscribe_stocks(new_0b)
    if ok:
        logger.info("[구독] 보유종목 구독 — %d종목", len(new_0b))
    else:
        for cd in new_0b:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
        logger.warning("[구독] 보유종목 구독 실패 — %d종목 롤백", len(new_0b))


# ---------------------------------------------------------------------------
# 재연결 후 구독 복원
# ---------------------------------------------------------------------------

async def restore_subscriptions_after_reconnect(broker_id: str) -> None:
    """재연결 성공 후 기존 구독 종목을 복원한다.

    engine_state.state.master_stocks_cache의 "_subscribed" 키를 기준으로 0B REG를 재전송한다.
    지수(0J)와 계좌(00/04) 구독도 함께 복원한다.

    Args:
        broker_id: 재연결된 증권사 ID
    """
    if not engine_state.state.login_ok:
        return

    ws = engine_state.state.connector_manager
    if not ws or not ws.is_connected():
        logger.warning("[연결] %s 구독 복원 생략 — 연결 없음", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()))
        return

    subscribed = {cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_subscribed", False)}
    if subscribed:
        # 재연결 시 서버 측 구독이 초기화됐으므로 "_subscribed" 키를 제거하고 재등록
        for cd in subscribed:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)

        targets_list = list(subscribed)
        for cd in targets_list:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd]["_subscribed"] = True
        
        ok = await ws.subscribe_stocks(targets_list)
        if ok:
            logger.info("[연결] %s 구독 복원 — %d종목", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()), len(targets_list))
        else:
            for cd in targets_list:
                if cd in engine_state.state.master_stocks_cache:
                    engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)
            logger.warning("[연결] %s 구독 복원 실패", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()))

    # 데이터(0J) 복원
    try:
        await subscribe_index_realtime()
        logger.info("[구독] %s 업종지수 구독 복원", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()))
    except Exception as e:
        logger.warning("[구독] %s 업종지수 구독 복원 실패: %s", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()), e, exc_info=True)

    # 계좌(00/04) 복원
    try:
        await subscribe_account_realtime()
        logger.info("[계좌] %s 계좌 구독 복원", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()))
    except Exception as e:
        logger.warning("[계좌] %s 계좌 구독 복원 실패: %s", BROKER_DISPLAY_NAMES.get(broker_id, broker_id.upper()), e, exc_info=True)
