# Instagram收藏视频下载功能

## 功能概述

YouTube视频自动下载上传系统现已支持Instagram收藏视频的自动下载功能。系统会定期检查您的Instagram收藏内容，自动下载收藏的视频并上传到Alist云存储。

## 核心特性

- **自动监控**: 定期检查Instagram收藏内容，发现新的收藏视频
- **智能去重**: 避免重复下载已处理的视频
- **并发下载**: 支持多个视频同时下载，提高效率
- **云端备份**: 自动上传到Alist云存储，节省本地空间
- **实时通知**: 通过Telegram机器人发送下载和上传状态通知
- **错误重试**: 自动重试失败的下载任务
- **质量控制**: 支持多种视频质量选择

## 技术实现

### 架构组件

```
Instagram模块架构:
├── instagram_client.py     # Instagram API客户端，基于instaloader
├── instagram_downloader.py # 视频下载器，使用yt-dlp
├── database.py            # 数据库扩展（Instagram表）
└── scheduler.py           # 调度器集成
```

### 工作流程

1. **收藏检查**: 使用instaloader获取用户收藏的媒体内容
2. **内容过滤**: 只处理视频类型的媒体，忽略图片
3. **数据库记录**: 将新发现的收藏视频信息存储到数据库
4. **下载队列**: 使用yt-dlp下载Instagram视频
5. **云端上传**: 自动上传到配置的Alist路径
6. **清理工作**: 删除本地临时文件，更新数据库状态

## 配置说明

### 环境变量配置

```bash
# Instagram功能开关
ENABLE_INSTAGRAM=true

# Instagram登录凭据
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password

# 会话文件路径（用于保存登录状态）
INSTAGRAM_SESSION_FILE=/app/data/instagram_session.json

# 下载配置
INSTAGRAM_DOWNLOAD_PATH=/app/downloads/instagram
INSTAGRAM_CHECK_INTERVAL=3600  # 检查间隔(秒)，默认1小时
MAX_INSTAGRAM_CONCURRENT=2     # 最大并发下载数

# 云端上传配置
INSTAGRAM_UPLOAD_TO_ALIST=true
INSTAGRAM_QUALITY=best         # 视频质量: best, 720p, 480p
```

### Docker Compose配置

系统会自动从环境变量读取配置，无需额外修改Docker Compose文件。确保在`.env`文件中正确设置Instagram相关配置。

## 安全注意事项

### 账号安全

1. **强密码**: 使用强密码保护Instagram账号
2. **双因素认证**: 建议启用Instagram双因素认证
3. **会话管理**: 系统会保存登录会话以避免频繁登录
4. **环境变量保护**: 确保`.env`文件不被上传到公共仓库

### 使用限制

1. **API限制**: Instagram对API访问有限制，避免过于频繁的请求
2. **私密账号**: 只能访问公开账号的内容
3. **收藏权限**: 需要账号登录才能访问收藏内容
4. **合规使用**: 遵守Instagram服务条款和版权法律

## 数据库结构

### Instagram媒体表 (instagram_media)

```sql
CREATE TABLE instagram_media (
    id TEXT PRIMARY KEY,              -- Instagram媒体ID
    shortcode TEXT NOT NULL UNIQUE,   -- 短代码，用于生成URL
    url TEXT NOT NULL,                -- Instagram帖子URL
    username TEXT NOT NULL,           -- 发布者用户名
    caption TEXT,                     -- 帖子标题/描述
    timestamp TIMESTAMP NOT NULL,     -- 发布时间
    status TEXT DEFAULT 'pending',    -- 状态: pending, downloaded, completed, failed
    file_path TEXT,                   -- 本地文件路径
    error_message TEXT,               -- 错误信息
    retry_count INTEGER DEFAULT 0,    -- 重试次数
    created_at TIMESTAMP,            -- 记录创建时间
    updated_at TIMESTAMP             -- 记录更新时间
);
```

### Instagram检查记录表 (instagram_checks)

```sql
CREATE TABLE instagram_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,           -- 检查的用户名
    last_checked TIMESTAMP NOT NULL, -- 最后检查时间
    media_count INTEGER DEFAULT 0,   -- 发现的媒体总数
    new_media_count INTEGER DEFAULT 0 -- 新发现的媒体数
);
```

## 使用指南

### 1. 启用功能

在`.env`文件中设置：
```bash
ENABLE_INSTAGRAM=true
INSTAGRAM_USERNAME=your_instagram_username
INSTAGRAM_PASSWORD=your_instagram_password
```

### 2. 重启系统

```bash
docker-compose down
docker-compose up -d
```

### 3. 监控日志

```bash
docker-compose logs -f youtube-downloader
```

### 4. Telegram通知

系统会通过Telegram机器人发送以下通知：
- 发现新的收藏视频
- 下载完成通知
- 上传完成通知
- 错误和重试通知

## 故障排除

### 常见问题

1. **登录失败**
   - 检查用户名和密码是否正确
   - 确认账号未被Instagram限制
   - 检查是否启用了双因素认证

2. **下载失败**
   - 检查网络连接是否正常
   - 确认视频是否为公开内容
   - 查看错误日志了解具体原因

3. **权限问题**
   - 确保Docker容器有足够的权限
   - 检查下载目录的写入权限
   - 验证Alist配置是否正确

### 调试方法

1. **查看详细日志**
   ```bash
   docker-compose logs youtube-downloader | grep -i instagram
   ```

2. **检查数据库状态**
   ```bash
   # 进入容器
   docker-compose exec youtube-downloader sh
   
   # 查看Instagram统计
   python3 -c "
   import asyncio
   from database import Database
   
   async def check_stats():
       db = Database('/app/data/app.db')
       await db.init()
       stats = await db.get_instagram_stats()
       print(stats)
   
   asyncio.run(check_stats())
   "
   ```

3. **测试Instagram连接**
   ```bash
   # 在容器内测试
   python3 -c "
   import asyncio
   from instagram_client import InstagramClient
   
   async def test_connection():
       client = InstagramClient('username', 'password')
       await client.init()
       print('连接成功')
   
   asyncio.run(test_connection())
   "
   ```

## 性能优化

### 推荐配置

- **检查间隔**: 1-4小时为宜，避免过于频繁
- **并发下载**: 2-3个为宜，避免触发限制
- **存储清理**: 定期清理本地下载文件
- **会话管理**: 合理设置会话文件权限

### 资源使用

- **CPU**: 下载和转码过程会使用CPU资源
- **内存**: 通常每个下载任务需要50-100MB内存
- **存储**: 临时文件会占用本地存储空间
- **网络**: 下载过程会消耗带宽资源

## 版权声明

使用本功能时，请遵守：
- Instagram服务条款
- 相关版权法律法规
- 内容创作者的权益
- 合理使用原则

本功能仅供个人学习和研究使用，请勿用于商业用途或侵犯他人权益的行为。