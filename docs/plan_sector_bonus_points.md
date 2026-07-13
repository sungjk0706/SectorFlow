# 업종 점수 누적 가산점제 전환 수정 계획서

> **작성일**: 2026-07-13
> **갱신일**: 2026-07-13 (사전조사 폭넓게 확장 + 설계 문제 2건 해결 + 프론트엔드 UI 계획 보강)
> **상태**: 계획 수립 (정밀 사전 조사 완료, 구현 대기)
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
- **데이터 정합성 (P22)**: 2차 가산점 모집단 = 컷오프 통과 업종 종목들. 진실 소스 단일화.

---

## 2. 새 점수 구조: 3단계 누적 가산점

### 2.1 전체 흐름 (옵션 C — 2패스 계산)

```
[기존 필터 ①] 5일평균거래대금 N억 이하 차단 (변경 없음)
    ↓
[1차 가산점] 업종 내 상승 종목 비율 (0~100점) — rank_to_score
    ↓
[3차 가산점] 업종 거래대금 (0~100점) — rank_to_score
    ↓
[중간 합산] 1차 + 3차 → 임시 점수 기반 정렬
    ↓
[업종 컷오프] 상승비율 min_rise_ratio 미만 업종 rank=0 (기존 로직 유지)
    ↓
[2차 가산점] 통과 업종(rank>0) 종목들만 모집단 → 백분위 점수 → 업종별 평균 (0~100점) ← 신규
    ↓
[종합 점수] 1차 + 2차 + 3차 합산 (0~300점) → 내림차순 재정렬 → 순위 부여
```

### 2.2 옵션 C 채택 근거 (설계 문제 A 해결)

**이전 검토에서 식별된 문제**: `calculate_bonus_scores`가 `compute_sector_scores` 내부에서 호출되지만, 컷오프 적용은 `engine_sector_confirm.py:163-173`에서 `calculate_bonus_scores` 호출 **이후**에 수행됨. 2차 가산점 계산 시점에는 컷오프가 적용되지 않아 "통과 업종" 판단이 불가.

**옵션 비교**:
- (A) `calculate_bonus_scores`에 `min_rise_ratio` 파라미터 전달 → 내부에서 통과 판단
  - 문제: 컷오프 기준이 두 곳(`engine_sector_confirm.py:163-173`와 `calculate_bonus_scores` 내부)에서 독립 참조 → P10(SSOT) 위반. 한쪽이 바뀌면 모집단과 실제 순위 어긋남 → P22 위반.
- (B) 2차 가산점을 전체 업종 대상 계산 → 모집단이 넓어져 왜곡 제한적이나 정합성 약화
- **(C) 2패스 계산: 1차/3차 계산 → 컷오프 적용 → 2차 계산(통과 업종만) → 종합 점수 재계산** ← 채택
  - 장점: 진실 소스 1곳. 컷오프 적용 후 통과 업종이 확정된 상태에서 2차 모집단 구성. P10/P22 준수.
  - 단점: 2패스 계산 (연산량 미증가 — 정렬은 1차/3차에서 1회, 2차에서 모집단 내 정렬 1회)

**구현 방식**: `calculate_bonus_scores`가 2패스로 동작.
1. 1패스: 1차(상승비율 순위) + 3차(거래대금 순위) 계산 → 임시 합산 → 정렬
2. 컷오프: `min_rise_ratio` 기준 통과 업종 `rank` 부여 (기존 `engine_sector_confirm.py:163-173` 로직을 `calculate_bonus_scores` 내부로 이관)
3. 2패스: 통과 업종(rank>0) 종목들만 모집단 → 백분위 점수 → 업종별 평균 → 2차 가산점
4. 종합: 1차 + 2차 + 3차 → 재정렬 → rank 부여

**주의**: `engine_sector_confirm.py:163-173`의 컷오프 로직이 `calculate_bonus_scores` 내부로 이관되므로, `engine_sector_confirm.py`에서는 컷오프 중복 적용 제거. `compute_full_sector_summary`의 컷오프 로직(L237-245)도 동일하게 이관.

### 2.3 각 단계 상세

#### 1차 가산점: 업종 내 상승 종목 비율 (0~100점)

- **의미**: 상승이 얼마나 넓게 퍼졌는가 (참여 폭)
- **데이터**: `rise_ratio` (전체 종목 기준 상승비율, 트리밍 미적용)
- **점수 변환**: `rank_to_score` 적용 — 업종들 사이에서 상승비율 순위 → 0~100점
- **변경**: 트리밍 제거로 `scored_rise_ratio` 대신 `rise_ratio` 사용

#### 2차 가산점: 통과 업종 종목들 상대평가 (0~100점) ← 신규

- **의미**: 상승이 얼마나 강한가 (상승 폭) — "많이 오른 종목들이 많은 업종"
- **모집단**: 컷오프 통과 업종(rank>0)에 속한 종목들 **만** (옵션 C — 컷오프 적용 후 확정)
- **계산 로직**:
  1. 통과 업종들의 모든 종목을 하나의 모집단으로 수집
  2. 각 종목에 등락률(`change_rate`) 기준 백분위 점수 부여 (0~100) — `percentile_to_score`
     - 가장 많이 오른 종목 = 100점
     - 중간 = 50점
     - 가장 하락 = 0점
  3. 업종별로 소속 종목들의 백분위 점수 **평균** 계산
  4. 평균이 높은 업종 = "많이 오른 종목들이 많은 업종"
- **미통과 업종(rank=0)**: 2차 가산점 = 0점 (모집단에서 제외되므로)
- **왜곡 회피**:
  - 평균 사용 → 종목 수 무관 (4종목 업종이나 20종목 업종이나 동일 0~100 스케일)
  - 백분위(순위) 기반 → +30% 급등 1개가 점수 왜곡하지 않음 (순위만 반영)
  - 통과 업종들만 모집단 → 탈락 업종 하락 종목이 기준을 낮추지 않음
  - 임계값 없음 → 사용자 주관 개입 없음

#### 3차 가산점: 업종 거래대금 (0~100점)

- **의미**: 거래대금이 얼마나 많은가 (신뢰도/유동성)
- **데이터**: `avg_trade_amount` (전체 종목 기준 거래대금 평균, 트리밍 미적용) — 명명 변경 (기존 `total_trade_amount` → `avg_trade_amount`, 섹션 2.6 참조)
- **점수 변환**: `rank_to_score` 적용 — 업종들 사이에서 거래대금 순위 → 0~100점
- **변경**: 트리밍 제거로 `scored_trade_amount` 대신 `avg_trade_amount` 사용
- **1개 대형주 영향**: 1개 대형주(거래대금 1000억)가 있는 4종목 업종의 평균이 332.5억이 되어 20종목 전부 50억인 업종보다 3차 가산점에서 유리. 단, 2차 가산점(백분위 평균)이 부분 보완 — 대형주 1개만 있고 나머지 종목들이 안 오른 업종은 2차 가산점이 낮아 균형 유지. 추가 보완 검토는 섹션 8.2 참조.

### 2.4 종합 점수 계산

```
final_score = 1차_가산점 + 2차_가산점 + 3차_가산점  (0~300점)
```

- 정렬: `final_score` 내림차순, 동점 시 2차 가산점 내림차순 → 1차 가산점 내림차순 → 업종명 오름차순
- 순위 부여: 1-based (컷오프 통과 업종만 rank 부여, 미달 업종은 rank=0)
- **WS payload 필드명 `final_score` 유지** — 값 범위만 0~100 → 0~300으로 변경. 프론트엔드 하위 호환성 유지 (Phase 1 백엔드 전환 후 프론트엔드가 깨지지 않도록).

### 2.5 백분위 점수 계산 로직 (신규 함수)

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

### 2.6 트리밍 제거 + 필드 통합 + 명명 재정의

#### 2.6.1 트리밍 제거 근거

1. **순위/백분위 기반에서 절대값 왜곡 영향 감소**: `rank_to_score`와 `percentile_to_score`는 순위만 반영하므로, 1개 극단 종목의 절대값이 점수를 왜곡하지 않음. 트리밍의 원래 목적이 구조적으로 해결됨.
2. **종목 수 비대칭 적용 왜곡**: 4종목 업종은 `round(4×0.1)=0`으로 트리밍 미작동, 20종목 업종만 트리밍 적용 → 업종 간 비대칭 → 자체가 왜곡 (`sector_calculator.py:140-152`).
3. **등락률 트리밍은 처음부터 효과 미미**: `scored_rise_ratio`는 이진 카운트(`change_rate > 0`) 기반이므로, 상하위 종목을 잘라내도 상승/하락 여부만 카운트 → 극단 등락률 제거가 상승비율에 미치는 영향 제한적.
4. **데이터 정합성(P22) 관점**: 인위적 잘라내기는 실제 데이터를 변형. 원본 데이터 기반 순위가 더 정직한 평가.

#### 2.6.2 필드 통합 + 명명 재정의

트리밍 제거 시 `scored_*` 필드와 원시 필드가 동일해지므로 필드 통합. 동시에 명명 재정의:

| 기존 필드 | 통합 후 필드 | 비고 |
|----------|-------------|------|
| `scored_rise_ratio` | 제거 → `rise_ratio` 사용 | 1차 가산점 원시값 |
| `scored_trade_amount` | 제거 → `avg_trade_amount` 사용 | 3차 가산점 원시값 (명명 변경) |
| `total_trade_amount` | `avg_trade_amount`로 명명 변경 | 기존 "업종 평균 거래대금" 의미를 이름에 반영 (P10/P23) |

**명명 변경 근거**: 기존 `total_trade_amount`는 "업종 평균 거래대금 (원)"이지만 이름은 "total" → 이름-의미 불일치 (P10/P23 위반). 트리밍 제거 후 표시·점수 양쪽에 단일 역할로 사용되므로 `avg_trade_amount`로 명명 변경이 정합성에 부합.

**영향 파일**: 명명 변경은 백엔드(models.py, sector_calculator.py, sector_data_provider.py, telegram_bot.py) + 프론트엔드(types/index.ts, sector-ranking-list.ts, sector-stock.ts) + 테스트 전체에 걸쳐 참조 변경 필요.

#### 2.6.3 트리밍 제거 범위

**백엔드**:
- `backend/app/domain/sector_calculator.py`:
  - L137-152: 등락률 트리밍 로직 전체 제거. `scored_rise_ratio` = `raw_rise_ratio` (또는 `scored_rise_ratio` 필드 자체 제거, `rise_ratio`로 통일)
  - L154-166: 거래대금 트리밍 로직 전체 제거. `scored_ta` = `raw_total_ta / len(filtered_stocks)` (또는 `scored_trade_amount` 필드 자체 제거, `avg_trade_amount`로 통합)
  - `trim_trade_amt_pct`, `trim_change_rate_pct` 파라미터 제거
- `backend/app/domain/models.py`:
  - `SectorScore.scored_rise_ratio` 필드 제거 → `rise_ratio`로 통일
  - `SectorScore.scored_trade_amount` 필드 제거 → `avg_trade_amount`로 통합 (명명 변경)
  - `SectorScore.total_trade_amount` → `avg_trade_amount` 명명 변경
- `backend/app/services/engine_sector_confirm.py`:
  - L120-121, L229-230: `trim_trade`, `trim_change` 변수 제거
  - L139-140, L238-239: `trim_trade_amt_pct`, `trim_change_rate_pct` 인자 제거
- `backend/app/services/sector_data_provider.py`:
  - L246-247: `trim_trade`, `trim_change` 변수 제거
  - L256-257: `trim_trade_amt_pct`, `trim_change_rate_pct` 인자 제거
  - L221: `sc.scored_trade_amount` → `sc.avg_trade_amount` 참조 변경
- `backend/app/core/settings_defaults.py`:
  - L88: `sector_trim_trade_amt_pct` 기본값 제거
  - L89: `sector_trim_change_rate_pct` 기본값 제거
- `backend/app/core/engine_settings.py`: L171-174 트리밍 관련 설정 키 처리 제거

**프론트엔드**:
- `frontend/src/pages/sector-settings.ts`:
  - ④ 극단값 제외 섹션 전체 제거 (L178-205) — `trimChangeRateInput`, `trimTradeAmtInput` 및 관련 DOM/저장 로직
  - `NUM_KEYS`에서 `sector_trim_change_rate_pct`, `sector_trim_trade_amt_pct` 제거
  - `syncFromSettings`에서 트리밍 입력 동기화 제거 (L97-98)
- `frontend/src/types/index.ts`:
  - `AppSettings`에서 `sector_trim_trade_amt_pct`, `sector_trim_change_rate_pct` 제거

**테스트**:
- `backend/tests/test_sector_calculator.py`: `TestComputeSectorScoresTrimming` 제거 (L336-396)
- 트리밍 관련 테스트 케이스 전체 제거

#### 2.6.4 섹션 번호 재정렬

트리밍(④) + 가중치(⑤) 제거 시 설정 페이지 섹션 번호 재정렬:
- 기존: ① 5일평균거래대금 / ② 업종순위 수신율 / ③ 업종 컷오프 / ④ 극단값 제외 / ⑤ 점수 가중치 / ⑥ 매수 대상
- 변경 후: ① 5일평균거래대금 / ② 업종순위 수신율 / ③ 업종 컷오프 / ④ 매수 대상 (기존 ⑥)
- ④ 극단값 제외 + ⑤ 점수 가중치 모두 제거 → ⑥을 ④로 재번호링
- 제거 자리에 "가산점 자동 계산" 안내문 추가 (선택)

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

## 4. 변경 영향 범위 전수 조사 결과 (갱신 — 프론트엔드 보강)

### 4.1 백엔드 — 높음 (전면 수정)

| 파일 | 영향도 | 변경 내용 |
|------|--------|----------|
| `backend/app/domain/models.py` | 높음 | `MetricDef`, `DEFAULT_METRICS` 제거. `SectorScore` 필드 수정: `metric_scores` 제거, `scored_rise_ratio`/`scored_trade_amount` 제거(트리밍 제거), `total_trade_amount` → `avg_trade_amount` 명명 변경, `bonus_rise_ratio`, `bonus_relative_strength`, `bonus_trade_amount` 신규 필드 추가. `final_score` 유지 (0~300 스케일). |
| `backend/app/domain/sector_score.py` | 높음 | `normalize_weight_values` 제거. `calculate_weighted_scores` 재작성 → `calculate_bonus_scores` (3단계 가산점 합산, 옵션 C 2패스). `rank_to_score` 유지. `percentile_to_score` 신규 추가. 컷오프 로직 이관 (min_rise_ratio 파라미터 추가). |
| `backend/app/domain/sector_calculator.py` | 높음 | `sector_weights` 파라미터 제거. `trim_trade_amt_pct`/`trim_change_rate_pct` 파라미터 제거(트리밍 제거). 등락률 트리밍 로직(L137-152) + 거래대금 트리밍 로직(L154-166) 제거. `scored_rise_ratio`/`scored_trade_amount` 계산 제거 → `rise_ratio`/`avg_trade_amount` 사용. `compute_sector_scores`, `compute_full_sector_summary`에서 `calculate_weighted_scores` 호출부 → `calculate_bonus_scores`로 교체. `compute_full_sector_summary`의 컷오프 로직(L237-245) 제거 (`calculate_bonus_scores` 내부로 이관). 2차 가산점용 백분위 계산 로직 추가. |
| `backend/app/services/engine_sector_confirm.py` | 높음 | `sector_weights` 참조 제거 (L122, L138, L161, L237). `trim_trade`/`trim_change` 변수 제거 (L120-121, L229-230). `trim_trade_amt_pct`/`trim_change_rate_pct` 인자 제거 (L139-140, L238-239). `calculate_weighted_scores` 호출 → `calculate_bonus_scores`로 교체. 컷오프 로직(L163-173) 제거 (`calculate_bonus_scores` 내부로 이관). |
| `backend/app/core/settings_defaults.py` | 높음 | `sector_weights` 기본값 제거 (L90). `sector_trim_trade_amt_pct` 기본값 제거 (L88). `sector_trim_change_rate_pct` 기본값 제거 (L89). |
| `backend/app/core/engine_settings.py` | 높음 | `sector_weights` 빌드/검증 제거 (L146-150). 트리밍 관련 설정 키 처리 제거 (L171-174). |
| `backend/app/core/settings_file.py` | 높음 | `_migrate_sector_weights` 함수 제거 (L27-43). `migrate_rank_primary_to_weights` 함수 제거 (L18-24). |
| `backend/app/services/sector_data_provider.py` | 중간 | `sector_weights` 참조 제거 (L248, L255). `trim_trade`/`trim_change` 변수 제거 (L246-247). `trim_trade_amt_pct`/`trim_change_rate_pct` 인자 제거 (L256-257). `get_sector_scores_snapshot` payload: `sc.scored_trade_amount` → `sc.avg_trade_amount` 참조 변경 (L221). 신규 가산점 필드 추가 (`bonus_rise_ratio`, `bonus_relative_strength`, `bonus_trade_amount`). |
| `backend/app/services/engine_account_notify.py` | 중간 | `normalize_weight_values` import 제거 (L282). `normalized_weights` 계산/전송 제거 (L286-287, L325, L343). |
| `backend/app/services/telegram_bot.py` | 낮음 | `s.scored_trade_amount` 참조 → `s.avg_trade_amount` 또는 `s.final_score`로 대체 (L460, L472). |
| `backend/app/domain/buy_filter.py` | 낮음 | 변경 없음 (rank 기반 필터링만 사용, 점수 필드 미참조). |
| `backend/app/pipelines/pipeline_compute.py` | 낮음 | 변경 없음 (간접 호출만). |
| `backend/app/services/engine_snapshot.py` | 낮음 | 변경 없음 (간접 참조만). |
| `backend/app/services/engine_service.py` | 낮음 | 설정 키 목록에서 `sector_weights` 참조 제거 (L160). |

### 4.2 프론트엔드 — 중간~높음 (계획서 갱신으로 보강)

| 파일 | 영향도 | 변경 내용 |
|------|--------|----------|
| `frontend/src/pages/sector-settings.ts` | 높음 | ⑤ 점수 가중치 섹션 전체 제거 (L207-247). ④ 극단값 제외 섹션 전체 제거 (L178-205) — `trimChangeRateInput`/`trimTradeAmtInput` 및 관련 DOM/저장 로직. `dualSlider` 변수/함수 제거 (L46, L72-83, L217-235). `saveWeightsNow` 제거 (L72-77). `updateAppliedWeightsLabel` 제거 (L52-61). `syncFromSettings` 가중치/트리밍 동기화 제거 (L91-98). `NUM_KEYS`에서 `sector_trim_change_rate_pct`/`sector_trim_trade_amt_pct` 제거. `prevNormalizedWeights` 제거 (L322). uiStore 구독 normalizedWeights 갱신 제거 (L338-341). unmount dualSlider.destroy 제거 (L361-364). 섹션 번호 재정렬 (④⑤ 제거 → ⑥을 ④로). 제거 자리에 "가산점 자동 계산" 안내문 추가. |
| `frontend/src/pages/sector-ranking-list.ts` | 중간 | `updateRankingRows` 점수 표시 로직 수정 (L150-153) — `final_score` 0~300 스케일 표시. 헤더 행 조정 (L196-202) — "종합점수" → "가산점" 라벨 변경. `total_trade_amount` → `avg_trade_amount` 참조 변경 (L153). 바 그래프 로직 (L154-155) — `final_score / maxScore` 정규화는 자동 적용 (값 범위 변경되어도 비율 동일). |
| **`frontend/src/pages/sector-stock.ts`** | 중간 | **계획서 갱신으로 신규 추가** — L156, L180-184, L211: `sectorScores`, `final_score`로 업종 정렬 및 점수 매핑. `final_score` 필드명 유지되므로 코드 변경 최소 (점수 범위 0~300에 대한 표시 조정만). `total_trade_amount` → `avg_trade_amount` 참조 변경 (있을 경우). |
| `frontend/src/types/index.ts` | 중간 | `sector_weights` 타입 제거 (L150). `sector_trim_trade_amt_pct`/`sector_trim_change_rate_pct` 타입 제거 (L153-154). `SectorStatus.normalized_weights` 제거 (L247). `SectorScoreRow`에 신규 가산점 필드 추가 (`bonus_rise_ratio`, `bonus_relative_strength`, `bonus_trade_amount`). `SectorScoreRow.total_trade_amount` → `avg_trade_amount` 명명 변경. |
| `frontend/src/stores/uiStore.ts` | 중간 | `normalizedWeights` 상태 필드 제거 (L58, L84). |
| `frontend/src/binding.ts` | 낮음 | `normalized_weights` 수신 제거 (L299-301). sector-scores 이벤트 바인딩은 유지. |
| `frontend/src/stores/hotStore.ts` | 낮음 | `applySectorScores` 변경 없음 (새 필드 자동 처리). `SectorScoreRow` 타입 변경만 반영. |
| `frontend/src/utils/sliderConvert.ts` | 삭제 | sector-settings.ts에서만 사용 → 삭제. |
| `frontend/src/components/common/create-slider.ts` | **삭제 불가** | **계획서 갱신으로 수정** — `createDualLabelSlider`는 `buy-settings.ts:11,267`에서도 사용 중 (매수설정 `boostOrderDualSlider`). **삭제하면 매수설정 슬라이더 깨짐 → 절대 삭제 불가**. `createSlider`도 `createDualLabelSlider` 내부에서 사용하므로 유지. |

### 4.3 프론트엔드 테스트 — 낮음

| 파일 | 영향도 | 변경 내용 |
|------|--------|----------|
| `frontend/tests/utils/sliderConvert.test.ts` | 삭제 | `sliderConvert.ts` 삭제에 따라 테스트도 삭제. |
| `frontend/tests/components/create-slider.ui.test.ts` | 유지 | `createDualLabelSlider`는 buy-settings.ts에서 사용 중이므로 컴포넌트+테스트 모두 유지. |

### 4.4 백엔드 테스트 — 높음 (전면 수정)

| 파일 | 영향도 | 변경 내용 |
|------|--------|----------|
| `backend/tests/test_sector_score.py` | 높음 | `TestNormalizeWeightValues` 클래스 전체 제거. `TestCalculateWeightedScores` → `TestCalculateBonusScores` 재작성 (3단계 가산점 합산, 옵션 C 2패스, 정렬, 순위 부여). `TestPercentileToScore` 신규 추가. `TestRankToScore` 유지. |
| `backend/tests/test_sector_calculator.py` | 높음 | `TestComputeSectorScoresTrimming` 제거 (L336-396). `TestComputeSectorScoresWeights` 제거 (L397-443). `TestComputeSectorScoresWithBonus` 신규 추가. `scored_trade_amount`/`scored_rise_ratio` 헬퍼 → `avg_trade_amount`/`rise_ratio`로 수정. |
| `backend/tests/test_sector_calculator_integration.py` | 중간 | `test_weighted_scores_calculated` → 가산점 계산 테스트로 수정. |
| `backend/tests/test_engine_sector_confirm.py` | 높음 | `calculate_weighted_scores` mock → `calculate_bonus_scores` mock 교체 (8개 테스트, L415/461/503/546/592/651/695/738). `sector_weights` 관련 mock 제거 (L426/472/514/560/606/662/706/749/792/835/872). `trim_trade`/`trim_change` 관련 mock/인자 제거 (L424-425/470-471/512-513/558-559/604-605/660-661/704-705/747-748/790-791/833-834/870-871). 컷오프 로직 이관에 따른 테스트 조정. |
| `backend/tests/test_settings_file.py` | 높음 | `TestMigrateRankPrimaryToWeights` 제거 (L12-27). `TestMigrateSectorWeights` 제거 (L32-80). |
| `backend/tests/test_engine_settings.py` | 중간 | L103: `sector_weights` 기본값 검증 제거. `sector_trim_trade_amt_pct`/`sector_trim_change_rate_pct` 기본값 검증 제거. |
| `backend/tests/test_buy_filter.py` | 낮음 | L60-61,73-74: `scored_trade_amount`/`scored_rise_ratio` 헬퍼 → `avg_trade_amount`/`rise_ratio`로 수정. |
| `backend/tests/test_telegram_bot.py` | 낮음 | L1167,1220: `scored_trade_amount` 참조 → `avg_trade_amount` 또는 `final_score`로 수정. |
| `backend/tests/test_sector_data_provider.py` | 중간 | `final_score`, `scored_trade_amount` → 신규 가산점 필드 + `avg_trade_amount`로 수정. |
| `backend/tests/test_pipeline_compute.py` | 낮음 | mock 데이터 가산점 필드 추가, 트리밍 관련 mock 제거. |
| `backend/tests/test_web_ws_routes.py` | 낮음 | L494,511,537,556: score 참조 수정. |
| `backend/tests/test_engine_snapshot.py` | 낮음 | L141,162,163,182,201,202,211,212,219,236,237,248,275: score 참조 수정. |

---

## 5. 구현 Phase 계획 (갱신 — Phase 1+2 통합 + 세분화)

### 5.1 Phase 구조 개요 (설계 문제 B 해결)

**이전 검토에서 식별된 문제**: Phase 1(백엔드 도메인)에서 `calculate_weighted_scores` 삭제 + `calculate_bonus_scores` 추가 시, Phase 2 대상인 `engine_sector_confirm.py:83,161`이 여전히 `calculate_weighted_scores`를 import/호출 → Phase 1 단독 완료 시 런타임 즉시 깨짐. 규칙 0-1(세션당 1단계 + 검증)이 요구하는 "단계 완료 후 런타임 기동 검증"이 Phase 1에서 불가능.

**해결**: 백엔드 도메인(기존 Phase 1) + 백엔드 서비스/설정(기존 Phase 2)을 **1개 세션에 통합**. "백엔드 전환"을 1단계로 정의. 각 Phase가 독립적으로 완료·검증 가능하도록 설계.

**WS payload 하위 호환성 유지**:
- Phase 1(백엔드) 완료 후 프론트엔드가 깨지지 않도록, WS payload에서 프론트엔드가 참조하는 필드명(`final_score`, `total_trade_amount`→`avg_trade_amount`, `rise_ratio`, `rank`) 유지
- 신규 가산점 필드(`bonus_rise_ratio`, `bonus_relative_strength`, `bonus_trade_amount`) 추가
- `scored_trade_amount` 제거 (프론트엔드 미참조 확인 완료 — sector-ranking-list.ts, sector-stock.ts 모두 `total_trade_amount`/`final_score` 참조)
- `normalized_weights` 제거 (프론트엔드 Phase 2에서 uiStore/binding 처리)
- → Phase 1 완료 후 백엔드 정상 동작, 프론트엔드도 기존 필드로 동작 (신규 가산점 필드는 무시)

### 5.2 Phase 1: 백엔드 전환 (도메인 + 서비스 + 설정 통합 — 1세션)

**목표**: 백엔드 전체를 가산점제로 전환. 런타임 기동 검증 가능.

#### 5.2.1 `backend/app/domain/models.py`

- `MetricDef` dataclass 제거 (L76-83)
- `DEFAULT_METRICS` 리스트 제거 (L86-99)
- `SectorScore` 필드 수정:
  - `scored_trade_amount` 필드 제거 → `avg_trade_amount`로 통합 (명명 변경)
  - `total_trade_amount` → `avg_trade_amount` 명명 변경
  - `scored_rise_ratio` 필드 제거 → `rise_ratio`로 통일
  - `metric_scores` 필드 제거
  - `bonus_rise_ratio: float = 0.0` 신규 필드 (1차 가산점)
  - `bonus_relative_strength: float = 0.0` 신규 필드 (2차 가산점)
  - `bonus_trade_amount: float = 0.0` 신규 필드 (3차 가산점)
  - `final_score` 유지 (0~300 스케일)

#### 5.2.2 `backend/app/domain/sector_score.py`

- `normalize_weight_values` 함수 제거 (L51-74)
- `calculate_weighted_scores` 재작성 → `calculate_bonus_scores`:
  ```python
  def calculate_bonus_scores(
      sector_scores: list,  # list[SectorScore]
      *,
      min_rise_ratio: float = 0.0,  # 컷오프 기준 (옵션 C — 진실 소스 1곳)
  ) -> None:
      # 1패스: 1차(상승비율 순위) + 3차(거래대금 순위) 계산
      #   - rank_to_score(rise_ratio) → bonus_rise_ratio
      #   - rank_to_score(avg_trade_amount) → bonus_trade_amount
      #   - 임시 합산 = bonus_rise_ratio + bonus_trade_amount
      #   - 임시 합산 기준 정렬
      # 컷오프: min_rise_ratio 기준 통과 업종 rank 부여 (rank>0), 미달 rank=0
      # 2패스: 통과 업종(rank>0) 종목들만 모집단
      #   - percentile_to_score(change_rate) → 종목별 백분위 점수
      #   - 업종별 평균 → bonus_relative_strength
      #   - 미통과 업종 bonus_relative_strength = 0.0
      # 종합: final_score = bonus_rise_ratio + bonus_relative_strength + bonus_trade_amount
      # 재정렬: final_score 내림차순, 동점 시 2차→1차→업종명
      # rank 재부여 (통과 업종만 1-based)
  ```
- `percentile_to_score` 신규 함수 추가 (섹션 2.5)
- `rank_to_score` 유지

#### 5.2.3 `backend/app/domain/sector_calculator.py`

- `compute_sector_scores` 파라미터 제거:
  - `sector_weights` 파라미터 제거 (L22)
  - `trim_trade_amt_pct` 파라미터 제거 (L23)
  - `trim_change_rate_pct` 파라미터 제거 (L24)
- 트리밍 로직 제거:
  - L137-152: 등락률 트리밍 로직 전체 제거
  - L154-166: 거래대금 트리밍 로직 전체 제거
- `scored_rise_ratio`/`scored_trade_amount` 계산 제거:
  - `rise_ratio` = `raw_rise_ratio` (직접 사용)
  - `avg_trade_amount` = `raw_total_ta / len(filtered_stocks)` (명명 변경)
- `SectorScore` 생성 시 필드 수정 (L169-180):
  - `total_trade_amount` → `avg_trade_amount`
  - `scored_trade_amount` 제거
  - `scored_rise_ratio` 제거
- `calculate_weighted_scores` 호출 → `calculate_bonus_scores` 호출 (L183):
  - `calculate_bonus_scores(sector_scores, min_rise_ratio=min_rise_ratio)` — 단, `compute_sector_scores`에는 `min_rise_ratio` 파라미터 추가 필요
- `compute_full_sector_summary` 파라미터 제거:
  - `sector_weights` 파라미터 제거 (L203)
  - `trim_trade_amt_pct` 파라미터 제거 (L204)
  - `trim_change_rate_pct` 파라미터 제거 (L205)
  - `min_rise_ratio` 파라미터 유지 (→ `calculate_bonus_scores`에 전달)
- `compute_full_sector_summary` 컷오프 로직 제거 (L237-245) — `calculate_bonus_scores` 내부로 이관

#### 5.2.4 `backend/app/services/engine_sector_confirm.py`

- L83: `from backend.app.domain.sector_score import calculate_weighted_scores` → `calculate_bonus_scores`
- L120-121: `trim_trade`, `trim_change` 변수 제거
- L122: `sector_weights` 변수 제거
- L138-140: `sector_weights`, `trim_trade_amt_pct`, `trim_change_rate_pct` 인자 제거
- L161: `calculate_weighted_scores(merged, weights=sector_weights)` → `calculate_bonus_scores(merged, min_rise_ratio=min_rise_ratio)`
- L163-173: 컷오프 로직 제거 (`calculate_bonus_scores` 내부로 이관)
- L229-230: `trim_trade`, `trim_change` 변수 제거
- L237-239: `sector_weights`, `trim_trade_amt_pct`, `trim_change_rate_pct` 인자 제거

#### 5.2.5 `backend/app/services/sector_data_provider.py`

- L221: `"total_trade_amount": sc.scored_trade_amount` → `"avg_trade_amount": sc.avg_trade_amount`
- L217-224: 신규 가산점 필드 추가:
  ```python
  "bonus_rise_ratio": round(sc.bonus_rise_ratio, 1),
  "bonus_relative_strength": round(sc.bonus_relative_strength, 1),
  "bonus_trade_amount": round(sc.bonus_trade_amount, 1),
  ```
- L246-247: `trim_trade`, `trim_change` 변수 제거
- L248: `sector_weights` 변수 제거
- L255-257: `sector_weights`, `trim_trade_amt_pct`, `trim_change_rate_pct` 인자 제거

#### 5.2.6 `backend/app/services/engine_account_notify.py`

- L282: `from backend.app.domain.sector_score import normalize_weight_values` 제거
- L286-287: `raw_weights`, `normalized_weights` 계산 제거
- L325, L343: `"normalized_weights": normalized_weights` payload 필드 제거

#### 5.2.7 `backend/app/core/settings_defaults.py`

- L88: `"sector_trim_trade_amt_pct": 10.0` 제거
- L89: `"sector_trim_change_rate_pct": 10.0` 제거
- L90: `"sector_weights": {"rise_ratio": 0.5, "total_trade_amount": 0.5}` 제거

#### 5.2.8 `backend/app/core/engine_settings.py`

- L146: `result["sector_weights"] = merged["sector_weights"]` 제거
- L147-150: `sector_weights` 키 정합성 검증 제거
- L171-174: `sector_trim_trade_amt_pct`, `sector_trim_change_rate_pct` 설정 빌드 제거

#### 5.2.9 `backend/app/core/settings_file.py`

- L18-24: `migrate_rank_primary_to_weights` 함수 제거
- L27-43: `_migrate_sector_weights` 함수 제거
- 마이그레이션 호출부에서 `_migrate_sector_weights` 호출 제거

#### 5.2.10 `backend/app/services/telegram_bot.py`

- L460: `s.scored_trade_amount / 1e8` → `s.avg_trade_amount / 1e8`
- L472: `s.scored_trade_amount / 1e8` → `s.avg_trade_amount / 1e8`

#### 5.2.11 `backend/app/services/engine_service.py`

- L160: 설정 키 목록에서 `sector_weights` 제거

#### 5.2.12 Phase 1 검증

- **런타임 기동**: `.venv/bin/python main.py` 기동, 로그 확인 (업종 점수 계산 정상, 에러 없음), 10~30초 대기 후 종료, 잔존 프로세스 확인
- **단위 테스트 (신규 함수만)**: `percentile_to_score`, `calculate_bonus_scores` 신규 테스트 작성 후 통과 확인
- **주의**: 기존 테스트는 Phase 1에서 깨짐 (함수명/필드명 변경). Phase 3에서 전면 수정. Phase 1 검증은 런타임 기동 + 신규 함수 단위 테스트만 수행.

### 5.3 Phase 2: 프론트엔드 전환 (1세션)

**목표**: 프론트엔드를 가산점제 UI로 전환. 빌드 + 브라우저 확인 가능.

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
- import 제거: `createDualLabelSlider`, `toDisplayValue`, `toServerValue`, `DualLabelSliderHandle`

**추가 — 제거 자리에 "가산점 자동 계산" 안내문**:
- ④ 자리에 `createStepLabel('④', '가산점 자동 계산 (상승폭·참여폭·거래대금 3단계 누적)')` + 설명문 추가
- 사용자에게 가중치 슬라이더/트리밍이 제거되고 자동 계산으로 전환되었음을 안내

**섹션 번호 재정렬**: ④ 극단값 제외 + ⑤ 점수 가중치 모두 제거 → 기존 ⑥ 매수 대상을 ④로 재번호링 (⑤로 밀지 않고 ④부터 시작).

#### 5.3.2 `frontend/src/pages/sector-ranking-list.ts`

**수정 — `updateRankingRows`** (L150-153):
```typescript
const finalScore = s.final_score.toFixed(1)        // 종합 가산점 (0~300)
const riseRatio = s.rise_ratio.toFixed(1) + '%'     // 상승비율 (표시용)
const tradeAmt = (s.avg_trade_amount / 100).toLocaleString('ko-KR', {...})  // 명명 변경
```

**수정 — 헤더 행** (L196-202):
- "종합점수" → "가산점" 라벨 변경
- "평균거래(억)" 유지 (avg_trade_amount 값은 동일 — 평균 거래대금)

**수정 — 바 그래프** (L154-155):
- `final_score / maxScore` 정규화는 자동 적용 (값 범위 0~300으로 변경되어도 비율 동일)
- 바 색상 로직 유지

**`RowCache` 인터페이스** (L23-27):
- `tradeAmt` 필드명 유지 (값은 avg_trade_amount)

#### 5.3.3 `frontend/src/pages/sector-stock.ts` (계획서 갱신으로 신규 추가)

**수정 — `computeRows`** (L156, L180-184, L211):
- `final_score` 필드명 유지되므로 정렬 로직 변경 없음 (값 범위 0~300으로 변경되어도 정렬 순서 동일)
- `scoreMap.set(sc.sector, sc.final_score)` 유지
- `total_trade_amount` 참조가 있을 경우 `avg_trade_amount`로 변경 (참조 확인 필요)

#### 5.3.4 `frontend/src/types/index.ts`

**제거**:
- L150: `sector_weights: Record<string, number>`
- L153: `sector_trim_trade_amt_pct: number`
- L154: `sector_trim_change_rate_pct: number`
- L247: `SectorStatus.normalized_weights`

**수정 — `SectorScoreRow`** (L234-241):
```typescript
export interface SectorScoreRow {
  rank: number;
  sector: string;
  final_score: number;          // 0~300 (종합 가산점)
  bonus_rise_ratio: number;     // 신규: 1차 가산점 (0~100)
  bonus_relative_strength: number;  // 신규: 2차 가산점 (0~100)
  bonus_trade_amount: number;   // 신규: 3차 가산점 (0~100)
  avg_trade_amount: number;     // 명명 변경 (기존 total_trade_amount)
  rise_ratio: number;
  total: number;
}
```

#### 5.3.5 `frontend/src/stores/uiStore.ts`

- L58: `normalizedWeights` 상태 필드 제거
- L84: 초기값 `normalizedWeights: null` 제거

#### 5.3.6 `frontend/src/binding.ts`

- L299-301: `normalized_weights` 수신 처리 제거 (sector-scores 이벤트 바인딩은 유지)

#### 5.3.7 `frontend/src/stores/hotStore.ts`

- `SectorScoreRow` 타입 변경 자동 반영 (신규 필드 추가, 명명 변경)
- `applySectorScores` 로직 변경 없음 (새 필드 자동 처리)

#### 5.3.8 `frontend/src/utils/sliderConvert.ts`

- **삭제** — sector-settings.ts에서만 사용. 다른 곳에서 참조 없음 확인 완료.

#### 5.3.9 `frontend/src/components/common/create-slider.ts`

- **유지 (삭제 불가)** — `createDualLabelSlider`는 `buy-settings.ts:11,267`에서 사용 중 (매수설정 `boostOrderDualSlider`). `createSlider`도 `createDualLabelSlider` 내부에서 사용. 삭제하면 매수설정 슬라이더 깨짐.

#### 5.3.10 Phase 2 검증

- **빌드**: `npm run build` — 타입 오류 없음
- **브라우저 확인**:
  - 업종순위 페이지: 가산점(0~300) 표시 정상
  - 업종순위 설정: ④ 극단값 제외 섹션 제거됨, ⑤ 가중치 슬라이더 제거됨, "가산점 자동 계산" 안내문 표시
  - ①~③ 설정 정상 동작 확인 (④⑤ 제거 후 번호 재정렬)
  - 매수후보 테이블: 업종 순위 기반 매수 타겟 정상 생성
  - WS sector-scores 이벤트 수신 정상

### 5.4 Phase 3: 테스트 전환 (1세션)

**목표**: 테스트 전면 수정. pytest 전체 통과.

#### 5.4.1 `backend/tests/test_sector_score.py`

**제거**:
- `TestNormalizeWeightValues` 클래스 전체 (L56-95)
- `TestCalculateWeightedScores` 클래스 전체 (L99-221)

**재작성**:
- `TestCalculateBonusScores` — 3단계 가산점 합산, 옵션 C 2패스, 컷오프 적용, 정렬 순서, 동점 처리, 순위 부여 테스트

**신규 추가**:
- `TestPercentileToScore` — 빈 리스트, 단일 값, 동점, 0~100 스케일, higher_is_better

**유지**:
- `TestRankToScore` — 기존 테스트 그대로 유지

**헬퍼 수정**:
- `_make_sector_score` 헬퍼 (L103-115): `scored_trade_amount`/`scored_rise_ratio` → `avg_trade_amount`/`rise_ratio`로 수정

#### 5.4.2 `backend/tests/test_sector_calculator.py`

**제거**:
- `TestComputeSectorScoresTrimming` (L336-396) — 트리밍 제거
- `TestComputeSectorScoresWeights` (L397-443) — 가중치 제거
- 트리밍 파라미터(`trim_trade_amt_pct`, `trim_change_rate_pct`) 관련 테스트 케이스 전체

**신규 추가**:
- `TestComputeSectorScoresWithBonus` — 3단계 가산점 계산 검증, 옵션 C 2패스, 컷오프 적용

#### 5.4.3 `backend/tests/test_sector_calculator_integration.py`

- `test_weighted_scores_calculated` → `test_bonus_scores_calculated`로 수정 (가산점 계산 검증)

#### 5.4.4 `backend/tests/test_engine_sector_confirm.py`

- `calculate_weighted_scores` mock → `calculate_bonus_scores` mock 교체 (8개 테스트)
- `sector_weights` 관련 mock 제거 (11개 테스트)
- `trim_trade`/`trim_change` 관련 mock/인자 제거 (11개 테스트)
- 컷오프 로직 이관에 따른 테스트 조정 (컷오프가 `calculate_bonus_scores` 내부에서 수행되므로 mock 동작 변경)

#### 5.4.5 `backend/tests/test_settings_file.py`

- `TestMigrateRankPrimaryToWeights` 제거 (L12-27)
- `TestMigrateSectorWeights` 제거 (L32-80)
- import에서 `migrate_rank_primary_to_weights`, `_migrate_sector_weights` 제거

#### 5.4.6 `backend/tests/test_engine_settings.py`

- L103: `sector_weights` 기본값 검증 제거
- `sector_trim_trade_amt_pct`/`sector_trim_change_rate_pct` 기본값 검증 제거

#### 5.4.7 기타 백엔드 테스트

- `test_sector_data_provider.py`: `final_score`, `scored_trade_amount` → 신규 가산점 필드 + `avg_trade_amount`로 수정
- `test_buy_filter.py`: L60-61,73-74 헬퍼 `scored_trade_amount`/`scored_rise_ratio` → `avg_trade_amount`/`rise_ratio`로 수정
- `test_telegram_bot.py`: L1167,1220 `scored_trade_amount` → `avg_trade_amount` 또는 `final_score`로 수정
- `test_pipeline_compute.py`: mock 데이터 가산점 필드 추가, 트리밍 관련 mock 제거
- `test_web_ws_routes.py`: L494,511,537,556 score 참조 수정
- `test_engine_snapshot.py`: L141,162,163,182,201,202,211,212,219,236,237,248,275 score 참조 수정

#### 5.4.8 프론트엔드 테스트

- `frontend/tests/utils/sliderConvert.test.ts`: **삭제** (sliderConvert.ts 삭제에 따라)
- `frontend/tests/components/create-slider.ui.test.ts`: **유지** (createDualLabelSlider는 buy-settings.ts에서 사용 중)

#### 5.4.9 Phase 3 검증

- **pytest 전체**: 모든 테스트 통과
- **ruff**: 0건
- **프론트엔드 빌드**: `npm run build` 통과 (sliderConvert.test.ts 삭제 후)

---

## 6. 검증 계획

### 6.1 단위 테스트 (Phase 1 + Phase 3)

- `percentile_to_score`: 빈 리스트, 단일 값, 동점, 0~100 스케일, higher_is_better
- `calculate_bonus_scores`: 3단계 합산, 옵션 C 2패스, 컷오프 적용, 정렬 순서, 동점 처리, 순위 부여
- `compute_sector_scores`: 가산점 계산 결과, 컷오프 동작
- **트리밍 제거 검증**: `compute_sector_scores` 호출 시 `trim_trade_amt_pct`/`trim_change_rate_pct` 파라미터 없이 정상 동작. 트리밍 미적용 시 `rise_ratio`/`avg_trade_amount`가 전체 종목 기준값과 일치.

### 6.2 통합 테스트 (Phase 3)

- `compute_full_sector_summary`: DB 연동 가산점 계산
- `_flush_sector_recompute_impl`: 증분 재계산 시 가산점 갱신
- `recompute_sector_summary_now`: 설정 변경 시 재계산

### 6.3 런타임 기동 검증 (Phase 1 — 필수)

- `.venv/bin/python main.py` 기동
- 로그 확인: 업종 점수 계산 정상, 에러 없음
- 10~30초 대기 후 종료, 잔존 프로세스 확인

### 6.4 프론트엔드 빌드 검증 (Phase 2)

- `npm run build` — 타입 오류 없음
- 브라우저 확인:
  - 업종순위 페이지: 가산점 표시 정상
  - 업종순위 설정: ④ 극단값 제외 섹션 제거됨, ⑤ 가중치 슬라이더 제거됨, "가산점 자동 계산" 안내문 표시
  - WS sector-scores 이벤트 수신 정상

### 6.5 UI 검증 (사용자 확인 항목 — Phase 2 후)

- 업종순위 페이지: 종합 가산점(0~300) 표시 정상
- 업종순위 설정: ④ 극단값 제외(트리밍) 섹션 사라짐 확인
- 업종순위 설정: ⑤ 가중치 슬라이더 사라짐 확인
- 업종순위 설정: "가산점 자동 계산" 안내문 표시 확인
- 업종순위 설정: ①~③ 설정 정상 동작 확인 (④⑤ 제거 후 번호 재정렬)
- 매수 후보 테이블: 업종 순위 기반 매수 타겟 정상 생성

---

## 7. 아키텍처 원칙 준수 검증 (갱신)

| 원칙 | 준수 여부 | 근거 |
|------|----------|------|
| P10 (SSOT) | 준수 | 트리밍 제거로 `scored_rise_ratio`/`scored_trade_amount` 제거 → `rise_ratio`/`avg_trade_amount` 단일 소스로 통합. 2차 가산점은 `change_rate` 단일 소스에서 계산. 컷오프 기준이 `calculate_bonus_scores` 내부 1곳으로 이관 (옵션 C). `total_trade_amount` → `avg_trade_amount` 명명 변경으로 이름-의미 일치. |
| P16 (살아있는 경로) | 준수 | `percentile_to_score`, `calculate_bonus_scores` 모두 `compute_sector_scores` 경로에서 호출. 트리밍 로직 제거 시 참조하는 설정 키(`sector_trim_*`)도 함께 제거. `MetricDef`/`DEFAULT_METRICS` 제거 시 모든 참조 제거. |
| P20 (폴백 금지) | 준수 | 임계값/기본값 폴백 없음. 빈 리스트/단일 값은 명시적 처리 (0점 또는 100점). 트리밍 제거로 인위적 잘라내기 폴백도 제거. |
| P21 (사용자 투명성) | 준수 | `normalized_weights` 전송 제거 → 가산점 3단계 점수를 WS payload로 전송하여 사용자에게 투명하게 공개. 트리밍 UI 제거로 사용자에게 불필요한 설정 노출 제거. "가산점 자동 계산" 안내문으로 전환 사실 명시. |
| P22 (데이터 정합성) | 준수 | 옵션 C 적용 — 2차 가산점 모집단 = 컷오프 통과 업종 종목들. 컷오프 적용 후 통과 업종이 확정된 상태에서 모집단 구성. 진실 소스 1곳. 트리밍 제거로 원본 데이터 변형 없이 정합성 유지. |
| P23 (일관된 통일성) | 준수 | 매수 설정 `boost_score` 누적 합산 패턴과 동일 구조. `rank_to_score` 재사용. `avg_trade_amount` 명명으로 이름-의미 일치. |
| P24 (단순성) | 준수 | 가중치 슬라이더 + `normalize_weight_values` + `MetricDef` + 트리밍 로직/설정/UI 제거 → 구조 단순화. |

---

## 8. 리스크 및 고려사항 (갱신)

### 8.1 2차 가산점 모집단 시점 — 옵션 C 채택 (해결 완료)

**이전 검토에서 식별된 문제**: `calculate_bonus_scores` 호출 시점과 컷오프 적용 시점의 순서 불일치.

**해결**: 옵션 C (2패스 계산) 채택 — 섹션 2.2 참조. 컷오프 로직이 `calculate_bonus_scores` 내부로 이관되어 진실 소스 1곳. P10/P22 준수.

### 8.2 3차 가산점 1개 대형주 편향 + median 대안 (추가 조사)

트리밍 제거 시 거래대금 평균에서 1개 대형주의 영향이 그대로 반영:
- 예: 4종목 업종, 1개 대형주 거래대금 1000억, 나머지 3개 각 10억 → 평균 332.5억
- 20종목 업종, 전부 50억 → 평균 50억
- 3차 가산점에서 4종목 업종이 무조건 유리

**왜곡인지 정당한 평가인지**: 대형주가 있는 업종이 거래대금이 많은 것은 사실이므로 3차 가산점에서 유리한 것은 정당. 단, 2차 가산점(백분위 평균)이 부분 보완 — 대형주 1개만 있고 나머지 종목들이 안 오른 업종은 2차 가산점이 낮아 균형 유지.

**추가 대안 — median 기반 3차 가산점**:
- 3차 가산점의 원시값을 평균이 아닌 **중앙값(median)**으로 계산하면 1개 대형주 영향 차단
- 예: 4종목 [10, 10, 10, 1000] → median = 10 (1개 대형주 영향 제거)
- 단, median은 값의 절반만 반영하므로 "업종 전체 거래대금" 의미가 약화
- 또한 `rank_to_score`는 순위 기반이므로, 1개 대형주가 평균을 끌어올려 순위를 올리는 효과는 median으로 완화 가능

**결론**: 기본은 평균 유지. median 대안을 계획서에 명시하되, 구현 후 실제 데이터로 1개 대형주 업종의 점수 편향 정도 모니터링. 편향이 심할 경우 median으로 전환 검토. 전체 점수의 1/3이므로 치명적이지는 않으나 확인 필요.

### 8.3 `percentile_to_score` vs `rank_to_score` 중복

두 함수는 유사하지만 스케일이 다름:
- `rank_to_score`: 꼴찌도 `1/N×100`점 — 업종 간 순위 비교 (1위와 꼴찌 모두 의미 있는 점수)
- `percentile_to_score`: 꼴찌 = 0점 — 종목 간 상대 비교 (가장 하락 종목은 0점)

P24(단순성) 관점에서 하나로 통합 가능하나, 의미가 다르므로 분리 유지 권장. `rank_to_score`는 업종 간 순위(1차/3차), `percentile_to_score`는 종목 간 백분위(2차)로 역할 분담.

### 8.4 기존 설정 데이터 마이그레이션

기존 사용자가 `sector_weights` 및 트리밍 값을 변경한 상태에서 새 버전으로 업데이트 시:
- `settings_file.py`의 `_migrate_sector_weights` 제거 → 기존 `sector_weights` 키가 설정 파일에 잔존
- `sector_trim_trade_amt_pct`, `sector_trim_change_rate_pct` 키도 설정 파일에 잔존
- 잔존 키는 무시됨 (사용되지 않음) — 기능 영향 없음
- 단, 설정 파일 정합성 검증 시 잔존 키 처리 로직 확인 필요

### 8.5 2차 가산점 계산 엣지 케이스

**통과 업종이 1개이고 종목이 1개인 경우**:
- `percentile_to_score([단일값])` = [100.0] — 정의대로 100점
- 해당 업종 2차 가산점 = 100점 — 극단적이지만 정당함 (유일한 통과 종목이므로)

**통과 업종이 0개인 경우** (min_rise_ratio 매우 높을 때):
- 2차 가산점 모집단 = 빈 리스트 → 모든 업종 2차 가산점 = 0.0
- final_score = 1차 + 0 + 3차 → 1차/3차만으로 순위 결정
- 정당함 (통과 업종이 없으므로 2차 상대평가 무의미)

### 8.6 WS payload 크기 + 하위 호환성

**신규 필드 추가**:
- 기존: `rank`, `sector`, `final_score`, `total_trade_amount`, `rise_ratio`, `total` (6개 필드)
- 신규: + `bonus_rise_ratio`, `bonus_relative_strength`, `bonus_trade_amount` (3개 필드 추가)
- 업종 수 20~50개 × 3개 필드 × 소수점 = 수백 바이트 증가 — 무시 가능

**하위 호환성 유지 (Phase 1→Phase 2 전환 안전성)**:
- `final_score` 필드명 유지 (값 범위만 0~100 → 0~300)
- `total_trade_amount` → `avg_trade_amount` 명명 변경 — **프론트엔드 Phase 2에서 함께 변경**
- `scored_trade_amount` 제거 — 프론트엔드 미참조 확인 완료
- `normalized_weights` 제거 — 프론트엔드 Phase 2에서 uiStore/binding 처리
- **주의**: `total_trade_amount` → `avg_trade_amount` 명명 변경 시, Phase 1(백엔드)에서 WS payload 필드명이 `avg_trade_amount`로 변경되면 프론트엔드(Phase 2 전)가 `total_trade_amount`를 참조하므로 일시적 에러. → **해결**: Phase 1에서 WS payload에 `avg_trade_amount`만 전송, 프론트엔드 Phase 2에서 `avg_trade_amount`로 전환. Phase 1 완료 후 프론트엔드가 일시적으로 거래대금 표시 깨짐 → Phase 2에서 즉시 수정. 또는 Phase 1에서 WS payload에 `total_trade_amount`와 `avg_trade_amount` 둘 다 전송 (하위 호환), Phase 2 완료 후 `total_trade_amount` 제거 (Phase 3 또는 별도). **추천**: 후자 (안전한 전환).

### 8.7 `createDualLabelSlider` 삭제 불가 (계획서 갱신으로 수정)

이전 계획서에서 "삭제 검토"로 기재되었으나, `createDualLabelSlider`는 `buy-settings.ts:11,267`에서 매수설정 `boostOrderDualSlider`로 사용 중. 삭제하면 매수설정 슬라이더 깨짐. → **삭제 불가, 유지**. `sliderConvert.ts`만 삭제 (sector-settings.ts 전용).

---

## 9. 구현 순서 (갱신 — Phase 1+2 통합)

### 9.1 Phase 구조 (3세션)

1. **Phase 1: 백엔드 전환 (1세션)** — 도메인 + 서비스 + 설정 통합
   - 백엔드 11개 파일 전환
   - 검증: 런타임 기동 + 신규 함수 단위 테스트
   - 커밋 + HANDOVER.md 갱신

2. **Phase 2: 프론트엔드 전환 (1세션)** — UI + 타입 + 바인딩
   - 프론트엔드 8개 파일 전환 + sliderConvert.ts 삭제
   - 검증: `npm run build` + 브라우저 확인
   - 커밋 + HANDOVER.md 갱신

3. **Phase 3: 테스트 전환 (1세션)** — 백엔드 테스트 12개 + 프론트엔드 테스트 1개
   - 테스트 전면 수정
   - 검증: pytest 전체 통과 + ruff 0건 + 프론트엔드 빌드
   - 커밋 + HANDOVER.md 갱신

### 9.2 각 Phase 완료 시

- 커밋 + HANDOVER.md 갱신 + 사용자 보고
- 다음 Phase는 다음 세션에서 HANDOVER.md 기반으로 진행 (규칙 0-1)

### 9.3 시작점

사용자 "진행해" 지시 후 Phase 1부터 착수.

---

## 10. 사전 조사 요약 (갱신 — 규칙 0-2 준수)

### 10.1 의존성 (전체 코드베이스)

**백엔드 (11개 파일)**:
1. `backend/app/domain/models.py` — `MetricDef`, `DEFAULT_METRICS`, `SectorScore.scored_*`, `metric_scores`, `total_trade_amount`
2. `backend/app/domain/sector_score.py` — `normalize_weight_values`, `calculate_weighted_scores`, `rank_to_score`
3. `backend/app/domain/sector_calculator.py` — `compute_sector_scores`, `compute_full_sector_summary` (sector_weights, trim_* 파라미터)
4. `backend/app/services/engine_sector_confirm.py` — L83,161 (calculate_weighted_scores 호출), L120-140, L229-239 (sector_weights, trim_* 변수/인자), L163-173 (컷오프)
5. `backend/app/services/sector_data_provider.py` — L221 (scored_trade_amount → WS payload), L246-257 (trim_*, sector_weights)
6. `backend/app/services/engine_account_notify.py` — L282-287,325,343 (normalize_weight_values, normalized_weights)
7. `backend/app/core/settings_defaults.py` — L88-90 (sector_trim_*, sector_weights 기본값)
8. `backend/app/core/engine_settings.py` — L146-174 (sector_weights, sector_trim_* 빌드/검증)
9. `backend/app/core/settings_file.py` — L18-43 (migrate_rank_primary_to_weights, _migrate_sector_weights)
10. `backend/app/services/telegram_bot.py` — L460,472 (scored_trade_amount)
11. `backend/app/services/engine_service.py` — L160 (sector_weights 참조)

**프론트엔드 (9개 파일)**:
1. `frontend/src/pages/sector-settings.ts` — ④ 트리밍 섹션, ⑤ 가중치 슬라이더, NUM_KEYS, syncFromSettings, dualSlider, saveWeightsNow, updateAppliedWeightsLabel, updateSliderUI, prevNormalizedWeights, uiStore 구독
2. `frontend/src/pages/sector-ranking-list.ts` — L150-153 (final_score 표시), L196-202 (헤더), L154-155 (바 그래프)
3. **`frontend/src/pages/sector-stock.ts`** (계획서 갱신으로 신규 추가) — L156,180-184,211 (sectorScores, final_score로 업종 정렬/점수 매핑)
4. `frontend/src/types/index.ts` — L150 (sector_weights), L153-154 (sector_trim_*), L234-241 (SectorScoreRow), L247 (normalized_weights)
5. `frontend/src/stores/uiStore.ts` — L58,84 (normalizedWeights)
6. `frontend/src/binding.ts` — L299-301 (normalized_weights 수신)
7. `frontend/src/stores/hotStore.ts` — L40,55,514-542 (sectorScores, SectorScoreRow)
8. `frontend/src/utils/sliderConvert.ts` — sector-settings.ts에서만 사용 → 삭제 가능
9. `frontend/src/components/common/create-slider.ts` — `createDualLabelSlider`는 buy-settings.ts에서도 사용 → **삭제 불가** (계획서 갱신)

**테스트 (14개 파일)**:
- 백엔드 12개: test_sector_score.py, test_sector_calculator.py, test_sector_calculator_integration.py, test_engine_sector_confirm.py, test_settings_file.py, test_engine_settings.py, test_buy_filter.py, test_telegram_bot.py, test_sector_data_provider.py, test_pipeline_compute.py, test_web_ws_routes.py, test_engine_snapshot.py
- 프론트엔드 2개: sliderConvert.test.ts (삭제), create-slider.ui.test.ts (유지)

### 10.2 영향 범위

- **백엔드**: 11개 파일 (도메인 3, 서비스 4, 코어 3, 기타 1)
- **프론트엔드**: 9개 파일 (페이지 3, 타입 1, 스토어 2, 바인딩 1, 유틸 1, 컴포넌트 1)
- **테스트**: 14개 파일 (백엔드 12, 프론트엔드 2)

### 10.3 아키텍처 원칙 부합 여부

- **P10 (SSOT)**: scored_* 필드 제거 → rise_ratio/avg_trade_amount 통합. 2차 가산점은 change_rate 단일 소스. 컷오프 기준 1곳으로 이관 (옵션 C). avg_trade_amount 명명 변경. ✓
- **P16 (살아있는 경로)**: 신규 함수가 compute_sector_scores 경로에서 호출. 기존 함수/필드 제거 시 참조도 함께 제거. ✓
- **P20 (폴백 금지)**: 임계값/기본값 폴백 없음. 빈 리스트/단일 값 명시적 처리. ✓
- **P21 (사용자 투명성)**: normalized_weights 전송 제거 → 가산점 3단계 점수 WS 전송. "가산점 자동 계산" 안내문. ✓
- **P22 (데이터 정합성)**: 옵션 C 적용 — 컷오프 후 통과 업종만 모집단. 진실 소스 1곳. ✓
- **P23 (일관성)**: 매수 설정 boost_score 패턴 부합. rank_to_score 재사용. avg_trade_amount 명명. ✓
- **P24 (단순성)**: 가중치 슬라이더 + normalize_weight_values + MetricDef + 트리밍 제거. ✓

---

## 11. 참고 자료

- 기존 순위 기반 점수 계획서: `docs/plan_score_rank_based.md`
- 아키텍처 원칙: `ARCHITECTURE.md` 제1부 "불변 원칙 24개"
- 매수 설정 가산점 구조: `backend/app/domain/buy_filter.py:8-61`
- 현재 업종 점수 계산: `backend/app/domain/sector_score.py:77-130`
- 현재 가중치 슬라이더 UI: `frontend/src/pages/sector-settings.ts:207-247`
- 현재 컷오프 로직: `backend/app/services/engine_sector_confirm.py:163-173`

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
| 10 | "트리밍은 min-max 정규화 시절 이상치 왜곡 방지용. 순위/백분위 기반이니 불필요. 인위적 잘라내기가 왜곡. 관련 설정 UI도 제거" | 트리밍 로직/파라미터/설정/UI 전체 제거. `scored_rise_ratio`/`scored_trade_amount` 필드 제거 → `rise_ratio`/`avg_trade_amount`로 통합. 2차 가산점(백분위 평균)이 1개 대형주 영향 부분 보완. |

## 부록 B: 계획서 갱신 이력

| 일시 | 갱신 내용 |
|------|----------|
| 2026-07-13 (최초) | 계획서 최초 작성 (사전 조사 완료, 구현 대기) |
| 2026-07-13 (갱신) | 사전조사 폭넓게 확장 (프론트엔드 보강, sector-stock.ts 누락 발견, createDualLabelSlider 삭제 불가 확인). 설계 문제 2건 해결 (옵션 C 채택, Phase 1+2 통합). 프론트엔드 UI 수정 계획 상세화. 추가 개선점 제시 (median 대안, avg_trade_amount 명명 변경, WS payload 하위 호환성). |
