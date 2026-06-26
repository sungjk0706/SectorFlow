from __future__ import annotations
# -*- coding: utf-8 -*-
"""
키움 WebSocket REG/UNREG 구독 관리 — 순수 함수 + async 구독 함수.

engine_service.py에서 분리된 REG 구독 로직.
"""

import logging
import math

from backend.app.services.engine_symbol_utils import (
    _format_kiwoom_reg_stk_cd,
    get_ws_subscribe_code,
)
from backend.app.services.engine_state import state

logger = logging.getLogger("engine")


def build_0b_reg_payloads(
    stocks: list[str], chunk_size: int = 100, *, reset_first: bool = True
) -> list[dict]:
    """종목 리스트를 chunk_size 단위로 분할하여 0B REG 페이로드 리스트를 생성한다.

    키움 공식 규격:
      refresh="0" → 기존 해지 후 새로 등록 (첫 청크에 사용하여 이전 구독 정리)
      refresh="1" → 기존 유지 + 누적 등록 (2번째 청크부터 사용하여 종목 추가)

    Args:
        stocks: 구독할 종목코드 리스트 (예: ["005930_AL", "000660"])
        chunk_size: 한 청크에 담을 최대 종목 수 (기본 100)
        reset_first: True면 첫 청크 refresh="0" (전체 재등록 시),
                     False면 모든 청크 refresh="1" (기존 구독에 추가 시)

    Returns:
        REG 페이로드 dict 리스트. 빈 리스트이거나 chunk_size < 1이면 빈 리스트.
    """
    if not stocks or chunk_size < 1:
        return []

    total = len(stocks)
    nchunks = math.ceil(total / chunk_size)
    payloads: list[dict] = []

    for ci in range(nchunks):
        chunk = stocks[ci * chunk_size : (ci + 1) * chunk_size]
        refresh_val = "0" if (ci == 0 and reset_first) else "1"
        payloads.append({
            "trnm":    "REG",
            "grp_no":  "4",
            "refresh": refresh_val,
            "data":    [{"item": chunk, "type": ["0B"]}],
        })

    return payloads


def build_0b_remove_payloads(
    stocks: list[str], chunk_size: int = 100
) -> list[dict]:
    """종목 리스트를 chunk_size 단위로 분할하여 0B REMOVE 페이로드 리스트를 생성한다.

    키움 공식 규격:
      trnm="REMOVE", grp_no="4", type=["0B"], refresh="1"

    Args:
        stocks: 구독 해지할 종목코드 리스트 (예: ["005930_AL", "000660"])
        chunk_size: 한 청크에 담을 최대 종목 수 (기본 100)

    Returns:
        REMOVE 페이로드 dict 리스트. 빈 리스트이거나 chunk_size < 1이면 빈 리스트.
    """
    if not stocks or chunk_size < 1:
        return []

    total = len(stocks)
    nchunks = math.ceil(total / chunk_size)
    payloads: list[dict] = []

    for ci in range(nchunks):
        chunk = stocks[ci * chunk_size : (ci + 1) * chunk_size]
        payloads.append({
            "trnm":    "REMOVE",
            "grp_no":  "4",
            "refresh": "1",
            "data":    [{"item": chunk, "type": ["0B"]}],
        })

    return payloads


def build_0d_reg_payloads(
    stocks: list[str], chunk_size: int = 50
) -> list[dict]:
    """종목 리스트를 chunk_size 단위로 분할하여 0D REG 페이로드 리스트를 생성한다.

    키움 공식 규격:
      trnm="REG", grp_no="7", refresh="1"(누적 등록), type=["0D"]

    Args:
        stocks: 구독할 종목코드 리스트 (예: ["005930", "000660"])
        chunk_size: 한 청크에 담을 최대 종목 수 (기본 50)

    Returns:
        REG 페이로드 dict 리스트. 빈 리스트이거나 chunk_size < 1이면 빈 리스트.
    """
    if not stocks or chunk_size < 1:
        return []

    total = len(stocks)
    nchunks = math.ceil(total / chunk_size)
    payloads: list[dict] = []

    for ci in range(nchunks):
        chunk = stocks[ci * chunk_size : (ci + 1) * chunk_size]
        payloads.append({
            "trnm":    "REG",
            "grp_no":  "7",
            "refresh": "1",
            "data":    [{"item": chunk, "type": ["0D"]}],
        })

    return payloads


def build_0d_remove_payloads(
    stocks: list[str], chunk_size: int = 50
) -> list[dict]:
    """종목 리스트를 chunk_size 단위로 분할하여 0D REMOVE 페이로드 리스트를 생성한다.

    키움 공식 규격:
      trnm="REMOVE", grp_no="7", refresh="1", type=["0D"]

    Args:
        stocks: 구독 해지할 종목코드 리스트 (예: ["005930", "000660"])
        chunk_size: 한 청크에 담을 최대 종목 수 (기본 50)

    Returns:
        REMOVE 페이로드 dict 리스트. 빈 리스트이거나 chunk_size < 1이면 빈 리스트.
    """
    if not stocks or chunk_size < 1:
        return []

    total = len(stocks)
    nchunks = math.ceil(total / chunk_size)
    payloads: list[dict] = []

    for ci in range(nchunks):
        chunk = stocks[ci * chunk_size : (ci + 1) * chunk_size]
        payloads.append({
            "trnm":    "REMOVE",
            "grp_no":  "7",
            "refresh": "1",
            "data":    [{"item": chunk, "type": ["0D"]}],
        })

    return payloads


def build_index_reg_payload() -> dict:
    """코스피(001)·코스닥(101) 업종지수 0J REG 페이로드를 생성한다.

    refresh="0"(기존 해지 후 등록)을 사용하여 grp_no=2를 초기화 후 재등록한다.

    Returns:
        0J REG 페이로드 dict.
    """
    return {
        "trnm":    "REG",
        "grp_no":  "2",
        "refresh": "0",
        "data":    [{"item": ["001", "101"], "type": ["0J"]}],
    }


def build_account_reg_payload() -> dict:
    """계좌 실시간(주문체결 00, 잔고 04) REG 페이로드를 생성한다.

    키움 공식 예시대로 item은 빈 문자열로 전송한다.
    refresh="0"(기존 해지 후 등록)을 사용하여 grp_no=10을 초기화 후 재등록한다.

    Returns:
        계좌 REG 페이로드 dict.
    """
    return {
        "trnm":    "REG",
        "grp_no":  "10",
        "refresh": "0",
        "data":    [
            {"item": [""], "type": ["00"]},
            {"item": [""], "type": ["04"]},
        ],
    }


# ---------------------------------------------------------------------------
# 헬퍼: 명시적 UNREG 전송
# ---------------------------------------------------------------------------

async def _unreg_grp(grp_no: str) -> bool:
    """해당 grp_no 전체를 UNREG(해지)한다.

    grp_no="4"(0B 종목)인 경우 등록된 종목 코드를 data에 포함하여 전송.
    그 외 grp는 data:[]로 전송.

    Args:
        es: engine_service 모듈 참조 (상태·WS 전송 함수 접근)
        grp_no: 해지할 구독 그룹 번호 (예: "4", "2", "5", "10")

    Returns:
        True if 성공(또는 등록 항목 없음), False if 실패/타임아웃.
    """
    ws = state.connector_manager or state.kiwoom_connector
    if not ws or not ws.is_connected() or ws.broker_id != "kiwoom":
        return True

    # grp_no=4(0B): 등록된 종목 코드를 data에 포함
    if grp_no == "4":
        from backend.app.services.engine_ws import _ws_send_remove_fire_and_forget
        subscribed_codes = {cd for cd, entry in state.master_stocks_cache.items() if entry.get("_subscribed", False)}
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
                    await _ws_send_remove_fire_and_forget(payload)
                    logger.debug("[구독] grp_no=%s 청크 %d/%d 전송 완료 (%d종목)", grp_no, ci+1, nchunks, len(chunk))
                except Exception as e:
                    logger.warning("[구독] grp_no=%s 청크 %d/%d 오류: %s", grp_no, ci+1, nchunks, e, exc_info=True)
            for cd in subscribed_codes:
                if cd in state.master_stocks_cache:
                    state.master_stocks_cache[cd].pop("_subscribed", None)
            return True


async def subscribe_sector_stocks_0b() -> None:
    """필터 통과 종목 + 보유종목 0B REG — 첫 청크 refresh='0'(기존 해지 후 등록), 이후 refresh='1'(누적 등록).

    engine_service.py of _subscribe_sector_stocks_0b() 이동 버전.
    보유종목 우선 등록, 200개 한도 적용, 이미 구독된 종목 제외.

    Args:
        es: engine_service 모듈 참조
    """
    ws = state.connector_manager or state.kiwoom_connector
    if not ws or not ws.is_connected() or not state.login_ok:
        return

    _WS_0B_LIMIT = 200

    # ── 1) 보유종목 코드 수집 (최우선) ──
    from backend.app.services.engine_service import get_positions
    positions = await get_positions()
    pos_codes_raw = [
        str(s.get("stk_cd", "")).strip()
        for s in positions
        if int(s.get("qty", 0) or 0) > 0 and str(s.get("stk_cd", "")).strip()
    ]
    pos_codes: list[str] = list(dict.fromkeys(
        _format_kiwoom_reg_stk_cd(cd) for cd in pos_codes_raw if cd
    ))

    # ── 2) 필터 통과 종목 코드 수집 ──
    _raw_filter = {cd for cd, entry in state.master_stocks_cache.items() if entry.get("_filtered", False)}
    filtered_codes: list[str] = list(dict.fromkeys(
        _format_kiwoom_reg_stk_cd(cd) for cd in _raw_filter if cd
    ))

    # ── 3) 합산 + 200개 한도 적용 (보유종목 우선) ──
    pos_set = set(pos_codes)
    filtered_only = [cd for cd in filtered_codes if cd not in pos_set]

    total_raw = len(pos_codes) + len(filtered_only)
    if total_raw > _WS_0B_LIMIT:
        allowed_filtered = max(0, _WS_0B_LIMIT - len(pos_codes))
        logger.warning(
            "[구독][시세] 한도 초과 -- 보유 %d + 필터 %d = %d > %d, "
            "보유종목 우선 등록, 필터 통과 종목 %d개만 등록",
            len(pos_codes), len(filtered_only), total_raw,
            _WS_0B_LIMIT, allowed_filtered,
        )
        filtered_only = filtered_only[:allowed_filtered]

    # ── 4) 보유종목 별도 선행 REG ──
    pos_targets = [cd for cd in pos_codes if not state.master_stocks_cache.get(cd, {}).get("_subscribed")]
    if pos_targets:
        for cd in pos_targets:
            if cd in state.master_stocks_cache:
                state.master_stocks_cache[cd]["_subscribed"] = True

        ok = await ws.subscribe_stocks(pos_targets)
        if ok:
            logger.info("[구독][보유종목] 완료 -- %d종목 성공", len(pos_targets))
        else:
            for cd in pos_targets:
                if cd in state.master_stocks_cache:
                    entry = state.master_stocks_cache[cd]
                    entry.pop("_subscribed", None)
            logger.warning("[구독][보유종목] 실패 -- %d종목 롤백", len(pos_targets))

    # ── 5) 필터 통과 종목 누적 REG ──
    filter_targets = [cd for cd in filtered_only if not state.master_stocks_cache.get(cd, {}).get("_subscribed")]
    if not filter_targets:
        if not pos_targets:
            logger.debug("[구독][시세] 신규 종목 없음 -- 생략")
        return

    for cd in filter_targets:
        if cd in state.master_stocks_cache:
            state.master_stocks_cache[cd]["_subscribed"] = True

    ok = await ws.subscribe_stocks(filter_targets)
    if ok:
        logger.info("[구독][필터] 완료 -- %d종목 성공", len(filter_targets))
    else:
        for cd in filter_targets:
            if cd in state.master_stocks_cache:
                state.master_stocks_cache[cd].pop("_subscribed", None)
        logger.warning("[구독][필터] 실패 -- %d종목 롤백", len(filter_targets))


async def subscribe_index_realtime() -> None:
    """코스피·코스닥 업종지수(0J) 실시간 구독 등록.

    키움증권만 지원하므로 키움증권일 때만 전송.
    """
    ws = state.connector_manager or state.kiwoom_connector
    if not ws or not ws.is_connected() or ws.broker_id != "kiwoom":
        return

    payload = build_index_reg_payload()
    try:
        from backend.app.services.engine_ws import _ws_send_reg_unreg_and_wait_ack
        ok, _rc = await _ws_send_reg_unreg_and_wait_ack(payload)
        if ok:
            logger.info("[연결] 업종지수(0J) 구독 완료")
        else:
            logger.warning("[연결] 업종지수(0J) 구독 응답 시간 초과")
    except Exception as e:
        logger.warning("[연결] 업종지수(0J) 구독 실패: %s", e, exc_info=True)


async def subscribe_account_realtime() -> None:
    """계좌 단위 실시간 구독: 주문체결(00)·잔고(04) — refresh='0'으로 누적 등록.

    Args:
        es: engine_service 모듈 참조
    """
    ws = state.connector_manager or state.kiwoom_connector
    if not ws or not ws.is_connected() or ws.broker_id != "kiwoom":
        # LS증권은 소켓 연결 및 로그인 핸드셰이크 단계에서 계좌등록(tr_type="1")을 수행하므로 키움만 Grp 10 전송
        return

    s = state.integrated_system_settings_cache
    broker_nm = str(s.get("broker", "") or "").lower().strip()
    acnt = str(s.get(f"{broker_nm}_account_no", "") or "").strip()
    if not acnt:
        logger.warning("[연결] 계좌번호 미설정 -- 구독 요청은 빈값으로 전송")

    payload = build_account_reg_payload()
    try:
        from backend.app.services.engine_ws import _ws_send_reg_unreg_and_wait_ack
        ok, _rc = await _ws_send_reg_unreg_and_wait_ack(payload)
        if ok:
            state.ws_account_subscribed = True
            logger.info(
                "[연결] 계좌 구독 완료 -- 계좌설정=%s",
                "Y" if acnt else "N",
            )
        else:
            logger.warning("[연결] 계좌 구독 응답 시간 초과")
    except Exception as e:
        logger.warning("[연결] 계좌 구독 실패: %s", e, exc_info=True)


async def subscribe_positions_stocks_realtime() -> None:
    """보유 종목 0B REG — 이미 구독된 종목 제외, 누적 등록."""
    ws = state.connector_manager or state.kiwoom_connector
    if not ws or not ws.is_connected():
        logger.warning("[구독] 종목 구독 생략 -- 미연결")
        return
    if not state.login_ok:
        logger.warning("[구독] 종목 구독 생략 -- 로그인 전. 로그인 응답 후 재시도됨.")
        return

    from backend.app.services.engine_service import get_positions
    ordered: list[str] = []
    positions = await get_positions()
    for s in positions:
        cd = str(s.get("stk_cd", "")).strip()
        if cd and int(s.get("qty", 0)) > 0:
            ordered.append(cd)

    if not ordered:
        return

    norm_list = [_format_kiwoom_reg_stk_cd(cd) for cd in ordered]
    logger.info("[시작] 보유 REG 대상 %d종목: %s", len(norm_list), norm_list)

    # 이미 구독 중인 종목 제외
    new_0b = [cd for cd in norm_list if not state.master_stocks_cache.get(cd, {}).get("_subscribed")]
    if not new_0b:
        logger.debug("[구독][보유종목] 전체 이미 구독 중 -- 생략")
        return

    for cd in new_0b:
        if cd in state.master_stocks_cache:
            state.master_stocks_cache[cd]["_subscribed"] = True

    ok = await ws.subscribe_stocks(new_0b)
    if ok:
        logger.info("[구독][보유종목] 완료 -- %d종목 성공", len(new_0b))
    else:
        for cd in new_0b:
            if cd in state.master_stocks_cache:
                state.master_stocks_cache[cd].pop("_subscribed", None)
        logger.warning("[구독][보유종목] 실패 -- %d종목 롤백", len(new_0b))


# ---------------------------------------------------------------------------
# 재연결 후 구독 복원
# ---------------------------------------------------------------------------

async def restore_subscriptions_after_reconnect(broker_id: str) -> None:
    """재연결 성공 후 기존 구독 종목을 복원한다.

    state.master_stocks_cache의 "_subscribed" 키를 기준으로 0B REG를 재전송한다.
    지수(0J)와 계좌(00/04) 구독도 함께 복원한다.

    Args:
        es: engine_service 모듈 참조
        broker_id: 재연결된 증권사 ID
    """
    if not state.login_ok or False:
        logger.debug("[재연결] %s 로그인 전 — 구독 복원 생략 (LOGIN 후 파이프라인이 처리)", broker_id.upper())
        return

    ws = state.connector_manager or state.kiwoom_connector
    if not ws or not ws.is_connected():
        logger.warning("[재연결] %s 구독 복원 생략 — 미연결", broker_id.upper())
        return

    subscribed = {cd for cd, entry in state.master_stocks_cache.items() if entry.get("_subscribed", False)}
    if subscribed:
        # 재연결 시 서버 측 구독이 초기화됐으므로 "_subscribed" 키를 제거하고 재등록
        for cd in subscribed:
            if cd in state.master_stocks_cache:
                state.master_stocks_cache[cd].pop("_subscribed", None)

        targets_list = list(subscribed)
        for cd in targets_list:
            if cd in state.master_stocks_cache:
                state.master_stocks_cache[cd]["_subscribed"] = True
        
        ok = await ws.subscribe_stocks(targets_list)
        if ok:
            logger.info("[재연결] %s 구독 복원 완료 — %d종목", broker_id.upper(), len(targets_list))
        else:
            for cd in targets_list:
                if cd in state.master_stocks_cache:
                    state.master_stocks_cache[cd].pop("_subscribed", None)
            logger.warning("[재연결] %s 구독 복원 실패", broker_id.upper())

    # 데이터(0J) 복원
    try:
        await subscribe_index_realtime()
        logger.info("[연결] %s 데이터(0J) 구독 복원 완료", broker_id.upper())
    except Exception as e:
        logger.warning("[재연결] %s 데이터 구독 복원 실패: %s", broker_id.upper(), e, exc_info=True)

    # 계좌(00/04) 복원
    try:
        await subscribe_account_realtime()
        logger.info("[연결] %s 계좌 구독 복원 완료", broker_id.upper())
    except Exception as e:
        logger.warning("[재연결] %s 계좌 구독 복원 실패: %s", broker_id.upper(), e, exc_info=True)
