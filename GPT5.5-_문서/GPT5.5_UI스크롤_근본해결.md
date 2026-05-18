# Cascade UI스크롤 근본해결

## 목적

이 문서는 `SectorFlow` 프로젝트에서 매수설정/매도설정 UI가 보이지 않거나, 화면 아래쪽 UI가 잘려 보이거나, 스크롤이 생기지 않는 문제를 하위 AI 또는 후속 작업자가 반복 삽질 없이 해결하도록 하기 위한 참고서다.

핵심 원칙은 다음과 같다.

- 추측하지 말고 코드 기반으로 조사한다.
- 증상 완화가 아니라 근본 원인을 제거한다.
- UI 문제는 `렌더링 여부`, `CSS 적용 여부`, `레이아웃/스크롤 체인`, `캐시/서비스워커` 순서로 확인한다.
- 수정 후 반드시 검색 검증과 빌드 검증을 한다.

---

## 이번에 실제로 해결한 문제 요약

### 문제 1: UI 요소가 보이지 않음

초기에는 매수설정 UI가 구현되어 있음에도 브라우저에서 보이지 않는 문제가 있었다.

실제 원인은 단일 원인이 아니라 복합 원인이었다.

- 개발환경에서 Service Worker가 이전 번들을 캐시해 오래된 화면을 보여줌
- `main.tsx`에서 body 스타일을 직접 지정해 다크 테마와 충돌 가능성이 있었음
- 이후에는 UI는 존재하지만 아래쪽 항목이 스크롤되지 않아 보이지 않는 문제가 남음

### 문제 2: 아래쪽 설정 항목이 스크롤로 보이지 않음

대표 항목:

```text
종목당 일일 최대 매수 금액
```

코드상 `BuySettingsPage.tsx`에는 해당 UI가 존재했다. 그러나 화면에서는 보이지 않는다고 보고되었다.

근본 원인은 다음 두 가지였다.

1. 페이지 간 CSS 클래스명 충돌
2. flex 컨테이너의 스크롤 체인 불완전

---

## 근본 원인 1: CSS 클래스명 충돌

### 문제 구조

여러 페이지가 같은 전역 CSS 클래스명을 사용하고 있었다.

예:

```css
.main-container
.left-panel
.left-panel-content
.setting-row
.setting-label
.input-small
.right-panel
.right-panel-content
```

이런 클래스명은 특정 페이지의 CSS가 다른 페이지 UI에 영향을 줄 수 있다.

특히 `sector-ranking`, `buy-settings`, `sell-settings` 같은 서로 다른 화면이 같은 `.main-container`를 쓰면, import 순서와 CSS 번들 순서에 따라 의도하지 않은 스타일이 적용될 수 있다.

### 해결 원칙

페이지별 prefix를 붙여 격리한다.

매수설정:

```text
buy-settings-page
buy-settings-left-panel
buy-settings-left-panel-content
buy-settings-row
buy-settings-label
buy-settings-input-small
buy-settings-right-panel
```

매도설정:

```text
sell-settings-page
sell-settings-left-panel
sell-settings-left-panel-content
sell-settings-row
sell-settings-label
sell-settings-input-small
sell-settings-right-panel
```

### 왜 이것이 근본해결책인가

전역 클래스명을 유지한 채 CSS 우선순위만 올리거나 `!important`를 쓰면 증상 완화일 뿐이다.

페이지별 prefix로 격리하면 CSS 충돌 경로 자체가 사라진다.

---

## 근본 원인 2: flex 스크롤 체인 불완전

### 문제 구조

상위 레이아웃이 `overflow: hidden`인 상태에서 내부 패널이 스크롤을 담당해야 한다.

이때 flex 자식 요소에 `min-height: 0`이 없으면, 브라우저는 자식의 최소 높이를 콘텐츠 높이로 계산할 수 있다.

결과적으로 `overflow-y: auto`가 있어도 실제 스크롤 영역이 만들어지지 않고 내용이 잘릴 수 있다.

### 올바른 구조

좌측 설정 패널이 스크롤되어야 하는 경우 다음 체인이 필요하다.

```css
.page-root {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.left-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.left-panel-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.right-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
```

### 왜 이것이 근본해결책인가

단순히 `height: 100vh`를 여기저기 추가하거나, `overflow-y: scroll`만 넣는 것은 증상 완화다.

flex 레이아웃에서는 스크롤을 담당하는 요소까지 모든 부모 체인이 줄어들 수 있어야 하므로 `min-height: 0`이 핵심이다.

---

## UI 표시 문제 조사 순서

아래 순서를 지키면 불필요한 삽질을 줄일 수 있다.

---

### 1단계: 실제 UI 코드가 존재하는지 확인

먼저 화면에 없는 UI가 코드에 존재하는지 확인한다.

예:

```text
종목당 일일 최대 매수 금액
```

확인 대상:

```text
frontend/src/presentation/pages/buy-settings/BuySettingsPage.tsx
frontend/src/presentation/pages/sell-settings/SellSettingsPage.tsx
```

확인 방법:

- 해당 라벨 문자열 검색
- 해당 props가 컴포넌트로 전달되는지 확인
- 입력 컴포넌트가 실제 JSX에 렌더링되는지 확인

판단 기준:

- 코드에 없으면 구현 누락
- 코드에 있으면 렌더링/스타일/스크롤/캐시 문제로 좁힌다

---

### 2단계: 데이터 props 연결 확인

UI가 코드에 있다면 컨테이너에서 값과 핸들러가 전달되는지 확인한다.

확인 대상 예:

```text
frontend/src/presentation/pages/buy-settings/BuySettingsContainer.tsx
frontend/src/presentation/pages/sell-settings/SellSettingsContainer.tsx
```

확인 항목:

- `settings` 객체에 해당 값이 있는가
- presentational component에 prop으로 전달되는가
- onChange handler가 연결되어 있는가

예:

```text
maxDailyTotalBuyAmt
maxStockCnt
buyAmt
```

판단 기준:

- props 전달이 안 되면 데이터 연결 문제
- props 전달이 되면 스타일/스크롤 문제 가능성이 높다

---

### 3단계: 실제 DOM을 가리는 CSS 여부 확인

다음 속성이 있는지 확인한다.

```css
display: none;
visibility: hidden;
opacity: 0;
height: 0;
overflow: hidden;
position: absolute;
z-index;
```

주의할 점:

`overflow: hidden` 자체는 나쁜 속성이 아니다. 상위 레이아웃에서는 필요할 수 있다. 문제는 스크롤을 담당해야 하는 하위 요소에 `overflow-y: auto`와 `min-height: 0` 체인이 없을 때 발생한다.

---

### 4단계: CSS 클래스명 충돌 확인

아래처럼 너무 일반적인 클래스명이 페이지별 CSS에서 반복 사용되는지 확인한다.

```text
.main-container
.left-panel
.right-panel
.setting-row
.input-small
```

확인 대상:

```text
frontend/src/presentation/pages/**/**.css
frontend/src/presentation/pages/**/**.tsx
```

문제 판단:

- 서로 다른 페이지에서 같은 클래스명을 쓰면 충돌 가능성이 있다.
- 특히 Vite/React 앱에서는 CSS가 전역으로 번들링되므로 CSS Modules를 쓰지 않는 한 클래스명은 전역이다.

해결:

- 페이지별 prefix로 격리한다.
- `buy-settings-*`, `sell-settings-*`처럼 명확히 구분한다.

---

### 5단계: flex 스크롤 체인 확인

설정 페이지처럼 좌측 패널만 세로 스크롤되어야 하는 화면은 다음을 확인한다.

페이지 루트:

```css
flex: 1;
min-width: 0;
min-height: 0;
overflow: hidden;
```

좌측 패널:

```css
display: flex;
flex-direction: column;
min-height: 0;
overflow: hidden;
```

좌측 패널 콘텐츠:

```css
flex: 1;
min-height: 0;
overflow-y: auto;
```

우측 패널:

```css
flex: 1;
min-width: 0;
min-height: 0;
overflow: hidden;
```

---

### 6단계: 캐시/서비스워커 확인

코드를 고쳤는데 브라우저 화면이 그대로면 서비스워커 캐시를 의심한다.

확인 대상:

```text
frontend/public/service-worker.js
frontend/src/main.tsx
```

개발환경에서는 서비스워커가 오래된 번들을 보여줄 수 있다.

해결 원칙:

- 개발환경에서는 서비스워커 등록을 막는다.
- 기존 등록된 서비스워커와 캐시를 정리한다.
- 사용자는 필요 시 `Command + Shift + R`로 강력 새로고침한다.

---

## 실제 수정 절차

### 매수설정 수정 절차

대상 파일:

```text
frontend/src/presentation/pages/buy-settings/BuySettingsPage.tsx
frontend/src/presentation/pages/buy-settings/BuySettingsPage.css
```

수정 방향:

- `main-container` → `buy-settings-page`
- `left-panel` → `buy-settings-left-panel`
- `left-panel-content` → `buy-settings-left-panel-content`
- `settings-page-title` → `buy-settings-page-title`
- `settings-card` → `buy-settings-card`
- `setting-row` → `buy-settings-row`
- `setting-label` → `buy-settings-label`
- `setting-label-with-toggle` → `buy-settings-label-with-toggle`
- `toggle-btn` → `buy-settings-toggle-btn`
- `input-small` → `buy-settings-input-small`
- `setting-section` → `buy-settings-section`
- `section-title` → `buy-settings-section-title`
- `right-panel` → `buy-settings-right-panel`
- `right-panel-header` → `buy-settings-right-panel-header`
- `right-panel-header-title` → `buy-settings-right-panel-header-title`
- `right-panel-header-subtitle` → `buy-settings-right-panel-header-subtitle`
- `right-panel-content` → `buy-settings-right-panel-content`

CSS에는 flex scroll chain을 추가한다.

핵심:

```css
.buy-settings-page {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.buy-settings-left-panel {
  min-height: 0;
  overflow: hidden;
}

.buy-settings-left-panel-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
```

---

### 매도설정 수정 절차

대상 파일:

```text
frontend/src/presentation/pages/sell-settings/SellSettingsPage.tsx
frontend/src/presentation/pages/sell-settings/SellSettingsPage.css
```

수정 방향:

- `main-container` → `sell-settings-page`
- `left-panel` → `sell-settings-left-panel`
- `left-panel-content` → `sell-settings-left-panel-content`
- `settings-page-title` → `sell-settings-page-title`
- `settings-card` → `sell-settings-card`
- `setting-row` → `sell-settings-row`
- `setting-label` → `sell-settings-label`
- `toggle-btn` → `sell-settings-toggle-btn`
- `input-small` → `sell-settings-input-small`
- `fixed-value` → `sell-settings-fixed-value`
- `setting-section` → `sell-settings-section`
- `section-title` → `sell-settings-section-title`
- `right-panel` → `sell-settings-right-panel`
- `right-panel-header` → `sell-settings-right-panel-header`
- `right-panel-header-title` → `sell-settings-right-panel-header-title`
- `right-panel-header-subtitle` → `sell-settings-right-panel-header-subtitle`
- `right-panel-content` → `sell-settings-right-panel-content`

CSS에는 매수설정과 동일한 flex scroll chain을 적용한다.

---

## 작업 시 주의사항

### 1. 긴 자동 치환 명령을 피한다

이번 작업 중 긴 `python3` 치환 명령은 사용자에게 진행상황이 보이지 않아 불안감을 만들었다.

하위 AI는 다음 원칙을 지킨다.

- 작은 범위의 `apply_patch` 사용
- 패치 후 즉시 검색 검증
- 한 번에 여러 파일을 크게 바꾸지 않기
- 진행상황을 짧게 보고하기

### 2. 정규식 검색에서 특수문자 주의

`grep_search`에서 `{`, `(`, `.` 같은 문자를 포함한 검색은 정규식 오류가 날 수 있다.

안전한 방법:

- 정확한 문자열 검색은 `FixedStrings: true` 사용
- 복잡한 OR 정규식보다 작은 검색 여러 개 사용

예:

```text
className="setting
className="input-small"
.main-container
.setting-row
```

각각 따로 검색한다.

### 3. `!important` 사용 금지

CSS 충돌을 `!important`로 덮는 것은 근본해결책이 아니다.

반드시 클래스명 격리로 해결한다.

### 4. 임의의 UI 구조 변경 금지

이번 문제는 표시/스크롤 문제다.

따라서 다음은 별도 승인 없이 하지 않는다.

- UI 항목 추가/삭제
- 레거시 UI 밀도 조정
- 가상 스크롤 도입
- 디자인 변경

---

## 검증 절차

### 1. TSX 전역 클래스 잔여 확인

매수설정:

```text
frontend/src/presentation/pages/buy-settings
```

검색:

```text
className="setting
className="input-small"
className={`toggle-btn
```

매도설정:

```text
frontend/src/presentation/pages/sell-settings
```

검색:

```text
className="setting
className="input-small"
className={`toggle-btn
```

기대 결과:

```text
No results found
```

### 2. CSS 전역 selector 잔여 확인

검색:

```text
.main-container
.setting-row
.input-small
.right-panel
```

주의:

`buy-settings-right-panel` 같은 문자열은 `.right-panel`이 아니라 prefix가 붙은 정상 클래스다. 검색은 고정 문자열로 정확히 확인한다.

기대 결과:

```text
No results found
```

### 3. 빌드 검증

위치:

```text
frontend
```

명령:

```bash
npm run build
```

기대 결과:

```text
✓ built
```

chunk size warning은 이번 UI 표시/스크롤 문제와 직접 관련 없는 번들 크기 경고다.

### 4. 브라우저 확인

사용자 확인 항목:

- 매수설정 페이지 진입
- 좌측 설정 영역에서 마우스 휠 또는 트랙패드 스크롤
- 아래쪽 `매수 한도` 섹션 확인
- `종목당 일일 최대 매수 금액` 표시 확인
- 매도설정 페이지에서도 좌측 설정 영역 스크롤 확인

브라우저가 오래된 화면을 보여주면:

```text
Command + Shift + R
```

로 강력 새로고침한다.

---

## 하위 AI용 문제 해결 체크리스트

작업 전:

- [ ] 사용자가 보고만 원하는지, 수정까지 승인했는지 확인
- [ ] 문제 UI가 코드에 존재하는지 확인
- [ ] props 연결이 되어 있는지 확인
- [ ] CSS 전역 클래스 충돌 여부 확인
- [ ] flex scroll chain 확인
- [ ] 서비스워커/캐시 가능성 확인

수정 중:

- [ ] 한 번에 큰 자동 치환 금지
- [ ] 파일 하나 또는 작은 블록 단위로 수정
- [ ] 페이지별 prefix 사용
- [ ] `min-height: 0` 누락 방지
- [ ] `overflow-y: auto`는 실제 스크롤 담당 요소에만 적용

수정 후:

- [ ] 잔여 전역 클래스 검색
- [ ] 빌드 실행
- [ ] 브라우저 강력 새로고침 안내
- [ ] 사용자가 확인할 화면 항목을 쉽게 설명

---

## 결론

이번 문제의 근본해결책은 다음 두 가지다.

```text
1. 페이지별 CSS 클래스명 격리
2. flex 스크롤 체인 정상화
```

이 두 가지를 적용하면 특정 페이지 CSS가 다른 페이지에 영향을 주는 문제와, 긴 설정 UI가 잘리는 문제를 함께 해결할 수 있다.

향후 유사한 UI 표시 문제는 이 문서의 조사 순서대로 확인하면 된다.
