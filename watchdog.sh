#!/bin/bash
# Watchdog bot ITLG — restart kalau mati, notif Telegram saat pulih
# Path otomatis dari lokasi script (bisa dijalanin dari mana aja)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_DIR="${ITLG_DIR:-$SCRIPT_DIR}"
PID_FILE="$BOT_DIR/.bot.pid"
LOG_FILE="$BOT_DIR/interlink.log"
TG_TOKEN=""
TG_CHAT="${OWNER_CHAT_ID:-0}"
BOT_NAME="${ITLG_SERVICE:-itlg-claim}"

# Selalu baca token/chat dari config.json live
if [ -f "$BOT_DIR/config.json" ]; then
  CFG_TOKEN=$(python3 -c "import json;print(json.load(open('$BOT_DIR/config.json')).get('tgBotToken',''))" 2>/dev/null || true)
  CFG_CHAT=$(python3 -c "import json;print(json.load(open('$BOT_DIR/config.json')).get('tgChatId',''))" 2>/dev/null || true)
  [ -n "$CFG_TOKEN" ] && TG_TOKEN="$CFG_TOKEN"
  [ -n "$CFG_CHAT" ] && TG_CHAT="$CFG_CHAT"
fi

if [ -z "$TG_TOKEN" ]; then
  echo "tgBotToken missing in config.json"
  exit 1
fi

cd "$BOT_DIR" || exit 1

notify() {
  local msg="$1"
  curl -s --max-time 15 -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    -d chat_id="$TG_CHAT" \
    -d text="$msg" >/dev/null 2>&1 || true
}

is_bot_alive() {
  if [ -f "$PID_FILE" ]; then
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      # Confirm it is our process tree
      if tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -Eq 'start_daemon\.py|bot\.py'; then
        return 0
      fi
    fi
  fi

  # Fallback: detect start_daemon or bare bot.py (exclude gateway/tests)
  local p
  for p in $(pgrep -f 'python3 .*(start_daemon\.py|bot\.py)' 2>/dev/null); do
    cmd=$(tr '\0' ' ' <"/proc/$p/cmdline" 2>/dev/null || true)
    case "$cmd" in
      *tg_gateway*|*test*|*demo*) continue ;;
      *start_daemon.py*|*bot.py*)
        echo "$p" >"$PID_FILE"
        return 0
        ;;
    esac
  done
  return 1
}

is_gateway_alive() {
  pgrep -f 'python3 .*tg_gateway\.py' >/dev/null 2>&1
}

BOT_WAS_DOWN=0
GW_WAS_DOWN=0

if ! is_bot_alive; then
  BOT_WAS_DOWN=1
  rm -f "$PID_FILE" "$BOT_DIR/.stop"
  nohup python3 start_daemon.py >>"$LOG_FILE" 2>&1 &
  sleep 3
fi

if ! is_gateway_alive; then
  GW_WAS_DOWN=1
  nohup python3 tg_gateway.py >>"$BOT_DIR/gateway.log" 2>&1 &
  sleep 2
fi

# Only notify when something was restarted
if [ "$BOT_WAS_DOWN" -eq 1 ] || [ "$GW_WAS_DOWN" -eq 1 ]; then
  BOT_OK=0
  GW_OK=0
  is_bot_alive && BOT_OK=1
  is_gateway_alive && GW_OK=1
  BOT_PID=$(cat "$PID_FILE" 2>/dev/null || echo '?')
  GW_PID=$(pgrep -f 'python3 .*tg_gateway\.py' | head -1)

  if [ "$BOT_OK" -eq 1 ] && [ "$GW_OK" -eq 1 ]; then
    notify "🔄 $BOT_NAME restarted
🤖 bot PID $BOT_PID
📱 gateway PID $GW_PID
🕐 $(date '+%H:%M WIB')"
    echo "restarted bot=$BOT_PID gateway=$GW_PID"
    exit 0
  fi

  notify "❌ $BOT_NAME FAILED restart
bot_ok=$BOT_OK gateway_ok=$GW_OK
🕐 $(date '+%H:%M WIB')"
  echo "failed bot_ok=$BOT_OK gateway_ok=$GW_OK"
  exit 1
fi

exit 0
