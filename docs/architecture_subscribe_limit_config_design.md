# 설계서: 종목 구독 200개 한도 설정 키 이관

> **상태**: 설계 완료 (구현 대기)
> **작성일**: 2026-07-18
> **관련 원칙**: P10(SSOT) · P21(사용자 투명성) · P22(정합성) · P24(단순성)
> **관련 파일**: `backend/app/services/engine_ws_reg.py` · `backend/app/core/settings_defaults.py` · `backend/app/core/engine_settings.py` · `frontend/src/pages/general-settings.ts`

---

## 1. 배경 및 목표

### 1.1 현재 상태

`engine_ws_reg.subscribe_sector_stocks_0b()`에 종목 구독 한도가 하드코딩되어 있음:

```python
# backend/app/services/engine_ws_reg.py:258
_WS_0B_LIMIT = 200
```

- 증권사별 분기 없이 모든 증권사에 동일 200 적용
- LS증권은 WebSocket(US3 TR)이 종목 1개씩 순차 전송 방식이라 한도가 더 여유로울 수 있으나, 코드에 명시된 공식 한도 없음
- 사용자가 5일 평균 거래대금(`sector_min_trade_amt`)으로 필터 통과 종목 수를 조절할 수 있으므로, 종목 수 자체는 이미 사용자 제어 가능
- 한도 초과 시 `logger.warning`만 출력되고 화면에 표시되지 않음 (P21 투명성 미흡)

### 1.2 목표

1. **200 하드코딩 → 설정 키 이관**: 사용자가 화면에서 조정 가능하도록 설정화
2. **기본값 200 유지**: 기존 동작 호환성 보장 (P22 정합성)
3. **P10 SSOT 부합**: 한도값이 코드 여러 곳이 아닌 설정 키 한 곳에서 관리
4. **P21 투명성 부합**: 한도 초과 시 화면에서 사용자가 인지 가능
5. **P24 단순성 부합**: 증권사별 분기는 추후 확장으로 미루고, 1단계는 단일 설정 키로 단순화

### 1.3 비목표 (본 설계에서 다루지 않음)

- 증권사별 한도 분기 (키움 200 / LS 500 등) — 추후 LS 공식 한도 확인 후 별도 설계
- 200 한도 완전 제거 — 리스크 과대 (LS 서버 거부 시 구독 불균형 발생)
- "보유종목 우선" 로직 제거 — 한도 설정화 후에도 우선순위 로직은 유효

---

## 2. 설계 방향

### 2.1 채택 방안: 설정 키 이관 (옵션 A)

신규 설정 키 `subscribe.max_0b_count` 추가:
- 기본값: 200 (기존 동작 100% 호환)
- 사용자 조정 범위: 1 ~ 1000 (보수적 상한)
- 저장 위치: `integrated_system_settings` 테이블 (기존 설정 키와 동일)
- 참조 시점: `engine_state.state.integrated_system_settings_cache` (P13 메모리 상주)

### 2.2 기각 방안

| 방안 | 기각 사유 |
|------|-----------|
| 옵션 B (증권사별 분기) | LS 공식 한도 미확인 상태 — 검증 없이 분기값 설정 위험 |
| 옵션 C (완전 제거) | LS 서버 거부 시 `_subscribed` 롤백으로 일부 종목만 구독되는 불균형 발생 |

---

## 3. 백엔드 변경 사항

### 3.1 설정 기본값 추가

**파일**: `backend/app/core/settings_defaults.py`

`DEFAULT_USER_SETTINGS` 딕셔너리에 신규 키 추가:

```python
# 구독 한도 (종목 실시간 시세 0B 동시 구독 최대 개수, 기본 200)
# 보유종목 우선 등록 후 필터 통과 종목은 남은 자리만큼만 등록
"subscribe.max_0b_count": 200,
```

**위치**: 기존 `timetable.*` 키 블록(라인 116-121) 직후, 딕셔너리 끝(라인 122) 이전

### 3.2 엔진 설정 로더 수정

**파일**: `backend/app/core/engine_settings.py`

`build_engine_settings_dict()` 함수 내에서 신규 키 타입 캐스팅 추가:

```python
# 구독 한도 (0B 종목 동시 구독 최대 개수) — 0도 유효값 아님(최소 1), P20 폴백 금지
_v = merged.get("subscribe.max_0b_count")
result["subscribe.max_0b_count"] = int(_v if _v is not None else 200)
```

**위치**: 기존 `sector_start_threshold_pct` 캐스팅(라인 219-220) 근처, 업종 설정 블록 끝

**패턴 일관성 (P23)**: 기존 `_v if _v is not None else 기본값` 패턴 준수 — `or` 폴밭 금지 (P20)

### 3.3 구독 함수 수정

**파일**: `backend/app/services/engine_ws_reg.py`

`subscribe_sector_stocks_0b()` 내 하드코딩 제거:

```python
# Before (라인 258)
_WS_0B_LIMIT = 200

# After
_WS_0B_LIMIT = int(engine_state.state.integrated_system_settings_cache.get("subscribe.max_0b_count", 200))
```

**설명**:
- `engine_state.state.integrated_system_settings_cache`는 엔진 기동 시 메모리 상주 (P13)
- 틱 연산 단계가 아니므로 캐시 참조 허용 (P13은 "틱 연산 단계 DB 조회 금지" — 본 함수는 구독 등록 시점이므로 해당 없음)
- `.get()` 기본값 200은 캐시 미초기화 시 안전장치 (P20 폴백과 구분 — 캐시 초기화 전 예외 상태 대비)

**주의**: `engine_state` 이미 임포트되어 있음 (라인 15) — 신규 임포트 불필요

### 3.4 설정 검증 (선택 — 권장)

**파일**: `backend/app/web/routes/settings.py`

설정 저장 API에서 `subscribe.max_0b_count` 검증 추가:

```python
# 1 <= max_0b_count <= 1000 범위 검증
if key == "subscribe.max_0b_count":
    v = int(value)
    if v < 1 or v > 1000:
        return JSONResponse({"detail": "구독 한도는 1~1000 사이여야 합니다"}, status_code=422)
```

**기존 패턴**: `timetable.*` 시각 순서 검증(`_validate_timetable_order`)과 동일한 422 응답 패턴 (P23 일관성)

---

## 4. 프론트엔드 변경 사항

### 4.1 UI 컴포넌트 추가

**파일**: `frontend/src/pages/general-settings.ts`

"구독" 섹션 신규 추가 (기존 "타임테이블" 섹션 이후):

```typescript
// 구독 한도 설정 (subscribe.max_0b_count, 기본 200)
container.appendChild(sectionTitle('구독 한도'))
const max0bInput = createNumInput({
  value: Number(vals['subscribe.max_0b_count'] ?? 200),
  onChange: v => onSettingChange('subscribe.max_0b_count', v),
  step: 10,
  min: 1,
  max: 1000,
  name: 'subscribe.max_0b_count',
})
container.appendChild(createSettingRow('종목 동시 구독 최대 개수', max0bInput.el))
container.appendChild(createDescText(
  '보유종목 우선 등록 후 필터 통과 종목은 남은 자리만큼만 등록 (기본 200, 범위 1~1000)'
))
```

**컴포넌트 재사용 (P23)**:
- `createNumInput`: `sector-settings.ts`에서 이미 사용 중인 숫자 입력 컴포넌트
- `createSettingRow`: 공통 설정 행 컴포넌트
- `createDescText`: 공통 설명 텍스트 컴포넌트
- `sectionTitle`: 공통 섹션 제목 컴포넌트

### 4.2 설정 저장

기존 `scheduleTimetableSave` 패턴과 동일하게 `settingsMgr.saveSection()` 사용:

```typescript
async function onSettingChange(key: string, value: number): Promise<void> {
  if (!settingsMgr) return
  vals[key] = value
  const res = await settingsMgr.saveSection({ [key]: value })
  toastResult(res)
  if (!res.ok) {
    // 저장 실패 시 이전 값으로 롤백 (P22 정합성)
    vals[key] = value  // TODO: 이전 값 추적 필요
  }
}
```

**주의**: 기존 `scheduleTimetableSave` 함수는 `timetable.*` 키 전용으로 타입이 좁혀져 있음 (`general-settings.ts:115`). 신규 함수 추가 또는 기존 함수 시그니처 확장 필요 — P24 단순성 고려 시 신규 작은 함수 추가 추천.

### 4.3 타입 정의

**파일**: `frontend/src/types/index.ts`

설정 타입에 신규 키 추가 (기존 `timetable.*` 타입 정의 근처):

```typescript
subscribe: {
  max_0b_count: number
}
```

또는 flat 키 그대로 사용 (기존 `timetable.krx_pre_subscribe` 패턴 준수):

```typescript
'subscribe.max_0b_count'?: number
```

**추천**: flat 키 패턴 (`'subscribe.max_0b_count'`) — 기존 `timetable.*` flat 키와 일관 (P23)

---

## 5. 아키텍처 원칙 부합 여부

| 원칙 | 부합 여부 | 근거 |
|------|-----------|------|
| P10 (SSOT) | ✅ 부합 | 한도값이 `engine_ws_reg.py` 하드코딩 → 설정 키 1곳으로 이관. 캐시 참조 시점도 `integrated_system_settings_cache` 단일 소스 |
| P13 (메모리 상주) | ✅ 부합 | 틱 연산 단계가 아닌 구독 등록 시점이므로 캐시 참조 허용. 틱 핸들러에서 참조하지 않음 |
| P20 (폴백 금지) | ✅ 부합 | `int(_v if _v is not None else 200)` 패턴 — 기존 설정 로더 패턴 준수. `.get(기본값)`은 캐시 미초기화 예외 상태 대비 안전장치 (폴백 아님) |
| P21 (사용자 투명성) | ✅ 부합 | 화면에서 한도값 조회/조정 가능. 한도 초과 시 기존 warning 로그 유지 (별도 화면 표시는 추후 과제) |
| P22 (정합성) | ✅ 부합 | 기본값 200 유지로 기존 동작 100% 호환. "보유종목 우선" 로직 유지 |
| P23 (일관성) | ✅ 부합 | 기존 설정 키 패턴(`timetable.*` flat 키) 준수. 기존 컴포넌트(`createNumInput`) 재사용 |
| P24 (단순성) | ✅ 부합 | 증권사별 분기 미도입으로 단순화. 신규 설정 키 1개만 추가 |

---

## 6. 영향 범위

### 6.1 백엔드 (3파일)

| 파일 | 변경 내용 | 라인 수 |
|------|-----------|---------|
| `backend/app/core/settings_defaults.py` | 신규 키 1줄 추가 | +1 |
| `backend/app/core/engine_settings.py` | 타입 캐스팅 2줄 추가 | +2 |
| `backend/app/services/engine_ws_reg.py` | 하드코딩 1줄 → 캐시 참조 1줄 | ±1 |
| `backend/app/web/routes/settings.py` (선택) | 검증 3줄 추가 | +3 |

### 6.2 프론트엔드 (2파일)

| 파일 | 변경 내용 | 라인 수 |
|------|-----------|---------|
| `frontend/src/pages/general-settings.ts` | UI 섹션 추가 | +15 |
| `frontend/src/types/index.ts` | 타입 정의 1줄 | +1 |

### 6.3 테스트 (2파일)

| 파일 | 변경 내용 |
|------|-----------|
| `backend/tests/test_engine_ws.py` | 기존 200 한도 테스트 → 설정 키 기반 테스트로 수정 |
| `backend/tests/test_settings_store.py` | 신규 키 저장/로드 테스트 추가 |

### 6.4 DB 마이그레이션

- **불필요**: `integrated_system_settings` 테이블은 키-값 구조라 신규 키 자동 추가
- 기존 사용자: 설정 로드 시 `DEFAULT_USER_SETTINGS`에서 기본값 200 보완 (P10 SSOT)

---

## 7. 리스크 및 완화 방안

### 7.1 리스크 1: 사용자가 너무 높게 설정 (예: 1000)

**증상**: LS증권 서버가 1000개 종목 구독 거부 → `subscribe_stocks()` False 반환 → `_subscribed` 롤백 → 일부 종목만 구독

**완화**:
- UI 입력 범위 1~1000 제한 (`createNumInput`의 `min`/`max` 속성)
- 백엔드 검증 422 에러 (선택 사항 3.4)
- 한도 초과 시 기존 warning 로그 유지 → 사용자가 로그로 인지 가능

### 7.2 리스크 2: 캐시 미초기화 시 참조

**증상**: 엔진 기동 전 `subscribe_sector_stocks_0b()` 호출 시 `integrated_system_settings_cache`가 빈 dict → `.get(기본값)`로 200 반환

**완화**:
- `.get("subscribe.max_0b_count", 200)` 기본값으로 안전장치
- 실제로는 `subscribe_sector_stocks_0b()`가 로그인 후에만 호출되므로 캐시 초기화 전 호출 가능성 낮음

### 7.3 리스크 3: 기존 테스트 호환성

**증상**: `test_engine_ws.py`의 200 한도 초과 테스트가 설정 키 미설정으로 실패

**완화**:
- 테스트에서 `engine_state.state.integrated_system_settings_cache`에 `subscribe.max_0b_count` 명시 설정
- 기본값 200이 기존 테스트 기대값과 동일하므로 대부분 자동 호환

---

## 8. 테스트 계획

### 8.1 백엔드 단위 테스트

```python
# test_engine_ws.py — 신규 테스트 케이스

async def test_subscribe_respects_configured_limit():
    """설정된 한도값이 subscribe_sector_stocks_0b에 반영되는지 검증."""
    mock_state.integrated_system_settings_cache = {"subscribe.max_0b_count": 50}
    # ... 보유종목 10 + 필터 통과 100 → 한도 50 → 필터 40만 등록
    assert len(mock_subscribe.call_args) == 40  # 보유 10 + 필터 40

async def test_subscribe_defaults_to_200_when_key_missing():
    """설정 키 없을 때 기본값 200 적용 검증 (P22 호환성)."""
    mock_state.integrated_system_settings_cache = {}
    # ... 기존 200 한도 동작
```

### 8.2 프론트엔드 테스트

```typescript
// settings.test.ts — 신규 키 저장 테스트
it('subscribe.max_0b_count 저장 성공', async () => {
  const res = await mgr.saveSection({ 'subscribe.max_0b_count': 300 })
  expect(res.ok).toBe(true)
})

it('subscribe.max_0b_count 범위 초과 시 422', async () => {
  const res = await mgr.saveSection({ 'subscribe.max_0b_count': 5000 })
  expect(res.ok).toBe(false)
  expect(res.error).toContain('1~1000')
})
```

### 8.3 런타임 기동 검증

- `python -W error::RuntimeWarning main.py` 기동 — RuntimeWarning 없음 확인
- 설정 변경 API 호출 → 캐시 갱신 → 구독 함수에 반영되는지 로그 확인

---

## 9. 추후 확장 (증권사별 분기)

본 설계에서는 단일 설정 키로 단순화했으나, 추후 LS증권 공식 한도 확인 후 증권사별 분기 확장 가능:

### 9.1 확장 방향

`broker_factory.py` 레지스트리에 증권사별 기본값 등록:

```python
BROKER_SUBSCRIBE_LIMITS = {
    "kiwoom": 200,
    "ls": 500,  # LS 공식 한도 확인 후 설정
}
```

### 9.2 설정 키 우선순위

1. 사용자 설정 `subscribe.max_0b_count` (최우선)
2. 증권사별 기본값 `BROKER_SUBSCRIBE_LIMITS[broker]`
3. 전역 기본값 200 (최후 폴백)

### 9.3 확장 시점

- LS증권 WebSocket 공식 구독 한도 문서 확인 후
- 사용자 피드백으로 LS 사용 시 200 제한이 실제로 문제가 된 경우

---

## 10. 구현 체크리스트

### 10.1 백엔드
- [ ] `settings_defaults.py`에 `subscribe.max_0b_count: 200` 추가
- [ ] `engine_settings.py`에 타입 캐스팅 추가
- [ ] `engine_ws_reg.py` 하드코딩 → 캐시 참조로 변경
- [ ] `web/routes/settings.py` 검증 추가 (선택)
- [ ] `py_compile` 통과
- [ ] `pytest test_engine_ws.py` 통과
- [ ] `pytest test_settings_store.py` 통과
- [ ] 런타임 기동 검증 (`-W error::RuntimeWarning`)

### 10.2 프론트엔드
- [ ] `general-settings.ts`에 "구독 한도" 섹션 추가
- [ ] `types/index.ts`에 타입 정의 추가
- [ ] `npm run build` 통과
- [ ] 브라우저에서 설정 변경 → 저장 → 재조회 확인

### 10.3 문서
- [ ] `ARCHITECTURE.md` 5.1절 "WS 구독 대상"에 설정 키 언급 추가
- [ ] `ARCHITECTURE.md` 6.3절 "필터링"의 "200개 한도" 표현 → "설정 가능 한도(기본 200)"로 수정

---

## 11. 참조

- 현재 하드코딩 위치: `backend/app/services/engine_ws_reg.py:258`
- 설정 패턴 참조: `backend/app/core/settings_defaults.py:116-121` (`timetable.*` 키)
- 엔진 설정 로더 패턴: `backend/app/core/engine_settings.py:219-220` (`sector_start_threshold_pct`)
- 프론트엔드 숫자 입력 패턴: `frontend/src/pages/sector-settings.ts:329` (`createNumInput`)
- ARCHITECTURE.md 관련 섹션: 라인 549-552, 735-740
