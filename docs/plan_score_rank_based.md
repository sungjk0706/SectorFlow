# 업종 점수 계산 방식 전환 수정 계획서

> **작성일**: 2026-07-12
> **상태**: 계획 승인됨, 구현 대기 (다음 세션에서 진행)
> **방향**: min-max 정규화 → 순위 기반 점수 (트리밍은 유지)

---

## 1. 배경 및 목적

### 1.1 설계 의도

사용자의 원래 설계 의도:
- 업종별로 "상승비율이 높은 순"과 "거래대금이 많은 순"을 **각각 따로 매김**
- 사용자가 슬라이더로 어느 쪽에 가중치를 더 줄지 결정
- 거래대금 100% → 돈 몰리는 업종 위주, 상승비율 100% → 골고루 오르는 업종 위주

### 1.2 현재 구현의 문제

현재 코드는 min-max 정규화 방식:
- 각 지표를 0~100점으로 변환 후 가중치로 가중합
- 거래대금의 long-tail 분포에 취약 (하나가 튀면 나머지가 0점 압축)
- "87.5점" 같은 추상적 숫자가 슬라이더 의미와 직결되지 않음
- 트리밍으로 완화하려 했으나 근본 해결 아님

### 1.3 전환 방향

- **제거**: min-max 정규화 (`normalize_metric_value` 함수)
- **추가**: 순위 기반 점수 변환 (지표별 순위 → 순위 점수)
- **유지**: 트리밍 로직, 가중치 정규화, 가중치 적용, 업종 컷오프

---

## 2. 순위 기반 점수 계산 방식 상세

### 2.1 계산 흐름

```
트리밍 후 scored_trade_amount, scored_rise_ratio (기존 유지)
    │
    ▼
각 지표별 순위 매기기 (1위, 2위, 3위, ...)
    │
    ▼
순위 → 점수 변환: 순위 점수 = (N - rank + 1) / N × 100
    │  (N = 전체 업종 수, 1위 = 100점, N위 = 100/N 점)
    ▼
final_score = (거래대금 순위점수 × 가중치) + (상승비율 순위점수 × 가중치)
    │
    ▼
final_score 내림차순 정렬 + 동점 처리
    │
    ▼
rank 부여 (1-based)
```

### 2.2 순위 점수 변환 공식

```
순위 점수 = (N - rank + 1) / N × 100
```

- N = 전체 업종 수
- 1위 = 100.0점
- 2위 = (N-1)/N × 100
- N위 = 1/N × 100

**예시** (5개 업종):
| 순위 | 순위 점수 |
|------|---------|
| 1위 | (5-1+1)/5 × 100 = 100.0 |
| 2위 | (5-2+1)/5 × 100 = 80.0 |
| 3위 | (5-3+1)/5 × 100 = 60.0 |
| 4위 | (5-4+1)/5 × 100 = 40.0 |
| 5위 | (5-5+1)/5 × 100 = 20.0 |

### 2.3 동점 순위 처리

값이 같은 업종들은 **같은 순위**를 받고, 다음 순위는 건너뜀 (표준 순위 방식).

**예시** (거래대금이 같은 2개 업종):
- A: 50억, B: 50억, C: 30억, D: 20억
- A와 B는 공동 1위, C는 3위, D는 4위
- 순위 점수: A=100, B=100, C=50, D=25

### 2.4 최종 점수 산출

```
final_score = (거래대금 순위점수 × 거래대금 가중치) + (상승비율 순위점수 × 상승비율 가중치)
```

**예시** (가중치 50:50, 5개 업종):

| 업종 | 거래대금 순위 | 거래 점수 | 상승비율 순위 | 상승 점수 | 최종 점수 |
|------|-------------|---------|-------------|---------|---------|
| 반도체 | 1위 | 100.0 | 2위 | 80.0 | 90.0 |
| 자동차 | 2위 | 80.0 | 1위 | 100.0 | 90.0 |
| 건설 | 3위 | 60.0 | 3위 | 60.0 | 60.0 |
| 은행 | 4위 | 40.0 | 4위 | 40.0 | 40.0 |
| 화학 | 5위 | 20.0 | 5위 | 20.0 | 20.0 |

### 2.5 동점 처리 규칙 (최종 순위)

final_score가 같을 경우 다음 순서로 타이브레이크:

1. final_score 내림차순
2. 동점 시 → 상승비율 트리밍 후 원시값 (`scored_rise_ratio`) 내림차순
3. 동점 시 → 거래대금 트리밍 후 원시값 (`scored_trade_amount`) 내림차순
4. 동점 시 → 업종명 오름차순 (결정적 정렬)

> **현재 코드와의 차이**: 현재는 2번이 `metric_scores["rise_ratio"]` (정규화 점수) 기준.
> 순위 기반에서는 정규화 점수가 의미가 없으므로 원시값으로 변경.
> 3번(거래대금 원시값)은 신규 추가.

---

## 3. 변경 대상 파일 및 함수

### 3.1 백엔드 — 핵심 변경

#### 파일 1: `backend/app/domain/sector_score.py`

| 항목 | 내용 |
|------|------|
| **제거** | `normalize_metric_value` 함수 (10~35줄) — min-max 정규화 |
| **유지** | `normalize_weight_values` 함수 (38~61줄) — 가중치 정규화 (합=1.0) |
| **수정** | `calculate_weighted_scores` 함수 (64~111줄) — 정규화 → 순위 기반으로 내부 로직 교체 |

**`calculate_weighted_scores` 변경 상세:**

제거:
- `normalize_metric_value` 호출 및 `metric_scores` 설정 부분 (91~95줄)

추가:
- 각 지표별 순위 매기기 (원시값 기준 정렬 → 순위 부여)
- 순위 → 점수 변환: `(N - rank + 1) / N × 100`
- 동점 순위 처리 (같은 값 = 같은 순위, 다음 순위 건너뜀)

수정:
- `final_score` 계산: `Σ(순위점수_i × 가중치_i)` (기존과 동일 구조, 점수 출처만 변경)
- 정렬 키: `metric_scores.get("rise_ratio")` → `scored_rise_ratio` (원시값)로 변경
- 정렬 키에 `scored_trade_amount` (원시값) 추가

#### 파일 2: `backend/app/domain/models.py`

| 항목 | 내용 |
|------|------|
| **수정** | `SectorScore.metric_scores` 필드 주석 (51줄) — "지표별 정규화 점수" → "지표별 순위 점수" |
| **유지** | `final_score` 필드 (50줄) — 0.0~100.0 범위 동일 |
| **유지** | `MetricDef` 구조 (76~99줄) — `extract` 함수 그대로 사용 (순위 매기기 위한 원시값 추출) |

> `metric_scores` 필드 자체는 유지. 값의 의미만 "정규화 점수" → "순위 점수"로 변경.
> UI에서 지표별 점수를 표시할 일이 있으면 순위 점수가 표시됨.

#### 파일 3: `backend/app/domain/sector_calculator.py`

| 항목 | 내용 |
|------|------|
| **유지** | 트리밍 로직 전체 (138~166줄) — 변경 없음 |
| **유지** | `compute_sector_scores` 함수 구조 — 변경 없음 |
| **유지** | `calculate_weighted_scores` 호출 (183줄) — 변경 없음 |

> 트리밍 후 값(`scored_trade_amount`, `scored_rise_ratio`)이 순위 기반의 입력값이 됨.

### 3.2 백엔드 — 간접 영향

#### 파일 4: `backend/app/services/engine_sector_confirm.py`

| 항목 | 내용 |
|------|------|
| **유지** | `calculate_weighted_scores` import 및 호출 (82줄, 160줄) — 변경 없음 |
| **유지** | 증분 재계산 로직 — 변경 없음 |

> `calculate_weighted_scores` 함수 시그니처가 동일하므로 호출부 변경 불필요.

#### 파일 5: `backend/app/services/engine_account_notify.py`

| 항목 | 내용 |
|------|------|
| **유지** | `normalize_weight_values` import 및 호출 (282줄, 287줄) — 변경 없음 |
| **유지** | `final_score` 전송 (sector_data_provider 통해) — 변경 없음 |

> 가중치 정규화는 유지되므로 `normalized_weights` 전송 로직 변경 없음.

#### 파일 6: `backend/app/services/sector_data_provider.py`

| 항목 | 내용 |
|------|------|
| **유지** | `get_sector_scores_snapshot` (204~227줄) — `final_score` 전송 유지 |
| **유지** | `scored_trade_amount`, `rise_ratio` 전송 — 변경 없음 |

> UI에 전송되는 데이터 구조 동일. `final_score` 값의 계산 방식만 변경됨.

### 3.3 프론트엔드 — 표시 로직

#### 파일 7: `frontend/src/pages/sector-ranking-list.ts`

| 항목 | 내용 |
|------|------|
| **유지** | `final_score` 기반 정렬 (96줄, 102줄) — 변경 없음 |
| **유지** | 점수 바 너비 계산 (125줄) — `final_score / maxScore` 비율 유지 |
| **유지** | 점수 표시 (121줄) — `final_score.toFixed(1)` 유지 |

> 프론트엔드는 `final_score` 값을 그대로 표시하므로 코드 변경 불필요.
> 단, 점수 바의 시각적 분포가 달라질 수 있음 (순위 기반이므로 균등한 간격).

#### 파일 8: `frontend/src/types/index.ts`

| 항목 | 내용 |
|------|------|
| **유지** | `SectorScoreRow` 인터페이스 (228~235줄) — 변경 없음 |

#### 파일 9: `frontend/src/pages/sector-stock.ts`

| 항목 | 내용 |
|------|------|
| **유지** | `final_score` 기반 정렬 (181~184줄, 211줄) — 변경 없음 |

### 3.4 문서

#### 파일 10: `ARCHITECTURE.md`

| 항목 | 내용 |
|------|------|
| **수정** | 5.2절 (598줄) — "min-max 정규화 + 가중치 점수" → "순위 기반 점수 + 가중치 점수" |
| **수정** | 6.2절 (701~714줄) — 계산 과정 설명을 순위 기반으로 변경 |
| **수정** | 6.3절 (716~720줄) — 트리밍 설명 유지, "순위 기반에서 이상치 영향 감소" 추가 |

#### 파일 11: `docs/architecture_audit_plan.md`

| 항목 | 내용 |
|------|------|
| **확인** | 섹션 7 문제 기록에 이력 추가 (역사적 로그는 유지) |

### 3.5 테스트

#### 파일 12: `backend/tests/test_sector_score.py`

| 항목 | 내용 |
|------|------|
| **제거** | `TestNormalizeMetricValue` 클래스 (16~36줄) — `normalize_metric_value` 함수 제거됨 |
| **수정** | `TestCalculateWeightedScores` 클래스 (84~152줄) — 순위 기반 점수 검증으로 변경 |
| **유지** | `TestNormalizeWeightValues` 클래스 (41~79줄) — 가중치 정규화는 유지됨 |

**테스트 수정 상세:**
- `test_single_sector_gets_rank_1`: 단일 업종 100점 — 유지 (순위 기반도 1위=100점)
- `test_ranking_by_final_score_descending`: 순위 내림차순 검증 — 유지
- `test_metric_scores_populated`: `metric_scores` 키 존재 검증 — 유지 (순위 점수 저장)
- `test_tiebreak_by_rise_ratio_then_sector_name`: 동점 처리 검증 — 수정 (원시값 기준)
- `test_custom_weights_affect_ranking`: 가중치 효과 검증 — 수정 (순위 기반으로 결과 변경)

**추가 테스트:**
- 동점 순위 처리 테스트 (같은 값 → 같은 순위 → 같은 점수)
- 순위 점수 공식 검증 테스트 (N개 업종 시 점수 간격)
- 동점 타이브레이크 3단계 테스트 (final_score → 상승비율 원시값 → 거래대금 원시값 → 업종명)

#### 파일 13: `backend/tests/test_sector_calculator.py`

| 항목 | 내용 |
|------|------|
| **수정** | `test_ranking_by_final_score` (155~162줄) — 순위 기반 결과로 업데이트 |
| **수정** | `final_score >= 0` 검증 (439줄) — 유지 (순위 점수도 0~100) |

#### 파일 14: `backend/tests/test_sector_calculator_integration.py`

| 항목 | 내용 |
|------|------|
| **수정** | `final_score` 범위 검증 (227~229줄) — 유지 (0~100 범위 동일) |
| **수정** | `metric_scores` 존재 검증 (229줄) — 유지 |

#### 파일 15: `backend/tests/test_engine_sector_confirm.py`

| 항목 | 내용 |
|------|------|
| **유지** | `calculate_weighted_scores` mock 패치 (436~759줄) — 함수명 동일하므로 유지 |
| **수정** | `_make_sector_score` 헬퍼 (363~368줄) — `final_score` 기본값 의미 변경 가능성 검토 |

#### 파일 16: `backend/tests/test_sector_data_provider.py`

| 항목 | 내용 |
|------|------|
| **유지** | `final_score` 전송 검증 (41~71줄) — 값 전송 로직 동일 |

#### 파일 17: `backend/tests/test_pipeline_compute.py`

| 항목 | 내용 |
|------|------|
| **유지** | `final_score` mock 데이터 (1185줄) — mock이므로 변경 불필요 |

---

## 4. 제거할 코드

### 4.1 `normalize_metric_value` 함수 (sector_score.py 10~35줄)

```python
def normalize_metric_value(
    values: list[float],
    higher_is_better: bool = True,
) -> list[float]:
    """..."""
    if not values:
        return []
    if len(values) == 1:
        return [100.0]
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [100.0] * len(values)
    span = hi - lo
    if higher_is_better:
        return [round((v - lo) / span * 100.0, 1) for v in values]
    return [round((hi - v) / span * 100.0, 1) for v in values]
```

**제거 사유**: min-max 정규화 방식 제거. 순위 기반 점수로 대체.

### 4.2 `calculate_weighted_scores` 내 정규화 부분 (sector_score.py 90~95줄)

```python
    # 2. 각 지표별 원시값 추출 → 정규화 → metric_scores 저장
    for metric in metrics:
        raw_values = [metric.extract(sc) for sc in sector_scores]
        normalized = normalize_metric_value(raw_values, metric.higher_is_better)
        for sc, norm_val in zip(sector_scores, normalized):
            sc.metric_scores[metric.key] = norm_val
```

**제거 사유**: 정규화 → 순위 기반 점수 변환으로 교체.

### 4.3 정렬 키의 `metric_scores` 참조 (sector_score.py 106줄)

```python
    key=lambda s: (-s.final_score, -s.metric_scores.get("rise_ratio", 0.0), s.sector),
```

**제거 사유**: `metric_scores["rise_ratio"]` (정규화 점수) 대신 `scored_rise_ratio` (원시값) 사용.

---

## 5. 새로 추가할 코드

### 5.1 순위 기반 점수 변환 함수 (sector_score.py)

`normalize_metric_value`를 대체하는 새 함수:

```python
def rank_to_score(
    values: list[float],
    higher_is_better: bool = True,
) -> list[float]:
    """
    원시값 리스트를 순위 기반 점수(0~100)로 변환.

    - 값이 클수록 좋으면: 큰 값이 1위 → 100점
    - 동점 처리: 같은 값은 같은 순위, 다음 순위는 건너뜀 (표준 순위)
    - 순위 점수 = (N - rank + 1) / N × 100
    - N=1이면 100점, 빈 리스트면 빈 리스트
    - 소수점 첫째 자리 반올림
    """
```

**구현 로직:**
1. 값과 인덱스 페어 생성
2. `higher_is_better=True`면 내림차순, `False`면 오름차순 정렬
3. 동점 그룹 식별 (같은 값 = 같은 순위)
4. 순위 → 점수 변환: `(N - rank + 1) / N × 100`
5. 원래 인덱스 순서대로 복원

### 5.2 `calculate_weighted_scores` 내 순위 기반 계산 (sector_score.py)

```python
    # 2. 각 지표별 원시값 추출 → 순위 점수 변환 → metric_scores 저장
    for metric in metrics:
        raw_values = [metric.extract(sc) for sc in sector_scores]
        rank_scores = rank_to_score(raw_values, metric.higher_is_better)
        for sc, rank_val in zip(sector_scores, rank_scores):
            sc.metric_scores[metric.key] = rank_val
```

### 5.3 정렬 키 수정 (sector_score.py)

```python
    # 4. 정렬: final_score 내림차순, 동점 시 scored_rise_ratio 내림차순,
    #         동점 시 scored_trade_amount 내림차순, 최종 동점 시 업종명 오름차순
    sector_scores.sort(
        key=lambda s: (
            -s.final_score,
            -s.scored_rise_ratio,
            -s.scored_trade_amount,
            s.sector,
        ),
    )
```

---

## 6. 유지할 코드 (변경 없음)

| 파일 | 함수/로직 | 유지 사유 |
|------|---------|---------|
| sector_calculator.py | 트리밍 로직 (138~166줄) | 대형주 왜곡 방지, 순위 기반에서도 필요 |
| sector_score.py | `normalize_weight_values` (38~61줄) | 가중치 합=1.0 정규화, 순위 기반에서도 동일하게 필요 |
| sector_filter.py | `filter_by_avg_amt` | 1차 필터, 점수 계산 방식과 무관 |
| sector_calculator.py | 업종 그룹핑, StockScore 생성 | 점수 계산 방식과 무관 |
| sector_calculator.py | 업종 컷오프 (min_rise_ratio) | rank=0 처리, 점수 계산 방식과 무관 |
| buy_filter.py | 매수 후보, 가산점, 가드 필터 | 업종 점수 계산과 분리됨 |
| engine_sector_confirm.py | 증분 재계산 로직 | `calculate_weighted_scores` 시그니처 동일 |
| sector_data_provider.py | 스냅샷 전송 | `final_score` 필드 유지 |
| engine_account_notify.py | WS 전송, 가중치 전송 | 데이터 구조 동일 |
| 프론트엔드 전체 | 점수 표시, 정렬, 바 너비 | `final_score` 값 표시, 계산 방식 무관 |

---

## 7. 영향 범위

### 7.1 직접 영향

| 항목 | 영향 내용 |
|------|---------|
| `final_score` 값 | 계산 방식 변경으로 값 자체가 달라짐. 기존 85.4점 → 90.0점 등 |
| 업종 순위 | 대부분 동일하나, 동점 처리 방식 변경으로 일부 순위 변동 가능 |
| `metric_scores` 값 | 정규화 점수 → 순위 점수로 의미 변경. 값 범위는 0~100 동일 |

### 7.2 간접 영향

| 항목 | 영향 내용 |
|------|---------|
| 매수 후보 | 상위 N개 업종 내 종목이 매수 후보. 업종 순위 변동 시 매수 후보 종목 변동 가능 |
| UI 점수 바 | 점수 바 너비가 `final_score / maxScore` 비율. 순위 기반은 균등한 간격이므로 바 분포가 균일해짐 |
| WS 전송 | `final_score` 값 변경. delta 전송 로직은 값 변경 감지하므로 자동 반영 |
| 가중치 슬라이더 | 의미가 더 직관적으로 연결됨. "거래대금 70%" = 거래대금 순위에 70% 가중치 |

### 7.3 영향 없음

| 항목 | 사유 |
|------|------|
| 트리밍 설정값 | 트리밍 로직 유지 |
| 1차 필터 (5일평균거래대금) | 점수 계산 전 단계, 무관 |
| 가산점 (고가돌파, 호가잔량비, 프순매, 거래대금순위) | 매수 후보 정렬 단계, 업종 점수와 분리 |
| 가드 필터 (상승률/하락률/체결강도) | 종목 단위 필터, 업종 점수와 분리 |
| 보유/금일매수 차단 | 종목 단위, 무관 |

---

## 8. 검증 방법

### 8.1 단위 테스트

| 테스트 파일 | 검증 내용 |
|------------|---------|
| test_sector_score.py | `rank_to_score` 함수: 순위 점수 공식, 동점 처리, 빈 리스트, 단일 업종 |
| test_sector_score.py | `calculate_weighted_scores`: 순위 기반 점수 계산, 가중치 효과, 동점 타이브레이크 3단계 |
| test_sector_score.py | `normalize_weight_values`: 기존 테스트 유지 (가중치 정규화 변경 없음) |
| test_sector_calculator.py | 통합: 트리밍 후 순위 기반 점수 계산, final_score 범위 0~100 |
| test_sector_calculator_integration.py | 통합: final_score 계산, metric_scores 존재 |
| test_engine_sector_confirm.py | 증분 재계산: calculate_weighted_scores 호출 유지 |

### 8.2 런타임 기동 확인

- `.venv/bin/python main.py` 기동
- 로그 확인: 업종 점수 계산 로그, 에러 없음
- 10~30초 대기 후 종료
- 잔존 프로세스 없음 확인

### 8.3 UI 확인 (사용자 확인 항목)

- 업종순위 화면: 점수 바 분포가 균등한 간격으로 표시되는지
- 업종순위 화면: 순위와 점수가 일치하는지 (1위가 가장 높은 점수)
- 설정 화면: 가중치 슬라이더 변경 시 업종 순위가 변하는지
- 매수 후보 화면: 상위 N개 업종 내 종목이 표시되는지

---

## 9. 아키텍처 원칙 부합 여부

### 9.1 P10 (SSOT — 단일 진실 소스)

| 항목 | 부합 여부 |
|------|---------|
| 점수 계산 입력값 | **부합**. `scored_trade_amount`, `scored_rise_ratio` 단일 소스 유지 |
| 가중치 | **부합**. `normalize_weight_values` 단일 함수 유지 |
| 순위 점수 | **부합**. `rank_to_score` 단일 함수로 순위 변환 집중 |

### 9.2 P16 (구현 = 살아있는 경로 배선)

| 항목 | 부합 여부 |
|------|---------|
| `normalize_metric_value` 제거 | **부합**. 제거 후 잔존 참조 없음 확인 필요 (전체 검색) |
| `rank_to_score` 추가 | **부합**. `calculate_weighted_scores`에서 호출되는 살아있는 경로 |

### 9.3 P20 (폴백 금지)

| 항목 | 부합 여부 |
|------|---------|
| 순위 점수 계산 | **부합**. 빈 리스트 → 빈 리스트, 단일 업종 → 100점 (예외 처리이지 폴백 아님) |
| 동점 처리 | **부합**. 같은 값 = 같은 순위 (규칙 기반, 폴백 아님) |

### 9.4 P21 (사용자 투명성)

| 항목 | 부합 여부 |
|------|---------|
| 점수 계산 방식 | **개선**. 순위 기반이 사용자 직관에 부합 ("1위, 2위"가 "87.5점"보다 투명) |
| 가중치 의미 | **개선**. 슬라이더 = 순위 가중치로 의미 직결 |
| UI 표시 | **부합**. `final_score` 표시 유지, 값의 의미가 더 명확해짐 |

### 9.5 P22 (데이터 정합성)

| 항목 | 부합 여부 |
|------|---------|
| 트리밍 후 값 | **부합**. `scored_*` 필드 유지, 순위 계산 입력값으로 사용 |
| 동점 순위 | **부합**. 표준 순위 방식 (같은 값 = 같은 순위, 건너뜀)으로 정합성 보장 |

### 9.6 P23 (일관된 통일성)

| 항목 | 부합 여유 |
|------|---------|
| 용어 | **부합**. "순위 점수"로 용어 통일, ARCHITECTURE.md 업데이트 |
| 에러 처리 | **부합**. 빈 리스트, 단일 업종 예외 처리 패턴 기존과 일관 |
| 네이밍 | **부합**. `rank_to_score` 함수명이 목적 명확히 표현 |

### 9.7 P24 (단순성)

| 항목 | 부합 여부 |
|------|---------|
| 복잡도 감소 | **부합**. min-max 정규화 (예외 4종류) → 순위 기반 (예외 2종류: 빈 리스트, 단일 업종) |
| 불필요한 추상화 | **부합**. `normalize_metric_value`의 `higher_is_better` 분기 제거 (순위는 항상 higher_is_better) |
| 함수 길이 | **부합**. `rank_to_score`는 `normalize_metric_value`보다 단순 |
| 더 단순한 대체 | **부합**. 순위 기반이 min-max보다 단순하고 설계 의도에 부합 |

---

## 10. 코드 제거 시 주의사항 (AGENTS.md 코드 제거 규칙)

### 10.1 참조 주석 정리

- `normalize_metric_value` 제거 시, 이 함수를 참조하는 모든 주석/docstring 수정
- `sector_score.py` 모듈 docstring (3줄) 수정: "정규화 및 가중치 계산" → "순위 기반 점수 및 가중치 계산"

### 10.2 전체 검색 범위

제거 후 다음 검색어로 전체 코드베이스 검색하여 잔존 참조 확인:
- `normalize_metric_value`
- `normalize_metric`
- `min-max`
- `min_max`
- `minmax`

단, `architecture_audit_plan.md` 섹션 7의 역사적 로그는 유지.

### 10.3 테스트 파일 포함

- `test_sector_score.py`의 `TestNormalizeMetricValue` 클래스 제거
- 해당 클래스의 docstring/주석도 함께 제거

---

## 11. 구현 순서 (다음 세션)

1. **sector_score.py**: `normalize_metric_value` 제거, `rank_to_score` 추가, `calculate_weighted_scores` 수정
2. **models.py**: `metric_scores` 필드 주석 수정
3. **test_sector_score.py**: 테스트 수정 및 추가
4. **test_sector_calculator.py**: 테스트 수정
5. **test_sector_calculator_integration.py**: 테스트 수정
6. **ARCHITECTURE.md**: 5.2절, 6.2절, 6.3절 수정
7. **전체 검색**: `normalize_metric_value` 잔존 참조 확인
8. **런타임 기동**: `.venv/bin/python main.py` 확인
9. **단위 테스트 실행**: `pytest backend/tests/test_sector_score.py` 등
10. **UI 확인**: 사용자에게 업종순위 화면 확인 요청

---

## 12. 위험 요소 및 대응

### 12.1 동점 다발

**위험**: 순위 기반은 동점이 min-max보다 자주 발생. 5개 업종 시 20점 단위로만 구분.

**대응**: 3단계 타이브레이크 규칙으로 해결 (final_score → 상승비율 원시값 → 거래대금 원시값 → 업종명).

### 12.2 업종 수에 따른 점수 스케일 변화

**위험**: 3개 업종 시 100/67/33, 10개 업종 시 100/90/.../10. 업종 수가 많으면 상위권 간격 좁아짐.

**대응**: min-max도 동일한 문제. 실제 커스텀 업종 수(5~15개) 범위에서 심각하지 않음.

### 12.3 기존 점수 값과의 불연속

**위험**: 전환 시점에 final_score 값이 급변. 사용자가 혼란을 느낄 수 있음.

**대응**: 전환 시 사용자에게 사전 안내. "점수 계산 방식이 순위 기반으로 변경되어 점수 숫자가 달라집니다. 순위 자체는 크게 변하지 않습니다."

---

## 13. 요약

| 항목 | 내용 |
|------|------|
| 제거 | `normalize_metric_value` 함수 (min-max 정규화) |
| 추가 | `rank_to_score` 함수 (순위 기반 점수 변환) |
| 수정 | `calculate_weighted_scores` 내부 로직, 정렬 키, 테스트, 문서 |
| 유지 | 트리밍, 가중치 정규화, 업종 컷오프, 매수 후보, 가산점, 프론트엔드 |
| 변경 파일 | 백엔드 6개 + 프론트엔드 0개(변경 없음) + 테스트 3개 + 문서 2개 |
| 아키텍처 원칙 | P10, P16, P20, P21, P22, P23, P24 모두 부합 또는 개선 |
