# AI 문제해결 참고서 03 - UI/CSS/스크롤 문제 해결

## 목적

이 문서는 `SectorFlow` 프론트엔드에서 UI가 보이지 않거나, 아래쪽 UI가 잘리거나, 스크롤이 생기지 않는 문제를 해결하는 방법을 정리한다.

이번 매수설정/매도설정 문제에서 실제로 사용한 접근법을 일반화했다.

---

## 1. 대표 증상

다음 증상이 있으면 이 문서를 먼저 본다.

```text
UI가 코드에는 있는데 화면에 보이지 않음
페이지 일부만 보이고 아래쪽 설정이 잘림
마우스 휠을 내려도 내부 스크롤이 안 됨
다른 페이지는 보이는데 특정 페이지만 이상함
수정했는데 브라우저에는 예전 화면이 보임
```

---

## 2. 먼저 판단할 것

UI가 안 보인다고 바로 CSS를 고치면 안 된다.

먼저 다음을 분리한다.

```text
렌더링 문제인가?
데이터 전달 문제인가?
CSS 표시 문제인가?
스크롤 문제인가?
캐시 문제인가?
```

---

## 3. UI 코드 존재 확인

사용자가 말한 문구를 먼저 찾는다.

예:

```text
종목당 일일 최대 매수 금액
```

확인 대상:

```text
frontend/src/presentation/pages/**/**Page.tsx
```

판단:

- 문구가 없으면 UI 구현 누락
- 문구가 있으면 렌더링 이후 문제 가능성

---

## 4. props/data 연결 확인

UI가 존재한다면 값이 전달되는지 본다.

확인 대상:

```text
Container.tsx
Page.tsx
appStore.ts
```

확인 흐름:

```text
store 값 → Container props → Page component → input value
input onChange → handler → store update → rerender
```

예:

```text
maxDailyTotalBuyAmt
maxStockCnt
buyAmt
```

값이 전달되고 있으면 CSS/스크롤 문제 가능성이 높다.

---

## 5. CSS 클래스명 충돌 확인

CSS Modules를 쓰지 않는 일반 CSS import 구조에서는 클래스명이 전역이다.

다음 클래스명은 충돌 위험이 높다.

```css
.main-container
.left-panel
.left-panel-content
.right-panel
.right-panel-content
.setting-row
.setting-label
.input-small
.toggle-btn
.section-title
```

여러 페이지에서 같은 이름을 쓰면 import 순서나 번들 순서에 따라 예상하지 못한 스타일이 적용될 수 있다.

---

## 6. 클래스명 충돌 근본해결

전역 클래스명을 유지하면서 우선순위만 높이면 근본해결이 아니다.

올바른 해결은 페이지별 prefix 격리다.

매수설정 예:

```text
buy-settings-page
buy-settings-left-panel
buy-settings-left-panel-content
buy-settings-row
buy-settings-label
buy-settings-input-small
buy-settings-right-panel
```

매도설정 예:

```text
sell-settings-page
sell-settings-left-panel
sell-settings-left-panel-content
sell-settings-row
sell-settings-label
sell-settings-input-small
sell-settings-right-panel
```

다른 페이지도 같은 원칙을 따른다.

예:

```text
general-settings-*
profit-status-*
stock-classification-*
chart-page-*
```

---

## 7. flex 스크롤 체인 문제

flex 레이아웃에서는 `overflow-y: auto` 하나만으로 스크롤이 보장되지 않는다.

상위 flex item들이 줄어들 수 있어야 한다.

핵심은 `min-height: 0`이다.

---

## 8. 올바른 스크롤 구조

설정 페이지처럼 좌측 패널이 스크롤되어야 하는 구조는 다음과 같다.

```css
.page-root {
  display: flex;
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

.right-panel-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
```

---

## 9. 이번 작업의 실제 정답 구조

매수설정 파일:

```text
frontend/src/presentation/pages/buy-settings/BuySettingsPage.tsx
frontend/src/presentation/pages/buy-settings/BuySettingsPage.css
```

매도설정 파일:

```text
frontend/src/presentation/pages/sell-settings/SellSettingsPage.tsx
frontend/src/presentation/pages/sell-settings/SellSettingsPage.css
```

적용 내용:

```text
전역 클래스명 제거
페이지별 prefix 클래스 적용
좌측 콘텐츠 영역에 overflow-y: auto 적용
flex parent에 min-height: 0 적용
빌드 성공 확인
```

---

## 10. 서비스워커/캐시 문제

코드가 맞는데 브라우저가 예전 화면을 보여주면 service worker를 의심한다.

확인 대상:

```text
frontend/public/service-worker.js
frontend/src/main.tsx
```

개발환경에서는 오래된 bundle이 cache first 전략으로 제공될 수 있다.

해결 방향:

- 개발환경에서 service worker 등록 방지
- 기존 service worker unregister
- caches 삭제
- 사용자는 `Command + Shift + R` 강력 새로고침

---

## 11. 검증 검색 방법

복잡한 정규식 대신 고정 문자열 검색을 나눠서 한다.

TSX 잔여 확인:

```text
className="setting
className="input-small"
className={`toggle-btn
```

CSS 잔여 확인:

```text
.main-container
.setting-row
.input-small
.right-panel
```

기대 결과:

```text
No results found
```

단, prefix가 붙은 정상 클래스는 문제 아님.

예:

```text
buy-settings-right-panel
sell-settings-right-panel
```

---

## 12. 빌드 검증

프론트엔드 디렉터리에서 실행한다.

```bash
npm run build
```

성공 기준:

```text
✓ built
```

chunk size warning은 UI 표시 문제와 직접 관련 없는 번들 크기 경고일 수 있다.

---

## 13. 사용자용 화면 확인 방법

초보 사용자에게는 다음처럼 안내한다.

매수설정 확인:

```text
1. 앱에서 매수설정 메뉴를 클릭한다.
2. 왼쪽 설정 영역 위에 마우스를 올린다.
3. 마우스 휠 또는 트랙패드로 아래로 내린다.
4. 매수 한도 섹션이 보이는지 확인한다.
5. 종목당 일일 최대 매수 금액이 보이면 성공이다.
```

매도설정 확인:

```text
1. 앱에서 매도설정 메뉴를 클릭한다.
2. 왼쪽 설정 영역을 아래로 스크롤한다.
3. 익절/손절, 추적 매도 항목이 잘리지 않고 보이는지 확인한다.
```

화면이 이상하면:

```text
Command + Shift + R
```

로 강력 새로고침한다.

---

## 14. 피해야 할 해결책

다음은 근본해결이 아니다.

```text
!important 추가
height: 100vh를 여러 곳에 무작정 추가
z-index만 올림
전역 CSS에 임시 override 추가
가상 스크롤 도입
브라우저 새로고침만 안내
```

가상 스크롤은 데이터 행이 수천 개 이상일 때 성능을 위한 선택이지, 설정 UI가 잘리는 문제의 해결책이 아니다.

---

## 15. 결론

UI 표시/스크롤 문제의 표준 해결 순서는 다음이다.

```text
1. UI 코드 존재 확인
2. props/state 연결 확인
3. CSS 가림 여부 확인
4. 전역 클래스 충돌 확인
5. 페이지별 prefix로 격리
6. flex scroll chain 수정
7. 캐시/서비스워커 확인
8. 검색 검증
9. 빌드 검증
10. 브라우저 확인
```

이 순서를 지키면 유사한 UI 문제를 안정적으로 해결할 수 있다.
