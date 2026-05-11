# SectorFlow 워크룰

실시간 주식 자동매매 앱. 핵심 철학: **단순한 로직, 근본 원인 해결, 추측 금지, 단계별 승인.**

---

## 1. 시스템 개요

- Python(FastAPI + asyncio) 백엔드 + TypeScript(Vanilla) 프론트엔드
- 증권사당 단일 WebSocket으로 실시간 데이터 수신
- 폴링 없는 순수 이벤트 기반 아키텍처
- macOS / Windows 크로스 플랫폼 (`pathlib.Path` 필수)
- 테스트모드: 데이터는 실시간 그대로, 주문만 가상

---

## 2. 파일 역할 맵

### 백엔드 (`backend/app/`)

| 파일 | 역할 |
|------|------|
| `services/engine_service.py` | 종목 시세 캐시, 매수후보 캐시, 상태 조회 API |
| `services/engine_sector_confirm.py` | 업종 점수 증분 재계산 + 개별 알림 |
| `services/engine_account_notify.py` | WS 브로드캐스트 (delta 전송) |
| `services/engine_ws_dispatch.py` | WS 메시지 분기 + 0J REAL 감지 |
| `services/daily_time_scheduler.py` | 시간 기반 타이머 + 지수 REST 폴링 제어 |
| `services/trade_history.py` | 체결 이력 영속 저장 + 단건 브로드캐스트 |
| `services/trading.py` | 자동매매 실행 (매수/매도 주문, 가드, 한도 관리) |
| `services/engine_bootstrap.py` | 엔진 기동 시 초기화 |
| `services/engine_strategy_core.py` | 매수/매도 전략 판단 로직 |
| `core/broker_connector.py` | 증권사 추상 클래스 |
| `web/ws_manager.py` | 프론트엔드 WebSocket 연결 관리 |

### 프론트엔드 (`frontend/src/`)

| 파일 | 역할 |
|------|------|
| `stores/appStore.ts` | Zustand 전역 상태 (Record 기반) |
| `binding.ts` | WS 이벤트 → Store 액션 바인딩 |
| `pages/sector-stock.ts` | 업종별 종목 시세 테이블 |
| `pages/buy-target.ts` | 매수후보 테이블 + 상태칩 |
| `pages/profit-overview.ts` | 수익현황 (계좌현황 + 체결이력) |
| `pages/sector-custom.ts` | 업종분류 커스텀 |
| `pages/general-settings.ts` | 일반설정 |
| `components/common/data-table.ts` | 공통 DataTable 컴포넌트 |

---

## 3. 데이터 흐름

```
키움 WS → _recv_loop → _on_ws_message (동기 직접 호출)
  → _handle_real_01 (주식체결):
      ├─ _pending_stock_details[code] 갱신
      ├─ 보유종목이면: check_sell_conditions([해당 1종목])
      ├─ recompute_sector_for_code → flush:
      │   ├─ dirty 섹터만 증분 계산
      │   ├─ notify_desktop_sector_scores() [delta]
      │   ├─ notify_sector_tick_single(code) [개별]
      │   └─ notify_buy_targets_update() [delta]
      └─ 캐시 무효화 없음 (가격만 변경 → 참조 공유)
  → _handle_real_0j (업종지수):
      └─ on_0j_real_received() → 폴링 즉시 중단

프론트엔드:
  sector-stocks-delta → added 병합 / removed 삭제
  buy-targets-delta → added 추가 / removed 필터 / changed 교체
  buy-history-append → [trade, ...prev] prepend
  sell-history-append → [trade, ...prev] prepend + dailySummary 갱신
```

---

## 4. 백엔드 규칙

### 4-1. 캐시 전략

| 캐시 | 무효화 조건 | 무효화 안 하는 경우 |
|------|------------|-------------------|
| `_sector_stocks_cache` | 종목 추가/제거, 순위 변경, 필터 변경 | 가격/등락률만 변경 (참조 공유) |
| `_buy_targets_snapshot_cache` | `_sector_summary_cache` 참조 교체 | 동일 참조 유지 시 |

### 4-2. 브로드캐스트 규칙

| 상황 | 이벤트 | 페이로드 |
|------|--------|---------|
| 필터 변경 (초기) | `sector-stocks-refresh` | `{ stocks: [전체] }` |
| 필터 변경 (이후) | `sector-stocks-delta` | `{ added, removed }` |
| 매수후보 변경 (초기) | `buy-targets-update` | `{ buy_targets: [전체] }` |
| 매수후보 변경 (이후) | `buy-targets-delta` | `{ added, removed, changed }` |
| 매수 체결 | `buy-history-append` | `{ trade: {단건} }` |
| 매도 체결 | `sell-history-append` | `{ trade: {단건}, daily_summary }` |

### 4-3. 인메모리 상태 영속성 규칙

**재기동 시 유실되면 안 되는 상태는 반드시 trade_history(영속 저장)에서 복원해야 한다.**

| 상태 | 복원 소스 | 복원 시점 |
|------|----------|----------|
| `_daily_buy_spent` | `trade_history.get_buy_history(today_only=True)` 합산 | AutoTradeManager 생성 시 |
| `_bought_today` | 위 결과의 stk_cd set | AutoTradeManager 생성 시 |
| `_checked_stocks` | 잔고 REST 조회 결과 | 엔진 부트스트랩 시 |

---

## 5. 프론트엔드 규칙

### 5-1. 상태 관리 (appStore)

| 필드 | 자료구조 | 갱신 방식 |
|------|---------|-----------|
| `sectorStocks` | `Record<string, SectorStock>` | `{ ...prev, [code]: newStock }` |
| `buyTargets` | `BuyTarget[]` | splice 교체/추가/제거 |
| `positions` | `Position[]` | splice 교체/추가/제거 |
| `sellHistory` / `buyHistory` | `Record[]` | `[newTrade, ...prev]` prepend |

### 5-2. DOM 갱신

```typescript
// ✅ CSS display 토글
panel.style.display = active ? '' : 'none'
// ✅ DataTable 증분 갱신
dataTable.updateRows(newRows)
// ❌ 금지 (초기 마운트 제외)
container.innerHTML = ''
```

---

## 6. 절대 금지 패턴

| 영역 | ❌ 금지 | ✅ 대신 |
|------|--------|--------|
| 체결 처리 | `create_task()`로 분리 | 동기 직접 처리 |
| 주기적 작업 | `while + sleep()` 폴링 | 이벤트 발생 시에만 반응 |
| 락 | 실시간 틱 경로에서 Lock | 단일 스레드 → 락 불필요 |
| WS 브로드캐스트 | 전체 리스트 재전송 | 델타만 전송 (초기 연결 제외) |
| 프론트 DOM | `innerHTML = ''` 후 재구축 | CSS display 토글 + 증분 갱신 |
| 프론트 상태 | `new Map()` 전체 복사 | 얕은 복사 + 단일 키 교체 |
| 배열 갱신 | `.map()` 전체 재생성 | splice 기반 증분 |
| 큐 | 체결 데이터 큐에 쌓기 | 받자마자 바로 처리 |
| 예외 처리 | `try-except`로 삼키기 | 오류 노출 (테스트 단계) |

---

## 7. 작업 프로세스 (순차 준수)

### 7-0. 워크룰 재확인 (매 작업 시작 시 필수)

**분석 및 수정 계획 단계 시작 시, 반드시 이 워크룰(특히 핵심 원칙)을 다시 읽고 준수할 것.**

### 7-1. 작업 전 필수 확인

1. 수정할 파일의 전체 구조 파악
2. 해당 함수의 호출처 추적
3. 영향받는 다른 파일 확인
4. 불확실하면 즉시 질문 (추측 금지)

### 7-2. 단계별 승인 (절대 위반 금지)

- **사용자의 명시적 승인 없이는 어떤 코드나 파일도 수정하지 마라.**
- 분석/제안/보고는 자유. 실제 변경은 승인 후에만.
- 각 단계 완료 후 `[N단계 완료] 결과: [요약]` 출력
- 오류 발생 시 즉시 중단 → 원인 분석 → 2가지 이상 해결안 제시 → 사용자 선택

### 7-3. 테스트 후 최종 보고 (필수)

**수정 완료 후, 반드시 테스트(구문 검증/빌드/진단)를 수행하고 그 결과를 포함한 최종 보고서를 작성할 것. 테스트 없이 완료 보고 금지.**

### 7-4. 코딩 원칙

- **단순성**: 요청받지 않은 기능/추상화 추가 금지. 50줄로 가능하면 200줄 금지.
- **정밀성**: 인접 코드/주석/포맷팅 "개선" 금지. 변경된 모든 줄은 사용자 요청에 직접 추적 가능해야 함.
- **출력**: 분석 과정/추측 표현 금지. 완료 보고/문제 발견/승인 요청만 허용. UI 기준으로 설명.

---

## 8. 실시간 데이터 무결성 (절대 위반 금지)

1. **순서 보장**: 같은 종목의 체결/호가는 발생 순서 그대로 처리.
2. **유실 허용치 0**: WS 재연결 시 유실 구간은 REST로 백필.
3. **지연 측정**: 수신→처리→전송 50ms 초과 경고, 200ms 초과 자동매매 중단.
4. **락 금지**: 실시간 틱 경로에서 모든 종류의 Lock 사용 금지.

---

## 9. 시장 시간 & 휴장일

| 시간대 | 시장 | 실시간 | 비고 |
|--------|------|--------|------|
| 08:00-08:50 | NXT 프리 | ✅ | 08:50 이후 신규주문 불가 |
| 09:00-15:30 | KRX 정규 + NXT 메인 | ✅ | |
| 15:40-16:00 | KRX 시간외종가 | ❌ | |
| 16:00-18:00 | KRX 시간외단일가 | ❌ | 10분 단위 |
| 16:00-20:00 | NXT 애프터 | ✅ | NXT 종목만 |

**휴장일:** WS 연결 안 함, 자동매매 OFF, API 조회는 마지막 종가

---

## 10. 에러 발생 시

1. 즉시 중단 + 현재 상태 요약
2. 로그/코드 기반 원인 분석 (추측 금지)
3. 2가지 이상 해결안 제시 (장단점 명시)
4. 사용자 선택 후 승인된 방안만 실행
5. 임시방편(예외 무시, sleep 지연, 테스트 우회) 절대 제안 금지

---

## 11. 컨텍스트 관리

### 새 세션 시작 시 (최우선)
1. `HANDOVER.md` 읽고 이전 작업 상태 복원
2. 없으면 "이전 작업 내역이 없습니다. 새로 시작할까요?" 대기
3. 복원 후 한 줄 요약 보고

### 인계서 자동작성 트리거
- 3개 이상 단계 완료 시 / 대화 20개 초과 시
- 사용자가 "인계서/정리/다음 세션" 언급 시
- 세션 종료 예상 시 / 심각한 에러로 중단 시

저장 위치: `HANDOVER.md` (프로젝트 루트, 항상 덮어쓰기)

---

## 12. 최종 점검 리스트

- [ ] 수정 코드가 사용자 요청 범위 내인가?
- [ ] 불필요한 리팩토링/스타일 변경 없는가?
- [ ] 체결 경로에 `create_task`/큐 없는가?
- [ ] 모든 반응이 이벤트 기반인가? (폴링 없음)
- [ ] WS 브로드캐스트가 델타만 전송하는가?
- [ ] 프론트에서 `innerHTML = ''` 없는가? (초기 마운트 제외)
- [ ] 배열 갱신이 splice 기반인가?
- [ ] 파일 경로가 `pathlib.Path`인가?
- [ ] 실시간 무결성 4규칙 확인했는가?
- [ ] 인메모리 상태가 재기동 후에도 정합성 유지되는가?
- [ ] 테스트(구문/빌드/진단) 수행했는가?
- [ ] 사용자 승인을 받았는가?

---

## 13. 추측 금지 강제 규칙 (AI 자기 제약)

### 13-1. 응답 전 자기 검열 (매번 필수)

응답을 생성하기 전, 다음 3가지를 반드시 확인한다:

1. **파일을 실제로 읽었는가?** → 읽지 않았으면 분석 불가. 먼저 읽어라.
2. **추측 표현이 포함되어 있는가?** → 포함되어 있으면 삭제하거나 "확인 필요"로 대체하라.
3. **승인 없이 수정을 제안하는가?** → 수정은 승인 후에만. 지금은 분석만.

### 13-2. 금지 표현 목록 (이 표현이 나오면 즉시 멈추고 파일을 읽어라)

| ❌ 금지 표현 | ✅ 대체 행동 |
|------------|------------|
| "~일 것입니다" | 해당 파일 읽고 확인 후 사실만 기술 |
| "~로 보입니다" | 해당 파일 읽고 확인 후 사실만 기술 |
| "~인 것 같습니다" | 해당 파일 읽고 확인 후 사실만 기술 |
| "아마도 ~" | 해당 파일 읽고 확인 후 사실만 기술 |
| "~때문일 수 있습니다" | 해당 파일 읽고 확인 후 사실만 기술 |
| "~가능성이 있습니다" | 해당 파일 읽고 확인 후 사실만 기술 |
| "일반적으로 ~" | SectorFlow 코드 기준으로만 판단 |
| "보통 이런 경우에는 ~" | SectorFlow 코드 기준으로만 판단 |

### 13-3. 허용되는 응답 형식

```
[확인한 사실] (파일명 + 줄번호 또는 함수명 명시)
- ...

[확인 필요 — 파일 읽겠습니다]
- ...

[승인 요청]
- 변경 내용: ...
- 영향 범위: ...
```

### 13-4. 허용되지 않는 응답 형식

```
❌ "이 오류는 아마 X 때문일 것입니다."
❌ "코드를 보면 Y로 보입니다." (실제로 읽지 않은 경우)
❌ "일반적으로 이런 패턴은 Z를 의미합니다."
❌ 파일을 읽지 않고 구조나 동작을 설명하는 모든 문장
```

### 13-5. 불확실할 때 유일한 허용 행동

**파일을 읽는다.** 읽을 수 없으면 "어떤 파일을 확인해야 하나요?"라고 질문한다.
추측으로 채우는 것은 어떤 경우에도 허용되지 않는다.
