#!/bin/bash
# Glink Daemon start script
# Auto-detects pidfile, supports --serve mode

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$BASE_DIR/.glink-daemon.pid"
LOG="$BASE_DIR/glink-daemon.log"
DAEMON="$BASE_DIR/glink-daemon.py"
PROJECT="${1:-hello-world}"
MODE="${2:-}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check for existing process
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo -e "${YELLOW}⚠ Glink daemon already running (pid=$OLD_PID)${NC}"
        echo "   Restart: kill $OLD_PID && $0 $PROJECT"
        exit 0
    else
        echo -e "${YELLOW}⚠ Cleaning stale pidfile (pid=$OLD_PID)${NC}"
        rm -f "$PIDFILE"
    fi
fi

echo -e "${GREEN}🚀 Starting Glink Daemon${NC}"
echo "   Project: $PROJECT"
echo "   Log:     $LOG"
echo "   Daemon:  $DAEMON"

cd "$BASE_DIR" || exit 1

if [ "$MODE" = "--serve" ]; then
    nohup python3 "$DAEMON" "$PROJECT" --serve > "$LOG" 2>&1 &
else
    nohup python3 "$DAEMON" "$PROJECT" > "$LOG" 2>&1 &
fi

PID=$!
echo $PID > "$PIDFILE"
echo -e "${GREEN}✅ Started (pid=$PID)${NC}"
echo "   Log:    tail -f $LOG"
echo "   Stop:   kill $PID"
echo "   API:    http://127.0.0.1:8426/health"
