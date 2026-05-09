# -*- coding: utf-8 -*-
"""
5일 평균 거래대금 저장데이터 — 브로커 무관 범용 모듈.

캐싱 정책 (5일 롤링 윈도우):
- backend/data/avg_amt_5d_cache.json 에 날짜 태그 + 종목별 5일치 배열로 저장.
- 저장데이터 구조: { "date": "YYYYMMDD", "data": { "005930": [D-4, D-3, D-2, D-1, D+0], ... } }
- 저장데이터 날짜가 직전 영업일 이상이면 유효 → 주말/공휴일에도 저장데이터 유지.

이 모듈에는 REST API 호출이 없으며, 저장데이터 파일 I/O와 유틸리티만 포함한다.
키움 REST 호출 함수는 kiwoom_daily_avg_volume.py에 잔류한다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.trading_calendar import is_cache_valid

_log = logging.getLogger(__name__)

# ── 저장데이터 파일 경로 상수 ────────────────────────────────────────────────────
_CACHE_FILENAME = "avg_amt_5d_cache.json"
_DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / _CACHE_FILENAME

# 5일거래대금 이어받기용 임시 파일 경로
_AVG_AMT_PROGRESS_PATH = Path(__file__).resolve().parents[2] / "data" / "avg_amt_5d_progress.json"
_AVG_AMT_RESUME_PATH   = Path(__file__).resolve().parents[2] / "data" / "avg_amt_5d_resume_data.json"

# 종목 간 순차 호출 간격 -- 키움 권장 초당 3~4건 (0.3초)
KA10005_GAP_SEC = 0.3


# ── 유틸리티 ───────────────────────────────────────────────────────────────

try:
    from zoneinfo import ZoneInfo

    def _kst_today_yyyymmdd() -> str:
        from app.core.trading_calendar import current_trading_date_str
        return current_trading_date_str()

except Exception:

    def _kst_today_yyyymmdd() -> str:
        from app.core.trading_calendar import current_trading_date_str
        return current_trading_date_str()


def _norm_stk(s: str) -> str:
    """종목코드 정규화. 알파벳 포함 여부에 따라 처리 분기 (2024년 신규 종목코드 대응)."""
    t = str(s or "").strip().lstrip("A")
    if not t:
        return ""
    # 알파벳 포함 여부에 따라 정규화 분기
    if t.isdigit():
        # 기존 숫자코드: 6자리 패딩
        return t.zfill(6)[-6:]
    else:
        # 알파벳 코드: 원문 대문자 유지 (4자리 이상 체크 제거, 모든 코드 허용)
        return t.upper()


# ── 저장데이터 저장/로드 ────────────────────────────────────────────────────────

def load_avg_amt_cache(
    path: Path | None = None,
) -> tuple[dict[str, int], dict[str, int]] | None:
    """
    저장데이터가 유효하면 (avg_map, high_5d_map) 튜플 반환, 아니면 None.

    - avg_map:    {종목코드: 평균거래대금(백만원)}
    - high_5d_map: {종목코드: 5일전고점(원)}  (없으면 빈 dict)

    날짜 만료 시 None 반환 — 호출처에서 갱신 필요 여부를 판단하는 데 사용.
    """
    p = path or _DEFAULT_CACHE_PATH
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        cached_date = raw.get("date", "")
        data = raw.get("data")
        if not isinstance(data, dict):
            return None

        is_v2 = raw.get("version") == 2

        # high_5d 파싱 (v2 전용, 없으면 빈 dict)
        _h5d_raw = raw.get("high_5d")
        high_5d: dict[str, int] = {}
        if isinstance(_h5d_raw, dict):
            high_5d = {str(k): int(v) for k, v in _h5d_raw.items() if isinstance(v, (int, float))}

        if is_v2:
            if not is_cache_valid(cached_date):
                _log.info("[avg_amt_cache] 날짜 만료 -- 저장데이터 무효화 (cached=%s)", cached_date)
                return None
            result: dict[str, int] = {}
            for k, v in data.items():
                if isinstance(v, list) and v:
                    valid = [x for x in v if isinstance(x, (int, float)) and x > 0]
                    if valid:
                        result[str(k)] = int(sum(valid) / len(valid))
                elif isinstance(v, (int, float)) and v > 0:
                    result[str(k)] = int(v)
            _log.debug("[avg_amt_cache] v2 저장데이터 로드 -- %d종목, high_5d=%d (cached=%s)", len(result), len(high_5d), cached_date)
            return result, high_5d
        else:
            if not is_cache_valid(cached_date):
                _log.info("[avg_amt_cache] v1 날짜 만료 -- 저장데이터 무효화 (cached=%s)", cached_date)
                return None
            _log.debug("[avg_amt_cache] v1 레거시 저장데이터 로드 -- %d종목 (cached=%s)", len(data), cached_date)
            return {str(k): int(v) for k, v in data.items()}, high_5d
    except Exception as e:
        _log.warning("[avg_amt_cache] 저장데이터 로드 실패 -- %s", e)
        return None


def load_avg_amt_cache_v2(
    path: Path | None = None,
) -> tuple[dict[str, list[int]], dict[str, list[int]]] | None:
    """
    v2 저장데이터 원본(5일치 배열) 로드. 롤링 갱신 시 사용.
    날짜 만료 여부와 무관하게 v2 데이터가 있으면 반환.
    반환: (v2_data, high_5d_arr) 튜플 또는 None.
      - v2_data: {종목코드: [D-4, D-3, D-2, D-1, D+0]}
      - high_5d_arr: {종목코드: [5일치 고가 배열]} 또는 {} (키 없으면 빈 dict)
    """
    p = path or _DEFAULT_CACHE_PATH
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if raw.get("version") != 2:
            return None
        cached_date = raw.get("date", "")
        data = raw.get("data")
        if not isinstance(data, dict):
            return None
        result: dict[str, list[int]] = {}
        for k, v in data.items():
            if isinstance(v, list):
                result[str(k)] = [int(x) for x in v]

        # high_5d_arr 파싱 (없으면 빈 dict)
        _h5d_arr_raw = raw.get("high_5d_arr")
        high_5d_arr: dict[str, list[int]] = {}
        if isinstance(_h5d_arr_raw, dict):
            for k, v in _h5d_arr_raw.items():
                if isinstance(v, list):
                    high_5d_arr[str(k)] = [int(x) for x in v]

        if not is_cache_valid(cached_date):
            _log.info("[avg_amt_cache_v2] 날짜 만료 -- stale 로드 (cached=%s, %d종목, high_5d_arr=%d)", cached_date, len(result), len(high_5d_arr))
        else:
            _log.debug("[avg_amt_cache_v2] 로드 -- %d종목, high_5d_arr=%d (cached=%s)", len(result), len(high_5d_arr), cached_date)
        return result, high_5d_arr
    except Exception as e:
        _log.warning("[avg_amt_cache_v2] 저장데이터 로드 실패 -- %s", e)
        return None


def save_avg_amt_cache(data: dict[str, int], path: Path | None = None) -> None:
    """평균 거래대금 dict를 날짜 태그와 함께 JSON 파일로 저장. (하위 호환용)"""
    p = path or _DEFAULT_CACHE_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": _kst_today_yyyymmdd(), "data": data}
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _log.info("[avg_amt_cache] 저장완료 -- %d종목 -> %s", len(data), p)
    except Exception as e:
        _log.warning("[avg_amt_cache] 저장실패 -- %s", e)


def save_avg_amt_cache_v2(data: dict[str, list[int]], date_str: str | None = None, path: Path | None = None, *, high_5d: dict[str, int] | None = None, high_5d_arr: dict[str, list[int]] | None = None) -> None:
    """5일치 배열 캐시를 v2 형식으로 저장. 기존 데이터와 동일하면 스킵."""
    p = path or _DEFAULT_CACHE_PATH
    ds = date_str or _kst_today_yyyymmdd()
    try:
        # 기존 캐시와 비교 — 날짜·데이터 모두 동일하면 저장 스킵
        if p.is_file():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
                if existing.get("version") == 2 and existing.get("date") == ds and existing.get("data") == data:
                    # high_5d가 새로 전달되었으면 기존 캐시에 없을 수 있으므로 스킵하지 않음
                    if high_5d is None or existing.get("high_5d") == high_5d:
                        if high_5d_arr is None or existing.get("high_5d_arr") == high_5d_arr:
                            _log.info("[avg_amt_cache_v2] 데이터 동일 -- 저장 생략 (date=%s, %d종목)", ds, len(data))
                            return
            except Exception:
                pass  # 비교 실패 시 그냥 덮어쓰기
        p.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {"version": 2, "date": ds, "data": data}
        if high_5d is not None:
            payload["high_5d"] = high_5d
        else:
            # 기존 캐시에 high_5d가 있으면 보존
            if p.is_file():
                try:
                    _existing = json.loads(p.read_text(encoding="utf-8"))
                    _old_high = _existing.get("high_5d")
                    if isinstance(_old_high, dict) and _old_high:
                        payload["high_5d"] = _old_high
                except Exception:
                    pass
        if high_5d_arr is not None:
            payload["high_5d_arr"] = high_5d_arr
        else:
            # 기존 캐시에 high_5d_arr가 있으면 보존 (high_5d 보존 패턴과 동일)
            if p.is_file():
                try:
                    _existing = json.loads(p.read_text(encoding="utf-8"))
                    _old_high_arr = _existing.get("high_5d_arr")
                    if isinstance(_old_high_arr, dict) and _old_high_arr:
                        payload["high_5d_arr"] = _old_high_arr
                except Exception:
                    pass
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _h5d_count = len(payload.get("high_5d") or {})
        _h5d_arr_count = len(payload.get("high_5d_arr") or {})
        _log.info("[avg_amt_cache_v2] 저장 완료 -- %d종목, high_5d=%d, high_5d_arr=%d (date=%s) -> %s", len(data), _h5d_count, _h5d_arr_count, ds, p)
    except Exception as e:
        _log.warning("[avg_amt_cache_v2] 저장 실패 -- %s", e)


def avg_from_v2(v2_data: dict[str, list[int]]) -> dict[str, int]:
    """v2 캐시(5일치 배열)에서 평균값 dict 생성. 엔진 메모리(_avg_amt_5d) 적재용."""
    result: dict[str, int] = {}
    for k, arr in v2_data.items():
        if arr:
            result[str(k)] = int(sum(arr) / 5)
    return result


def load_high_5d_from_cache(path: Path | None = None) -> dict[str, int] | None:
    """v2 캐시 파일에서 high_5d 데이터만 로드. 없으면 None.

    DEPRECATED: load_avg_amt_cache()가 (avg_map, high_5d_map) 튜플을 반환하므로
    신규 코드에서는 load_avg_amt_cache()를 사용할 것.
    """
    p = path or _DEFAULT_CACHE_PATH
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if raw.get("version") != 2:
            return None
        h5d = raw.get("high_5d")
        if not isinstance(h5d, dict) or not h5d:
            return None
        result = {str(k): int(v) for k, v in h5d.items() if isinstance(v, (int, float))}
        _log.debug("[avg_amt_cache] high_5d 로드 -- %d종목", len(result))
        return result
    except Exception as e:
        _log.warning("[avg_amt_cache] high_5d 로드 실패 -- %s", e)
        return None


# ── v2 캐시 롤링 갱신 (ka10086 trade_amount 기반) ─────────────────────────

def rolling_update_v2_from_trade_amounts(
    existing_v2: dict[str, list[int]] | None,
    trade_amounts: dict[str, int],
    *,
    high_prices: dict[str, int] | None = None,
    high_5d_arr: dict[str, list[int]] | None = None,
    eligible_set: set[str] | None = None,
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """
    ka10086 trade_amount(원 단위) → 백만원 변환 후 v2 캐시 롤링 갱신.
    고가(high_prices) 전달 시 고가 5일 배열도 동일 패턴으로 롤링 갱신.

    - trade_amounts: {종목코드: 거래대금(원)} — ka10086 확정 조회 결과
    - existing_v2: 기존 v2 캐시 {종목코드: [D-4..D+0]} 또는 None(최초)
    - high_prices: {종목코드: 당일 고가(원)} 또는 None(고가 롤링 스킵)
    - high_5d_arr: 기존 고가 5일 배열 {종목코드: [D-4..D+0]} 또는 None(최초)
    - eligible_set: 적격종목 코드 집합 또는 None(필터 미적용, 하위 호환)
    - 반환: (updated_v2, updated_high_arr) 튜플
      - updated_v2: 갱신된 거래대금 v2 캐시 {종목코드: [최대 5일치 배열]}
      - updated_high_arr: 갱신된 고가 5일 배열 {종목코드: [최대 5일치 배열]}

    거래대금 롤링 규칙:
    - 원 → 백만원: int(amt / 1_000_000), amt_million <= 0이면 스킵
    - 기존 종목: 가장 오래된 값 제거 → 당일 값 추가 (최대 5개)
    - 신규 종목: [amt_million] 배열로 추가
    - 기존 캐시에만 있는 종목: 그대로 유지

    고가 롤링 규칙 (거래대금과 동일 패턴):
    - 고가 0 이하 스킵
    - 기존 종목: 가장 오래된 값 제거 → 당일 고가 추가 (최대 5개)
    - 신규 종목: [high_price] 배열로 추가
    - 기존 종목(당일 고가 없음): 그대로 유지
    """
    # ── 거래대금 롤링 (기존 로직 그대로) ──────────────────────────────────
    # 원 → 백만원 변환 (0 이하 스킵)
    today: dict[str, int] = {}
    for code, amt in trade_amounts.items():
        amt_million = int(amt / 1_000_000)
        if amt_million > 0:
            today[code] = amt_million

    if existing_v2 is None:
        updated_v2 = {code: [amt] for code, amt in today.items() if eligible_set is None or code in eligible_set}
    else:
        updated_v2: dict[str, list[int]] = {}

        # 기존 종목 롤링
        for code, arr in existing_v2.items():
            if eligible_set is not None and code not in eligible_set:
                continue
            today_amt = today.pop(code, 0)
            if today_amt > 0:
                new_arr = arr[1:] + [today_amt] if len(arr) >= 5 else arr + [today_amt]
                updated_v2[code] = new_arr[-5:]
            else:
                updated_v2[code] = arr

        # 신규 종목 추가
        for code, amt in today.items():
            if eligible_set is not None and code not in eligible_set:
                continue
            updated_v2[code] = [amt]

    _log.info(
        "[v2_rolling] trade_amount 기반 롤링 완료 -- 기존 %d + 신규 %d = 총 %d종목",
        len(existing_v2 or {}), len(today), len(updated_v2),
    )

    # ── 고가 롤링 ────────────────────────────────────────────────────────
    if high_prices is None:
        # 고가 롤링 스킵 — 기존 배열 그대로 반환
        return updated_v2, high_5d_arr or {}

    existing_high = high_5d_arr or {}
    # 당일 고가 필터 (0 이하 스킵)
    today_high: dict[str, int] = {
        code: hp for code, hp in high_prices.items() if hp > 0
    }

    if not existing_high:
        updated_high: dict[str, list[int]] = {
            code: [hp] for code, hp in today_high.items() if eligible_set is None or code in eligible_set
        }
    else:
        updated_high = {}

        # 기존 종목 롤링
        for code, arr in existing_high.items():
            if eligible_set is not None and code not in eligible_set:
                continue
            hp = today_high.pop(code, 0)
            if hp > 0:
                new_arr = arr[1:] + [hp] if len(arr) >= 5 else arr + [hp]
                updated_high[code] = new_arr[-5:]
            else:
                updated_high[code] = arr

        # 신규 종목 추가
        for code, hp in today_high.items():
            if eligible_set is not None and code not in eligible_set:
                continue
            updated_high[code] = [hp]

    _log.info(
        "[v2_rolling] high_price 기반 롤링 완료 -- 기존 %d + 신규 %d = 총 %d종목",
        len(existing_high), len(today_high), len(updated_high),
    )

    return updated_v2, updated_high


# ── 5일거래대금 이어받기 진행 파일 ────────────────────────────────────────

def save_avg_amt_progress(
    date: str,
    completed_codes: list[str],
    all_codes: list[str],
    v2_data: "dict[str, list[int]] | None" = None,
    high_cache: "dict[str, int] | None" = None,
    high_5d_arr: "dict[str, list[int]] | None" = None,
) -> None:
    """Chunk 완료마다 호출 — 진행 파일 + 실제 데이터 파일 저장."""
    try:
        payload = {
            "date": date,
            "total": len(all_codes),
            "completed": completed_codes,
            "codes_hash": sorted(all_codes),
        }
        _AVG_AMT_PROGRESS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        _log.warning("[avg_amt_progress] 저장 실패: %s", e)

    if v2_data is not None:
        try:
            data_payload = {
                "date": date,
                "v2_data": v2_data,
                "high_cache": high_cache or {},
                "high_5d_arr": high_5d_arr or {},
            }
            _AVG_AMT_RESUME_PATH.write_text(
                json.dumps(data_payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            _log.warning("[avg_amt_resume] 저장 실패: %s", e)


def load_avg_amt_progress(
    date: str,
    all_codes: list[str],
    ws_subscribe_start: str = "07:50",
) -> "tuple[set[str], dict[str, list[int]], dict[str, int], dict[str, list[int]]] | None":
    """
    이어받기 진행 파일 로드.

    유효 조건: 날짜 일치 + 종목 목록 일치 + 다음 거래일 ws_subscribe_start 이전.

    Returns:
        (completed_codes, v2_data, high_cache, high_5d_arr) 또는 None (이어받기 불가)
    """
    if not _AVG_AMT_PROGRESS_PATH.is_file():
        return None
    try:
        raw = json.loads(_AVG_AMT_PROGRESS_PATH.read_text(encoding="utf-8"))
        cached_date = raw.get("date", "")

        # 날짜 및 시간 유효성 검증 (sector_stock_cache._is_progress_valid와 동일 로직)
        from app.core.sector_stock_cache import _is_progress_valid
        if not _is_progress_valid(cached_date, ws_subscribe_start):
            _log.info("[avg_amt_progress] 만료 또는 날짜 불일치 (cached=%s)", cached_date)
            return None

        # 종목 목록 일치 검증
        cached_hash = raw.get("codes_hash", [])
        if set(cached_hash) != set(all_codes):
            _log.info("[avg_amt_progress] 종목 목록 불일치 (상장폐지/신규상장 발생)")
            return None

        completed = set(raw.get("completed", []))

        # 실제 데이터 로드
        v2_data: dict[str, list[int]] = {}
        high_cache: dict[str, int] = {}
        high_5d_arr: dict[str, list[int]] = {}
        if _AVG_AMT_RESUME_PATH.is_file():
            try:
                rraw = json.loads(_AVG_AMT_RESUME_PATH.read_text(encoding="utf-8"))
                v2_data   = rraw.get("v2_data", {})
                high_cache  = rraw.get("high_cache", {})
                high_5d_arr = rraw.get("high_5d_arr", {})
            except Exception as e:
                _log.warning("[avg_amt_resume] 로드 실패: %s", e)

        _log.info("[avg_amt_progress] 이어받기 로드 -- %d/%d종목 완료, 데이터 %d종목",
                  len(completed), len(all_codes), len(v2_data))
        return completed, v2_data, high_cache, high_5d_arr
    except Exception as e:
        _log.warning("[avg_amt_progress] 로드 실패: %s", e)
        return None


def clear_avg_amt_progress() -> None:
    """다운로드 완료 후 이어받기 임시 파일 삭제."""
    for p in (_AVG_AMT_PROGRESS_PATH, _AVG_AMT_RESUME_PATH):
        try:
            if p.is_file():
                p.unlink()
                _log.debug("[avg_amt_progress] 삭제 완료: %s", p.name)
        except Exception as e:
            _log.warning("[avg_amt_progress] 삭제 실패 %s: %s", p.name, e)
