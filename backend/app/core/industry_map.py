# -*- coding: utf-8 -*-
"""
업종 데이터 인프라

- ka10099: 적격 종목코드 수집 + 부적격 필터
- JSON 캐시 저장/로드 (backend/data/eligible_stocks_cache.json)

주의: ka10099 실제 응답 필드명이 키움AI 답변과 다를 수 있음.
      첫 호출 시 응답 전체를 로그에 남기고, 파싱 실패해도 앱이 죽지 않게 방어.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.core.trading_calendar import is_cache_valid, current_trading_date_str

if TYPE_CHECKING:
    from app.core.kiwoom_rest import KiwoomRestAPI

_log = logging.getLogger(__name__)

# 캐시 파일 경로
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
ELIGIBLE_STOCKS_CACHE_PATH = _CACHE_DIR / "eligible_stocks_cache.json"

# ── 메모리 캐시 ──────────────────────────────────────────────────────────
# {종목코드(6자리): ""} — 키(종목코드)만 의미 있음, 값은 항상 빈 문자열
_eligible_stock_codes: dict[str, str] = {}


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


# ── ka10099 종목→업종명 맵 구축 ──────────────────────────────────────────


async def fetch_ka10099_eligible_stocks(api: "KiwoomRestAPI") -> dict[str, str]:
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
            await asyncio.sleep(0.5)

        except Exception as e:
            _log.warning("[매매적격종목] ka10099 %s 예외: %s", mrkt_label, e)
            continue

    _log.info("[매매적격종목] 전체 적격 종목 -- %d종목", len(result))
    return result


# ── 게터 ─────────────────────────────────────────────────────────────────


def get_eligible_stocks() -> dict[str, str]:
    """현재 메모리의 {종목코드: ""} 맵 복사본 반환. 키(종목코드)만 의미 있음."""
    return dict(_eligible_stock_codes)
