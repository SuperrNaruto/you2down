# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube视频自动下载上传系统 - A Python-based automated YouTube video downloading and uploading system. The system monitors YouTube playlists, automatically downloads new videos using yt-dlp, uploads to Alist cloud storage, and provides real-time Telegram notifications.

## Core Architecture

### System Components
The system follows a modular async architecture with clear separation of concerns:

- **main.py**: `YouTubeDownloadSystem` orchestrates all components with proper lifecycle management
- **scheduler.py**: `TaskScheduler` uses APScheduler for periodic tasks (playlist checks, queue processing, cleanup)
- **config.py**: Pydantic-based configuration management with environment variable binding
- **database.py**: SQLite with async operations for video/playlist state tracking
- **downloader.py**: yt-dlp wrapper with concurrent download management and quality control
- **uploader.py**: Alist API client with retry logic and local file cleanup
- **telegram_bot.py**: Aiogram-based notification system with interactive retry buttons
- **youtube_client.py**: YouTube Data API v3 client for playlist monitoring

### Data Flow
1. Scheduler periodically checks YouTube playlists for new videos
2. New videos are queued in SQLite database with "pending" status
3. Downloader processes queue with configurable concurrency limits
4. Successfully downloaded videos trigger upload to Alist
5. Completed uploads clean up local files and update database status
6. Telegram notifications sent at each stage with retry mechanisms

### Configuration System
Uses Pydantic BaseSettings with `.env` file support. Critical configs:
- `PLAYLISTS`: Comma-separated YouTube playlist IDs
- `VIDEO_QUALITY`: best/4k/1080p/720p/480p (controls yt-dlp format selection)
- `MAX_CONCURRENT_DOWNLOADS`: Controls async semaphore limits
- `CHECK_INTERVAL`: Playlist monitoring frequency

## Development Commands

### Local Development
```bash
# Setup environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run locally (requires .env configuration)
python app/main.py
```

### Docker Development
```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f you2down

# Stop and cleanup
docker-compose down

# Rebuild after code changes
docker-compose build --no-cache
```

### Configuration Setup
```bash
# Create environment file
cp .env.example .env
# Edit .env with actual API keys and configuration
```

## Key Implementation Details

### Async Architecture
- All I/O operations use async/await pattern
- Semaphores control concurrency (downloads, uploads)
- AsyncIOScheduler manages periodic tasks
- Proper session management for aiohttp clients

### Error Handling & Retry Logic
- Database tracks retry counts with exponential backoff
- Telegram provides interactive retry buttons
- Failed tasks automatically retry up to 3 times
- Cleanup jobs handle orphaned files and failed uploads

### Video Quality Management
The `_get_quality_format()` method in downloader.py maps user-friendly quality settings to yt-dlp format strings:
- "best" → "bestvideo+bestaudio/best" (supports 4K/8K)
- "4k" → "bestvideo[height<=2160]+bestaudio/best[height<=2160]"
- Lower resolutions follow similar pattern

### Database Schema
- `videos` table: Tracks individual video processing state with retry counts
- `playlists` table: Stores last check timestamps for incremental updates
- All operations use async SQLite with proper locking

### Monitoring & Observability
- Structured logging with configurable levels
- Telegram commands for status checking (/status, /stats)
- Daily summary reports with processing statistics
- Health check endpoint on port 8080

## Testing Notes

This system requires external API integrations (YouTube, Telegram, Alist) so testing typically requires:
- Valid API credentials in test environment
- Network connectivity to external services
- Consider using test playlists and isolated Alist storage paths

The modular architecture allows for unit testing individual components by mocking the async clients and database operations.

## Troubleshooting & Debugging Experience

### Alist API Integration Issues (2025-08-23)

**Problem**: After Pydantic v2 migration, the system faced "token is invalidated" errors when calling Alist API, despite successful login.

**Root Cause Analysis**:
- Initially suspected session management issues
- Investigated multiple potential causes: cookie handling, session consistency, token format
- **Actual Issue**: Alist API uses non-standard authentication header format

**Solution**:
```python
# ❌ Wrong (Standard Bearer Token format)
headers = {"Authorization": f"Bearer {token}"}

# ✅ Correct (Alist-specific format) 
headers = {"Authorization": token}  # Direct token value, no Bearer prefix
```

**Key Learning Points**:
1. **API Documentation vs Reality**: Official API docs may not always reflect exact implementation details
2. **Authentication Formats Vary**: Not all APIs follow RFC 6750 Bearer token standards
3. **Systematic Testing**: Test different auth formats when standard approaches fail
4. **Storage Path Validation**: Always verify target paths exist and have write permissions

**Debugging Process**:
1. ✅ Verified token generation works (login successful)
2. ✅ Tested session consistency (not the issue)
3. ✅ Checked HTTP headers and network calls
4. ✅ Discovered auth format difference through systematic testing
5. ✅ Validated storage path availability (`/115` instead of `/videos`)

**Prevention Strategies**:
- Always test API authentication with minimal examples first
- Create isolated test scripts to validate API behavior
- Check server-specific documentation beyond generic API standards
- Verify storage/path configurations before integration testing

**Files Modified**:
- `app/alist_client.py`: Fixed all Authorization header formats
- `.env`: Updated ALIST_PATH from `/videos` to `/115`
- Added comprehensive test scripts for validation

This experience demonstrates the importance of not assuming standard API behavior and systematically testing external service integrations.