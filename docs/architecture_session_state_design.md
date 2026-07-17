# 장 상태 관리 아키텍처 설계 검토 (2026-07-16)

> **상태**: 설계 검토 완료. 안 D(하이브리드) 선택. 코드 수정 전 사용자 승인 대기.
> **관련 문서**: `docs/krx_receive_rate_missing_investigation.md` (타이머 미실행 근본 원인 조사)
> **관련 원칙**: P10(SSOT), P16(살아있는 경로), P20(폴백 금지), P24(단순성)

---

## 1. 배경

SectorFlow는 장 상태 관리를 위해 두 가지 방식을 사용 중:

1. **로컬 타이머 11개** (daily_time_scheduler.py:733-743): 08:00, 08:30, 08:40, 08:50, 09:00, 15:20, 15:30, 15:40, 16:00, 18:00, 20:00 시점에 `call_later` 예약 → `_broadcast_market_phase()` 호출
2. **JIF** (engine_ws_dispatch.py:204): 증권사 push 장운영정보 — 현재 서킷브레이커/사이드카만 처리, 장 상태 전환 미처리

**문제**: 08:00/09:00 타이머가 선택적으로 미실행되어 `state.market_phase["krx"]`가 미갱신 → KRX 수신률 0/0 고정 (HANDOVER.md "다음 세션 진행 대기" 참조). 타이머 신뢰성 문제를 구조적으로 해결하기 위해 장 상태 관리 방식 전환 검토.

---

## 2. 4가지 설계안 비교표

| 항목 | 안 A (표시 주기 + 4 타이머) | 안 B (전부 주기) | 안 C (이중화) | **안 D (하이브리드 — JIF + 주기)** |
|---|---|---|---|---|
| **장 상태 갱신 1순위** | 주기적 계산 | 주기적 계산 | 주기적 계산 + 타이머 | **JIF push** |
| **보완 경로** | 4개 타이머 (08:00/09:00/15:30/20:00) | 없음 | 동일 부작용 중복 | 주기적 시간 계산 (10초) |
| **타이머 수** | 4개 | 0개 | 4개 + 주기 태스크 | **0개** |
| **부작용 트리거** | 4 타이머 내부 | 주기 태스크 내 페이즈 변경 감지 | 양쪽에서 감지 (멱등성 가드 필요) | JIF 전환 이벤트 + 주기 태스크 페이즈 변경 감지 |
| **P10 (SSOT)** | 부분 위험 (표시/작업 2곳 판단) | 준수 (단일 함수) | 위험 (2곳 동일 판단) | **준수** (JIF는 예외+전환, 시간이 SSOT) |
| **P16 (살아있는 경로)** | 4 타이머 미실행 시 부작용 누락 (HANDOVER 문제 잔존) | 준수 (주기 태스크 단일 경로) | 준수 (이중화 보완) | **준수** (JIF 끊김 시 시간 기반 보완) |
| **P20 (폴백 금지)** | 준수 | 준수 | 위험 (멱등성 가드 = 폴백 성격) | **준수** (JIF는 1순위 이벤트, 폴백 아님) |
| **P24 (단순성)** | 중간 (책임 분리는 단순, 타이머 잔존) | 가장 단순 (단일 경로) | 가장 복잡 (이중화 로직) | **중간** (JIF 핸들러 + 주기 태스크) |
| **표준 부합** | 부분 (표시/작업 분리는 베스트 프랙티스) | 부분 (단일 사용자 로컬 앱에서 허용) | 비권장 (복잡도 > 이득) | **가장 부합** (이벤트 1순위 + 시간 보완) |
| **HANDOVER 타이머 문제 해결** | 미해결 (4 타이머 잔존) | 해결 (타이머 0개) | 부분 해결 (이중화로 보완) | **해결** (타이머 0개, JIF가 1순위) |

---

## 3. 최종 선택: 안 D (하이브리드 — JIF 1순위 + 현재 시간 기반 보조)

### 선택 근거

1. **표준 베스트 프랙티스 부합**: NexusFi Academy "이벤트 루프 + 하우스키핑 타이머" 패턴. 거래소 push를 1순위, 시간 기반을 보완으로 사용하는 것이 금융권 표준.
2. **KRX JIF API 표준 활용**: KRX가 제공하는 장운영정보 WebSocket push (H0STMKO0/H0NXMKO0)를 현재 미활용. 이는 거래소 ground truth이므로 가장 신뢰할 수 있는 상태 소스.
3. **타이머 신뢰성 문제 근본 해결**: 타이머 0개로 HANDOVER.md에 문서화된 08:00/09:00 타이머 미실행 문제를 구조적으로 제거.
4. **WS 끊김 시에도 동작**: JIF 수신 불가 시 주기적 시간 계산이 살아있는 경로로 동작 (P16 준수).
5. **예외 상황 즉시 반영**: 조기 마감, 임시 정지 등 거래소 예외를 JIF가 즉시 push (시간 기반만으로는 불가능).

### 안 A/B/C 미선택 사유

- **안 A**: 4 타이머 신뢰성 문제가 잔존하여 HANDOVER.md 근본 문제 미해결.
- **안 B**: 단일 사용자 로컬 앱에서는 허용 가능하나, KRX JIF API를 활용하지 않아 표준에서 벗어남. 부작용 10초 지역도 표준에서는 이벤트 기반 권장.
- **안 C**: 복잡도 증가가 이득보다 큼. 멱등성 가드 로직이 P20(폴백 금지) 위반 우려.

---

## 4. 안 D 동작 원리

### 4-1. 앱 기동 시

```
start_daily_time_scheduler()
  → calc_timebased_market_phase()  # 현재 KST 시각 기준 장 상태 계산
  → state.market_phase 갱신
  → _broadcast_market_phase()      # WS 브로드캐스트 + 페이즈 변경 감지
```

- JIF 수신 전 공백 구간 보완. 엔진 기동 직후 즉시 현재 시간 기반 상태 반영.
- 기존 `start_daily_time_scheduler()` line 1043-1050 로직 유지.

### 4-2. JIF 수신 시 (1순위)

```
engine_ws_dispatch._handle_jif(data)
  → jangubun/jstatus 파싱
  → JIF 페이즈 맵 조회 (jangubun/jstatus → KRX/NXT 페이즈명)
  → state.market_phase 덮어쓰기  # 거래소 ground truth
  → _broadcast_market_phase()     # WS 브로드캐스트 + 페이즈 변경 감지 → 부작용 트리거
```

- JIF가 장 상태 전환 이벤트를 push하면 즉시 `state.market_phase` 갱신.
- 서킷브레이커/사이드카는 기존 로직 유지 (krx_alert 필드만 갱신).
- **현재 `_handle_jif()`는 서킷브레이커만 처리** (engine_ws_dispatch.py:212 "그 외 jangubun/jstatus 조합은 미처리") → **장 상태 전환까지 확장 필요** (섹션 5 참조).

### 4-3. JIF 미수신 시 (보완)

```
주기 태스크 (10초 간격)
  → calc_timebased_market_phase()
  → 이전 state.market_phase와 비교
  → 변경 시에만 state 갱신 + _broadcast_market_phase()
```

- WS 연결 끊김, JIF 미수신, 네트워크 지연 시 시간 기반 계산이 보완.
- 페이즈 변경 감지 시 부작용 트리거 (JIF 경로와 동일 로직 재사용 — P10 SSOT).
- 10초 주기: 분 단위 경계에서 최대 10초 내 반영. `calc_timebased_market_phase()`는 순수 함수(거래일 캐시 조회만)라 CPU 부하 무시 가능.

### 4-4. 타이머: 전면 제거 (0개)

- `schedule_ws_subscribe_timers()` 내 11개 market-phase 전환 타이머 (line 733-743) 제거.
- `confirmed_download_time` 타이머 (line 713-722)는 별도 기능이므로 유지.
- 부작용 트리거(WS 연결/해제, 업종 재계산, 구독 변경)는 JIF + 주기 태스크의 페이즈 변경 감지에서 수행.

### 4-5. 부작용 트리거 (4개 전환, 기존 로직 유지)

| 전환 | 트리거 함수 | 부작용 |
|---|---|---|
| NXT "프리마켓" 진입 | `_on_nxt_premarket_start()` + `_on_ws_subscribe_start()` | 업종 재계산(KRX 단독 제외) + WS 연결 + 실시간 필드 초기화 + GC 비활성화 + 수신율 게이트 리셋 |
| KRX "정규장" 진입 | `_on_krx_market_open()` | 업종 재계산(전체 종목) + KRX 단독 종목 재구독 |
| KRX "체결 정산" 진입 | `_on_krx_after_hours_start()` | 업종 재계산 + KRX 단독 종목 구독 해지 |
| NXT "장마감" 진입 | `_on_ws_subscribe_end()` | WS 연결 해제 + 전체 구독 해지 + GC 정상화 + 수신율 게이트 해제 |

- `_broadcast_market_phase()` 내 페이즈 변경 감지 로직 (line 532-545) 유지.
- JIF 경로와 주기 태스크 경로 모두 동일 `_broadcast_market_phase()` 호출 → 단일 부작용 트리거 경로 (P10/P16).

---

## 5. JIF 핸들러 확장 필요 사항

### 현재 상태

`engine_ws_dispatch.py:_handle_jif()` (line 204-246):
- jangubun 1/2 (코스피/코스닥) + jstatus 61~71 → 서킷브레이커/사이드카만 처리
- "그 외 jangubun/jstatus 조합은 미처리" (line 212) — 장 상태 전환 미처리

### 확장 필요 사항

1. **JIF 페이즈 맵 구성**: jangubun(1=코스피, 2=코스닥, 3=NXT?) + jstatus(장운영 코드) → KRX/NXT 페이즈명 매핑 테이블.
   - KRX jstatus 코드: 장개시, 장전 시간외, 동시호가 접수, 시가 동시호가, 정규장, 종가 동시호가, 체결 정산, 장후 시간외, 시간외 단일가, 장 종료, 장마감 등
   - NXT jstatus 코드: 프리마켓, 정규장 준비, 메인마켓, 조기 마감, 단일가 매매, 애프터마켓, 애프터마켓 지속, 장마감 등
   - **정확한 jstatus 코드값은 KRX 개발 문서 또는 실제 JIF 수신 로그 확인 필요** (추측 금지 — 규칙 1).

2. **`_handle_jif()` 확장**:
   - 서킷브레이커/사이드카 처리 (기존) + 장 상태 전환 처리 (신규) 분기
   - 장 상태 전환 시 `state.market_phase` 갱신 + `_broadcast_market_phase()` 호출
   - 기존 서킷브레이커 로직은 `krx_alert` 필드만 갱신하므로 페이즈 갱신과 충돌 없음

3. **JIF 페이즈 맵 검증**:
   - 실제 런타임에서 JIF 수신 시 jangubun/jstatus 값 로그 출력 → 맵 정확성 검증
   - 누락된 jstatus 코드 발견 시 맵 추가 (폴백 아닌 실제 데이터 기반 보완)

### 주의점

- JIF가 모든 장 상태 전환을 커버하는지 사전 검증 필요. 일부 전환(예: 08:40 동시호가 접수)은 JIF에 포함되지 않을 수 있음 → 해당 전환은 주기적 시간 계산이 보완.
- JIF 수신 지연 시 주기적 시간 계산이 먼저 페이즈를 갱신할 수 있음 → JIF 수신 시 동일 페이즈면 no-op, 다르면 JIF가 우선 (거래소 ground truth).

---

## 6. 표준 아키텍처 검토 근거

### 6-1. NexusFi Academy (트레이딩 자동화 교육 자료)

- **"Trading Automation Fundamentals"**: "이벤트 루프 패턴이 해결책... 핸들러를 등록하고 이벤트 루프가 이벤트를 전달... 하우스키핑 타이머(세션 종료, 조정, 헬스 체크)는 이벤트 루프 내에서 허용."
- **"Market Data Handling"**: "세션 open/close 전환을 깨끗하게 처리... Pre-market vs RTH vs post-market 상태 변경... Exchange-level trading halts and circuit breakers... '데이터 없음 = 시장 닫힘' vs '데이터 없음 = 무언가 고장' 구분 필요."
- **핵심 적용**: JIF를 세션 전환 이벤트로, 시간 기반을 하우스키핑 보완으로 사용.

### 6-2. KRX JIF API (한국거래소 장운영정보)

- KRX 실시간 시장정보: 장운영정보 WebSocket push API 제공 (H0STMKO0=KRX, H0NXMKO0=NXT, H0UNMKO0=통합).
- 출처: koreainvestment/open-trading-api GitHub, kenshin579/korea-investment-stock 문서.
- **핵심 적용**: 거래소가 push하는 장운영정보를 장 상태 1순위 소스로 활용 — 이는 거래소 ground truth이므로 가장 신뢰할 수 있음.

### 6-3. Deribit Options Strategy 사례 (gist 리뷰)

- 12+ 타이머 사용 → "implicit ordering dependencies" 문제 보고 (타이머 간 mutable state 공유).
- "타이머 기반 모델은 이 규모에서 실제로 괜찮음. 이벤트 소싱은 과잉." — 단, "스탑로스는 모든 quote tick에서 평가" — 핵심 작업은 이벤트 기반 권장.
- **핵심 적용**: SectorFlow의 11개 타이머는 동일한 `state.market_phase` 공유 → 타이머 간 순서 의존성 문제 발생 가능. 타이머 제거로 근본 해결.

### 6-4. trading-state 라이브러리 (PyPI)

- "passive: never schedules, polls, or talks to an exchange. The caller owns the network."
- "All reads are synchronous and return immediately."
- **핵심 적용**: `calc_timebased_market_phase()`가 동일 철학 — 순수 함수, 부작용 없음, 호출자가 상태 갱신 시점 결정.

### 6-5. CCXT Pro (암호화폐 거래소 통합 라이브러리)

- `fetchStatus` (REST) → `watchStatus` (WebSocket) 전환 패턴.
- "WebSocket: Real-time monitoring, live price feeds... More lenient (continuous stream)."
- **핵심 적용**: REST 폴링 → WebSocket push 전환이 표준 진화 방향. SectorFlow도 JIF push 활용이 동일 방향.

### 6-6. Sierra Chart ACSIL (선물 자동매매)

- "상태 머신을 primary source of truth로 취급... 매 함수 호출마다 실제 위치/주문과 조정."
- "세션 경계 감지 시 상태 리셋: 일일 P&L 카운터, 거래 횟수 제한, 이전 세션 기준 가격 로직."
- **핵심 적용**: 장 상태 전환 시 부작용(업종 재계산, 구독 변경)이 상태 머신 전환에 연결되어야 함 — 안 D의 `_broadcast_market_phase()` 페이즈 변경 감지가 이를 담당.

---

## 7. 다음 세션 세부 수정 계획 수립을 위한 참고 사항

### 7-1. 사전 검증 필요 항목 (코드 수정 전)

1. **JIF jstatus 코드 맵핑**: 실제 런타임 로그에서 JIF 수신 시 jangubun/jstatus 값을 확인하여 페이즈명 맵 구성. 추측 금지 (규칙 1).
   - 확인 방법: `_handle_jif()`에 임시 DEBUG 로그 추가 (jstatus 전체 출력) 후 장 시작 시점 런타임 관찰.
   - 또는 KRX 개발 문서/증권사 API 문서에서 jstatus 코드 정의 조회.

2. **JIF 커버리지 확인**: JIF가 모든 장 상태 전환(11개 시점)을 push하는지, 일부만 push하는지 확인.
   - 일부만 push 시: 해당 전환은 주기적 시간 계산이 보완 (안 D 설계대로).

3. **NXT 09:00:30 문제**: 현재 `NXT_PREP_NONE_END = (9, 0)` — 09:00:00부터 "메인마켓" 산정. 실제 NXT 메인마켓은 09:00:30 시작 (사용자 보고).
   - `calc_timebased_market_phase()`가 `now.hour * 60 + now.minute` 사용 (초 무시) → 09:00:30 지원하려면 초 단위 판별 또는 30초 오프셋 상수 추가 필요.
   - **이번 전환 작업에 포함할지 사용자 결정 필요**.

4. **WS 초기화 07:55 / WS 구독 07:59 조정**: 현재 코드에 07:55/07:59 시각이 존재하지 않음. WS 구독은 08:00 NXT "프리마켓" 진입 시 `_on_ws_subscribe_start()`로 시작.
   - WS 연결을 08:00보다 5분~1분 일찍 시작하려면 별도 트리거 필요.
   - **이번 전환 작업에 포함할지 사용자 결정 필요**.

### 7-2. 예상 수정 파일 (안 D 적용 시)

**백엔드**:
- `engine_ws_dispatch.py` — `_handle_jif()` 확장 (장 상태 전환 처리 추가, JIF 페이즈 맵)
- `daily_time_scheduler.py` — 11개 타이머 제거, 주기 태스크 추가, `_broadcast_market_phase()` 책임 유지
- `engine_loop.py` — 주기 태스크 기동/종료 연결 (또는 별도 태스크)
- `tests/test_daily_time_scheduler.py` — 타이머 테스트 수정, 주기 태스크 테스트 추가
- `tests/test_engine_ws_dispatch.py` — JIF 장 상태 전환 테스트 추가

**프론트엔드**: 수정 없음 (WS "market-phase" 이벤트 구조 동일)

### 7-3. 단계 분할 제안 (세션당 1단계 — 규칙 0-1)

작업량이 많으므로 세션당 1단계로 분할 권장:

- **1단계**: JIF jstatus 코드 맵핑 사전 검증 (런타임 로그 확인 또는 문서 조회) — 코드 수정 없음, 조사 only.
- **2단계**: JIF 핸들러 확장 (`_handle_jif()` 장 상태 전환 처리 추가) + 테스트.
- **3단계**: 주기 태스크 추가 + 11개 타이머 제거 + 테스트.
- **4단계**: 런타임 기동 검증 + 통합 테스트.

### 7-4. 아키텍처 원칙 점검 체크리스트 (수정 시 적용)

- [ ] **P10 (SSOT)**: `state.market_phase` 갱신 경로가 JIF + 주기 태스크 2곳이나, 동일 `calc_timebased_market_phase()` / JIF 맵 기반이므로 단일 진실 소스 유지.
- [ ] **P16 (살아있는 경로)**: JIF 끊김 시 주기 태스크가 살아있는 경로. 주기 태스크 중단 시 JIF가 살아있는 경로. 양쪽 모두 중단 시에만 상태 갱신 중단 (단일 장애점 제거).
- [ ] **P20 (폴백 금지)**: JIF는 폴백이 아닌 1순위 이벤트 소스. 주기 태스크는 보완이지 폴백 아님. silent `except: pass` 금지.
- [ ] **P24 (단순성)**: 타이머 0개, 주기 태스크 1개, JIF 핸들러 1개. 함수 50줄 이하, 파일 500줄 이하 유지.

### 7-5. 승인 대기 항목

- 안 D 적용 승인 (사용자 실행 지시어 대기 — 규칙 0).
- NXT 09:00:30 수정 포함 여부.
- WS 07:55/07:59 조정 포함 여부.
- 단계 분할(4단계) 진행 방식 승인.
