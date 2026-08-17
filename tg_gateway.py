#!/usr/bin/env python3
"""ITLG Gateway v3 — modern PTB, all inline buttons, one-message rule.

Konvensi (skill modern-telegram-bot):
- Semua interaksi via inline buttons (no text commands selain /start /help)
- One-message rule: edit pesan yang ada, jangan kirim baru (send_or_replace anti-stack)
- Back button wajib di semua sub-view
- Owner gate (group=-1 TypeHandler + ApplicationHandlerStop)
- block=False pada CallbackQueryHandler (multi-user non-blocking)
- Global error handler biar bug kelihatan
- auto-delete input teks user
- Tidak pakai monospace / em dash (pakai ·)
"""
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import bot as itlg

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, Chat
from telegram.ext import (
    Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, TypeHandler, filters,
)

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
SERVICE_NAME = os.environ.get("ITLG_SERVICE", "itlg-claim")
CONFIG_FILE = SCRIPT_DIR / "config.json"
WIB = timezone(timedelta(hours=7))

_busy = set()          # chat_id yang lagi proses panjang (claim/group/rec/sync)
LAST_BOT_MSG = {}      # chat_id -> message_id (anti-stack)
# State input config via bot: chat_id -> {"field": ..., "account": ...}
CONFIG_INPUT = {}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


def is_dm(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.type == Chat.PRIVATE


def fmt_wib(fmt="%H:%M"):
    return datetime.now(WIB).strftime(fmt)


def fmt_num(n):
    try:
        return f"{n:,.0f}".replace(",", ".")
    except Exception:
        return str(n)


def countdown(secs):
    h, m, s = int(secs // 3600), int((secs % 3600) // 60), int(secs % 60)
    if h > 0:
        return f"{h:02d}j {m:02d}m"
    return f"{m:02d}m {s:02d}s"


def bot_pid():
    """Reliable detection if the ITLG bot daemon is running."""
    pid_file = SCRIPT_DIR / ".bot.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return pid
        except Exception:
            pass
    try:
        out = subprocess.getoutput('pgrep -f "start_daemon.py"').strip()
        pids = []
        for line in out.splitlines():
            try:
                p = int(line.strip())
                with open(f"/proc/{p}/cmdline", "rb") as fh:
                    cmd = fh.read().decode(errors="ignore")
                if "start_daemon.py" in cmd and SERVICE_NAME in cmd:
                    pids.append(p)
            except Exception:
                continue
        if pids:
            return min(pids)
    except Exception:
        pass
    return None


def bot_pid_str():
    pid = bot_pid()
    return f"✅ Berjalan (PID {pid})" if pid else "❌ Berhenti"


async def send_or_replace(bot, chat_id: int, text: str, markup=None):
    """Delete previous bot msg in chat (if tracked) then send new. Anti-stack."""
    prev = LAST_BOT_MSG.get(chat_id)
    if prev:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prev)
        except Exception:
            pass
    try:
        msg = await bot.send_message(chat_id=chat_id, text=text,
                                     reply_markup=markup, parse_mode="HTML")
        LAST_BOT_MSG[chat_id] = msg.message_id
        return msg
    except Exception:
        # HTML ke-tolak (tag salah) — kirim ulang tanpa HTML
        try:
            msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
            LAST_BOT_MSG[chat_id] = msg.message_id
            return msg
        except Exception:
            return None


async def safe_edit_msg(bot, chat_id: int, msg_id: int, text: str, markup=None):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                    text=text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                        text=text, reply_markup=markup)
            return True
        except Exception:
            return False


async def edit_cq_or_send(q, text: str, markup=None):
    """Edit the callback's message; if that fails, delete old + send new."""
    try:
        await q.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        try:
            await q.edit_message_text(text, reply_markup=markup)
            return True
        except Exception:
            await send_or_replace(q.get_bot(), q.message.chat.id, text, markup)
            return True


async def safe_hapus(bot, chat_id: int, msg_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


# ─── Keyboard builders ───────────────────────────────────────────────────────

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Saldo", callback_data="bal"),
         InlineKeyboardButton("⛏️ Klaim", callback_data="claim")],
        [InlineKeyboardButton("👥 Group", callback_data="grp"),
         InlineKeyboardButton("♻️ Recovery", callback_data="rec")],
        [InlineKeyboardButton("🔄 Sinkron", callback_data="sync"),
         InlineKeyboardButton("🛠️ Kelola", callback_data="mgmt")],
        [InlineKeyboardButton("⚙️ Config", callback_data="cfg"),
         InlineKeyboardButton("ℹ️ Info", callback_data="help")],
    ])


def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main")]])


def kb_grp(claimable: bool):
    rows = []
    if claimable:
        rows.append([InlineKeyboardButton("⛏️ Klaim Group", callback_data="grpdo")])
    rows.append([InlineKeyboardButton("🔙 Menu", callback_data="main")])
    return InlineKeyboardMarkup(rows)


def kb_rec(can_recover: bool):
    rows = []
    if can_recover:
        rows.append([InlineKeyboardButton("♻️ Klaim Recovery", callback_data="recdo")])
    rows.append([InlineKeyboardButton("🔙 Menu", callback_data="main")])
    return InlineKeyboardMarkup(rows)


def kb_mgmt(bot_running: bool):
    rows = []
    if bot_running:
        rows.append([InlineKeyboardButton("🛑 Stop", callback_data="stop"),
                     InlineKeyboardButton("🔄 Restart", callback_data="restart")])
    else:
        rows.append([InlineKeyboardButton("▶️ Start", callback_data="start")])
    rows.append([InlineKeyboardButton("🔙 Menu", callback_data="main")])
    return InlineKeyboardMarkup(rows)


def kb_stop_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yakin, Stop", callback_data="stopgo")],
        [InlineKeyboardButton("🔙 Batal", callback_data="mgmt")],
    ])


def kb_cfg():
    """Menu atur config (single account, root config.json)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Login ID", callback_data="cfgin:loginId"),
         InlineKeyboardButton("🔑 Passcode", callback_data="cfgin:passcode")],
        [InlineKeyboardButton("📧 Email", callback_data="cfgin:email"),
         InlineKeyboardButton("🔐 IMAP Pass", callback_data="cfgin:imapPassword")],
        [InlineKeyboardButton("🌐 Proxy", callback_data="cfgin:proxy"),
         InlineKeyboardButton("📸 Face Photo", callback_data="cfgin:facePhoto")],
        [InlineKeyboardButton("🔑 Login", callback_data="login"),
         InlineKeyboardButton("💾 Verifikasi", callback_data="verify")],
        [InlineKeyboardButton("🔙 Menu", callback_data="main")],
    ])


def kb_login_choice():
    """Pilih jalur login: OTP atau Face."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 OTP Login", callback_data="loginotp")],
        [InlineKeyboardButton("📸 Face Login", callback_data="loginface")],
        [InlineKeyboardButton("🔙 Batal", callback_data="cfg")],
    ])

# ─── Data gathering (sync, jalan di thread) ──────────────────────────────────

def _get_token(account=None):
    """Single account: selalu config root."""
    cfg = load_config()
    tk = itlg.get_session(cfg, allow_login=False)
    return cfg, tk


def _gather_dashboard(account=None):
    """Returns dict of live data. Runs in thread (network + slow)."""
    cfg, tk = _get_token()
    d = {"token_ok": bool(tk), "cfg": cfg, "account": "default"}
    if not tk:
        return d
    device_id = cfg.get("deviceId", "")
    try:
        d["bal"] = itlg.get_balance(tk, device_id)
    except Exception:
        d["bal"] = None
    try:
        d["ic"] = itlg.check_claimable(tk, device_id) or {}
    except Exception:
        d["ic"] = {}
    try:
        d["g"] = itlg.get_group_mining_list(tk, device_id) or {}
    except Exception:
        d["g"] = {}
    try:
        d["can_rec"], d["tot_rec"] = itlg.check_recovery(tk, device_id)
    except Exception:
        d["can_rec"], d["tot_rec"] = False, 0
    d["state"] = itlg.load_claim_state()
    d["sync"] = itlg.load_sync_state()
    d["pid"] = bot_pid()
    return d


def _mine_line(ic):
    if ic.get("isClaimable"):
        return "✅ Bisa diklaim!"
    nf = ic.get("nextFrame")
    if nf:
        remain = max(0, int((nf - time.time() * 1000) / 1000))
        return f"⏳ {countdown(remain)} lagi"
    return "⏳ Mining"


def _group_line(g):
    if not g:
        return "N/A"
    groups = g.get("groups", [])
    total_pool = sum(x.get("totalReward", 0) for x in groups)
    if g.get("requesterHasClaimedToday"):
        return f"✅ Claimed ({len(groups)} grup · pool {fmt_num(total_pool)})"
    if g.get("isClaimable"):
        return f"✅ Bisa diklaim! ({len(groups)} grup · pool {fmt_num(total_pool)})"
    nxt = g.get("nextTimeClaim")
    if nxt:
        remain = max(0, int((nxt - time.time() * 1000) / 1000))
        return f"⏳ {countdown(remain)} lagi"
    return f"⏳ Pending ({len(groups)} grup)"


def _recovery_line(d):
    if d.get("can_rec") and d.get("tot_rec", 0) > 0:
        return f"💎 +{fmt_num(d['tot_rec'])} ITLG"
    return "Tidak ada"


def _sync_line(d):
    sync = d.get("sync", {})
    if sync.get("last_ok"):
        return f"✅ {fmt_wib('%d/%m %H:%M')}"
    if sync.get("last_day"):
        return "⚠️ Gagal terakhir"
    return "Belum pernah"


# ─── Text builders ───────────────────────────────────────────────────────────

def text_dashboard(d):
    if not d.get("token_ok"):
        return ("📊 ITLG Dashboard\n"
                "━━━━━━━━━━━\n"
                "❌ Token tidak valid\n"
                "Jalankan di server: python3 bot.py --login-face")
    bal = d.get("bal")
    bal_s = f"<b>{fmt_num(bal)}</b> ITLG" if bal is not None else "?"
    mine = _mine_line(d.get("ic", {}))
    grp = _group_line(d.get("g", {}))
    rec = _recovery_line(d)
    sync = _sync_line(d)
    state = d.get("state", {})
    hist = state.get("history", [])
    avg = f" · ~{fmt_num(round(sum(hist) / len(hist), 1))}/klaim" if hist else ""
    pid = d.get("pid")
    bot_s = f"✅ Berjalan (PID {pid})" if pid else "❌ Berhenti"
    return (
        "📊 ITLG Dashboard\n"
        "━━━━━━━━━━━\n"
        f"💰 Saldo · {bal_s}\n"
        f"⛏️ Mining · {mine}{avg}\n"
        f"👥 Group · {grp}\n"
        f"♻️ Recovery · {rec}\n"
        f"🔄 Sinkron · {sync}\n"
        "━━━━━━━━━━━\n"
        f"🤖 Bot · {bot_s}\n"
        f"🕐 {fmt_wib()} WIB"
    )


def text_balance(d):
    if not d.get("token_ok"):
        return "❌ Token tidak valid\nJalankan: python3 bot.py --login-face"
    bal = d.get("bal")
    bal_s = f"<b>{fmt_num(bal)}</b> ITLG" if bal is not None else "?"
    mine = _mine_line(d.get("ic", {}))
    hist = d.get("state", {}).get("history", [])
    avg = f"~{fmt_num(round(sum(hist) / len(hist), 1))} ITLG/klaim" if hist else "-"
    per_day = f"~{fmt_num(round(sum(hist) / len(hist) * 6, 1))} ITLG/hari" if hist else "-"
    return (
        "💰 Saldo\n"
        "━━━━━━━━━━━\n"
        f"💎 {bal_s}\n"
        f"⛏️ {mine}\n"
        f"📈 {avg}\n"
        f"📈 {per_day}\n"
        f"🕐 {fmt_wib()} WIB"
    )


def text_group(d):
    if not d.get("token_ok"):
        return "❌ Token tidak valid\nJalankan: python3 bot.py --login-face"
    g = d.get("g", {})
    if not g:
        return "👥 Group Mining\n━━━━━━━━━━━\nTidak ada data group."
    groups = g.get("groups", [])
    total_pool = sum(x.get("totalReward", 0) for x in groups)
    lines = ["👥 Group Mining", "━━━━━━━━━━━"]
    if g.get("requesterHasClaimedToday"):
        lines.append(f"✅ Claimed hari ini ({len(groups)} grup)")
        lines.append(f"💎 Pool · {fmt_num(total_pool)} ITLG")
        nxt = g.get("nextTimeClaim")
        if nxt:
            remain = max(0, int((nxt - time.time() * 1000) / 1000))
            lines.append(f"⏳ Berikutnya · {countdown(remain)}")
    elif g.get("isClaimable"):
        lines.append(f"✅ Bisa diklaim! ({len(groups)} grup)")
        lines.append(f"💎 Pool · {fmt_num(total_pool)} ITLG")
    else:
        lines.append(f"⏳ Pending ({len(groups)} grup)")
        lines.append(f"💎 Pool · {fmt_num(total_pool)} ITLG")
        nxt = g.get("nextTimeClaim")
        if nxt:
            remain = max(0, int((nxt - time.time() * 1000) / 1000))
            lines.append(f"⏳ {countdown(remain)} lagi")
    lines.append(f"🕐 {fmt_wib()} WIB")
    return "\n".join(lines)


def text_recovery(d):
    if not d.get("token_ok"):
        return "❌ Token tidak valid\nJalankan: python3 bot.py --login-face"
    if d.get("can_rec") and d.get("tot_rec", 0) > 0:
        return (f"♻️ Recovery Burn\n━━━━━━━━━━━\n"
                f"💎 Bisa dipulihkan · +{fmt_num(d['tot_rec'])} ITLG\n"
                f"🕐 {fmt_wib()} WIB")
    return (f"♻️ Recovery Burn\n━━━━━━━━━━━\n"
            f"ℹ️ Tidak ada yang bisa dipulihkan saat ini\n"
            f"🕐 {fmt_wib()} WIB")


def text_mgmt(d):
    pid = d.get("pid")
    bot_s = f"✅ Berjalan (PID {pid})" if pid else "❌ Berhenti"
    return (
        "🛠️ Kelola Bot\n"
        "━━━━━━━━━━━\n"
        f"🤖 Daemon · {bot_s}\n"
        f"🕐 {fmt_wib()} WIB"
    )


def text_help():
    return (
        "ℹ️ ITLG Farm Bot\n"
        "━━━━━━━━━━━\n"
        "⛏️ Auto klaim mining · tiap 4 jam\n"
        "👥 Auto klaim group · tiap 24 jam\n"
        "♻️ Auto recovery burn\n"
        "🔄 Sinkron harian · silent + notif kalau antrian berubah\n"
        "━━━━━━━━━━━\n"
        "🎯 Antrian KYC\n"
        "Matching = lagi diproses curator. Angka matches di notif itu total global curator, bukan posisi kamu — wajar makin naik.\n"
        "Kamu maju kalau level KYC naik (VERIFY_ROUND_1 → dst).\n"
        "━━━━━━━━━━━\n"
        "💬 Semua bisa dikontrol dari tombol di bawah. Ketik /help kapan aja buat lihat info ini lagi.\n"
        "━━━━━━━━━━━\n"
        "☕ Support · saweria.co/febfrmn"
    )


# ─── Long ops (jalan di thread) ──────────────────────────────────────────────

def _run_claim():
    cfg, tk = _get_token()
    if not tk:
        return "❌ Token tidak valid\nJalankan: python3 bot.py --login-face"
    tk2, claimed = itlg.attempt_claim(cfg, tk)
    if claimed:
        bal = itlg.get_balance(tk2, cfg.get("deviceId", ""))
        return (f"✅ Klaim berhasil +{fmt_num(claimed)} ITLG\n"
                f"💰 Saldo · {fmt_num(bal) if bal is not None else '?'} ITLG")
    ic = itlg.check_claimable(tk2, cfg.get("deviceId", "")) or {}
    nf = ic.get("nextFrame")
    if nf:
        remain = max(0, int((nf - time.time() * 1000) / 1000))
        return f"⏳ Belum waktunya klaim\nBerikutnya · {countdown(remain)}"
    return "ℹ️ Belum bisa klaim sekarang"


def _run_group():
    cfg, tk = _get_token()
    if not tk:
        return "❌ Token tidak valid\nJalankan: python3 bot.py --login-face"
    tk2, claimed, gnext = itlg.attempt_group_claim(cfg, tk)
    if claimed:
        return "✅ Group mining berhasil diklaim!"
    if gnext:
        remain = max(0, int((gnext - time.time() * 1000) / 1000))
        return f"⏳ Group belum siap\nBerikutnya · {countdown(remain)}"
    return "❌ Group claim gagal. Cek log."


def _run_recovery():
    cfg, tk = _get_token()
    if not tk:
        return "❌ Token tidak valid\nJalankan: python3 bot.py --login-face"
    can, tot = itlg.check_recovery(tk, cfg.get("deviceId", ""))
    if not can or tot <= 0:
        return f"ℹ️ Tidak ada recovery\n💎 Total · {fmt_num(tot)} ITLG"
    tk2, recovered = itlg.attempt_recovery(cfg, tk)
    if recovered > 0:
        return f"✅ Recovery berhasil +{fmt_num(recovered)} ITLG"
    return "⚠️ Recovery gagal (mungkin belum unlock cycle)"


def _run_sync():
    cfg, tk = _get_token()
    if not tk:
        return "❌ Token tidak valid\nJalankan: python3 bot.py --login-face"
    ok = itlg.do_sync(cfg, tk, force=False)
    if ok:
        # Re-gather buat tampilkan antrian real di pesan
        d = _gather_dashboard()
        mine = _mine_line(d.get("ic", {}))
        grp = _group_line(d.get("g", {}))
        rec = _recovery_line(d)
        sync = _sync_line(d)
        return (
            "✅ Sinkron ok\n"
            f"💰 Saldo · <b>{fmt_num(d.get('bal'))} ITLG</b>\n"
            f"⛏️ Mining · {mine}\n"
            f"👥 Group · {grp}\n"
            f"♻️ Recovery · {rec}\n"
            f"🔄 {sync}\n"
            f"🕐 {fmt_wib()} WIB"
        )
    return f"⚠️ Sinkron gagal\nCoba lagi nanti\n🕐 {fmt_wib()} WIB"


def text_cfg():
    """Ringkasan config saat ini (single account)."""
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except Exception:
        cfg = {}
    tok = (SCRIPT_DIR / "token.json").exists()
    return ("⚙️ Config\n"
            "━━━━━━━━━━━\n"
            f"👤 Login ID · {cfg.get('loginId') or '❌ kosong'}\n"
            f"📧 Email · {cfg.get('email') or '❌ kosong'}\n"
            f"🌐 Proxy · {'✅ set' if cfg.get('proxy') else '❌ kosong'}\n"
            f"🔑 Token · {'✅ ada' if tok else '❌ kosong'}\n"
            f"🕐 {fmt_wib()} WIB")


def _verify_now():
    """Cek token aktif via API. Runs in thread."""
    try:
        cfg = load_config()
        tk = itlg.get_session(cfg, allow_login=False)
        if not tk:
            return "❌ Token tidak valid.\nJalankan login (⚙️ Config → 🔑 Login)."
        info = itlg.get_user_info(tk, cfg.get("deviceId", ""))
        if not info:
            return "❌ Token expired / API menolak."
        bal = itlg.get_balance(tk, cfg.get("deviceId", ""))
        lid = cfg.get("loginId", "?")
        return (f"✅ Token valid!\n"
                f"👤 Login ID · {lid}\n"
                f"💰 Saldo · {fmt_num(bal) if bal is not None else '?'} ITLG\n"
                f"🕐 {fmt_wib()} WIB")
    except Exception as e:
        return f"⚠️ Gagal verifikasi: {e}"


def _do_login(method):
    """Jalankan login OTP/face (single account). Runs in thread."""
    try:
        cfg = load_config()
        if method == "otp":
            # Paksa hapus token dulu biar OTP flow jalan
            for tf in ("token.json", "token-backup.json"):
                p = SCRIPT_DIR / tf
                if p.exists():
                    p.unlink()
            if not cfg.get("email") or not cfg.get("imapPassword"):
                return "❌ OTP butuh email + IMAP pass di config.\nAtur dulu via menu ⚙️ Config."
            access, _ = itlg.do_login(cfg)
            if access:
                return "✅ OTP login berhasil!"
            return "❌ OTP login gagal. Cek log."
        elif method == "face":
            if not cfg.get("facePhoto") or not os.path.exists(cfg.get("facePhoto", "")):
                return "❌ Face login butuh foto di config (facePhoto).\nAtur dulu via menu ⚙️ Config."
            access, _ = itlg.do_face_login(cfg)
            if access:
                return "✅ Face login berhasil!"
            return "❌ Face login gagal. Cek log."
        return "❌ Metode tidak dikenal."
    except Exception as e:
        return f"⚠️ Login error: {e}"


async def _with_busy(q, chat_id, busy_key, working_text, fn):
    """Run fn() in a thread with busy-guard. Edit q's message with result."""
    if chat_id in _busy:
        await edit_cq_or_send(q, "⏳ Masih ada proses jalan. Tunggu selesai.", kb_back())
        return
    _busy.add(chat_id)
    try:
        await edit_cq_or_send(q, working_text, kb_back())
        result = await asyncio.to_thread(fn)
        await edit_cq_or_send(q, result, kb_back())
    finally:
        _busy.discard(chat_id)


# ─── Daemon control (systemd system-level) ───────────────────────────────────

def _daemon_stop():
    r = subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME],
                       capture_output=True, text=True, timeout=60)
    return f"🛑 Bot daemon dihentikan" if r.returncode == 0 else f"⚠️ Gagal stop: {r.stderr.strip()[:80]}"


def _daemon_start():
    r = subprocess.run(["sudo", "systemctl", "start", SERVICE_NAME],
                       capture_output=True, text=True, timeout=60)
    return f"▶️ Bot daemon dimulai" if r.returncode == 0 else f"⚠️ Gagal start: {r.stderr.strip()[:80]}"


def _daemon_restart():
    r = subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME],
                       capture_output=True, text=True, timeout=90)
    return f"🔄 Bot daemon di-restart" if r.returncode == 0 else f"⚠️ Gagal restart: {r.stderr.strip()[:80]}"


# ─── Handlers ────────────────────────────────────────────────────────────────

async def gate_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner gate — runs FIRST (group=-1). Non-owner: reject + stop."""
    if update.effective_user and not is_owner(update.effective_user.id):
        try:
            if update.callback_query:
                await update.callback_query.answer("Khusus owner 🙅", show_alert=False)
            elif update.effective_message and is_dm(update):
                await update.effective_message.reply_text("🔒 Private Bot\nBot ini cuma buat admin.")
        except Exception:
            pass
        raise ApplicationHandlerStop
    return None


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_dm(update):
        return
    chat_id = update.effective_chat.id
    try:
        await safe_hapus(ctx.bot, chat_id, update.effective_message.message_id)
    except Exception:
        pass
    d = await asyncio.to_thread(_gather_dashboard)
    await send_or_replace(ctx.bot, chat_id, text_dashboard(d), kb_main())


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_dm(update):
        return
    chat_id = update.effective_chat.id
    try:
        await safe_hapus(ctx.bot, chat_id, update.effective_message.message_id)
    except Exception:
        pass
    await send_or_replace(ctx.bot, chat_id, text_help(), kb_back())


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Auto-delete stray text + reshow main menu (all-button bot).
    Kalau lagi mode input config (CONFIG_INPUT), simpan ke file."""
    if not is_dm(update):
        return
    chat_id = update.effective_chat.id
    text = (update.effective_message.text or "").strip()
    # Mode input config aktif?
    pend = CONFIG_INPUT.get(chat_id)
    try:
        await safe_hapus(ctx.bot, chat_id, update.effective_message.message_id)
    except Exception:
        pass
    if pend and text:
        field = pend.get("field")
        del CONFIG_INPUT[chat_id]

        # Simpan field config root (single account)
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
        except Exception:
            cfg = {}
        if text.lower() == "batal":
            await send_or_replace(ctx.bot, chat_id, "🔙 Dibatalkan.", kb_cfg())
            return
        # passcode / imapPassword bisa berisi spasi — simpan mentah
        cfg[field] = text
        # Bersihkan token kalau loginId/passcode berubah (biar re-login)
        if field in ("loginId", "passcode"):
            for tf in ("token.json", "token-backup.json"):
                p = SCRIPT_DIR / tf
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        labels = {"loginId": "Login ID", "passcode": "Passcode", "email": "Email",
                  "imapPassword": "IMAP Pass", "proxy": "Proxy", "facePhoto": "Face Photo"}
        await send_or_replace(ctx.bot, chat_id,
            f"✅ {labels.get(field, field)} disimpan.", kb_cfg())
        return

    d = await asyncio.to_thread(_gather_dashboard)
    await send_or_replace(ctx.bot, chat_id, text_dashboard(d), kb_main())


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    chat_id = q.message.chat.id
    bot = q.get_bot()

    if not is_owner(uid):
        await q.answer("Khusus owner 🙅")
        return

    # Main dashboard
    if data == "main":
        await q.answer()
        d = await asyncio.to_thread(_gather_dashboard)
        await edit_cq_or_send(q, text_dashboard(d), kb_main())
        return

    # Balance
    if data == "bal":
        await q.answer()
        d = await asyncio.to_thread(_gather_dashboard)
        await edit_cq_or_send(q, text_balance(d), kb_back())
        return

    # Group view
    if data == "grp":
        await q.answer()
        d = await asyncio.to_thread(_gather_dashboard)
        claimable = bool(d.get("g", {}).get("isClaimable")) and not d.get("g", {}).get("requesterHasClaimedToday")
        await edit_cq_or_send(q, text_group(d), kb_grp(claimable))
        return

    # Recovery view
    if data == "rec":
        await q.answer()
        d = await asyncio.to_thread(_gather_dashboard)
        can = bool(d.get("can_rec")) and d.get("tot_rec", 0) > 0
        await edit_cq_or_send(q, text_recovery(d), kb_rec(can))
        return

    # Manage view
    if data == "mgmt":
        await q.answer()
        d = await asyncio.to_thread(_gather_dashboard)
        await edit_cq_or_send(q, text_mgmt(d), kb_mgmt(bool(d.get("pid"))))
        return

    # ─── Config (single account) ───
    # Menu config
    if data == "cfg":
        await q.answer()
        await edit_cq_or_send(q, text_cfg(), kb_cfg())
        return

    # Minta input field config
    if data.startswith("cfgin:"):
        await q.answer()
        field = data.split(":", 1)[1]
        CONFIG_INPUT[chat_id] = {"field": field}
        labels = {"loginId": "Login ID", "passcode": "Passcode", "email": "Email",
                  "imapPassword": "IMAP Pass", "proxy": "Proxy (http://user:pass@host:port)",
                  "facePhoto": "Path foto selfie"}
        lbl = labels.get(field, field)
        await edit_cq_or_send(q, f"⚙️ Atur {lbl}\n━━━━━━━━━━━\nKetik nilai baru:\n\n🔙 / batal (ketik 'batal')", kb_cfg())
        return

    # Verifikasi token
    if data == "verify":
        await q.answer()
        await edit_cq_or_send(q, "💾 Verifikasi token…", kb_cfg())
        res = await asyncio.to_thread(_verify_now)
        await edit_cq_or_send(q, res, kb_cfg())
        return

    # Pilih jalur login
    if data == "login":
        await q.answer()
        await edit_cq_or_send(q, "🔑 Login\n━━━━━━━━━━━\nPilih jalur login:", kb_login_choice())
        return

    # OTP login
    if data == "loginotp":
        await q.answer()
        await edit_cq_or_send(q, "📱 OTP Login\nMengirim OTP ke email…", kb_cfg())
        res = await asyncio.to_thread(_do_login, "otp")
        await edit_cq_or_send(q, res, kb_cfg())
        return

    # Face login
    if data == "loginface":
        await q.answer()
        await edit_cq_or_send(q, "📸 Face Login\nVerifikasi wajah…", kb_cfg())
        res = await asyncio.to_thread(_do_login, "face")
        await edit_cq_or_send(q, res, kb_cfg())
        return

    # Help
    if data == "help":
        await q.answer()
        await edit_cq_or_send(q, text_help(), kb_back())
        return

    # Force claim (mine)
    if data == "claim":
        await q.answer()
        await _with_busy(q, chat_id, chat_id, "⛏️ Klaim mining...\nCek iklan dulu, ±1-2 menit", _run_claim)
        return

    # Force group claim
    if data == "grpdo":
        await q.answer()
        await _with_busy(q, chat_id, chat_id, "👥 Klaim group mining...\nMohon tunggu", _run_group)
        return

    # Force recovery
    if data == "recdo":
        await q.answer()
        await _with_busy(q, chat_id, chat_id, "♻️ Cek & klaim recovery...\nMohon tunggu", _run_recovery)
        return

    # Force sync
    if data == "sync":
        await q.answer()
        await _with_busy(q, chat_id, chat_id, "🔄 Sinkronisasi...\nAmbil status antrian terbaru", _run_sync)
        return

    # Stop confirm
    if data == "stop":
        await q.answer()
        await edit_cq_or_send(q, "🛑 Yakin mau stop bot daemon?", kb_stop_confirm())
        return

    # Stop go
    if data == "stopgo":
        await q.answer()
        await edit_cq_or_send(q, "🛑 Menghentikan daemon...", kb_back())
        result = await asyncio.to_thread(_daemon_stop)
        await asyncio.sleep(3)
        await edit_cq_or_send(q, result, kb_back())
        return

    # Restart
    if data == "restart":
        await q.answer()
        await edit_cq_or_send(q, "🔄 Restart daemon...", kb_back())
        result = await asyncio.to_thread(_daemon_restart)
        await asyncio.sleep(4)
        await edit_cq_or_send(q, result, kb_back())
        return

    # Start (when stopped)
    if data == "start":
        await q.answer()
        await edit_cq_or_send(q, "▶️ Menjalankan daemon...", kb_back())
        result = await asyncio.to_thread(_daemon_start)
        await asyncio.sleep(4)
        await edit_cq_or_send(q, result, kb_back())
        return

    # Unknown callback
    await q.answer("❌ Aksi tidak dikenal")


async def global_error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    err = getattr(ctx, "error", None)
    if err is None:
        # Update-fetcher noise (e.g. manual getUpdates interference) — log only
        print("[GATEWAY] updater noise (error=None)", flush=True)
        return
    import traceback
    print(f"[GATEWAY ERROR] {type(err).__name__}: {err}", flush=True)
    traceback.print_exc()
    try:
        if update and hasattr(update, "effective_chat") and update.effective_chat:
            chat_id = update.effective_chat.id
            text = f"❌ Error: {type(err).__name__}: {err}"
            await send_or_replace(ctx.bot, chat_id, text, kb_main())
    except Exception:
        pass


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("🤖 ITLG Gateway v3 (PTB modern, all inline buttons)", flush=True)
    print("  ☕ https://saweria.co/febfrmn", flush=True)
    print("  💬 Telegram: /start buka menu · /help info lengkap", flush=True)

    cfg = load_config()
    token = cfg.get("tgBotToken")
    if not token:
        print("❌ tgBotToken not set. Jalankan: python3 setup.py", flush=True)
        sys.exit(1)

    app = Application.builder().token(token).build()

    # Owner gate — group -1, jalan duluan
    app.add_handler(TypeHandler(Update, gate_all), group=-1)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback, block=False))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(global_error_handler)

    print(f"👤 Owner: {OWNER_ID}", flush=True)
    print("Listening...", flush=True)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
