# -*- coding: utf-8 -*-
"""
텔레그램 양방향 Bot Command 리스너 (로컬 설정 파일 + 메모리 상태 기반)

지원 명령어 (한글 / 영문 alias):
  자동 / auto       -- 자동매매 마스터 ON/OFF 토글 (time_scheduler_on)
  매수              -- 매수 체결 내역 (최근 10건)
  매도              -- 매도 체결 내역 (최근 10건)
  상태 / status     -- 엔진·스케줄·스위치 + 리스크 상태 (계좌 제외)
  현황              -- 상태 와 동일 (호환)
  잔고 / balance    -- 계좌 현황 (예수금/주문가능/평가/실현손익)
  계좌 / account    -- 잔고 와 동일 (호환)
  당일              -- 당일 실현 손익 (손익금 + 수익률)
  5일               -- 최근 5거래일 실현 손익
  당월              -- 당월 실현 손익
  누적              -- 누적 실현 손익
  업종 / sector     -- 업종 상위 5 (가산점 + 종목 5개)
  후보 / candidate  -- 매수 후보 (가드 통과) 10위 + 대비/등락률/가산점
  설정 / settings   -- 주요 설정값 조회 (변경 불가, 조회 전용)
  도움말 / help     -- 명령어 목록 (/start 도 동일)
"""
import asyncio
import logging
import re
import time
from datetime import datetime

import httpx

from backend.app.core.constants import _KST
from backend.app.services.auto_trading_effective import auto_trading_effective
from backend.app.services.engine_utils import TaskGuardMixin
from backend.app.services.telegram_fmt import (
    fmt_won,
    fmt_rate,
    fmt_score,
    fmt_signed_won,
    fmt_change,
)

logger = logging.getLogger(__name__)

# Long polling: Telegram은 최대 50초까지 대기 가능. 개인 PC·로컬 환경에 맞춰 30초로 호출 빈도 감소.
_GETUPDATES_LONG_POLL = 30
# getUpdates 대기(30초) + 여유. read가 짧으면 연결이 끊겨 빈 폴링이 늘어남.
_HTTPX_POLL = httpx.Timeout(connect=15.0, read=45.0, write=15.0, pool=15.0)


def _mask_telegram_url(s: str) -> str:
    """로그/예외 문자열에 섞인 Bot API URL에서 토큰 경로를 가립니다."""
    if not s:
        return s
    return re.sub(
        r"(https://api\.telegram\.org/bot)([^/]+)(/)",
        r"\1***\3",
        s,
        flags=re.IGNORECASE,
    )


def _normalize_chat_id(raw: str) -> str:
    """Telegram chat id 는 숫자 문자열로 통일 (앞뒤 공백·형식 차이 허용)."""
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        return str(int(s))
    except (ValueError, TypeError):
        return s


def _build_risk_status_lines() -> str:
    """리스크 차단 상태 요약 라인 생성 (저장된 SSOT만 표시 — P10/P21/P24).

    표시 대상 (이미 engine_state에 저장된 상태):
      - OMS 서킷브레이커: RiskManager.circuit_breaker.get_state() (CLOSED/OPEN/HALF_OPEN)
      - KRX 서킷브레이커: engine_state.krx_circuit_breaker_active + market_phase["krx_alert"]
        (사이드카는 krx_circuit_breaker_active 미설정 — 개인 매매 가능하므로 자동매매 중단 아님)

    일일 손실 한도 등 리스크 매니저 조건은 주문 시도 시에만 계산되어
    상태로 저장되지 않으므로 여기서 표시하지 않음 (추후 보강 시 본 함수에 추가).

    반환: 상태 명령어 본문에 삽입할 라인 문자열 (빈 줄 1개 + 리스크 라인들).
    예외 격리 (P25) — 조회 실패 시 정상 표시.
    """
    try:
        from backend.app.services.engine_state import state
        from backend.app.services.risk_manager import get_risk_manager

        # OMS 서킷브레이커 상태
        cb_state = get_risk_manager().circuit_breaker.get_state()
        # KRX 서킷브레이커 상태 (사이드카는 자동매매 중단 아님 — krx_circuit_breaker_active 미설정)
        krx_active = bool(state.krx_circuit_breaker_active)
        krx_alert = (state.market_phase.get("krx_alert") or "").strip()

        # 차단 우선순위: OMS 서킷브레이커 > KRX 서킷브레이커 (P23 — header.ts 칩 순서와 동일)
        if cb_state == "OPEN":
            return (
                "\n\n🛡️ <b>리스크 상태</b>\n"
                "🚫 매매 차단 중: OMS 서킷브레이커 차단 (자동매매 마스터 강제 OFF)"
            )
        if cb_state == "HALF_OPEN":
            return (
                "\n\n🛡️ <b>리스크 상태</b>\n"
                "⚠️ 매매 제한 중: OMS 서킷브레이커 복구 시도 (단일 테스트 주문만 허용)"
            )
        if krx_active:
            alert_txt = f" — {krx_alert}" if krx_alert else ""
            return (
                "\n\n🛡️ <b>리스크 상태</b>\n"
                f"🚫 매매 차단 중: KRX 서킷브레이커 발동{alert_txt}"
            )
        # 정상
        return (
            "\n\n🛡️ <b>리스크 상태</b>\n"
            "✅ 정상 (차단 없음)"
        )
    except Exception:
        logger.warning("[알림] 리스크 상태 조회 실패 — 상태 명령어에서 리스크 라인 생략", exc_info=True)
        return ""


async def _build_account_brief_lines(snap: dict, is_virtual: bool) -> str:
    """계좌 요약 라인 생성 — 모드별 라벨/데이터 소스 분리 (P10 SSOT, P21 투명성, P23 일관성).

    프론트엔드 수익현황 페이지(profit-shared.ts renderAccountVals)와 동일 기준:
      - 가상매매: 행 0 = "누적 투자금" (initial_deposit, settlement_engine SSOT)
      - 실전매매:   행 0 = "예수금"     (deposit, 증권사 REST kt00001 SSOT)
    주문가능 금액(orderable)은 양 모드 공통 표시 (프론트엔드와 동일).
    라벨은 프론트엔드 account-labels.ts와 동일 — "총평가/총손익" 모호성 제거 (P23).
    누적 실현 손익금/수익률 추가 — 프론트엔드 aggregatePnl/computeCumulativePnl과 동일 공식 (P21).
    수익률 분모 = 매수원금 합계(realized_buy_total) — 양 모드 공통 (프론트엔드와 동일 — P10 SSOT).
    """
    from backend.app.services.trade_history import get_realized_pnl_summary

    if is_virtual:
        row0_label = "누적 투자금"
        row0_val = int(snap.get("initial_deposit", 0) or 0)
    else:
        row0_label = "예수금"
        row0_val = int(snap.get("deposit", 0) or 0)
    orderable  = int(snap.get("orderable", 0) or 0)
    total_eval = int(snap.get("total_eval", 0) or 0)
    total_pnl  = int(snap.get("total_pnl", 0) or 0)
    total_rate = float(snap.get("total_rate", 0.0) or 0.0)
    pos_cnt    = int(snap.get("position_count", 0) or 0)
    snap_at    = (snap.get("snapshot_at") or "")[:19].replace("T", " ")

    # 누적 실현 손익 — trade_history SSOT에서 집계 (프론트엔드 aggregatePnl과 동일)
    trade_mode = "virtual" if is_virtual else "live"
    realized_pnl, realized_buy_total = await get_realized_pnl_summary(trade_mode=trade_mode)
    # 수익률 분모: 매수원금 합계 (프론트엔드 computeCumulativePnl/aggregatePnl과 동일 — P10 SSOT)
    cum_denominator = realized_buy_total
    cum_rate = realized_pnl / cum_denominator * 100 if cum_denominator > 0 else 0.0

    return (
        f"💰 {row0_label}: {fmt_won(row0_val)}\n"
        f"💳 주문가능: {fmt_won(orderable)}\n"
        f"📈 보유 종목 평가 금액: {fmt_won(total_eval)}\n"
        f"📉 보유 종목 평가 손익금: {fmt_signed_won(total_pnl)}\n"
        f"📊 보유 종목 평가 수익률: {fmt_rate(total_rate)}\n"
        f"💵 누적 총 실현 손익금: {fmt_signed_won(realized_pnl)}\n"
        f"📈 누적 총 실현 수익률: {fmt_rate(cum_rate)}\n"
        f"🏷️ 보유종목: {pos_cnt}개\n"
        f"🕐 기준시각: {snap_at}"
    )


async def _compute_period_pnl(label: str, *, today_only: bool = False, date_from: str = "", date_to: str = "", is_virtual: bool) -> str:
    """기간별 실현 손익 라인 1줄 생성 (P10 SSOT — trade_history.get_realized_pnl_summary, 프론트엔드 aggregatePnl과 동일 공식).

    수익률 분모 = 매수원금 합계(buy_total) — 프론트엔드 computeCumulativePnl과 동일.
    실전매매: 증권사 서버가 수익률 SSOT이므로 앱에서 재계산 금지 → 수익률 미표시 (AGENTS.md 실전vs테스트 테이블).
    """
    from backend.app.services.trade_history import get_realized_pnl_summary

    trade_mode = "virtual" if is_virtual else "live"
    pnl, buy_total = await get_realized_pnl_summary(
        today_only=today_only, date_from=date_from, date_to=date_to, trade_mode=trade_mode,
    )
    pnl_txt = fmt_signed_won(pnl)
    if is_virtual:
        rate = pnl / buy_total * 100 if buy_total > 0 else 0.0
        rate_txt = f"  ({fmt_rate(rate)})"
    else:
        # 실전매매: 증권사 서버가 수익률 SSOT — 앱에서 재계산 금지
        rate_txt = "  (수익률: 증권사 확인)"
    return f"  {label}: {pnl_txt}{rate_txt}"



def _build_settings_lines(flat: dict) -> str:
    """주요 설정값 요약 라인 생성 (조회 전용 — P21 사용자 투명성, P10 SSOT).

    인자: load_integrated_system_settings() 결과 flat dict.
    반환: 설정 명령어 본문에 삽입할 라인 문자열.
    주의: 본 함수는 조회만 수행 — 설정 변경은 절대 금지 (P15 단일 주문 경로, P16 살아있는 경로).
    """
    def on_off(key: str) -> str:
        return "ON" if bool(flat.get(key)) else "OFF"

    # 자동매매
    mode = flat.get("trade_mode") or "virtual"
    mode_txt = "테스트" if mode == "virtual" else "실전"
    auto_lines = [
        f"🔰 마스터: {on_off('time_scheduler_on')}",
        f" 매수: {on_off('auto_buy_on')} ({flat.get('buy_time_start', '?')}~{flat.get('buy_time_end', '?')})",
        f"🏪 매도: {on_off('auto_sell_on')} ({flat.get('sell_time_start', '?')}~{flat.get('sell_time_end', '?')})",
        f"🎯 투자모드: {mode_txt}",
    ]

    # 매수 조건 (매수 차단 — 개별 종목 단위, P23 책임 분리)
    buy_lines = []
    if flat.get("max_stock_cnt_on"):
        buy_lines.append(f"최대 종목: {flat.get('max_stock_cnt', 0)}개")
    if flat.get("buy_amt_on"):
        buy_lines.append(f"종목당 금액: {fmt_won(flat.get('buy_amt'))}")
    if flat.get("max_daily_total_buy_on"):
        buy_lines.append(f"일일 총매수 한도: {fmt_won(flat.get('max_daily_total_buy_amt'))}")
    if flat.get("rebuy_block_on"):
        buy_lines.append(f"재매수 차단: {flat.get('rebuy_block_period', '?')}")
    if flat.get("buy_block_rise_on"):
        buy_lines.append(f"상승 차단: {fmt_rate(flat.get('buy_block_rise_pct'))}")
    if flat.get("buy_block_fall_on"):
        buy_lines.append(f"하락 차단: {fmt_rate(flat.get('buy_block_fall_pct'))}")
    buy_block = " · ".join(buy_lines) if buy_lines else "제한 없음"

    # 매도 조건
    sell_lines = []
    if flat.get("tp_apply"):
        sell_lines.append(f"익절: {fmt_rate(flat.get('tp_val'))}")
    if flat.get("loss_apply"):
        sell_lines.append(f"손절: {fmt_rate(flat.get('loss_val'))}")
    if flat.get("ts_apply"):
        sell_lines.append(
            f"트레일링: 시작 {fmt_rate(flat.get('ts_start_val'))} / 하락 {fmt_rate(flat.get('ts_drop_val'))}"
        )
    sell_block = " · ".join(sell_lines) if sell_lines else "조건 없음"

    # 리스크 관리
    risk_lines = []
    if flat.get("risk_manager_on"):
        risk_lines.append(f"리스크 매니저: {on_off('risk_manager_on')}")
        if flat.get("daily_loss_limit_on"):
            risk_lines.append(f"일일 손실 한도: {fmt_won(flat.get('daily_loss_limit'))}")
        if flat.get("daily_loss_rate_limit_on"):
            risk_lines.append(f"일일 손실률: {fmt_rate(flat.get('daily_loss_rate_limit'))}")
        if flat.get("consecutive_loss_limit_on"):
            risk_lines.append(f"연속 손실: {flat.get('consecutive_loss_limit', 0)}회")
    risk_lines.append(f"종목 최대 노출: {fmt_won(flat.get('max_single_stock_exposure'))}")
    risk_block = " · ".join(risk_lines)

    # 업종 필터 (업종 단위 — 개별 종목 단위 매수 차단은 매수 조건 섹션, P23 책임 분리)
    sector_lines = [
        f"최소 상승 비율: {fmt_rate(flat.get('sector_min_rise_ratio_pct'))}",
        f"최소 거래대금: {fmt_won(flat.get('sector_min_trade_amt'))}",
        f"최대 업종 수: {flat.get('sector_max_targets', 0)}개",
        f"수신률 임계값: {fmt_rate(flat.get('sector_start_threshold_pct'))}",
    ]
    sector_block = " · ".join(sector_lines)

    return (
        "⚙️ <b>자동매매</b>\n"
        + "\n".join(auto_lines) + "\n\n"
        f"💰 <b>매수 조건</b>\n{buy_block}\n\n"
        f"📉 <b>매도 조건</b>\n{sell_block}\n\n"
        f"🛡️ <b>리스크 관리</b>\n{risk_block}\n\n"
        f"📊 <b>업종 필터</b>\n{sector_block}"
    )


class TelegramBot(TaskGuardMixin):
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self._offsets: dict[str, int] = {}
        self._last_poll_err_mon: float | None = None
        self._last_poll_err_msg: str = ""

    @property
    def is_running(self) -> bool:
        """폴링 태스크가 살아있는지 여부 (활성 설정 없음으로 자동 종료 후 False)."""
        return self._task is not None and not self._task.done()

    def start(self):
        self._start_guarded(self._poll_loop, "[알림] 폴링 시작")

    async def stop_async(self) -> None:
        """폴링 작업이 httpx 대기 중이어도 취소·종료를 기다린다(데스크톱 종료 시 잔류 방지)."""
        self._running = False
        t = self._task
        if t and not t.done():
            t.cancel()
            try:
                await asyncio.wait_for(t, timeout=12.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._task = None
        logger.info("[알림] 폴링 종료")

    # ── 내부 폴링 반복 ────────────────────────────────────────────────────────

    async def _poll_loop(self):
        while self._running:
            tasks: list = []
            had_error = False
            try:
                rows = self._fetch_enabled_settings()
                tasks = [
                    self._poll_one(row)
                    for row in rows
                    if row.get("telegram_bot_token") and row.get("telegram_chat_id")
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                had_error = True
                logger.error("[알림] 반복 오류: %s", _mask_telegram_url(str(exc)))
            if not tasks:
                self._running = False
                logger.info("[알림] 활성 설정 없음 — 폴링 자동 종료")
                break
            if had_error:
                await asyncio.sleep(2)

    def _fetch_enabled_settings(self) -> list[dict]:
        """state.integrated_system_settings_cache에서 직접 조회 (원칙 13: 메모리 상주).

        B21-01 세션 4: decrypt_secret() 결과 기반으로 전환 (P20 폴백 제거).
        - gAAAA 접두 + ENCRYPTED → 평문 토큰 사용
        - gAAAA 접두 + KEY_UNAVAILABLE/DECRYPT_FAILED → 스킵 + 상태별 경고 로그 (폴링 차단)
        - gAAAA 접두 아님 → 평문 토큰 그대로 사용 (PLAINTEXT_LEGACY 호환)
        """
        from backend.app.services.engine_state import state
        from backend.app.core.encryption import decrypt_secret, SecretValueState

        flat = state.integrated_system_settings_cache
        if not flat.get("tele_on"):
            return []
        chat_raw = str(flat.get("telegram_chat_id") or "").strip()
        if not chat_raw:
            return []

        rows: list[dict] = []
        seen_tokens: set[str] = set()
        for token_field in ("telegram_bot_token_test", "telegram_bot_token_real"):
            raw_token = flat.get(token_field) or ""
            s = str(raw_token)
            if s.startswith("gAAAA"):
                result = decrypt_secret(s)
                if result.state is SecretValueState.ENCRYPTED and result.plaintext is not None:
                    token = result.plaintext.strip()
                else:
                    # 복호화 불가 — 스킵 + 상태별 경고 로그 (P21, 폴링 차단).
                    if result.state is SecretValueState.KEY_UNAVAILABLE:
                        logger.warning("[알림] 토큰 복호화 불가 — 암호화 키 없음/오류. 필드: %s", token_field)
                    elif result.state is SecretValueState.DECRYPT_FAILED:
                        logger.warning("[알림] 토큰 복호화 실패 — 암호문 손상 또는 다른 키. 필드: %s", token_field)
                    continue
            else:
                token = s.strip()
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            rows.append({
                "telegram_bot_token": token,
                "telegram_chat_id":   _normalize_chat_id(chat_raw),
                "_profile":           "root",
            })
        return rows

    async def _poll_one(self, row: dict):
        token         = (row.get("telegram_bot_token") or "").strip()
        allowed_chat  = _normalize_chat_id(str(row.get("telegram_chat_id") or ""))
        profile       = row.get("_profile")
        offset        = self._offsets.get(token, 0)

        url    = f"https://api.telegram.org/bot{token}/getUpdates"
        params = {"offset": offset, "timeout": _GETUPDATES_LONG_POLL, "limit": 20}

        try:
            async with httpx.AsyncClient(timeout=_HTTPX_POLL) as client:
                resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return
            data = resp.json()
        except Exception as exc:
            masked = _mask_telegram_url(str(exc))
            # Python 종료 시점의 atexit 등록 예외는 복구 불가 상태에 가까워 루프를 중단한다.
            if isinstance(exc, RuntimeError) and "atexit" in str(exc).lower():
                logger.warning("[알림] 런타임 종료 감지로 폴링 중단: %s", masked)
                self._running = False
                return
            now = time.monotonic()
            if (
                self._last_poll_err_msg != masked
                or self._last_poll_err_mon is None
                or (now - self._last_poll_err_mon) >= 10.0
            ):
                logger.debug("[알림] 갱신 조회 실패: %s", masked)
                self._last_poll_err_msg = masked
                self._last_poll_err_mon = now
            return

        if not data.get("ok"):
            return

        for update in data.get("result", []):
            uid = update.get("update_id", 0)
            if uid >= self._offsets.get(token, 0):
                self._offsets[token] = uid + 1

            msg = update.get("message") or update.get("channel_post") or {}
            if not msg:
                continue

            raw_chat = (msg.get("chat") or {}).get("id")
            sender_id = _normalize_chat_id(str(raw_chat) if raw_chat is not None else "")
            if sender_id != allowed_chat:
                logger.warning("[알림] 허용되지 않은 채팅 ID %s (허용: %s)", sender_id, allowed_chat)
                continue

            text = (msg.get("text") or "").strip()
            if text:
                await self._handle_command(token, allowed_chat, text, profile)

    # ── 메시지 전송 ──────────────────────────────────────────────────────────

    async def _send(self, token: str, chat_id: str, text: str):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                )
        except Exception as exc:
            logger.debug(f"[알림] 메시지 전송 오류: {exc}")

    # ── 명령어 라우터 ─────────────────────────────────────────────────────────

    async def _handle_command(self, token: str, chat_id: str, text: str, profile: str | None = None):
        raw = (text.split()[0] if text else "").strip()
        cmd = raw.lstrip("/").lower()
        # 한글 명령은 lower()가 동일 -- 영문 alias 만 소문자 처리됨
        if not cmd:
            return
        if cmd in ("자동", "auto"):
            await self._cmd_toggle_auto_master(token, chat_id, profile)
        elif cmd == "매수":
            await self._cmd_buy_history(token, chat_id)
        elif cmd == "매도":
            await self._cmd_sell_history(token, chat_id)
        elif cmd in ("상태", "status"):
            await self._cmd_status_full(token, chat_id, profile)
        elif cmd in ("현황",):
            await self._cmd_status_full(token, chat_id, profile)
        elif cmd in ("잔고", "balance"):
            await self._cmd_account(token, chat_id)
        elif cmd in ("계좌", "account"):
            await self._cmd_account(token, chat_id)
        elif cmd == "당일":
            await self._cmd_period_pnl(token, chat_id, "당일")
        elif cmd == "5일":
            await self._cmd_period_pnl(token, chat_id, "5일")
        elif cmd == "당월":
            await self._cmd_period_pnl(token, chat_id, "당월")
        elif cmd == "누적":
            await self._cmd_period_pnl(token, chat_id, "누적")
        elif cmd in ("업종", "sector"):
            await self._cmd_sector(token, chat_id)
        elif cmd in ("후보", "candidate"):
            await self._cmd_buy_candidates(token, chat_id)
        elif cmd in ("설정", "settings"):
            await self._cmd_settings(token, chat_id)
        elif cmd in ("도움말", "help"):
            await self._cmd_help(token, chat_id)
        elif cmd == "start":
            # 텔레그램 기본 /start -> 도움말 (구 /시작·스케줄 ON 과 무관)
            await self._cmd_help(token, chat_id)
        else:
            await self._send(token, chat_id, "❓ 알 수 없는 명령어입니다.\n도움말 로 사용 가능한 명령어를 확인하세요.")

    # ── 명령어 핸들러 ─────────────────────────────────────────────────────────

    async def _cmd_help(self, token: str, chat_id: str):
        text = (
            "📋 <b>SectorFlow Bot 명령어</b>\n\n"
            "자동  -- 자동매매 마스터 ON/OFF (토글)\n"
            "매수  -- 매수 체결 내역 (최근 10건)\n"
            "매도  -- 매도 체결 내역 (최근 10건)\n"
            "상태  -- 엔진·스케줄·스위치 + 리스크 상태 (현황)\n"
            "잔고  -- 계좌 현황 (계좌)\n"
            "당일  -- 당일 실현 손익\n"
            "5일   -- 최근 5거래일 실현 손익\n"
            "당월  -- 당월 실현 손익\n"
            "누적  -- 누적 실현 손익\n"
            "업종  -- 업종 상위 5 (가산점 + 종목 5개)\n"
            "후보  -- 매수 후보 (가드 통과) 10위 + 대비/등락률/가산점\n"
            "설정  -- 주요 설정값 조회 (변경 불가, 조회 전용)\n"
            "도움말 -- 이 메시지"
        )
        await self._send(token, chat_id, text)

    async def _toggle_setting_bool(
        self,
        key: str,
        label: str,
    ) -> bool:
        """현재값 반전 후 저장. 새 값 반환."""
        from backend.app.core.settings_store import apply_settings_updates
        from backend.app.services.engine_config import refresh_engine_integrated_system_settings_cache
        from backend.app.services.engine_state import state

        flat = state.integrated_system_settings_cache
        cur = bool(flat[key])
        new = not cur
        await apply_settings_updates({key: new})
        await refresh_engine_integrated_system_settings_cache(None, use_root=True)
        from backend.app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        await notify_desktop_header_refresh()
        await notify_desktop_settings_toggled()
        logger.info("[알림] 설정 %s — %s (%s)", key, new, label)
        return new

    async def _cmd_toggle_auto_master(self, token: str, chat_id: str, profile: str | None = None):
        try:
            new = await self._toggle_setting_bool("time_scheduler_on", "자동매매 마스터")
            if new:
                await self._send(
                    token,
                    chat_id,
                    " <b>자동매매 마스터</b> <b>ON</b>\n동작 시간·매수/매도 스위치 조건이 맞으면 자동매매가 허용됩니다.",
                )
            else:
                await self._send(
                    token,
                    chat_id,
                    "⏹️ <b>자동매매 마스터</b> <b>OFF</b>\n자동매매가 중단됩니다.",
                )
        except Exception as exc:
            await self._send(token, chat_id, f" 오류 발생: {str(exc)[:120]}")

    async def _cmd_buy_history(self, token: str, chat_id: str) -> None:
        """매수 체결 내역 최근 10건 전송 (trade_history SSOT — P10)."""
        try:
            from backend.app.services.trade_history import get_buy_history

            records = await get_buy_history()
            now_str = datetime.now(_KST).strftime("%H:%M")

            if not records:
                await self._send(token, chat_id, f"📥 <b>매수 체결 내역</b> ({now_str})\n내역 없음")
                return

            lines = [f"📥 <b>매수 체결 내역</b> (최근 {min(len(records), 10)}건, {now_str})\n"]
            for rec in records[:10]:
                dt = f"{rec.get('date', '')} {rec.get('time', '')}".strip()
                name = rec.get("stk_nm", "?")
                price = int(rec.get("price", 0) or 0)
                qty = int(rec.get("qty", 0) or 0)
                total = int(rec.get("total_amt", 0) or 0)
                sector = rec.get("sector", "")
                sec_txt = f"  [{sector}]" if sector else ""
                rank = rec.get("buy_rank")
                rank_txt = f"  #{rank}" if rank else ""
                lines.append(
                    f"  {dt}  {name}  {fmt_won(price)} × {qty}주 = {fmt_won(total)}{sec_txt}{rank_txt}"
                )

            await self._send(token, chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(token, chat_id, f"⚠ 매수 내역 조회 오류: {str(exc)[:120]}")

    async def _cmd_sell_history(self, token: str, chat_id: str) -> None:
        """매도 체결 내역 최근 10건 전송 (trade_history SSOT — P10).

        매도 내역에는 실현 손익(pnl)과 손익률(pnl_rate)을 포함 —
        프론트엔드 수익현황 페이지 aggregatePnl과 동일 데이터 (P21 투명성).
        """
        try:
            from backend.app.services.trade_history import get_sell_history

            records = await get_sell_history()
            now_str = datetime.now(_KST).strftime("%H:%M")

            if not records:
                await self._send(token, chat_id, f"📤 <b>매도 체결 내역</b> ({now_str})\n내역 없음")
                return

            lines = [f"📤 <b>매도 체결 내역</b> (최근 {min(len(records), 10)}건, {now_str})"]
            for i, rec in enumerate(records[:10], 1):
                dt = f"{rec.get('date', '')} {rec.get('time', '')}".strip()
                name = rec.get("stk_nm", "?")
                price = int(rec.get("price", 0) or 0)
                qty = int(rec.get("qty", 0) or 0)
                total = int(rec.get("total_amt", 0) or 0)
                pnl = int(rec.get("realized_pnl", 0) or 0)
                pnl_rate = float(rec.get("pnl_rate", 0.0) or 0.0)
                reason = rec.get("reason", "")
                reason_txt = f" ({reason})" if reason else ""
                lines.append(
                    f"\n{i}. {dt}  {name}\n"
                    f"   {fmt_won(price)} × {qty}주 = {fmt_won(total)}\n"
                    f"   {fmt_signed_won(pnl)} ({fmt_rate(pnl_rate)}){reason_txt}"
                )

            await self._send(token, chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(token, chat_id, f"⚠ 매도 내역 조회 오류: {str(exc)[:120]}")

    async def _cmd_period_pnl(self, token: str, chat_id: str, period: str) -> None:
        """기간별 실현 손익 전송 (당일/5일/당월/누적).

        period: "당일" | "5일" | "당월" | "누적"
        trade_history SSOT에서 집계 (P10), 프론트엔드 aggregatePnl과 동일 공식 (P23).
        실전매매: 수익률은 증권사 서버 SSOT이므로 앱에서 재계산 금지 (AGENTS.md).
        """
        try:
            from backend.app.core.trade_mode import is_virtual_mode
            from backend.app.services.engine_state import state

            _is_virtual = is_virtual_mode(state.integrated_system_settings_cache)
            now_str = datetime.now(_KST).strftime("%H:%M")

            from datetime import date as _date
            from backend.app.core.trading_calendar import get_chart_reference_trading_day, get_recent_trading_days

            # 거래일 기준 오늘 — get_chart_reference_trading_day() SSOT (프론트 getTradingToday()와 동일 의미 — P10).
            # 08:00 프리마켓 개시 전에는 직전 거래일 반환 → 텔레그램 손익 명령어와 프론트 수익현황 페이지 기준 일치.
            ref = get_chart_reference_trading_day()
            ref_iso = ref.isoformat()
            label = period
            if period == "당일":
                line = await _compute_period_pnl("당일", date_from=ref_iso, date_to=ref_iso, is_virtual=_is_virtual)
            elif period == "5일":
                recent5 = get_recent_trading_days(5, from_date=ref)
                if recent5:
                    line = await _compute_period_pnl(
                        "5거래일", date_from=recent5[0].isoformat(), date_to=recent5[-1].isoformat(), is_virtual=_is_virtual,
                    )
                else:
                    line = "  5거래일: 데이터 없음"
            elif period == "당월":
                month_start = _date(ref.year, ref.month, 1).isoformat()
                line = await _compute_period_pnl("당월", date_from=month_start, date_to=ref_iso, is_virtual=_is_virtual)
            else:  # 누적
                line = await _compute_period_pnl("누적", is_virtual=_is_virtual)

            text = f"📈 <b>{label} 실현 손익</b> ({now_str})\n\n{line}"
            await self._send(token, chat_id, text)
        except Exception as exc:
            await self._send(token, chat_id, f"⚠ {period} 손익 조회 오류: {str(exc)[:120]}")

    async def _cmd_status_full(self, token: str, chat_id: str, profile: str | None = None):
        """엔진·스케줄·스위치 + 리스크 상태 (계좌 제외 — 잔고 명령어와 분리, P23 책임 분리)."""
        try:
            from backend.app.services.engine_lifecycle import get_engine_status
            from backend.app.core.settings_file import load_integrated_system_settings

            eng = get_engine_status()
            eng_running = eng.get("running", False)
            flat = await load_integrated_system_settings()
            t_on = bool(flat["time_scheduler_on"])
            buy_on = bool(flat["auto_buy_on"])
            sell_on = bool(flat["auto_sell_on"])
            eff = auto_trading_effective(flat)
            now_str = datetime.now(_KST).strftime("%H:%M:%S")

            # 리스크 차단 상태 (저장된 SSOT만 표시 — P21 사용자 투명성, P10 SSOT)
            risk_lines = _build_risk_status_lines()

            text = (
                "📊 <b>상태</b>\n\n"
                f"⚙️ 매매엔진: {' 가동중' if eng_running else '⏹️ 정지'}\n"
                f"🔰 자동매매 마스터: {' ON' if t_on else '⏸️ OFF'}\n"
                f" 자동 매수: {' ON' if buy_on else '⏸️ OFF'}"
                f" ({flat['buy_time_start']}~{flat['buy_time_end']})\n"
                f"🏪 자동 매도: {' ON' if sell_on else '⏸️ OFF'}"
                f" ({flat['sell_time_start']}~{flat['sell_time_end']})\n"
                f"🤖 지금 자동매매 가능: {' 예' if eff else '⏸️ 아니오'}\n"
                f"🕐 확인 시각: {now_str} (KST)"
                f"{risk_lines}"
            )
            await self._send(token, chat_id, text)
        except Exception as exc:
            await self._send(token, chat_id, f" 상태 조회 오류: {str(exc)[:120]}")

    async def _cmd_account(self, token: str, chat_id: str):
        try:
            from backend.app.services.engine_account import get_account_snapshot
            from backend.app.core.trade_mode import is_virtual_mode
            from backend.app.services.engine_state import state

            snap = await get_account_snapshot()
            if not snap:
                await self._send(token, chat_id, " 계좌 데이터가 없습니다.\n엔진이 실행 중인지 확인하세요.")
                return

            _is_virtual = is_virtual_mode(state.integrated_system_settings_cache)
            acct_lines = await _build_account_brief_lines(snap, _is_virtual)
            text = f"💼 <b>계좌 현황</b>\n\n{acct_lines}"
            await self._send(token, chat_id, text)
        except Exception as exc:
            await self._send(token, chat_id, f" 계좌 조회 오류: {str(exc)[:120]}")

    async def _cmd_sector(self, token: str, chat_id: str) -> None:
        """업종 강도 상위 5개 요약 — 업종명, 가산점(획득/만점), 종목 최대 5개.

        sector_summary_cache를 직접 사용 (P10 SSOT — 프론트엔드 업종순위와 동일 데이터).
        만점은 compute_sector_total_max SSOT 헬퍼로 계산 (sector_score.py 공식 단일 소스).
        종목은 boost_score 내림차순 최대 5개 이름만 표시.
        """
        try:
            from backend.app.services.engine_state import state
            from backend.app.domain.sector_score import compute_sector_total_max

            ss = state.sector_summary_cache
            if not ss or not ss.sectors:
                await self._send(token, chat_id, "📊 업종 데이터가 아직 없습니다. 엔진 가동 후 다시 시도하세요.")
                return

            sectors = ss.sectors
            now_str = datetime.now(_KST).strftime("%H:%M")

            # 만점 계산 — 설정 캐시의 슬라이더 값 사용 (P10 SSOT, P13 메모리 캐시)
            cache = state.integrated_system_settings_cache
            n_sectors = len(sectors)
            total_max = compute_sector_total_max(
                n_sectors,
                rise_ratio_slider=int(cache.get("sector_bonus_rise_ratio_slider", 0)),
                relative_strength_slider=int(cache.get("sector_bonus_relative_strength_slider", 0)),
                trade_amount_slider=int(cache.get("sector_bonus_trade_amount_slider", 0)),
            )

            lines = [f"📊 <b>업종 상위 5</b> ({now_str})  만점 {fmt_score(total_max)}\n"]

            for s in sectors[:5]:
                # 업종 내 종목 — boost_score 내림차순, 동점 시 등락률 내림차순, 최대 5개
                top_stocks = sorted(
                    s.stocks,
                    key=lambda st: (-st.boost_score, -st.change_rate, st.name),
                )[:5]
                stock_names = "  ".join(st.name for st in top_stocks)
                lines.append(
                    f"<b>{s.rank}. {s.sector}</b>  "
                    f"가산점 {fmt_score(s.final_score)}/{fmt_score(total_max)}"
                )
                if stock_names:
                    lines.append(f"  종목: {stock_names}")

            await self._send(token, chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(token, chat_id, f"⚠ 업종 조회 오류: {str(exc)[:120]}")

    async def _cmd_buy_candidates(self, token: str, chat_id: str) -> None:
        """매수 후보 (가드 통과 종목) 최대 10위 전송.

        buy_targets만 표시 (blocked_targets 제외) — sector_summary_cache SSOT.
        각 종목: 순위, 종목명, 대비, 등락률, 가산점(획득/만점), 업종.
        만점은 compute_stock_boost_max SSOT 헬퍼로 계산 (buy_filter.py 공식 단일 소스).
        실시간 필드(change, change_rate)는 틱 미수신 시 None일 수 있으므로
        "미수신"으로 명시 표시 (P20 폴백 금지).
        """
        try:
            from backend.app.services.sector_data_provider import get_buy_targets_sector_stocks
            from backend.app.services.engine_state import state
            from backend.app.domain.buy_filter import compute_stock_boost_max

            targets_all = await get_buy_targets_sector_stocks()
            # 가드 통과 종목만 (buy_targets) — blocked_targets 제외
            targets = [t for t in targets_all if t.get("guard_pass") is True][:10]
            now_str = datetime.now(_KST).strftime("%H:%M")

            if not targets:
                await self._send(token, chat_id, f"🎯 매수 후보 ({now_str})\n후보 없음")
                return

            # 종목 가산점 만점 — 설정 캐시 기반 (P10 SSOT, P13 메모리 캐시)
            cache = state.integrated_system_settings_cache
            boost_max = compute_stock_boost_max(
                boost_high_on=bool(cache.get("boost_high_breakout_on", False)),
                boost_high_score=float(cache.get("boost_high_breakout_score", 1.0)),
                boost_order_ratio_on=bool(cache.get("boost_order_ratio_on", False)),
                boost_order_ratio_score=float(cache.get("boost_order_ratio_score", 1.0)),
                boost_program_net_buy_on=bool(cache.get("boost_program_net_buy_on", False)),
                boost_program_net_buy_score=float(cache.get("boost_program_net_buy_score", 1.0)),
                boost_news_on=bool(cache.get("boost_news_on", False)),
                boost_news_score=float(cache.get("boost_news_score", 1.0)),
            )

            lines = [f"🎯 <b>매수 후보 TOP {len(targets)}</b> ({now_str})\n가산점 만점 {fmt_score(boost_max)}"]
            for t in targets:
                # 대비(원) — None 시 "미수신" (P20 폴백 금지). 프론트 createChangeCell과 동일 (▲/▼ + 콤마).
                change_raw = t.get("change")
                if change_raw is not None:
                    try:
                        ch = int(change_raw)
                        change_txt = f"{fmt_change(ch)}원"
                    except (ValueError, TypeError):
                        change_txt = "미수신"
                else:
                    change_txt = "미수신"

                # 등락률 — None 시 "미수신". 프론트 createRateCell과 동일 (fmtRate + %, +/- 부호).
                rate_raw = t.get("change_rate")
                if rate_raw is not None:
                    try:
                        rate = float(rate_raw)
                        rate_txt = fmt_rate(rate)
                    except (ValueError, TypeError):
                        rate_txt = "미수신"
                else:
                    rate_txt = "미수신"

                # 가산점 — boost_score (0.0 = 미부여, 명시적 값)
                boost = float(t.get("boost_score") or 0.0)
                sector = t.get("sector") or ""
                sec_txt = f" [{sector}]" if sector else ""
                lines.append(
                    f"\n{t['rank']}. {t['name']}{sec_txt}\n"
                    f"   {change_txt}  {rate_txt}\n"
                    f"   가산점 {fmt_score(boost)}/{fmt_score(boost_max)}"
                )

            await self._send(token, chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(token, chat_id, f"⚠ 매수 후보 조회 오류: {str(exc)[:120]}")

    async def _cmd_settings(self, token: str, chat_id: str) -> None:
        """주요 설정값 조회 (조회 전용 — 변경 불가, P21 사용자 투명성).

        설정 변경은 UI에서만 가능 — 본 명령어는 읽기 전용 (P15/P16).
        """
        try:
            from backend.app.core.settings_file import load_integrated_system_settings

            flat = await load_integrated_system_settings()
            body = _build_settings_lines(flat)
            text = f"⚙️ <b>설정 조회</b> (변경은 UI에서만)\n\n{body}"
            await self._send(token, chat_id, text)
        except Exception as exc:
            await self._send(token, chat_id, f"⚠ 설정 조회 오류: {str(exc)[:120]}")


# ── 설정 변경 시 폴링 start/stop/restart 단일 진입 (engine_service·settings 공유) ────
TELEGRAM_POLLING_KEYS = frozenset({
    "tele_on",
    "telegram_bot_token_test",
    "telegram_bot_token_real",
    "telegram_chat_id",
})
_TELEGRAM_CRED_KEYS = frozenset({
    "telegram_bot_token_test",
    "telegram_bot_token_real",
    "telegram_chat_id",
})


async def apply_telegram_polling_change(changed_keys: set[str]) -> None:
    """설정 변경에 맞춰 폴링을 start/stop/restart.

    - tele_on=False → stop
    - tele_on=True + 토큰/chat_id 변경 → stop+start (즉시 재폴링)
    - tele_on=True + tele_on만 변경 → start (폴링 미실행 시 기동)
    """
    if not (changed_keys & TELEGRAM_POLLING_KEYS):
        return
    try:
        from backend.app.services.engine_state import state

        tele_on = bool(state.integrated_system_settings_cache.get("tele_on", False))
        if not tele_on:
            await telegram_bot.stop_async()
            logger.info("[알림] 텔레그램 OFF → 폴링 종료")
            return
        # tele_on=True: 토큰·chat_id 변경 시 실행 중이면 stop 후 start로 즉시 재폴링.
        if changed_keys & _TELEGRAM_CRED_KEYS and telegram_bot.is_running:
            await telegram_bot.stop_async()
        telegram_bot.start()
        logger.info("[알림] 텔레그램 설정 변경 → 폴링 (재)시작")
    except Exception:
        logger.warning("[알림] 폴링 start/stop 실패", exc_info=True)


telegram_bot = TelegramBot()
