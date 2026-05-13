# -*- coding: utf-8 -*-
"""
키움 WebSocket REG/UNREG 구독 관리 — 순수 함수 + async 구독 함수.

engine_service.py에서 분리된 REG 구독 로직.
"""
from __future__ import annotations

import logging
import math
from types import ModuleType

from app.services.engine_symbol_utils import (
    _format_kiwoom_reg_stk_cd,
    get_ws_subscribe_code,
)

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

async def _unreg_grp(es: ModuleType, grp_no: str) -> bool:
    """해당 grp_no 전체를 UNREG(해지)한다.

    grp_no="4"(0B 종목)인 경우 등록된 종목 코드를 data에 포함하여 전송.
    그 외 grp는 data:[]로 전송.

    Args:
        es: engine_service 모듈 참조 (상태·WS 전송 함수 접근)
        grp_no: 해지할 구독 그룹 번호 (예: "4", "2", "5", "10")

    Returns:
        True if 성공(또는 등록 항목 없음), False if 실패/타임아웃.
    """
    # grp_no=4(0B): 등록된 종목 코드를 data에 포함
    if grp_no == "4" and hasattr(es, "_subscribed_stocks") and es._subscribed_stocks:
        stock_list = [get_ws_subscribe_code(cd) for cd in list(es._subscribed_stocks)]
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
                await es._ws_send_remove_fire_and_forget(payload)
                logger.debug("[구독] grp_no=%s 청크 %d/%d 전송 완료 (%d종목)", grp_no, ci+1, nchunks, len(chunk))
            except Exception as e:
                logger.warning("[구독] grp_no=%s 청크 %d/%d 오류: %s", grp_no, ci+1, nchunks, e, exc_info=True)
        es._subscribed_stocks.clear()
        return True

    # 그 외 grp: 구독 중인 아이템을 data에 포함하여 REMOVE (빈 data 전송 시 305003 에러)
    data: list[dict] = []
    if grp_no == "5":
        # 업종 0U — 구독 폐지됨 (sector_mapping 기반 자체 집계로 전환)
        logger.debug("[구독] grp_no=5 생략 — 0U 구독 폐지됨")
        return True
    elif grp_no == "2":
        # 지수 0J (코스피 001, 코스닥 101)
        data = [{"item": ["001", "101"], "type": ["0J"]}]
    elif grp_no == "10":
        # 계좌 (주문체결 00, 잔고 04)
        data = [{"item": [""], "type": ["00", "04"]}]

    if not data:
        logger.debug("[구독] grp_no=%s 생략 — 구독 아이템 없음", grp_no)
        return True

    payload = {
        "trnm":    "REMOVE",
        "grp_no":  grp_no,
        "refresh": "0",
        "data":    data,
    }

    try:
        sent = await es._ws_send_remove_fire_and_forget(payload)
        if sent:
            logger.info("[구독] grp_no=%s 전송 완료", grp_no)
        else:
            logger.warning("[구독] grp_no=%s 전송 실패 — 연결 없음", grp_no)
            return False
        return True
    except Exception as e:
        logger.warning("[구독] grp_no=%s 오류: %s", grp_no, e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# async 구독 함수 5개
# ---------------------------------------------------------------------------

async def subscribe_sector_stocks_0b(es: ModuleType) -> None:
    """필터 통과 종목 + 보유종목 0B REG — 첫 청크 refresh='0'(기존 해지 후 등록), 이후 refresh='1'(누적 등록).

    engine_service.py의 _subscribe_sector_stocks_0b() 이동 버전.
    보유종목 우선 등록, 200개 한도 적용, 이미 구독된 종목 제외.

    Args:
        es: engine_service 모듈 참조
    """
    if not es._kiwoom_connector or not es._kiwoom_connector.is_connected() or not es._login_ok:
        return

    _WL_0B_CHUNK = 100
    _WS_0B_LIMIT = 200

    # ── 1) 보유종목 코드 수집 (최우선) ──
    pos_codes_raw = [
        str(s.get("stk_cd", "")).strip()
        for s in es._positions
        if int(s.get("qty", 0) or 0) > 0 and str(s.get("stk_cd", "")).strip()
    ]
    pos_codes: list[str] = list(dict.fromkeys(
        _format_kiwoom_reg_stk_cd(cd) for cd in pos_codes_raw if cd
    ))

    # ── 2) 필터 통과 종목 코드 수집 ──
    # _filtered_sector_codes가 None(필터 미설정)이면 _sector_stock_layout 전체 코드 사용
    _raw_filter = es._filtered_sector_codes
    if _raw_filter is None:
        _raw_filter = {v for t, v in es._sector_stock_layout if t == "code" and v}
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
    pos_targets = [cd for cd in pos_codes if cd not in es._subscribed_stocks]
    if pos_targets:
        for cd in pos_targets:
            es._subscribed_stocks.add(cd)
        pos_al = [get_ws_subscribe_code(cd) for cd in pos_targets]
        pos_payloads = build_0b_reg_payloads(pos_al, chunk_size=_WL_0B_CHUNK, reset_first=True)
        pos_ok = pos_fail = 0
        for ci, payload in enumerate(pos_payloads):
            chunk = pos_targets[ci * _WL_0B_CHUNK : (ci + 1) * _WL_0B_CHUNK]
            ok, _rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
            if ok and str(_rc) == "0":
                pos_ok += len(chunk)
                logger.debug(
                    "[구독][보유종목] 청크 %d/%d 응답 -- %d종목 (누적 성공 %d)",
                    ci + 1, len(pos_payloads), len(chunk), pos_ok,
                )
            else:
                pos_fail += len(chunk)
                for cd in chunk:
                    es._subscribed_stocks.discard(cd)
                logger.warning(
                    "[구독][보유종목] 청크 %d/%d 실패 (rc=%s) -- %d종목 롤백",
                    ci + 1, len(pos_payloads), _rc, len(chunk),
                )
        logger.info(
            "[구독][보유종목] 완료 -- %d종목 / 성공 %d / 실패 %d",
            len(pos_targets), pos_ok, pos_fail,
        )

    # ── 5) 필터 통과 종목 누적 REG ──
    filter_targets = [cd for cd in filtered_only if cd not in es._subscribed_stocks]
    if not filter_targets:
        if not pos_targets:
            logger.debug("[구독][시세] 신규 종목 없음 -- 생략")
        return

    for cd in filter_targets:
        es._subscribed_stocks.add(cd)
    filter_al = [get_ws_subscribe_code(cd) for cd in filter_targets]
    filter_payloads = build_0b_reg_payloads(filter_al, chunk_size=_WL_0B_CHUNK, reset_first=False)
    filter_ok = filter_fail = 0
    for ci, payload in enumerate(filter_payloads):
        chunk = filter_targets[ci * _WL_0B_CHUNK : (ci + 1) * _WL_0B_CHUNK]
        ok, _rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
        if ok and str(_rc) == "0":
            filter_ok += len(chunk)
            logger.debug(
                "[구독][필터] 청크 %d/%d 응답 -- %d종목 (누적 성공 %d)",
                ci + 1, len(filter_payloads), len(chunk), filter_ok,
            )
        else:
            filter_fail += len(chunk)
            for cd in chunk:
                es._subscribed_stocks.discard(cd)
            logger.warning(
                "[구독][필터] 청크 %d/%d 실패 (rc=%s) -- %d종목 롤백",
                ci + 1, len(filter_payloads), _rc, len(chunk),
            )
    logger.info(
        "[구독][필터] 완료 -- %d종목 / 성공 %d / 실패 %d",
        len(filter_targets), filter_ok, filter_fail,
    )


async def subscribe_index_realtime(es: ModuleType) -> None:
    """코스피(001)·코스닥(101) 업종지수 0J REG — refresh='0'으로 누적 등록.

    engine_service.py의 _subscribe_index_realtime() 이동 버전.
    0J는 09:00~15:30 전송, 이후 REST 폴링 또는 캐시로 대체.

    Args:
        es: engine_service 모듈 참조
    """
    if not es._kiwoom_connector or not es._kiwoom_connector.is_connected() or not es._login_ok:
        return

    from datetime import datetime, time as _time, timezone, timedelta
    _KST = timezone(timedelta(hours=9))
    _now = datetime.now(_KST).time()
    _market_open  = _time(9, 0)
    _market_close = _time(15, 35)
    if not (_market_open <= _now <= _market_close):
        logger.debug("[데이터] 0J REG 생략 — 장외 시간 (REST 폴링으로 대체)")
        return

    payload = build_index_reg_payload()
    try:
        ok, _rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
        if ok:
            logger.info("[데이터] 코스피·코스닥 구독 완료 (09:00~15:30 전송, 이후 REST 폴링)")
        else:
            logger.warning("[데이터] 코스피·코스닥 구독 응답 시간 초과")
    except Exception as e:
        logger.warning("[데이터] 구독 실패: %s", e, exc_info=True)


async def subscribe_account_realtime(es: ModuleType) -> None:
    """계좌 단위 실시간 구독: 주문체결(00)·잔고(04) — refresh='0'으로 누적 등록.

    engine_service.py의 _subscribe_account_realtime() 이동 버전.
    키움 공식 예시대로 item은 빈 문자열로 전송.

    Args:
        es: engine_service 모듈 참조
    """
    if not es._kiwoom_connector or not es._kiwoom_connector.is_connected():
        logger.warning("[연결] 계좌 구독 생략 -- 미연결")
        return

    s = es._settings_cache or {}
    acnt = str(s.get("kiwoom_account_no", "") or "").strip()
    if not acnt:
        logger.warning("[연결] 계좌번호 미설정 -- 구독 요청은 빈값으로 전송")

    payload = build_account_reg_payload()
    try:
        ok, _rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
        if ok:
            es._ws_account_subscribed = True
            logger.info(
                "[연결] 계좌 구독 완료 -- 계좌설정=%s",
                "Y" if acnt else "N",
            )
        else:
            logger.warning("[연결] 계좌 구독 응답 시간 초과")
    except Exception as e:
        logger.warning("[연결] 계좌 구독 실패: %s", e, exc_info=True)


async def subscribe_positions_stocks_realtime(es: ModuleType) -> None:
    """보유 종목 0B REG — 이미 구독된 종목 제외, refresh='0'으로 누적 등록.

    engine_service.py의 _subscribe_positions_stocks_realtime() 이동 버전.
    보유종목 중 미구독 종목만 grp_no=4에 추가 등록.

    Args:
        es: engine_service 모듈 참조
    """
    if not es._kiwoom_connector or not es._kiwoom_connector.is_connected():
        logger.warning("[구독] 종목 구독 생략 -- 미연결")
        return
    if not es._login_ok:
        logger.warning("[구독] 종목 구독 생략 -- 로그인 전. 로그인 응답 후 재시도됨.")
        return

    from app.services.engine_service import get_positions
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
    new_0b = [cd for cd in norm_list if cd not in es._subscribed_stocks]
    if not new_0b:
        logger.debug("[구독][보유종목] 전체 이미 구독 중 -- 생략")
        return

    _CHUNK = 100
    nchunks_0b = (len(new_0b) + _CHUNK - 1) // _CHUNK
    logger.debug("[구독][보유종목] %d종목 -> %d청크", len(new_0b), nchunks_0b)

    for cd in new_0b:
        es._subscribed_stocks.add(cd)

    # NXT 중복상장 여부에 따라 _AL / 순수6자리 자동 분기 후 build_0b_reg_payloads 사용
    # 기존 구독에 추가하는 것이므로 reset_first=False (모든 청크 refresh="1")
    payloads = build_0b_reg_payloads(
        [get_ws_subscribe_code(cd) for cd in new_0b],
        chunk_size=_CHUNK,
        reset_first=False,
    )

    ok_0b = fail_0b = 0
    for ci, payload in enumerate(payloads):
        chunk = new_0b[ci * _CHUNK : (ci + 1) * _CHUNK]
        ok, _rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
        if ok:
            ok_0b += len(chunk)
            logger.debug("[구독][보유종목] 청크 %d/%d 응답 -- %d종목", ci + 1, nchunks_0b, len(chunk))
        else:
            fail_0b += len(chunk)
            for cd in chunk:
                es._subscribed_stocks.discard(cd)
            logger.warning(
                "[구독][보유종목] 청크 %d/%d 응답 시간 초과 -- %d종목 롤백",
                ci + 1, nchunks_0b, len(chunk),
            )
    logger.info("[구독][보유종목] 완료 -- 성공 %d / 실패 %d", ok_0b, fail_0b)


# ---------------------------------------------------------------------------
# 재연결 후 구독 복원
# ---------------------------------------------------------------------------

async def restore_subscriptions_after_reconnect(es: ModuleType, broker_id: str) -> None:
    """재연결 성공 후 기존 구독 종목을 복원한다.

    _subscribed_stocks에 저장된 종목 목록을 기준으로 0B REG를 재전송한다.
    지수(0J)와 계좌(00/04) 구독도 함께 복원한다.

    Args:
        es: engine_service 모듈 참조
        broker_id: 재연결된 증권사 ID
    """
    if not getattr(es, "_login_ok", False):
        logger.debug("[재연결] %s 로그인 전 — 구독 복원 생략 (LOGIN 후 파이프라인이 처리)", broker_id.upper())
        return

    subscribed = set(getattr(es, "_subscribed_stocks", set()))
    if subscribed:
        # 재연결 시 서버 측 구독이 초기화됐으므로 _subscribed_stocks를 비우고 재등록
        es._subscribed_stocks.clear()
        targets_al = [get_ws_subscribe_code(cd) for cd in subscribed]
        payloads = build_0b_reg_payloads(targets_al, chunk_size=100, reset_first=True)
        _CHUNK = 100
        ok_total = fail_total = 0
        targets_list = list(subscribed)
        for ci, payload in enumerate(payloads):
            chunk_orig = targets_list[ci * _CHUNK : (ci + 1) * _CHUNK]
            ok, _rc = await es._ws_send_reg_unreg_and_wait_ack(payload)
            if ok and str(_rc) == "0":
                for cd in chunk_orig:
                    es._subscribed_stocks.add(cd)
                ok_total += len(chunk_orig)
            else:
                fail_total += len(chunk_orig)
                logger.warning("[재연결] %s 0B REG 청크 %d 실패 (rc=%s)", broker_id.upper(), ci + 1, _rc)
        logger.info(
            "[재연결] %s 구독 복원 완료 — 0B %d종목 ACK / %d종목 실패",
            broker_id.upper(), ok_total, fail_total,
        )

    # 데이터(0J) 복원
    try:
        await subscribe_index_realtime(es)
        logger.info("[연결] %s 데이터(0J) 구독 복원 완료", broker_id.upper())
    except Exception as e:
        logger.warning("[재연결] %s 데이터 구독 복원 실패: %s", broker_id.upper(), e, exc_info=True)

    # 계좌(00/04) 복원
    try:
        await subscribe_account_realtime(es)
        logger.info("[연결] %s 계좌 구독 복원 완료", broker_id.upper())
    except Exception as e:
        logger.warning("[재연결] %s 계좌 구독 복원 실패: %s", broker_id.upper(), e, exc_info=True)
