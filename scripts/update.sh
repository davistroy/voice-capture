#!/bin/bash
#
# Voice Capture Update Script
# Brings down the stack, updates code, rebuilds, and restarts
#
# Usage: ./scripts/update.sh [--no-rebuild]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
REBUILD=true
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-rebuild)
            REBUILD=false
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--no-rebuild]"
            echo ""
            echo "Options:"
            echo "  --no-rebuild    Skip docker image rebuild (faster if only config changed)"
            echo "  -h, --help      Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

cd "$PROJECT_DIR"
log_info "Working directory: $PROJECT_DIR"

# Check for uncommitted changes
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    log_warn "You have uncommitted changes. They will be preserved during update."
fi

# Step 1: Bring down the stack
log_info "Stopping docker stack..."
docker compose down

# Step 2: Pull latest code
log_info "Pulling latest code from git..."
CURRENT_BRANCH=$(git branch --show-current)
git fetch origin "$CURRENT_BRANCH"

# Check if there are updates
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$CURRENT_BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    log_info "Already up to date."
else
    log_info "Updating from $LOCAL to $REMOTE..."
    git pull origin "$CURRENT_BRANCH"
fi

# Step 3: Rebuild if needed
if [ "$REBUILD" = true ]; then
    log_info "Rebuilding docker images..."
    docker compose build --no-cache voice-capture
else
    log_info "Skipping rebuild (--no-rebuild specified)"
fi

# Step 4: Bring the stack back up
log_info "Starting docker stack..."
docker compose up -d

# Step 5: Show status
log_info "Waiting for services to start..."
sleep 5

log_info "Service status:"
docker compose ps

log_info "Update complete!"
echo ""
echo "Useful commands:"
echo "  docker compose logs -f voice-capture    # View application logs"
echo "  docker compose logs -f rclone           # View rclone sync logs"
echo "  docker compose ps                       # Check service status"
