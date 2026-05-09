# -*- coding: utf-8 -*-
"""디버그 세션 NDJSON -- 프로젝트 루트 `debug-92c6a0.log` 단일 경로."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# backend/app/core -> parents[3] = SectorFlow 루트
DEBUG_SESSION_LOG_PATH = Path(__file__).resolve().parents[3] / "debug-92c6a0.log"


def append_ndjson(payload: dict) -> None:
    try:
        p = {**payload, "sessionId": "92c6a0", "timestamp": int(time.time() * 1000)}
        with open(DEBUG_SESSION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def scan_hts_63781eok_raw_text(text: str) -> dict:
    """
    HTS [0130] '63,781억' 근처에 해당할 수 있는 숫자 문자열이 원문에 있는지.
    - 63781억(원) = 6,378,100,000,000 -> '6378100000000' (13자리 이상)
    - 콤마 포함 표기 등
    """
    if not text:
        return {"empty": True}
    hits: list[str] = []
    for needle in (
        "6378100000000",  # 63,781억(원)
        "6378100000000000",
        "6,378,100,000,000",
    ):
        if needle in text:
            hits.append(needle)
    # 13자리 이상 연속 숫자 (조 단위 원 가능)
    bigs = re.findall(r"\d{13,}", text)
    over_5t = [b for b in bigs if len(b) >= 13 and int(b) >= 5_000_000_000_000]
    return {
        "needle_hits": hits,
        "digit_13plus_sample": bigs[:30],
        "count_int_ge_5e12_won": len(over_5t),
        "sample_ge_5e12": over_5t[:15],
        "len_text": len(text),
    }
