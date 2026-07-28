# -*- coding: utf-8 -*-
"""
텔레그램 양방향 Bot Command 리스너 (로컬 설정 파일 + 메모리 상태 기반)

지원 명령어 (한글 / 영문 alias):
  자동 / auto       -- 자동매매 마스터 ON/OFF 토글 (time_scheduler_on)
  매수              -- 자동 매수 스위치 ON/OFF 토글 (auto_buy_on)
  매도              -- 자동 매도 스위치 ON/OFF 토글 (auto_sell_on)
  상태 / status     -- 스케줄·스위치 + 자동매매 가능 여부 + 계좌 요약
  현황              -- 상태 와 동일 (호환)
  잔고 / balance    -- 계좌 현황만
  계좌 / account    -- 잔고 와 동일 (호환)
  업종 / sector     -- 업종 분석 상위/하위 요약
  후보 / candidate  -- 매수 후보 1~10순위
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
      - KRX 서킷브레이커/사이드카: engine_state.krx_circuit_breaker_active + market_phase["krx_alert"]

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
        # KRX 서킷브레이커/사이드카 상태
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
                f"🚫 매매 차단 중: KRX 서킷브레이커/사이드카 발동{alert_txt}"
            )
        # 정상
        return (
            "\n\n🛡️ <b>리스크 상태</b>\n"
            "✅ 정상 (차단 없음)"
        )
    except Exception:
        logger.warning("[알림] 리스크 상태 조회 실패 — 상태 명령어에서 리스크 라인 생략", exc_info=True)
        return ""


class TelegramBot:
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

    def start(self, _db_getter=None):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[알림] 폴링 시작")

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
            await self._cmd_toggle_auto_buy(token, chat_id, profile)
        elif cmd == "매도":
            await self._cmd_toggle_auto_sell(token, chat_id, profile)
        elif cmd in ("상태", "status"):
            await self._cmd_status_full(token, chat_id, profile)
        elif cmd in ("현황",):
            await self._cmd_status_full(token, chat_id, profile)
        elif cmd in ("잔고", "balance"):
            await self._cmd_account(token, chat_id)
        elif cmd in ("계좌", "account"):
            await self._cmd_account(token, chat_id)
        elif cmd in ("업종", "업종", "sector"):
            await self._cmd_sector(token, chat_id)
        elif cmd in ("후보", "candidate"):
            await self._cmd_buy_candidates(token, chat_id)
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
            "매수  -- 자동 매수 스위치 ON/OFF (토글)\n"
            "매도  -- 자동 매도 스위치 ON/OFF (토글)\n"
            "상태  -- 스케줄·스위치 + 지금 자동매매 가능 여부 + 계좌 요약 (현황)\n"
            "잔고  -- 계좌 현황만 (계좌)\n"
            "업종  -- 업종 분석 상위/하위 요약\n"
            "후보  -- 매수 후보 1~10순위\n"
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

    async def _cmd_toggle_auto_buy(self, token: str, chat_id: str, profile: str | None = None):
        try:
            new = await self._toggle_setting_bool("auto_buy_on", "자동 매수")
            await self._send(
                token,
                chat_id,
                f"{'' if new else '⏸️'} <b>자동 매수</b> <b>{'ON' if new else 'OFF'}</b>",
            )
        except Exception as exc:
            await self._send(token, chat_id, f" 오류 발생: {str(exc)[:120]}")

    async def _cmd_toggle_auto_sell(self, token: str, chat_id: str, profile: str | None = None):
        try:
            new = await self._toggle_setting_bool("auto_sell_on", "자동 매도")
            await self._send(
                token,
                chat_id,
                f"{'' if new else '⏸️'} <b>자동 매도</b> <b>{'ON' if new else 'OFF'}</b>",
            )
        except Exception as exc:
            await self._send(token, chat_id, f" 오류 발생: {str(exc)[:120]}")

    async def _cmd_status_full(self, token: str, chat_id: str, profile: str | None = None):
        try:
            from backend.app.services.engine_lifecycle import get_engine_status
            from backend.app.services.engine_account import get_account_snapshot
            from backend.app.core.settings_file import load_integrated_system_settings

            eng = get_engine_status()
            eng_running = eng.get("running", False)
            flat = await load_integrated_system_settings()
            t_on = bool(flat["time_scheduler_on"])
            buy_on = bool(flat["auto_buy_on"])
            sell_on = bool(flat["auto_sell_on"])
            eff = auto_trading_effective(flat)
            now_str = datetime.now(_KST).strftime("%H:%M:%S")

            snap = await get_account_snapshot()
            acct_lines = ""
            if snap:
                deposit    = snap.get("deposit", 0) or 0
                total_eval = snap.get("total_eval", 0) or 0
                total_pnl  = snap.get("total_pnl", 0) or 0
                total_rate = snap.get("total_rate", 0) or 0
                pos_cnt    = snap.get("position_count", 0) or 0
                snap_at    = (snap.get("snapshot_at") or "")[:19].replace("T", " ")
                pnl_sign  = "+" if total_pnl >= 0 else ""
                rate_sign = "+" if total_rate >= 0 else ""
                acct_lines = (
                    f"\n💰 예수금: {deposit:,.0f}원\n"
                    f"📈 총평가: {total_eval:,.0f}원\n"
                    f"📊 총손익: {pnl_sign}{total_pnl:,.0f}원 ({rate_sign}{total_rate:.2f}%)\n"
                    f"🏷️ 보유종목: {pos_cnt}개\n"
                    f"🕐 계좌기준: {snap_at}"
                )
            else:
                acct_lines = "\n 계좌 스냅샷 없음 (엔진 가동 여부 확인)"

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
                f"{acct_lines}"
            )
            await self._send(token, chat_id, text)
        except Exception as exc:
            await self._send(token, chat_id, f" 상태 조회 오류: {str(exc)[:120]}")

    async def _cmd_account(self, token: str, chat_id: str):
        try:
            from backend.app.services.engine_account import get_account_snapshot

            snap = await get_account_snapshot()
            if not snap:
                await self._send(token, chat_id, " 계좌 데이터가 없습니다.\n엔진이 실행 중인지 확인하세요.")
                return

            deposit    = snap.get("deposit", 0) or 0
            total_eval = snap.get("total_eval", 0) or 0
            total_pnl  = snap.get("total_pnl", 0) or 0
            total_rate = snap.get("total_rate", 0) or 0
            pos_cnt    = snap.get("position_count", 0) or 0
            snap_at    = (snap.get("snapshot_at") or "")[:19].replace("T", " ")

            pnl_sign  = "+" if total_pnl >= 0 else ""
            rate_sign = "+" if total_rate >= 0 else ""

            text = (
                "💼 <b>계좌 현황</b>\n\n"
                f"💰 예수금: {deposit:,.0f}원\n"
                f"📈 총평가: {total_eval:,.0f}원\n"
                f"📊 총손익: {pnl_sign}{total_pnl:,.0f}원 ({rate_sign}{total_rate:.2f}%)\n"
                f"🏷️ 보유종목: {pos_cnt}개\n"
                f"🕐 기준시각: {snap_at}"
            )
            await self._send(token, chat_id, text)
        except Exception as exc:
            await self._send(token, chat_id, f" 계좌 조회 오류: {str(exc)[:120]}")

    async def _cmd_sector(self, token: str, chat_id: str) -> None:
        """업종 강도 상위/하위 요약."""
        try:
            from backend.app.services.sector_data_provider import get_sector_summary_inputs
            from backend.app.domain.sector_calculator import compute_full_sector_summary

            inputs = await get_sector_summary_inputs()
            if not inputs.get("all_codes"):
                await self._send(token, chat_id, " 종목 데이터가 없습니다. 엔진 가동 후 다시 시도하세요.")
                return

            # krx_codes/nxt_codes는 수신률 분리 집계 전용, all_filter_codes는 구독 대상 식별 전용
            # — compute_full_sector_summary에는 all_codes만 전달
            compute_inputs = {k: v for k, v in inputs.items() if k not in ("krx_codes", "nxt_codes", "all_filter_codes")}
            summary = await compute_full_sector_summary(
                **compute_inputs,
            )

            sectors = summary.sectors
            if not sectors:
                await self._send(token, chat_id, "📊 업종 데이터가 아직 없습니다.")
                return

            now_str = datetime.now(_KST).strftime("%H:%M")
            lines = [f"📊 <b>업종 분석 요약</b> ({now_str})\n"]

            # 상위 5개
            lines.append("🔺 <b>상위 업종</b>")
            for s in sectors[:5]:
                amt_b = s.avg_trade_amount / 1e8
                lines.append(
                    f"  {s.rank}. {s.sector}  "
                    f"avg {s.avg_change_rate:+.2f}%  "
                    f"상승 {s.rise_count}/{s.total}  "
                    f"거래대금 {amt_b:.0f}억"
                )

            # 하위 3개 (역순)
            if len(sectors) > 5:
                lines.append("\n🔻 <b>하위 업종</b>")
                for s in sectors[-3:]:
                    amt_b = s.avg_trade_amount / 1e8
                    lines.append(
                        f"  {s.rank}. {s.sector}  "
                        f"avg {s.avg_change_rate:+.2f}%  "
                        f"상승 {s.rise_count}/{s.total}"
                    )

            await self._send(token, chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(token, chat_id, f" 업종 조회 오류: {str(exc)[:120]}")

    async def _cmd_buy_candidates(self, token: str, chat_id: str) -> None:
        """매수 후보 1~10순위 전송."""
        try:
            from backend.app.services.sector_data_provider import get_buy_targets_sector_stocks

            targets = await get_buy_targets_sector_stocks()
            now_str = datetime.now(_KST).strftime("%H:%M")

            if not targets:
                await self._send(token, chat_id, f"🎯 매수 후보 ({now_str})\n후보 없음")
                return

            lines = [f"🎯 <b>매수 후보 TOP {len(targets)}</b> ({now_str})\n"]
            for t in targets:
                rate = t["change_rate"]
                sign = "▲" if rate > 0 else ("▼" if rate < 0 else "━")
                strength = t["strength"]
                str_txt = f"  체결강도 {strength:.0f}" if strength >= 0 else ""
                ta = t.get("trade_amount") or 0
                amt_억 = ta / 1_0000_0000 if ta > 0 else 0
                amt_txt = f"  {amt_억:,.0f}억" if amt_억 > 0 else ""
                sector = t.get("sector") or ""
                sec_txt = f"  [{sector}]" if sector else ""
                lines.append(
                    f"  {t['rank']}. {t['name']}  "
                    f"{t['cur_price']:,}원  {sign}{abs(rate):.2f}%"
                    f"{str_txt}{amt_txt}{sec_txt}"
                )

            await self._send(token, chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(token, chat_id, f"⚠ 매수 후보 조회 오류: {str(exc)[:120]}")


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
