# SectorFlow 백엔드 디버깅 계획서

**작성일:** 2026년 5월 11일  
**목표:** 보고서에 식별된 문제점들을 단계별로 디버깅 및 수정  
**진행 방식:** 각 단계 승인 후 진행

---

## 문제점 요약 (총 5개)

| 우선순위 | 문제 | 파일 | 위험도 |
|---------|------|------|--------|
| 🚨 Critical | `time.sleep()` 블로킹 | `kiwoom_rest.py`, `industry_map.py` | 높음 |
| 🚨 Critical | `_TICK_FIELDS` 미정의 | `engine_account_notify.py` | 높음 |
| 🔶 High | 캐시 무한 증가 | `engine_service.py` (전역 변수) | 중간 |
| 🔶 High | 동기 I/O | `settings_file.py` | 중간 |
| 🔷 Medium | 메모리 모니터링 부재 | 전역 | 낮음 |

---

## 단계별 디버깅 계획

### 📌 단계 1: `_TICK_FIELDS` 상수 정의 (가장 간단, 가장 위험)

**목표:** 런타임 오류 방지  
**소요 시간:** 5분  
**리스크:** 매우 낮음 (상수 추가만)

**작업 내용:**
1. `engine_account_notify.py` 340번째 줄 주변 확인
2. `_TICK_FIELDS` 상수 정의 추가
3. 코드가 올바르게 참조하는지 검증

**예상 수정:**
```python
# engine_account_notify.py 상단에 추가
_TICK_FIELDS = ("cur_price", "change", "change_rate", "trade_amount", "strength")
```

**승인 요청:** ⬜ 이 단계를 진행하시겠습니까?

---

### 📌 단계 2: `time.sleep()` 블로킹 수정 (Critical)

**목표:** 이벤트 루프 블로킹 제거  
**소요 시간:** 1시간  
**리스크:** 중간 (키움 API 호출 로직 변경)

**작업 내용:**
1. `kiwoom_rest.py`의 모든 `time.sleep()` 위치 확인
   - 151번째 줄: 429 에러 대기
   - 165번째 줄: 재시도 대기
   - 192번째 줄: 토큰 재시도
   - 201번째 줄: 429 대기
2. `industry_map.py`의 `time.sleep()` 확인
   - 388번째 줄: 코스피/코스닥 간격
   - 425번째 줄: API 간격
3. 각 함수가 async인지 확인
4. `time.sleep()` → `await asyncio.sleep()`로 변경

**주의사항:**
- 함수가 `async def`가 아닌 경우 함수 시그니처도 함께 수정 필요
- 호출처에서 `await` 추가 필요
- REST API 호출은 동기식(`requests` 라이브러리)이므로 `asyncio.to_thread()`로 감싸는 것도 고려

**승인 요청:** ⬜ 이 단계를 진행하시겠습니까?

---

### 📌 단계 3: 캐시 크기 제한 구현 (High)

**목표:** 메모리 누수 방지  
**소요 시간:** 4시간  
**리스크:** 중간 (캐시 로직 변경)

**작업 내용:**
1. 캐시 사용 현황 분석
   - `_rest_radar_quote_cache`
   - `_latest_trade_amounts`
   - `_pending_stock_details`
   - `_snapshot_history`
2. LRU 캐시 클래스 구현 또는 `functools.lru_cache` 활용
3. 기존 딕셔너리 기반 캐시를 LRU로 교체 또는 래핑
4. 크기 제한 테스트 (1000개 등)

**예상 수정 방식:**
```python
# 방법 1: collections.OrderedDict 사용
from collections import OrderedDict

class LRUCache:
    def __init__(self, maxsize=1000):
        self.cache = OrderedDict()
        self.maxsize = maxsize
    
    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]
    
    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)
```

**승인 요청:** ⬜ 이 단계를 진행하시겠습니까?

---

### 📌 단계 4: 설정 파일 I/O 비동기화 (High)

**목표:** 파일 I/O 블로킹 제거  
**소요 시간:** 2시간  
**리스크:** 낮음 (단순 래핑)

**작업 내용:**
1. `settings_file.py`의 모든 파일 작업 확인
2. `load_settings()` 함수를 async 버전 추가 또는 `asyncio.to_thread()`로 래핑
3. `save_settings()` 함수 비동기화
4. 호출처 업데이트

**예상 수정:**
```python
# 변경 전 (동기):
def load_settings() -> dict:
    with open(_SETTINGS_PATH, "r") as f:
        return json.load(f)

# 변경 후 (비동기):
async def load_settings_async() -> dict:
    return await asyncio.to_thread(_sync_load_settings)

def _sync_load_settings() -> dict:
    with open(_SETTINGS_PATH, "r") as f:
        return json.load(f)
```

**승인 요청:** ⬜ 이 단계를 진행하시겠습니까?

---

### 📌 단계 5: 메모리 모니터링 추가 (Medium)

**목표:** 메모리 사용량 가시화  
**소요 시간:** 2시간  
**리스크:** 낮음 (관측 기능 추가)

**작업 내용:**
1. `psutil` 라이브러리 설치 확인 (없으면 추가)
2. 주기적 메모리 로깅 함수 구현
3. 메인 루프 또는 스케줄러에 통합
4. 로그 포맷 결정

**예상 수정:**
```python
# engine_loop.py 또는 daily_time_scheduler.py에 추가
import psutil
import asyncio

async def memory_monitor_loop():
    while True:
        await asyncio.sleep(300)  # 5분마다
        process = psutil.Process()
        mem = process.memory_info()
        logger.info(
            f"[메모리] RSS: {mem.rss/1024/1024:.1f}MB, "
            f"VMS: {mem.vms/1024/1024:.1f}MB, "
            f"Percent: {process.memory_percent():.1f}%"
        )
```

**승인 요청:** ⬜ 이 단계를 진행하시겠습니까?

---

## 진행 체크리스트

| 단계 | 문제 | 상태 | 승인자 | 완료일 |
|-----|------|------|--------|--------|
| 1 | `_TICK_FIELDS` 정의 | ⬜ 대기 | | |
| 2 | `time.sleep()` 수정 | ⬜ 대기 | | |
| 3 | 캐시 크기 제한 | ⬜ 대기 | | |
| 4 | 설정 I/O 비동기화 | ⬜ 대기 | | |
| 5 | 메모리 모니터링 | ⬜ 대기 | | |

---

## 회귀 테스트 계획

각 단계 완료 후 수행할 테스트:

### 단계 1 테스트
- [ ] 프로그램 정상 기동 확인
- [ ] `engine_account_notify.py` import 오류 없음 확인

### 단계 2 테스트
- [ ] 키움 API 연결 정상 작동
- [ ] 429 에러 발생 시 재시도 정상 동작
- [ ] 실시간 데이터 수신 중단 없음 확인

### 단계 3 테스트
- [ ] 캐시 1000개 이상 시 오래된 항목 삭제 확인
- [ ] 메모리 사용량 안정화 확인 (장시간 실행)

### 단계 4 테스트
- [ ] 설정 파일 읽기/쓰기 정상 동작
- [ ] 설정 변경 후 UI에 반영 확인

### 단계 5 테스트
- [ ] 로그에 메모리 사용량 기록 확인
- [ ] 5분 간격으로 로그 출력 확인

---

## 롤백 계획

각 단계별 롤백 방법:

1. **Git 사용:** 각 단계별로 커밋하여 문제 발생 시 해당 커밋으로 revert
2. **백업:** 수정 전 파일 백업 (`.bak` 확장자)
3. **Feature Flag:** 중요한 변경은 설정으로 on/off 가능하게 구현

```bash
# 롤백 명령어 예시
git revert <commit-hash>
# 또는
cp file.py.bak file.py
```

---

## 긴급 연락처

문제 발생 시:
- 로그 파일 위치: `backend/logs/`
- 디버그 모드: `DEBUG=1` 환경변수 설정
- 긴급 롤백: `git checkout HEAD~1`

---

**다음 행동:** 각 단계별 승인을 기다립니다. 시작하실 단계를 알려주세요.
