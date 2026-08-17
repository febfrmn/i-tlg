#!/usr/bin/env python3
"""Menjalankan daemon bot ITLG (kompatibel dengan Hermes, bypass deteksi pgrep)."""
import os, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import bot

cfg = bot.load_config()

# Tulis PID langsung
pid_file = Path(bot.SCRIPT_DIR) / ".bot.pid"
pid_file.write_text(str(os.getpid()))

def cleanup():
    if pid_file.exists():
        pid_file.unlink()

bot.log("info", f"Daemon dimulai (PID {os.getpid()})")

max_restarts = 50
restart_count = 0
while restart_count < max_restarts:
    if Path(bot.STOP_FILE).exists():
        bot.log("info", "Sinyal stop diterima. Keluar.")
        cleanup()
        break
    try:
        bot.run_loop(cfg)
    except KeyboardInterrupt:
        print("\nDihentikan.")
        cleanup()
        break
    except Exception as e:
        restart_count += 1
        bot.log("err", f"Crash #{restart_count}: {e}")
        bot.log("info", f"Auto-restart dalam 30 detik ({restart_count}/{max_restarts})")
        time.sleep(30)
        continue

if restart_count >= max_restarts:
    bot.log("err", "Batas restart tercapai.")
cleanup()
