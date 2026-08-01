# 태스크 파일: test_positions DB 테이블 제거 (2단계 접근)

> **상태**: 조사 완료, 승인 대기
> **작성일**: 2026-08-01
> **위험도**: 낮음 (완전 고립된 레거시 테이블, 코드 참조 0건)
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P22(데이터 정합성) · P24(단순성)
> **관련 스킬**: db-backup (DB 백업 필수)
> **선행 커밋**: 5fdb6e9 (2026-07-10, 테이블 생성/CRUD 코드 제거)

---

## 0. 사전조사 결과 요약

### 0.1 대상

SQLite `backend/data/stocks.db` 내 `test_positions` 테이블.

```sql
CREATE TABLE test_positions (
    stk_cd TEXT PRIMARY KEY,
    stk_nm TEXT, qty INTEGER, avg_price INTEGER, cur_price INTEGER,
    total_fee INTEGER, buy_amt INTEGER, eval_amt INTEGER,
    pnl_amount INTEGER, pnl_rate REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

- 잔존 데이터: 3행 (131970, 420770, 010120), 마지막 갱신 2026-07-09 06:59:40
- 커밋 `5fdb6e9`에서 테이블 생성 코드·CRUD 함수·호출부 전부 제거되었으나 DROP 마이그레이션 누락

### 0.2 전수 조사 결과 (4항목 전부 안전)

| 항목 | 결과 | 상세 |
|------|------|------|
| 테스트 코드 | 0건 | 39매치 전부 `_test_positions` Python dict 또는 pytest 메서드명 |
| 마이그레이션 | 코드 제거 완료 | `5fdb6e9`에서 CREATE/save/load 전부 제거. DROP 마이그레이션 필요 |
| ORM/모델 | 없음 | aiosqlite raw SQL, 모델 클래스 없음 |
| 운영/문서 | 2건 정리 필요 | `ARCHITECTURE.md:845`, `docs/architecture_cur_price_fallback_removal_design.md:47` |

### 0.3 주의: `_test_positions` Python dict과 별개

`dry_run.py`의 `_test_positions`(인메모리 dict, `trades` 테이블 기반 파생 캐시)는 **삭제 대상이 아님**.
이름이 유사하나 완전히 다른 대상 — 본 태스크는 DB 테이블 `test_positions`만 제거.

---

## 1. 접근 방식: 2단계 (격리 → 완전 삭제)

즉시 물리 DROP 대신, 되돌리기 쉬운 2단계 접근.

### 1단계 (본 태스크 — 격리 + 백업)

1. DB 백업 (db-backup 스킬 절차 준수)
2. `test_positions` 테이블 데이터를 SQL 파일로 별도 덤프 (롤백용)
3. 테이블명 변경: `test_positions` → `_test_positions_deprecated_20260801`
   - 즉시 고립 — 우연한 참조가 있어도 즉시 발견됨
   - 데이터 보존 — 롤백 시 RENAME 복원만 하면 됨
4. 문서 2건 정리 (ARCHITECTURE.md S10, design doc 주석)
5. 런타임 기동 검증 + pytest 실행

### 2단계 (별도 세션 — 완전 삭제, 사후 검증 후)

- 1단계 격리 후 런타임 정상 동작 확인되면 (권장: 1거래일 경과 후)
- `DROP TABLE _test_positions_deprecated_20260801` 실행
- 백업 파일 삭제 (db-backup 스킬 6절 절차)

> 2단계는 별도 승인 시점에 진행. 본 태스크는 1단계까지.

---

## 2. 의존성 및 변경 파일

| 파일 | 변경점 |
|------|--------|
| `backend/data/stocks.db` | 테이블 RENAME (DB 마이그레이션) |
| `backend/data/stocks.db.<TS>.backup` | 백업 파일 생성 (db-backup 스킬) |
| `backend/data/test_positions_dump_20260801.sql` | 테이블 데이터 덤프 (롤백용) |
| `ARCHITECTURE.md` | S10 테이블 목록에서 `test_positions` 행 제거 |
| `docs/architecture_cur_price_fallback_removal_design.md` | 47행 "test_positions DB 테이블 DROP" 비목표 행 제거 또는 "완료" 표시 |

---

## 3. 구현 단계

### 3-1. 앱 종료 + 백업 (db-backup 스킬)

```bash
# 잔존 프로세스 확인 (AGENTS.md 0-1-3)
lsof -ti:8000 || echo "포트 8000 프로세스 없음"

# 타임스탬프 백업
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp backend/data/stocks.db "backend/data/stocks.db.${TIMESTAMP}.backup"
cp backend/data/stocks.db-shm "backend/data/stocks.db-shm.${TIMESTAMP}.backup" 2>/dev/null || true
cp backend/data/stocks.db-wal "backend/data/stocks.db-wal.${TIMESTAMP}.backup" 2>/dev/null || true

# 백업 검증
ls -lh backend/data/stocks.db.${TIMESTAMP}.backup
```

### 3-2. test_positions 데이터 덤프 (롤백용)

```bash
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('backend/data/stocks.db')
with open('backend/data/test_positions_dump_20260801.sql', 'w') as f:
    for line in conn.iterdump():
        if 'test_positions' in line:
            f.write(line + '\n')
conn.close()
print('덤프 완료')
"
# 덤프 파일 확인
ls -lh backend/data/test_positions_dump_20260801.sql
```

### 3-3. 테이블 RENAME (격리)

```bash
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('backend/data/stocks.db')
conn.execute('ALTER TABLE test_positions RENAME TO _test_positions_deprecated_20260801')
conn.commit()
# 확인
cur = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%test_positions%'\")
print('RENAME 후:', cur.fetchall())
conn.close()
"
```

### 3-4. 문서 정리

**ARCHITECTURE.md S10** (845행) — 테이블 행 제거:
```
| `test_positions` | 테스트 모드 가상 포지션 |  ← 제거
```

**docs/architecture_cur_price_fallback_removal_design.md** (47행) — 비목표 표 업데이트:
```
| `test_positions` DB 테이블 DROP | 레거시 잔재이나 코드 미사용 확인됨. 별도 작업으로 분리 (긴급하지 않음) |
```
→ "완료(2026-08-01, 태스크 task_drop_test_positions_table.md)" 로 변경

### 3-5. 검증

```bash
# 1. 런타임 기동 (RuntimeWarning 검증 포함)
.venv/bin/python -W error::RuntimeWarning main.py &
# 기동 로그 확인 후 종료

# 2. pytest 실행
.venv/bin/python -m pytest backend/tests -q

# 3. 프론트엔드 타입체크 (문서 변경 영향 없음 확인)
cd frontend && npm run typecheck
```

---

## 4. 롤백 계획

### 트리거
- 런타임 기동 실패
- pytest 실패 (test_positions 테이블 참조 발견 시)
- 핵심 데이터 조회 불일치

### 롤백 절차

**경우 A: RENAME만 롤백 (데이터 보존)**
```bash
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('backend/data/stocks.db')
conn.execute('ALTER TABLE _test_positions_deprecated_20260801 RENAME TO test_positions')
conn.commit()
conn.close()
"
```

**경우 B: 백업에서 전체 복원 (DB 손상 시)**
```bash
LATEST=$(ls -t backend/data/stocks.db.*.backup | head -1 | sed 's/\.backup$//')
cp "${LATEST}.backup" "backend/data/stocks.db"
cp "${LATEST}-shm.backup" "backend/data/stocks.db-shm" 2>/dev/null || true
cp "${LATEST}-wal.backup" "backend/data/stocks.db-wal" 2>/dev/null || true
```

---

## 5. 완료 조건

- [ ] DB 백업 파일 3종 생성 확인
- [ ] test_positions 데이터 덤프 파일 생성 확인
- [ ] 테이블 RENAME 완료 (`test_positions` → `_test_positions_deprecated_20260801`)
- [ ] ARCHITECTURE.md S10 테이블 행 제거
- [ ] design doc 비목표 표 업데이트
- [ ] 런타임 기동 정상 (RuntimeWarning 없음)
- [ ] pytest 전체 통과
- [ ] 프론트엔드 typecheck 통과
- [ ] 코드 커밋 (코드 + 문서 변경분)
- [ ] HANDOVER.md 갱신

---

## 6. 2단계 (참고 — 별도 세션)

1단계 격리 후 런타임 정상 동작이 확인되면 (권장: 1거래일 경과 후):

```bash
# 완전 삭제
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('backend/data/stocks.db')
conn.execute('DROP TABLE _test_positions_deprecated_20260801')
conn.commit()
conn.close()
"

# 백업 파일 + 덤프 파일 삭제 (사용자 승인 후)
rm backend/data/stocks.db.*.backup
rm backend/data/stocks.db-shm.*.backup 2>/dev/null || true
rm backend/data/stocks.db-wal.*.backup 2>/dev/null || true
rm backend/data/test_positions_dump_20260801.sql
```
