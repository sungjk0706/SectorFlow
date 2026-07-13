# 업종 점수 누적 가산점제 전환 수정 계획서

> **작성일**: 2026-07-13
> **상태**: 계획 수립 (사전 조사 완료, 구현 대기)
> **방향**: 가중치 슬라이더 방식 → 3단계 누적 가산점 방식 + 트리밍 제거
> **전제**: 본 계획서는 정밀 사전 조사 기반. 구현은 별도 세션에서 사용자 승인 후 진행.

---

## 1. 배경 및 목적

### 1.1 현재 구조의 문제

현재 업종 점수 시스템은 2개 지표의 가중치 합산 방식:
- `total_trade_amount` (거래대금) — 기본 가중치 0.5
- `rise_ratio` (상승종목비율) — 기본 가중치 0.5
- 사용자가 설정 페이지에서 듀얼 슬라이더로 두 지표의 비중을 조절

문제점:
1. **상승비율 지표의 정보 손실**: `rise_ratio`는 이진 판단. +0.01% 오른 종목이나 +30% 오른 종목이나 동일하게 "상승 1건"으로 카운트 (`sector_calculator.py:132`).
2. **가중치 슬라이더의 주관 왜곡**: 사용자가 비중을 정하는 것 자체가 왜곡. 약세장/강세장에 따라 적정 비중이 달라지므로 고정 가중치는 근본적으로 한계.
3. **종목 수 왜곡 미해결**: 4종목 업종과 20종목 업종을 동일한 상승비율 기준으로 비교. 트리밍 10%는 `round(4×0.1)=0`이므로 5종목 이하 업종에서 작동하지 않음 (`sector_calculator.py:140-152`).

### 1.2 전환 방향

사용자와의 대화를 통해 도달한 설계 방향:
1. **가중치 슬라이더 삭제** — 주관 개입 제거
2. **3단계 누적 가산점 도입** — 의미론적 순서 기반 점수 누적
3. **2차 가산점 = 상대평가** — 통과 업종 종목들만 모집단으로 상대 비교. 임계값 없음.
4. **매수 설정 가산점 패턴과 일관성 유지** (P23) — `boost_score` 구조와 동일 패턴
5. **트리밍 제거** — 순위/백분위 기반 점수에서 절대값 이상치 영향 감소하므로 트리밍 불필요. 종목 수 비대칭 적용 왜곡(4종목 업종은 `round(4×0.1)=0`으로 트리밍 미작동) 제거. 관련 설정 UI도 함께 제거.

### 1.3 핵심 설계 원칙

- **왜곡 회피**: 절대 임계값 없음, 사용자 주관 개입 없음, 종목 수 무관, 트리밍 인위적 잘라내기 없음
- **상대평가**: 차단 필터 통과 업종들의 종목들만 모집단 → 백분위 점수 → 업종별 평균
- **부하 최소**: 이미 계산된 데이터 재사용, 추가 연산 O(N log N) 1회

---

## 2. 새 점수 구조: 3단계 누적 가산점

### 2.1 전체 흐름

```
[기존 필터 ①] 5일평균거래대금 N억 이하 차단 (변경 없음)
    ↓
[기존 필터 ③] 업종내 종목 상승비율 N% 이하 차단 (변경 없음)
    ↓
[1차 가산점] 업종 내 상승 종목 비율 (0~100점)
    ↓
[2차 가산점] 통과 업종 종목들만 모집단 → 백분위 점수 → 업종별 평균 (0~100점) ← 신규
    ↓
[3차 가산점] 업종 거래대금 평균 (0~100점)
    ↓
[종합 점수] 3개 합산 (0~300점) → 내림차순 정렬 → 순위 부여
```

### 2.2 각 단계 상세

#### 1차 가산점: 업종 내 상승 종목 비율 (0~100점)

- **의미**: 상승이 얼마나 넓게 퍼졌는가 (참여 폭)
- **데이터**: `rise_ratio` (전체 종목 기준 상승비율, 트리밍 미적용)
- **점수 변환**: `rank_to_score` 적용 — 업종들 사이에서 상승비율 순위 → 0~100점
- **변경**: 트리밍 제거로 `scored_rise_ratio` 대신 `rise_ratio` 사용

#### 2차 가산점: 통과 업종 종목들 상대평가 (0~100점) ← 신규

- **의미**: 상승이 얼마나 강한가 (상승 폭) — "많이 오른 종목들이 많은 업종"
- **모집단**: 차단 필터(①, ③) 통과한 업종들에 속한 종목들 **만**
- **계산 로직**:
  1. 통과 업종들의 모든 종목을 하나의 모집단으로 수집
  2. 각 종목에 등락률(`change_rate`) 기준 백분위 점수 부여 (0~100)
     - 가장 많이 오른 종목 = 100점
     - 중간 = 50점
     - 가장 하락 = 0점
  3. 업종별로 소속 종목들의 백분위 점수 **평균** 계산
  4. 평균이 높은 업종 = "많이 오른 종목들이 많은 업종"
- **왜곡 회피**:
  - 평균 사용 → 종목 수 무관 (4종목 업종이나 20종목 업종이나 동일 0~100 스케일)
  - 백분위(순위) 기반 → +30% 급등 1개가 점수 왜곡하지 않음 (순위만 반영)
  - 통과 업종들만 모집단 → 탈락 업종 하락 종목이 기준을 낮추지 않음
  - 임계값 없음 → 사용자 주관 개입 없음

#### 3차 가산점: 업종 거래대금 평균 (0~100점)

- **의미**: 거래대금이 얼마나 많은가 (신뢰도/유동성)
- **데이터**: `total_trade_amount` (전체 종목 기준 거래대금 평균, 트리밍 미적용)
- **점수 변환**: `rank_to_score` 적용 — 업종들 사이에서 거래대금 순위 → 0~100점
- **변경**: 트리밍 제거로 `scored_trade_amount` 대신 `total_trade_amount` 사용
- **1개 대형주 영향**: 1개 대형주(거래대금 1000억)가 있는 4종목 업종의 평균이 332.5억이 되어 20종목 전부 50억인 업종보다 3차 가산점에서 유리. 단, 2차 가산점(백분위 평균)이 부분 보완 — 대형주 1개만 있고 나머지 종목들이 안 오른 업종은 2차 가산점이 낮아 균형 유지.

### 2.3 종합 점수 계산

```
final_score = 1차_가산점 + 2차_가산점 + 3차_가산점  (0~300점)
```

- 정렬: `final_score` 내림차순, 동점 시 2차 가산점 내림차순 → 1차 가산점 내림차순 → 업종명 오름차순
- 순위 부여: 1-based (컷오프 통과 업종만 rank 부여, 미달 업종은 rank=0)

### 2.4 백분위 점수 계산 로직 (신규 함수)

현재 `rank_to_score` 공식: `(N - rank + 1) / N × 100`
- 1위 = 100점, 꼴찌 = `1/N × 100`점 (0이 아님)
- 완전한 0~100 백분위를 위해 별도 함수 필요

**신규 함수 `percentile_to_score`**:
```python
def percentile_to_score(values: list[float], higher_is_better: bool = True) -> list[float]:
    """
    원시값 리스트를 백분위 점수(0~100)로 변환.
    - 가장 큰 값 = 100, 가장 작은 값 = 0
    - 동점 처리: 같은 값은 같은 점수
    - 빈 리스트면 빈 리스트, N=1이면 100점
    """
    # 정렬 후 (rank-1)/(N-1) × 100 공식 사용
    # N=1인 경우 100점 (단일 종목 = 유일한 기준)
```

**`rank_to_score`와의 차이**:
- `rank_to_score`: 꼴찌도 `1/N×100`점 (0점 아님) — 업종 간 순위 비교용
- `percentile_to_score`: 꼴찌 = 0점 — 종목 간 상대 비교용 (0~100 완전 스케일)

**재사용 가능성**: `rank_to_score`는 1차/3차 가산점(업종 간 순위)에 그대로 사용. `percentile_to_score`는 2차 가산점(종목 간 백분위)에 신규 추가.

### 2.5 트리밍 제거 (신규)

#### 2.5.1 트리밍의 역사적 배경

트리밍(상승률 상/하위 N%, 거래대금 상/하위 N% 종목 제외)은 min-max 정규화 시절에 이상치 왜곡을 막기 위해 도입. 절대값 기반 정규화에서 1개 극단 종목이 점수를 왜곡하는 것을 방지하려는 목적.

#### 2.5.2 제거 근거

1. **순위/백분위 기반에서 절대값 왜곡 영향 감소**: `rank_to_score`와 `percentile_to_score`는 순위만 반영하므로, 1개 극단 종목의 절대값이 점수를 왜곡하지 않음. 트리밍의 원래 목적이 구조적으로 해결됨.
2. **종목 수 비대칭 적용 왜곡**: 4종목 업종은 `round(4×0.1)=0`으로 트리밍 미작동, 20종목 업종만 트리밍 적용 → 업종 간 비대칭 → 자체가 왜곡 (`sector_calculator.py:140-152`).
3. **등락률 트리밍은 처음부터 효과 미미**: `scored_rise_ratio`는 이진 카운트(`change_rate > 0`) 기반이므로, 상하위 종목을 잘라내도 상승/하락 여부만 카운트 → 극단 등락률 제거가 상승비율에 미치는 영향 제한적.
4. **데이터 정합성(P22) 관점**: 인위적 잘라내기는 실제 데이터를 변형. 원본 데이터 기반 순위가 더 정직한 평가.

#### 2.5.3 제거 범위

**백엔드**:
- `backend/app/domain/sector_calculator.py`:
  - L137-152: 등락률 트리밍 로직 전체 제거. `scored_rise_ratio` = `raw_rise_ratio` (또는 `scored_rise_ratio` 필드 자체 제거, `rise_ratio`로 통일)
  - L154-166: 거래대금 트리밍 로직 전체 제거. `scored_trade_amount` = `raw_total_ta / len(filtered_stocks)` (또는 `scored_trade_amount` 필드 자체 제거, `total_trade_amount`로 통일)
  - `trim_trade_amt_pct`, `trim_change_rate_pct` 파라미터 제거
- `backend/app/domain/models.py`:
  - `SectorScore.scored_rise_ratio` 필드 제거 → `rise_ratio`로 통일
  - `SectorScore.scored_trade_amount` 필드 제거 → `total_trade_amount`로 통일
- `backend/app/services/engine_sector_confirm.py`:
  - L114-115: `trim_trade`, `trim_change` 변수 제거
  - L133-134: `trim_trade_amt_pct`, `trim_change_rate_pct` 인자 제거
  - L223-224, L232-233: 동일 인자 제거
- `backend/app/services/sector_data_provider.py`:
  - L246-247: `trim_trade`, `trim_change` 변수 제거
  - L256-257: `trim_trade_amt_pct`, `trim_change_rate_pct` 인자 제거
- `backend/app/core/settings_defaults.py`:
  - `sector_trim_trade_amt_pct` 기본값 제거 (L83)
  - `sector_trim_change_rate_pct` 기본값 제거 (L84)
- `backend/app/core/engine_settings.py`: 트리밍 관련 설정 키 처리 제거

**프론트엔드**:
- `frontend/src/pages/sector-settings.ts`:
  - ④ 극단값 제외 섹션 전체 제거 (L178-205) — `trimChangeRateInput`, `trimTradeAmtInput` 및 관련 DOM/저장 로직
  - `NUM_KEYS`에서 `sector_trim_change_rate_pct`, `sector_trim_trade_amt_pct` 제거
  - `syncFromSettings`에서 트리밍 입력 동기화 제거 (L97-98)
- `frontend/src/types/index.ts`:
  - `AppSettings`에서 `sector_trim_trade_amt_pct`, `sector_trim_change_rate_pct` 제거

**테스트**:
- `backend/tests/test_sector_calculator.py`: `TestComputeSectorScoresTrimming` 제거 (L233-321)
- 트리밍 관련 테스트 케이스 전체 제거

#### 2.5.4 필드 통합 정리

트리밍 제거 시 `scored_*` 필드와 `raw_*` 필드가 동일해지므로 필드 통합:

| 기존 필드 | 통합 후 필드 | 비고 |
|----------|-------------|------|
| `scored_rise_ratio` | 제거 → `rise_ratio` 사용 | 1차 가산점 원시값 |
| `scored_trade_amount` | 제거 → `total_trade_amount` 사용 | 3차 가산점 원시값 |

**주의**: `total_trade_amount`는 기존에 "업종 평균 거래대금 (원) — 표시용"으로 정의 (`models.py:42`). 트리밍 제거 후 점수 계산에도 사용하므로, 정확히는 "업종 평균 거래대금"으로 단일 역할. 기존 `scored_trade_amount`가 평균이었으므로 `total_trade_amount`도 평균으로 재정의 필요 (또는 `avg_trade_amount`로 명명 변경 검토).

#### 2.5.5 섹션 번호 재정렬

트리밍(④) 제거 시 설정 페이지 섹션 번호 재정렬:
- 기존: ① 5일평균거래대금 / ② 업종순위 수신율 / ③ 업종 컷오프 / ④ 극단값 제외 / ⑤ 점수 가중치 / ⑥ ...
- 변경 후: ① 5일평균거래대금 / ② 업종순위 수신율 / ③ 업종 컷오프 / ④ (기존 ⑥) ...
- ④ 극단값 제외 + ⑤ 점수 가중치 모두 제거 → 이후 섹션 번호 앞당김

---

## 3. 매수 설정 가산점 패턴과의 일관성 (P23)

### 3.1 매수 설정 기존 가산점 구조 (`buy_filter.py:8-61`)

```
boost_score = 0.0
if boost_high_on and (조건 만족): score += boost_high_score
if boost_order_ratio_on and (조건 만족): score += boost_order_ratio_score
if boost_program_net_buy_on and (조건 만족): score += boost_program_net_buy_score
if boost_trade_amount_rank_on and (조건 만족): score += boost_trade_amount_rank_score
return max(score, 0.0)
```

패턴:
- 각 가산점 항목 = `on/off` 스위치 + `score` 점수값(기본 1.0)
- 조건 만족 시 score 값 누적 합산
- 정렬 시 `boost_score` 내림차순이 1순위 기준

### 3.2 업종 점수 가산점 적용 방식

매수 설정은 "조건 만족 여부" 기반(이진)이지만, 업종 점수는 "순위/백분위" 기반(연속값). 따라서:

- **동일 패턴**: 누적 합산 방식, 각 단계 독립 점수
- **차이**: on/off 스위치 없음 (3단계 모두 항상 적용), 점수 범위 0~100 (매수 설정은 0~N)

이 차이는 정당함:
- 매수 설정 가산점 = "특정 조건 만족 종목에 추가 가산" (조건부)
- 업종 점수 가산점 = "모든 업종을 3개 기준으로 순위화 후 누적" (필수)

P23 일관성은 "누적 합산 방식"과 "각 단계 독립 점수" 구조에서 달성됨.

---

## 4. 변경 영향 범위 전수 조사 결과

### 4.1 백엔드 — 높음 (전면 수정)

| 파일 | 영향도 | 변경 내용 |
|------|--------|----------|
| `backend/app/domain/models.py` | 높음 | `MetricDef`, `DEFAULT_METRICS` 제거. `SectorScore` 필드 수정: `metric_scores` 제거, `scored_rise_ratio`/`scored_trade_amount` 제거(트리밍 제거), `bonus_rise_ratio`, `bonus_relative_strength`, `bonus_trade_amount` 신규 필드 추가. `final_score` 유지 (0~300 스케일). |
| `backend/app/domain/sector_score.py` | 높음 | `normalize_weight_values` 제거. `calculate_weighted_scores` 재작성 → `calculate_bonus_scores` (3단계 가산점 합산). `rank_to_score` 유지. `percentile_to_score` 신규 추가. |
| `backend/app/domain/sector_calculator.py` | 높음 | `sector_weights` 파라미터 제거. `trim_trade_amt_pct`/`trim_change_rate_pct` 파라미터 제거(트리밍 제거). 등락률 트리밍 로직(L137-152) + 거래대금 트리밍 로직(L154-166) 제거. `scored_rise_ratio`/`scored_trade_amount` 계산 제거 → `rise_ratio`/`total_trade_amount` 사용. `compute_sector_scores`, `compute_full_sector_summary`에서 `calculate_weighted_scores` 호출부 → `calculate_bonus_scores`로 교체. 2차 가산점용 백분위 계산 로직 추가. |
| `backend/app/services/engine_sector_confirm.py` | 높음 | `sector_weights` 참조 제거 (L116, L132, L155, L231). `trim_trade`/`trim_change` 변수 제거 (L114-115, L223-224). `trim_trade_amt_pct`/`trim_change_rate_pct` 인자 제거 (L133-134, L232-233). `calculate_weighted_scores` 호출 → `calculate_bonus_scores`로 교체. |
| `backend/app/core/settings_defaults.py` | 높음 | `sector_weights` 기본값 제거 (L85). `sector_trim_trade_amt_pct` 기본값 제거 (L83). `sector_trim_change_rate_pct` 기본값 제거 (L84). |
| `backend/app/core/engine_settings.py` | 높음 | `sector_weights` 빌드/검증 제거 (L132-136). 트리밍 관련 설정 키 처리 제거. |
| `backend/app/core/settings_file.py` | 높음 | `_migrate_sector_weights` 함수 제거 (L27-41, L302). |
| `backend/app/services/sector_data_provider.py` | 중간 | `sector_weights` 참조 제거 (L248, L255). `trim_trade`/`trim_change` 변수 제거 (L246-247). `trim_trade_amt_pct`/`trim_change_rate_pct` 인자 제거 (L256-257). `get_sector_scores_snapshot` payload에 신규 가산점 필드 추가 (L217-224). `scored_trade_amount` → `total_trade_amount` 참조 변경. |
| `backend/app/services/engine_account_notify.py` | 중간 | `normalize_weight_values` import 제거 (L282). `normalized_weights` 계산/전송 제거 (L286-287, L325, L343). |
| `backend/app/services/telegram_bot.py` | 낮음 | `scored_trade_amount` 참조 → `total_trade_amount` 또는 `final_score`로 대체 (L460, L472). |
| `backend/app/domain/buy_filter.py` | 낮음 | 변경 없음 (rank 기반 필터링만 사용, 점수 필드 미참조). |
| `backend/app/pipelines/pipeline_compute.py` | 낮음 | 변경 없음 (간접 호출만). |
| `backend/app/services/engine_snapshot.py` | 낮음 | 변경 없음 (간접 참조만). |
| `backend/app/services/engine_service.py` | 낮음 | 설정 키 목록에서 `sector_weights` 참조 제거 (L160). |

### 4.2 프론트엔드 — 중간

| 파일 | 영향도 | 변경 내용 |
|------|--------|----------|
| `frontend/src/pages/sector-settings.ts` | 높음 | ⑤ 점수 가중치 섹션 전체 제거 (L207-247). ④ 극단값 제외 섹션 전체 제거 (L178-205) — `trimChangeRateInput`/`trimTradeAmtInput` 및 관련 DOM/저장 로직. `dualSlider` 변수/함수 제거 (L46, L72-83, L217-235). `saveWeightsNow` 제거 (L72-77). `updateAppliedWeightsLabel` 제거 (L52-61). `syncFromSettings` 가중치/트리밍 동기화 제거 (L91-98). `NUM_KEYS`에서 `sector_trim_change_rate_pct`/`sector_trim_trade_amt_pct` 제거. `prevNormalizedWeights` 제거 (L322). uiStore 구독 normalizedWeights 갱신 제거 (L338-341). unmount dualSlider.destroy 제거 (L361-364). 섹션 번호 재정렬 (④⑤ 제거 → 이후 섹션 앞당김). |
| `frontend/src/pages/sector-ranking-list.ts` | 중간 | `updateRankingRows` 점수 표시 로직 수정 (L150-153). 헤더 행 조정 (L196-202) — "종합점수" → "가산점" 또는 3단계 컬럼 추가 검토. 바 그래프 로직 조정 (L154-155). |
| `frontend/src/types/index.ts` | 중간 | `sector_weights` 타입 제거 (L147). `sector_trim_trade_amt_pct`/`sector_trim_change_rate_pct` 타입 제거. `SectorStatus.normalized_weights` 제거 (L241). `SectorScoreRow`에 신규 가산점 필드 추가. |
| `frontend/src/stores/uiStore.ts` | 중간 | `normalizedWeights` 상태 필드 제거 (L58, L84). |
| `frontend/src/binding.ts` | 낮음 | `normalized_weights` 수신 제거 (L300). sector-scores 이벤트 바인딩은 유지. |
| `frontend/src/stores/hotStore.ts` | 낮음 | `applySectorScores` 변경 없음 (새 필드 자동 처리). |
| `frontend/src/utils/sliderConvert.ts` | 낮음 | 삭제 검토 (다른 곳에서 미사용 시). |
| `frontend/src/components/common/create-slider.ts` | 낮음 | `createDualLabelSlider` 삭제 검토 (다른 곳에서 미사용 시). |

### 4.3 테스트 — 높음 (전면 수정)

| 파일 | 변경 내용 |
|------|----------|
| `backend/tests/test_sector_score.py` | `TestNormalizeWeightValues` 제거. `TestCalculateWeightedScores` → `TestCalculateBonusScores` 재작성. `TestRankToScore` 유지. `TestPercentileToScore` 신규 추가. |
| `backend/tests/test_sector_calculator.py` | `TestComputeSectorScoresWithWeights` 제거 → `TestComputeSectorScoresWithBonus` 재작성. 가중치 테스트 → 가산점 테스트. `TestComputeSectorScoresTrimming` 제거 (L233-321, 트리밍 제거). 트리밍 파라미터 관련 테스트 제거. |
| `backend/tests/test_sector_calculator_integration.py` | 가중치 점수 계산 테스트 → 가산점 계산 테스트. |
| `backend/tests/test_engine_sector_confirm.py` | `calculate_weighted_scores` mock → `calculate_bonus_scores` mock 교체 (8개 테스트). |
| `backend/tests/test_settings_file.py` | `TestMigrateSectorWeights` 제거 (27개 테스트). |
| `backend/tests/test_engine_settings.py` | `sector_weights` 기본값 검증 제거 (L64). |
| `backend/tests/test_sector_data_provider.py` | `final_score`, `scored_trade_amount` 관련 테스트 → 신규 가산점 필드로 수정. |
| `backend/tests/test_settings_boost_order_ratio.py` | 변경 없음 (매수 설정 가산점 테스트, 업종 점수와 무관). |
| `backend/tests/test_buy_filter.py` | 헬퍼 함수 `scored_trade_amount`, `scored_rise_ratio` 참조 → 신규 필드로 수정. |
| `backend/tests/test_telegram_bot.py` | `scored_trade_amount` 참조 → 신규 필드로 수정 (L1167, L1220). |
| `backend/tests/test_pipeline_compute.py` | mock 데이터 `final_score` 유지, 가산점 필드 추가. |

---

## 5. 상세 구현 계획

### 5.1 Phase 1: 백엔드 도메인 모델 및 점수 계산 로직

#### 5.1.1 `backend/app/domain/models.py`

**제거**:
- `MetricDef` dataclass (L76-84)
- `DEFAULT_METRICS` 리스트 (L86-99)
- `SectorScore.scored_trade_amount` 필드 (트리밍 제거로 `total_trade_amount`와 통합)
- `SectorScore.scored_rise_ratio` 필드 (트리밍 제거로 `rise_ratio`와 통합)
- `SectorScore.metric_scores` 필드

**수정 — `SectorScore` dataclass**:
```python
@dataclass
class SectorScore:
    """업종 단위 강도 스코어 — 누적 가산점제."""
    sector: str
    total: int
    rise_count: int
    rise_ratio: float
    avg_change_rate: float
    total_trade_amount: int     # 업종 평균 거래대금 (원) — 표시용 + 3차 가산점 원시값
    avg_ratio_5d_pct: float
    rank: int = 0
    stocks: list[StockScore] = field(default_factory=list)
    # ── 누적 가산점 (신규) ──
    bonus_rise_ratio: float = 0.0           # 1차: 상승비율 순위 점수 (0~100)
    bonus_relative_strength: float = 0.0    # 2차: 통과 업종 종목 상대평가 평균 (0~100)
    bonus_trade_amount: float = 0.0         # 3차: 거래대금 순위 점수 (0~100)
    final_score: float = 0.0                # 종합 = 1차 + 2차 + 3차 (0~300)
```

**참고**: `total_trade_amount`는 기존 "표시용" 정의에서 "표시용 + 3차 가산점 원시값"으로 역할 확장. 트리밍 제거로 `scored_trade_amount`와 동일해지므로 단일 필드로 통합.

#### 5.1.2 `backend/app/domain/sector_score.py`

**제거**:
- `normalize_weight_values` 함수 (L51-74)

**수정 — `calculate_weighted_scores` → `calculate_bonus_scores`**:
```python
def calculate_bonus_scores(
    sector_scores: list,  # list[SectorScore]
) -> None:
    """
    3단계 누적 가산점 계산 — in-place 설정.

    1차: 상승비율 순위 점수 (rank_to_score)
    2차: 통과 업종 종목들 백분위 평균 (percentile_to_score)
    3차: 거래대금 순위 점수 (rank_to_score)
    final_score = 1차 + 2차 + 3차 (0~300)
    """
    if not sector_scores:
        return

    # 1차: 상승비율 순위 점수
    rise_values = [sc.rise_ratio for sc in sector_scores]
    rise_scores = rank_to_score(rise_values, higher_is_better=True)
    for sc, s in zip(sector_scores, rise_scores):
        sc.bonus_rise_ratio = s

    # 2차: 통과 업종 종목들 백분위 평균
    # 통과 업종(rank > 0 또는 컷오프 통과)의 종목들만 모집단
    pass_sectors = [sc for sc in sector_scores if sc.rank > 0]  # 또는 별도 통과 플래그
    all_pass_stocks = [s for sc in pass_sectors for s in sc.stocks]
    if all_pass_stocks:
        change_rates = [s.change_rate for s in all_pass_stocks]
        percentile_scores = percentile_to_score(change_rates, higher_is_better=True)
        # 종목 → 백분위 점수 매핑
        stock_score_map = {s.code: ps for s, ps in zip(all_pass_stocks, percentile_scores)}
        for sc in pass_sectors:
            sector_stock_scores = [stock_score_map[s.code] for s in sc.stocks if s.code in stock_score_map]
            sc.bonus_relative_strength = round(
                sum(sector_stock_scores) / len(sector_stock_scores), 1
            ) if sector_stock_scores else 0.0
    # 미통과 업종은 bonus_relative_strength = 0.0 유지

    # 3차: 거래대금 순위 점수
    trade_values = [float(sc.total_trade_amount) for sc in sector_scores]
    trade_scores = rank_to_score(trade_values, higher_is_better=True)
    for sc, s in zip(sector_scores, trade_scores):
        sc.bonus_trade_amount = s

    # 종합 점수
    for sc in sector_scores:
        sc.final_score = round(
            sc.bonus_rise_ratio + sc.bonus_relative_strength + sc.bonus_trade_amount, 1
        )

    # 정렬: final_score 내림차순, 동점 시 2차→1차→업종명
    sector_scores.sort(
        key=lambda s: (
            -s.final_score,
            -s.bonus_relative_strength,
            -s.bonus_rise_ratio,
            s.sector,
        ),
    )

    # 순위 부여 (1-based) — 컷오프는 별도 처리 (engine_sector_confirm.py에서 수행)
    for i, sc in enumerate(sector_scores):
        sc.rank = i + 1
```

**신규 추가 — `percentile_to_score`**:
```python
def percentile_to_score(
    values: list[float],
    higher_is_better: bool = True,
) -> list[float]:
    """
    원시값 리스트를 백분위 점수(0~100)로 변환.
    - 가장 큰 값 = 100, 가장 작은 값 = 0
    - 동점 처리: 같은 값은 같은 점수
    - 빈 리스트면 빈 리스트, N=1이면 100점
    """
    if not values:
        return []
    n = len(values)
    if n == 1:
        return [100.0]

    indexed = list(enumerate(values))
    indexed.sort(key=lambda x: x[1], reverse=higher_is_better)

    scores = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        # 백분위: (rank-1)/(N-1) × 100 — 꼴찌=0, 1위=100
        score = round((i) / (n - 1) * 100.0, 1)
        for k in range(i, j):
            orig_idx = indexed[k][0]
            scores[orig_idx] = score
        i = j

    return scores
```

#### 5.1.3 `backend/app/domain/sector_calculator.py`

**수정 — `compute_sector_scores`**:
- `sector_weights` 파라미터 제거 (L22)
- `trim_trade_amt_pct` 파라미터 제거 (L23) — 트리밍 제거
- `trim_change_rate_pct` 파라미터 제거 (L24) — 트리밍 제거
- L137-152: 등락률 트리밍 로직 전체 제거. `scored_rise_ratio` 계산 제거, `rise_ratio`(`raw_rise_ratio`) 사용
- L154-166: 거래대금 트리밍 로직 전체 제거. `scored_ta` 계산 제거, `total_trade_amount`(`raw_total_ta / len(filtered_stocks)`) 사용
- L178-179: `SectorScore` 생성 시 `scored_trade_amount`/`scored_rise_ratio` 필드 제거 (또는 `total_trade_amount`/`rise_ratio`로 통합)
- `calculate_weighted_scores(sector_scores, weights=sector_weights)` → `calculate_bonus_scores(sector_scores)` (L183)

**수정 — `compute_full_sector_summary`**:
- `sector_weights` 파라미터 제거 (L203)
- `trim_trade_amt_pct` 파라미터 제거 — 트리밍 제거
- `trim_change_rate_pct` 파라미터 제거 — 트리밍 제거
- `calculate_weighted_scores` 호출 → `calculate_bonus_scores`로 교체 (L231)

### 5.2 Phase 2: 백엔드 서비스/설정

#### 5.2.1 `backend/app/services/engine_sector_confirm.py`

**수정 — `_flush_sector_recompute_impl`**:
- L114-115: `trim_trade`/`trim_change` 변수 제거 — 트리밍 제거
- L116: `sector_weights = state.integrated_system_settings_cache["sector_weights"]` 제거
- L132: `sector_weights=sector_weights` 인자 제거
- L133-134: `trim_trade_amt_pct=trim_trade`/`trim_change_rate_pct=trim_change` 인자 제거 — 트리밍 제거
- L155: `calculate_weighted_scores(merged, weights=sector_weights)` → `calculate_bonus_scores(merged)`

**수정 — `_full_recompute`**:
- L223-224: `trim_trade`/`trim_change` 변수 제거 — 트리밍 제거
- L232-233: `trim_trade_amt_pct`/`trim_change_rate_pct` 인자 제거 — 트리밍 제거
- L231: `sector_weights=state.integrated_system_settings_cache["sector_weights"]` 인자 제거

#### 5.2.2 `backend/app/services/sector_data_provider.py`

**수정 — `get_sector_scores_snapshot`** (L217-224):
```python
out.append({
    "rank": sc.rank,
    "sector": sc.sector,
    "final_score": round(sc.final_score, 1),
    "bonus_rise_ratio": round(sc.bonus_rise_ratio, 1),        # 신규
    "bonus_relative_strength": round(sc.bonus_relative_strength, 1),  # 신규
    "bonus_trade_amount": round(sc.bonus_trade_amount, 1),   # 신규
    "total_trade_amount": sc.total_trade_amount,  # scored_trade_amount → total_trade_amount (트리밍 제거)
    "rise_ratio": round(sc.rise_ratio * 100, 1),
    "total": sc.total,
})
```

**수정 — `recompute_sector_summary_now`**:
- L246-247: `trim_trade`/`trim_change` 변수 제거 — 트리밍 제거
- L248: `sector_weights = state.integrated_system_settings_cache["sector_weights"]` 제거
- L255: `sector_weights=...` 인자 제거
- L256-257: `trim_trade_amt_pct=trim_trade`/`trim_change_rate_pct=trim_change` 인자 제거 — 트리밍 제거

#### 5.2.3 `backend/app/services/engine_account_notify.py`

**수정 — `notify_desktop_sector_scores`**:
- L282: `from backend.app.domain.sector_score import normalize_weight_values` 제거
- L286-287: `raw_weights`, `normalized_weights` 계산 제거
- L325, L343: `"normalized_weights": normalized_weights` payload 필드 제거

#### 5.2.4 `backend/app/core/settings_defaults.py`

- L83: `"sector_trim_trade_amt_pct": 10.0` 제거 — 트리밍 제거
- L84: `"sector_trim_change_rate_pct": 10.0` 제거 — 트리밍 제거
- L85: `"sector_weights": {"rise_ratio": 0.5, "total_trade_amount": 0.5}` 제거

#### 5.2.5 `backend/app/core/engine_settings.py`

- L132-136: `sector_weights` 빌드/정합성 검증 제거

#### 5.2.6 `backend/app/core/settings_file.py`

- L27-41: `_migrate_sector_weights` 함수 제거
- L302: `_migrate_sector_weights` 호출 제거

#### 5.2.7 `backend/app/services/engine_service.py`

- L160: 설정 키 목록에서 `sector_weights` 제거

#### 5.2.8 `backend/app/services/telegram_bot.py`

- L460, L472: `scored_trade_amount` 참조 → `bonus_trade_amount` 또는 `final_score`로 대체

### 5.3 Phase 3: 프론트엔드

#### 5.3.1 `frontend/src/pages/sector-settings.ts`

**제거 — ④ 극단값 제외 섹션 전체** (L178-205) — 트리밍 제거:
- `trimRow`, `leftCol`, `rightCol` DOM 요소
- `trimChangeRateInput` 생성 및 `onNumChange('sector_trim_change_rate_pct', v)` 호출
- `trimTradeAmtInput` 생성 및 `onNumChange('sector_trim_trade_amt_pct', v)` 호출
- `createStepLabel('④', '상하위(N%) 종목 제외후 가중치 계산')` 라벨

**제거 — ⑤ 점수 가중치 섹션 전체** (L207-247):
- `weightLabel`, `weightDesc`, `weightWrap` DOM 요소
- `dualSlider` 생성 (L217-235)
- `appliedWeightsLabel` (L238-246)

**제거 — 관련 함수/변수**:
- `dualSlider` 변수 (L46)
- `trimChangeRateInput`/`trimTradeAmtInput` 변수 (트리밍 제거)
- `saveWeightsNow` 함수 (L72-77)
- `updateSliderUI` 함수 (L79-83)
- `updateAppliedWeightsLabel` 함수 (L52-61)
- `syncFromSettings` 내 가중치 동기화 (L91-93) + 트리밍 입력 동기화 (L97-98)
- `NUM_KEYS`에서 `sector_trim_change_rate_pct`/`sector_trim_trade_amt_pct` 제거
- `prevNormalizedWeights` 변수 (L322)
- uiStore 구독 normalizedWeights 갱신 (L338-341)
- unmount `dualSlider.destroy()` (L361-364)

**섹션 번호 재정렬**: ④ 극단값 제외 + ⑤ 점수 가중치 모두 제거 → 이후 섹션(⑥ 등)을 ④부터 재번호링. 또는 제거 자리에 "가산점 자동 계산" 안내문 추가 검토.

#### 5.3.2 `frontend/src/pages/sector-ranking-list.ts`

**수정 — `updateRankingRows`** (L150-153):
```typescript
const finalScore = s.final_score.toFixed(1)        // 종합 가산점 (0~300)
const riseRatio = s.rise_ratio.toFixed(1) + '%'     // 상승비율 (표시용)
const tradeAmt = (s.total_trade_amount / 100).toLocaleString('ko-KR', {...})
// 신규: 2차 가산점 표시 추가 검토
```

**수정 — 헤더 행** (L196-202):
- "종합점수" → "가산점" 라벨 변경
- 2차 가산점 컬럼 추가 검토 (화면 폭 고려)

**수정 — 바 그래프** (L154-155):
- `final_score` 기준 바 너비/색상 — 0~300 스케일로 조정

#### 5.3.3 `frontend/src/types/index.ts`

**제거**:
- L147: `sector_weights: Record<string, number>`
- `sector_trim_trade_amt_pct` 타입 제거 — 트리밍 제거
- `sector_trim_change_rate_pct` 타입 제거 — 트리밍 제거
- L241: `SectorStatus.normalized_weights`

**수정 — `SectorScoreRow`** (L228-235):
```typescript
export interface SectorScoreRow {
  rank: number;
  sector: string;
  final_score: number;          // 0~300 (종합 가산점)
  bonus_rise_ratio: number;     // 신규: 1차 가산점 (0~100)
  bonus_relative_strength: number;  // 신규: 2차 가산점 (0~100)
  bonus_trade_amount: number;   // 신규: 3차 가산점 (0~100)
  total_trade_amount: number;
  rise_ratio: number;
  total: number;
}
```

#### 5.3.4 `frontend/src/stores/uiStore.ts`

- L58: `normalizedWeights` 상태 필드 제거
- L84: 초기값 `normalizedWeights: null` 제거

#### 5.3.5 `frontend/src/binding.ts`

- L300: `normalized_weights` 수신 처리 제거 (sector-scores 이벤트 바인딩은 유지)

#### 5.3.6 삭제 검토 파일

- `frontend/src/utils/sliderConvert.ts` — 다른 곳에서 미사용 시 삭제
- `frontend/src/components/common/create-slider.ts` 중 `createDualLabelSlider` — 다른 곳에서 미사용 시 삭제

### 5.4 Phase 4: 테스트

#### 5.4.1 `backend/tests/test_sector_score.py`

**제거**:
- `TestNormalizeWeightValues` 클래스 전체

**재작성**:
- `TestCalculateWeightedScores` → `TestCalculateBonusScores` — 3단계 가산점 합산, 정렬, 순위 부여 테스트

**신규 추가**:
- `TestPercentileToScore` — 빈 리스트, 단일 값, 동점, 0~100 스케일, higher_is_better

**유지**:
- `TestRankToScore` — 기존 테스트 그대로 유지

#### 5.4.2 `backend/tests/test_sector_calculator.py`

**제거**:
- `TestComputeSectorScoresWithWeights` (L402-443)
- `TestComputeSectorScoresTrimming` (L233-321) — 트리밍 제거
- 트리밍 파라미터(`trim_trade_amt_pct`, `trim_change_rate_pct`) 관련 테스트 케이스 전체

**신규 추가**:
- `TestComputeSectorScoresWithBonus` — 3단계 가산점 계산 검증

#### 5.4.3 `backend/tests/test_sector_calculator_integration.py`

- 가중치 점수 계산 테스트 → 가산점 계산 테스트로 수정

#### 5.4.4 `backend/tests/test_engine_sector_confirm.py`

- `calculate_weighted_scores` mock → `calculate_bonus_scores` mock 교체 (8개 테스트)
- `sector_weights` 관련 mock 제거
- `trim_trade`/`trim_change` 관련 mock/인자 제거 — 트리밍 제거

#### 5.4.5 `backend/tests/test_settings_file.py`

- `TestMigrateSectorWeights` 제거 (27개 테스트)
- 트리밍 관련 설정 마이그레이션 테스트 제거 (있을 경우)

#### 5.4.6 `backend/tests/test_engine_settings.py`

- L64: `sector_weights` 기본값 검증 제거
- `sector_trim_trade_amt_pct`/`sector_trim_change_rate_pct` 기본값 검증 제거 — 트리밍 제거

#### 5.4.7 기타 테스트

- `test_sector_data_provider.py`: `final_score`, `scored_trade_amount` → 신규 가산점 필드 + `total_trade_amount`로 수정
- `test_buy_filter.py`: 헬퍼 함수 `scored_trade_amount`/`scored_rise_ratio` 참조 → `total_trade_amount`/`rise_ratio`로 수정
- `test_telegram_bot.py`: `scored_trade_amount` 참조 → `total_trade_amount` 또는 `final_score`로 수정 (L1167, L1220)
- `test_pipeline_compute.py`: mock 데이터 가산점 필드 추가, 트리밍 관련 mock 제거

---

## 6. 검증 계획

### 6.1 단위 테스트

- `percentile_to_score`: 빈 리스트, 단일 값, 동점, 0~100 스케일, higher_is_better
- `calculate_bonus_scores`: 3단계 합산, 정렬 순서, 동점 처리, 순위 부여
- `compute_sector_scores`: 가산점 계산 결과, 컷오프 동작
- **트리밍 제거 검증**: `compute_sector_scores` 호출 시 `trim_trade_amt_pct`/`trim_change_rate_pct` 파라미터 없이 정상 동작. 트리밍 미적용 시 `rise_ratio`/`total_trade_amount`가 전체 종목 기준값과 일치.

### 6.2 통합 테스트

- `compute_full_sector_summary`: DB 연동 가산점 계산
- `_flush_sector_recompute_impl`: 증분 재계산 시 가산점 갱신
- `recompute_sector_summary_now`: 설정 변경 시 재계산

### 6.3 런타임 기동 검증 (백엔드 수정 시 필수)

- `.venv/bin/python main.py` 기동
- 로그 확인: 업종 점수 계산 정상, 에러 없음
- 10~30초 대기 후 종료, 잔존 프로세스 확인

### 6.4 프론트엔드 빌드 검증

- `npm run build` — 타입 오류 없음
- 브라우저 확인:
  - 업종순위 페이지: 가산점 표시 정상
  - 업종순위 설정: ④ 극단값 제외 섹션 제거됨, ⑤ 가중치 슬라이더 제거됨, 다른 설정 정상 동작
  - WS sector-scores 이벤트 수신 정상

### 6.5 UI 검증 (사용자 확인 항목)

- 업종순위 페이지: 종합 가산점(0~300) 표시 정상
- 업종순위 설정: ④ 극단값 제외(트리밍) 섹션 사라짐 확인
- 업종순위 설정: ⑤ 가중치 슬라이더 사라짐 확인
- 업종순위 설정: ①~③ 설정 정상 동작 확인 (④⑤ 제거 후 번호 재정렬)
- 매수 후보 테이블: 업종 순위 기반 매수 타겟 정상 생성

---

## 7. 아키텍처 원칙 준수 검증

| 원칙 | 준수 여부 | 근거 |
|------|----------|------|
| P10 (SSOT) | 준수 | 트리밍 제거로 `scored_rise_ratio`/`scored_trade_amount` 제거 → `rise_ratio`/`total_trade_amount` 단일 소스로 통합. 2차 가산점은 `change_rate` 단일 소스에서 계산. |
| P16 (살아있는 경로) | 준수 | `percentile_to_score`, `calculate_bonus_scores` 모두 `compute_sector_scores` 경로에서 호출. 트리밍 로직 제거 시 참조하는 설정 키(`sector_trim_*`)도 함께 제거. |
| P20 (폴백 금지) | 준수 | 임계값/기본값 폴백 없음. 빈 리스트/단일 값은 명시적 처리 (0점 또는 100점). 트리밍 제거로 인위적 잘라내기 폴백도 제거. |
| P21 (사용자 투명성) | 준수 | `normalized_weights` 전송 제거 → 가산점 3단계 점수를 WS payload로 전송하여 사용자에게 투명하게 공개. 트리밍 UI 제거로 사용자에게 불필요한 설정 노출 제거. |
| P22 (데이터 정합성) | 준수 | 2차 가산점 모집단 = 컷오프 통과 업종 종목들. 필터 통과 여부와 모집단 일치. 트리밍 제거로 원본 데이터 변형 없이 정합성 유지. |
| P23 (일관된 통일성) | 준수 | 매수 설정 `boost_score` 누적 합산 패턴과 동일 구조. `rank_to_score` 재사용. |
| P24 (단순성) | 준수 | 가중치 슬라이더 + `normalize_weight_values` + `MetricDef` + 트리밍 로직/설정/UI 제거 → 구조 단순화. |

---

## 8. 리스크 및 고려사항

### 8.1 2차 가산점 모집단 정의

"통과 업종"의 정의:
- **옵션 A**: `rank > 0` (컷오프 통과 후 순위 부여된 업종)
- **옵션 B**: 별도 통과 플래그 (컷오프 통과 여부와 순위 부여 분리)

현재 `engine_sector_confirm.py:158-167`에서 컷오프 통과 업종에만 `rank` 부여. 따라서 **옵션 A**(`rank > 0`)가 자연스러움. 단, `calculate_bonus_scores` 호출 시점과 컷오프 적용 시점의 순서 주의 필요.

**시점 이슈**: `calculate_bonus_scores`가 `compute_sector_scores` 내부에서 호출되지만, 컷오프(`min_rise_ratio`) 적용은 `engine_sector_confirm.py`에서 `calculate_bonus_scores` 호출 **이후**에 수행됨. 따라서 2차 가산점 계산 시점에는 아직 컷오프가 적용되지 않아 `rank > 0` 판단이 불가.

**해결方案**:
- (A) `calculate_bonus_scores` 내부에서 `scored_rise_ratio >= min_rise_ratio` 조건으로 통과 업종 판단 — `min_rise_ratio` 파라미터 추가 필요
- (B) 2차 가산점은 전체 업종 대상으로 계산하되, 컷오프 미달 업종은 `rank=0`으로 최종 순위에서 제외 — 모집단이 넓어지지만 왜곡은 제한적
- (C) 2단계 계산: 1차/3차 계산 → 컷오프 적용 → 2차 계산 (통과 업종만) → final_score 재계산

**추천**: (A) — `min_rise_ratio` 파라미터를 `calculate_bonus_scores`에 전달하여 통과 업종 판단. 구조가 단순하고 1패스 계산.

### 8.2 `percentile_to_score` vs `rank_to_score` 중복

두 함수는 유사하지만 스케일이 다름:
- `rank_to_score`: 꼴찌도 `1/N×100`점 — 업종 간 순위 비교 (1위와 꼴찌 모두 의미 있는 점수)
- `percentile_to_score`: 꼴찌 = 0점 — 종목 간 상대 비교 (가장 하락 종목은 0점)

P24(단순성) 관점에서 하나로 통합 가능하나, 의미가 다르므로 분리 유지 권장. `rank_to_score`는 업종 간 순위(1차/3차), `percentile_to_score`는 종목 간 백분위(2차)로 역할 분담.

### 8.3 기존 설정 데이터 마이그레이션

기존 사용자가 `sector_weights` 및 트리밍 값을 변경한 상태에서 새 버전으로 업데이트 시:
- `settings_file.py`의 `_migrate_sector_weights` 제거 → 기존 `sector_weights` 키가 설정 파일에 잔존
- `sector_trim_trade_amt_pct`, `sector_trim_change_rate_pct` 키도 설정 파일에 잔존
- 잔존 키는 무시됨 (사용되지 않음) — 기능 영향 없음
- 단, 설정 파일 정합성 검증 시 잔존 키 처리 로직 확인 필요

### 8.4 2차 가산점 계산 시 종목 수 0 엣지 케이스

통과 업종이 1개이고 종목이 1개인 경우:
- `percentile_to_score([단일값])` = [100.0] — 정의대로 100점
- 해당 업종 2차 가산점 = 100점 — 극단적이지만 정당함 (유일한 통과 종목이므로)

### 8.5 WS payload 크기

`get_sector_scores_snapshot`에 가산점 필드 3개 추가:
- 기존: `rank`, `sector`, `final_score`, `total_trade_amount`, `rise_ratio`, `total` (6개 필드)
- 신규: + `bonus_rise_ratio`, `bonus_relative_strength`, `bonus_trade_amount` (3개 필드 추가)
- 업종 수 20~50개 × 3개 필드 × 소수점 = 수백 바이트 증가 — 무시 가능

### 8.6 트리밍 제거에 따른 1개 대형주 영향 (3차 가산점)

트리밍 제거 시 거래대금 평균에서 1개 대형주의 영향이 그대로 반영:
- 예: 4종목 업종, 1개 대형주 거래대금 1000억, 나머지 3개 각 10억 → 평균 332.5억
- 20종목 업종, 전부 50억 → 평균 50억
- 3차 가산점에서 4종목 업종이 무조건 유리

**왜곡인지 정당한 평가인지**: 대형주가 있는 업종이 거래대금이 많은 것은 사실이므로 3차 가산점에서 유리한 것은 정당. 단, 2차 가산점(백분위 평균)이 부분 보완 — 대형주 1개만 있고 나머지 종목들이 안 오른 업종은 2차 가산점이 낮아 균형 유지.

**결론**: 구조적 균형 존재. 추가 보호장치 불필요. 다만 구현 후 실제 데이터로 1개 대형주 업종의 점수 편향 정도 모니터링 권장.

---

## 9. 구현 순서 (별도 세션 진행 시)

1. **Phase 1**: 백엔드 도메인 (models.py, sector_score.py, sector_calculator.py)
2. **Phase 1 검증**: 단위 테스트 (test_sector_score.py, test_sector_calculator.py)
3. **Phase 2**: 백엔드 서비스/설정 (engine_sector_confirm.py, sector_data_provider.py, settings_*.py, engine_account_notify.py)
4. **Phase 2 검증**: 런타임 기동 + 통합 테스트
5. **Phase 3**: 프론트엔드 (sector-settings.ts, sector-ranking-list.ts, types/index.ts, uiStore.ts, binding.ts)
6. **Phase 3 검증**: `npm run build` + 브라우저 확인
7. **Phase 4**: 테스트 전면 수정
8. **Phase 4 검증**: 전체 테스트 통과

각 Phase 완료 시 커밋 + HANDOVER.md 갱신.

---

## 10. 참고 자료

- 기존 순위 기반 점수 계획서: `docs/plan_score_rank_based.md`
- 아키텍처 원칙: `ARCHITECTURE.md` 제1부 "불변 원칙 24개"
- 매수 설정 가산점 구조: `backend/app/domain/buy_filter.py:8-61`
- 현재 업종 점수 계산: `backend/app/domain/sector_score.py:77-130`
- 현재 가중치 슬라이더 UI: `frontend/src/pages/sector-settings.ts:207-247`

---

## 부록 A: 사용자 대화 기반 설계 의사결정 기록

| 순서 | 사용자 의견 | 설계 반영 |
|------|------------|----------|
| 1 | "업종에 속한 종목들이 몇%씩 올랐느냐, 많이 상승한 종목들이 많은 업종에 점수 더 부여" | 2차 가산점 설계 출발점 |
| 2 | "절대 임계값을 사용자가 정하는 것 자체가 데이터 왜곡" | 임계값 고정 방식 거부 → 상대평가 채택 |
| 3 | "업종 내 종목들 간 실시간 상대비교" | 업종 내 상대 기준 (전체 분포 아님) |
| 4 | "업종에 속한 종목수가 적더라도 상대평가" | 평균 사용 (합산 거부) → 종목 수 무관 |
| 5 | "크게 오른 종목 기준을 의식하지 마" | 임계값/분위 기준 만들지 않음 → 백분위 점수로 자동 해결 |
| 6 | "통과 업종들에 속한 종목들만의 상대평가" | 모집단 = 컷오프 통과 업종 종목들만 |
| 7 | "가중치 슬라이더는 별 의미 없어" | 가중치 슬라이더 삭제, 누적 가산점 방식 채택 |
| 8 | "매수설정처럼 가산점 방식 도입, 단위 적절히 정해서" | 매수 설정 boost_score 패턴 참조, 0~100 스케일 |
| 9 | "이미 차단 필터링 있으니 통과 업종들 사이에서 비교" | 별도 계층 필터 불필요, 기존 컷오프 재사용 |
| 10 | "트리밍은 min-max 정규화 시절 이상치 왜곡 방지용. 순위/백분위 기반이니 불필요. 인위적 잘라내기가 왜곡. 관련 설정 UI도 제거" | 트리밍 로직/파라미터/설정/UI 전체 제거. `scored_rise_ratio`/`scored_trade_amount` 필드 제거 → `rise_ratio`/`total_trade_amount`로 통합. 2차 가산점(백분위 평균)이 1개 대형주 영향 부분 보완. |
