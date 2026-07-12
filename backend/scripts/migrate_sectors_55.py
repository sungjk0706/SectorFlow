# -*- coding: utf-8 -*-
"""
업종 분류 69개 → 55개 마이그레이션 스크립트.
동조성 기준으로 재분류: 25개 오분류 종목 이동 + 69개 업종 → 55개 업종 병합.

대상 테이블:
  - sectors (업종 정의, name PK)
  - custom_sectors (종목→업종 원본 매핑, stock_code PK)
  - master_stocks_table (파생 sector 컬럼)

실행 전 백업 필수 (stocks.db.{timestamp}.backup).
"""
import sqlite3
import sys

DB_PATH = "backend/data/stocks.db"

# ── Phase 1: 25개 오분류 종목 이동 (code → target old sector) ──
STOCK_MOVES = [
    ("010130", "특수강/비철금속및정밀소재"),      # 고려아연: 종합제철 → 비철금속
    ("080220", "반도체/설계·IDM"),                 # 제주반도체: 반도체/부품 → 설계·IDM
    ("046890", "반도체/설계·IDM"),                 # 서울반도체: 디스플레이 → 설계·IDM
    ("012330", "자동차/전장및시스템"),             # 현대모비스: 완성차 → 부품
    ("419050", "2차전지/소재"),                    # 삼기에너지솔루션즈: 전장 → 2차전지
    ("475040", "AI및지능형소프트웨어"),            # 스트라드비젼: 전장 → AI
    ("002380", "화학/소재"),                       # KCC: 건설자재 → 화학
    ("483650", "뷰티/화장품"),                     # 달바글로벌: 화학/소재 → 뷰티
    ("000850", "일반기계"),                        # 화천기공: 건설기계 → 일반기계
    ("319400", "로봇/자동화"),                     # 현대무벡스: 일반기계 → 로봇
    ("272210", "방산/우주항공"),                   # 한화시스템: 전자부품 → 방산
    ("001820", "전자부품/시스템·모듈"),            # 삼화콘덴서: 전력부품 → 전자부품
    ("100090", "조선/해양"),                       # SK오션플랜트: 물류 → 조선
    ("008350", "특수강/비철금속및정밀소재"),      # 남선알미늄: 물류 → 비철금속
    ("012030", "지주/지배구조(금융·유통·소비재)"), # DB: 인프라 → 지주(금융·소비재)
    ("023590", "IT서비스/SI및데이터보안"),        # 다우기술: 핀테크 → IT서비스
    ("036570", "게임"),                            # NC: 플랫폼 → 게임
    ("257720", "플랫폼및콘텐츠서비스"),           # 실리콘투: 리빙 → 플랫폼
    ("214450", "바이오신약/개발"),                 # 파마리서치: 뷰티 → 바이오신약
    ("195940", "전통제약/원료"),                   # HK이노엔: 의료기기 → 전통제약
    ("196170", "바이오신약/개발"),                 # 알테오젠: 진단 → 바이오신약
    ("365660", "IT서비스/SI및데이터보안"),        # 레몬헬스케어: 진단 → IT서비스
    ("131970", "반도체/장비"),                     # 두산테스나: 전문서비스 → 반도체/장비
    ("453450", "에너지/유틸리티"),                 # 그리드위즈: 전문서비스 → 에너지
    ("089860", "리빙/인테리어"),                   # 롯데렌탈: 전문서비스 → 리빙
]

# ── Phase 2A: 단순 이름 변경 (old → new) ──
SECTOR_RENAMES = [
    ("종합제철/판재류", "종합제철/판재"),
    ("건설/산업용강관및철강재", "건설/강관·철강재"),
    ("특수강/비철금속및정밀소재", "비철금속·특수강"),
    ("건설자재및인테리어", "건설자재"),
    ("건설기계및자동화", "건설기계"),
    ("타이어및소재/고무", "타이어"),
    ("디스플레이/OLED", "디스플레이"),
    ("전자부품/시스템·모듈", "전자부품/시스템"),
    ("AI및지능형소프트웨어", "AI/소프트웨어"),
    ("IT서비스/SI및데이터보안", "IT서비스/SI"),
    ("인프라/네트워크및기타기술", "인프라/네트워크"),
    ("K-푸드수출/성장주", "K-푸드수출"),
    ("국내식품대장주", "식품/내수"),
    ("진단/헬스케어/기타", "진단/헬스케어"),
    ("여행/레저/플랫폼", "여행/레저"),
]

# ── Phase 2B: 병합 (여러 old → 하나의 new) ──
SECTOR_MERGES = [
    # (new_name, [old_names...])
    ("반도체/소재·부품", ["반도체/소재", "반도체/부품"]),
    ("종합건설·SOC·플랜트", ["종합건설/디벨로퍼", "SOC/토목인프라", "플랜트/엔지니어링/설비"]),
    ("자동차부품·전장·차체", ["자동차/전장및시스템", "차체/구동/부품제조"]),
    ("플랫폼·콘텐츠·방송미디어", ["플랫폼및콘텐츠서비스", "방송/미디어"]),
    ("은행·보험·금융지주", ["은행/금융지주", "보험"]),
    ("지주(금융·소비재)", ["지주/지배구조(금융·유통·소비재)", "기타특수지주사"]),
    ("지주(산업·에너지)", ["지주/지배구조(산업/철강/중공업)", "지주/지배구조(종합/에너지/전기전자)"]),
    ("유통·물류·종합상사", ["유통/리테일", "물류/지주및기타", "산업재/종합상사"]),
    ("고무·플라스틱·종이·목재", ["고무/플라스틱", "종이/목재"]),
    ("식품소재·농업·사료", ["식품소재/기술주", "농업/사료"]),
    ("서비스·광고·교육", ["전문서비스", "광고/마케팅", "교육/출판"]),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    c = conn.cursor()

    try:
        # ── 사전 검증: 종목 수 ──
        c.execute("SELECT COUNT(*) FROM master_stocks_table")
        total_before = c.fetchone()[0]
        print(f"[사전] 종목 수: {total_before}")

        c.execute("SELECT COUNT(DISTINCT sector) FROM master_stocks_table WHERE sector IS NOT NULL AND sector != '' AND sector != '미분류'")
        sectors_before = c.fetchone()[0]
        print(f"[사전] 업종 수: {sectors_before}")

        # ── Phase 1: 25개 종목 이동 ──
        print("\n=== Phase 1: 25개 오분류 종목 이동 ===")
        moved = 0
        for code, target_sector in STOCK_MOVES:
            # master_stocks_table 업데이트
            c.execute("UPDATE master_stocks_table SET sector = ? WHERE code = ?", (target_sector, code))
            rows_affected = c.rowcount
            if rows_affected > 0:
                # custom_sectors 업데이트 (존재하는 경우)
                c.execute("UPDATE custom_sectors SET name = ? WHERE stock_code = ?", (target_sector, code))
                moved += 1
                # 종목명 조회 for logging
                c.execute("SELECT name FROM master_stocks_table WHERE code = ?", (code,))
                name_row = c.fetchone()
                name = name_row[0] if name_row else "?"
                print(f"  {code} {name} → {target_sector}")
            else:
                print(f"  WARNING: {code} not found in master_stocks_table")
        print(f"Phase 1 완료: {moved}개 종목 이동")

        # ── Phase 2B: 병합 (먼저 실행 — 여러 old를 하나의 new로) ──
        print("\n=== Phase 2B: 업종 병합 ===")
        merged_count = 0
        for new_name, old_names in SECTOR_MERGES:
            for old_name in old_names:
                # master_stocks_table
                c.execute("UPDATE master_stocks_table SET sector = ? WHERE sector = ?", (new_name, old_name))
                mst_rows = c.rowcount
                # custom_sectors
                c.execute("UPDATE custom_sectors SET name = ? WHERE name = ?", (new_name, old_name))
                cs_rows = c.rowcount
                # sectors 테이블에서 old 삭제
                c.execute("DELETE FROM sectors WHERE name = ?", (old_name,))
                print(f"  {old_name} → {new_name} (master: {mst_rows}, custom: {cs_rows})")
                merged_count += 1
            # new_name이 sectors에 없으면 추가
            c.execute("INSERT OR IGNORE INTO sectors (name) VALUES (?)", (new_name,))
            print(f"  → sectors에 '{new_name}' 등록")
        print(f"Phase 2B 완료: {merged_count}개 old 업종 병합")

        # ── Phase 2A: 단순 이름 변경 ──
        print("\n=== Phase 2A: 업종 이름 변경 ===")
        renamed = 0
        for old_name, new_name in SECTOR_RENAMES:
            # master_stocks_table
            c.execute("UPDATE master_stocks_table SET sector = ? WHERE sector = ?", (new_name, old_name))
            mst_rows = c.rowcount
            # custom_sectors
            c.execute("UPDATE custom_sectors SET name = ? WHERE name = ?", (new_name, old_name))
            cs_rows = c.rowcount
            # sectors 테이블 이름 변경
            c.execute("UPDATE sectors SET name = ? WHERE name = ?", (new_name, old_name))
            print(f"  {old_name} → {new_name} (master: {mst_rows}, custom: {cs_rows})")
            renamed += 1
        print(f"Phase 2A 완료: {renamed}개 업종 이름 변경")

        # ── 커밋 ──
        conn.commit()
        print("\n[커밋 완료]")

        # ── 사후 검증 ──
        c.execute("SELECT COUNT(*) FROM master_stocks_table")
        total_after = c.fetchone()[0]
        print(f"\n[사후] 종목 수: {total_after}")

        c.execute("SELECT COUNT(DISTINCT sector) FROM master_stocks_table WHERE sector IS NOT NULL AND sector != '' AND sector != '미분류'")
        sectors_after = c.fetchone()[0]
        print(f"[사후] 업종 수: {sectors_after}")

        c.execute("SELECT COUNT(*) FROM sectors")
        sectors_table_count = c.fetchone()[0]
        print(f"[사후] sectors 테이블 업종 수: {sectors_table_count}")

        # 종목 수 불일치 확인
        if total_before != total_after:
            print(f"ERROR: 종목 수 불일치 ({total_before} → {total_after})")
            sys.exit(1)

        # sectors 테이블과 master_stocks_table.sector 불일치 확인
        c.execute("""
            SELECT DISTINCT ms.sector FROM master_stocks_table ms
            WHERE ms.sector IS NOT NULL AND ms.sector != '' AND ms.sector != '미분류'
            AND ms.sector NOT IN (SELECT name FROM sectors)
        """)
        orphaned = c.fetchall()
        if orphaned:
            print(f"ERROR: sectors 테이블에 없는 업종이 master_stocks_table에 존재:")
            for row in orphaned:
                print(f"  - {row[0]}")
            sys.exit(1)

        # sectors 테이블에 있지만 master_stocks_table에 없는 업종 (빈 업종)
        c.execute("""
            SELECT s.name FROM sectors s
            WHERE s.name NOT IN (
                SELECT DISTINCT sector FROM master_stocks_table
                WHERE sector IS NOT NULL AND sector != '' AND sector != '미분류'
            )
        """)
        empty_sectors = c.fetchall()
        if empty_sectors:
            print(f"WARNING: master_stocks_table에 종목이 없는 빈 업종:")
            for row in empty_sectors:
                print(f"  - {row[0]}")

        print(f"\n=== 최종 업종 목록 ({sectors_after}개) ===")
        c.execute("""
            SELECT sector, COUNT(*) cnt FROM master_stocks_table
            WHERE sector IS NOT NULL AND sector != '' AND sector != '미분류'
            GROUP BY sector ORDER BY cnt DESC, sector
        """)
        for i, (sector, cnt) in enumerate(c.fetchall(), 1):
            print(f"  {i:2d}. [{cnt:2d}종목] {sector}")

        print("\n마이그레이션 성공 완료.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: 마이그레이션 실패 — {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
