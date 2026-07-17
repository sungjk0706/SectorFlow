# 구독/해지 타임라인 심층 조사 보고서

> **작성일**: 2026-07-17
> **조사 범위**: NXT/KRX 실시간 구독/해지 타임라인 전체 흐름 + "웹소켓 연결" API 명세서 존재 여부 확인
> **조사 성격**: 사전조사 (코드 수정 없음). 사용자 승인 후 설계·구현 진행 예정.
> **참조 규칙**: AGENTS.md 섹션3 규칙 0(승인 전 수정 금지) + P10(SSOT) + P16(살아있는 경로) + P21(사용자 투명성) + P22(데이터 정합성) + P24(단순성)

---

## 1. 확정된 타임라인 (07:58~20:00)

### 1.1 전체 타임라인 요약

| 시각 | 동작 | 트리거 | 핵심 함수 |
|------|------|--------|-----------|
| 07:58 | 실시간 필드 초기화 | 시간 기반 주기 태스크 (`_check_prestart_triggers`) | `_on_realtime_fields_reset()` |
| 07:59 | WS 구독 사전 준비 (GC 비활성화, 캐시 초기화) | 시간 기반 주기 태스크 | `_on_ws_subscribe_start()` |
| 08:00 | NXT 프리마켓 진입 → WS 연결 + NXT 구독 시작 | JIF push (1순위) / 시간 기반 (보완) | `_apply_market_phase()` → `_on_nxt_premarket_start()` |
| 09:00 | KRX 정규장 진입 → KRX 단독 종목 추가 구독 | JIF push / 시간 기반 | `_on_krx_market_open()` |
| 15:20 | KRX 정규장 종료 → 종가 동시호가 전환 (구독 유지) | JIF push / 시간 기반 | `_apply_market_phase()` (부작용 트리거 없음) |
| 15:30 | KRX 체결 정산 진입 → KRX 단독 종목 구독 해지 | JIF push / 시간 기반 | `_on_krx_after_hours_start()` → `remove_krx_only_stocks()` |
| 15:40 | NXT 애프터마켓 진입 (구독 변경 없음) | JIF push / 시간 기반 | `_apply_market_phase()` (부작용 트리거 없음) |
| 20:00 | NXT 장마감 → 전체 구독 해지 + WS 연결 해제 | JIF push / 시간 기반 | `_on_ws_subscribe_end()` → `_trigger_unreg_all()` |

### 1.2 상세 호출 체인

#### 07:58 — 실시간 필드 초기화
```
_market_phase_periodic_loop() [10초 루프]
  → _check_prestart_triggers()
    → schedule_engine_task(_on_realtime_fields_reset())
      → _reset_realtime_fields()  # 전일 확정 데이터 제거
```
- 파일: `backend/app/services/daily_time_scheduler.py` L1128-1151 (트리거), L641-661 (실행)
- 멱등성 가드: `state.last_realtime_reset_date == today_str`
- 거래일/주말 체크 포함

#### 07:59 — WS 구독 사전 준비
```
_check_prestart_triggers()
  → schedule_engine_task(_on_ws_subscribe_start())
    → gc.disable()  # 장중 GC 비활성화
    → reset_sector_threshold()  # 수신율 게이트 리셋
    → _reset_realtime_fields()  # 07:58 누락 시 보완
    → notify_cache.prev_scores = []  # delta 캐시 초기화
    → state.sector_summary_cache = None
    → _broadcast_market_phase()
    → state.ws_window_changed_event.set()  # 엔진 루프 통지
```
- 파일: `backend/app/services/daily_time_scheduler.py` L664-708
- **중요**: 07:59 시점 `market_phase.nxt = "장개시전"` (NXT_ACTIVE_PHASES 아님) → `is_ws_subscribe_window()`=False → 엔진 루프가 WS 연결하지 않음. 사전 준비만 수행.

#### 08:00 — NXT 프리마켓 진입 (실제 WS 연결 + NXT 구독)
```
[JIF 경로] _handle_jif() → _apply_jif_phase(nxt="프리마켓") → _apply_market_phase()
[시간 경로] _broadcast_market_phase() → calc_timebased_market_phase() → _apply_market_phase()

_apply_market_phase()
  → _on_nxt_premarket_start()  # 업종 재계산 (KRX 단독 종목 제외)
  → _on_ws_subscribe_start()   # 멱등성 가드로 스킵 (07:59 이미 실행)

[엔진 루프] is_ws_subscribe_window()=True 감지
  → ConnectorManager.connect_all()
    → LOGIN 수신 → _handle_login()
      → _trigger_reg_pipeline()
        → _login_post_pipeline()
          → _cleanup_stale_ws_subscriptions_on_session_ready()
          → recompute_sector_summary_now()
          → _run_sector_reg_pipeline()
            → run_conditional_reg_pipeline()
              → subscribe_sector_stocks_0b(nxt_only=is_nxt_only_window())
              → subscribe_index_realtime()  # 0J 업종지수
              → _ensure_account_subscription()  # 계좌 (실전모드)
```
- 08:00 시점: krx="장전 대기"(KRX_INACTIVE), nxt="프리마켓"(NXT_ACTIVE) → `is_nxt_only_window()`=True
- **NXT-enabled 종목만 구독** (KRX 단독 종목 제외), 보유종목 우선, 200개 한도

#### 09:00 — KRX 정규장 진입 (KRX 단독 종목 추가 구독)
```
_apply_market_phase()  # krx: "시가 동시호가" → "정규장"
  → _on_krx_market_open()
    → recompute_sector_summary_now()  # 전체 종목 포함 재계산
    → subscribe_sector_stocks_0b()  # nxt_only=False (기본값)
      → KRX 단독 종목만 추가 구독 (_subscribed 플래그 기반 제외)
```
- 파일: `backend/app/services/daily_time_scheduler.py` L404-428

#### 15:30 — KRX 체결 정산 진입 (KRX 단독 종목 구독 해지)
```
_apply_market_phase()  # krx: "종가 동시호가" → "체결 정산"
  → _on_krx_after_hours_start()
    → recompute_sector_summary_now()
    → state.krx_remove_done 체크 (멱등성)
    → remove_krx_only_stocks()  # KRX 단독 종목만 REMOVE
```
- **KRX 단독 종목만 해지**, NXT-enabled 종목은 구독 유지 (20:00까지)
- 파일: `backend/app/services/daily_time_scheduler.py` L431-461, `backend/app/services/market_close_pipeline.py` L122-202

#### 20:00 — NXT 장마감 (전체 구독 해지 + WS 연결 해제)
```
_apply_market_phase()  # nxt: "애프터마켓 지속" → "장마감"
  → _on_ws_subscribe_end()
    → gc.enable() + gc.collect()
    → state.ws_subscribe_window_active = False
    → mark_sector_threshold_passed()
    → state.confirmed_done = False
    → _trigger_unreg_all()
      → _do_unreg_all()
        → ws.unsubscribe_stocks(all_codes)
        → 계좌 REMOVE
        → _subscribed 플래그 전체 제거
    → state.ws_window_changed_event.set()

[엔진 루프] is_ws_subscribe_window()=False 감지
  → ConnectorManager.disconnect_all()
```
- 파일: `backend/app/services/daily_time_scheduler.py` L711-742, L901-952

### 1.3 트리거 구조 (하이브리드 — 안 D)

- **JIF push = 1순위**: `_handle_jif()` → `_apply_jif_phase()` → `_apply_market_phase()`
  - 파일: `backend/app/services/engine_ws_dispatch.py` L257-290
  - JIF 맵: L208-227
- **시간 기반 주기 태스크 = 보완**: 10초 간격 `_market_phase_periodic_loop()` → `_broadcast_market_phase()` → `_apply_market_phase()`
  - 파일: `backend/app/services/daily_time_scheduler.py` L1154-1180
- 부작용 트리거는 `_apply_market_phase()` 내 페이즈 변경 감지 시 멱등성 보장

### 1.4 중복 구독 방지 로직

| 로직 | 위치 | 기준 |
|------|------|------|
| 종목 단위 멱등성 | `subscribe_sector_stocks_0b()` | `master_stocks_cache[cd].get("_subscribed")` 체크 |
| WS 구독 시작 멱등 | `_on_ws_subscribe_start()` | `last_ws_subscribe_start_date == today_str` |
| 필드 초기화 멱등 | `_on_realtime_fields_reset()` | `last_realtime_reset_date == today_str` |
| KRX 해지 멱등 | `_on_krx_after_hours_start()` | `state.krx_remove_done` |
| 페이즈 변경 멱등 | `_apply_market_phase()` | `prev_krx != new_krx or prev_nxt != new_nxt` |
| REG 청크 refresh | `build_0b_reg_payloads()` | 첫 청크 `refresh="0"`, 이후 `refresh="1"` |

### 1.5 예외 상황 처리

#### 앱 중간 재시작 시
```
start_daily_time_scheduler()
  → calc_timebased_market_phase()  # 현재 장 상태 즉시 계산
  → state.market_phase 갱신
run_engine_loop()
  → _init_ws_subscribe_state()  # 현재 구간 판정
  → LOGIN 후 _login_post_pipeline()  # 잔존 구독 정리 + 구독 재설정
```
- `state.master_stocks_cache._subscribed`는 메모리만 존재 → 재시작 시 초기화 → 모든 종목 재구독

#### WS 재연결 시
```
ConnectorManager._on_reconnect_success(broker_id)
  → restore_subscriptions_after_reconnect(broker_id)
    → master_stocks_cache._subscribed 기준 0B REG 재전송
    → subscribe_index_realtime()  # 0J 복원
    → subscribe_account_realtime()  # 계좌 복원
```
- 파일: `backend/app/core/connector_manager.py` L109-116, `backend/app/services/engine_ws_reg.py` L439-488

---

## 2. 제안된 변경 사항과 검토 결과

### 2.1 사용자 제안 타임라인 (재설계안)

| 시각 | 제안 동작 | 현재 대비 변경 |
|------|-----------|-----------------|
| 07:58 | 필드 초기화 + GC 비활성화 + 캐시 초기화 | GC/캐시를 07:59에서 이동 |
| 07:59 | WS 연결 + LOGIN + NXT 구독 신청 | 신규: 08:00에서 07:59로 이동 |
| 08:00 | NXT 프리마켓 시작 (이미 구독됨) | 동작 없음 |
| 08:59 | KRX 추가 구독 신청 | 신규: 09:00에서 08:59로 이동 |
| 09:00 | KRX 정규장 시작 (이미 구독됨) | 재계산만 |
| 15:20 | KRX 단독 종목 구독 해지 | 변경: 15:30에서 15:20으로 이동 |
| 15:30 | NXT 단일가 매매 진입 (구독 유지) | KRX 해지 로직 제거 |
| 20:00 | 전체 구독 해지 + WS 연결 해제 | 변경 없음 |

### 2.2 프로젝트 핵심 특성 (재설계 전제)

1. **매매 로직**: 시장가 체결만 사용 (지정가 없음)
2. **동시호가 구간** (08:40~09:00, 15:20~15:30): 시장가 체결 불가 → 구독 유지할 이유 없음
3. **종가 데이터**: 20:40 확정시세 다운로드로 수신 (실시간 종가 수신 불필요)
4. **향후 계획**: 시장가 체결 불가능한 시간대 매매 임시 중단 로직 추가 예정

### 2.3 검토 결과

| 제안 | 기술 가능 | P원칙 | 부작용 | 권장 |
|------|-----------|-------|--------|------|
| 1. 07:58 통합 (GC+캐시) | 가능 | P24 주의 | 낮음 | **부분 이동** (데이터 준비만) |
| 2. 07:59 NXT 구독 | 가능 | P21 부가 작업 | UI 표시 필요 | **권장** |
| 3. 08:59 KRX 사전 구독 | 가능 | P21 부가 작업 | UI 표시 필요 | **권장** |
| 4. 15:20 KRX 해지 | 가능 | P22 위반 아님 | UI 표시 필요 | **권장** |
| 5. 15:30 유지 | - | - | - | KRX 해지 로직만 15:20 이동 |
| 6. 20:00 유지 | - | - | - | **유지** |

### 2.4 이전 검토 오류 정정

| 항목 | 이전 검토 | 정정 |
|------|-----------|------|
| 08:59 KRX 구독 효과 | "1초 단축" | **오류**. 08:59:01 구독 시 09:00까지 59초 여유. 정규장 시작 시점에 이미 구독 완료 상태 보장. |
| 15:20 KRX 해지 부작용 | "종가 데이터 손실 (P22 위반)" | **오류**. 종가는 20:40 확정시세 다운로드로 수신. 실시간 종가 수신 불필요. P22 위반 아님. |
| 15:20~15:30 구독 유지 이유 | "종가 동시호가 체결 시세 필요" | **오류**. 시장가 체결만 사용 → 동시호가 구간 체결 불가 → 매매 로직 관점에서 구독 유지 이유 없음. |

### 2.5 공통 부가 작업 (P21 사용자 투명성)

- 07:59/08:59 사전 구독 시 UI에 "사전 구독 중" 상태 표시
- 15:20 KRX 해지 시 UI에 "시장가 매매 불가 구간 — 구독 해지" 표시
- `market_phase`에 `pre_subscribe: bool` 플래그 추가 검토 (프론트엔드 표시용)

---

## 3. "웹소켓 연결" API 명세서 존재 여부

### 3.1 프로젝트 내 명세서 검색 결과

#### 키움증권
- **"웹소켓 연결" 별도 API 명세서: 없음**
- `docs/api_specs/키움증권API/websocket/실시간/` 폴더: TR명(0B, 0J, 0s 등)별 명세서만 존재
- LOGIN은 각 TR명세서의 **예제 코드(Python 샘플) 내부**에만 등장 (본문 스펙에 미포함)
  - 예: `주식체결_0B.txt` L412-419, `주문체결_00.txt` L370-377 등 모든 TR명세서에 동일 LOGIN 패킷 포함

#### LS증권
- **"웹소켓 연결" 별도 API 명세서: 없음**
- `docs/api_specs/LS증권API/websocket/실시간/` 폴더: TR명(US3, JIF 등)별 명세서만 존재
- LS는 **LOGIN 개념 자체가 없음** — 소켓 연결 시 Header에 토큰 포함 = 인증 완료

### 3.2 인터넷 검색 결과

#### 키움증권
- **알고랩 가이드** (https://algolab.co.kr/blog/kiwoom-rest-api-algotrading-guide-2026)
  > "접속 후 토큰으로 로그인(인증) 메시지를 보내고, 원하는 실시간 항목을 등록(구독)하면 이벤트가 푸시됩니다."
  - WebSocket 접속 → LOGIN 메시지 → 구독(REG) 순서. "웹소켓 연결" 별도 API가 아닌 표준 WebSocket 라이브러리 사용.
- **GitHub younghwan91/kiwoom-rest-api** (https://github.com/younghwan91/kiwoom-rest-api)
  - `ws.connect()` = 표준 `websockets.connect()` 래퍼 (별도 API 아님)
- **Notepad 블로그 예제** (https://cadmus1216.blogspot.com/2026/04/import-asyncio-import-json-import.html)
  > "WebSocket 연결 시 별도 HTTP 인증 헤더는 필요 없고, trnm: LOGIN 메시지로 인증합니다."

#### LS증권
- **LS증권 공식 OPENAPI 안내** (https://www.ls-sec.co.kr/xingapi/openapi/info.jsp)
  - WebSocket 연결에 대한 별도 API 언급 없음 — 토큰 발급(REST) + WebSocket 연결(표준) + 구독 신청(tr_type) 구조
- **GitHub xorrhks0216/LsApiHelper** (https://github.com/xorrhks0216/LsApiHelper)
  - `client.realtime()` = WebSocket 클라이언트 생성 (표준 WebSocket)
- **GitHub kimpro82/MyInvestmentModules** (https://github.com/kimpro82/MyInvestmentModules)
  - WebSocket URL + 토큰 Header 기반 인증. "웹소켓 연결" 별도 API 없음.
- **GitHub callin2/ls-api** (https://github.com/callin2/ls-api)
  - 환경변수로 WebSocket 엔드포인트만 지정. "웹소켓 연결" 별도 API 없음.

### 3.3 사실 정리

| 질문 | 답변 | 근거 |
|------|------|------|
| 키움 "웹소켓 연결" 별도 API 명세서 존재? | **없음** | 프로젝트 내 명세서 + 알고랩 가이드 + GitHub 3개 저장소 |
| 키움 LOGIN 별도 API? | **아님** — 연결 후 전송하는 메시지 | 알고랩: "접속 후 토큰으로 로그인(인증) 메시지를 보내고" |
| LS "웹소켓 연결" 별도 API 명세서 존재? | **없음** | 프로젝트 내 명세서 + LS증권 공식 안내 + GitHub 3개 저장소 |
| LS LOGIN 별도 API? | **아님** — LOGIN 개념 자체 없음, 소켓 연결 시 토큰 Header 포함 | GitHub xorrhks0216: 토큰 캐싱 후 WebSocket 연결 |

---

## 4. 핵심 발견: "웹소켓 연결"은 증권사 API가 아닌 표준 WebSocket 프로토콜

### 4.1 사실

**두 증권사 모두 "웹소켓 연결"이라는 별도 API는 존재하지 않음**

- WebSocket 연결은 **표준 WebSocket 프로토콜** (`websockets.connect()`) 사용
- 증권사 고유 API가 아닌 **표준 라이브러리 사용**
- 증권사 API 명세서는 **구독 신청(REG / tr_type=3) 스펙만 제공**
- 인증 방식:
  - 키움: 연결 후 LOGIN 메시지 전송 (별도 API 아닌 메시지 방식)
  - LS: 소켓 연결 시 토큰 Header 포함 (별도 API 아닌 헤더 방식)

### 4.2 구독 신청 함수 내부에 웹소켓 연결 포함 여부

**결론: 포함되어 있지 않음**

- `subscribe_stocks()`는 연결 체크만 하고, 연결 없으면 즉시 `return False`
- 내부에서 자동 연결하지 않음 (키움/LS 모두)
- `connect()`를 먼저 호출해야만 구독 신청 가능

### 4.3 프로젝트 내 "WS 연결" 관련 코드

| 함수 | 위치 | 역할 |
|------|------|------|
| `KiwoomConnector.connect()` | `kiwoom_connector.py:212` | 소켓 연결 + LOGIN 전송 + 수신루프 기동 |
| `LsConnector.connect()` | `ls_connector.py:344` | 토큰 발급 + 소켓 연결 + 수신루프 기동 |
| `ConnectorManager.connect_all()` | `connector_manager.py:88` | 모든 커넥터 병렬 연결 |
| `ConnectorManager.disconnect_all()` | `connector_manager.py:118` | 모든 커넥터 병렬 해제 |
| `is_ws_subscribe_window()` | `daily_time_scheduler.py` | 구독 구간 판정 (market_phase 기반) |
| `ws_window_changed_event` | `engine_state.py` | 구독 구간 변경 통지 |

### 4.4 호출 관계도

```
[엔진 루프] engine_loop.py
  │ is_ws_subscribe_window() == True 감지
  ↓
  ConnectorManager() 생성 → connect_all()
    ├─ KiwoomConnector.connect()
    │   ├─ websockets.connect(uri)              ← 표준 소켓 연결
    │   ├─ _raw_send({"trnm": "LOGIN", ...})    ← LOGIN 메시지
    │   └─ _recv_task 기동                       ← 수신루프
    └─ LsConnector.connect()
        ├─ _get_token_async()                   ← 토큰 발급 (REST)
        ├─ _LsSocket.connect()                  ← 표준 소켓 연결 (토큰 포함)
        ├─ state.login_ok = True
        ├─ _trigger_reg_pipeline()              ← 구독 파이프라인 트리거
        └─ subscribe_jif()                      ← JIF 구독

[LOGIN 응답 수신]
  → _trigger_reg_pipeline()
    → _login_post_pipeline()
      → _run_sector_reg_pipeline()
        → subscribe_sector_stocks_0b()          ← 구독 신청 (REG)
        → subscribe_index_realtime()
        → _ensure_account_subscription()

[엔진 루프] is_ws_subscribe_window() == False 감지
  → ConnectorManager.disconnect_all()
    ├─ unsubscribe_stocks()                     ← 구독 해지
    └─ connector.disconnect()                   ← 소켓 종료
```

---

## 5. 수정 방향: connect()/disconnect() 단순화 가능성

### 5.1 현재 구조 분석

**`connect()`가 하는 일**:
1. 표준 WebSocket 소켓 연결 (`websockets.connect()`)
2. 인증 (키움: LOGIN 메시지 / LS: 토큰 Header)
3. 수신루프 기동 (`_recv_task`)

**`disconnect()`가 하는 일**:
1. 수신루프 취소
2. 소켓 종료 (`_ws.close()`)

### 5.2 단순화 가능성 검토

**현재 구조는 이미 단순한 편** — `connect()`는 3단계를 하나로 묶고 있으나, 각 단계는 API 명세상 필수:
- 소켓 연결: 구독 신청의 선행 조건 (소켓 객체 없이 `send()` 불가)
- 인증: 서버가 미인증 세션 거부
- 수신루프: REAL 메시지 수신 안 됨

**제거 검토 대상**:
- `is_ws_subscribe_window()` + 엔진 루프의 "구독 구간 감지 루프" — 이것은 프로젝트 자원 관리 추상화
- 07:59 사전 구독을 위해 이 추상화를 유지하면서 사전 구간 확장하는 방식이 합리적

### 5.3 결론

- **`connect()`/`disconnect()` 자체는 단순화 대상 아님** — API 명세상 필수 단계를 캡슐화
- **엔진 루프의 "구독 구간 감지"는 유지하되 사전 구간 확장** — 07:59~08:00 사전 구간 추가
- **불필요한 추상화 제거 대상 없음** — 현재 구조는 API 명세와 일치

### 5.4 재설계에 미치는 영향

| 변경 | API 명세상 제약 | 기술적 가능성 |
|------|----------------|---------------|
| 07:59 NXT 구독 | 제약 없음 — 소켓 연결 + LOGIN + REG 전부 가능 | 가능 |
| 08:59 KRX 추가 구독 | 제약 없음 — REG는 LOGIN 응답 후 언제든 전송 가능 | 가능 |
| 15:20 KRX 구독 해지 | 제약 없음 — REMOVE는 언제든 전송 가능 | 가능 |

---

## 6. 관련 파일 전체 목록

### 구독/해지 로직
- `backend/app/services/daily_time_scheduler.py` — 스케줄러, `_apply_market_phase`, `_on_ws_subscribe_start/end`, `_check_prestart_triggers`, `_market_phase_periodic_loop`, `is_ws_subscribe_window`, `is_nxt_only_window`, `_do_unreg_all`
- `backend/app/services/engine_ws_dispatch.py` — JIF 처리, `_handle_jif`, `_apply_jif_phase`, `_JIF_PHASE_MAP_KRX/NXT`
- `backend/app/services/engine_ws_reg.py` — REG/UNREG 페이로드, `subscribe_sector_stocks_0b`, `subscribe_index_realtime`, `subscribe_account_realtime`, `restore_subscriptions_after_reconnect`
- `backend/app/services/ws_subscribe_control.py` — 구독 상태 관리, `run_conditional_reg_pipeline`, `start_quote/stop_quote`, `_ensure_account_subscription`, `cleanup_stale_subscriptions`
- `backend/app/services/engine_ws.py` — `_broker_message_handler`, `_ws_send_reg_unreg_and_wait_ack`, `_run_sector_reg_pipeline`
- `backend/app/services/engine_loop.py` — `run_engine_loop`, WS 구간 감지 루프, `_init_ws_subscribe_state`
- `backend/app/services/engine_bootstrap.py` — `_login_post_pipeline`
- `backend/app/services/market_close_pipeline.py` — `remove_krx_only_stocks`, `fetch_unified_confirmed_data`
- `backend/app/core/connector_manager.py` — `ConnectorManager`, `connect_all/disconnect_all`, `_on_reconnect_success`
- `backend/app/services/engine_snapshot.py` — `_reset_realtime_fields`

### 증권사별 커넥터
- `backend/app/core/ls_connector.py` — LS증권 (NXT 지원)
- `backend/app/core/kiwoom_connector.py` — 키움증권

### API 명세서
- `docs/api_specs/키움증권API/websocket/실시간/주식체결_0B.txt` — 키움 0B 체결 명세 + LOGIN 예제
- `docs/api_specs/LS증권API/websocket/실시간/(통합)체결US3.txt` — LS US3 체결 명세
- `docs/api_specs/LS증권API/인증/접근토큰발급token.txt` — LS OAuth2 토큰 발급 명세

---

## 7. 다음 세션 진행 방향

### 7.1 사용자 결정 대기 항목
1. 제안 1 (07:58 통합): 부분 이동 권장 — 데이터 준비만 07:58로, WS 구독 상태는 07:59 유지
2. 제안 2 (07:59 NXT 구독): 권장 — `is_ws_subscribe_window()` + `is_nxt_only_window()` 사전 구간 추가
3. 제안 3 (08:59 KRX 사전 구독): 권장 — `_check_prestart_triggers()` 08:59 추가
4. 제안 4 (15:20 KRX 해지): 권장 — `_apply_market_phase()` 트리거 조건 15:20 변경
5. P21 부가 작업: 사전 구독 상태 UI 표시

### 7.2 수정 계획 (승인 시)

**다단계 작업 분할 제안 (세션당 1단계)**:

1. **설계 문서 + 태스크 파일 작성**: `docs/plan_subscribe_timeline_redesign.md`
2. **백엔드 배선**: `is_ws_subscribe_window()` + `is_nxt_only_window()` 사전 구간 추가 (07:59 NXT 구독 활성화)
3. **프론트엔드**: 사전 구독 상태 UI 표시
4. **백엔드 트리거**: 08:59 KRX 사전 구독 + 15:20 KRX 해지 시점 변경
5. **테스트 + 검증**: 테스트 갱신 + 런타임 검증

### 7.3 영향 파일 예상
- `backend/app/services/daily_time_scheduler.py` (핵심)
- `backend/tests/test_daily_time_scheduler.py` (테스트)
- `frontend/src/` (UI 표시 — 3단계)
- `docs/plan_subscribe_timeline_redesign.md` (설계 문서 — 1단계)

### 7.4 검증 방법
- `pytest backend/tests/test_daily_time_scheduler.py`
- 런타임 기동 후 07:58/07:59/08:59/15:20/15:30/20:00 로그 확인 (거래일 장 시간대)
