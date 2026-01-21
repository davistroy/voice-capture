#!/bin/bash
# =============================================================================
# rclone Setup Script for Voice Capture Pipeline
# =============================================================================
#
# This script helps configure rclone for Google Drive sync.
#
# Prerequisites:
# - rclone installed (https://rclone.org/install/)
# - Google account with Drive access
# - For headless server: a machine with a browser (for OAuth)
#
# Usage:
#   ./setup.sh              # Interactive setup
#   ./setup.sh --headless   # Headless server setup (generates auth URL)
#   ./setup.sh --test       # Test existing configuration
#   ./setup.sh --help       # Show this help
#
# =============================================================================
#
# OAUTH SETUP PROCESS FOR GOOGLE DRIVE
# =====================================
#
# rclone uses OAuth 2.0 to authenticate with Google Drive. The process differs
# depending on whether your server has a graphical browser available.
#
# OPTION A: Server with Browser (Desktop/Laptop)
# -----------------------------------------------
# 1. Run: ./setup.sh
# 2. When prompted for "auto config", choose Yes (Y)
# 3. A browser window opens automatically
# 4. Log in to Google and grant permissions
# 5. rclone receives the token automatically
#
# OPTION B: Headless Server (UNRAID, NAS, VPS)
# ---------------------------------------------
# 1. Run: ./setup.sh --headless
# 2. When prompted for "auto config", choose No (n)
# 3. rclone displays a URL - copy this URL
# 4. Open the URL in a browser on another machine
# 5. Log in to Google and grant permissions
# 6. Google displays an authorization code
# 7. Copy the code back to the rclone prompt
# 8. rclone saves the configuration
#
# OPTION C: Remote Configuration (Recommended for Headless)
# ----------------------------------------------------------
# On your local machine with a browser:
#   rclone authorize "drive"
# This opens a browser, authenticates, and outputs a token.
# Copy the token JSON to your headless server when prompted.
#
# TOKEN REFRESH
# -------------
# OAuth tokens expire periodically. rclone handles refresh automatically
# as long as the refresh_token is valid. If authentication fails:
#   rclone config reconnect gdrive:
#
# =============================================================================

set -e

# Script directory for relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RCLONE_CONFIG_DIR="$PROJECT_ROOT/rclone-config"

# Parse arguments
HEADLESS=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --headless)
            HEADLESS=true
            shift
            ;;
        --test)
            TEST_ONLY=true
            shift
            ;;
        --help|-h)
            head -60 "$0" | tail -55
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "Voice Capture - rclone Setup"
echo "=============================================="
echo ""

# Check if rclone is installed
if ! command -v rclone &> /dev/null; then
    echo "ERROR: rclone is not installed."
    echo ""
    echo "Install rclone:"
    echo "  Linux:   curl https://rclone.org/install.sh | sudo bash"
    echo "  macOS:   brew install rclone"
    echo "  Windows: Download from https://rclone.org/downloads/"
    echo "  Docker:  docker pull rclone/rclone"
    echo ""
    exit 1
fi

echo "rclone version: $(rclone version | head -n 1)"
echo "Project root:   $PROJECT_ROOT"
echo "Config dir:     $RCLONE_CONFIG_DIR"
echo ""

# Test-only mode
if [ "$TEST_ONLY" = true ]; then
    echo "Running configuration test..."
    echo ""

    if ! rclone listremotes | grep -q "^gdrive:"; then
        echo "FAIL: No 'gdrive' remote configured"
        echo "Run: ./setup.sh"
        exit 1
    fi

    echo "Testing Google Drive connection..."
    if rclone lsd gdrive: --max-depth 1 2>/dev/null; then
        echo ""
        echo "SUCCESS: Google Drive accessible"
    else
        echo "FAIL: Cannot access Google Drive"
        echo "Try: rclone config reconnect gdrive:"
        exit 1
    fi

    echo ""
    echo "Testing VoiceCaptures/inbox folder..."
    if rclone lsd gdrive:/VoiceCaptures/inbox 2>/dev/null; then
        echo "SUCCESS: VoiceCaptures/inbox folder exists"

        # List any existing files
        FILE_COUNT=$(rclone ls gdrive:/VoiceCaptures/inbox 2>/dev/null | wc -l)
        echo "Files in inbox: $FILE_COUNT"
    else
        echo "WARNING: VoiceCaptures/inbox folder not found"
        echo "It will be created on first sync or you can create it:"
        echo "  rclone mkdir gdrive:/VoiceCaptures/inbox"
    fi

    echo ""
    echo "Configuration test complete."
    exit 0
fi

# Check if gdrive remote already exists
if rclone listremotes | grep -q "^gdrive:"; then
    echo "A 'gdrive' remote already exists."
    echo ""
    read -p "Do you want to reconfigure it? (y/N): " reconfigure
    if [[ ! "$reconfigure" =~ ^[Yy]$ ]]; then
        echo "Keeping existing configuration."
        echo ""
        echo "Testing connection..."
        if rclone lsd gdrive: &> /dev/null; then
            echo "SUCCESS: Connected to Google Drive."
        else
            echo "WARNING: Could not connect. Run 'rclone config reconnect gdrive:'"
        fi
        exit 0
    fi
    echo ""
fi

echo "Setting up Google Drive remote..."
echo ""
echo "=============================================="
echo "Configuration Guide"
echo "=============================================="
echo ""
echo "When prompted, use these settings:"
echo ""
echo "  n) New remote"
echo "  Name:                 gdrive"
echo "  Storage type:         Google Drive (option 18 or 'drive')"
echo "  Client ID:            [Leave blank - uses rclone default]"
echo "  Client Secret:        [Leave blank]"
echo "  Scope:                1 (Full access to all files)"
echo "  Service Account:      [Leave blank]"
echo "  Root folder ID:       [Leave blank]"
echo "  Advanced config:      No (n)"
echo ""

if [ "$HEADLESS" = true ]; then
    echo "HEADLESS MODE:"
    echo "  Auto config:          No (n)"
    echo "  -> Copy the displayed URL to a browser on another machine"
    echo "  -> Authenticate with Google"
    echo "  -> Copy the verification code back here"
    echo ""
    echo "Alternatively, run on a machine with a browser:"
    echo "  rclone authorize \"drive\""
    echo "Then paste the resulting token when prompted."
    echo ""
else
    echo "  Auto config:          Yes (y) - browser will open"
    echo ""
fi

read -p "Press Enter to start configuration..."
echo ""

# Run interactive configuration
rclone config

echo ""
echo "=============================================="
echo "Configuration Complete"
echo "=============================================="
echo ""

# Verify the remote was created
if rclone listremotes | grep -q "^gdrive:"; then
    echo "SUCCESS: 'gdrive' remote created."
    echo ""

    # Test connection
    echo "Testing connection..."
    if rclone lsd gdrive: &> /dev/null; then
        echo "SUCCESS: Connected to Google Drive."
        echo ""

        # Check/create VoiceCaptures folder
        echo "Checking for VoiceCaptures folder..."
        if rclone lsd gdrive:/VoiceCaptures &> /dev/null; then
            echo "Found: gdrive:/VoiceCaptures/"
        else
            echo "Creating VoiceCaptures folder structure..."
            rclone mkdir gdrive:/VoiceCaptures/inbox
            echo "Created: gdrive:/VoiceCaptures/inbox/"
        fi

        # Check/create inbox subfolder
        if ! rclone lsd gdrive:/VoiceCaptures/inbox &> /dev/null; then
            rclone mkdir gdrive:/VoiceCaptures/inbox
            echo "Created: gdrive:/VoiceCaptures/inbox/"
        fi

        echo ""
        echo "=============================================="
        echo "Copying Configuration to Project"
        echo "=============================================="
        echo ""

        # Ensure config directory exists
        mkdir -p "$RCLONE_CONFIG_DIR"

        # Detect rclone config file location
        RCLONE_CONF_PATH="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
        if [ ! -f "$RCLONE_CONF_PATH" ]; then
            # Try alternative locations
            if [ -f "$HOME/.rclone.conf" ]; then
                RCLONE_CONF_PATH="$HOME/.rclone.conf"
            elif [ -f "/config/rclone/rclone.conf" ]; then
                RCLONE_CONF_PATH="/config/rclone/rclone.conf"
            fi
        fi

        if [ -f "$RCLONE_CONF_PATH" ]; then
            cp "$RCLONE_CONF_PATH" "$RCLONE_CONFIG_DIR/rclone.conf"
            chmod 600 "$RCLONE_CONFIG_DIR/rclone.conf"
            echo "Copied: $RCLONE_CONF_PATH"
            echo "    ->  $RCLONE_CONFIG_DIR/rclone.conf"
            echo ""
            echo "IMPORTANT: rclone.conf contains OAuth tokens."
            echo "           Do NOT commit this file to version control."
            echo "           It is already listed in .gitignore."
        else
            echo "WARNING: Could not find rclone.conf"
            echo "Manually copy your config file to: $RCLONE_CONFIG_DIR/"
            echo ""
            echo "Typical locations:"
            echo "  Linux/macOS: ~/.config/rclone/rclone.conf"
            echo "  Windows:     %APPDATA%\\rclone\\rclone.conf"
        fi

        echo ""
        echo "=============================================="
        echo "Next Steps"
        echo "=============================================="
        echo ""
        echo "1. Verify the configuration was copied:"
        echo "   ls -la $RCLONE_CONFIG_DIR/"
        echo ""
        echo "2. Test the sync manually:"
        echo "   ./scripts/rclone/sync.sh --once"
        echo ""
        echo "3. Configure iOS Shortcut to save recordings to:"
        echo "   Google Drive > VoiceCaptures > inbox"
        echo ""
        echo "4. Start the pipeline:"
        echo "   docker-compose up -d"
        echo ""
        echo "5. Verify rclone container is syncing:"
        echo "   docker-compose logs -f rclone"
        echo ""
    else
        echo "WARNING: Could not list Google Drive contents."
        echo "You may need to reauthorize: rclone config reconnect gdrive:"
    fi
else
    echo "WARNING: 'gdrive' remote was not created."
    echo "Run this script again or use: rclone config"
fi
