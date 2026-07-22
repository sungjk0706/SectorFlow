# -*- coding: utf-8 -*-
"""
time_scheduler_on + KST 시각에 따른 자동매매 허용 여부 변화 감지.

장마감 후 확정 데이터 갱신:
- 5일 평균 거래대금 캐시 롤링 갱신
"""
from __future__ import annotations
import asyncio
import gc
from datetime import datetime, timezone, timedelta
import logging
from backend.app.services import engine_state
from backend.app.services.engine_lifecycle import schedule_engine_task
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))



# ── KRX 거래 시간대 (한국거래소 실제 스케줄) ────────────────────────────────
KRX_PRE_OPEN_NONE_START = (8,  0)    # 08:00 거래 없음(주문 불가) 시작
KRX_PRE_TIME_EXTERNAL   = (8,  30)   # 08:30 장전 시간외 시작 (전일 종가, 실시간 선착순)
KRX_PRE_AUCTION_NONE    = (8,  40)   # 08:40 거래 없음(동시호가 접수) 시작
KRX_OPENING_AUCTION     = (8,  50)   # 08:50 시가 동시호가 시작 (09:00 일괄 체결)
KRX_REGULAR_START       = (9,  0)    # 09:00 정규장 시작
KRX_REGULAR_END         = (15, 20)   # 15:20 정규장 종료 → 종가 동시호가
KRX_CLOSING_AUCTION_END = (15, 30)   # 15:30 종가 동시호가 종료 → 거래 없음(정산)
KRX_SETTLE_END          = (15, 40)   # 15:40 거래 없음(정산) 종료 → 장후 시간외
KRX_AFTER_HOURS_END     = (16, 0)    # 16:00 장후 시간외 종료 → 시간외 단일가매매 개시
KRX_SINGLE_PRICE_END    = (18, 0)    # 18:00 시간외 단일가매매 종료 → 거래 없음(장 마감)
KRX_CLOSE_NONE_END      = (20, 0)    # 20:00 거래 없음(장 마감) 종료 → 장마감

# ── NXT 거래 시간대 (넥스트레이드 실제 스케줄) ──────────────────────────────
NXT_PREMARKET_START   = (8,  0)    # 08:00 프리마켓 시작 (전일 종가 ±10%)
NXT_PREMARKET_END     = (8,  50)   # 08:50 프리마켓 종료 → 거래 없음(정규장 준비)
NXT_PREP_NONE_END     = (9,  0)    # 09:00 거래 없음(정규장 준비) 종료 → 메인마켓
NXT_MAINMARKET_END    = (15, 20)   # 15:20 메인마켓 조기 마감 → 조기 마감
NXT_EARLY_CLOSE_END   = (15, 30)   # 15:30 조기 마감 종료 → 단일가 매매
NXT_SINGLE_PRICE_END  = (15, 40)   # 15:40 단일가 매매 종료(일괄 체결) → 애프터마켓
NXT_AFTERMARKET_START = (15, 40)   # 15:40 애프터마켓 시작 (당일 종가 ±10%)
NXT_AFTERMARKET_END   = (20, 0)    # 20:00 애프터마켓 종료 → 장마감

# ── 카운트다운 임계 시각 (거래소 규정 — 사용자 조정 불가, 코드 상수 P10/P24) ──
# JIF에 10분전 코드 없는 구간(KRX 장마감, NXT 프리마켓/에프터마켓 장마감)은
# _TIMETABLE 보조 엔트리만 담당 — JIF 매핑 테이블(engine_ws_dispatch.py)과 중복 없음.
# KRX 정규장 장마감 카운트다운 임계 (→ 15:20, 종가동시호가 개시)
KRX_CLOSE_COUNTDOWN_10M = (15, 10)       # 15:10 장마감 10분전 (보조 전용 — JIF 10분전 코드 없음)
KRX_CLOSE_COUNTDOWN_5M  = (15, 15)       # 15:15 장마감 5분전
KRX_CLOSE_COUNTDOWN_1M  = (15, 19)       # 15:19 장마감 1분전
KRX_CLOSE_COUNTDOWN_10S = (15, 19, 50)   # 15:19:50 장마감 10초전
# KRX 정규장 장개시 카운트다운 임계 (→ 09:00)
KRX_OPEN_COUNTDOWN_10M = (8, 50)         # 08:50 장개시 10분전
KRX_OPEN_COUNTDOWN_5M  = (8, 55)         # 08:55 장개시 5분전
KRX_OPEN_COUNTDOWN_1M  = (8, 59)         # 08:59 장개시 1분전
KRX_OPEN_COUNTDOWN_10S = (8, 59, 50)     # 08:59:50 장개시 10초전
# NXT 프리마켓 장마감 카운트다운 임계 (→ 08:50, 5분전이 최대)
NXT_PRE_CLOSE_COUNTDOWN_5M  = (8, 45)    # 08:45 프리마켓 장마감 5분전
NXT_PRE_CLOSE_COUNTDOWN_1M  = (8, 49)    # 08:49 프리마켓 장마감 1분전
NXT_PRE_CLOSE_COUNTDOWN_10S = (8, 49, 50)  # 08:49:50 프리마켓 장마감 10초전
# NXT 프리마켓 장개시 카운트다운 임계 (→ 08:00)
NXT_PRE_OPEN_COUNTDOWN_10M  = (7, 50)    # 07:50 프리마켓 장개시 10분전
NXT_PRE_OPEN_COUNTDOWN_5M   = (7, 55)    # 07:55 프리마켓 장개시 5분전
NXT_PRE_OPEN_COUNTDOWN_1M   = (7, 59)    # 07:59 프리마켓 장개시 1분전
NXT_PRE_OPEN_COUNTDOWN_10S  = (7, 59, 50)  # 07:59:50 프리마켓 장개시 10초전
# NXT 에프터마켓 장개시 카운트다운 임계 (→ 15:40)
NXT_AFT_OPEN_COUNTDOWN_10M  = (15, 30)   # 15:30 에프터마켓 장개시 10분전
NXT_AFT_OPEN_COUNTDOWN_5M   = (15, 35)   # 15:35 에프터마켓 장개시 5분전
NXT_AFT_OPEN_COUNTDOWN_1M   = (15, 39)   # 15:39 에프터마켓 장개시 1분전
NXT_AFT_OPEN_COUNTDOWN_10S  = (15, 39, 50)  # 15:39:50 에프터마켓 장개시 10초전
# NXT 에프터마켓 장마감 카운트다운 임계 (→ 20:00, 5분전이 최대)
NXT_AFT_CLOSE_COUNTDOWN_5M  = (19, 55)   # 19:55 에프터마켓 장마감 5분전
NXT_AFT_CLOSE_COUNTDOWN_1M  = (19, 59)   # 19:59 에프터마켓 장마감 1분전
NXT_AFT_CLOSE_COUNTDOWN_10S = (19, 59, 50)  # 19:59:50 에프터마켓 장마감 10초전

# ── 사전 트리거 시각 (장 시작 전 사전 준비 — 안 D 4단계) ──────────────────────
REALTIME_FIELDS_RESET_TIME = (7, 58)   # 07:58 실시간 필드 초기화 (WS 구독 1분 전)
WS_SUBSCRIBE_PRESTART_TIME = (7, 59)   # 07:59 WS 구독 사전 시작 (NXT 프리마켓 1분 전)
KRX_PRE_SUBSCRIBE_TIME    = (8, 59)   # 08:59 KRX 사전 구독 (정규장 1분 전)
NXT_MAINMARKET_START_SECOND = 30       # 09:00:30 NXT 메인마켓 시작 (초 단위 예외)
NXT_MAINMARKET_START = (NXT_PREP_NONE_END[0], NXT_PREP_NONE_END[1], NXT_MAINMARKET_START_SECOND)  # 09:00:30 — 타임테이블 엔트리용 3-tuple (P10 SSOT 파생)


def is_nxt_premarket_window() -> bool:
    """현재 장 상태가 NXT 프리마켓 구간인지 판단.

    SSOT: engine_state.state.market_phase에서 읽어 판단.
    market_phase는 시간 기반 스케줄러 + JIF 경계 이벤트가 갱신하므로 빈 문자열이면 안 됨.
    거래일 판별은 calc_timebased_market_phase()에서 이미 수행되어 market_phase에 반영됨.
    """
    mp = engine_state.state.market_phase
    nxt = mp.get("nxt", "")
    if not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: nxt=%r — 시간 기반 초기화 누락 가능", nxt)
        return False
    return nxt == "프리마켓"


def is_nxt_aftermarket_window() -> bool:
    """현재 장 상태가 NXT 애프터마켓 구간인지 판단.

    SSOT: engine_state.state.market_phase에서 읽어 판단.
    market_phase는 시간 기반 스케줄러 + JIF 경계 이벤트가 갱신하므로 빈 문자열이면 안 됨.
    거래일 판별은 calc_timebased_market_phase()에서 이미 수행되어 market_phase에 반영됨
    (기존 시간 기반 구현의 거래일 체크 누락이 자동 해결됨).
    """
    mp = engine_state.state.market_phase
    nxt = mp.get("nxt", "")
    if not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: nxt=%r — 시간 기반 초기화 누락 가능", nxt)
        return False
    return nxt == "애프터마켓"


def calc_timebased_market_phase() -> dict:
    """현재 KST 시각 기반으로 KRX/NXT 장 상태를 산정하여 반환.

    market_phase의 SSOT로 사용되며, 거래일 판별 포함.
    반환: {"krx": str, "nxt": str}

    시간대별 상태 정의 (한국거래소/넥스트레이드 실제 스케줄):
      KRX:
        00:00~08:00  장개시전
        08:00~08:30  장전 대기 (거래 없음, 주문 불가)
        08:30~08:40  장전 시간외 (전일 종가, 실시간 선착순)
        08:40~08:50  동시호가 접수 (거래 없음)
        08:50~09:00  시가 동시호가 (09:00 일괄 체결)
        09:00~15:20  정규장 (실시간 매매, ±30%)
        15:20~15:30  종가 동시호가 (15:30 일괄 체결)
        15:30~15:40  체결 정산 (거래 없음)
        15:40~16:00  장후 시간외 (당일 종가, 실시간 선착순)
        16:00~18:00  시간외 종가매매 종료 + 시간외 단일가매매 개시 (10분 단위 체결, ±10%)
        18:00~20:00  장 종료 (거래 없음)
        20:00~24:00  장마감
      NXT:
        00:00~08:00  장개시전
        08:00~08:50  프리마켓 (전일 종가 ±10%)
        08:50~09:00  정규장 준비 (거래 없음)
        09:00~15:20  메인마켓 (실시간 매매, ±30%)
        15:20~15:30  조기 마감
        15:30~15:40  단일가 매매 (15:40 일괄 체결)
        15:40~20:00  애프터마켓 (당일 종가 ±10%)
        20:00~24:00  장마감
    """
    from backend.app.core.trading_calendar import is_trading_day

    now = _kst_now()
    today = now.date()
    t = now.hour * 60 + now.minute

    if today.weekday() >= 5 or not is_trading_day(today):
        return {"krx": "휴장일", "nxt": "휴장일"}

    def _m(hm: tuple[int, int]) -> int:
        return hm[0] * 60 + hm[1]

    # ── KRX ──
    if t < _m(KRX_PRE_OPEN_NONE_START):
        krx = "장개시전"
    elif t < _m(KRX_PRE_TIME_EXTERNAL):
        krx = "장전 대기"
    elif t < _m(KRX_PRE_AUCTION_NONE):
        krx = "장전 시간외"
    elif t < _m(KRX_OPENING_AUCTION):
        krx = "동시호가 접수"
    elif t < _m(KRX_REGULAR_START):
        krx = "시가 동시호가"
    elif t < _m(KRX_REGULAR_END):
        krx = "정규장"
    elif t < _m(KRX_CLOSING_AUCTION_END):
        krx = "종가 동시호가"
    elif t < _m(KRX_SETTLE_END):
        krx = "체결 정산"
    elif t < _m(KRX_AFTER_HOURS_END):
        krx = "장후 시간외"
    elif t < _m(KRX_SINGLE_PRICE_END):
        krx = "시간외 종가매매 종료 + 시간외 단일가매매 개시"
    elif t < _m(KRX_CLOSE_NONE_END):
        krx = "장 종료"
    else:
        krx = "장마감"

    # ── NXT ──
    if t < _m(NXT_PREMARKET_START):
        nxt = "장개시전"
    elif t < _m(NXT_PREMARKET_END):
        nxt = "프리마켓"
    elif t < _m(NXT_PREP_NONE_END):
        nxt = "정규장 준비"
    elif t == _m(NXT_PREP_NONE_END) and now.second < NXT_MAINMARKET_START_SECOND:
        nxt = "정규장 준비"           # 09:00:00~09:00:29 — 정규장 준비 유지 (초 단위 예외)
    elif t < _m(NXT_MAINMARKET_END):
        nxt = "메인마켓"              # 09:00:30~ — 메인마켓
    elif t < _m(NXT_EARLY_CLOSE_END):
        nxt = "조기 마감"
    elif t < _m(NXT_SINGLE_PRICE_END):
        nxt = "단일가 매매"
    elif t < _m(NXT_AFTERMARKET_END):
        nxt = "애프터마켓"
    else:
        nxt = "장마감"

    return {"krx": krx, "nxt": nxt}


# ── 카운트다운 SSOT (P10) ─────────────────────────────────────────────────────
# 각 페이즈의 다음 전환 시각 매핑 — 기존 시간표 상수 재사용 (새 시각 하드코딩 금지).
# 10분 이내 남은 시간만 카운트다운 표시 (COUNTDOWN_THRESHOLD_MIN).
COUNTDOWN_THRESHOLD_MIN = 10

_KRX_COUNTDOWN_MAP: dict[str, tuple[tuple[int, int], str]] = {
    "시가 동시호가": (KRX_REGULAR_START, "정규장 장개시"),   # → 09:00
    "정규장":       (KRX_REGULAR_END,   "정규장 장마감"),   # → 15:20
    "종가 동시호가": (KRX_CLOSING_AUCTION_END, "종가 동시호가 종료"),  # → 15:30
    "장후 시간외": (KRX_AFTER_HOURS_END, "장후 시간외 종료"),  # → 16:00
    "시간외 종가매매 종료 + 시간외 단일가매매 개시": (KRX_SINGLE_PRICE_END, "시간외 단일가매매 종료"),  # → 18:00
}

_NXT_COUNTDOWN_MAP: dict[str, tuple[tuple[int, int], str]] = {
    "장개시전":        (NXT_PREMARKET_START,  "프리마켓 장개시"),    # → 08:00
    "프리마켓":        (NXT_PREMARKET_END,    "프리마켓 장마감"),    # → 08:50
    "정규장 준비":     (NXT_PREP_NONE_END,    "메인마켓 장개시"),    # → 09:00
    "메인마켓":        (NXT_MAINMARKET_END,   "메인마켓 장마감"),    # → 15:20
    "단일가 매매":     (NXT_SINGLE_PRICE_END, "에프터마켓 장개시"),  # → 15:40
    "애프터마켓":      (NXT_AFTERMARKET_END,  "에프터마켓 장마감"),  # → 20:00
}


def calc_countdown(market: str, phase: str) -> dict | None:
    """현재 페이즈의 다음 전환까지 남은 시간 계산 (KST 기준, 순수 함수).

    market: "krx" | "nxt"
    phase: 현재 페이즈명 (calc_timebased_market_phase() 결과와 동일)
    반환: {"label": str, "remaining_sec": int} | None
      - 10분 이내 남은 시간만 반환 (COUNTDOWN_THRESHOLD_MIN)
      - 카운트다운 대상 페이즈가 아니면 None
      - remaining_sec <= 0이면 None (이미 전환 시각 지난 경우, P20 폴백 금지)

    P10: target 시각은 기존 시간표 상수 참조 — 새 하드코딩 없음.
    P16: get_market_phase()를 통해 기존 10초 브로드캐스트 경로에 편입.
    P24: 순수 함수, 부작용 없음.
    """
    cmap = _KRX_COUNTDOWN_MAP if market == "krx" else _NXT_COUNTDOWN_MAP
    entry = cmap.get(phase)
    if not entry:
        return None
    target_hm, label = entry
    now = _kst_now()
    kst_total_sec = (now.hour * 60 + now.minute) * 60 + now.second
    target_sec = (target_hm[0] * 60 + target_hm[1]) * 60
    remaining_sec = target_sec - kst_total_sec
    if remaining_sec <= 0:
        return None
    if remaining_sec > COUNTDOWN_THRESHOLD_MIN * 60:
        return None
    return {"label": label, "remaining_sec": remaining_sec}


def _get_active_override(market: str) -> dict | None:
    """JIF 카운트다운 override 활성 여부 반환 (만료 시 None — P20 폴백 금지).

    market: "krx" | "nxt"
    반환: {label, remaining_sec, expires_at} | None
      - override 미설정 시 None
      - override 만료(expires_at 경과) 시 None (만료된 값 사용 금지 — P20)
    P10 SSOT: engine_state.state.{krx,nxt}_countdown_override 단일 소스.
    P24 단순성: 순수 함수, 50줄 이하.
    """
    override = (
        engine_state.state.krx_countdown_override if market == "krx"
        else engine_state.state.nxt_countdown_override
    )
    if override is None:
        return None
    expires_at = override.get("expires_at")
    if expires_at is None or _kst_now() >= expires_at:
        # 만료 — None 반환 (P20: 만료된 값 사용 금지)
        return None
    return override


KRX_INACTIVE_PHASES = frozenset({
    "장개시전", "장전 대기", "장전 시간외", "동시호가 접수", "시가 동시호가",
    "종가 동시호가", "체결 정산", "장후 시간외", "시간외 종가매매 종료 + 시간외 단일가매매 개시", "장 종료",
    "장마감", "휴장일",
})

NXT_ACTIVE_PHASES = frozenset({
    "프리마켓", "정규장 준비", "메인마켓",
    "단일가 매매", "애프터마켓",
})


def _is_pre_subscribe_window() -> bool:
    """07:59~08:00 사전 구독 구간 여부 (시간 기반 — 재시작 대응, P16 살아있는 경로).

    WS_SUBSCRIBE_PRESTART_TIME(07:59) ~ NXT_PREMARKET_START(08:00) 사이.
    시간 기반 판정이므로 엔진 재시작 시에도 사전 구간이 누락되지 않음
    (플래그 기반 판정은 메모리 상주 → 재시작 시 False → 사전 구간 누락).
    휴장일은 calc_timebased_market_phase()가 "휴장일"로 산정하므로 자동 차단.
    P10 SSOT: 기존 시간 상수(WS_SUBSCRIBE_PRESTART_TIME, NXT_PREMARKET_START) 재사용.
    """
    now = _kst_now()
    t = now.hour * 60 + now.minute
    prestart_t = WS_SUBSCRIBE_PRESTART_TIME[0] * 60 + WS_SUBSCRIBE_PRESTART_TIME[1]
    market_t = NXT_PREMARKET_START[0] * 60 + NXT_PREMARKET_START[1]
    if not (prestart_t <= t < market_t):
        return False
    mp = engine_state.state.market_phase
    if mp.get("nxt") == "휴장일" or mp.get("krx") == "휴장일":
        return False
    return True


def is_nxt_only_window() -> bool:
    """현재 장 상태가 NXT-only 거래 구간인지 판단 (KRX 비활성 + NXT 활성).

    SSOT: engine_state.state.market_phase에서 읽어 판단.
    market_phase는 시간 기반 스케줄러가 갱신하므로 빈 문자열이면 안 됨.
    사전 구독 구간(07:59~08:00) 시간 기반 판정 추가 — NXT-only 구독 (KRX 단독 종목 제외).
    """
    mp = engine_state.state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: krx=%r, nxt=%r — 시간 기반 초기화 누락 가능", krx, nxt)
        return False
    if krx in KRX_INACTIVE_PHASES and nxt in NXT_ACTIVE_PHASES:
        return True
    # 사전 구독 구간(07:59~08:00) — KRX 비활성 + 시간 기반 → NXT-only 구독
    if _is_pre_subscribe_window() and krx in KRX_INACTIVE_PHASES:
        return True
    return False


def get_nxt_trde_tp(base_trde_tp: str = "3") -> str:
    """
    현재 장 상태에 맞는 NXT trde_tp 반환.
    - 프리마켓: 'P'
    - 애프터마켓: 'U'
    - 그 외(메인마켓/정규장 준비/조기 마감/단일가 매매): base_trde_tp
      (실시간 매매 불가 구간 — 자동매매 게이트에서 차단 전제)

    SSOT: engine_state.state.market_phase 기반으로 is_nxt_premarket_window/is_nxt_aftermarket_window 경유 판단.
    """
    if is_nxt_premarket_window():
        return "P"
    if is_nxt_aftermarket_window():
        return "U"
    return base_trde_tp


# ── 체결 불가 시간대 주문 게이트 (Order Time Guard) ────────────────────────────
# 페이즈 기반 판별 — 별도 버퍼 없이 engine_state.state.market_phase로 즉시 차단 여부 결정 (P24 단순화).


def is_order_blocked_by_time(stk_cd: str) -> bool:
    """체결 불가 시간대 주문 차단 판별 (매수·매도 공통).

    SSOT: engine_state.state.market_phase 기반. 기존 is_nxt_only_window() 패턴과 동일 구조.
    KRX 비활성 + NXT 활성 시 is_nxt_enabled(stk_cd)로 종목별 분기
      — NXT 종목은 허용, KRX 단독 종목만 차단.
    빈 문자열 phase 시 False 반환 + 에러 로그 (P20 폴백 금지).
    휴장일 시 False 반환 — 장 안 열리므로 주문 자체 발생 안 함 (P23 일관성,
    get_order_time_block_status()와 동일 패턴).
    """
    mp = engine_state.state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: krx=%r, nxt=%r — 시간 기반 초기화 누락 가능", krx, nxt)
        return False  # P20 폴백 금지 — 빈 문자열은 차단하지 않고 에러 로그

    # 휴장일 조기 반환 — 장 안 열리므로 주문 자체 발생 안 함 (P23 일관성).
    if krx == "휴장일" or nxt == "휴장일":
        return False

    # 본 판별 — 기존 is_nxt_only_window()와 동일 구조
    if krx in KRX_INACTIVE_PHASES:
        if nxt in NXT_ACTIVE_PHASES:
            from backend.app.services.engine_symbol_utils import is_nxt_enabled
            return not is_nxt_enabled(stk_cd)  # NXT 종목 허용, KRX 단독 종목 차단
        return True  # 양쪽 비활성 — 전부 차단
    return False  # KRX 활성 — 허용


def get_order_time_block_status() -> tuple[bool, str]:
    """체결 불가 시간대 주문 차단 상태 (페이즈 기반, 종목 구분 없음).

    WS 브로드캐스트용 — 헤더 칩 표시에 사용 (P21 사용자 투명성).
    is_order_blocked_by_time(stk_cd)와 동일한 페이즈 판별을 사용하되
    종목별 is_nxt_enabled 분기 없이 페이즈 수준에서 차단 여부와 사유 반환.

    반환 (blocked, reason):
      - (False, ""): KRX 활성 — 전부 허용
      - (True, "KRX 단독 종목 차단 · NXT 가능"): KRX 비활성 + NXT 활성 — KRX 단독 종목 차단, NXT 종목 허용
      - (True, "KRX·NXT 모두 주문 불가"): 양쪽 비활성 — 전부 차단
      - (False, ""): 빈 문자열 phase — 에러 로그 (P20 폴백 금지)
      - (False, ""): 휴장일 — 장 안 열리므로 칩 표시 불필요 (P21 사용자 투명성)
    """
    mp = engine_state.state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: krx=%r, nxt=%r — 시간 기반 초기화 누락 가능", krx, nxt)
        return (False, "")  # P20 폴백 금지 — 빈 문자열은 차단하지 않고 에러 로그

    # 휴장일 조기 반환 — 장 안 열리므로 주문 차단 칩 불필요 (P21 사용자 투명성).
    # _is_pre_subscribe_window() L255-256과 동일 패턴 (P23 일관성).
    if krx == "휴장일" or nxt == "휴장일":
        return (False, "")

    # 본 판별 — 페이즈 수준 (종목별 분기 없음)
    if krx in KRX_INACTIVE_PHASES:
        if nxt in NXT_ACTIVE_PHASES:
            return (True, "KRX 단독 종목 차단 · NXT 가능")
        return (True, "KRX·NXT 모두 주문 불가")
    return (False, "")


def get_market_phase() -> dict:
    """현재 KRX/NXT 장 상태 반환 (순수 읽기).

    SSOT: engine_state.state.market_phase에서 읽어 복사본 반환.
    market_phase는 시간 기반 스케줄러가 갱신하므로 빈 문자열이면 안 됨.
    """
    mp = engine_state.state.market_phase
    krx = mp.get("krx", "")
    nxt = mp.get("nxt", "")
    if not krx or not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: krx=%r, nxt=%r — 시간 기반 초기화 누락 가능", krx, nxt)
    phase: dict = {"krx": krx, "nxt": nxt}
    if mp.get("krx_alert"):
        phase["krx_alert"] = mp["krx_alert"]
    # NXT-only 구간 플래그 — 프론트엔드가 중복 상수 없이 백엔드 SSOT를 사용하도록 파생 (P10/P22)
    phase["is_nxt_only"] = is_nxt_only_window()
    # 카운트다운 — JIF override 우선 (P10 SSOT — JIF 1순위), 없으면 calc_countdown() 보조.
    # 10초 주기 브로드캐스트 + JIF 수신 시 즉시 브로드캐스트로 자동 갱신 (P16 살아있는 경로).
    krx_override = _get_active_override("krx")
    nxt_override = _get_active_override("nxt")
    phase["krx_countdown"] = krx_override if krx_override is not None else calc_countdown("krx", krx)
    phase["nxt_countdown"] = nxt_override if nxt_override is not None else calc_countdown("nxt", nxt)
    return phase


async def is_heavy_operation_allowed(now: datetime | None = None) -> bool:
    """
    대량 다운로드 및 무거운 배치 연산 허용 여부 반환.
    - 실시간 연결 구간(market_phase 활성): 차단 (False)
    - 그 외 시간: 허용 (True)
    """
    if now is None:
        now = _kst_now()
    
    # 실시간 연결 구간이면 무거운 작업 차단
    if await is_ws_subscribe_window():
        return False
    
    # 실시간 연결 구간 외면 허용
    return True


def _kst_now() -> datetime:
    return datetime.now(KST)


def _parse_hm(hm_str: str) -> tuple[int, int]:
    """'HH:MM' 문자열 -> (hour, minute). 파싱 실패 시 (0, 0)."""
    try:
        parts = str(hm_str or "").strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        logger.warning("[스케줄] 시간 파싱 실패 (시간 문자열=%r)", hm_str, exc_info=True)
        return 0, 0


async def is_ws_subscribe_window(settings: dict | None = None) -> bool:
    """
    현재 시각이 웹소켓 구독 허용 구간인지 판단.
    조건: market_phase의 NXT 페이즈가 활성 구간.
    구독 구간 = NXT_ACTIVE_PHASES (프리마켓 ~ 애프터마켓, 08:00~20:00).
    사전 구독 구간(07:59~08:00) 시간 기반 판정 추가 — 재시작 대응 (P16 살아있는 경로).
    주말/공휴일은 calc_timebased_market_phase()가 nxt="휴장일"로 산정하므로 자동 차단.
    settings 미전달 시 integrated_system_settings_cache에서 읽음.
    SSOT: engine_state.state.market_phase가 구독 구간 판정의 단일 기준 (P10).
    """
    if settings is None:
        settings = engine_state.state.integrated_system_settings_cache
    if not settings:
        raise RuntimeError("settings cache not initialized")

    mp = engine_state.state.market_phase
    nxt = mp.get("nxt", "")
    if not nxt:
        logger.error("[시스템] 장 상태 빈 문자열 감지: nxt=%r — 시간 기반 초기화 누락 가능", nxt)
        return False
    if nxt in NXT_ACTIVE_PHASES:
        return True
    # 사전 구독 구간(07:59~08:00) — 시간 기반 판정 (재시작 대응, P16)
    return _is_pre_subscribe_window()


async def is_edit_window_open(settings: dict | None = None) -> bool:
    """수정 허용 시간대 판단(업종 커스텀 등).
    허용: NOT is_ws_subscribe_window().
    WS 구독 구간 밖이면 편집 가능 (프론트 computeEditWindowOpenByTime과 동일 기준)."""
    if settings is None:
        settings = engine_state.state.integrated_system_settings_cache
    if not settings:
        raise RuntimeError("settings cache not initialized")
    return not await is_ws_subscribe_window(settings)


# ── call_later 기반 WS 구독 구간 타이머 ─────────────────────────────────────






async def _on_nxt_premarket_start() -> None:
    """08:00 NXT 프리마켓 진입 콜백 — 업종 종합점수 재계산.

    07:55(WS 구독 시작) 시점에는 market_phase가 장개시전/장개시전이므로
    is_nxt_only_window()가 False이고, KRX 단독 종목이 포함된 채 점수가 계산됨.
    08:00 NXT 경계 이벤트 수신 시 market_phase가 장전 대기/프리마켓으로 갱신되어
    is_nxt_only_window()가 True로 전환되므로, 재계산 시 KRX 단독 종목이 제외됨.
    구독 변경은 없음 (08:00에는 구독 해지/재구독 불필요 — 필터링만 적용).
    recompute_sector_summary_now() 내부에서 notify 3종이 이미 호출되므로 중복 호출을 제거한다.
    _broadcast_market_phase() 내 페이즈 변경 감지 시 자동 트리거된다 (수정 8 통합).
    """
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        if today.weekday() >= 5 or not is_trading_day(today):
            return
        logger.info("[작업실행] NXT 프리마켓 처리 — 업종 재계산 시작 (KRX 단독 종목 제외)")
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        await recompute_sector_summary_now()
        logger.info("[작업실행] NXT 프리마켓 처리 — 업종 재계산 완료")
    except Exception as e:
        logger.warning("[작업실행] NXT 프리마켓 처리 콜백 오류: %s", e, exc_info=True)


async def _on_krx_market_open() -> None:
    """09:00 KRX 정규장 진입 콜백 — 업종 종합점수 재계산.

    NXT 프리마켓(08:00~08:50)에는 NXT-enabled 종목만 업종 점수에 포함되었으므로,
    09:00 KRX 정규장 진입 시 전체 종목을 포함하도록 재계산 필요.
    KRX 단독 종목 구독은 08:59 _on_krx_pre_subscribe()에서 수행하므로 여기서는 재계산만 담당.

    recompute_sector_summary_now() 내부에서 notify 3종이 이미 호출되므로 중복 호출을 제거한다.
    _broadcast_market_phase() 내 페이즈 변경 감지 시 자동 트리거된다 (수정 8 통합).
    """
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now()
        if today.weekday() >= 5 or not is_trading_day(today.date()):
            return
        logger.info("[작업실행] KRX 정규장 진입 — 업종 재계산 시작 (09:00)")
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        await recompute_sector_summary_now()
        logger.info("[작업실행] 업종 재계산 완료 (09:00 KRX 정규장)")
    except Exception as e:
        logger.warning("[작업실행] KRX 정규장 진입 업종 재계산 콜백 오류: %s", e, exc_info=True)


async def _on_krx_pre_subscribe() -> None:
    """08:59 KRX 사전 구독 콜백 — KRX 단독 종목 사전 구독 (재계산 없음).

    정규장(09:00) 1분 전에 KRX 단독 종목(nxt_enable=False) WS 구독을 미리 수행하여
    09:00 시가 동시호가 체결 시점부터 실시간 시세를 즉시 수신 (P16 살아있는 경로).
    재계산은 09:00 _on_krx_market_open()에서 수행하므로 여기서는 구독만 담당.
    날짜 기반 멱등성 가드(last_krx_pre_subscribe_date)로 중복 실행 방지.
    거래일 아닌 시 가드 미설정 — 다음 거래일에 실행 (기존 _on_realtime_fields_reset 패턴 준수).

    가짜 성공 방지 (P20 폴백 금지 · P22 정합성):
    구독 전후 _subscribed 카운트를 비교하여 실제 구독이 발생한 경우에만 가드를 설정.
    0건 구독(WS 미연결·필터 누락·이미 전량 구독 등) 시 가드 미설정 + 경고 로그 —
    실패 원인을 로그로 기록하여 사용자가 인지하고 근본 수정할 수 있도록 함.
    """
    try:
        today = _kst_now()
        today_str = today.strftime("%Y%m%d")
        if engine_state.state.last_krx_pre_subscribe_date == today_str:
            return  # 이미 오늘 실행됨 — 중복 방지
        from backend.app.core.trading_calendar import is_trading_day
        if today.weekday() >= 5 or not is_trading_day(today.date()):
            return
        logger.info("[작업실행] KRX 단독 종목 사전 구독 시작 (08:59)")
        from backend.app.services.engine_ws_reg import subscribe_sector_stocks_0b

        _cache = engine_state.state.master_stocks_cache
        before_count = sum(1 for e in _cache.values() if e.get("_subscribed"))

        await subscribe_sector_stocks_0b()

        after_count = sum(1 for e in _cache.values() if e.get("_subscribed"))
        if after_count > before_count:
            engine_state.state.last_krx_pre_subscribe_date = today_str
            logger.info(
                "[작업실행] KRX 단독 종목 사전 구독 완료 — 신규 %d종목 (구독 %d→%d)",
                after_count - before_count, before_count, after_count,
            )
        else:
            logger.warning(
                "[작업실행] KRX 사전 구독 0건 — 가짜 성공 방지: 가드 미설정 (WS 미연결·필터 누락·이미 전량 구독 등 원인 확인 필요)"
            )
    except Exception as e:
        logger.warning("[작업실행] KRX 사전 구독 콜백 오류: %s", e, exc_info=True)


async def _on_krx_closing_auction_start() -> None:
    """15:20 종가 동시호가 전환 콜백 — 업종 종합점수 재계산 + KRX 단독 종목 구독해지.

    KRX 정규장 종료(15:20) 시점에 KRX 단독 종목(nxt_enable=False) WS 구독 해지.
    시장가 주문만 사용하므로 종가 동시호가 구간(15:20~15:30) 체결이 불가하여 구독 유지 불필요.
    NXT-enabled 종목은 NXT 거래(20:00까지)가 가능하므로 구독 유지.
    recompute_sector_summary_now() 내부에서 notify 3종이 이미 호출되므로 중복 호출을 제거한다.
    _broadcast_market_phase() 내 페이즈 변경 감지 시 자동 트리거된다 (수정 8 통합).
    """
    try:
        from backend.app.core.trading_calendar import is_trading_day
        today = _kst_now().date()
        if today.weekday() >= 5 or not is_trading_day(today):
            return
        logger.info("[작업실행] KRX 단독 종목 구독 해지 시작 (15:20 — 종가 동시호가)")
        from backend.app.services.sector_data_provider import recompute_sector_summary_now
        await recompute_sector_summary_now()
        logger.info("[작업실행] 업종 재계산 완료 (15:20 종가 동시호가)")

        # KRX 단독 종목 장마감 구독해지
        if not engine_state.state.krx_remove_done:
            engine_state.state.krx_remove_done = True
            from backend.app.services.market_close_pipeline import remove_krx_only_stocks
            result = await remove_krx_only_stocks()
            if result.get("skipped"):
                engine_state.state.krx_remove_done = False
                logger.debug("[작업실행] KRX 단독 종목 구독 해지 생략 — 플래그 복원 (앱준비 후 재시도 가능)")
            else:
                logger.info("[작업실행] KRX 단독 종목 구독 해지 완료 — 해지 %d종목, 실패 %d종목 (15:20 — 종가 동시호가)", result.get("removed", 0), result.get("failed", 0))
    except Exception as e:
        engine_state.state.krx_remove_done = False
        logger.warning("[작업실행] KRX 단독 종목 구독 해지 콜백 오류: %s", e, exc_info=True)


def _fire_unified_confirmed_fetch() -> None:
    """장마감(market_phase 비활성 전환) 또는 부트스트랩 catch-up 시 확정 조회 트리거 함수.

    confirmed_done 플래그 체크 → 이미 완료면 스킵.
    fetch_unified_confirmed_data(es) 비동기 태스크 생성.
    성공 시 confirmed_done = True, 실패 시 confirmed_done = False로 복원.
    """
    try:
        if engine_state.state.confirmed_done:
            return
        engine_state.state.confirmed_done = True
        schedule_engine_task(_do_unified_confirmed_fetch(), context="통합 확정 조회")
    except Exception as e:
        logger.warning("[스케줄] 통합 확정 조회 시작 오류: %s", e, exc_info=True)


async def _do_unified_confirmed_fetch() -> None:
    """통합 확정 조회 비동기 헬퍼."""
    try:
        from backend.app.services.market_close_pipeline import fetch_unified_confirmed_data
        await fetch_unified_confirmed_data()
        engine_state.state.confirmed_done = True
        logger.info("[스케줄] 통합 확정 조회 완료")
    except Exception as e:
        engine_state.state.confirmed_done = False
        logger.warning("[스케줄] 통합 확정 조회 실패 — 플래그 복원: %s", e, exc_info=True)
        try:
            engine_state.state.confirmed_refresh_running_confirmed = False
            engine_state.state.confirmed_refresh_message = ""
        except Exception as _e:
            logger.warning("[시스템] 플래그 복원 실패: %s", _e, exc_info=True)


async def retry_pipeline_catchup_after_bootstrap() -> None:
    """부트스트랩 완료 후 미실행 파이프라인 catch-up 재시도.

    기동 시 WS/REST 미준비로 스킵된 작업을 부트스트랩 완료 후 재실행한다.
    
    데이터 무결성 및 단일 진실 공급원(Single Source of Truth) 원칙에 따라,
    단절 구간(market_phase 비활성) 기동 시 
    메모리에 로드된 DB 데이터의 유효 기한(date)을 엄격히 판별하여 누락된 확정 다운로드를 수행한다.
    """
    t = _kst_now().hour * 60 + _kst_now().minute

    _settings = engine_state.state.integrated_system_settings_cache

    # 마스터 캐시에서 데이터 유효기간(date) 추출
    _cached_date_str = ""
    if len(engine_state.state.master_stocks_cache) > 0:
        _first_stock = next(iter(engine_state.state.master_stocks_cache.values()))
        _cached_date_str = _first_stock.get("date", "")

    # 기준일 = 가장 최근 확정된 거래일 (소속 거래일의 직전 거래일).
    # 다운로드 파이프라인(execute_unified_rolling_and_save)과 수동 확인 API
    # (check_download_data_exists)가 모두 이 기준일로 date/dt를 저장하므로,
    # 기동 스킵 판단도 동일 기준일을 사용해야 함 (P10 SSOT).
    from backend.app.core.trading_calendar import (
        get_current_trading_day_str,
        get_previous_trading_day_str,
    )
    _latest_confirmed_day = get_previous_trading_day_str(get_current_trading_day_str())
    _cache_is_fresh = (_cached_date_str == _latest_confirmed_day)

    # ── 판단: 단절 구간 (market_phase 비활성) — is_ws_subscribe_window() 기반 (P10) ──
    in_ws_window = await is_ws_subscribe_window(_settings)

    if not in_ws_window:
        confirmed_dl_str = str(_settings["timetable.confirmed_download"])[:5]
        cdl_h, cdl_m = _parse_hm(confirmed_dl_str)
        confirmed_dl_minutes = cdl_h * 60 + cdl_m

        if t < confirmed_dl_minutes:
            logger.info(
                "[스케줄] 단절 구간 기동 — 확정 다운로드 시각(%s) 이전 — 타이머 대기 (캐시=%s, 최근 확정 거래일=%s)",
                confirmed_dl_str, _cached_date_str, _latest_confirmed_day
            )
            return

        if not _cache_is_fresh and not engine_state.state.confirmed_done:
            logger.info(
                "[스케줄] 단절 구간 기동 — 캐시 날짜(%s) ≠ 최근 확정 거래일(%s) → 확정 데이터 자동 다운로드 트리거",
                _cached_date_str or "없음", _latest_confirmed_day
            )
            _fire_unified_confirmed_fetch()
            return

        logger.info(
            "[스케줄] 단절 구간 기동 — 캐시(%s) = 최근 확정 거래일(%s) 확정 다운로드 시각 경과 (스킵)",
            _cached_date_str, _latest_confirmed_day
        )
        engine_state.state.confirmed_done = True
        return
    else:
        # 실시간 연결 구간 (market_phase 활성)
        # 이 구간에서는 실시간 틱 데이터가 캐시를 채우므로 확정 다운로드를 하지 않음
        logger.debug("[스케줄] 실시간 연결 구간 기동 — 실시간 틱 수신 중이므로 다운로드 대기/스킵")
        return




def _apply_market_phase(phase: dict) -> None:
    """전달받은 phase(krx, nxt)를 engine_state.state.market_phase에 적용 + 브로드캐스트 + 부작용 트리거.

    JIF 경로(_handle_jif → _apply_jif_phase)와 시간 기반 경로(_broadcast_market_phase)가
    공통으로 사용하는 단일 적용 경로 (P10 SSOT, P24 단순성).
    부작용 트리거 로직이 이 한 곳에 집중 — 페이즈 변경 감지 시 멱등성 보장 (같은 페이즈면 부작용 미발생).

    페이즈 변경 감지 시 부작용 트리거 (수정 8 — 타이머 3개 통합):
      - NXT "프리마켓" 진입 → _on_nxt_premarket_start() (08:00, KRX 단독 종목 제외)
      - NXT "프리마켓" 진입 → _on_ws_subscribe_start() (08:00, WS 연결 + 실시간 필드 초기화)
      - KRX "정규장" 진입 → _on_krx_market_open() (09:00, 업종 재계산)
      - KRX "종가 동시호가" 진입 → _on_krx_closing_auction_start() (15:20, KRX 단독 종목 구독해지)
      - NXT "장마감" 진입 → _on_ws_subscribe_end() (20:00, WS 연결 해제 + 구독 해지)
    """
    try:
        from backend.app.services.engine_account_notify import _broadcast
        prev_krx = engine_state.state.market_phase.get("krx")
        prev_nxt = engine_state.state.market_phase.get("nxt")
        new_krx = phase.get("krx", "")
        new_nxt = phase.get("nxt", "")
        engine_state.state.market_phase["krx"] = new_krx
        engine_state.state.market_phase["nxt"] = new_nxt
        broadcast_phase = get_market_phase()
        schedule_engine_task(_broadcast("market-phase", broadcast_phase), context="market-phase 브로드캐스트")
        # ── 체결 불가 시간대 주문 차단 상태 브로드캐스트 (P21 사용자 투명성) ──
        # 페이즈 갱신 시마다 차단 상태 산정 — JIF + 10초 주기 양쪽에서 자동 전송 (P10 SSOT, P16 살아있는 경로).
        # 페이즈 기반이므로 blocked=False 시 자동 해제 (P24 — 별도 해제 로직 없음).
        blocked, reason = get_order_time_block_status()
        schedule_engine_task(_broadcast("order_time_blocked", {"blocked": blocked, "reason": reason}), context="order_time_blocked 브로드캐스트")
        # 페이즈 변경 감지 → 업종 재계산 + WS 구독 시작/종료 트리거
        if prev_krx != new_krx or prev_nxt != new_nxt:
            # ── 장 상태 변경 로그 (P21 사용자 투명성) ──
            krx_part = f"KRX: {prev_krx} → {new_krx}" if prev_krx != new_krx else f"KRX: {new_krx} 유지"
            nxt_part = f"NXT: {prev_nxt} → {new_nxt}" if prev_nxt != new_nxt else f"NXT: {new_nxt} 유지"
            logger.info("[장상태] %s | %s", krx_part, nxt_part)
            if new_nxt == "프리마켓" and prev_nxt != "프리마켓":
                schedule_engine_task(_on_nxt_premarket_start(), context="NXT 프리마켓 진입")
                schedule_engine_task(_on_ws_subscribe_start(), context="WS 구독 시작")
            if new_krx == "정규장" and prev_krx != "정규장":
                schedule_engine_task(_on_krx_market_open(), context="KRX 정규장 진입")
            if new_krx == "종가 동시호가" and prev_krx != "종가 동시호가":
                schedule_engine_task(_on_krx_closing_auction_start(), context="KRX 종가 동시호가 — 구독 해지")
            if new_nxt == "장마감" and prev_nxt != "장마감":
                schedule_engine_task(_on_ws_subscribe_end(), context="WS 구독 종료")
    except Exception as e:
        logger.warning("[스케줄] 장 상태 적용 오류: %s", e, exc_info=True)


def _broadcast_market_phase() -> None:
    """시간 기반 장 상태 계산 + _apply_market_phase 위임.

    시간 기반 보완 경로 (안 D — JIF 1순위, 시간 기반 보조).
    calc_timebased_market_phase() 결과를 _apply_market_phase()에 전달하여
    state 갱신 + 브로드캐스트 + 부작용 트리거 수행 (P10 SSOT — 적용 경로 단일).
    """
    try:
        fresh = calc_timebased_market_phase()
        _apply_market_phase(fresh)
    except Exception as e:
        logger.warning("[스케줄] 장 상태 화면 전송 오류: %s", e, exc_info=True)


async def _apply_auto_toggle_on_startup(settings: dict) -> None:
    """앱 기동/자정 시 거래일 판별 — 실행 제어는 런타임 게이트가 담당.
    거래일 판별 결과를 로깅하고 UI 갱신 알림만 수행."""
    from backend.app.core.trading_calendar import is_trading_day, get_kst_today

    is_trade_day = is_trading_day(get_kst_today())

    logger.debug("[스케줄] 기동 판별 — 거래일=%s (설정값 미변경)", is_trade_day)
    try:
        from backend.app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        await notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
    except Exception as e:
        logger.warning("[시스템] 화면 전송 실패: %s", e, exc_info=True)


async def _on_realtime_fields_reset() -> None:
    """07:58 사전 트리거 — 실시간 필드 초기화 + GC 비활성화 + 캐시 초기화 (데이터 준비 통합).

    WS 구독 시작(07:59)과 분리하여 1분 먼저 실행 — WS 연결 전에 전일 데이터 제거 +
    장중 GC 비활성화 + 수신율 게이트 리셋 + delta 비교 캐시 초기화.
    날짜 기반 멱등성 가드: 같은 날 중복 실행 방지 (P22 데이터 정합성).
    거래일 체크 이후 GC 비활성화 — 주말/공휴일 시 GC 비활성화 생략 (개선).
    """
    try:
        today = _kst_now()
        today_str = today.strftime("%Y%m%d")
        if engine_state.state.last_realtime_reset_date == today_str:
            return  # 이미 오늘 실행됨 — 중복 방지
        from backend.app.core.trading_calendar import is_trading_day
        if today.weekday() >= 5 or not is_trading_day(today.date()):
            return
        logger.info("[작업실행] 실시간 필드 초기화 + GC 비활성화 + 캐시 초기화 (사전 — 07:58)")
        # 장중 GC 비활성화 (HFT 지연 방지) — 거래일 체크 이후 실행 (주말 GC 비활성화 방지)
        gc.disable()
        logger.info("[스케줄] 장중 메모리 정리 비활성화 (실시간 처리 지연 방지)")
        # 실시간 필드 초기화 (전일 확정 데이터 제거)
        from backend.app.services.engine_snapshot import _reset_realtime_fields
        await _reset_realtime_fields()
        # 수신율 임계값 게이트 리셋 — 새 구독 세션 시작 시 임계값 대기 상태로 전환
        from backend.app.pipelines.pipeline_compute import reset_sector_threshold
        reset_sector_threshold()
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        from backend.app.services.engine_account_notify import notify_cache
        notify_cache.prev_scores = []
        engine_state.state.sector_summary_cache = None
        engine_state.state.last_realtime_reset_date = today_str
        logger.info("[작업실행] 실시간 필드 초기화 + GC 비활성화 + 캐시 초기화 완료 (사전 — 07:58)")
    except Exception as e:
        logger.warning("[작업실행] 실시간 필드 초기화 오류: %s", e, exc_info=True)


async def _on_ws_subscribe_start() -> None:
    """WS 구독 시작 — WS 구독 구간 진입 상태 전환 + 엔진 루프 통지.

    07:59 사전 트리거 (타임테이블) 또는 08:00 phase 변경 감지 (_apply_market_phase)로 호출.
    날짜 기반 멱등성 가드: 같은 날 중복 실행 방지.
    데이터 준비(GC 비활성화 + 필드 초기화 + 게이트 리셋 + 캐시 초기화)는
    _on_realtime_fields_reset()에서 07:58에 사전 실행 (통합). 사전 실행 누락 시 보완.
    """
    try:
        today = _kst_now()
        today_str = today.strftime("%Y%m%d")
        if engine_state.state.last_ws_subscribe_start_date == today_str:
            logger.debug("[작업실행] NXT 종목 구독 신청 스킵 (이미 실행됨 — %s)", today_str)
            return
        if today.weekday() >= 5:
            return
        from backend.app.core.trading_calendar import is_trading_day
        if not is_trading_day(today.date()):
            return
        logger.info("[작업실행] NXT 종목 구독 신청 (사전 — 07:59)")
        engine_state.state.ws_subscribe_window_active = True
        engine_state.state.last_ws_subscribe_start_date = today_str
        # ── 데이터 준비는 07:58 사전 실행됨 (_on_realtime_fields_reset — GC+필드+게이트+캐시 통합) ──
        #    사전 실행 누락 시 여기서 보완 (멱등성 — last_realtime_reset_date 체크, P16 살아있는 경로)
        if engine_state.state.last_realtime_reset_date != today_str:
            logger.info("[스케줄] 데이터 준비 사전 실행 누락 — 보완 (실시간 필드 초기화 + GC 비활성화)")
            await _on_realtime_fields_reset()
        # market-phase WS 브로드캐스트 (WS 구독 시작 = 07:59 또는 08:00 전환 시점)
        _broadcast_market_phase()
        # ── WS 연결은 엔진 루프의 구간 감지가 담당 → 이벤트 통지 ──
        engine_state.state.ws_window_changed_event.set()
        logger.info("[작업실행] NXT 종목 구독 신청 완료 — 엔진 루프에 연결 통지 (사전 — 07:59)")
    except Exception as e:
        logger.warning("[작업실행] NXT 종목 구독 신청 콜백 오류: %s", e, exc_info=True)


async def _on_ws_subscribe_end() -> None:
    """WS 구독 종료 시각이 되면 자동 실행 — 실시간 수신 중단 + WS 연결 해제 + 업종 재계산을 순서대로 하는 함수."""
    try:
        logger.info("[작업실행] NXT 종목 구독 해지 + 장마감 시작 (20:00 — 장마감)")
        # 장마감 후 GC 정상화 및 메모리 정리
        gc.enable()
        gc.collect()
        logger.info("[작업실행] 장마감 후 메모리 정리 정상화 완료")

        from backend.app.core.memory_monitor import start_memory_monitor, log_memory_snapshot, stop_memory_monitor
        start_memory_monitor()
        log_memory_snapshot("장마감 GC 정리 후")
        stop_memory_monitor()
        engine_state.state.ws_subscribe_window_active = False
        # ── 수신율 임계값 게이트 해제 — 장마감 후 확정 데이터 기반 전송 허용 ──
        from backend.app.pipelines.pipeline_compute import mark_sector_threshold_passed
        mark_sector_threshold_passed()
        engine_state.state.confirmed_done = False  # 오후 8시 구독 종료 → 8시 30분 확정 갱신 허용
        await _trigger_unreg_all()
        # 구독 상태 전체 false + WS 브로드캐스트
        from backend.app.services.ws_subscribe_control import _set_status
        _set_status(quote=False)
        # market-phase WS 브로드캐스트 (구독 종료 시각 기준 상태 반영)
        _broadcast_market_phase()
        # ── WS 연결 해제는 엔진 루프의 구간 감지가 담당 → 이벤트 통지 ──
        engine_state.state.ws_window_changed_event.set()
        logger.info("[작업실행] NXT 종목 구독 해지 + 장마감 완료 — 엔진 루프에 해제 통지 (20:00 — 장마감)")
        # ── 확정 데이터 다운로드는 타임테이블 11번째 항목(timetable.confirmed_download)이 담당 ──
        # ws_subscribe_end와 분리하여 증권사 확정 데이터 준비 시간 확보 (기본값 20:40)
    except Exception as e:
        logger.warning("[작업실행] NXT 종목 구독 해지 + 장마감 콜백 오류: %s", e, exc_info=True)


async def _on_confirmed_download() -> None:
    """timetable.confirmed_download 도달 시 확정 데이터 다운로드 실행.

    P22 (데이터 정합성): last_confirmed_download_date 날짜 기반 멱등성 가드 —
        같은 날 2회 호출 시 2회째 스킵. 기존 last_realtime_reset_date 패턴과 동일 (P23).
        기존 confirmed_done 플래그는 _fire_unified_confirmed_fetch() 내 1차 가드로 유지 (이중 안전장치).
    """
    try:
        today_str = _kst_now().strftime("%Y%m%d")
        if engine_state.state.last_confirmed_download_date == today_str:
            logger.debug("[스케줄] 확정 다운로드 오늘 이미 실행 — 스킵 (P22)")
            return
        logger.info("[스케줄] 확정 시세 다운로드 시각 도달 → 확정 데이터 다운로드 트리거")
        _fire_unified_confirmed_fetch()
        engine_state.state.last_confirmed_download_date = today_str
    except Exception as e:
        logger.warning("[스케줄] 확정 데이터 다운로드 콜백 오류: %s", e, exc_info=True)


# ── 타임테이블 스케줄러 (10초 루프 대체) ──────────────────────────────────────
# 시간표 항목: (시각 상수, 동작 종류, 콜백, 컨텍스트)
# - kind="direct": 시각 도달 시 callback 직접 실행 (사전 트리거)
# - kind="phase":  시각 도달 시 _broadcast_market_phase() 호출 (페이즈 재계산)
#
# P10 SSOT: 시간 상수는 기존 라인 21-49 재사용, 신규 상수 생성 없음.
# P24 단순성: 두 종류를 동일 리스트에서 kind 필드로 구분 (별도 리스트 분할 금지).
# P16 (살아있는 경로): _TIMETABLE은 기동 시 build_timetable_from_cache()로 채워짐.
#   빈 리스트 상태로 스케줄러 동작 금지 → start_daily_time_scheduler()에서 반드시 빌드 호출.
_TIMETABLE: list[dict] = []


def _parse_hm_tuple(v: str) -> tuple[int, int]:
    """HH:MM 문자열 → (h, m) 튜플. 형식 오류 시 ValueError (P20 폴백 금지)."""
    h, m = str(v).strip().split(":")
    return int(h), int(m)


def _to3(hm_or_hms: tuple) -> tuple[int, int, int]:
    """(h, m) → (h, m, 0), (h, m, s) → 그대로. 타임테이블 time 필드 3-tuple 정규화 (P23 일관성)."""
    if len(hm_or_hms) == 2:
        return (hm_or_hms[0], hm_or_hms[1], 0)
    return hm_or_hms  # 이미 3-tuple


def _fmt_hms(hms: tuple[int, int, int]) -> str:
    """3-tuple → "HH:MM" (s=0) 또는 "HH:MM:SS" (s≠0). ctx 문자열용 (기존 표시 호환)."""
    h, m, s = hms
    return f"{h:02d}:{m:02d}:{s:02d}" if s else f"{h:02d}:{m:02d}"


def build_timetable_from_cache(settings: dict) -> list[dict]:
    """설정 캐시 기반으로 타임테이블 리스트 빌드 (P10 SSOT · P13 메모리 상주).

    인자: engine_state.state.integrated_system_settings_cache 스냅샷
    반환: dict 리스트 (11~12항목) — time 필드는 모두 (h, m, s) 3-tuple (P23 일관성)
          - 3~4개 direct: 시각을 캐시에서 읽음 (없으면 DEFAULT_USER_SETTINGS 기본값)
          - 8개 phase:    시각을 코드 상수(21-49)에서 읽음 (거래소 고정, 09:00:30 포함)

    P16 (살아있는 경로): scheduler_market_close_on OFF 시 마지막 항목 스킵 —
        dead path(콜백 호출 후 아무 동작 없음) 제거.
        09:00:30 NXT 메인마켓 phase 엔트리 추가 — JIF 미수신 시 시간표 보완 경로가 전환 수행.
    P24 단순성: 함수 50줄 이하, 복잡도 O(n) n=12.
    P20 폴백 금지: 캐시에 키가 없으면 DEFAULT_USER_SETTINGS 기본값 (이것도 없으면 ValueError).
    """
    from backend.app.core.settings_defaults import DEFAULT_USER_SETTINGS

    def _cache_time(key: str) -> tuple[int, int, int]:
        v = settings.get(key) or DEFAULT_USER_SETTINGS.get(key)
        if not v:
            raise ValueError(f"타임테이블 시각 누락: {key} — 기본값 폴백 금지 (P20)")
        return _to3(_parse_hm_tuple(v))

    rt = _cache_time("timetable.realtime_reset")
    ws = _cache_time("timetable.ws_prestart")
    krx = _cache_time("timetable.krx_pre_subscribe")

    entries: list[dict] = [
        {"time": rt,   "kind": "direct", "action": _on_realtime_fields_reset, "ctx": f"실시간 필드 초기화 ({_fmt_hms(rt)})"},
        {"time": ws,   "kind": "direct", "action": _on_ws_subscribe_start,    "ctx": f"WS 구독 사전 시작 ({_fmt_hms(ws)})"},
        {"time": _to3(NXT_PREMARKET_START),  "kind": "phase",  "ctx": "NXT 프리마켓 진입 감지 (08:00)"},
        {"time": krx,  "kind": "direct", "action": _on_krx_pre_subscribe,     "ctx": f"KRX 사전 구독 ({_fmt_hms(krx)})"},
        {"time": _to3(KRX_REGULAR_START),    "kind": "phase",  "ctx": "KRX 정규장 진입 감지 (09:00)"},
        {"time": NXT_MAINMARKET_START,       "kind": "phase",  "ctx": "NXT 메인마켓 진입 감지 (09:00:30)"},
        {"time": _to3(KRX_REGULAR_END),      "kind": "phase",  "ctx": "KRX 종가 동시호가 진입 감지 (15:20)"},
        {"time": _to3(KRX_CLOSING_AUCTION_END), "kind": "phase",  "ctx": "KRX 체결 정산 전환 감지 (15:30)"},
        {"time": _to3(NXT_SINGLE_PRICE_END), "kind": "phase",  "ctx": "NXT 애프터마켓 진입 감지 (15:40)"},
        {"time": _to3(NXT_AFTERMARKET_END),  "kind": "phase",  "ctx": "NXT 장마감 진입 감지 (20:00)"},
        # ── 카운트다운 갱신 엔트리 (kind="countdown" — 페이즈 전환 아님, JIF 미수신 공백 보조) ──
        # JIF override 활성 시 _timetable_event_fired()에서 스킵 (JIF 1순위 — 중복 갱신 방지).
        # KRX 장개시 카운트다운 (→ 09:00)
        {"time": _to3(KRX_OPEN_COUNTDOWN_10M),  "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 10분전 (08:50)"},
        {"time": _to3(KRX_OPEN_COUNTDOWN_5M),   "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 5분전 (08:55)"},
        {"time": _to3(KRX_OPEN_COUNTDOWN_1M),   "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 1분전 (08:59)"},
        {"time": _to3(KRX_OPEN_COUNTDOWN_10S),  "kind": "countdown", "market": "krx", "ctx": "KRX 장개시 10초전 (08:59:50)"},
        # KRX 장마감 카운트다운 (→ 15:20) — 10분전은 보조 전용 (JIF 10분전 코드 없음)
        {"time": _to3(KRX_CLOSE_COUNTDOWN_10M), "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 10분전 (15:10)"},
        {"time": _to3(KRX_CLOSE_COUNTDOWN_5M),  "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 5분전 (15:15)"},
        {"time": _to3(KRX_CLOSE_COUNTDOWN_1M),  "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 1분전 (15:19)"},
        {"time": _to3(KRX_CLOSE_COUNTDOWN_10S), "kind": "countdown", "market": "krx", "ctx": "KRX 장마감 10초전 (15:19:50)"},
        # NXT 프리마켓 장개시 카운트다운 (→ 08:00)
        {"time": _to3(NXT_PRE_OPEN_COUNTDOWN_10M),  "kind": "countdown", "market": "nxt", "ctx": "NXT 프리마켓 장개시 10분전 (07:50)"},
        {"time": _to3(NXT_PRE_OPEN_COUNTDOWN_5M),   "kind": "countdown", "market": "nxt", "ctx": "NXT 프리마켓 장개시 5분전 (07:55)"},
        {"time": _to3(NXT_PRE_OPEN_COUNTDOWN_1M),   "kind": "countdown", "market": "nxt", "ctx": "NXT 프리마켓 장개시 1분전 (07:59)"},
        {"time": _to3(NXT_PRE_OPEN_COUNTDOWN_10S),  "kind": "countdown", "market": "nxt", "ctx": "NXT 프리마켓 장개시 10초전 (07:59:50)"},
        # NXT 프리마켓 장마감 카운트다운 (→ 08:50, 5분전이 최대)
        {"time": _to3(NXT_PRE_CLOSE_COUNTDOWN_5M),  "kind": "countdown", "market": "nxt", "ctx": "NXT 프리마켓 장마감 5분전 (08:45)"},
        {"time": _to3(NXT_PRE_CLOSE_COUNTDOWN_1M),  "kind": "countdown", "market": "nxt", "ctx": "NXT 프리마켓 장마감 1분전 (08:49)"},
        {"time": _to3(NXT_PRE_CLOSE_COUNTDOWN_10S), "kind": "countdown", "market": "nxt", "ctx": "NXT 프리마켓 장마감 10초전 (08:49:50)"},
        # NXT 에프터마켓 장개시 카운트다운 (→ 15:40)
        {"time": _to3(NXT_AFT_OPEN_COUNTDOWN_10M),  "kind": "countdown", "market": "nxt", "ctx": "NXT 에프터마켓 장개시 10분전 (15:30)"},
        {"time": _to3(NXT_AFT_OPEN_COUNTDOWN_5M),   "kind": "countdown", "market": "nxt", "ctx": "NXT 에프터마켓 장개시 5분전 (15:35)"},
        {"time": _to3(NXT_AFT_OPEN_COUNTDOWN_1M),   "kind": "countdown", "market": "nxt", "ctx": "NXT 에프터마켓 장개시 1분전 (15:39)"},
        {"time": _to3(NXT_AFT_OPEN_COUNTDOWN_10S),  "kind": "countdown", "market": "nxt", "ctx": "NXT 에프터마켓 장개시 10초전 (15:39:50)"},
        # NXT 에프터마켓 장마감 카운트다운 (→ 20:00, 5분전이 최대)
        {"time": _to3(NXT_AFT_CLOSE_COUNTDOWN_5M),  "kind": "countdown", "market": "nxt", "ctx": "NXT 에프터마켓 장마감 5분전 (19:55)"},
        {"time": _to3(NXT_AFT_CLOSE_COUNTDOWN_1M),  "kind": "countdown", "market": "nxt", "ctx": "NXT 에프터마켓 장마감 1분전 (19:59)"},
        {"time": _to3(NXT_AFT_CLOSE_COUNTDOWN_10S), "kind": "countdown", "market": "nxt", "ctx": "NXT 에프터마켓 장마감 10초전 (19:59:50)"},
    ]

    # 마지막 항목 — 확정 데이터 다운로드 (timetable.confirmed_download)
    # 토글 OFF 시 엔트리 자체 스킵 → 콜백 내부 게이트 불필요 (P16 살아있는 경로)
    scheduler_close_on = bool(settings.get("scheduler_market_close_on", True))
    if scheduler_close_on:
        cd = _cache_time("timetable.confirmed_download")
        entries.append({
            "time": cd,
            "kind": "direct",
            "action": _on_confirmed_download,
            "ctx": f"확정 데이터 다운로드 ({_fmt_hms(cd)})",
        })

    return entries


def _schedule_next_timetable_event() -> None:
    """시간표에서 다음 미래 이벤트를 찾아 call_later 1개 예약.

    P11 (폴링 금지): while + sleep 대신 call_later 이벤트 기반.
    P14 (멀티스레드 금지): 타이머 1개만 유지 (기존 타이머 취소 후 재예약).
    P24 단순성: 시간표 선형 스캔, 복잡도 O(n) n=12.
    """
    # 기존 타이머 취소
    if engine_state.state.timetable_timer_handle is not None:
        engine_state.state.timetable_timer_handle.cancel()
        engine_state.state.timetable_timer_handle = None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    now = _kst_now()
    now_sec = now.hour * 3600 + now.minute * 60 + now.second

    # 다음 미래 이벤트 탐색 (오늘 남은 이벤트)
    next_entry = None
    next_delay = None
    for entry in _TIMETABLE:
        h, m, s = entry["time"]
        event_sec = h * 3600 + m * 60 + s
        delay = event_sec - now_sec
        if delay <= 0:
            continue  # 이미 지난 이벤트
        if next_delay is None or delay < next_delay:
            next_delay = delay
            next_entry = entry

    if next_entry is None or next_delay is None:
        # 오늘 남은 이벤트 없음 → 익일 첫 이벤트까지 대기
        # P10 SSOT: 빌드된 _TIMETABLE의 첫 항목 시각을 참조 (사용자 조정 시각 반영).
        # 빈 리스트 상태는 기동 시 빌드 전에만 존재 → REALTIME_FIELDS_RESET_TIME 상수로 안전장치.
        first_time = _to3(_TIMETABLE[0]["time"]) if _TIMETABLE else _to3(REALTIME_FIELDS_RESET_TIME)
        h, m, s = first_time
        target = now.replace(hour=h, minute=m, second=s, microsecond=0) + timedelta(days=1)
        next_delay = (target - now).total_seconds()
        next_entry = {"time": first_time, "kind": "phase", "ctx": f"익일 첫 이벤트 ({_fmt_hms(first_time)} 재스케줄)"}

    # 최소 1초 보장 (즉시 실행 방지)
    delay = max(next_delay, 1)
    engine_state.state.timetable_timer_handle = loop.call_later(
        delay,
        lambda: schedule_engine_task(_timetable_event_fired(next_entry), context=f"타임테이블: {next_entry['ctx']}"),
    )
    logger.debug("[스케줄] 다음 타임테이블 이벤트 — %s (%.0f초 후)", next_entry["ctx"], delay)


async def _timetable_event_fired(entry: dict) -> None:
    """타임테이블 이벤트 발생 시 실행 — 동작 수행 + 다음 이벤트 예약.

    P16 (살아있는 경로): JIF 미수신 시 시간표가 보완 경로 유지.
    P22 (데이터 정합성): 멱등성 가드는 각 _on_* 콜백 내부에서 유지.
    P20 (폴백 금지): 예외 시 logger.warning(exc_info=True), silent pass 금지.
    """
    try:
        kind = entry["kind"]
        ctx = entry["ctx"]
        logger.info("[스케줄] 타임테이블 이벤트 실행 — %s", ctx)

        if kind == "direct":
            # 직접 동작: 사전 트리거 콜백 실행
            action = entry["action"]
            await action()
        elif kind == "phase":
            # 페이즈 재계산: _broadcast_market_phase() → _apply_market_phase() 내 부작용 트리거
            _broadcast_market_phase()
        elif kind == "countdown":
            # 보조 로직 — JIF 미수신 공백 시 카운트다운 갱신 (P16 살아있는 경로).
            # JIF override 활성 시 스킵 (JIF 1순위 — 중복 갱신 방지, P10 SSOT).
            # override 없으면 calc_countdown() 보완값으로 브로드캐스트 (get_market_phase가 자동 반영).
            market = entry["market"]
            if _get_active_override(market) is not None:
                return  # JIF override 활성 → 보조 로직 스킵
            from backend.app.services.engine_account_notify import _broadcast
            schedule_engine_task(
                _broadcast("market-phase", get_market_phase()),
                context=f"countdown 브로드캐스트 ({ctx})",
            )

        # JIF 미수신 헬스체크 (옵션 A — 이벤트 실행 시점에 체크)
        _check_jif_health()

    except Exception as e:
        logger.warning("[스케줄] 타임테이블 이벤트 오류: %s", e, exc_info=True)
    finally:
        # 다음 이벤트 예약 (오류 발생 여부와 무관하게 스케줄러 지속)
        _schedule_next_timetable_event()


# JIF 헬스체크 임계값 — 마지막 JIF 수신 후 이 시간(초) 경과 시 경고
_JIF_STALE_WARN_SEC = 120  # 2분 (JIF는 페이즈 전환 시점에만 수신되므로 넉넉한 임계값)


def _check_jif_health() -> None:
    """마지막 JIF 수신 시각 경과 시간 체크 — 경고만 로깅, 자동 조치 없음 (P24).

    P21 (사용자 투명성): JIF 미수신 시 사용자가 인지할 수 있도록 로그.
    단, 자동 조치(강제 페이즈 전환 등)는 금지 — 시간표가 이미 보완 역할 수행 중.
    """
    last_jif = engine_state.state.last_jif_received_at
    if last_jif is None:
        # 기동 후 JIF 미수신 — 시간표가 보완 중이므로 경고만
        logger.debug("[스케줄] JIF 미수신 상태 — 시간표 보완 동작 중")
        return
    elapsed = (_kst_now() - last_jif).total_seconds()
    if elapsed > _JIF_STALE_WARN_SEC:
        logger.warning("[스케줄] JIF 미수신 %.0f초 경과 — 시간표 보완 경로로 동작 중", elapsed)


async def _timetable_startup_scan() -> None:
    """기동 시 시간표 스캔 — 다음 미래 이벤트 예약.

    P16 (살아있는 경로): 재기동 시 사전 트리거 구간(07:58~08:00) 누락 방지.
    P22 (데이터 정합성): 멱등성 가드(engine_state.state.last_*_date)로 중복 실행 차단.
    P24 단순성: 본 함수는 "다음 예약"에만 집중 — 직접 동작 즉시 실행은
    기존 _init_ws_subscribe_state()(998-1046)가 담당, 중복 금지.

    기동 시나리오:
    - 07:55 재기동: 07:58/07:59 이벤트 예약만 (아직 도달 전)
    - 07:58:30 재기동: 07:58 direct 동작은 _init_ws_subscribe_state()가 담당 + 07:59 예약
    - 09:30 재기동: 07:58/07:59/08:59 direct 동작 스킵 (이미 지난, 멱등성 가드) + 15:20 예약
    """
    # 기동 시 현재 페이즈 즉시 산정은 기존 start_daily_time_scheduler()(1394-1397)가 담당
    # — 본 함수에서 중복 수행 금지

    # 다음 미래 이벤트 예약
    _schedule_next_timetable_event()
    logger.info("[기동] 타임테이블 스케줄러 시작 — 다음 이벤트 예약 완료")


async def _init_ws_subscribe_state() -> None:
    """
    엔진 재기동 시 현재 시각 기준으로 WS 구독 상태를 판정하고,
    WS 구독 구간 밖이면서 업종 갱신이 아직 안 됐으면 즉시 1회 갱신하는 함수.

    사전 구독 구간(07:59~08:00) 재시작 시: is_ws_subscribe_window()가 시간 기반으로
    True 반환 (Change 2) → in_window=True 분기가 GC 비활성화 + 필드 초기화 + 게이트
    리셋 + 캐시 초기화 수행 (07:58 로직과 동일). P16 살아있는 경로 — 재시작 시 사전
    구간 누락 없음.
    """
    settings = engine_state.state.integrated_system_settings_cache
    if not settings or not isinstance(settings, dict):
        raise RuntimeError("settings cache not initialized")
    in_window = await is_ws_subscribe_window(settings)
    engine_state.state.ws_subscribe_window_active = in_window

    # ── 수신율 임계값 게이트 동기화 — 엔진 재기동 시 현재 구간에 맞게 플래그 설정 ──
    from backend.app.pipelines.pipeline_compute import reset_sector_threshold, mark_sector_threshold_passed
    if in_window:
        reset_sector_threshold()
    else:
        mark_sector_threshold_passed()

    if in_window:
        # 장중 GC 비활성화 (HFT 지연 방지) — _on_ws_subscribe_start와 동일
        gc.disable()
        logger.info("[스케줄] 장중 메모리 정리 비활성화 (실시간 처리 지연 방지)")
        # ── 4단계: 구독 구간 내 기동 시 날짜 플래그 동기화 (중복 실행 방지) ──
        today_str = _kst_now().strftime("%Y%m%d")
        engine_state.state.last_ws_subscribe_start_date = today_str
        # ── 실시간 필드 초기화 (전일 확정 데이터 제거) ──
        # 캐시 로드 전이면 스킵 — engine_cache._load_caches_preboot()에서 DB 로드 후 수행
        if engine_state.state.preboot_cache_loaded:
            logger.info("[스케줄] 구독 구간 내 시작 — 실시간 필드 초기화")
            from backend.app.services.engine_snapshot import _reset_realtime_fields
            await _reset_realtime_fields()
            engine_state.state.last_realtime_reset_date = today_str
        else:
            logger.info("[스케줄] 구독 구간 내 시작 — 실시간 필드 초기화는 캐시 로드 후 수행")
        # delta 비교 캐시 초기화 → 다음 sector-scores 전송이 전체 스냅샷으로 나감
        try:
            from backend.app.services.engine_account_notify import notify_cache
            notify_cache.prev_scores = []
            engine_state.state.sector_summary_cache = None
        except Exception as e:
            logger.warning("[시스템] 캐시 초기화 실패: %s", e, exc_info=True)

        # market-phase WS 브로드캐스트 — _on_ws_subscribe_start와 동일
        _broadcast_market_phase()

        engine_state.state.ws_window_changed_event.set()
        logger.info("[스케줄] 구독 구간 내 시작 — 엔진 루프에 연결 통지")
    else:
        # 구독 상태 false + WS 브로드캐스트
        from backend.app.services.ws_subscribe_control import _set_status
        _set_status(quote=False)


def _trigger_reg_pipeline() -> None:
    """로그인 상태면 REG 파이프라인 재실행."""
    try:
        ws = engine_state.state.connector_manager or engine_state.state.active_connector
        if ws and ws.is_connected() and engine_state.state.login_ok:
            from backend.app.services.engine_bootstrap import _login_post_pipeline
            schedule_engine_task(_login_post_pipeline(), context="REG 파이프라인 재실행")
        else:
            logger.info("[스케줄] 구독 구간 진입 — 연결 없음, 연결 후 자동 구독됨")
    except Exception as e:
        logger.warning("[스케줄] 구독 등록 파이프라인 실행 오류: %s", e)


async def _trigger_unreg_all() -> None:
    """구독 중인 종목 전체 UNREG 전송 + WS 캐시 클리어."""
    try:
        # 실시간 틱 데이터 캐시 clear() 로직 삭제 (_latest_trade_prices, _latest_trade_amounts, _latest_strength)
        logger.info("[스케줄] 캐시 데이터 삭제 완료")

        ws = engine_state.state.connector_manager or engine_state.state.active_connector
        if not ws or not ws.is_connected() or not engine_state.state.login_ok:
            return
        await _do_unreg_all()
    except Exception as e:
        logger.warning("[스케줄] 구독 해지 오류: %s", e)


async def _do_unreg_all() -> None:
    """구독 중인 종목 전체 REMOVE 전송 (비동기)."""
    try:
        subscribed = {cd for cd, entry in engine_state.state.master_stocks_cache.items() if entry.get("_subscribed", False)}
        ws = engine_state.state.connector_manager or engine_state.state.active_connector
        if not ws or not ws.is_connected():
            return

        all_codes = list(subscribed)
        if not all_codes:
            logger.info("[스케줄] 구독 해지 대상 없음 — 이미 구독 없음")
            return

        # Broker Abstraction: subscribe_stocks / unsubscribe_stocks 추상 API 사용
        ok = await ws.unsubscribe_stocks(all_codes)

        # 키움증권일 때만 계좌 실시간도 해지 (grp 10)
        broker_nm = str(engine_state.state.integrated_system_settings_cache["broker"]).lower().strip()
        if broker_nm == "kiwoom":
            acnt_no = str(engine_state.state.integrated_system_settings_cache.get(f"{broker_nm}_account_no", "") or "").strip()
            if acnt_no:
                await ws.send_message({
                    "trnm": "REMOVE", "grp_no": "10", "refresh": "0",
                    "data": [{"item": [""], "type": ["00", "04"]}],
                })

        # 구독 상태 초기화
        for cd in subscribed:
            if cd in engine_state.state.master_stocks_cache:
                engine_state.state.master_stocks_cache[cd].pop("_subscribed", None)

        logger.info("[스케줄] 구독 해지 완료 — %d종목 (성공=%s)", len(all_codes), ok)

        # ws_subscribe_control 상태 동기화 — 구독 해지 완료
        from backend.app.services import ws_subscribe_control
        ws_subscribe_control._set_status(quote=False)
    except Exception as e:
        logger.warning("[스케줄] 구독 해지 전송 오류: %s", e)


# ── call_later 기반 매수/매도 시간 전환 타이머 ─────────────────────────────────


def _seconds_until_hm(h: int, m: int) -> float:
    """현재 KST 시각에서 오늘 h:m까지 남은 초. 이미 지났으면 음수."""
    now = _kst_now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (target - now).total_seconds()


async def _on_auto_trade_transition(label: str) -> None:
    """매수/매도 시간 구간 진입/이탈 시 1회 실행되는 콜백."""
    try:
        from backend.app.services.engine_config import refresh_engine_integrated_system_settings_cache
        from backend.app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        logger.info("[스케줄] 자동매매 시간 전환 — %s", label)
        # 엔진 설정 캐시 갱신 (메모리만, 디스크 I/O 없음)
        schedule_engine_task(refresh_engine_integrated_system_settings_cache(None, use_root=True), context="설정 캐시 갱신")
        await notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
    except Exception as e:
        logger.warning("[스케줄] 자동매매 전환 콜백 오류: %s", e)


async def schedule_auto_trade_timers(settings: dict | None = None) -> None:
    """
    매수/매도 시간 구간 전환 시점에 call_later 타이머를 예약한다.
    기존 타이머는 모두 취소 후 재예약.
    엔진 기동 시 + 설정 변경 시 호출.
    """

    # 기존 타이머 전부 취소
    for handle in engine_state.state.auto_trade_timer_handles:
        handle.cancel()
    engine_state.state.auto_trade_timer_handles.clear()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 이벤트 루프 없으면 스킵

    if settings is None:
        # engine_state.state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = engine_state.state.integrated_system_settings_cache
    if not settings:
        raise RuntimeError("settings cache not initialized")

    # ws_subscribe 타이머는 time_scheduler_on과 무관하게 항상 예약 (독립 기능)
    # 매수/매도 타이머만 time_scheduler_on 체크
    if not bool(settings.get("time_scheduler_on", False)):
        return  # 마스터 스위치 OFF면 매수/매도 타이머 불필요

    # 예약 대상 시각들: 매수 시작/종료, 매도 시작/종료
    time_points = [
        ("buy_time_start", str(settings["buy_time_start"])[:5], "매수 구간 진입"),
        ("buy_time_end", str(settings["buy_time_end"])[:5], "매수 구간 이탈"),
        ("sell_time_start", str(settings["sell_time_start"])[:5], "매도 구간 진입"),
        ("sell_time_end", str(settings["sell_time_end"])[:5], "매도 구간 이탈"),
    ]

    for key, hm_str, label in time_points:
        h, m = _parse_hm(hm_str)
        delay = _seconds_until_hm(h, m)
        if delay < 0:
            continue  # 이미 지난 시각은 스킵
        if delay < 1:
            delay = 1  # 최소 1초 (즉시 실행 방지)
        handle = loop.call_later(delay, lambda: schedule_engine_task(_on_auto_trade_transition(label), context=f"자동매매 전환({label})"))
        engine_state.state.auto_trade_timer_handles.append(handle)
        logger.debug(
            "[스케줄] %s (%s) — %.0f초 후 예약",
            label, hm_str, delay,
        )


# ── call_later 기반 자정 날짜 변경 타이머 ─────────────────────────────────────


async def _on_midnight() -> None:
    """자정(00:00)이 되면 자동 실행 — 갱신 플래그를 초기화하고 당일 타이머를 새로 예약하는 함수."""
    try:
        now = _kst_now()

        if engine_state.state.last_reset_date != now.strftime("%Y%m%d"):
            engine_state.state.last_reset_date = now.strftime("%Y%m%d")
            engine_state.state.krx_remove_done = False
            engine_state.state.confirmed_done = False
            engine_state.state.last_confirmed_download_date = ""  # 확정 다운로드 멱등성 가드 리셋 (P22)
            logger.info("[스케줄] 자정 날짜 변경 — 플래그 초기화 (%s)", engine_state.state.last_reset_date)

            # 연도 변경 시 다음 연도 거래일 캐시 미리 생성 (블로킹 방지)
            current_year = now.year
            from backend.app.core.trading_calendar import has_trading_days_for_year, refresh_trading_days_for_year
            next_year = current_year + 1
            if not has_trading_days_for_year(next_year):
                logger.info("[스케줄] 연도 변경 — %d년 거래일 캐시 생성", next_year)
                await refresh_trading_days_for_year(next_year)


            # 날짜 변경 시 거래일/시간 기준 자동 ON/OFF 판별
            # engine_state.state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
            settings = engine_state.state.integrated_system_settings_cache
            if not settings:
                raise RuntimeError("settings cache not initialized")
            await _apply_auto_toggle_on_startup(settings)

            await schedule_auto_trade_timers(settings)
            # ── 타임테이블 타이머는 _schedule_next_timetable_event()가 다음 미래 이벤트를
            #    자동 예약하므로 자정에 별도 재예약 불필요 (P14 단일 타이머, P24 단순성).
            #    confirmed_download 타이머도 타임테이블 11번째 항목으로 통합 (4세션).
        # 다음날 자정 타이머 재예약 (날짜 변경 여부와 무관하게 항상 수행)
        schedule_midnight_timer()
    except Exception as e:
        logger.warning("[스케줄] 자정 콜백 오류: %s", e)


def schedule_midnight_timer() -> None:
    """다음 자정(00:00)에 call_later 타이머를 예약하는 함수. 엔진 기동 시 + 자정 콜백에서 호출."""
    if engine_state.state.midnight_timer_handle is not None:
        engine_state.state.midnight_timer_handle.cancel()
        engine_state.state.midnight_timer_handle = None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    delay = _seconds_until_hm(0, 0)
    if delay <= 0:
        # 이미 자정 지남 → 다음날 자정까지 (24시간 + delay)
        delay += 86400
    engine_state.state.midnight_timer_handle = loop.call_later(max(delay, 1), lambda: schedule_engine_task(_on_midnight(), context="자정 날짜 변경"))
    logger.debug("[스케줄] 자정 타이머 — %.0f초 후 예약", delay)


# ── 스케줄러 시작/중지 ────────────────────────────────────────────────────────


async def start_daily_time_scheduler() -> None:
    """타임스케줄러를 시작하는 함수 — 이벤트 타이머 초기 예약."""
    # 엔진 기동 시 타이머 초기 예약
    try:
        # ── 기동 시 자동 ON/OFF 판별: 거래일+시간구간이면 ON, 아니면 OFF ──
        # engine_state.state.integrated_system_settings_cache는 app.py에서 이미 초기화됨 (단일 소스 진리)
        settings = engine_state.state.integrated_system_settings_cache
        if not settings:
            raise RuntimeError("settings cache not initialized")
        await _apply_auto_toggle_on_startup(settings)

        # ── market_phase 시간 기반 초기화 (SSOT) ──
        phase = calc_timebased_market_phase()
        engine_state.state.market_phase["krx"] = phase["krx"]
        engine_state.state.market_phase["nxt"] = phase["nxt"]
        logger.info("[기동] 장 상태 계산 완료 | KRX: %s, NXT: %s", phase["krx"], phase["nxt"])

        # 기동 시 현재 장 상태 즉시 브로드캐스트 (WS 구독 창과 무관)
        _broadcast_market_phase()

        engine_state.state.last_reset_date = _kst_now().strftime("%Y%m%d")

        await schedule_auto_trade_timers(settings)
        schedule_midnight_timer()

        # ── 타임테이블 빌드 (DB 저장 시각 반영 — P10/P13/P16) ──
        # 기동 시 캐시 기반으로 _TIMETABLE 채움. 빈 리스트 상태로 스케줄러 동작 금지.
        global _TIMETABLE
        _TIMETABLE = build_timetable_from_cache(settings)
        logger.info("[기동] 타임테이블 빌드 완료 — %d항목", len(_TIMETABLE))

        # ── 타임테이블 스케줄러 기동 (10초 루프 대체 — 시간표 기반 보완) ──
        await _timetable_startup_scan()
        # WS 구독 상태 초기화는 engine_loop.run_engine_loop()에서 WS 연결 이전에 수행됨
        # (표준 기동 순서: 초기화 → 연결 → 구독). 여기서 중복 호출 제거 — 경쟁 조건 방지 (P22).
    except Exception as e:
        logger.warning("[스케줄] 타이머 초기 예약 실패: %s", e)


async def stop_daily_time_scheduler() -> None:
    """타임스케줄러를 중지하는 함수 — 모든 타이머 취소."""
    # 모든 타이머 취소
    for handle in engine_state.state.auto_trade_timer_handles:
        handle.cancel()
    engine_state.state.auto_trade_timer_handles.clear()
    if engine_state.state.midnight_timer_handle is not None:
        engine_state.state.midnight_timer_handle.cancel()
        engine_state.state.midnight_timer_handle = None
    # ── 타임테이블 타이머 취소 (10초 루프 대체) ──
    if engine_state.state.timetable_timer_handle is not None:
        engine_state.state.timetable_timer_handle.cancel()
        engine_state.state.timetable_timer_handle = None
    logger.info("[스케줄] 중지")
