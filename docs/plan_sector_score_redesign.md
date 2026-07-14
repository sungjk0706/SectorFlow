# 업종 점수 산정 방식 리팩토링 계획서

> **작성일**: 2026-07-15
> **상태**: 설계 완료, 구현 대기 (Step 1 사전조사부터 시작)
> **세션당 1단계 원칙 준수 — 총 4세션 예상**

---

## 1. 배경

업종순위 설정 패널 ④ "가산점 만점 설정 (3단계 누적)"의 3개 설정값(1차 만점 10, 2차 만점 7, 3차 만점 5)과 2차 가산점(상대평가) 계산 방식을 전면 개편.

### 현재 방식 (변경 전)

- **만점**: 사용자가 숫자 입력 (기본값 10, 7, 5)
- **1차 (상승비율)**: 업종 간 상승비율 순위 → tiered 점수 (1위=만점, 2위=만점-1, ...)
- **2차 (상대평가)**: 통과 업종 종목들 → 종목별 0~100 백분위 변환 → 업종별 평균 → 업종 간 순위 (4단계)
- **3차 (거래대금)**: 업종 간 평균 거래대금 순위 → tiered 점수
- **컷오프 미달 업종**: `rank=0` 고정 (순위 표시 + 매수 제외 동시 사용)
- **종합 점수**: 1차 + 2차 + 3차 (0~22점)

### 핵심 코드 위치 (변경 전)

- `backend/app/domain/sector_score.py` — `calculate_bonus_scores()`, `rank_to_tiered_score()`, `percentile_to_score()`
- `backend/app/domain/sector_calculator.py` — `compute_full_sector_summary()` (파라미터 전달)
- `backend/app/domain/models.py` — `SectorScore` dataclass
- `backend/app/core/engine_settings.py` — 만점 설정 3개 (`sector_bonus_rise_ratio_max` 등)
- `backend/app/core/settings_defaults.py` — 만점 기본값 3개
- `backend/app/services/engine_sector_confirm.py` — `calculate_bonus_scores()` 호출 (2곳)
- `backend/app/services/sector_data_provider.py` — `recompute_sector_summary_now()`, `get_sector_scores_snapshot()`
- `backend/app/domain/buy_filter.py` — `sc.rank == 0` 매수 제외 조건
- `backend/app/services/engine_service.py` — 설정 키 목록
- `frontend/src/types/index.ts` — `AppSettings`, `SectorScoreRow`
- `frontend/src/pages/sector-settings.ts` — 만점 숫자 입력 3개
- `frontend/src/pages/sector-ranking-list.ts` — `rank === 0` 기반 UI 표시

---

## 2. 최종 확정 사항

### 2.1 만점 기준 변경

- **기존**: 사용자가 숫자 입력 (10, 7, 5)
- **변경**: 우측 실시간 시세 테이블에 올라온 **업종 수**를 만점으로 자동 사용
- 1위 = 업종 수, 2위 = 업종 수 - 1, ... (순위별 1점 차감 유지)
- 업종 수 변동 시 만점도 자동 변경
- **최종 순위는 1차+2차+3차 합계 점수로 결정**
- 구현: `calculate_bonus_scores()`에서 `max_score = len(sector_scores)` 사용
- 사용자 설정값 3개(`sector_bonus_rise_ratio_max` 등) 제거

### 2.2 가중치 조절 슬라이더 추가

- 3개 가산점 각각에 슬라이더 (-100% ~ +100%, 기본값 0%)
- **조정 만점 = 업종 수 × (1 + 슬라이더/100)**
- 예: 업종 50개 → 1차 조정 만점 50점 → 슬라이더 -50% → 조정 만점 25점 → 1위 25점, 2위 24.5점, ...
- 기존 만점 숫자 입력 3개 제거 → 슬라이더 3개로 대체 (설정 패널 단순화 — 입력 컴포넌트 6개 → 3개)
- 신규 설정 키: `sector_bonus_rise_ratio_slider`, `sector_bonus_relative_strength_slider`, `sector_bonus_trade_amount_slider` (기본값 0)
- 소수점 점수 허용 → `rank_to_tiered_score()` 반환형 `int` → `float` 전환 필요
- 슬라이더 -100% → 조정 만점 0 → 해당 가산점 무효화 (사용자 의도적, P20 폴백 아님)
- 기존 `createSlider()` 컴포넌트 재사용 가능

### 2.3 2차 가산점 알고리즘 변경 — 가중 순위 합 (Weighted Rank Sum)

- **기존**: 종목별 0~100 백분위 → 업종 평균 → 업종 순위 (4단계)
- **변경**: 가중 순위 합 (3단계)

**알고리즘**:
1. 통과 업종의 모든 종목을 상승률 내림차순 정렬 → 순위 1, 2, 3, ..., N
2. 각 종목의 가중치 = (N - 순위 + 1) / N → 1위 = 1.0, 2위 = (N-1)/N, ..., N위 = 1/N
3. 업종별 가중치 합산 = Σ (해당 업종 종목의 가중치)
4. 업종 간 가중 합 순위 → `rank_to_tiered_score()` (1위 = 조정 만점)

**추천 근거**:
- 부하: 정렬 O(N log N) + 순회 O(N) — 현재 백분위 방식과 동일 복잡도
- P22: 통과 업종만 모집단, 가중치는 순위에서만 도출 (파생 데이터 아님)
- P24: 3단계 (현재 4단계보다 1단계 적음)
- 의도 부합: 상위 순위 종목이 높은 가중치 → "위쪽에 많이 포진한 업종"이 정확히 높은 점수
- 현재 백분위 평균 방식의 문제(1개 1위 + 9개 꼴찌가 비슷한 평균) 해결 — 상위 집중도 직접 반영

**주의**: 종목 수가 많은 업종이 유리 (가중치 합산 기회 많음). 사용자 의도 "많이 포진"에 부합하므로 정규화 없이 가중 합 사용.

**제거 대상**: `percentile_to_score()` 함수 (dead code — P16)

### 2.4 계산 대상 — 컷오프 통과 업종만

- 업종 내 상승비율 이하 차단 필터링을 통과한 업종만 2차 계산 대상 (현재 방식 유지)
- 탈락했던 업종이 실시간 상승비율 변동으로 재통과 시 즉시 계산에 포함
- 안 B(전 업종 대상)는 P22 위반(탈락 업종 종목이 통과 업종 점수에 영향) + P7 부하 증가로 부적합

### 2.5 컷오프 미달 업종 — 순위 정상 표시

- `rank=0` 고정 해제 → 실제 순위 정상 표시 (1, 2, 3, ... 모든 업종)
- `SectorScore`에 `is_cutoff_passed: bool` 필드 신설 (rank와 분리)
- 미달 업종은 행 배경색 회색으로 구분 유지 (기존 UI 패턴)
- 매수 제외 판단: `sc.rank == 0` → `not sc.is_cutoff_passed` (`buy_filter.py`)
- UI 통과 카운트: `s.rank > 0` → `s.is_cutoff_passed` (`sector-ranking-list.ts`, `sector-settings.ts`)
- 스냅샷 전파: `get_sector_scores_snapshot()`에 `is_cutoff_passed` 필드 추가
- `SectorScoreRow` 타입에 `is_cutoff_passed: boolean` 추가

### 2.6 실시간 반영

- 기존 구조(`request_sector_recompute` → `_flush_sector_recompute_impl`)로 이미 구현됨
- 추가 작업 없음 — 만점 자동화, 슬라이더, 가중 순위 합 모두 매 재계산마다 자동 반영

---

## 3. 아키텍처 원칙 부합 여부

| 원칙 | 부합 | 비고 |
|---|---|---|
| P10 (SSOT) | O | 만점이 업종 수에서 자동 도출, rank/is_cutoff_passed 분리 |
| P16 (살아있는 경로) | O | `percentile_to_score()` 제거 → dead code 해소 |
| P20 (폴백 금지) | O | 슬라이더 -100%는 사용자 의도적 무효화 (폴백 아님) |
| P21 (사용자 투명성) | O | 미달 업종 순위 표시, 만점 자동 표시 |
| P22 (데이터 정합성) | O | 통과 업종만 모집단, 가중치는 순위에서만 도출 |
| P23 (일관성) | O | 3개 가산점 동일 슬라이더 방식, 용어 사전 준수 |
| P24 (단순성) | O | 만점 입력 3개 제거 → 슬라이더 3개, 2차 4단계 → 3단계 |

---

## 4. 성능 영향

| 변경사항 | 성능 영향 | 측정 |
|---|---|---|
| 만점 = 업종 수 | 없음 | `len()` O(1) |
| 슬라이더 3개 | 없음 | 곱셈 3회 |
| 2차 알고리즘 (백분위 → 가중 순위 합) | 동일 | 정렬 O(N log N) + 순회 O(N), N=수백~수천, ~1ms |
| is_cutoff_passed 분리 | 없음 | 필드 추가만 |
| float 전환 | 없음 | int → float 연산 |

**실시간 틱 핸들러 지연**: 없음. `calculate_bonus_scores()`는 배치 실행되어 틱 핸들러 블로킹 없음.

---

## 5. 단계별 작업 계획 (세션당 1단계)

### Step 1: 백엔드 — 점수 계산 로직 전면 개편

**대상 파일** (5개):
1. `backend/app/domain/sector_score.py`
   - `calculate_bonus_scores()` 전면 수정: 만점 = `len(sector_scores)`, 슬라이더 비율 적용
   - `rank_to_tiered_score()` → `float` 반환으로 전환
   - 2차 알고리즘: 백분위 → 가중 순위 합 (Weighted Rank Sum)
   - `percentile_to_score()` 제거 (P16)
   - `is_cutoff_passed` 필드 설정 로직 추가
   - rank 부여 로직: 모든 업종에 순위 부여 (컷오프 미달도 rank 부여, is_cutoff_passed로 구분)
2. `backend/app/domain/models.py`
   - `SectorScore`에 `is_cutoff_passed: bool = True` 필드 추가
3. `backend/app/core/engine_settings.py`
   - 만점 설정 3개 제거 (`sector_bonus_rise_ratio_max` 등)
   - 슬라이더 설정 3개 추가 (`sector_bonus_rise_ratio_slider` 등, 기본값 0)
4. `backend/app/core/settings_defaults.py`
   - 만점 기본값 3개 제거, 슬라이더 기본값 3개(0) 추가
5. `backend/app/domain/sector_calculator.py`
   - `compute_full_sector_summary()` 파라미터: 만점 3개 → 슬라이더 3개

**사전조사 항목 (Step 1 세션 시작 시 수행)**:
- `calculate_bonus_scores()` 호출처 3곳 파라미터 변경 영향
- `percentile_to_score()` 참조 전체 검색 (제거 전 잔존 참조 확인)
- `rank_to_tiered_score()`의 `int` 반환에 의존하는 코드 검색
- `SectorScore.rank` 참조 모든 곳 검색 (rank=0 의존 코드 식별)
- 테스트 파일 `test_sector_score.py` 현재 테스트 케이스 분석

**검증**: pytest (test_sector_score.py 수정), 런타임 기동, ruff

### Step 2: 백엔드 — 호출처 + 매수 필터 + 스냅샷 전파

**대상 파일** (4개):
1. `backend/app/services/engine_sector_confirm.py`
   - `_flush_sector_recompute_impl()`, `_full_recompute()` — 만점 파라미터 3개 → 슬라이더 파라미터 3개
2. `backend/app/services/sector_data_provider.py`
   - `recompute_sector_summary_now()` — 파라미터 변경
   - `get_sector_scores_snapshot()` — `is_cutoff_passed` 필드 추가
3. `backend/app/domain/buy_filter.py`
   - `sc.rank == 0` → `not sc.is_cutoff_passed` 매수 제외 조건 변경
4. `backend/app/services/engine_service.py`
   - 설정 키 목록 갱신 (만점 3개 제거, 슬라이더 3개 추가)

**검증**: pytest (test_engine_sector_confirm.py, test_buy_filter.py 수정), 런타임 기동

### Step 3: 프론트엔드 — 설정 패널 + 타입

**대상 파일** (3개):
1. `frontend/src/types/index.ts`
   - `AppSettings`: 만점 3개 제거, 슬라이더 3개 추가
   - `SectorScoreRow`: `is_cutoff_passed: boolean` 추가
2. `frontend/src/pages/sector-settings.ts`
   - 만점 숫자 입력 3개 제거 → 슬라이더 3개 추가 (`createSlider()` 재사용)
   - 만점 자동 표시 ("현재 만점 = N점 (업종 N개)")
3. `frontend/src/pages/sector-ranking-list.ts`
   - `rank === 0` → `is_cutoff_passed` 기반 표시 변경
   - 통과 카운트 표시 로직 변경 (`rank > 0` → `is_cutoff_passed`)

**검증**: TypeScript typecheck, 빌드, 브라우저 확인

### Step 4: 테스트 + 문서 갱신

**대상 파일** (테스트 3개 + 문서 2개):
1. `backend/tests/test_sector_score.py` — 만점 자동화, 슬라이더, 가중 순위 합, is_cutoff_passed 테스트 전면 재작성
2. `backend/tests/test_engine_sector_confirm.py` — 만점 파라미터 → 슬라이더 파라미터 mock 변경
3. `backend/tests/test_buy_filter.py` — `rank == 0` → `is_cutoff_passed` 테스트 변경
4. `ARCHITECTURE.md` — 업종 점수 계산 방식 설명 갱신
5. `HANDOVER.md` — 작업 완료 기록

**검증**: pytest 전체, 런타임 기동, ruff, typecheck, 빌드

---

## 6. 다음 세션에서 할 일

1. 본 계획서를 바탕으로 **Step 1에 대한 심도 있는 사전조사** 수행
   - 영향 받는 모든 파일, 함수, 변수, 호출 경로 식별
   - `percentile_to_score()` 잔존 참조 전체 검색
   - `rank_to_tiered_score()` int 반환 의존 코드 검색
   - `SectorScore.rank` 참조 모든 곳 검색
2. 조사 결과를 바탕으로 **정밀한 리팩토링 계획서** 작성 (본 파일에 추가 또는 별도)
3. 계획서 검토 완료 후 Step 1 수정 진행
