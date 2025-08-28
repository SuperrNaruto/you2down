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

## 系统简化优化记录 (2025-08-27)

**问题**: Instagram模块过度复杂，包含不必要的多账号负载均衡、IP轮换等企业级功能，增加了维护负担和资源消耗。

**简化方案**:
1. **删除过度复杂组件**:
   - 移除 `instagram_account_manager.py` - 多账号管理器
   - 简化 `instagram_client.py` - 移除代理轮换、IP轮换、复杂错误分析
   - 清理 `config.py` - 移除多账号和代理轮换配置项
   - 简化 `scheduler.py` - 去除复杂的初始化逻辑

2. **代码质量提升**:
   - 减少约500行冗余代码
   - 移除不必要的复杂性和抽象
   - 保留核心功能：Instagram收藏视频下载
   - 保持基础重试和错误处理机制

3. **性能改进**:
   - 减少内存占用（移除多余管理器和缓存）
   - 提升启动速度（减少组件初始化时间）
   - 提高稳定性（减少出错点和复杂交互）

**核心原则**: 专注本质功能，移除过度工程化，提升代码质量和可维护性。

## Instagram功能优化记录 (2025-08-27)

**问题**: Instagram收藏功能由于API限制无法正常工作，遇到401认证错误和速率限制。

**解决方案**: 改用点赞功能替代收藏功能
1. **技术实现**:
   - 使用 `instaloader` 的 feed + `viewer_has_liked` 过滤器
   - 通过 `get_feed_posts()` 获取关注的人的帖子
   - 过滤出用户点赞过的视频内容
   - 保持原有的API接口兼容性

2. **核心修改**:
   - `instagram_client.py`: 新增 `get_liked_posts()` 方法实现点赞视频获取
   - 保留 `get_saved_media()` 作为兼容方法，内部调用点赞功能
   - 增加扫描范围限制，避免无限循环（最多扫描 limit×10 个帖子）

3. **优势**:
   - 避开Instagram对收藏API的严格限制
   - 利用feed功能相对较松的访问控制
   - 用户体验基本一致（都是获取感兴趣的内容）
   - 保持代码架构和调用方式不变

**配置更新**: 已重新启用Instagram功能 (`ENABLE_INSTAGRAM=true`)，现在下载点赞过的视频而非收藏的视频。

## Cookie认证系统 (2025-08-27)

**问题**: VPS环境中无法使用浏览器手动登录Instagram，导致认证困难。

**解决方案**: 实现多层级cookie认证系统
1. **Cookie文件支持**:
   - 支持JSON、Netscape、键值对三种cookie格式
   - 自动解析和验证cookie有效性
   - 优先使用cookie文件进行认证（最稳定）

2. **认证优先级**:
   - Cookie文件 → Session文件 → 用户名密码
   - 多层fallback机制确保认证成功率

3. **自动维护**:
   - 自动检测cookie过期状态
   - 401错误时自动重新加载认证
   - 支持热更新cookie文件

4. **VPS部署优化**:
   - 完全兼容无头环境
   - 详细的cookie导入指南
   - 安全的文件权限控制

**技术实现**:
- `instagram_client.py`: 新增 `_load_cookies_from_file()`, `_parse_cookies()`, `_validate_cookies()` 方法
- `config.py`: 新增 `instagram_cookie_file` 配置项
- 完整的cookie格式兼容性和错误处理机制

**使用方法**: 参考 `INSTAGRAM_COOKIE_GUIDE.md` 详细指南