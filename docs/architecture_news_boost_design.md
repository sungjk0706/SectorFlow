# 설계서: 실시간 뉴스(NWS) 매수 가산점

> **상태**: 설계 완료 (구현 대기)
> **작성일**: 2026-07-23
> **관련 원칙**: P4(증권사명 침투 금지) · P7(블로킹 금지) · P10(SSOT) · P11(폴링 금지) · P13(설정 메모리 상주) · P15(단일 주문 경로) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패)
> **관련 파일**: `backend/app/core/ls_connector.py` · `backend/app/pipelines/pipeline_compute_tick_handlers.py` · `backend/app/domain/buy_filter.py` · `backend/app/services/engine_radar.py` · `backend/app/services/engine_state.py` · `backend/app/core/engine_settings.py` · `backend/app/core/settings_defaults.py` · `backend/app/core/settings_store.py` · `frontend/src/pages/buy-settings.ts` · `frontend/src/pages/general-settings.ts` · `frontend/src/types/index.ts`
> **관련 API 스펙**: `docs/api_specs/LS증권API/websocket/실시간/실시간뉴스제목패킷NWS.txt`

---

## 1. 배경 및 목표

### 1.1 현재 상태

매수 후보 선정은 2단계 구조:
1. **1차 필터**: 장마감 후 5일 평균 거래대금 기준 필터링 (매수후보 테이블에 올라온 종목만 2단계 대상)
2. **2단계 스코어링**: `calculate_boost_score()` 가산점 3개 합산 → 정렬 → 상위 종목 매수

현재 가산점 3개 (`backend/app/domain/buy_filter.py:8-53`):

| 가산점 | 설정 키 | 캐시 소스 |
|---|---|---|
| 5일 전고가 돌파 | `boost_high_breakout_on/score` | `get_high_price_5d_cache()` |
| 호가 잔량 비율 | `boost_order_ratio_on/pct/score` | `get_orderbook_cache()` |
| 프로그램 순매수 | `boost_program_net_buy_on/score` | `get_program_net_buy_cache()` |

**거래대금 가산점은 이미 제거됨** (1차 필터에서 처리, 커밋 7660393).

실시간 데이터 인프라:
- 활성 WebSocket 증권사 = **LS증권** (`broker=ls`)
- 실시간 핸들러 3종: `0B`(체결), `0D`(호가), `0J`(업종지수) + `JIF`(장운영정보, tick_queue 우회 직접 처리)
- LS connector의 `_convert_ls_to_internal()`이 LS 메시지 → 내부 형식 변환 담당
- `subscribe_jif()` / `subscribe_index()` 가 단건 TR 구독 패턴 제공 (NWS와 동일 구조)

### 1.2 목표

1. **NWS 실시간 뉴스 가산점 추가**: 4대 가산점 완성 (5일고가 · 호가비율 · 프.순.매 · 뉴스)
2. **정적 키워드 사전 기반**: 호재 키워드가 뉴스 제목에 포함 시 가산점 부여 (LLM 미사용)
3. **매수후보 테이블 내 종목만**: 1차 필터(거래대금) 통과한 종목에만 가산점 적용
4. **5분 TTL**: 뉴스 감지 후 5분간 가산점 유지, 이후 자동 만료
5. **사용자 UI 조작**: 매수설정에서 가산점 ON/OFF + 점수, 일반설정에서 키워드 사전 편집
6. **P4/P7/P10/P11/P13/P15/P16/P20/P21/P22/P23/P24/P25 완전 부합**

### 1.3 비목표 (본 설계에서 다루지 않음)

- **LLM 실시간 호재/악재 분류**: 비용/지연/복잡도. 정적 키워드 먼저 → 효과 검증 후 별도 설계
- **악재 뉴스 자동 손절**: P15 위반(매도 로직 우회) + 낚시성 뉴스 손실 확정 위험. 제외
- **뉴스 본문 2차 조회 TR**: 제목 기반 1차 판단만. 본문 조회는 효과 입증 후 별도 설계
- **후보 외 종목 임시 추가**: 1차 필터(거래대금) 우회 금지. 매수후보 테이블 내 종목만
- **키움 NWS 지원**: NWS는 LS 전용 TR. 키움-only 환경에서는 뉴스 가산점 0점 (P25 격리)

---

## 2. 설계 방향

### 2.1 핵심 설계 결정

#### 결정 1: NWS 구독 = JIF 단건 구독 패턴 재사용
- NWS는 종목별 구독이 아닌 **뉴스 전체 스트림 1건** (`tr_key="NWS001"`)
- `subscribe_jif()`와 동일 구조: `tr_type="3"`, `tr_cd="NWS"`, `tr_key="NWS001"`
- LS connector에 `subscribe_news()` / `unsubscribe_news()` 메서드 추가
- 연결 시 `subscribe_jif()` 직후에 `subscribe_news()` 호출 (P16 살아있는 경로)
- 재연결 시에도 JIF 재구독과 동일 위치에서 재구독

#### 결정 2: NWS 메시지 처리 = tick_queue 우회 직접 처리 (JIF 패턴)
- 뉴스는 체결/호가와 달리 **이벤트성** — tick_queue 대기 시 지연 발생
- JIF가 이미 tick_queue 우회 직접 핸들러 호출 패턴을 사용 중 (`ls_connector.py:132-135`)
- NWS도 동일 패턴: `_convert_ls_to_internal()`에서 `trnm="NWS"` 내부 메시지 생성 → `_recv_loop()`에서 `trnm=="NWS"` 시 직접 `_on_message()` 호출
- P23 일관성: JIF와 동일한 우회 패턴

#### 결정 3: 키워드 사전 = 메모리 상주 dict (P13)
- 호재 키워드 리스트는 `engine_state`에 메모리 캐시로 상주
- 틱 단계(가산점 계산)에서 DB 조회 금지 (P13)
- 설정 변경 시 캐시 갱신 (설정 로더에서 한 번 로드)
- 기본 키워드: 수주, 최대실적, 특허, 공급계약, 무상증자, 세계최초, MOU, FDA승인, 독점공급, 대규모수주
- 사용자가 일반설정 UI에서 편집 가능 → 설정 저장 시 메모리 캐시 갱신

#### 결정 4: 뉴스 가산점 캐시 = `engine_state`에 `news_boost_cache: dict[str, float]`
- 구조: `{종목코드: 가산점}` — 5분 TTL
- NWS 핸들러가 키워드 매칭 시 해당 종목 코드에 가산점 기록 (시간戳 함께)
- `get_news_boost_cache()` getter가 만료된 항목 필터링 후 반환 (P7 — 매 호출마다 전체 순회 금지, 만료는 lazy 방식)
- `calculate_boost_score()`에 `news_boost_cache` 파라미터 추가 — 기존 3개 캐시와 동일 패턴

#### 결정 5: code 빈 뉴스 = 스킵 + debug 로깅 (P20)
- NWS 패킷의 `code` 필드가 빈값(종합 시황/정치 뉴스) → 폴백으로 덮지 않고 스킵
- `logger.debug()`로 스킵 로깅 (silent pass 금지, P20)
- code 필드에 복수 종목코드가 들어올 수 있음 (최대 240자) → 파싱 필요

#### 결정 6: 매수후보 테이블 내 종목만 가산점 부여
- NWS 핸들러가 code를 파싱한 후, 해당 code가 `master_stocks_cache`(매수후보)에 있는지 O(1) 조회
- 후보에 없는 종목의 뉴스 → 무시 (1차 필터 우회 금지)
- P7: 매 뉴스마다 전체 리스트 순회 금지, dict O(1) 조회

#### 결정 7: UI 분리 — 가산점 토글/점수는 매수설정, 키워드 사전은 일반설정
- **매수설정** (`buy-settings.ts`): `boost_news_on` 토글 + `boost_news_score` 점수 입력 (기존 3개와 동일 위계, 4번째 줄)
- **일반설정** (`general-settings.ts`): 호재 키워드 목록 편집 섹션 (시스템 운영 성격, P23/P24 부합)
- 키워드는 다중 입력 UI (태그 입력 패턴 또는 텍스트에어리어 + 쉼표/줄바꿈 구분)

#### 결정 8: 가산점 기본값 = OFF
- `boost_news_on` 기본값 False — 사용자가 명시적으로 ON 해야 활성화
- 기존 3개 가산점과 동일 (모두 기본 OFF)
- LS WebSocket 연결 없어도 에러 없이 0점 (P25 격리)

#### 결정 9: NWS 핸들러는 PGM(프로그램순매수) 캐시 갱신 패턴 참조
- UPH 틱 → `program_net_buy_cache` 갱신 → `get_program_net_buy_cache()`가 조회
- NWS 핸들러 → `news_boost_cache` 갱신 → `get_news_boost_cache()`가 조회
- 동일한 "핸들러가 캐시 갱신, getter가 조회" 패턴 (P23 일관성)

### 2.2 기각 방안

| 방안 | 기각 사유 |
|---|---|
| LLM 실시간 호재/악재 분류 | 비용/지연(0.5초 보장 불가)/복잡도. 정적 키워드 먼저 (P24 단순성) |
| 악재 뉴스 자동 전량 손절 | P15 위반(매도 로직 우회) + 낚시성 뉴스 손실 확정. 사용자 승인 거부 |
| 뉴스 본문 2차 조회 TR | 본문 조회는 복잡도 증가. 제목 기반 먼저, 효과 입증 후 별도 설계 |
| 후보 외 종목 임시 추가 | 1차 필터(거래대금) 우회. 사용자 결정: 매수후보 내 종목만 |
| NWS를 tick_queue 경유 | 뉴스는 이벤트성, 큐 대기 시 지연. JIF 우회 패턴 재사용 (P23) |
| 키워드 사전 DB 저장 | 매 틱 DB 조회 금지 (P13). 메모리 상주 + 설정 변경 시 갱신 |
| 키워드 UI를 매수설정에 통합 | 매수 "조건"과 "재료 사전" 성격 상이. 일반설정 분리가 P23/P24 부합 |
| 점수 유지 30분/장마감 | 5분 선택 — 뉴스 효과 빠른 감쇠, 단타 중심. 사용자 결정 |
| NWS 구독을 사용자 토글 | 장운영정보(JIF)와 동일하게 자동 구독. 가산점 ON/OFF로 제어 (P23) |

---

## 3. 백엔드 변경 사항

### 3.1 설정 기본값 추가

**파일**: `backend/app/core/settings_defaults.py`

`DEFAULT_USER_SETTINGS`의 기존 boost 블록(라인 42-48) 직후에 추가:

```python
"boost_news_on": False,              # 실시간 뉴스 가산점 ON/OFF
"boost_news_score": 1.0,             # 뉴스 가산점 점수
"news_boost_ttl_sec": 300,           # 뉴스 가산점 유지 시간 (초, 기본 5분)
"news_keywords": "수주,최대실적,특허,공급계약,무상증자,세계최초,MOU,FDA승인,독점공급,대규모수주",  # 호재 키워드 (쉼표 구분)
```

**주의**: `news_keywords`는 쉼표 구분 문자열로 저장 (JSON 리스트 아님) — 기존 설정 저장 구조(`settings_store.py`)가 문자열/숫자/불린 위주이므로 일관성 유지 (P23).

### 3.2 엔진 설정 로더 수정

**파일**: `backend/app/core/engine_settings.py`

`_build_boost_settings()` (라인 235-258)에 신규 키 추가:

```python
def _build_boost_settings(merged: dict) -> dict:
    # ... 기존 3개 가산점 로직 유지 ...
    _v = merged.get("boost_news_score")
    boost_news_score = max(float(_v if _v is not None else 1.0), 0)
    _v = merged.get("news_boost_ttl_sec")
    news_boost_ttl_sec = max(int(_v if _v is not None else 300), 0)
    news_keywords_raw = str(merged.get("news_keywords", "") or "")
    news_keywords = [k.strip() for k in news_keywords_raw.split(",") if k.strip()]
    return {
        # ... 기존 3개 ...
        "boost_news_on": bool(merged.get("boost_news_on")),
        "boost_news_score": boost_news_score,
        "news_boost_ttl_sec": news_boost_ttl_sec,
        "news_keywords": news_keywords,  # 리스트로 변환하여 메모리 상주 (P13)
    }
```

### 3.3 설정 저장 검증 추가

**파일**: `backend/app/core/settings_store.py`

`apply_settings_updates()` 내 기존 검증 로직 직후에 추가:

```python
# 뉴스 가산점 설정 검증 (P20/P22)
if "boost_news_score" in data:
    try:
        _n = float(data["boost_news_score"])
    except (TypeError, ValueError):
        raise ValueError("뉴스 가산점 점수는 숫자여야 합니다")
    if _n < 0 or _n > 100:
        raise ValueError("뉴스 가산점 점수는 0~100 사이여야 합니다")
if "news_boost_ttl_sec" in data:
    try:
        _n = int(data["news_boost_ttl_sec"])
    except (TypeError, ValueError):
        raise ValueError("뉴스 가산점 유지 시간은 정수여야 합니다")
    if _n < 0 or _n > 3600:
        raise ValueError("뉴스 가산점 유지 시간은 0~3600초 사이여야 합니다")
if "news_keywords" in data:
    _kw = str(data["news_keywords"]).strip()
    if len(_kw) > 2000:
        raise ValueError("호재 키워드는 2000자 이하여야 합니다")
```

### 3.4 engine_state에 뉴스 가산점 캐시 추가

**파일**: `backend/app/services/engine_state.py`

`EngineState` 클래스에 신규 캐시 필드 추가:

```python
# 실시간 뉴스 가산점 캐시 — {종목코드: (가산점, 타임스탬프)}
news_boost_cache: dict[str, tuple[float, float]]  # (score, timestamp_sec)
# 호재 키워드 메모리 상주 (P13) — 설정 로더에서 갱신
news_keywords_cache: list[str]
```

**주의**: `news_boost_cache`는 `(score, timestamp)` 튜플로 저장 — TTL 만료 판단용. 기존 캐시들(`master_stocks_cache` 등)과 동일하게 `engine_state.state` 싱글턴에서 관리 (P10 SSOT).

### 3.5 engine_radar에 뉴스 가산점 getter 추가

**파일**: `backend/app/services/engine_radar.py`

기존 `get_program_net_buy_cache()` (라인 33-35) 직후에 추가:

```python
def get_news_boost_cache() -> dict[str, float]:
    """뉴스 가산점 캐시 반환 — 만료된 항목 제외 (5분 TTL).

    P7: 매 호출마다 전체 순회하지만, 캐시 크기는 매수후보 종목 수(수십~수백)로 제한.
    만료 항목은 lazy 제거 (필터링하며 반환).
    """
    import time
    now = time.monotonic()
    ttl = engine_state.state.news_boost_ttl_sec if hasattr(engine_state.state, "news_boost_ttl_sec") else 300
    cache = engine_state.state.news_boost_cache
    # 만료 항목 lazy 제거
    expired = [cd for cd, (_s, ts) in cache.items() if now - ts > ttl]
    for cd in expired:
        del cache[cd]
    return {cd: s for cd, (s, _ts) in cache.items()}
```

### 3.6 LS Connector에 NWS 구독 메서드 추가

**파일**: `backend/app/core/ls_connector.py`

#### 3.6.1 `_TR_KOR` 딕셔너리에 NWS 추가 (라인 24)

```python
_TR_KOR = {"UH1": "호가", "UPH": "프로그램매매", "US3": "체결", "JIF": "장운영정보", "IJ_": "업종지수", "NWS": "실시간뉴스"}
```

#### 3.6.2 `_convert_ls_to_internal()`에 NWS 케이스 추가

`IJ_` 케이스(라인 278-298) 직후, `else` 이전에 추가:

```python
elif tr_cd == "NWS":
    title = str(body.get("title", "")).strip()
    code_raw = str(body.get("code", "")).strip()
    if not title:
        return None
    return {
        "trnm": "NWS",
        "title": title,
        "code": code_raw,  # 복수 종목코드 가능 (최대 240자, 공백/쉼표 구분)
    }
```

#### 3.6.3 `_recv_loop()`에 NWS 직접 처리 분기 추가 (라인 132-140)

```python
if internal_msg.get("trnm") in ("JIF", "NWS"):
    await self._on_message(internal_msg)
else:
    try:
        self._queue_callback(internal_msg)
    except asyncio.QueueFull:
        logger.warning(...)
```

#### 3.6.4 `subscribe_news()` / `unsubscribe_news()` 메서드 추가

`subscribe_index()` (라인 628) 직후에 추가 — JIF 패턴과 동일 구조:

```python
async def subscribe_news(self) -> bool:
    """실시간 뉴스(NWS) 구독 등록 — 단건 스트림 (tr_key=NWS001)."""
    if not self.is_connected() or not self._socket:
        logger.warning("[구독] %s 실시간뉴스 구독 실패 — 연결 없음", _BROKER_DISPLAY)
        return False
    payload = {
        "header": {
            "token": self._token,
            "tr_type": "3"
        },
        "body": {
            "tr_cd": "NWS",
            "tr_key": "NWS001"
        }
    }
    success = await self._socket.send(payload)
    if not success:
        logger.warning("[구독] %s 실시간뉴스 구독 실패", _BROKER_DISPLAY)
    return success

async def unsubscribe_news(self) -> bool:
    """실시간 뉴스(NWS) 구독 해지."""
    if not self.is_connected() or not self._socket:
        return False
    payload = {
        "header": {
            "token": self._token,
            "tr_type": "4"
        },
        "body": {
            "tr_cd": "NWS",
            "tr_key": "NWS001"
        }
    }
    return await self._socket.send(payload)
```

#### 3.6.5 연결 시 NWS 구독 호출 추가

`connect()` 내 `subscribe_jif()` 호출(라인 381-384) 직후에 추가:

```python
# 실시간 뉴스(NWS) 구독
try:
    await self.subscribe_news()
except Exception:
    logger.warning("[구독] %s 실시간뉴스 구독 실패", _BROKER_DISPLAY, exc_info=True)
```

재연결 루프 `_on_socket_disconnect()` 복구 부분(라인 737-741)에도 JIF 재구독 직후 추가:

```python
# 실시간 뉴스(NWS) 재구독
try:
    await self.subscribe_news()
except Exception:
    logger.warning("[구독] %s 재연결 후 실시간뉴스 구독 실패", _BROKER_DISPLAY, exc_info=True)
```

### 3.7 NWS 틱 핸들러 추가

**파일**: `backend/app/pipelines/pipeline_compute_tick_handlers.py`

기존 `_handle_real_0d_tick()` (라인 264-296) 직후에 추가:

```python
async def _handle_nws_news(item: dict) -> None:
    """NWS 실시간 뉴스 처리 — 호재 키워드 매칭 시 news_boost_cache 갱신 (5분 TTL).

    P7: 매 뉴스마다 매수후보 전체 순회 금지 — master_stocks_cache O(1) 조회.
    P13: 키워드 사전은 메모리 상주 (engine_state.news_keywords_cache).
    P20: code 빈 뉴스는 폴백 없이 스킵 + debug 로깅.
    P25: NWS 처리 실패가 다른 틱 처리 블로킹 금지.
    """
    import time
    try:
        title = item.get("title", "")
        code_raw = item.get("code", "")
        if not title:
            return
        if not code_raw:
            logger.debug("[연산] 뉴스 제목 수신 (종목코드 없음, 스킵): %s", title[:60])
            return

        # 복수 종목코드 파싱 (공백/쉼표 구분, 최대 240자)
        from backend.app.services.engine_symbol_utils import _base_stk_cd
        codes = [_base_stk_cd(c.strip()) for c in code_raw.replace(",", " ").split() if c.strip()]
        codes = [c for c in codes if c]
        if not codes:
            logger.debug("[연산] 뉴스 제목 수신 (유효 종목코드 없음, 스킵): %s", title[:60])
            return

        # 호재 키워드 매칭 (메모리 상재 사전, P13)
        keywords = engine_state.state.news_keywords_cache
        if not keywords:
            return  # 키워드 미설정 시 가산점 부여 안 함 (P20 폴백 금지)
        matched = any(kw in title for kw in keywords)
        if not matched:
            return  # 호재 키워드 미포함 시 스킵 (silent 아님 — 자연스러운 경로)

        # 매수후보 테이블 내 종목만 가산점 부여 (1차 필터 우회 금지)
        master_cache = engine_state.state.master_stocks_cache
        score = engine_state.state.news_boost_score if hasattr(engine_state.state, "news_boost_score") else 1.0
        now = time.monotonic()
        hit_codes = []
        for code in codes:
            if code in master_cache:  # O(1) 조회 (P7)
                engine_state.state.news_boost_cache[code] = (score, now)
                hit_codes.append(code)
        if hit_codes:
            logger.info("[연산] 뉴스 가산점 부여 — 종목=%s 키워드 매칭: %s", hit_codes, title[:60])

    except Exception as e:
        logger.error("[연산] 뉴스(NWS) 처리 오류: %s", e, exc_info=True)
```

#### 3.7.1 핸들러 디스패치 추가

NWS 메시지 디스패치 위치 확인 필요 — `_on_ws_message()`(또는 동등 핸들러)에서 `trnm=="NWS"` 분기 추가하여 `_handle_nws_news()` 호출.

### 3.8 buy_filter.py에 뉴스 가산점 로직 추가

**파일**: `backend/app/domain/buy_filter.py`

#### 3.8.1 `calculate_boost_score()`에 news 파라미터 추가 (라인 8-21)

```python
def calculate_boost_score(
    stock,
    *,
    high_5d_cache: dict[str, int],
    orderbook_cache: dict[str, tuple[int, int]],
    program_net_buy_cache: dict[str, int],
    news_boost_cache: dict[str, float],  # 신규
    boost_high_on: bool = False,
    boost_high_score: float = 1.0,
    boost_order_ratio_on: bool = False,
    boost_order_ratio_pct: float = 20.0,
    boost_order_ratio_score: float = 1.0,
    boost_program_net_buy_on: bool = False,
    boost_program_net_buy_score: float = 1.0,
    boost_news_on: bool = False,          # 신규
    boost_news_score: float = 1.0,        # 신규 (캐시에 이미 점수 저장되어 있어 중복값이지만 기존 패턴 일관성)
) -> float:
```

#### 3.8.2 점수 계산 블록 추가 (라인 47-51 직후)

```python
    # 4. 실시간 뉴스
    if boost_news_on:
        news_score = news_boost_cache.get(stock.code, 0.0)
        if news_score > 0:
            score += boost_news_score
```

**주의**: `news_boost_cache`는 이미 `get_news_boost_cache()`에서 만료 항목 필터링됨. 캐시에 있는 종목은 유효한 가산점 보유. `boost_news_score`는 사용자 설정값, 캐시의 점수는 부여 시점의 설정값 — 일관성을 위해 `boost_news_score`(현재 설정)를 사용.

#### 3.8.3 `create_buy_targets()`에 news 파라미터 추가 (라인 97-122)

`create_buy_targets()` 시그니처에 `news_boost_cache` + `boost_news_on` + `boost_news_score` 추가. 내부 `calculate_boost_score()` 호출(라인 200 부근)에 전달.

#### 3.8.4 `build_buy_targets_from_settings()`에 news 전달 추가 (라인 257-288)

```python
from backend.app.services.engine_radar import get_high_price_5d_cache, get_orderbook_cache, get_program_net_buy_cache, get_news_boost_cache

return create_buy_targets(
    # ... 기존 인자 ...
    news_boost_cache=get_news_boost_cache(),
    boost_news_on=bool(settings.get("boost_news_on", False)),
    boost_news_score=float(settings.get("boost_news_score", 1.0)),
    # ...
)
```

### 3.9 engine_state에 키워드/점수 동기화

**파일**: `backend/app/services/engine_state.py` (또는 설정 로드 시점)

설정 로드 시 `news_keywords_cache`와 `news_boost_score`를 `engine_state.state`에 동기화:

```python
# 설정 로드 후 (engine_settings 로드 완료 시점)
engine_state.state.news_keywords_cache = settings.get("news_keywords", [])
engine_state.state.news_boost_score = float(settings.get("boost_news_score", 1.0))
engine_state.state.news_boost_ttl_sec = int(settings.get("news_boost_ttl_sec", 300))
```

**주의**: 설정 변경 시에도 동기화 필요 — 기존 설정 변경 핸들러(실시간 설정 갱신)와 동일 위치에서 갱신.

---

## 4. 프론트엔드 변경 사항

### 4.1 타입 정의 추가

**파일**: `frontend/src/types/index.ts`

`AppSettings` 인터페이스에 신규 키 추가:

```typescript
boost_news_on: boolean
boost_news_score: number
news_boost_ttl_sec: number
news_keywords: string  // 쉼표 구분 문자열
```

### 4.2 매수설정 — 뉴스 가산점 토글/점수 UI

**파일**: `frontend/src/pages/buy-settings.ts`

#### 4.2.1 모듈 상태 참조 추가 (라인 50-52 직후)

```typescript
let boostNewsToggle: ReturnType<typeof createToggleBtn> | null = null
let boostNewsScoreInput: ReturnType<typeof createNumInput> | null = null
let boostNewsControls: HTMLElement | null = null
```

#### 4.2.2 `syncBoost()`에 뉴스 동기화 추가 (라인 80-106)

```typescript
const newsOn = !!r.boost_news_on
boostNewsToggle?.setOn(newsOn)
if (boostNewsScoreInput && (!act || !boostNewsScoreInput.el.contains(act))) {
  boostNewsScoreInput.setValue(Number(r.boost_news_score) ?? 1.0)
}
if (boostNewsControls) {
  setDisabled(boostNewsControls, !newsOn)
}
```

#### 4.2.3 mount 섹션 빌더에 뉴스 가산점 행 추가

`buildBoostSection()`(또는 동등 함수) 내에 기존 3개 가산점 행과 동일 패턴으로 4번째 행 추가:

```typescript
// 실시간 뉴스 가산점 (4번째)
boostNewsScoreInput = createNumInput({
  value: 1.0,
  onChange: v => { vals.boost_news_score = v; saveHelper!.autoSave('boost_news_score', v) },
  step: 0.5,
  name: 'boost_news_score',
})
{
  const r = createToggleLabelControlsRow({
    labelText: '실시간 뉴스 가산점',
    toggleOn: false,
    onToggle: next => { vals.boost_news_on = next; saveHelper!.saveImmediate({ boost_news_on: next }) },
    controlsChild: boostNewsScoreInput.el,
  })
  boostNewsToggle = r.toggle
  boostNewsControls = r.controls
  root.appendChild(r.el)
}
```

**UI 표시**: "실시간 뉴스 가산점" — 기존 3개(5일고가 돌파, 호가 잔량 비율, 프로그램 순매수)와 동일 위계.

### 4.3 일반설정 — 호재 키워드 편집 섹션

**파일**: `frontend/src/pages/general-settings.ts`

#### 4.3.1 섹션 위치

"전역매매설정 (매매 안전장치)" 섹션(라인 683)과 "화면 표시" 섹션(라인 689) 사이에 신규 섹션 추가:

```
sectionTitle('실시간 뉴스 설정')
```

#### 4.3.2 키워드 입력 UI

텍스트에어리어 + 쉼표/줄바꿈 구분 입력 (기존 공통 컴포넌트 재사용, P23):

```typescript
// 호재 키워드 입력 (쉼표 또는 줄바꿈 구분)
const keywordsInput = createTextAreaInput({
  value: '',
  onChange: v => { vals.news_keywords = v; saveHelper!.autoSave('news_keywords', v) },
  placeholder: '수주, 최대실적, 특허, 공급계약, ...',
  name: 'news_keywords',
})
```

**주의**: `createTextAreaInput`이 기존 공통 컴포넌트에 없으면, `components/common/`에서 텍스트 입력 패턴 검색 후 동일 패턴으로 추가 (P23 공통 자산 재사용). 없을 경우 `createNumInput` 패턴 참조하여 신규 생성.

#### 4.3.3 TTL 설정 (옵션)

뉴스 가산점 유지 시간(`news_boost_ttl_sec`)도 동일 섹션에 숫자 입력으로 추가 — 기본 300초(5분).

### 4.4 매수후보 테이블 — 뉴스 가산점 표시 (P21)

**파일**: 매수후보 테이블 렌더링 파일 (추후 조사에서 특정)

매수후보 테이블에 뉴스 가산점이 반영된 종목 표시 — 기존 가산점 표시 패턴(있다면)과 일관성 유지. 사용자가 "이 종목에 왜 뉴스 가산점이 붙었지?" 확인 가능 (P21).

**상세**: 2세션 심층 사전조사에서 매수후보 테이블 컬럼 구조 확인 후 구체화.

---

## 5. 표준 검토 (아키텍처 원칙 부합)

| 원칙 | 부합 | 검토 내용 |
|---|---|---|
| **P4 (증권사명 침투 금지)** | ✅ | NWS 구독/변환/핸들러 로직은 `ls_connector.py`에 격리. 공통 핸들러(`pipeline_compute_tick_handlers.py`)의 `_handle_nws_news()`는 LS 의존성 없이 내부 메시지(`trnm="NWS"`)만 처리. 키움-only 환경에서 NWS 메시지 수신 안 됨 → 자연스럽게 0점 |
| **P7 (블로킹 금지)** | ✅ | NWS 핸들러는 `master_stocks_cache` O(1) 조회. 매 뉴스마다 전체 리스트 순회 금지. `get_news_boost_cache()`는 만료 lazy 제거 (캐시 크기 = 매수후보 수로 제한) |
| **P10 (SSOT)** | ✅ | `news_boost_cache`는 `engine_state.state` 단일 소스. 키워드 사전도 `news_keywords_cache` 단일 소스. 설정은 `integrated_system_settings` 단일 소스 |
| **P11 (폴링 금지)** | ✅ | NWS는 WebSocket 이벤트 기반. `while + sleep` 폴링 없음. TTL 만료는 lazy(`get_news_boost_cache()` 호출 시) — 별도 폴링 태스크 없음 |
| **P13 (설정 메모리 상주)** | ✅ | 키워드 사전, 점수, TTL 모두 `engine_state.state`에 메모리 상주. 틱 단계(가산점 계산)에서 DB 조회 금지 |
| **P15 (단일 주문 경로)** | ✅ | 뉴스 가산점은 매수 점수에만 가산. 매도 로직(`execute_sell()`) 우회 없음. 악재 자동 손절 제외 |
| **P16 (살아있는 경로)** | ✅ | `subscribe_news()`가 `connect()`/재연결 루프에 연결됨. `_handle_nws_news()`가 디스패치에 연결됨. `calculate_boost_score()`에 news 분기 연결됨. dead code 없음 |
| **P20 (폴백 금지)** | ✅ | code 빈 뉴스 → 폴백 없이 스킵 + `logger.debug()`. 키워드 미설정 → 가산점 0 (빈값 폴백 아님). `except: pass` 없음 — 모든 예외 `logger.error(exc_info=True)` |
| **P21 (사용자 투명성)** | ✅ | 매수설정에 가산점 토글/점수 UI. 일반설정에 키워드 편집 UI. 매수후보 테이블에 뉴스 가산점 표시. 뉴스 가산점 부여 시 `logger.info()`로 종목+제목 로깅 |
| **P22 (데이터 정합성)** | ✅ | `news_boost_cache`는 파생 데이터(원본: NWS 패킷 + 키워드 사전). 중복 저장 없음. TTL 만료 시 자동 제거로 정합성 유지 |
| **P23 (일관성)** | ✅ | NWS 구독 = JIF 패턴. NWS 핸들러 = PGM 캐시 갱신 패턴. 가산점 UI = 기존 3개와 동일 패턴. 용어: "뉴스" (뉴스 가산점, 호재 키워드). `_TR_KOR` 딕셔너리 확장 |
| **P24 (단순성)** | ✅ | 기존 3개 가산점 패턴 그대로 4번째 추가 — 신규 추상화 없음. 키워드 사전 = 단순 리스트. TTL = lazy 만료 (별도 타이머 태스크 없음). LLM 미사용 |
| **P25 (격리된 실패)** | ✅ | NWS 구독 실패 → `logger.warning()` 후 계속 (JIF와 동일). NWS 핸들러 예외 → `logger.error()` 후 다른 틱 처리 유지. LS WebSocket 끊김 → 키움 체결/호가 정상 작동. 키움-only 환경 → 뉴스 가산점 0점 (에러 아님) |

---

## 6. 사용자 결정 항목 (이미 확정)

| 항목 | 결정 | 비고 |
|---|---|---|
| 점수 유지 시간 | **5분 (300초)** | 사용자 선택. `news_boost_ttl_sec` 기본값 |
| 키워드 편집 위치 | **일반설정 페이지 분리** | 사용자 제안 + 기술 검토 합의. 매수설정은 가산점 토글/점수만 |
| 후보 외 종목 처리 | **매수후보 테이블 내 종목만** | 1차 필터(거래대금) 통과한 종목만. 사용자 결정 |
| LLM 분류 | **제외** | 정적 키워드 사전만. 효과 검증 후 별도 설계 |
| 악재 자동 손절 | **제외** | P15 위반 + 낚시성 뉴스 위험 |

---

## 7. 다음 세션 (2세션) 진행 항목

2세션에서 수행할 심층 사전조사 + 태스크 파일 작성 항목:

1. **의존성 조사**: `_on_ws_message()` 디스패치 구조 정확한 위치, `engine_state` 설정 동기화 시점, 매수후보 테이블 컬럼 구조
2. **영향 범위**: 백엔드 9파일 + 프론트엔드 3파일 + 테스트 1파일 (`test_buy_filter.py`)
3. **기존 공통 자산 확인**: `createTextAreaInput` 존재 여부, 매수후보 테이블 가산점 표시 기존 패턴, `engine_state` 설정 동기화 기존 패턴
4. **단계 분할**: 백엔드 NWS 인프라(구독/변환/핸들러) → 가산점 로직 → 설정 → 프론트엔드 매수설정 → 프론트엔드 일반설정 → 테스트
5. **태스크 파일**: `docs/plan_news_boost.md` 작성

---

## 8. 테스트 계획 (개요)

- `test_buy_filter.py`: `calculate_boost_score()` news 케이스 추가 (가산점 부여/미부여/빈 캐시/TTL 만료)
- NWS 핸들러 단위 테스트: 키워드 매칭, code 빈값 스킵, 복수 code 파싱, 매수후보 외 종목 무시
- LS connector: `subscribe_news()` / `_convert_ls_to_internal()` NWS 케이스 (모의 메시지)
- 런타임 검증: LS 모의투자 WebSocket 연결 후 NWS 구독 ACK + 모의 뉴스 수신 → 가산점 부여 로그 확인
