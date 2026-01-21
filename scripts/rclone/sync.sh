#!/bin/bash
# =============================================================================
# rclone Sync Script for Voice Capture Pipeline
# =============================================================================
#
# This script syncs files from Google Drive to the local inbox.
# It can run as a continuous loop (for Docker) or single execution (for testing).
#
# Usage:
#   ./sync.sh                   # Continuous sync loop (default: 180s interval)
#   ./sync.sh --once            # Single sync, then exit
#   ./sync.sh --interval 60     # Continuous sync with 60s interval
#   ./sync.sh --dry-run         # Preview what would be synced (no changes)
#   ./sync.sh --delete-after    # Delete remote files after successful sync
#   ./sync.sh --help            # Show this help
#
# Environment Variables:
#   RCLONE_SYNC_INTERVAL   - Sync interval in seconds (default: 180)
#   RCLONE_REMOTE          - Remote path (default: gdrive:/VoiceCaptures/inbox)
#   RCLONE_LOCAL           - Local path (default: /data/inbox or ./inbox)
#   RCLONE_LOG_FILE        - Log file path (default: /data/logs/rclone.log)
#   RCLONE_CONFIG          - Path to rclone.conf (default: auto-detected)
#
# Exit Codes:
#   0  - Success
#   1  - Configuration error
#   2  - Sync error (in --once mode)
#
# =============================================================================

set -e

# Script directory for relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Determine if running in Docker (paths differ)
if [ -d "/data/inbox" ]; then
    # Docker container paths
    DEFAULT_LOCAL="/data/inbox"
    DEFAULT_LOG="/data/logs/rclone.log"
else
    # Local development paths
    DEFAULT_LOCAL="$PROJECT_ROOT/inbox"
    DEFAULT_LOG="$PROJECT_ROOT/logs/rclone.log"
fi

# Configuration with environment variable overrides
REMOTE="${RCLONE_REMOTE:-gdrive:/VoiceCaptures/inbox}"
LOCAL="${RCLONE_LOCAL:-$DEFAULT_LOCAL}"
LOG_FILE="${RCLONE_LOG_FILE:-$DEFAULT_LOG}"
INTERVAL="${RCLONE_SYNC_INTERVAL:-180}"

# Command-line options
RUN_ONCE=false
DRY_RUN=false
DELETE_AFTER=false
VERBOSE=true

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --once|-1)
            RUN_ONCE=true
            shift
            ;;
        --interval|-i)
            INTERVAL="$2"
            shift 2
            ;;
        --dry-run|-n)
            DRY_RUN=true
            shift
            ;;
        --delete-after)
            DELETE_AFTER=true
            shift
            ;;
        --quiet|-q)
            VERBOSE=false
            shift
            ;;
        --help|-h)
            head -30 "$0" | tail -25
            exit 0
            ;;
        *)
            # Support legacy positional argument for interval
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                INTERVAL="$1"
            else
                echo "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
            fi
            shift
            ;;
    esac
done

# Ensure directories exist
mkdir -p "$LOCAL"
mkdir -p "$(dirname "$LOG_FILE")"

# Check rclone is available
if ! command -v rclone &> /dev/null; then
    echo "ERROR: rclone not found"
    exit 1
fi

# Check remote is configured
if ! rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
    echo "ERROR: 'gdrive' remote not configured"
    echo "Run: ./scripts/rclone/setup.sh"
    exit 1
fi

log() {
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    if [ "$VERBOSE" = true ]; then
        echo "[$timestamp] $1"
    fi
}

print_config() {
    echo "=============================================="
    echo "Voice Capture - rclone Sync"
    echo "=============================================="
    echo "Remote:       $REMOTE"
    echo "Local:        $LOCAL"
    echo "Log file:     $LOG_FILE"
    echo "Interval:     ${INTERVAL}s"
    echo "Mode:         $([ "$RUN_ONCE" = true ] && echo "Single run" || echo "Continuous")"
    echo "Dry run:      $DRY_RUN"
    echo "Delete after: $DELETE_AFTER"
    echo "=============================================="
    echo ""
}

# Build rclone command options
build_rclone_opts() {
    local opts="--checksum"
    opts="$opts --log-file=$LOG_FILE"
    opts="$opts --log-level=INFO"

    if [ "$VERBOSE" = true ]; then
        opts="$opts --verbose"
    fi

    if [ "$DRY_RUN" = true ]; then
        opts="$opts --dry-run"
    fi

    echo "$opts"
}

# Single sync function
sync_once() {
    local opts
    opts=$(build_rclone_opts)

    log "Starting sync from $REMOTE to $LOCAL"

    # Execute sync
    # shellcheck disable=SC2086
    if rclone sync "$REMOTE" "$LOCAL" $opts; then
        log "Sync completed successfully"

        # Count files in local inbox
        local file_count
        file_count=$(find "$LOCAL" -type f 2>/dev/null | wc -l)
        log "Files in local inbox: $file_count"

        # Delete remote files after successful sync if requested
        if [ "$DELETE_AFTER" = true ] && [ "$DRY_RUN" = false ]; then
            log "Deleting synced files from remote..."
            # Only delete files that exist locally
            for file in "$LOCAL"/*; do
                if [ -f "$file" ]; then
                    local filename
                    filename=$(basename "$file")
                    if rclone deletefile "$REMOTE/$filename" 2>/dev/null; then
                        log "Deleted remote: $filename"
                    fi
                fi
            done
        fi

        return 0
    else
        local exit_code=$?
        log "Sync failed with exit code: $exit_code"
        return $exit_code
    fi
}

# Health check - verify remote is accessible
health_check() {
    log "Performing health check..."

    if rclone lsd gdrive: --max-depth 0 &>/dev/null; then
        log "Remote accessible: OK"
        return 0
    else
        log "Remote NOT accessible - may need reauthentication"
        log "Try: rclone config reconnect gdrive:"
        return 1
    fi
}

# Main execution
if [ "$VERBOSE" = true ]; then
    print_config
fi

# Initial health check
if ! health_check; then
    echo "ERROR: Cannot access Google Drive remote"
    echo "Check authentication: rclone config reconnect gdrive:"
    exit 1
fi

if [ "$RUN_ONCE" = true ]; then
    # Single execution mode
    log "Running single sync..."
    if sync_once; then
        log "Done."
        exit 0
    else
        log "Sync failed."
        exit 2
    fi
else
    # Continuous loop mode
    log "Starting continuous sync loop (interval: ${INTERVAL}s)..."
    log "Press Ctrl+C to stop"
    echo ""

    # Track consecutive failures for backoff
    CONSECUTIVE_FAILURES=0
    MAX_BACKOFF=300  # 5 minutes max

    while true; do
        if sync_once; then
            CONSECUTIVE_FAILURES=0
        else
            CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))

            # Apply exponential backoff on repeated failures
            if [ $CONSECUTIVE_FAILURES -ge 3 ]; then
                BACKOFF=$((INTERVAL * CONSECUTIVE_FAILURES))
                if [ $BACKOFF -gt $MAX_BACKOFF ]; then
                    BACKOFF=$MAX_BACKOFF
                fi
                log "Multiple failures ($CONSECUTIVE_FAILURES) - backing off for ${BACKOFF}s"
                sleep $BACKOFF
                continue
            fi
        fi

        log "Sleeping for ${INTERVAL}s..."
        sleep "$INTERVAL"
    done
fi
