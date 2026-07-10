# HANDOVER — SectorFlow

## 추후 논의 필요 (미결정)

### 업종순위 구독 정책 개선 검토 (2026-07-10)
- **상태**: 분석 완료, 구현 미결정 — 추후 재논의 예정
- **현재 구독 구조 (코드 확인 완료)**:
  - 0B(현재가/대비/등락률/거래대금/체결강도): `_filtered=True`(거래대금 필터 통과) 종목 + 보유종목, 200종목 한도 (`engine_ws_reg.py:257`). 매수후보 테이블 전체 종목(통과/차단 무관) 이미 수신 중
  - 0D/PGM(호가잔량비/프순매): `guard_pass=True` 종목만, 30초 지연 해지 (`engine_sector_confirm.py:290,23`). 차단 종목은 5일고가/거래대금 가산점만 부여, 잔량비/프순매 가산점 제외 (`buy_filter.py:221,224`)
  - 업종 순위: `sector_max_targets`(상위 N개) + `sector_min_rise_ratio_pct`(상승비율 미만 rank=0) — 상승비율 미만 업종은 순위에서 제외일 뿐 구독 해지 아님 (`engine_sector_confirm.py:162-172`)
- **제안 1 (매수후보 0D/PGM 구독 확대)**: `guard_pass` 조건 제거 → 통과/차단 전체 0D/PGM 구독. 수정 2곳: `engine_sector_confirm.py:290`, `buy_filter.py:221,224`. 세션 증가량은 실제 통과/차단 비율 로그 확인 필요
- **제안 2 (sector_max_targets 제거, 상승비율 자동 필터링)**: 상승비율 컷오프는 이미 구현됨. max_targets 제거 시 강세장 업종 수 폭증 → 0B 200한도 압박. max_targets를 상한선으로 유지 권장
- **정정 사항 (사용자 피드백)**:
  1. 상승비율 미만 업종은 순위 제외 로직이지 구독 해지가 아님 — 0B는 `_filtered` 기반이므로 rank=0 업종도 0B 유지
  2. 재매수차단 OFF 시 금일매수 종목도 매수 후보 유효 → "보유중/금일매수 구독 제외"는 `rebuy_block_on` 설정과 충돌. 단, `buy_filter.py:194`는 `rebuy_block_on` 설정과 무관하게 항상 금일매수를 차단 처리함 — 이 자체가 별개 모순
  3. 매수후보 테이블 모든 종목(통과/차단 무관)은 이미 0B 실시간 데이터 수신 중 — 0D/PGM만 guard_pass 기반

## 직전 완료 작업
- **2026-07-10: 업종순위 수신율 임계값 우회 버그 수정 — SSOT 게이트로 5개 우회 경로 차단**
  - 목적: 사용자가 설정한 수신율 임계값(`sector_start_threshold_pct`)에 도달하기 전에 업종순위가 프론트엔드에 표시되는 버그. Phase 1 루프의 지역 변수 게이트만으로는 5개 외부 경로가 임계값 체크 없이 sector-scores를 전송했음
  - 근본 원인: `_sector_recompute_loop_impl` Phase 1의 `phase1_completed` 지역 변수가 임계값 통과 상태의 유일한 게이트. 외부 5개 경로(`_login_post_pipeline`, `apply_settings_change`, `_on_krx_market_open`, `_on_krx_after_hours_start`, `_send_initial_snapshot_delayed`)가 `recompute_sector_summary_now()` → `notify_desktop_sector_scores(force=True)` 또는 `ws_manager.send_to()`로 임계값과 무관하게 sector-scores 브로드캐스트
  - 수정: `_sector_threshold_passed` 전역 SSOT 플래그 + 3개 함수(`is_sector_threshold_passed` / `reset_sector_threshold` / `mark_sector_threshold_passed`) 추가
    - `pipeline_compute.py`: SSOT 플래그 + 함수 정의, Phase 1 통과 시점에 `mark_sector_threshold_passed()` 호출
    - `daily_time_scheduler.py`: `_on_ws_subscribe_start()` / `_init_ws_subscribe_state()` WS 구간 진입 시 `reset_sector_threshold()`, `_on_ws_subscribe_end()` / `_ws_disconnect_only()` 구간 종료 시 `mark_sector_threshold_passed()` 호출
    - `engine_account_notify.py`: `notify_desktop_sector_scores()` 진입부에 게이트 추가 — 미통과 시 `prev_scores` 클리어 후 return (임계값 통과 후 첫 전송이 전체 스냅샷이 되도록 보장)
    - `ws.py`: 초기 스냅샷 sector-scores 전송 블록에 동일 게이트 추가
  - 영향: WS 구독 구간 내 임계값 미달 시 sector-scores 전송 차단, 비-WS 구간은 기본값 True로 기존 동작 유지, 내부 계산(`recompute_sector_summary_now`)은 수행되므로 `_filtered` 플래그/구독 파이프라인 정상 동작, 수신율 표시(`receive-rate` 이벤트)는 영향 없음
  - 검증: 신규 테스트 7개(`TestSectorThresholdGate` 5 + `TestNotifySectorScoresGate` 2) 통과, 기존 테스트 1077개 전체 통과, 프론트엔드 빌드 성공, 런타임 기동 검증 완료
  - 테스트 파일: `test_daily_time_scheduler.py`에 `initialize_queues()` 추가 (lazy import of pipeline_compute 시 모듈 레벨 `get_broadcast_queue()` 호출 대응)
  - 커밋: `accca2b` push 완료
- **2026-07-10: exchange_calendars 교체 — korean_lunar_calendar 기반 직접 구현 (~109MB 절감 + 제헌절 버그 수정)**
  - 목적: exchange_calendars가 pandas(70MB)+numpy(33MB) 등 ~109MB 의존성을 끌어오는데, 코드베이스에서 사용처는 `trading_calendar.py`의 `_generate_trading_days_from_xkrx()` 1곳만. 연 1회 캐시 생성 시에만 사용하므로 경량화 필요
  - 추가 발견: exchange_calendars XKRX 캘린더가 제헌절(7/17, 2026년부터 공휴일 재지정)을 반영하지 않는 버그 확인 — DB 캐시에 2026년 7/17이 거래일로 잘못 등록되어 있었음 (246일 → 정상 245일)
  - `trading_calendar.py`: `_generate_trading_days_from_xkrx()` 제거 → `_generate_trading_days()` + `_compute_holidays()` 직접 구현
    - 고정 양력 휴일 9종: 신정, 삼일절, 근로자의날, 어린이날, 현충일, 광복절, 개천절, 한글날, 크리스마스
    - 제헌절: 2026년부터 공휴일 재지정 반영 (exchange_calendars는 2007년 end_date로 누락)
    - 음력 휴일 3종: 설날(3일), 추석(3일), 부처님오신날 — `korean_lunar_calendar`로 음력→양력 변환
    - 대체 공휴일: 2021년 확대 규칙 (설날/추석=일요일만, 어린이날/삼일절/광복절/개천절/한글날/부처님오신날=토/일요일, 제헌절=2026~)
    - KRX 전용 연말 휴일: Dec 31 (주말 시 직전 금요일)
    - 임시 공휴일/선거일: `_MANUAL_HOLIDAYS` dict 수동 관리 (2024: 국회의원선거/국군의날, 2025: 임시공휴일/대통령선거)
  - `requirements.txt`: `exchange_calendars>=4.0.0` 제거 → `korean-lunar-calendar>=0.3.1` 명시 추가
  - `mypy.ini`: `[mypy-exchange_calendars]` 섹션 제거
  - `stock_tables.py`: 주석 "exchange_calendars 연 1회 갱신" → "korean_lunar_calendar 기반 연 1회 갱신"
  - `ARCHITECTURE.md`: 인프라 섹션 "exchange_calendars (거래일)" → "korean_lunar_calendar (음력→양력 변환, KRX 거래일 계산)"
  - venv: exchange_calendars, pandas, numpy, pyluach, toolz, tzdata 6개 패키지 uninstall — site-packages 195MB → 86MB (109MB 절감)
  - DB 캐시 재생성: 2026년 245일(제헌절 수정), 2027년 247일. 백업: `stocks.db.bak.20260710_171552`
  - 검증: 2024-2025년 휴일 exchange_calendars와 100% 일치, 2026년은 제헌절 1일 추가(정확), pytest 1070/1070 통과 (신규 45건 포함)
  - 테스트: `test_trading_calendar.py` 신규 — 2024-2027년 휴일/거래일 수/대체공휴일/제헌절/임시공휴일/엣지케이스 45건
  - 임시 공휴일 관리: 새 선거일/임시공휴일 발생 시 `_MANUAL_HOLIDAYS` dict에 날짜 추가 후 `refresh_trading_days_for_year()` 호출
  - 커밋: `b111496` push 완료
- **2026-07-10: 5일고가 돌파 표시 분리 — 현재가 필드 배경 → ▲ 아이콘(좌측) + 5일고가 필드 초록 배경**
  - 목적: 매수후보 페이지에서 5일고가 돌파 종목의 현재가 셀에 초록 배경(`COLOR.successBg`)이 표시되는데, 실시간 시세 변경 시 노란 플래시 효과(`composite: 'replace'`)가 같은 셀 배경에 겹쳐 초록→노랑→투명→초록 깜빡임 발생. 두 시각적 효과의 충돌 제거
  - 근본 원인: `buy-target.ts`의 `cur_price` 컬럼이 `flash: true`이면서 동시에 5일고가 돌파 시 배경색 적용. `data-table.ts`의 `triggerFlash`가 `composite: 'replace'`로 동작하여 인라인 배경색을 무시하고 keyframe 값으로 대체
  - `buy-target.ts cur_price 컬럼 (26-41줄)`: 초록 배경 제거. 돌파 시 `justifyContent`를 `space-between`으로 변경하여 ▲ 아이콘을 셀 좌측 끝에, 가격 숫자를 우측 끝에 배치. 아이콘: `COLOR.up`(빨강 #f44336), `FONT_SIZE.body`(13px), `FONT_WEIGHT.bold`(700). HTS 표준 기호 ▲(U+25B2) 사용 — `ui-styles.ts`의 `changeArrow` 함수와 동일 기호
  - `buy-target.ts high_5d 컬럼 (95-104줄)`: `createNumberCell` 반환 셀에 돌파 시 `COLOR.successBg` 배경 적용. `flash` 미적용 컬럼이므로 플래시 충돌 없음
  - `createPriceCell` 미수정 → `sell-position.ts`, `sector-stock.ts` 영향 없음
  - `data-table.ts` 미수정 → 플래시 로직 변동 없음
  - HTS 참고: 키움 영웅문 차트에서 신고가 돌파 시 ▲ 화살표 표시. 시세표에서는 별도 컬럼/배지로 분리. TradingView/Trading Dashboard Kit도 가격 플래시와 돌파 신호를 서로 다른 시각적 요소로 분리하는 공통 패턴
  - 검증: tsc 타입체크 0 에러, vite build 통과 (58 모듈 1.76s)
  - 커밋: (이번 커밋)
- **2026-07-10: 현재가 플래시 효과 복원 — Web Animations API + 일반설정 ON/OFF 토글**
  - 목적: 과거 3차례 구현/제거된 현재가 플래시 효과와 ON/OFF 토글 UI를 Web Animations API 기반으로 복원. reflow 강제/setTimeout/class 관리 없이 부하 거의 0으로 실시간 가격 변동 시각화
  - 히스토리 조사: 1차(행 단위 빨강/파랑, 5cba9e3에서 제거), 2차(셀 단위 노랑, 17a779d에서 추가), 3차(flash-anim.ts 모듈 분리 + 토글, 864c385에서 리팩토링 → 3e6da0c에서 제거). 세 번 모두 기능 자체 버그/성능 문제가 아닌 부수적 코드 정리로 제거됨
  - `data-table.ts`: `ColumnDef.flash?: boolean` 옵션 추가 + `triggerFlash(cell)` 헬퍼 (Web Animations API `cell.animate()` 1줄). `composite: 'replace'`로 연속 틱 시 이전 애니메이션 자동 대체. `uiStore.getState().settings.ui_price_flash_on === false` 체크로 토글 반영. 4개 diffing 지점 (fixed mode key 기반/index 기반/updateItemByKey + virtual scroll renderRow)에 트리거 삽입
  - `ui-styles.ts`: `makePriceColumn`에 `flash: true` 추가 (업종별종목실시간시세 페이지 적용)
  - `sell-position.ts`: 커스텀 `cur_price` 컬럼에 `flash: true` 추가 (보유종목 페이지)
  - `buy-target.ts`: 커스텀 `cur_price` 컬럼에 `flash: true` 추가 (매수후보 페이지)
  - `general-settings.ts`: '실시간 데이터 통신' 섹션 하단에 '실시간 현재가 플래시 효과' ON/OFF 토글 UI 추가. `createToggleBtn` + `settingsMgr.saveSection({ ui_price_flash_on: next })` 패턴 (기존 토글과 동일). `syncFromSettings()`에 `uiFlashToggle?.setOn(r.ui_price_flash_on !== false)` 동기화 추가
  - `settings_defaults.py`: `DEFAULT_USER_SETTINGS`에 `"ui_price_flash_on": True` 추가 (기본값 ON)
  - `types/index.ts`: `AppSettings`에 `ui_price_flash_on: boolean` 명시 (인덱스 시그니처로 이미 호환되나 가독성 향상)
  - `index.html`: 잔존 dead CSS (`@keyframes cell-flash`, `.cell-flash`) 제거 — Web Animations API 사용으로 CSS 불필요
  - 백엔드 스키마 변경 불필요: `integrated_system_settings` 테이블이 key-value 구조, `PATCH /api/settings/{field_name}`가 모든 필드 범용 저장
  - 검증: tsc 타입체크 0 에러, vite build 통과 (58 모듈 2.28s), eslint 0건, 백엔드 런타임 기동 정상 (238ms 부트, 잔여 프로세스 없음), `DEFAULT_USER_SETTINGS` 확인 `ui_price_flash_on=True`
  - 커밋: 3df2bc0
- **2026-07-10: 매수후보 거래대금 가산점 비교 범위 확대 — 통과 종목만 → 전체 종목(통과+차단) + 차단 종목 5일고가 가산점 부여**
  - 목적: 거래대금 가산점이 통과 종목끼리만 상대비교되어 종목 수가 적을 때 가산점 왜곡 가능 → 매수후보 테이블 전체 종목(통과/차단 무관)으로 비교 범위 확대
  - `buy_filter.py:198-209`: 거래대금 순위 계산에서 `guard_pass` 필터 제거 → `all_stocks` 전체로 순위 계산 (보유/금일매수 종목도 포함)
  - `buy_filter.py:211-230`: 차단 종목 가산점 스킵 로직 제거 → 차단 종목도 `calculate_boost_score` 호출. 잔량비(`boost_order_ratio_on and not _is_blocked`), 프순매(`boost_program_net_buy_on and not _is_blocked`)는 구독 세션 제한으로 통과 종목만 유지. 5일고가(`boost_high_on`)와 거래대금(`boost_trade_amount_rank_on`)은 차단 종목에게도 부여
  - `hotStore.ts:111-118`: `recalcTradeAmountRank`에서 `guard_pass` 필터 제거 → 전체 `targets`로 순위 계산 (백엔드와 동일 로직)
  - `buy_filter.py:57`: 주석 "매수 후보 내 보유 제외 후" → "매수후보 테이블 전체 종목 중"으로 수정
  - `test_buy_filter.py`: 2개 테스트 업데이트 — `test_trade_amount_rank_excludes_held_codes` → `test_trade_amount_rank_includes_held_codes` (보유 종목이 전체 1위면 rank 0), `test_blocked_stock_boost_score_zero` → `test_blocked_stock_receives_high_breakout_boost` (차단 종목 5일고가 돌파 시 가산점 5.0 부여 확인)
  - 정렬 영향 없음: `is_blocked`가 정렬 1순위이므로 차단 종목은 항상 통과 종목 뒤, 가산점이 매수 우선순위에 영향 주지 않음
  - 검증: pytest 57/57 통과, vite build 통공 (1.03s), 백엔드 런타임 기동 정상 (업종 재계산/구독 완료, 에러 없음)
  - 커밋: (이번 커밋)
- **2026-07-10: 검색 결과 강조 방식 통일 — 4페이지 outline: 2px solid COLOR.down 일원화 + COLOR.highlight 상수 삭제 + dead code 정리**
  - 목적: 검색어 입력 시 검색된 행 강조 방식이 페이지마다 불일치 (sector-stock=노랑 배경, buy-target/stock-detail=강조 없음, stock-classification=dead code) → `outline: 2px solid COLOR.down`(#1e88e5, 파랑)로 전 페이지 통일
  - `sector-stock.ts`: `background: COLOR.highlight`(노랑 배경) → `outline: 2px solid COLOR.down`(파랑 테두리)로 변경, 비매칭 행 `outline: 'none'` 처리
  - `buy-target.ts`: `rowStyle` 추가 — `searchTerm` 있을 때 모든 표시 행(=매칭 행)에 `outline: 2px solid COLOR.down` 적용, 없을 때 `outline: 'none'`
  - `stock-detail.ts`: `rowStyle` 추가 — `searchQuery` 있을 때 모든 표시 행에 `outline: 2px solid COLOR.down` 적용, zebraStriping과 충돌 없음
  - `stock-classification.ts`: `highlightStockCode` dead code 정리 (3곳) — 변수 선언(line 87), null 할당(line 778/1515), rowStyle 분기(line 1019-1021) 제거. `highlightStockCode`는 한 번도 non-null 값이 할당된 적 없었음
  - `ui-styles.ts`: `COLOR.highlight`(#fff9c4, 노랑) 상수 삭제 — 사용처 0건 확인 후 제거
  - outline 선택 이유: `<tr>` 요소에서 `border`는 box model에 추가되어 레이아웃 시프트 발생, `outline`은 box model 외부에 그려져 레이아웃 영향 없음. `sector-ranking-list.ts` 업종 선택 강조와 동일 패턴
  - 검증: tsc 타입체크 0 에러, vite build 통과 (58 모듈 712ms), `COLOR.highlight` grep 0건, `highlightStockCode` grep 0건
  - 커밋: (이번 커밋)
- **2026-07-10: 기간 선택 박스 공통 컴포넌트 신규 생성 + 수익현황/수익상세 일원화 + 검색입력창 라벨/placeholder 일관성 통일**
  - 목적: 수익현황/수익상세 페이지의 기간 선택 박스가 인라인 하드코딩(2곳)으로 스타일 분산 + 크기 너무 작음(padding 2px 4px, font 11px) → 공통 컴포넌트 생성 후 일원화 + 크기 증가
  - `date-range-input.ts` (신규): `createDateRangeInput({ from, to, label, compact, onChange })` API, 반환 `{ el, getValue(), setValue() }`, 기본 크기 padding 6px 8px / fontSize 13px / minWidth 120px, compact 모드 padding 4px 6px / fontSize 12px / minWidth 100px, `~` 구분자 + 시작/종료 date input 한 쌍, change 이벤트 → onChange 콜백
  - `canvas-profit-chart.ts`: 인라인 dateFromInput/dateToInput 2개 + dateSep span 제거 → `createDateRangeInput` 사용, `setDateRange()` API → `dateRangeInput.setValue()` 위임
  - `profit-detail.ts`: 모듈 변수 `dateFromInput`/`dateToInput` 2개 → `dateRangeInput: DateRangeInputApi` 1개로 통합, `filterByDate`/`filterByDateRange`/`updateTabLabels`/`updateStatistics`/`showTable`/`clearBtn`/`onTotalClick` 모두 `getValue()`/`setValue()` API 사용, 인라인 date input 2개 + dateSep + filterLabel 제거 → `createDateRangeInput` label 옵션 사용, 날짜 필터 change 이벤트를 컴포넌트 onChange로 이관
  - 검색입력창 일관성 통일: `profit-detail.ts` `compact: true` 제거 → 기본 모드(padding 4px 26px, fontSize 13px, 🔍 아이콘 + ✕ 클리어버튼)로 다른 6개 인스턴스와 통일
  - 라벨 텍스트 통일: `'종목명 / 코드'` → `'종목명/코드'` (슬래시 양옆 공백 제거) 5곳 일괄 변경 (profit-detail, stock-classification, stock-detail, buy-target, sector-stock)
  - 안내 글자(placeholder) 통일: `종목명/코드 검색`으로 6곳 일괄 변경 — 기존 2종 혼재(`종목명 / 코드 검색` 3곳, `종목명 또는 코드 검색` 2곳) + search-input.ts 기본값 1곳
  - 아키텍처: 원칙 10 (SSOT — 기간 선택 UI 단일 소스), 원칙 22 (파생 데이터 — dateRangeInput.getValue()로 모든 날짜 접근 일원화)
  - 검증: tsc 타입체크 0 에러, vite build 통과 (58 모듈 1.78s), 잔여 `dateFromInput`/`dateToInput` 외부 참조 0건, 잔여 `종목명 / 코드`/`종목명 또는` 0건
  - 커밋: (이번 커밋)
  - 목적: 각 페이지가 검색 입력란의 라벨/색상/스타일을 자체 구현하여 7개 검색란 스타일 분산 → 공통 컴포넌트 `search-input.ts`에 기능 내장 후 전 페이지 통일
  - `search-input.ts`: `label`/`labelColor`/`compact` 옵션 추가, `width` 기본값 `100%`→`180px`, input에 `sf-search-input` 클래스 추가, 텍스트 색상 `COLOR.code` 명시, 포커스 언더라인 강조 (`boxShadow: inset 0 -2px 0 borderColor`, HTS 스타일), compact 모드(아이콘/클리어버튼 off, padding 2px 4px, fontSize 12px), 라벨 폰트 `FONT_SIZE.section`(14px) 통일
  - `index.html`: `.sf-search-input::placeholder { color: #9e9e9e; }` CSS 추가 (COLOR.disabled 통일 — JS inline style로는 ::placeholder 설정 불가)
  - `sector-stock.ts`: 자체 라벨 span 2개(stockSearchWrapper/sectorSearchWrapper) 제거, 컴포넌트 `label` 옵션 사용 (종목명/코드 파랑, 업종명 주황), width 180px 기본값 적용
  - `stock-classification.ts`: 종목 검색(파랑 라벨+border, width 100%), 대상업종 검색(주황 라벨+border, width 100%) 추가
  - `stock-detail.ts`: 라벨 "종목명 / 코드" + 파랑 border + width 180px 통일 (검색란은 line 150에 이미 존재, 스타일 통일 작업)
  - `buy-target.ts`: 자체 라벨 span 제거, 컴포넌트 `label` 옵션 사용
  - `profit-detail.ts`: stockFilterInput을 `createSearchInput` compact 모드로 교체, `.value.trim()`→`.getValue()` (3곳), 자체 "종목:" 라벨 제거, width 180px 통일
  - 색상 구분 (검색 대상별): 종목명/코드=🔵COLOR.down(파랑), 업종/섹터=🟠COLOR.warning(주황)
  - 검증: tsc 타입체크 0 에러, vite build 통과 (57 모듈), vitest 109/109 통과
  - 커밋: (이번 커밋)
- **2026-07-10: 프론트엔드 색상 체계 통일 — 하드코딩 색상 ~190곳 COLOR 상수로 일원화 + secondary→tertiary 통합**
  - 목적: 28개 파일에 분산된 하드코딩 색상(~190곳)을 `ui-styles.ts` COLOR 상수로 통일, `secondary`(#888)를 `tertiary`(#666)로 통합하여 라벨/설명문 색상 일원화
  - `ui-styles.ts`: COLOR 상수 16개 추가 — `white`, `groupHeader`, `border`/`borderDark`/`borderLight`/`borderGrid`/`borderRow`, `zebra`/`surfaceLight`/`hoverBg`/`surface`/`highlight`/`inactiveBg`/`toggleOff`; `secondary` 제거; `CELL_BORDER`·cellStyle·disabled option 하드코딩 교체
  - `secondary`→`tertiary` 일괄 교체: 12개 파일 33곳 (sed 일괄 처리)
  - 하드코딩 색상 교체: 28개 파일 ~190곳 — 텍스트(`#aaa`→disabled, `#999`→disabled, `#111`→neutral, `#222`→neutral, `#666`→tertiary, `#1a1a1a`→neutral, `#333`→neutral, `#616161`→tertiary, `#1a237e`→groupHeader, `#fff`→white), 보더(`#ccc`→border, `#ddd`→borderDark, `#eee`→borderLight, `#d0d0d0`→borderGrid, `#e5e7eb`→borderRow, `#f5f5f5`→neutralBg, `#f0f0f0`→hoverBg, `#e0e0e0`→inactiveBg, `#d0d5dd`→borderGrid), 배경(`#f9f9f9`→zebra, `#fafafa`→surfaceLight, `#f8f9fa`/`#f8f8f8`/`#f7f8fa`→surface, `#fff9c4`→highlight, `#6c757d`→toggleOff, `#dee2e6`→inactiveBg)
  - cssText/template literal 문자열 내 `#xxx`도 `${COLOR.xxx}` 형식으로 교체 (sidebar, shell, header, router, canvas-sector-donut, canvas-profit-chart, profit-overview, profit-detail, profit-shared, sector-ranking-list, settings-common)
  - 제외 (도메인 특화): 차트 팔레트 20색, 점수 색상 3종(#e67e22/#2c3e50/#7f8c8d), 브로커 브랜드(#FF8C00/#DC143C), 슬라이더(#0d6efd/#e9ecef), 다크테마(DARK_FIELD_STYLE #1e1e1e/#555/#ddd), 부트스트랩 칩(#f3e5f5/#6a1b9a), success hover(#157347)
  - 아키텍처: 원칙 10 (SSOT — 색상 단일 소스 진리), 원칙 22 (파생 데이터 모델 — 보더/배경 계층화)
  - 검증: tsc 타입체크 0 에러, vite build 통과 (57 모듈 1.97s), vitest 109/109 통과, grep 재검색 — `COLOR.secondary` 0건, 비제외 하드코딩 색상 0건
  - 커밋: (이번 커밋)
- **2026-07-10: 수익상세/매도설정 페이지 데이터 정합성 근본 수정 + 매수일자 최초 매수일 표시 + 매수일자 색상 변경**
  - 문제 1: 수익상세 페이지(매수 8건/매도 6건)와 매도설정 페이지(보유종목 5종목) 간 데이터 불일치
  - 원인 1: `trade_history._buy_history/_sell_history`(수익상세 원천)와 `dry_run._test_positions`(보유종목 원천)가 이중 상태로 관리, `record_buy/record_sell`(동기)과 `_apply_buy/_apply_sell`(비동기 0.1초 후)이 원자적으로 결합되지 않아 diverge
  - 수정 1 (SSOT 일원화): `dry_run._test_positions`를 파생 캐시로 격하 — `_positions_dirty` 플래그 추가, `_load_positions()` → `_refresh_positions_if_dirty()`로 변경 (dirty 시 `build_positions_from_trades()`로 재구축, cur_price/stk_nm 등 비파생 필드 보존)
  - 수정 1: `_apply_buy/_apply_sell`에서 `_test_positions` 직접 수정 제거, `settlement_engine`만 갱신
  - 수정 1: `trade_history._insert_trade()`/`clear_test_history()`/`_reset_global_state()`에서 `dry_run._positions_dirty = True` 설정 (캐시 무효화)
  - 수정 1: `engine_lifecycle.py` `_load_positions()` → `_refresh_positions_if_dirty()` 교체
  - 문제 2: 보유종목 매수일자가 모두 오늘로 표시됨 (최초 매수일이 아님)
  - 원인 2: `build_positions_from_trades()`가 `_buy_history`(DESC 정렬)를 순회하며 첫 발견 매수의 date를 buy_date로 설정 — DESC이므로 첫 발견 = 최근 매수일. 이후 더 오래된 매수를 만나도 buy_date 갱신 안 함. `get_earliest_buy_date()`도 같은 버그
  - 수정 2: `build_positions_from_trades()` `if pos:` 분기에 `buy_date` 최초 매수일 추적 로직 추가 (문자열 비교 `rec_date < pos["buy_date"]`)
  - 수정 2: `get_earliest_buy_date()`를 전체 순회하며 최소 date 추적하도록 수정
  - 문제 3: 매수일자 컬럼 색상 — 당일 빨강(강조), 과거 회색
  - 수정 3: `sell-position.ts` 매수일자 컬럼 색상 변경 — 당일=`COLOR.neutral`(#333, 기본 텍스트), 과거=`COLOR.disabled`(#9e9e9e, 연한 회색)
  - 데이터 검증: 5종목(161390/000990/066570/000270/035420) 모두 2026-07-10 매수, 매도 기록 없음 → buy_date=오늘이 정확함. 전체 44건 매수/39건 매도, 잔여 5종목 정합
  - 검증: 런타임 시작 정상 (에러 없음), 백엔드 테스트 1025 passed, 프론트엔드 build 성공
  - 커밋: (이번 커밋)
- **2026-07-10: 수익현황 페이지 빈 데이터 차트/도넛 stale state 근본 수정 — 더미 데이터 생성 로직 완전 제거 + currentSegments 초기화**
  - 문제: 날짜 범위에 매도 데이터가 없어도 일별 수익률 차트에 더미 막대/라인이 표시되고, 업종별 수익 분포 도넛 우측 범례에 이전 데이터가 잔류
  - 원인: `canvas-profit-chart.ts`의 `generateDummyData()` 폴백 (원칙 20 위반), `canvas-sector-donut.ts`의 `render()`에서 `currentSegments` 미초기화 (원칙 22 위반)
  - `canvas-profit-chart.ts`: `generateDummyData()` 29줄 삭제, `refreshInternal()` 더미 분기 제거 + `hasVisibleBar` 판정을 `pnl !== null && pnl !== 0`에서 `pnl === null`로 수정 (손익 0원 정상 매도 폴백 버그 제거), overlay 텍스트 "(샘플 데이터)" 제거
  - `canvas-sector-donut.ts`: `render()`의 `!hasData` 분기와 `totalAbs === 0` 분기에 `currentSegments = []`, `segmentRects = []` 초기화 추가
  - `profit-overview.ts`: `initState`/`filteredSellHistory` 할당을 `createSectorDonut` 전으로 이동, 도넛 초기 data를 `filteredSellHistory`로 변경 (초기 전체 데이터 렌더링 → 덮어쓰기 깜빡임 방지)
  - 아키텍처: 원칙 10 (SSOT — 더미 제2 소스 제거), 원칙 20 (폴백 금지), 원칙 21 (사용자 투명성 — "샘플 데이터" 표시 제거), 원칙 22 (데이터 정합성 — 파이프라인 단계 간 currentSegments 일관성)
  - 검증: tsc 타입체크 통과, vite build 통과 (57 모듈), vitest 109/109 통과
  - 커밋: (이번 커밋)
- **2026-07-10: 보유종목 테이블 매수일자 컬럼 추가 — trade_history SSOT → WS → hotStore → UI 전체 파이프라인**
  - 목적: 매도설정 페이지 보유종목 테이블에 매수일자 표시 — 당일 매수 빨강, 과거 회색 조건부 스타일링
  - 백엔드: `trade_history.py` `build_positions_from_trades()` buy_date 파생 + `get_earliest_buy_date()` 헬퍼 추가 (실전모드 REST 보완용)
  - 백엔드: `dry_run.py` `_apply_buy()` 신규 position에 buy_date 추가, `engine_account.py` `_broadcast_account()` 실전모드 buy_date 주입
  - 백엔드: `engine_account_notify.py` `_POSITION_CMP_KEYS`, `_MIN_POSITION_KEYS`에 buy_date 추가
  - 프론트엔드: `types/index.ts` Position에 `buy_date?: string` 추가, `sell-position.ts` 매수일자 컬럼 추가 + 컬럼 순서 조정
  - 컬럼 순서: 순번→종목코드→종목명→현재가→매수가→매수금액→평가손익→수익률→수량→매수일자
  - 아키텍처: 원칙 10 (SSOT — trade_history date 필드에서 파생), 원칙 18 (테스트모드 동등성), 원칙 20 (폴백 금지), 원칙 22 (파생 데이터 모델)
  - 검증: py_compile 4파일 성공, tsc --noEmit 성공, vite build 성공, 런타임 기동 정상 (966ms, 에러 없음), test_dry_run_fill_event 29 passed
  - 커밋: `77d1d3c` push 완료
- **2026-07-10: 매수후보 페이지 검색 입력란 위치 재조정 — 좌측 상단, 주문가능금액 배지 하단**
  - 변경 파일: `frontend/src/pages/buy-target.ts` 1개
  - 검증: `npm run typecheck` 통과, `npm run test` 109 passed
  - 커밋: `d4b3d40` push 완료

## 현재 상태
- **백엔드**: 유령 매도 기록(id=144) 삭제 완료, 유령 포지션 재발 방지 예방 조치 구현 완료 (근본 원인은 미해결), boost_order_ratio_pct 422 오류 수정 완료, Settlement Engine 리팩토링 완료, RiskManager 리팩토링 Phase 1 완료, 보유종목 buy_date 파생·브로드캐스트 구현 완료, exchange_calendars 교체 완료 (korean_lunar_calendar 기반 직접 구현, ~109MB 절감, 제헌절 버그 수정)
- **프론트엔드**: 더미 데이터 삭제 완료, 차트 툴팁 잘림 수정 완료, 매수후보 페이지 주문가능금액 배지·검색 입력란 추가 완료, 보유종목 테이블 매수일자 컬럼 추가 완료, 수익현황 페이지 빈 데이터 차트/도넛 stale state 근본 수정 완료, 프론트엔드 색상 체계 통일 완료 (하드코딩 ~190곳 COLOR 상수화 + secondary→tertiary 통합), 검색 입력란 공통 컴포넌트 통일 완료 (5페이지 7개 인스턴스 + label/compact 옵션 + 포커스 언더라인 + placeholder 색상), `npm run build` 통과
- **Git**: 커밋 `b111496` push 완료 (exchange_calendars 교체)

## 다음 단계
- **1순위: 유령 포지션 근본 원인 심층 조사 (별도 세션)**:
  - 과거 005930 유령 포지션의 정확한 발생 시점 및 경로 추적
  - WAL 체크포인트 타이밍, `_save_positions_worker` 실행 시점 등 DB 레벨 분석
  - `docs/ghost_position_investigation.md` [A]~[I] 미조사 항목 참조
- **2순위: 브라우저 실제 화면 확인** — 장중에 매수후보 테이블에서 SK하이닉스(000660) 하이라이트 깜빡임 없는지 확인 + 매수/매도호가잔량비율 슬라이더 422 미발생 확인

## 미해결 문제
- **유령 포지션 005930 (avg_price=70,100) — 근본 원인 미해결, 재발 방지 조치 + 유령 매도 기록 삭제 완료**
  - 상세 조사 기록: `docs/ghost_position_investigation.md`
  - 재발 방지 조치 (2026-07-10 구현): `test_positions` 테이블 제거, `trades` 기반 SSOT 전환, `execute_sell()` 런타임 가드
  - 유령 매도 기록 삭제 (2026-07-10): `trades` id=144 삭제, 수익 통계 정정 완료
  - 근본 원인 미해결: 과거 005930 유령 포지션의 정확한 발생 시점 및 경로는 미추적
  - 미조사 항목 (`docs/ghost_position_investigation.md` [A]~[I] 참조):
    - [A] 14:00 shutdown 시 DB close 누락 확인 (app.py shutdown 로그 유무)
    - [C] WAL 파일 상태 확인 (`ls -la backend/data/stocks.db-wal`)
    - [D] 14:24 "database is locked" 에러 원인 — 단일 연결인데 왜 lock?
    - [G] 외부 프로세스에 의한 DB 직접 조작 가능성 (14:32~15:52 공백 시간)
    - [H] 70,100 값의 출처 역산 — 07-09 005930 매수 체결가들로 평균가 계산 불가 확인
    - [I] WAL checkpoint 타이밍 이슈 — 이전 데이터 복원 가능성
- **체결지연 50ms 초과 WARNING 7건** (2026-07-08 13:26~ 런타임 기동 중 발생)
  - `trading_2026-07-08.log:9597~9609` — 50~143ms 지연 7건 (200ms 초과 없음)
  - 조사 필요: `_handle_real_01_tick` await 체인 프로파일링, 지연 발생 위치 식별

## 테스트 실행 원칙 (필수 준수)

### 1. 실행 명령어 (통일)
```
python -m pytest backend/tests/[파일명] -v --timeout=15 --timeout-method=signal
```
- `timeout_method = signal` 필수 — `thread` 방식은 asyncio C-level wait를 interrupt하지 못해 hang 시 프로세스가 영구 블록됨
- `pytest.ini`에 전역 설정되어 있으므로 CLI에서 생략 가능

### 2. 자동 hang 체크 원칙 (에이전트 필수 강제 — 수동 개입 금지)
- **a. 10초마다 진행 상태 자동 체크**: 테스트 실행 후 `command_status`로 주기적 확인
- **b. 10초 이상 로그/출력 멈추면 즉시 hang 간주**: 대기 없이 강제 종료 결정
- **c. hang 감지 시 즉시 프로세스 강제 종료**: SIGTERM/Ctrl+C로 프로세스 종료
- **d. hang 원인 자동 분석**: 종료 후 로그/코드 분석하여 원인 보고
- **e. 위 모든 과정은 에이전트가 자동 수행**: 사용자 확인 대기 금지, 수동 개입 금지
- 정상 완료: "✅ N passed in N.Ns"
- hang 감지: "❌ 10초 이상 응답 없음 — 강제 종료 및 원인 분석 시작"

### 3. 테스트 hang 방지 코딩 원칙 (근본 원인별)

#### 원인 A: 실제 asyncio 동기화 프리미티브 (Lock/Event/wait_for)
- **금지**: 테스트에서 실제 `asyncio.Lock()`, `asyncio.Event()`, `asyncio.wait_for()` 사용
- **해결**: `MagicMock` + `AsyncMock`으로 교체
  - Lock: `lock.__aenter__ = AsyncMock(return_value=lock)`, `lock.__aexit__ = AsyncMock(return_value=None)`
  - Event: `ev.wait = AsyncMock()`, `ev.clear/set = MagicMock()`
  - wait_for: 즉시 반환 또는 즉시 `TimeoutError` 발생시키는 async 함수로 patch

#### 원인 B: asyncio.create_task 백그라운드 태스크
- **금지**: 테스트에서 `asyncio.create_task()`가 실제 실행되는 것을 허용
- **해결**: `patch("module.asyncio.create_task")`로 mock 교체, `add_done_callback` 속성 포함

#### 원인 C: NotificationWorker / 백그라운드 워커 싱글톤
- **금지**: `_fire_and_forget_telegram` 등이 실제 `NotificationWorker.get_instance()`를 호출하여 백그라운드 태스크 생성
- **해결**: autouse fixture에서 `patch("module._fire_and_forget_telegram")` 처리

#### 원인 D: 실제 DB I/O (aiosqlite)
- **금지**: 테스트에서 `get_db_connection()`이 실제 DB에 연결
- **해결**: autouse fixture에서 `patch("backend.app.db.database.get_db_connection")` 처리

#### 원인 E: pytest-asyncio 이벤트 루프 간섭
- **금지**: conftest.py에 async fixture 사용 (이벤트 루프 정리 중 hang 유발)
- **금지**: conftest.py에서 `asyncio.sleep` 전역 patch (pytest-asyncio 내부 동작 간섭)
- **해결**: conftest.py는 동기 fixture만 사용, 캐시 리셋 등 최소 기능만 유지

### 4. run_command 사용 시
- `Blocking: false` + `WaitMsBeforeAsync: 20000` — hang 감지 시 명령 취소 가능
- 또는 subprocess + `proc.wait(timeout=N)` + `proc.kill()` 패턴 사용

## 개선 필요 영역 — 테스트 커버리지

### 현재 커버리지: 14% (13,833줄 중 1,981줄 커버)

### 고커버리지 영역 (유지)
- `sector_score.py` 100%, `models.py` 100%, `settings_defaults.py` 100%
- `sector_calculator.py` 97%, `sector_filter.py` 96%
- `test_dry_run_fill_event.py` 95%, `test_sector_calculator.py` 100%
- `database.py` 88%, `engine_state.py` 82%, `trade_mode.py` 79%
- `settings_file.py` 70%, `engine_utils.py` 68%

### 테스트 부족 영역 (우선순위별)

#### Priority 1 — 매매 핵심 로직 (완료)
- `test_buy_filter.py` ✅, `test_circuit_breaker.py` ✅, `test_settlement_engine.py` ✅
- `test_risk_manager.py` ✅, `test_buy_order_executor.py` ✅, `test_trading.py` ✅ (hang 해결 — 커밋 `a4fa031`)

#### Priority 2 — 엔진/WS 계층 (완료)
- `test_engine_ws.py` ✅, `test_engine_ws_dispatch.py` ✅, `test_engine_ws_parsing.py` ✅
- `test_engine_ws_reg.py` ✅, `test_engine_account.py` ✅, `test_engine_account_notify.py` ✅
- `test_engine_account_rest.py` ✅, `test_engine_symbol_utils.py` ✅

#### Priority 3 — 파이프라인/스케줄러 (완료)
- `market_close_pipeline.py` (712줄, 86%) ✅
- `pipeline_compute.py` (655줄, 92%) ✅ — 배치 드레인 + 코얼레싱 + 계좌 디바운스 추가 (2026-07-06)
- `pipeline_gateway.py` (86줄, 87%) ✅
- `daily_time_scheduler.py` (601줄, 90%) ✅
- `data_manager.py` (136줄, 96%) ✅

#### Priority 4 — 브로커 커넥터 (0% 커버, 장기)
- `kiwoom_connector.py`, `kiwoom_rest.py`, `kiwoom_order.py`, `kiwoom_providers.py`, `kiwoom_stock_rest.py`
- `ls_connector.py`, `ls_rest.py`, `ls_providers.py`
- `connector_manager.py`

#### Priority 5 — Web 라우트 (0% 커버, 장기)
- `app.py`, `ws.py`, `ws_manager.py`, `settings.py`, `stock_classification.py`, `status.py`

#### Priority 6 — 유틸/기타 (0% 커버, 장기)
- `telegram.py`, `telegram_bot.py`, `trade_history.py` (회귀 테스트 2건 추가), `dry_run.py`
- `journal.py`, `logger.py`, `encryption.py`, `sector_mapping.py`
