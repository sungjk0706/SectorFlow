# -*- coding: utf-8 -*-
"""
키움 REST — 테마 데이터 수집 CLI
  ka90001: 테마그룹 전체 목록 (연속조회로 끝까지 수신)
  ka90002: 전체 테마 구성종목

사용:
  프로젝트 루트에서:
    python backend/scripts/kiwoom_theme_cli.py

결과 파일:
  backend/data/kiwoom_theme_groups.json      ← ka90001 전체 응답
  backend/data/kiwoom_theme_stocks_all.json  ← ka90002 전체 테마 구성종목
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.settings_file import load_settings   # noqa: E402
from app.core.encryption import decrypt_value       # noqa: E402
from app.core.kiwoom_rest import KiwoomRestAPI      # noqa: E402

THEME_URL = "/api/dostk/thme"
DATA_DIR = BACKEND / "data"
CALL_INTERVAL = 0.4  # ka90002 호출 간격 (초)


def call_ka90001_all(api: KiwoomRestAPI) -> list[dict]:
    """ka90001 연속조회로 전체 테마그룹 수신."""
    url = f"{api.base_url}{THEME_URL}"
    body = {
        "qry_tp": "0",
        "stk_cd": "",
        "date_tp": "10",
        "thema_nm": "",
        "flu_pl_amt_tp": "1",
        "stex_tp": "1",
    }
    all_groups: list[dict] = []
    cont_yn = "N"
    next_key = ""
    page = 0
    while True:
        page += 1
        resp, _ = api._call_api(
            url, "ka90001", body,
            cont_yn=cont_yn, next_key=next_key,
            label=f"ka90001[page={page}]",
        )
        if resp is None:
            break
        data = resp.json()
        groups = data.get("thema_grp", [])
        all_groups.extend(groups)
        print(f"  page {page}: {len(groups)}개 수신 (누계 {len(all_groups)}개)")
        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "")
        if cont_yn != "Y" or not next_key:
            break
        time.sleep(CALL_INTERVAL)
    return all_groups


def call_ka90002(api: KiwoomRestAPI, thema_grp_cd: str) -> dict | None:
    """특정 테마그룹 구성종목 연속조회로 전체 수신."""
    url = f"{api.base_url}{THEME_URL}"
    body = {
        "date_tp": "10",
        "thema_grp_cd": thema_grp_cd,
        "stex_tp": "1",
    }
    all_stocks: list[dict] = []
    merged: dict | None = None
    cont_yn = "N"
    next_key = ""
    while True:
        resp, _ = api._call_api(
            url, "ka90002", body,
            cont_yn=cont_yn, next_key=next_key,
            label=f"ka90002[{thema_grp_cd}]",
        )
        if resp is None:
            break
        data = resp.json()
        if merged is None:
            merged = data
        stocks = data.get("thema_comp_stk", [])
        all_stocks.extend(stocks)
        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "")
        if cont_yn != "Y" or not next_key:
            break
        time.sleep(CALL_INTERVAL)
    if merged is not None:
        merged["thema_comp_stk"] = all_stocks
    return merged


def _dec(v) -> str:
    if not v:
        return ""
    s = str(v)
    return decrypt_value(s) if s.startswith("gAAAA") else s


def main() -> int:
    flat = load_settings()
    key = _dec(flat.get("kiwoom_app_key_real")) or _dec(flat.get("kiwoom_app_key"))
    secret = _dec(flat.get("kiwoom_app_secret_real")) or _dec(flat.get("kiwoom_app_secret"))

    if not key or not secret:
        print("settings.json 에서 kiwoom_app_key / kiwoom_app_secret 을 찾을 수 없습니다.", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    api = KiwoomRestAPI(key, secret)

    # ── 1단계: ka90001 테마그룹 전체 목록 (연속조회) ───────────────────────
    print("[1/2] ka90001 테마그룹 전체 목록 조회 중 (연속조회)...")
    groups = call_ka90001_all(api)
    if not groups:
        print("ka90001 응답 없음. 토큰 또는 API 오류를 확인하세요.", file=sys.stderr)
        return 2

    out_groups = DATA_DIR / "kiwoom_theme_groups.json"
    out_groups.write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  → 저장 완료: {out_groups} ({len(groups)}개)")

    # ── 2단계: ka90002 전체 테마 구성종목 ──────────────────────────────────
    print(f"\n[2/2] ka90002 구성종목 조회 중 (전체 {len(groups)}개 테마, 간격 {CALL_INTERVAL}s)...")
    target = groups

    result: list[dict] = []
    for i, grp in enumerate(target, 1):
        code = grp.get("thema_grp_cd", "")
        name = grp.get("thema_nm", "")
        data = call_ka90002(api, code)
        entry = {
            "thema_grp_cd": code,
            "thema_nm": name,
            "flu_rt": grp.get("flu_rt"),
            "dt_prft_rt": grp.get("dt_prft_rt"),
            "rising_stk_num": grp.get("rising_stk_num"),
            "fall_stk_num": grp.get("fall_stk_num"),
            "stk_num": grp.get("stk_num"),
            "main_stk": grp.get("main_stk"),
            "ka90002": data,
        }
        result.append(entry)

        stk_count = len((data or {}).get("thema_comp_stk", []))
        print(f"  [{i:3d}/{len(target)}] {name}({code}) — 종목 {stk_count}개")

        if i < len(target):
            time.sleep(CALL_INTERVAL)

    out_stocks = DATA_DIR / "kiwoom_theme_stocks_all.json"
    out_stocks.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  → 저장 완료: {out_stocks}")

    # ── 요약 출력 ────────────────────────────────────────────────────────────
    total_stocks = sum(
        len((e.get("ka90002") or {}).get("thema_comp_stk", []))
        for e in result
    )
    print("\n====== 수집 요약 ======")
    print(f"  테마그룹 수 : {len(result)}개")
    print(f"  구성종목 합계: {total_stocks}개 (중복 포함)")
    print(f"  결과 파일   : {out_groups.name}, {out_stocks.name}")

    # ka90001 필드 목록
    if groups:
        print(f"\n  [ka90001 필드] {list(groups[0].keys())}")
    # ka90002 응답 필드 목록
    for e in result:
        comp = (e.get("ka90002") or {}).get("thema_comp_stk", [])
        if comp:
            print(f"  [ka90002 구성종목 필드] {list(comp[0].keys())}")
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
