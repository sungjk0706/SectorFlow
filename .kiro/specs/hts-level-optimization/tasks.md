# Implementation Plan: HTS 급 최적화 전수조사 및 수정계획

## Overview

SectorFlow 실시간 주식 자동매매 앱의 프론트엔드/백엔드 전체를 HTS 수준 성능으로 최적화한다. 핵심 구현 순서: 데이터 레이어(AppStore index cache + splice) → 렌더링 레이어(rAF coalescing + cell diffing) → 네트워크 레이어(WS 인코딩 + 백필) → 부가 기능(flash, router, memory) 순으로 진행한다.

## Tasks

- [x] 1. AppStore 인덱스 캐시 및 splice 기반 증분 갱신
  - [x] 1.1 AppStore에 buyTargetIndexCache / positionIndexCache (Map) 추가 및 rebuildIndex 함수 구현
    - `frontend/src/stores/appStore.ts` 모듈 스코프에 `_buyTargetIndexCache: Map<string, number>`, `_positionIndexCache: Map<string, number>` 선언
    - `rebuildBuyTargetIndex(targets)` / `rebuildPositionIndex(positions)` 함수 구현
    - buyTargets/positions가 변경되는 모든 setState 호출 지점에서 캐시 재구축 호출 추가
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 1.2 applyRealData를 splice 기반 증분 갱신으로 리팩토링
    - `findIndex` 호출을 `_buyTargetIndexCache.get(code)` / `_positionIndexCache.get(code)`로 교체
    - `[...bt]` 스프레드 복사를 `buyTargets.splice(idx, 1, newItem)` 으로 교체
    - positions splice 시 `eval_amount`, `pnl_amount`, `pnl_rate` 파생 필드 재계산 로직 포함
    - 대상 종목 미존재 또는 필드 동일 시 setState 호출 생략 (reference equality guard)
    - _Requirements: 4.5, 5.1, 5.2, 5.3, 5.4, 12.3_

  - [x]* 1.3 Property 3: Index Cache Consistency 테스트 작성
    - **Property 3: 인덱스 캐시 정합성**
    - fast-check로 임의의 BuyTarget[]/Position[] 배열 생성 → rebuildIndex 후 모든 `cache.get(arr[i].code) === i` 검증
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**

  - [x]* 1.4 Property 4: Splice + Derived Field Recalculation 테스트 작성
    - **Property 4: 증분 갱신 정확성**
    - fast-check로 임의의 Position(buy_amt > 0, qty > 0) + 새 cur_price 생성 → splice 후 eval_amount === cur_price × qty, pnl_amount === eval_amount − buy_amt, pnl_rate === round((pnl_amount / buy_amt) × 100, 2) 검증
    - **Validates: Requirements 5.1, 5.2**

  - [x]* 1.5 Property 5: applyRealData No-Op Guard 테스트 작성
    - **Property 5: 변경 없으면 상태 유지**
    - fast-check로 존재하지 않는 code 또는 동일 필드값 틱 생성 → setState 미호출 검증
    - **Validates: Requirements 5.3, 12.3**

- [x] 2. rAF Coalescing 패턴 적용 (sell-position, buy-target, profit-overview)
  - [x] 2.1 sell-position.ts에 rAF coalescing + reference equality guard 적용
    - store 구독 콜백에서 positions 참조 비교 (`prevRef === currentRef` → skip)
    - sectorStocks만 변경 시 updateRows 호출 생략
    - `requestAnimationFrame` 기반 단일 갱신 예약 (이중 호출 제거)
    - unmount 시 `cancelAnimationFrame` + 구독 해제
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 12.1, 12.2_

  - [x] 2.2 buy-target.ts에 rAF coalescing + reference equality guard 적용
    - buyTargets 참조 동일 시 sort + updateRows 생략
    - rAF 콜백 내에서 sort + updateRows 1회 실행
    - positions/settings/wsSubscribeStatus/buyLimitStatus 참조 동일 시 updateBadges 생략
    - unmount 시 cancelAnimationFrame
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 2.3 profit-overview.ts에 rAF coalescing + selective update 적용
    - 필드 그룹별 참조 비교: positions/account, sellHistory/buyHistory, dailySummary
    - 변경된 필드 그룹에 해당하는 DOM 섹션만 갱신
    - rAF 기반 프레임당 최대 1회 DOM 갱신
    - unmount 시 cancelAnimationFrame + mounted 플래그 확인
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x]* 2.4 Property 1: Reference Equality Guard 테스트 작성
    - **Property 1: 상태 참조 미변경 시 갱신 생략**
    - fast-check로 임의의 상태 변경 시퀀스 생성 (참조 동일 유지) → DOM update 함수 미호출 검증
    - **Validates: Requirements 1.1, 1.2, 2.2, 12.1, 12.3**

  - [x]* 2.5 Property 2: rAF Coalescing 테스트 작성
    - **Property 2: 프레임 내 다중 변경 → 단일 갱신**
    - fast-check로 임의의 N (1-100) 상태 변경 생성 (mock rAF) → DOM update 정확히 1회 호출 검증
    - **Validates: Requirements 1.3, 1.4, 2.1, 11.1**

  - [x]* 2.6 Property 10: Selective Page Update 테스트 작성
    - **Property 10: 선택적 DOM 갱신**
    - fast-check로 profit-overview의 필드 그룹 변경 조합 생성 → 비관련 섹션 DOM mutation 0건 검증
    - **Validates: Requirements 11.2, 11.3, 11.4**

- [x] 3. Checkpoint - 데이터 레이어 및 rAF 패턴 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. DataTable cell diffing + 가격 플래시 효과
  - [x] 4.1 DataTable renderRow를 cell diffing 방식으로 교체
    - `rowEl.innerHTML = ''` 제거 → 기존 셀 DOM 유지
    - 최초 렌더링 또는 행 타입 변경 시에만 셀 생성
    - 문자열 셀: `textContent` 비교 후 변경 시에만 갱신
    - HTMLElement 셀: `outerHTML` 비교 후 변경 시에만 교체
    - 개별 셀 render 예외 시 try-catch로 해당 셀만 건너뛰기
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 4.2 DataTable에 가격 플래시 효과 구현
    - `flashState: Map<string, { prevPrice: number; flashTs: number }>` 관리
    - 가격 상승 시 빨간색, 하락 시 파란색 배경 플래시
    - CSS transition (`background-color 300ms ease-out`) 사용 — setTimeout/setInterval 금지
    - reflow 강제로 transition 재시작 (300ms 내 재변경 시 새 플래시)
    - 뷰포트 밖 행이 스크롤로 복귀 시 300ms 경과한 플래시 미표시
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [x]* 4.3 Property 6: Cell Diffing Idempotence 테스트 작성
    - **Property 6: 동일 데이터 재렌더링 시 DOM 무변경**
    - fast-check로 임의의 row 데이터 생성 → 동일 데이터로 2회 renderRow 호출 → DOM mutation 0건 검증
    - **Validates: Requirements 3.1, 3.2**

  - [x]* 4.4 Property 14: Flash Direction Matches Price Change 테스트 작성
    - **Property 14: 플래시 방향 정확성**
    - fast-check로 임의의 가격 변경 시퀀스 생성 → 상승 시 red, 하락 시 blue 검증 + 300ms 내 재변경 시 최종 방향 검증
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.5**

- [x] 5. FixedTable 증분 갱신 + Virtual Scroller 고정 높이 최적화
  - [x] 5.1 FixedTable updateRows를 rowKey 기반 증분 갱신으로 교체
    - `tbody.innerHTML = ''` 제거 (초기 로딩 시에만 허용)
    - rowKey 기반 old/new 행 매핑 구축
    - 신규 행 삽입, 제거된 행 DOM 삭제, 기존 행 셀별 diff 갱신
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 5.2 Virtual Scroller에 고정 높이 fast path 추가
    - `detectFixedHeight()` — 초기화 시 행 높이 균일 여부 감지
    - 고정 높이 모드: `index × rowHeight` 산술 계산 (offsets 배열 순회 없음)
    - 길이 동일 + 고정 높이 시 오프셋 재계산 생략
    - 가변 높이 모드: 높이 변경된 행 이후만 증분 갱신
    - 오프셋 drift > 1px 시 전체 재계산 fallback
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x]* 5.3 Property 7: FixedTable Incremental Update 테스트 작성
    - **Property 7: rowKey 기반 증분 갱신**
    - fast-check로 임의의 old/new row 배열 생성 → 삽입/제거/갱신 정확성 검증
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x]* 5.4 Property 9: Virtual Scroller Fixed-Height Offset 테스트 작성
    - **Property 9: 고정 높이 오프셋 산술**
    - fast-check로 임의의 item count N + row height H 생성 → offset(i) === i × H, totalHeight === N × H 검증
    - **Validates: Requirements 10.1, 10.3, 10.5**

- [x] 6. Checkpoint - 렌더링 레이어 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. sector-stock 타이틀 CSS display 토글
  - [x] 7.1 sector-stock.ts updateUI에서 innerHTML 제거 및 CSS display 토글 적용
    - mount 시 타이틀 영역 DOM 요소(기본 타이틀 span, 거래대금 필터 span, 종목 수 span) 1회 생성
    - updateUI에서 `titleH3.innerHTML = ''` 제거
    - sectorStatus true: textContent 갱신만 수행
    - sectorStatus false: `display: none` 토글
    - sectorStatus false→true: `display: ''` 전환 (DOM 추가/제거 없음)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x]* 7.2 Property 16: Sector-Stock Title CSS Toggle 테스트 작성
    - **Property 16: innerHTML 미사용**
    - fast-check로 임의의 sectorStatus/minTradeAmt/stockCount 시퀀스 생성 → DOM 요소 수 불변 + textContent/display만 변경 검증
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**

- [x] 8. WS Message Encoder/Decoder (백엔드 + 프론트엔드)
  - [x] 8.1 백엔드 ws_manager.py에 FID 필터 + key shortening + zlib 압축 구현
    - `ALLOWED_FIDS = {'10', '11', '12', '14', '228'}` 필터링
    - key shortening: `type→t`, `item→i`, `values→v`
    - JSON 직렬화 후 바이트 크기 > 512 → zlib 압축 binary frame 전송
    - 바이트 크기 ≤ 512 → 텍스트 프레임 전송
    - zlib 압축 실패 시 graceful degradation (텍스트 전송)
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x] 8.2 프론트엔드 ws.ts에 binary/text frame 디코딩 + key expansion 구현
    - binary frame: zlib decompress → JSON parse → key expand
    - text frame: JSON parse → key expand
    - `KEY_MAP = { t: 'type', i: 'item', v: 'values' }` 복원
    - zlib 해제 실패 / JSON 파싱 실패 시 console.error 후 메시지 무시
    - _Requirements: 14.5_

  - [x]* 8.3 Property 11: WS Message Round-Trip 테스트 작성
    - **Property 11: 인코딩/디코딩 왕복**
    - fast-check로 임의의 real-data 메시지 생성 → encode → decode → 원본과 의미적 동치 검증 (허용 FID만 유지)
    - **Validates: Requirements 14.2, 14.5**

  - [x]* 8.4 Property 12: WS Compression Threshold 테스트 작성
    - **Property 12: 압축 임계값**
    - fast-check로 임의 크기(50-1000 bytes) 메시지 생성 → >512 bytes면 binary, ≤512이면 text 검증
    - **Validates: Requirements 14.3, 14.4**

  - [x]* 8.5 Property 13: WS FID Filtering 테스트 작성
    - **Property 13: 불필요 필드 제거**
    - fast-check로 임의의 FID keys를 가진 values dict 생성 → 전송 결과에 {10,11,12,14,228}만 포함 검증
    - **Validates: Requirements 14.1**

- [x] 9. 백엔드 _is_relevant_code set 캐시 최적화
  - [x] 9.1 engine_account_notify.py에 _positions_code_set / _layout_code_set 구현
    - `_positions_code_set: set[str]` — stk_cd 6자리 정규화 후 set 구축
    - `_layout_code_set: set[str]` — layout에서 type=="code" 값 set 구축
    - `_rebuild_positions_cache()` / `_rebuild_layout_cache()` 함수 구현
    - _positions 재할당 / _sector_stock_layout 재할당·clear 시 동기적 캐시 재구축
    - `_is_relevant_code(nk)` → `nk in _pending_stock_details or nk in _positions_code_set or nk in _layout_code_set`
    - 캐시 재구축 예외 시 이전 캐시 유지 + 로그 경고
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x]* 9.2 Property 8: _is_relevant_code Set Equivalence 테스트 작성 (Hypothesis)
    - **Property 8: set 캐시 정확성**
    - Hypothesis로 임의의 stock code + positions/layout 상태 생성 → set 기반 결과 === 리스트 순회 결과 검증
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

- [x] 10. Checkpoint - 네트워크 레이어 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. WS 재연결 시 스냅샷 새로고침 (간소화)
  - [x] 11.1 ws.ts에 재연결 성공 시 스냅샷 새로고침 구현
    - 재연결 성공 → 장중 실시간 데이터 필드 비움 (기존 방식 유지)
    - 서버로부터 initial-snapshot 수신 시 AppStore 전체 교체 (applyInitialSnapshot)
    - 버퍼링/replay 로직 없음 — 시간 순서 꼬임 위험 제거
    - backfilling 플래그를 AppStore에 설정하여 UI가 동기화 상태 표시
    - _Requirements: 8.1, 8.3, 8.6, 8.7_
    - _결정: 버퍼링+replay 방식 대신 스냅샷 새로고침으로 간소화 (데이터 정합성 우선)_

  - [x]* 11.2 Property 15: WS 재연결 스냅샷 적용 테스트 작성
    - **Property 15: 재연결 시 스냅샷 정합성**
    - fast-check로 임의의 스냅샷 데이터 생성 → applyInitialSnapshot 후 Store 상태가 스냅샷과 일치 검증
    - **Validates: Requirements 8.3**

- [x] 12. Router 모듈 캐시 활성화
  - [x] 12.1 router.ts에 moduleCache 활성화 (프리페치 제외)
    - 주석 처리된 moduleCache 활성화
    - `loadModule(config)` — 캐시 hit 시 즉시 반환, miss 시 import 후 캐시 저장
    - 캐시된 페이지 전환 시 스피너 미표시 + 동기 mount
    - prefetchIdleRoutes 미구현 (장중 부하 방지 — 프리페치 생략)
    - _Requirements: 15.1, 15.2_
    - _결정: 프리페치는 장중 부하 대비 이득이 크지 않아 생략_

- [x] 13. 메모리 누수 방지 강화
  - [x] 13.1 메모리 정리 코드 추가 (pool cleanup, rowCache clear, console.log 제거)
    - virtual-scroller destroy() 후 pool 요소 수 0 보장
    - sector-stock.ts unmount 시 rowCache.clear() 호출
    - sell-position.ts line 121~122 console.log 제거 (또는 빌드 시 strip)
    - unmount 후 rAF 콜백 실행 시 mounted 플래그 확인 → 즉시 return
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 12.2, 12.4_

- [x] 14. Page-Aware Data Filtering (보고 있는 화면만 데이터 받기)
  - [x] 14.1 백엔드 ws_manager.py에 per-client active_page 관리 구현
    - `_client_active_page: dict[WebSocket, str]` 추가
    - `set_active_page(ws, page)` / `clear_active_page(ws)` 메서드 구현
    - `unregister(ws)` 시 `_client_active_page` 항목 제거
    - WS 수신 핸들러에서 "page-active" / "page-inactive" 메시지 파싱 → set_active_page / clear_active_page 호출
    - _Requirements: 17.1, 17.2, 17.3, 17.10_

  - [x] 14.2 백엔드 _send_realdata_immediate를 per-client 필터링으로 교체
    - `_is_code_relevant_for_page(page, code)` 함수 구현
    - sector-analysis: layout 종목만 전송
    - buy-target: buyTargets 종목만 전송
    - sell-position: positions 종목만 전송
    - profit-overview / settings: real-data 전송 안 함
    - 알 수 없는 페이지 또는 active_page 미설정: 전체 전송 (안전 폴백)
    - _Requirements: 17.4, 17.5, 17.6, 17.7, 17.8, 17.12_

  - [x] 14.3 프론트엔드 각 페이지 mount/unmount에 page-active/page-inactive 전송 추가
    - `notifyPageActive(page)` / `notifyPageInactive(page)` 유틸 함수 구현 (ws.ts)
    - 각 페이지 mount 시 notifyPageActive 호출, unmount 시 notifyPageInactive 호출
    - 페이지 식별자 매핑: sector-analysis, buy-target, sell-position, profit-overview, settings
    - _Requirements: 17.1, 17.2, 17.9_

  - [x]* 14.4 Property 17: Page-Aware Filtering 테스트 작성
    - **Property 17: 페이지별 필터링 정확성**
    - Hypothesis로 임의의 active_page + stock code 조합 생성 → _is_code_relevant_for_page 결과가 페이지별 규칙과 일치 검증
    - **Validates: Requirements 17.4, 17.5, 17.6, 17.7, 17.8**

- [x] 15. Final checkpoint - 전체 통합 검증
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests use fast-check (TypeScript) and Hypothesis (Python) as specified in the design
- 워크룰 준수: splice 기반 배열 갱신, innerHTML 금지 (초기 마운트 제외), 이벤트 기반 (폴링 없음), 델타 전송, 단일 스레드 모델
- 구현 순서: 데이터 레이어 → 렌더링 레이어 → 네트워크 레이어 → 부가 기능 (의존성 순)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "9.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "9.2"] },
    { "id": 2, "tasks": ["1.4", "1.5", "2.1", "2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "2.6", "7.1"] },
    { "id": 4, "tasks": ["4.1", "5.1", "5.2", "7.2"] },
    { "id": 5, "tasks": ["4.2", "4.3", "5.3", "5.4"] },
    { "id": 6, "tasks": ["4.4", "8.1"] },
    { "id": 7, "tasks": ["8.2", "8.3", "8.4", "8.5"] },
    { "id": 8, "tasks": ["11.1", "12.1", "13.1", "14.1"] },
    { "id": 9, "tasks": ["11.2", "14.2"] },
    { "id": 10, "tasks": ["14.3", "14.4"] }
  ]
}
```
