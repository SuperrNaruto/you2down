# YouTube视频自动下载上传系统

一个基于Python的YouTube视频自动下载上传系统，可以监控YouTube播放列表，自动下载新视频并上传到Alist云存储，支持Telegram通知。

## ✨ 特性

- 🎬 **自动监控** - 定时检查YouTube播放列表更新
- ⬇️ **高效下载** - 使用yt-dlp进行视频下载，支持并发处理
- ☁️ **自动上传** - 下载完成后自动上传到Alist云存储
- 📱 **实时通知** - 通过Telegram Bot发送处理状态通知
- 🔄 **智能重试** - 失败任务自动重试机制
- 🐳 **容器化** - Docker单容器部署，简单易用
- 📊 **状态监控** - 支持查看系统状态和统计信息

## 🏗️ 系统架构

```
app/
├── main.py              # 主入口
├── config.py            # 配置管理
├── youtube_client.py    # YouTube API客户端
├── alist_client.py      # Alist API客户端
├── telegram_bot.py      # Telegram通知和重试
├── downloader.py        # 下载管理
├── uploader.py          # 上传管理
├── database.py          # SQLite数据库
└── scheduler.py         # 任务调度
```

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone <repository_url>
cd you2down
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的配置信息
```

### 3. 使用Docker运行

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## ⚙️ 配置说明

### 必需配置

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `YOUTUBE_API_KEY` | YouTube Data API v3密钥 | `AIzaSyC...` |
| `BOT_TOKEN` | Telegram Bot Token | `123456:ABC-DEF...` |
| `CHAT_ID` | Telegram Chat ID | `123456789` |
| `ALIST_SERVER` | Alist服务器地址 | `https://alist.example.com` |
| `ALIST_USERNAME` | Alist用户名 | `admin` |
| `ALIST_PASSWORD` | Alist密码 | `password` |
| `PLAYLISTS` | YouTube播放列表ID | `PLrAXtmRdnEQy4VqEemQ...` |

### 可选配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `CHECK_INTERVAL` | `1800` | 检查间隔(秒) |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | 最大并发下载数 |
| `DOWNLOAD_PATH` | `/app/downloads` | 下载目录 |
| `ALIST_PATH` | `/videos` | Alist上传路径 |
| `VIDEO_QUALITY` | `best` | 视频质量(best/4k/1080p/720p/480p) |
| `LOG_LEVEL` | `INFO` | 日志级别 |

### 🎥 视频质量说明

系统支持灵活的视频质量控制，通过 `VIDEO_QUALITY` 参数设置：

- **best**: 最高可用质量，包括4K、8K等超高清视频
- **4k**: 限制最高为4K分辨率(2160p)
- **1080p**: 限制最高为1080p全高清
- **720p**: 限制最高为720p高清  
- **480p**: 限制最高为480p标清

yt-dlp会自动选择指定质量范围内的最佳视频和音频组合，并合并为MP4格式。

## 📋 使用步骤

### 1. 获取YouTube API密钥

1. 访问 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建项目或选择现有项目
3. 启用 "YouTube Data API v3"
4. 创建API密钥

### 2. 创建Telegram Bot

1. 向 [@BotFather](https://t.me/BotFather) 发送 `/newbot`
2. 按提示创建Bot并获取Token
3. 获取你的Chat ID（可以向 [@userinfobot](https://t.me/userinfobot) 发送消息获取）

### 3. 获取YouTube播放列表ID

从播放列表URL中提取ID：
```
https://www.youtube.com/playlist?list=PLrAXtmRdnEQy4VqEemQ...
                                      ↑ 这部分就是播放列表ID
```

## 🔧 开发

### 本地开发环境

```bash
# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 运行
python app/main.py
```

### 项目结构

- `app/` - 主要代码目录
- `downloads/` - 视频下载临时目录
- `data/` - SQLite数据库存储
- `logs/` - 日志文件

## 📊 系统监控

### Telegram命令

- `/start` - 启动Bot
- `/status` - 查看系统状态
- `/stats` - 查看统计信息

### 自动通知

- 🚀 系统启动/停止通知
- 🔄 下载开始/完成通知
- ⬆️ 上传开始/完成通知
- ❌ 失败任务通知（带重试按钮）
- 📊 每日统计报告

## 🛠️ 故障排除

### 常见问题

1. **YouTube API配额不足**
   - 检查Google Cloud Console中的API使用情况
   - YouTube Data API v3每日配额默认为10,000单位

2. **下载失败**
   - 检查网络连接
   - 确认视频可访问性
   - 查看yt-dlp版本是否最新

3. **上传失败**
   - 验证Alist服务器连接
   - 检查用户权限和存储空间
   - 确认上传路径存在

### 日志查看

```bash
# Docker日志
docker-compose logs you2down

# 文件日志
tail -f logs/app.log
```

## 🔒 安全建议

1. **保护敏感信息**
   - 不要在代码中硬编码API密钥
   - 使用 `.env` 文件管理配置
   - 不要提交 `.env` 文件到版本控制

2. **网络安全**
   - 使用HTTPS连接Alist服务器
   - 定期更新依赖包
   - 监控系统日志

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request来改进项目！

## 📞 支持

如果遇到问题，请：

1. 查看日志文件
2. 检查配置是否正确
3. 提交Issue并附上相关日志