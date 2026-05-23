# HTS급 주식자동매매 파이프라인 리팩토링 태스크

본 문서는 하위 AI도 한 줄 한 줄 기계적으로 실행할 수 있도록 설계된 극도로 섬세한 아키텍처 분리 작업 명세서입니다. 모든 작업은 `backend/app/services/` 디렉토리 내에서 이루어집니다.

---

## 1. 전역 이벤트 버스 (Queues) 초기화 구축
- [ ] `backend/app/services/core_queues.py` 신규 파일 생성
- [ ] `asyncio.Queue` 기반의 4개 코어 큐 인스턴스 전역 생성 및 Export:
  - `tick_queue = asyncio.Queue()`: 시세 수신 전용
  - `order_queue = asyncio.Queue()`: OMS(주문) 전용
  - `broadcast_queue = asyncio.Queue()`: UI 프론트엔드 전송 전용
  - `control_queue = asyncio.Queue()`: 사용자 설정 제어 전용 (가장 우선순위가 높음)

## 2. 시세 수신부 (Ingestion Pipeline) 격리
- [ ] `engine_service.py`에서 실시간 웹소켓 시세(틱, 체결)를 파싱하는 로직 탐색
- [ ] 틱 수신 시 `_apply_real01_volume_amount_to_radar_rows` 등 즉시 연산을 수행하던 로직 제거
- [ ] 대신 파싱된 원본 시세 데이터를 `await tick_queue.put(raw_data)` 로 큐에 밀어넣도록 수정
- [ ] **목표:** 수신 함수는 단 1의 연산도 하지 않고 오직 큐에 데이터를 적재하는 역할만 하도록 다이어트 완료

## 3. 초고속 연산 엔진 (Compute Engine) 구축
- [ ] `backend/app/services/pipeline_compute.py` 신규 파일 생성
- [ ] `run_compute_loop()` 비동기 무한 루프 함수 작성: `while True: data = await tick_queue.get()`
- [ ] `engine_service.py`에 있던 업종 순위 계산, 체결강도 업데이트, 등락률 계산 로직을 통째로 이관
- [ ] 매수/매도 로직 (사용자 설정 타점 도달 여부 체크) 이관
- [ ] 연산 결과, 타점에 도달한 종목이 발생하면 `await order_queue.put({'action': 'BUY', 'code': '005930'})` 발송
- [ ] 연산 결과, UI 화면 갱신이 필요하면 `await broadcast_queue.put(summary_data)` 발송
- [ ] `tick_queue.task_done()` 호출로 메모리 해제 보장

## 4. OMS 전용 배관 (Order Pipeline) 구축
- [ ] `backend/app/services/pipeline_oms.py` 신규 파일 생성
- [ ] `run_oms_loop()` 비동기 무한 루프 함수 작성: `while True: order = await order_queue.get()`
- [ ] 수신된 `order` 객체의 명령어에 따라 키움증권 REST API / WS API를 호출하여 실제 매수/매도 주문 실행
- [ ] 주문 실패/성공 시 `broadcast_queue`에 알림 전송하여 화면(UI)에 팝업 띄우도록 연계
- [ ] `order_queue.task_done()` 호출

## 5. UI 브로드캐스터 (Gateway Pipeline) 분리
- [ ] `backend/app/services/pipeline_broadcast.py` 신규 파일 생성
- [ ] `run_broadcast_loop()` 비동기 무한 루프 함수 작성: `while True: data = await broadcast_queue.get()`
- [ ] 기존 `backend_coalescing.py`의 `push_sector_summary` 등 프론트엔드 웹소켓(`ws_manager.py`) 쏘는 로직을 이곳으로 이관
- [ ] UI 랜더링 과부하를 막기 위해 초당 N회 이하로 데이터를 묶어서(Batch) 보내는 로직 유지
- [ ] `broadcast_queue.task_done()` 호출

## 6. 컨트롤 플레인 (Control Plane) 우회 배관 연동
- [ ] 기존 API 라우터(`settings.py`, `stock_classification.py` 등)에서 사용자가 설정을 변경할 때의 로직 수정
- [ ] DB에만 저장하던 설정값을 실시간 연산 엔진에 적용하기 위해 `await control_queue.put({'type': 'UPDATE_CONFIG', 'payload': ...})` 호출
- [ ] `pipeline_compute.py`에서 `tick_queue`를 처리하기 전, `control_queue`에 데이터가 있는지 비동기로 확인하고, 있으면 최우선으로 연산 엔진의 상태(전역 변수 등)를 업데이트하도록 로직 삽입

## 7. 중앙 코디네이터 (Bootstrap) 연동 및 테스트
- [ ] `engine_loop.py` 또는 `engine_bootstrap.py`의 메인 시작점에서 `asyncio.create_task()`를 이용하여 위 4개의 파이프라인 루프(Compute, OMS, Broadcast)를 백그라운드 태스크로 동시 실행
- [ ] 기존 `engine_service.py`에 남아있는 레거시(더 이상 쓰지 않는 함수들) 완전 삭제 및 청소
- [ ] Mock(가짜) 틱 데이터를 수백 개 발생시켜 `Ingestion -> Compute -> Broadcast`가 꼬이지 않고 콘솔에 찍히는지 테스트 스크립트로 검증
