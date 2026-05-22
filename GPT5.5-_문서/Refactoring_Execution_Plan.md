# SectorFlow 리팩토링 실행 계획서

본 문서는 `Antigravity_Refactoring_Plan.md`을 기반으로 현재 진행 상태(HANDOVER.md)를 분석하여, 미완료된 작업들을 실행하기 위한 촘촘한 실행 계획을 정의합니다.

---

## 📊 현재 상태 분석

### 완료된 Phase
- **Phase 1.1**: Event Model 정의 ✅
- **Phase 1.2**: Event Bus 구현 ✅
- **Phase 2.1**: Hot Store 분리 (P1-1 단계 1-6) ✅
- **Phase 2.2**: DataTable 렌더링 최적화 ✅
- **Phase 2.3**: 렌더링 성능 모니터링 ✅
- **Phase 4.1**: Binary Protocol 최적화 (이미 Protobuf 사용) ✅
- **Phase 4.2**: Persistence Journaling 도입 ✅
- **Phase 4.3**: 관측성(Observability) 고도화 ✅
- **Phase 4.4**: 장애 복구 테스트 ✅

### 건너뛴 Phase (이유 명시)
- **Phase 1.3**: Broker Adapter 리팩토링 → 복잡도로 인해 Phase 1.4로 통합 후 연기
- **Phase 1.4**: engine_service.py 분리 → 2398라인 파일 리팩토링 복잡도로 인해 연기
- **Phase 2.2**: Web Component 도입 → 이미 Vanilla TS 사용 중이므로 불필요
- **Phase 2.3**: React 역할 축소 → 이미 Vanilla TS 사용 중이므로 불필요
- **Phase 3.1**: Strategy Core 완전 분리 → 복잡도로 인해 연기
- **Phase 3.2**: Safety Layer 구현 → 이미 AutoTradeManager에 구현됨
- **Phase 3.3**: Order Engine 구현 → 이미 state_manager.py, kiwoom_order.py에 구현됨
- **Phase 3.4**: engine_service.py 책임 축소 → 복잡도로 인해 연기

---

## 🎯 미완료 핵심 작업 실행 계획

### 우선순위 1: Phase 1.3+1.4 통합 - Broker Adapter & engine_service.py 분리

**이유**: 실시간 데이터 수신 경로의 핵심 병목 제거, Event Bus 활성화

#### 단계 1.1: 사전 정밀 조사 (2-3시간 예상)
- **파일 분석**:
  - `backend/app/services/kiwoom_connector.py` - Kiwoom WebSocket 수신부
  - `backend/app/services/ls_connector.py` - LS WebSocket 수신부 (존재 시)
  - `backend/app/services/engine_service.py` - 데이터 처리 로직 (2398라인)
- **데이터 흐름 파악**:
  - 브로커 → WebSocket 수신 → engine_service.py → State Manager
  - 현재 동기 처리 지점 식별
- **영향성 조사**:
  - engine_service.py 의존 파일 목록화
  - 데이터 수신 경로와 연결된 모든 컴포넌트 식별
- **위험도 평가**:
  - 고위험: 핵심 데이터 수신 경로
  - 롤백 계획 수립 (git commit + 백업)

#### 단계 1.2: Broker Adapter Event Bus 통합 (4-5시간 예상)
- **작업 범위**:
  - `kiwoom_connector.py` 수정: 수신 데이터 → Event Bus Publish
  - `ls_connector.py` 수정: 수신 데이터 → Event Bus Publish (존재 시)
- **구현 내용**:
  - WebSocket 수신 핸들러에서 직접 비즈니스 로직 제거
  - `event_bus.publish()` 호출로 이벤트 전송
  - `MarketTickEvent`, `OrderFillEvent`, `AccountUpdateEvent` 사용
- **테스트**:
  - 단위 테스트: Broker Adapter → Event Bus 전송 검증
  - 통합 테스트: 실제 브로커 연결 시 이벤트 수신 확인

#### 단계 1.3: engine_service.py Event Bus 구독 (5-6시간 예상)
- **작업 범위**:
  - `engine_service.py`에 Event Bus 구독 로직 추가
  - 기존 직접 수신 로직을 이벤트 핸들러로 변환
- **구현 내용**:
  - `async def subscribe_to_event_bus()` 메서드 추가
  - 이벤트 타입별 핸들러 분리:
    - `handle_market_tick(event: MarketTickEvent)`
    - `handle_order_fill(event: OrderFillEvent)`
    - `handle_account_update(event: AccountUpdateEvent)`
- **테스트**:
  - Event Bus → engine_service.py 전송 검증
  - 기존 기능 회귀 테스트

#### 단계 1.4: engine_service.py 책임 분리 (8-10시간 예상)
- **작업 범위**:
  - 2398라인 engine_service.py를 기능별 모듈로 분리
- **분리 계획**:
  - `backend/app/services/market_processor.py` - 시세 데이터 처리
  - `backend/app/services/order_processor.py` - 주문/체결 처리
  - `backend/app/services/account_processor.py` - 계정 업데이트 처리
  - `backend/app/services/sector_processor.py` - 업종 점수 계산
  - `engine_service.py` - 코디네이터 역할만 유지
- **구현 내용**:
  - 각 프로세서를 독립 클래스로 설계
  - Event Bus에서 구독하는 이벤트 타입 명시
  - 프로세서 간 의존성 최소화
- **테스트**:
  - 각 프로세서 단위 테스트
  - 전체 통합 테스트
  - 성능 회귀 테스트

#### 단계 1.5: 검증 및 최적화 (2-3시간 예상)
- **Coalescing 로직 검증**:
  - Event Bus의 종목별 최신 데이터 유지 로직 확인
  - Drop 카운트 로깅 확인
- **성능 측정**:
  - 브로커 수신 → Event Bus → 프로세서 지연 측정
  - 50ms/200ms threshold 준수 확인
- **문서화**:
  - HANDOVER.md 업데이트
  - 아키텍처 다이어그램 업데이트

---

### 우선순위 2: Phase 3.1 - Strategy Core 완전 분리

**이유**: 비즈니스 로직과 데이터 수신 경로 완전 분리, 유지보수성 향상

#### 단계 2.1: 사전 정밀 조사 (2-3시간 예상)
- **파일 분석**:
  - `backend/app/services/engine_service.py` - 업종 점수 계산 로직
  - `backend/app/services/sector_processor.py` - 분리 후 업종 처리 (단계 1.4 완료 시)
- **로직 파악**:
  - 업종 점수 계산 알고리즘
  - 매수 후보 선정 로직
  - 매수/매도 신호 생성 로직
- **영향성 조사**:
  - Strategy Core 의존 파일 목록화
  - TradeSignal 사용처 식별

#### 단계 2.2: Strategy Core 모듈 생성 (4-5시간 예상)
- **작업 범위**:
  - `backend/app/services/strategy_core.py` 생성
- **구현 내용**:
  - `StrategyCore` 클래스 설계
  - Event Bus 구독 (MarketTickEvent)
  - 업종 점수 계산 로직 이전
  - 매수 후보 선정 로직 이전
  - `TradeSignal` 객체 배출:
    - `BuySignal` (종목코드, 수량, 가격)
    - `SellSignal` (종목코드, 수량, 가격)
- **테스트**:
  - 업종 점수 계산 단위 테스트
  - TradeSignal 생성 테스트
  - 기존 로직과 결과 일치 검증

#### 단계 2.3: Order Engine과 통합 (3-4시간 예상)
- **작업 범위**:
  - `backend/app/services/order_engine.py` 수정 (이미 구현됨)
  - TradeSignal 수신 로직 추가
- **구현 내용**:
  - Order Engine이 Event Bus에서 TradeSignal 구독
  - Safety Layer 통과 후 주문 실행
  - 상태 기계(State Machine) 유지
- **테스트**:
  - TradeSignal → Order Engine 전송 검증
  - Safety Layer 동작 검증
  - 주문 실행 회귀 테스트

#### 단계 2.4: engine_service.py에서 Strategy Core 제거 (2-3시간 예상)
- **작업 범위**:
  - engine_service.py에서 업종 점수/매수 후보 로직 제거
  - Strategy Core로 위임
- **구현 내용**:
  - engine_service.py는 코디네이터 역할만 유지
  - Strategy Core 인스턴스化管理
- **테스트**:
  - 전체 통합 테스트
  - 기능 회귀 테스트

#### 단계 2.5: 검증 및 문서화 (1-2시간 예상)
- **기능 검증**:
  - 업종 점수 계산 정확성
  - 매수/매도 신호 정확성
- **문서화**:
  - HANDOVER.md 업데이트
  - 아키텍처 다이어그램 업데이트

---

## 📋 전체 실행 일정

### 총 예상 시간: 35-45시간

| 우선순위 | Phase | 단계 | 예상 시간 | 의존성 |
|---------|-------|------|----------|--------|
| 1 | 1.3+1.4 | 1.1 사전 조사 | 2-3시간 | 없음 |
| 1 | 1.3+1.4 | 1.2 Broker Adapter 통합 | 4-5시간 | 1.1 |
| 1 | 1.3+1.4 | 1.3 engine_service 구독 | 5-6시간 | 1.2 |
| 1 | 1.3+1.4 | 1.4 engine_service 분리 | 8-10시간 | 1.3 |
| 1 | 1.3+1.4 | 1.5 검증 및 최적화 | 2-3시간 | 1.4 |
| 2 | 3.1 | 2.1 사전 조사 | 2-3시간 | 1.5 |
| 2 | 3.1 | 2.2 Strategy Core 생성 | 4-5시간 | 2.1 |
| 2 | 3.1 | 2.3 Order Engine 통합 | 3-4시간 | 2.2 |
| 2 | 3.1 | 2.4 engine_service 정리 | 2-3시간 | 2.3 |
| 2 | 3.1 | 2.5 검증 및 문서화 | 1-2시간 | 2.4 |

---

## ⚠️ 안전장치

### 각 단계 시작 전
- Git commit으로 현재 상태 저장
- 백업 파일 생성 (중요 파일만)
- 롤백 계획 문서화

### 각 단계 완료 후
- 단위 테스트 실행
- 통합 테스트 실행
- 빌드 검증 (npm run build)
- HANDOVER.md 업데이트

### 심각한 오류 발생 시
- 즉시 해당 단계 전체 롤백
- 원인 분석 (파일명+줄번호)
- 재계획 후 재시도

---

## 🎯 성공 기준

### Phase 1.3+1.4 완료 기준
- [ ] Broker Adapter가 Event Bus로 이벤트 전송
- [ ] engine_service.py가 Event Bus에서 구독
- [ ] engine_service.py가 4개 프로세서로 분리
- [ ] Coalescing 로직 동작 (Drop 카운트 로깅)
- [ ] 50ms/200ms threshold 준수
- [ ] 모든 테스트 통과
- [ ] 빌드 성공

### Phase 3.1 완료 기준
- [ ] Strategy Core가 독립 모듈로 분리
- [ ] TradeSignal 객체 배출
- [ ] Order Engine이 TradeSignal 수신
- [ ] 업종 점수 계산 정확성 유지
- [ ] 매수/매도 신호 정확성 유지
- [ ] 모든 테스트 통과
- [ ] 빌드 성공

---

## 📝 참고 문서

- 리팩토링 계획서: `/Users/sungjk0706/Desktop/SectorFlow/GPT5.5-_문서/Antigravity_Refactoring_Plan.md`
- 핸드오버: `/Users/sungjk0706/Desktop/SectorFlow/HANDOVER.md`
- 아키텍처 금지 패턴: `/Users/sungjk0706/.windsurf/plans/architecture-forbidden-patterns-d2f61d.md`
- 안전장치 프로토콜: `/Users/sungjk0706/.windsurf/plans/refactoring-safety-protocol-d2f61d.md`
