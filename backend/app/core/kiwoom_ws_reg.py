# -*- coding: utf-8 -*-
"""
키움 WebSocket REG/UNREG/REMOVE 페이로드 빌더 — 순수 함수.

키움 규격(grp_no/refresh/type)을 services 계층이 아닌 core 계층에 캡슐화 (P4/P23).
입력(종목코드 리스트) → 페이로드 dict 변환만 수행. 상태·I/O 의존 없음.

engine_ws_reg.py에서 분리됨 (COUPLING-S6 후속).
"""
from __future__ import annotations
import math


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
