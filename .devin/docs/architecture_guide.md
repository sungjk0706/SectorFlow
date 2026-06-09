# SectorFlow 이벤트 기반 아키텍처 가이드

**작성일**: 2026-05-27  
**목적**: 이벤트 기반 아키텍처에서 절대 쓰지 말아야 할 금기 로직 정의

---

## 이벤트 기반 아키텍처에서 절대 쓰지 말아야 할 5가지 금기 로직

### ❌ 1. 상태 체크를 위한 주기적 폴링 (Polling)

**최악의 코드:**
```python
while True:
    if engine_state.has_new_order():
        process_order()
    await asyncio.sleep(0.01)  # 10ms 마다 폴링
```

**이유:**
- 이벤트 기반 아키텍처의 본질은 "일이 터지면 나를 부르는 것(Push)"
- 폴링을 쓰면 sleep하는 시간(10ms)만큼 무조건 지연(Latency) 발생
- 주기를 너무 줄이면 CPU 과도 점유

**대안:**
- 반드시 asyncio.Queue나 asyncio.Event 사용
- 데이터가 들어오는 순간 깨어나도록 구현: `await queue.get()`

---

### ❌ 2. 큐(Queue) 상태를 조건문으로 판단하는 폴링

**최악의 코드:**
```python
while True:
    if not tick_queue.empty():  # ❌ 절대 금지
        data = tick_queue.get_nowait()
        _process(data)
```

**이유:**
- queue.empty()와 get_nowait() 조합은 비동기 이벤트 루프를 쉬게 하지 못함
- 무한 루프를 돌게 만듦
- 다른 코루틴들이 실행될 기회 박탈 (Starvation)

**대안:**
- 무조건 비동기 차단 메서드 사용: `data = await tick_queue.get()`
- 데이터가 없을 때 루프 제어권을 다른 코루틴에게 즉시 양보

---

### ❌ 3. 가혹한 폴백 및 무한 재시도 (Infinite Retry Without Backoff)

**최악의 코드:**
```python
except Exception:
    # 에러 나면 즉시 다시 호출
    return await request_order_rest()
```

**이유:**
- 네트워크 지연이나 증권사 서버 오버로드 시 즉시 무한 재시도
- 이벤트 루프가 에러 처리 코루틴들로 도배됨
- 전체 파이프라인 마비 ("자해성 디도스(Self-DDoS)" 공격)

**대안:**
- 재시도 최대 3~5회로 제한
- 지수 백오프(Exponential Backoff) 전략 적용: `await asyncio.sleep(retry_count ** 2)`

---

### ❌ 4. 컨텍스트가 없는 양보 (asyncio.sleep(0)의 과용)

**현재 상황:**
- pipeline_compute.py:156에 asyncio.sleep(0) 사용

**이유:**
- asyncio.sleep(0)은 제어권을 이벤트 루프에 넘겼다가 "즉시" 다시 대기열 맨 뒤로 들어감
- 처리할 틱 데이터가 쌓여있는데 너무 자주 sleep(0) 호출 시
- 컨텍스트 스위칭 오버헤드로 틱 처리 처리량(Throughput) 급감

**대안:**
- 틱 데이터 하나 처리할 때마다 양보하지 않음
- 배치 단위(예: 10개 또는 50개 틱 처리 후 1회)로 sleep(0) 호출
- 레이턴시 방지에 훨씬 유리

---

### ❌ 5. 동기식 Lock과 비동기 코루틴의 혼용

**현재 상황:**
- journal.py:35, trade_history.py:31, dry_run.py:64에서 threading.Lock 사용
- Phase 1-2에서 제거 예정

**이유:**
- 비동기 루프 내에서 `with threading.Lock():` 사용 시
- 블록 내부에서 await 호출 또는 시간이 걸리는 작업 시
- 스레드 전체가 잠겨버림
- 이벤트 루프에 붙어있는 모든 파이프라인 태스크(compute, oms, gateway) 동시 얼어버림

**대안:**
- 비동기 환경에서는 오직 상호 배제가 필요한 최소한의 디스크 쓰기 구간에만 사용
- `async with asyncio.Lock():` 사용

---

## 디버그 로그 관리

### 디버그 로그 생성 원칙
- 문제 분석 시에만 임시로 디버그 로그 추가
- `logger.debug()`는 기본적으로 사용하지 않음
- 불필요한 INFO 레벨 로그도 제거

### 디버그 로그 삭제 원칙
- 문제 해결 후 추가한 디버그 로그는 즉시 삭제
- 성능 측정용 로그(ms 단위)는 삭제
- "import 완료", "호출 직전" 등 디버깅용 로그는 삭제

### 운영 로그 유지 원칙
- 앱 기동/종료, 매수 체결 등 사용자에게 필요한 정보만 INFO로 출력
- ERROR, WARNING 레벨 로그는 유지

### 코드 작성 시 주의사항
- 평소에는 디버그 로그를 생성하지 않음
- 문제 발생 시에만 임시로 추가하고 해결 후 삭제

---

## 적용 상태

| 금기 로직 | 현재 상태 | 계획 |
|---------|---------|------|
| 1. 주기적 폴링 | 미사용 | - |
| 2. 큐 상태 폴링 | 미사용 | - |
| 3. 무한 재시도 | kiwoom_sector_rest.py에 백오프 있음 | - |
| 4. asyncio.sleep(0) 과용 | pipeline_compute.py:156 사용 | 배치 단위 양보 검토 |
| 5. 동기 Lock 혼용 | journal.py, trade_history.py, dry_run.py 사용 | Phase 1-2에서 제거 |
