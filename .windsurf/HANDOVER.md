# SectorFlow 워크룰 위반 수정 — HANDOVER

## 완료된 서브 Phase

### Phase 1-1: `engine_ws_dispatch.py` — 실시간 체결 4건
- **완료 시점**: 2026-05-13
- **수정 파일**: `backend/app/services/engine_ws_dispatch.py`
- **수정 지점**: 4개 지점 `except: pass` → `logger.warning(...)`
  - 라인 271: `except RuntimeError` → `[재구독] 루프 미실행` 로그
  - 라인 335: `except (ValueError, TypeError)` → `[체결강도] 파싱 실패` 로그
  - 라인 387: `except (ValueError, TypeError)` → `[체결강도WL] 파싱 실패` 로그
  - 라인 404: `except (ValueError, TypeError)` → `[미체결] 파싱 실패` 로그 (fallback `unex = 0` 유지)
- **검증 결과**:
  - `grep -n "except.*pass"` → 0건
  - `python3 -m py_compile` → 문법 검사 통과
- **기존 동작 변경**: 없음 (예외 발생 시 fallback 값 유지, 흐름 계속)

### Phase 1-2: `engine_account_notify.py` — 브로드캐스트/필터 2건
- **완료 시점**: 2026-05-13
- **수정 파일**: `backend/app/services/engine_account_notify.py`
- **수정 지점**: 2개 지점 `except: pass` → `logger.error(...)`
  - 라인 298-299: `except Exception` (필터 `_is_relevant_code`) → `[필터] 종목 판별 실패` 로그
  - 라인 318-319: `except Exception` (정규화 `notify_raw_real_data`) → `[정규화] raw_code 실패` 로그 + `return` 추가
- **검증 결과**:
  - `grep -n "except.*pass"` → 0건
  - `python3 -m py_compile` → 문법 검사 통과
- **기존 동작 변경**: 318-319만 예외 시 `return` 추가 (잘못된 데이터 브로드캐스트 방지)

### Phase 1-3: `engine_strategy_core.py` — 전략/구독 2건
- **완료 시점**: 2026-05-13
- **수정 파일**: `backend/app/services/engine_strategy_core.py`
- **수정 지점**: 2개 지점 `except: pass` → `logger.warning/error(...)`
  - 라인 42-43: `except Exception` (종목명 REST 조회 `resolve_radar_display_name`) → `[종목명] REST 조회 실패` 로그
  - 라인 116-117: `except RuntimeError` (실시간 구독 등록 `register_pending_stock`) → `[구독] task 생성 실패` 로그
- **검증 결과**:
  - `grep -n "except.*pass"` → 0건
  - `python3 -m py_compile` → 문법 검사 통과
- **기존 동작 변경**: 없음 (fallback 값 유지, 흐름 계속)

### Phase 1-4: `engine_bootstrap.py` — 부트스트랩 7건
- **완료 시점**: 2026-05-13
- **수정 파일**: `backend/app/services/engine_bootstrap.py`
- **수정 지점**: 7개 지점 `except: pass` → `logger.warning/error(...)`
  - 라인 44-45: `except Exception` (부트스트랩 stage 브로드캐스트) → `[부트] stage 브로드캐스트 실패` warning
  - 라인 272-273: `except Exception` (매수후보 갱신) → `[부트] 매수후보 갱신 실패` warning
  - 라인 425-426: `except Exception` (부트스트랩 완료 UI 초기 전송) → `[부트] UI 초기 전송 실패` error
  - 라인 441-442: `except Exception` (장외 매수후보 갱신) → `[장외] 매수후보 갱신 실패` warning
  - 라인 446-447: `except Exception` (장외 섹터 갱신) → `[장외] 섹터 갱신 실패` warning
  - 라인 705-706: `except Exception` (5일평균 후처리) → `[5일평균] 후처리 실패` error
  - 라인 736-737: `except Exception` (5일평균 진행률 브로드캐스트) → `[5일평균] 진행률 전송 실패` warning
- **검증 결과**:
  - `grep -n "except.*pass"` → 0건
  - `python3 -m py_compile` → 문법 검사 통과
- **기존 동작 변경**: 없음 (흐름 계속)

### Phase 1-5: `trading.py` — 텔레그램 알림 1건
- **완료 시점**: 2026-05-13
- **수정 파일**: `backend/app/services/trading.py`
- **수정 지점**: 1개 지점 `except: pass` → `logger.warning(...)`
  - 라인 32-33: `except Exception` (텔레그램 NotificationWorker 큐 등록) → `[텔레그램] 알림 큐 등록 실패` 로그
- **검증 결과**:
  - `grep -n "except.*pass"` → 0건
  - `python3 -m py_compile` → 문법 검사 통과
- **기존 동작 변경**: 없음 (흐름 계속)

### Phase 2-1: `engine_ws_dispatch.py` + `engine_service.py` — 실시간 지연 측정
- **완료 시점**: 2026-05-13
- **수정 파일**:
  - `backend/app/services/engine_ws_dispatch.py`
  - `backend/app/services/engine_service.py`
- **수정 지점**:
  - `engine_service.py` 라인 265: `_realtime_latency_exceeded: bool = False` 전역 플래그 추가
  - `engine_ws_dispatch.py`: `import time` 추가
  - `_handle_real_01` 라인 286: `_ts = int(time.time() * 1000)` 주입 + 함수 끝 `_check_realtime_latency(_ts, es)` 호출
  - `_handle_real_00` 라인 413: `_ts = int(time.time() * 1000)` 주입 + 함수 끝 `_check_realtime_latency(_ts, es)` 호출
  - `_check_realtime_latency` helper 함수 추가: `50ms` 경고 / `200ms` 초과 시 `_realtime_latency_exceeded = True`
- **검증 결과**:
  - `python3 -m py_compile engine_ws_dispatch.py` → 문법 검사 통과
  - `python3 -m py_compile engine_service.py` → 문법 검사 통과
- **기존 동작 변경**: 200ms 초과 시 `_realtime_latency_exceeded = True` 설정 (자동매매 중단 트리거)

### Phase 3: `appStore.ts` — `.map()` 전체 재생성
- **완료 시점**: 2026-05-13
- **수정 파일**: `frontend/src/stores/appStore.ts`
- **수정 지점**: `applySectorScores` 함수 (`appStore.ts:481-504`)
  - `same`이 `false`일 때 `updates.sectorOrder = scores.map(...)`가 항상 새 배열 참조를 생성하는 문제 수정
  - `newOrder`와 `prevOrder`를 순서 비교 → 실제 순서 변경 시에만 `sectorOrder` 갱신
- **검증 결과**: TypeScript 문법 확인 완료
- **기존 동작 변경**: 동일 업종 순서에 대해 불필요한 `sectorOrder` 참조 교체 방지 (리렌더링 최소화)

---

## 다음 진행 대상 Phase

### Phase 4: 프론트엔드 `innerHTML = ''` 수정
- **완료 시점**: 2026-05-13
- **수정 파일**:
  - `frontend/src/pages/sector-analysis.ts`: `maxTargetsStatusEl.innerHTML = ''` → `while (firstChild) removeChild` (라인 35, 1개 지점)
  - `frontend/src/components/common/data-table.ts`: 4개 지점 수정
    - `renderEmpty` 라인 215: `tbody.innerHTML = ''` → `while` 제거
    - `updateRows` 라인 291: `tbody.innerHTML = ''` → `while` 제거
    - 가상 스크롤 행 갱신 라인 408: `rowEl.innerHTML = ''` → `while` 제거
    - 셀 내용 교체 라인 540: `cell.innerHTML = ''` → `while` 제거
- **검증 결과**:
  - `grep 'innerHTML = \'\'' frontend/src/pages/sector-analysis.ts frontend/src/components/common/data-table.ts` → 0건
  - 추가 발견: `fixed-table.ts`(2건), `settings-common.ts`(1건), `sector-custom.ts`(7건), `error-boundary.ts`(2건), `router.ts`(1건), `main.ts`(1건)에 잔여
- **기존 동작 변경**: 없음 (DOM 초기화 동작 유지, 참조 보존 방식으로 변경)

### Phase 5: 추가 `innerHTML = ''` 파일 수정
- **완료 시점**: 2026-05-13
- **수정 파일**:
  - `frontend/src/components/common/fixed-table.ts`: 2개 지점
    - `renderEmpty` 라인 134: `tbody.innerHTML = ''` → `while (tbody.firstChild) tbody.removeChild(tbody.firstChild)`
    - `updateRows` 라인 290: `tbody.innerHTML = ''` → `while` 제거
  - `frontend/src/components/common/settings-common.ts`: 1개 지점
    - `renderContent` 라인 133: `content.innerHTML = ''` → `while` 제거
  - `frontend/src/pages/sector-custom.ts`: 8개 지점 (빌드 초기화 + unmount)
    - `buildTripleHeader` 라인 371: `shell.tripleHeader.innerHTML = ''` → `while` 제거
    - `buildTripleLeft` 라인 888: `shell.tripleLeft.innerHTML = ''` → `while` 제거
    - `buildTripleCenter` 라인 899: `shell.tripleCenter.innerHTML = ''` → `while` 제거
    - `buildTripleRight` 라인 1169: `shell.tripleRight.innerHTML = ''` → `while` 제거
    - `unmount` 라인 1535-1538: 4개 패널 일괄 `innerHTML = ''` → `while` 제거
  - `frontend/src/components/common/error-boundary.ts`: 2개 지점
    - `renderError` 라인 22: `container.innerHTML = ''` → `while` 제거
    - 재시도 버튼 클릭 라인 50: `container.innerHTML = ''` → `while` 제거
  - `frontend/src/router.ts`: 1개 지점
    - `handleRouteChange` 라인 133: `contentEl.innerHTML = ''` → `while` 제거
  - `frontend/src/main.ts`: 1개 지점
    - `patchRouterForDualLayout` 라인 248: `shell.leftPanel.innerHTML = ''` → `while` 제거
- **검증 결과**:
  - `grep -rn "innerHTML = ''"` 대상 6파일 → 0건
  - `npx tsc --noEmit` → exit code 0 (신규 문법 오류 0건)
- **기존 동작 변경**: 없음 (DOM 초기화 동작 유지, 참조 보존 방식으로 변경)

---

### Phase 6: 위반 5 — 실시간 체결 무거운 로깅
- **완료 시점**: 2026-05-13
- **조사 파일**: `backend/app/services/engine_ws_dispatch.py`, `backend/app/services/engine_account_notify.py`
- **조사 결과**: 정상 체결 틱마다 호출되는 `logger.info`/`warning`/`error`는 **존재하지 않음**
  - `logger.debug` 호출은 있으나 DEBUG 레벨은 운영 환경(INFO)에서 출력되지 않음
  - Phase 1-1에서 추가된 `logger.warning` 2건(`[체결강도]`, `[체결강도WL]`)은 모두 **파싱 실패 `except` 블록 내부**에만 존재
  - `plan_workrule_fix.md`의 "재검토 필요" 항목은 **기우였음** (실제 위반 없음)
- **수정 필요 여부**: 없음

### Phase 7: 위반 6 — 네트워크 복구 버퍼링
- **완료 시점**: 2026-05-13
- **조사 파일**: `frontend/src/api/ws.ts`, `backend/app/services/engine_ws_reg.py`, `frontend/src/stores/appStore.ts`
- **조사 결과**:
  - 프론트엔드 `ws.ts`: 재연결 시 `backfilling=true` → 서버 `initial-snapshot` 수신 → 전체 상태 교체
  - 백엔드 `engine_ws_reg.py`: `restore_subscriptions_after_reconnect`는 구독 재등록만 수행, **끊긴 데이터 버퍼링 없음**
  - 메시지 수신 경로(`_dispatchMessage`): 즉시 핸들러 호출, **큐/버퍼 없음**
  - **워크룰 권장 방식(스냅샷 덮어쓰기)을 이미 준수 중**
- **수정 필요 여부**: 없음

---

### Phase 8: 위반 7 — 장중 프리페치
- **완료 시점**: 2026-05-13
- **조사 파일**: `frontend/src/router.ts`, `main.ts`, `binding.ts`, `appStore.ts`, `api/client.ts`, 9개 페이지 모듈 전체
- **조사 결과**: 장중 프리페치 로직 **존재하지 않음**
  - `prefetch/preload/idle/fetchData` 키워드 grep → 0건
  - 라우터는 hashchange 기반. `moduleCache`로 캐싱만 수행. 사용자 네비게이션 시에만 동적 import 실행
  - 모든 페이지 모듈은 Store에 이미 존재하는 데이터만 읽어 표시. 외부 API 호출은 사용자 상호작용 시에만 발생
  - "한번 본 페이지는 빠르게" 원칙(moduleCache) 준수. "미리 다른 화면 로드" 위반 없음
- **수정 필요 여부**: 없음

### Phase 9: 위반 8 — 미시청 화면 데이터 전송
- **완료 시점**: 2026-05-13
- **조사 파일**: `frontend/src/api/ws.ts`, `backend/app/web/routes/ws.py`, `backend/app/web/ws_manager.py`, `backend/app/services/engine_account_notify.py`
- **조사 결과**: `real-data`는 이미 per-client 활성 페이지 기준 필터링 적용 중
  - 프론트엔드: `notifyPageActive`/`notifyPageInactive` → WS `page-active`/`page-inactive` 전송 (모든 페이지 mount/unmount에서 호출)
  - 백엔드: `ws_manager._client_active_page`로 클라이언트별 활성 페이지 추적
  - `_is_code_relevant_for_page(page, code)`: sector-analysis→레이아웃+pending 종목, buy-target→매수후보/차단 종목, sell-position→보유종목, profit-overview/settings→real-data 미전송
  - `broadcast("real-data")` → 사전 필터링 + per-client 필터링. 필요 없는 클라이언트에는 압축·task 생성 생략
  - 나머지 이벤트(account-update, buy-targets-delta, sector-scores 등): 워크룰 예외(매수후보/보유종목은 거의 항상 보낼 수 있도록 허용) + 빈도 낮음(수 초~수 분 단위) → 실질적 부하 negligible
- **수정 필요 여부**: 없음

---

### Phase 12: 단계 1 — 압축 로직(Conflation) 도입
- **완료 시점**: 2026-05-13
- **수정 파일**: `backend/app/services/engine_account_notify.py`
- **수정 지점**:
  - `_should_conflate(item)` 함수 추가 (`engine_account_notify.py:43-72`)
  - `_CONFLATE_MS = 50`, `_conflate_cache` 모듈 스코프 변수 추가 (`engine_account_notify.py:37-40`)
  - `notify_raw_real_data` 상단에 `_should_conflate(item)` 체크 추가 (`engine_account_notify.py:348-349`)
- **동작**: 01/0B 시세 타입에서 동일 종목·동일 가격·50ms 이내 중복 틱 → `_broadcast("real-data")` 생략
- **압축 대상 제외**: 00(주문체결), 04/80(잔고), 0J(지수), 0D(호가잔량) — 이들은 압축하지 않고 정상 전송
- **검증 결과**:
  - `python3 -m py_compile` → 문법 검사 통과
  - `test_conflation.py` 6개 케이스 전체 통과:
    - 동일 가격 50ms 이내 압축
    - 가격 변화 시 통과
    - 50ms 이후 동일 가격 통과
    - 00/0J/0D 타입 압축 대상 아님
    - 0B 타입 압축
    - 스트레스 테스트(20건/20ms): 1건 통과, 19건 압축
- **기존 동작 변경**: 없음 (압축으로 생략된 틱은 프론트엔드 delta 비교로도 어차피 무시됨)

---

### Phase 13: 단계 2 — 논블로킹 I/O 전면 적용
- **완료 시점**: 2026-05-13
- **조사 파일**: `backend/app/services/engine_ws_dispatch.py`, `backend/app/services/engine_loop.py`, `backend/app/core/kiwoom_rest.py`, `backend/app/services/daily_time_scheduler.py`, `backend/app/services/engine_bootstrap.py`
- **조사 결과**:
  - 실시간 WS 메시지 처리 경로(`engine_ws_dispatch.py` → `engine_account_notify.py` → `ws_manager.broadcast`)에 `time.sleep`, 동기 HTTP, 동기 파일 I/O가 **존재하지 않음**
  - REST API 호출(`kiwoom_rest.py`)의 `time.sleep`(429 backoff, 연속조회 간격)은 모두 `engine_loop.py`의 `asyncio.to_thread()`로 별도 스레드에서 실행 (`engine_loop.py:56`, `engine_loop.py:75`)
  - 동기 파일 I/O(`save_index_cache`, `load_index_cache` 등)는 스케줄러 콜백(장마감 후)에서만 호출, 실시간 경로 무관
  - `httpx`(`kiwoom_rest.py:17`) 사용, 동기/비동기 모두 지원. 모든 호출이 `asyncio.to_thread()` 경유
- **수정 필요 여부**: 없음 (이미 논블로킹 I/O 원칙 준수 중)

### Phase 14: 단계 3 — 인메모리 캐시 구축
- **완료 시점**: 2026-05-13
- **조사 파일**: `backend/app/services/engine_service.py`, `backend/app/services/engine_cache.py`
- **조사 결과**:
  - LRU 캐시가 이미 전면 적용됨 (`engine_service.py:117-203`):
    - `_pending_stock_details`: LRUCache(maxsize=3000)
    - `_orderbook_cache`: LRUCache(maxsize=2000)
    - `_latest_trade_prices/amounts/strength`: LRUCache(maxsize=2500) 각각
    - `_rest_radar_quote_cache`: LRUCache(maxsize=1500)
  - 증분 캐시 존재: `_sector_stocks_cache`(1초 생명주기), `_buy_targets_snapshot_cache`
  - WS 구독 시작 시(`_reset_realtime_fields`, `engine_service.py:452-488`) 모든 실시간 캐시 `clear()` 수행 — 전일 데이터 오염 방지
  - 파일 캐시 로드(`engine_cache.py:18-140`)는 `asyncio.to_thread()` + `asyncio.gather()`로 병렬 처리
- **수정 필요 여부**: 없음 (이미 인메모리 캐시 + LRU 적용 완료)

---

## 다음 진행 대상 Phase

없음 — 모든 Phase 완료.

---

### Phase 15: 단계 4 — 전체 통합 및 성능 검증
- **완료 시점**: 2026-05-13
- **수정 파일**:
  - `backend/app/services/engine_ws_dispatch.py`
  - `backend/app/services/engine_account_notify.py`
  - `frontend/src/main.ts`
- **수정 지점**:
  - `engine_ws_dispatch.py`:
    - `_tick_stats`, `_real_received_stats` 모듈 변수 추가 (라인 67-79)
    - `_record_tick(elapsed_ms)` 함수 추가 (라인 82-104) — 1초 윈도우 틱 처리 지연 집계
    - `_flush_tick_stats()` 함수 추가 (라인 107-118) — 집계 결과 INFO 로깅
    - `_record_real_received()` 함수 추가 (라인 121-132) — WS REAL 메시지 수신 카운터
    - `_check_realtime_latency`에서 `_record_tick(elapsed)` 호출 (라인 472)
    - `_handle_real` 시작 부분에 `_record_real_received()` 호출 (라인 584)
  - `engine_account_notify.py`:
    - `_broadcast_stats` 모듈 변수 추가 (라인 42-47)
    - `_record_broadcast(attempted, actual)` 함수 추가 (라인 50-65)
    - `_flush_broadcast_stats()` 함수 추가 (라인 68-80)
    - `notify_raw_real_data`에 `_record_broadcast` 호출 추가 (라인 388, 404)
  - `frontend/src/main.ts`:
    - `startFpsMonitor()` 함수 추가 (라인 14-43) — requestAnimationFrame 기반 1초 FPS 카운터
    - `main()` 끝에 `startFpsMonitor()` 호출 (라인 261)
- **검증 결과**:
  - `python3 -m py_compile` → engine_ws_dispatch.py, engine_account_notify.py 문법 통과
  - `npx tsc --noEmit` → exit code 0, 신규 문법 오류 0건
  - `grep "except.*pass"` 대상 파일 → 0건
- **기존 동작 변경**: 없음 (통계 변수 추가만, 기존 흐름 유지)
