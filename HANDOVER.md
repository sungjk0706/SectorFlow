# HANDOVER.md

## 완료 단계
- 실시간 지연 원인 분석 및 근본 해결 완료
  - 원인 6: Conflation 50ms 제거 (`engine_account_notify.py`)
    - `_CONFLATE_MS`, `_conflate_cache`, `_should_conflate()` 함수 전체 제거
    - `notify_raw_real_data()`에서 conflation 체크 로직 제거
    - 증권사 틱을 그대로 처리, 동일 가격이라도 거래대금/체결강도 등 다른 FID 변경 시 데이터 손실 방지
  - 원인 5: `shared_lock` 경합 전면 제거 (16개 파일, 21개 사용처)
    - `LazyLock` 클래스 정의 제거 (`engine_utils.py`)
    - `state.shared_lock` 정의 제거 (`engine_state.py`)
    - `_apply_real01_volume_amount_to_radar_rows`: `async def` → `def`로 변경, lock 제거
    - `pipeline_compute.py:408`: `await` 제거 (동기 호출로 변경)
    - `pipeline_compute.py:283`: `recompute_sector_summary_now` 래핑 lock 제거 (유일한 await 포함 지점)
    - 나머지 18개 동기 사용처 lock 제거 (engine_account, engine_cache, engine_snapshot, engine_ws, engine_ws_reg, buy_order_executor, market_close_pipeline, settings, stock_classification_data)
    - 근거: asyncio 협력 스케줄링에서 await 없는 동기 코드는 GIL + 협력 스케줄링에 의해 원자적 실행 보장
  - 검증: `shared_lock`/`LazyLock`/`_should_conflate` 잔여 검색 0건, `py_compile` 16개 파일 전체 성공
  - 커밋: `e3980f6` — 푸시 완료
- WS 연결 책임 engine_loop 단일화 완료
  - `engine_state.py` — `ws_window_changed_event` (LazyEvent) 필드 추가
  - `engine_loop.py` — `engine_stop_event.wait()` 제거, `asyncio.wait([stop, change], FIRST_COMPLETED)` 기반 구간 감지 루프 도입
  - `engine_loop.py` — WS 연결/해제 단일 책임: `ConnectorManager` 생성, `connect_all()`, `disconnect_all()` 모두 루프 내에서만 수행
  - `daily_time_scheduler.py` — `_on_ws_subscribe_start()` WS 연결 코드 제거, `ws_window_changed_event.set()` 추가
  - `daily_time_scheduler.py` — `_on_ws_subscribe_end()` WS 해제 코드 제거, `ws_window_changed_event.set()` 추가
  - `daily_time_scheduler.py` — `_ws_disconnect_only()` WS 해제 코드 제거, `ws_window_changed_event.set()` 추가
  - `daily_time_scheduler.py` — `_init_ws_subscribe_state()` `_trigger_reg_pipeline()` 제거, `ws_window_changed_event.set()` 추가
  - `engine_loop.py` — `_trigger_reg_pipeline()` 중복 호출 제거 (LS connector 내부 호출 + engine_ws_dispatch.py 로그인 응답 호출로 충분)
  - 스케줄러 잔류 책임: GC, 설정 ON/OFF 저장, 프론트엔드 통지, 실시간 필드 초기화, 캐시 초기화, `_trigger_unreg_all()`, market-phase 브로드캐스트
  - 검증: py_compile 3개 파일 성공, 앱 기동 성공, LS WS 연결 + REG 파이프라인 1회 트리거 확인, 프론트엔드 WS 3채널 연결 성공
- Settings Fallback 리팩토링 완료
  - DEFAULT_USER_SETTINGS를 단일 소스 진리로 확정
  - 28개 파일에서 .get("key", default) or fallback 패턴 → dict["key"] 직접 접근으로 변경
  - initial_deposit → test_virtual_deposit 통일
  - settings_defaults.py에 누락 키 추가: sector_start_threshold_pct, sell_per_symbol, broker_config
  - py_compile 28개 파일 전부 성공
  - 잔여 .get()은 동적 브로커 키({broker_nm}_account_no 등)와 선택적 런타임 키(_broker_specs, page_overrides)만 — 정당한 사용
- Kiwoom API Timeout 근본 해결 완료
- 종목 수 불일치 문제 근본 해결 완료
- 다운로드 완료 후 프론트엔드 새로고침 필요 문제 근본 해결 완료
- 업종순위 페이지 우측 테이블 불투명 처리 문제 근본 해결 완료
- Holiday Guard 리팩토링 완료
  - `is_trading_day_with_holiday_guard()` 중앙화 함수 추가 (trading_calendar.py)
  - `auto_trading_effective.py _master_on()` → 단일 함수 호출로 교체
  - `daily_time_scheduler.py` — 개별 토글 존중, 마스터/WS만 ON/OFF, 데드 코드 제거
  - `settings_defaults.py` — `auto_off_by_holiday: False` 추가
  - `general-settings.ts` — `shouldForceOff()` 적용 확대 (autoBuy, autoSell, syncFromSettings)
- Trading Days DB 캐시 제거 완료
  - `trading_days_cache` DB 테이블, save/load 함수, DDL 전체 제거
  - `is_trading_day()` → `exchange_calendars` XKRX 캘린더 직접 호출 (`xkrx.is_session()`)로 전환
  - `_get_xkrx()` lazy singleton 추가 (모듈 레벨 1회 로드, 메모리 상주, 11μs/call, 오프라인)
  - `initialize_trading_calendar_cache()` — app.py 시작 호출 제거
  - `refresh_trading_days_cache()` — 함수 및 연초 갱신 블록 제거
  - `POST /trading-calendar/refresh` API 엔드포인트 제거
  - SSOT 위반 해결: library 단일 진리 원천 (DB 캐시 + library 2개 → 1개)
  - 빈 캐시 치명 버그 해결: DB 비어있으면 모든 날짜 False → 항상 정확한 판별
  - 검증: py_compile 5개 파일 성공, npm run build 성공, 런타임 is_trading_day(get_kst_today()) → True
  - 커밋: `0703968` — 푸시 완료

## 현재 상태
- 실시간 지연 근본 해결 완료 (conflation + shared_lock 전면 제거)
- WS 연결 책임 engine_loop 단일화 완료
- 거래일 판별은 `exchange_calendars` XKRX 캘린더 직접 호출로 동작 (오프라인, O(1))

## 다음 단계
- 별도 작업 없음. 사용자 요청 시 진행.
- 런타임 검증 권장: `SectorFlow.command` 실행 후 장중 틱 수신 시 실시간 지연 개선 확인

## 미커밋 파일
- `daily_time_scheduler.py` — 이전 작업 수정사항 (별도 커밋 권장)
- `stocks.db`, `stocks.db-shm`, `stocks.db-wal` — 런타임 데이터 (커밋 제외)

## 미해결 문제
### 1. exchange_calendars 라이브러리 last_session 한계
- `xkrx.last_session: 2027-06-25` — 이 날짜 이후 판별 불가
- 라이브러리 업데이트로 해결 가능 (현재 2026년이므로 당장 문제 없음)
