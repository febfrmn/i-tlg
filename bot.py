#!/usr/bin/env python3
"""
Interlink Labs Auto Claim v2.3 — login sekali, klaim selamanya (mining + group + recovery). Full bahasa Indonesia.

Penggunaan:
  python bot.py              # mode loop (hitung mundur live, auto klaim tiap 4 jam)
  python bot.py --once        # jalankan sekali, cek + klaim jika bisa, lalu keluar
  python bot.py --login       # paksa login ulang (kirim OTP)
  python bot.py --login-face --photo selfie.jpg  # face login with photo file

Bot auto claim ITLG Interlink Labs. Mining 4 jam, group mining, recovery otomatis.
Login sekali saja, klaim selamanya. Notif Telegram full bahasa Indonesia.

Config: config.json (jalankan `python setup.py` untuk setup interaktif)
"""

import sys, os, json, time, imaplib, email, re, hashlib, base64, argparse, random
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
import urllib3
urllib3.disable_warnings()

# ─── WIB timezone (UTC+7) ─────────────────────────────────────────────────────
WIB = timezone(timedelta(hours=7))
def now_wib():
    """Current time in WIB (Asia/Jakarta)."""
    return datetime.now(WIB)
def fmt_wib(fmt="%H:%M"):
    return datetime.now(WIB).strftime(fmt)

def fmt_int(n):
    """Format angka ribuan Indonesia (87.843) — aman untuk int/float.
    Integer → ribuan tanpa desimal; float kecil → pertahankan 4 desimal."""
    try:
        n = float(n)
        if n == int(n):
            return f"{int(n):,}".replace(",", ".")
        if abs(n) < 100:
            return f"{n:,.4f}".rstrip("0").rstrip(".")
        return f"{n:,.2f}".replace(",", ".")
    except Exception:
        return str(n)

# ─── Config ───────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_BASE   = "https://prod.interlinklabs.ai/api/v1"
APP_VER    = "6.0.1"  # sync dgn Play Store real (audit 2026-08-16)
CLAIM_INTERVAL = 4 * 60 * 60
OTP_TIMEOUT    = 180  # 3 minutes — Interlink can be slow to send OTP
OTP_POLL_DELAY = 5
LOG_FILE     = os.path.join(SCRIPT_DIR, "interlink.log")

CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
TOKEN_FILE  = os.path.join(SCRIPT_DIR, "token.json")
STATE_FILE  = os.path.join(SCRIPT_DIR, "claim_state.json")

# ─── Config (single account, root dir) ───────────────────────────────────────
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
TOKEN_FILE  = os.path.join(SCRIPT_DIR, "token.json")
STATE_FILE  = os.path.join(SCRIPT_DIR, "claim_state.json")
SYNC_STATE_FILE = os.path.join(SCRIPT_DIR, "sync_state.json")
BOT_PID_FILE = os.path.join(SCRIPT_DIR, ".bot.pid")

def _proxy_for_cfg(cfg):
    """Proxy per config: cfg['proxy'] (http/socks5://host:port) atau env ITLG_PROXY."""
    p = cfg.get("proxy") or os.environ.get("ITLG_PROXY", "")
    return p or None

def _session_for_proxy(proxy):
    """requests.Session dengan proxy (kalau ada)."""
    s = requests.Session()
    s.verify = False
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s

# ─── Colors ───────────────────────────────────────────────────────────────────
class C:
    R = "\033[0m";  B = "\033[1m"
    RED = "\033[31m"; GR = "\033[32m"
    YLW = "\033[33m"; CY = "\033[36m"
    DIM = "\033[2m"

def log(ok, msg):
    icon = {"ok":"✅","err":"❌","warn":"⚠️","info":"ℹ️","step":"➡️"}[ok]
    line = f"{icon} {msg}"
    if ok == "err":   line = f"{C.RED}{line}{C.R}"
    elif ok == "ok":  line = f"{C.GR}{line}{C.R}"
    elif ok == "warn": line = f"{C.YLW}{line}{C.R}"
    elif ok == "info": line = f"{C.DIM}{line}{C.R}"
    elif ok == "step": line = f"{C.CY}{line}{C.R}"
    print(line)
    # ─── File logging (BUG M fix) ───
    try:
        ts = now_wib().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception:
        pass

# ─── Config loader (single account root) ─────────────────────────────────────
def load_config(name=None):
    """Load config root (single account). name diabaikan (backward compat)."""
    cfg_path = CONFIG_FILE
    if not os.path.exists(cfg_path):
        log("err", f"config.json tidak ditemukan: {cfg_path}. Jalankan: python setup.py")
        sys.exit(1)
    with open(cfg_path) as f:
        cfg = json.load(f)
    if not cfg.get("deviceId"):
        import secrets
        cfg["deviceId"] = secrets.token_hex(8)
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
    if not cfg.get("deviceModel"):
        devices = [
            ("Redmi Note 8 Pro", "XiaoMi"), ("Redmi Note 11", "XiaoMi"),
            ("SM-G991B", "samsung"), ("SM-A525F", "samsung"),
            ("Pixel 6", "Google"), ("Pixel 7", "Google"),
            ("CPH2247", "OPPO"), ("V2057A", "vivo"),
            ("RMX3081", "Realme"), ("M2101K6G", "POCO"),
        ]
        dev = random.choice(devices)
        cfg["deviceModel"] = dev[0]
        cfg["deviceBrand"] = dev[1]
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
    return cfg

# ─── Token store (single account root) ────────────────────────────────────────
def _token_paths():
    """Return (token_file, backup_file) — selalu root dir."""
    return (TOKEN_FILE, os.path.join(SCRIPT_DIR, "token-backup.json"))

def save_tokens(access, refresh):
    data = {"access": access, "refresh": refresh or "", "saved_at": int(time.time())}
    tok_f, bak_f = _token_paths()
    for path in (tok_f, bak_f):
        try:
            with open(path, "w") as f:
                json.dump(data, f)
            os.chmod(path, 0o600)
        except Exception:
            pass

def load_tokens():
    tok_f, _ = _token_paths()
    try:
        with open(tok_f) as f:
            data = json.load(f)
        return data.get("access"), data.get("refresh")
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

# ─── Claim state (actual claim amounts) ───────────────────────────────────────
def save_claim_state(claimed=None, balance=None):
    state = load_claim_state()
    if claimed is not None:
        state["last_claim"] = claimed
        state["history"] = (state.get("history", []) + [claimed])[-10:]
    if balance is not None:
        state["balance"] = balance
    state["updated_at"] = int(time.time())
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        os.chmod(STATE_FILE, 0o600)
    except Exception:
        pass

def load_claim_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"history": [], "last_claim": 0, "balance": 0}

def get_actual_rate(state):
    """Compute actual per-claim and per-day from claim history."""
    history = state.get("history", [])
    if not history:
        return 0, 0
    avg = sum(history) / len(history)
    return round(avg, 1), round(avg * 6, 1)

# ─── JWT helpers ────────────────────────────────────────────────────────────────
def jwt_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None

def token_expired(token, buffer=300):
    exp = jwt_exp(token)
    if not exp:
        return True
    return time.time() >= (exp - buffer)

# ─── HTTP ─────────────────────────────────────────────────────────────────────
def headers(token=None, device_id=None, cfg=None):
    model = "M2101K6G"
    brand = "POCO"
    if cfg:
        model = cfg.get("deviceModel", model)
        brand = cfg.get("deviceBrand", brand)
    # Anti-ban human fingerprint: ONE consistent okhttp UA per device.
    # Rotating UA per request is a bot pattern (real app always sends same UA).
    ua = "okhttp/4.12.0"
    h = {
        "User-Agent": ua,
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "version": APP_VER,
        "x-platform": "android",
        "x-model": model,
        "x-brand": brand,
        "x-system-name": "Android",
        "x-bundle-id": "org.ai.interlinklabs.interlinkId",
        "x-app-version": APP_VER,
    }
    if device_id:
        h["x-unique-id"] = device_id
        h["x-device-id"] = device_id
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def safe_json(r):
    """Parse JSON response safely, return {} on failure."""
    try:
        return r.json()
    except Exception:
        return {}

def api_get(path, token, device_id, params=None, cfg=None):
    h = headers(token, device_id, cfg)
    h["x-date"] = str(int(time.time() * 1000))
    sess = _session_for_proxy(_proxy_for_cfg(cfg or {}))
    return sess.get(f"{API_BASE}{path}", params=params, headers=h, timeout=30)

def api_post(path, data, token=None, device_id=None, cfg=None):
    h = headers(token, device_id, cfg)
    h["x-date"] = str(int(time.time() * 1000))
    body = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    h["x-content-hash"] = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    sess = _session_for_proxy(_proxy_for_cfg(cfg or {}))
    return sess.post(f"{API_BASE}{path}", data=body, headers=h, timeout=30)

# Base alternatif hasil reverse-engineer APK (Hermes bundle decompile):
#   KYC_API_URL  = https://api-curator.interlinklabs.ai/api
#   PROD_API_URL = https://prod.interlinklabs.ai/api/v1  (APP_API_URL)
KYC_API_URL = "https://api-curator.interlinklabs.ai/api"
PROD_API_URL = "https://prod.interlinklabs.ai/api/v1"

def _alt_headers(token=None, device_id=None, cfg=None):
    """Header KYC/mini-app: api-public + Origin (dari bundle decompile)."""
    h = headers(token, device_id, cfg)
    h["api-public"] = "mini-app"
    h["Origin"] = "https://mini-app.interlinklabs.ai"
    h["Referer"] = "https://mini-app.interlinklabs.ai/"
    return h

def api_get_alt(base, path, token=None, device_id=None, cfg=None, params=None):
    h = _alt_headers(token, device_id, cfg)
    h["x-date"] = str(int(time.time() * 1000))
    sess = _session_for_proxy(_proxy_for_cfg(cfg or {}))
    return sess.get(f"{base}{path}", params=params, headers=h, timeout=30)

def api_post_alt(base, path, data, token=None, device_id=None, cfg=None):
    h = _alt_headers(token, device_id, cfg)
    h["x-date"] = str(int(time.time() * 1000))
    body = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    h["x-content-hash"] = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    sess = _session_for_proxy(_proxy_for_cfg(cfg or {}))
    return sess.post(f"{base}{path}", data=body, headers=h, timeout=30)

# ─── Login flow (ONE-TIME ONLY) ────────────────────────────────────────────────
def check_login_id(cfg):
    r = api_get(f"/auth/loginId-exist-check/{cfg['loginId']}", token=None,
                device_id=cfg["deviceId"], params={"deviceId": cfg["deviceId"]})
    return safe_json(r).get("statusCode") == 200

def check_passcode(cfg):
    r = api_post("/auth/check-passcode?v=2",
                 {"loginId": str(cfg["loginId"]), "passcode": str(cfg["passcode"]), "deviceId": cfg["deviceId"]},
                 device_id=cfg["deviceId"])
    d = safe_json(r)
    if d.get("statusCode") == 200:
        data = d.get("data", {})
        return data.get("email") or (data.get("verificationInfo") or [{}])[0].get("gmail")
    return None

def send_otp(cfg, email_addr):
    r = api_post("/auth/send-otp-email-verify-login",
                 {"loginId": str(cfg["loginId"]), "passcode": str(cfg["passcode"]),
                  "email": email_addr, "deviceId": cfg["deviceId"]},
                 device_id=cfg["deviceId"])
    d = safe_json(r)
    return r.status_code == 200 and d.get("statusCode") == 200

def grab_otp(cfg, email_addr, after_ts):
    """Poll IMAP for a fresh login OTP. Only accept emails sent after after_ts."""
    time.sleep(5)
    deadline = time.time() + OTP_TIMEOUT
    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(email_addr, cfg["imapPassword"])
            mail.select("inbox")
            _, msgs = mail.search(None, "ALL")
            for eid in reversed(msgs[0].split()[-10:]):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                for part in msg_data:
                    if not isinstance(part, tuple):
                        continue
                    msg = email.message_from_bytes(part[1])
                    try:
                        if parsedate_to_datetime(msg.get("Date", "")).timestamp() < after_ts - 30:
                            continue
                    except Exception:
                        pass
                    subj = str(msg.get("Subject", ""))
                    if "login" not in subj.lower() and "verification code" not in subj.lower():
                        continue
                    body = ""
                    if msg.is_multipart():
                        for p in msg.walk():
                            ct = p.get_content_type()
                            if ct == "text/plain":
                                try: body = p.get_payload(decode=True).decode(errors="ignore")
                                except: pass
                            elif ct == "text/html" and not body:
                                try: body = p.get_payload(decode=True).decode(errors="ignore")
                                except: pass
                    else:
                        try: body = msg.get_payload(decode=True).decode(errors="ignore")
                        except: pass
                    matches = re.findall(r"\b(\d{6})\b", body or "")
                    if matches:
                        mail.logout()
                        return matches[0]
            mail.logout()
        except Exception as e:
            log("warn", f"Error IMAP: {e}")
        time.sleep(OTP_POLL_DELAY)
    return None

def verify_otp(cfg, otp):
    r = api_post("/auth/check-otp-email-verify-login?v=2",
                 {"loginId": str(cfg["loginId"]), "otp": otp, "deviceId": cfg["deviceId"]},
                 device_id=cfg["deviceId"])
    d = safe_json(r)
    if d.get("statusCode") == 200:
        data = d.get("data", {})
        return data.get("accessToken"), data.get("refreshToken")
    return None, None

def do_login(cfg):
    """Full OTP login. Returns (access, refresh) or (None, None)."""
    log("step", "Cek login ID...")
    if not check_login_id(cfg):
        log("err", f"Login ID {cfg['loginId']} tidak ditemukan.")
        return None, None

    log("step", "Cek passcode...")
    found_email = check_passcode(cfg)
    if not found_email and not cfg.get("email"):
        log("err", "Passcode salah dan tidak ada email di config.")
        return None, None
    email_addr = found_email or cfg["email"]
    log("ok", f"Email akun: {email_addr}")

    if not cfg.get("imapPassword"):
        log("err", "imapPassword belum diisi di config.json")
        return None, None

    for attempt in range(3):
        send_ts = time.time()
        log("step", f"Kirim OTP percobaan {attempt+1}/3...")
        if not send_otp(cfg, email_addr):
            time.sleep(5)
            continue
        log("info", "Menunggu email OTP...")
        otp = grab_otp(cfg, email_addr, send_ts)
        if not otp:
            continue
        log("step", f"Verifikasi OTP {otp}...")
        access, refresh = verify_otp(cfg, otp)
        if access:
            log("ok", "Login berhasil!")
            save_tokens(access, refresh)
            log("info", "Token disimpan ke token.json + token-backup.json")
            return access, refresh
        log("warn", "OTP kadaluarsa, kirim ulang...")

    log("err", "Login gagal setelah 3 percobaan.")
    return None, None

# ─── Face Login (selfie photo, alternative to OTP) ───────────────────────────
def get_presigned_login(cfg):
    """Get presigned URL for face photo upload."""
    r = api_post("/s3/face/presigned-login",
                 {"loginId": str(cfg["loginId"]), "passcode": str(cfg["passcode"])},
                 device_id=cfg["deviceId"])
    return safe_json(r)

def upload_face(upload_url, face_data):
    """Upload face photo to presigned URL."""
    try:
        import urllib3
        urllib3.disable_warnings()
        r = requests.put(upload_url, data=face_data,
                        headers={"Content-Type": "image/png"}, timeout=30, verify=False)
        return r.status_code == 200
    except Exception:
        return False

def login_with_face(cfg, image_key):
    """Login using face image key."""
    r = api_post("/auth/login",
                 {"loginId": str(cfg["loginId"]),
                  "passcode": str(cfg["passcode"]),
                  "image": image_key,
                  "presignedUrlImage": image_key},
                 device_id=cfg["deviceId"])
    return safe_json(r)

def do_face_login(cfg, photo_override=None):
    """
    Full face login flow with detailed error messages.
    Returns (access_token, refresh_token) or (None, None).
    """
    lid = cfg.get("loginId", "")
    pwd = cfg.get("passcode", "")
    photo_path = photo_override or cfg.get("facePhoto", "")

    if not all([lid, pwd]):
        log("err", "loginId atau passcode belum diisi di config.")
        return None, None

    if not photo_path or not os.path.exists(photo_path):
        log("err", f"Foto wajah tidak ditemukan: {photo_path}")
        log("info", "Jalankan: python setup.py (isi facePhoto path)")
        return None, None

    # Validate photo file
    try:
        file_size = os.path.getsize(photo_path)
        if file_size < 50000:
            log("err", f"Foto terlalu kecil ({file_size} bytes). Minimal 50KB.")
            log("info", "Gunakan foto selfie jelas, minimal 300x300 pixel, format PNG/JPG.")
            return None, None
        if file_size > 5000000:
            log("err", f"Foto terlalu besar ({file_size} bytes). Maksimal 5MB.")
            return None, None
    except Exception as e:
        log("err", f"Gagal cek ukuran foto: {e}")
        return None, None

    log("step", "Verifikasi passcode...")
    check = check_passcode(cfg)
    if not check:
        log("err", "Passcode salah.")
        return None, None
    log("ok", f"User terverifikasi: {check}")

    try:
        with open(photo_path, "rb") as f:
            face_data = f.read()
        log("step", f"Foto dimuat: {photo_path} ({len(face_data)} bytes)")
    except Exception as e:
        log("err", f"Gagal baca foto: {e}")
        return None, None

    log("step", "Mendapatkan URL upload...")
    presign = get_presigned_login(cfg)
    if presign.get("statusCode") != 200:
        log("err", f"Gagal dapat presigned URL: {presign.get('message', '')}")
        return None, None

    try:
        image_data = presign["data"]["image"]
        image_key = image_data["key"]
        upload_url = image_data["uploadUrl"]
        log("ok", f"Dapat URL upload (key: {image_key[:30]}...)")
    except (KeyError, TypeError) as e:
        log("err", f"Respon presign tidak sesuai: {e}")
        return None, None

    log("step", "Upload foto wajah...")
    if not upload_face(upload_url, face_data):
        log("err", "Upload foto wajah gagal (server reject).")
        log("info", "Coba: foto lebih jelas, cahaya cukup, wajah full frame.")
        return None, None
    log("ok", "Foto wajah terupload.")

    log("step", "Verifikasi wajah + login...")
    result = login_with_face(cfg, image_key)

    data = result.get("data", {})
    token = None
    refresh_tok = None

    if isinstance(data, dict):
        token = data.get("accessToken") or data.get("token") or data.get("access_token")
        refresh_tok = data.get("refreshToken") or data.get("refresh_token")

    if not token:
        for k in ["token", "accessToken", "access_token"]:
            if k in result:
                token = result[k]
    if not refresh_tok:
        for k in ["refreshToken", "refresh_token"]:
            if k in result:
                refresh_tok = result[k]

    if token:
        log("ok", "Face login berhasil!")
        save_tokens(token, refresh_tok)
        log("info", f"Token disimpan. Refresh token: {'ADA' if refresh_tok else 'TIDAK ADA'}")
        return token, refresh_tok

    # Detailed error messages
    msg = str(result.get("message", "")).upper()
    status = result.get("statusCode")

    if "E304" in msg or "NOT MATCH" in msg or "TIDAK COCOK" in msg:
        log("err", "WAJAH TIDAK COCOK! Selfie berbeda dengan foto registrasi.")
        log("info", "Tips: Gunakan foto yang mirip dengan foto daftar (angle, cahaya, ekspresi).")
    elif "E301" in msg or "INVALID" in msg:
        log("err", "Foto tidak valid atau format salah.")
        log("info", "Gunakan PNG atau JPG, ukuran 100KB-2MB, wajah jelas.")
    elif "E302" in msg or "BLUR" in msg or "LOW QUALITY" in msg:
        log("err", "Foto terlalu blur atau kualitas rendah.")
        log("info", "Ambil foto dengan cahaya cukup, fokus tajam, tidak gerak.")
    elif "E303" in msg or "FACE NOT DETECTED" in msg:
        log("err", "Wajah tidak terdeteksi di foto.")
        log("info", "Pastikan wajah full frame, tidak tertutup masker/kacamata hitam.")
    elif status == 400:
        log("err", f"Error request (400): {result.get('message', 'bad request')}")
    elif status == 401:
        log("err", "Passcode salah atau sesi expired.")
    elif status == 429:
        log("err", "Terlalu banyak percobaan. Tunggu 5-10 menit.")
    else:
        log("err", f"Face login gagal: {result.get('message', 'unknown error')} (status: {status})")
        log("info", "Coba: foto lebih terang, angle sama dengan foto daftar, atau pakai OTP login.")

    return None, None

# ─── Refresh ──────────────────────────────────────────────────────────────────
def do_refresh(cfg, refresh_token):
    if not refresh_token:
        return None
    log("step", "Merefresh token...")
    try:
        r = api_post("/auth/token", {"refreshToken": refresh_token}, device_id=cfg["deviceId"])
        d = safe_json(r)
        if d.get("statusCode") == 200:
            data = d.get("data", {})
            new_access = data.get("accessToken") or data.get("jwtToken")
            new_refresh = data.get("refreshToken")
            if new_access:
                log("ok", "Token berhasil direfresh.")
                save_tokens(new_access, new_refresh or refresh_token)
                return new_access
    except Exception as e:
        log("warn", f"Gagal refresh: {e}")
    return None

# ─── Get session (login once, never logout) ────────────────────────────────────
def get_session(cfg, allow_login=True):
    """Get a valid access token. Order: stored → refresh → face login → OTP login."""
    access, refresh = load_tokens()
    if access and not token_expired(access):
        return access
    if refresh:
        new_access = do_refresh(cfg, refresh)
        if new_access:
            return new_access
    if not allow_login:
        log("warn", "Tidak ada token valid. Jalankan: python bot.py --login atau --login-face")
        return None
    if cfg.get("facePhoto") and os.path.exists(cfg["facePhoto"]):
        log("warn", "Token tidak valid. Mencoba face login...")
        access, refresh = do_face_login(cfg)
        if access:
            return access
        log("warn", "Face login gagal. Mencoba OTP...")
    else:
        log("warn", "Token tidak valid. Memicu login OTP...")
    access, refresh = do_login(cfg)
    return access

# ─── API helpers ──────────────────────────────────────────────────────────────
def get_user_info(token, device_id):
    r = api_get("/auth/current-user-full?include=userInfo,token,isClaimable", token, device_id)
    d = safe_json(r)
    return d.get("data") if d.get("statusCode") == 200 else None

def check_claimable(token, device_id):
    r = api_get("/token/check-is-claimable", token, device_id)
    return safe_json(r).get("data", {})

def get_balance(token, device_id):
    data = get_user_info(token, device_id)
    return data.get("token", {}).get("interlinkGoldTokenAmount", 0) if data else None

def trigger_ads(token, device_id, last_claim):
    try:
        r = api_get(f"/token/get-random-ads-mining-new?totalHhp=1&lastTimeClaim={last_claim}", token, device_id)
        d = safe_json(r)
        if d.get("statusCode") == 200:
            retry = d.get("data", {}).get("timeRetry")
            return retry if retry is not None else 10
    except Exception:
        pass
    return 10

def claim_airdrop(token, device_id):
    r = api_post("/token/claim-airdrop", {}, token=token, device_id=device_id)
    return safe_json(r)

# ─── Recovery (burn cycle recovery, check every claim cycle) ──────────────────
def check_recovery(token, device_id):
    """Check if any burned ITLG is recoverable right now. Full audit fix: use real keys + fallback to user info."""
    # Primary: /total-recoverable
    r = api_get("/recovery/total-recoverable", token, device_id)
    d = safe_json(r)
    if d.get("statusCode") == 200:
        data = d.get("data", {})
        can = data.get("canRecover", False)
        total = data.get("totalRecoverable", 0) or data.get("totalBisa dipulihkan", 0)
        if can or total > 0:
            return True, total
    # Fallback to current-user-full (more reliable for isRecoverable + itlgRecoverable)
    user = get_user_info(token, device_id)
    if user:
        ti = user.get("token", {})
        if ti.get("isRecoverable") or ti.get("itlgRecoverable", 0) > 0:
            return True, ti.get("itlgRecoverable", 0) or ti.get("itlgBisa dipulihkan", 0)
    return False, 0

def get_recoverable_burns(token, device_id):
    """Get list of burn transactions that can be recovered. Audit fix: check multiple real keys."""
    r = api_get("/recovery/my", token, device_id)
    d = safe_json(r)
    if d.get("statusCode") == 200:
        burns = d.get("data", {}).get("data", [])
        # Real API uses isRecoverable + totalRecoverable, fallback old keys
        return [b for b in burns if b.get("isRecoverable") or b.get("totalRecoverable", 0) > 0 or b.get("isBisa dipulihkan")]
    return []

def attempt_recovery(cfg, token):
    """Check + claim recovery if available. Returns (token, recovered_amount)."""
    device_id = cfg["deviceId"]
    can_recover, total = check_recovery(token, device_id)
    if not can_recover or total <= 0:
        return token, 0

    log("ok", f"Saldo recoverable tersedia! {total} ITLG bisa dipulihkan...")
    burns = get_recoverable_burns(token, device_id)
    if not burns:
        log("info", "Recovery: canRecover=true tapi tidak ada burn yang bisa dipulihkan.")
        return token, 0

    balance_before = get_balance(token, device_id)
    recovered_total = 0
    for burn in burns:
        tid = burn.get("transactionId")
        if not tid:
            continue
        log("step", f"Memulihkan burn: {tid} ({burn.get('amount', 0)} ITLG)...")
        r = api_post("/recovery/claim", {"transactionId": tid}, token=token, device_id=device_id)
        result = safe_json(r)
        status = result.get("statusCode")
        msg = result.get("message", "")
        if status == 200 or status == 201:
            amt = burn.get("amount", 0)
            recovered_total += amt
            log("ok", f"Pulih! +{amt} ITLG dari {tid}")
            time.sleep(2)
        else:
            log("warn", f"Gagal pulihkan {tid}: {msg}")

    if recovered_total > 0:
        time.sleep(2)
        balance_after = get_balance(token, device_id)
        log("ok", f"Pemulihan selesai! +{recovered_total} ITLG kembali")
        if balance_before is not None and balance_after is not None:
            log("info", f"Saldo: {balance_before} → {balance_after} ITLG")
        try:
            send_telegram_notif(cfg, {
                "claimed": recovered_total,
                "before": balance_before,
                "after": balance_after,
                "rate_per_claim": recovered_total,
                "rate_per_day": None,
                "group_rate": 0,
                "claim_type": "recovery",
            })
        except Exception:
            pass
    return token, recovered_total

# ─── Group mining (24h cycle, 1 claim = all groups) ───────────────────────────
GROUP_INTERVAL = 24 * 60 * 60  # 24 hours

def get_group_mining_list(token, device_id):
    """Get list of all groups + next claim time."""
    r = api_post("/group-mining/get-list-group-mining", {}, token=token, device_id=device_id)
    d = safe_json(r)
    return d.get("data") if d.get("statusCode") == 200 else None

def claim_group_mining(token, device_id, group_id):
    """Claim group mining for one group (claims ALL groups at once)."""
    r = api_post("/group-mining/claim-group-mining", {"groupId": group_id}, token=token, device_id=device_id)
    return safe_json(r)

def attempt_group_claim(cfg, token):
    """Check + claim group mining (24h cycle). Returns (token, claimed, next_time_ms)."""
    device_id = cfg["deviceId"]
    data = get_group_mining_list(token, device_id)
    if not data:
        log("err", "Gagal mengambil data group mining.")
        return token, False, None

    groups = data.get("groups", [])
    next_time = data.get("nextTimeClaim")
    already_claimed = data.get("requesterHasClaimedToday", False)

    claimable_group = None
    total_reward = 0
    for g in groups:
        total_reward += g.get("totalReward", 0)
        if g.get("canClaim"):
            claimable_group = g
            break

    if not claimable_group:
        if already_claimed:
            log("info", f"Group mining: sudah diklaim hari ini. {len(groups)} grup, pool: {total_reward} ITLG")
        else:
            log("info", f"Group mining: belum waktunya. {len(groups)} grup, pool: {total_reward} ITLG")
        return token, False, next_time

    gid = claimable_group["groupId"]
    log("ok", f"Group mining bisa diklaim! Grup: {gid} ({len(groups)} grup, pool: {total_reward} ITLG)")

    jitter = random.randint(30, 120)
    log("info", f"Tunggu {jitter}s (seperti manusia)...")
    time.sleep(jitter)

    balance_before = get_balance(token, device_id)
    result = claim_group_mining(token, device_id, gid)
    status = result.get("statusCode")
    msg = result.get("message", "")

    if status == 200:
        time.sleep(2)
        balance_after = get_balance(token, device_id)
        claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else None
        claimed_str = str(claimed) if claimed is not None else "?"
        log("ok", f"Group mining diklaim! +{claimed_str} ITLG")
        if balance_before is not None and balance_after is not None:
            log("info", f"Saldo: {balance_before} → {balance_after} ITLG")
        try:
            send_telegram_notif(cfg, {
                "claimed": claimed,
                "before": balance_before,
                "after": balance_after,
                "rate_per_claim": claimed or 0,
                "rate_per_day": None,
                "group_rate": total_reward,
                "claim_type": "group",
            })
        except Exception as e:
            log("warn", f"Notif Telegram gagal: {e}")
        return token, True, next_time

    if status == 400 and "ALREADY_CLAIMED" in str(msg).upper():
        log("info", "Group mining: sudah diklaim hari ini.")
        return token, False, next_time

    log("err", f"Group mining gagal ({status}): {msg}")
    return token, False, next_time

# ─── Rates ────────────────────────────────────────────────────────────────────
def get_rates(ti, state=None):
    """Extract rate info for dashboard + notifications."""
    mining   = ti.get("dailyMiningRate", 0) or 0
    group    = ti.get("groupMiningRate", 0) or 0
    ref_dir  = ti.get("directReferralsHashRate", 0) or 0
    ref_ind  = ti.get("indirectReferralsHashRate", 0) or 0
    actual_per_claim, actual_per_day = (0, 0)
    if state:
        actual_per_claim, actual_per_day = get_actual_rate(state)
    return {
        "mining": mining, "group": group,
        "ref_dir": ref_dir, "ref_ind": ref_ind,
        "actual_per_claim": actual_per_claim,
        "actual_per_day": actual_per_day,
        "has_history": actual_per_claim > 0,
    }

# ─── Dashboard ─────────────────────────────────────────────────────────────────
def show_dashboard(token, device_id):
    data = get_user_info(token, device_id)
    if not data:
        log("err", "Gagal ambil data user.")
        return None, None
    ui = data.get("userInfo", {})
    ti = data.get("token", {})
    ic = data.get("isClaimable", {})
    state = load_claim_state()
    rates = get_rates(ti, state)
    gold        = ti.get("interlinkGoldTokenAmount", 0)
    total_ref   = ti.get("totalReferral", 0)
    streak      = ti.get("burningStreak", 0)
    burned      = ti.get("burnedCycles", 0)
    recoverable = ti.get("itlgRecoverable", 0)
    has_group   = rates["group"] > 0
    W = 38
    print()
    print(f"  {C.B}╔{'═'*W}╗{C.R}")
    print(f"  {C.B}║{C.R}  {ui.get('username', 'N/A')[:30]:<34}  {C.B}║{C.R}")
    print(f"  {C.B}╠{'═'*W}╣{C.R}")
    print(f"  {C.B}║{C.R}  Saldo ITLG   {str(gold):>28}  {C.B}║{C.R}")
    print(f"  {C.B}║{C.R}  Klaim terakhir     {str(state.get('last_claim', 0)) + ' ITLG':>28}  {C.B}║{C.R}")
    if rates["has_history"]:
        print(f"  {C.B}║{C.R}  Per klaim  {str(rates['actual_per_claim']) + ' ITLG':>28}  {C.B}║{C.R}")
        print(f"  {C.B}║{C.R}  Per hari           {str(rates['actual_per_day']) + ' ITLG':>28}  {C.B}║{C.R}")
    else:
        print(f"  {C.B}║{C.R}  Per klaim  {'menunggu klaim pertama':>28}  {C.B}║{C.R}")
        print(f"  {C.B}║{C.R}  Per hari           {'menunggu klaim pertama':>28}  {C.B}║{C.R}")
    if has_group:
        print(f"  {C.B}║{C.R}  Group rate         {str(rates['group']) + '/day':>28}  {C.B}║{C.R}")
    else:
        print(f"  {C.B}║{C.R}  Group rate         {'pending aktivasi':>28}  {C.B}║{C.R}")
    print(f"  {C.B}║{C.R}  Referral           {str(round(rates['ref_dir'] + rates['ref_ind'], 2)) + f' ({total_ref} refs)':>28}  {C.B}║{C.R}")
    print(f"  {C.B}║{C.R}  Streak / Burn  {f'{streak} / {burned}':>28}  {C.B}║{C.R}")
    if recoverable and recoverable > 0:
        print(f"  {C.B}║{C.R}  Bisa dipulihkan    {str(recoverable) + ' ITLG':>28}  {C.B}║{C.R}")
    print(f"  {C.B}╚{'═'*W}╝{C.R}")
    return ic, ti

def format_countdown(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}j {m:02d}m"
    return f"{m:02d}m {s:02d}s"

# ─── Telegram notification ────────────────────────────────────────────────────
def send_telegram_notif(cfg, info):
    """Kirim notifikasi Telegram. Full Indonesia + bedakan tipe klaim."""
    bot_token = cfg.get("tgBotToken")
    chat_id = cfg.get("tgChatId")
    if not bot_token or not chat_id:
        return

    claimed = info.get("claimed")
    before = info.get("before")
    after = info.get("after")
    per_claim = info.get("rate_per_claim", 0)
    per_day = info.get("rate_per_day")
    group_rate = info.get("group_rate", 0)
    crash = info.get("crash", False)
    claim_type = info.get("claim_type", "mine")
    sync = info.get("sync", False)
    sync_ok = info.get("ok", False)
    queue_update = info.get("queue_update", False)
    now = fmt_wib("%H:%M:%S WIB")

    claimed_str = str(claimed) if claimed is not None else "?"
    before_str = str(before) if before is not None else "?"
    after_str = str(after) if after is not None else "?"

    if queue_update:
        # Notif singkat: antrian berubah (dikirim saat sync silent mendeteksi perubahan)
        lines = ["🎯 Antrian update", "━━━━━━━━━━━"]
        match = info.get("matching_status")
        if match:
            curator = info.get("curator_name")
            line = f"🏷️ Status · {match}"
            if curator:
                tm = info.get("curator_total")
                line += f" → {curator}"
                if tm is not None:
                    line += f" ({fmt_int(tm)} matches)"
            lines.append(line)
        kyc_prog = info.get("kyc_progress")
        if kyc_prog:
            kyc_status = info.get("kyc_status", "")
            lines.append(f"📋 KYC · {kyc_prog} level ({kyc_status})")
        hcs = info.get("hcs")
        if hcs is not None:
            lines.append(f"🧠 HCS · {hcs}")
        lines.append(f"🕐 {now}")
        text = "\n".join(lines)
    elif sync:
        if sync_ok:
            lines = ["✅ Sinkron ok"]
            # Antrian real dari API (kalau ada)
            saldo = info.get("saldo")
            if saldo is not None:
                lines.append(f"💰 Saldo: {int(saldo):,} ITLG".replace(",", "."))
            mnext = info.get("mine_next_ms")
            if mnext:
                remain = max(0, int((mnext - time.time() * 1000) / 1000))
                lines.append(f"⛏️ Mining: {format_countdown(remain)} lagi")
            gnext = info.get("group_next_ms")
            gstatus = info.get("group_status")
            if gnext or gstatus is not None:
                if gstatus:
                    lines.append("👥 Group: siap klaim ✅")
                elif gnext:
                    remain = max(0, int((gnext - time.time() * 1000) / 1000))
                    lines.append(f"👥 Group: {format_countdown(remain)} lagi")
            rec = info.get("rec_count")
            if rec is not None:
                lines.append(f"♻️ Recovery: {rec} siap pulih" if rec else "♻️ Recovery: tidak ada")
            hcs = info.get("hcs")
            if hcs is not None:
                hcs_line = f"🧠 HCS: {hcs}"
                hd = info.get("hcs_daily")
                hg = info.get("hcs_group")
                if hd is not None and hg is not None:
                    hcs_line += f" (daily {hd:.4f} · group {hg:.4f})"
                lines.append(hcs_line)
            # KYC / matching status asli
            match = info.get("matching_status")
            if match:
                curator = info.get("curator_name")
                line = f"🎯 Antrian: {match}"
                if curator:
                    tm = info.get("curator_total")
                    line += f" dengan {curator}"
                    if tm is not None:
                        line += f" ({fmt_int(tm)} matches)"
                lines.append(line)
            kyc_prog = info.get("kyc_progress")
            if kyc_prog:
                kyc_status = info.get("kyc_status", "")
                lines.append(f"📋 KYC: {kyc_prog} level ({kyc_status})")
            # Sync button status
            can = info.get("sync_can_click")
            if can is not None:
                if can:
                    lines.append("🔄 Sync: siap klik ✅")
                else:
                    rem = info.get("sync_remaining")
                    if rem:
                        lines.append(f"🔄 Sync: {format_countdown(rem)} lagi")
            lines.append(f"🕐 {now}")
            text = "\n".join(lines)
        else:
            text = f"⚠️ sinkron gagal\n🕐 {now}"
    elif crash:
        text = f"❌ Bot Crash!\n\nBot mengalami error dan akan restart otomatis.\n🕐 {now}\n\nCek log: python bot.py --status"
    elif claim_type == "recovery":
        text = f"✅ Pemulihan Berhasil\n\n💰 Dapat: +{claimed_str} ITLG (dari burn recovery)\n📊 Saldo: {before_str} → {after_str} ITLG\n🕐 {now}\n\nKlaim mining berikutnya dalam 4 jam."
    elif claim_type == "group":
        text = f"✅ Group Mining Berhasil\n\n💰 Dapat: +{claimed_str} ITLG\n📊 Saldo: {before_str} → {after_str} ITLG\n👥 Group reward: {group_rate} ITLG total\n🕐 {now}\n\nGroup berikutnya dalam 24 jam."
    else:
        day_line = f"\n📈 Per hari: ~{per_day} ITLG (6 klaim)" if per_day else ""
        text = f"✅ Klaim Berhasil\n\n💰 Dapat: +{claimed_str} ITLG\n📊 Saldo: {before_str} → {after_str} ITLG\n⏱️ Per klaim: {per_claim} ITLG{day_line}\n🕐 {now}\n\nKlaim berikutnya dalam 4 jam."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10, verify=False)
        if r.status_code == 200:
            log("ok", "Notif Telegram terkirim.")
        else:
            log("warn", f"Error Telegram: {r.status_code}")
    except Exception as e:
        log("warn", f"Error notif Telegram: {e}")

# ─── Hourly sync (best-effort heartbeat) ──────────────────────────────────────
# REVERSE-ENGINEERED (Hermes bundle decompile v6.0.1): tombol sinkron ASLI ada
# endpoint-nya!  GET/POST https://prod.interlinklabs.ai/api/v1/synchronize-curator
# Cooldown 12 jam (nextAvailableAt - lastTimeClick = 43.200.000 ms).
# KYC status: https://api-curator.interlinklabs.ai/api/kyc/user/review-batches
# Matching:    https://api-curator.interlinklabs.ai/api/user/detail
SYNC_STATE_FILE = os.path.join(SCRIPT_DIR, "sync_state.json")

def load_sync_state():
    try:
        with open(SYNC_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_day": None, "last_ts": 0, "last_ok": None, "next_ts": 0}

def save_sync_state(state):
    try:
        with open(SYNC_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        os.chmod(SYNC_STATE_FILE, 0o600)
    except Exception:
        pass

def next_sync_ts():
    """Next sync time: ~1 jam dari sekarang (55-65 menit, human jitter).
    User req 2026-08-16: sinkron tiap jam sekali."""
    return int(time.time()) + random.randint(55 * 60, 65 * 60)

def do_sync(cfg, token, force=False):
    """Best-effort heartbeat: ping current-user + check-is-claimable + group + recovery.
    SILENT by default — tidak kirim notif Telegram, kecuali antrian (queue) berubah
    → kirim notif update antrian singkat. force=True (manual /sync, --sync-now)
    → kirim notif lengkap ✅ sinkron ok / ⚠️ gagal."""
    device_id = cfg.get("deviceId", "")
    state = load_sync_state()
    today = now_wib().strftime("%Y-%m-%d")
    try:
        user = get_user_info(token, device_id)
        ic = check_claimable(token, device_id)
        if user is None and ic is None:
            raise RuntimeError("API unreachable")
        ok = user is not None
        state["last_day"] = today
        state["last_ts"] = int(time.time())
        state["last_ok"] = ok
        state["next_ts"] = next_sync_ts()
        save_sync_state(state)

        # Antrian (queue) real yang bisa ditampilkan: saldo, mining, group, recovery
        antrian = _gather_antrian(cfg, token, user, ic)

        # Change detection: notif antrian cuma kalau status berubah
        snap = {
            "matching_status": antrian.get("matching_status"),
            "curator_name": antrian.get("curator_name"),
            "kyc_name": antrian.get("kyc_name"),
            "kyc_progress": antrian.get("kyc_progress"),
            "kyc_status": antrian.get("kyc_status"),
        }
        prev = state.get("antrian_snap") or {}
        state["antrian_snap"] = snap
        save_sync_state(state)

        if ok:
            log("ok", f"Sinkron OK ({fmt_wib('%H:%M')} WIB)")
            if force:
                send_telegram_notif(cfg, {"sync": True, "ok": True, **antrian})
            elif prev and snap != prev:
                # Antrian berubah → notif update singkat (prev kosong = baseline, jangan notif)
                log("info", "Antrian berubah → kirim notif update")
                send_telegram_notif(cfg, {"queue_update": True, **antrian})
        else:
            log("warn", "Sinkron: API tidak balas lengkap")
            if force:
                send_telegram_notif(cfg, {"sync": True, "ok": False})
        return ok
    except Exception as e:
        log("err", f"Sinkron gagal: {e}")
        state["last_ok"] = False
        state["next_ts"] = next_sync_ts()
        save_sync_state(state)
        if force:
            send_telegram_notif(cfg, {"sync": True, "ok": False})
        return False


def _gather_antrian(cfg, token, user=None, ic=None):
    """Kumpulkan data antrian real dari API (best-effort, jangan pernah gagal total)."""
    device_id = cfg.get("deviceId", "")
    out = {}
    try:
        if user is not None:
            tok = user.get("token", {})
            out["saldo"] = tok.get("interlinkGoldTokenAmount", 0)
    except Exception:
        pass
    try:
        if ic is not None:
            out["mine_next_ms"] = ic.get("nextFrame")
    except Exception:
        pass
    try:
        g = get_group_mining_list(token, device_id) or {}
        out["group_next_ms"] = g.get("nextTimeClaim")
        out["group_status"] = g.get("isClaimable")
    except Exception:
        pass
    try:
        burns = get_recoverable_burns(token, device_id)
        out["rec_count"] = len(burns)
    except Exception:
        pass
    try:
        hcs = get_hcs(token, device_id)
        if hcs:
            out["hcs"] = hcs.get("totalHcs")
            bd = hcs.get("breakdown") or {}
            fb = bd.get("fromBalances") or {}
            out["hcs_daily"] = fb.get("hcsClaimDaily")
            out["hcs_group"] = fb.get("hcsClaimGroupMining")
    except Exception:
        pass
    # KYC / curator status (hasil reverse-engineer APK — endpoint asli!)
    try:
        r = api_get_alt(KYC_API_URL, "/kyc/user/review-batches", token, device_id, cfg)
        if r.status_code == 200:
            d = safe_json(r).get("data") or {}
            items = d.get("items") or []
            if items:
                it = items[0]
                out["kyc_name"] = it.get("name")
                out["kyc_progress"] = it.get("progress")
                out["kyc_status"] = it.get("status")
    except Exception:
        pass
    try:
        r = api_get_alt(KYC_API_URL, "/user/detail", token, device_id, cfg)
        if r.status_code == 200:
            d = safe_json(r).get("data") or {}
            out["matching_status"] = d.get("matchingStatus")
            cur = d.get("matchingCurator") or {}
            if cur:
                out["curator_name"] = cur.get("displayName")
                out["curator_total"] = cur.get("totalMatches")
    except Exception:
        pass
    try:
        r = api_get_alt(PROD_API_URL, "/synchronize-curator", token, device_id, cfg)
        if r.status_code == 200:
            d = safe_json(r).get("data") or {}
            out["sync_can_click"] = d.get("canClick")
            rem = d.get("remainingMs")
            if rem:
                out["sync_remaining"] = max(0, int(rem / 1000))
    except Exception:
        pass
    return out


def do_sync_now(cfg, token):
    """Klik tombol sinkron asli: POST /synchronize-curator (cooldown 12 jam)."""
    device_id = cfg.get("deviceId", "")
    try:
        r = api_post_alt(PROD_API_URL, "/synchronize-curator", {}, token, device_id, cfg)
        d = safe_json(r)
        if r.status_code in (200, 201) and d.get("success", True):
            data = d.get("data") or {}
            log("ok", f"Sync click queued: {data.get('queued')}")
            return {"sync_now": True, "queued": data.get("queued"), "next_ms": data.get("nextAvailableAt")}
        log("warn", f"Klik sinkron gagal: {r.status_code} {d}")
        return {"sync_now": False}
    except Exception as e:
        log("err", f"Sync click error: {e}")
        return {"sync_now": False}

def get_hcs(token, device_id):
    """Get Human Credit Score (HCS) via /hcs/get-hcs-by-loginId (auto dari token).
    Returns dict {totalHcs, breakdown} or None."""
    try:
        r = api_get("/hcs/get-hcs-by-loginId", token, device_id)
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data") or {}
        return {
            "totalHcs": data.get("totalHcs"),
            "breakdown": data.get("breakdown") or {},
        }
    except Exception as e:
        log("warn", f"HCS fetch error: {e}")
        return None


def maybe_hourly_sync(cfg, token):
    """Call once per loop iteration — cheap check, runs at most 1x/jam.
    SILENT: tidak kirim notif kecuali antrian berubah (do_sync force=False)."""
    state = load_sync_state()
    if state.get("next_ts", 0) and time.time() < state["next_ts"]:
        return  # not yet time
    log("info", "Jadwal sinkron tiba. Menjalankan sinkron (silent)...")
    do_sync(cfg, token, force=False)  # force=False → silent, cuma notif kalau antrian berubah

# ─── Claim ─────────────────────────────────────────────────────────────────────
def attempt_claim(cfg, token):
    device_id = cfg["deviceId"]
    ic = check_claimable(token, device_id)
    if not ic.get("isClaimable"):
        nf = ic.get("nextFrame")
        if nf:
            remain = int((nf - time.time() * 1000) / 1000)
            log("info", f"Belum bisa klaim. Berikutnya {format_countdown(max(0, remain))}")
        return token, False

    # Human-like delay: wait 30-120s before claiming
    jitter = random.randint(30, 120)
    log("info", f"Bisa diklaim! Tunggu {jitter}s (seperti manusia)...")
    time.sleep(jitter)

    # Re-check claimable after delay (BUG 5 fix)
    ic_after = check_claimable(token, device_id)
    if not ic_after.get("isClaimable"):
        nf = ic_after.get("nextFrame")
        if nf:
            remain = int((nf - time.time() * 1000) / 1000)
            log("info", f"Diklaim dari aplikasi saat menunggu. Berikutnya {format_countdown(max(0, remain))}")
        else:
            log("info", "Diklaim dari aplikasi saat menunggu. Lewati.")
        return token, False

    balance_before = get_balance(token, device_id)
    user = get_user_info(token, device_id)
    if not user:
        return token, False
    ti = user.get("token", {})
    last_claim = ti.get("lastClaimTime") or int(time.time() * 1000)
    group_rate = ti.get("groupMiningRate", 0) or 0

    log("ok", "Siap klaim! Memicu ads...")
    wait = trigger_ads(token, device_id, last_claim)
    time.sleep(wait + 5)

    log("step", "Mengklaim...")
    result = claim_airdrop(token, device_id)
    status = result.get("statusCode")
    msg = result.get("message", "")

    if status == 200:
        time.sleep(2)
        balance_after = get_balance(token, device_id)
        claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else None
        rates = get_rates(ti, load_claim_state())
        save_claim_state(claimed=claimed, balance=balance_after)
        claimed_str = str(claimed) if claimed is not None else "?"
        log("ok", f"Klaim berhasil! +{claimed_str} ITLG")
        log("info", f"Saldo: {balance_before} → {balance_after} ITLG")
        if rates["has_history"]:
            log("info", f"Rata-rata: {rates['actual_per_claim']} | Per hari: {rates['actual_per_day']} ITLG")
        else:
            log("info", f"Klaim pertama tercatat: {claimed} ITLG")
        try:
            send_telegram_notif(cfg, {
                "claimed": claimed,
                "before": balance_before,
                "after": balance_after,
                "rate_per_claim": rates["actual_per_claim"] if rates["has_history"] else claimed,
                "rate_per_day": rates["actual_per_day"] if rates["has_history"] else None,
                "group_rate": 0,
                "claim_type": "mine",
            })
        except Exception as e:
            log("warn", f"Notif Telegram gagal: {e}")
        show_dashboard(token, device_id)
        return token, True

    if status == 400 and "TOO_EARLY" in str(msg).upper():
        log("info", "Sudah diklaim (mungkin manual?). Sinkron timer dari API...")
        ic_new = check_claimable(token, device_id)
        nf = ic_new.get("nextFrame")
        if nf:
            remain = int((nf - time.time() * 1000) / 1000)
            log("info", f"Klaim berikutnya {format_countdown(max(0, remain))}")
        return token, False

    if status == 500:
        log("err", "Error server. Coba lagi dalam 10 detik...")
        time.sleep(10)
        result2 = claim_airdrop(token, device_id)
        if result2.get("statusCode") == 200:
            balance_after = get_balance(token, device_id)
            claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else None
            rates = get_rates(ti, load_claim_state())
            save_claim_state(claimed=claimed, balance=balance_after)
            claimed_str = str(claimed) if claimed is not None else "?"
            log("ok", f"Klaim berhasil (percobaan ulang)! +{claimed_str} ITLG")
            try:
                send_telegram_notif(cfg, {
                    "claimed": claimed,
                    "before": balance_before,
                    "after": balance_after,
                    "rate_per_claim": rates["actual_per_claim"] if rates["has_history"] else claimed,
                    "rate_per_day": rates["actual_per_day"] if rates["has_history"] else None,
                    "group_rate": 0,
                    "claim_type": "mine",
                })
            except Exception:
                pass
            show_dashboard(token, device_id)
            return token, True
        log("err", f"Percobaan ulang gagal: {result2.get('message', '')}")
        return token, False

    log("err", f"Klaim gagal ({status}): {msg}")
    return token, False

# ─── Run modes ──────────────────────────────────────────────────────────────────
def run_once(cfg):
    log("info", f"Eksekusi: {fmt_wib()}")
    token = get_session(cfg, allow_login=False)
    if not token:
        return
    maybe_hourly_sync(cfg, token)
    ic, _ = show_dashboard(token, cfg["deviceId"])
    if ic and ic.get("isClaimable"):
        attempt_claim(cfg, token)
    else:
        nf = ic.get("nextFrame") if ic else None
        if nf:
            remain = int((nf - time.time() * 1000) / 1000)
            log("info", f"Klaim berikutnya {format_countdown(max(0, remain))}")

    log("info", "Cek group mining...")
    token, group_claimed, group_next = attempt_group_claim(cfg, token)
    if group_next:
        remain = int((group_next - time.time() * 1000) / 1000)
        log("info", f"Group mining berikutnya {format_countdown(max(0, remain))}")

    log("info", "Cek recovery...")
    token, recovered = attempt_recovery(cfg, token)
    if recovered > 0:
        log("ok", f"Berhasil pulihkan {recovered} ITLG!")
    else:
        log("info", "Recovery: belum ada yang bisa dipulihkan.")


def run_loop(cfg):
    # Write PID immediately so gateway detects us
    try:
        with open(".bot.pid", "w") as pf:
            pf.write(str(os.getpid()))
        log("info", f"PID file written: {os.getpid()}")
    except Exception as e:
        log("warn", f"Could not write PID file: {e}")

    log("info", "Mode loop. Mining 4 jam + Group mining 24 jam.")
    token = get_session(cfg)
    if not token:
        log("err", "Token tidak valid. Jalankan: python bot.py --login")
        return

    # Initial check
    ic, _ = show_dashboard(token, cfg["deviceId"])
    if ic and ic.get("isClaimable"):
        token, _ = attempt_claim(cfg, token)

    token, _, group_next = attempt_group_claim(cfg, token)

    token, recovered = attempt_recovery(cfg, token)
    if recovered > 0:
        show_dashboard(token, cfg["deviceId"])

    ic = check_claimable(token, cfg["deviceId"])
    mining_next = ic.get("nextFrame") or (time.time() * 1000 + CLAIM_INTERVAL * 1000)
    if not group_next:
        group_next = time.time() * 1000 + GROUP_INTERVAL * 1000

    log("info", f"Mining berikutnya: {format_countdown((mining_next - time.time() * 1000) / 1000)}")
    log("info", f"Group berikutnya: {format_countdown((group_next - time.time() * 1000) / 1000)}")

    while True:
        if os.path.exists(STOP_FILE):
            log("info", "Sinyal stop diterima. Keluar dari loop.")
            return
        now_ms = time.time() * 1000
        mining_remain = max(0, (mining_next - now_ms) / 1000)
        group_remain = max(0, (group_next - now_ms) / 1000)

        # Hourly sync heartbeat (1x/jam, human jitter 55-65 menit)
        try:
            maybe_hourly_sync(cfg, token)
        except Exception as e:
            log("warn", f"Sinkron check error: {e}")

        if mining_remain > 0 or group_remain > 0:
            print(f"\r  {C.CY}⏰ Mining: {format_countdown(mining_remain)} | Group: {format_countdown(group_remain)}{C.R}     ", end="", flush=True)

        if mining_remain <= 0:
            print()
            log("step", "⏳ Waktu mining! Proses klaim...")
            token = get_session(cfg)
            if not token:
                log("warn", "Token habis. Tunggu 60 detik lalu coba lagi...")
                time.sleep(60)
                token = get_session(cfg)
            if token:
                token, claimed = attempt_claim(cfg, token)
                if claimed:
                    ic = check_claimable(token, cfg["deviceId"])
                    mining_next = ic.get("nextFrame") or (time.time() * 1000 + CLAIM_INTERVAL * 1000)
                    log("ok", f"Siklus klaim selesai. Mining berikutnya: {format_countdown((mining_next - time.time() * 1000) / 1000)}")
                else:
                    ic = check_claimable(token, cfg["deviceId"])
                    nf = ic.get("nextFrame")
                    if nf:
                        mining_next = nf
                        log("info", f"Belum waktunya. Berikutnya: {format_countdown((nf - time.time() * 1000) / 1000)}")
                    else:
                        mining_next = time.time() * 1000 + 300 * 1000
                        log("info", "Tidak bisa dapat timer dari API. Coba lagi 5 menit.")
            else:
                log("err", "Gagal dapat token. Coba lagi 5 menit.")
                mining_next = time.time() * 1000 + 300 * 1000

            # ALWAYS try recovery after mining timer (independent of claim success).
            # This is the root cause fix: recovery used to only run when claimed==True.
            if token:
                token, recovered = attempt_recovery(cfg, token)
                if recovered > 0:
                    log("ok", f"Auto pemulihan burn +{recovered} ITLG")

        if group_remain <= 0:
            print()
            log("step", "⏳ Waktu group mining! Proses klaim...")
            token = get_session(cfg)
            if token:
                token, claimed, group_next = attempt_group_claim(cfg, token)
                if not group_next:
                    group_next = time.time() * 1000 + GROUP_INTERVAL * 1000
            else:
                group_next = time.time() * 1000 + 300 * 1000

            # Try recovery after group cycle too
            if token:
                token, recovered = attempt_recovery(cfg, token)
                if recovered > 0:
                    log("ok", f"Auto pemulihan burn +{recovered} ITLG")

        time.sleep(10)

# ─── Cleanup old log/cache (auto, runs on bot start) ──────────────────────────
def cleanup_old_files(max_age_days=2):
    """Delete log entries older than max_age_days."""
    import glob
    now = time.time()
    cutoff = now - (max_age_days * 86400)

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
            if len(lines) > 500:
                with open(LOG_FILE, "w") as f:
                    f.writelines(lines[-500:])
        except Exception:
            pass

    for pattern in ["token-backup-*.json", "claim_state-*.json"]:
        for f in glob.glob(os.path.join(SCRIPT_DIR, pattern)):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except Exception:
                pass

    pycache = os.path.join(SCRIPT_DIR, "__pycache__")
    if os.path.isdir(pycache):
        for f in glob.glob(os.path.join(pycache, "*")):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except Exception:
                pass


# ─── Stop bot ──────────────────────────────────────────────────────────────────
STOP_FILE = os.path.join(SCRIPT_DIR, ".stop")

def stop_bot():
    """Stop the running bot gracefully using stopfile."""
    with open(STOP_FILE, "w") as f:
        f.write(str(int(time.time())))
    log("info", "Sinyal stop terkirim. Bot akan berhenti dalam 10 detik.")
    import subprocess, signal
    try:
        pids = subprocess.getoutput('pgrep -f "start_daemon.py"').strip().split("\n")
        my_pid = str(os.getpid())
        pids = [p for p in pids if p and p != my_pid and p.strip()]
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
        if pids:
            log("ok", f"Stop signal terkirim ke {len(pids)} proses.")
        else:
            log("info", "Tidak ada proses bot berjalan (tapi stopfile dibuat).")
    except Exception as e:
        log("warn", f"Gagal kirim sinyal: {e}")
    time.sleep(2)
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)


# ─── Status check (live API call for accurate timers) ─────────────────────────
def show_status():
    """Cek status live — panggil API untuk timer real, bukan log basi."""
    state = load_claim_state()
    bal = state.get("balance", 0)
    lc = state.get("last_claim", 0)
    history = state.get("history", [])
    updated = state.get("updated_at", 0)
    ago = int(time.time() - updated)
    h, m = ago // 3600, (ago % 3600) // 60
    last_claim_wib = datetime.fromtimestamp(updated, tz=WIB).strftime("%H:%M WIB") if updated > 0 else "N/A"

    import subprocess
    try:
        pid = subprocess.getoutput('pgrep -f "start_daemon.py"').strip().split("\n")[0]
        bot_status = "✅ Berjalan" if pid else "❌ Mati"
    except Exception:
        bot_status = "❓ Tidak tahu"

    cfg = load_config()
    tok_f, bak_f = _token_paths()
    if not os.path.exists(tok_f) and os.path.exists(bak_f):
        import shutil
        shutil.copy2(bak_f, tok_f)
        os.chmod(tok_f, 0o600)
    token = get_session(cfg, allow_login=False)

    mining_next_str = "N/A"
    group_next_str = "N/A"
    group_status = "N/A"
    per_claim = "N/A"
    per_day = "N/A"
    rec = "N/A"

    if token:
        device_id = cfg["deviceId"]

        try:
            ic = check_claimable(token, device_id)
            nf = ic.get("nextFrame")
            if nf:
                remain = max(0, int((nf - time.time() * 1000) / 1000))
                mining_next_str = format_countdown(remain)
            else:
                mining_next_str = "bisa klaim sekarang!"
        except Exception as e:
            mining_next_str = f"API error: {e}"

        try:
            gdata = get_group_mining_list(token, device_id)
            if gdata:
                groups = gdata.get("groups", [])
                gnext = gdata.get("nextTimeClaim")
                total_reward = sum(g.get("totalReward", 0) for g in groups)
                if gnext:
                    remain = max(0, int((gnext - time.time() * 1000) / 1000))
                    group_next_str = format_countdown(remain)
                if gdata.get("isClaimable"):
                    group_status = f"bisa klaim! ({len(groups)} grup)"
                elif gdata.get("requesterHasClaimedToday", False):
                    group_status = f"udah diklaim ({len(groups)} grup)"
                else:
                    group_status = f"pending ({len(groups)} grup)"
        except Exception:
            pass

        try:
            data = get_user_info(token, device_id)
            if data:
                ti = data.get("token", {})
                bal = ti.get("interlinkGoldTokenAmount", bal)
                rec = f"{ti.get('itlgBisa dipulihkan', 0)} ITLG"
        except Exception:
            pass
    else:
        mining_next_str = "⚠️ Token tidak ada"

    if history:
        avg = round(sum(history) / len(history), 1)
        per_claim = f"{avg} ITLG"
        per_day = f"{round(avg * 6, 1)} ITLG"

    print()
    print(f"  {C.CY}{C.B}╔══════════════════════════════════════╗{C.R}")
    print(f"  {C.CY}{C.B}║   Interlink ITLG — Status             ║{C.R}")
    print(f"  {C.CY}{C.B}╚══════════════════════════════════════╝{C.R}")
    print()
    print(f"  🤖 Bot: {bot_status}")
    print(f"  💰 Saldo: {bal} ITLG")
    print(f"  🎯 Klaim terakhir: +{lc} ITLG ({h}j {m}m lalu, {last_claim_wib})")
    if history:
        print(f"  📊 Riwayat: {' → '.join(str(x) for x in history[-5:])}")
    print(f"  📈 Rata-rata: {per_claim} | Per hari: {per_day}")
    print(f"  💎 Bisa pulih: {rec}")
    print(f"  ───────────── group ─────────────")
    print(f"  👥 Grup: {group_status}")
    print(f"  ⏳ Group berikutnya: {group_next_str}")
    print(f"  ───────────── mining ─────────────")
    print(f"  ⏳ Mining berikutnya: {mining_next_str}")
    print()

def main():
    parser = argparse.ArgumentParser(description="Interlink Labs Auto Claim")
    parser.add_argument("--once", action="store_true", help="Jalankan sekali, lalu keluar")
    parser.add_argument("--login", action="store_true", help="Paksa login ulang via OTP")
    parser.add_argument("--login-face", action="store_true", help="Login pakai foto selfie")
    parser.add_argument("--photo", type=str, default=None, help="Path foto selfie (pakai dengan --login-face)")
    parser.add_argument("--status", action="store_true", help="Cek status live (panggil API)")
    parser.add_argument("--sync-now", action="store_true", help="Klik tombol sinkron asli (POST /synchronize-curator, cooldown 12 jam)")
    parser.add_argument("--stop", action="store_true", help="Hentikan bot yang sedang berjalan")
    parser.add_argument("--restart", action="store_true", help="Stop lalu start ulang bot")
    parser.add_argument("--verify", action="store_true", help="Verifikasi token aktif (cek API)")
    args = parser.parse_args()

    print(f"""
febfrmn
****   
    ***
       
       
  *    
       
     * 
 *    *
*  *   
       
       
    *  
          Bot Auto Claim Interlink Labs · login sekali, klaim tiap 4 jam
          https://saweria.co/febfrmn
""")
    print(f"  {C.DIM}  💬 Telegram: /start buka menu · /help info lengkap{C.R}\n")

    # ─── Verifikasi token (single account) ───
    if args.verify:
        cfg = load_config()
        tk = get_session(cfg, allow_login=False)
        if not tk:
            log("err", "Token tidak valid / belum login. Jalankan: python bot.py --login atau --login-face")
            return
        ok = get_user_info(tk, cfg.get("deviceId", ""))
        if ok:
            log("ok", f"✅ Token valid. LoginId: {cfg.get('loginId')} | Saldo: {get_balance(tk, cfg.get('deviceId',''))} ITLG")
        else:
            log("err", "Token expired / API menolak. Jalankan ulang login.")
        return

    cfg = load_config()

    if args.login:
        tok_f, _ = _token_paths()
        if os.path.exists(tok_f):
            os.remove(tok_f)
        # ─── Pilih metode login ───
        has_face = cfg.get("facePhoto") and os.path.exists(cfg.get("facePhoto", ""))
        if has_face:
            print(f"\n  {C.B}Pilih metode login:{C.R}")
            print(f"  {C.CY}1{C.R}  OTP (via email)")
            print(f"  {C.CY}2{C.R}  Face Login (via selfie)")
            pilihan = input(f"\n  {C.B}> {C.R}").strip()
            if pilihan == "2":
                access, _ = do_face_login(cfg)
            else:
                access, _ = do_login(cfg)
        else:
            log("info", "Face login tidak dikonfigurasi. Gunakan OTP.")
            log("info", "Untuk face login: isi facePhoto di config.json atau pakai --login-face --photo selfie.jpg")
            access, _ = do_login(cfg)
        if access:
            log("ok", "Login selesai. Jalankan: python bot.py")
        return

    if args.login_face:
        tok_f, _ = _token_paths()
        if os.path.exists(tok_f):
            import shutil
            shutil.copy2(tok_f, tok_f + ".pre-login")
        access, _ = do_face_login(cfg, photo_override=args.photo)
        if access:
            log("ok", "Face login selesai. Jalankan: python bot.py")
            pre = tok_f + ".pre-login"
            if os.path.exists(pre):
                os.remove(pre)
        else:
            pre = tok_f + ".pre-login"
            if os.path.exists(pre):
                import shutil
                shutil.move(pre, tok_f)
                log("info", "Token sebelumnya dipulihkan (face login gagal).")
        return

    if args.status:
        show_status()
        return

    if args.sync_now:
        token = get_session(cfg, allow_login=False)
        if not token:
            log("err", "Gagal ambil token (harus login dulu).")
            return
        res = do_sync_now(cfg, token)
        if res.get("sync_now") and res.get("queued"):
            nx = res.get("next_ms")
            if nx:
                remain = max(0, int((nx - time.time() * 1000) / 1000))
                log("ok", f"Sync click queued. Cooldown: {format_countdown(remain)}")
            else:
                log("ok", "Sync click queued.")
        else:
            log("warn", "Sync click gagal / masih cooldown. Cek GET /synchronize-curator.")
        return

    if args.stop:
        stop_bot()
        return

    if args.restart:
        stop_bot()
        time.sleep(3)
        log("info", "Mulai ulang...")

    if args.once:
        run_once(cfg)
        return

    # ─── Main loop with crash-proof auto-restart ───
    cleanup_old_files(max_age_days=2)

    import subprocess
    existing = subprocess.getoutput('pgrep -f "start_daemon.py"').strip().split("\n")
    existing = [p for p in existing if p and p != str(os.getpid())]
    if existing and not args.restart:
        log("warn", "Bot sudah berjalan. Gunakan --stop dulu atau --status untuk cek.")
        return

    MAX_RESTARTS = 50
    restart_count = 0
    while restart_count < MAX_RESTARTS:
        # Write PID immediately so /status shows ✅ Berjalan
        try:
            with open(".bot.pid", "w") as pf:
                pf.write(str(os.getpid()))
        except Exception:
            pass

        if os.path.exists(STOP_FILE):
            log("info", "Sinyal stop diterima. Keluar.")
            try:
                os.remove(STOP_FILE)
            except Exception:
                pass
            break
        try:
            run_loop(cfg)
        except KeyboardInterrupt:
            print(f"\n\n  {C.DIM}Berhenti.{C.R}\n")
            break
        except Exception as e:
            restart_count += 1
            log("err", f"Crash #{restart_count}: {e}")
            log("info", f"Restart otomatis dalam 30 detik... (percobaan {restart_count}/{MAX_RESTARTS})")
            try:
                send_telegram_notif(cfg, {
                    "crash": True,
                    "claimed": 0, "before": 0, "after": 0,
                    "rate_per_claim": 0, "rate_per_day": None, "group_rate": 0,
                })
            except Exception:
                pass
            time.sleep(30)
            cleanup_old_files(max_age_days=2)
            log("step", f"Restart... (percobaan {restart_count}/{MAX_RESTARTS})")
            continue
    if restart_count >= MAX_RESTARTS:
        log("err", f"Max restart ({MAX_RESTARTS}) tercapai. Bot berhenti. Cek log.")

if __name__ == "__main__":
    main()
