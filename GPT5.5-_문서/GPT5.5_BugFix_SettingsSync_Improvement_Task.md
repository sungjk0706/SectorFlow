# 버그 수정 및 설정 동기화 개선 Task

## Backend

### 1. 계좌 브로드캐스트 TypeError 수정
- **파일:** engine_service.py
- **위치:** L1620
- **내용:** TypeError 발생 원인 파악 및 수정

## Frontend

### 2. 업종분석 슬라이더 동기화 누락 수정
- **파일:** sector-analysis.ts
- **위치:** L156
- **내용:** 슬라이더 동기화 로직 누락 수정

### 3. 설정 저장 동기화 방어 및 Jitter 방지 고도화
- **파일:** sector-analysis.ts, buy-settings.ts, sell-settings.ts
- **내용:** 
  - 설정 저장 시 동기화 방어 로직 강화
  - Jitter 방지 고도화

### 4. 매수후보 호가잔량비 실시간 갱신 In-place Mutation 수정
- **파일:** hotStore.ts
- **위치:** L305
- **내용:** In-place Mutation 방식으로 수정하여 불필요한 재생성 방지

### 5. 종목코드 정규화 Mismatch 해결
- **파일:** hotStore.ts
- **내용:**
  - normalizeStockCode 헬퍼 함수 작성
  - rebuildBuyTargetIndex, rebuildPositionIndex, getBuyTargetIndex, getPositionIndex 헬퍼 적용
  - applyRealData, applyOrderbookUpdate, applyAccountUpdate 정규화 연동
  - stocksToMap 정규화 연동

### 6. 가상 스크롤러 0-Height 방어 및 rAF 누수 해결
- **파일:** virtual-scroller.ts
- **내용:**
  - onScroll, updateItems에 clientHeight || 400 폴백 적용
  - initialRender 1회성 rAF 트리거로 수정 및 ResizeObserver 연동 강화

### 7. 업종분석 설정값 Jitter 방지 및 슬라이더 자원 정리
- **파일:** sector-analysis.ts, create-slider.ts
- **내용:**
  - sector-analysis.ts syncFromSettings에 isInteracting 차단 추가
  - create-slider.ts isInteracting window 이벤트 리스너 연동
  - DualLabelSliderHandle에 destroy() 제공
  - sector-analysis.ts, buy-settings.ts unmount 시 해제 연동

### 8. 듀얼 레이아웃 설정 카드 웹소켓 active_page 덮어쓰기 버그 수정
- **파일:** sell-settings.ts, buy-settings.ts
- **내용:**
  - sell-settings.ts mount/unmount의 notifyPageActive/notifyPageInactive 제거
  - buy-settings.ts mount/unmount의 notifyPageActive/notifyPageInactive 제거

## Verification

### 9. 빌드 검증 및 수동 테스트
- **빌드 검증:** npm run build 성공 여부 확인
- **수동 테스트:**
  - SectorFlow.command 재시동
  - 웹소켓 연결 상태 확인
  - 실시간 시세 갱신 확인
  - 매도설정 페이지 보유종목 테이블 실시간 갱신 확인
  - 매수설정 페이지 매수후보 테이블 실시간 갱신 확인
