# -*- coding: utf-8 -*-
"""
업종 데이터 인프라

- ka10101: 업종코드 목록 조회 (코스피/코스닥)
- ka10099: 적격 종목코드 수집 + 부적격 필터
- JSON 캐시 저장/로드 (backend/data/eligible_stocks_cache.json)
- 앱 기동 시 자동 실행, 일 1회 갱신

주의: ka10101/ka10099 실제 응답 필드명이 키움AI 답변과 다를 수 있음.
      첫 호출 시 응답 전체를 로그에 남기고, 파싱 실패해도 앱이 죽지 않게 방어.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.core.trading_calendar import is_cache_valid, current_trading_date_str

if TYPE_CHECKING:
    from app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)

# 캐시 파일 경로
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
ELIGIBLE_STOCKS_CACHE_PATH = _CACHE_DIR / "eligible_stocks_cache.json"
REAL_INDUSTRY_CODES_CACHE_PATH = _CACHE_DIR / "real_industry_codes_cache.json"

# ── 메모리 캐시 ──────────────────────────────────────────────────────────
# {종목코드(6자리): ""} — 키(종목코드)만 의미 있음, 값은 항상 빈 문자열
_eligible_stock_codes: dict[str, str] = {}

# 실제 키움 업종코드 -- ka10010 응답 기반
# [(실제업종코드, 업종명, 시장구분)]  예: [("001", "종합(KOSPI)", "0"), ("002", "대형주", "0"), ...]
_real_industry_codes: list[tuple[str, str, str]] = []

# 업종명 → 실제 업종코드 역매핑 (WS 0U 구독용)
# {"전기전자": "013", "건설업": "024", ...}
_industry_name_to_real_code: dict[str, str] = {}


# ── 캐시 저장/로드 ───────────────────────────────────────────────────────



def load_eligible_stocks_cache() -> Optional[dict[str, str]]:
    """
    캐시 파일에서 적격 종목코드 맵 로드.
    캐시가 당일 것이면 반환, 아니면 None (갱신 필요).
    """
    try:
        if not ELIGIBLE_STOCKS_CACHE_PATH.exists():
            return None
        raw = json.loads(ELIGIBLE_STOCKS_CACHE_PATH.read_text(encoding="utf-8"))
        cached_date = raw.get("date", "")
        if not is_cache_valid(cached_date):
            _log.info("[매매적격종목] 저장데이터 만료 (cached=%s) -- 갱신 필요", cached_date)
            return None
        data = raw.get("data")
        if not isinstance(data, dict) or not data:
            return None
        _log.info("[매매적격종목] 저장데이터 로드 -- %d종목", len(data))
        return data
    except Exception as e:
        _log.warning("[매매적격종목] 저장데이터 로드 실패: %s", e)
        return None


def save_eligible_stocks_cache(data: dict[str, str]) -> None:
    """적격 종목코드 맵을 JSON 캐시로 저장."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"date": current_trading_date_str(), "data": data}
        ELIGIBLE_STOCKS_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        _log.info("[매매적격종목] 저장완료 -- %d종목 (%s)", len(data), ELIGIBLE_STOCKS_CACHE_PATH.name)
    except Exception as e:
        _log.warning("[매매적격종목] 저장실패: %s", e)


# ── 실제 업종코드 캐시 (ka10010 기반) ────────────────────────────────────


def load_real_industry_codes_cache() -> Optional[list[tuple[str, str, str]]]:
    """실제 업종코드 캐시 로드. 당일 것이면 반환, 아니면 None."""
    try:
        if not REAL_INDUSTRY_CODES_CACHE_PATH.exists():
            return None
        raw = json.loads(REAL_INDUSTRY_CODES_CACHE_PATH.read_text(encoding="utf-8"))
        if not is_cache_valid(raw.get("date", "")):
            return None
        items = raw.get("data")
        if not isinstance(items, list) or not items:
            return None
        result = [(str(r[0]), str(r[1]), str(r[2])) for r in items if len(r) >= 3]
        _log.info("[실제업종코드] 저장데이터 로드 -- %d개", len(result))
        return result
    except Exception as e:
        _log.warning("[실제업종코드] 저장데이터 로드 실패: %s", e)
        return None


def save_real_industry_codes_cache(data: list[tuple[str, str, str]]) -> None:
    """실제 업종코드 목록을 JSON 캐시로 저장."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"date": current_trading_date_str(), "data": data}
        REAL_INDUSTRY_CODES_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        _log.info("[실제업종코드] 저장완료 -- %d개", len(data))
    except Exception as e:
        _log.warning("[실제업종코드] 저장실패: %s", e)


# ── 실제 업종코드 (하드코딩) ──────────────────────────────────────────────
#
# ka10010은 stk_cd(종목코드)가 필수 파라미터라 업종코드 목록 조회용으로 사용 불가.
# (에러 1511: 필수입력 파라미터=stk_cd)
# 키움 공식 업종코드를 하드코딩하여 WS 0U 구독에 사용한다.
# 출처: 키움증권 업종분류 (코스피 약 28개, 코스닥 약 19개)

_KOSPI_INDUSTRY_CODES: list[tuple[str, str]] = [
    ("001", "종합(KOSPI)"),
    ("002", "대형주"),
    ("003", "중형주"),
    ("004", "소형주"),
    ("005", "음식료품"),
    ("006", "섬유의복"),
    ("007", "종이목재"),
    ("008", "화학"),
    ("009", "의약품"),
    ("010", "비금속광물"),
    ("011", "철강금속"),
    ("012", "기계"),
    ("013", "전기전자"),
    ("014", "의료정밀"),
    ("015", "운수장비"),
    ("016", "유통업"),
    ("017", "전기가스업"),
    ("018", "건설업"),
    ("019", "운수창고업"),
    ("020", "통신업"),
    ("021", "금융업"),
    ("022", "은행"),
    ("024", "증권"),
    ("025", "보험"),
    ("026", "서비스업"),
    ("027", "제조업"),
    ("028", "KRX 100"),
    ("029", "KOSPI 200"),
]

_KOSDAQ_INDUSTRY_CODES: list[tuple[str, str]] = [
    ("101", "종합(KOSDAQ)"),
    ("116", "제조"),
    ("117", "건설"),
    ("118", "유통"),
    ("119", "운송"),
    ("120", "금융"),
    ("123", "통신방송서비스"),
    ("124", "IT S/W & SVC"),
    ("125", "IT H/W"),
    ("126", "음식료·담배"),
    ("127", "섬유·의류"),
    ("128", "종이·목재"),
    ("129", "출판·매체복제"),
    ("130", "화학"),
    ("131", "제약"),
    ("132", "비금속"),
    ("133", "금속"),
    ("134", "기계·장비"),
    ("135", "일반전기전자"),
    ("136", "의료·정밀기기"),
    ("137", "운송장비·부품"),
    ("138", "기타제조"),
    ("139", "통신서비스"),
    ("140", "방송서비스"),
    ("141", "인터넷"),
    ("142", "디지털컨텐츠"),
    ("143", "소프트웨어"),
    ("144", "컴퓨터서비스"),
    ("145", "반도체"),
    ("146", "IT부품"),
    ("147", "정보기기"),
    ("148", "기타서비스"),
    ("149", "오락·문화"),
]


def get_hardcoded_industry_codes() -> list[tuple[str, str, str]]:
    """
    키움 공식 업종코드 하드코딩 목록 반환.
    반환: [(업종코드, 업종명, 시장구분), ...]
    시장구분: "0"=코스피, "1"=코스닥
    """
    result: list[tuple[str, str, str]] = []
    for code, name in _KOSPI_INDUSTRY_CODES:
        result.append((code, name, "0"))
    for code, name in _KOSDAQ_INDUSTRY_CODES:
        result.append((code, name, "1"))
    _log.info("[실제업종코드] 하드코딩 -- 코스피 %d개 + 코스닥 %d개 = %d개",
              len(_KOSPI_INDUSTRY_CODES), len(_KOSDAQ_INDUSTRY_CODES), len(result))
    return result


def _normalize_industry_name(name: str) -> str:
    """업종명 정규화 — 공백·특수문자·중점(·) 제거, 소문자 변환."""
    import re
    s = str(name).strip()
    # 괄호 안 내용 제거: "종합(KOSPI)" → "종합"
    s = re.sub(r"\([^)]*\)", "", s)
    # 공백·특수문자·중점 제거
    s = re.sub(r"[\s·/&\-_,.]", "", s)
    return s.lower()


# ka10099 업종명 → 하드코딩 업종명 수동 별칭 테이블
# ka10099 응답의 업종명이 하드코딩과 미세하게 다를 때 보정.
# 키: ka10099 업종명(정규화 전 원본), 값: 하드코딩/ka10101 업종명(정확 일치 대상)
# ka10099 upName과 ka10101 name은 명명 체계가 다를 수 있음 (키움 공식 안내)
# ka10101 서버 데이터가 주력이므로, 서버 업종명이 들어오면 자동 매칭됨.
# 이 별칭은 하드코딩 비상 폴백 시 + ka10099↔ka10101 명칭 차이 보정용.
_INDUSTRY_NAME_ALIASES: dict[str, str] = {
    # ── 미매칭 6개 섹터 (ka10099 upName → 하드코딩 업종명) ──
    "일반서비스": "서비스업",
    "IT 서비스": "서비스업",
    "전기/가스": "전기가스업",
    "운송/창고": "운수창고업",
    "통신": "통신업",
    # "부동산"은 하드코딩에 없음 — ka10101 서버 데이터에 있을 수 있음

    # ── 기존 별칭 (ka10099 응답 변형 대응) ──
    "전기,전자": "전기전자",
    "전기·전자": "전기전자",
    "전기/전자": "전기전자",
    "의료정밀": "의료정밀",
    "섬유,의복": "섬유의복",
    "섬유·의복": "섬유의복",
    "섬유/의류": "섬유의복",
    "종이,목재": "종이목재",
    "종이·목재": "종이목재",
    "종이/목재": "종이목재",
    "음식료": "음식료품",
    "음식료/담배": "음식료품",
    "비금속": "비금속광물",
    "철강,금속": "철강금속",
    "철강·금속": "철강금속",
    "운수장비": "운수장비",
    "운송장비/부품": "운수장비",
    "전기가스": "전기가스업",
    "운수창고": "운수창고업",
    "기계/장비": "기계",
    "의료/정밀기기": "의료정밀",
    "오락/문화": "오락·문화",
    "출판/매체복제": "출판·매체복제",

    # ── 코스닥 영문 변형 ──
    "IT SW & SVC": "IT S/W & SVC",
    "IT HW": "IT H/W",
    "ITSW&SVC": "IT S/W & SVC",
    "ITHW": "IT H/W",
}


def _build_name_to_real_code_map(
    real_codes: list[tuple[str, str, str]],
) -> dict[str, str]:
    """
    실제 업종코드 목록에서 {업종명: 실제업종코드} 역매핑 구축.
    동일 업종명이 코스피/코스닥에 모두 있을 수 있으므로 코스피 우선.

    정확 일치 외에 정규화 매칭도 지원:
      1) 정확 일치 (원본 업종명)
      2) 별칭 테이블 (_INDUSTRY_NAME_ALIASES)
      3) 정규화 매칭 (공백·특수문자 제거 후 비교)
    """
    name_map: dict[str, str] = {}
    # 코스닥 먼저 넣고 코스피로 덮어쓰기 (코스피 우선)
    for inds_cd, inds_nm, mrkt_tp in sorted(real_codes, key=lambda x: x[2], reverse=True):
        name_map[inds_nm] = inds_cd
    return name_map


def resolve_industry_name_to_real_code(sector_name: str) -> str:
    """
    섹터명(ka10099 업종명)을 실제 업종코드로 변환.
    매칭 순서:
      1) 정확 일치
      2) 별칭 테이블
      3) 정규화 매칭 (공백·특수문자 제거 후 비교)
    실패 시 빈 문자열.
    """
    # 1) 정확 일치
    code = _industry_name_to_real_code.get(sector_name, "")
    if code:
        return code

    # 2) 별칭 테이블
    alias = _INDUSTRY_NAME_ALIASES.get(sector_name, "")
    if alias:
        code = _industry_name_to_real_code.get(alias, "")
        if code:
            return code

    # 3) 정규화 매칭
    norm_target = _normalize_industry_name(sector_name)
    if not norm_target:
        return ""
    for real_name, real_code in _industry_name_to_real_code.items():
        if _normalize_industry_name(real_name) == norm_target:
            return real_code

    _log.warning("[업종매칭] 미매칭 섹터: %r -- 별칭 테이블 추가 필요", sector_name)
    return ""


# ── ka10099 종목→업종명 맵 구축 ──────────────────────────────────────────


def fetch_ka10099_eligible_stocks(api: "KiwoomRestAPI") -> dict[str, str]:
    """
    ka10099 — 시장별 전체 종목 리스트에서 적격 종목코드 수집 + 부적격 필터.
    코스피(mrkt_tp='0') + 코스닥(mrkt_tp='10') 각각 호출.
    반환: {6자리 종목코드: ""} — 값은 빈 문자열, 키(종목코드)만 의미 있음.
    업종명은 sector_custom.json이 유일한 출처이므로 여기서 파싱하지 않음.
    실패 시 빈 딕셔너리.
    """
    if not api._ensure_token():
        _log.warning("[매매적격종목] 토큰 없음 -- ka10099 조회 생략")
        return {}

    result: dict[str, str] = {}

    for mrkt_tp, mrkt_label in (("0", "코스피"), ("10", "코스닥")):
        try:
            url = f"{api.base_url.rstrip('/')}/api/dostk/stkinfo"

            resp, _ = api._call_api(url, "ka10099", {"mrkt_tp": mrkt_tp},
                                     label=f"ka10099-map/{mrkt_label}")
            if resp is None:
                continue

            data = resp.json()
            items = data.get("list") or []

            collected = 0
            filtered = 0
            filter_reasons: dict[str, int] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                cd = str(item.get("code") or "").strip().lstrip("A")
                if not cd:
                    continue
                # 알파벳 포함 여부에 따라 정규화 분기 (2024년 신규 종목코드 대응)
                if cd.isdigit():
                    c6 = cd.zfill(6)[-6:]  # 기존 숫자코드: 6자리 패딩
                else:
                    c6 = cd.upper()  # 알파벳 코드: 원문 대문자 유지

                # ── 매매 부적격 종목 필터 (입구 컷) ──────────────
                from app.core.stock_filter import is_excluded
                excluded, reason = is_excluded(item, c6)
                if excluded:
                    filtered += 1
                    filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                    continue

                result[c6] = ""
                collected += 1

            _log.info(
                "[매매적격종목] ka10099 %s -- 총 %d종목, 수집 %d, 부적격 제외 %d",
                mrkt_label, len(items), collected, filtered,
            )
            if filter_reasons:
                _log.info("[매매적격종목] %s 부적격 사유: %s", mrkt_label, filter_reasons)

            # 코스피 → 코스닥 사이 간격
            time.sleep(0.5)

        except Exception as e:
            _log.warning("[매매적격종목] ka10099 %s 예외: %s", mrkt_label, e)
            continue

    _log.info("[매매적격종목] 전체 적격 종목 -- %d종목", len(result))
    return result


# ── 통합 앱준비 ──────────────────────────────────────────────────────


def fetch_ka10101_industry_codes(api: "KiwoomRestAPI") -> list[tuple[str, str, str]]:
    """
    ka10101 — 서버 기반 업종코드+업종명 목록 조회 (키움 공식 확인: 정상 동작 API).
    코스피(mrkt_tp="0") + 코스닥(mrkt_tp="1") 각각 호출.
    반환: [(업종코드, 업종명, 시장구분), ...]
    예: [("001", "종합(KOSPI)", "0"), ("005", "음식료업", "0"), ("101", "종합(KOSDAQ)", "1"), ...]
    실패 시 빈 리스트.
    """
    result: list[tuple[str, str, str]] = []
    for mrkt_tp, label in (("0", "코스피"), ("1", "코스닥")):
        try:
            items = api.fetch_ka10101(mrkt_tp)
            if not items:
                _log.warning("[업종코드] ka10101 %s 결과 없음", label)
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code", "")).strip()
                name = str(item.get("name", "")).strip()
                market_code = str(item.get("marketCode", mrkt_tp)).strip()
                if code and name:
                    result.append((code, name, market_code))
            _log.info("[업종코드] ka10101 %s -- %d개 업종 파싱", label, len([r for r in result if r[2] == market_code]))
            time.sleep(0.5)
        except Exception as e:
            _log.warning("[업종코드] ka10101 %s 예외: %s", label, e)
            continue

    if result:
        _log.info("[업종코드] ka10101 전체 %d개 업종코드 조회 완료", len(result))
        save_real_industry_codes_cache(result)
    else:
        _log.warning("[업종코드] ka10101 전체 결과 없음 -- 하드코딩 비상 폴백 필요")
    return result


def bootstrap_industry_data(api: "KiwoomRestAPI") -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """
    앱 기동 시 호출 — 업종 데이터 인프라 초기화.
    1) 캐시가 당일 것이면 캐시 사용 (API 호출 없음)
    2) 캐시가 없거나 날짜 불일치면 API 호출 후 캐시 저장

    반환: (industry_map, industry_codes)
    - industry_map: {종목코드: 업종명}
    - industry_codes: [(업종코드, 업종명, 시장구분), ...]
    실패해도 빈 값 반환 — 앱 기동을 막지 않음.
    """
    global _eligible_stock_codes, _real_industry_codes, _industry_name_to_real_code

    # ── 적격 종목코드 (ka10099) ──────────────────────────────────────────
    map_cached = load_eligible_stocks_cache()
    if map_cached is not None:
        _eligible_stock_codes = map_cached
    else:
        try:
            map_fresh = fetch_ka10099_eligible_stocks(api)
            if map_fresh:
                _eligible_stock_codes = map_fresh
                save_eligible_stocks_cache(map_fresh)
            else:
                _log.warning("[업종부트] ka10099 매매적격종목 결과 없음 -- 맵 비어있음")
        except Exception as e:
            _log.warning("[업종부트] ka10099 실패 (앱 기동 계속): %s", e)

    # ── 실제 업종코드 (ka10101 서버 데이터 중심) — WS 0U 구독용 ────────
    # 키움 공식 답변: ka10101은 정상 동작 API. 서버 데이터를 주력으로 사용.
    real_cached = load_real_industry_codes_cache()
    if real_cached is not None:
        _real_industry_codes = real_cached
        _log.info("[업종부트] 실제업종코드 당일 저장데이터 사용 -- %d개", len(real_cached))
    else:
        ka10101_result = fetch_ka10101_industry_codes(api)
        if ka10101_result:
            _real_industry_codes = ka10101_result
            _log.info("[업종부트] ka10101 서버 데이터 사용 -- %d개", len(ka10101_result))
        else:
            _real_industry_codes = get_hardcoded_industry_codes()
            _log.warning("[업종부트] ka10101 실패 → 하드코딩 비상 폴백 -- %d개", len(_real_industry_codes))

    # ── 업종명→실제코드 역매핑 구축 ──────────────────────────────────────
    if _real_industry_codes:
        _industry_name_to_real_code = _build_name_to_real_code_map(_real_industry_codes)
        _log.info("[업종부트] 업종명→실제코드 역매핑 -- %d개", len(_industry_name_to_real_code))

    _log.info(
        "[업종부트] 초기화 완료 -- 실제업종코드 %d개, 종목 %d종목",
        len(_real_industry_codes), len(_eligible_stock_codes),
    )
    return dict(_eligible_stock_codes), list([])


def refresh_industry_data(api: "KiwoomRestAPI") -> None:
    """
    일일 갱신용 — 캐시 무시하고 API 강제 호출 후 캐시 덮어쓰기.
    daily_time_scheduler에서 호출.
    """
    global _eligible_stock_codes, _real_industry_codes, _industry_name_to_real_code

    try:
        map_fresh = fetch_ka10099_eligible_stocks(api)
        if map_fresh:
            _eligible_stock_codes = map_fresh
            save_eligible_stocks_cache(map_fresh)
    except Exception as e:
        _log.warning("[업종갱신] ka10099 실패: %s", e)

    # 실제 업종코드 — ka10101 서버 데이터 중심, 네트워크 장애 시 하드코딩 비상 폴백
    ka10101_result = fetch_ka10101_industry_codes(api)
    if ka10101_result:
        _real_industry_codes = ka10101_result
        _log.info("[업종갱신] ka10101 서버 데이터 사용 -- %d개", len(ka10101_result))
    else:
        _real_industry_codes = get_hardcoded_industry_codes()
        _log.warning("[업종갱신] ka10101 실패 → 하드코딩 비상 폴백 -- %d개", len(_real_industry_codes))
    _industry_name_to_real_code = _build_name_to_real_code_map(_real_industry_codes)

    _log.info(
        "[업종갱신] 완료 -- 실제업종코드 %d개, 종목 %d종목",
        len(_real_industry_codes), len(_eligible_stock_codes),
    )


# ── 게터 ─────────────────────────────────────────────────────────────────


def get_eligible_stocks() -> dict[str, str]:
    """현재 메모리의 {종목코드: ""} 맵 복사본 반환. 키(종목코드)만 의미 있음."""
    return dict(_eligible_stock_codes)


def get_real_industry_codes() -> list[tuple[str, str, str]]:
    """현재 메모리의 실제 업종코드 [(실제업종코드, 업종명, 시장구분)] 복사본 반환."""
    return list(_real_industry_codes)


def get_industry_name_to_real_code() -> dict[str, str]:
    """현재 메모리의 {업종명: 실제업종코드} 역매핑 복사본 반환."""
    return dict(_industry_name_to_real_code)


def get_real_industry_code_list() -> list[str]:
    """WS 0U 구독용 실제 업종코드 리스트 반환 (중복 제거)."""
    seen: set[str] = set()
    result: list[str] = []
    for inds_cd, _nm, _mrkt in _real_industry_codes:
        if inds_cd not in seen:
            seen.add(inds_cd)
            result.append(inds_cd)
    return result


def get_real_code_for_industry_name(name: str) -> str:
    """업종명으로 실제 업종코드 조회. 없으면 빈 문자열."""
    return _industry_name_to_real_code.get(name, "")
