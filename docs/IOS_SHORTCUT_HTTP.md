# iOS Shortcut for HTTP Direct Upload

This guide covers creating an iOS Shortcut that uploads voice recordings directly to your Voice Capture server via HTTP, bypassing the Google Drive/rclone sync path for lower latency.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Creating the Shortcut](#creating-the-shortcut)
4. [Apple Watch Setup](#apple-watch-setup)
5. [Async Upload Shortcut (Alternative)](#async-upload-shortcut-alternative)
6. [Troubleshooting](#troubleshooting)
7. [Reference](#reference)

---

## Overview

### Two Capture Paths

| Path | Latency | How It Works |
|------|---------|--------------|
| Google Drive + rclone | 2-5 minutes | iOS saves to Drive, rclone syncs every 60-180s |
| **HTTP Direct Upload** | 5-15 seconds | iOS POSTs directly to server via Tailscale |

The HTTP path provides immediate feedback - your shortcut will show success/failure and include a direct link to the Notion page.

### Architecture

```
┌─────────────┐    HTTP POST     ┌─────────────────┐
│   iPhone    │ ───────────────► │  Voice Capture  │
│  (Tailscale)│   via Tailscale  │     Server      │
└─────────────┘                  └────────┬────────┘
                                          │
                                          ▼
                                 ┌─────────────────┐
                                 │     Notion      │
                                 └─────────────────┘
```

---

## Prerequisites

Before creating the shortcut, ensure you have:

### On Your iPhone

- [ ] **Tailscale app** installed and connected to your tailnet
- [ ] **Just Press Record app** installed (or another recording app)
- [ ] **Shortcuts app** (pre-installed on iOS)

### On Your Server

- [ ] HTTP server enabled (`HTTP_ENABLED=true` in `.env`)
- [ ] Server accessible via Tailscale
- [ ] Know your server's Tailscale hostname or IP

### Get Your Server Details

```bash
# On your server, find your Tailscale hostname
tailscale status

# Example output:
# 100.64.0.1    my-server    davistroy@ linux   -
# The hostname is "my-server" and IP is "100.64.0.1"
```

You can use either the hostname (e.g., `http://my-server:8080`) or the IP (e.g., `http://100.64.0.1:8080`).

---

## Creating the Shortcut

### Step 1: Create New Shortcut

1. Open **Shortcuts** app on iPhone
2. Tap **+** in the top right to create a new shortcut
3. Tap the title ("New Shortcut") and rename to **Voice Capture (HTTP)**

### Step 2: Add Recording Actions

**Action 1: Start New Recording**

1. Tap **Add Action** or search at bottom
2. Search: `Just Press Record`
3. Select: **Start New Recording**

**Action 2: Wait to Return**

1. Tap **+** to add next action
2. Search: `Wait to Return`
3. Select: **Wait to Return** (under Scripting)

**Action 3: Get Latest Recording**

1. Tap **+** to add next action
2. Search: `Just Press Record`
3. Select: **Get Latest Recording**

### Step 3: Add HTTP Upload Action

**Action 4: Get Contents of URL**

1. Tap **+** to add next action
2. Search: `Get Contents of URL`
3. Select: **Get Contents of URL**

Configure it as follows:

**URL:**
```
http://YOUR-TAILSCALE-HOSTNAME:8080/api/v1/capture?wait=true
```
Replace `YOUR-TAILSCALE-HOSTNAME` with your actual Tailscale hostname or IP.

**Method:** `POST`

**Headers:** Tap "Add new header"
- **Key:** `X-API-Key`
- **Text:** Your API key (the value of `HTTP_API_KEY` in your `.env`)

> **Note:** If you didn't set an API key, skip the header.

**Request Body:** Select `Form`

Add form fields:

| Key | Value | Type |
|-----|-------|------|
| `audio` | Select "Latest Recording" (magic variable from step 3) | File |
| `device` | `phone` | Text |

To select the magic variable:
1. Tap the value field
2. Tap **Select Variable** (or tap the magic wand icon)
3. Select **Latest Recording** from the previous action

### Step 4: Add Response Handling

**Action 5: Get Dictionary Value (check success)**

1. Tap **+** to add action
2. Search: `Get Dictionary Value`
3. Configure:
   - **Get:** `success`
   - **from:** Contents of URL (auto-selected)

**Action 6: If Statement**

1. Tap **+** to add action
2. Search: `If`
3. Configure: **If** Dictionary Value **is** 1

**Action 7: (Inside If - Success) Get Notion URL**

1. Inside the "If" block, tap **+**
2. Search: `Get Dictionary Value`
3. Configure:
   - **Get:** `notion_url`
   - **from:** Contents of URL

**Action 8: (Inside If - Success) Show Notification**

1. Tap **+** to add action
2. Search: `Show Notification`
3. Configure:
   - **Title:** `Captured!`
   - **Body:** Tap, then select **Dictionary Value** (notion_url)
   - Under **More**, enable: **Sound**, **Attachment** (select notion_url)

**Action 9: (Otherwise - Failure) Get Error Message**

1. In the "Otherwise" section, tap **+**
2. Search: `Get Dictionary Value`
3. Configure:
   - **Get:** `message`
   - **from:** Contents of URL

**Action 10: (Otherwise - Failure) Show Notification**

1. Tap **+** to add action
2. Search: `Show Notification`
3. Configure:
   - **Title:** `Capture Failed`
   - **Body:** Select **Dictionary Value** (message)

### Step 5: Add Final Feedback (Optional)

After the "End If", add:

**Action 11: Vibrate Device**

1. Tap **+** (after the End If)
2. Search: `Vibrate Device`
3. Select it

### Step 6: Save and Test

1. Tap **Done** in the top right
2. Test by tapping the shortcut
3. Record a test message
4. Verify you get a notification with the Notion link

---

## Complete Shortcut Structure

Your shortcut should look like this:

```
┌─────────────────────────────────────────────────┐
│  Voice Capture (HTTP)                           │
├─────────────────────────────────────────────────┤
│  1. Start New Recording                         │
│     Just Press Record                           │
├─────────────────────────────────────────────────┤
│  2. Wait to Return                              │
├─────────────────────────────────────────────────┤
│  3. Get Latest Recording                        │
│     Just Press Record                           │
├─────────────────────────────────────────────────┤
│  4. Get Contents of URL                         │
│     POST http://my-server:8080/api/v1/capture   │
│     Headers: X-API-Key: [your-key]              │
│     Body: audio=[Recording], device=phone       │
├─────────────────────────────────────────────────┤
│  5. Get Dictionary Value                        │
│     Get success from Contents of URL            │
├─────────────────────────────────────────────────┤
│  6. If Dictionary Value is 1                    │
│  ├──────────────────────────────────────────────┤
│  │  7. Get Dictionary Value (notion_url)        │
│  │  8. Show Notification "Captured!"            │
│  ├──────────────────────────────────────────────┤
│  │  Otherwise                                   │
│  ├──────────────────────────────────────────────┤
│  │  9. Get Dictionary Value (message)           │
│  │  10. Show Notification "Capture Failed"      │
│  └──────────────────────────────────────────────┤
│  End If                                         │
├─────────────────────────────────────────────────┤
│  11. Vibrate Device                             │
└─────────────────────────────────────────────────┘
```

---

## Apple Watch Setup

### Enable on Watch

1. In Shortcuts app on iPhone, tap your shortcut
2. Tap the **...** menu (info button)
3. Scroll down and enable **Show on Apple Watch**

### Add to Watch Face

1. On Apple Watch, open the Shortcuts app
2. Verify your shortcut appears
3. Add it as a complication to your watch face

### Watch Limitations

- HTTP uploads require the iPhone to be reachable (nearby or on same network)
- For truly standalone Watch capture (no iPhone needed), use the Google Drive shortcut instead
- The Watch will use the iPhone as a network relay via Bluetooth/WiFi

### Device Field for Watch

If you want to track Watch vs Phone captures, create a second shortcut:

1. Duplicate the shortcut (tap and hold, select "Duplicate")
2. Rename to **Voice Capture Watch (HTTP)**
3. Change the `device` form field from `phone` to `watch`
4. Put this version on your Watch face

---

## Async Upload Shortcut (Alternative)

If you prefer not to wait for processing (faster response, no Notion link in notification):

### Modifications

Change the URL query parameter from `wait=true` to `wait=false`:

```
http://YOUR-TAILSCALE-HOSTNAME:8080/api/v1/capture?wait=false
```

### Simplified Response Handling

With async mode, the response is immediate:

```json
{
  "success": true,
  "capture_id": 42,
  "status": "pending"
}
```

You can simplify the shortcut to just show a "Recording submitted!" notification without the Notion URL.

### When to Use Async

- When network is slow and you don't want to wait
- When you're capturing many recordings quickly
- When you just want fire-and-forget behavior

---

## Troubleshooting

### Connection Issues

| Problem | Solution |
|---------|----------|
| "Could not connect to server" | Verify Tailscale is connected on iPhone. Check server is running. |
| "The request timed out" | Increase `HTTP_REQUEST_TIMEOUT_SECONDS` in server `.env`. |
| "Network connection was lost" | iPhone switched networks. Reconnect Tailscale. |

**Debug Tailscale connection:**

```bash
# On iPhone (Terminal app or SSH from another device)
ping YOUR-TAILSCALE-HOSTNAME

# Or test HTTP endpoint
curl http://YOUR-TAILSCALE-HOSTNAME:8080/health
```

### Authentication Errors

| Problem | Solution |
|---------|----------|
| "Unauthorized" (401) | Check `X-API-Key` header matches `HTTP_API_KEY` in server `.env`. |
| Header not being sent | Ensure header key is exactly `X-API-Key` (case-sensitive). |

### File Errors

| Problem | Solution |
|---------|----------|
| "No 'audio' field in request" | Check form body configuration. Audio file must be attached. |
| "Invalid audio format" | Ensure Just Press Record is set to M4A format in its settings. |
| "File exceeds maximum size" | Recording too long. Check `HTTP_MAX_UPLOAD_MB` setting. |

### Processing Errors

| Problem | Solution |
|---------|----------|
| "Processing failed" | Check server logs: `docker-compose logs voice-capture` |
| Timeout during processing | Increase timeout or use async mode (`wait=false`). |

### Shortcut Not Working

| Problem | Solution |
|---------|----------|
| "Wait to Return" never completes | Ensure you tap STOP in Just Press Record (don't swipe away). |
| No recording available | Just Press Record may need microphone permission. |
| Notification doesn't appear | Check Shortcuts has notification permission in Settings. |

### Check Server Status

From the server:

```bash
# Check HTTP server is running
docker-compose logs voice-capture | grep -i http

# Test health endpoint
curl http://localhost:8080/health

# Check recent uploads
docker-compose exec voice-capture python -m src.cli.queue_status
```

---

## Reference

### API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/api/v1/capture` | POST | Yes* | Upload audio |
| `/api/v1/capture/{id}` | GET | Yes* | Check status |

*If `HTTP_API_KEY` is configured

### Upload Request Format

```http
POST /api/v1/capture?wait=true HTTP/1.1
Host: your-server:8080
X-API-Key: your-api-key
Content-Type: multipart/form-data

--boundary
Content-Disposition: form-data; name="audio"; filename="recording.m4a"
Content-Type: audio/mp4

[binary audio data]
--boundary
Content-Disposition: form-data; name="device"

phone
--boundary--
```

### Response Format (Success, Sync)

```json
{
  "success": true,
  "capture_id": 42,
  "status": "complete",
  "template": "task",
  "notion_url": "https://notion.so/workspace/page-id",
  "processing_time_ms": 3450
}
```

### Response Format (Success, Async)

```json
{
  "success": true,
  "capture_id": 42,
  "status": "pending"
}
```

### Response Format (Error)

```json
{
  "success": false,
  "error": "invalid_audio_format",
  "message": "File must be M4A, MP3, WAV, or WEBM",
  "capture_id": null
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTP_ENABLED` | `false` | Enable HTTP server |
| `HTTP_PORT` | `8080` | Server port |
| `HTTP_API_KEY` | - | Optional authentication key |
| `HTTP_MAX_UPLOAD_MB` | `100` | Max file size |
| `HTTP_REQUEST_TIMEOUT_SECONDS` | `60` | Request timeout |

---

## See Also

- [Deployment Guide](DEPLOYMENT_GUIDE.md) - Full system setup
- [Part 4: iOS Capture Setup](DEPLOYMENT_GUIDE.md#part-4-ios-capture-setup) - Google Drive shortcut
- [Part 11: HTTP Upload Endpoint](DEPLOYMENT_GUIDE.md#part-11-http-upload-endpoint-alternative-ingestion) - Server configuration

---

*Last updated: 2026-01-24*
