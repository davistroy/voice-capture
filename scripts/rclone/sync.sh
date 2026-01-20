#!/bin/bash
# =============================================================================
# rclone Sync Script for Voice Capture Pipeline
# =============================================================================
#
# This script syncs files from Google Drive to the local inbox.
# It's designed to run in a loop inside the Docker container.
#
# Usage (standalone):
#   ./sync.sh [interval_seconds]
#
# Environment Variables:
#   RCLONE_SYNC_INTERVAL - Sync interval in seconds (default: 180)
#
# =============================================================================

set -e

# Configuration
REMOTE="gdrive:/VoiceCaptures/inbox"
LOCAL="/data/inbox"
LOG_FILE="/data/logs/rclone.log"
INTERVAL="${RCLONE_SYNC_INTERVAL:-180}"

# Override interval from argument if provided
if [ -n "$1" ]; then
    INTERVAL="$1"
fi

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

echo "=============================================="
echo "Voice Capture - rclone Sync"
echo "=============================================="
echo "Remote:   $REMOTE"
echo "Local:    $LOCAL"
echo "Interval: ${INTERVAL}s"
echo "Log:      $LOG_FILE"
echo "=============================================="
echo ""

# Single sync function
sync_once() {
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo "[$timestamp] Starting sync..."

    if rclone sync "$REMOTE" "$LOCAL" \
        --checksum \
        --verbose \
        --log-file="$LOG_FILE" \
        --log-level=INFO; then
        echo "[$timestamp] Sync completed successfully"
        return 0
    else
        local exit_code=$?
        echo "[$timestamp] Sync failed with exit code: $exit_code"
        return $exit_code
    fi
}

# Main loop
echo "Starting sync loop..."
while true; do
    sync_once || true  # Continue even if sync fails

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sleeping for ${INTERVAL}s..."
    sleep "$INTERVAL"
done
