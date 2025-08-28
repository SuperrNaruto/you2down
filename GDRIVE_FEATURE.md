# Google Drive自动下载功能

## 功能概述

本系统新增了自动检测YouTube视频描述中Google Drive分享链接并自动下载的功能。当系统监控播放列表发现新视频时，会自动分析视频描述，检测其中的Google Drive链接，并自动下载这些文件。

## 核心功能特性

### 1. 智能链接检测
- **多格式支持**: 支持多种Google Drive链接格式
  - 标准文件分享: `https://drive.google.com/file/d/{id}/view`
  - 旧版链接: `https://drive.google.com/open?id={id}`
  - Google文档: `https://docs.google.com/document/d/{id}`
  - Google表格: `https://docs.google.com/spreadsheets/d/{id}`
  - Google演示: `https://docs.google.com/presentation/d/{id}`

- **智能去重**: 自动去除重复的文件ID
- **正则表达式匹配**: 使用高效的正则表达式进行链接识别
- **URL参数解析**: 支持从复杂URL参数中提取文件ID

### 2. 异步下载系统
- **并发下载**: 支持配置最大并发下载数
- **进度监控**: 实时跟踪下载进度
- **断点续传**: 支持大文件下载
- **文件大小限制**: 可配置最大文件大小限制
- **智能重试**: 下载失败自动重试，支持指数退避

### 3. 数据库集成
- **状态跟踪**: 完整记录每个文件的下载状态
- **关联管理**: 维护视频与Drive文件的关联关系
- **重试记录**: 跟踪重试次数和错误信息
- **时间戳**: 记录创建和更新时间

### 4. Telegram通知
- **检测通知**: 发现Drive链接时的通知
- **下载状态**: 下载成功/失败的实时通知
- **进度更新**: 大文件下载进度提醒
- **错误报告**: 详细的错误信息反馈

### 5. Alist集成
- **自动上传**: 下载完成后自动上传到Alist
- **目录管理**: 自动创建gdrive子目录
- **本地清理**: 上传成功后自动清理本地文件
- **路径配置**: 支持自定义上传路径

## 技术架构

### 核心模块

1. **gdrive_detector.py** - Google Drive链接检测器
   - `GoogleDriveDetector`: 主检测类
   - `DriveLink`: 链接信息数据类
   - 支持多种链接格式的正则表达式匹配

2. **gdrive_downloader.py** - Google Drive文件下载器
   - `GoogleDriveDownloader`: 异步下载器
   - `DownloadProgress`: 进度跟踪数据类
   - 支持并发下载和进度回调

3. **database.py** - 数据库扩展
   - `DriveFileInfo`: Drive文件信息数据类
   - 新增drive_files表和相关操作方法
   - 扩展videos表支持Drive链接信息

### 数据库架构

#### videos表扩展字段
```sql
ALTER TABLE videos ADD COLUMN gdrive_links TEXT;           -- JSON存储Drive链接
ALTER TABLE videos ADD COLUMN gdrive_status TEXT DEFAULT 'none';  -- Drive状态
ALTER TABLE videos ADD COLUMN gdrive_file_count INTEGER DEFAULT 0; -- Drive文件数
```

#### 新增drive_files表
```sql
CREATE TABLE drive_files (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    original_url TEXT NOT NULL,
    link_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    file_path TEXT,
    file_size INTEGER,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos (id)
);
```

## 配置选项

在`.env`文件中添加以下配置：

```bash
# Google Drive配置（可选）
ENABLE_GDRIVE_DOWNLOAD=true            # 启用Google Drive下载功能
GDRIVE_DOWNLOAD_PATH=/app/downloads/gdrive  # Google Drive文件下载路径
MAX_GDRIVE_FILE_SIZE=1073741824        # 最大文件大小限制（字节），默认1GB
MAX_GDRIVE_CONCURRENT=2                # 最大并发下载数
GDRIVE_UPLOAD_TO_ALIST=true            # 将下载的Google Drive文件上传到Alist
```

## 工作流程

1. **监控阶段**: 系统定期检查YouTube播放列表
2. **检测阶段**: 发现新视频时分析描述内容
3. **识别阶段**: 使用正则表达式识别Google Drive链接
4. **记录阶段**: 创建Drive文件记录到数据库
5. **下载阶段**: 异步下载Drive文件到本地
6. **上传阶段**: （可选）上传文件到Alist云存储
7. **通知阶段**: 通过Telegram发送状态更新
8. **清理阶段**: 定期清理已处理的文件

## 状态管理

### Drive文件状态
- `pending`: 待下载
- `downloading`: 下载中
- `completed`: 下载完成
- `failed`: 下载失败
- `uploaded`: 已上传到Alist

### 视频Drive状态
- `none`: 无Drive链接
- `detected`: 检测到Drive链接
- `downloading`: Drive文件下载中
- `completed`: 所有Drive文件处理完成
- `failed`: Drive文件处理失败

## 错误处理

### 重试机制
- 最大重试次数: 3次
- 重试间隔: 指数退避算法
- 失败记录: 详细错误信息存储

### 错误类型
- 网络错误: 连接超时、DNS解析失败
- 权限错误: 文件不可访问、需要权限
- 文件错误: 文件不存在、已删除
- 存储错误: 磁盘空间不足、路径无效

## 性能优化

### 并发控制
- 使用asyncio.Semaphore控制并发数
- 避免过多并发请求导致IP被封
- 智能队列管理

### 内存管理
- 流式下载大文件
- 及时释放文件句柄
- 控制内存使用量

### 网络优化
- 连接池复用
- 合理的超时设置
- 用户代理头设置

## 测试验证

运行测试脚本验证功能：

```bash
# 简单测试（无依赖）
python3 test_gdrive_simple.py

# 完整功能测试（需要安装依赖）
python3 test_gdrive_feature.py
```

## 安全考虑

### 文件类型限制
- 建议限制可下载的文件类型
- 扫描下载文件的病毒
- 限制文件大小

### 访问控制
- 仅下载公开可访问的文件
- 不支持需要登录的私有文件
- 遵守Google Drive使用条款

### 隐私保护
- 不存储敏感的用户信息
- 及时清理临时文件
- 保护下载文件的安全

## 监控和日志

### 日志记录
- 详细的操作日志
- 错误堆栈跟踪
- 性能指标记录

### Telegram通知
- 实时状态更新
- 错误告警
- 统计报告

## 依赖更新

新增的Python包依赖：

```
aiofiles==23.2.0      # 异步文件操作
requests>=2.31.0      # HTTP请求支持
```

现有的依赖包（已包含）：
- `aiohttp`: HTTP客户端
- `asyncio`: 异步编程
- `aiosqlite`: 异步SQLite

## 使用建议

1. **文件大小控制**: 建议设置合理的文件大小限制（如1GB）
2. **并发数量**: 根据网络条件调整并发下载数（推荐1-3个）
3. **存储空间**: 确保有足够的磁盘空间存储下载文件
4. **网络稳定**: 建议在稳定的网络环境下运行
5. **定期清理**: 定期清理已处理的文件释放空间

## 故障排除

### 常见问题

1. **链接检测失败**
   - 检查正则表达式是否匹配
   - 验证视频描述内容格式

2. **下载失败**
   - 检查网络连接
   - 确认文件访问权限
   - 验证存储空间

3. **上传失败**
   - 检查Alist配置
   - 验证上传路径权限
   - 确认网络连接

### 调试方法
- 查看详细日志
- 使用测试脚本验证
- 检查数据库状态
- 监控Telegram通知

## 未来扩展

### 可能的增强功能
1. **更多云存储支持**: OneDrive、Dropbox等
2. **文件格式转换**: 自动转换Google Docs到PDF
3. **批量操作**: 支持文件夹批量下载
4. **增量同步**: 智能同步更新的文件
5. **文件预览**: 生成文件预览和摘要

### 性能优化
1. **缓存机制**: 缓存文件元数据
2. **压缩下载**: 支持压缩文件传输
3. **多线程下载**: 文件分块并行下载
4. **智能调度**: 根据网络状况调整策略

这个Google Drive自动下载功能为YouTube视频下载系统增加了强大的扩展能力，能够自动处理视频描述中的附加资源，提供了完整的自动化解决方案。