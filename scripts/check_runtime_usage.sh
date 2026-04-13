#!/usr/bin/env bash
set -euo pipefail

BOT_MATCH="${TWEETICCINI_BOT_MATCH:-/tweeticcini/.venv/bin/python /home/pi/discord_projects/tweeticcini/bot.py}"
DASHBOARD_MATCH="${TWEETICCINI_DASHBOARD_MATCH:-/tweeticcini/.venv/bin/python -m uvicorn src.dashboard_api.app:app}"

find_pid() {
  local pattern="$1"
  ps ax -o pid=,args= | awk -v pattern="$pattern" 'index($0, pattern) { print $1; exit }'
}

print_process_row() {
  local label="$1"
  local pid="$2"

  if [[ -z "$pid" ]]; then
    printf '%-12s %-8s %-8s %-8s %s\n' "$label" "-" "-" "-" "not running"
    return
  fi

  ps -p "$pid" -o %cpu=,%mem=,rss=,args= | awk -v label="$label" '
    {
      cpu=$1
      mem=$2
      rss_mb=$3 / 1024
      $1=""
      $2=""
      $3=""
      sub(/^ +/, "", $0)
      printf "%-12s %-8s %-8s %-8.1f %s\n", label, cpu, mem, rss_mb, $0
    }
  '
}

bot_pid="$(find_pid "$BOT_MATCH")"
dashboard_pid="$(find_pid "$DASHBOARD_MATCH")"

echo "Tweeticcini runtime snapshot"
echo
printf '%-12s %-8s %-8s %-8s %s\n' "Process" "%CPU" "%MEM" "RSS(MB)" "Command"
print_process_row "bot" "$bot_pid"
print_process_row "dashboard" "$dashboard_pid"

echo
echo "System"
uptime
if command -v free >/dev/null 2>&1; then
  free -h
fi
