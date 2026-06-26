# HANDOVER.md

## 완료 단계
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

## 현재 상태
- Settings Fallback 리팩토링 완료 검증됨
- 새로운 문제 보고: 공휴일 자동매매 차단 토글(holiday_guard_on)이 자동매수/자동매도 토글에 영향을 주는 현상

## 다음 단계
- 공휴일 자동매매 차단 토글 ↔ 자동매수/자동매도 토글 상호작용 문제 조사 및 수정

## 미해결 문제
### 1. 공휴일 자동매매 차단 토글이 자동매수/자동매도 토글에 영향

#### 조사 결과 (코드 기반)

**프론트엔드 (`frontend/src/pages/general-settings.ts`):**
- `shouldForceOff()` (줄 85-87): `!tradingDayLoading && !isTradingDay && !!vals.holiday_guard_on`
  - 비거래일 + holiday_guard_on ON → true 반환
- `shouldForceOff()` 적용 위치:
  - `handleMasterToggle()` (줄 374): 차단 + 다이얼로그 표시 → 마스터 토글 ON 불가
  - `handleWsToggle()` (줄 399): 차단 + 다이얼로그 표시 → WS 토글 ON 불가
  - 줄 972: `masterToggle?.setOn(forceOff ? false : ...)` → 시각적 OFF (vals不变)
  - 줄 974: `wsToggle?.setOn(forceOff ? false : ...)` → 시각적 OFF (vals不变)
- **자동매수 토글 (줄 259-269): shouldForceOff() 검사 없음** — 자유롭게 토글 가능
- **자동매도 토글 (줄 298-308): shouldForceOff() 검사 없음** — 자유롭게 토글 가능
- `updateAutoTradeDisabledStates()` (줄 423-428): holidayToggleRow만 비활성화, autoBuy/autoSell 행은 제어 안 함
- 줄 993: `autoBuyToggle?.setOn(!!r.auto_buy_on)` — forceOff 미적용
- 줄 1000: `autoSellToggle?.setOn(!!r.auto_sell_on)` — forceOff 미적용

**백엔드:**
- `_apply_holiday_guard_on_startup()` (`daily_time_scheduler.py:1064-1110`):
  - 기동 시 공휴일 + holiday_guard_on ON → time_scheduler_on, auto_buy_on, auto_sell_on, ws_subscribe_on 전부 False로 DB 저장
  - auto_off_by_holiday 플래그 설정 (DEFAULT_USER_SETTINGS에 없는 키)
- `_master_on()` (`auto_trading_effective.py:19-30`):
  - `holiday_guard_on` ON + 비거래일 → False 반환
  - 마스터가 OFF면 자동매수/매도 실행 안 됨

**문제 요약:**
1. 공휴일에 자동매수/매도 토글을 ON할 수 있지만, 마스터가 막혀 있어 실제로 동작 안 함 (사용자 혼란)
2. 줄 972에서 masterToggle을 시각적 OFF로 설정하지만 vals.time_scheduler_on은 업데이트 안 함 (UI/상태 불일치)
3. 자동매수/매도 토글에 shouldForceOff() 검사나 비활성화 처리가 없음
4. 정상 거래일에도 문제 발생 가능: _apply_holiday_guard_on_startup이 공휴일에 모든 플래그를 False로 저장했으므로, 다음 거래일에 사용자가 수동으로 다시 켜야 함

**수정 방향 (승인 필요):**
- 프론트엔드: 자동매수/매도 토글에도 shouldForceOff() 적용 또는 비활성화 처리
- 프론트엔드: 줄 972/974의 시각적 OFF 시 vals 값도 동기화
- 백엔드: daily_time_scheduler.py 줄 180, 185, 1072, 1086의 .get() 폴백을 직접 접근으로 변경 (이전 리팩토링에서 누락)
- auto_off_by_holiday 키를 DEFAULT_USER_SETTINGS에 추가 여부 결정

### 2. daily_time_scheduler.py 잔여 .get() 폴백 (이전 리팩토링에서 누락)
- 줄 180: `settings.get("holiday_guard_on", True)` → `settings["holiday_guard_on"]`
- 줄 185: `settings.get("ws_subscribe_on", True)` → `settings["ws_subscribe_on"]`
- 줄 1072: `settings.get("holiday_guard_on", True)` → `settings["holiday_guard_on"]`
- 줄 1086: `settings.get(k, True)` → `settings[k]` (time_scheduler_on, auto_buy_on, auto_sell_on, ws_subscribe_on)
- 줄 1087: `settings.get("auto_off_by_holiday", False)` → DEFAULT_USER_SETTINGS에 auto_off_by_holiday 추가 후 직접 접근
