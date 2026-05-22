# 웹소켓 active_page 덮어쓰기 버그 수정 계획서

보유종목 테이블의 실시간 현재가 미갱신 현상과 앱 재기동 시 실시간 데이터 미표시 현상에 대한 원인 분석 및 단계별 수정 과정 안내입니다.

## 원인 분석 (Root Cause)

### 1. 보유종목/매수후보 현재가 실시간 미갱신 버그

**구조:** `#/sell-settings` (매도설정) 및 `#/buy-settings` (매수설정) 경로는 왼쪽 패널에 설정 카드(sell-settings.ts, buy-settings.ts), 오른쪽 패널에 목록 테이블(sell-position.ts, buy-target.ts)을 배치하는 듀얼 레이아웃(dual layout) 구조입니다.

**버그 흐름:**
- 사용자가 매도설정 페이지에 진입하면 라우터에 의해 두 모듈이 차례대로 마운트됩니다.
- sell-position.ts가 마운트되면서 `notifyPageActive('sell-position')`을 호출합니다.
- 직후 sell-settings.ts가 마운트되면서 `notifyPageActive('sell-settings')`를 호출합니다.
- 프론트엔드 앱은 단 하나의 웹소켓 채널(wsClient)을 공유하므로, 마지막에 호출된 `notifyPageActive('sell-settings')`가 웹소켓 세션의 active_page 값을 'sell-settings'로 덮어씁니다.
- 백엔드(ws_manager.py)는 세션의 active_page가 'sell-settings'이면 "실시간 데이터 미전송 대상 페이지"로 판단하여 실시간 체결 데이터를 전혀 보내지 않습니다. (sell_position_active도 False가 되어 계좌 정보 갱신에서도 누락됩니다.)
- 매수설정 페이지도 동일: buy-target.ts가 'buy-target'을 활성화한 직후, buy-settings.ts가 'buy-settings'로 덮어쓰면서 매수후보 테이블의 실시간 업데이트가 멈추는 동일한 현상이 발생했습니다.

**해결책:** 설정 카드 모듈(sell-settings.ts, buy-settings.ts)은 독자적으로 실시간 시세를 구독할 필요가 없으므로, 해당 파일들에서 `notifyPageActive` 및 `notifyPageInactive` 호출을 제거합니다. 이를 통해 웹소켓의 active_page가 메인 테이블 모듈이 지정한 'sell-position'과 'buy-target'으로 온전히 유지되도록 합니다.

### 2. 앱 재기동 후 실시간 데이터 미표시 (연결해제) 현상

현재 로컬 환경을 점검한 결과, 백엔드 서버(포트 8000)와 프론트엔드 개발 서버(포트 5173)가 모두 실행 중이지 않은 상태(종료 상태)입니다.

브라우저에 남아 있는 이전 캐시 화면 혹은 빈 페이지가 열려 있으나 백엔드 서버가 종료되어 있어 화면 우측 상단과 사이드바에 연결해제 (Disconnected) 상태 배지가 표시되고 실시간 현재가가 모두 0으로 나오는 것입니다.

**해결책:** 프로젝트 루트 폴더에 있는 SectorFlow.command 스크립트를 다시 실행(더블 클릭 등)하면 백엔드와 프론트엔드가 정상 기동하며 웹소켓이 자동으로 다시 연결(Connected)되고 실시간 데이터가 표시됩니다.

## Proposed Changes

### 1. 매도설정 카드 모듈에서 웹소켓 활성화 알림 제거

**[MODIFY] sell-settings.ts**

**변경 위치:** mount 함수와 unmount 함수 내부

**수정 사항:**
- mount 내부의 `notifyPageActive('sell-settings')` (약 139라인) 코드를 제거하거나 주석 처리합니다.
- unmount 내부의 `notifyPageInactive('sell-settings')` (약 278라인) 코드를 제거하거나 주석 처리합니다.

```diff
  /* ── mount ── */
  function mount(container: HTMLElement): void {
-   notifyPageActive('sell-settings')
    settingsMgr = createSettingsManager(uiStore)
    saving = false
```

```diff
  /* ── unmount ── */
  function unmount(): void {
-   notifyPageInactive('sell-settings')
    if (unsubSettings) { unsubSettings(); unsubSettings = null }
    if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null }
```

### 2. 매수설정 카드 모듈에서 웹소켓 활성화 알림 제거

**[MODIFY] buy-settings.ts**

**변경 위치:** mount 함수와 unmount 함수 내부

**수정 사항:**
- mount 내부의 `notifyPageActive('buy-settings')` (약 159라인) 코드를 제거하거나 주석 처리합니다.
- unmount 내부의 `notifyPageInactive('buy-settings')` (약 433라인) 코드를 제거하거나 주석 처리합니다.

```diff
  /* ── mount ── */
  function mount(container: HTMLElement): void {
-   notifyPageActive('buy-settings')
    settingsMgr = createSettingsManager(uiStore)
```

```diff
  /* ── unmount ── */
  function unmount(): void {
-   notifyPageInactive('buy-settings')
    if (unsubSettings) { unsubSettings(); unsubSettings = null }
```

## Verification Plan

### 1. 자동화 빌드 테스트

수정 완료 후 프론트엔드 루트(frontend/) 디렉토리에서 빌드 명령어 실행하여 타입스크립트 및 번들 오류 유무 확인:

```bash
npm run build
```

### 2. 수동 검증 단계

1. **서버 기동:** 터미널이나 데스크톱에서 `./SectorFlow.command`를 실행하여 서버를 시작합니다.
2. **화면 접속 및 연결 상태 확인:** 브라우저로 http://localhost:5173에 접속하여 우측 상단 배지가 초록색 연결됨으로 표시되는지 확인합니다.
3. **매도설정 페이지 검증:**
   - `#/sell-settings` (매도설정) 메뉴로 이동합니다.
   - 우측의 보유종목 테이블 현재가 필드가 실시간으로 변동하는지 확인합니다.
4. **매수설정 페이지 검증:**
   - `#/buy-settings` (매수설정) 메뉴로 이동합니다.
   - 우측의 매수후보 테이블 현재가 및 실시간 체결 데이터가 변동하는지 확인합니다.
