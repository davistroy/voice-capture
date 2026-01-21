# rclone Configuration for Voice Capture Pipeline

This directory contains scripts for setting up and running rclone to sync audio files from Google Drive to the local processing inbox.

## Overview

The Voice Capture pipeline uses rclone to sync audio recordings from Google Drive (`/VoiceCaptures/inbox`) to a local directory where the Python watcher picks them up for processing.

**Sync Flow:**
```
iPhone/Watch → iOS Shortcut → Google Drive → rclone sync → Local Inbox → Watcher
```

## Files

| File | Purpose |
|------|---------|
| `setup.sh` | Interactive rclone configuration with Google Drive OAuth |
| `sync.sh` | Sync script (continuous loop or single run) |

## Quick Start

### 1. Configure rclone (One-Time Setup)

Run the setup script to configure Google Drive authentication:

```bash
# If you have a browser on this machine:
./scripts/rclone/setup.sh

# If this is a headless server (UNRAID, NAS, etc.):
./scripts/rclone/setup.sh --headless
```

The script will:
1. Guide you through rclone configuration
2. Create the `gdrive` remote
3. Create the `VoiceCaptures/inbox` folder on Google Drive if needed
4. Copy `rclone.conf` to the project's `rclone-config/` directory

### 2. Verify Configuration

```bash
# Test the configuration
./scripts/rclone/setup.sh --test

# Or manually:
rclone ls gdrive:/VoiceCaptures/inbox
```

### 3. Start the Pipeline

```bash
docker-compose up -d
```

## Google Drive OAuth Setup

rclone uses OAuth 2.0 to authenticate with Google Drive. The specific process depends on your environment.

### Option A: Machine with Browser (Recommended)

If the machine where you're configuring rclone has a web browser:

1. Run `./setup.sh`
2. When asked "Use auto config?", answer **Yes** (Y)
3. A browser window opens automatically
4. Sign in to Google and grant rclone permissions
5. Return to the terminal - rclone saves the token automatically

### Option B: Headless Server (UNRAID, NAS, VPS)

If the server has no browser:

1. Run `./setup.sh --headless`
2. When asked "Use auto config?", answer **No** (n)
3. rclone displays a URL like:
   ```
   If your browser doesn't open automatically go to the following link:
   https://accounts.google.com/o/oauth2/auth?...
   ```
4. Copy this URL to a browser on another machine
5. Sign in to Google and grant permissions
6. Google displays a verification code
7. Copy the code back to the terminal prompt

### Option C: Remote Authorization (Best for Headless)

Generate credentials on a machine with a browser, then transfer:

On a machine with a browser:
```bash
rclone authorize "drive"
```

This outputs JSON token data. When configuring on the headless server, paste this token when prompted for "result from rclone authorize".

### Token Refresh

OAuth tokens expire periodically. rclone handles refresh automatically as long as the refresh token is valid. If authentication fails after some time:

```bash
rclone config reconnect gdrive:
```

## Sync Script Usage

### Continuous Loop (Default - Used by Docker)

```bash
./scripts/rclone/sync.sh
```

Syncs every 180 seconds (configurable via `RCLONE_SYNC_INTERVAL`).

### Single Sync (Testing)

```bash
./scripts/rclone/sync.sh --once
```

### Dry Run (Preview Changes)

```bash
./scripts/rclone/sync.sh --once --dry-run
```

### Delete Files After Sync

By default, files remain on Google Drive after syncing. To delete after successful sync:

```bash
./scripts/rclone/sync.sh --once --delete-after
```

### All Options

```
Usage:
  ./sync.sh                   # Continuous sync loop (default: 180s interval)
  ./sync.sh --once            # Single sync, then exit
  ./sync.sh --interval 60     # Continuous sync with 60s interval
  ./sync.sh --dry-run         # Preview what would be synced (no changes)
  ./sync.sh --delete-after    # Delete remote files after successful sync
  ./sync.sh --help            # Show help
```

## Testing in Docker

### Test rclone Service in Isolation

```bash
# Start only the rclone service
docker-compose up rclone

# In another terminal, watch the logs
docker-compose logs -f rclone

# Check the inbox volume
docker-compose exec rclone ls -la /data/inbox/
```

### Test a Single Sync

```bash
# Execute one sync inside the container
docker-compose exec rclone rclone sync gdrive:/VoiceCaptures/inbox /data/inbox --checksum -v
```

### Verify Configuration Inside Container

```bash
# Check rclone config is mounted
docker-compose exec rclone rclone listremotes

# List Google Drive contents
docker-compose exec rclone rclone ls gdrive:/VoiceCaptures/inbox
```

### Manual File Test

1. Place a test audio file on Google Drive:
   ```bash
   # From your local machine
   rclone copy test.m4a gdrive:/VoiceCaptures/inbox/
   ```

2. Trigger sync and verify:
   ```bash
   docker-compose exec rclone rclone sync gdrive:/VoiceCaptures/inbox /data/inbox --checksum -v
   docker-compose exec rclone ls -la /data/inbox/
   ```

3. Verify the voice-capture service sees it:
   ```bash
   docker-compose exec voice-capture ls -la /app/inbox/
   ```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RCLONE_SYNC_INTERVAL` | `180` | Seconds between sync cycles |
| `RCLONE_REMOTE` | `gdrive:/VoiceCaptures/inbox` | Remote path |
| `RCLONE_LOCAL` | `/data/inbox` | Local path (in container) |
| `RCLONE_LOG_FILE` | `/data/logs/rclone.log` | Log file path |
| `RCLONE_CONFIG` | Auto-detected | Path to rclone.conf |

## Directory Structure

```
voice-capture/
├── rclone-config/
│   ├── .gitkeep           # Ensures directory exists in git
│   └── rclone.conf        # OAuth tokens (NOT committed - in .gitignore)
├── scripts/rclone/
│   ├── setup.sh           # Configuration script
│   ├── sync.sh            # Sync script
│   └── README.md          # This file
└── docker-compose.yml     # Defines rclone service
```

## Troubleshooting

### "remote not found" or "gdrive: not configured"

Run setup to configure the remote:
```bash
./scripts/rclone/setup.sh
```

### "token has been expired or revoked"

Reauthenticate:
```bash
rclone config reconnect gdrive:
# Then copy updated rclone.conf to rclone-config/
```

### Files Not Appearing in Inbox

1. Check rclone can access the remote:
   ```bash
   rclone ls gdrive:/VoiceCaptures/inbox
   ```

2. Check sync logs:
   ```bash
   docker-compose logs rclone
   cat logs/rclone.log
   ```

3. Verify the folder structure exists:
   ```bash
   rclone lsd gdrive:/VoiceCaptures
   ```

### Permission Denied on rclone.conf

The config file should be readable only by the owner:
```bash
chmod 600 rclone-config/rclone.conf
```

### Sync is Slow

rclone uses checksums to detect changes, which requires reading file contents. For faster operation (but slightly less reliable change detection):
```bash
rclone sync gdrive:/VoiceCaptures/inbox /data/inbox --size-only
```

## Security Notes

- **Never commit `rclone.conf`** - it contains OAuth tokens that grant access to your Google Drive
- The config is mounted read-only into Docker containers (`./rclone-config:/config/rclone:ro`)
- Tokens can be revoked from [Google Account Security](https://myaccount.google.com/permissions)
- Consider using a dedicated Google account for this pipeline
