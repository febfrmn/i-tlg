#!/usr/bin/env python3
"""
Setup bot Interlink — mengisi config.json dengan panduan interaktif.

Cara pakai: python setup.py
"""

import json, os, hashlib, getpass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
EXAMPLE     = os.path.join(SCRIPT_DIR, "config.json.example")

BOLD  = "\033[1m"
DIM   = "\033[2m"
CYAN  = "\033[36m"
GREEN = "\033[32m"
RESET = "\033[0m"

def ask(prompt, default=""):
    suffix = f" {DIM}(default: {default}){RESET}" if default else ""
    full = f"  {BOLD}{prompt}{RESET}{suffix}\n  > "
    val = input(full).strip()
    return val or default

def main():
    print(f"""
febfrmn
****   
    ***
       
       
  *    
       
     * 
 *    *
*  *   
       
       
    *  
          Setup Bot Interlink · isi config.json
          https://saweria.co/febfrmn
""")

    # Muat config yang sudah ada
    existing = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            existing = json.load(f)
        print(f"  {GREEN}Config.json ditemukan — memuat nilai yang ada.{RESET}\n")
    elif os.path.exists(EXAMPLE):
        with open(EXAMPLE) as f:
            existing = json.load(f)

    # Set fingerprint device acak kalau belum ada
    if not existing.get("deviceModel"):
        import random as _r
        devices = [
            ("Redmi Note 8 Pro", "XiaoMi"), ("Redmi Note 11", "XiaoMi"),
            ("SM-G991B", "samsung"), ("SM-A525F", "samsung"),
            ("Pixel 6", "Google"), ("Pixel 7", "Google"),
            ("CPH2247", "OPPO"), ("V2057A", "vivo"),
            ("RMX3081", "Realme"), ("M2101K6G", "POCO"),
        ]
        dev = _r.choice(devices)
        existing["deviceModel"] = dev[0]
        existing["deviceBrand"] = dev[1]

    print(f"  {BOLD}WAJIB DIISI{RESET} — tanpa ini bot tidak jalan:\n")

    loginId = ask("ID Login Interlink (angka saja, contoh: 123456 — BUKAN @username)",
                  str(existing.get("loginId", "")))

    # Untuk rahasia: tampilkan petunjuk kalau sudah ada, tapi jangan tampilkan nilainya
    passcode_default = str(existing.get("passcode", ""))
    if passcode_default:
        print(f"  {BOLD}Passcode{RESET} {DIM}(saat ini: {'*' * len(passcode_default)} — tekan Enter untuk pertahankan){RESET}")
        passcode = getpass.getpass(f"  > ") or passcode_default
    else:
        passcode = getpass.getpass(f"  {BOLD}Passcode{RESET} (6 digit dari pendaftaran)\n  > ")

    email = ask("Email Gmail terdaftar di Interlink (contoh: you@gmail.com)",
                existing.get("email", ""))

    imap_default = existing.get("imapPassword", "")
    if imap_default:
        print(f"  {BOLD}Gmail App Password{RESET} {DIM}(saat ini: {'*' * len(imap_default)} — tekan Enter untuk pertahankan){RESET}")
        print(f"  {DIM}  BUKAN password Gmail kamu! Buat di: https://myaccount.google.com/apppasswords{RESET}")
        print(f"  {DIM}  Mendukung spasi (abcd efgh ijkl mnop) atau tanpa spasi (abcdefghijklmnop){RESET}")
        imap_password = getpass.getpass(f"  > ") or imap_default
    else:
        print(f"  {BOLD}Gmail App Password{RESET} (16 karakter — BUKAN password Gmail kamu!)")
        print(f"  {DIM}  Buat di: https://myaccount.google.com/apppasswords{RESET}")
        imap_password = getpass.getpass(f"  > ")

    print(f"\n  {BOLD}OPSIONAL{RESET} — tekan Enter untuk lewati:\n")

    # Foto wajah untuk face login (alternatif OTP)
    face_photo_default = existing.get("facePhoto", "")
    face_photo = ask("Path foto wajah (selfie.jpg — alternatif login OTP)",
                     face_photo_default)
    if face_photo:
        face_photo = face_photo.strip('"').strip("'")
        if not os.path.exists(face_photo):
            print(f"  {BOLD}⚠️  File tidak ditemukan: {face_photo}{RESET}")
            print(f"  {DIM}  Face login tidak akan jalan tanpa file ini. Kamu bisa lanjut dan pakai OTP.{RESET}")

    tg_bot_token = ask("Token Bot Telegram (kosongkan untuk nonaktifkan notifikasi)",
                       existing.get("tgBotToken", ""))
    tg_chat_id = ask("ID Chat Telegram (kosongkan untuk nonaktifkan notifikasi)",
                     str(existing.get("tgChatId", "")))

    # Bangun config
    cfg = {
        "loginId": loginId,
        "passcode": passcode,
        "email": email,
        "imapPassword": imap_password,
        "facePhoto": face_photo,
        "deviceId": existing.get("deviceId", ""),
        "tgBotToken": tg_bot_token,
        "tgChatId": tg_chat_id,
    }

    # Auto-generate deviceId — acak per instalasi (BUKAN md5 dari loginId)
    # Interlink bisa diam-diam menolak OTP dari pola deviceId yang mirip bot
    if not cfg["deviceId"]:
        import secrets
        cfg["deviceId"] = secrets.token_hex(8)  # 16 karakter hex acak (format ANDROID_ID)
        print(f"\n  {GREEN}✅ Device ID dibuat otomatis: {cfg['deviceId']}{RESET}")

    # Simpan
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)

    print(f"\n  {GREEN}{BOLD}✅ Config tersimpan ke {CONFIG_FILE}{RESET}")
    print(f"  {DIM}(chmod 600 — hanya kamu yang bisa baca){RESET}\n")

    # Validasi
    missing = []
    if not loginId:    missing.append("loginId")
    if not passcode:   missing.append("passcode")
    if not email:      missing.append("email")
    if not imap_password: missing.append("imapPassword")

    if missing:
        print(f"  {BOLD}⚠️  Field wajib belum diisi: {', '.join(missing)}{RESET}")
        print(f"  Edit {CONFIG_FILE} manual atau jalankan ulang setup ini.\n")
        return 1
    else:
        print(f"  {GREEN}Semua field wajib sudah terisi!{RESET}")
        print(f"\n  {BOLD}Langkah berikutnya:{RESET}")
        print(f"  1. Jalankan: {CYAN}python setup.py{RESET}         (setup interaktif)")
        print(f"  2. Metode login:")
        print(f"     • {CYAN}python bot.py --login{RESET}       (OTP via email)")
        if face_photo:
            print(f"     • {CYAN}python bot.py --login-face{RESET} (foto selfie)")
        print(f"  3. Jalankan: {CYAN}python bot.py{RESET}           (mulai bot)")
        print(f"  4. Biarkan berjalan — auto-claim mining + group + recovery.")
        print(f"\n  {BOLD}⚠️  OTP tidak masuk?{RESET}")
        print(f"  {DIM}  • Cek folder Spam/Junk di Gmail{RESET}")
        print(f"  {DIM}  • Tunggu 1-2 menit — Interlink kadang lambat{RESET}")
        print(f"  {DIM}  • Pastikan Gmail App Password benar (bukan password Gmail kamu){RESET}")
        print(f"  {DIM}  • Kalau OTP tetap tidak datang, coba login dari app InterLink dulu,{RESET}")
        print(f"  {DIM}    lalu jalankan bot.py --login (app mendaftarkan device kamu ke Interlink){RESET}")
        print()
    return 0

if __name__ == "__main__":
    exit(main())
