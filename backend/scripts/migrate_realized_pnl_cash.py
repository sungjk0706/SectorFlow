# -*- coding: utf-8 -*-
"""
trades 테이블 SELL 레코드 realized_pnl/pnl_rate 현금 기준 마이그레이션 스크립트.

기존: realized_pnl = (price - avg_buy_price) * qty  (순수 차익, 수수료/세금 제외)
      pnl_rate    = realized_pnl / (avg_buy_price * qty) * 100

변경: realized_pnl = total_amt - buy_total_amt  (현금 기준, 수수료/세금 포함)
      pnl_rate    = realized_pnl / buy_total_amt * 100

대상: trades 테이블 SELL 레코드 전체 (avg_buy_price > 0 AND buy_total_amt > 0).
      유령 데이터/0매입 레코드는 제외 (trade_history.py record_sell 안전장치와 동일 기준).

특성:
  - idempotent (멱등): 이미 현금 기준인 레코드는 재실행해도 동일값.
  - 스키마 변경 없음: UPDATE만 수행, DDL 없음.
  - 모드 무관 (P18): trade_mode 분기 없이 동일 적용.

실행 전 백업 필수 (stocks.db.{timestamp}.backup).
"""
import sqlite3
import sys

DB_PATH = "backend/data/stocks.db"


def migrate() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        # 대상 레코드 조회
        cur.execute(
            "SELECT id, total_amt, buy_total_amt FROM trades "
            "WHERE side='SELL' AND avg_buy_price > 0 AND buy_total_amt > 0"
        )
        rows = cur.fetchall()
        print(f"[마이그레이션] 대상 SELL 레코드: {len(rows)}건")

        if not rows:
            print("[마이그레이션] 갱신 대상 없음. 종료.")
            return

        updated = 0
        for rec_id, total_amt, buy_total_amt in rows:
            realized_pnl = total_amt - buy_total_amt
            pnl_rate = round(realized_pnl / buy_total_amt * 100, 2) if buy_total_amt > 0 else 0.0
            cur.execute(
                "UPDATE trades SET realized_pnl=?, pnl_rate=? WHERE id=?",
                (realized_pnl, pnl_rate, rec_id),
            )
            updated += 1

        conn.commit()
        print(f"[마이그레이션] 갱신 완료: {updated}건 (현금 기준)")
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"[마이그레이션] DB: {DB_PATH}")
    migrate()
    print("[마이그레이션] 완료.")
