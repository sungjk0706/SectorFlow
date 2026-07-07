# SectorFlow sector 캐시 쓰기 캡슐화 리팩토링 계획

- **프로젝트:** SectorFlow
- **작업명:** sector 캐시 직접 쓰기 접점 단일화 (캡슐화)
- **작성일:** 2026-07-08
- **전제:** 이전 조사에서 sector 캐시 직접 쓰기 4개 지점 확인 완료. 자동 동기화(방식 A) 및 sector_cache 분리(방식 C)는 범위에서 제외.

---

## 진행 원칙 (필수 준수)

### 1. 사전조사 선행 원칙
Step 진행 전 반드시 다음 사항을 코드 기반으로 조사한다:
- 대상 파일의 전체 구조와 의존성
- 영향 받는 모든 파일/함수/변수
- 기존 코드 패턴과의 일관성
- 테스트 커버리지 및 기존 테스트 영향
- 아키텍처 원칙(SSOT, 살아있는 경로, 폴백 금지) 부합 여부

### 2. 보고 → 승인 → 진행 원칙
1. 사전조사 결과를 바탕으로 근본 수정안과 검증 방법을 제시
2. 사용자 승인을 받은 후에만 실제 수정 진행
3. 승인 없이 수정/구현 금지

### 3. 세션당 1단계 원칙
- 각 세션은 1단계(Step)만 진행
- 단계 완료 시: 커밋 + HANDOVER.md 업데이트 + 사용자 보고

### 4. 보고 형식 (5항목)
1. 문제 현상 (UI 기준 설명 + 비유 + 실제 화면)
2. 근본 원인 (코드 기반, 파일:줄, 구체적 데이터 흐름)
3. 수정 방안 (아키텍처 원칙 부합 근거 포함)
4. 수정 영향 범위 (변경 파일, 영향 받는 다른 모듈)
5. 검증 방법 (테스트, 사용자 확인 방법)

---

## 배경 및 목표

### 현재 문제
- `stock_classification_data.py`의 4개 함수가 `master_stocks_cache`의 내부 구조(`entry["sector"]`)를 직접 알고 있음
- 캐시 구조 변경 시 4곳을 모두 수정해야 하는 결합도 문제
- 캐시 접근이 분산되어 있어 일관성 보장이 어려움

### 해결 방향
- 캐시 쓰기 코드를 `update_sector_in_cache()` 함수로 캡슐화
- 종목분류 페이지는 캐시 내부 구조를 모르도록 개선
- 동기식 직접 쓰기 방식은 유지하되, 접점만 단일화

### 목표
- 종목분류 페이지가 캐시 내부 구조를 몰라도 되도록 개선
- 캐시 접근을 단일 지점(`update_sector_in_cache` 함수)으로 통일
- 아키텍처 원칙 강화

### 제외 항목
- **방식 A (자동 동기화 시스템):** 기각됨 — 원칙 5, 7, 13, 16 위반
- **방식 C (sector_cache 분리):** 이번 작업 범위에서 제외 — 별도 계획서 필요

---

## 수정 범위

### 캐시 직접 쓰기 4개 지점

| # | 파일 | 함수 | 줄 | 현재 코드 | 수정 후 |
|---|------|------|----|----------|---------|
| 1 | `stock_classification_data.py` | `rename_sector()` | `:62-64` | `entry["sector"] = new_name` (loop) | `update_sector_in_cache(code, new_name)` (loop) |
| 2 | `stock_classification_data.py` | `delete_sector()` | `:113-115` | `entry["sector"] = "미분류"` (loop) | `update_sector_in_cache(code, "미분류")` (loop) |
| 3 | `stock_classification_data.py` | `move_stock()` | `:149-151` | `entry["sector"] = target_sector` | `update_sector_in_cache(stock_code, target_sector)` |
| 4 | `stock_classification_data.py` | `sync_sector_from_custom_sectors()` | `:217-222` | `state.master_stocks_cache[code]["sector"] = sector` (loop) | `update_sector_in_cache(code, sector)` (loop) |

### 신규 추가 함수

```python
# stock_classification_data.py 상단에 추가
def update_sector_in_cache(code: str, sector: str) -> None:
    """sector 값을 master_stocks_cache에 안전하게 갱신.

    단일 진입점: 모든 sector 캐시 쓰기는 이 함수를 경유한다.
    캐시에 종목이 없으면 경고 로그 후 스킵 (폴백 없음).
    """
    from backend.app.services.engine_state import state
    entry = state.master_stocks_cache.get(code)
    if entry is None:
        _log.warning("[캐시갱신] 종목 %s이(가) 캐시에 없음 — sector 갱신 스킵", code)
        return
    entry["sector"] = sector
```

### 함수 배치 근거

`stock_classification_data.py`에 배치하는 이유:
- 이 파일이 유일한 sector 캐시 쓰기 주체
- `engine_state.py`는 상태 보관소지 쓰기 로직을 포함하지 않는 구조
- 쓰기 주체와 캡슐화 함수를 같은 파일에 배치하여 응집도 유지

---

## 진행 상태 요약

| 단계 | 내용 | 상태 | 세션 |
|------|------|------|------|
| Step 1 | `update_sector_in_cache()` 함수 추가 | 대기 | - |
| Step 2 | `move_stock()` 캡슐화 적용 (단건, 가장 단순) | 대기 | - |
| Step 3 | `rename_sector()` + `delete_sector()` 캡슐화 적용 (loop) | 대기 | - |
| Step 4 | `sync_sector_from_custom_sectors()` 캡슐화 적용 (loop) | 대기 | - |
| Step 5 | 빌드 검증 + 테스트 + 브라우저 확인 | 대기 | - |

---

## Step 1: `update_sector_in_cache()` 함수 추가

- **사전조사:**
  - 대상 파일: `backend/app/core/stock_classification_data.py` (229줄)
  - 현재 구조: 모듈 상단에 `_log = logging.getLogger(__name__)` (`:11`), 데이터 모델 (`:15-20`), 조회 함수 (`:25-32`), 비즈니스 로직 (`:37-228`)
  - 의존성: `backend.app.services.engine_state.state` — 4개 함수에서 지연 import 방식으로 사용
  - 영향 범위: 신규 함수 추가만, 기존 코드 변경 없음
  - 기존 코드 패턴: 지연 import (`from backend.app.services.engine_state import state`를 함수 내부에서 import)
  - 테스트 영향: `stock_classification_data.py` 전용 테스트 없음. `test_market_close_pipeline.py`에서 `sync_sector_from_custom_sectors`를 AsyncMock으로 patch
  - 아키텍처 원칙: 원칙 10 (SSOT) — 캐시 쓰기 단일 진입점 생성. 원칙 16 (살아있는 경로) — 직접 호출 체인 유지. 원칙 5 (EventBus 금지) — 동기식 직접 호출. 원칙 20 (폴백 금지) — 캐시 미스 시 경고 로그 후 스킵, 폴백 없음

- **목표:** `update_sector_in_cache()` 함수를 `stock_classification_data.py`에 추가
- **대상 파일:** `backend/app/core/stock_classification_data.py`
- **변경 내용:**
  - 비즈니스 로직 섹션 상단 (`:35` 직전)에 `update_sector_in_cache()` 함수 추가
  - 지연 import 패턴 유지 (`from backend.app.services.engine_state import state`를 함수 내부에서 import)
  - 캐시에 종목이 없으면 경고 로그 후 return (폴백 없음)

- **선행 조건:** 없음 (신규 함수 추가만)
- **롤백 방법:** 추가된 함수 삭제
- **검증 방법:**
  - `python -m py_compile backend/app/core/stock_classification_data.py`
  - `python -m pytest backend/tests/ -x -q` (기존 테스트 통과 확인)
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): 캐시 sector 쓰기의 단일 진입점 생성 — 부합
  - 원칙 16 (살아있는 경로): 동기식 직접 호출, 큐/이벤트 중개 없음 — 부합
  - 원칙 5 (EventBus 금지): 직접 함수 호출, pub-sub 없음 — 부합
  - 원칙 20 (폴백 금지): 캐시 미스 시 대체 경로 없이 로그 후 스킵 — 부합

---

## Step 2: `move_stock()` 캡슐화 적용

- **사전조사:**
  - 대상: `stock_classification_data.py:146-153`의 캐시 직접 쓰기 블록
  - 현재 코드:
    ```python
    # 2) 인메모리 캐시 증분 업데이트
    try:
        from backend.app.services.engine_state import state
        entry = state.master_stocks_cache.get(stock_code)
        if entry:
            entry["sector"] = target_sector
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 종목 업종 갱신 실패: %s", e)
    ```
  - 가장 단순한 케이스: 단건 쓰기, loop 없음
  - 영향 범위: `move_stock()` 함수만, 호출처(`stock_classification.py:257, 272`)는 변경 없음
  - 테스트 영향: `move_stock()` 직접 테스트 없음

- **목표:** `move_stock()`의 캐시 직접 쓰기를 `update_sector_in_cache()` 호출로 교체
- **대상 파일:** `backend/app/core/stock_classification_data.py`
- **변경 내용:**
  - `:146-153` 블록을 다음으로 교체:
    ```python
    # 2) 인메모리 캐시 증분 업데이트
    try:
        update_sector_in_cache(stock_code, target_sector)
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 종목 업종 갱신 실패: %s", e)
    ```

- **선행 조건:** Step 1 완료
- **롤백 방법:** 원래 코드로 복원
- **검증 방법:**
  - `python -m py_compile backend/app/core/stock_classification_data.py`
  - `python -m pytest backend/tests/ -x -q`
  - 브라우저: 종목분류 페이지에서 종목 1개 이동 → 업종 변경 즉시 반영 확인
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): 캐시 쓰기가 단일 함수를 경유 — 부합
  - 원칙 16 (살아있는 경로): `move_stock()` → `update_sector_in_cache()` → cache 직접 쓰기, 경로 유지 — 부합
  - 원칙 5 (EventBus 금지): 직접 호출 — 부합
  - 원칙 20 (폴백 금지): 폴백 없음 — 부합

---

## Step 3: `rename_sector()` + `delete_sector()` 캡슐화 적용

- **사전조사:**
  - 대상 1: `stock_classification_data.py:59-66` (`rename_sector` 캐시 쓰기)
  - 현재 코드 (rename):
    ```python
    # 2) 인메모리 캐시 증분 업데이트
    try:
        from backend.app.services.engine_state import state
        for cd, entry in state.master_stocks_cache.items():
            if entry.get("sector") == old_name:
                entry["sector"] = new_name
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종명 변경 실패: %s", e)
    ```
  - 대상 2: `stock_classification_data.py:110-117` (`delete_sector` 캐시 쓰기)
  - 현재 코드 (delete):
    ```python
    # 2) 인메모리 캐시 증분 업데이트
    try:
        from backend.app.services.engine_state import state
        for cd, entry in state.master_stocks_cache.items():
            if entry.get("sector") == name:
                entry["sector"] = "미분류"
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종 삭제 반영 실패: %s", e)
    ```
  - 공통점: 둘 다 cache 전체 순회하며 조건부 갱신 (loop)
  - 영향 범위: 2개 함수만, 호출처(`stock_classification.py:212, 242`)는 변경 없음

- **목표:** `rename_sector()`와 `delete_sector()`의 캐시 직접 쓰기를 `update_sector_in_cache()` 호출로 교체
- **대상 파일:** `backend/app/core/stock_classification_data.py`
- **변경 내용:**
  - `rename_sector` `:59-66` 블록을 다음으로 교체:
    ```python
    # 2) 인메모리 캐시 증분 업데이트
    try:
        from backend.app.services.engine_state import state
        for cd, entry in state.master_stocks_cache.items():
            if entry.get("sector") == old_name:
                update_sector_in_cache(cd, new_name)
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종명 변경 실패: %s", e)
    ```
  - `delete_sector` `:110-117` 블록을 다음으로 교체:
    ```python
    # 2) 인메모리 캐시 증분 업데이트
    try:
        from backend.app.services.engine_state import state
        for cd, entry in state.master_stocks_cache.items():
            if entry.get("sector") == name:
                update_sector_in_cache(cd, "미분류")
    except Exception as e:
        _log.warning("[메모리업데이트] 인메모리 업종 삭제 반영 실패: %s", e)
    ```
  - 주의: loop 자체는 유지 (조건부 갱신이므로 단건 교체 불가), 내부 쓰기만 캡슐화

- **선행 조건:** Step 1 완료
- **롤백 방법:** 원래 코드로 복원
- **검증 방법:**
  - `python -m py_compile backend/app/core/stock_classification_data.py`
  - `python -m pytest backend/tests/ -x -q`
  - 브라우저: 종목분류 페이지에서 업종명 변경 → 전체 종목 업종 일괄 변경 확인
  - 브라우저: 종목분류 페이지에서 업종 삭제 → 해당 업종 종목이 "미분류"로 이동 확인
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): 캐시 쓰기가 단일 함수를 경유 — 부합
  - 원칙 16 (살아있는 경로): 직접 호출 체인 유지 — 부합
  - 원칙 5 (EventBus 금지): 직접 호출 — 부합
  - 원칙 20 (폴백 금지): 폴백 없음 — 부합

---

## Step 4: `sync_sector_from_custom_sectors()` 캡슐화 적용

- **사전조사:**
  - 대상: `stock_classification_data.py:213-224`의 캐시 갱신 블록
  - 현재 코드:
    ```python
    # 메모리 캐시 sector 필드 갱신 (활성 + 복원 종목 모두 포함)
    for row in rows:
        code = row["stock_code"]
        sector = row["name"]
        if code in state.master_stocks_cache:
            state.master_stocks_cache[code]["sector"] = sector
    for row in hidden_rows:
        code = row["stock_code"]
        if code in master_codes and code in state.master_stocks_cache:
            state.master_stocks_cache[code]["sector"] = row["name"]

    _log.info("[동기화] 메모리 캐시 sector 필드 갱신 완료 -- %d종목", updated)
    ```
  - 특이점: 2개 loop (활성 종목 + 복원 종목), `state`를 이미 함수 상단에서 import (`:165`)
  - 영향 범위: `sync_sector_from_custom_sectors()` 함수만
  - 테스트 영향: `test_market_close_pipeline.py:649, 687`에서 `sync_sector_from_custom_sectors`를 AsyncMock으로 patch — 함수 시그니처 변경 없으므로 영향 없음

- **목표:** `sync_sector_from_custom_sectors()`의 캐시 직접 쓰기를 `update_sector_in_cache()` 호출로 교체
- **대상 파일:** `backend/app/core/stock_classification_data.py`
- **변경 내용:**
  - `:213-224` 블록을 다음으로 교체:
    ```python
    # 메모리 캐시 sector 필드 갱신 (활성 + 복원 종목 모두 포함)
    for row in rows:
        code = row["stock_code"]
        sector = row["name"]
        update_sector_in_cache(code, sector)
    for row in hidden_rows:
        code = row["stock_code"]
        if code in master_codes:
            update_sector_in_cache(code, row["name"])

    _log.info("[동기화] 메모리 캐시 sector 필드 갱신 완료 -- %d종목", updated)
    ```
  - 주의: `if code in state.master_stocks_cache` 체크 제거 — `update_sector_in_cache()` 내부에서 처리

- **선행 조건:** Step 1 완료
- **롤백 방법:** 원래 코드로 복원
- **검증 방법:**
  - `python -m py_compile backend/app/core/stock_classification_data.py`
  - `python -m pytest backend/tests/ -x -q`
  - 브라우저: 장마감 후 업종 분류 페이지 정상 표시 확인 (또는 수동 1일봉 다운로드 후 확인)
- **아키텍처 원칙 부합:**
  - 원칙 10 (SSOT): 캐시 쓰기가 단일 함수를 경유 — 부합
  - 원칙 16 (살아있는 경로): 직접 호출 체인 유지 — 부합
  - 원칙 5 (EventBus 금지): 직접 호출 — 부합
  - 원칙 20 (폴백 금지): 폴백 없음 — 부합

---

## Step 5: 빌드 검증 + 테스트 + 브라우저 확인

- **사전조사:**
  - 전체 변경 파일: `backend/app/core/stock_classification_data.py` (1개 파일만)
  - 변경 내용: 신규 함수 1개 + 4개 함수 내부 쓰기 블록 교체
  - 외부 인터페이스 변경: 없음 (함수 시그니처, import 경로 모두 동일)
  - 테스트 파일: `test_market_close_pipeline.py`에서 `sync_sector_from_custom_sectors`를 AsyncMock으로 patch — 시그니처 변경 없으므로 영향 없음

- **목표:** 전체 변경사항 통합 검증
- **검증 항목:**
  1. **백엔드 컴파일:** `python -m py_compile backend/app/core/stock_classification_data.py`
  2. **기존 테스트:** `python -m pytest backend/tests/ -x -q`
  3. **잔여 직접 쓰기 검색:** `state.master_stocks_cache[.*]["sector"] =` 패턴이 `update_sector_in_cache` 외에 남아있는지 grep 확인
  4. **프론트엔드 빌드:** `cd frontend && npm run build`
  5. **브라우저 확인 (사용자 직접):**
     - 종목 1개 이동 → 업종 변경 즉시 반영
     - 업종명 변경 → 전체 종목 일괄 반영
     - 업종 삭제 → 해당 종목 "미분류" 이동
     - 업종 순위 재계산 정상 동작

- **선행 조건:** Step 1~4 완료
- **롤백 방법:** git revert
- **아키텍처 원칙 최종 확인:**
  - 원칙 10 (SSOT): 모든 sector 캐시 쓰기가 `update_sector_in_cache()` 단일 진입점을 경유 — 부합
  - 원칙 16 (살아있는 경로): 4개 함수 → `update_sector_in_cache()` → cache 직접 쓰기, 모든 경로 살아있음 — 부합
  - 원칙 5 (EventBus 금지): 전부 동기식 직접 호출, 큐/이벤트 없음 — 부합
  - 원칙 20 (폴백 금지): 캐시 미스 시 경고 로그 후 스킵, 대체 경로 없음 — 부합

---

## 완료 기준

- [ ] `update_sector_in_cache()` 함수가 `stock_classification_data.py`에 존재
- [ ] 4개 함수(`rename_sector`, `delete_sector`, `move_stock`, `sync_sector_from_custom_sectors`)의 캐시 쓰기가 전부 `update_sector_in_cache()` 호출로 교체됨
- [ ] `state.master_stocks_cache[...]["sector"] =` 직접 할당이 `update_sector_in_cache()` 내부 1곳에만 존재
- [ ] `py_compile` 통과
- [ ] `pytest` 기존 테스트 전부 통과
- [ ] `npm run build` 통과
- [ ] 브라우저에서 종목분류 페이지 정상 동작 (사용자 확인)
- [ ] 각 Step 완료 시 커밋 + HANDOVER.md 업데이트
