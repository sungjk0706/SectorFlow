# -*- coding: utf-8 -*-
"""
텔레그램 양방향 Bot Command 리스너 (로컬 설정 파일 + 메모리 상태 기반)

지원 명령어:
  자동     -- 자동매매 마스터 ON/OFF 토글 (time_scheduler_on)
  매수     -- 자동 매수 스위치 ON/OFF 토글 (auto_buy_on)
  매도     -- 자동 매도 스위치 ON/OFF 토글 (auto_sell_on)
  상태     -- 스케줄·스위치 + 계좌 요약
  잔고     -- 계좌 현황만
  현황     -- 상태 와 동일 (호환)
  계좌     -- 잔고 와 동일 (호환)
  도움말   -- 명령어 목록
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from app.services.auto_trading_effective import auto_trading_effective

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

_KST = timezone(timedelta(hours=9))


class TelegramBot:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._offsets: dict[str, int] = {}
        self._last_poll_ok_mon: float | None = None
        self._last_poll_err_mon: float | None = None
        self._last_poll_err_msg: str = ""

    def start(self, _db_getter=None):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[텔레그램] 폴링 시작")

    async def stop_async(self) -> None:
        """폴링 태스크가 httpx 대기 중이어도 취소·종료를 기다린다(데스크톱 종료 시 잔류 방지)."""
        self._running = False
        t = self._task
        if t and not t.done():
            t.cancel()
            try:
                await asyncio.wait_for(t, timeout=12.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._task = None
        self._last_poll_ok_mon = None
        logger.info("[텔레그램] 폴링 종료")

    def stop(self) -> None:
        """비동기 루프 밖에서 취소만 할 때. 엔진 종료 경로는 stop_async 를 사용한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._last_poll_ok_mon = None
        logger.info("[텔레그램] 폴링 종료(취소만, await 없음)")

    def get_poll_ok_age_sec(self) -> float | None:
        """마지막 getUpdates 성공(HTTP 200·ok) 이후 경과 초. 없으면 None."""
        if self._last_poll_ok_mon is None:
            return None
        return time.monotonic() - self._last_poll_ok_mon

    # ── 내부 폴링 루프 ────────────────────────────────────────────────────────

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
                logger.error("[텔레그램] 루프 오류: %s", _mask_telegram_url(str(exc)))
            # 실패 즉시 0초 재시도는 로그 폭주를 유발하므로 항상 최소 간격을 둔다.
            if not tasks:
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(2 if had_error else 1)

    def _fetch_enabled_settings(self) -> list[dict]:
        """
        tele_on=True 인 모든 설정 소스(루트 settings.json + data/<사용자>/settings.json)에서 수집.
        UI는 로그인 사용자 프로필에만 저장하므로 사용자 파일을 반드시 포함해야 원격 명령이 동작한다.
        """
        try:
            from app.core.settings_file import iter_merged_settings_profiles
            from app.core.encryption import decrypt_value

            rows: list[dict] = []
            seen_tokens: set[str] = set()

            for profile_key, flat in iter_merged_settings_profiles():
                if not flat.get("tele_on"):
                    continue
                raw_token = flat.get("telegram_bot_token") or ""
                if str(raw_token).startswith("gAAAA"):
                    token = (decrypt_value(raw_token) or "").strip()
                else:
                    token = str(raw_token).strip()
                chat_raw = str(flat.get("telegram_chat_id") or "").strip()
                if not token or not chat_raw:
                    continue
                if token in seen_tokens:
                    continue
                seen_tokens.add(token)
                rows.append({
                    "telegram_bot_token": token,
                    "telegram_chat_id":   _normalize_chat_id(chat_raw),
                    "telegram_on":        True,
                    "_profile":           profile_key,
                })
            return rows
        except Exception as exc:
            logger.debug("[텔레그램] 설정 조회 실패: %s", exc)
            return []

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
                logger.warning("[텔레그램] 런타임 종료 감지로 폴링 중단: %s", masked)
                self._running = False
                return
            now = time.monotonic()
            if (
                self._last_poll_err_msg != masked
                or self._last_poll_err_mon is None
                or (now - self._last_poll_err_mon) >= 10.0
            ):
                logger.debug("[텔레그램] 업데이트 조회 실패: %s", masked)
                self._last_poll_err_msg = masked
                self._last_poll_err_mon = now
            return

        if not data.get("ok"):
            return

        self._last_poll_ok_mon = time.monotonic()

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
                logger.warning("[텔레그램] 비승인 채팅 ID %s (허용: %s)", sender_id, allowed_chat)
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
            logger.debug(f"[텔레그램] 메시지 전송 오류: {exc}")

    # ── 명령어 라우터 ─────────────────────────────────────────────────────────

    async def _handle_command(self, token: str, chat_id: str, text: str, profile: Optional[str] = None):
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
        elif cmd in ("거래", "trade"):
            await self._send(
                token,
                chat_id,
                "ℹ️ 인메모리 거래내역 집계는 제거되었습니다. 잔고·상태로 계좌를 확인하세요.",
            )
        elif cmd in ("상태", "status"):
            await self._cmd_status_full(token, chat_id, profile)
        elif cmd in ("현황",):
            await self._cmd_status_full(token, chat_id, profile)
        elif cmd in ("잔고", "balance"):
            await self._cmd_account(token, chat_id)
        elif cmd in ("계좌", "account"):
            await self._cmd_account(token, chat_id)
        elif cmd in ("업종", "섹터", "sector"):
            await self._cmd_sector(token, chat_id)
        elif cmd in ("후보", "candidate"):
            await self._cmd_buy_candidates(token, chat_id)
        elif cmd in ("수익", "profit"):
            await self._cmd_profit_discontinued(token, chat_id)
        elif cmd in ("휴일", "holiday"):
            await self._cmd_toggle_holiday(token, chat_id, profile)
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
            "상태  -- 스케줄·스위치 + 지금 자동매매 가능 여부 + 계좌 요약\n"
            "잔고  -- 계좌 현황만\n"
            "업종  -- 업종 분석 상위/하위 요약\n"
            "후보  -- 매수후보 1~10순위\n"
            "휴일  -- 공휴일 자동매매 차단 ON/OFF (토글)\n"
            "도움말 -- 이 메시지"
        )
        await self._send(token, chat_id, text)

    async def _toggle_setting_bool(
        self,
        key: str,
        label: str,
    ) -> bool:
        """현재값 반전 후 저장. 새 값 반환."""
        from app.core.settings_file import load_settings, update_settings
        from app.services import engine_service

        flat = load_settings()
        if key in ("auto_buy_on", "auto_sell_on", "holiday_guard_on"):
            cur = bool(flat.get(key, True))
        else:
            cur = bool(flat.get(key, False))
        new = not cur
        update_settings({key: new})
        await engine_service.refresh_engine_settings_cache(None, use_root=True)
        from app.services.engine_account_notify import (
            notify_desktop_header_refresh,
            notify_desktop_settings_toggled,
        )
        notify_desktop_header_refresh()
        notify_desktop_settings_toggled()
        logger.info("[텔레그램] 설정 %s -> %s (%s)", key, new, label)
        return new

    async def _cmd_toggle_auto_master(self, token: str, chat_id: str, profile: Optional[str] = None):
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

    async def _cmd_toggle_auto_buy(self, token: str, chat_id: str, profile: Optional[str] = None):
        try:
            new = await self._toggle_setting_bool("auto_buy_on", "자동 매수")
            await self._send(
                token,
                chat_id,
                f"{'' if new else '⏸️'} <b>자동 매수</b> <b>{'ON' if new else 'OFF'}</b>",
            )
        except Exception as exc:
            await self._send(token, chat_id, f" 오류 발생: {str(exc)[:120]}")

    async def _cmd_toggle_auto_sell(self, token: str, chat_id: str, profile: Optional[str] = None):
        try:
            new = await self._toggle_setting_bool("auto_sell_on", "자동 매도")
            await self._send(
                token,
                chat_id,
                f"{'' if new else '⏸️'} <b>자동 매도</b> <b>{'ON' if new else 'OFF'}</b>",
            )
        except Exception as exc:
            await self._send(token, chat_id, f" 오류 발생: {str(exc)[:120]}")

    async def _cmd_status_full(self, token: str, chat_id: str, profile: Optional[str] = None):
        try:
            from app.services.engine_service import get_status, get_account_snapshot
            from app.core.settings_file import load_settings

            eng = get_status()
            eng_running = eng.get("running", False)
            flat = load_settings()
            t_on = bool(flat.get("time_scheduler_on", False))
            buy_on = bool(flat.get("auto_buy_on", True))
            sell_on = bool(flat.get("auto_sell_on", True))
            eff = auto_trading_effective(flat)
            now_str = datetime.now(_KST).strftime("%H:%M:%S")

            snap = get_account_snapshot()
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

            text = (
                "📊 <b>상태</b>\n\n"
                f"⚙️ 매매엔진: {' 가동중' if eng_running else '⏹️ 정지'}\n"
                f"🔰 자동매매 마스터: {' ON' if t_on else '⏸️ OFF'}\n"
                f" 자동 매수: {' ON' if buy_on else '⏸️ OFF'}"
                f" ({flat.get('buy_time_start', '09:00')}~{flat.get('buy_time_end', '15:20')})\n"
                f"🏪 자동 매도: {' ON' if sell_on else '⏸️ OFF'}"
                f" ({flat.get('sell_time_start', '09:00')}~{flat.get('sell_time_end', '15:20')})\n"
                f"🤖 지금 자동매매 가능: {' 예' if eff else '⏸️ 아니오'}\n"
                f"🕐 확인 시각: {now_str} (KST)"
                f"{acct_lines}"
            )
            await self._send(token, chat_id, text)
        except Exception as exc:
            await self._send(token, chat_id, f" 상태 조회 오류: {str(exc)[:120]}")

    async def _cmd_account(self, token: str, chat_id: str):
        try:
            from app.services.engine_service import get_account_snapshot

            snap = get_account_snapshot()
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
        """섹터 강도 상위/하위 요약."""
        try:
            from app.services import engine_service
            from app.services.engine_sector_score import compute_full_sector_summary

            inputs = engine_service.get_sector_summary_inputs()
            if not inputs.get("all_codes"):
                await self._send(token, chat_id, " 종목 데이터가 없습니다. 엔진 가동 후 다시 시도하세요.")
                return

            summary = compute_full_sector_summary(
                **inputs,
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
                amt_b = s.total_trade_amount / 1e8
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
                    amt_b = s.total_trade_amount / 1e8
                    lines.append(
                        f"  {s.rank}. {s.sector}  "
                        f"avg {s.avg_change_rate:+.2f}%  "
                        f"상승 {s.rise_count}/{s.total}"
                    )

            # 지수 가드
            if summary.index_guard_active:
                lines.append(f"\n 지수 가드 발동: {summary.index_guard_reason}")

            await self._send(token, chat_id, "\n".join(lines))
        except Exception as exc:
            await self._send(token, chat_id, f" 업종 조회 오류: {str(exc)[:120]}")

    async def _cmd_buy_candidates(self, token: str, chat_id: str) -> None:
        """매수후보 1~10순위 전송."""
        try:
            from app.services import engine_service

            targets = engine_service.get_buy_targets_snapshot()
            now_str = datetime.now(_KST).strftime("%H:%M")

            if not targets:
                await self._send(token, chat_id, f"🎯 매수후보 ({now_str})\n후보 없음")
                return

            lines = [f"🎯 <b>매수후보 TOP {len(targets)}</b> ({now_str})\n"]
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
            await self._send(token, chat_id, f"⚠ 매수후보 조회 오류: {str(exc)[:120]}")

    async def _cmd_profit_discontinued(self, token: str, chat_id: str) -> None:
        await self._send(
            token,
            chat_id,
            "ℹ️ 체결 이력 기반 당일 실현 손익 집계는 제거되었습니다.\n"
            "증권사 앱/HTS에서 당일 실현을 확인하거나 잔고·상태를 참고하세요.",
        )

    async def _cmd_toggle_holiday(self, token: str, chat_id: str, profile: Optional[str] = None):
        new = await self._toggle_setting_bool("holiday_guard_on", "공휴일 자동매매")
        status = "ON (공휴일 차단)" if new else "OFF (공휴일 허용)"
        await self._send(token, chat_id, f"📅 공휴일 자동매매: <b>{status}</b>")


telegram_bot = TelegramBot()
