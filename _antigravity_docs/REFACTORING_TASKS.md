# 주식 자동매매 아키텍처 리팩토링: 마이크로 지시서 (하이브리드 확정본)

> [!IMPORTANT]
> 이 문서는 사용자와의 `grill-me` 인터뷰를 통해 확정된 **[최종 황금 밸런스 아키텍처]**를 구현하기 위한 외과 수술급 지시서입니다. 하위 AI는 절대 임의로 로직을 추가하거나 삭제하지 말고, 지시된 [삭제할 내용]과 [추가할 내용]만 기계적으로 파일에 적용하세요.

## 🏗️ 최종 아키텍처 원칙 (Agreed Principles)
1. **장중 실시간 데이터 연산 (Memory):** 초당 수백 번 쏟아지는 웹소켓 틱 데이터와 업종 순위 계산은 **파이썬 메모리(딕셔너리)에서 초고속으로 수행**합니다. (DB 병목 제거)
2. **장 마감 데이터 영구 저장 (SQLite DB):** 장 마감(20:30) 후 확정된 데이터(종목마스터, 기준가, 5일 평균 거래대금 등)는 다음 날을 위해 **SQLite DB에 저장**합니다.
3. **더미 프론트엔드 (Dumb Terminal):** 프론트엔드는 수학 연산을 하지 않고 백엔드가 계산해 넘겨준 완성된 JSON만 화면에 렌더링합니다.

---

## 🛠 1단계: SQLite DB 로드/세이브 연결 (JSON 캐시 대체)

### Task 1: `backend/app/db/crud.py`에 전체 조회 함수 추가
**지시문**: `backend/app/db/crud.py` 파일을 수정해.
- **[추가할 내용]**: 파일 맨 아래에 `get_all_stocks()` 함수를 만들어. DB 커넥션을 맺고 `SELECT code, name, sector, prev_close, avg_5d_trade_amount, high_price FROM stocks` 쿼리를 실행한 뒤, 딕셔너리 리스트 형태로 리턴하는 짧은 함수를 추가해.

### Task 2: `backend/app/services/engine_bootstrap.py` (앱 시작 시 DB 로드)
**지시문**: `backend/app/services/engine_bootstrap.py` 파일을 수정해.
- **[수정할 위치]**: `load_snapshot_cache()`를 호출해서 기존 JSON 파일을 읽어오는 코드를 찾아. (대략 130~150라인 부근 `_st._pending_stock_details`를 복원하는 곳)
- **[삭제할 내용]**: `from backend.app.core.sector_stock_cache import load_snapshot_cache` 임포트와 해당 호출 부분을 지워.
- **[추가할 내용]**: 대신 `from backend.app.db.crud import get_all_stocks`를 임포트해. 앱 시작 시 `get_all_stocks()`를 호출해서 가져온 리스트를 돌면서 `_st._pending_stock_details` 딕셔너리에 꽂아 넣도록 수정해.

### Task 3: `backend/app/services/market_close_pipeline.py` (장 마감 시 DB 저장)
**지시문**: `backend/app/services/market_close_pipeline.py` 파일을 수정해.
- **[수정할 위치]**: 장 마감 후 스냅샷을 저장하는 `_save_confirmed_cache(es)` 함수 본문을 찾아. (대략 367라인 부근)
- **[삭제할 내용]**: `save_snapshot_cache(rows)`를 호출해서 JSON 파일로 저장하는 부분을 지워.
- **[추가할 내용]**: 대신 `from backend.app.db.crud import insert_stock`을 임포트해. `rows` 리스트를 for문으로 돌면서 `insert_stock()`을 호출하여 SQLite DB에 안전하게 한 줄씩 기록하도록 코드를 갈아끼워.

---

## 🛠 2단계: 프론트엔드 종속성 끊기 (Dumb Terminal화)

### Task 4: `frontend/src/stores/hotStore.ts`의 완전한 더미화 검증
**지시문**: `frontend/src/stores/hotStore.ts` 파일을 수정해.
- **[수정할 위치]**: `export function applySectorScores(data: SectorScoresEvent)` 함수 내부를 확인해.
- **[삭제할 내용]**: 만약 해당 함수 안에 `Array.prototype.sort()`나 섹터별 등락률을 재계산하는 수학 수식(`+`, `/`)이 단 한 줄이라도 있다면 **모두 지워**.
- **[추가할 내용]**: 백엔드가 파이썬 메모리에서 0.001초만에 완벽하게 계산해준 데이터를 그대로 상태에 꽂아넣는 아래 코드만 남겨.
  ```typescript
  export function applySectorScores(data: SectorScoresEvent): void {
    hotStore.setState((state) => {
      state.sectorScores = data.sectors; // 백엔드가 연산한 완성본을 그대로 사용
    });
  }
  ```

### Task 5: `frontend/src/pages/sector-analysis.ts` UI 단순화
**지시문**: `frontend/src/pages/sector-analysis.ts` 파일을 수정해.
- **[삭제할 내용]**: 데이터를 렌더링하기 전에 `state.sectorScores.filter(...)` 또는 `.sort(...)`로 가공하는 프론트엔드 측의 데이터 조작 로직을 모두 찾아서 지워.
- **[추가할 내용]**: 이미 백엔드에서 정렬되어 넘어오므로, 그냥 `hotStore.getState().sectorScores.forEach(...)`로 순회하면서 화면 DOM 요소(HTML)에 텍스트만 뿌려주는 순수 렌더러 역할로 수정해.
