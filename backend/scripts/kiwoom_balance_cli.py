# -*- coding: utf-8 -*-
"""
키움 REST — 계좌평가잔고내역(kt00018) 조회 CLI

사용:
  프로젝트 루트에서:
    set PYTHONPATH=backend
    python backend/scripts/kiwoom_balance_cli.py

  또는 .env / 환경변수에 KIWOOM_APP_KEY, KIWOOM_APP_SECRET 설정.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.core.kiwoom_rest import KiwoomRestAPI  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="kt00018 계좌평가잔고내역 조회")
    p.add_argument(
        "--qry-tp",
        default="1",
        help="조회구분: 1=합산, 2=개별 (기본 1)",
    )
    p.add_argument(
        "--dmst-stex-tp",
        default="KRX",
        help="국내거래소구분: KRX, NXT 등 (기본 KRX)",
    )
    args = p.parse_args()

    s = get_settings()
    key = (os.environ.get("KIWOOM_APP_KEY") or s.KIWOOM_APP_KEY or "").strip()
    secret = (os.environ.get("KIWOOM_APP_SECRET") or s.KIWOOM_APP_SECRET or "").strip()

    if not key or not secret:
        print("KIWOOM_APP_KEY / KIWOOM_APP_SECRET 이 필요합니다 (.env 또는 환경변수).", file=sys.stderr)
        return 1

    api = KiwoomRestAPI(key, secret)
    raw = api.get_balance_detail(qry_tp=args.qry_tp, dmst_stex_tp=args.dmst_stex_tp)
    if raw is None:
        print("조회 실패 (토큰 또는 API 응답 없음). 로그를 확인하세요.", file=sys.stderr)
        return 2

    print(json.dumps(raw, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
