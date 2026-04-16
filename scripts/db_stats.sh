#!/usr/bin/env bash
set -euo pipefail

DEFAULT_DB_PATH="/home/pi/discord_projects/tweeticcini/data/tracked_accounts.db"
DB_PATH="${TWEETICCINI_DB:-$DEFAULT_DB_PATH}"

if [[ "${1:-}" == *.db ]]; then
  DB_PATH="$1"
  shift || true
fi

query() {
  sqlite3 "$DB_PATH" ".headers on" ".mode column" "$1"
}

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [db_path] <command>

Commands:
  summary       Show a quick overview
  monitors      Count all monitors
  roles         Count monitors with role mentions
  post          Count monitors with non-default post filters
  media         Count monitors with non-default media filters
  rules         Show enabled rule counts by server
  sessions      List configured Twitter sessions
  role-list     List monitors that have role mentions
  post-list     List monitors that use non-default post filters
  media-list    List monitors that use non-default media filters
  sql "<query>" Run a custom SQL query

Environment:
  TWEETICCINI_DB  Override the default DB path
EOF
}

cmd="${1:-summary}"
if [[ $# -gt 0 ]]; then
  shift || true
fi

if [[ "$cmd" == "help" || "$cmd" == "-h" || "$cmd" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "Database not found: $DB_PATH" >&2
  exit 1
fi

case "$cmd" in
  summary)
    sqlite3 "$DB_PATH" ".headers on" ".mode column" "
      select count(*) as total_monitors from notification;
      select count(*) as monitors_with_role from notification where role_id is not null and trim(role_id) != '';
      select count(*) as monitors_with_nondefault_post_filter from notification where enable_type is not null and trim(enable_type) != '' and enable_type != '11';
      select count(*) as monitors_with_nondefault_media_filter from notification where enable_media_type is not null and trim(enable_media_type) != '' and enable_media_type != '11';
      select count(distinct server_id) as active_servers from channel;
      select count(*) as active_sessions from server_twitter_session where is_active = 1 and status = 'active';
    "
    ;;
  monitors)
    query "select count(*) as total_monitors from notification;"
    ;;
  roles)
    query "select count(*) as monitors_with_role from notification where role_id is not null and trim(role_id) != '';"
    ;;
  post)
    query "select count(*) as monitors_with_nondefault_post_filter from notification where enable_type is not null and trim(enable_type) != '' and enable_type != '11';"
    ;;
  media)
    query "select count(*) as monitors_with_nondefault_media_filter from notification where enable_media_type is not null and trim(enable_media_type) != '' and enable_media_type != '11';"
    ;;
  rules)
    query "select server_id, count(*) as enabled_rule_count from alert_rule where enabled = 1 group by server_id order by enabled_rule_count desc, server_id;"
    ;;
  sessions)
    query "select server_id, session_name, client_key, status, is_active from server_twitter_session order by server_id, session_name;"
    ;;
  role-list)
    query "select c.server_id, u.username, n.role_id from notification n join channel c on c.id = n.channel_id join user u on u.id = n.user_id where n.role_id is not null and trim(n.role_id) != '' order by c.server_id, u.username;"
    ;;
  post-list)
    query "select c.server_id, u.username, n.enable_type from notification n join channel c on c.id = n.channel_id join user u on u.id = n.user_id where n.enable_type is not null and trim(n.enable_type) != '' and n.enable_type != '11' order by c.server_id, u.username;"
    ;;
  media-list)
    query "select c.server_id, u.username, n.enable_media_type from notification n join channel c on c.id = n.channel_id join user u on u.id = n.user_id where n.enable_media_type is not null and trim(n.enable_media_type) != '' and n.enable_media_type != '11' order by c.server_id, u.username;"
    ;;
  sql)
    if [[ "${1:-}" == "" ]]; then
      echo "Missing SQL query." >&2
      usage >&2
      exit 1
    fi
    query "$1"
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
