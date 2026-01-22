# Voice Capture to Notion Pipeline - Complete Setup Guide

## Overview

This system captures voice recordings from Apple Watch/iPhone, automatically transcribes them using OpenAI Whisper, classifies them into structured templates using Claude, and stores them in Notion. It runs on Docker (ideal for UNRAID, home server, or VPS).

---

## Prerequisites

| Requirement | Source | Cost |
|-------------|--------|------|
| Docker & Docker Compose | docker.com | Free |
| OpenAI API Key | platform.openai.com | Pay per use (~$0.006/min) |
| Anthropic API Key | console.anthropic.com | Pay per use (~$0.003/1K tokens) |
| Notion API Key | notion.so/my-integrations | Free |
| Pushover Account | pushover.net | $5 one-time |
| Google Account | For Drive sync | Free |
| iPhone/Apple Watch | For capture | — |
| "Just Press Record" app | App Store | $4.99 |

---

## Part 1: Notion Setup

### 1.1 Create Voice Captures Database

In Notion, create a new database with these properties:

| Property | Type | Values/Notes |
|----------|------|--------------|
| Title | Title | Auto-generated from transcript |
| Date | Date | Capture timestamp |
| Type | Select | Journal, Task, Idea, Research, Product, General |
| Device | Select | Watch, Phone |
| Tags | Multi-select | Auto-populated from classification |
| Mood | Select | (for Journal only) Great, Good, Okay, Difficult, Rough |
| Priority | Select | (for Task/Product) High, Medium, Low |
| Status | Select | (for Task/Research) Not Started, In Progress, Complete |

### 1.2 Create Weekly Summaries Database

Create a second database for weekly synthesis:

| Property | Type |
|----------|------|
| Title | Title |
| Week Start | Date |
| Week End | Date |
| Capture Count | Number |
| Supplemental Input | Checkbox |

### 1.3 Create Notion Integration

1. Go to **notion.so/my-integrations**
2. Click **New Integration**
3. Name it "Voice Capture Pipeline"
4. Select your workspace
5. Copy the **Internal Integration Secret** (starts with `secret_`)
6. **Grant Access**: Open each database, click `...` → **Connections** → Add your integration

### 1.4 Get Database IDs

For each database:
1. Open the database as a full page
2. Copy the URL: `https://notion.so/workspace/DATABASE_ID?v=...`
3. The DATABASE_ID is the 32-character hex string before `?v=`

---

## Part 2: API Keys Setup

### 2.1 OpenAI API Key (Whisper)

1. Go to **platform.openai.com/api-keys**
2. Create new secret key
3. Copy it (starts with `sk-`)

### 2.2 Anthropic API Key (Claude)

1. Go to **console.anthropic.com/settings/keys**
2. Create key
3. Copy it (starts with `sk-ant-`)

### 2.3 Pushover Setup (Notifications)

1. Go to **pushover.net** and create account ($5 one-time)
2. Note your **User Key** on the dashboard
3. **Create an Application** → Get the **API Token**

---

## Part 3: Server Deployment

### 3.1 Clone and Configure

```bash
# Clone the repository
git clone https://github.com/davistroy/voice-capture.git
cd voice-capture

# Copy environment template
cp .env.example .env
```

### 3.2 Edit .env File

```bash
nano .env  # or your preferred editor
```

Fill in all values:

```env
# Required API Keys
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
NOTION_API_KEY=secret_your-notion-key
PUSHOVER_API_TOKEN=your-pushover-app-token
PUSHOVER_USER_KEY=your-pushover-user-key

# Required Notion Database IDs
NOTION_VOICE_CAPTURES_DB_ID=your-32-char-database-id
NOTION_WEEKLY_SUMMARIES_DB_ID=your-32-char-database-id

# Optional (defaults shown)
VOICE_CAPTURE_LOG_LEVEL=INFO
RCLONE_SYNC_INTERVAL=180
```

### 3.3 Configure rclone (Google Drive Sync)

**If your server has a browser:**
```bash
./scripts/rclone/setup.sh
```

**If headless (UNRAID, NAS):**
```bash
./scripts/rclone/setup.sh --headless
```

This will:
1. Walk you through Google OAuth
2. Create the `gdrive` remote
3. Create `/VoiceCaptures/inbox` folder on Drive
4. Copy `rclone.conf` to `rclone-config/`

**Test the configuration:**
```bash
./scripts/rclone/setup.sh --test
# Or manually:
rclone ls gdrive:/VoiceCaptures/inbox
```

### 3.4 Start the Services

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps
```

### 3.5 Verify Configuration

```bash
# Run config verification
docker-compose exec voice-capture python -m src.cli.verify_config
```

This checks:
- All environment variables
- API connectivity (OpenAI, Claude, Notion, Pushover)
- Directory permissions

---

## Part 4: iOS Capture Setup

### 4.1 Install Just Press Record

1. Download **Just Press Record** from App Store ($4.99)
2. Enable iCloud sync in app settings
3. Configure: Audio Quality = High, Format = M4A

### 4.2 Create iOS Shortcut

This shortcut records audio and saves it to Google Drive for processing. Follow these steps exactly.

#### Step 1: Open Shortcuts App

1. Find the **Shortcuts** app on your iPhone (comes pre-installed, blue icon with overlapping squares)
2. If you can't find it, swipe down on home screen and search "Shortcuts"
3. Tap to open — you'll see a screen with "All Shortcuts" at the top

#### Step 2: Create New Shortcut

1. Tap the **+** button in the top-right corner
2. You'll see a blank shortcut editor with "New Shortcut" at the top
3. At the bottom, you'll see "Search for apps and actions" — this is where you'll add each action

#### Step 3: Add "Start Recording" Action

1. Tap "**Search for apps and actions**" at the bottom
2. Type: `Just Press Record`
3. You'll see the Just Press Record app icon with available actions listed below it
4. Tap **"Start New Recording"**
5. **What you should see:** A blue action block appears that says "Start New Recording"

**⚠️ Troubleshooting:** If you don't see Just Press Record:
- Make sure the app is installed
- Open Just Press Record once first, then return to Shortcuts
- Restart your iPhone if it still doesn't appear

#### Step 4: Add "Wait to Return" Action

1. Tap "**Search for apps and actions**" again
2. Type: `Wait to Return`
3. Tap **"Wait to Return"** (under Scripting)
4. **What you should see:** A second action block appears below the first

**What this does:** When you run the shortcut, it opens Just Press Record to record. This action waits until you finish recording and return to the Shortcuts app.

#### Step 5: Add "Get Latest Recording" Action

1. Tap "**Search for apps and actions**" again
2. Type: `Just Press Record`
3. Look for **"Get Latest Recording"** and tap it
4. **What you should see:** A third action block appears. It may show "Get Latest Recording from Just Press Record"

#### Step 6: Add "Save File" Action

1. Tap "**Search for apps and actions**" again
2. Type: `Save File`
3. Tap **"Save File"** (the one with the Files icon, not iCloud-specific)
4. **What you should see:** A new action block with several configurable options

#### Step 7: Configure the Save File Action (CRITICAL)

This is the most important step. You need to configure exactly where files go.

1. In the Save File action block, you'll see:
   - **Save [Recording]** — this should already show "Recording" from the previous action
   - **Ask Where to Save** toggle — **turn this OFF** (tap the toggle so it's gray, not green)

2. Once you turn off "Ask Where to Save," new options appear:
   - **Destination Folder** — tap this

3. A folder browser opens. Navigate as follows:
   - Tap **"Browse"** at the bottom if you're not already in browse mode
   - Tap **"Google Drive"** (if you don't see it, see troubleshooting below)
   - Navigate to or create: **VoiceCaptures** folder
   - Inside VoiceCaptures, navigate to or create: **inbox** folder
   - Tap **"Open"** or **"Done"** in the top-right when you're inside `/VoiceCaptures/inbox/`

4. **What you should see:** The Save File action now shows:
   ```
   Save Recording to /VoiceCaptures/inbox
   ```

**⚠️ Troubleshooting — Can't see Google Drive:**
- Open the **Files** app separately
- Tap **"Browse"** at the bottom
- Tap the **"..."** button in the top-right → **"Edit"**
- Enable **"Google Drive"** toggle
- Return to Shortcuts and try again

**⚠️ Troubleshooting — VoiceCaptures folder doesn't exist:**
- In the Files app, navigate to Google Drive
- Tap and hold on empty space → **"New Folder"**
- Name it exactly: `VoiceCaptures`
- Open it, create another folder named exactly: `inbox`
- Return to Shortcuts and navigate to this folder

#### Step 8: Verify Your Shortcut

Your completed shortcut should show **4 actions** in this exact order:

```
┌─────────────────────────────────────┐
│ 1. Start New Recording              │
│    Just Press Record                │
├─────────────────────────────────────┤
│ 2. Wait to Return                   │
│    Scripting                        │
├─────────────────────────────────────┤
│ 3. Get Latest Recording             │
│    Just Press Record                │
├─────────────────────────────────────┤
│ 4. Save Recording                   │
│    to /VoiceCaptures/inbox          │
└─────────────────────────────────────┘
```

#### Step 9: Name and Save the Shortcut

1. Tap **"New Shortcut"** at the very top of the screen (or the dropdown arrow next to it)
2. Tap **"Rename"**
3. Type: `Voice Capture` (or any name you prefer)
4. Tap **"Done"** on keyboard
5. Tap **"Done"** in top-right to save the shortcut

#### Step 10: Test the Shortcut

**This is critical — test before relying on it!**

1. Find your new shortcut in the Shortcuts app
2. Tap it to run
3. **What should happen:**
   - Just Press Record opens and immediately starts recording (you'll see the red recording indicator)
   - Speak a test message: "This is a test recording"
   - Tap the **stop button** in Just Press Record
   - You'll be returned to Shortcuts (may see a brief "Running..." indicator)
   - Shortcut completes

4. **Verify the file was saved:**
   - Open the **Files** app
   - Navigate to **Google Drive → VoiceCaptures → inbox**
   - You should see a new `.m4a` file with today's date/time
   - Tap it to play and confirm it's your recording

**✅ Success indicators:**
- File appears in Google Drive within seconds
- File is playable and contains your test message
- File name format is something like `2026-01-22 10-30-45.m4a`

**⚠️ Common problems:**

| Problem | Solution |
|---------|----------|
| Shortcut runs but no file appears | Check Save File destination is set correctly. Recreate the action if needed |
| "Access denied" or permissions error | Open Files app, navigate to Google Drive manually first to trigger sign-in |
| Recording is empty/silent | Check Just Press Record has microphone permission in Settings → Privacy → Microphone |
| Shortcut gets stuck on "Wait to Return" | Make sure you tap STOP in Just Press Record, don't just swipe away |
| Google Drive folder not found | Create the folders manually in Files app first, then reconfigure the shortcut |

#### Step 11: Add to Home Screen

1. In Shortcuts app, tap and hold on your "Voice Capture" shortcut
2. Tap **"Details"** (or tap the **"..."** button)
3. Tap **"Add to Home Screen"**
4. Optionally customize the icon color/glyph
5. Tap **"Add"** in the top-right
6. **What you should see:** The shortcut appears on your home screen as an app icon

### 4.3 Apple Watch Complication

1. In Shortcuts app, select your shortcut
2. Tap the `...` menu → **Add to Apple Watch**
3. Add complication to your watch face

**Usage:** Tap the complication → speak → tap again to stop. File syncs automatically.

---

## Part 5: Using the System

### 5.1 Daily Capture Flow

1. **Tap** the Watch complication (or iPhone shortcut)
2. **Speak** your thought
3. **Tap** to stop recording
4. **Done** — file syncs to Google Drive, then to your server, transcribed, classified, and posted to Notion

**Typical latency:** 2-5 minutes from capture to Notion page

### 5.2 Monitor Processing

```bash
# View real-time logs
docker-compose logs -f voice-capture

# Check queue status
docker-compose exec voice-capture python -m src.cli.queue_status
```

### 5.3 Handle Failures

```bash
# View failed items
docker-compose exec voice-capture python -m src.cli.queue_status

# Retry a specific capture
docker-compose exec voice-capture python -m src.cli.retry --capture-id 42

# Retry all failed
docker-compose exec voice-capture python -m src.cli.retry --all-failed

# Reset a capture to reprocess from scratch
docker-compose exec voice-capture python -m src.cli.reset_capture --filename "file.m4a"
```

### 5.4 Health Monitoring

```bash
# Run health check manually
docker-compose exec voice-capture python -m src.cli.health_check
```

The system sends daily health summaries via Pushover at 9 PM (configurable). Alerts trigger for:
- Failure rate > 20%
- Queue backup > 10 items
- Any API unreachable

---

## Part 6: Weekly Synthesis

The weekly synthesis skill requires **Notion MCP** configured in Claude Code or Claude Desktop.

### 6.1 Configure Notion MCP

**Claude Code** (`~/.claude.json`):
```json
{
  "mcpServers": {
    "notion": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-notion"],
      "env": {
        "NOTION_API_KEY": "secret_your-notion-api-key"
      }
    }
  }
}
```

### 6.2 Run Weekly Synthesis

```bash
# In Claude Code
claude "Run weekly-voice-synthesis"

# Or with options
claude "Run weekly-voice-synthesis with days=14"
claude "Run weekly-voice-synthesis with save_to_notion=false"
```

The skill will:
1. Query captures from the past 7 days
2. Group by template type
3. If sparse (< 3 captures), ask supplemental questions
4. Generate structured summary
5. Save to Weekly Summaries database

---

## Part 7: Template Reference

### Template Types & Triggers

| Template | Trigger Phrases | Key Fields |
|----------|-----------------|------------|
| **Journal** | "Today I...", "I feel...", "Reflecting on..." | Mood, Summary, People |
| **Task** | "I need to...", "Remind me to...", "Don't forget..." | Due Date, Priority, Status |
| **Idea** | "What if...", "Idea:", "I'm thinking..." | Core Concept, Potential Value |
| **Research** | "Learn about...", "Research...", "I wonder..." | Question, Why It Matters, Status |
| **Product** | "Feature request:", "Bug:", "[Project name]..." | Product, Type, User Impact |
| **General** | (fallback for < 0.7 confidence) | Summary, Suggested Template |

### Adding Custom Templates

1. Create `config/templates/your_template.yaml` using `_template.yaml` as reference
2. Define triggers, fields, and Notion property mappings
3. Restart the service: `docker-compose restart voice-capture`

---

## Part 8: UNRAID-Specific Setup

This section provides detailed UNRAID-specific instructions. UNRAID is popular for home servers and has some unique considerations for running Docker Compose stacks.

### 8.1 Install Community Applications (If Not Already Installed)

Community Applications (CA) is required to install the Docker Compose Manager plugin.

1. Open your UNRAID web UI (typically `http://tower` or `http://[your-server-ip]`)
2. Go to **Plugins** tab in the top navigation
3. If you see "Community Applications" in your installed plugins, skip to 8.2
4. If not installed:
   - Click **Install Plugin** tab
   - Paste this URL: `https://raw.githubusercontent.com/Squidly271/community.applications/master/plugins/community.applications.plg`
   - Click **Install**
   - Wait for installation to complete (you'll see "plugin installation successful")
   - Refresh the page — **Apps** tab should now appear in the top navigation

### 8.2 Install Docker Compose Manager Plugin

1. Click the **Apps** tab in UNRAID web UI
2. In the search bar at the top, type: `Docker Compose Manager`
3. Find **"Docker Compose Manager"** by dcflacern (look for the blue whale + gear icon)
4. Click **Install**
5. On the settings page that appears:
   - Leave defaults as-is (they work for most setups)
   - Click **Apply**
6. Wait for installation to complete

**✅ Success indicator:** After installation, you'll see a new **"Compose"** icon in the Docker tab, or a **"Compose"** entry in the sidebar.

**⚠️ Troubleshooting:**
- If you don't see Compose after installing, go to **Settings → Docker** and ensure Docker is enabled
- Try refreshing your browser (Ctrl+Shift+R for hard refresh)

### 8.3 Prepare the Application Directory

You'll store the voice-capture application in UNRAID's appdata share.

#### Step 1: Access the Terminal

1. In UNRAID web UI, click the **terminal icon** (">_") in the top-right corner
   - OR go to **Tools → System Terminal**
   - OR SSH into your server: `ssh root@[your-unraid-ip]`
2. **What you should see:** A black terminal window with a command prompt like `root@Tower:~#`

#### Step 2: Create Directory and Clone Repository

Type these commands exactly (press Enter after each line):

```bash
# Navigate to appdata
cd /mnt/user/appdata

# Create voice-capture directory
mkdir -p voice-capture

# Clone the repository
git clone https://github.com/davistroy/voice-capture.git /mnt/user/appdata/voice-capture

# Navigate into the directory
cd /mnt/user/appdata/voice-capture

# Verify you're in the right place
pwd
```

**✅ Success indicator:** The `pwd` command should output: `/mnt/user/appdata/voice-capture`

**⚠️ Troubleshooting — git not found:**
```bash
# Install git via Nerd Tools plugin, or use this one-liner:
curl -L https://github.com/davistroy/voice-capture/archive/main.tar.gz | tar xz -C /mnt/user/appdata/voice-capture --strip-components=1
```

#### Step 3: Create and Configure .env File

```bash
# Copy the example environment file
cp .env.example .env

# Edit with nano (pre-installed on UNRAID)
nano .env
```

**In the nano editor:**
1. Use arrow keys to navigate
2. Delete placeholder values and type your real API keys
3. When done: Press **Ctrl+O** (write out), then **Enter** to confirm, then **Ctrl+X** to exit

**Required values to fill in:**
```env
OPENAI_API_KEY=sk-your-actual-openai-key
ANTHROPIC_API_KEY=sk-ant-your-actual-anthropic-key
NOTION_API_KEY=secret_your-actual-notion-key
PUSHOVER_API_TOKEN=your-actual-pushover-token
PUSHOVER_USER_KEY=your-actual-pushover-user-key
NOTION_VOICE_CAPTURES_DB_ID=your-32-character-database-id
NOTION_WEEKLY_SUMMARIES_DB_ID=your-32-character-database-id
```

**Verify the file was saved:**
```bash
cat .env | head -5
```
You should see your filled-in values (not the placeholders).

### 8.4 Configure rclone for Google Drive (Headless Mode)

UNRAID servers typically don't have a GUI browser, so you'll use headless authentication.

#### Step 1: Start rclone Configuration

```bash
cd /mnt/user/appdata/voice-capture
./scripts/rclone/setup.sh --headless
```

**What you'll see:**
```
No existing rclone config found. Starting interactive setup...

This is a headless server. You'll need to authenticate on another device.
```

#### Step 2: Authenticate via Another Computer

The script will display something like:

```
1. On a computer with a browser, run:
   rclone authorize "drive"

2. Complete the Google sign-in in your browser

3. Copy the token that appears and paste it here when prompted
```

**On your laptop/desktop (not the UNRAID server):**

1. Install rclone if needed:
   - **Mac:** `brew install rclone`
   - **Windows:** Download from rclone.org/downloads
   - **Linux:** `sudo apt install rclone` or `curl https://rclone.org/install.sh | sudo bash`

2. Run the authorize command:
   ```bash
   rclone authorize "drive"
   ```

3. A browser window opens automatically
4. Sign in to your Google account
5. Click **Allow** to grant rclone access to Google Drive
6. **What you'll see in the terminal:** A JSON blob starting with `{"access_token":`

7. **Copy the entire JSON blob** (from `{` to `}`, including the braces)

#### Step 3: Paste the Token in UNRAID

1. Go back to your UNRAID terminal
2. When prompted "Paste your token here:", paste the JSON blob
3. Press **Enter**

**✅ Success indicator:**
```
Remote "gdrive" configured successfully!
Testing connection...
Connected to Google Drive as: yourname@gmail.com
Creating /VoiceCaptures/inbox folder...
Done! rclone is ready.
```

#### Step 4: Verify rclone Works

```bash
# List your Google Drive root
rclone ls gdrive: --max-depth 1

# Verify the VoiceCaptures folder exists
rclone ls gdrive:/VoiceCaptures/inbox
```

**✅ Success indicator:** No errors. The inbox folder may be empty (which is fine) or show test files if you created any.

**⚠️ Troubleshooting:**

| Problem | Solution |
|---------|----------|
| "Failed to configure token" | Make sure you copied the complete JSON including braces |
| "Connection refused" | Check your UNRAID has internet access: `ping google.com` |
| Token expired during setup | Start over with `./scripts/rclone/setup.sh --headless` |
| Permission denied errors | Run `chmod +x ./scripts/rclone/setup.sh` first |

### 8.5 Add Stack to Docker Compose Manager

#### Step 1: Open Docker Compose Manager

1. In UNRAID web UI, click the **Docker** tab
2. At the bottom, click **"Compose"** (or look for it in the left sidebar depending on your UNRAID version)
3. You'll see the Docker Compose Manager interface

**What you should see:** A page titled "Docker Compose Manager" with options to add new stacks.

#### Step 2: Add New Stack

1. Click **"Add New Stack"** button
2. Fill in the form:
   - **Name:** `voice-capture` (no spaces, lowercase)
   - **Description:** `Voice capture to Notion pipeline` (optional)

3. For **Compose File Location**, you have two options:

**Option A — Point to existing file (Recommended):**
- Select **"Use existing compose file"** or **"Custom path"**
- Enter path: `/mnt/user/appdata/voice-capture/docker-compose.yml`

**Option B — Copy/paste compose content:**
- Select **"Edit compose file"** or similar
- Copy the entire contents of `docker-compose.yml` and paste it

4. Click **"Save"** or **"Add Stack"**

**✅ Success indicator:** The stack appears in your list of compose stacks.

#### Step 3: Configure Stack Environment

1. Find your `voice-capture` stack in the list
2. Click on it to open stack details
3. Look for **"Env File"** or **"Environment"** settings
4. Set the env file path to: `/mnt/user/appdata/voice-capture/.env`
5. Save changes

### 8.6 Start the Stack

1. In Docker Compose Manager, find your `voice-capture` stack
2. Click the **"Compose Up"** button (usually a play icon or "Start" button)
3. **What you should see:** A log window showing containers being created:
   ```
   Creating network "voice-capture_default" with the default driver
   Creating voice-capture_rclone_1 ... done
   Creating voice-capture_voice-capture_1 ... done
   ```

4. Wait for startup to complete (30-60 seconds)

#### Verify Containers Are Running

**In UNRAID Web UI:**
1. Go to **Docker** tab
2. You should see two new containers:
   - `voice-capture` (the main application)
   - `rclone` (Google Drive sync service)
3. Both should show a **green "running"** status

**Via Terminal:**
```bash
cd /mnt/user/appdata/voice-capture
docker-compose ps
```

**✅ Success indicator:**
```
        Name                       Command               State   Ports
-----------------------------------------------------------------------
voice-capture_rclone_1          /entrypoint.sh              Up
voice-capture_voice-capture_1   python -m src.main          Up
```

**⚠️ Troubleshooting — Container won't start:**

```bash
# Check logs for errors
docker-compose logs voice-capture

# Common issues:
# - "OPENAI_API_KEY not set" → Check your .env file
# - "Cannot connect to Notion" → Verify database ID and API key
# - "Permission denied" → Run: chmod -R 755 /mnt/user/appdata/voice-capture
```

### 8.7 Configure Persistent Storage Paths

By default, the containers use Docker volumes. For easier backup and access on UNRAID, modify the paths.

#### Step 1: Stop the Stack

```bash
cd /mnt/user/appdata/voice-capture
docker-compose down
```

#### Step 2: Create Local Directories

```bash
mkdir -p /mnt/user/appdata/voice-capture/data
mkdir -p /mnt/user/appdata/voice-capture/logs
mkdir -p /mnt/user/appdata/voice-capture/inbox
mkdir -p /mnt/user/appdata/voice-capture/rclone-config
```

#### Step 3: Edit docker-compose.yml

```bash
nano docker-compose.yml
```

Find the `volumes` section for the `voice-capture` service and modify it:

```yaml
services:
  voice-capture:
    # ... other settings ...
    volumes:
      - /mnt/user/appdata/voice-capture/data:/app/data
      - /mnt/user/appdata/voice-capture/logs:/app/logs
      - /mnt/user/appdata/voice-capture/inbox:/app/inbox
      - /mnt/user/appdata/voice-capture/config:/app/config:ro

  rclone:
    # ... other settings ...
    volumes:
      - /mnt/user/appdata/voice-capture/rclone-config:/config/rclone
      - /mnt/user/appdata/voice-capture/inbox:/data/inbox
      - /mnt/user/appdata/voice-capture/logs:/data/logs
```

Save with **Ctrl+O**, **Enter**, **Ctrl+X**.

#### Step 4: Copy rclone Config (If Not Already There)

```bash
# If you configured rclone earlier, copy its config
cp ~/.config/rclone/rclone.conf /mnt/user/appdata/voice-capture/rclone-config/
```

#### Step 5: Restart the Stack

```bash
docker-compose up -d
```

### 8.8 Set Up Auto-Start on UNRAID Boot

Docker Compose Manager stacks should auto-start by default. Verify this:

1. Go to **Settings → Docker** in UNRAID
2. Ensure **"Preserve user defined networks"** is set to **Yes**
3. In Docker Compose Manager, check your stack settings for an **"Auto Start"** toggle — ensure it's enabled

**To test:**
```bash
# Simulate a reboot by restarting Docker
/etc/rc.d/rc.docker restart

# Wait 30 seconds, then check
docker-compose -f /mnt/user/appdata/voice-capture/docker-compose.yml ps
```

### 8.9 UNRAID-Specific Monitoring

#### View Logs in UNRAID Web UI

1. Go to **Docker** tab
2. Click on `voice-capture` container
3. Click **"Log"** button
4. **What you should see:** Real-time application logs

#### Set Up Log Rotation (Recommended)

UNRAID doesn't rotate Docker logs by default. Add this to prevent disk fill:

```bash
nano /mnt/user/appdata/voice-capture/docker-compose.yml
```

Add under each service:
```yaml
services:
  voice-capture:
    # ... other settings ...
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 8.10 Backup Strategy for UNRAID

#### What to Back Up

| Path | Contents | Backup Priority |
|------|----------|----------------|
| `/mnt/user/appdata/voice-capture/.env` | API keys and secrets | **Critical** |
| `/mnt/user/appdata/voice-capture/data/voice_capture.db` | Processing history | High |
| `/mnt/user/appdata/voice-capture/rclone-config/rclone.conf` | Google Drive auth | High |
| `/mnt/user/appdata/voice-capture/config/` | Template customizations | Medium |

#### Simple Backup Script

Create `/mnt/user/appdata/voice-capture/backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/mnt/user/backups/voice-capture"
DATE=$(date +%Y%m%d)

mkdir -p "$BACKUP_DIR"

# Backup critical files
tar -czf "$BACKUP_DIR/voice-capture-$DATE.tar.gz" \
  -C /mnt/user/appdata/voice-capture \
  .env \
  data/voice_capture.db \
  rclone-config/rclone.conf \
  config/

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/voice-capture-*.tar.gz | tail -n +8 | xargs -r rm

echo "Backup complete: $BACKUP_DIR/voice-capture-$DATE.tar.gz"
```

Make it executable and add to User Scripts plugin for weekly runs:
```bash
chmod +x /mnt/user/appdata/voice-capture/backup.sh
```

### 8.11 UNRAID Troubleshooting Reference

| Issue | Diagnosis | Solution |
|-------|-----------|----------|
| Container keeps restarting | `docker logs voice-capture` | Check for API key errors or missing config |
| rclone not syncing | Check rclone container logs | Re-run setup script, refresh OAuth token |
| High CPU usage | Check if stuck processing | Restart container, check for corrupt audio files |
| Database locked errors | Multiple container instances | Ensure only one voice-capture container runs |
| Files not appearing in inbox | Check rclone sync | `docker exec rclone rclone ls gdrive:/VoiceCaptures/inbox` |
| After UNRAID update, stack gone | Docker Compose Manager reset | Re-add the stack using steps in 8.5 |
| Permission denied on /app/data | Volume permissions | `chmod -R 777 /mnt/user/appdata/voice-capture/data` |

#### Useful UNRAID Terminal Commands

```bash
# Check container status
docker ps -a | grep voice

# View real-time logs
docker logs -f voice-capture_voice-capture_1

# Enter container for debugging
docker exec -it voice-capture_voice-capture_1 bash

# Check disk usage
du -sh /mnt/user/appdata/voice-capture/*

# Test rclone from within container
docker exec voice-capture_rclone_1 rclone ls gdrive:/VoiceCaptures/inbox

# Force sync now
docker exec voice-capture_rclone_1 rclone sync gdrive:/VoiceCaptures/inbox /data/inbox

# Restart just the voice-capture service
cd /mnt/user/appdata/voice-capture && docker-compose restart voice-capture
```

---

## Part 9: Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Files not syncing from Drive | Run `rclone ls gdrive:/VoiceCaptures/inbox` to test. Reconnect with `rclone config reconnect gdrive:` |
| Transcription failing | Check OpenAI API key and billing. Verify audio format is M4A/WAV/MP3 |
| Classification wrong template | Adjust confidence threshold in `config/classification.yaml`. Check trigger patterns in templates |
| Notion page not created | Verify database ID and integration has access. Check rate limiting in logs |
| No notifications | Verify Pushover tokens. Test with `python -m src.cli.health_check` |

### View Logs

```bash
# All services
docker-compose logs -f

# Voice capture only
docker-compose logs -f voice-capture

# rclone sync only
docker-compose logs -f rclone

# Check rclone log file
docker-compose exec rclone cat /data/logs/rclone.log
```

### Database Inspection

```bash
# Enter container
docker-compose exec voice-capture bash

# Use sqlite3
sqlite3 /app/data/voice_capture.db
> SELECT id, filename, status, retry_count FROM captures ORDER BY id DESC LIMIT 10;
> SELECT * FROM failure_log ORDER BY id DESC LIMIT 5;
> .quit
```

---

## Part 10: Maintenance

### Regular Tasks

| Task | Frequency | Command |
|------|-----------|---------|
| Check health | Daily (automatic) | Pushover notification |
| Review failed captures | Weekly | `python -m src.cli.queue_status` |
| Update Docker images | Monthly | `docker-compose pull && docker-compose up -d` |
| Refresh OAuth tokens | As needed | `rclone config reconnect gdrive:` |
| Backup database | Weekly | Copy `voice_capture.db` from data volume |

### Updating the System

```bash
cd voice-capture
git pull
docker-compose build
docker-compose up -d
```

---

## Quick Reference Card

```
CAPTURE:     Tap Watch complication → Speak → Tap to stop
MONITOR:     docker-compose logs -f voice-capture
QUEUE:       docker-compose exec voice-capture python -m src.cli.queue_status
RETRY:       docker-compose exec voice-capture python -m src.cli.retry --all-failed
HEALTH:      docker-compose exec voice-capture python -m src.cli.health_check
SYNTHESIS:   claude "Run weekly-voice-synthesis"
```

---

## Architecture Diagram

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Apple Watch    │     │    iPhone       │     │  Just Press     │
│  Complication   │────▶│    Shortcut     │────▶│    Record       │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │  Google Drive   │
                                               │ /VoiceCaptures/ │
                                               │     inbox/      │
                                               └────────┬────────┘
                                                         │ rclone sync
                                                         ▼
┌────────────────────────────────────────────────────────────────────┐
│                        Docker Host (UNRAID)                        │
│  ┌──────────────┐     ┌──────────────────────────────────────┐    │
│  │   rclone     │────▶│         voice-capture                │    │
│  │   service    │     │  ┌────────┐  ┌────────┐  ┌────────┐ │    │
│  └──────────────┘     │  │Watcher │─▶│Whisper │─▶│Claude  │ │    │
│                       │  └────────┘  │  API   │  │  API   │ │    │
│                       │              └────────┘  └───┬────┘ │    │
│                       │                              │      │    │
│                       │              ┌───────────────▼────┐ │    │
│                       │              │    Notion API      │ │    │
│                       │              └────────────────────┘ │    │
│                       └──────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │     Notion      │
                                               │ Voice Captures  │
                                               │    Database     │
                                               └─────────────────┘
```

---

*Guide version: 1.0.0 | Last updated: 2026-01-21*
