# SectorFlow 아키텍처 최적화 인계서

**작업 날짜:** 2026-05-13  
**작업 목표:** Trading App Architecture Optimization - Priority 1 완료, Priority 2 완료

---

## 완료된 작업 (Priority 1)

### Task 2.4: Settings Manager Pattern (SSOT)
**목적:** Python GC 최적화를 위한 싱글톤 Settings Manager 적용

**수정된 파일:**
1. **`/frontend/src/settings.ts`**
   - 전역 싱글톤 `globalSettingsManager` 추가 (line 105)
   - `export const globalSettingsManager = createSettingsManager(appStore)`

2. **`/frontend/src/pages/buy-target.ts`**
   - import: `globalSettingsManager` 추가
   - `updateBadges()` 함수에서 `appStore.getState().settings` → `globalSettingsManager.getSettings()` 변경
   - store 구독에서 settings 참조 변경
   - wsBadge 타입 변경 (`HTMLElement`)

3. **`/frontend/src/pages/sell-position.ts`**
   - import: `globalSettingsManager`, `createGlobalWsBadge` 추가
   - mount 함수에서 settings 접근 변경
   - wsBadge 전역 배지 적용

4. **`/frontend/src/pages/profit-overview.ts`**
   - import: `globalSettingsManager`, `createGlobalWsBadge` 추가
   - `renderAccountVals()` 함수에서 settings 접근 변경
   - mount 함수에서 settings 접근 변경
   - onDateRangeChange 콜백에서 settings 접근 변경
   - store 구독에서 settings 참조 변경
   - rAF 콜백에서 settings 접근 변경 및 wsBadge.update 제거

### Task 2.3: WebSocket Status Badge (Single Subscription)
**목적:** 단일 store subscriber를 사용하는 전역 WS 배지 모듈

**수정된 파일:**
1. **`/frontend/src/settings.ts`**
   - 전역 WS 배지 모듈 추가 (line 108-147)
   - `createGlobalWsBadge()`: 단일 subscriber 유지, 싱글톤 패턴
   - `destroyGlobalWsBadge()`: subscriber 정리

2. **`/frontend/src/pages/general-settings.ts`**
   - import: `createGlobalWsBadge` 추가
   - 모듈 상태: `wsBadge: HTMLElement` 추가
   - `renderTabBar()` 함수: 탭 바 오른쪽에 WS 배지 추가
   - unmount 함수: wsBadge 정리

3. **`/frontend/src/pages/buy-settings.ts`**
   - import: `createGlobalWsBadge` 추가
   - 모듈 상태: `wsBadge: HTMLElement` 추가
   - mount 함수: 헤더 행에 WS 배지 추가
   - unmount 함수: wsBadge 정리

4. **`/frontend/src/pages/sell-settings.ts`**
   - import: `createGlobalWsBadge` 추가
   - 모듈 상태: `wsBadge: HTMLElement` 추가
   - mount 함수: 헤더 행에 WS 배지 추가
   - unmount 함수: wsBadge 정리

---

## 완료된 작업 (Priority 2)

### Task 2.1: rAF Coalescing
**목적:** `sector-analysis.ts`에 requestAnimationFrame 코일레싱 패턴 적용

**수정된 파일:**
1. **`/frontend/src/pages/sector-analysis.ts`**
   - 모듈 변수 추가 (line 79-80):
     - `rafHandle: number | null = null`
     - `_mounted = false`
   - mount 함수 (line 337):
     - `_mounted = true` 추가
   - appStore subscribe 콜백 (line 539-549):
     - rAF coalescing 패턴 적용
     - `if (rafHandle !== null) return`으로 중복 예약 방지
     - rAF 콜백 내에서 최신 상태 가져오기
   - unmount 함수 (line 562, 564):
     - `_mounted = false` 추가
     - rAF 취소 로직 추가

### Task 2.2: Page Activity Notifications
**목적:** 페이지 활성/비활성 알림 추가

**수정된 파일:**
1. **`/frontend/src/pages/sector-analysis.ts`**
   - import 추가 (line 6): `import { notifyPageActive, notifyPageInactive } from '../api/ws'`
   - mount 함수 (line 338): `notifyPageActive('sector-analysis')` 추가
   - unmount 함수 (line 563): `notifyPageInactive('sector-analysis')` 추가

2. **`/frontend/src/pages/buy-settings.ts`**
   - import 추가 (line 7): `import { notifyPageActive, notifyPageInactive } from '../api/ws'`
   - mount 함수 (line 147): `notifyPageActive('buy-settings')` 추가
   - unmount 함수 (line 420): `notifyPageInactive('buy-settings')` 추가

---

## 아키텍처 원칙

### Python-Centric Resource Efficiency
- **싱글톤 패턴:** 모듈 레벨 사전 인스턴스화로 객체 생성/소멸 최소화
- **단일 Subscription:** 전역 상태 배지는 단일 subscriber만 유지
- **GC 최적화:** 불필요한 객체 생성 방지, 참조 재사용

### Single-Source-Of-Truth (SSOT)
- **Settings Manager:** 전역 싱글톤으로 중앙화된 설정 관리
- **WS Badge:** 전역 싱글톤으로 단일 상태 소스

---

## 수정된 파일 목록

**Priority 1:**
1. `/frontend/src/settings.ts` - globalSettingsManager, createGlobalWsBadge 추가
2. `/frontend/src/pages/buy-target.ts` - globalSettingsManager, createGlobalWsBadge 적용
3. `/frontend/src/pages/sell-position.ts` - globalSettingsManager, createGlobalWsBadge 적용
4. `/frontend/src/pages/profit-overview.ts` - globalSettingsManager, createGlobalWsBadge 적용
5. `/frontend/src/pages/general-settings.ts` - createGlobalWsBadge 적용
6. `/frontend/src/pages/buy-settings.ts` - createGlobalWsBadge 적용
7. `/frontend/src/pages/sell-settings.ts` - createGlobalWsBadge 적용

**Priority 2:**
8. `/frontend/src/pages/sector-analysis.ts` - rAF 코일레싱 패턴 적용, 페이지 활성/비활성 알림 추가
9. `/frontend/src/pages/buy-settings.ts` - 페이지 활성/비활성 알림 추가

---

## 참고 사항

- general-settings.ts는 이미 createSettingsManager를 사용하므로 globalSettingsManager로 변경하지 않음
- 전역 WS 배지는 createGlobalWsBadge()를 호출하여 DOM에 추가만 하면 됨 (자동 업데이트됨)
- unmount 시에는 wsBadge 참조만 null로 설정하면 됨 (전역 subscriber는 settings.ts에서 관리)
- notifyPageInactive 함수는 page 인자가 필요함 (`notifyPageInactive('page-name')`)

---

## 수정 과정에서 발생한 오류

### 해결된 오류
- **notifyPageInactive 인자 누락**: 초기 구현 시 `notifyPageInactive()`로 호출하여 TS2554 오류 발생. `notifyPageInactive('page-name')`으로 수정하여 해결.
- **기존 빌드 오류 6건**: 본 세션에서 모두 해결 완료
  1. `general-settings.ts` export default 누락 → `export default { mount, unmount }` 추가
  2. `buy-target.ts` initState 미정의 → mount 함수 시작에 `const initState = appStore.getState()` 추가
  3. `profit-overview.ts` unused state 변수 (2곳) → 불필요한 변수 제거
  4. `sell-position.ts` unused isTestMode 변수 → 불필요한 변수 제거
  5. `settings.ts` 타입 비교 오류 → `state.wsSubscribeStatus?.quote_subscribed ?? false`로 수정
  6. `sell-position.ts` 중복 import → 중복된 `globalSettingsManager, createGlobalWsBadge` import 제거

---

## 작업 상태

- **Priority 1**: 완료
- **Priority 2**: 완료
- **기존 빌드 오류 수정**: 완료
- **빌드 상태**: 성공 (Exit code: 0)
- **다음 세션**: 새로운 작업 진행 가능
