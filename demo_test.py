#!/usr/bin/env python3
"""
Demo Test untuk ITLG Claim Bot v2.3
Menampilkan contoh output notifikasi Telegram dan dashboard dalam format full Indonesia.

Jalankan:
  python demo_test.py
  python demo_test.py --claim-success
  python demo_test.py --recovery
  python demo_test.py --group
  python demo_test.py --dashboard
  python demo_test.py --all
"""

import argparse
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))

def fmt_wib(fmt="%H:%M:%S WIB"):
    return datetime.now(WIB).strftime(fmt)

def demo_claim_success():
    """Simulasi klaim mining berhasil (format yang user minta)"""
    print("=== DEMO: Klaim Mining Berhasil ===\n")
    
    claimed = 48
    before = 9632
    after = 9680
    per_claim = 38.3
    per_day = 229.8
    group_rate = 0.71
    now = fmt_wib()
    
    day_line = f"\n📈 Per hari: ~{per_day} ITLG (6 klaim)"
    
    text = (
        f"✅ Klaim Berhasil\n\n"
        f"💰 Dapat: +{claimed} ITLG\n"
        f"📊 Saldo: {before} → {after} ITLG\n"
        f"⏱️ Per klaim: {per_claim} ITLG{day_line}\n"
        f"🕐 {now}\n\n"
        f"Klaim berikutnya dalam 4 jam."
    )
    print(text)
    print("\n" + "="*50)

def demo_recovery():
    """Simulasi recovery berhasil"""
    print("=== DEMO: Pemulihan (Recovery) Berhasil ===\n")
    
    claimed = 696
    before = 9680
    after = 10376
    now = fmt_wib()
    
    text = (
        f"✅ Pemulihan Berhasil\n\n"
        f"💰 Dapat: +{claimed} ITLG (dari burn recovery)\n"
        f"📊 Saldo: {before} → {after} ITLG\n"
        f"🕐 {now}\n\n"
        f"Klaim mining berikutnya dalam 4 jam."
    )
    print(text)
    print("\n" + "="*50)

def demo_group():
    """Simulasi group mining berhasil"""
    print("=== DEMO: Group Mining Berhasil ===\n")
    
    claimed = 120
    before = 10376
    after = 10496
    group_rate = 0.71
    now = fmt_wib()
    
    text = (
        f"✅ Group Mining Berhasil\n\n"
        f"💰 Dapat: +{claimed} ITLG\n"
        f"📊 Saldo: {before} → {after} ITLG\n"
        f"👥 Group reward: {group_rate} ITLG total\n"
        f"🕐 {now}\n\n"
        f"Group berikutnya dalam 24 jam."
    )
    print(text)
    print("\n" + "="*50)

def demo_dashboard():
    """Simulasi tampilan dashboard di terminal"""
    print("=== DEMO: Dashboard (seperti di /status) ===\n")
    print("""
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
    
    print("  💰 Saldo ITLG          10376")
    print("  📊 Klaim terakhir       696 ITLG")
    print("  ⏱️ Per klaim           38.3 ITLG")
    print("  📈 Per hari            229.8 ITLG")
    print("  👥 Group rate          0.71/hari (aktif!)")
    print("  👥 Referral            4.5 (21 refs)")
    print("  🔥 Streak / Burn       12 / 511")
    print("  💎 Bisa dipulihkan     0 ITLG")
    print()
    print("  ⏳ Mining berikutnya: 03h 42m 15s")
    print("  ⏳ Group berikutnya:  19h 11m 00s")
    print()

def main():
    parser = argparse.ArgumentParser(description="Demo Test ITLG Claim Bot v2.3")
    parser.add_argument("--claim-success", action="store_true", help="Tampilkan contoh klaim berhasil")
    parser.add_argument("--recovery", action="store_true", help="Tampilkan contoh recovery")
    parser.add_argument("--group", action="store_true", help="Tampilkan contoh group claim")
    parser.add_argument("--dashboard", action="store_true", help="Tampilkan contoh dashboard")
    parser.add_argument("--all", action="store_true", help="Tampilkan semua demo")
    
    args = parser.parse_args()
    
    if args.all or not any([args.claim_success, args.recovery, args.group, args.dashboard]):
        demo_claim_success()
        demo_recovery()
        demo_group()
        demo_dashboard()
    else:
        if args.claim_success:
            demo_claim_success()
        if args.recovery:
            demo_recovery()
        if args.group:
            demo_group()
        if args.dashboard:
            demo_dashboard()

if __name__ == "__main__":
    main()
