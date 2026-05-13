# -*- coding: utf-8 -*-
"""
업종별 종목 레이아웃 + KRX 스냅샷 캐시.

앱 기동 시 캐시를 먼저 로드해서 UI를 즉시 표시하고,
이후 백그라운드에서 ka10095 최신 데이터로 갱신한다.

캐시 파일:
  - sector_layout_cache.json : _sector_stock_layout (업종별 종목 배치)
  - confirmed_snapshot_cache.json : 전종목 확정 시세 스냅샷 (종목코드, 시세 상세)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.trading_calendar import is_cache_valid, current_trading_date_str

_log = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
LAYOUT_CACHE_PATH = _CACHE_DIR / "sector_layout_cache.json"
SNAPSHOT_CACHE_PATH = _CACHE_DIR / "confirmed_snapshot_cache.json"
STOCK_NAME_CACHE_PATH = _CACHE_DIR / "stock_name_cache.json"
PROGRESS_CACHE_PATH = _CACHE_DIR / "confirmed_download_progress.json"
RESUME_DATA_CACHE_PATH = _CACHE_DIR / "confirmed_resume_data.json"


# ── sector_stock_layout 캐시 ─────────────────────────────────────────────

def save_layout_cache(layout: list[tuple[str, str]]) -> None:
    """업종별 종목 레이아웃을 JSON 캐시로 저장."""
    try:
        payload = {
            "date": current_trading_date_str(),
            "data": layout,  # [("sector", "반도체"), ("code", "005930"), ...]
        }
        LAYOUT_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        count = sum(1 for t, _ in layout if t == "code")
        _log.info("[layout_cache] 저장 완료 -- %d종목", count)
    except Exception as e:
        _log.warning("[layout_cache] 저장 실패: %s", e)


def load_layout_cache() -> list[tuple[str, str]] | None:
    """다음 거래일 NXT 장마감(20:00)까지 유효하면 레이아웃 반환, 아니면 None."""
    if not LAYOUT_CACHE_PATH.is_file():
        return None
    try:
        raw = json.loads(LAYOUT_CACHE_PATH.read_text(encoding="utf-8"))
        if not is_cache_valid(raw.get("date", "")):
            _log.info("[layout_cache] 날짜 만료 (cached=%s)", raw.get("date"))
            return None
        data = raw.get("data")
        if not isinstance(data, list) or not data:
            return None
        result = [(str(t), str(v)) for t, v in data]
        count = sum(1 for t, _ in result if t == "code")
        _log.debug("[layout_cache] 로드 완료 -- %d종목", count)
        return result
    except Exception as e:
        _log.warning("[layout_cache] 로드 실패: %s", e)
        return None


# ── sector_stock_layout 유틸리티 ──────────────────────────────────────────


def find_sector_for_code(
    stock_code: str, layout: list[tuple[str, str]]
) -> str:
    """
    sector_stock_layout에서 특정 종목코드가 속한 섹터 헤더를 찾는다.
    종목코드 위치에서 위로 올라가며 가장 가까운 ("sector", ...) 항목을 반환.
    찾지 못하면 빈 문자열 반환.
    """
    target = ("code", stock_code)
    try:
        idx = layout.index(target)
    except ValueError:
        return ""
    for i in range(idx - 1, -1, -1):
        kind, val = layout[i]
        if kind == "sector":
            return val
    return ""


# ── KRX 스냅샷 캐시 ─────────────────────────────────────────────────────

def save_snapshot_cache(rows: list[tuple[str, dict]]) -> None:
    """ka10095 스냅샷 결과를 JSON 캐시로 저장."""
    try:
        serializable = []
        for stk_cd, detail in rows:
            serializable.append({"code": stk_cd, "detail": detail})
        payload = {
            "date": current_trading_date_str(),
            "count": len(serializable),
            "data": serializable,
        }
        SNAPSHOT_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        _log.info("[snapshot_cache] 저장 완료 -- %d종목", len(serializable))
    except Exception as e:
        _log.warning("[snapshot_cache] 저장 실패: %s", e)


def load_snapshot_cache() -> list[tuple[str, dict]] | None:
    """당일 캐시가 유효하면 [(종목코드, detail)] 반환, 아니면 None."""
    if not SNAPSHOT_CACHE_PATH.is_file():
        return None
    try:
        raw = json.loads(SNAPSHOT_CACHE_PATH.read_text(encoding="utf-8"))
        if not is_cache_valid(raw.get("date", "")):
            _log.info("[snapshot_cache] 날짜 만료 (cached=%s)", raw.get("date"))
            return None
        data = raw.get("data")
        if not isinstance(data, list) or not data:
            return None
        result = [(str(item["code"]), dict(item["detail"])) for item in data]
        _log.debug("[snapshot_cache] 로드 완료 -- %d종목", len(result))
        return result
    except Exception as e:
        _log.warning("[snapshot_cache] 로드 실패: %s", e)
        return None


def load_completed_stocks_from_snapshot(completed_codes: set[str]) -> dict[str, dict]:
    """
    완료된 종목 코드들에 해당하는 데이터를 복원.

    우선순위:
    1. confirmed_resume_data.json (다운로드 중 20종목마다 저장된 임시 데이터)
    2. confirmed_snapshot_cache.json (이전 완전 완료 세션의 데이터)

    Args:
        completed_codes: 완료된 종목 코드 set

    Returns:
        {종목코드: detail} dict (찾지 못한 종목은 제외)
    """
    if not completed_codes:
        return {}

    # 1순위: 임시 resume data 파일 (이번 세션에서 20종목마다 저장한 실제 데이터)
    if RESUME_DATA_CACHE_PATH.is_file():
        try:
            raw = json.loads(RESUME_DATA_CACHE_PATH.read_text(encoding="utf-8"))
            data: dict = raw.get("data", {})
            if data:
                result = {cd: detail for cd, detail in data.items() if cd in completed_codes}
                found = len(result)
                missing = len(completed_codes) - found
                if missing > 0:
                    _log.warning("[resume] resume_data에서 %d종목 누락 (완료 목록 %d종목 중 %d종목 복원)", missing, len(completed_codes), found)
                else:
                    _log.info("[resume] 완료된 %d종목 데이터 resume_data에서 복원 완료", found)
                return result
        except Exception as e:
            _log.warning("[resume] resume_data 로드 실패: %s", e)

    # 2순위: 기존 snapshot_cache (이전 완전 완료 세션)
    snapshot = load_snapshot_cache()
    if not snapshot:
        _log.warning("[resume] snapshot_cache 없음 -- 완료된 %d종목 데이터 복원 불가", len(completed_codes))
        return {}

    result: dict[str, dict] = {}
    for code, detail in snapshot:
        if code in completed_codes:
            result[code] = detail

    found = len(result)
    missing = len(completed_codes) - found
    if missing > 0:
        _log.warning("[resume] snapshot에서 %d종목 누락 (완료 목록 %d종목 중 %d종목 복원)", missing, len(completed_codes), found)
    else:
        _log.info("[resume] 완료된 %d종목 데이터 snapshot에서 복원 완료", found)

    return result


# ── 시장구분 + NXT 캐시 ──────────────────────────────────────────────────

MARKET_MAP_CACHE_PATH = _CACHE_DIR / "market_map_cache.json"


def save_market_map_cache(market_map: dict[str, str], nxt_map: dict[str, bool]) -> None:
    """시장구분 + NXT 중복상장 맵을 JSON 캐시로 저장."""
    try:
        payload = {
            "date": current_trading_date_str(),
            "market_map": market_map,
            "nxt_map": {k: v for k, v in nxt_map.items() if v},  # True만 저장 (용량 절약)
        }
        MARKET_MAP_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        total_nxt = sum(1 for v in nxt_map.values() if v)
        _log.info("[market_map_cache] 저장 완료 -- %d종목 (NXT %d)", len(market_map), total_nxt)
    except Exception as e:
        _log.warning("[market_map_cache] 저장 실패: %s", e)


def load_market_map_cache() -> tuple[dict[str, str], dict[str, bool]] | None:
    """당일 캐시가 유효하면 (market_map, nxt_map) 반환, 아니면 None."""
    if not MARKET_MAP_CACHE_PATH.is_file():
        return None
    try:
        raw = json.loads(MARKET_MAP_CACHE_PATH.read_text(encoding="utf-8"))
        if not is_cache_valid(raw.get("date", "")):
            _log.info("[market_map_cache] 날짜 만료 (cached=%s)", raw.get("date"))
            return None
        market_map = raw.get("market_map")
        nxt_true = raw.get("nxt_map", {})
        if not isinstance(market_map, dict) or not market_map:
            return None
        # nxt_map 복원: 캐시에 있는 키는 True, market_map에 있지만 캐시에 없는 키는 False
        nxt_map = {k: k in nxt_true for k in market_map}
        total_nxt = sum(1 for v in nxt_map.values() if v)
        _log.debug("[market_map_cache] 로드 완료 -- %d종목 (NXT %d)", len(market_map), total_nxt)
        return market_map, nxt_map
    except Exception as e:
        _log.warning("[market_map_cache] 로드 실패: %s", e)
        return None


# ── 종목명 매핑 캐시 (ka10099) ────────────────────────────────────────────


def save_stock_name_cache(name_map: dict[str, str]) -> None:
    """종목명 매핑을 JSON 캐시로 저장. {6자리 종목코드: 종목명}."""
    try:
        payload = {
            "date": current_trading_date_str(),
            "count": len(name_map),
            "data": name_map,
        }
        STOCK_NAME_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        _log.info("[stock_name_cache] 저장 완료 -- %d종목", len(name_map))
    except Exception as e:
        _log.warning("[stock_name_cache] 저장 실패: %s", e)


def load_stock_name_cache() -> dict[str, str] | None:
    """다음 거래일 NXT 장마감(20:00)까지 유효하면 {종목코드: 종목명} 반환, 아니면 None."""
    if not STOCK_NAME_CACHE_PATH.is_file():
        return None
    try:
        raw = json.loads(STOCK_NAME_CACHE_PATH.read_text(encoding="utf-8"))
        if not is_cache_valid(raw.get("date", "")):
            _log.info("[stock_name_cache] 날짜 만료 (cached=%s)", raw.get("date"))
            return None
        data = raw.get("data")
        if not isinstance(data, dict) or not data:
            return None
        _log.debug("[stock_name_cache] 로드 완료 -- %d종목", len(data))
        return data
    except Exception as e:
        _log.warning("[stock_name_cache] 로드 실패: %s", e)
        return None


# ── 확정 시세 다운로드 진행 파일 캐시 ──────────────────────────────────────

from app.core.trading_calendar import _next_business_date
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = None


def _parse_hm(time_str: str) -> tuple[int, int]:
    """HH:MM 문자열을 (hour, minute) 튜플로 변환."""
    try:
        parts = str(time_str).strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 7, 50  # 기본값 07:50


def _is_progress_valid(cached_date_str: str, ws_subscribe_start: str) -> bool:
    """
    진행 파일 유효성 판정.
    
    규칙: 캐시 날짜의 다음 거래일 ws_subscribe_start 시간까지 유효.
    
    예시:
      - 월 20:30 캐시 → 화 07:50까지 유효 (ws_subscribe_start="07:50")
      - 금 20:30 캐시 → 월 07:50까지 유효 (주말/공휴일 건너뜀)
    """
    if not cached_date_str:
        return False
    try:
        cached_date = datetime.strptime(cached_date_str, "%Y%m%d").date()
        next_biz = _next_business_date(cached_date)
        
        now = datetime.now(_KST) if _KST else datetime.now()
        sh, sm = _parse_hm(ws_subscribe_start)
        expiry = datetime(
            next_biz.year, next_biz.month, next_biz.day,
            sh, sm, tzinfo=_KST if _KST else None
        )
        return now < expiry
    except (ValueError, TypeError):
        return False


def save_progress_cache(
    date: str,
    completed_codes: list[str],
    all_codes: list[str],
    data: "dict[str, dict] | None" = None,
) -> None:
    """
    ka10086 다운로드 진행 상황을 저장.
    20종목마다 호출하여 중단 시 이어받기 가능.
    
    Args:
        date: 거래일 (YYYYMMDD)
        completed_codes: 완료된 종목 코드 목록
        all_codes: 전체 종목 코드 목록 (무결성 검증용)
        data: 완료된 종목의 실제 시세 데이터 {종목코드: detail}
    """
    try:
        payload = {
            "date": date,
            "total": len(all_codes),
            "completed": completed_codes,
            "codes_hash": sorted(all_codes),  # 목록 변경 감지용
        }
        PROGRESS_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        _log.warning("[progress_cache] 저장 실패: %s", e)

    if data:
        try:
            data_payload = {
                "date": date,
                "data": data,
            }
            RESUME_DATA_CACHE_PATH.write_text(
                json.dumps(data_payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            _log.warning("[resume_data] 저장 실패: %s", e)


def load_progress_cache(date: str, all_codes: list[str], ws_subscribe_start: str = "07:50") -> set[str]:
    """
    ka10086 다운로드 진행 상황을 로드.
    
    유효 기간: 다음 거래일 ws_subscribe_start 시간까지
    날짜 불일치, 목록 불일치, 만료 시 빈 set 반환.
    
    Args:
        date: 예상 거래일 (YYYYMMDD)
        all_codes: 현재 전체 종목 코드 목록
        ws_subscribe_start: 실시간 연결 시작 시간 (HH:MM)
    
    Returns:
        완료된 종목 코드 set (없으면 빈 set)
    """
    if not PROGRESS_CACHE_PATH.is_file():
        return set()
    try:
        raw = json.loads(PROGRESS_CACHE_PATH.read_text(encoding="utf-8"))
        cached_date = raw.get("date", "")
        
        # 1. 날짜 및 시간 유효성 검증
        if not _is_progress_valid(cached_date, ws_subscribe_start):
            _log.info("[progress_cache] 만료 또는 날짜 불일치 (cached=%s)", cached_date)
            return set()
        
        # 2. 종목 목록 일치 검증
        cached_hash = raw.get("codes_hash", [])
        if set(cached_hash) != set(all_codes):
            _log.info("[progress_cache] 종목 목록 불일치 (상장폐지/신규상장 발생)")
            return set()
        
        completed = raw.get("completed", [])
        _log.info("[progress_cache] 로드 완료 -- %d/%d종목", len(completed), len(all_codes))
        return set(completed)
    except Exception as e:
        _log.warning("[progress_cache] 로드 실패: %s", e)
        return set()


def clear_progress_cache() -> None:
    """다운로드 완료 후 진행 파일 및 임시 데이터 파일 삭제."""
    try:
        if PROGRESS_CACHE_PATH.is_file():
            PROGRESS_CACHE_PATH.unlink()
            _log.debug("[progress_cache] 삭제 완료")
    except Exception as e:
        _log.warning("[progress_cache] 삭제 실패: %s", e)
    try:
        if RESUME_DATA_CACHE_PATH.is_file():
            RESUME_DATA_CACHE_PATH.unlink()
            _log.debug("[resume_data] 삭제 완료")
    except Exception as e:
        _log.warning("[resume_data] 삭제 실패: %s", e)
