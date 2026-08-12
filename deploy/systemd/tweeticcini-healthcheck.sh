#!/usr/bin/env bash
set -euo pipefail

DASHBOARD_URL="${TWEETICCINI_HEALTH_URL:-http://127.0.0.1:8080/health}"
DASHBOARD_SERVICE="${TWEETICCINI_DASHBOARD_SERVICE:-tweeticcini-dashboard.service}"
BOT_SERVICE="${TWEETICCINI_BOT_SERVICE:-tweeticcini-bot.service}"
TUNNEL_SERVICE="${TWEETICCINI_TUNNEL_SERVICE:-cloudflared}"
STATE_DIR="${TWEETICCINI_HEALTH_STATE_DIR:-/tmp/tweeticcini-health}"
PUBLIC_STATUS_FILE="${TWEETICCINI_PUBLIC_STATUS_FILE:-$STATE_DIR/public-status.json}"
BOT_FAILURE_THRESHOLD="${TWEETICCINI_BOT_FAILURE_THRESHOLD:-2}"

mkdir -p "$STATE_DIR"

log() {
  logger -t tweeticcini-health "$*"
  printf '%s\n' "$*"
}

set_counter() {
  printf '%s' "$2" >"$STATE_DIR/$1"
}

get_counter() {
  if [[ -f "$STATE_DIR/$1" ]]; then
    cat "$STATE_DIR/$1"
  else
    printf '0'
  fi
}

restart_service() {
  local service_name="$1"
  log "restarting ${service_name}"
  systemctl restart "$service_name"
}

write_public_status() {
  local status="$1"
  local message="$2"
  python3 - "$PUBLIC_STATUS_FILE" "$status" "$message" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
status = sys.argv[2]
message = sys.argv[3]
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    json.dumps(
        {
            "status": status,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "tweeticcini-healthcheck",
        }
    ),
    encoding="utf8",
)
PY
}

ensure_active() {
  local service_name="$1"
  if ! systemctl is-active --quiet "$service_name"; then
    restart_service "$service_name"
  fi
}

fetch_health() {
  curl --silent --show-error --max-time 10 "$DASHBOARD_URL"
}

dashboard_payload="$(fetch_health || true)"

if [[ -z "$dashboard_payload" ]]; then
  write_public_status "offline" "Tweeticcini is temporarily unavailable while the dashboard reconnects to the host system."
  log "dashboard health probe failed; restarting ${DASHBOARD_SERVICE}"
  restart_service "$DASHBOARD_SERVICE"
  sleep 8
  dashboard_payload="$(fetch_health || true)"
  if [[ -z "$dashboard_payload" ]]; then
    write_public_status "offline" "Tweeticcini is temporarily unavailable while the public tunnel reconnects to the host system."
    log "dashboard still unhealthy after restart; restarting ${TUNNEL_SERVICE}"
    restart_service "$TUNNEL_SERVICE"
    exit 0
  fi
fi

dashboard_status="$(printf '%s' "$dashboard_payload" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('status', ''))" 2>/dev/null || true)"

if [[ -z "$dashboard_status" ]]; then
  write_public_status "degraded" "Tweeticcini health data is temporarily unavailable while the dashboard refreshes."
  log "dashboard health payload was not parseable; restarting ${DASHBOARD_SERVICE}"
  restart_service "$DASHBOARD_SERVICE"
  exit 0
fi

ensure_active "$DASHBOARD_SERVICE"
ensure_active "$TUNNEL_SERVICE"

if [[ "$dashboard_status" != "ok" ]]; then
  write_public_status "degraded" "Tweeticcini is running in a degraded state. Alerts may be delayed while services recover."
  log "dashboard health status is ${dashboard_status}; leaving dashboard up and checking runtime signals"
fi

bot_health_line="$(printf '%s' "$dashboard_payload" | python3 -c "import json,sys; data=json.load(sys.stdin); log_health=data.get('log_health', {}); session_count=int(data.get('twitter_session_count') or 0); healthy_count=int(data.get('healthy_twitter_session_count') or 0); bot_online_recently='1' if log_health.get('bot_online_recently') else '0'; dead_task_count=int(log_health.get('dead_task_warning_count_since_last_online') or 0); unhealthy='1' if ((session_count > 0 and healthy_count == 0) or bot_online_recently == '0' or dead_task_count > 0) else '0'; print('|'.join([unhealthy, str(session_count), str(healthy_count), bot_online_recently, str(dead_task_count)]))" 2>/dev/null || true)"

if [[ -z "$bot_health_line" ]]; then
  write_public_status "degraded" "Tweeticcini health data is temporarily unavailable while the bot status refreshes."
  log "unable to parse dashboard health payload for bot status; restarting ${BOT_SERVICE}"
  restart_service "$BOT_SERVICE"
  exit 0
fi

IFS='|' read -r bot_unhealthy session_count healthy_count bot_online_recently dead_task_count <<<"$bot_health_line"

if [[ "$bot_unhealthy" == "1" ]]; then
  consecutive_failures="$(( $(get_counter bot_failures) + 1 ))"
  set_counter bot_failures "$consecutive_failures"
  write_public_status "degraded" "Tweeticcini is recovering from a bot runtime issue. Alerts may be delayed until monitoring stabilizes."
  log "bot health warning ${consecutive_failures}/${BOT_FAILURE_THRESHOLD} (sessions=${session_count}, healthy=${healthy_count}, online_recently=${bot_online_recently}, dead_tasks=${dead_task_count})"
  if (( consecutive_failures >= BOT_FAILURE_THRESHOLD )); then
    restart_service "$BOT_SERVICE"
    set_counter bot_failures 0
  fi
else
  set_counter bot_failures 0
  if [[ "$dashboard_status" == "ok" ]]; then
    write_public_status "ok" "Tweeticcini is operating normally."
  fi
fi
