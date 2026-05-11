# 인계서 (HANDOVER)

**작성일:** 2026-05-11
**작업명:** HTS 급 최적화 전수조사 및 수정계획

---

## 1. 완료된 작업

### requirements.md 작성 (1~8번 상세화 완료)
- 경로: `.kiro/specs/hts-level-optimization/requirements.md`
- Requirement 1~8: 상세 Acceptance Criteria 반영 완료
- Requirement 9~16: 미반영 (아래 섹션 3에 상세화 결과 보존)
- config: `.kiro/specs/hts-level-optimization/.config.kiro` (requirements-first workflow)

---

## 2. 전수조사 결과 요약 (16건)

| # | 영역 | 핵심 문제 | 분류 |
|---|------|----------|------|
| 1 | sell-position.ts | 이중 updateRows + 구독 가드 없음 | 렌더링 |
| 2 | buy-target.ts | 매 틱 sort + rAF 미사용 | 렌더링 |
| 3 | data-table.ts renderRow | innerHTML='' 후 전체 셀 재생성 | DOM |
| 4 | appStore.ts applyRealData | findIndex O(n) 선형 탐색 | 연산 |
| 5 | appStore.ts applyRealData | [...bt] 전체 복사 (splice 미사용) | 워크룰 위반 |
| 6 | sector-stock.ts | titleH3.innerHTML='' | 워크룰 위반 |
| 7 | fixed-table.ts | tbody.innerHTML='' 전체 재구축 | DOM |
| 8 | ws.ts | 재연결 시 REST 백필 없음 | 무결성 |
| 9 | engine_account_notify.py | _is_relevant_code O(n) 리스트 순회 | 백엔드 |
| 10 | virtual-scroller.ts | 매 updateItems 시 전체 오프셋 재계산 | 연산 |
| 11 | profit-overview.ts | rAF 미사용, 동시 구독 갱신 | 렌더링 |
| 12 | 전체 | 비활성 페이지 불필요 구독 트리거 | 구조 |
| 13 | DataTable | 가격 변동 플래시 효과 없음 | UX |
| 14 | ws_manager.py | 불필요 FID 포함, 압축 미적용 | 네트워크 |
| 15 | router.ts | 모듈 캐시 주석 처리됨 | 로딩 |
| 16 | 전체 | console.log 잔존, rowCache 미해제 | 메모리 |

---

## 3. 미반영 상세화 결과 (9~16번) — 다음 세션에서 파일에 append할 것

### Requirement 9: 백엔드 _is_relevant_code 성능 최적화

#### Acceptance Criteria
1. THE WSManager SHALL `_positions`의 각 항목에서 `stk_cd` 필드를 6자리 정규화하여 `set[str]` 자료구조로 캐시한다
2. THE WSManager SHALL `_sector_stock_layout`에서 타입이 "code"인 튜플의 값을 `set[str]` 자료구조로 캐시한다
3. WHEN `_positions`가 재할당되거나 `_sector_stock_layout`이 재할당 또는 clear될 때, THE WSManager SHALL 해당 캐시 set을 동일 호출 내에서(별도 비동기 태스크 없이) 재구축한다
4. WHEN `_is_relevant_code`가 호출될 때, THE WSManager SHALL `_pending_stock_details` dict의 `in` 연산과 캐시 set의 `in` 연산(각 O(1))만으로 관련 여부를 판별하며, 리스트 순회(`any(...)`)를 사용하지 않는다
5. IF `_positions` 캐시 set과 `_sector_stock_layout` 캐시 set 모두에 해당 종목코드가 없고 `_pending_stock_details`에도 없으면, THEN THE WSManager SHALL `False`를 반환하여 해당 틱의 브로드캐스트를 생략한다
6. WHEN `_is_relevant_code`가 초당 500회 호출될 때, THE WSManager SHALL 호출당 평균 처리 시간을 10μs 이하로 유지한다

### Requirement 10: 가상 스크롤러 오프셋 증분 계산

#### Acceptance Criteria
1. IF getRowHeight가 모든 인덱스에 대해 동일한 값을 반환하는 것이 초기화 시점에 확인되면, THEN THE Virtual_Scroller SHALL offsets 배열 순회 없이 산술 계산(index × rowHeight)으로 오프셋을 반환하고, getRowHeight 호출을 생략한다
2. WHEN updateItems가 호출되고 새 items 배열의 길이가 이전과 동일하며 고정 높이 모드가 활성 상태일 때, THE Virtual_Scroller SHALL 오프셋 재계산을 생략하고 sentinel 높이를 유지한다
3. WHEN updateItems가 호출되고 새 items 배열의 길이가 이전과 다를 때, THE Virtual_Scroller SHALL 고정 높이 모드에서는 산술 계산으로 totalHeight와 sentinel 높이만 갱신하고, 가변 높이 모드에서는 전체 오프셋을 재계산한다
4. WHEN updateItem이 호출되고 해당 행의 높이가 변경되지 않았을 때, THE Virtual_Scroller SHALL 오프셋 재계산을 생략한다
5. WHEN updateItem이 호출되고 해당 행의 높이가 변경되었을 때, THE Virtual_Scroller SHALL 해당 행 이후의 오프셋만 증분 갱신하여 O(n−index) 이내에 완료한다

### Requirement 11: profit-overview 페이지 rAF 갱신 병합

#### Acceptance Criteria
1. WHEN 동일 애니메이션 프레임(16.6ms) 내에 2회 이상의 store 상태 변경이 발생할 때, THE Profit_Overview_Page SHALL requestAnimationFrame을 사용하여 해당 프레임의 모든 변경을 1회의 DOM 갱신으로 병합한다
2. WHEN positions 또는 account 필드만 변경될 때, THE Profit_Overview_Page SHALL 계좌현황 숫자와 요약카드만 갱신하고, 차트 및 이력 테이블의 DOM은 갱신하지 않는다
3. WHEN sellHistory 또는 buyHistory 필드만 변경될 때, THE Profit_Overview_Page SHALL 해당 이력 테이블과 요약카드만 갱신하고, 차트 및 계좌현황 숫자의 DOM은 갱신하지 않는다
4. WHEN dailySummary 필드만 변경될 때, THE Profit_Overview_Page SHALL 차트만 갱신하고, 계좌현황·요약카드·이력 테이블의 DOM은 갱신하지 않는다
5. WHEN unmount가 호출될 때, THE Profit_Overview_Page SHALL 대기 중인 requestAnimationFrame 콜백을 cancelAnimationFrame으로 취소한다

### Requirement 12: 비활성 페이지 구독 해제

#### Acceptance Criteria
1. WHILE 사용자가 특정 페이지를 보고 있을 때, THE AppStore SHALL 해당 페이지의 구독 콜백에서 관심 필드의 참조가 변경되지 않은 경우 DOM 갱신 로직을 실행하지 않는다
2. WHEN 페이지가 unmount될 때, THE 페이지 모듈 SHALL 동기적으로 해당 페이지의 모든 store 구독 해제와 예약된 requestAnimationFrame 취소를 완료한다
3. THE AppStore SHALL applyRealData 내에서 각 상태 필드에 대해 실제 값 변경이 없으면 이전 객체 참조를 유지하여, 불필요한 구독 트리거를 방지한다
4. IF unmount 후 이전 페이지가 예약한 rAF 콜백이 실행될 때, THEN THE 콜백 SHALL DOM 조작 없이 즉시 반환한다

### Requirement 13: 가격 변동 시각적 피드백 (플래시 효과)

#### Acceptance Criteria
1. WHEN 종목의 현재가가 이전 값과 다른 값으로 갱신될 때, THE DataTable SHALL 해당 행의 현재가, 대비, 등락률 셀에 배경색 플래시 효과를 적용한다 (300ms 페이드아웃)
2. WHEN 가격이 상승할 때, THE DataTable SHALL 빨간색 계열 배경색 플래시를 표시한다
3. WHEN 가격이 하락할 때, THE DataTable SHALL 파란색 계열 배경색 플래시를 표시한다
4. THE DataTable SHALL 플래시 효과에 CSS transition (background-color)을 사용하며, JavaScript setTimeout/setInterval을 사용하지 않는다
5. IF 300ms 이내에 동일 종목의 가격이 재차 변경되면, THEN THE DataTable SHALL 진행 중인 플래시를 즉시 중단하고 새로운 방향의 플래시를 처음부터 다시 시작한다

### Requirement 14: WebSocket 메시지 최소화

#### Acceptance Criteria
1. WHEN real-data 메시지를 전송할 때, THE WSManager SHALL values에서 프론트엔드에서 사용하는 FID(10, 11, 12, 14, 228)만 포함한다
2. THE WSManager SHALL real-data 메시지의 키 이름을 단축형으로 전송한다: "type"→"t", "item"→"i", "values"→"v"
3. WHEN 직렬화된 JSON 메시지의 바이트 크기가 128바이트를 초과할 때, THE WSManager SHALL zlib 압축 후 바이너리 프레임으로 전송한다
4. IF 128바이트 이하일 때, THEN THE WSManager SHALL 압축 없이 텍스트 프레임으로 전송한다
5. WHEN 프론트엔드가 메시지를 수신할 때, THE WSClient SHALL 바이너리면 zlib 해제 후 파싱, 텍스트면 직접 파싱하여 단축 키를 원래 키로 복원한다

### Requirement 15: 초기 로딩 성능 최적화

#### Acceptance Criteria
1. WHEN 페이지 모듈이 최초 로딩된 후, THE Router SHALL 해당 모듈을 메모리에 캐시하여 재방문 시 즉시 마운트한다
2. WHEN 앱이 시작될 때, THE Router SHALL 현재 활성 라우트의 모듈을 우선 로딩한다
3. WHEN 초기 스냅샷 수신이 완료될 때, THE AppStore SHALL 2초 이내에 UI 렌더링을 완료한다

### Requirement 16: 메모리 누수 방지 강화

#### Acceptance Criteria
1. WHEN 페이지가 unmount될 때, THE Virtual_Scroller SHALL destroy() 호출 후 내부 DOM 풀의 요소 수를 0으로 만든다
2. WHEN Sector_Stock_Page가 unmount될 때, THE Sector_Stock_Page SHALL rowCache(Map)에 대해 clear()를 호출한다
3. IF 빌드 모드가 프로덕션이면, THEN THE Sell_Position_Page SHALL console.log 호출이 번들에 포함되지 않는다
4. WHILE 앱이 8시간 연속 실행 중일 때, THE AppStore SHALL 기동 후 5분 경과 시점 대비 힙 메모리 증가량이 50MB를 초과하지 않는다

---

## 4. 미완료 작업 (다음 세션에서 진행)

1. **requirements.md 9~16번 append** — 위 섹션 3의 내용을 파일에 반영
2. **analyze_requirements 실행** — 전체 요구사항 품질 검증
3. **design.md 작성**
4. **tasks.md 작성**
5. 사용자 승인 후 구현 착수

---

## 5. 다음 세션 시작 시 할 일

1. 이 인계서 읽기
2. requirements.md에 섹션 3 내용 append (9~16번)
3. analyze_requirements 실행
4. design.md → tasks.md 순서로 진행

---

## 6. 반성 및 주의사항

- **토큰 낭비 문제**: 16개 요구사항을 개별 서브에이전트로 상세화하려다 과도한 토큰 소모. 다음엔 직접 작성하거나 배치로 처리할 것.
- 파일 쓰기 시 `fs_write`의 `text` 파라미터 누락 오류 주의 — 큰 파일은 분할 작성.
- 워크룰 7-2 준수: 코드 수정은 반드시 사용자 승인 후에만.
