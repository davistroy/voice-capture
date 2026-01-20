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
# - For headless server: a browser available on another machine
#
# =============================================================================

set -e

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
    echo ""
    exit 1
fi

echo "rclone version: $(rclone version | head -n 1)"
echo ""

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
echo "IMPORTANT: When prompted, use these settings:"
echo "  - Name: gdrive"
echo "  - Storage type: Google Drive (usually option 18)"
echo "  - Client ID: Leave blank (uses rclone's default)"
echo "  - Client Secret: Leave blank"
echo "  - Scope: Full access (option 1)"
echo "  - Root folder: Leave blank"
echo "  - Service account: Leave blank"
echo "  - Edit advanced config: No"
echo "  - Auto config: Yes (if you have a browser)"
echo ""
read -p "Press Enter to continue..."
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
        echo "Next Steps"
        echo "=============================================="
        echo ""
        echo "1. Copy rclone.conf to the project:"
        echo "   cp ~/.config/rclone/rclone.conf ./rclone-config/"
        echo ""
        echo "2. Configure iOS Shortcut to save recordings to:"
        echo "   Google Drive > VoiceCaptures > inbox"
        echo ""
        echo "3. Start the pipeline:"
        echo "   docker-compose up -d"
        echo ""
    else
        echo "WARNING: Could not list Google Drive contents."
        echo "You may need to reauthorize: rclone config reconnect gdrive:"
    fi
else
    echo "WARNING: 'gdrive' remote was not created."
    echo "Run this script again or use: rclone config"
fi
