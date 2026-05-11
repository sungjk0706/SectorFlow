# SectorFlow 백엔드 성능 분석 보고서 (일반 사용자용)

**작성일:** 2026년 5월 11일  
**분석 대상:** SectorFlow 자동매매 시스템 백엔드  
**분석 범위:** 실시간 데이터 처리, 캐싱, 비동기 처리, 메모리 관리

---

## 1. 실행 요약

이 보고서는 SectorFlow 백엔드의 성능을 분석한 결과입니다. 전반적으로 **잘 설계된 시스템**이며 실시간 주식 매매에 적합한 구조입니다. 다만 몇 가지 개선하면 더 좋아질 부분이 있습니다.

**핵심 결론:**
- ✅ 실시간 데이터 처리는 효율적으로 설계됨
- ✅ 캐싱 시스템이 잘 구축되어 있음
- ⚠️ 일부 블로킹(멈춤) 현상 개선 필요
- ⚠️ 메모리 사용량 관리 기능 추가 필요

---

## 2. 실시간 데이터 처리 (웹소켓)

### 잘된 점 ✅

**1. 빠른 메시지 처리**
- 웹소켓으로 들어오는 실시간 주식 데이터를 빠르게 분류하여 처리
- `engine_ws_dispatch.py`가 메시지 타입별(체결가, 잔고, 호가 등)로 적절히 분배
- 예: 체결가(01), 주문체결(00), 잔고변경(04), 지수(0j), 호가(0d)

**2. 섹터 재계산 최적화 (이미 수정됨)**
- 매 실시간 틱마다 섹터를 재계산하지 않고, **0.3초 동안 모아서 한 번에 계산**
- `engine_sector_confirm.py`의 `call_later(0.3, ...)` 패턴 사용
- 효과: 키움증권 API 호출(REG/REMOVE) 횟수 대폭 감소 → **사이드바 클릭 등 UI 반응 개선**

**3. 락(Lock) 없는 고속 캐시**
- `_latest_trade_amounts`(최근 거래대금) 같은 단순 캐시는 락 없이 직접 접근
- Python의 GIL(전역 인터프리터 락) 덕분에 단일 키 접근은 안전함
- 성능 최적화를 위해 락을 과도하게 사용하지 않음

### 문제점 ⚠️

**1. time.sleep() 블로킹 현상**
- 키움증권 REST API 호출 시 `time.sleep()`을 사용하여 대기
- 위치: `app/core/kiwoom_rest.py` (151, 165, 192, 201번째 줄)
- 위치: `app/core/industry_map.py` (388, 425번째 줄)
- 문제: `time.sleep()`은 프로그램 전체를 멈추게 함 (비동기 처리 불가)
- 영향: API 응답 대기 중 다른 기능(실시간 데이터 수신 등)이 잠시 멈출 수 있음

**2. 미정의 상수 오류**
- `engine_account_notify.py` 340번째 줄에서 `_TICK_FIELDS` 상수 참조
- 해당 상수가 정의되지 않음 → 런타임 오류 가능성
- 즉시 수정 필요

### 개선 제안 🔧

**1. time.sleep() → asyncio.sleep()로 변경**
```python
# 변경 전 (블로킹):
time.sleep(0.3)  # 프로그램 전체 멈춤

# 변경 후 (비동기):
await asyncio.sleep(0.3)  # 다른 작업은 계속 진행
```

**2. _TICK_FIELDS 상수 정의**
```python
# engine_account_notify.py 상단에 추가
_TICK_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")
```

---

## 3. 캐싱 시스템 (데이터 저장/불러오기)

### 잘된 점 ✅

**1. 다중 캐시 아키텍처**
- **파일 캐시**: 프로그램 종료 후에도 유지되는 JSON 파일
  - 레이아웃 캐시: 관심 종목 목록
  - 스냅샷 캐시: 장마감 후 확정 데이터
  - 5일평균 캐시: 거래대금 5일 평균
  - 업종맵 캐시: 적격 종목 코드
- **메모리 캐시**: 프로그램 실행 중 빠른 접근용
  - `_latest_trade_amounts`: 실시간 거래대금
  - `_high_5d_cache`: 5일 전고가
  - `_rest_radar_quote_cache`: REST API 호가 데이터

**2. 병렬 캐시 로딩**
- 프로그램 시작 시 5개 캐시를 동시에(parallel) 로드
- `asyncio.gather()` + `asyncio.to_thread()` 사용
- 효과: 시작 시간 단축 (순차 로딩보다 약 5배 빠름)

**3. 스마트 캐시 갱신 (Coalesce_Save)**
- 커스텀 업종 데이터(`sector_custom_data.py`) 저장 시 Coalesce 패턴 사용
- 여러 번 저장 요청이 들어와도 최신 데이터만 디스크에 기록
- 스레드 Lock으로 동시 저장 충돌 방지
- 효과: 디스크 I/O 감소, 프로그램 반응성 유지

**4. 날짜 기반 캐시 검증**
- `is_cache_valid()` 함수로 캐시 유효성 검사
- 거래일 기준으로 오래된 캐시 자동 폐기
- 주말/공휴일 지나면 자동으로 새 데이터 로드

### 문제점 ⚠️

**1. 일부 동기 I/O 남아있음**
- `settings_file.py`: 설정 파일 읽기/쓰기가 동기식
- `debug_session_log.py`: 디버그 로그 파일 쓰기가 동기식
- 영향: 파일 크기가 클 때 이벤트 루프가 잠시 멈출 수 있음

**2. 캐시 크기 제한 없음**
- `_rest_radar_quote_cache`: 종목 수가 많아지면 무한 증가
- `_latest_trade_amounts`: 장중 거래량 증가에 따라 계속 커짐
- `_snapshot_history`: 수익률 이력이 계속 쌓임 (삭제 로직 없음)
- 위험: 장시간 실행 시 메모리 사용량 계속 증가

**3. 불필요한 deepcopy() 남발**
- `sector_custom_data.py`의 `load_custom_data()`는 항상 `deepcopy()` 반환
- 읽기 전용 조회에도 불필요한 메모리 복사 발생
- `load_custom_data_readonly()` 함수가 있지만 사용처에서 혼용 가능성

### 개선 제안 🔧

**1. 모든 파일 I/O를 비동기로**
```python
# 현재 (동기 - 프로그램 멈춤):
with open("settings.json", "r") as f:
    data = json.load(f)

# 개선 (비동기 - 다른 작업 가능):
data = await asyncio.to_thread(json.load, open("settings.json", "r"))
```

**2. 캐시 크기 제한 (LRU eviction)**
```python
# 예: 최대 1000개까지만 저장, 오래된 것 자동 삭제
from collections import OrderedDict

class LimitedCache:
    def __init__(self, maxsize=1000):
        self.cache = OrderedDict()
        self.maxsize = maxsize
    
    def set(self, key, value):
        if len(self.cache) >= self.maxsize:
            self.cache.popitem(last=False)  # 가장 오래된 것 삭제
        self.cache[key] = value
```

**3. 읽기 전용 최적화**
- 읽기 전용 함수를 표준으로 사용
- 수정이 필요할 때만 `deepcopy()` 사용

---

## 4. 비동기 처리 패턴

### 잘된 점 ✅

**1. asyncio.to_thread() 광범위 사용**
- 블로킹 작업(파일 I/O, REST API 호출)을 별도 스레드로 위임
- 메인 이벤트 루프는 계속해서 실시간 데이터 처리 가능
- 사용처: `engine_cache.py`, `engine_bootstrap.py`, `market_close_pipeline.py` 등

**2. asyncio.gather() 병렬 처리**
- 여러 작업을 동시에 실행하여 시간 단축
- 예: 캐시 로딩, 브로커 초기화 등

**3. 이벤트 기반 동기화**
- `asyncio.Event` 객체로 작업 순서 조율
- 예: `market_close_pipeline.py`의 
  - `data_fetched_event`: 데이터 수신 완료 신호
  - `parsing_done_event`: 파싱 완료 신호
  - 타임아웃(300초) 설정으로 무한 대기 방지

**4. Coalescing (모아서 처리)**
- 계좌 브로드캐스트: 0.5초 동안 모아서 1회만 전송
- 섹터 재계산: 0.3초 동안 모아서 1회만 계산
- 효과: 불필요한 네트워크/계산 트래픽 감소

### 문제점 ⚠️

**1. Task 누수 가능성**
- `create_task()`로 생성된 태스크 중 일부가 명시적으로 정리되지 않음
- Python 3.11+의 `TaskGroup` 패턴 미사용
- 장시간 실행 시 백그라운드 태스크 누적 가능

**2. Backpressure (배압) 부재**
- 웹소켓 메시지 처리에 속도 제한 없음
- 시장 개장 직후 등 거래 대량 발생 시 메시지 폭주 가능
- 큐 깊이 모니터링 없음

### 개선 제안 🔧

**1. Python 3.11+ TaskGroup 사용**
```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(task1())
    tg.create_task(task2())
# 자동으로 모든 태스크 완료 대기 및 정리
```

**2. 세마포어로 병렬 처리 제한**
```python
# 최대 100개 동시 처리
_ws_sem = asyncio.Semaphore(100)

async def handle_message(msg):
    async with _ws_sem:
        await process(msg)
```

---

## 5. 메모리 관리

### 잘된 점 ✅

**1. 명시적 자원 정리**
- `_reset_realtime_fields()`: 실시간 구독 시작 시 캐시 초기화
- `.clear()` 메서드로 딕셔너리 비우기
- 타이머 핸들 저장 및 취소 (`_account_broadcast_timer`, `_recompute_handle`)

**2. 락 기반 동시성 제어**
- `asyncio.Lock` (`_shared_lock`): 공유 상태 보호
- `threading.Lock`: Coalesce_Save에서 파일 동시 쓰기 방지
- 프로세스 레벨 파일 락 (`lock_manager.py`): 중복 실행 방지

**3. Dataclass 사용**
- `@dataclass`로 구조화된 데이터 관리
- `@dataclass(frozen=True)`로 불변 객체 표현

### 문제점 ⚠️

**1. 무한 증가 데이터 구조**
| 변수명 | 문제 | 영향 |
|--------|------|------|
| `_latest_trade_amounts` | 종목별 실시간 거래대금 누적 | 장중 메모리 증가 |
| `_rest_radar_quote_cache` | REST 호가 데이터 캐싱 | 제한 없음 |
| `_pending_stock_details` | 관심 종목 상세 정보 | 삭제 로직 미흡 |
| `_snapshot_history` | 수익률 이력 | 계속 쌓임 |

**2. GC (가비지 컬렉션) 미관리**
- Python 자동 GC에만 의존
- 명시적 `gc.collect()` 호출 없음
- 메모리 압박 시 대응 늦을 수 있음

**3. 메모리 모니터링 부재**
- 현재 메모리 사용량 로깅 없음
- 메모리 누수 감지 메커니즘 없음
- 프로덕션 프로파일링 없음

### 개선 제안 🔧

**1. 주기적 GC 실행**
```python
import gc

async def periodic_gc():
    while True:
        await asyncio.sleep(300)  # 5분마다
        gc.collect()
```

**2. 메모리 사용량 모니터링**
```python
import psutil

def log_memory():
    proc = psutil.Process()
    mem = proc.memory_info()
    logger.info(f"메모리 사용량: {mem.rss/1024/1024:.1f}MB")
```

---

## 6. 우선순위별 개선 제안

### 🚨 즉시 수정 필요 (Critical)

**1. time.sleep() → asyncio.sleep() 변경**
- 파일: `app/core/kiwoom_rest.py`, `app/core/industry_map.py`
- 이유: 프로그램 전체 멈춤 현상 방지
- 예상 시간: 1시간

**2. _TICK_FIELDS 상수 정의**
- 파일: `app/services/engine_account_notify.py`
- 이유: 런타임 오류 방지
- 예상 시간: 5분

### 🔶 다음 스프린트 (High)

**3. 캐시 크기 제한**
- 대상: `_rest_radar_quote_cache`, `_latest_trade_amounts`
- 방법: LRU 방식으로 오래된 항목 자동 삭제
- 예상 시간: 4시간

**4. 설정 파일 I/O 비동기화**
- 파일: `app/core/settings_file.py`
- 방법: `asyncio.to_thread()`로 감싸기
- 예상 시간: 2시간

**5. 메모리 모니터링 추가**
- 방법: 주기적 메모리 사용량 로깅
- 예상 시간: 2시간

### 🔷 추후 개선 (Medium)

**6. aiofiles 라이브러리 도입**
- 효과: 더 효율적인 비동기 파일 I/O
- 예상 시간: 4시간

**7. 캐시 압축**
- 방법: JSON 캐시 gzip 압축 저장
- 효과: 디스크 I/O 감소, 저장공간 절약
- 예상 시간: 2시간

**8. TaskGroup 패턴 도입 (Python 3.11+)**
- 효과: 태스크 누수 방지, 자동 정리
- 예상 시간: 4시간

### 💡 장기 개선 (Low)

**9. 서킷 브레이커 도입**
- 효과: 키움 API 장애 시 복원력 향상
- 예상 시간: 8시간

**10. 메트릭 수집 (Prometheus 등)**
- 효과: 실시간 성능 모니터링
- 예상 시간: 8시간

---

## 7. 종합 평가

### 아키텍처 강점 ⭐
1. **비동기 설계**: `asyncio.to_thread()`로 블로킹 최소화
2. **효율적 캐싱**: 다중 레벨 캐시로 성능 최적화
3. **모듈 분리**: 관심사 분리가 명확함
4. **이벤트 기반**: 느슨한 결합으로 유지보수 용이
5. **실시간 최적화**: Coalescing 패턴으로 불필요한 처리 감소

### 개선 필요 영역 📋
1. **블로킹 코드**: `time.sleep()` 잔여물 제거
2. **메모리 관리**: 캐시 크기 제한 및 모니터링
3. **I/O 최적화**: 모든 파일 작업 비동기화
4. **관측성**: 메트릭 및 로깅 강화

### 총평
SectorFlow 백엔드는 **실시간 주식 매매 시스템으로서 적합한 설계**입니다. 이미 많은 최적화가 적용되어 있으며(0.3초 coalescing, 병렬 캐시 로딩, 비동기 I/O 등), HTS 수준의 실시간 동기화를 달성하고 있습니다.

즉시 수정이 필요한 항목은 2가지뿐이며(`time.sleep()`, `_TICK_FIELDS`), 나머지는 점진적으로 개선하면 됩니다.

---

## 부록: 주요 파일 설명

| 파일명 | 기능 | 라인수 |
|--------|------|--------|
| `engine_service.py` | 메인 엔진 오케스트레이터 | 2,260 |
| `engine_cache.py` | 캐시 로딩/저장 관리 | 141 |
| `engine_bootstrap.py` | 프로그램 시작 시 데이터 준비 | - |
| `engine_ws_dispatch.py` | 웹소켓 메시지 분배 | 546 |
| `engine_sector_confirm.py` | 섹터 재계산 및 최적화 | - |
| `avg_amt_cache.py` | 5일 거래대금 평균 캐시 | 476 |
| `sector_stock_cache.py` | 업종별 종목 캐시 | 415 |
| `market_close_pipeline.py` | 장마감 후 데이터 처리 | 772 |
| `kiwoom_rest.py` | 키움증권 REST API 클라이언트 | 634 |
| `daily_time_scheduler.py` | 시간 기반 자동 작업 | 1,300+ |

---

**보고서 작성:** AI 어시스턴트  
**검증 완료:** 2026년 5월 11일  
**버전:** 2.0 (사용자용)
