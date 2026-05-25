#!/bin/bash
# Glink Daemon healthcheck script — for cron-based monitoring
# If the daemon is down, auto-restart it
# Suggested cron: */5 * * * * /path/to/glink/bin/glink-healthcheck.sh

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$BASE_DIR/.glink-daemon.pid"
LOG="$BASE_DIR/glink-daemon.log"
DAEMON="$BASE_DIR/glink-daemon.py"
PORT="${GLINK_PORT:-8426}"

# Check if API port is alive
if lsof -ti :${PORT} > /dev/null 2>&1; then
    # Daemon is running — update pidfile if process restarted
    ACTUAL_PID=$(lsof -ti :${PORT} | head -1)
    if [ -f "$PIDFILE" ] && [ "$(cat "$PIDFILE")" != "$ACTUAL_PID" ]; then
        echo "$ACTUAL_PID" > "$PIDFILE"
        echo "$(date '+%H:%M:%S') pidfile updated: $ACTUAL_PID" >> "$BASE_DIR/.glink-healthcheck.log"
    fi
    exit 0
fi

# Port is down — need to restart
echo "$(date '+%H:%M:%S') ⚠ Daemon offline, restarting" >> "$BASE_DIR/.glink-healthcheck.log"

# Clean stale pidfile
[ -f "$PIDFILE" ] && rm -f "$PIDFILE"

# Detect last project from log
PROJECT=$(grep -oP '(?<=Project: )\S+' "$LOG" 2>/dev/null | tail -1 || true)
PROJECT="${PROJECT:-hello-world}"

# Alert via webhook
if [ -n "${GLINK_ALERT_WEBHOOK:-}" ]; then
    curl -s -m 5 -X POST -H "Content-Type: application/json" \
      -d "$(cat <<EOF
{
  "msg_type": "interactive",
  "card": {
    "header": {
      "title": {"tag": "plain_text", "content": "⚠️ Glink Daemon Offline — Auto-Restoring"},
      "template": "red"
    },
    "elements": [
      {"tag": "markdown", "content": "**Project**: $PROJECT\n**Host**: $(hostname)\n**Action**: Auto-restart daemon"},
      {"tag": "hr"},
      {"tag": "note", "elements": [{"tag": "plain_text", "content": "Glink Healthcheck | $(date '+%Y-%m-%d %H:%M:%S')"}]}
    ]
  }
}
EOF
)" "$GLINK_ALERT_WEBHOOK" >/dev/null 2>&1 || true
fi

# Start
cd "$BASE_DIR" || exit 1
nohup python3 "$DAEMON" "$PROJECT" >> "$LOG" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PIDFILE"
echo "$(date '+%H:%M:%S') ✅ Daemon restarted (pid=$NEW_PID, project=$PROJECT)" >> "$BASE_DIR/.glink-healthcheck.log"
