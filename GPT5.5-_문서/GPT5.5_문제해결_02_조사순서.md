# AI 문제해결 참고서 02 - 조사/분석 표준순서

## 목적

이 문서는 문제 유형과 무관하게 하위 AI가 먼저 따라야 할 공통 조사 순서를 정의한다.

핵심은 다음이다.

```text
현상 확인 → 진입점 확인 → 데이터 흐름 확인 → 원인 후보 분리 → 최소 수정 → 검증
```

---

## 1단계: 사용자의 요청 유형 분류

먼저 사용자가 원하는 것이 무엇인지 구분한다.

### 보고만 원하는 경우

예:

```text
원인을 분석해서 보고하라
왜 그런지 확인해라
수정은 승인 후에 하라
```

행동:

- 파일 조사 가능
- 명령 실행은 읽기/검증 중심
- 코드 수정 금지
- 원인과 해결책 보고 후 대기

### 수정까지 원하는 경우

예:

```text
진행해
수정해
근본해결책으로 해결해라
```

행동:

- 조사 후 수정 가능
- 작은 단위로 진행
- 수정 후 검증 필수

---

## 2단계: 재현 범위 확인

문제가 어디에서 발생하는지 좁힌다.

확인 항목:

- 특정 페이지만 문제인가
- 전체 앱 문제인가
- 개발 서버에서만 문제인가
- 빌드 결과에서도 문제인가
- 새로고침 후에도 문제인가
- 특정 브라우저 캐시 문제인가

예:

```text
sector-ranking은 보이는데 buy-settings만 안 보임
```

이 경우 전체 앱 문제보다 해당 페이지 CSS/route/rendering 문제 가능성이 높다.

---

## 3단계: 진입점 확인

프론트엔드에서 먼저 볼 파일:

```text
frontend/src/main.tsx
frontend/src/presentation/components/layout/MainLayout.tsx
```

확인 항목:

- route가 등록되어 있는가
- 현재 URL hash와 route가 일치하는가
- container component가 렌더링되는가
- MainLayout이 children을 표시하는가
- layoutType 같은 설정이 실제로 전달/사용되는가

---

## 4단계: 페이지 컴포넌트 확인

확인 대상 예:

```text
frontend/src/presentation/pages/buy-settings/BuySettingsPage.tsx
frontend/src/presentation/pages/sell-settings/SellSettingsPage.tsx
```

확인 항목:

- 사용자가 말한 UI 문구가 JSX에 존재하는가
- 조건부 렌더링으로 숨겨져 있지 않은가
- className이 CSS와 일치하는가
- ref/web component 연결이 정상인가

판단:

- JSX에 없으면 구현 누락
- JSX에 있으면 CSS/스크롤/데이터/캐시 문제 가능성

---

## 5단계: Container와 State 확인

확인 대상 예:

```text
BuySettingsContainer.tsx
SellSettingsContainer.tsx
appStore.ts
```

확인 항목:

- store에서 값을 읽는가
- page component에 props로 전달하는가
- onChange handler가 store를 업데이트하는가
- 값 타입이 맞는가
- undefined가 들어갈 가능성이 있는가

데이터 흐름 예:

```text
appStore.settings → Container → Page props → Input value
Input onChange → Container handler → appStore.setState → Page rerender
```

이 흐름 중 끊긴 곳을 찾는다.

---

## 6단계: CSS와 레이아웃 확인

확인 대상:

```text
page css
global.css
layout component style
다른 페이지 css
```

확인 항목:

- 전역 클래스명 충돌 여부
- `display: none`
- `visibility: hidden`
- `opacity: 0`
- `height: 0`
- `overflow: hidden`
- flex parent의 `min-height: 0` 누락
- z-index 문제

CSS가 전역이면 페이지별 prefix를 우선 고려한다.

---

## 7단계: 캐시/서비스워커 확인

코드는 맞는데 화면이 예전이면 캐시를 확인한다.

확인 대상:

```text
frontend/public/service-worker.js
frontend/src/main.tsx
```

확인 항목:

- 개발환경에서 service worker가 등록되는가
- cache first 전략이 있는가
- 오래된 bundle이 제공될 수 있는가

사용자 확인:

```text
Command + Shift + R
```

---

## 8단계: 원인 후보 분리

원인을 섞지 말고 분리한다.

예:

```text
원인 A: UI 코드 자체는 존재함
원인 B: props도 전달됨
원인 C: CSS 클래스 충돌 가능성 있음
원인 D: 스크롤 체인 불완전
```

이렇게 분리하면 수정 범위가 명확해진다.

---

## 9단계: 수정 전략 선택

수정은 원인별로 한다.

- CSS 충돌 → 클래스명 격리
- 스크롤 문제 → flex scroll chain 수정
- 데이터 미전달 → container props 연결
- state 미반영 → store update 경로 수정
- 캐시 문제 → dev service worker 비활성/캐시 정리
- 타입 문제 → 타입 정의와 호출부 정합성 수정

증상만 덮는 수정은 피한다.

---

## 10단계: 검증

수정 후 검증 순서:

1. 수정한 문자열이 남아 있는지 검색
2. TypeScript/build 실행
3. 브라우저 화면 확인
4. 사용자가 쉽게 확인할 수 있는 절차 안내

프론트엔드 기본 빌드:

```bash
npm run build
```

---

## 11단계: 보고

보고에는 다음이 있어야 한다.

- 원인
- 수정 파일
- 수정 내용
- 검증 결과
- 남은 확인 사항

나쁜 보고:

```text
고쳤습니다.
```

좋은 보고:

```text
CSS 전역 클래스 충돌을 페이지별 prefix로 제거했습니다.
flex scroll chain에 min-height: 0과 overflow-y: auto를 적용했습니다.
잔여 전역 클래스 검색 결과 없음, npm run build 성공입니다.
브라우저에서 해당 페이지 좌측 패널 스크롤을 확인하면 됩니다.
```
