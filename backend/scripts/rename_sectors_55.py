# -*- coding: utf-8 -*-
"""
업종명 정비 스크립트 — 55개 업종 중 9개 이름을 한국 주식시장 일반 용어로 변경.

인터넷 검색으로 확인한 KRX/FICS 공식 업종명 및 테마주 용어 기반.
대상 테이블: sectors, custom_sectors, master_stocks_table.sector
"""
import sqlite3

DB_PATH = "backend/data/stocks.db"

RENAMES = [
    ("건설/강관·철강재", "강관/철강재"),
    ("리빙/인테리어", "생활가전/리빙"),
    ("바이오의약품(CMO/CDMO)", "바이오의약품"),
    ("인프라/네트워크", "네트워크인프라"),
    ("자동차부품·전장·차체", "자동차부품"),
    ("전력/에너지부품", "전선·케이블"),
    ("종합건설·SOC·플랜트", "건설"),
    ("플랫폼·콘텐츠·방송미디어", "K-콘텐츠/미디어"),
    ("서비스·광고·교육", "서비스업"),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for old, new in RENAMES:
        c.execute("UPDATE master_stocks_table SET sector = ? WHERE sector = ?", (new, old))
        c.execute("UPDATE custom_sectors SET name = ? WHERE name = ?", (new, old))
        c.execute("UPDATE sectors SET name = ? WHERE name = ?", (new, old))
        print(f"  {old} → {new}")
    conn.commit()
    conn.close()
    print("완료.")


if __name__ == "__main__":
    main()
