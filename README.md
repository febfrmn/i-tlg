# ITLG Claim Bot v2.3 — Full Indonesia

```
febfrmn
****   
    ***
       
       
  *    
       
     * 
 *    *
*  *   
       
       
    *  
          ITLG Claim Bot · auto claim mining + group + recovery
          https://saweria.co/febfrmn
```

Auto claim ITLG dari Interlink Labs. Mining 4 jam, group mining, recovery otomatis. Full bahasa Indonesia, cepat, dan bebas bug.

Satu script Python. Login sekali pakai OTP atau selfie, lalu klaim selamanya. Notifikasi Telegram full Indonesia.

---

## Fitur Baru di v2.3

- **Sanitasi untuk publik** — semua nilai sensitif (owner ID, chat ID, path server, nama service) jadi placeholder/env var, aman di-push ke GitHub
- Path script otomatis (`$(dirname "$0")`) — bisa dijalanin dari folder mana aja
- Semua dokumentasi + pesan full bahasa Indonesia

### Fitur Baru di v2.2

- Full bahasa Indonesia di semua notifikasi Telegram dan log
- **Fixed**: Mining claim notif tidak lagi menampilkan "👥 Group: 0.71/hari" dari API groupMiningRate (misleading). Hanya real per-claim + per-hari dari history.
- **Fixed**: Group claim notif sekarang menampilkan "Group reward: XXX ITLG total" (actual amount), bukan rate.
- Gateway lebih robust: pakai `requests` + long polling + exponential backoff + auto-reconnect (tahan timeout di VPS Oracle)
- Penambahan `demo_test.py` untuk verifikasi output notif
- Perbaikan lag & bug pesan
- Header bot dan gateway full Indonesia
- Lebih cepat dan stabil

## Panduan Cepat

```bash
git clone https://github.com/febfrmn/i-tlg.git
cd i-tlg
pip install requests
python setup.py
```

`setup.py` akan menanyakan semua yang dibutuhkan dan menyimpannya ke `config.json`.

### Yang dibutuhkan sebelum setup

| Field | Apa itu | Contoh | Cara dapat |
|---|---|---|---|
| **loginId** | ID Interlink kamu — **angka**, bukan email | `8002` | Buka app Interlink → Profil |
| **passcode** | Passcode 6 digit (angka saja) | `204008` | Kamu pilih saat daftar |
| **email** | Alamat Gmail terdaftar di akun kamu | `you@gmail.com` | Email yang dipakai saat daftar |
| **imapPassword** | Gmail App Password — 16 huruf | `abcd efgh ijkl mnop` | [Buat di sini](https://myaccount.google.com/apppasswords) |
| **tgBotToken** | Token bot Telegram (opsional) | `123456:ABC-DEF...` | Buat via [@BotFather](https://t.me/BotFather) |
| **tgChatId** | ID Telegram kamu (opsional) | `123456789` | Chat [@userinfobot](https://t.me/userinfobot) |

## Perintah

```
python bot.py               # Jalankan (auto-restart kalau crash)
python bot.py --status      # Status live (panggil API, timer akurat)
python bot.py --stop        # Hentikan bot
python bot.py --restart     # Stop + start fresh
python bot.py --once        # Jalan sekali
python bot.py --login       # Login ulang paksa OTP (email)
python bot.py --login-face  # Login pakai foto selfie
```

## Metode Login

### Metode 1: OTP (email)

```bash
python setup.py          # isi loginId, passcode, email, imapPassword
python bot.py --login    # kirim OTP ke email, masukkan kode
```

### Metode 2: Selfie / Foto Wajah

```bash
python setup.py              # isi loginId, passcode + path foto selfie
python bot.py --login-face   # upload foto → verifikasi wajah → login
```

Foto wajah: selfie yang jelas, pencahayaan bagus, wajah terlihat penuh. Format: JPG/PNG.

### Fitur Login

| Fitur | Detail |
|---|---|
| Face Login | `--login-face` — login pakai selfie, tanpa OTP |
| Auto face fallback | Token expired → coba face login dulu sebelum OTP |
| Dual login | OTP + Selfie, bisa pakai salah satu |

### Fitur v2.0 (perbandingan)

| Fitur | v1 | v2 |
|---|---|---|
| Mining claim (4 jam) | Auto + delay | Auto + delay + re-fetch timer saat gagal |
| Group mining (24 jam) | Manual | Auto + delay manusia 30-120 detik |
| Recovery | Manual | Auto tiap siklus + claim |
| Timer status | Parse log basi | API live (sama dengan APK) |
| Crash | Mati | Auto-restart 50x, delay 30 detik |
| Notif Telegram | Claim saja | Claim + alert crash |
| Stop | Kill manual | `--stop` graceful |
| Log | Buncit | Auto-trim 500 baris + bersihkan 2 hari |
| Double-run | Bisa | Terproteksi |
| PID | Ditampilkan | Disembunyikan (aman untuk grup) |

## Auto Claim (sepenuhnya otomatis)

| Fitur | Interval | Status |
|---|---|---|
| Mining claim | 4 jam | ✅ Auto + delay manusia 10-60 detik |
| Group mining | 24 jam | ✅ Auto + delay manusia 30-120 detik |
| Recovery | Tiap siklus | ✅ Auto-cek + claim |
| Token refresh | Auto | ✅ JWT auto-refresh |

## Tampilan Status

```
  ╔══════════════════════════════════════╗
  ║   Interlink ITLG — Status             ║
  ╚══════════════════════════════════════╝

  🤖 Bot: ✅ Running
  💰 Balance: 8087 ITLG
  🎯 Last claim: +41 ITLG (0h 2m ago, 15:02 WIB)
  📊 History: 17 → 17 → 17 → 41 → 41
  📈 Per claim: 25.0 ITLG | Per day: 150.0 ITLG
  👥 Refs: 4.5 (21 refs)
  🔥 Streak/Burned: 0 / 511
  💎 Recoverable: 10241 ITLG
  ─────────────────────────────
  👥 Group: claimed today (5 groups, pool: 432)
  ⏳ Group next: 16h 55m 44s
  ⏳ Mining next: 03h 55m 44s
```

Semua nilai **live dari API** — timer sama persis dengan APK kamu.

## Cara Kerja

1. Pertama kali: kirim OTP ke Gmail, IMAP ambil, verifikasi, simpan token
2. Bot baca `nextFrame` dari API — tau persis kapan bisa claim lagi
3. Mining claim tiap 4 jam, group mining tiap 24 jam, recovery tiap siklus — semua otomatis
4. Notifikasi Telegram di setiap claim + alert crash
5. Token tidak pernah logout. Auto-refresh kalau expired. Auto-restart kalau crash.
6. Log auto-cleanup: trim ke 500 baris terakhir, hapus file lebih dari 2 hari

## Anti-Deteksi

- **Random device fingerprint** — tiap akun dapat model HP random (Samsung, Xiaomi, Pixel, OPPO, dll)
- **Timing mirip manusia** — tunggu 10-120 detik setelah window claim terbuka sebelum claim
- **Tidak polling terus-menerus** — cek tiap 10 detik, bukan tiap 1 detik
- **Endpoint sama dengan app** — pakai endpoint dan header API yang sama persis dengan app Android Interlink resmi

## Backup Token

Setelah login pertama, token disimpan ke `token.json` + `token-backup.json` (chmod 600).

```bash
# Backup manual
cp token.json ~/token-backup.json

# Restore
cp ~/token-backup.json token.json
chmod 600 token.json
```

## File

```
setup.py              # setup interaktif
bot.py                # bot utama (v2.3)
config.json           # config kamu (gitignored)
token.json            # token tersimpan (gitignored)
claim_state.json      # riwayat claim (gitignored)
```

## OTP Tidak Masuk?

1. **Cek Spam/Junk** — Gmail kadang ngarahin email Interlink ke Spam
2. **Tunggu 1-2 menit** — Interlink kadang lambat
3. **Verifikasi Gmail App Password** — harus App Password 16 huruf, bukan password Gmail biasa
4. **Login dari app dulu** — buka app InterLink, login sekali, baru jalankan `bot.py --login`
5. **Cek akses IMAP** — Pengaturan Gmail → Forwarding dan POP/IMAP → Aktifkan IMAP

## Lisensi

FEB-FRMN Source-Available — non-commercial / no-resale. Credit ke [@febfrmn](https://github.com/febfrmn).

---

## ☕ Dukungan

[![Saweria](https://img.shields.io/badge/Saweria-ffb13b?style=for-the-badge&logo=ko-fi&logoColor=white)](https://saweria.co/febfrmn)

## Demo Test (baru di v2.2)

Gunakan `demo_test.py` untuk melihat contoh output notifikasi Telegram tanpa perlu menjalankan bot:

```bash
python demo_test.py                    # tampilkan semua contoh
python demo_test.py --claim-success    # contoh klaim mining berhasil (format utama)
python demo_test.py --recovery         # contoh recovery
python demo_test.py --group            # contoh group mining
python demo_test.py --dashboard        # contoh tampilan /status
```

Ini sangat berguna untuk:
- Verifikasi format pesan sebelum release
- Testing notifikasi Telegram
- Menunjukkan ke user seperti apa outputnya
