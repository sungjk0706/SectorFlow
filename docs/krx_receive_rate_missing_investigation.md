# KRX 수신률 미표시 문제 조사 보고서 (NXT 프리마켓 → 정규장 전환 시)

## 조사 개요
- **발생일**: 2026-07-16
- **현상**: NXT 프리마켓 08:00 이전 기동 후 10:50경 확인 시 KRX 수신률 표시 없음 (KRX 0/0, NXT 100% 고정 2시간 18분)
- **기대 동작**: 09:00 정규장 시작 후 KRX 수신률도 표시되어야 함
- **복구**: 10:52 앱 재기동 후 정상 복구
- **조사 세션**: 3회 (1차: 코드+로그 조사, 2차: git 이력 비교 조사, 3차: 타이머 미실행 원인 심층 추적)
- **상태**: 조사 진행 중. 08:00/09:00 타이머 미실행 확정, 08:30 타이머 정상 실행 확정. 타이머 미실행 근본 원인은 여전히 미확인 (DEBUG 로그 추적 불가 → INFO 승격 필요).

---

## 타임라인 (2026-07-16)

| 시간 | 이벤트 | 근거 |
|------|--------|------|
| 07:50:43 | 앱 기동, `장 상태 초기화: KRX=장개시전, NXT=장개시전` | 로그 line 3830 |
| 07:50:44 | 임계값 통과 (KRX: 100.0%, NXT: 100.0%) — 비-WS 구간이라 즉시 통과 | 로그 line 3850 |
| 08:00 (예상) | **08:00 market_phase 타이머 미실행** — `_broadcast_market_phase()` 호출 로그 부재 | 로그 전수 확인 |
| 08:01:59 | 자동매매 시간 전환 타이머 정상 실행 — `매도 구간 이탈` 로그 출력 | 로그 (별도 타이머 시스템) |
| 08:00~08:28 | **로그 28분 공백** — 08:00 타이머 미실행으로 market_phase 미갱신 → WS 미연결 → 틱 없음 → INFO 로그 없음 (정상) | — |
| 08:29:59 | **08:30 market_phase 타이머 정상 실행** — `_broadcast_market_phase()` 호출, 누적 페이즈 변경(장개시전→장전 대기/프리마켓) 감지 → `_on_nxt_premarket_start()` 트리거 | 로그 line 3882 |
| 08:30:00 | WS 연결 + 보유종목 구독(2종목) + 필터 종목 구독(132종목) + 0B 자동 구독 완료 | 로그 line 3908~3934 |
| 08:30:00 | 수신율 갱신 시작 — `KRX: 0/0 (0.0%), NXT: 5/134 (3.7%)` (NXT-only 구간 정상) | 로그 line 3952 |
| 08:34:36 | NXT 100% 도달 — `KRX: 0/0 (0.0%), NXT: 134/134 (100.0%)` | 로그 line 4178 |
| 08:45:05 | 마지막 호가·프로그램매매 구독 해지 로그 | 로그 line 4310 |
| 08:45~09:00 | **로그 15분 공백** — 08:50 NXT 프리마켓 종료 후 양 시장 비거래 구간(정규장 준비/시가 동시호가)이라 틱 없음 → INFO 로그 없음이 정상 (3차 조사 확정) | — |
| 09:00 (예상) | **09:00 market_phase 타이머 미실행** — `_broadcast_market_phase()` 호출 로그 부재 → `_on_krx_market_open()` 미호출 | 로그 전수 확인 |
| 09:00:19 | 호가·프로그램매매 구독 재개 (정상 — 별도 경로) | 로그 line 4312 |
| 09:07:59 | 대한항공 매도 + SK이노베이션 매수 — 틱 정상 수신 확인 | 로그 line 4588~4626 |
| 09:00~10:52 | **수신율 갱신 로그 전혀 없음** (약 2시간 18분) | — |
| 10:52:32 | 앱 재기동, `장 상태 초기화: KRX=정규장, NXT=메인마켓` | 로그 line 5722 |
| 10:52:53 | 임계값 통과 (KRX: 97.2%, NXT: 97.0%) — 이후 KRX/NXT 분리 수신율 정상 표시 | 로그 |

---

## 확인된 사실 (코드 + 로그 기반)

### 사실 1. 09:00 `_on_krx_market_open()` 미호출 (확정)
- 로그 전수 검색 결과 `[스케줄] KRX 정규장 진입 (09:00)` INFO 로그 부재
- 코드상 `_on_krx_market_open()` 호출 시 반드시 해당 로그 출력 (<ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" /> line 361)
- **호출되지 않았음이 확정**

### 사실 2. `state.market_phase["krx"]` 미갱신 (확정)
- `_on_krx_market_open()`은 `_broadcast_market_phase()` 내 페이즈 변경 감지 시에만 호출 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" lines="528-533" />)
- `_broadcast_market_phase()`가 09:00에 실행되지 않았음 → `state.market_phase["krx"]`가 "시가 동시호가" (또는 이전 값)로 유지
- `state.market_phase["krx"]` 갱신 경로는 단 2곳만 존재 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" lines="523-524, 1036-1037" />):
  1. `_broadcast_market_phase()` (line 523-524) — 타이머 기반
  2. `start_daily_time_scheduler()` (line 1036-1037) — 기동 시 1회만
- **타이머 미실행 = market_phase 미갱신 확정**

### 사실 3. `is_nxt_only_window()` True 유지 (확정)
- `is_nxt_only_window()`는 `state.market_phase` 기반 판단 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" lines="181-193" />)
- `krx`가 KRX_INACTIVE_PHASES("시가 동시호가" 포함) + `nxt`가 NXT_ACTIVE_PHASES → True 유지
- **정규장임에도 NXT-only 구간으로 잘못 판단 확정**

### 사실 4. KRX 수신률 0/0 고정 원인 (확정)
- `get_sector_summary_inputs()`에서 `is_nxt_only_window()`=True → KRX 단독 종목 필터링 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/sector_data_provider.py" lines="37-41" />)
- `krx_codes` 빈 리스트 반환
- `_calc_market_receive_rate(codes=[], ...)` → total=0 → `{"received": 0, "total": 0, "pct": 0.0}` (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/pipelines/pipeline_compute.py" lines="156-158" />)
- **KRX 수신률 0/0 고정 원인 확정**

### 사실 5. 틱은 정상 수신 중 (확정)
- 09:07:59 대한항공 매도 + SK이노베이션 매수 발생 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/logs/trading_2026-07-16.log" lines="4588-4626" />)
- 08:30에 이미 132종목 0B 구독 완료 상태로 유지 (재구독 불필요)
- `_handle_real_01_tick()`에서 `_receive_rate_dirty = True` 세팅 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/pipelines/pipeline_compute.py" lines="620-625" />)
- **틱 수신 자체는 정상, 계산만 안 되는 것 확정**

### 사실 6. KRX 0B 재구독 안 됨 (확정)
- `_on_krx_market_open()` 미호출 → `subscribe_sector_stocks_0b()` 미실행 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" lines="365-367" />)
- 다만 08:30에 이미 132종목 0B 구독 완료 상태이므로, KRX 단독 종목도 0B 틱 수신 중
- **재구독 자체는 안 됐지만, 0B 틱 수신에는 영향 없음 (이미 구독된 상태 유지)**

### 사실 7. 단일 원인에서 연쇄 발생 (확정)
- 타이머 미실행 → `market_phase` 미갱신 → `is_nxt_only_window()` True 유지 → 2개 현상 동시 발생:
  1. KRX 0B 재구독 안 됨 (구독 문제)
  2. KRX 수신률 0/0 유지 (계산 문제)
- **틱 자체는 08:30 구독된 132종목에서 들어오고 있었음. 구독이 안 돼서 틱이 없었던 것이 아님**

### 사실 8. 분리 작업(1·2·3단계) 자체는 구독 로직 미변경 (확정)
- 3단계 커밋(`bcab27c`) diff에서 `engine_ws_reg.py`, `engine_ws.py`, `ws_subscribe_control.py` 변경 없음
- `sector_data_provider.py`는 `krx_codes`/`nxt_codes` 분리 반환만 추가 (기존 `all_codes` 로직 유지)
- `pipeline_compute.py`는 수신률 집계 분리만 (구독 로직 미관여)
- **분리 작업이 구독 로직에 미치는 영향 없음 확정**

### 사실 9. 09:00 타이머 예약 코드는 정상 존재 (확정)
- `schedule_ws_subscribe_timers()` 내 11개 시점 타이머 예약 (08:00~20:00) (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" lines="724-734" />)
- 09:00 포함: `(9, 0, "09:00")`
- `delay_mp > 0 and loop` 조건에서 `loop.call_later(max(delay_mp, 1), _broadcast_market_phase)` 예약
- **코드상 09:00 타이머 예약은 정상. 런타임에서 실행되지 않은 것이 문제**

### 사실 10. JIF 핸들러는 market_phase 갱신 안 함 (확정)
- `_handle_jif()`는 서킷브레이커/사이드카 alert만 처리 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_ws_dispatch.py" lines="204-230" />)
- docstring 명시: "장운영 페이즈 전환은 앱 내부 시계 로직(_broadcast_market_phase)이 담당 (P10 SSOT)"
- **JIF 이벤트로 market_phase 갱신하는 폴백 경로 없음 확정**

### 사실 11. 08:00 타이머도 미실행 — 08:30 타이머가 대신 처리 (3차 조사 확정)
- 08:29:59.899에 "NXT 프리마켓 진입 (08:00)" 로그 출력 (로그 line 3882)
- 메시지는 "08:00"이지만 **실제 실행 시각은 08:29:59** — 08:00 타이머가 아니라 **08:30 타이머가 실행**되어 `_broadcast_market_phase()`가 누적된 페이즈 변경(장개시전 → 장전 대기/프리마켓)을 한 번에 감지한 것
- 08:00~08:30 사이 28분간 로그 공백도 이로 설명됨: 08:00 타이머 미실행 → `market_phase` 미갱신 → `is_ws_subscribe_window()` False → WS 미연결 → 틱 없음 → INFO 로그 없음
- **08:00 타이머 미실행 확정, 08:30 타이머 정상 실행 확정**

### 사실 12. 자동매매 타이머는 정상 실행 — 같은 루프에서 일부만 실패 (3차 조사 확정)
- 08:01:59.972에 `[스케줄] 자동매매 시간 전환 — 매도 구간 이탈` 로그 정상 출력
- 이것은 `schedule_auto_trade_timers()`로 예약된 **별도 타이머 시스템** (같은 이벤트 루프, 다른 핸들 리스트)
- **같은 asyncio 이벤트 루프에서 다른 타이머는 정상 실행되고 있었음 확정**
- → 이벤트 루프 전체 블록이 아니라 `ws_subscribe_timer_handles` 계열 타이머만 선택적으로 미실행

### 사실 13. 08:45~09:00 로그 15분 공백은 이벤트 루프 블록이 아님 (3차 조사 확정)
- 08:50에 NXT 프리마켓 종료 → "정규장 준비" 구간 진입. KRX도 "시가 동시호가" 구간으로 거래 없음
- **08:50~09:00은 양 시장 모두 비거래 구간이라 틱이 없고**, 틱 처리 로그가 INFO 레벨에서 출력되지 않는 것이 정상
- 08:45~08:50 공백도 동적 구독 변경이 없으면(매수 후보 변동 없음) INFO 로그가 없는 것이 정상
- compute loop, LS 커넥터, gc 모두 `await` 기반으로 이벤트 루프 블록 경로 없음 확인
- **15분 공백 = 자연스러운 현상, 이벤트 루프 블록 아님 확정**

### 사실 14. 타이머 예약 로그가 DEBUG 레벨이라 추적 불가 (3차 조사 확정)
- `schedule_ws_subscribe_timers()` 내 타이머 예약 로그가 `logger.debug()` 레벨 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" lines="730-734" />)
- INFO 로그에는 타이머 예약/실행 추적 정보가 전혀 남지 않음
- **타이머가 실제로 예약되었는지, 재호출되었는지, 실행되었는지를 로그로 확인할 수 없음**
- → DEBUG → INFO 로그 승격이 원인 특정의 전제 조건

### 사실 15. 설정 변경(PATCH) 경로 전수 추적 — 07:50~09:00 사이 변경 없음 (3차 조사 확정)
- PATCH HTTP 요청: 07:50~09:00 사이 **0건** (마지막 PATCH는 03:08)
- `_apply_pending_settings_on_startup()`: 보류 설정 없음 (로그 부재로 확인)
- `refresh_engine_integrated_system_settings_cache()`: 08:02에 실행됐지만 `schedule_ws_subscribe_timers()` 호출하지 않음 (<ref_file file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/engine_config.py" /> line 46-93 확인)
- **`schedule_ws_subscribe_timers()`는 07:50:43 기동 시 1회만 호출된 것으로 확인**

### 사실 16. 타이머 핸들 리스트 교체/손실 경로 없음 (3차 조사 확정)
- `state.ws_subscribe_timer_handles`에 대한 `=` 대입은 테스트 파일에만 존재
- 프로덕션 코드에서는 `.clear()`, `.append()`만 사용 — 리스트 객체 자체가 교체되는 경로 없음
- 타이머 취소 코드: `schedule_ws_subscribe_timers()` 시작부와 `stop_daily_time_scheduler()`만 존재, 둘 다 호출되지 않음
- **코드상 타이머 핸들 손실/교체 경로 없음 확정**

---

## 확인 안 된 것 (다음 세션 조사 필요)

### 미확인 1. 08:00, 09:00 타이머만 선택적 미실행의 근본 원인 ⭐⭐⭐ (최고 중요도)
- **중요도**: P10(SSOT), P16(살아있는 경로) 핵심 위반
- **현상**: 같은 이벤트 루프, 같은 `call_later` 함수, 같은 핸들 리스트에 있는 타이머 중 08:00과 09:00만 미실행. 08:30 타이머와 자동매매 타이머는 정상 실행 (사실 11, 12)
- **3차 조사로 배제된 가능성**:
  - 이벤트 루프 전체 블록 — 아님 (자동매매 타이머 정상 실행, 사실 12)
  - 타이머 핸들 리스트 교체/손실 — 코드상 경로 없음 (사실 16)
  - 설정 변경에 의한 타이머 재예약 — 07:50~09:00 사이 설정 변경 없음 (사실 15)
  - 15분 로그 공백 = 이벤트 루프 블록 — 아님 (사실 13, 비거래 구간 정상)
- **여전히 남은 가능성**:
  - `schedule_ws_subscribe_timers()` 재호출 (DEBUG 로그로 인해 추적 불가, 사실 14) — 재호출 시 08:00 타이머는 `delay_mp <= 0`으로 재예약되지 않고 08:30/09:00은 재예약됨. 그 후 09:00 이후 다시 재호출 시 09:00 타이머도 `delay_mp <= 0`으로 재예약되지 않음. **하지만 재호출을 트리거할 코드 경로를 찾지 못함**
  - asyncio `call_later` 타이머 관리 이슈 (macOS/Python 3.12, KqueueSelector) — 하지만 08:30 타이머 정상 실행이므로 단순 플랫폼 버그 단정 어려움
- **P10/P16 관점**: `market_phase` 갱신이 타이머 단일 경로에만 의존 → 타이머 실패 시 폴백 없음 = P16 위반

### 미확인 2. `schedule_ws_subscribe_timers()` 재호출 여부 ⭐⭐⭐ (최고 중요도)
- **중요도**: 미확인 1의 핵심 분기점
- **현상**: 타이머 예약 로그가 DEBUG 레벨이라 (사실 14) 재호출 여부를 로그로 확인 불가
- **조사 필요 항목**:
  - DEBUG → INFO 로그 승격 후 재발 시 재호출 여부 추적
  - 재호출 트리거 가능한 모든 경로 전수 추적 (현재 코드상 찾지 못함)

### 미확인 3. 분리 작업 이전 구독 로직과 현재 구독 로직의 차이 ⭐ (보통)
- **중요도**: 회귀 여부 확인
- **현상**: 과거에는 09:00 KRX 종목수 표시가 정상 동작했다는 사용자 보고
- **조사 필요 항목**:
  - `aba9e92` (재계산 타이머 3개 통합) 이전: 09:00 전용 타이머 존재 (`_krx_open_wrapper`)
  - `076a66b` (is_ws_subscribe_window market_phase 전환) 이후: 09:00 전용 타이머 제거, `_broadcast_market_phase()` 내 페이즈 변경 감지로 통합
  - **과거(7902640)에는 09:00 전용 타이머가 독립 존재 → 현재는 market_phase 타이머에 의존**
  - 이 의존성 변경이 타이머 미실행과 관련 있는지 추가 추적 필요
- **P10/P16 관점**: 타이머 통합으로 단일 장애점(single point of failure) 증가 가능성

### 미확인 4. JIF 경계 이벤트 핸들러에서 market_phase 갱신 여부 ⭐ (보통)
- **중요도**: P16 폴백 경로 부재 확인
- **현상**: JIF 핸들러는 alert만 처리, market_phase 갱신 안 함 (사실 10)
- **조사 필요 항목**:
  - 과거 커밋(`9e3944f` JIF 처리 단순화)에서 JIF가 market_phase 갱신하던 로직이 제거되었는지
  - JIF를 폴백 경로로 활용 가능성 검토 (수정 방안 수립 시)

---

## P10/P16 관점 종합 검토

### P10 (SSOT) 위반 가능성
- `state.market_phase`가 시간 기반 타이머에만 의존하여 갱신
- 타이머 실패 시 `is_nxt_only_window()`가 잘못된 값을 반환
- 이 잘못된 값이 `get_sector_summary_inputs()`와 Phase 1 임계값 게이트 양쪽에 영향
- **단일 진실 소스가 타이머에 의존적 → P10 취약**

### P16 (살아있는 경로) 위반 확정
- 타이머 실패 시 `market_phase`를 갱신하는 폴백 경로 없음
- JIF 핸들러도 market_phase 갱신 안 함 (사실 10)
- **`_broadcast_market_phase()` 단일 경로만 존재 → P16 위반**

### P21 (사용자 투명성) 위반
- 타이머 미실행 → KRX 수신률 0/0이 2시간+ 유지되어도 사용자에게 알림 없음
- "왜 KRX 수신률이 안 올라가지?" 의문만 남음
- **백엔드 상태 변화(장애)의 UI 표시 의무 위반**

---

## 관련 파일
- `backend/app/services/daily_time_scheduler.py` — `_broadcast_market_phase()` (페이즈 갱신), `schedule_ws_subscribe_timers()` (타이머 예약), `_on_krx_market_open()` (09:00 콜백), `is_nxt_only_window()` (판단)
- `backend/app/services/sector_data_provider.py` — `get_sector_summary_inputs()` (krx_codes/nxt_codes 분리 반환)
- `backend/app/pipelines/pipeline_compute.py` — `_calculate_receive_rate()`, `_calc_market_receive_rate()`, Phase 2 루프
- `backend/app/services/engine_ws_dispatch.py` — `_handle_jif()` (JIF 핸들러, market_phase 미갱신)
- `backend/app/services/engine_loop.py` — WS 구간 변화 감지 루프, `_init_ws_subscribe_state()` 호출
- `backend/app/web/app.py` — `start_daily_time_scheduler()` 호출 (기동 시)
- `backend/logs/trading_2026-07-16.log` — 07:50~10:52 구간 로그

---

## 관련 커밋 (git 이력)
- `7902640` feat(sector): market-specific stock filtering for NXT-only windows — is_nxt_only_window() + 09:00 전용 타이머 최초 추가
- `aba9e92` fix: 재계산 타이머 3개 _broadcast_market_phase() 통합 — 09:00 전용 타이머 제거, 페이즈 변경 감지로 통합
- `076a66b` feat: is_ws_subscribe_window() market_phase 기반 전환 — ws_subscribe_start/end 타이머 제거, market_phase 타이머에 의존
- `b04f98c` feat: NXT-only 구독 분리 — subscribe_sector_stocks_0b() nxt_only 파라미터 추가
- `bcab27c` feat: 백엔드 수신률 KRX/NXT 분리 집계 — 3단계 (구독 로직 미변경, 수신률 집계만 분리)

---

## 다음 세션 조사 방향 (우선순위 순)

1. **DEBUG → INFO 로그 승격 먼저 적용** (최우선 전제 작업)
   - `schedule_ws_subscribe_timers()` 내 타이머 예약 로그 `logger.debug()` → `logger.info()` 승격 (<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/backend/app/services/daily_time_scheduler.py" lines="730-734" />)
   - `_broadcast_market_phase()` 실행 시 INFO 로그 추가 (페이즈 변경 내역, 타이머 핸들 수)
   - `schedule_ws_subscribe_timers()` 호출 시 INFO 로그 추가 (호출 스택 추적용)
   - 이것만으로도 재발 시 원인 특정 가능. **근본 원인 추적의 전제 조건**

2. **08:00, 09:00 타이머만 실패한 근본 원인 추적** (미확인 1)
   - INFO 승격 후 재발 시 타이머 예약/실행/재호출 추적
   - `schedule_ws_subscribe_timers()` 재호출 여부 확인 (미확인 2)
   - asyncio `call_later` 타이머 핸들 생존 검증 로깅 (cancelled 상태)

3. **`schedule_ws_subscribe_timers()` 재호출 경로 전수 추적** (미확인 2)
   - 현재 코드상 재호출 트리거를 찾지 못함 — INFO 승격 후 런타임 추적 필요
   - 재호출 시 `delay_mp <= 0`인 타이머가 재예약되지 않는 로직이 08:00/09:00 미실행의 원인일 가능성

4. **타이머 통합(aba9e92) 이전/이후 비교** (미확인 3)
   - 과거 09:00 전용 타이머 vs 현재 market_phase 타이머 의존 구조의 신뢰성 비교
   - 회귀 여부 최종 확인

5. **JIF 폴백 경로 활용 가능성** (미확인 4)
   - JIF 이벤트를 market_phase 갱신 폴백으로 활용 가능성 검토 (수정 방안 수립 시)

---

## 수정 방안 (제안 only — 승인 대기)

**근본 해결 방향**: 2단계 접근 — (1) 추적 가능성 확보, (2) 타이머 의존도 감소.

### 1단계: 추적 가능성 확보 (최우선 — 원인 특정의 전제)
- `schedule_ws_subscribe_timers()` 내 타이머 예약 로그 DEBUG → INFO 승격
- `_broadcast_market_phase()` 실행 시 INFO 로그 추가 (페이즈 변경 내역, 타이머 핸들 수/cancelled 상태)
- `schedule_ws_subscribe_timers()` 호출 시 INFO 로그 추가 (호출 스택 추적용)
- **이것만으로도 재발 시 원인 특정 가능**

### 2단계: 타이머 의존도 감소 (근본 해결)
- **Phase 2 루프 내 `market_phase` 주기적 갱신**: `_sector_recompute_loop_impl` Phase 2 while 루프(0.2초 간격)에서 `calc_timebased_market_phase()`를 주기적(예: 1초)으로 호출하여 `state.market_phase` 갱신. 타이머 실패 시에도 페이즈가 갱신됨.
- **`_calculate_receive_rate()` 호출 시 `market_phase` 갱신**: 수신률 계산 전 `market_phase`를 시간 기반으로 재확인. P10 SSOT 강화.
- **타이머 미실행 감지 로깅**: 타이머 핸들 생존 검증 로깅 추가.

### P원칙 관점
- **P16(살아있는 경로) 위반 해결**: 타이머 단일 경로 → Phase 2 루프 폴백 경로 추가
- **P10(SSOT) 강화**: `market_phase`가 타이머에만 의존하지 않고 시간 기반으로도 갱신
- **P21(사용자 투명성) 위반 해결**: 타이머 미실행 감지 로깅으로 장애 가시성 확보

**주의**: 백엔드 핵심 로직(수신률 + 장 상태) 변경이므로 safe-trade 스킬 + 테스트 + 런타임 기동 검증 필수. 사용자 승인 후 진행.
